# RotaryPosEmb 调优工作流

所有设备运行经 `task-submit --device auto` 申请一张卡；精度任务上限 120 秒，profiling 上限 90 秒，不进行多卡测试。编译、生成数据和分析不占卡。

1. 固定 tests/cases.json、随机种子、输入分布、theta、编译器和 SoC。公开模板只有一个用例，扩展集不冒充平台隐藏 15 用例。
2. 先验证模板接口、逐元素误差通过率、最大绝对误差、NaN/Inf、position=0、非对齐、输出边界哨兵。
3. 使用 ACL event 记录多批平均时间及 host 端总时间；event 包含 host 下发不足造成的空洞，小算子以 profiler 的 Task Duration 补充判断。Profiler replay 下的 event 时间不能作为原生性能。
4. `msprof op` 仅采集一次代表 kernel，收集 PipeUtilization、Memory、MemoryUB，保存原始 CSV 与摘要。
5. 根据指标形成假设，注明修改、预期变化和验收指标。每次修改重新编译、精度 gate、耗时比较、profiling 确认。失败或回退也保留记录。
6. 最终复测全覆盖集和模板原始脚本，打包单文件 kernel.asc，记录 SHA256、Git commit、硬件和工具链。

## 实验记录

### v0 基线

- Ascend910_9392，48 AIV，1850 MHz，CANN 9.0.0，dav-2201。
- FP32 频率在算子 host 入口实时生成，通过 launch 参数传入；所有 cos/sin 在设备内部生成。没有外部 cos/sin 输入或输入数据特化。
- 按 token/head 分组，前后半维分别通过 DataCopyPad 搬运，FP32 旋转，单次 FP16 输出舍入。
- `benchmarks/profiles/baseline` 保存原始采集 CSV。Task Duration=189.504 us；平均 AIV 时间184.304 us，VEC=26.62%，MTE2=30.91%，MTE3=32.26%，scalar=15.56%。每核 MTE2/MTE3 活跃带宽11.432/10.958 GB/s。
- 观察：短行 DMA 与串行流水开销明显，未达到带宽上限；对每个 head 复制 cos/sin 增加了向量指令与 scalar 下发。
- 扩展测试暴露 position=0 从 VECIN 直接经 MTE3 写回时缺少 MTE2→MTE3 依赖，新增 PIPE_ALL 同步修复；原失败结果保留 baseline_full.json。

### v1 假设

- 对 half_dim 为8倍数、dim≤512的形状走连续整行 DMA；其他形状保留 DataCopyPad 通用路径。
- 使用向量 repeat stride=0 广播同一 token 的 cos/sin，省去逐 head 展开。
- 输入/输出双缓冲和预取下一块，允许 MTE2/VEC/MTE3 重叠；不改变精度语义。
- 验收：全套精度通过，典型形状 event 时间降低；profile中 DMA 活跃带宽上升，总 Task Duration 降低。

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

### v1 反馈与 v2 假设

- 代表 FP16 形状 event 46.881 us（基线159.758 us），profile Task Duration 48.001 us（基线189.504 us）。
- MTE2/MTE3 平均活跃带宽从11.432/10.958提升到38.228/75.414 GB/s；每核 DMA 指令从171.67减少到22.33，额外事务流量下降。
- VEC 利用率从26.62%升至77.89%，当前更值得减少三角函数指令和低 mask 的重复调用。
- 单 head 长序列 profile=186.304 us，VEC=80.24%，scalar=45.32%，DMA 活跃带宽仅1.51/1.65 GB/s；每 token 的小计算和小搬运需要跨 token 合批。
- v2：融合 sin/cos 的范围缩减，四分之一角多项式和二倍角恢复代替重复的通用高阶 API。所有运算保持 FP32；CPU 对一百万个[-pi,pi]角度检查，sin/cos 最大绝对误差3.69e-7/5.37e-7，仍须设备全量精度 gate。
- 后续对 H=1 增加 token 合批，将三角函数的 SIMD mask 填满，并扩大 DMA 块。

### v2 / v3 结果

- v2 代表 FP16 原生 event=36.109 us，profile=37.341 us，VEC时间从v1的35.130 us下降到26.770 us；每核DMA活跃带宽保持37.56/76.87 GB/s。三角函数融合的预期收益得到验证。
- v3 H=1 跨 token 合批：sequence8192 原生event=14.755 us，基线250.050 us；batch128=9.145 us，基线130.398 us。
- v3 26个代表用例全部通过，包括新增D=512边界、合批尾块、合批全零/非有限输入。复查时修复了D/2=256的分区边界条件，避免对齐路径错误执行两次。
- runner复用单一ACL初始化，单卡批量执行多个测试；缩短设备占用时间，支持遍历16..1024全部偶数维度与两种dtype。

### v4 假设

v2仍有约77%的VEC占用。在对齐路径将四次乘法和两次加减改成两次乘法、两次MulAddDst，额外的负sin向量每token只生成一次。保持FP32；FMA舍入语义与分离乘加略有差异，必须重新通过完整精度测试和维度扫描，且profile应显示VEC时间下降才保留。

### 最终保留v4

VEC时间从v2的26.770 us降到20.612 us，典型FP16 profile=31.321 us。完整29例与1010项维度扫描全部通过；同卡交替原生测量确认DeepSeek FP16/FP32加速5.22/3.95倍，单head长序列16.57倍，大形状6.27倍。原始数据、测试方法与提交边界见performance.md。

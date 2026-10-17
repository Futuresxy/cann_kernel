# RotaryPosEmb 调优工作流

> 补充规则更新：下文 Host 生成频率的实现仅保留作历史实验。当前 V6/V4 暂停提交，需将全部数学计算移至 Device 并重新验证。[自动提交工作流及状态](cannjudge_workflow.md)。后续单卡任务每阶段上限 60 秒，串行执行。

当前所有设备运行经 `task-submit --device auto --max-time 60` 串行申请一张卡，每阶段上限 60 秒，不进行多卡测试。编译、生成数据和分析不占卡。后文为历史记录；当前分析与实验顺序见 [RoPE 算法与瓶颈优化路线](rope_optimization_strategy.md)。

1. 固定 tests/cases.json、随机种子、输入分布、theta、编译器和 SoC。公开模板只有一个用例，扩展集不冒充平台隐藏 15 用例。
2. 先验证模板接口、逐元素误差通过率、最大绝对误差、NaN/Inf、position=0、非对齐、输出边界哨兵；再用实际CANN启动API逐次确认每次run_kernel恰好一次启动。
3. 使用 ACL event 记录多批平均时间及 host 端总时间；event 包含 host 下发不足造成的空洞，小算子以 profiler 的 Task Duration 补充判断。Profiler replay 下的 event 时间不能作为原生性能。
4. 用非replay的msprof对15个本地回归形状各调用5次，要求设备任务总数75。之后`msprof op`仅采集一次代表kernel，收集PipeUtilization、Memory、MemoryUB，保存原始CSV与摘要。
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

### 提交边界修正：仅替换kernel.asc

撤销旧打包器对CMakeLists.txt、main.asc和run.sh的改写，不再在提交包或提交源码目录加入manifest。以原始附件的文件SHA256清单为固定基准；打包器和独立校验器要求仅kernel.asc变化，其余7个文件相同、无新增和删除。

内核通过float/half函数重载代替自写if constexpr，全部类型转换仍为同样的DataCopy/Cast指令。原始模板的CMAKE_CXX_STANDARD=14不改动；其ASC编译使用工具链默认语言模式。强制整个SDK按严格C++14编译的额外探测不作为验收要求，因为本机CANN头文件自身使用C++17特性。实际比赛工程验收只采用原模板提供的命令，不额外增加编译选项。

单卡0短任务执行原始run.sh、完整29例、1010项扫描和一次PMU采集，全部通过。典型FP16原生30.896 us，profile30.701 us，保留此前的分块与流水线优化。

### 连续相同编译日志后的上传版调整

两份平台编译日志逐字节相同，第一行均对应旧完整源码第289行。本地将旧源码截成末尾128行可复现相同pos_未定义报错，完整源码可在原模板编译；尚不能据此确认传输中的具体截断环节。

生成80行、16363字节的ROPE1743_COMPLETE_V2版本，仅合并空白和删除注释，归一化的非注释代码一致。用新源码重新构建并运行29例、1010项扫描和一次单卡PMU采集，全部通过；profile30.641 us，性能保持。发布包仍要求仅kernel.asc与原始模板不同。

### 单次启动约束修复：ROPE1743_SINGLE_LAUNCH_V3

平台反馈Expected 75 launches, got 85。排查发现dim>512时host频率分区循环包含两次launch，属于实现违规，与物理代码行数无关；之前仅做精度扫描与单kernel PMU采样，遗漏完整迭代启动数检查。

闭环：本地15形状×5调用，旧二进制用非replay msprof复现85个设备任务；移除host列分区启动循环，宽维度完整半维在一个kernel中完成。用128个FP32种子、3个比例和384个int16 ULP修正精确编码宽维度频率，不增加临时设备分配、预处理kernel或额外输入。小维度的DMA、合批、三角函数路径保持原有算法。

验证：原模板构建通过；单卡12的60秒任务完成37例精度、1010维度扫描、逐次启动API检查（222+2020次均为1）、设备计数旧85/新75、一次PMU。新版FP16原生30.518 us，PMU30.861 us。打包器必须同时通过精度、逐次启动与设备任务计数三个门槛。保留可读471行源码，不再使用80行压缩排版。

### 第二轮：PROFILED_V4

从平台通过的V3重新定基线，扩展为23个性能点、46个固定精度点和1010+456项扫描。保留跨token动态三角函数缓存、受限的连续搬运/Gather路径及宽维度向量恢复；淘汰对齐Gather、GM stride、FusedMulAdd替换等负收益方案。同卡ABBA、PMU、候选补丁、完整复现命令及一个旧版即存在的FP16极大幅度精度失败，见 [profiled_v4.md](profiled_v4.md)。本轮结果不能映射为平台隐藏15点的对应延迟。

### 第三轮：PROFILED_V5

以平台15点通过的0a4281f为基线，扩展33个性能形状和52个固定回归点。保留FP16原精度旋转、输出L2策略、宽维度单head合批、positions的Brcb广播和短维度多head连续搬运。修正本地runner输出对齐后，两版由同一runner重建并进行同卡ABBA，避免把测试环境变化当作优化收益。非replay L2计数解释输入缓存命中变化，PMU记录VEC/标量/MTE瓶颈变化。最终52+1010+456+672项通过，4588次逐次启动及75/75设备任务检查通过。完整结果、候选取舍、压力测试范围及复现命令见 [profiled_v5.md](profiled_v5.md)。


## 第四轮：平台反馈驱动回退

V5平台出现两个用例2.36%数值错误及测试13、14延迟回退，正式源码与提交包恢复为0a4281f的V4。新增与V4直接逐位比较的248项精度门槛；仅在独立实验中探索FP32连续DMA/Gather、宽维单head合批及UB预算选tile。保留有效局部收益与对照退化的原始数据，不将实验版替换正式包。报告见 [rollback_v4_round4.md](rollback_v4_round4.md)，复现入口为tools/validate_round4.sh。


## 第五轮：V6与平衡的同地址计时

保留V4的FP32数值路径，增加FP32队列直接计算、非对齐连续DMA、宽维单head合批，以及保持四乘两加减的单head positions向量化。增加同上下文、同GM地址的ABBA与交换源码后的BAAB，做A/A校准，并以普通runner的独立进程ABBA和PMU交叉验证。拒绝工作区偏移、标量UB positions缓存和无收益的角度向量化；手动positions缓冲复用错误由长流式测试检出并记录。2190项回归、414项逐位比较和两类单kernel启动检查通过。详见 [profiled_v6.md](profiled_v6.md)。


## 第七轮：V8 按并行度拆分与舍入保护

从符合补充规则的 V7 出发，以 paired profiler 和 PMU 区分小输入标量初始化与低核数瓶颈。小频率采用带 Q53 回退的 Q31 求值；只有行任务至多占四分之一可用 AIV 核时，才将配对旋转列分摊到更多核。淘汰对所有小工作集拆列及 width=64/128 全标量方案。3156 项参考回归、414 项 V4 逐位比较、6364 次逐次启动审计和75/75设备任务检查通过；详见 [profiled_v8.md](profiled_v8.md)。


## 第八轮：V9 初始化与编译实例隔离

以 V8 为合规基线，固定 33 点作为性能代表集。保留 Q31 快速求值加 Q53 回退、调用内根幂/相同 power 的 reciprocal 复用、二的幂指数缩放、64B 小工作区、首次 DMA 重叠和独立编译实例；淘汰 sqrt 多项式与两读宽维替换。新增 theta 与跨分派测试发现并修复 V8 在 theta 紧邻 1 时的精度问题。最终固定集加速约 1.030 倍，小输入局部改善，大流式持平；见 [profiled_v9.md](profiled_v9.md)。

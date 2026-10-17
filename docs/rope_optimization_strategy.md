# RoPE：从算法、数据流到 profiling 的优化路线

分析基线为 V9，源码 SHA256 `5917d3aaeb6969619852ba56cc7934f5bae66540295cf381fc0340bc50529ecc`。真实平台提交 **879119，15/15 Pass，48.45 分**；目标为官方成绩超过 70。宽维实验的局部收益没有换算成平台成绩。

本文按用户要求替代“先改指令、再寻找解释”的工作方式。当前阶段先做诊断，空闲的 Mac 自动提交 watcher 已停止，无未决平台提交；既有脚本及一分钟轮询设置保留。远端只使用现有环境，NPU 任务串行申请单卡，每次 `--max-time 60`。约束来源为 [AGENTIC.md](../AGENTIC.md)、[kernel_requirement.md](../kernel_requirement.md)、[forbidden.md](../forbidden.md)。

## 1. 算法里哪些工作可以减少

令 `N=B*S`、`K=D/2`、`e=sizeof(x.dtype)`，每个 token 的第 k 对维度：

```text
f[k]     = theta^(-k/K)
phi[t,k] = positions[t] * f[k]
c,s      = cos(phi), sin(phi)
yL       = xL*c - xR*s
yR       = xR*c + xL*s
```

数学上需要生成 K 个频率、N*K 对三角值，旋转 N*H*K 对输入。旋转每对为 4 次乘法加 2 次加减，即 `3*N*H*D` FLOPs；最低逻辑读写量为 `2*N*H*D*e + 4*N` 字节。仅旋转的算术强度约为 FP16 **0.75 FLOP/B**、FP32 **0.375 FLOP/B**，频率、三角函数、格式转换、UB 流量和控制指令另计。因此不能仅凭这两个数字断言整算子受 DRAM 限制。

| 可减少的工作 | 本题可用的方式 | 必须保留的条件 |
|---|---|---|
| 重复生成 sin/cos | 同一 token 的所有 head 复用一组 K 维系数；在单次 kernel 内按 token 合批 | 不把系数扩展成 `[N,H,D]` 后写入 GM；跨 head 的广播布局需与计算匹配 |
| sin/cos 重复范围缩减 | 联合范围缩减，联合求值或共享中间项；比较当前 sqrt/倍角恢复与其他 FP32 数值算法 | 先给误差预算，特别覆盖最大位置和舍入中点；不能只看平均误差 |
| 频率初始化 | 合理选择标量保护位路径、向量补偿路径；复用本次调用的 log(theta)、已生成数学中间项 | 每次调用在 Device 生成；不能 Host 算频率、硬编码结果或跨调用缓存 |
| 角度/旋转中间张量 | 频率→角度→sin/cos→旋转在 UB 内融合，算完直接写最终输出 | 一个调用只启动一个 kernel；不得靠额外预处理 kernel 分摊工作 |
| 旋转算术与读端口 | 在相同舍入语义下改用合适的乘加形式、原位更新和操作数布局 | 保存仍会被另一半使用的原输入，验证真实设备舍入和别名依赖 |

频率满足几何递推，但直接 `f[k+1]=round(f[k]*r)` 会积累误差；它还可能不等于参考的 FP32 `pow` 再 reciprocal。`exp(-log(theta)*k/K)` 也不保证相同舍入，最大位置会放大频率误差。任何递推、近似或更低阶多项式都先进入数值模型研究，不能直接替代当前路径。positions 是任意合法整数，不能假设连续位置后用 token 间递推跳过三角计算。

理想的 K 个频率是算法下界。V9 多数行分区路径实际每个 AIV 各算一次 K 维频率，即约 P*K；这用重复计算换来独立执行。单 kernel 内跨核共享频率需要合法空间、正确同步和额外流量，当前接口没有现成的安全全局屏障方案，不能把下界直接当作可实现收益。小输入的列分区则可能减少每核频率量，同时增加碎片 DMA，需比较两种成本。

## 2. 先解决数值链，再决定哪些计算能融合

输入/输出类型只有 **FP16、FP32**。int32 是 positions：其范围不超过 131072，转换到 FP32 的整数值可精确表示；需要分析的是读取、转换、广播的调度成本。三角函数内部的 int32 范围缩减另行统计，不能混为第三种输入算子。

分阶段记录：`FP32 exponent → FP32 power → reciprocal/frequency → FP32 angle → range reduction → sin/cos → rotation → output cast`。误差传播的一阶估计为：

```text
delta_phi ≈ p*delta_f + angle_rounding_error
|delta_y| ≲ (|xL|+|xR|)*(|delta_phi|+trig_error) + rotation_rounding_error
```

这只是诊断上界，最终必须运行原逐元素判定和最大误差判定。大幅值、抵消、极大位置、theta 接近 1、非二次幂 K 会暴露不同问题。对高幅值 FP16，输出一个 ULP 就可能远大于 0.1；FP32 中间误差很小也可能跨过 FP16 舍入中点，因此 matched_ratio 很高仍可能失败。

**已观察到的继承问题**：宽维补充集 `[1,137,17,1024] / FP16`，theta=10000，scale=60000，seed=175322，V9 和宽维候选逐位一致，但相对当前本地参考的最大绝对误差均为 **32.0 > 0.1**，matched_ratio 约 0.9999874。不是候选通过精度的证据。NumPy 与 libm 在这组 512 个 FP32 频率上逐位相同，也不能据此证明 Device 频率正确。证据见 [实验](../benchmarks/experiments/agentic/20261017T041419176110Z-vector-fma/wide/experiment.json)、[失败定位](../benchmarks/experiments/agentic/20261017T041419176110Z-vector-fma/wide/amplitude_diagnostic.json)。

下一步固定原始输入与哈希，用单独诊断副本导出 Device 各阶段结果，定位频率、角度、三角值、旋转或 cast 的第一处差异；再与当前 FP32 参考以及独立高精度数学计算对照，报告 ULP、绝对误差、舍入中点距离。诊断副本不计入性能、不提交；正式实现仍只输出 y。本地 `tools/suite.py` 的 golden 不是平台 golden 的证明：两种参考的差别应记录为未知项，不能改参考或阈值把失败变为通过。

### 已完成的分阶段归因

诊断导出最终半精度输出与原 V9 的2384896个元素逐位一致，且绑定同一输入及源码。主控的只读交叉检查见 [结果](../benchmarks/analysis/v9_stage_crosscheck.json)、[脚本](../tools/analyze_rope_stages.py)：48核全部频率和70144个角度均与当前FP32参考逐位相同；用导出的Device sin/cos重算后，有限FP32旋转、有限FP16输出均零位差。当前失败的第一处差异在三角求值链，不能归咎于频率、旋转指令舍入或写回。

59392个非零位置三角元素中，cos/sin最大绝对误差约5.36e-7/4.40e-7；最终817个输出绝对差超过0.1。原模板 [RotaryPosEmb.py](../templates/rotaryposemb_1743/scripts/RotaryPosEmb.py) 使用NumPy FP32中间链。这里还存在参考敏感性：保持同一FP32角度和分离FP32旋转，仅以FP64三角计算后舍入FP32作诊断，输出相对原参考仍有115个超过0.1、最大差32。此结果与远端80位十进制高精度分析一致；“更准确的实数函数”不自动等于“复现原FP32库的舍入”。没有替换验收golden或调整阈值。

后续数值研究先区分三个目标：复现当前FP32参考、满足数学误差界、符合真实平台golden。首先建立实际参考库的范围缩减/多项式模型，并证明设备可实现的舍入语义；不盲目追求更多多项式项或更高精度后宣称修复。NumPy 2.2.6 的[官方实现](https://raw.githubusercontent.com/numpy/numpy/v2.2.6/numpy/_core/src/umath/loops_trigonometric.dispatch.cpp)在有原生FMA支持时采用分区求值及范围缩减，超范围转标量库；这也说明库和硬件路径是参考行为的一部分。不能在当前NPU上把名称含FMA的API直接当作等价实现。

复现主控交叉检查时，用已有服务器Python/NumPy运行下面的CPU命令（需先生成冻结输入和阶段导出，不申请NPU、不修改输入）：

```bash
python3 tools/analyze_rope_stages.py \
  --data-dir build/rope_v9_system \
  --manifest benchmarks/diagnostics/rope_v9_system/input_manifest.json --cores 48
```

位置 0 按规格保持原输入位模式，包括有符号零及非有限值。一般旋转路径仍需覆盖 NaN/Inf、溢出、抵消和尾块；不能用降低 FP16 中间精度来掩盖成本。历史 FP16 直接旋转曾导致平台精度回退，见 [回退记录](rollback_v4_round4.md)。

## 3. V9 已经实现了什么，以及哪里仍有成本

源码为 [kernel.asc](../operators/rotary_pos_emb/kernel.asc)：`DeviceFrequencyChunk`/`ScalarFrequencies` 生成频率，`SinCosFp32` 联合三角求值；`run_kernel` 依据公开 shape/dtype 和数值条件选择互斥路径。

| 路径/形状族 | 当前数据流 | 首先应解释的剩余成本 |
|---|---|---|
| 小工作集，部分核空闲 | `SmallRotary` 按成对频率列分区，短行 DMA | 每核初始化、核数/列分区收益、短 burst、短 mask、控制下发 |
| 对齐 FP16，多 head | `AlignedRotary`/`LargeAlignedRotary`：连续 DMA→FP32 Cast→两份工作区旋转→FP16 Cast→写回；动态 trig cache | UB 读写、Cast、广播/乘加读端口、head tile 与 trig batch 的容量竞争 |
| 对齐 FP32，多 head | `DirectFloatRotary` 在输入/输出队列直接计算，复用输出区作 trig scratch | 已经省去了输入/输出额外 FP32 拷贝；继续分析队列生存期、乘加读端口和 scratch 复用 |
| H=1、长序列 | `BatchedRotary`/`BulkPositionRotary` 跨 token 合批 | 没有 H 倍三角复用，trig 吞吐和 token 合批、positions DMA/广播更重要 |
| 短非对齐、多 head | `PackedRotary`/`HeadTileRotary` 连续搬运、UB Gather/重排 | Gather 吞吐、对齐填充、有效 lane、重排字节数与减少的 DMA 事务 |
| 其余非对齐 | 通用 `Rotary` 按半行布局处理 | 碎片 DMA、块间距、尾部 mask、频繁同步；需要单独 PMU，不从对齐点外推 |
| 大流式输入 | 连续分块、预取/队列、FP32 旋转 | 实际 DRAM/L2 读写、MTE 事务粒度和重叠；初始化通常已被摊薄 |

**D1024 FP16、N=256、H=32 的具体模型**：V9 先得到 3 个 head group，再均衡为 tileHeads=11，768 个 job 分到 48 核；工作区 size=11264、stride=11272。输入双缓冲、单输出缓冲、两份 FP32 工作区共 157760B；频率及 trig cache 共 32768B，trig batch=5；合计 190528B（不含潜在额外分配，实际还需核对 scratch 复用）。单纯增大 tile、加缓冲或扩大 cache 会相互挤占容量。

按当前连续 job 分区，每核接触 6 个 token，48 核合计 288 次 token 访问，理想为 256：核边界导致最多这一模型中的 **12.5%** trig token 重复，另有 batch=5 的余批。不是 12.5% 端到端收益承诺；若改为整 token 分区，必须核对 head 并行度、负载均衡、最后一批、DMA overlap。这个例子提供可解释的 tiling 研究对象，避免无模型地遍历参数。

**搬移要分层计量**：GM↔UB 字节与事务数、UB↔VEC 的读写、UB 内重排/Cast、同步等待分别记录。减少一个 `DataCopy` 不代表减少一遍 DRAM；融合也可能多读第三个操作数、增加 bank 冲突或延长队列占用。FP32 已经直接用队列，不能再给它计算一次并不存在的“去掉输入拷贝”收益。

通用非对齐 `Rotary::Process` 还有可直接从源码核对的成本：每个新 token 将 cos/sin 各复制到另外 `tileHeads-1` 行；计算第一半输出后，又从输入队列重新 LoadFp32 原第一半来计算第二半；每个 job 末尾执行 PIPE_ALL，输入/输出队列深度均为1。这些是明确存在的操作，尚未证明各自占主耗时。后续可以比较“保留两半输入、独立输出/临时区、只广播 K 维系数”的布局，预期减少系数展开和一次半输入转换；同时核对额外 trig 区的 UB 预算、broadcast 读端口、尾 mask 与指令数。预取/双缓冲应作为另一项实验，不能与布局重写一起改变后只报告一个加速数。

## 4. Profiling 给出的证据与还缺少的证据

同一 V9 SHA 的代表 PMU 为 [tiny](../benchmarks/profiles/agentic_r1_v9_tiny/summary.json)、[DeepSeek FP16](../benchmarks/profiles/agentic_r1_v9_deepseek/summary.json)、[wide FP16](../benchmarks/profiles/agentic_r1_v9_wide/summary.json)、[stream FP16](../benchmarks/profiles/agentic_r1_v9_stream/summary.json)。这些为 replay 诊断，不用作正式加速比。

| 本地代表 | AIV时间/us | VEC活跃 | scalar活跃 | MTE2活跃 | MTE3活跃 | 当前证据支持的方向 |
|---|---:|---:|---:|---:|---:|---|
| tiny | 2.089 | 19.0% | 76.5% | 8.6% | 5.7% | 初始化、标量控制和并行度；不是带宽优先 |
| DeepSeek FP16 | 16.104 | 71.0% | 59.5% | 61.1% | 28.8% | 计算与搬运重叠的混合场景，需看关键依赖 |
| D1024/H32 FP16 | 30.523 | 86.3% | 31.3% | 25.1% | 13.9% | 向量计算、UB操作数流和转换 |
| 大流式 FP16 | 757.845 | 47.1% | 29.4% | 93.7% | 63.9% | 搬运关键路径、事务和缓存流量 |

各管线可重叠，占比不能相加到 100%，VEC 活跃占比也不等于有效 lane 占比或峰值算力利用率。平均每核时间不等于全 kernel 尾核时间。`scalar_vector_stall` 需结合指令依赖和事件解释，不能直接称作“空跑”。

当前 `SinCosFp32` 静态含34次基础 API 调用：11 Muls、10 Mul、7 Adds、3 Sub、2 Cast、1 Sqrt。这个清单提示应研究范围缩减、sqrt/倍角恢复和数据依赖，但不是34条硬件指令的结论。H=1 时每对输入都需要这套三角生成；H大时可摊到多个head，优化三角求值的收益上限不同。先量化这些阶段和全核临界路径，再决定是否研究新的多项式。

本地大流式 `[4,8192,128,64] / FP16` 最低 X/Y 流量为 1GiB，原生约 842.786us，对应逻辑有效带宽约 **1.274TB/s**。这不是测得的 DRAM 峰值：重复输入可能命中 L2。必须用实际内存计数区分冷数据与稳态缓存，不能据此断言到达硬件上限。小的 DeepSeek 工作集逻辑有效带宽更高同样不意味着 DRAM 更快。

下一轮采集只补缺项，首先复用现有数据：

1. 按 entry 和循环统计实际汇编的向量、标量、mask 设置、Cast、Gather、barrier/事件数量；记录 repeat、stride、实际有效元素数，区分静态条数与动态执行次数。
2. 给频率初始化、角度/三角、转换、旋转、写回建立数据流图和临界依赖。诊断微 kernel 可用来排除假设，但不能把隔离阶段耗时相加当总耗时，也不能提交不完整算子。
3. 查看各核 job/字节数和最大/最小时间，判断尾核不平衡；结合 DMA 数据量/指令数确认 burst 是否过碎。
4. 只有工具已支持时，补相应计数器和源码/指令定位；若当前版本无指标，报告缺失，不通过装软件或改系统获取。

## 5. 历史结果决定哪些方向不能直接重试

| 方案 | 已有结论 | 再研究所需新证据 |
|---|---|---|
| Q53 log 提前终止 | 数值相同；固定33点几何平均0.995493×，已拒绝 | 新汇编/新的关键路径解释，不能仅凭少几条运算 |
| 用硬件 FMA 提取 TwoProd 残差 | 本设备 vmadd/vmla 不是所需 IEEE 单次舍入，探针失败 | 已明确不适用，不能把 API 名称当数值保证 |
| 频率补偿累积改 MulAddDst | 合并加速约1.00223×，描述性区间跨1，VEC时间不降 | 新的读端口/关键路径证据；不重复原试验 |
| 宽维旋转改变操作数数据流 | D1024/H32 FP16 31.981→29.2805us，**加速1.092×，耗时减少8.44%**；VEC 26.344→23.669us | 收益补丁保留，但先修复/澄清继承精度问题，再完整验收；不能泛化到 FP32 |
| 手工 mask/Counter 复用 | round3 已有 mask_trig/mask_all，历史收益小，未推广 | 先比对 V9 实际汇编与老实验，证明当前仍有新增冗余 |
| 通用 bank padding、positions 标量 UB缓存、宽泛 Gather、全量拆列 | 多次回退或无稳定收益 | 必须指出不同的布局/瓶颈，引用旧补丁，避免改名重试 |
| FP16 中间旋转、sqrt替换余弦 | 出现精度失败/平台回退 | 误差界和阶段定位通过之前不进入性能候选 |

乘加读端口和地址布局的限制见 [官方 FusedMulAdd 文档](https://asc.gitcode.com/api/SIMD-API/basic_api/memory_vector_compute/composite_compute/FusedMulAdd.html)。外部 mask 管理见 [CANN 9.0 SetVectorMask](https://www.hiascend.com/doc_center/source/en/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0096.html)。这些提供假设依据；本机探针、当前源码和端到端测量决定是否适用。

## 6. 接下来按这个顺序执行

| 阶段 | 工作及进入条件 | 要交付的证据/停止条件 |
|---|---|---|
| P0 数值归因 | 固定继承失败输入，逐阶段对照；先 CPU 分析，再最小单卡诊断 | 第一处误差、ULP/舍入边界、真实参考语义的已知/未知；阈值和 golden 不改 |
| P1 分支画像 | 补 FP32、H=1、非对齐代表的缺失 PMU/汇编；建立按 family 的访存/指令模型 | 每族一个有来源的瓶颈结论；若证据不足只补诊断，不改算法 |
| P2 宽维 FP16 | P0 解决后，保留已有原位乘加收益；研究整 token 分区与 batch 容量的权衡 | 一次只改变一个因素；VEC/重算量预期与实测一致，完整精度通过 |
| P3 H=1/非对齐 | H=1 关注联合 trig 和 token合批；非对齐关注短DMA与UB重排 | 先测有效 lane、Gather/事务开销；根据模型选择一种替换，禁止直接铺开所有 shape |
| P4 小输入/流式 | 小输入关注初始化与可用核；流式关注实际流量和流水重叠 | 优先级由可获收益及官方15点反馈更新，不能只优化已知快的本地点 |

每个实验开始前必须写清 **输入族与数值域、源码/二进制哈希、旧实验差异、瓶颈证据、改动、预计降低的成本、可能回退点、验收指标**。阶段结束给 accepted/rejected/inconclusive 及理由。局部改动失败保留补丁和原始数据，不立即换一个猜测；先用结果修正模型。

验收分两层：先保持原精度阈值，执行相关数值域与尾块/guard/position0/非有限输入覆盖；再同输入、同上下文/地址、非 replay 的 ABBA+BAAB 测量，关注目标族和独立对照族，必要时用 A/A 判断噪声。最后对拟提交的准确源码执行完整精度、单次启动、设备 task 计数和原模板检查。诊断副本的结果不能替代提交源码的证据。

## 7. 平台闭环如何服务于瓶颈分析

15 个隐藏点的 shape 未知，不以延迟猜测其 dtype/shape，也不按测试编号分派实现。公开 shape 族用来理解硬件映射；真实提交只替换 kernel.asc，并逐字节校验回读、记录源码 SHA 和唯一提交 ID。每分钟查询同一次提交直到 15 点结果完整；编译/运行错误保存页面定位，不伪造分数。成功后读取“华华的世界”的成绩、排名和差距。

目前与最优时延比最大的点为9、5、6、4、7，但这些编号不是优化分支。按当前四舍五入时延和公开评分公式估算，单把这5点耗时减半，总分约62.82；这5点全部达到最优，其余不变才约71.03。故一个局部9%收益不足以支持70分预期，需要多族收益与平台反馈共同验证。排名会变化，官方分数仍以成绩页为准。

达到本地验收后再恢复 Mac watcher：候选按 SHA 去重、提交→60秒轮询→收集15点/错误→Git回传→通知同一远端 Codex→下一轮诊断。精度未通过时不发布 ready。远端既有会话已收到本次方法调整，先交诊断报告；不启动额外调优进程或改远端环境。

可复现的 CPU 分析命令：

```bash
.local/cannjudge/venv/bin/python tools/analyze_rope_workload.py
```

输出 [v9_workload_model.json](../benchmarks/analysis/v9_workload_model.json) 包含固定33点的算法工作量、逻辑字节数、4个源绑定 PMU、宽维 UB/分区模型及15点分数机会估计；脚本校验当前源码必须为上述 V9 SHA，不运行设备或浏览器。

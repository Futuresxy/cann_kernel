# RotaryPosEmb 第二轮 profiling 优化（2026-10-16）

本轮基线是已经通过平台的可读 V3（Git `b32d3a6`），不是最初的慢实现。最终源码标记 `ROPE1743_PROFILED_V4`，采用按形状选择的三角函数批量缓存、非对齐数据连续搬运/UB Gather、宽维度向量恢复及分块。提交仍只替换 `kernel.asc`，模板其他7个文件逐字节不变。

15个隐藏测试点没有 shape/dtype/theta，单个延迟不能唯一反推输入。以下23点是公开示例形状与本地扩展矩阵，不冒充平台隐藏点，也不据此预测平台分数。长流式输入改善有限，单 token/短序列差异约0.1微秒；没有所有形状均数倍加速的结论。

## 同卡最终性能

Ascend910_9392，48 AIV，CANN9.0.0，dav-2201。通过 task-submit 仅申请物理卡0，依次执行 baseline/candidate/candidate/baseline。每个进程每点先5次预热，再5次采样；每进程取5次设备 Task Duration 的中位数，两轮进程再取中位数。无 msprof op replay。每个进程共230次调用和230个设备 kernel，ABBA共920个。输入、源码、二进制哈希与每轮样本保存在 `benchmarks/results/profiled_v4_paired.json`，原始 op_summary.csv 保存在四个 `benchmarks/profiles/profiled_v4_paired_*` 目录。

| 本地用例 | shape | dtype | V3 / us | V4 / us | 加速比 |
|---|---|---|---:|---:|---:|
| tiny | [1, 8, 1, 16] | float32 | 2.660 | 2.490 | 1.07× |
| unaligned_half | [2, 16, 3, 24] | float16 | 4.920 | 4.880 | 1.01× |
| deepseek_half | [2, 512, 128, 64] | float16 | 29.641 | 20.141 | 1.47× |
| deepseek_float | [2, 512, 128, 64] | float32 | 33.401 | 23.521 | 1.42× |
| sequence8192 | [1, 8192, 1, 64] | float32 | 14.250 | 14.110 | 1.01× |
| large_half | [4, 1024, 128, 64] | float16 | 97.692 | 60.121 | 1.62× |
| heads256 | [1, 32, 256, 128] | float16 | 12.180 | 11.590 | 1.05× |
| aligned_d512_half | [1, 7, 17, 512] | float16 | 13.550 | 8.340 | 1.62× |
| wide_half | [1, 7, 17, 1024] | float16 | 21.200 | 14.140 | 1.50× |
| prefill_h32_d128_half | [2, 512, 32, 128] | float16 | 28.140 | 18.810 | 1.50× |
| prefill_h32_d128_float | [2, 512, 32, 128] | float32 | 27.980 | 19.031 | 1.47× |
| prefill_h32_d256_half | [2, 512, 32, 256] | float16 | 43.281 | 34.201 | 1.27× |
| prefill_h8_d64_half | [2, 512, 8, 64] | float16 | 19.530 | 11.580 | 1.69× |
| prefill_h3_d24_half | [2, 512, 3, 24] | float16 | 34.861 | 6.730 | 5.18× |
| prefill_h32_d30_float | [2, 512, 32, 30] | float32 | 72.601 | 19.700 | 3.69× |
| prefill_h32_d96_half | [2, 512, 32, 96] | float16 | 25.990 | 16.421 | 1.58× |
| prefill_h32_d1024_half | [1, 256, 32, 1024] | float16 | 65.932 | 53.821 | 1.23× |
| prefill_h32_d1024_float | [1, 256, 32, 1024] | float32 | 68.821 | 57.241 | 1.20× |
| stream_h128_d64_half | [2, 4096, 128, 64] | float16 | 225.225 | 208.474 | 1.08× |
| stream_h32_d128_float | [2, 4096, 32, 128] | float32 | 212.875 | 206.974 | 1.03× |
| single_token_many_heads | [1, 1, 256, 128] | float16 | 7.021 | 7.090 | 0.99× |
| short_s16_h32 | [1, 16, 32, 128] | float32 | 7.001 | 7.110 | 0.98× |
| narrow_head_long | [1, 8192, 4, 16] | float16 | 104.373 | 21.621 | 4.83× |

上表采用设备实际执行时间。`profiled_v4.json` 另保留原生 ACL event 与 host 耗时，它们包含下发空洞；PMU replay 中的 event 耗时不用于上述性能比较。matrix.json 的 minimum_io_gbs 是读写有效张量字节数除以设备时间，不等同于实测 HBM 带宽，未扣除缓存影响。

## 瓶颈、假设和采集反馈

以下为 msprof op 单 kernel 的各核平均流水时间，单位微秒。不同流水可以重叠，不可直接相加推导总耗时。原始逐核 CSV、命令及源码/二进制哈希保存在对应 profiling 目录；PMU采集用于解释变化，与上表的非replay计时分开。

| 场景 | 指标 | V3 | V4 | 反馈 |
|---|---|---:|---:|---|
| DeepSeek FP16 | VEC | 20.612 | 13.147 | -36.2% |
| DeepSeek FP16 | MTE2 | 8.697 | 9.885 | +13.7% |
| DeepSeek FP16 | MTE3 | 4.338 | 4.689 | +8.1% |
| DeepSeek FP16 | scalar | 11.495 | 10.237 | -10.9% |
| H32/D30 FP32 | VEC | 21.950 | 12.089 | -44.9% |
| H32/D30 FP32 | MTE2 | 24.762 | 1.862 | -92.5% |
| H32/D30 FP32 | MTE3 | 21.249 | 1.128 | -94.7% |
| H32/D30 FP32 | scalar | 12.982 | 6.290 | -51.5% |
| H32/D1024 FP16 | VEC | 19.872 | 22.884 | +15.2% |
| H32/D1024 FP16 | MTE2 | 8.157 | 7.517 | -7.8% |
| H32/D1024 FP16 | MTE3 | 9.020 | 4.660 | -48.3% |
| H32/D1024 FP16 | scalar | 37.614 | 34.210 | -9.1% |

1. 对齐 D64：旧版 VEC 占约73%，逐 token 产生很短的三角函数向量。假设批量处理角度可以减少短指令调用。每核缓存最多16个有效 token 的 cos/sin/负sin，频率宽度按8个FP32元素对齐，并限制缓存到本核的有效 token 区间。VEC平均20.612→13.147us；MTE2指令数22.33保持不变，说明主要收益来自向量计算而非少搬输入。没有固定位置表，位置仍实时从设备输入读取。
2. 非对齐 D30：旧版 MTE2/MTE3时间24.762/21.249us，短行 DMA 比较零碎。将多个 token 连续装入 UB，再 Gather 分离前后半维、展开 cos/sin、重组输出。最终 MTE2/MTE3为1.862/1.128us，每核对应指令数43.67→6.33，验证了减少 DMA 事务的假设。索引在每次 kernel 内构造，构造成本已包含在最终计时中。
3. 宽维度 D1024：旧版 scalar37.614us，约占平均AIV时间52%。把频率种子/比例/ULP修正恢复转为向量 Cast/Add，同时扩大 tile、减少输出缓冲、调整工作区间隔。scalar下降到34.210us，改善有限；MTE3降为4.660us。最终设备时间提升约1.23倍，仍有标量和调度开销，不能宣称宽维度瓶颈已经消除。

## 候选与淘汰依据

候选源码以相对于 b32d3a6 的补丁、源码SHA256保存在 `benchmarks/experiments/round2/`；每个候选的精度结果与计时存放于 `benchmarks/results/round2_*`。矩阵profile用于探索选路，最终结论以上述同卡ABBA为准。未通过的早期结果同样保留。

| 候选 | 观察 | 决策 |
|---|---|---|
| auto_sync | 仅移除显式PIPE_V，收益较小；编译器默认依赖同步下精度通过 | 在无复杂别名的路径保留 |
| cache_trig/cache_auto/cache_tight | 跨token合批三角函数；缩紧频率pitch和有效区间后多数对齐场景更快 | 保留cache_tight作为小中维度路径 |
| cache_fmadd | FusedMulAdd替换MulAddDst，D64无改善 | 淘汰 |
| packed | D24/D30及窄维度长序列显著改善；H32/D128等对齐场景反而更慢 | 只在非对齐小维度与D16少head长序列选用 |
| aligned_tuned | 两份工作区、输出单缓冲、大tile在D512更快，在D64更慢 | 仅用于D≥512对齐路径 |
| wide_vec/wide_tuned | 频率恢复向量化，配合tile和修正值打包后宽维度更快 | 合并到宽维度路径 |
| head_packed/head_split | 用索引Gather把两个D64 head打包满64个FP32 lane，重排成本超过算术收益，profile约61us | 淘汰 |
| head_striped | GM分开搬前后半维，短行stride DMA更慢 | 淘汰 |
| direct_dma | 对齐DataCopy替换DataCopyPad没有稳定收益 | 淘汰 |
| head_mask | GatherMask和UB stride copy仍慢，5点精度通过，DeepSeek低重复原生event约74us | 初筛淘汰，没有继续占卡采PMU |
| merged | 最终受限选路，46例通过、完整矩阵无明显大幅回退 | 保留为V4 |

部分选路在极小输入下并不触发，避免初始化和 Gather 的成本压过收益。rotate-half和复数乘法只是同一组实部/虚部方程的不同写法，算术操作数不因此自动减少；本轮通过FP32 Mul/MulAddDst、频率复用和搬运布局实现收益。

## 查表方案的取舍

已实现的是当前调用内的动态UB小表：输入position→批量生成FP32 cos/sin→按token/head复用，离开当前调用就失效。位置、theta改变不会复用旧值，也不增加外部输入或预处理kernel。

没有采用遍历0..131072全部位置的预生成大表：一次调用不一定用到这些位置，不同theta/dim需要重建；单kernel规则下跨核生成和安全共享整表也增加成本。固定步长的角度LUT加插值尚未实现或实测，不能把它列为已经被profiling否定的方案。若继续研究，必须同时测表生成、UB/GM访存、误差和端到端时间，不能只比较查一次表与算一次sin的局部耗时。

## 正确性与已知精度限制

最终V4验收：

- 46个固定回归用例全部通过；与赛题相同的逐元素容差、99%比例及max_abs_error门槛同时检查。
- 16..1024的505个偶数维度×两dtype，共1010项全部通过。
- 16..128的57个偶数维度×两dtype×head数1/3/7/32，共456项全部通过。包含尾块、极大位置、混合零位置及NaN/Inf。
- 输出前后哨兵与position=0位模式检查全部通过。
- 实际启动API逐次审计：46×6 + 1010×2 + 456×2 = 3208次调用，每次恰好1个kernel。
- 非replay设备profiling：75次调用→75个设备任务，ABBA性能矩阵每轮230/230。
- 将V4放进原始模板，其余7文件原样，原始CMake工程编译成功；原始main及verify_result.py通过，最大误差2.623e-6。编译日志中仅有SDK已有的GM_ADDR host类型属性警告。

有一个必须保留的失败：`tests/precision_stress_cases.json` 中 seed=88、x幅度60000、shape=[1,37,17,64]、FP16、位置覆盖0..131072。平台通过版V3和本轮V4均得到匹配比例0.99997515898，但最大绝对误差32，大于0.1，因此均判FAIL。相邻FP16值在这个幅度可能相差32，近似三角函数或FP32乘加的微小差异可能使输出跨过舍入边界；这是原因推断，未做逐指令误差归因。原始记录为 `round2_platform_stress.json` 与 `profiled_v4_precision_stress.json`。所有普通测试仍严格保留原阈值，没有放宽规则。

该压力用例独立列为已知失败诊断，未计入上面的46项成功数。它说明不能宣称对所有FP16输入幅度都满足赛题阈值；它也不是本轮优化新引入的回归。平台隐藏数据的分布未公开，最终仍需平台验证。

修复过的开发问题也有保留：packed早期版本在尾块零位置Select上失败，发现CANN9.0 CompareScalar的count按64个FP32元素处理完整repeat，改为向上取整比较长度、只写有效输出后，混合零位置和456项扫描通过。中间一次设备脚本被修改时已经开始执行，导致shell语法失败、未运行合并版；随后使用独立固定脚本重跑成功。未将该任务计入性能或验收。

## 复现与提交

CPU编译、生成数据、解析结果均不占NPU；设备阶段串行使用task-submit的一张卡，每个阶段60秒上限；原模板main固定卡0，单独申请卡0并限制30秒。没有多卡或常驻任务。

```bash
source /usr/local/Ascend/ascend-toolkit/latest/set_env.sh
# 重建一个探索候选，自动核对源码SHA256，不改当前正式kernel
python3 tools/replay_experiment.py packed
# 重建平台通过版基线
bash tools/build_revision.sh b32d3a6 platform_v1
# 正式版的编译与分阶段单卡复测，见README的完整命令
bash tools/build.sh
bash tools/build_launch_audit.sh
python3 tools/suite.py --generate-only
python3 tools/suite.py --sweep --generate-only
python3 tools/suite.py --packed-sweep --generate-only
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled.sh --phase correctness'
python3 tools/suite.py --cases-file tests/performance_cases.json --generate-only
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled.sh --phase paired'
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled.sh --phase pmu'
# 独立诊断命令预期可能返回1，失败结果不覆盖标准验收数据
task-submit --device auto --max-time 20 --run 'bash tools/device_suite.sh --cases-file tests/precision_stress_cases.json --label profiled_v4_precision_stress --warmup 1 --repeat 3 --batches 1'
# kernel须先提交Git；打包器验证精度/API启动数/设备启动数/源码哈希
python3 tools/package.py --result profiled_v4 --launch-profile profiled_v4_launches
python3 tools/verify_submission.py
```

正式源文件 815行，39093字节，SHA256 `2acfbd5c205915280dfe6818d8217a78f08a9fb769ad3a1843b4f58a73eb3d58`。首行 `// ROPE1743_PROFILED_V4`，末行 `// END_ROPE1743_V4`。完整纯文本与只含kernel.asc的ZIP，和工程ZIP内源码字节完全一致。

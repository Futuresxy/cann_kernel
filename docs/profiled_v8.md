# V8：按并行度分派，保持 Device 完整计算

V7 的平台反馈显示，小输入回退，而部分大输入改善。隐藏 15 个测试点的 shape 和源码导出哈希未知，因此没有从耗时猜出测试点，也没有为其编号写分支。原始反馈保存在 `benchmarks/results/platform_user_v7_20261016.json`，仅作用户提供的性能记录。

本轮基线是已发布、符合新增 Device 计算规则的 V7，SHA256 `1c66f36807ae1540c173c6dd95141079cf94c76af1aaa578478a4f2393cfc32b`。最终 V8 源码 SHA256 为 `c9dd01c9addb702d01964676f2e753f383fc31b21a9a4834fee0e7b754aa7c2a`，1773 行、83836 字节，首尾标记分别为 `ROPE1743_PROFILED_V8`、`END_ROPE1743_V8`。

## Profiling 如何决定改动

在 Ascend910_9392、48 AIV、CANN 9.0 上，V7 的 tiny 用例每核标量执行占比约 81%，VEC 约 15%。这类小输入首先受频率初始化开销影响，扩大搬运 tile 并不能解决。

`[1,1,256,128] / float16` 的 V7 只启动 3 个核。每核 VEC 时间约 3.85us，等待向量约 1.73us，指令等待约 1.55us。V8 将完整的旋转列对分摊到 32 个核，每核 VEC 时间约 0.68us，等待向量约 0.47us，指令等待约 0.14us。分派后的标量初始化成为更明显的瓶颈。

以上是 operator-profiler replay 的 PMU 诊断，原始 CSV 和元数据位于 `benchmarks/profiles/round7_{v7,occupancy}_{tiny,single_token_many_heads}/`。不把 replay 中的 event 时间用作最终加速比。性能选择使用无 replay 的同地址 ABBA 与交换源码后的 BAAB。

## 保留的实现

Host 只根据 shape、dtype、theta 的合法数值范围和可用核数决定分块，传入 theta 标量并执行一个互斥的 kernel 分支。频率、角度、正余弦和旋转都在该次 Device kernel 中生成。

小输入先估算每个 tile 至多 32 heads 时的行任务数。只有这些任务至多使用四分之一的可用 AIV 核，才增加按列分区；每个分区包含前后半维的对应列，最小搬运单位按 32 字节对齐。列数、分区数、UB 容量和头数共同限制拆分规模。核数已经够用时继续使用 V7 连续搬运和跨 head 复用路径。所有输出元素均由唯一分区写入。

频率的短向量路径增加带区间保护的 Q31 求值：先计算与原路径同一个数学函数的低成本近似；若误差区间碰到 FP32 舍入中点，回到原 Q53 保护位路径。接受区间外的近似仍舍入为相同的 FP32 power，再使用原整数舍入 reciprocal。二的幂宽度可直接生成精确的指数分数，省去逐列除法。较宽向量保留 V7 的 FP32 高低位算法。

正余弦、角度和旋转仍保持 FP32 指令顺序，没有采用降低旋转精度或 FMA 重排。position=0 保持输入的原始位模式，包括 NaN/Inf 和负零；这来自算子恒等性质，不依赖数据生成规律。新增搬运补齐的 UB lane 显式初始化。

所有数学小表均在当前 Device 调用内由通用数学展开生成。没有预先保存的 RoPE 频率、位置角度、旋转结果或 Host 向量，没有跨调用缓存、全局工作区、预处理 kernel、空 kernel 或预热识别。

## 数值区间与验证

Q31 路径使用 exp2 在 `[-1/64,1/64]` 上的三阶通用多项式。参考 [Arm exp2f 实现](https://raw.githubusercontent.com/ARM-software/optimized-routines/master/math/exp2f.c) 与 [系数定义](https://raw.githubusercontent.com/ARM-software/optimized-routines/master/math/exp2f_data.c)；数学系数不是预计算的算子输出。

沿当前整数指令计算，log 从 Q53 截断及乘积截断引入不到 2 个 Q31 自变量单位；多项式导数上界约 0.701，乘 range-reduction 中心值小于 2，将这部分误差放大至不到 2.804 个单位。Horner 截断误差传播、中心值舍入及最终乘积截断合计不到 3.6 个单位；区间交界的多项式误差、Q53/Q61 误差及归一化再乘 2 后，仍小于采用的 32 个单位保护区间。FP32 power 舍弃 8 位，舍入中点余数为 128：余数落在闭区间 `[96,160]` 时使用 Q53；只接受这个保护区间以外的结果。最终 reciprocal 的原始 ties-to-even 舍入不变。

CPU 数值模型比较了 75 个 theta、所有 8..128 宽度，共 608025 个非首列频率：455622 个被 Q31 接受、152403 个回退，接受结果与 Q53 的频率位模式差异为零。这是模型证据，不代替设备验证。模型和记录位于 `benchmarks/experiments/round7/numerical_model/`：

```bash
python3 benchmarks/experiments/round7/numerical_model/adaptive_all.py
```

最终设备检查保持原精度阈值，未修改判题、计时或参考计算：

| 检查 | 通过数 |
|---|---:|
| 固定 FP16/FP32 回归及逐次启动审计 | 52/52 |
| theta、频率及大位置边界 | 256/256 |
| 新增小输入、非对齐、特殊值、近消去 | 544/544 |
| D=16..1024 全部偶数维度，两种类型 | 1010/1010 |
| 跨 token 合批 | 456/456 |
| head/宽维/搬运路径 | 672/672 |
| 补充对齐及尾块 | 166/166 |
| 与已通过平台的 V4 直接逐位比较 | 414/414，零变化元素 |

合计 3156 项设备参考精度检查，逐次审计 6364 次真实 runtime launch 均为每调用一次启动。独立无 replay profiler 记录为 75 次调用、75 个 Device kernel task。V4 仅用作历史输出对照，其 Host 频率表不符合新增规则，不用于本次提交。局部报告不表示隐藏用例已通过。

## 最终同地址双顺序结果

`benchmarks/results/profiled_v8_balanced.json` 记录 105 个形状，8400 次调用对应 8400 个 Device task。每个实现每形状各取 4 个采样块的中位数，再合并 ABBA/BAAB；输入与 GM 分配在每个进程内共享，反向采集检查相同输入哈希。单位 us；几何平均加速比为 1.115×，这不是比赛得分。

| shape / dtype | V7 | V8 | 加速比 |
|---|---:|---:|---:|
| [1,8,1,16] / float32 | 3.280 | 3.060 | 1.07× |
| [2,16,3,24] / float16 | 5.480 | 5.290 | 1.04× |
| [2,512,128,64] / float16 | 18.671 | 17.990 | 1.04× |
| [1,1,256,128] / float16 | 8.650 | 5.770 | 1.50× |
| [1,1,1,128] / float32 | 6.950 | 3.510 | 1.98× |
| [1,1,1,256] / float16 | 7.630 | 4.050 | 1.88× |
| [1,256,32,1024] / float16 | 32.540 | 32.531 | 1.00× |
| large_stream_half | 844.327 | 843.247 | 1.00× |

没有把所有变化写成收益。极小 `[1,1,1,16] / float32` 为 3.960→4.140us、`[1,1,32,32] / float32` 为 4.150→4.310us，约有 0.16–0.18us 回退；大多数宽向量和大工作集基本持平。不同采样顺序中这些极短 kernel 存在波动，未据此匹配具体 shape 增加分支。前期 56 点筛选的独立双顺序数据保留为 `round7_occupancy_balanced`，不与最终矩阵混算。

复现最终性能采集前先在 CPU 重新生成性能矩阵，避免之前精度套件覆盖同名输入。构建两个交换源文件的 runner 后，单卡执行：

```bash
# 将实际的冻结 V7 kernel.asc 放在 build/tuning_round7/v7/。
bash tools/build_paired.sh build/tuning_round7/v7 operators/rotary_pos_emb build/tuning_round7/occupancy_forward
bash tools/build_paired.sh operators/rotary_pos_emb build/tuning_round7/v7 build/tuning_round7/occupancy_reverse
python3 tools/suite.py --cases-file tests/round7_performance_cases.json --generate-only
task-submit --device auto --timeout 0 --max-time 60 \
  --run 'bash tools/validate_profiled_v8.sh --phase shared'
```

## 被淘汰的方案与复现

最初对所有小工作集拆列，单 token 有收益，但 `[1,32,32,64] / float16` 从约 6.48us 回退到 7.96us。收紧为按空闲核数决定后，这类场景继续走连续搬运路径。将 width=64 或 128 全部转为标量频率计算也更慢，因此保留宽向量计算。所有初筛、对照和补丁保存在 round7 实验目录；没有给只做 CPU 构建的候选填写设备性能结论。

```bash
python3 tools/replay_experiment.py occupancy --round round7 --source-only
bash tools/build.sh
bash tools/build_launch_audit.sh
bash tools/validate_profiled_v8.sh --phase prepare
# 每条等待完成并释放设备，再开始下一条；timeout=0 仅表示排队不限时。
for phase in correctness precision math small sweep packed_sweep path_sweep aligned_audit; do
  task-submit --device auto --timeout 0 --max-time 60 \
    --run "bash tools/validate_profiled_v8.sh --phase $phase"
done
```

本机 task-submit 的默认客户端 600 秒等待超时会取消尚未运行的任务，故显式设置 `--timeout 0`。NPU 占用仍由 `--max-time 60` 严格限制。本轮所有任务串行、单卡完成。

## 参考实现与适用边界

[FlashInfer 的 RoPE](https://github.com/flashinfer-ai/flashinfer/blob/main/include/flashinfer/pos_enc.cuh) 根据 token 网格与硬件并发度选择 head 并行，启发本轮在行并行不足时增加列并行。[FlashAttention 的 Triton 实现](https://github.com/Dao-AILab/flash-attention/blob/main/flash_attn/ops/triton/rotary.py) 使用 token/head 分块和向量搬运。[CANN RotaryPositionEmbedding](https://gitcode.com/cann/ops-transformer/tree/9.0.0-beta.1/posembedding/rotary_position_embedding) 按布局分派并广播同一位置的三角值。后两者接口可接收外部 cos/sin，不能照搬为本题的预计算表输入；本实现仍在唯一 kernel 内完成全流程，也没有照搬第三方 kernel 源码。

本轮主要解决小输入的初始化和核利用率。大输入保留 V7 已验证的搬运和计算方式，未宣称带宽瓶颈已消除或平台 15 点全面加速。正式上传只替换 `kernel.asc`；提交目录其余 7 个文件必须与最初附件逐字节相同。

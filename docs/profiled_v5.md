# RotaryPosEmb 第三轮优化：PROFILED_V5（2026-10-16）

> 已撤回：用户平台反馈两个用例出现2.36%数值错误，测试13、14延迟上升。当前正式源码和提交包已回退到V4。下文为历史本地实验记录，不能作为V5可提交或平台精度通过的依据。

基线是平台15点精度通过、用户提供新成绩的V4（Git 0a4281f），不是最初版本。平台15个shape仍未公开，记录于 `benchmarks/results/platform_feedback_v4.json` 的成绩与下述本地33个shape不做对应推断。

本轮保留FP16原精度旋转、输出L2策略、宽维度单head合批、positions向量广播和短维度多head连续搬运。提交仍只替换kernel.asc，原始模板其他7文件不变。CPU编译、分析和报告均不占卡，设备任务经task-submit串行单卡运行，每个任务不超过60秒。

## 最终性能：同卡、同runner、同输入

硬件Ascend910_9392，48 AIV，CANN9.0.0，dav-2201。按 baseline/candidate/candidate/baseline 交替；每进程每点5次预热+5次采样，取Task Duration中位数，两轮再取中位数。原23点与新增10点分别完成一次同卡ABBA，共1320次实际调用/1320个设备kernel，没有operator-profiler replay。

修正了本地runner的输出哨兵偏移：原128字节偏移改为512字节，保持输出512字节对齐。基线和候选用同一新runner重建，配对脚本核对runner及输入哈希。因此最终表不能直接与以前128字节偏移的绝对时间混用。下表在 `profiled_v5_paired.json` / `profiled_v5_extended.json` 中有逐轮样本，原始CSV位于同名前缀的profiling目录。

| 本地用例 | shape | dtype | V4 / µs | V5 / µs | 加速比 |
|---|---|---|---:|---:|---:|
| tiny | [1, 8, 1, 16] | float32 | 2.500 | 2.450 | 1.02× |
| unaligned_half | [2, 16, 3, 24] | float16 | 5.070 | 4.840 | 1.05× |
| deepseek_half | [2, 512, 128, 64] | float16 | 20.691 | 16.170 | 1.28× |
| deepseek_float | [2, 512, 128, 64] | float32 | 24.130 | 23.460 | 1.03× |
| sequence8192 | [1, 8192, 1, 64] | float32 | 14.660 | 12.250 | 1.20× |
| large_half | [4, 1024, 128, 64] | float16 | 60.802 | 44.981 | 1.35× |
| heads256 | [1, 32, 256, 128] | float16 | 12.611 | 11.580 | 1.09× |
| aligned_d512_half | [1, 7, 17, 512] | float16 | 8.790 | 8.200 | 1.07× |
| wide_half | [1, 7, 17, 1024] | float16 | 14.770 | 13.830 | 1.07× |
| prefill_h32_d128_half | [2, 512, 32, 128] | float16 | 19.900 | 15.210 | 1.31× |
| prefill_h32_d128_float | [2, 512, 32, 128] | float32 | 19.920 | 18.910 | 1.05× |
| prefill_h32_d256_half | [2, 512, 32, 256] | float16 | 35.751 | 22.430 | 1.59× |
| prefill_h8_d64_half | [2, 512, 8, 64] | float16 | 11.980 | 11.380 | 1.05× |
| prefill_h3_d24_half | [2, 512, 3, 24] | float16 | 6.920 | 6.760 | 1.02× |
| prefill_h32_d30_float | [2, 512, 32, 30] | float32 | 20.101 | 19.791 | 1.02× |
| prefill_h32_d96_half | [2, 512, 32, 96] | float16 | 17.171 | 13.280 | 1.29× |
| prefill_h32_d1024_half | [1, 256, 32, 1024] | float16 | 57.111 | 40.660 | 1.40× |
| prefill_h32_d1024_float | [1, 256, 32, 1024] | float32 | 60.681 | 57.181 | 1.06× |
| stream_h128_d64_half | [2, 4096, 128, 64] | float16 | 176.243 | 103.752 | 1.70× |
| stream_h32_d128_float | [2, 4096, 32, 128] | float32 | 173.344 | 109.093 | 1.59× |
| single_token_many_heads | [1, 1, 256, 128] | float16 | 7.300 | 7.100 | 1.03× |
| short_s16_h32 | [1, 16, 32, 128] | float32 | 7.050 | 7.000 | 1.01× |
| narrow_head_long | [1, 8192, 4, 16] | float16 | 21.971 | 21.691 | 1.01× |
| unaligned_h128_d30_half | [2, 1024, 128, 30] | float16 | 641.173 | 102.972 | 6.23× |
| unaligned_h128_d30_float | [2, 1024, 128, 30] | float32 | 434.019 | 103.082 | 4.21× |
| prefill_d192_half | [2, 512, 32, 192] | float16 | 27.100 | 20.750 | 1.31× |
| prefill_d384_float | [2, 512, 32, 384] | float32 | 58.021 | 57.121 | 1.02× |
| large_stream_half | [4, 8192, 128, 64] | float16 | 845.887 | 830.197 | 1.02× |
| large_stream_float | [2, 8192, 64, 128] | float32 | 848.217 | 833.986 | 1.02× |
| sequence_d1024_half | [1, 8192, 1, 1024] | float16 | 201.494 | 106.422 | 1.89× |
| unaligned_h64_d126_half | [2, 512, 64, 126] | float16 | 111.972 | 111.912 | 1.00× |
| unaligned_h64_d254_float | [2, 512, 64, 254] | float32 | 162.594 | 162.613 | 1.00× |
| sequence_d1024_float | [1, 8192, 1, 1024] | float32 | 201.614 | 116.023 | 1.74× |

约1.00～1.09倍的差异视为基本持平，不据此宣称显著加速。大于缓存容量的两组512MiB输入仅改善约2%，仍有明显的访存限制。固定输入预热后的结果也不等同于整个网络或持续更换输入的吞吐。

## Profiling闭环

以下PMU为单次kernel的各核平均流水时间，流水可重叠，不能直接相加。两版均使用修正后的runner；PMU replay的计时不替代上表的非replay配对计时。原始命令、源码和二进制哈希随CSV保存。

| 场景 | 指标 | V4 | V5 |
|---|---|---:|---:|
| DeepSeek FP16 | VEC / µs | 13.147 | 9.466 |
| DeepSeek FP16 | scalar / µs | 9.433 | 9.476 |
| DeepSeek FP16 | MTE2 / µs | 9.480 | 9.742 |
| DeepSeek FP16 | MTE3 / µs | 4.390 | 5.149 |
| DeepSeek FP16 | MTE2指令/核 | 22.33 | 22.33 |
| H128/D30 FP16 | VEC / µs | 67.397 | 91.765 |
| H128/D30 FP16 | scalar / µs | 45.929 | 18.004 |
| H128/D30 FP16 | MTE2 / µs | 302.839 | 13.688 |
| H128/D30 FP16 | MTE3 / µs | 292.421 | 6.579 |
| H128/D30 FP16 | MTE2指令/核 | 342.33 | 43.67 |
| H1/D1024 FP32 | VEC / µs | 148.980 | 76.809 |
| H1/D1024 FP32 | scalar / µs | 102.121 | 47.331 |
| H1/D1024 FP32 | MTE2 / µs | 51.697 | 14.840 |
| H1/D1024 FP32 | MTE3 / µs | 25.181 | 9.030 |
| H1/D1024 FP32 | MTE2指令/核 | 171.67 | 35.15 |

L2策略另外使用**非replay**硬件计数器采集，同样检查实际调用数等于设备任务数。采集计数器本身会影响时间和缓存活动，下面只解释命中率，不将其耗时混入ABBA表。

| 场景 | V4读取命中率 | V5读取命中率 | V4输出写分配 | V5输出写分配 |
|---|---:|---:|---:|---:|
| stream_h128_d64_half | 0.075% | 99.99990% | 262173 | 0 |
| stream_h32_d128_float | 0.071% | 99.99990% | 262192 | 0 |

这验证了输出写分配挤出输入缓存的假设。仅绕过输出后，输入工作集可留在L2；同时绕过输入会失去这一收益，已淘汰。operator-profiler replay会改变缓存状态，探索阶段曾出现与稳态计时相反的结果，相关CSV仍保留，不用来宣称该策略对冷输入也同样加速。

## 保留的算法与硬件映射

1. **FP16多head旋转**：对dim为32倍数、heads≥16、tokens≥128的FP16输入，频率/角度/cos/sin先以FP32生成，然后将系数转换为FP16，直接在输出队列完成旋转。省去整块输入和结果的FP32工作区转换；较大维度也减少向量repeat数。没有降低FP32输出的计算精度。UB按 `8*size+26*cacheSize+4*freqSize` 字节控制在188KiB内。
2. **输出L2策略**：连续路径中单个输入张量≥128MiB时，仅输出采用bypass，输入保持默认缓存。64MiB阈值与FP16计算优化合并后，会使能整体放入缓存的中等张量变慢，因此最终提高到128MiB。硬件缓存保持数据一致性，算子没有保存跨调用的计算结果。
3. **宽维度单head合批**：原来D>512没有采用Batched路径。现在通过WideFrequencies统一处理，把每token调度变成按UB预算合批；旋转由4Mul+2加减改为2Mul+2MulAddDst，工作区从三份减为两份。宽频率的1292字节编码不变，每次调用仍只启动一个kernel。
4. **小维度单head位置向量化**：按块DMA装载positions，将int32转换为FP32，用Brcb/规则Copy广播位置，再乘频率生成角度。position=0先产生位掩码，输出时Select原始输入，减少逐token标量读和分支，保留NaN/Inf与有符号零的位模式。
5. **多head非对齐短行**：dim≤64、heads>32、tokens≥128时连续装载整块head数据，在UB内Gather拆分和重组，避免GM上大量短行stride DMA。更宽维度的Gather开销较高，因此没有推广到所有非对齐shape。原先heads≤32的token合批路径继续保留。

所有路径只依据真实shape/dtype选择，positions在设备读取。没有离线输出、外部sin/cos、额外预处理kernel、全局同步kernel或临时GM频率表。

## 检索与实验取舍

[Ascend官方API优化实践](https://www.hiascend.com/developer/techArticles/20241107-1)给出了mask复用与Counter模式的方法；实测单独改写mask收益很小，未全局替换。UB间隔32字节、D64规则向量Copy重排也没有得到收益，已淘汰。不是看到API名称或理论吞吐提高就直接合并。

[Ascend搬运优化实践](https://www.hiascend.com/developer/techArticles/20240906-1)强调搬运粒度与对齐；本轮据此修正计时runner，并验证了连续搬运方案。[SetL2CacheHint文档](https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/82RC1alpha002/API/ascendcopapi/atlasascendc_api_07_00033.html)提供缓存模式接口，最终选择由非replay硬件计数与同卡计时共同决定。

还检查了[官方RotaryPositionEmbedding](https://gitcode.com/cann/ops-transformer/tree/9.0.0-beta.1/posembedding/rotary_position_embedding)、[vLLM Ascend RoPE](https://github.com/vllm-project/vllm-ascend/blob/main/vllm_ascend/ops/triton/rope.py)和[FlashAttention RoPE](https://github.com/Dao-AILab/flash-attention/blob/main/flash_attn/ops/triton/rotary.py)的按token/head切分与缓存复用思路。这些接口接收外部cos/sin，不能直接替换本题接口。QKV/Norm/Attention图级融合需要本题没有的输入，当前文件内融合的是三角函数、转换、旋转和搬运。

rotate-half与复数乘法对应同一组实数方程，改变写法不自动减少算术量。固定角度LUT加插值本轮仍未实现或实测，不能将它写成已经被profiling否定的方案；本轮的小表是每次调用内部生成的cos/sin缓存。CANN9.0实际SDK的MulCast只支持half到int8/uint8，不能按其他版本API名称假设存在float/half乘法转换融合。

13组探索候选及最终阈值调整都保存在 `benchmarks/experiments/round3/` 的补丁与manifest中；原始失败/负收益记录位于 `benchmarks/results/round3_*` / `benchmarks/profiles/round3_*`。这些探索多数使用旧128字节偏移runner，最终速度结论以上面的512字节对齐ABBA为准。

## 正确性与提交验收

- 52个固定用例通过，包含新分支、大缓存工作集、NaN/Inf和零位置。
- 1010个维度扫描、456个token合批扫描、672个新增路径扫描通过，共2190项。
- 比较函数仍采用原赛题阈值，FP16逐元素容差、99%匹配比例及最大绝对误差门槛均未放宽。固定集最低匹配比例约99.592%，新路径扫描最低约99.644%。
- 4588次实际启动API审计，每次调用恰好启动一个kernel；15个本地分支覆盖形状×5调用的设备记录为75/75。另有1320次ABBA设备任务计数校验。
- 原始模板工程编译与原始main/verify_result.py运行通过，最大误差2.623e-6；只有kernel.asc改变，另外7文件逐字节相同。

按用户要求，极大幅度压力点保留为诊断，不以其阻塞本轮性能优化。新FP16快路径使用赛题允许的输入精度旋转；常规集通过不表示任意FP16幅度都满足最大绝对误差门槛。平台隐藏15点需要用本版本再次复测。

## 复现

README给出编译和各阶段的完整命令。基线须用当前runner重建：`bash tools/build_revision.sh 0a4281f platform_v4`。探索候选可用 `python3 tools/replay_experiment.py half_wide --round round3` 重建，不改正式kernel。

硬件计数器的非replay采集示例，必须通过单卡限时队列：

```bash
task-submit --device auto --max-time 45 --run 'bash tools/profile_matrix.sh --binary build/rope_runner --label my_l2 --cases-file tests/performance_cases.json --metrics L2Cache'
```

打包要求当前kernel已提交Git，并且主精度、API启动、设备计数与三个额外扫描均对应当前源码/二进制：

```bash
python3 tools/package.py --result profiled_v5 --launch-profile profiled_v5_launches --extra-result profiled_v5_sweep --extra-result profiled_v5_packed_sweep --extra-result profiled_v5_path_sweep
python3 tools/verify_submission.py
```

源码1201行，58681字节，SHA256 `217729cabc7de8ff0230343bcec7133fff9bc2157da1d52b7089e09c5755b7a9`。首行 `// ROPE1743_PROFILED_V5`，末行 `// END_ROPE1743_V5`。上传ZIP仅含完整kernel.asc，纯文本与工程ZIP中的源码字节相同。

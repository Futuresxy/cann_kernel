# V7：Device 频率生成与片上内存优化

本轮从 V6 源码 `d04a5eed…` 出发，按新增规则将整个频率计算迁入 Device。V4/V6 只作为历史精度和性能对照，其 Host 频率表不再符合提交要求。平台隐藏 15 点未知，本报告只记录本地实验，不将本地 shape 对应到平台测试编号。

最终候选为 `ROPE1743_PROFILED_V7`，源码 SHA256 `1c66f36807ae1540c173c6dd95141079cf94c76af1aaa578478a4f2393cfc32b`，1562 行，结尾 `// END_ROPE1743_V7`。提交仍只替换 kernel.asc，原模板其余 7 文件逐字节保留。

## 本轮保留的改动

Host 只按 shape、dtype、UB 容量及并行度决定分块和启动配置，将 theta 标量传给 Device。未读取输入数据，未生成或传递频率向量。每次 run_kernel 恰好启动一条 Device 分支。

Device 每次重新生成频率。直接使用 FP32 Ln/Exp 在最大位置下产生明显角度误差，因此使用带保护位的 log2/exp2 计算，最终将 power 和 reciprocal 舍入到 FP32；角度、正余弦、旋转继续使用 FP32。小频率向量使用标量整数保护位路径，较宽向量使用 FP32 高低位对。标量与向量的分界来自本地初始化耗时的对照，按向量长度选择，不按具体测试数据选择。

32 项通用 exp2 表在本次 Device 调用内部由数学展开生成，用于缩小多项式自变量。它不包含预先计算的 RoPE 频率、位置角度或旋转结果，不从 Host 传入，也不跨调用保留。宽向量使用 Gather 获取通用数学近似的局部系数。数值算法参考 [Arm powf](https://raw.githubusercontent.com/ARM-software/optimized-routines/master/math/powf.c) 与 [exp2 多项式系数](https://raw.githubusercontent.com/ARM-software/optimized-routines/master/math/exp2f_data.c) 的区间缩减思路；没有硬编码某个 theta、D 或测试点的频率和 ULP 修正表。

依据初始化阶段 VEC 占比较高的 profiling，通用 exp2 表改由 Device 标量流水用 Q61 保护位生成，再拆为 FP32 高低两部分。与向量反复开方建表相比，多数初始化敏感场景减少约 1us。频率工作区优先复用当前调用尚未使用的 UB 区域；小工作区才按容量证明申请临时缓冲，避免为了初始化缩小主计算 tile。

对齐 FP16 多 head 路径移除未使用的第三工作数组。D≤64 且 head tile 足够大时，在当前调用内部将 cosine 展开为两半，用整行向量乘法减少短 mask 指令。保持后续 FP32 乘加顺序，不引入 FP16 旋转。释放的 UB 用于更大的 head tile；对最后一组 head 重新均衡分块，减少大尾块不平衡。

对齐 FP32 路径直接在输入、输出队列中计算，覆盖更多短序列，减少整块 UB 复制。短 token 数保留更小的 tile，防止并行度下降。缓存策略继续使用默认值。

## 闭环与被淘汰方案

所有候选保存在 `benchmarks/experiments/round6/`，补丁基于 manifest 绑定的 V6 Git 版本，可通过 `tools/replay_experiment.py NAME --round round6 --source-only` 按哈希重建。源码、实际二进制、输入、runner 哈希均随结果保存。

| 实验 | 反馈与决定 |
|---|---|
| device_exp | 仅 16/52 通过，直接 Ln/Exp 的误差在大位置放大；淘汰 |
| device_dd | 51/52 通过，wide_theta_half 最大误差 0.1704 超过 0.1；淘汰 |
| device_dd_bias / fixed_nofence | 52/52 通过，但向量初始化过长；继续削减数学指令 |
| device_table_fast | 改用本次调用生成的通用 exp2 表，保留为后续基础 |
| cos_full | 移除冗余 UB、减少短向量指令，保留 |
| scalar_small | 小宽度保留；width=64 标量路径更慢，因此回到向量路径 |
| sin_split | 拆开乘加未取得稳定收益，DeepSeek FP16 更慢；淘汰 |
| dma_plain | 对齐路径换用普通 DataCopy 没有稳定收益；淘汰 |
| selected_scratch | 已通过完整回归，后续由 scalar_table 的更低初始化开销替代 |
| scalar_table | 通用表移至标量流水，保留为最终 V7 |

`round6_screen_*` 是不同进程的初筛，不能把数个百分点的缓存变化当作优化收益。最终结论使用同进程、同 GM 地址的 ABBA 和交换源码后的 BAAB，两个实现每个 shape 各有 4 个块中位数。每块 5 次预热和 5 次采样。

早期反向采集中，runner 完成全部 shape，但导出的 task 数为 1240/1320；另一轮为 560/600，普通 runner 的 75 次检查也出现过 70 条导出记录。计数检查拒绝整份采集，未放宽预期次数或用缺失数据算加速比。原始无效采集保存在 `benchmarks/validation/profiled_v7/profile_collection_failure/`。这些采集中 stream/task 编号反复复用；本地普通 runner 和 paired runner 改为整个采集共用一条 stream 后，A/A 采集记录完整，8 点相同源码的差异约在 2% 内。编号复用是排查方向，不将它写成已证明的驱动根因。比赛模板 main.asc、计时和校验脚本未修改。

## 最终同地址双顺序结果

Ascend910_9392、48 AIV、CANN 9.0、dav-2201。下表由最终完整采集生成；单位 us。历史 V6 是性能对照，不能按新增规则重新提交。

| 场景 | shape / dtype | V6 | V7 | 加速比 |
|---|---|---:|---:|---:|
| tiny | [1, 8, 1, 16] / float32 | 2.330 | 3.250 | 0.72× |
| unaligned_half | [2, 16, 3, 24] / float16 | 4.930 | 5.431 | 0.91× |
| deepseek_half | [2, 512, 128, 64] / float16 | 20.460 | 18.770 | 1.09× |
| deepseek_float | [2, 512, 128, 64] / float32 | 19.640 | 19.691 | 1.00× |
| sequence8192 | [1, 8192, 1, 64] / float32 | 12.850 | 12.910 | 1.00× |
| large_half | [4, 1024, 128, 64] / float16 | 60.441 | 53.411 | 1.13× |
| heads256 | [1, 32, 256, 128] / float16 | 12.160 | 9.080 | 1.34× |
| aligned_d512_half | [1, 7, 17, 512] / float16 | 8.460 | 8.971 | 0.94× |
| wide_half | [1, 7, 17, 1024] / float16 | 12.650 | 9.970 | 1.27× |
| prefill_h32_d128_half | [2, 512, 32, 128] / float16 | 19.440 | 16.470 | 1.18× |
| prefill_h32_d128_float | [2, 512, 32, 128] / float32 | 17.791 | 14.840 | 1.20× |
| prefill_h32_d256_half | [2, 512, 32, 256] / float16 | 35.121 | 27.081 | 1.30× |
| prefill_h8_d64_half | [2, 512, 8, 64] / float16 | 11.691 | 11.971 | 0.98× |
| prefill_h3_d24_half | [2, 512, 3, 24] / float16 | 6.900 | 7.591 | 0.91× |
| prefill_h32_d30_float | [2, 512, 32, 30] / float32 | 19.960 | 20.150 | 0.99× |
| prefill_h32_d96_half | [2, 512, 32, 96] / float16 | 16.941 | 15.911 | 1.06× |
| prefill_h32_d1024_half | [1, 256, 32, 1024] / float16 | 55.521 | 32.630 | 1.70× |
| prefill_h32_d1024_float | [1, 256, 32, 1024] / float32 | 53.901 | 34.281 | 1.57× |
| stream_h128_d64_half | [2, 4096, 128, 64] / float16 | 200.654 | 200.134 | 1.00× |
| stream_h32_d128_float | [2, 4096, 32, 128] / float32 | 200.514 | 197.494 | 1.02× |
| single_token_many_heads | [1, 1, 256, 128] / float16 | 4.350 | 8.630 | 0.50× |
| short_s16_h32 | [1, 16, 32, 128] / float32 | 6.160 | 7.891 | 0.78× |
| narrow_head_long | [1, 8192, 4, 16] / float16 | 21.910 | 21.391 | 1.02× |
| unaligned_h128_d30_half | [2, 1024, 128, 30] / float16 | 99.992 | 100.222 | 1.00× |
| unaligned_h128_d30_float | [2, 1024, 128, 30] / float32 | 100.112 | 100.322 | 1.00× |
| prefill_d192_half | [2, 512, 32, 192] / float16 | 26.560 | 20.520 | 1.29× |
| prefill_d384_float | [2, 512, 32, 384] / float32 | 44.251 | 30.430 | 1.45× |
| large_stream_half | [4, 8192, 128, 64] / float16 | 845.927 | 844.677 | 1.00× |
| large_stream_float | [2, 8192, 64, 128] / float32 | 845.827 | 842.726 | 1.00× |
| sequence_d1024_half | [1, 8192, 1, 1024] / float16 | 110.493 | 88.112 | 1.25× |
| unaligned_h64_d126_half | [2, 512, 64, 126] / float16 | 111.793 | 109.213 | 1.02× |
| unaligned_h64_d254_float | [2, 512, 64, 254] / float32 | 161.823 | 154.134 | 1.05× |
| sequence_d1024_float | [1, 8192, 1, 1024] / float32 | 118.072 | 95.292 | 1.24× |

最终完整记录为 `profiled_v7_balanced.json`，使用显式 seed 的 `tests/round6_performance_cases.json` 在 CPU 单独生成输入后采集。正反向各 1320 个 device task，合计 2640/2640。两组 512MiB 流式输入基本持平；tiny 增加约 0.92us，short_s16_h32 增加约 1.73us，单 token 多 head 明显变慢。小形状承担 Device 频率生成成本，上述退化没有从报告中剔除。

大工作集若基本持平会如实保留。小形状还承担 Device 频率初始化成本，不宣称所有形状都比含 Host 数学的历史版本更快。

## 最终硬件反馈

最终 PMU 原始 CSV 与源码/二进制哈希在 `profiled_v7_tiny/` 和 `profiled_v7_prefill_h32_d1024_half/`。这是 replay 诊断，不用于计算前表加速比。D1024 多 head 的 VEC 占用约 86%，后续继续优化应减少旋转与三角向量指令；小形状则有明显的频率初始化标量成本。初始化优化没有解决大流式工作集的访存代价。

## 精度和规则验证

使用原赛题误差阈值，输出前后 512B 哨兵，零位置逐位保持原输入，包括 NaN/Inf 和有符号零。不调整 golden 或精度阈值。

- 2612 项参考精度检查全部通过：基础 52、完整偶数 D 扫描 1010、packed 456、路径扫描 672、额外对齐/消减检查 166、数学矩阵 256。
- 52 项基础集另以审计二进制运行，逐次验证实际调用只启动一个 kernel；扩展 2560 项也都有逐次启动审计。所有输出哨兵和零位置原始位模式检查通过。
- 与平台通过的 V4 直接逐位比较：248+166=414 项全部通过，新增差异元素为 0。最终普通 runner 与 V4 对照使用同一份持久 stream harness，源码及二进制哈希绑定于结果。
- msprof 的 15 项本地回归 ×5 次调用为 75/75 device kernel，与平台未公开的 15 个 shape 没有对应关系。
- 按原模板 CMake 配置编译成功；原始 main.asc 在单卡 0 上运行公开样例并通过原始校验脚本，最大绝对误差 2.6226e-6。提交目录与 ZIP 均只有 kernel.asc 相对模板发生变化。
- 本地发布/合规工具的 17 项 CPU 检查通过。浏览器相关代码本轮未改动，也没有在真实平台自动提交。

普通 runner 修复 stream 生命周期后，基础与逐位对照重新运行并保存新 harness 哈希；扩展扫描还保留修复前同一最终 kernel 的真实二进制证据。它们使用的 kernel SHA 相同，未将旧 kernel 的结果用于新源码。

扩展数学矩阵为 8 个 theta × 16 个 D × 两种 dtype，共 256 项，包含 theta<1、非对齐、最大位置及 scale=32 输入。414 项逐位对照直接运行旧 V4 与候选二进制，比对约 2.42 亿元素，NaN payload 不要求相同，其他输出位均参与比较。它是额外检查，赛题参考误差判断仍独立执行。

源码规则审查在 `benchmarks/validation/profiled_v7/compliance.json`，绑定最终源码 SHA。V7 的通用数学系数、当前调用内的频率/三角复用不替代输入相关计算，不保留跨轮缓存，没有离线结果表或附加 kernel。最终打包还校验源码 Git 提交、普通与审计二进制、75 次设备任务、原模板 7 文件及全部扩展结果。

## 复现

```bash
bash tools/build_revision.sh 0a4281f platform_v4
bash tools/build.sh
bash tools/build_launch_audit.sh
bash tools/validate_profiled_v7.sh --phase prepare
# 每阶段完成并释放卡后再开始下一阶段；每条仅申请单卡
for phase in correctness math sweep packed_sweep path_sweep aligned_audit precision; do
  task-submit --device auto --max-time 60 --run "bash tools/validate_profiled_v7.sh --phase $phase"
done
# 按 round6 manifest 重建性能基线和候选后，CPU 构建正反向 runner
bash tools/build_paired.sh 基线目录 候选目录 build/tuning_round6/final_forward
bash tools/build_paired.sh 候选目录 基线目录 build/tuning_round6/final_reverse
python3 tools/suite.py --cases-file tests/round6_performance_cases.json --generate-only
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled_v7.sh --phase shared'
```

设备阶段始终通过 task-submit 串行申请一张卡，各阶段设置 60 秒上限，完成即释放。编译、输入生成、归档和分析在 CPU 完成。PMU replay 只分析流水和事务，不混入最终原生 task 耗时。

# V6：基于V4的FP32计算与搬运优化

> 2026-10-15 补充规则：本版本 Host 频率表需要迁移到 Device，暂停推荐提交。本文性能和精度是历史结果，不代表满足新增规则；V4 同类方案也需迁移。当前状态见 [提交工作流](cannjudge_workflow.md)。

本轮以平台15点通过的V4（0a4281f）为基线。历史候选源码标记 `ROPE1743_PROFILED_V6`，1194行、58458字节，SHA256为 `d04a5eedfadf0293736adbf6dd7d6573f03c8425cdeab12085bdf785f975d321`，结尾 `// END_ROPE1743_V6`。平台隐藏15点尚未重测，下面都是本地实测，不能换算为平台成绩。

正式提交仍只修改kernel.asc，模板其余7文件逐字节保持不变。旋转和三角函数均保留FP32，默认L2策略沿用V4。V4的可回退源码、原提交ZIP和元数据保存在 `dist/history/profiled_v4/`；Git中的V4源文件也可从0a4281f恢复。

## 实现与选择依据

V4对齐FP32路径先将VECIN复制到VECCALC，计算完再复制到VECOUT。这两次本地整块复制不增加有效计算，还占用工作区。新增DirectFloatRotary直接从输入队列读，在输出队列计算；生成三角缓存时临时复用尚未写结果的输出区作为工作区。队列控制缓冲复用，各队列缓冲带32B间隔，扩大head tile仍受UB容量限制，角度缓存最多占输出区的一半。适用条件为对齐D、H>1、token≥128、FP32，其余形状保持原路径。

非对齐D≤64、H>32、token≥128的路径，将每head两段碎片DMA改为连续搬入、UB Gather重排和连续搬出。四个FP32乘积与分离加减保持原通用路径的形式。宽维D>512、H=1的对齐输入合批多个token，用实际队列、工作区、三角数组和频率缓冲的预算选tile，减少短DMA和标量循环。

对齐D≤128、H=1、token≥128的输入批量搬入positions，Cast/Brcb和向量Mul生成角度，Select恢复零位置的原始位模式。此处使用与V4单head路径相同的四个FP32乘积和分离加减，不将系数或中间结果转换为FP16。

所有分支在一次run_kernel调用内恰好启动一个device kernel，不引入外部cos/sin输入、额外预处理kernel或跨调用缓存。FP16对齐多head的主体计算保持V4；本轮没有找到足够稳定的该路径加速方式。

## 计时工作流的改进

上一轮不同进程的配对中，未改动路径也出现数个百分点的变化。本轮新增 `tests/paired_runner.asc`：两份源码在独立命名空间内编译到同一个本地runner，每个shape共享GM输入、positions、输出地址和ACL上下文，按ABBA运行。每块5次预热、5次计时，取设备Task Duration中位数。交换两源码再构建反向runner，形成BAAB，最终每份源码取4个块中位数的中位数。

8个A/A校准点采用逐字节相同的V4，两路差异在0.5%以内，原始结果为 `round5_self_check_shared.json`。33点最终平衡采样共2640次调用、2640个device kernel，见 `profiled_v6_balanced.json` 及forward/reverse的原始CSV。输入、两份源码、runner、编译参数和实际二进制哈希都记录在结果中。此工具属于本地测试工程，不进入比赛提交包。

另用实际单文件普通runner完成23点独立进程ABBA，原始记录为 `profiled_v6_paired.json`。其中未改动路径仍出现约5%的差异，因此补做了独立进程A/A：旧V4与当前重新编译V4的二进制SHA256完全相同，仍在部分点测出约5%差异（`round5_native_self_check.json`）。这种幅度不能仅凭该计时方法归因于内核改动，原始记录全部保留。设备ELF进一步确认，V4/V6共享的14个entry中有12个.text段逐字节一致，模块stack记录也一致；两项变化来自通用化的单head初始化。证据保存在 `benchmarks/validation/profiled_v6/device_code_comparison.json`。 可用tools/compare_device_code.py从两份普通runner提取并复核这些段。本轮主要性能结论采用经过同地址A/A校准的ABBA/BAAB，同时不把它当成平台得分保证。PMU也采集实际普通runner。PMU replay的耗时只用于分析流水，不作为最终加速比。

所有设备阶段经过task-submit，串行申请一张卡，每阶段最长60秒，完成释放后再开始下一阶段。编译和输入生成使用CPU。

## 同地址、双顺序33点结果

Ascend910_9392、48 AIV、CANN9.0、dav-2201。单位us。

| 用例 | shape | dtype | V4 | V6 | 加速比 |
|---|---|---|---:|---:|---:|
| tiny | [1, 8, 1, 16] | float32 | 2.390 | 2.370 | 1.01× |
| unaligned_half | [2, 16, 3, 24] | float16 | 5.110 | 5.050 | 1.01× |
| deepseek_half | [2, 512, 128, 64] | float16 | 20.831 | 20.890 | 1.00× |
| deepseek_float | [2, 512, 128, 64] | float32 | 24.260 | 19.990 | 1.21× |
| sequence8192 | [1, 8192, 1, 64] | float32 | 14.851 | 13.190 | 1.13× |
| large_half | [4, 1024, 128, 64] | float16 | 60.851 | 60.682 | 1.00× |
| heads256 | [1, 32, 256, 128] | float16 | 12.841 | 12.820 | 1.00× |
| aligned_d512_half | [1, 7, 17, 512] | float16 | 8.610 | 8.670 | 0.99× |
| wide_half | [1, 7, 17, 1024] | float16 | 13.090 | 12.890 | 1.02× |
| prefill_h32_d128_half | [2, 512, 32, 128] | float16 | 20.070 | 20.050 | 1.00× |
| prefill_h32_d128_float | [2, 512, 32, 128] | float32 | 20.181 | 18.411 | 1.10× |
| prefill_h32_d256_half | [2, 512, 32, 256] | float16 | 36.161 | 36.200 | 1.00× |
| prefill_h8_d64_half | [2, 512, 8, 64] | float16 | 12.130 | 12.160 | 1.00× |
| prefill_h3_d24_half | [2, 512, 3, 24] | float16 | 6.990 | 7.040 | 0.99× |
| prefill_h32_d30_float | [2, 512, 32, 30] | float32 | 20.190 | 20.171 | 1.00× |
| prefill_h32_d96_half | [2, 512, 32, 96] | float16 | 17.420 | 17.441 | 1.00× |
| prefill_h32_d1024_half | [1, 256, 32, 1024] | float16 | 58.041 | 57.901 | 1.00× |
| prefill_h32_d1024_float | [1, 256, 32, 1024] | float32 | 61.351 | 55.711 | 1.10× |
| stream_h128_d64_half | [2, 4096, 128, 64] | float16 | 210.315 | 215.035 | 0.98× |
| stream_h32_d128_float | [2, 4096, 32, 128] | float32 | 218.635 | 217.664 | 1.00× |
| single_token_many_heads | [1, 1, 256, 128] | float16 | 4.800 | 4.500 | 1.07× |
| short_s16_h32 | [1, 16, 32, 128] | float32 | 6.351 | 6.420 | 0.99× |
| narrow_head_long | [1, 8192, 4, 16] | float16 | 22.190 | 22.090 | 1.00× |
| unaligned_h128_d30_half | [2, 1024, 128, 30] | float16 | 644.473 | 100.262 | 6.43× |
| unaligned_h128_d30_float | [2, 1024, 128, 30] | float32 | 432.819 | 100.352 | 4.31× |
| prefill_d192_half | [2, 512, 32, 192] | float16 | 27.501 | 27.541 | 1.00× |
| prefill_d384_float | [2, 512, 32, 384] | float32 | 58.731 | 45.701 | 1.29× |
| large_stream_half | [4, 8192, 128, 64] | float16 | 846.267 | 846.537 | 1.00× |
| large_stream_float | [2, 8192, 64, 128] | float32 | 846.917 | 846.267 | 1.00× |
| sequence_d1024_half | [1, 8192, 1, 1024] | float16 | 202.224 | 112.732 | 1.79× |
| unaligned_h64_d126_half | [2, 512, 64, 126] | float16 | 112.022 | 112.182 | 1.00× |
| unaligned_h64_d254_float | [2, 512, 64, 254] | float32 | 163.514 | 163.194 | 1.00× |
| sequence_d1024_float | [1, 8192, 1, 1024] | float32 | 202.324 | 120.143 | 1.68× |

两个512MiB流式点基本持平。128MiB FP16流式点本次约慢2.2%，其4个块中位数范围在V4为201.964～217.004us，V6为195.264～216.525us，存在明显缓存/采样变化；该路径保留V4，但仍保留这个较慢结果，不宣称全形状无退化。短小形状的微小变化也不计作可靠优化收益。

## 硬件反馈

下表为msprof op逐核平均流水时间，单位us；各流水可重叠，不能相加推导总耗时。采集命令、源码和实际普通runner二进制哈希保存在每个profile目录的metadata.json中。

| 场景 | 指标 | V4 | V6 |
|---|---|---:|---:|
| DeepSeek FP32 | VEC | 16.432 | 12.339 |
| DeepSeek FP32 | scalar | 14.799 | 9.844 |
| DeepSeek FP32 | MTE2 | 19.819 | 20.067 |
| DeepSeek FP32 | MTE3 | 10.396 | 13.163 |
| DeepSeek FP32 | MTE2指令数 | 43.667 | 22.333 |
| H1/D64/FP32 | VEC | 6.526 | 5.362 |
| H1/D64/FP32 | scalar | 9.331 | 5.874 |
| H1/D64/FP32 | MTE2 | 1.100 | 1.176 |
| H1/D64/FP32 | MTE3 | 0.485 | 0.497 |
| H1/D64/FP32 | MTE2指令数 | 3.667 | 6.333 |
| H128/D30/FP16 | VEC | 67.397 | 88.720 |
| H128/D30/FP16 | scalar | 45.514 | 18.097 |
| H128/D30/FP16 | MTE2 | 298.884 | 13.645 |
| H128/D30/FP16 | MTE3 | 291.794 | 6.620 |
| H128/D30/FP16 | MTE2指令数 | 342.333 | 43.667 |
| H1/D1024/FP32 | VEC | 148.980 | 77.861 |
| H1/D1024/FP32 | scalar | 108.002 | 52.290 |
| H1/D1024/FP32 | MTE2 | 52.108 | 14.797 |
| H1/D1024/FP32 | MTE3 | 25.341 | 8.889 |
| H1/D1024/FP32 | MTE2指令数 | 171.667 | 35.146 |

DeepSeek FP32的VEC下降约25%、scalar下降约33%，支持消除UB复制并减少head tile循环的方向；PMU replay中的MTE3时间增加，不能声称每条流水都更快。单head D64的scalar下降约37%，VEC下降约18%；positions批量搬运和角度广播减少了标量工作，但加入了少量DMA/UB工作。

非对齐多head的VEC变重，主要收益来自MTE2/MTE3事务减少，符合连续DMA替代碎片事务的假设。宽维单head同时降低VEC、scalar和DMA事务，符合合批假设。这些均与非replay计时分开评估。

## 候选淘汰记录

补丁和源码SHA256保存在 `benchmarks/experiments/round5/`，可通过replay_experiment.py重建。

| 候选 | 结果与决定 |
|---|---|
| direct_float | FP32整块复制消除、输出临时工作区复用；保留 |
| fp32_dma | 在同地址复测中重现非对齐连续DMA、宽维单head合批的收益；保留 |
| bulk_precise | 单head positions向量化、保持V4乘加顺序；保留 |
| bank_pad | 工作区错开32B并缩减工作数组，DeepSeek等点慢约10%～14%；淘汰 |
| position_cache | 将positions搬入UB并供标量循环读取，同步开销抵消收益，多个点慢约20%～30%；淘汰 |
| trig_vector | 手工管理positions缓冲，长流式回归检出错误，未进行性能验收；淘汰 |
| trig_vector_queue | 改用TQue管理复用并增加同步，52点长重复精度通过，但没有稳定性能收益；淘汰 |

32B偏移是针对特定bank冲突的优化手段，需要结合实际布局验证。本轮没有把偏移本身当作收益证明，依据实测淘汰了该候选。参考[华为Ascend C最佳实践](https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/82RC1alpha001/opdevg/ascendcbestP/atlas_ascendc_best_practices_10_0027.html)。

## 精度与运行验收

414项直接V4输出比较，共241,538,684个输出元素：新增差异元素为0，每项对NumPy参考的匹配比例都是100%，最大绝对误差继续受比赛门槛检查。有限值、Inf、正负零要求位模式相同，NaN要求位置一致；零位置另要求与输入逐位相同。新增166项包含所有16对齐维度、head/tile尾部、长序列、零位置、特殊值和抵消输入；另保留上一轮248项多种子、幅度与theta组合。结果为 `profiled_v6_bits.json` 和 `profiled_v6_extended_bits.json`。

固定52项回归、1010项全偶数维度、456项packed分支和672项路径扫描共2190项全部通过。52×6+1010×2+456×2+672×2=4588次逐次启动API审计均各启动一个kernel；另外166项专门覆盖新增对齐FP32路径，补齐direct-wide分支的审计，合计4920次。独立非replay设备计数为75/75。输出哨兵与零位置原位模式均检查通过。

原模板C++14配置编译通过；最终ZIP还使用原始main和校验脚本运行验证。提交ZIP、解压目录、独立kernel、完整纯文本均逐字节核对，只有kernel.asc与附件原模板不同。

这些结果说明本轮未在已测输入中引入V4输出差异，不是任意输入的数学证明，也不代表平台15个隐藏点通过。V4已知极大幅度FP16诊断的限制仍见历史V4报告，本轮没有放宽门槛或宣称解决所有输入幅度的精度问题。

## 复现与提交

```bash
bash tools/build_revision.sh 0a4281f platform_v4
bash tools/build.sh
bash tools/build_launch_audit.sh
bash tools/validate_profiled_v6.sh --phase prepare
bash tools/build_paired.sh build/revisions/0a4281f1a3789d78f15c76750f2dc76c85526329 \
  operators/rotary_pos_emb build/profiled_v6/forward
bash tools/build_paired.sh operators/rotary_pos_emb \
  build/revisions/0a4281f1a3789d78f15c76750f2dc76c85526329 build/profiled_v6/reverse
# 以下每条等待完成释放后，才执行下一条；prepare/build不申请卡
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled_v6.sh --phase precision'
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled_v6.sh --phase correctness'
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled_v6.sh --phase sweeps'
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled_v6.sh --phase aligned_audit'
bash tools/validate_profiled_v6.sh --phase prepare
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled_v6.sh --phase shared'
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled_v6.sh --phase paired'
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled_v6.sh --phase pmu_aligned'
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled_v6.sh --phase pmu_dma'
# kernel先提交Git；打包增加两项直接V4逐位比较门槛
python3 tools/package.py --result profiled_v6 --launch-profile profiled_v6_launches \
  --extra-result profiled_v6_sweep --extra-result profiled_v6_packed_sweep \
  --extra-result profiled_v6_path_sweep --extra-result profiled_v6_aligned_audit \
  --bitwise-result profiled_v6_bits --bitwise-result profiled_v6_extended_bits
python3 tools/verify_submission.py
bash tools/check_submission_build.sh
task-submit --device 0 --max-time 30 --run 'bash tools/check_submission_device.sh'
```

单独重建候选：先加载CANN环境，再运行 `python3 tools/replay_experiment.py direct_float --round round5`。正式代码路径为 `operators/rotary_pos_emb/kernel.asc`，上传文件路径为 `dist/rotaryposemb_1743_submission/kernel.asc`，完整工程为其同名ZIP。完整源码的行数、首末标记、哈希和验收来源都记录在包外 `dist/manifest.json`。

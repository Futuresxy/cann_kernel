# V4回退与精度优先的第四轮实验

正式源码和 `dist/` 当前恢复为平台15点通过的V4，与Git `0a4281f` 的kernel.asc逐字节一致。恢复提交为 `0950bc4`。文件815行、39093字节，SHA256为 `2acfbd5c205915280dfe6818d8217a78f08a9fb769ad3a1843b4f58a73eb3d58`，末行 `// END_ROPE1743_V4`。以下实验均未替换正式源码或正式提交包。

## 回退依据与验证

用户报告V5在两个平台用例出现2.36%数值错误，测试13、14延迟增加；没有提供其shape或具体延迟。本地历史2190项通过不能抵消这个平台失败，相关反馈保存在 `benchmarks/results/platform_feedback_v5.json`，V5报告已标记撤回。

V5的FP16旋转将系数和中间乘加降到FP16，增加舍入误差，是精度失败的重点嫌疑；缺少平台失败输入，尚未证明唯一根因。输出绕过L2只在固定输入反复运行的部分本地场景明显受益，不能推断冷缓存、不同输入或平台测试13、14的收益。本次两项都撤回，不放宽任何精度阈值。

恢复后的验证记录：

- 52项固定回归全部通过，包括FP16/FP32、零位置原位模式、NaN/Inf和输出哨兵。
- 52项逐次启动API审计全部通过；非replay msprof确认75次调用恰好75个设备kernel。
- 原始比赛模板仅替换kernel.asc，原始CMake编译、main运行与verify_result.py通过，最大误差 `2.6226043701171875e-6`。
- 提交ZIP、解压目录、独立源码及完整纯文本相互一致，模板其余7文件逐字节保持原样。

结果为 `benchmarks/results/rollback_v4{,_audit}.json`、`benchmarks/profiles/rollback_v4_launches/` 和 `benchmarks/validation/rollback_v4/`。V4历史极大幅度FP16诊断的已知限制仍见 [V4报告](profiled_v4.md)，此次是精确回退，没有宣称修复基线所有数值边界。

## 精度检查方式改变

新增 `tools/compare_v4_outputs.py` 和 `tests/round4_precision_cases.json`。在原参考容差之外，候选还必须与V4直接逐位比较：有限值、Inf及正负零必须位模式相同，NaN要求同位置为NaN，不比较NaN载荷。position=0仍额外要求与原始输入逐位相同。参考判定继续使用原比赛阈值，基线本身参考失败也会判本轮比较失败。

248项、75,567,008个输出元素覆盖：非对齐D18/30/62，H33/129；单head宽维D528/640/1008/1024；FP16/FP32；seed88/2026；输入幅度0.25/10/32；theta100/10000；最大位置131072、尾块、每7个token一个零位置及特殊值。另含对齐路径对照点。

`precision_safe`与`precision_safe_tiled`两版均248/248通过，变化元素为0，所有参考匹配比例均100%，最大绝对误差0.03125。这些是本地测试结论，不是任意输入逐位相同的证明，也不是平台隐藏点的精度保证。

## 保留FP32的数据布局实验

本轮复用V4的FP32频率生成、范围缩减和SinCos函数，不引入FP16系数、中间结果或输出L2绕过，也不增加预处理kernel或外部输入。

`precision_safe`包含两个受限分支：

1. D不被16整除、D≤64、H>32、token≥128：一次连续DMA搬多head，在UB Gather分离前后半维并重组输出，取代每head的碎片DMA。旋转显式使用四个FP32乘积和分离的减法/加法，与V4该通用路径的运算方式一致。
2. D>512、D被16整除、H=1、token≥16：复用FP32批量token计算，把多次短DMA和短向量计算合批。宽频率仍用种子、比例与整数ULP修正恢复；频率缓冲为512个FP32元素，避免宽度小于512时初始化越界。

`precision_safe_tiled`仅进一步调整第二个分支的tile：依据输入类型和UB实际分配预算，按 `tile*D*(4*sizeof(T)+18)+2048 ≤ 180KiB` 选取。四份队列、三份FP32工作数组和三份半宽三角数组均计入预算。D1024的tile由4改为FP16的6、FP32的5，不改变SinCos公式或旋转精度。

`precision_safe_tiled`另外通过52项固定回归、52项逐次启动审计和672项分支边界扫描；扫描1344次调用均各启动一个kernel。独立msprof检查仍为75次调用、75个设备任务。

原始候选补丁、源码SHA256和基线版本在 `benchmarks/experiments/round4/`。两版实验仍各次调用仅启动一个kernel。

## Profiling闭环与性能结论

Ascend910_9392，48 AIV，CANN9.0，dav-2201。所有设备任务通过task-submit串行申请单卡，最长60秒，到结束释放后才提交下一任务。CPU生成数据、编译、比对和分析。基线与候选使用同一个512字节输出对齐runner，配对脚本核对runner、输入、源码与二进制哈希。

设备耗时使用无replay的msprof Task Duration；每点5次预热、5次采样，baseline/candidate/candidate/baseline交替，每轮取采样中位数，再对两轮取中位数。PMU replay只解释流水瓶颈，不混作计时收益。

### V4与precision_safe的同卡配对

| 本地用例 | V4 / us | 候选 / us | 加速比 |
|---|---:|---:|---:|
| unaligned_h128_d30_half | 640.393 | 99.992 | 6.40× |
| unaligned_h128_d30_float | 432.879 | 100.162 | 4.32× |
| large_stream_half | 845.737 | 846.177 | 1.00× |
| large_stream_float | 847.247 | 846.817 | 1.00× |
| sequence_d1024_half | 201.394 | 125.433 | 1.61× |
| sequence_d1024_float | 201.474 | 124.783 | 1.61× |

先前PMU显示非对齐多head的MTE2/MTE3碎片事务很重，宽维单head的标量与短向量调用占比较高，因此先只改变布局和批次，再用PMU验证对应流水是否下降。这里的shape是本地矩阵，不能映射为平台测试点编号。

### 宽维tile的增量配对

| 本地用例 | 原tile / us | 预算选tile / us | 加速比 |
|---|---:|---:|---:|
| sequence_d1024_half | 125.713 | 110.662 | 1.14× |
| sequence_d1024_float | 124.892 | 118.002 | 1.06× |

该表基线是 `precision_safe`，不是V4。两个独立配对实验的延迟不拼接成平台预期加速比。

### 对照与淘汰

23点完整矩阵中，一些未改动的对齐路径测到约3%～7%的变化。8点复测后，部分小中型对照仍约1%～6%变慢，流式用例前后轮波动更大，尚未证明所有形状无退化。原始逐轮样本同时保留，不能只挑有收益的点。因此上述候选继续列为实验，正式包保持V4。

另一个 `trig_batch64` 候选移除对齐路径未使用的第三工作数组，并将三角缓存批次上限由16增为64。8点ABBA中，小中型输入改善约2%～4%，一个流式FP32用例190.753→206.904us，约8%退化，未采用。结果在 `round4_trig_batch64_paired.json`；没有为了提高平均值而合并该修改。

### 最终FP32候选的硬件反馈

以下为msprof op的逐核平均值，时间单位us；流水可重叠，不能相加推导端到端延迟。四次采集的当前频率均1850MHz。

| 场景 | 指标 | V4 | precision_safe_tiled |
|---|---|---:|---:|
| H128/D30/FP16 | VEC | 67.397 | 88.720 |
| H128/D30/FP16 | scalar | 45.712 | 18.972 |
| H128/D30/FP16 | MTE2 | 302.437 | 13.837 |
| H128/D30/FP16 | MTE3 | 292.028 | 6.632 |
| H128/D30/FP16 | MTE2指令数 | 342.333 | 43.667 |
| H1/D1024/FP32 | VEC | 148.980 | 77.861 |
| H1/D1024/FP32 | scalar | 105.456 | 53.636 |
| H1/D1024/FP32 | MTE2 | 51.835 | 14.824 |
| H1/D1024/FP32 | MTE3 | 25.343 | 9.126 |
| H1/D1024/FP32 | MTE2指令数 | 171.667 | 35.146 |

非对齐head路径VEC时间反而增加，收益来自MTE2/MTE3事务和流水时间显著下降，支持连续DMA/Gather的优化假设；不能把它描述为纯向量计算加速。宽维单head路径同时减少VEC、scalar和DMA事务，支持合批与减少短循环的假设。原始逐核CSV和源码/二进制元数据保存在 `benchmarks/profiles/round4_precision_safe_tiled_{baseline,candidate}_*/`。

## 复现

正式V4可以按README编译、运行并使用 `tools/package.py --result rollback_v4 --launch-profile rollback_v4_launches` 重新打包。打包要求当前正式kernel已提交Git，并检查源码、实际二进制、逐次启动与设备任务计数一致。

实验独立重建，不改正式kernel：

```bash
source /usr/local/Ascend/ascend-toolkit/latest/set_env.sh
python3 tools/replay_experiment.py precision_safe_tiled --round round4
cmake -S . -B build/replayed_experiments/round4/precision_safe_tiled/audit \
  -DROPE_KERNEL_DIR="$PWD/build/replayed_experiments/round4/precision_safe_tiled" \
  -DROPE_LAUNCH_AUDIT=ON -DNPU_ARCH=dav-2201
cmake --build build/replayed_experiments/round4/precision_safe_tiled/audit -j4
python3 tools/stamp_build.py \
  --source build/replayed_experiments/round4/precision_safe_tiled/kernel.asc \
  --binary build/replayed_experiments/round4/precision_safe_tiled/audit/rope_runner
# prepare在CPU上生成输入和参考，不申请卡
bash tools/validate_round4.sh --phase prepare --label round4_replay
# 以下每个命令等待完成后，再执行下一个；均只申请一张卡
task-submit --device auto --max-time 35 --run 'bash tools/validate_round4.sh --phase precision --label round4_replay'
task-submit --device auto --max-time 60 --run 'bash tools/validate_round4.sh --phase correctness --label round4_replay'
task-submit --device auto --max-time 60 --run 'bash tools/validate_round4.sh --phase paths --label round4_replay'
task-submit --device auto --max-time 60 --run 'bash tools/validate_round4.sh --phase paired --label round4_replay'
task-submit --device auto --max-time 60 --run 'bash tools/validate_round4.sh --phase extended --label round4_replay'
task-submit --device auto --max-time 60 --run 'bash tools/validate_round4.sh --phase pmu --label round4_replay'
```

上述命令要求当前正式runner仍是V4；也可用 `--baseline build/rope_runner_platform_v4` 指定同runner重建的历史基线。实验工具拒绝将其他源码冒充V4比较基线。当前正式提交文件仍是 `dist/rotaryposemb_1743_submission/kernel.asc`。

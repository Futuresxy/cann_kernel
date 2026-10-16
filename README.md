# CANN Kernel：RotaryPosEmb

2026 初赛 RotaryPosEmb（problem 1743），Ascend C 原生实现，匹配附件的 `run_kernel` 直接调用接口。基础版和后续优化版通过 Git 提交保存；源码、测试、profiling、报告、原始模板和提交包分目录管理。

## 目录

```text
operators/rotary_pos_emb/kernel.asc  平台提交的唯一算子源文件
CMakeLists.txt                      本地可配置测试工程
templates/rotaryposemb_1743/         用户附件原始工程，保留不改
tests/runner.asc                    通用 ACL runner，计时与边界哨兵
tests/cases.json                    固定扩展集，非平台隐藏用例
tests/performance_cases.json        23项同卡性能矩阵
tests/precision_stress_cases.json   独立极大幅度精度诊断，保留已知失败
tools/                             编译、精度、profiling、分析、打包
benchmarks/results/                原生 event/host 时间与精度结果
benchmarks/profiles/               profiling 原始 CSV、摘要和元数据
benchmarks/experiments/            候选源码补丁、哈希与基线版本
docs/problem_statement.md          赛题说明
docs/tuning_workflow.md             指标驱动的实验记录
dist/rotaryposemb_1743_submission/  严格原模板工程，仅kernel.asc不同
dist/                              独立内核、提交ZIP、包外校验元数据
build/                             二进制、临时输入输出、原始采集目录
```

## 编译与验证

要求 CANN 9.0（当前验证版本）、支持 `find_package(ASC)` 的 bisheng，Python 3 + NumPy。默认 Ascend A2/A3 的 `dav-2201`；本机已验证 SoC 为 Ascend910_9392。

```bash
bash tools/build.sh
bash tools/build_launch_audit.sh
# 不占NPU，预生成数据
python3 tools/suite.py --generate-only
# 单卡、60秒上限：精度、逐次启动检查、设备任务数与一次PMU
# 15个本地回归形状×5次调用，设备kernel任务数必须为75
task-submit --device auto --max-time 60 --run 'bash tools/validate_single_launch.sh --label restored_full_v3 --launch-label restored_full_v3_launches'
# CPU汇总已有采集数据
python3 tools/profile.py --label restored_full_v3 --analyze-only
python3 tools/report.py baseline_fixed restored_full_v3
# 当前kernel先提交Git；打包要求精度与两类启动检查对应同一源码
python3 tools/package.py --result restored_full_v3 --launch-profile restored_full_v3_launches
```

设备任务始终经过服务器 task-submit 队列。编译和报告在 CPU 上完成。不要将 profiler replay 内的 event 时间当作原生 kernel 性能；小算子 event 时间还会包含 host 下发空洞。

## 数学与精度

`x[B,S,H,D]` 按前后两半旋转。频率在算子 host 入口用 FP32 `pow` 与倒数实时生成；位置、角度、cos/sin、乘加均为 FP32。频率并非新增输入，不提供外部 cos/sin 或离线常量表。FP16 输出仅最后舍入一次。

对于较大位置，使用三段2π常量缩减角度，避免直接调用高阶 Sin/Cos 超出有效范围。优化版共用正余弦的范围缩减，在四分之一角上计算多项式并通过二倍角恢复。position=0 单独保持原始位模式，包括 NaN/Inf。

精度验收实现赛题的逐元素 `atol+rtol*abs(golden)`、99%通过率和最大绝对误差双重门槛；参考附件 NumPy FP32 golden。非有限值按 NaN/同号 Inf 分别比较。测试包含 FP16/FP32、非对齐、最大位置、边界维度、不同 theta、大 head 数和长序列，并验证输出前后哨兵。

附件只提供一个公开样例，平台15个隐藏点的实际输入未公开。具体已验证形状及结果以 `benchmarks/results/` 为准。

## 复现历史基线

```bash
# 以当前批量runner重新编译指定Git版本的kernel，编译过程不占卡
bash tools/build_revision.sh e35b0cc baseline
# 同一卡上按 baseline/candidate/candidate/baseline 交替采样
# candidate 参数可指定当前已保存的候选二进制
task-submit --device auto --max-time 90 --run 'bash tools/paired.sh --candidate build/rope_runner'
# 全部505个偶数维度 × 两种dtype：1010个精度用例
task-submit --device auto --max-time 90 --run 'bash tools/device_suite.sh --label sweep --sweep --warmup 1 --repeat 1 --batches 1'
```

## 仅允许修改kernel.asc的提交要求

提交ZIP和`dist/rotaryposemb_1743_submission/`解压目录均只包含原始模板的8个文件：仅`kernel.asc`替换为优化实现，其余7个文件逐字节保持一致。不修改`CMakeLists.txt`、`main.asc`、`run.sh`，不新增包内manifest或其他文件。版本元数据只保存在提交目录外的`dist/manifest.json`。

源码中的类型转换分派已改用函数重载，移除了自写的`if constexpr`。实际编译严格采用原模板配置和工具链默认的ASC模式，不需要修改模板中的C++标准设置或添加编译参数。

```bash
# 检查ZIP、解压目录与原始模板：必须只有kernel.asc不同
python3 tools/verify_submission.py
# 使用包内原始CMakeLists.txt构建，未添加编译参数
bash tools/check_submission_build.sh
# 原始main.asc固定选择设备0，因此只申请该单卡
task-submit --device 0 --max-time 30 --run 'bash tools/check_submission_device.sh'
```

仓库根目录的开发构建工程、tools、tests及benchmarks仅用于本地测试和profiling，不进入比赛提交包。`templates/rotaryposemb_1743.sha256.json`记录用户原始ZIP中各文件的SHA256，打包和检查均使用这一固定基准。

## 当前优化版

`operators/rotary_pos_emb/kernel.asc` 为 `ROPE1743_PROFILED_V4`。完整源码及提交包由 `tools/package.py` 生成，首末标记、行数、SHA256 以 `dist/manifest.json` 为准。请完整替换平台编辑框内容。

本轮相对于已通过平台的 V3 调优，而非相对于最早的慢基线。新增按 shape 选择的跨 token 三角函数缓存、非对齐小维度连续搬运/UB Gather，以及宽维度频率向量恢复。原始 CSV、候选补丁、失败记录、性能对照和精度限制见 [本轮报告](docs/profiled_v4.md)。

```bash
bash tools/build.sh
bash tools/build_launch_audit.sh
python3 tools/suite.py --generate-only
python3 tools/suite.py --sweep --generate-only
python3 tools/suite.py --packed-sweep --generate-only
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled.sh --phase correctness'
# CPU 生成完整性能矩阵输入，再在同一卡上按 ABBA 顺序采集设备任务耗时
python3 tools/suite.py --cases-file tests/performance_cases.json --generate-only
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled.sh --phase paired'
task-submit --device auto --max-time 60 --run 'bash tools/validate_profiled.sh --phase pmu'
# 确保当前 kernel 已提交 Git；三项门槛必须对应同一源码/二进制
python3 tools/package.py --result profiled_v4 --launch-profile profiled_v4_launches
python3 tools/verify_submission.py
```

`paired` 需要预先保留 V3 基线二进制 `build/rope_runner_platform_v1`，或用 `tools/build_revision.sh b32d3a6 platform_v1` 重建。设备审计采用实际 CANN 启动 API 与非 replay msprof 两套证据。本地 runner 和测试脚本不进入提交包。

## 完整源码的下载与复制

`dist/kernel_full_source.txt` 与 `dist/kernel.asc` 字节一致；`dist/kernel_upload.zip` 只含完整 kernel.asc。解压后替换平台整个源码，纯文本可用于全选复制。不要只复制源码预览中的某个函数片段。

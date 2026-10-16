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

`x[B,S,H,D]` 按前后两半旋转。频率在算子 host 入口用 FP32 `pow` 与倒数实时生成；位置、角度、cos/sin生成均为 FP32；所有路径均采用FP32旋转，最后转换到输出类型。频率并非新增输入，不提供外部 cos/sin 或离线常量表。精度判定保持赛题原阈值。

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

## 当前稳定版与实验状态

当前正式源码恢复为平台15点精度通过的 V4（`ROPE1743_PROFILED_V4`），与提交 `0a4281f` 的 kernel.asc 逐字节一致。V5 被平台反馈为两个用例出现2.36%数值错误，且测试13、14退化，已撤回；其历史报告和实验数据保留用于分析，不作为可提交版本。

本轮回退验证、逐位精度门槛、候选收益与未晋级原因见 [回退与第四轮实验报告](docs/rollback_v4_round4.md)。

稳定版的所有旋转算术保持FP32，撤回FP16原精度旋转和输出L2绕过策略。后续候选在独立实验目录中验证，正式提交包继续使用V4。精度门槛不放宽，并增加与V4直接逐位比较，避免局部通过率掩盖新增误差。

本地runner保持输出512字节对齐，基线和候选必须由同一runner重建。恢复验证使用 `tools/validate_profiled_v5.sh --phase correctness --label rollback_v4`（脚本名为历史名称，实际验证当前构建的源码）。打包结果和源码哈希由 `dist/manifest.json` 记录；原模板的7个非kernel文件保持不变。

## 完整源码的下载与复制

`dist/kernel_full_source.txt` 与 `dist/kernel.asc` 字节一致；`dist/kernel_upload.zip` 只含完整 kernel.asc。解压后替换平台整个源码，纯文本可用于全选复制。不要只复制源码预览中的某个函数片段。

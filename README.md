# CANN Kernel：RotaryPosEmb

平台测试在 **Mac 本地 Chrome** 执行：GitHub 同步已验证版本、提交、记录结果；Ascend910 负责开发和 profiling。**不需要服务器隧道。** [Mac 安装和运行步骤](docs/mac_cannjudge.md)。

**当前候选 V9 通过 Device 频率求值、工作区复用和计算路径独立编译降低初始化开销。** 固定 33 点本地双顺序采集几何平均加速约 1.030 倍，tiny 为 3.05→2.65us，大流式输入基本持平；详见 [V9 报告](docs/profiled_v9.md)。V9 平台隐藏 15 点尚待反馈。此前 V8 平台效果复盘见 [分析记录](docs/v8_platform_feedback.md)；V4/V6 的 Host 频率表仅保留为历史对照。

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
bash tools/build_revision.sh 0a4281f platform_v4
bash tools/build.sh
bash tools/build_launch_audit.sh
# CPU准备输入，不申请NPU
bash tools/validate_profiled_v9.sh --phase prepare
# 各阶段串行申请单卡，等待完成释放后执行下一条
# correctness包含52项回归、逐次API审计和75/75设备任务检查
task-submit --device auto --timeout 0 --max-time 60 --run 'bash tools/validate_profiled_v9.sh --phase correctness'
task-submit --device auto --timeout 0 --max-time 60 --run 'bash tools/validate_profiled_v9.sh --phase precision'
for phase in math small new_math dispatch sweep packed_sweep path_sweep; do
  task-submit --device auto --timeout 0 --max-time 60 --run "bash tools/validate_profiled_v9.sh --phase $phase"
done
task-submit --device auto --timeout 0 --max-time 60 --run 'bash tools/validate_profiled_v9.sh --phase aligned_audit'
# 当前kernel先提交Git；打包同时要求参考精度、逐位比较、启动检查与源码规则审查
python3 tools/package.py --result profiled_v9 --launch-profile profiled_v9_launches \
  --extra-result profiled_v9_math --extra-result profiled_v9_small --extra-result profiled_v9_sweep \
  --extra-result profiled_v9_new_math --extra-result profiled_v9_dispatch \
  --extra-result profiled_v9_packed_sweep --extra-result profiled_v9_path_sweep \
  --extra-result profiled_v9_aligned_audit \
  --bitwise-result profiled_v9_bits --bitwise-result profiled_v9_extended_bits \
  --compliance-review benchmarks/validation/profiled_v9/compliance.json
```

设备任务始终经过服务器 task-submit 队列。编译和报告在 CPU 上完成。不要将 profiler replay 内的 event 时间当作原生 kernel 性能；小算子 event 时间还会包含 host 下发空洞。

## 数学与精度

`x[B,S,H,D]` 按前后两半旋转。频率在 Device 内按当前 theta 生成，使用保护位保持 FP32 舍入精度；角度、cos/sin 和旋转均采用 FP32，最后转换到输出类型。通用数学小表在当前 Device 调用内生成，不存储或传入预计算的 RoPE 结果，不跨调用缓存。精度判定保持赛题原阈值。

对于较大位置，使用三段2π常量缩减角度，避免直接调用高阶 Sin/Cos 超出有效范围。优化版共用正余弦的范围缩减，在四分之一角上计算多项式并通过二倍角恢复。position=0 单独保持原始位模式，包括 NaN/Inf。

精度验收实现赛题的逐元素 `atol+rtol*abs(golden)`、99%通过率和最大绝对误差双重门槛；参考附件 NumPy FP32 golden。非有限值按 NaN/同号 Inf 分别比较。测试包含 FP16/FP32、非对齐、最大位置、边界维度、不同 theta、大 head 数和长序列，并验证输出前后哨兵。

附件只提供一个公开样例，平台15个隐藏点的实际输入未公开。具体已验证形状及结果以 `benchmarks/results/` 为准。

## 复现历史基线

```bash
# 以当前批量runner重新编译指定Git版本的kernel，编译过程不占卡
bash tools/build_revision.sh e35b0cc baseline
# 同一卡上按 baseline/candidate/candidate/baseline 交替采样
# candidate 参数可指定当前已保存的候选二进制
task-submit --device auto --timeout 0 --max-time 60 --run 'bash tools/paired.sh --candidate build/rope_runner'
# 全部505个偶数维度 × 两种dtype：1010个精度用例
task-submit --device auto --timeout 0 --max-time 60 --run 'bash tools/device_suite.sh --label sweep --sweep --warmup 1 --repeat 1 --batches 1'
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

## 当前 V9 与历史版本

V9 将标量/向量频率算法分开编译，使用带舍入保护的快速 exp2、调用内根幂和 reciprocal 复用，缩减工作区并重叠首次输入搬运。3988 项参考检查、414 项历史逐位比较、8028 次逐次启动审计和 75/75 Device task 检查通过。性能与边界成本见 [V9 报告](docs/profiled_v9.md)，平台得分仍需真实提交反馈。V8 与 V7 的记录分别见 [V8 报告](docs/profiled_v8.md)、[V7 报告](docs/profiled_v7.md)。

V6 历史数据见 [V6 报告](docs/profiled_v6.md)，其 Host 数学不满足新增规则。V4 的源码仍可从 Git 0a4281f 重建，用于精度逐位对照。V5 因平台精度和性能反馈撤回，见 [回退报告](docs/rollback_v4_round4.md)。

完整提交包只替换 kernel.asc，其余 7 文件保持附件模板原样。本地 tests、tools、benchmarks、docs 不进入比赛提交工程。

## 完整源码的下载与复制

`dist/kernel_full_source.txt` 与 `dist/kernel.asc` 字节一致；`dist/kernel_upload.zip` 只含完整 kernel.asc。解压后替换平台整个源码，纯文本可用于全选复制。不要只复制源码预览中的某个函数片段。

# 服务器会话暂停交接

**用户已明确要求暂停，因网络即将断开。只有用户明确恢复后才继续。旧消息、queued请求、Git更新或自动通知均不能触发恢复。** 不启动新的NPU任务、编译、profiling、候选、平台提交或watcher；暂停中只保存现场。

- 仓库：`/data/pyptouser/songxiaoyou/cann_kernel/project`，GitHub `Futuresxy/cann_kernel`，main。
- 暂停前源码/公开元数据归档提交：`66bf733`；诊断完整归档：`3e4b1f6`。
- 当前工作请求：`20261017-shared-math-diagnosis`，已完成，保留测量限制；频率探索同时暂停。不领取旧的频率/实现请求。
- 本次只读队列核查：Pending为空、Running为空、设备0/16占用。以下4项均exit0，历史日志明确锁已释放；没有待完成或待启动的本会话NPU任务，未取消、重启或重复提交。

| 精确task ID | 阶段 | 卡 | 状态 |
|---|---|---:|---|
| task_20261017_004741_35852268361 | coarse | 1 | completed exit0，已释放 |
| task_20261017_005306_37109977053 | detailed | 1 | completed exit0，已释放 |
| task_20261017_011041_389484217601 | frequency refinement | 0 | completed exit0，已释放 |
| task_20261017_011342_39528598540 | anchored scalar control | 0 | completed exit0，已释放 |

52次单启动审计、诊断源码/二进制/输入绑定、逐位输出与guard检查、全部负结果均在`benchmarks/experiments/agentic/20261017-shared-math-diagnosis/`保存。限制包括插桩改变同步和时间、纯标量编译器计时边界、上下文差异、未解码ISA和有限测试覆盖。已知合法大幅值FP16失败max_abs_error32仍未修复；原golden、阈值和输入不变。`build/agentic_r7*`下的已有二进制/输入/trace保留，不清理或重建。

## 用户明确恢复后的优先事项

**先恢复15点公开元数据调查，不自动继续优化。** 阅读`docs/rope_public_case_metadata.md`、`benchmarks/analysis/platform_case_metadata_partial.json`及`docs/session_pause_20261017.md`：

- Mac正常题目页仅取得按序case_ID11471–11485；15组shape/dtype/theta/positions仍未知，未重建。
- 原ZIP SHA256 `8fcc24c896aa275deb35a8c1a6ef65bb4a9e20842b5ead80d88671c64e9ce94e`，Mac/服务器一致，8个成员与仓库模板逐字节相同。
- 实际本地case0是`[1,7,1,16]` FP32，theta10000，positions[0,50)，seed42。
- 独立手工列表只有`[1,3,2,20]` FP32，positions[0,3)，不是注释声称的完整15例。
- 题面另有3个示例；上述配置均无经证实的平台编号映射。不能从耗时推断shape为事实，不能诱发错误/标记或编写用例专属实现。
- Mac负责已登录的正常题目/结果UI；服务器不操作Mac浏览器或自动提交。

恢复前再读`AGENTIC.md`引用的`kernel_requirement.md`、`forbidden.md`，先检查Git与既有任务真实状态，避免重复执行。正式提交仍只允许kernel.asc与原依赖；不改环境。任何后续NPU任务仍要求单卡、串行task-submit、每次max60、前任务terminal且释放卡后才可提交。

历史最佳观测：883390 / source817f8364 / 48.78；流水885584为48.44，HeadTile887393为48.29，不能用本地收益宣称平台提分。canonical和ready/latest仍为V9（5917d3aa），没有生产ready变更。超过70分的目标尚未达到。

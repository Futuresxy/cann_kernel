# 暂停与恢复上下文：2026-10-17

用户明确要求暂停，因即将断网；**只有用户明确恢复后才继续**。目标仍为Mac主控联合Ascend910既有Codex、遵守赛规争取官方超过70分，目前未达成。

## 恢复时首先做什么

用户最新优先事项是：**先根据题目和已知信息重建平台15项测试的覆盖，再继续优化**。不要直接继续频率或trig实验，不要启动自动提交watcher或旧的ready任务。先阅读本文件、`AGENTIC.md`、`kernel_requirement.md`、`forbidden.md`，检查Git、服务器会话和已提交任务的真实状态；观察超时不是任务失败，不可重复提交。

## 暂停状态

- Mac无运行中的提交/浏览器轮询进程，无未决平台提交。
- 私有控制器 `.local/cannjudge/controller.json` 为 `paused_by_user`，`paused:true`。
- 已向服务器固定会话发送暂停消息，回执ID `01a148ee-8840-7d80-9282-3c0ad9e29ebc`。要求不再启动实验、保留已提交任务/现场、保存交接，等待用户恢复。
- 暂停检查时服务器没有正在运行的NPU测试或bisheng编译进程。频率补充诊断现场此前未跟踪，随后已在远端提交 `3e4b1f6` 完整归档，并合入Mac；不要清理或覆盖。
- SSH一次出现连接关闭，重试成功；不能把连接失败当作服务器任务已停止。

## 平台真实成绩与源码

| 提交 | 源码SHA前缀 | 官方分数 | 结论 |
|---|---|---:|---|
| 879119 | 5917d3aaeb69 | 48.45 | V9基线，15/15通过 |
| 883390 | 817f8364de18 | 48.78 | 此前最高观测值，后续实验性能对照 |
| 885584 | f32e9651514d | 48.44 | 通用非对齐流水，本地1.68～1.73倍，未观察到平台提分 |
| 887393 | 8d91182ab86e | 48.29 | HeadTile周期Copy布局，本地1.525倍，平台15/15通过、排名快照69；未提分 |

887393的run为 `20261017T073409479470Z-8d91182ab86e`，结果页：
https://cannjudge.cn/public/op_challenge_jingdong_prelim/rotaryposemb/submission/6ad324f5193e507d8e794473

真实反馈在 `platform_results/rotary_pos_emb/`，完整实验在 `benchmarks/experiments/agentic/`，平台试验在 `platform_trials/rotary_pos_emb/`。canonical `operators/rotary_pos_emb/kernel.asc` 和ready/latest仍为V9，不能把HEAD的canonical误认成48.78或48.29的实验源码。48.78源码存于 `platform_trials/rotary_pos_emb/20261017-user-platform-wide-fma/kernel.asc`。

所有实验保留一个继承的合法高幅值FP16失败：`[1,137,17,1024]`，max_abs32>0.1；不修改原golden、阈值或输入，不宣称全面正确/production-ready。新HeadTile的1765项输出与父版逐位一致；普通52、审计52、启动75及原模板验证通过。一次NPU计时误重叠已排除并串行重采，异常保留在任务记录中。

## 15项case重建：目前确定和未知

已通过正常题目页加载的 `/api/problems/...` 响应，获取按顺序排列的15个测试标识：**11471～11485**。保存于 `benchmarks/analysis/platform_case_metadata_partial.json`。响应仅给标识、type/default、baseline/null；**没有shape、dtype、theta、positions分布**，`npu_cases`没有提供。不能把这些标识当作已经还原15个输入。

原始下载包 `/Users/songxiaoyou/Downloads/rotaryposemb_problem_1743_template.zip`，SHA256 `8fcc24c896aa275deb35a8c1a6ef65bb4a9e20842b5ead80d88671c64e9ce94e`，16968字节，8个文件。原模板和当前提交只读文件已核对：

- `gen_data.py`只生成case0：`[1,7,1,16]`、FP32、theta10000、positions0..49、seed42、uniform[-10,10]。是否对应平台第1项未证实。
- `RotaryPosEmb.py`注释写“JSON npu_cases对应15例”，实际demo数组只有 `[1,3,2,20]`、FP32、positions上限3、theta10000；不是15项配置。
- 题目还有tiny/DeepSeek/非对齐例子，但没有与平台编号的映射。
- 提交结果15行DOM只含编号、状态、错误比例、当前/最优耗时，无shape/dtype。
- 公开前端代码未含 `npu_cases` 常量；只读取正常页面模块，没有访问私有判题接口、管理员接口、诱发错误或修改计时。
- 首次点击“下载空工程”未收到下载事件而超时；不要声称重新下载成功。原下载ZIP与当前只读脚本均已检查。

私有调查原件在 `.local/cannjudge/case-reconstruction/`：normal-problem-case-metadata.json、problem/submission页面文字与控件、submitted-main.asc/gen_data/reference/run、结果行DOM、公开前端JS。没有保存cookies或请求头。

恢复后的可做事项：检查**已有失败提交**正常UI公开的错误详情是否含输入规模/shape；继续检查官方公开case元数据来源。不要通过故意报错、计时标记、额外提交探针或按隐藏case硬编码实现来获取信息。耗时只能筛候选等价类；当前kernel把B/S合成N，`[1,1024,128,64]`与`[2,512,128,64]`调用配置相同，因此耗时不能唯一逆向B/S。不能编造15个具体shape作为事实。

## 已完成的profiling与未收尾的诊断

先读 `docs/rope_bottleneck_review.md` 及HeadTile实验README。HeadTile局部向量布局已实测改善，但没有平台提分。当前八场景共用计算链任务为 `20261017-shared-math-diagnosis`，**仅诊断，不授权性能候选**。

粗/细两版诊断已经输出8项结果，均与817父版输出逐位一致、guard通过，使用独立trace缓冲。粗粒度的全核累计SYS_CNT tick大致为：tiny频率81.75/trig21.38；DeepSeek FP16频率114.65/trig55.79/旋转396.38；FP32旋转583.21；H1D1024 FP16 trig2264.58/旋转1333.92；FP32 trig2413.42/旋转1511.94。不能把强制同步后的阶段tick当原kernel可加占比，也没有解码ISA计数。Sqrt不是唯一或最大trig成本。

首个coarse任务 `task_20261017_004741_35852268361` 已确认completed(exit0)；排队期间没有取消或重提。诊断分配到device1，本身不是并发违规；旧native计时device0与新诊断不可混算加速比。频率子阶段补充诊断后来被用户“先逆向case”及暂停指令覆盖；已保存于 `frequency_attribution/`，恢复先检查任务状态，不自动继续实验。

## 工具与约束

- Mac仓库：`/Users/songxiaoyou/cann_kernel_judge`，GitHub `Futuresxy/cann_kernel` main。
- Python：`.venv/bin/python` 3.12.15；浏览器工具 `.local/cannjudge/venv/bin/python`。系统Python3.9未改。
- SSH：`ssh Ascend910`；远端仓库 `~/cann_kernel/project`。
- 固定Codex会话：`01a13f1b-61ec-7571-b10e-2b20134d43e3`，标题“实现并优化 RotaryPosEmb 算子”；通过 `codex queue --thread ... --message ...` 联合。队列回执不等于任务已执行，需读公开消息/真实任务状态。
- 不安装/更新服务器包、驱动、系统或队列配置；不更改远程环境。NPU串行自动分配单卡，单任务max60秒；前任务终态和释放卡后才可提交下一项。
- 平台只编辑kernel.asc，其余7文件只读；完整源码回读SHA核对；一次提交后每60秒查看，先确认终态再发下一项。
- 私有登录、通知配置和浏览器profile留在 `.local/cannjudge/`，不提交Git；无网络时不要反复登录、重装或重提。

# Mac 与 Ascend910 现有 Codex 会话协作

Mac 负责浏览器提交和成绩反馈；Ascend910 上已有的 Codex 会话负责源码优化、本地验证和 ready 候选发布。两端通过 Git 交换文件，不需要 Mac 登录管理服务器，不安装软件或修改服务器环境。

Mac 可以作为主控。反馈推送成功后，通过 SSH 调用已核实的 `codex queue --thread UUID --message ...` 唤醒固定的现有会话，不新建会话，不改变其模型或权限。官方 app-server 的会话与 turn 协议可用于后续扩展：[官方文档](https://learn.chatgpt.com/docs/app-server)。当前无需新增服务或暴露端口。

## 文件协议

```text
Mac：已完成提交
  → platform_results/rotary_pos_emb/<run-id>.json
  → tuning_requests/rotary_pos_emb/<run-id>.json（ready_for_tuning）
  → GitHub
远端现有 Codex：inbox 读取任务 → 分析瓶颈 → 只修改 kernel.asc
  → 编译、精度、单 kernel 启动、profiling 与合规审查
  → stage --request 任务文件 --hypothesis 优化依据
  → publish，latest.json 记录 ready 和 tuning_request_id
  → GitHub
Mac：watch 读取新 ready 候选 → 全文核对 → 一次提交
  → 每分钟等待状态、15 点性能、对应的官方分数
  → 输出下一轮 feedback 和 request
```

任务包含父源码 SHA256、源码 Git 提交、官方分数、15 点耗时、TBest 差距、前五名逐点差距、赛事规则和精度要求。失败任务只提供失败状态及提取出的 kernel.asc 编译错误定位，不伪造性能分数。浏览器 profile、Cookie、账号信息、截图和原始日志不进入任务文件。

任务按 request_id 冻结。候选的 manifest 与 latest.json 中的 tuning_request_id 必须一致；结果继续保留该 ID，下一轮任务用 responds_to 连接上一轮。源码变化后必须重新取得证据，不能改标签复用旧证据。

## Mac 端

```bash
# 将一次已完成结果交给现有远端会话。
bash tools/mac_cannjudge.sh handoff \
  --run benchmarks/platform/runs/实际run-id/run.json --publish-feedback

# 持续处理已验证候选，自动将最终反馈及下一轮任务推送 GitHub。
bash tools/mac_cannjudge.sh watch --publish-feedback \
  --notify-config .local/cannjudge/notify.json \
  --interval 60 --idle-timeout 1800 --max-candidates 3
```

notify.json 只保存在 Mac 的 Git 忽略目录，包含 `ssh_host` 和 `thread_id`。先用远端 `codex agents` 确认会话可见，再使用其 UUID。`notification.json` 在调用前记录意图，成功后记录 queued；连接超时则标为 uncertain，不自动重复通知。queued 只表示进入现有会话消息队列，不能据此声称调优已完成。

`max-candidates=3` 包括当前基线，因此最多触发两轮新候选，最后一次结果不会再启动额外一轮。远端无可靠改进或验证受阻时，按通知约定提交 `tuning_responses/rotary_pos_emb/<request_id>.json`（state 为 blocked 或 no_improvement，附 reason 与 evidence 路径），Mac 主控读取后结束本轮。后台状态存于 `.local/cannjudge/controller.json`。

反馈发布使用临时 Git 克隆，只提交两个明确路径：精简结果和对应任务。不会操作 Mac 的索引、切换工作分支、pull/reset 工作区或推送其他未提交文件。非快进冲突会在临时克隆重新读取远端，最多三次；不强推。运行目录记录 feedback-published.json，重复查询同一结果不会重复发布任务。

## 远端已有会话

首次让远端会话读取更新后的这些工具。已有工作区有改动时由该会话先检查，不要直接覆盖或 reset。标准库 inbox 命令只 fetch/read Git 对象并保存任务到 .local，等待时不占 NPU，不需要 Playwright。

```bash
python3 tools/cannjudge.py inbox --wait --interval 60 --timeout 1800

# 完成一轮后，等待下一轮反馈；替换 ID。
python3 tools/cannjudge.py inbox --after 上一轮request_id \
  --wait --interval 60 --timeout 1800
```

inbox 输出任务 JSON 的本地路径，Codex 读取后实施优化。若优化没有可靠收益、精度失败或队列不可用，应记录原因并停止该轮，不能发布未经验证的 ready 候选。不要为了接通通路而安装软件或修改 task-submit/驱动/系统设置。

成功候选使用已有验证与打包流程，再关联任务：

```bash
python3 tools/cannjudge.py stage --review .local/cannjudge/compliance.json \
  --request .local/cannjudge/inbox/实际request_id.json \
  --hypothesis '实际改动、profiling 依据以及本地测量结论'
python3 tools/cannjudge.py publish --candidate build/platform_candidates/实际新SHA256
# 检查源码、证据与发布目录的 Git diff，只提交本轮相关文件并正常推送。
```

## 发给现有远端 Codex 的启动指令

未配置 SSH 通知时，可将下段发给已有会话一次。已配置 `--notify-config` 时由主控直接向固定 UUID 排队通知，不再需要手工转发。

> 请与 Mac CANNJudge worker 通过此仓库 GitHub 协作，先阅读 docs/codex_handoff.md 和 docs/mac_cannjudge.md。不要安装或修改服务器环境。保留现有工作区改动，取得最新工具后运行 python3 tools/cannjudge.py inbox --wait，读取最新 ready_for_tuning 任务。以任务的父源码哈希和官方性能反馈为基线，结合本地 profiling 选择一个优化假设；平台工程只改 kernel.asc，不能按隐藏测试点编号写专属路径。使用现有 task-submit 串行单卡、每阶段不超过 60 秒，完成精度、启动检查和合规证据。通过后 stage --request --hypothesis 并 publish、提交和正常推送新 ready 候选，保留 tuning_request_id。Mac 会自动提交并回传成绩，再通过 inbox --after 等待后续反馈。先最多做两轮新候选；没有收益或缺少证据时记录原因并停止，不重复发布旧源码。

这条协议自动化的是候选、提交和反馈的交接。算法优化由远端 Codex 在现有会话中基于真实测量执行；未收到新候选前，不能宣称获得调优收益。

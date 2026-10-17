# 在 Mac 本地提交 CANNJudge

Mac 直接访问 GitHub 和比赛网站，Ascend910 负责算子开发、精度测试与 profiling。无需连接 Ascend910 的浏览器隧道，也无需开放 Chrome 调试端口。Mac 使用 Playwright 启动已安装的 Google Chrome；该方式由 [Playwright 官方文档](https://playwright.dev/python/docs/browsers#google-chrome--microsoft-edge)支持。

```text
Ascend910：修改 kernel → 单卡验证/profiling → GitHub 已验证候选
Mac：GitHub 拉取候选 → 本地 Chrome 提交 → 精度/15点耗时记录
Mac：导出精简结果 → GitHub → Ascend910 分析并继续优化
```

当前候选为 Device 完整计算、频率路径独立编译的 V9；本地验证与测量见 [V9 报告](profiled_v9.md)。发布状态以 GitHub 的 `submissions/rotary_pos_emb/latest.json` 为准，只有 ready 候选才能同步提交。2026-10-17 已在 Mac Chrome 实际完成提交 879119，Pass、15/15 通过、官方分数 48.45。平台只替换 kernel.asc，其他 7 个工程文件只读。

## Mac 首次准备

要求 Python 3.10+、Git 和已安装的 Google Chrome。在 Mac 终端执行，或在 Mac 本地打开仓库，由本地任务执行这些命令：

```bash
git clone git@github.com:Futuresxy/cann_kernel.git "$HOME/cann_kernel_judge"
cd "$HOME/cann_kernel_judge"
bash tools/mac_cannjudge.sh setup
bash tools/mac_cannjudge.sh login
```

已有本地克隆时进入对应仓库执行后两条即可；工具需更新时，在确认本地改动已保存后执行 `git pull --ff-only`。`setup` 只安装 Python 依赖，不安装 CANN，也不运行 NPU，不覆盖已安装的 Chrome。

如果 `python3` 版本不足，可指定已有的新版本，例如：

```bash
CANNJUDGE_PYTHON=python3.11 bash tools/mac_cannjudge.sh setup
```

如果项目根目录已有 `.venv/bin/python`，脚本会自动使用该环境的 Python；显式设置的 `CANNJUDGE_PYTHON` 优先级最高。未激活虚拟环境也可直接运行以上命令。

`login` 打开专用 Chrome 数据目录。手动登录平台后在终端按 Enter，登录状态留在 Mac 的 `.local/cannjudge/browser/`，不会提交到 GitHub。日常 Chrome 可以继续使用。

`login` 通过页面的“退出”链接确认登录，不要求编辑器暴露全局 Monaco API。已校准的 `cannjudge.live.json` 使用键盘粘贴和网站“复制当前文件”按钮，保留末尾换行、核对完整字节和 SHA256，并检查只有 kernel.asc 可写。剪贴板文本会暂存并在操作后恢复。`inspect` 的 `models=null` 不影响该适配器。

所有浏览器操作在 Mac 执行。本工具不通过 SSH 修改或管理 Ascend910 环境。

## 自动提交与反馈

首次 setup 使用经过真实页面校准的 live 配置，已有自定义 config 不会被覆盖。升级旧的未校准配置时，先备份 `.local/cannjudge/config.json`，再复制 `tools/judge_workflow/cannjudge.live.json` 到该路径。

```bash
# 从 GitHub 读取已验证候选；提交一次并一直等到最终反馈。
bash tools/mac_cannjudge.sh run

# 或指定本地完整冻结候选目录，避免网络同步。
bash tools/mac_cannjudge.sh run --candidate submissions/rotary_pos_emb/完整SHA256

# 持续查看 GitHub 上的新候选；最多处理 3 个不同源码，空闲 30 分钟后退出。
bash tools/mac_cannjudge.sh watch --interval 60 --idle-timeout 1800 --max-candidates 3
```

`run` 优先恢复尚未结束的提交；其次复用本地结果或已核对源码的历史记录；只有新候选才会填写并点击一次。点击意图先持久化。提交后不再修改编辑器，每 **60 秒**读取同一个结果，默认最长 **30 分钟**。排队、Running、部分测试点、缺失耗时和尚未更新的官方分数都继续等待。编译/精度/运行失败立即保存错误，不生成性能分数。

官方分数来自赛事排名。先搜索提交人的昵称，再同时核对昵称、精确提交时间和 15 点耗时，避免把旧成绩当成这次提交的分数。`platform_score_raw` 是官网原始分数；`displayed_timings_score` 只是按显示的舍入耗时计算的估算值，两者独立保存。排行榜被其他手动提交覆盖时，不猜测本次官方分数，保留待恢复记录。历史复用可以只有精确匹配源码的测试点结果，不冒用当前排行榜分数。

每个 run 生成：

| 文件 | 内容 |
|---|---|
| `run.json` | 源码哈希、提交 ID、URL、状态、官方分数和名次 |
| `cases.csv` | 15 点耗时、TBest、差距和精度 |
| `feedback.json` | 下一轮程序可读取的反馈，含成功/失败、成绩、排名和分析 |
| `leaderboard.json` | 前五名成绩与逐点性能差距，优先分析的测试点 |
| `problem-context.json` | 赛事开始/截止时间、输入约束、规则、精度和计分要求 |
| `diagnostics.json` | 失败时的页面错误全文及文件/行/列定位 |
| `result.*` / `score.*` / `diagnostics.*` | 页面正文、截图及错误日志 |

最新反馈固定为 `benchmarks/platform/runs/latest-feedback.json`。精简、无登录资料的结果自动导出到 `platform_results/rotary_pos_emb/<run-id>.json`。原始截图、账号信息与日志留在 Git 忽略目录。

与 Ascend910 上已有 Codex 会话的自动交接见 [双端协作协议](codex_handoff.md)。`watch --publish-feedback` 会通过隔离 Git 克隆发布精简结果和不可变调优任务；现有远端会话通过 `inbox` 接收，验证后带任务 ID 发布下一轮 ready 候选。Mac 不操作远端环境。

```bash
# 只验证填入 kernel 和完整回读，不点击提交。
bash tools/mac_cannjudge.sh preflight --candidate 完整冻结候选目录

# 超时/断线后继续同一提交，不重复提交。
bash tools/mac_cannjudge.sh resume --run-id 实际run-id

# 补读已完成提交的新分数、排名和赛事信息。
bash tools/mac_cannjudge.sh resume --run-id 实际run-id --refresh
```

`submit --candidate 完整冻结候选目录` 始终要求一次真实点击，不复用历史。只有明确需要重复源码的通路验证时，才额外使用 `--repeat-source`；它仍不能绕过尚未结束的提交。日常使用 `run` 即可。

GitHub SSH 22 端口连接失败时，只读 fetch 会尝试 GitHub SSH 443；不改变 SSH 配置，也不操作 Ascend910。

## 首次页面校准

```bash
bash tools/mac_cannjudge.sh inspect
bash tools/mac_cannjudge.sh inspect --url '一条真实历史提交的详情URL' \
  --output .local/cannjudge/result-inspection
```

目前真实站点字段已记录在 `cannjudge.live.json`；站点改版时重新检查提交详情链接、提交编号、整体状态、15 点耗时与错误信息后再更新配置。通用 `cannjudge.example.json` 仍保持未校准，不能直接提交。

## 日常提交

服务端发布 ready 版本后，Mac 执行：

```bash
bash tools/mac_cannjudge.sh sync
bash tools/mac_cannjudge.sh submit
```

`submit` 自带同步，所以日常可只执行第二条。同步读取一个已 fetch 的 Git 提交，校验候选源码、源码 Git 版本和全部测试证据；不执行 pull、reset 或覆盖 Mac 工作区。若 GitHub 算子已经更新、候选尚未重新验证，拒绝提交旧候选。只有完整 kernel.asc 会放入平台编辑器，全文回读一致后点击一次。

结果存于 Mac 的 `benchmarks/platform/runs/<run-id>/`。编译或精度失败不视为性能候选，超时不重复提交：

```bash
bash tools/mac_cannjudge.sh resume --run-id 实际run-id
```

需要把反馈带回服务器时，先导出精简结果，再仅提交这个结果文件：

```bash
bash tools/mac_cannjudge.sh export-result --run benchmarks/platform/runs/实际run-id/run.json
git add platform_results/rotary_pos_emb/实际run-id.json
git commit -m "Record CANNJudge result"
git push origin main
```

导出只保留源码哈希、Git 版本、平台提交编号、状态、原始得分及各点耗时。浏览器目录、Cookie、截图、页面正文、URL 和原始日志不进入导出。服务器 fetch 后即可读取此结果继续分析。推送遇到分支冲突时保留本地结果，处理冲突后再推送，不强制覆盖远端。

## Ascend910 发布步骤

CPU 编译和源码审查后，经 task-submit 串行单卡短任务完成精度、启动审计与 profiling。提交源码 Git 版本，再使用现有工具打包、冻结：

```bash
python3 tools/package.py --result 实际验证标签 --launch-profile 实际启动检查标签 \
  --compliance-review .local/cannjudge/compliance.json
python3 tools/cannjudge.py stage --review .local/cannjudge/compliance.json
python3 tools/cannjudge.py publish --candidate build/platform_candidates/实际SHA256
git add submissions/rotary_pos_emb
git commit -m "Publish validated RotaryPosEmb candidate"
git push origin main
```

发布只复制源码及规定的精度/启动/合规证据，不复制浏览器资料或输入数据。提交包依然只有 kernel.asc 相对原始模板有变化，GitHub 的发布目录不进入比赛工程。

本地测试覆盖 Git 交换、字节级回读、一次提交、等待完整性能结果、每分钟轮询、错误定位、防重复和恢复。真实 Chrome 已完成提交 879119 和官方分数采集，也已只读验证历史 Compile Error 记录的错误详情与源码定位。平台测试点编号只用于比较，不据此编写隐藏 shape 专属分支。

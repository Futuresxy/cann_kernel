# 在 Mac 本地提交 CANNJudge

Mac 直接访问 GitHub 和比赛网站，Ascend910 负责算子开发、精度测试与 profiling。无需连接 Ascend910 的浏览器隧道，也无需开放 Chrome 调试端口。Mac 使用 Playwright 启动已安装的 Google Chrome；该方式由 [Playwright 官方文档](https://playwright.dev/python/docs/browsers#google-chrome--microsoft-edge)支持。

```text
Ascend910：修改 kernel → 单卡验证/profiling → GitHub 已验证候选
Mac：GitHub 拉取候选 → 本地 Chrome 提交 → 精度/15点耗时记录
Mac：导出精简结果 → GitHub → Ascend910 分析并继续优化
```

当前候选为 Device 完整计算、频率路径独立编译的 V9；本地验证与测量见 [V9 报告](profiled_v9.md)。发布状态以 GitHub 的 `submissions/rotary_pos_emb/latest.json` 为准，只有 ready 候选才能同步提交。V4/V6 的 Host 频率表保留为历史对照。真实 Mac Chrome/平台页面仍需首次登录校准。

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

当前会话的执行位置仍是服务器，不能直接操作 Mac 桌面。因此首次启动需在 Mac 执行，或在 Mac 本地建立对应任务。这个部署方式不依赖服务器回连 Mac。

## 首次页面校准

```bash
bash tools/mac_cannjudge.sh inspect
bash tools/mac_cannjudge.sh inspect --url '一条真实历史提交的详情URL' \
  --output .local/cannjudge/result-inspection
```

根据真实页面校准 `.local/cannjudge/config.json`：提交详情链接、提交编号、整体状态、15 个测试点的编号/耗时/精度状态，以及 Monaco kernel 模型路径。完成才设置 `calibrated=true`。具体字段见 [工作流说明](cannjudge_workflow.md#首次校准)。默认配置不会盲点提交；若真实编辑器 API 不同，需先适配。

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

本地验证包括 Git 发布/拉取、独立 Mac 克隆模拟、工作区不被覆盖、旧候选与证据篡改拦截和结果导出。浏览器流程在 Linux Chromium 的本地页面测试通过；真正的 macOS Chrome 和比赛页面尚待首次登录后联调，不能把这些本地测试当成平台提交成功。

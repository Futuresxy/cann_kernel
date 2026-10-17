# 在 Mac 本地提交 CANNJudge

Mac 直接访问 GitHub 和比赛网站，Ascend910 负责算子开发、精度测试与 profiling。无需连接 Ascend910 的浏览器隧道，也无需开放 Chrome 调试端口。Mac 使用 Playwright 启动已安装的 Google Chrome；该方式由 [Playwright 官方文档](https://playwright.dev/python/docs/browsers#google-chrome--microsoft-edge)支持。

```text
Ascend910：修改 kernel → 单卡验证/profiling → GitHub 已验证候选
Mac：GitHub 拉取候选 → 本地 Chrome 提交 → 精度/15点耗时记录
Mac：导出精简结果 → GitHub → Ascend910 分析并继续优化
```

当前候选为 Device 完整计算、频率路径独立编译的 V9；本地验证与测量见 [V9 报告](profiled_v9.md)。发布状态以 GitHub 的 `submissions/rotary_pos_emb/latest.json` 为准，只有 ready 候选才能同步提交。V4/V6 的 Host 频率表保留为历史对照。2026-10-17 用户已在 Mac 完成登录；全局 Monaco API 未暴露，真实编辑器选择器仍需校准。

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

如果项目根目录已有 `.venv/bin/python`，setup 会自动使用该环境的 Python；显式设置的 `CANNJUDGE_PYTHON` 优先级最高。setup 之后的同步、导出等命令也优先使用已安装的 `.local/cannjudge/venv/bin/python`，避免重新落回系统旧 Python。未激活虚拟环境也可运行这些命令。

`login` 打开专用 Chrome 数据目录。手动登录平台后在终端按 Enter，登录状态留在 Mac 的 `.local/cannjudge/browser/`，不会提交到 GitHub。日常 Chrome 可以继续使用。

`login` 通过页面的“退出”链接确认登录，不要求编辑器暴露全局 Monaco API。`inspect` 等待页面和代码编辑器结束加载后保存检查结果；如果 `models` 为 `null`，可使用已实现的 keyboard 适配器，仍需校准实际编辑器和文件标签。

当前会话的执行位置仍是服务器，不能直接操作 Mac 桌面。因此首次启动需在 Mac 执行，或在 Mac 本地建立对应任务。这个部署方式不依赖服务器回连 Mac。

## 首次页面校准

已登录用户先更新脚本，然后只读采集编辑页和一条已有 Pass 成绩页。截图确认结果地址为 `/rotaryposemb/submission/不透明标识`；页面显示的数字提交 ID 与该标识不同。

```bash
git pull --ff-only
bash tools/mac_cannjudge.sh inspect --share
bash tools/mac_cannjudge.sh inspect --url '真实历史提交详情URL' \
  --output .local/cannjudge/result-inspection --share

git add platform_inspections/rotary_pos_emb/editor.json platform_inspections/rotary_pos_emb/result.json
git commit -m "Record CANNJudge page structure"
git push origin main
```

`--share` 只导出 DOM 结构、CSS 路径和限定的界面标签到 `platform_inspections/`；不导出输入值、代码正文、账号显示名、链接或登录数据。完整页面文字、截图和原始 inspect.json 留在 Git 忽略目录，不加入版本库。页面需要手动展开时可加 `--interactive`，按 Enter 后采集当前页面。

根据这两个结构报告完成选择器适配，配置位于 `.local/cannjudge/config.json`：

- `editor_mode="keyboard"`：通过可见界面操作，不需要全局 Monaco API。
- `editor_selector`：唯一可见的编辑器根节点；Monaco 常见 `.monaco-editor`，以实际 DOM 为准。
- `kernel_tab_selector`：唯一的 kernel.asc 文件标签，操作前会点击它。
- `kernel_active_selector`：当前激活文件的标签，操作前后必须显示 kernel.asc，不能只是永远存在的文件树节点。
- 可选 `editor_frame_selector`：编辑器在同源 iframe 时使用。

keyboard 适配器检查文件标签和焦点，经正常全选、粘贴和复制实现全文回读；源码的字节、SHA256、行数及首尾行均记录。粘贴与最终提交前分别核对全文。它只能审计所操作文件，无法像全局模型 API 那样枚举全部未打开文件，因此不声称完成额外模型的逐项核对。工具不操作其他工程文件。

已有 Pass 成绩页可以只读自动校准：

```bash
bash tools/mac_cannjudge.sh calibrate-result --result-url '真实历史提交详情URL'
bash tools/mac_cannjudge.sh check-editor
```

第一条读取可见提交元数据和执行结果表，支持状态 `Pass`，按列名区分“用时”和“最优用时”，记录输出错误占比。采用 URL 与数字 ID 分别绑定的方式。只把历史结果用于页面校准，不关联到 V9 候选。若实际页面未使用语义表格或结构有歧义，会停止并要求结构报告，不猜测 DOM。

第二条在结果配置完整、编辑器字段已适配的前提下，通过读取 kernel.asc 校验路径，再设置 `calibrated=true`；不写代码、不点击提交。配置不完整时保留未校准状态。

## 日常提交

服务端发布 ready 版本后，Mac 执行：

```bash
bash tools/mac_cannjudge.sh submit --publish-result
```

这条命令完成 GitHub 候选同步、编辑器写入/全文回读、一次提交、绑定新增详情 URL、等待同一提交的最终结果及 GitHub 成绩回传。同步读取一个已 fetch 的 Git 提交，校验候选源码、源码 Git 版本和全部测试证据；不执行 pull、reset 或覆盖 Mac 工作区。若 GitHub 算子已经更新、候选尚未重新验证，拒绝提交旧候选。只有完整 kernel.asc 会放入平台编辑器，全文回读一致后点击一次。

结果存于 Mac 的 `benchmarks/platform/runs/<run-id>/`。编译或精度失败不视为性能候选，超时不重复提交：

```bash
bash tools/mac_cannjudge.sh resume --run-id 实际run-id --publish-result
```

`--publish-result` 只在平台终态后回传精简结果，以新抓取的远端 main 为父提交，通过临时 Git 索引生成只包含该成绩文件的提交。不改动 Mac 的 HEAD、工作区或暂存区，不强推；遇到并发推送会抓取新版本重试一次。重复回传同一结果不会创建重复提交，源码 SHA/Git 版本不匹配会停止。回传失败保留运行记录，可单独重试：

```bash
bash tools/mac_cannjudge.sh share-result --run benchmarks/platform/runs/实际run-id/run.json
```

不加 `--publish-result` 时，最终成绩自动导出到 `platform_results/rotary_pos_emb/实际run-id.json`，也可手动管理：

```bash
bash tools/mac_cannjudge.sh export-result --run benchmarks/platform/runs/实际run-id/run.json
git add platform_results/rotary_pos_emb/实际run-id.json
git commit -m "Record CANNJudge result"
git push origin main
```

导出只保留源码哈希、Git 版本、平台提交编号、状态、原始得分及各点耗时、错误占比和最优耗时参考。比较使用“用时”；不把最优列当成本次成绩，不推测官方计分公式。浏览器目录、Cookie、截图、页面正文、URL 和原始日志不进入导出。服务器 fetch 后即可读取该结果继续分析、修改算子并做单卡精度/profiling 验证，发布下一候选。每轮仍需在 Mac 触发一次 submit 命令；当前没有后台常驻监听或自动改代码服务。

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

本地验证包括真实 headless Chromium 的大文件剪贴板往返、无全局 Monaco 的一次提交/跳转/15 点解析、截断和文件切换拦截、两列耗时区分、Git 发布/拉取、工作区与暂存区保持、幂等和并发回传。测试页面模拟截图显示的界面契约，尚未在真实 macOS Chrome/比赛页面自动提交；仍需这次页面结构校准与真实提交验证。相关改动仅涉及工具和文档，kernel.asc 和原模板未修改，也未占用 NPU。

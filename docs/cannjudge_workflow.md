# CANNJudge 提交与反馈工作流

**2026-10-16 更新：采用 Mac 本地 Chrome 提交模式，不需要服务器隧道。** Mac 从 GitHub 拉取已验证候选并直接提交，操作步骤见 [Mac 本地运行](mac_cannjudge.md)。本文后续的 CDP/SSH 隧道仅保留为可选接入方式。

当前状态（2026-10-15）：工具和本地浏览器测试已完成，真实站点尚未接通，未自动提交或取得新平台成绩。服务器的 HTTP 客户端与 Chromium 访问平台均出现连接关闭，也没有连接到截图中的登录浏览器。默认站点配置 `calibrated=false`，禁止点击提交，直到浏览器连接和真实结果页校准完成。

**V7 已实现 Device 完整频率计算。** 本地验证见 [V7 报告](profiled_v7.md)，GitHub 的 latest.json 指向通过源码规则、精度和启动检查的冻结候选。V4/V6 的 Host 频率表仍属历史对照，不能用于新规则下的提交。真实浏览器页面仍需首次校准，尚未取得 V7 平台成绩。

## 流程

```text
修改 kernel.asc，每轮一个有 profiling 依据的优化假设
 → CPU 编译、静态筛查、源码审查
 → task-submit 单卡短任务：精度、一次 kernel 启动审计、profiling
 → Git 保存源码；原模板打包，仅 kernel.asc 变化
 → stage 冻结源码及本地证据，记录 SHA256
 → 浏览器替换完整 kernel.asc，读回全文比对 SHA256
 → 只点击一次“提交代码”，绑定新增结果 URL 和提交编号
 → 每 15 秒读取同一提交，保存状态、日志、15 点耗时与截图
 → 比较精度通过的两个提交，与本地 PMU 对照后设计下一轮修改
```

程序执行提交、轮询和记录；Codex 根据证据修改代码。它不会根据隐藏测试点编号编写专属分支，也不会仅凭延迟猜定隐藏 shape。比较输出的几何平均加速比只是分析指标，不冒充未公开的官方计分公式。没有无限次提交循环。

本地 NPU 运行始终经过 `task-submit` 串行申请一张卡，每阶段不超过 60 秒，完成释放后再开始下一阶段。浏览器和平台结果轮询不占用本机 NPU。

## 文件

| 路径 | 用途 |
|---|---|
| `tools/cannjudge.py` | audit / stage / login / inspect / submit / resume / compare |
| `tools/judge_workflow/core.py` | 合规筛查、证据校验、提交状态、耗时比较 |
| `tools/judge_workflow/browser.py` | 浏览器连接、源码回读、一次提交、结果采集 |
| `tools/judge_workflow/cannjudge.example.json` | 未校准配置，默认禁止提交 |
| `tests/test_cannjudge_workflow.py` | CPU 浏览器测试，使用本地模拟页面 |
| `build/platform_candidates/<sha>/` | 冻结源码、Git 版本、本地验证证据 |
| `benchmarks/platform/runs/<run-id>/` | 真实平台记录、截图和日志，默认不进入 Git |
| `.local/cannjudge/` | 登录目录、站点配置、探测记录，不进入 Git |
| `benchmarks/validation/supplementary_rules_v6.json` | 历史 V6 被拦截的具体行号 |

本地模拟页面验证浏览器 API 契约，不代表真实平台已联调，也不修改任何平台判题逻辑。

## 浏览器接入

服务器已安装隔离环境 `build/platform_workflow/venv` 与 Chromium。其他电脑可安装：

可从 `dist/cannjudge_worker.zip` 取得只含浏览器工具的压缩包，或使用完整 Git 仓库；压缩包不含源码候选、登录资料与提交历史。CPU 上运行 `python3 tools/export_cannjudge_worker.py` 可重建。

```bash
python3 -m venv .venv-judge
.venv-judge/bin/python -m pip install -r tools/judge_workflow/requirements.txt
.venv-judge/bin/python -m playwright install chromium
```

Windows 使用 `.venv-judge\Scripts\python.exe`。以下 `python3` 换为对应虚拟环境 Python。

方案 A：自己电脑运行 Chrome，通过 SSH 反向隧道让服务器连接。网页流量从自己电脑发出，适合服务器连接平台失败的现状。

```bash
# 在自己电脑启动专用 Chrome，Chrome 可执行文件路径按操作系统调整。
# 专用 profile 需手动登录平台一次，不自动继承日常 Chrome 的登录。
google-chrome --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.cannjudge-chrome"

# 仍在自己电脑运行，替换 SSH_HOST，必要时增加 SSH 端口参数。
ssh -N -o ExitOnForwardFailure=yes -R 127.0.0.1:9222:127.0.0.1:9222 songxiaoyou@SSH_HOST

# 在服务器只读探测。
build/platform_workflow/venv/bin/python tools/cannjudge.py inspect \
  --cdp http://127.0.0.1:9222
```

Chrome 136 起调试端口需要搭配非默认 `--user-data-dir`。连接使用 Playwright 的 `connect_over_cdp`，适用于 Chromium 浏览器。[Chrome 说明](https://developer.chrome.com/blog/remote-debugging-port)、[Playwright API](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp)。调试端口及隧道两端均绑定本机地址，不公开到网络。

方案 B：在能访问平台、有桌面的电脑运行独立浏览器 worker：

```bash
python3 tools/cannjudge.py login --profile .local/cannjudge/browser
python3 tools/cannjudge.py inspect --profile .local/cannjudge/browser
```

`login` 由用户在浏览器手动完成登录，完成后在终端按 Enter。脚本不索要密码，不导出 Cookie、登录状态或认证请求头。截图和可见页面可能包含账号信息，保存在 Git 忽略目录。

## 首次校准

先只读探测提交页和一条已存在的提交详情页：

```bash
python3 tools/cannjudge.py inspect --cdp http://127.0.0.1:9222
python3 tools/cannjudge.py inspect --cdp http://127.0.0.1:9222 \
  --url '真实历史提交详情URL' --output .local/cannjudge/result-inspection
```

将 example 复制到 `.local/cannjudge/config.json`，根据真实页面填写：

- 新提交详情链接的选择器、详情 URL 规则；只绑定这次新增的链接。
- 提交编号和整体状态的唯一元素；编号需与详情 URL 对应。
- 15 个测试点的行、编号、当前实现耗时、精度/通过状态元素。
- 可选的 `log_selector` 和 `score_selector`，分别采集日志与官方原始得分。
- 如编辑器不使用以 `kernel.asc` 结尾的 URI，填写经实际绑定确认的 `kernel_model_uri`。

校准完成才设置 `calibrated=true`。没有臆造平台私有 API。若平台未暴露 Monaco 模型 API，工具停止，需要基于真实编辑器补充适配，不能声称完成全文回读。默认示例没有编造结果页选择器。

## 冻结与提交

V7 已完成 Device 频率迁移；后续数学改变时仍须重新验证，不能沿用旧版本精度结果。静态 `audit` 只是保守筛查，不能证明全部规则；Host 帮助函数、Device 完整计算、临时复用与持久缓存的区别仍需源码审查。

审查文件 `compliance.json` 包含 `kernel_sha256`、`reviewer`、`reviewed_at`、`device_math_notes` 和 `assertions`。必需的断言名称由 `audit` 输出的 `required_review_assertions` 给出，每项需在实际审查后填为 true。说明中应指明频率、角度、三角函数和旋转的 Device 实现位置，以及没有跨调用缓存的依据。这是技术证据，不是额外的用户授权步骤。

```bash
python3 tools/cannjudge.py audit
# 打包保留原有精度和启动门槛，并新增源码审查参数。
python3 tools/package.py --result 实际验证标签 --launch-profile 实际启动检查标签 \
  --compliance-review .local/cannjudge/compliance.json
python3 tools/cannjudge.py stage --review .local/cannjudge/compliance.json

# <sha> 使用 stage 输出的完整目录名。
python3 tools/cannjudge.py submit --cdp http://127.0.0.1:9222 \
  --config .local/cannjudge/config.json --candidate build/platform_candidates/<sha>
```

若 worker 在另一台电脑，复制完整的 `build/platform_candidates/<sha>/`，包括 `evidence/`。worker 再次校验源码和证据哈希、精度、合规审查及单 kernel 启动。仅将完整 kernel.asc 放入平台编辑器，测试工程和证据不上传平台。

编辑器读回不一致、其他已打开文件变化、多个新增结果链接、编号不符、测试点缺失或精度状态矛盾都会停止。程序先持久化点击意图，再点击一次；网络异常不自动重试点击。

## 恢复和比较

默认每 15 秒轮询，最长 15 分钟。记录 `run.json`、`result.txt`、`result.png` 和可选日志；元数据包括源码 SHA256、Git 版本、提交编号、URL、状态与微秒耗时。

```bash
# 继续读取同一提交，不点击提交。
python3 tools/cannjudge.py resume --cdp http://127.0.0.1:9222 \
  --config .local/cannjudge/config.json --run-id 实际run-id

# 点击后断线、未捕获详情 URL 时，先核对平台历史，再绑定真实详情。
python3 tools/cannjudge.py resume --cdp http://127.0.0.1:9222 \
  --config .local/cannjudge/config.json --run-id 实际run-id --result-url '核对后的真实详情URL'

python3 tools/cannjudge.py compare --baseline 路径A/run.json --candidate 路径B/run.json \
  --output benchmarks/platform/comparison.json
```

编译/精度失败的提交不进入性能比较。终态前禁止另一次提交，同一源码 SHA 不自动重复提交。多台 worker 应共享运行目录或固定只使用一个 worker。点击前后崩溃时先核对平台历史，没有证据则保留未决状态，不能清空记录来重试。

每轮对照平台退化点、本地 MTE2/MTE3/VEC/Scalar、UB 占用和非 replay Task Duration。Device 在本次调用中生成频率与三角数据后进行复用可作为候选；预先准备结果表、跨调用缓存不进入候选。

## 验证范围

```bash
build/platform_workflow/venv/bin/python tests/test_cannjudge_workflow.py
```

测试使用真实 Chromium 与本地模拟页面，覆盖全文回读、其他文件不变、一次提交、结果绑定、15 点解析、失败状态、精度错误、单位换算、候选篡改与截断、过期审查、重复提交和未校准配置拦截。没有占用 NPU，没有向真实平台提交代码。

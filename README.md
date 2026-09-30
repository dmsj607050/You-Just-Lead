<p align="center">
  <img src="docs/assets/logo.png" alt="You Just Lead" width="420">
</p>

# You Just Lead

面向机器学习竞赛的**证据驱动科研流水线**：把「提出假设 → 设计实验 → 真跑 → 核查证据 → 据此改进 → 新假设」
做成一条可审计、可中断、可恢复的闭环。

**人负责方向与算力审批，Agent 负责执行、记录、核查与建议。** 这条边界写在代码里，不写在提示词里。

## Windows 当前本地版

`1.0.0-rc.6` 候选中的 `dist/YouJustLead.exe` 是单文件程序，不需要先装 Python。它会：

1. 在「文档/YouJustLead」建好本机工作区；
2. 在本机回环地址启动后端，并打开一个无地址栏的应用窗口；
3. 首次使用进「设置 → 模型」，从预设里挑一家（DeepSeek / OpenAI / 月之暗面 / 阿里百炼 /
   本地 Ollama / 自定义），填一次密钥即可；也可以先设环境变量 `YJL_LLM_API_KEY`。
   想换一家、或者同时留着几家切换，都在这一页。

### 与托管后端的关系

Windows EXE 当前启动的是**本机后端**，模型来源与 API Key 由本机配置。评委使用的鸿蒙 HAP 已加入用户名/密码注册登录，首次注册赠送 100 积分；每 1,000 个输入加输出 token 扣 1 积分，DeepSeek 由平台服务器托管，评委不需要填写 API Key。

RC6 HAP 已配置连接 `https://nucrobot.online/yjl-cloud`。公网 HTTPS 注册、登录、登出与 DeepSeek API 计费已实测，模型 usage 与积分账本相符。最新 HAP 已在模拟器经公网完成自助注册、领取 100 积分、创建云端项目、进入工作流并发起一条短问答；重启应用后从服务端读到余额由 100.00 变为 97.95，确认扣账落库。该问答路径目前只做过这次模拟器验收；真机与正式 AGC 发布包仍未验。Windows 云客户端尚未实现，费用告警、全局限流和训练执行器仍缺，因此当前 HAP 是可在模拟器运行的 RC 候选，不是已完成正式分发验收的评委 Release。实现与验收状态见 [架构决定 D12/D13](docs/architecture.md) 和 [云端部署记录](docs/cloud_deployment.md)。

想离线看上一次的状态：`YouJustLead.exe --offline`。它不启动后端，直接打开上一次成功同步的静态快照
（页面与数据都打包在本机，一个网络请求都不发）。

界面与鸿蒙端逐屏对齐（同一套配色常量、同一组原子组件、同样的「标题 → 一行现状 → 分段导航 → 一次只渲染一段」）。
**研究循环**这一页两端各有一份、内容一致，那是这套编排框架的正面。

## 研究循环（EGRL）

编排层不是一条固定流水线，而是**一份持续更新的科研状态 + 一个固定动作空间**：

```text
ResearchState = 假设 / 实验 / 证据 / 分支 / 决策 / 图边
动作空间      = 14 个动作（检索文献、提出假设、设计实验、核查结果、终止路线、综合结论 …）
判定          = 4 种（通过 / 实现缺陷 / 实验设计缺陷 / 假设被反证）+「查不动」
```

三件让它不是「模型自说自话」的事：

- **假设必须可证伪**：没有预测与反证条件的假设，编排器不会为它设计实验，会先要求补全，补不动就终止这条路线；
- **实验必须有对照**：没写对照、没写自变量、没列控制变量的比较不算一次公平比较；
- **结果不能直接进入下一轮**：中间必须过 Evidence Validator 的**九项机器核查**
  （真的跑成了 / 有可比对照 / 指标确实动了 / **预测被满足** / 跨种子复现过 / 没有数据泄漏 /
  实现对得上假设 / 只动了一个变量 / 日志与结论一致）。九项里"没人查过"与"查了不合格"是两回事 ——
  前者记 `null` 并退回核查，后者才下判定。

判「假设被反证」看的是**预测有没有被满足**，不是指标有没有涨：复现类假设的成功恰恰是「指标没变」。
这条踩过坑 —— 一次精确复现 `0.00234` 的实验曾被判成「假设被反证」，判定语义因此改成现在这样。

**烧算力的事必须人批准。** `RUN_EXPERIMENT` / `REPLICATE_EXPERIMENT` 不会被自动触发：
编排器登记成待批准、继续推进别的路线，人点一次批准，才会提交训练作业（批准同时绑定配置的 sha256 与 GPU 预算）。

真实跑过的一圈（工作区 `workspace/aic2026`）：

| 环节 | 实际发生了什么 |
|---|---|
| 提出假设 | H0007：把 `external.stage` 从 `rgb` 换成 `fusion` 后 mAP@50-95 会高于单模态参考点 0.00234 |
| 设计实验 | 模型自己读现有配置、写出 `configs/loop/stage_fusion_vs_rgb.yaml`（只改一个自变量） |
| 真执行 | 人工批准 → JOB-0003 → EXP-0008，真实数据上的 `stage=fusion` 训练（1 epoch、10% 数据子集） |
| 证据核查 | 0.00211 ≤ 0.00234 → `prediction_met=false` → 判定 `hypothesis_falsified` |
| 据此改进 | 终止 H0007 与分支 B0007（负结果是有价值的结论，不是要修的 bug） |
| 新假设 | 综合证据后开出 3 条：三模态读取/配对是否真的成立、0.002 是否只是 1 epoch+10% 数据的产物、差距是否在噪声内 |

这说明一次实验路线确实走过了“提出 → 设计 → 批准 → 训练 → 核查 → 终止”并留下账本事件；它不等于 G4/G5 验收通过。EXP-0006/0007/0008 的 manifest 仍标为 `planned`，对应 result 标为 `completed`；三模态配对、数据泄漏与跨种子复现也仍未核实。三个已完成运行均为同一种子、1 epoch、`fraction=0.1`，不能据此外推完整训练表现。

## 交付形态：一个项目，按系统选一个包

鸿蒙端是比赛要交的，Windows 是给用户用的 —— 同一份东西的两个出口，共用同一个后端与同一套
科研契约，所以都在本仓库里构建。

| 你的系统 | 产物 | 用途 |
|---|---|---|
| Windows | `dist/YouJustLead.exe` | 当前为本地模式：自带界面、本机后端、离线可读；本机可配置模型来源与 API Key |
| Windows | `dist/competition-agent-api.exe` | 无界面的本地服务，给没有 Python 环境的机器用；当前鸿蒙端本机调试时连接它 |
| 鸿蒙 | `device/` 编出来的 HAP | 评委客户端候选：账号登录、平台托管 DeepSeek 与积分计量；公网注册、问答计费和扣账已实测，仍不是 AGC 正式发布包 |
| Linux | —— | **还没有**。后端本身跨平台，但桌面壳是 Windows 专用的（找 Edge 与 `%LOCALAPPDATA%`），要出 Linux 版得先改 `app/desktop_entry.py` |

前两个由 `tools/build_desktop_app.ps1` 与 `tools/build_local_agent.ps1` 构建，
产物位于 `dist/`（不进版本库），摘要记录在对应的 `docs/RELEASE_<版本>.md` 里。
鸿蒙端工程就在本仓库的 `device/` 子目录（2026-09-28 从 `YouJustLead-Harmony` 并进来，
理由见 `docs/architecture.md` D10），构建命令见 `docs/versioning.md`。

## 从源码跑

需要 **Python 3.10+**（`pyproject.toml` 的 `requires-python`）。依赖清单也在那里，
核心是三个包 —— 训练、追踪、桌面端各自还有额外的，按需装：

```powershell
python -m pip install "pypdf>=5.0" "PyYAML>=6.0" "Pillow>=10.0"
# 要跑真实训练再加 torch；要 MLflow 追踪再加 mlflow；要自己构建桌面端再加 keyring + pyinstaller

python main.py init
python main.py serve                       # 本地接口 + 内置界面（默认 127.0.0.1:8765）
python main.py run --config configs/<你的>.yaml
python main.py status
python -m unittest discover -s tests       # 全量测试
python main.py release-manifest            # 发布清单；退出码即「能不能发布」
```

只想用不想配环境的话，等 RC.6 的 Windows Release 发布后再下载 `YouJustLead.exe`；在此之前，GitHub 上的旧版不代表本候选。

工作区在 `workspace/<项目 id>/`，每个子目录是一个项目；有哪些项目、当前是哪一个记在 `workspace/projects.json`。

## 目录原则

- `agents/`、`tools/`、`schemas/`：后端可复用能力，不保存某一比赛的产物。
- `app/orchestrator/`：研究循环的编排层（策略 / 验证器 / 执行器 / 状态 / 回填）。
- `app/code_tools.py`：Agent 唯一能动手的地方（读、写、搜、跑命令，跑命令在隔离容器里）。
- `web/`：Windows 端内置界面（无框架、无构建步骤，由后端自己 serve）。
- `device/`：鸿蒙端 ArkTS 工程（DevEco 工程根，构建命令见 `docs/versioning.md`）。
- `workspace/`：每个子目录是一场比赛的工作区。`database/`：账本与迁移。`paper/`：论文与证据映射。

## 文档

| 文档 | 内容 |
|---|---|
| [AGENT.md](AGENT.md) | 行为约束与安全边界 |
| [docs/architecture.md](docs/architecture.md) | 架构决定记录（D1–D13：边界、契约、发布门禁、托管服务、评委账号与积分计量） |
| [docs/operation_guide.md](docs/operation_guide.md) | 操作指南（含内置 Windows 端与鸿蒙端） |
| [docs/versioning.md](docs/versioning.md) | 版本流与发布清单；什么算「可以发布」 |
| [docs/SUBMISSION.md](docs/SUBMISSION.md) | 比赛提交材料 |
| [CHANGELOG.md](CHANGELOG.md) | 每个版本改了什么 |
| [docs/RELEASE_*.md](docs/) | 历史发布说明（版本号 + commit + 产物 SHA-256） |

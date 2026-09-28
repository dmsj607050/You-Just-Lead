<p align="center">
  <img src="docs/assets/logo.png" alt="You Just Lead" width="420">
</p>

# You Just Lead

面向机器学习竞赛的**证据驱动科研流水线**：把「提出假设 → 设计实验 → 真跑 → 核查证据 → 据此改进 → 新假设」
做成一条可审计、可中断、可恢复的闭环。

**人负责方向与算力审批，Agent 负责执行、记录、核查与建议。** 这条边界写在代码里，不写在提示词里。

## 下载就能用（Windows）

1. 到 [Releases](../../releases) 下载 `YouJustLead.exe`（单文件，不需要先装 Python）。
2. 双击。它会在「文档/YouJustLead」建好工作区、在本机回环地址起后端，并打开一个无地址栏的应用窗口。
3. 首次使用在「设置 → 模型」里填 DeepSeek API Key，或先设环境变量 `DEEPSEEK_API_KEY`。

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
| 真执行 | 人工批准 → JOB-0003 → EXP-0008，真实三模态早融合训练 |
| 证据核查 | 0.00211 ≤ 0.00234 → `prediction_met=false` → 判定 `hypothesis_falsified` |
| 据此改进 | 终止 H0007 与分支 B0007（负结果是有价值的结论，不是要修的 bug） |
| 新假设 | 综合证据后开出 3 条：三模态读取/配对是否真的成立、0.002 是否只是 1 epoch+10% 数据的产物、差距是否在噪声内 |

## 交付形态：一个项目，按系统选一个包

鸿蒙端是比赛要交的，Windows 是给用户用的 —— 同一份东西的两个出口，共用同一个后端与同一套
科研契约，所以都在本仓库里构建。

| 你的系统 | 产物 | 用途 |
|---|---|---|
| Windows | `dist/YouJustLead.exe` | 给用户直接下载使用：自带界面、自带后端、离线可读 |
| Windows | `dist/competition-agent-api.exe` | 无界面的本地服务，给没有 Python 环境的机器用；鸿蒙端在电脑上连的就是它 |
| 鸿蒙 | `device/` 编出来的 HAP | 比赛交付用的端侧应用 |
| Linux | —— | **还没有**。后端本身跨平台，但桌面壳是 Windows 专用的（找 Edge 与 `%LOCALAPPDATA%`），要出 Linux 版得先改 `app/desktop_entry.py` |

前两个由 `tools/build_desktop_app.ps1` 与 `tools/build_local_agent.ps1` 构建，
产物位于 `dist/`（不进版本库），摘要记录在对应的 `docs/RELEASE_<版本>.md` 里。
鸿蒙端工程就在本仓库的 `device/` 子目录（2026-09-28 从 `YouJustLead-Harmony` 并进来，
理由见 `docs/architecture.md` D10），构建命令见 `docs/versioning.md`。

## 从源码跑

```powershell
python main.py init
python main.py serve                       # 本地接口 + 内置界面（默认 127.0.0.1:8765）
python main.py run --config configs/<你的>.yaml
python main.py status
python -m unittest discover -s tests       # 全量测试
python main.py release-manifest            # 发布清单；退出码即「能不能发布」
```

工作区在 `workspace/<项目 id>/`，每个子目录是一个项目；有哪些项目、当前是哪一个记在 `workspace/projects.json`。

## 目录原则

- `agents/`、`tools/`、`schemas/`：后端可复用能力，不保存某一比赛的产物。
- `app/orchestrator/`：研究循环的编排层（策略 / 验证器 / 执行器 / 状态 / 回填）。
- `app/code_tools.py`：Agent 唯一能动手的地方（读、写、搜、跑命令，跑命令在隔离容器里）。
- `web/`：Windows 端内置界面（无框架、无构建步骤，由后端自己 serve）。
- `workspace/`：每个子目录是一场比赛的工作区。`database/`：账本与迁移。`paper/`：论文与证据映射。

## 文档

| 文档 | 内容 |
|---|---|
| [AGENT.md](AGENT.md) | 行为约束与安全边界 |
| [docs/architecture.md](docs/architecture.md) | 架构决定记录（含 D9：科研契约只有一处定义） |
| [docs/operation_guide.md](docs/operation_guide.md) | 操作指南（含内置 Windows 端与鸿蒙端） |
| [docs/versioning.md](docs/versioning.md) | 版本流与发布清单；什么算「可以发布」 |
| [docs/SUBMISSION.md](docs/SUBMISSION.md) | 比赛提交材料 |
| [docs/RELEASE_*.md](docs/) | 历史发布说明（版本号 + commit + 产物 SHA-256） |
| [app/orchestrator/README.md](app/orchestrator/README.md) | 编排层各模块的职责与三处硬约束 |

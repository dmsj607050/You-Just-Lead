# 提交说明

**You Just Lead 1.0.0-rc.1** —— 面向机器学习竞赛的**证据驱动科研流水线**：
把「提出假设 → 设计实验 → 真跑 → 核查证据 → 据此改进 → 新假设」做成一条可审计、可中断、可恢复的闭环。

人负责方向与算力审批，Agent 负责执行、记录、核查与建议。这条边界写在代码里，不写在提示词里。

> **一个仓库装三端。** 后端（Python）、Windows 客户端、鸿蒙端（ArkTS，在 `device/`）都在本仓库里，
> 共用同一个后端与同一套科研契约。2026-09-28 之前端侧在第二个仓库，理由与合并理由见
> `docs/architecture.md` D10。

---

## 一、下载什么

发布页：**https://github.com/dmsj607050/You-Just-Lead/releases/tag/v1.0.0-rc.1**（2026-09-28 发布，标为预发布）

| 你的系统 | 下载 | 大小 | SHA-256（前 12 位） |
|---|---|---|---|
| **Windows** | `YouJustLead.exe` | 10,043,573 字节 | `6375c9721ce9` |
| **Windows** | `competition-agent-api.exe` | 9,998,270 字节 | `bba63495d627` |
| **鸿蒙** | `entry-default-signed.hap` | 3,042,268 字节 | `590f4965c7df` |
| —— | `SHA256SUMS.txt` | 268 字节 | 上面三行，平台侧可核对 |

完整摘要见 `docs/RELEASE_1.0.0-rc.1.md`。**产物不进版本库**，能证明「下载到的是不是发布的那一个文件」
的只有那份摘要与 GitHub 自己算的 digest。

### Windows：双击即用

1. 下载 `YouJustLead.exe`。
2. 双击。它会在「文档/YouJustLead」建好工作区、在本机回环地址起后端、打开一个无地址栏的应用窗口。
3. 首次使用在「设置 → 模型」里填 DeepSeek API Key（或先设环境变量 `DEEPSEEK_API_KEY`）。

不需要装 Python，Windows 10/11 自带的 Edge 就够（用它的 `--app` 模式开窗口，不自带浏览器内核）。
想离线看上一次的状态：`YouJustLead.exe --offline` —— 不启动后端，一个网络请求都不发。

`competition-agent-api.exe` 是同一个后端但**没有界面**，给没有 Python 环境的机器当执行器用；
鸿蒙端在电脑上连的就是它。

### 鸿蒙端

`entry-default-signed.hap` 是**调试签名**，装真机要走开发者模式：

```powershell
hdc install -r entry-default-signed.hap
hdc shell aa start -a EntryAbility -b com.youjustlead.agent
```

**它需要一个后端**：在电脑上起 `competition-agent-api.exe serve --port 8765`，模拟器还要做端口转发
（设备里的 `127.0.0.1` 是模拟器自己，不是主机）：

```powershell
hdc rport tcp:8765 tcp:8765
```

后端连不上时应用**不会假装能用**：它切到离线模式，直接读工作区里已经落盘的证据，
并把需要重算的能力标成「需外部执行器」。

---

## 二、最短的自证路径

想确认它不是在演示假数据，按这条走：

1. 双击 `YouJustLead.exe` → 进「研究循环」页。
2. 看「当前」段五个数字与现状行（假设 / 可证伪 / 实验 / 跑完没核查 / 设计跑不起来）。
3. 翻四个分段：**当前 / 假设 / 证据 / 决策轨迹**。
4. 「证据」段里每条实验都能点开看**九项机器核查**逐条结果
   （真的跑成了 / 有可比对照 / 指标确实动了 / 预测被满足 / 跨种子复现过 / 没有数据泄漏 /
   实现对得上假设 / 只动了一个变量 / 日志与结论一致）。
   **「未核查」与「查了不合格」是两种状态** —— 「没人查过」记 `null` 并退回核查，只有「查了不合格」才下判定。
5. 「决策轨迹」段能看到每一步为什么这么走，包括**负结果**：一条假设被反证之后被终止，并据此开出新假设。

工作区 `workspace/aic2026` 里有 8 条在册实验（`EXP-0001`~`EXP-0008`）与 3 个作业
（`JOB-0001`~`JOB-0003`），都是真实数据上的真实运行记录。

---

## 三、比赛提交契约（AIC2026）

从**官方规则 PDF（8 页）**逐条抽取并人工批准（2026-09-24），无未决问题。规则原件不改动地存在
工作区里，`competition_spec.yaml` 记了它的 sha256 与逐字段的原文出处；24 个必填字段齐全。

| 项 | 内容 |
|---|---|
| 任务 | 基于**可见光 + 热红外 + 深度**三模态的目标检测 |
| 指标 | `mAP@50-95`，越大越好 |
| 类别 | 12 类（`0 person` … `11 tricycle`） |
| 提交格式 | 每张测试图一个**同名** `.txt`，全部打包成一个压缩包 |
| 每行 | `[class_id, norm_center_x, norm_center_y, norm_w, norm_h, confidence]` |
| 坐标 | 按原图尺寸归一化，0~1 |
| 空图 | **必须交空文件**，不允许缺失 |
| 每图上限 | 100 框，超出按置信度截断 |
| 硬约束 | **禁止联网/调 API**；只用官方数据（禁外部数据）；**允许**公开预训练权重；**禁止**集成 |

**三件本工具替人守住的事**：

- 规则不清楚就**不自己假设** —— 抽不到原文的项如实标成「规则文档未记载」（如截止日期、提交次数、模型体积上限），
  并要求人工复核后才放行；
- 提交前本地格式校验（`main.py validate-submission`），**不会向比赛平台上传任何东西**；
- 烧算力的动作（跑真训练、复现）**不会被自动触发**，只登记成待批准，批准同时绑定配置的 sha256 与 GPU 预算。

---

## 四、这一版验证过什么（附证据，不虚报）

| 验证 | 证据 |
|---|---|
| 自动化测试 | **405 项全绿，0 跳过**（`python -m unittest discover -s tests`） |
| 发布门禁 | `python main.py release-manifest` → `release_ready: true`、`release_blockers: []`、退出码 0 |
| 产物可从本仓库构建 | 两个 exe + HAP 都在本仓库里现编；鸿蒙端在 `device/` 子目录里 `hvigorw clean assembleHap` → BUILD SUCCESSFUL（`typeCheck` 开着） |
| 鸿蒙端真机 | 装进模拟器、启 `EntryAbility`，四段逐一截图核对；五个数字、九项核查、动作中文名都对得上 |
| 真实科研闭环 | 工作区 `aic2026` 上跑通一整圈：假设 H0007 → 模型自己写单变量配置 → 人工批准 → `JOB-0003`/`EXP-0008` 真训练 → 判定 `hypothesis_falsified` → 终止该路线 → 开出 3 条新假设 |
| 规则关口 | `rule_approval.json`：`approved: true`，24 个必填字段齐全，`gaps: []`，逐条对照 PDF |

## 五、已知缺口（如实列出）

- **没有比赛成绩。** 在册训练是**管线级验证**（1 epoch、10% 子集），`mAP@50-95 = 0.00211 / 0.00234`
  证明的是「链路正确」，**不是模型能力**，也不是冲榜配方。这一点在规则里也有风险提示：
  低于赛事方公布的基线成绩可能被认定无效。
- **上架不可能**，缺的都是账号与资质：Release 签名的 `.app`（要 AGC 账号与云管理证书）、
  APP 备案、隐私政策 URL、AI 功能声明、内容分级。
- **上架还有个结构性障碍**：应用是纯客户端，装到别人机器上没有本机 Python 后端就全是「连接失败」。
  上架前要先定形态（陪跑式配 Windows 端 / 离线可演示 / 后端上云）。**只给评委交付的话不必走上架**——
  下载上面那两个文件即可。
- **Linux 没有产物。** 后端本身跨平台，但桌面壳是 Windows 专用的（找 Edge 与 `%LOCALAPPDATA%`）。
- **鸿蒙端没有真测试**：`device/entry/src/test` 里是 DevEco 的模板桩，唯一的断言是
  `expect('abc').assertContain('b')`。端侧的保护目前靠后端的**源码级扫描**（`tests/test_arkts_sources.py`），
  它拦的是"名字对不上"，拦不住"渲染出来不对"。
- 两个前端（`web/` 与端侧 ArkTS）的配色与图标是**各写一份**的，值现在一致，但没有测试比对它们。

---

## 六、从源码跑

需要 **Python 3.10+**。依赖清单在 `pyproject.toml`，核心三个：

```powershell
python -m pip install "pypdf>=5.0" "PyYAML>=6.0" "Pillow>=10.0"

python main.py init
python main.py serve                       # 本地接口 + 内置界面（默认 127.0.0.1:8765）
python main.py run --config configs/<你的>.yaml
python main.py paper --workspace workspace/aic2026    # 从已落盘证据生成论文包
python main.py validate-submission --path submissions/candidate.csv
python -m unittest discover -s tests       # 全量测试
python main.py release-manifest            # 发布清单；退出码即「能不能发布」
```

端侧工程在 `device/`，构建前要先配一次签名（配置不在版本库里，见
`device/build-profile.json5.example` 与 `docs/versioning.md`）。

---

## 七、文档在哪

| 文档 | 内容 |
|---|---|
| [`README.md`](../README.md) | 项目定位、交付形态、下载与运行 |
| [`docs/architecture.md`](architecture.md) | 架构决定记录 D1–D10，每条都注明验收依据 |
| [`docs/operation_guide.md`](operation_guide.md) | 操作指南（跑实验 / 连端侧 / 模拟器端口转发 / 局域网接入） |
| [`docs/versioning.md`](versioning.md) | 版本流与发布清单；什么算「可以发布」 |
| [`docs/RELEASE_1.0.0-rc.1.md`](RELEASE_1.0.0-rc.1.md) | 这一版的发布说明与产物摘要 |
| [`CHANGELOG.md`](../CHANGELOG.md) | 每个版本改了什么 |
| [`AGENT.md`](../AGENT.md) | 人机边界与必须人工审批的操作清单 |

# You Just Lead 1.0.0-rc.1 发布说明

**这一版的产物就在本机，是可下载的**（早期 `0.1.5`~`0.1.9` 那几份是历史记录，产物已不在）。

| 项 | 值 |
|---|---|
| 版本 | `1.0.0-rc.1`（`rc` 阶段：功能冻结，只剩验证） |
| 后端仓库 | `You-Just-Lead` @ `1d2b42b0d0a463b884c72acf3750c4fcf3e2dba7`（`master`，无未提交改动） |
| 端侧仓库 | `YouJustLead-Harmony` @ `8b623f5e461f2908d4d35f91c13295ab8465498a`（`master`，无未提交改动） |
| 清单生成时间 | `2026-09-28T06:59:24+00:00` |
| 发布判定 | `release_ready: true`，`release_blockers: []`，`main.py release-manifest` 退出码 0 |
| 应用版本 | `com.youjustlead.agent` / `versionName 1.0.0` / `versionCode 1000000` |

两个 exe 是用这份树构建的：清单里的 commit 是**生成清单那一刻的 HEAD**，它比构建时刻多了
发布工具那一次提交（`main.py` / `app/release_service.py` / 测试 / 文档）—— 这几样都不在
两个 exe 里（它们的入口分别只依赖 `app/desktop_entry.py` 与 `app/local_agent_entry.py → app/api_server.py`），
所以 commit 号对得上实际打包进去的代码。

## 产物与校验和

产物在本机 `release/` 目录（该目录不进版本库，所以摘要记在这里 —— 这才是事后能证明
「发出去的是哪一个文件」的东西）：

```text
6a4f5b7cd8442232306a19b7820efa856b395b010a9a9376be718e44df7a6789  competition-agent-api.exe
10ce8e04fb2f938278518ab05bfbbffc10cd9703b54f67450ddccce2dc3f6eff  YouJustLead.exe
c09cec59f182343d3c29441c8a766051da2f76ad1b3f1aef10d6414598f5dabf  entry-default-signed.hap
```

| 产物 | 大小 | 说明 |
|---|---|---|
| `YouJustLead.exe` | 9,773,093 字节 | **给用户下载的那个**：双击即用，自带界面与后端，离线可读 |
| `competition-agent-api.exe` | 9,997,267 字节 | 无界面的本地服务（`python main.py serve` 的等价物），给没有 Python 环境的机器用 |
| `entry-default-signed.hap` | 2,822,262 字节 | 鸿蒙端调试签名 HAP（端侧仓库构建产物） |
| `.app` | 缺失 | 上架要交的产物。**必须**在 DevEco 里 `Build APP(s)` 才有，需要 AGC 账号与云管理证书；清单里如实记 `present: false`、`required_for_release: false` |

列表也可以从 `release/SHA256SUMS.txt` 直接取（由 `main.py release-manifest` 生成，不是手抄的）。

## 用户怎么用

1. 下载 `YouJustLead.exe`。
2. 双击。它会在「文档/YouJustLead」建好工作区、在本机回环地址起后端、打开一个无地址栏的应用窗口。
3. 首次使用在「设置 → 模型」里填 DeepSeek API Key，或先设环境变量 `DEEPSEEK_API_KEY`。
4. 想离线看上一次的状态：`YouJustLead.exe --offline`（不启动后端，一个网络请求都不发）。

Windows 10/11 自带 Edge 即可，不需要装 Python、不需要装浏览器内核。

## 这一版验证过什么

全部 389 项自动化测试通过（`python -m unittest discover -s tests`）。除此之外，下列事情是**真跑过**的，
不是"应该能行"：

| 验证 | 证据 |
|---|---|
| 冻结后的 exe 真能起服务 | `dist\YouJustLead.exe --port 8899` 真机启动：`/health` 返回 ok，`/api/research/contract` 返回 14 个动作 / 9 项核查，工作区骨架与离线包自动就位 |
| 本地执行器 exe 真能起服务 | `dist\competition-agent-api.exe --port 8896`：`/health` 返回 ok，契约端点可用 |
| 离线页在后端完全不在时可用 | 停掉后端 → 浏览器打开 `%LOCALAPPDATA%\YouJustLead\offline\index.html#loop`：顶部徽章「离线：显示上次同步的数据」，页面上写着"这是后端起不来时打开的静态快照（时间）"，研究循环页照常显示假设/证据/决策轨迹 |
| 研究循环在真实工作区跑通一整圈 | 见下节 |
| 界面把整圈显示出来 | 研究循环页「最近的推进」显示该次推进的 3 步（核查结果 / 终止路线 / 综合结论）与每步详情；假设页显示被终止的 H0007 与 3 条新假设；证据页显示 EXP-0008 的九项核查与判定「假设被反证」 |

### 真实工作区上的一整圈

工作区 `workspace/aic2026`，真实三模态数据、真实 GPU 训练：

| 环节 | 实际发生 |
|---|---|
| 提出假设 | H0007：把 `external.stage` 从 `rgb` 换成 `fusion` 后，mAP@50-95 会高于单模态参考点 0.00234 |
| 设计实验 | 模型自己读现有配置、写出 `configs/loop/stage_fusion_vs_rgb.yaml` —— 只改一个自变量，其余键值与对照配置逐字相同 |
| 真执行 | 人工批准（研究层 + GPU 预算，批准绑定配置 sha256）→ `JOB-0003` → `EXP-0008` |
| 证据核查 | `EXP-0008` 得到 `mAP@50-95 = 0.00211` ≤ 0.00234 → `prediction_met=false` → 判定 `hypothesis_falsified` |
| 据此改进 | 终止 H0007 与分支 B0007（负结果是有价值的结论，不是要修的 bug） |
| 新假设 | 综合证据后开出 3 条：三模态读取与同 stem 配对是否真的成立、0.002 是否只是 1 epoch + 10% 数据的产物、0.00234 与 0.00211 的差距是否在噪声内 |

对照基线：`EXP-0006`（`stage=rgb`）= `0.00234`，`EXP-0007`（同配置复跑）= `0.00234`（精确复现）。

## 已知缺口（如实列出，不虚报）

- **鸿蒙端没有研究循环页**，也没有调用 `GET /api/research/contract`。它现有的页面把判定值当不透明
  字符串显示，所以不会与契约冲突，但「三端共用一套契约」在端侧目前只到「不产生第二份副本」这一层。
  ArkTS 的改动本机无法编译（没有 DevEco 构建链），所以这一版没有动端侧代码。
- **`.app` 未构建**；签名、AGC 建应用、工信部备案、隐私政策 URL、AI 功能声明都需要账号或资质。
- **比赛成绩不在这一版里**：`workspace/aic2026` 上的实验是管线级验证（1 epoch、10% 子集），
  不是冲榜配方；上面那个 `0.00211` 是"链路正确性"的证据，不是模型能力。
- H0003 / H0004 这两条假设在当前工作区**无法被一次性判决**（模型给出的理由是：它们把"三模态读取"
  与"同口径可比"两件互相冲突的要求绑在一起）。编排器把它们记成没有对照的设计，不会拿它们去烧算力 ——
  这是设计边界，不是缺陷，但界面上的"已设计实验"计数会包含这种空设计。

## 复现这一次发布

```powershell
cd 'B:\You Just Lead\competition-agent'
powershell -ExecutionPolicy Bypass -File tools\build_desktop_app.ps1      # -> dist\YouJustLead.exe
powershell -ExecutionPolicy Bypass -File tools\build_local_agent.ps1      # -> dist\competition-agent-api.exe
# 端侧 HAP：DevEco Studio 里 Build Hap(s)
python main.py release-manifest                                          # 退出码 0，并归位产物 + 写 SHA256SUMS.txt
```

清单与校验和落在 `release/`；版本号只有一处来源（仓库根的 `VERSION`），流程见 `docs/versioning.md`。

## 下一步（上传到 GitHub Release）

仓库已有远端（`https://github.com/dmsj607050/You-Just-Lead.git`）。上传产物需要**你的账号凭据**，
所以这一步留给你：

```powershell
git push origin master
git tag -a v1.0.0-rc.1 -m "You Just Lead 1.0.0-rc.1"
git push origin v1.0.0-rc.1
# 然后把 release\ 下的 4 个文件（3 个产物 + SHA256SUMS.txt）作为 Release 资产上传
```

Release 说明可以直接用本文件；`CHANGELOG.md` 里有面向用户的变更摘要。

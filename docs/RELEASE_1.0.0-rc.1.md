# You Just Lead 1.0.0-rc.1 发布说明

**这一版的产物就在本机，是可下载的**（早期 `0.1.5`~`0.1.9` 那几份是历史记录，产物已不在）。

| 项 | 值 |
|---|---|
| 版本 | `1.0.0-rc.1`（`rc` 阶段：功能冻结，只剩验证） |
| 后端仓库 | `You-Just-Lead` @ `8b39ecaa345ef7863a4f5563459e26e4e2806afb`（`master`，无未提交改动） |
| 端侧仓库 | `YouJustLead-Harmony` @ `33fd233b2a0e5c5d7a0daf16e0665f6efa1224d7`（`master`，无未提交改动） |
| 清单生成时间 | `2026-09-28T12:02:58+00:00` |
| 发布判定 | `release_ready: true`，`release_blockers: []`，`main.py release-manifest` 退出码 0 |
| 应用版本 | `com.youjustlead.agent` / `versionName 1.0.0` / `versionCode 1000000` |

三个产物各自的构建输入都与清单记录的 commit 对得上：HAP 是在端侧 `33fd233` 上现编、并装进
模拟器验过的那一个；两个 exe 的构建输入（`app/`、`schemas/`、`main.py`、`web/`）自后端 `6baa7a0`
起就没有改动过 —— 那之后的三个提交只动了 `docs/`、`CHANGELOG.md` 与 `tests/`，所以 exe 的内容
与当前 `8b39eca` 一致。这也是 `release_ready` 要求"仓库干净"的原因：产物与 commit 必须对得上，
否则差的那一个提交没人说得清。

## 产物与校验和

产物在本机 `release/` 目录（该目录不进版本库，所以摘要记在这里 —— 这才是事后能证明
「发出去的是哪一个文件」的东西）：

```text
bba63495d627a89e0f197f024040cc3f56d16149b9d94cd75e2c18a92b115c8c  competition-agent-api.exe
6375c9721ce9beb3952520b1415ae20fd2e3378201650c516c57b2174c2eeffb  YouJustLead.exe
590f4965c7df8a21826626d1360fb2b4d053fe82a665f6cc3492a40f00f4d556  entry-default-signed.hap
```

> HAP 那一行在模拟器验收的当天被重建过一次：旧构建（`48e303c8…`，3,025,374 字节）里
> 「当前」段的五个数字装机后恒为 0。缺陷与修法见下面「验证过什么」表的最后两行。

| 产物 | 大小 | 说明 |
|---|---|---|
| `YouJustLead.exe` | 10,043,573 字节 | **给用户下载的那个**：双击即用，自带界面与后端，离线可读 |
| `competition-agent-api.exe` | 9,998,270 字节 | 无界面的本地服务（`python main.py serve` 的等价物），给没有 Python 环境的机器用 |
| `entry-default-signed.hap` | 3,042,268 字节 | 鸿蒙端**调试签名** HAP，含研究循环页（在端侧仓库 `33fd233` 现编，并装进模拟器验过，命令见文末） |
| `.app` | 缺失 | 上架要交的产物。**必须**在 DevEco 里 `Build APP(s)` 才有，需要 AGC 账号与云管理证书；清单里如实记 `present: false`、`required_for_release: false` |

列表也可以从 `release/SHA256SUMS.txt` 直接取（由 `main.py release-manifest` 生成，不是手抄的）。

## 用户怎么用

1. 下载 `YouJustLead.exe`。
2. 双击。它会在「文档/YouJustLead」建好工作区、在本机回环地址起后端、打开一个无地址栏的应用窗口。
3. 首次使用在「设置 → 模型」里填 DeepSeek API Key，或先设环境变量 `DEEPSEEK_API_KEY`。
4. 想离线看上一次的状态：`YouJustLead.exe --offline`（不启动后端，一个网络请求都不发）。

Windows 10/11 自带 Edge 即可，不需要装 Python、不需要装浏览器内核。

## 这一版验证过什么

全部 403 项自动化测试通过（`python -m unittest discover -s tests`），连续多轮全绿。除此之外，下列事情是**真跑过**的，
不是"应该能行"：

| 验证 | 证据 |
|---|---|
| 冻结后的 exe 真能起服务 | `dist\YouJustLead.exe --port 8899` 真机启动：`/health` 返回 ok，`/api/research/contract` 返回 14 个动作 / 9 项核查，工作区骨架与离线包自动就位 |
| 本地执行器 exe 真能起服务 | `dist\competition-agent-api.exe --port 8896`：`/health` 返回 ok，契约端点可用 |
| 离线页在后端完全不在时可用 | 停掉后端 → 浏览器打开 `%LOCALAPPDATA%\YouJustLead\offline\index.html#loop`：顶部徽章「离线：显示上次同步的数据」，页面上写着"这是后端起不来时打开的静态快照（时间）"，研究循环页照常显示假设/证据/决策轨迹 |
| 端侧要的数据真的在接口上 | 服务端实查：契约返回 14 动作 / 9 核查 / 5 判定 / 3 作业状态 / 6 步骤状态（都带中文名与色调）；快照里每条证据带 9 对 `{name, value}`、每条假设带 `falsifiable` |
| **端侧真的编译过** | 用 DevEco 自带的 hvigor 6.26.4 + SDK 全量重编：`hvigorw clean assembleHap --no-daemon` → **BUILD SUCCESSFUL**。`typeCheck` 已打开，所以类型错误也会被拦；这次就是它抓出 `ResearchContract` 漏声明了后端早在发的 `job_statuses` / `step_statuses`（8 个错误） |
| 端侧 HAP 由这一版现编 | `entry-default-signed.hap`：2,822,262 → **3,042,268** 字节，含新建的研究循环页 |
| 端侧源码的结构检查（补充） | `tests/test_arkts_sources.py`（8 项）：6 个端侧文件的括号配平、import 的符号都真的导出过、新页面上的 60 余个 `this.xxx` 都在那个 struct 上、**页面声明的接口字段与后端实际在发的对得上** |
| **端侧真的在模拟器上跑起来过** | 把这一版现编的 HAP（3,042,268 字节，`590f4965…`）装进模拟器（`127.0.0.1:5555`）并 `aa start` 启 `EntryAbility`：侧栏第九项「研究循环」在「复现」与「设置」之间；四段（当前 / 假设 / 证据 / 决策轨迹）逐一截图核对 |
| 端侧显示的每个数字都对得上 | 「当前」段五个数字 **10 / 5 / 13 / 0 / 3**，与同一批状态算出的现状行「假设 10（可证伪 5） · 实验 13 · 分支 8/10 活跃 · 证据 8 · 其中 3 个设计跑不起来」逐项一致 |
| 端侧显示的是后端算出来的判定，不是自己编的 | 「假设」段 H0001 徽章「进行中」+ 黄色提示「这次设计跑不起来：没有对照也没有配置（生成它时还没有记下原因）」；「证据」段 EXP-0008 徽章「假设被反证」，九项核查逐条是/是/是/否/否/**未核查**/是/是/是；「决策轨迹」段的动作名是中文（补全假设 / 修复实现）—— 这三处的名字都来自 `GET /api/research/contract` |
| **模拟器上抓到一个编译抓不到的缺陷** | 五个数字原先恒为 0，而同一批状态算出的现状行是对的：`@Builder` 的参数**按值取**，父组件重建不会把新值推进去。改成 `@Component` + `@Prop`（`Widgets.ets` 的 `MetricCard`）后恢复，重编重装复验为 10 / 5 / 13 / 0 / 3。同一次还改了 `ForEach` 的 key（原先是两个列表长度，改措辞不会重绘） |
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

- **端侧在模拟器上验过，没在真机上验过**。四段与五个数字都逐项核对过了（见上表），
  但仍缺：真机窄屏与深色模式下的布局、字体放大后的截断、轮询定时器在页面销毁时是否真的被清掉
  （这次没有直接观测到）、契约取不到时的退化显示（动作名退回内部名字）长什么样。这些要装机才能下结论。
- **`.app` 未构建**；签名、AGC 建应用、工信部备案、隐私政策 URL、AI 功能声明都需要账号或资质。
- **「批准执行」与「人提假设」两个动作两端界面都还没有入口**。后端接口都在
  （`POST /api/research/loop/run`、`POST /api/research/loop/hypotheses`），但要在界面上点，
  得再补一轮；目前只能走接口。
- **比赛成绩不在这一版里**：`workspace/aic2026` 上的实验是管线级验证（1 epoch、10% 子集），
  不是冲榜配方；上面那个 `0.00211` 是"链路正确性"的证据，不是模型能力。
- H0003 / H0004 这两条假设在当前工作区**无法被一次性判决**（模型给出的理由是：它们把"三模态读取"
  与"同口径可比"两件互相冲突的要求绑在一起）。编排器把它们记成没有对照的设计，不会拿它们去烧算力 ——
  这是设计边界，不是缺陷，但界面上的"实验总数"计数会包含这种空设计（另有一个数字单独说明）。

## 复现这一次发布

```powershell
cd 'B:\You Just Lead\competition-agent'
powershell -ExecutionPolicy Bypass -File tools\build_desktop_app.ps1      # -> dist\YouJustLead.exe
powershell -ExecutionPolicy Bypass -File tools\build_local_agent.ps1      # -> dist\competition-agent-api.exe
python main.py release-manifest                                          # 退出码 0，并归位产物 + 写 SHA256SUMS.txt
```

端侧 HAP 用 DevEco 自带的 hvigor 从命令行编（不必打开 IDE）：

```powershell
$deveco = 'B:\Deveco_studio\setup\DevEco Studio'   # 本机的 DevEco 安装位置
$env:DEVECO_SDK_HOME = "$deveco\sdk"
$env:NODE_HOME = "$deveco\tools\node"
$env:PATH = "$deveco\tools\node;$deveco\tools\ohpm\bin;$deveco\tools\hvigor\bin;$env:PATH"
Set-Location 'B:\YouJustLead'
hvigorw.bat clean assembleHap --no-daemon           # -> entry\build\default\outputs\default\entry-default-signed.hap
```

那次模拟器验收是这么走的（后端要在本机 8765 上起着，且已做过 `rport`，见 `docs/operation_guide.md` 第 5 节）：

```powershell
$hdc = "$deveco\sdk\default\openharmony\toolchains\hdc.exe"
& $hdc list targets                                  # 127.0.0.1:5555
& $hdc rport tcp:8765 tcp:8765
& $hdc install -r 'B:\YouJustLead\entry\build\default\outputs\default\entry-default-signed.hap'
& $hdc shell aa start -a EntryAbility -b com.youjustlead.agent
& $hdc shell uitest dumpLayout -p /data/local/tmp/layout.json   # 按文本找控件坐标，别靠截图目测
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

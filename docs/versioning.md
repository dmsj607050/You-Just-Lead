# 版本流与发布清单

这份文档规定「一个版本」是怎么被描述的，以及**什么算可以发布**。
配套工具：`python main.py release-manifest`（`app/release_service.py`）。

---

## 1. 单一版本来源

版本号只有一处：仓库根的 `VERSION` 文件。格式

```text
MAJOR.MINOR.PATCH                  正式版
MAJOR.MINOR.PATCH-<stage>.<序号>   预发布
```

`<stage>` ∈ `dev` / `alpha` / `beta` / `rc`。写歪了工具会**直接拒绝**，不猜、不兜底。

**端侧必须跟着走**：`device/AppScope/app.json5` 里的 `versionName` 必须等于 `VERSION` 的
`MAJOR.MINOR.PATCH` 部分（`1.0.0-rc.1` ↔ `versionName: "1.0.0"`）。
对不上就是「文档里的版本 ≠ 实际构建的版本」，工具会把它记成阻塞项。

当前：`1.0.0-rc.6`。Python 全量测试基线为 `473` 项；本次候选源改动后的完整复跑结果见 CHANGELOG。HAP 在 DevEco Hvigor 下清理重编并安装至 `127.0.0.1:5555`；模拟器实点核对项目选择、空审计状态、工作流余额、窄窗口布局，以及数据、实验台账、写作空态到工作流动作区的首用路径和中文文案。HAP 在工作流建议与数据空态中明确了“云端暂无数据上传或页面内审计入口”；该说明已在模拟器实看。溯源页布局树确认不再暴露云主机绝对目录；非最大化窗口中“复现”入口完整可见并已点通。复现页当前从服务端收到 `docker executable not found (docker)`，验收项目没有计划或运行记录；HAP 已改为提示联系平台管理员检查容器环境，保留诊断文本。第一次设置页重排曾触发模拟器导航故障，回退后那次 HAP 为 3,416,140 字节，SHA-256：`E6B9F94CA3875014CC2F6A9B607FF9B28ADED602F164DE094F844B54050D45D2`；模拟器实点确认当时设置页可打开。该包为 DevEco 调试签名验证包，不是 AGC Release 包。鸿蒙真机、系统深色模式、字体放大仍未验。

2026-09-30 第二次设置页 UI 迭代后，Python 全量测试实跑 `475` 项通过；Hvigor 清理构建 `BUILD SUCCESSFUL`（35 项任务）。HAP 已安装至 `127.0.0.1:5555`，模拟器目视检查设置总览、运行环境、平台托管模型和高级诊断。当前工作树验证包 3,556,835 字节，SHA-256：`16F149F670F74F4BB3404BB2126CF974C65897898042C4B3215FE1B8D0575BD5`；截图和布局树位于 `build/settings-ui-review/`。这仍是 DevEco 调试签名验证构建，不是 AGC Release 包。

Windows Web 已在 1280×720、390×844 与 320×568 浏览器视口实测；正文间距、窄屏顶栏和无横向溢出已核对，空审计显示明确空态。当前源码重建的 API EXE 和桌面 EXE 放在 `build/` 隔离目录，没有覆盖 `dist/`。API EXE 与桌面 EXE 的 `--help` 均退出码 0；API EXE 实启后 `/health` 返回 `status: ok` 并报告隔离工作区；桌面 EXE 实际提供首页、CSS、JS，均返回 HTTP 200。桌面 EXE 首启时使用 Edge 应用窗口；修正兼容层进程交接后，桌面 EXE 会在 Edge 窗口存活期间保持 API 服务。向专用 Edge profile 的 `You Just Lead` 窗口发送 `WM_CLOSE` 后，Edge 进程组退出，桌面 EXE 退出码 0，端口释放。

API EXE：10,220,048 字节，SHA-256：`954435B42FE0FA3C168C254DC4EC5305FAED9FBEDB6A3672070498E5BA421F80`。桌面 EXE：10,276,832 字节，SHA-256：`AD930310305E92D2B0EF6390C874B6E407362D463B865CF447113FD938D78F18`。2026-09-30 绕过本机失效代理只读检查 `https://nucrobot.online/yjl-cloud/api/health`，返回 `status: ok, mode: cloud`；公网云服务的账号、问答计量与扣账此前已有实测记录，本次没有再次发送会扣积分的模型请求。当前工作区有未提交改动，发布清单仍为 `release_ready: false`，没有创建正式 Release。

产品交付边界：Windows EXE 仍启动本机后端，不能直接使用云账号；RC6 鸿蒙 HAP 使用云账号和服务器托管 DeepSeek，评委无需填写 API Key。HAP 内注册、登录、领取积分、建项目、进入工作流与直接问答均已在模拟器实测；一次短问答扣除 2.05 积分并在重启后从服务器余额确认。云端交叉账号隔离仅有自动化测试，存储配额、费用告警、全局并发限制、管理员停用开关、密码恢复和账号删除尚缺。真实实验 EXP-0008 已产生负结果和 `hypothesis_falsified` 记录，但 manifest/result 状态与决策文字仍冲突，泄漏核查与跨种子复现也未完成；训练、重型审计和复现仍无配对执行器。G4/G5/G6 仍不能标记通过；HAP 真机/正式分发条件与 Release 门禁也未满足。

---

## 2. 版本流

```text
dev ──► alpha ──► beta ──► rc ──► release
│        │         │       │        │
│        │         │       │        └ 正式发布：产物齐、仓库干净
│        │         │       └ 候选：功能冻结，只剩验证
│        │         └ 外部可试：可能有已知缺口
│        └ 小范围可跑：接口可能变
└ 开发版：默认状态；**不算发布**
```

只有 `rc` 与 `release` 算「发布阶段」。其余阶段生成清单没问题，但 `release_ready` 一定是 false。

---

## 3. 一条命令

```powershell
cd 'B:\You Just Lead\competition-agent'
python main.py release-manifest            # 写 release/release_manifest.json 并打印
python main.py release-manifest --print    # 只看不写
```

**退出码就是答案**：`0` = 这个版本可以发布，`1` = 不可以（并打印 `release_blockers` 说明原因）。

清单记录（对应目标里点名的字段）：

| 字段 | 来源 |
|---|---|
| `version` / `version_core` / `stage` | `VERSION` |
| `build_time` | 生成时刻（秒级 UTC） |
| `git.backend` | 工作仓库的 commit、分支、是否有未提交改动 |
| `schema.data_contracts` | `schemas/contracts.py::CONTRACT_VERSION` |
| `schema.db_migration` | `database/ledger.py::SCHEMA_VERSION`（**迁移版本就是它**） |
| `schema.experiment_registry` / `schema.training_scaffold` | 各自的模块常量 |
| `workspace_schema` | 工作区目录清单 + 清单摘要 |
| `components.backend.python` | 运行时 Python 版本 |
| `components.device` | `bundleName` / `versionName` / `versionCode` |
| `artifacts[]` | 每个产物的路径、字节数、**SHA-256**、是否存在、是否发布必需 |

不编数字：产物不在就记 `present: false`、`sha256: null`，路径记成「本来该在哪」。

---

## 4. 什么算可以发布

三条**同时**成立（`release_ready`）：

1. 版本号处于 `rc` 或 `release` 阶段；
2. 所有「发布必需」的产物都在（API EXE、Windows 桌面 EXE、端侧 HAP）；
3. 工作仓库**没有未提交改动** —— 发布必须从干净的提交切出来，否则 commit 号对不上实际内容。

缺哪条就会出现在 `release_blockers` 里。这条门槛针对的是一个已发生过的真问题：
`docs/RELEASE_0.1.5.md` 记了安装包的 SHA-256，而 `0.1.6`~`0.1.9` 都没记 ——
**靠人记的纪律一定会退化**，所以把它变成工具会拦住的条件。

---

## 5. 切一次发布要做的事

```text
1. 改 VERSION（并同步端侧 AppScope/app.json5 的 versionName）
2. 编译产物：后端 dist/competition-agent-api.exe、dist/YouJustLead.exe、端侧 HAP
3. python main.py release-manifest        # 退出码必须是 0；并把产物归位到 release/ 并写出 SHA256SUMS.txt
4. 写 docs/RELEASE_<版本>.md，**贴进清单里的 version / commit / 产物 SHA-256**
5. 提交（清单与产物在 release/，那是输出目录、不进版本库；摘要进发布说明才留得下来）
6. 打 tag，并把 release/ 里的产物上传到分发位置
```

端侧 HAP 用 DevEco 自带的 hvigor 从命令行编（不必打开 IDE）。
`hvigorw.bat` 是 DevEco 装在 `tools\hvigor\bin` 里的**全局**脚本，不是工程文件 —— 进到工程根跑就行：

```powershell
$deveco = 'B:\Deveco_studio\setup\DevEco Studio'
$env:DEVECO_SDK_HOME = "$deveco\sdk"; $env:NODE_HOME = "$deveco\tools\node"
$env:PATH = "$deveco\tools\node;$deveco\tools\ohpm\bin;$deveco\tools\hvigor\bin;$env:PATH"
Set-Location 'B:\You Just Lead\competition-agent\device'; hvigorw.bat clean assembleHap --no-daemon
```

端侧工程自 2026-09-28 起就在本仓库的 `device/` 里（此前是第二个仓库 `YouJustLead-Harmony`，
理由见 `docs/architecture.md` D10）。**它不是必须放在仓库根才能构建** ——
上面这条命令就是在子目录里跑的，已实测通过。

**克隆之后要先配一次签名**，否则编出来的是 `entry-default-unsigned.hap`，而发布清单要的是
signed 那一个，会直接报阻塞。配置本身不在版本库里：`device/build-profile.json5` 同时装着
签名口令与本机绝对路径，两样都不该进公开仓库，所以它被 `.gitignore` 掉了，版本库里留的是
`device/build-profile.json5.example`。复制一份、在 DevEco 里 `File > Project Structure >
Signing Configs` 配一次即可（它会把口令与路径填回来）。

第 3 步会把清单里**确实存在**的产物复制到 `release/`（复制，不是移动：`dist/` 仍是构建产物的原处），
并写出 `release/SHA256SUMS.txt` —— 下载页要贴的那几行是算出来的，不是手抄的。缺的产物直接跳过。

第 4 步不是仪式：产物不进版本库（`/release/` 已在 `.gitignore` 里），
所以**只有发布说明里的摘要**能在事后证明「发出去的是哪一个文件」。
`tests/test_release_manifest.py::ReleaseNoteDisciplineTests` 会检查每份发布说明
要么标成历史记录、要么留下摘要。

> 顺带记一个踩过的坑：`.gitignore` 里原先**漏了** `/release/`，于是 `release/` 是「未跟踪」而不是
> 「被忽略」—— 十几 MB 的安装包随时会被一次 `git add -A` 带进版本库。
> 现在已经补上规则，并由 `ReleaseOutputIsIgnoredTests` 钉住（用 `git check-ignore` 判定）。
> 判"是不是被忽略"要看 `git status --ignored`（`??` = 未跟踪、`!!` = 已忽略），
> 别只看 `git check-ignore` 的回显 —— 那一行里的路径名很容易被误读成 pattern。

---

## 6. 还没做的（需要用户侧账号或资质）

当前只有 DevEco **调试签名**的 HAP，`.app` 从没构建过（清单里如实记 `present: false`）。
下面这些**不能靠代码完成**：

| 事项 | 卡在哪 |
|---|---|
| Release 签名（`.app`） | 需要 AGC 账号与云管理证书；产物要按 26.0.0 及以上流程在 DevEco 里 `Build APP(s)` |
| AGC 建应用 | 包名必须是 `com.youjustlead.agent` |
| APP 备案 | 工信部要求，需要主体信息 |
| 隐私政策 URL | 要如实写明「提示词会发往第三方大模型」 |
| AI 功能声明 / 内容分级 | 需要主体信息 |
| 软著 | 非必选资质 |

这些属于六个 Gate 里的 **G6**。按目标的要求，G6 排在真实科研闭环（G4/G5）之后 ——
但**清单工具已经就绪**，等产物齐了、仓库干净了，一条命令就能给出可审计的版本记录。

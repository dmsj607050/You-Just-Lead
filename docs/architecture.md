# 架构边界与决定（Architecture Decision Record）

适用范围：You Just Lead 的本地原型与托管客户端形态（鸿蒙端 + Python API + 外部服务）。
状态：科研工作流保留本地执行模式；D13 的账号、用户隔离与 token 计量已部署至 `nucrobot.online`，公网 HTTPS 注册、登录、问答计费与登出已实测。Windows 客户端目前仍是本地模式；鸿蒙 RC6 已连接云服务，但未形成正式 Release。

这份文档回答一个问题：**什么东西该在哪一侧。** 每一条都注明了验收依据，
所以它不是愿望清单，而是可以在机器上核对的事实。

---

## 1. 三条边界

```text
鸿蒙端（Device Core）        本地 Python 后端（Local Executor）      外部服务
─────────────────────       ─────────────────────────────────       ──────────
项目 / 决策 / 证据            数据审计（重型）                        LLM
工作区读写                    真实训练                               文献检索
规则就绪度与批准              检索聚合                               训练运行时
账本（JSONL）                 大模型调用
离线状态读取                  论文包生成
人机交互（两道人工关口）
```

一句话：**鸿蒙端负责项目、决策、证据、工作区和可解释的人机交互；后端负责计算密集型与外部资源型任务。**
后端既可由本机启动，也新增显式开启的云账号模式。云模式只能绑定回环地址、由 HTTPS 反向代理对外；本地模式的工作区和模型来源设置仍沿用原有边界。

---

## 2. 已生效的决定

### D1 人主导：证据录入 ≠ 规则批准（两道独立关口）

`agents/rules_agent.py` 与端侧 `common/LocalRuleGate.ets` 都严格分两步：
录入证据只写证据、`requires_human_confirmation` 保持 true；批准是另一道关口，要人写复核说明。
**再录一次证据会撤回上一次批准**（证据变了，原来的复核结论不再成立）。

- 依据：`tests/test_workflow_extensions.py::test_rule_evidence_endpoints_record_anchors_without_approving`（后端）、
  端侧装机验收（2026-09-24，见 `PROJECT_STATUS.md` 2.2 节）。

### D2 工作区是**唯一**的审计单元

工作区在用户可见目录 `文档/YouJustLead`（端侧）/ `workspace/<project_id>`（后端）。
**项目的一切证据必须在工作区里**：规格、账本、证据记录、数据审计、实验手册与结果、论文证据图。
理由是目标里那条验收——"换一台机器、换一个 Workspace 重新跑一次"：拷得走的工作区才谈得上复现。

2026-09-24 修掉的一处违例：论文证据图原先默认写到 `workspace.parent.parent/paper/generated`
（即仓库根，**在工作区之外**），而读取方按 `project_root` 读——两边只因为工作区恰好位于
`<repo>/workspace/<id>` 才碰巧一致。现在写入与读取都按 `<workspace>/paper/generated/`。

- 依据：`paper/generator.py::generate_paper_package`（默认位置）、
  `app/trace_service.py::paper_package_report`（读取位置）、
  `tests/test_workflow_extensions.py::test_paper_evidence_lands_where_the_trace_chain_reads_it`、
  `::test_workspace_can_be_relocated_without_losing_the_evidence_package`。
- **副作用（已清理）**：真实项目里那份旧产物原先在 `competition-agent/paper/generated/`（工作区之外），
  新规则下它不再被溯源链读到，`/api/trace` 的论文链会显示"未生成"。当时没有删它（那是历史证据）。
  **2026-09-28 清掉了** —— 工作区里已有同一份的更新版本（`workspace/aic2026/paper/generated/`），
  留着一份读不到的副本只会让人以为论文生成坏了。要恢复显示就在工作区里重新生成：
  `python main.py paper --workspace workspace/<项目 id>`。

### D3 账本按项目隔离，且 schema 有版本与迁移

两张表都带 `project_id`，`experiments` 主键是 `(project_id, experiment_id)`，读取一律按项目过滤。
库上有 `user_version`，v1→v2 迁移是原地的、事务内的，旧行归 `current_competition`。

- 依据：`database/ledger.py`（`SCHEMA_VERSION`、`ledger_for_workspace`）、
  `tests/test_ledger_project_isolation.py`（12 项）、真实库迁移后 21 条事件 + 3 条实验一条不少。

### D4 状态读取端侧化，重计算执行器化

后端断开时，端侧仍要能看：工作区、规则与批准、数据审计摘要、实验历史、账本、论文证据；
而检索 / 大模型 / 训练 / 重型审计标注为**需要外部执行器**，端侧不假装能做。

- 依据：`entry/src/main/ets/common/LocalStatus.ets`、`view/LocalStatusPage.ets`，
  装机验收（后端断开 + 同步真实产物逐条对账，见 `PROJECT_STATUS.md` 2.2 节）。

### D5 单一数据契约（`schemas/contracts.py`）

规则域有**两套实现**（Python / ArkTS），所以字段名与类型必须来自一处声明。
`tests/test_canonical_contracts.py` 拿**真实产出**核对：字段集合、类型、以及"没有未声明的字段"，
并检查端侧读/写那段源码里声明的字段名是否还在。

- 依据：`schemas/contracts.py`（8 份契约）、`tests/test_canonical_contracts.py`（20 项）。
- **能力边界**：端侧那半是**源码级检查**，不是运行时校验（ArkTS 没有 JSON Schema 校验库，
  也不在 Python 进程里）。端侧运行时的一致性由装机验收负责，别把这两件事混为一谈。

### D6 落盘失败要重试，且不留残渣

`tools/files.py` 的原子写是**所有 JSON 落盘的唯一漏斗**：唯一临时名 + 有界退避重试
（`PermissionError` / `WinError 5,32,33`，总预算 1s）+ `finally` 清理临时文件；读侧同样容忍。
理由是 Windows 上 `os.replace` 会撞并发读者，而这不是"某个测试的问题"，是持久层缺陷。

- 依据：`tools/files.py`、`tests/test_files_atomic.py`（确定性回归，在旧实现上必然失败）。

### D7 旧决策：桌面仪表盘废弃（当时的原型以鸿蒙端为主）

<!-- 这一条被更正过三次：最早文档写"源码已经不在了"（不是事实）；后来写"源码在第三方仓库、
     归属待用户拍板"；再后来按"内容都发到自己的 GitHub"搬进了客户端仓库。 -->

**2026-09-24 用户拍板**：比赛原型只保留鸿蒙应用，旧的仪表盘不要了。据此：

| 项 | 实况 |
|---|---|
| 端侧工程 | **只有端侧应用**（`entry/` 等 DevEco 工程），没有 `desktop/`。当时它在客户端仓库 `YouJustLead-Harmony`，2026-09-28 并入本仓库的 `device/`（见 D10） |
| 仪表盘源码 | **已从仓库移除**；历史留在端侧工程那串提交里（引入 `43aeaf1`、移除 `a26ca7f`），需要时可取回。那段历史现在也在本仓库里 —— 它随 `device/` 一起并了过来 |
| 第三方托管 | 已废弃，`git.chatgpt-team.site` 不再被任何东西引用 |
| 本机残留 | **无**：安装包与历史镜像已按用户要求删除。仪表盘历史的唯一留存处是端侧工程那串提交（`43aeaf1` 引入 / `a26ca7f` 移除） |
| 当时的判定 | 旧仪表盘不在比赛原型架构内，也不再作为交付物存在；该结论不限制 D12 新确认的 Windows 可下载客户端 |

**两件名字里带 dashboard / desktop、但不是那个仪表盘的东西，不要连坐删掉**：

- `app/dashboard_service.py` 与 `GET /api/dashboard`：这是后端给**端侧应用**的聚合快照接口，
  端侧 `BackendClient.ets` 正在调它。
- `app/local_agent_entry.py` + `tools/build_local_agent.ps1`：Windows **本地执行器**
  （产物 `dist/competition-agent-api.exe`，发布清单里 `required_for_release=true`）。
  端侧应用连的就是它。

当前原型的交付形态：**鸿蒙端应用 + 本地 Python 执行器**。这是现有实现的描述；面向用户的目标交付形态见 D12。

### D8 版本只有一处来源，发布与否是可判定的

版本号只在 `VERSION` 一处；端侧 `AppScope/app.json5` 的 `versionName` 必须等于它的
`MAJOR.MINOR.PATCH` 部分。`python main.py release-manifest` 产出 `release/release_manifest.json`，
**退出码即答案**（0 可发布 / 1 不可发布），并在 `release_blockers` 里说明原因。

可以发布要同时满足三条：版本处于 `rc`/`release` 阶段、发布必需的产物都在、工作仓库没有未提交改动。

- 依据：`app/release_service.py`、`tests/test_release_manifest.py`（25 项）、`docs/versioning.md`。
- 针对的真问题：`docs/RELEASE_0.1.5.md` 记了安装包 SHA-256，`0.1.6`~`0.1.9` 都没记 ——
  纪律靠人记就会退化，所以改成工具会拦住的条件。
- 未被这条决定覆盖的：Release 签名（`.app`）、AGC、备案、隐私政策、AI 声明都要用户侧账号或资质，
  见 `docs/versioning.md` 第 6 节。

### D9 科研词汇只有一处定义，两个前端从接口取

D5 管的是**字段**（一份 JSON 长什么样）。这一条管的是**词汇**：动作名、九项核查、
判定值、假设/分支状态、图边类型，以及它们的中文名与色调。

它只在 `schemas/research.py` 定义一次，后端发在 `GET /api/research/contract`，
Windows 端的 `web/` 与鸿蒙端的 ArkTS 都从那里取。`tests/test_research_contract.py`
两头都守：契约自洽（每个动作都有中文名、待批准与动作空间对得上、要动算力的动作
**不允许**出现在自由选择集合里），以及两个前端的源码里**搜不到**这些名字的第二份。

- 针对的真问题：Windows 界面原来自己抄了一份动作中文名表。抄的代价不是"多写几行"，
  而是**静默漂移** —— 后端删掉一个动作，界面还显示着它的中文名，谁都不会发现。
- 依据：`schemas/research.py::research_contract`、`tests/test_research_contract.py`（17 项）、
  `tests/test_web_views_render.py`（7 项，用真实脚本渲染真实快照，拦住"视图引用了不存在的变量"）。
- **端侧没有反射，所以取值要成对发**：`evidence[].checks` 是 `[{name, value}]`、
  `hypotheses[].falsifiable` 是后端算好的。不这么做，ArkTS 想按名字取字段就得把那九个核查项
  的名字抄进源码 —— 那就等于契约有了第二份定义，而后端加第十项时端侧会静默地少显示一项。
- **端侧编译过一次，但不是每次改动都编**：用 DevEco 自带的 hvigor（`hvigorw clean assembleHap --no-daemon`，
  见 `docs/versioning.md`）全量重编是 BUILD SUCCESSFUL，并且 `hvigor-config.json5` 的 `typeCheck` 已打开 ——
  就是它抓出 `ResearchContract` 漏声明了后端早在发的 `job_statuses` / `step_statuses`。另外
  `tests/test_arkts_sources.py`（17 项）在没有构建链的环境里守着括号配平、import 的符号真的导出过、
  页面上的 `this.xxx` 真的存在，以及**页面声明的字段与后端实际在发的一致**。
- **这一层在模拟器上真的跑起来过**：现编的 HAP 装进模拟器启 `EntryAbility`，四段
  （当前 / 假设 / 证据 / 决策轨迹）逐一核对 —— 五个数字 10 / 5 / 13 / 0 / 3、EXP-0008 的九项核查
  逐条显示、动作名显示中文。顺带在装机时抓到 `@Builder` 按值传参导致数值不刷新的缺陷，
  改成 `@Component` + `@Prop` 才对。
- **`@Builder` 的刷新边界（2026-09-29 补记，比上面那句更准确）**：`@Builder` 体内读到的状态变了
  **不会**重建它那棵子树。实测过的三种写法：把表单写进 `@Builder`、写进 `build()` 里嵌在分段
  `if` 内的 `if`、以及同一处的提示行 —— 条件明明为真（`probeForm` 的日志坐实 `open=true`、
  `AceTextField` 日志坐实输入框真的被创建），节点却一个都不进布局树。
  所以「随状态出现/收起的块」必须靠 `ForEach` 的 key 强制重建 —— 工程里早有先例
  （`view/ReproductionPage.ets::PlanBlock`，注释写着"不要依赖 `@Builder` 的刷新时机"）；
  `view/SettingsPage.ets::modelKeys` 是第二处。key 里只放**结构性**状态，不放输入框草稿，
  否则每敲一个字都重建、光标会丢。
- **`console.log` 不能写在 `@Builder` 里**：编译期直接报 `does not meet UI component syntax`。
  调试探针要包成一个普通方法，在 UI 表达式的位置调用（`if (this.probe(...))`）。
- **剩下的边界（如实写）**：模拟器不等于真机 —— 窄屏布局、深色模式、字体放大、轮询定时器
  是否真的随页面销毁而停，都还没验。`test_arkts_sources.py` 是**源码级**扫描，它拦的是
  "名字对不上"，拦不住"渲染出来不对"，后者只有装机看。

### D10 端侧工程与后端在同一个仓库里（2026-09-28）

端侧 ArkTS 工程从 `YouJustLead-Harmony` 并进本仓库，落在 `device/` 子目录，19 个提交的历史
原样保留（路径重写加前缀）。第二个仓库不再更新，作为历史留档。

**为什么改**：分仓的理由当初是"工具链不同"，但工具链要求的是**不同的构建根**，不是不同的仓库 ——
实测 `hvigorw clean assembleHap` 在 `device/` 子目录里照样 BUILD SUCCESSFUL。而分仓的代价是真的：

| 代价 | 具体 | 实测证据 |
|---|---|---|
| 端侧的自动保护会**静默消失** | 后端有 9 处 `skipTest` 的条件是"端侧仓库不在这台机器上"，其中 5 处就是端侧全部的源码检查。换台机器照样 `Ran 403 tests` 全绿 | 合并前 |
| 发布门禁会说谎 | `_default_artifacts` 在找不到端侧仓库时**根本不把 HAP 列进产物清单**，于是 `release_ready: true` 而端侧那半没被看过 | `release_ready = True` / `artifacts = ['backend-executable','desktop-app']` |
| 契约改动无法原子 | 后端加 `job_statuses` / `step_statuses` 时忘了端侧那份接口声明，只有端侧编译能抓，而端侧编译只在这台机器上发生过 | 8 个编译错误 |

**合仓改了什么**：`tools/device_project.py` 只认一个位置（没有猜测、没有环境变量、不返回 None）；
端侧两个产物**无条件**进清单，找不到就 `present: false` 变成阻塞项；那 9 处 `skipTest` 全部去掉，
缺 `device/` 直接红；`release_manifest` 不再记 `git.device`（同一个仓库，重复记一次只会误导）。

**合仓没改什么（如实写）**：两份实现仍然要各自同步 —— 端侧是 83 个手写 ArkTS 文件，与本仓库的
Python 一行都不共用。配色就是一处例子：`device/entry/src/main/ets/common/AppTheme.ets` 与
`web/styles.css` 的十六进制值逐字相同，而**没有任何测试比对它们**。合仓只是让"加一条比对测试"
变得顺手，没有自动修好它。

- 依据：`app/release_service.py`、`tools/device_project.py`、`docs/versioning.md`、
  `tests/test_release_manifest.py::test_the_hap_is_always_a_required_artifact`、
  `tests/test_arkts_sources.py::DeviceCheckoutTests`。

### D11 模型来源是可编辑的外部配置，密钥与它分开放（2026-09-29）

起因是一个真实缺口：两个前端的「模型」区原来**只是只读展示**，密钥只能靠环境变量进去，
而 README 那句"在「设置 → 模型」里填 DeepSeek API Key"描述的是一个**不存在的表单**。

**做法**：

- **一套「来源」= 任意 OpenAI 兼容服务**（`POST {base_url}/chat/completions` + `Authorization: Bearer`）。
  `app/llm_service.py`（原名 `deepseek_service.py`，改名是因为它已经不只服务 DeepSeek）是唯一发请求的地方，
  地址、密钥、模型都从**当前使用**的那套取 —— 换一家就是换个地址，不需要写适配器。
- **可以同时存多套，选一套当前使用。** 预设（DeepSeek / OpenAI / 月之暗面 / 阿里百炼 / 本地 Ollama / 自定义）
  只做**预填**，地址可改；接一家没预置的服务也不用动代码。预设清单由后端发在
  `GET /api/settings/providers` 的 `presets` 里，两个前端都不自己抄一份 —— 与 D9 是同一条原则。
- **密钥只进系统凭据库**：`settings.json` 只存名称/地址/模型，所以那个文件可以拿给别人看；
  每套一条凭据记录（`provider:<id>`），界面只回 `has_key`，不回密钥本身。
- **旧配置一次性迁移**：把原来的单供应商设置与那把密钥搬成一套 DeepSeek 来源，不用手动重填；
  旧凭据记录**不删** —— 那是用户自己存进去的东西，删掉不可逆。
- **环境变量改名** `DEEPSEEK_API_KEY` → `YJL_LLM_API_KEY`：多供应商之后旧名字只对得上其中一家。
  旧名字仍然认，但**只在当前这套的预设是 DeepSeek 时**生效。
- **环境变量只覆盖「当前使用」那套**：它是一句全局设置，不是给某一套来源的 —— 不这么切，
  「测试某一套」就会把当前这套的密钥发给第三方。`has_key` / `configured` / `key_source`
  与真正取密钥这四处统一按这条口径判（`settings_service._env_key()`）。
  这一条是部署到一台**没有系统凭据库**的 Linux 时才暴露的：那时界面说「未配置」「缺密钥」，
  而 Agent 其实答得出来 —— 状态在说谎。
- 接口：`GET/POST /api/settings/providers`、`.../active`、`.../delete`、`.../test`；
  `/api/agent/deepseek` 改名 `/api/agent/ask`。旧的 `/api/settings/deepseek` 已下线。

**验收依据**：`tests/test_model_providers.py`（16 项，用 `_FakeKeyring` + 临时 `APPDATA`，
**不碰这台机器真实的凭据库与设置文件**）；`tests/test_arkts_sources.py::ContractShapeTests`
新增一条，比对端侧 `ProviderSettings` 与后端 `providers_status()` 逐字段一致；
Windows 端 `web/views.js` 与鸿蒙端 `device/entry/src/main/ets/view/SettingsPage.ets` 各自接上。

**真机验收（模拟器）**：预设预填、新增并保存、设为当前、删除（两步确认）、测试连接逐项走过；
「测试」是真的发了一次请求，回来显示「连接正常（deepseek-v4-pro）」。测试连接**指定某一套**
（不需要先切过去）也验过 —— 后端为此单开了 `verify_connection(provider_id)`。

### D12 面向用户的目标形态：托管后端 + 可下载客户端（2026-09-29）

**用户已确认产品方向**：服务由项目方部署；用户下载客户端即可使用，不要求安装 Python 或自行启动后端。评委使用方案由 2026-09-29 的 D13 具体规定为平台托管 DeepSeek 与账号积分计量。

实现状态：Windows EXE 仍在本机启动回环后端；鸿蒙端 RC6 请求 `https://nucrobot.online/yjl-cloud`，含登录、注册和积分页。云账号 API 以独立 systemd 服务运行在回环端口 `8766`，Nginx 仅新增 `/yjl-cloud/api/` 反向代理；原有 `youjustlead.service` 和网站路由保留。公网实测健康检查返回 200，未登录访问项目接口返回 401；真实 HTTPS 注册、登录、建项目、DeepSeek 问答、usage 计费与登出撤销均通过。HAP 已重编、安装并在模拟器显示登录页。Windows EXE 仍是本地模式；HAP 的 Release 分发、真机与长时间运行尚未验收。

仍然有效的要求：

- 鸿蒙应用连接正式 HTTPS API，不依赖开发机端口转发；
- 用户项目、工作区、账本按账号隔离；
- HAP 与共享 Windows 发行包不含服务端 DeepSeek 密钥；
- 真实服务器验收覆盖注册、登录、项目隔离、登出、模型调用与积分结算。

评委问答的密钥路径已定为服务器环境中的 DeepSeek Key；训练、重型数据审计与复现仍需用户自己的执行器，配对方案尚未实现。第 7 节记录已上线能力与仍缺的验收。

### D13 评委账号、托管 DeepSeek 与积分计量（2026-09-29）

**用户已确认**：用户名和密码自助注册；每个新账号首次注册赠送 100 积分；每 1,000 个 DeepSeek 输入与输出 token 合计扣 1 积分；评委不需要购买或填写 DeepSeek API Key。DeepSeek API Key 由项目方配置在服务器的秘密环境/秘密管理器中，HAP 只持有账号会话令牌。

实现口径：

- 账本以整数 token 保存余额；初始赠送 `100,000` token。余额可精确显示为积分小数，避免每次请求向上取整多扣积分。
- 成功模型响应按服务商返回的 `prompt_tokens + completion_tokens` 计量；请求前预留额度，请求后按真实 usage 结算并返还未使用的预留。缺少 usage 时不得静默免费放行，必须按明确的保守策略处理并留下账本事件。
- 密码只存带随机盐的慢哈希；会话令牌只存哈希，支持登出撤销和到期。用户 ID 使用服务端生成的不透明 ID；用户项目注册表、工作区、实验账本均从该 ID 派生到独立数据根。
- 注册、登录、积分与工作区 API 必须走 HTTPS；除注册/登录/健康检查外，所有 API 都要求有效会话。预检请求不能访问数据。错误响应、应用日志和账本不得包含密码、原始会话令牌或 DeepSeek 密钥。
- 免费注册积分意味着模型费用由项目方承担。速率限制、单次输出上限和服务端停用开关是上线条件；赠分是“每个账号一次”，不能声称已经防止同一人批量注册。
- 云端无 GPU。训练、重型审计等任务的真实执行位置仍按 D4/D12 另行验收；仅完成账号与问答计量，不代表单个 HAP 已能在服务器上跑完重型科研实验。

**验收门槛**：两个账号互不可见；重复注册不能重复领同一账号赠分；并发请求不能突破余额；登出后的令牌立即失效；模型调用响应 usage 与扣费账本逐项对上；日志与服务端持久文件无模型密钥；真实 `https://nucrobot.online` 上从新账号注册到模型调用及余额变化全流程通过。完成这些之前，不得把当前部署宣传为评委可直接使用的公共服务。

RC6 已覆盖账号注册/登录、独立 UUID 数据根、每个新账号赠送 100,000 token、DeepSeek 调用预留与按 usage 结算、登出撤销和云端模型配置隐藏。服务器线上验收：两个 API 验收账号注册、登录、登出通过；第二个账号创建项目并完成一次 DeepSeek 问答，服务商 usage 为输入 3,083 + 输出 578 = 3,661 token，账本同额扣减，余额从 100,000 变为 96,339。第三个账号由 HAP 在模拟器自助注册，页面显示 100 积分，随后从 HAP 创建云端项目并进入工作流。2026-09-30 又从 HAP 工作流问答区发出一条短问题，界面收到单轮回答；强制停止并重启应用后，向服务器重新读取的余额由 100.00 变为 97.95，证明端侧问答、计量和余额读取闭环。服务端健康检查为 200，未授权项目请求为 401，非 HTTPS 标记请求为 426。2026-09-30 本机绕过代理只读健康检查返回 `status: ok, mode: cloud`。Python 全量回归为 464 项通过。

D13 替代 D12 中的 BYOK 评委路径，并保留“任何发行包都不含服务端凭据”、用户/项目隔离和 HTTPS 要求。公网 API 与 HAP 界面的注册到模型计费闭环均已验收。账号交叉项目不可见仍只由自动化测试覆盖，未单独在线上执行。赠分按账号而非实名身份，因此不能防止同一人批量注册。云端存储配额、全局并发上限、费用告警、管理员停用开关、密码恢复、账号删除、HUKS 会话保护和 HAP 真机验收仍缺；科研训练与重型审计的执行器配对也未实现。故 D13 的核心云问答闭环已验收，公共规模运营及完整科研执行不应标记完成。

---

## 3. 被否决的替代方案

| 方案 | 否决理由 |
|---|---|
| 把训练、重型审计与复现也整体搬到无 GPU 云主机 | D12 已确认托管服务与可下载客户端是产品方向；把耗算力执行也迁到当前无 GPU 云主机仍无法支持真实实验，账号、资源隔离与成本也需要单独验收 |
| 把 Python 的能力整体搬到 ArkTS | 训练与重型审计本来就不该在端侧；D4 只要求"状态读取端侧化" |
| 用 JSON Schema 做契约层 | Python 侧不引第三方依赖、ArkTS 侧没有校验库 → 只会得到一份没人校验的文档。改成可执行声明 + 真实产出对拍 |
| 端侧 `canIUse(常量)` 处理 syscap 告警 | 实测不生效，必须传字符串字面量（见项目记忆） |
| 靠"连续 20 次全绿"绕过偶发失败 | 偶发失败要修根因。20 次全绿是**验证手段**，不是修法 |

---

## 4. 本阶段明确不做的事

按目标里"在第一条真实实验闭环形成以前停止新增非必要功能"，同时遵守 D12 已确认的产品方向：

- 不再扩张 AI Agent 数量、不做新的研究 Agent；
- 不做鸿蒙分布式能力、元服务；
- 不把训练等重计算迁到云端；云端身份、隔离和客户端远程接入属于 D12 必需工作，不再列为永久不做项；
- 界面改动应服务于可下载客户端的易用性与个性化，不能以桌面端 Legacy 为由排除 Windows 用户。

---

## 5. 已知破口（诚实列出）

1. **B1**：训练、重型数据审计、检索、LLM 必须有外部执行器；端侧只能标注需求，不能执行。
2. **B2**：契约的端侧那半是源码级检查，端侧运行时一致性靠装机验收，不是自动测试。
3. **B3**：`claims` 只能由落在审计范围内的实验产生（合成 runner 会被 `tools/experiment_scope.py` 排除），
   所以在有真实数据之前它**必须是空的** —— 那是对的行为，不是缺陷。
4. **B4**：`nucrobot.online` 已部署独立 RC6 云账号服务并通过一次公网模型计费闭环；云主机只有 2 核 / 2 GiB、无 GPU，当前无存储配额、全局并发上限、费用告警与管理员停用开关。它通过功能验收不等于具备面向大量用户的运营保障。
5. **B5（G4/G5）**：真实数据上确实有 H0007 → JOB-0003 → EXP-0008 的 1 epoch、10% 子集训练记录，因此不能说“没有跑过实验”，但它还不能证明 Gate 已通过。`experiments/manifests/EXP-0008.json` 为 `planned`，对应结果文件为 `completed`；结果 `val_map50_95=0.00211`，低于假设阈值 `0.00234`，但结果文件的 `decision` 是 `keep_as_candidate`、`conclusion` 是“Baseline completed”。研究循环状态中的 V0043 则记录 `prediction_met=false`、`verdict=hypothesis_falsified`，并注明泄漏检查未做（`leakage_free=null`）、未跨种子复现（`replicated_across_seeds=false`）。也就是说，已有负结果与假设证伪记录，但结果/优化账本的措辞和计划状态仍冲突，且核查未齐。历史文件保持原样；G4/G5 仍未通过。本轮没有启动训练。

---

## 6. 改边界的流程

1. 任何新增功能必须先回答：**它关闭的是六个 Gate 里的哪一个**（G1 架构 / G2 规则 / G3 数据 /
   G4 实验 / G5 证据 / G6 发布）。答不上来就暂缓。
2. 每项任务要齐：`需求 → 实现 → 自动化测试 → 真实验收 → 账本/事件 → 文档`。
   "代码写完了"不算 Done。
3. 改本文件第 1 节那张图（三条边界）需要用户确认；只改第 2 节的决定清单则需要同时更新验收依据。

---

## 7. 云服务与用户自己的执行器（账号与问答计费已线上验收，执行器未实现）

> D12/D13 的产品方向已由用户确认。账号、用户根目录与 DeepSeek token 计量已部署并完成公网验收。执行器配对仍是未实现方案。服务器为阿里云 ECS（`39.106.174.180`，2 核 2 G，无 GPU），不适合承载训练等重计算。

### 7.1 暂定拓扑

一个**云后端**负责身份、状态、编排、账本与同步；训练、数据审计、复现这些重活暂建议跑在**用户自己的机器**上。
按 D13，评委问答由云后端使用项目方配置的 DeepSeek API Key，按用户账号积分计量；用户机器上的执行器配对方案仍待实现。

### 7.2 为什么是这条（不是偏好，是被约束和已有决定逼出来的）

- **云主机没有 GPU。** 部署实测 `/api/runtime/local` → `{"gpu": {"available": false}}`、
  2 核 / 1.8 GiB、Ubuntu 20.04。把训练搬到云上，等于把六个 Gate 里最缺的 G4 直接堵死。
- **架构本来就这么设计。** D4「状态读取端侧化，重计算执行器化」—— 这一条只是把 D4 推到
  "后端住在云上"的场景，不是新方向。
- **托管密钥会把模型费用与滥用责任放到项目方。** DeepSeek API Key 必须通过服务器秘密配置，
  不能放进 HAP、源代码、普通设置文件或日志。注册限流、余额预留与对账、单次输出上限、
  停用开关和费用告警都是发布前置条件；密钥托管是产品责任，不是一个配置选项。

### 7.3 本地模式与云模式的边界

| 领域 | 当前实现 | 位置 |
|---|---|---|
| 用户与项目根 | 本地模式使用原有单一根目录；`YJL_CLOUD_MODE=1` 时按已认证用户切换到 UUID 独立根 | `api_server.py::_prepare_cloud_request()`、`project_registry.py` |
| 项目注册表 | 本地模式使用 `workspace/projects.json`；云模式每个 UUID 根下有自己的注册表与工作区 | `project_registry.py::REGISTRY_FILENAME` |
| API 认证 | 本地模式沿用共享令牌/Origin；云模式除健康检查与注册登录外要求 Bearer 会话，并校验 HTTPS 反代标记 | `api_server.py`、`account_service.py` |
| 客户端地址 | Windows EXE 启本地回环后端；HAP RC6 使用 `https://nucrobot.online/yjl-cloud`，Nginx 路由至独立云账号服务 | `app/desktop_entry.py`、`device/.../BackendConfig.ets` |
| 模型密钥 | 本地模式由本机来源配置；云模式固定从 `YJL_LLM_API_KEY` 读取 DeepSeek Key，客户端不能读取或改配 | `settings_service.py`（D11/D13） |
| 执行位置 | 当前云主机 CPU 可处理账号、状态与问答；训练、数据审计、Docker 复现仍需执行器方案 | `authorization.py`、`container_runner.py`、`training_scheduler.py` |

**两处好消息，说明这不是重写：**

1. **工作区路径解析已支持云账号根**：请求认证后，handler 切换到该用户 UUID 根；项目注册表与既有工作区 API 可以沿用。
2. **模型密钥仍只有一个解析出口**：本地来源由 `resolve_credentials()` 读取；云模式提供固定 DeepSeek 来源，密钥来自服务器环境，不随客户端请求传递。

### 7.4 分五个阶段（每阶段能独立验收）

**阶段 0 · 保持本地路径兼容（已完成）**

- 本地模式继续使用原有工作区与模型来源，不要求本地用户注册账号。
- 托管模式通过显式 `YJL_CLOUD_MODE=1` 开启；未设置时保持本地默认行为。

**阶段 1 · 账号与隔离**

- 用户表 + 登录 / 令牌轮换；**每个用户一个 `project_root`**，各自一份 `projects.json`。
- 验收：两个账号互相看不到对方的项目、工作区、账本。要有测试钉住，
  沿用 `tests/test_ledger_project_isolation.py` 的路子，只是维度从"项目"变成"用户 + 项目"。
- RC6 已有 SQLite 账号、会话及每账号 UUID 根；本地 API 测试覆盖两个账号互不可见。公网已验收注册、登录、登出和问答计费；线上交叉账号不可见未单独复测。

**阶段 2 · 托管模型调用与按量计费**

- DeepSeek Key 只由部署环境注入服务器，**不回传客户端、不写入项目数据或日志**；所有客户端模型调用必须经过 HTTPS。
- 每次请求先以用户整数 token 余额原子预留预算，模型响应后依据真实 `prompt_tokens + completion_tokens` 结算；一次模型动作里的每次调用都计费，包括研究循环在后台线程发出的调用。
- 验收：服务端磁盘/日志与发行包无 Key；并发余额不会透支；DeepSeek usage 与用户积分账本对得上；无余额或无 Key 时请求在调用模型前拒绝。
- RC6 已有固定 DeepSeek 云来源与 `UsageMeter`；本地测试覆盖预留、结算、余额不足和不泄露设置字段。公网一次真实问答的 provider usage 与账本扣减均为 3,661 token。

**阶段 3 · 执行器配对**

- 用户机器上的执行器**主动出站连接**云端（用户不用开任何端口、不用配端口映射），
  云端把要跑的任务派给它，结果回流成状态。
- 验收：关掉那台机器 → 任务停在 queued；打开 → 继续跑完。

**阶段 4 · 配额与滥用**

- 按用户存储与请求配额；除积分余额外，还要限制账号注册/登录频率、单次输出长度和突发并发。
  100 积分是一次性的注册赠分，平台承担实际模型费用；上线前需配置用量监控与快速停服开关。
- RC6 已有限制：每客户端 IP 每日 200 次注册、每 IP/用户名组合 15 分钟 20 次失败登录、每次模型请求最多 2,048 输出 token。每账号存储配额、全局并发上限、费用告警和管理员停用开关仍缺。

### 7.5 要改的既有决定（如实列出，不藏）

- **D2「工作区是唯一的审计单元」** → 每个用户有独立项目根，每个项目仍是审计单元；用户 UUID 在目录根隔离，不需给 D3 的项目账本 schema 加用户列。
- **D11「密钥只进本机系统凭据库」** → 本地 BYOK 模式继续成立；D13 评委模式改由服务端托管项目方的 DeepSeek Key，服务端密钥仅来自秘密配置，不进入 HAP、用户工作区或日志。
- **D7 的旧桌面范围** → 不再限制 Windows 客户端；Windows 与鸿蒙都是 D12 的目标入口。
- **第 4 节的云端范围** → 用户身份、隔离和客户端远程接入是 D12 的必需工作；训练等重计算仍暂定留在用户机器。

### 7.6 明确不做 / 还没定

**不做**：把训练搬到云上（没 GPU，且与 D4 相反）。

**还没定**（这几条定了才好开工）：

- 执行器与云端怎么配对（一次性配对码 / 用户手动填令牌 / 扫码）；
- 云上要不要留一块小 GPU —— 只为"演示与冒烟测试"，还是完全交给用户机器。

### 7.7 已完成与尚缺验收

- **已完成**：独立云账号服务与 Nginx HTTPS 路由上线；公网健康检查 200、匿名项目请求 401；两个随机账号注册/登录/登出通过；一个账号新建验收项目并完成 DeepSeek 调用，usage 与账本同为 3,661 token。
- **线上验收留下的数据**：三个随机验收账号仍在云端数据库；其中一个有模型验收项目和 3,661 token 账目，另一个是 HAP 自助注册并创建的空白项目。未删除线上数据。
- **原有服务保持**：旧 `youjustlead.service` 和原网站 `/` 未替换；新增服务使用独立数据目录和端口，便于单独回滚。
- **已完成**：最新 HAP 在模拟器经公网注册、自动登录、显示 100 积分、创建项目并进入工作流。
- **尚缺**：HAP 真机安装和 AGC 正式发布签名验收。
- 线上两个账号交叉读取项目的拒绝目前由自动化测试覆盖，尚未做额外公网交叉隔离测试。
- HAP 会话令牌当前放在应用私有 Preferences；没有硬件密钥库封装、密码恢复、账号删除和存储配额。
- 执行器配对、云端费用告警、全局并发限制、每用户存储配额和管理员停用开关仍未实现。

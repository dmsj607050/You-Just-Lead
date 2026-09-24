# 架构边界与决定（Architecture Decision Record）

适用范围：You Just Lead 本机形态（鸿蒙端 + 本地 Python 执行器 + 外部服务）。
状态：**v1 边界已冻结**（2026-09-24）。改边界要走第 6 节的流程，不要顺手改。

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
本仓库**不托管任何云端服务**，云端只是被调用的外部依赖。

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
- **副作用（如实记录）**：真实项目里那份旧产物在 `competition-agent/paper/generated/`（工作区之外），
  新规则下它不再被溯源链读到，`/api/trace` 的论文链会显示"未生成"。
  旧文件没有被删（那是历史证据），要恢复显示就在工作区里重新生成：
  `python main.py paper --workspace workspace/current_competition`。

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

- 依据：`schemas/contracts.py`（7 份契约）、`tests/test_canonical_contracts.py`（15 项）。
- **能力边界**：端侧那半是**源码级检查**，不是运行时校验（ArkTS 没有 JSON Schema 校验库，
  也不在 Python 进程里）。端侧运行时的一致性由装机验收负责，别把这两件事混为一谈。

### D6 落盘失败要重试，且不留残渣

`tools/files.py` 的原子写是**所有 JSON 落盘的唯一漏斗**：唯一临时名 + 有界退避重试
（`PermissionError` / `WinError 5,32,33`，总预算 1s）+ `finally` 清理临时文件；读侧同样容忍。
理由是 Windows 上 `os.replace` 会撞并发读者，而这不是"某个测试的问题"，是持久层缺陷。

- 依据：`tools/files.py`、`tests/test_files_atomic.py`（确定性回归，在旧实现上必然失败）。

### D7 桌面仪表盘已**废弃并移除**，v1 只有端侧应用

<!-- 这一条被更正过三次：最早文档写"源码已经不在了"（不是事实）；后来写"源码在第三方仓库、
     归属待用户拍板"；再后来按"内容都发到自己的 GitHub"搬进了客户端仓库。 -->

**2026-09-24 用户拍板（最终）**：只要鸿蒙端应用，旧的仪表盘不要了。据此：

| 项 | 实况 |
|---|---|
| 客户端仓库 | `YouJustLead-Harmony` **只有端侧应用**（`entry/` 等 DevEco 工程），没有 `desktop/` |
| 仪表盘源码 | **已从两个仓库移除**；历史留在客户端仓库的提交里（引入 `43aeaf1`、移除 `a26ca7f`），需要时可取回 |
| 第三方托管 | 已废弃，`git.chatgpt-team.site` 不再被任何东西引用 |
| 本机残留 | `B:\You Just Lead\you-just-lead-desktop.exe`（13 MB 安装包）、`output\frontend-history-backup.git`（历史镜像） |
| 判定 | 仪表盘**不在 v1 架构内，也不再作为交付物存在** |

**两件名字里带 dashboard / desktop、但不是那个仪表盘的东西，不要连坐删掉**：

- `app/dashboard_service.py` 与 `GET /api/dashboard`：这是后端给**端侧应用**的聚合快照接口，
  端侧 `BackendClient.ets` 正在调它。
- `app/local_agent_entry.py` + `tools/build_local_agent.ps1`：Windows **本地执行器**
  （产物 `dist/competition-agent-api.exe`，发布清单里 `required_for_release=true`）。
  端侧应用连的就是它。

v1 的交付形态：**鸿蒙端应用 + 本地 Python 执行器**。

### D8 版本只有一处来源，发布与否是可判定的

版本号只在 `VERSION` 一处；端侧 `AppScope/app.json5` 的 `versionName` 必须等于它的
`MAJOR.MINOR.PATCH` 部分。`python main.py release-manifest` 产出 `release/release_manifest.json`，
**退出码即答案**（0 可发布 / 1 不可发布），并在 `release_blockers` 里说明原因。

可以发布要同时满足三条：版本处于 `rc`/`release` 阶段、发布必需的产物都在、两个仓库都没有未提交改动。

- 依据：`app/release_service.py`、`tests/test_release_manifest.py`（22 项）、`docs/versioning.md`。
- 针对的真问题：`docs/RELEASE_0.1.5.md` 记了安装包 SHA-256，`0.1.6`~`0.1.9` 都没记 ——
  纪律靠人记就会退化，所以改成工具会拦住的条件。
- 未被这条决定覆盖的：Release 签名（`.app`）、AGC、备案、隐私政策、AI 声明都要用户侧账号或资质，
  见 `docs/versioning.md` 第 6 节。

---

## 3. 被否决的替代方案

| 方案 | 否决理由 |
|---|---|
| 全面云化（后端上云、端侧只当壳） | 与"离线可演示 / 端侧自足"这条已定路线冲突；且会引入账号、可用性、成本三类新风险 |
| 把 Python 的能力整体搬到 ArkTS | 训练与重型审计本来就不该在端侧；D4 只要求"状态读取端侧化" |
| 用 JSON Schema 做契约层 | Python 侧不引第三方依赖、ArkTS 侧没有校验库 → 只会得到一份没人校验的文档。改成可执行声明 + 真实产出对拍 |
| 端侧 `canIUse(常量)` 处理 syscap 告警 | 实测不生效，必须传字符串字面量（见项目记忆） |
| 靠"连续 20 次全绿"绕过偶发失败 | 偶发失败要修根因。20 次全绿是**验证手段**，不是修法 |

---

## 4. 本阶段明确不做的事

按目标里"在第一条真实实验闭环形成以前停止新增非必要功能"：

- 不再扩张 AI Agent 数量、不做新的研究 Agent；
- 不做鸿蒙分布式能力、元服务；
- 不做云端复杂架构；
- 不急着重写页面（端侧只补"状态读取"，不重写已有后端页面）；
- 桌面端只做 Legacy 定位，不加功能。

---

## 5. 已知破口（诚实列出）

1. **B1**：训练、重型数据审计、检索、LLM 必须有外部执行器；端侧只能标注需求，不能执行。
2. **B2**：契约的端侧那半是源码级检查，端侧运行时一致性靠装机验收，不是自动测试。
3. **B3**：`claims` 只能由落在审计范围内的实验产生（合成 runner 会被 `tools/experiment_scope.py` 排除），
   所以在有真实数据之前它**必须是空的** —— 那是对的行为，不是缺陷。
4. **B4**：桌面端源码与历史在一个第三方托管上，且本地有未提交改动（见 D7）。

---

## 6. 改边界的流程

1. 任何新增功能必须先回答：**它关闭的是六个 Gate 里的哪一个**（G1 架构 / G2 规则 / G3 数据 /
   G4 实验 / G5 证据 / G6 发布）。答不上来就暂缓。
2. 每项任务要齐：`需求 → 实现 → 自动化测试 → 真实验收 → 账本/事件 → 文档`。
   "代码写完了"不算 Done。
3. 改本文件第 1 节那张图（三条边界）需要用户确认；只改第 2 节的决定清单则需要同时更新验收依据。

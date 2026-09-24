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

**端侧必须跟着走**：`B:\YouJustLead\AppScope\app.json5` 里的 `versionName` 必须等于 `VERSION` 的
`MAJOR.MINOR.PATCH` 部分（`1.0.0-dev.0` ↔ `versionName: "1.0.0"`）。
对不上就是「文档里的版本 ≠ 实际构建的版本」，工具会把它记成阻塞项。

当前：`1.0.0-dev.0` —— v1 线路上的开发版（六个 Gate 里只过了 G1）。

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
python main.py release-manifest --device-repo 'B:\YouJustLead'   # 手动指定端侧仓库
```

**退出码就是答案**：`0` = 这个版本可以发布，`1` = 不可以（并打印 `release_blockers` 说明原因）。

清单记录（对应目标里点名的字段）：

| 字段 | 来源 |
|---|---|
| `version` / `version_core` / `stage` | `VERSION` |
| `build_time` | 生成时刻（秒级 UTC） |
| `git.backend` / `git.device` | 两个仓库各自的 commit、分支、是否有未提交改动 |
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
2. 所有「发布必需」的产物都在（后端 exe、端侧 HAP）；
3. 两个仓库都**没有未提交改动** —— 发布必须从干净的提交切出来，否则 commit 号对不上实际内容。

缺哪条就会出现在 `release_blockers` 里。这条门槛针对的是一个已发生过的真问题：
`docs/RELEASE_0.1.5.md` 记了安装包的 SHA-256，而 `0.1.6`~`0.1.9` 都没记 ——
**靠人记的纪律一定会退化**，所以把它变成工具会拦住的条件。

---

## 5. 切一次发布要做的事

```text
1. 改 VERSION（并同步端侧 AppScope/app.json5 的 versionName）
2. 编译产物：后端 dist/competition-agent-api.exe、端侧 HAP（DevEco 里 Build Hap(s)）
3. python main.py release-manifest        # 退出码必须是 0
4. 写 docs/RELEASE_<版本>.md，**贴进清单里的 version / commit / 产物 SHA-256**
5. 提交（清单本身在 release/，那是输出目录、不进版本库；摘要进发布说明才留得下来）
6. 打 tag，并把 release/ 里的产物上传到分发位置
```

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
但**清单工具已经就绪**，等产物齐了、仓库干净了、版本升到 rc，一条命令就能给出可审计的版本记录。

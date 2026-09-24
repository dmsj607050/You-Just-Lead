# Competition Agent 操作指南

该项目以“人确定方向与高风险操作，系统执行、记录和分析”为原则。所有事实以结构化 JSON / SQLite 记录为准；Markdown 与 TeX 是从这些记录生成的报告。

## 1. 建立一个真实比赛工作区

把未经修改的官方规则、样例提交文件和 README 放入 `workspace/current_competition/input/`，原始数据放入 `workspace/current_competition/data/raw/`。

```powershell
conda run -n AIC python main.py rules --source input/official_rules.md
conda run -n AIC python main.py audit-data
conda run -n AIC python main.py plan
```

先人工核验 `competition_spec.yaml` 与 `docs/competition_rules.md`，并显式处理其中的 `unresolved_questions`。字段完整后，用带有审阅说明的命令记录确认：

```powershell
conda run -n AIC python main.py approve-rules --note "Reviewed against the official competition page on 2026-07-16."
```

在规则状态未确认前，不应启动真实训练或提交。

## 2. 建立基线

当前内置四个训练适配器：

- `synthetic_binary_classification`：只用于检查基础设施。
- `tabular_classification`：真实数值 CSV 的二分类/多分类基线，可选生成测试集预测文件。
- `tabular_regression`：真实数值 CSV 的回归基线，以最小化 RMSE 为默认验证目标。
- `image_classification`：按类别子目录组织的图像分类基线，可选生成本地 CSV 预测文件。
- `image_segmentation`：成对图像/二值掩码的轻量 U-Net 基线，可选生成与原图同尺寸的 PNG 掩码提交目录。

可随时运行 `python main.py capabilities` 查看适配器、配置模板与数据契约。规则确认后，中央工作流会根据明确的 `task_type` 推荐匹配的内置适配器；对于目标检测、NLP、时序等未覆盖任务，它会明确提示需要新增任务适配器，而不会错误套用现有模型。

复制 `configs/tabular_classification.template.yaml` 为新配置，确认 `train_csv`、`target_column`、特征列、验证方式及提交列后运行。模板中 `data/raw/...` 这类相对数据路径始终相对于当前比赛工作区解析，不依赖你从哪个终端目录启动命令：

```powershell
conda run -n AIC python main.py run --config configs/tabular_baseline.yaml
conda run -n AIC python main.py report
conda run -n AIC python main.py plan
```

每次运行都会冻结配置、数据版本、Git 状态、环境信息、训练曲线、指标与下一步建议，并同步到 SQLite 与 MLflow 本地记录。真实训练会重新核对数据审计的内容指纹；只要原始数据目录在审计后发生任何内容或文件布局变化，就必须先重新执行 `audit-data`。

`python main.py plan` 还会生成 `experiments/proposals.json`：最多三个待人工审核的候选实验。每个候选项都包含父实验、证据、成本与风险分数、回滚目标和审批要求；优先级仅用于排序，不代表虚构的分数提升，也不会自动启动训练。

图像分类运行会额外保存验证集逐样本预测，并生成 `experiments/artifacts/EXP-xxxx/error_analysis.json` 和 Markdown 摘要。该分析只记录本地样本路径、真实/预测类别与置信度，用于发现类别召回不对称、高置信度误判和主要混淆关系。

若真实训练配置请求 CUDA，必须先审核预算并为**该配置的当前内容**记录审批；改动配置后需要重新审批：

```powershell
conda run -n AIC python main.py approve-run --config configs/image_segmentation.yaml --note "Approved: 4 GPU hours on the local RTX workstation."
```

分割比赛可从 `configs/image_segmentation.template.yaml` 开始；图像与掩码需按文件名 stem 一一匹配。数据审计会额外报告前景比例、空掩码和跨 train/test 的精确重复风险。

提交前先进行本地格式校验；该命令不会向比赛平台上传任何文件：

```powershell
conda run -n AIC python main.py validate-submission --path submissions/candidate.csv
```

## 3. 研究与复现

检索是显式触发的网络操作，结果会落盘为 `research/papers.json` 和 `research/research_radar.md`。不传 `--query` 就按 `competition_spec.yaml` 里的任务类型与模态自动拼检索式（App 上就是「按规则检索」）：

```powershell
conda run -n AIC python main.py research --limit 6
conda run -n AIC python main.py research --query "semantic segmentation boundary loss" --limit 5
```

每条候选的相关性由四项可复算的分量加权得出（词命中 / 任务匹配 / 是否带代码 / 年份），分量明细写在记录的 `relevance_parts` 里。候选的取舍与价值评判在 App 的「文献」页完成：

- **取舍**：逐条标 `investigate`（调研）或 `discard`（舍弃），落盘在 `research/candidate_decisions.json`；
- **评判**：对标记为调研的候选，用论文标题去 GitHub 找实现仓库，再结合许可、任务匹配、年份给出结论，落盘在 `research/candidate_assessments.json`。

两份文件都独立于 `papers.json`，所以**重跑检索不会覆盖人已经做过的决定**；如果新一次检索里没有某条记录，它的取舍仍留在文件里，只是不再计入界面顶部的计数。

第三方仓库先只创建审批记录：

```powershell
conda run -n AIC python main.py reproduce --repository https://github.com/owner/repository.git
```

仅当人工确认来源、许可证与资源预算后，才使用 `--approved` 克隆以供**静态检查**；该步骤仍不会执行下载的代码。静态检查通过后，可以用显式容器镜像和命令发起一次网络隔离、只读挂载的 smoke test：

```powershell
conda run -n AIC python main.py reproduce --repository https://github.com/owner/repository.git --approved --smoke-test --image python:3.11-slim --command "python --version"
```

完整复现仍应采用专门批准的数据挂载、镜像与资源预算，而不是直接在宿主机运行第三方代码。

### 3.1 隔离容器里跑 baseline

App 的「复现」页把上一步的结论变成一次可审计的运行。命令行等价物是这两个接口：

```powershell
# 生成计划（会 clone 仓库做静态检查，仍不执行任何代码）
curl -X POST http://127.0.0.1:8765/api/reproductions/plan -H "Content-Type: application/json" `
  -d '{\"paper_id\":\"arxiv:2604.16630v1\"}'

# 批准并运行（note 必填；command 可留空，留空则用计划里选中的那条原文）
curl -X POST http://127.0.0.1:8765/api/reproductions/run -H "Content-Type: application/json" `
  -d '{\"plan_id\":\"REPRO-trimodal-uav-det\",\"command_id\":\"cmd-1\",\"note\":\"核对过 README 与许可\",\"command\":\"python scripts/train.py --data /data --epochs 1\"}'
```

计划来自仓库自身的文本，不猜：入口脚本按文件名归类，候选命令从 README 里抄并带上**行号出处**（`README.md:99`），没有文档命令时才退化成带 `fallback` 标记的探测命令。数据只挂已审计的目录（`/data`，只读），没有审计过就不挂。

运行分两个阶段，**隔离发生在执行那一刻**：

| 阶段 | 网络 | 做什么 |
| --- | --- | --- |
| `download_wheels` | bridge | 只 `pip download` 拉 wheel 到 `/work/wheels`，不跑仓库代码 |
| `install_and_run` | none | 从本地 wheel 安装，然后在 `/work/src`（仓库的**副本**）里跑批准过的命令 |

仓库本身始终以只读挂在 `/src`：训练要往仓库目录写权重，所以命令在副本里跑，原始克隆不被改动。产物落在 `reproductions/runs/<run_id>/`（`run.json`、`download.log`、`run.log`、`work/`、`output/`），运行记录里会列出命令写出的文件，并把 JSON 顶层键 / CSV 表头摘出来 —— 指标就在那里，系统不去猜哪个文件是结果。

批准绑定的是**内容**：批准文件里记着计划内容的 sha256，执行前重算一次，不匹配就拒绝运行。所以批准之后改动计划不会悄悄生效，必须重新批准。

**前置条件：Docker。** 这一页需要 Docker Desktop（Windows 上用 WSL2 后端）；没装时接口会如实报错（`Docker is not usable: docker executable not found on PATH`），不会排一个永远跑不动的作业。要跑 GPU 训练还需要在 WSL2 里装 `nvidia-container-toolkit`，此时计划里 `requires_gpu` 为真才加 `--gpus all`。

## 4. 决策与论文

```powershell
conda run -n AIC python main.py plan
conda run -n AIC python main.py paper
```

`plan` 生成受规则约束的待办队列；`paper` 生成 `paper/generated/competition_report.tex`、`references.bib` 和证据映射。它不会虚构未记录的结果。

## 5. 连接端侧应用

端侧应用读两样东西：本机工作区文件，以及（可选）本地 Agent 的 HTTP 接口。

先启动只监听本机的 Agent：

```powershell
conda run -n AIC python main.py serve --port 8765
```

没有 Python 环境的机器上，用打包好的**本地执行器**起同一个服务（见 `docs/architecture.md` D7）：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_local_agent.ps1
dist\competition-agent-api.exe serve --port 8765
```

然后在鸿蒙端应用里把后端地址指向 `http://127.0.0.1:8765`。

**模拟器必须再做一步端口转发**，否则一直是"连接失败"：模拟器里的 `127.0.0.1` 是**模拟器自己**，
不是主机（它的 `Documents` 也不是主机的 Documents），主机上起没起后端都连不上。

```powershell
$hdc = "B:\Deveco_studio\setup\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe"
& $hdc rport tcp:8765 tcp:8765     # 设备 8765 -> 主机 8765
& $hdc fport ls                    # 应当看到 tcp:8765 tcp:8765 [Reverse]
```

**注意是 `rport` 不是 `fport`**：`fport localnode remotenode` 是"**主机**监听并转发到设备"，方向正好相反
（拿 `fport` 去映射 8765 会报 `TCP Port listen failed at 8765`，因为主机 8765 被后端自己占了）。
`rport` 只在 hdc 会话内有效，模拟器重启后要重新执行。

API 可达时应用读真实实验、数据审计与决策状态；不可达时应用切到**离线模式**，直接读工作区里已经
落盘的证据（规则就绪度、数据审计、实验历史、账本、文献检索、论文证据），并把需要重算的能力标成
"需外部执行器"。API 还提供 `/api/workflow`（当前阶段、阻塞项与推荐动作）和 `/api/capabilities`
（内置任务适配器及数据契约），便于应用按真实状态引导下一步。

### 让同一局域网内的手机接入

要让手机或鸿蒙设备通过局域网访问，改用局域网地址启动：

```powershell
$env:YJL_API_TOKEN = "pick-a-long-random-value"
conda run -n AIC python main.py serve --host 0.0.0.0 --port 8765
```

启动时会打印本机在局域网中的可访问地址与当前令牌。非回环绑定下，会消耗本地 API Key 或触发真实工作的端点必须携带 `X-YJL-Token` 请求头，包括 `/api/agent/deepseek`、`/api/rules/approve`、`/api/experiments/execute`、`/api/decisions/approve`、`/api/data-audit/run` 等；只读端点保持开放。未设置 `YJL_API_TOKEN` 时每次启动都会生成新令牌，客户端需要重新配置。

局域网模式与回环模式不要共用同一个端口：本机走回环端口，设备走另一个端口，两者读写同一工作区。若客户端是带 `Origin` 头的 Web 组件，可通过 `YJL_ALLOWED_ORIGINS`（逗号分隔）把它加入允许列表；该列表在局域网模式下不替代令牌，令牌始终是唯一凭据。

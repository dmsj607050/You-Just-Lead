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

检索是显式触发的网络操作，结果会落盘为 `research/papers.json` 和 `research/research_radar.md`：

```powershell
conda run -n AIC python main.py research --query "semantic segmentation boundary loss" --limit 5
```

第三方仓库先只创建审批记录：

```powershell
conda run -n AIC python main.py reproduce --repository https://github.com/owner/repository.git
```

仅当人工确认来源、许可证与资源预算后，才使用 `--approved` 克隆以供**静态检查**；该步骤仍不会执行下载的代码。静态检查通过后，可以用显式容器镜像和命令发起一次网络隔离、只读挂载的 smoke test：

```powershell
conda run -n AIC python main.py reproduce --repository https://github.com/owner/repository.git --approved --smoke-test --image python:3.11-slim --command "python --version"
```

完整复现仍应采用专门批准的数据挂载、镜像与资源预算，而不是直接在宿主机运行第三方代码。

## 4. 决策与论文

```powershell
conda run -n AIC python main.py plan
conda run -n AIC python main.py paper
```

`plan` 生成受规则约束的待办队列；`paper` 生成 `paper/generated/competition_report.tex`、`references.bib` 和证据映射。它不会虚构未记录的结果。

## 5. 连接前端

先启动只监听本机的 API：

```powershell
conda run -n AIC python main.py serve --port 8765
```

在另一个终端连接前端：

```powershell
cd frontend
$env:NEXT_PUBLIC_COMPETITION_API_URL = "http://127.0.0.1:8765"
npm run dev
```

前端在 API 可达时读取真实实验、数据审计和决策状态；不可达时明确显示演示数据模式。API 还提供 `/api/workflow`（当前阶段、阻塞项与推荐动作）和 `/api/capabilities`（内置任务适配器及数据契约），便于前端按真实状态引导下一步。已私密发布的云端界面无法直接读取你电脑上的数据，若要让云端展示真实数据，需要另行部署受认证保护的后端服务。

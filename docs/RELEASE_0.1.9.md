# You Just Lead 0.1.9 提交说明

> 状态（2026-09-24 核对）：下面点名的安装包**不在本仓库** —— `release/` 目录不存在，
> 全盘也找不到任何 `0.1.x` 安装包。这是一条**历史发布记录**，不是可下载的产物。
> 桌面端已按 `docs/architecture.md` D7 降级为 Legacy（源码在独立仓库 `frontend/`）。
> 下一阶段的版本流（dev → alpha → beta → RC → release）与 `release_manifest.json`
> 属于六个 Gate 里的 G6，等真实科研闭环(G4/G5)完成后再建。

## 安装包

- `release/You Just Lead_0.1.9_x64-setup.exe`：Windows 桌面安装包。

## 已验证的真实功能

- 本地桌面程序和 sidecar 启动；不依赖 ChatGPT 网页。
- 规则文件/公共网页导入、PDF/文本/HTML 解析、结构化报告、人工确认和项目内审计记录。
- 多源公开研究检索（arXiv、OpenAlex、Semantic Scholar、GitHub），并保存结果、来源故障和 Markdown 雷达报告。
- 用户确认的公开论文/源码可进入 `MAT-xxxx` 后台资料任务：PDF 下载与摘录、源码静态审查；第三方代码不会被自动执行。
- 训练骨架生成：在规则已确认、数据审计存在且适配器已实现时，生成 `configs/agent_baseline.yaml`、`reports/training_scaffold.json` 和 Markdown 报告，记录数据指纹、模型适配器、阻塞项和下一道环境门禁；此动作不启动训练。
- 训练部署页可真实读取本机 Conda、Python、NVIDIA GPU 总显存/空闲显存，并保存 `PROBE-xxxx` 报告；显存不足时给出有数字依据的服务器建议。
- 服务器探测在用户点击后经 SSH 私钥执行只读命令；密码不会传入 Agent 或落盘，且要求已验证服务器主机指纹。

## 尚未接入真实执行

- 图片 OCR、需要登录的规则网页。
- 受限论文下载、全文深度方法归纳，以及第三方源码的隔离运行复现。
- 新建 Conda 环境、安装依赖、SSH 远程同步/训练部署、自动调参和真实训练任务的前端启动审批链。

未接入阶段不得显示为已完成或已执行。

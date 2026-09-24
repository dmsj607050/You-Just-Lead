# You Just Lead 0.1.4 提交说明

## 交付物

- `release/You Just Lead_0.1.4_x64-setup.exe`：Windows 桌面安装包。
- 其余目录：完整源代码、测试、训练框架和示例工作区。

## 快速体验

1. 运行 `release/` 内的安装程序。
2. 启动 You Just Lead，打开左下角“模型设置”。
3. 保存 DeepSeek API Key 后点击“测试连接”；界面会保留并高亮成功或失败结果。

## 当前可真实运行的功能

- Windows 桌面端与本机 Agent 的启动、健康检查和 DeepSeek API Key 的本机安全存储。
- DeepSeek 连接测试与基于本地工作区状态的只读/草稿式 Agent 工具调用。
- YAML 配置化的合成、表格、回归、图像分类、分割等参考训练运行器。
- 训练前审批、实验账本、结果记录、曲线诊断、Markdown 报告和下一步实验建议。
- 本地 API 提供工作流、规则就绪度、数据审计、实验状态和训练任务查询。

## 当前仍为前端预览的流程

“项目 → 规则 → 检索 → 分析 → 构建 → 部署”工作台已经完成页面交互，但其中规则文件上传与解析、网页/PDF/图片读取、论文实时检索、源码下载复现、SSH/Conda/GPU 探测和一键训练尚未接入执行服务。界面会明确标注为“前端交互预览”，不应被视为真实执行结果。

## 代码运行

后端基础闭环：`python main.py init`、`python main.py run --experiment-id EXP-0001`、`python main.py status`。

桌面端重新打包：进入客户端仓库的 `desktop/`（本机 `B:\YouJustLead\desktop`）后运行 `npm run desktop:package`。

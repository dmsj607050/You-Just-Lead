# You Just Lead 0.1.7 提交说明

## 安装包

- `release/You Just Lead_0.1.7_x64-setup.exe`：Windows 桌面安装包。

## 已验证的真实功能

- 桌面程序与本地 sidecar 启动，不依赖 ChatGPT 网页。
- 规则文件/公共网页导入、PDF/文本/HTML 解析、结构化报告、人工确认与项目内审计记录。
- 多源公开研究检索：arXiv、OpenAlex、Semantic Scholar、GitHub 并行查询；结果、来源故障与 Markdown 雷达报告保存到 `research/`。
- 用户确认参考资料后，可创建可查询的后台资料任务（`MAT-xxxx`）。任务只下载选中的公开 PDF，并对公开源码进行静态复现审查；第三方代码不会被自动执行。
- 每项资料的论文下载、PDF 文本摘录、源码静态检查、失败原因和 Markdown/JSON 报告均保留在项目工作区。

## 尚未接入真实执行

- 扫描图片 OCR、需登录规则网页。
- 全文深度方法归纳、受限论文下载、源码的隔离运行复现。
- SSH 远程探测与一键训练。

未接入阶段不得视为已执行结果。

# You Just Lead 0.1.5 提交说明

## 安装包

- `release/You Just Lead_0.1.5_x64-setup.exe`：Windows 桌面安装包。
- SHA-256：`09EE73B98BA63B0853A04E3268A50397F8BE69AF229F86BDD19F5D8D5A6FE8F6`

## 本版本实际可用

- 桌面程序会启动本地 sidecar，不依赖 ChatGPT 网页。
- 规则页可上传 Markdown、文本、HTML、可选中文本的 PDF，或提交公共 HTTPS 规则网页。
- 原始规则材料会保存到项目工作区；Agent 会生成 `competition_spec.yaml`、Markdown 规则报告、提交清单和提取审计记录。
- 前端显示实际提取字段、证据数量、完整 Markdown 报告和未解决的核对项；人工填写核对说明后才可进入下一阶段。
- 本地 sidecar 已进行打包后烟雾测试：规则导入、报告读取、人工确认，以及 PDF 解析依赖均通过。

## 明确尚未接入

- 扫描图片 OCR、网页需要登录时的规则获取。
- 研究资料实时检索/筛选、论文与源码下载复现。
- SSH 服务器探测、Conda/GPU 自动配置与一键训练。

这些未接入的阶段仍应按前端原型看待，不能当作已真实执行。

# You Just Lead 0.1.6 提交说明

> 状态（2026-09-24 核对）：下面点名的安装包**不在本仓库** —— `release/` 目录不存在，
> 全盘也找不到任何 `0.1.x` 安装包。这是一条**历史发布记录**，不是可下载的产物。
> 桌面端已按 `docs/architecture.md` D7 降级为 Legacy（源码在独立仓库 `frontend/`）。

## 安装包

- `release/You Just Lead_0.1.6_x64-setup.exe`：Windows 桌面安装包。

## 已验证的真实功能

- 桌面程序与本地 sidecar 启动，不依赖 ChatGPT 网页。
- 规则文件/公共网页导入、PDF/文本/HTML 解析、结构化报告、人工确认与项目内审计记录。
- 多源公开研究检索：arXiv、OpenAlex、Semantic Scholar、GitHub 并行查询；结果、来源故障与 Markdown 雷达报告保存到 `research/`。
- 前端展示真实返回的来源、年份、原文/源码链接、源码可用性和来源故障；用户可取消候选资料后确认采用范围。

## 尚未接入真实执行

- 扫描图片 OCR、需登录规则网页。
- 论文与源代码的批量下载、静态复现审查、SSH 远程探测与一键训练。

未接入阶段不得视为已执行结果。

# Release 1.0.0-rc.4

这是功能冻结后的验证候选版。版本清单记录提交、运行时版本与每个交付文件的摘要；
候选包暂存于 `build/release-rc4-candidate/`。

## 版本与构建

- 版本：`1.0.0-rc.4`
- Windows 应用代码提交：`3037283aa3aba07b1def0456dcbc7b48a19d7384`
- API EXE 重建时仓库位于 `e1d091a21b02c7a1d5d9bf0d0c8ecd6eeae5ba51`；该提交只补充验证文档，应用代码与 `3037283` 相同。
- 本地执行器重建时间：2026-09-29 16:01（Asia/Shanghai）
- 嵌入式 Python：`3.10.10`

## 交付文件

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `competition-agent-api.exe` | 10,206,066 | `82703141a42e844f938394ec65fd60d95f47678449273f7a89be49f50f8e00d7` |
| `YouJustLead.exe` | 10,253,913 | `290b4f6ea4da77668d00170512ed2eab421a8f86f963e338958ee9cb7e9e35b5` |
| `entry-default-signed.hap` | 3,161,410 | `310fcd93383178a010bd2749fb5b35040a91ab33841619802af69b4a41bac6f2` |

## 验证

- 本地 API EXE 在隔离工作区启动；由该 EXE 的监听子进程服务的回环 `/health` 返回 HTTP 200 和 `status: ok`。验收使用端口 `57858`，随后清理了本次启动的父子进程。
- 候选目录内三个产物的字节数与 SHA-256 均和 `release_manifest.json` 一致；清单的 `release_ready` 为 `true`。
- HAP 已按 CHANGELOG 中记录的流程在 `127.0.0.1:5555` 模拟器安装并查看浅色、深色主界面。真机、窄屏和字体放大仍未验。

## 发布边界

- 这份清单只确认版本与本地构建产物，不代表六个 Gate 全部通过。
- G4/G5 的九项实验核查仍未完成真实验收；D12 的远程多用户连接与隔离也未完成。
- 本候选版没有创建 GitHub Release。当前 GitHub CLI 登录令牌失效，且远程发布形态仍待验收。

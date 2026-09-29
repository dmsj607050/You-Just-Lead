# Release 1.0.0-rc.5

这是规则复核改进后的验证候选版。候选包暂存于 `build/release-rc5-candidate/`；仓库内既有的 `release/` 目录未修改。

## 版本与构建

- 版本：`1.0.0-rc.5`
- Windows 应用源代码提交：`c05f9f6c87cf596b9c3e2b5419c99c004968446d`
- Windows EXE 使用 Python `3.10.10`、PyInstaller `6.22.3` 重建。
- 清单生成时间：`2026-09-29T11:34:27+00:00`；清单记录工作区干净，commit 为 `c05f9f6c87cf596b9c3e2b5419c99c004968446d`。
- HAP 沿用 rc.4 的构建产物；本候选没有端侧源码变更，也没有重新构建 HAP。其 SHA-256 与 rc.4 相同。

## 交付文件

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `competition-agent-api.exe` | 10,207,197 | `2dd178c5df1b94d9fe5eb634508bb30dc1b4dffccafd59da96c33af872542209` |
| `YouJustLead.exe` | 10,263,886 | `1c3781f34cc12a6e42974bb290dabf1c713317f8c47ef6d942dd5708a72d7dd5` |
| `entry-default-signed.hap` | 3,161,410 | `310fcd93383178a010bd2749fb5b35040a91ab33841619802af69b4a41bac6f2` |

三个文件的大小与 SHA-256 已逐一和候选目录中的 `release_manifest.json` 核对；`SHA256SUMS.txt` 由这些摘要生成。

## 验证

- Python 全量回归实跑：437 项通过，0 failures、0 errors、0 skipped。另在版本号更新后重跑发布清单专项测试：26 项通过。
- 两个新建 Windows EXE 的 `--help` 实跑退出码均为 0。
- API EXE 在隔离的 B 盘数据根与回环端口 `58765` 启动；`GET /health` 实返 `status: ok`，并报告隔离工作区 `build/api-smoke-localappdata/YouJustLead/workspace/current_competition`。测试结束后端口已关闭，测试数据库与工作区骨架均在 `build/` 下。
- 在干净提交上执行 `release-manifest --print`，退出码为 0，`release_ready: true`，`release_blockers: []`。此状态只代表版本、必需构建产物和 Git 干净条件满足。
- HAP 上一候选已安装至模拟器并查看浅色、深色界面；本候选未重做该项。真机、窄屏与字体放大仍未验。

## 发布边界

- Windows EXE 仍在用户电脑启动本地后端，鸿蒙端默认连本机 API。虽然模型来源可由用户配置、密钥存本机系统凭据库，客户端仍未接入已部署的远程服务器；云端认证和多用户数据隔离也未完成验收。
- G4/G5 的真实研究闭环与九项核查未通过本候选重新验收；G6 与 GitHub Release 发布也未完成。
- 清单的 `release_ready: true` 不代表六个 Gate 全部通过，也不表示此候选已对外发布。

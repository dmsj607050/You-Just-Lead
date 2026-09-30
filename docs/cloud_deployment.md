# 云端账号服务部署记录

更新时间：2026-09-30。该文档记录 RC6 云账号与托管 DeepSeek 问答服务，不能替代正式 Release、备案或隐私政策。

## 当前拓扑

```text
鸿蒙 HAP
  └─ HTTPS https://nucrobot.online/yjl-cloud/api/...
       └─ Nginx (现有 HTTPS 虚拟主机)
            └─ 127.0.0.1:8766
                 └─ youjustlead-cloud-rc6.service
                      └─ /var/lib/youjustlead-cloud-rc6
```

- 独立服务单元：`youjustlead-cloud-rc6.service`，仅监听回环地址 `127.0.0.1:8766`，专用系统用户运行。
- 部署代码：`/opt/youjustlead-cloud-rc6`；用户数据：`/var/lib/youjustlead-cloud-rc6`。
- Nginx 仅新增 `/yjl-cloud/api/` 代理路径。原有网站 `/` 和 `youjustlead.service` 未被替换。
- Nginx 修改前的配置副本：`/etc/nginx/sites-available/nucrobot.codex-backup-rc6-20260929`。
- 模型密钥沿用服务器秘密环境配置，由服务端读取；不要把值复制进文档、命令行回显、客户端或日志。
- HAP API 根地址：`https://nucrobot.online/yjl-cloud`。例如健康检查是 `https://nucrobot.online/yjl-cloud/api/health`。

## 线上验收记录

- 健康检查：HTTPS 200，响应 `status: ok`、`mode: cloud`。
- 匿名访问项目 API：401；没有 HTTPS 代理标记的云请求：426。
- 两个随机验收账号的注册、登录和登出撤销通过；一个账号创建隔离验收项目。
- 一次 DeepSeek 问答实际消耗输入 3,083 + 输出 578 = 3,661 token；账本扣减 3,661，余额从 100,000 变为 96,339。
- 验收数据保留在服务器：三个随机账号；一个空账号，一个有模型验收项目和问答计费账目，另一个由 HAP 注册、创建空白项目并完成一次短问答。没有清理这些数据。
- API 的账号隔离测试已覆盖两个账号互不可见；本次没有再从公网跨账号请求对方项目。
- HAP 在模拟器经公网完成注册、自动登录、100 积分显示、项目创建和进入工作流，并从工作流发起一条短问答。应用重启后再次读取服务端余额，从 100.00 变为 97.95 积分，和一次问答的 token 扣账相符。

## 查看服务状态

有服务器 SSH 权限的维护者可运行：

```bash
sudo systemctl status youjustlead-cloud-rc6.service --no-pager
sudo journalctl -u youjustlead-cloud-rc6.service -n 100 --no-pager
curl -fsS https://nucrobot.online/yjl-cloud/api/health
```

日志只用于看状态与错误，不要输出或复制秘密环境变量。

## 单独回滚云账号路由

部署采用独立服务和独立 Nginx 路径。若需要停用 RC6 云账号服务，可先在 Nginx 配置中撤下 `location /yjl-cloud/api/` 块，运行 `sudo nginx -t`，再平滑 reload；随后运行 `sudo systemctl disable --now youjustlead-cloud-rc6.service`。旧的 `youjustlead.service` 和网站 `/` 保持原状。备份文件保存在上文路径，可供维护者人工对照恢复。

停用服务不会删除 `/var/lib/youjustlead-cloud-rc6` 中的用户与账本数据。若要删除、迁移或清理这批数据，先备份并由项目负责人单独决定；此部署记录不授权删除数据。

## 尚未具备的生产运营能力

- 每用户存储配额、全局并发限制、费用告警、管理员快速停用开关。
- 密码恢复、账号删除、HAP 会话令牌的 HUKS 保护。
- 云端训练或重型数据审计执行器配对；当前 ECS 为 2 核 2 GiB、无 GPU。
- HAP 真机、窄屏、深色、放大字体验收；模拟器上的公网注册、登录、建项目、进入工作流和问答链路已在上文记录。
- Windows 桌面端仍是本地模式，不连接该账号服务。

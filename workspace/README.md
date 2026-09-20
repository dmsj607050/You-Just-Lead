# Competition workspace

每个子目录是一个项目（一场竞赛的工作区）：规则、数据、实验、模型与提交候选都在里面，
互不干扰。

`projects.json` 是项目注册表，记「有哪些项目、当前是哪一个」：

```json
{
  "version": 1,
  "current": "current_competition",
  "projects": [
    { "id": "current_competition", "name": "高分辨率遥感影像水体智能分割", "created_at": "..." }
  ]
}
```

- 首次读取注册表时会自动扫描已有工作区补登记，所以 `current_competition/` 不需要手工搬动，
  它就是这个文件里的第一个项目。
- App 的启动页读 `GET /api/projects`，新建走 `POST /api/projects`（建目录骨架 + 从
  `competition_spec.template.yaml` 复制一份带项目名的规格），切换走 `POST /api/projects/select`，
  删除走 `DELETE /api/projects/<id>`（**连工作区目录一起删**，不可恢复；有任务在跑时拒绝删除）。
- 删掉的如果是当前项目，`current` 置空而不会自动改选别的项目：客户端会回到项目选择页，
  命令行会报「先选一个项目」。
- 命令行默认作用在**当前项目**上；要指定别的项目就传 `--workspace workspace/<id>`。

# 官方规则确认表

用途：请从已登录的“高分辨率遥感影像水体分割挑战赛”规则页逐项填写。不要依据记忆填写；每项应附页面原文或截图位置。该表完成后，系统才能解除真实训练和候选提交包校验的规则门槛。

| 字段 | 已有证据 | 需要从官方页确认的值 | 证据位置 |
|---|---|---|---|
| 截止时间 | 公开列表显示 2026-08-27 | `YYYY-MM-DD HH:MM Asia/Shanghai` | 待填 |
| 每日提交次数 | 本地规则总结为 3 | 整数 | 待填 |
| 推理包格式 | `.tar.gz`，入口为顶层 `run.py` | 是否仍有效 | 待填 |
| 运行时输出 | 本地总结称直接 PNG；现有模板写 `submit.zip` | `loose_png` 或 `submit_zip` | 待填 |
| 输出目录 | 本地总结为 `/work/output/` | 完整绝对路径 | 待填 |
| 输出文件名 | `<input_stem>_mask.png` | 精确命名规则 | 待填 |
| 输出掩膜 | 1024×1024、单通道、像素 0/255 | 是否仍有效 | 待填 |
| 模型体积 | 本地总结为不超过 600 MB | 限制对象（模型/包）与单位 | 待填 |
| 推理硬件与时限 | 未确认 | GPU、显存、时限、CPU/RAM | 待填 |
| 预训练模型 | 未确认 | 是否允许、必须披露哪些来源 | 待填 |
| 外部数据 | 未确认 | 是否允许、允许范围与披露要求 | 待填 |
| TTA / 多尺度 | 未确认 | 是否允许及是否计入模型集成 | 待填 |
| 多模型集成 | 未确认 | 是否允许与模型数/体积规则 | 待填 |

## 填完后的配置变更

在 `competition_spec.yaml` 中：

1. 填入精确 `competition.deadline`、`submission.daily_limit`、`submission.contract.runtime_output`；
2. 将 `constraints.pretrained_models_allowed`、`external_data_allowed`、`ensemble_allowed` 写为明确的 `true` 或 `false`；
3. 填入 `constraints.inference_time_limit_seconds` 与其他适用限制；
4. 删除 `approval.unresolved_questions` 中已被官方原文解答的问题；
5. 只有所有问题都删除后，才把 `approval.requires_human_confirmation` 设为 `false`。

## 审批与启动顺序

规则确认本身、GPU 预算批准、训练执行是三个独立步骤：

```powershell
cd 'B:\You Just Lead\competition-agent'
python main.py approve-rules --workspace workspace\current_competition --note '已按官方规则页复核，证据见 docs/official_rule_confirmation.md'
python main.py approve-run --workspace workspace\current_competition --config configs\xunfei_waterseg_v16_stage1.yaml --note '批准 fold-0 v16 stage-1，预算 30 GPU 小时'
python main.py run --workspace workspace\current_competition --config configs\xunfei_waterseg_v16_stage1.yaml
```

第二条命令会绑定该配置的 SHA-256；任何数据路径、超参数、预训练权重来源或外部源码指纹变化，都需要重新审查和批准。

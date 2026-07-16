# Competition Agent

面向机器学习竞赛的实验驱动研发工作流系统。

```text
规则确认 → 数据审计 → 可复现基线 → 实验记录 → 结果诊断
→ 候选方案 → 人工审批 → 新实验 → 论文证据整理
```

第一版先建立可靠的实验基础设施。人负责研究方向、预算和高风险操作审批；Agent 负责执行、记录、分析与建议。

## 首次使用

1. 将 `workspace/current_competition/competition_spec.template.yaml` 复制为 `competition_spec.yaml`，根据官方规则填写。
2. 将原始比赛资料放进 `workspace/current_competition/input/`，不要修改原始文件。
3. 每次训练前创建运行清单到 `experiments/manifests/`；训练后将结构化结果写入 `experiments/results/`。
4. 从结果生成实验日志、最佳方案和下一步建议。

## 目录原则

- `agents/`、`tools/`、`schemas/`：后端可复用能力，不保存某一比赛的产物。
- `workspace/current_competition/`：当前比赛的规则、报告、实验、模型与提交候选。
- `database/`：Agent 状态、审批、论文与实验关系的结构化存储。
- `paper/`：从实验记录生成的论文草稿、表格和证据映射。

详细行为约束见 [AGENT.md](AGENT.md)。

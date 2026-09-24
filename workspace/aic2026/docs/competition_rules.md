# Competition rules — review draft

> This file is generated from a local source document. Confirm every unresolved item before training or submission.

## Extracted specification

### Competition
- **name**: AIC2026 面向城市场景的视觉多模态目标检测
- **platform**: unresolved
- **task_type**: unresolved
- **deadline**: unresolved

### Data

### Evaluation
- **primary_metric**: unresolved
- **direction**: maximize
- **public_private_split**: unresolved

### Submission
- **format**: unresolved
- **filename_rule**: unresolved
- **required_columns**: []
- **id_column**: unresolved
- **expected_rows**: unresolved
- **daily_limit**: unresolved

### Constraints
- **external_data_allowed**: unresolved
- **pretrained_models_allowed**: True
- **ensemble_allowed**: False
- **inference_time_limit_seconds**: unresolved
- **model_size_limit_mb**: unresolved

## Source evidence

- `constraints.ensemble_allowed` — line 222:  禁止将多个不同结构或训练阶段的模型进行简单集成，直接采用投票法、平
- `constraints.pretrained_models_allowed` — line 226:  允许使用 ImageNet、COCO、Objects365 等公开预训练权重。

## Required human confirmation

- [ ] Confirm competition.task_type from the official rules.
- [ ] Confirm evaluation.primary_metric from the official rules.
- [ ] Confirm submission.format from the official rules.
- [ ] Confirm constraints.external_data_allowed from the official rules.

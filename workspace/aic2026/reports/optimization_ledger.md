# Optimization ledger

This document is generated from frozen experiment manifests and results.
Use it to select one controlled next change; do not treat a missing entry as a negative result.

## EXP-0001 — failed

- Change type: `baseline`
- Parent / rollback: `none`
- Data version: `3043a20b5b88cfcd354d80c1d450f4f8566d25a2da5783df2d3e5c9b973f53d6`
- Config: `configs\aic_detection_external.yaml`
- Hypothesis: 三模态检测数据读取、Ultralytics 训练与验证、mAP@50-95 落盘这条链在真实数据上可复跑，并给出一个可比的参考点。
- Validation metric: not produced
- Best epoch: not produced
- Decision: `reject`
- Conclusion: Experiment failed before producing validated results.

- Failure: RuntimeError: Detection training command failed with exit code 1; inspect B:\You Just Lead\competition-agent\workspace\aic2026\experiments\artifacts\EXP-0001\detection_train.log before retrying.

### Evidence-led next candidates

- Inspect the captured error before retrying.

## EXP-0002 — failed

- Change type: `baseline`
- Parent / rollback: `none`
- Data version: `3043a20b5b88cfcd354d80c1d450f4f8566d25a2da5783df2d3e5c9b973f53d6`
- Config: `configs\aic_detection_external.yaml`
- Hypothesis: 三模态检测数据读取、Ultralytics 训练与验证、mAP@50-95 落盘这条链在真实数据上可复跑，并给出一个可比的参考点。
- Validation metric: not produced
- Best epoch: not produced
- Decision: `reject`
- Conclusion: Experiment failed before producing validated results.

- Failure: RuntimeError: Detection training command failed with exit code 1; inspect B:\You Just Lead\competition-agent\workspace\aic2026\experiments\artifacts\EXP-0002\detection_train.log before retrying.

### Evidence-led next candidates

- Inspect the captured error before retrying.

## EXP-0003 — failed

- Change type: `baseline`
- Parent / rollback: `none`
- Data version: `3043a20b5b88cfcd354d80c1d450f4f8566d25a2da5783df2d3e5c9b973f53d6`
- Config: `configs\aic_detection_external.yaml`
- Hypothesis: 三模态检测数据读取、Ultralytics 训练与验证、mAP@50-95 落盘这条链在真实数据上可复跑，并给出一个可比的参考点。
- Validation metric: not produced
- Best epoch: not produced
- Decision: `reject`
- Conclusion: Experiment failed before producing validated results.

- Failure: RuntimeError: Detection training command failed with exit code 1; inspect B:\You Just Lead\competition-agent\workspace\aic2026\experiments\artifacts\EXP-0003\detection_train.log before retrying.

### Evidence-led next candidates

- Inspect the captured error before retrying.

## EXP-0004 — failed

- Change type: `baseline`
- Parent / rollback: `none`
- Data version: `3043a20b5b88cfcd354d80c1d450f4f8566d25a2da5783df2d3e5c9b973f53d6`
- Config: `configs\aic_detection_external.yaml`
- Hypothesis: 三模态检测数据读取、Ultralytics 训练与验证、mAP@50-95 落盘这条链在真实数据上可复跑，并给出一个可比的参考点。
- Validation metric: not produced
- Best epoch: not produced
- Decision: `reject`
- Conclusion: Experiment failed before producing validated results.

- Failure: RuntimeError: Detection training command failed with exit code 1; inspect B:\You Just Lead\competition-agent\workspace\aic2026\experiments\artifacts\EXP-0004\detection_train.log before retrying.

### Evidence-led next candidates

- Inspect the captured error before retrying.

## EXP-0005 — failed

- Change type: `baseline`
- Parent / rollback: `none`
- Data version: `3043a20b5b88cfcd354d80c1d450f4f8566d25a2da5783df2d3e5c9b973f53d6`
- Config: `configs\aic_detection_external.yaml`
- Hypothesis: 三模态检测数据读取、Ultralytics 训练与验证、mAP@50-95 落盘这条链在真实数据上可复跑，并给出一个可比的参考点。
- Validation metric: not produced
- Best epoch: not produced
- Decision: `reject`
- Conclusion: Experiment failed before producing validated results.

- Failure: KeyError: 'val_loss'

### Evidence-led next candidates

- Inspect the captured error before retrying.

## EXP-0006 — completed

- Change type: `baseline`
- Parent / rollback: `none`
- Data version: `3043a20b5b88cfcd354d80c1d450f4f8566d25a2da5783df2d3e5c9b973f53d6`
- Config: `configs\aic_detection_external.yaml`
- Hypothesis: 三模态检测数据读取、Ultralytics 训练与验证、mAP@50-95 落盘这条链在真实数据上可复跑，并给出一个可比的参考点。
- Validation metric: 0.00234
- Best epoch: 1
- Decision: `keep_as_candidate`
- Conclusion: Baseline completed with validation metric 0.0023.

### Metrics

- `epochs_scored`: 1.0
- `learning_rate`: 0.000203488
- `train_box_loss`: 1.99506
- `train_cls_loss`: 6.5347
- `train_dfl_loss`: 0.00661
- `train_loss`: 8.53637
- `val_box_loss`: 1.94829
- `val_cls_loss`: 5.33426
- `val_dfl_loss`: 0.00819
- `val_loss`: 7.29074
- `val_map50`: 0.00367
- `val_map50_95`: 0.00234
- `val_precision`: 0.00698
- `val_recall`: 0.06718

### Evidence-led next candidates

- 在保持当前基线的前提下，只验证一个低成本改动。

## EXP-0007 — completed

- Change type: `baseline`
- Parent / rollback: `none`
- Data version: `3043a20b5b88cfcd354d80c1d450f4f8566d25a2da5783df2d3e5c9b973f53d6`
- Config: `configs\loop\baseline_rerun.yaml`
- Hypothesis: 重跑 EXP-0006 同配置链路，判断 val_map50_95=0.00234 的参考点是否能在 ±0.001 容差内复现，从而判决该链路在真实数据上可复跑且参考点可比。
- Validation metric: 0.00234
- Best epoch: 1
- Decision: `keep_as_candidate`
- Conclusion: Baseline completed with validation metric 0.0023.

### Metrics

- `epochs_scored`: 1.0
- `learning_rate`: 0.000203488
- `train_box_loss`: 1.99506
- `train_cls_loss`: 6.5347
- `train_dfl_loss`: 0.00661
- `train_loss`: 8.53637
- `val_box_loss`: 1.94829
- `val_cls_loss`: 5.33426
- `val_dfl_loss`: 0.00819
- `val_loss`: 7.29074
- `val_map50`: 0.00367
- `val_map50_95`: 0.00234
- `val_precision`: 0.00698
- `val_recall`: 0.06718

### Evidence-led next candidates

- 在保持当前基线的前提下，只验证一个低成本改动。

## EXP-0008 — completed

- Change type: `ablation`
- Parent / rollback: `none`
- Data version: `3043a20b5b88cfcd354d80c1d450f4f8566d25a2da5783df2d3e5c9b973f53d6`
- Config: `configs\loop\stage_fusion_vs_rgb.yaml`
- Hypothesis: 在 EXP-0007 同配置下，仅把输入模态从 RGB 单模态改为 RGB+IR+Depth 早融合（external.stage: rgb→fusion），判决 val_map50_95 是否高于 RGB 参考点 0.00234。
- Validation metric: 0.00211
- Best epoch: 1
- Decision: `keep_as_candidate`
- Conclusion: Baseline completed with validation metric 0.0021.

### Metrics

- `epochs_scored`: 1.0
- `learning_rate`: 0.000203488
- `train_box_loss`: 2.00207
- `train_cls_loss`: 6.93193
- `train_dfl_loss`: 0.00664
- `train_loss`: 8.94064
- `val_box_loss`: 1.97557
- `val_cls_loss`: 5.37317
- `val_dfl_loss`: 0.00822
- `val_loss`: 7.35696
- `val_map50`: 0.00328
- `val_map50_95`: 0.00211
- `val_precision`: 0.00363
- `val_recall`: 0.10466

### Evidence-led next candidates

- 在保持当前基线的前提下，只验证一个低成本改动。


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


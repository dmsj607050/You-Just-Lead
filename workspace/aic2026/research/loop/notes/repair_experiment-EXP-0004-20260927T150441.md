# REPAIR_EXPERIMENT EXP-0004

建议终止对 EXP-0004 的修复。依据：
(1) 实验登记表里 EXP-0004 已判定为 decision=reject、状态 failed；同 hypothesis 且 config_sha256 完全一致（d96d5a826eefd9fde0f39a2dcd3d496e92ab4abe50e36c661021c2b5b2e0783e）的 EXP-0006 状态为 completed、decision=keep_as_candidate、validation_metric=0.00234（best_epoch=1），说明该配置的基线链路在后续运行中已经真正跑通并产出 Held-out 指标，修复 EXP-0004 不会再产生新的证据增量。
(2) EXP-0004 的 runtime 只有 19.775 秒（EXP-0005 为 113.01s、EXP-0006 为 107.813s），错误显示 training command exit code 1；但我无法读到 experiments/artifacts/EXP-0004/detection_train.log 的实际内容——工作区文件读取工具持续返回 'path escapes the workspace'，run_command 也因 Docker 未运行而失败。这是『没查到日志内容』，不是『确认日志里没有问题』。在无法指回日志具体报错行的情况下，对训练脚本或 configs/aic_detection_external.yaml 做任何具体修改都只能是猜测，会污染证据链。
(3) 该配置的 change_type=baseline，manifest 的 expected_improvement 明确写的是『建立可复现的 Held-out 参考指标；本配置的目标是链路正确，不是榜单分数』，这个目标已经由 EXP-0006 达成；资源应转向当前分支 B0001 的下一个正式改动，而不是继续修一个已被 reject 且后续已成功复跑的历史失败实验。

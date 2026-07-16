# 第一阶段：实验基础设施

## 已交付能力

1. 统一训练入口：training.runner 按配置选择任务适配器；当前含可运行的合成二分类参考实现。
2. 实验配置：每次训练保存不可变的 YAML 配置快照与 SHA-256 哈希。
3. Git 绑定：运行前记录当前 commit、分支与工作区脏状态；若未初始化 Git，则明确记录 unavailable。
4. 追踪：优先使用已安装的 MLflow；未安装时写入 experiments/tracking/mlflow_fallback.jsonl。
5. 实验账本：Manifest 和 Result 均写入 JSON，并同步到 database/competition_agent.sqlite。
6. 自动报告：从结构化 Result 生成 EXPERIMENT_LOG、BEST_RUN、FAILED_IDEAS、NEXT_ACTIONS 和 reports/training_summary。

## 运行约束

真实比赛训练应在已读取官方规则、完成数据审计并完成审批后启动。每一次真实训练必须通过配置文件定义数据版本、随机种子、训练命令和验证指标。

## 启用原生 MLflow

安装可选依赖后，无需修改代码，下一次运行会自动选择 MLflow 后端：

    python -m pip install .[mlflow]

本地 JSONL 回退记录不丢失任何第一阶段所需的参数、指标与产物路径。

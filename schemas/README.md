# Data contracts

Markdown is derived from structured data, so the shapes below are contracts, not suggestions.

## 已经存在的

| 文件 | 是什么 | 谁在用 |
|---|---|---|
| `experiment.py` | `ExperimentManifest`（开跑前的计划）与 `ExperimentResult`（跑完的结果），两个 dataclass | `app/experiment_service.py` 生产；端侧离线状态页读取 |
| `action.py` | 下一步动作与建议的结构 | `agents/strategy_agent.py` |
| `contracts.py` | **项目级数据契约登记表**：字段名 + 类型 + 谁生产 + 谁消费 | `tests/test_canonical_contracts.py` 拿真实产出核对 |

## 契约层怎么运作（`contracts.py`）

规则域有**两套实现**（后端 `agents/rules_agent.py`、端侧 `entry/src/main/ets/common/LocalRuleGate.ets`），
两边今天逐字对齐，但没有任何东西阻止某一侧改名或加字段 —— 那种漂移是**静默**的：文件照样写出来，
另一侧读到的却是空值。`contracts.py` 把「字段名 + 类型 + 生产者 + 消费者」写在一处，
用测试去核对：

- **Python 侧**：调用真实生产函数，断言字段集合、类型逐条吻合，且**没有未声明的字段**。
- **端侧**：检查声明的字段名是否仍出现在端侧读/写那段源码里。这是**源码级检查**，
  不是运行时校验 —— 端侧没有 JSON Schema 校验库，也不在 Python 进程里。
  端侧运行时的一致性由装机验收负责，见 `docs/architecture.md` D5。

### 为什么不是 JSON Schema

本仓库不引第三方依赖（Python 侧），端侧也没有 JSON Schema 校验库。
写成 `*.schema.json` 只会得到一份**没人校验**的文档，看着规范、实际拦不住漂移。
所以这里选择"可执行的声明 + 真实产出对拍"，能力边界写清楚，不假装更强。

## 还没有的

下面这些在早期计划里列过，但**至今没有实现，也没有被任何代码需要**，所以不在这里假装存在：

- `competition.py` —— 规则/数据路径/指标/限制的强类型化（目前由 `tools/configuration.py`
  的 `load_yaml` + `agents/rules_agent.py` 的字段清单承担）；
- `paper.py` —— 论文元数据、代码溯源、许可、复现记录；
- `proposal.py` —— 假设、证据、成本、风险与回滚（目前由 `schemas/action.py` 与
  `agents/strategy_agent.py` 的输出结构承担）。

要加就按 `contracts.py` 的方式加：**先有真实生产者，再登记契约、加对拍测试**。
不要先写一份 schema 再去找谁来用。

"""项目级数据契约：一份声明，两端（Python / ArkTS）都按它对齐。

这个模块存在的理由是一个真实风险：规则域现在有**两套实现** —— 后端 `agents/rules_agent.py`
与端侧 `entry/src/main/ets/common/LocalRuleGate.ets`。今天它们逐字对齐，但没有任何东西阻止
半年后某一侧改名、加字段或改类型，而那种漂移是**静默**的：文件照样写出来，另一侧读到的却是空值。

契约把「字段名 + 类型 + 谁生产 + 谁消费」写在一处，再由
`tests/test_canonical_contracts.py` 拿**真实产出**去核对 —— 漂移会让测试失败。

## 为什么不是 JSON Schema

本仓库不允许第三方依赖（Python 侧），端侧（ArkTS）也没有 JSON Schema 校验库。
所以这里的契约是**可执行的声明**，不是通用校验器的输入：

- **Python 侧**：测试调用真实生产函数，断言字段集合与类型逐条吻合，且**没有未声明的字段**
  （加了字段却没更新契约同样会失败）。
- **端侧**：测试检查声明的字段名是否仍出现在端侧读/写那段源码里。这是**源码级检查**，
  不是运行时校验 —— 能力边界就是这么多，别把它当成端侧也被自动校验了。
  端侧的运行时不变量（写出的文件与后端逐字段一致）由验收流程负责，见 `docs/architecture.md`。
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 契约格式自身的版本。改字段含义（不是改字段名）时递增。
CONTRACT_VERSION = 1

#: 字段类型名 → 判定函数。`any` 只用于"值可以是任何 YAML/JSON 标量"的位置。
TYPE_CHECKS: dict[str, str] = {
    "str": "isinstance(value, str)",
    "bool": "isinstance(value, bool)",
    "int": "isinstance(value, int) and not isinstance(value, bool)",
    "float": "isinstance(value, (int, float)) and not isinstance(value, bool)",
    "dict": "isinstance(value, dict)",
    "list": "isinstance(value, list)",
    "any": "True",
}

#: 通配一段：`fields.*` 表示"这个字典的每一个值"。只允许出现在路径末尾或中间一段。
WILDCARD = "*"


@dataclass(frozen=True)
class ArktsSite:
    """端侧某处读或写这份契约的位置。

    `locator` 是 `相对仓库根的路径::符号`，指向端侧那个文件里的一个函数或常量名；
    `markers` 是必须出现在**该文件**里的字段名。只做"名字还在不在"的检查。
    """

    locator: str
    role: str
    markers: tuple[str, ...]


@dataclass(frozen=True)
class Contract:
    """一份数据契约。

    `fields` 的键是**点分路径**，可以带一段 `*` 通配（如 `fields.*.anchor`）；
    值是 `TYPE_CHECKS` 里的类型名。
    """

    name: str
    purpose: str
    python_producer: str
    python_consumer: str
    fields: dict[str, str]
    arkts_sites: tuple[ArktsSite, ...] = field(default_factory=tuple)
    invariants: tuple[str, ...] = field(default_factory=tuple)


_RULE_EVIDENCE_FIELDS: dict[str, str] = {
    "profile": "str",
    "source": "dict",
    "source.source_type": "str",
    "source.source_locator": "str",
    "source.reviewed_at": "str",
    "fields": "dict",
    f"fields.{WILDCARD}": "dict",
    f"fields.{WILDCARD}.value": "any",
    f"fields.{WILDCARD}.anchor": "str",
}

CONTRACTS: dict[str, Contract] = {
    "rule_profile": Contract(
        name="rule_profile",
        purpose="规则档案的必备字段清单与类型敏感字段的控件类型（讯飞水体分割 19 个字段 / AIC 三模态检测 24 个字段）",
        python_producer="agents/rules_agent.py::RULE_PROFILES",
        python_consumer="agents/rules_agent.py::rule_confirmation_readiness_for_workspace",
        fields={"required_fields": "list", "field_kinds": "dict", "profile": "str"},
        arkts_sites=(
            ArktsSite(
                locator="entry/src/main/ets/common/LocalRules.ets::RULE_PROFILES",
                role="consumer",
                markers=(
                    "BASE_CONFIRMATION_FIELDS",
                    "XUNFEI_CONFIRMATION_FIELDS",
                    "AIC_DETECTION_CONFIRMATION_FIELDS",
                    "ruleProfileName",
                    "evidenceFieldKind",
                ),
            ),
        ),
        invariants=(
            "required_fields 里没有重复项",
            "field_kinds 的键必须是 required_fields 的子集（给不存在的字段声明控件类型是隐藏 bug）",
            "profile 必须是 RULE_PROFILES 里的一个档案名；generic 表示还没认领档案",
        ),
    ),
    "rule_evidence": Contract(
        name="rule_evidence",
        purpose="人工复核过的官方规则证据记录：工作区 docs/rule_evidence_*.yaml 的内容格式",
        python_producer="agents/rules_agent.py::build_rule_evidence_record",
        python_consumer="agents/rules_agent.py::apply_official_rule_evidence",
        fields=_RULE_EVIDENCE_FIELDS,
        arkts_sites=(
            ArktsSite(
                locator="entry/src/main/ets/common/LocalRuleGate.ets::buildRecord",
                role="producer",
                markers=(
                    "profile",
                    "source_type",
                    "source_locator",
                    "reviewed_at",
                    "value",
                    "anchor",
                    "source",
                    "fields",
                ),
            ),
        ),
        invariants=(
            "fields 的键恰好是该档案 required_fields 的全部名字，不多不少",
            "source.source_locator 里不能有 '...' 占位（端侧与后端都拦这一条）",
        ),
    ),
    "workflow_event": Contract(
        name="workflow_event",
        purpose="账本事件的一行：后端是 workflow_events 表的一行，端侧是 ledger.jsonl 的一行",
        python_producer="database/ledger.py::record_event",
        python_consumer="database/ledger.py::recent_events",
        fields={"event_type": "str", "created_at": "str", "payload": "str"},
        arkts_sites=(
            ArktsSite(
                locator="entry/src/main/ets/common/LocalLedger.ets::appendEvent",
                role="producer",
                markers=("event_type", "created_at", "payload"),
            ),
            ArktsSite(
                locator="entry/src/main/ets/common/LocalLedger.ets::readEvents",
                role="consumer",
                markers=("event_type", "created_at", "payload"),
            ),
        ),
        invariants=(
            "两张账本表都带 project_id，且读取一律按 project_id 过滤",
            "created_at 是秒级 UTC，偏移写成 +00:00（两端同格式，别用 Z）",
        ),
    ),
    "experiment_manifest": Contract(
        name="experiment_manifest",
        purpose="实验开跑前落盘的计划：实验手册（experiments/manifests/EXP-*.json）",
        python_producer="schemas/experiment.py::ExperimentManifest",
        python_consumer="app/experiment_service.py::ExperimentService.run",
        fields={
            "experiment_id": "str",
            "hypothesis": "str",
            "config_path": "str",
            "config_sha256": "str",
            "parent_id": "any",
            "change_type": "str",
            "data_version": "str",
            "seed": "any",
            "command": "str",
            "git": "dict",
            "environment": "dict",
            "config": "dict",
            "expected_improvement": "any",
            "estimated_gpu_hours": "any",
            "rollback_plan": "any",
            "created_at": "str",
            "status": "str",
        },
        arkts_sites=(
            ArktsSite(
                locator="entry/src/main/ets/common/LocalStatus.ets::readExperimentStatuses",
                role="consumer",
                markers=(
                    "experiment_id",
                    "hypothesis",
                    "change_type",
                    "data_version",
                    "created_at",
                    "status",
                ),
            ),
        ),
    ),
    "experiment_result": Contract(
        name="experiment_result",
        purpose="实验跑完后的结果：experiments/results/EXP-*.json",
        python_producer="schemas/experiment.py::ExperimentResult",
        python_consumer="app/experiment_service.py::ExperimentService.run",
        fields={
            "experiment_id": "str",
            "status": "str",
            "started_at": "str",
            "finished_at": "str",
            "best_epoch": "any",
            "validation_metric": "any",
            "metrics": "dict",
            "runtime_seconds": "float",
            "peak_gpu_memory_gb": "any",
            "diagnosis": "dict",
            "conclusion": "str",
            "decision": "str",
            "next_candidates": "list",
            "artifact_paths": "list",
            "tracker_backend": "any",
            "error": "any",
        },
        arkts_sites=(
            ArktsSite(
                locator="entry/src/main/ets/common/LocalStatus.ets::readExperimentStatuses",
                role="consumer",
                markers=("validation_metric", "status", "experiment_id"),
            ),
        ),
    ),
    "evidence_claim": Contract(
        name="evidence_claim",
        purpose="论文证据图里的一条声明（paper/generated/evidence_map.json 的 claims 项）",
        python_producer="paper/generator.py::generate_paper_package",
        python_consumer="app/trace_service.py::_paper_chain",
        fields={"claim": "str", "experiment_id": "str", "result_path": "str"},
        invariants=(
            "claims 只能由跑完的实验生成；没有实验就必须是空列表，不许编一条出来",
        ),
    ),
    "project_manifest": Contract(
        name="project_manifest",
        purpose="项目注册表：workspace/projects.json",
        python_producer="app/project_registry.py::create_project",
        python_consumer="app/project_registry.py::load_registry",
        fields={
            "version": "int",
            "current": "any",
            "projects": "list",
            f"projects.{WILDCARD}": "dict",
            f"projects.{WILDCARD}.id": "str",
            f"projects.{WILDCARD}.name": "str",
            f"projects.{WILDCARD}.created_at": "str",
        },
        invariants=(
            "项目 id 就是工作区目录名（workspace/<id>），账本的 project_id 也是它",
        ),
    ),
}


def resolve(payload: object, path: str) -> list[object]:
    """按点分路径从真实产出里取值。

    路径里可以有一段 `*`：`fields.*.anchor` 表示"fields 下每一个值的 anchor"。
    路径不存在时返回空列表（由调用方判断"该有却没有"），不抛异常。
    """
    parts: list[str] = path.split(".")
    current: list[object] = [payload]
    for part in parts:
        following: list[object] = []
        for item in current:
            if part == WILDCARD:
                if isinstance(item, list):
                    following.extend(item)
                elif isinstance(item, dict):
                    following.extend(item.values())
            elif isinstance(item, dict) and part in item:
                following.append(item[part])
        current = following
        if not current:
            return []
    return current


def type_matches(type_name: str, value: object) -> bool:
    """按 `TYPE_CHECKS` 判定一个值是否符合声明的类型。"""
    if type_name == "str":
        return isinstance(value, str)
    if type_name == "bool":
        return isinstance(value, bool)
    if type_name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "dict":
        return isinstance(value, dict)
    if type_name == "list":
        return isinstance(value, list)
    if type_name == "any":
        return True
    raise ValueError(f"Unknown contract type: {type_name}")

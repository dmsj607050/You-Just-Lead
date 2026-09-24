"""The authorization gateway: the only route from a proposal to real work.

Policies are evaluated in order and the first one with an opinion decides, so
the order below is the order of the checks this system has always applied.  The
agent produces proposals; it cannot reach a skill without passing through here.

Extracted from ``ExperimentService._require_real_training_preflight`` without
changing which runs are blocked or why.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from agents.data_agent import dataset_inventory_sha256
from agents.rules_agent import rule_confirmation_readiness
from app.approval_service import verify_training_config_approval
from schemas.action import COSTLY, LOW, TRAINING_RUN, ActionRequest
from tools.configuration import DATA_PATH_KEYS, get_mapping, load_yaml
from tools.files import read_json


ALLOW = "allow"
DENY = "deny"
REQUIRE_HUMAN_APPROVAL = "require_human_approval"
NO_OPINION = "no_opinion"

SYNTHETIC_RUNNER = "synthetic_binary_classification"
PRETRAINED_ABSENT = (None, False, "", "none", "None")


@dataclass(frozen=True)
class PolicyVerdict:
    outcome: str
    policy: str
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.outcome == ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "policy": self.policy, "reason": self.reason}


class PolicyContext:
    """Lazy, read-only view of the workspace facts a policy may inspect.

    Facts load on first access, so a denial never triggers the expensive data
    fingerprint scan.
    """

    def __init__(self, workspace: Path, request: ActionRequest):
        self.workspace = workspace
        self.request = request
        self._spec: dict[str, Any] | None = None
        self._readiness: dict[str, Any] | None = None
        self._audit: dict[str, Any] | None = None
        self._audit_loaded = False

    @property
    def spec_path(self) -> Path:
        return self.workspace / "competition_spec.yaml"

    @property
    def spec(self) -> dict[str, Any]:
        if self._spec is None:
            self._spec = load_yaml(self.spec_path) if self.spec_path.exists() else {}
        return self._spec

    @property
    def readiness(self) -> dict[str, Any]:
        if self._readiness is None:
            self._readiness = rule_confirmation_readiness(self.spec)
        return self._readiness

    @property
    def audit(self) -> dict[str, Any] | None:
        if not self._audit_loaded:
            path = self.workspace / "reports" / "data_statistics.json"
            self._audit = read_json(path) if path.exists() else None
            self._audit_loaded = True
        return self._audit

    @property
    def audited_data_dir(self) -> str | None:
        audit = self.audit
        value = audit.get("data_dir") if audit else None
        return str(value) if value else None

    @property
    def audited_inventory(self) -> str | None:
        audit = self.audit
        value = audit.get("inventory_sha256") if audit else None
        return str(value) if value else None

    @property
    def runner(self) -> str:
        return str(self.request.parameters.get("runner", ""))

    @property
    def device(self) -> str:
        return str(self.request.parameters.get("device", "cpu"))

    @property
    def config_path(self) -> Path:
        return Path(str(self.request.parameters.get("config_path", "")))

    def declared_data_inputs(self) -> list[tuple[str, str]]:
        data = self.request.parameters.get("data") or {}
        return [(key, str(data[key])) for key in DATA_PATH_KEYS if data.get(key)]


class Policy(Protocol):
    name: str
    short_circuit: bool

    def evaluate(self, context: PolicyContext) -> PolicyVerdict: ...


class SyntheticSmokeTestPolicy:
    """The infrastructure smoke test never touches real competition data."""

    name = "synthetic_smoke_test"
    short_circuit = True

    def evaluate(self, context: PolicyContext) -> PolicyVerdict:
        if context.runner == SYNTHETIC_RUNNER:
            return PolicyVerdict(ALLOW, self.name, "Infrastructure smoke test runs without real data.")
        return PolicyVerdict(NO_OPINION, self.name)


class RuleSpecificationPolicy:
    """Official rules must carry a complete, human-confirmed specification."""

    name = "rule_specification"
    short_circuit = False

    def evaluate(self, context: PolicyContext) -> PolicyVerdict:
        if not context.spec_path.exists():
            return PolicyVerdict(
                DENY, self.name, "Real training requires competition_spec.yaml. Analyze official rules first."
            )
        spec = context.spec
        readiness = context.readiness
        if spec.get("approval", {}).get("requires_human_confirmation", True) or not readiness["ready"]:
            details = "; ".join(item["field"] for item in readiness["gaps"][:4])
            return PolicyVerdict(
                DENY,
                self.name,
                "Real training is blocked until official rules receive complete human confirmation"
                + (f" (missing: {details})." if details else "."),
            )
        return PolicyVerdict(ALLOW, self.name)


class PretrainedModelPolicy:
    """Pretrained weights require an explicit allowance in the official rules."""

    name = "pretrained_model_weights"
    short_circuit = False

    def evaluate(self, context: PolicyContext) -> PolicyVerdict:
        model = context.request.parameters.get("model") or {}
        reference = model.get("encoder_weights") or model.get("pretrained_model")
        if reference in PRETRAINED_ABSENT:
            return PolicyVerdict(ALLOW, self.name)
        if context.spec.get("constraints", {}).get("pretrained_models_allowed") is not True:
            return PolicyVerdict(
                DENY,
                self.name,
                "This configuration requests pretrained model weights, but the official rules "
                "do not explicitly permit them. Confirm the source and set "
                "constraints.pretrained_models_allowed to true before training.",
            )
        return PolicyVerdict(ALLOW, self.name)


class DataAuditPresencePolicy:
    """A deterministic audit with a content fingerprint must exist."""

    name = "data_audit_presence"
    short_circuit = False

    def evaluate(self, context: PolicyContext) -> PolicyVerdict:
        if context.audit is None:
            return PolicyVerdict(
                DENY, self.name, "Real training is blocked until the deterministic data audit is complete."
            )
        if not context.audited_data_dir or not context.audited_inventory:
            return PolicyVerdict(
                DENY, self.name, "The data audit does not contain a content fingerprint. Re-run audit-data."
            )
        return PolicyVerdict(ALLOW, self.name)


class DataFingerprintPolicy:
    """Raw data that changed after its audit invalidates the audit."""

    name = "data_fingerprint"
    short_circuit = False

    def evaluate(self, context: PolicyContext) -> PolicyVerdict:
        try:
            current = dataset_inventory_sha256(Path(str(context.audited_data_dir)))
        except OSError:
            return PolicyVerdict(
                DENY, self.name, "The audited data directory can no longer be read. Re-run audit-data."
            )
        if current != context.audited_inventory:
            return PolicyVerdict(
                DENY, self.name, "Raw data changed after its audit. Re-run audit-data before training."
            )
        return PolicyVerdict(ALLOW, self.name)


class AuditedInputScopePolicy:
    """Every declared input must be a real file inside the audited directory."""

    name = "audited_input_scope"
    short_circuit = False

    def evaluate(self, context: PolicyContext) -> PolicyVerdict:
        inputs = context.declared_data_inputs()
        if not inputs:
            return PolicyVerdict(
                DENY,
                self.name,
                "Real training requires declared data input paths inside the audited directory.",
            )
        audited_root = Path(str(context.audited_data_dir)).resolve()
        for key, value in inputs:
            candidate = Path(value).expanduser().resolve()
            if not candidate.exists():
                return PolicyVerdict(DENY, self.name, f"Configured data input does not exist: {key}={candidate}")
            if not candidate.is_relative_to(audited_root):
                return PolicyVerdict(
                    DENY,
                    self.name,
                    f"Configured data input is outside the audited directory: {key}={candidate}",
                )
        return PolicyVerdict(ALLOW, self.name)


class BudgetApprovalPolicy:
    """GPU work needs a human approval bound to this exact configuration."""

    name = "budget_approval"
    short_circuit = False

    def evaluate(self, context: PolicyContext) -> PolicyVerdict:
        if not context.device.startswith("cuda"):
            return PolicyVerdict(ALLOW, self.name)
        try:
            verify_training_config_approval(context.workspace, context.config_path)
        except PermissionError as exc:
            return PolicyVerdict(REQUIRE_HUMAN_APPROVAL, self.name, str(exc))
        return PolicyVerdict(ALLOW, self.name)


TRAINING_POLICIES: tuple[Policy, ...] = (
    SyntheticSmokeTestPolicy(),
    RuleSpecificationPolicy(),
    PretrainedModelPolicy(),
    DataAuditPresencePolicy(),
    DataFingerprintPolicy(),
    AuditedInputScopePolicy(),
    BudgetApprovalPolicy(),
)


def evaluate(
    context: PolicyContext,
    policies: tuple[Policy, ...] = TRAINING_POLICIES,
) -> PolicyVerdict:
    """Return the first verdict that has an opinion about this proposal."""
    for policy in policies:
        verdict = policy.evaluate(context)
        if verdict.outcome in (DENY, REQUIRE_HUMAN_APPROVAL):
            return verdict
        if verdict.outcome == ALLOW and policy.short_circuit:
            return verdict
    return PolicyVerdict(ALLOW, "none", "Every policy allowed this action.")


def authorise(
    request: ActionRequest,
    workspace: Path,
    policies: tuple[Policy, ...] = TRAINING_POLICIES,
) -> PolicyVerdict:
    """Raise PermissionError unless a policy allows the proposal as submitted."""
    verdict = evaluate(PolicyContext(workspace, request), policies)
    if not verdict.allowed:
        raise PermissionError(verdict.reason)
    return verdict


def training_run_request(
    config: dict[str, Any],
    config_path: Path,
    *,
    requested_by: str = "human:cli",
) -> ActionRequest:
    """Describe a training run as a content-bound proposal."""
    parameters: dict[str, Any] = {
        "runner": str(get_mapping(config, "training").get("runner", "")),
        "device": str(get_mapping(config, "training").get("device", "cpu")),
        "model": get_mapping(config, "model"),
        "data": get_mapping(config, "data"),
        "config_path": str(config_path.resolve()),
    }
    digest = hashlib.sha256(
        json.dumps(parameters, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return ActionRequest(
        action_id=f"ACT-{digest[:12]}",
        kind=TRAINING_RUN,
        skill=TRAINING_RUN,
        parameters=parameters,
        content_sha256=digest,
        risk=COSTLY if parameters["device"].startswith("cuda") else LOW,
        rationale="Run one frozen configuration and record every observable outcome.",
        requested_by=requested_by,
    )

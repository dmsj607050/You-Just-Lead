"""Tests for the DeepSeek Agent tool-calling loop and the agent_tools layer.

All DeepSeek network calls are mocked so the tests run offline and do not spend
API credits.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent_tools import (
    agent_tools_schema,
    available_tool_names,
    execute_tool,
)
from app.deepseek_service import DeepSeekError, run_agent
from tools.files import write_json_atomic


HIGH_RISK_TOOL_NAMES = {"run_training", "start_training", "submit", "delete", "download", "reproduce", "approve_run"}


def _message(content: str | None = None, tool_calls=None, reasoning: str | None = None) -> dict:
    message: dict = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return message


def _tool_call(call_id: str, name: str, arguments: dict | str) -> dict:
    raw_args = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": raw_args}}


def _response(message: dict) -> dict:
    return {"choices": [{"message": message}]}


class AgentToolsSchemaTests(unittest.TestCase):
    def test_schema_returns_one_entry_per_registered_tool(self) -> None:
        schema = agent_tools_schema()
        schema_names = {entry["function"]["name"] for entry in schema}
        handler_names = set(available_tool_names())
        self.assertEqual(schema_names, handler_names)
        self.assertGreaterEqual(len(schema_names), 10)

    def test_every_tool_has_required_schema_fields(self) -> None:
        for entry in agent_tools_schema():
            self.assertEqual(entry["type"], "function")
            function = entry["function"]
            self.assertIn("name", function)
            self.assertIn("description", function)
            self.assertIn("parameters", function)
            self.assertEqual(function["parameters"]["type"], "object")
            self.assertIn("required", function["parameters"])

    def test_no_high_risk_tool_is_exposed(self) -> None:
        names = set(available_tool_names())
        forbidden = names & HIGH_RISK_TOOL_NAMES
        self.assertFalse(forbidden, f"High-risk tools must not be exposed to the Agent: {forbidden}")

    def test_create_experiment_draft_is_the_only_write_tool(self) -> None:
        write_tools = {name for name in available_tool_names() if "create" in name or "write" in name}
        self.assertEqual(write_tools, {"create_experiment_draft"})


class AgentToolExecutionTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        workspace = root / "workspace" / "current_competition"
        for sub in ("experiments/manifests", "experiments/results", "experiments/drafts", "experiments/approvals", "reports", "research"):
            (workspace / sub).mkdir(parents=True, exist_ok=True)
        (root / "database").mkdir(parents=True, exist_ok=True)
        return workspace

    def test_list_experiments_returns_empty_when_no_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            outcome = execute_tool(root, workspace, "list_experiments", {})
            self.assertEqual(outcome, {"experiments": [], "total": 0})

    def test_list_experiments_returns_recorded_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            write_json_atomic(workspace / "experiments" / "results" / "EXP-0001.json", {
                "experiment_id": "EXP-0001",
                "status": "completed",
                "validation_metric": 0.91,
                "decision": "keep",
            })
            outcome = execute_tool(root, workspace, "list_experiments", {})
            self.assertEqual(outcome["total"], 1)
            self.assertEqual(outcome["experiments"][0]["experiment_id"], "EXP-0001")

    def test_get_experiment_returns_full_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            write_json_atomic(workspace / "experiments" / "results" / "EXP-0001.json", {
                "experiment_id": "EXP-0001",
                "status": "completed",
                "validation_metric": 0.88,
                "best_epoch": 5,
                "decision": "keep",
                "diagnosis": {"overfitting": False},
            })
            outcome = execute_tool(root, workspace, "get_experiment", {"experiment_id": "EXP-0001"})
            self.assertEqual(outcome["experiment_id"], "EXP-0001")
            self.assertEqual(outcome["best_epoch"], 5)

    def test_get_experiment_returns_error_for_missing_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            outcome = execute_tool(root, workspace, "get_experiment", {"experiment_id": "EXP-9999"})
            self.assertIn("error", outcome)

    def test_get_workflow_state_returns_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            outcome = execute_tool(root, workspace, "get_workflow_state", {})
            self.assertIn("stage", outcome)
            self.assertIn("components", outcome)
            self.assertFalse(outcome["automatic_execution"])

    def test_get_data_audit_returns_error_when_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            outcome = execute_tool(root, workspace, "get_data_audit", {})
            self.assertIn("error", outcome)

    def test_get_best_run_returns_error_without_completed_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            outcome = execute_tool(root, workspace, "get_best_run", {})
            self.assertIn("error", outcome)

    def test_create_experiment_draft_persists_file_and_returns_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            outcome = execute_tool(root, workspace, "create_experiment_draft", {
                "hypothesis": "Increasing dropout from 0.1 to 0.3 reduces overfitting on the small validation set.",
            })
            self.assertEqual(outcome["status"], "awaiting_human_approval")
            self.assertTrue(outcome["draft_id"].startswith("DRAFT-"))
            draft_file = workspace / "experiments" / "drafts" / f"{outcome['draft_id']}.json"
            self.assertTrue(draft_file.exists())

    def test_create_experiment_draft_rejects_short_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            outcome = execute_tool(root, workspace, "create_experiment_draft", {"hypothesis": "short"})
            self.assertIn("error", outcome)

    def test_execute_tool_returns_error_for_unknown_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            outcome = execute_tool(root, workspace, "run_training", {})
            self.assertIn("error", outcome)


class RunAgentLoopTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        workspace = root / "workspace" / "current_competition"
        for sub in ("experiments/manifests", "experiments/results", "experiments/drafts", "experiments/approvals", "reports", "research"):
            (workspace / sub).mkdir(parents=True, exist_ok=True)
        (root / "database").mkdir(parents=True, exist_ok=True)
        return workspace

    def _patch_settings(self):
        return patch(
            "app.deepseek_service.deepseek_settings_status",
            return_value={
                "configured": True,
                "key_source": "environment",
                "model": "deepseek-v4-pro",
                "supported_models": ["deepseek-v4-flash", "deepseek-v4-pro"],
                "secure_storage_available": True,
            },
        )

    def _patch_key(self):
        return patch("app.deepseek_service.get_deepseek_api_key", return_value=("sk-test-key", "environment"))

    def test_single_turn_returns_final_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            responses = [_response(_message(content="当前工作流处于 rules_capture 阶段，建议先运行 rules 命令。"))]
            with self._patch_settings(), self._patch_key(), patch("app.deepseek_service._request", side_effect=responses):
                outcome = run_agent("当前项目处于什么阶段？", "rules_capture", root, workspace, thinking=False)
            self.assertEqual(outcome["content"], "当前工作流处于 rules_capture 阶段，建议先运行 rules 命令。")
            self.assertEqual(outcome["turns"], 1)
            self.assertFalse(outcome.get("truncated", False))
            self.assertEqual(len(outcome["trace"]), 1)
            self.assertEqual(outcome["trace"][0]["type"], "final")

    def test_multi_turn_executes_tool_then_answers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            write_json_atomic(workspace / "experiments" / "results" / "EXP-0001.json", {
                "experiment_id": "EXP-0001",
                "status": "completed",
                "validation_metric": 0.91,
                "decision": "keep",
            })
            responses = [
                _response(_message(
                    content="我先查看实验记录。",
                    tool_calls=[_tool_call("call_1", "list_experiments", {})],
                )),
                _response(_message(content="当前共有 1 个已完成实验 EXP-0001，验证指标 0.91，建议下一步尝试提升鲁棒性。")),
            ]
            with self._patch_settings(), self._patch_key(), patch("app.deepseek_service._request", side_effect=responses):
                outcome = run_agent("总结当前实验进度", "evidence_led_iteration", root, workspace, thinking=False)
            self.assertEqual(outcome["turns"], 2)
            self.assertEqual(len(outcome["trace"]), 2)
            self.assertEqual(outcome["trace"][0]["type"], "tool_calls")
            self.assertEqual(outcome["trace"][0]["tool_calls"][0]["name"], "list_experiments")
            self.assertEqual(outcome["trace"][1]["type"], "final")
            self.assertIn("EXP-0001", outcome["content"])

    def test_multiple_tool_calls_in_one_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            responses = [
                _response(_message(
                    content="同时拉取工作流和实验列表。",
                    tool_calls=[
                        _tool_call("call_1", "get_workflow_state", {}),
                        _tool_call("call_2", "list_experiments", {}),
                    ],
                )),
                _response(_message(content="已收集工作流和实验数据，当前没有完成实验，建议先建立基线。")),
            ]
            with self._patch_settings(), self._patch_key(), patch("app.deepseek_service._request", side_effect=responses):
                outcome = run_agent("给我一份状态摘要", "baseline_design", root, workspace, thinking=False)
            self.assertEqual(outcome["turns"], 2)
            self.assertEqual(len(outcome["trace"][0]["tool_calls"]), 2)
            self.assertEqual(outcome["trace"][0]["tool_calls"][0]["name"], "get_workflow_state")
            self.assertEqual(outcome["trace"][0]["tool_calls"][1]["name"], "list_experiments")

    def test_max_turns_truncation_is_graceful(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            loop_response = _response(_message(
                content="继续调查。",
                tool_calls=[_tool_call("call_loop", "list_experiments", {})],
            ))
            final_response = _response(_message(content="已达轮数上限，基于已有信息无法给出更多结论。"))
            responses = [loop_response, loop_response, final_response]
            with self._patch_settings(), self._patch_key(), patch("app.deepseek_service._request", side_effect=responses):
                outcome = run_agent("反复调查", "evidence_led_iteration", root, workspace, max_turns=2, thinking=False)
            self.assertTrue(outcome["truncated"])
            self.assertEqual(outcome["turns"], 2)
            self.assertEqual(outcome["trace"][-1]["type"], "max_turns_summary")

    def test_invalid_prompt_length_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            with self._patch_settings(), self._patch_key():
                with self.assertRaises(DeepSeekError):
                    run_agent("", "stage", root, workspace)
                with self.assertRaises(DeepSeekError):
                    run_agent("x" * 8001, "stage", root, workspace)

    def test_tool_arguments_as_dict_are_handled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            write_json_atomic(workspace / "experiments" / "results" / "EXP-0001.json", {
                "experiment_id": "EXP-0001",
                "status": "completed",
                "validation_metric": 0.9,
            })
            responses = [
                _response(_message(
                    content="查看 EXP-0001 详情。",
                    tool_calls=[_tool_call("call_1", "get_experiment", {"experiment_id": "EXP-0001"})],
                )),
                _response(_message(content="EXP-0001 已完成，指标 0.9。")),
            ]
            with self._patch_settings(), self._patch_key(), patch("app.deepseek_service._request", side_effect=responses):
                outcome = run_agent("看下 EXP-0001", "evidence_led_iteration", root, workspace, thinking=False)
            self.assertEqual(outcome["trace"][0]["tool_calls"][0]["result"]["experiment_id"], "EXP-0001")

    def test_trace_preserves_reasoning_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            responses = [
                _response(_message(
                    content="先列实验。",
                    reasoning="用户问进度，需要先看实验列表。",
                    tool_calls=[_tool_call("call_1", "list_experiments", {})],
                )),
                _response(_message(content="没有实验。", reasoning="列表为空。")),
            ]
            with self._patch_settings(), self._patch_key(), patch("app.deepseek_service._request", side_effect=responses):
                outcome = run_agent("进度如何", "baseline_design", root, workspace, thinking=False)
            self.assertEqual(outcome["trace"][0]["reasoning"], "用户问进度，需要先看实验列表。")
            self.assertEqual(outcome["trace"][1]["reasoning"], "列表为空。")


if __name__ == "__main__":
    unittest.main()

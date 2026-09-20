"""Tests for local rule extraction and data-audit artefacts."""

from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from agents.data_agent import audit_dataset
from agents.rules_agent import (
    apply_official_rule_evidence,
    analyze_rules,
    approve_rule_specification,
    rule_confirmation_readiness,
    RuleImportError,
    import_rule_source,
)
from tools.configuration import load_yaml
from tools.files import read_json


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLq6QAAAABJRU5ErkJggg=="
)


class RulesAndDataAgentTests(unittest.TestCase):
    def test_xunfei_evidence_record_is_complete_but_not_an_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            spec_path = workspace / "competition_spec.yaml"
            from tools.configuration import write_yaml

            write_yaml(
                spec_path,
                {
                    "competition": {"preferred_runner": "waterseg_external"},
                    "submission": {"validation_profile": "xunfei_waterseg_inference_package"},
                    "approval": {"requires_human_confirmation": True, "unresolved_questions": ["review rules"]},
                },
            )
            values = {
                "competition.name": "Water Cup",
                "competition.platform": "iFLYTEK",
                "competition.task_type": "image_segmentation",
                "competition.deadline": "2026-08-27 23:59 Asia/Shanghai",
                "evaluation.primary_metric": "global_water_iou",
                "evaluation.direction": "maximize",
                "submission.format": "tar.gz inference package",
                "submission.filename_rule": "<input_stem>_mask.png",
                "submission.daily_limit": 3,
                "constraints.model_size_limit_mb": 600,
                "submission.contract.package_layout": "one top-level directory containing run.py and model/",
                "submission.contract.required_files": ["run.py", "model/model.ts", "model/config.json"],
                "submission.contract.mask_size": [1024, 1024],
                "submission.contract.mask_filename_suffix": "_mask",
                "submission.contract.runtime_output": "loose_png",
                "constraints.external_data_allowed": False,
                "constraints.pretrained_models_allowed": True,
                "constraints.ensemble_allowed": False,
                "constraints.inference_limit_evidence": "Official rules page: limit not separately published.",
            }
            evidence_path = workspace / "docs" / "rule_evidence.yaml"
            write_yaml(
                evidence_path,
                {
                    "source": {
                        "source_type": "authenticated_rule_page",
                        "source_locator": "https://challenge.example.test/water/rules",
                        "reviewed_at": "2026-07-17T00:00:00+08:00",
                    },
                    "fields": {key: {"value": value, "anchor": f"Rules section for {key}"} for key, value in values.items()},
                },
            )

            outcome = apply_official_rule_evidence(workspace, evidence_path)
            applied = load_yaml(spec_path)

            self.assertTrue(outcome["readiness"]["ready"])
            self.assertTrue(applied["approval"]["requires_human_confirmation"])
            self.assertEqual(applied["approval"]["unresolved_questions"], [])
            self.assertTrue(rule_confirmation_readiness(applied)["ready"])

    def test_rules_agent_creates_reviewable_specification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            source = workspace / "input" / "official_rules.md"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(
                    [
                        "Competition name: Demo Vision Cup",
                        "Platform: Kaggle",
                        "Task type: image classification",
                        "Metric: accuracy",
                        "Metric direction: maximize",
                        "Submission format: csv",
                        "External data: prohibited",
                        "Pretrained: allowed",
                        "Ensemble: not allowed",
                    ]
                ),
                encoding="utf-8",
            )

            outcome = analyze_rules(source, workspace)
            spec = load_yaml(workspace / "competition_spec.yaml")

            self.assertEqual(spec["competition"]["name"], "Demo Vision Cup")
            self.assertEqual(spec["evaluation"]["primary_metric"], "accuracy")
            self.assertFalse(spec["constraints"]["external_data_allowed"])
            self.assertFalse(spec["approval"]["requires_human_confirmation"])
            self.assertEqual(outcome["evidence_count"], 9)
            self.assertTrue((workspace / "docs" / "competition_rules.md").exists())
            self.assertTrue((workspace / "docs" / "submission_checklist.md").exists())
            approval = approve_rule_specification(workspace, "Reviewed against the official document.")
            self.assertTrue(approval["approved"])
            self.assertFalse(load_yaml(workspace / "competition_spec.yaml")["approval"]["requires_human_confirmation"])

    def test_imported_rule_file_is_stored_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            source_text = "\n".join(
                [
                    "Competition name: Imported Vision Cup",
                    "Platform: Kaggle",
                    "Task type: image classification",
                    "Metric: accuracy",
                    "Metric direction: maximize",
                    "Submission format: csv",
                    "External data: prohibited",
                    "Pretrained: allowed",
                    "Ensemble: not allowed",
                ]
            )
            outcome = import_rule_source(
                workspace,
                filename="official_rules.md",
                content_base64=base64.b64encode(source_text.encode("utf-8")).decode("ascii"),
            )

            self.assertEqual(outcome["source"]["kind"], "file")
            self.assertTrue(Path(outcome["source"]["path"]).exists())
            self.assertEqual(outcome["spec"]["competition"]["name"], "Imported Vision Cup")
            self.assertEqual(outcome["analysis"]["evidence_count"], 9)
            self.assertIn("Imported Vision Cup", outcome["report_markdown"])

    def test_import_rejects_image_without_ocr_and_private_rule_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            with self.assertRaises(RuleImportError):
                import_rule_source(
                    workspace,
                    filename="rule.png",
                    content_base64=base64.b64encode(PNG_1X1).decode("ascii"),
                )
            with self.assertRaises(RuleImportError):
                import_rule_source(workspace, source_url="http://127.0.0.1/rules")
    def test_data_audit_detects_duplicates_missing_values_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            raw = workspace / "data" / "raw"
            (raw / "train").mkdir(parents=True)
            (raw / "test").mkdir()
            (raw / "train" / "one.png").write_bytes(PNG_1X1)
            (raw / "test" / "same.png").write_bytes(PNG_1X1)
            (raw / "train" / "labels.csv").write_text(
                "id,label\n1,cat\n2,\n", encoding="utf-8"
            )
            (raw / "train" / "empty.bin").write_bytes(b"")

            stats = audit_dataset(workspace)
            persisted = read_json(workspace / "reports" / "data_statistics.json")

            self.assertEqual(stats["file_count"], 4)
            self.assertEqual(len(persisted["inventory_sha256"]), 64)
            self.assertEqual(persisted["images"]["count"], 2)
            self.assertEqual(len(persisted["exact_duplicate_groups"]), 1)
            self.assertGreaterEqual(persisted["issue_count"], 2)
            self.assertTrue((workspace / "data" / "metadata.jsonl").exists())
            self.assertTrue((workspace / "reports" / "data_quality_issues.csv").exists())
            self.assertTrue((workspace / "reports" / "figures" / "data_overview.svg").exists())

    def test_data_audit_profiles_segmentation_masks(self) -> None:
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest("Pillow is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            masks = workspace / "data" / "raw" / "train" / "masks"
            masks.mkdir(parents=True)
            empty = Image.new("L", (10, 10), color=0)
            foreground = Image.new("L", (10, 10), color=0)
            ImageDraw.Draw(foreground).rectangle((0, 0, 4, 4), fill=255)
            empty.save(masks / "empty.png")
            foreground.save(masks / "foreground.png")

            stats = audit_dataset(workspace)

            self.assertEqual(stats["segmentation_masks"]["count"], 2)
            self.assertEqual(stats["segmentation_masks"]["empty_count"], 1)
            self.assertGreater(stats["segmentation_masks"]["foreground_ratio"]["mean"], 0)


if __name__ == "__main__":
    unittest.main()

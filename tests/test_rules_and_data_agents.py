"""Tests for local rule extraction and data-audit artefacts."""

from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from agents.data_agent import audit_dataset
from agents.rules_agent import analyze_rules, approve_rule_specification
from tools.configuration import load_yaml
from tools.files import read_json


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLq6QAAAABJRU5ErkJggg=="
)


class RulesAndDataAgentTests(unittest.TestCase):
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

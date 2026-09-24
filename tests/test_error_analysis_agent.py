"""Tests for deterministic per-sample validation error summaries."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.error_analysis_agent import analyze_prediction_errors
from tools.files import read_json


class ErrorAnalysisAgentTests(unittest.TestCase):
    def test_summarizes_confusion_and_high_confidence_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "validation_predictions.jsonl"
            source.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in (
                        {"path": "a.png", "true_label": "river", "predicted_label": "river", "confidence": 0.9},
                        {"path": "b.png", "true_label": "river", "predicted_label": "road", "confidence": 0.95},
                        {"path": "c.png", "true_label": "road", "predicted_label": "road", "confidence": 0.8},
                        {"path": "d.png", "true_label": "road", "predicted_label": "road", "confidence": 0.7},
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            summary = analyze_prediction_errors(source, root / "analysis")

            persisted = read_json(root / "analysis" / "error_analysis.json")
            self.assertEqual(summary["samples"], 4)
            self.assertEqual(summary["high_confidence_error_count"], 1)
            self.assertEqual(summary["confusion"]["river"]["road"], 1)
            self.assertEqual(persisted["worst_examples"][0]["path"], "b.png")
            self.assertTrue((root / "analysis" / "error_analysis.md").exists())

"""Generate a conservative TeX research report from recorded evidence only."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tools.configuration import load_yaml
from tools.experiment_scope import current_competition_results, manifests_by_id
from tools.files import read_json, write_json_atomic
from tools.provenance import utc_now


def _tex(value: Any) -> str:
    text = str(value if value is not None else "not recorded")
    return text.replace("\\", "\\textbackslash{}").replace("&", "\\&").replace("%", "\\%").replace("_", "\\_").replace("#", "\\#").replace("{", "\\{").replace("}", "\\}")


def _records(directory: Path) -> list[dict[str, Any]]:
    return sorted((read_json(path) for path in directory.glob("EXP-*.json")), key=lambda item: item["experiment_id"])


def _citation_key(record: dict[str, Any], index: int) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "", str(record.get("title") or "reference"))[:18]
    return f"{normalized or 'reference'}{index}"


def _curated_bibliography(workspace: Path) -> tuple[str, list[str]]:
    """Prefer a reviewed BibTeX list over raw search hits when one is available."""
    candidates = sorted((workspace / "research").glob("*_references.bib"))
    if not candidates:
        return "", []
    content = candidates[0].read_text(encoding="utf-8")
    keys = re.findall(r"@\w+\s*\{\s*([^,\s]+)", content)
    return content.strip(), keys


def generate_paper_package(workspace: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """Build TeX, BibTeX and an evidence map without manufacturing claims."""
    output = output_dir or workspace.parent.parent / "paper" / "generated"
    output.mkdir(parents=True, exist_ok=True)
    spec = load_yaml(workspace / "competition_spec.yaml") if (workspace / "competition_spec.yaml").exists() else {}
    results = current_competition_results(workspace)
    manifests = manifests_by_id(workspace)
    data_stats = read_json(workspace / "reports" / "data_statistics.json") if (workspace / "reports" / "data_statistics.json").exists() else {}
    research_path = workspace / "research" / "papers.json"
    research = read_json(research_path).get("records", []) if research_path.exists() else []
    curated_bib, curated_keys = _curated_bibliography(workspace)
    completed = [result for result in results if result.get("status") == "completed" and result.get("validation_metric") is not None]
    direction = spec.get("evaluation", {}).get("direction", "maximize")
    best = (max if direction == "maximize" else min)(completed, key=lambda item: float(item["validation_metric"])) if completed else None

    title = spec.get("competition", {}).get("name") or "Competition research report"
    metric = spec.get("evaluation", {}).get("primary_metric") or "validation metric"
    tex_lines = [
        "\\documentclass[11pt]{ctexart}",
        "\\usepackage[margin=1in]{geometry}",
        "\\usepackage{booktabs}",
        "\\usepackage[hidelinks]{hyperref}",
        "\\title{" + _tex(title) + "}",
        "\\author{Competition Agent evidence workflow}",
        "\\date{" + utc_now()[:10] + "}",
        "\\begin{document}",
        "\\maketitle",
        "\\section{Scope and compliance}",
        "This report is generated only from persisted rule, data and experiment records. It does not claim unrecorded results.",
        "\\begin{itemize}",
        "\\item Task: " + _tex(spec.get("competition", {}).get("task_type")),
        "\\item Primary metric: " + _tex(metric) + " (" + _tex(direction) + ")",
        "\\item Rules require human confirmation: " + _tex(spec.get("approval", {}).get("requires_human_confirmation", True)),
        "\\end{itemize}",
        "\\section{Data audit}",
        "Audited files: " + _tex(data_stats.get("file_count")) + ". Quality issues: " + _tex(data_stats.get("issue_count")) + ". Exact duplicate groups: " + _tex(len(data_stats.get("exact_duplicate_groups", []))) + ".",
        "\\section{Experimental protocol and results}",
        "\\begin{center}\\begin{tabular}{llll}\\toprule",
        "Experiment & Status & " + _tex(metric) + " & Change type \\\\ \\midrule",
    ]
    evidence_claims: list[dict[str, Any]] = []
    for result in results:
        manifest = manifests.get(result["experiment_id"], {})
        tex_lines.append("{} & {} & {} & {} \\\\".format(_tex(result["experiment_id"]), _tex(result["status"]), _tex(result.get("validation_metric")), _tex(manifest.get("change_type"))))
        if result.get("status") == "completed":
            evidence_claims.append({"claim": f"{result['experiment_id']} completed with {metric}={result.get('validation_metric')}", "experiment_id": result["experiment_id"], "result_path": f"experiments/results/{result['experiment_id']}.json"})
    tex_lines.extend(["\\bottomrule\\end{tabular}\\end{center}"])
    if best:
        tex_lines.extend(["The best recorded validation result is " + _tex(best["experiment_id"]) + " with " + _tex(metric) + " = " + _tex(best["validation_metric"]) + "."])
    else:
        tex_lines.append("No completed validation result is recorded yet.")
    tex_lines.extend(["\\section{Limitations and next steps}", "All conclusions remain conditional on the official-rule confirmation, data-audit findings and held-out evaluation. The decision memo should be reviewed before the next run."])

    bib_lines: list[str] = []
    if curated_keys:
        tex_lines.append("\\section{Related work candidates}")
        tex_lines.append(
            "This initial report cites only the manually reviewed candidates. "
            "The full automated radar remains a separate evidence record."
        )
        tex_lines.append("\\cite{" + ",".join(curated_keys) + "}.")
        bib_lines.append(curated_bib)
    elif research:
        tex_lines.append("\\section{Related work candidates}")
        tex_lines.append("The following records were retrieved for review; inclusion here is not a claim of reproduction or endorsement.")
        for index, record in enumerate(research[:20], 1):
            key = _citation_key(record, index)
            tex_lines.append("\\cite{" + key + "} " + _tex(record.get("title")) + ".")
            authors = " and ".join(record.get("authors") or ["Unknown"])
            bib_lines.extend([f"@misc{{{key},", f"  title = {{{record.get('title', 'Untitled')}}},", f"  author = {{{authors}}},", f"  year = {{{record.get('year') or 'n.d.'}}},", f"  howpublished = {{\\url{{{record.get('url') or ''}}}}}", "}", ""])
    if bib_lines:
        tex_lines.extend(["\\bibliographystyle{plain}", "\\bibliography{references}"])
    tex_lines.append("\\end{document}")

    tex_path = output / "competition_report.tex"
    bib_path = output / "references.bib"
    evidence_path = output / "evidence_map.json"
    tex_path.write_text("\n".join(tex_lines) + "\n", encoding="utf-8")
    bib_path.write_text("\n".join(bib_lines) + "\n", encoding="utf-8")
    evidence = {"generated_at": utc_now(), "claims": evidence_claims, "data_statistics": "reports/data_statistics.json" if data_stats else None, "rule_specification": "competition_spec.yaml" if spec else None, "research_records": len(research)}
    write_json_atomic(evidence_path, evidence)
    return {"tex_path": str(tex_path), "bib_path": str(bib_path), "evidence_map": str(evidence_path), "claims": len(evidence_claims)}

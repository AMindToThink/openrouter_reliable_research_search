#!/usr/bin/env python3
"""Add the `provider_ab_rerun_assessment` column to the survey dataset.

The column records, per repo, whether we could empirically demonstrate provider-routing
corruption by rerunning *their own code* with nothing changed but a pinned OpenRouter
provider — and, for the viable ones, the strong/weak provider pair, cost and wall-clock.

Source of truth for the cell text is `findings/ab_assessments.json` (written by the
multi-agent evaluation). This script only joins it onto the existing dataset, so the
numbers in the CSV/JSON always come from the generated file, never hand-typed.

Usage:
    uv run scripts/add_ab_column.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FINDINGS = ROOT / "findings"
ASSESSMENTS = FINDINGS / "ab_assessments.json"
SURVEY_JSON = FINDINGS / "survey.json"
SURVEY_CSV = FINDINGS / "survey.csv"
ARTIFACT_DATA = ROOT / "artifact" / "_data.json"

COLUMN_KEY = "provider_ab_rerun_assessment"
COLUMN_HEADER = "Provider A/B rerun assessment"


def load_assessments() -> dict[str, str]:
    if not ASSESSMENTS.exists():
        raise SystemExit(f"missing {ASSESSMENTS} — run the evaluation workflow first")
    data = json.loads(ASSESSMENTS.read_text())
    cells = data["cells"] if isinstance(data, dict) and "cells" in data else data
    if not isinstance(cells, dict):
        raise SystemExit(f"{ASSESSMENTS} must map repo title -> assessment text")
    return cells


def apply_to_json(cells: dict[str, str]) -> list[dict[str, Any]]:
    survey = json.loads(SURVEY_JSON.read_text())
    rows = survey["rows"]

    missing = [r["title"] for r in rows if r["title"] not in cells]
    if missing:
        raise SystemExit(
            "no assessment for these repos (titles must match survey.json exactly):\n  "
            + "\n  ".join(missing)
        )
    extra = [t for t in cells if t not in {r["title"] for r in rows}]
    if extra:
        raise SystemExit("assessments reference unknown repos:\n  " + "\n  ".join(extra))

    for row in rows:
        row[COLUMN_KEY] = cells[row["title"]]

    SURVEY_JSON.write_text(json.dumps(survey, indent=1) + "\n")
    return rows


def apply_to_csv(cells: dict[str, str]) -> None:
    with SURVEY_CSV.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if COLUMN_HEADER not in fieldnames:
        fieldnames.append(COLUMN_HEADER)

    for row in rows:
        title = row["Title"]
        if title not in cells:
            raise SystemExit(f"no assessment for CSV row {title!r}")
        row[COLUMN_HEADER] = cells[title]

    with SURVEY_CSV.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def apply_to_artifact(rows: list[dict[str, Any]]) -> None:
    """Keep the interactive explorer's embedded data in sync, if it carries per-repo rows."""
    if not ARTIFACT_DATA.exists():
        return
    data = json.loads(ARTIFACT_DATA.read_text())
    by_title = {r["title"]: r[COLUMN_KEY] for r in rows}
    target = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(target, list):
        return
    touched = 0
    for row in target:
        if isinstance(row, dict) and row.get("title") in by_title:
            row[COLUMN_KEY] = by_title[row["title"]]
            touched += 1
    if touched:
        ARTIFACT_DATA.write_text(json.dumps(data, indent=1) + "\n")
    print(f"artifact/_data.json: updated {touched} rows")


def main() -> None:
    cells = load_assessments()
    rows = apply_to_json(cells)
    apply_to_csv(cells)
    apply_to_artifact(rows)
    print(f"added {COLUMN_KEY!r} to {len(rows)} rows in survey.json and survey.csv")


if __name__ == "__main__":
    main()

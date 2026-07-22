#!/usr/bin/env python3
"""Add the `provider_issue_fingerprints` column to the survey dataset.

The column records, per repo, what a *reader* could observe in that project's own published
output — figures, tables, appendix transcripts, released JSON/JSONL, leaderboard entries,
committed logs — that would raise or lower suspicion that provider routing actually corrupted
the result. It is deliberately separate from the audit columns: those say what the *code*
leaves open, this says what the *evidence* shows. Most cells are expected to say "nothing
checkable was released" — that is the finding, not a gap.

Cell text comes from `findings/fingerprint_assessments.json` (written by the multi-agent
evaluation). This script only joins it onto the existing dataset, so published cells always
come from the generated file and are never hand-typed.

Usage:
    uv run scripts/add_fingerprint_column.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FINDINGS = ROOT / "findings"
ASSESSMENTS = FINDINGS / "fingerprint_assessments.json"
SURVEY_JSON = FINDINGS / "survey.json"
SURVEY_CSV = FINDINGS / "survey.csv"
ARTIFACT_DATA = ROOT / "artifact" / "_data.json"

COLUMN_KEY = "provider_issue_fingerprints"
COLUMN_HEADER = "Signs provider issues messed up the paper"

# Parallel scalar columns, joined from the same file. Keeping the verdict machine-readable
# lets the artifact filter on it and lets tests check the prose and the verdict agree.
VERDICT_KEY = "fingerprint_verdict"
VERDICT_HEADER = "Fingerprint verdict"
IDS_KEY = "fingerprint_ids"
IDS_HEADER = "Fingerprint IDs"

VERDICTS = {
    # Something is visibly off in what they published.
    "fingerprints_found",
    # They released enough to look, and it looks clean.
    "checked_clean",
    # They released raw outputs, but the check is inconclusive either way.
    "inconclusive",
    # Aggregate-only publication: nothing a reader could check. The common case.
    "nothing_checkable_released",
}


def load_assessments() -> dict[str, dict[str, Any]]:
    if not ASSESSMENTS.exists():
        raise SystemExit(f"missing {ASSESSMENTS} — run the fingerprint workflow first")
    data = json.loads(ASSESSMENTS.read_text())
    cells = data["cells"] if isinstance(data, dict) and "cells" in data else data
    if not isinstance(cells, dict):
        raise SystemExit(f"{ASSESSMENTS} must map repo title -> assessment object")
    for title, cell in cells.items():
        if not isinstance(cell, dict):
            raise SystemExit(f"{title}: cell must be an object, got {type(cell).__name__}")
        for field in ("text", "verdict", "fingerprint_ids"):
            if field not in cell:
                raise SystemExit(f"{title}: cell is missing {field!r}")
        if cell["verdict"] not in VERDICTS:
            raise SystemExit(
                f"{title}: verdict {cell['verdict']!r} not one of {sorted(VERDICTS)}"
            )
        if not str(cell["text"]).strip():
            raise SystemExit(f"{title}: empty assessment text")
    return cells


def apply_to_json(cells: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    survey = json.loads(SURVEY_JSON.read_text())
    rows = survey["rows"]

    missing = [r["title"] for r in rows if r["title"] not in cells]
    if missing:
        raise SystemExit(
            "no fingerprint assessment for these repos (titles must match survey.json exactly):\n  "
            + "\n  ".join(missing)
        )
    extra = [t for t in cells if t not in {r["title"] for r in rows}]
    if extra:
        raise SystemExit("assessments reference unknown repos:\n  " + "\n  ".join(extra))

    for row in rows:
        cell = cells[row["title"]]
        row[COLUMN_KEY] = cell["text"]
        row[VERDICT_KEY] = cell["verdict"]
        row[IDS_KEY] = list(cell["fingerprint_ids"])

    SURVEY_JSON.write_text(json.dumps(survey, indent=2, ensure_ascii=False) + "\n")
    return rows


def apply_to_csv(cells: dict[str, dict[str, Any]]) -> None:
    with SURVEY_CSV.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for header in (COLUMN_HEADER, VERDICT_HEADER, IDS_HEADER):
        if header not in fieldnames:
            fieldnames.append(header)

    for row in rows:
        title = row["Title"]
        if title not in cells:
            raise SystemExit(f"no fingerprint assessment for CSV row {title!r}")
        cell = cells[title]
        row[COLUMN_HEADER] = cell["text"]
        row[VERDICT_HEADER] = cell["verdict"]
        row[IDS_HEADER] = ", ".join(cell["fingerprint_ids"])

    with SURVEY_CSV.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def apply_to_artifact(rows: list[dict[str, Any]]) -> None:
    """Keep the interactive explorer's embedded data in sync."""
    if not ARTIFACT_DATA.exists():
        return
    data = json.loads(ARTIFACT_DATA.read_text())
    by_title = {
        r["title"]: (r[COLUMN_KEY], r[VERDICT_KEY], r[IDS_KEY]) for r in rows
    }
    target = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(target, list):
        return
    touched = 0
    for row in target:
        if isinstance(row, dict) and row.get("title") in by_title:
            text, verdict, ids = by_title[row["title"]]
            row[COLUMN_KEY] = text
            row[VERDICT_KEY] = verdict
            row[IDS_KEY] = ids
            touched += 1
    if touched:
        ARTIFACT_DATA.write_text(json.dumps(data, ensure_ascii=False))
    print(f"artifact/_data.json: updated {touched} rows")


def main() -> None:
    cells = load_assessments()
    rows = apply_to_json(cells)
    apply_to_csv(cells)
    apply_to_artifact(rows)
    tally: dict[str, int] = {}
    for cell in cells.values():
        tally[cell["verdict"]] = tally.get(cell["verdict"], 0) + 1
    print(f"added {COLUMN_KEY!r} to {len(rows)} rows in survey.json and survey.csv")
    for verdict, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:32s} {n}")


if __name__ == "__main__":
    main()

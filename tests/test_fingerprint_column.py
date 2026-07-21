"""Regression tests for the `provider_issue_fingerprints` column.

Guards the join in scripts/add_fingerprint_column.py: every surveyed repo carries an
assessment, the three published artifacts agree, every cited fingerprint id exists in the
catalogue, and — the one that actually matters — a `fingerprints_found` verdict is never
supported only by the catalogue's explicit negative controls.

    uv run --with pytest pytest tests/test_fingerprint_column.py
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FINDINGS = ROOT / "findings"

COLUMN_KEY = "provider_issue_fingerprints"
COLUMN_HEADER = "Signs provider issues messed up the paper"
VERDICT_KEY = "fingerprint_verdict"
VERDICT_HEADER = "Fingerprint verdict"
IDS_KEY = "fingerprint_ids"
IDS_HEADER = "Fingerprint IDs"

VERDICTS = {"fingerprints_found", "checked_clean", "inconclusive", "nothing_checkable_released"}

# Families that are explicitly NOT evidence of corruption. F12 and F17 are labelled negative
# results in the catalogue itself; F16 is the paperwork gap, which is why a problem would be
# unfalsifiable rather than proof that one occurred.
NON_EVIDENCE = {"F12", "F16", "F17"}


@pytest.fixture(scope="module")
def survey_rows() -> list[dict]:
    return json.loads((FINDINGS / "survey.json").read_text())["rows"]


@pytest.fixture(scope="module")
def csv_rows() -> list[dict]:
    with (FINDINGS / "survey.csv").open(newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def catalogue_ids() -> set[str]:
    data = json.loads((FINDINGS / "fingerprints.json").read_text())
    return {f["id"] for f in data["families"]}


def test_every_repo_has_an_assessment(survey_rows: list[dict]) -> None:
    missing = [r["title"] for r in survey_rows if not (r.get(COLUMN_KEY) or "").strip()]
    assert not missing, f"repos with no fingerprint assessment: {missing}"


def test_every_repo_has_a_valid_verdict(survey_rows: list[dict]) -> None:
    for r in survey_rows:
        assert r.get(VERDICT_KEY) in VERDICTS, f"{r['title']}: {r.get(VERDICT_KEY)!r}"


def test_csv_and_json_agree(survey_rows: list[dict], csv_rows: list[dict]) -> None:
    assert len(survey_rows) == len(csv_rows)
    for j, c in zip(survey_rows, csv_rows, strict=True):
        assert j["title"] == c["Title"]
        assert j[COLUMN_KEY] == c[COLUMN_HEADER]
        assert j[VERDICT_KEY] == c[VERDICT_HEADER]
        assert ", ".join(j[IDS_KEY]) == c[IDS_HEADER]


def test_artifact_data_in_sync(survey_rows: list[dict]) -> None:
    artifact = json.loads((ROOT / "artifact" / "_data.json").read_text())
    by_title = {r["title"]: r for r in survey_rows}
    for row in artifact:
        src = by_title[row["title"]]
        assert row[COLUMN_KEY] == src[COLUMN_KEY]
        assert row[VERDICT_KEY] == src[VERDICT_KEY]
        assert row[IDS_KEY] == src[IDS_KEY]


def test_assessments_file_matches_survey(survey_rows: list[dict]) -> None:
    cells = json.loads((FINDINGS / "fingerprint_assessments.json").read_text())["cells"]
    assert set(cells) == {r["title"] for r in survey_rows}


def test_cited_fingerprints_exist(survey_rows: list[dict], catalogue_ids: set[str]) -> None:
    for r in survey_rows:
        unknown = set(r[IDS_KEY]) - catalogue_ids
        assert not unknown, f"{r['title']} cites fingerprints not in the catalogue: {sorted(unknown)}"


def test_a_positive_finding_is_never_only_negative_controls(survey_rows: list[dict]) -> None:
    """The whole point of F12/F16/F17 is that they do not evidence corruption."""
    for r in survey_rows:
        if r[VERDICT_KEY] != "fingerprints_found":
            continue
        real = set(r[IDS_KEY]) - NON_EVIDENCE
        assert real, (
            f"{r['title']} is marked fingerprints_found but cites only {sorted(r[IDS_KEY])}, "
            "which the catalogue defines as non-evidence"
        )


def test_nothing_checkable_cells_claim_no_observation(survey_rows: list[dict]) -> None:
    """If nothing was released, the cell cannot be citing an observed behavioural fingerprint."""
    for r in survey_rows:
        if r[VERDICT_KEY] != "nothing_checkable_released":
            continue
        observed = set(r[IDS_KEY]) - NON_EVIDENCE
        assert not observed, (
            f"{r['title']} says nothing checkable was released yet cites {sorted(observed)}"
        )


def test_no_verifier_meta_language_leaked_into_prose(survey_rows: list[dict]) -> None:
    """Cells are published prose, not internal review notes about an earlier draft."""
    banned = re.compile(
        r"\b(the claim|this claim|the original claim|the reviewed claim|the original submission"
        r"|the earlier agent|I confirmed|I downgrade|I verified|checks out)\b",
        re.IGNORECASE,
    )
    offenders = [r["title"] for r in survey_rows if banned.search(r[COLUMN_KEY])]
    assert not offenders, f"verifier framing leaked into published cells: {offenders}"


def test_stats_carries_the_verdict_tally(survey_rows: list[dict]) -> None:
    stats = json.loads((FINDINGS / "stats.json").read_text())
    assert "fingerprint_verdict" in stats, "regenerate stats.json"
    expected: dict[str, int] = {}
    for r in survey_rows:
        expected[r[VERDICT_KEY]] = expected.get(r[VERDICT_KEY], 0) + 1
    assert stats["fingerprint_verdict"] == dict(
        sorted(expected.items(), key=lambda kv: -kv[1])
    )


def test_artifact_page_renders_the_field() -> None:
    tmpl = (ROOT / "artifact" / "index_template.html").read_text()
    assert "fingerprintBlock(d)" in tmpl
    assert "provider_issue_fingerprints" in tmpl
    for verdict in VERDICTS:
        assert verdict in tmpl, f"artifact template does not label the {verdict!r} verdict"

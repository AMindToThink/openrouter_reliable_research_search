"""Provenance tests for the fingerprint catalogue and its generated report.

`findings/fingerprints.json` is the source of truth; `reports/detection-fingerprints.md` is
derived from it by `scripts/make_fingerprints.py`. These tests enforce that the catalogue is
internally consistent, that it only claims fingerprint-to-mistake links the taxonomy actually
defines, and that the report on disk is the one the script currently produces.

    uv run pytest tests/test_fingerprints.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = ROOT / "findings" / "fingerprints.json"
REPORT = ROOT / "reports" / "detection-fingerprints.md"
TAXONOMY = ROOT / "findings" / "taxonomy.md"

POWERS = {"high", "medium", "low"}
EVIDENCE = {"documented_catch", "literature_supported", "plausible_untested"}
VERIFICATION = {"verified", "partial"}
REQUIRED = {
    "id", "name", "one_line", "what_you_see", "where_to_look", "mechanism", "how_to_check",
    "benign_explanations", "discriminative_power", "evidence_strength", "needs_raw_outputs",
    "related_mistake_ids", "verification", "real_instances", "sources",
}


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads(CATALOGUE.read_text())


@pytest.fixture(scope="module")
def families(data: dict) -> list[dict]:
    return data["families"]


@pytest.fixture(scope="module")
def taxonomy_ids() -> set[str]:
    """M-ids the taxonomy actually defines, read from its table rather than hardcoded."""
    return set(re.findall(r"\*\*(M\d+)\*\*", TAXONOMY.read_text()))


def test_every_family_has_every_field(families: list[dict]) -> None:
    for f in families:
        missing = REQUIRED - set(f)
        assert not missing, f"{f.get('id')}: missing {sorted(missing)}"


def test_ids_are_sequential(families: list[dict]) -> None:
    assert [f["id"] for f in families] == [f"F{i}" for i in range(1, len(families) + 1)]


def test_enums(families: list[dict]) -> None:
    for f in families:
        assert f["discriminative_power"] in POWERS, f["id"]
        assert f["evidence_strength"] in EVIDENCE, f["id"]
        assert f["verification"] in VERIFICATION, f["id"]
        assert isinstance(f["needs_raw_outputs"], bool), f["id"]


def test_mistake_links_exist_in_taxonomy(families: list[dict], taxonomy_ids: set[str]) -> None:
    """A fingerprint may only claim to reveal a mistake the taxonomy defines."""
    assert taxonomy_ids, "failed to parse any M-ids out of taxonomy.md"
    for f in families:
        unknown = set(f["related_mistake_ids"]) - taxonomy_ids
        assert not unknown, f"{f['id']} references undefined mistakes {sorted(unknown)}"


def test_every_family_lists_benign_explanations(families: list[dict]) -> None:
    """A fingerprint with no competing innocent explanation has not been thought about."""
    for f in families:
        assert len(f["benign_explanations"]) >= 2, (
            f"{f['id']} lists fewer than two benign explanations — the point of the catalogue "
            "is that most observations have mundane causes"
        )


def test_documented_catch_families_cite_something(families: list[dict]) -> None:
    """`documented_catch` means someone really caught a provider; show the receipt."""
    for f in families:
        if f["evidence_strength"] != "documented_catch":
            continue
        assert f["real_instances"] or f["sources"], f"{f['id']} claims a catch with no citation"


def test_real_instances_are_well_formed(families: list[dict]) -> None:
    for f in families:
        for ri in f["real_instances"]:
            assert set(ri) == {"what_happened", "url", "verbatim_quote"}, f["id"]
            assert ri["url"].startswith("http"), f"{f['id']}: bad url {ri['url']!r}"
            assert ri["what_happened"].strip(), f["id"]


def test_negative_families_are_marked_low_power(families: list[dict]) -> None:
    """The explicit negative controls must never read as usable evidence."""
    negatives = [f for f in families if f["name"].startswith(("NEGATIVE CONTROL", "NEGATIVE RESULT"))]
    assert negatives, "the catalogue must carry explicit negative results"
    for f in negatives:
        assert f["discriminative_power"] == "low", f"{f['id']} is a negative result but not low-power"


def test_checklist_and_undetectable_reference_real_families(data: dict, families: list[dict]) -> None:
    ids = {f["id"] for f in families}
    text = " ".join(data["reader_checklist"]) + " " + " ".join(data["undetectable"])
    cited = set(re.findall(r"\bF\d+\b", text))
    assert cited, "the checklist should point at specific fingerprints"
    assert cited <= ids, f"references unknown fingerprints {sorted(cited - ids)}"


def test_verification_is_complete(data: dict) -> None:
    """Every candidate got an adversarial verifier, and every family says so.

    The first run of this sweep lost its verification stage to a spend limit and the
    catalogue shipped with families marked `partial`. That is a legitimate state to be in
    briefly, but it must never be silently mistaken for a finished audit — so the counts and
    the per-family labels are checked against each other here.
    """
    prov = data["provenance"]
    assert prov["unverified_candidates"] == 0, "some candidates still have no verifier"
    assert prov["verified_candidates"] == prov["raw_candidates"]
    assert prov["survived_verification"] <= prov["verified_candidates"]
    unverified = [f["id"] for f in data["families"] if f["verification"] != "verified"]
    assert not unverified, (
        f"provenance claims full verification but these families are not: {unverified}"
    )


def test_undetectable_section_is_substantive(data: dict) -> None:
    """The honest negative result is load-bearing; a stub would quietly overclaim."""
    assert len(data["undetectable"]) >= 5


def test_report_matches_generator(tmp_path: Path) -> None:
    """`reports/detection-fingerprints.md` must be exactly what the script produces today."""
    before = REPORT.read_text()
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_fingerprints.py")],
        check=True, cwd=ROOT, capture_output=True,
    )
    after = REPORT.read_text()
    assert before == after, (
        "reports/detection-fingerprints.md is stale or hand-edited — "
        "run `uv run scripts/make_fingerprints.py`"
    )


def test_report_names_every_family(families: list[dict]) -> None:
    text = REPORT.read_text()
    for f in families:
        assert f"### {f['id']} — " in text, f"{f['id']} missing from the report"

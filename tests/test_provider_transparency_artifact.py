"""Integrity checks for the graded provider report card before it gets published.

Grading vendors is the most opinionated thing in this repo, so the page has to keep two
promises the rest of the project makes elsewhere:

  1. **A grade never outruns its evidence.** Only providers verified against a live page
     snapshot are graded; the unchecked leads stay ungraded, on the same rule that denies
     them quotations. A score with no recorded reason is a number the reader cannot argue
     with, so the generator refuses one.
  2. **No letter is hand-typed.** Letters are computed from the four criterion scores at
     build time. If someone edits a score, the letter moves with it; there is no stored
     grade that can quietly disagree with the reasoning printed beside it.

    uv run --with pytest pytest tests/test_provider_transparency_artifact.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "findings" / "provider_transparency.json"
GRADES = ROOT / "findings" / "provider_grades.json"
PAGE = ROOT / "artifact" / "provider-transparency.html"
TEMPLATE = ROOT / "artifact" / "provider-transparency_template.html"
GEN = ROOT / "scripts" / "make_provider_transparency_artifact.py"

CRITERIA = ("A", "B", "C", "P")


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text()


@pytest.fixture(scope="module")
def grading() -> dict:
    return json.loads(GRADES.read_text())


@pytest.fixture(scope="module")
def entries() -> list[dict]:
    return json.loads(AUDIT.read_text())["entries"]


def rows(page: str) -> list[dict]:
    """The graded rows exactly as the published page received them."""
    m = re.search(r"const ROWS = (\[.*?\]);\n", page, re.S)
    assert m, "the page no longer carries its ROWS payload"
    return json.loads(m.group(1).replace("\\u003c", "<"))


# --- the page is publishable as an Artifact ---------------------------------------

@pytest.mark.parametrize("tag", ["<!doctype", "<html", "<body", "</body>", "</html>"])
def test_page_has_no_document_wrapper(page: str, tag: str) -> None:
    """Artifacts are wrapped in their own skeleton; our own wrapper would nest documents."""
    assert tag not in page.lower()


def test_page_starts_with_a_title(page: str) -> None:
    assert page.lstrip().startswith("<title>"), "the <title> names the artifact in the gallery"


def test_page_has_exactly_one_script_block(page: str) -> None:
    assert page.count("<script>") == 1 and page.count("</script>") == 1


def test_no_external_resources(page: str) -> None:
    """A strict CSP blocks every external host — the page must be self-contained."""
    for pattern in (r"<script[^>]+src=", r'<link[^>]+href="https?://',
                    r"@import\s+url\(", r'https?://[^"\')\s]+\.(?:js|css|woff2?)'):
        assert not re.search(pattern, page, re.I), f"external resource matched {pattern!r}"


def test_embedded_data_cannot_break_out_of_the_script(page: str) -> None:
    body = re.search(r"<script>(.*)</script>", page, re.S).group(1)
    for bad in ("</script", "<!--", "]]>"):
        assert bad not in body, f"{bad!r} inside the script block would terminate it early"


def test_page_is_regenerable(page: str) -> None:
    """The guard against a hand-edit: the file must rebuild byte-identically."""
    subprocess.run([sys.executable, str(GEN)], check=True, capture_output=True)
    after = PAGE.read_text()
    if after != page:
        PAGE.write_text(page)  # leave the tree as we found it
        pytest.fail("artifact/provider-transparency.html is not what the generator produces "
                    "— edit findings/provider_grades.json and regenerate instead.")


# --- a grade never outruns its evidence -------------------------------------------

def test_only_verified_providers_are_graded(grading: dict, entries: list[dict]) -> None:
    verified = {e["key"] for e in entries if e.get("verified")}
    assert set(grading["grades"]) == verified, (
        "grades must cover every verified provider and no unchecked lead — scoring a lead "
        "would launder a search result into a finding")


def test_unchecked_leads_reach_the_page_ungraded(page: str, entries: list[dict]) -> None:
    leads = re.search(r"const LEADS = (\[.*?\]);\n", page, re.S)
    assert leads, "the page no longer carries its LEADS payload"
    parsed = json.loads(leads.group(1).replace("\\u003c", "<"))
    assert len(parsed) == len([e for e in entries if not e.get("verified")])
    assert all("scores" not in lead and "letter" not in lead for lead in parsed)


def test_every_score_is_in_range_and_explained(grading: dict) -> None:
    for key, g in grading["grades"].items():
        assert set(g["scores"]) == set(CRITERIA), f"{key}: needs all four criterion scores"
        for c in CRITERIA:
            assert g["scores"][c] in (0, 1, 2), f"{key}/{c}: scores are 0, 1 or 2"
            assert g["reasons"].get(c), f"{key}/{c}: an unexplained score is unarguable"


def test_the_page_quotes_nothing_the_audit_does_not_hold(page: str, entries: list[dict]) -> None:
    known = {q for e in entries for q in e.get("quotes", [])}
    for row in rows(page):
        unknown = [q for q in row["quotes"] if q not in known]
        assert not unknown, f"{row['key']} shows text absent from {AUDIT.name}: {unknown}"


# --- no letter is hand-typed ------------------------------------------------------

def test_no_letter_is_stored_in_the_data(grading: dict) -> None:
    """A stored grade could disagree with the reasoning printed beside it."""
    for key, g in grading["grades"].items():
        assert not {"letter", "grade"} & set(g), f"{key}: the letter is computed, not curated"


def test_published_letters_match_a_recomputation(page: str, grading: dict) -> None:
    rubric = grading["_rubric"]
    for row in rows(page):
        assert row["total"] == sum(row["scores"][c] for c in CRITERIA)
        expected = next(name for cut, name in rubric["bands"] if row["total"] >= cut)
        if row["flag"] and expected < rubric["cap_on_flag"]:
            expected = rubric["cap_on_flag"]
        assert row["letter"] == expected, (
            f"{row['key']}: page says {row['letter']}, the scores say {expected}")


def test_an_a_requires_full_marks(grading: dict) -> None:
    """The top band is 8/8. If a provider ever earns one, this test should pass — what it
    forbids is quietly lowering the bar so that something finally reaches it."""
    top_cut, top_name = grading["_rubric"]["bands"][0]
    assert (top_name, top_cut) == ("A", 8), "an A means solid on all four criteria"


def test_every_band_is_reachable_and_ordered(grading: dict) -> None:
    bands = grading["_rubric"]["bands"]
    cuts = [c for c, _ in bands]
    assert cuts == sorted(cuts, reverse=True), "bands are matched highest-first"
    assert cuts[-1] == 0, "the bottom band must catch every score"

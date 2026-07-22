"""The prior-work list must never contain a citation nobody checked.

Three failure modes this suite exists to prevent, all of which happened at least once while
the list was being built:

  1. **Hand-typed paper metadata.** A search agent reported a title and author list from
     memory. Titles/authors/dates for arXiv entries must come from the arXiv API snapshot,
     so `prior_work.json` is forbidden from carrying them.
  2. **Paraphrase presented as a quotation.** A page-summarising model returned a fluent,
     plausible, and entirely invented list of a paper's contents. Every quotation must
     therefore appear verbatim in the fetched abstract or page text.
  3. **An unchecked lead reading as evidence.** Entries with `verified: false` were surfaced
     by search and confirmed by nobody; they must carry no quotation and must stay in the
     leads section.

    uv run pytest tests/test_prior_work.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "findings" / "prior_work.json"
SNAP = ROOT / "findings" / "prior_work_sources.json"
DOC = ROOT / "reports" / "prior-work.md"

# Metadata that must be fetched, never typed into the curated list.
FETCHED_ONLY = ("title", "authors", "author", "published", "abstract")


def norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    for a, b in [("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), ("−", "-")]:
        s = s.replace(a, b)
    return s.strip().lower()


@pytest.fixture(scope="module")
def entries() -> list[dict]:
    return json.loads(SRC.read_text())["entries"]


@pytest.fixture(scope="module")
def sources() -> dict[str, dict]:
    return json.loads(SNAP.read_text())["sources"]


def test_keys_are_unique(entries: list[dict]) -> None:
    keys = [e["key"] for e in entries]
    assert len(keys) == len(set(keys)), f"duplicate keys: {[k for k in keys if keys.count(k) > 1]}"


def test_every_verified_entry_has_a_fetched_source(entries: list[dict], sources: dict) -> None:
    missing = [e["key"] for e in entries if e.get("verified") and e["key"] not in sources]
    assert not missing, f"verified but never fetched: {missing}"


def test_arxiv_entries_do_not_hand_type_metadata(entries: list[dict]) -> None:
    offenders = {e["key"]: [f for f in FETCHED_ONLY if f in e]
                 for e in entries if "arxiv_id" in e}
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, (
        f"arXiv metadata must come from the API snapshot, not the curated file: {offenders}")


def test_quotes_are_verbatim_in_the_fetched_source(entries: list[dict], sources: dict) -> None:
    """The core guard: a quotation that is not in the source is a fabrication."""
    for e in entries:
        if not e.get("verified"):
            continue
        rec = sources[e["key"]]
        haystack = rec["abstract"] if rec["kind"] == "arxiv" else rec["quote_context"]
        assert norm(e["quote"]) in norm(haystack), (
            f"{e['key']}: quote is not verbatim in the fetched "
            f"{'abstract' if rec['kind'] == 'arxiv' else 'page text'}:\n  {e['quote']!r}")


def test_unverified_leads_carry_no_quote(entries: list[dict]) -> None:
    offenders = [e["key"] for e in entries if not e.get("verified") and e.get("quote")]
    assert not offenders, f"unchecked leads must not be quoted: {offenders}"


def test_every_entry_has_taxonomy_or_reason(entries: list[dict]) -> None:
    taxonomy = (ROOT / "findings" / "taxonomy.md").read_text()
    for e in entries:
        assert e.get("why"), f"{e['key']}: no `why` — say what it is evidence for, or drop it"
        for code in e.get("supports", []):
            assert re.search(rf"\b{code}\b", taxonomy), f"{e['key']}: {code} is not in taxonomy.md"


def test_generated_doc_is_in_sync() -> None:
    """reports/prior-work.md is generated; a hand edit must fail rather than persist."""
    before = DOC.read_text()
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_prior_work.py")],
                   check=True, capture_output=True, cwd=ROOT)
    after = DOC.read_text()
    if before != after:
        DOC.write_text(after)  # leave the corrected file in place, then fail loudly
        pytest.fail("reports/prior-work.md was stale or hand-edited; regenerated it. "
                    "Edit findings/prior_work.json and rerun scripts/make_prior_work.py.")


def test_readme_prior_work_figures_are_quoted_from_a_source(sources: dict) -> None:
    """Every figure the README borrows from prior work must exist in a verified quotation.

    The README's own statistics are pinned by tests/test_claims_provenance.py against
    claims.json. Numbers taken from someone else's paper have no claim behind them, so they
    are pinned here instead: to the quote, quote context, or body-quote text that
    scripts/fetch_prior_work_sources.py located in the source itself.
    """
    readme = (ROOT / "README.md").read_text()
    section = readme.split("## This isn't a new claim", 1)
    assert len(section) == 2, "the README prior-work section is missing"
    block = section[1].split("\n## ", 1)[0]

    # the skill quotes the same figures to auditors, under an explicit marker
    skill = (ROOT / "skill" / "use-openrouter-safely" / "SKILL.md").read_text()
    marked = re.search(r"<!-- PRIOR-WORK FIGURES:.*?-->(.*?)<!-- END PRIOR-WORK FIGURES -->",
                       skill, re.S)
    assert marked, "the skill's prior-work figures block is missing or its markers were renamed"
    block += marked.group(1)

    haystack = norm(" ".join(
        str(rec.get("abstract", "")) + " " + str(rec.get("quote_context", "")) + " "
        + " ".join(bq["context"] for bq in rec.get("body_quotes", []))
        for rec in sources.values()))

    # standalone numeric tokens only: skips M1, fp8, r1, 2023-2024 and similar identifiers
    figures = set(re.findall(r"(?<![A-Za-z0-9.\-])\d+(?:\.\d+)?%?(?![A-Za-z0-9.\-])", block))
    unsourced = [f for f in figures if norm(f) not in haystack]
    assert not unsourced, (
        f"README cites prior-work figures that appear in no verified quotation: {sorted(unsourced)}. "
        "Add a body_quote that contains them and rerun scripts/fetch_prior_work_sources.py.")


def test_doc_marks_unverified_leads_as_unverified() -> None:
    doc = DOC.read_text()
    assert "## Unchecked leads" in doc
    leads = [e for e in json.loads(SRC.read_text())["entries"] if not e.get("verified")]
    body, appendix = doc.split("## Unchecked leads", 1)
    for e in leads:
        assert e["key"] not in body or e.get("title", "") in appendix, (
            f"{e['key']} is unverified but appears outside the leads section")

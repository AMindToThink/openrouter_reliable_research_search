"""The transparency audit must never present an unchecked claim as a verified one.

This report is more dangerous than the rest of the repo because it is *about* trusting
vendors, and it is built largely from agent-reported search results. Four failure modes it
exists to prevent:

  1. **A search agent's paraphrase printed as a quotation.** Every quote must be located
     verbatim in a snapshot of the live page, taken by the fetch script — not in a
     page-summarising model's rendering of it.
  2. **An unchecked lead reading as evidence.** Entries with `verified: false` were
     confirmed by nobody; they must carry no quotation and stay in the leads section.
  3. **A hand-typed statistic.** The declaration-rate numbers in the prose must come from
     our own measurement, so the report must be byte-identically regenerable from the data.
  4. **A vendor quote that has quietly rotted.** Docs get rewritten. If a page no longer
     contains what we said it contains, that is a finding about the vendor and the suite
     must fail loudly rather than let the stale quote stand.

    uv run --with pytest pytest tests/test_provider_transparency.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "findings" / "provider_transparency.json"
SNAP = ROOT / "findings" / "provider_transparency_sources.json"
DOC = ROOT / "reports" / "provider-transparency.md"
GEN = ROOT / "scripts" / "make_provider_transparency.py"

VALID_AXES = {"A", "B", "C"}


@pytest.fixture(scope="module")
def entries() -> list[dict]:
    return json.loads(SRC.read_text())["entries"]


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(SNAP.read_text())


@pytest.fixture(scope="module")
def doc() -> str:
    return DOC.read_text()


def test_keys_are_unique(entries: list[dict]) -> None:
    keys = [e["key"] for e in entries]
    assert len(keys) == len(set(keys)), f"duplicate keys: {[k for k in keys if keys.count(k) > 1]}"


def test_every_entry_is_well_formed(entries: list[dict]) -> None:
    for e in entries:
        assert e["url"].startswith("https://"), f"{e['key']}: needs an https source URL"
        assert e.get("note"), f"{e['key']}: needs a note saying what was found"
        assert set(e.get("axes", [])) <= VALID_AXES, f"{e['key']}: unknown axis"
        if e.get("verified"):
            assert e.get("gap"), (
                f"{e['key']}: a verified entry must record what the provider still does NOT "
                "disclose. A one-sided entry reads as an endorsement.")


def test_unchecked_leads_carry_no_quotation(entries: list[dict]) -> None:
    """The load-bearing rule: nobody confirmed these, so they get no quotes."""
    offenders = [e["key"] for e in entries if not e.get("verified") and e.get("quotes")]
    assert not offenders, f"unverified entries carrying quotes: {offenders}"


def test_every_verified_entry_was_actually_fetched(entries: list[dict], snapshot: dict) -> None:
    sources = snapshot["sources"]
    missing = [e["key"] for e in entries if e.get("verified") and e["key"] not in sources]
    assert not missing, (
        f"marked verified but never fetched: {missing}. "
        "Run: uv run scripts/fetch_provider_transparency.py")


def test_every_quotation_was_located_verbatim(entries: list[dict], snapshot: dict) -> None:
    """A quote we cannot find in the live page is not a quote."""
    sources = snapshot["sources"]
    bad: list[str] = []
    for e in entries:
        if not e.get("verified"):
            continue
        rec = sources[e["key"]]
        confirmed = {q["quote"] for q in rec["quotes"] if q["confirmed"]}
        for q in e.get("quotes", []):
            if q not in confirmed:
                bad.append(f"{e['key']}: {q[:70]!r} (page returned HTTP {rec['status']})")
    assert not bad, "quotations not found in the fetched page:\n  " + "\n  ".join(bad)


def test_quoteless_verified_entries_explain_themselves(entries: list[dict]) -> None:
    """A verified entry with no quote must say what was checked instead (an API, an absence)."""
    for e in entries:
        if e.get("verified") and not e.get("quotes"):
            assert e.get("quote_exempt"), (
                f"{e['key']}: verified with no quotation and no `quote_exempt` explaining "
                "what was checked in its place.")


def test_report_quotes_nothing_that_is_not_in_the_data(entries: list[dict], doc: str) -> None:
    known = {q for e in entries for q in e.get("quotes", [])}
    quoted = [ln[2:].strip() for ln in doc.splitlines()
              if ln.startswith("> ") and ln.strip() != ">"]
    unknown = [q for q in quoted if q not in known]
    assert not unknown, f"report quotes text absent from {SRC.name}: {unknown}"


def test_measured_statistics_appear_in_the_report(snapshot: dict, doc: str) -> None:
    """Guards against a generator change silently dropping the one number that is ours."""
    m = snapshot["measured"]
    assert f"{m['endpoints_total']} serving endpoints" in doc
    assert f"{m['undeclared_pct']}%" in doc
    assert m["undeclared_count"] == m["by_quantization"]["undeclared"]
    assert 0 < m["undeclared_pct"] < 100, "a 0% or 100% rate means the sample broke"
    for provider in m["providers_always_undeclared"]:
        assert provider in doc, f"{provider} missing from the report's silent-provider list"


def test_readme_headline_matches_the_measurement(snapshot: dict) -> None:
    """The README borrows one figure from this report; it must not drift from the data.

    The README is hand-written, so nothing regenerates it — this assertion is the only
    thing standing between a refetched sample and a stale headline.
    """
    pct = snapshot["measured"]["undeclared_pct"]
    readme = (ROOT / "README.md").read_text()
    line = [ln for ln in readme.splitlines() if "provider-transparency.md" in ln]
    assert line, "the README no longer links reports/provider-transparency.md"
    assert f"{pct}% of sampled endpoints declare no quantization" in line[0], (
        f"README provider-transparency line must cite {pct}% — refetching moved it.")


def test_skill_and_guide_cite_the_audit_correctly(entries: list[dict], snapshot: dict) -> None:
    """The skill and the guide borrow figures from this audit; hold them to the data.

    Neither file is generated, so this assertion is the only thing keeping their prose in
    step with a refetch. The audit is the argument for pinning; a stale number in the
    advice would undercut exactly the discipline it is asking researchers to adopt.
    """
    m = snapshot["measured"]
    skill = (ROOT / "skill" / "use-openrouter-safely" / "SKILL.md").read_text()
    guide = (ROOT / "reports" / "openrouter-best-practices.md").read_text()

    n_verified = sum(1 for e in entries if e.get("verified"))
    n_leads = len(entries) - n_verified

    for name, text in (("SKILL.md", skill), ("best-practices", guide)):
        assert f"{len(entries)} provider" in text, (
            f"{name} must say how many providers were audited ({len(entries)})")
        assert f"{m['undeclared_pct']}%" in text, (
            f"{name} cites a declaration rate that is no longer {m['undeclared_pct']}%")

    assert f"{n_verified} verified" in guide and f"{n_leads} recorded as unchecked" in guide, (
        f"the guide must state the split ({n_verified} verified / {n_leads} leads) — a reader "
        "who is not told how thin the evidence is will over-trust it")
    assert f"{m['endpoints_total']} serving endpoints" in guide
    assert f"{len(m['providers_always_undeclared'])} providers" in guide


def test_skill_criterion_table_matches_the_grades(entries: list[dict]) -> None:
    """The skill names which providers score solid on each criterion. Hold it to the scores.

    This table is the reason the skill tells the model to *ask* rather than recommend — it is
    where "A and P are almost disjoint" is visible. A hand-typed name drifting out of step
    with findings/provider_grades.json would quietly turn that argument into an assertion.
    """
    grades_path = ROOT / "findings" / "provider_grades.json"
    if not grades_path.exists():
        pytest.skip("provider_grades.json not present on this branch")
    grades = json.loads(grades_path.read_text())["grades"]
    skill = (ROOT / "skill" / "use-openrouter-safely" / "SKILL.md").read_text()

    # "Azure AI Foundry" is written "Azure" in the skill's table; first word is the handle.
    short = {e["key"]: e["provider"].split()[0] for e in entries}

    top = max(sum(g["scores"].values()) for g in grades.values())
    assert f"The top score is {top}" in skill, f"the skill should say the top score is {top}"
    assert top < 8, "an A is now achievable — the skill's 'A band is vacant' claim is stale"

    rows = {line.split("|")[1].strip(): line.split("|")[3].strip()
            for line in skill.splitlines()
            if line.startswith("| **") and line.count("|") >= 4}
    for crit in ("A", "B", "C", "P"):
        row = next((v for k, v in rows.items() if k.startswith(f"**{crit}**")), None)
        assert row is not None, f"the skill's criterion table has no {crit} row"
        for key, g in grades.items():
            named = short[key] in row
            solid = g["scores"][crit] == 2
            assert named == solid, (
                f"criterion {crit}: {short[key]} scores {g['scores'][crit]} but is "
                f"{'listed' if named else 'not listed'} in the skill's solid column")


def test_report_is_regenerable(doc: str) -> None:
    """The strongest guard against hand-typed numbers: the file must rebuild byte-identically."""
    before = doc
    subprocess.run([sys.executable, str(GEN)], check=True, capture_output=True)
    after = DOC.read_text()
    if after != before:
        DOC.write_text(before)  # leave the tree as we found it
        pytest.fail(f"{DOC.name} is not what the generator produces — it was edited by hand. "
                    "Edit findings/provider_transparency.json and regenerate instead.")

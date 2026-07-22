#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Build the explorable provider report card from the audit and its grading rubric.

The audit (findings/provider_transparency.json) records what each provider does and does
not disclose. The rubric (findings/provider_grades.json) scores it. This joins the two and
inlines the result into artifact/provider-transparency_template.html.

No letter is ever stored. Grades are computed here from the four criterion scores, so a
grade cannot drift away from the reasoning printed beside it, and a score edited in the
data moves the letter on the page without anyone remembering to.

Only entries verified against a live page snapshot are graded. The unchecked leads are
carried through ungraded, on the same rule that denies them quotations.

Run:  uv run scripts/make_provider_transparency_artifact.py
Out:  artifact/provider-transparency.html
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "findings/provider_transparency.json"
GRADES = ROOT / "findings/provider_grades.json"
SNAP = ROOT / "findings/provider_transparency_sources.json"
TEMPLATE = ROOT / "artifact/provider-transparency_template.html"
OUT = ROOT / "artifact/provider-transparency.html"

ROWS_PLACEHOLDER = "/*__ROWS__*/[]"
RUBRIC_PLACEHOLDER = "/*__RUBRIC__*/{}"
LEADS_PLACEHOLDER = "/*__LEADS__*/[]"

CRITERIA = ("A", "B", "C", "P")


def letter_for(total: int, bands: list[list], flagged: bool, cap: str) -> str:
    """Lowest band whose threshold the total clears, then the flag cap.

    Bands arrive highest-first, so the first threshold the total reaches wins.
    """
    grade = next(name for threshold, name in bands if total >= threshold)
    if flagged and grade < cap:  # letters sort the same way grades rank
        return cap
    return grade


def main() -> None:
    audit = json.loads(AUDIT.read_text())
    grading = json.loads(GRADES.read_text())
    confirmed = {
        key: {q["quote"] for q in rec["quotes"] if q["confirmed"]}
        for key, rec in json.loads(SNAP.read_text())["sources"].items()
    }

    rubric = grading["_rubric"]
    grades = grading["grades"]
    entries = audit["entries"]

    verified = [e for e in entries if e.get("verified")]
    leads = sorted([e for e in entries if not e.get("verified")], key=lambda e: e["rank"])

    ungraded = [e["key"] for e in verified if e["key"] not in grades]
    if ungraded:
        raise SystemExit(
            f"verified but ungraded: {ungraded}. Every provider the audit stands behind "
            f"needs a score block in {GRADES.name}, or the ledger silently omits it."
        )
    stray = [k for k in grades if k not in {e["key"] for e in verified}]
    if stray:
        raise SystemExit(
            f"graded but not verified: {stray}. Scoring an unverified lead would launder "
            "a search result into a finding."
        )

    rows = []
    for e in verified:
        g = grades[e["key"]]
        scores = {k: int(g["scores"][k]) for k in CRITERIA}
        if any(v not in (0, 1, 2) for v in scores.values()):
            raise SystemExit(f"{e['key']}: scores must be 0, 1 or 2 — got {scores}")
        missing = [k for k in CRITERIA if not g["reasons"].get(k)]
        if missing:
            raise SystemExit(
                f"{e['key']}: no reason recorded for {missing}. An unexplained score is a "
                "number the reader cannot argue with."
            )
        total = sum(scores.values())
        # Print only what the live page still says: a quote that has rotted is dropped
        # here and fails tests/test_provider_transparency.py loudly.
        quotes = [q for q in e.get("quotes", []) if q in confirmed.get(e["key"], set())]
        rows.append(
            {
                "key": e["key"],
                "provider": e["provider"],
                "or_slug": e["or_slug"],
                "url": e["url"],
                "axes": e["axes"],
                "quotes": quotes,
                "quote_exempt": e.get("quote_exempt", ""),
                "note": e["note"],
                "gap": e["gap"],
                "scores": scores,
                "reasons": {k: g["reasons"][k] for k in CRITERIA},
                "flag": g.get("flag"),
                "total": total,
                "letter": letter_for(
                    total, rubric["bands"], bool(g.get("flag")), rubric["cap_on_flag"]
                ),
            }
        )

    lead_rows = [
        {"provider": e["provider"], "url": e["url"], "axes": e["axes"], "note": e["note"]}
        for e in leads
    ]

    def inline(value: object) -> str:
        # `</script` inside the payload would close the block early; `<` is the same
        # string to JSON.parse and inert to the HTML parser.
        return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")

    html = TEMPLATE.read_text()
    for placeholder, payload in (
        (ROWS_PLACEHOLDER, rows),
        (RUBRIC_PLACEHOLDER, rubric),
        (LEADS_PLACEHOLDER, lead_rows),
    ):
        if html.count(placeholder) != 1:
            raise SystemExit(f"template must carry exactly one {placeholder}")
        html = html.replace(placeholder, inline(payload))

    OUT.write_text(html)
    spread = ", ".join(
        f"{name}:{sum(1 for r in rows if r['letter'] == name)}"
        for _, name in rubric["bands"]
    )
    print(f"wrote {OUT.relative_to(ROOT)} — {len(rows)} graded ({spread}), "
          f"{len(lead_rows)} ungraded leads")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regenerate findings/summary.md from the survey data.

Every number here is read from findings/survey.json / stats.json — never hand-typed —
so the summary cannot drift from the dataset.

Usage:  uv run scripts/make_summary.py
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = json.loads((ROOT / "findings/survey.json").read_text())["rows"]
st = json.loads((ROOT / "findings/stats.json").read_text())

NAME = {"M1": "Unpinned quantization", "M2": "Silent parameter dropping", "M3": "Probabilistic provider routing",
        "M4": "No provenance logging", "M5": "Data-policy leakage", "M6": "Model version drift",
        "M7": "seed→determinism assumption", "M8": "Cross-provider comparison confound",
        "M9": "Judge on unconstrained route", "M10": "No reporting", "M11": "Silent backend mixing",
        "M12": "Cheap/degraded route chosen"}
SEV = {"M1": "High", "M2": "High", "M3": "High", "M4": "High", "M5": "Med", "M6": "Med", "M7": "Med",
       "M8": "High", "M9": "High", "M10": "Med", "M11": "Med", "M12": "Med"}

n = st["n"]
imp = st["impacted"]
verified = imp["impact_verified_rows"]

# Safety classes replace the old binary safe/unsafe split: a repo that never routes a
# research call through OpenRouter has demonstrated nothing about using it well, so it is
# excluded from the denominator rather than counted as a success. Written by
# scripts/set_safety_class.py — run that before this.
try:
    KL = st["safety_class"]
    USERS = st["actual_openrouter_users"]
    PCT_USERS = st["at_risk_pct_of_users"]
    CRIT = st["critical_route"]
    PCT = st["at_risk_pct_of_critical_route"]
except KeyError as exc:  # fail loudly rather than silently emitting the stale framing
    raise SystemExit(
        f"stats.json is missing {exc.args[0]!r} — run `uv run scripts/set_safety_class.py` first. "
        "Refusing to regenerate summary.md with the superseded safe/unsafe framing."
    ) from exc
AT_RISK = KL.get("at_risk", 0)
HANDLED = KL.get("handled", 0)
OFF_PATH = KL.get("not_on_result_path", 0)
NO_USAGE = KL.get("no_usage_found", 0)
CLASS_LABEL = {"at_risk": "❌ at risk", "handled": "✅ handled",
               "not_on_result_path": "➖ off result path", "no_usage_found": "➖ no usage"}

L: list[str] = []

L.append("# Findings — do important research repos use OpenRouter reliably?\n")
L.append(f"> **{AT_RISK} of {CRIT} ({PCT}%)** of the surveyed repos whose OpenRouter output actually reaches a "
         f"reported result, a training set, or a safety measurement leave at least one uncontrolled "
         f"provider-routing corruption channel open. **Exactly {HANDLED}** controls for it. We traced "
         f"**{imp['total_findings']} specific claims/figures** across **{imp['repos_with_impacted_findings']} repos** "
         f"that could be affected.\n")
L.append(f"> Denominators, precisely: **{n}** repos surveyed · **{USERS}** contain an OpenRouter call site "
         f"anywhere ({AT_RISK}/{USERS} = {PCT_USERS}% at risk) · **{CRIT}** put its output on a result path. "
         f"The headline uses {CRIT}, because a repo only demonstrates something about *using OpenRouter well* "
         f"if OpenRouter reaches a published number. The {OFF_PATH} `not_on_result_path` and {NO_USAGE} "
         f"`no_usage_found` repos are excluded — they are not successes, they are non-data-points.\n")
L.append("**Read this correctly.** *At risk* means *exposed to a known corruption channel that was not controlled "
         "for* — **not** that any published number is wrong. *Possibly-impacted findings* are **hypotheses worth "
         "checking, not demonstrated errors**. We audited how the code routes model calls; we did not re-run "
         "experiments across providers to measure the actual delta. See `methodology.md`.\n")

L.append("## Headline numbers\n")
L.append(f"- Repos audited: **{n}** (importance-first: NeurIPS/ICML/ICLR/ACL/NAACL/Nature + "
         "UK AISI/METR/Redwood/Palisade/Anthropic-Fellows + LessWrong/AF)")
L.append(f"- OpenRouter output reaches a reported result: **{CRIT}** · contains any OpenRouter call site: "
         f"**{USERS}** (of {n} surveyed)")
L.append(f"- Safety classes: **at_risk {AT_RISK}** · **handled {HANDLED}** · not_on_result_path {OFF_PATH} · "
         f"no_usage_found {NO_USAGE}")
L.append(f"- Severity: **{st['severity'].get('high', 0)} high**, {st['severity'].get('medium', 0)} medium, "
         f"{st['severity'].get('none', 0)} none")
L.append(f"- **Specific possibly-impacted findings: {imp['total_findings']}** "
         f"({imp['by_severity']['high']} high-impact, {imp['by_severity']['medium']} medium, "
         f"{imp['by_severity']['low']} low) across {imp['repos_with_impacted_findings']}/{n} repos")
L.append(f"- Adversarial verification completed for **{verified}/{n}** rows"
         + ("" if verified == n else f" ({n - verified} flagged `impact_verified: false`)"))
L.append(f"- Author awareness: {st['awareness'].get('aware_and_handled', 0)} aware & handled, "
         f"{st['awareness'].get('aware_partial', 0)} partially aware, {st['awareness'].get('unaware', 0)} unaware\n")

L.append("## Most common mistakes\n")
L.append(f"| Rank | ID | Mistake | Severity | Repos (of {n}) |")
L.append("| --- | --- | --- | --- | --- |")
for i, (m, c) in enumerate(st["mistake_freq"].items(), 1):
    L.append(f"| {i} | {m} | {NAME.get(m, m)} | {SEV.get(m, '?')} | {c} |")
L.append("")

L.append("## Examples of specific possibly-impacted claims\n")
L.append("Each row of `survey.csv` carries a **Possibly-impacted findings** column naming the exact "
         "figure/table/number and the mechanism. A few illustrative ones:\n")
shown = 0
for r in rows:
    fs = [f for f in (r.get("impacted_findings") or [])
          if f.get("severity") == "high" and f.get("depends_on_or") == "high"]
    if not fs or shown >= 6:
        continue
    f = fs[0]
    L.append(f"- **{r['title'].split(' (')[0]}** — *{f['locator'][:120]}*: {f['finding'][:190]}")
    shown += 1
L.append("")

L.append("## The one repo that uses it properly\n")
for r in rows:
    if r.get("safety_class") == "handled":
        why = (r.get("safety_class_reason") or r.get("audit_notes") or "")[:400].replace("\n", " ")
        L.append(f"- **{r['title']}** — {why}")
L.append("")

L.append("## Not success stories (recorded separately, not counted as safe)\n")
L.append("These repos avoid the mistakes only because no reported result depends on OpenRouter — "
         "which demonstrates nothing about using it well.\n")
for r in rows:
    if r.get("safety_class") in ("not_on_result_path", "no_usage_found"):
        why = (r.get("safety_class_reason") or "")[:300].replace("\n", " ")
        L.append(f"- **{r['title']}** (`{r['safety_class']}`) — {why}")
L.append("")

L.append("## Full table\n")
L.append("| Repo | Venue | Class | Severity | Mistakes | Impacted claims |")
L.append("| --- | --- | :---: | :---: | --- | :---: |")
for r in rows:
    cls = CLASS_LABEL.get(r.get("safety_class", ""), r.get("safety_class", "?"))
    mids = ", ".join(r.get("mistake_ids") or []) or "—"
    L.append(f"| {r['title'].split(' (')[0][:44]} | {(r.get('venue') or '')[:24]} | {cls} | "
             f"{r.get('severity')} | {mids} | {len(r.get('impacted_findings') or [])} |")
L.append("\nSee `survey.csv` / `survey.json` for full detail (evidence, call-site permalink, one-line fix, "
         "per-claim mechanism and confidence).\n")

(ROOT / "findings/summary.md").write_text("\n".join(L))
print(f"wrote findings/summary.md — {imp['total_findings']} findings, {verified}/{n} verified")

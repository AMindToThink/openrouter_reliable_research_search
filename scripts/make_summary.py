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
L: list[str] = []

L.append("# Findings — do important research repos use OpenRouter reliably?\n")
L.append(f"> **{st['unsafe']} of {n}** surveyed important research repos ({round(100 * st['unsafe'] / n)}%) leave at "
         f"least one uncontrolled provider-routing corruption channel open. **{st['critical_route']} of {n}** route "
         f"OpenRouter output straight into a reported result, a training set, or a safety measurement. We traced "
         f"**{imp['total_findings']} specific claims/figures** across **{imp['repos_with_impacted_findings']} repos** "
         f"that could be affected.\n")
L.append("**Read this correctly.** *At risk* means *exposed to a known corruption channel that was not controlled "
         "for* — **not** that any published number is wrong. *Possibly-impacted findings* are **hypotheses worth "
         "checking, not demonstrated errors**. We audited how the code routes model calls; we did not re-run "
         "experiments across providers to measure the actual delta. See `methodology.md`.\n")

L.append("## Headline numbers\n")
L.append(f"- Repos audited: **{n}** (importance-first: NeurIPS/ICML/ICLR/ACL/NAACL/Nature + "
         "UK AISI/METR/Redwood/Palisade/Anthropic-Fellows + LessWrong/AF)")
L.append(f"- Use it **safely**: **{st['safe']}**  ·  **unsafe**: **{st['unsafe']}**")
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

L.append("## The repos that use it safely (and why)\n")
for r in rows:
    if r.get("uses_safely") is True:
        why = (r.get("audit_notes") or "")[:200].replace("\n", " ")
        L.append(f"- **{r['title']}** — {why}")
L.append("")

L.append("## Full table\n")
L.append("| Repo | Venue | Safe? | Severity | Mistakes | Impacted claims |")
L.append("| --- | --- | :---: | :---: | --- | :---: |")
for r in rows:
    safe = "✅" if r.get("uses_safely") else "❌"
    mids = ", ".join(r.get("mistake_ids") or []) or "—"
    L.append(f"| {r['title'].split(' (')[0][:44]} | {(r.get('venue') or '')[:24]} | {safe} | "
             f"{r.get('severity')} | {mids} | {len(r.get('impacted_findings') or [])} |")
L.append("\nSee `survey.csv` / `survey.json` for full detail (evidence, call-site permalink, one-line fix, "
         "per-claim mechanism and confidence).\n")

(ROOT / "findings/summary.md").write_text("\n".join(L))
print(f"wrote findings/summary.md — {imp['total_findings']} findings, {verified}/{n} verified")

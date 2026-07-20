#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Merge a verify-workflow result into the survey, then regenerate CSV / stats / artifact data.

SAFETY RULE (learned the hard way): this only ever UPGRADES a row from
`impact_verified: false` -> `true`. It never overwrites an already-verified row and never
downgrades one. A failed/partial workflow run must not be able to destroy good data — a
resume whose agents died on a usage limit returned `verified: false` for rows that were
already verified, and a blanket merge would have silently thrown away 18 good rows.

Usage:
    uv run scripts/merge_verified.py <workflow-output.json>
"""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def norm(u: str | None) -> str:
    return (u or "").rstrip("/").lower()


def load_workflow_rows(p: Path) -> list[dict]:
    raw = json.loads(p.read_text())
    res = raw.get("result", raw)
    if isinstance(res, str):
        res = json.loads(res)
    return res["rows"]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out_path = Path(sys.argv[1])
    if not out_path.exists():
        print(f"error: no such file: {out_path}", file=sys.stderr)
        return 2

    new = {norm(r.get("repo_url")): r for r in load_workflow_rows(out_path)}
    survey = json.loads((ROOT / "findings/survey.json").read_text())
    rows = survey["rows"]

    upgraded, skipped_already, refused_downgrade = [], 0, []
    for r in rows:
        n = new.get(norm(r.get("repo_url")))
        if not n:
            continue
        if not n.get("verified"):
            if r.get("impact_verified"):
                refused_downgrade.append(r["title"])
            continue
        if r.get("impact_verified"):
            skipped_already += 1
            continue
        r["impacted_findings"] = n.get("impacted_findings") or []
        r["headline_impact"] = n.get("headline_impact", "")
        r["no_impact_reason"] = n.get("no_impact_reason", "")
        r["impact_verified"] = True
        upgraded.append(r["title"])

    (ROOT / "findings/survey.json").write_text(json.dumps(survey, indent=2, ensure_ascii=False))
    regenerate(rows)

    print(f"upgraded to verified : {len(upgraded)}")
    for t in upgraded:
        print(f"   + {t[:66]}")
    print(f"already verified (left alone) : {skipped_already}")
    print(f"refused to downgrade          : {len(refused_downgrade)}")
    still = sum(1 for r in rows if not r.get("impact_verified"))
    print(f"still unverified              : {still}/{len(rows)}")
    return 0


def regenerate(rows: list[dict]) -> None:
    """Rebuild survey.csv, stats.json and artifact/_data.json from survey.json."""
    disc = {norm(c["repo_url"]): c for c in json.loads((ROOT / "findings/discovered_candidates.json").read_text())}

    def importance(r: dict) -> str:
        # prefer the value stored on the row; fall back to the discovery record
        return r.get("importance") or (disc.get(norm(r.get("repo_url"))) or {}).get("importance", "")

    def flat(fs: list[dict]) -> str:
        return "\n\n".join(
            f"[{f.get('locator','')}] {f.get('finding','')}\n"
            f"    → mechanism: {f.get('mechanism','')}\n"
            f"    → severity: {f.get('severity')} | depends-on-OpenRouter: {f.get('depends_on_or')}"
            for f in fs
        )

    cols = [("title", "Title"), ("summary", "Summary"), ("importance", "Importance/Impact"),
            ("openrouter_use", "What they use OpenRouter for"), ("uses_safely", "Uses it safely"),
            ("safety_class", "Safety class"), ("safety_class_reason", "Why this safety class"),
            ("mistakes", "Mistakes (null if safe)"), ("mistake_ids", "Mistake IDs"),
            ("headline_impact", "Headline possibly-impacted claim"),
            ("impacted_findings", "Possibly-impacted findings (specific figures/claims)"),
            ("n_impacted", "# impacted findings"), ("impact_verified", "Impact analysis verified"),
            ("no_impact_reason", "Why nothing impacted"),
            ("model_type", "Model type"), ("critical_route", "Critical route"), ("severity", "Severity"),
            ("awareness", "Awareness"), ("safeguards_present", "Safeguards present"),
            ("one_line_fix", "One-line fix"), ("code_ref", "Call site (file:line)"), ("code_url", "Code URL"),
            ("repo_url", "Repo URL"), ("paper_url", "Paper URL"), ("venue", "Venue"), ("confidence", "Confidence"),
            ("provider_ab_rerun_assessment", "Provider A/B rerun assessment")]

    with (ROOT / "findings/survey.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([h for _, h in cols])
        for r in rows:
            out = []
            for k, _ in cols:
                if k == "importance":
                    v = importance(r)
                elif k == "mistakes":
                    v = "" if r.get("uses_safely") else (r.get("mistakes") or "")
                elif k == "impacted_findings":
                    v = flat(r.get("impacted_findings") or [])
                elif k == "n_impacted":
                    v = len(r.get("impacted_findings") or [])
                elif k in ("mistake_ids", "safeguards_present"):
                    v = ", ".join(r.get(k) or [])
                else:
                    v = r.get(k, "")
                out.append("TRUE" if v is True else "FALSE" if v is False else v)
            w.writerow(out)

    # stats.json is derived IN FULL from the rows. Nothing here is carried over from the
    # previous file: a hand-carried aggregate goes stale silently the moment the survey
    # changes, which is how `safe: 4` outlived the safe/unsafe framing it belonged to.
    def tally(key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in rows:
            v = r.get(key)
            if v:
                out[str(v)] = out.get(str(v), 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    mistake_freq: dict[str, int] = {}
    for r in rows:
        for mid in r.get("mistake_ids") or []:
            mistake_freq[mid] = mistake_freq.get(mid, 0) + 1

    classes = tally("safety_class")
    users = len(rows) - classes.get("no_usage_found", 0)
    at_risk = classes.get("at_risk", 0)
    # Headline denominator: repos whose OpenRouter output reaches a published result.
    # `users` (any call site anywhere) is kept as the secondary, wider figure.
    critical = sum(1 for r in rows if r.get("critical_route"))

    stats = {
        "n": len(rows),
        "critical_route": critical,
        "severity": tally("severity"),
        "model_type": tally("model_type"),
        "awareness": tally("awareness"),
        "mistake_freq": dict(sorted(mistake_freq.items(), key=lambda kv: (-kv[1], kv[0]))),
        "impacted": {
            "repos_with_impacted_findings": sum(1 for r in rows if r.get("impacted_findings")),
            "total_findings": sum(len(r.get("impacted_findings") or []) for r in rows),
            "by_severity": {s: sum(1 for r in rows for f in (r.get("impacted_findings") or [])
                                   if f.get("severity") == s) for s in ("high", "medium", "low")},
            "impact_verified_rows": sum(1 for r in rows if r.get("impact_verified")),
        },
        "safety_class": classes,
        "surveyed": len(rows),
        "actual_openrouter_users": users,
        "at_risk_pct_of_users": round(100 * at_risk / users) if users else 0,
        "at_risk_pct_of_critical_route": round(100 * at_risk / critical) if critical else 0,
    }
    (ROOT / "findings/stats.json").write_text(json.dumps(stats, indent=2))

    art = [{
        "title": r["title"], "summary": r.get("summary") or "", "importance": importance(r),
        "use": r.get("openrouter_use") or "", "safe": bool(r.get("uses_safely")),
        "mistakes": (r.get("mistakes") or "") if not r.get("uses_safely") else "",
        "mids": r.get("mistake_ids") or [], "model_type": r.get("model_type"),
        "critical": bool(r.get("critical_route")), "severity": r.get("severity"),
        "awareness": r.get("awareness"), "safeguards": r.get("safeguards_present") or [],
        "fix": r.get("one_line_fix") or "", "venue": r.get("venue"), "confidence": r.get("confidence"),
        "evidence": r.get("evidence") or "", "notes": r.get("audit_notes") or "",
        "repo": r.get("repo_url"), "paper": r.get("paper_url"),
        "code": r.get("code_url"), "code_ref": r.get("code_ref"),
        "impacted": [{"finding": f.get("finding") or "", "locator": f.get("locator") or "",
                      "mechanism": f.get("mechanism") or "", "severity": f.get("severity"),
                      "dep": f.get("depends_on_or")} for f in (r.get("impacted_findings") or [])],
        "headline_impact": r.get("headline_impact") or "",
        "no_impact": r.get("no_impact_reason") or "",
        "impact_verified": bool(r.get("impact_verified")),
        "safety_class": r.get("safety_class") or ("at_risk" if not r.get("uses_safely") else ""),
        "safety_class_reason": r.get("safety_class_reason") or "",
        "provider_ab_rerun_assessment": r.get("provider_ab_rerun_assessment") or "",
    } for r in rows]
    (ROOT / "artifact/_data.json").write_text(json.dumps(art, ensure_ascii=False))

    tmpl = (ROOT / "artifact/index_template.html").read_text()
    (ROOT / "artifact/index.html").write_text(tmpl.replace("/*__DATA__*/[]", json.dumps(art, ensure_ascii=False)))
    print("regenerated: survey.csv, stats.json, artifact/_data.json, artifact/index.html")


if __name__ == "__main__":
    raise SystemExit(main())

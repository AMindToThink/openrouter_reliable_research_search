#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Assign a precise `safety_class` to every row, then regenerate all derived files.

Why this exists: a plain `uses_safely: true` conflated three very different situations, and
reporting them together ("4 repos control for it properly") badly overstated the good news.
A repo that never routes a research call through OpenRouter has demonstrated *nothing* about
using OpenRouter well — it just isn't a data point either way.

Classes:
  at_risk             routes research calls through OpenRouter with an uncontrolled channel open
  handled             routes research calls through OpenRouter AND controls for it properly
  not_on_result_path  OpenRouter present in the repo, but not feeding any reported result
  no_usage_found      no OpenRouter call site exists at all (discovery false positive)

Only `handled` is a positive example of using OpenRouter well.
`no_usage_found` repos are excluded from the "repos that route through OpenRouter" denominator.

Rationale per row is recorded in `safety_class_reason`, sourced from the audit evidence.
"""
from __future__ import annotations
import json
from pathlib import Path

import merge_verified  # reuse regenerate() so all derived files stay in sync

ROOT = Path(__file__).resolve().parent.parent

CLASSIFY: dict[str, tuple[str, str]] = {
    "https://github.com/nostalgebraist/cot_legibility": (
        "handled",
        "Uses OpenRouter on a critical route and controls for it: pins "
        "extra_body['provider']={'only':['novita'],'allow_fallbacks':False}, logs the served provider "
        "per call (verified in the run artifacts), and runs the grader on direct OpenAI/Anthropic APIs "
        "so no judge route can be corrupted. Provider routing is itself the study's research question.",
    ),
    "https://github.com/bespokelabsai/curator": (
        "not_on_result_path",
        "Exactly one OpenRouter file exists in the repo (examples/providers/openrouter_reasoning_online.py), "
        "a single-hardcoded-problem demo. The released datasets were generated via the direct DeepSeek API. "
        "The demo is itself well-configured (pinned order, allow_fallbacks:False, require_parameters:True), "
        "but no reported result depends on OpenRouter.",
    ),
    "https://github.com/PalisadeResearch/robot_shutdown_resistance": (
        "not_on_result_path",
        "OpenRouter appears only in a superseded exploratory harness (src/initial-experiments, whose own "
        "README says it is superseded) and a pricing lookup. The headline pipeline calls xAI directly via "
        "LiteLLM (DEFAULT_MODEL='xai/grok-4-0709') with per-call provider logging.",
    ),
    "https://github.com/camel-ai/oasis": (
        "no_usage_found",
        "Shallow-cloned and grepped case-insensitively for 'openrouter' across every file: zero matches. "
        "OpenRouter is only an inherited capability of the CAMEL framework and is never invoked. All paper "
        "results run on direct OpenAI (GPT-4o-mini) or author-controlled self-hosted vLLM. A discovery "
        "false positive — not an OpenRouter user at all.",
    ),
}


def main() -> int:
    survey_path = ROOT / "findings/survey.json"
    survey = json.loads(survey_path.read_text())
    rows = survey["rows"]

    counts: dict[str, int] = {}
    for r in rows:
        url = (r.get("repo_url") or "").rstrip("/")
        if url in CLASSIFY:
            cls, reason = CLASSIFY[url]
            if r.get("uses_safely") is not True:
                raise SystemExit(
                    f"refusing to classify {url!r} as {cls!r}: the row is not marked uses_safely. "
                    "The classification table is stale — re-check the audit before running this."
                )
        elif r.get("uses_safely") is True:
            raise SystemExit(
                f"row marked safe but unclassified: {url!r} ({r['title']!r}). "
                "Add it to CLASSIFY with evidence rather than letting it default."
            )
        else:
            cls, reason = "at_risk", ""
        r["safety_class"] = cls
        r["safety_class_reason"] = reason
        counts[cls] = counts.get(cls, 0) + 1

    survey_path.write_text(json.dumps(survey, indent=2, ensure_ascii=False))

    stats_path = ROOT / "findings/stats.json"
    stats = json.loads(stats_path.read_text())
    n = len(rows)
    no_usage = counts.get("no_usage_found", 0)
    users = n - no_usage
    at_risk = counts.get("at_risk", 0)
    stats["safety_class"] = counts
    stats["surveyed"] = n
    stats["actual_openrouter_users"] = users
    stats["at_risk_pct_of_users"] = round(100 * at_risk / users) if users else 0
    stats_path.write_text(json.dumps(stats, indent=2))

    merge_verified.regenerate(rows)

    print("safety_class counts:")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"   {k:20} {v}")
    print(f"\nsurveyed: {n} | actual OpenRouter users: {users} (excludes {no_usage} with no call site)")
    print(f"at risk: {at_risk}/{users} = {stats['at_risk_pct_of_users']}% of actual users")
    print(f"genuinely handled well: {counts.get('handled', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

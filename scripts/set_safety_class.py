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


def summary_lines(counts: dict[str, int], n: int) -> list[str]:
    """Render the console summary.

    Three denominators are each defensible and they give different rates, so report all
    three together and mark the one the published headline uses. This used to print a
    single unlabelled "91% of actual users", which read as a contradiction of the README's
    97% and led a reviewer to conclude the explorer had silently reverted to the old
    framing. It had not — but one bare percentage was enough to make it look that way.

    Pure so tests/test_claims_provenance.py can pin it to findings/claims.json: console
    output is otherwise the one published surface the provenance chain does not cover.
    """
    at_risk = counts.get("at_risk", 0)
    handled = counts.get("handled", 0)
    off_path = counts.get("not_on_result_path", 0)
    no_usage = counts.get("no_usage_found", 0)

    with_call_site = n - no_usage        # an OpenRouter call site exists somewhere in the repo
    on_result_path = at_risk + handled   # its output reaches a published result

    def rate(denom: int) -> str:
        return f"{at_risk}/{denom} = {round(100 * at_risk / denom)}%" if denom else "n/a"

    out = ["safety_class counts:"]
    out += [f"   {k:20} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
    out += [
        "",
        "at-risk rate, by denominator:",
        f"   {n:>3}  repos surveyed                             {rate(n)}",
        f"   {with_call_site:>3}  contain an OpenRouter call site anywhere   {rate(with_call_site)}",
        f"   {on_result_path:>3}  put its output on a result path            {rate(on_result_path)}   <- headline",
        "",
        f"excluded from the headline denominator: {off_path} off result path, "
        f"{no_usage} with no call site",
        f"uses OpenRouter on a result path AND controls for it: {handled}",
    ]
    return out


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

    # This script owns only the per-row classification. Every aggregate — including the
    # safety_class tally — is derived from the rows by regenerate(), so there is exactly
    # one writer of stats.json and it can never disagree with the dataset.
    merge_verified.regenerate(rows)

    for line in summary_lines(counts, len(rows)):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

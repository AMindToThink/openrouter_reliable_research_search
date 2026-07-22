#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Derive every number cited in prose from the authoritative data files.

Prose (README.md, findings/summary.md, the `use-openrouter-safely` skill) quotes a lot of
statistics. Markdown has no `\\input{}`, so we cannot make prose *reference* a generated
value the way a LaTeX paper does. The next best thing, and what this script exists for:

  1. compute every cited number here, from the data, with its derivation recorded;
  2. write them to `findings/claims.json`;
  3. let `tests/test_claims_provenance.py` assert the prose still agrees.

That turns "someone hand-typed a number and it drifted" from an invisible error into a
failing test. Never hand-type a statistic into prose — add it here and cite the value.

Sources of truth:
  findings/survey.json                     the 35-repo audit dataset (one row per repo)
  findings/stats.json                      aggregates, written by merge_verified/set_safety_class
  findings/provider_spread_reference.json  live OpenRouter endpoint snapshot (87 models)

Usage:  uv run scripts/build_claims.py [--check]

    --check  recompute and exit non-zero if findings/claims.json is stale, without
             rewriting it (for CI).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FINDINGS = ROOT / "findings"
CLAIMS_PATH = FINDINGS / "claims.json"

# Quantizations at or below 8-bit. "unknown" is deliberately excluded: it is a missing
# label, not a precision claim, and counting it as low-precision would overstate the risk.
LOW_PRECISION = {"int4", "fp4", "int8", "fp8", "fp6"}
HIGH_PRECISION = {"bf16", "fp16", "fp32"}
# Parameters whose silent absence corrupts research (taxonomy M2 / M9).
WATCH_PARAMS = ["seed", "logprobs", "top_logprobs", "response_format",
                "structured_outputs", "temperature", "top_k", "min_p"]


class Claims:
    """Collects named claims with their derivation, so nothing lands undocumented."""

    def __init__(self) -> None:
        self._d: dict[str, dict[str, Any]] = {}

    def add(self, name: str, value: Any, source: str, derivation: str) -> None:
        if name in self._d:
            raise SystemExit(f"duplicate claim {name!r} — names must be unique")
        self._d[name] = {"value": value, "source": source, "derivation": derivation}

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return dict(sorted(self._d.items()))


def survey_claims(c: Claims, rows: list[dict[str, Any]], stats: dict[str, Any]) -> None:
    src = "findings/survey.json"
    n = len(rows)
    classes: dict[str, int] = {}
    for r in rows:
        cls = r.get("safety_class")
        if not cls:
            raise SystemExit(
                f"row {r.get('title')!r} has no safety_class — run scripts/set_safety_class.py first"
            )
        classes[cls] = classes.get(cls, 0) + 1

    at_risk = classes.get("at_risk", 0)
    no_usage = classes.get("no_usage_found", 0)
    users = n - no_usage

    c.add("repos_surveyed", n, src, "len(rows)")
    c.add("repos_routing_through_openrouter", users, src,
          "len(rows) - count(safety_class == 'no_usage_found')")
    c.add("repos_at_risk", at_risk, src, "count(safety_class == 'at_risk')")
    c.add("repos_handled", classes.get("handled", 0), src, "count(safety_class == 'handled')")
    c.add("repos_not_on_result_path", classes.get("not_on_result_path", 0), src,
          "count(safety_class == 'not_on_result_path')")
    c.add("repos_no_usage_found", no_usage, src, "count(safety_class == 'no_usage_found')")
    c.add("at_risk_pct_of_users", round(100 * at_risk / users) if users else 0, src,
          "round(100 * repos_at_risk / repos_routing_through_openrouter)")

    critical = sum(1 for r in rows if r.get("critical_route"))
    c.add("repos_critical_route", critical, src, "count(critical_route truthy)")

    # The headline denominator. A repo is only a meaningful data point about *using
    # OpenRouter well* if OpenRouter output reaches a published result — which is exactly
    # what critical_route records. The two partitions must coincide: every at_risk and
    # handled row is on a critical route, and every off-path / no-usage row is not. If that
    # ever stops holding, the headline is measuring something other than what it claims.
    on_path = sum(1 for r in rows if r.get("safety_class") in ("at_risk", "handled"))
    if on_path != critical:
        mismatched = [r["title"] for r in rows
                      if (r.get("safety_class") in ("at_risk", "handled"))
                      != bool(r.get("critical_route"))]
        raise SystemExit(
            f"safety_class and critical_route disagree ({on_path} on-path vs {critical} "
            f"critical): {mismatched}. The headline denominator is not trustworthy until "
            "these are reconciled."
        )
    c.add("at_risk_pct_of_critical_route", round(100 * at_risk / critical) if critical else 0,
          src, "round(100 * repos_at_risk / repos_critical_route)")
    c.add("repos_severity_high", sum(1 for r in rows if r.get("severity") == "high"), src,
          "count(severity == 'high')")
    c.add("rows_impact_verified", sum(1 for r in rows if r.get("impact_verified")), src,
          "count(impact_verified truthy)")

    findings = [f for r in rows for f in (r.get("impacted_findings") or [])]
    c.add("impacted_findings_total", len(findings), src,
          "sum(len(row.impacted_findings))")
    c.add("repos_with_impacted_findings",
          sum(1 for r in rows if r.get("impacted_findings")), src,
          "count(rows with >=1 impacted_finding)")
    for sev in ("high", "medium", "low"):
        c.add(f"impacted_findings_{sev}", sum(1 for f in findings if f.get("severity") == sev),
              src, f"count(impacted_findings with severity == {sev!r})")

    freq: dict[str, int] = {}
    for r in rows:
        for mid in r.get("mistake_ids") or []:
            freq[mid] = freq.get(mid, 0) + 1
    for mid, cnt in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
        c.add(f"mistake_{mid}_repos", cnt, src, f"count(rows whose mistake_ids contain {mid!r})")

    # Cross-check the aggregate file against the rows it claims to summarise.
    if stats.get("impacted", {}).get("total_findings") != len(findings):
        raise SystemExit(
            f"stats.json impacted.total_findings={stats.get('impacted', {}).get('total_findings')} "
            f"but survey.json has {len(findings)} — regenerate stats via scripts/set_safety_class.py"
        )


def fingerprint_claims(c: Claims, rows: list[dict[str, Any]], families: list[dict[str, Any]]) -> None:
    """Evidence-side numbers: what a reader could actually SEE in each project's own output.

    Kept separate from survey_claims because it answers a different question. survey_claims
    counts what the code leaves open; these count what the published artifacts reveal — and
    the two deliberately do not track each other. A repo can be wide open in code and show
    nothing at all, which is the entire point of the quantization-is-subtle result.
    """
    src = "findings/survey.json"
    verdicts: dict[str, int] = {}
    for r in rows:
        v = r.get("fingerprint_verdict")
        if not v:
            raise SystemExit(
                f"row {r.get('title')!r} has no fingerprint_verdict — "
                "run scripts/add_fingerprint_column.py first"
            )
        verdicts[v] = verdicts.get(v, 0) + 1

    for verdict in ("fingerprints_found", "checked_clean", "inconclusive",
                    "nothing_checkable_released"):
        c.add(f"fingerprint_{verdict}", verdicts.get(verdict, 0), src,
              f"count(fingerprint_verdict == {verdict!r})")

    # How many projects released anything a reader could check at all. This is the number
    # that carries the honest headline: the rest are unfalsifiable either way.
    checkable = len(rows) - verdicts.get("nothing_checkable_released", 0)
    c.add("fingerprint_repos_checkable", checkable, src,
          "len(rows) - count(fingerprint_verdict == 'nothing_checkable_released')")

    cat = "findings/fingerprints.json"
    c.add("fingerprint_families", len(families), cat, "len(families)")
    c.add("fingerprint_families_need_raw_outputs",
          sum(1 for f in families if f["needs_raw_outputs"]), cat,
          "count(families with needs_raw_outputs)")
    c.add("fingerprint_families_documented_catch",
          sum(1 for f in families if f["evidence_strength"] == "documented_catch"), cat,
          "count(families with evidence_strength == 'documented_catch')")


def endpoint_claims(c: Claims, models: list[dict[str, Any]]) -> None:
    src = "findings/provider_spread_reference.json"
    c.add("endpoint_models", len(models), src, "len(models)")

    counts = sorted(m["n_endpoints"] for m in models)
    c.add("endpoints_per_model_median", int(statistics.median(counts)), src,
          "median(model.n_endpoints)")
    c.add("endpoints_per_model_max", counts[-1], src, "max(model.n_endpoints)")

    def quants(m: dict[str, Any]) -> set[str]:
        return {e.get("quant") for e in m["endpoints"]}

    c.add("models_mixed_precision",
          sum(1 for m in models if quants(m) & HIGH_PRECISION and quants(m) & LOW_PRECISION),
          src, "count(models with >=1 endpoint in {bf16,fp16,fp32} AND >=1 in {int4,fp4,int8,fp8,fp6})")
    c.add("models_with_4bit_endpoint",
          sum(1 for m in models if quants(m) & {"int4", "fp4"}), src,
          "count(models with >=1 endpoint quantized int4 or fp4)")

    def varies(m: dict[str, Any], key: str) -> bool:
        vals = {e[key] for e in m["endpoints"] if e.get(key)}
        return len(vals) > 1

    c.add("models_context_varies", sum(1 for m in models if varies(m, "ctx")), src,
          "count(models with >1 distinct non-null endpoint.ctx)")
    c.add("models_max_output_varies", sum(1 for m in models if varies(m, "max_out")), src,
          "count(models with >1 distinct non-null endpoint.max_out)")

    for p in WATCH_PARAMS:
        partial = 0
        for m in models:
            sup = [p in (e.get("params") or []) for e in m["endpoints"]]
            if any(sup) and not all(sup):
                partial += 1
        c.add(f"models_partial_{p}", partial, src,
              f"count(models where {p!r} is supported by some but not all endpoints)")

    # Widest spreads, used as the worked examples in prose.
    def widest(key: str) -> tuple[str, int, int, float]:
        best: tuple[str, int, int, float] | None = None
        for m in models:
            vals = [e[key] for e in m["endpoints"] if e.get(key)]
            if len(set(vals)) < 2:
                continue
            lo, hi = min(vals), max(vals)
            ratio = hi / lo
            if best is None or ratio > best[3]:
                best = (m["model"], lo, hi, ratio)
        if best is None:
            raise SystemExit(f"no model has a spread in {key!r}")
        return best

    for key, label in (("ctx", "context"), ("max_out", "max_output")):
        model, lo, hi, ratio = widest(key)
        c.add(f"widest_{label}_model", model, src, f"argmax(max({key})/min({key})) over models")
        c.add(f"widest_{label}_min", lo, src, f"min endpoint.{key} for {model}")
        c.add(f"widest_{label}_max", hi, src, f"max endpoint.{key} for {model}")
        c.add(f"widest_{label}_ratio", round(ratio, 1), src, f"max/min of endpoint.{key} for {model}")

    # llama-3.3-70b is the worked example in the skill: it is a model the survey's repos
    # actually benchmark, and it exhibits BOTH cliffs at once. It is deliberately NOT
    # described as the worst case — `widest_*` above records the true extremes.
    llama = "meta-llama/llama-3.3-70b-instruct"
    lm = next((m for m in models if m["model"] == llama), None)
    if lm is None:
        raise SystemExit(f"{llama} missing from the endpoint snapshot — update the prose example")
    for key, label in (("ctx", "context"), ("max_out", "max_output")):
        vals = [e[key] for e in lm["endpoints"] if e.get(key)]
        c.add(f"llama33_{label}_min", min(vals), src, f"min endpoint.{key} for {llama}")
        c.add(f"llama33_{label}_max", max(vals), src, f"max endpoint.{key} for {llama}")
        c.add(f"llama33_{label}_ratio", round(max(vals) / min(vals), 1), src,
              f"max/min of endpoint.{key} for {llama}")

    # gpt-oss-120b is the worked example for partial logprobs support in the skill.
    ref = "openai/gpt-oss-120b"
    gpt = next((m for m in models if m["model"] == ref), None)
    if gpt is None:
        raise SystemExit(f"{ref} missing from the endpoint snapshot — update the prose example")
    with_lp = sum(1 for e in gpt["endpoints"] if "logprobs" in (e.get("params") or []))
    c.add("gptoss_endpoints", gpt["n_endpoints"], src, f"n_endpoints for {ref}")
    c.add("gptoss_endpoints_with_logprobs", with_lp, src,
          f"count({ref} endpoints whose params include 'logprobs')")


def build() -> dict[str, Any]:
    survey = json.loads((FINDINGS / "survey.json").read_text())
    stats = json.loads((FINDINGS / "stats.json").read_text())
    models = json.loads((FINDINGS / "provider_spread_reference.json").read_text())

    families = json.loads((FINDINGS / "fingerprints.json").read_text())["families"]

    c = Claims()
    survey_claims(c, survey["rows"], stats)
    fingerprint_claims(c, survey["rows"], families)
    endpoint_claims(c, models)
    return {
        "_README": "Generated by scripts/build_claims.py — do not edit. Every statistic cited "
                   "in prose must appear here and is enforced by tests/test_claims_provenance.py.",
        "claims": c.as_dict(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify claims.json is current; do not rewrite it")
    args = ap.parse_args()

    fresh = build()
    if args.check:
        if not CLAIMS_PATH.exists():
            print(f"error: {CLAIMS_PATH.relative_to(ROOT)} does not exist — run without --check",
                  file=sys.stderr)
            return 1
        if json.loads(CLAIMS_PATH.read_text()) != fresh:
            print(f"error: {CLAIMS_PATH.relative_to(ROOT)} is stale — "
                  "rerun `uv run scripts/build_claims.py`", file=sys.stderr)
            return 1
        print(f"{CLAIMS_PATH.relative_to(ROOT)} is current ({len(fresh['claims'])} claims)")
        return 0

    CLAIMS_PATH.write_text(json.dumps(fresh, indent=2) + "\n")
    print(f"wrote {CLAIMS_PATH.relative_to(ROOT)} — {len(fresh['claims'])} claims")
    for name, c in fresh["claims"].items():
        print(f"  {name:38} {c['value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

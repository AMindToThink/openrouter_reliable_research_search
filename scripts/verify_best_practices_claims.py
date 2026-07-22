#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Independently verify the empirical claims in reports/openrouter-best-practices.md §1-2.

That report describes "what OpenRouter actually does by default" and "the parameters that
matter." Some of those sentences are things we can check against data we hold or can fetch
ourselves (the endpoints API); others are OpenRouter's own prose about its own routing
algorithm, which no public read-only endpoint lets an outsider audit. This script draws that
line explicitly, computes what is computable, and never reports a number it did not derive
from fetched data.

Four questions, each answered from data, not from re-reading the vendor's docs:

  1. Quantization disclosure.  Across findings/provider_spread_reference.json (and a fresh
     live refetch of the full open-weight catalog, to check for drift since that snapshot),
     what fraction of endpoints report a real quantization vs "unknown"? Per model, how often
     does a research-relevant slug carry BOTH a high-precision and a <=fp8/int4 endpoint?

  2. Cheaper implies more quantized?  Within each model, rank endpoints by price and by
     precision and test the correlation directly (Spearman rank correlation, computed from
     scratch -- no scipy dependency). Report where it holds, how strongly, and where it
     inverts. If it does not hold cleanly, that is reported as a finding, not smoothed over.

  3. What varies besides precision?  Recompute context-window, max-output, and
     supported-parameter spread per model independently of scripts/build_claims.py (a second,
     from-scratch implementation against the same committed snapshot), cross-check against
     findings/claims.json (must match exactly -- same data, two implementations), and
     separately check the specific worked examples the skill quotes (llama-3.3-70b,
     openai/gpt-oss-120b) against a fresh live fetch, since the committed snapshot is a
     point-in-time capture that can drift.

  4. What can't an outsider see?  A documented list of endpoints-API schema gaps relevant to
     auditing OpenRouter's routing claims, each backed by a concrete schema observation (not
     speculation) recorded in `api_visibility_gaps` below.

Sources of truth:
  findings/provider_spread_reference.json  committed snapshot (87 open-weight models)
  artifact/endpoints.json                  the 5 models tied directly to survey repos
  findings/claims.json                     scripts/build_claims.py's own derived numbers
  live OpenRouter endpoints API            https://openrouter.ai/api/v1/models/{id}/endpoints

Usage:
    uv run scripts/verify_best_practices_claims.py            # full run incl. live refetch
    uv run scripts/verify_best_practices_claims.py --no-live  # offline: core sections only
    uv run scripts/verify_best_practices_claims.py --check    # verify the offline-reproducible
                                                                # "core" section is current;
                                                                # exits non-zero if stale. Never
                                                                # touches the network.

Output: findings/best_practices_verification.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fetch_provider_spread as fps  # sibling script; reuse its fetch/mapping, don't duplicate it

ROOT = Path(__file__).resolve().parent.parent
FINDINGS = ROOT / "findings"
SNAPSHOT_PATH = FINDINGS / "provider_spread_reference.json"
ARTIFACT_ENDPOINTS_PATH = ROOT / "artifact" / "endpoints.json"
CLAIMS_PATH = FINDINGS / "claims.json"
OUT_PATH = FINDINGS / "best_practices_verification.json"

# Quantizations at or below 8-bit. Matches scripts/build_claims.py's LOW_PRECISION exactly;
# kept as a separate literal (not imported) because build_claims.py is not meant as a library
# and duplicating a five-item set is cheaper than coupling two independently-runnable scripts.
# The offline cross-check in spread_recompute() below will catch the two ever disagreeing.
LOW_PRECISION = {"int4", "fp4", "int8", "fp8", "fp6"}
HIGH_PRECISION = {"bf16", "fp16", "fp32"}

# Ordinal precision rank used for the price-vs-precision correlation. Lower = more quantized.
# "unknown" is deliberately absent: it is a missing label, not a precision claim, so it cannot
# be placed on this scale (see quant_disclosure_stats -- this is the same reasoning
# build_claims.py uses to exclude "unknown" from LOW_PRECISION).
PRECISION_RANK: dict[str, int] = {
    "int4": 0, "fp4": 0,
    "fp6": 1,
    "int8": 2, "fp8": 2,
    "fp16": 3, "bf16": 3,
    "fp32": 4,
}

WATCH_PARAMS = ["seed", "logprobs", "top_logprobs", "response_format",
                "structured_outputs", "temperature", "top_k", "min_p"]

# Concrete, schema-verified gaps in what the public endpoints API exposes. Each entry is
# something we tried to find in the actual JSON payload (see the "evidence" field) rather
# than something assumed. This is the answer to task item 4: it is a finding in its own
# right, not filler -- routing behaviour that cannot be audited from outside is the argument
# for pinning (§3a) and provenance logging (§4) in the report this script is checking.
API_VISIBILITY_GAPS: list[dict[str, str]] = [
    {
        "gap": "Which endpoint served any specific past request",
        "why_it_matters": "Cannot audit whether load-balancing actually behaved as documented "
                           "for a call you did not make yourself.",
        "evidence": "GET /api/v1/models/{author}/{slug}/endpoints returns the current candidate "
                     "endpoint list only -- no request history. OpenRouter's separate "
                     "GET /api/v1/generation?id=... exposes the provider for ONE response, but "
                     "only if you already possess that response's generation id, i.e. only for "
                     "calls you made yourself with an API key. There is no bulk or third-party "
                     "view of what actually got routed where.",
    },
    {
        "gap": "Real-time selection weight / actual traffic share per endpoint",
        "why_it_matters": "OpenRouter's docs describe sampling 'weighted by the inverse square "
                           "of price,' but this is a claim about an internal algorithm with no "
                           "corresponding read-only field to check it against.",
        "evidence": "The endpoint object has no weight/probability/traffic-share field. The "
                     "closest fields (uptime_last_1d/30m/5m) measure endpoint HEALTH "
                     "(did it error recently), not how often OpenRouter's router actually "
                     "selects it relative to its siblings.",
    },
    {
        "gap": "Whether a listed endpoint is receiving any traffic at all",
        "why_it_matters": "A stale or dead endpoint could sit in the list looking like a live "
                           "routing option.",
        "evidence": "latency_last_30m and throughput_last_30m are both present as schema fields "
                     "but were observed null on every sampled endpoint in this run (see "
                     "'schema_fields_observed_null' in the output) -- the fields nominally meant "
                     "to answer this are not populated in practice for the endpoints checked.",
    },
    {
        "gap": "Per-endpoint data-retention / training policy",
        "why_it_matters": "The report's `data_collection` guidance (§2) is about which "
                           "providers may retain prompts to train on; an auditor would want to "
                           "check that per endpoint the same way quantization is checked.",
        "evidence": "No data_collection/training/retention key exists anywhere in the raw "
                     "endpoint JSON (checked by inspecting the full payload for "
                     "openai/gpt-oss-120b's endpoints -- see keys enumerated in "
                     "'raw_endpoint_schema_keys'). That policy lives only in OpenRouter's "
                     "prose provider-comparison pages, not in any field this script can diff.",
    },
    {
        "gap": "Whether the declared quantization is actually what is being served",
        "why_it_matters": "'quantization': 'bf16' is a label the PROVIDER supplies to "
                           "OpenRouter; nothing in this API independently verifies it against "
                           "the running weights.",
        "evidence": "No verification/attestation field exists alongside 'quantization'. "
                     "Confirming a provider's self-report would require sampled generations "
                     "compared against a trusted reference (the kind of two-sample test 'Model "
                     "Equality Testing', ICLR 2025, ran; 11/31 endpoints in that paper served "
                     "different weights than advertised) -- out of reach of a metadata-only API.",
    },
    {
        "gap": "Change history of the endpoint list itself",
        "why_it_matters": "Knowing when an endpoint was added, removed, or requantized would "
                           "let you correlate a result change with a routing change.",
        "evidence": "The API returns only the current endpoint list, with no last-changed "
                     "timestamp or diff/changelog endpoint. The drift this script measures "
                     "(committed snapshot vs a fresh fetch) exists only because we took two "
                     "independent snapshots ourselves and diffed them -- OpenRouter does not "
                     "provide that comparison.",
    },
]


def load_snapshot() -> list[dict[str, Any]]:
    if not SNAPSHOT_PATH.exists():
        raise SystemExit(f"{SNAPSHOT_PATH} missing -- run scripts/fetch_provider_spread.py first")
    return json.loads(SNAPSHOT_PATH.read_text())


def load_artifact_models() -> list[dict[str, Any]]:
    if not ARTIFACT_ENDPOINTS_PATH.exists():
        raise SystemExit(f"{ARTIFACT_ENDPOINTS_PATH} missing -- run scripts/fetch_endpoints.py first")
    return json.loads(ARTIFACT_ENDPOINTS_PATH.read_text())["models"]


# --- 1. Quantization disclosure -----------------------------------------------------

def quant_disclosure_stats(models: list[dict[str, Any]]) -> dict[str, Any]:
    total_endpoints = 0
    unknown_endpoints = 0
    histogram: dict[str, int] = {}
    n_all_unknown = 0
    n_no_unknown = 0
    n_some_unknown = 0
    n_mixed_precision = 0

    for m in models:
        eps = m["endpoints"]
        quants_here = [e["quant"] for e in eps]
        for q in quants_here:
            total_endpoints += 1
            histogram[q] = histogram.get(q, 0) + 1
            if q == "unknown":
                unknown_endpoints += 1

        distinct = set(quants_here)
        n_unknown_here = sum(1 for q in quants_here if q == "unknown")
        if n_unknown_here == len(quants_here):
            n_all_unknown += 1
        elif n_unknown_here == 0:
            n_no_unknown += 1
        else:
            n_some_unknown += 1
        if (distinct & HIGH_PRECISION) and (distinct & LOW_PRECISION):
            n_mixed_precision += 1

    if total_endpoints == 0:
        raise SystemExit("quant_disclosure_stats: no endpoints in snapshot -- refusing to divide by zero")

    return {
        "n_models": len(models),
        "n_endpoints": total_endpoints,
        "unknown_endpoints": unknown_endpoints,
        "real_quant_endpoints": total_endpoints - unknown_endpoints,
        "pct_unknown": round(100 * unknown_endpoints / total_endpoints, 1),
        "quant_histogram": dict(sorted(histogram.items(), key=lambda kv: (-kv[1], kv[0]))),
        "n_models_all_endpoints_unknown": n_all_unknown,
        "n_models_no_unknown_endpoint": n_no_unknown,
        "n_models_some_unknown_endpoint": n_some_unknown,
        "n_models_mixed_precision": n_mixed_precision,
        "n_models_with_4bit_endpoint": sum(
            1 for m in models if {e["quant"] for e in m["endpoints"]} & {"int4", "fp4"}
        ),
    }


def research_relevant_slug_stats(artifact_models: list[dict[str, Any]]) -> dict[str, Any]:
    """The 5 models actually tied to survey repos in artifact/endpoints.json, checked the same
    way -- these are the slugs research in this survey actually depends on, as opposed to the
    broader 87-model catalog sweep."""
    out: dict[str, Any] = {}
    for m in artifact_models:
        quants = {e["quant"] for e in m["endpoints"]}
        n_unknown = sum(1 for e in m["endpoints"] if e["quant"] == "unknown")
        out[m["id"]] = {
            "why": m["why"],
            "n_endpoints": len(m["endpoints"]),
            "distinct_quants": sorted(quants),
            "n_unknown_endpoints": n_unknown,
            "has_both_high_and_low_precision": bool((quants & HIGH_PRECISION) and (quants & LOW_PRECISION)),
        }
    return out


# --- 2. Cheaper implies more quantized? ---------------------------------------------

def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation, average-rank tie handling. No scipy dependency (matches this
    project's dependencies=[] convention for scripts). Returns None if either series is constant
    (undefined correlation)."""
    n = len(xs)

    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg_rank
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denx = sum((a - mx) ** 2 for a in rx)
    deny = sum((b - my) ** 2 for b in ry)
    if denx == 0 or deny == 0:
        return None
    return num / (denx * deny) ** 0.5


def price_vs_precision(models: list[dict[str, Any]], price_key: str) -> dict[str, Any]:
    """Within each model, does a lower price predict a lower (more-quantized) precision rank?
    Restricted to endpoints with a disclosed (non-'unknown') quantization and a real price --
    'unknown' cannot be placed on the precision scale (see PRECISION_RANK), and endpoints with
    no price are not comparable."""
    n_no_spread = 0
    rhos: list[tuple[str, float]] = []
    cheapest_checked = 0
    cheapest_is_most_quantized = 0

    for m in models:
        eps = [e for e in m["endpoints"] if e["quant"] != "unknown" and e.get(price_key) is not None]
        if len(eps) < 2:
            n_no_spread += 1
            continue
        prices = [e[price_key] for e in eps]
        precs = [PRECISION_RANK[e["quant"]] for e in eps]
        if len(set(prices)) < 2 or len(set(precs)) < 2:
            n_no_spread += 1
            continue

        rho = _spearman(prices, precs)
        if rho is not None:
            rhos.append((m["model"], rho))

        cheapest_checked += 1
        min_price = min(prices)
        precs_at_min_price = [precs[i] for i, p in enumerate(prices) if p == min_price]
        if min(precs_at_min_price) == min(precs):
            cheapest_is_most_quantized += 1

    n_considered = len(rhos)
    values = [r for _, r in rhos]
    n_pos = sum(1 for r in values if r > 0.01)
    n_neg = sum(1 for r in values if r < -0.01)
    n_zero = n_considered - n_pos - n_neg
    violations = sorted([{"model": mid, "rho": round(r, 3)} for mid, r in rhos if r < -0.01],
                         key=lambda d: d["rho"])

    return {
        "price_field": price_key,
        "n_models_total": len(models),
        "n_models_no_usable_price_precision_spread": n_no_spread,
        "n_models_considered": n_considered,
        "n_models_positive_correlation": n_pos,
        "n_models_negative_correlation": n_neg,
        "n_models_near_zero_correlation": n_zero,
        "pct_models_positive": round(100 * n_pos / n_considered, 1) if n_considered else None,
        "mean_spearman_rho": round(statistics.mean(values), 3) if values else None,
        "median_spearman_rho": round(statistics.median(values), 3) if values else None,
        "cheapest_endpoint_is_most_quantized": cheapest_is_most_quantized,
        "cheapest_endpoint_checked": cheapest_checked,
        "pct_cheapest_is_most_quantized": (
            round(100 * cheapest_is_most_quantized / cheapest_checked, 1) if cheapest_checked else None
        ),
        "negative_correlation_models": violations,
        "interpretation": (
            "positive rho means higher price predicts higher (less-quantized) precision -- i.e. "
            "the report's 'cheaper endpoints are favored, and cheaper is more quantized' premise "
            "holds directionally for that model. A model with no usable spread (all endpoints "
            "the same disclosed precision, all unknown, or a single price) cannot support or "
            "refute the claim at all and is excluded from n_models_considered."
        ),
    }


# --- 3. Context / max-output / parameter spread, recomputed independently -----------

def _varies(models: list[dict[str, Any]], key: str) -> int:
    return sum(1 for m in models if len({e[key] for e in m["endpoints"] if e.get(key)}) > 1)


def _widest(models: list[dict[str, Any]], key: str) -> dict[str, Any]:
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
        raise SystemExit(f"_widest: no model has a spread in {key!r}")
    model, lo, hi, ratio = best
    return {"model": model, "min": lo, "max": hi, "ratio": round(ratio, 1)}


def spread_recompute(models: list[dict[str, Any]]) -> dict[str, Any]:
    """A second, from-scratch implementation of the numbers scripts/build_claims.py derives
    from the same committed snapshot. If this disagrees with findings/claims.json, either this
    script or build_claims.py has a bug -- see cross_check_against_claims() below, which raises
    loudly on any mismatch rather than reporting two different numbers as if that were fine."""
    partial_params: dict[str, int] = {}
    for p in WATCH_PARAMS:
        count = 0
        for m in models:
            supported = [p in (e.get("params") or []) for e in m["endpoints"]]
            if any(supported) and not all(supported):
                count += 1
        partial_params[p] = count

    counts = sorted(m["n_endpoints"] for m in models)

    llama = "meta-llama/llama-3.3-70b-instruct"
    lm = next((m for m in models if m["model"] == llama), None)
    if lm is None:
        raise SystemExit(f"{llama} missing from the snapshot -- the skill's worked example can't be checked")
    llama_stats = {}
    for key, label in (("ctx", "context"), ("max_out", "max_output")):
        vals = [e[key] for e in lm["endpoints"] if e.get(key)]
        llama_stats[label] = {"min": min(vals), "max": max(vals), "ratio": round(max(vals) / min(vals), 1)}

    gptoss = "openai/gpt-oss-120b"
    gm = next((m for m in models if m["model"] == gptoss), None)
    if gm is None:
        raise SystemExit(f"{gptoss} missing from the snapshot -- the skill's worked example can't be checked")
    gptoss_stats = {
        "n_endpoints": gm["n_endpoints"],
        "n_with_logprobs": sum(1 for e in gm["endpoints"] if "logprobs" in (e.get("params") or [])),
    }

    return {
        "endpoints_per_model_median": int(statistics.median(counts)),
        "endpoints_per_model_max": counts[-1],
        "models_context_varies": _varies(models, "ctx"),
        "models_max_output_varies": _varies(models, "max_out"),
        "widest_context": _widest(models, "ctx"),
        "widest_max_output": _widest(models, "max_out"),
        "llama33_worked_example": llama_stats,
        "gptoss_worked_example": gptoss_stats,
        "models_partial_param_support": partial_params,
    }


def cross_check_against_claims(recomputed: dict[str, Any]) -> list[str]:
    """Compare the from-scratch recompute above against findings/claims.json. Both read the
    same committed snapshot, so any mismatch is a real bug (in this script or in
    build_claims.py), not a data disagreement -- reported here as a list of mismatches instead
    of silently trusting either file."""
    if not CLAIMS_PATH.exists():
        raise SystemExit(f"{CLAIMS_PATH} missing -- run scripts/build_claims.py first")
    claims = {k: v["value"] for k, v in json.loads(CLAIMS_PATH.read_text())["claims"].items()}

    checks: list[tuple[str, Any, Any]] = [
        ("endpoints_per_model_median", recomputed["endpoints_per_model_median"], claims["endpoints_per_model_median"]),
        ("endpoints_per_model_max", recomputed["endpoints_per_model_max"], claims["endpoints_per_model_max"]),
        ("models_context_varies", recomputed["models_context_varies"], claims["models_context_varies"]),
        ("models_max_output_varies", recomputed["models_max_output_varies"], claims["models_max_output_varies"]),
        ("widest_context_model", recomputed["widest_context"]["model"], claims["widest_context_model"]),
        ("widest_context_ratio", recomputed["widest_context"]["ratio"], claims["widest_context_ratio"]),
        ("widest_max_output_model", recomputed["widest_max_output"]["model"], claims["widest_max_output_model"]),
        ("widest_max_output_ratio", recomputed["widest_max_output"]["ratio"], claims["widest_max_output_ratio"]),
        ("llama33_context_ratio", recomputed["llama33_worked_example"]["context"]["ratio"], claims["llama33_context_ratio"]),
        ("llama33_max_output_ratio", recomputed["llama33_worked_example"]["max_output"]["ratio"], claims["llama33_max_output_ratio"]),
        ("gptoss_endpoints", recomputed["gptoss_worked_example"]["n_endpoints"], claims["gptoss_endpoints"]),
        ("gptoss_endpoints_with_logprobs", recomputed["gptoss_worked_example"]["n_with_logprobs"], claims["gptoss_endpoints_with_logprobs"]),
    ]
    for p in WATCH_PARAMS:
        checks.append((f"models_partial_{p}", recomputed["models_partial_param_support"][p], claims[f"models_partial_{p}"]))

    mismatches = [f"{name}: this script={ours!r} vs claims.json={theirs!r}"
                  for name, ours, theirs in checks if ours != theirs]
    if mismatches:
        raise SystemExit(
            "spread_recompute disagrees with findings/claims.json on data both read from the "
            "same committed snapshot -- this is a bug, not a data change:\n  " + "\n  ".join(mismatches)
        )
    return [name for name, _, _ in checks]


# --- live drift check -----------------------------------------------------------------

def live_drift_check(committed: list[dict[str, Any]], limit: int | None) -> dict[str, Any]:
    """Refetch the open-weight catalog live and compare against the committed snapshot. Uses
    fetch_provider_spread.fetch_spread() directly so the mapping is identical to what produced
    the committed file -- any difference is real drift (or a live API classification quirk),
    not a second, subtly different implementation."""
    live = fps.fetch_spread(limit=limit)

    committed_ids = {m["model"] for m in committed}
    live_ids = {m["model"] for m in live}

    # A model can be "dropped" for two very different reasons: (a) genuinely gone from
    # OpenRouter's catalog, or (b) still in the catalog but now excluded by
    # fetch_provider_spread.is_open_weight()'s author-prefix classification. Those are not the
    # same finding, so distinguish them by checking today's full catalog directly rather than
    # assuming "not in the live open-weight sweep" means "not in OpenRouter's catalog."
    catalog = fps.get(fps.MODELS_API)
    if catalog is None:
        raise SystemExit("could not fetch the model catalog for the drop-reason check")
    all_catalog_ids = {m["id"] for m in catalog.get("data", [])}

    dropped = sorted(committed_ids - live_ids)
    dropped_detail = [
        {
            "model": mid,
            "still_in_catalog": mid in all_catalog_ids,
            "reclassified_as_proprietary": mid in all_catalog_ids and not fps.is_open_weight(mid),
        }
        for mid in dropped
    ]
    added = sorted(live_ids - committed_ids)

    live_quant = quant_disclosure_stats(live)
    committed_quant = quant_disclosure_stats([m for m in committed if m["model"] in live_ids or True])
    # (committed_quant intentionally recomputed over the FULL committed set for an apples-to-
    # apples "whole snapshot then vs whole snapshot now" comparison; the model-set overlap is
    # reported separately via dropped/added above.)

    live_ctx_varies = _varies(live, "ctx")
    live_maxout_varies = _varies(live, "max_out")

    def worked_example(model_id: str) -> dict[str, Any] | None:
        lm = next((m for m in live if m["model"] == model_id), None)
        if lm is None:
            return None
        out: dict[str, Any] = {"n_endpoints": lm["n_endpoints"]}
        for key, label in (("ctx", "context"), ("max_out", "max_output")):
            vals = [e[key] for e in lm["endpoints"] if e.get(key)]
            if vals:
                out[label] = {"min": min(vals), "max": max(vals), "ratio": round(max(vals) / min(vals), 1)}
        out["n_with_logprobs"] = sum(1 for e in lm["endpoints"] if "logprobs" in (e.get("params") or []))
        return out

    return {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sample_limit": limit,
        "n_models_live": len(live),
        "n_models_committed": len(committed),
        "models_dropped_since_snapshot": dropped_detail,
        "models_added_since_snapshot": added,
        "quant_disclosure_committed": committed_quant,
        "quant_disclosure_live": live_quant,
        "pct_unknown_delta": round(live_quant["pct_unknown"] - committed_quant["pct_unknown"], 1),
        "models_context_varies_live": live_ctx_varies,
        "models_max_output_varies_live": live_maxout_varies,
        "worked_examples_live": {
            "meta-llama/llama-3.3-70b-instruct": worked_example("meta-llama/llama-3.3-70b-instruct"),
            "openai/gpt-oss-120b": worked_example("openai/gpt-oss-120b"),
        },
    }


def schema_probe() -> dict[str, Any]:
    """Fetch one live endpoint payload and record its exact top-level keys, so
    API_VISIBILITY_GAPS's evidence claims about missing fields are checked against a real
    response every run rather than remembered from a one-off inspection."""
    payload = fps.get(fps.ENDPOINTS_API.format("openai/gpt-oss-120b"))
    if payload is None:
        raise SystemExit("could not fetch a live endpoint payload for the schema probe")
    endpoints = (payload.get("data") or {}).get("endpoints") or []
    if not endpoints:
        raise SystemExit("schema probe got an empty endpoint list -- nothing to inspect")
    keys = sorted(endpoints[0].keys())
    null_fields = sorted({
        k for e in endpoints for k, v in e.items()
        if v is None and k in ("latency_last_30m", "throughput_last_30m")
    })
    return {
        "probed_model": "openai/gpt-oss-120b",
        "raw_endpoint_schema_keys": keys,
        "schema_fields_observed_null": null_fields,
        "fields_confirmed_absent": [
            f for f in ("data_collection", "training", "retention", "selection_weight",
                        "traffic_share", "served_request_count", "quantization_verified")
            if f not in keys
        ],
    }


# --- assembly ---------------------------------------------------------------------

def build_core() -> dict[str, Any]:
    """Everything reproducible from committed files alone -- no network. This is the section
    --check validates."""
    models = load_snapshot()
    artifact_models = load_artifact_models()

    recomputed = spread_recompute(models)
    checked_against_claims = cross_check_against_claims(recomputed)

    return {
        "quant_disclosure": quant_disclosure_stats(models),
        "research_relevant_slugs": research_relevant_slug_stats(artifact_models),
        "price_vs_precision_by_prompt_price": price_vs_precision(models, "in_per_m"),
        "price_vs_precision_by_completion_price": price_vs_precision(models, "out_per_m"),
        "spread_recompute": recomputed,
        "spread_recompute_cross_checked_fields": checked_against_claims,
    }


def build_full(no_live: bool, sample_limit: int | None) -> dict[str, Any]:
    core = build_core()
    models = load_snapshot()
    out: dict[str, Any] = {
        "_README": "Generated by scripts/verify_best_practices_claims.py -- do not edit. "
                   "Verifies the §1/§2 empirical claims in reports/openrouter-best-practices.md "
                   "against data we hold or fetched ourselves. See tests/test_verify_best_practices_claims.py.",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "core": core,
        "api_visibility_gaps": API_VISIBILITY_GAPS,
    }
    if no_live:
        out["live_drift_check"] = None
        out["schema_probe"] = None
    else:
        out["live_drift_check"] = live_drift_check(models, sample_limit)
        out["schema_probe"] = schema_probe()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-live", action="store_true",
                    help="skip the live refetch/schema probe; write only the offline-reproducible core")
    ap.add_argument("--sample-limit", type=int, default=None,
                    help="limit the live refetch to the first N open-weight models (default: all)")
    ap.add_argument("--check", action="store_true",
                    help="recompute the offline 'core' section and exit non-zero if the committed "
                         "output file is stale on that section. Never touches the network.")
    args = ap.parse_args()

    if args.check:
        core = build_core()
        if not OUT_PATH.exists():
            print(f"error: {OUT_PATH.relative_to(ROOT)} does not exist -- run without --check", file=sys.stderr)
            return 1
        committed = json.loads(OUT_PATH.read_text())
        if committed.get("core") != core:
            print(f"error: {OUT_PATH.relative_to(ROOT)} 'core' section is stale -- "
                  "rerun `uv run scripts/verify_best_practices_claims.py`", file=sys.stderr)
            return 1
        print(f"{OUT_PATH.relative_to(ROOT)} core section is current")
        return 0

    result = build_full(no_live=args.no_live, sample_limit=args.sample_limit)
    OUT_PATH.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {OUT_PATH.relative_to(ROOT)}")
    qd = result["core"]["quant_disclosure"]
    print(f"  quantization: {qd['unknown_endpoints']}/{qd['n_endpoints']} endpoints unknown "
          f"({qd['pct_unknown']}%); {qd['n_models_mixed_precision']}/{qd['n_models']} models "
          f"mix high+low precision")
    pvp = result["core"]["price_vs_precision_by_prompt_price"]
    print(f"  price-vs-precision: positive in {pvp['n_models_positive_correlation']}/"
          f"{pvp['n_models_considered']} testable models (median rho={pvp['median_spearman_rho']}); "
          f"{pvp['n_models_no_usable_price_precision_spread']} models had no usable spread at all")
    if not args.no_live:
        drift = result["live_drift_check"]
        print(f"  live drift: {len(drift['models_dropped_since_snapshot'])} dropped, "
              f"{len(drift['models_added_since_snapshot'])} added since the committed snapshot; "
              f"unknown-rate moved {drift['pct_unknown_delta']:+.1f}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

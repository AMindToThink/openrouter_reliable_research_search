#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regenerate findings/provider_spread_reference.json from OpenRouter's live API.

This is the provenance for the endpoint statistics quoted throughout the project (the
skill's evidence table, the A/B experiment plan's quality-cliff table). Until this script
existed the snapshot was committed data with no way to reproduce it.

What it collects, per open-weight model: every serving endpoint, its self-reported
quantization, context window, max output tokens, price, uptime, and the exact list of
sampling/format parameters that endpoint honours. That last field is what makes taxonomy
M2 (silent parameter dropping) measurable rather than theoretical.

    GET https://openrouter.ai/api/v1/models                      (public, no auth)
    GET https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints

Proprietary models are excluded: they are effectively single-served, so provider spread is
not a meaningful risk for them (see findings/taxonomy.md, "model-risk axis").

⚠️  REGENERATING MOVES PUBLISHED NUMBERS. Endpoints rotate constantly — providers appear,
    drop, and requantize. A fresh fetch will not reproduce the committed snapshot, and the
    statistics derived from it are quoted in prose. After regenerating you MUST run:

        uv run scripts/build_claims.py
        uv run --with pytest pytest tests/

    and update any prose the tests flag. Treat a regeneration as a data change to be
    reviewed, not a routine refresh.

Usage:
    uv run scripts/fetch_provider_spread.py                 # rewrite the canonical snapshot
    uv run scripts/fetch_provider_spread.py -o /tmp/x.json  # write elsewhere (safe to try)
    uv run scripts/fetch_provider_spread.py --limit 5       # smoke-test against a few models
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "findings" / "provider_spread_reference.json"
MODELS_API = "https://openrouter.ai/api/v1/models"
ENDPOINTS_API = "https://openrouter.ai/api/v1/models/{}/endpoints"

# Authors whose models are served by a single first-party backend. Provider spread is not a
# meaningful risk for these, and including them would dilute the prevalence statistics.
PROPRIETARY_AUTHORS = {"openai", "anthropic", "google", "x-ai", "perplexity", "cohere",
                       "amazon", "microsoft", "inflection", "ai21"}
# ...except open-weight releases from those authors, which ARE multi-served.
OPEN_WEIGHT_EXCEPTIONS = {"openai/gpt-oss-120b", "openai/gpt-oss-20b"}
# Whole open-weight families from otherwise-proprietary authors. Without this, every
# `google/gemma-*` model silently drops out of the sweep even though it is open-weight and
# multi-served — four of them are in the committed snapshot and would have vanished on the
# next refresh, quietly shrinking the denominator rather than failing.
OPEN_WEIGHT_PREFIXES = ("google/gemma-",)


def get(url: str, timeout: int = 30) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"  !! {url}: {e}", file=sys.stderr)
        return None


def is_open_weight(model_id: str) -> bool:
    if model_id in OPEN_WEIGHT_EXCEPTIONS:
        return True
    if model_id.lower().startswith(OPEN_WEIGHT_PREFIXES):
        return True
    return model_id.split("/", 1)[0].lower() not in PROPRIETARY_AUTHORS


def price_per_m(pricing: dict[str, Any] | None, key: str) -> float | None:
    """OpenRouter quotes $/token; the snapshot stores $/1M tokens."""
    try:
        return round(float(pricing[key]) * 1e6, 6)  # type: ignore[index]
    except (KeyError, TypeError, ValueError):
        return None


def endpoint_record(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_name": e.get("provider_name"),
        "provider_slug": (e.get("tag") or "").split("/")[0] or None,
        "endpoint_tag": e.get("tag"),
        "quant": e.get("quantization") or "unknown",
        "ctx": e.get("context_length"),
        "max_out": e.get("max_completion_tokens"),
        "max_prompt": e.get("max_prompt_tokens"),
        "in_per_m": price_per_m(e.get("pricing"), "prompt"),
        "out_per_m": price_per_m(e.get("pricing"), "completion"),
        # 1-day uptime, matching the committed snapshot. Not 30m: a half-hour window is too
        # noisy to judge whether an endpoint is dependable enough to pin a study to.
        "uptime_1d": (round(u, 1) if isinstance(u := e.get("uptime_last_1d"), (int, float)) else None),
        "params": sorted(e.get("supported_parameters") or []),
    }


def fetch_spread(limit: int | None = None) -> list[dict[str, Any]]:
    catalog = get(MODELS_API)
    if catalog is None:
        raise SystemExit("could not fetch the model catalog — aborting rather than writing a partial snapshot")

    ids = sorted({m["id"] for m in catalog.get("data", []) if is_open_weight(m["id"])})
    if limit is not None:
        ids = ids[:limit]
    print(f"{len(ids)} open-weight models to query", file=sys.stderr)

    out: list[dict[str, Any]] = []
    for i, model_id in enumerate(ids, 1):
        payload = get(ENDPOINTS_API.format(model_id))
        data = (payload or {}).get("data") or {}
        eps = [endpoint_record(e) for e in data.get("endpoints", [])]
        # A model served by one endpoint has no spread to measure; excluding it keeps the
        # denominator honest ("of the models that have a choice, how many vary?").
        if len(eps) < 2:
            continue
        # Only observed data is stored. Aggregates (quantization spread, price range,
        # parameter coverage) are derived in scripts/build_claims.py, never persisted here:
        # a derived value baked into a snapshot drifts from the rows it summarises and
        # nothing catches it. The retired `quant_spread` field did exactly that — it
        # disagreed with its own endpoint list for 78 of 87 models.
        out.append({
            "model": model_id,
            "n_endpoints": len(eps),
            "endpoints": eps,
        })
        print(f"  [{i}/{len(ids)}] {model_id:<50} {len(eps):>3} endpoints", file=sys.stderr)

    if not out:
        raise SystemExit("no multi-endpoint models found — refusing to write an empty snapshot")
    return sorted(out, key=lambda m: m["model"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT,
                    help="output path (default: the canonical snapshot)")
    ap.add_argument("--limit", type=int, default=None,
                    help="only query the first N models (smoke test)")
    args = ap.parse_args()

    spread = fetch_spread(args.limit)
    args.out.write_text(json.dumps(spread, indent=1) + "\n")
    total = sum(m["n_endpoints"] for m in spread)
    print(f"\nwrote {args.out} — {len(spread)} models, {total} endpoints")
    if args.out == DEFAULT_OUT:
        print("the canonical snapshot changed: rerun scripts/build_claims.py and the test suite,\n"
              "then update any prose the tests flag.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

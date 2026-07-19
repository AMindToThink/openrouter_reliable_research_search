#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Fetch REAL provider/endpoint data from OpenRouter's public API.

This replaces the invented provider<->quantization pairings that the Routing Roulette
widget originally used. Everything here is fetched live from:

    GET https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints   (no auth required)

Models are chosen to tie back to repos in the survey, so the demo shows the real
provider spread for models that real research actually ran through OpenRouter.

Run:  uv run scripts/fetch_endpoints.py
Out:  artifact/endpoints.json
"""
from __future__ import annotations
import json, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://openrouter.ai/api/v1/models/{}/endpoints"

# model -> which surveyed repo used it (for the "why this model" line in the UI)
MODELS = {
    "openai/gpt-oss-120b": "LLM judge in kmerkelbach/llm-request-tone; ai-psychosis used the 20b sibling",
    "meta-llama/llama-3.3-70b-instruct": "benchmarked model in GoodStartLabs/AI_Diplomacy",
    "google/gemma-3-27b-it": "teacher model in ArthurConmy/hereditary",
    "mistralai/mistral-small-3.2-24b-instruct": "ablation model in GoodStartLabs/AI_Diplomacy",
    "deepseek/deepseek-r1": "the model in nostalgebraist/cot_legibility",
}

# parameters whose silent absence corrupts research (taxonomy M2 / M9)
WATCH = ["seed", "response_format", "structured_outputs", "temperature", "top_p", "logprobs", "tools"]


def fetch(model: str) -> dict | None:
    req = urllib.request.Request(API.format(model), headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["data"]
    except (urllib.error.URLError, KeyError, TimeoutError) as e:
        print(f"  !! {model}: {e}")
        return None


def main() -> int:
    out = {"fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "source": "https://openrouter.ai/api/v1/models/{id}/endpoints (public, no auth)",
           "models": []}
    for model, why in MODELS.items():
        d = fetch(model)
        if d is None:
            continue
        eps = []
        for e in d.get("endpoints", []):
            sp = set(e.get("supported_parameters") or [])
            try:
                price = float(e["pricing"]["prompt"])
            except (KeyError, TypeError, ValueError):
                price = 0.0
            eps.append({
                "provider": e.get("provider_name", "?"),
                "tag": e.get("tag", ""),
                "quant": e.get("quantization") or "unknown",
                "ctx": e.get("context_length") or 0,
                "price_in": price * 1e6,               # $ per 1M prompt tokens
                "supports": {p: (p in sp) for p in WATCH},
            })
        if not eps:
            continue
        out["models"].append({"id": d["id"], "name": d.get("name", d["id"]), "why": why, "endpoints": eps})
        quants = sorted({e["quant"] for e in eps})
        print(f"  {d['id']:<44} {len(eps):>3} endpoints  quant={','.join(quants)}")

    dest = ROOT / "artifact/endpoints.json"
    dest.write_text(json.dumps(out, indent=2))
    total = sum(len(m["endpoints"]) for m in out["models"])
    print(f"\nwrote {dest.relative_to(ROOT)} — {len(out['models'])} models, {total} real endpoints, at {out['fetched_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

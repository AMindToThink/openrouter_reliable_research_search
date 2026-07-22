#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regenerate findings/provider_transparency_sources.json — the evidence behind the audit.

Two jobs, both of which exist so that reports/provider-transparency.md cannot contain a
number or a quotation that nobody checked:

  1. **Snapshot the cited pages.** Every entry in findings/provider_transparency.json marked
     `verified: true` has its URL fetched and reduced to plain text, and each of its quotes
     is looked for verbatim in that text. A quote that cannot be located is recorded as
     unconfirmed, and the generator labels it as such in the report rather than dropping it
     silently. This is the same rule findings/prior_work_sources.json enforces for citations.

  2. **Measure the declaration rate.** For a fixed sample of widely-served open-weight
     models, count how many serving endpoints declare a real quantization to OpenRouter and
     how many say "unknown". This is the one number in the report that is ours rather than a
     vendor's, and it is the reason the report can say providers are opaque without relying
     on any provider's own account of itself.

     GET https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints    (public, no auth)

⚠️  REGENERATING MOVES PUBLISHED NUMBERS. Endpoints rotate constantly and vendor docs get
    rewritten; a page that quoted cleanly last month may not today. A fetch that turns a
    confirmed quote unconfirmed is a real finding about the vendor, not a bug to paper over.
    After regenerating you MUST run:

        uv run scripts/make_provider_transparency.py
        uv run --with pytest pytest tests/test_provider_transparency.py

Usage:
    uv run scripts/fetch_provider_transparency.py
    uv run scripts/fetch_provider_transparency.py --skip-pages   # refresh only the measurement
    uv run scripts/fetch_provider_transparency.py -o /tmp/x.json # write elsewhere
"""
from __future__ import annotations

import argparse
import collections
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "findings" / "provider_transparency.json"
DEFAULT_OUT = ROOT / "findings" / "provider_transparency_sources.json"
ENDPOINTS_API = "https://openrouter.ai/api/v1/models/{}/endpoints"

# A fixed sample, not a random one: these are widely-served open-weight models with many
# endpoints each, so the declaration rate reflects providers competing to serve the same
# slug — exactly the situation where a caller cannot tell which backend answered.
SAMPLE_MODELS = [
    "openai/gpt-oss-120b",
    "qwen/qwen3-235b-a22b",
    "deepseek/deepseek-chat-v3-0324",
    "meta-llama/llama-3.3-70b-instruct",
    "moonshotai/kimi-k2",
    "z-ai/glm-4.6",
]

# Values that mean "we are not telling you". OpenRouter passes the provider's own
# declaration through, so an absent value is the provider's silence, not OpenRouter's.
UNDECLARED = {None, "", "unknown"}

UA = "openrouter-reliable-research-search/1.0 (+https://github.com/mkhoriaty)"


def fetch(url: str, timeout: int = 45) -> tuple[int, str]:
    """GET a URL, returning (status, body). Network errors are surfaced, not swallowed."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def to_text(body: str) -> str:
    """Reduce an HTML page to the plain text a reader would see.

    Deliberately crude. The point is not fidelity but falsifiability: if a quote cannot be
    found in this text, we do not get to call it verbatim.
    """
    body = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", body)
    body = re.sub(r"(?s)<!--.*?-->", " ", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", html.unescape(body)).strip()


def norm(s: str) -> str:
    """Fold the punctuation that publishing pipelines silently rewrite."""
    for a, b in [("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), ("−", "-"), (" ", " ")]:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


def snapshot_pages(entries: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for e in entries:
        if not e.get("verified"):
            continue  # unchecked leads carry no quote, so there is nothing to confirm
        url = e["url"]
        print(f"  fetching {e['key']:<22} {url}", file=sys.stderr)
        status, body = fetch(url)
        text = to_text(body) if status == 200 else ""
        hay = norm(text)
        quotes = [{"quote": q, "confirmed": norm(q) in hay} for q in e.get("quotes", [])]
        out[e["key"]] = {
            "url": url,
            "status": status,
            "text_chars": len(text),
            "quotes": quotes,
        }
        for q in quotes:
            if not q["confirmed"]:
                print(f"      UNCONFIRMED: {q['quote'][:70]!r}", file=sys.stderr)
    return out


def measure_declaration_rate() -> dict[str, Any]:
    counts: collections.Counter[str] = collections.Counter()
    by_provider: dict[str, set[str]] = {}
    per_model: dict[str, int] = {}

    for slug in SAMPLE_MODELS:
        print(f"  endpoints for {slug}", file=sys.stderr)
        status, body = fetch(ENDPOINTS_API.format(slug))
        if status != 200:
            raise SystemExit(f"{slug}: OpenRouter returned {status}. Refusing to publish a "
                             f"declaration rate computed over a partial sample.")
        endpoints = json.loads(body)["data"]["endpoints"]
        per_model[slug] = len(endpoints)
        for ep in endpoints:
            q = ep.get("quantization")
            counts[q if q not in UNDECLARED else "undeclared"] += 1
            by_provider.setdefault(ep["provider_name"], set()).add(
                "undeclared" if q in UNDECLARED else q)

    total = sum(counts.values())
    silent = sorted(p for p, qs in by_provider.items() if qs == {"undeclared"})
    speaking = sorted(p for p, qs in by_provider.items() if qs != {"undeclared"})
    return {
        "sample_models": SAMPLE_MODELS,
        "endpoints_per_model": per_model,
        "endpoints_total": total,
        "by_quantization": dict(counts.most_common()),
        "undeclared_count": counts["undeclared"],
        "undeclared_pct": round(100 * counts["undeclared"] / total),
        "providers_always_undeclared": silent,
        "providers_declaring_somewhere": speaking,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--skip-pages", action="store_true",
                    help="refresh only the OpenRouter measurement, reusing stored snapshots")
    args = ap.parse_args()

    entries = json.loads(SRC.read_text())["entries"]

    if args.skip_pages:
        if not args.out.exists():
            raise SystemExit(f"--skip-pages needs an existing {args.out.name} to reuse.")
        sources = json.loads(args.out.read_text())["sources"]
    else:
        print("Snapshotting cited pages:", file=sys.stderr)
        sources = snapshot_pages(entries)

    print("Measuring quantization declaration rate:", file=sys.stderr)
    measured = measure_declaration_rate()

    args.out.write_text(json.dumps({
        "_note": "GENERATED by scripts/fetch_provider_transparency.py. `sources` records "
                 "whether each cited quote was located verbatim in the live page; `measured` "
                 "is our own count of how many OpenRouter endpoints decline to declare a "
                 "quantization. Do not edit by hand.",
        "sources": sources,
        "measured": measured,
    }, indent=2) + "\n")

    unconfirmed = [(k, q["quote"]) for k, v in sources.items()
                   for q in v["quotes"] if not q["confirmed"]]
    print(f"\nWrote {args.out.relative_to(ROOT)}", file=sys.stderr)
    print(f"  {measured['undeclared_pct']}% of {measured['endpoints_total']} endpoints "
          f"declare no quantization", file=sys.stderr)
    print(f"  {len(unconfirmed)} quote(s) unconfirmed", file=sys.stderr)
    for k, q in unconfirmed:
        print(f"    {k}: {q[:80]!r}", file=sys.stderr)


if __name__ == "__main__":
    main()

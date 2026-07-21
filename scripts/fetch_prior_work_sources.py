#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pypdf"]
# ///
"""Fetch and pin the sources behind findings/prior_work.json.

Prior-work metadata is never hand-typed. For every entry this script fetches the
authoritative source and records what it found:

  * arXiv entries -> the arXiv API (title, authors, dates, abstract), so titles and author
    lists come from arXiv rather than from anyone's memory.
  * web entries   -> the live page, reduced to text, with the surrounding context of the
    quoted line recorded verbatim.
  * `body_quotes` -> the paper PDF itself, for figures that live in the body rather than the
    abstract (a table cell, a prevalence rate). These are the numbers most likely to be
    misremembered, so they get the same verbatim treatment as everything else.

Every `quote` in prior_work.json must appear verbatim in the fetched abstract or page text.
A quote that does not match is a hard failure here -- a misquotation is exactly the defect
this pipeline exists to prevent, so it must never be written into the snapshot.

Entries marked "verified": false are leads that no one has checked; they carry no quote and
are deliberately NOT fetched, so the snapshot can never make an unverified lead look sourced.

Run:  uv run scripts/fetch_prior_work_sources.py
Out:  findings/prior_work_sources.json
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "findings/prior_work.json"
OUT = ROOT / "findings/prior_work_sources.json"

ARXIV_API = "http://export.arxiv.org/api/query?id_list={}&max_results=100"
ATOM = "{http://www.w3.org/2005/Atom}"
UA = {"User-Agent": "openrouter-reliable-research-search/prior-work (+https://github.com/AMindToThink)"}
CONTEXT_CHARS = 400


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def page_text(url: str) -> str:
    """Strip a page to whitespace-normalised text so a quote can be located in it."""
    raw = get(url)
    stripped = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", stripped))).strip()


def pdf_text(arxiv_id: str) -> str:
    """Extract the full text of an arXiv PDF so body figures can be checked against it."""
    import io

    import pypdf

    req = urllib.request.Request(f"https://arxiv.org/pdf/{arxiv_id}", headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
    pages = pypdf.PdfReader(io.BytesIO(raw)).pages
    return re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in pages))


def norm(s: str) -> str:
    """Normalise for substring matching: collapse whitespace, unify quotes and dashes."""
    s = re.sub(r"\s+", " ", s)
    for a, b in [("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), ("−", "-")]:
        s = s.replace(a, b)
    return s.strip()


def fetch_arxiv(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    feed = ET.fromstring(get(ARXIV_API.format(",".join(ids))))
    out: dict[str, dict] = {}
    for e in feed.findall(f"{ATOM}entry"):
        abs_url = e.findtext(f"{ATOM}id", "")
        m = re.search(r"arxiv\.org/abs/(.+?)(?:v\d+)?$", abs_url)
        if not m:  # a malformed entry means the id list is wrong; do not guess
            raise SystemExit(f"arXiv returned an entry with an unparseable id: {abs_url!r}")
        out[m.group(1)] = {
            "arxiv_id": m.group(1),
            "abs_url": abs_url.replace("http://", "https://"),
            "title": norm(e.findtext(f"{ATOM}title", "")),
            "authors": [a.findtext(f"{ATOM}name", "") for a in e.findall(f"{ATOM}author")],
            "published": e.findtext(f"{ATOM}published", "")[:10],
            "updated": e.findtext(f"{ATOM}updated", "")[:10],
            "abstract": norm(e.findtext(f"{ATOM}summary", "")),
        }
    missing = [i for i in ids if i not in out]
    if missing:
        raise SystemExit(f"arXiv returned no entry for: {missing} -- fix the ids, do not invent metadata.")
    return out


def main() -> None:
    entries = json.loads(SRC.read_text())["entries"]
    verified = [e for e in entries if e.get("verified")]

    arxiv_ids = [e["arxiv_id"] for e in verified if "arxiv_id" in e]
    meta = fetch_arxiv(arxiv_ids)

    records: dict[str, dict] = {}
    failures: list[str] = []

    for e in verified:
        key, quote = e["key"], e.get("quote", "")
        if not quote:
            failures.append(f"{key}: marked verified but has no quote")
            continue

        if "arxiv_id" in e:
            m = meta[e["arxiv_id"]]
            haystack, where = m["abstract"], "abstract"
            rec = {"kind": "arxiv", **m}
        else:
            url = e["url"]
            try:
                haystack = page_text(url)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                failures.append(f"{key}: could not fetch {url} ({type(exc).__name__}: {exc})")
                continue
            where = "page"
            rec = {"kind": "web", "url": url}

        i = norm(haystack).lower().find(norm(quote).lower())
        if i < 0:
            failures.append(f"{key}: quote not found in {where} of {e.get('url', e.get('arxiv_id'))}\n    {quote!r}")
            continue

        h = norm(haystack)
        rec["quote"] = quote
        rec["quote_found_in"] = where
        rec["quote_context"] = h[max(0, i - CONTEXT_CHARS): i + len(quote) + CONTEXT_CHARS]

        if e.get("body_quotes"):
            # Figures that live in the body of a paper (a table cell, a prevalence rate) or
            # further down a page than the pull-quote. Same verbatim rule as everything else.
            body = norm(pdf_text(e["arxiv_id"])) if "arxiv_id" in e else h
            checked = []
            for bq in e["body_quotes"]:
                j = body.lower().find(norm(bq["quote"]).lower())
                if j < 0:
                    failures.append(f"{key}: body quote not found in the PDF of "
                                    f"{e['arxiv_id']}\n    {bq['quote']!r}")
                    continue
                checked.append({**bq, "context": body[max(0, j - CONTEXT_CHARS):
                                                      j + len(bq["quote"]) + CONTEXT_CHARS]})
            rec["body_quotes"] = checked

        records[key] = rec

    if failures:
        print("REFUSING to write the snapshot -- unverifiable sources:\n", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        raise SystemExit(1)

    OUT.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "note": "Generated by scripts/fetch_prior_work_sources.py. arXiv metadata comes from the "
                "arXiv API; web quotes were located in the live page text on the date above.",
        "sources": records,
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(records)} verified sources "
          f"({len(arxiv_ids)} arXiv, {len(records) - len(arxiv_ids)} web)")


if __name__ == "__main__":
    main()

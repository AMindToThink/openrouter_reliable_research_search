#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Build the self-contained interactive explorer.

Injects two datasets into artifact/index_template.html:
  /*__DATA__*/       <- artifact/_data.json      (the 35-repo survey, trimmed for display)
  /*__ENDPOINTS__*/  <- artifact/endpoints.json  (REAL OpenRouter endpoint data)

Artifacts must be fully self-contained (a strict CSP blocks every external host), so the
data is inlined rather than fetched at runtime.

Run:  uv run scripts/build_artifact.py
Out:  artifact/index.html
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMPL = ROOT / "artifact/index_template.html"
OUT = ROOT / "artifact/index.html"


def main() -> int:
    tmpl = TMPL.read_text()
    data = (ROOT / "artifact/_data.json").read_text().strip()
    endpoints = (ROOT / "artifact/endpoints.json").read_text().strip()

    for placeholder in ("/*__DATA__*/[]", '/*__ENDPOINTS__*/{"fetched_at":"","models":[]}'):
        if placeholder not in tmpl:
            print(f"error: placeholder missing from template: {placeholder}", file=sys.stderr)
            return 1

    html = tmpl.replace("/*__DATA__*/[]", data)
    html = html.replace('/*__ENDPOINTS__*/{"fetched_at":"","models":[]}', endpoints)

    # A JSON string containing "</script" would break out of the script block.
    for blob, name in ((data, "_data.json"), (endpoints, "endpoints.json")):
        for bad in ("</script", "<!--", "]]>"):
            if bad in blob:
                print(f"error: {name} contains {bad!r} — would break the page", file=sys.stderr)
                return 1
        json.loads(blob)  # fail loudly on malformed data

    if html.count("<script>") != 1 or "const DATA = [" not in html:
        print("error: injection did not produce a single well-formed script block", file=sys.stderr)
        return 1

    OUT.write_text(html)
    ep = json.loads(endpoints)
    n_ep = sum(len(m["endpoints"]) for m in ep.get("models", []))
    print(f"wrote {OUT.relative_to(ROOT)} — {len(html):,} bytes")
    print(f"  survey rows:    {len(json.loads(data))}")
    print(f"  real endpoints: {n_ep} across {len(ep.get('models', []))} models (fetched {ep.get('fetched_at')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

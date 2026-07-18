#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Static auditor for research-reliability mistakes in OpenRouter usage.

Heuristic, dependency-free scanner. It finds files that talk to OpenRouter (or a
similar multi-provider router) and flags the safeguards that appear to be MISSING,
mapping each to the taxonomy in this repo (M1..M12). It cannot prove a result is
corrupted — it points a human at the call sites that deserve a closer look.

Usage:
    uv run audit_openrouter.py <path> [--json] [--all-files]

Exit code is non-zero when any High-severity risk is found on an OpenRouter path,
so this can gate CI. Run with --json for machine-readable output.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ---- what "using OpenRouter (or a similar router)" looks like in code ---------
ROUTER_SIGNALS: list[tuple[str, re.Pattern[str]]] = [
    ("openrouter_base_url", re.compile(r"openrouter\.ai/api", re.I)),
    ("openrouter_api_key", re.compile(r"OPENROUTER_API_KEY", re.I)),
    ("openrouter_model_slug", re.compile(r"""["']openrouter/""", re.I)),
    ("requesty", re.compile(r"requesty\.ai", re.I)),
    ("vercel_ai_gateway", re.compile(r"ai-gateway\.vercel|gateway\.ai\.cloudflare", re.I)),
]

# ---- safeguard signals (presence = good) -------------------------------------
HAS_QUANTIZATIONS = re.compile(r"""["']quantizations["']""")
HAS_REQUIRE_PARAMS = re.compile(r"""["']require_parameters["']""")
HAS_DATA_COLLECTION_DENY = re.compile(r"""["']data_collection["']\s*[:=]\s*["']deny["']""")
HAS_PROVIDER_PIN = re.compile(r"""["'](order|only)["']\s*[:=]""")
HAS_SORT = re.compile(r"""["']sort["']\s*[:=]""")
HAS_PROVIDER_DICT = re.compile(r"""["']provider["']\s*[:=]""")

# ---- risk signals (presence = suspicious) ------------------------------------
USES_STRUCTURED_OUTPUT = re.compile(r"response_format|json_schema|structured_output|response_schema")
USES_SAMPLING_PARAMS = re.compile(r"\b(temperature|top_p|top_k|seed|logprobs|logit_bias|min_p)\b")
USES_FLOOR_OR_PRICE = re.compile(r""":floor\b|["']sort["']\s*[:=]\s*["']price["']|:nitro\b""")
LOGS_PROVENANCE = re.compile(r"""\.provider\b|["']provider["']\s*\]|/generation\?id|generation_id|native_finish""")

TEXT_EXTS = {
    ".py", ".ipynb", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb",
    ".yaml", ".yml", ".toml", ".json", ".env", ".sh", ".md", ".txt", ".cfg", ".ini",
}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
             ".ruff_cache", "dist", "build", ".next", "site-packages"}


@dataclass
class Finding:
    mistake_id: str
    name: str
    severity: str  # High | Med
    file: str
    line: int
    detail: str


@dataclass
class FileReport:
    path: str
    router_signals: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def iter_text_files(root: Path):
    if root.is_file():
        yield root
        return
    for p in root.rglob("*"):
        if p.is_dir():
            if p.name in SKIP_DIRS:
                # prune: rglob can't prune, so skip descendants by checking parts
                continue
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in TEXT_EXTS:
            yield p


def read_text(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, OSError):
        # Not a decodable text file we can audit; report as skipped, don't crash.
        return None


def find_line(text: str, pattern: re.Pattern[str]) -> int:
    m = pattern.search(text)
    if not m:
        return 0
    return text.count("\n", 0, m.start()) + 1


def audit_file(p: Path, root: Path) -> FileReport | None:
    text = read_text(p)
    if text is None:
        return None
    signals = [name for name, pat in ROUTER_SIGNALS if pat.search(text)]
    if not signals:
        return None

    rel = str(p.relative_to(root)) if root.is_dir() else str(p)
    rep = FileReport(path=rel, router_signals=signals)

    has_provider_dict = bool(HAS_PROVIDER_DICT.search(text))
    has_quant = bool(HAS_QUANTIZATIONS.search(text))
    has_req = bool(HAS_REQUIRE_PARAMS.search(text))
    has_deny = bool(HAS_DATA_COLLECTION_DENY.search(text))
    has_pin = bool(HAS_PROVIDER_PIN.search(text))
    has_sort = bool(HAS_SORT.search(text))
    logs_prov = bool(LOGS_PROVENANCE.search(text))

    def add(mid: str, name: str, sev: str, pat: re.Pattern[str] | None, detail: str):
        rep.findings.append(Finding(mid, name, sev, rel, find_line(text, pat) if pat else 1, detail))

    # M1 — unpinned quantization
    if not has_quant:
        add("M1", "Unpinned quantization", "High", ROUTER_SIGNALS[0][1],
            "No `quantizations` restriction found — provider may serve int4/fp4/int8.")
    # M3 — probabilistic routing (no pin / no sort)
    if not has_pin and not has_sort:
        add("M3", "Probabilistic provider routing", "High", ROUTER_SIGNALS[0][1],
            "No `order`/`only`/`sort` — default load-balancing across providers; run-to-run drift.")
    # M2 — silent param dropping
    if USES_SAMPLING_PARAMS.search(text) and not has_req:
        add("M2", "Silent parameter dropping", "High", USES_SAMPLING_PARAMS,
            "Sampling params passed but no `require_parameters:true` — may be silently ignored.")
    # M9 — judge/grader on unconstrained route
    if USES_STRUCTURED_OUTPUT.search(text) and not has_req:
        add("M9", "Structured output without require_parameters", "High", USES_STRUCTURED_OUTPUT,
            "response_format/JSON-schema used but not forced to a supporting provider.")
    # M5 — data policy leakage
    if not has_deny:
        add("M5", "Data-policy not restricted", "Med", ROUTER_SIGNALS[0][1],
            "No `data_collection:'deny'` — prompts may route to train-on-your-data providers.")
    # M4 — no provenance logging
    if not logs_prov:
        add("M4", "No provenance logging", "Med", None,
            "No sign the served `provider` / generation id is recorded — can't reproduce/diagnose.")
    # M12 — actively cheap/degraded route
    if USES_FLOOR_OR_PRICE.search(text):
        add("M12", "Cheap/degraded route selected", "Med", USES_FLOOR_OR_PRICE,
            "`:floor`/`sort:price`/`:nitro` selects cheapest-or-fastest (often most quantized) route.")

    # Positive note: provider dict exists but partial
    if has_provider_dict and not (has_quant and has_req):
        rep.findings.append(Finding(
            "note", "Partial provider config", "info", rel,
            find_line(text, HAS_PROVIDER_DICT),
            "A `provider` config exists but is missing quantizations and/or require_parameters."))
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path, help="File or directory to audit")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    args = ap.parse_args()

    root = args.path
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2

    reports: list[FileReport] = []
    for p in iter_text_files(root):
        rep = audit_file(p, root)
        if rep is not None:
            reports.append(rep)

    high = sum(1 for r in reports for f in r.findings if f.severity == "High")
    med = sum(1 for r in reports for f in r.findings if f.severity == "Med")

    if args.json:
        out = {
            "openrouter_files": len(reports),
            "high": high, "med": med,
            "reports": [
                {"path": r.path, "router_signals": r.router_signals,
                 "findings": [asdict(f) for f in r.findings]}
                for r in reports
            ],
        }
        print(json.dumps(out, indent=2))
        return 1 if high else 0

    if not reports:
        print("No OpenRouter / router usage detected. (Nothing to audit.)")
        return 0

    print(f"OpenRouter reliability audit — {len(reports)} file(s) use a router\n")
    sev_order = {"High": 0, "Med": 1, "info": 2}
    for r in reports:
        print(f"── {r.path}   [{', '.join(r.router_signals)}]")
        for f in sorted(r.findings, key=lambda x: sev_order.get(x.severity, 9)):
            tag = {"High": "🔴", "Med": "🟠", "info": "ℹ️"}.get(f.severity, "•")
            loc = f":{f.line}" if f.line else ""
            print(f"   {tag} [{f.mistake_id}] {f.name} ({r.path}{loc})\n        {f.detail}")
        print()

    print(f"Summary: {high} High, {med} Med across {len(reports)} router file(s).")
    print("Heuristic only — confirm each on the actual call path. See taxonomy.md for M1..M12.")
    return 1 if high else 0


if __name__ == "__main__":
    raise SystemExit(main())

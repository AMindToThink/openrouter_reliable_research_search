"""Tests for the skill's bundled static auditor.

Focus on the rules added after the survey/endpoint sweep:
  * an endpoint-tag pin (`only: ["targon/fp8"]`) pins the quantization, so it must NOT
    raise M1 — the previous behaviour flagged `cot_legibility`, our one exemplary repo;
  * a bare vendor pin without a quantization IS a finding (the MathArena int4 trap);
  * a pin without `allow_fallbacks: false` is only a preference;
  * M4 severity matches findings/taxonomy.md (High);
  * a quantization floor with no hard pin, on a call site that looks identity-sensitive
    (interrogating/red-teaming/probing/judging a specific model), raises M13 — a floor is
    not a pin, and the same floor on a generic/infra call site must NOT raise it.

    uv run pytest tests/test_audit_openrouter.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skill" / "use-openrouter-safely" / "scripts" / "audit_openrouter.py"


@pytest.fixture(scope="module")
def audit():
    spec = importlib.util.spec_from_file_location("audit_openrouter", SCRIPT)
    assert spec and spec.loader, f"could not load {SCRIPT}"
    mod = importlib.util.module_from_spec(spec)
    # @dataclass resolves string annotations via sys.modules[cls.__module__]; register first.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def scan(audit, tmp_path: Path, source: str) -> set[tuple[str, str]]:
    """Run the auditor over one synthetic file; return {(mistake_id, name)}."""
    f = tmp_path / "call_site.py"
    f.write_text(source, encoding="utf-8")
    report = audit.audit_file(f, tmp_path)
    assert report is not None, "auditor did not recognise this as a router call site"
    return {(x.mistake_id, x.name) for x in report.findings}


def severities(audit, tmp_path: Path, source: str) -> dict[str, str]:
    f = tmp_path / "call_site.py"
    f.write_text(source, encoding="utf-8")
    report = audit.audit_file(f, tmp_path)
    assert report is not None
    return {x.mistake_id: x.severity for x in report.findings}


BASE = 'client = OpenAI(base_url="https://openrouter.ai/api/v1")\n'

ENDPOINT_TAG_PIN = BASE + """
resp = client.chat.completions.create(
    model="deepseek/deepseek-r1",
    temperature=0.0,
    extra_body={"provider": {
        "only": ["targon/fp8"],
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
    }},
)
log(resp.provider)
"""

BARE_VENDOR_PIN = BASE + """
resp = client.chat.completions.create(
    model="moonshotai/kimi-k2.6",
    extra_body={"provider": {"order": ["moonshotai"], "allow_fallbacks": False}},
)
log(resp.provider)
"""

NO_SAFEGUARDS = BASE + """
resp = client.chat.completions.create(
    model="deepseek/deepseek-r1", temperature=0.7,
)
"""

FLOOR_ON_IDENTITY_SENSITIVE_SITE = BASE + """
def get_model(untrusted_model: str):
    return client.chat.completions.create(
        model=untrusted_model,
        extra_body={"provider": {
            "quantizations": ["fp8", "fp16", "bf16", "fp32", "unknown"],
            "sort": "exacto",
            "data_collection": "deny",
        }},
    )
log(resp.provider)
"""

FLOOR_ON_GENERIC_INFRA_SITE = BASE + """
def make_model(name: str):
    return client.chat.completions.create(
        model=name,
        extra_body={"provider": {
            "quantizations": ["fp8", "fp16", "bf16", "fp32", "unknown"],
            "sort": "exacto",
            "data_collection": "deny",
        }},
    )
log(resp.provider)
"""

FLOOR_WITH_HARD_PIN_ON_IDENTITY_SENSITIVE_SITE = BASE + """
def get_model(judge_model: str):
    return client.chat.completions.create(
        model=judge_model,
        extra_body={"provider": {
            "quantizations": ["fp8", "fp16", "bf16", "fp32"],
            "only": ["cerebras/fp16"],
            "allow_fallbacks": False,
        }},
    )
log(resp.provider)
"""


def test_endpoint_tag_pin_does_not_raise_m1(audit, tmp_path):
    """`only: ["targon/fp8"]` fixes the quantization — flagging M1 here is a false positive."""
    ids = {mid for mid, _ in scan(audit, tmp_path, ENDPOINT_TAG_PIN)}
    assert "M1" not in ids


def test_endpoint_tag_pin_is_otherwise_clean(audit, tmp_path):
    """The exemplary configuration should raise no High findings at all."""
    f = tmp_path / "call_site.py"
    f.write_text(ENDPOINT_TAG_PIN, encoding="utf-8")
    report = audit.audit_file(f, tmp_path)
    highs = [x for x in report.findings if x.severity == "High"]
    assert highs == [], f"unexpected High findings: {[(x.mistake_id, x.name) for x in highs]}"


def test_bare_vendor_pin_flags_unverified_quantization(audit, tmp_path):
    """The MathArena trap: deterministic routing onto a possibly-int4 endpoint."""
    findings = scan(audit, tmp_path, BARE_VENDOR_PIN)
    assert ("M1", "Provider pinned, quantization unverified") in findings


def test_bare_vendor_pin_does_not_report_probabilistic_routing(audit, tmp_path):
    """It IS pinned — M3's load-balancing finding would be wrong here."""
    findings = scan(audit, tmp_path, BARE_VENDOR_PIN)
    assert ("M3", "Probabilistic provider routing") not in findings


def test_pin_without_fallbacks_off_is_flagged(audit, tmp_path):
    src = BASE + """
resp = client.chat.completions.create(
    model="x/y", extra_body={"provider": {"order": ["fireworks"]}},
)
"""
    findings = scan(audit, tmp_path, src)
    assert ("M3", "Pin can silently fall back") in findings


def test_fallbacks_off_suppresses_the_fallback_finding(audit, tmp_path):
    findings = scan(audit, tmp_path, BARE_VENDOR_PIN)
    assert ("M3", "Pin can silently fall back") not in findings


def test_unpinned_call_flags_the_core_high_severity_set(audit, tmp_path):
    ids = {mid for mid, _ in scan(audit, tmp_path, NO_SAFEGUARDS)}
    assert {"M1", "M2", "M3", "M4", "M5"} <= ids


def test_m4_severity_matches_taxonomy(audit, tmp_path):
    """taxonomy.md rates M4 High; the scanner previously said Med."""
    assert severities(audit, tmp_path, NO_SAFEGUARDS)["M4"] == "High"


def test_non_router_file_is_ignored(audit, tmp_path):
    f = tmp_path / "unrelated.py"
    f.write_text("print('hello')\n", encoding="utf-8")
    assert audit.audit_file(f, tmp_path) is None


def test_floor_on_identity_sensitive_site_flags_m13(audit, tmp_path):
    """A quantization floor is not a pin for a call site studying a specific model."""
    findings = scan(audit, tmp_path, FLOOR_ON_IDENTITY_SENSITIVE_SITE)
    assert ("M13", "Fleet floor mistaken for a pin") in findings


def test_floor_on_generic_infra_site_does_not_flag_m13(audit, tmp_path):
    """The same floor is a legitimate 3b default when no model is the specific research subject."""
    findings = scan(audit, tmp_path, FLOOR_ON_GENERIC_INFRA_SITE)
    ids = {mid for mid, _ in findings}
    assert "M13" not in ids


def test_floor_with_hard_pin_on_identity_sensitive_site_does_not_flag_m13(audit, tmp_path):
    """Already pinned — M13 would be a false positive here."""
    findings = scan(audit, tmp_path, FLOOR_WITH_HARD_PIN_ON_IDENTITY_SENSITIVE_SITE)
    ids = {mid for mid, _ in findings}
    assert "M13" not in ids


def test_floor_on_identity_sensitive_site_does_not_also_flag_m1(audit, tmp_path):
    """The floor itself does satisfy M1 — M13 is the separate, correct finding here."""
    ids = {mid for mid, _ in scan(audit, tmp_path, FLOOR_ON_IDENTITY_SENSITIVE_SITE)}
    assert "M1" not in ids

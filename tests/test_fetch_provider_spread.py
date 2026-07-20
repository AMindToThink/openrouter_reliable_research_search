"""Pin the OpenRouter endpoints-API field mapping.

`findings/provider_spread_reference.json` is the evidence base for every endpoint statistic
the project publishes, so the mapping from OpenRouter's API onto that schema has to be
exact. These tests run offline against a fixture recorded from the live API, and were
written after three real mapping bugs: `max_prompt` and `max_out` were read from a
non-existent `limits` sub-object, and `uptime_1d` was silently taking the 30-minute window.

    uv run pytest tests/test_fetch_provider_spread.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "fetch_provider_spread.py"
SNAPSHOT = ROOT / "findings" / "provider_spread_reference.json"

# Recorded verbatim from GET /api/v1/models/openai/gpt-oss-120b/endpoints.
RAW_ENDPOINT: dict[str, Any] = {
    "name": "DekaLLM | openai/gpt-oss-120b",
    "model_id": "openai/gpt-oss-120b",
    "model_name": "OpenAI: gpt-oss-120b",
    "context_length": 131072,
    "pricing": {"prompt": "0.00000003", "completion": "0.00000018", "discount": 0},
    "provider_name": "DekaLLM",
    "tag": "dekallm/bf16",
    "quantization": "bf16",
    "max_completion_tokens": None,
    "max_prompt_tokens": None,
    "status": 0,
    "uptime_last_30m": 98.6182429278312,
    "uptime_last_5m": 98.88888888888889,
    "uptime_last_1d": 98.25780601633868,
    "supports_implicit_caching": False,
    "latency_last_30m": None,
    "throughput_last_30m": None,
    "supported_parameters": ["temperature", "seed", "logprobs", "max_tokens"],
}


@pytest.fixture(scope="module")
def fps():
    spec = importlib.util.spec_from_file_location("fetch_provider_spread", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_record_matches_committed_schema(fps) -> None:
    """A freshly-mapped record must have exactly the snapshot's fields — no more, no less."""
    committed = json.loads(SNAPSHOT.read_text())
    expected = set(committed[0]["endpoints"][0].keys())
    assert set(fps.endpoint_record(RAW_ENDPOINT).keys()) == expected


def test_prices_converted_to_dollars_per_million(fps) -> None:
    rec = fps.endpoint_record(RAW_ENDPOINT)
    assert rec["in_per_m"] == 0.03
    assert rec["out_per_m"] == 0.18


def test_uptime_uses_the_one_day_window_not_thirty_minutes(fps) -> None:
    """Regression: the first draft read uptime_last_30m, which is far noisier."""
    rec = fps.endpoint_record(RAW_ENDPOINT)
    assert rec["uptime_1d"] == 98.3, "must be round(uptime_last_1d, 1)"
    assert rec["uptime_1d"] != round(RAW_ENDPOINT["uptime_last_30m"], 1)


def test_token_limits_read_from_top_level_fields(fps) -> None:
    """Regression: these were read from a `limits` sub-object that does not exist."""
    rec = fps.endpoint_record({**RAW_ENDPOINT,
                               "max_completion_tokens": 2048, "max_prompt_tokens": 6000})
    assert rec["max_out"] == 2048
    assert rec["max_prompt"] == 6000


def test_missing_limits_become_none_not_zero(fps) -> None:
    rec = fps.endpoint_record(RAW_ENDPOINT)
    assert rec["max_out"] is None and rec["max_prompt"] is None


def test_provider_slug_derived_from_endpoint_tag(fps) -> None:
    rec = fps.endpoint_record(RAW_ENDPOINT)
    assert rec["endpoint_tag"] == "dekallm/bf16"
    assert rec["provider_slug"] == "dekallm"


def test_params_sorted_for_stable_diffs(fps) -> None:
    rec = fps.endpoint_record(RAW_ENDPOINT)
    assert rec["params"] == sorted(RAW_ENDPOINT["supported_parameters"])


def test_missing_quantization_is_labelled_unknown(fps) -> None:
    """'unknown' is a missing label, not a precision claim — build_claims relies on this."""
    rec = fps.endpoint_record({**RAW_ENDPOINT, "quantization": None})
    assert rec["quant"] == "unknown"


@pytest.mark.parametrize("model_id,expected", [
    ("meta-llama/llama-3.3-70b-instruct", True),
    ("deepseek/deepseek-r1", True),
    ("qwen/qwen3-235b", True),
    ("openai/gpt-4o", False),
    ("anthropic/claude-opus-4.8", False),
    ("google/gemini-2.5-pro", False),
    ("openai/gpt-oss-120b", True),   # open-weight release from a proprietary author
])
def test_open_weight_filter(fps, model_id: str, expected: bool) -> None:
    assert fps.is_open_weight(model_id) is expected


def test_snapshot_only_contains_multi_endpoint_models() -> None:
    """Single-endpoint models have no spread to measure and would skew the denominators."""
    models = json.loads(SNAPSHOT.read_text())
    assert all(m["n_endpoints"] >= 2 for m in models)
    assert all(m["n_endpoints"] == len(m["endpoints"]) for m in models)


def test_snapshot_stores_observations_only() -> None:
    """No derived aggregates in the snapshot — they belong in claims.json.

    Regression: a persisted `quant_spread` field disagreed with its own endpoint list for
    78 of 87 models and matched no reproducible definition. Derived values are computed
    from `endpoints` at read time so they cannot drift.
    """
    models = json.loads(SNAPSHOT.read_text())
    for m in models:
        assert set(m.keys()) == {"model", "n_endpoints", "endpoints"}, m["model"]


def test_quantization_spread_is_derivable_from_endpoints() -> None:
    """What quant_spread was meant to express, computed rather than stored."""
    models = json.loads(SNAPSHOT.read_text())
    spreads = {m["model"]: len({e["quant"] for e in m["endpoints"]}) for m in models}
    assert all(s >= 1 for s in spreads.values())
    assert max(spreads.values()) >= 2, "expected at least one model serving mixed quantizations"

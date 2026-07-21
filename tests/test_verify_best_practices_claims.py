"""Pin the conclusions of scripts/verify_best_practices_claims.py the way
tests/test_claims_provenance.py pins prose numbers, and unit-test the pure functions
(Spearman correlation, quantization-disclosure counting) against known-answer fixtures so a
future edit to the analysis can't silently change what "verified" means.

    uv run --with pytest pytest tests/test_verify_best_practices_claims.py

No network access is used or required: everything here reads committed files
(findings/provider_spread_reference.json, findings/claims.json,
findings/best_practices_verification.json) or exercises pure functions on inline fixtures.
The live-refetch/schema-probe sections of the output are inherently point-in-time and are
checked for *shape*, not for specific values that would go stale by definition.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "verify_best_practices_claims.py"
OUT_PATH = ROOT / "findings" / "best_practices_verification.json"
SNAPSHOT_PATH = ROOT / "findings" / "provider_spread_reference.json"
CLAIMS_PATH = ROOT / "findings" / "claims.json"


@pytest.fixture(scope="module")
def vbp():
    # verify_best_practices_claims.py does `import fetch_provider_spread as fps` at module
    # level, a same-directory sibling import; scripts/ must be on sys.path first, same pattern
    # tests/test_claims_provenance.py uses for set_safety_class -> merge_verified.
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("verify_best_practices_claims", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def output() -> dict[str, Any]:
    if not OUT_PATH.exists():
        pytest.fail(f"{OUT_PATH} missing -- run `uv run scripts/verify_best_practices_claims.py`")
    return json.loads(OUT_PATH.read_text())


# --- the offline 'core' section must be reproducible and current -------------------

def test_core_section_is_current() -> None:
    """--check never touches the network; if this fails, someone edited the snapshot or the
    analysis without regenerating findings/best_practices_verification.json."""
    r = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, f"core section is stale:\n{r.stdout}{r.stderr}"


# --- pure function: Spearman correlation --------------------------------------------

def test_spearman_perfect_positive(vbp) -> None:
    assert vbp._spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_spearman_perfect_negative(vbp) -> None:
    assert vbp._spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_no_relationship_is_near_zero(vbp) -> None:
    # rank(y) = [2,4,1,3] against rank(x) = [1,2,3,4]: verified by brute force over all 24
    # permutations of 4 ranks to be the (an) exact rho == 0.0 case, not just "small."
    rho = vbp._spearman([1, 2, 3, 4], [20, 40, 10, 30])
    assert rho == pytest.approx(0.0, abs=1e-9)


def test_spearman_constant_series_is_undefined(vbp) -> None:
    """A model where every endpoint has the same price (or same precision) has no
    correlation to report -- must return None, not a spurious 0.0 or a ZeroDivisionError."""
    assert vbp._spearman([5, 5, 5], [1, 2, 3]) is None
    assert vbp._spearman([1, 2, 3], [7, 7, 7]) is None


def test_spearman_handles_ties_with_average_rank(vbp) -> None:
    # x has a tie at rank (1,2) -> both get 1.5; perfectly monotonic otherwise -> rho should
    # still be strongly positive, not undefined.
    rho = vbp._spearman([1, 1, 2, 3], [10, 10, 20, 30])
    assert rho == pytest.approx(1.0)


# --- pure function: quantization disclosure -----------------------------------------

def _fixture_models() -> list[dict[str, Any]]:
    return [
        {
            "model": "vendor/all-disclosed-mixed",
            "n_endpoints": 3,
            "endpoints": [
                {"quant": "bf16", "ctx": 100, "max_out": 10, "params": ["seed"]},
                {"quant": "fp8", "ctx": 100, "max_out": 10, "params": []},
                {"quant": "int4", "ctx": 100, "max_out": 10, "params": []},
            ],
        },
        {
            "model": "vendor/all-unknown",
            "n_endpoints": 2,
            "endpoints": [
                {"quant": "unknown", "ctx": 50, "max_out": 5, "params": []},
                {"quant": "unknown", "ctx": 50, "max_out": 5, "params": []},
            ],
        },
        {
            "model": "vendor/single-precision-no-unknown",
            "n_endpoints": 2,
            "endpoints": [
                {"quant": "fp16", "ctx": 20, "max_out": 2, "params": ["seed"]},
                {"quant": "fp16", "ctx": 30, "max_out": 3, "params": []},
            ],
        },
    ]


def test_quant_disclosure_counts_unknown_correctly(vbp) -> None:
    stats = vbp.quant_disclosure_stats(_fixture_models())
    assert stats["n_endpoints"] == 7
    assert stats["unknown_endpoints"] == 2
    assert stats["real_quant_endpoints"] == 5
    assert stats["pct_unknown"] == pytest.approx(100 * 2 / 7, abs=0.05)


def test_quant_disclosure_model_level_buckets(vbp) -> None:
    stats = vbp.quant_disclosure_stats(_fixture_models())
    assert stats["n_models_all_endpoints_unknown"] == 1   # vendor/all-unknown
    assert stats["n_models_no_unknown_endpoint"] == 2      # the other two
    assert stats["n_models_some_unknown_endpoint"] == 0
    assert stats["n_models_mixed_precision"] == 1          # bf16+fp8+int4 together
    assert stats["n_models_with_4bit_endpoint"] == 1


def test_quant_disclosure_refuses_empty_input(vbp) -> None:
    with pytest.raises(SystemExit):
        vbp.quant_disclosure_stats([])


# --- pure function: price vs precision ----------------------------------------------

def test_price_vs_precision_detects_clean_positive_case(vbp) -> None:
    """Cheapest endpoint is the most quantized, priciest is full precision -- the report's
    claim should register as a clean positive here."""
    models = [{
        "model": "vendor/clean-case",
        "endpoints": [
            {"quant": "int4", "in_per_m": 0.01},
            {"quant": "fp8", "in_per_m": 0.02},
            {"quant": "bf16", "in_per_m": 0.05},
        ],
    }]
    result = vbp.price_vs_precision(models, "in_per_m")
    assert result["n_models_considered"] == 1
    assert result["n_models_positive_correlation"] == 1
    assert result["cheapest_endpoint_is_most_quantized"] == 1


def test_price_vs_precision_detects_inversion(vbp) -> None:
    """The opposite pattern: the disclosed-bf16 endpoint is CHEAPEST and the fp4 endpoints are
    pricier -- exactly the shape found for openai/gpt-oss-120b in the real snapshot (DekaLLM's
    bf16 endpoint undercuts the fp4 providers). Must register as negative, not get smoothed
    into 'roughly positive.'"""
    models = [{
        "model": "vendor/inverted-case",
        "endpoints": [
            {"quant": "bf16", "in_per_m": 0.03},
            {"quant": "fp4", "in_per_m": 0.04},
            {"quant": "fp4", "in_per_m": 0.05},
        ],
    }]
    result = vbp.price_vs_precision(models, "in_per_m")
    assert result["n_models_considered"] == 1
    assert result["n_models_negative_correlation"] == 1
    assert result["cheapest_endpoint_is_most_quantized"] == 0
    assert result["negative_correlation_models"][0]["model"] == "vendor/inverted-case"


def test_price_vs_precision_excludes_unknown_quant(vbp) -> None:
    """'unknown' has no place on the precision scale -- a model where the only spread is
    disclosed-vs-unknown must not be silently treated as a precision comparison."""
    models = [{
        "model": "vendor/one-real-one-unknown",
        "endpoints": [
            {"quant": "fp8", "in_per_m": 0.01},
            {"quant": "unknown", "in_per_m": 0.02},
        ],
    }]
    result = vbp.price_vs_precision(models, "in_per_m")
    assert result["n_models_considered"] == 0
    assert result["n_models_no_usable_price_precision_spread"] == 1


def test_price_vs_precision_excludes_flat_price_or_flat_precision(vbp) -> None:
    models = [
        {"model": "vendor/flat-price", "endpoints": [
            {"quant": "fp4", "in_per_m": 0.02}, {"quant": "bf16", "in_per_m": 0.02}]},
        {"model": "vendor/flat-precision", "endpoints": [
            {"quant": "fp8", "in_per_m": 0.01}, {"quant": "fp8", "in_per_m": 0.02}]},
    ]
    result = vbp.price_vs_precision(models, "in_per_m")
    assert result["n_models_considered"] == 0
    assert result["n_models_no_usable_price_precision_spread"] == 2


# --- cross-check against build_claims.py's independent computation -----------------

def test_cross_check_raises_loudly_on_a_real_mismatch(vbp) -> None:
    """The whole point of cross_check_against_claims is to fail hard, not warn, when two
    independent implementations reading the same committed data disagree."""
    bogus = vbp.spread_recompute(vbp.load_snapshot())
    bogus["endpoints_per_model_median"] = -999999  # deliberately wrong
    with pytest.raises(SystemExit):
        vbp.cross_check_against_claims(bogus)


def test_cross_check_passes_on_the_real_recompute(vbp) -> None:
    recomputed = vbp.spread_recompute(vbp.load_snapshot())
    checked = vbp.cross_check_against_claims(recomputed)  # must not raise
    assert "widest_context_ratio" in checked
    assert "gptoss_endpoints_with_logprobs" in checked


# --- pinned conclusions on the real, committed data ---------------------------------
# These numbers are the actual answers to the task's questions, computed from
# findings/provider_spread_reference.json (87 open-weight models, fetched 2026-07-20). If the
# snapshot is regenerated, rerun scripts/verify_best_practices_claims.py and update these
# alongside it -- exactly the discipline test_claims_provenance.py already enforces for
# build_claims.py.

def test_pinned_quant_disclosure_rate(output) -> None:
    qd = output["core"]["quant_disclosure"]
    assert qd["n_models"] == 87
    assert qd["n_endpoints"] == 547
    assert qd["unknown_endpoints"] == 173
    assert qd["pct_unknown"] == 31.6
    assert qd["n_models_mixed_precision"] == 33


def test_pinned_quant_disclosure_is_not_negligible(output) -> None:
    """The report's premise is that undisclosed quantization is common, not a rare edge case.
    Pin the qualitative conclusion, not just the raw number: at minimum a quarter of all
    endpoints in the sweep report no real quantization at all."""
    qd = output["core"]["quant_disclosure"]
    assert qd["pct_unknown"] > 25.0


def test_pinned_price_vs_precision_holds_only_moderately(output) -> None:
    """Empirical result, not assumed: the 'cheaper implies more quantized' claim is directionally
    true on average but far from universal. Roughly a third of models with usable spread
    actually invert it, and nearly half the catalog has no usable spread to test at all. This
    test pins that nuance so it can't quietly get reported as a clean monotonic relationship.
    """
    pvp = output["core"]["price_vs_precision_by_prompt_price"]
    assert pvp["n_models_considered"] == 48
    assert pvp["n_models_no_usable_price_precision_spread"] == 39
    assert pvp["n_models_positive_correlation"] == 31
    assert pvp["n_models_negative_correlation"] == 13
    assert 0.2 < pvp["median_spearman_rho"] < 0.5, (
        "the average relationship should be moderate-positive, not strong/clean and not absent"
    )
    # the claim must NOT be reported as universal:
    assert pvp["n_models_negative_correlation"] > 0
    assert pvp["pct_models_positive"] < 100.0


def test_pinned_gptoss_is_a_documented_negative_correlation_example(output) -> None:
    """openai/gpt-oss-120b is the skill's worked example for partial logprobs support; it is
    ALSO a case where the cheapest disclosed endpoint (DekaLLM, bf16) is full precision while
    pricier endpoints are fp4/fp8 -- i.e. this specific worked example inverts the 'cheaper is
    more quantized' claim. Worth pinning explicitly since it's the doc's own running example."""
    pvp = output["core"]["price_vs_precision_by_prompt_price"]
    models_with_negative_rho = {v["model"] for v in pvp["negative_correlation_models"]}
    assert "openai/gpt-oss-120b" in models_with_negative_rho


def test_pinned_spread_recompute_matches_skill_worked_examples(output) -> None:
    sr = output["core"]["spread_recompute"]
    assert sr["endpoints_per_model_median"] == 4
    assert sr["endpoints_per_model_max"] == 30
    assert sr["models_context_varies"] == 64
    assert sr["models_max_output_varies"] == 73
    assert sr["llama33_worked_example"]["context"]["ratio"] == 21.8
    assert sr["llama33_worked_example"]["max_output"]["ratio"] == 62.5
    assert sr["gptoss_worked_example"]["n_with_logprobs"] == 8
    assert sr["gptoss_worked_example"]["n_endpoints"] == 20


def test_pinned_research_relevant_slugs_include_a_gap(output) -> None:
    """artifact/endpoints.json's 5 survey-linked models: at least one both discloses a
    genuine high/low precision spread AND ties directly to a repo in the survey, which is the
    concrete version of 'a research-relevant slug has both' the task asked for."""
    slugs = output["core"]["research_relevant_slugs"]
    assert "openai/gpt-oss-120b" in slugs
    assert slugs["openai/gpt-oss-120b"]["has_both_high_and_low_precision"] is True
    assert any(v["has_both_high_and_low_precision"] for v in slugs.values())


# --- the parts of the output that are inherently point-in-time: shape-only checks ---

def test_api_visibility_gaps_are_all_documented(output) -> None:
    """Item 4 of the task: every claimed API gap must carry concrete evidence, not just an
    assertion -- guards against the list degenerating into unbacked prose."""
    gaps = output["api_visibility_gaps"]
    assert len(gaps) >= 5
    for g in gaps:
        assert g["gap"] and g["why_it_matters"] and g["evidence"]
        assert len(g["evidence"]) > 40, f"evidence for {g['gap']!r} looks too thin to be concrete"


def test_live_sections_present_when_generated_with_live_data(output) -> None:
    """The committed findings/best_practices_verification.json should be the full (live)
    version, not the --no-live offline stub, since that's the version whose drift numbers are
    reported. If someone regenerates with --no-live, this fails as an explicit signal rather
    than an empty section going unnoticed."""
    assert output["live_drift_check"] is not None, (
        "findings/best_practices_verification.json was generated with --no-live -- "
        "regenerate without that flag so the drift check is part of the committed record"
    )
    assert output["schema_probe"] is not None


def test_live_drift_check_shape(output) -> None:
    drift = output["live_drift_check"]
    for key in ("fetched_at", "n_models_live", "n_models_committed",
                "models_dropped_since_snapshot", "models_added_since_snapshot",
                "quant_disclosure_live", "pct_unknown_delta", "worked_examples_live"):
        assert key in drift


def test_live_drift_explains_google_gemma_as_reclassification_not_churn(output) -> None:
    """Regression guard for a real finding surfaced while building this script: the 4 models
    dropped between the committed snapshot and a same-week live refetch are NOT gone from
    OpenRouter's catalog -- fetch_provider_spread.is_open_weight() buckets author 'google'
    entirely under PROPRIETARY_AUTHORS with no gemma exception (unlike the openai/gpt-oss
    exception it does have), so live gemma endpoints are silently excluded from future
    sweeps. That's a live methodology caveat, not evidence of endpoints disappearing."""
    dropped = output["live_drift_check"]["models_dropped_since_snapshot"]
    gemma_drops = [d for d in dropped if d["model"].startswith("google/gemma")]
    assert gemma_drops, "expected at least one google/gemma model dropped in this run's diff"
    assert all(d["still_in_catalog"] and d["reclassified_as_proprietary"] for d in gemma_drops)


def test_schema_probe_confirms_no_data_policy_or_selection_weight_field(output) -> None:
    probe = output["schema_probe"]
    for field in ("data_collection", "selection_weight", "traffic_share"):
        assert field in probe["fields_confirmed_absent"]
    assert "quantization" in probe["raw_endpoint_schema_keys"]

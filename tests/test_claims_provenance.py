"""Every statistic cited in prose must match the data it claims to summarise.

Markdown cannot `\\input{}` a generated value, so prose numbers are hand-written by
necessity. This suite is the compensating control: `scripts/build_claims.py` derives each
statistic from the dataset, and the assertions below pin the prose to those values. If the
survey is re-run and a number moves, the prose that quotes it fails here instead of
silently going stale.

Adding a statistic to prose? Add a claim in build_claims.py and a case here. Never
hand-type a number that has no claim behind it.

    uv run pytest tests/test_claims_provenance.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLAIMS_PATH = ROOT / "findings" / "claims.json"
README = ROOT / "README.md"
SUMMARY = ROOT / "findings" / "summary.md"
SKILL = ROOT / "skill" / "use-openrouter-safely" / "SKILL.md"


@pytest.fixture(scope="module")
def claims() -> dict[str, object]:
    if not CLAIMS_PATH.exists():
        pytest.fail("findings/claims.json missing — run `uv run scripts/build_claims.py`")
    return {k: v["value"] for k, v in json.loads(CLAIMS_PATH.read_text())["claims"].items()}


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text()


@pytest.fixture(scope="module")
def summary() -> str:
    return SUMMARY.read_text()


@pytest.fixture(scope="module")
def skill() -> str:
    return SKILL.read_text()


def test_claims_file_is_current() -> None:
    """claims.json must be regenerated whenever the dataset changes."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_claims.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"claims.json is stale:\n{r.stdout}{r.stderr}"


# --- internal consistency of the dataset itself ------------------------------------

def test_safety_classes_partition_the_survey(claims) -> None:
    total = (claims["repos_at_risk"] + claims["repos_handled"]
             + claims["repos_not_on_result_path"] + claims["repos_no_usage_found"])
    assert total == claims["repos_surveyed"]


def test_user_denominator_excludes_only_no_usage(claims) -> None:
    assert (claims["repos_routing_through_openrouter"]
            == claims["repos_surveyed"] - claims["repos_no_usage_found"])


def test_impacted_findings_severities_sum_to_total(claims) -> None:
    assert (claims["impacted_findings_high"] + claims["impacted_findings_medium"]
            + claims["impacted_findings_low"]) == claims["impacted_findings_total"]


def test_every_row_was_adversarially_verified(claims) -> None:
    """The README advertises full verification coverage; hold it to that."""
    assert claims["rows_impact_verified"] == claims["repos_surveyed"]


# --- prose agrees with the data ----------------------------------------------------

def test_readme_headline_ratio(readme, claims) -> None:
    """The headline scores against repos where OpenRouter reaches a published result."""
    at_risk = claims["repos_at_risk"]
    crit = claims["repos_critical_route"]
    pct = claims["at_risk_pct_of_critical_route"]
    assert f"**{at_risk} / {crit} ({pct}%)**" in readme, (
        f"README headline must read '{at_risk} / {crit} ({pct}%)'"
    )


def test_readme_states_all_three_denominators(readme, claims) -> None:
    """Readers must be able to tell 35 / 34 / 32 apart — conflating them is how 91% got there."""
    assert str(claims["repos_surveyed"]) in readme
    assert f'**{claims["repos_routing_through_openrouter"]}** contain an OpenRouter call' in readme
    assert f'**{claims["repos_critical_route"]}** put its output on a result path' in readme
    assert (f'31/{claims["repos_routing_through_openrouter"]} '
            f'({claims["at_risk_pct_of_users"]}%)') in readme, "keep the wider rate visible"


def test_on_result_path_classes_equal_critical_route(claims) -> None:
    """The headline denominator is only meaningful if these two partitions coincide."""
    assert (claims["repos_at_risk"] + claims["repos_handled"]
            == claims["repos_critical_route"])


def test_readme_safety_class_table(readme, claims) -> None:
    for key, label in (("repos_at_risk", "at_risk"), ("repos_handled", "handled"),
                       ("repos_not_on_result_path", "not_on_result_path"),
                       ("repos_no_usage_found", "no_usage_found")):
        assert re.search(rf"\|\s*`{label}`\s*\|\s*{claims[key]}\s*\|", readme), (
            f"README safety-class table: `{label}` should be {claims[key]}"
        )


def test_readme_findings_count(readme, claims) -> None:
    assert f"**{claims['impacted_findings_total']} specific claims/figures**" in readme
    assert (f"({claims['impacted_findings_high']} high-impact, "
            f"{claims['impacted_findings_medium']} medium, "
            f"{claims['impacted_findings_low']} low.)") in readme


def test_readme_high_severity_count(readme, claims) -> None:
    assert f"- **{claims['repos_severity_high']}** carry a **high-severity** gap" in readme


def test_readme_pervasive_gaps_match_mistake_frequencies(readme, claims) -> None:
    for mid, label in (("M4", "no provenance logging"), ("M5", "data-policy"),
                       ("M1", "unpinned quantization"), ("M3", "probabilistic routing")):
        n = claims[f"mistake_{mid}_repos"]
        assert f"({n})" in readme, f"README pervasive-gaps line: {label} ({mid}) should cite ({n})"


def test_summary_headline(summary, claims) -> None:
    assert (f"**{claims['repos_at_risk']} of {claims['repos_critical_route']} "
            f"({claims['at_risk_pct_of_critical_route']}%)**") in summary


def test_summary_mistake_table_matches_frequencies(summary, claims) -> None:
    for mid in [k.split("_")[1] for k in claims if k.startswith("mistake_")]:
        n = claims[f"mistake_{mid}_repos"]
        assert re.search(rf"\|\s*{mid}\s*\|[^|]*\|[^|]*\|\s*{n}\s*\|", summary), (
            f"summary.md mistake table: {mid} should be {n} repos"
        )


def test_skill_survey_base_rates(skill, claims) -> None:
    """The skill's taxonomy table cites 'seen in N/35' base rates."""
    n = claims["repos_surveyed"]
    for mid in [k.split("_")[1] for k in claims if k.startswith("mistake_")]:
        cnt = claims[f"mistake_{mid}_repos"]
        assert re.search(rf"\|\s*{mid}\s*\|[^|]*\|[^|]*\|\s*{cnt}/{n}\s*\|", skill), (
            f"SKILL.md taxonomy table: {mid} should read {cnt}/{n}"
        )


def test_skill_headline_matches_survey(skill, claims) -> None:
    assert (f"**{claims['repos_at_risk']}/{claims['repos_critical_route']} "
            f"({claims['at_risk_pct_of_critical_route']}%)**") in skill
    assert (f"{claims['repos_at_risk']}/{claims['repos_routing_through_openrouter']} "
            f"({claims['at_risk_pct_of_users']}%)") in skill, (
        "the skill should still show the wider rate so auditors can tell the two apart")


def test_skill_safety_class_counts(skill, claims) -> None:
    for key, label in (("repos_at_risk", "at_risk"), ("repos_handled", "handled"),
                       ("repos_not_on_result_path", "not_on_result_path"),
                       ("repos_no_usage_found", "no_usage_found")):
        assert re.search(rf"\|\s*`{label}`\s*\|[^|]*\|\s*{claims[key]}\s*\|", skill), (
            f"SKILL.md safety-class table: `{label}` should be {claims[key]}"
        )


def test_skill_endpoint_sweep_numbers(skill, claims) -> None:
    """The evidence table's prevalence column, all derived from the endpoint snapshot."""
    n = claims["endpoint_models"]
    for key in ("models_mixed_precision", "models_with_4bit_endpoint",
                "models_context_varies", "models_max_output_varies",
                "models_partial_seed", "models_partial_logprobs",
                "models_partial_structured_outputs", "models_partial_response_format"):
        assert f"{claims[key]}/{n}" in skill, f"SKILL.md should cite {claims[key]}/{n} for {key}"


def test_skill_endpoints_per_model(skill, claims) -> None:
    assert (f"median {claims['endpoints_per_model_median']}, "
            f"max {claims['endpoints_per_model_max']}") in skill


def test_skill_llama_cliff_example(skill, claims) -> None:
    """The worked example must quote the real endpoint spread."""
    assert f"{claims['llama33_context_min']:,} vs {claims['llama33_context_max']:,}" in skill
    assert f"({claims['llama33_context_ratio']}x)" in skill
    assert f"{claims['llama33_max_output_min']:,} vs {claims['llama33_max_output_max']:,}" in skill
    assert f"({claims['llama33_max_output_ratio']}x)" in skill


def test_skill_does_not_claim_llama_is_the_worst_case(skill, claims) -> None:
    """llama-3.3-70b is the worked example, not the extreme — a real model beats it.

    Regression guard: the first draft of the skill labelled this column 'Worst observed'
    while quoting llama's 62.5x, when xiaomi/mimo-v2.5 spreads 64.0x.
    """
    assert claims["widest_max_output_ratio"] > claims["llama33_max_output_ratio"], (
        "premise changed: llama IS now the widest max-output spread; update the prose"
    )
    assert "Worst observed" not in skill, (
        "SKILL.md must not label its example column 'Worst observed' — the examples are "
        "illustrative, and llama-3.3-70b is not the extreme case"
    )


def test_skill_gptoss_logprobs_example(skill, claims) -> None:
    assert (f"{claims['gptoss_endpoints_with_logprobs']} of "
            f"{claims['gptoss_endpoints']} endpoints") in skill

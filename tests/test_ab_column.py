"""Regression tests for the `provider_ab_rerun_assessment` column.

Guards the join in scripts/add_ab_column.py: every surveyed repo must carry an
assessment, the three published artifacts must agree, and the provider pairs cited
in the recommended cells must actually exist on OpenRouter (checked against the
committed endpoint snapshot, not the network).

    uv run pytest tests/test_ab_column.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FINDINGS = ROOT / "findings"
COLUMN_KEY = "provider_ab_rerun_assessment"
COLUMN_HEADER = "Provider A/B rerun assessment"


@pytest.fixture(scope="module")
def survey_rows() -> list[dict]:
    return json.loads((FINDINGS / "survey.json").read_text())["rows"]


@pytest.fixture(scope="module")
def csv_rows() -> list[dict]:
    with (FINDINGS / "survey.csv").open(newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def spread() -> dict[str, dict]:
    """model slug -> {endpoint_tag -> endpoint} from the committed snapshot."""
    data = json.loads((FINDINGS / "provider_spread_reference.json").read_text())
    return {m["model"]: {e["endpoint_tag"]: e for e in m["endpoints"]} for m in data}


def test_every_repo_has_an_assessment(survey_rows: list[dict]) -> None:
    missing = [r["title"] for r in survey_rows if not r.get(COLUMN_KEY, "").strip()]
    assert not missing, f"repos with no assessment: {missing}"


def test_csv_and_json_agree(survey_rows: list[dict], csv_rows: list[dict]) -> None:
    assert len(survey_rows) == len(csv_rows)
    for j, c in zip(survey_rows, csv_rows, strict=True):
        assert j["title"] == c["Title"]
        assert j[COLUMN_KEY] == c[COLUMN_HEADER]


def test_artifact_data_in_sync(survey_rows: list[dict]) -> None:
    artifact = json.loads((ROOT / "artifact" / "_data.json").read_text())
    by_title = {r["title"]: r[COLUMN_KEY] for r in survey_rows}
    for row in artifact:
        assert row[COLUMN_KEY] == by_title[row["title"]]


def test_assessments_file_matches_survey(survey_rows: list[dict]) -> None:
    cells = json.loads((FINDINGS / "ab_assessments.json").read_text())["cells"]
    assert set(cells) == {r["title"] for r in survey_rows}


@pytest.mark.parametrize(
    ("model", "strong", "weak"),
    [
        # the three recommended experiments' provider pairs
        ("moonshotai/kimi-k2.6", "streamlake/fp8", "moonshotai/int4"),
        ("openai/gpt-oss-120b", "cerebras/fp16", "wandb/fp4"),
    ],
)
def test_recommended_provider_pairs_exist(
    spread: dict[str, dict], model: str, strong: str, weak: str
) -> None:
    """The pin strings we tell people to use must be real endpoint tags."""
    assert model in spread, f"{model} absent from the endpoint snapshot"
    endpoints = spread[model]
    for tag in (strong, weak):
        assert tag in endpoints, f"{tag} is not a live endpoint tag for {model}"


def test_recommended_pairs_are_a_real_quality_gap(spread: dict[str, dict]) -> None:
    """Strong arm must be strictly higher precision than the weak arm."""
    quality = {"fp32": 7, "bf16": 6, "fp16": 6, "fp8": 4, "int8": 4, "fp6": 3, "int4": 1, "fp4": 1}
    for model, strong, weak in [
        ("moonshotai/kimi-k2.6", "streamlake/fp8", "moonshotai/int4"),
        ("openai/gpt-oss-120b", "cerebras/fp16", "wandb/fp4"),
    ]:
        eps = spread[model]
        s_q = quality[eps[strong]["quant"]]
        w_q = quality[eps[weak]["quant"]]
        assert s_q > w_q, f"{model}: {strong} ({s_q}) is not stronger than {weak} ({w_q})"


def test_gpt_oss_pair_both_expose_logprobs(spread: dict[str, dict]) -> None:
    """The logprob-divergence readout requires logprobs on BOTH arms."""
    eps = spread["openai/gpt-oss-120b"]
    for tag in ("cerebras/fp16", "wandb/fp4"):
        assert "logprobs" in eps[tag]["params"], f"{tag} does not expose logprobs"

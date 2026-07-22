"""Internal-consistency checks for findings/observed_routing.json.

This file is different in kind from the rest of findings/: everywhere else in this repo
audits what research code *says* it will do with OpenRouter; this file records what a
real run's own committed logs say OpenRouter *did* — provider by provider, response by
response. That evidentiary weight only holds if the bookkeeping is airtight, so this
suite is entirely offline and checks the shape of the committed file itself:

  * every response is accounted for (observed-provider counts + unattributed failures
    sum to the run's total, and the failure breakdown sums to the same unattributed
    count);
  * every record carries a locator and a primary-source URL a reader can click through
    to the exact raw run file being cited (per findings/survey.json's own standard);
  * every survey_corrections entry names a row that actually exists in
    findings/survey.json, so a correction can't silently drift from what it corrects.

It does not re-fetch GitHub — `scripts/fetch_observed_routing.py` is the reproducible,
network-touching half of this pair; this suite is the compensating control that runs
anywhere, offline, and fails loudly if the committed file's own bookkeeping breaks.

    uv run pytest tests/test_observed_routing.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OBSERVED_PATH = ROOT / "findings" / "observed_routing.json"
SURVEY_PATH = ROOT / "findings" / "survey.json"

ALLOWED_CATEGORIES = {
    "verified_pin",
    "unpinned_single_provider_observed",
    "allowlist_not_a_pin",
    "load_balancing_within_run",
    "data_quality_failure_no_artifact",
}

REQUIRED_RECORD_KEYS = {
    "id", "category", "repo", "repo_url", "run", "model_name", "model_slug",
    "configured_routing", "n_total", "observed_providers", "n_unattributed",
    "failure_detail", "locator", "primary_source_url", "config_source_url",
    "what_it_demonstrates",
}

REQUIRED_QUALITATIVE_KEYS = {
    "id", "category", "repo", "repo_url", "model_name", "model_slug", "locator",
    "primary_source_url", "quotes", "what_it_demonstrates", "note",
}

REQUIRED_CORRECTION_KEYS = {
    "id", "row_title", "survey_field", "original_claim", "primary_source_finding",
    "locator",
}


@pytest.fixture(scope="module")
def data() -> dict:
    if not OBSERVED_PATH.exists():
        pytest.fail("findings/observed_routing.json missing — run "
                    "`uv run scripts/fetch_observed_routing.py`")
    return json.loads(OBSERVED_PATH.read_text())


@pytest.fixture(scope="module")
def records(data: dict) -> list[dict]:
    return data["records"]


@pytest.fixture(scope="module")
def survey_titles() -> set[str]:
    rows = json.loads(SURVEY_PATH.read_text())["rows"]
    return {row["title"] for row in rows}


# --- top-level shape -----------------------------------------------------------------

def test_top_level_keys_present(data: dict) -> None:
    for key in ("generated_by", "source_repo", "source_commit", "methodology",
                "code_references", "n_records", "records", "qualitative_observations",
                "survey_corrections"):
        assert key in data, f"observed_routing.json is missing top-level key {key!r}"


def test_source_commit_looks_like_a_git_sha(data: dict) -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", data["source_commit"]), (
        "source_commit should be a full 40-char git SHA, so counts are pinned to an "
        "immutable snapshot rather than a mutable branch")


def test_n_records_matches_records_length(data: dict, records: list[dict]) -> None:
    assert data["n_records"] == len(records) > 0


def test_record_ids_are_unique(records: list[dict]) -> None:
    ids = [r["id"] for r in records]
    dupes = [i for i in ids if ids.count(i) > 1]
    assert len(ids) == len(set(ids)), f"duplicate record ids: {sorted(set(dupes))}"


# --- every record: required fields, locator, primary source --------------------------

@pytest.mark.parametrize("index", range(200))
def test_record_has_required_keys(records: list[dict], index: int) -> None:
    if index >= len(records):
        pytest.skip("fewer records than the parametrize ceiling")
    r = records[index]
    missing = REQUIRED_RECORD_KEYS - r.keys()
    assert not missing, f"record {r.get('id')} is missing keys: {missing}"


def test_every_record_has_a_locator_and_primary_source(records: list[dict]) -> None:
    for r in records:
        assert isinstance(r["locator"], str) and r["locator"].strip(), (
            f"record {r['id']} has an empty locator")
        assert isinstance(r["primary_source_url"], str), r["id"]
        assert r["primary_source_url"].startswith("https://"), (
            f"record {r['id']} primary_source_url is not an https link: "
            f"{r['primary_source_url']!r}")
        assert "raw.githubusercontent.com" in r["primary_source_url"], (
            f"record {r['id']} primary_source_url should point at a raw run artifact, "
            f"got {r['primary_source_url']!r}")
        assert r["config_source_url"].startswith("https://"), r["id"]


def test_record_run_path_matches_its_primary_source_url(records: list[dict]) -> None:
    """The locator's run directory must actually be the path the URL points at."""
    for r in records:
        # URL-encode spaces the same way the fetch script does, then compare.
        encoded_run = r["run"].replace(" ", "%20")
        assert encoded_run in r["primary_source_url"], (
            f"record {r['id']}: run {r['run']!r} not found in its own primary_source_url "
            f"{r['primary_source_url']!r}")


def test_record_categories_are_known(records: list[dict]) -> None:
    for r in records:
        assert r["category"] in ALLOWED_CATEGORIES, (
            f"record {r['id']} has an unrecognized category {r['category']!r}; add it to "
            f"ALLOWED_CATEGORIES if this is deliberate")


def test_record_repo_url_matches_repo(records: list[dict]) -> None:
    for r in records:
        assert r["repo_url"] == f"https://github.com/{r['repo']}", r["id"]


# --- the load-bearing check: every response is accounted for -------------------------

def test_observed_and_unattributed_counts_sum_to_total(records: list[dict]) -> None:
    for r in records:
        observed_sum = sum(r["observed_providers"].values())
        assert observed_sum + r["n_unattributed"] == r["n_total"], (
            f"record {r['id']}: observed_providers ({observed_sum}) + n_unattributed "
            f"({r['n_unattributed']}) != n_total ({r['n_total']})")


def test_failure_detail_sums_to_unattributed(records: list[dict]) -> None:
    for r in records:
        detail_sum = sum(r["failure_detail"].values())
        assert detail_sum == r["n_unattributed"], (
            f"record {r['id']}: failure_detail sums to {detail_sum} but n_unattributed "
            f"is {r['n_unattributed']} — every unattributed response should be classified")


def test_counts_are_nonnegative_ints(records: list[dict]) -> None:
    for r in records:
        assert isinstance(r["n_total"], int) and r["n_total"] > 0, r["id"]
        assert isinstance(r["n_unattributed"], int) and r["n_unattributed"] >= 0, r["id"]
        for provider, count in r["observed_providers"].items():
            assert isinstance(count, int) and count > 0, f"{r['id']}: {provider}"


# --- the two categories this file exists to distinguish -------------------------------

def test_verified_pin_records_are_actually_single_provider(records: list[dict]) -> None:
    """A record only belongs in verified_pin if the data really is 100% one provider."""
    for r in records:
        if r["category"] == "verified_pin":
            assert len(r["observed_providers"]) == 1, (
                f"record {r['id']} is tagged verified_pin but observed "
                f"{len(r['observed_providers'])} distinct providers")
            assert r["n_unattributed"] == 0, (
                f"record {r['id']} is tagged verified_pin but has "
                f"{r['n_unattributed']} unattributed/failed responses")


def test_load_balancing_records_show_at_least_two_providers(records: list[dict]) -> None:
    """A record only belongs in load_balancing_within_run if mixing was actually observed."""
    for r in records:
        if r["category"] == "load_balancing_within_run":
            assert len(r["observed_providers"]) >= 2, (
                f"record {r['id']} is tagged load_balancing_within_run but only observed "
                f"{list(r['observed_providers'])}")


def test_unpinned_single_provider_records_show_exactly_one_provider(records: list[dict]) -> None:
    """These exist as a contrast to load_balancing_within_run: same kind of unpinned
    config, but only one provider happened to show up in this particular run's window."""
    for r in records:
        if r["category"] == "unpinned_single_provider_observed":
            assert len(r["observed_providers"]) == 1, (
                f"record {r['id']} is tagged unpinned_single_provider_observed but "
                f"observed {list(r['observed_providers'])} — belongs in "
                f"load_balancing_within_run instead")


def test_allowlist_not_a_pin_records_configured_more_than_one_provider(
    records: list[dict],
) -> None:
    """These records exist to show an allow-list >= 2 entries doesn't guarantee spread."""
    for r in records:
        if r["category"] == "allowlist_not_a_pin":
            configured = r["configured_routing"]
            assert isinstance(configured, list) and len(configured) >= 2, (
                f"record {r['id']} is tagged allowlist_not_a_pin but configured_routing "
                f"is {configured!r}, not a >=2-entry allow-list")


# --- qualitative observations (no raw artifact, so no counts to sum) -----------------

def test_qualitative_observations_have_required_keys(data: dict) -> None:
    for obs in data["qualitative_observations"]:
        missing = REQUIRED_QUALITATIVE_KEYS - obs.keys()
        assert not missing, f"qualitative observation {obs.get('id')} missing: {missing}"
        assert obs["quotes"], f"qualitative observation {obs['id']} has no quotes"
        assert obs["primary_source_url"].startswith("https://"), obs["id"]
        assert obs["locator"].strip(), obs["id"]


# --- survey corrections must point at a real survey row ------------------------------

def test_survey_corrections_have_required_keys(data: dict) -> None:
    for c in data["survey_corrections"]:
        missing = REQUIRED_CORRECTION_KEYS - c.keys()
        assert not missing, f"survey correction {c.get('id')} missing: {missing}"
        assert c["locator"].strip(), c["id"]


def test_survey_corrections_reference_a_real_survey_row(
    data: dict, survey_titles: set[str],
) -> None:
    for c in data["survey_corrections"]:
        assert c["row_title"] in survey_titles, (
            f"survey correction {c['id']} references row_title {c['row_title']!r}, which "
            f"is not a title in findings/survey.json")


def test_survey_corrections_locators_reference_real_records(
    data: dict, records: list[dict],
) -> None:
    record_ids = {r["id"] for r in records}
    for c in data["survey_corrections"]:
        referenced = {rid for rid in record_ids if rid in c["locator"]}
        assert referenced, (
            f"survey correction {c['id']} locator {c['locator']!r} does not name any "
            f"record id defined in this file")

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Fetch and pin the primary-source evidence behind findings/observed_routing.json.

Every other findings file in this repo audits what research code *says* it will do with
OpenRouter (config, request bodies, absence of a `provider` dict). This one is different:
it mines the *run artifacts* — the raw `inference.json` files a real study committed to
its own git history — for what OpenRouter actually did, response by response, as logged
by the study's own code (`metadata.openrouter_provider`, populated straight from the
OpenAI-SDK chat-completion object's `.provider` field on the final stream chunk).

nostalgebraist/cot_legibility (https://www.lesswrong.com/posts/jHnZzicKzczkCCArK/) is the
only repo in findings/survey.json whose committed run data actually logs a served-provider
field per response (confirmed by grepping every other row's evidence/audit_notes for
`openrouter_provider`/`response.provider`/"generation id" — no other repo in the survey
persists this field at all, which is itself the more common finding: M4, no provenance
logging). That makes every count below unusually strong evidence: not "this code could
route unpredictably" but "here is the exact provider that served each of N requests, en
route to a number a human being published."

Fetches are pinned to a specific commit so a future push to the `nost` branch cannot
silently change already-verified counts out from under this file. Re-run with an updated
COMMIT (and re-verify the new counts by hand) if you deliberately want to refresh this.

Run:  uv run scripts/fetch_observed_routing.py
Out:  findings/observed_routing.json
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "findings" / "observed_routing.json"

REPO = "nostalgebraist/cot_legibility"
COMMIT = "f4437e4609770eb6d3def5f30951595c26420613"  # nost branch, 2026-04-19T20:14:09Z
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}"
BLOB_BASE = f"https://github.com/{REPO}/blob/{COMMIT}"
UA = {"User-Agent": "openrouter-reliable-research-search/observed-routing "
                     "(+https://github.com/AMindToThink)"}

# Code that produces the `metadata.openrouter_provider` field every count below reads.
CODE_REFERENCES = {
    "provider_pin_construction": {
        "path": "src/inference/providers.py",
        "lines": "36-43",
        "note": ("A list-valued `openrouter_provider` in a model config becomes "
                  "extra_body['provider'] = {'only': provider_config, 'allow_fallbacks': False} "
                  "in the OpenRouter request body. This is the code path every 'configured "
                  "routing' string in this file was produced by."),
    },
    "provenance_capture": {
        "path": "src/inference/providers.py",
        "lines": "100-104",
        "note": ("result['provider_model'] = last_chunk.model / "
                  "result['openrouter_provider'] = last_chunk.provider — read straight off "
                  "the final streamed chat-completion chunk's own attributes, not derived."),
    },
    "metadata_persistence": {
        "path": "src/inference/runner.py",
        "lines": "11-36",
        "note": ("process_question() copies result['openrouter_provider'] into the per-record "
                  "metadata dict that inference.json rows carry, when present. A request that "
                  "raised inside providers.py's own try/except still returns normally with an "
                  "'error' string in metadata and no openrouter_provider key; a request that "
                  "raised OUTSIDE that try/except (observed nowhere in this dataset's inner "
                  "errors, but structurally possible) would fall to runner.py's own except "
                  "clause and carry a top-level 'error' key with metadata entirely absent."),
    },
    "model_registry_pins": {
        "path": "src/utils/models.py",
        "lines": "37-78",
        "note": ("The repo's own house-convention provider lists for R1 (['novita']), qwq "
                  "(['deepinfra/bf16', 'nebius/fp8']), Kimi K2 (['novita/fp8', 'moonshotai/fp8']), "
                  "Kimi K2 0905 (['chutes/fp8']), and R1-Distill-Qwen-32B/14B ([], i.e. no "
                  "restriction at all) — later overridden per-run by config.yaml in most of the "
                  "runs below."),
    },
}


def _quote_path(path: str) -> str:
    return "/".join(urllib.parse.quote(part) for part in path.split("/"))


def fetch_text(path: str) -> str:
    req = urllib.request.Request(f"{RAW_BASE}/{_quote_path(path)}", headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def fetch_json(path: str) -> Any:
    return json.loads(fetch_text(path))


def raw_url(path: str) -> str:
    return f"{RAW_BASE}/{_quote_path(path)}"


def blob_url(path: str, lines: str | None = None) -> str:
    u = f"{BLOB_BASE}/{_quote_path(path)}"
    if lines:
        a, _, b = lines.partition("-")
        u += f"#L{a}" + (f"-L{b}" if b else "")
    return u


# --- run definitions -----------------------------------------------------------------
# config_dir may differ from inference_dir: several runs/YYYYMMDD_.../config.yaml files
# were overwritten in place by a later analysis-only re-run (they now show only an
# `analysis`-stage config with no `inference:` section). Their streamlit_runs/ mirror
# holds the original inference-stage config that actually produced the committed
# inference.json (verified byte-identical to the runs/ copy — see report).

RUNS: list[dict[str, Any]] = [
    # --- Category: verified pin (lead 1) ---------------------------------------------
    dict(id="r1-novita-pin-198", category="verified_pin",
         config_dir="runs/20260419_100716_R1_gpqa", inference_dir="runs/20260419_100716_R1_gpqa",
         model_name="R1", what_it_demonstrates=(
             "A true single-entry allow-list (openrouter_provider: [novita]) is empirically "
             "100% single-provider across every logged response, not just configured to be.")),
    dict(id="r1-novita-pin-300", category="verified_pin",
         config_dir="runs/20260419_103551_R1_gpqa", inference_dir="runs/20260419_103551_R1_gpqa",
         model_name="R1", what_it_demonstrates=(
             "Second independent run, same single-entry pin, same result: 300/300 responses "
             "from the one named provider.")),
    dict(id="kimik2-0905-pin", category="verified_pin",
         config_dir="streamlit_runs/20251021_201024_Kimi K2 0905_gpqa",
         inference_dir="streamlit_runs/20251021_201024_Kimi K2 0905_gpqa",
         model_name="Kimi K2 0905", what_it_demonstrates=(
             "A single-entry pin on a different model/provider (chutes/fp8) is also "
             "empirically 100% single-provider — the mechanism generalizes beyond R1/Novita.")),

    # --- Category: allow-list is not a pin (lead 3) ----------------------------------
    dict(id="r1-targon-allowlist-a", category="allowlist_not_a_pin",
         config_dir="streamlit_runs/20251014_190506_R1_gpqa", inference_dir="runs/20251014_190506_R1_gpqa",
         model_name="R1", what_it_demonstrates=(
             "A 2-entry allow-list (openrouter_provider: [targon/fp8, Nebius], "
             "allow_fallbacks:false) did not spread load: every one of 295 successful "
             "responses came from Targon and Nebius was never observed serving a single "
             "request. The 5 failures are Targon-side 429s (see failure_detail), not "
             "fallback attempts to Nebius — allow_fallbacks:false means a rate-limited "
             "request fails outright rather than trying the list's other entry.")),
    dict(id="r1-targon-allowlist-b", category="allowlist_not_a_pin",
         config_dir="streamlit_runs/20251014_201056_R1_gpqa", inference_dir="runs/20251014_201056_R1_gpqa",
         model_name="R1", what_it_demonstrates=(
             "Same exact config as r1-targon-allowlist-a, run ~65 minutes later same day: "
             "this time Targon rate-limited far harder (125/131 failures are explicit "
             "Targon 429 responses) and only 169/300 requests succeeded — still 100% "
             "Targon among successes, still 0 Nebius. Combined with the sibling run: 600 "
             "requests total under this allow-list, 0 ever served by the second listed "
             "provider. The published post's headline Targon-arm statistics (mean "
             "illegibility 4.305, 36.6% correct) come from run (a); this run (b) is the "
             "one with the 12.5-point correctness swing the survey's provider_ab_rerun_"
             "assessment field calls out.")),

    # --- Category: load balancing observed within a single run (lead 2) -------------
    # qwq (qwen/qwq-32b), openrouter_provider: [deepinfra/bf16, nebius/fp8] in every run.
    # Chronological run-directory order also traces the split drifting over 5 days.
    *[dict(id=f"qwq-{d.replace('streamlit_runs/', '').split('_')[0]}-{d.replace('streamlit_runs/', '').split('_')[1]}",
           category="load_balancing_within_run",
           config_dir=d, inference_dir=d, model_name="qwq",
           what_it_demonstrates=(
               "qwq (qwen/qwq-32b) under its house 2-provider allow-list "
               "([deepinfra/bf16, nebius/fp8]) split live traffic between both listed "
               "providers within a single run — not merely across separate runs."))
      for d in [
          "streamlit_runs/20251016_011742_qwq_gpqa",
          "streamlit_runs/20251017_172954_qwq_gpqa",
          "streamlit_runs/20251017_192243_qwq_gpqa",
          "streamlit_runs/20251017_224816_qwq_gpqa",
          "streamlit_runs/20251017_230836_qwq_gpqa",
          "streamlit_runs/20251018_034705_qwq_gpqa",
          "streamlit_runs/20251018_145227_qwq_gpqa",
          "streamlit_runs/20251018_175940_qwq_gpqa",
          "streamlit_runs/20251019_184002_qwq_gpqa",
          "streamlit_runs/20251019_185849_qwq_gpqa",
          "streamlit_runs/20251019_191941_qwq_gpqa",
          "streamlit_runs/20251019_195028_qwq_gpqa",
          "streamlit_runs/20251019_202534_qwq_gpqa",
          "streamlit_runs/20251020_185640_qwq_gpqa",
          "streamlit_runs/20251020_221724_qwq_gpqa",
          "streamlit_runs/20251020_232429_qwq_gpqa",
      ]],
    dict(id="kimik2-mix-194533", category="load_balancing_within_run",
         config_dir="streamlit_runs/20251021_194533_Kimi K2_gpqa",
         inference_dir="streamlit_runs/20251021_194533_Kimi K2_gpqa",
         model_name="Kimi K2", what_it_demonstrates=(
             "Kimi K2 (moonshotai/kimi-k2) under a 3-entry allow-list "
             "([novita/fp8, fireworks/fp8, moonshotai/fp8]) split traffic between two of "
             "the three listed providers (Moonshot AI, Novita) within one run; the third "
             "listed provider (Fireworks) was never used.")),
    dict(id="kimik2-mix-195820", category="allowlist_not_a_pin",
         config_dir="streamlit_runs/20251021_195820_Kimi K2_gpqa",
         inference_dir="streamlit_runs/20251021_195820_Kimi K2_gpqa",
         model_name="Kimi K2", what_it_demonstrates=(
             "Same model, 2-entry allow-list ([novita/fp8, fireworks/fp8]): all successes "
             "went to Novita, Fireworks was never observed, and 29% of requests failed "
             "outright on an OpenRouter-side per-model rate limit (429, "
             "'limit_rpm/moonshotai/kimi-k2', provider_name: null — this is a platform-wide "
             "cap on the model, not attributable to either listed provider) rather than "
             "falling over to the second listed provider.")),
    dict(id="r1distill32b-mix-155559", category="load_balancing_within_run",
         config_dir="streamlit_runs/20251024_155559_R1-Distill-Qwen-32B_gpqa",
         inference_dir="streamlit_runs/20251024_155559_R1-Distill-Qwen-32B_gpqa",
         model_name="R1-Distill-Qwen-32B", what_it_demonstrates=(
             "deepseek/deepseek-r1-distill-qwen-32b with openrouter_provider: [] (an empty "
             "list, i.e. no provider restriction requested at all — the model-registry "
             "default) split live traffic between NextBit and Novita within a single run. "
             "An empty `only` list evidently does not restrict routing to zero providers "
             "or error out; OpenRouter falls back to ordinary default routing.")),
    dict(id="r1distill32b-nextbit-003910", category="unpinned_single_provider_observed",
         config_dir="streamlit_runs/20251022_003910_R1-Distill-Qwen-32B_gpqa",
         inference_dir="streamlit_runs/20251022_003910_R1-Distill-Qwen-32B_gpqa",
         model_name="R1-Distill-Qwen-32B", what_it_demonstrates=(
             "Same unpinned config, two days earlier: only one provider (NextBit) is ever "
             "observed among successes, but 59% of requests failed outright with a bare "
             "'Provider returned error' (no provider attributable) — a much higher failure "
             "rate than either single-pinned R1 run, under an unpinned/unrestricted route. "
             "No mixing observed THIS time — contrast with r1distill32b-mix-155559, same "
             "model, same config, 2 days later, which does mix.")),

    # --- Category: unpinned, but only one provider observed in this narrow window ---
    dict(id="r1distill14b-mostly-together-012813", category="unpinned_single_provider_observed",
         config_dir="streamlit_runs/20251022_012813_R1-Distill-Qwen-14B_gpqa",
         inference_dir="streamlit_runs/20251022_012813_R1-Distill-Qwen-14B_gpqa",
         model_name="R1-Distill-Qwen-14B", what_it_demonstrates=(
             "deepseek/deepseek-r1-distill-qwen-14b, same empty-list config as the 32B "
             "variant: unlike the 32B runs, this run shows no second provider among "
             "successes (all Together) but does show a meaningful failure rate (19%, mixed "
             "503/generic provider errors) — included as a same-model, same-config contrast "
             "showing routing outcomes differ even for closely related model sizes.")),
    dict(id="r1distill14b-together-013133", category="unpinned_single_provider_observed",
         config_dir="streamlit_runs/20251022_013133_R1-Distill-Qwen-14B_gpqa",
         inference_dir="streamlit_runs/20251022_013133_R1-Distill-Qwen-14B_gpqa",
         model_name="R1-Distill-Qwen-14B", what_it_demonstrates=(
             "Same unpinned config, same day: 100/100 Together, 0 failures. Included as a "
             "reminder that 'unpinned' does not always mean 'observed mixing' within any "
             "one narrow time window — the risk is that it CAN, silently, not that it "
             "always will (see the 32B runs and the qwq runs, where it does).")),
    dict(id="r1distill14b-mostly-together-155133", category="unpinned_single_provider_observed",
         config_dir="streamlit_runs/20251024_155133_R1-Distill-Qwen-14B_gpqa",
         inference_dir="streamlit_runs/20251024_155133_R1-Distill-Qwen-14B_gpqa",
         model_name="R1-Distill-Qwen-14B", what_it_demonstrates=(
             "Same unpinned config, two days later: 99/100 Together, 1 generic provider "
             "error. Third data point for the same model/config across two different days, "
             "all Together-dominated — contrast with the 32B variant's NextBit/Novita mix "
             "under the identical [] config.")),
]


def norm_run_key(model_conf: dict | None) -> Any:
    if not model_conf:
        return None
    return model_conf.get("openrouter_provider", "<key absent>")


def analyze_run(entry: dict) -> dict:
    config_path = f"{entry['config_dir']}/config.yaml"
    inference_path = f"{entry['inference_dir']}/inference.json"
    config = yaml.safe_load(fetch_text(config_path))
    inference = fetch_json(inference_path)

    model_conf = None
    if isinstance(config, dict) and "inference" in config:
        models = config["inference"].get("models") or []
        if models:
            model_conf = models[0]
    configured = norm_run_key(model_conf)
    model_slug = model_conf.get("model_id") if model_conf else None

    provider_counts: Counter[str] = Counter()
    failure_detail: Counter[str] = Counter()
    n_unattributed = 0

    for rec in inference:
        md = rec.get("metadata")
        provider = md.get("openrouter_provider") if isinstance(md, dict) else None
        if provider:
            provider_counts[provider] += 1
            continue
        # Not attributed to a provider: classify why, from whichever error string exists.
        err = None
        if isinstance(md, dict) and md.get("error"):
            err = md["error"]
        elif "error" in rec:
            err = rec["error"]
        n_unattributed += 1
        if err is None:
            failure_detail["unknown_no_error_string"] += 1
        elif "429" in err and "provider_name': 'Targon'" in err.replace('"', "'"):
            failure_detail["targon_rate_limit_429"] += 1
        elif "429" in err and "limit_rpm" in err:
            failure_detail["openrouter_model_rate_limit_429_unattributed"] += 1
        elif "Expecting value" in err:
            failure_detail["response_json_parse_error"] += 1
        elif "NoneType" in err:
            failure_detail["nonetype_error"] += 1
        elif "Provider returned error" in err:
            failure_detail["provider_returned_error_unattributed"] += 1
        else:
            failure_detail["other:" + err[:60]] += 1

    return dict(
        n_total=len(inference),
        configured_routing=configured,
        model_slug=model_slug,
        observed_providers=dict(sorted(provider_counts.items(), key=lambda kv: -kv[1])),
        n_unattributed=n_unattributed,
        failure_detail=dict(failure_detail),
        config_url=raw_url(config_path),
        inference_url=raw_url(inference_path),
    )


QUALITATIVE_OBSERVATIONS = [
    dict(
        id="azure-cot-truncation-discarded-run",
        category="data_quality_failure_no_artifact",
        repo=REPO,
        repo_url=f"https://github.com/{REPO}",
        model_name="R1", model_slug="deepseek/deepseek-r1",
        locator=("Author's own LessWrong write-up, sections describing the initial "
                 "reproduction attempt (no committed run directory in this repo matches "
                 "it — see note)."),
        primary_source_url="https://www.lesswrong.com/posts/jHnZzicKzczkCCArK/r1-cot-illegibility-revisited",
        quotes=[
            "As of this writing, only two providers offer R1 on OpenRouter: Novita and Azure.",
            ("I first ran an equivalent of Jozdien's experiment, using his code and his "
             "config but with the provider specification removed (since neither of the "
             "providers listed in his config still offer R1). Here, some requests routed "
             "to Novita and some to Azure."),
            ("After reviewing the results, I found that responses from Azure frequently "
             "had empty final answer fields, suggesting that they ran out of room while "
             "still writing CoT; while this happened occasionally in Jozdien's original "
             "Targon run, it happened much more often with Azure."),
            ("Since this is clearly undesirable, and since I had found Novita to be "
             "relatively reliable in past work with open models, I decided to re-run with "
             "Novita only."),
        ],
        what_it_demonstrates=(
            "A provider silently mixed into an unpinned run (Novita+Azure) produced a "
            "specific, provider-attributable data-quality failure (Azure truncating "
            "chain-of-thought mid-generation, leaving empty final-answer fields) that the "
            "author caught by manual inspection and used as the reason to switch to a "
            "hard single-provider pin. This is the human motivation behind every pinned "
            "run in this dataset — but it happened on a run that predates this repo's "
            "provider-logging code and was never committed, so it cannot be re-verified "
            "against a raw artifact the way every other record in this file can. Treat the "
            "counts as unavailable and the quotes as the primary evidence."),
        note=("No run directory in nostalgebraist/cot_legibility's git history logs a "
              "response from an 'Azure' provider — runs/20251012_225607_R1_gpqa is the "
              "only unpinned pre-provenance-logging R1 run committed, and its metadata "
              "schema (duration_ms, tokens only — no provider_model/openrouter_provider "
              "keys) predates the provenance-capture code entirely, so even that run "
              "cannot confirm or rule out being the run the post describes. Only 1/100 of "
              "its responses has an empty answer field, which does not match the post's "
              "'frequently' — treat this as a different, earlier run, not corroborating "
              "evidence."),
    ),
]

SURVEY_CORRECTIONS = [
    dict(
        id="targon-run-a-300-vs-295",
        row_title="R1 CoT Illegibility Revisited (nostalgebraist, fork of Jozdien/cot_legibility)",
        survey_field="headline_impact",
        original_claim=("\"...all match exactly in run runs/20251014_190506_R1_gpqa; "
                        "300/300 records' metadata.openrouter_provider == \\\"Targon\\\", "
                        "0 Nebius.\""),
        primary_source_finding=(
            "Fetched runs/20251014_190506_R1_gpqa/inference.json directly: 295/300 records "
            "carry metadata.openrouter_provider == 'Targon'; the other 5 have metadata == "
            "null (a request-level failure, each with a Targon-attributed 429 rate-limit "
            "error string). 0 Nebius is correct; '300/300 == Targon' is not — it is 295/300, "
            "which is also the n=295 the same survey paragraph's legibility statistics "
            "already use two sentences earlier ('Illeg>=5: 34.9% (103/295)'), making the "
            "'300/300' phrasing an internal inconsistency within its own paragraph, not "
            "just a mismatch with the raw file."
        ),
        locator="record id r1-targon-allowlist-a in this file; runs/20251014_190506_R1_gpqa/inference.json",
    ),
    dict(
        id="targon-run-b-drifted-mischaracterization",
        row_title="R1 CoT Illegibility Revisited (nostalgebraist, fork of Jozdien/cot_legibility)",
        survey_field="provider_ab_rerun_assessment",
        original_claim=("\"One unpinned run drifted mid-experiment (only 169/300 responses "
                        "from Targon) and landed at 31.4% accuracy, a 12.5-point spread "
                        "against a pinned run.\""),
        primary_source_finding=(
            "The 169/300 raw count is correct (verified directly against "
            "runs/20251014_201056_R1_gpqa/inference.json), but 'drifted' misdescribes the "
            "mechanism: of the 131 non-Targon records, 125 carry an explicit Targon-side "
            "429 rate-limit error, 3 are JSON-parse errors, and 3 are 'NoneType' errors — "
            "none carry any provider name other than Targon anywhere in their error text, "
            "and Nebius (the allow-list's second entry) is never observed serving a single "
            "request in this run or its sibling. The run did not drift to a different "
            "provider; the sole responding provider (Targon) rate-limited nearly half the "
            "traffic and the allow_fallbacks:false config meant those requests failed "
            "outright rather than shifting to Nebius. 'Unpinned' (2-entry allow-list, "
            "contrasted with the true single-entry Novita pin) is a fair characterization; "
            "'drifted' is not, since it implies the response population changed providers "
            "mid-run, which the error text rules out."
        ),
        locator="record id r1-targon-allowlist-b in this file; runs/20251014_201056_R1_gpqa/inference.json",
    ),
]


def build() -> dict:
    records = []
    for entry in RUNS:
        analysis = analyze_run(entry)
        total_attributed = sum(analysis["observed_providers"].values()) + analysis["n_unattributed"]
        assert total_attributed == analysis["n_total"], (
            f"{entry['id']}: counts do not sum ({total_attributed} != {analysis['n_total']})")
        records.append(dict(
            id=entry["id"],
            category=entry["category"],
            repo=REPO,
            repo_url=f"https://github.com/{REPO}",
            run=entry["inference_dir"],
            model_name=entry["model_name"],
            model_slug=analysis["model_slug"],
            configured_routing=analysis["configured_routing"],
            n_total=analysis["n_total"],
            observed_providers=analysis["observed_providers"],
            n_unattributed=analysis["n_unattributed"],
            failure_detail=analysis["failure_detail"],
            locator=f"{entry['inference_dir']}/inference.json (+ config.yaml at {entry['config_dir']})",
            primary_source_url=analysis["inference_url"],
            config_source_url=analysis["config_url"],
            what_it_demonstrates=entry["what_it_demonstrates"],
        ))

    return dict(
        generated_by="scripts/fetch_observed_routing.py",
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_repo=f"https://github.com/{REPO}",
        source_commit=COMMIT,
        methodology=(
            "Every count in `records` is read straight from a run's committed "
            "inference.json (one row per model response, metadata.openrouter_provider "
            "populated by the study's own code from the OpenAI-SDK chat-completion "
            "object's `.provider` attribute on the final streamed chunk) and its sibling "
            "config.yaml, fetched at the pinned commit above. Nothing here is retyped from "
            "the survey's prose — see survey_corrections for two places where the prose "
            "did not hold up against this re-fetch."
        ),
        code_references={
            key: {**ref, "url": blob_url(ref["path"], ref["lines"])}
            for key, ref in CODE_REFERENCES.items()
        },
        n_records=len(records),
        records=records,
        qualitative_observations=QUALITATIVE_OBSERVATIONS,
        survey_corrections=SURVEY_CORRECTIONS,
    )


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {OUT} ({data['n_records']} records, "
          f"{len(data['qualitative_observations'])} qualitative observations, "
          f"{len(data['survey_corrections'])} survey corrections)")


if __name__ == "__main__":
    main()

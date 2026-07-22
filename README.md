# OpenRouter Reliable Research Search

> Does the way researchers call **OpenRouter** (and similar multi-provider routers) silently
> corrupt their results?

OpenRouter is a convenient unified API in front of dozens of inference providers. But by
default it **load-balances the same "model" across providers that may serve it quantized,
truncated, differently-tokenized, or with silently-dropped sampling parameters.** Two
identical requests can hit two different backends and return materially different outputs.
Most researchers who depend on OpenRouter for model outputs don't know this — and it can
make a model look smarter or dumber, or shift its measured propensities, in ways that
quietly invalidate a result.

This side-project:

1. **Best practices** — a thorough, citation-backed guide to using OpenRouter (or similar)
   reliably for research. → [`reports/openrouter-best-practices.md`](reports/openrouter-best-practices.md)
2. **A survey** of important public research code (top ML conferences + LessWrong) that uses
   OpenRouter, checking whether their results could be silently corrupted, with a **taxonomy
   of mistakes** and a **dataset**. → [`findings/`](findings/)
3. **An interactive explorer** + a **shareable summary image** of the findings.
4. **A Claude skill** for using OpenRouter properly and auditing a codebase's usage.
   → [`skill/`](skill/)

## Why this matters (the one-paragraph version)

By default OpenRouter routes each request to whichever provider is cheapest-and-up, weighted
by the inverse square of price. Providers are free to serve a model at any quantization
(down to int4), on any inference engine, and to **silently ignore request parameters they
don't support** (`temperature`, `seed`, `logprobs`, `response_format`) unless you set
`require_parameters: true`. Independent work finds inference-backend choice alone can move a
benchmark score by **up to ~16 percentage points**, yet the inference stack is almost never
reported. If your research pins none of this, "the model" you evaluated is a moving target.

## This isn't a new claim — and that's the point

The mechanism is established. What was missing is evidence about whether working research code
does anything about it. Four sources, each quoted verbatim and pinned in
[`reports/prior-work.md`](reports/prior-work.md):

- **It is measurable, and it was measured at a top venue.** *Model Equality Testing* (ICLR 2025)
  ran a two-sample test against commercial APIs and found **11 out of 31 endpoints serve
  different distributions than reference weights released by Meta**.
- **The gap can be enormous.** On AIME25, identical `gpt-oss-120b` weights scored **93.3%** via
  Cerebras/Nebius/Fireworks/DeepInfra/Novita/Together, **86.7%** via Groq, **80.0%** via Azure
  and **36.7%** via CompactifAI — one slug, one benchmark, one week.
- **The field does not notice.** *Chasing Shadows* audited all 72 LLM-security papers at leading
  venues from 2023–2024. Its pitfall P9 — being unable to tell which model instance produced a
  result — was the most prevalent one it found, **present in 73.6% (53) of papers**, and
  **not one of them discussed it**.
- **It has already invalidated published work.** After a re-run changed only the OpenRouter
  provider, the author of the critiqued paper conceded his results "were contaminated by bad
  inference setups."

This survey is the missing piece: not "can routing corrupt a result" — that is settled — but
**how many real research repos leave the channel open.** The answer is most of them.

## Layout

| Path | What's there |
| --- | --- |
| `reports/` | Best-practices guide; prior work; detection fingerprints; provider transparency audit; the provider A/B rerun experiment plan |
| `findings/` | The survey dataset (CSV/JSON), taxonomy of mistakes, fingerprint catalogue, methodology, `claims.json` |
| `scripts/` | Everything generated is generated here — see [Provenance](#provenance-where-every-published-number-comes-from) |
| `artifact/` | Interactive data explorer (self-contained HTML) |
| `image/` | Shareable summary graphic |
| `skill/` | `use-openrouter-safely` Claude skill |
| `tests/` | Enforces the provenance chain — prose numbers, artifact integrity, API field mappings |

## Headline findings

We audited **35** influential public repos (importance-first: NeurIPS · ICML · ICLR · ACL ·
NAACL · Nature + UK AISI · METR · Redwood · Palisade · Anthropic Fellows + LessWrong/AF) flagged
as routing model calls through OpenRouter. Each verdict came from one audit agent **plus one
adversarial verifier** reading the actual source. Numbers below are generated from
[`findings/stats.json`](findings/stats.json).

- **31 / 32 (97%)** of the repos whose OpenRouter output actually reaches a reported number, a
  training set, or a safety measurement leave at least one **uncontrolled** provider-routing
  corruption channel open.
- **Three denominators, stated plainly.** 35 repos surveyed · **34** contain an OpenRouter call
  site anywhere · **32** put its output on a result path. The headline uses **32**, because a repo
  only demonstrates something about *using OpenRouter well* if OpenRouter reaches a published
  number. Against the wider 34 the rate is 31/34 (91%).
- **113 specific claims/figures** across **31 repos** were traced to an OpenRouter-routed call and could
  be affected — each named down to the figure/table/number, with its mechanism and a
  *"does this really depend on OpenRouter?"* confidence. (34 high-impact, 53 medium, 26 low.)
- **23** carry a **high-severity** gap (can distort a result, not just reproducibility).
- **Exactly one repo** — `nostalgebraist/cot_legibility` — both uses OpenRouter for real results
  **and** controls for it (pins `only:[novita]`, `allow_fallbacks:False`, logs the served provider).
  It's exemplary precisely because *provider choice is its research question*.
- The other three previously-"safe" repos are **not** success stories, and we no longer count them
  as such. Every row now carries a `safety_class`:

  | class | n | in the headline denominator? | meaning |
  | --- | :-: | :-: | --- |
  | `at_risk` | 31 | ✅ | OpenRouter feeds a reported result, with an uncontrolled channel open |
  | `handled` | 1 | ✅ | feeds a reported result **and** controls for it — the only real positive |
  | `not_on_result_path` | 2 | ❌ | OpenRouter present in the repo, but no reported result depends on it |
  | `no_usage_found` | 1 | ❌ | no OpenRouter call site at all (discovery false positive) |

  A repo that never routes a research call through OpenRouter has demonstrated *nothing* about
  using OpenRouter well — lumping those in with the one genuine success overstated the good news.
  The two `at_risk` + `handled` classes are exactly the 32 repos flagged `critical_route`; a build
  check fails if that ever stops holding.
- Most pervasive gaps (all silent by default): **no provenance logging (28)**, **data-policy
  left open (27)**, **unpinned quantization (26)**, **probabilistic routing (26)**.

> **Read this correctly.** "At risk" = the code leaves a known corruption channel **open and
> uncontrolled**, *not* that any published number is wrong. The *possibly-impacted findings* are
> **hypotheses worth checking, not demonstrated errors**. We audited how each repo *routes*
> model calls; we did not re-run experiments across providers to measure the actual delta. See
> [`findings/methodology.md`](findings/methodology.md).
>
> **All 35 rows completed adversarial verification** — a second agent re-read the paper and code and
> was told to drop any cited figure it could not find in the real source. That stage earns its keep:
> it caught a first-pass agent inventing numbers for one repo, and a paper whose reproducibility
> appendix claims a model was called "via Google AI" when the code hardcodes an OpenRouter slug.

## Can you tell from the outside?

The audit above reads code. A separate question is whether a **reader** — with only the paper,
its figures, its appendix and whatever data was released — could ever notice. There is one
famous case where someone did: nostalgebraist read the chain-of-thought transcripts published
with an "illegible reasoning" paper, recognised them as decode-level gibberish rather than
reasoning, re-ran the same prompts on a different OpenRouter provider, and watched the
phenomenon vanish. The paper's author agreed his results "were contaminated by bad inference
setups."

So we went looking for the rest of that method. 18 parallel research sweeps, one adversarial
verifier per candidate, merged into **17** fingerprint families →
[`reports/detection-fingerprints.md`](reports/detection-fingerprints.md), data in
[`findings/fingerprints.json`](findings/fingerprints.json). **13** rest on a documented catch
rather than on reasoning; **12** are checkable only if the authors released raw outputs. The
catalogue includes two explicit *negative* families — run-to-run variance, temperature-0
non-determinism, cost and throughput side channels — because each of them looks like a
fingerprint and is not one.

Then we ran every one of the 35 surveyed projects against the catalogue, one agent per repo,
with a second adversarial pass over every positive claim. The verdict lives in the dataset as
**Signs provider issues messed up the paper**:

| Verdict | Repos | Meaning |
| --- | --- | --- |
| `nothing_checkable_released` | 14 | No transcripts, per-sample data, or provider metadata. No reader could ever check. |
| `fingerprints_found` | 8 | Something in their own published output is visibly off. |
| `checked_clean` | 7 | Enough was released to look, and the applicable checks come back clean. |
| `inconclusive` | 6 | Raw outputs exist but do not settle it either way. |

Only **21** of 35 projects released anything a reader could check at all. Among those that did,
the hit rate is not small — released outputs contain literal `<|endoftext|>` salad, completion
walls below the declared `max_tokens`, near-half-empty completion rates on one model but not
its neighbours, and `<think>` tags that appear for three hours and then stop. But the honest
headline runs the other way: **the fingerprint that mattered most is the one nobody publishes.**
Provider metadata survives in released data for only a handful of these projects, aggregate-only
reporting destroys every distributional signal before publication, and the original catch itself
needed both released transcripts *and* someone willing to pay to re-run the experiment.

## Deliverables

| | |
| --- | --- |
| 📊 **Interactive explorer** | Provider Routing Inspector — filter by verdict/severity, click a mistake to filter, "Routing Roulette" demo, per-repo link to the exact offending line: **https://claude.ai/code/artifact/6ba2006d-e72e-47b8-9e81-fe6270f8305e** (source: [`artifact/index.html`](artifact/index.html)) |
| 🖼️ **Shareable image** | [`image/openrouter_findings.png`](image/openrouter_findings.png) — one-glance summary + the fix |
| 📄 **Best-practices guide** | [`reports/openrouter-best-practices.md`](reports/openrouter-best-practices.md) |
| 📚 **Prior work** | [`reports/prior-work.md`](reports/prior-work.md) — who already documented this, with every quotation pinned to its source |
| 🔍 **Detection fingerprints** | [`reports/detection-fingerprints.md`](reports/detection-fingerprints.md) — 17 things a reader can look for in a published paper, and the much longer list of what cannot be told at all |
| 🔍 **Provider transparency** | [`reports/provider-transparency.md`](reports/provider-transparency.md) — could a researcher find out what changed by reading the vendor's own docs? Mostly not: 31% of sampled endpoints declare no quantization at all |
| 🗂️ **Dataset** | [`findings/survey.csv`](findings/survey.csv) · [`findings/survey.json`](findings/survey.json) (incl. a validated GitHub permalink to each call site) |
| 🧾 **Taxonomy** | [`findings/taxonomy.md`](findings/taxonomy.md) — the M1–M12 mistake catalog |
| 🛠️ **Claude skill** | [`skill/use-openrouter-safely/`](skill/use-openrouter-safely/) — guidance + a heuristic static auditor |

## Reproduce

```bash
# audit any repo for OpenRouter reliability mistakes (heuristic first pass)
uv run skill/use-openrouter-safely/scripts/audit_openrouter.py <path-to-repo>
```

### Use the skill

`use-openrouter-safely` works in two modes: writing OpenRouter calls correctly, and auditing a
repo's existing usage against the M1–M12 taxonomy. To install it for Claude Code:

```bash
cp -r skill/use-openrouter-safely ~/.claude/skills/
```

It then activates on its own whenever you're working with OpenRouter, or you can invoke it
directly with `/use-openrouter-safely`. The guidance is plain Markdown — `skill/use-openrouter-safely/SKILL.md`
is worth reading even if you don't use Claude Code.

### Provenance: where every published number comes from

No statistic in this repo is hand-typed. Two files are *inputs* — the audit dataset
(`findings/survey.json`, written by the multi-agent sweeps) and the endpoint snapshot
(`findings/provider_spread_reference.json`, fetched from OpenRouter's API). Everything else
is generated from them:

```bash
uv run scripts/fetch_provider_spread.py   # refetch the endpoint snapshot   ⚠️ see below
uv run scripts/set_safety_class.py        # classify rows -> regenerates survey.csv,
                                          #   stats.json, artifact/_data.json, index.html
uv run scripts/build_claims.py            # derive every prose-cited statistic -> claims.json
uv run scripts/make_summary.py            # findings/summary.md
uv run scripts/fetch_prior_work_sources.py      # re-verify every prior-work quotation at source
uv run scripts/make_prior_work.py               # reports/prior-work.md
uv run scripts/add_fingerprint_column.py  # join per-repo fingerprint verdicts onto the dataset
uv run scripts/make_fingerprints.py       # reports/detection-fingerprints.md
uv run scripts/fetch_provider_transparency.py   # re-verify every vendor quotation at source
uv run scripts/make_provider_transparency.py    # reports/provider-transparency.md
uv run --with cairosvg scripts/make_poster.py   # image/openrouter_findings.{svg,png}
uv run --with pytest pytest tests/        # enforces the whole chain
```

`findings/claims.json` is the ledger: each entry records a value, its source file, and the
derivation used. Markdown cannot `\input{}` a value, so
[`tests/test_claims_provenance.py`](tests/test_claims_provenance.py) is the compensating
control — it asserts the numbers written in this README, `findings/summary.md`, and the skill
still match the data. A statistic that drifts fails a test instead of quietly going stale.

Derived values are never persisted into the input snapshots, only into `claims.json`. (A
`quant_spread` field once stored in the endpoint snapshot disagreed with its own endpoint
list for 78 of 87 models; it was removed rather than repaired.)

> ⚠️ **Refetching the endpoint snapshot moves published numbers.** Endpoints rotate
> constantly. `fetch_provider_spread.py` will not reproduce the committed snapshot — rerun
> `build_claims.py` and the test suite afterwards and update whatever the tests flag. Treat it
> as a reviewed data change, not a routine refresh.

The two multi-agent sweeps (importance-first discovery → per-repo audit + adversarial verify)
were run as background workflows; the discovery record is preserved in
[`findings/discovered_candidates.json`](findings/discovered_candidates.json).

---
name: use-openrouter-safely
description: >-
  Use when writing, reviewing, or auditing code that calls OpenRouter (or a similar
  multi-provider router like Requesty / Vercel AI Gateway / a LiteLLM proxy) to produce
  RESEARCH results — evals, LLM-as-judge scoring, agent rollouts, benchmark numbers, or
  generated/labeled training data. OpenRouter's default routing silently load-balances a
  "model" across providers that may serve it quantized (down to int4), with different context
  windows and max-output caps, on different inference engines, and drops unsupported
  sampling/format params — quietly corrupting results and breaking reproducibility. Triggers:
  "openrouter", "OPENROUTER_API_KEY", "openrouter.ai/api/v1", provider routing, endpoint
  pinning, `extra_body={"provider": ...}`, quantization of an API model, "which provider served
  this", reproducibility of API model outputs, auditing a repo's model-inference hygiene.
---

# Using OpenRouter safely for research

**The core problem:** with default settings, "a model" on OpenRouter is *not a fixed artifact*.
The same slug can be served by different providers, at different quantizations (int4→fp32), with
different context windows and output caps, on different inference engines, with silently-dropped
parameters. If a result depends on which weights actually ran and you pinned nothing, the result
may not reproduce or generalize — and you won't get an error.

**Source repo — every `reports/…` and `findings/…` path in this file lives there:**
<https://github.com/AMindToThink/openrouter_reliable_research_search>. This skill distills that
public audit; go there for the full evidence: the 35-repo survey dataset (`findings/survey.csv`),
the complete best-practices guide
([`reports/openrouter-best-practices.md`](https://github.com/AMindToThink/openrouter_reliable_research_search/blob/master/reports/openrouter-best-practices.md)),
prior work with every
quotation verified at source (`reports/prior-work.md`), the 17-fingerprint detection catalogue
(`reports/detection-fingerprints.md`), the 22-provider transparency audit and grades
(`reports/provider-transparency.md`), the dated endpoint snapshot behind the numbers below
(`findings/provider_spread_reference.json`), and an interactive data explorer.

This skill has two modes. Pick based on the task. **Both start with Step 0.**

---

## Step 0 — re-check the world before you advise (dispatch subagents, in parallel)

Everything below has a shelf life of weeks. Endpoints rotate, providers requantize without
announcing it, and vendor lifecycle policies get rewritten under stable URLs. We audited
22 providers for whether they publish serving changes (`reports/provider-transparency.md`):
**almost none do.** Providers announce launches and they announce retirements; a change to how an
endpoint serves an existing model ID is the event nobody logs — and it is exactly the event that
invalidates a result without changing a line of the caller's code.

So do not answer from this file alone. Before giving routing advice for a specific project, send
these out **concurrently, in one message**, and wait:

| Agent | Question | Must return |
| --- | --- | --- |
| **endpoints** | For each model slug this project actually uses, what endpoints exist *right now*? | The live `GET /api/v1/models/{author}/{slug}/endpoints` JSON — quantization, context, max output, `supported_parameters` per endpoint. A call, not a search. |
| **the pinned provider** | For the endpoint we're about to recommend, what does the provider currently say it serves, and has it changed? | Provider's own docs/changelog + a direct quote with a URL. Say "not found" rather than inferring. |
| **router defaults** | Have OpenRouter's routing defaults, `provider` fields, or slug suffixes changed since this skill was written? | Current docs for `require_parameters`, `allow_fallbacks`, `data_collection`, `sort`, `only`/`order`, `quantizations`. |
| **new measurements** | Any new independent measurement of cross-provider divergence since 2026-07? | Citations with numbers, or an explicit "nothing new found." |

Two rules for what comes back:

1. **Rank the evidence and say which class each finding is.** Our own measurement beats independent
   prior work beats a vendor's assertion about itself. A provider's docs are *testimony* — usable,
   attributable, and not proof. Label it that way in what you tell the user.
2. **A quantization label is self-reported and unaudited, whoever repeats it.** If the answer
   matters, the endpoints API is a stronger source than a docs page, and an actual A/B rerun
   (`reports/provider-ab-experiment-plan.md`) is stronger than both.

Skip Step 0 only for a question that doesn't depend on current state ("what does
`require_parameters` do?"). Anything of the form "which provider should I use" or "is this repo
safe" depends on it.

---

## The evidence (use these numbers; don't hand-wave)

**A real natural experiment.** `nostalgebraist/cot_legibility` logs the provider that served each
response, running the same GPQA-diamond pipeline on the same slug `deepseek/deepseek-r1`:

| Run | Served by | Illegibility (mean ± sd) | Accuracy |
| --- | --- | --- | --- |
| allow-list `[targon/fp8, Nebius]` | Targon 295/300 | **4.31** ± 2.13 | 36.6% |
| allow-list `[targon/fp8, Nebius]` | Targon **169**/300 | 4.18 ± 1.81 | 31.4% |
| pinned `novita` | novita | **2.31** ± 0.75 | 43.9% |
| pinned `novita` | novita | 2.28 ± 0.75 | 40.5% |

~88% swing in the headline metric and a 12.5-point accuracy spread. *Honest caveat: the runs are
~6 months apart, so checkpoint drift is confounded with provider. Suggestive, not clean.*
Independent work also finds inference-backend choice alone can move a benchmark by ~16pp
(arXiv 2605.19537).

**Correction (2026-07-21).** Earlier versions of this skill said the 169/300 run "drifted
mid-experiment" to another backend. That was wrong, and we only caught it by going back to the raw
`inference.json`. Nebius never served a single one of those 600 requests. The missing 131 responses
are **failures**: 125 Targon 429s, plus 6 parse/None errors. The real lesson is arguably worse —
with `allow_fallbacks: false`, a two-entry allow-list did not spread load across its two entries;
it hammered one provider and **turned provider saturation into 42% missing data**, silently, in a
run whose surviving responses were still scored and reported. Verified counts for this and 27 other
runs: `findings/observed_routing.json`.

**Genuine mid-run backend mixing does happen — just not there.** In the same repo's committed
runs, **16 of 16** `qwq` GPQA runs were served by DeepInfra *and* Nebius within a single run under
one unchanged config, with splits ranging from 90/10 to 10/90. A Kimi-K2 run split 58 Novita / 42
Moonshot. An R1-Distill run with an **empty** `openrouter_provider: []` list split 47 NextBit / 40
Novita — an empty allow-list restricts nothing, it falls through to default routing. This is the
strongest evidence in this skill: not that routing *could* change mid-experiment, but that in real
published research it *did*, repeatedly, with the served provider recorded to prove it.

<!-- PRIOR-WORK FIGURES: every number below is pinned to a verified quotation in
     findings/prior_work_sources.json and guarded by tests/test_prior_work.py. -->
**Three external results worth quoting instead of arguing from first principles** (full list,
with every quotation located verbatim in its source: `reports/prior-work.md`):

- **The endpoint may not be serving the weights.** *Model Equality Testing* (ICLR 2025) ran a
  two-sample test against commercial APIs and found **11 out of 31 endpoints serve different
  distributions than reference weights released by Meta**. If you need to know which artifact
  answered you and cannot pin, this is the test to run.
- **The spread can be enormous.** Identical `gpt-oss-120b` weights on AIME25: **93.3%** via
  Cerebras/Nebius/Fireworks/DeepInfra/Novita/Together, **86.7%** Groq, **80.0%** Azure,
  **36.7%** CompactifAI.
- **Nobody reports it.** *Chasing Shadows* audited all 72 LLM-security papers at leading venues
  from 2023–2024; being unable to identify the model instance behind a result was its most
  prevalent pitfall, **present in 73.6% (53) of papers**, discussed by none of them.
<!-- END PRIOR-WORK FIGURES -->

**How much actually varies within one slug** (live endpoint sweep, 87 open-weight models —
`findings/provider_spread_reference.json`):

| What varies | Prevalence | Example |
| --- | --- | --- |
| Endpoints per model | median 4, max 30 | — |
| Both high-precision **and** ≤fp8 endpoints | **33/87** models | `gpt-oss-120b`: `cerebras/fp16` vs `wandb/fp4` |
| A 4-bit (int4/fp4) endpoint exists | **28/87** models | — |
| **Context window** differs across endpoints | **64/87** models | `llama-3.3-70b`: 6,000 vs 131,072 (21.8x) |
| **Max output tokens** differs | **73/87** models | `llama-3.3-70b`: 2,048 vs 128,000 (62.5x) |
| `seed` supported on some endpoints only | 61/87 models | — |
| `logprobs` / `top_logprobs` partial | 63/87 models | `gpt-oss-120b`: 8 of 20 endpoints |
| `structured_outputs` partial | 56/87 models | — |
| `response_format` partial | 41/87 models | — |

These counts are from a dated snapshot, and the catalog moves under you: a same-day live refetch
already showed `gpt-oss-120b`'s `logprobs` endpoint count change (`findings/best_practices_verification.json`
→ `live_drift_check`). Treat every figure here as "as of the snapshot," and re-check before you
rely on one — the drift is itself the argument for pinning and logging.

`llama-3.3-70b` is used as the worked example because the survey's repos actually benchmark it
and it shows both cliffs at once — it is *not* the extreme. The widest max-output spread in the
snapshot is `xiaomi/mimo-v2.5` at 64.0x (16,384 vs 1,048,576).

Two consequences people miss: **context/output cliffs are not a quantization problem.** A 2,048
max-output endpoint truncates chain-of-thought mid-reasoning and a 6k-context endpoint truncates
your prompt — neither is a precision issue and both change results. And `temperature` is nearly
universal (partial on only 3/87) while `seed`/`logprobs`/`structured_outputs` are coin-flips —
so "my params went through" intuitions built on `temperature` are misleading.

---

## Mode A — Authoring: call OpenRouter properly

### First, ask what to prioritize — nobody scores an A

The 22-provider audit (`reports/provider-transparency.md`) grades the 10 verified providers out of
8 — two points each on four criteria (`findings/provider_grades.json`; explorable at
`artifact/provider-transparency.html`). **The top score is 6. The A band is vacant.**

| Criterion | Asks | Scores solid (2) |
| --- | --- | --- |
| **A** serves-now | Does it say what it serves — precision, context, engine — specifically enough to check? | Cerebras · Cloudflare · Chutes |
| **B** when-it-changed | Is there a dated record of serving *changes*, not just launches and retirements? | Together · Cloudflare · Groq · DeepSeek |
| **C** what-happens-next | Is there a notice period stated in advance? | Azure · Together · Anthropic · OpenAI |
| **P** pinnable | Can a caller fix the artifact — an immutable ID, or a written promise the weights won't move? | Cerebras · Azure · xAI |

Read the right-hand column carefully: **A and P are almost disjoint.** Cerebras is the only
provider that both tells you what it serves and promises not to change it. Everyone else makes you
choose between knowing the precision and being able to pin the artifact. The split is systematic —
the labs and hyperscalers document lifecycle and never state serving precision; the GPU clouds do
the reverse — and 31% of sampled endpoints decline to declare a quantization at all.

So there is no "best provider" to hand over, and choosing one silently for the researcher hides a
tradeoff that is theirs. **Ask them** (`AskUserQuestion`), then map the answer to a config:

| If they prioritize… | Then | Because |
| --- | --- | --- |
| **Reproducibility** — a headline number, a comparison, anything re-run later | Hard endpoint pin (`only: ["provider/quant"]`, `allow_fallbacks: False`), plus per-response provenance logging | Fixes the endpoint — as close to fixing the weights as a router gets; what the tag serves is provider convention, not contract, so the log is your change-detector. Costs you availability: a down endpoint is now a hard error, which is the point |
| **Knowing what actually ran** — the model's identity is the research subject | Prefer providers that publish precision per model *and* re-verify it against the endpoints API each run; log the endpoint record with the results | Self-reported labels are unaudited; the strongest version of this is Model Equality Testing, not a docs page |
| **Being told when it changes** — a long-running eval, a leaderboard you maintain | Prefer a provider whose changelog is machine-followable, and snapshot the endpoint record every run so *you* hold the diff | Nobody logs the mutation. Your own stored snapshots are the only reliable change-detector |
| **Cost or throughput** — exploration, pilot runs, non-reported work | Default routing or a quantization floor is genuinely fine — say so | Don't sell a pin to someone whose output never reaches a reported number (§6 of the full guide) |

If they can't answer or don't care, **default to reproducibility** and say that's what you did —
it's the only choice that can be loosened later without invalidating what you already ran.

Two facts worth stating plainly when this comes up:

- **A written weight-fixity guarantee exists and is worth asking a vendor for.** Azure states it as
  a lifecycle contract rather than a convention. That is the shape of a real pin; treat "we use
  dated model IDs" without such a statement as a convention that could change.
- **A pinnable ID is not universal.** DeepSeek's API exposes only floating names — the dated tags
  are open-weight release labels, not API `model` values. For providers like that there is no
  correct configuration to recommend, only measurement after the fact. Check before you promise a
  researcher that pinning is available.

### Then set the routing

Set routing preferences under the `provider` key. Two presets, only one of which is a pin:

**Reproducibility-first** (you want the *same* weights every run — headline numbers, comparisons):
```python
extra_body={"provider": {
    "only": ["cerebras/fp16"],       # ENDPOINT TAG: pins provider AND quantization
    "allow_fallbacks": False,        # fail loudly rather than silently switch weights
    "require_parameters": True,      # only route to providers that honor temperature/seed/response_format
    "data_collection": "deny",
}}
```

**Quality-floor default** — for a call site whose whole job is one named model, this is never the
fix; use the preset above. It's only for shared infra underneath many call sites that genuinely
can't hardcode a pin because it doesn't know the model in advance — and even there, the floor must
never be the caller's *entire* safety story. If you're writing that infra, make each call site
either supply a hard pin or explicitly, visibly opt out of one (a `pin=`/`floor_only_ack=`-style
API — see `reports/openrouter-best-practices.md` §3b for the pattern and why a bare floor fails
this repo's own taxonomy). The floor itself:
```python
provider = {
    "quantizations": ["fp8", "fp16", "bf16", "fp32"],  # add "unknown" only if you need Claude/GPT/Gemini
    "data_collection": "deny",
    "sort": "exacto",                # quality-first; also disables probabilistic load balancing
    "require_parameters": True,
}
```

### Pin the endpoint, not just the vendor

`only`/`order` accept **endpoint tags** of the form `provider_slug/variant` — and for most
open-weight models the variant *is the quantization*: `cerebras/fp16`, `targon/fp8`,
`deepinfra/bf16`, `wandb/fp4`. This is the maximal pin a router offers: it fixes the declared
quantization, not just the company. It is still not a weight-fixity contract — the provider can
change what the tag serves without renaming it, which is what the endpoint snapshot below is for.
(`nostalgebraist/cot_legibility` pins this way; the docs also show region/variant forms like
`google-vertex/us-east5`.)

> **⚠️ The trap: pinning a provider does not pin quality.** MathArena pins Kimi K2.6 with
> `provider: {order: [moonshotai], allow_fallbacks: False}` — textbook-looking, fully
> deterministic routing — but the `moonshotai` endpoint serves that model at **int4**, while an
> fp8 endpoint of the same slug exists. They pinned themselves to the *worst* backend and their
> published leaderboard number is measured on it. **Always look up what the endpoint you're
> pinning actually serves.**

### Pre-flight: check the endpoints before you commit

```bash
curl -s https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints | \
  jq '.data.endpoints[] | {provider_name, quantization, context_length, max_completion_tokens, supported_parameters}'
```
Confirm: the quantization you expect · a context window that fits your prompts · a max-output cap
that fits your longest generation · the params you actually pass (`seed`, `logprobs`,
`response_format`). Endpoints rotate — re-check immediately before a run that matters.

**Save that JSON with your results.** It is not a pre-flight check to throw away; it is the only
change-detector you get. No provider changelog substitutes for it, because providers publish
launches and retirements and almost never publish the change to an endpoint that keeps its name —
so a stored endpoint record from run N, diffed against run N+1, is how you find out that the thing
you pinned started serving something else.

Then, non-negotiably:
- **Record the provider that actually served each call** — the response `provider` field, or
  `GET /api/v1/generation?id=...` (OpenRouter's schema does not document a top-level `provider`
  field on the chat response; the generation endpoint and the opt-in metadata header are the
  documented routes). Store it **per response, not per run**: routing genuinely does change
  backends mid-run — 16 of 16 `qwq` runs above split across two providers under one config.
- **Version-pin the model slug** and record the exact string.
- If you rely on **structured outputs / JSON schema** for a judge or parser, you *must* set
  `require_parameters: true` (or `only`/`order` to supporting endpoints) — otherwise the schema is
  silently ignored on some routes and your parser scores free-form text.
- Don't trust `seed` for bitwise determinism; verify empirically.
- **Report the routing config and served providers** in the paper/README. The inference stack is a
  hyperparameter.

Key facts (so you can reason about edge cases):
- Default routing = load-balance by inverse-square of price; identical requests hit different
  providers. Setting `sort` **or** `order` disables load balancing.
- `require_parameters` defaults to **false** → unsupported params are silently ignored.
- `data_collection` defaults to **"allow"** → prompts may go to train-on-your-data providers.
- `allow_fallbacks` defaults to **true** → your pin is a *preference*, not a guarantee, until you
  set it false. With it false, a down endpoint is a hard error — post-filter errored rows before
  computing metrics rather than letting them silently shrink n.
- Documented slug suffixes are `:nitro` (=`sort:throughput`) and `:floor` (=`sort:price`, cheapest
  and usually most quantized — avoid for research). `:exacto` is **not** documented as a suffix
  even though `sort: "exacto"` is a valid dict value. Prefer the `provider` dict either way, so
  the recorded model name stays clean.
- There is **no** per-provider slug suffix (you cannot write `model:fireworks`) — a pin must go in
  the request body's `provider` field. A repo is only pinnable if it has `extra_body`-style
  plumbing or one editable call site.
- Quantization labels are **self-reported by providers**, not audited. Strong circumstantial
  evidence of a quality gap, not a certification — and often not even offered: across 42 endpoints
  for 6 widely-served open-weight models, **31% declared no quantization at all** (7 providers
  declared nothing anywhere in the sample). A missing label is the provider's silence, not
  OpenRouter's.
- Proprietary models (Claude/GPT/Gemini) are effectively single-served → quantization/provider
  risk is low; open-weight models are where it bites hardest.

Full guide: [`reports/openrouter-best-practices.md`](https://github.com/AMindToThink/openrouter_reliable_research_search/blob/master/reports/openrouter-best-practices.md)
in the openrouter_reliable_research_search repo.

---

## Mode B — Auditing a codebase's OpenRouter usage

Goal: decide whether their results could be **silently corrupted** by provider routing, and
classify any mistakes against the taxonomy (`M1..M12`, below).

### Step 1 — Run the bundled static scanner (first pass)
```bash
uv run scripts/audit_openrouter.py <repo_path>        # human-readable
uv run scripts/audit_openrouter.py <repo_path> --json # machine-readable, exits 1 on High findings
```
It finds router call sites and flags missing safeguards. **It is heuristic** — it catches literal
`openrouter/...` slugs, `OPENROUTER_API_KEY`, and `openrouter.ai/api`, but *not* models passed
dynamically (e.g. via argv/config). Always pair it with Step 2.

### Step 2 — Grep + read the actual call path (don't skip this)
```bash
grep -rInE "openrouter|OPENROUTER_API_KEY|base_url|require_parameters|quantizations|data_collection|extra_body|provider\s*[:=]" <repo> \
  --include=*.py --include=*.yaml --include=*.yml --include=*.toml --include=*.json
```
For each call site, determine:
1. **What is OpenRouter used for?** Eval, LLM-judge, agent rollout, data generation? Does its
   output feed a *reported number, a training set, or a safety measurement*? (That's a "critical
   route" — mistakes there actually invalidate results; on a throwaway script they're minor.)
2. **Open-weight or proprietary model?** Open-weight ⇒ high quantization/provider risk.
3. **Which safeguards are present?** quantizations · require_parameters · data_collection:deny ·
   order/only/sort · allow_fallbacks:false · provenance logging.
4. **If they pinned — what does the pinned endpoint actually serve?** Look it up (Mode A
   pre-flight). A confident-looking pin onto an int4 endpoint is worse than it looks.
5. **Is the model itself the research subject** (interrogation/red-teaming/probing/judge/
   benchmark/comparison)? If yes, a `quantizations` floor with no `order`/`only` pin is still
   **M1** — the fix is recipe 3a, a hard endpoint pin, never recipe 3b's fleet floor.

**`inspect_ai` is plumbing, not a safeguard — but the plumbing is enough.** `OpenRouterAPI.__init__`
only *collects* whatever `provider` dict the caller passes and `completion_params()` forwards it to
`extra_body["provider"]` unchanged; it sets no `quantizations` floor, no `require_parameters`, no
`order`/`allow_fallbacks`, no `data_collection` of its own, and captures no provenance beyond the
raw response it logs for every provider. So don't credit an inspect-based repo for safety it didn't
configure — but equally, any inspect-based eval (much of the safety ecosystem — Inspect Evals,
openbench, …) *is* pinnable via `-M provider='{...}'` with **zero source edits**. "They can't
easily fix this" is a rare excuse, and the one-line fix is concrete.

### Step 3 — Classify against the taxonomy

| ID | Mistake | Sev | Seen in | Tell-tale |
| --- | --- | --- | :---: | --- |
| M4 | No provenance logging | High | 28/35 | served `provider`/generation id never stored |
| M5 | Data-policy leakage | Med | 27/35 | `data_collection` left `allow` |
| M1 | Unpinned quantization | High | 26/35 | no `quantizations` |
| M3 | Probabilistic provider routing | High | 26/35 | no `order`/`only`/`sort` |
| M2 | Silent parameter dropping | High | 22/35 | sampling params + no `require_parameters` |
| M6 | Model version drift | Med | 22/35 | bare undated slug |
| M8 | Cross-provider comparison confound | High | 21/35 | models compared, none pinned |
| M10 | No reporting | Med | 13/35 | paper/README says nothing about routing/stack |
| M7 | seed→determinism assumption | Med | 3/35 | relies on `seed` for reproducibility |
| M9 | Judge on unconstrained route | High | 3/35 | `response_format`/schema without `require_parameters` |
| M11 | Silent backend mixing | Med | 3/35 | some calls direct, some via router, same "model" |
| M12 | Cheap/degraded route chosen | Med | 1/35 | `:floor` / `sort:price` on a research path |

*"Seen in" = base rates from our 35-repo survey of published research code — check the top four
first; they're the ones almost everyone misses.* Not in the table because nobody in the survey
guarded against it: **context/max-output cliffs** (see the evidence section). If a repo relies on
long prompts or long CoT and pins nothing, add it as a finding under M1's spirit.

### Step 4 — Verdict: use four classes, not "safe / unsafe"

A plain safe/unsafe split **overstates the good news**, because it lumps genuine successes together
with repos that simply never routed a result through OpenRouter. Classify as:

| class | meaning | survey n |
| --- | --- | :-: |
| `at_risk` | OpenRouter output reaches a reported result, with an uncontrolled channel open | 31 |
| `handled` | reaches a reported result **and** controls for it — the only real positive | 1 |
| `not_on_result_path` | OpenRouter present in the repo, but no reported result depends on it | 2 |
| `no_usage_found` | no OpenRouter call site at all (discovery false positive) | 1 |

A repo that never routes a research call through OpenRouter has demonstrated **nothing** about
using OpenRouter well — don't credit it as a success story, and don't put it in the denominator
either. Score against the repos where OpenRouter output actually reaches a published result
(`at_risk + handled`): the survey headline is **31/32 (97%)** at risk. Counting every repo that
merely contains a call site gives the wider, weaker 31/34 (91%).

**Be fair (this matters):** don't hunt for mistakes. Legitimate non-mistakes: proprietary
single-served models (M1/M3/M8 don't apply); explicitly exploratory/qualitative work; provider
pinned **and** provenance logged even if not every knob is set. When you assert "at risk," cite the
exact file:line and say which reported result it threatens — and remember the honest framing:
*at risk* means *exposed to an uncontrolled corruption channel*, **not** that a published number is
wrong. Impacted findings are hypotheses worth checking, not demonstrated errors, unless you
actually re-ran the experiment across providers.

### Step 5 — Report
Per repo: what they use OpenRouter for · open/proprietary · safety_class · mistakes (M-ids + the
threatened result) · severity · a one-line fix. Full method + dataset schema:
`findings/taxonomy.md`, `findings/methodology.md`, and the 35-repo dataset in `findings/survey.csv`
of the openrouter_reliable_research_search repo. To go beyond static audit to proof, see
`reports/provider-ab-experiment-plan.md` — how to rerun a repo's own code changing nothing but the
pinned endpoint.

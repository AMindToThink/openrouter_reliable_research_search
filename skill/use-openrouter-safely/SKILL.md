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

This skill has two modes. Pick based on the task.

---

## The evidence (use these numbers; don't hand-wave)

**A real natural experiment.** `nostalgebraist/cot_legibility` logs the provider that served each
response, running the same GPQA-diamond pipeline on the same slug `deepseek/deepseek-r1`:

| Run | Served by | Illegibility (mean ± sd) | Accuracy |
| --- | --- | --- | --- |
| unpinned | Targon 295/300 | **4.31** ± 2.13 | 36.6% |
| unpinned | Targon **169**/300 | 4.18 ± 1.81 | 31.4% |
| pinned `novita` | novita | **2.31** ± 0.75 | 43.9% |
| pinned `novita` | novita | 2.28 ± 0.75 | 40.5% |

~88% swing in the headline metric and a 12.5-point accuracy spread. **One unpinned run drifted
mid-experiment** — only 169 of 300 responses came from Targon, so a *single run* was served by
multiple backends. *Honest caveat: the runs are ~6 months apart, so checkpoint drift is confounded
with provider. Suggestive, not clean.* Independent work also finds inference-backend choice alone
can move a benchmark by ~16pp (arXiv 2605.19537).

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

Set routing preferences under the `provider` key. Two good presets:

**Reproducibility-first** (you want the *same* weights every run — headline numbers, comparisons):
```python
extra_body={"provider": {
    "only": ["cerebras/fp16"],       # ENDPOINT TAG: pins provider AND quantization
    "allow_fallbacks": False,        # fail loudly rather than silently switch weights
    "require_parameters": True,      # only route to providers that honor temperature/seed/response_format
    "data_collection": "deny",
}}
```

**Quality-floor default** (shared infra that doesn't know the model in advance — never for a call
site whose whole job is one named model; that always needs the preset above instead):
```python
provider = {
    "quantizations": ["fp8", "fp16", "bf16", "fp32", "unknown"],  # keep "unknown" only if you need Claude/GPT/Gemini
    "data_collection": "deny",
    "sort": "exacto",                # quality-first; also disables probabilistic load balancing
    "require_parameters": True,      # add this if you pass sampling params or use structured outputs
}
```

### Pin the endpoint, not just the vendor

`only`/`order` accept **endpoint tags** of the form `provider_slug/variant` — and for most
open-weight models the variant *is the quantization*: `cerebras/fp16`, `targon/fp8`,
`deepinfra/bf16`, `wandb/fp4`. This is the maximal pin: it fixes the weights, not just the
company. (`nostalgebraist/cot_legibility` pins this way; the docs also show region/variant forms
like `google-vertex/us-east5`.)

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

Then, non-negotiably:
- **Record the provider that actually served each call** — the response `provider` field, or
  `GET /api/v1/generation?id=...`. Store it **per response, not per run**: unpinned routing can
  drift mid-experiment (see the 169/300 case above).
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
  evidence of a quality gap, not a certification.
- Proprietary models (Claude/GPT/Gemini) are effectively single-served → quantization/provider
  risk is low; open-weight models are where it bites hardest.

Full guide: `reports/openrouter-best-practices.md` in the openrouter_reliable_research_search repo.

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

**`inspect_ai` is the reference plumbing.** `OpenRouterAPI.__init__` collects a `provider` dict
model-arg and emits it as `extra_body["provider"]`, so any inspect-based eval (much of the safety
ecosystem — Inspect Evals, openbench, …) is pinnable via `-M provider='{...}'` with **zero source
edits**. That makes "they can't easily fix this" a rare excuse, and makes the one-line fix concrete.

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

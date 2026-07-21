# Which experiment should we rerun to *prove* provider routing corrupts research?

The survey (`findings/`) is a **static** audit: 31/35 important repos leave a provider-routing
corruption channel open. It does not show that any published number is wrong. This report picks
the experiments that would close that gap empirically — rerun *their own code*, change *nothing*
but the pinned OpenRouter provider, and see whether the conclusion moves.

**Selection constraint (from the brief):** the only permitted intervention is "rerun their code
and pin a provider" — a config/CLI/env pin, or at worst a one-line edit at a single call site.
Anything requiring glue code, Docker/K8s, GPUs, browsers, or paid third-party services is out.

## How the candidates were found

35 screening agents (one per surveyed repo) shallow-cloned each repo and traced the call path from
entry point to HTTP body, required to prove a `provider` dict can reach the wire. No repo's code
was executed. Provider ground truth came from the live OpenRouter endpoints API for all 156
open-weight models (`findings/provider_spread_reference.json`).

Two mechanism facts, verified by hand, shape everything below:

1. **There is no per-provider model-slug suffix.** Only `:nitro`, `:floor`, `:free`. A pin must go
   in the request body's `provider` field, so a repo is viable only if it has `extra_body`-style
   plumbing (or one editable call site).
2. **`provider.only` accepts endpoint tags of the form `slug/quant`** — e.g. `cerebras/fp16`,
   `wandb/fp4`. This is the maximal pin: it fixes the *quantization*, not just the vendor.
   Confirmed independently by `nostalgebraist/cot_legibility`, which pins with exactly this form
   (`targon/fp8`, `deepinfra/bf16`).

`inspect_ai` is plumbing, not a safety feature — checked directly against the real source
(`UKGovernmentBEIS/inspect_ai` @ `8ebc782`), it earns no "reference implementation" label. Its
`OpenRouterAPI.__init__` only *collects* whatever `provider` dict the caller passes via
`-M provider=...` (`inspect_ai/model/_providers/openrouter.py:108-112`) and `completion_params()`
forwards it to `extra_body["provider"]` unchanged (`:372-385`); it sets no default `quantizations`
floor, `require_parameters`, `order`/`allow_fallbacks`, or `data_collection` of its own — the
provider docs' only worked example for `provider` is `{'quantizations': ['int8']}`, and the other
three are never mentioned (`docs/providers.qmd:1542-1549`; also <https://inspect.aisi.org.uk/providers.html>).
It has no OpenRouter-specific provenance capture either (M4): Inspect logs the full raw response
for every call regardless of provider (`openai_compatible.py:258-264`), and OpenRouter's response
body now carries an `openrouter_metadata.endpoints` block naming the served provider (confirmed
against the live `openrouter.ai/openapi.json` schema), so that provenance rides along into the
`.eval` log by accident — undocumented, and never surfaced as a field — not because inspect_ai
built anything to capture it. The fact worth keeping: because the caller's dict reaches the wire
untouched, **any** inspect-based eval genuinely is pinnable via `-M provider='{...}'` with zero
source edits — that's plumbing the recommendations below rely on, nothing more.

## The quality cliffs hiding under one model name

Not just quantization. From the endpoint sweep:

| Cliff | Worst case | Consequence |
| --- | --- | --- |
| Quantization | `gpt-oss-120b`: `cerebras/fp16` vs `wandb/fp4` | silent accuracy loss |
| Context window | `llama-3.3-70b`: `novita/bf16` **6,000** vs `together/fp8` **131,072** (21.8x) | prompt truncation / hard error |
| Max output | `llama-3.3-70b`: `together/fp8` **2,048** vs `wandb/fp16` **128,000** (62x) | chain-of-thought cut off mid-reasoning |
| Logprobs | `gpt-oss-120b`: only 8 of 20 endpoints expose them | your logprobs silently vanish |

**Design preference:** structural cliffs (6k context) tend to *crash*. A crash is a weaker
demonstration than a plausible-but-wrong number, because the whole thesis is that the corruption is
invisible. The recommendations below therefore favour **precision gaps over structural gaps**.

---

## Recommended #1 — MathArena (ETH Zurich SRI Lab): Kimi K2.6 on AIME/HMMT

**Why this one.** A live, widely-cited leaderboard for uncontaminated competition math — the
frontier-reasoning case where one flipped token changes the final boxed integer. Auto-graded, so
there is no judge confound.

**Finding worth reporting on its own:** `configs/models/moonshot/k26.yaml` pins
`provider: {order: [moonshotai], allow_fallbacks: False}`, and the `moonshotai` endpoint is served
**int4**. MathArena's published Kimi-K2.6 number is measured on an int4 backend while an fp8
endpoint of the same slug exists.

- **Pin:** zero-config. Copy the YAML, change the `order` list. (`src/matharena/runner.py:293`
  splats `extra_body` verbatim; six sibling configs already use this shape.)
- **Pair:** `streamlake/fp8` ($0.855/$3.60 per Mtok) vs `moonshotai/int4` ($0.95/$4.00). Both ~100% uptime.
- **Matrix:** no control/experimental split, so: strong / weak / strong-replicate (the replicate
  establishes the noise floor, without which a delta is uninterpretable).
- **Scale:** 30 problems x n=4 x 2 competitions x 3 conditions = 720 samples, ~7.2M output tokens.
- **Cost: ~$42. Wall-clock: ~1.9 h** at the repo's own `concurrent_requests: 32`.

```bash
cp configs/models/moonshot/k26.yaml configs/models/moonshot/k26_weak.yaml    # order: [moonshotai]  (int4)
cp configs/models/moonshot/k26.yaml configs/models/moonshot/k26_strong.yaml  # order: [streamlake], quantizations: [fp8]
uv run python scripts/run.py --comp aime/aime_2026 --models moonshot/k26_weak   --n 4
uv run python scripts/run.py --comp aime/aime_2026 --models moonshot/k26_strong --n 4
```

## Recommended #2 — openbench (Groq): `gpt_oss_aime25`

**Why this one.** The best precision gap available anywhere in the survey (fp16 vs fp4 on one
slug), it replicates a headline number from OpenAI's own gpt-oss release, and it is nearly free.
Both endpoints expose logprobs, so the divergence can additionally be read out distributionally.

- **Pin:** zero-config. `-M` is `yaml.safe_load`-parsed (`_cli/utils.py:39-59`) and forwarded into
  inspect_ai's `eval()`. **Note:** `-M only=Cerebras` is wrong; the whole dict goes under `provider`.
- **Pair:** `cerebras/fp16` ($0.35/$0.75, 100% uptime) vs `wandb/fp4` ($0.04/$0.14, 95% uptime).
- **Scale:** 30 AIME-2025 questions x `epochs=8` (hardcoded) = 240 completions/arm; 3 conditions = 720.
- **Cost: ~$3.20. Wall-clock: <1 h.**

```bash
bench eval gpt_oss_aime25 --model openrouter/openai/gpt-oss-120b \
  -M provider='{"only": ["cerebras/fp16"], "allow_fallbacks": false, "require_parameters": true}' \
  --reasoning-effort high --logfile strong.eval
bench eval gpt_oss_aime25 --model openrouter/openai/gpt-oss-120b \
  -M provider='{"only": ["wandb/fp4"], "allow_fallbacks": false, "require_parameters": true}' \
  --reasoning-effort high --logfile weak.eval
```

## Recommended #3 — EQ-Bench Creative Writing v3: the full pathological matrix

**Why this one.** The only clean fit for strong-weak / weak-strong / strong-strong, because
test-model and judge-model are two independently pinnable roles. Judge scores are parsed by regex
(`core/scoring.py:15-32`), so a degraded judge produces wrong-but-plausible numbers rather than a
crash — precisely the silent corruption we want to exhibit.

- **Pin:** one line. `utils/api.py:220-296` builds a bare dict shipped by
  `requests.post(..., json=payload)` at `:297-302`; insert `payload["provider"] = {...}`.
- **Pair:** `cerebras/fp16` vs `wandb/fp4` on `openai/gpt-oss-120b`, applied per role.
- **Efficiency:** `--redo-judging` re-scores frozen generations, so generation is paid once.
- **Cost: ~$1. Wall-clock: ~1 h.**

| | Judge strong | Judge weak |
| --- | --- | --- |
| **Test strong** | correct baseline | pathological |
| **Test weak** | pathological | (optional floor) |

---

## Free evidence we already have: `nostalgebraist/cot_legibility`

The repo our survey marked **safe** already contains the natural experiment, because it logs which
provider served each response (`src/inference/providers.py:104`). Same slug
`deepseek/deepseek-r1`, same GPQA-diamond pipeline:

| Run | Served by | Illegibility (mean ± sd) | Accuracy |
| --- | --- | --- | --- |
| 2025-10-14 19:05 | allow-list `[targon/fp8, Nebius]` → Targon 295/300 | **4.31** ± 2.13 (n=295) | 36.6% |
| 2025-10-14 20:10 | allow-list `[targon/fp8, Nebius]` → Targon **169**/300 | 4.18 ± 1.81 (n=169) | 31.4% |
| 2026-04-19 | pinned `novita` | **2.31** ± 0.75 (n=198) | 43.9% |
| 2026-04-19 | pinned `novita` | 2.28 ± 0.75 (n=300) | 40.5% |

An ~88% swing in the headline metric, and a 12.5-point accuracy spread. **Correction:** an earlier
version of this plan said the second run "drifted mid-experiment." It did not — Nebius, the second
entry in its allow-list, served none of the 600 requests across both runs. The 131 missing
responses are failures (125 Targon 429s, 6 parse/None errors): with `allow_fallbacks: false`, a
two-entry allow-list did not spread load, it converted provider saturation into 42% missing data.
Counts re-derived from the raw `inference.json` in `findings/observed_routing.json`. Mid-run
backend *mixing* is real and documented elsewhere in the same repo (16/16 `qwq` runs split across
DeepInfra and Nebius) — just not in this run.

**Honest caveat:** those runs are ~6 months apart, so checkpoint drift is confounded with provider.
This is suggestive, not clean — and it is exactly the argument for running the paired same-day A/B.
Rerunning is zero-config, but `deepseek/deepseek-r1` now has only two live endpoints (`azure` vs
`novita/fp8`), a modest and partly-unknown quality gap. ~$15, ~1 h.

## Optional add-on: direct logprob divergence probe (~$0.50)

The sharpest possible readout, and no repo in the survey does it. Send an identical prompt set to
`openai/gpt-oss-120b` pinned to `cerebras/fp16`, `dekallm/bf16`, `novita/fp4`, `wandb/fp4` — all
four expose logprobs — and compare top-20 token distributions: KL divergence, top-1 agreement rate,
rank correlation over lesser-probability tokens. Quantization shows up immediately and
quantitatively, with no benchmark noise in the way.

**This is not a rerun of anyone's code** — it needs ~50 lines of new script, so it sits outside the
brief's constraint. Flagged because it is the cheapest, most legible evidence available and would
make a strong figure.

## Program totals

| | Cost | Wall-clock |
| --- | --- | --- |
| #1 MathArena | ~$42 | ~1.9 h |
| #2 openbench AIME | ~$3 | <1 h |
| #3 EQ-Bench 2x2 | ~$1 | ~1 h |
| **All three** | **~$46** | **~2 h** (parallel) / ~4 h (serial) |

Comfortably inside the 6-hour target. Cost is dominated by MathArena's reasoning-token volume.

## Risk register

- **Reasoning-token blowup.** Every estimate hinges on output length for thinking models. Pilot
  with `--limit`/`--n 1` before committing. MathArena's cost could swing 2-3x.
- **Provider catalog drift.** Endpoints rotate. Re-check `/api/v1/models/{slug}/endpoints`
  immediately before running; `tests/test_ab_column.py` pins the pairs against the snapshot.
- **`allow_fallbacks: false` means hard failure**, not rerouting. Post-filter errored rows before
  computing accuracy, and prefer the high-uptime endpoints listed above.
- **Self-reported quantization.** The `fp16`/`fp4` tags come from providers, not from an audit.
  Strong circumstantial evidence of a quality gap, not a certification.
- **The null result.** If strong and weak agree within noise, that is a *publishable* finding too —
  it bounds the risk the survey describes. Report it either way; the replicate arm exists precisely
  so a null can be distinguished from an underpowered test.
- **Log the served provider.** Whatever runs, record the `provider` field OpenRouter echoes back.
  Without it we repeat the mistake we are documenting.

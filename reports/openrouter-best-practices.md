# Using OpenRouter (and similar routers) reliably for research

**One-sentence version:** By default, OpenRouter treats "a model" as a name that can be
served by *any* of several providers, at *any* quantization, on *any* inference engine, with
*silently dropped* sampling parameters — so unless you pin routing explicitly, the artifact
you evaluated is not a fixed object and your numbers may not reproduce or generalize.

This guide is grounded in OpenRouter's own docs, community practice, and one strong reference
implementation (Redwood Research's Control Tower). It is written for people who use OpenRouter
to *produce research results* — evals, LLM-as-judge scores, agent rollouts, or generated data.

---

## 1. What OpenRouter actually does by default

OpenRouter is a unified API in front of dozens of independent inference providers. For any
given model slug (e.g. `deepseek/deepseek-r1`) there are often several providers, and they are
**not interchangeable**. What varies between them:

- **Quantization.** A provider may serve the model at `fp16`, `bf16`, `fp8`, or all the way
  down to `int4`/`fp4`. Lower precision is cheaper and faster and *usually* close — but "close"
  is not "identical," and degradation is prompt-dependent and worst on the hard/long-tail
  inputs that research often cares about. OpenRouter's own docs warn: *"Quantized models may
  exhibit degraded performance for certain prompts, depending on the method used."*
- **Inference engine & settings.** vLLM vs SGLang vs TensorRT-LLM vs a bespoke stack, each with
  different kernels, prefix caching, and logit-processing defaults. Independent work ("The
  Silent Hyperparameter", 2026) finds backend choice *alone* can move a benchmark score by up
  to **~16.6 percentage points**, and that across 35,000 ML papers the inference stack is
  almost never reported.
- **Which parameters are honored.** Providers that don't support a parameter in your request
  **still receive the request and silently ignore the unknown parameter** — unless you opt in
  to `require_parameters: true`. This silently voids `temperature`, `top_p`, `seed`,
  `logprobs`, `response_format`/structured outputs, `stop`, tool-calling, etc., on providers
  that lack them.
- **Which provider you get at all.** With no routing preferences, OpenRouter load-balances:
  it prioritizes providers with no outage in the last ~30 seconds, then samples the
  lowest-cost ones weighted by the **inverse square of price**. So *two identical requests can
  hit two different providers*, and cheaper-hence-more-quantized endpoints are favored.
- **What happens to your prompts.** `data_collection` defaults to **`"allow"`**, meaning
  requests may route to providers that retain prompts to train on. For proprietary eval sets,
  red-team prompts, or unpublished data, this is a leak.

Crucial consequence: **setting `provider.sort` or `provider.order` disables load balancing**
(routing becomes deterministic-ish), while leaving them unset means routing is probabilistic.

### The default is not the safe default — and tooling won't fix it for you

In `QwenLM/qwen-code` PR #348, a contributor tried to make the tool default to full-precision
providers (`provider.quantizations = fp8+`) because quantized routing "can result in
substantially worse output for coding." **The PR was rejected** — maintainers considered a
baked-in precision opinion too paternalistic ("would silently change behavior for everyone").
The lesson for researchers: *no one upstream is going to pin this for you.* If your results
depend on which weights actually ran, you must set the routing yourself.

---

## 2. The parameters that matter (the `provider` object)

Pass these under the `provider` key (OpenAI-SDK users: `extra_body={"provider": {...}}`;
Inspect users: the `provider=` model arg; raw HTTP: top-level `"provider"`).

| Field | Default | Set it to… | Why |
| --- | --- | --- | --- |
| `quantizations` | *(unset → any)* | `["fp8","fp16","bf16","fp32"]` (add `"unknown"` only if you must reach proprietary models) | Stop silently landing on int4/fp4/int8. |
| `require_parameters` | `false` | `true` | Force routing only to providers that honor your `temperature`/`seed`/`response_format`/tools. Prevents silent parameter dropping. |
| `data_collection` | `"allow"` | `"deny"` | Don't send prompts to train-on-your-data providers. Use ZDR/`zdr:true` to also exclude operational retention. |
| `order` | *(unset)* | `["provider-slug"]` | Pin a single named provider for maximum reproducibility (disables load balancing). |
| `only` / `ignore` | *(unset)* | allow-list / block-list of slugs | Whitelist trusted providers, or exclude a known-bad one. `ignore` is safer than `only` (excluding one bad provider can't 404 you the way pinning one can if it goes down). |
| `allow_fallbacks` | `true` | `false` **only** if you pinned `order`/`only` and want hard reproducibility | With fallbacks on, you can still drift among the *filtered* set. Off = fail rather than silently switch. |
| `sort` | *(unset)* | `"exacto"` (quality-first, tool-call-accuracy sort) or `"throughput"`/`"latency"`/`"price"` | Deterministic ordering; `exacto` favors higher-quality endpoints. Note: setting `sort` disables load balancing. |

Model-slug shortcuts: `:nitro` = `sort:throughput`, `:floor` = `sort:price`, `:exacto` =
`sort:exacto`. Prefer the `provider` dict over the slug suffix so the **model name stays clean**
in your logs, cost accounting, and metadata (routing preference belongs in `provider`, not in
the identifier you record as "the model").

---

## 3. Two safe recipes

**Which one do you reach for?** Ask first: *is the specific model's identity — its weights,
checkpoint, or provider — the thing your research is about?* If you're interrogating, red-teaming,
probing, judging, or benchmarking one named model, the answer is yes, and **3a is mandatory** — a
quality floor is not a pin, no matter how good the floor. 3b is a legitimate choice only for shared
infrastructure that must serve whichever model a caller passes in, where no single call path knows
or cares in advance which one that will be. Don't let "3b is Control Tower's own default" become a
reason to skip 3a at a call site that already knows exactly which model it needs — see the trap
below.

### 3a. Reproducibility-first (you want the *same* weights every run)

Pin one provider and forbid drift. Accept that the run fails loudly if that provider is down —
which is what you want, versus silently switching to a different artifact mid-experiment.

```python
# OpenAI SDK against OpenRouter
resp = client.chat.completions.create(
    model="deepseek/deepseek-r1",
    messages=msgs,
    temperature=0,
    seed=12345,               # honored only if the provider supports it — see require_parameters
    extra_body={"provider": {
        "order": ["fireworks"],          # the exact provider you validated
        "allow_fallbacks": False,        # fail rather than switch weights
        "require_parameters": True,      # don't route to a provider that ignores tem\seed
        "quantizations": ["fp8", "fp16", "bf16", "fp32"],
        "data_collection": "deny",
    }},
)
```

Then **record the actual provider that served each response** (see §4).

### 3b. Quality-floor / fleet default (many models, provider-agnostic, but never garbage)

You can't pin one provider across many heterogeneous models, but you can guarantee a floor.
This is the Control Tower pattern and a good project-wide default:

```python
OPENROUTER_PROVIDER_DEFAULTS = {
    "quantizations": ["fp8", "fp16", "bf16", "fp32", "unknown"],  # "unknown" kept so Claude/Gemini/GPT still route
    "data_collection": "deny",
    "sort": "exacto",            # quality-first ordering; also disables load balancing
    # consider adding: "require_parameters": True  (see the gotcha below)
}
```

Trade-off they consciously accept: `"unknown"` lets open-weight providers that *decline to
disclose* their precision slip past the fp8 floor. They lean on the `exacto` quality sort +
empirical tool-call accuracy to catch bad endpoints instead. If you don't need proprietary
models in the same call path, **drop `"unknown"`** for a hard precision floor.

> **⚠️ The trap: copying the floor into an identity-sensitive call site.** A downstream research
> script that interrogates one specific "untrusted model" (or judges it with a fixed "judge
> model") is not in the same position as a shared library serving arbitrary callers — that script
> already knows exactly which model it needs. Recommending the 3b floor as *the* fix for such a
> call site — or worse, waving off `allow_fallbacks: false` with "there's no pin to protect" — gets
> the logic backwards: the floor is what infra falls back to when it *doesn't* know the model in
> advance. The call site should pin its endpoint (3a) on top of, not instead of, any shared floor.
> This exact mistake is taxonomy entry **M13** (`findings/taxonomy.md`).

---

## 4. Reproducibility & reporting checklist

Treat the provider/inference stack as a first-class hyperparameter — because it is.

- [ ] **Pin quantization** (`quantizations`) to a precision floor you trust.
- [ ] **Set `require_parameters: true`** if you depend on `temperature`/`seed`/`logprobs`/
      `response_format`/tools. (Otherwise a provider silently ignoring them corrupts results.)
- [ ] **Pin the provider** (`order` + `allow_fallbacks:false`) for any headline number you want
      to reproduce, or at minimum `sort`/`only` to a trusted set.
- [ ] **Set `data_collection: "deny"`** (or `zdr`) for any non-public prompt data.
- [ ] **Log the served provider for every call.** OpenRouter returns it: the response `provider`
      field, or query the generation via `GET /api/v1/generation?id=...`. Save it alongside
      outputs. "We used deepseek-r1 via OpenRouter" is *not* a reproducible method statement.
- [ ] **Report the routing config** (the whole `provider` dict) and the observed provider
      distribution in your paper/appendix, the same way you'd report temperature.
- [ ] **Don't assume `seed` gives determinism.** Even honored, most providers don't guarantee
      bitwise reproducibility; batching/kernels make it best-effort. Verify empirically.
- [ ] **Version-pin the model slug.** A bare slug can silently point at an updated snapshot;
      prefer dated/versioned slugs where they exist and record the exact string.
- [ ] **Spot-check across the routes you'll actually hit.** OpenRouter's own advice: *"flexibility
      requires measurement — evaluate important models across the actual provider routes."*

---

## 5. The `require_parameters` gotcha (the subtle one)

Many judges/graders rely on **structured outputs / provider-enforced JSON** (`response_format`
with a JSON schema) so the model can't return unparseable text. But `response_format` is
exactly the kind of parameter a provider may not support. Without `require_parameters: true`,
OpenRouter can route your judge call to a provider that **ignores the schema**, returns
free-form prose, and either (a) fails your parser, or worse (b) gets "recovered" by lenient
parsing into a wrong-but-plausible score. Any judge/grader path that assumes constrained
decoding **must** set `require_parameters: true` (or `only`/`order` to providers that support
it). This is easy to miss because it fails intermittently — only when routing happens to pick a
non-supporting provider.

---

## 6. When is default OpenRouter *fine*?

Not every use needs the full treatment. It's fine to be relaxed when:

- The model is **proprietary and single-served** (Claude/GPT/Gemini via their own API through
  OpenRouter): there's effectively one backend, so quantization/provider-switching risk is low.
  (You still care about `data_collection` and version drift.)
- You're doing **exploratory / qualitative** work where a few percent of output variance is
  irrelevant to the conclusion.
- Cost/latency dominate and the result is robust to backend noise (you've checked).

It is **not** fine when: you report benchmark numbers, compare models, measure subtle
propensities or safety behaviors, generate training data, or need run-to-run reproducibility —
especially on **open-weight** models where quantization and provider choice bite hardest.

---

## 7. "Similar" routers

The silent-provider-switching risk is specific to **multi-provider routers**: OpenRouter
(dominant), Requesty, Vercel AI Gateway, Unify, Martian, and self-hosted **LiteLLM proxies**
configured with multiple upstreams. Single-provider hosts (Together, Fireworks, DeepInfra,
Novita, Hyperbolic) serve one backend — you still must record *which* host and its quantization,
but there's no per-request switching. Direct first-party APIs (Anthropic/OpenAI/Google) are the
most controlled, at higher cost and less model coverage.

---

## Sources

- OpenRouter — Provider Routing docs: <https://openrouter.ai/docs/features/provider-routing>
- OpenRouter — Model Routing (blog): <https://openrouter.ai/blog/insights/model-routing/>
- OpenRouter — Reliability/Failover (blog): <https://openrouter.ai/blog/insights/reliability-failover/>
- "The Silent Hyperparameter: Quantifying the Impact of Inference Backends on LLM Reproducibility" — <https://arxiv.org/abs/2605.19537>
- "Chasing Shadows: Pitfalls in LLM Security Research" — <https://arxiv.org/pdf/2512.09549>
- QwenLM/qwen-code PR #348 (rejected "avoid quantized models" default) — <https://github.com/QwenLM/qwen-code/pull/348>
- Reference implementation: Redwood Research Control Tower `openrouter_provider.py` (fp8+ floor, `data_collection: deny`, `sort: exacto`).

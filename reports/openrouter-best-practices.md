# Using OpenRouter (and similar routers) reliably for research

**One-sentence version:** By default, OpenRouter treats "a model" as a name that can be
served by *any* of several providers, at *any* quantization, on *any* inference engine, with
*silently dropped* sampling parameters — so unless you pin routing explicitly, the artifact
you evaluated is not a fixed object and your numbers may not reproduce or generalize.

This guide is grounded in OpenRouter's own docs, community practice, and a scored case study of
LinuxArena's `control-tower` `openrouter_provider.py` — which, checked against this repo's
own taxonomy in §3b, fails three of the mistakes it exists to prevent. It's included as a worked
failure, not a model to imitate. It is written for people who use OpenRouter to *produce research
results* — evals, LLM-as-judge scores, agent rollouts, or generated data. For how much of this
thesis was already established elsewhere, and by whom, see
[`reports/prior-work.md`](prior-work.md).

---

## 1. What OpenRouter actually does by default

OpenRouter is a unified API in front of dozens of independent inference providers. For any
given model slug (e.g. `deepseek/deepseek-r1`) there are often several providers, and they are
**not interchangeable**. What varies between them:

- **Quantization.** A provider may serve the model at `fp16`, `bf16`, `fp8`, or all the way
  down to `int4`/`fp4`. Lower precision is cheaper and faster and *usually* close — but "close"
  is not "identical," and degradation is prompt-dependent and worst on the hard/long-tail
  inputs that research often cares about. OpenRouter's own docs warn: *"Quantized models may
  exhibit degraded performance for certain prompts, depending on the method used"* — though that
  sentence sits in the field reference for the opt-in `quantizations` knob, near the bottom of the
  page, while the description of what you get by configuring nothing ("load balance requests
  across providers, prioritizing price") is at the top with no such caveat.
  Measured by us across 547 endpoints of 87 open-weight models
  (`findings/best_practices_verification.json`): `fp8` 43.1%, **`unknown` 31.6%**, `fp4` 11.2%,
  `bf16` 9.1%, `int4` 4.0%, `fp16` 0.9% — and `fp32` **never once**. Two consequences. An `fp32`
  floor is theoretical on this catalog, and roughly a third of endpoints decline to state their
  precision at all, which is why a `quantizations` floor that keeps `"unknown"` has a hole rather
  than an edge case: 70 of 87 models mix disclosed and undisclosed endpoints, and 2 disclose
  nothing on any endpoint.
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
- **Which provider you get at all.** With no routing preferences, OpenRouter states it
  load-balances: it prioritizes providers with no outage in the last ~30 seconds, then samples
  the lowest-cost ones weighted by the **inverse square of price**. (This is OpenRouter's own
  description of its internal algorithm — see the update below on how much of it can actually be
  checked from outside.) So *two identical requests can hit two different providers*.
  **We used to add "and cheaper-hence-more-quantized endpoints are favored"; our own data only
  partly supports that, so here is the measured version.** Ranking each model's endpoints by
  price and by precision, the correlation is positive in **58–65% of the models with a testable
  spread** (64.6% by prompt price, 57.8% by completion price) with a median ρ of only 0.21–0.36,
  and it **inverts outright in 13–16 models**. The cheapest endpoint is the most quantized one
  about 71% of the time. `openai/gpt-oss-120b` — this guide's own recurring example — is one of
  the inversions: its cheapest disclosed endpoint is `bf16`, while pricier ones are `fp4`/`fp8`.
  So price is a weak, unreliable proxy for precision: cheap routing *tends* toward worse weights
  but you cannot infer either from the other. Look the endpoint up (§3) instead of reasoning from
  its price. This isn't hypothetical: independently
  measured (not by this repo), the same `gpt-oss-120b` slug scored 93.3% via one set of providers
  and 36.7% via another on AIME25 — a 56.6-point spread under one model name — and a peer-reviewed
  audit of API endpoints found 11 of 31 tested serving distributions that didn't match the
  reference weights they claimed to serve. See `reports/prior-work.md` for both, with sources and
  verified quotations.
- **What happens to your prompts.** `data_collection` defaults to **`"allow"`**, meaning
  requests may route to providers that retain prompts to train on. For proprietary eval sets,
  red-team prompts, or unpublished data, this is a leak.

Crucial consequence: **setting `provider.sort` or `provider.order` disables load balancing**
(routing becomes deterministic-ish), while leaving them unset means routing is probabilistic.
That one is not just vendor prose: OpenRouter's public API schema documents the `sort` field as
*"When set, no load balancing is performed."*

### What you cannot check from outside — and why that is itself the argument

We probed the public endpoints API and enumerated every field it returns
(`findings/best_practices_verification.json` → `api_visibility_gaps`). What varies between
endpoints *is* visible: precision, context window, max output, supported parameters, price. What
governs **which endpoint you actually get, and which one you actually got**, is not:

- no selection weight, traffic share, or served-request count — so the inverse-square-of-price
  claim, and Auto Exacto's quality tiers, cannot be audited by anyone outside OpenRouter;
- no data-retention or training-policy field per endpoint, so `data_collection` cannot be
  verified against the endpoints it is supposed to filter;
- no verification alongside `quantization` — the precision is the provider's self-report;
- the `latency_last_30m` / `throughput_last_30m` fields, which would show whether a listed
  endpoint is even taking traffic, were `null` on every endpoint we sampled.

A routing system whose routing cannot be inspected from outside is not a reason to trust its
description of itself. It is the reason to **pin what you can pin and log what actually served
you** (§3, §4): provenance you record yourself is the only part of this that does not depend on
taking the vendor's word.

### The default is not the safe default — and tooling won't fix it for you

In `QwenLM/qwen-code` PR #348, a contributor tried to make the tool default to full-precision
providers (`provider.quantizations = fp8+`) because quantized routing "can result in
substantially worse output for coding." **The PR was rejected** — maintainers considered a
baked-in precision opinion too paternalistic ("silently changes behavior for everyone using
OpenRouter today").
The lesson for researchers: *no one upstream is going to pin this for you.* If your results
depend on which weights actually ran, you must set the routing yourself.

### 2026 update: "Auto Exacto" narrows part of this, for a slice of traffic — it doesn't fix it

In March 2026 OpenRouter shipped "Auto Exacto." Everything in this subsection is **OpenRouter's
own description of its own algorithm** — there is no field on the response that confirms it fired
on a given call, and unlike the gpt-oss-120b/Model-Equality-Testing findings just above, this repo
has no independent measurement of it. Read it as a vendor claim, not a verified fact.

- **Scope: requests with `tools`, not all requests.** OpenRouter's announcement: *"For requests
  that include tools, it's on by default."* A call without a `tools` array — most eval scoring,
  judging, and plain generation calls — is, by OpenRouter's own account, still governed by the
  price-weighted default described above.
- **Coverage is unclear, and OpenRouter's two own sources don't agree.** The announcement says
  OpenRouter *"enabled auto exacto globally for a chosen selection of our top tool calling models
  — notably GLM-4.7, GLM-5, DeepSeek V3.2, and gpt-oss-120b."* OpenRouter's current docs page
  instead says it runs *"by default on every tool-calling request, requiring no configuration,"*
  with no model list at all. We could not determine from outside which is current, or whether any
  specific model you use is covered — nothing in the API response says either way, so treat this
  as **unverifiable from outside**, not as "on for everyone now." Human edit: probably the docs are more up to date.
- **It reorders, it does not replace, the inverse-square-of-price sampling above.** OpenRouter's
  own account of the mechanism: providers are grouped into quality tiers using three signals
  (throughput, tool-call telemetry, benchmark scores) that OpenRouter says it recomputes "roughly
  every 5 minutes," and *"within each tier, the original routing order (price, latency, your
  preferences) stays intact. [...] We just push lowest performing providers to the back."* So even
  on the traffic it covers, the price-weighted sampling this guide describes is still what picks
  among whichever providers survive the quality cut — this is a pre-filter, not a different
  algorithm, and it is not a pin.
- **The older, opt-in mechanism is broader and separate.** `:exacto` (equivalently
  `provider.sort: "exacto"`, confirmed as a valid value in OpenRouter's public API schema) still
  exists on its own, and per OpenRouter "works across all models and all request types" — tool
  calls or not. That is the mechanism the `sort` row in §2 refers to; it is unaffected by any of
  the above.

**This doesn't change the guide's conclusion.** Taking OpenRouter's account at face value: Auto
Exacto is scoped to tool-calling requests on an unconfirmed set of models, it reorders among
still-multiple eligible providers rather than pinning one, and it leaves `allow_fallbacks`,
`quantizations`, and `data_collection` at their old, unsafe-for-research defaults. A
quality-weighted unpin is still an unpin. If anything, a default that reportedly changes
composition on a ~5-minute cycle with no caller-visible signal is a stronger argument for logging
the served provider on every call (§4), not a weaker one.

---

## 2. The parameters that matter (the `provider` object)

Pass these under the `provider` key (OpenAI-SDK users: `extra_body={"provider": {...}}`;
Inspect users: the `provider=` model arg; raw HTTP: top-level `"provider"`).

| Field | Default | Set it to… | Why |
| --- | --- | --- | --- |
| `quantizations` | *(unset → any)* | `["fp8","fp16","bf16","fp32"]` (add `"unknown"` only if you must reach proprietary models) | Stop silently landing on int4/fp4/int8 — but this is a floor, not a pin: it narrows the set of eligible providers, it doesn't fix one. Not sufficient by itself when the model's identity is the thing your research is about (§3). |
| `require_parameters` | `false` | `true` | Force routing only to providers that honor your `temperature`/`seed`/`response_format`/tools. Prevents silent parameter dropping. |
| `data_collection` | `"allow"` | `"deny"` | Don't send prompts to train-on-your-data providers. Use ZDR/`zdr:true` to also exclude operational retention. |
| `enforce_distillable_text` | *(unset → any)* | `true`, only if your research pipeline generates training/distillation data (§6) | A *licensing* filter, not a privacy one: restricts routing to models whose author has authorized using outputs to train/distill another model. Doesn't stop a provider retaining or training on *your prompts* — that's `data_collection`/`zdr`, above. |
| `order` | *(unset)* | `["provider-slug"]` | Pin a single named provider for maximum reproducibility (disables load balancing). |
| `only` / `ignore` | *(unset)* | allow-list / block-list of slugs | Whitelist trusted providers, or exclude a known-bad one. `ignore` is safer than `only` (excluding one bad provider can't 404 you the way pinning one can if it goes down). |
| `allow_fallbacks` | `true` | `false` **only** if you pinned `order`/`only` and want hard reproducibility | With fallbacks on, you can still drift among the *filtered* set. Off = fail rather than silently switch. |
| `sort` | *(unset)* | `"exacto"` (quality-first, tool-call-accuracy sort) or `"throughput"`/`"latency"`/`"price"` | Deterministic ordering; `exacto` favors higher-quality endpoints. Note: setting `sort` (like `order`) disables load balancing — confirmed directly in OpenRouter's public API schema. |
| `max_price` / `preferred_min_throughput` / `preferred_max_latency` | *(unset)* | a price ceiling (`{"prompt": …, "completion": …}`, USD/1M tokens) or a throughput/latency threshold | Cost/performance *preferences*, not filters or pins — endpoints outside the threshold are deprioritized, not excluded. Combine with a floor/pin (§3); don't use instead of one. |

Model-slug shortcuts: `:nitro` = `sort:throughput`, `:floor` = `sort:price`, `:exacto` =
`sort:exacto` (the *opt-in* Exacto mechanism — see the 2026 update in §1 for how this differs from
the newer, on-by-default "Auto Exacto"). Prefer the `provider` dict over the slug suffix so the
**model name stays clean** in your logs, cost accounting, and metadata (routing preference belongs
in `provider`, not in the identifier you record as "the model").

Full documented `quantizations` value set, per OpenRouter's public API schema: `int4`, `int8`,
`fp4`, `fp6`, `fp8`, `fp16`, `bf16`, `fp32`, `unknown`.

---

## 3. Pin the endpoint — and if you're the library, force the choice

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

### 3b. If you're the library, not the caller

Sometimes the code that talks to OpenRouter is shared infrastructure underneath many research
call sites, and it genuinely can't hardcode a pin — it doesn't know which model any given caller
will ask for. That's a real constraint on the library. **It is not a license for the library's
silent default to become the caller's entire safety story** — and that is exactly the mistake
LinuxArena's `control-tower` makes in `openrouter_provider.py`:

```python
OPENROUTER_PROVIDER_DEFAULTS = {
    "quantizations": ["fp8", "fp16", "bf16", "fp32", "unknown"],
    "data_collection": "deny",
    "sort": "exacto",
}
```

Quoted as of 2026-07-21, from the public `control-tower` repo at commit `79a3c6f`
(`src/control_tower/models/openrouter_provider.py`, lines 37–41):
<https://github.com/linuxarena/control-tower/blob/79a3c6f76c0575292ff80d6ece04ff288c64c482/src/control_tower/models/openrouter_provider.py#L37-L41>.

**Scored against this repo's own taxonomy, this implementation fails three of the mistakes it
exists to prevent:**

- **M2 / M9 (silent parameter dropping / judge on an unconstrained route) — FAIL.**
  `require_parameters` is never set. Any judge call built on this default that depends on
  provider-enforced structured output can be silently routed to a provider that ignores the
  schema — exactly the failure mode this guide is written to stop.
- **M4 (no provenance logging) — FAIL.** Nothing in `control-tower`'s `models/` code captures
  which provider actually served a call. Without that, a bad route can't even be diagnosed after
  the fact, let alone reproduced.
- **M1 (unpinned quantization) — nominally addressed, with a self-inflicted hole.** The floor
  exists, but `"unknown"` — kept so proprietary models still route — lets any provider that
  *declines to disclose its precision* pass straight through it. That's not a quantization floor
  with an edge case; it's a quantization floor with a hole sized to fit exactly the providers
  worth worrying about.
- **M3 (probabilistic routing) — nominally addressed, but not a pin.** `sort: exacto` disables
  blind load-balancing, which is real progress over the default. It is still an ordering
  preference among multiple providers, not a fixed one, and there's no `allow_fallbacks: false`
  because there's nothing pinned to protect.

By the same standard applied to the 35 repos in this survey, this pattern would score `at_risk`:
three High-severity mistakes fail outright, and the two it nominally addresses have known,
documented holes rather than being solved. The consequence is measured, not hypothetical:
BashArena (`redwoodresearch/basharena_public`), a Control-research codebase in the same
ecosystem this library was written for, never routes through this pattern at all and is flagged
`at_risk` with the near-complete `M1, M2, M3, M4, M5, M7, M8` set in this survey
(`findings/survey.csv`) — a safeguard living in one shared library did not reach the research
repo next door. That is what a floor-as-the-whole-policy actually buys you: a shared module that
looks like it solved the problem, and a research call site that never touches it.

An upstream fix for these gaps is in progress as of this writing; the scoring above is pinned
to the commit cited, independent of whether that fix lands.

**The fix isn't a better floor. It's making the pin the thing a caller has to actively skip,
not the thing they have to actively add:**

```python
FLOOR_DEFAULTS = {
    "quantizations": ["fp8", "fp16", "bf16", "fp32"],  # no "unknown" unless you truly cannot avoid it
    "data_collection": "deny",
    "sort": "exacto",
    "require_parameters": True,
}

def make_model(name: str, *, pin: dict | None = None, floor_only_ack: bool = False):
    """Construct a model handle. Callers must supply a hard provider pin, or explicitly
    acknowledge that this call's result doesn't depend on which provider serves it."""
    if pin is None and not floor_only_ack:
        raise ValueError(
            f"No provider pin for {name!r}. If this call's result truly doesn't depend on "
            "which provider/quantization serves it, pass floor_only_ack=True and say why in "
            "a comment at the call site. Otherwise pass pin={'order': [...], "
            "'allow_fallbacks': False}."
        )
    return get_model(name, provider={**FLOOR_DEFAULTS, **(pin or {})})
```

Keep the floor underneath this — it's a real backstop for the calls that legitimately opt out,
and a guard against the worst case if a pinned endpoint goes down. What it cannot do is stand in
that way, every time, by callers who never think about it — which is the whole reason this
for the decision, and a design that lets it stand in for the decision by default will get used
mistake is common enough to survey.

> **⚠️ The trap:** a script that interrogates one specific "untrusted model" isn't in the same
> position as shared infra serving arbitrary callers — it already knows which model it needs.
> Recommending the 3b floor as *the* fix there, or waving off `allow_fallbacks: false` with
> "there's no pin to protect," gets it backwards: pin the endpoint (3a) on top of, not instead of,
> any shared floor. Still counts as **M1** (`findings/taxonomy.md`).

---

## 4. Reproducibility & reporting checklist

Treat the provider/inference stack as a first-class hyperparameter — because it is.

- [ ] **Set a quantization floor** (`quantizations`) you trust. This restricts, it does not pin —
      if the model's identity is what your research is about, you also need the next item.
- [ ] **Set `require_parameters: true`** if you depend on `temperature`/`seed`/`logprobs`/
      `response_format`/tools. (Otherwise a provider silently ignoring them corrupts results.)
- [ ] **Pin the provider** (`order` + `allow_fallbacks:false`) for any headline number you want
      to reproduce, or at minimum `sort`/`only` to a trusted set.
- [ ] **Set `data_collection: "deny"`** (or `zdr`) for any non-public prompt data.
- [ ] **Log the served provider for every call.** Two mechanisms are confirmed in OpenRouter's
      public API schema: query `GET /api/v1/generation?id=...` (returns `provider_name`), or opt in
      per-request with the `X-OpenRouter-Metadata: enabled` header to get an `openrouter_metadata`
      block — naming the selected provider — on the chat-completion response itself. (Older
      guidance pointed at a bare response-level `provider` field; OpenRouter's current published
      schema for `/chat/completions` does not document one, so verify against your own response
      bodies rather than assuming it's there.) Save whichever you use alongside outputs. "We used
      deepseek-r1 via OpenRouter" is *not* a reproducible method statement.
- [ ] **Report the routing config** (the whole `provider` dict) and the observed provider
      distribution in your paper/appendix, the same way you'd report temperature.
- [ ] **Don't assume `seed` gives determinism.** Even honored, most providers don't guarantee
      bitwise reproducibility; batching/kernels make it best-effort. Verify empirically.
- [ ] **Version-pin the model slug.** A bare slug can silently point at an updated snapshot;
      prefer dated/versioned slugs where they exist and record the exact string.
- [ ] **Spot-check across the routes you'll actually hit.** Flexibility requires measurement: run
      the models your result depends on across the provider routes you might actually be served,
      and compare. Nobody upstream measures this for you, and no vendor claim substitutes for it.
      (Earlier versions of this guide attributed that first clause to OpenRouter. It is not their
      wording — we searched their provider-routing docs and both routing blog posts and could not
      find it — so it is stated here as our own advice.)

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
- You're doing **exploratory / qualitative** work where a output variance is
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

See also [`reports/prior-work.md`](prior-work.md) — independently-sourced, quotation-verified
evidence (13 checked sources) that this survey's thesis predates it, including the gpt-oss-120b
cross-provider spread and Model Equality Testing findings cited in §1.

OpenRouter's own docs/blog entries below are the vendor's description of its own system, not an
independently audited one — flagged inline in §1 and §2 wherever this guide relies on them for a
behavioral claim.

- OpenRouter — Provider Routing docs (redirects to the current URL as of 2026-07-21): <https://openrouter.ai/docs/guides/routing/provider-selection>
- OpenRouter — public API schema (used to verify `provider`-object field names/defaults, the `sort` enum incl. `"exacto"`, and the `/chat/completions` response shape): <https://openrouter.ai/openapi.json>
- OpenRouter — "Auto Exacto: Adaptive Quality Routing, On by Default" (blog, 2026-03-12): <https://openrouter.ai/blog/announcements/auto-exacto/>
- OpenRouter — Auto Exacto docs guide: <https://openrouter.ai/docs/guides/routing/auto-exacto>
- OpenRouter — "Provider Variance: Introducing Exacto" (blog, 2025-10-21): <https://openrouter.ai/blog/announcements/provider-variance-introducing-exacto/>
- OpenRouter — Model Routing (blog): <https://openrouter.ai/blog/insights/model-routing/>
- OpenRouter — Reliability/Failover (blog): <https://openrouter.ai/blog/insights/reliability-failover/>
- "The Silent Hyperparameter: Quantifying the Impact of Inference Backends on LLM Reproducibility" — <https://arxiv.org/abs/2605.19537>
- "Chasing Shadows: Pitfalls in LLM Security Research" — <https://arxiv.org/pdf/2512.09549>
- QwenLM/qwen-code PR #348 (rejected "avoid quantized models" default; closed, not merged, 2026-04-27) — <https://github.com/QwenLM/qwen-code/pull/348>
- LinuxArena `control-tower` `openrouter_provider.py`, quoted as of 2026-07-21 at commit `79a3c6f` — <https://github.com/linuxarena/control-tower/blob/79a3c6f76c0575292ff80d6ece04ff288c64c482/src/control_tower/models/openrouter_provider.py#L37-L41> — scored against this repo's own taxonomy in §3b: fails M2/M9 (`require_parameters` never set) and M4 (no provenance capture), and only nominally addresses M1/M3 (a floor with an `"unknown"` hole, an order-preference with no pin). A worked failure case, not a model to imitate.

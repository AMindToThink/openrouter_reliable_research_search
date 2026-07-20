# Taxonomy of OpenRouter research-reliability mistakes

Stable IDs (`M1`…`M12`). Auditors classify each repo's OpenRouter usage against these. A repo
is **safe** (`uses_safely = true`) if it exhibits *none* of the corrupting mistakes for the way
it actually uses OpenRouter — including the legitimate "doesn't matter here" cases noted below.

Severity reflects how badly the mistake can distort a research result, not how common it is.

| ID | Mistake | Severity | What it is | How it corrupts research | How to detect in code |
| --- | --- | --- | --- | --- | --- |
| **M1** | Unpinned quantization | High | No `provider.quantizations`; the model may be served int4/fp4/int8. | Cheaper/lower-precision endpoints are favored by default routing; degradation is prompt-dependent and worst on hard inputs — inflates or deflates capability measurements. | No `quantizations` key anywhere in the request/`provider` dict. |
| **M2** | Silent parameter dropping | High | No `require_parameters: true`; a provider lacking a requested param still gets the request and ignores it. | `temperature`/`top_p`/`seed`/`logprobs`/`stop`/`response_format` silently voided on some routes → your decoding config isn't what ran. | `require_parameters` never set, yet non-default sampling/format params are passed. |
| **M3** | Probabilistic provider routing | High | No `order`/`only`/`sort`; OpenRouter load-balances across providers by inverse-square price. | Identical requests hit different backends run-to-run → results don't reproduce; cheaper-hence-more-quantized providers favored. | No routing preference set; bare model slug with default routing. |
| **M4** | No provenance logging | High | The provider that actually served each response is never recorded. | You cannot reproduce, diagnose, or even *notice* a bad route after the fact; "model X via OpenRouter" is not a method. | Response `provider` field / `GET /generation` never read or stored. |
| **M5** | Data-policy leakage | Med | `data_collection` left at `"allow"`. | Proprietary eval sets / red-team prompts / unpublished data may be retained by train-on-data providers → leakage & contamination. | No `data_collection: "deny"` (or `zdr`). |
| **M6** | Model version drift | Med | Bare, undated model slug that can silently repoint to a new snapshot. | Results attributed to "model X" mix snapshots across the study's timespan. | Slug has no version/date pin and none recorded. |
| **M7** | Seed→determinism assumption | Med | Treats `seed` as guaranteeing reproducible outputs. | Providers rarely guarantee bitwise determinism (batching/kernels); "seeded" runs still diverge. | Relies on `seed` for reproducibility without empirical verification; often paired with M2. |
| **M8** | Cross-provider comparison confound | High | Compares models/conditions where each routed to a *different* backend/quantization. | Measured differences confound the model with its serving stack (up to ~16pp from backend alone). | Multiple models compared, none pinned; different providers plausibly served each. |
| **M9** | Judge/grader on unconstrained route | High | LLM-judge relies on structured outputs / constrained JSON but doesn't force a supporting provider. | Judge silently returns free-form text on some routes; lenient parsing yields wrong-but-plausible scores. | `response_format`/JSON-schema used without `require_parameters`/`only`. |
| **M10** | No reporting | Med | Paper/README discloses neither provider routing nor inference stack. | Readers can't assess or reproduce; the inference stack is a hidden hyperparameter. | No mention of provider/quantization/routing in docs or paper. |
| **M11** | Silent backend mixing | Med | Some calls go direct (Anthropic/OpenAI), others via OpenRouter, within one experiment. | Same "model" served by different stacks in one dataset → inconsistent artifact. | Mixed clients/base_urls for the same logical model. |
| **M12** | Actively selecting the cheap/degraded route | Med | Uses `:floor`/`sort:price` (or picks cheapest provider) for research-grade measurements. | Deliberately routes to the cheapest — usually most quantized — endpoint. | `:floor` suffix or `sort:"price"` on a research measurement path. |

**A floor is not a pin — this still counts as M1.** `quantizations` (a floor) and `order`/`only`
(a pin) fix different things. A floor alone is a legitimate M1 fix only for shared infrastructure
that must serve whichever model a caller passes in, where no single call path knows in advance
which one that will be. When the call site's model argument is itself the research subject — the
"untrusted model" being interrogated/red-teamed/probed, the judge scoring it, or any model
compared/benchmarked by name — a floor with no `order`/`only` pin is still **M1**: the model under
study can land on any provider/quantization inside the floor, run to run. Don't let "a
`quantizations` key is present" read as safe in that case, and don't recommend the floor as *the*
fix for such a call site — pin the endpoint instead.

## Legitimate "not a mistake" cases (still `uses_safely = true`)

- **Proprietary single-served models** (Claude/GPT/Gemini through OpenRouter): effectively one
  backend, so M1/M3/M8 largely don't apply. (M5/M6 still can.)
- **Exploratory/qualitative** use where backend noise can't change the conclusion, *and the
  authors say so*.
- **Provenance logged + provider pinned**: even without every knob, if they pin the provider and
  record it, the artifact is fixed and reproducible.

## Severity → weighting (for scoring a repo)

- **Critical route** = OpenRouter output feeds a reported number, a training set, or a safety
  measurement. High-severity mistakes on a critical route are the ones that actually invalidate
  results. The same mistake on a throwaway exploratory script is noted but not damning.

## Model-risk axis (record per repo)

- `open_weight` — quantization/provider risk is **high** (many providers, real precision spread).
- `proprietary` — quantization/provider risk is **low** (single served backend), data/version
  risk remains.
- `mixed` — both.

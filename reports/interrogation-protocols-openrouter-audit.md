# OpenRouter usage audit — `interrogation-protocols`

**Scope:** a read-only review of how the `interrogation-protocols` project (and its vendored
`control-tower`) uses OpenRouter, and where model outputs could be silently corrupted by
provider routing. **Nothing in that project was edited.** Findings are ordered by severity.

**Bottom line:** the project's *framework* path is a model of good practice — Control Tower
injects a strong `provider` policy (fp8+ precision floor, `data_collection: deny`, `exacto`
quality sort) into every OpenRouter call built through `ModelSpec.make_model()`. But the two
**standalone interrogation scripts bypass that layer**, so any `openrouter/...` model run
through them gets OpenRouter's unsafe defaults. There is also one framework-wide gap
(`require_parameters`) that interacts badly with the judge's reliance on constrained JSON.

---

## Finding 1 — (Medium) The interrogation scripts bypass CT's provider safeguards

**Where:** `scripts/trial_interrogation.py:442` and `scripts/interrogate_to_docent.py:180`:

```python
from inspect_ai.model import get_model
models = (get_model(args.untrusted_model), get_model(args.judge_model))
```

These call Inspect's `get_model(name)` **directly, with no `provider=` argument.** CT's
default routing preferences live *only* inside `ModelSpec.make_model()`
(`control-tower/src/control_tower/models/model_spec.py:33-46`), which these scripts never call.

**Why it matters.** The README and `.env.example` explicitly steer these scripts toward
OpenRouter — `.env.example` says `OPENROUTER_API_KEY` is "used for the interrogation / judge
model calls in `scripts/trial_interrogation.py` and `scripts/interrogate_to_docent.py`," and
model names are passed as `openrouter/<provider>/<model>`. When a model name carries the
`openrouter/` prefix and reaches a bare `get_model()`, Inspect routes it through OpenRouter with
**default routing**: load-balanced across providers, any quantization down to int4,
`data_collection: "allow"`. None of CT's `OPENROUTER_PROVIDER_DEFAULTS` (fp8+ floor, deny,
exacto) apply.

So the two quantities this project actually measures — the **judge's suspicion score** and the
**untrusted model's interrogation responses** — can be produced by a silently quantized or
data-collecting endpoint, and can drift run-to-run as load balancing samples different
providers. For a project studying subtle propensities (does U confess under interrogation?
where does the suspicion threshold sit?), provider-induced output variance is a direct
confound on the result.

**It also contradicts the project's own rule.** `docs/control-tower-best-practices.md` §3 says,
verbatim: *"Do not import the OpenAI/Anthropic/OpenRouter SDKs and do not call Inspect's
`get_model()` directly in downstream code. Go through Control Tower's model layer."* These
scripts are downstream code and call `get_model()` directly.

**Suggested fix (one line each).** Route the scripts through the layer that already exists:

```python
from control_tower.models.model_spec import get_model_spec
models = (get_model_spec(args.untrusted_model).make_model(),
          get_model_spec(args.judge_model).make_model())
```

…or, if keeping the scripts dependency-light on purpose (the README advertises a
`--no-project` lightweight path), pass the prefs inline:

```python
from control_tower.models.openrouter_provider import OPENROUTER_PROVIDER_DEFAULTS, merge_provider_prefs
def _mk(name):
    if name.startswith("openrouter/"):
        return get_model(name, provider=merge_provider_prefs(OPENROUTER_PROVIDER_DEFAULTS, None))
    return get_model(name)
```

---

## Finding 2 — (Medium) `require_parameters` is never set, but the judge relies on provider-enforced JSON

The judge path is documented as emitting JSON under **provider-enforced constrained decoding**
(`scripts/trial_interrogation.py` around lines 325/349; the test suite `tests/test_judge_variants.py`
and `tests/test_add_judge_variant.py` explicitly reason about "provider-enforced JSON" and
guard against a fabricated number when the format breaks).

But neither `OPENROUTER_PROVIDER_DEFAULTS` nor the scripts set `require_parameters: true`.
Without it, OpenRouter may route a judge call to a provider that **does not support
`response_format`/structured outputs**, which then *silently ignores the schema* and returns
free-form text. The downstream effect is exactly the failure the tests are trying to prevent —
except it originates in routing, not in the model. This is intermittent (only when routing
lands on a non-supporting provider), which makes it especially easy to miss.

**Suggested fix.** Add `"require_parameters": True` to `OPENROUTER_PROVIDER_DEFAULTS` (or at
least on any structured-output/judge call path), so requests only route to providers that honor
the JSON-schema constraint. Note this narrows the provider pool and may need the `"unknown"`
quantization allowance to stay, to avoid zero-provider hard-fails on some models.

---

## Finding 3 — (Low / accepted) The `"unknown"` quantization allowance is a real, disclosed loophole

`OPENROUTER_PROVIDER_DEFAULTS["quantizations"]` includes `"unknown"`, which the module's own
docstring flags: proprietary models (Claude/Gemini/GPT) report `unknown` and would otherwise
route to zero providers, so it's kept — at the cost that **open-weight providers that decline to
disclose their precision also slip past the fp8 floor.** They consciously accept this and rely
on the `exacto` quality sort to catch bad endpoints empirically. This is a reasonable
engineering call, not a bug — but it means the precision floor is *soft* for open-weight models.
If a specific experiment cares about an open-weight model's exact weights, pin that call path to
a known provider (`order`/`only`) or drop `"unknown"` for that path.

---

## Finding 4 — (Low / informational) Residual run-to-run provider drift under `sort: exacto`

`sort: exacto` disables load balancing and orders providers by quality, but `allow_fallbacks`
is left at its default (`true`). So among the *filtered* provider set, the actual serving
provider can still vary between runs (top choice down, fall back to next). For most work this is
fine and desirable (availability). For a *headline reproducible number*, pin `order` +
`allow_fallbacks: false` on that specific path and log the served provider. This is a
reproducibility/robustness trade-off to make deliberately, not a defect.

---

## What the project already does right (credit where due)

- **Precision floor** via `quantizations` — no silent int4/fp4/int8. (`openrouter_provider.py`)
- **`data_collection: "deny"`** — excludes train-on-your-data providers by default.
- **`sort: "exacto"`** — quality-first ordering, and it disables probabilistic load balancing.
- **Clean separation** — routing preference lives in the `provider` dict, so the recorded model
  *name* stays clean for cost/metadata (a genuinely good practice).
- **Regression tests** (`tests/test_trusted_routing.py`) that assert the provider dict handed to
  the client keeps the quantization/data-collection guarantees and never pins a single provider
  in a way that 404s — this is exactly the kind of test §4 of the best-practices report asks for.
- **Deep-copy hygiene** in `merge_provider_prefs` so shared defaults can't be mutated per-call.

The gap is only that this excellent policy is applied at the `make_model()` layer, and the two
standalone scripts don't go through it. Closing Finding 1 makes the whole project consistent
with its own §3 rule and with the best-practices guide in this repo.

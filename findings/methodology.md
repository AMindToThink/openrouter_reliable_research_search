# Survey methodology

**Question.** Among *important* public research projects that use OpenRouter (or a similar
multi-provider router), how many could have their results silently corrupted by provider
routing — quantization, provider-switching, silent parameter dropping — and what mistakes recur?

## Selection (importance-first, not mistake-first)

Per the project brief, we pick candidates by **influence, then check usage** — we do *not*
search for repos that look broken. Discovery ran as parallel agents across independent lanes:
AI-control/safety evals, LLM-as-judge papers, agent benchmarks, LessWrong/Alignment Forum posts
with code, a broad GitHub code-search sweep, multi-agent/persuasion work, data-generation/RLAIF,
and reasoning/math/code eval harnesses. Importance signals: citations, GitHub stars, authoring
lab/researcher, benchmark adoption, and community attention (LW/AF karma, media).

Inclusion required **verified** OpenRouter usage: an agent had to fetch a real file showing the
call site (or quote the paper), not guess. Single-provider hosts (Together, Fireworks, DeepInfra,
etc.) and first-party APIs (Anthropic/OpenAI/Google direct) are excluded unless reached *through*
a router — the silent-switching risk is specific to multi-provider routers.

## Per-repo audit

Each candidate was audited (and the verdict adversarially re-checked by a second agent) on:

1. **What OpenRouter is used for** and whether that output feeds a *reported number, a training
   set, or a safety measurement* ("critical route") vs. a throwaway/exploratory script.
2. **Model type** — open-weight (high quantization/provider risk) vs. proprietary single-served
   (low) vs. mixed.
3. **Safeguards present** — `quantizations`, `require_parameters`, `data_collection:deny`,
   `order`/`only`/`sort`, and provenance logging.
4. **Classification** against the taxonomy (`M1..M12`, see `taxonomy.md`).

## "Safe" vs "unsafe" — the bar

A repo is **safe** (`uses_safely = true`) if it exhibits *none of the corrupting mistakes for the
way it actually uses OpenRouter*. Explicitly **not** penalized:

- Proprietary single-served models (M1/M3/M8 don't apply — one backend).
- Work the authors frame as exploratory/qualitative where backend noise can't flip the conclusion.
- Repos that pin the provider **and** log provenance, even if not every knob is set.

Every "unsafe" verdict cites the exact call site and names the reported result it threatens.
Every "safe" verdict says why the risk doesn't apply. Verdicts are **PLAUSIBLE unless a verifier
confirmed them from the code** — we flag confidence.

## What this survey is and isn't

- It **is** a static audit of how the code *routes* model calls, and whether that routing leaves
  the door open to silent corruption.
- It is **not** a claim that any specific published number is wrong. We did not re-run anyone's
  experiments across providers to measure the actual delta. "Unsafe" means *the result is exposed
  to a known corruption channel that was not controlled for*, not "the result is false."
- Static analysis has blind spots: dynamic model names (argv/config), routing set in
  infrastructure we can't see, and provenance logged in a way we didn't recognize. We mark
  confidence accordingly and prefer under-claiming.

## Honesty notes

- The `require_parameters`/quantization risk is **highest for open-weight models**; we weight
  severity by model type and by whether the route is critical.
- A repo can be *aware* of the issue and pin providers deliberately (e.g. pinning R1 to specific
  providers to reproduce a behavior) — that's **good practice**, and we credit it, even though it
  touches the same machinery an "unsafe" repo mishandles.

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

## Layout

| Path | What's there |
| --- | --- |
| `reports/` | Best-practices guide; audit of the `interrogation-protocols` project |
| `findings/` | The survey dataset (CSV/JSON), taxonomy of mistakes, methodology |
| `artifact/` | Interactive data explorer (self-contained HTML) |
| `image/` | Shareable summary graphic |
| `skill/` | `use-openrouter-safely` Claude skill |
| `research/` | Raw per-repo audit notes from subagents |

## Status

Work in progress. See the task list / commit history.

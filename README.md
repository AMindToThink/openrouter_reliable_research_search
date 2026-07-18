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

## Headline findings

We audited **35** influential public repos (importance-first: NeurIPS · ICML · ICLR · ACL ·
NAACL · Nature + UK AISI · METR · Redwood · Palisade · Anthropic Fellows + LessWrong/AF) that
route model calls through OpenRouter. Each verdict came from one audit agent **plus one
adversarial verifier** reading the actual source. Numbers below are generated from
[`findings/stats.json`](findings/stats.json).

- **31 / 35 (89%)** leave at least one *uncontrolled* provider-routing corruption channel open.
- **32 / 35** route OpenRouter output straight into a reported number, a training set, or a safety measurement.
- **23** carry a **high-severity** gap (can distort a result, not just reproducibility).
- Only **4** control for it properly — and the cleanest, `nostalgebraist/cot_legibility`, is
  exemplary precisely because *provider choice is its research question*.
- Most pervasive gaps (all silent by default): **no provenance logging (28)**, **data-policy
  left open (27)**, **unpinned quantization (26)**, **probabilistic routing (26)**.

> **Read this correctly.** "At risk" = the code leaves a known corruption channel **open and
> uncontrolled**, *not* that any published number is wrong. We audited how each repo *routes*
> model calls; we did not re-run experiments across providers to measure the actual delta. See
> [`findings/methodology.md`](findings/methodology.md).

## Deliverables

| | |
| --- | --- |
| 📊 **Interactive explorer** | Provider Routing Inspector — filter by verdict/severity, click a mistake to filter, "Routing Roulette" demo, per-repo link to the exact offending line: **https://claude.ai/code/artifact/6ba2006d-e72e-47b8-9e81-fe6270f8305e** (source: [`artifact/index.html`](artifact/index.html)) |
| 🖼️ **Shareable image** | [`image/openrouter_findings.png`](image/openrouter_findings.png) — one-glance summary + the fix |
| 📄 **Best-practices guide** | [`reports/openrouter-best-practices.md`](reports/openrouter-best-practices.md) |
| 🔎 **`interrogation-protocols` audit** | [`reports/interrogation-protocols-openrouter-audit.md`](reports/interrogation-protocols-openrouter-audit.md) (report only — that project was not modified) |
| 🗂️ **Dataset** | [`findings/survey.csv`](findings/survey.csv) · [`findings/survey.json`](findings/survey.json) (incl. a validated GitHub permalink to each call site) |
| 🧾 **Taxonomy** | [`findings/taxonomy.md`](findings/taxonomy.md) — the M1–M12 mistake catalog |
| 🛠️ **Claude skill** | [`skill/use-openrouter-safely/`](skill/use-openrouter-safely/) — guidance + a heuristic static auditor |

## Reproduce

```bash
# audit any repo for OpenRouter reliability mistakes (heuristic first pass)
uv run skill/use-openrouter-safely/scripts/audit_openrouter.py <path-to-repo>

# regenerate the shareable image from the dataset (numbers come from the data)
uv run scripts/make_poster.py
```

The two multi-agent sweeps (importance-first discovery → per-repo audit + adversarial verify)
were run as background workflows; the discovery record is preserved in
[`findings/discovered_candidates.json`](findings/discovered_candidates.json).

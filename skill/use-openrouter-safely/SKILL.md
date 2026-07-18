---
name: use-openrouter-safely
description: >-
  Use when writing, reviewing, or auditing code that calls OpenRouter (or a similar
  multi-provider router like Requesty / Vercel AI Gateway / a LiteLLM proxy) to produce
  RESEARCH results — evals, LLM-as-judge scoring, agent rollouts, benchmark numbers, or
  generated/labeled training data. OpenRouter's default routing silently load-balances a
  "model" across providers that may serve it quantized (down to int4), on different inference
  engines, and drops unsupported sampling/format params — quietly corrupting results and
  breaking reproducibility. Triggers: "openrouter", "OPENROUTER_API_KEY",
  "openrouter.ai/api/v1", provider routing, `extra_body={"provider": ...}`, quantization of an
  API model, "which provider served this", reproducibility of API model outputs, auditing a
  repo's model-inference hygiene.
---

# Using OpenRouter safely for research

**The core problem:** with default settings, "a model" on OpenRouter is *not a fixed artifact*.
The same slug can be served by different providers, at different quantizations (int4→fp32), on
different inference engines, with silently-dropped parameters. Backend choice alone can move a
benchmark by ~16pp (arXiv 2605.19537). If a result depends on which weights actually ran and you
pinned nothing, the result may not reproduce or generalize — and you won't get an error.

This skill has two modes. Pick based on the task.

---

## Mode A — Authoring: call OpenRouter properly

Set routing preferences under the `provider` key. Two good presets:

**Reproducibility-first** (you want the *same* weights every run — headline numbers, comparisons):
```python
extra_body={"provider": {
    "order": ["fireworks"],          # the one provider you validated
    "allow_fallbacks": False,        # fail loudly rather than silently switch weights
    "require_parameters": True,      # only route to providers that honor temperature/seed/response_format
    "quantizations": ["fp8", "fp16", "bf16", "fp32"],
    "data_collection": "deny",
}}
```

**Quality-floor default** (many heterogeneous models, provider-agnostic, but never garbage):
```python
provider = {
    "quantizations": ["fp8", "fp16", "bf16", "fp32", "unknown"],  # keep "unknown" only if you need Claude/GPT/Gemini
    "data_collection": "deny",
    "sort": "exacto",                # quality-first; also disables probabilistic load balancing
    "require_parameters": True,      # add this if you pass sampling params or use structured outputs
}
```

Then, non-negotiably:
- **Record the provider that actually served each call** — the response `provider` field, or
  `GET /api/v1/generation?id=...`. Store it with the output. Without this you cannot reproduce.
- **Version-pin the model slug** and record the exact string.
- If you rely on **structured outputs / JSON schema** for a judge or parser, you *must* set
  `require_parameters: true` (or `only`/`order` to providers that support it) — otherwise the
  schema is silently ignored on some routes and your parser scores free-form text.
- Don't trust `seed` for bitwise determinism; verify empirically.

Key facts (so you can reason about edge cases):
- Default routing = load-balance by inverse-square of price; identical requests hit different
  providers. Setting `sort` **or** `order` disables load balancing.
- `require_parameters` defaults to **false** → unsupported params are silently ignored.
- `data_collection` defaults to **"allow"** → prompts may go to train-on-your-data providers.
- Slug suffixes: `:nitro`=throughput, `:floor`=price (cheapest, usually most quantized — avoid
  for research), `:exacto`=quality sort. Prefer the `provider` dict so the recorded model name
  stays clean.
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
   order/only/sort · provenance logging.

### Step 3 — Classify against the taxonomy

| ID | Mistake | Sev | Tell-tale |
| --- | --- | --- | --- |
| M1 | Unpinned quantization | High | no `quantizations` |
| M2 | Silent parameter dropping | High | sampling params + no `require_parameters` |
| M3 | Probabilistic provider routing | High | no `order`/`only`/`sort` |
| M4 | No provenance logging | High | served `provider`/generation id never stored |
| M5 | Data-policy leakage | Med | `data_collection` left `allow` |
| M6 | Model version drift | Med | bare undated slug |
| M7 | seed→determinism assumption | Med | relies on `seed` for reproducibility |
| M8 | Cross-provider comparison confound | High | models compared, none pinned |
| M9 | Judge on unconstrained route | High | `response_format`/schema without `require_parameters` |
| M10 | No reporting | Med | paper/README says nothing about routing/stack |
| M11 | Silent backend mixing | Med | some calls direct, some via router, same "model" |
| M12 | Cheap/degraded route chosen | Med | `:floor` / `sort:price` on a research path |

**Be fair (this matters):** don't hunt for mistakes. A repo is **safe** if it exhibits none of the
corrupting mistakes *for the way it actually uses OpenRouter*. Legitimate non-mistakes:
proprietary single-served models (M1/M3/M8 don't apply); explicitly exploratory/qualitative work;
provider pinned **and** provenance logged even if not every knob is set. When you assert "unsafe,"
cite the exact file:line and say which reported result it threatens. When you assert "safe," say
why the risk doesn't apply here.

### Step 4 — Report
Per repo: what they use OpenRouter for · open/proprietary · safe? (bool) · mistakes (M-ids + the
threatened result) · severity · a one-line fix. Full method + dataset schema:
`findings/taxonomy.md` and `findings/methodology.md` in the openrouter_reliable_research_search repo.

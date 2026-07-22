# Blog post review checklist

Review of `⚠️ A Pervasive Bug with OpenRouter is Destroying AI Safety Research.md` against
the repo's own data and the live sources it cites. Check items off as you address them.

## Factual errors / citations to fix

- [ ] **"NeurIPS 2026 paper" is wrong.** Arun Jose's paper (arXiv 2510.27338) was a **NeurIPS
      2025** poster (neurips.cc/virtual/2025/poster/115367). The arXiv page itself carries no
      venue field, so nothing on the linked page supports "2026."
- [ ] **"Accuracy is Not All You Need" links to the wrong paper.** `neurips.cc/virtual/2022/58881`
      is an unrelated NeurIPS 2022 paper (Piorkowski et al., human-AI collaboration) that just
      happens to share the title. The compressed-model "flips" paper you mean (Dutta et al.,
      arXiv 2407.09141) is **NeurIPS 2024**: correct link is
      `https://neurips.cc/virtual/2024/poster/95234`. The quote itself is accurate — only the
      URL is wrong.
- [ ] **RAND citation (footnote/backdoor claim) doesn't support the claim as currently placed.**
      Re-verified against the full RRA2849-1 PDF directly: "backdoor" appears 23 times, but
      every instance is a cryptographic/access-control/software-supply-chain backdoor used to
      **steal model weights** (NSA/Dual_EC_DRBG, TETRA cipher, xz/liblzma, event-stream npm
      package, etc.). The report explicitly scopes out model-behavior manipulation: *"the
      terminal goal of model integrity is outside the scope of this report"* and lists *"training
      data poisoning"* among vectors it deliberately excludes. It does not support "models
      maliciously finetuned to push agendas or have hidden backdoors" as written.
      **Fix options:**
      - Swap in **PoisonGPT** (Mithril Security, 2023) — a GPT-J edited to spread a false claim,
        uploaded under a typosquatted HF name, passed standard benchmarks. Directly on point.
      - Or **Sleeper Agents** (Hubinger et al., arXiv 2401.05566) — canonical hidden-trigger
        backdoor-in-model-behavior paper.
      - Or keep the RAND link but move it elsewhere in the post (e.g. "A New Org?" section,
        as support for "securing model infrastructure is hard"), and cite PoisonGPT/Sleeper
        Agents for the backdoor/agenda sentence specifically.
- [ ] **"I haven't spotted any of the 'Fingerprints' of bad inference providers in these repos"
      contradicts the repo's own fingerprint sweep.** `findings/stats.json` records
      `fingerprints_found` for **8 of 35** repos, with named, quotable artifacts: Aider (its own
      published 61.3% vs 59.6% vs 54.7% same-model cross-path spread), EQ-Bench/Judgemark
      (`</think>` appears exactly twice, both in one run), MathArena (phi-4 completions hit a
      31,000-token wall on 25/120 AIME rows), ctfish/Palisade (stray inline `<think>` tags in
      four runs), plus Nous Autoreason, lighteval Swiss-Legal, OpenHands, and the nostalgebraist
      rerun itself. Of your six *highlighted* repos specifically: Inspect AI and Inspect Evals
      are `nothing_checkable_released` (vacuously clean — nothing was published to check), METR
      and Scaling Laws for Scalable Oversight are `inconclusive` (not clean), only BashArena is
      genuinely `checked_clean`, and control-tower isn't in the 35-repo dataset at all. Recommend
      replacing the sentence with the true (and stronger) finding: fingerprints were found in a
      quarter of the repos that released anything checkable.
- [ ] **Footnote 4 (90/10–10/90 provider-mix ratios) is attributed to the wrong model.** Those
      within-run GPQA splits are from nostalgebraist's **QwQ-32B** runs (16/16 split across
      DeepInfra/Nebius), not from the DeepSeek-R1 runs the illegibility story is about. The R1
      runs were single-provider; the messy 169/300 Targon run was 125 rate-limit failures
      silently counted as missing data, not fallback routing (the repo has an explicit
      correction on file for this). As currently placed, the footnote reads as describing R1.
- [ ] **Denominator drift across the post.** Canonical chain: 35 surveyed → 34 with an OpenRouter
      call site → 32 where output reaches a reported result → 31 at-risk + 1 handled
      (nostalgebraist). The 31/32 = 97% math is correct, but:
      - Line 7 says "codebases **that use OpenRouter**" — that population is 34 (rate would be
        91%), not 32.
      - Background section: "31/32 AI Safety codebases **checked**" — checked = 35, not 32.
      - "the 32 repos Claude **found**" — found/surveyed = 35, not 32.
      One consistent sentence fixes all three: *"35 surveyed; in 32 the OpenRouter output feeds
      a reported result; 31 of those 32 (97%) leave a corruption channel open."*
- [ ] **Two hedges to restore.**
      - "same quantization (fp8)" — nostalgebraist wrote "**as far as I can tell**, so did the
        provider used in the paper" — the post states it as flat fact.
      - "All had gaps" — true for the **10 providers actually verified** in
        `findings/provider_transparency.json`; 12 more entries are unchecked leads. Say "all 10
        audited providers had gaps."

## Repo content worth adding (ranked by importance)

- [ ] **Measured effect sizes for the flagship nostalgebraist/Arun Jose story** — currently the
      opening section has no numbers. Illegibility swung **4.31±2.13 (Targon) → 2.31±0.75
      (Novita)**; GPQA accuracy **36.6% → 43.9%** — from provider choice alone, same model.
- [ ] **The MathArena cautionary tale** — pins textbook-style
      (`order: [moonshotai], allow_fallbacks: False`) but that endpoint serves Kimi K2.6 at
      **int4** while an fp8 endpoint of the same slug exists elsewhere. Belongs next to "Pin the
      endpoint": pinning a provider without pinning quantization can still hand you the worst
      backend.
- [ ] **Numbers behind the prior-work bullets**, currently just links:
      - Model Equality Testing: **11/31** endpoints serve different distributions than reference
        weights.
      - Chasing Shadows: pitfall P9 present in **73.6% (53/72)** of papers, discussed by none;
        CodeLlama attack success **18.21% → 69.52%** at 2-bit.
      - Willison/AIME25: identical gpt-oss-120b weights score **93.3% vs 86.7% vs 80.0% vs
        36.7%** across providers in one week.
- [ ] **Provider-transparency specifics behind "all had gaps"** — **31%** of sampled endpoints
      declare no quantization at all; no vendor publishes a dated changelog of serving-config
      changes; top report-card grade is **6/8** (Cerebras), the "A" band is empty; Together AI's
      docs allow silently redirecting a live model ID after **3 days'** notice; DeepSeek's API
      has **no pinnable ID at all**.
- [ ] **Mistake-frequency ranking as a finding, not just advice** — no provenance logging is the
      single most common failure (**28/35**), ahead of data-policy leakage (**27**), unpinned
      quantization (**26**), probabilistic routing (**26**).
- [ ] **A few of the 113 traced claims, named** — currently "Highlighting Some Impacted Work"
      uses generic one-liners; citing 2-3 specific figures/tables would land harder (34
      high-impact, 53 medium, 26 low; 23 repos high-severity).
- [ ] **Release-precision principle**, stated explicitly — quantization labels only describe
      fidelity relative to a model's *release* precision (gpt-oss is MXFP4-native, so its bf16
      endpoints are an upcast, not extra fidelity; DeepSeek ships fp8 natively). Belongs in "Set
      a floor": a bf16 floor protects nothing for an MXFP4-native model.
- [ ] **Concrete API mechanics for the checklist** — name `allow_fallbacks: false` explicitly
      (it's literally the "conscious choice" bullet); mention per-endpoint context/output
      cliffs — llama-3.3-70b endpoints range **6,000 to 131,072** context and **2,048 to
      128,000** max output, a truncation problem unrelated to quantization.
- [ ] **The existing $46, ~2-hour A/B replication plan** (`reports/provider-ab-experiment-plan.md`)
      — the post asks replicators to act but never mentions a costed, ready-to-run plan already
      exists in the repo.
- [ ] **Credibility/texture details** — the adversarial-verify pass caught a first-pass agent
      inventing numbers, and a paper whose appendix says "via Google AI" while the code
      hardcodes OpenRouter; awareness split is 19/35 partially aware, 13 fully unaware (not
      uniformly clueless); Palisade's headline pipeline and Bespoke Curator's demo are genuine
      positive examples, not just exclusions.

## Minor / cosmetic

- [ ] "Cerebas" → "Cerebras" (footnote 8).
- [ ] Garbled sentence: "This is just a selection. For more, prior work (see Claude's Report)."
- [ ] "artefact" / "Artifact" spelling inconsistency.
- [ ] GitHub-issue link points to the repo root, not `/issues`.
- [ ] "proprietary models from OpenAI, Anthropic, or Gemini" — Gemini is the model, Google is
      the company.
- [ ] Embedded image is a low-res screenshot of the F1–F17 fingerprint table; the repo's
      purpose-built shareable poster (`image/openrouter_findings.png`) is unused.
- [ ] Consider preempting the "that's documented behavior, not a bug" rebuttal with one line
      (e.g. "by design or not, it corrupts results silently").

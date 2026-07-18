# Findings — do important research repos use OpenRouter reliably?

> **31 of 35** surveyed important research repos (89%) leave at least one uncontrolled provider-routing corruption channel open. **32 of 35** route OpenRouter output straight into a reported result, a training set, or a safety measurement.

**Read this correctly.** *Unsafe* means *exposed to a known corruption channel that was not controlled for* — **not** that any published number is wrong. We audited how the code routes model calls; we did not re-run experiments across providers to measure the actual delta. See `methodology.md`.

## Headline numbers

- Repos audited: **35** (importance-first: NeurIPS/ICML/ICLR/ACL/NAACL/Nature + UK AISI/METR/Redwood/Palisade/Anthropic-Fellows + LessWrong/AF)
- Use it **safely**: **4**  ·  **unsafe**: **31**
- Severity: **23 high**, 8 medium, 4 none
- Author awareness: 2 aware & handled, 19 partially aware, 13 unaware
- Model exposure: 26 mixed, 6 open-weight (highest risk), 3 proprietary-only (lowest risk)

## Most common mistakes

| Rank | ID | Mistake | Severity | Repos (of 35) |
| --- | --- | --- | --- | --- |
| 1 | M4 | No provenance logging | High | 28 |
| 2 | M5 | Data-policy leakage | Med | 27 |
| 3 | M1 | Unpinned quantization | High | 26 |
| 4 | M3 | Probabilistic provider routing | High | 26 |
| 5 | M2 | Silent parameter dropping | High | 22 |
| 6 | M6 | Model version drift | Med | 22 |
| 7 | M8 | Cross-provider comparison confound | High | 21 |
| 8 | M10 | No reporting | Med | 13 |
| 9 | M7 | seed→determinism assumption | Med | 3 |
| 10 | M9 | Judge on unconstrained route | High | 3 |
| 11 | M11 | Silent backend mixing | Med | 3 |
| 12 | M12 | Cheap/degraded route chosen | Med | 1 |

The four most pervasive gaps — **no provenance logging, data-policy left open, unpinned quantization, and probabilistic routing** — are all *silent by default*: nothing errors, so nobody notices.

## The 4 repos that use it safely (and why)

- **Bespoke Curator (bespokelabsai/curator)** — Nice case of "the smoking-gun file the discovery step found is real but is a demo, not the production path." The discovery evidence itself flagged medium confidence that the released datasets used OpenRouter — I was able
- **OASIS (Open Agent Social Interaction Simulations with One Million Agents)** — This is a clean 'inherited-but-unused' case: the taxonomy risk (M1-M12) presupposes an actual OpenRouter call site to audit, and none exists in this repo. All headline paper results (1M-agent simulation, group polarizati
- **Palisade Research — robot_shutdown_resistance** — This is a clean example of a repo that touches OpenRouter but is correctly judged safe under the taxonomy: the router is confined to an admittedly-exploratory dev harness and a pricing lookup, while the actual headline-g
- **R1 CoT Illegibility Revisited (nostalgebraist, fork of Jozdien/cot_legibility)** — This is a genuinely exemplary case for the taxonomy: the repo doesn't just avoid the mistakes, its entire research question IS "does OpenRouter provider choice silently change R1's measured behavior?" — and it answers ye

## Full table

| Repo | Venue | Safe? | Severity | Mistakes |
| --- | --- | :---: | :---: | --- |
| AI Diplomacy | media/LessWrong-adjacent a | ❌ | high | M1, M2, M3, M4, M6, M8, M10 |
| AI Induced Psychosis: A shallow investigation | Alignment Forum / LessWron | ❌ | high | M1, M3, M4, M5, M6, M8 |
| ARC-AGI Benchmarking | arXiv / ARC Prize official | ❌ | high | M1, M3, M4, M6, M8 |
| AgentLab | other (framework backing 2 | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10 |
| Aider | Community/industry — 47,47 | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10 |
| AppWorld | ACL 2024 (Best Resource Pa | ❌ | high | M1, M2, M3, M4, M5, M6, M7, M8, M10 |
| CAMEL | NeurIPS 2023 | ❌ | high | M1, M2, M3, M4, M5, M6, M9, M12 |
| EQ-Bench Creative Writing Bench + Judgemark-v2 | community benchmark/leader | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10 |
| Hereditary Traits Distillation | Alignment Forum | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10, M11 |
| Inspect Evals | UK AISI | ❌ | high | M1, M2, M3, M4, M5, M8 |
| JudgeArena | ICML 2025 (Tuning LLM Judg | ❌ | high | M1, M2, M3, M4, M5, M8 |
| METR RE-Bench task suite | arXiv | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10 |
| Multi-hop / no-CoT latent reasoning experiment | Alignment Forum (LessWrong | ❌ | high | M1, M2, M3, M4, M6, M8 |
| Nous Research — Autoreason | self-published research re | ❌ | high | M1, M2, M3, M4, M5, M6, M8 |
| OpenPipe ART | widely used open-source RL | ❌ | high | M1, M3, M4, M5, M6, M10 |
| Prompt Framing Changes LLM Performance | LessWrong | ❌ | high | M1, M2, M3, M4, M5, M6, M8 |
| Redwood Research — BashArena | other | ❌ | high | M1, M2, M3, M4, M5, M7, M8 |
| Scaling Laws For Scalable Oversight | NeurIPS 2025 (Spotlight) | ❌ | high | M1, M2, M3, M4, M5, M6, M8 |
| Seer | Alignment Forum | ❌ | high | M2, M4, M5 |
| ctfish | arXiv (ICML-format writeup | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10 |
| diffing-toolkit | Alignment Forum | ❌ | high | M4, M5, M6 |
| lighteval — Swiss-Legal / LEXam LLM-as-judge t | ICLR 2026 (LEXam: Benchmar | ❌ | high | M1, M3, M4, M5, M6, M8, M10, M11 |
| safety-tooling | Multiple (shared infra: An | ❌ | high | M1, M2, M3, M4, M5, M8, M9, M10, M11 |
| Evaluating LLMs for accuracy incentivizes hall | Nature (2026) | ❌ | medium | M4, M6 |
| Inspect AI | UK AISI (govt AI safety in | ❌ | medium | M1, M2, M3, M5, M9 |
| MathArena | ETH Zurich SRI Lab (Martin | ❌ | medium | M1, M2, M3, M5, M8 |
| OSWorld | NeurIPS 2024 (Datasets and | ❌ | medium | M4, M5, M6 |
| OpenHands | arXiv (other) | ❌ | medium | M1, M2, M3, M4, M5, M6, M8, M10 |
| Prometheus 2 / BiGGen-Bench | NAACL 2025 (BiGGen-Bench); | ❌ | medium | M4, M5, M6, M10 |
| openbench | Industry (Groq, official o | ❌ | medium | M1, M2, M3, M5, M7 |
| tau2-bench | arXiv (Sierra AI); tau-ben | ❌ | medium | M1, M3, M4, M5 |
| Bespoke Curator | Open-source tool (Bespoke  | ✅ | none | — |
| OASIS | arXiv 2024 | ✅ | none | — |
| Palisade Research — robot_shutdown_resistance | other (Palisade Research t | ✅ | none | — |
| R1 CoT Illegibility Revisited | LessWrong | ✅ | none | — |

See `survey.csv` / `survey.json` for full per-repo detail (summary, importance, evidence, one-line fix, verifier reasoning). Interactive explorer + shareable image in the repo root deliverables.

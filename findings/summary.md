# Findings — do important research repos use OpenRouter reliably?

> **31 of 35** surveyed important research repos (89%) leave at least one uncontrolled provider-routing corruption channel open. **32 of 35** route OpenRouter output straight into a reported result, a training set, or a safety measurement. We traced **113 specific claims/figures** across **31 repos** that could be affected.

**Read this correctly.** *At risk* means *exposed to a known corruption channel that was not controlled for* — **not** that any published number is wrong. *Possibly-impacted findings* are **hypotheses worth checking, not demonstrated errors**. We audited how the code routes model calls; we did not re-run experiments across providers to measure the actual delta. See `methodology.md`.

## Headline numbers

- Repos audited: **35** (importance-first: NeurIPS/ICML/ICLR/ACL/NAACL/Nature + UK AISI/METR/Redwood/Palisade/Anthropic-Fellows + LessWrong/AF)
- Use it **safely**: **4**  ·  **unsafe**: **31**
- Severity: **23 high**, 8 medium, 4 none
- **Specific possibly-impacted findings: 113** (34 high-impact, 53 medium, 26 low) across 31/35 repos
- Adversarial verification completed for **35/35** rows
- Author awareness: 2 aware & handled, 19 partially aware, 13 unaware

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

## Examples of specific possibly-impacted claims

Each row of `survey.csv` carries a **Possibly-impacted findings** column naming the exact figure/table/number and the mechanism. A few illustrative ones:

- **AI Diplomacy** — *arXiv:2508.07485 (Duffy, Paech et al., 'Democratizing Diplomacy'), Contributions list (end of Introduction) + Figure 3 (*: Central scaling claim — contribution #2: "comprehensive benchmarking across 13 contemporary models show[ing]... clear performance scaling with model size"; operationalized in Figure 3 (left,
- **AI Induced Psychosis: A shallow investigation** — *graphs/intro.png (results_analysis.R lines 107-117) and graphs/delulu.png (same regression object reused, lines 217-222)*: Headline chart 'Many AIs Encourage Users' Delusions' (graphs/intro.png / graphs/delulu.png), feols regression of delusion_confirmation_rating (0-4) on target_model — the post's central model
- **ARC-AGI Benchmarking** — *arcprize.org/leaderboard, the live results source arXiv:2505.11831 §6 names for 'complete updated scores'; not a row in *: Official ARC-AGI Leaderboard entry for DeepSeek R1-0528, model config 'deepseek_r1_0528-openrouter' (model_name: deepseek/deepseek-r1-0528, models.yml lines 1458-1465, provider: openrouter, 
- **AgentLab** — *Table 2 (Section 6.2 'Results')*: Llama-3.1-405B-Instruct and Llama-3.1-70B-Instruct success rates in Table 2, listed as 405B/70B: WorkArena L1 43.3%±2.7 / 27.9%±2.5, WebArena 24.0%±1.5 / 18.4%±1.4, MiniWoB 64.6%±1.9 / 57.6%
- **EQ-Bench Creative Writing Bench + Judgemark-v2** — *eqbench.com/judgemark-v2.html leaderboard, live data confirmed directly in judgemark-v2.js `leaderboardDataV2` (fetched *: Judgemark-v2 live judge-leaderboard scores/ranks for open-weight judges (eqbench.com/judgemark-v2.html): zai-org/GLM-5 judgemark_score=85.58 (rank 1) vs *Qwen/Qwen3.5-397B-A17B=85.45 (rank 2
- **Hereditary Traits Distillation** — *reports/report_25_depression_teacher_control/README.md and reports/report_24_nemotron_blackmail_transfer/README.md (veri*: Negative-emotion transfer headline delta (Gemma-3-27B-it teacher mean negativity 1.39 -> Gemma-distilled Qwen3.5-9B-Base student 0.82 [0.72,0.93] vs Llama-3.1-70B-instruct control 0.36 [0.21

## The repos that use it safely (and why)

- **Bespoke Curator (bespokelabsai/curator)** — Nice case of "the smoking-gun file the discovery step found is real but is a demo, not the production path." The discovery evidence itself flagged medium confidence that the released datasets used Ope
- **OASIS (Open Agent Social Interaction Simulations with One Million Agents)** — This is a clean 'inherited-but-unused' case: the taxonomy risk (M1-M12) presupposes an actual OpenRouter call site to audit, and none exists in this repo. All headline paper results (1M-agent simulati
- **Palisade Research — robot_shutdown_resistance** — This is a clean example of a repo that touches OpenRouter but is correctly judged safe under the taxonomy: the router is confined to an admittedly-exploratory dev harness and a pricing lookup, while t
- **R1 CoT Illegibility Revisited (nostalgebraist, fork of Jozdien/cot_legibility)** — This is a genuinely exemplary case for the taxonomy: the repo doesn't just avoid the mistakes, its entire research question IS "does OpenRouter provider choice silently change R1's measured behavior?"

## Full table

| Repo | Venue | Safe? | Severity | Mistakes | Impacted claims |
| --- | --- | :---: | :---: | --- | :---: |
| AI Diplomacy | media/LessWrong-adjacent | ❌ | high | M1, M2, M3, M4, M6, M8, M10 | 4 |
| AI Induced Psychosis: A shallow investigatio | Alignment Forum / LessWr | ❌ | high | M1, M3, M4, M5, M6, M8 | 5 |
| ARC-AGI Benchmarking | arXiv / ARC Prize offici | ❌ | high | M1, M3, M4, M6, M8 | 4 |
| AgentLab | other (framework backing | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10 | 5 |
| Aider | Community/industry — 47, | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10 | 7 |
| AppWorld | ACL 2024 (Best Resource  | ❌ | high | M1, M2, M3, M4, M5, M6, M7, M8, M10 | 1 |
| CAMEL | NeurIPS 2023 | ❌ | high | M1, M2, M3, M4, M5, M6, M9, M12 | 0 |
| EQ-Bench Creative Writing Bench + Judgemark- | community benchmark/lead | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10 | 3 |
| Hereditary Traits Distillation | Alignment Forum | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10, M11 | 4 |
| Inspect Evals | UK AISI | ❌ | high | M1, M2, M3, M4, M5, M8 | 4 |
| JudgeArena | ICML 2025 (Tuning LLM Ju | ❌ | high | M1, M2, M3, M4, M5, M8 | 3 |
| METR RE-Bench task suite | arXiv | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10 | 3 |
| Multi-hop / no-CoT latent reasoning experime | Alignment Forum (LessWro | ❌ | high | M1, M2, M3, M4, M6, M8 | 5 |
| Nous Research — Autoreason | self-published research  | ❌ | high | M1, M2, M3, M4, M5, M6, M8 | 5 |
| OpenPipe ART | widely used open-source  | ❌ | high | M1, M3, M4, M5, M6, M10 | 3 |
| Prompt Framing Changes LLM Performance | LessWrong | ❌ | high | M1, M2, M3, M4, M5, M6, M8 | 4 |
| Redwood Research — BashArena | other | ❌ | high | M1, M2, M3, M4, M5, M7, M8 | 3 |
| Scaling Laws For Scalable Oversight | NeurIPS 2025 (Spotlight) | ❌ | high | M1, M2, M3, M4, M5, M6, M8 | 4 |
| Seer | Alignment Forum | ❌ | high | M2, M4, M5 | 3 |
| ctfish | arXiv (ICML-format write | ❌ | high | M1, M2, M3, M4, M5, M6, M8, M10 | 2 |
| diffing-toolkit | Alignment Forum | ❌ | high | M4, M5, M6 | 4 |
| lighteval — Swiss-Legal / LEXam LLM-as-judge | ICLR 2026 (LEXam: Benchm | ❌ | high | M1, M3, M4, M5, M6, M8, M10, M11 | 4 |
| safety-tooling | Multiple (shared infra:  | ❌ | high | M1, M2, M3, M4, M5, M8, M9, M10, M11 | 6 |
| Evaluating LLMs for accuracy incentivizes ha | Nature (2026) | ❌ | medium | M4, M6 | 5 |
| Inspect AI | UK AISI (govt AI safety  | ❌ | medium | M1, M2, M3, M5, M9 | 5 |
| MathArena | ETH Zurich SRI Lab (Mart | ❌ | medium | M1, M2, M3, M5, M8 | 5 |
| OSWorld | NeurIPS 2024 (Datasets a | ❌ | medium | M4, M5, M6 | 2 |
| OpenHands | arXiv (other) | ❌ | medium | M1, M2, M3, M4, M5, M6, M8, M10 | 1 |
| Prometheus 2 / BiGGen-Bench | NAACL 2025 (BiGGen-Bench | ❌ | medium | M4, M5, M6, M10 | 2 |
| openbench | Industry (Groq, official | ❌ | medium | M1, M2, M3, M5, M7 | 3 |
| tau2-bench | arXiv (Sierra AI); tau-b | ❌ | medium | M1, M3, M4, M5 | 3 |
| Bespoke Curator | Open-source tool (Bespok | ✅ | none | — | 0 |
| OASIS | arXiv 2024 | ✅ | none | — | 0 |
| Palisade Research — robot_shutdown_resistanc | other (Palisade Research | ✅ | none | — | 0 |
| R1 CoT Illegibility Revisited | LessWrong | ✅ | none | — | 1 |

See `survey.csv` / `survey.json` for full detail (evidence, call-site permalink, one-line fix, per-claim mechanism and confidence).

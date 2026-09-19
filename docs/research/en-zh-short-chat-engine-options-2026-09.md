# EN↔ZH Translation Engines for Short Colloquial Chat — Options as of Sept 2026

Companion to `docs/deadlock-translation-research.md` (glossary, slang, prompt tactics). This file covers **engine/API selection only**. Non-obvious claims are linked; **[V]** = vendor claim, not independently reproduced.

## 1. Cloud / API options

| System | EN↔ZH evidence | Glossary parameter | Multi-turn | Price /M tokens | Short-input latency |
|---|---|---|---|---|---|
| **Qwen-MT** (`qwen-mt-flash` / `plus` / `lite`, Alibaba Model Studio) | No public WMT / arena EN↔ZH number located (**gap**) | ✅ native `terms[]` array + `tm_list` translation memory + `domains` prompt ([docs](https://www.alibabacloud.com/help/en/model-studio/machine-translation)) | ❌ "single-turn translation only… system messages not supported" (same docs) | flash ¥0.7 in / ¥1.95 out CN (~$0.10/$0.27); SG ¥1.174/¥3.596 ([page](https://help.aliyun.com/en/model-studio/qwen-mt-flash)) | flash supports **incremental** streaming; `qwen-mt-lite` is positioned for "real-time chat and live comment translation" **[V]** |
| **DeepSeek V4-Flash / V4-Pro** | [XSCT Bench](https://www.xsctbench.com/testcase/l_multi_001): 中英互译 96.9 / 94.6; [日常会话](https://www.xsctbench.com/testcase/l_multi_002) 89.6 / 89.5 (mid-pack of 88) | prompt only | ✅ | Flash $0.14 / $0.28 (cache hit $0.028); Pro $1.74 / $3.48 ([pricing](https://apidog.com/blog/deepseek-v4-api-pricing/)) | not published |
| **GPT-5.5** | XSCT 中英互译 **98.4**, 日常会话 92.5; Tencent-run WMT25 GEMBA **83.29** ([table](https://www.digitalapplied.com/blog/specialist-translation-models-vs-frontier-llms-reference)) | prompt only | ✅ | $5 / $30 (apidog comparison table) | not published |
| **Gemini 3.1 Pro** | XSCT 96.79 / 90.71; Tencent-run FLORES-200 EN⇔XX XCOMET **94.42 — best of every compared system** | prompt only | ✅ | 3 Pro $2 / $12 ([BenchLM](https://benchlm.ai/models/gemini-3-pro)); 3.1 Pro not verified | not published |
| **Claude Opus 4.6** | XSCT 中英互译 **100.0**, 日常会话 91.1 (Sonnet 4.6 scored 94.15 there) | prompt only | ✅ | $15 / $75 (apidog comparison table) | not published |
| **Hy-MT2 via OpenRouter** | WMT25 GEMBA **84.34** (30B-A3B) — best of the compared set, Tencent-run | terminology via prompt template (documented) | ✅ (chat template) | $0.074 / $0.295 (7B, 30B-A3B); 1.8B $0.044 / $0.177 | not published |
| **Google Cloud Translation** NMT / Advanced-LLM / Adaptive | none published | ✅ native glossaries (v3 / Adaptive) | n/a | $20/M chars; $10+$10; $25+$25 ([pricing](https://cloud.google.com/translate/pricing)) | NMT lowest |
| **Azure Translator S1** | Tencent-run WMT25 GEMBA **67.63** — behind every Hy-MT2 size | ✅ custom translator | n/a | $10/M chars; $40 custom ([pricing](https://azure.microsoft.com/en-us/pricing/details/translator/)) | low |
| **DeepL** | no benchmark located | ✅ glossaries | n/a | Developer free 1M chars/mo; Growth $26/mo + $27.50/M | low |

**Caveats.** (1) XSCT Bench is an LLM-judged Chinese leaderboard whose public test cases are trivially easy (中英互译基础 = translate 「今天天气很好」; 日常会话 = translate "hello") — top scores saturate at 100 and the ranking is noisy (qwen3-8b 67.8 vs hunyuan-turbo 100.0). Treat it as a **weak discriminator**, not a verdict on "mid no". (2) All Hy-MT2-vs-frontier scores, including the GPT-5.5/Gemini/DeepSeek baselines, are **one Tencent-run evaluation** (arXiv 2605.22064 Table 2); no independent reproduction was found. (3) Whether frontier LLMs beat specialist MT flips by metric: specialists lead WMT25 XCOMET-XXL, frontier leads FLORES-200 EN⇔XX (same table).

## 2. Open-weight models on a 16 GB RTX 4070 Ti SUPER

Estimated throughput is bandwidth-derived, **not measured** ([ModelFit](https://modelfit.io/gpu/rtx-4070-ti-super/): 7B Q4_K_M ≈ 81 tok/s, ~0.4 s first token; 14B Q4 ≈ 45 tok/s). A 5-word ZH output is ~8–14 tokens → roughly **0.3–0.6 s** for 7B, less for 1.8B.

| Model | Params | Quants | Licence | Fit / latency | Failure modes |
|---|---|---|---|---|---|
| **Hy-MT2-1.8B** | 1.8B dense | Q4_K_M 1.1 GB (Ollama `maternion/hy-mt2:1.8b-q4_K_M`, `kaelri/hy-mt2`), FP8, 2-bit, 1.25-bit GGUF (440 MB) | Apache-2.0 per [LICENSE.txt read](https://www.digitalapplied.com/blog/specialist-translation-models-vs-frontier-llms-reference) + [mlx-community derivative metadata](https://huggingface.co/mlx-community/Hy-MT2-1.8B-8bit/raw/5d43a051b711d5de1e639d7fadf16c3c010cb7e9/README.md) — ⚠ contradicts the *Hunyuan Community Licence* (excludes EU/UK/KR) you recorded for Hunyuan-MT-7B/HY-MT1.5; **verify on the repo before shipping** (I could not fetch huggingface.co) | Best local fit | Vendor claims it beats Microsoft/Doubao APIs **[V]** |
| **Hy-MT2-7B** | 7B dense | FP8, GGUF | as above | ~4.5 GB Q4_K_M, fits with ASR/TTS resident | Specialised prompt format; no default system prompt; terminology only via "参考下面的翻译" examples ([card](https://ollama.com/maternion/hy-mt2:1.8b-q4_K_M)) |
| **Hy-MT2-30B-A3B** | MoE, 3B active, 128 experts/8 per token | FP8 | as above | Q4 ≈ 17–18 GB → **does not fit 16 GB**, CPU offload slows decode | — |
| **TranslateGemma 4B/12B/27B** | dense | community GGUF | **Apache-2.0** | 12B Q4 ≈ 8 GB | Human MQM: ja→en *below* Gemma 3 due to named-entity mistranslation; ZH not separately documented ([2026-01-15 launch](https://gihyo.jp/article/2026/01/translategemma), [tech report](https://arxiv.org/pdf/2601.09012)) |
| **North Small Translate** (Cohere) | — | open weight | open weight, 16K ctx | unknown | WMT26 83.6% is **provider-run with GPT-5.6 Sol as judge** ([BenchLM](https://benchlm.ai/benchmarks/wmt26)) — display-only |
| **Seed-X-7B / PPO-7B** | 7B | community GGUF | "other"/OpenMDW, **not verified** | fits | Card warns against multi-round chat format (your notes) |
| **TowerInstruct / TOWER+ 7B–72B** | 7B / 72B | — | **CC-BY-NC — blocks commercial use** | — | — |
| **NLLB-200-3.3B, MADLAD-400-3B** | 3B | GGUF/CTranslate2 | CC-BY-NC / Apache-2.0 | fast | 2022-era, general-domain, poor on colloquial short text; NLLB capped at 512 tokens |

**Int4/Int8 degradation.** The HY-MT1.5 authors state Int4 causes "significant accuracy degradation" and shipped FP8 instead ([report](https://ar5iv.labs.arxiv.org/html/2512.24092)) — so prefer **Q6_K/FP8 over Q4_K_M**; Hy-MT2's 1.25-bit/2-bit GGUFs are vendor-claimed-good and unverified. ⚠ I found **no independent Q4-vs-FP16 measurement for Hy-MT2**.

## 3. Ranking for this use case

| Rank | Best quality regardless of cost | Best practical |
|---|---|---|
| 1 | **Gemini 3.1 Pro** (best FLORES EN⇔XX of the compared set) or **GPT-5.5** (best short-pair XSCT); both need a slang glossary prompt | **Local: Hy-MT2-7B Q6_K** — sub-0.5 s, free, private, Apache-2.0, same weights already in the stack |
| 2 | **Claude Opus 4.6** (ties/beats on short conversational) | **Cloud: `qwen-mt-flash`** — the only leading option with a *native* `terms` glossary + incremental streaming, ~$0.10/$0.27 per M |
| 3 | **Hy-MT2-30B-A3B** (best WMT25 specialist; needs >16 GB) | **Hybrid: local Hy-MT2-7B primary + Qwen-MT fallback** when the term-hit count is high |

Latency dominates: at 1–12 words, decode time is trivial and **network RTT + provider TTFT is the whole budget**, so a local 7B usually *feels* faster than any API. Privacy and all-day cost also favour local.

## 4. Glossary / terminology

- **Native parameters:** Qwen-MT `terms[]` + `tm_list`; Google Cloud Translation glossaries/Adaptive; Azure custom translator; DeepL glossaries. One-line-per-term prompt blocks are documented for **Hy-MT2** ("Reference the following translations: X translates to Y").
- **Documented best practice (Qwen):** terms, translation memory and domain prompts all consume input tokens — "include only references directly relevant to the text being translated. Avoid passing large, generic reference lists" ([docs](https://www.alibabacloud.com/help/en/model-studio/machine-translation)).
- **Therefore, for ~4000 terms:** never inject the dictionary. (a) Aho-Corasick/regex-match the incoming message → inject only the 0–10 terms actually present; (b) enforce the same pairs deterministically in your existing `MiddlewareChain` post-pass (the game-term glossary has two valid ZH targets per term, so post-editing must accept both); (c) keep the *static* instruction block byte-identical at the prompt **prefix** so prefix caching applies — DeepSeek discounts cached input 80–92% ([pricing](https://apidog.com/blog/deepseek-v4-api-pricing/)); llama.cpp/Ollama reuse the KV prefix similarly. ⚠ No vendor publishes a glossary-size→latency curve; the prefix-cache benefit is documented only as a pricing/token fact.
- ⚠ Qwen-MT's restriction to **one user message, no system role** conflicts with multi-turn context windows; its 8,192-token input cap also caps glossary size per request.

## 5. Newer / easy to miss (2026)

- **TranslateGemma** (Google, 2026-01-15, Apache-2.0, 4/12/27B, 55 langs) — [launch](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/), [arXiv 2601.09012](https://arxiv.org/pdf/2601.09012).
- **Hy-MT2 + IFMTBench** (Tencent, 2026-05-21) — instruction-following MT benchmark, on-device 1.25-bit path ([arXiv 2605.22064](https://arxiv.org/abs/2605.22064)).
- **North Small Translate** (Cohere, 2026-09-10, open weight) — [blog](https://cohere.com/blog/north-small-translate).
- **TOWER+** (ACL 2026) — [paper](https://aclanthology.org/2026.acl-long.1366/).
- **ChatGPT Translate** (consumer feature, not an API; launched ~2026-01-15) — [report](https://m.techweb.com.cn/article/2026-01-15/2970628.shtml).
- **Leaderboards to verify claims yourself:** [WMT26 general task](https://www2.statmt.org/wmt26/translation-task.html) (Hunyuan sponsors a special award) + [video-subtitle task](https://www2.statmt.org/wmt26/video-subtitle-translation.html); [WMT25 findings, Kocmi et al. 2025](https://doi.org/10.18653/v1/2025.wmt-1.22) "Time to stop evaluating on easy test sets"; [BenchLM WMT26 mirror](https://benchlm.ai/benchmarks/wmt26) (display-only); [XSCT Bench](https://xsctbench.com/) (weak); [DiscoX, ICLR 2026](https://papernotes.org/ICLR2026/multilingual_mt/discox_benchmarking_discourse-level_translation_in_expert_domains/) discourse-level ZH benchmark.

## Final recommendation

Run **Hy-MT2-7B at Q6_K (or FP8) locally as the always-on engine** — immediate, private, zero marginal cost — with match-filtered glossary injection into a cached prompt prefix plus post-pass term enforcement. Keep **`qwen-mt-flash`** as the cloud fallback for term-heavy or ambiguous messages (native `terms`, incremental streaming, negligible cost), and benchmark it against **Gemini 3.1 Pro / GPT-5.5** on a hand-built 200-message Deadlock chat set before trusting any published leaderboard for this task; none of the leaderboards above evaluate 1–12-word gaming slang.

# Deadlock EN↔ZH Chat Translation: Terms, Local MT, Prompting, Player Base

Short in-game **text chat** for *Deadlock* (Valve, 6v6 MOBA/shooter). Non-obvious claims are linked; uncertainty is flagged.

> **Framing caveat.** Valve's own 简中 is the *worst-case* baseline, not the target: Chinese players call it "纯纯机翻水平" and preferred a community patch ([1](https://forums.playdeadlock.com/threads/%E4%B8%AD%E6%96%87%E7%BF%BB%E8%AF%91%E7%9B%AE%E5%89%8D%E5%A4%AA%E5%B7%AE%E5%8A%B2%EF%BC%8C%E7%BA%AF%E7%BA%AF%E6%9C%BA%E7%BF%BB%E6%B0%B4%E5%B9%B3.28719/), [2](https://forums.playdeadlock.com/threads/%E9%83%A8%E5%88%86%E7%BF%BB%E8%AF%91%E5%BB%BA%E8%AE%AE.22503/)). Terminology is **unstable**.

## (a) Glossary — EN → ZH

**[VG]** [vgover mechanics guide](https://www.vgover.com/news/113845) · **[BW]** [Bilibili Deadlock Wiki](https://wiki.biligame.com/playdeadlock/%E8%8B%B1%E9%9B%84%E6%80%BB%E8%A7%88) · **[D2]** [CN Dota2 glossary](https://bbs.it007.com/forum.php?mod=viewthread&tid=1236216) · **[LOL]** [CN LoL abbreviations](https://www.sinogamer.com/thread-62055-1-1.html)

| EN | ZH | Note | Src |
|---|---|---|---|
| Deadlock | **异锁** (official) / 死锁 | Renamed 2025-06; "死" sensitive | [GamerSky](https://www.gamersky.com/news/202506/1946042.shtml) |
| mid boss | 中路BOSS / 终极BOSS | | VG |
| urn | 魂瓮 / 灵瓮 | Both live | [VG](https://www.vgover.com/news/218875) |
| Guardian (T1) | 守卫者 | | VG |
| Walker (T2) | 地行者 | | VG |
| Base Guardian (T3) | 基地守护者 | | VG |
| Shrine | 神龛 | | VG |
| Patron / core | 大守护者 / 水晶 | | VG |
| lane | 兵线 | 4 lanes 黄/橙/蓝/紫 | VG |
| zipline | 索道 / 滑索 | | VG |
| jungle / jungling | 野区 / 打野 | | VG, LOL |
| souls | 魂灵 / 灵魂 / 魂魄 | **3 variants in use** | VG, BW |
| Spirit (stat) | 元灵 (official); 魂力/灵力/灵能 | Contested | BW, [forum](https://forums.playdeadlock.com/threads/%E9%83%A8%E5%88%86%E7%BF%BB%E8%AF%91%E5%BB%BA%E8%AE%AE.22503/) |
| last hit / deny | 补刀(正补) / 反补 | | VG, D2 |
| unsecured souls | 未保护魂灵 | | VG |
| gank | 抓人 / 游走 | | D2, LOL |
| push | 推进 / 推 | | D2, LOL |
| rotate | 转线 / 支援 | ⚠ no fixed term found | — |
| ult / ulti | 大招 | | D2, LOL |
| feed | 送 / 送人头 | | D2, LOL |
| ks | 抢人头 | | LOL |
| enemy missing | miss / MIA / 敌人消失 | Players type *miss* | D2, LOL |
| def | 防守 / 守 | | D2 |
| b | 撤 / 闪 / **3** | "3" is native CN | D2, LOL |
| brb / afk / noob | 马上回来 / 挂机 / 菜鸟 | | LOL |
| gg / ez / smurf / toxic | **keep English** | ⚠ no settled CN forms | D2, LOL |
| Haze / Lash / Seven | 暗影→**岚梦**; 神鞭→**劳什**; 老七→**柒** (2025-09) | Haze rename drew 290+ reactions | [forum](https://forums.playdeadlock.com/threads/chinese-localization-after-todays-update-is-really-bad-%E4%BB%8A%E5%A4%A9%E6%9B%B4%E6%96%B0%E4%B9%8B%E5%90%8E%E7%9A%84%E4%B8%AD%E6%96%87%E7%BF%BB%E8%AF%91%E9%9D%9E%E5%B8%B8%E5%B7%AE%E5%8A%B2.80785/) |
| nicknames | 蓝牛/蓝胖, 火男, 冰男, 机枪妹, 电男 | ≠ official names | [ali213](https://gl.ali213.net/html/2024-9/1491289.html) |

**Implication:** the glossary must be **per-patch** and accept two valid ZH targets (official vs. community); many slang tokens should pass through unchanged.

## (b) Local open-source MT, EN↔ZH

| Model | Params / License | Type | zh↔en evidence | Short-chat fit | Literal-slang risk |
|---|---|---|---|---|---|
| **Hy-MT2-1.8B/7B/30B-A3B** | 1.8B–30B MoE; Tencent HY licence (⚠ excludes EU/UK/KR) | MT-specialised, 33 langs | 1.8B beats MS/Doubao APIs ([card](https://ollama.com/RogerBen/HY-MT2-1.8B)) | **Best** — built for scenario use | Low; style/personalisation prompts |
| **HY-MT1.5-1.8B/7B** | 1.8B/7B; same | MT-specialised | Human 0–4 ZH⇒EN/EN⇒ZH **3.01/2.61**, best vs all commercial APIs (Google 2.34); **0.18 s** latency ([report](https://ar5iv.labs.arxiv.org/html/2512.24092)) | **Best-documented** | Lowest — RL scores Cultural Appropriateness + Fluency |
| **Hunyuan-MT-7B** | 7B; same | MT LLM, 33 langs | FLORES-200 XCOMET-XXL 0.8643 ZH⇔XX; WMT25 **first in 30/31** ([card](https://hf-mirror.com/tencent/Hunyuan-MT-7B/raw/main/README.md), [report](https://ar5iv.labs.arxiv.org/html/2509.05209v1)) | Terse template by design ("不要额外解释") | Medium — report names slang/neologisms **unsolved**; has terminology RL reward |
| **Hunyuan-MT-Chimera-7B** | 7B; same | Fusion of 6 candidates | Beats base ([report](https://ar5iv.labs.arxiv.org/html/2509.05209v1)) | **Poor** — 6× generations first | Lower than base |
| **kaelri/hy-mt2** (Ollama) | 1.8b/7b; same | **Packaging only** — official GGUF | Author's bench **COMET 0.8954** FLORES zh-en ([README](https://ollama.com/kaelri/hy-mt2)) | Good; 256K ctx | Same as base |
| **Seed-X-7B / PPO-7B** | 7B; OpenMDW | MT, Mistral arch | ZH⇒XX 0.8010 / XX⇒ZH 0.7702 | **Worst** — card says avoid multi-round conversation format | Medium-high |
| **Qwen-MT ("Qwen3-MT")** | undisclosed; **proprietary API** | MT, 92 langs | No public zh-en numbers ([docs](https://www.alibabacloud.com/help/en/model-studio/machine-translation)) | Mixed — *single-turn only*, no system messages | Low-med; glossary `terms` + domain prompt |
| **Qwen3-8B/14B/32B** | Apache-2.0 | General LLM | 0.7250/0.8056, 0.7826/0.8318, 0.7933/0.8436 | Good (chat-native) | Higher — no MT terminology reward |
| **Tower-Plus-9B/72B** | 9B/72B; **CC-BY-NC** | General LLM tuned for MT | 0.7726/0.7912; 0.7703/0.8235 | Good | Medium; ⚠ NC blocks commercial use |
| **NLLB-200** | 600M–54B MoE; **CC-BY-NC** | Sentence-level enc-dec, 200 langs | Paper: +44% BLEU vs prior SOTA ([paper](https://arxiv.org/abs/2207.04672)) | **Poor** — *"not released for production"* | High |
| **OPUS-MT** | ⚠ ~75M unverified; CC-BY-4.0 | Marian, one per pair | Tatoeba BLEU 36.1 (2020) | Poor — no chat/context | **Highest** |
| **MADLAD-400** | 3B/7B/10B; Apache-2.0 | T5 seq2seq, 450+ langs | No zh-en XCOMET | Poor — general domain only | High |

**Caveats.** (1) "1.8B is a community distillation" is **false** — HY-MT1.5-1.8B/7B are official Tencent releases, distilled *by Tencent*; `kaelri` is only a packager ([report](https://ar5iv.labs.arxiv.org/html/2512.24092)). (2) WMT25 is **30/31, not 31/31**. (3) Qwen3-MT has **no open weights** — it is an API name. (4) ⚠ Your default `kaelri/hy-mt2:1.8b-q4_K_M` **exists**, but the HY-MT1.5 authors state Int4 causes *"significant accuracy degradation"* and chose FP8 — **prefer Q6_K (the packager's own default) or FP8**, and budget stop sequences for documented control-token leakage. (5) Scores are **not comparable across the two Tencent reports** (Tower-Plus-72B: 0.7002 vs 0.7969).

## (c) Short-chat prompt engineering

**Failure modes (documented).** Google's WMT24 audit found LLM output containing *refusals, alternative translations and commentary*, naming **"short input segments lacking sufficient context"** as the primary cause ([Briakou et al. 2024](https://arxiv.org/abs/2410.00863)). ChatGPT MT appended `(Note: …)` in non-English-centric pairs incl. ZH ([Peng et al. 2023](https://ar5iv.labs.arxiv.org/html/2303.13780)); chat MQM found all systems *"overly correcting ambiguous source content"* ([MQM-Chat](https://arxiv.org/abs/2408.16390)); turn-level quality outruns conversation-level ([WMT24 Chat](https://aclanthology.org/2024.wmt-1.59/)). Mistranslated named entities are a **separate critical error class** ([Guerreiro et al. 2023](https://ar5iv.labs.arxiv.org/html/2208.05309)) — exactly the hero-name case. ⚠ **Unsourced:** no primary study on pinyin-instead-of-Hanzi output, nor language-ID failure at 1–3 words; test locally.

**Effective techniques**
1. **Glossary injection** — Qwen-MT exposes a `terms` array ([docs](https://www.alibabacloud.com/help/en/model-studio/machine-translation)); terminology-constrained refinement lifts recall ([Bogoychev & Chen 2023](https://arxiv.org/abs/2310.05824)).
2. **Temperature 0** — 0→1 costs **−4.3 COMET** on EN→ZH *and* increased hallucinated appendices ([Peng et al. 2023](https://ar5iv.labs.arxiv.org/html/2303.13780)). Cheapest fix for added commentary.
3. **Prior-turn context** — multi-turn beat segment-level, **largest gain (+4.16 dBLEU) where "segments are short and require context"** ([Hu et al. 2025](https://ar5iv.labs.arxiv.org/html/2503.10494)). Directly supports a sliding window for "mid no".
4. **Few-shot** — 3-shot > 1-shot; TopK-selected > random; *suboptimal examples degrade output* ([Peng](https://ar5iv.labs.arxiv.org/html/2303.13780), [Zhang](https://arxiv.org/abs/2301.07069)). ⚠ Not verified for ≤8-word inputs.
5. **Output-only + delimiters** — Hunyuan-MT hard-codes it: `把下面的文本翻译成<目标语言>，不要额外解释。` ([report](https://ar5iv.labs.arxiv.org/html/2509.05209v1)).
6. **Keep-as-is list** — Qwen-MT pins `Transformer → Transformer`; [pyvideoTrans](https://doc.pyvideotrans.com/aitranslate) documents glossary instructions for chat subtitles. Keep domain labels accurate — **wrong domain degrades quality** ([Peng et al. 2023](https://ar5iv.labs.arxiv.org/html/2303.13780)).

## (d) Population & language mix

- **Servers:** NA-Central (Chicago), EU (Stockholm), **Asia (Hong Kong)**, SA (Santiago), OCE (Sydney) ([list](https://forums.playdeadlock.com/threads/does-the-region-in-the-game-currently-affect-anything.4111/), [GearUP](https://www.gearupbooster.com/blog/change-deadlock-servers.html)). Hong Kong is the natural CN endpoint.
- **No user-facing region picker.** Region is set only by the `citadel_region_override` cvar (F7), which **broke ~early 2026** ([thread](https://forums.playdeadlock.com/threads/citadel_region_override.113839/)). A northern-China player reports **150 ms in ranked** but acceptable casual ping ([thread](https://forums.playdeadlock.com/threads/why-doesnt-the-ranked-mode-server-have-regions.153641/)).
- **Mixed-language lobbies are normal.** EU players repeatedly landed in all-Russian lobbies with "communication impossible" ([thread](https://forums.playdeadlock.com/threads/mm-keeps-putting-me-in-full-russian-lobbies-i-live-1700km-away-from-russian-border.36942/), 19+ reactions) — the demand signal.
- **CN population: large Steam-wide, unquantified for Deadlock.** Simplified Chinese became Steam's #1 language (Aug 2024, ~35%, driven by *Black Myth*) while Deadlock peaked at **171,490** concurrent (2024-09-02), falling to **~6,455** by 2025-06 ([GameLook](http://www.gamelook.com.cn/2024/09/553377/), [GamerSky](https://www.gamersky.com/news/202506/1946042.shtml)). ⚠ **No per-title CN share is published.**
- **CN infrastructure exists:** [Bilibili wiki](https://wiki.biligame.com/playdeadlock/%E8%8B%B1%E9%9B%84%E6%80%BB%E8%A7%88), an [NGA board](https://ngabbs.com/thread.php?fid=510478), Bilibili guides teaching English callouts ([video](https://www.bilibili.com/video/BV182Nuz6ExR/)), a 5EPlay "common English phrases" article ([link](http://csgo.5eplay.com/article/2410227c9f38) — JS-rendered, not retrievable).
- **⚠ Highest-leverage finding.** Deadlock has a long-standing **IME bug: typing Chinese crashes the game** ([2024-07](https://forums.playdeadlock.com/threads/ime-input-method-editor-support.10609/); recurrences [1](https://forums.playdeadlock.com/threads/play-games-with-chinese-input-sometimes-freeze-keyboard.8631/), [2](https://forums.playdeadlock.com/threads/chinese-iem-bug.28810/)). **Verify against the current build** — if it holds, CN players *cannot type Chinese in chat at all*, so the valuable direction is **EN→ZH overlay** plus **pinyin/abbreviation→EN**, not ZH→EN text entry.

## (e) Community slang absent from official localisation

These will **not** appear in the game's own string tables, so a glossary derived from localisation files misses them entirely. Sources: **[D2]**, **[LOL]**, and **[AT]** [CN game-abbreviation glossary](https://www.alicetec.cn/archives/UMsX6z3T).

| EN | ZH (community) | Src |
|---|---|---|
| gg | 认输 / kept as `gg` ("输的一方打出来…自己认输的一种表现") | [LOL] |
| wp / ggwp | 打得好 | [AT] |
| glhf / gl / hf | 祝你好运，玩得开心 (开局用语) | [AT], [D2] |
| ez | ⚠ **no settled CN form — keep English** | — |
| ks | 抢人头 | [LOL] |
| feed / feeder | 送人头 / "经验书" (养肥敌人的玩家) | [LOL], [D2] |
| noob | 菜鸟 | [LOL] |
| oom | 没魔了 | [LOL] |
| cd | 冷却时间 | [LOL] |
| ult / ulti | 大招 | [D2], [LOL] |
| gank | 抓人 / 游走 | [D2], [LOL] |
| rotate | 转线 / 支援 ⚠ no fixed term found | — |
| deny | 反补 | [D2], [LOL] |
| b | 撤 / 闪 / **3** ("3" is native CN) | [D2], [LOL] |
| brb | 马上回来 | [LOL] |
| push | 推进 | [D2], [LOL] |
| def | 防守 / 守 | [D2] |
| miss | 消失 / 敌人消失 | [D2], [LOL] |
| afk | 挂机 | [LOL] |
| imba | 不平衡 (过强或过弱) | [D2] |
| nerf | 削弱 | [D2] |
| ff | 认输 / 弃权 | [D2] |
| bd | 偷塔 | [D2], [LOL] |
| smurf / toxic / **int / throw / tilt / diff / low** | ⚠ **no sourced CN equivalent found** — do not invent one; pass through or test empirically | — |

⚠ The last row is a genuine gap, not an oversight: my fetched CN glossaries contain no entries for *int*, *throw*, *tilt*, *diff*, or *low* (as in "he's low" → likely 残血, but **unsourced**). Treat these as hypotheses to validate against real chat logs before hard-coding.

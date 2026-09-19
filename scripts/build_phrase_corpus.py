"""把三份语料合并成项目可直接用的数据文件。

三份来源：
  A. 官方聊天轮盘（66 条）——Valve 自带英↔简中，玩家实际点的呼号
  B. 官方核心术语（从本地化里查到的官方译名：卫士/机甲/守护神/灵瓮/复生石/正补/回收…）
  C. 社区常用说法（中文玩家实际打字）—— 人工整理，英文侧对齐官方术语

产出：
  data/deadlock_callouts.json     官方呼号（英↔中）
  data/deadlock_terms_official.json  官方核心术语（英↔中，带 token 出处）
  data/deadlock_zh2en.json       中文→英文 术语/短语（**补齐我们最缺的那一侧**）
  data/deadlock_testset.jsonl    30 条真实中文聊天 + 期望术语，用于改前改后量化对比

用法：python scripts/build_phrase_corpus.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LOC = Path(r"D:\software\steam\steamapps\common\Deadlock\game\citadel"
           r"\resource\localization")
LINE_RE = re.compile(r'^\s*"([^"]+)"\s+"(.*)"\s*$')

# ---------------------------------------------------------------------------
# B. 官方核心术语：英文原文 -> 在本地化里精确/近似查到的官方中文
#    （provenance 里的 token 可以直接回查，方便随版本更新重新核对）
# ---------------------------------------------------------------------------
OFFICIAL_TERMS: list[tuple[str, str, str]] = [
    # 英文术语, 官方中文, token 出处
    ("souls", "魂魄", "Citadel_Hero_Stats_Souls"),
    ("last hit", "正补", "Citadel_LaneStats_LastHits"),
    ("deny", "回收", "Citadel_Profile_Stats_Denies:f"),
    ("ability points", "技能点", "guide_upgrades_killing_guardians_header"),
    ("boon", "恩赐", "Citadel_Player_Level_PowerIncrease"),
    ("imbue", "加强", "item_info_imbue"),
    ("flex slot", "弹性槽位", "CitadelCategoryFlex"),
    ("guardian", "卫士", "Citadel_Hud_KillFeedGuardian"),
    ("walker", "机甲", "Citadel_Hud_KillFeedWalker"),
    ("shrine", "圣坛", "Citadel_Hud_KillFeedShieldName"),
    ("patron", "守护神", "Citadel_Hud_KillFeedTitan"),
    ("urn", "灵瓮", "Citadel_HUD_IdolReturned"),
    ("mid-boss", "中区头目", "Objective_MidBoss"),
    ("rejuvenator", "复生石", "Item_Rejuvenator"),
    ("trooper", "步兵", "Citadel_AttackerClass_CLASS_TROOPER"),
    ("neutrals", "中立生物", "guide_neutrals_header"),
    ("zipline", "滑索", "Citadel_ZiplineBoostDesc"),
    ("stamina", "耐力", "extra_stamina_pickup_label"),
    ("headshot", "头弹", "citadel_build_tag_headshots"),
    ("lane", "对线", "Citadel_HeroBuilds_Lane"),
    ("stun", "眩晕", "citadel_chatwheel_label_Stun"),
    ("shop", "商店", "citadel_settings_shop"),
    ("dash", "冲刺", "citadel_ability_dash"),
    ("parry", "格挡", "citadel_ability_melee_parry"),
    ("melee", "近战", "Citadel_ShopFilter_Melee"),
]

# ---------------------------------------------------------------------------
# C. 社区常用说法：中文玩家实际会打的 -> 游戏内英文（英文侧与官方术语一致）
#    kind: term=术语, phrase=整句, slang=黑话
# ---------------------------------------------------------------------------
ZH2EN: list[tuple[str, str, str]] = [
    # —— 最要命的那批黑话（模型会按字面翻错）——
    ("送", "feed", "slang"),
    ("送了", "fed", "slang"),
    ("别送", "stop feeding", "phrase"),
    ("别送了", "stop feeding", "phrase"),
    ("一直送", "keep feeding", "phrase"),
    ("你在送", "you're feeding", "phrase"),
    ("送人头", "feeding kills", "slang"),
    ("送了全队", "feeding the whole team", "phrase"),
    # —— 战斗呼号 ——
    ("越塔", "dive", "slang"),
    ("越塔杀他", "dive him", "phrase"),
    ("抱团", "group up", "slang"),
    ("抱团推", "group up and push", "phrase"),
    ("开团", "initiate", "slang"),
    ("别开团", "don't initiate", "phrase"),
    ("抓人", "gank", "slang"),
    ("蹲人", "camp them", "slang"),
    ("绕后", "flank", "slang"),
    ("他们在绕后", "they're flanking", "phrase"),
    ("撤退", "get back", "phrase"),
    ("撤", "back", "phrase"),
    ("上", "go", "phrase"),
    ("上啊", "go", "phrase"),
    ("推进", "push", "phrase"),
    ("推塔", "push the guardian", "phrase"),
    ("别浪", "play safe", "phrase"),
    ("稳住", "hold", "phrase"),
    ("等我", "wait for me", "phrase"),
    ("我来了", "on my way", "phrase"),
    ("跟我来", "come with me", "phrase"),
    ("掩护我", "cover me", "phrase"),
    ("小心", "care", "phrase"),
    ("小心绕后", "care, they're flanking", "phrase"),
    ("敌人消失", "missing", "phrase"),
    ("对面不见了", "enemy missing", "phrase"),
    # —— 资源与目标 ——
    ("魂瓮", "urn", "term"),
    ("灵瓮", "urn", "term"),
    ("抢魂瓮", "contest the urn", "phrase"),
    ("魂瓮要没了", "urn is about to expire", "phrase"),
    ("复生石", "rejuvenator", "term"),
    ("复生石掉了", "rejuv is dropping", "phrase"),
    ("大怪", "mid boss", "slang"),
    ("中区头目", "mid boss", "term"),
    ("打大怪", "do mid boss", "phrase"),
    ("卫士", "guardian", "term"),
    ("机甲", "walker", "term"),
    ("圣坛", "shrine", "term"),
    ("守护神", "patron", "term"),
    ("步兵", "trooper", "term"),
    ("野怪", "neutrals", "slang"),
    ("打野", "farm camps", "slang"),
    ("刷野", "farm camps", "phrase"),
    ("正补", "last hit", "term"),
    ("补刀", "last hit", "slang"),
    ("反补", "deny", "slang"),
    ("回收", "deny", "term"),
    ("魂魄", "souls", "term"),
    ("经济", "souls", "slang"),
    ("装备", "item", "term"),
    ("出装", "build", "slang"),
    ("技能点", "ability points", "term"),
    ("大招", "ult", "slang"),
    ("大好了", "ult is ready", "phrase"),
    ("没耐力", "no stamina", "phrase"),
    ("滑索", "zipline", "term"),
    ("商店", "shop", "term"),
    # —— 路线（Deadlock 是四条彩色线）——
    ("中路", "mid", "term"),
    ("黄路", "yellow", "term"),
    ("蓝路", "blue", "term"),
    ("绿路", "green", "term"),
    ("紫路", "purple", "term"),
    ("换线", "swap lanes", "phrase"),
    ("需要帮忙", "need help", "phrase"),
    # —— 礼节/收尾 ——
    ("漂亮", "good job", "phrase"),
    ("干得漂亮", "good job", "phrase"),
    ("打得好", "good job", "phrase"),
    ("谢了", "thanks", "phrase"),
    ("谢谢", "thanks", "phrase"),
    ("我的", "my bad", "phrase"),
    ("抱歉", "sorry", "phrase"),
    ("稳住别急", "hold, don't rush", "phrase"),
    ("一起上", "go together", "phrase"),
    # —— 口语别名（玩家实际怎么说，与官方译名并存；用户要求"都收录"）——
    ("塔", "guardian", "alias"),
    ("大机器人", "walker", "alias"),
    ("机器人", "walker", "alias"),
    ("神坛", "shrine", "alias"),
    ("老家", "patron", "alias"),
    ("基地", "patron", "alias"),
    ("小兵", "trooper", "alias"),
    ("缆车", "zipline", "alias"),
    ("体力", "stamina", "alias"),
    ("爆头", "headshot", "alias"),
    ("复活石", "rejuvenator", "alias"),
    ("灵魂", "souls", "alias"),
    ("钱", "souls", "alias"),
    ("蹲点", "camp", "alias"),
    ("偷家", "backdoor", "alias"),
    ("反蹲", "counter-gank", "alias"),
    ("控住", "stun", "alias"),
    ("晕了", "stunned", "alias"),
    ("慢一下", "slow", "alias"),
    ("打断", "interrupt", "alias"),
    ("买装备", "buy items", "alias"),
    ("回城", "go back to base", "alias"),
    ("补给", "heal up", "alias"),
]

# ---------------------------------------------------------------------------
# D. 测试集：真实中文聊天 + 期望出现的关键英文术语（改前改后对比用）
# ---------------------------------------------------------------------------
TESTSET: list[tuple[str, list[str]]] = [
    ("别送了", ["feeding"]),
    ("你一直送，都已经0-10了", ["feeding"]),
    ("别送了，行吗？你一直送，都已经0-10了。", ["feeding"]),
    ("中路没人", ["mid"]),
    ("小心对面绕后", ["flank"]),
    ("我来了", ["on my way"]),
    ("抱团推进", ["group up"]),
    ("等我大招", ["ult"]),
    ("魂瓮要没了", ["urn"]),
    ("复生石掉了", ["rejuv"]),
    ("打大怪", ["mid boss"]),
    ("越塔杀他", ["dive"]),
    ("撤退", ["back"]),
    ("别浪", ["safe"]),
    ("我残血了", ["low"]),
    ("机甲在推", ["walker"]),
    ("别开团", ["initiate"]),
    ("跟我来", ["come with me"]),
    ("掩护我", ["cover me"]),
    ("他们在打野", ["camps"]),
    ("反补一下", ["deny"]),
    ("补刀别漏", ["last hit"]),
    ("谢了", ["thanks"]),
    ("干得漂亮", ["good job"]),
    ("我的", ["my bad"]),
    ("一起上", ["go"]),
    ("稳住别急", ["hold"]),
    ("黄路需要帮忙", ["help"]),
    ("换线吧", ["swap"]),
    ("他们圣坛没了", ["shrine"]),
]


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)

    # A. 官方呼号：复用 collect 脚本的解析
    from collect_deadlock_phrases import parse_locale  # type: ignore

    name = "citadel_main"
    en = parse_locale(LOC / name / f"{name}_english.txt")
    zh = parse_locale(LOC / name / f"{name}_schinese.txt")
    callouts: dict[str, dict[str, str]] = {}
    pat = re.compile(r"^citadel_chatwheel_(label|message)_(.+)$")
    for token, text in en.items():
        m = pat.match(token)
        if not m:
            continue
        entry = callouts.setdefault(m.group(2), {})
        key = "en" if m.group(1) == "message" else "labelEn"
        entry[key] = text.strip()
        zt = zh.get(token, "")
        if zt:
            entry["zh" if m.group(1) == "message" else "labelZh"] = zt.strip()
    callouts = {k: v for k, v in callouts.items()
                if v.get("en") and v.get("zh")}

    (DATA / "deadlock_callouts.json").write_text(
        json.dumps(callouts, ensure_ascii=False, indent=1), encoding="utf-8")

    # B. 官方术语
    terms = {en_t: {"zh": zh_t, "token": token}
             for en_t, zh_t, token in OFFICIAL_TERMS}
    (DATA / "deadlock_terms_official.json").write_text(
        json.dumps(terms, ensure_ascii=False, indent=1), encoding="utf-8")

    # C. 中文→英文
    zh2en = {zt: {"en": en_t, "kind": kind} for zt, en_t, kind in ZH2EN}
    (DATA / "deadlock_zh2en.json").write_text(
        json.dumps(zh2en, ensure_ascii=False, indent=1), encoding="utf-8")

    # C2. 给 Glossary 直接加载的扁平表 {中文: 英文}。
    #     与 glossary.json（英→中）对称，补上一直空着的中文侧。
    flat = {zt: en_t for zt, en_t, _kind in ZH2EN}
    (DATA / "glossary_zh.json").write_text(
        json.dumps(flat, ensure_ascii=False, indent=1), encoding="utf-8")

    # D. 测试集
    with (DATA / "deadlock_testset.jsonl").open("w", encoding="utf-8") as fh:
        for text, expect in TESTSET:
            fh.write(json.dumps({"zh": text, "expect": expect},
                                ensure_ascii=False) + "\n")

    # 顺带写一份人看的 TSV，便于校对
    with (DATA / "deadlock_corpus.tsv").open("w", encoding="utf-8") as fh:
        fh.write("kind\tzh\ten\n")
        for zt, item in zh2en.items():
            fh.write(f"{item['kind']}\t{zt}\t{item['en']}\n")
        for key, item in sorted(callouts.items()):
            fh.write(f"callout\t{item['zh']}\t{item['en']}\n")

    print(f"官方呼号      {len(callouts):4} 条 -> data/deadlock_callouts.json")
    print(f"官方核心术语  {len(terms):4} 条 -> data/deadlock_terms_official.json")
    print(f"中文→英文     {len(zh2en):4} 条 -> data/deadlock_zh2en.json")
    print(f"测试集        {len(TESTSET):4} 条 -> data/deadlock_testset.jsonl")
    print("人读版        -> data/deadlock_corpus.tsv")
    print("\n中文→英文采样：")
    for zt in list(zh2en)[:14]:
        print(f"  {zt:12} -> {zh2en[zt]['en']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""data/ 目录的数据质检：把"术语表里混进了垃圾"这件事变成可执行的检查。

## 为什么需要它

术语/俚语/保留词都是**自动生成 + 手工维护**混在一起的，一次重跑生成脚本就可能
把垃圾重新灌回来。实测踩过的全部问题都写在下面对应的检查里（每条都标注了症状），
这个脚本的作用是：改数据前后各跑一次，看数字有没有变差。

## 用法

    python scripts/check_data_quality.py            # 只看有没有问题
    python scripts/check_data_quality.py -v         # 连每条坏数据都列出来
    python scripts/check_data_quality.py --strict   # 有任何 WARN 就以非 0 退出（CI 用）

退出码：0 = 通过（可能有 WARN），1 = 有 FAIL，2 = 数据文件缺失/损坏。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
CJK_SPACE_RE = re.compile(r"[\u4e00-\u9fff][ \t]+[\u4e00-\u9fff]")
TEMPLATE_RE = re.compile(r"&[a-z]+;|[{}]|[%$]\w")
PINYIN_RE = re.compile(r"[a-z]{2,}")
LONE_UNIT_RE = re.compile(r"(?<![A-Za-z])(?:s|m|x|sec|secs|stacks)(?![A-Za-z])", re.I)


class Report:
    def __init__(self, verbose: bool):
        self.verbose = verbose
        self.fails: list[str] = []
        self.warns: list[str] = []

    def check(self, name: str, bad: list, limit: int, level: str = "FAIL",
              hint: str = "", show: bool = True):
        n = len(bad)
        if n == 0:
            print(f"  ✅ {name}")
            return 0
        mark = "❌" if level == "FAIL" else "⚠️ "
        print(f"  {mark} {name}: {n} 条" + (f"（上限 {limit}）" if limit else ""))
        if hint:
            print(f"      ↳ {hint}")
        if show and (self.verbose or n <= 6):
            for item in bad[:20]:
                print(f"      · {item}")
        (self.fails if level == "FAIL" else self.warns).append(f"{name}: {n}")
        return n


def load(name: str):
    path = DATA / name
    if not path.exists():
        print(f"缺少数据文件: {path}", file=sys.stderr)
        raise SystemExit(2)
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true", help="列出每条坏数据")
    ap.add_argument("--strict", action="store_true", help="有 WARN 也返回非 0")
    args = ap.parse_args()

    r = Report(args.verbose)
    print("术语表 data/glossary.json")
    glossary = load("glossary.json")
    terms = glossary.get("terms", {})

    # 症状：从本地化文件刮出来的排版残留（"肉  盾"、"高  压  电"、"区 域 封 锁"）
    spaced = [f"{k} -> {v['zh']!r}" for k, v in terms.items()
              if CJK_SPACE_RE.search(v.get("zh", ""))]
    r.check("中文译名里混了排版空格（会教模型照抄怪空格）", spaced, 0,
            hint="生成脚本的 clean() 应该压掉中文字之间的空格")

    # 症状：大小写只差一个字母的重复键（Silencer/silencer 共 62 组），
    # 它们不是"两种写法都有用"，而是同一术语被记了两遍
    lower = {}
    for k in terms:
        lower.setdefault(k.lower(), []).append(k)
    dupes = [f"{v}" for v in lower.values() if len(v) > 1]
    r.check("大小写重复键（同一术语记了两遍）", dupes, 0)

    # 症状："other} Won"、"%hero_name% 出装"、"&nbsp;killed themself" 这种模板碎片
    templated = [f"{k} -> {v.get('zh')!r}" for k, v in terms.items()
                 if TEMPLATE_RE.search(k) or TEMPLATE_RE.search(v.get("zh", ""))]
    r.check("键或译名里含模板碎片（{} %s &nbsp;）", templated, 0)

    # 症状：剥掉数值占位符后留下的残句（"+s Duration"、"Recast within s."）
    # ⚠️ 规则收窄到"符号 + 单位"：第一版写成"任意位置的孤立 s/m"，把正常的
    #    "On Max Stacks Proc"（Stacks 里有 s）和 "S America" 误报了。
    lone = [k for k in terms if re.search(r"[+\-–]\s*(?:s|m|x|sec|secs)\b", k, re.I)]
    r.check("键里有孤立的单位 token（数值占位符被剥掉的残句）", lone, 0)

    # 症状：拼音没删干净（phrases.json 末尾曾有一条 "信号轮盘 xinhao lunpan"）
    def latin_words(value: str) -> list[str]:
        return [w for w in re.findall(r"[A-Za-z]{2,}", value)]

    pinyin = [f"{k} -> {v!r}" for k, v in terms.items()
              if CJK_RE.search(v.get("zh", "")) and latin_words(v["zh"])]
    r.check("译名里混了拉丁字母（多为拼音残留）", pinyin, 20, level="WARN",
            hint="英雄译名（麦金妮）、ID/Alt/Shift/VAC 这类界面词本来就带字母，"
                 "只有明显超过这个量才说明是未翻译残留")

    print("\n整句/短语 data/phrases.json")
    phrases = load("phrases.json")
    bad_phrases = [f"{k!r} -> {v!r}" for k, v in phrases.items()
                   if CJK_RE.search(v) and PINYIN_RE.search(v) and latin_words(v)]
    r.check("短语译文里混了拼音", bad_phrases, 0)

    # 症状：分路的英文与译名对不上。判据：译文里的分路色必须和英文键里的分路色一致
    # （纯色词键如 "Push Purple" 则反过来检查）。
    # deadlock_callouts.json 是**人工参考快照**（运行时没人读）—— 它曾经有
    # "Purple 的英文写成 Green"（紫路→Defend Green），会把紫路说成绿路，所以一起查。
    lane_zh = {"green": "绿", "blue": "蓝", "yellow": "黄", "purple": "紫", "orange": "橙"}
    wrong_lane = []
    callouts_path = DATA / "deadlock_callouts.json"
    callouts = json.loads(callouts_path.read_text(encoding="utf-8")) if callouts_path.exists() else {}
    for k, v in list(phrases.items()) + list(callouts.items()):
        if not CJK_RE.search(str(v)):
            continue
        en_colors = {c for c in lane_zh if re.search(rf"\b{c}\b", k, re.I)}
        zh_colors = {c for c, ch in lane_zh.items() if ch in str(v)}
        if en_colors and zh_colors and en_colors != zh_colors:
            wrong_lane.append(f"{k} -> {v}")
        elif not en_colors and len(zh_colors) == 1 and re.fullmatch(
                rf"(?:Push|Defend|Missing|Headed to)\s+\w+", k, re.I):
            # 形如 "HeadedToPurple"（驼峰/下划线写法）也要能认出来
            m = re.search(r"(Green|Blue|Yellow|Purple|Orange)", k, re.I)
            if m and {m.group(1).lower()} != zh_colors:
                wrong_lane.append(f"{k} -> {v}")
    r.check("分路名与译名不一致（紫/绿 写反）", sorted(set(wrong_lane)), 0)

    print("\n俚语与保留词")
    slang = {k: v for k, v in load("slang.json").items() if not k.startswith("_")}
    keep_doc = load("keep_as_is.json")
    keep = [w for w in keep_doc.get("keep", []) if w]
    overrides = {str(w).lower() for w in (keep_doc.get("_slang_overrides") or [])}

    # 症状：同一个词两张表都有 → stash 先跑 → 既不翻也不解释（afk/ult/b 全中）
    overlap = sorted(({w.lower() for w in keep} & {k.lower() for k in slang}) - overrides)
    r.check("keep_as_is 与 slang 重叠（会让两条规则同时失效）", overlap, 0,
            hint="按 keep_as_is.json 的 _conflict_note 处理：默认俚语优先，"
                 "确实要保留英文的写进 _slang_overrides")

    print("\n游戏名保护表 data/gamenames.json")
    names = load("gamenames.json")
    # 症状：别名来自本地化的 _search 关键字，里面混进了**别的游戏**的词
    #   （不朽尸王/刷新球/大电锤 是 Dota 的叫法，映射过来是错的）。
    # ⚠️ 别名在这里是**键**，不是值 —— 这个方向搞反过一次，检查会永远"通过"。
    dota = ["不朽尸王", "刷新球", "大电锤", "回音战刃", "天堂之戟", "骷髅王", "斧王",
            "帕吉", "沙王", "拉比克", "悠米", "提夫林", "塞拉斯", "弗兰克"]
    bad_alias = [f"{k} -> {v}" for k, v in names.items() if any(d in k for d in dota)]
    r.check("英雄/物品别名里混进了别的游戏的词", bad_alias, 0)

    print("\n参考基线 data/deadlock_testset*.jsonl")
    for fname in ("deadlock_testset.jsonl", "deadlock_testset_en.jsonl"):
        path = DATA / fname
        if not path.exists():
            r.check(f"{fname} 存在", [fname], 0)
            continue
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        bad = []
        for i, ln in enumerate(lines, 1):
            try:
                json.loads(ln)
            except Exception as e:  # noqa: BLE001
                bad.append(f"第 {i} 行: {e}")
        r.check(f"{fname} 可解析（{len(lines)} 行）", bad, 0)

    print()
    if r.fails:
        print(f"结论：{len(r.fails)} 项不通过 -> " + "; ".join(r.fails))
        return 1
    if r.warns and args.strict:
        print(f"结论：无 FAIL，但 --strict 下有 {len(r.warns)} 项 WARN -> " + "; ".join(r.warns))
        return 1
    print(f"结论：全部通过" + (f"（{len(r.warns)} 项 WARN，见上）" if r.warns else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

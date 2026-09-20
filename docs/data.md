# 术语与语料数据（data/）怎么维护

`data/` 里的文件分三类，**维护方式完全不同**，混起来就会出问题：

| 类型 | 文件 | 谁生成 | 怎么改 |
|---|---|---|---|
| **自动生成** | `glossary.json`、`phrases.json`、`templates.json` | `scripts/build_glossary.py`（读游戏本地化文件，不联网） | **别手改**，改生成脚本里的清洗规则，然后重新生成 |
| **自动派生** | `gamenames.json` | `scripts/build_gamenames.py`（读 `glossary.json`） | 同上；它只是把 hero/item 那部分挑出来 |
| **手工维护** | `slang.json`、`keep_as_is.json`、`deadlock_zh2en.json`、`zh_term_blocklist.json`、`en_term_blocklist.json`、`phrases_zh.json` | 人 | 直接改，改完重启桥 |

另外几份**运行时没人读**、只作人读对照的参考快照（见
[phrase-corpus.md](phrase-corpus.md)）：`deadlock_callouts.json`、`deadlock_terms_official.json`、
`deadlock_testset.jsonl`（跑分用）、`deadlock_testset_en.jsonl`（跑分用）。

> `deadlock_zh2en.json` 是**里外都算数**的一份：它既是人读的对照表，也是
> `Glossary.zh_terms` 的数据源（中→英方向的人工审校层，允许单字如 `送=feed`）。
> 它曾经有个扁平副本 `glossary_zh.json`（104 条逐条相同、零冲突），
> 2026-09-20 合并掉了 —— 两份并存只会出现"改一份不同步另一份"。
> `templates.json` 目前**没有消费者**（带 `{hero_name}` 占位符的整句在 mod 方案下
> 不会以英文形态出现在聊天行里），数据照旧生成，需要时在 `Glossary._load` 里接回来。

## 重新生成（游戏更新后 / 改了清洗规则后）

```bat
python scripts\build_glossary.py     :: 1. 从游戏本地化文件重抽术语与整句
python scripts\build_gamenames.py     :: 2. 派生英雄/物品名保护表
python scripts\check_data_quality.py  :: 3. 质检：必须"全部通过"才算做完
python -m unittest discover -s tests -t .   :: 4. 术语相关单测
```

`build_glossary.py` 会因为清洗规则挡掉一些条目，并把原因打出来（`[长度] [斜杠片段]
[拼音残留] …`）。**这些日志要看一眼** —— 沉默地丢数据是这类脚本最容易踩的坑。

## 质检脚本查什么（每条都有实测来源）

```bat
python scripts\check_data_quality.py -v
python scripts\check_data_quality.py --strict    :: CI 用：有 WARN 也失败
```

| 检查项 | 症状（都是实际踩过的） |
|---|---|
| 中文译名含排版空格 | 本地化文件里有 `肉  盾`、`高  压  电`、`区 域 封 锁` 共 99 条；作为少样本喂给模型，模型会照抄这种怪空格 |
| 大小写重复键 | `Silencer`/`silencer`、`Max Health`/`max health` 共 62 组，同一术语记了两遍 |
| 模板碎片 | `other} Won`、`%hero_name% 出装`、`&nbsp;killed themself`、`+s DurationApplies % Spirit Resist` |
| 孤立单位 token | 数值占位符被剥掉后剩下的残句（`+s Duration`） |
| 拼音残留 | `"ping wheel": "信号轮盘 xinhao lunpan"` —— 玩家会看到拼音当译文 |
| 分路名对不上 | `Defend_Purple` 的英文写成了 `Defend Green`，会把紫路说成绿路 |
| keep/slang 重叠 | **同一个词两张表都有 → 两条规则同时失效**（词被 stash 成占位符，模型只看到 `⦁0⦁`，既不翻也不解释）。实测 15 个词全中：afk/b/brb/buff/cd/gl/glhf/hf/ks/mia/nerf/oom/ult/ulti/wp |
| 跨游戏别名 | 英雄别名的来源是本地化的 `_search` 字段，里面混进了 Dota 的叫法（不朽尸王→幸免于难、刷新球→刷新环、大电锤→积雷电容），会被名称保护表当真 |

## 两张黑名单（注入提示词前的最后一道闸）

术语表是从官方本地化自动抽的，里面 2000 多条是 UI 字符串，很多键本身就是**日常英语词**：
一命中就注入提示词，把模型带偏。所以两个方向各有一份黑名单：

| 文件 | 管哪个方向 | 实测踩到的例子 |
|---|---|---|
| `en_term_blocklist.json` | 英→中（`terms_for` 注入前） | `care, they're flanking` 注入 `They're=他们`；`their shrine is down` 注入 `Down=下`；`nice fight` 注入 `Fight=进攻`（那是个技能名） |
| `zh_term_blocklist.json` | 中→英（`terms_for` 注入前） | `马上到` / `早上好` / `上路没人` 全部注入 `上=go`；`我送他们回家` 注入 `他们=They're` |

另外两条规则写在 `dlchat/chat/glossary.py` 的 `_is_noise_term` / `_zh_allowed` 里：
含撇号的英文键一律不注入；中→英方向**单字只认人工审校层**（`deadlock_zh2en.json` 里逐条
确认过的「送=feed」），兜底索引里的单字一律拦掉。

## 评测基线

| 文件 | 内容 | 怎么用 |
|---|---|---|
| `deadlock_testset.jsonl` | 30 条中文聊天 + 期望英文术语 | `python scripts\bench_zh2en.py --compare` |
| `deadlock_testset_en.jsonl` | 60 条英文聊天 + 参考中文译文 + 语域标注 | `python scripts\bench_en2zh.py --compare` |
| `bench_en2zh_last.json` | 上一次跑分记录（自动生成，已 gitignore） | 跨改动 diff |

`bench_en2zh.py --dry-run` 会拿**参考译文**过一遍检查器：必须 60/60 全过，
否则说明检查项有误判，别带着误判去跑真模型（这一步是免费的，先跑它）。

跑真模型（要花钱/要本地 Ollama）：

```bat
ollama serve
python scripts\bench_en2zh.py --variant new -v      :: 当前提示词
python scripts\bench_en2zh.py --compare             :: 与"不带术语约束"的基线对比
python scripts\bench_en2zh.py --base-url https://api.deepseek.com/v1 --model deepseek-flash
```

> 术语命中率的判定是**确定性的**（关键词/汉字），不代表"翻得好"。人工评分那部分看
> `--verbose` 打印的 markdown 表：术语 / 意思 / 自然度 / 语域 / 长度五个维度。

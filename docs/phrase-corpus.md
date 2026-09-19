# Deadlock 沟通语料（英↔简中）

给翻译管线用的语料库。**核心原则：优先用游戏自己的数据** —— 聊天轮盘和术语表的官方
简中就是玩家在游戏里看到的词，比任何社区整理都准，而且游戏更新后可以重新生成。

## 语料来源

| 来源 | 内容 | 为什么可信 |
|------|------|-----------|
| **游戏自带本地化**（`game/citadel/resource/localization/`） | 聊天轮盘呼号、核心术语的官方简中 | Valve 官方翻译，松散文本可直接读，随版本更新 |
| **SteamDB 术语表**（2026 版，见文末链接） | 当前版本的核心机制词（注意游戏改过版） | 与游戏 build 23988212 对齐，说明 Urn 已重做为占领圈、Patron 是终局目标等 |
| **社区实际用词** | 中文玩家真的会打的黑话 → 游戏内英文 | 人工整理，英文侧对齐官方术语 |

## 产物

```
data/deadlock_callouts.json         官方聊天轮盘呼号（英↔简中，54 条）
data/deadlock_terms_official.json   官方核心术语（英↔简中，25 条，带 token 出处）
data/deadlock_zh2en.json            中文→英文 术语/短语（81 条）★ 我们最缺的那一侧
data/deadlock_testset.jsonl         30 条真实中文聊天 + 期望术语（改前改后量化对比用）
data/deadlock_corpus.tsv            上面全部的人读版，方便校对
```

生成脚本（读游戏文件，不联网）：

```bat
python scripts\collect_deadlock_phrases.py    :: 原始采集
python scripts\lookup_terms.py --core         :: 查官方译名
python scripts\build_phrase_corpus.py         :: 合并成上面四个文件
```

## 官方术语（重点：这些和玩家自己猜的不一样）

| 英文 | 官方简中 | 玩家常说的 |
|------|---------|-----------|
| souls | 魂魄 | 灵魂 / 钱 |
| last hit / deny | **正补 / 回收** | 补刀 / 反补 |
| guardian / walker | **卫士 / 机甲** | 塔 / 大机器人 |
| shrine / patron | **圣坛 / 守护神** | 神坛 / 老家 |
| urn | **灵瓮** | 魂瓮 |
| mid-boss / rejuvenator | **中区头目 / 复生石** | 大怪 / 复活石 |
| trooper / neutrals | 步兵 / 中立生物 | 小兵 / 野怪 |
| zipline / stamina | 滑索 / 耐力 | 缆车 / 体力 |
| headshot / flex slot | 头弹 / 弹性槽位 | 爆头 / 自由槽 |
| lanes | 黄路 / 蓝路 / 绿路 / 紫路 | 上/中/下路（Deadlock 是四条彩色线） |

官方聊天轮盘里的呼号（节选，全部 54 条见 `deadlock_callouts.json`）：

| 英文 | 官方简中 |
|------|---------|
| Care! | 小心！ |
| Missing! | 敌人消失！ |
| Push! | 推进！ |
| Get Back! | 撤退！ |
| Go! | 上啊！ |
| On my way! | 来了！ |
| Going to Gank | 准备抓人 |
| Cover me! | 掩护我！ |
| I'll flank 'em | 我来包抄他们 |
| Rejuv's Dropping | 复生石掉落了 |
| Need Help on Yellow! | 黄路需要帮助！ |
| Good Job! / Thanks! | 干得漂亮！ / 谢了！ |

## 中文→英文（81 条，最要命的一批）

模型会把「送」按字面翻成 send —— 中文玩家说「送」其实是 **feed**（送人头）。
这类黑话必须显式喂给模型，例子（`data/deadlock_zh2en.json` 全量）：

```
送 → feed          别送了 → stop feeding     一直送 → keep feeding
越塔 → dive        抱团 → group up           开团 → initiate
绕后 → flank       蹲人 → camp them          抓人 → gank
撤退 → get back    别浪 → play safe          稳住 → hold
魂瓮 → urn         复生石 → rejuvenator      大怪 → mid boss
正补 → last hit    反补 → deny               大招 → ult
```

## 怎么用（待接入）

1. **重写 zh→en 少样本**：现在那 4 组中性示例里有一句 `来个人帮忙送魂瓮 → need help with
   urn`（原文的「送」在译文里没有对应词），实测把「送」教成了 send。换成含黑话的示例，
   例如 `别送了 → stop feeding`、`越塔 → dive`、`抱团 → group up`。
2. **生成 zh→en 术语表**：把 `deadlock_zh2en.json` 接进 `Glossary`（现在 3926 条术语
   **全部是英→中方向，中文键 0 条**），让 `送=feed` 这类提示能在句子里命中。
3. **加一条硬规则**：不得添加原文没有的词（实测模型会自己加 "lol"）。
4. **用 `deadlock_testset.jsonl` 量化**：改前改后各跑一次，统计期望术语命中率 + 人工评分。

## 效果（实测，30 条测试集）

```
[legacy（改动前）] 术语命中 10/30 = 33%
[new（改动后）]    术语命中 30/30 = 100%
```

改动前后的具体错例（同一模型、温度 0）：

| 输入 | 改动前 | 改动后 |
|------|--------|--------|
| 别送了 | `skip it` | `stop feeding` |
| 别送了，行吗？你一直送，都已经0-10了。 | `stop sending, lol. we're already 0-10.` | `stop feeding, please? You keep feeding and we're already 0-10.` |
| 越塔杀他 | `flank him` | `dive him` |
| 别开团 | `no teamfight` | `don't initiate` |
| 抱团推进 | `push together` | `group up and push` |

复跑：

```bat
python scripts\bench_zh2en.py --compare
```

## 日常使用

**语料是自动生效的**，不需要你做任何事：

| 环节 | 说明 |
|------|------|
| 词条怎么进模型 | 桥启动时加载 `data/glossary_zh.json`（中文→英文）；翻译时命中的词条作为 `TERMS:` 行注入提示词 |
| 改完语料要做什么 | **重启桥**（提示词和词表都在进程内存里；重启同时清掉旧译文缓存） |
| mod 要不要重装 | **不用**。语料/提示词全在桥这一侧，游戏内 mod 无需重新导入 |
| 游戏更新后 | 重跑 `collect_deadlock_phrases.py` + `build_phrase_corpus.py`，检查官方译名有没有变，再重启桥 |

游戏内日常操作：

1. **收到英文** → 自动显示中文（悬停看原文；`译文显示` 可切成双语）
2. **要说中文** → 打中文 → **连按两下空格**（默认触发键）→ 输入框变中英对照 → 回车发出（`我发出去的消息` 默认「中英都发」）
3. **改设置** → 聊天框那行点「设置」或输入 `/tongyi`（旧命令 `/dlchat` 也可用）；改完按「保存并生效」（写入 `settings.json`，重启依然有效）
4. **看状态** → 输入框左侧小圆点：绿=正常、黄=最近有失败、红=桥不通

链接：
[SteamDB Deadlock 术语表](https://steamdb.com/en/deadlock/mechanics/glossary)、
[5EPlay《DeadLock》队伍交流常用英语短语](http://csgo.5eplay.com/article/2410227c9f38)

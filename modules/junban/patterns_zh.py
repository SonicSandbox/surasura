# SPDX-License-Identifier: GPL-3.0-or-later
"""パターン in Chinese — tokens and the words the rules know (Patterns_Chinese_Spec.md §6–§8).

The Japanese builder (`patterns_build.py`) counts Japanese; this is its Chinese counterpart, pure except
jieba, writing the same four tables with the same row shapes — so the store, the lookup's shares and
spread, the formatter and the packages serve both languages unchanged.

The key-space contract
----------------------
A word is keyed **(its Simplified form, "")** — exactly what `analyzer.ChineseTokenizer(script="s")`
gives, or every lookup silently misses (Z-F12). So the text goes through `zh_script.to_simplified`
(length-preserving) and is cut by **`analyzer.chinese_cut`, the analyzer's own cut**, and a word is what
`analyzer.chinese_word` says is one — never `jieba.posseg.cut`,
which segments differently on one line in five (跳过 → 跳 / 过, 这批 → 这 / 批: Z-F2). posseg is used
only for its TAG DICTIONARY (`word_tag_tab`): a tag is a lookup, one per word type, whatever the
context (Z-F3) — so the rules decide function words from closed lists, and tags only tell a noun from a
verb. A token outside the dictionary (很难, 这张) is split by posseg's own cut of that one token for
COUNTING only; it stays one word, keyed as the analyzer keys it.
"""

import re
import sys
from collections import Counter, namedtuple

from app.unicode_ranges import HAN, KANA_LETTERS

# The Chinese builder's own version, recorded in each database's meta (Japanese has its own).
# 2: the documents each pattern was seen in (`files`); line 1's kind in `section` (Q a measure word, P a
#    coverb); 〜会 / 〜动 / 〜光 nouns are no verb forms; an adverb's verb (DV); a 在…下 frame is no coverb
#    slot; FORM_SHARE its own (Patterns_Quality_Spec.md §10).
# 3: the cut is analyzer.chinese_cut — jieba's dictionary only (a guessed name kept when a surname leads it),
#    CC-CEDICT's words (a phrase entry with grammar in it is its words: 吃 / 了 / 饭), a doubled form at its word
#    (开开心心 is 开心); a number is no word (ZTok.key); 著 words read as CC-CEDICT pairs them (著急 is 着急); …… and
#    ；no longer end a sentence.
BUILDER_VERSION = 3

# One token of a sentence. `text` is its Simplified form, `orig` the same stretch of the text as written
# (conversion is length-preserving — the alias table's spelling), `tag` the dictionary's tag or None, `word`
# whether it is a Chinese token (CJK and no kana — what the rules read: a number between a verb and its
# measure word is one), `key` the word the analyzer counts it as (analyzer.chinese_word: "" for a number,
# which the list never counts; analyzer.chinese_base: 开心 for 开开心心).
ZTok = namedtuple("ZTok", "text orig tag word key", defaults=("",))

# The ChineseTokenizer's own ranges (app/unicode_ranges.py): 〇 and Extension A / B are words there too, and
# kana means a kana LETTER — a card 约翰・列侬 is a Chinese name (a phrase), never 'another language' for its ・.
_CJK = re.compile(f"[{HAN}]")                  # a Chinese character: the token is Chinese
_KANA = re.compile(f"[{KANA_LETTERS}]")        # a kana letter: a card holding one is Japanese (resolve_key)
_CONTENT = re.compile(f"[{HAN}0-9A-Za-z０-９Ａ-Ｚａ-ｚ]")   # a token with none of these is a barrier

# --- the closed lists (§6) --------------------------------------------------------------------- #
# Measure words for things. The tag dictionary files only 29 of 72 common ones as `q` (件 块 `zg`, 本 `r`,
# 条 张 双 `n` … Z-F4), so the list, not the tag, decides. Checked against CC-CEDICT's 136 (WP-Z4): its
# 点 起 出 方 打 stay out — 一点 (a little), 一起 (together), 出门, 一方面 would be measure words everywhere.
CLASSIFIERS = frozenset(
    "个 本 位 件 条 张 只 杯 种 类 家 辆 台 部 场 口 头 匹 支 枝 块 片 双 对 套 层 封 首 句 份 间 座 所 把 篇 棵 朵 颗 "
    "粒 根 盏 架 艘 碗 瓶 盒 包 袋 名 群 批 堆 排 段 节 章 幅 面 扇 道 顶 餐 顿 项 门 届 串 束 副 款 列 班 栋 幢 株 枚 "
    "滴 笔 处 股 桩 盘 罐 床 尊 通 册 席 期 宗 轮 管 壶 户 桶 缸 则 丝 柄 身 杆 缕 组 撮 堂 页 具 集 记 盆 簇 队 行 "
    "局 幕 声 档".split())
# Measure words for how often something is done: 打了三次电话 is not a measure word of 电话.
VERBAL_CLASSIFIERS = frozenset("次 遍 趟 回 下 番 阵".split())
# What may stand before a measure word: a numeral or a demonstrative — never a pronoun (我把书 is the
# preposition 把, Z-F9). Digits count; so do 半 and 多 (半碗, 多个).
_NUMDEM = re.compile(r"^(?:[0-9０-９一二两三四五六七八九十百千万亿几半多每这那哪某各该]|这些|那些|哪些)+")
# The coverbs that introduce a predicate's argument (跟她结婚, 对我很重要). 和 与 同 跟 also mean "and" (D3).
# 关于 is not one: it opens a topic (关于他的作品你知道哪些 — KdConv asks this 106 times), never the
# predicate's argument (the gate, WP-Z6).
COVERBS = frozenset("跟 和 同 与 对 给 向 为 替 从 在 把 被 让 叫 比 往 朝 离 用 对于".split())
AND_COVERBS = frozenset("跟 和 同 与".split())
# 都 / 也 / 一样 / 一起 after the noun phrase make 和-type words "and" (他跟你一样…, 我和她一起…).
AND_MARKERS = frozenset("都 也 一样 一起".split())
# Aspect: 了 过 着 — and 著, which to_simplified leaves as it is (著 is Simplified too, 著名): after a
# verb it is the aspect marker 着 (Z-F6).
ASPECT = {"了": "了", "过": "过", "着": "着", "著": "着"}
# Result and direction complements (看完, 放下, 走进来, 放在, 送给); the two-character ones first, so
# 看清楚 is 看 + 清楚.
COMPLEMENTS = tuple(sorted(set(
    "完 到 见 懂 好 错 住 掉 走 成 会 满 够 透 遍 光 动 在 给 清楚 明白 干净 来 去 上 下 进 出 回 过 起 开 "
    "上来 上去 下来 下去 进来 进去 出来 出去 回来 回去 过来 过去 起来 开来".split()), key=lambda c: (-len(c), c)))
_COMPLEMENT_SET = frozenset(COMPLEMENTS)
# Degree words before an adjective (很重要, 太贵); longest first. 越来越 is a frame (越来越〜), not a form.
DEGREE = tuple(sorted(set("很 太 最 更 挺 真 非常 特别 比较 十分 相当 有点 有点儿 极其 格外 更加".split()),
                      key=lambda d: (-len(d), d)))
_DEGREE_SET = frozenset(DEGREE)
# Where a thing is: 在〜上, 〜里.
LOCALIZERS = frozenset("上 里 中 下 外 内 旁边 里面 上面 下面 外面 之间".split())
# Suffixes that make a frame of their own: 〜们, 〜性.
NOUN_SUFFIXES = frozenset("们 性 化 者 家 员".split())
# Words the dictionary keeps whole that LOOK like a word plus a complement or a degree word, but mean
# something of their own: 打开 is "open", not 打 + 开; 难过 "sad"; 很快 "soon"; 过去 "the past". Never a
# form (§6.2) — grown at the gate. The balanced build added the words that start with a degree word
# (WP-Z6): 最近 "recently", 更新 "update", 更换 "replace", 真相 "the truth", 太守 a title, 更加 itself one;
# and nouns that start with a measure word, never one plus a noun: 这 + 餐馆 is not 餐〜 for 馆, nor 一 +
# 列车 列〜 for 车 — or 家人 家〜 for 人, 一把手 (the boss) 把〜 for 手.
LEXICALISED = frozenset("打开 看起来 看上去 难过 最好 很快 好的 下一班 上下班 过去 看来 说来 想来 "
                        "最近 更加 更新 更换 更改 更动 更正 真相 真主 真谛 真切 真诚 真爱 真系 太守 太古 太监 太保 太白 "
                        "挺进 餐馆 列车 台风 台海 名单 支行 把手 一把手 家人 一家人".split())
# A word the dictionary files as a noun that ends in one of these is that noun, never a verb and its
# complement: 演唱会 (a concert), 研讨会, 聚会, 教会 (a church), 误会; 活动 (90% of 活's uses in the
# balanced build), 启动; 闪光 (a flash), 争光, 测光 (Patterns_Quality_Spec.md §10 E5). Only these endings:
# jieba files real forms as nouns too — 睁开, 染上, 伪装成, 托付给, 写信给, 折射出, 咽下 — and they stay. 光
# was measured before it joined: every noun ending in it that reached a card was wrong (闪光 32% of 闪),
# and the real ones jieba files as nouns (杀光, 卖光, 烧光) stay under 2% of their verb. The cost, accepted
# (U12): 学会 is filed as a noun ("a society"), so 学 loses the form 学会. 开会 and 转会 are verbs, and a
# modal on its own (可能 会) is `_verb_forms`': both stay.
NOUN_ENDINGS = frozenset("会 动 光".split())
# Demonstratives that make a frame before a noun (这个〜, 这种〜).
DEMONSTRATIVES = frozenset("这 那 这个 那个 这些 那些 这种 那种 每 每个 某 某个 哪 哪个 各 各种".split())

# --- classes from the tag dictionary (§6) ------------------------------------------------------ #
NOUN_TAGS = frozenset("n ng nz nt ns nl vn an".split())
VERB_TAGS = frozenset("v vd vi vq vn".split())
# `b` (区别词) too: the dictionary files 高兴 there, and a real 区别词 never follows 很 anyway.
ADJ_TAGS = frozenset("a ad an b".split())
NAME_TAGS = frozenset("nr nrfg nrt".split())
# Common words the context-free dictionary files under another class (Z-F4; the gate, WP-Z4/Z6):
# 一样 as a pronoun, 安静 as a name, 生气 and 见面 as nouns. From the balanced build (WP-Z6): verbs every
# learner has filed as nouns or bound forms (学 问 记 飞 `n`, 喝 `vg`, 穿 选 `zg`, 换 `nz`) — so 喝咖啡 and
# 穿衣服 were never pairs; tastes and 热 / 晚 as nouns, places or times (酸 辣 热 `n`, 咸 香 `ns`, 晚 `tg`);
# 成 and 指 as nouns, the "objects" of 1,516 and 1,629 verbs (发展成, 报道指); and 时 — "when", after a
# clause (采访时, 年轻时: 8,688 pairings, not one a noun's) — is `tg`, a time morpheme no rule counts.
# 同意 is filed as an adverb, 家 only as a measure word, 顾客 as a name, and nouns as verbs: 想法 看法 说法
# 做法 选手 对手 考生 处长 杀手 (这种说法: 94 of 440 uses right after a measure word). And the verbs of
# everyday life it files as nouns — mostly a verb and its object in one word: 回家 got 个〜 47% (a
# measure word!) and 聊天 no 跟〜. Tags only — the key stays jieba's word.
TAG_FIXES = {"一样": "a", "安静": "a", "高兴": "a", "生气": "v", "见面": "v",
             "学": "v", "问": "v", "记": "v", "飞": "v", "喝": "v", "穿": "v", "选": "v", "换": "v", "同意": "v",
             "酸": "a", "辣": "a", "热": "a", "咸": "a", "香": "a", "晚": "a", "成": "v", "指": "v", "时": "tg",
             "家": "n", "顾客": "n", "想法": "n", "看法": "n", "说法": "n", "做法": "n", "选手": "n", "对手": "n",
             "考生": "n", "处长": "n", "杀手": "n", "伤心": "a", "约会": "vn", "录音": "vn",
             **dict.fromkeys("回家 关心 唱歌 跑步 散步 聊天 购物 生病 毕业 住院 排队 花钱 照相 上学 放学 刮风 点菜 "
                             "买单 结账 失业 上车 关门 关灯 写字 读书 做作业 洗衣服".split(), "v")}

_TAGS = {}


def tag_table():
    """posseg's tag dictionary (349,045 words), loaded once; posseg is never asked to segment."""
    if not _TAGS:
        import jieba
        import jieba.posseg as posseg
        jieba.setLogLevel(60)
        _TAGS["tab"] = dict(posseg.dt.word_tag_tab, **TAG_FIXES)       # a copy: jieba's own table untouched
        _TAGS["cut"] = posseg.dt.cut
    return _TAGS["tab"]


# --- tokens -------------------------------------------------------------------------------------- #
def iter_tokens(text, boundaries):
    """Yield one list of `ZTok` per sentence, punctuation kept in place as barriers — segmented exactly
    as `ChineseTokenizer(script="s")` segments (the contract above): line by line, through Simplified,
    by `analyzer.chinese_cut`, and split at any token holding a character of the zh boundary set
    (character-wise, as the analyzer does: a terminator can arrive glued to a symbol)."""
    from app import zh_script
    from app.analyzer import chinese_base, chinese_cut, chinese_word, tagger_text
    tags = tag_table()
    intern = sys.intern
    for line in text.split("\n"):
        line = tagger_text(line)[0]         # read as the analyzer reads it: ⽅法 is 方法 (its `word`)
        simp = zh_script.to_simplified(line)
        sentence, pos = [], 0
        for w in chinese_cut(simp):
            orig = line[pos:pos + len(w)]
            pos += len(w)
            if _CONTENT.search(w):
                key = (chinese_base(w) or w) if len(w) > 2 else w
                sentence.append(ZTok(intern(w), intern(orig), tags.get(w), bool(_CJK.search(w)) and not _KANA.search(w),
                                     intern(key) if chinese_word(key) else ""))
            else:
                sentence.append(ZTok(w, orig, None, False))          # a barrier: punctuation, space
            if not boundaries.isdisjoint(w):
                yield sentence
                sentence = []
        if sentence:
            yield sentence


def is_barrier(tok):
    return tok is None or not _CONTENT.search(tok.text)


def parts(tok):
    """-> [(text, tag)] — the token as the rules read it. A dictionary word is itself; a token outside
    the dictionary (很难, 这张, 看著 — the analyzer's own fusions) is split by posseg's cut of that one
    token (很 + 难, 这 + 张), for counting only: the token stays one word, keyed whole."""
    if tok.tag is not None or not tok.word:
        return [(tok.text, tok.tag)]
    tag_table()
    return [(p.word, p.flag) for p in _TAGS["cut"](tok.text)]


def split_classifier(text):
    """A fused numeral/demonstrative + measure word (+ noun) -> (prefix, classifier, rest), else None:
    一碗 -> (一, 碗, ""), 这家 -> (这, 家, ""), 两辆车 -> (两, 辆, 车). Z-F5: 83% of measure words arrive
    fused like this, so a rule on separate tokens alone would miss nearly all of them."""
    m = _NUMDEM.match(text)
    if not m or m.end() == len(text):
        return None
    rest = text[m.end():]
    for size in (2, 1):
        if rest[:size] in CLASSIFIERS:
            return text[:m.end()], rest[:size], rest[size:]
    return None


def aspect(text):
    """The aspect marker `text` is (了 过 着; 著 read as 着), or None."""
    return ASPECT.get(text)


# --- counting (pure given jieba's dictionary) ---------------------------------------------------- #
NOUN, VERB, ADJ, NAME = "noun", "verb", "adj", "name"
# Inside the stretch between a coverb and its predicate: the noun phrase (他, 这本书, 我的朋友) …
_NP_TAGS = frozenset("r n nr nrfg nrt ns nt nz ng m q mq uj a b f t s vn an j l".split())
# … and, right before the predicate, adverbs (很 is `zg`, like 5,666 other single characters: Z-F4).
_ADVERB_TAGS = frozenset("d ad df zg".split())
# The line each rule feeds. Candidates are counted and stored, never shown until the gate says so: it
# kept subject–predicate (压力很大) and adjective 地 verb (认真地学习) as pairs (WP-Z6); the coverb's noun
# (在中央政治局第二十一次集体〜) and 对〜来说 (16 rows in 17.8M words) stay candidates. `DV` is an adverb and
# the verb after it (马上去, 突然失控 — Patterns_Quality_Spec.md §10 E6).
_KIND = {"VO": "colloc", "AN": "colloc", "SP": "colloc", "AD": "colloc", "DV": "colloc",
         "F1": "frame", "F2": "frame", "F3": "frame", "F4": "frame", "PO": "cand", "F5": "cand"}
# The adverbs of `DV`: jieba's `d` (马上 已经 一直 终于) and `ad`, an adjective it files as one (突然 认真).
_DV_TAGS = frozenset("d ad".split())
# 离合词 (Z-W5): what may stand between the two characters of a separable verb, and nothing looser — an
# aspect marker (结了婚, 见过面), 个 or a numeral and measure word (洗个澡, 吃了一顿饭; 睡了一觉 after an aspect
# marker), a person and 的 or a measure word (生他的气, 帮我一个忙). Measured on Tatoeba (WP-Z4): with any
# numeral, pronoun or "X的" allowed, 190 of 213 splits were chance pairs — 看一下, 听我说, 认识的人, 有足够的钱.
_PERSON = r"(?:[我你他她它]们?|自己|大家|人家)"
_INSERTION = re.compile(r"[了过着][一两几]?|(?:[了过着])?(?:个|[一两几这那][个次顿场回下]|" + _PERSON
                        + r"(?:的|[一两几这那]?[个次顿场回下]))")
_SPLIT_MAX = 6
_VERBS2 = {}


def classes(tag):
    """The classes a dictionary tag makes a word (§6): a `vn` word (影响) is a noun AND a verb, an `an`
    word a noun and an adjective; a name (nr …) is only a name."""
    if tag in NAME_TAGS:
        return {NAME}
    out = set()
    if tag in NOUN_TAGS:
        out.add(NOUN)
    if tag in VERB_TAGS:
        out.add(VERB)
    if tag in ADJ_TAGS:
        out.add(ADJ)
    return out


def _at(toks, j):
    return toks[j] if 0 <= j < len(toks) else None


def _numdem(text):
    return bool(text) and _NUMDEM.fullmatch(text) is not None


def _id(counts, text):
    """The id of word `text` — the (Simplified word, "") key — in `counts` (patterns_build.Counts)."""
    key = (text, "")
    i = counts.ids.get(key)
    if i is None:
        i = counts.ids[key] = len(counts.keys)
        counts.keys.append(key)
    return i


def _tally(counts, text, orig, tag):
    x = _id(counts, text)
    counts.word[x] += 1
    counts.orth[(x, orig)] += 1
    counts.pos[(x, tag or "")] += 1
    return x


def _pair(counts, x, key):
    counts.pattern[(x, key)] += 1
    counts.doc.add((x, key))        # the documents it was seen in (patterns_build.Counts, §8.1 h)


# A sentence particle the dictionary glued to a noun: 看电影吧 is cut 看 / 电影吧 — 电影吧 a dictionary word.
_PARTICLES = "吧吗呢啊呀"


def _noun_of(counts, tok):
    """-> (id, text) of the noun a token is as a collocate: 电影吧 is 电影 + 吧 wherever the dictionary rates
    电影 the commoner word (4,918 to 3) — a use of 电影 then, like any word inside a fused token — while
    酒吧, two characters, stays whole."""
    import jieba
    text = tok.text
    if len(text) >= 3 and text[-1] in _PARTICLES and jieba.dt.FREQ.get(text[:-1], 0) > jieba.dt.FREQ.get(text, 0):
        return _head(counts, tok, 0, text[:-1]), text[:-1]
    return _id(counts, text), text


def _compound(first, second):
    """Two characters, then one: 推荐 + 菜, 制作 + 人, 健康 + 码 — the shape of a Chinese compound noun, and
    never of a verb and its object or an adjective and its noun (购买书 and 美丽花 are not said; 买书,
    美丽的花 are: the [2+1] rule of Chinese word structure). In the balanced build (WP-Z6) 2,835
    verb–object and 398 adjective–noun pairings had it — compounds (推荐菜, 制作人, 统计书, 年轻时) and
    names (便宜坊) nearly all."""
    return len(first) >= 2 and len(second) == 1


def _two_then_one(text):
    """Does jieba's own dictionary read a three-character word as two characters and one — 放大 + 器 (an
    amplifier), 打火 + 机 (a lighter) — rather than one and two (放 + 大器, 打 + 火机)? Compared as jieba
    compares two routes, by the product of the words' dictionary frequencies: 打电话 stays 打 + 电话 and
    做作业 做 + 作业 (WP-Z6)."""
    import jieba
    freq = jieba.dt.FREQ
    return (freq.get(text[:2]) or 1) * (freq.get(text[2:]) or 1) > (freq.get(text[:1]) or 1) * (freq.get(text[1:]) or 1)


def _nounlike(tok):
    """A noun by the dictionary, or a single character it files as `zg` (车, 件 — 5,666 characters of every
    class, Z-F4) — which only a measure word before it can call a noun."""
    return NOUN in classes(tok.tag) or tok.tag == "zg"


def _head(counts, tok, start, text):
    """A use of the word `text` found inside the fused token `tok` at `start` (看 in 看完, 书 in 本书): it
    is a use of that word too, so its count includes it and no form's share passes 100% (§6.2)."""
    return _tally(counts, text, tok.orig[start:start + len(text)], tag_table().get(text))


def count(sentences, counts):
    """Accumulate §6's patterns from `sentences` (lists of `ZTok`) into `counts`, a
    `patterns_build.Counts` — the same counters as Japanese, keyed (Simplified word, ""), so the
    Japanese merge and store serve Chinese unchanged."""
    for toks in sentences:
        for i, t in enumerate(toks):
            if not t.key:
                continue                        # punctuation, a number: never a word of the list
            counts.tokens += 1
            x = _tally(counts, t.key, t.orig, t.tag)
            cls = classes(t.tag)
            if _nounlike(t):
                _measure_word(counts, x, toks, i)
            if NOUN in cls:
                _noun_frames(counts, x, toks, i)
                _subject(counts, x, toks, i)
            if VERB in cls or ADJ in cls:
                _degree(counts, x, toks, i)
                _coverb(counts, x, toks, i)
            if VERB in cls:
                _verb_forms(counts, x, toks, i)
                _object(counts, x, toks, i)
            if ADJ in cls:
                _adjective(counts, x, toks, i)
            if t.tag in _DV_TAGS:
                _adverb(counts, x, toks, i)
            _fused(counts, toks, i)
        _separable(counts, toks)
    return counts


_PERSONS = frozenset("我 你 他 她 它 我们 你们 他们 她们 它们 咱们 大家 自己 您".split())
# What may stand between a measure word and its noun: 一个[有趣的]故事, 这件[糟糕的]事, 一个[我喜欢的]人.
_MODIFIER_TAGS = frozenset("a ad an b d zg v vd vi r".split())


def _classifier_at(toks, j):
    """The measure word the token at `j` is or ends with, else None: separate after a numeral or a
    demonstrative (一 碗), fused with one (一碗, 这家), or a bare 个 — speech drops the 一 after a verb:
    是 个 好人, 找 了 个 工作, and 买个 手机 / 吃个 饭, where jieba glues 个 to the verb."""
    t, p = _at(toks, j), _at(toks, j - 1)
    if t is None or not t.word:
        return None
    if t.text in CLASSIFIERS and p is not None and _numdem(p.text):
        return t.text
    if t.text == "个" and p is not None and p.word and (VERB in classes(p.tag) or p.text in ("了", "过")):
        return t.text
    if len(t.text) == 2 and t.text[1] == "个" and VERB in classes(tag_table().get(t.text[0])):
        return "个"
    split = split_classifier(t.text)
    return split[1] if split and not split[2] else None


def _measure_word(counts, x, toks, i):
    """Z-Q: the measure word of the noun at `i` — right before it (一 碗 面, 这家 店) or before a short
    modifier (一个有趣的故事, 一件新衣服: up to four words that are not nouns and 的, or one adjective —
    past a noun it is that noun's: 一个人的故事). A noun compound is counted at its head, its last noun:
    一名网球选手 counts 选手, never 网球 (the balanced build, WP-Z6). The fused shapes inside a token are
    `_fused`'s."""
    n1 = _at(toks, i + 1)
    if n1 is not None and n1.word and NOUN in classes(n1.tag):
        return                                                       # 网球 in 一名网球选手
    cl = _classifier_at(toks, i - 1)
    p1 = _at(toks, i - 1)
    if cl is None and p1 is not None and p1.word and (p1.tag in ("a", "b") or NOUN in classes(p1.tag)):
        cl = _classifier_at(toks, i - 2)                             # 一件新衣服, 一名网球选手
    if cl is None and p1 is not None and p1.text == "的":
        for k in range(i - 2, max(-1, i - 7), -1):
            found = _classifier_at(toks, k)
            if found:
                cl = found if k < i - 2 else None                    # at least one word before 的
                break
            if not (toks[k].word and toks[k].tag in _MODIFIER_TAGS):
                break
    if cl:
        _pair(counts, x, ("Q", None, cl))


def _coverb(counts, x, toks, i):
    """Z-P: the coverb that introduces an argument of the predicate at `i` — the nearest one to the left,
    past a noun phrase of up to six tokens and the adverbs before the predicate (跟她结婚, 对我很重要,
    把书放在桌子上). 在 right before a verb is the progressive (他在睡觉): no noun phrase, not counted. 和
    / 跟 / 与 / 同 mean "and" when 都 / 也 / 一样 / 一起 follow the noun phrase (D3). A 在 that a localizer
    after the word closes is a frame, not a coverb (在老师的帮助下: `_framed`)."""
    j = i - 1
    while j >= 0 and toks[j].word and toks[j].text not in COVERBS \
            and (toks[j].tag in _ADVERB_TAGS or toks[j].text in _DEGREE_SET):
        j -= 1
    fused = _fused_coverb(_at(toks, j))
    if fused:                                  # 在家吃饭: the dictionary keeps 在家 whole (`r`)
        if fused[0] == "在" and _framed(toks, i):
            return                              # 在家学习中: the frame 在〜中
        _pair(counts, x, ("P", None, fused[0]))
        _pair(counts, x, ("PO", _id(counts, fused[1]), toks[j].text + "〜"))
        return
    k = j
    while k >= 0 and toks[k].word and toks[k].text not in COVERBS and toks[k].tag in _NP_TAGS and j - k < 6:
        k -= 1
    if k < 0 or k == j or toks[k].text not in COVERBS:
        return
    if toks[k].text in AND_COVERBS and any(toks[m].text in AND_MARKERS for m in range(k + 1, i)):
        return
    # 和 between two nouns, or ending a list, joins them: 经济和社会发展, 经济、商业和文化 — "and" (the
    # balanced build, WP-Z6: most of 发展's and 重要's 和〜). After a pronoun (我和你结婚) it stays a coverb.
    before = _at(toks, k - 1)
    if toks[k].text in AND_COVERBS and before is not None \
            and (before.text == "、" or (before.word and NOUN in classes(before.tag))):
        return
    if toks[j].text == "的" and classes(toks[i].tag) == {ADJ}:
        return                                  # 台湾和捷克关系进展的重要里程碑: 重要 describes a noun
    if toks[k].text == "在" and all(toks[m].text in _PERSONS for m in range(k + 1, j + 1)):
        return                                  # 在我睡觉的时候: a time clause and its subject, no place
    if toks[k].text == "在" and _framed(toks, i):
        return                                  # 在老师的帮助下, 在经济发展中: the frame 在〜下 / 在〜中
    _pair(counts, x, ("P", None, toks[k].text))
    noun = toks[j]
    if NOUN in classes(noun.tag):                                  # the candidate 在家〜, 跟朋友〜
        _pair(counts, x, ("PO", _id(counts, noun.text), "".join(t.text for t in toks[k:j + 1]) + "〜"))


def _framed(toks, i):
    """Does a localizer right after the predicate at `i` close the 在 before it — 在老师的帮助下, 在他的影响下,
    在经济发展中? That 在 is the frame 在〜下 / 在〜中 around the word, never its coverb (Patterns_Quality_Spec.md
    §10 E4, rule 1). But 上 or 下 after a one-character verb is its direction complement — jieba cuts
    在墙上挂上 and 在床上躺下 as 挂 / 上, 躺 / 下 — and there 在 stays the coverb: 181 of the 5,674 slots the
    balanced build counted before a localizer (写上, 贴上, 挂上, 住下, 生下)."""
    loc = _at(toks, i + 1)
    return loc is not None and loc.word and loc.text in LOCALIZERS \
        and not (len(toks[i].text) == 1 and loc.text in ("上", "下"))


def _fused_coverb(tok):
    """-> (coverb, noun) for a token that is a coverb and its noun or pronoun in one — 在家 (`r`), 对我
    (outside the dictionary) — else None. A dictionary noun or verb that merely starts like one (对象,
    用户, 比较) is tagged as what it is, and never qualifies."""
    if tok is None or not tok.word or len(tok.text) < 2 or tok.tag not in ("r", None):
        return None
    head, rest = tok.text[0], tok.text[1:]
    tag = tag_table().get(rest)
    # 家 is filed `q` (a measure word) and 校 `zg`: one character after a coverb is taken for its noun.
    if head in COVERBS and (tag == "r" or NOUN in classes(tag) or (len(rest) == 1 and tag in ("q", "zg"))):
        return head, rest
    return None


def _verb_forms(counts, x, toks, i):
    """Z-W1–W3 on separate tokens: aspect (买了, 笑著 = 笑着), complement (放下), potential (看不懂)."""
    n1, n2 = _at(toks, i + 1), _at(toks, i + 2)
    if n1 is None or not n1.word:
        return
    marker = aspect(n1.text)
    if marker:
        _pair(counts, x, ("W", None, "{w}" + marker))
    elif n1.text in _COMPLEMENT_SET and toks[i].text + n1.text not in LEXICALISED:
        _pair(counts, x, ("W", None, "{w}" + n1.text))
    elif n1.text in ("得", "不") and n2 is not None and n2.text in _COMPLEMENT_SET and n2.text != toks[i].text:
        _pair(counts, x, ("W", None, "{w}" + n1.text + n2.text))       # not 去不去, the A-not-A question


def _object(counts, x, toks, i):
    """Z-C1: verb + its object noun, an aspect marker allowed between (打电话, 打了电话, 穿着衣服) — for
    both words. An object that is a noun compound is its head, the last noun, as for a measure word:
    维护国家安全 pairs 维护 with 安全, 解决实际问题 解决 with 问题 (WP-Z6) — a head of two characters or
    more: a one-character one ends a compound jieba split (核准 / 书) or a frame (告全国民众书)."""
    j = i + 1
    if _at(toks, j) is not None and aspect(toks[j].text):
        j += 1
    obj = _at(toks, j)
    if obj is not None and obj.word and NOUN in classes(obj.tag) and not aspect(obj.text) \
            and not (j == i + 1 and _compound(toks[i].text, obj.text)):   # 看著: 著 is `n`; 推荐菜
        while j < i + 4 and _at(toks, j + 1) is not None and toks[j + 1].word \
                and NOUN in classes(toks[j + 1].tag) and len(toks[j + 1].text) >= 2:
            j += 1
        obj = toks[j]
        y, noun = _noun_of(counts, obj)
        _pair(counts, x, ("VO", y, "{w}" + noun))
        _pair(counts, y, ("VO", x, toks[i].text + "{w}"))


def _degree(counts, x, toks, i):
    """Z-W4's degree word before (很重要, 太贵) and Z-F4's 越来越〜 — for a verb too: a verb of feeling or
    state takes them (很喜欢, 很想, 越来越喜欢 — WP-Z6), an action verb never does, and the form's share
    floor keeps the chance ones out."""
    word, p1 = toks[i].text, _at(toks, i - 1)
    if p1 is not None and p1.text in _DEGREE_SET and p1.text + word not in LEXICALISED:
        _pair(counts, x, ("W", None, p1.text + "{w}"))
    if p1 is not None and p1.text == "越来越":
        _pair(counts, x, ("F4", _id(counts, p1.text), "越来越〜"))


def _adjective(counts, x, toks, i):
    """Z-W4's 的 after, Z-C2 (adjective (+的) + noun, for both), Z-C4 (adjective 地 verb, a candidate)
    and Z-F4's 〜得很, 〜极了, 〜死了 (the degree word before is `_degree`'s)."""
    word = toks[i].text
    n1, n2 = _at(toks, i + 1), _at(toks, i + 2)
    if n1 is None:
        return
    if n1.text == "的":
        _pair(counts, x, ("W", None, "{w}的"))
    if n1.text == "得" and n2 is not None and n2.text == "很":
        _pair(counts, x, ("F4", _id(counts, "很"), "〜得很"))
    if n1.text == "极了" or (n1.text == "极" and n2 is not None and n2.text == "了"):
        _pair(counts, x, ("F4", _id(counts, "极"), "〜极了"))
    if n1.text == "死" and n2 is not None and n2.text == "了":
        _pair(counts, x, ("F4", _id(counts, "死"), "〜死了"))
    if n1.text == "地" and n2 is not None and n2.word and VERB in classes(n2.tag):
        y = _id(counts, n2.text)
        _pair(counts, x, ("AD", y, "{w}地" + n2.text))
        _pair(counts, y, ("AD", x, word + "地{w}"))
    j = i + 2 if n1.text == "的" else i + 1
    noun = _at(toks, j)
    # 突然失控 is an adverb and a verb (失控 is `vn`, a noun and a verb): the adverb's pair is `_adverb`'s,
    # never also this one — but the verb keeps its side, 努力工作 on 工作 (41 cards would lose a real
    # pairing: the Chinese judge, 2026-09-25).
    adverb = j == i + 1 and toks[i].tag in _DV_TAGS and noun is not None and VERB in classes(noun.tag)
    if noun is not None and noun.word and NOUN in classes(noun.tag) \
            and (n1.text == "的" or not _compound(word, noun.text)):       # 年轻时, 健康码
        (y, text), mid = _noun_of(counts, noun), "的" if n1.text == "的" else ""
        if not adverb:
            _pair(counts, x, ("AN", y, "{w}" + mid + text))
        _pair(counts, y, ("AN", x, word + mid + "{w}"))


def _adverb(counts, x, toks, i):
    """Z-C6 (`DV`, Patterns_Quality_Spec.md §10 E6): an adverb and the verb right after it — the adverb's
    pairing: 马上去, 已经走, 终于来, 突然失控. jieba files 马上 已经 一直 终于 as `d`, which no other rule
    counts, and 突然 认真 as `ad`, an adjective class — so 突然失控 was an adjective and its noun (`AN`) by
    accident; `_adjective` now leaves it here, and it counts once. The verb gets no pairing back: every
    verb's line would fill with 不〜, 也〜, 都〜, 就〜."""
    verb = _at(toks, i + 1)
    if verb is not None and verb.word and VERB in classes(verb.tag):
        _pair(counts, x, ("DV", _id(counts, verb.text), "{w}" + verb.text))


# What may follow an adjective that ends its clause as the predicate: 天气冷了, 身体好吗, 压力大得很.
_CLAUSE_END = frozenset("了 吗 呢 吧 啊 呀 啦 嘛 得".split())


def _subject(counts, x, toks, i):
    """Z-C3: noun + (degree word) + adjective ending its clause, the noun not after 的 — 压力很大, 身体好
    吗. Not an adjective before 的 or a noun (中国最大的公司, 日本大地震: it describes the next noun) or a
    verb (水平显著提高: an adverb), and not a `b` (中心主任, 国务院副: never a predicate) or an `an` (国家
    安全: one noun) — at the gate (WP-Z6) these were most of the 13,187 pairings."""
    p1 = _at(toks, i - 1)
    if p1 is not None and p1.text == "的":
        return
    j = i + 1
    if _at(toks, j) is not None and toks[j].text in _DEGREE_SET:
        j += 1
    adj, after = _at(toks, j), _at(toks, j + 1)
    if adj is not None and adj.word and adj.tag in ("a", "ad") \
            and (after is None or not after.word or after.text in _CLAUSE_END):
        y = _id(counts, adj.text)
        _pair(counts, x, ("SP", y, "{w}" + adj.text))
        _pair(counts, y, ("SP", x, toks[i].text + "{w}"))


def _noun_frames(counts, x, toks, i):
    """Z-F1 demonstrative before (这个〜, 这家〜), Z-F2 localizer after (在〜上, 〜里), Z-F3 suffix after
    (〜们), and the candidate Z-F5 (对〜来说)."""
    p1, n1 = _at(toks, i - 1), _at(toks, i + 1)
    if p1 is not None and p1.word:
        split = split_classifier(p1.text)
        if p1.text in DEMONSTRATIVES or (split and not split[2] and split[0] in DEMONSTRATIVES):
            _pair(counts, x, ("F1", _id(counts, p1.text), p1.text + "〜"))
    if n1 is None or not n1.word:
        return
    if n1.text in LOCALIZERS:
        zai = p1 is not None and p1.text == "在"
        _pair(counts, x, ("F2", _id(counts, n1.text), ("在〜" if zai else "〜") + n1.text))
    if n1.text in NOUN_SUFFIXES:
        _pair(counts, x, ("F3", _id(counts, n1.text), "〜" + n1.text))
    if n1.text == "来说" and p1 is not None and p1.text == "对":
        _pair(counts, x, ("F5", _id(counts, n1.text), "对〜来说"))


def _fused(counts, toks, i):
    """The shapes jieba fuses into one token (Z-F5), taken apart for counting — the token stays a word of
    its own, and the word inside it gets the use: 两辆车 (辆〜 for 车), 三 本书 (本〜 for 书), 很难 (很〜 is a
    form of 难), 看完 / 去过 / 看不懂 / 放在 (forms of 看, 去, 放 — and 放's coverb; never the nouns 演唱会 or
    活动: NOUN_ENDINGS), 朋友们 (〜们)."""
    t = toks[i]
    if not t.word or len(t.text) < 2 or t.text in LEXICALISED:
        return
    tags = tag_table()
    split = split_classifier(t.text)
    if split and split[2] and _nounlike(ZTok(split[2], "", tags.get(split[2]), True)):
        _pair(counts, _head(counts, t, len(t.text) - len(split[2]), split[2]), ("Q", None, split[1]))
        return
    p1 = _at(toks, i - 1)
    if p1 is not None and _numdem(p1.text) and t.text[0] in CLASSIFIERS \
            and _nounlike(ZTok(t.text[1:], "", tags.get(t.text[1:]), True)):
        _pair(counts, _head(counts, t, 1, t.text[1:]), ("Q", None, t.text[0]))
        return
    for degree in DEGREE:
        rest = t.text[len(degree):]
        if t.text.startswith(degree) and rest and (tags.get(rest) in ADJ_TAGS or tags.get(rest) in VERB_TAGS):
            _pair(counts, _head(counts, t, len(degree), rest), ("W", None, degree + "{w}"))     # 很忙, 很怕
            return
    noun = NOUN in classes(t.tag) and t.text[-1] in NOUN_ENDINGS         # 演唱会, 活动: a noun, no form
    for size in (1, 2):
        stem, rest = t.text[:size], t.text[size:]
        if noun or not rest or tags.get(stem) not in VERB_TAGS:
            continue
        marker = aspect(rest)
        if marker:
            form = "{w}" + marker
        elif rest in _COMPLEMENT_SET or (rest[0] in "得不" and rest[1:] in _COMPLEMENT_SET):
            form = "{w}" + rest
        else:
            continue
        y = _head(counts, t, 0, stem)
        _pair(counts, y, ("W", None, form))
        _coverb(counts, y, toks, i)
        return
    if (t.tag in VERB_TAGS or t.tag in ("l", None)) and len(t.text) >= 3:
        # A verb and its object in one word (打电话 — a set phrase, `l` —, 看电影): the pairing of both.
        # Two characters (关心, 生气) are words of their own far more often than a verb and an object; and a
        # three-character word jieba reads as two and one is a compound noun (放大器, 打火机).
        for size in (1, 2):
            stem, rest = t.text[:size], t.text[size:]
            if len(rest) >= 2 and tags.get(stem) in VERB_TAGS and NOUN in classes(tags.get(rest)) \
                    and not (len(t.text) == 3 and _two_then_one(t.text)):
                x, y = _head(counts, t, 0, stem), _head(counts, t, size, rest)
                _pair(counts, x, ("VO", y, "{w}" + rest))
                _pair(counts, y, ("VO", x, stem + "{w}"))
                return
    if t.text[-1] in NOUN_SUFFIXES and tags.get(t.text[:-1]) in NOUN_TAGS:
        y = _head(counts, t, 0, t.text[:-1])
        _pair(counts, y, ("F3", _id(counts, t.text[-1]), "〜" + t.text[-1]))


def _separable(counts, toks):
    """Z-W5: a two-character verb split by an insertion, read from the sentence string — jieba cuts 洗个澡
    into 洗 / 个 / 澡 and never sees 洗澡 in it. Any two-character verb in the dictionary; a shape shows
    only where the gate's floors (≥ 3 uses, ≥ 10% of the verb's) say it is the verb's own (§6.2). The
    second character must end a word there: 说了个笑话 is 说 … 笑话, never a split of 说笑."""
    if not _VERBS2:
        # Two-character verbs — and nouns: the dictionary files 生气 and 见面 as `n` (Z-F4). The split's
        # grammar (了, a pronoun, a measure word, X的) is narrow, and the floors decide what shows.
        _VERBS2.update((w, tag) for w, tag in tag_table().items()
                       if len(w) == 2 and (tag in VERB_TAGS or tag == "n"))
    tags = tag_table()
    starts, text = [], ""
    for t in toks:
        starts.append(len(text))
        text += t.text if t.word else ("\x00" * len(t.text))       # nothing splits across a barrier
    orig = "".join(t.orig if t.word else "\x00" * len(t.orig) for t in toks)
    word_start = []                             # each character: where its token starts
    for t, start in zip(toks, starts):
        word_start += [start] * len(t.text)
    for p, a in enumerate(text):
        if p > word_start[p] and tags.get(text[word_start[p]:p + 1]) is not None:
            continue                            # 认识几个字: 识 ends the word 认识 — no split of 识字
        for q in range(p + 2, min(p + 2 + _SPLIT_MAX, len(text))):
            verb = a + text[q]
            if verb not in _VERBS2:
                continue
            inserted = text[p + 1:q]
            if "\x00" in inserted or not _INSERTION.fullmatch(inserted):          # 下一班: 一 alone is none
                continue
            if tags.get(text[q:q + 2]) is not None and len(text[q:q + 2]) == 2:
                continue                        # 请了个客人: the second character starts a word (客人)
            if tags.get(inserted[-1] + text[q]) is not None:
                continue                        # 不了解: the insertion ends a word with it (了解)
            # Shapes that are never a split (Tatoeba, WP-Z4): the same word twice (拍了拍); a numeral, a
            # coverb or a negator first (几个字, 把他的手, 不了义 — the balanced build, WP-Z6); a pronoun,
            # particle, preposition or numeral second (忘了我, 懂了吗, 试着用, 买了辆); a measure word counting
            # the noun after it (买了张票, 喝了杯茶).
            second, after = text[q], tags.get(text[q + 1:q + 2])
            if a == second or tags.get(a) in ("m", "p") or a in COVERBS or a in "不没别" \
                    or (tags.get(second) or "x")[0] in "ryupcm" \
                    or (second in CLASSIFIERS and (NOUN in classes(after) or after == "zg")):
                continue
            x = _tally(counts, verb, orig[p] + orig[q], _VERBS2[verb])
            _pair(counts, x, ("W", None, text[p:q + 1]))


# --- scoring (pure) ------------------------------------------------------------------------------ #
# A form is kept when it covers at least this share of the word's uses. Chinese's own: Japanese lowers its
# patterns_build.FORM_SHARE to 0.05, and a Chinese build must not move with it (Patterns_Quality_Spec.md
# §10 E7).
FORM_SHARE = 0.10


def score(counts, floor):
    """-> (lemma_rows, alias_rows, pattern_rows) for the store — the Japanese row shapes.

    A word is shown as its Simplified self (the key); `alias` maps every spelling the corpus wrote it in
    (學習) to it. Line 1 is the measure word for a noun or the coverb for a predicate — for a word that is
    both (影响, a `vn`: 这个影响 and 对我影响很大), whichever kind has more slots. Only words at or above
    `floor` get pattern rows; a form must reach FORM_SHARE of the word's uses; a pairing or a frame
    patterns_build.MIN_PATTERN uses, scored by logDice."""
    from modules.junban import patterns_build as pb
    own = {}
    for (i, tag), c in counts.pos.items():
        # A word's part of speech is its commonest use of a class the rules count (as Japanese, builder 5).
        rank = (bool(classes(tag)), c)
        cur = own.get(i)
        if cur is None or rank > cur[1] or (rank == cur[1] and tag < cur[0]):
            own[i] = (tag, rank)
    lemma_rows = [(text, "", text, own.get(i, ("", 0))[0], counts.word[i]) for i, (text, _r) in enumerate(counts.keys)]
    alias_rows = [(orth, counts.keys[i][0], "", c) for (i, orth), c in counts.orth.items()]
    slots = Counter()
    for (x, key), c in counts.pattern.items():
        if key[0] in ("Q", "P"):
            slots[(x, key[0])] += c
    pattern_rows = []
    for (x, (rule, y, item)), c in counts.pattern.items():
        fx = counts.word[x]
        if fx < floor:
            continue
        text = counts.keys[x][0]
        files = counts.docs.get((x, (rule, y, item)), 0)
        if rule in ("Q", "P"):          # line 1's kind is its section: the lookup hides a thin coverb row
            other = "P" if rule == "Q" else "Q"
            if slots[(x, rule)] > slots[(x, other)] or (slots[(x, rule)] == slots[(x, other)] and rule == "Q"):
                pattern_rows.append((text, "", "particle", item, c, None, rule, files))
            continue
        if rule == "W":
            if c >= pb.MIN_PATTERN and c >= FORM_SHARE * fx:
                pattern_rows.append((text, "", "form", item, c, None, "W", files))
            continue
        if c < pb.MIN_PATTERN:
            continue
        fy = counts.word[y] if y is not None else c
        pattern_rows.append((text, "", _KIND[rule], item, c, round(pb.log_dice(c, fx, max(fy, c)), 3), rule,
                             files))
    return lemma_rows, alias_rows, pattern_rows


# --- lookup and rendering (§7) ------------------------------------------------------------------ #
# 书面语 in the card's own script (D9).
WRITTEN = {"s": "书面语", "t": "書面語"}


def script_of(word, zh_script=None):
    """The card's own script (D6): Traditional when its word changes under t2s, Simplified when it
    changes under s2t, else the user's `zh_script` (t → Traditional), else Simplified."""
    from app import zh_script as zs
    if zs.to_simplified(word) != word:
        return "t"
    if zs.to_traditional(word) != word:
        return "s"
    return "t" if zh_script == "t" else "s"


def _cut(text):
    from app.analyzer import chinese_cut, tagger_text
    return [t for t in chinese_cut(tagger_text(text)[0]) if t.strip()]


def resolve_key(word, store):
    """-> ((Simplified word, ""), None) or (None, reason) — §7. `word` is the card's word, normalised
    (`match.normalize_word`: pinyin brackets, markup and ruby gone). A word holding kana is Japanese and
    never looked up here (S4). One jieba word, or a compound the database keeps whole; several words are
    a phrase (D14); a spelling the corpus wrote (a Traditional one: the alias table) is the last resort. A 的 or
    地 written on the word comes off (认真地 is 认真, as `anki_match.one_word` reads a card), so does a 了 / 过 / 着
    after a verb (吃了 is 吃), and a doubled form is its word (开开心心 is 开心, as the builder keys it)."""
    if not word:
        return None, "no word"
    if _KANA.search(word):
        return None, "language"
    from app import zh_script as zs
    from app.analyzer import chinese_base, chinese_verb
    from app.anki_match import ZH_ASPECTS, ZH_CARD_ENDINGS
    simp = zs.to_simplified(word)
    tokens = _cut(simp)
    if len(tokens) == 2 and (tokens[1] in ZH_CARD_ENDINGS or (tokens[1] in ZH_ASPECTS and chinese_verb(tokens[0]))):
        tokens = tokens[:1]
    if len(tokens) == 1:
        tokens = [chinese_base(tokens[0]) or tokens[0]]
    if len(tokens) == 1 and store.word(tokens[0], ""):
        return (tokens[0], ""), None
    if store.word(simp, ""):
        return (simp, ""), None
    found = store.by_orth(word)
    if found:
        return found[0][:2], None
    return None, ("phrase" if len(tokens) > 1 else "not found")


def is_name(word):
    """Is the card's word a name (nr, nrfg, nrt: 鲁迅, 特朗普 — and 李明, which the dictionary does not
    hold: a word outside it is tagged by posseg's own cut)? Names get no register (§9)."""
    from app import zh_script as zs
    tokens = _cut(zs.to_simplified(word or ""))
    tags = [tag for t in tokens for _w, tag in parts(ZTok(t, t, tag_table().get(t), True))]
    return bool(tags) and all(tag in NAME_TAGS for tag in tags)


def _in_context(template, mark, simp):
    """`template` in Traditional, converted WITH the card's word in it — 〜 / {w} stand in for the word
    while converting, then take their place back (conversion is length-preserving): 头发 → 頭髮 in
    context, where character by character gives 頭發."""
    from app import zh_script as zs
    if mark not in template:
        return zs.to_traditional(template)
    i = template.index(mark)
    out = zs.to_traditional(template.replace(mark, simp, 1))
    return out[:i] + mark + out[i + len(simp):]


def render_lines(lines, word, script):
    """`lines` (`patterns.lines_for`) in the card's script. Simplified: as stored. Traditional: every item
    converted in context; a measure word with a numeral before it too — OpenCC needs one: 只猫 → 只貓, but
    一只猫 → 一隻貓 (checked 2026-09-24) — so 只〜 beside 猫 is 隻〜."""
    if script != "t":
        return lines
    from app import zh_script as zs
    simp = zs.to_simplified(word)
    out = dict(lines)
    out["particle"] = [((zs.to_traditional("一" + item + simp)[1:1 + len(item)] if item in CLASSIFIERS
                         else zs.to_traditional(item + simp)[:len(item)]), share)
                       for item, share in lines.get("particle", [])]
    for kind, mark in (("form", "{w}"), ("colloc", "{w}"), ("frame", "〜")):
        out[kind] = [(_in_context(item, mark, simp), n) for item, n in lines.get(kind, [])]
    return out


def _shown(word, key, script):
    """The word a card's lines are written with: the card's own spelling when the card is the word (問題 for 问题),
    else the word the lookup read it as (`resolve_key`), in the card's script — 认真地 is 认真 (认真履行, never
    认真地履行), 吃了 is 吃 (吃晚饭), 开开心心 is 开心 (很开心), 認真地 is 認真."""
    from app import zh_script as zs
    if zs.to_simplified(word) == key[0]:
        return word
    return zs.to_traditional(key[0]) if script == "t" else key[0]


def from_sources(word, stores, zh_script=None):
    """-> (html, reason, source) — `patterns.patterns_from_sources` for a Chinese card: the same choice
    (the first source with four collocations that is not thin, else the first with four, else the
    richest, the earlier on a tie), the lines in the card's own script, `{w}` its own spelling (or, for a card read
    as its word — 认真地, 吃了 — that word: `_shown`), `pat-thin`
    on every line when the chosen source has under `THIN_USES` uses of the word (Patterns_Quality_Spec
    §10 E3: the Japanese path's version never runs for Chinese), and 书面语 / 書面語 unless the word is a
    name."""
    from modules.junban import patterns as pt
    script = script_of(word, zh_script)
    best, first, full = None, None, None
    for name, store in stores:
        if store is None:
            continue
        key, reason = resolve_key(word, store)
        found = store.word(*key) if key else None
        uses = found[2] if found else 0
        if key is not None and uses < store.floor():
            key, reason = None, f"too rare ({uses} < {store.floor()})"
        shown = _shown(word, key, script) if key else word
        out = pt.format_patterns(render_lines(pt.lines_for(store, *key), shown, script), shown, name) if key else ""
        if not out:
            first = first or reason or "no pattern clears the floors"
            continue
        n, thin = pt._collocations(out), uses < pt.THIN_USES
        if best is None or n > best[0]:
            best = (n, out, name, thin)
        if n >= pt.CAPS["colloc"]:
            if not thin:
                full = (n, out, name, thin)
                break
            full = full or (n, out, name, thin)
    chosen = full or best
    if not chosen:
        return "", first or "no database built", None
    _n, out, name, thin = chosen
    if thin:
        out = re.sub(r'<div class="(pat-[^"]*)">', r'<div class="\1 pat-thin">', out)
    balanced = dict(stores).get("balanced")
    written = balanced is not None and not is_name(word) \
        and pt.register_of(resolve_key(word, balanced)[0], stores, language="zh")
    return out + (f'<div class="pat-register">{WRITTEN[script]}</div>' if written else ""), None, name

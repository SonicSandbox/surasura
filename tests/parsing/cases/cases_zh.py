"""Chinese — jieba's segmentation, the script setting, and the Chinese consumers (layers tokens_zh, text, card_key,
known, and evaluators_zh.py's zh_* layers).

Ported 2026-09-26 from debug/parsing_suite/zh (the adversary's 229 rows: cases_data.py, measured in cases.md — its
"today" is reproduced here), the Chinese rows of debug/parsing_suite/known/known_cases.md (merged into the adversary
row they repeat; `refs` names both), and the key cases of the zh tests (LOCK, `refs` naming the test). This file owns
every ZH- group (docs/agent instructions/Parsing_Suite.md, "Ids"):

    SEG segmentation · NAM names · PRT particles, aspect · RED reduplication · SEP separable verbs · MSR measure words
    NUM numerals · IDM chengyu · SCR script (繁简), kana in Chinese · YUE Cantonese · SPL sentence ends · LAT Latin,
    digits · TXT reading subtitle files · ENC characters, encodings · CRD card fields · KEY card matching
    KNW known words, their caches · NTL note-type language · BDG the 文 badge, tiers · PAT パターン

Statuses follow the adversary's (OK → LOCK, WRONG → TARGET, LIMITATION → LIMIT, DISPUTED → DISPUTED), with its
matches-today LIMITATIONs as LOCK citing the decision they prove. The families of wrong segmentations cite the open
decision that would fix them: ZH-HMM (jieba's HMM guesses), ZH-DICTIONARY (phrases in jieba's dictionary), ZH-LEMMA,
ZH-NUMERALS, ZH-TRAD-ASIS. Sources: the zh library is the four bundled samples (data/zh); Tatoeba, KdConv, zhwiki
and zhwikinews are the staged corpora (docs/assets/corpora/zh); "doc: tests/Test Resources/zh/…" are the fixtures.
"""
from tests.parsing.case import Case, ass, srt

TAT = "corpus: Tatoeba cmn (CC BY 2.0 FR)"
KD = "corpus: KdConv (Apache-2.0)"
WIKI = "corpus: zhwiki (CC BY-SA 4.0)"
WN = "corpus: zhwikinews (CC BY 4.0)"
LIB1 = "library: data/zh HighPriority/H_priority_sample_1.txt"
LIB2 = "library: data/zh HighPriority/H_priority_sample_2.txt"
LIB3 = "library: data/zh LowPriority/L_priority_sample_1.txt"
LIB4 = "library: data/zh LowPriority/L_priority_sample_2.txt"
FIX = "doc: tests/Test Resources/zh/patterns_zh_sample.txt"
FIXT = "doc: tests/Test Resources/zh/patterns_zh_sample_trad.txt"
BBC = "doc: tests/Test Resources/zh/chinese_text_1.txt"
TWN = "doc: tests/Test Resources/zh/traditional_news.txt"
MIX = "doc: tests/Test Resources/zh/mixed_script_transcript.txt"
CTX = "doc: tests/Test Resources/zh/context_test.txt"
SHARED = "doc: release_assets/patterns/patterns_zh_shared.zip (shared v2, f996b2c)"
MADE = "constructed"

# The line the adversary quoted twice from the library (a name, an idiom, an HMM fusion).
LIB1_SEAL = ("于是，龙仁用一尊龙神像设下神圣封印，藉此让拥有邪恶力量的敌人不得其门而入——但是却碰上我们的造访。")
LIB1_ROSE = "雅露露紧皱着眉，而白蔷薇小姐则不发一语地听着龙仁的话。"
BUDGET = "2005-06财政年度，加州大學河濱分校的运营预算为四亿三千五百万美元。"
CANTONESE = "任何犯咗法嘅人，我哋都會揾證據。"
# mixed_script_transcript.txt: the same dish in a Traditional and a Simplified line.
NOODLES = "這家店的牛肉麵非常有名，每天都有很多人排隊。\n我们先点一碗牛肉面，再来一杯珍珠奶茶。"


def zh(row):
    return f"debug/parsing_suite/zh {row}"


def kc(row):
    return f"debug/parsing_suite/known {row}"


def seg(id, category, text, span, want, basis, status, **more):
    """A tokens_zh case expecting exactly `want` for the span (the zh adversary's notation: counted words joined
    ' / ', dropped text in [brackets])."""
    return Case(id=id, lang="zh", layer="tokens_zh", category=category, text=text, span=span,
                expect={"seg": want}, basis=basis, status=status, **more)


def count(id, text, word, expect, basis, status, **more):
    """A zh_pat_count case: what the Chinese パターン builder counts for `word` in `text`."""
    return Case(id=id, lang="zh", layer="zh_pat_count", category="M", text=text, span="", expect=expect,
                basis=basis, status=status, ctx={"word": word, **more.pop("ctx", {})}, **more)


def conv(id, text, span, script, out, basis, status, **more):
    """A zh_conv case: the zh_script setting's conversion of `text`."""
    return Case(id=id, lang="zh", layer="zh_conv", category="O", text=text, span=span, expect={"out": out},
                basis=basis, status=status, ctx={"script": script}, **more)


CASES = [
    # === O. segmentation — seeded by the framework ================================================================ #
    Case(id="ZH-SEG-001", lang="zh", layer="tokens_zh", category="O",
         text="过了一会儿，他来了。", span="他来",
         expect={"seg": "他 / 来"},
         basis="Pronoun + verb; 他来 is no CC-CEDICT word and UD splits 他:PRON / 来:VERB — jieba's HMM fuses two "
               "known words where its dictionary has no path it prefers.",
         status="LOCK", decision="ZH-HMM", source="constructed",
         refs=("debug/parsing_suite/zh ZH-SEG-01", kc("RL-83")), note="HMM off: 他 / 来 (fixed)."),
    Case(id="ZH-SEG-002", lang="zh", layer="tokens_zh", category="O",
         text="你做事不能半途而废。", span="半途而废",
         expect={"seg": "半途而废"},
         basis="CC-CEDICT idiom 半途而废 'give up halfway' — one word (four-character idioms are 93% whole today).",
         status="LOCK", source="corpus: Tatoeba cmn (CC BY 2.0 FR)",
         refs=("debug/parsing_suite/zh ZH-IDIOM-03",)),
    Case(id="ZH-SEG-003", lang="zh", layer="tokens_zh", category="O",
         text="他就把书放下了。", span="就把",
         expect={"seg": "就 / 把"},
         basis="就 + the coverb 把 (disposal construction) are two words; the reinforce setting forces exactly this "
               "split (jieba 0.42.1 makes it anyway).",
         status="LOCK", source="constructed", ctx={"reinforce": True},
         refs=("analyzer.ChineseTokenizer (reinforce)", "debug/parsing_suite/zh ZH-SEG-20", kc("ZH-11"))),

    # --- HMM fusions, jieba's dictionary phrases, path errors ------------------------------------------------------ #
    seg("ZH-SEG-004", "O", "我要睡覺", "我要", "我 / 要",
        "Pronoun + the modal 要: UD 我:PRON / 要:AUX ×13, never one token; no CC-CEDICT word — jieba's HMM glues two "
        "dictionary words (Z-F9: 我要 is one of the commonest fusions, 436 in Tatoeba).",
        "LOCK", decision="ZH-HMM", source=TAT, refs=(zh("ZH-SEG-02"), kc("ZH-4")),
        note="HMM off: 我 / 要 (fixed)."),
    seg("ZH-SEG-005", "O", "喔喔，这是目前为止最长的名号！", "这是", "这 / 是",
        "Demonstrative + copula: UD 这:PRON / 是:AUX ×22, never one token; no CC-CEDICT word (Tatoeba's commonest "
        "HMM fusion, 469 uses).",
        "LOCK", decision="ZH-HMM", source=LIB2, refs=(zh("ZH-SEG-03"), kc("ZH-4")),
        note="HMM off: 这 / 是 (fixed)."),
    seg("ZH-SEG-006", "O", "我试着打圆场。", "我试", "我 / 试",
        "Pronoun + verb (试着 = try + the durative 着); an HMM fusion, no dictionary word.",
        "LOCK", decision="ZH-HMM", source=LIB2, refs=(zh("ZH-SEG-04"),), note="HMM off: fixed."),
    seg("ZH-SEG-007", "O", "我用香蕉剑朝黑暗球的中央砍去。", "剑朝", "剑 / 朝",
        "A noun + the coverb 朝 'towards': an HMM fusion across a phrase boundary.",
        "LOCK", decision="ZH-HMM", source=LIB3, refs=(zh("ZH-SEG-05"),), note="HMM off: fixed."),
    seg("ZH-SEG-008", "O", "我和雅露露轻轻点头。", "我和雅", "我 / 和 / 雅露露",
        "Pronoun + 和 + the character's name 雅露露 (Yaruru); the HMM takes the name's first character into 我和雅.",
        "TARGET", decision="ZH-HMM", source=LIB2, refs=(zh("ZH-SEG-06"),),
        note="HMM off: 我 / 和 / 雅 — still wrong, the name splits (ZH-NAM-004)."),
    seg("ZH-SEG-009", "O", LIB1_ROSE, "而白", "而 / 白蔷薇",
        "而 'while' + the name 白蔷薇 (Shirobara); 而白 is no word.",
        "TARGET", decision="ZH-HMM", source=LIB1, refs=(zh("ZH-SEG-07"),),
        note="HMM off: 而 / 白 — the name still splits."),
    seg("ZH-SEG-010", "O", LIB1_ROSE, "不发一语", "不 / 发 / [一] / 语",
        "A set phrase CC-CEDICT does not list (its idiom is 一言不发), so its words 不 发 一 语; the HMM makes the "
        "non-word 发一语.",
        "LOCK", decision="ZH-HMM", source=LIB1, refs=(zh("ZH-SEG-08"),), note="HMM off: fixed."),
    seg("ZH-SEG-011", "O", "他们说说笑笑地走了。", "地走了", "地 / 走 / 了",
        "The adverbial particle 地, the verb, the aspect marker — three words (UD PART / VERB / AUX); 地走了 is a "
        "jieba dictionary entry (freq 3, tag l) that no dictionary lists.",
        "LOCK", decision="ZH-DICTIONARY", source=MADE, refs=(zh("ZH-SEG-09"),)),
    seg("ZH-SEG-012", "O", "龙仁激动地喊着，但白蔷薇小姐却硬是截断他的话。", "地喊", "地 / 喊",
        "地 + the verb 喊 — here an HMM guess (ZH-SEG-011's 地走了 is a dictionary entry).",
        "LOCK", decision="ZH-HMM", source=LIB2, refs=(zh("ZH-SEG-10"),), note="HMM off: fixed."),
    seg("ZH-SEG-013", "O", "我唱歌唱得很好。", "唱歌唱", "唱歌 / 唱",
        "The verb-copying construction V-O-V-得 (Li & Thompson 1981 §11): 唱歌 (CC-CEDICT, a 离合词), then 唱 again "
        "before 得; jieba's best path reads the dictionary word 歌唱 'to sing (lit.)' (freq 410).",
        "TARGET", source=TAT, refs=(zh("ZH-SEG-11"),),
        note="A path error — neither an HMM guess nor a phrase entry: no switch fixes it."),
    seg("ZH-SEG-014", "O", LIB1_SEAL, "龙仁用", "龙仁 / 用",
        "A name + the verb 用; the HMM fuses them (龙仁叹, 由龙仁 and 尼洛是 in the same library).",
        "LOCK", decision="ZH-HMM", source=LIB1, refs=(zh("ZH-SEG-12"),),
        note="HMM off: 龙 / 仁 / 用 — the name splits instead."),
    seg("ZH-SEG-015", "O", "白蔷薇小姐硬是盖掉我的台词……好郁卒我想死。", "好郁卒", "好 / 郁卒",
        "CC-CEDICT 郁卒 (Tw) 'depressed and frustrated' after the degree adverb 好; the HMM makes 好郁 + 卒.",
        "TARGET", decision="ZH-COMPOUND-JOIN", source=LIB2, refs=(zh("ZH-SEG-13"),),
        note="HMM off: 好 / 郁 / 卒 — still wrong (jieba lacks 郁卒)."),
    seg("ZH-SEG-016", "O", "附带一提，她说累积到一万点会送我一根香蕉。", "一万点会", "[一万] / 点 / 会",
        "The numeral, the measure word 点 'points', the modal 会; 点会 is no word (HMM).",
        "LOCK", decision="ZH-HMM", source=LIB2, refs=(zh("ZH-SEG-14"),), note="HMM off: fixed."),
    seg("ZH-SEG-017", "O", "她拥抱了一下儿子,然后让他上床睡觉。", "一下儿子", "一下 / 儿子",
        "一下 (CC-CEDICT; UD 一下:ADV) + 儿子 'son' — the erhua 一下儿 would be wrong here.",
        "LOCK", source=TAT, refs=(zh("ZH-SEG-15"),)),
    seg("ZH-SEG-018", "O", "请稍等一下儿。", "稍等一下儿", "稍等 / 一下儿",
        "CC-CEDICT 稍等 'to wait a moment' and 一下儿 'erhua form of 一下'; jieba's dictionary holds 稍等一下 "
        "(freq 3, tag l) and leaves 儿 a word of its own.",
        "TARGET", decision="ZH-COMPOUND-JOIN", source=MADE, refs=(zh("ZH-SEG-16"),)),
    seg("ZH-SEG-019", "O", "我考了HSK四级。", "我考", "我 / 考",
        "Pronoun + verb; the Latin run splits the Han text and the HMM fuses the short remainder.",
        "LOCK", decision="ZH-HMM", source=MADE, refs=(zh("ZH-SEG-17"),), note="HMM off: fixed."),
    seg("ZH-SEG-020", "O", "呼呼，这下真是赚到了。", "这下", "这下",
        "CC-CEDICT 这下 [zhe4 xia4] 'this time' — a dictionary word, kept whole.",
        "LIMIT", decision="ZH-HMM", source=LIB2, refs=(zh("ZH-SEG-18"),),
        note="HMM off breaks it (这 / 下): one of the four cases switching the HMM off costs — accepted with "
             "the surname guard (ZH-HMM, 2026-09-30); a join of CC-CEDICT's words (ZH-COMPOUND-JOIN) was measured "
             "and not built."),
    seg("ZH-SEG-021", "O", "你把门关上吧。", "把门", "把 / 门",
        "The disposal construction 把 + object + verb (把门关上 'shut the door'); jieba prefers the dictionary word "
        "把门 'to stand as a goalkeeper' (CC-CEDICT), so the list counts 把门 and 门 loses the use.",
        "TARGET", source=FIX, refs=(zh("ZH-SEG-19"),), note="A path error: no switch fixes it."),
    seg("ZH-SEG-022", "O", "他就把书放下了。", "就把", "就 / 把",
        "就 + the coverb 把: two words. jieba 0.42.1 splits them without the reinforce setting too — neither 就把 nor "
        "您不 is in its dictionary; the setting is a hand list of exactly these two pairs (ZH-SEG-003 has it on).",
        "LOCK", source=MADE, ctx={"reinforce": False},
        refs=(zh("ZH-SEG-20"), kc("ZH-11"), "tests/test_reinforce.py (hollow: test_reinforce_disabled is `pass`)")),
    seg("ZH-SEG-023", "O", "这里似乎距离地面很近。", "很近", "很 / 近",
        "Degree adverb + adjective (UD 很:ADV / 好:ADJ, 很:ADV / 快:ADJ); 很近 is no CC-CEDICT word — the HMM joins "
        "them (很准, 很想, 很长 in the same library).",
        "LOCK", decision="ZH-HMM", source=LIB2, refs=(zh("ZH-SEG-21"),), note="HMM off: fixed."),
    seg("ZH-SEG-024", "O", "他很着急。", "很着急", "很 / 着急",
        "CC-CEDICT 着急 'to worry' after the degree adverb; 很着急 is a jieba dictionary entry (freq 3, tag l), no word.",
        "LOCK", decision="ZH-DICTIONARY", source=MADE, refs=(zh("ZH-SEG-22"),)),
    seg("ZH-SEG-025", "O", "「呼哈哈哈看吧！", "看吧", "看 / 吧",
        "The verb + the sentence particle 吧 (UD 吧:PART); 看吧 is no CC-CEDICT word but a jieba entry (freq 180, n).",
        "LOCK", decision="ZH-DICTIONARY", source=LIB3, refs=(zh("ZH-SEG-23"),)),
    seg("ZH-SEG-026", "O", "我们去看电影吧。", "电影吧", "电影 / 吧",
        "电影 + the particle 吧; jieba's dictionary lists 电影吧 as a noun (freq 3), so the list gets it — the パターン "
        "builder works round it (patterns_zh._noun_of), the analyzer doesn't.",
        "LOCK", decision="ZH-DICTIONARY", source=FIX, refs=(zh("ZH-SEG-24"), kc("ZH-10"))),
    seg("ZH-SEG-027", "O", "他在冒险中学会了勇敢和坚强。", "中学会", "中 / 学会",
        "冒险中 'in the adventure' (the localizer 中) + 学会 'learned' (CC-CEDICT); jieba's best path reads 中学 "
        "'middle school' + 会. Accepted for パターン, whose keys must be the analyzer's (Patterns_Chinese_Spec §6.6) — "
        "never decided for the list.",
        "TARGET", source=CTX, refs=(kc("ZH-2"), "golden: tests/Test Resources/zh/asis_tokens_golden.json"),
        note="A path error: neither HMM off nor a phrase rule reaches it."),
    seg("ZH-SEG-028", "O", "他生我的气了。", "他生", "他 / 生",
        "Pronoun + 生 of the separable 生气, split by 我的 (生我的气 'be angry with me'); the HMM glues 他生.",
        "LOCK", decision="ZH-HMM", source=MADE, refs=(kc("ZH-3"),)),
    seg("ZH-SEG-029", "O",
        "特朗普的发文强调“与中国关系很好”“我和习主席的个人关系非常好”，并列举通话涵盖的议题范围，但对臺湾部分着墨较少;",
        "我和习", "我 / 和 / 习",
        "Pronoun + 和 + the surname 习 of 习主席 'Chairman Xi'; the HMM glues 我和习 (a golden-pinned list word).",
        "LOCK", decision="ZH-HMM", source=BBC,
        refs=(kc("ZH-3"), "golden: tests/Test Resources/zh/asis_tokens_golden.json (lemma 我和习)")),
    seg("ZH-SEG-030", "O", "我喜欢喝咖啡。", "喝咖啡", "喝 / 咖啡",
        "Verb + object (UD 踢:VERB / 足球:NOUN for the like 踢足球); 喝咖啡 is a jieba dictionary entry (freq 3, filed "
        "as a name), no CC-CEDICT word — the list counts a phrase and 咖啡 loses the use.",
        "TARGET", decision="ZH-DICTIONARY", source=MADE, refs=(kc("ZH-9"),)),
    seg("ZH-SEG-031", "O", "我坐出租车去机场。", "出租车", "出租车",
        "CC-CEDICT 出租车 'taxi' — a noun jieba keeps whole; a rule splitting jieba's phrases must keep it.",
        "LOCK", decision="ZH-DICTIONARY", source=MADE, refs=(kc("ZH-9"),)),
    seg("ZH-SEG-032", "O", "我们去酒吧喝一杯。", "酒吧", "酒吧",
        "CC-CEDICT 酒吧 'bar' ends in the particle's character; a rule taking 吧 off (电影吧 → 电影 + 吧) must leave it.",
        "LOCK", decision="ZH-DICTIONARY", source=MADE, refs=(kc("ZH-10"),)),
    seg("ZH-SEG-033", "O", "您不用担心。", "您不", "您 / 不用",
        "您 + 不用 'need not' — the reinforce setting's second pair (您不); jieba splits it with or without the tuning.",
        "LOCK", source=MADE, ctx={"reinforce": True}, refs=(kc("ZH-11"), "analyzer.ChineseTokenizer (reinforce)")),

    # === I. names ================================================================================================= #
    seg("ZH-NAM-001", "I", "我的朋友李明是老师。", "李明", "李明",
        "A personal name is one proper noun (UD PROPN); jieba's HMM joins surname + given name.",
        "LOCK", decision="ZH-HMM", source=FIX, refs=(zh("ZH-NAME-01"), kc("ZH-21")),
        note="HMM off breaks it (李 / 明)."),
    seg("ZH-NAM-002", "I", "贏的是，王小明。", "王小明", "王小明",
        "One personal name (UD PROPN).", "LOCK", source=TAT, refs=(zh("ZH-NAME-02"),)),
    seg("ZH-NAM-003", "I", "还叫欧阳丹枫，邱呼生。", "欧阳丹枫", "欧阳丹枫",
        "One personal name: the compound surname 欧阳 (CC-CEDICT) + the given name 丹枫 — UD tokenizes a full name as "
        "one PROPN.",
        "TARGET", source=KD, refs=(zh("ZH-NAME-03"),), note="HMM off: 欧阳 / 丹 / 枫 — worse."),
    seg("ZH-NAM-004", "I", "「喂，雅露露！？」", "雅露露", "雅露露",
        "A character's name (Yaruru) is one word; split, it puts 雅 'elegant' on the list (露露 is the library's "
        "commonest non-CC-CEDICT word: 27 uses).",
        "TARGET", decision="ZH-NAMES", source=LIB1, refs=(zh("ZH-NAME-04"),)),
    seg("ZH-NAM-005", "I", "我连滚带爬地逃离香德拉。", "香德拉", "香德拉",
        "A name (Shandora) is one word; split, 香 'fragrant' is counted as vocabulary (德拉: 21 uses).",
        "TARGET", decision="ZH-NAMES", source=LIB4, refs=(zh("ZH-NAME-05"),)),
    seg("ZH-NAM-006", "I", "你正是勇者巴拿纳德大人的转世哟。", "巴拿纳德", "巴拿纳德",
        "A transliterated name, one word — the HMM joins it (11 uses in the library).",
        "LIMIT", decision="ZH-HMM", source=LIB1, refs=(zh("ZH-NAME-06"),), note="HMM off breaks it (巴 / 拿 / 纳 / 德): 巴 is no surname, so the guard can't keep it — the price the "
                "user accepted with the surname guard (ZH-HMM, 2026-09-30)."),
    seg("ZH-NAM-007", "I", "哈利波特系列。", "哈利波特", "哈利波特",
        "CC-CEDICT 哈利·波特 'Harry Potter' — the name written without its dot is still one name, never 哈利波 + 特.",
        "TARGET", decision="ZH-NAMES", source=KD, refs=(zh("ZH-NAME-07"),)),
    seg("ZH-NAM-008", "I", "你看过哈利·波特与魔法石吗？", "哈利·波特", "哈利 / [·] / 波特",
        "With the interpunct the given name and the surname are two words; the dot is punctuation (GB/T 15834-2011, "
        "间隔号).", "LOCK", source=KD, refs=(zh("ZH-NAME-08"),)),
    seg("ZH-NAM-009", "I", "约翰・列侬是1940年出生的。", "约翰・列侬", "约翰 / [・] / 列侬",
        "The katakana middle dot U+30FB used as 间隔号 (as Traditional text often does): jieba cuts it off, so the "
        "name's parts are counted as with ·.",
        "LIMIT", decision="ZH-HMM", source="constructed: from Tatoeba's 约翰·列侬",
        refs=(zh("ZH-NAME-09"), kc("ZH-87")),
        note="HMM off breaks it (列 / 侬): a name's second part, no surname leading it — the price the user accepted "
             "with the surname guard (ZH-HMM, 2026-09-30)."),
    seg("ZH-NAM-010", "I", "三个臭皮匠，赛过诸葛亮。", "诸葛亮", "诸葛亮",
        "A historical name (CC-CEDICT 诸葛亮), one word.", "LOCK", source=TAT, refs=(zh("ZH-NAME-10"),)),
    seg("ZH-NAM-011", "I", "中国打着长远算盘，习近平与特朗普暂时休战", "特朗普", "特朗普",
        "A transliterated name, one word (in jieba's dictionary).", "LOCK", source=BBC,
        refs=(zh("ZH-NAME-11"), kc("ZH-21"))),
    seg("ZH-NAM-012", "I", "那是小李的书。", "小李", "小李",
        "小 + a surname, a form of address used as a name (UD PROPN).", "TARGET", decision="ZH-NAMES", source=TAT,
        refs=(zh("ZH-NAME-12"),)),
    seg("ZH-NAM-013", "I", "张又侠落马：中共军方高层震荡，“空窗期”内台湾如何面临双重考验", "张又侠", "张又侠",
        "A general's name (张 + 又侠) — one proper noun; jieba cuts 张 / 又 / 侠, and the pieces pair with other words "
        "on パターン cards (Patterns_Chinese_Spec §16.1 WP-Z6: accepted noise there, never for the list).",
        "TARGET", decision="ZH-NAMES", source=BBC, refs=(kc("ZH-7"),)),

    # === O. particles and aspect ================================================================================== #
    seg("ZH-PRT-001", "O", "我已经吃了饭。", "吃了饭", "吃 / 了 / 饭",
        "Verb + aspect 了 + object (UD 吃:VERB / 了:AUX); 吃了饭 is no CC-CEDICT word — jieba's dictionary holds the "
        "phrase (freq 3, l), so the list gets a 'word' 吃了饭 and 吃饭 loses the use.",
        "LOCK", decision="ZH-DICTIONARY", source=FIX, refs=(zh("ZH-PART-01"),)),
    seg("ZH-PRT-002", "O", "我去过北京，也去过上海。", "去过", "去 / 过",
        "UD 去:VERB / 过:AUX ×3 — the experiential 过 is its own token; 去过 is no CC-CEDICT word (a jieba entry, "
        "freq 550, tag vq).",
        "LOCK", decision="ZH-DICTIONARY", source=FIX, refs=(zh("ZH-PART-02"),)),
    seg("ZH-PRT-003", "O", "他笑着说：“没问题！”", "笑着", "笑 / 着",
        "Verb + the durative 着 (UD AUX).", "LOCK", source=FIX, refs=(zh("ZH-PART-03"),)),
    seg("ZH-PRT-004", "O", "看着办吧。", "看着办", "看着办",
        "CC-CEDICT 看着办 'to do as one sees fit' — lexicalised, one word.", "LOCK", source=TAT,
        refs=(zh("ZH-PART-04"),)),
    seg("ZH-PRT-005", "O", "他睡着了。", "睡着", "睡着",
        "CC-CEDICT 睡着 [shui4 zhao2] 'to fall asleep' — 着 is the result complement zháo here, one word.",
        "LOCK", source=TAT, refs=(zh("ZH-PART-05"),)),
    seg("ZH-PRT-006", "O", "汤姆跑得很快。", "跑得很快", "跑 / 得 / 很 / 快",
        "The complement of 得 is degree + adjective, 'very fast': UD splits 很 / 快 ×10 there and keeps 很快 whole "
        "(×8) only for 'soon' (ZH-PRT-007); 很快 is not in CC-CEDICT (a jieba entry, freq 5,033).",
        "LOCK", decision="ZH-DICTIONARY", source=TAT, refs=(zh("ZH-PART-06"),)),
    seg("ZH-PRT-007", "O", "他很快就回来了。", "很快", "很快",
        "Here 很快 means 'soon' — UD keeps it one token (很快:ADV ×5).",
        "LIMIT", decision="ZH-DICTIONARY", source=FIX, refs=(zh("ZH-PART-07"),),
        note="A rule splitting every jieba entry CC-CEDICT lacks would break this — the same string as ZH-PRT-006. "
             "The price ZH-DICTIONARY accepts: CC-CEDICT lacks 很快, so it is 很 + 快 (its 'soon' counted as 快, which "
             "CC-CEDICT also glosses 'soon')."),
    seg("ZH-PRT-008", "O", "得走了。", "得", "得",
        "得 děi 'must' is one word here. It shares one key with the particle de (跑得快) and dé (得到): the key has no "
        "reading, so the list counts three words as one (ZH-NO-READING).",
        "LOCK", decision="ZH-NO-READING", source=TAT, refs=(zh("ZH-PART-08"),)),
    seg("ZH-PRT-009", "O", "我受不了他。", "受不了", "受不了",
        "CC-CEDICT 受不了 'unbearable' — a lexicalised potential form, one word.", "LOCK", source=TAT,
        refs=(zh("ZH-PART-09"),)),
    seg("ZH-PRT-010", "O", "「好了，赶快带我们到秘宝那里！龙之秘宝是我的！」", "好了", "好 / 了",
        "Adjective + the sentence-final 了 (UD 好:ADJ / 了:PART) — two words.", "LOCK", source=LIB2,
        refs=(zh("ZH-PART-10"),)),
    seg("ZH-PRT-011", "O", "红红的火苗，滚开的水，越煮越有滋味。", "红红的", "红红 / 的",
        "A reduplicated adjective + the particle 的 (UD 的:PART, 3,407×); 红红的 is no CC-CEDICT word (a jieba entry, "
        "freq 113, z).",
        "TARGET", decision="ZH-DICTIONARY", source=TAT, refs=(zh("ZH-PART-11"),)),
    seg("ZH-PRT-012", "O", "这件事我了解了。", "了解了", "了解 / 了",
        "了解 liǎojiě (a word) then aspect 了 le — the same character, two words, kept apart.", "LOCK", source=MADE,
        refs=(zh("ZH-PART-12"),)),
    seg("ZH-PRT-013", "O", "他慢慢地走过来。", "慢慢地", "慢慢 / 地",
        "CC-CEDICT 慢慢 + the adverbial particle 地.", "LOCK", source=MADE, refs=(zh("ZH-PART-13"),)),
    seg("ZH-PRT-014", "O", "我们四个人都坐在可爱的床铺上交谈着。", "交谈着", "交谈 / 着",
        "Verb + the durative 着.", "LOCK", source=LIB1, refs=(zh("ZH-PART-14"),)),
    seg("ZH-PRT-015", "O", "我看完了这本书。", "看完", "看 / 完",
        "A verb + its result complement: CC-CEDICT lists many such compounds (看懂, 听懂, 拿走, 看不懂) but not 看完, "
        "and UD splits them about half the time (找到:VERB ×8, 找:VERB / 到:VERB ×6; 246 compound:vv/dir arcs). One "
        "word, or the verb and its complement — the user's call; today it is two, as expected here.",
        "LOCK", decision="ZH-DICTIONARY", source=FIX, refs=(zh("ZH-PART-15"),)),
    seg("ZH-PRT-016", "O", "我听得懂中文，可是说得不好。", "听得懂", "听得懂",
        "CC-CEDICT 听得懂 'to understand (by hearing)' — a lexicalised potential form.", "LOCK", source=FIX,
        refs=(zh("ZH-PART-16"),)),

    # === O. reduplication ========================================================================================= #
    seg("ZH-RED-001", "O", "看看！", "看看", "看看",
        "CC-CEDICT 看看; UD 看看:VERB ×7 — the tentative AA form is one token.", "LOCK", source=TAT,
        refs=(zh("ZH-REDUP-01"),)),
    seg("ZH-RED-002", "O", "请看一看。", "看一看", "看一看",
        "CC-CEDICT 看一看; UD 看一看:VERB — A一A is one token.", "LOCK", source=TAT, refs=(zh("ZH-REDUP-02"),)),
    seg("ZH-RED-003", "O", "你想帮帮忙吗？", "帮帮忙", "帮帮忙",
        "CC-CEDICT 帮帮忙 'to help' — the AAB form of the 离合词 帮忙.", "LOCK", source=TAT, refs=(zh("ZH-REDUP-03"),)),
    seg("ZH-RED-004", "O", "「你就试试看吧。」", "试试看", "试试看",
        "CC-CEDICT 试试看 'to give it a try'.", "LOCK", source=LIB4, refs=(zh("ZH-REDUP-04"),)),
    seg("ZH-RED-005", "O", "人人都好。", "人人", "人人",
        "CC-CEDICT 人人 'everyone'.", "LOCK", source=TAT, refs=(zh("ZH-REDUP-05"),)),
    seg("ZH-RED-006", "O", "她高高兴兴地回家了。", "高高兴兴", "高兴",
        "CC-CEDICT 高高兴兴 — the AABB vivid form of 高兴, counted as 高兴 (ZH-LEMMA: its senses share 'cheerful' and "
        "'mood' with 高兴's) — moved on purpose with the rule (2026-09-30).", "LOCK", decision="ZH-LEMMA", source=MADE,
        refs=(zh("ZH-REDUP-06"),)),
    seg("ZH-RED-007", "O", "你應該休息休息。", "休息休息", "休息",
        "ABAB tentative reduplication of 休息 — one use, as 看看 (AA) is one token. Today two tokens, so 休息 is "
        "counted twice for one use; as its lemma it is 休息, once.",
        "LOCK", decision="ZH-LEMMA", source=TAT, refs=(zh("ZH-REDUP-07"),),
        note="The other answer: 休息休息 as one word. Either way, not two uses."),
    seg("ZH-RED-008", "O", "大家都开开心心的。", "开开心心", "开心",
        "AABB is productive morphology (Li & Thompson 1981 §3.1.1): 开开心心 is not in CC-CEDICT while 高高兴兴 is, so "
        "which AABB forms get a row of their own depends on jieba's dictionary (开开心心: freq 10). As a lemma, 开心.",
        "LOCK", decision="ZH-LEMMA", source=MADE, refs=(zh("ZH-REDUP-08"),),
        note="The other answer — every AABB its own word — is today, by dictionary accident."),
    seg("ZH-RED-009", "O", "汤姆说他想问我一个个人问题。", "一个个人", "[一] / 个 / 个人",
        "'A personal question': 一个 + 个人 (CC-CEDICT 'personal'); the reduplicated 一个个 'one by one' is wrong here. "
        "一个 is a count (ZH-DICTIONARY's count rule: the treebanks cut it 342 times, never keep it whole), so 一 / 个 — "
        "moved on purpose with the rule (2026-09-30).",
        "LOCK", source=TAT, refs=(zh("ZH-REDUP-09"),)),
    seg("ZH-RED-010", "O", "“我们在悉尼大学读书，就是想要一个干干净净，没有人打扰我们的环境。", "干干净净", "干净",
        "The AABB form of 干净, one token (UD would give one ADJ); not in CC-CEDICT, so counted as 干净 (ZH-LEMMA) — moved "
        "on purpose with the rule (2026-09-30).",
        "LOCK", decision="ZH-LEMMA", source=WN, refs=(zh("ZH-REDUP-10"),)),
    seg("ZH-RED-011", "O", "哈哈哈哈哈！", "哈哈哈哈哈", "哈哈",
        "Laughter is one interjection however long; jieba's dictionary has 哈哈 and 哈哈哈, so a run is cut by length "
        "(哈哈哈 / 哈哈; 啊啊啊啊 → 啊啊啊 / 啊; 呵呵呵呵呵 → 呵呵 / 呵呵 / 呵). As a lemma: CC-CEDICT's 哈哈, once.",
        "LOCK", decision="ZH-LEMMA", source=MADE, refs=(zh("ZH-REDUP-11"),),
        note="The other answer: the run as one word. The library's 哈哈哈哈 happens to be one token."),

    seg("ZH-RED-401", "O", "这里有形形色色的人。", "形形色色", "形形色色",
        "CC-CEDICT 形形色色 'all kinds of' is a word of its own — its base 形色 means 'shape and color; appearance': an "
        "AABB form with a meaning its base lacks is never folded into it (OGO-EXCEPTIONS' test, ZH-LEMMA).",
        "LOCK", decision="ZH-LEMMA", source=MADE),
    # === O. separable verbs (离合词) ================================================================================= #
    seg("ZH-SEP-001", "O", "今天早上她和他见了面。", "见了面", "见 / 了 / 面",
        "见面 is separable (Wiktionary; UD compound:vo, 'known as 離合詞'): split by 了 it is 见 + 了 + 面. jieba's "
        "dictionary holds 见了面 (freq 3), so a non-word lands on the list and 见面 loses the use.",
        "LOCK", decision="ZH-DICTIONARY", source=TAT, refs=(zh("ZH-SEP-01"), kc("ZH-22"))),
    seg("ZH-SEP-002", "O", "我们明天见个面吧。", "见个面", "见 / 个 / 面",
        "见面 split by 个 (Wiktionary separable); 见个面 is an HMM guess.",
        "LOCK", decision="ZH-HMM", source=FIX, refs=(zh("ZH-SEP-02"), kc("ZH-22")), note="HMM off: fixed."),
    seg("ZH-SEP-003", "O", "他洗了个澡就睡觉了。", "洗了个澡", "洗 / 了 / 个 / 澡",
        "洗澡 split by 了个: four tokens, as UD would give.", "LOCK", source=FIX, refs=(zh("ZH-SEP-03"),)),
    seg("ZH-SEP-004", "O", "先洗个热水澡，然后上床睡觉。", "洗个热水澡", "洗 / 个 / 热水澡",
        "洗澡 split by 个 + a modifier; CC-CEDICT 热水澡 'hot bath' is a word — but jieba's dictionary glues the adverb "
        "to the verb (先洗, freq 3, b).",
        "TARGET", decision="ZH-DICTIONARY", source=TAT, refs=(zh("ZH-SEP-04"),)),
    seg("ZH-SEP-005", "O", "他们去年结了婚。", "结了婚", "结 / 了 / 婚",
        "结婚 (Wiktionary separable) split by 了; 结了婚 is a jieba entry, no word.",
        "LOCK", decision="ZH-DICTIONARY", source=FIX, refs=(zh("ZH-SEP-05"),)),
    seg("ZH-SEP-006", "O", "你结过婚吗？", "结过婚", "结 / 过 / 婚",
        "结婚 split by 过; 结过婚 is a jieba entry, no word.",
        "LOCK", decision="ZH-DICTIONARY", source=TAT, refs=(zh("ZH-SEP-06"),)),
    seg("ZH-SEP-007", "O", "别生我的气。", "别生", "别 / 生",
        "The negative imperative 别 + 生 of 生气, split by 我的; 别生 is an HMM guess.",
        "LOCK", decision="ZH-HMM", source=FIX, refs=(zh("ZH-SEP-07"),), note="HMM off: fixed."),
    seg("ZH-SEP-008", "O", "我们一起吃过饭。", "吃过饭", "吃 / 过 / 饭",
        "吃饭 (Wiktionary separable) split by 过; 吃过饭 is a jieba entry.",
        "LOCK", decision="ZH-DICTIONARY", source=FIX, refs=(zh("ZH-SEP-08"),)),
    seg("ZH-SEP-009", "O", "我们午后吃了顿饭。", "吃了顿饭", "吃 / 了 / 顿 / 饭",
        "吃饭 split by 了 + the measure word 顿 (UD 顿: clf); 顿饭 is no CC-CEDICT word (a jieba entry).",
        "TARGET", decision="ZH-DICTIONARY", source=TAT, refs=(zh("ZH-SEP-09"),)),
    seg("ZH-SEP-010", "O", "我上完课很累。", "上完课", "上 / 完 / 课",
        "上课 (CC-CEDICT) split by the result complement 完; 完课 is an HMM guess.",
        "LOCK", decision="ZH-HMM", source=TAT, refs=(zh("ZH-SEP-10"),), note="HMM off: fixed."),
    seg("ZH-SEP-011", "O", "我考完试了。", "考完试", "考 / 完 / 试",
        "考试 split by 完; 考完试 is a jieba entry (even tagged a name, nr), no word.",
        "TARGET", decision="ZH-DICTIONARY", source=MADE, refs=(zh("ZH-SEP-11"),)),
    seg("ZH-SEP-012", "O", "他理了发。", "理了发", "理 / 了 / 发",
        "理发 (CC-CEDICT) split by 了; the HMM also glues the subject (他理).",
        "LOCK", decision="ZH-HMM", source=MADE, refs=(zh("ZH-SEP-12"),), note="HMM off: fixed."),
    seg("ZH-SEP-013", "O", "我们聊了一会儿天。", "一会儿天", "一会儿 / 天",
        "聊天 (Wiktionary separable) split by 了一会儿 (CC-CEDICT 一会儿); 一会儿天 is a jieba entry.",
        "TARGET", decision="ZH-DICTIONARY", source=MADE, refs=(zh("ZH-SEP-13"),)),
    seg("ZH-SEP-014", "O", "你一周洗几次澡？", "洗几次澡", "洗 / 几次 / 澡",
        "洗澡 split by 几次 (CC-CEDICT 几次 'several times').", "LOCK", source=TAT, refs=(zh("ZH-SEP-14"),)),
    Case(id="ZH-SEP-015", lang="zh", layer="tokens_zh", category="O",
         text="他洗了个澡就睡觉了。", span="洗了个澡",
         expect={"words": ["洗澡"]},
         basis="The word list has only tokens: a split 离合词 never counts as the verb the learner studies (洗澡). The "
               "パターン builder reads splits from the sentence string (Z-W5); the list doesn't — crediting the lexeme "
               "is a second count path, not a segmentation fix.",
         status="LIMIT", decision="ZH-LEMMA", source=FIX, refs=(zh("ZH-SEP-15"),)),

    # === O. measure words ========================================================================================= #
    seg("ZH-MSR-001", "O", "我昨天买了一本书，今天又买了三本书。", "一本书", "[一] / 本 / 书",
        "Numeral + measure word + noun (UD 本: clf); jieba reads 本书 'this book' (freq 1,225, not in CC-CEDICT) — 书 "
        "loses the use and 本书 gains it (Z-F5; 三本书 → 三 / 本书).",
        "TARGET", decision="ZH-DICTIONARY", source=FIX, refs=(zh("ZH-MW-01"), kc("ZH-5"), kc("RL-83"))),
    seg("ZH-MSR-002", "O", "我看完了这本书。", "这本书", "这 / 本 / 书",
        "UD 这:DET / 本:NOUN / 书:NOUN ×3; 本书 is a jieba entry.",
        "TARGET", decision="ZH-DICTIONARY", source=FIX, refs=(zh("ZH-MW-02"),)),
    seg("ZH-MSR-003", "O", "我们中午吃了一碗牛肉面。", "一碗", "[一] / 碗",
        "Numeral + measure word: two words (UD 一:NUM / 碗: clf); 一碗 is no CC-CEDICT word (a jieba entry, freq 1,097) "
        "— one of 625 such numeral / demonstrative + measure-word entries.",
        "LOCK", decision="ZH-DICTIONARY", source=FIX, refs=(zh("ZH-MW-03"), kc("RL-83"))),
    seg("ZH-MSR-004", "O", "请来两杯啤酒。", "两杯", "[两] / 杯",
        "Not in CC-CEDICT; UD splits numeral and classifier.", "LOCK", decision="ZH-DICTIONARY", source=TAT,
        refs=(zh("ZH-MW-04"),)),
    seg("ZH-MSR-005", "O", "你有三只猫。", "三只", "[三] / 只",
        "UD 三:NUM / 只:NOUN.", "LOCK", decision="ZH-DICTIONARY", source=TAT, refs=(zh("ZH-MW-05"),)),
    seg("ZH-MSR-006", "O", "香德拉朝我放了一颗黑暗球。", "一颗", "[一] / 颗",
        "UD 一:NUM / 颗:NOUN ×9; not in CC-CEDICT.", "LOCK", decision="ZH-DICTIONARY", source=LIB3,
        refs=(zh("ZH-MW-06"),)),
    seg("ZH-MSR-007", "O", "请唱一首歌。", "一首歌", "[一] / 首 / 歌",
        "Numeral + measure word + noun, fused into one jieba token; three words.", "LOCK", decision="ZH-DICTIONARY",
        source=TAT, refs=(zh("ZH-MW-07"),)),
    seg("ZH-MSR-008", "O", "她问了我们好几个问题。", "好几个", "好几 / 个",
        "CC-CEDICT 好几 'several' + the measure word 个; 好几个 is no dictionary word.", "TARGET",
        decision="ZH-DICTIONARY", source=TAT, refs=(zh("ZH-MW-08"),)),
    Case(id="ZH-MSR-009", lang="zh", layer="tokens_zh", category="O",
         text="一百多个人在一个火车事故中受了伤。", span="一百多个",
         expect={"words": ["个"], "not_words": ["一百多个"]},
         basis="An approximate numeral + the measure word: UD keeps the numeral one NUM and the classifier apart; "
               "一百多个 is a jieba entry. (What the numeral itself counts as is ZH-NUMERALS.)",
         status="TARGET", decision="ZH-DICTIONARY", source=TAT, refs=(zh("ZH-MW-09"),)),
    seg("ZH-MSR-010", "O", "这次的咏唱很长，看来她打算施展强大的魔法。", "这次", "这 / 次",
        "UD 这:DET / 次:NOUN ×17 (这次:DET ×1); not in CC-CEDICT (a jieba entry, freq 9,832).", "LOCK",
        decision="ZH-DICTIONARY", source=LIB4, refs=(zh("ZH-MW-10"),)),
    seg("ZH-MSR-011", "O", "我是第一名。", "第一名", "第一 / 名",
        "UD 第一:NUM / 名:NOUN ×2; not in CC-CEDICT.", "TARGET", decision="ZH-DICTIONARY", source=TAT,
        refs=(zh("ZH-MW-11"),)),
    seg("ZH-MSR-012", "O", "桌子上有两本书和一个杯子。", "一个", "[一] / 个",
        "CC-CEDICT lists 一个 'a; an; one' as a word; UD splits it (一:NUM / 个: clf ×342). jieba keeps it whole (and 两个, "
        "三个 …, which CC-CEDICT doesn't list). A learner's list: one word 'a', or the numeral and 个?",
        "LOCK", decision="ZH-DICTIONARY", source=FIX, refs=(zh("ZH-MW-12"),)),
    seg("ZH-MSR-013", "O", "红萝卜好讨厌，为什么它要存在这个世界上呢？", "这个", "这个",
        "CC-CEDICT 这个 '(pronoun) this; (adjective) this' is one word; UD splits it (这:DET / 个: clf ×74), but it holds "
        "no numeral, so the dictionary wins (ZH-DICTIONARY): only a numeral + measure word is a count.",
        "LOCK", decision="ZH-DICTIONARY", source=LIB3, refs=(zh("ZH-MW-13"),),
        note="Expectation corrected 2026-09-29 (was 这 / 个, the treebanks' cut) when ZH-DICTIONARY was decided."),
    seg("ZH-MSR-014", "O", "「可以请你稍等一下吗？」", "稍等一下", "稍等 / 一下",
        "CC-CEDICT 稍等 and 一下 (UD 一下:ADV ×7) — two words; jieba's dictionary holds 稍等一下 (freq 3).", "TARGET",
        decision="ZH-DICTIONARY", source=LIB1, refs=(zh("ZH-MW-14"),)),
    seg("ZH-MSR-015", "O", "我瞥了他一眼。", "一眼", "一眼",
        "CC-CEDICT 一眼 'a glance' — a verbal measure word lexicalised with 一.", "LOCK", source=TAT,
        refs=(zh("ZH-MW-15"),)),
    seg("ZH-MSR-016", "O", "他有两个朋友。", "两个", "[两] / 个",
        "Not in CC-CEDICT; UD 两:NUM / 个: clf ×37 — and with a digit (我有2个苹果) the list counts 个, so the "
        "numeral's script changes the vocabulary.", "LOCK", decision="ZH-DICTIONARY", source=MADE,
        refs=(zh("ZH-MW-16"),)),
    seg("ZH-MSR-017", "O", "每个人都来了。", "每个", "每个",
        "CC-CEDICT 每个 'each; every', and UD keeps it one DET (每个:DET ×17; 每:DET / 个:NOUN ×3): a unit dictionary "
        "and treebank agree on.", "LOCK", decision="ZH-DICTIONARY", source=MADE, refs=(kc("RL-83"),)),

    seg("ZH-MSR-401", "O", "我们一起去吧。", "一起", "一起",
        "CC-CEDICT 一起 'together' — a word the treebanks keep whole (一起 59 whole / 1 cut): a numeral + a measure-word "
        "shape that is no count stays one word.", "LOCK", decision="ZH-DICTIONARY", source=MADE),
    seg("ZH-MSR-402", "O", "我们的想法都一样。", "一样", "一样",
        "CC-CEDICT 一样 'same' — kept whole by the treebanks (38 / 0).", "LOCK", decision="ZH-DICTIONARY", source=MADE),
    seg("ZH-MSR-403", "O", "请给我一些水。", "一些", "一些",
        "CC-CEDICT 一些 'some; a few' — kept whole by the treebanks (82 / 0).", "LOCK", decision="ZH-DICTIONARY",
        source=MADE),
    seg("ZH-MSR-404", "O", "他一次也没来过。", "一次", "[一] / 次",
        "CC-CEDICT lists 一次 'first; once', but the treebanks cut it after the numeral in every use they hold (35 / 0): "
        "a numeral + the verbal measure word 次, a count, kept apart as Japanese counts are (ZH-DICTIONARY).",
        "LOCK", decision="ZH-DICTIONARY", source=MADE,
        note="Z5 then drops the numeral: expectation → [一] / 次 when it lands."),
    # === numerals and dates ======================================================================================== #
    seg("ZH-NUM-001", "D", "今天是６月１８号，也是Muiriel的生日！", "６月", "[６] / 月",
        "A full-width digit is dropped exactly like an ASCII one; the word is 月.", "LOCK", source=TAT,
        refs=(zh("ZH-NUM-01"),)),
    seg("ZH-NUM-002", "D", "今天是2026年9月26日。", "2026年", "[2026] / 年",
        "Digits are no vocabulary; 年 is the word.", "LOCK", source=MADE, refs=(zh("ZH-NUM-02"),)),
    Case(id="ZH-NUM-003", lang="zh", layer="tokens_zh", category="C",
         text="今天是二〇一六年十一月二十三日。", span="二〇一六年",
         expect={"words": ["年"], "not_words": ["六年"]},
         basis="〇 (U+3007 IDEOGRAPHIC NUMBER ZERO; CC-CEDICT 〇 'zero') is a numeral character outside the tokenizer's "
               "range [一-鿿]: it is dropped, and jieba reads 六年 'six years' in a date (before F7: 二 / [〇] / 一 / 六年).",
         status="TARGET", decision="ZH-HAN-RANGE", source=TAT, refs=(zh("ZH-NUM-03"), kc("RL-86")),
         note="F7 (2026-09-27): 〇 is Han to the tokenizer now (二 / 〇 / 一 / 六年); jieba's own Han range (to "
              "U+9FD5) still cuts the date at 〇, so 一六年 is segmented alone and 六年 remains. Whether a numeral is a "
              "list word is ZH-NUMERALS."),
    Case(id="ZH-NUM-004", lang="zh", layer="tokens_zh", category="O",
         text="一九七二年生的。", span="一九七二年",
         expect={"words": ["年"], "not_words": ["一九七二年"]},
         basis="A year written in characters is numeral + 年, as with digits (ZH-NUM-002): UD splits NUM + 年 ×1,494 and "
               "keeps it one token ×8; 一九七二年 is a jieba entry.",
         status="TARGET", decision="ZH-DICTIONARY", source=TAT, refs=(zh("ZH-NUM-04"),)),
    Case(id="ZH-NUM-005", lang="zh", layer="tokens_zh", category="O",
         text="我二十五岁了。", span="二十五岁",
         expect={"words": ["岁"], "not_words": ["二十五岁"]},
         basis="UD 二十五:NUM / 岁:NOUN (a numeral + 岁 split ×66, one token ×3); not in CC-CEDICT — a jieba entry, so "
               "岁 loses the use.",
         status="LOCK", decision="ZH-DICTIONARY", source=TAT, refs=(zh("ZH-NUM-05"),)),
    seg("ZH-NUM-006", "O", "现在是下午三点半。", "三点半", "[三] / 点 / 半",
        "A number + the measure word 点 'o'clock' is a count (ZH-DICTIONARY's count rule, as Japanese 三時 is 三 + 時): "
        "CC-CEDICT lists no 三点, so jieba's entry is read as its words. UD keeps a clock time one noun (三点:NOUN ×2, "
        "like 三月) — moved on purpose with the count rule (2026-09-30).", "LOCK", source=MADE,
        refs=(zh("ZH-NUM-06"),)),
    Case(id="ZH-NUM-007", lang="zh", layer="tokens_zh", category="O",
         text="第三十二届奥运会。", span="第三十二届",
         expect={"words": ["届"], "not_words": ["第三十二届"]},
         basis="An ordinal numeral + the measure word 届; 第三十二届 is a jieba entry.",
         status="LOCK", decision="ZH-DICTIONARY", source=MADE, refs=(zh("ZH-NUM-07"),)),
    Case(id="ZH-NUM-008", lang="zh", layer="tokens_zh", category="D",
         text=BUDGET, span="三千五百",
         expect={"seg": "[三千五百]", "not_words": ["三千五百"]},
         basis="A number written in characters is no word (ZH-NUMERALS, as NUMERALS-NOT-WORDS for Japanese): neither "
               "the whole 三千五百 nor any character of it (三, 千, 五, 百) counts — the digits (2005) never did. UD / CTB "
               "keep a numeral one token (五万三千:NUM), but no dictionary lists it as a word.",
         status="LOCK", decision="ZH-NUMERALS", source=WIKI, refs=(zh("ZH-NUM-08"),),
         note="Expectation tightened 2026-09-29 (was not_words 三千五百 only, which the split alone passes by cutting it "
              "into 三 / 千 / 五 / 百 — the 'its characters' option the decision turned down)."),
    Case(id="ZH-NUM-009", lang="zh", layer="tokens_zh", category="O",
         text="我等了十几分钟。", span="十几分钟",
         expect={"words": ["分钟"], "not_words": ["十几分钟"]},
         basis="CC-CEDICT 十几 'more than ten' + 分钟; 十几分钟 is a jieba entry (freq 194).",
         status="TARGET", decision="ZH-DICTIONARY", source=MADE, refs=(zh("ZH-NUM-09"),)),
    seg("ZH-NUM-010", "D", "平均年龄为43.5岁。", "43.5岁", "[43.5] / 岁",
        "The decimal stays one dropped token; 岁 is the word.", "LOCK", source=WIKI, refs=(zh("ZH-NUM-10"),)),
    seg("ZH-NUM-011", "O", "这是在两千年。", "两千年", "两千年",
        "CC-CEDICT 两千年 'the year 2000' — a date here, one dictionary word.", "LOCK", source=TAT,
        refs=(zh("ZH-NUM-11"),)),
    Case(id="ZH-NUM-012", lang="zh", layer="tokens_zh", category="D",
         text="台灣經濟部今天公布最新統計，今年第二季出口金額比去年同期成長百分之十二。", span="百分之十二",
         expect={"words": ["百分之"], "not_words": ["百分之十二", "十二"]},
         basis="CC-CEDICT 百分之 'percent' is a word; the numeral after it counts nothing a learner studies "
               "(ZH-NUMERALS) — jieba fuses the percentage (a jieba entry; CTB keeps it one CD).",
         status="TARGET", decision="ZH-NUMERALS", source=TWN, ctx={"script": "s"}, refs=(zh("ZH-NUM-12"),),
         note="Expectation tightened 2026-09-29 (十二 added to not_words: the split alone leaves it a word)."),
    Case(id="ZH-NUM-013", lang="zh", layer="tokens_zh", category="O",
         text=BUDGET, span="万美元",
         expect={"words": ["美元"], "not_words": ["万美元"]},
         basis="万 belongs to the numeral (四亿三千五百万 'four hundred thirty-five million'); CC-CEDICT 美元 'US dollar'. "
               "Whatever the numeral policy, 万美元 is no word — jieba's dictionary glues the multiplier to the unit "
               "(freq 2,034).",
         status="LOCK", decision="ZH-DICTIONARY", source=WIKI, refs=(zh("ZH-NUM-13"),)),
    seg("ZH-NUM-014", "O", "十二月很冷。", "十二月", "十二月",
        "CC-CEDICT 十二月 'December' — a month name, one word.", "LOCK", source=MADE, refs=(kc("RL-83"),)),

    Case(id="ZH-NUM-401", lang="zh", layer="tokens_zh", category="D", text="你千万别忘了。", span="千万",
         expect={"words": ["千万"]},
         basis="千万 'by all means' (CC-CEDICT, beside 'ten million') is a word whose numerals count nothing — it stays a "
               "word (ZH-NUMERALS, as JT-NUMERAL-WORDS keeps 十八番).", status="LOCK", decision="ZH-NUMERALS",
         source=MADE),
    Case(id="ZH-NUM-402", lang="zh", layer="tokens_zh", category="D", text="万一下雨怎么办？", span="万一",
         expect={"words": ["万一"]},
         basis="万一 'just in case' (CC-CEDICT) counts nothing: a word.", status="LOCK", decision="ZH-NUMERALS",
         source=MADE),
    Case(id="ZH-NUM-403", lang="zh", layer="tokens_zh", category="D", text="我数到十一。", span="十一",
         expect={"not_words": ["十一"]},
         basis="十一 'eleven' is a number, no word (CC-CEDICT's other 十一, 'National Day', is a name).",
         status="LOCK", decision="ZH-NUMERALS", source=MADE,
         note="If --show finds jieba fuses 十一 with its neighbour, pick a line where it stands alone."),
    Case(id="ZH-NUM-404", lang="zh", layer="tokens_zh", category="D", text="他把钱包拾了起来。", span="拾",
         expect={"words": ["拾"]},
         basis="拾 'to pick up' is a word; it is also the financial form of 十, which Unicode numbers (10) — the numeral "
               "test is GB/T 15835's numerals, never the financial forms.", status="LOCK", decision="ZH-NUMERALS",
         source=MADE),
    Case(id="ZH-NUM-405", lang="zh", layer="tokens_zh", category="D", text="你真是个二百五。", span="二百五",
         expect={"words": ["二百五"]},
         basis="二百五 'idiot' (CC-CEDICT) is written in numerals and counts nothing: a word.", status="LOCK",
         decision="ZH-NUMERALS", source=MADE,
         note="If jieba cuts it (二百 / 五), this is TARGET for the join question, not the numeral test."),
    # === O. chengyu ================================================================================================ #
    seg("ZH-IDM-001", "O", "一石二鸟。", "一石二鸟", "一石二鸟",
        "CC-CEDICT idiom, one word (93% of CC-CEDICT's 4,957 Simplified four-character idioms are kept whole).",
        "LOCK", source=TAT, refs=(zh("ZH-IDIOM-01"),)),
    seg("ZH-IDM-002", "O", "实事求是。", "实事求是", "实事求是", "CC-CEDICT idiom.", "LOCK", source=TAT,
        refs=(zh("ZH-IDIOM-02"),)),
    seg("ZH-IDM-003", "O", "井底之蛙。", "井底之蛙", "井底之蛙", "CC-CEDICT idiom.", "LOCK", source=TAT,
        refs=(zh("ZH-IDIOM-04"),)),
    seg("ZH-IDM-004", "O", "在实战中，你要知道三心二意是很危险的。", "三心二意", "三心二意", "CC-CEDICT idiom.",
        "LOCK", source=TAT, refs=(zh("ZH-IDIOM-05"),)),
    seg("ZH-IDM-005", "O", "他做事总是马马虎虎的。", "马马虎虎", "马马虎虎",
        "CC-CEDICT 马马虎虎 — an idiomatic AABB, one word.", "LOCK", source=MADE, refs=(zh("ZH-IDIOM-06"),)),
    seg("ZH-IDM-006", "O", LIB1_SEAL, "不得其门而入", "不得其门而入",
        "CC-CEDICT 不得其门而入 'to be unable to get in' — one idiom; today 不得 + two HMM non-words (其门, 而入).",
        "TARGET", decision="ZH-COMPOUND-JOIN", source=LIB1, refs=(zh("ZH-IDIOM-07"),),
        note="HMM off: 不得 / 其 / 门 / 而 / 入 — still no idiom (jieba lacks it)."),
    seg("ZH-IDM-007", "O", "每次这两个人一吵架，都会让我受到池鱼之殃。", "池鱼之殃", "池鱼之殃",
        "A 成语 (池鱼之殃 'the fish in the pond suffer' — 成语词典; CC-CEDICT lacks it and 殃及池鱼) — one word.",
        "LOCK", source=LIB2, refs=(zh("ZH-IDIOM-08"),), note="Its words 池鱼 / 之 / 殃 would be as right; a fusion never."),
    seg("ZH-IDM-008", "O", "那裡人山人海。", "人山人海", "人山人海",
        "CC-CEDICT idiom — survives a Traditional neighbour (那裡) under as-is.", "LOCK", source=TAT,
        refs=(zh("ZH-IDIOM-09"),)),
    seg("ZH-IDM-009", "O", "他说得天花乱坠。", "天花乱坠", "天花乱坠", "CC-CEDICT idiom.", "LOCK", source=MADE,
        refs=(zh("ZH-IDIOM-10"),)),

    # === O. script (繁简) — seeded by the framework ================================================================ #
    Case(id="ZH-SCR-001", lang="zh", layer="tokens_zh", category="O",
         text="為什麼？", span="為什麼",
         expect={"seg": "為什麼"},
         basis="CC-CEDICT 為什麼 'why' — one word. Under the default as-is setting jieba's Simplified dictionary "
               "doesn't know it and cuts 為 / 什麼; segmenting through Simplified fixes it but changes as-is output.",
         status="LOCK", decision="ZH-TRAD-ASIS", source="corpus: Tatoeba cmn (CC BY 2.0 FR)",
         refs=("Chinese_Script_Conversion_Spec.md I2", "debug/parsing_suite/zh ZH-SCRIPT-18"),
         note="As-is through Simplified: 為什麼 (fixed); HMM off: 為 / 什 / 麼."),
    Case(id="ZH-SCR-002", lang="zh", layer="tokens_zh", category="O",
         text="我覺得這個價格很合理。", span="我覺得",
         expect={"seg": "我 / 覺得"},
         basis="CC-CEDICT 覺得 'to think' after the pronoun 我; read as Traditional (the script setting 't') the "
               "text is segmented in Simplified, so the words come right and stay Traditional.",
         status="LOCK", source="constructed", ctx={"script": "t"},
         refs=("Chinese_Script_Conversion_Spec.md §5.3", "debug/parsing_suite/zh ZH-SCRIPT-20")),

    # --- the conversion itself (zh_script.convert) ----------------------------------------------------------------- #
    conv("ZH-SCR-003", "头发", "发", "t", "頭髮",
         "发 is 發 (emit) or 髮 (hair): OpenCC's phrase table picks 髮 in 头发 'hair'.", "LOCK", source=MADE,
         refs=(zh("ZH-SCRIPT-01"), "tests/test_zh_script.py::test_known_pairs_convert_both_ways", kc("ZH-70"))),
    conv("ZH-SCR-004", "发现", "发", "t", "發現", "发 = 發 in 发现 'discover'.", "LOCK", source=MADE,
         refs=(zh("ZH-SCRIPT-02"), "tests/test_zh_script.py::test_known_pairs_convert_both_ways")),
    conv("ZH-SCR-005", "理发", "发", "t", "理髮", "理发 'a haircut': 髮.", "LOCK", source=MADE,
         refs=(zh("ZH-SCRIPT-03"),)),
    conv("ZH-SCR-006", "以后 · 皇后", "后", "t", "以後 · 皇后", "后 is 後 (after) or 后 (empress).", "LOCK",
         source=MADE, refs=(zh("ZH-SCRIPT-04"),)),
    conv("ZH-SCR-007", "干净 · 干部 · 干杯 · 若干 · 干涉", "干", "t", "乾淨 · 幹部 · 乾杯 · 若干 · 干涉",
         "干 has three Traditional sources: 乾 (dry), 幹 (do; trunk), 干 (interfere, 若干).", "LOCK", source=MADE,
         refs=(zh("ZH-SCRIPT-05"), kc("ZH-70"))),
    conv("ZH-SCR-008", "公里 · 里面", "里", "t", "公里 · 裡面",
         "The unit 里 stays; 'inside' is 裡 in Taiwan (教育部 standard). OpenCC's standard form 裏 was what Q2's generic "
         "Traditional gave; Taiwan's standard characters write 裡 (ZH-S2T-CHI, built 2026-09-30).", "LOCK",
         decision="ZH-S2T-CHI", source=MADE, refs=(zh("ZH-SCRIPT-06"),)),
    conv("ZH-SCR-009", "我们", "们", "t", "我們", "One-to-one.", "LOCK", source=MADE, refs=(zh("ZH-SCRIPT-07"),)),
    conv("ZH-SCR-010", "面条 · 方面", "面", "t", "麵條 · 方面",
         "Taiwan and Hong Kong write 麵 for noodles; OpenCC's standard form is 麪 — Taiwan's standard characters write "
         "麵 (ZH-S2T-CHI, built 2026-09-30).", "LOCK", decision="ZH-S2T-CHI", source=MADE, refs=(zh("ZH-SCRIPT-08"), kc("ZH-72"))),
    conv("ZH-SCR-011", "关系 · 联系 · 系统 · 系鞋带", "系", "t", "關係 · 聯繫 · 系統 · 繫鞋帶",
         "系 has three Traditional sources, each right in its phrase.", "LOCK", source=MADE,
         refs=(zh("ZH-SCRIPT-09"),)),
    conv("ZH-SCR-012", "一只猫 · 只有", "只", "t", "一隻貓 · 只有",
         "The measure word is 隻; 'only' stays 只 (Z-F6: OpenCC needs the numeral to see the measure word).", "LOCK",
         source=MADE, refs=(zh("ZH-SCRIPT-10"),)),

    # --- 著 and variants that to_simplified leaves ---------------------------------------------------------------- #
    seg("ZH-SCR-013", "O", "我不著急。", "著急", "着急",
        "CC-CEDICT pairs 著急 (Traditional) with 着急 (Simplified); the Simplified setting exists to merge them, but "
        "to_simplified leaves 著 (a Simplified character too: 著名), so 著急 is cut 著 / 急 and never meets 着急.",
        "LOCK", decision="ZH-ZHE-READING", source=TAT, ctx={"script": "s"}, refs=(zh("ZH-SCRIPT-11"), kc("ZH-74"))),
    seg("ZH-SCR-014", "O", "他正看著電視。", "看著", "看 / 着",
        "The aspect marker 著 = 着 (Z-F6: the パターン builder reads 著 after a verb as 着, the analyzer doesn't) — under "
        "the Simplified setting the list keeps a word 著 beside 着.",
        "TARGET", decision="ZH-ZHE-READING", source=FIXT, ctx={"script": "s"}, refs=(zh("ZH-SCRIPT-12"), kc("ZH-74"))),
    seg("ZH-SCR-015", "O", "孩子睡著了。", "睡著", "睡着",
        "CC-CEDICT 睡著 / 睡着 [shui4 zhao2]: one word in both scripts; under s Traditional text gives 睡著.",
        "LOCK", decision="ZH-ZHE-READING", source=MADE, ctx={"script": "s"}, refs=(zh("ZH-SCRIPT-13"),)),
    seg("ZH-SCR-016", "O", "新法案受到衞生專家的歡迎。", "衞生", "卫生",
        "衞 is CC-CEDICT's 'variant of 衛|卫' (the Hong Kong form); to_simplified leaves it, and jieba cuts 衞 / 生.",
        "TARGET", source=WN, ctx={"script": "s"}, refs=(zh("ZH-SCRIPT-14"),)),
    seg("ZH-SCR-017", "O", "吃飯。", "吃飯", "吃飯",
        "Taiwan and Hong Kong write 吃 (教育部 standard); OpenCC's s2t gives 喫 (CC-CEDICT: 'variant of 吃'), so under "
        "the Traditional setting every 吃 in the report and the Traditional パターン reads 喫 — one of the commonest "
        "verbs.", "LOCK", decision="ZH-S2T-CHI", source=TAT, ctx={"script": "t"}, refs=(zh("ZH-SCRIPT-15"),)),
    conv("ZH-SCR-018", "范先生 · 我姓余", "范", "t", "范先生 · 我姓余",
         "The surnames 范 and 余 are written 范 / 余 in Traditional (CC-CEDICT 余 'surname Yu'); out of context OpenCC "
         "gives 範 / 餘 — the residual S→T error the spec accepts (gotcha 7).", "LIMIT", decision="ZH-OPENCC-FORMS",
         source=MADE, refs=(zh("ZH-SCRIPT-16"),)),
    conv("ZH-SCR-019", "郁达夫是作家。", "郁", "t", "郁達夫是作家。",
         "The surname 郁 stays 郁 (not 鬱) inside the writer's name — a phrase OpenCC knows.", "LOCK", source=MADE,
         refs=(zh("ZH-SCRIPT-17"),)),

    # --- Traditional text under the default as-is ------------------------------------------------------------------ #
    seg("ZH-SCR-020", "O", "氣象署提醒，下週起天氣轉涼，洗完頭髮記得吹乾，出門多穿一件外套。", "頭髮", "頭髮",
        "CC-CEDICT 頭髮 'hair' — as ZH-SCR-001: the default as-is reads Traditional text through jieba's Simplified "
        "dictionary, character by character here.",
        "LOCK", decision="ZH-TRAD-ASIS", source=TWN, refs=(zh("ZH-SCRIPT-19"),),
        note="As-is through Simplified: 頭髮 (fixed)."),
    seg("ZH-SCR-021", "O", "我覺得這個價格很合理。", "我覺得", "我 / 覺得",
        "CC-CEDICT 覺得 'to think'; under as-is the HMM glues 我覺 and leaves 得 (the Simplified line of the same "
        "fixture gives 我 / 觉得; ZH-SCR-002 is this line under t).",
        "LOCK", decision="ZH-TRAD-ASIS", source="constructed: the Traditional of mixed_script_transcript.txt's line",
        refs=(zh("ZH-SCRIPT-20"),), note="As-is through Simplified: 我 / 覺得 (fixed)."),
    seg("ZH-SCR-022", "O", "他在房間裡面。", "裡面", "裡面",
        "The Traditional setting emitted OpenCC's standard 裏面, not the Taiwan 裡面 the text wrote (Q2); Taiwan's "
        "standard characters keep 裡面 (ZH-S2T-CHI, built 2026-09-30).", "LOCK", decision="ZH-S2T-CHI", source=MADE, ctx={"script": "t"}, refs=(zh("ZH-SCRIPT-21"),)),
    seg("ZH-SCR-023", "O", "這個軟體很好用。", "軟體", "软体",
        "Taiwan's 軟體 and the PRC's 软件 are different words for 'software'; t2s changes the script, not the "
        "vocabulary (Q2: regional phrasing out of scope) — 软体 is 軟體 in Simplified.",
        "LOCK", decision="ZH-OPENCC-FORMS", source=MADE, ctx={"script": "s"}, refs=(zh("ZH-SCRIPT-22"), kc("ZH-73"))),
    conv("ZH-SCR-024", "乾隆 · 乾坤 · 瞭望", "乾", "s", "乾隆 · 乾坤 · 瞭望",
         "qián in 乾隆 / 乾坤 and liào in 瞭望 are not simplified — OpenCC's phrases.", "LOCK", source=MADE,
         refs=(zh("ZH-SCRIPT-23"),)),
    conv("ZH-SCR-025", "裡面 · 裏面 · 麵條 · 麪條", "裡", "s", "里面 · 里面 · 面条 · 面条",
         "The Simplified setting puts both Traditional variants on one Simplified word.", "LOCK", source=MADE,
         refs=(zh("ZH-SCRIPT-24"),)),
    seg("ZH-SCR-026", "O", "我祇有一個。", "祇有", "只有",
        "CC-CEDICT 祇 'variant of 只': read as Simplified, 我祇有一個 is 我只有一个 — 只有 'only', one word as the "
        "Simplified text gives it. t2s leaves 祇 (also qí, 神祇), so 祇有 stays apart from 只有.",
        "LIMIT", decision="ZH-OPENCC-FORMS", source=MADE, ctx={"script": "s"}, refs=(zh("ZH-SCRIPT-25"),),
        note="The adversary's row expected 只 / 有; 只有 is the word (CC-CEDICT 只有, jieba one token)."),
    seg("ZH-SCR-027", "O", "我們一起去臺灣旅遊。", "臺灣旅遊", "臺灣 / 旅遊",
        "CC-CEDICT 臺灣 'Taiwan' + 旅遊 'travel'; as-is on Traditional text jieba gives 臺 / 灣旅遊 (under s: 台湾 / 旅游).",
        "LOCK", decision="ZH-TRAD-ASIS", source=MADE, refs=(zh("ZH-SCRIPT-26"),),
        note="As-is through Simplified: fixed."),
    seg("ZH-SCR-028", "O",
        "中方通报把“臺湾”置于最优先位置，称习近平在电话中直言臺湾问题是中美关系中“最重要的问题”", "臺湾", "臺湾",
        "A mixed-script spelling in a Simplified article (BBC): one word, 'Taiwan'. Under as-is jieba knows neither "
        "臺湾 nor 臺 as a word (under s: 台湾, with 臺湾 an alias of the パターン key) — the ZH-SCR-001 decision.",
        "LOCK", decision="ZH-TRAD-ASIS", source=BBC, refs=(zh("ZH-SCRIPT-27"), kc("ZH-83")),
        note="As-is through Simplified: fixed."),
    Case(id="ZH-SCR-029", lang="zh", layer="text", category="O",
         text=NOODLES, span="",
         expect={"words": ["牛肉麵"], "not_words": ["牛肉麪"]},
         basis="One dish (CC-CEDICT 牛肉麵 / 牛肉面): the Traditional setting merges the file's two spellings — as "
               "Taiwan's 牛肉麵 since ZH-S2T-CHI was built (2026-09-30); before, as OpenCC's standard 牛肉麪, a form "
               "CC-CEDICT doesn't list and Taiwan doesn't write.",
         status="LOCK", decision="ZH-S2T-CHI", source=MIX, ctx={"script": "t"},
         refs=(zh("ZH-SCRIPT-28"), kc("ZH-68"), "Chinese_Script_Conversion_Spec.md §12")),
    Case(id="ZH-SCR-030", lang="zh", layer="text", category="O",
         text=NOODLES, span="",
         expect={"words": ["牛肉面"], "not_words": ["牛肉麵", "牛肉"]},
         basis="Read as Simplified, the Traditional line's 牛肉麵 and the Simplified line's 牛肉面 are one word, counted "
               "twice (the setting's whole point).",
         status="LOCK", source=MIX, ctx={"script": "s"},
         refs=(zh("ZH-SCRIPT-28"), "tests/test_zh_script.py::test_a_word_from_either_script_lands_on_one_spelling",
               "tests/test_zh_script_tokenizer.py::test_a_mixed_library_counts_each_word_once")),
    seg("ZH-SCR-031", "O", "經濟關係的發展很重要。", "經濟關係", "經濟 / 關係",
        "CC-CEDICT 經濟 'economy' + 關係 'relations'; as-is, jieba's Simplified dictionary cuts 經濟關 / 係.",
        "LOCK", decision="ZH-TRAD-ASIS", source=MADE,
        refs=(kc("ZH-6"), "tests/test_zh_script_tokenizer.py::test_t_segments_traditional_text_better_than_as_is")),
    seg("ZH-SCR-032", "O", "經濟關係的發展很重要。", "經濟關係", "經濟 / 關係",
        "Under t the text is segmented in Simplified (经济 / 关系) and sliced from the Traditional — right, in the "
        "script it was written in.",
        "LOCK", source=MADE, ctx={"script": "t"},
        refs=(kc("ZH-6"), "tests/test_zh_script_tokenizer.py::test_t_segments_traditional_text_better_than_as_is")),
    conv("ZH-SCR-033", "一位里長說，希望政府准許延長", "里長", "t", "一位里長說，希望政府准許延長",
         "里 and 准 are ordinary Traditional characters too (里長 'village chief', 准許 'permit'); read straight from "
         "the Traditional, OpenCC 'corrected' them to 裏長 / 準許 — through Simplified they keep their meaning.",
         "LOCK", source=MADE,
         refs=(kc("ZH-69"), "tests/test_zh_script.py::test_shared_characters_keep_their_traditional_meaning")),
    conv("ZH-SCR-034", "我买了一台电脑。", "台", "t", "我買了一台電腦。",
         "The measure word for machines is 台 in Taiwan; OpenCC's standard gives 臺 (一臺電腦).", "LIMIT",
         decision="ZH-OPENCC-FORMS", source=MADE, refs=(kc("ZH-72"),)),
    conv("ZH-SCR-035", "U盘", "盘", "t", "U盤",
         "U盘 'USB stick': OpenCC's Taiwan table writes 隨身碟 — a length-changing entry that would shift every offset "
         "after it (I3), so the build drops it and the character converts: U盤.", "LOCK", source=MADE,
         refs=(kc("ZH-79"),
               "tests/test_zh_script.py::test_build_script_drops_unequal_length_entries_and_writes_a_decodable_module")),
    conv("ZH-SCR-036", "為什麼？", "為什麼", "tw", "為什麼？",
         "An unknown zh_script value (a hand-edited 'tw') reads as as-is: the text as written, never a crash or a "
         "guess.", "LOCK", source=MADE,
         refs=(kc("ZH-80"), "tests/test_zh_script.py::test_effective_script",
               "tests/test_zh_script_tokenizer.py::test_an_unknown_script_value_is_as_is")),
    conv("ZH-SCR-037", "乾淨 · 幹部", "乾", "s", "干净 · 干部",
         "t2s is many-to-one: 乾 (dry) and 幹 (do) are both 干 in Simplified — one word read as Simplified, whose "
         "frequency rank is the commoner spelling's.", "LOCK", source=MADE,
         refs=(kc("ZH-71"), "tests/test_zh_script_analysis.py::"
                            "test_frequency_list_keys_convert_and_merged_spellings_keep_the_commoner_rank")),

    # --- C. kana in Chinese content ---------------------------------------------------------------------------------- #
    Case(id="ZH-SCR-038", lang="zh", layer="tokens_zh", category="C",
         text="私は学生です。", span="学生",
         expect={"not_words": ["学生"]},
         basis="A Japanese sentence is no Chinese text: its kanji words (私, 学生) are Japanese ones. jieba cuts every "
               "kana off the Han runs, so the kana filter never fires and has_target_language('zh') is 'any CJK'.",
         status="LIMIT", decision="ZH-CJK-TOKENS", source=MADE, refs=(zh("ZH-LANG-07"), kc("RL-99"))),
    seg("ZH-SCR-039", "C", "今天の晚餐超好吃", "の", "[の]",
        "In content a kana token is never a Chinese word: Taiwanese の (for 的) is dropped, its neighbours kept.",
        "LOCK", source=MADE, refs=(zh("ZH-LANG-08"),)),

    # === O. Cantonese ============================================================================================== #
    seg("ZH-YUE-001", "O", "再次感謝各位觀衆嘅支持。", "嘅", "嘅",
        "CC-CEDICT 嘅 'possessive particle (Cantonese)' — counted as its own word, never read as 的.", "LOCK",
        decision="ZH-CANTONESE-OUT", source=WN, refs=(zh("ZH-CANT-01"),)),
    seg("ZH-YUE-002", "O", CANTONESE, "我哋", "我哋",
        "Cantonese 我哋 'we' is one word; jieba (a Mandarin dictionary) cuts 我 / 哋 and counts 哋.", "LIMIT",
        decision="ZH-CANTONESE-OUT", source=WN, refs=(zh("ZH-CANT-02"),)),
    seg("ZH-YUE-003", "O", "「人走後便冇嘢㗎啦。", "㗎", "㗎",
        "㗎 (U+35CE, CJK Extension A) is a Cantonese particle, a Chinese character: counted as written, like 嘅 "
        "(ZH-YUE-001).", "LOCK",
        decision="ZH-CANTONESE-OUT", source=WIKI, refs=(zh("ZH-CANT-03"), kc("RL-86")),
        note="F7 (2026-09-27): the tokenizer's range was [一-鿿] and dropped it silently (a LIMIT under "
             "ZH-CANTONESE-OUT); it is Unicode's Han ranges now (app/unicode_ranges.py)."),
    seg("ZH-YUE-004", "O", "唔該晒。", "唔該晒", "唔該晒",
        "Cantonese 晒 'all; completely'; under the Traditional setting it becomes 曬 (sun-dry) — Mandarin tables.",
        "LIMIT", decision="ZH-CANTONESE-OUT", source=MADE, ctx={"script": "t"}, refs=(zh("ZH-CANT-04"),)),
    seg("ZH-YUE-005", "O", "佢係我朋友。", "係", "係",
        "The Cantonese copula 係 'to be'; t2s maps it to 系 (right for Mandarin 關係 → 关系), so under t the Cantonese "
        "word becomes 系 (OpenCC keeps 我係香港人 — context-dependent).", "LIMIT", decision="ZH-CANTONESE-OUT",
        source=MADE, ctx={"script": "t"}, refs=(zh("ZH-CANT-05"),)),
    seg("ZH-YUE-006", "O", CANTONESE, "犯咗法", "犯 / 咗 / 法",
        "CC-CEDICT 咗 'Cantonese particle equivalent to 了': the verb, the aspect particle, the object.", "LOCK",
        decision="ZH-CANTONESE-OUT", source=WN, refs=(zh("ZH-CANT-06"),)),
    seg("ZH-YUE-007", "O", "第一我未必有、第二我冇講出來，第三你估我冇諗乜嘢？", "冇講出來", "冇 / 講 / 出來",
        "CC-CEDICT 冇 'to not have (Cantonese)' — the negation + 講 'say' + the complement 出來.", "LOCK",
        decision="ZH-TRAD-ASIS", source=WN, refs=(zh("ZH-CANT-07"),),
        note="As-is through Simplified gives 冇 / 講 / 出來 — the ZH-TRAD-ASIS question."),

    # === B. sentence ends (text: a .txt file, or a subtitle) ======================================================== #
    Case(id="ZH-SPL-001", lang="zh", layer="text", category="B", text="“是黑车吗？”我问他。", span="”",
         expect={"sentences": ["“是黑车吗？”", "我问他。"]},
         basis="A closing quotation mark belongs to the sentence it closes (GB/T 15834-2011, 引号; UAX #29 SB9); the "
               "second example used to start with ” (the Japanese tokenizer strips 」』” from a sentence's start, the "
               "Chinese one doesn't).",
         status="LOCK", source=TAT, refs=(zh("ZH-BOUND-01"), kc("SD-28"), "F4 (ChineseTokenizer.tokenize_sentences)")),
    Case(id="ZH-SPL-002", lang="zh", layer="text", category="B", text="「唔……也对，你会误解也是应该的。」", span="……",
         expect={"sentences": ["「唔……也对，你会误解也是应该的。」"]},
         basis="GB/T 15834-2011: 省略号 marks omitted text or halting speech, not a sentence end — though a "
               "sentence-final …… is common in fiction (他走了……). Today 「唔…… ‖ 也对，…。」 (since F4 the …… ends "
               "together and the 」 stays with the sentence it closes; before, one … and the 」 were lost).",
         status="LOCK", decision="ZH-BOUNDARIES", source=LIB1, refs=(zh("ZH-BOUND-02"), kc("SD-30"), kc("RL-10"))),
    Case(id="ZH-SPL-003", lang="zh", layer="text", category="B", text="《红楼梦》是一本书；我很喜欢。", span="；",
         expect={"sentences": ["《红楼梦》是一本书；我很喜欢。"]},
         basis="GB/T 15834-2011: 分号 joins the clauses of ONE complex sentence; the app splits at it by design "
               "(shorter example sentences).",
         status="LOCK", decision="ZH-BOUNDARIES", source=FIX, refs=(zh("ZH-BOUND-03"), kc("ZH-90"))),
    Case(id="ZH-SPL-004", lang="zh", layer="text", category="B", text="那是她的车．我的车是红色的．", span="．",
         expect={"sentences": ["那是她的车．", "我的车是红色的．"]},
         basis="The full-width ．(U+FF0E) ends sentences in real text (Tatoeba writes 那是她的车．) — but Taiwan also "
               "writes the name interpunct as ．(瑪麗．居禮), so adding it to the set would split such names.",
         status="LIMIT", decision="ZH-BOUNDARIES", source="constructed: from Tatoeba's 那是她的车．",
         refs=(zh("ZH-BOUND-04"),)),
    Case(id="ZH-SPL-005", lang="zh", layer="text", category="B", text="你好!我叫小明.你呢?", span=".",
         expect={"sentences": ["你好!", "我叫小明.", "你呢?"]},
         basis="A half-width . after Chinese ends a sentence in informal text — but . is also the decimal point, and "
               "jieba keeps 3.5 as one token, so the per-character test would split every decimal.",
         status="LIMIT", decision="ZH-BOUNDARY-CHARS", source=MADE, refs=(zh("ZH-BOUND-05"),)),
    Case(id="ZH-SPL-006", lang="zh", layer="text", category="B", text="我喜欢苹果、香蕉和橘子。", span="、",
         expect={"sentences": ["我喜欢苹果、香蕉和橘子。"]},
         basis="顿号 separates list items inside a sentence (GB/T 15834-2011).", status="LOCK", source=MADE,
         refs=(zh("ZH-BOUND-06"),)),
    Case(id="ZH-SPL-007", lang="zh", layer="text", category="B", text="这部电影出品时间是不是很久了？？", span="？？",
         expect={"sentences": ["这部电影出品时间是不是很久了？？"]},
         basis="A doubled terminator is one sentence end (UAX #29 SB8a); the second ？ used to be split off as debris "
               "and dropped (accepted then as harmless: the sentence stayed a verbatim prefix of the file).",
         status="LOCK", decision="ZH-BOUNDARY-CHARS", source=KD,
         refs=(zh("ZH-BOUND-07"), "F4 (ChineseTokenizer.tokenize_sentences)")),
    Case(id="ZH-SPL-008", lang="zh", layer="text", category="B", text="他说——我不去。", span="——",
         expect={"sentences": ["他说——我不去。"]},
         basis="破折号 is inside the sentence.", status="LOCK", source=MADE, refs=(zh("ZH-BOUND-08"),)),
    Case(id="ZH-SPL-009", lang="zh", layer="text", category="B", text="我今天\n很高兴。", span="",
         expect={"sentences": ["我今天很高兴。"]},
         basis="A hard line wrap inside a sentence (text copied from a PDF or an e-book) — every line end is a sentence "
               "end by design ('End of a line is itself a hard sentence boundary').",
         status="LIMIT", decision="ZH-BOUNDARIES", source=MADE, refs=(zh("ZH-BOUND-09"),)),
    Case(id="ZH-SPL-010", lang="zh", layer="text", category="B", text=srt("我觉得，", "他不会来"), span="",
         expect={"sentences": ["我觉得，他不会来。"]},
         basis="A subtitle cue ending in ， runs on into the next (逗号 is a pause INSIDE a sentence; UAX #29 "
               "SContinue); close_cue treated only arrows and dashes as continuations, so it appended 。 and the "
               "example read 我觉得，。",
         status="LOCK", decision="CUE-CLOSES", source=MADE, ctx={"ext": ".srt"},
         refs=(zh("ZH-BOUND-10"), "F4 (analyzer.close_cue)")),
    Case(id="ZH-SPL-011", lang="zh", layer="text", category="B", text="这是第一句话。这是第二句话", span="",
         expect={"sentences": ["这是第一句话。", "这是第二句话"]},
         basis="The last sentence flushes without a terminator.", status="LOCK", source=MADE,
         refs=(zh("ZH-BOUND-11"),)),
    Case(id="ZH-SPL-012", lang="zh", layer="text", category="B", text="真的吗？！太好了！", span="？！",
         expect={"sentences": ["真的吗？！", "太好了！"]},
         basis="？！ is one sentence end (UAX #29 SB8a): two sentences, split after it, the ！ kept (it used to be "
               "dropped as debris, as with ？？ in ZH-SPL-007).", status="LOCK", decision="ZH-BOUNDARY-CHARS",
         source=MADE, refs=(zh("ZH-BOUND-12"), "F4 (ChineseTokenizer.tokenize_sentences)")),
    Case(id="ZH-SPL-013", lang="zh", layer="text", category="B", text="如果你們喜歡這個影片，記得按讚訂閱。", span="，",
         expect={"sentences": ["如果你們喜歡這個影片，記得按讚訂閱。"]},
         basis="逗号 is a pause inside a sentence, never its end.", status="LOCK", source=MIX,
         refs=(zh("ZH-BOUND-13"),)),
    Case(id="ZH-SPL-014", lang="zh", layer="text", category="B", text="我今天很高兴｡他也很高兴｡", span="｡",
         expect={"sentences": ["我今天很高兴｡", "他也很高兴｡"]},
         basis="The half-width ｡ (U+FF61) is a full stop; it is a required zh boundary (merged into any saved "
               "settings, 2.1).", status="LOCK", source=MADE,
         refs=(kc("RL-2"), "tests/test_subtitle_sentence_splitting.py::test_halfwidth_full_stop_is_a_boundary")),

    Case(id="ZH-SPL-401", lang="zh", layer="text", category="B", text="英國作家達爾文．庫克出版了新書。", span="．",
         expect={"sentences": ["英國作家達爾文．庫克出版了新書。"]},
         basis="Between two Chinese characters ．(U+FF0E) is a foreign name's dot — the 間隔號 Taiwan and Hong Kong write "
               "with it (達爾文．庫克 'Darwin Cook') — not a full stop: one sentence. Measured 2026-09-29: of 997 ．in "
               "~150 MB of general Chinese text, 994 sit between two Chinese characters; of 40 read, ~35 are name dots.",
         status="LOCK", decision="ZH-BOUNDARIES", source="constructed: the name dot as zh news writes it (Leipzig)"),
    Case(id="ZH-SPL-402", lang="zh", layer="text", category="B", text="他走了……我们也走吧。", span="……",
         expect={"sentences": ["他走了……", "我们也走吧。"]},
         basis="In fiction a sentence-final …… ends its sentence (他走了……) and the next begins: two sentences. The "
               "decided set keeps …… inside one (GB/T 15834-2011: 省略号 marks omission or halting speech), so the two "
               "run on — the price ZH-BOUNDARIES accepts, as Japanese pays with そうか…じゃあ行くか。",
         status="LIMIT", decision="ZH-BOUNDARIES", source=MADE,
         note="Passes today (…… is a boundary until Z1); the scorecard shows it flip when Z1 lands."),
    Case(id="ZH-SPL-403", lang="zh", layer="text", category="B", text=srt("我买了书；", "他买了笔。"), span="；",
         expect={"sentences": ["我买了书；他买了笔。"]},
         basis="A subtitle cue ending in ；(分号: clauses of ONE sentence, GB/T 15834-2011) runs on into the next cue, as "
               "one ending in a comma does (ZH-SPL-010, CUE-CLOSES) — close_cue closes it with 。 today (我买了书；。).",
         status="LOCK", decision="ZH-BOUNDARIES", source=MADE, ctx={"ext": ".srt"}),
    # === Latin and digits ========================================================================================== #
    seg("ZH-LAT-001", "C", "Apple 推出新款 iPhone。", "推出新款 iPhone", "推出 / 新款 / [iPhone]",
        "Latin words are not Chinese vocabulary: dropped, the Chinese around them kept.", "LOCK", source=TAT,
        refs=(zh("ZH-LATIN-01"), kc("ZH-84"))),
    seg("ZH-LAT-002", "O", "卡拉OK對減輕壓力有益。", "卡拉OK", "卡拉OK",
        "CC-CEDICT 卡拉OK 'karaoke'; UD 卡拉OK:NOUN — today the list gets 卡拉 and drops OK.", "TARGET", source=TAT,
        refs=(zh("ZH-LATIN-02"), kc("RL-85"))),
    seg("ZH-LAT-003", "C", "你要這件T恤嗎？", "T恤", "T恤",
        "CC-CEDICT T恤 'T-shirt' — one word (jieba's dictionary has it).", "LOCK", source=TAT,
        refs=(zh("ZH-LATIN-03"), kc("RL-85"))),
    seg("ZH-LAT-010", "C", "你要這件Ｔ恤嗎？", "Ｔ恤", "T恤",
        "Full-width Ｔ is the letter T (NFKC): Ｔ恤 is T恤 'T-shirt' (CC-CEDICT), one word, as ZH-LAT-003. Read as "
        "written, jieba cuts the full-width letter off and counts 恤 alone.", "LOCK", decision="NFKC-READING",
        source=MADE, refs=("Parsing_Suite_Findings.md §5 F5",)),
    seg("ZH-LAT-004", "C", "她看起来好小啊，90后吗？", "90后", "90后",
        "90后 'born in the 1990s' is a lexicalised expression (not in CC-CEDICT, nor 九〇后); today the list counts 后 "
        "'after' for it — digits are never words.", "LIMIT", decision="ZH-CJK-TOKENS", source=KD,
        refs=(zh("ZH-LATIN-04"),)),
    seg("ZH-LAT-005", "O", "第2集中睦的逐漸崩潰從製作角度看非常有效。", "第2集中", "第 / [2] / 集 / 中",
        "'In episode 2': 第 + 2 + the measure word 集 + the localiser 中; jieba reads 集中 'to concentrate'.",
        "TARGET", source=WIKI, refs=(zh("ZH-LATIN-05"),), note="A path error: no switch fixes it."),
    seg("ZH-LAT-006", "C", "我的QQ号是12345。", "QQ号", "[QQ] / 号",
        "QQ号 'QQ number' = QQ + 号: any token with one CJK character is counted, so a Latin-glued token is a list word "
        "whenever jieba's dictionary holds it (QQ号: freq 3, not in CC-CEDICT).", "TARGET", decision="ZH-DICTIONARY",
        source=MADE, refs=(zh("ZH-LATIN-06"),)),
    seg("ZH-LAT-007", "C", "学习（xuéxí）很重要。", "（xuéxí）", "[（xuéxí）]",
        "Pinyin in running text is not a word: dropped with its brackets.", "LOCK", source=MADE,
        refs=(zh("ZH-LATIN-10"),)),
    seg("ZH-LAT-008", "C", "他去做了B超。", "B超", "B超",
        "CC-CEDICT B超 'B-mode ultrasonography' — a Latin + Han word jieba keeps whole in prose.", "LOCK",
        source=MADE, refs=(kc("RL-85"),)),
    seg("ZH-LAT-009", "C", "我们AA制吧。", "AA制", "AA制",
        "CC-CEDICT AA制 'to go Dutch' — kept whole in prose (a subtitle stripped it to 制 until F2: ZH-TXT family).",
        "LOCK",
        source=MADE, refs=(kc("RL-85"), kc("RL-22"))),

    # === A. reading subtitle files — seeded by the framework ======================================================== #
    Case(id="ZH-TXT-001", lang="zh", layer="text", category="A",
         text=srt("我有2个苹果。"), span="2",
         expect={"contains": ["我有2个苹果"]},
         basis="'I have 2 apples': the digit is the sentence's content; the subtitle cleaner strips every ASCII "
               "letter and digit, leaving 我有个苹果 — the example changes meaning.",
         status="LOCK", source="constructed", ctx={"ext": ".srt"},
         refs=("Parsing_Robustness_Suite_Scope.md §2 A", "debug/parsing_suite/zh ZH-LATIN-09", kc("RL-22"), "F2")),
    Case(id="ZH-TXT-002", lang="zh", layer="text", category="A", text=srt("我买了一件T恤"), span="T恤",
         expect={"contains": ["我买了一件T恤"], "words": ["T恤"]},
         basis="CC-CEDICT T恤 'T-shirt': clean_subtitle_text('zh') strips every ASCII letter and digit from a cue, so "
               "T恤 becomes 恤 — and the example sentence itself changes.",
         status="LOCK", source=MADE, ctx={"ext": ".srt"}, refs=(zh("ZH-LATIN-07"), kc("RL-22"), "F2")),
    Case(id="ZH-TXT-003", lang="zh", layer="text", category="A", text=srt("我们去唱卡拉OK吧"), span="卡拉OK",
         expect={"contains": ["卡拉OK"], "words": ["卡拉OK"]},
         basis="CC-CEDICT 卡拉OK 'karaoke': the cue's OK is stripped, leaving 卡拉 (as ZH-TXT-002).",
         status="TARGET", source=MADE, ctx={"ext": ".srt"}, refs=(zh("ZH-LATIN-08"), kc("RL-22"), "ZH-LAT-002"),
         note="F2 keeps OK in the sentence (我们去唱卡拉OK吧。); what is left is jieba's cut, 卡拉 / OK — ZH-LAT-002's, "
              "not the cleaner's."),
    Case(id="ZH-TXT-004", lang="zh", layer="text", category="A", text=srt("3个人来了"), span="3个人",
         expect={"contains": ["3个人来了"], "not_words": ["个人"]},
         basis="'3 people came': stripping the digit leaves 个人来了 — 个人 'personal; individual' becomes a list word "
               "and the example says something else.",
         status="TARGET", source=MADE, ctx={"ext": ".srt"}, refs=(kc("RL-22"),),
         note="F2 keeps the digit (3个人来了。); jieba still cuts 3 / 个人 / 来 / 了 — after a numeral 个 is the measure "
              "word (3个 + 人), a segmentation question for the Chinese family, not the cleaner's."),
    Case(id="ZH-TXT-005", lang="zh", layer="text", category="A", text=srt("（李明(lǐ míng)）你在做什么？"), span="",
         expect={"sentences": ["你在做什么？"]},
         basis="A speaker label with its reading in nested brackets is no dialogue: the nesting-aware bracket strip "
               "leaves nothing behind.", status="LOCK", source=MADE, ctx={"ext": ".srt"},
         refs=(kc("RL-17"), "tests/test_speaker_label_stripping.py::test_chinese_cues_get_the_same_treatment")),
    Case(id="ZH-TXT-006", lang="zh", layer="text", category="A", text=ass("我觉得\\N他不会来"), span="",
         expect={"contains": ["我觉得他不会来"], "not_contains": ["\\"]},
         basis="ASS's \\N is a line break inside one cue; the cleaner strips ASCII letters, so N goes and a lone "
               "backslash stays in the example: 我觉得\\他不会来。",
         status="LOCK", decision="CUE-LINES", source=MADE, ctx={"ext": ".ass"}, refs=(kc("RL-20"),),
         note="F2 reads \\N as a line break (no backslash left), and a cue's lines were joined with a space as in an "
              ".srt, so the example read 我觉得 他不会来。 — jieba keeps the space. Fixed 2026-09-28: a Chinese "
              "caption's line break between two wide characters joins with nothing (CSS Text 3's segment-break rule, "
              "analyzer._join_lines), an .srt cue's two lines too; Japanese keeps the space, which its tagger reads "
              "as a word boundary and its sentence drops."),
    Case(id="ZH-TXT-007", lang="zh", layer="text", category="A", text=srt("他说：我们走吧"), span="他说：",
         expect={"contains": ["他说：我们走吧"]},
         basis="A colon after 说 introduces speech — 他说：我们走吧 'he said: let's go' is dialogue, not a speaker label; "
               "the Japanese label rule (a name holds no hiragana) has no Chinese counterpart, so it stays Japanese.",
         status="LOCK", source=MADE, ctx={"ext": ".srt"}, refs=("F3", "JA-TXT-019", "JA-TXT-045")),
    Case(id="ZH-TXT-008", lang="zh", layer="text", category="A", text=srt("[音乐]", "[笑声]我们走吧"), span="[笑声]",
         expect={"sentences": ["我们走吧。"], "not_words": ["音乐", "笑声"]},
         basis="Captions write what is heard but not said in square brackets (the SDH convention) in Chinese as in "
               "Japanese: [音乐] 'music', [笑声] 'laughter' are no speech.",
         status="LOCK", source=MADE, ctx={"ext": ".srt"}, refs=("F3", "JA-TXT-022")),

    # === characters and encodings ================================================================================== #
    Case(id="ZH-ENC-001", lang="zh", layer="tokens_zh", category="C", text="这个⽅法很好。", span="",
         expect={"words": ["方法"], "not_words": ["法"]},
         basis="⽅ is U+2F45 KANGXI RADICAL SQUARE, which PDF extraction emits for 方; Unicode decomposes it to 方 "
               "(NFKC). Outside [一-鿿] it is dropped today, and 法 is counted alone.",
         status="LOCK", source=MADE, refs=(zh("ZH-ENC-01"),)),
    seg("ZH-ENC-002", "C", "刘䶮是南汉的开国皇帝。", "刘䶮", "刘䶮",
        "CC-CEDICT 䶮 (U+4DAE, CJK Extension A) 'character coined for the name of Liu Yan'; the tokenizer's [一-鿿] "
        "and jieba's own Han range (to U+9FD5) both miss Extension A.", "TARGET", decision="ZH-HAN-RANGE", source=MADE,
        refs=(zh("ZH-ENC-02"), kc("AM-78")),
        note="F7 (2026-09-27): the tokenizer counts 䶮 now (刘 / 䶮, was 刘 / [䶮]); jieba's own Han range still "
             "cuts the name there — joining it is a change to jieba's segmentation (Parsing_Fixes_Plan §2.4)."),
    seg("ZH-ENC-003", "C", "我哋搭\U000282e2上去。", "\U000282e2", "\U000282e2",
        "𨋢 (U+282E2, Extension B) 'lift' in Hong Kong writing is a Chinese character: counted as written (an "
        "Extension B name character in Mandarin is too).", "LOCK", decision="ZH-CANTONESE-OUT", source=MADE,
        refs=(zh("ZH-ENC-03"), kc("RL-86")),
        note="F7 (2026-09-27): the tokenizer's range stopped at U+9FFF and dropped it as non-CJK (a LIMIT under "
             "ZH-CANTONESE-OUT); it is Unicode's Han ranges now, planes 2 and 3 included."),
    Case(id="ZH-ENC-004", lang="zh", layer="tokens_zh", category="C", text="学​习很重要。", span="",
         expect={"words": ["学习"], "not_words": ["学", "习"]},
         basis="A ZERO WIDTH SPACE (U+200B, a format character) pasted inside a word is invisible, but jieba cuts "
               "there. normalize_word removes it from card fields (ZH-CRD-007); content keeps it.",
         status="LOCK", source=MADE, refs=(zh("ZH-ENC-04"),)),
    Case(id="ZH-ENC-005", lang="zh", layer="known", category="A", text="", span="",
         expect={"known": ["冒险", "勇者"]},
         basis="Notepad's UTF-8 starts a file with a BOM; load_simple_list reads 'utf-8', not 'utf-8-sig', so the BOM "
               "sticks to the first line and 冒险 is never ignored.",
         status="LOCK", source=MADE, ctx={"ignore": "﻿冒险\n勇者\n"},
         refs=(zh("ZH-ENC-05"), kc("HX-16"), "F1: path_utils.read_text (2026-09-27)"),
         note="The shipped User Files/zh/IgnoreList.txt starts with a BOM before a comment line, which it turns into an "
              "entry ('\\ufeff# Add words…') — harmless until that line is replaced by a word."),
    Case(id="ZH-ENC-006", lang="zh", layer="text", category="A", text="我们走吧。\r\n他说。", span="",
         expect={"sentences": ["我们走吧。", "他说。"]},
         basis="CRLF line ends: no \\r reaches a sentence.", status="LOCK", source=MADE,
         refs=(zh("ZH-ENC-06"), kc("SD-36"))),
    seg("ZH-ENC-007", "C", "你应该对地位比自己高旳人更多一点尊重才对。", "旳", "[旳]",
        "旳 (U+65F3) is a typo for 的 in the source (not in CC-CEDICT) — no word of Chinese; the analyzer counts what "
        "is written.", "LIMIT", decision="ZH-CJK-TOKENS", source=LIB2, refs=(zh("ZH-ENC-07"),)),
    Case(id="ZH-ENC-008", lang="zh", layer="tokens_zh", category="C", text="ー个人", span="ー个",
         expect={"not_words": ["个人"]},
         basis="Katakana ー (U+30FC) typed or OCR'd for 一 ('一个人' was meant): dropped (no CJK), and the rest reads 个人 "
               "'personal' — garbage in.", status="LIMIT", decision="ZH-CJK-TOKENS", source=MADE,
         refs=(zh("ZH-ENC-08"),)),
    seg("ZH-ENC-009", "C", "今天好开心😂哈哈", "😂", "[😂]",
        "Emoji are not words: dropped, the words around them kept.", "LOCK", source=MADE, refs=(zh("ZH-ENC-09"),)),
    Case(id="ZH-ENC-010", lang="zh", layer="text", category="A", text="我们一起学习中文。\n他说。", span="",
         expect={"contains": ["我们一起学习中文。"]},
         basis="GBK is how older Simplified text files are saved on Chinese Windows. The reader tries UTF-8, then "
               "reads with errors='ignore': the Chinese is destroyed and the file contributes nothing, silently.",
         status="LOCK", source=MADE, ctx={"encoding": "gbk"},
         refs=(kc("RL-103"), "F1: path_utils.read_text (2026-09-27)"),
         note="Found porting this suite: the Chinese side of RL-102 / RL-103 (CP932, UTF-16 for Japanese)."),
    Case(id="ZH-ENC-011", lang="zh", layer="text", category="A", text="我們一起學習中文。\n他說。", span="",
         expect={"contains": ["我們一起學習中文。"]},
         basis="Big5 is how older Traditional text files (Taiwan, Hong Kong) are saved; read as UTF-8 with errors "
               "ignored, the file contributes nothing, silently.",
         status="LOCK", source=MADE, ctx={"encoding": "big5"},
         refs=(kc("RL-103"), "F1: path_utils.read_text (2026-09-27)"),
         note="Found porting this suite."),
    Case(id="ZH-ENC-012", lang="zh", layer="text", category="A", text="我们一起学习中文。\n他说。", span="",
         expect={"contains": ["我们一起学习中文。"]},
         basis="UTF-16 (Windows Notepad's 'Unicode') is a Unicode file like any other; read as UTF-8 with errors "
               "ignored, it contributes nothing, silently.",
         status="LOCK", source=MADE, ctx={"encoding": "utf-16"},
         refs=(kc("RL-103"), "F1: path_utils.read_text (2026-09-27)")),
    Case(id="ZH-ENC-013", lang="zh", layer="text", category="A", text="我们走吧。\n他说。", span="",
         expect={"sentences": ["我们走吧。", "他说。"]},
         basis="A UTF-8 BOM is no text, but a .txt is read as 'utf-8', so the first example sentence carries it "
               "(\\ufeff我们走吧。) — invisible in the report, and no longer the file's own wording.",
         status="LOCK", source=MADE, ctx={"encoding": "utf-8-sig"},
         refs=(kc("HX-16"), "F1: path_utils.read_text (2026-09-27)")),
    # Found with F1 (Parsing_Suite_Findings.md §5): Chinese Windows' own encodings, in a list and in a subtitle.
    Case(id="ZH-ENC-014", lang="zh", layer="user_file", category="A", text="冒险\r\n勇者\r\n", span="",
         expect={"error": "", "has": ["冒险", "勇者"]},
         basis="Notepad's 'ANSI' on Simplified Chinese Windows is GBK (CP936): read as UTF-8 the ignore list raises and "
               "Generate stops.",
         status="LOCK", source=MADE, ctx={"encoding": "gbk"},
         refs=("Parsing_Suite_Findings.md §5 F1", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="ZH-ENC-015", lang="zh", layer="text", category="A", text=srt("我们一起学习中文。", "他说。"), span="",
         expect={"contains": ["我们一起学习中文。"]},
         basis="A GBK subtitle (older Simplified releases): pysrt reads it as UTF-8, raises, and the whole file "
               "contributes nothing — silently.",
         status="LOCK", source=MADE, ctx={"ext": ".srt", "encoding": "gbk"},
         refs=(kc("RL-102"), "F1: path_utils.read_text (2026-09-27)")),
    Case(id="ZH-ENC-016", lang="zh", layer="text", category="A", text=srt("我們一起學習中文。", "他說。"), span="",
         expect={"contains": ["我們一起學習中文。"]},
         basis="A Big5 subtitle (older Traditional releases, Taiwan and Hong Kong): as ZH-ENC-015. GB18030 reads almost "
               "any byte pair — Big5's included — so the Big5 reading must win on evidence: read as GB18030, Big5's "
               "full-width punctuation (，。「」) comes out as Private Use characters, which no standard text holds.",
         status="LOCK", source=MADE, ctx={"ext": ".srt", "encoding": "big5"},
         refs=(kc("RL-102"), "F1: path_utils.read_text (2026-09-27)")),
    Case(id="ZH-ENC-017", lang="zh", layer="user_file", category="A", text="學習\r\n中文\r\n", span="",
         expect={"error": "", "has": ["學習", "中文"]},
         basis="A Big5 word list (Traditional Windows' 'ANSI'). With no punctuation, its GB18030 reading holds no Private "
               "Use character, so nothing in the bytes tells Big5 from GBK: a short, punctuation-free Big5 file is read "
               "as GB18030. Read as UTF-8 today, the list raises and Generate stops.",
         status="LIMIT", decision="FILE-ENCODING", source=MADE, ctx={"encoding": "big5"},
         refs=("Parsing_Suite_Findings.md §5 F1",),
         note="F1 (2026-09-27) ends the crash but reads this list wrong (GB18030 first, as the plan orders): the one "
              "Big5 shape the evidence rule can't see. Accepted by the user, 2026-09-27 (FILE-ENCODING): saving the "
              "list as UTF-8 reads it right."),
    Case(id="ZH-ENC-018", lang="zh", layer="text", category="A", text="他們的友誼是永恒的。\n", span="",
         expect={"sentences": ["他們的友誼是永恒的。"]},
         basis="Big5 as Windows writes it (code page 950) carries the ETEN characters 碁 銹 裏 墻 恒 粧 嫺 (F9D6–F9DC) "
               "and €, which the Big5 table without them refuses — the whole file would be lost to one 恒.",
         status="LOCK", source=MADE, ctx={"encoding": "cp950"},
         refs=(kc("RL-103"), "F1: path_utils.read_text (2026-09-27)")),

    # === K. card fields (card_key: the field as Junban and the label read it) ======================================== #
    Case(id="ZH-CRD-001", lang="zh", layer="card_key", category="K", text="学习[xue2 xi2]", span="[xue2 xi2]",
         expect={"word": "学习", "key": "学习"},
         basis="A CC-CEDICT-style card's pinyin in brackets is a reading, not the word: stripped (Z-F16).",
         status="LOCK", source=MADE, ctx={"list": ["学习"]},
         refs=(zh("ZH-CARD-01"), kc("ZH-89"), kc("AM-8"),
               "modules/junban/tests/test_patterns_zh_lookup.py::test_a_card_with_pinyin_brackets_is_found")),
    Case(id="ZH-CRD-002", lang="zh", layer="card_key", category="K", text="学习 (xuéxí)", span="(xuéxí)",
         expect={"word": "学习"},
         basis="A reading in parentheses is an annotation, not part of the word; normalize_word mirrors anki_miner's "
               "Japanese scan and keeps it, so the card matches nothing.",
         status="LOCK", decision="ZH-CARD-FIELD", source=MADE, ctx={"list": ["学习"]}, refs=(zh("ZH-CARD-02"),)),
    Case(id="ZH-CRD-003", lang="zh", layer="card_key", category="K", text="学习 xuéxí", span="xuéxí",
         expect={"word": "学习"},
         basis="A Latin reading after a space is an annotation; kept today, so no match.",
         status="LOCK", decision="ZH-CARD-FIELD", source=MADE, ctx={"list": ["学习"]}, refs=(zh("ZH-CARD-03"),)),
    Case(id="ZH-CRD-004", lang="zh", layer="card_key", category="K",
         text='<span class="tone2">学</span><span class="tone2">习</span>', span="学",
         expect={"word": "学习", "key": "学习"},
         basis="Tone-coloured spans (the Chinese Support add-ons) are markup.", status="LOCK", source=MADE,
         ctx={"list": ["学习"]}, refs=(zh("ZH-CARD-04"),)),
    Case(id="ZH-CRD-005", lang="zh", layer="card_key", category="K",
         text="<ruby>学<rt>xué</rt></ruby><ruby>习<rt>xí</rt></ruby>", span="学",
         expect={"word": "学习", "key": "学习"},
         basis="Ruby pinyin is a reading: it goes before the tags do.", status="LOCK", source=MADE,
         ctx={"list": ["学习"]}, refs=(zh("ZH-CARD-05"),)),
    Case(id="ZH-CRD-006", lang="zh", layer="card_key", category="K", text="学习 / 學習", span="學習",
         expect={"word": "学习"},
         basis="Decks that print both scripts in the word field hold one word twice; kept whole today, so no match.",
         status="LOCK", decision="ZH-CARD-FIELD", source=MADE, ctx={"list": ["学习"]}, refs=(zh("ZH-CARD-06"),)),
    Case(id="ZH-CRD-007", lang="zh", layer="card_key", category="K", text="学​习", span="",
         expect={"word": "学习", "key": "学习"},
         basis="A zero-width space pasted inside the word is no character of it: normalize_word drops it (content "
               "keeps it: ZH-ENC-004).", status="LOCK", source=MADE, ctx={"list": ["学习"]},
         refs=(zh("ZH-ENC-04"),)),

    Case(id="ZH-CRD-401", lang="zh", layer="card_key", category="K", text="约翰・列侬", span="・",
         expect={"word": "约翰・列侬"},
         basis="A Chinese foreign name's dot (间隔号, here the katakana middle dot U+30FB) joins the name's parts: the "
               "field is ONE word — never parted at the dot, as the Japanese reading keeps ジョン・スミス whole.",
         status="LOCK", decision="ZH-CARD-FIELD", source=MADE, ctx={"list": ["约翰・列侬"]},
         note="Guards Z2's separator rule: a Chinese field is never parted at ・ or ·."),
    Case(id="ZH-CRD-402", lang="zh", layer="card_key", category="K", text="学习<br>xuéxí", span="xuéxí",
         expect={"word": "学习", "key": "学习"},
         basis="A field's second line is not its word (Anki writes each line as <br> or <div>): the first line is.",
         status="LOCK", decision="ZH-CARD-FIELD", source=MADE, ctx={"list": ["学习"]}),
    Case(id="ZH-CRD-403", lang="zh", layer="card_key", category="K", text="「学习」", span="「",
         expect={"word": "学习", "key": "学习"},
         basis="The brackets a word was typed in are no part of it.",
         status="LOCK", decision="ZH-CARD-FIELD", source=MADE, ctx={"list": ["学习"]}),
    # === K. card matching — seeded by the framework ================================================================ #
    Case(id="ZH-KEY-001", lang="zh", layer="card_key", category="K",
         text="學習", span="學習",
         expect={"key": "学习"},
         basis="學習 and 学习 are one word in two scripts; a Traditional card against a Simplified library under the "
               "default as-is setting matches nothing, so Junban never places it and the label never marks it.",
         status="TARGET", source="constructed", ctx={"list": ["学习", "工作"]},
         refs=("Parsing_Robustness_Suite_Scope.md §2 K", zh("ZH-CARD-07")),
         note="The adversary filed it DISPUTED; the ratified scope (§2 K) files it TARGET — a fallback that converts "
              "only the lookup key changes no as-is output."),
    Case(id="ZH-KEY-002", lang="zh", layer="card_key", category="K", text="學習", span="學習",
         expect={"key": "学习", "via": "exact"},
         basis="With the library read as Simplified the lookup key is converted (never the card): the Traditional "
               "card meets 学习.", status="LOCK", source=MADE,
         ctx={"list": ["我们", "一起", "学习", "中文"], "script": "s"},
         refs=(zh("ZH-CARD-08"), kc("ZH-77"),
               "modules/junban/tests/test_zh_script_lookup.py::test_traditional_cards_match_a_list_read_as_simplified")),
    Case(id="ZH-KEY-003", lang="zh", layer="card_key", category="K", text="學習", span="學習",
         expect={"key": "學習", "via": "exact"},
         basis="With the library read as Traditional both sides are Traditional.", status="LOCK", source=MADE,
         ctx={"list": ["我們", "一起", "學習", "中文"], "script": "t"}, refs=(zh("ZH-CARD-09"),)),
    Case(id="ZH-KEY-004", lang="zh", layer="card_key", category="K", text="认真地", span="认真地",
         expect={"key": "认真"},
         basis="A card written with its particle (认真地 'earnestly', 漂亮的) is its word 认真; Japanese drops an ending "
               "(努力する → 努力, MATCH-ENDINGS) — Chinese has no such rule.",
         status="LOCK", decision="ZH-CARD-FIELD", source=MADE, ctx={"list": ["他", "认真", "地", "学习"]},
         refs=(zh("ZH-CARD-10"),)),
    Case(id="ZH-KEY-005", lang="zh", layer="card_key", category="K", text="看", span="看",
         expect={"key": "看", "via": "exact"},
         basis="Most common Chinese words are one character (看, 我): a card of one keeps its key — the one-character "
               "guard is Japanese-only.", status="LOCK", source=MADE, ctx={"list": ["我", "看", "书"]},
         refs=(kc("AM-26"), "tests/test_anki_match.py::test_chinese_keeps_its_one_character_words")),

    Case(id="ZH-KEY-401", lang="zh", layer="card_key", category="K", text="漂亮的", span="漂亮的",
         expect={"key": "漂亮", "via": "L7"},
         basis="漂亮 'pretty' + the attributive particle 的 (it does な's job): read alone as ONE word + 的, the card is "
               "its word (ZH-CARD-FIELD; MATCH-ENDINGS for Japanese 斬新な → 斬新).",
         status="LOCK", decision="ZH-CARD-FIELD", source=MADE, ctx={"list": ["漂亮", "的"]}),
    Case(id="ZH-KEY-402", lang="zh", layer="card_key", category="K", text="目的", span="目的",
         expect={"key": ""},
         basis="目的 'purpose' is one word (CC-CEDICT; jieba one token): its 的 is no particle, so the card is never "
               "目's — the ending rule takes ONE word + 的 as the tokenizer reads it.",
         status="LOCK", decision="ZH-CARD-FIELD", source=MADE, ctx={"list": ["目", "的", "学习"]}),
    Case(id="ZH-KEY-403", lang="zh", layer="card_key", category="K", text="我的", span="我的",
         expect={"key": "我", "via": "L7"},
         basis="我的 'my' is 我 + 的 read alone: the card is 我 — the decided price ('one word unless there's a good "
               "reason', as お茶する → お茶).",
         status="LOCK", decision="ZH-CARD-FIELD", source=MADE, ctx={"list": ["我", "的"]}),
    Case(id="ZH-KEY-404", lang="zh", layer="card_key", category="K", text="吃了", span="吃了",
         expect={"key": "吃", "via": "L7"},
         basis="吃了 'ate' is the verb 吃 + the aspect marker 了 — its paradigm, no word of its own (as CARD-INFLECTIONS "
               "placed 取り消した at 取り消す). The user took the lean (ZH-CARD-ENDINGS, 2026-09-29); built 2026-09-30.",
         status="LOCK", decision="ZH-CARD-ENDINGS", source=MADE, ctx={"list": ["吃", "了"]}),
    Case(id="ZH-KEY-405", lang="zh", layer="card_key", category="K", text="开开心心", span="开开心心",
         expect={"key": "开心", "via": "L7"},
         basis="A doubled form counts as its base (ZH-LEMMA): a card mined as 开开心心 is 开心's, as 努力する is 努力's.",
         status="LOCK", decision="ZH-LEMMA", source=MADE, ctx={"list": ["开心"]},
         note="Needs Z2 (a Chinese card read alone is the word its one token counts as) and Z6 (that word is 开心)."),
    # === J. known words, and the known-words cache ================================================================ #
    Case(id="ZH-KNW-001", lang="zh", layer="known", category="J",
         text="學習", span="學習",
         expect={"known": ["学习"], "adds": ["学习"]},
         basis="With the library read as Simplified (script 's') a Traditional known word is converted as the "
               "tokenizer converts the text, so 學習 known means 学习 known.",
         status="LOCK", source="constructed", ctx={"script": "s"},
         refs=("Chinese_Script_Conversion_Spec.md §7",)),
    Case(id="ZH-KNW-002", lang="zh", layer="known", category="J", text="学习[xué xí]", span="学习",
         expect={"known": ["学习"]},
         basis="A known word with its reading in brackets still makes 学习 known (the brackets tokenize to nothing).",
         status="LOCK", source=MADE, refs=(zh("ZH-CARD-11"),)),
    Case(id="ZH-KNW-003", lang="zh", layer="known", category="J", text="不得其门而入", span="不得其门而入",
         expect={"known": ["不得其门而入"], "unknown": ["不得", "其门", "而入"]},
         basis="Knowing the idiom 不得其门而入 'unable to get in' is knowing the idiom: jieba cuts it into 不得 ('must "
               "not', another sense) and two HMM non-words, and load_known_words marks every piece known.",
         status="LIMIT", decision="ZH-KNOWN-PIECES", source=MADE, refs=(zh("ZH-CARD-12"), kc("AM-68"))),
    Case(id="ZH-KNW-004", lang="zh", layer="known", category="J", text="學習", span="學習",
         expect={"known": ["學習"], "unknown": ["學", "習"], "adds": ["學習"]},
         basis="A Traditional known word under as-is is one word: jieba keeps 學習 whole, so 學 and 習 don't become "
               "known on their own.", status="LOCK", decision="ZH-HMM", source=MADE, refs=(zh("ZH-CARD-13"),),
         note="Whole only by the HMM's guess (jieba lacks 學習): HMM off cuts 學 / 習 and makes both known."),
    Case(id="ZH-KNW-005", lang="zh", layer="zh_known_card", category="K", text="學習", span="學習",
         expect={"known": True},
         basis="學習 and 学习 are one word: a Traditional card of a word known in Simplified is known. Junban's known "
               "tier and Backfill's skip convert a Chinese card only when the setting converts, so under the default "
               "as-is it is 'not known'.",
         status="TARGET", source=MADE, ctx={"known": ["学习"]}, refs=(zh("ZH-CARD-14"),),
         note="The adversary filed it DISPUTED; the ratified scope (§2 K: 'never known') files it TARGET, with "
              "ZH-KEY-001."),
    Case(id="ZH-KNW-006", lang="zh", layer="zh_known_card", category="K", text="學習", span="學習",
         expect={"known": True},
         basis="S7: with the Simplified setting the card's word is converted and meets 学习.", status="LOCK",
         source=MADE, ctx={"known": ["学习"], "script": "s"},
         refs=(zh("ZH-CARD-15"), kc("ZH-108"),
               "modules/junban/tests/test_side_by_side.py::test_a_traditional_card_meets_a_simplified_known_word")),
    Case(id="ZH-KNW-007", lang="zh", layer="known", category="J", text="头发", span="头发",
         expect={"known": ["頭髮"], "unknown": ["头发"]},
         basis="load_known_words takes the script from the tokenizer: read as Traditional, a known 头发 is 頭髮, the "
               "spelling the content comes out in.", status="LOCK", source=MADE, ctx={"script": "t"},
         refs=("tests/test_zh_script_analysis.py::test_known_words_follow_the_tokenizer_script",)),
    Case(id="ZH-KNW-008", lang="zh", layer="known", category="J", text="", span="",
         expect={"known": ["东西"]},
         basis="An ignore-list line written in Traditional (東西) ignores the word in the library's script (东西).",
         status="LOCK", source=MADE, ctx={"ignore": ["東西"], "script": "s"},
         refs=("tests/test_zh_script_analysis.py::"
               "test_one_script_merges_the_counts_and_applies_known_and_ignored_words",)),
    Case(id="ZH-KNW-009", lang="zh", layer="zh_cache_sig", category="N", text="就把", span="",
         expect={"known_moves": False},
         basis="The known-words cache holds KnownWord.json cut with the run's reinforce setting; switching it rebuilt "
               "the token store but served the known words cut the old way. Reinforce is retired (ZH-REINFORCE): "
               "switching it changes no cut, so the cached known words are right — moved on purpose (2026-09-30).",
         status="LOCK", decision="ZH-REINFORCE", source=MADE, ctx={"from": {"reinforce": False}, "to": {"reinforce": True}},
         refs=(kc("SD-13"), "Chinese_Script_Conversion_Spec.md §12 (reinforce not folded in)",
               "Parsing_Robustness_Suite_Scope.md §2 N"),
         note="jieba 0.42.1 splits 就把 and 您不 either way, so no known word moves today."),
    Case(id="ZH-KNW-010", lang="zh", layer="zh_cache_sig", category="N", text="学习", span="",
         expect={"build_moves": False},
         basis="Switching reinforce changed how content is cut, so the token store rebuilt. Reinforce is retired "
               "(ZH-REINFORCE): the build signature reads reinforce=False either way and no store rebuilds for it — "
               "moved on purpose (2026-09-30).", status="LOCK", decision="ZH-REINFORCE", source=MADE,
         ctx={"from": {"reinforce": False}, "to": {"reinforce": True}},
         refs=(kc("ZH-120"), "tests/test_zh_script_tokenizer.py::test_build_signature")),
    Case(id="ZH-KNW-011", lang="zh", layer="zh_cache_sig", category="N", text="学习", span="",
         expect={"build_moves": True, "known_moves": True},
         basis="A script switch re-reads everything in the other script: the token store rebuilds and the known "
               "words are re-read (the script is folded into both signatures, only when converting — as-is keeps its "
               "old ones, I2).", status="LOCK", source=MADE, ctx={"from": {"script": "asis"}, "to": {"script": "s"}},
         refs=(kc("ZH-121"), kc("ZH-122"),
               "tests/test_zh_script_tokenizer.py::test_known_signature_changes_only_when_converting")),

    # === O. note-type language (Backfill, S3 / S4) ================================================================= #
    Case(id="ZH-NTL-001", lang="zh", layer="zh_note_lang", category="O", text="学习", span="",
         expect={"language": None},
         basis="D7: a note type with no kana anywhere is not set — never filled until the user chooses Chinese.",
         status="LOCK", source=MADE, ctx={"fields": {"Pinyin": "xuéxí", "Meaning": "to study"}},
         refs=(zh("ZH-LANG-01"), kc("ZH-104"),
               "modules/junban/tests/test_side_by_side.py::test_a_note_type_with_no_kana_and_no_language_set_is_never_filled")),
    Case(id="ZH-NTL-002", lang="zh", layer="zh_note_lang", category="O", text="学习", span="",
         expect={"language": None},
         basis="Bopomofo (U+3100–312F) is not kana.", status="LOCK", source=MADE,
         ctx={"fields": {"Zhuyin": "ㄒㄩㄝˊ ㄒㄧˊ"}}, refs=(zh("ZH-LANG-02"),)),
    Case(id="ZH-NTL-003", lang="zh", layer="zh_note_lang", category="O", text="约翰・列侬", span="・",
         expect={"language": None},
         basis="The middle dot ・ (U+30FB) in a Chinese foreign name is punctuation, no kana letter (fixed "
               "2026-09-25: backfill._KANA holds kana letters only).", status="LOCK", source=MADE,
         refs=(zh("ZH-LANG-03"), kc("ZH-87"),
               "modules/junban/tests/test_side_by_side.py::test_a_chinese_foreign_names_middle_dot_is_no_kana")),
    Case(id="ZH-NTL-004", lang="zh", layer="zh_note_lang", category="O", text="晚餐", span="",
         expect={"language": None},
         basis="の for 的 is common in Taiwanese Chinese writing (shop signs, social media): a Chinese note, no Japanese "
               "one. A Chinese note type of four notes where one holds it is Chinese — not set until the user chooses — "
               "never Japanese (ZH-NOTE-KANA: Japanese only when most notes hold kana).",
         status="LOCK", decision="ZH-NOTE-KANA", source=MADE,
         ctx={"fields": {"Sentence": "今天の晚餐超好吃"},
              "notes": [{"Hanzi": "学习", "Sentence": "我们一起学习中文。"},
                        {"Hanzi": "问题", "Sentence": "这个问题很重要。"},
                        {"Hanzi": "朋友", "Sentence": "他是我的好朋友。"}]},
         refs=(zh("ZH-LANG-04"), kc("ZH-117")),
         note="Rewritten 2026-09-29 as a type of four notes: one note is 'most' of a one-note type (that shape is "
              "ZH-NTL-403, LIMIT)."),
    Case(id="ZH-NTL-005", lang="zh", layer="zh_note_lang", category="O", text="无所谓", span="",
         expect={"language": None},
         basis="The shrug kaomoji's ツ is a katakana letter in a Chinese note; one such note among four leaves the type "
               "Chinese (not set), never Japanese.",
         status="LOCK", decision="ZH-NOTE-KANA", source=MADE,
         ctx={"fields": {"Notes": "¯\\_(ツ)_/¯"},
              "notes": [{"Hanzi": "学习", "Notes": "to study"}, {"Hanzi": "问题", "Notes": "question"},
                        {"Hanzi": "朋友", "Notes": "friend"}]},
         refs=(zh("ZH-LANG-05"),), note="Rewritten 2026-09-29 as a type of four notes (see ZH-NTL-004)."),
    Case(id="ZH-NTL-006", lang="zh", layer="zh_pat_key", category="O", text="约翰・列侬", span="・",
         expect={"reason": "phrase"},
         basis="A Chinese name written with ・ is two words — a phrase for the パターン lookup, never 'another "
               "language': ・ is punctuation Chinese writes too (Unicode files it Common, no kana letter).",
         status="LOCK", source=MADE, refs=(zh("ZH-LANG-06"), kc("ZH-88"), kc("AM-77")),
         note="F8i (2026-09-27): patterns_zh._KANA was the whole kana block and refused the card as "
              "'language' (backfill._KANA was narrowed on 2026-09-25, patterns_zh's was not); every Chinese "
              "kana test reads app/unicode_ranges.KANA_LETTERS now."),
    Case(id="ZH-NTL-007", lang="zh", layer="zh_note_lang", category="O", text="勉強する", span="",
         expect={"language": "zh"},
         basis="D7 rule 1: the user's choice decides first — a note type set to Chinese stays Chinese though one of "
               "its notes is Japanese; the per-note kana guard (S4, ZH-NTL-008) keeps that note out.",
         status="LOCK", source=MADE,
         ctx={"fields": {"Sentence": "毎日勉強する。"}, "languages": {"Chinese Vocab": "zh"}},
         refs=("modules/junban/tests/test_side_by_side.py::test_a_word_with_kana_is_never_filled_from_chinese_data",)),
    Case(id="ZH-NTL-008", lang="zh", layer="zh_pat_key", category="O", text="勉強する", span="",
         expect={"reason": "language"},
         basis="S4: 勉強する is Japanese (kana) and never looked up in Chinese data, even where its kanji (勉强) are a "
               "Chinese word.", status="LOCK", source=MADE, ctx={"store": ["勉强"]},
         refs=(kc("ZH-105"),
               "modules/junban/tests/test_patterns_zh_lookup.py::test_a_word_with_kana_is_never_looked_up_in_chinese")),

    Case(id="ZH-NTL-401", lang="zh", layer="zh_note_lang", category="O", text="勉強", span="",
         expect={"language": "ja"},
         basis="A Japanese note type has kana in most notes (a sentence, a reading): read as Japanese, as every real one "
               "is (Lapis: 1,457 of 1,457).",
         status="LOCK", decision="ZH-NOTE-KANA", source=MADE,
         ctx={"fields": {"Sentence": "毎日勉強する。"},
              "notes": [{"Hanzi": "上層部", "Sentence": "上層部に報告する。"}, {"Hanzi": "確認", "Meaning": "check"}]}),
    Case(id="ZH-NTL-402", lang="zh", layer="zh_note_lang", category="O", text="勉強", span="",
         expect={"language": "ja"},
         basis="These are Japanese notes, but a kanji-only word deck holds kana in few of them (one reading of three): "
               "the type reads as not set and is never filled until the user picks Japanese — the safe failure "
               "ZH-NOTE-KANA accepts.",
         status="LIMIT", decision="ZH-NOTE-KANA", source=MADE,
         ctx={"fields": {"Meaning": "study"},
              "notes": [{"Hanzi": "上層部", "Meaning": "upper management"}, {"Hanzi": "確認", "Reading": "かくにん"}]},
         note="Passed while any note with kana decided; flipped when the most-notes rule was built (2026-09-30), "
              "as foreseen — the accepted price."),
    Case(id="ZH-NTL-403", lang="zh", layer="zh_note_lang", category="O", text="晚餐", span="",
         expect={"language": None},
         basis="A Chinese note type of ONE note whose note holds a stray の: its one note is 'most' of it, so it still "
               "reads as Japanese — the price of the most-notes rule on a one-note type (the old ZH-NTL-004's shape).",
         status="LIMIT", decision="ZH-NOTE-KANA", source=MADE, ctx={"fields": {"Sentence": "今天の晚餐超好吃"}}),
    # === the 文 badge, tiers ======================================================================================= #
    Case(id="ZH-BDG-001", lang="zh", layer="zh_badge", category="L", text="研究", span="",
         expect={"badge": None, "ja_rank": None},
         basis="A Chinese word spelled like a Japanese one (研究, 描写) is a Chinese word: it takes no Japanese spoken "
               "rank, so no 文 badge on another language's evidence (fixed 2026-09-25, ENGINE 14; the Japanese table "
               "ranks 研究 1,072).", status="LOCK", source=MADE,
         refs=(zh("ZH-BADGE-01"), kc("ZH-114"),
               "tests/test_modality.py::test_the_reading_badge_goes_by_the_runs_own_language")),
    Case(id="ZH-BDG-002", lang="zh", layer="zh_badge", category="L", text="学习", span="",
         expect={"ranked": True},
         basis="A Chinese word could be judged read-or-heard only against a Chinese spoken-frequency reference; there "
               "is none, so no Chinese word can ever get the 文 badge.", status="LIMIT",
         decision="ZH-NO-SPOKEN-RANKS", source=MADE, refs=(zh("ZH-BADGE-02"),)),
    Case(id="ZH-BDG-003", lang="zh", layer="zh_tier", category="H", text="机", span="",
         expect={"tiers": []},
         basis="机 'machine' and 几 'how many' are different Chinese words. get_tier_label falls back to the Japanese "
               "spelling-alias table on a Chinese run (机 → 几 bridges Japanese spellings), so 机, missing from a "
               "Chinese frequency list, takes 几's tier.", status="TARGET", source=MADE,
         ctx={"freq": {"zh": {"几": 3}}}, refs=(kc("RL-98"),),
         note="Also 道 → 路, 花 → 華, 年 → 歳 (RL-98's probe); 3,743 CJK → CJK aliases."),

    # === M. パターン — the lookup, the shipped data (shared v2) ===================================================== #
    Case(id="ZH-PAT-001", lang="zh", layer="zh_pat_key", category="M", text="學習", span="",
         expect={"key": "学习"},
         basis="A Traditional card finds the Simplified key (§7).", status="LOCK", source=SHARED,
         refs=(zh("ZH-PAT-01"), kc("ZH-77"),
               "modules/junban/tests/test_patterns_zh_lookup.py::test_a_traditional_card_finds_the_simplified_key")),
    Case(id="ZH-PAT-002", lang="zh", layer="zh_pat_key", category="M", text="洗个澡", span="",
         expect={"reason": "phrase"},
         basis="D14: a multi-word card word is skipped in v1 (a phrase).", status="LOCK", source=SHARED,
         refs=(zh("ZH-PAT-02"),
               "modules/junban/tests/test_patterns_zh_lookup.py::test_a_multi_word_card_is_a_phrase_and_an_unknown_word_is_not_found")),
    Case(id="ZH-PAT-003", lang="zh", layer="zh_pat_lines", category="M", text="书", span="",
         expect={"first": "本〜"},
         basis="CC-CEDICT CL:本 for 书: its measure word leads line 1.", status="LOCK", source=SHARED,
         refs=(zh("ZH-PAT-03"),)),
    Case(id="ZH-PAT-004", lang="zh", layer="zh_pat_lines", category="M", text="貓", span="",
         expect={"first": "隻〜"},
         basis="A Traditional card's measure word is 隻 (只 → 隻 needs a numeral in context, Z-F6).", status="LOCK",
         source=SHARED, refs=(zh("ZH-PAT-04"), kc("ZH-75"),
                              "modules/junban/tests/test_patterns_zh_lookup.py::test_a_classifier_renders_in_traditional_beside_its_noun")),
    Case(id="ZH-PAT-005", lang="zh", layer="zh_pat_key", category="M", text="著急", span="",
         expect={"key": "着急"},
         basis="著急 is the Traditional spelling of 着急 (CC-CEDICT 著急 / 着急): to_simplified leaves 著, jieba cuts it "
               "alone, and the card finds no lines.", status="LOCK", decision="ZH-ZHE-READING", source=SHARED, refs=(zh("ZH-PAT-05"),)),
    Case(id="ZH-PAT-006", lang="zh", layer="zh_pat_lines", category="M", text="東西", span="",
         expect={"not_has": ["喫"]},
         basis="A Traditional card's lines are converted with OpenCC's s2t, which writes 吃 as 喫 (ZH-SCR-017): "
               "Backfill would put 喫東西 on a Taiwanese learner's card (蛋糕 → 喫蛋糕, 早餐 → 喫早餐 too).",
         status="LOCK", decision="ZH-S2T-CHI", source=SHARED, refs=(zh("ZH-PAT-06"),)),
    Case(id="ZH-PAT-013", lang="zh", layer="zh_pat_rows", category="M", text="通高 过人 忘带 开唱", span="",
         expect={"forms": {"通高": [], "过人": [], "忘带": [], "开唱": []}},
         basis="None of 通高, 过人, 忘带, 开唱 is a separable verb (not in Wiktionary's list; 忘带, 开唱 no words at "
               "all): their 'splits' are misparses — 法案通过高, 过我的人, 忘了带, 开个唱 — still rows of the shipped "
               "data, a non-word whose every use is a 'split' passing the floor at 100%.",
         status="TARGET", source=SHARED, refs=(zh("ZH-PAT-13"), kc("ZH-25"), kc("SD-97"))),
    Case(id="ZH-PAT-017", lang="zh", layer="zh_pat_lines", category="M", text="洗澡", span="",
         expect={"has": ["洗个澡"]},
         basis="The spec's showcase (§0: 洗澡 洗个澡 16%; D2: 'the forms a learner needs most'). In Tatoeba 洗个澡 is "
               "13 of 83 uses (16%); the shipped set adds written text (177 uses) and FORM_SHARE 10% drops it (7%): "
               "none of 洗澡 结婚 见面 帮忙 吃饭 睡觉 聊天 唱歌 has a split form in shared v2.",
         status="TARGET", source=SHARED, refs=(zh("ZH-PAT-17"),)),
    Case(id="ZH-PAT-018", lang="zh", layer="zh_pat_lines", category="M", text="帮忙", span="",
         expect={"not_has": ["让〜"]},
         basis="The causative 让 (让我帮忙 'let me help') is a verb taking a pivot, not a coverb introducing 帮忙's "
               "argument — UD: 让:VERB ×16 before 我, never ADP.", status="LIMIT", decision="ZH-PAT-V1-LIMITS",
         source=SHARED, refs=(zh("ZH-PAT-18"), kc("ZH-45"))),
    Case(id="ZH-PAT-019", lang="zh", layer="zh_pat_lines", category="M", text="觉得", span="",
         expect={"not_has": ["觉得有点", "觉得大家"]},
         basis="有点 'a bit' is an adverb and 大家 a pronoun, no objects; the context-free tag table files 有点 as a noun "
               "(Z-F4), so 觉得有点 is counted as verb + object — TAG_FIXES never took 有点.", status="TARGET",
         source=SHARED, refs=(zh("ZH-PAT-19"),)),
    Case(id="ZH-PAT-020", lang="zh", layer="zh_pat_lines", category="M", text="行", span="",
         expect={"not_has": ["个〜", "家〜"]},
         basis="A card for 行 xíng 'OK; to walk' should show xíng's lines; the key has no reading, so 行 xíng and 行 háng "
               "('trade; firm': 一家行) share one row, and its line 1 (个〜 · 家〜) is háng's.", status="LIMIT",
         decision="ZH-NO-READING", source=SHARED, refs=(zh("ZH-PAT-20"), kc("ZH-13"))),
    Case(id="ZH-PAT-050", lang="zh", layer="zh_pat_lines", category="M", text="通", span="",
         expect={"not_has": ["通过"]},
         basis="A card for 通 'to go through; to open up' shows the form line '通过 95%': 通过 'to pass; through' is a "
               "word of its own (CC-CEDICT; UD 通过:VERB ×30, :ADP ×30), counted as 通 + the experiential 过 — 12,777 "
               "rows in shared v2 (超 has 超过, 6,379).", status="TARGET", source=SHARED, refs=(kc("SD-96"),)),
    Case(id="ZH-PAT-053", lang="zh", layer="zh_pat_key", category="M", text="不可能", span="",
         expect={"key": "不可能"},
         basis="CC-CEDICT 不可能 'impossible' is a headword; jieba cuts it 不 / 可能 (as UD does: 不:ADV / 可能:AUX ×4), "
               "so the card is a 'phrase' and gets no line. A 不/没 + word rule (Patterns_Quality_Spec §10 F8, 'not "
               "now') would join it — in the analyzer's list too, the key space being one.",
         status="TARGET", decision="ZH-COMPOUND-JOIN", source=SHARED, refs=(kc("ZH-8"),)),
    Case(id="ZH-PAT-054", lang="zh", layer="zh_pat_lines", category="M", text="写", span="",
         expect={"lines": ["colloc: 写小说"]},
         basis="An item holding the name dot · (列夫·托尔斯泰) would split the card's line (the field contract): it is "
               "dropped, the rest kept.", status="LOCK", source=MADE,
         ctx={"store": {"words": [["写", "v", 40]],
                        "patterns": [["写", "colloc", "列夫·托尔斯泰{w}", 12, 9.0, "SP"],
                                     ["写", "colloc", "{w}小说", 10, 8.0, "VO"]]}},
         refs=(kc("ZH-63"),
               "modules/junban/tests/test_patterns_zh_lookup.py::test_an_item_holding_a_name_dot_is_dropped")),
    Case(id="ZH-PAT-055", lang="zh", layer="zh_pat_lines", category="M", text="問題", span="",
         expect={"lines": ["colloc: 沒問題", "frame: 這個〜"]},
         basis="Lines come out in the card's own script (D6): a Traditional card says 沒問題 and 這個〜.", status="LOCK",
         source=MADE,
         ctx={"store": {"words": [["问题", "n", 40]],
                        "patterns": [["问题", "colloc", "没{w}", 12, 9.0, "VO"],
                                     ["问题", "frame", "这个〜", 20, 10.0, "F1"]]}},
         refs=(kc("ZH-76"),
               "modules/junban/tests/test_patterns_zh_lookup.py::test_the_cards_own_spelling_fills_the_word")),
    Case(id="ZH-PAT-056", lang="zh", layer="zh_pat_lines", category="M", text="洗", span="",
         expect={"has": ["洗頭髮"], "not_has": ["頭發"]},
         basis="An item is converted with the card's word in it: 洗头发 in Traditional is 洗頭髮 (hair) — character by "
               "character it would be 頭發 (Z-F6). 洗 is script-neutral, so the user's setting (t) decides.",
         status="LOCK", source=MADE,
         ctx={"script": "t", "store": {"words": [["洗", "v", 40]],
                                       "patterns": [["洗", "colloc", "{w}头发", 12, 9.0, "VO"]]}},
         refs=(kc("ZH-75"),
               "modules/junban/tests/test_patterns_zh_lookup.py::test_an_item_converts_with_the_cards_word_in_context")),

    # --- M. what the Chinese builder counts (patterns_zh.count, before any floor) ---------------------------------- #
    count("ZH-PAT-007", "我把书放在桌子上了。", "书", {"not_has": ["Q:把"]},
          "我把书 is the preposition 把 (Z-F9): a measure word needs a numeral or a demonstrative before it.", "LOCK",
          source=FIX, refs=(zh("ZH-PAT-07"), kc("ZH-32"),
                            "modules/junban/tests/test_patterns_zh_build.py::test_the_preposition_ba_is_never_a_measure_word")),
    count("ZH-PAT-008", "我给他打了三次电话。", "电话", {"not_has": ["Q:次"]},
          "次 is a verbal measure word: it counts the calling, not the phone.", "LOCK", source=FIX,
          refs=(zh("ZH-PAT-08"), kc("ZH-33"),
                "modules/junban/tests/test_patterns_zh_build.py::test_a_verbal_classifier_is_not_a_measure_word")),
    count("ZH-PAT-009", "他洗了个澡就睡觉了。", "洗澡", {"has": ["W:洗了个澡"]},
          "Z-W5 reads the separable verb's split from the sentence string (jieba cuts 洗 / 了 / 个 / 澡).", "LOCK",
          source=FIX, refs=(zh("ZH-PAT-09"), kc("ZH-22"),
                            "modules/junban/tests/test_patterns_zh_build.py::test_a_separable_verb_split_is_a_form")),
    count("ZH-PAT-010", "我们坐下一班车吧。", "下班", {"patterns": {}},
          "下一班 'the next one' is no split of 下班 (Z-F10: 一 alone is no insertion).", "LOCK", source=FIX,
          refs=(zh("ZH-PAT-10"), kc("ZH-23"),
                "modules/junban/tests/test_patterns_zh_build.py::test_the_next_shift_is_not_a_split_xiaban")),
    count("ZH-PAT-011", "他正看著電視。", "看", {"has": ["W:{w}着"]},
          "著 after a verb is the aspect marker 着 (Z-F6).", "LOCK", source=FIXT,
          refs=(zh("ZH-PAT-11"), kc("ZH-57"),
                "modules/junban/tests/test_patterns_zh_build.py::test_traditional_zhe_after_a_verb_is_the_aspect_marker")),
    count("ZH-PAT-012", "我和她一起去看电影。", "看", {"not_has": ["P:和"]},
          "D3: 和 … 一起 is 'and', no coverb.", "LOCK", source=FIX,
          refs=(zh("ZH-PAT-12"), kc("ZH-40"),
                "modules/junban/tests/test_patterns_zh_build.py::test_he_and_gen_as_and_are_not_coverbs")),
    count("ZH-PAT-014", "他是唯一一个理解过我的人。", "过人", {"patterns": {}},
          "The experiential 过 of 理解过, then 我的人 — no split of 过人 'to surpass others' by 我的.", "TARGET",
          source=MADE, refs=(zh("ZH-PAT-14"), kc("ZH-25"))),
    count("ZH-PAT-015", "别忘了带伞。", "忘带", {"patterns": {}},
          "忘了 + 带伞 'forget to bring an umbrella' — no split of a verb 忘带, which doesn't exist.", "TARGET",
          source=TAT, refs=(zh("ZH-PAT-15"), kc("ZH-25"))),
    count("ZH-PAT-016", "她要开个唱会。", "开唱", {"patterns": {}},
          "开 + 个 + 唱会 (a concert): the second character must not start a word — 唱会 is outside jieba's tag "
          "table, so the guard misses it.", "TARGET", source=MADE, refs=(zh("ZH-PAT-16"), kc("ZH-25"))),
    count("ZH-PAT-021", "我们吃了一碗牛肉面。", "牛肉面", {"has": ["Q:碗"]},
          "Z-F5: 83% of measure words arrive fused with their numeral (一碗 牛肉面) — the noun still gets its measure "
          "word.", "LOCK", source=MADE,
          refs=(kc("ZH-31"),
                "modules/junban/tests/test_patterns_zh_build.py::test_measure_words_arrive_fused_and_are_still_counted")),
    count("ZH-PAT-022", "我买了三本书。", "书", {"has": ["Q:本"]},
          "三 本书: the measure word fused with its noun (本书 'this book') is taken apart — 本〜 counts for 书.",
          "LOCK", source=MADE,
          refs=(kc("ZH-5"),
                "modules/junban/tests/test_patterns_zh_build.py::test_measure_words_arrive_fused_and_are_still_counted")),
    count("ZH-PAT-023", "他家有两辆车。", "车", {"has": ["Q:辆"]},
          "两辆车 fused whole (numeral + measure word + noun): 车 gets 辆〜 (车 is filed zg — the measure word says noun).",
          "LOCK", source=MADE,
          refs=("modules/junban/tests/test_patterns_zh_build.py::test_measure_words_arrive_fused_and_are_still_counted",)),
    count("ZH-PAT-024", "他买了一把刀。", "刀", {"has": ["Q:把"]},
          "一把刀: after a numeral 把 is the measure word (the other half of ZH-PAT-007).", "LOCK", source=MADE,
          refs=("modules/junban/tests/test_patterns_zh_build.py::test_the_preposition_ba_is_never_a_measure_word",)),
    count("ZH-PAT-025", "他是个好人。", "好人", {"has": ["Q:个"]},
          "Speech drops the 一 after a verb (是个好人): a bare 个 after a verb is still the measure word.", "LOCK",
          source=MADE, refs=(kc("ZH-34"),
                             "modules/junban/tests/test_patterns_zh_build.py::test_a_bare_ge_after_a_verb_is_a_measure_word")),
    count("ZH-PAT-026", "她跟男朋友结婚了。", "结婚", {"has": ["P:跟"]},
          "The coverb sits across a noun phrase: 跟男朋友结婚 'marry her boyfriend' — 跟〜 for 结婚.", "LOCK", source=MADE,
          refs=(kc("ZH-38"),
                "modules/junban/tests/test_patterns_zh_build.py::test_a_coverb_is_found_across_a_noun_phrase")),
    count("ZH-PAT-027", "他在睡觉。", "睡觉", {"not_has": ["P:在"]},
          "在 right before the verb is the progressive, no coverb (no noun phrase between).", "LOCK", source=MADE,
          refs=(kc("ZH-39"), "modules/junban/tests/test_patterns_zh_build.py::test_the_progressive_zai_is_not_a_coverb")),
    count("ZH-PAT-028", "他被打了。", "打", {"not_has": ["P:被"]},
          "The short passive 被打 names no agent: 被 introduces no argument here (被老师批评 does).", "LOCK",
          source=MADE,
          refs=(kc("ZH-39"), "modules/junban/tests/test_patterns_zh_build.py::test_the_progressive_zai_is_not_a_coverb")),
    count("ZH-PAT-029", "他跟你一样喜欢音乐。", "喜欢", {"not_has": ["P:跟"]},
          "D3: 跟 … 一样 is 'as … as', no coverb of 喜欢.", "LOCK", source=MADE,
          refs=(kc("ZH-40"), "modules/junban/tests/test_patterns_zh_build.py::test_he_and_gen_as_and_are_not_coverbs")),
    count("ZH-PAT-030", "别生我的气。", "生气", {"has": ["W:生我的气"]},
          "The separable 生气 split by 我的: read from the sentence (jieba never sees 生气 in it).", "LOCK", source=MADE,
          refs=(kc("ZH-22"), "modules/junban/tests/test_patterns_zh_build.py::test_a_separable_verb_split_is_a_form")),
    count("ZH-PAT-031", "我们明天见个面吧。", "见面", {"has": ["W:见个面"]},
          "The separable 见面 split by 个.", "LOCK", source=MADE,
          refs=("modules/junban/tests/test_patterns_zh_build.py::test_a_separable_verb_split_is_a_form",)),
    count("ZH-PAT-032", "你看一下。", "看下", {"patterns": {}},
          "看一下 'take a look' is no split of a verb 看下 — a chance pair (190 of 213 loose Tatoeba splits were such).",
          "LOCK", source=MADE,
          refs=(kc("ZH-24"), "modules/junban/tests/test_patterns_zh_build.py::test_chance_pairs_are_not_splits")),
    count("ZH-PAT-033", "他请了个客人来家里吃饭。", "请客", {"patterns": {}},
          "请了个客人 'invited a guest' is no split of 请客: the second character starts a word there (客人).", "LOCK",
          source=MADE, refs=(kc("ZH-23"),
                             "modules/junban/tests/test_patterns_zh_build.py::test_the_next_shift_is_not_a_split_xiaban")),
    count("ZH-PAT-034", "他受了伤。", "受伤", {"has": ["W:受了伤"]},
          "受了伤 is a real split of 受伤 that Wiktionary's list lacks — the rule is data-driven, no list ships.",
          "LOCK", source=MADE,
          refs=(kc("ZH-26"),
                "modules/junban/tests/test_patterns_zh_build.py::test_real_splits_the_wiktionary_list_misses_are_kept")),
    count("ZH-PAT-035", "请打开窗户。", "打", {"not_has": ["W:{w}开"]},
          "打开 is 'open', a word of its own — never 打 + the complement 开.", "LOCK", source=MADE,
          refs=(kc("ZH-49"), "modules/junban/tests/test_patterns_zh_build.py::test_a_lexicalised_compound_is_never_a_form")),
    count("ZH-PAT-036", "他很快就回来了。", "快", {"not_has": ["W:很{w}"]},
          "很快 'soon' is lexicalised — no degree form of 快.", "LOCK", source=MADE,
          refs=("modules/junban/tests/test_patterns_zh_build.py::test_a_lexicalised_compound_is_never_a_form",)),
    count("ZH-PAT-037", "我们周末去听演唱会。", "演唱", {"not_has": ["W:{w}会"]},
          "E5: 演唱会 'a concert' is a noun, never 演唱 + the complement 会.", "LOCK", source=MADE,
          refs=(kc("ZH-50"),
                "modules/junban/tests/test_patterns_zh_build.py::test_a_noun_that_ends_like_a_verb_and_its_complement_is_not_a_form")),
    count("ZH-PAT-038", "我很喜欢这本书。", "喜欢", {"has": ["W:很{w}"]},
          "Degree words go with verbs of feeling too: 很喜欢.", "LOCK", source=MADE,
          refs=(kc("ZH-51"),
                "modules/junban/tests/test_patterns_zh_build.py::test_a_verb_of_feeling_takes_degree_words_and_a_lexicalised_one_never")),
    count("ZH-PAT-039", "他买了书，电话响了。", "书", {"patterns": {"VO:买{w}": 1}},
          "Punctuation is a barrier: 买书 pairs, 书 and 电话 never do across the comma.", "LOCK", source=MADE,
          refs=(kc("ZH-95"), "modules/junban/tests/test_patterns_zh_build.py::test_nothing_pairs_across_punctuation")),
    count("ZH-PAT-040", "我们马上出发。", "马上", {"has": ["DV:{w}出发"]},
          "E6: an adverb pairs with the verb right after it (马上出发).", "LOCK", source=MADE,
          refs=(kc("ZH-60"),
                "modules/junban/tests/test_patterns_zh_build.py::test_an_adverb_pairs_with_the_verb_right_after_it")),
    count("ZH-PAT-041", "在老师的帮助下，他进步了。", "帮助", {"not_has": ["P:在"]},
          "E4: 在老师的帮助下 is the frame 在…下 around 帮助, not 在 introducing its argument.", "LOCK", source=MADE,
          refs=(kc("ZH-42"),
                "modules/junban/tests/test_patterns_zh_build.py::test_zai_closed_by_a_localizer_after_the_word_is_a_frame_not_its_coverb")),
    count("ZH-PAT-042", "在老师的帮助下，他进步了。", "帮助", {"not_has": ["W:{w}下"]},
          "The 下 closes the frame 在…下 (a localizer), no direction complement of 帮助: E4 keeps 在 from counting as "
          "帮助's coverb here, but the complement rule still reads 帮助 + 下 as the form 帮助下.", "TARGET",
          source=MADE, refs=(kc("ZH-42"),),
          note="Found porting this suite. Not in shared v2 (帮助 has no form row): the 10% form share hides it there."),
    count("ZH-PAT-043", "我喝了茶。", "喝", {"has": ["VO:{w}茶"]},
          "TAG_FIXES: the dictionary files 喝 vg, so 喝茶 was never a pair; it is.", "LOCK", source=MADE,
          refs=(kc("ZH-17"),
                "modules/junban/tests/test_patterns_zh_build.py::test_verbs_the_dictionary_files_as_nouns_pair_with_their_objects")),
    count("ZH-PAT-044", "他死时才三十岁。", "死", {"not_has": ["VO:{w}时"]},
          "时 'when' after a clause is no object (8,688 wrong pairings before TAG_FIXES).", "LOCK", source=MADE,
          refs=("modules/junban/tests/test_patterns_zh_build.py::test_verbs_the_dictionary_files_as_nouns_pair_with_their_objects",)),
    count("ZH-PAT-045", "他是一名网球选手。", "选手", {"has": ["Q:名"]},
          "A noun phrase ends in its head: 一名网球选手 counts 名〜 for 选手, never for 网球.", "LOCK", source=MADE,
          refs=(kc("ZH-36"),
                "modules/junban/tests/test_patterns_zh_build.py::test_a_noun_compound_takes_its_measure_word_at_its_head")),
    count("ZH-PAT-046", "我坐一列车去上海。", "车", {"not_has": ["Q:列"]},
          "列车 'train' is one noun that starts with a measure word's character — no 列〜 for 车.", "LOCK", source=MADE,
          refs=(kc("ZH-37"),
                "modules/junban/tests/test_patterns_zh_build.py::test_a_noun_compound_takes_its_measure_word_at_its_head")),
    count("ZH-PAT-047", "经济和社会发展很快。", "发展", {"not_has": ["P:和"]},
          "和 joining two nouns (经济和社会) is 'and', no coverb of 发展.", "LOCK", source=MADE,
          refs=(kc("ZH-40"),
                "modules/junban/tests/test_patterns_zh_build.py::test_he_joining_two_nouns_is_and_and_an_adjective_after_de_has_no_coverb")),
    count("ZH-PAT-048", "这个问题很难回答。", "难", {"uses": 1, "has": ["W:很{w}"]},
          "很难 is kept whole as the analyzer's word (the key), and read as 很 + 难 for counting: a degree form of 难, "
          "whose use it is — no share over 100%.", "LOCK", source=MADE,
          refs=(kc("ZH-4"), kc("ZH-48"),
                "modules/junban/tests/test_patterns_zh_build.py::test_an_out_of_dictionary_fusion_is_split_for_counting_but_stays_one_word")),
    count("ZH-PAT-049", "法案通过了。", "通", {"not_has": ["W:{w}过"]},
          "通过 'to pass' is a word (CC-CEDICT; UD 通过:VERB), not 通 + the experiential 过 — the fused-form rule counts "
          "every 通过 as a use of 通 (as E5's 活动 once did for 活).", "TARGET", source=MADE, refs=(kc("SD-96"),)),
    count("ZH-PAT-051", "他们开了一个碰头会。", "碰头", {"not_has": ["W:{w}会"]},
          "碰头会 'a briefing' is a noun, no 碰头 + the complement 会 — one of ~41 〜会 / 〜光 nouns jieba tags as a "
          "name, an idiom or an abbreviation, out of E5's reach.", "LIMIT", decision="ZH-PAT-V1-LIMITS", source=MADE,
          refs=(kc("ZH-20"),), note="Shared v2 holds 碰头 {w}会 ×7."),
    count("ZH-PAT-052", "我学会了游泳。", "学", {"has": ["W:{w}会"]},
          "学会 'to learn (to master)' is 学 + the result complement 会 — a form of 学; the dictionary files 学会 as a "
          "noun ('a society'), so E5 takes it (U12, the accepted cost).", "LIMIT", decision="ZH-PAT-V1-LIMITS",
          source=MADE, refs=(kc("ZH-18"),
                             "modules/junban/tests/test_patterns_zh_build.py::test_real_forms_jieba_files_as_nouns_keep_their_forms")),
    count("ZH-PAT-061", "你去不去？", "去", {"not_has": ["W:{w}不去"]},
          "去不去 'going or not?' is the A-not-A question, no potential form of 去 (V不C needs a complement other than "
          "the verb). _verb_forms has that guard; jieba fuses the question into one token (去不去, 懂不懂, 回不回来) and "
          "the fused-token path (_fused) lacks it.", "TARGET", source=MADE, refs=(kc("ZH-52"),),
          note="Found porting this suite: ZH-52 was locked by nothing. 懂不懂 → 懂 W:{w}不懂 too."),
    count("ZH-PAT-062", "这对环境产生了很大的影响。", "产生", {"not_has": ["Q:对"]},
          "产生 'to give rise to' is a verb (CC-CEDICT) and 这 + 对 here is 'this' + the coverb 'on'. jieba's tag table "
          "files 产生 as a noun (n), so 这对环境产生 reads as demonstrative + measure word 对 'pair' + noun + head noun.",
          "TARGET", source=MADE, refs=(kc("ZH-17"), kc("ZH-58")),
          note="Found porting this suite: 产生 is missing from TAG_FIXES (the v1 remedy for mis-filed everyday words)."),
    Case(id="ZH-PAT-063", lang="zh", layer="zh_pat_lines", category="M", text="产生", span="",
         expect={"not_has": ["个〜", "项〜"]},
         basis="产生 is a verb, which takes no measure word; filed as a noun by jieba's tag table (ZH-PAT-062), its "
               "shipped card leads with measure words (个〜 44% · 项〜 24%) and noun frames, and none of a verb's lines.",
         status="TARGET", source=SHARED, refs=(kc("ZH-17"),), note="Found porting this suite."),
    count("ZH-PAT-064", "这对环境产生了很大的影响。", "产生", {"has": ["VO:{w}影响"]},
          "产生…影响 'have an effect' is a verb and its object across 很大的 — the builder pairs by adjacency only (no "
          "parser, D12), so it is never counted (and 产生 is filed a noun besides: ZH-PAT-062).", "LIMIT",
          decision="ZH-PAT-V1-LIMITS", source=MADE, refs=(kc("ZH-58"), "Patterns_Chinese_Spec.md §8.3")),
    count("ZH-PAT-065", "我讲了一个有趣的故事。", "故事", {"has": ["Q:个"]},
          "Chinese puts a modifier between the measure word and its noun: 一个有趣的故事 counts 个〜 for 故事.", "LOCK",
          source=MADE, refs=(kc("ZH-35"),
                             "modules/junban/tests/test_patterns_zh_build.py::test_a_measure_word_reaches_its_noun_past_a_modifier_never_past_another_noun")),
    count("ZH-PAT-066", "这是一个人的故事。", "故事", {"not_has": ["Q:个"]},
          "…but never past another noun: in 一个人的故事 the 个 is 人's.", "LOCK", source=MADE,
          refs=(kc("ZH-35"),
                "modules/junban/tests/test_patterns_zh_build.py::test_a_measure_word_reaches_its_noun_past_a_modifier_never_past_another_noun")),
    count("ZH-PAT-067", "这家餐厅的推荐菜很好吃。", "推荐", {"not_has": ["VO:{w}菜"]},
          "Two characters + one is a compound noun ([2+1]: 推荐菜 'recommended dish'), never a verb and its object.",
          "LOCK", source=MADE,
          refs=(kc("ZH-54"), "modules/junban/tests/test_patterns_zh_build.py::test_two_characters_then_one_is_a_compound_never_a_pair")),
    count("ZH-PAT-068", "他用打火机点了一支烟。", "打", {"not_has": ["VO:{w}火机"]},
          "打火机 'a lighter' is 打火 + 机 by jieba's own frequencies — no 打 + 火机.", "LOCK", source=MADE,
          refs=(kc("ZH-55"),
                "modules/junban/tests/test_patterns_zh_build.py::test_a_three_character_word_jieba_reads_as_two_and_one_is_not_a_verb_and_its_object")),
    count("ZH-PAT-069", "我们要维护国家安全。", "维护", {"has": ["VO:{w}安全"]},
          "An object compound pairs at its head: 维护国家安全 keeps 安全 safe, not 国家.", "LOCK", source=MADE,
          refs=(kc("ZH-56"),
                "modules/junban/tests/test_patterns_zh_build.py::test_an_object_that_is_a_noun_compound_pairs_at_its_head")),
    count("ZH-PAT-070", "天气很冷。", "天气", {"has": ["SP:{w}冷"]},
          "Subject + predicate: an adjective that ends its clause (天气很冷) pairs with its noun.", "LOCK", source=MADE,
          refs=(kc("ZH-59"),
                "modules/junban/tests/test_patterns_zh_build.py::test_a_subject_pair_needs_an_adjective_ending_its_clause")),
    count("ZH-PAT-071", "这是中国最大的公司。", "中国", {"not_has": ["SP:{w}最大"]},
          "…and 中国最大的公司 is no subject pair: 最大 describes 公司.", "LOCK", source=MADE,
          refs=(kc("ZH-59"),
                "modules/junban/tests/test_patterns_zh_build.py::test_a_subject_pair_needs_an_adjective_ending_its_clause")),
    count("ZH-PAT-072", "他拿着书走了。", "拿", {"has": ["VO:{w}书"]},
          "An aspect marker may stand between a verb and its object: 拿着书 pairs 拿 + 书.", "LOCK", source=MADE,
          refs=(kc("ZH-57"),
                "modules/junban/tests/test_patterns_zh_build.py::test_any_aspect_marker_may_stand_between_a_verb_and_its_object")),
    count("ZH-PAT-073", "他跟你一样。", "一样", {"has": ["P:跟"]},
          "TAG_FIXES: the dictionary files 一样 as a pronoun; as the adjective it is, 跟〜一样 is its line.", "LOCK",
          source=MADE, refs=(kc("ZH-17"),
                             "modules/junban/tests/test_patterns_zh_build.py::test_words_the_dictionary_misfiles_get_their_lines")),

    # --- M. the key-space contract (the builder's words are the analyzer's) ------------------------------------------ #
    Case(id="ZH-PAT-057", lang="zh", layer="zh_key_parity", category="M", text="他跳过了那道题，对台湾这批大谈特谈。",
         span="", expect={"same": True},
         basis="The builder must key every word exactly as the analyzer does or every lookup silently misses (§17 #1): "
               "it cuts with jieba.cut, never posseg's cut, which differs on one line in five (跳过, 对台, 这批, 大谈).",
         status="LOCK", source=MADE, ctx={"script": "s"},
         refs=(kc("ZH-1"), kc("SD-100"), "docs/assets/corpora/tools/zh/research/exp7_contract.py",
               "modules/junban/tests/test_patterns_zh_build.py::test_the_zh_builder_keys_every_word_exactly_as_the_analyzer_does")),
    Case(id="ZH-PAT-058", lang="zh", layer="zh_key_parity", category="M", text="他就把书放下了。", span="",
         expect={"same": True},
         basis="The contract's reinforce leg on a line that holds 就把: the builder cuts with the same process-wide jieba "
               "the analyzer tuned (the fixtures hold neither pair, so the contract test's reinforce half checks "
               "nothing).", status="LOCK", source=MADE, ctx={"script": "s", "reinforce": True},
         refs=(kc("ZH-12"), kc("ZH-11"), "docs/assets/corpora/tools/zh/research/exp7_contract.py")),
    Case(id="ZH-PAT-059", lang="zh", layer="zh_key_parity", category="M", text="許多學者認為，台灣必須持續學習新技術。",
         span="", expect={"same": True},
         basis="Under t the builder's Simplified cut, sliced from the line converted in context, is the analyzer's "
               "Traditional words.", status="LOCK", source=TWN, ctx={"script": "t"},
         refs=("modules/junban/tests/test_patterns_zh_build.py::test_traditional_text_is_keyed_through_simplified",
               "docs/assets/corpora/tools/zh/research/exp7_contract.py")),
    Case(id="ZH-PAT-060", lang="zh", layer="zh_key_parity", category="M", text="许多学者认为，台湾必须持续学习新技术。",
         span="", expect={"same": True},
         basis="On Simplified text the builder's keys are the as-is analyzer's too (Z-F12).", status="LOCK",
         source=MADE, ctx={"script": "asis"},
         refs=("modules/junban/tests/test_patterns_zh_build.py::test_on_simplified_text_the_keys_are_the_as_written_ones",)),
    Case(id="ZH-PAT-074", lang="zh", layer="zh_key_parity", category="M",
         text="今天是二〇一六年十一月二十三日。刘䶮是南汉的开国皇帝。我哋搭\U000282e2上去。", span="",
         expect={"same": True},
         basis="The builder counts a token as a word by the ChineseTokenizer's own test, so the two share one "
               "definition of a Chinese character: 〇, Extension A (䶮) and B (𨋢) are words to both, or to neither.",
         status="LOCK", source=MADE, ctx={"script": "s"},
         refs=("app/unicode_ranges.py",),
         note="F7 (2026-09-27): both read app/unicode_ranges.py; before, both spelled [一-鿿]."),
    # --- RC1 (2026-09-28): a Chinese caption's lines join as CSS Text 3 joins them --------------------------------- #
    Case(id="ZH-TXT-901", lang="zh", layer="text", category="A", text=srt("我明天\n要去北京"), span="",
         expect={"sentences": ["我明天要去北京。"]},
         basis="A line break between two Han characters is nothing in running text (CSS Text 3, segment breaks): "
               "the cue reads 我明天要去北京。, not 我明天 要去北京。",
         status="LOCK", decision="CUE-LINES", source=MADE, ctx={"ext": ".srt"}),
    Case(id="ZH-TXT-902", lang="zh", layer="text", category="A", text=srt("我买了一件\nT恤"), span="",
         expect={"sentences": ["我买了一件 T恤。"]},
         basis="Beside a Latin letter a line break stays a space (CSS Text 3: only between two wide characters "
               "does it vanish).",
         status="LOCK", decision="CUE-LINES", source=MADE, ctx={"ext": ".srt"}),
]

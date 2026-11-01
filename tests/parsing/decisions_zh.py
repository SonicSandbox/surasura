"""Chinese decisions — merged into the register by decisions.py (docs/agent instructions/Parsing_Suite.md §7).

The two raised with the suite (ZH-TRAD-ASIS, ZH-HMM) live in decisions.py. Here: the Chinese choices already made
and recorded elsewhere (the specs, the code, the user's answers), which the LIMIT cases trade on, and the open
questions the zh adversary's DISPUTED cases raise (debug/parsing_suite/zh, 2026-09-26), one per family. Those families
were decided 2026-09-29 (Chinese_Decisions.md: #1-#10 and N1-N6, the user's leans; #9 the Taiwan-variants branch).
"""
from tests.parsing.decisions import Decision

ALL = (
    # --- decided: what Chinese is in Surasura ------------------------------------------------------------------- #
    Decision(
        "ZH-CJK-TOKENS", "2026-02-09",
        "Which jieba tokens are Chinese words the list counts?",
        "Any token holding a CJK ideograph (Unicode's Han: the Unified Ideographs, Extensions A and on, the "
        "compatibility ideographs, 々 and 〇 — app/unicode_ranges.py; U+4E00–U+9FFF until F7, 2026-09-27) and no kana "
        "letter (Hiragana / Katakana by their Script property — never ・, Chinese's name dot too, or ー: F8i) — "
        "ChineseTokenizer's filter. Nothing checks a dictionary; digits, Latin and symbols are never words.",
        "The Chinese filter since the multi-language restructure (25a687a); Latin and digits are no vocabulary "
        "(known_cases RL-85, RL-94: 'Decision'); a library is one language (data/<lang>/), so kana marks Japanese "
        "noise.",
        "A digit or Latin part falls off a word jieba splits (90后 → 后); typos and OCR errors count as written (旳 "
        "for 的) and a kana lookalike is dropped (ー for 一 leaves 个人 'personal'); a Japanese line in a Chinese "
        "library counts its kanji words (私, 学生). Characters outside the old range (〇, Extension A / B) were the "
        "range's gap, not this choice — counted since F7.",
        "decided", ("app/analyzer.py ChineseTokenizer", "debug/parsing_suite/known RL-85, RL-94, RL-99")),
    Decision(
        "ZH-NO-READING", "2026-09-24",
        "Does a Chinese word's key carry its reading, so homographs (行 xíng / háng, 得 dé / de / děi, 了 le / liǎo) "
        "are separate words?",
        "No — a Chinese word is keyed (word, \"\"): jieba gives no pinyin (pypinyin would be a new dependency), and "
        "the list, known words, cards and パターン all key it so.",
        "Patterns_Chinese_Spec §1 ('Not a reading/pinyin feature … 行 (xíng / háng) stays one row'), §7, §8.3; "
        "tests/test_reading_key.py::test_chinese_rows_are_unchanged.",
        "Homographs share one row, one known status and one パターン field: 行's line 1 is háng's (个〜 29% · 家〜 29%); "
        "得 děi 'must' counts with the particle de and 得到's dé.",
        "decided", ("Patterns_Chinese_Spec.md §1, §7, §8.3", "debug/parsing_suite/known ZH-13")),
    Decision(
        "ZH-OPENCC-FORMS", "2026-09-18",
        "Under the Simplified / Traditional setting, which Traditional: OpenCC's generic standard forms, or what "
        "Taiwan and Hong Kong write (裡, 麵, 台, 軟體)?",
        "OpenCC's generic s2t / t2s (ver.1.4.2), through Simplified — t = s2t(t2s(x)), length-preserving; regional "
        "vocabulary is out of scope in v1. Amended 2026-09-29 (ZH-S2T-CHI): Traditional characters are Taiwan's standard "
        "forms where OpenCC's is a variant (OpenCC's TWVariants.txt).",
        "Chinese_Script_Conversion_Spec Q2, 'Generic only in v1 — confirmed by the user 2026-09-18'; §12: through "
        "Simplified every word lands on one spelling (牛肉麵 / 牛肉面) and shared characters keep their meaning (里長, "
        "准許); gotcha 7: S→T is ambiguous, OpenCC's phrases fix the common cases, not all. The standard-form part "
        "reopened by ZH-S2T-CHI, 2026-09-29.",
        "A character out of its phrase can take the wrong source (the surnames 范 → 範, 余 → 餘); variants OpenCC "
        "leaves alone stay apart (祇 ≠ 只); regional words stay two words (軟體 / 软件). The Taiwan table "
        "(built 2026-09-30) leaves ZH-SCR-034 (一臺電腦: Taiwan writes 台 and 臺 both), ZH-SCR-018 (范 / 余) and "
        "ZH-SCR-026 (祇) as they were; ZH-SCR-008, -010, -022 and -029 are right since.",
        "decided", ("Chinese_Script_Conversion_Spec.md Q2, §12, gotcha 7", "Chinese_Build_Spec.md Z7")),
    Decision(
        "ZH-CANTONESE-OUT", "2026-09-24",
        "Is Cantonese written in Chinese characters (嘅, 咗, 我哋, 冇, 係) read as a language of its own?",
        "No — Chinese means Mandarin: jieba's dictionary and OpenCC's tables are Mandarin's, and Cantonese text is "
        "read with them as it comes.",
        "Patterns_Chinese_Spec §1 ('Not Cantonese or Classical Chinese … a Cantonese card finds nothing or "
        "little'), §18; no Cantonese segmenter is a dependency (CLAUDE.md §4).",
        "Cantonese words split (我哋 → 我 / 哋) — 㗎 and 𨋢, outside the tokenizer's old range, were dropped until F7 "
        "(2026-09-27); under the Traditional setting Cantonese characters take Mandarin forms (晒 → 曬, the copula "
        "係 → 系).",
        "decided", ("Patterns_Chinese_Spec.md §1, §18",)),
    Decision(
        "ZH-BOUNDARY-CHARS", "2026-07-30",
        "How does the Chinese tokenizer see a sentence end in a token?",
        "Per character: a token holding any character of the zh boundary set ends the sentence (a terminator "
        "glued to a symbol — ➡。, ｡。 — still splits); what closes it — more terminators, closing quotes and "
        "brackets, spaces — stays with it (UAX #29 SB8a / SB9: ？？, ？！, “是黑车吗？”), a line end ending it where "
        "it stands; a fragment with no CJK left after a split is dropped as debris.",
        "v2.1 ('Endings glued to a symbol were swallowed', PRE_RELEASE_FEATURES_v2.1; 52c38d4); "
        "analyzer.ChineseTokenizer.tokenize_sentences. Which characters are in the set is ZH-BOUNDARIES. F4 "
        "(2026-09-27): a doubled terminator lost its second mark as debris and a closing ” opened the next sentence "
        "— the closing run now stays with its sentence.",
        "The half-width . can't join the set — jieba keeps 3.5 as one token, so every decimal would split.",
        "decided", ("PRE_RELEASE_FEATURES_v2.1.md", "debug/parsing_suite/known RL-3")),
    Decision(
        "ZH-NO-SPOKEN-RANKS", "2026-09-25",
        "Can a Chinese word get the 文 (reading-word) badge?",
        "No — the spoken-rank table is Japanese words' (through UniDic), so a Chinese run loads none (ENGINE 14); "
        "Chinese has no spoken-frequency reference of its own.",
        "Patterns_Quality_Spec §15.9, latent defect 32: the Japanese ranks badged Chinese words (描写, 研究) on "
        "another language's evidence. Patterns_Chinese_Spec D9 / §16.2: the shareable spoken side is too small for "
        "a register either (3,457 of the 6,000 commonest words would lean written).",
        "No Chinese word is ever badged 文, even one met only in writing.",
        "decided", ("Patterns_Quality_Spec.md §15.9", "tests/test_modality.py")),
    Decision(
        "ZH-PAT-V1-LIMITS", "2026-09-25",
        "Which errors of the Chinese パターン builder (v1, builder 2) are accepted?",
        "Those no v1 rule reaches, judged at the gate by the agent standing in for the user (§4.1): adjacency only "
        "(no parser, D12) — 产生…影响 across 很大的 is no pair; the causative 让 counted as a coverb (觉得 让〜 83%, "
        "帮忙 让〜 27%); rare nouns that end like verb + complement left (碰头会); 学会 filed as a noun, so 学 loses "
        "the form 学会 (U12). Not accepted: an everyday word the tag dictionary mis-files — TAG_FIXES is the v1 "
        "remedy (~50 entries), so those cases stay TARGET.",
        "Patterns_Chinese_Spec §8.3, §16.1 WP-Z6 (97 good, 50 noisy, 2 wrong of 149 cards), §20 'Left'; "
        "Patterns_Quality_Spec §10 E5 (U12), §15.7.",
        "Those lines stay wrong or missing on real cards until a better tagger or a parser (§8.4, the user's "
        "approval): 帮忙's line 1 shows 让〜, 碰头 shows 碰头会, 学's card lacks 学会.",
        "decided", ("Patterns_Chinese_Spec.md §8.3, §16.1, §20", "Patterns_Quality_Spec.md §10 E5")),

    # --- open: the zh adversary's DISPUTED families ------------------------------------------------------------ #
    Decision(
        "ZH-DICTIONARY", "2026-09-29",
        "jieba's dictionary holds phrases no dictionary lists as words (吃了饭, 见了面, 一碗, 二十五岁, 电影吧, 喝咖啡, "
        "QQ号 — 625 numeral / demonstrative + measure-word pairs alone): split them into their words? And where "
        "CC-CEDICT lists a unit that UD splits (一个, 这个, 不可能, 看完), which wins?",
        "The narrow split, with the count rule (the user, 2026-09-30 ~19:45, on the measured numbers: 'All of the "
        "mentions look good, your lean is good'): a jieba dictionary entry CC-CEDICT doesn't list is read as the words "
        "jieba's own route finds among those both dictionaries hold — never the whole entry — when those words hold "
        "grammar where grammar stands: an aspect marker (了 着 过) after a verb or an adjective, or inside an entry jieba "
        "tags a verb (吃了饭, 去过, 结了婚); 的 after a word (漂亮的); the adverb-making 地 after an adjective, an adverb or "
        "a status word of two characters or more, or a doubled word — never after a verb, a noun or one character "
        "(认真地, 慢慢地 split; 用地 'land use', 满地, 地安门 whole); the complement 得 after a verb or an adjective, or "
        "inside a verb entry (跑得快; 种瓜得瓜, 录得 whole); a sentence-final particle after a verb, an adjective, a noun "
        "or a pronoun (电影吧, 看吧; 甚么 whole); 很 before a word (很多, 很着急); a number, or a one-character pronoun "
        "(这 那 每 某), before a measure word (一碗, 这次). A number written in pieces is one piece (一万二千 + 名). "
        "jieba's name-tagged entries and doubled words stay whole. Where CC-CEDICT lists a unit the dictionary wins "
        "(这个, 每个, 出租车, 酒吧, 一下, 一些, 一样 whole) — except a count: a number + a measure word (jieba's measure "
        "tag, or a CC-CEDICT classifier sense) that the UD Chinese treebanks cut after the number in most of their "
        "uses, at least twice — 33 units (一个, 一次, 一种, 一家 …; the months, 一方面, 两岸 have no measure word and stay "
        "whole). One cut every Chinese caller reads (analyzer.chinese_cut: the tokenizer, the パターン builder and its "
        "lookup); its table is derived at build time (scripts/build_cedict_data.py) into its own module "
        "(app/cedict_data.py, CC BY-SA 4.0), credited in README. Built 2026-09-30 (step 4, Z4).",
        "The user, 2026-09-29, took the lean (Chinese_Decisions.md #3). WORD-IDENTITY (the dictionaries decide what a "
        "word is — CC-CEDICT is named there — not a tagger's lexicon) and JT-EXPRESSIONS (a phrase joined in the "
        "tokenizer takes its pieces' uses from every other sentence) directly; CJ-B's mirror ('a compound in neither "
        "list stays in pieces'); JT-NUMERAL-WORDS + NUMERALS-NOT-WORDS by analogy for the count (二日, 一匹 stay numeral "
        "+ counter though the dictionaries list them). The zh adversary (2026-09-26): 625 of jieba's 664 numeral / "
        "demonstrative + measure-word entries are no CC-CEDICT word, and HMM off doesn't touch them. The count's "
        "yardstick: CC-CEDICT can't tell 一个 'a' (a count) from 一下, 一样, 一起, 一眼 (words) — its 一个 even glosses "
        "'the whole (afternoon)' —, while the UD treebanks (GSDSimp, HK, CFL; read-only count 2026-09-29) cut 一 + 个 "
        "342 times and never keep it whole, 一次 35 / 0, 一种 85 / 0, and keep 一些 (82 whole / 0 cut), 一样 (38 / 0), "
        "一起 (59 / 1), 一下 (8 / 1) whole: the treebanks the decisions doc named as the boundary yardstick for this "
        "very disagreement. Measured 2026-09-30 on 3,000 lines of general text (lane Z, MEASURE.md §2.2), 100 random "
        "splits read by hand each: the broad split 80% right (84% with the 很 class), the narrow one 89% (94%), the "
        "narrow one as built — the position tests and the count rule — 92% (98%), 814 splits per 3,000 lines; sparing "
        "jieba's name tags is right (100 random name-tagged entries CC-CEDICT lacks: 49 names, 18 partial names, 10 "
        "words, 23 not names). The treebanks alone cut a number off almost every word (67 units, half of them words: "
        "the months, 一方面, 两岸), hence the measure-word test.",
        "Real compounds jieba has and CC-CEDICT lacks become their pieces — 很快 'soon' is 很 + 快, its 'soon' counted "
        "as 快, which CC-CEDICT also glosses 'soon' (ZH-PRT-007) —, as Japanese 滞在先 stays 滞在 + 先; how many is "
        "what the hand-read sample shows. 一个 'a' and 三点 'three o'clock' are never list words (个 and 点 get their "
        "uses). jieba's name tags are noisy (喝咖啡, 考完试, 太贵 are tagged names — Patterns_Chinese_Spec Z-F4): what "
        "sparing them keeps is measured. A 成语 CC-CEDICT lacks is split into its words (池鱼之殃). CC-CEDICT (CC BY-SA "
        "4.0) and the treebanks' numeral units (CC BY-SA 4.0) become shipped data with their credits; rebuilding the "
        "table needs the SCHEMA / ENGINE bumps (no signature holds it). Joins jieba misses (不可能, 这下, 一下儿) are "
        "ZH-COMPOUND-JOIN. As built (narrow): jieba's phrase entries that hold no grammar stay whole (管理制度, 风景区, "
        "喝咖啡, 一本 + 本书 — about 2,800 right splits per 3,000 lines the broad split made and this doesn't); the 很 / 最 "
        "+ adjective class splits (很多, 很大 — the treebanks keep 很多 whole 61 times of 62); the count rule cuts words "
        "whose number counts nothing but that take a measure word — 一系列, 一度, 一道, 一手, 一方, 一行, 一身, 一面, "
        "二手, 四处, 三级, 二级, 二代, 五代, 二次, 二号, 三条, 四条, 一代, 一刻 (about 3% of the splits) —; a pronoun + a "
        "measure word reads 咋样 'how' as 咋 + 样.",
        "decided", ("Chinese_Decisions.md #3", "Chinese_Build_Spec.md Z4",
                    "debug/parsing_suite/zh cases.md (segmentation, measure words, separable verbs; Aggregates)",
                    "Parsing_Robustness_Suite_Scope.md §2 O")),
    Decision(
        "ZH-LEMMA", "2026-09-29",
        "Does Chinese get lemmas — a form counted as its base word (休息休息 → 休息, 开开心心 → 开心, 哈哈哈哈哈 → 哈哈, "
        "a split separable verb 洗了个澡 → 洗澡) — or is every jieba token its own word, as before?",
        "Doubled forms count as their base when the base is a CC-CEDICT word — an AABB token (开开心心 → 开心, "
        "高高兴兴 → 高兴, 干干净净 → 干净), a two-character word said twice (休息休息 → one use of 休息), a run of one "
        "character cut by length (哈哈哈哈哈 → one 哈哈, CC-CEDICT's) — keyed to the base, the text's own spelling kept "
        "as the surface (the list's Forms show 开开心心). An AABB form CC-CEDICT lists with meanings mostly its base "
        "lacks stays its own word (马马虎虎 'so-so, tolerable' beside 马虎 'careless'; 形形色色 'all kinds of') — "
        "OGO-EXCEPTIONS' own-meaning test, its glosses matched by stem (方方面面 'all aspects' is 方面 'aspect'); a "
        "form made only of numerals is the numbers' (三三两两: ZH-NUMERALS). A word said twice is any word the cut keeps "
        "whole. A run of one character folds only when CC-CEDICT's shortest run of it is a sound or a laugh (哈哈, 呵呵, "
        "汪汪 — never 好好 'well', 太太 'wife', 爱爱) — the user, 2026-09-30 ~19:45, took both leans: 'All of the "
        "mentions look good, your lean is good', accepting too that 爸爸妈妈 'dad and mom' counts as 爸妈 'mom and dad' "
        "(74 uses in the general text read; 爸爸 and 妈妈 lose them — no shape rule tells it from 大大小小 → 大小). A "
        "separable verb split by other words (洗了个澡) stays in pieces until the Phrase Bundle. One step of the one "
        "Chinese cut every caller reads (the analyzer, the token store, known words, the sentence dictionary, Junban, "
        "the パターン builder). Built 2026-09-30 (step 4, Z6): 403 doubled forms fold, 40 keep a meaning of their own, 54 "
        "sounds; 93 of 100 folds read at random in general text are right (94 with jieba's guesses off, 97 without the "
        "accepted 爸爸妈妈).",
        "The user, 2026-09-29, took the lean (Chinese_Decisions.md #6). By analogy: UNIDIC-LEMMA (one row per word "
        "however it is written), U2-NOMINALIZER (a derived form counts as its base, even one JMdict lists — ADJ-SA's "
        "優しさ), STRETCH-MARKS (a stretched word is its word — a lengthened laugh is the same thing), CJ-1B (ドキッと "
        "is ドキッ's row); directly JT-EXPRESSIONS / UNIDIC-SHORT-UNITS for separable verbs. Before it jieba's "
        "dictionary decided by accident: 高高兴兴 and 开开心心 were rows of their own, 休息休息 counted 休息 twice for "
        "one use, 哈哈哈哈哈 was two rows. The own-meaning exception follows OGO-EXCEPTIONS (a listed form with a "
        "meaning the bare word lacks is a word of its own): the plain lean folds 马马虎虎 into 马虎 and breaks "
        "ZH-IDM-005, a LOCK the decisions doc didn't list.",
        "The vivid doubled form never gets a row or a card of its own (高高兴兴, though CC-CEDICT lists it); a card for "
        "it lands on the base (as 努力する → 努力). New code with its own errors, guarded by the base being a "
        "dictionary word: 一个个人 is 一个 + 个人 (ZH-RED-009); 家家户户 has no base 家户 and is untouched; "
        "single-character doubles (人人, 看看, 慢慢) are words of their own, out of scope. A word said twice for "
        "emphasis is one use (谢谢谢谢). 洗澡's split uses stay off the list (パターン's forms line still shows 洗个澡). "
        "A name of a doubled syllable or two words that meet are read as one word said twice (比奧比奧 'Biobío' is one "
        "比奧, 本部 + 本部长 one 本部; 3 of 100 folds with jieba's guesses on), the pandas 团团 + 圆圆 are 团圆, and 吃吃吃 "
        "'eat, eat, eat' is 吃吃 'giggle' (jieba already cut it so).",
        "decided", ("Chinese_Decisions.md #6", "Chinese_Build_Spec.md Z6",
                    "debug/parsing_suite/zh cases.md (reduplication, separable verbs)")),
    Decision(
        "ZH-NUMERALS", "2026-09-29",
        "A composite numeral (三千五百, 百分之十二, 二十五): one list word, its characters (三 千 五 百), or not counted?",
        "Not counted: a token made only of numeral characters — the numerals of Chinese running text (GB/T "
        "15835-2011: 〇 零 一 二 三 四 五 六 七 八 九 十 百 千 万 亿, with 萬 億) and 两 / 兩 'two' (the numeral a count "
        "takes) — is never a list word nor an unknown in a sentence; one CC-CEDICT lists as a common word (lower-case "
        "pinyin) with a meaning that counts nothing stays a word (千万 'by all means', 万一 'just in case', 一一 'one by "
        "one', 二百五 'idiot') — the table's short list, read in full by hand with the build. The financial forms (壹 贰 "
        "… 拾 陆) are no numerals here (拾 'pick up', 陆 'land' are words), nor 几 'how many' or 半 'half'. One word "
        "test every Chinese caller reads (analyzer.chinese_word: the tokenizer, the パターン builder's word flag). A "
        "numeral inside a fused token is reached by ZH-DICTIONARY's split first (一碗 → 一 / 碗). 'A hundred or so' is "
        "a quantity (the user, 2026-09-30 ~19:45, took the lean: 'your lean is good'): 百十 counts as a number, so 19 "
        "words stay — 一一, 一五一十, 一百一, 七七八八, 万一, 万万, 万千, 三七, 三七二十一, 三三两两, 三八, 二百五, 五七, 五五, "
        "五四, 八八六, 千万, 千千万万, 四一二 (app/cedict_data.py's NOT_COUNTS). With the table unreadable no number is "
        "dropped. Built 2026-09-30 (step 4, Z5).",
        "The user, 2026-09-29, took the lean (Chinese_Decisions.md #8). NUMERALS-NOT-WORDS ('Bare numbers … are never "
        "list words and never count as unknown words in a sentence', 2026-09-27) and JT-NUMERAL-WORDS (a word whose "
        "numeral counts nothing is still a word, checked against the dictionary) directly. jieba's numeral tag can't "
        "be the test as UniDic's class was — context-free and noisy (十分 'very' is tagged a numeral, Z-F4) — and "
        "Unicode's numeric property isn't either: it numbers the financial forms (拾 10, 陆 6, 参 3) and gives 兩 2 but "
        "两 nothing (Python 3.11's unicodedata). GB/T 15835's numerals are the standard's own list. 两 joins as "
        "Japanese's 何 / 数 / 幾 counting did; 几 stays a word ('how many?' is vocabulary, as 何 alone is in Japanese).",
        "A sentence full of numbers reads easier than it is (the Japanese price). 一 'as soon as' (一…就…) and 一 "
        "'whole' never count; 十一 'eleven' is no word though CC-CEDICT also lists 十一 'National Day' (a name). Words "
        "that hold other characters are untouched (三心二意, 一模一样, 十分, 十几 'more than ten', 第一 'first'); an "
        "ordinal is 第 + a number (第三十二届 → 第 … 届, though the split may leave 第三 'third', a CC-CEDICT word). "
        "The gloss reading that keeps 千万 is a reading of CC-CEDICT's English (a number or a quantity counts; anything "
        "else counts nothing): its list is shown to the user with the build. Accepted 2026-09-30: 千万 keeps its 'ten "
        "million' uses too (a homograph — 2 of its 15 uses in 20,000 general lines follow a number: 一千萬), and 一一 "
        "inside 九一一 (9/11) stays a word. Measured: 6,271 numbers-only uses in 20,000 lines of general text stop "
        "being words, 31 stay (千万 15, 一一 11, 万一 3, 千千万万 2).",
        "decided", ("Chinese_Decisions.md #8", "Chinese_Build_Spec.md Z5", "debug/parsing_suite/zh ZH-NUM-08, "
                    "ZH-NUM-12", "Parsing_Robustness_Suite_Scope.md §2 D")),
    Decision(
        "ZH-BOUNDARIES", "2026-09-29",
        "Which characters end a Chinese sentence: …… (a sentence-final ellipsis in fiction, or halting speech "
        "mid-sentence), ；(GB/T: clauses of one sentence), ．(a full-width stop — and Taiwan's name interpunct "
        "瑪麗．居禮), every line end (a PDF's hard wrap)?",
        "…… and ；/ ; no longer end a Chinese sentence, ．stays out, and a line end still ends one: the zh set is "
        "。｡！？!?\\n — settings_manager's default, the analyzer's own and the tokenizer's fallback alike. A saved zh set "
        "that is the old default (。｡！？!?\\n；;…… in any order, with or without ｡) is moved to the new one as settings "
        "load — saved sets only ever gained characters before —, and a hand-edited set is left alone. A subtitle cue "
        "ending in ；runs on into the next cue, as one ending in a comma does (analyzer.close_cue). Built in step 4 "
        "(Chinese_Build_Spec.md Z1).",
        "The user, 2026-09-29, took the lean (Chinese_Decisions.md #1), following the Japanese principles: F4 "
        "(sentence ends per UAX #29, where … and ； end nothing and a line break ends one) and JA-ELLIPSIS (… 'is as "
        "often a pause') directly, and GB/T 15834-2011 agrees — 省略号 marks omission or halting speech, 分号 joins the "
        "clauses of one sentence; LINE-BREAK-BOUNDARY for line ends. ．by analogy from a measurement (2026-09-29, "
        "read-only): in ~150 MB of general Chinese text ．sits between two Chinese characters 994 times and ends a line "
        "3 times; of 40 read in one news file, about 35 are a foreign name's dot (達爾文．庫克), 3 a title's, 2 a "
        "sentence end — Chinese writes it as the name dot (間隔號), where Japanese added it (F4) as the full stop "
        "Japanese writes. Reverses the register's earlier leans (keep ；for shorter examples; add ．).",
        "Longer examples: a …… pause or a ；clause stays inside one sentence, so fewer sentences are short enough to "
        "be i+1 (the report's display window trims long ones); a novel's sentence-final …… followed by more text on "
        "the same line runs on (他走了……我们也走吧。 is one example — ZH-SPL-402; Japanese pays the same with "
        "そうか…じゃあ行くか。). The rare ．that ends a sentence (那是她的车．) doesn't (ZH-SPL-004); a hard-wrapped "
        "sentence stays cut at the line end (ZH-SPL-009); the half-width . stays out (ZH-SPL-005, ZH-BOUNDARY-CHARS). "
        "A learner who wants ；back adds it to settings.json — a hand-edited set is never migrated.",
        "decided", ("Chinese_Decisions.md #1", "Chinese_Build_Spec.md Z1", "Parsing_Suite_Findings.md §5 F4",
                    "debug/parsing_suite/known SD-30, RL-10", "debug/parsing_suite/zh ZH-BOUND-02..04, 09")),
    Decision(
        "ZH-S2T-CHI", "2026-09-29",
        "Under the Traditional setting OpenCC writes 吃 as 喫 (喫飯; Backfill's 喫東西 on a Traditional card) — and 为 as "
        "爲, 里 as 裏, 众 as 衆, 面 as 麪: keep OpenCC's generic forms, or write Taiwan's standard characters?",
        "Taiwan's standard characters wherever OpenCC's form is only a variant of one: under the Traditional setting "
        "every character OpenCC's Taiwan-variants table maps (TWVariants.txt, OpenCC ver.1.4.2, one character to one) "
        "is written in its Taiwan form after the generic table (喫 → 吃, 爲 → 為, 裏 → 裡, 衆 → 眾, 麪 → 麵, 着 → 著), "
        "by a rule — never a one-word exception; regional vocabulary (软件 → 軟體) stays out, as Q2 chose. Built in "
        "zh_script's data (scripts/build_zh_script_data.py), so the tokenizer, the report and Backfill's lines agree "
        "(Chinese_Build_Spec.md Z7).",
        "The user, 2026-09-29: 'switch probably. You're ok to download for that'. U16-SPELLINGS (a word under its commonest spelling) and NFKC-READING / "
        "STRETCH-MARKS (the form the standard writes); WORD-IDENTITY rules out the 吃-only exception. The download: "
        "the user's OK 2026-09-29; TWVariants.txt fetched 2026-09-30 at OpenCC's ver.1.4.2 tag "
        "(docs/assets/opencc/FETCHED.json: 986 bytes, sha256 e187278e…). Measured: Taiwanese news read as Traditional "
        "keeps all but 6 of its characters (14 with the generic forms); over 30,000 Traditional lines of news and "
        "encyclopedia text 1.22% of the characters came out unlike the text, 0.44% now (it stops 為 → 爲 7,412 times, "
        "adds 着 → 著 199). The user took the lean on those numbers, 2026-09-30 ~19:45: 'All of the mentions look good, "
        "your lean is good'. Built 2026-09-30 (step 4, Z7): 39 variants; Taiwan's 簷, 痺, 睪, 潀 read back as "
        "Simplified where the generic table lacked them, never 著 (著名 'famous' is Simplified's own — Taiwan's 著 for 着 "
        "is ZH-ZHE-READING's).",
        "Reopens ZH-OPENCC-FORMS (amended below). Hong Kong learners get Taiwan's forms where Hong Kong differs (裡 "
        "where HK writes 裏); 着 is written 著 (Taiwan's 看著), which ZH-ZHE-READING's question meets; every Traditional "
        "user's words change once.",
        "decided", ("Chinese_Decisions.md #9", "Chinese_Build_Spec.md Z7", "Chinese_Script_Conversion_Spec.md Q2")),
    Decision(
        "ZH-CARD-FIELD", "2026-09-29",
        "What of a Chinese card's word field is the word: an annotation (pinyin in parentheses 学习 (xuéxí), a "
        "reading after a space, both scripts 学习 / 學習) — and a particle written on (认真地, 漂亮的)?",
        "Read the Japanese way (anki_match.card_word, language 'zh'): the field's first line, in NFKC as the tokenizer "
        "reads text; notes in brackets dropped (学习 (xuéxí), 学习（xuéxí） → 学习); the first word where 、，, ／/ ；; "
        "or a space parts several (学习 xuéxí, 学习 / 學習 → 学习); the punctuation around it gone (「学习」). A name's "
        "dot never parts it (约翰・列侬, 哈利·波特 — Chinese's 间隔号, as the Japanese reading keeps ジョン・スミス "
        "whole). And a card read alone as ONE word + 的 or 地 is that word (认真地 → 认真, 漂亮的 → 漂亮 — "
        "anki_match.one_word, card_key via L7), in Junban, the report's 'In Anki' label and Backfill alike; the user's "
        "'no' still wins. Built 2026-09-30 (step 4, Z2): Junban reads a Chinese card alone with the analyzer's own "
        "Chinese tokenizer in the list's script, for this placement only (its sentence is not read: Chinese cards the "
        "list doesn't hold still go by FreqSort).",
        "The user, 2026-09-29, took the lean (Chinese_Decisions.md #2). F8f ('a card is one word', 2026-09-27) and "
        "MATCH-ENDINGS ('I'd prefer them to be one word', 2026-09-26) directly: 的 after a word does な's job, 地 does "
        "に's. Since F8f card_word is split by language, so the Chinese branch is new code and Japanese doesn't move — "
        "the register's old worry ('stripping (…) would change Japanese too') no longer holds. Before it all four "
        "shapes matched nothing (Junban filed them 'not on the list', the label never marked them, Backfill found no "
        "lines); 学习[xue2 xi2] already worked (ZH-CRD-001).",
        "A second spelling in the field is unused (学习 / 學習 reads 学习 — a Traditional list under as-is then meets "
        "it only through ZH-KEY-001's fallback, a TARGET of its own). The ending rule reads the card with the "
        "tokenizer and takes ONE word + 的 / 地 only, so a word ending in those characters is untouched (目的, 土地 are "
        "one token), but a card mined as 我的 'my' lands on 我 'I' — the user's 'one word unless there's a good "
        "reason', as お茶する → お茶. Endings beyond 的 / 地 (吃了, 去过) are ZH-CARD-ENDINGS, open.",
        "decided", ("Chinese_Decisions.md #2", "Chinese_Build_Spec.md Z2",
                    "debug/parsing_suite/zh ZH-CARD-02, 03, 06, 10", "Anki_Match_Consistency_Scope.md")),
    Decision(
        "ZH-KNOWN-PIECES", "2026-09-29",
        "A known Chinese term jieba cuts into several words (不得其门而入 → 不得 / 其门 / 而入): mark every piece "
        "known, or only the term?",
        "Every piece, as in Japanese — today's behaviour, no code change: load_known_words marks each token of a known "
        "term known (knowing 不得其门而入 marks 不得 known, and with the guesses off 其 'its', 门 'door', 而 'and', 入 "
        "'enter'). Keeping the idiom whole is a segmentation question (ZH-COMPOUND-JOIN).",
        "The user, 2026-09-29, took the lean (Chinese_Decisions.md #5). KNOWN-PIECES (2026-09-25, "
        "Patterns_Quality_Spec §6.2a) directly: 'a learner who knows the whole mostly knows its parts', its price "
        "accepted by name — 'お金 marks 金 gold' — exactly 不得's case; known phrases do the same (AM-68: 恩を売る makes "
        "恩, を, 売る known). Both languages share one reader (load_known_words). Reverses the register's earlier lean "
        "(only pieces that are dictionary words), which behaves the same once the guesses are off.",
        "不得 'must not' counts as known through an idiom (as お金 → 金): a learner who only memorised the idiom loses "
        "不得 as a new word. While the guesses are on, the guessed non-words (其门, 而入) marked known leave the list — "
        "a side gain.",
        "decided", ("Chinese_Decisions.md #5", "Patterns_Quality_Spec.md §6.2a", "debug/parsing_suite/zh ZH-CARD-12",
                    "debug/parsing_suite/known AM-68")),
    Decision(
        "ZH-NOTE-KANA", "2026-09-29",
        "D7 rule 2 reads a note type as Japanese when ONE of its notes has a kana letter in any field: keep 'any "
        "note', or ask more — most notes, or kana in the word field?",
        "Most notes: Backfill reads a note type as Japanese (D7 rule 2) only when more than half of its notes in scope "
        "hold a kana letter in some field; a stray の or ツ leaves a Chinese type 'not set' — never filled until the "
        "user chooses (backfill.note_language). The user's choice still decides first; the per-note kana guard (S4) is "
        "unchanged. Built 2026-09-30 (step 4, Z2).",
        "The user, 2026-09-29, took the lean (Chinese_Decisions.md #7). No parsing decision covers it; the data-safety "
        "rules do, by analogy: the user's cards are user data (CLAUDE.md §4); D7's own rule 3 (nothing is filled into "
        "a note type whose language is not set); when unsure, ask rather than act (LABEL-VS-JUNBAN, MATCH-ENDINGS: "
        "'the user's no always wins'). Japanese stays as it is: the user's Lapis type holds 1,457 notes, every one "
        "with kana (debug/anki_backfill_baseline_ja.json). Taiwanese writing uses の for 的 (今天の晚餐超好吃) and a "
        "shrug ¯\\_(ツ)_/¯ holds ツ: one such note made an unset Chinese type Japanese, and a Japanese session would "
        "fill it (68% of kanji-only Japanese words are Chinese words too, Z-F11).",
        "A Japanese note type whose kana sits in few of its notes (a kanji-only word deck with no reading or sentence "
        "field) shows 'Language?' and is never filled until the user picks — a safe failure (nothing written) instead "
        "of wrong-language lines on cards (ZH-NTL-402). A one-note Chinese type whose one note holds a stray kana still "
        "reads as Japanese: its note is 'most' (ZH-NTL-403). 'Kana in the word field' would fail Japanese far more "
        "often (勉強, 上層部 are kanji only).",
        "decided", ("Chinese_Decisions.md #7", "Chinese_Build_Spec.md Z2", "Patterns_Chinese_Spec.md D7, §12 S3",
                    "debug/parsing_suite/zh ZH-LANG-04, 05")),
    # --- decided 2026-09-29: step 4's new Chinese questions (Chinese_Decisions.md §4, N1-N6), the user's leans --- #
    Decision(
        "ZH-ZHE-READING", "2026-09-29",
        "著 under the Simplified setting: the Traditional→Simplified table leaves 著 as it is (著 is a Simplified "
        "character too: 著名 'famous'), so 看著 / 睡著 / 著急 stay apart from 看着 'looking' / 睡着 'asleep' / 着急 "
        "'anxious', and a 著急 card gets no パターン — read 著 as 着 where CC-CEDICT pairs them?",
        "Yes (N1) — read 著 words by CC-CEDICT's own Traditional / Simplified pairs (睡著 → 睡着, 著急 → 着急; 著名 "
        "stays), as phrases of the Traditional→Simplified table, one rule for the analyzer and the パターン builder; the "
        "aspect marker after any verb (看著) stays the builder's until a verb test both can share exists. And every "
        "other CC-CEDICT pair the table reads as no word of jieba's dictionary nor CC-CEDICT, where CC-CEDICT's "
        "reading is one of jieba's (砲擊 → 炮击, 姪女 → 侄女, 暱稱 → 昵称: 64 pairs) — the user, 2026-09-30 ~19:45: "
        "'All of the mentions look good, your lean is good'. Pairs the table reads as a word too (計畫: OpenCC's 计划, "
        "CC-CEDICT's 计画) or whose CC-CEDICT spelling jieba lacks (149) are left as the table reads them, for later. "
        "Built 2026-09-30 (step 4, N1): scripts/build_zh_script_data.py, 183 著 / 着 pairs and 64 others, from "
        "CC-CEDICT (credited in app/zh_script_data.py).",
        "The user, 2026-09-29: 'take your lean for everything else'. Chinese_Decisions.md N1; Parsing_Suite_Findings §6; Patterns_Chinese_Spec Z-F6. The パターン builder already "
        "reads 著 after a verb as 着 (patterns_zh.ASPECT); the analyzer doesn't — two rules for one reading (CJ-7). "
        "Lean: read 著 words by CC-CEDICT's own Traditional / Simplified pairs (睡著 → 睡着, 著急 → 着急; 著名 stays), "
        "as phrases of the Traditional→Simplified table, one rule for the analyzer and the builder; the aspect marker "
        "after any verb (看著) stays the builder's until a verb test both can share exists.",
        "Yes: 著急 and 着急 are one row, a 著急 card finds its lines; a pair CC-CEDICT lacks stays apart (看著: "
        "ZH-SCR-014 stays TARGET). Taiwan's 砲擊 and 姪女 come back as 炮擊 and 侄女 under the Traditional setting (19 "
        "characters in 1.1 million of Traditional text). No: under the Simplified setting Traditional text keeps a word "
        "著 beside 着 (ZH-SCR-013 / 014 / 015, ZH-PAT-005 stay TARGET).",
        "decided", ("Chinese_Decisions.md N1", "Patterns_Chinese_Spec.md Z-F6")),
    Decision(
        "ZH-COMPOUND-JOIN", "2026-09-29",
        "CC-CEDICT headwords jieba cuts — 这下 'this time' (once the guesses are off), 郁卒 'glum', 不可能 "
        "'impossible', 一下儿, and the 7% of CC-CEDICT's four-character idioms jieba cuts (不得其门而入, 一字不提): join "
        "them, as Japanese B joins the dictionaries' compounds?",
        "Yes, measured first (N2) — join the CC-CEDICT headwords jieba cuts as CJ-B does, gated against chance "
        "meetings by CJ-3's even-odds test on general text, judged as a variant before it is built. Measured "
        "2026-09-30 (step 4), not built — back to the user: over 300,000 lines of general text 7,989 words join "
        "(1.4% of all words), 92 of 100 joins read right, but CC-CEDICT's phrase entries re-glue what ZH-DICTIONARY "
        "puts apart and six LOCKs break (我去 / 过, 跑 / 得很 / 快, 看 / 完了, 结了 / 婚, 每个人, 维护国家安全's line); "
        "with the UD treebanks as a second witness (a word they write in pieces is refused) 96 of 100 read right and "
        "three still break (结了婚, 每个人, 维护国家安全), while 不可能 is refused (the treebanks write 不 + 可能) — no "
        "case it was to fix is fixed.",
        "The user, 2026-09-29: 'take your lean for everything else'. Chinese_Decisions.md N2. Lean: join them as CJ-B does, gated against chance meetings by CJ-3's even-odds test "
        "on general text — Chinese has no spaces, so chance meetings are the real risk (这下 inside 这下面 'this, "
        "underneath'); measured as a variant first. Would fix ZH-PAT-053 不可能, ZH-SEG-020 这下 (broken by ZH-HMM), "
        "ZH-SEG-015 郁卒, ZH-SEG-018 一下儿, ZH-IDM-006.",
        "Join: dictionary words the cut misses become rows and cards match them (不可能 gets its パターン); a gate that "
        "lets a chance meeting through glues two words. Don't: they stay in pieces (不 + 可能, 这 + 下), the pieces "
        "taking their uses.",
        "decided", ("Chinese_Decisions.md N2", "Patterns_Quality_Spec.md §10 F8")),
    Decision(
        "ZH-NAMES", "2026-09-29",
        "Chinese names beyond the HMM's guesses: jieba's dictionary itself cuts names into real words (雅露露 → 雅 "
        "'elegant' / 露露, 香德拉 → 香 'fragrant' / 德拉), and a guess glues a name to its verb (龙仁用) — a Chinese "
        "names layer, as Japanese has three?",
        "Not yet (N3) — no Chinese names layer beyond ZH-HMM's guard until a Chinese library or a names source "
        "exists; the cases citing it stay TARGET.",
        "The user, 2026-09-29: 'take your lean for everything else'. Chinese_Decisions.md N3; ties to ZH-HMM's guard. Japanese answered with three layers, each with a switch "
        "(NAMES-UNLISTED-KATAKANA, -RECURRENCE, -KANJI); a Chinese one needs a names source (none ships: JMnedict is "
        "Japanese; CC-CEDICT holds surnames and famous names only) and can't be tuned on the user's Chinese library "
        "(four bundled samples). Lean: none beyond ZH-HMM's guard until a Chinese library or a names source exists.",
        "A layer: transliterated and fictional names become one word (露露 the samples' commonest word CC-CEDICT lacks, "
        "27 uses), at the price of a new source and junk it keeps. None: their pieces count as common words (雅, 香).",
        "decided", ("Chinese_Decisions.md N3", "debug/parsing_suite/zh ZH-NAME-04, 05")),
    Decision(
        "ZH-CARD-ENDINGS", "2026-09-29",
        "CARD-INFLECTIONS' Chinese side: a card written with its aspect marker (吃了 'ate', 去过 'have been', 看着 "
        "'looking') or with 得 — is it its verb?",
        "Yes (N4) — 了 / 过 / 着 after ONE verb read alone come off a card (anki_match.one_word's Chinese "
        "endings), the paradigm being no word of its own; never where CC-CEDICT lists the whole (看着办, 睡着, 受不了). "
        "Built 2026-09-30 (step 4, N4): ONE verb by jieba's own tags (analyzer.chinese_verb: v, vn, vd …, read only "
        "when a card asks), in 順, the report's label, Backfill and the パターン lookup; a word CC-CEDICT lists whole "
        "is one token to the cut and never meets the rule.",
        "The user, 2026-09-29: 'take your lean for everything else'. Chinese_Decisions.md N4. ZH-CARD-FIELD took 的 / 地 (MATCH-ENDINGS' な / に); CARD-INFLECTIONS placed "
        "取り消した at 取り消す. Lean: yes for 了 / 过 / 着 after ONE verb read alone (anki_match.one_word's Chinese "
        "endings), as the paradigm is no word of its own; never where CC-CEDICT lists the whole (看着办, 睡着, 受不了).",
        "Yes: 吃了 lands on 吃, 去过 on 去. No: those cards are 'not on the list' in Junban and unlabelled.",
        "decided", ("Chinese_Decisions.md N4",)),
    Decision(
        "ZH-REINFORCE", "2026-09-29",
        "'Reinforce Chinese segmentation' is a hand list of two pairs (就把, 您不) that jieba 0.42.1 splits anyway — "
        "and with the HMM off never guesses: retire the setting, or leave it?",
        "Retire it (N5): the checkbox, the settings key (read as ignored), the tokenizer's argument; the token "
        "store's reinforce suffix stays readable so no store rebuilds for it. Built 2026-09-30 (step 4, N5): the "
        "checkbox is gone from Settings and the dashboard no longer saves the key or passes --reinforce; "
        "ChineseTokenizer and the パターン builder ignore the argument (both still accept it, as an old command line "
        "may pass it); every store's signature reads reinforce=False, the string a store built as shipped holds; "
        "tests/test_reinforce.py is retired.",
        "The user, 2026-09-29: 'take your lean for everything else'. Chinese_Decisions.md N5. WORD-IDENTITY says no hand lists as rules; the setting changes nothing today "
        "(ZH-SEG-022; tests/test_reinforce.py's disabled test is `pass`) — but it is a visible setting, so the user "
        "decides. Lean: retire it (the checkbox, the settings key read as ignored, the tokenizer's argument; the token "
        "store's reinforce suffix kept readable so no store rebuilds for it).",
        "Retire: one control fewer, no hand list in the tokenizer; a user who ticked it sees it gone. Leave: a switch "
        "that does nothing.",
        "decided", ("Chinese_Decisions.md N5", "debug/parsing_suite/zh ZH-SEG-20")),
    Decision(
        "ZH-HAN-RANGE", "2026-09-29",
        "jieba's own Chinese-character range stops at U+9FD5: 䶮 (Extension A, in the name 刘䶮) and 〇 (二〇一六年) cut "
        "a run as non-Chinese — widen jieba's range to Unicode's Han blocks (app/unicode_ranges.HAN)?",
        "Yes (N6) — the one Chinese cut sets jieba's Chinese-character range once per process from "
        "unicode_ranges.HAN (Unicode's Han blocks). Measured 2026-09-30 (step 4), not built — back to the user: with "
        "the guesses off (ZH-HMM) the wider range changes no cut in 300,000 lines of general text (9 lines with them "
        "on: runs of rare characters glued, 〇〇, 㥪㥪); an unknown character is its own piece either way, so "
        "ZH-ENC-002 and ZH-NUM-003 can't move by it — jieba's dictionary lacks 刘䶮, and its route reads 一 / 六年 "
        "inside the date however wide the run.",
        "The user, 2026-09-29: 'take your lean for everything else'. Chinese_Decisions.md N6; MERGE_RECORD ('for the Chinese round'). F7's principle (Han by Unicode's own ranges, "
        "2026-09-27) applies directly — the tokenizer already counts them; jieba's regex (re_han_default) still cuts. "
        "Lean: yes — the one Chinese cut sets jieba's range once per process (a module global, as reinforce tunes "
        "jieba), from unicode_ranges.",
        "Yes: 二〇一六年 is cut as one run (its numerals then dropped, 年 counted), 刘䶮 reaches jieba whole. No: those "
        "runs stay cut at the character (ZH-NUM-003, ZH-ENC-002 stay TARGET).",
        "decided", ("Chinese_Decisions.md N6", "debug/parsing_fixes_run/MERGE_RECORD.md")),
)

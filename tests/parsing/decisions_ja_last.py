"""Decisions for the last small parsing round (lane LR: measured 2026-09-30 as variants_ja_last.py, built 2026-10-01 on
the user's choices) — merged into the register by decisions.py. Fields and rules: decisions.py and
docs/agent instructions/Parsing_Suite.md §7.

Counts quoted from "the library" were measured read-only on 2026-10-01 over the token store's 356,608 sentences, re-read
with the lane's tokenizer under the suite's pins (the frozen settings and name tables): debug/lr/library_uses.py and
debug/lr/iplus1.py in the lane; the hand-reading is phase 1's (MEASURE.md, debug/lr/rule_*.md)."""
from tests.parsing.decisions import Decision

ALL = (
    Decision(
        "CUT-VERB-AUX", "2026-10-01",
        "A JMdict word the tagger reads as a verb + an auxiliary (くだらない = 下る + ない, 知らせる = 知る + せる, 思わず = "
        "思う + ず): that word, or the verb and its grammar?",
        "That word when JMdict's editors list it — a priority tag of a curated list (ichi, spec; never only news / nf, "
        "a string's frequency in the newspaper) — and the auxiliaries are the negative or the causative (ない; ず, ぬ, ん; "
        "せる, させる), never tense, politeness, aspect or the passive, never after a light verb (される, させる). A word "
        "JMdict says is usually written in kana is that word only written in kana (すまない; 済まない is 済む's negative). "
        "Keyed by its dictionary form when it conjugates (くだら + なかっ is くだらない's past), else as written (思わず, "
        "never 思わぬ). Its lemma is the spelling the lists rank best (つまらない, not 詰らない); it counts as itself — "
        "never known through the verb. app/dictionary_data.py's AUX_WORDS (16 keys), analyzer._join_cut_words.",
        "The user, 2026-10-01: build \"curated-active\" (lane LR phase 1, §2). The lists' unit test (R7) is the wrong "
        "witness here: Jiten's parser takes 知らない as an entry (it would join, 1,244 uses), JPDB files くだらない under "
        "下る (it would not). JMdict's editors separate them: くだらない, 思いがけない, 知らせる carry ichi1; 知らない and "
        "足りない no tag; 変わらない only news tags (the plain negative in 10 of 13 uses). Hand-read on the library: 98% "
        "right (63 of 64). The passives (思われる 444, 救われる 178) are the verb's own passive in most uses (81% right "
        "as words): they stay the verb's. On the library 1,221 uses of 15 words become their words (思わず 373, すまない "
        "159, 知らせる 116, 済ませる 116, つまらない 112, つまんない 93, くだらない 83, 絶えず 52 …).",
        "A plain negative written as the word (そうは思わず, 気がすまない — 気が済む's negative, in kana) joins wrongly "
        "(~2%); 知らない, 足りない and 変わらない stay their verbs' (they are, mostly); a word written in kanji that JMdict "
        "calls usually kana stays the verb (下らない, 堪らない: 69 library uses). The words count as themselves: 11 of the "
        "15 are no known word of the user's yet (523 uses), and 99 of the library's i+1 sentences (0.1%) wait for one of "
        "them. Two phrase rows split by spelling (気がすまない / 気が済まない, いたたまらない / 居た堪らない). A pre-noun "
        "word only before a noun (いらぬ心配) was part of the measured rule; no curated pre-noun word passes the gate, so "
        "it was not built.",
        "decided", ("lanes/LR MEASURE.md §2, HANDOFF.md", "tests/test_cut_words.py", "JA-AUD-038", "JA-AUD-039",
                    "JA-AUD-040")),
    Decision(
        "CUT-WORD-PARTICLES", "2026-10-01",
        "A JMdict adverb or conjunction the tagger reads as a word + particles (いつも = いつ + も, ちなみに = 因み + に, "
        "どうにか = どう + に + か) or as particles (a clause's でも = で + も): that word, or its pieces?",
        "That word when JMdict's editors list it (a curated tag), both lists rank it about as often as general text "
        "holds the run (R7 on JPDB 2024 AND Jiten, ratio <= 8) and its first word is a closed class: particles opening a "
        "clause (でも — never after a word, a closing bracket or a quote), a pronoun (いつも, 何か, それとも), an adverb "
        "with more than an optional と / に after it (どうにか; すぐに stays すぐ's) — or a noun the lists rank rarer alone "
        "than the whole (因み in ちなみに); never a free noun's adverbial form (本当に is 本当 + に). A run inside a longer "
        "JMdict spelling stays that spelling's pieces (かどうか, それにしても, いつものように): the longest spelling from "
        "the left wins, as JT-EXPRESSIONS keeps an expression's pieces. Each counts as itself — knowing いつ and も is no "
        "knowing いつも. app/dictionary_data.py's PARTICLE_WORDS (75 keys), analyzer._join_cut_words.",
        "The user, 2026-10-01: build \"narrow-longest\", each joined word counting as itself (lane LR phase 1, §3). "
        "Hand-read on the library: about 92% right (73 of 79 kept); the ordinary-text LOCKs it changes: 46 of 50 right "
        "(4 LIMIT below). On the library 24,119 uses of 60 words become their words (でも 2,995, なんか 2,725, 何か 2,612, "
        "それで 1,742, なんで 1,636, それに 1,560, 一緒に 1,334, いつも 892 …). The wider gate (common + R7, 39,133 uses, "
        "90%) also joined 本当に, ために, 今まで and すぐに — a free word's own adverbial use.",
        "それに / それで are the weakest (about 70% / 90%): a pronoun + a case particle the run can't tell from the "
        "conjunction (それによって, それで名乗り出て, それにしたって — none of them a longer JMdict spelling), and その実は "
        "('that fruit') reads as 実は 'actually'. A word + particles inside an expression stays its pieces where the word "
        "is meant (いつものように: いつ + も + の). The words count as themselves: the user's known words hold 20 of the 62 "
        "(15,685 uses); 42 are new to the list (8,434 uses: 何か 2,612, 一緒に 1,334, どこか 544 …) until marked known — "
        "4,119 sentences that were fully known now wait for one, and 2,028 i+1 sentences (2.2%) gain a second unknown. "
        "The base words lose those uses (何 about −7,500, それ −4,900, 一緒 −1,330).",
        "decided", ("lanes/LR MEASURE.md §3, HANDOFF.md", "tests/test_cut_words.py", "JA-AUD-041", "JA-AUD-042",
                    "JA-AUD-043", "JA-CMP-061")),
    Decision(
        "PRONOUN-BASES", "2026-10-01",
        "A pronoun + a suffix the lists carry as a word of its own (何様, 俺様, お前さん, それなり, これっぽっち): one word, "
        "or the pronoun and its suffix?",
        "One word while Settings -> Language & Parsing -> \"Pronouns with a suffix as one word\" is on (logic.pronoun_bases, "
        "the default): Part A takes a pronoun as a base for the suffixes after it (never after a prefix). Never a plural: "
        "the table's build reads 方 by the lists' reading (あなた方 アナタガタ, though the tagger reads its 方 カタ), and a "
        "nominalizer after a pronoun is never one (これさ is これ + the particle さ). Off, they count as their parts. The "
        "switch is read as a file is tokenized: a suffix of the store's build signature and the known-words key when "
        "off, and in the run signature.",
        "The user, 2026-10-01: build it behind a new switch, default on (\"I could see someone not wanting all the extra "
        "words that adds\"). 87 headwords join; on the library 345 uses of 20 words (それなり 119, 俺様 77, お前さん 44, "
        "これっぽっち 22, 何様 15 …), 98% right by hand. A real table rebuild matches the in-memory measurement; it also "
        "drops 各方 (a plural) and two words with 0 uses (悪方, あいがた).",
        "A pronoun word read through its pronoun (U9): 何様 and お前さん are nouns, so a known 何 or お前 makes them no "
        "unknown in a sentence (a question for the user). A colloquial collision joins wrongly (私家 シカ for わたし家). "
        "Off, JT-PART-A's old price returns: お前さん is お前 + さん.",
        "decided", ("lanes/LR MEASURE.md §5, HANDOFF.md", "tests/test_pronoun_bases.py", "JA-AFX-276", "JA-AUD-022")),
    Decision(
        "KATAKANA-STRETCH-DROP", "2026-10-01",
        "A katakana word stretched inside — two marks or more, a wave dash, a dash run, read as one ー (STRETCH-MARKS, "
        "DASH-STRETCH) — that is no word with that ー (ジャーック, バイバーイ): keep the ー, or read the word without it?",
        "Without it, where that is a word the dictionaries know — a headword of the lists, or one the tagger reads alone "
        "as one word it knows (ジャ～ック is ジャック, バイバ～イ バイバイ, スト～ップ ストップ); a stretched spelling that is a "
        "word with one ー keeps it (スーーパー is スーパー), and one ー as written is the word's own (オットー). "
        "analyzer._katakana_stretches, in Tagger: every tagger call.",
        "The user, 2026-10-01: build \"-known\" (lane LR phase 1, §6). On the library 56 uses, every one a junk unknown "
        "word before; by hand 81% become the word the text says. Dropping the mark whatever results (\"-any\") is much "
        "worse: ヒエ〜 became 稗 'millet', トーーク 得.",
        "About one in five drops makes a misleading real word: くださ〜い's サ〜イ read 菜, テ～ンス 'tense', キ〜モ 肝 — "
        "where before it was junk; a shout's sound can take a word's row (ザ─────ック is ざっく).",
        "decided", ("lanes/LR MEASURE.md §6, HANDOFF.md", "tests/test_tagger_reading.py", "JA-AUD-011")),
)

"""The decisions register — each parsing choice, what it knowingly gives up, and the cases it trades.

The user asked the suite to "account for decision tradeoffs in the future" (2026-09-26): a rule change is judged
against the choices already made, not rediscovered. A case names the decision it trades on (`Case.decision`):

    LIMIT     cites a DECIDED decision — the reason the wrong answer is accepted (its `tradeoff`);
    DISPUTED  cites an OPEN decision — the user's call, both sides in `rationale` / `tradeoff`;
    TARGET    may cite the decision that will fix it;  LOCK  may cite the decision it proves.

The scorecard groups every flip by the decision it touches, so a change that undoes a tradeoff (or pays one
twice) is visible by name. Record a new choice here the day it is made; when an open one is decided, set
`choice`, `status="decided"` and the date, then re-file its DISPUTED cases (LOCK / TARGET / LIMIT).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    id: str
    date: str           # when it was decided (open: when it was raised)
    question: str
    choice: str         # None while open
    rationale: str      # why — the evidence, and for an open one the sides and the lean
    tradeoff: str       # what the choice knowingly gives up (open: what each side gives up)
    status: str         # "open" | "decided"
    refs: tuple = ()


ALL = (
    # --- principles -------------------------------------------------------------------------------------------- #
    Decision(
        "WORD-IDENTITY", "2026-09-26",
        "What decides what a word IS — segmentation, joins, whether a half is a word of its own?",
        "Japanese (or Chinese) as a whole: the dictionaries (JPDB 2024, Jiten, JMdict, CC-CEDICT), general "
        "reference text, UniDic, linguistics and phonology. The user's library decides only what to learn next "
        "(and helps find errors). No hand-made white or black lists as rules — a list of cases is this suite.",
        "The user, 2026-09-26: a rule tuned on one learner's sentences doesn't hold for Japanese; lists don't "
        "scale. Every case's `basis` follows it.",
        "A misparse that only matters in this library is not fixed by a library-tuned rule — Ignore takes a frequent bogus "
        "row, give-back (CJ-6) hides a rare one — with ONE exception, the user's: what a work invents, which no dictionary "
        "of Japanese can hold — names (NAMES-RECURRENCE, NAMES-KANJI) and, since 2026-09-29, a work's own kanji terms "
        "(NAMES-WORK-TERMS), only where JMdict has no entry.",
        "decided", ("Parsing_Robustness_Suite_Scope.md (principles)", "Compound_Join_Measurement.md §12.4")),
    Decision(
        "UNIDIC-LEMMA", "2026-09-22",
        "What names a Japanese word — its identity for counting, matching and known words?",
        "UniDic's lemma (`Word`), keyed with the lemma's reading (lForm, ENGINE_REVISION 10): one row per word "
        "however it is conjugated. `Orth` is only the spelling shown.",
        "The lemma merges spellings and conjugations the list must count as one (いう / 言う / 言える), and lForm "
        "still tells real homographs apart (上手 ジョウズ / カミテ).",
        "UniDic merges words the dictionaries keep apart (帰る under 返る, 治める under 収める) and gives some "
        "words one fixed reading whatever is said (私 ワタクシ, 日本 ニッポン, 明日 アス) — and between two entries "
        "for one spelling it picks by context (いー the filler over 良い: いーぜ, いーよ — JA-SCR-005, -006).",
        "decided", ("CLAUDE.md engine rules", "analyzer.py ENGINE_REVISION 10")),

    # --- 2.3: words keep their prefixes and suffixes (Patterns_Quality_Spec.md Part A) --------------------------- #
    Decision(
        "AFFIX-GUARDS", "2026-09-25",
        "Which prefix / suffix runs never join, whatever the dictionary lists?",
        "Plural and collective suffixes (私たち, 子供たち, 先生方); a person's name as a base (田中さん); anything "
        "after a number (3年生, 三回目), a prefix after a number included (三大祭り = 三 + 大 + 祭り).",
        "Part A §6.1 and checkpoint A; 三大祭り added by the §15.9 sweep. Plurals are regular grammar, not "
        "words; a name is no base; a number makes a count, not a word.",
        "私たち and 彼ら — JPDB headwords — are listed as 私 + たち; an honorific after a name never becomes a "
        "word; counters after numbers (回目, 年生) never do either. Recorded 2026-09-28 (step 3, the user's lean): the "
        "plural guard, which the compound joins inherit (CJ-B), also keeps a few rare hiragana shape words in pieces — "
        "うろこがた, かぎがた, くしがた, すりばちがた, おんながた (and 押方) — since UniDic files their がた 'shape, style' as 方 "
        "カタ, the plural suffix's lemma, too: no tagger test tells them apart. Their usual kanji spellings (鱗形, 櫛形, "
        "女形) are one token and unaffected.",
        "decided", ("Patterns_Quality_Spec.md §6.1", "Patterns_Quality_Spec.md §15.9")),
    Decision(
        "U1-OGO-SHARE", "2026-09-25",
        "お / ご / 御 + a word: join always, never, or when the お / ご form is a usual form of the word?",
        "Join when the お / ご form is at least 30% of the word's uses (50% in conversation, U18), decided once "
        "per word for all its spellings (U16) — the §15.9 sweep rebuilt the table on the right counts "
        "(おやすみ / お休み, ご存知 / ご存じ one word each).",
        "A polite form of a common word is that word (お名前 is 名前); a form that is usually said with お is a "
        "word of its own (お茶, お金, お菓子). Measured on the shared corpus, not the user's library.",
        "Polite forms stay split (お名前, お仕事, お部屋), and so do dictionary entries under the share — お帰り "
        "20%, お守り 26%, お疲れ, お邪魔 (OGO-EXCEPTIONS).",
        "decided", ("Patterns_Quality_Spec.md §6.4 (U1)", "Patterns_Quality_Spec.md §15.9")),
    Decision(
        "OGO-EXCEPTIONS", "2026-09-28",
        "お帰り and お守り fall under U1's 30% (20% and 26%) and split — keep the rule, or treat them as words of their "
        "own? (Also 姉様, not joined while 兄様 is: the lists carry only 兄様.)",
        "Yes, by a dictionary test (the user, 2026-09-28: \"I do want all 6 the way your yes leans\"): an お / ご / 御 "
        "word U1 leaves split joins when JMdict lists it as its own entry with a meaning the bare word lacks — an "
        "entry holding the お/ご spelling (or its kana) that is not the bare word's entry, with a sense neither marked "
        "polite / honorific nor sharing a gloss with the bare word's senses (glosses compared case- and "
        "bracket-free). Candidates: the 132 お/ご words of debug/ogo_joins.md with 20+ prefixed uses that U1 splits, "
        "and those under U1's 20-use floor. The words it decides join the affix joins with every spelling of their "
        "group under one lemma (U16), decided at build time and kept in their own module (app/dictionary_data.py, CC "
        "BY-SA 4.0), merged by affix_joins() at run time; the list goes to the user with the build. 姉様 is outside "
        "the test (no お/ご; the lists carry only 兄様). JMdict: docs/assets/reference_lists/JMdict_e.gz (EDRDG, created "
        "2026-09-28). Compound_Build_Spec.md §2.13. As built (WP-5, scripts/jmdict_flags.py; recorded 2026-09-28, the "
        "user's leans): decided once per WORD, over every spelling of it (entries found by spelling + reading); a kana "
        "spelling's entries count only when they hold one of the word's kanji spellings (the homophone rule: ごえん is "
        "ご縁, never 誤嚥); the glosses compared are the kanji spellings'; and a bare-word sense marked abbr (an "
        "abbreviation) does not count against the お/ご word — it is that word, shortened: JMdict's 守り 'amulet' is "
        "お守り, so お守り joins. Option (a), the test as ratified: all 55 words it decides join (お守り, お帰り / おかえり, "
        "お笑い, おかわり, お疲れ, お嬢, ご苦労, お天気, お友達, お見舞い, お上手 …) — pending the user's confirmation of "
        "that list; 80 stay split. Built 2026-09-29 (the compound build): the tables landed — app/dictionary_data.py "
        "holds 440 spellings of 281 お/ご words the test joins (the 55 above, and words under U1's 20-use floor), "
        "merged by analyzer.affix_joins(); the four polite readings they sweep in are LIMIT (JA-AFX-274 お上手, 310 "
        "お見舞い, 316 お友達, 321 お疲れで); option (a), all 55, still pending the user's confirmation of the list.",
        "§15.9 question 1, asked 2026-09-25. JMdict lists お帰り(なさい) and 御守り 'amulet' as entries of their own — "
        "'amulet' is no polite 守り; naming exceptions by hand would be a list (WORD-IDENTITY), a JMdict entry with a "
        "sense of its own is Japanese-wide. The ogo report: 132 お/ご words with 20+ prefixed uses stay split under U1 "
        "(お守り 26%, おかえり 20%, お邪魔 23%, お疲れ 12%, お笑い 15%, おかわり 4%, お宅 28%, お見合い 26% …). A read-only sketch of the test "
        "against JMdict_e 2026-09-28 (WP-0) on the suite's cases: it joins お帰り ('welcome home', int), お疲れ ('good "
        "work!', int), お嬢 ('young lady'), ご苦労 ('thank you for your hard work', exp); it leaves split 御社 and お邪魔 "
        "(every sense marked hon / pol), お手洗い ('toilet' is also a sense of 手洗い) and お守り — the bare 守り has the sense "
        "'amulet; charm', marked abbr (JMdict reads 守り 'amulet' as short for お守り): the lane decides whether an "
        "abbreviation sense of the bare word counts against the お-word. Re-filed 2026-09-28: 12 DISPUTED cases "
        "TARGET (the lane's test decides each; a word it leaves split becomes LIMIT then), 姉様 twice LIMIT, お帰りなさい's "
        "card LIMIT under JT-EXPRESSIONS. WP-5 (2026-09-28) on the 132 words + 御社, お嬢, お手洗い: 55 join, 80 split (every "
        "sense polite: お名前, お仕事, お部屋, 御社, お邪魔, お宅; polite or a shared gloss: お手洗い, お話, お見合い, ご挨拶; no "
        "entry: お菊); the abbreviation lean sweeps in only お守り; the expected joins (お守り, お帰り, お笑い, おかわり) all "
        "join, the expected splits (お名前, お仕事, お部屋) all split. Option (b), narrowed — the first sense the word's "
        "own, or a greeting / set phrase — joins 33: お友達 and お見舞い split, but so do お嬢, お座敷, お約束, お開き "
        "(variant ogo-jmdict-main); the user took (a).",
        "A polite or honorific form stays split even where learners meet it as a set word (御社, お邪魔 of お邪魔します); an "
        "お-word whose meaning the bare word shares stays split (お手洗い — 手洗い is also 'toilet'); 姉様 stays 姉 + 様; every "
        "call rests on JMdict's glosses and register tags. Under (a) a word mostly said as a polite form but with a "
        "rarer meaning of its own joins — お友達 ('another child'), お天気 ('mood'), お水 ('nightlife'), お見舞い ('dealing "
        "a blow'), お上手, お疲れ (お疲れで is the greeting's spelling) — so its polite uses count as that word too, not "
        "the bare one (LIMIT since the tables landed, 2026-09-29: JA-AFX-274, 310, 316, 321), and a learner who knows 友達 meets お友達 "
        "as a new word (a prefix word is never seen through).",
        "decided", ("Compound_Build_Spec.md §2.13", "Parsing_Fixes_Plan.md §1 (ratified 2026-09-28; step-3 answer 1)", "Patterns_Quality_Spec.md §15.9 Q1", "Parsing_Robustness_Suite_Scope.md §2 E", "debug/ogo_joins.md", "scripts/jmdict_flags.py (WP-5)", "debug/parsing_fixes_run/step3/J_REPORT.md §3")),
    Decision(
        "U2-NOMINALIZER", "2026-09-25",
        "Join the nominalizers さ / み after a な-word (不自然さ)?",
        "No — さ / み after a な-word stay apart and count toward the word (不自然さ → 不自然); UniDic's 形状詞可能 "
        "nouns too (複雑さ, 便利さ). 人間味 and よそみ, whose み is 味 / 見, still join.",
        "The user (U2): the さ-noun is the adjective's meaning; its card shows 〜さ on the word's own card.",
        "A nominalized word never gets a row or a card of its own.",
        "decided", ("Patterns_Quality_Spec.md §6.1, §8.4 (U2)",)),
    Decision(
        "U9-SEE-THROUGH", "2026-09-25",
        "A suffix-joined word (利用者) whose base (利用) is known: unknown, known, or in between?",
        "Halfway + lower: its own list word — card and reading — at half the score, and never an unknown when "
        "choosing example sentences. Noun-making suffixes only, never a prefix word but the polite お / ご (不自然 never; a "
        "dictionary お / ご word — ご苦労 — halfway through 苦労: KNOWN-BASE-AFFIX Q1 (b), 2026-09-29).",
        "Checkpoint A, asked with both cases argued. 'Known when the base is known' would have hidden 5,547 "
        "joined words, 自転車 ← 自転 and 可能性 for anyone who knows 可能.",
        "The word still takes a row and a card though it can be read; a prefix word (不自然) is never seen through; "
        "a dictionary お / ご word whose meaning moved (お守り) is read through its bare word in sentences.",
        "decided", ("Patterns_Quality_Spec.md §6.8 (U9)",)),
    Decision(
        "U16-SPELLINGS", "2026-09-25",
        "Spellings of one word (お勧め / おすすめ / オススメ): one list word?",
        "Yes — one word per spelling group, under the best-ranked spelling's lemma; the text keeps its own spelling.",
        "Checkpoint A. A learner learns one word, whichever way a text writes it.",
        "The list shows one spelling for all of them.",
        "decided", ("Patterns_Quality_Spec.md §6.1 (U16)",)),
    Decision(
        "U17-HONORIFIC-WORDS", "2026-09-25",
        "Dictionary words that end in an honorific (母さん, 皆さん, お嬢さん, 神様)?",
        "Join them, each with its own reading (母さん カアサン, not 母 はは + さん); plurals and names still never.",
        "Checkpoint A: they are words of their own, not a polite way of saying the word inside.",
        "Honorific kana spellings stay their own words (おじょうさま beside お嬢様; §15.9 question 3).",
        "decided", ("Patterns_Quality_Spec.md §6.1 (U17)",)),

    # --- 2.3.1: Anki match consistency --------------------------------------------------------------------------- #
    Decision(
        "MATCH-ENDINGS", "2026-09-26",
        "A card's word written with an ending (努力する, バシッと, 斬新な): the list word, a question, or a phrase?",
        "The list word, with no question (`anki_match.card_key`, L7), when read alone it is ONE word + ONE ending "
        "(する / な / に / と): 努力する → 努力, バシッと → バシッ. Two endings stay a phrase (楽しみにする, クビにする "
        "— their meaning moves). A kana card is looked up by its own letters, never by the lemma the tagger "
        "guesses for it alone (まく ↛ 膜). The user's 'no' always wins; a known noun + する goes to Junban's "
        "known tier; the report's 'In Anki' label uses the same key.",
        "Anki_Match_Consistency_Scope.md items 1-2, ratified; the user: 'I'd prefer them to be one word'. The "
        "spec's own measure of the rule had 0 wrong.",
        "A noun + する whose meaning drifts counts as the noun (お茶する → お茶) — the user's 'one word unless "
        "there's a good reason'. Since CARD-SENSE (2026-09-30) the dictionary is that reason: a card JMdict lists "
        "whole is a word of its own (心する 'take heed', 一気に 'in one go'); お茶する and 努力する, which it doesn't "
        "list, stay their noun.",
        "decided", ("Anki_Match_Consistency_Scope.md items 1-2", "tests/test_anki_match.py")),

    # --- the compound leans (Compound_Join_Measurement.md §12.7) — approved 2026-09-26, validated 2026-09-27 ------- #
    Decision(
        "CJ-B", "2026-09-26",
        "Join noun + noun compounds that are dictionary headwords (上層部, not 上層 + 部)?",
        "Yes — approved 2026-09-26, validated on this suite 2026-09-27 (Parsing_Suite_Findings.md §1: the leans "
        "package fixes 264 of the 267 wrong compound cases): B, with (iii): a compound whose parts are all known "
        "counts like a U9 word (half score, never an unknown in a sentence); built in step 3 (Compound_Build_Spec.md "
        "§2.2). B's blind spots were decided 2026-09-28: place parts (JT-PLACE-BASE), な-word parts (JT-NA-ADJ), "
        "numeral words (JT-NUMERAL-WORDS), verb + verb (JT-COMPOUND-VERBS), the fringe behind a switch (JT-B-FRINGE).",
        "Real words replace junk halves (中途半端 for 中途, 自業自得 for 自業), readings come right (一昨日 "
        "オトトイ), anki_miner's compound cards match exactly. Without (iii), 4,714 fully known sentences would "
        "gain an unknown.",
        "+288 / -189 list rows on the user's library (27 junk halves, 76 absorbed, 86 real words at the edge — "
        "give-back, CJ-6, returns most); about 0.1% wrong joins; B read left to right, longest first: 旧市庁舎 reads 旧市 "
        "+ 庁舎 (the right cut is 旧 + 市庁舎) — accepted 2026-09-28 (the user's answer 8; JA-CMP-218 becomes LIMIT under "
        "this decision when the lane that breaks it lands); a compound in neither list stays in pieces (滞在先, "
        "JA-KEY-088). Its blind spots as measured — numeral idioms (一石二鳥), noun + な-adjective (一生懸命), 日本語 (a place "
        "part) — are decided since 2026-09-28. B inherits the plural guard (AFFIX-GUARDS): 先生方 stays 先生 + 方, and so "
        "do the rare hiragana shape words written with がた (うろこがた, くしがた, おんながた) — accepted 2026-09-28.",
        "decided", ("Compound_Join_Measurement.md §0, §11, §12.7",)),
    Decision(
        "CJ-1A", "2026-09-26",
        "Sound words + と: which join?",
        "Validated on this suite 2026-09-27 (Parsing_Suite_Findings.md §1): the っ rule — a kana sound word tagged 副詞 "
        "ending in っ / ッ, directly followed by the case particle と, is one word (ドキッと, バシッと, ざっと). Nothing else, no "
        "list. A card mined with its と is still matched as the sound word + と (CJ-1B, 2026-09-28).",
        "The final っ is the first half of a double consonant that と's /t/ completes; JPDB / Jiten list 191 "
        "っ-form stems only with と; UniDic already keeps the lexicalized ones whole (ずっと, そっと, はっと). "
        "0 of 60 wrong joins.",
        "ン / り forms stay bare (CJ-2); a quoted 「バシッ」と and バシッ！と stay apart (34 uses).",
        "decided", ("Compound_Join_Measurement.md §12.3, §12.7 #1",)),
    Decision(
        "CJ-1B", "2026-09-27",
        "A joined sound word (ざっと): the same word as its bare form, shown with と (UniDic's lemma kept) — or a "
        "separate word?",
        "The same word, shown with と: ドキッと is ドキッ's row — UniDic's lemma and reading kept (どき / ドキ), the "
        "と-form only its spelling — and shares its known status (the っ rule R2Q, same-word build: the r2q-same "
        "variant). Built with the compound build (Parsing_Fixes_Plan.md §2 step 3). A card mined with its と (バシッと) "
        "is the sound word (decided 2026-09-28, the user's lean on WP-2's question 1): read alone it is one token, and "
        "the card rule reads it apart again — the sound word + the ending と (anki_match.ending_apart, in card_key and "
        "the report's label) — so it reaches the sound word's row with no question even where the list never writes "
        "the と-form, in Junban, the 'In Anki' label and 例文 alike, as MATCH-ENDINGS placed it before the join. Told by "
        "the token alone: written with っと while its reading, the sound word's, does not end in ット (ずっと, ちょっと, "
        "はっと are と-adverbs of their own and keep it).",
        "The user, 2026-09-27 (Parsing_Fixes_Plan.md §1, decision 3), on the suite's evidence "
        "(Parsing_Suite_Findings.md §1): r2q-same fixes 79 cases and breaks 8, r2q-separate 78 and 11 — the same 69 "
        "wrong sound words either way. Separate words also make ぐっと / ぱっと / ぎゅっと (bare forms known) new words "
        "(575 sentences gain an unknown), turn the tut チッと into ちっと 'a little', and a rebuilt list can't "
        "restore their card matches. The さっ finding that reopened it (2026-09-26): separate words only keep that "
        "misread interjection off さっと's row; neither build fixes the tag. The card rule (2026-09-28): with the join "
        "alone, a バシッと card reached the row only when a rebuilt list's Forms held バシッと, else Junban asked "
        "'same word?', and a half-width ﾊﾞｼｯと lost its key; reading the card apart restores all of it (JA-LBL-002, "
        "JA-LBL-036, JA-KEY-053's key).",
        "Homographs stay one row: the interjection さっ 'come on', which UniDic tags as the adverb unless 、 follows "
        "(about 17 of 37 bare uses), counts on さっと's row — neither build fixes that tag —, and the scoff フッ "
        "shares a row with ふっと 'suddenly'. The card rule looks the sound word up by its letters and their kana "
        "fold, as before the join: where the adverb itself is not on the list, a ぐっと card reaches a misread グッ row "
        "(ぐっちゃぐっちゃ read as グッ) — JA-LBL-005, wrong before step 3 for the same reason, TARGET again.",
        "decided", ("Parsing_Fixes_Plan.md §1 decision 3", "Parsing_Suite_Findings.md §1",
                    "Compound_Join_Measurement.md §12.3, §12.7 #1 and its correction")),
    Decision(
        "CJ-2", "2026-09-26",
        "ン / り forms (ポンと, くるりと): joined with と or bare?",
        "Validated on this suite 2026-09-27 (Parsing_Suite_Findings.md §1): bare, as the dictionaries and the user's "
        "miner write them (くるり); 2.3.1's と ending keeps matching those cards.",
        "Their と is optional (ゆっくり(と)歩く), not part of the word as after っ.",
        "The list shows くるり where sentences say くるりと.",
        "decided", ("Compound_Join_Measurement.md §12.7 #2",)),
    Decision(
        "CJ-3", "2026-09-26",
        "Which dictionary compounds does B refuse as coincidences (今頭 = 今 + 頭)?",
        "Validated on this suite 2026-09-27 (Parsing_Suite_Findings.md §1): the even-odds gate, H + form at the "
        "median — refuse a compound only when neither the reference text nor the dictionary lists vouch that it is "
        "at least as common as a chance meeting of its parts. No reading margin.",
        "Keeps 仕事人間, 年格好, 恋話, 練習問題, 安全日, ばかもの; refuses 9 of 10 coincidences (今頭, 今手, 時花 …).",
        "Chance strings the gate accepts still join where their parts meet by chance (give-back hides a rare one) — "
        "the suite's 11, LOCK now, become LIMIT under this decision when B lands (Compound_Build_Spec.md §6): 日限り "
        "(その日|限り, JA-CMP-025), 最近親 (026), 実際家 (実際|家にいる, 027), 仕事人間 (a comma-less transcript, 028), 後加工 (219), 地和 "
        "(331), 結月 (332), 月平均 (565), 夜酒 (595), 節先生 (611), 上湯 (631); and 円玉 with its digits stripped (JA-CMP-030: "
        "nothing is left for the number guard). About 18 transparent words whose spelling usually sits inside a "
        "longer word stay split (販売機, 学生会, 店前); a chance meeting of real words in one sentence (実際|家) can't be seen "
        "by a table rule.",
        "decided", ("Compound_Join_Measurement.md §12.6, §12.7 #3",)),
    Decision(
        "CJ-4", "2026-09-26",
        "A per-user 'not a word here' file for bogus joins?",
        "Validated on this suite 2026-09-27 (Parsing_Suite_Findings.md §1): no — Ignore covers a frequent bogus row, "
        "give-back hides a rare one.",
        "A per-user list is a white/black list (WORD-IDENTITY).",
        "A bogus join stays in the tokens; only its effect on the list is handled.",
        "decided", ("Compound_Join_Measurement.md §12.7 #4",)),
    Decision(
        "CJ-5", "2026-09-26",
        "'A half never used outside the whole' (権益 in 既得権益) — judged in the user's library or in Japanese?",
        "Validated on this suite 2026-09-27 (Parsing_Suite_Findings.md §1): in the user's library — for what to "
        "learn only; what a word IS stays Japanese-wide (WORD-IDENTITY).",
        "It is what the learner will meet, and it self-corrects as the library grows; the general version hides "
        "ビニール (27 uses alone).",
        "A half can swap in and out of the list as the library changes.",
        "decided", ("Compound_Join_Measurement.md §12.7 #5",)),
    Decision(
        "CJ-6", "2026-09-26",
        "A rare compound (below the list's cut-off): one word, or given back to its parts?",
        "Validated on this suite 2026-09-27 (Parsing_Suite_Findings.md §1): give-back with the R free/bound flag — a "
        "rare compound returns its uses to its free parts; bound-half idioms stay one word, one unknown (千載一遇); free "
        "halves count apart (トランスジェンダー = two).",
        "No idiom list: a part is free when JPDB 2024 or Jiten meets it on its own at least as often as inside "
        "the compound. Leavers 189 → 48, none at the edge.",
        "A real word whose partner is bound (撤回 in 前言撤回) is still credited; non-literal compounds of free "
        "words (八方美人, 大根役者) read as parts when rare, for now.",
        "decided", ("Compound_Join_Measurement.md §12.2, §12.5, §12.7 #6",)),
    Decision(
        "CJ-7", "2026-09-26",
        "Do the list, the band slider, Junban and the sentence dictionary / 例文 each keep their own rule?",
        "Validated on this suite 2026-09-27 (Parsing_Suite_Findings.md §1): one parse, one learning rule (give-back) "
        "and one example rule everywhere — examples only where the word stands on its own, the report included.",
        "B's tokens decide which word a sentence is an example FOR; give-back only changes how hard it counts.",
        "10 words lose their i+1 example in the report. The backlog card 成長期 goes by its own 9 uses, not 12: 3 sit "
        "inside 経済成長期, which B joins and give-back reads 経済成長 + 期 — a use inside a longer word is that word's "
        "(counting it too would count it twice). Accepted 2026-09-28 (the user's answer 8): JA-JBN-056 becomes LIMIT "
        "under this decision when the lane that breaks it lands.",
        "decided", ("Compound_Join_Measurement.md §12.5, §12.7 #7",)),

    # --- open questions the scope names ---------------------------------------------------------------------------- #
    Decision(
        "ONE-CHAR-IPLUS1", "2026-09-30",
        "An unknown one-character word the list can never offer (昴, 斬 in 斬魄刀, は) — should it still keep a "
        "sentence from being i+1?",
        "No — count exactly what the list can offer, everywhere (the user, 2026-09-30, A4: 'count exactly what the "
        "list can offer, everywhere', and 'document and isolate them'). A one-character word the list can never offer "
        "— grammar and particles, a name the tagger reads as a common noun (スバル as 昴), a one-kanji word under the "
        "commonness gate (簪), a piece of a term (斬 in 斬魄刀), a misparse — is no unknown in a sentence in the report, "
        "例文, the sentence dictionary, 順 and the YouTube preview, and nothing to learn in a file's coverage "
        "(analyzer.unoffered / single_kind — one rule). A one-kanji word the list offers (ONE-KANJI-WORDS) is an "
        "honest unknown where it stands on its own. The report names each file's one-kanji words the list can't offer "
        "('Also in this file, not on your list', with counts; never grammar: analyzer.not_on_list) so a card can "
        "still be made for one (スバル).",
        "Measured on the user's library (single_kanji/REPORT.md §10): 4,536 sentences were not i+1 only because of an "
        "unknown one-character word, 1,470 of them スバル's; under the rule and this choice 3,334 come back (1,454 "
        "スバル's) and 1,546 more become i+1 for a newly listed one-kanji word; 83% of one-word sentences hold a "
        "particle, so a learner whose known words lack は and が lost almost every i+1 sentence. The three consumers "
        "disagreed before (the analyzer and sentence_corpus counted, Junban didn't).",
        "A sentence can be called i+1 while it holds a particle the learner hasn't met, or a name piece — neither can "
        "be learned from the list.",
        "decided", ("Parsing_Robustness_Suite_Scope.md §2 L", "debug/parsing_suite/ja_consumers D06-D07",
                    "debug/parsing_fixes_run/single_kanji/REPORT.md §5 Q4, §10")),
    Decision(
        "IGNORED-ENTRIES", "2026-09-29",
        "KnownWord.json's IGNORED entries (Migaku's status): honour them as ignored?",
        "Honour them: KnownWord.json's IGNORED entries (Migaku's status) are ignored words, as a line of the Ignore "
        "list is — read as the lists' lines are (a hiragana one also names its kanji word) — so they leave the list, "
        "never count as an unknown in a sentence, and a card for one goes to Junban's known tier. One reader "
        "(token_index.ignored_entries) for every ignore set: the analyzer's (analyzer.load_ignored_entries), the "
        "Rarity preview's (preview_ignore_set — the slider and automatic rarity count what the list counts), "
        "Junban's, the YouTube preview's and the sentence dictionary's (sentence_corpus.known_sets).",
        "load_known_words counts only KNOWN / hasCard; the user's 63 IGNORED entries are not honoured and 10 of "
        "them are on today's list. The user, 2026-09-29: took the lean (honour). Built by lane RC4: on the "
        "2026-09-26 snapshot the 63 entries take 9 rows off the list (オーロラ, 不在, 支払い, 混む, and five names "
        "or interjections).",
        "A word the user dismissed in Migaku long ago stays off the list until the entry is changed; a kana card "
        "whose word is IGNORED goes last (ひかり, 光 IGNORED — JA-JBN-023).",
        "decided", ("Parsing_Robustness_Suite_Scope.md §2 J", "debug/parsing_suite/ja_consumers K14",
                    "debug/parsing_fixes_run/lanes/RC/HANDOFF.md §8")),
    Decision(
        "ZH-TRAD-ASIS", "2026-09-29",
        "Traditional text under the default as-is setting: segment it through Simplified (emitting the text as "
        "written), or keep as-is output byte-identical (Chinese_Script_Conversion_Spec I2)?",
        "Cut as-is Traditional text through Simplified and keep every word as written: the as-is tokenizer segments the "
        "text's Simplified form and emits the text's own spelling (為什麼 one word, still spelled 為什麼; 頭髮; 我 / "
        "覺得; 臺灣 / 旅遊) — as the Japanese tagger reads ﾅｲﾌ as ナイフ and keeps the text's spelling. As-is still keeps "
        "the scripts apart (學習 and 学习 are two rows — what the Script setting is for). This overrides the conversion "
        "spec's invariant I2 ('as-is is byte-for-byte today's behaviour') and the letter of the user's D2 ('zero "
        "behaviour change for anyone who doesn't touch it'), by name — the user was told (2026-09-29). Built "
        "2026-09-30 (step 4, Z3).",
        "The user, 2026-09-29, took the lean (Chinese_Decisions.md #10). NFKC-READING (F5: every tagger reads a "
        "normalized form while each token keeps the text's spelling) — the same shape; WORD-IDENTITY (為什麼 is a "
        "CC-CEDICT word, whichever script writes it); the re-analysis stance ('never a reason to not make something "
        "better'; every Japanese fix group re-analysed everyone once). I2's own reason — 'existing zh users must not "
        "get a surprise full rebuild on upgrade' — is the reason that stance set aside; D2 was about the script "
        "feature, and the F fixes changed default behaviour for every user. Measured: through Simplified fixes 7, "
        "breaks 0 (VALIDATION_leans §3.8); with HMM off it is what keeps Traditional text readable (為 / 什 / 麼 "
        "otherwise).",
        "Every Chinese user's as-is tokens change once (a store rebuild and a re-analysis, batched with the release's "
        "bumps); known words and cards keyed on the old junk re-match — for the better (a known 學習 stays one word, "
        "ZH-KNW-004). A Simplified text whose characters the Traditional→Simplified table changes could cut "
        "differently — checked on the Simplified fixtures (expected identical). The as-is golden of 2.2 "
        "(asis_tokens_golden.json) is regenerated on purpose.",
        "decided", ("Chinese_Decisions.md #10, §5 check 3", "Chinese_Script_Conversion_Spec.md I2, D2",
                    "Chinese_Build_Spec.md Z3", "debug/parsing_suite/VALIDATION_leans.md §3.8")),
    Decision(
        "ZH-HMM", "2026-09-29",
        "jieba's HMM (it guesses words its dictionary lacks): keep it on, or switch it off?",
        "Off — only the dictionary makes a word (jieba.cut(..., HMM=False) inside the one Chinese cut every caller "
        "reads, analyzer.chinese_cut) — switched together with ZH-TRAD-ASIS, and with a names guard built alongside: a "
        "run the HMM would keep whole stays whole where it spells a name, found the way the Japanese names were — a "
        "names source (CC-CEDICT's surnames) and grammar guards — and measured on general text first (guessed runs "
        "read by hand as name / real word / junk). Built if a guard reaches about 90% right; if none does, the numbers "
        "go back to the user (on vs off) before anything of it is built. Chinese_Build_Spec.md Z3. No guard reached "
        "~90% counted as the Japanese names were (partial names wrong); the user, 2026-09-30 ~19:45, took the lean — "
        "the surname guard — after seeing 40 of 100 guessed runs right with the guesses on, 57 with them off and 68 "
        "off with the guard: 'All of the mentions look good, your lean is good'. Built 2026-09-30 (step 4, #4): "
        "jieba's dictionary cut, and in a run of single characters it leaves, jieba's own model guesses; a guess of "
        "2-3 characters led by a CC-CEDICT surname, no jieba word, with no grammar character and no verb last at 3 "
        "stays whole (else its first two characters are tried: 龙仁 / 用) — 75% of what it keeps are names or words "
        "(90% counting partial names), and it keeps half the names; the rest is in characters (他 / 来, 我 / 要).",
        "The user, 2026-09-29, took the lean (Chinese_Decisions.md #4), recorded as the orchestrator's review framed "
        "it. WORD-IDENTITY (a statistical guess is no dictionary) pulls for off; the names decisions "
        "(NAMES-UNLISTED-KATAKANA, NAMES-RECURRENCE, NAMES-KANJI, 2026-09-28: a name the dictionaries lack stays one "
        "word, with guards, each measured first) pull for keeping the guesses that are names — resolved as the "
        "Japanese names were, by a measured guard. The tie rule (join when in doubt) covers names, 'not clear junk' — "
        "and a pronoun glued to a verb (他来, 我要) is clear junk. Chinese one-character words are list words, so a "
        "name cut into characters puts its uses on real words' rows (巴拿纳德 → 拿 'take' +1). Measured on the first "
        "baseline (VALIDATION_leans §3.7-3.8): off fixes 16 (12 glued non-words, 4 separable verbs) and breaks 5 "
        "(李明, 巴拿纳德, 列侬, 这下, 學習); with ZH-TRAD-ASIS, 23 fixed and 4 broken (學習 comes back).",
        "Off: the glued non-words leave the list (他来, 我要, 这是, 很近 — 105 of the samples' 1,168 distinct words were "
        "HMM guesses) and the words inside get their uses back; a name the dictionary lacks is split into characters "
        "that count as other words (李 / 明; 巴 / 拿 / 纳 / 德; 龙 / 仁 / 用) wherever the guard misses it; a word "
        "CC-CEDICT has and jieba lacks splits (这下, 郁卒 — ZH-COMPOUND-JOIN). With the guard: a name it misses stays "
        "split, a junk run it keeps stays glued. Names jieba's dictionary itself cuts (雅露露 → 雅 / 露露) are "
        "untouched either way (ZH-NAMES). The reinforce setting becomes inert (its two pairs are never guessed — "
        "ZH-REINFORCE).",
        "decided", ("Chinese_Decisions.md #4, §5 check 1", "Chinese_Build_Spec.md Z3",
                    "debug/parsing_suite/VALIDATION_leans.md §3.7-3.8",
                    "debug/parsing_suite/zh cases.md (Alternatives measured)")),
)


def _area_decisions():
    """Every decisions_<area>.py beside this file adds its own `ALL`, as evaluators_<area>.py adds layers — so areas
    ported in parallel never edit one file at once. A duplicate id still fails the integrity test."""
    import importlib
    import os
    import pkgutil
    here = os.path.dirname(os.path.abspath(__file__))
    extra = []
    for info in sorted(pkgutil.iter_modules([here]), key=lambda info: info.name):
        if info.name.startswith("decisions_"):
            extra.extend(importlib.import_module(f"tests.parsing.{info.name}").ALL)
    return tuple(extra)


ALL = ALL + _area_decisions()
DECISIONS = {decision.id: decision for decision in ALL}

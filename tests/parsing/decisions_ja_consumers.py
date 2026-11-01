"""The Japanese consumers' decisions — merged into the register by decisions.py (`_area_decisions`).

Decided: the choices the consumers already live by, recorded so a case the choice knowingly gets wrong can be a
LIMIT that names it. Open: the adversary's (debug/parsing_suite/ja_consumers) DISPUTED families, grouped, each with
both sides and a lean — for the user, in small batches (Parsing_Robustness_Suite_Scope.md decision 6). The other open
families the consumers trade on are in decisions.py: OGO-EXCEPTIONS (姉様, お帰り), IGNORED-ENTRIES, ONE-CHAR-IPLUS1
(and CJ-1B, sound words, decided 2026-09-27).
"""
from tests.parsing.decisions import Decision

ALL = (
    # --- decided ------------------------------------------------------------------------------------------------- #
    Decision(
        "SKIP-SINGLES", "2026-09-22",
        "A Japanese one-character word (醤, 昴, 光): a list word, a card the list can match, a word Junban counts?",
        "Never a list word ('Exclude 1-character words', on by default for Japanese); so a one-character card matches "
        "no row (a one-character key only as a row's own Word, build_index) and Junban never counts one beside a "
        "card. The report's and 例文's sentence counts still do (ONE-CHAR-IPLUS1 is open). SUPERSEDED 2026-09-30 by "
        "ONE-KANJI-WORDS (a one-kanji dictionary word is a list word where it stands on its own) and ONE-CHAR-IPLUS1 "
        "(decided: what the list can't offer counts nowhere); its cases keep their answers, re-filed under those.",
        "Single kanji are as often pieces, readings and names as words (谷 the surname タニ, 見 the stem of 見る): "
        "49 one-character Orth keys matched real cards to the wrong word (Junban_Backlog_Spec §4.3, §12.2).",
        "Real one-character words (醤, 夢, 顔, 目) never get a row or a placed card; a one-character card goes by its "
        "sentence.",
        "decided", ("Junban_Backlog_Spec.md §4.3, §5.4, §12.2", "debug/parsing_suite/known RL-79, AM-25, AM-28")),
    Decision(
        "ONE-KANJI-WORDS", "2026-09-30",
        "A Japanese one-character word (手, 目, こと 事, 時 とき / じ, 昴, 斬 in 斬魄刀): when is it a list word?",
        "When the language says it is a word — rule V2, all four gates (the user, 2026-09-30, every lean A1-A9 with "
        "A4 / A6 adjusted): a one-kanji (lemma, reading) general text uses, most of the time, as a word of its own (a "
        "common noun, a pronoun, a な-word, an adverb, a conjunction, an interjection — never a prefix, a suffix, a "
        "proper noun or the よう of ような), that JMdict lists with that reading and a sense beyond an affix, counter, "
        "numeral or particle, and that JMdict marks common or both JPDB 2024 and Jiten rank in their top 20,000 "
        "(app/one_kanji_data.py, built from the shared set's text, JMdict and the two lists by "
        "scripts/build_one_kanji_data.py — never a library); counted only where it stands on its own: glued to another "
        "one-kanji piece (斬 + 魄 + 刀), right after a number (三 + 年) or right after a number's counter written in "
        "kanji (２時間目's 目, 三週間前's 前 — added 2026-10-01, the user's card examples) a use is a piece of "
        "something else — no use, "
        "example or unknown (analyzer.bound_uses; the token store keeps each file's, so the Rarity slider counts what "
        "Generate counts). Each reading on its own: (時, とき) is listed, (時, じ) by its own free uses; 中 ちゅう, 的 "
        "and 様 さま never. Kana-written words under a one-kanji lemma (こと, もの, ため, しばしば) and nouns that mostly "
        "work as suffixes (部, 式, 感) are list words when they pass. A listed one-kanji word counts in a phrase's "
        "readiness like any word (手に入れる waits for 手). Settings keeps the key exclude_single (on): 'List one-kanji "
        "words only when they're dictionary words'; off lists every one-character word, every use counting. A "
        "one-character spelling stays a card key only as a row's own word (build_index: a タニ card is never 谷's), "
        "and a one-character card read alone is never another row's word (見 is not 見る). スバル stays off (a "
        "names-side follow-up is logged: Parsing_Future_Work.md #6).",
        "Measured on the user's library (single_kanji/REPORT.md §3-§4): the rule lists 90% right rows on a beginner's "
        "list (99% by uses), 87% of the user's 23 new rows at the 43-use cut-off, 77% of 116 at 11; it reaches 264 of "
        "the 294 JPDB top-2,000 words hidden before. The table as built (1,130 words, general text's parts of speech "
        "where the measurement used the library's) agrees with the measurement on 1,026 of the 1,042 library words it "
        "listed. The gates each earn their place (§3: without the dictionary gates 32% of the extra rows are words; "
        "without gate 4, 斬 615 and 魄 568 uses become rows).",
        "The tagger's errors become rows (踵 read かかと in 踵を返す, 霞 a character's name, ナシ read as 梨, キモッ "
        "read as 肝): Ignore is the tool, as for any bad row. A word general text uses mostly as an affix stays off "
        "though it is a word too (本 'book', 方 'person': suffixes in about half and two thirds of the text's uses). Two "
        "one-kanji words side by side with no particle are pieces (私今, and a space a sentence's text doesn't keep: "
        "2-4% of a real word's uses). The counter clause (2026-10-01) can't tell a count's own word from a free "
        "one after a span of time: the 旅 'journey' of 三日間旅をした is a piece too — about 1 in 7 of the 121 "
        "uses it changes on the user's library (debug/parsing_fixes_run/bound_counts/measure_g2.json); Nつ目 (つ is no "
        "kanji) still counts 目.",
        "decided", ("debug/parsing_fixes_run/single_kanji/REPORT.md §3, §5, §11-§12",
                    "app/one_kanji_data.py", "analyzer.py § One-character words")),
    Decision(
        "UNIDIC-SHORT-UNITS", "2026-09-23",
        "The unit of a word: UniDic's short units (plus the app's affix joins), or the dictionaries' longer words "
        "(使いこなす, 言い出す, 引きずり下ろす)?",
        "UniDic's short units plus join_affixes (and, approved, B's noun compounds — CJ-B). A compound verb UniDic "
        "splits stays two words; a card for it is found as the run of its words (L9 phrases) and 例文 finds it the "
        "same way.",
        "Surasura and anki_miner share the tokenizer (fugashi + unidic-lite 1.0.8), so a card's words are the "
        "library's words; L9 recovers 194 of 221 multi-token cards (Junban_Backlog_Spec §4.2, §4.6, §11.1).",
        "Compound verbs never get a row, a placed card or パターン lines of their own (使いこなす = 使う + こなす; "
        "引きずり下ろす's pairing shows as 座から引きずる).",
        "decided", ("Junban_Backlog_Spec.md §4.2, §11.1", "debug/parsing_suite/ja_consumers F55",
                    "debug/parsing_suite/known PJ-40")),
    Decision(
        "L9-LEMMA-RUNS", "2026-09-23",
        "A phrase card (気がつく, ひと月, この方): found in the library as its run of lemmas, or as its run of "
        "lemmas AND readings / surfaces?",
        "Its run of lemmas, however each word is inflected (anki_match.find_phrases; 例文's phrases, "
        "sentence_corpus.collect) — reading-blind; never across a mark the tokenizer dropped (気が、付く: the run's "
        "surfaces must be one run of the sentence — 2026-09-30, with PHRASE-ROWS).",
        "Inflection must not hide a phrase (気がついた is 気がつく); UniDic's readings would not rescue the "
        "ambiguous ones anyway — it reads かた before が as ホウ (3 of 8 kept この方 sentences).",
        "A run of the same lemmas that is another word counts too: 一月 (January) for ひと月, この方 (ほう) for この方 "
        "(かた), 引かれる for 惹かれる, どうする for どうしよう — and 見る方 for 見方 (2 of 80).",
        "decided", ("Junban_Backlog_Spec.md §11.1 item 2, §12.4", "debug/parsing_suite/ja_consumers F56-F59, P27")),
    Decision(
        "NAMES-STAY", "2026-09-26",
        "Names (UniDic's 固有名詞, and names UniDic misreads as words): list words, known words, cards like any "
        "other?",
        "Yes — names stay on the list and are known like any word; the 人名 check only keeps them out of affix "
        "joins. A hiragana name UniDic cuts in two (ひろか = ヒロ + か) can't be caught reliably: Ignore handles a "
        "bogus row.",
        "Anki_Match_Consistency_Scope.md item 5 (no change). A learner meets the names of what they watch; a rule "
        "that guesses names from kana would be a list (WORD-IDENTITY).",
        "Knowing the name ひろか marks ヒロ known wherever it appears; name pieces fill list rows (ナミ from 司波).",
        "decided", ("Anki_Match_Consistency_Scope.md item 5", "debug/parsing_suite/ja_consumers K10")),
    Decision(
        "CACHE-BY-BUMPS", "2026-09-25",
        "The join table (app/reference_data.py) and the tokenizer's rules: in the cache keys, or announced by hand?",
        "By hand: a rebuild of the join table, or any tokenizer change, bumps SCHEMA_VERSION (the token store and "
        "the known-words cache are dropped) and ENGINE_REVISION (every report re-analysed) — no signature holds the "
        "table (CLAUDE.md engine rules).",
        "A version bump rebuilds everything once, batched per release; hashing a 1.6 MB table into every key on "
        "every read costs time for a change that ships with a release anyway.",
        "A rebuild without the bumps mixes old cached tokens with new ones and serves the old known-word sets — "
        "only the version pins in the tests force the edit.",
        "decided", ("CLAUDE.md §6 engine rules", "Patterns_Quality_Spec.md §15.9",
                    "debug/parsing_suite/known AF-77, RL-109", "debug/parsing_suite/ja_consumers K17")),
    Decision(
        "KNOWN-PIECES", "2026-09-25",
        "A known joined word (時間帯, お金, お休み): does it make its pieces known too?",
        "Yes (Patterns_Quality_Spec §6.2a): load_known_words adds the word, each token's lemma, the pieces of every "
        "joined word, and the combined key.",
        "Before words kept their affixes, knowing 時間帯 made 時間 known (17 lemmas, 2,787 uses would have lost it); "
        "a learner who knows the whole mostly knows its parts.",
        "A piece that is another word is marked known too: お金 marks 金 'gold' (キン), お休み marks 休む; knowing "
        "the base never marks the joined word (利用 ↛ 利用者 — U9 instead).",
        "decided", ("Patterns_Quality_Spec.md §6.2a", "debug/parsing_suite/known AF-54, AF-57, HX-28")),
    Decision(
        "PAT-COMPOUNDS", "2026-09-24",
        "パターン: is a run of nouns (奨学金 = 奨学 + 金, 時間帯) a word of its own, with its own lines?",
        "Yes — the builder counts every noun run as a word (patterns_build.count, `_run` / `_compound`), keyed by its "
        "spelling and its parts' readings; its parts keep their own counts.",
        "156 of the user's Lapis notes were skipped as 'phrases' without it (patterns_build.count).",
        "No headword gate: a name + a title (田中先生) is a word, a run across a phrase boundary is one "
        "(ご存知の通り年, これ以上騒ぎ — CJ-71), and the key's reading is the parts' (株式会社 カブシキカイシャ: "
        "rendaku lost — B keys by the list's reading, CJ-B).",
        "decided", ("modules/junban/patterns_build.py count()", "Compound_Join_Measurement.md §9.5",
                    "debug/parsing_suite/known CJ-70, CJ-71", "debug/parsing_suite/ja_consumers P01, P08")),
    Decision(
        "PAT-ITEM-SPELLING", "2026-09-23",
        "A パターン item (風に感じる): written as the text spelled its words, or with their readings?",
        "As the text spelled them — each word's commonest spelling (orthBase), never its lemma or reading.",
        "The card shows how the words are written; 期待を為る is not something a learner reads (patterns_build "
        "docstring).",
        "A partner whose reading changes its meaning reads ambiguously: そんな風に感じる shows as 風に感じる, 'feel "
        "the wind'.",
        "decided", ("modules/junban/patterns_build.py (the key-space contract)",
                    "debug/parsing_suite/ja_consumers P20")),
    Decision(
        "PAT-ADJACENCY", "2026-09-22",
        "パターン's pairings: from adjacency (the words next to each other) or from a dependency parse?",
        "Adjacency, with punctuation as a barrier (Patterns_Spec §12 #2); no dependency parser (GiNZA is out of "
        "scope: a new dependency, P7).",
        "fugashi + unidic-lite are already shipped; the gate compares the result with NLT's dependency-parsed "
        "yardstick before anything is adopted.",
        "A pairing with a word between (影響を強く受ける) counts nothing; the quotative と and the 'with' と share a "
        "tag (話す と〜 67% in news quotes); adverbial Nに / Nで can look like an argument.",
        "decided", ("Patterns_Spec.md §12 #2, P7", "debug/parsing_suite/known PJ-57, PJ-59")),
    Decision(
        "STALE-LIST", "2026-09-23",
        "Junban follows a list written before the latest known words (努力 just marked known): trust the list, "
        "or re-test every card?",
        "Trust the list it follows for where a card goes — its rows and their order; 'Reorder becomes Generate' "
        "(§16.6) tells the user when the library, the known words or the settings changed since the last Generate, "
        "and one Generate catches the list up. Whether a card's word is KNOWN is read from the known words as they "
        "stand, for every card, before its list key (amended 2026-09-27 with F8a — Junban's own D3: a known word "
        "goes last whatever else matched it).",
        "The preview must be the calculation the run writes (I5); a list that disagrees with KnownWord.json is "
        "out of date as a whole, and the gate says so. The known test never came from the list: 93 of the user's "
        "known words were list keys too (65 kana-only), and each such card took a list slot (Parsing_Suite_Findings "
        "§5 F8a).",
        "Until the user presses Generate, the list's rows and order are the last Generate's: a word just learned "
        "still holds its row (its own cards go last, as known) and the words around it keep their old ranks.",
        "decided", ("Junban_Backlog_Spec.md §16.6", "debug/parsing_suite/ja_consumers R09",
                    "Parsing_Fixes_Plan.md F8a")),
    Decision(
        "IGNORE-KANA-LINES", "2026-09-27",
        "An Ignore / Blacklist / Graduated line is compared with the lemma (為る, 其れ). Which lines are also read "
        "through the tokenizer: only a hiragana line read alone as ONE kanji word with the line's own sound "
        "(restricted: する → 為る, それ → 其れ), or every line, as KnownWord entries are (literal)?",
        "Restricted — the narrow rule as built in F8g (analyzer.load_simple_list): a hiragana line read alone as ONE "
        "kanji-spelled word with the line's own sound also names that word (する → 為る, それ → 其れ, ある → 有る); "
        "every other line — kanji, katakana, a line read with another sound or as several words — names only the "
        "lemma it spells.",
        "The user, 2026-09-27: 'Keep narrow' (the lean). F8g (Parsing_Suite_Findings §5). The lists hold lemmas the "
        "report wrote: read alone, 12 of the user's 105 distinct lines are ANOTHER lemma (為る → 成る, どん → 何の, "
        "ハイ → はい, 書き → 書く, 遅く → 遅い) and 12 split (一日 → 一 + 日, 彼の → 彼 + の). Restricted adds nothing on "
        "the user's lists and never makes a line ignore a word the user didn't name.",
        "A kana line UniDic reads with another sound still ignores nothing (いい is 良い, lForm ヨイ — JA-KNW-035; "
        "ください is 下さる). A kana line names one homophone (まく → 膜, JT-KANA-ALONE). Literal, given up: it would "
        "have ignored いい's 良い, and made the user's own Blacklist 為る ignore なる (成る) and 11 more lines ignore "
        "a word the user never named.",
        "decided", ("Parsing_Suite_Findings.md §5 F8g", "debug/parsing_suite/known RL-71")),
    Decision(
        "CARD-INFLECTIONS", "2026-09-27",
        "A card's word written in a conjugated form (取り消した, 行きません, 飲んじゃう): which endings are the word's "
        "own paradigm — the card placed at its dictionary form — and which make a word of its own?",
        "The plain conjugations only, as F8f built them (anki_match.INFLECTIONS, read by one_word / card_key — "
        "Junban's placement and the report's 'In Anki' label alike): the past た (だ, たら), the polite ます, the "
        "negatives ない / ず (ぬ, ん) / まい, the desire たい, the te-, ba- and tari-forms (て, ば, たり), and the "
        "aspect contractions UniDic files as auxiliaries (ちゃう, てる, とく) — after ONE conjugated word not written "
        "in kana alone: 行きません → 行く (JA-KEY-098), 考えた → 考える, never the noun 考え (JA-KEY-104). Voice and "
        "derivation make words of their own, never placed at the verb or adjective: せる / させる / れる / られる "
        "(待たせる JA-KEY-099, 知らせる) and さ (優しさ) — such a card is read through its adjective, as ADJ-SA "
        "decided (2026-09-29).",
        "The user, 2026-09-27: 'Yes' to keeping the set as built (the lean). JMdict's headword is the dictionary form "
        "— a paradigm is no entry of its own, while voice and derivation make entries (待たせる 'keep waiting', "
        "知らせる 'inform', 優しさ 'kindness'), and anki_miner mines them as cards of their own. F8f: 10 cases fixed, "
        "7 new (JA-KEY-098…104).",
        "A conjugated form JMdict lists as a word of its own is no paradigm: since CARD-SENSE (decided 2026-09-30) "
        "堪らない 'unbearable', 疲れた 'worn-out' and 知らない are words of their own, never placed at 堪る, 疲れる "
        "or 知る (JA-KEY-103, JA-KEY-084); a form it doesn't list (取り消した, 行きません) is its verb. A passive "
        "card mined for its verb "
        "(言われる, the list's row 言う) is not placed at 言う either. A card in kana alone is never read for its "
        "inflection (かった is 買った, 勝った or 刈った — MATCH-ENDINGS, JA-KEY-100). A known adjective makes its "
        "さ-noun card known (優しさ when 優しい is known) — ADJ-SA, decided 2026-09-29.",
        "decided", ("Parsing_Suite_Findings.md §5 F8f", "app/anki_match.py INFLECTIONS", "tests/test_anki_match.py")),

    # --- open: the adversary's DISPUTED families ------------------------------------------------------------------ #
    Decision(
        "KNOWN-BASE-AFFIX", "2026-09-29",
        "A card that is a known word + a polite prefix or a plural suffix — お部屋, ご苦労, ご挨拶, ご案内する, "
        "お話しする (部屋, 苦労 … known; U1 left them split: the お / ご form is under 30% of the word's uses), 俺たち, "
        "お前ら (俺, お前 known): the known word (Junban's known tier, the base's row for the label, the base's "
        "パターン), or a phrase / word of its own?",
        "The base, everywhere — known through each other: a card that is a word + the polite お / ご (read オ / ゴ) or "
        "a plural (達 タチ, 等 ラ, 共 ドモ) is that word — Junban's known tier and row, the 'In Anki' mark, パターン and "
        "例文 (anki_match.affixes_off through one_word; Known_Through_Spec.md, not built yet). Parsing already splits "
        "them (U1, AFFIX-GUARDS), so the list and sentences already read them as the base. A joined お / ご word the "
        "dictionary gives a meaning of its own (ご苦労, お見舞い, お守り, お帰り — OGO-EXCEPTIONS) stays its own word and "
        "card, but halfway: half score when its bare word is known, never an unknown in a sentence (Q1 (b), "
        "U9-SEE-THROUGH). Q3: the next reorder suspends the newly known cards (junban_later_suspend) — the measured "
        "list is shown to the user first. Q4: 例文 uses the base word's sentences, the card's own form first when as "
        "easy. Q6: the kana-card mark gap (べんきょうした) is fixed in the same build.",
        "The user, 2026-09-29: 'the 2 you mentioned are both what I would want. I want those known through each "
        "other' — and asked whether parsing works the same way: yes, one idea of 'known' for the list, i+1, Junban, "
        "the mark, パターン / 例文; parsing already reads the base. The spec's questions Q1–Q6 answered 'all great' "
        "(every lean). U1 calls お部屋 'a polite version of a common word' and AFFIX-GUARDS calls plurals regular "
        "grammar, not words — as MATCH-ENDINGS reads 努力する.",
        "Polite set phrases count as their word (お邪魔 → 邪魔, as お茶する → お茶); 方-plurals stay phrases (UniDic's "
        "方 カタ, as in 見方); お前ら / 俺たち cards (891× and 458×) go last as known and, with the user's suspend "
        "setting, are suspended by the next reorder. A dictionary お / ご word whose meaning moved (お守り) is read "
        "through its bare word in sentences; an ご苦労 card is its own card, not known through 苦労 (JA-JBN-034, "
        "JA-LBL-031 LIMIT).",
        "decided", ("Known_Through_Spec.md §0, §6 (answers at its top)", "debug/parsing_suite/ja_consumers F47, F48, F49",
                    "debug/parsing_suite/known AF-62, AF-66", "Patterns_Quality_Spec.md §6.4 (U1)")),
    Decision(
        "ADJ-SA", "2026-09-29",
        "An い-adjective + さ (優しさ, 暑さ) when the adjective is known: known through the adjective, or a word of "
        "its own?",
        "Through the adjective, everywhere — known through each other, as parsing already reads it: an い-adjective is "
        "never a base for a suffix join (analyzer._is_base), so 優しさ is ALWAYS two tokens, 優しい + さ, and U9 never "
        "sees it. A card of an adjective or a な-word + さ / み read alone is that word (anki_match.affixes_off through "
        "one_word; Known_Through_Spec.md, not built yet): Junban's known tier and row, the 'In Anki' mark, パターン and "
        "例文. A known 優しさ makes 優しい known (load_known_words, as before). A card in kana alone keeps its さ "
        "(やさしさ: 優しさ or 易しさ is the tagger's guess, as CARD-INFLECTIONS). UniDic's own さ / み nouns (静けさ, "
        "楽しみ, 強み) are words of their own (Q5).",
        "The user, 2026-09-29: 'I want those known through each other' — and 'it would function the same way when "
        "parsing too? because same word': yes, and parsing already does. U2 counts 不自然さ toward 不自然; さ is "
        "regular grammar, never joined. (Not 'its own list word at half score' — that premise was wrong; "
        "Known_Through_Spec.md §0 corrects it.) Spec questions answered 'all great'.",
        "Kana さ-cards go by their sentence; with the user's suspend setting a new 優しさ card whose adjective is "
        "known is suspended by the next reorder (shown first, Q3). Seeing 楽しみ / 強み through their adjective would "
        "need a hand-made list, so they stay words.",
        "decided", ("Known_Through_Spec.md §0, §6 (answers at its top)", "debug/parsing_suite/ja_consumers F51",
                    "Patterns_Quality_Spec.md §6.1, §8.4 (U2)")),
    Decision(
        "CARD-SENSE", "2026-09-30",
        "A card whose word is a dictionary entry of its own but that UniDic reads as another lexeme — 心する 'take "
        "heed' (心 + する), 揚げる 'deep-fry' (filed under 上げる), the noun 集い (the list's row is the verb 集う; "
        "the library has 1 noun use, 8 verb uses spelled 集い), the noun 生き when only 生きる is listed, a kana card "
        "read as a word + an ending (ことに 'especially', 殊に — 事 + に, known): that lexeme's row / known status / "
        "パターン / 例文, or a word of its own?",
        "A word of its own exactly when JMdict gives the card's word an entry of its own, apart from the word it is "
        "read as — no entry holds both (anki_match.two_words: the card's word by its kanji spelling, or a card in kana "
        "alone by the readings it can end in, app/jmdict_data.py READINGS; the other word by a kanji spelling only). "
        "Such a card is never that word's: Junban places it by its own sentence (or as a phrase, L9) unless a list row "
        "carries its own spelling — the row's Word or Orth (anki_match.another_word: 治める on the 収める / 治める row "
        "is that row's); it is never known through that word (Junban's known tier, Backfill's skip); the 'In Anki' "
        "mark marks no row of that word; パターン come only from a word the database holds as the card writes it (its "
        "lemma, or its main spelling: 帰る is the database's 返る written 帰る); 例文 search the library for the card's "
        "own word — its run of words (心する, 一気に), or one word as it is written (sentence_corpus.collect: a word "
        "whose lemma or dictionary spelling IS the card's — 揚げる, never 上げる). Inside one entry (逃げだす in 逃げ出す's) "
        "the card is that word, as before; with no entry for the card's word (努力する, お茶する: the noun takes する) "
        "or for a word in kana it is read as (ひょい of ひょいと; すっ of すっと, never the prefix 素っ that shares its "
        "sound) nothing changes. Kept apart from the rule: the word's own grammar comes off first, whatever JMdict "
        "lists (お部屋, 俺たち, 暑さ, ご無沙汰 are entries — KNOWN-BASE-AFFIX, ADJ-SA); a じる verb and its ずる form are "
        "one verb (UniDic files 信じる under 信ずる; JMdict gives each conjugation an entry, with the same senses); "
        "the user's 'yes' still places a card, and 'Same word as one on your list?' asks nothing across two "
        "dictionary words (対する is no 対 + する). Spellings compare in NFKC, as a card's word is read (JMdict's "
        "２０世紀 is a 20世紀 card's).",
        "The user, 2026-09-30: 'This is a good trade. I would let the dictionary decide'. The lean (2026-09-26) — a "
        "word of its own exactly when JMdict has a separate entry — taken; its one example of the other side is gone: "
        "today's JMdict gives 揚げる 'to deep-fry' an entry of its own (2864817), apart from 上げる's, so a 揚げる card "
        "is a word of its own too, never known through 上げる (JA-JBN-046 corrected). Measured read-only (lane CS, "
        "debug/cs_measure): 11 of the user's 187 new cards (backlog of 2026-09-29) change — 心する, 揚げる, ハンパじゃない "
        "('tremendous', an entry of its own) and eight words JMdict lists whole with a number in them (何人, 何年, 何日, "
        "何種類, 数年, 数日間, ２０世紀, ９０年代) leave Junban's known tier for their sentence; all 11 were and stay behind "
        "the list (the 'not on your list' actions reach them either way); no 'In Anki' mark moves. On the frozen "
        "backlog (302 cards, 2026-09-26) 17 change: those kinds, ひと月 and １年, and 4 cards leave a list row whose "
        "Forms hold their spelling (集い, 仕向け, 従兄, 蹴っ飛ばす — 4 rows lose their mark).",
        "A card JMdict lists whole goes by its own sentence where it once took a list row or went last as known: the "
        "に-adverbs JMdict lists (一気に 'in one go', 本当に, 確かに, すぐに, 急に, 勝手に — not 丁寧に or 最後に, which it "
        "doesn't), past and negative forms it lists (疲れた 'worn-out', 知らない, 堪らない, 済まない), words with a "
        "number (何人, 一年 — NUMERALS-NOT-WORDS' card price paid back), a noun spelled as a verb's stem (生き, 仕向け, "
        "集い) and a variant it keeps apart (蹴っ飛ばす, 撮る from 取る, 従兄 from 従兄弟). Such a card has no パターン "
        "until a database holds it (心する, 揚げる), finds 例文 only as written (ひと月 none: the library never holds it "
        "as one token), and a kana card's run is reading-blind (ことに's 事 + に also meets ことにする). A card that "
        "leaves a row whose Forms hold its spelling still counts as 'on the list in some form' for the later actions, "
        "so the user's suspend setting leaves it alone.",
        "decided", ("debug/parsing_suite/ja_consumers F18, P18, F33, D18, P26, F54, F39",
                    "debug/parsing_suite/known AM-21", "app/anki_match.py two_words, another_word, word_of_its_own",
                    "debug/parsing_fixes_run/lanes/CS/HANDOFF.md")),
    Decision(
        "NAME-WORDS", "2026-09-30",
        "Names in the consumers: an unknown name in a sentence (茂木さん) — an unknown for i+1 or not? A name card "
        "(ユウカ) — パターン lines from other people of that name, or none? A kana card of a common word (ひかり "
        "'light') that spells a name row (ヒカリ, 271 of 290 uses ひかりさん) — that row, or the word 光?",
        "(a) A name counts like any other word, everywhere — the report, 例文, the sentence dictionary, Junban's tiers "
        "and now 'i+1 first' too (it never counted one) — unless the learner turns on Settings → Language & Parsing "
        "→ Ignore names (off by default): the library's names are then ignored words everywhere (off the list, never "
        "an unknown in a sentence: the list, the Rarity slider and automatic rarity, Junban, 例文, the sentence "
        "dictionary, the YouTube preview — whose video's own names count too), through ONE reader "
        "(token_index.ignored_names, inside ignored_entries, which every ignore set already calls). A name there: "
        "a word the tagger's dictionary knows and tags as a person's name (固有名詞 人名), 2+ characters; a katakana "
        "name made one word (names layer 1); a JMnedict kanji name the library's table joins (layer 3) — never a "
        "spelling UniDic also lists as a common word said the same (ひかり / 光, 悪魔, 渚), a name keyed as a common "
        "word is (麻衣 = マイ 'my'), an unknown word, the katakana runs the library repeats (layer 2: 15 of 69 are "
        "people), or a work's own terms (layer 4). The token store records each file's names (SCHEMA 12). "
        "(b) A name card keeps its パターン lines (only the register chip is dropped), as built. (c) A hiragana card "
        "read alone as a word with a kanji (ひかり → 光) never takes the row whose own word is its letters in katakana "
        "(the name ヒカリ; likewise the loanword ダイブ for だいぶ) — in Junban and the 'In Anki' label alike "
        "(anki_match.not_the_name) — it lands on its own word's row when the list has one; a katakana ヒカリ card still marks the name row. No honorific check.",
        "The user, 2026-09-30: (a) 'You would still need to learn names UNLESS they select ignore names as a "
        "setting', then 'Yes to ignore names switch'; (b) 'nothing wrong with seeing the contexts that name is used'; "
        "(c) a hiragana ひかり card is the word 光, the honorific check skipped ('skip it if it adds anything'). "
        "Measured on the user's library (1,987 files, read-only, lane IN): the switch hides 3,095 lemmas, 57.7k of "
        "4.28M counted tokens (1.3%); UniDic's tag gives 2,144 lemmas, layer 1 888, layer 3 68. What it gets wrong "
        "is in the tradeoff; layer 2 was left out on the measurement (terms, places, titles, web boilerplate and "
        "common compounds — ネックストラップ, テリヤキバーガー — outnumber its people).",
        "(a) Counting names: a card whose sentence holds a name later on the list waits in 'i+1 first' (or brings "
        "the name's card first). The switch is conservative: a name spelled or keyed like a common word stays "
        "(ナギサ / 渚 577 uses, ヒカリ / ひかり 278, マイン 1,746, レム 999, ユカワ 412, ローズ ...), so do names the "
        "tagger doesn't know as one word (ルキア) and the katakana runs the library repeats (ヒラマン, トルフィン); "
        "and a few sounds UniDic lists as foreign names are hidden with the names (ウッ 312, ダー 116, イッ, ブー), "
        "as are a lemma's common uses when the common word isn't UniDic's reading of the spelling alone (イエス "
        "'yes' 26 beside Jesus 434, ギル, タイ, エル: 396 uses in 56 lemmas). A name card, with the switch on, is "
        "an ignored card: Junban puts it last and Backfill skips it, as any ignored word's. (c) A hiragana card that "
        "IS the name or the loanword (a character called ひかり) no longer lands on its row by its letters — it goes "
        "by its sentence, or the user's 'yes'.",
        "decided", ("debug/parsing_suite/ja_consumers D12, P19, F29", "Junban_Backlog_Spec.md §17",
                    "debug/parsing_fixes_run/lanes/IN/HANDOFF.md")),
    Decision(
        "LABEL-VS-JUNBAN", "2026-09-29",
        "逃げだす (no answer yet): the report's 'In Anki' label reads a kanji card through the dictionary and marks "
        "逃げ出す automatically (Patterns_Quality_Spec Part B), while Junban only ASKS (L6, 'Same word?'). One answer "
        "for both — which?",
        "Both automatic for a card with a kanji that reads alone as ONE word — the whole word one token, more than "
        "one character — whose lemma is a list row: 逃げだす IS 逃げ出す (anki_match.whole_word_alone, read by "
        "card_key — Junban's placement, via L6 — and by the label's _dictionary_keys). Junban keeps asking only for "
        "kana cards (まく ↛ 膜) and for the sentence bridge (みとれる shown by its sentence as 見惚れる, JA-KEY-908); "
        "the user's 'no' always wins (JA-KEY-911). A one-character card is never read alone into another row, in "
        "the label either (見 ↛ 見る: JA-KEY-909, -912 — the label read it so until then).",
        "Part B: the label is keyed by the dictionary (92 of 328 cards were unlabelled before it). The consistency "
        "scope: 'the label means exactly where Junban places a card'. The user, 2026-09-29: took the lean ('keep "
        "going'). Built by lane RC4: on the 2026-09-26 snapshot's backlog one more card is placed with no question "
        "(なり代わる → 成り代わる); the other kanji cards it reads alone already had the user's 'yes'.",
        "A wrong lemma read alone (a homograph) places a card without asking — measured 0 wrong on the backlog's "
        "kanji cards; a kana card is still asked about, and the label still marks a kana card's word only by its "
        "letters.",
        "decided", ("debug/parsing_suite/ja_consumers F35", "debug/parsing_suite/known AM-49",
                    "Anki_Match_Consistency_Scope.md item 1", "tests/test_anki_match.py")),
    Decision(
        "PAT-ORDER", "2026-09-30",
        "パターン's collocations: ordered by strength (logDice: 気に入る · 気がつく) or by count (気にする · 気がする)?",
        "Strength (logDice), as built: a card leads with the patterns most typical of its word — how much more often "
        "the two meet than their own commonness predicts (気に入る leads 気's card), not the commonest pairing (気にする, "
        "where する goes with everything).",
        "Patterns_Quality_Spec §15.9 question 2 (the user reads both versions). logDice favours what is common WITH "
        "the word, and lets rare items through (29 of 600 seen fewer than 10 times: 報酬が貰う, 不自然な長寿); by count "
        "the lines turn generic (良いこと, 早くする). Lean: logDice, as built. The user, 2026-09-30: 'I think most "
        "typical' — after the difference was explained (frequent = how often two words meet; typical = how much more "
        "often than their commonness predicts; by frequency する / ある / なる would lead almost every card): nothing "
        "changes.",
        "logDice: a rare pairing can lead a card. Count: common verbs and empty nouns lead every card.",
        "decided", ("Patterns_Quality_Spec.md §8.2, §15.9 Q2", "debug/parsing_suite/known AF-70")),
)

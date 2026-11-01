"""Decisions the Japanese tokenizing cases trade on (cases_ja_tokens.py), merged into decisions.py's register.

Decided: JT-PART-A (the 2.3 affix join itself), JT-NAMES, JT-SENSE, JT-EXPRESSIONS, JT-KANA-ALONE, JT-SANITIZE,
JT-JAPANESE-ONLY — choices already made (in a spec, a release, or the adversary's accepted limitations), recorded
with what they give up; NFKC-READING (F5, 2026-09-27: what every tagger call reads); NUMERALS-NOT-WORDS (the
user's decision 2, 2026-09-27, built in F6); NAMES-UNLISTED-KATAKANA, NAMES-RECURRENCE and NAMES-KANJI (decision 9
and names layers 2 and 3 — decided by the user 2026-09-28, built in app/names.py). JT-PLACE-BASE, JT-NUMERAL-WORDS, JT-NA-ADJ, JT-B-FRINGE (B's blind spots and fringe, found by the
adversary after the compound leans were approved) and JT-COMPOUND-VERBS — decided by the user 2026-09-28 with the
compound build (Compound_Build_Spec.md), recorded before its lanes branched. KATAKANA-COMPOUND-IN-NAME (step 3: a
katakana compound cutting a katakana name — measured by lane KN, decided by the user 2026-09-29 with the lean, built by
lane KN2). IN-TEXT-COMPOUNDS (a headword the build reads only alone, read where the text writes it — measured
2026-09-30 in debug/parsing_fixes_run/in_text_compounds/REPORT.md, every lean taken by the user, built by lane IT).
"""
from tests.parsing.decisions import Decision

ALL = (
    # --- decided ------------------------------------------------------------------------------------------------- #
    Decision(
        "JT-PART-A", "2026-09-25",
        "Join a prefix / suffix run back into one word (新幹線, 可能性, 子供っぽい, 違和感)?",
        "Yes — Part A: 接頭辞 + a base, or a base + 接尾辞 (and 感, a noun UniDic uses like a suffix), joins when the "
        "whole is a JPDB 2024 / Jiten headword in both lists or one list's top 60,000 (U15), with the list's reading "
        "and the suffix's word class. A base is a noun (never a number or a person's name — a place is allowed: "
        "日本人), a な-word, or after 御 a verb's 連用形. One function for every caller: analyzer.join_affixes.",
        "Patterns_Quality_Spec.md Part A and checkpoint A: UniDic's short units cut off the word the content says "
        "(the list counted 幹線, 可能, 日本); the dictionaries decide which runs are words (WORD-IDENTITY).",
        "The lists' long tails still join a few names and misreadings (むいみ → 無意味, 事力); a verb form (非モテ), "
        "an adjective (お + めでたい) is never a base, nor a pronoun while logic.pronoun_bases is off (PRONOUN-BASES, "
        "2026-10-01: on, the default, お前さん is one word); a join-table word the tagger reads "
        "as two plain nouns in some contexts (父上が, 母上が) is joined by neither Part A nor B; every table rebuild "
        "needs SCHEMA_VERSION + ENGINE_REVISION bumps.",
        "decided", ("Patterns_Quality_Spec.md Part A, §6.1-§6.2, §15.1", "CLAUDE.md engine rules")),
    Decision(
        "JT-NAMES", "2026-09-26",
        "Names UniDic doesn't know are cut into words (モロナイ → モロ + ナイ, 一護 → ハジメ + マモル) or read as common words (さくら "
        "→ 桜, アウロラ → オーロラ): a name rule, or names as ordinary words ignored by hand?",
        "No name rule in the tokenizer or the core list: names are ordinary list words, ignored by hand. A name "
        "UniDic knows keeps its katakana lemma (須藤 → スドウ). Superseded 2026-09-28 for names the tagger cuts into "
        "pieces: NAMES-UNLISTED-KATAKANA, NAMES-RECURRENCE and NAMES-KANJI make them one word (their LIMITs re-filed "
        "under those); a name stays a list word, ignored by hand (NAMES-STAY).",
        "Junban_Module_Spec.md §15 Q2 (settled: no proper-noun filter — 'a card existing means the user already "
        "chose to mine that word'); the core list keeps names (known_cases RL-46). Telling an unknown name from "
        "words would take a name list (WORD-IDENTITY: no hand lists). Accepted in the adversary's catalogue (names: "
        "16 of 20 rows LIMITATION).",
        "Name pieces fill the head of the list (ナイ #4, モーサ #2, モロ #11, ＲＯＭ #27, ロゼ #32; about 28 of the top 70 rows "
        "are names); a split name's pieces count as real words (一 read ハジメ, 250 uses); a name read as a common word "
        "shares that word's row (アウロラ / オーロラ, the surname 茶柱 / 'tea stalk').",
        "decided", ("Junban_Module_Spec.md §13 #9, §15 Q2", "debug/parsing_suite/known RL-46, RL-47", "debug/parsing_suite/ja_tokens N01-N20")),
    Decision(
        "JT-SENSE", "2026-09-26",
        "Where only the meaning tells two words or readings apart — a kana spelling (いる 居る / 要る, とる 取る / "
        "撮る, さばき 捌き / 裁き), a kanji verb with two readings (止める とめる / やめる), a filler or a determiner "
        "(あの), an ambiguous string (はきもの, 十分待った, 何人) — take the tagger's pick, or add sense rules?",
        "The tagger's pick stands: no word-sense rules.",
        "Accepted in the adversary's catalogue (LIMITATION, 2026-09-26). UniDic (unidic-lite, the version anki_miner "
        "shares — an upgrade was declined, known_cases RL-77) picks by its lattice costs; 要る vs 居る needs the "
        "meaning, and a rule per word would be a hand list (WORD-IDENTITY). Kanji words a context could decide "
        "(人気のない ひとけ, 今何時 なんじ, 辛いもの からい, casual 今日 きょう) are NOT accepted — they are TARGETs.",
        "Those uses count toward the tagger's word: お金がいる credits 居る, 写真をとる 取る, やめておく とめる; the "
        "learner sees the other word's row and reading.",
        "decided", ("debug/parsing_suite/ja_tokens V10b, V33, V34, R11, R12, L04, M12",
                    "debug/parsing_suite/known RL-77")),
    Decision(
        "JT-EXPRESSIONS", "2026-09-23",
        "Multi-word expressions the lists carry as headwords — noun + adjective (気持ち悪い, 申し訳ない, 間違いない), "
        "a particle inside (しょうがない, あっという間, 知らぬ間に, お気に入り), a pronoun + a copula (なんで, "
        "なんだかんだ): one word, or their pieces?",
        "Their pieces. The tokenizer joins affixes (Part A) and, if built, noun + noun compounds (B) — never a phrase. "
        "Phrases are the Phrase Bundle's job (additive rows): since 2026-09-30 the list adds a row for the phrase "
        "(PHRASE-ROWS — the tokens unchanged), so these cases stay LIMIT at the token layer and their partners at the "
        "phrases layer (JA-PHR) are LOCKs. An adverb or a conjunction JMdict lists that the tagger cuts at its "
        "particles is one word since 2026-10-01 (CUT-WORD-PARTICLES: なんで 'why'), and a run of one inside a longer "
        "JMdict spelling stays that spelling's pieces, as an expression's are.",
        "Phrase_Bundle_Spec.md (2026-09-23): 'I do eventually want the bundle … we won't implement that right now'. "
        "A phrase joined in the tokenizer would take its pieces' uses from every other sentence.",
        "The list never offers the expression; its pieces take its uses, some as junk (しょうがない's しょう read "
        "仕様, なんだかんだ's かん read 彼).",
        "decided", ("Phrase_Bundle_Spec.md", "debug/parsing_suite/ja_tokens E01-E06, S34, V15")),
    Decision(
        "JT-KANA-ALONE", "2026-09-26",
        "A KnownWord entry is tokenized alone (load_known_words); a kana entry (かえる, はし) names no kanji word — "
        "trust the tagger's pick?",
        "Yes, as built: the dictForm is read by the tokenizer alone and trusted, and the dictForm itself is known as a "
        "lemma.",
        "analyzer.load_known_words (known_cases RL-68): the tokenized dictForm makes a known 辿り着く cover "
        "辿り着いた. Accepted for kana entries in the adversary's catalogue (LIMITATION, K01-K02).",
        "A kana entry marks one homophone: knowing かえる marks 蛙, never 帰る / 変える; はし marks 箸, never 橋. When "
        "the pick is a name (かみ → 嘉美, かける → カケル) the entry marks nothing useful — those are TARGETs.",
        "decided", ("debug/parsing_suite/ja_tokens K01-K03b", "debug/parsing_suite/known RL-68")),
    Decision(
        "JT-SANITIZE", "2026-09-26",
        "UniDic glosses some lemmas (テスト-test, イエス-yes, そう-様態): keep the gloss, or cut it?",
        "Cut it: _sanitize_term cuts a Japanese lemma at the first ASCII hyphen or space — always on for Japanese "
        "since v2.0 (the toggle was removed).",
        "RELEASE_v1.5.md, PRE_RELEASE_FEATURES_v2.0.md (known_cases RL-37): glossed lemmas made -suffix rows and "
        "missed the frequency lists.",
        "Homographs UniDic tells apart only by the gloss share a row: イエス 'yes' / イエス 'Jesus', そう-様態 / the "
        "adverb そう (the shipped Blacklist line そう-様態 blacklists both).",
        "decided", ("debug/parsing_suite/known RL-37, RL-38, HX-19",)),
    Decision(
        "JT-JAPANESE-ONLY", "2026-09-26",
        "Which tokens can be words at all?",
        "A token counts only with kana or kanji in its lemma or surface, and never a symbol or a space (補助記号, "
        "空白, 記号 — the '记号' typo fixed in F6, 2026-09-27): Latin (iPhone, OK), digits, kaomoji, emoji and "
        "compatibility symbols (㈱) never count, nor a character UniDic reads as a character (記号,一般: 玖 キュウ, "
        "乃 ノ, しゃ, いー). One kind of 記号 is text: a letter spelled out by its name (記号,文字 with kana in its "
        "surface: デルタ, アルファ, ガンマ線's ガンマ) is a word, counted under that name — its lForm, so アルファー is "
        "アルファ — not under the symbol UniDic makes its lemma (δ, α). analyzer.word_lemma.",
        "analyzer.JapaneseTokenizer.tokenize_sentences' filter and main's count (known_cases RL-43, RL-94). F6 "
        "(Parsing_Suite_Findings.md §5, approved 2026-09-27): the filter meant UniDic's symbol class but spelled it "
        "记号 (Chinese), so a 1-in-10 sample kept 913 記号 tokens with kana or kanji as words (about 9,100 library-"
        "wide: アア #187, イー #641, ホウ #869, キュウ 680 uses from the name 玖渚); UniDic files a letter's name "
        "(記号,文字) — a JMdict word, デルタ, アルファ — as a symbol too, so the fix keeps those.",
        "A word in disguise is lost: ㈱ (株式会社) never counts, nor the Latin half of Tシャツ, nor ＯＫ in full-width "
        "Latin (read as OK since F5: NFKC-READING). Half-width katakana (ﾅｲﾌ) is read as full-width katakana since F5 "
        "and counts. Since F6 a name or an interjection UniDic files as 記号 no longer counts (いーちゃん's いー, row "
        "#641; the ああ it tags アア, #187, is not recovered as ああ either), and a name piece spelled like a letter's "
        "name becomes a listable word (ニーファイ's ファイ, the character ゼータ) where it was the one-character φ, ζ.",
        "decided", ("debug/parsing_suite/known RL-43, RL-94", "debug/parsing_suite/ja_tokens C13-C15, C20-C30",
                    "Parsing_Suite_Findings.md §5 F6", "app/analyzer.py word_lemma")),
    Decision(
        "NFKC-READING", "2026-09-27",
        "Compatibility forms (ﾅｲﾌ, ５０, ＯＫ, ⽅, ㌔, ①), text in decomposed form (か + U+3099) and invisible format "
        "characters (a zero-width space): how does a tagger read them?",
        "Every tagger call (both tokenizers, the known words, the token store, パターン's build and lookup, the "
        "sentence dictionary, 順) reads text through analyzer.tagger_text: a character whose NFKC form is made of "
        "letters, marks and digits is read in that form (ﾅｲﾌ → ナイフ, ５０ → 50, ＯＫ → OK, ⽅ → 方, ① → 1, ｶﾞ and "
        "か + U+3099 → ガ / が); a default-ignorable character (zero-width space, variation selector, soft hyphen) is not "
        "read; punctuation, symbols and spaces are read as written. A token's surface, its sentence and the "
        "boundary test keep the text's own spelling; an unknown word is named by the text as read.",
        "F5 (Parsing_Suite_Findings.md §5), approved 2026-09-27 (Parsing_Fixes_Plan.md decision 1): a compatibility "
        "character is the same text (Unicode NFKC) — the library's 6,727 half-width katakana tokens were never "
        "counted, ５０ was read フィフティー and １０分 テン + ブン, ⽅法 and a word cut by a zero-width space were lost. "
        "Punctuation and spaces stay as written: they are never words, UniDic writes Japanese punctuation full width "
        "(its lemma for ! is ！), and NFKC turns a full-width space (a token that keeps two words apart) into a space "
        "the tagger skips. The user, 2026-09-27, confirmed the price below: full-width digits read as digits "
        "(１人 → 1 + 人), as ASCII digits already were.",
        "UniDic spells a few words with full-width digits or Latin letters, and those now read as their ASCII "
        "spelling already did: １人 / ２人 / １番 / １日 are 1 + 人 and so on — 一人, 二人, 一番, 一日 count only where "
        "the text writes them in kanji or kana (as with 1人); ＯＫ, ＣＤ, ＴＶ are Latin and never count "
        "(JT-JAPANESE-ONLY); １０代 no longer joins (it joined only because １０ was misread as テン: the number "
        "guard, AFFIX-GUARDS, keeps 10代 apart); ㍿ reads as 株式 + 会社, the second piece with no surface of its own.",
        "decided", ("Parsing_Suite_Findings.md §5 F5", "Parsing_Fixes_Plan.md §1 decision 1",
                    "app/analyzer.py tagger_text")),
    Decision(
        "NUMERALS-NOT-WORDS", "2026-09-27",
        "Numbers (二十, 五十, 百, 〇, Ⅲ): list words and unknown words in a sentence, or never?",
        "Never — the user, 2026-09-27: 'Bare numbers (二十, 五十, 百, 〇, Ⅲ) are never list words and never count as "
        "unknown words in a sentence. Idioms that hold a numeral (一石二鳥) are a separate, later question "
        "(JT-NUMERAL-WORDS, with the compound build).' Built in F6 as UniDic's class: a 数詞 token is no word "
        "(analyzer.word_lemma drops it from the tokens every caller reads) — kanji numerals, digits, 〇, Ⅲ, ①, ゼロ, "
        "and 何 / 数 / 幾 counting (何人, 数十, 幾つ).",
        "Parsing_Fixes_Plan.md §1 decision 2 (Parsing_Suite_Findings.md §5's one quick yes/no): a number is no "
        "vocabulary — 二十 was list row #28 (341 uses), 五十 #102 (139), 30 kanji numerals were counted as words "
        "(三十 272, 四十 151), 百 / 万 made sentences look harder (万 alone blocked 180). UniDic's class says what a "
        "number is, not a list; it holds 何, 数 and 幾 where they count (何人, 数十), as the number guard "
        "(AFFIX-GUARDS) already reads them. Digits were never counted (no Japanese); they leave the tokens too. "
        "The user, 2026-09-27, accepted the card price below — a card holding a number (何人, ２年生, ２０世紀) reads "
        "as its other word for now — to revisit with JT-NUMERAL-WORDS.",
        "What the tokens no longer hold, every caller loses together (one parse): indefinite numerals leave the list "
        "(何十 65 uses, 何千 59, 何百 41, 数十 33, 数百 26, 数千 17 on the 2026-09-26 counts); ゼロ never counts; a "
        "numeral inside a word or idiom is gone from it (一石二鳥 is 石 + 二鳥, 精一杯 精 + 杯) until JT-NUMERAL-WORDS; "
        "a card's word loses its number — ２０世紀, ９０年代, 数年, 何人, ひと月 read alone are the one word 世紀 / 年代 / "
        "年 / 人 / 月, so 順 filed such a card known when that word is (10 of the 302 backlog cards of 2026-09-26; "
        "since CARD-SENSE, 2026-09-30, a card JMdict lists whole — all ten — is a word of its own, never known so), "
        "a phrase card keeps only its other words (２年生 is 年 + 生, and meets every N年生), and 例文 for ひと月 finds "
        "no sentence; a file's word total no longer counts its numbers.",
        "decided", ("Parsing_Fixes_Plan.md §1 decision 2", "Parsing_Suite_Findings.md §5",
                    "app/analyzer.py word_lemma")),

    # --- decided 2026-09-28: names (decision 9) and the compound build's six ---------------------------------------- #
    Decision(
        "NAMES-UNLISTED-KATAKANA", "2026-09-28",
        "A katakana run the tagger cuts into pieces (トゥー + リ, モーサ + ヤ, グリム + ジョー, リム + ハイ) whose spelling neither "
        "JPDB 2024 nor Jiten lists: keep it ONE word (decision 9) — every such run, or only a run with a piece that "
        "is no common word?",
        "Yes — the run as names-katakana-pieces measured it, with two guards (the user, 2026-09-28: \"I take all your "
        "leans\"): a katakana run the tagger cuts, whose spelling no JPDB 2024 / Jiten headword has and with at least "
        "one piece that is no common word, is ONE word keyed as a word the dictionary lacks (its spelling, no "
        "reading, unknown); a run of common listed words stays in pieces (NAMES-RECURRENCE may join it); so does a "
        "run that is one piece repeated (its spelling less a final ッ / ー is one unit twice or more: ブンブン + ブンブン, アア "
        "+ アッ) and a stutter (a piece cut off with ッ, then a word starting with the same sound: バッ + バカ). Built in "
        "app/names.py, called from analyzer.join_affixes (every caller); its own switch, logic.names_katakana, "
        "default on (Settings → Language & Parsing); in the token store's build signature when off. On a tie the "
        "user's rule: \"I would prefer that it combine wrong ones than separate right ones, granted all else is "
        "equal\" (プラスアルファー joining is forgivable). Refinement decided 2026-09-28 (the user's answers to the step-3 "
        "questions, 2026-09-28: \"I take all leans as accurate\", answer 2): a run made only of interjections — every "
        "piece UniDic's 感動詞 (アッ + ハハ, ウワ + アア) — stays in pieces: laughter and cries, not a name; built as a variant "
        "first (JA-NAM-901, 902). As built (WP-4, app/names.py katakana_kind; recorded 2026-09-28): a run whose EVERY "
        "piece the tagger tags 感動詞 is a sound, in pieces; one piece of another kind keeps it a name, one word "
        "(ハイミロ = ハイ + ミロ: JA-NAM-801). A laugh or cry with a piece the tagger reads as a letter (記号: キャアア = "
        "キャ + アア, イヒヒヒ, ウギャ, ブワーッ) stays one word, read literally (the user's lean, 2026-09-28): a one-letter "
        "piece is not counted as neutral, which would also split names and titles spelled with one (デュラララ, コラヴァ). "
        "Refined 2026-09-30 (lane N4, the second audit's name problems — JA-AUD-010, JA-AUD-012): (1) a run a headword "
        "spells is the dictionary word it spells — the compound and affix joins make it one where their tables hold "
        "it; where they don't (too rare for their gate: ブシン, JPDB 2024 #132,572), a run with a piece that is no common "
        "word is one word as an unlisted run is (ブ, read as the prefix 無, + シン), keyed the same (no reading); a run "
        "of common words stays in pieces as before, and without the compound table a headword stays as the tagger cuts "
        "it; (2) a run's last piece that heads a word the text goes on writing in hiragana is that word's, not the "
        "name's — two or more hiragana tokens after it, with a piece that is no grammar and not ending on a prefix, "
        "spell a headword with it (サクサク + ジャ + がい + も: ジャガイモ); one token alone never does (トゥーリは → リハ, "
        "ハーフダンさん → ダンサン, ノイトラのお話 → トラノオ stay names). Merged after Ignore names (NAME-WORDS, 2026-09-30): "
        "a listed word made one word by (1) is no name for it — the lists carry it as a word, and it is as often a "
        "word as a name (ハアッ 184, ブシン 72, コスパ, ガチ beside ユキメ 180, カナデ 118, ルキア); counted as names, the switch "
        "would hide 257 more lemmas, 1,485 uses.",
        "Measured 2026-09-27 as two variants (variants_ja_tokens.py; data/variants/katakana_runs_measure.py): "
        "names-katakana, the rule as the user put it (every unlisted run, keyed as UniDic keys an unknown word), and "
        "names-katakana-pieces (a run made only of common listed words — 普通名詞 / な-words of 2+ letters — stays split, "
        "as B leaves a compound the lists don't carry). Suite: names-katakana fixes 8 (the JT-NAMES LIMITs モロナイ, "
        "モーサヤ, コロム, ローゼマイン, アンネローゼ, サテラ, ナイッシュー, ニーファイ) and breaks 1 ordinary-text LOCK (ギガカップ); -pieces fixes 7 "
        "(not ローゼマイン), breaks 0. General text (6,300 lines, 9 corpora): 928 of 6,064 katakana words are cut, 415 of "
        "those listed; names-katakana keeps the other 513 whole — of 100 at random, 50 names, 7 one-word terms, 41 "
        "compounds of listed words (パーキングスペース, クアッドコア, サッカーニュース), 2 junk: 57% right. -pieces keeps 141 whole — of "
        "the same 100 it keeps 36: 29 names, 3 terms, 2 compounds, 2 junk: 89% right, but 21 of the 50 names stay in "
        "pieces (スカイツリー, キャットウーマン, バーナバス). The library: the 2026-09-27 audit's 300 sentences — 16 kept whole, 12 "
        "names, 2 compounds (ギガカップ, マイナスポイント), 2 junk (バッバカ, アアッ); -pieces 9 (7 names). The list's example "
        "sentences: 100 at random of 1,306 kept whole — 51 names, 2 terms, 25 compounds, 22 junk (speech-recognition "
        "garble): 53%; -pieces 47 kept, 74% (35 names, 1 compound, 11 junk). The list's head: names-katakana takes "
        "10 of the top 100 rows out of every example sentence that held them (#2 モーサ, #4 ナイ, #11 モロ, #32 ロゼ, #48 "
        "アンネ, #57 テラ, #93 トル, #98 ラッド, #99 フィン and #24 クロース, header junk), 64 rows in all — about 17 of them real "
        "words whose sentences only had them inside unlisted compounds (ドクター of スーパードクター, ソード, フロンティア); -pieces 6 of "
        "the top 100 (モーサ, ナイ, モロ, アンネ, テラ, ラッド), 36 in all, name pieces only. Lean: -pieces — right 89% of the time "
        "on general text (the rule as put, 57%), it keeps three of the user's four examples (トゥーリ, グリムジョー, モーサヤ) and "
        "most of the list's head, and costs almost no compound; a name spelled only with common loanwords (リムハイ, "
        "ヒラマン, ローゼマイン) stays in pieces, as today. The guards (2026-09-28, variant names-katakana-guarded): on lane "
        "M's labelled rows they take back 4 of the 92 runs -pieces keeps whole — 3 junk (バッバカ, アアッ, コツンコツン) and a "
        "name said twice (ソフィソフィ: its pieces are the name); in the library 98 spellings, 380 uses (laughter and "
        "sounds: フフフフッ 50, アアッ 41, ハハハハッ 31, アッアッ 14, ハッハッハッハ 7). Suite, as built: fixes 9 (7 JT-NAMES LIMITs, トゥーリ, "
        "グリムジョー) and moves 2 LOCKs — ノワキノ (katakana-written grammar, accepted: LIMIT) and プラスアルファー (JPDB 2024 "
        "#60,660 and Jiten #51,598 list プラスアルファ: one word is right, the case's expectation is). The interjection "
        "guard (WP-4, 2026-09-28; variant names-interjection-runs): fixes JA-NAM-901, 902, breaks 0; in general text "
        "(254,114 katakana lines) layer 1 joins 11,636 runs and the guard splits 40 uses of 21 spellings — 20 laughs "
        "and cries (アッハハ, イヒヒヒヒ, ヒーハー, エヘヘヘ), 1 name (アウサア); 204 uses with an interjection piece beside "
        "another piece stay joined — mostly names (マララ, イエレン, フェイリス), a few laughs with a letter piece (about 10 "
        "uses: イヒヒヒ, キャアア, ブワーッ). The 2026-09-30 refinements, measured on the library (debug/parsing_fixes_run/"
        "lanes/N4/debug/n4/layer1_listed_summary.txt, every file read through the token store's tokenizer): (1) joins 292 "
        "listed spellings, 1,635 uses — names and words the tagger shattered into junk (ユキメ 176, カナデ 118, ブシン 71, "
        "ルキア 36, キサマ 37, ノイトラ 31, カッコイイ 19, インフルエンサー 17, ディズニーランド 15, スザク 22) and cries the lists "
        "carry as words (ハアッ 184, ホエ 8); by the piece that isn't a common word: a prefix or suffix 34 spellings / 386 "
        "uses, a letter 84 / 392, grammar 54 / 303, an interjection 11 / 28, another 135 / 526. (2) takes one head in the "
        "library (the audit's ジャがいも): the first draft, any hiragana after the head, took 30 (53 uses) — names before "
        "an honorific or a particle (ガクセイさん → セイサン, ハーフダンさん, ノイトラのお話) — so it needs two tokens and no "
        "prefix at the end. Suite: fixes JA-AUD-012 (ブシン), half of JA-AUD-010; moves JA-AFX-243 (its expectation "
        "assumed the only alternative to the pieces was the join table's word; edited) and JA-KNW-016 (シゲキ, still "
        "wrong: a known シゲキ now also marks the number 四 known).",
        "Every unlisted run: every katakana name the tagger cuts becomes one row (トゥーリ, リムハイ, ヒラマン, ローゼマイン) and "
        "Ignore takes it once instead of its pieces — but a compound of listed words the lists don't carry becomes "
        "one unknown word (41 of 100 kept whole in general text, 25 in the library's): its words lose those uses "
        "(ドクター, ソード) and a learner who knows パーキング and スペース still meets パーキングスペース as new; frequent ones become rows "
        "(コミュニケーションスキル). Only runs with a non-word piece: almost no compound (2 of 36), but names spelled with "
        "common loanwords stay in pieces (21 of 50 names in general text, 16 of 51 in the library's) and their "
        "pieces keep filling rows (ロゼ #32, リム, ハイ). As built: a katakana stammer or repeated sound stays in pieces, "
        "as today; a name said twice (ソフィソフィ) counts as the name twice; katakana-written grammar becomes one unknown "
        "word (ノワキノ); a joined run is keyed as an unknown word (no reading; Junban's 'i+1 first' counts it as a "
        "name). Untouched: a name read as one common word (アウロラ → オーロラ, ロム → ＲＯＭ), hiragana names (さくら → 桜, ひろか → ヒロ "
        "+ か, あっちゃん), a run with kanji in it (ダー子: ダー stays). A names switch flipped while Junban is open applies "
        "after a restart, like the other parsing settings — accepted 2026-09-28 (the user's answer 5; all three "
        "names switches). The interjection guard splits a name whose every piece the tagger reads as an interjection "
        "(アウサア, an old spelling of 'Arthur': LIMIT JA-NAM-802, the one name among the 21 spellings it splits in "
        "general text), and a laugh or cry with a piece read as a letter stays one unknown word (キャアア: LIMIT "
        "JA-NAM-803). As refined 2026-09-30: a listed word the tagger shatters becomes one row keyed as a word no "
        "dictionary has — no reading, though the lists give one (カッコイイ, ブシン); a cry the lists carry (ハアッ, 184 "
        "uses) is one word, no longer counted as the interjection アッ; a word written half in katakana and half in "
        "hiragana (ジャがいも) is kept off a name before it but is still read in pieces (蛇 + 街 + も).",
        "decided", ("Parsing_Fixes_Plan.md §1 decision 9, §2 step 2", "Parsing_Suite_Findings.md §7", "variants_ja_tokens.py names-katakana, names-katakana-pieces", "data/variants/katakana_runs_measure.py, katakana_runs_labels.json", "app/names.py", "variants_ja_tokens.py names-katakana-guarded")),
    Decision(
        "NAMES-RECURRENCE", "2026-09-28",
        "Names layer 2 (the user's idea): a katakana run layer 1 leaves split — made only of common listed words, リム "
        "+ ハイ, ヒラ + マン, ローゼ + マイン — that keeps recurring in the user's own content: make it ONE word, library-wide? "
        "And by which gauge, so that it behaves the same in a small library and a large one?",
        "Yes (the user, 2026-09-28: \"I take all your leans\"), its own switch, logic.names_recurring, default on: a "
        "katakana run NAMES-UNLISTED-KATAKANA leaves in pieces (only common listed words) is ONE word, library-wide, "
        "when its stickiness — of the uses, as a word after layer 1, of its least-used piece, the share inside this "
        "run — is at least T and it has 3+ uses in the library; a run already joined stays joined until its "
        "stickiness falls below 0.5 (the flip guard). T = 0.7 (the user's tie rule: measured with the flip guard, "
        "0.7 over 0.8 is about even). Built as a library-wide table: each file's candidate runs recorded in the "
        "token store at index time, the table computed after indexing and stored there, applied by "
        "analyzer.join_affixes and the store's cached tokens for every caller; never in the cache's build signature "
        "(its switch is in the run signature: flipping it needs only a Generate); never in shared data (the パターン "
        "builder and the reference-data build run without it). T = 0.7 kept: confirmed by the user 2026-09-28 "
        "(answer 4).",
        "Measured 2026-09-28 (data/variants/names_layers_scan.py, names_recurrence_measure.py; variant "
        "names-recurrence = layer 1 + a frozen table of the library's joins). The library (the 1,987 files the token "
        "store lists, 4.31 M words, 39 works) holds 1,289 such runs (3,961 uses); the 169 with 3+ uses were "
        "hand-labelled: 62 names, 10 one-word terms, 85 compounds, 12 junk. Raw count >= 50 (the first cut) is right "
        "on lane M's 60 rows (10 of its 23 misses, 0 compounds) but 58% on the 169: page chrome (サイトマップフィードバック 138 "
        "uses) and a story's own terms (クラスポイント 53, キーカード 38) recur as much as names. Uses per million words, uses "
        "within one work and within one file are no better (<= 66%) and don't scale: a raw or per-work count loses "
        "names as the library shrinks (a tenth of the files keeps 29-40% of its joins), per million explodes (a "
        "tenth joins 186 runs, 160 that the whole library doesn't). Best: stickiness — of the uses, as a word, of "
        "the run's least-used piece (a piece inside a run layer 1 keeps whole is no use of it: ローゼ in アンネローゼ), the "
        "share inside this run. At >= 0.8 with 3+ uses it joins 49 runs, 40 right (82%; 79% of uses — 85% and 96% of "
        "uses without 2 page-chrome runs), rescues 12 of lane M's 23 misses with 0 compounds glued, and scales: of "
        "the runs with 3 uses in a part (a tier, a half, a quarter, a tenth, one work), 93-100% get the same call. "
        "Built up one work at a time (5 random orders) it flips ~0.4 times per joined run, half of those corrections "
        "(a compound that looked sticky early). The same ratio within one work only is the most stable (0 un-joins) "
        "but 61% right: inside one story its terms look sticky. Suite: layer 1 fixes 9 and breaks 4 LOCKs (バッバカ, "
        "ノワキノ, ブンブンブンブン, プラスアルファー); layers 1 + 2 fix 14 (+ ローゼマイン, リムハイ, ヒラマン, ギルベルタ, シャドウガーデン), break the same 4. "
        "Lean: build it, its own toggle, default on — stickiness >= 0.8, 3 uses; a library-wide step after the "
        "per-file tokens, never a signature of the token cache. Built 2026-09-28 at T = 0.7 (stickw, floor 3, flip "
        "guard 0.5). The flip guard, measured with the growth simulation (5 random orders of the 39 works, "
        "names_flip_guard_measure.py): T 0.7 — without it 0.41 flips per joined run, 60 joined at the end (46 right, "
        "14 wrong, 77%; uses 1,273 / 351); with it 0.20 flips, 70.4 joined (51.0 right, 19.4 wrong, 72%; uses 1,318 "
        "/ 386) — the ~10 extra are runs joined earlier that the guard keeps. T 0.8 — without 0.42 flips, 49 (40 / "
        "9, 82%); with 0.16 flips, 60 (46.8 / 13.2, 78%; uses 1,302 / 355). 0.7 over 0.8, both guarded: +4.2 right "
        "(サンボマスター, ヒートテック, スネークマンショー, カモシカコンビ, ライジングエアライン, シーレム, サムウェア, サードマン) and +6.2 wrong (アンバランスパワー, "
        "ペアレントトレーニング, ヴァンパイアハンター, ジャンピングチャンス, ゴールデンエイジ, ボーナスポイント, ダークブラウン, ゴールデンウィー, ローソー) — about even, so the "
        "user's tie rule keeps 0.7. The built table, the whole library indexed at once through the app's own code "
        "(data/names/library_names.py): 65 runs — 38 names, 7 one-word terms, 10 compounds, 4 junk (page chrome), 6 "
        "unlabelled (names by the look: クールホーン, アビラマ, ドンドチャッカ). Suite: fixes ローゼマイン, リムハイ, ヒラマン, ギルベルタ, シャドウガーデン, "
        "トルフィン, モードレッド; ククリナイフ and テリヤキバーガー join (accepted); パンプル (1 use) stays in pieces.",
        "On: 40 names and terms become one row (ヒラマン 347 uses, シャドウガーデン 182, トルフィン 122, リンシャン 100, ギルベルタ 93) and "
        "layer 1's two readings of one name agree (it reads 15 names both ways: ギルベルタ whole in 62 uses, in pieces in "
        "31); トル #93 and フィン #99 leave the list's top 100 (17 rows in all). But 6 compounds whose rarer word appears "
        "nowhere else (ククリナイフ, テリヤキバーガー, エナジーフィラー, ツノナシ, ピロービジネス, リニアカノン) and 3 junk runs become unknown words; a "
        "word's parse depends on the user's whole library, not on Japanese (the one rule that does — WORD-IDENTITY's "
        "exception, the user's own idea); a run can flip as works are added, and every consumer must apply the same "
        "library table. Off: 23 of the misses stay in pieces (リムハイ, ヒラマン, ローゼマイン) and their pieces keep filling "
        "rows. As built (T 0.7): the compounds it glues — ククリナイフ, テリヤキバーガー, エナジーフィラー, ツノナシ, ピロービジネス, リニアカノン, "
        "ペアレントトレーニング, ドリームキラー, ジャンピングチャンス, ゴールデンエイジ — and page chrome (サイトマップフィードバック, マイアカウント, プラザゴイ, ゴールデンウィー) "
        "become unknown words; a name used fewer than 3 times (パンプル) or whose rarer piece is common alone (ジャガノート, "
        "タコピー) stays in pieces. The flip guard makes the table depend on the order the library grew in (about 10 of "
        "70 runs), in exchange for half the flips. The word-selection preview (Settings) counts the library before "
        "these tables (the token store's running totals).",
        "decided", ("data/variants/names_recurrence_measure.py, names_recurrence_labels.json, names_recurrence.json", "variants_ja_tokens.py names-recurrence", "debug/parsing_fixes_run/names_review/nm/", "app/names.py", "data/variants/names_flip_guard_measure.py", "data/names/library_names.py, library_tables.json")),
    Decision(
        "NAMES-KANJI", "2026-09-28",
        "Names layer 3: a run of 2-5 tokens UniDic cuts (一 + 護, 玖 + 渚, 赤 + 音, 巫 + 女子) whose whole spelling is a "
        "person's name in anki_miner's JMnedict wordsets (surnames, given names): make it ONE word — and with which "
        "guards, since JMnedict's long tail spells many chance meetings of two words?",
        "Yes (the user, 2026-09-28: \"I take all your leans\"), its own switch, logic.names_kanji, default on: the "
        "guarded rule as measured (a run of 2-5 tokens, 8 characters at most, with a kanji, spelling a person's name "
        "in JMnedict — surnames, given names — and no JPDB 2024 headword; not when a piece is grammar, a number "
        "without a person's name, after a number, a person's name + a suffix, a plural suffix last, or a surname + a "
        "given name whose whole is no listed surname), plus a floor of 3 uses in the library, which drops most "
        "one-off chance meetings. Built as a library-wide table like NAMES-RECURRENCE (the same store, the same "
        "callers, never in shared data). The name table (CC BY-SA 4.0, EDRDG) ships in its own generated module, "
        "app/name_data.py. 今頭 (a chance meeting the transcripts repeat 7 times) accepted as a known wrong — the "
        "user, 2026-09-28 (answer 3; JA-CMP-017, LIMIT).",
        "Measured 2026-09-28 (variant names-kanji, data/variants/name_spellings.json, names_kanji_measure.py). The "
        "rule: the longest such run from the left, 8 characters at most, with a kanji — unless the spelling is also "
        "a JPDB 2024 headword (JMdict's: 冬月 トウゲツ, 伊吹, 一葉), a piece is grammar (上の, 流され, な子) or the run starts with a "
        "suffix / ends with a prefix, a piece is a number and none a person's name (四年, 三十一, 栄 + 二丁目) or the run "
        "follows a number (１０ + 円玉), a person's name UniDic reads is followed by a suffix (マリア + 様, 司 + 氏, 寅 + さん) "
        "or a plural suffix ends it (お光 + 達), or UniDic reads a surname + a given name and the whole is no listed "
        "surname (宮崎 + 駿; 司 + 波 is the surname 司波). The guards take 596 of the 859 runs the bare lists would join in "
        "the library. Library: 267 runs, 4,807 uses (一護 1,022, 玖渚 680, 巫女子 660, 赤音 332, 望実 222, 真姫 211); 50 random "
        "uses: 45 right (90%); 50 random spellings: 21 right (42%) — most wrong ones are one-off chance meetings in "
        "speech-recognition transcripts (今頭, 後町, 塔雨), 4 partial names (有昭 of 有昭田, 神館 of 存神館, 比古 of 幹比古) and 霊子 "
        "(Bleach's term, 99 uses). General text (6,300 lines): 105 runs, 91 right (87%), 9 two-noun coincidences "
        "(奥隅, 河淵, 新枝, 市花), 5 partial. The 2026-09-27 audit: fixes 一護 and 赤音 (and the canary 雪緒), misses 狛村 (not "
        "listed), 一葉 (also a word), 崩玉, 藍染 (one token). Suite: fixes JA-NAM-006 一護; breaks 12 LOCKs — 3 on purpose "
        "(玖渚, 金家, 京楽 are names), 3 partial names (元柳, 有昭, 神館), 6 chance meetings (霊子 twice, 今頭, 今手, 今女, 円玉). A "
        "library gate doesn't fit kanji: layer 2's stickiness refuses real names (夜一 0.05, 数一 0.01 — kanji pieces "
        "are common alone); a floor of 3 library uses would lift the spellings to ~80% (a chance meeting rarely "
        "recurs) at the price of layer 2's library step. Lean: build it, dictionary-only with these guards, its own "
        "toggle, default on. Built 2026-09-28 with the floor (data/names/library_names.py: the library through the "
        "app's own code): of the 263 names the guarded rule reads, 70 have 3+ uses (4,559 of 4,794 uses). They keep "
        "一護, 玖渚, 巫女子, 赤音, 望実, 真姫 and 司波 and drop 今手, 今女, 円玉, 奥隅, 河淵 (0-1 uses); 今頭 stays (7 uses — a chance meeting "
        "the transcripts repeat). The 70, labelled: 49 names, 5 one-unit words that are no names (忌子, 村中, 杉苗, 礼義, "
        "陽日), 16 wrong — 11 cut short — partial names, places and terms (元柳, 秀知, 比古, 左衛門, 根島, 有昭, 神館, 駒宮, 義魂, 空羅, "
        "聖見) — and 霊子, 今頭, 会馬, 話心, 大狼; by uses 94% right (the 16 hold 291 of 4,559). On lane NM's 50 random "
        "spellings (which NM counted 21 right, 42%; relabelled here, 21 right too) the floor keeps 11 — 7 right (司波, "
        "冬雪, 数一, おニャン子, 祐弥, 麻理亜, しず子), 4 wrong (有昭, 神館, 霊子, 忌子): 64%; it drops 14 real names used once or twice (勇音, "
        "伏川, 鳥嶋, 哲五郎, 紗代, 菜々美, 橋彌, 花音, 創介, 歌田, 橋垣, 珊珊, 瀬戸内, 影崎). Suite: fixes 一護, 赤音, 巫女子, 望実, 雪緒, 司波; 玖渚 and 京楽 are "
        "names (expectations edited); 霊子 (twice), 元柳, 有昭, 神館 and 今頭 accepted.",
        "On: kanji names UniDic cuts become one row, and common words stop counting name pieces — 女子 602 uses, 音 "
        "344, 赤 332, 渚 (the row ナギサ, #36, 578 uses, all from 玖渚); the joined name is keyed as a word the dictionary "
        "lacks (no reading). But about 1 use in 10 in the library is a chance meeting made a name (今頭 in 今頭の中で), 霊子 "
        "becomes a name, a partial name becomes a row (元柳 of 元柳斎); a name that is also a dictionary word (冬月, 伊吹, "
        "一葉) stays in pieces, as does one JMnedict lacks (狛村). Off: as today (JT-NAMES) — the pieces count as their "
        "common words (一 read ハジメ, 護 マモル). Untouched, as before: a name the tagger reads as one common word (茶柱 'tea "
        "stalk', 静か), a kanji it reads alone as a given name where no listed name spans the run (探 モトム in 探窟家), a "
        "named thing that is no person (灰猫, a sword's name). As built with the floor: a real name used once or twice "
        "stays in pieces (about 14 of 50 random spellings); a chance meeting the library repeats 3+ times joins (今頭, "
        "会馬, 話心 — transcripts); a partial name the library repeats joins (元柳 of 元柳斎, 有昭 of 有昭田, 秀知 of 秀知院, 比古 of "
        "幹比古); a series' term that is also a name joins (霊子, 義魂, 空羅); a name JMnedict lacks stays in pieces (枢木, "
        "狛村).",
        "decided", ("data/variants/name_spellings.py, names_kanji_measure.py, names_list_head.py", "variants_ja_tokens.py names-kanji, names-katakana-kanji, names-all", "debug/parsing_fixes_run/names_review/nm/", "app/names.py", "app/name_data.py", "data/names/library_names.py, library_tables.json")),
    Decision(
        "NAMES-WORK-TERMS", "2026-09-29",
        "Names layer 4: a run of 2+ tokens UniDic reads as one kanji each (斬 + 魄 + 刀, 霊 + 圧, 卍 + 解, 零 + 崎, 崩 + 玉) that "
        "the compound build and names layers 1-3 leave in pieces — a work's own term, or a name JMnedict lacks or layer 3 "
        "refuses: make it ONE word when the library keeps using it as one?",
        "Yes (the user, 2026-09-29: \"start working on 2a-2c\", taking every lean of the trial report's §1): its own switch, "
        "logic.names_work_terms, default on; layer 2's gauge and numbers — stickiness (the run's uses over the lone uses of "
        "its least-used kanji, those inside the layer-3 names of the same runs taken out) >= 0.7 with 3+ uses, and a joined "
        "term stays while >= 0.5; a number may sit inside a term (護廷十三隊, 零崎); uses in a transcript whose header says "
        "its captions are auto-generated (native auto, auto-translated) count toward nothing — the join still applies there; "
        "guards: no grammar piece (a particle, verb, adjective, pronoun, 連体詞 …) and no 君 様 殿 氏 達 等 共 方 内 中 外 上 下 前 "
        "後 間 last, and no JMdict word (its kanji forms written in Han alone, shipped as spellings in app/name_data.py). "
        "Built as a library-wide table beside NAMES-RECURRENCE and NAMES-KANJI — the same store, the same callers, never in "
        "shared data (library=False) — applied after layers 2-3 on what they leave, never overlapping; keyed as layer 3 keys "
        "a name (the spelling, no reading). Also, at no cost on the measured set: never a spelling of the affix or compound "
        "tables (the compound build's, Japanese-wide — so the phrases switch is never undone), never a layer-3 name, never a "
        "run of numbers alone (NUMERALS-NOT-WORDS). As built 2026-09-30 (lane N4): the grammar guard with real parts of "
        "speech lets a name's linking 之 through inside a run, as layer 3's does (星之宮: JA-NAM-413), and reads a run's "
        "shape as the tagger reads it in most of its uses; JMdict's kanji spellings ship entry by entry in "
        "app/jmdict_data.py (not name_data.py: a card reader can load them without the person names) — the guard "
        "reads them only for the spellings that reach it and keeps only its answers (45 ms; the module's text in "
        "memory).",
        "Measured 2026-09-29 (debug/parsing_fixes_run/work_terms/: a read-only scan of the token store, re-cut the way the "
        "compound build and layer 3 would reach it — both approximated — and 254 hand labels). Of 5,368 runs of one-kanji "
        "pieces, 1,329 with 3+ uses: 39 are layer-3 names, 23 compound-build words, and 1,240 (20,930 uses) the pool — "
        "mostly counts (第三, 一度, 何度), whose counters are everyday words, so their stickiness is low. At 0.7 / 3 uses "
        "with the three guards: 67 new words, 3,318 uses — 37 work terms and 21 names right (87%; 97% by uses), 3 old "
        "spellings the lists lack (源因, 即坐, 孤獨), 5 partial terms (疋殺, 売教, 弧雀, 調戯, 尽敵), 1 ordinal (第一刷); no chance "
        "meeting, no auto-caption error. Without the guards: 86, 71%. Wider (0.5): 102, 76%. The guards: auto captions "
        "drop 17 caption errors (水薦 for 推薦, 共容 for 教養) that repeat, so look sticky; JMdict drops the 8 real words the "
        "compound tables should own (一発, 十二支, 起承転結, 鄭寧) and costs nothing — the frequency lists as a guard would cost "
        "6 names (勇音, 空吾: Jiten carries anime names); refusing numbers would cost 7 right joins for 1 wrong. Below 0.5 "
        "counts return (a random 40: 5 terms, 23 counts). 42 of the 67 are Bleach's (斬魄刀 550, 霊圧 494, 卍解 198). "
        "Suite: fixes JA-NUM-038 崩玉; JA-ORD-209 (霊圧) is one word on purpose. The real table (2026-09-30, lane N4: the "
        "library through the app's own code, data/names/library_names.py; auto captions read from the transcripts' "
        "headers — peko peko vlog and AI文明論 are manual captions, 7 transcripts in HighPriority auto): 78 terms, 3,370 "
        "uses — 45 work terms and 20 names right (83%; 95% by uses: 3,202), 8 partial (疋殺, 桜景厳, 王属, 鳳橋楼, 売教, 弧雀, "
        "調戯, 尽敵), 4 rare words (源因, 即坐, 孤獨, 蛙化), 1 ordinal (第一刷); new beside the trial's 67: 一蘭 and 蛙化 (manual "
        "captions), 白漣, 双蓮蒼火墜, 蒼火墜, 神殺鎗, 五柱鉄貫, 弐撃決殺, 聖任, 羅武, 宮商; gone: 白哉 (哉 read as grammar: "
        "JA-NAM-412), 玖渚友 (layer 3 takes 玖渚), 久南白 (長久 is one token). Suite: fixes JA-NUM-038, JA-NAM-401, 402, "
        "403, 410, 411; JA-ORD-209 edited; JA-NAM-408 (疋殺) joins as accepted; nothing else moves.",
        "On: a work's own kanji terms become rows (斬魄刀, 霊圧, 卍解, 虚閃, 崩玉) and names layer 3 misses join (零崎 — a "
        "number, 白哉, 狛村); a sentence counts the term as one unknown, not 2-3 kanji; the kanji lose those uses (魄 97%, 圧 "
        "96%, 斬 89%) — no list row, as single kanji are never listed. But the library, not Japanese, decides these words "
        "(WORD-IDENTITY's exception, extended by the user from names to a work's terms); 3 real words the lists lack join on "
        "the library's say-so (源因, 即坐, 孤獨); a term's edges can't be seen, so a partial term joins (疋殺 of 金色疋殺地蔵, "
        "like layer 3's 元柳); a term can flip as works are added (the flip guard halves it); the rows have no reading. About "
        "half of a work's frequent terms stay in pieces — their rarest kanji is also an everyday word (十刃 208, 恋次 152, "
        "空座町 125) — and a term inside a longer run is counted as that run. Terms met only in auto-caption talk (一蘭, 徐倫, "
        "蛙化) stay in pieces. A word JMdict lists stays as the compound build leaves it (鄭寧 in pieces: in no frequency "
        "list). Off: today's parse, and no re-reading of files (the table is applied as the cache is read). As built: a "
        "name or term whose kanji the tagger reads as grammar stays in pieces (白哉, 106 uses: 哉 read as the classical "
        "かな — LIMIT JA-NAM-412).",
        "decided", ("debug/parsing_fixes_run/work_terms/REPORT.md, scan.py, analyze.py, measure.py, labels.tsv, "
                    "proposed.json", "Names_Work_Terms_Spec.md", "variants_ja_tokens.py names-work-terms, "
                    "names-work-terms-off", "data/variants/work_terms.json", "app/names.py", "app/name_data.py",
                    "data/names/library_names.py, library_tables.json")),
    Decision(
        "JT-PLACE-BASE", "2026-09-28",
        "Compounds whose first part is a place name (日本語, 中国語, 鳥取県, 日本語教師, 伊勢海老, 東京タワー): let B take a place name as "
        "a part, as 2.3's _is_base already does for suffixes (日本人)?",
        "Yes (the user, 2026-09-28: \"I do want all 6 the way your yes leans\"): B takes a place name as a compound "
        "part — any noun analyzer._is_base accepts, a 固有名詞 that is no person's name — as Part A already does for "
        "suffixes (日本人), gated like any B join (the even-odds gate, CJ-3): 日本語, 中国語, 鳥取県, 東京タワー, フジテレビ are one word "
        "each. A spelling that is no gated headword (in both JPDB 2024 and Jiten, or in one list's top 60,000) never "
        "joins: 伊勢海老 (JMdict lists it; JPDB 2024 #78,021 only, not Jiten) stays 伊勢 + 海老, and 日本語教師 (in no "
        "dictionary) is 日本語 + 教師. Compound_Build_Spec.md §2.3.",
        "B as first measured joined plain nouns only (no 固有名詞): 2,491 gated headwords were out, 167 met in the "
        "library (1,177 uses), 12 at the cut-off — 日本語 554, 鳥取県 71, フジテレビ 50, 中国語 38 (CJM §2, places.py); the "
        "adversary: 日本語 is 'the learner's most basic word' and was never listed (語 is one character). The "
        "dictionaries list these words and Part A already takes a place as a base. Measured for the spec "
        "(2026-09-28, the gated pool read alone by today's tokenizer): +3,099 candidates with a place part (日本語, "
        "東京都, 江戸時代, 神奈川県; and UniDic 地名 quirks that are words anyway: 八方塞がり, 大和撫子); parts filed 固有名詞・一般 are the "
        "lane's to count and read. Re-filed 2026-09-28: 5 DISPUTED cases TARGET, 伊勢海老 LIMIT, 日本語教師 TARGET with its "
        "expectation corrected (checked 2026-09-28: not in JPDB 2024, Jiten or JMdict — two words, 日本語 + 教師).",
        "Landmarks, companies and other proper nouns the lists carry join as common words (東京タワー, フジテレビ) — Ignore "
        "takes them; a place compound outside the gate stays in pieces (伊勢海老 → 伊勢 + 海老: LIMIT JA-CMP-228).",
        "decided", ("Compound_Build_Spec.md §2.3", "Parsing_Fixes_Plan.md §1 (ratified 2026-09-28)", "Compound_Join_Measurement.md §2", "debug/parsing_suite/ja_tokens B30-B32", "debug/parsing_suite/known CJ-6")),
    Decision(
        "JT-NUMERAL-WORDS", "2026-09-28",
        "Words and idioms that hold a numeral (一石二鳥, 三日坊主, 一日中, 二十歳 はたち, 二枚目, 精一杯, 二酸化炭素, 五つ子): nothing joins "
        "through or after a 数詞 today — let a headword whose numeral counts nothing join?",
        "Yes — the not-a-count test (the user, 2026-09-28: \"I do want all 6 the way your yes leans\"; N3, fixed "
        "counts, approved the same day — the user's answers to the step-3 questions, 2026-09-28: \"I take all leans "
        "as accurate\", answer 6). A gated headword of 4 tokens or fewer holding a 数詞 — every other token a compound "
        "part or a noun suffix (接尾辞・名詞的: 歳, 日, 枚, つ, 目, 中), never ending in a bare number, and starting at the first "
        "numeral of its run — joins, before the numeral is dropped (NUMERALS-NOT-WORDS), when its numeral is no "
        "count: N1, inside — a numeral after a non-numeral token of the word (精一杯 read 精 + 一 + 杯, 力一杯, 十人十色, 一つ一つ, "
        "世界一周); N2, not read as a count — no reading the lists give the spelling reads its counter the way the "
        "lists' other counts read that counter, up to voicing (二十歳 ハタチ: 歳 is サイ in 十歳, 一歳; 十八番 オハコ: 番 is バン), and a "
        "spelling the lists also read as a count stays apart (五分 ゴフン, 一日 イチニチ) — UniDic's per-token kana is never "
        "the yardstick; N4, no counter — the token after the numeral is no counter at all (一 + 大事, 一 + 時期); N3, a "
        "fixed count — a count built into a longer word whose frame the lists carry with no other number (一日中: no "
        "二日中; 一年中, 三日坊主, 三日月, 二酸化炭素, 三半規管, 一軒家, 二度寝). Otherwise a count, apart: 三日, 二日, 四月, 一匹, 三階, 九時, 十円玉 (百円玉), "
        "三年生 (一年生), 一年前 (百年前). A counter is a noun the lists carry right after two or more different numbers (the "
        "build's COUNTERS table) or one UniDic files as 助数詞 / 助数詞可能. The same test is B's number guard: a compound "
        "right after a 数詞 joins only when that number counts nothing in it (何 + 得意気 joins; １０ + 円玉 doesn't). Built "
        "as a variant first, N3 measured beside the literal test (Compound_Build_Spec.md §2.5). And N2 checked against "
        "JMdict (2026-09-29, the user took the leans — step-3 question 10(b)): a word the lists read as no count joins only "
        "where JMdict agrees — it goes apart when JMdict lists the spelling read as a count as a word of its own (一期 "
        "いっき 'one term'), or reads the word itself as a count too and marks neither the spelling nor the list's reading "
        "common (三位 さんい 'third place'), or says the word is usually written in kana and doesn't mark it common (七節 "
        "ナナフシ: the kanji spell the count); an archaic entry reads nothing (二十歳 はたとせ). A priority tag (ichi, news, "
        "spec, gai, nf) is JMdict's common mark: 二十歳 はたち and 十八番 keep joining. Guard LOCKs JA-NUM-910 to 912 (三位, "
        "一期, 七節).",
        "The number guard (AFFIX-GUARDS) keeps counts from becoming words (3年生, 三回目, 十円玉) and B inherited it, so "
        "numeral idioms never joined — B's blind spot the adversary found (M19-M26); it also fired where nothing "
        "counts (何 'what' is tagged 数詞: 何得意気). Since F6 (NUMERALS-NOT-WORDS) the numeral itself is no word, so an "
        "idiom counted as its other pieces (一石二鳥 → 石 + 二鳥). UniDic's counter class misses counters (人, 冊, 軒 after a "
        "numeral are 接尾辞・名詞的・一般), its kana misses counting phonology (一匹 イチ + ヒキ; the lists read イッピキ), and the "
        "lists read one spelling two ways where it is a count and a word (五分 ゴブ #4,443 and ゴフン #91,210; 一日 イチニチ and "
        "ツイタチ) — hence the lists as the yardstick. A scratch sketch for the spec (2026-09-28, not the lane's "
        "measurement): 2,460 numeral headwords in the gated pool — N1 232, N2 166, N3 390, N4 539, counts 1,133; "
        "misfires the lane must fix: single-number counts the lists carry only with 一 read as N4 (一片, 一拍, 一票, 一勝), "
        "counts a naive tail match calls special (数日間, 五十人, 九本). The lane hand-labels 50 joins and 50 aparts per "
        "clause and brings the classes to the user if joins are under 90% not-counts. Re-filed 2026-09-28: 14 "
        "DISPUTED cases TARGET (N1 / N2 / N4 and the guard: 二十歳, 十八番, 十人十色, 一石二鳥, 一期一会, 精一杯, 力一杯, 得意気; N3: 一日中, 一年中, "
        "三日坊主, 三日月, 二酸化炭素, 三半規管), 4 LIMIT (四六時中, 二枚目, 五つ子, ５つ子); guard LOCKs JA-NUM-901 to 907 (二日, 五分, 一匹, 四月, 三階, "
        "三年生, 一年前) beside JA-CMP-223 (十円玉). The JMdict check as built (2026-09-29; measured by hand labels first, "
        "2026-09-28): 11 of the 58 words the lists read as no count go apart — 一期, 三位, 六体, 二七日, 七節, 八町, 五形, 二形, "
        "八十日目, し所, 三七日 — 9 of 11 rightly; right joins among the no-count words 71% → 83%; the numeral words 1,268 → 1,257. "
        "The suite held none of the moved words; the \"inside\" misfires (週一回, 下二桁 join) are untouched.",
        "A fixed count that is still a count joins under N3 (一回戦 'first round', 二度目 'second time'; 数年後 'a few "
        "years later', whose 数 counts, is one word — LIMIT JA-AFX-233), and "
        "single-number counts the lists carry only with 一 join under N4 (一票, 一勝); a word whose frame takes another "
        "number stays apart though it is one word — 四六時中 (二六時中 is a word too), 二枚目 'handsome man' (三枚目), 五つ子 (三つ子): "
        "LIMIT; a spelling that is both a count and a word stays a count (五分 ごぶ, 一日 ついたち); a listed count (二日 フツカ, "
        "四月 シガツ, 一匹 イッピキ) stays numeral + counter, the numeral uncounted. With the JMdict check, a word the lists "
        "read as no count whose spelling JMdict also reads as a count goes apart everywhere, its rarer sense too: 一期 "
        "'lifetime' written alone, 三位 'the Trinity' alone (一期一会 and 三位一体 still join: their numerals sit inside).",
        "decided", ("Compound_Build_Spec.md §2.5, §11 Q1", "Parsing_Fixes_Plan.md §1 (ratified 2026-09-28; step-3 answer 6)", "debug/parsing_suite/ja_tokens M11, M19-M26, A60-A61", "debug/parsing_suite/known CJ-9, RL-44")),
    Decision(
        "JT-NA-ADJ", "2026-09-28",
        "Noun + な-adjective compounds (一生懸命 = 一生 + 懸命, 前途多難 = 前途 + 多難): B joins plain nouns only — take a 形状詞 part "
        "too?",
        "Yes (the user, 2026-09-28: \"I do want all 6 the way your yes leans\"): a な-word (形状詞) of subclass 一般 or タリ "
        "is a compound part, gated like any B join — never 形状詞・助動詞語幹 (みたい, そう: grammar — バカみたい stays バカ + みたい). The "
        "joined word takes its last part's class: 一生懸命 (懸命 is a な-word) is a な-word (一生懸命に, 一生懸命な), 前途多難 too, 自信満々 / "
        "意気揚々 / 興味津々 (タリ) likewise; 好き放題, 特別扱い (a な-word first) are nouns. Compound_Build_Spec.md §2.4.",
        "一生懸命 is JPDB #2,435 and one word in every dictionary; UniDic files 懸命 / 多難 as 形状詞, so neither Part A nor B "
        "joined them (the adversary: B's second blind spot). Measured for the spec (2026-09-28): +1,381 candidates "
        "with a な-word part in the gated pool (一生懸命, 自信満々, 興味津々, 好き放題 — and バカみたい, whose みたい is 形状詞・助動詞語幹, grammar: "
        "left out). Re-filed 2026-09-28: both DISPUTED cases TARGET; guard LOCK JA-CMP-901 (バカみたい).",
        "More joins to gate; the list shows 一生懸命 where it showed 一生 and 懸命 (the golden's 前途 / 多難 rows become 前途多難); "
        "grammar that looks like a な-word (みたい, そう) never makes a compound.",
        "decided", ("Compound_Build_Spec.md §2.4", "Parsing_Fixes_Plan.md §1 (ratified 2026-09-28)", "debug/parsing_suite/ja_tokens M28", "debug/parsing_suite/known GD-1")),
    Decision(
        "JT-B-FRINGE", "2026-09-28",
        "B joins every gated headword read as plain nouns — phrase patterns the lists carry (予想通り, こと自体, 予想以上), "
        "titles (もののけ姫, 人間失格, スターウォーズ), 元 + a noun (元首相), an adverb + its verb-noun (再度確認, 絶対必要). Keep them joined, "
        "or refuse some shapes?",
        "Keep them joined, behind a Settings switch the user asked for (the user, 2026-09-28: \"I do want all 6 the "
        "way your yes leans\"): \"Phrases and titles as one word\" (logic.phrases_and_titles), default on (\"personally "
        "I want them connected\"). On: every gated compound joins as B was measured; off: the fringe stays in its "
        "parts. Its tooltip, the user's text: \"On: 予想通り, こと自体, 元首相 and もののけ姫 each count as one word. Off: they count "
        "as their parts (予想 + 通り).\" Which entries are fringe is decided by JMdict, a flag per table entry set at "
        "build time (the switch filters at run time) — as built (WP-5, scripts/jmdict_flags.py, 2026-09-28): never a "
        "loanword (a katakana-only spelling — スターウォーズ stays one word with the switch off) and never a compound "
        "verb; otherwise a TITLE (every sense at the list's reading names a work, product, company or organization: "
        "もののけ姫, 人間失格, 仮面ライダー), a PHRASE (JMdict lists it, never as a noun, and every sense is phrase-like — "
        "expression, adverb, interjection, の / な modifier, none marked idiom / yoji / onomatopoeia: 予想通り, こと自体, "
        "毎日毎日, 文句なし) or a PREFIX + WORD (the first part's first JMdict sense a prefix, not a noun — 元 'former', 同, "
        "旧, 前 — and the whole read as its parts: 元首相, not 仮初め). The tooltip's four are the acceptance set (4 of 4). "
        "No adverb + する-noun exception (decided 2026-09-28, the user's lean): JMdict lists 再度確認 as a noun "
        "('reconfirmation; double check') and no JMdict test separates the shape, so 再度確認 joins like any gated "
        "compound. JMdict: docs/assets/reference_lists/JMdict_e.gz (EDRDG, CC BY-SA 4.0, created 2026-09-28), read only "
        "by the build. Compound_Build_Spec.md §2.12, §4.",
        "The measurement accepted them (CJM §4: 21 phrase-pattern rows, 'right, but phrases', half score under "
        "(iii); names and titles: 'Ignore covers it'); the adversary disputed them (予想通り is a pattern, a title is a "
        "name, 再度確認 an adverb + its verb-noun that パターン already shows as a pairing). Measured for the spec: the "
        "UniDic shape 'adverbial noun + verbal noun' covers 127 table spellings, 34 met in the library (about 165 "
        "uses) — 再度確認 (3) but also 日常生活 (30), 後始末 (18), 冬支度 (44), 日常会話 (14), 一時停止, 瞬間移動, 単身赴任, real words; no "
        "in-repo list separates phrases from compounds (BCCWJ's units include 再度確認; the TMW lists are frequency "
        "lists) — hence JMdict. Checked against JMdict_e (2026-09-28, WP-0, read-only): JMdict lists 再度確認 as a noun "
        "('reconfirmation; double check', no priority tag), and 元首相 (n), 予想通り / 文字通り / 予想以上 / 毎日毎日 (adv), 絶対必要 (n, "
        "adj-na) as words; only こと自体 and 人それぞれ are expressions (exp) alone; the four titles are JMdict `work` "
        "entries (スターウォーズ too, which JMnedict's org set lacks). So 'no entry or only exp' leaves 予想通り, 元首相 and 再度確認 "
        "outside their classes: the lane (WP-5) finds a Japanese-wide criterion that meets the acceptance set, or "
        "brings the confusion table to the user. Re-filed 2026-09-28: 14 DISPUTED cases TARGET (joined, the switch's "
        "default), 再度確認 LOCK (two words, as today). WP-5's confusion tables (2026-09-28, JMdict_e, 218,840 entries): "
        "the fringe — spec literal ('no entry / exp only') 2 of the 4 tooltip words; 'the last part has a suffix sense' "
        "3 of 4, but 22 of 81 never-fringe controls flagged; as built 4 of 4, 13 of 21 phrases, 3 of 9 titles, 0 of 81 "
        "controls — 822 table entries flagged (208 titles, 432 phrases, 182 prefix + word), 129 met in the library. "
        "The exception — the adverb + する-noun shape alone flags 118 words, 117 of them real words it would split "
        "(日常生活, 冬支度, 一時停止); 'no JMdict entry' catches 1 (前処理) and misses 再度確認; 'no する-verb sense' 92 (91 "
        "real), 'no priority tag' 109 (108), 'first part's first sense an adverb, the whole no する-verb' 11 (10: "
        "絶対服従, 逐次通訳, うっかりミス): no JMdict test keeps 再度確認 apart without splitting real words, so the "
        "exception is not built (the user's lean, 2026-09-28) and JA-CMP-039 is re-expected as one word.",
        "On (the default): patterns and titles are list words (half score under (iii) when their parts are known) "
        "and their halves lose those uses (予想, 通り); off: they count as their parts. 再度確認 is one word, like "
        "every adverb + verbal-noun headword the gate passes — パターン no longer shows 再度 + 確認 as a pairing (3 uses "
        "in the library). A loanword title (スターウォーズ, スラムダンク, スレイヤー) stays one word with the switch off; a "
        "phrase JMdict also lists as a noun or with a noun sense (予定通り, 思い通り, 今現在, 自分一人) and a noun phrase (別問題, "
        "別行動, 女子供, お腹いっぱい) are no fringe and stay joined off too; a title with no JMdict name entry (巨神兵) "
        "likewise. The fringe is only as good as the dictionaries' coverage. The switch changes what a run counts: in "
        "the token store's build signature only when off, and in the run signature.",
        "decided", ("Compound_Build_Spec.md §2.12, §4, §11 Q3", "Parsing_Fixes_Plan.md §1 (ratified 2026-09-28; step-3 answer 1)", "Compound_Join_Measurement.md §4", "debug/parsing_suite/ja_tokens B35-B37, B43, B44, B49", "debug/parsing_suite/known CJ-15, CJ-17", "scripts/jmdict_flags.py (WP-5)", "debug/parsing_fixes_run/step3/J_REPORT.md §1-2")),
    Decision(
        "JT-COMPOUND-VERBS", "2026-09-28",
        "Verb + verb compounds UniDic splits (走り出す = 走る + 出す; the kanji 取り掛かる = 取る + 掛かる, while the kana 取りかかる is "
        "one word): join the lexical ones the dictionaries list?",
        "Yes — a gated headword (the user, 2026-09-28: \"I do want all 6 the way your yes leans\"): V1 (連用形, not する) + "
        "V2 spelling a gated headword (V1 as the text writes it + V2's dictionary form: 走り + 出す) is one verb, "
        "conjugating as V2, with the list's reading (ハシリダス). As built (2026-09-29): a verb UniDic reads whole on its own "
        "(取り掛かる, 見える) is never a table entry, even where a sentence cuts it (取り + 掛かっ, み + える) — the entry would "
        "carry the word's own key, and parts invented from the cut (見える = 見る + 得る; 教える = 教える + 得る) would make every "
        "use of the word read as a compound; the build refuses an entry whose key is one of its parts' keys or the key "
        "of a word the tagger reads whole. Syntactic compounds stay two words by grammar: a V2 is syntactic when it takes a verbal "
        "noun + する as V1 (勉強し始める, 説明し続ける — Kageyama's diagnostic: a lexical compound never does), decided by the "
        "CORPUS SHARE (the user's answers to the step-3 questions, 2026-09-28: \"I take all leans as accurate\", "
        "answer 7(b)): the share of a V2's V + V uses in the shared corpus whose V1 is a verbal noun + し; a V2 at or "
        "above the cut is syntactic (始める, 続ける, 終わる / 終える, 過ぎる expected above; 込む, 上げる, 付ける, 回す — and 出す — below). "
        "The cut sits AT the lowest aspect verb's share (終わる 4.20%), not in the middle of the gap below it (2.84%) "
        "(2026-09-29, the user took the leans — step-3 question 11(b)): a V2 in the gap — 掛かる 3.1%, 切れる 3.1%, 忘れる "
        "3.2%, 置く 3.4%, 倒す 3.6%, 返す 3.9% — makes words (斬りかかる, 言い忘れる, 隠し切れる, 置き忘れる, 見つめ返す join; "
        "読み終わる stays two). A verb + verb spelled in kana alone that JMdict lists but never as a verb is no compound "
        "(きおく is 記憶 'memory', which the tagger reads 来 + 置く; くんいく 訓育, read 呉れる + 行く): kanji say which verbs a "
        "spelling holds, kana alone doesn't. The V2 table goes to the user with the scorecard. No coincidence gate (it models two nouns meeting by "
        "chance; the lane reports what it would refuse). Compound_Build_Spec.md §2.6, §11 Q2.",
        "Syntactic compounds (食べ始める, 食べ過ぎる) are two words by grammar (Kageyama 1993); lexical ones are headwords "
        "(走り出す JPDB #3,530, 取り掛かる #13,882). But the lists do carry syntactic compounds (食べ始める JPDB #12,263, 食べ過ぎる "
        "#15,609, 書き始める #22,022, 読み終わる #17,092), so the test must be explicit. UniDic already keeps most lexical V + "
        "V whole (思い出す, 取り出す, 飛び出す, 話し合う, 見直す, 付き合う) and cuts the productive ones (言い出す, 泣き出す, 走り出す, 使いこなす, 食べ始める); "
        "取り掛かる is one token alone and 取り + 掛かる in context. 956 V (連用形) + V candidates in the gated pool. The lists' "
        "own measure — they carry し + V2 for 始める, 続ける, 過ぎる, 終える, 得る, 出す (し出す #33,947), 尽くす … — would keep 343 apart "
        "and join 613, with 出す syntactic (走り出す, 言い出す, 泣き出す apart); the corpus share puts 出す with the lexical V2s: "
        "走り出す joins, 食べ始める stays two. Re-filed 2026-09-28: 走り出す TARGET; guard LOCK JA-VRB-901 (勉強し始める) beside "
        "JA-VRB-007 (食べ始める). The cut at 終わる measured by hand labels first (2026-09-28): it joins 35 more headwords "
        "(掛かる 18, 忘れる 7, 返す 3, 倒す / 置く / 切れる 2, 飛ぶ 1) — 22 lexical, 9 syntactic, 3 both, 1 junk (きおく, now kept "
        "out); those 35 go from 33% to 67% right, all 954 verb + verb headwords from 84.0% to 85.2%. As built: V 519 → 552 "
        "(+34, くんいく out). New LOCKs 2026-09-29: JA-VRB-910 to 912 (斬りかかる, 言い忘れる, 隠し切れる), JA-VRB-913 (読み終わる, "
        "the cut's edge), JA-VRB-914 (the kana guard).",
        "An inceptive 〜出す joins (泣き出す 'burst into tears'), as the dictionaries list it; a V2 near the cut decides "
        "dozens of verbs at once; the few syntactic compounds whose V2 falls under the cut join — with the cut at "
        "終わる a few more (a 〜切れる 'manage to … fully', 〜掛かる 'be about to', 〜忘れる 'forget to' join as one verb). A "
        "kana verb + verb JMdict doesn't list keeps its entry. A verb UniDic keeps "
        "whole alone but a sentence cuts (the kanji 取り掛かる → 取り + 掛かる; the kana 取りかかる stays one word) keeps the cut "
        "there: JA-VRB-002 back to TARGET 2026-09-29 — a repair table without parts is left for later.",
        "decided", ("Compound_Build_Spec.md §2.6, §11 Q2", "Parsing_Fixes_Plan.md §1 (ratified 2026-09-28; step-3 answer 7)", "debug/parsing_suite/ja_tokens V02, V06, V07")),

    # --- decided 2026-09-29 (step 3, lanes KN / KN2): a katakana compound inside a katakana name ---------------------- #
    Decision(
        "KATAKANA-COMPOUND-IN-NAME", "2026-09-29",
        "A katakana run names layer 1 keeps whole on the tagger's pieces (ビル + デ + イング, a letter among them) is "
        "cut by a katakana compound joined first (ビルデ = ビル + デ), and layer 1 then reads two listed words and keeps "
        "them apart: ビルデイング → ビルデ + イング. Let layer 1's whole run win over a katakana compound inside it — never, "
        "always, or only for a compound JMdict doesn't list?",
        "Only for a compound JMdict doesn't list (the user took the lean, 2026-09-29). A compound spelled in katakana "
        "alone that JMdict has as no headword or reading, written with its ・ or without (ビルデ, ローデ, デリア — 1,213 "
        "of the table's 9,076 katakana-only spellings), carries flag 4 in app/dictionary_data.py, set by the data "
        "build (scripts/jmdict_flags.py unlisted); inside a longer katakana run names layer 1 keeps whole on the "
        "tagger's pieces, its pieces go back and layer 1 makes the run one word (ビルデイング, ローデウェイク, "
        "サイケデリア). A compound JMdict lists keeps its join (フジテレビ + アナウンサー, クラウドファンディング + サイト); "
        "so does a flagged one alone, across a space, or among common words layer 1 leaves in pieces. Built in "
        "analyzer.join_affixes (_give_way_to_names: after the compound join, before a compound's affixes and the っ "
        "rule; looked at only on lines where a flagged compound landed), only while logic.names_katakana is on; the "
        "switch's test stays flags & 1 (the flag is never fringe).",
        "Measured 2026-09-29 (lane KN; the lane's debug/kn_scan.py, kn_labels.py): runs layer 1 keeps whole with "
        "compounds off that a katakana-only compound cuts with them on. The user's library (173,177 katakana lines): 8 "
        "uses, 4 spellings, 3 sentences (one copied into three folders, one into two): ビルデイング, ラバンデリア (a café) "
        "wrong; ワンピース + フジテレビ right; ロールプレイング + ゲー (ゲーム split by a space) junk either way. General text "
        "(9 corpora, 2,917,189 katakana lines): 431 uses, 226 spellings — 392 right cuts (213: フジテレビ + アナウンサー 26, "
        "クラウドファンディング + サイト 13, イートイン + スペース 12, アルティメット + ニッパー), 30 wrong (15: ローデウェイク 6, "
        "アビトゥーア 5, バンデシネ 5, サイケデリア, バルデラマ, アデロール — names and loanwords a deep-tail fragment cuts), 9 junk. "
        "Variant katakana-run-before-compound (always): fixes the 30, glues the 392 back into one unknown word each "
        "— 7% right; library 4 fixed, 2 glued. Variant katakana-run-before-unlisted-compound (only a compound JMdict "
        "has as no headword or reading — 1,213 of the table's 9,076 katakana-only spellings: ビルデ, ローデ, バンデ, デリア "
        "yield; フジテレビ, デコメ, イートイン don't): fixes 29 of the 30, glues 19 (12 proper-name compounds: ソルトレイクシティ "
        "+ オリンピック, ランドローバー + グループ; about 8 of them one name anyway, リオグランデバレー); library 4 fixed, 0 "
        "glued. Neither JPDB / Jiten ranks nor the parts table tells the two kinds apart (wrong: ビルデ past #200,000, "
        "デリア #77,521; right: デコメ #139,262, アビーム #255,355); JMdict does. Suite: neither moves any case before lane "
        "KN's six (JA-NAM-930–932 fixed by both; JA-CMP-930, 931 broken by the broad one, JA-CMP-932 by both). Lean: "
        "the JMdict-narrowed rule (the user's tie rule: join when in doubt — a split name floods the list), built with "
        "a table flag — the runtime holds no JMdict: a bit on each katakana-only compound JMdict doesn't list, set by "
        "the data build, read by join_affixes' compound step; not the broad rule.",
        "19 uses of proper-name compounds in general text (12 spellings JMdict doesn't list, as places or brands: "
        "ソルトレイクシティ + オリンピック, ランドローバー + グループ, カンザスシティー + エリア) become one unknown word — about "
        "8 of them one name anyway (リオグランデバレー); the library, none. One of the 30 wrong cuts stays (a compound "
        "JMdict lists). The broad rule's price (392 right cuts glued: フジテレビアナウンサー one unknown, and a learner who "
        "knows フジテレビ and アナウンサー loses both uses) is not paid. The marks follow JMdict: a data build with a newer "
        "JMdict can move them, and a table rebuild needs the SCHEMA / ENGINE bumps (this release's carry it).",
        "decided", ("Compound_Build_Spec.md §2.1", "app/analyzer.py _give_way_to_names",
                    "scripts/jmdict_flags.py unlisted", "variants_ja_tokens.py katakana-run-before-compound, "
                    "katakana-run-before-unlisted-compound", "data/variants/katakana_compounds_jmdict.py")),

    # --- decided 2026-09-30 (the 出来損ない report; lane IT): headwords read where the text writes them ---------------- #
    Decision(
        "IN-TEXT-COMPOUNDS", "2026-09-30",
        "The compound build reads each JPDB 2024 / Jiten headword ALONE, so a word the tagger reads otherwise alone "
        "is never keyed where a sentence writes it as nouns (出来損ない: 出来る + 損なう alone, 出来 + 損ない in a sentence; "
        "通行止め, 郵便受け, 質問攻め, 並大抵, 四方八方) — the list offers 損ない 'harm' for 出来損ない 'a failure', and a 出来損ない "
        "card is a phrase. Read the reference text too? And where the tagger writes such a word's first part as a "
        "verb's stem (立ち[立つ] + 位置, 待ち[待つ] + 時間, a card's 出来る + 損なう)?",
        "Yes to both (the user took every lean, 2026-09-30 — Q1 and Q2 are the fix). The build reads its reference "
        "text (the shared set's slices and the rest of FORM_SOURCES) with the tables of the headwords read alone; a "
        "headword those tables leave apart that the text writes as a run of 2-3 nouns spelling it is a noun candidate "
        "with its commonest such run's words for parts, through every gate the build has (plurals, the even odds, one "
        "lemma per spelling, a word the tagger reads whole, no word made of itself). Guards: never a word the tagger "
        "reads whole alone, one whose alone reading already has a compound's shape, one the text reads whole with the "
        "lists' reading, or one spelled in katakana alone — left to the katakana-name rule (Q4: ダンボール). A run "
        "inside a word the tables join, or across one, is no evidence. The mark 8 (app/dictionary_data.py, from "
        "JMdict): a noun compound JMdict lists as a noun (n, n-adv, n-t, n-suf) that the text, or the word read alone, "
        "writes with a verb's stem (its plain 連用形, never する's) — a run of nouns and stems spelling it joins as the "
        "noun: anywhere when it ends in a noun, but when it ends in a stem only where nothing but closing punctuation "
        "follows on the line (a card, a known word); a new such word takes the parts of its commonest reading in the "
        "text (立ち位置 = 立つ + 位置, the verb a learner knows). Q3: a stem at the end of a run mid-sentence stays apart "
        "(魔法使い + サリー, 事業仕分け + は; logged for later as its own variant: what follows the stem). Q5: a word "
        "the tagger mostly reads another way joins only where it reads nouns (partial joins kept: 過去問, 中小企業 — "
        "the other readings are other rules' TARGETs). Q6: stem + noun words that read so alone too (居場所), stem + "
        "方 / 過ぎ and nouns from a grammatical second verb are not part of this. Q7: built before the パターン v5 "
        "rebuild, so no BUILDER bump of its own.",
        "Measured 2026-09-30 (in_text_compounds/REPORT.md; the variants intext-nouns / intext-stems): 731 new table "
        "words (5 refused as chance meetings, 7 as plurals; 910 read whole alone, 211 with a compound's shape alone, 4 "
        "read whole in the text, 89 katakana alone kept out); 584 marked words (216 new, 368 already in the table); a "
        "random 100 of the table's new words 96 right (98.8% by uses); the user's library 286 new joins across 80 "
        "words, every one right (153 / 48 with nouns only). Scorecard: JA-RPT-001 / 002 fixed; JA-VRB-005 and "
        "JA-ORD-370 re-expected (立ち入り禁止, 金文字 — both one word now, rightly). Speed unchanged; the table +1.6%.",
        "A chance meeting the even odds can't see joins (開橋 in 昇開橋 — 'lift bridge' is 昇開 + 橋; 一人立ち in "
        "一人立ち二人立ち, 'one, then two, stood up'): 4 of the 100 sampled. A word's parts are the tagger's reading "
        "(過去問 = 過去 + 問い), used only for crediting free parts. 281 words join in under half the places the "
        "text spells them (the rest stay as today). People's full names that the tagger doesn't tag enter the table "
        "(大岡越前, 梶原一騎 — one unit, but Ignore names doesn't hide them). A line ending in a verb's stem joins as the "
        "noun (a subtitle cut mid-word would too: 5 lines of the library, all nouns). A stem-last run mid-sentence "
        "stays apart (3 of 14 出来損ない in the reference text: 出来損ない呼ばわり). The edges of the list's cut-off move "
        "(待ち受ける off, 向き on — the one-parse rule at work). Every table rebuild needs the SCHEMA / ENGINE bumps (14 / "
        "21).",
        "decided", ("debug/parsing_fixes_run/in_text_compounds/REPORT.md", "Parsing_Future_Work.md #1, #7, #12",
                    "scripts/build_reference_data.py in_text_words", "app/analyzer.py _joins_with_stems",
                    "variants_ja_intext.py intext-nouns, intext-stems")),
)

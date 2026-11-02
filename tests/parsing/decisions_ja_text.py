"""Decisions for Japanese text reading and sentence splitting (cases_ja_text.py) — and FILE-ENCODING, which Chinese
files share (cases_zh.py's ZH-ENC cases) — merged into the register by decisions.py. Fields and rules: decisions.py
and docs/agent instructions/Parsing_Suite.md §7.

Counts quoted from "the library" were measured read-only on 2026-09-26 over data/ja (HighPriority, LowPriority,
GoalContent; .srt cues as pysrt-free block splits, .ass Dialogue events)."""
from tests.parsing.decisions import Decision

ALL = (
    # --- decided: the standing rules a LIMIT case accepts -------------------------------------------------------- #
    Decision(
        "LINE-BREAK-BOUNDARY", "2026-07-13",
        "Does every line break end a Japanese sentence?",
        "Yes — JapaneseTokenizer.tokenize_sentences reads a text line by line, and the end of a line ends the "
        "sentence whatever comes before it.",
        "v2.0 (PRE_RELEASE_FEATURES_v2.0.md, 'Cleaner Example Sentences'): fugashi swallows \\n, so a YouTube "
        "transcript's title / URL / dashes merged into its first sentence (v=…------AIを…) and caption lines with "
        "no punctuation ran together. The downloader relies on it (v2.1: one cue per line in the timestamped "
        "format).",
        "A sentence hard-wrapped across lines is cut, even mid-word (彼は新幹 / 線に乗った。); so is a quotation "
        "that runs over several lines.",
        "decided", ("PRE_RELEASE_FEATURES_v2.0.md", "tests/test_sentence_splitting.py")),
    Decision(
        "CUE-CLOSES", "2026-09-18",
        "A subtitle cue that ends in no punctuation: the end of a sentence, or a sentence the next cue continues?",
        "The end, unless the cue marks a continuation: analyzer.close_cue appends 。 to a cue ending in no "
        "terminator (。｡．！？!?, looked for past closing brackets and quotes: 「行くぞ。」 has ended) and leaves one "
        "ending in a continuation mark (➡ ➨ → ⇒ ➔ ►, Netflix's ― —) open, the mark removed, to join the next cue — "
        "or in a comma (、，,､), the comma kept. A cue ending in … or ‥ has ended but gains no 。: its end is a line "
        "break (JA-ELLIPSIS). Consecutive .ass events that share one timing are one caption, closed once — one per "
        "speaker's colour on that screen since 2026-09-29 (CAPTION-SPEAKERS) — (an .srt cue is its own caption: two "
        "cues with one timing are two speakers shown at once). No grammar guess.",
        "v2.1 (RELEASE_v2.1.md): unterminated anime cues made 409-character 'sentences' (51 after); v2.2 "
        "(RELEASE_v2.2.md): Netflix's dash joins the line like the fansubs' arrow. A cue is the subtitle's own unit "
        "of speech, and the marks are its own way of saying a sentence runs on. F4 (2026-09-27): the file's own "
        "marks and timing — the broadcast captions' ➨, a comma (UAX #29 SContinue), a caption's lines written as "
        "events with one timing, a … cue's end without an invented 。.",
        "A sentence the subtitler broke across cues with no mark becomes fragments each closed with 。 "
        "(…織姫を救うために。 / …一護たちは。): 5,479 .srt cues in the library end in が を に で て は or と with no "
        "mark (an upper bound); a fragment is a shorter example, and rarely one a learner can read alone.",
        "decided", ("RELEASE_v2.1.md", "RELEASE_v2.2.md", "tests/test_subtitle_sentence_splitting.py")),
    Decision(
        "READ-AS-WRITTEN", "2026-09-26",
        "Does the reader repair what a text says — guess sentence ends it doesn't mark, correct speech-to-text "
        "errors, drop a page's navigation?",
        "No. The reader removes markup it recognises by the file format's own conventions (subtitle labels, tags, "
        "cues); a text's words and punctuation are taken as written.",
        "Recorded 2026-09-26 from the app's standing behaviour and the adversary's LIMITATION rows (ja_tokens T13, "
        "T23, P07): a guessed boundary or a corrected word needs a language model or a hand list (WORD-IDENTITY). "
        "The report's display window (≤150 characters around the word, RELEASE_v2.1) keeps a run-on example "
        "readable, and YouTube cues are joined into one paragraph on purpose (downloader.clean_vtt_cues: a cue is "
        "not a sentence).",
        "Speech-to-text with no 。 reads as run-on 'sentences' (889 YouTube sentences over 150 characters, 114 over "
        "500) — fewer i+1 examples; SNS text never ends at ｗ or an emoji; speech-to-text garbage (わかわかんない) "
        "and a scraped page's navigation (戻る次へ in every scripture chapter file) count as words.",
        "decided", ("debug/parsing_suite/ja_tokens T13, T23, P07",)),
    Decision(
        "SENTENCE-FROM-TOKENS", "2026-07-31",
        "A sentence's text: the file's own characters, or its tokens' surfaces joined?",
        "The tokens' surfaces joined — MeCab's ASCII spaces are no tokens, so they vanish; a full-width space is a "
        "token and stays.",
        "The sentence is what the token store caches beside its tokens; a source link finds it in the file "
        "whitespace-tolerantly (static_html_generator.AnchorFinder, RELEASE_v2.1). Dropping the spaces is also "
        "what joins a YouTube transcript's cue pieces back into words (なん ですよね → なんですよね).",
        "Latin words run together in examples (YouTubeのHarryPotterを見た。) and a subtitle's spacing between "
        "phrases is lost (そうだ 女｡ → そうだ女｡) — display only.",
        "decided", ("RELEASE_v2.1.md", "debug/parsing_suite/known RL-35")),

    # --- decided 2026-09-27 (Parsing_Fixes_Plan.md §1): the text-reading answers ------------------------------- #
    Decision(
        "JA-ELLIPSIS", "2026-09-27",
        "Does … (or ‥) inside a line end a Japanese sentence?",
        "No — … is as often a pause inside one sentence as an end: そうか…じゃあ行くか。 is one example. A subtitle "
        "cue that ends in … has still ended, on its own timing: analyzer.close_cue ends it with a line break and "
        "adds no 。 (F4).",
        "The user, 2026-09-27 (decision 5): 'No — it is as often a pause (あの…すみません).' Raised 2026-09-26: "
        "split — an utterance often ends in … in subtitles and manga, and the sunset Reels merge treated … as a "
        "terminator; keep — a wrong split makes two half-examples where a wrong join makes one long one. The end "
        "of a cue is the file's boundary, not its text's: 12,530 .srt cues of the library read …。 before F4.",
        "Two utterances joined by … inside one line make one example (そうか…じゃあ行くか。); a pause that crosses "
        "two subtitle cues (あの… / すみません) is two, since the cue's end is the boundary.",
        "decided", ("Parsing_Fixes_Plan.md §1 decision 5", "debug/parsing_suite/ja_tokens P04",
                    "debug/parsing_suite/known RL-10")),
    Decision(
        "QUOTE-SPANS", "2026-09-27",
        "A quotation holding several sentences (「今日は晴れ。明日は雨」と言った。, 『…。…。』で始まる): split at its "
        "inner 。, or kept whole with what follows it?",
        "Kept whole when と / って or a verb follows the closing bracket: 「今日は晴れ。明日は雨」と言った。 and "
        "「行くぞ。」走り出した。 are one sentence each (analyzer._sentence_ends). Quotations in a row with nothing "
        "between them are taken together by what follows the last: 「やめて。」「いやだ。」と言い合った。 is one "
        "sentence; 「おはよう。」「おはよう。」 alone is two. A comma after the closing marks continues the sentence "
        "(UAX #29 SB8a, SContinue): 「はい。」、と彼は言った。 is one. Any other follower leaves its sentences apart, "
        "the closing bracket with the sentence it closes (UAX #29 SB9): 「行くぞ。」 / 次だ。 The quotation brackets "
        "are 「」『』｢｣〝〟“” (Unicode's Quotation_Mark brackets); a closer with no opener on its line closes a "
        "quotation opened on an earlier line.",
        "The user, 2026-09-27 (decision 6): 'Kept whole when と / って or a verb follows the closing bracket.' The "
        "quotation is the object of 言った: neither half is a sentence a learner can read alone, and each carried "
        "an unbalanced bracket. Before F4 every inner 。 split. Quotations in a row and the comma: built by lane RC1 "
        "(2026-09-28, JA-SPL-045, -046, -901 – -903); the user, 2026-09-29, took the lean — と takes both "
        "quotations.",
        "Long examples when a long speech is quoted (the display window trims them); a quotation that nothing "
        "takes as a quote (a line of dialogue: 「今日は晴れ。明日は雨。」) still splits, each half with one bracket; "
        "a quotation followed by another particle (『…』で始まる) is QUOTE-SPANS-PARTICLES (decided the same day: "
        "whole).",
        "decided", ("Parsing_Fixes_Plan.md §1 decision 6", "debug/parsing_suite/ja_tokens P02")),
    Decision(
        "SUB-PARENS", "2026-09-27",
        "A parenthesised group in a subtitle — a speaker label, a reading, a sound — or speech (a thought, an aside)?",
        "Keep removing them, as today, until the library shows thought lines (the user, 2026-09-27): every （…） / "
        "(…) group in a subtitle goes — labels, readings, sounds, and a thought line with them.",
        "Today every （…） / (…) group goes (_strip_bracketed): labels （風太郎）, readings 中野(なかの) and sounds "
        "（ドアをたたく音）, and with them any thought line （どうしよう…）. In the library the groups are labels, "
        "readings and sounds: of the .srt cues that are one group, 1,479 end in 音 / 声 and the other 535 are "
        "sounds and notes too (ざわめき, ノック, ため息, 警官の英語) — no thought line was found. Keep speech: a "
        "whole-cue group with a predicate is dialogue. Remove all: a mistaken keep puts a sound or a name into a "
        "sentence. Lean (approved): remove all (today), until a library shows thought lines.",
        "A thought written in parentheses never reaches the list (JA-TXT-011); a rule to keep one would have to "
        "tell （どうしよう…） from （荒い息遣い）.",
        "decided", ("debug/parsing_suite/known RL-18", "tests/test_speaker_label_stripping.py",
                    "Parsing_Fixes_Plan.md §1 decision 7")),
    Decision(
        "SONG-LINES", "2026-09-27",
        "Sung lyrics — an OP / ED karaoke event, a ♪-marked cue: content to count?",
        "Skip only lines the file itself marks as song (the user, 2026-09-27): an ASS / SSA event carrying karaoke "
        "timing (\\k, \\K, \\kf, \\ko — analyzer.ass_dialogue_text); keep ♪ dialogue and on-screen signs. A style's "
        "name is the subtitler's free text, not the format's, so a song style is known by its karaoke only.",
        "Today every cue and every Dialogue event counts, whatever its style. Skip songs: an OP / ED repeats every "
        "episode, multiplying its words' counts by the episode count, in a poetic register (the catalog's RL-30). "
        "Count: it is Japanese the learner hears. In the library the question hardly arises: its 42 .ass files hold "
        "no song events (styles Default / Default-ja only), and its 1,514 ♪ cues are music marks (♪～, no Japanese: "
        "dropped) or sung dialogue (だから口調を変えているんだヨー♪). Lean (approved): skip only events the file "
        "itself marks as song (a karaoke \\k tag, a song style), keep ♪ dialogue; on-screen signs stay content.",
        "An insert song's words are lost when the file times it as karaoke; an OP subtitled without karaoke timing "
        "(its style named OP, say) still counts, repeated every episode.",
        "decided", ("debug/parsing_suite/known RL-30", "Parsing_Fixes_Plan.md §1 decision 8")),
    Decision(
        "QUOTE-SPANS-PARTICLES", "2026-09-27",
        "A quotation holding two sentences followed by a particle other than と / って (『吾輩は猫である。名前はまだ"
        "無い。』で始まる小説, 「…。…」が口癖だ): kept whole as with と / って, or split at its inner 。 as before?",
        "Kept whole when any particle (UniDic 助詞: で, が, の, は, を, も, まで, なんて …) follows the closing bracket, "
        "as with と / って and a verb (analyzer._takes_quotation): 『吾輩は猫である。名前はまだ無い。』で始まる小説を"
        "読んだ。 is one sentence. A noun or a new subject after the bracket still starts a sentence (「はい。」 / "
        "彼女は頷いた。); another quotation right after it, or a comma, does not (QUOTE-SPANS, 2026-09-29: "
        "JA-SPL-045, -046).",
        "The user, 2026-09-27: 'yes' (the lean). The quotation is a noun phrase of the sentence (what the novel "
        "begins with), the reason given for と / って in decision 6, and a particle can't begin a Japanese sentence: "
        "before, the split left 『吾輩は猫である。 / 名前はまだ無い。』 / で始まる小説を読んだ。 — the last starting "
        "with a particle, the first two with dangling brackets.",
        "Long examples when a long passage is quoted as a noun (the display window trims them).",
        "decided", ("Parsing_Fixes_Plan.md §1 decision 6", "tests/test_sentence_splitting.py")),

    Decision(
        "FILE-ENCODING", "2026-09-27",
        "In which encoding is a file the user supplies read — content, KnownWord.json, the word lists, a frequency "
        "list, in Japanese or Chinese — when nothing but its bytes says?",
        "The file's own, by one rule for every such file (path_utils.read_text, F1): a BOM names it (UTF-8, UTF-16, "
        "UTF-32); else strict UTF-8; else the language's Windows encodings, each read strictly — CP932 for Japanese; "
        "GB18030, then Big5 as Windows writes it (code page 950, with the ETEN characters 恒 裏 碁) for Chinese — "
        "and the first whose reading holds no Private Use character (U+E000–F8FF) wins. A file none of them reads "
        "whole is read as UTF-8 with its bad bytes marked U+FFFD, and a warning — never dropped.",
        "A file's encoding is a property of the file, not of its text (F1, Parsing_Fixes_Plan.md; built 2026-09-27 — "
        "11 fixed, 14 new cases). Before it, CP932 / UTF-16 / GBK files contributed nothing, silently, and a "
        "KnownWord.json or word list saved with a BOM or as UTF-16 stopped Generate. The Private Use refusal and "
        "code page 950 were accepted by the orchestrator the same day: GB18030 reads almost any byte pair, Big5's "
        "included, and every Big5 ，。 comes out Private Use — without the refusal no Big5 file would read as Big5; "
        "without cp950 one 恒 loses a whole file (ZH-ENC-018). The user, 2026-09-27, on short Big5 lists: accepted "
        "the lean (accept the limit below).",
        "A short Big5 file with no punctuation — a word list, 學習 / 中文 — holds nothing that tells Big5 from GBK: "
        "its GB18030 reading has no Private Use character, so it is read as GB18030, wrong words (ZH-ENC-017, "
        "LIMIT). A Big5 file with any ，。 reads right, and saving the list as UTF-8 fixes it. No statistical guess "
        "at the encoding: a guess would misread short GBK lists instead, and the rule stays one the user can "
        "reason about.",
        "decided", ("Parsing_Fixes_Plan.md F1", "app/path_utils.py read_text", "tests/test_file_encodings.py")),

    # --- decided 2026-09-27: a setting, the learner's choice ------------------------------------------------------ #
    Decision(
        "TXT-PAREN-READINGS", "2026-09-27",
        "Kana alone in parentheses right after kanji in a Japanese book's .txt (玖渚友(くなぎさ・とも), 窮鼠（きゅうそ）): "
        "that kanji's reading — the typographic stand-in for ruby, removed as F3 removes Aozora 《ruby》 — for any "
        "kana, for hiragana only, or kept as text (as before)?",
        "A setting, default hiragana only: settings.json logic.paren_readings (Settings → Language & Parsing, "
        "'Readings in ( ) in books', Japanese only). \"hiragana\" (the default, 'Hiragana only (recommended)'): a "
        "group of hiragana (with ・ ー) right after kanji in a .txt / .md book is that kanji's reading and goes, as "
        "Aozora 《ruby》 does; \"any\" ('Any kana'): a katakana or mixed group too; \"off\" ('Keep as text'): every "
        "group is text, as before. One place every reader reaches — analyzer.strip_text_conventions (PAREN_READINGS, "
        "paren_readings()), so the analyzer, the token store, the sentence dictionary and the パターン build read "
        "alike; never a subtitle (SUB-PARENS drops every group already) or a transcript. In the run signature (never "
        "_NON_ANALYSIS_SETTINGS); in the token store's build signature only when not the default; the report's "
        "source anchor finds a sentence whichever option (REMOVED_INLINE holds any kana in parentheses). The plain "
        "scorecard measures the default; variants paren-readings-any / paren-readings-off the other two.",
        "The user, 2026-09-27, on the measurement below: 'I don't suppose this could be a setting selection? So it "
        "turns on and off for the 3 variations? And make the default your recommendation.' Earlier the same day: "
        "'yes' to the rule for any kana, to be measured before it is relied on. Measured "
        "read-only the same day on the library (data/ja HighPriority, LowPriority, GoalContent: 1,620 .txt, no .md): "
        "40 kana-only groups right after kanji, in 28 files, of 404 parenthesised groups after kanji — 19 readings "
        "(15 names in hiragana: 衣笠彰梧（きぬがさ・しょうご）, 戯言's cast list; 凸（デコ） / 凹（ボコ） ×4), 6 "
        "glosses (複製（コピー） ×2, 傾向（ホメオスタシス）, 章（チャプター）, 月光会（ルーナー・ソサエティー）, "
        "心（りっしんべん）) and 15 asides (GS「堕落（アダムとエバの）」 ×9, ぶどう園（イスラエル）, 株（キリスト）, "
        "預言者（アビナダイ）, 自分（アマリキヤ）, 自分（モロナイ）, 批評家（ウィリアム・エンプソン）): 38% asides, over the "
        "10% the build was held to, so it was not built. By script: the 16 hiragana groups are 15 readings and one "
        "gloss, no aside; of the 24 with katakana, 4 are readings. The rest of data/ja (copies of the same books) adds "
        "妻（わたし） (a reading), 傷（トラウマ） (a gloss), 岸見一郎（きしみ・いちろう）. The recommendation, now the "
        "default: hiragana only — a kanji's reading is written in hiragana; katakana after kanji is mostly an aside "
        "or a loanword gloss. Either way the list barely moves: 94 word uses leave the counts (hiragana only: 40 — "
        "mostly junk pieces of the names read as words: と + ヤマ, 其の, 礼, 順), 1–11 per word, no word gained, and "
        "the one word that would fall below the list's floor (ルナ, a misreading of ルーナー, 11 → "
        "10) goes only with the katakana groups.",
        "The default (hiragana only): a reading in katakana stays counted (凸（デコ）, 4 of 40 — JA-TXT-050, LIMIT), "
        "and a hiragana gloss goes (心（りっしんべん）, 1 — JA-TXT-054, LIMIT). 'Any kana': an aside or a gloss in "
        "katakana goes with the readings — 自分（アマリキヤ）を reads 自分を, and the learner loses who 自分 is (15 of "
        "40); コピー, ホメオスタシス lose a use. Either rule: the "
        "example shows the kanji without its reading (玖渚友, 妻が後片づけをする — the author's わたし gone), as with "
        "Aozora ruby; an aside in hiragana right after kanji with no punctuation (天才（なんちゃって）) would go — none "
        "in the library. 'Keep as text': every reading counts again, as junk pieces (くなぎさ・とも → ナギサ + 共; "
        "はんだ・れい → 半田 + 礼). A learner who changes the option re-indexes the library once and re-analyses once.",
        "decided", ("Parsing_Fixes_Plan.md §1 (F3's questions)", "tests/parsing/variants_ja_text.py",
                    "tests/test_paren_readings.py", "debug/parsing_suite/ja_tokens T18")),

    # --- decided 2026-09-29: lane RC1's answers (the user: "keep going" — every lean holds) ------------------------ #
    Decision(
        "STRETCH-MARKS", "2026-09-29",
        "A wave dash or ー inside a word (すご～い, ふる～い, いらっしゃ～い, 暗～い, ありがとー): a stretched vowel of "
        "the word, or a symbol between two pieces?",
        "～ (U+FF5E, the JIS wave dash as Windows' code page 932 decodes it) is read 〜 (U+301C, as the JIS mapping "
        "and UniDic write it). Inside a word — after kana or a kanji, before a kana — a wave dash or a run of marks "
        "is one ー. A ー the tagger still leaves alone after hiragana or a kanji is read with the word before it (the "
        "word read without it: 暗～い → 暗い, す〜ぐ → 直ぐ). After katakana ー is part of the word (オットー). "
        "Between two kanji ～ is a range, no stretch (月曜～金曜). One place every tagger call reaches: "
        "analyzer.tagger_text / Tagger (_SAME_CHARACTER, _stretches, _lone_marks).",
        "The user, 2026-09-29: took the lean ('keep going'). UniDic's own pronunciations read 〜 inside a word as ー "
        "(あま〜い is アマーイ); sys.dic holds 718 entries with 〜 and 48 with ～, one of which reads ～ as から — "
        "counted in every stretched line before. 現代仮名遣い writes a long vowel in hiragana with a vowel letter, so "
        "a ー there is a stretch; 外来語の表記 writes it in katakana with ー, so there it belongs to the word "
        "(measured: dropping it after katakana turned オットー into 夫, ゼニー into 銭). On the library (read-only, "
        "2026-09-28): 19,473 unique lines hold a mark; the fallback fired on 432, mostly improvements (ずる～い → "
        "狡い, きらーい → 嫌い, ごめ～ん → 御免, もーっと → もっと). Built by lane RC1 (JA-SCR-003, -004, -101, "
        "-901 – -907).",
        "A drop can make another word: しゃーない read without its ー is しゃない, which UniDic reads 社内 (JA-VRB-022, "
        "LIMIT; 0 uses in the library). A stretch at a word's end before the next word is unseen (いや～なんだかんだ, "
        "JA-CMP-062); a nickname stays junk (ラムちー).",
        "decided", ("lanes/RC HANDOFF.md §1", "tests/test_tagger_reading.py")),
    Decision(
        "CUE-LINES", "2026-09-29",
        "A subtitle caption's line break (an .srt cue's lines, an .ass event's \\N, a caption's events): nothing, or "
        "a space?",
        "Chinese: nothing between two East Asian wide characters (Unicode East_Asian_Width F / W / H — Hangul "
        "aside), a space otherwise — CSS Text 3 §4.1.3's segment-break rule (analyzer._join_lines): 我觉得\\N他不会来 "
        "is 我觉得他不会来, 我买了一件\\NT恤 is 我买了一件 T恤. Japanese keeps the space: to its tagger it is the word "
        "boundary where the subtitler broke the line, and the sentence's text drops spaces anyway "
        "(SENTENCE-FROM-TOKENS).",
        "The user, 2026-09-29: took the lean. jieba reads a space as a boundary, so a Chinese caption joined with "
        "one cut a word the subtitler broke across lines; CSS Text 3 is the web's own rule for joining such lines. "
        "Japanese: 行くぞ / うん needs the boundary (JA-TXT-904). Built by lane RC1 (ZH-TXT-006, -901, -902).",
        "A Chinese word broken across lines beside a Latin letter keeps a space (我买了一件 T恤); a Japanese line "
        "broken inside a word stays cut there (as LINE-BREAK-BOUNDARY).",
        "decided", ("lanes/RC HANDOFF.md §1", "tests/test_subtitle_sentence_splitting.py")),
    Decision(
        "CAPTION-SPEAKERS", "2026-09-29",
        "Consecutive .ass events with one timing — one screen of captions: one speaker's caption, or several "
        "speakers' at once?",
        "One screen; each colour on it is one speaker's caption, its lines in the file's order (analyzer._captions). "
        "An event's colour is its first visible character's: its style's PrimaryColour as \\c / \\1c / \\r change it "
        "(parse_ass). One colour on the screen is one caption, as CUE-CLOSES built it.",
        "The user, 2026-09-29: took the lean. Japanese TV captions (字幕放送) tell speakers apart by colour: the "
        "library's 3 broadcast series hold 48 same-timing pairs in two colours, and all 48 are two people speaking — "
        "one interleaves a speaker's two lines around the other's (JA-TXT-902, made up on that shape). The first "
        "visible character's colour skips the converters' coloured-space quirk (JA-TXT-903). Built by lane RC1.",
        "Two speakers in one colour still read as one caption; one speaker whose lines change colour on one screen "
        "reads as two.",
        "decided", ("lanes/RC HANDOFF.md §1", "tests/test_subtitle_sentence_splitting.py")),
)

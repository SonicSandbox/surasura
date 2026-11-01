"""Decisions for the kinds the second random audit found (cases_ja_audit.py, audit 2026-09-29) — merged into the
register by decisions.py. Fields and rules: decisions.py and docs/agent instructions/Parsing_Suite.md §7.

Built by lane AF, 2026-09-30, under the user's approval to fix the audit's remaining small kinds. Counts quoted from
"the library" were measured read-only on 2026-09-30 over the token store's 357,368 sentences, re-read with the app's
tokenizer under the suite's pins (the frozen settings and name tables): debug/parsing_fixes_run/lanes/AF/HANDOFF.md."""
from tests.parsing.decisions import Decision

ALL = (
    Decision(
        "DASH-STRETCH", "2026-09-30",
        "A dash drawn out right after a kana — ─ ━ (box drawing, which web text writes for a dash), ― (the horizontal "
        "bar), — (an em dash): a stretched vowel inside the word (ジャ─────ック, 衛兵さ───ん), or the dash between two "
        "words (それは──あなたの)?",
        "A stretch only where it can't be the dash: before a ん / ン that ends the word (衛兵さ───ん, う────ん, ド────ン) "
        "and between katakana where the word goes on after a ッ, a small kana or ン, none of which begins a word "
        "(ジャ─────ック). There the run is read as one ー, as STRETCH-MARKS reads a run of marks — so ジャ─────ック is "
        "ジャーック, as ジャ～ック is. Everywhere else a dash: between words, before a ッ that ends the word (the catch "
        "of a shout: いくぞ──ッ, 何──ッ), before a hiragana っ / ん that goes on (──って, ──んだ). One place every tagger "
        "call reaches: analyzer.tagger_text (_DASH_STRETCH_RE, _inside_a_word).",
        "The user approved fixing the audit's kinds (2026-09-30); the audit found ジャ─────ック read as 蛇 + ック. On the "
        "library, ─ stands between kana 698 times, about 650 of them the dash between two words (light novels write "
        "── for it); ― 11, all dashes. Read as STRETCH-MARKS reads ～ — a stretch wherever a kana follows — 112 "
        "sentences changed: 8 better (衛兵さーん, おおーッ, グーッ), 5 worse (何──ッ became 何 + つ, ひ──ッ ひー + つ, "
        "月丹──ッ lost its name, かも──って read 持って, ディアボ──ッ the junk name ディアボーッ), the rest only their "
        "surfaces. As built, 3 sentences change, all better: 衛兵さ───ん is さん (twice), ジャ─────ック one word.",
        "A shout's stretch before a final ッ stays a dash (おおお──ッ, グ──ッ, な──ッ: harmless — the word before is "
        "read as without it); a stretched katakana word keeps its ー unless the word without it is a word (since "
        "2026-10-01, KATAKANA-STRETCH-DROP: ジャ─────ック is the name ジャック); "
        "a word stretched before a letter that can begin a word stays in pieces (は──い is はあ + い, すご────い 凄い + "
        "い); a stretched suffix doesn't join its word (お母さ───ん is お母 + さん, as お母さ～ん is).",
        "decided", ("lanes/AF HANDOFF.md", "tests/test_tagger_reading.py", "JA-AUD-011", "JA-AUD-024")),
    Decision(
        "DASH-NOT-A-WORD", "2026-09-30",
        "A dash UniDic reads as a word by context — the full-width hyphen-minus － as から, 対, マイナス or 引く, the wave "
        "dash 〜 as から: a word, or punctuation?",
        "Punctuation: a token that is one dash — Unicode's Dash_Punctuation (Pd), and ～, which the tagger reads as the "
        "wave dash — is never a word (analyzer.word_lemma). The sentence keeps it.",
        "Unicode files the dashes as punctuation; the tagger's word for one is a guess from context (救い－幼い: から). "
        "On the library － counted 18 times, every one punctuation: scripture headings (GS「救い－幼い子供たちの救い」 — "
        "から 10 times, 対 4, マイナス 1, 引く 1), a verse range (3ニフ10・15－16, から) and a katakana long vowel "
        "written with it (コピ－, マイナス). 17 sentences change.",
        "A range's から said aloud (1－3 read いちからさん) is no use of から. Other symbols UniDic reads as words still "
        "count — ％ パーセント (78 uses in the library), ○ 丸, × バツ, ℃ 度, ． テン, ／ 割る: Unicode files them as "
        "other punctuation or symbols, not dashes, and none is decided here. A katakana long vowel written with a "
        "dash stays wrong (コピ－ is コピ read as コーヒー: JA-AUD-037).",
        "decided", ("lanes/AF HANDOFF.md", "tests/test_word_lemma.py", "JA-AUD-023", "JA-AUD-036")),
    Decision(
        "FILLER-PIECES", "2026-09-30",
        "Two fillers the tagger cut out of one interjection — ま + あ for まあ (けどまあやっぱり), あ + あ～ for ああ～, "
        "い + え for いえ: two fillers (まー + あー), or the interjection?",
        "The interjection or adverb the pair reads as ALONE, when the tagger reads it alone as ONE such word (UniDic's "
        "感動詞 or 副詞): まあ, ああ, いえ, ええ, うん, shown as written. Only two of UniDic's fillers (フィラー) in a row, "
        "each one kana (a ー or 〜 aside — UniDic spells some with 〜: え〜), nothing between them; a pair that reads "
        "otherwise alone stays (う + え〜 in うえ～ん reads 上; ま + え in したまえ), as do two whole interjections (あー "
        "+ あー, each ああ). analyzer._sounds, a step of join_affixes.",
        "UniDic decides what a word is: alone, まあ is まあ and いえ いえ; in speech without punctuation its lattice "
        "prefers a chain of one-mora fillers. On the library 498 sentences change: まあ 285 uses (was まー + あー), "
        "ああ 192 (あ～あ, ああ～), いえ 95, ええ 88, うん 14, おお 6, えい 5 — the fillers あー 673, まー 285, えー 277, "
        "いー 100 fewer.",
        "UniDic's pick for the pair is not always the word said: Kansai ええ 'good' (騒がんでええ, めっちゃええタイミ"
        "ング — about 5 of the 88) becomes ええ 'yes', and a pair cut out of another word (挟み撃ちにあう: 遭う read あ + "
        "う) the interjection あう — each as wrong as the two fillers were, now one wrong word instead of two.",
        "decided", ("lanes/AF HANDOFF.md", "tests/test_sound_words.py", "JA-AUD-017", "JA-AUD-018",
                    "JA-AUD-029")),
    Decision(
        "REPEATED-SOUNDS", "2026-09-30",
        "A sound said three times or more that the tagger leaves as a katakana word it doesn't know (ハァハァハァ, "
        "ﾌﾌﾌﾌﾌ), though it lists the sound said twice (ハァハァ はあはあ): a word of its own, or the sound word?",
        "The sound word the tagger reads that sound said twice as, alone, when that is ONE interjection or adverb it "
        "knows: ハァハァハァ is はあはあ, ﾌﾌﾌﾌﾌ ふふ, ダラダラダラダラ だらだら — shown as written. Only a katakana word "
        "the dictionary lacks that is one unit written three times or more (a final ッ or ー aside); else as it was. "
        "analyzer._sounds.",
        "Japanese makes its sound words by doubling (畳語), and the dictionaries list the doubled form; said more "
        "times it is the same sound. On the library 109 sentences change: はあはあ 87 uses (81 were the unknown "
        "word ハァハァハァ), ふふ 8, ぴぴ 5, ぼんぼん, だらだら, ふらふら, もぐもぐ, ぶつぶつ, ちょろちょろ, かたかた.",
        "A stammer said like a sound becomes the sound word (シャ、シャ、シャシャシャシャシャ、シャドウ様: しゃしゃ — "
        "JA-AUD-032); a sound whose double the tagger reads as two words stays a word of its own (ヘヘヘ, ゼロゼロゼロ"
        "ゼロ); UniDic lists a few threes as words of their own (はあはあはあ, どんどんどん), so one sound said three "
        "times can sit on two rows by script.",
        "decided", ("lanes/AF HANDOFF.md", "tests/test_sound_words.py", "JA-AUD-019", "JA-AUD-031")),
    Decision(
        "GLUED-OPENER", "2026-09-30",
        "The next line's opening bracket that the tagger reads as one symbol with a full stop — half-width ｡｢, ｡((, "
        "〞。〝: the end of this sentence, or the start of the next?",
        "The start of the next: in the token a sentence ends with, an opening bracket or quote (Unicode Ps / Pi) after "
        "its terminator begins the next sentence (analyzer._opening). The token is a symbol, never a word: only the "
        "sentences' text moves.",
        "The splitter already keeps an opening mark out of a sentence's end (_closes takes closing marks only, UAX "
        "#29's SB9 read for Japanese); the tagger glues a full stop and a bracket it knows in neither form (JIS X 0201's "
        "half-width ｡｢, ｡((, 〞。〝) into one unknown symbol. On the library 182 sentences ended with the next line's "
        "bracket — 《 110 (subtitle captions), (( 40, ｢ 24, 〝 6, “ 1, 「 1.",
        "A symbol between the stop and the bracket stays with the sentence that ends (！⚞「 → ！⚞ | 「).",
        "decided", ("lanes/AF HANDOFF.md", "tests/test_sentence_splitting.py", "JA-AUD-020", "JA-AUD-034")),
)

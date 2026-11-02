"""Japanese text reading and sentence splitting — a file as the app reads it (layer text, and the text_scan /
text_report / text_extract layers of evaluators_ja_text.py).

Groups owned by this file: TXT (reading and cleaning files), SPL (sentence splitting), ENC (encodings) —
docs/agent instructions/Parsing_Suite.md, "Ids". Seeded by the framework; ported 2026-09-26 from
debug/parsing_suite/ja_tokens (categories 6 and 7), debug/parsing_suite/known (text cleaning, sentence splitting,
encoding) and the splitting / speaker-label / verse-number tests. Decisions: decisions_ja_text.py.

Every case is a file's content with its extension and encoding (ctx ext / encoding / name), read through the app's
own path — so a fix to the reader shows up here, whichever function it lands in. "The library" in a basis means the
user's data/ja, measured read-only on 2026-09-26; the Chinese side (the zh cleaner, …… and ，) is cases_zh.py's.
"""
from tests.parsing.case import Case, ass, srt

# The first five cues of the repo's sample subtitle (samples/ja/HighPriority/H_priority_sample_2.srt, 五等分の花嫁),
# byte for byte: a BOM, CRLF, a trailing space after each timing, nested furigana in a speaker label and a reading.
_SAMPLE_SRT = ("﻿1\r\n00:00:02,419 --> 00:00:03,628 \r\n（風太郎(ふうたろう)）くっ…\r\n\r\n"
               "2\r\n00:00:03,962 --> 00:00:06,923 \r\n何だ これ\r\nセンサー 反応しろ！\r\n\r\n"
               "3\r\n00:00:07,465 --> 00:00:12,554 \r\nクソ あの５人だけでなく\r\nお前も俺の邪魔をするのか！\r\n\r\n"
               "4\r\n00:00:13,263 --> 00:00:14,556 \r\nあの…\r\n\r\n"
               "5\r\n00:00:15,265 --> 00:00:18,518 \r\n30階の中野(なかの)さんの\r\n家庭教師をしている\r\n")


def _youtube(title, channel_line, body="", kind="Japanese (native auto)",
             url="https://www.youtube.com/watch?v=k3fCiT5rbGw"):
    """A YouTube transcript as the downloader writes it (modules/youtube_downloader downloader.build_text): the
    title, 'channel | date | duration', the captions line, the URL, a blank line, a rule of 60 dashes, then the
    cues from the next line — joined by spaces (one per line when timestamps are kept)."""
    return "\n".join([title, channel_line, f"Captions: {kind}", url, "", "-" * 60, ""]) + body + "\n"


# An .ass file shaped like the library's broadcast captions ([SubsPlease] … .ja.ass): a BOM, [Script Info], the
# styles and the events, each with its own start and end — the two lines of one caption are two events that share
# one timing. Events: (start, end, text), or (start, end, text, style, kind) — kind "Dialogue" or "Comment".
_ASS_HEAD = ("﻿[Script Info]\nScriptType: v4.00+\nPlayResX: 960\nPlayResY: 540\n\n[V4+ Styles]\n"
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
             "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
             "Alignment, MarginL, MarginR, MarginV, Encoding\n"
             "Style: Default,Yu Gothic,46,&H00FFFFFF,&H000000FF,&H00000000,&H7F000000,1,0,0,0,100,100,4,0,1,2,2,1,"
             "0,0,0,1\n"
             "Style: OP,Yu Gothic,40,&H00FFFFFF,&H000000FF,&H00000000,&H7F000000,1,0,0,0,100,100,0,0,1,2,2,8,"
             "0,0,20,1\n\n"
             "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")


def _ass_events(*events):
    lines = []
    for event in events:
        start, end, text = event[:3]
        style = event[3] if len(event) > 3 else "Default"
        kind = event[4] if len(event) > 4 else "Dialogue"
        lines.append(f"{kind}: 0,{start},{end},{style},,0000,0000,0000,,{text}\n")
    return _ASS_HEAD + "".join(lines)


# [SubsPlease] Yomi no Tsugai - 13 (1080p).ja.ass, events 45–50: a voice-over (⸨ … ⸩) labelled with its speaker
# (アサ：), carried over six events by the ➨ arrow, two of them two-line captions (437 / 497 share a timing).
_YOMI_VOICE_OVER = _ass_events(
    ("0:01:15.26", "0:01:17.60", "{\\pos(172,497)}⸨{\\c&H00FFFF00\\fscx50}アサ：{\\fscx100}運命の双子に生まれたのは➨"),
    ("0:01:17.60", "0:01:20.60", "{\\pos(292,437)\\c&H00FFFF00}自分で選んだ道じゃ"),
    ("0:01:17.60", "0:01:20.60", "{\\pos(312,497)\\c&H00FFFF00}なかったけど➨"),
    ("0:01:20.60", "0:01:24.61", "{\\pos(252,437)\\c&H00FFFF00}ここからは"),
    ("0:01:20.60", "0:01:24.61", "{\\pos(272,497)\\c&H00FFFF00}自分で選んだ道だから➨"),
    ("0:01:24.61", "0:01:27.94", "{\\pos(312,497)\\c&H00FFFF00}自分で手を汚すよ{\\c&H00FFFFFF}⸩"))

# The repo's sample subtitle, cues 61–63 byte for byte: two speakers talking at once are two cues with one timing
# (Netflix repeats the first speaker's line beside the second's).
_SRT_TWO_SPEAKERS = ("61\r\n00:04:18,800 --> 00:04:20,343 \r\n（風太郎）あれは てめえが薬を…\r\n\r\n"
                     "62\r\n00:04:20,343 --> 00:04:21,844 \r\n（風太郎）あれは てめえが薬を…\r\n\r\n"
                     "63\r\n00:04:20,343 --> 00:04:21,844 \r\n（二乃）フフフフ…\r\n")

# Moroni_1.txt (a scripture book imported from a web page): its footnote block, citations as book · chapter・verse.
_SCRIPTURE_FOOTNOTES = "2①\n1ニフ12・20－23\n2②\nアル45・14\n3①\nマタ10・32－33、3ニフ29・5\n"

# An SSA (v4) subtitle, the .ass format's predecessor: the same events under [V4 Styles] and a Marked field.
_SSA = ("[Script Info]\nScriptType: v4.00\n\n[V4 Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, Bold, Italic, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding\n"
        "Style: Default,MS Gothic,28,16777215,65535,65535,-2147483640,0,0,1,2,2,2,10,10,10,0,128\n\n"
        "[Events]\nFormat: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: Marked=0,0:00:02.00,0:00:04.50,Default,,0000,0000,0000,,本当にそう思うの。\n")

# One EPUB chapter (the extract layer packs it into a book): a head <title>, a heading, and ruby with <rp> fallbacks.
_EPUB_CHAPTER = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
                 '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ja" lang="ja"><head><title>第一章</title>'
                 '<link rel="stylesheet" type="text/css" href="style.css"/></head><body><div class="main">'
                 '<h1>序章</h1><p>彼は<ruby>漢字<rp>（</rp><rt>かんじ</rt><rp>）</rp></ruby>を覚えた。</p>'
                 '<p>次の日も図書館へ行った。</p></div></body></html>')

CASES = [
    # === TXT: reading and cleaning files (A) ===================================================================== #
    # --- subtitle speaker labels, readings and sounds in parentheses --------------------------------------------- #
    Case(id="JA-TXT-001", lang="ja", layer="text", category="A",
         text=_SAMPLE_SRT, span="（風太郎(ふうたろう)）",
         expect={"contains": ["くっ…", "お前も俺の邪魔をするのか！", "中野さんの家庭教師をしている"],
                 "not_contains": ["）", "ふうたろう", "なかの", "-->", "00:00"]},
         basis="A speaker label and a furigana reading are not dialogue: a nested label is removed whole "
               "(_strip_bracketed) — no orphan ） — and a reading in parentheses goes with it; the dialogue stays. "
               "Cue numbers and timings never reach a sentence.",
         status="LOCK", source="doc: samples/ja/HighPriority/H_priority_sample_2.srt", ctx={"ext": ".srt"},
         refs=("tests/test_speaker_label_stripping.py", "debug/parsing_suite/ja_tokens T02",
               "debug/parsing_suite/known RL-17, SD-37")),
    Case(id="JA-TXT-005", lang="ja", layer="text", category="A",
         text=srt("（上杉）そうだね", "(上杉)そうだね", "（一花）（二乃）そうだね"), span="",
         expect={"sentences": ["そうだね。", "そうだね。", "そうだね。"]},
         basis="A plain speaker label goes whole, in full-width or ASCII parentheses, one or several in a row — "
               "the Netflix / broadcast caption convention of naming the speaker in parentheses before the line.",
         status="LOCK", ctx={"ext": ".srt"},
         refs=("tests/test_speaker_label_stripping.py::test_a_plain_unnested_label_still_goes",
               "tests/test_speaker_label_stripping.py::test_adjacent_and_trailing_groups",
               "debug/parsing_suite/ja_tokens T01")),
    Case(id="JA-TXT-006", lang="ja", layer="text", category="A",
         text=srt("）くっ…", "（風太郎 何やってるの"), span="",
         expect={"contains": ["くっ…", "何やってるの"], "not_contains": ["）"]},
         basis="An orphan closing bracket is residue, never content; a cue whose opening bracket never closes "
               "keeps the dialogue after it — losing subtitle text is worse than one stray （.",
         status="LOCK", ctx={"ext": ".srt"},
         refs=("tests/test_speaker_label_stripping.py::test_an_orphan_closing_bracket_is_dropped_wherever_it_sits",
               "tests/test_speaker_label_stripping.py::test_an_unmatched_opener_keeps_the_dialogue_after_it")),
    Case(id="JA-TXT-007", lang="ja", layer="text", category="A",
         text=srt("（風太郎(ふうたろう)）", "（三玖(みく)）本当にそう思うの。"), span="",
         expect={"sentences": ["本当にそう思うの。"]},
         basis="A cue that is nothing but a speaker label says nothing: it vanishes, not an empty sentence.",
         status="LOCK", ctx={"ext": ".srt"},
         refs=("tests/test_speaker_label_stripping.py::test_a_label_only_cue_is_not_emitted_end_to_end",)),
    Case(id="JA-TXT-008", lang="ja", layer="text", category="A",
         text=ass("{\\pos(10,20)}（三玖(みく)）そうだね"), span="",
         expect={"sentences": ["そうだね。"]},
         basis="ASS override tags ({\\pos(10,20)}) are styling, removed before the label's brackets are counted — "
               "their own parentheses must not unbalance it.",
         status="LOCK", ctx={"ext": ".ass"},
         refs=("tests/test_speaker_label_stripping.py::test_ass_override_tags_are_removed_before_bracket_counting",
               "debug/parsing_suite/known RL-19")),
    Case(id="JA-TXT-009", lang="ja", layer="text", category="A",
         text=_ass_events(("0:00:15.44", "0:00:18.27",
                           "{\\pos(232,497)\\fscx50}（{\\fscx100}左{\\fscx50}）{\\fscx100}東の村の言い伝えだな{\\fscx50}。")),
         span="",
         expect={"sentences": ["東の村の言い伝えだな。"]},
         basis="Broadcast captions mark who speaks by screen side, （右） / （左） — a label, with override tags even "
               "inside its brackets; the line is the dialogue.",
         status="LOCK", source="library: [SubsPlease] Yomi no Tsugai - 13 (1080p).ja.ass", ctx={"ext": ".ass"}),
    Case(id="JA-TXT-010", lang="ja", layer="text", category="A",
         text=srt("（織姫）ハァハァ ハァハァ… （ドアをたたく音）"), span="（ドアをたたく音）",
         expect={"contains": ["ハァハァ"], "not_contains": ["織姫", "ドア"], "not_words": ["ドア", "叩く"]},
         basis="SDH captions describe sounds in parentheses — （ドアをたたく音） 'knocking on the door' is no speech; "
               "the library's .srt holds 2,014 cues that are one such group (ざわめき, ノック, ため息, …音).",
         status="LOCK", source="library: Bleach - 161.srt", ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/known RL-18",)),
    Case(id="JA-TXT-011", lang="ja", layer="text", category="A",
         text=srt("そうだね（心の声）", "（どうしよう…）"), span="（どうしよう…）",
         expect={"contains": ["どうしよう…"]},
         basis="A thought written in parentheses is speech the learner reads; today every parenthesised group "
               "goes. （心の声） 'inner voice' is a note and rightly goes. expect is the keep side.",
         status="LIMIT", decision="SUB-PARENS", ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/known RL-18",
               "tests/test_speaker_label_stripping.py::test_adjacent_and_trailing_groups"),
         note="SUB-PARENS decided 2026-09-27: keep removing every group, as today, until the library shows thought "
              "lines — the thought is the price."),

    # --- the subtitle cleaner's ASCII strip ---------------------------------------------------------------------- #
    Case(id="JA-TXT-002", lang="ja", layer="text", category="A",
         text=_SAMPLE_SRT, span="30階",
         expect={"contains": ["30階の中野さんの"]},
         basis="30階 'the 30th floor' is what the line says; the subtitle cleaner strips every ASCII letter and "
               "digit, so the example sentence changes meaning and the number guard can't see the number "
               "(回目, 年後 then join as words). 1,756 .srt cues of the library hold an ASCII letter or digit.",
         status="LOCK", source="doc: samples/ja/HighPriority/H_priority_sample_2.srt", ctx={"ext": ".srt"},
         refs=("Parsing_Robustness_Suite_Scope.md §2 A", "debug/parsing_suite/ja_tokens T08",
               "debug/parsing_suite/known RL-22", "F2 (Parsing_Fixes_Plan.md): markup, not letters",
               "tests/test_subtitle_markup.py")),
    Case(id="JA-TXT-012", lang="ja", layer="text", category="A",
         text=srt("(ﾙﾋﾟ)階級は No.６｡", "iPhoneを買った", "Tシャツを着る"), span="",
         expect={"contains": ["No.６", "iPhoneを買った", "Tシャツを着る"]},
         basis="Latin letters are part of what a Japanese line says — No.６ 'number 6', iPhone, Tシャツ (JMdict "
               "ティーシャツ): stripping them leaves 階級は.６｡, a sentence that starts at を, and シャツ for Tシャツ. "
               "Not counting a Latin token is the tokenizer's job, not the cleaner's.",
         status="LOCK", source="library: Bleach - 138.srt (the first cue; the others constructed)",
         ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/ja_tokens T09, T10", "debug/parsing_suite/known RL-22", "F2",
               "tests/test_subtitle_markup.py")),
    Case(id="JA-TXT-013", lang="ja", layer="text", category="A",
         text=srt("398回目ですよ", "100年ぶりだね", "ｷﾐが知るのは 100年後｡"), span="",
         expect={"contains": ["398回目ですよ"], "not_words": ["回目", "年ぶり", "年後"]},
         basis="After a number a counter is no word of its own (Part A's number guard: 三回目 = 三 + 回 + 目); "
               "the stripped digits hide the number, so 回目, 年ぶり and 年後 join as words (年生 203, 番隊 179, 度目 "
               "171, 回目 146, 年後 97 uses in the library).",
         status="LOCK", decision="AFFIX-GUARDS",
         source="library: コンフィデンスマンJP.S01E10 (Netflix).srt, Bleach - 300.srt, Bleach - 199.srt",
         ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/ja_tokens M14, M15, M16", "F2: the digits stay, so the number guard sees them")),
    Case(id="JA-TXT-014", lang="ja", layer="text", category="A",
         text=srt("こんにちは\nHello", "- 行こう", "> そうだね"), span="",
         expect={"sentences": ["こんにちは。", "行こう。", "そうだね。"]},
         basis="An English line of a bilingual cue is not the Japanese text, and a leading - or > is subtitle "
               "noise; the Japanese line stays.",
         status="LOCK", ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/known RL-23",)),

    # --- markup a subtitle format defines ------------------------------------------------------------------------ #
    Case(id="JA-TXT-015", lang="ja", layer="text", category="A",
         text=srt("<b>てか ﾅｲﾌ投げんなよ</b>\n<b>皿とかあんだろ ｽﾌﾟｰﾝとか…</b>",
                  "<i>余は余の領内の反乱を鎮めるため</i>", '<font color="#ffff00">行くぞ</font>'), span="",
         expect={"not_contains": ["<", ">", '="#"']},
         basis="SubRip's markup — <b>, <i>, <font color> — is formatting, not text; the cleaner strips the letters "
               "inside it and leaves <>…</> and <=\"#\"> in the sentence: 4,638 <b> pairs in the library's Amazon "
               "subtitles (Vinland Saga), 3,050 sentences.",
         status="LOCK", source="library: ヴィンランド・サガ.S02E01 (Amazon).srt (the first cue)",
         ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/ja_tokens T11", "debug/parsing_suite/known RL-21", "F2",
               "tests/test_subtitle_markup.py")),
    Case(id="JA-TXT-016", lang="ja", layer="text", category="A",
         text=ass("そうだ\\Nお前に話がある", "えっと\\hその"), span="",
         expect={"contains": ["お前に話がある"], "not_contains": ["\\"]},
         basis="In ASS, \\N is a forced line break and \\h a hard space (the format's own escapes), read like an "
               "SRT cue's second line; the ASCII strip leaves a lone backslash (そうだ\\お前に話がある。). The library's "
               ".ass files hold none today.",
         status="LOCK", ctx={"ext": ".ass"},
         refs=("debug/parsing_suite/known RL-20", "F2", "tests/test_subtitle_markup.py")),
    Case(id="JA-TXT-017", lang="ja", layer="text", category="A",
         text=_ass_events(("0:00:01.00", "0:00:03.00", "訳注：ここは後で直す", "Default", "Comment"),
                          ("0:00:03.00", "0:00:05.00", "本当にそう思うの。")), span="",
         expect={"sentences": ["本当にそう思うの。"]},
         basis="An ASS Comment event is the subtitler's note, never shown: only Dialogue events are speech.",
         status="LOCK", ctx={"ext": ".ass"},
         refs=("debug/parsing_suite/known RL-30",)),
    Case(id="JA-TXT-018", lang="ja", layer="text", category="A",
         text=_ass_events(("0:01:30.00", "0:01:34.00", "{\\k40}夢{\\k30}の{\\k45}中{\\k30}で{\\k60}君を探した", "OP"),
                          ("0:01:34.00", "0:01:36.00", "本当にそう思うの。")), span="夢",
         expect={"contains": ["本当にそう思うの。"], "not_contains": ["夢の中で"]},
         basis="An OP karaoke event (\\k syllable timings, the OP style) is a song the file marks as one; every "
               "episode repeats it. expect is the skip side.",
         status="LOCK", decision="SONG-LINES", ctx={"ext": ".ass"},
         refs=("debug/parsing_suite/known RL-30", "F3", "tests/test_subtitle_conventions.py"),
         note="SONG-LINES decided 2026-09-27: skip only what the file marks as song — the karaoke timing does."),

    # --- speaker labels a subtitle convention writes with a colon ------------------------------------------------ #
    Case(id="JA-TXT-019", lang="ja", layer="text", category="A",
         text=_YOMI_VOICE_OVER, span="アサ：",
         expect={"not_contains": ["アサ："], "not_words": ["麻"]},
         basis="⸨アサ：… ⸩ is a voice-over labelled with its speaker — Name + full-width colon at the start, the "
               "caption convention for who speaks; today the label is dialogue (83 sentences of this series carry "
               "one) and アサ is read 麻 'hemp'.",
         status="LOCK", source="library: [SubsPlease] Yomi no Tsugai - 13 (1080p).ja.ass", ctx={"ext": ".ass"},
         refs=("debug/parsing_suite/ja_tokens T03", "F3", "tests/test_subtitle_conventions.py")),
    Case(id="JA-TXT-020", lang="ja", layer="text", category="A",
         text=srt("《浮竹:四月か…｡"), span="浮竹:",
         expect={"not_contains": ["浮竹:"]},
         basis="《Name: opens a voice-over line with its speaker's name (95 such cues in the library's .srt: 《平子:, "
               "《一角:, 《ｳﾙｷｵﾗ:) — a label, not dialogue, as with ⸨アサ：.",
         status="LOCK", source="library: Bleach - 138.srt", ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/ja_tokens T03", "F3", "tests/test_subtitle_conventions.py")),

    # --- sound cues in square brackets --------------------------------------------------------------------------- #
    Case(id="JA-TXT-003", lang="ja", layer="text", category="A",
         text=_youtube("動画タイトル", "忠犬ハチ公 | 2024-05-01 | 12:34", "[音楽]疲れちゃったっていう感じですね。"),
         span="[音楽]",
         expect={"not_contains": ["[音楽]"], "not_words": ["音楽"]},
         basis="[音楽] is YouTube's auto-caption marker for music, not speech: 1,055 cue tokens are credited to "
               "音楽 511, 笑い 465, 咳払い 33 (row #462), 拍手 30. One case for every [cue] of the .txt path.",
         status="LOCK", source="library: @忠犬ハチ公 (youtube) — the cue line under the downloader's header "
                               "(its title and channel line constructed)",
         refs=("Parsing_Robustness_Suite_Scope.md §2 A", "debug/parsing_suite/ja_tokens T07, T24",
               "debug/parsing_suite/known RL-29", "F3", "tests/test_text_conventions.py"),
         note="The text first held the cue line alone; the library file is the downloader's, header and all, and "
              "that header is what says the brackets are a caption's sound cues. A .txt without it is read as "
              "written (READ-AS-WRITTEN) — a web novel's [ステータス] stays."),
    Case(id="JA-TXT-021", lang="ja", layer="text", category="A",
         text=_youtube("動画タイトル", "PIVOT 公式チャンネル | 2024-05-01 | 25:00",
                       "そうですね。 へえ。 18[笑い]年後 はどうなってますか?"),
         span="[笑い]",
         expect={"not_contains": ["[笑い]"], "not_words": ["笑い", "年後"]},
         basis="A cue between a number and its counter hides the number: 18 [laughter] 年後 is 18年後 'in 18 "
               "years', yet 年後 joins as a word after the cue.",
         status="LOCK", source="library: PIVOT 公式チャンネル - 【推薦入試こそ学力が必要】… (youtube) — the cues under "
                               "the downloader's header (its title and channel line constructed)",
         refs=("debug/parsing_suite/ja_tokens M17", "F3"),
         note="As JA-TXT-003: the text first held the cue line alone, without the header the file carries."),
    Case(id="JA-TXT-022", lang="ja", layer="text", category="A",
         text=srt("[無線](浦原)決まったっすねぇ｡"), span="[無線]",
         expect={"not_contains": ["[無線]"], "not_words": ["無線"]},
         basis="[無線] 'over the radio' is an SDH note on how a line is heard, in square brackets; 25 such cues "
               "(無線, ﾓﾆﾀ, 外) keep it as a word.",
         status="LOCK", source="library: Bleach - 213.srt", ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/ja_tokens T06", "F3", "tests/test_subtitle_conventions.py")),
    Case(id="JA-TXT-023", lang="ja", layer="text", category="A",
         text=srt("［拍手］"), span="",
         expect={"sentences": []},
         basis="［拍手］ in full-width brackets is an SDH sound cue ('applause'), as （拍手） is — which goes today.",
         status="LOCK", ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/ja_tokens T05", "F3")),

    # --- YouTube transcripts ------------------------------------------------------------------------------------- #
    Case(id="JA-TXT-004", lang="ja", layer="text", category="A",
         text=_youtube("『サイゼで喜ぶ彼女』を社会学的に斬っていく山田玲司【山田玲司のヤングサンデー  切り抜き】",
                       "山田玲司の原作が10倍おもしろくなる解説【切り抜き】 | 2022-02-22 | 13:27"), span="",
         expect={"sentences": []},
         basis="A transcript's header — the title, 'channel | date | duration', captions, URL, rule — is the "
               "downloader's label, not the video's speech: 93 of 原作's 160 uses (row #61) come from one channel's "
               "headers, 切り抜き 100 (#35).",
         status="LOCK", source="library: 山田玲司の原作が - 意見/ (a youtube transcript's header)",
         refs=("Parsing_Robustness_Suite_Scope.md §2 A", "debug/parsing_suite/ja_tokens T12",
               "debug/parsing_suite/known RS-4", "F3", "tests/test_text_conventions.py")),
    Case(id="JA-TXT-024", lang="ja", layer="text", category="A",
         text=_youtube("天気の話", "天気チャンネル | 2025-05-01 | 3:10",
                       "[00:01:02] 今日はいい天気ですね\n[00:01:05] そうですね", kind="Japanese (manual)"),
         span="[00:01:02]",
         expect={"contains": ["今日はいい天気ですね"], "not_contains": ["[00:"]},
         basis="The 'keep timestamps' format prefixes each cue with its time — the downloader's own mark, not "
               "speech; it reaches the example sentence as [00:01:02]今日は….",
         status="LOCK",
         refs=("debug/parsing_suite/known RL-14", "F3", "tests/test_text_conventions.py")),

    # --- books and web text: ruby, readings, annotations, apparatus ---------------------------------------------- #
    Case(id="JA-TXT-025", lang="ja", layer="text", category="A",
         text=("しかし事実そうなのかもしれない。草薙くさなぎは先程から目の前のチェス盤を二十分以上睨んでいるが、どう考えても"
               "打開策は見えてこなかった。キングの逃げ道はなく、窮鼠きゆうそ猫を噛むとばかりにがむしゃらに攻撃する術すべもない。"
               "いろいろと手は思いつくが、それらのすべてが何手も前に封じられていることに気づくのだった。\n"
               "退屈そうに頬杖をついてそういってから、湯川学はわざとらしい大欠伸あくびをした。小さめのメタルフレームの眼鏡は"
               "外して脇に置いてある。いかにも、もう必要ないといわんばかりだ。\n"), span="くさなぎ",
         expect={"not_contains": ["草薙くさなぎ", "欠伸あくび"], "not_words": ["クサナギ", "欠伸"]},
         basis="Flattened ruby: the reading printed right after its kanji (草薙くさなぎ, 大欠伸あくび, 窮鼠きゆうそ) is the "
               "same word again, not text — today it counts as a second word (~25 in this book).",
         status="TARGET", source="library: 容疑者Xの献身_09.txt",
         refs=("debug/parsing_suite/ja_tokens T16, T17",),
         note="F3 left it: no markup marks the reading, so no format convention finds it. Telling it from text needs "
              "a dictionary test (the kana after a kanji run is that run's reading — 草薙 くさなぎ; the old kana of "
              "窮鼠きゆうそ and the partial 大欠伸あくび make it fuzzy) — a rule of its own, not markup."),
    Case(id="JA-TXT-026", lang="ja", layer="text", category="A",
         text="玖渚友(くなぎさ・とも)\n", span="(くなぎさ・とも)",
         expect={"not_contains": ["くなぎさ"], "not_words": ["ナギサ", "共"]},
         basis="Kana in parentheses right after a name is its reading (くなぎさ・とも for 玖渚友), the typographic "
               "stand-in for ruby; a .txt novel is not cleaned, so なぎさ is counted again and とも read 共.",
         status="LOCK", decision="TXT-PAREN-READINGS", source="library: 戯言1_01.txt",
         refs=("debug/parsing_suite/ja_tokens T18", "tests/test_paren_readings.py"),
         note="F3 left it: a .txt declares no format, and 漢字(かな) is a reading only by typographic habit "
              "(小説家になろう makes it ruby in its own files). Fixed 2026-09-27 by the setting "
              "(logic.paren_readings), under its default, hiragana only — and under 'Any kana' (variant "
              "paren-readings-any); 'Keep as text' leaves it (variant paren-readings-off)."),

    # --- TXT-PAREN-READINGS (a setting, 2026-09-27): kana in parentheses right after kanji — filed under its default,
    # hiragana only; variants paren-readings-any / paren-readings-off measure the other two options ------------- #
    Case(id="JA-TXT-049", lang="ja", layer="text", category="A",
         text="キングの逃げ道はなく、窮鼠（きゅうそ）猫を噛むとばかりに攻撃する術もない。\n", span="（きゅうそ）",
         expect={"contains": ["窮鼠猫を噛む"], "not_contains": ["きゅうそ"]},
         basis="Hiragana alone in parentheses right after kanji is its reading (窮鼠 きゅうそ), the typographic "
               "stand-in for ruby — the same word again, not text, as Aozora's 窮鼠《きゅうそ》 (F3).",
         status="LOCK", decision="TXT-PAREN-READINGS",
         source="constructed: 容疑者Xの献身_09.txt's sentence (JA-TXT-025) with its reading in parentheses",
         note="The user's own example (2026-09-27). Fixed by the setting's default (hiragana only), and by 'Any "
              "kana'; 'Keep as text' leaves it."),
    Case(id="JA-TXT-050", lang="ja", layer="text", category="A",
         text=("スタンドライトでもマグカップでも、丸くワッと広がった部分、キュッと狭まった部分、穴、取っ手の曲線などなど、"
               "さまざまな凸（デコ）と凹（ボコ）のリズミカルな組み合わせでできています。\n"), span="（デコ）",
         expect={"not_contains": ["（デコ）", "（ボコ）"]},
         basis="Katakana alone in parentheses right after kanji, here the reading of 凸 and 凹 (凸凹 デコボコ) — a "
               "ruby stand-in as JA-TXT-049 is; it counts デコ and ボコ once more each.",
         status="LIMIT", decision="TXT-PAREN-READINGS", source="library: センスの哲学_07.txt",
         note="The default's price (hiragana only, 2026-09-27): a katakana group stays text, so デコ and ボコ count "
              "once more each — katakana after kanji was a reading in 4 of the library's 24 katakana groups (these "
              "four). The 'Any kana' option removes it (variant paren-readings-any)."),
    Case(id="JA-TXT-051", lang="ja", layer="text", category="A",
         text="また、もしレホンタイが自分（アマリキヤ）を全軍の副指揮官にしてくれるならば、その兵をレホンタイの手に引き渡しても"
              "いいと言った。\n",
         span="（アマリキヤ）",
         expect={"contains": ["自分（アマリキヤ）を"], "words": ["アマリキヤ"]},
         basis="An aside, not a reading: the parentheses name who 自分 means — アマリキヤ is no reading of 自分 "
               "(じぶん). The name is text the learner reads.",
         status="LOCK", decision="TXT-PAREN-READINGS", source="library: Alma_47.txt (a chapter's summary)",
         note="The default (hiragana only) keeps it; the 'Any kana' option removes it (variant paren-readings-any): "
              "15 of the library's 40 groups after kanji are asides like this (ぶどう園（イスラエル）, "
              "預言者（アビナダイ）, GS「堕落（アダムとエバの）」 ×9)."),
    Case(id="JA-TXT-052", lang="ja", layer="text", category="A",
         text="GS「堕落（アダムとエバの）」\n", span="（アダムとエバの）",
         expect={"contains": ["堕落（アダムとエバの）"], "words": ["アダム", "エバ"]},
         basis="A topic's title in the scripture's Guide (the Fall 'of Adam and Eve'): the parentheses are part of "
               "the title, not a reading of 堕落 (だらく).",
         status="LOCK", decision="TXT-PAREN-READINGS", source="library: Alma_12.txt (and 8 more chapters)",
         note="The default (hiragana only) keeps it; 'Any kana' removes it (katakana and hiragana mixed)."),
    Case(id="JA-TXT-053", lang="ja", layer="text", category="A",
         text=("また本作品の全部または一部を無断で複製（コピー）、転載、配信、送信（ホームページなどへの掲載を含む）を行うこと、"
               "ならびに改竄、改変を加えることは著作権法その他の関連法規、および国際条約で禁止されています。\n"),
         span="（コピー）",
         expect={"contains": ["複製（コピー）"], "words": ["コピー"]},
         basis="A gloss, not a reading: コピー is another word for 複製 (ふくせい), which the text writes out — "
               "a word the learner reads.",
         status="LOCK", decision="TXT-PAREN-READINGS", source="library: 思考の整理学_01.txt (an e-book's notice)",
         note="The default (hiragana only) keeps it; 'Any kana' removes it (6 such glosses of 40: コピー ×2, "
              "ホメオスタシス, チャプター, ルーナー・ソサエティー, りっしんべん)."),
    Case(id="JA-TXT-054", lang="ja", layer="text", category="A",
         text="「忙」の字は、心（りっしんべん）を亡くしていると書く。\n", span="（りっしんべん）",
         expect={"contains": ["心（りっしんべん）"]},
         basis="A gloss in hiragana: りっしんべん names the form 忄 that 心 takes in 忙 — not 心's reading "
               "(こころ, しん). Text the learner reads.",
         status="LIMIT", decision="TXT-PAREN-READINGS", source="library: 思考の整理学_17.txt",
         note="The default's price (hiragana only, 2026-09-27), and the 'Any kana' option's too: the one hiragana "
              "group of the library's 16 that isn't a reading goes, and the sentence reads 心を亡くしている. Only "
              "'Keep as text' keeps it (variant paren-readings-off; its words there are 立心 + 偏, not 立心偏)."),
    Case(id="JA-TXT-055", lang="ja", layer="text", category="A",
         text="そして数十秒後、ぼくはキムチがこんもりと盛られた（おばちゃんはサービスしてくれた）どんぶりを片手に、"
              "巫女子ちゃんの正面に戻った。\n",
         span="（おばちゃんはサービスしてくれた）",
         expect={"contains": ["盛られた（おばちゃんはサービスしてくれた）どんぶり"], "words": ["サービス"]},
         basis="An aside in kana after a verb: only a group right after kanji can be a kanji's reading, so the rule "
               "never reaches it, whichever option.",
         status="LOCK", decision="TXT-PAREN-READINGS", source="library: 戯言2_04.txt"),
    Case(id="JA-TXT-027", lang="ja", layer="text", category="A",
         text="漢字《かんじ》を覚える。\n｜夏目漱石《なつめそうせき》の本を読む。\n", span="《かんじ》",
         expect={"not_contains": ["《", "｜"], "not_words": ["感じ"]},
         basis="Aozora Bunko's ruby notation: 《…》 after kanji is the reading, ｜ marks where the ruby base starts "
               "(the 青空文庫 注記 rules) — today かんじ is counted as 感じ.",
         status="LOCK",
         refs=("debug/parsing_suite/ja_tokens T19", "F3", "tests/test_text_conventions.py")),
    Case(id="JA-TXT-028", lang="ja", layer="text", category="A",
         text=("その時、低空飛行をしていた一台の飛行艇から信号があった。《敵は島の背後より、太平洋に向かって、潜水艦に乗じて"
               "遁れ去らんとす》「しまった」龍介はそう叫ぶと直ちに信号をかえした。《直ちに着水せよ》。\n"), span="",
         expect={"contains": ["敵は島の背後より", "直ちに着水せよ"]},
         basis="《…》 also quotes text (here signal messages): it is ruby only as kana right after kanji, so a rule for "
               "Aozora ruby must keep these words.",
         status="LOCK", source="corpus: aozora/aozora_0023.txt"),
    Case(id="JA-TXT-029", lang="ja", layer="text", category="A",
         text=("叔父は仕方なしに私の空家へはいる事を承諾してくれました。しかし市の方にある住居もそのままにしておいて、両方の"
               "間を往ったり来たりする便宜を与えてもらわなければ困るといいました。私に［＃「私に」は底本では「私は」］固より"
               "異議のありようはずがありません。私はどんな条件でも東京へ出られれば好いくらいに考えていたのです。\n"),
         span="［＃「私に」は底本では「私は」］",
         expect={"contains": ["私に固より異議のありようはずがありません。"], "not_words": ["底本"]},
         basis="［＃…］ is an Aozora Bunko input note (here: the source edition reads 私は), not the novel's text.",
         status="LOCK", source="library: こころ_28.txt", refs=("F3", "tests/test_text_conventions.py")),
    Case(id="JA-TXT-030", lang="ja", layer="text", category="A",
         text=("すべてを腹の中にしまっておいて下さい。」\n\n底本：「こころ」集英社文庫、集英社\n"
               "１９９１（平成3）年2月25日第1刷\n１９９５（平成7）年6月14日第10刷\n初出：「朝日新聞」\n"
               "１９１４（大正3）年4月20日～8月11日\n※誤植の修正は「漱石全集」岩波書店を参照しました。\n"
               "入力：j.utiyama\n校正：伊藤時也\n１９９９年7月31日公開\n２０１０年10月31日修正\n青空文庫作成ファイル：\n"
               "このファイルは、インターネットの図書館、青空文庫（http://www.aozora.gr.jp/）で作られました。入力、校正、"
               "制作にあたったのは、ボランティアの皆さんです。\n"), span="底本",
         expect={"contains": ["すべてを腹の中にしまっておいて下さい。"],
                 "not_words": ["底本", "初出", "校正", "青空", "文庫"]},
         basis="An Aozora Bunko file ends with its colophon — 底本：, 初出：, 入力：, 校正：, the 青空文庫 notice — the "
               "format's bibliographic block after the text, not the novel.",
         status="LOCK", source="library: こころ_54.txt",
         refs=("debug/parsing_suite/ja_tokens T20", "F3", "tests/test_text_conventions.py")),
    Case(id="JA-TXT-031", lang="ja", layer="text", category="A",
         text=_SCRIPTURE_FOOTNOTES, span="ニフ",
         expect={"sentences": [], "not_words": ["ニフ", "アル", "マタ"]},
         basis="A cross-reference — a book's abbreviation, then chapter・verse (1ニフ12・20－23 = 1 Nephi 12:20–23) — "
               "is apparatus, not language: 2,690 abbreviation tokens (アル 683, ニフ 655, モサ 318); ニフ is row #1 "
               "of the list, モサ #19, エテ #124.",
         status="LOCK", source="library: Moroni_1.txt (its footnote block)",
         refs=("Parsing_Robustness_Suite_Scope.md §2 A", "debug/parsing_suite/ja_tokens T14", "F3",
               "tests/test_text_conventions.py")),
    Case(id="JA-TXT-032", lang="ja", layer="text", category="A",
         text=("2 見よ、レーマン人同士の①戦争が今非常に激しい。また、彼らは憎しみのために、キリストを否定しないニーファイ人を"
               "すべて②殺している。\n"), span="①",
         expect={"not_words": ["一", "二"]},
         basis="①② are footnote marks tied to the notes below the chapter, not numerals in the sentence; UniDic "
               "reads ① as 一 and ② as 二, counted each time. (Backfill's 例文 tidy already drops ①–⑳.)",
         status="LOCK", source="library: Moroni_2.txt",
         refs=("debug/parsing_suite/ja_tokens T22", "debug/parsing_suite/known RL-26", "F3",
               "tests/test_text_conventions.py")),
    Case(id="JA-TXT-033", lang="ja", layer="text_report", category="A",
         text=("13そこでモーサヤは、主に命じられたとおりにした。\n14そして彼らは、ゼラヘムラの民と呼ばれた民を発見した。\n"
               "3人で主に祈った。\n"), span="",
         expect={"sentences": ["そこでモーサヤは、主に命じられたとおりにした。",
                               "そして彼らは、ゼラヘムラの民と呼ばれた民を発見した。", "3人で主に祈った。"]},
         basis="A verse number before a sentence is the book's numbering, not the sentence (376 of 11,199 examples "
               "began with one); a number that counts something (3人) is the sentence's own. Display only.",
         status="LOCK", source="doc: tests/test_verse_numbers.py (the user's Mosiah)",
         refs=("tests/test_verse_numbers.py::test_a_run_shows_the_verse_without_its_number_on_both_lists",
               "debug/parsing_suite/known RL-24")),
    Case(id="JA-TXT-034", lang="ja", layer="text_report", category="A",
         text="10年前に会った。\n12月になった。\n100万円もするの？\n2、3日で終わる。\n１人で待ってろ。\n５つ子豆知識！\n",
         span="",
         expect={"sentences": ["10年前に会った。", "12月になった。", "100万円もするの？", "2、3日で終わる。",
                               "１人で待ってろ。", "５つ子豆知識！"]},
         basis="A number followed by what it counts — a counter, another number, punctuation — is part of the "
               "sentence and stays: 10年前, 12月, 100万円, 2、3日, １人, ５つ子.",
         status="LOCK", source="doc: tests/test_verse_numbers.py",
         refs=("tests/test_verse_numbers.py::test_a_number_that_counts_something_stays",
               "debug/parsing_suite/known RL-24")),
    Case(id="JA-TXT-035", lang="ja", layer="text", category="H",
         text="関連コンテンツクロスパネル\n", span="クロス",
         expect={"words": ["クロス"], "not_words": ["クロース"]},
         basis="クロス here is 'cross' (a cross-reference panel); unidic-lite picks the lexeme クロース 'cloth' "
               "among these loanwords (alone, クロスする and テーブルにクロス read クロス) — row #24, 289 uses, from a "
               "page's chrome in every scripture chapter.",
         status="TARGET", source="library: Moroni_1.txt",
         refs=("debug/parsing_suite/ja_tokens T15",)),
    Case(id="JA-TXT-036", lang="ja", layer="text", category="A",
         text="戻る次へ\n", span="",
         expect={"sentences": []},
         basis="'Back / Next' is the web page's navigation the import kept (with 関連コンテンツクロスパネル), in "
               "every scripture chapter file — not the book; no format convention marks it.",
         status="LIMIT", decision="READ-AS-WRITTEN", source="library: Moroni_1.txt",
         refs=("debug/parsing_suite/ja_tokens T15",)),
    Case(id="JA-TXT-037", lang="ja", layer="text", category="A",
         text="あのわかわかんないです。\n", span="わかわかんない",
         expect={"words": ["分かる"], "not_words": ["我が"]},
         basis="Speech-to-text stutter: わか is a false start of わかんない, not 我が 'my'.",
         status="LIMIT", decision="READ-AS-WRITTEN", source="library: PIVOT 公式チャンネル (youtube)",
         refs=("debug/parsing_suite/ja_tokens T23",)),
    Case(id="JA-TXT-038", lang="ja", layer="text", category="A",
         text="# 第一章\n\n**本**を読む。\n", ctx={"ext": ".md"}, span="",
         expect={"not_contains": ["#", "**"]},
         basis="In a Markdown file (.md is a content type) # and ** are markup (CommonMark), not text; today they "
               "reach the sentence. The library holds no .md file.",
         status="LOCK", refs=("F3", "tests/test_text_conventions.py")),

    # --- which files are read ------------------------------------------------------------------------------------ #
    Case(id="JA-TXT-039", lang="ja", layer="text_scan", category="A",
         text=_SSA, ctx={"ext": ".ssa"}, span="",
         expect={"read": True, "sentences": ["本当にそう思うの。"]},
         basis="An .ssa subtitle is the same event format as .ass (v1.6 promised ASS / SSA) and extract_text parses "
               "it, but CONTENT_EXTENSIONS omits .ssa, so the scan never reads one.",
         status="LOCK",
         refs=("debug/parsing_suite/known RL-34", "F3", "tests/test_subtitle_conventions.py")),
    Case(id="JA-TXT-040", lang="ja", layer="text_scan", category="A",
         text="図書館で本を読む。", ctx={"ext": ".epub"}, span="",
         expect={"read": False},
         basis="An .epub (or .html) dropped straight into a tier folder is a container or markup, not text: it goes "
               "through Extract, and the scan skips it.",
         status="LOCK",
         refs=("tests/test_analyzer_ignores_epub_html.py::test_epub_and_html_in_content_folder_are_ignored",
               "debug/parsing_suite/known RL-33")),
    Case(id="JA-TXT-041", lang="ja", layer="text_extract", category="A",
         text=_EPUB_CHAPTER, ctx={"ext": ".epub"}, span="",
         expect={"sentences": ["序章", "彼は漢字を覚えた。", "次の日も図書館へ行った。"]},
         basis="An EPUB chapter's text is its body: the head's <title> is metadata, and ruby's <rt> reading and <rp> "
               "fallbacks are not the sentence. (The catalog's probe saw the title fused to the first line; through "
               "ebooklib 0.20 the head is rebuilt without it.)",
         status="LOCK",
         refs=("debug/parsing_suite/known RL-32",)),
    Case(id="JA-TXT-042", lang="ja", layer="text_extract", category="A",
         text=srt("（三玖(みく)）本当にそう思うの。", "残された わずかな時間で\n少しでも 己の力をあげるために➡",
                  "過酷な修行に 挑んでいた｡"),
         ctx={"ext": ".srt"}, span="",
         expect={"sentences": ["本当にそう思うの。", "残されたわずかな時間で少しでも己の力をあげるために過酷な修行に挑んでいた｡"]},
         basis="A subtitle read through Extract should say what the same file says in the library: Extract's own "
               "cleaner keeps the speaker label and the ➡ and writes each cue line on a line of its own, so the "
               "sentence breaks at every line.",
         status="LOCK",
         refs=("debug/parsing_suite/known RL-31", "tests/test_importer.py", "F3")),

    # --- F3's guards: what the format rules must leave alone (2026-09-27) --------------------------------------- #
    Case(id="JA-TXT-043", lang="ja", layer="text", category="A",
         text=_ass_events(("0:01:30.00", "0:01:34.00", "夢の中で君を探した", "OP"),
                          ("0:01:34.00", "0:01:36.00", "本当にそう思うの。")), span="夢の中で",
         expect={"contains": ["本当にそう思うの。"], "not_contains": ["夢の中で"]},
         basis="An OP line in the file's OP style with no karaoke timing: a song the file marks by its style, which "
               "decision 8 skips (a song style). ASS has no song flag — a style's name is the subtitler's free text "
               "(OP, ED, Song, 歌詞 …) — so only a list of names would find it.",
         status="LIMIT", decision="SONG-LINES", ctx={"ext": ".ass"},
         refs=("Parsing_Fixes_Plan.md §1 decision 8", "JA-TXT-018"),
         note="The 'song style' half of decision 8, unsettled by F3: built as karaoke timing only (JA-TXT-018); "
              "a style read by its name would be a hand-made list. Asked with F3. Re-filed LIMIT 2026-09-28: "
              "SONG-LINES as decided knows a song by its karaoke only and names this as its price (an OP subtitled "
              "without karaoke timing still counts)."),
    Case(id="JA-TXT-044", lang="ja", layer="text", category="A",
         text=srt("だから口調を変えているんだヨー♪", "♪～"), span="♪",
         expect={"contains": ["だから口調を変えているんだヨー♪"], "not_contains": ["～"]},
         basis="Sung dialogue marked ♪ is still what the character says; a cue that is only a music mark (♪～) holds "
               "no Japanese and gives no sentence. SONG-LINES keeps ♪ dialogue.",
         status="LOCK", decision="SONG-LINES", source="library: a ♪ cue quoted in SONG-LINES' count",
         ctx={"ext": ".srt"}, refs=("F3",)),
    Case(id="JA-TXT-045", lang="ja", layer="text", category="A",
         text=srt("理由は簡単：お前が弱いからだ", "アサ：行こう"), span="：",
         expect={"sentences": ["理由は簡単：お前が弱いからだ。", "行こう。"]},
         basis="A speaker label is a name before a colon; a clause before one (理由は簡単 — its particle is written in "
               "hiragana) is speech and stays. A name holds no hiragana, so the label rule reads no grammar.",
         status="LOCK", ctx={"ext": ".srt"}, refs=("F3", "JA-TXT-019", "tests/test_subtitle_conventions.py")),
    Case(id="JA-TXT-046", lang="ja", layer="text", category="A",
         text="1人目は太郎だ。\n2人目は花子だ。\n3人目は次郎だ。\n", span="1人目",
         expect={"sentences": ["1人目は太郎だ。", "2人目は花子だ。", "3人目は次郎だ。"]},
         basis="Numbers that count what follows them (1人目 'the first person') are the text's own, even on lines that "
               "count up like verses: every line of the run goes on with the same counter.",
         status="LOCK", refs=("F3", "JA-AUD-004", "JA-TXT-034", "tests/test_text_conventions.py")),
    Case(id="JA-TXT-047", lang="ja", layer="text", category="A",
         text="【鑑定】と唱えると、[ステータス]が表示された。\n", span="[ステータス]",
         expect={"contains": ["[ステータス]が表示された。"]},
         basis="Square brackets hold a caption's sound cue only in captions: a web novel's [ステータス] 'status' is its "
               "text. A .txt without the downloader's header is read as written (READ-AS-WRITTEN).",
         status="LOCK", refs=("F3", "JA-TXT-003", "tests/test_text_conventions.py")),
    Case(id="JA-TXT-048", lang="ja", layer="text", category="A",
         text=("こころ\n夏目漱石\n\n-------------------------------------------------------\n"
               "【テキスト中に現れる記号について】\n\n《》：ルビ\n（例）私《わたくし》\n\n"
               "｜：ルビの付く文字列の始まりを特定する記号\n（例）一｜人《ひとり》\n\n"
               "［＃］：入力者注　主に外字の説明や、傍点の位置の指定\n"
               "　　　（数字は、JIS X 0213の面区点番号またはUnicode、底本のページと行数）\n"
               "（例）※［＃「てへん＋劣」、第3水準1-84-77］\n"
               "-------------------------------------------------------\n\n　　　上　先生と私\n\n　　　　　一\n\n"
               "　私《わたくし》はその人を常に先生と呼んでいた。だからここでもただ先生と書くだけで本名は打ち明けない。\n"),
         span="【テキスト中に現れる記号について】",
         expect={"contains": ["私はその人を常に先生と呼んでいた。"],
                 "not_contains": ["【テキスト中に現れる記号について】"], "not_words": ["ルビ", "外字", "傍点", "水準"]},
         basis="An Aozora Bunko file opens with a legend of its notation between two rules of dashes "
               "(【テキスト中に現れる記号について】《》：ルビ, ｜, ［＃］ …) — the format's apparatus, the same in every book, "
               "not the novel; the title and author above it stay.",
         status="LOCK", source="corpus: 青空文庫 こころ (夏目漱石) — its header, as every 青空文庫 file carries one",
         refs=("F3", "JA-TXT-027", "JA-TXT-030", "tests/test_text_conventions.py"),
         note="Found building F3: the legend is the same format's front matter as the colophon is its back matter."),

    # === SPL: sentence splitting (B) ============================================================================= #
    # --- quotations ---------------------------------------------------------------------------------------------- #
    Case(id="JA-SPL-001", lang="ja", layer="text", category="B",
         text="「まあ！」と、うばは　びっくりしました。\n", span="",
         expect={"sentences": ["「まあ！」と、うばは　びっくりしました。"]},
         basis="！ inside a quotation closed by 」と ends the quote, not the sentence (quotative と continues it); "
               "the quote used to be cut off and the rest started with と. Same: 彼は「待て！」と叫んだ。",
         status="LOCK", decision="QUOTE-SPANS", source="corpus: aozora/aozora_0001.txt",
         refs=("Parsing_Robustness_Suite_Scope.md §2 B", "debug/parsing_suite/ja_tokens P01",
               "debug/parsing_suite/known SD-28", "F4 (analyzer._sentence_ends)")),
    Case(id="JA-SPL-003", lang="ja", layer="text", category="B",
         text="本当に？と聞いた。\n", span="",
         expect={"sentences": ["本当に？と聞いた。"]},
         basis="A quotation without brackets: ？ followed by the quotative と is the quoted question, and the "
               "sentence goes on to its verb (a quoted question or exclamation keeps its mark before と).",
         status="LOCK",
         refs=("debug/parsing_suite/known SD-28", "F4 (analyzer._sentence_ends)")),
    Case(id="JA-SPL-004", lang="ja", layer="text", category="B",
         text="「今日は晴れ。明日は雨」と言った。\n", span="",
         expect={"sentences": ["「今日は晴れ。明日は雨」と言った。"]},
         basis="Two sentences quoted as the object of one verb: kept whole, since と follows the closing bracket "
               "(the user, 2026-09-27, decision 6).",
         status="LOCK", decision="QUOTE-SPANS",
         refs=("debug/parsing_suite/ja_tokens P02", "F4 (analyzer._sentence_ends)")),
    Case(id="JA-SPL-005", lang="ja", layer="text", category="B",
         text="『吾輩は猫である。名前はまだ無い。』で始まる小説を読んだ。\n", span="",
         expect={"sentences": ["『吾輩は猫である。名前はまだ無い。』で始まる小説を読んだ。"]},
         basis="As JA-SPL-004 with 『』 quoting a book's opening, the particle で after the closing bracket: the "
               "quotation is a noun phrase of the sentence (what the novel begins with), and a particle can't begin "
               "a sentence — one sentence (the user, 2026-09-27: QUOTE-SPANS-PARTICLES). Before: 『吾輩は猫である。 "
               "/ 名前はまだ無い。』 / で始まる小説を読んだ。",
         status="LOCK", decision="QUOTE-SPANS-PARTICLES", refs=("F4 (analyzer._takes_quotation)",)),
    Case(id="JA-SPL-006", lang="ja", layer="text", category="B",
         text="そうです。」「うーん、よくわからないから、マインに任せるよ」\n", span="",
         expect={"contains": ["そうです。」", "「うーん、よくわからないから、マインに任せるよ」"], "not_contains": ["」「"]},
         basis="A closing 」 after a sentence's 。 belongs to that sentence, never to the next one (UAX #29 SB9).",
         status="LOCK",
         refs=("tests/test_context_prioritization.py::test_japanese_quotation_cleanup",
               "debug/parsing_suite/known RL-9")),
    Case(id="JA-SPL-007", lang="ja", layer="text", category="B",
         text="「行くぞ。」次だ。\n", span="",
         expect={"sentences": ["「行くぞ。」", "次だ。"]},
         basis="Closing punctuation after a terminator stays with its sentence (Unicode UAX #29, SB9: ATerm/STerm "
               "Close* ×); the 」 used to be dropped, leaving 「行くぞ。 open. A noun after the bracket (次) is no "
               "quotative: two sentences (decision 6).",
         status="LOCK", decision="QUOTE-SPANS",
         refs=("debug/parsing_suite/known RL-9", "F4 (analyzer._sentence_ends)")),

    # --- terminators --------------------------------------------------------------------------------------------- #
    Case(id="JA-SPL-008", lang="ja", layer="text", category="B",
         text=srt("(鵯州)反応は!? 何色だ？"), span="!?",
         expect={"sentences": ["反応は!?", "何色だ？"]},
         basis="A run of terminators ends a sentence together (UAX #29 SB8a: no break between terminators): the ? "
               "after ! used to be cut off and dropped as debris, so the question read as 反応は!. 1,561 .srt cues "
               "in the library hold !? or ！？.",
         status="LOCK", source="library: Bleach - 138.srt", ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/ja_tokens P06", "debug/parsing_suite/known RL-8", "F4 (analyzer._sentence_ends)")),
    Case(id="JA-SPL-009", lang="ja", layer="text", category="B",
         text=srt("えっ！？　これで終わり？"), span="！？",
         expect={"sentences": ["えっ！？", "これで終わり？"]},
         basis="As JA-SPL-008 in full-width: ！？ is one mark (感嘆疑問符); it used to read えっ！.",
         status="LOCK", source="library: Bleach - 166.srt", ctx={"ext": ".srt"},
         refs=("F4 (analyzer._sentence_ends)",)),
    Case(id="JA-SPL-010", lang="ja", layer="text", category="B",
         text="「…………」\n思わず須藤の頭を叩きたくなったが、そこは精神的に大人のオレが我慢して耐えた。\n", span="「…………」",
         expect={"sentences": ["思わず須藤の頭を叩きたくなったが、そこは精神的に大人のオレが我慢して耐えた。"]},
         basis="A line of punctuation alone — a silent reply; 「…………」 alone is 155 lines of the library's novels — "
               "holds no word: no sentence, as with the lone ? that !? leaves.",
         status="LOCK", source="library: ようこそ実力至上主義の教室へ3_02.txt",
         refs=("tests/test_subtitle_sentence_splitting.py::test_punctuation_only_fragments_are_not_emitted",
               "debug/parsing_suite/known RL-8")),
    Case(id="JA-SPL-011", lang="ja", layer="text", category="B",
         text="これはペンである．あれは本である．\n", span="．",
         expect={"sentences": ["これはペンである．", "あれは本である．"]},
         basis="．(U+FF0E) is the full stop of horizontal technical and official Japanese (the 公用文 ．，style) — a "
               "sentence terminator (UAX #29 ATerm); it was not in the ja boundary set (a required one since F4).",
         status="LOCK",
         refs=("debug/parsing_suite/ja_tokens P03", "debug/parsing_suite/known RL-11",
               "F4 (settings_manager.DEFAULT_SETTINGS)")),
    Case(id="JA-SPL-012", lang="ja", layer="text", category="B",
         text=srt("これはペンです．", "あれは本だ"), span="．",
         expect={"sentences": ["これはペンです．", "あれは本だ。"]},
         basis="close_cue takes ． as a cue's terminator; while ． was no boundary, the two cues ran together into "
               "one sentence.",
         status="LOCK", ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/known RL-11", "F4 (settings_manager.DEFAULT_SETTINGS)")),
    Case(id="JA-SPL-013", lang="ja", layer="text", category="B",
         text="3.14は円周率。\n３．１４は円周率。\n", span="",
         expect={"sentences": ["3.14は円周率。", "３．１４は円周率。"]},
         basis="A point between digits is a decimal point, not a full stop (UAX #29 SB6: ATerm × Numeric) — the "
               "guard for making ． a boundary.",
         status="LOCK",
         refs=("debug/parsing_suite/ja_tokens P11",)),
    Case(id="JA-SPL-014", lang="ja", layer="text", category="B",
         text="そうか…じゃあ行くか。\nえっと‥わかった。\n", span="…",
         expect={"sentences": ["そうか…じゃあ行くか。", "えっと‥わかった。"]},
         basis="An ellipsis inside a line is as often a pause as an end (あの…すみません): no sentence end — the "
               "user, 2026-09-27, decision 5 (expect was the split side while it was open).",
         status="LOCK", decision="JA-ELLIPSIS",
         refs=("debug/parsing_suite/ja_tokens P04", "debug/parsing_suite/known RL-10")),
    Case(id="JA-SPL-015", lang="ja", layer="text", category="B",
         text=srt("ウウ…", "（恋次）ハッ…"), span="",
         expect={"sentences": ["ウウ…", "ハッ…"]},
         basis="A cue that ends in … has ended — the subtitle's own mark, on its own timing — yet … is no "
               "terminator in running text (JA-ELLIPSIS): close_cue added 。, so 12,530 .srt cues in the library "
               "became …。 sentences; the cue's end is now a line break and the sentence reads as the file does.",
         status="LOCK", decision="CUE-CLOSES", source="library: Bleach - 161.srt", ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/known RS-7", "F4 (analyzer.close_cue)")),
    Case(id="JA-SPL-016", lang="ja", layer="text", category="B",
         text=srt("お前に話がある｡", "反応です！", "わかった"), span="",
         expect={"sentences": ["お前に話がある｡", "反応です！", "わかった。"]},
         basis="｡ (half-width, anime subtitles' full stop) ends a sentence and a cue already ending in a terminator "
               "is not given another; a cue that ends with no mark is closed with 。.",
         status="LOCK", decision="CUE-CLOSES", ctx={"ext": ".srt"},
         refs=("tests/test_subtitle_sentence_splitting.py"
               "::test_a_cue_already_ending_in_halfwidth_is_not_double_terminated",
               "tests/test_subtitle_sentence_splitting.py::test_halfwidth_full_stop_is_a_boundary",
               "debug/parsing_suite/ja_tokens P05", "debug/parsing_suite/known RL-2, RL-4")),
    Case(id="JA-SPL-017", lang="ja", layer="text", category="B",
         text="我々の最終目的は➡。藍染との決戦だ｡力を発揮できる者がいるなら➡。\n", span="",
         expect={"contains": ["藍染との決戦だ｡"], "not_contains": ["決戦だ｡力"]},
         basis="A terminator glued to a symbol (➡。 is one token) still ends the sentence.",
         status="LOCK",
         refs=("tests/test_subtitle_sentence_splitting.py::test_a_terminator_glued_to_a_symbol_still_splits",
               "debug/parsing_suite/known RL-3")),

    # --- subtitle cues ------------------------------------------------------------------------------------------- #
    Case(id="JA-SPL-018", lang="ja", layer="text", category="B",
         text=srt("残された わずかな時間で\n少しでも 己の力をあげるために➡", "過酷な修行に 挑んでいた｡"), span="➡",
         expect={"contains": ["わずかな時間で少しでも", "あげるために過酷な修行に"], "not_contains": ["➡", "｡。"]},
         basis="A cue's two lines are one caption, and ➡ says the sentence runs into the next cue: one sentence.",
         status="LOCK", decision="CUE-CLOSES", ctx={"ext": ".srt"},
         refs=("tests/test_subtitle_sentence_splitting.py::test_a_continuation_arrow_joins_the_next_cue",
               "tests/test_subtitle_sentence_splitting.py::test_a_real_subtitle_splits_into_readable_sentences",
               "debug/parsing_suite/known RL-5")),
    Case(id="JA-SPL-019", lang="ja", layer="text", category="B",
         text=srt("（二乃(にの)）あんたみたいなえたいの知れない男を―", "招き入れるなんてどうかしてるわ。",
                  "（四葉(よつば)）水の分量は―", "フィーリング！"), span="―",
         expect={"sentences": ["あんたみたいなえたいの知れない男を招き入れるなんてどうかしてるわ。", "水の分量はフィーリング！"]},
         basis="Netflix's trailing ― means the sentence continues in the next cue (its arrow); labels go.",
         status="LOCK", decision="CUE-CLOSES", ctx={"ext": ".srt"},
         refs=("tests/test_subtitle_sentence_splitting.py::test_a_netflix_shaped_subtitle_joins_across_dashes",
               "debug/parsing_suite/known RL-6")),
    Case(id="JA-SPL-020", lang="ja", layer="text", category="B",
         text=srt("せっかく作ってもらったのに――", "食べられなかった。", "連絡してくれたら ―", "迎えに行ったのに。", "―",
                  "本当に。", "もらったのに―➡", "悪いね。"), span="",
         expect={"sentences": ["せっかく作ってもらったのに食べられなかった。", "連絡してくれたら迎えに行ったのに。", "本当に。",
                               "もらったのに悪いね。"]},
         basis="Repeated, spaced and mixed continuation marks all continue; a cue that is only a dash says nothing.",
         status="LOCK", decision="CUE-CLOSES", ctx={"ext": ".srt"},
         refs=("tests/test_subtitle_sentence_splitting.py::test_repeated_trailing_dashes_are_all_stripped",
               "tests/test_subtitle_sentence_splitting.py::test_a_cue_that_is_only_a_dash_produces_nothing")),
    Case(id="JA-SPL-021", lang="ja", layer="text", category="B",
         text=srt("―そうだね", "そう―だね"), span="―",
         expect={"sentences": ["―そうだね。", "そう―だね。"]},
         basis="Only a dash at a cue's end continues; a leading or mid-line dash is part of the line.",
         status="LOCK", decision="CUE-CLOSES", ctx={"ext": ".srt"},
         refs=("tests/test_subtitle_sentence_splitting.py::test_a_leading_dash_is_not_a_continuation",
               "debug/parsing_suite/known RL-7")),
    Case(id="JA-SPL-022", lang="ja", layer="text", category="B",
         text=ass("そうだ 女｡ お前に話がある｡", "我々の最終目的は➡", "藍染との決戦だ｡"), span="➡",
         expect={"contains": ["我々の最終目的は藍染との決戦だ｡", "お前に話がある｡"], "not_contains": ["➡"]},
         basis="An .ass file's events are cues like an .srt's: ｡ ends, ➡ continues.",
         status="LOCK", decision="CUE-CLOSES", ctx={"ext": ".ass"},
         refs=("tests/test_subtitle_sentence_splitting.py::test_ass_subtitles_get_the_same_treatment",)),
    Case(id="JA-SPL-023", lang="ja", layer="text", category="B",
         text=_YOMI_VOICE_OVER, span="➨",
         expect={"contains": ["運命の双子に生まれたのは自分で選んだ道じゃ"], "not_contains": ["➨"]},
         basis="➨ (U+27A8) is these captions' continuation arrow, like ➡; unknown to close_cue, it was kept and the "
               "cue closed mid-clause with 。 (35 sentences in this file alone).",
         status="LOCK", decision="CUE-CLOSES", source="library: [SubsPlease] Yomi no Tsugai - 13 (1080p).ja.ass",
         ctx={"ext": ".ass"},
         refs=("debug/parsing_suite/ja_tokens T04", "F4 (analyzer._CUE_CONTINUATIONS)")),
    Case(id="JA-SPL-024", lang="ja", layer="text", category="B",
         text=_ass_events(
             ("0:06:51.92", "0:06:55.90", "{\\pos(232,497)}睨まれている状態ですから{\\fscx50}。"),
             ("0:06:55.90", "0:07:00.13", "{\\pos(212,437)\\c&H0000FFFF}《ハッセは領主への反逆罪で"),
             ("0:06:55.90", "0:07:00.13", "{\\pos(252,497)\\c&H0000FFFF}罰を与えられた》"),
             ("0:07:00.13", "0:07:02.60", "{\\pos(192,497)\\c&H0000FFFF}《祈念式を行えなかったため➡"),
             ("0:07:02.60", "0:07:05.24", "{\\pos(192,497)\\c&H0000FFFF}収穫は不作に終わったそうだ》")),
         span="反逆罪で",
         expect={"contains": ["ハッセは領主への反逆罪で罰を与えられた", "祈念式を行えなかったため収穫は不作に終わったそうだ"],
                 "not_contains": ["反逆罪で。"]},
         basis="Two events with one start and end are the two lines of one caption (the file's own timing): read as "
               "one cue, like an .srt cue's two lines — not two cues each closed with 。. (The adversary filed it as "
               "a limitation; the shared timing is the rule.)",
         status="LOCK", decision="CUE-CLOSES", source="library: [SubsPlease] Honzuki no Gekokujou S4 - 21 (1080p).ja.ass",
         ctx={"ext": ".ass"},
         refs=("debug/parsing_suite/ja_tokens P10", "F4 (analyzer._captions)")),
    Case(id="JA-SPL-025", lang="ja", layer="text", category="B",
         text=srt("（ナレーション） 藍染(あいぜん)に連れ去られた 織姫(おりひめ)を救うために",
                  "虚圏(ウェコムンド)に乗り込んだ一護(いちご)たちは", "破面(アランカル)の本拠地 虚夜宮(ラス･ノーチェス)に突入した"),
         span="",
         expect={"sentences": ["藍染に連れ去られた織姫を救うために虚圏に乗り込んだ一護たちは破面の本拠地虚夜宮に突入した。"]},
         basis="One narrated sentence broken over three cues with no continuation mark; each cue is closed with 。 "
               "(…救うために。 / …一護たちは。).",
         status="LIMIT", decision="CUE-CLOSES", source="library: Bleach - 161.srt", ctx={"ext": ".srt"},
         refs=("debug/parsing_suite/ja_tokens P10",)),

    # --- line breaks, prose, transcripts ------------------------------------------------------------------------- #
    Case(id="JA-SPL-002", lang="ja", layer="text", category="B",
         text="今日は晴れ。\r\n明日は雨。", span="",
         expect={"sentences": ["今日は晴れ。", "明日は雨。"]},
         basis="Windows line ends (CRLF) split like LF, and no \\r survives into a sentence.",
         status="LOCK", source="constructed",
         refs=("debug/parsing_suite/ja_tokens P09", "debug/parsing_suite/known RL-105, SD-36")),
    Case(id="JA-SPL-026", lang="ja", layer="text", category="B",
         text=_youtube("動画タイトル", "チャンネル | 2024 | 10:00", "AIを賢く使う人が増えている。", kind="ja (auto)",
                       url="https://www.youtube.com/watch?v=J0dSAhzWM6A"), span="",
         expect={"contains": ["AIを賢く使う人が増えている。"], "not_contains": ["v=", "----", "http"]},
         basis="A header line never merges into the body's first sentence: each line ends its sentence.",
         status="LOCK", decision="LINE-BREAK-BOUNDARY",
         refs=("tests/test_sentence_splitting.py::test_transcript_header_does_not_merge_into_body_sentence",
               "debug/parsing_suite/known RL-1")),
    Case(id="JA-SPL-027", lang="ja", layer="text", category="B",
         text="猫が寝ている\n犬が走っている\n", span="",
         expect={"sentences": ["猫が寝ている", "犬が走っている"]},
         basis="Caption lines with no punctuation are separate sentences, not one.",
         status="LOCK", decision="LINE-BREAK-BOUNDARY",
         refs=("tests/test_sentence_splitting.py::test_plain_newlines_split_lines_into_separate_sentences",
               "debug/parsing_suite/known RL-1")),
    Case(id="JA-SPL-028", lang="ja", layer="text", category="B",
         text="彼は新幹\n線に乗った。\n", span="",
         expect={"sentences": ["彼は新幹線に乗った。"]},
         basis="A hard-wrapped line cuts one sentence — here one word, 新幹線 — in two.",
         status="LIMIT", decision="LINE-BREAK-BOUNDARY",
         refs=("debug/parsing_suite/ja_tokens P08",)),
    Case(id="JA-SPL-029", lang="ja", layer="text", category="B",
         text="少年は静かに扉を開けた。廊下には誰もいなかった。秘密の部屋が待っていた。", ctx={"ext": ".txt"}, span="",
         expect={"sentences": ["少年は静かに扉を開けた。", "廊下には誰もいなかった。", "秘密の部屋が待っていた。"]},
         basis="Prose splits at its 。 — nothing the subtitle rules do reaches a book.",
         status="LOCK",
         refs=("tests/test_subtitle_sentence_splitting.py::test_plain_prose_is_unaffected",)),
    Case(id="JA-SPL-030", lang="ja", layer="text", category="B",
         text="今日は天気がいいので 公園に行きました そのあと カフェで休みました\n", span="",
         expect={"sentences": ["今日は天気がいいので公園に行きました", "そのあとカフェで休みました"]},
         basis="Two sentences the speaker ended; auto-captions write no 。 and the cues are joined by spaces.",
         status="LIMIT", decision="READ-AS-WRITTEN",
         refs=("debug/parsing_suite/ja_tokens T13",)),
    Case(id="JA-SPL-031", lang="ja", layer="text", category="B",
         text="マジかｗ次行こう\n", span="ｗ",
         expect={"sentences": ["マジかｗ", "次行こう"]},
         basis="SNS text ends a sentence with ｗ (or an emoji) instead of 。.",
         status="LIMIT", decision="READ-AS-WRITTEN",
         refs=("debug/parsing_suite/ja_tokens P07",)),
    Case(id="JA-SPL-032", lang="ja", layer="text", category="B",
         text="YouTube の Harry Potter を見た。\n", span="Harry Potter",
         expect={"sentences": ["YouTube の Harry Potter を見た。"]},
         basis="The sentence as written keeps its spaces; it is rebuilt from tokens, and MeCab's ASCII spaces are no "
               "tokens (subtitles too: そうだ 女｡ → そうだ女｡).",
         status="LIMIT", decision="SENTENCE-FROM-TOKENS",
         refs=("debug/parsing_suite/ja_tokens P12", "debug/parsing_suite/known RL-35")),

    # --- F4's rules at their edges (2026-09-27) ------------------------------------------------------------------ #
    Case(id="JA-SPL-033", lang="ja", layer="text", category="B",
         text="「行くぞ。」走り出した。\n", span="",
         expect={"sentences": ["「行くぞ。」走り出した。"]},
         basis="A verb right after a quotation's closing bracket takes it as its quote, と left out as fiction "
               "writes it (「うん」頷いた): one sentence — decision 6 names the verb with と / って.",
         status="LOCK", decision="QUOTE-SPANS", refs=("F4 (analyzer._sentence_ends)",)),
    Case(id="JA-SPL-034", lang="ja", layer="text", category="B",
         text="「はい。」彼女は頷いた。\n", span="",
         expect={"sentences": ["「はい。」", "彼女は頷いた。"]},
         basis="A quotation followed by a new subject (彼女は) is a sentence of its own: only a particle or a verb "
               "joins what follows (decision 6, QUOTE-SPANS-PARTICLES); the 」 stays with the sentence it closes "
               "(UAX #29 SB9).",
         status="LOCK", decision="QUOTE-SPANS", refs=("F4 (analyzer._sentence_ends)",)),
    Case(id="JA-SPL-035", lang="ja", layer="text", category="B",
         text="「今日は晴れ。明日は雨。」\n", span="",
         expect={"sentences": ["「今日は晴れ。", "明日は雨。」"]},
         basis="A quotation of two sentences that nothing takes as a quote (a line of dialogue) splits at its inner "
               "。 (decision 6), the closing bracket with the sentence it closes (UAX #29 SB9).",
         status="LOCK", decision="QUOTE-SPANS", refs=("F4 (analyzer._sentence_ends)",)),
    Case(id="JA-SPL-036", lang="ja", layer="text", category="B",
         text="「今日は晴れ。\n明日は雨。」と彼は言った。\n", span="",
         expect={"sentences": ["「今日は晴れ。", "明日は雨。」と彼は言った。"]},
         basis="A quotation that began on an earlier line (a novel's speech over two lines): its closing bracket, "
               "followed by と, keeps the rest of its line one sentence; the line break still ends the first "
               "(LINE-BREAK-BOUNDARY).",
         status="LOCK", decision="QUOTE-SPANS", refs=("F4 (analyzer._sentence_ends)",)),
    Case(id="JA-SPL-037", lang="ja", layer="text", category="B",
         text="本当？って聞いた。えっ!?って感じだった。\n", span="って",
         expect={"sentences": ["本当？って聞いた。", "えっ!?って感じだった。"]},
         basis="The colloquial quotative って after a quoted question or exclamation, as と (JA-SPL-003): the "
               "sentence goes on to its verb.",
         status="LOCK", refs=("F4 (analyzer._sentence_ends)",)),
    Case(id="JA-SPL-038", lang="ja", layer="text", category="B",
         text="ドアを開けた。と、そこには誰もいなかった。\n", span="と",
         expect={"sentences": ["ドアを開けた。", "と、そこには誰もいなかった。"]},
         basis="After a full stop, と、 is the conjunction 'and then' opening a sentence — a quoted sentence drops "
               "its 。 before the quotative と (わかったと言った) — so the sentence ends at 。. UniDic tags this と "
               "格助詞 too: the full stop tells them apart.",
         status="LOCK", refs=("F4 (analyzer._sentence_ends)",)),
    Case(id="JA-SPL-039", lang="ja", layer="text", category="B",
         text="Ｍｒ．Ｓｍｉｔｈは３．１４倍速い．次の問題へ進む．\n", span="．",
         expect={"sentences": ["Ｍｒ．Ｓｍｉｔｈは３．１４倍速い．", "次の問題へ進む．"]},
         basis="A full stop followed at once by a Latin letter or a digit is an abbreviation's or a decimal point "
               "(UAX #29 SB6–SB8: Ｍｒ．Ｓｍｉｔｈ, ３．１４), not a sentence end — the guard that lets ． end sentences.",
         status="LOCK", refs=("F4 (analyzer._terminates)",)),
    Case(id="JA-SPL-040", lang="ja", layer="text", category="B",
         text=srt("今日は、", "晴れです"), span="、",
         expect={"sentences": ["今日は、晴れです。"]},
         basis="A cue ending in 、 has not ended: the comma is a pause inside the sentence (UAX #29 SContinue), so "
               "it runs on into the next cue, the comma kept — close_cue made it 今日は、。",
         status="LOCK", decision="CUE-CLOSES", ctx={"ext": ".srt"}, refs=("F4 (analyzer.close_cue)",)),
    Case(id="JA-SPL-041", lang="ja", layer="text", category="B",
         text=srt("「行くぞ。」", "「そうか…」", "行こう"), span="",
         expect={"sentences": ["「行くぞ。」", "「そうか…」", "行こう。"]},
         basis="A cue's terminator is found past its closing bracket: 「行くぞ。」 has ended and gains no second 。 "
               "(it read 「行くぞ。」。), and 「そうか…」 has ended on its ellipsis, gaining none (JA-ELLIPSIS).",
         status="LOCK", decision="CUE-CLOSES", ctx={"ext": ".srt"}, refs=("F4 (analyzer.close_cue)",)),
    Case(id="JA-SPL-042", lang="ja", layer="text", category="B",
         text=_SRT_TWO_SPEAKERS, span="フフフフ…",
         expect={"sentences": ["あれはてめえが薬を…", "あれはてめえが薬を…", "フフフフ…"]},
         basis="An .srt cue is its own caption (SubRip's unit): two cues with one timing are two captions on screen "
               "at once — here two speakers, 風太郎 and 二乃 — never one sentence. The one-timing rule is .ass's, "
               "whose broadcast captions write a caption's lines as events (JA-SPL-024).",
         status="LOCK", decision="CUE-CLOSES", source="doc: samples/ja/HighPriority/H_priority_sample_2.srt",
         ctx={"ext": ".srt"}, refs=("F4 (analyzer._captions)",)),

    # --- QUOTE-SPANS-PARTICLES (the user, 2026-09-27): a particle after the closing bracket --------------------- #
    Case(id="JA-SPL-043", lang="ja", layer="text", category="B",
         text="「今日は晴れ。明日は雨。」が彼の口癖だ。\n", span="」が",
         expect={"sentences": ["「今日は晴れ。明日は雨。」が彼の口癖だ。"]},
         basis="The quotation is the subject of 口癖だ, marked by the case particle が: one sentence, like "
               "JA-SPL-005's で — a particle can't begin a Japanese sentence.",
         status="LOCK", decision="QUOTE-SPANS-PARTICLES", refs=("F4 (analyzer._takes_quotation)",)),
    Case(id="JA-SPL-044", lang="ja", layer="text", category="B",
         text="「行くぞ。」の一言で、皆が走り出した。\n", span="」の",
         expect={"sentences": ["「行くぞ。」の一言で、皆が走り出した。"]},
         basis="The quotation modifies 一言 through the particle の: one sentence (QUOTE-SPANS-PARTICLES).",
         status="LOCK", decision="QUOTE-SPANS-PARTICLES", refs=("F4 (analyzer._takes_quotation)",)),
    Case(id="JA-SPL-045", lang="ja", layer="text", category="B",
         text="「やめて。」「いやだ。」と言い合った。\n", span="」「",
         expect={"sentences": ["「やめて。」「いやだ。」と言い合った。"]},
         basis="Two quotations in a row, both taken by と言い合った: one sentence by the grammar. Decisions 6 and "
               "QUOTE-SPANS-PARTICLES look only at the word right after a closing bracket, and here that is another "
               "quotation — so the first still splits off: 「やめて。」 / 「いやだ。」と言い合った。",
         status="LOCK", decision="QUOTE-SPANS",
         note="Found 2026-09-27 building QUOTE-SPANS-PARTICLES. Built 2026-09-28 (lane RC1): a run of quotations is "
              "taken by what follows the last; the user, 2026-09-29, took the lean (QUOTE-SPANS)."),
    Case(id="JA-SPL-046", lang="ja", layer="text", category="B",
         text="「はい。」、と彼は言った。\n", span="」、と",
         expect={"sentences": ["「はい。」、と彼は言った。"]},
         basis="A comma after a sentence's closing mark continues the sentence (Unicode UAX #29 SB8a: STerm Close* "
               "Sp* × SContinue — 、 is SContinue), and と takes the quotation: one sentence. Today: 「はい。」 / "
               "、と彼は言った。 — _sentence_ends looks past closing marks and spaces only.",
         status="LOCK", decision="QUOTE-SPANS",
         note="Found 2026-09-27 building QUOTE-SPANS-PARTICLES. Built 2026-09-28 (lane RC1): SContinue after the "
              "closing marks continues the sentence (QUOTE-SPANS, decided 2026-09-29)."),

    # === ENC: encodings (A) ====================================================================================== #
    Case(id="JA-ENC-001", lang="ja", layer="text", category="A",
         text=srt("そこのドアを開けてくれ。"), ctx={"ext": ".srt", "encoding": "cp932"}, span="",
         expect={"sentences": ["そこのドアを開けてくれ。"]},
         basis="Shift_JIS (CP932) is the legacy Japanese encoding of many subtitle files: pysrt reads it as UTF-8, "
               "fails, and the whole file silently contributes nothing.",
         status="LOCK",
         refs=("debug/parsing_suite/known RL-102", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-002", lang="ja", layer="text", category="A",
         text="すると先生は昨日と違って、一種の弧線を描いて、妙な方向から岸の方へ帰り始めた。\n",
         ctx={"encoding": "cp932"}, span="",
         expect={"sentences": ["すると先生は昨日と違って、一種の弧線を描いて、妙な方向から岸の方へ帰り始めた。"]},
         basis="Aozora Bunko distributes its texts in Shift_JIS: read as UTF-8 with errors ignored, the Japanese is "
               "destroyed and the file contributes nothing, silently.",
         status="LOCK", source="library: こころ_02.txt (re-encoded as Aozora Bunko ships it)",
         refs=("debug/parsing_suite/known RL-103", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-003", lang="ja", layer="text", category="A",
         text="すると先生は昨日と違って、一種の弧線を描いて、妙な方向から岸の方へ帰り始めた。\n",
         ctx={"encoding": "utf-16"}, span="",
         expect={"sentences": ["すると先生は昨日と違って、一種の弧線を描いて、妙な方向から岸の方へ帰り始めた。"]},
         basis="UTF-16 with its BOM (Windows Notepad's 'Unicode') names its own encoding; read as UTF-8 it yields "
               "nothing.",
         status="LOCK", source="library: こころ_02.txt (re-encoded)",
         refs=("debug/parsing_suite/known RL-103", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-004", lang="ja", layer="text", category="A",
         text=srt("そこのドアを開けてくれ。"), ctx={"ext": ".srt", "encoding": "utf-16"}, span="",
         expect={"sentences": ["そこのドアを開けてくれ。"]},
         basis="A UTF-16 subtitle with its BOM is read (pysrt follows the BOM) — the path the .txt and .ass readers "
               "lack.",
         status="LOCK",
         refs=("debug/parsing_suite/known RL-102",)),
    Case(id="JA-ENC-005", lang="ja", layer="text", category="A",
         text=ass("本当にそう思うの。"), ctx={"ext": ".ass", "encoding": "cp932"}, span="",
         expect={"sentences": ["本当にそう思うの。"]},
         basis="As JA-ENC-001 for .ass (read as UTF-8, errors ignored): a CP932 or UTF-16 .ass contributes nothing.",
         status="LOCK",
         refs=("debug/parsing_suite/known RL-102, RL-103", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-006", lang="ja", layer="text", category="A",
         text=("プロローグ\r\n\r\n\r\n「ギルベルタ商会でマインがとうとう倒れたらしい。部屋の準備と魔術具を」\r\n"
               "商業ギルドにいる祖父からの急使が馬を走らせてきて、そう言った。\r\n"),
         ctx={"encoding": "utf-8-sig"}, span="プロローグ",
         expect={"contains": ["プロローグ"], "not_contains": ["﻿"]},
         basis="A UTF-8 BOM marks the encoding, it is no character of the text; a .txt is read as utf-8, not "
               "utf-8-sig, so the first sentence carries it (29 .txt files in the library).",
         status="LOCK", source="library: HonZukiV3_1.txt",
         refs=("debug/parsing_suite/ja_tokens T21", "debug/parsing_suite/known HX-16",
               "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-007", lang="ja", layer="text", category="A",
         text=srt("（三玖(みく)）本当にそう思うの。"), ctx={"ext": ".srt", "encoding": "utf-8-sig"}, span="",
         expect={"sentences": ["本当にそう思うの。"]},
         basis="A Windows-authored subtitle — BOM and CRLF — reads like any other.",
         status="LOCK",
         refs=("tests/test_speaker_label_stripping.py::test_crlf_and_bom_subtitles_are_handled",
               "debug/parsing_suite/known RL-105")),
    Case(id="JA-ENC-008", lang="ja", layer="known", category="A",
         text="", ctx={"ignore": "﻿一人\r\n彼\r\n"}, span="",
         expect={"known": ["一人|ヒトリ", "彼|カレ"]},
         basis="An ignore list saved with a BOM (Notepad) whose first line is a word: the BOM is not part of the "
               "word, yet the list is read as utf-8 and its first entry never matches. The user's lists all carry "
               "a BOM and start with a # comment, which is what hides it.",
         status="LOCK", source="library: User Files/ja/Blacklist.txt (its first entries, the comment removed)",
         refs=("debug/parsing_suite/known HX-16", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-009", lang="ja", layer="known", category="A",
         text="", ctx={"ignore": "﻿# ja Blacklist\r\n一人\r\n彼\r\n"}, span="",
         expect={"known": ["一人|ヒトリ", "彼|カレ"]},
         basis="The same list as the user keeps it — BOM, then a # comment line — reads every entry.",
         status="LOCK", source="library: User Files/ja/Blacklist.txt",
         refs=("debug/parsing_suite/known HX-16",)),
    # Found with F1 (Parsing_Suite_Findings.md §5): the files the user keeps in User Files/, as an editor saves them.
    Case(id="JA-ENC-010", lang="ja", layer="user_file", category="A",
         text='\ufeff{"words": [{"dictForm": "冒険", "knownStatus": "KNOWN"}, '
              '{"dictForm": "勇者", "knownStatus": "KNOWN"}]}',
         ctx={"name": "KnownWord.json"}, span="",
         expect={"error": "", "has": ["冒険", "勇者"]},
         basis="A BOM marks the encoding, it is no part of the JSON (RFC 8259 §8.1: a parser may ignore it); Notepad's "
               "'UTF-8 with BOM' writes one. json.load refuses it, so load_known_words raises and Generate stops — "
               "the crash Parsing_Fixes_Plan.md names (the Anki sync refuses the file the same way).",
         status="LOCK", refs=("Parsing_Suite_Findings.md §5 F1", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-011", lang="ja", layer="user_file", category="A",
         text='{"words": [{"dictForm": "冒険", "knownStatus": "KNOWN"}, '
              '{"dictForm": "勇者", "knownStatus": "KNOWN"}]}',
         ctx={"name": "KnownWord.json", "encoding": "utf-16"}, span="",
         expect={"error": "", "has": ["冒険", "勇者"]},
         basis="UTF-16 with its BOM (Notepad's 'Unicode') names its own encoding; read as UTF-8 the file raises "
               "(0xFF is no UTF-8 byte) and Generate stops.",
         status="LOCK", refs=("Parsing_Suite_Findings.md §5 F1", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-012", lang="ja", layer="user_file", category="A",
         text="# 覚えなくていい単語\n一人\n彼\n", ctx={"encoding": "utf-16"}, span="",
         expect={"error": "", "has": ["一人", "彼"]},
         basis="An ignore list saved as UTF-16 (Notepad's 'Unicode'): the BOM names the encoding. Read as UTF-8 the list "
               "raises and Generate stops — the Ignore, Black and Graduated lists are all read this way.",
         status="LOCK", refs=("Parsing_Suite_Findings.md §5 F1", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-013", lang="ja", layer="user_file", category="A",
         text="一人\r\n彼\r\n", ctx={"encoding": "cp932"}, span="",
         expect={"error": "", "has": ["一人", "彼"]},
         basis="Notepad's 'ANSI' on Japanese Windows is CP932 (Shift_JIS): read as UTF-8 the list raises and Generate "
               "stops.",
         status="LOCK", source="library: User Files/ja/Blacklist.txt (its first entries, re-encoded)",
         refs=("Parsing_Suite_Findings.md §5 F1", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-014", lang="ja", layer="user_file", category="A",
         text="\ufeffWord,Rank\r\n冒険,1500\r\n勇者,3200\r\n", ctx={"name": "frequency_list_ja_Novel.csv"}, span="",
         expect={"error": "", "has": ["冒険", "勇者"]},
         basis="Excel's 'CSV UTF-8' starts the file with a BOM. Read as utf-8 it sticks to the first header, 'Word' is "
               "never found, every row is skipped and the frequency list loads 0 words — silently (its tier column "
               "says Outside for every word).",
         status="LOCK", refs=("Parsing_Suite_Findings.md §5 F1", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-015", lang="ja", layer="user_file", category="A",
         text="Word,Rank\r\n冒険,1500\r\n勇者,3200\r\n",
         ctx={"name": "frequency_list_ja_Novel.csv", "encoding": "cp932"}, span="",
         expect={"error": "", "has": ["冒険", "勇者"]},
         basis="Japanese Excel's plain 'CSV' is CP932: read as UTF-8 the load fails, a warning is printed and the list "
               "contributes 0 words.",
         status="LOCK", refs=("Parsing_Suite_Findings.md §5 F1", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-016", lang="ja", layer="text", category="A",
         text=ass("本当にそう思うの。"), ctx={"ext": ".ass", "encoding": "utf-16"}, span="",
         expect={"sentences": ["本当にそう思うの。"]},
         basis="As JA-ENC-005 for a UTF-16 .ass (its BOM names the encoding): read as UTF-8 with errors ignored, it "
               "contributes nothing.",
         status="LOCK", refs=("debug/parsing_suite/known RL-102, RL-103", "F1: path_utils.read_text (2026-09-27)")),
    Case(id="JA-ENC-017", lang="ja", layer="text", category="A",
         text="", span="",
         expect={"sentences": []},
         basis="An empty file is no text in any encoding: it contributes nothing and stops nothing.",
         status="LOCK"),
    Case(id="JA-ENC-018", lang="ja", layer="text", category="A",
         text="すると先生は昨日と違って、\r\n一種の弧線を描いた。\n妙な方向から\r岸の方へ帰り始めた。\r\n", span="",
         expect={"contains": ["一種の弧線を描いた。", "岸の方へ帰り始めた。"], "not_contains": ["\r"]},
         basis="CRLF, LF and a lone CR (an old Mac file) all end a line — a file edited on two machines mixes them — "
               "and no \\r reaches a sentence (where a line break ends a sentence is F4's, not this case's).",
         status="LOCK", source="library: こころ_02.txt (line ends mixed)",
         refs=("debug/parsing_suite/known RL-105",)),
    # --- RC1 (2026-09-28): broadcast captions' speakers by colour; a caption's lines ------------------------------- #
    Case(id="JA-TXT-901", lang="ja", layer="text", category="B",
         text=_ass_events(("0:00:05.00", "0:00:07.00", "{\\pos(332,437)\\c&H0000FFFF}え…お父様を？"),
                          ("0:00:05.00", "0:00:07.00", "{\\pos(432,497)}うむ。")), span="",
         expect={"sentences": ["え…お父様を？", "うむ。"]},
         basis="Two events with one timing in two colours are two people speaking: Japanese TV captions (字幕放送) "
               "tell speakers apart by colour (here yellow, then white). One sentence each — before, one caption "
               "joined them: え…お父様を？ うむ。 read as one.",
         status="LOCK", decision="CAPTION-SPEAKERS", ctx={"ext": ".ass"}),
    Case(id="JA-TXT-902", lang="ja", layer="text", category="B",
         text=_ass_events(("0:00:05.00", "0:00:07.00", "{\\pos(500,436)}駅前で待っている"),
                          ("0:00:05.00", "0:00:07.00", "{\\pos(140,496)\\c&H0000FFFF}早く行こう。"),
                          ("0:00:05.00", "0:00:07.00", "{\\pos(520,496)}友達がいるんだ。")), span="",
         expect={"sentences": ["駅前で待っている友達がいるんだ。", "早く行こう。"]},
         basis="Two speakers side by side: one's two lines (white, right) around the other's line (yellow, left) in "
               "the file's order. Each colour is one speaker's caption, read in order — the white lines are one "
               "sentence; before, the yellow line was read inside it.",
         status="LOCK", decision="CAPTION-SPEAKERS", ctx={"ext": ".ass"}),
    Case(id="JA-TXT-903", lang="ja", layer="text", category="B",
         text=_ass_events(("0:00:05.00", "0:00:07.00", "{\\pos(172,437)}その後{\\c&H0000FFFF\\fscx50}　{\\c&H00FFFFFF\\fscx100}会議を"),
                          ("0:00:05.00", "0:00:07.00", "{\\pos(172,497)}開きます。")), span="",
         expect={"sentences": ["その後　会議を開きます。"]},
         basis="A caption's colour is its first visible character's: the broadcast captions colour a narrowed "
               "space now and then (a converter's quirk), which says nothing about who speaks — one sentence.",
         status="LOCK", decision="CAPTION-SPEAKERS", ctx={"ext": ".ass"}),
    Case(id="JA-TXT-904", lang="ja", layer="text", category="A",
         text=srt("行くぞ\nうん"), span="",
         expect={"sentences": ["行くぞうん。"], "words": ["うん", "行く"]},
         basis="A Japanese cue's two lines join with a space the tagger reads as a word boundary — where the "
               "subtitler broke the line — and the sentence shown drops it (the text CSS Text 3 renders).",
         status="LOCK", decision="CUE-LINES", ctx={"ext": ".srt"}),

    # --- RC1 (2026-09-28): quotations in a row; a comma after a closing bracket ------------------------------------ #
    Case(id="JA-SPL-901", lang="ja", layer="text", category="B",
         text="「おはよう。」「おはよう。」と挨拶を交わした。\n", span="」「",
         expect={"sentences": ["「おはよう。」「おはよう。」と挨拶を交わした。"]},
         basis="Quotations in a row, both taken by と: one sentence (as JA-SPL-045).",
         status="LOCK", decision="QUOTE-SPANS"),
    Case(id="JA-SPL-902", lang="ja", layer="text", category="B",
         text="「おはよう。」「おはよう。」\n", span="」「",
         expect={"sentences": ["「おはよう。」", "「おはよう。」"]},
         basis="Two quotations that nothing takes are two lines of dialogue: two sentences.",
         status="LOCK", decision="QUOTE-SPANS"),
    Case(id="JA-SPL-903", lang="ja", layer="text", category="B",
         text="「わかった。」、と彼女は答えた。\n", span="」、と",
         expect={"sentences": ["「わかった。」、と彼女は答えた。"]},
         basis="A comma after a sentence's closing bracket continues the sentence (UAX #29 SB8a, SContinue).",
         status="LOCK", decision="QUOTE-SPANS"),
]

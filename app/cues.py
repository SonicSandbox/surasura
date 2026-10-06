"""A subtitle's cues with their times, and the words in each (P1.3, the Integration Spec §4.3).

The analyzer reads a subtitle as one text and drops its times; Connect needs both — which line a word was said on,
and when — to tell Anki Miner the line to cut a card from. This reads them, by the analyzer's own rules:

- `read(path, language)` -> [Cue]: an .srt's cues and an .ass / .ssa file's Dialogue events in the file's order,
  each with its start and end (milliseconds, as the file writes them) and its text as speech — cleaned exactly as a
  Generate cleans it (`clean_subtitle_text`, `ass_dialogue_text`). A cue holding none of the language's script (an
  English line, a ♪～) is kept but not `counted`, as a Generate never reads it: Anki Miner counts it as a line, so a
  card's lines around one are counted as Anki Miner counts them. Two units are kept (R05-C12): each Cue is the event Anki Miner cuts a card
  from, and `caption` numbers the caption window a Generate reads it in (an .srt's cue is its own; an .ass file's
  events on screen together in one colour are one, `analyzer._captions`). A sung line — karaoke timing, a style the
  subtitler named OP / ED / song, a ♪ — is kept and marked `sung`: a card is never cut from one.
- `tokens(cues, language)` -> [Token]: each cue's words, keyed as every caller keys them — Japanese through
  `JapaneseTokenizer` (so `join_affixes`, the library's name tables, sanitized lemmas), Chinese through
  `ChineseTokenizer` (`chinese_cut` / `chinese_word`, in the `script` asked for) — each with the index of the cue it
  was said in, and `written`: the word as the file writes it (Chinese read in another script is written in the
  file's own). A Japanese token also carries its tagger node (`node`: part of speech, a joined word's parts), for
  the callers that need more than the key.

Standard library only (no pysrt): the times are read here, the text by the analyzer's own functions. Nothing is
written. Haya's E2.2 and Connect's pick (`app/connect/pick.py`) read it.
"""
import bisect
import re
from collections import namedtuple

from app import analyzer, zh_script
from app.path_utils import read_text

# One subtitle line: `index` its place among the cues kept (file order), `start` / `end` milliseconds as the file
# writes them (no offset), `text` the line as speech, `caption` the caption window it belongs to, `sung` a line no
# card is cut from, `counted` whether a Generate reads it (an event in karaoke timing, a line with none of the
# language's script: it reads neither).
Cue = namedtuple("Cue", "index start end text caption sung counted")


class Cues(list):
    """`read`'s answer: the cues, and `joiner` — what a Generate puts between two captions of this file ("" for an
    .srt, " " for an .ass), so `tokens` reads the file's text exactly as a Generate does."""
    joiner = ""

# One word said in a cue: the analyzer's key and spellings (lemma, reading, surface, orth), the index of its cue,
# the sentence it was read in (its text, as the tokenizer yields it), and (Japanese) the tagger's node it was read
# from (None for Chinese), and `written`, the word as the file itself writes it.
Token = namedtuple("Token", "lemma reading surface orth cue sentence node written")

SUBTITLES = (".srt", ".ass", ".ssa")

# SubRip: "00:00:02,419 --> 00:00:03,628" (a full stop is read as the comma is; hours may run past two digits;
# a player's position coordinates may follow).
_SRT_TIMING_RE = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})")
# ASS / SSA: "0:00:02.42" (hundredths).
_ASS_TIME_RE = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?$")
# A style the subtitler named for a song (OP_JP, ED-Romaji, Insert Song, Karaoke): sung, though its lines carry no
# karaoke timing. Only the pick reads this; a Generate still counts the line's words.
_SONG_STYLE_RE = re.compile(r"(?i)(?:^|[^a-z])(?:op|ed|opening|ending|song|karaoke|insert)(?:[^a-z]|$)")
_SONG_MARKS = frozenset("♪♫♬〽")


def _ms(hours, minutes, seconds, fraction):
    fraction = (fraction or "0").ljust(3, "0")[:3]
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(fraction)


def seconds(ms):
    """A cue time in seconds, as Anki Miner's run file takes it (millisecond precision)."""
    return round(ms / 1000.0, 3)


def _sung(text):
    return not _SONG_MARKS.isdisjoint(text)


def _srt(content, language):
    """[(start, end, text, sung, colour)] of an .srt: each cue's lines holding the language's script, cleaned and
    joined as extract_text joins them."""
    out = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.split("\n")
        for at, line in enumerate(lines):
            timing = _SRT_TIMING_RE.search(line)
            if timing:
                break
        else:
            continue
        g = timing.groups()
        kept = [analyzer.clean_subtitle_text(line, language) for line in lines[at + 1:]
                if analyzer.has_target_language(line, language)]
        text = analyzer._join_lines([line for line in kept if line], language)
        if text:
            out.append((_ms(*g[:4]), _ms(*g[4:]), text, _sung(text), None, True))
        else:                   # a line in another script (English, ♪～): no words, but one of the file's lines
            other = " ".join(t for t in (analyzer.clean_subtitle_text(line, language) for line in lines[at + 1:]) if t)
            if other:
                out.append((_ms(*g[:4]), _ms(*g[4:]), other, _sung(other), None, False))
    return out


def _ass_time(value):
    match = _ASS_TIME_RE.match(value.strip())
    if not match:
        return None
    return _ms(*match.groups())             # hundredths: "42" is 420 ms


def _ass(content, language):
    """[(start, end, text, sung, colour)] of an .ass / .ssa file's Dialogue events, read as parse_ass reads them; a
    karaoke event (which a Generate drops) is kept, cleaned of its timing, and marked sung."""
    out, events, fields = [], False, None
    colours, colour_index = {}, 3
    text_index, start_index, end_index, style_index = 9, 1, 2, 3
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line == "[Events]":
            events = True
            continue
        if line.startswith("[") and line.endswith("]"):
            events = False
            continue
        if events and line.startswith("Format:"):
            fields = [f.strip() for f in line[7:].split(",")]
            try:
                text_index = fields.index("Text")
                start_index, end_index = fields.index("Start"), fields.index("End")
                style_index = fields.index("Style")
            except ValueError:
                pass
            continue
        if not events:
            if line.startswith("Format:"):
                styles = [f.strip() for f in line[7:].split(",")]
                if "PrimaryColour" in styles:
                    colour_index = styles.index("PrimaryColour")
            elif line.startswith("Style:"):
                style = line[6:].split(",")
                if len(style) > colour_index:
                    colours[style[0].strip()] = analyzer._ass_colour_value(style[colour_index])
            continue
        if not line.startswith("Dialogue:"):
            continue
        parts = line[len("Dialogue:"):].split(",", text_index)
        if len(parts) <= text_index:
            continue
        raw, style = parts[text_index], parts[style_index].strip()
        start, end = _ass_time(parts[start_index]), _ass_time(parts[end_index])
        if start is None or end is None:
            continue
        karaoke = bool(analyzer._ASS_KARAOKE_RE.search(raw))
        text = analyzer.ass_dialogue_text(analyzer._ASS_BLOCK_RE.sub("", raw) if karaoke else raw, language)
        counted = not karaoke
        if not text:            # a line in another script (a sign in English, ♪～): one of the file's lines all the same
            text = " ".join(analyzer._ASS_BREAK_RE.sub(" ", analyzer._ass_event_text(raw)).replace("\\h", " ").split())
            counted = False
        if text:
            colour = analyzer._ass_colour(raw, colours.get(style, ""), colours)
            out.append((start, end, text, karaoke or bool(_SONG_STYLE_RE.search(style)) or _sung(text), colour,
                        counted))
    return out


def read(path, language="ja"):
    """The cues of the subtitle at `path` (.srt, .ass, .ssa), in the file's order: Cues. Read through
    `path_utils.read_text` (a BOM names the encoding, CRLF and LF alike); a file that isn't a subtitle, or holds no
    line in the language's script, has none."""
    lower = str(path).lower()
    cues = Cues()
    if not lower.endswith(SUBTITLES):
        return cues
    content = read_text(path, language)
    srt = lower.endswith(".srt")
    if not srt:                             # read as a Generate reads it: TV captions cleaned (ENGINE_REVISION 31)
        from app import caption_clean
        content = caption_clean.clean(content, arrows=False)     # arrows kept: "runs on", as a Generate reads
    cues.joiner = "" if srt else " "
    captions, screen, shown = 0, {}, None
    for start, end, text, sung, colour, counted in (_srt if srt else _ass)(content, language):
        # .srt: every cue is its own caption. .ass: the events a Generate reads that are on screen together (one
        # timing) are one caption per colour, in the order each colour first shows (analyzer._captions); an event it
        # never reads (karaoke) is a caption of its own.
        if srt or not counted:      # (a karaoke event, a line in another script)
            caption, captions = captions, captions + 1
        else:
            if (start, end) != shown:
                screen, shown = {}, (start, end)
            if colour not in screen:
                screen[colour], captions = captions, captions + 1
            caption = screen[colour]
        cues.append(Cue(len(cues), start, end, text, caption, sung, counted))
    return cues


def _text(cues, language):
    """The text a Generate reads from `cues` (extract_text / parse_ass: each caption closed, captions joined), and
    where each counted cue starts in it: (text, [(offset, cue index)])."""
    by_caption = {}
    for cue in cues:
        if cue.counted:
            by_caption.setdefault(cue.caption, []).append(cue)
    joiner = getattr(cues, "joiner", "")
    parts, starts, at = [], [], 0
    for caption in sorted(by_caption):
        members = by_caption[caption]
        closed = analyzer.close_cue(analyzer._join_lines([cue.text for cue in members], language))
        if not closed:
            continue
        if parts and joiner:
            parts.append(joiner)
            at += len(joiner)
        inner = 0
        for cue in members:
            found = closed.find(cue.text, inner)
            if found < 0:       # its end changed in closing (an arrow taken off): find what is left of it
                found = closed.find(cue.text.rstrip(analyzer._CUE_CONTINUATIONS).rstrip(), inner)
            found = inner if found < 0 else found
            starts.append((at + found, cue.index))
            inner = found
        parts.append(closed)
        at += len(closed)
    return "".join(parts), starts


def _read(tokenizer, text, language):
    """[(sentence, (lemma, reading, surface, orth), node)] of `text`, as the tokenizer reads it; the node (Japanese)
    found by reading the text once more through `join_affixes` and matching surfaces in order."""
    read = [(sentence, token) for sentence, sentence_tokens in tokenizer.tokenize_sentences(text)
            for token in sentence_tokens]
    if language != "ja":
        return [(sentence, token, None) for sentence, token in read]
    joins = analyzer.affix_joins()
    nodes = [node for line in text.split("\n")
             for node in analyzer.join_affixes(tokenizer.tagger(line), joins, library=tokenizer.library)]
    out, at = [], 0
    for sentence, token in read:
        node = None
        for j in range(at, len(nodes)):
            if nodes[j].surface == token[2]:
                node, at = nodes[j], j + 1
                break
        out.append((sentence, token, node))
    return out


def tokens(cues, language="ja", script="asis", tokenizer=None):
    """Every word said in `cues`, in the file's order: [Token]. The text is read exactly as a Generate reads the file
    (`_text`: the same captions, closed and joined the same way) by the analyzer's tokenizer (`tokenizer`, made here
    when None), so the words are the token store's for the same file; each word is then placed in the cue its text
    stands in. A cue a Generate never reads (karaoke) is read on its own. Japanese tokens also carry their node."""
    if tokenizer is None:
        tokenizer = (analyzer.ChineseTokenizer(script=script) if language == "zh"
                     else analyzer.JapaneseTokenizer())
    out = []
    text, starts = _text(cues, language)
    if starts:
        # Chinese words come out in the script asked for: look for them in the text so written (length-preserving)
        shown = zh_script.convert(text, getattr(tokenizer, "script", "asis")) if language == "zh" else text
        offsets, cursor = [offset for offset, _cue in starts], 0
        for sentence, (lemma, reading, surface, orth), node in _read(tokenizer, text, language):
            found = shown.find(surface, cursor) if surface else -1
            at = cursor if found < 0 else found
            cursor = at + len(surface)
            cue = starts[max(bisect.bisect_right(offsets, at) - 1, 0)][1]
            written = text[at:cursor] if found >= 0 else surface     # conversion keeps length: the file's own spelling
            out.append(Token(lemma, reading, surface, orth, cue, sentence, node, written))
    for cue in cues:
        if not cue.counted and cue.sung:        # a song a Generate never reads: its words, to say they're only sung
            for sentence, (lemma, reading, surface, orth), node in _read(tokenizer, analyzer.close_cue(cue.text),
                                                                         language):
                out.append(Token(lemma, reading, surface, orth, cue.index, sentence, node, surface))
    out.sort(key=lambda token: token.cue)       # stable: each cue's words stay in the order said
    return out

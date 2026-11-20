"""Songs out of the counts (Kotoba-OP, 3.0.17): a show's opening and ending songs, which its subtitles write again every
episode, are left out of a run's counts while `logic.count_song_lyrics` is off (the default).

Measured on a 746-episode library: 17 of 45 shows counted their
songs — 3.4 % of every counted line, up to 13 % of a show's — and lifted a song's 10–20 words into the list's top 500
(59 words in one show). Karaoke timing, the one mark today's reader skipped, was on 29 lines of the whole library: the
songs come as .srt lines with ♬, as .ass events in a style the subtitler names OPJP / jp-ed / Ending, or with no mark
at all.

A sentence of a title's files is a song line when (`left_out`):
  1. its .ass event's style is a song style (`song_style`: OP, ED, Opening, Ending, Insert, Song, Lyrics, Kara,
     Music, 歌, 主题, 片头, 片尾, 插曲 and the joined forms OPJP, EDCN-CHS, jp-ed, ED2-JP, OP - JP), or
  2. it sits in a run of RUN sentences or more (one other sentence between allowed) each in an ordered pair of lines
     (`line_key`: the text without spaces, punctuation and marks) that recurs in `need` of the title's episodes — a
     quarter of them, at least LOW and at most HIGH, or LOW when half the run carries ♪ ♫ ♬ or a song style; or
  3. it carries ♪ and its line is a song line of (1) / (2) elsewhere in the title (the ending sung inside an episode).
Pairs, never lines: えっ？ and はい repeat in every episode of every show. Under the bar stay a flashback, a recap or a
fixed narration repeated in a few episodes; a song sung once (in-story singing) stays as dialogue does. Only the song's
copy goes: the same words said in an episode keep their counts.

An episode is `episode_names.identity`'s (an .srt and an .ass of one episode are one episode), else its file.

Pure: the standard library and `app.unicode_ranges` (no tokenizer, no store, no settings).
"""
import hashlib
import math
import re
from collections import Counter

from app.unicode_ranges import HAN, KANA

LOW, HIGH, SHARE = 3, 6, 0.25      # the episodes a pair recurs in: a quarter of the title's, at least 3, at most 6
RUN, GAP = 4, 1                    # a run: this many sentences or more, one other sentence between allowed

NOTE, STYLED = 1, 2                # a sentence's marks: ♪ in its text; its .ass event's style is a song style

_NOTE_RE = re.compile("[♪♫♬🎵🎶〽]")
_LANG = r"(?:jp|j|jpn|jap|ja|cn|c|chs|cht|sc|tc|chn|zh|rom|romaji|eng|en|kanji|kana)?"
_SONG_STYLE_RE = re.compile(
    r"(?i)(?<![a-z])(?:op|ed|in|ins)\d*" + _LANG + r"\d*(?![a-z])"
    r"|opening|ending|insert|song|lyric|karaoke|kara(?![a-z]*te)|music|theme(?!d)"
    r"|歌|ＯＰ|ＥＤ|主题|片头|片尾|插曲")
_NOT_KEY_RE = re.compile(r"[\s\W_ー～〜]+")
_SCRIPT_RE = re.compile(f"[{KANA}{HAN}]")


def song_style(style):
    """Whether an .ass style's name says song (the module's docstring, 1). A style's name is the subtitler's free text:
    a style named after a character called Ed reads as one."""
    return bool(style) and bool(_SONG_STYLE_RE.search(style))


def plain(text):
    """A text without spaces, punctuation and marks — what a line is, however the file writes it."""
    return _NOT_KEY_RE.sub("", text or "")


def script_len(text):
    """How many Japanese or Chinese characters a text holds — the measure a file's captions and its sentences are
    matched by (`file_lines`): a line with none (WHITE ALBUM, an English line) the tokenizer drops weighs nothing."""
    return len(_SCRIPT_RE.findall(text or ""))


def _key(bare):
    if not bare or not _SCRIPT_RE.search(bare):
        return 0
    return int.from_bytes(hashlib.blake2b(bare.encode("utf-8"), digest_size=6).digest(), "big")


def line_key(text):
    """A sentence's line, the same however a file punctuates, spaces or marks it — a 48-bit number (JSON keeps it
    exact) — or 0 for one with no Japanese or Chinese script (♪～ alone: no line)."""
    return _key(plain(text))


def pack(key, marks=0):
    """One sentence's line as the token store keeps it: its key and its marks in one number (`file_lines`)."""
    return key << 2 | marks


def file_lines(sentences, song_marks=()):
    """A file's `lines` — one number a sentence of `sentences` ([(text, tokens), …]), its key and marks (`pack`: a JSON
    list of plain numbers reads back fast) — what the token store keeps for the rule. `song_marks`: an .ass file's
    captions in the order of its text, [[length, is a song], …] (parse_ass: each caption's `script_len`, 1 when every
    event in it is in a song style); a sentence lying wholly in song captions is STYLED — matched by place, so a line
    said that is also a lyric of the same file stays. When the sentences don't add up to the captions, no STYLED mark
    (the pairs still find a song that repeats)."""
    sentences = list(sentences)                  # read twice below: a generator would give nothing the second time
    styled = _styled([script_len(text) for text, _tokens in sentences], song_marks) if song_marks else ()
    out = []
    for no, (text, _tokens) in enumerate(sentences):
        marks = NOTE if _NOTE_RE.search(text or "") else 0
        if no in styled:
            marks |= STYLED
        out.append(_key(plain(text)) << 2 | marks)
    return out


def _styled(sizes, song_marks):
    """The numbers of the sentences (`sizes`: their `script_len`s) that lie wholly in song captions (`file_lines`)."""
    if sum(sizes) != sum(n for n, _s in song_marks):
        return ()
    styled, caption, left = set(), 0, song_marks[0][0]
    for no, size in enumerate(sizes):
        need, sung = size, size > 0
        while need:
            while left == 0:                     # an empty caption (all marks) holds no character
                caption += 1
                left = song_marks[caption][0]
            take = min(need, left)
            sung = sung and bool(song_marks[caption][1])
            need, left = need - take, left - take
        if sung:
            styled.add(no)
    return styled


def need(episodes):
    """How many episodes a pair of lines recurs in for a run to be a song (the module's docstring, 2)."""
    return min(max(LOW, math.ceil(SHARE * episodes)), HIGH)


def left_out(files):
    """{file: {sentence number, …}} of the song lines among one title's `files` — [(file, episode, lines), …], `lines`
    as `file_lines` makes them (None or [] for a file with none). Every file of the title, in any order. Every sentence
    keeps its place: one with no line (♪～, an English line: key 0) never pairs and stands as a gap."""
    out, keys, pairs = {}, {}, {}                    # pairs: episode -> the pairs of lines it holds
    for f, ep, lines in files:
        lines = lines or []
        out[f] = {no for no, v in enumerate(lines) if v & STYLED}
        k = keys[f] = [v >> 2 for v in lines]
        pairs.setdefault(ep, set()).update(p for p in zip(k, k[1:]) if p[0] and p[1] and p[0] != p[1])
    if len(pairs) >= LOW:
        seen = Counter()                             # a pair -> how many episodes hold it
        for held in pairs.values():
            seen.update(held)
        bar = need(len(pairs))
        for f, ep, lines in files:
            k = keys[f]
            counts = [seen.get(p, 0) for p in zip(k, k[1:])]    # a pair with no line, or a line twice, is never held
            if counts and max(counts) >= LOW:
                _runs(counts, lines, bar, out[f])
    songs = {keys[f][no] for f in out for no in out[f] if keys[f][no]}
    if songs:
        for f, ep, lines in files:
            k = keys[f]
            out[f].update(no for no, v in enumerate(lines or ()) if v & NOTE and k[no] in songs)
    return out


def _runs(counts, lines, bar, out):
    """Adds to `out` the sentence numbers of a file's song runs (the module's docstring, 2) — `counts`: the episodes
    each pair of neighbouring sentences recurs in, `lines` the file's."""
    n = len(lines)
    count = [0] * n                                  # the most episodes either pair of a sentence recurs in
    for j, e in enumerate(counts):
        if e > count[j]:
            count[j] = e
        if e > count[j + 1]:
            count[j + 1] = e
    i = 0
    while i < n:
        if count[i] < LOW:
            i += 1
            continue
        members, gap, j, last = [i], 0, i + 1, i
        while j < n:
            if count[j] >= LOW:
                members.append(j)
                last, gap = j, 0
            else:
                gap += 1
                if gap > GAP:
                    break
            j += 1
        i = last + 1
        if len(members) < RUN:
            continue
        marked = sum(1 for m in members if lines[m] & 3)
        enough = LOW if marked * 2 >= len(members) else bar
        strong = [m for m in members if count[m] >= enough]
        if len(strong) >= RUN:
            out.update(m for m in members if strong[0] <= m <= strong[-1])

# SPDX-License-Identifier: GPL-3.0-or-later
"""A Japanese card's sentence furigana and its word's pitch, for Backfill's ふりがな and アクセント fills (Kantan-PF).

Why Surasura fills them at all: on Lapis, SentenceFurigana is the AJT Japanese add-on's to write (Anki Miner's mapping
leaves it blank so AJT's per-word colour lands there, Anki_Card_Layout_Spec §4 / §6), and AJT writes only when no Anki
window is in front as the note is added (its `tasks.py::should_generate`). A card added while Anki is in front gets no
furigana and no AJT pitch — 13 of a learner's 1,017 Connect cards, five batches in a row (2026-11-21). Anki Miner fills
PitchPosition from Kanjium, which has no set phrase or compound of its own: 378 of those 1,017 had none.

- `sentence_furigana(text, tagger)`: the sentence in Anki's own furigana form, `漢字[かんじ]` — what Anki Miner writes
  when its mapping names the field (its `generate_furigana_from_tokens`), read by the card's `{{furigana:…}}`. The
  field's markup (`<b>` round the word) stays where it is; a reading goes over its kanji only (取[と]った, 入[い]り
  口[ぐち]); a kanji word whose reading can't be split is read whole.
- `pitch(word, reading, tagger)`: the word's accent from UniDic's `aType` (unidic-lite, already shipped) — only for a
  word that is one dictionary word read as the card reads it; never a name, an interjection or a part of a word, and
  never a set phrase or a compound (measured on the learner's cards, 2026-11-21: one word agrees with Kanjium 332 /
  349 on the accent that colours the word; a compound rule from `aConType` 52%, a phrase 60% — left empty, honestly).

Standard library and the tagger handed in (fugashi): each node's features are read before the next call, which reuses
them.
"""
import html
import re

_TAG = re.compile(r"<[^<>]*>")
_KANJI = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f々〆ヶ]")
_KANA = re.compile(r"[ぁ-ゖァ-ヺー]")
# Not one word of its own: a pitch for these would colour the card wrong (a name's accent is the name's own; a
# particle, an ending or a cry has no headword accent)
NO_PITCH_POS1 = frozenset(("感動詞", "補助記号", "記号", "空白", "接頭辞", "接尾辞", "助詞", "助動詞"))
NAME_POS2 = "固有名詞"
_DIGITS = re.compile(r"\d+(?:,\d+)*")


def hiragana(text):
    """Katakana folded to hiragana (ー and the rest as they are)."""
    return "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text or "")


def _feature(node, name):
    value = getattr(node.feature, name, None)
    return "" if value in (None, "*") else str(value)


def _nodes(tagger, text):
    """[(surface, kana, aType, pos1, pos2, unknown)] — read at once (fugashi reuses a node after the next call)."""
    return [(node.surface, _feature(node, "kana"), _feature(node, "aType"), _feature(node, "pos1"),
             _feature(node, "pos2"), bool(getattr(node, "is_unk", False))) for node in tagger(text)]


def _split(surface, reading):
    """-> [(text, reading or "")]: the reading over each kanji run, the kana between them read as themselves —
    取った/とった -> 取[と]った, 入り口/いりぐち -> 入[い]り 口[ぐち]. A kanji run beside another, or a split two ways
    can make, is read whole: the surface over the whole reading."""
    runs = [m.group(0) for m in re.finditer(r"(?:%s)+|(?:(?!%s).)+" % (_KANJI.pattern, _KANJI.pattern), surface)]
    if len(runs) == 1:
        return [(surface, reading)]
    groups = ["(.+?)" if _KANJI.match(run) else "(" + re.escape(hiragana(run)) + ")" for run in runs]
    lazy = re.fullmatch("".join(groups), reading)
    greedy = re.fullmatch("".join(g.replace("(.+?)", "(.+)") for g in groups), reading)
    if not lazy or not greedy or lazy.groups() != greedy.groups():
        return [(surface, reading)]
    return [(run, part if _KANJI.match(run) else "") for run, part in zip(runs, lazy.groups())]


def _token_furigana(surface, kana):
    """One word in Anki's form: [(its text, the text written, a reading over it)] — the texts make up `surface`."""
    if not _KANJI.search(surface) or not kana:
        return [(surface, _plain(surface), False)]
    reading = hiragana(kana)
    if reading == hiragana(surface):
        return [(surface, _plain(surface), False)]
    return [(text, f"{_plain(text)}[{part}]", True) if part else (text, _plain(text), False)
            for text, part in _split(surface, reading)]


def _plain(text):
    """Text as the field writes it: escaped as the Sentence was, and a bracket of its own never read as a reading."""
    return html.escape(text, quote=False).replace("[", "&#91;").replace("]", "&#93;")


def sentence_furigana(text, tagger):
    """`text` (a card's Sentence: escaped text with markup) in Anki's furigana form. "" for a sentence with no text.
    Its markup stays where it is; one that falls inside a reading's kanji (a bold on half of 試合) goes to that
    reading's edge — an opening tag before it, a closing one after — so a reading is never split (取 of 取った bolds
    as <b>取[と]</b>った)."""
    plain, tags = [], []                    # the text unescaped; each tag with the offset it stood at
    at = 0
    for part in re.split(r"(<[^<>]*>)", text or ""):
        if _TAG.fullmatch(part):
            tags.append((at, part))
        elif part:
            unescaped = html.unescape(part)
            plain.append(unescaped)
            at += len(unescaped)
    plain = "".join(plain)
    if not plain.strip():
        return ""
    pieces, cursor = [], 0                  # (start, end, written, a reading over it), in the text's order
    for surface, kana, _a, _p1, _p2, _unk in _nodes(tagger, plain):
        start = plain.find(surface, cursor) if surface else -1
        if start < 0:
            continue
        if start > cursor:
            pieces.append((cursor, start, _plain(plain[cursor:start]), False))    # what the tagger left out
        for part, written, spaced in _token_furigana(surface, kana):
            pieces.append((start, start + len(part), written, spaced))
            start += len(part)
        cursor = start
    if cursor < len(plain):
        pieces.append((cursor, len(plain), _plain(plain[cursor:]), False))
    placed = []
    for offset, tag in tags:
        for start, end, _written, spaced in pieces:
            if spaced and start < offset < end:
                offset = end if tag.startswith("</") else start
                break
        placed.append((offset, tag))
    out, pending = [], sorted(placed, key=lambda t: t[0])
    for start, end, written, spaced in pieces:
        while pending and pending[0][0] <= start:
            out.append(pending.pop(0)[1])
        if spaced and out and not out[-1].endswith((">", " ")):
            # Anki's filter reads `[…]` over the run since the last ASCII space or tag: a space keeps it on these
            # kanji (one already there does it: a second would show)
            out.append(" ")
        if not spaced and any(start < offset < end for offset, _tag in pending):
            cut = [offset for offset, _tag in pending if start < offset < end]
            last = start
            for offset in cut:                                  # a tag inside plain text stays exactly there
                out.append(_plain(plain[last:offset]))
                while pending and pending[0][0] == offset:
                    out.append(pending.pop(0)[1])
                last = offset
            out.append(_plain(plain[last:end]))
            continue
        out.append(written)
    out.extend(tag for _offset, tag in pending)
    return "".join(out)


def pitch(word, reading, tagger):
    """-> (the word's PitchPosition — UniDic's `aType`, `0` or `1,2` —, None) or ("", why not): "phrase" for more
    than one word, "name", "not a word" (a cry, a particle, a part of a word), "reading differs" (the card reads it
    another way: another word's accent), "no pitch data"."""
    word = (word or "").strip()
    if not word:
        return "", "no word"
    nodes = _nodes(tagger, word)
    if len(nodes) != 1:
        return "", "phrase"
    surface, kana, accent, pos1, pos2, unknown = nodes[0]
    if unknown or not _DIGITS.fullmatch(accent or ""):
        return "", "no pitch data"
    if pos2 == NAME_POS2:
        return "", "name"
    if pos1 in NO_PITCH_POS1:
        return "", "not a word"
    said = hiragana(reading or "") or (hiragana(word) if not _KANJI.search(word) else "")
    if not said or hiragana(kana) != said:
        return "", "reading differs"
    return accent, None

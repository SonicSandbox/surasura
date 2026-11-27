"""BOOK-ONCE (3.0.21): a book's cue index (`lineup.Book`) built once a book, for *Card sound*'s audiobook step
(`sound_source._audiobooks`) and Connect's pick of a word's cue (`lineup.place` / `lineup.split`).

Before: `_audiobooks` handed `add_audio.place` a plain list for each card its own look-up missed (a Book built a card:
the whole book indexed again), and `lineup.place` walked every cue in Python for each word. Now one Book a book, and
each card / word is a dict look plus one or two `str.find` — the same answers as the old code, which these tests keep
as their reference (`_place_before`, `_split_before`) and compare on real ja + zh lines.
"""
import os

import pytest

from app.connect import add_audio, lineup, sound_source as ss
from tests.connect.test_add_audio import MAPPING, book  # noqa: F401 (the fixture)
from tests.test_audiobook_transcripts import _other_lines

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")


def _place_before(line_text, spelling, found, unit=None):
    """`lineup.place` as it was before BOOK-ONCE: one Python pass over the cues for each word — the reference."""
    MIN_CHARS, clean = lineup.MIN_CHARS, lineup.clean
    hold = clean(spelling)
    if isinstance(unit, int) and not isinstance(unit, bool):
        cue = next((c for c in found if c.unit == unit), None)
        if cue is not None and (not hold or hold in cue.text):
            return cue
    want = clean(line_text)
    if not want:
        return None
    for k, cue in enumerate(found):
        if not cue.text:
            continue
        if cue.text == want or (len(want) >= MIN_CHARS and want in cue.text):
            return cue if not hold or hold in cue.text else None
        if len(cue.text) >= MIN_CHARS and cue.text in want:
            run = [cue]
            for nxt in found[k + 1:]:
                if not nxt.text or nxt.text not in want or len(nxt.text) < MIN_CHARS:
                    break
                run.append(nxt)
            holding = [c for c in run if not hold or hold in c.text]
            return holding[0] if len(holding) == 1 else None
    return None


def _book_cues(language, names):
    """Real subtitle lines as one book's cues, with the shapes a book has: a cue with no letters (♪ only), lines said
    again later, a line said twice in one cue, a cue of MIN_CHARS exactly, a cue holding a pair twice; units as Anki
    Miner numbers them, one number on two cues, some cues without one, one damaged (a list, from a hand-edited file)."""
    found = []
    for name in names:
        path = os.path.join(RESOURCES, language, name)
        found += [lineup.Cue(path + ".m4b", path, a, z, lineup.clean(t), len(found) + n)
                  for n, (a, z, t) in enumerate(lineup.srt_cues(path), 1)]
    found.insert(3, lineup.Cue("a.m4b", "a.srt", 0.0, 1.0, "", 9999))
    found += [c._replace(start=c.start + 600, unit=None) for c in found[4:6]]
    found += [found[6]._replace(start=900.0, text=found[6].text * 2, unit=found[2].unit),
              found[7]._replace(start=901.0, text=found[7].text[:lineup.MIN_CHARS], unit=[1, 2]),
              found[8]._replace(start=902.0, text=(found[0].text + found[5].text) * 2, unit=None)]
    return found


def _sentences(found, language):
    texts = [c.text for c in found if c.text]
    assert len(texts) > 8 and len(set(texts)) < len(texts)            # real lines, some said twice
    return (texts + [a + b for a, b in zip(texts, texts[1:])] +
            [a + b + c for a, b, c in zip(texts, texts[1:], texts[2:])] +
            [t[1:-1] for t in texts] + [t[:4] for t in texts] + [t + "です" for t in texts] +
            list(_other_lines(language)) + ["", "。"] +
            [a + b[:lineup.MIN_CHARS] for a, b in zip(texts, texts[1:])] + [found[0].text + found[5].text])


BOOKS = [("ja", ["placed_episode.srt", "repeated_lines.ja.srt", "utterances_sample.srt", "verses_sample.srt"]),
         ("zh", ["night_market.srt", "repeated_lines.zh.srt", "utterances_sample.srt"])]


@pytest.mark.parametrize("language,names", BOOKS)
def test_a_words_cue_by_the_books_index_is_the_old_passs_ja_and_zh(language, names):
    """Every word shape against the old pass, on real lines: a line that is a cue (once, or said twice), held inside a
    longer cue, said over two or three cues, part of a cue, a short line, a line not in the book, an empty one; the
    spelling none / held / not held / bracketed; the unit none, the cue's own, a neighbour's, one on two cues, one no
    cue has, a bool, a string — the same Cue (or None) from a list or the Book."""
    found = _book_cues(language, names)
    indexed = lineup.Book(found)
    units = [None, True, "41", 123456, found[2].unit, found[5].unit, found[10].unit]
    checked = 0
    for s in _sentences(found, language):
        clean = lineup.clean(s)
        for spelling in (None, "", clean[:2], clean[-3:-1], "存在しない", "「" + clean[:2] + "」"):
            for unit in units:
                want = _place_before(s, spelling, found, unit)
                assert lineup.place(s, spelling, indexed, unit) == want, (s, spelling, unit)
                assert lineup.place(s, spelling, found, unit) == want, (s, spelling, unit)
                checked += want is not None
    assert checked > 500                                               # (not a pass of all None)


def _split_before(words, state):
    """`lineup.split` before BOOK-ONCE (the old `place` a word) — the reference."""
    groups, rest = {}, []
    found = lineup.cues(state) if lineup.usable(state) else []
    for word in words:
        cue = _place_before(word.get("line_text"), word.get("surface") or word.get("orth") or word.get("word"),
                            found, word.get("unit_index")) if found else None
        if cue is None:
            rest.append(word)
            continue
        groups.setdefault((cue.audio, cue.subtitle), []).append(
            dict(word, line_start=cue.start, line_end=cue.end, line_expansion=[0, 0], line_skip=[]))
    return groups, rest


@pytest.mark.parametrize("language,names", BOOKS)
def test_a_books_picked_words_are_split_by_one_index_built_once(language, names, monkeypatch):
    """Red before BOOK-ONCE: each word walked the whole book. `split` indexes the book's cues once for all its words
    and groups them exactly as before."""
    found = _book_cues(language, names)
    monkeypatch.setattr(lineup, "usable", lambda state: True)
    monkeypatch.setattr(lineup, "cues", lambda state: list(found))
    words = []
    for k, s in enumerate(_sentences(found, language)):
        clean = lineup.clean(s)
        words.append({"line_text": s, "surface": clean[:2] if k % 3 else None, "word": clean[-3:-1] or "x",
                      "unit_index": found[k % len(found)].unit if k % 4 == 0 else None})
    want = _split_before(words, {})
    real, built = getattr(lineup, "Book", None), []
    assert real is not None, "the book's cue index lives beside the cues"

    class Counted(real):
        def __init__(self, cues):
            built.append(len(cues))
            super().__init__(cues)
    monkeypatch.setattr(lineup, "Book", Counted)
    got = lineup.split(words, {})
    assert built == [len(found)]
    assert got == want and sum(len(v) for v in got[0].values()) > 50


def test_add_audios_book_is_the_line_ups_one_index():
    """One class: *Add audio*'s Book is the line-up's (a caller may build it from either name)."""
    assert add_audio.Book is getattr(lineup, "Book", None)


def test_card_sound_indexes_a_paired_book_once_for_all_its_cards(book, monkeypatch, tmp_path):  # noqa: F811
    """Red before BOOK-ONCE: a card whose sentence no cue says whole was placed with a plain list — the book indexed
    again for that card. Now the book's cues are indexed once and every card is placed in them, each at the cue *Add
    audio* would cut (its own test: the same plan)."""
    monkeypatch.setattr(ss, "_sound_files", lambda language, s: {})
    want = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)["can"]
    notes = book["anki"].notes([100, 101, 102, 103, 104, 200, 201, 300])
    real, built = getattr(lineup, "Book", None), []
    assert real is not None, "the book's cue index lives beside the cues"

    class Counted(real):
        def __init__(self, cues):
            built.append(len(cues))
            super().__init__(cues)
    monkeypatch.setattr(lineup, "Book", Counted)
    got = ss.plan("ja", notes, MAPPING, book["steps"], ledger_path=str(tmp_path / "no-ledger.sqlite"))
    assert len(built) == 1 and built[0] > 4
    assert want and all(got[nid].kind == ss.AUDIOBOOK and got[nid].cue == cue for nid, cue in want.items())


def test_a_card_with_no_letters_in_its_sentence_never_takes_a_no_letters_cue(book, monkeypatch, tmp_path):  # noqa: F811
    """A card whose sentence field holds no letters (emptied, or only punctuation) is placed by `place`'s rule: no
    sentence, no cue — never a ♪-only cue of the book (its clean text is empty too). Before BOOK-ONCE the step's own
    look-up matched the two empty texts and gave the card the music's sound."""
    monkeypatch.setattr(ss, "_sound_files", lambda language, s: {})
    want = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)["can"]
    notes = book["anki"].notes(list(want))
    first = notes[0]
    first["fields"][MAPPING.sentence]["value"] = "……。"
    real = lineup.cues
    monkeypatch.setattr(lineup, "cues", lambda state: real(state) + [lineup.Cue("a.m4b", "a.srt", 0.0, 1.0, "")])
    got = ss.plan("ja", notes, MAPPING, book["steps"], ledger_path=str(tmp_path / "no-ledger.sqlite"))
    assert got[first["noteId"]].kind != ss.AUDIOBOOK
    assert all(got[n["noteId"]].kind == ss.AUDIOBOOK for n in notes[1:])

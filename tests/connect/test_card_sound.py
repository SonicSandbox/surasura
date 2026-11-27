"""*Add sound* (AUDIO-FILL, `app/connect/card_sound.py`; Sonic § 106 + § 108, PLAN lane 2; ROLES *Card sound*): real
sound first for every card at once, the AI voice only for the cards due in the window, the card type following its
sound, one Undo a run, *Remove all AI audio*.

What a wrong answer would cost: the learner's own audio overwritten (the cardinal sin), a suspended card voiced, the
AI voice run over a month of cards at once (hours of a learner's CPU) or before the soonest-due, a real clip refused
because an AI one was there first, an AI clip the learner edited replaced, a card type the learner set changed, an
Undo that leaves half a run behind, a Chinese card handed to a voice that reads only Japanese.

Real data: AUDIO-FIND's suite — the Japanese and Chinese episodes (`placed_episode.srt`, `night_market.srt`), their
lines, a recap of the same lines; Connect's ledger is a real one; Anki is the writer's fake (notesInfo's shape) with
the two searches the press asks; the cut and the AI voice hand back real files on disk.
"""
import base64
import os
from collections import namedtuple

import pytest

from app.connect import card_sound as cs, sentence_audio as sa
from app.connect.ledger import Ledger
from tests.connect.test_add_audio import MAPPING
from tests.connect.test_sentence_audio import FakeAnki
from tests.connect.test_sound_source import EPISODE, _made, lib  # noqa: F401 (the fixture)

MARKS = ("IsSentenceCard", "IsAudioCard")
_Cue = namedtuple("_Cue", "start end text")
UNSAID = {"ja": _Cue(4000, 6000, "今日は朝から雨が降っている。"), "zh": _Cue(4000, 6000, "今天从早上开始一直下雨。")}
MARKED = MAPPING._replace(quiet_mark=MARKS[0], sound_mark=MARKS[1])


class Anki(FakeAnki):
    """The writer's fake plus the press's two searches (Anki's own rules: an empty field, suspended cards left out, a
    tag, a list of ids) and the due window."""

    def __init__(self, due=None):
        super().__init__()
        self.suspended, self.due_ = set(), dict(due or {})
        self.searches = []

    def find(self, query):
        self.searches.append(query)
        live = [n for n in sorted(self.notes_) if n not in self.suspended or "-is:suspended" not in query]
        if "tag:" + cs.AI_TAG in query:
            return [n for n in sorted(self.notes_) if cs.AI_TAG in self.notes_[n]["tags"]]
        if "nid:" in query:
            ids = {int(x) for x in query.split("nid:")[1].split()[0].split(",")}
            return [n for n in live if n in ids]
        return [n for n in live if self.value(n) == ""]

    def due(self, deck, days):
        return {n: d for n, d in self.due_.items() if d < days}

    def read_media(self, name):
        kept = self.media.get(name)
        return base64.b64decode(kept) if kept else b"ID3 kept"      # (a file Anki has that no test stored)


def _clip(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + name.encode("utf-8"))
    return str(path)


def _cutter(tmp_path, asked):
    def cut(language, line_id, settings, steps):
        asked.append(line_id)
        return _clip(tmp_path, "line-" + line_id.replace(":", "_") + ".mp3")
    return cut


def _voice(tmp_path, asked):
    def make(note_ids, kinds, paragraphs):
        asked.append(list(note_ids))
        return {"files": {n: _clip(tmp_path, f"ai-{n}.mp3") for n in note_ids}, "problems": []}
    return make


def _marked(anki, nid, sentence_mark, audio_mark):
    fields = anki.notes_[nid]["fields"]
    fields[MARKS[0]] = {"value": sentence_mark, "order": 10}
    fields[MARKS[1]] = {"value": audio_mark, "order": 11}


def _run(env, tmp_path, cut=None, voice=None, **kw):
    with Ledger(env["ledger"]) as ledger:
        return cs.run(env["anki"], ledger, env["lang"], kw.pop("mapping", MAPPING), env["steps"],
                      cut_line=cut or _cutter(tmp_path, []), cut_book=lambda *a: {}, make_ai=voice,
                      kinds={}, paragraphs={}, ledger_path=env["ledger"], keep_dir=str(tmp_path / "kept"), **kw)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_real_sound_goes_on_every_card_at_once_and_never_over_the_learners_audio(lib, lang, tmp_path):
    """Two Connect cards with their own lines get the cut clip (real sound is never metered: no due window asked);
    the learner's own audio card and a suspended card are never touched; Undo empties exactly the two."""
    env = lib(lang)
    env["anki"] = Anki()
    said = env["said"]
    _made(env, EPISODE, [(600, said[0], None), (601, said[2], None), (602, said[3], None), (603, said[4], None)])
    env["anki"].notes_[602]["fields"]["SentenceAudio"]["value"] = "[sound:mine.mp3]"
    env["anki"].suspended.add(603)
    cut = []
    got = _run(env, tmp_path, cut=_cutter(tmp_path, cut), ai=False)
    assert got["real"] == 2 and got["id"]
    for n in (600, 601):
        assert env["anki"].value(n).startswith("[sound:surasura-sa-") and sa.TAG in env["anki"].notes_[n]["tags"]
    assert env["anki"].value(602) == "[sound:mine.mp3]", "the learner's own audio stays"
    assert env["anki"].value(603) == "", "a suspended card waits for its unsuspend"
    assert len(cut) == 2
    with Ledger(env["ledger"]) as ledger:
        back = cs.undo(env["anki"], ledger, got["id"])
        assert back["emptied"] == [600, 601]
        assert cs.undo(env["anki"], ledger, got["id"])["refused"], "a run is undone once"
    assert env["anki"].value(600) == env["anki"].value(601) == ""


def test_the_ai_voice_reads_only_the_cards_due_in_the_window_soonest_first(lib, tmp_path):
    """Four cards with no real sound: due in 2, today, in 5 days, and not due — a 3-day window voices the two due
    soonest (today's first); the rest wait for their day; nothing at all while the voice is off."""
    env = lib("ja")
    env["anki"] = Anki(due={701: 2, 702: 0, 703: 5})
    for n in (701, 702, 703, 704):
        env["anki"].add(n, "犬が好きだ。", "犬")
    asked = []
    off = _run(env, tmp_path, voice=_voice(tmp_path, asked), ai=False)
    assert (off["ai"], off["waiting"], off["id"], asked) == (0, 4, None, [])
    got = _run(env, tmp_path, voice=_voice(tmp_path, asked), ai=True, days=3)
    assert asked == [[702, 701]], "soonest first, only the window's"
    assert (got["ai"], got["waiting"]) == (2, 2)
    assert cs.AI_TAG in env["anki"].notes_[702]["tags"] and env["anki"].value(703) == ""


def test_a_chinese_card_without_real_sound_is_never_handed_to_the_voice(lib, tmp_path):
    env = lib("zh")
    env["anki"] = Anki(due={801: 0})
    env["anki"].add(801, "我喜欢狗。", "狗")
    asked = []
    got = _run(env, tmp_path, voice=_voice(tmp_path, asked), ai=True)
    assert (got["silent"], got["ai"], asked) == (1, 0, [])


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_real_sound_replaces_only_an_untouched_ai_clip(lib, lang, tmp_path):
    """Two cards got the AI voice; then their real line turns up. The untouched one's AI clip is replaced (its own
    record, its Undo puts the AI clip back); the one whose field the learner edited since keeps the learner's edit."""
    env = lib(lang)
    env["anki"] = Anki()
    said = env["said"]
    _made(env, EPISODE, [(900, said[0], None), (901, said[2], None)])
    with Ledger(env["ledger"]) as ledger:
        wrote = sa.fill(env["anki"], ledger, {900: _clip(tmp_path, "a.mp3"), 901: _clip(tmp_path, "b.mp3")},
                        tag=cs.AI_TAG, by="ai-audio")
    ai_900 = env["anki"].value(900)
    env["anki"].notes_[901]["fields"]["SentenceAudio"]["value"] = "[sound:my-own.mp3]"
    got = _run(env, tmp_path, ai=False)
    assert got["swapped"] == 1 and got["real"] == 0
    assert env["anki"].value(900) != ai_900 and "line-" not in env["anki"].value(900)
    assert env["anki"].value(901) == "[sound:my-own.mp3]"
    with Ledger(env["ledger"]) as ledger:
        cs.undo(env["anki"], ledger, got["id"])
    assert env["anki"].value(900) == ai_900, "Undo puts the AI clip back"
    assert wrote["id"]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_card_type_follows_its_sound_and_never_a_type_the_learner_set(lib, lang, tmp_path):
    """A sentence card made for want of sound (BOOK-CARD's pair) gets its line: it becomes the audio card. A silent
    Connect audio card (no line here) becomes the sentence card. A card the learner set both marks on, and a card
    Connect never made, keep theirs. Undo puts every mark back."""
    env = lib(lang)
    env["anki"] = Anki()
    said = env["said"]
    _made(env, EPISODE, [(1000, said[0], None), (1001, said[2], None)])
    _made(env, 99, [(1002, UNSAID[lang], None)])         # (no subtitle here, a line no episode says)
    env["anki"].add(1003, said[4].text, said[4].text[:2])           # not Connect's
    _marked(env["anki"], 1000, "x", "")
    _marked(env["anki"], 1001, "x", "x")                 # the learner's own choice
    _marked(env["anki"], 1002, "", "x")
    _marked(env["anki"], 1003, "", "x")
    got = _run(env, tmp_path, ai=False, mapping=MARKED, marks=MARKS)
    marks = lambda n: (env["anki"].value(n, MARKS[0]), env["anki"].value(n, MARKS[1]))  # noqa: E731
    assert marks(1000) == ("", "x"), "it has sound now: the audio card"
    assert marks(1001) == ("x", "x")
    assert marks(1002) == ("x", ""), "still silent: the sentence card until sound comes"
    assert marks(1003) == ("", "x"), "a card Connect never made keeps its type"
    assert got["flipped"] == 2
    with Ledger(env["ledger"]) as ledger:
        cs.undo(env["anki"], ledger, got["id"])
    assert (marks(1000), marks(1002)) == (("x", ""), ("", "x"))
    assert env["anki"].value(1000) == ""


def test_remove_all_ai_audio_counts_first_then_takes_off_every_ai_clip_and_keeps_the_learners(lib, tmp_path):
    """An AI clip the writer put on, a hand-made one carrying the tag (Iro-C's), an AI clip the learner replaced with
    his own, and real sound: the count is 2; the press empties those two (its copies kept), the silent Connect card
    becomes the sentence card, and its Undo puts all of it back."""
    env = lib("ja")
    env["anki"] = Anki()
    said = env["said"]
    _made(env, 99, [(1100, said[0], None)])
    for n in (1101, 1102, 1103):
        env["anki"].add(n, said[n - 1100].text, "犬")
    _marked(env["anki"], 1100, "", "x")
    with Ledger(env["ledger"]) as ledger:
        sa.fill(env["anki"], ledger, {1100: _clip(tmp_path, "a.mp3"), 1102: _clip(tmp_path, "c.mp3")},
                tag=cs.AI_TAG, by="ai-audio")
        sa.fill(env["anki"], ledger, {1103: _clip(tmp_path, "d.mp3")}, tag=sa.TAG, by="add-audio")
    env["anki"].notes_[1101]["fields"]["SentenceAudio"]["value"] = "[sound:iro-c-1101.mp3]"
    env["anki"].notes_[1101]["tags"].append(cs.AI_TAG)
    env["anki"].notes_[1102]["fields"]["SentenceAudio"]["value"] = "[sound:my-own.mp3]"
    before = {n: env["anki"].value(n) for n in (1100, 1101, 1102, 1103)}
    with Ledger(env["ledger"]) as ledger:
        assert cs.remove_ai_audio(env["anki"], ledger, "ja", "SentenceAudio") == {"cards": 2}
        got = cs.remove_ai_audio(env["anki"], ledger, "ja", "SentenceAudio", confirm=True, marks=MARKS,
                                 ledger_path=env["ledger"], keep_dir=str(tmp_path / "kept"))
    assert got["removed"] == [1100, 1101] and got["flipped"] == 1
    assert env["anki"].value(1100) == env["anki"].value(1101) == ""
    assert env["anki"].value(1102) == before[1102] and env["anki"].value(1103) == before[1103]
    assert env["anki"].value(1100, MARKS[0]) == "x"
    with Ledger(env["ledger"]) as ledger:
        cs.undo(env["anki"], ledger, got["id"])
    assert {n: env["anki"].value(n) for n in before} == before


def test_an_empty_deck_and_no_audio_field_write_nothing(lib, tmp_path):
    env = lib("ja")
    env["anki"] = Anki()
    assert _run(env, tmp_path, ai=True)["id"] is None
    env["anki"].add(1200, "犬が好きだ。", "犬")
    got = _run(env, tmp_path, ai=True, mapping=MAPPING._replace(fields={"word": "Expression"}))
    assert got["id"] is None and env["anki"].value(1200) == ""


def test_a_line_that_cannot_be_cut_leaves_its_cards_for_the_next_run(lib, tmp_path):
    """The cut refused one line (its video gone mid-run): that card is named in `not_cut`, the other is written."""
    env = lib("ja")
    env["anki"] = Anki()
    said = env["said"]
    _made(env, EPISODE, [(1300, said[0], None), (1301, said[2], None)])
    ok = _cutter(tmp_path, [])

    def cut(language, line_id, settings, steps):
        if line_id.endswith(str(int(said[0].start))):
            raise OSError("the video went away")
        return ok(language, line_id, settings, steps)
    got = _run(env, tmp_path, cut=cut, ai=False)
    assert got["real"] == 1 and list(got["not_cut"]) == [1300] and env["anki"].value(1300) == ""


def test_days_of_takes_only_the_three_choices():
    assert [cs.days_of({"card_sound_days": d}) for d in (1, 3, 7, 5, None, "7")] == [1, 3, 7, 3, 3, 3]
    assert cs.days_of(None) == cs.DAYS_DEFAULT


def test_ai_held_follows_the_writers_records_in_order(tmp_path):
    """An AI write stands until a later write of Surasura's to that note, and never once undone."""
    anki = Anki()
    for n in (1, 2, 3):
        anki.add(n, "犬が好きだ。", "犬")
    with Ledger(str(tmp_path / "l.sqlite")) as ledger:
        a = sa.fill(anki, ledger, {1: _clip(tmp_path, "1.mp3"), 2: _clip(tmp_path, "2.mp3"),
                                   3: _clip(tmp_path, "3.mp3")}, tag=cs.AI_TAG, by="ai-audio")
        anki.notes_[2]["fields"]["SentenceAudio"]["value"] = ""
        sa.fill(anki, ledger, {2: _clip(tmp_path, "2r.mp3")}, tag=sa.TAG, by="add-audio")
        held = cs.ai_held(ledger)
        assert set(held) == {1, 3}
        sa.undo(anki, ledger, a["id"])
        assert cs.ai_held(ledger) == {}
    assert os.path.isdir(str(tmp_path))

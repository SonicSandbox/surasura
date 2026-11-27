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


# --- Connect's automatic pass (`auto`: § 106 "new cards get sound by themselves while the switch is on") --------- #
@pytest.fixture
def auto_env(lib, tmp_path, monkeypatch):
    """`auto` with this suite's Anki, cut and voice in place of the real ones (Anki Miner's mapping, the clip cut, the
    AI voice, the sync owed recorded)."""
    from app.connect import undo as undoing

    def make(lang, due=None, voice_on=False):
        env = lib(lang)
        env["anki"] = Anki(due=due)
        env["cut"], env["voiced"], env["synced"] = [], [], []
        env["unheard"] = set()

        def voice(note_ids, kinds, paragraphs):
            env["voiced"].append(list(note_ids))
            return {"files": {n: _clip(tmp_path, f"ai-{n}.mp3") for n in note_ids if n not in env["unheard"]},
                    "problems": [], "unheard": sorted(env["unheard"] & set(note_ids))}
        monkeypatch.setattr(cs, "Anki", lambda url: env["anki"])
        monkeypatch.setattr(cs, "_mapping", lambda s, l: (str(tmp_path / "run"), MAPPING))
        monkeypatch.setattr(cs, "_cut_line", _cutter(tmp_path, env["cut"]))
        monkeypatch.setattr(cs, "_cut_book", lambda s, l: (lambda *a: {}))
        monkeypatch.setattr(cs, "_make_ai", lambda s, l, stop: voice)
        monkeypatch.setattr(cs, "_voice_on", lambda s, l: voice_on)
        monkeypatch.setattr(cs, "_kinds", lambda *a: {})
        monkeypatch.setattr(cs, "_paragraphs", lambda *a: {})
        monkeypatch.setattr(undoing, "owe_sync", lambda s: env["synced"].append(True))
        monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)     # (every test sets it: Anki here is the fake)
        return env
    return make


def _auto(env, **kw):
    with Ledger(env["ledger"]) as ledger:
        return cs.auto({"connect_enabled": True}, env["lang"], ledger, steps=env["steps"],
                       ledger_path=env["ledger"], **kw)


def _new(env, ids):
    with Ledger(env["ledger"]) as ledger:
        cs.queue_new(ledger, env["lang"], ids)
        return cs._meta_json(ledger, cs.NEW + env["lang"], [])


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_automatic_pass_gives_connects_new_cards_their_real_sound_and_only_those(auto_env, lang):
    """A part's two new cards are noted when it fills; the pass gives them their line's sound once and clears the
    list. An older soundless card nobody noted waits for the press (the pass never plans the whole deck)."""
    env = auto_env(lang)
    said = env["said"]
    _made(env, EPISODE, [(1200, said[0], None), (1201, said[2], None), (1202, said[3], None)])
    assert _new(env, [1200, 1201]) == [1200, 1201]
    got = _auto(env)
    assert got["real"] == 2 and got["id"] and env["synced"]
    assert env["anki"].value(1200).startswith("[sound:surasura-sa-") and env["anki"].value(1202) == ""
    assert _new(env, []) == [], "looked at once"
    assert _auto(env) == {"skipped": cs.NOTHING}, "nothing new and the voice off: Anki isn't even asked"


def test_the_automatic_pass_voices_the_window_soonest_first_and_a_refused_clip_waits_for_tomorrow(auto_env):
    """The voice on: three soundless cards due today / in 2 days / in 5 (3-day window) — the two inside are voiced,
    soonest first; one the voice's check refused is tried again tomorrow, never at every pass."""
    env = auto_env("ja", due={1301: 2, 1302: 0, 1303: 5}, voice_on=True)
    for n in (1301, 1302, 1303):
        env["anki"].add(n, "犬が好きだ。", "犬")
    env["unheard"] = {1301}
    got = _auto(env)
    assert env["voiced"] == [[1302, 1301]] and got["ai"] == 1
    assert env["anki"].value(1302).startswith("[sound:") and env["anki"].value(1301) == ""
    assert _auto(env)["id"] is None, "the refused one isn't asked again today"
    assert env["voiced"] == [[1302, 1301]]
    with Ledger(env["ledger"]) as ledger:                   # tomorrow: tried again
        cs._put_meta(ledger, cs.TRIED + "ja", {"day": "2000-01-01", "notes": [1301]})
    _auto(env)
    assert env["voiced"][-1] == [1301]


def test_a_busy_pc_holds_the_ai_voice_but_never_the_real_sound(auto_env):
    """`ai_hold` (the CPU busy) keeps the voice from starting; the new cards' real sound still goes on."""
    env = auto_env("ja", due={1401: 0, 1402: 0}, voice_on=True)
    said = env["said"]
    _made(env, EPISODE, [(1400, said[0], None)])
    env["anki"].add(1401, "犬が好きだ。", "犬")
    _new(env, [1400])
    got = _auto(env, ai_hold=lambda: True)
    assert got["real"] == 1 and env["voiced"] == [] and env["anki"].value(1401) == ""


def test_a_stop_between_two_lines_leaves_the_rest_for_the_next_pass(auto_env):
    """A part coming in (`should_stop`) stops the cut between two lines: what was cut is written, and the card the
    stop left stays on the list, so the next pass cuts it."""
    env = auto_env("ja")
    said = env["said"]
    _made(env, EPISODE, [(1500, said[0], None), (1501, said[2], None)])
    _new(env, [1500, 1501])
    asks = iter([False, True] + [True] * 10)
    got = _auto(env, should_stop=lambda: next(asks))
    assert got["real"] == 1 and len(env["cut"]) == 1
    left = _new(env, [])
    assert len(left) == 1 and env["anki"].value(left[0]) == ""
    assert _auto(env)["real"] == 1 and _new(env, []) == []


def test_the_automatic_pass_does_nothing_with_connect_off_or_anki_switched_off(auto_env, monkeypatch):
    env = auto_env("ja", voice_on=True)
    with Ledger(env["ledger"]) as ledger:
        assert cs.auto({}, "ja", ledger)["skipped"]
        monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
        assert cs.auto({"connect_enabled": True}, "ja", ledger)["skipped"]
    assert env["anki"].searches == []


def test_the_new_cards_list_keeps_each_card_once_and_its_newest_within_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "NEW_MAX", 3)
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        cs.queue_new(ledger, "ja", [1, 2])
        cs.queue_new(ledger, "ja", [2, 3, 4])
        assert cs._meta_json(ledger, cs.NEW + "ja", []) == [2, 3, 4]
        assert cs._meta_json(ledger, cs.NEW + "zh", []) == []
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (cs.NEW + "zh", "not json"))
        cs.queue_new(ledger, "zh", [5])                     # a damaged list is started again, never a failure
        assert cs._meta_json(ledger, cs.NEW + "zh", []) == [5]


# --- *Needs you*'s count (`recount` in Connect's pass, `counted` in the window) ---------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_count_plans_each_soundless_card_once_a_day_and_the_window_reads_it(lib, lang, tmp_path, monkeypatch):
    """Two cards with their line, one with none (Japanese: the AI voice's; Chinese: silent), the learner's own audio
    card (not counted): the count says so; a second count plans only the card added since; a card that got sound
    drops out; the window's reader returns the same numbers from the ledger alone."""
    from app.connect import sound_source
    env = lib(lang)
    env["anki"] = Anki()
    said = env["said"]
    _made(env, EPISODE, [(1600, said[0], None), (1601, said[2], None)])
    env["anki"].add(1602, UNSAID[lang].text, UNSAID[lang].text[:2])
    env["anki"].add(1603, said[3].text, said[3].text[:2], audio="[sound:mine.mp3]")
    real_plan, planned = sound_source.plan, []

    def plan(language, notes, mapping, steps, ledger_path=None):
        planned.append(sorted(int(n["noteId"]) for n in notes))
        return real_plan(language, notes, mapping, steps, ledger_path=ledger_path)
    monkeypatch.setattr(sound_source, "plan", plan)
    with Ledger(env["ledger"]) as ledger:
        got = cs.recount(env["anki"], ledger, lang, MAPPING, env["steps"], ledger_path=env["ledger"])
        ai, silent = (1, 0) if lang == "ja" else (0, 1)
        assert {k: got[k] for k in ("cards", "real", "ai", "silent")} == {"cards": 3, "real": 2, "ai": ai,
                                                                          "silent": silent}
        env["anki"].add(1604, UNSAID[lang].text, UNSAID[lang].text[:2])
        env["anki"].notes_[1600]["fields"]["SentenceAudio"]["value"] = "[sound:now.mp3]"
        again = cs.recount(env["anki"], ledger, lang, MAPPING, env["steps"], ledger_path=env["ledger"])
    assert planned == [[1600, 1601, 1602], [1604]], "each card planned once a day"
    assert (again["real"], again["cards"]) == (1, 3)
    assert cs.counted(lang, ledger_path=env["ledger"]) == {k: again[k] for k in ("cards", "real", "ai", "silent",
                                                                                 "at")}
    assert cs.counted("zh" if lang == "ja" else "ja", ledger_path=env["ledger"]) is None


def test_the_windows_reader_says_none_without_a_ledger_or_with_a_damaged_count(tmp_path):
    assert cs.counted("ja", ledger_path=str(tmp_path / "none.sqlite")) is None
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (cs.COUNT + "ja", "{broken"))
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (cs.COUNT + "zh",
                                                                                        '{"real": "many"}'))
    assert cs.counted("ja", ledger_path=str(tmp_path / "ledger.db")) is None
    assert cs.counted("zh", ledger_path=str(tmp_path / "ledger.db")) is None


@pytest.mark.parametrize("argv, want", [(["add-sound"], (False, None, False)),
                                        (["add-sound", "--confirm"], (True, None, False)),
                                        (["add-sound", "--undo", "r7"], (False, "r7", False)),
                                        (["add-sound", "--remove-ai", "--confirm"], (True, None, True))])
def test_the_command_lines_add_sound_is_card_sounds_one_door(monkeypatch, argv, want):
    # why: surasura-cli's *Add sound* is the window's press (`act`): the counts without --confirm, one run's Undo,
    # *Remove all AI audio* — never a second writer
    from app.cli import __main__ as cli
    from app.cli import connect_verbs
    asked = []
    monkeypatch.setattr(connect_verbs, "settings", lambda: {"target_language": "zh"})
    monkeypatch.setattr(cs, "act", lambda s, lang, confirm=False, undo_id=None, remove_ai=False:
                        asked.append((lang, confirm, undo_id, remove_ai)) or {"ok": True})
    args = cli._parser().parse_args(argv)
    assert args.verb == "add-sound"
    assert connect_verbs.add_sound(args) == {"ok": True}
    assert asked == [("zh",) + want]


def test_undo_and_remove_ai_are_one_or_the_other():
    from app.cli import __main__ as cli
    from app.cli import contract
    with pytest.raises(contract.CliError):                # (the CLI's parser answers a usage error, never an exit)
        cli._parser().parse_args(["add-sound", "--undo", "r7", "--remove-ai"])


# --- the review's fixes (AUDIO-FILL c) ------------------------------------------------------------------------------ #
def _rec(by, notes, tag=None, mode=None):
    out = {"state": sa.DONE, "by": by, "notes": notes, "tag": tag}
    if mode:
        out["mode"] = mode
    return out


def test_a_type_flip_that_writes_the_same_ai_clip_back_leaves_it_held():
    """Decision 4's flip writes the sound field back as it is (`_flips`): the AI clip still stands, so real sound may
    still replace it (decision 3) and *Remove all AI audio* still takes it; a later write of another value doesn't."""
    clip = "[sound:surasura-sa-ai.mp3]"
    records = [("1", _rec("ai-audio", {"5": clip, "6": clip}, tag=cs.AI_TAG)),
               ("2", _rec(cs.BY_TYPE, {"5": {"SentenceAudio": clip, "IsSentenceCard": "x"}}, mode=sa.REPLACE)),
               ("3", _rec(cs.BY_SWAP, {"6": {"SentenceAudio": "[sound:real.mp3]"}}, tag=sa.TAG, mode=sa.REPLACE))]
    assert cs.ai_held(None, records) == {5: clip}


def test_the_runs_record_is_saved_at_its_first_write_and_every_chunk_never_every_write(monkeypatch):
    # why: saving the whole list after each write made a big Remove all write N²/2 ids (the review's waste find)
    saved = []
    monkeypatch.setattr(cs, "_save_run", lambda ledger, rid, rec: saved.append(len(rec["records"])))
    rec = {"records": []}
    for n in range(1, 2 * cs.CHUNK + 7):
        rec["records"].append(str(n))
        cs._save_some(None, "r", rec)
    assert saved == [1, cs.CHUNK, 2 * cs.CHUNK]


def _plan_one(monkeypatch, n=7):
    from app.connect import sound_source
    src = sound_source.Source(sound_source.LINE, 7, 0, 1000, f"7:{n}")
    monkeypatch.setattr(cs, "look", lambda *a, **k: {"field": "SentenceAudio", "plan": {n: src}, "notes": {n: {}},
                                                      "held": {}, "silent": 0})
    monkeypatch.setattr(cs, "_cut_real", lambda *a: ({n: "clip.mp3"}, {}))

    def fill(anki, ledger, clips, field, tag, by, records):
        records.append("written-1")
        return {"filled": list(clips)}
    monkeypatch.setattr(cs, "_fill", fill)


def test_a_run_stopped_after_a_write_names_its_undo_even_when_its_record_cant_be_saved(monkeypatch):
    # why: the stopped run's id must reach the caller (its Undo, Anki's sync owed); a ledger busy at that moment
    # must not swap the first error for its own
    import sqlite3
    _plan_one(monkeypatch)

    def save(ledger, rid, rec):
        if rec.get("stopped"):
            raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(cs, "_save_run", save)
    monkeypatch.setattr(cs, "_voice_on", lambda s, l: (_ for _ in ()).throw(ConnectionError("Anki closed")))
    with pytest.raises(ConnectionError) as got:
        cs.run(None, None, "ja", MAPPING, None, settings={})
    assert got.value.card_sound_id


@pytest.fixture
def act_env(monkeypatch, tmp_path):
    from app.cli import verbs
    from app.connect import undo as undoing
    owed = []
    monkeypatch.setattr(cs, "Anki", lambda url: Anki())
    monkeypatch.setattr(cs, "_mapping", lambda s, l: (str(tmp_path / "run"), MAPPING))
    monkeypatch.setattr(verbs, "require_set_up", lambda lang: None)
    monkeypatch.setattr(undoing, "owe_sync", lambda s: owed.append(True))
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    return owed


def test_a_plain_words_error_after_writes_keeps_the_runs_undo_and_owes_the_sync(act_env, monkeypatch):
    from app.cli.contract import CliError

    def run(*a, **k):
        e = CliError("needs-you", "Anki Miner's field mapping changed")
        e.card_sound_id = "r1"
        raise e
    monkeypatch.setattr(cs, "run", run)
    with pytest.raises(CliError) as got:
        cs.act({"connect_enabled": True}, "ja", confirm=True)
    assert got.value.context.get("undo") == "r1" and act_env == [True]


def test_an_undo_stopped_part_way_still_owes_the_sync(act_env, monkeypatch):
    monkeypatch.setattr(cs, "run_record", lambda ledger, rid: {"records": []})
    monkeypatch.setattr(cs, "undo", lambda anki, ledger, rid: (_ for _ in ()).throw(ConnectionError("Anki closed")))
    with pytest.raises(Exception):
        cs.act({"connect_enabled": True}, "ja", undo_id="r1")
    assert act_env == [True]


def test_the_toasts_undo_with_connect_off_says_why():
    got = cs.press_undo("ja", "r1", {"connect_enabled": False})
    assert got == {"ok": False, "say": cs.UNDO_OFF, "emptied": 0, "kept": 0}


def test_remove_all_ai_audio_counts_and_takes_only_the_mappings_deck(monkeypatch, tmp_path):
    # why: the clips Surasura wrote into another deck are not this deck's to count or take
    anki = Anki()
    for n in (1, 2):
        anki.add(n, "犬が好きだ。", "犬")
    with Ledger(str(tmp_path / "l.sqlite")) as ledger:
        sa.fill(anki, ledger, {1: _clip(tmp_path, "1.mp3"), 2: _clip(tmp_path, "2.mp3")}, tag=cs.AI_TAG,
                by="ai-audio")
        for n in (1, 2):                                  # (the tagged search finds none: the held half alone)
            anki.notes_[n]["tags"] = [t for t in anki.notes_[n]["tags"] if t != cs.AI_TAG]
        asked = []
        monkeypatch.setattr(cs, "_in_deck", lambda a, deck, ids: asked.append((deck, set(ids))) or {1})
        assert set(cs.ai_cards(anki, ledger, "SentenceAudio", deck="Mining")) == {1}
        assert asked == [("Mining", {1, 2})]
        assert set(cs.ai_cards(anki, ledger, "SentenceAudio")) == {1, 2}, "no deck named: every held clip"


def test_the_voices_kinds_and_paragraphs_read_the_cards_items_once(monkeypatch):
    calls = []
    monkeypatch.setattr(cs, "_items", lambda *a: calls.append(a) or {5: (9, "book/ch1.epub")})
    items = cs._items_or_none("ja", None, [5], None)
    assert cs._kinds("ja", None, [5], None, items) == {5: "book"} and len(calls) == 1


def test_a_token_store_that_cant_be_read_gives_no_paragraphs_never_a_stopped_voice(monkeypatch):
    monkeypatch.setattr(cs, "_paragraph_texts", lambda *a: (_ for _ in ()).throw(OSError("store locked")))
    assert cs._paragraphs("ja", None, [5], {}, MAPPING, None, {5: (9, "book/ch1.epub")}) == {}


def test_a_busy_pc_never_asks_anki_for_the_due_window(auto_env):
    # why: the hold comes first: a busy PC pays for no due search (~40 Anki look-ups) it then can't use
    env = auto_env("ja", due={1401: 0}, voice_on=True)
    said = env["said"]
    _made(env, EPISODE, [(1400, said[0], None)])
    env["anki"].add(1401, "犬が好きだ。", "犬")
    _new(env, [1400])
    asked = []
    real_due = env["anki"].due
    env["anki"].due = lambda deck, days: asked.append(days) or real_due(deck, days)
    got = _auto(env, ai_hold=lambda: True)
    assert got["real"] == 1 and asked == [] and env["voiced"] == []


def test_a_refused_clip_keeps_its_day_even_when_the_pass_then_stops(auto_env, monkeypatch):
    # why: a pass stopped after the voice (Anki closed at the write) must not voice the refused clip again next pass
    env = auto_env("ja", due={1401: 0}, voice_on=True)
    env["anki"].add(1401, "犬が好きだ。", "犬")
    env["unheard"] = {1401}
    real_fill = cs._fill

    def fill(anki, ledger, clips, field, tag, by, records):
        if tag == cs.AI_TAG:
            raise ConnectionError("Anki closed")
        return real_fill(anki, ledger, clips, field, tag, by, records)
    monkeypatch.setattr(cs, "_fill", fill)
    with pytest.raises(ConnectionError):
        _auto(env)
    with Ledger(env["ledger"]) as ledger:
        assert 1401 in cs._tried(ledger, "ja")

"""Which sound a card would get (AUDIO-FIND, `app/connect/sound_source.py`; Sonic § 106, PLAN lane 1): its own line in
its episode, its book's audiobook, the same sentence word for word in another episode, else the AI voice's turn — read
only, in that order — and which cards fall due in the next N days.

What a wrong answer would cost: a clip of another line on a card teaches the wrong sound (the cardinal sin: a
re-timed subtitle's neighbour, one of two lines that say the same words in the card's own episode); a card with sound
already planned again (the learner's audio overwritten later); a Chinese card handed to a voice that reads only
Japanese; Anki asked once a card, or a whole new queue rendered, just to know what falls due.

Real data: the suite's Japanese and Chinese episodes (`placed_episode.srt`, `night_market.srt`) and their lines, a recap
episode made of the same lines at other times, the add-audio suite's paired book (a real EPUB, M4B and trusted `.srt`
in a real store); Connect's ledger is a real one; Anki is the writer's fake (notesInfo's shape).
"""
import os

import pytest

from app import cues
from app.connect import ledger as ledger_mod, lineup, sound_source as ss, swap
from app.connect.ledger import Ledger
from tests.connect.test_add_audio import MAPPING, book  # noqa: F401 (the fixture)
from tests.connect.test_sentence_audio import FakeAnki

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
SUBS = {"ja": os.path.join(RESOURCES, "ja", "placed_episode.srt"),
        "zh": os.path.join(RESOURCES, "zh", "night_market.srt")}
EPISODE, RECAP, OTHER = 7, 8, 9


class Steps:
    """Connect's lookups as the plan asks them: each item's subtitle in the library, its video on this PC."""

    def __init__(self, subtitles, videos):
        self.subtitles, self.videos, self.asked = subtitles, videos, []

    def subtitle(self, lang, job):
        self.asked.append(("subtitle", job["item_id"]))
        return self.subtitles.get(job["item_id"])

    def video(self, lang, job):
        self.asked.append(("video", job["item_id"]))
        return self.videos.get(job["item_id"])


def _srt(path, lines):
    """A real subtitle file of `lines` [(start ms, end ms, text)]."""
    def t(ms):
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    with open(path, "w", encoding="utf-8") as f:
        for n, (a, b, text) in enumerate(lines, 1):
            f.write(f"{n}\n{t(a)} --> {t(b)}\n{text}\n\n")
    return str(path)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """-> (lang) -> dict: the language's real episode (item EPISODE) with its video, a recap episode (RECAP: two of
    its lines again, at other times) with its video, the ledger, Anki; the library's subtitles in that order; the
    token store's look is the files' own words (`_holding`: a file holds a word its text says), every look recorded."""
    def make(lang):
        said = [c for c in cues.read(SUBS[lang], lang) if c.counted]
        recap = _srt(tmp_path / f"recap-{lang}.srt", [(60000, 62500, said[3].text), (63000, 65500, said[0].text)])
        videos = {}
        for item in (EPISODE, RECAP):
            v = tmp_path / f"ep{item}-{lang}.mkv"
            v.write_bytes(b"\x1aE\xdf\xa3 matroska")
            videos[item] = str(v)
        steps = Steps({EPISODE: SUBS[lang], RECAP: recap}, videos)
        looked = []

        def holding(language, paths, runs):
            looked.append((list(paths), runs))
            out = []
            for p in paths:
                with open(p, encoding="utf-8-sig") as f:
                    text = f.read()
                if any(all(w in text for w in run) for run in runs):
                    out.append(p)
            return out
        monkeypatch.setattr(ss, "_holding", holding)
        monkeypatch.setattr(ss, "_sound_files", lambda language, s: {SUBS[lang]: EPISODE, recap: RECAP})
        monkeypatch.setattr(ss, "_books", lambda language, s, nids: [])
        return {"lang": lang, "said": said, "steps": steps, "recap": recap, "looked": looked,
                "ledger": str(tmp_path / f"ledger-{lang}.sqlite"), "anki": FakeAnki()}
    return make


def _made(env, item, rows):
    """Connect made these cards from `item`: rows [(note id, the cue its line is, start s or None: the cue's own)]."""
    with Ledger(env["ledger"]) as ledger:
        job = ledger.queue(env["lang"], item, "test", None)
        with ledger.transaction():
            ledger.record_outcomes(job, 1, [
                {"word": cue.text[:2], "reading": f"r{nid}", "sentence": cue.text, "outcome": "made", "note_id": nid,
                 "line_start": cue.start / 1000.0 if start is None else start, "line_end": cue.end / 1000.0}
                for nid, cue, start in rows])
    for nid, cue, _start in rows:
        env["anki"].add(nid, f"<b>{cue.text[:2]}</b>{cue.text[2:]}", cue.text[:2])


def _plan(env, ids):
    return ss.plan(env["lang"], env["anki"].notes(ids), MAPPING, env["steps"], ledger_path=env["ledger"])


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_connect_card_gets_its_own_line_in_its_own_episode(lib, lang):
    """Two cards of the episode: each its own cue (the id the journey's clip takes), never the recap's same words."""
    env = lib(lang)
    _made(env, EPISODE, [(500, env["said"][0], None), (501, env["said"][2], None)])
    got = _plan(env, [500, 501])
    for nid, cue in ((500, env["said"][0]), (501, env["said"][2])):
        assert got[nid] == ss.Source(ss.LINE, EPISODE, cue.start, cue.end, swap.line_id(EPISODE, cue.start / 1000))
    assert not env["looked"], "no other episode is looked at once every card has its own line"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_retimed_subtitle_still_finds_the_cards_own_line_by_its_words(lib, lang):
    """The subtitle shifted 0.8 s since the mine: no cue at the recorded start, so the one cue that says the card's
    sentence word for word is its line."""
    env = lib(lang)
    cue = env["said"][4]
    _made(env, EPISODE, [(510, cue, cue.start / 1000.0 - 0.8)])
    got = _plan(env, [510])[510]
    assert (got.kind, got.item_id, got.start) == (ss.LINE, EPISODE, cue.start)


def test_a_cue_now_at_the_recorded_start_saying_other_words_is_never_taken(lib, tmp_path):
    """Re-timed so another line now starts where the card's did: that neighbour is never the card's sound."""
    env = lib("ja")
    said = env["said"]
    moved = _srt(tmp_path / "moved.srt", [(said[0].start, said[0].end, said[1].text),
                                          (said[1].start + 4000, said[1].end + 4000, said[0].text)])
    env["steps"].subtitles[EPISODE] = moved
    _made(env, EPISODE, [(520, said[0], None)])
    got = _plan(env, [520])[520]
    assert got.kind == ss.LINE and got.start == said[1].start + 4000, "its own words, where they are now"


def test_two_lines_of_one_sentence_in_its_episode_after_a_retime_are_refused_and_never_its_neighbours(lib, tmp_path):
    """The card's episode says its sentence twice (a catchphrase) and was re-timed: no line can be told for it, so
    none is taken — not either copy, not the neighbour now at its start, and its own episode is no "elsewhere"."""
    env = lib("ja")
    said = env["said"]
    twice = _srt(tmp_path / "twice.srt", [(1000, 3200, said[1].text), (5000, 7000, said[5].text),
                                          (30000, 32200, said[1].text)])
    env["steps"].subtitles[EPISODE] = twice
    _made(env, EPISODE, [(530, said[1], 4.9)])
    assert _plan(env, [530])[530] == ss.Source(ss.NONE, why=ss.AI)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_whose_episode_is_gone_gets_the_same_line_from_another_episode(lib, lang, monkeypatch):
    """The card's episode left the library (no subtitle for it): another episode says its sentence word for word,
    so that line is its sound — the first such episode in the library's order."""
    env = lib(lang)
    _made(env, OTHER, [(540, env["said"][3], None)])
    got = _plan(env, [540])[540]
    cue = env["said"][3]
    assert got == ss.Source(ss.ELSEWHERE, EPISODE, cue.start, cue.end, swap.line_id(EPISODE, cue.start / 1000))
    monkeypatch.setattr(ss, "_sound_files", lambda language, s: {env["recap"]: RECAP, SUBS[lang]: EPISODE})
    got = _plan(env, [540])[540]
    want = [c for c in cues.read(env["recap"], lang) if c.text == cue.text][0]
    assert got == ss.Source(ss.ELSEWHERE, RECAP, want.start, want.end, swap.line_id(RECAP, want.start / 1000))
    assert [runs for _paths, runs in env["looked"]] == [[[cue.text[:2]]]] * 2, "one look a plan, the card's word"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_connect_didnt_make_gets_the_same_sentence_from_the_library(lib, lang):
    """A Yomitan card (no ledger row) whose sentence an episode says: that line. One no episode says: the AI voice's
    turn in Japanese; in Chinese no sound (no voice reads it)."""
    env = lib(lang)
    line = env["said"][0].text
    env["anki"].add(550, line, line[:2])
    env["anki"].add(551, "誰も言わない一文です。" if lang == "ja" else "没有人说过这句话。", "誰も" if lang == "ja" else "没有")
    got = _plan(env, [550, 551])
    assert got[550].kind == ss.ELSEWHERE and got[550].item_id == EPISODE, "the library's first episode that says it"
    assert got[551] == ss.Source(ss.NONE, why=ss.AI if lang == "ja" else ss.SILENT)


def test_an_episode_without_its_video_here_gives_no_line(lib):
    """The subtitle is there but its video isn't on this PC: nothing to cut from, so the next step's turn."""
    env = lib("ja")
    del env["steps"].videos[EPISODE]
    del env["steps"].videos[RECAP]
    _made(env, EPISODE, [(560, env["said"][0], None)])
    assert _plan(env, [560])[560].why == ss.AI


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_with_sound_already_or_no_audio_field_is_never_planned(lib, lang):
    """The learner's own audio (and a single space: something is there) is theirs; a mapping with no audio field has
    nowhere to put one. Neither is looked for anywhere."""
    env = lib(lang)
    line = env["said"][0].text
    env["anki"].add(570, line, line[:2], audio="[sound:mine.mp3]")
    env["anki"].add(571, line, line[:2], audio=" ")
    got = _plan(env, [570, 571])
    assert {got[570].kind, got[571].kind} == {ss.NONE} and got[570].why == got[571].why == "it has sentence audio already"
    assert ss.tally(got)["has_sound"] == 2
    unmapped = MAPPING._replace(fields={"word": "Expression", "sentence": "Sentence"})
    assert ss.plan(lang, env["anki"].notes([570]), unmapped, env["steps"], env["ledger"])[570].why == ss.NO_FIELD
    assert not env["steps"].asked and not env["looked"]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_empty_library_and_no_ledger_give_every_card_the_voices_turn(lib, lang, monkeypatch):
    env = lib(lang)
    monkeypatch.setattr(ss, "_sound_files", lambda language, s: {})
    line = env["said"][2].text
    env["anki"].add(580, line, line[:2])
    got = _plan(env, [580])
    assert got[580].why == (ss.AI if lang == "ja" else ss.SILENT) and not os.path.exists(env["ledger"])
    assert ss.plan(lang, [], MAPPING, env["steps"], env["ledger"]) == {}


def test_the_tally_is_what_needs_you_says(lib):
    """27 cards with no sound → N their episode's sound, M the AI voice: the plan's own count."""
    env = lib("ja")
    _made(env, EPISODE, [(590, env["said"][0], None)])
    _made(env, OTHER, [(591, env["said"][3], None)])
    env["anki"].add(592, "誰も言わない一文です。", "誰も")
    got = ss.tally(_plan(env, [590, 591, 592]))
    assert got == {"line": 1, "audiobook": 0, "elsewhere": 1, "ai": 1, "silent": 0, "has_sound": 0,
                   "other": 0}


def test_a_book_card_gets_the_narrators_line_add_audio_would_cut(book, monkeypatch, tmp_path):  # noqa: F811
    """The add-audio suite's book: each card Connect made from it is placed in its line-up exactly where *Add audio*
    places it (the same cue), the card with audio is not planned, the one the audiobook never says waits for the
    voice, and the card of another item is no card of this book's."""
    from app.connect import add_audio
    monkeypatch.setattr(ss, "_sound_files", lambda language, s: {})      # (no episode in this library)
    want = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)["can"]
    notes = book["anki"].notes([100, 101, 102, 103, 104, 200, 201, 300])
    got = ss.plan("ja", notes, MAPPING, book["steps"], ledger_path=str(tmp_path / "no-ledger.sqlite"))
    assert want
    for nid, cue in want.items():
        assert got[nid].kind == ss.AUDIOBOOK and got[nid].cue == cue
    assert got[200].kind == ss.NONE and got[201].why == ss.AI
    assert got[300].kind != ss.AUDIOBOOK


# --- the due window -------------------------------------------------------------------------------------------- #
class FakeAnkiSearch:
    """AnkiConnect's searches as Anki answers them, over a deck of cards {card: (note, kind, due, suspended)} — kind
    learn / review (due: days from today) / new (due: its place in the new queue)."""

    def __init__(self, cards):
        self.cards, self.calls = cards, []

    def __call__(self, action, url, **params):
        self.calls.append((action, params.get("query")))
        if action == "cardsInfo":
            return [{"cardId": c, "note": self.cards[c][0], "due": self.cards[c][2]} for c in params["cards"]]
        q = params["query"]
        hits = []
        for card, (note, kind, due, suspended) in self.cards.items():
            if suspended and "-is:suspended" in q:
                continue
            if "is:learn" in q and kind != "learn":
                continue
            if "-is:new" in q and kind != "review":
                continue
            if " is:new" in q and kind != "new":
                continue
            if "prop:due<=" in q and not due <= int(q.split("prop:due<=")[1]):
                continue
            if "prop:due=" in q and not due == int(q.split("prop:due=")[1]):
                continue
            if "prop:pos<=" in q and not due <= int(q.split("prop:pos<=")[1]):
                continue
            hits.append(note if action == "findNotes" else card)
        return sorted(set(hits))


def _deck():
    cards = {1: (11, "learn", 0, False), 2: (12, "review", -3, False), 3: (13, "review", 1, False),
             4: (14, "review", 2, False), 5: (15, "review", 3, False), 6: (16, "review", 0, True)}
    for k in range(30):                         # the new queue, out of order on purpose (Junban's places)
        cards[100 + k] = (200 + k, "new", (k * 7) % 30 + 1, k == 4)
    return cards


def test_the_cards_due_in_the_next_three_days_soonest_first(monkeypatch):
    """Learning and overdue today, then each review's own day; the new queue's first per-day × 3 by place, a day's
    worth at a time; past the window, suspended or another kind: out. Anki asked a search a day and a few id-only
    searches for the new queue, cardsInfo only for the window's new cards."""
    from app import anki_connect
    fake = FakeAnkiSearch(_deck())
    monkeypatch.setattr(anki_connect, "invoke", fake)
    got = ss.due_days("http://127.0.0.1:8765", "日本語::Mining", 3, per_day=4)
    assert {n: got[n] for n in (11, 12, 13, 14)} == {11: 0, 12: 0, 13: 1, 14: 2}
    assert 15 not in got and 16 not in got, "past the window, suspended"
    new = sorted((fake.cards[c][2], fake.cards[c][0]) for c in fake.cards if fake.cards[c][1] == "new"
                 and not fake.cards[c][3])
    assert {n: got[n] for _p, n in new[:12]} == {n: i // 4 for i, (_p, n) in enumerate(new[:12])}
    assert not set(got) & {n for _p, n in new[12:]}
    assert len([c for c in fake.calls if c[0] == "cardsInfo"]) == 1, "only the window's new cards, once"
    assert all('deck:"日本語::Mining"' in q for a, q in fake.calls if a != "cardsInfo")
    assert len([c for c in fake.calls if c[0] != "cardsInfo"]) <= 4 + 2 * 6, "a search a day, the queue halved"


def test_a_small_new_queue_is_all_in_the_window_and_no_days_is_none(monkeypatch):
    from app import anki_connect
    cards = {1: (11, "new", 5, False), 2: (12, "new", 2, False)}
    fake = FakeAnkiSearch(cards)
    monkeypatch.setattr(anki_connect, "invoke", fake)
    assert ss.due_days("u", None, 1, per_day=20) == {11: 0, 12: 0}
    assert not [q for _a, q in fake.calls if q and "prop:pos" in q], "fewer than a window: no halving"
    assert ss.due_days("u", None, 0) == {}


def test_the_decks_own_new_cards_a_day_is_read_when_not_given(monkeypatch):
    from app import anki_connect
    from app.connect import anki_session
    cards = {100 + k: (200 + k, "new", k, False) for k in range(10)}
    monkeypatch.setattr(anki_connect, "invoke", FakeAnkiSearch(cards))
    monkeypatch.setattr(anki_session, "per_day", lambda url, deck: 3)
    got = ss.due_days("u", "Mining", 2)
    assert got == {200: 0, 201: 0, 202: 0, 203: 1, 204: 1, 205: 1}


def test_the_ledgers_card_lines_are_one_reader_for_piyo_and_the_cards_sound(tmp_path):
    """`ledger.note_lines` keeps the line's end too; Piyo's translations read the same rows as before."""
    from app import card_translations
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        job = ledger.queue("ja", EPISODE, "test", None)
        with ledger.transaction():
            ledger.record_outcomes(job, 1, [{"word": "文化祭", "reading": "ブンカサイ", "sentence": "文化祭まで、あと三日しかないよ。",
                                             "line_start": 1.0, "line_end": 3.2, "outcome": "made", "note_id": 600}])
    assert ledger_mod.note_lines(path, [600, 601], "ja") == {600: (EPISODE, 1.0, 3.2, "文化祭まで、あと三日しかないよ。")}
    assert card_translations._outcomes(path, [600], "ja") == {600: (EPISODE, 1.0, "文化祭まで、あと三日しかないよ。")}
    assert ledger_mod.note_lines(path, [600], "zh") == {} and ledger_mod.note_lines(None, [600]) == {}


# --- the review's cases (AUDIO-FIND, 2026-11-26) ---------------------------------------------------------------- #
def test_a_line_saying_only_part_of_the_sentence_at_its_start_is_never_its_sound(lib, tmp_path):
    """Re-timed so the cue now at the card's start says only the first half of its sentence (both halves 8+
    characters): half its sound is no sound — the cue that holds the whole sentence, elsewhere in the file, is it."""
    env = lib("ja")
    said = env["said"]
    whole = said[0].text + said[1].text
    env["steps"].subtitles[EPISODE] = _srt(tmp_path / "half.srt", [(1000, 3200, said[0].text), (40000, 45000, whole)])
    cue = said[0]._replace(text=whole)
    _made(env, EPISODE, [(700, cue, 1.0)])
    got = _plan(env, [700])[700]
    assert (got.kind, got.start) == (ss.LINE, 40000)


def test_a_line_shown_again_is_one_line_never_two_after_a_retime(lib):
    """The suite's repeated-lines episode shows 図書館の鍵を忘れちゃった twice back to back (one line, shown
    again): re-timed, it is still found — its first copy — never refused as two lines."""
    env = lib("ja")
    path = os.path.join(RESOURCES, "ja", "repeated_lines.ja.srt")
    env["steps"].subtitles[EPISODE] = path
    first = cues.read(path, "ja")[0]
    _made(env, EPISODE, [(710, first, 9.9)])
    got = _plan(env, [710])[710]
    assert (got.kind, got.start) == (ss.LINE, first.start)


@pytest.mark.parametrize("off, found", [(5, True), (6, False)])
def test_a_start_off_by_five_ms_keeps_its_line_and_six_looks_by_its_words(lib, tmp_path, off, found):
    """Within NEAR_MS the cue at the start is the card's even when its text was retyped longer; one more ms and it
    is looked for by its words, which this one no longer says alone."""
    env = lib("ja")
    said = env["said"]
    longer = said[2].text + said[3].text
    env["steps"].subtitles[EPISODE] = _srt(tmp_path / "near.srt", [(said[2].start + off, said[2].end, longer)])
    _made(env, EPISODE, [(720, said[2], None)])
    assert (_plan(env, [720])[720].kind == ss.LINE) is found


def test_a_subtitle_that_cant_be_read_leaves_only_its_own_cards_to_the_next_step(lib, monkeypatch):
    env = lib("ja")
    _made(env, EPISODE, [(730, env["said"][0], None)])
    real = cues.read

    def broken(path, *a, **k):
        if path == SUBS["ja"]:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "a damaged file")
        return real(path, *a, **k)
    monkeypatch.setattr(cues, "read", broken)
    got = _plan(env, [730])[730]
    assert got.kind == ss.ELSEWHERE and got.item_id == RECAP


def test_the_tally_keeps_a_card_with_no_audio_field_apart_from_one_with_sound(lib):
    env = lib("ja")
    env["anki"].add(740, env["said"][0].text, "文化", audio="[sound:mine.mp3]")
    unmapped = MAPPING._replace(fields={"word": "Expression", "sentence": "Sentence"})
    assert ss.tally(ss.plan("ja", env["anki"].notes([740]), unmapped, env["steps"], env["ledger"]))["other"] == 1
    assert ss.tally(_plan(env, [740]))["has_sound"] == 1


def test_a_busy_ledger_is_a_wait_never_cards_without_their_lines(lib, monkeypatch):
    import sqlite3
    from app.connect import runner
    env = lib("ja")
    _made(env, EPISODE, [(750, env["said"][0], None)])

    def busy(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(ledger_mod, "note_lines", busy)
    with pytest.raises(runner.Wait):
        _plan(env, [750])


def test_a_note_with_a_review_later_and_a_new_card_first_in_line_is_due_today(monkeypatch):
    from app import anki_connect
    cards = {1: (11, "review", 2, False), 2: (11, "new", 1, False)}
    cards.update({10 + k: (20 + k, "new", 2 + k, False) for k in range(10)})
    monkeypatch.setattr(anki_connect, "invoke", FakeAnkiSearch(cards))
    assert ss.due_days("u", None, 3, per_day=2)[11] == 0


def test_a_sparse_new_queue_widens_its_search_until_the_window_is_full(monkeypatch):
    """Junban spaces the places far apart (DevTest: 3,564 … 997,709): the search doubles past them, then halves."""
    from app import anki_connect
    cards = {100 + k: (200 + k, "new", 1000 * (k + 1), False) for k in range(40)}
    fake = FakeAnkiSearch(cards)
    monkeypatch.setattr(anki_connect, "invoke", fake)
    got = ss.due_days("u", None, 1)
    assert got == {200 + k: 0 for k in range(ss.NEW_PER_DAY)}
    asked = [q for _a, q in fake.calls if q and "prop:pos" in q]
    assert len(asked) == len(set(asked)) and len(asked) <= 2 * 16, "no place asked twice"

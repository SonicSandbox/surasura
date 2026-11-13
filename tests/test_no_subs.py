"""Michi-NS (3.0.1, PROVISIONAL rules P1–P9; the spec: the 3.0 plan's tracks/tools/work/no-subs/SPEC.md, Sonic's NS-1…7):
a video in a source folder with no subtitle waits (SRC K5). *Make them from the audio* has Anki Miner 3.11's
`transcribe` (here the tests' fake, run as a child as the real one is) write one, the waiting item takes it in place —
read, listed and mined like any other, timed to its own audio, its cards tagged — and a copy goes beside the video (Q4,
the S3 exception Sonic approved: only where no file has its name, never over one, never removed). hato finds them online
only once its tools entry lists `find` (hato 1.1.x): today's hato is never sent a thing.

What a wrong answer would cost: a learner's file overwritten beside their video (S3); a second item for one episode
when the next look sees the copy beside it; a made subtitle mined as if a person had timed it, untagged; a cancelled or
refused run leaving a half file or a row stuck at *Making…*; titles sent to hato before the learner's yes, or to a hato
that can't take a list. Real subtitles from tests/Test Resources; never Anki, never a real Anki Miner or hato."""
import datetime
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from app import library_store as ls
from app import no_subs, tools_entry
from app.connect import anki_miner, fit_check, library
from app.services import needs as service
from app.services import view_rows
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _text, _tree, _video, _waiting, _write  # noqa: F401

FAKE = os.path.join(os.path.dirname(__file__), "connect", "fake_anki_miner.py")
RES = os.path.join(os.path.dirname(__file__), "Test Resources")
_SHOW = {"ja": "図書館の午後", "zh": "夜市小记"}
# what the speech model "hears" in each language: a real line of the suite's own subtitles, as an SRT
_HEARD = {"ja": "1\n00:01:33,100 --> 00:01:36,250\nすみません、この本を借りたいんですが。\n\n"
                "2\n00:01:36,800 --> 00:01:39,900\n図書館のカードはお持ちですか？\n\n"
                "3\n00:01:40,500 --> 00:01:43,000\nいいえ、今日初めて来ました。\n",
          "zh": "1\n00:00:01,200 --> 00:00:03,800\n大家好，欢迎回到我的频道。\n\n"
                "2\n00:00:04,100 --> 00:00:07,350\n今天我们要去台北的夜市吃东西。\n\n"
                "3\n00:00:08,000 --> 00:00:10,500\n这里的小吃真的很好吃。\n"}
_ENGLISH = "1\n00:01:33,100 --> 00:01:36,250\nExcuse me, I'd like to borrow this book.\n"
READY = {"speech": {"installed": ["small"], "model": "small"}}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """The fake Anki Miner's plan (a dict the test fills) and its log of calls; its speech models in the test's home."""
    plan, log = tmp_path / "plan.json", tmp_path / "calls.log"
    monkeypatch.setattr(no_subs, "_MINERS", {})
    monkeypatch.setattr(anki_miner, "_SPEECH", {})
    monkeypatch.setenv("FAKE_ANKI_MINER_PLAN", str(plan))
    monkeypatch.setenv("FAKE_ANKI_MINER_LOG", str(log))
    monkeypatch.setenv("ANKI_MINER_HOME", str(tmp_path / "am-home"))

    class Fake:
        def set(self, **values):
            values.setdefault("app", "3.11.0")
            values.setdefault("features", ["named-words-whitelisted", "transcribe", "setup-speech-ocr"])
            plan.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")

        def calls(self, command=None):
            if not log.exists():
                return []
            got = [json.loads(line)["argv"] for line in log.read_text(encoding="utf-8").splitlines()]
            return [a for a in got if command is None or (len(a) > 1 and a[1] == command)]
    return Fake()


def _library(language, names=("05",)):
    """A library whose source folder holds videos and no subtitle: each a waiting item (K5)."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    videos = [_video(os.path.join(src, _SHOW[language], f"[Grp] {_SHOW[language]} - {n} (1080p).mkv"),
                     body=b"\x1a\x45\xdf\xa3 matroska " + n.encode()) for n in names]
    store.__enter__()
    root = store.add_source(src)
    _look(store, language, root, first=True)
    assert _waiting(store) == len(names)
    return store, data_dir, src, root, videos


def _items(store):
    return store.conn.execute("SELECT id, rel_path, availability FROM items ORDER BY id").fetchall()


def _make(store, language, ids=None, **kw):
    ids = [i for i, _r, a in _items(store) if a == "waiting"] if ids is None else ids
    return no_subs.make(store, language, ids, settings={}, path=FAKE, **kw)


def _beside(video, language):
    return no_subs.beside_path(video, language)


# --- made from the audio: the write ------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiting_video_made_from_its_audio_is_filled_in_place_timed_to_its_audio(language, fake):
    """Why: the item the video waited on takes the made text — its id and place kept, the copy in the library's own
    folder — its record says `transcribed` (never `timed`, K16), and Connect mines it as timed to its own audio (Q5).
    A copy goes beside the video, and that is the ONLY thing written in the learner's folder."""
    store, data_dir, src, root, (video,) = _library(language)
    fake.set(heard_videos={os.path.basename(video): _HEARD[language]}, **READY)
    (item_id, before, _a), = _items(store)
    tree = dict((t[0], t[1:]) for t in _tree(src))
    try:
        out = _make(store, language)
        assert out["made"] == 1 and out["failed"] == 0 and out["beside_refused"] == 0
        (same, rel, availability), = _items(store)
        stem = os.path.splitext(os.path.basename(video))[0]
        assert same == item_id and availability == "available"
        assert rel == f"{before.rpartition('/')[0]}/{stem}.{language}.srt"
        copy = os.path.join(data_dir, *rel.split("/"))
        with open(copy, encoding="utf-8") as f:
            assert f.read() == _HEARD[language]
        record = library.pairing_of(store, item_id)
        assert record["verdict"] == "transcribed" and record["subtitle_source"]["provider"] == "transcribe"
        assert record["video_path"] == os.path.abspath(video)
        assert fit_check.fit(record, video, copy, tsubasa="")[:2] == (fit_check.TIMED, "audio")
        beside = _beside(video, language)
        with open(beside, encoding="utf-8") as f:
            assert f.read() == _HEARD[language]
        after = dict((t[0], t[1:]) for t in _tree(src))
        added = set(after) - set(tree)
        assert added == {os.path.relpath(beside, src)}, "only the copy beside the video was written there"
        assert all(after[k][:2] == tree[k][:2] for k in tree if tree[k][0] is not None), "no file of theirs changed"
        assert no_subs.note(rel, language) == no_subs.MADE and no_subs.note(before, language) is None
        assert [c[1] for c in fake.calls()][-1] == "transcribe"
        assert not os.path.exists(os.path.join(os.path.dirname(no_subs.state_path(language)),
                                               f"no-subs-run-{language}"))     # Anki Miner's run folder gone
    finally:
        store.__exit__(None, None, None)


def test_the_next_look_takes_the_copy_beside_the_video_as_a_version_never_a_second_item(fake):
    """Why: the copy beside the video is a subtitle file in the source folder; the folder's next look must see it as
    the same episode (`episode_names.FROM_AUDIO`, `Store._track_items`), never a new item or a fill over the text."""
    store, data_dir, src, root, (video,) = _library("ja")
    fake.set(heard_videos={os.path.basename(video): _HEARD["ja"]}, **READY)
    try:
        assert _make(store, "ja")["made"] == 1
        before = _items(store)
        _look(store, "ja", root, full=True)
        assert _items(store) == before, "one episode, one item: its made text stays"
    finally:
        store.__exit__(None, None, None)


def test_a_file_already_beside_the_video_under_that_name_is_never_written_over(fake):
    """Why: S3 — Surasura only ever adds beside a video; whatever is there under the made copy's name stays."""
    store, data_dir, src, root, (video,) = _library("ja")
    fake.set(heard_videos={os.path.basename(video): _HEARD["ja"]}, **READY)
    beside = _beside(video, "ja")
    with open(beside, "w", encoding="utf-8") as f:
        f.write(_ENGLISH)
    try:
        assert _make(store, "ja")["made"] == 1
        with open(beside, encoding="utf-8") as f:
            assert f.read() == _ENGLISH
    finally:
        store.__exit__(None, None, None)


def test_a_folder_that_takes_no_copy_keeps_surasuras_and_says_so_once(fake, monkeypatch):
    """Why: a read-only share: the episode is still filled from Surasura's own copy; the press says it once."""
    store, data_dir, src, root, (video,) = _library("ja")
    fake.set(heard_videos={os.path.basename(video): _HEARD["ja"]}, **READY)
    monkeypatch.setattr(no_subs, "beside_path", lambda v, lang: os.path.join(src, "no such folder", "x.srt"))
    try:
        out = _make(store, "ja")
        assert out["made"] == 1 and out["beside_refused"] == 1
        assert _items(store)[0][2] == "available"
    finally:
        store.__exit__(None, None, None)


def test_hatos_beside_the_video_setting_off_writes_nothing_beside_it(fake, monkeypatch):
    """Why: Q4 follows hato's own setting (SRC-7) once hato says it: off, nothing goes beside the video."""
    store, data_dir, src, root, (video,) = _library("ja")
    fake.set(heard_videos={os.path.basename(video): _HEARD["ja"]}, **READY)
    monkeypatch.setattr(no_subs, "hato_config", lambda settings=None, run=None: {no_subs.BESIDE_KEY: False})
    try:
        assert _make(store, "ja")["made"] == 1
        assert not os.path.exists(_beside(video, "ja"))
    finally:
        store.__exit__(None, None, None)


@pytest.mark.parametrize("heard, note, key", [("no_speech", no_subs.NO_SPEECH, "no_speech"),
                                              ("VIDEO_UNREADABLE", no_subs.UNREADABLE, "unreadable"),
                                              (_ENGLISH, no_subs.NO_SPEECH, "no_speech")])
def test_no_speech_an_unreadable_video_or_another_language_writes_nothing_and_says_so(heard, note, key, fake):
    """Why: nothing made is nothing kept — the row says why (never a silent miss), and isn't offered again."""
    store, data_dir, src, root, (video,) = _library("ja")
    fake.set(heard_videos={os.path.basename(video): heard}, **READY)
    tree = _tree(src)
    try:
        out = _make(store, "ja")
        assert out[key] == 1 and out["made"] == 0
        (item_id, rel, availability), = _items(store)
        assert availability == "waiting" and no_subs.note(rel, "ja") == note
        assert not [n for _w, _d, files in os.walk(os.path.join(data_dir, ls.CONTENT_FOLDER)) for n in files]
        assert _tree(src) == tree
    finally:
        store.__exit__(None, None, None)


def test_a_cancel_keeps_nothing_and_leaves_no_row_at_making(fake):
    """Why: P1 — a cancel loses only the episode under way; nothing half-written, the row as it was."""
    store, data_dir, src, root, (video,) = _library("ja")
    fake.set(heard_videos={os.path.basename(video): _HEARD["ja"]}, transcribe_hold=5, **READY)
    stop = threading.Event()
    seen = []

    def progress(n, total, pct):
        seen.append(pct)
        if no_subs.note(_items(store)[0][1], "ja") == no_subs.MAKING:
            stop.set()
    try:
        out = _make(store, "ja", stop=stop.is_set, on_progress=progress)
        assert out["made"] == 0
        (_i, rel, availability), = _items(store)
        assert availability == "waiting" and no_subs.note(rel, "ja") is None
        assert not os.path.exists(_beside(video, "ja"))
    finally:
        store.__exit__(None, None, None)


def test_an_item_removed_meanwhile_keeps_nothing(fake, monkeypatch):
    """Why: the item no longer waits on that video: the copy made a moment ago goes, nothing beside the video."""
    store, data_dir, src, root, (video,) = _library("ja")
    fake.set(heard_videos={os.path.basename(video): _HEARD["ja"]}, **READY)
    monkeypatch.setattr(type(store), "fill_track", lambda self, *a, **k: False)
    try:
        out = _make(store, "ja")
        assert out["gone"] == 1 and out["made"] == 0
        assert not [n for _w, _d, files in os.walk(os.path.join(data_dir, ls.CONTENT_FOLDER)) for n in files]
        assert not os.path.exists(_beside(video, "ja"))
    finally:
        store.__exit__(None, None, None)


def test_an_anki_miner_that_cannot_listen_is_never_asked_to(fake):
    """Why: before 3.11 (no `transcribe` feature) nothing is offered or run."""
    store, data_dir, src, root, (video,) = _library("ja")
    fake.set(features=["named-words-whitelisted", "inspect", "tracks"], heard_videos={}, **READY)
    try:
        assert _make(store, "ja") == {"no_miner": True}
        assert not fake.calls("transcribe")
    finally:
        store.__exit__(None, None, None)


def test_no_speech_model_asks_first_then_its_install_lets_it_listen(fake):
    """Why: the model is a download (AB-Q2): never fetched without the learner's yes — `make` says so; after the yes,
    Anki Miner's own setup installs it and the episode is made."""
    store, data_dir, src, root, (video,) = _library("ja")
    fake.set(heard_videos={os.path.basename(video): _HEARD["ja"]}, speech={"installed": [], "model": "small"})
    try:
        assert _make(store, "ja") == {"no_model": True}
        assert not fake.calls("setup") and not fake.calls("transcribe")
        miner = no_subs.can_make({}, FAKE)
        assert no_subs.install_speech(miner, "ja") is None
        assert [c for c in fake.calls("setup") if "--speech-model" in c]
        assert _make(store, "ja")["made"] == 1
    finally:
        store.__exit__(None, None, None)


def test_one_episode_a_call_each_lighting_up_as_it_ends(fake):
    """Why: P1 — one `transcribe` per episode; each row filled before the next is asked."""
    store, data_dir, src, root, videos = _library("ja", names=("01", "02"))
    fake.set(heard_videos={os.path.basename(v): _HEARD["ja"] for v in videos}, **READY)
    filled = []
    real = type(store).fill_track

    def fill(self, item_id, *a, **k):
        filled.append((item_id, len(fake.calls("transcribe"))))
        return real(self, item_id, *a, **k)
    try:
        type(store).fill_track = fill
        assert _make(store, "ja")["made"] == 2
        assert [n for _i, n in filled] == [1, 2]
    finally:
        type(store).fill_track = real
        store.__exit__(None, None, None)


# --- the rows and the card ---------------------------------------------------------------------------------------- #
def _ep(subs, waiting=True, **kw):
    return view_rows.Episode(id=kw.pop("id", 1), label="Ep 1", number=1, title="x", watched=False, cards=0,
                             mining=False, missing=False, removed=False, in_top=False, pct=None, n_new=None,
                             status=None, mark=None, play_tip="", can_play=False, waiting=waiting, subs=subs, rel_path=kw.pop("rel", "Library/a/x"),
                             **kw)


def _shim(subs, **kw):
    return view_rows._Shim(_ep(subs, **kw), False)


def test_the_rows_say_what_is_happening_to_their_subtitle():
    """Why: a waiting row never just says *No subtitles yet* while one is being made or looked for (SPEC §9)."""
    st, _m = view_rows.status_of([_shim(no_subs.MAKING)], "video", None)
    assert st.label == "Making its subtitle from the audio…"
    st, _m = view_rows.status_of([_shim((no_subs.NOT_FOUND, "2026-11-03"), id=1),
                                  _shim((no_subs.NOT_FOUND, "2026-11-09"), id=2)], "video", None)
    assert st.label == "Not on jimaku yet · looks again 3 Nov"
    # Zh-H: a Chinese NOT_FOUND names hato's Chinese sites, never jimaku (PROVISIONAL words); Japanese as above
    st, _m = view_rows.status_of([_shim((no_subs.NOT_FOUND, "2026-11-03", "zh"), id=1),
                                  _shim((no_subs.NOT_FOUND, "2026-11-09", "zh"), id=2)], "video", None)
    assert st.label == "Not found online yet · looks again 3 Nov" and "jimaku" not in st.label + st.tip
    assert "assrt.net" in st.tip and "OpenSubtitles" in st.tip
    assert view_rows.STRINGS["arr_" + view_rows.SUBS_KEYS[view_rows.subs_said(
        [_shim((no_subs.NOT_FOUND, "2026-11-03", "zh"))])[0]]] == "not found online yet · looks again {date}"
    st, _m = view_rows.status_of([_shim(no_subs.NO_SPEECH, id=1), _shim(None, id=2)], "video", None)
    assert st.label == "No subtitles yet · 2", "a mix says the plain words"
    st, _m = view_rows.status_of([_shim(None)], "video", None)
    assert "fills it in by itself" not in st.tip, "never the claim only a hato you run yourself made true"


def _view(*rows):
    return view_rows.View(language="ja", mode="store", reason=None, state=None, busy=False, loading=False,
                          cached=False, rows=rows, lines=(), goal=None, finished=(), needs=(), counts=None,
                          subline="", badges=(), worst=())


def _row(work_id, title, eps):
    return view_rows.Row(**{**{f: None for f in view_rows.Row._fields}, "key": f"w{work_id}", "work_id": work_id,
                            "title": title, "episodes": tuple(eps), "media": "anime", "tier": "arrivals"})


def test_one_card_a_line_per_show_and_only_while_a_way_is_here():
    """Why: ONE card for every video with no subtitle (never one per video at 2,000 of them), a line per show with its
    own *Make them from the audio*; *Find them with hato* only while hato takes a list and the yes isn't given; none
    when neither way is here; a video being made, or one already heard silent, isn't offered."""
    view = _view(_row(1, "Frieren", [_ep(None, id=1), _ep(None, id=2), _ep(no_subs.MAKING, id=3)]),
                 _row(2, "Dandadan", [_ep(None, id=4), _ep(no_subs.NO_SPEECH, id=5)]))
    (card,) = [e for e in service.entries(view, no_subs={"make": True, "hato": True}) if e.kind == service.NO_SUBS]
    assert card.title == "3 videos have no subtitles yet"
    assert [(ln.text, ln.actions) for ln in card.lines] == [("Frieren (2)", ("make_from_audio",)),
                                                            ("Dandadan (1)", ("make_from_audio",))]
    assert card.actions == ("find_with_hato",) and card.data["item_ids"] == (1, 2, 4)
    (hato_only,) = [e for e in service.entries(view, no_subs={"make": False, "hato": True})
                    if e.kind == service.NO_SUBS]
    assert all(ln.actions == () for ln in hato_only.lines) and hato_only.key == card.key
    assert not [e for e in service.entries(view) if e.kind == service.NO_SUBS]
    more = _view(_row(1, "Frieren", [_ep(None, id=1), _ep(None, id=2), _ep(None, id=6)]))
    (again,) = [e for e in service.entries(more, no_subs={"make": True}) if e.kind == service.NO_SUBS]
    assert again.key != card.key, "a new waiting video brings the card back after *Not now*"


def test_no_offer_without_a_waiting_video_and_none_asked_of_anki_miner(monkeypatch):
    """Why: the offer's look asks Anki Miner (a process) — never for a library with nothing waiting."""
    asked = []
    monkeypatch.setattr(no_subs, "can_make", lambda settings, path=None: asked.append(1))
    assert service.no_subs_offer(_view(_row(1, "Frieren", [_ep(None, waiting=False)])), {}) is None
    assert not asked


# --- hato (only once it takes a list) ------------------------------------------------------------------------------ #
def _hato(verbs, cli, version="1.1.0"):
    folder = tools_entry.tools_dir()
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "hato.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "tool": "hato", "name": "hato", "version": version, "cli": cli, "app": None,
                   "contract": 1, "verbs": verbs, "updated": "2026-11-05T00:00:00Z"}, f)


class _Proc:
    """A hato run as `popen` hands it back: its NDJSON lines, then its end."""

    def __init__(self, lines, calls, command):
        import io
        calls.append(command)
        self.stdout = io.BytesIO(b"".join((json.dumps(x, ensure_ascii=False) + "\n").encode("utf-8") for x in lines))
        self.returncode = 0

    def poll(self):
        return 0

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


def test_todays_hato_is_never_sent_a_thing(tmp_path):
    """Why: hato 1.0.x lists only `pairings`: it can't take a list of waiting videos — nothing is started, whatever
    the learner said; and without the yes, not even a hato that could."""
    store, data_dir, src, root, (video,) = _library("ja")
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    calls = []
    try:
        _hato(["pairings"], cli)
        assert no_subs.find(store, "ja", {no_subs.SETTING: True}, popen=lambda c, **k: _Proc([], calls, c)) == \
            {"off": True}
        _hato(["pairings", "find"], cli)
        assert no_subs.find(store, "ja", {}, popen=lambda c, **k: _Proc([], calls, c)) == {"off": True}
        assert calls == []
    finally:
        store.__exit__(None, None, None)


def test_a_chinese_video_is_never_handed_to_hato_whose_subtitles_are_japanese(tmp_path):
    """Why (Zh-C, Chinese end to end): hato up to 1.2 searches jimaku.cc, Japanese anime subtitles, and its ranking
    never tries a file tagged with another language and no Japanese — asked with `--lang zh` it would put a Japanese
    subtitle beside a Chinese video, named as Chinese. With both libraries' yes and a 1.2 hato that takes a list, a
    Chinese look starts nothing; *Find them with hato* is never offered for Chinese; Japanese is asked as before."""
    store, data_dir, src, root, (video,) = _library("zh")
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    calls = []
    both = {no_subs.SETTING: True, no_subs.SETTING_ZH: True}
    try:
        _hato(["pairings", "find"], cli, version="1.2.1")
        assert no_subs.find(store, "zh", both, popen=lambda c, **k: _Proc([], calls, c)) == {"off": True}
        assert calls == [] and not no_subs.hato_on(both, "zh")
        assert no_subs.hato_on({no_subs.SETTING: True}, "ja"), "Japanese: hato as before"
        from app.services import needs
        from types import SimpleNamespace
        view = SimpleNamespace(language="zh")
        needs_waiting = needs.no_subs_waiting
        try:
            needs.no_subs_waiting = lambda v: [("row", "episode")]
            assert needs.no_subs_offer(view, {}) in (None, {"make": True, "hato": False})
            assert needs.no_subs_offer(SimpleNamespace(language="ja"), {})["hato"] is True
        finally:
            needs.no_subs_waiting = needs_waiting
    finally:
        store.__exit__(None, None, None)


@pytest.mark.parametrize("version, languages", [
    ("1.1.1", ("ja",)), ("1.2.1", ("ja",)), ("1.3.0", ("ja", "zh")), ("1.4.0", ("ja", "zh")),
    ("1.10.0", ("ja", "zh")), ("2.0.0", ("ja", "zh")), ("1.3.0rc1", ("ja",)), ("1.3.0.dev0", ("ja",)),
    (" 1.3.0", ("ja",)), ("\uff11.\uff13.\uff10", ("ja",)),
    ("1.3", ("ja",)), ("", ("ja",)), (None, ("ja",)), (130, ("ja",)), ("v1.3.0", ("ja",))])
def test_the_languages_hato_finds_subtitles_in_are_read_from_its_version(version, languages):
    """Why (Zh-H, 09-hato-layer.md §7.9): hato's tools entry says it finds Chinese subtitles only by its `version`
    (1.3.0, Layer 20) — compared as numbers (1.10 is after 1.3), in hato's own one shape (exactly X.Y.Z, ASCII digits:
    its `update.parse_version`); anything else is a hato that finds Japanese only: a Chinese video is never handed to a
    hato that would put a Japanese file beside it."""
    assert no_subs.hato_languages({"version": version}) == languages
    assert no_subs.hato_languages(None) == ("ja",)


def _zh_rows(videos, retry_after):
    """hato 1.3.0's NDJSON for a `--lang zh` run, as its real run printed it (Zh-H's connect_e2e, the 3.0 plan's
    tracks/pipeline/work/zh-h/E2E.md: hato 1.3.0 from source on assrt.net's recorded answers, no network): a Chinese file found and timed for the first
    video, written beside it as `.zh.ass`; nothing for the second, with hato's own date."""
    return [{"type": "progress", "phase": "walking", "folders": 1},
            {"type": "video", "video": videos[0], "outcome": "CONFIDENT", "retry_after": None,
             "output_path": os.path.splitext(videos[0])[0] + ".zh.ass", "reason": "",
             "jimaku_filename": "[Nekomoe kissaten] Sousou no Frieren - 01 [WebRip 1080p].chs.ass"},
            {"type": "video", "video": videos[1], "outcome": "NOT_FOUND", "retry_after": retry_after,
             "output_path": None, "jimaku_filename": None,
             "reason": f"No release on the entry places a file on episode 4. Will retry after {retry_after[:10]}."},
            {"type": "run", "videos": 2, "lang": "zh", "stopped": None}]


class _Said:
    """`subprocess.run`'s answer for `hato_says_zh`: its stdout and exit code."""

    def __init__(self, out, code=0):
        self.stdout, self.returncode = out, code


@pytest.mark.parametrize("answer, says", [
    (_Said(b"hato 1.3.0\r\n"), True), (_Said(b"hato 1.4.0\n"), True), (_Said(b"hato 1.2.1\n"), False),
    (_Said(b"hato 1.3.0\n", code=1), False), (_Said(b""), False), (_Said(b"hato 1.3.0rc1\n"), False),
    (_Said(b"tsubasa 1.3.0\n"), False), (_Said(None), False), (OSError("no such program"), False),
    # a hato that hangs on `--version`: its timeout is no OSError, and still never raises out (Zh-H mutant Y8)
    (subprocess.TimeoutExpired(["hato-cli.exe", "--version"], 30), False)])
def test_before_a_chinese_run_the_hato_program_itself_says_it_finds_chinese(answer, says):
    """Why (Zh-H, the adversary's MUST): hato's *Go back* to 1.2 leaves its tools entry naming 1.3.0 until the kept
    hato starts again (§7.1) — a Chinese run then would get jimaku's Japanese files named as Chinese. So the program
    is asked (`<cli> --version`, §3's quick verb, trusted over the file): only `hato X.Y.Z` at 1.3.0 or later says
    yes; no answer, another program, a failed call, another shape or an older version say no. Never raises."""
    asked = []

    def run(command, **kw):
        asked.append(command)
        if isinstance(answer, Exception):
            raise answer
        return answer
    assert no_subs.hato_says_zh("C:/hato/hato-cli.exe", run=run) is says
    assert asked == [["C:/hato/hato-cli.exe", "--version"]]


def test_a_chinese_video_goes_to_hato_1_3_once_the_chinese_library_said_yes(tmp_path, monkeypatch):
    """Why (Zh-H): hato 1.3.0 finds Chinese subtitles (assrt.net, then OpenSubtitles, on the learner's own keys). The
    Chinese library has its own yes — the Japanese card's yes named jimaku.cc and its key, so it never sends Chinese
    titles anywhere. With the Chinese yes, the waiting Chinese videos go to hato as a `--lang zh` run, and what it
    answers is kept in the Chinese library's own file: a found one's folder looked at again, a NOT_FOUND's date."""
    store, data_dir, src, root, videos = _library("zh", names=("01", "02"))
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    _hato(["pairings", "find"], cli, version="1.3.0")
    calls = []
    now = time.time()
    retry_after = datetime.datetime.fromtimestamp(now + 86400, datetime.timezone.utc).isoformat()
    lines = _zh_rows([os.path.abspath(v) for v in videos], retry_after)
    says = []
    monkeypatch.setattr(no_subs, "hato_says_zh", lambda c, run=None: says.append(c) or True)
    try:
        assert no_subs.find(store, "zh", {no_subs.SETTING: True}, now=now,
                            popen=lambda c, **k: _Proc(lines, calls, c)) == {"off": True}
        assert calls == [] and not no_subs.hato_on({no_subs.SETTING: True}, "zh"), "the Japanese yes is Japanese only"
        assert no_subs.hato_on({no_subs.SETTING_ZH: True}, "zh") and not no_subs.hato_on({no_subs.SETTING_ZH: True})
        out = no_subs.find(store, "zh", {no_subs.SETTING_ZH: True}, now=now,
                           popen=lambda c, **k: _Proc(lines, calls, c))
        assert (out["asked"], out["found"], out["not_found"], out["failed"]) == (2, 1, 1, 0)
        assert out["roots"] == {root: src} and says == [cli], "the program asked once, before the run"
        (command,) = calls
        assert command[:2] == [cli, src] and command[-2:] == ["--lang", "zh"]
        rel = [r for _i, r, _a in _items(store)][1]
        tomorrow = time.strftime("%Y-%m-%d", time.localtime(datetime.datetime.fromisoformat(retry_after).timestamp()))
        assert no_subs.note(rel, "zh") == (no_subs.NOT_FOUND, tomorrow, "zh") and no_subs.note(rel, "ja") is None
        assert no_subs.note(rel) == (no_subs.NOT_FOUND, tomorrow, "zh"), "either library's: the Chinese one says so"
        assert os.path.exists(no_subs.state_path("zh")) and not os.path.exists(no_subs.state_path("ja"))
        assert no_subs.due(store, "zh", now=now) == []
    finally:
        store.__exit__(None, None, None)


def test_a_hato_gone_back_to_1_2_under_an_entry_naming_1_3_is_handed_no_chinese_video(tmp_path):
    """Why (Zh-H, the adversary's MUST): after *Go back* the entry still names 1.3.0 while the program is 1.2.1 —
    the program's own answer wins: nothing is started, nothing waits (no failed-run hour), Japanese is not asked it."""
    store, data_dir, src, root, (video,) = _library("zh")
    cli = os.path.join(str(tmp_path), "hato-cli.cmd")
    with open(cli, "w", encoding="ascii") as f:
        f.write("@echo hato 1.2.1\r\n" if sys.platform == "win32" else "")
    if sys.platform != "win32":
        os.remove(cli)
        cli = str(tmp_path / "hato-cli")
        with open(cli, "w", encoding="ascii") as f:
            f.write("#!/bin/sh\necho hato 1.2.1\n")
        os.chmod(cli, 0o755)
    _hato(["pairings", "find"], cli, version="1.3.0")
    calls = []
    try:
        assert not no_subs.hato_says_zh(cli), "the program says 1.2.1"
        out = no_subs.find(store, "zh", {no_subs.SETTING_ZH: True}, popen=lambda c, **k: _Proc([], calls, c))
        assert out == {"off": True} and calls == []
        assert len(no_subs.due(store, "zh")) == 1, "no failed-run wait: asked again once the program is 1.3"
    finally:
        store.__exit__(None, None, None)


def test_hatos_chinese_file_fills_the_waiting_video_in_place_with_only_the_chinese_yes(tmp_path):
    """Why (Zh-H, read back): what hato 1.3.0 hands over for a Chinese video — its real pairing record (assrt.net's
    file, `language` zh, no jimaku entry; tests/Test Resources/connect/pairing_v1_zh_hato_1_3.json), its copy in the
    Chinese drop folder — is registered with only the Chinese library's yes (Connect off: Q3), and fills the waiting
    video's own item in place; the copy hato also wrote beside the video makes no second item at the next look."""
    from app.cli import connect_verbs
    from app.connect import videos as connect_videos
    store, data_dir, src, root, (video,) = _library("zh", names=("01",))
    try:
        (waiting_id,) = [i for i, _r, a in _items(store) if a == "waiting"]
        before = len(_items(store))
        stem = os.path.splitext(os.path.basename(video))[0]
        with open(os.path.join(RES, "zh", "night_market.srt"), "rb") as f:
            found = f.read()
        drop = os.path.join(data_dir, *ls.HATO_FOLDER.split("/"), _SHOW["zh"], stem + ".zh.srt")
        beside = os.path.join(os.path.dirname(video), stem + ".zh.srt")
        for path in (drop, beside):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(found)
        with open(os.path.join(RES, "connect", "pairing_v1_zh_hato_1_3.json"), encoding="utf-8") as f:
            record = json.load(f)
        import hashlib
        record.update({"content_key": connect_videos.content_key(video), "video_path": os.path.abspath(video),
                       "video_size": os.path.getsize(video), "subtitle_path": beside, "library_path": drop,
                       "subtitle_sha256": hashlib.sha256(found).hexdigest(),
                       "show": {"episode": 1, "movie": False, "season": None, "title": _SHOW["zh"]}})
        assert connect_verbs.register_record(record, "zh", wait=10.0, loaded={})["landed"] == "skipped"
        assert connect_verbs.register_record(record, "zh", wait=10.0, loaded={no_subs.SETTING: True})["landed"] == \
            "skipped", "the Japanese yes takes no Chinese file"
        answer = connect_verbs.register_record(record, "zh", wait=10.0, loaded={no_subs.SETTING_ZH: True})
        assert answer["file_id"] == waiting_id and answer["landed"] != "skipped", answer
        got = {i: (r, a) for i, r, a in _items(store)}
        assert len(got) == before and got[waiting_id][1] == "available"
        pairing = library.pairing_of(store, waiting_id)
        assert pairing["language"] == "zh" and pairing["subtitle_source"]["provider"] == "assrt"
        _look(store, "zh", root)
        assert len(_items(store)) == before and _waiting(store) == 0, "hato's copy beside the video: no second item"
    finally:
        store.__exit__(None, None, None)


def test_japanese_is_asked_as_before_whatever_hatos_version(tmp_path):
    """Why: "Japanese unchanged" — a 1.3.0 hato gets the same Japanese run, on the same yes, as a 1.1 one did."""
    store, data_dir, src, root, (video,) = _library("ja")
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    calls = []
    try:
        for version in ("1.1.1", "1.3.0"):
            _hato(["pairings", "find"], cli, version=version)
            assert no_subs.find(store, "ja", {no_subs.SETTING_ZH: True},
                                popen=lambda c, **k: _Proc([], calls, c)) == {"off": True}
            assert no_subs.hato_finds() == cli and no_subs.hato_finds(language="ja") == cli
        no_subs.find(store, "ja", {no_subs.SETTING: True}, popen=lambda c, **k: _Proc([], calls, c))
        (command,) = calls
        assert command[-2:] == ["--lang", "ja"]
    finally:
        store.__exit__(None, None, None)


def test_the_chinese_card_offers_hato_with_its_own_words_and_the_japanese_card_is_unchanged(tmp_path, monkeypatch):
    """Why (Zh-H; PROVISIONAL words): a Chinese library's card offers *Find them with hato* while hato 1.3 is here and
    that library hasn't said yes — the Japanese yes doesn't count for it — and says where hato looks for Chinese
    (assrt.net, then OpenSubtitles, with the learner's own keys), never jimaku. The Japanese card's words and press are
    as before."""
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    _hato(["pairings", "find"], cli, version="1.3.0")
    monkeypatch.setattr(no_subs, "can_make", lambda settings, path=None: None)
    zh = _view(_row(1, "夜市小记", [_ep(None)]))._replace(language="zh")
    ja = _view(_row(1, "Frieren", [_ep(None)]))
    assert service.no_subs_offer(zh, {no_subs.SETTING: True}) == {"make": False, "hato": True}
    assert service.no_subs_offer(zh, {no_subs.SETTING_ZH: True}) is None
    assert service.no_subs_offer(ja, {no_subs.SETTING_ZH: True}) == {"make": False, "hato": True}
    zh_card = service._no_subs_entry(zh, {"make": False, "hato": True}, set())
    ja_card = service._no_subs_entry(ja, {"make": False, "hato": True}, set())
    assert zh_card.actions == ("find_with_hato_zh",) and ja_card.actions == ("find_with_hato",)
    assert "assrt.net" in zh_card.say and "OpenSubtitles" in zh_card.say and "jimaku" not in zh_card.say
    assert ja_card.say == service.STRINGS["no_subs_say_hato"] and "jimaku" in ja_card.say
    _hato(["pairings", "find"], cli, version="1.2.1")
    assert service.no_subs_offer(zh, {}) is None, "a 1.2 hato: no Chinese offer"


def test_hato_found_one_not_the_other_its_retry_date_kept_outside_the_library(tmp_path):
    """Why: NS-2 — the waiting videos alone, by list file; a found one's folder is looked at again (K5 fills it); a
    NOT_FOUND waits for hato's own date (P5), its row saying it, and is asked again on that date."""
    store, data_dir, src, root, videos = _library("ja", names=("01", "02"))
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    _hato(["pairings", "find"], cli)
    calls = []
    # hato's retry date is a day ahead of the run, whatever day the suite runs on (a fixed date stopped being "ahead")
    now = time.time()
    retry_after = datetime.datetime.fromtimestamp(now + 86400, datetime.timezone.utc).isoformat()
    lines = [{"type": "progress", "done": 1}, {"type": "video", "video": videos[0], "outcome": "CONFIDENT"},
             {"type": "video", "video": videos[1], "outcome": "NOT_FOUND", "retry_after": retry_after},
             {"type": "run", "videos": 2}]
    try:
        out = no_subs.find(store, "ja", {no_subs.SETTING: True}, now=now,
                           popen=lambda c, **k: _Proc(lines, calls, c))
        assert (out["asked"], out["found"], out["not_found"]) == (2, 1, 1) and out["roots"] == {root: src}
        (command,) = calls
        assert command[:2] == [cli, src] and "--only-list" in command and "--json" in command
        rel = [r for _i, r, _a in _items(store)][1]
        assert no_subs.note(rel, "ja")[0] == no_subs.NOT_FOUND
        later = now + 2 * 86400
        assert {v.video for v in no_subs.due(store, "ja", now=now)} == set()
        assert {v.video for v in no_subs.due(store, "ja", now=later)} == {os.path.abspath(v) for v in videos}
        assert not any("hato" in json.dumps(r) for r in [library.pairing_of(store, i) for i, _r, _a in _items(store)])
    finally:
        store.__exit__(None, None, None)


def test_a_hato_run_that_fails_as_a_whole_waits_an_hour(tmp_path):
    """Why: P4 — offline or a crash: nothing pops up, nothing is asked again before OFFLINE_S."""
    store, data_dir, src, root, (video,) = _library("ja")
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    _hato(["find"], cli)
    try:
        now = time.time()
        out = no_subs.find(store, "ja", {no_subs.SETTING: True}, now=now, popen=lambda c, **k: _Proc([], [], c))
        assert out["failed"] == 1 and not out["roots"]
        assert no_subs.due(store, "ja", now=now + 60) == []
        assert len(no_subs.due(store, "ja", now=now + no_subs.OFFLINE_S + 1)) == 1
    finally:
        store.__exit__(None, None, None)


def test_a_silent_hato_run_is_stopped(tmp_path, monkeypatch):
    """Why: P3 — a hato that hangs never holds the looks' worker for ever."""
    store, data_dir, src, root, (video,) = _library("ja")
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    _hato(["find"], cli)
    monkeypatch.setattr(no_subs, "HATO_SILENT_S", 0.5)
    started = time.monotonic()
    try:
        out = no_subs.find(store, "ja", {no_subs.SETTING: True}, popen=lambda c, **k: subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"], stdout=subprocess.PIPE, stdin=subprocess.DEVNULL))
        assert out["failed"] == 1 and time.monotonic() - started < 15
    finally:
        store.__exit__(None, None, None)


def test_register_is_listed_for_hato_once_the_learner_said_yes_with_connect_off():
    """Why: Q3 — finding subtitles is about the library, not cards; either library's yes (Zh-H: hato hands a Chinese
    file over through `register` too when its `write_beside_video` is off)."""
    assert not tools_entry.registers({})
    assert tools_entry.registers({no_subs.SETTING: True})
    assert tools_entry.registers({no_subs.SETTING_ZH: True}), "the verb is listed on either library's yes"
    # Zh-H (the adversary's SHOULD): a pairing is taken only on its own library's yes (or Connect on)
    assert tools_entry.registers({no_subs.SETTING: True}, "ja") and not tools_entry.registers({no_subs.SETTING: True}, "zh")
    assert tools_entry.registers({no_subs.SETTING_ZH: True}, "zh") and not tools_entry.registers({no_subs.SETTING_ZH: True}, "ja")
    assert tools_entry.registers({"connect_enabled": True}, "zh") and tools_entry.registers({"connect_enabled": True}, "ja")
    assert tools_entry.registers({"connect_enabled": True})


def test_connect_mines_a_made_subtitle_with_its_tag_and_no_other_episode(tmp_path):
    """Why: Q5 — only an episode whose record says `transcribed` carries `surasura::from-audio` to Anki Miner."""
    from app.connect import runner
    from app.connect.ledger import Ledger
    from tests.connect.fake_steps import FakeSteps
    plan = {"queue": {"ja": [1, 2]}, "line": {"ja": [1, 2]},
            "pairings": {"1": {"producer": "source", "verdict": "transcribed"},
                         "2": {"producer": "source", "verdict": "extracted"}}}
    steps = FakeSteps(str(tmp_path), plan)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        with ledger.transaction():
            made = ledger.queue("ja", 1, "user", None, store_id="store-1")
            track = ledger.queue("ja", 2, "user", None, store_id="store-1")
        assert runner._pick(steps, ledger, "ja", ledger.job_by_id(made)).get("from_audio") is True
        assert "from_audio" not in runner._pick(steps, ledger, "ja", ledger.job_by_id(track))


def test_connect_tags_an_origin_the_store_says_was_heard_and_never_another_record(tmp_path):
    """Why: Hato-SP — the tag rides on the store's answer (`Steps.heard`), asked only for a source folder's origin
    (`producer` "source"): hato's own record for an episode is hato's text (a jimaku file), never one made from audio."""
    from app.connect import runner
    from app.connect.ledger import Ledger
    from tests.connect.fake_steps import FakeSteps
    plan = {"queue": {"ja": [1, 2, 3]}, "line": {"ja": [1, 2, 3]}, "heard": [1, 3],
            "pairings": {"1": {"producer": "source"}, "2": {"producer": "source"}, "3": {"schema": 1, "verdict": "timed"}}}
    steps = FakeSteps(str(tmp_path), plan)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        with ledger.transaction():
            jobs = [ledger.queue("ja", n, "user", None, store_id="store-1") for n in (1, 2, 3)]
        got = [runner._pick(steps, ledger, "ja", ledger.job_by_id(j)).get("from_audio") for j in jobs]
    assert got == [True, None, None]


def _heard_library(language, before_first_look, also_plain=False):
    """A source folder: one video and hato's `<video>.<lang>.from-audio.srt` beside it — written before the first look,
    or after it (the video waited, K5, and the next look fills the item in place). `also_plain`: a person's
    `<video>.<lang>.srt` there too, from the start."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    video = _video(os.path.join(src, _SHOW[language], f"[Grp] {_SHOW[language]} - 05 (1080p).mkv"),
                   body=b"\x1a\x45\xdf\xa3 matroska 05")
    made = no_subs.beside_path(video, language)
    if also_plain:
        _write(os.path.splitext(video)[0] + f".{language}.srt", _text(language, 5))
    if before_first_look:
        _write(made, _HEARD[language])                                  # settled, as a finished file is
    store.__enter__()
    root = store.add_source(src)
    _look(store, language, root, first=True)
    if not before_first_look:
        assert _waiting(store) == 1
        _write(made, _HEARD[language])
        _look(store, language, root, full=True)
    return store, video, made


@pytest.mark.parametrize("before_first_look", [True, False], ids=["there-first", "after-the-video-waited"])
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_from_audio_subtitle_hato_made_is_read_as_its_episode_and_heard(language, before_first_look):
    """Why: Hato-SP end to end on the store — a video whose only subtitle is hato's `<video>.<lang>.from-audio.srt`:
    the look takes it as that video's episode (one item, available, never waiting) and the store says its text was
    made from the audio, whether the file was there first or filled a waiting item later (then the item's pairing is
    still the VIDEO's origin row: the review's case). Nothing is written beside the video (S3)."""
    store, video, made = _heard_library(language, before_first_look)
    try:
        (item_id, _rel, availability), = _items(store)
        assert availability == "available" and _waiting(store) == 0
        record = library.pairing_of(store, item_id)
        assert record["producer"] == "source" and "verdict" not in record
        if not before_first_look:       # the item's pairing is its video's row: why every live origin is read
            assert record["origin"] == os.path.abspath(video)
        assert library.heard(store, item_id) is True
        assert sorted(os.listdir(os.path.dirname(video))) == sorted([os.path.basename(video), os.path.basename(made)])
    finally:
        store.__exit__(None, None, None)


def test_a_persons_subtitle_beside_hatos_made_one_is_the_text_and_nothing_is_heard():
    """Why: Hato-SP — with a real subtitle there too, the look reads the person's file (`subtitle_rank`: a re-timer's
    mark after a plain one) and keeps hato's as another version of the episode: no card of it says *from audio*."""
    store, video, made = _heard_library("ja", True, also_plain=True)
    try:
        (item_id, rel, _a), = _items(store)
        assert not rel.endswith(".from-audio.srt")
        assert library.heard(store, item_id) is False
    finally:
        store.__exit__(None, None, None)


def test_a_film_with_no_episode_number_stays_one_item_after_the_next_look(fake):
    """Why: a film's name carries no episode number, so only its name pairs the copy beside it with the video: the
    `from-audio` mark must come off the stem (`episode_names.FROM_AUDIO`), or the next look makes a second title."""
    store, data_dir = _empty("ja")
    src = _drive("driveA")
    video = _video(os.path.join(src, "映画", "君の名は (2016) [1080p].mkv"), body=b"\x1a\x45\xdf\xa3 film")
    store.__enter__()
    try:
        root = store.add_source(src)
        _look(store, "ja", root, first=True)
        assert _waiting(store) == 1
        fake.set(heard_videos={os.path.basename(video): _HEARD["ja"]}, **READY)
        assert _make(store, "ja")["made"] == 1
        before = _items(store)
        _look(store, "ja", root, full=True)
        assert _items(store) == before
    finally:
        store.__exit__(None, None, None)


# --- the adversary's round 1 (register: tracks/pipeline/reviews/no-subs-register.md) -------------------------------- #
def test_a_making_note_a_surasura_that_quit_left_is_no_note(fake):
    """Why (MUST 1): a crash or a quit mid-episode skips the clean-up; the row must not say *Making…* for ever, nor be
    left out of the offer and hato's list."""
    store, data_dir, src, root, (video,) = _library("ja")
    (item_id, rel, _a), = _items(store)
    try:
        no_subs._change(store, "ja", notes={rel: no_subs.MAKING})
        assert no_subs.note(rel, "ja") == no_subs.MAKING
        path = no_subs.state_path("ja")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["notes"][rel][2] = os.getpid() + 100000          # another (gone) process's
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        no_subs._NOTES.clear()
        assert no_subs.note(rel, "ja") is None
        assert [v.rel for v in no_subs.due(store, "ja")] == [rel]
    finally:
        store.__exit__(None, None, None)


def test_a_rows_note_costs_a_dict_look_not_a_stat(monkeypatch):
    """Why (MUST 2): the view builder asks every row — 20k rows must never mean 40k stats on the reader's thread."""
    no_subs._NOTES.clear()
    no_subs.note("Library/a/x.srt", "ja")
    calls = []
    real = os.stat
    monkeypatch.setattr(no_subs.os, "stat", lambda *a, **k: calls.append(a) or real(*a, **k))
    for n in range(2000):
        no_subs.note(f"Library/a/{n}.srt", "ja")
    assert len(calls) <= 2


def test_a_copy_beside_the_video_is_never_left_half_written(fake, monkeypatch):
    """Why (SHOULD 4): a disk that fills or a share that drops mid-write leaves nothing beside the video."""
    store, data_dir, src, root, (video,) = _library("ja")
    fake.set(heard_videos={os.path.basename(video): _HEARD["ja"]}, **READY)

    def broken(fd):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(no_subs.os, "fsync", broken)
    try:
        out = _make(store, "ja")
        assert out["made"] == 1 and out["beside_refused"] == 1
        folder = os.path.dirname(video)
        assert sorted(os.listdir(folder)) == [os.path.basename(video)], "no half file, no temp left"
    finally:
        store.__exit__(None, None, None)


def test_hato_never_takes_or_writes_over_a_show_being_made(fake, tmp_path):
    """Why (SHOULD 5): a press marks its whole show at once; hato's list leaves it out and its answer never replaces
    *Making…*."""
    store, data_dir, src, root, videos = _library("ja", names=("01", "02"))
    fake.set(heard_videos={os.path.basename(v): _HEARD["ja"] for v in videos}, **READY)
    seen = []
    try:
        _make(store, "ja", on_progress=lambda n, total, pct: seen.append(len(no_subs.due(store, "ja"))))
        assert seen and seen[0] == 0, "while a show is made, none of it is due for hato"
    finally:
        store.__exit__(None, None, None)


def test_hatos_answer_never_writes_over_making(tmp_path):
    store, data_dir, src, root, (video,) = _library("zh")
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    _hato(["find"], cli)
    (item_id, rel, _a), = _items(store)
    try:
        no_subs._change(store, "zh", notes={rel: no_subs.MAKING})
        v = no_subs.waiting(store)[0]
        # hato's retry date ahead of the run, whatever day the suite runs on (a fixed 2027-01-01 would pass)
        ahead = datetime.datetime.fromtimestamp(time.time() + 30 * 86400, datetime.timezone.utc).isoformat()
        lines = [{"type": "video", "video": video, "outcome": "NOT_FOUND", "retry_after": ahead}]
        no_subs._hato_run(store, "zh", cli, src, [v], str(tmp_path), lambda: False, None, {"asked": 0, "found": 0,
                          "not_found": 0, "failed": 0}, lambda c, **k: _Proc(lines, [], c))
        assert no_subs.note(rel, "zh") == no_subs.MAKING
    finally:
        store.__exit__(None, None, None)


def test_a_tidy_beside_a_hato_run_never_drops_its_looking_note(tmp_path):
    """Why (Minato-SM): `tidy` (the tracks' worker) and hato's run (its own worker) now run side by side; a tidy whose
    read of the waiting rows predates the run's LOOKING note never takes that note away — the run drops it at its end."""
    store, data_dir, src, root, (video,) = _library("ja")
    (item_id, rel, _a), = _items(store)
    try:
        no_subs._change(store, "ja", notes={rel: no_subs.LOOKING})
        no_subs._change(store, "ja", live={})                        # a tidy that read no waiting row
        assert no_subs.note(rel, "ja") == no_subs.LOOKING
        no_subs._change(store, "ja", drop_if={rel: no_subs.LOOKING})  # the run's end
        assert no_subs.note(rel, "ja") is None
    finally:
        store.__exit__(None, None, None)


def test_a_video_hato_said_nothing_of_waits_an_hour(tmp_path):
    """Why (SHOULD 7): a path hato wrote another way, or a cut run, never means asking again at every look."""
    store, data_dir, src, root, videos = _library("ja", names=("01", "02"))
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    _hato(["find"], cli)
    lines = [{"type": "video", "video": videos[0], "outcome": "NOT_FOUND", "retry_after": "2000-01-01T00:00:00"}]
    try:
        now = time.time()
        no_subs.find(store, "ja", {no_subs.SETTING: True}, now=now, popen=lambda c, **k: _Proc(lines, [], c))
        assert no_subs.due(store, "ja", now=now + 60) == [], "a date already past and a video not answered: an hour"
        assert len(no_subs.due(store, "ja", now=now + no_subs.OFFLINE_S + 1)) == 2
    finally:
        store.__exit__(None, None, None)


def test_no_speech_is_offered_again_once_its_video_changed(fake):
    """Why (SHOULD 8): *No speech found* holds for that file only; a replaced video is asked again."""
    store, data_dir, src, root, (video,) = _library("ja")
    fake.set(heard_videos={os.path.basename(video): "no_speech"}, **READY)
    (item_id, rel, _a), = _items(store)
    try:
        _make(store, "ja")
        no_subs.tidy(store, "ja")
        assert no_subs.note(rel, "ja") == no_subs.NO_SPEECH, "the same file: still said"
        _video(video, body=b"\x1a\x45\xdf\xa3 a better release, with its audio", age=10)
        no_subs._NOTES.clear()
        no_subs.tidy(store, "ja")
        assert no_subs.note(rel, "ja") is None
    finally:
        store.__exit__(None, None, None)


def test_a_cancel_during_the_speech_models_setup_ends_the_wait_at_once(fake):
    """Why (SHOULD 3): its Cancel works during the download too; Anki Miner's own setup goes on by itself."""
    fake.set(speech={"installed": [], "model": "small"}, speech_setup="hang")
    miner = no_subs.can_make({}, FAKE)
    started = time.monotonic()
    assert no_subs.install_speech(miner, "ja", cancel=lambda: time.monotonic() - started > 0.5) == no_subs.STOPPED
    assert time.monotonic() - started < 4


@pytest.mark.parametrize("film", [False, True])
def test_a_beside_copy_the_learner_corrected_is_still_the_same_episode(film, fake):
    """Why: the learner fixes a misheard word in the copy beside the video — other bytes now, so only the name pairs it
    (the `from-audio` mark off the stem) and only the made item's verdict makes it a version (`_track_items`): never a
    second item, never a fill over the made text."""
    store, data_dir = _empty("ja")
    src = _drive("driveA")
    name = "君の名は (2016) [1080p].mkv" if film else f"[Grp] {_SHOW['ja']} - 05 (1080p).mkv"
    video = _video(os.path.join(src, "映画" if film else _SHOW["ja"], name), body=b"\x1a\x45\xdf\xa3 x")
    store.__enter__()
    try:
        root = store.add_source(src)
        _look(store, "ja", root, first=True)
        fake.set(heard_videos={name: _HEARD["ja"]}, **READY)
        assert _make(store, "ja")["made"] == 1
        before = _items(store)
        with open(_beside(video, "ja"), "a", encoding="utf-8") as f:
            f.write("\n4\n00:01:44,000 --> 00:01:46,000\nそれでは、カードを作りましょう。\n")
        _look(store, "ja", root, full=True)
        assert _items(store) == before
        (item_id, _rel, _a), = before
        # the look leaves it with its video's episode (never a record of its own); the made text stays the item's
        assert not store.conn.execute("SELECT 1 FROM pairings WHERE content_key LIKE '%from-audio%'").fetchone()
        assert library.pairing_of(store, item_id)["verdict"] == "transcribed"
    finally:
        store.__exit__(None, None, None)


# --- Mado-FU2: *Next in line…* while hato's search waits its turn (Sonic 2026-11-13, "7. Fix this yea") ------------ #
class _Paced:
    """A hato run whose lines arrive one step at a time: `step()` lets the next one through (its stdout's
    `readline` waits for it), so a test sees what the rows say between them."""

    def __init__(self, lines, command, calls):
        import queue
        calls.append(command)
        self.q, self.lines, self.returncode = queue.Queue(), list(lines), 0
        self.stdout = self

    def step(self, n=1):
        for _ in range(n):
            if self.lines:
                self.q.put((json.dumps(self.lines.pop(0), ensure_ascii=False) + "\n").encode("utf-8"))
        if not self.lines:
            self.q.put(b"")                                   # its end

    def readline(self):
        return self.q.get(timeout=20)

    def poll(self):
        return 0

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


def _until(fn, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.05)
    return fn()


def test_fresh_u_a_video_waiting_behind_another_hato_run_says_next_in_line_until_its_search_starts(tmp_path):
    """Why (Minato-SM's finding; Sonic: "Fix this"): `--wait` queues a run behind another hato (its window, another
    library's run) for up to hours, and its videos said *Looking…* all along. Now: *Next in line* from the moment they
    are handed over and while hato says it waits; *Looking* from its first line that is the search itself; nothing
    once the run ends (its answers say the rest)."""
    store, data_dir, src, root, videos = _library("ja", names=("01", "02"))
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    _hato(["find"], cli)
    rels = [r for _i, r, _a in _items(store)]
    lines = [{"type": "progress", "phase": "waiting", "stage": "waiting for another hato run to finish"},
             {"type": "progress", "phase": "start", "folders": 1},
             {"type": "video", "video": videos[0], "outcome": "CONFIDENT"},
             {"type": "video", "video": videos[1], "outcome": "NOT_FOUND", "retry_after": None},
             {"type": "run", "videos": 2}]
    runs, calls, said = [], [], []

    def started(command, **_k):
        runs.append(_Paced(lines, command, calls))
        return runs[-1]

    def hato_side():
        # (one connection a thread: `find` keeps the store on this test's thread; this side reads only the notes file)
        notes = lambda: [no_subs.note(r, "ja") for r in rels]
        if not _until(lambda: runs):
            return
        said.append(notes())                                  # handed over
        runs[0].step()                                        # hato: waiting for another run
        time.sleep(0.8)                                       # (past a look of the run's loop)
        said.append(notes())
        runs[0].step()                                        # hato's own search begins
        _until(lambda: notes() == [no_subs.LOOKING] * 2)
        said.append(notes())
        runs[0].step(3)
    side = threading.Thread(target=hato_side, daemon=True)
    try:
        side.start()
        out = no_subs.find(store, "ja", {no_subs.SETTING: True}, popen=started)
        side.join(20)
        assert said == [[no_subs.QUEUED] * 2, [no_subs.QUEUED] * 2, [no_subs.LOOKING] * 2]
        assert out["asked"] == 2
        assert no_subs.note(rels[0], "ja") is None and no_subs.note(rels[1], "ja")[0] == no_subs.NOT_FOUND
    finally:
        for r in runs:
            r.step(len(r.lines) + 1)
        side.join(20)
        store.__exit__(None, None, None)


def test_fresh_u_a_run_that_never_got_its_turn_leaves_no_next_in_line_behind(tmp_path):
    """Why: the window closing (stop) mid-wait, or hato saying nothing at all, must never leave *Next in line* on a
    row; and a video being made from its audio meanwhile keeps saying so (never written over)."""
    store, data_dir, src, root, videos = _library("ja", names=("01", "02"))
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    _hato(["find"], cli)
    rels = [r for _i, r, _a in _items(store)]
    try:
        no_subs._change(store, "ja", notes={rels[1]: no_subs.MAKING})
        seen = []

        def started(command, **_k):
            seen.append([no_subs.note(r, "ja") for r in rels])
            return _Proc([{"type": "progress", "phase": "waiting", "stage": "waiting"}], [], command)
        no_subs.find(store, "ja", {no_subs.SETTING: True}, popen=started)
        assert seen == [[no_subs.QUEUED, no_subs.MAKING]]
        assert no_subs.note(rels[0], "ja") is None and no_subs.note(rels[1], "ja") == no_subs.MAKING
    finally:
        store.__exit__(None, None, None)


def test_fresh_u_next_in_line_is_this_processs_note_and_a_tidy_keeps_it():
    """Why: like *Looking*, a note a Surasura that quit left is no note (`_live`), and the tracks' tidy beside the run
    never drops it (the run does, at its end)."""
    assert no_subs.QUEUED in no_subs.TRANSIENT and no_subs.QUEUED in no_subs.WAITING_NOTES
    assert not no_subs._live([no_subs.QUEUED, None, os.getpid() + 1])
    assert no_subs._live(no_subs._entry(no_subs.QUEUED))


def test_fresh_u_the_rows_say_next_in_line_and_looking_wins_a_mix_of_the_two():
    """Why: the row's words (PROVISIONAL): *Next in line…* while every waiting video waits its turn; one already being
    looked for makes the row *Looking for subtitles…*; the tray's line the same, lower case."""
    st, _m = view_rows.status_of([_shim(no_subs.QUEUED, id=1), _shim(no_subs.QUEUED, id=2)], "video", None)
    assert st.label == "Next in line…" and "hato" in st.tip
    assert st.tone == "dim"
    st, _m = view_rows.status_of([_shim(no_subs.QUEUED, id=1), _shim(no_subs.LOOKING, id=2)], "video", None)
    assert st.label == "Looking for subtitles…"
    assert view_rows.STRINGS["arr_" + view_rows.SUBS_KEYS[view_rows.subs_said(
        [_shim(no_subs.QUEUED)])[0]]] == "next in line…"

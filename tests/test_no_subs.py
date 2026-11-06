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
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _tree, _video, _waiting  # noqa: F401

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
def _hato(verbs, cli):
    folder = tools_entry.tools_dir()
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "hato.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "tool": "hato", "name": "hato", "version": "1.1.0", "cli": cli, "app": None,
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


def test_hato_found_one_not_the_other_its_retry_date_kept_outside_the_library(tmp_path):
    """Why: NS-2 — the waiting videos alone, by list file; a found one's folder is looked at again (K5 fills it); a
    NOT_FOUND waits for hato's own date (P5), its row saying it, and is asked again on that date."""
    store, data_dir, src, root, videos = _library("ja", names=("01", "02"))
    cli = str(tmp_path / "hato-cli.exe")
    open(cli, "wb").close()
    _hato(["pairings", "find"], cli)
    calls = []
    lines = [{"type": "progress", "done": 1}, {"type": "video", "video": videos[0], "outcome": "CONFIDENT"},
             {"type": "video", "video": videos[1], "outcome": "NOT_FOUND", "retry_after": "2026-11-09T00:00:00+00:00"},
             {"type": "run", "videos": 2}]
    try:
        now = time.time()
        out = no_subs.find(store, "ja", {no_subs.SETTING: True}, now=now,
                           popen=lambda c, **k: _Proc(lines, calls, c))
        assert (out["asked"], out["found"], out["not_found"]) == (2, 1, 1) and out["roots"] == {root: src}
        (command,) = calls
        assert command[:2] == [cli, src] and "--only-list" in command and "--json" in command
        rel = [r for _i, r, _a in _items(store)][1]
        assert no_subs.note(rel, "ja")[0] == no_subs.NOT_FOUND
        later = time.mktime((2026, 11, 10, 0, 0, 0, 0, 0, -1))
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
    """Why: Q3 — finding subtitles is about the library, not cards."""
    assert not tools_entry.registers({})
    assert tools_entry.registers({no_subs.SETTING: True})
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
        lines = [{"type": "video", "video": video, "outcome": "NOT_FOUND", "retry_after": "2027-01-01T00:00:00Z"}]
        no_subs._hato_run(store, "zh", cli, src, [v], str(tmp_path), lambda: False, None, {"asked": 0, "found": 0,
                          "not_found": 0, "failed": 0}, lambda c, **k: _Proc(lines, [], c))
        assert no_subs.note(rel, "zh") == no_subs.MAKING
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

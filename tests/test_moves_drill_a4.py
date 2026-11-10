"""Drill A4 — a show moved to a NAS folder Surasura reads (the moves scope §5; Sonic's MV-1, MV-2, MV-3): nothing the
learner made of the show moves, nothing is counted twice, nothing is read again.

The library: `A/[Grp] Show/` with four real episodes and `A/[Grp] Show2/` holding only a video (it waits for its
subtitle), taken in by setup's scan; episode 2 put in Soon, episode 1 watched (set aside, W-1: *Keep studying watched
episodes* off), episode 4 Finished; a real Generate (its own process, as the dashboard runs it) and an index. That
state is S0: every row's id, tier, place, ✓, show and copy; what the token store holds; the lists and the run signature
byte for byte; what each folder counts.

  4a       app closed: both shows moved to the NAS (B, a "network" folder), B added, both looked at, the disk sync, an
           index, a Generate — with and without a folder level added (`B/2024 Fall/…`);
  4a+      then the show's next episode and a v2 of episode 3, in the new place;
  MV-2     the show moved where no source reads: nothing joins, nothing is added; *Find its folder*'s call (the picked
           folder added as a read folder: the show's own, or the one above it) — the show joins, no duplicate;
  4b       app open: the move during an index the window started, then a focus and a Refresh (the window's own
           services: `SourceLooks`, `Chores`);
  4b.3     the NAS unplugged and the app started again.

What a wrong answer costs a learner: his show twice in the window, its next episode in New arrivals as a new title, a
waiting video twice, words counted twice, a Generate (or a re-tokenizing) for a move that changed no text, or episodes
dropped when the NAS is off. Japanese and Chinese alike, real texts from tests/Test Resources/, made-up show names, a
few bytes as a fake video; both "drives" are temp folders beside the test's data folder (never a real drive: the
`subst` twin is not needed — `local_or_network` is what makes B "network", monkeypatched).
"""
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

import pytest

from app import library_store as ls
from app import sources
from app import token_index as ti
from tests.test_finished_reference import _spy_tokenizing
from tests.plan_file_cases import child_env
from tests.test_generate_watched import LIST, REPO, REUSED
from tests.test_library_store_support import LANGUAGES, RESOURCES, roots
from tests.test_sources_scan import (_OURS, _SHOWS, _drive, _empty, _fresh_module_state, _library_files,  # noqa: F401
                                     _look, _settle, _sha, _video, _write)
from tests.test_token_store_kept import _run_indexer

LEVEL = "2024 Fall"
# Each episode a real subtitle: the lines of one resource as cues (the Chinese ones are texts: a .txt read as an
# .srt would hold no words), told apart by the resource and by the episode's own last cue
_SOURCES = {"ja": ("placed_episode.srt", "library_episode.ass", "phrases_sample.srt", "tv_captions.ass"),
            "zh": ("night_market.srt", "chinese_text_1.txt", "traditional_news.txt", "mixed_script_transcript.txt")}
_LAST = {"ja": "また来週、ここで会おうね。", "zh": "我们下个星期再见吧。"}


def _lines(language, name):
    with open(os.path.join(RESOURCES, language, name), encoding="utf-8-sig") as f:
        text = f.read()
    if name.endswith(".srt"):
        return [line for block in text.strip().split("\n\n") for line in block.splitlines()[2:] if line.strip()]
    if name.endswith(".ass"):
        return [line.split(",", 9)[9].replace("\\N", " ") for line in text.splitlines()
                if line.startswith("Dialogue:")]
    return [line.strip() for line in text.splitlines() if line.strip()]


def _episode(language, n, version=""):
    lines = _lines(language, _SOURCES[language][n % 4])[:40] + [f"{_LAST[language]}{n}{version}"]
    return "".join(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\n{line}\n\n" for i, line in enumerate(lines, 1))


def _name(show, n, language, v=""):
    return f"[Grp] {show} - {n:02d}{v}.{_OURS[language]}.srt"


def _shows(language):
    return f"[Grp] {_SHOWS[language][1]}", f"[Grp] {_SHOWS[language][0]}"


def _generate(root, language, said=False):
    """A full Generate in its own process, as the dashboard runs it (test_generate_watched's), saying what it printed
    when it wrote no list."""
    cmd = [sys.executable, os.path.join(REPO, "app", "analyzer.py"), f"--language={language}", "--static",
           "--no-open", "--min-freq", "1"]
    p = subprocess.run(cmd, cwd=REPO, env=child_env(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0 and os.path.isfile(os.path.join(root, "results", LIST)), (p.stdout + p.stderr)[-3000:]
    subprocess.run([sys.executable, os.path.join(REPO, "app", "library_store.py"), "maintain", "--language", language],
                   cwd=REPO, env=child_env(root), capture_output=True)
    with open(os.path.join(root, "results", LIST), "rb") as f:
        return (f.read(), p.stdout) if said else f.read()


def _reopen(language):
    data_dir, user_files_dir = roots(language)
    return ls.open_store(language, data_dir, user_files_dir)


def _seed(language, monkeypatch, b_first=False):
    """The drill's library, Generated and indexed -> (store closed, data_dir, A, B, {episode: id}, the waiting id,
    S0). `b_first`: B added (empty) before S0, as for the window's drill."""
    monkeypatch.setattr(sources, "local_or_network", lambda path: "network")
    store, data_dir = _empty(language)
    show, show2 = _shows(language)
    a, b = _drive("driveA"), _drive("driveB")
    for n in (1, 2, 3, 4):
        _write(os.path.join(a, show, _name(show[6:], n, language)), _episode(language, n))
    _video(os.path.join(a, show2, f"[Grp] {show2[6:]} - 01.mkv"))
    _settle(a)
    with store:
        first = _look(store, language, store.add_source(a), first=True)
        if b_first:
            store.add_source(b)
        ids = {}
        for i in first["ids"]:
            rel = store.item(i)["rel_path"]
            ids["waiting" if rel.endswith(".mkv") else rel.rsplit(" - ", 1)[1][:2]] = i
        assert store.move([ids["02"]], "soon") is not None
        assert store.set_watched([ids["01"]]) is not None
        assert store.finish([ids["04"]]) is not None
    _generate(os.environ["SURASURA_TEST_ROOT"], language)
    _run_indexer(language)
    return data_dir, a, b, ids, _state(language)


def _state(language):
    """What S0 holds: the rows, the token store's lists and rows, the library listing, New arrivals, each folder's
    count, the lists' bytes and the run signature."""
    root = os.environ["SURASURA_TEST_ROOT"]
    data_dir, _u = roots(language)
    store = _reopen(language)
    try:
        rows = store.conn.execute("SELECT id, tier, ord, watched, work_id, rel_path, availability FROM items "
                                  "ORDER BY id").fetchall()
        lists = store.text_lists()
        arrivals = [i for i, _e, _a in store.ordered("arrivals")]
        counts = [(os.path.basename(s["path"]), s["items"]) for s in store.sources(all=True)]
        asks, works = store.rename_asks(), store.conn.execute("SELECT id, title FROM works ORDER BY id").fetchall()
    finally:
        store.close()
    with sqlite3.connect(f"file:{ti.store_path_for(language)}?mode=ro", uri=True) as db:
        tokens = db.execute("SELECT path, mtime, size, total, counted, aside FROM files ORDER BY path").fetchall()
    csvs = {}
    for path in sorted(glob.glob(os.path.join(root, "results", "*.csv"))):
        with open(path, "rb") as f:
            csvs[os.path.basename(path)] = f.read()
    with open(os.path.join(root, "results", "run_signature.txt"), "rb") as f:
        signature = f.read()
    return {"rows": rows, "lists": lists, "arrivals": arrivals, "library": _library_files(data_dir), "tokens": tokens,
            "csvs": csvs, "signature": signature, "counts": counts, "asks": asks, "works": works}


def _same_as_s0(s0, now, counts=None):
    """Every part of S0 unchanged — but each folder's count (`counts`: as the move leaves them)."""
    for k in s0:
        if k == "counts":
            assert now[k] == (counts if counts is not None else s0[k]), k
        else:
            assert now[k] == s0[k], k
    assert s0["csvs"], "the lists were written"


def _move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    _settle(os.path.dirname(dst))


def _index_reads_nothing(language):
    patcher, seen = _spy_tokenizing()
    with patcher:
        _run_indexer(language)
    assert seen == [], "a move that changed no text is never read again"


def _generate_skips(language):
    raw, said = _generate(os.environ["SURASURA_TEST_ROOT"], language, said=True)
    assert REUSED in said, "nothing a run reads moved: Generate skips"


def _root(store, folder):
    """The id of the source reading `folder`."""
    return next(r["id"] for r in store.sources(all=True) if os.path.normpath(r["path"]) == os.path.normpath(folder))


def _under(store, folder):
    """{item id} of the origins recorded under `folder` (their path keys)."""
    top = ls.path_key(os.path.abspath(folder)).rstrip("/") + "/"
    return {o.item_id for k, o in store.origins().items() if k.startswith(top)}


# --- 4a: app closed ------------------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("level", ["", LEVEL])
def test_4a_a_show_moved_to_the_nas_with_the_app_closed_changes_nothing_but_where_its_originals_are(language, level,
                                                                                                    monkeypatch):
    """Both shows moved to B (with and without the added level), B added, A and B looked at in full, the disk sync,
    an index and a Generate: added 0, attached 5 (four texts, the waiting video); every row as S0 (ids, tier, place,
    ✓, episode 1 still set aside, the works); the token store not read again; the lists and the run signature byte for
    byte (Generate skips); New arrivals as S0 (the one waiting video, never twice); A counts 0, B 5 (D5); every item's
    origin found under B."""
    data_dir, a, b, ids, s0 = _seed(language, monkeypatch)
    show, show2 = _shows(language)
    for s in (show, show2):
        _move(os.path.join(a, s), os.path.join(b, level, s) if level else os.path.join(b, s))
    store = _reopen(language)
    try:
        root_b = store.add_source(b)
        assert _look(store, language, _root(store, a), full=True)["added"] == 0
        result = _look(store, language, root_b, full=True)
        assert (result["added"], result["attached"]) == (0, 5)
        assert not (store.sync_disk() or {}).get("missing")
        assert _under(store, b) == set(ids.values())
        aside = store.text_lists()[2]
        assert store.item(ids["01"])["rel_path"] in aside, "W-1's aside kept"
    finally:
        store.close()
    _index_reads_nothing(language)
    _generate_skips(language)
    _same_as_s0(s0, _state(language), counts=[("driveA", 0), ("driveB", 5)])


@pytest.mark.parametrize("language", LANGUAGES)
def test_4a_then_the_next_episode_joins_the_show_and_a_v2_is_its_episode(language, monkeypatch):
    """After the move under the added level: `- 05` joins the show (its work, Current — never New arrivals, never a
    second title), `- 03v2` is episode 3's text (recopied, no new item); the index reads those two copies alone and
    every counted file is counted once."""
    data_dir, a, b, ids, s0 = _seed(language, monkeypatch)
    show, show2 = _shows(language)
    moved = os.path.join(b, LEVEL, show)
    _move(os.path.join(a, show), moved)
    _move(os.path.join(a, show2), os.path.join(b, LEVEL, show2))
    store = _reopen(language)
    try:
        root_b = store.add_source(b)
        _look(store, language, root_b, full=True)
        _write(os.path.join(moved, _name(show[6:], 5, language)), _episode(language, 5))
        _settle(b)
        five = _look(store, language, root_b)
        assert five["added"] == 1
        new = five["ids"][0]
        item = store.item(new)
        work = dict((r[0], r[4]) for r in s0["rows"])[ids["03"]]
        assert item["work_id"] == work and item["tier"] in ("now", "soon")
        assert item["rel_path"] == f"Library/{show}/{_name(show[6:], 5, language)}"
        assert [i for i, _e, _a in store.ordered("arrivals")] == s0["arrivals"]
        v2 = _write(os.path.join(moved, _name(show[6:], 3, language, "v2")), _episode(language, 3, "v2"))
        _settle(b)
        again = _look(store, language, root_b)
        assert (again["added"], again["recopied"]) == (0, 1)
        copy3 = os.path.join(data_dir, *store.item(ids["03"])["rel_path"].split("/"))
        assert _sha(copy3) == _sha(v2)
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == len(s0["rows"]) + 1
        assert store.conn.execute("SELECT COUNT(DISTINCT work_id) FROM items").fetchone()[0] == len(s0["works"])
        counted = store.text_lists()[0]
    finally:
        store.close()
    patcher, seen = _spy_tokenizing()
    with patcher:
        _run_indexer(language)
    rel3 = {r[0]: r[5] for r in s0["rows"]}[ids["03"]]
    want = {ls.path_key(os.path.join(data_dir, *r.split("/"))) for r in (item["rel_path"], rel3)}
    assert {ls.path_key(p) for p in seen if os.path.isabs(str(p))} == want
    with ti.open_store(language) as tokens:
        files = [ls.path_key(p) for p in tokens.counted_files()]
    assert sorted(files) == sorted(ls.path_key(os.path.join(data_dir, *r.split("/"))) for r in counted)
    assert len(files) == len(set(files)), "nothing counted twice"


# --- MV-2: moved where Surasura doesn't read, then *Find its folder* ----------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("picked", ["the show's folder", "the folder above it"])
def test_mv2_a_show_moved_where_no_source_reads_joins_only_once_its_folder_is_added(language, picked, monkeypatch):
    """MV-1's bound: the show moved to C, a folder no source holds — a full look of A adds and attaches nothing, the
    sync, the index and Generate change nothing (its items keep their copies). MV-2: the folder picked added as a read
    folder (*Find its folder*'s call: `add_source` then its look) — its four files are their items (no duplicate, every
    row as S0), its next episode joins the show; A then counts only Show2's waiting video."""
    data_dir, a, b, ids, s0 = _seed(language, monkeypatch)
    show, _show2 = _shows(language)
    c = _drive("driveC")
    moved = os.path.join(c, LEVEL, show)
    _move(os.path.join(a, show), moved)
    store = _reopen(language)
    try:
        unread = _look(store, language, _root(store, a), full=True)
        assert (unread["added"], unread["attached"]) == (0, 0)
        assert not (store.sync_disk() or {}).get("missing")
    finally:
        store.close()
    _index_reads_nothing(language)
    _generate_skips(language)
    _same_as_s0(s0, _state(language))
    store = _reopen(language)
    try:
        root_c = store.add_source(moved if picked == "the show's folder" else os.path.dirname(moved))
        found = _look(store, language, root_c)
        assert (found["added"], found["attached"]) == (0, 4)
        rows = store.conn.execute("SELECT id, tier, ord, watched, work_id, rel_path, availability FROM items "
                                  "ORDER BY id").fetchall()
        assert rows == s0["rows"], "no duplicate: the same rows"
        assert [s["items"] for s in store.sources(all=True)] == [1, 4]
        _write(os.path.join(moved, _name(show[6:], 5, language)), _episode(language, 5))
        _settle(c)
        five = _look(store, language, root_c)
        assert five["added"] == 1
        assert store.item(five["ids"][0])["work_id"] == store.item(ids["03"])["work_id"]
        assert store.item(five["ids"][0])["rel_path"].startswith(f"Library/{show}/")
    finally:
        store.close()


# --- 4b: app open -------------------------------------------------------------------------------------------------- #

class _IndexerHere:
    """The indexer child the window's `Chores` starts, run in this process (its tokenizing spied by the caller); the
    first run moves the shows first — the learner's move while the window's index runs."""

    def __init__(self, language, move):
        self.language, self.move, self.runs = language, move, 0

    def __call__(self, args, **kw):
        self.runs += 1
        if self.runs == 1:
            self.move()
        _run_indexer(self.language)
        return self

    pid = None
    returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def terminate(self):
        pass


def _until(check, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("language", LANGUAGES)
def test_4b_the_move_while_the_window_indexes_then_a_focus_and_a_refresh(language, monkeypatch):
    """The window open (its `SourceLooks` and `Chores`, B already read): the shows moved under the added level while
    its forced index runs; then the window's focus five minutes on and a Refresh. As 4a: every row as S0, no rename
    ask and no missing file (*Needs you* has nothing), the token store never read, Generate skips with the lists byte
    for byte, A counts 0 and B 5 — and the index after the move ran no more (measured: no extra run)."""
    from app.services import chores as C
    from app.services import source_looks
    from app.services.jobs import JobRegistry
    from tests.test_services_chores import _Clock, _Settings
    monkeypatch.setenv("SURASURA_NO_UI_TIMERS", "1")
    monkeypatch.delenv("SURASURA_NO_AUTOINDEX", raising=False)     # the window's indexer, as it runs (in-process)
    data_dir, a, b, ids, s0 = _seed(language, monkeypatch, b_first=True)
    show, show2 = _shows(language)

    def move():
        for s in (show, show2):
            _move(os.path.join(a, s), os.path.join(b, LEVEL, s))
    child = _IndexerHere(language, move)
    forced = []

    def needed(lang, script):
        if not forced:
            forced.append(True)
            return True                                  # the window's forced index at its start: it runs
        return C.index_needed(lang, script)
    clock = _Clock(10000.0)
    chores = C.Chores(JobRegistry(), _Settings(target_language=language), language, update_staged=lambda: False,
                      clock=clock, timer=lambda delay, call: None, popen=child, needed=needed,
                      log_folder=os.path.join(os.environ["SURASURA_TEST_ROOT"], "logs"))
    _data, user_files_dir = roots(language)
    looks = source_looks.SourceLooks(ls.StoreOpener(language, data_dir, user_files_dir), language,
                                     clock=lambda: clock.now, kind=lambda _p: "network")
    patcher, seen = _spy_tokenizing()
    try:
        with patcher:
            assert chores.index(force=True) is None
            assert _until(lambda: child.runs == 1 and not chores._indexing)
            clock.now += sources.FOCUS_S + 1
            assert looks.asked(focused=True)
            chores.activated()
            assert looks.idle(60) and _until(lambda: not chores._indexing)
            clock.now += 30
            assert looks.asked(refreshed=True)
            assert looks.idle(60) and _until(lambda: not chores._indexing)
        assert seen == [], "the index during and after the move read nothing again"
        assert child.runs == 1, "no extra index run: the move changed no text"
    finally:
        looks.close()
        looks.idle(10)
        chores.close(store=False)
    store = _reopen(language)
    try:
        assert store.rename_asks() == [] and not store.conn.execute(
            "SELECT 1 FROM items WHERE availability = 'missing'").fetchone()
        assert _under(store, b) == set(ids.values())
    finally:
        store.close()
    _generate_skips(language)
    _same_as_s0(s0, _state(language), counts=[("driveA", 0), ("driveB", 5)])


# --- 4b.3: the NAS unplugged, the app started again ---------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_4b3_the_nas_unplugged_and_the_app_started_again_keeps_everything(language, monkeypatch):
    """After 4a, B unplugged (its folder gone) and the app started again: B's look says unreachable and marks or
    moves nothing; every row as S0, nothing counted twice or dropped, the token store never read, Generate skips — B
    still counts the 5 it keeps (*its 5 episodes are kept*)."""
    data_dir, a, b, ids, s0 = _seed(language, monkeypatch)
    show, show2 = _shows(language)
    for s in (show, show2):
        _move(os.path.join(a, s), os.path.join(b, s))
    store = _reopen(language)
    try:
        root_b = store.add_source(b)
        _look(store, language, root_b, full=True)
    finally:
        store.close()
    os.rename(b, b + " (unplugged)")
    try:
        sources._LOOKED.clear()
        sources._RUNNING.clear()
        store = _reopen(language)
        try:
            assert _look(store, language, root_b, full=True).get("reachable") is False
            assert _look(store, language, _root(store, a), full=True)["added"] == 0
            assert not (store.sync_disk() or {}).get("missing")
        finally:
            store.close()
        _index_reads_nothing(language)
        _generate_skips(language)
        _same_as_s0(s0, _state(language), counts=[("driveA", 0), ("driveB", 5)])
    finally:
        os.rename(b + " (unplugged)", b)


# --- 4a-tier (D2), 4a-rename (D7a) and MV-3: a move inside the data folder (FIX1, the intent review) ---------------- #
# The scope's in-library rows: a 2.x tier-folder show (the library folder's own `HighPriority/<show>/`) cut, synced,
# pasted into another tier folder with its times floored to 2 s (a FAT stick's round trip) and synced again; and one
# episode renamed in its folder. Nothing the learner made moves, nothing is read again — and MV-3's one background
# Generate after it (the report's sources name the new place) reads nothing again either: run here as the dashboard
# runs it, in its own process, its tokenizing counted inside that process (`_generate_spied`).

_SPIED_GENERATE = r'''
import json, os, runpy, sys
from app import token_index as ti
seen, real_pool, real_make = [], ti._tokenized, ti.make_tokenizer
def pool(paths, tokenize_file, workers):
    seen.extend(str(p) for p in paths)
    return real_pool(paths, tokenize_file, workers)
def make(*args, **kwargs):
    made = real_make(*args, **kwargs)
    by_text = made.tokenize_text
    def tokenize_text(text, facts=None):
        seen.append(text[:40])
        return by_text(text, facts)
    made.tokenize_text = tokenize_text
    return made
ti._tokenized, ti.make_tokenizer = pool, make
out = sys.argv.pop(1)
sys.argv[0] = os.path.join("app", "analyzer.py")
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
finally:
    with open(out, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)
'''


def _generate_spied(language):
    """MV-3's background Generate: the dashboard's run in its own process, every file its token store tokenizes
    counted there -> (the list's bytes, what it printed, the files it read)."""
    root = os.environ["SURASURA_TEST_ROOT"]
    out = os.path.join(root, "generate_tokenized.json")
    cmd = [sys.executable, "-c", _SPIED_GENERATE, out, f"--language={language}", "--static", "--no-open",
           "--min-freq", "1"]
    p = subprocess.run(cmd, cwd=REPO, env=child_env(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0 and os.path.isfile(os.path.join(root, "results", LIST)), (p.stdout + p.stderr)[-3000:]
    subprocess.run([sys.executable, os.path.join(REPO, "app", "library_store.py"), "maintain", "--language", language],
                   cwd=REPO, env=child_env(root), capture_output=True)
    with open(out, encoding="utf-8") as f:
        seen = json.load(f)
    with open(os.path.join(root, "results", LIST), "rb") as f:
        return f.read(), p.stdout, seen


def _seed_tier(language):
    """A 2.x tier-folder show inside the data folder — `HighPriority/[Grp] Show/` with the four real episodes, taken
    in by the disk sync; episode 2 in Soon, episode 1 watched (set aside), a Generate and an index -> (data_dir, the
    show's folder rel, {episode: id}, S0)."""
    store, data_dir = _empty(language)
    show = _shows(language)[0]
    folder = f"HighPriority/{show}"
    for n in (1, 2, 3, 4):
        _write(os.path.join(data_dir, *folder.split("/"), _name(show[6:], n, language)), _episode(language, n))
    with store:
        added = store.sync_disk()["added"]
        assert len(added) == 4
        ids = {store.item(i)["rel_path"].rsplit(" - ", 1)[1][:2]: i for i in added}
        assert store.move([ids["02"]], "soon") is not None
        assert store.set_watched([ids["01"]]) is not None
    _generate(os.environ["SURASURA_TEST_ROOT"], language)
    _run_indexer(language)
    return data_dir, folder, ids, _state(language)


def _rows(language):
    store = _reopen(language)
    try:
        return store.conn.execute("SELECT id, tier, ord, watched, work_id, rel_path, availability FROM items "
                                  "ORDER BY id").fetchall(), store.text_lists()
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_4a_tier_a_tier_folder_show_cut_and_pasted_into_another_tier_folder_keeps_everything(language):
    """4a-tier (D2): the show cut (a sync sees it gone), then pasted into `LowPriority/` with its times floored to 2 s
    and synced: its four items are the same — ids, tier, place, ✓, episode 1 still aside, works — no new item, no
    rename ask. MV-3: the one background Generate after it reads nothing again (0 files tokenized in its process) and
    its lists differ from S0's only in the sentence sources' paths (the new place); the index after reads nothing."""
    data_dir, folder, ids, s0 = _seed_tier(language)
    show = folder.rsplit("/", 1)[1]
    held = os.path.join(os.environ["SURASURA_TEST_ROOT"], "clipboard", show)
    shutil.move(os.path.join(data_dir, *folder.split("/")), held)
    store = _reopen(language)
    try:
        assert sorted(store.sync_disk()["missing"]) == sorted(ids.values())
    finally:
        store.close()
    moved = f"LowPriority/{show}"
    shutil.move(held, os.path.join(data_dir, *moved.split("/")))
    for path in glob.glob(os.path.join(data_dir, *moved.split("/"), "*")):
        t = (os.stat(path).st_mtime_ns // 2_000_000_000) * 2_000_000_000
        os.utime(path, ns=(t, t))
    store = _reopen(language)
    try:
        summary = store.sync_disk()
        assert sorted(summary["renamed"]) == sorted(ids.values()) and summary["added"] == []
        assert store.rename_asks() == []
    finally:
        store.close()
    rows, (counted, kept, aside) = _rows(language)
    want = [r[:5] + (r[5].replace(folder, moved, 1), r[6]) for r in s0["rows"]]
    assert rows == want, "ids, tier, place, ✓, work kept; only the path moved"
    assert [p.replace(moved, folder, 1) for p in aside] == list(s0["lists"][2]), "W-1's aside kept"
    raw, said, seen = _generate_spied(language)
    assert REUSED not in said, "the sources moved: the one background Generate runs"
    assert seen == [], "the background Generate read nothing again"
    root = os.environ["SURASURA_TEST_ROOT"]
    for name, before in s0["csvs"].items():
        with open(os.path.join(root, "results", name), "rb") as f:
            now = f.read()
        assert now.replace(moved.encode("utf-8"), folder.encode("utf-8")) == before, f"{name}: only Src paths moved"
    _index_reads_nothing(language)
    _generate_skips(language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_4a_rename_an_episode_renamed_in_its_folder_is_never_read_again(language):
    """4a-rename (D7a): one tier-folder episode renamed in its folder (Explorer keeps its time): the sync keeps its
    item (rule 2), the index reads nothing (the store's move note re-keys its row), and MV-3's background Generate
    reads nothing either, its sources naming the new name."""
    data_dir, folder, ids, s0 = _seed_tier(language)
    store = _reopen(language)
    try:
        old = store.item(ids["03"])["rel_path"]
    finally:
        store.close()
    new = old.replace(" - 03", " - 03 (renamed)")
    os.replace(os.path.join(data_dir, *old.split("/")), os.path.join(data_dir, *new.split("/")))
    store = _reopen(language)
    try:
        assert store.sync_disk()["renamed"] == [ids["03"]]
    finally:
        store.close()
    _index_reads_nothing(language)
    raw, said, seen = _generate_spied(language)
    assert REUSED not in said and seen == [], "the background Generate read nothing again"
    rows, _lists = _rows(language)
    assert rows == [r[:5] + (new if r[0] == ids["03"] else r[5], r[6]) for r in s0["rows"]]


def test_d1_a_2x_tier_show_moved_out_to_a_nas_source():
    pytest.skip("D1 is dropped (the moves scope's header and §0): a 2.x tier show moved out to a NAS source is out "
                "of this scope — no rule is built for it")


def test_a_row_whose_recorded_mtime_differs_from_the_note_is_not_re_keyed(tmp_path):
    # why: the old row's recorded time is not the note's, so the row stands for another file and the move note must
    # re-key nothing (this pins the row-versus-note check only; the on-disk mtime rule is not exercised here)
    show = tmp_path / "番組"
    show.mkdir()
    new = show / "第二話.srt"
    new.write_bytes("また来週、ここで会おうね。\n".encode("utf-8") * 3)
    t_ns = 1_700_000_000_000_000_000
    os.utime(str(new), ns=(t_ns, t_ns))
    st = os.stat(str(new))
    old_key, new_key = ti._norm("番組/第一話.srt"), ti._norm(str(new))
    moved = [("番組/第一話.srt", st.st_size, t_ns, str(new), st.st_size, st.st_mtime_ns)]
    signatures, listed = {new_key: b"signature"}, {new_key: str(new)}

    # the old row was written 5 s after the note's time: it is not the note's file, so nothing is re-keyed
    touched = {old_key: {"size": st.st_size, "mtime": t_ns / 1e9 + 5}}
    assert ti._noted_moves(moved, {old_key}, touched, signatures, listed) == []

    # control: the same file with its time unchanged is re-keyed, so the empty answer above is the rule at work
    unchanged = {old_key: {"size": st.st_size, "mtime": t_ns / 1e9}}
    assert ti._noted_moves(moved, {old_key}, unchanged, signatures, listed) == [(old_key, new_key)]


def test_a_file_whose_mtime_changed_on_disk_is_not_re_keyed(tmp_path):
    # why: the row and the note agree on the old file, but the new file's time on disk is not the note's, so it is
    # another file and the move note must re-key nothing (the row-versus-note check is pinned by the test above)
    show = tmp_path / "番組"
    show.mkdir()
    new = show / "第二話.srt"
    new.write_bytes("また来週、ここで会おうね。\n".encode("utf-8") * 3)
    t_ns = 1_700_000_000_000_000_000
    os.utime(str(new), ns=(t_ns, t_ns))
    st = os.stat(str(new))
    old_key, new_key = ti._norm("番組/第一話.srt"), ti._norm(str(new))
    # the note recorded the new file 5 s later than it is on disk now
    moved = [("番組/第一話.srt", st.st_size, t_ns, str(new), st.st_size, st.st_mtime_ns + 5_000_000_000)]
    signatures, listed = {new_key: b"signature"}, {new_key: str(new)}
    unchanged = {old_key: {"size": st.st_size, "mtime": t_ns / 1e9}}
    assert ti._noted_moves(moved, {old_key}, unchanged, signatures, listed) == []


def test_rekey_onto_a_path_with_kept_text_replaces_it_and_sets_nothing_aside(tmp_path):
    # why: a moved file's kept text takes over the path, replacing the text kept there, with no integrity error and no
    # damaged-file set aside: the moved file's text is what the path holds afterwards, and the old path holds nothing
    data_dir = str(tmp_path)
    db = os.path.join(data_dir, "kept_text_ja_moves.db")
    kept = ti._KeptText(db, data_dir)
    old = ti._norm(os.path.join(data_dir, "A", "[Grp] Show - 01.srt"))
    new = ti._norm(os.path.join(data_dir, "A", "[Grp] Show - 01 (moved).srt"))
    moved_text = "今日はいい天気ですね。また来週、ここで会おうね。"
    try:
        kept.put({old: (moved_text, {"captions": 2}, 1.0, 10), new: ("昨日の雨が上がった。", {}, 2.0, 20)})
        kept.rekey(old, new)
        assert kept.get(new) == (moved_text, {"captions": 2}, 1.0, 10)
        assert kept.get(old) is None
    finally:
        kept.close()
    assert sorted(f for f in os.listdir(data_dir) if not f.endswith(("-wal", "-shm"))) == [os.path.basename(db)], \
        "nothing set aside: the kept file is the only file the folder holds"

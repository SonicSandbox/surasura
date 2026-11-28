"""ONE-READ 3: the journey's render opens the library store once, the name tables are read again only when the token
store moved, and a Generate after a sync parses KnownWord.json once.

Why (counted at the base, RP-2's libraries and the bench's 2k / 20k ones): the render opened the library store twice
— the page's facts (`journey_render.store_facts`) and the ▶'s rows (`play.files` → `_rows`, after a mode check of its
own) — ~15 ms an open (three connections: the mode check, the store's, the close's anchor) at every Generate and every
redraw. The tokenizer's name tables (`names.library_tables`) were read through a fresh connection and parsed again every
`names.REFRESH` seconds in every long-lived process (a window, Junban), the tables unchanged almost always. And a
Generate whose known words missed their cache (any sync that added a word) parsed KnownWord.json twice: once for the
known words, once more for the ignore set's IGNORED entries (~49 ms each at 3 MB). After it: one open a render, handed
to both readers and closed after the page; a look at the store's files (two stats) before any read; one parse handed
to the ignore set.

What a wrong answer would cost: a page drawn from a store closed under it (no facts: episodes by file name only, no ▶),
a window applying name tables older than the last index (names cut in pieces until a restart), or an ignore set missing
the words dismissed in Migaku. Real data: RP-2's real libraries (ja + zh, `plan_file_cases`) Generated in a child
process as the dashboard runs it, each run counted in a child of its own; real words in the files written here.
"""
import json
import os
import subprocess
import sys
import time

import pytest

from app import journey_render, names
from app import token_index as ti
from tests import plan_file_cases as cases

# The child: one run, counted — the library store's handles made inside the journey's render (`_write_journey`) and
# closed there, its mode checks, and KnownWord.json's reads in the whole run. Its last line only when the run finished.
_CHILD = r"""
import builtins, io, json, os, runpy, sys
from app import library_store as ls, path_utils as pu, static_html_generator as shg
n = {"opens": 0, "probes": 0, "closes": 0, "known_reads": 0, "phase": "run"}
language = sys.argv[2]
KP = os.path.normcase(os.path.abspath(os.path.join(pu.get_user_files_path(language), "KnownWord.json")))
real_open = builtins.open
def opened(file, *a, **k):
    mode = a[0] if a else k.get("mode", "r")
    if (isinstance(file, (str, os.PathLike)) and "r" in mode and "+" not in mode
            and os.path.normcase(os.path.abspath(os.fspath(file))) == KP):
        n["known_reads"] += 1
    return real_open(file, *a, **k)
builtins.open = io.open = opened
real_init, real_probe, real_close, real_write = ls.Store.__init__, ls._probe, ls._close, shg._write_journey
def init(self, *a, **k):
    n["opens"] += n["phase"] == "render"
    return real_init(self, *a, **k)
def probe(*a, **k):
    n["probes"] += n["phase"] == "render"
    return real_probe(*a, **k)
def close(conn, db_path, role):
    n["closes"] += n["phase"] == "render"
    return real_close(conn, db_path, role)
def write(*a, **k):
    n["phase"] = "render"
    try:
        return real_write(*a, **k)
    finally:
        n["phase"] = "run"
ls.Store.__init__, ls._probe, ls._close, shg._write_journey = init, probe, close, write
sys.argv = ["analyzer.py", f"--language={language}", "--static", "--no-open"] + (
    ["--from-plan"] if sys.argv[1] == "redraw" else [])
try:
    runpy.run_path(os.path.join("app", "analyzer.py"), run_name="__main__")
except SystemExit as e:
    if e.code not in (0, None):
        raise
print("COUNT " + json.dumps(n), flush=True)
"""

# One move on the root's library store (a show to the top of NOW), as test_one_read makes it: the redraw's case.
_MOVE = r"""
import os, sys
from app import library_store as ls
language, root = sys.argv[1], sys.argv[2]
store = ls.open_store(language, os.path.join(root, "data", language), os.path.join(root, "User Files", language))
assert store is not None and store.move([store.ids("soon")[-1]], "now") is not None
store.close()
"""

LEVEL_2 = {"SURASURA_SENTENCE_TABLE": "2"}


def _env(root):
    env = cases.child_env(root)
    env.update(LEVEL_2)
    return env


def _counted(root, language, what):
    p = subprocess.run([sys.executable, "-c", _CHILD, what, language], cwd=cases.REPO, env=_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("COUNT ")]
    assert p.returncode == 0 and line, p.stdout[-2000:] + p.stderr[-2000:]
    got = json.loads(line[-1][6:])
    got["out"] = p.stdout
    return got


def _moved_known(root, language):
    """KnownWord.json moved, as a sync that adds a word moves it: the run's known-words read misses (the costly case)."""
    path = os.path.join(root, "User Files", language, "KnownWord.json")
    later = time.time() + 5
    os.utime(path, (later, later))


@pytest.fixture(scope="module", params=["ja", "zh"])
def root(request, tmp_path_factory):
    """RP-2's library Generated once (the token store indexed, the library store built)."""
    language = request.param
    root = str(tmp_path_factory.mktemp(f"one-read-3-{language}") / "root")
    cases.build(root, f"rp2-{language}")
    cases.generate(root, f"rp2-{language}", extra_env=LEVEL_2)
    return root, language


def test_a_generates_journey_opens_the_library_store_once_and_parses_the_known_words_once(root):
    # why: the page's facts and the ▶'s rows each opened the store (and the ▶ checked its mode first); a Generate after
    # a sync parsed KnownWord.json for the known words and again for the ignore set's IGNORED entries
    root, language = root
    _moved_known(root, language)
    got = _counted(root, language, "generate")
    assert "Journey written" in got["out"], got["out"][-1500:]
    # (ONE-READ 4: the render reads through the run's one handle, opened before it and closed at the run's end — so
    # none of its own; test_one_read_4 counts the whole run)
    assert got["opens"] == 0, f"the library store never opened again in the render: {got}"
    assert got["probes"] == 0, f"its mode read through the run's handle: {got}"
    assert got["closes"] == 0, f"never closed in the render (the run's handle, never a reader's): {got}"
    assert got["known_reads"] == 1, f"KnownWord.json read once a run: {got}"


def test_a_redraws_journey_opens_the_library_store_once(root):
    # why: the journey's redraw from the plan (only the order moved) draws the same page: the same one open
    root, language = root
    if language != "ja":
        pytest.skip("the render's opens are the same code for both; the ja library is the one moved")
    cases.generate(root, f"rp2-{language}", extra_env=LEVEL_2)        # the plan of this very order
    p = subprocess.run([sys.executable, "-c", _MOVE, language, root], cwd=cases.REPO, env=_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-2000:]
    got = _counted(root, language, "redraw")
    assert "Redrew the journey" in got["out"], got["out"][-1500:]
    assert got["opens"] == 0 and got["probes"] == 0 and got["closes"] == 0, got     # the run's handle (ONE-READ 4)


# --- the name tables: a look before a read ------------------------------------------------------------------------ #
def _tables(word):
    """Name tables as the index stores them (app/names.py), one recurring katakana name in them."""
    return {"k": {word: [1.0, word, "", word]}, "j": {}, "w": {}, "stamp": word}


_WRITTEN = [time.time_ns()]


def _store_with(tables):
    store = ti.open_store("ja")
    try:
        store.set_meta("names_tables", json.dumps(tables, ensure_ascii=False))
    finally:
        store.close()
    # (a second write inside one clock tick can leave the same mtime and page count: the test's two writes, not a
    # learner's index minutes apart — each one dated apart, so the look is tested and never the clock's grain)
    _WRITTEN[0] += 2_000_000_000
    os.utime(ti.store_path_for("ja"), ns=(_WRITTEN[0], _WRITTEN[0]))


@pytest.fixture
def reads(monkeypatch):
    """Every read of a value from the token store's meta (`_read_meta`: a fresh connection and a parse), counted."""
    got = []
    real = ti._read_meta
    monkeypatch.setattr(ti, "_read_meta", lambda language, key: got.append(key) or real(language, key))
    monkeypatch.setattr(names, "REFRESH", -1.0)      # below zero: every call is a look (two inside one clock tick too)
    names.forget_library_tables()
    yield got
    names.forget_library_tables()


def test_the_name_tables_are_read_again_only_when_the_token_store_moved(reads):
    # why: a window looked every 30 s through a fresh connection and parsed the tables again, unchanged almost always
    _store_with(_tables("メロンベンチ"))
    for _ in range(3):
        assert "メロンベンチ" in names.library_tables()["k"]
    assert reads == ["names_tables"], f"read once while the store stood still: {reads}"
    _store_with(_tables("ソラハシ"))                                  # the next index wrote newer tables
    assert "ソラハシ" in names.library_tables()["k"], "a store that moved is read again"
    assert len(reads) == 2
    names.library_tables()
    assert len(reads) == 2


def test_a_token_store_made_again_or_gone_is_read_again(reads):
    # why: a store rebuilt (a schema change, Repair) is a new file in the old one's place; one deleted has no tables
    _store_with(_tables("メロンベンチ"))
    assert "メロンベンチ" in names.library_tables()["k"]
    path = ti.store_path_for("ja")
    for name in (path, path + "-wal", path + "-shm"):
        if os.path.exists(name):
            os.remove(name)
    assert names.library_tables() is None, "no store: no tables"
    _store_with(_tables("カザハヤ"))
    assert "カザハヤ" in names.library_tables()["k"], "the new store's own tables"


def test_tables_a_caller_set_are_read_over_at_the_next_look_and_pinned_ones_never(reads):
    # why: the tables an index hands in (`use_library_tables`) are not the store's read: the next look reads the store,
    # as before; a pinned measurement never reads it
    _store_with(_tables("メロンベンチ"))
    names.library_tables()
    names.use_library_tables(_tables("ヒナタ"))
    assert "メロンベンチ" in names.library_tables()["k"] and len(reads) == 2
    names.use_library_tables(_tables("ヒナタ"), pin=True)
    _store_with(_tables("ソラハシ"))
    assert "ヒナタ" in names.library_tables()["k"] and len(reads) == 2


def test_tables_forgotten_are_read_from_the_store_again(reads):
    # why: `forget_library_tables` is "back to the store on next use": the store that stood still is still read, never
    # answered "no tables" by the stamp of the read before
    _store_with(_tables("メロンベンチ"))
    names.library_tables()
    names.forget_library_tables()
    assert "メロンベンチ" in names.library_tables()["k"] and len(reads) == 2


def test_no_token_store_yet_means_no_tables_and_no_error(reads):
    # why: a first run, before any index: nothing to read, every look cheap
    assert names.library_tables() is None and names.library_tables() is None


def test_a_read_that_failed_is_read_again_at_the_next_look(reads, monkeypatch):
    # why: a store busy at the look (its read answers None) never keeps its stamp: the next look reads it again, as
    # every look did before, instead of no names until the next index moves the store
    _store_with(_tables("メロンベンチ"))
    real, failed = ti.read_names_tables, [None]
    monkeypatch.setattr(ti, "read_names_tables", lambda language: failed.pop() if failed else real(language))
    assert names.library_tables() is None
    assert "メロンベンチ" in names.library_tables()["k"], "the store that stood still, read at the next look"


def test_the_stamp_moves_with_the_wal_and_an_empty_wal_is_none(tmp_path):
    # why: a commit in WAL mode moves only the -wal until a checkpoint, so the look must see it; a reader's open makes
    # an empty -wal that holds no write, and must not read as one
    db = tmp_path / "token_store_ja.db"
    db.write_bytes(b"\0" * 4096)
    alone = names._store_stamp(str(db))
    wal = tmp_path / "token_store_ja.db-wal"
    wal.write_bytes(b"")
    assert names._store_stamp(str(db)) == alone, "an empty -wal is no write"
    wal.write_bytes(b"\1" * 4152)
    committed = names._store_stamp(str(db))
    assert committed != alone, "a commit in the -wal moves the stamp"
    wal.write_bytes(b"\1" * 8272)
    assert names._store_stamp(str(db)) != committed, "and the next one again"
    assert names._store_stamp(str(tmp_path / "token_store_zh.db")) is None, "no store: None"


# --- the render's one handle: where its open found none, and a ▶ lookup that reaches the pairings ----------------- #
class _Handle:
    """The render's open library store as a reader gets it: a reader that closes it (`with`) is counted."""
    closed = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed += 1


@pytest.fixture
def opens(monkeypatch):
    """Every library-store open and mode check a reader makes itself, counted (each answers "no store")."""
    from app import library_store
    got = []
    monkeypatch.setattr(library_store, "check_mode", lambda *a, **k: got.append("probe") or ("missing", None))
    monkeypatch.setattr(library_store, "open_store", lambda *a, **k: got.append("open"))
    monkeypatch.setattr(journey_render, "open_library", lambda *a, **k: got.append("open"))
    return got


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_render_whose_open_found_no_store_opens_none_again(opens, language, capsys):
    # why: the render's one open found no store (a 2.x library, or one busy past its wait): the facts and the ▶'s
    # rows answer "none" from that, never a second open that could read a store the facts didn't — and say nothing
    # (no store is no failed read)
    from app.services import play
    assert journey_render.store_facts(language, library=False) is None
    assert play._rows(language, ["Show/01.srt"], library=False) == ({}, "")
    assert opens == [] and capsys.readouterr().out == ""


def test_a_journey_whose_open_found_no_store_hands_the_render_none_to_open(monkeypatch):
    # why: `_write_journey`'s one open found no store: the render is told so (False), so its ▶ rows never open one
    from app import analyzer
    from app import static_html_generator as shg

    class Drawn(Exception):
        pass
    seen = {}

    def render(language, **k):
        seen.update(k)
        raise Drawn
    monkeypatch.setattr(journey_render, "open_library_look", lambda *a, **k: (None, None))
    monkeypatch.setattr(journey_render, "render", render)
    monkeypatch.setattr(analyzer, "journey_marks", lambda language: pytest.fail("opened the store again (ONE-READ 4)"))
    with pytest.raises(Drawn):
        shg._write_journey("ja", open_browser=False)
    assert seen["library"] is False and seen["facts"] is False


def test_a_lookup_the_memo_misses_hands_the_renders_handle_to_the_pairings(monkeypatch):
    # why: the first render after a Generate misses the ▶'s memo for a source that may play: its pairing record is
    # read through the render's handle, the one `files` was given, not a second open
    from app.services import play
    handle, seen, rel = _Handle(), [], "Bocchi/01.srt"
    monkeypatch.setattr(play, "_rows", lambda language, rels, library=None: ({rel: (5, "anime", (), ())}, "Bocchi"))
    monkeypatch.setattr(play, "_places", lambda data_dir, rel, rows, copies: ["Bocchi"])
    monkeypatch.setattr(play, "_list_all", lambda folders, listings: None)
    monkeypatch.setattr(play, "_holds_playable", lambda *a, **k: True)
    monkeypatch.setattr(play, "_memo_key", lambda *a: "key")
    monkeypatch.setattr(play, "_pairings",
                        lambda language, ids, moved, handed=None: seen.append((ids, handed)) or {i: {} for i in ids})
    monkeypatch.setattr(play, "_finder", lambda language, listings=None: None)
    monkeypatch.setattr(play, "_find", lambda *a, **k: (None, None))
    assert play.files("ja", [rel], memo={}, library=handle) == {rel: None}
    assert seen == [([5], handle)]


def test_the_pairings_read_through_the_renders_handle_and_leave_it_open(opens, monkeypatch):
    # why: a ▶ lookup the memo misses reads the sources' pairing records; in the render that is the render's handle,
    # read through and left for its opener to close, not a mode check and an open of its own
    from app.connect import library
    from app.services import play
    handle = _Handle()
    monkeypatch.setattr(library, "pairing_of",
                        lambda store, i: {"origin": "hato", "item": i} if store is handle else None)
    monkeypatch.setattr(library, "moved_of", lambda store, i, record, roots: None)
    moved = {}
    got = play._pairings("ja", [3, 7], moved, handed=handle)
    assert got == {3: {"origin": "hato", "item": 3}, 7: {"origin": "hato", "item": 7}} and moved == {3: None, 7: None}
    assert opens == [] and handle.closed == 0


# --- the ignore set from the known words' one parse --------------------------------------------------------------- #
KNOWN = [{"dictForm": "冒険", "knownStatus": "KNOWN"}, {"dictForm": "準備", "hasCard": 1},
         {"dictForm": "危険", "knownStatus": "IGNORED"}, {"dictForm": " 価値 ", "knownStatus": "IGNORED"},
         {"dictForm": "", "knownStatus": "IGNORED"}]


@pytest.fixture
def known_file(tmp_path, monkeypatch):
    folder = tmp_path / "User Files"
    folder.mkdir()
    path = folder / "KnownWord.json"
    path.write_text(json.dumps({"words": KNOWN}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ti, "_IGNORED_ENTRIES", {})
    return str(folder), str(path)


class _Reads:
    def __init__(self, monkeypatch, path):
        from app import analyzer, path_utils
        self.n = 0
        real = path_utils.read_text

        def read_text(p, *a, **k):
            self.n += os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(path))
            return real(p, *a, **k)
        monkeypatch.setattr(path_utils, "read_text", read_text)      # (token_index imports it at each call)
        monkeypatch.setattr(analyzer, "read_text", read_text)        # (the analyzer holds its own name for it)


def _fresh(path, language="ja"):
    """The IGNORED entries a parse of its own finds (the base's second parse)."""
    with open(path, encoding="utf-8") as f:
        return ti._ignored_of(json.load(f))


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_ignore_set_takes_the_known_words_parse_and_finds_the_same_entries(known_file, monkeypatch, language):
    # why: a Generate whose known words missed their cache parsed the file once for them and once more for the ignore
    # set; the one parse now serves both, with the same answer (the dismissed words, trimmed, blanks left out)
    from app import analyzer
    folder, path = known_file
    tokenizer = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
    count = _Reads(monkeypatch, path)
    analyzer.load_known_words(path, tokenizer)
    got = ti._ignored_file_entries(folder, language)
    assert got == ["危険", "価値"] == _fresh(path)
    assert count.n == 1, f"one parse for both: {count.n}"


def test_a_write_between_the_parse_and_the_ignore_set_is_read_again(known_file, monkeypatch):
    # why: the kept answer is the file as it was parsed; a sync's write after it (another program's) must be read, never
    # answered from the older parse
    from app import analyzer
    folder, path = known_file
    count = _Reads(monkeypatch, path)
    analyzer.load_known_words(path, analyzer.JapaneseTokenizer())
    later = time.time() + 5
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"words": KNOWN + [{"dictForm": "有名", "knownStatus": "IGNORED"}]}, f, ensure_ascii=False)
    os.utime(path, (later, later))
    assert ti._ignored_file_entries(folder, "ja") == ["危険", "価値", "有名"]
    assert count.n == 2


def test_a_write_while_the_known_words_are_parsed_is_read_again(known_file, monkeypatch):
    # why: the entries are kept under the file's signature from before the read; a sync's write landing while it is
    # read leaves a newer file than the parse, so the ignore set reads it again instead of the parse's older entries
    from app import analyzer
    folder, path = known_file
    real, written = analyzer.read_text, []

    def read_then_written(p, *a, **k):
        text = real(p, *a, **k)
        if not written:
            written.append(p)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"words": KNOWN + [{"dictForm": "有名", "knownStatus": "IGNORED"}]}, f, ensure_ascii=False)
            later = time.time() + 5
            os.utime(path, (later, later))
        return text
    monkeypatch.setattr(analyzer, "read_text", read_then_written)
    analyzer.load_known_words(path, analyzer.JapaneseTokenizer())
    assert written and ti._ignored_file_entries(folder, "ja") == ["危険", "価値", "有名"]


def test_an_unreadable_known_words_file_leaves_the_ignore_set_to_read_it(known_file, monkeypatch):
    # why: a file the known words can't parse raises there as before; the ignore set reads it on its own (none of its
    # entries ignored), never an answer kept from a parse that didn't happen
    from app import analyzer
    folder, path = known_file
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"words": [')
    with pytest.raises(ValueError):
        analyzer.load_known_words(path, analyzer.JapaneseTokenizer())
    assert ti._ignored_file_entries(folder, "ja") == []

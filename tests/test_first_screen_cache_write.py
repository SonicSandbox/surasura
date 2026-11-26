"""KEYMOVE-L2 (3.0.19): the first screen's cache (`window_cache_<lang>.json`) is written in one pass of the C encoder.

The reader writes it at the next look that finds the store unchanged (speed round 5) — and the look a key press wakes
is such a look: the writer hasn't landed the move yet. At 20,000 files that write sat in front of the move's new
numbers on the reader's thread: `view_rows.to_cache` copied every row, episode and status into plain lists in Python
(~99,000 calls for 40 rows), then `json.dump` walked the copy again with the pure-Python encoder (`json.dump` never
uses the C one) — ~21 ms of work stretched to ~100 ms while the writer held Python's lock, the first key move's view
~155 ms at both levels. The C encoder writes namedtuples as arrays, so the copy pass is not needed: the same text, in
one pass. These tests count the Python calls the write makes (a counter, never a clock) and check the file is the
text the two passes wrote, on Japanese and Chinese seed libraries.
"""
import json
import sys

import pytest

from app.services import library_reader, view_rows
from tests.fixtures import window_seed


def _plain(value):
    """The old writer's copy pass, kept here as the reference: namedtuples and tuples -> lists, recursively."""
    if isinstance(value, tuple) and hasattr(value, "_fields"):
        return [_plain(v) for v in value]
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _old_to_cache(view, rows):
    """The old `view_rows.to_cache`, kept here whole as the reference (never the code under test): the first `rows`
    rows without their `string`, the lines among them, the Goal strip's first five, the counts — copied plain."""
    kept = view.rows[:rows]
    return {"rows": _plain([r._replace(string=None) for r in kept]),
            "lines": _plain([ln for ln in view.lines if ln.after < len(kept)]),
            "goal": _plain(view.goal)[:5], "counts": _plain(view.counts), "subline": view.subline,
            "badges": dict(view.badges), "keep_watched": bool(view.keep_watched)}


def _built_reader(tmp_path, language):
    """A reader on a seed library with its first view built by hand (no thread), the cache file in `tmp_path`."""
    seed = window_seed.build(language=language)         # the 40-row seed (shows with episodes, books, songs)
    cache = tmp_path / f"window_cache_{language}.json"
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02, cache_file=str(cache))
    views = []
    reader.subscribe(views.append)
    reader._look()                                       # the look that builds the first view
    assert views and views[-1].rows, "the seed library shows rows"
    return reader, views[-1], cache


def _python_calls(fn):
    """How many Python functions run while `fn` runs (sys.setprofile's 'call' events; C functions are 'c_call')."""
    n = [0]

    def prof(_frame, event, _arg):
        if event == "call":
            n[0] += 1
    sys.setprofile(prof)
    try:
        fn()
    finally:
        sys.setprofile(None)
    return n[0]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_first_screens_cache_is_written_without_a_python_pass_per_row_or_episode(tmp_path, language):
    """The write's Python calls don't grow with the rows: a handful (the write itself, the figures, the file), never one
    per row, episode, status or JSON chunk. Before KEYMOVE-L2: thousands on the seed library (the copy pass and the
    pure-Python encoder), ~99,000 on the 20k bench's 40 rows."""
    reader, view, cache = _built_reader(tmp_path, language)
    rows = len(view.rows[:reader.cache_rows])
    episodes = sum(len(r.episodes) for r in view.rows[:reader.cache_rows])
    calls = _python_calls(lambda: reader._write_cache(view, ["store-id", 1, 2, None]))
    assert cache.exists()
    assert calls < 60, f"{calls} Python calls to write {rows} rows ({episodes} episodes)"


@pytest.mark.parametrize("language,cache_rows", [("ja", None), ("zh", None), ("ja", 5), ("zh", 5)])
def test_the_cache_file_is_the_text_the_copy_pass_and_json_dump_wrote(tmp_path, monkeypatch, language, cache_rows):
    """The bytes don't move: the file is exactly what the old writer wrote (`json.dump` of the plain copy, the same
    keys in the same order, Japanese / Chinese titles as they are, `ensure_ascii=False`) — so a cache an older version
    wrote and one this version writes read the same, and `from_cache` reads it back into the same first screen."""
    monkeypatch.setattr(library_reader.time, "time", lambda: 1764000000.25)     # `written_at`, fixed
    reader, view, cache = _built_reader(tmp_path, language)
    if cache_rows is not None:                           # fewer cached rows than the view has: the lines' filter and
        reader.cache_rows = cache_rows                   # the rows' cut both count
        assert len(view.rows) > cache_rows and any(ln.after >= cache_rows for ln in view.lines)
    assert any(r.string is not None for r in view.rows), "the rows carry a `string` the cache leaves out"
    key = ["store-id", 3, 41, [1764000000000000000, 2471285]]
    reader._write_cache(view, key, None)
    got = cache.read_text(encoding="utf-8")

    data = {"version": library_reader.CACHE_VERSION, "key": key, "written_at": 1764000000.25,
            "view": _old_to_cache(view, reader.cache_rows),
            "numbers": library_reader._cached_figures(view, None, reader.cache_rows),
            "faded": False, "app": library_reader.APP_VERSION}
    import io
    want = io.StringIO()
    json.dump(data, want, ensure_ascii=False)
    assert got == want.getvalue()
    back = view_rows.from_cache(json.loads(got)["view"], language=language)
    assert back is not None and [r.key for r in back.rows] == [r.key for r in view.rows[:reader.cache_rows]]
    if language == "ja":
        assert any("぀" <= ch <= "鿿" for ch in got), "Japanese written as it is, never \\u escapes"


def test_an_empty_library_writes_a_cache_with_no_rows(tmp_path):
    """Empty state: a library with no rows still writes a readable cache (nothing to copy, nothing to encode)."""
    reader, view, cache = _built_reader(tmp_path, "ja")
    empty = view._replace(rows=(), lines=())
    reader._write_cache(empty, ["store-id", 1, 1, None])
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["view"]["rows"] == [] and data["view"]["lines"] == []
    assert view_rows.from_cache(data["view"]) is not None


def test_a_cache_that_cannot_be_written_is_only_slower_next_time(tmp_path, monkeypatch):
    """A failing disk: an OSError while writing raises nothing and leaves the old cache file as it was (as before)."""
    reader, view, cache = _built_reader(tmp_path, "ja")

    def refuse(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(library_reader.os, "replace", refuse)
    reader._write_cache(view, ["store-id", 1, 1, None])
    assert not cache.exists()

"""Fresh library (3.0.1) WP0: `path_utils.profile_parts()`, the one list of every place Surasura keeps files and what
*Start over completely* (moves / stays) and *Sort my library again* (part / stays) do with each.

What a wrong answer would cost a learner:
  * a place left behind by Start over: the new start finds an old file (a word store, Connect's ledger, a window's
    cache) and mixes the old Surasura into the new one — or a Put back can't bring it back;
  * a place moved that must stay: the telemetry id counted twice, a network opt-out lost (P7), the installer's notes
    gone (the library looks missing, or the Surasura 2 import is offered again, P8), another install's files taken;
  * in a portable or source folder, a program's own files (Surasura.exe, a checkout's code) moved as if they were his.

Like `PLACED` for settings, `CALL_SITES` below records every place in the code that names a data root: a new one
fails `test_every_place_the_code_names_a_data_root_is_counted_here` until it is classified in `path_utils.PARTS` and
counted here. `test_every_file_the_code_writes_is_named_by_the_table` makes each writer's own path under the test
root and checks the table names it.
"""
import os
import re

import pytest

from app import library_store as ls
from app import path_utils
from tests.test_library_store_support import LANGUAGES, names, touch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every source file that names a data root (by text: a comment counts too, so the count is only ever looked at),
# and how many times. modules/ is the private overlay: absent in a public checkout, its rows are skipped there.
CALL_SITES = {
    "app/cli/contract.py": 1,
    "app/cli/events.py": 1,
    "app/cli/verbs.py": 1,
    "app/connect/anki_miner.py": 2,
    "app/connect/kick.py": 3,
    "app/connect/known_signal.py": 1,
    "app/connect/ledger.py": 1,
    "app/import_2x.py": 2,
    "app/library_store.py": 3,
    "app/locks.py": 8,
    "app/path_utils.py": 19,
    "app/profile_reset.py": 1,
    "app/qt/shell.py": 1,
    "app/qt/single.py": 2,
    "app/replan_preview.py": 1,
    "app/report.py": 2,
    "app/services/anki_miner_setup.py": 4,
    "app/services/arrivals.py": 1,
    "app/services/chores.py": 1,
    "app/services/covers.py": 4,
    "app/services/covers_online.py": 3,
    "app/services/first_run.py": 1,
    "app/services/generate.py": 1,
    "app/services/journey.py": 1,
    "app/services/library_reader.py": 1,
    "app/services/moves.py": 1,
    "app/services/needs.py": 1,
    "app/services/settings_io.py": 1,
    "app/telemetry.py": 3,
    "app/token_index.py": 1,
    "app/updater.py": 3,
    "modules/junban/__init__.py": 1,
    "modules/junban/backlog_shows.py": 1,
    "modules/junban/patterns_build.py": 1,
    "modules/junban/patterns_package.py": 1,
    "modules/junban/undo.py": 1,
    "modules/koe/keystore.py": 1,
    "modules/koe/server.py": 1,
    "modules/youtube_downloader/downloader_view.py": 1,
    "modules/youtube_downloader/ytdlp_manager.py": 1,
}
_ROOT_CALL = re.compile(r"\b(get_local_data_path|get_persistent_user_data_path|persistent_root|local_data_root|"
                        r"_local_data_root|get_covers_cache_path)\(\)")


def _root():
    return os.environ["SURASURA_TEST_ROOT"]


def _make(path, folder=False):
    if folder:
        os.makedirs(path, exist_ok=True)
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(names("ja")[0])
    return path


def _part_of(path, parts=None):
    """The part holding `path` (the entry it is, or lies under)."""
    key = os.path.normcase(os.path.normpath(path))
    for part in parts if parts is not None else path_utils.profile_parts():
        top = os.path.normcase(os.path.normpath(part["path"]))
        if key == top or key.startswith(top + os.sep):
            return part
    return None


def _writers():
    """(what writes it, its path, a folder?) — each from the code's own path function under the test root."""
    from app import report, telemetry, updater
    from app.cli import contract, events
    from app.connect import anki_miner, kick, known_signal, ledger
    from app.services import first_run, library_reader, moves, needs, settings_io
    from app.services import anki_miner_setup
    out = [
        ("the window's reader cache", library_reader.cache_path("ja"), False),
        ("the window's pending moves", moves.journal_path("ja"), False),
        ("Needs you's seen list", needs.seen_path("zh"), False),
        ("settings import's record", settings_io.record_path(), False),
        ("Connect's ledger", ledger.path(), False),
        ("Connect's wake file", kick.wake_path(), False),
        ("the known-words signal", known_signal.record_path("ja"), False),
        ("Connect's whitelist", anki_miner.whitelist_path("zh"), False),
        ("Anki Miner's install staging", anki_miner_setup.staging_folder(), True),
        ("the folder-time cache", os.path.join(ledger.folder(), "sources_ja.json"), False),
        ("the covers cache", os.path.join(path_utils.get_covers_cache_path(), "a.jpg"), False),
        ("the window's state", os.path.join(path_utils.get_local_data_path(), "window_state.json"), False),
        ("the one-window lock", os.path.join(path_utils.get_local_data_path(), "window-abc.lock"), False),
        ("the update's state", updater.update_state_path(), False),
        ("the update's folder", updater.update_dir(), True),
        ("the CLI's log", os.path.join(contract.log_folder() if hasattr(contract, "log_folder") else
                                       os.path.join(path_utils.get_local_data_path(), "logs"), "cli.log"), False),
        ("the CLI's events", events.events_path() if hasattr(events, "events_path") else
         os.path.join(path_utils.get_local_data_path(), "logs", "cli-events.jsonl"), False),
        ("a lock", os.path.join(path_utils.get_local_data_path(), "locks", "results.lock"), False),
        ("a word store", os.path.join(_root(), "index", "token_store_ja.db"), False),    # token_index's rule
        # (the suite's conftest points `store_path_for` at a folder of its own)
        ("the saved reports", os.path.join(report.folder(), "report.json"), False),
        ("the telemetry id", os.path.join(path_utils.get_persistent_user_data_path(), "telemetry_id.json"), False),
        ("the telemetry URL", os.path.join(path_utils.persistent_root(), telemetry.URL_CACHE), False),
        ("the start gate's note", first_run.note_path(), False),
        ("the import's note", os.path.join(path_utils.local_data_root(), "import.json"), False),
        ("the installs note", os.path.join(path_utils.local_data_root(), path_utils.INSTALLS_NOTE), False),
        ("the library note", os.path.join(path_utils.local_data_root(), path_utils.LIBRARY_NOTE), False),
        ("the update marker", ls.update_staged_path(), False),
        ("the update lock", ls.update_lock_path(), False),
        ("settings.json", path_utils.get_settings_path(), False),
        ("results", os.path.join(path_utils.get_user_file("results"), "reading_list_static.html"), False),
        ("known words", os.path.join(path_utils.get_user_files_path("ja"), "KnownWord.json"), False),
        ("the content", os.path.join(path_utils.get_data_path("zh"), "Library", "a.txt"), False),
        ("the journal", os.path.join(path_utils.get_local_data_path(), path_utils.PROFILE_JOURNAL), False),
    ]
    for lang in LANGUAGES:
        out.append((f"the {lang} library store", ls.library_db_path(lang, path_utils.get_data_path(lang)), False))
    try:
        from modules.junban import backlog_shows, patterns_build, undo
        from modules.koe import keystore, server
        from modules.youtube_downloader import downloader_view, ytdlp_manager
    except ImportError:                                  # a public checkout: no modules/
        return out
    out += [
        ("Koe's key", keystore._path(), False),
        ("Koe's usage", server._usage_path(), False),
        ("Junban's backlog shows", backlog_shows.path("ja"), False),
        ("Junban's runs", undo.runs_folder("ja"), True),
        ("パターン", patterns_build.default_db_path("ja"), False),
        ("YouTube's rest", downloader_view.rest_path("ja"), False),
        ("yt-dlp", ytdlp_manager._bin_dir(), True),
    ]
    return out


# What each writer's part must be: the parts that stay (the rest move)
STAYS = {"the one-window lock", "the update's state", "the update's folder", "the CLI's log", "the CLI's events",
         "a lock", "the telemetry id", "the telemetry URL", "the start gate's note", "the import's note",
         "the installs note", "the library note", "the update marker", "the update lock", "the journal", "yt-dlp"}


def test_every_place_the_code_names_a_data_root_is_counted_here():
    """A new place a file is written must be classified (path_utils.PARTS) before it ships: the count of each source
    file's calls of the data roots' functions is recorded here, and any change fails until it is looked at."""
    found = {}
    for top in ("app", "modules"):
        for where, dirs, files in os.walk(os.path.join(REPO, top)):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", "reels")]
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(where, name)
                    with open(path, encoding="utf-8") as f:
                        count = len(_ROOT_CALL.findall(f.read()))
                    if count:
                        found[os.path.relpath(path, REPO).replace(os.sep, "/")] = count
    expected = {k: v for k, v in CALL_SITES.items() if os.path.exists(os.path.join(REPO, *k.split("/")))}
    assert found == expected, ("a data root is named in a new place, or one went: classify what it writes in "
                               "path_utils.PARTS, then count it in CALL_SITES")


def test_every_file_the_code_writes_is_named_by_the_table():
    """Each writer's own path, made under the test root, lies in a part the table names (never `unlisted`), and the
    part does what the spec says: the program's own notes, logs, locks and the telemetry id stay, the rest moves."""
    made = [(what, _make(path, folder)) for what, path, folder in _writers()]
    parts = path_utils.profile_parts()
    for what, path in made:
        part = _part_of(path, parts)
        assert part is not None, f"{what} ({path}) is in no part"
        assert not part["unlisted"], f"{what} ({path}) isn't named by path_utils.PARTS"
        want = path_utils.STAYS if what in STAYS else path_utils.MOVES
        assert part["start_over"] == want, f"{what}: {part}"


def test_an_entry_nobody_named_moves_with_start_over_and_is_named_unlisted():
    """§4.4's default: never left behind silently — it moves, and the record names it."""
    stray = _make(os.path.join(path_utils.persistent_root(), "made_by_a_new_feature.json"))
    part = _part_of(stray)
    assert part["unlisted"] and part["start_over"] == path_utils.MOVES and part["role"] == "unlisted"


def test_in_the_library_folder_only_surasuras_own_names_are_ever_parts():
    """A portable program's folder (or a checkout) holds the program itself: never a part, so never moved."""
    for name in ("Surasura.exe", "_internal", "app", "README.md"):
        _make(os.path.join(path_utils.get_user_data_path(), name), folder=name in ("_internal", "app"))
    roles = {p["rel"]: p for p in path_utils.profile_parts() if p["place"] == "library"}
    assert not {"Surasura.exe", "_internal", "app", "README.md"} & set(roles)
    _make(os.path.join(path_utils.get_user_files_path("ja"), "KnownWord.json"))
    assert roles.get("User Files") is None                               # made after the listing above
    part = _part_of(os.path.join(path_utils.get_user_files_path("ja"), "KnownWord.json"))
    assert part["role"] == "user_files" and part["start_over"] == path_utils.MOVES


def test_only_this_installs_stores_move_and_their_lock_files_stay():
    """`libraries` (the test root's `index`) holds every install's stores: another install's stay, and so do this
    one's lock files (whoever holds one holds it open)."""
    mine = ls.library_db_path("ja", path_utils.get_data_path("ja"))
    for suffix in ("", "-wal", "-shm", ".bak.20261101-120000", ".lock", ".wlock"):
        _make(mine + suffix)
    other = _make(os.path.join(os.path.dirname(mine), "library_ja_0123456789abcdef.db"))
    parts = path_utils.profile_parts()
    for suffix in ("", "-wal", "-shm", ".bak.20261101-120000"):
        part = _part_of(mine + suffix, parts)
        assert part["role"] == "library_store" and part["start_over"] == path_utils.MOVES
        assert part["sort_again"] == path_utils.PART
    for path in (mine + ".lock", mine + ".wlock", other):
        assert _part_of(path, parts)["start_over"] == path_utils.STAYS


def test_another_installs_folder_in_the_local_root_stays_and_this_ones_is_its_own_place(monkeypatch):
    """The real layout: this install's folder sits inside the local root; another install's folder there stays."""
    local = path_utils.local_data_root()
    own = os.path.join(local, "aaaaaaaaaaaaaaaa")
    monkeypatch.setattr(path_utils, "get_local_data_path", lambda: _make(own, folder=True))
    _make(os.path.join(own, "window_state.json"))
    _make(os.path.join(local, "bbbbbbbbbbbbbbbb", "window_state.json"))
    parts = path_utils.profile_parts()
    assert _part_of(os.path.join(own, "window_state.json"), parts)["place"] == "install"
    other = _part_of(os.path.join(local, "bbbbbbbbbbbbbbbb"), parts)
    assert other["role"] == "other_install" and other["start_over"] == path_utils.STAYS
    assert not [p for p in parts if p["place"] == "local" and p["rel"] == "aaaaaaaaaaaaaaaa"]


def test_a_place_that_isnt_there_has_no_parts_and_nothing_is_made():
    """A first start (nothing written yet): no parts, and the listing makes no folder (it reads only)."""
    roaming = path_utils.persistent_root()
    assert not os.path.exists(roaming)
    assert [p for p in path_utils.profile_parts() if p["place"] == "roaming"] == []
    assert not os.path.exists(roaming)


def test_every_part_a_sort_again_sets_aside_is_marked_part():
    """`start_fresh`'s moves (the manifest, the folder-time cache, `data/<lang>`'s entries) and its store lie in
    parts marked PART for Sort again: the table and the reset agree on what Sort again touches."""
    from app import sources
    for lang in LANGUAGES:
        data_dir, user_files_dir = path_utils.get_data_path(lang), path_utils.get_user_files_path(lang)
        touch(data_dir, "Library/" + names(lang)[3] + ".srt", names(lang)[4])
        _make(ls.manifest_path(user_files_dir))
        _make(sources.cache_path(lang))
        _make(ls.library_db_path(lang, data_dir))
    parts = path_utils.profile_parts()
    for lang in LANGUAGES:
        for path in (ls.manifest_path(path_utils.get_user_files_path(lang)), sources.cache_path(lang),
                     os.path.join(path_utils.get_data_path(lang), "Library"),
                     ls.library_db_path(lang, path_utils.get_data_path(lang))):
            assert _part_of(path, parts)["sort_again"] == path_utils.PART, path


def test_settings_are_found_where_the_layout_keeps_them(monkeypatch):
    """Installed: settings.json in the roaming root; portable or source: in the library folder. Either way the part
    named settings is the one the program reads (`get_settings_path`)."""
    _make(path_utils.get_settings_path())
    part = _part_of(path_utils.get_settings_path())
    assert part["role"] == "settings" and part["place"] == "library"
    monkeypatch.setattr(path_utils, "installed_library", lambda: _root())
    _make(path_utils.get_settings_path())
    part = _part_of(path_utils.get_settings_path())
    assert part["role"] == "settings" and part["place"] == "roaming"


def test_every_role_that_moves_has_words_for_the_window():
    """A refusal names the part that was held in plain words (`profile_reset.WHAT`), never a role code."""
    from app import profile_reset
    moving = {role for _p, _n, role, so, _sa in path_utils.PARTS if so == path_utils.MOVES}
    assert moving | {"library_store", "unlisted"} <= set(profile_reset.WHAT)

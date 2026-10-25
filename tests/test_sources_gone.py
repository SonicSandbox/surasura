"""T6 (Sonic 2026-10-24, alpha 2's first try: "Yes your lean is exactly what i'd do"): a source folder that is GONE —
moved or deleted while its drive, or the folder above it, is still there — is told apart from one that is AWAY (an
unplugged drive, a share or NAS down, a parent that can't be read). A gone one becomes ONE *Needs you* card (the window
draws it): *Find its new folder…* · *Stop reading it* · *Keep waiting*. Away stays as today (the offline line).

Why these matter: a gone Downloads show read as "offline" left 届 amber with nothing to do (*Keep waiting* and × only,
*Needs you* empty). The fix must never call an away drive gone (a learner told his NAS show "moved" would stop
reading it), *Find its new folder…* must join the old folder's episodes to the new place with no second copy — also
when that place is read already (his root 19) — and *Stop reading it* moves nothing on disk, removes no episode, and
comes back with Undo. Every scenario runs for Japanese and Chinese, with real subtitles from tests/Test Resources/, in
temp folders under the per-test SURASURA_TEST_ROOT (never anyone's real folder); a `subst` drive stands in for a drive
letter that goes away.
"""
import os
import shutil
import string
import subprocess
import sys
import time

import pytest

from app import library_store as ls
from app import sources
from app.connect import library as connect_library
from app.services import source_looks
from tests.test_library_store_support import LANGUAGES, names, roots
from tests.test_sources_scan import _fresh_module_state  # noqa: F401  (each test a new run of the app)


# --- helpers ------------------------------------------------------------------------------------------------------- #

def _elsewhere(*parts):
    """A folder beside the test's data folder ("another drive"), never inside it."""
    path = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", *parts)
    os.makedirs(path, exist_ok=True)
    return path


def _empty(language):
    from tests.test_library_store_sources import _empty as empty
    return empty(language)


def _show(language, folder, count=3):
    """`count` real subtitles of one show in `folder` (settled): their paths."""
    from tests.test_library_store_sources import _scanned_show
    return _scanned_show(language, os.path.dirname(folder), os.path.basename(folder), count)


def _look(store, language, root, **kw):
    from tests.test_sources_scan import _look as look
    return look(store, language, root, **kw)


def _settle(root):
    from tests.test_sources_scan import _settle as settle
    settle(root)


def _rows(store):
    """Every item as the learner sees it: id, tier, place, file, availability, title."""
    return store.conn.execute("SELECT id, tier, ord, rel_path, availability, work_id FROM items ORDER BY id").fetchall()


def _tree(top):
    out = []
    for where, dirs, files in os.walk(top):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(where, f)
            out.append((os.path.relpath(p, top), os.path.getsize(p)))
    return out


def _counts(store):
    return {s["path"]: s["items"] for s in store.sources(all=True)}


def _marked(store, paths):
    origins = store.origins()
    return [origins[ls.path_key(os.path.abspath(p))].moved_to is not None for p in paths]


def _subst(target):
    """A free drive letter standing in for `target` (`subst`): the letter, or None where subst can't run."""
    taken = {d for d in string.ascii_uppercase if os.path.exists(d + ":\\")}
    for letter in "ZYXWVUTSRQPONMLKJ":
        if letter in taken:
            continue
        try:
            done = subprocess.run(["subst", letter + ":", target], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode == 0 and os.path.isdir(letter + ":\\"):
            return letter
    return None


def _unsubst(letter):
    subprocess.run(["subst", letter + ":", "/d"], capture_output=True, timeout=30)


def unplug(monkeypatch, drive):
    """A drive unplugged, in temp folders: `drive` goes, and whatever still answers above it is another volume (as above
    a drive letter whose root isn't there). -> put it back (the folder, the volumes)."""
    os.rename(drive, drive + " (unplugged)")
    real = sources._volume_at
    monkeypatch.setattr(sources, "_volume_at", lambda path: real(path) + 7)

    def back():
        monkeypatch.setattr(sources, "_volume_at", real)
        os.rename(drive + " (unplugged)", drive)
    return back


def _looks(language):
    data_dir, user_files_dir = roots(language)
    return source_looks.SourceLooks(ls.StoreOpener(language, data_dir, user_files_dir), language,
                                    kind=lambda _p: "network")


def _writer(language):
    from app.qt.strings import MOVE_WORDS
    from app.services import moves
    from tests.test_services_moves import Heard
    data_dir, user_files_dir = roots(language)
    heard = Heard()
    w = moves.Writer(ls.StoreOpener(language, data_dir, user_files_dir, role="window"), language,
                     journal_file=moves.journal_path(language), words=MOVE_WORDS, retry=0.05, **heard.kw())
    return w.start(), heard


def _until(condition, seconds=30.0):
    from tests import services_helpers as h
    return h.until(condition, seconds)


# --- the rule: gone or away (`sources.reach`) -------------------------------------------------------------------- #

def test_a_folder_removed_from_a_folder_still_there_is_gone_and_one_whose_drive_went_is_away(monkeypatch):
    """The one rule, on plain folders: there → reached; removed while the folder above it lists, on its volume → gone;
    its drive unplugged (only another volume answers above it) → away — never gone."""
    parent = _elsewhere("Downloads")
    folder = os.path.join(parent, "Show")
    os.makedirs(folder)
    dev = os.stat(folder).st_dev
    assert sources.reach(folder, dev=dev) == sources.REACHED
    os.rename(folder, folder + " (moved)")
    assert sources.reach(folder, dev=dev) == sources.GONE
    assert sources.reach(folder.upper(), dev=dev) == sources.GONE   # one folder however written (A2)
    back = unplug(monkeypatch, parent)
    assert sources.reach(folder, dev=dev) == sources.AWAY
    back()


def test_a_drive_letter_that_is_not_there_and_a_drive_root_are_away():
    """An unplugged drive takes its root with it: away. A source that IS a drive or share root has nothing above it to
    read: never gone."""
    taken = {d for d in string.ascii_uppercase if os.path.exists(d + ":\\")}
    letter = next(d for d in "ZYXWVUTSRQPONMLKJ" if d not in taken)
    assert sources.reach(letter + ":\\Anime\\Show") == sources.AWAY
    assert sources.reach(letter + ":\\") == sources.AWAY


def test_a_folder_last_seen_on_another_volume_is_never_gone():
    """Another stick plugged in at the same letter (or a folder that was a mounted volume): the folder above lists, but
    it is not the volume the folder was read on — away, as an unplugged drive is."""
    parent = _elsewhere("Media")
    folder = os.path.join(parent, "Show")
    os.makedirs(folder)
    dev = os.stat(folder).st_dev
    os.rmdir(folder)
    assert sources.reach(folder, dev=dev) == sources.GONE
    assert sources.reach(folder, dev=dev + 1) == sources.AWAY


def test_with_no_volume_recorded_only_the_system_volume_says_gone(monkeypatch):
    """When unsure, AWAY: a folder last read before this rule (no volume recorded yet — Sonic's
    Downloads folder) is gone only where the folder above it is on Windows' own volume, which no stick or share can
    take over; anywhere else (a stick or USB disk whose letter another may answer at, a share, a Mac's /Volumes) it is
    away. With a volume recorded, the volume decides."""
    parent = _elsewhere("Media")
    folder = os.path.join(parent, "Show")
    os.makedirs(folder)
    dev = os.stat(folder).st_dev
    os.rmdir(folder)
    monkeypatch.setattr(sources, "_system_volume", lambda d: d == dev)
    assert sources.reach(folder) == sources.GONE
    monkeypatch.setattr(sources, "_system_volume", lambda d: False)
    assert sources.reach(folder) == sources.AWAY
    assert sources.reach(folder, dev=dev) == sources.GONE
    assert sources.reach(folder, dev=dev + 1) == sources.AWAY


def test_a_share_that_is_down_costs_one_wait_never_four(monkeypatch):
    """A8 (G5: one wait): a NAS or share down answers *the network path was not found* (Windows' 53) — away at once,
    with one call that reaches the share; the look's own failed stat of the folder is reused (no second ask)."""
    parent = _elsewhere("NAS")
    folder = os.path.join(parent, "Show")
    calls = []
    real_stat, real_scandir = os.stat, os.scandir

    def under(path):
        hit = os.path.normcase(os.fspath(path)).startswith(os.path.normcase(parent))
        if hit:
            calls.append(path)
        return hit

    def stat(path, *a, **kw):
        if under(path):
            raise OSError(None, "The network path was not found", None, 53)
        return real_stat(path, *a, **kw)

    def scandir(path="."):
        if under(path):
            raise OSError(None, "The network path was not found", None, 53)
        return real_scandir(path)
    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(os, "scandir", scandir)
    assert sources.reach(folder, dev=1) == sources.AWAY and len(calls) == 1
    del calls[:]
    down = OSError(None, "The network path was not found", None, 53)
    assert sources.reach(folder, dev=1, error=down) == sources.AWAY and calls == []


def test_the_system_volume_is_windows_own_and_no_other():
    """`_system_volume` names %SystemDrive%'s volume alone (off Windows, none): another volume is never taken for it."""
    if sys.platform != "win32":
        assert sources._system_volume(os.stat(os.sep).st_dev) is False
        return
    own = os.stat(os.environ.get("SystemDrive", "C:") + os.sep).st_dev
    assert sources._system_volume(own) is True
    assert sources._system_volume(own + 1) is False


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_look_at_a_share_that_is_down_asks_it_once(language, monkeypatch):
    """G5 at the look: the look's own failed check of the folder is what decides gone or away — the share isn't asked
    a second time (each ask of a share that's down is a network wait)."""
    store, data_dir = _empty(language)
    nas = _elsewhere("NAS")
    show = os.path.join(nas, names(language)[71])
    _show(language, show)
    with store:
        root = store.add_source(show)
        _look(store, language, root, first=True)
        calls = []
        real_stat, real_scandir = os.stat, os.scandir

        def under(path):
            hit = os.path.normcase(os.path.abspath(os.fspath(path))).startswith(os.path.normcase(nas))
            if hit:
                calls.append(path)
            return hit

        def stat(path, *a, **kw):
            if under(path):
                raise OSError(None, "The network path was not found", None, 53)
            return real_stat(path, *a, **kw)

        def scandir(path="."):
            if under(path):
                raise OSError(None, "The network path was not found", None, 53)
            return real_scandir(path)
        monkeypatch.setattr(os, "stat", stat)
        monkeypatch.setattr(os, "scandir", scandir)
        try:
            result = sources.scan(store, language, root, full=True)
        finally:
            monkeypatch.setattr(os, "stat", real_stat)
            monkeypatch.setattr(os, "scandir", real_scandir)
        assert (result["reachable"], result["gone"]) == (False, False)
        assert len(calls) == 1, calls


def test_a_folder_whose_parent_moved_too_is_gone_on_the_same_volume():
    """The shows' folder itself moved (`Downloads/Anime/<show>`, each show its own source):
    the first folder above that still lists, on the volume the show was read on, says gone — not only the parent."""
    downloads = _elsewhere("Downloads")
    folder = os.path.join(downloads, "Anime", "Show")
    os.makedirs(folder)
    dev = os.stat(folder).st_dev
    os.rename(os.path.join(downloads, "Anime"), os.path.join(_elsewhere("D-drive"), "Anime"))
    assert sources.reach(folder, dev=dev) == sources.GONE
    assert sources.reach(folder, dev=dev + 1) == sources.AWAY


def test_a_folder_still_listed_by_its_parent_but_unreadable_is_away():
    """A folder link (junction) to a drive that's away is listed by the folder above it, yet can't be read: away,
    never gone (its files may all be on that drive)."""
    try:
        import _winapi
    except ImportError:
        pytest.skip("folder links are Windows junctions here")
    parent = _elsewhere("Links")
    target = _elsewhere("Target", "Show")
    link = os.path.join(parent, "Show")
    _winapi.CreateJunction(target, link)
    try:
        assert sources.reach(link) == sources.REACHED
        shutil.rmtree(os.path.dirname(target))                     # the drive the link points at goes
        assert sources.reach(link) == sources.AWAY
        assert sources.reach(os.path.join(link, "Season 2")) == sources.AWAY  # a show inside it, walked up to it
    finally:
        os.rmdir(link)


def test_a_share_that_answers_with_an_error_is_away_and_never_gone(monkeypatch):
    """A NAS or share down answers *the network path was not found* (Windows' 53 — Python's FileNotFoundError, like a
    folder that's simply missing) for the folder AND for the folder above it: away. Access denied on the folder is
    away at once; the folder above it unreadable, away."""
    parent = _elsewhere("Share")
    folder = os.path.join(parent, "Show")
    real_stat, real_scandir = os.stat, os.scandir
    down = OSError(None, "The network path was not found", None, 53)
    assert isinstance(down, FileNotFoundError)

    def under(path):
        return os.path.normcase(os.fspath(path)).startswith(os.path.normcase(parent))

    def stat(path, *a, **kw):
        if under(path):
            raise OSError(None, "The network path was not found", None, 53)
        return real_stat(path, *a, **kw)

    def scandir(path="."):
        if under(path):
            raise OSError(None, "The network path was not found", None, 53)
        return real_scandir(path)
    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(os, "scandir", scandir)
    assert sources.reach(folder) == sources.AWAY
    monkeypatch.setattr(os, "stat", real_stat)
    assert sources.reach(folder) == sources.AWAY                      # the folder above can't be listed

    def denied(path, *a, **kw):
        if os.path.normcase(os.fspath(path)) == os.path.normcase(folder):
            raise PermissionError(13, "Access is denied")
        return real_stat(path, *a, **kw)
    monkeypatch.setattr(os, "scandir", real_scandir)
    monkeypatch.setattr(os, "stat", denied)
    assert sources.reach(folder) == sources.AWAY


# --- the look says it (`sources.scan`), ja + zh ------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_look_says_gone_for_a_show_folder_moved_away_and_away_for_a_drive_unplugged(language, monkeypatch):
    """Sonic's case on plain folders: each show folder in Downloads is its own source. Moved out of Downloads: the look
    says unreachable and gone; Downloads itself unreadable: unreachable, not gone. Nothing is marked or moved, and the
    folder keeps counting its episodes either way."""
    store, data_dir = _empty(language)
    show = os.path.join(_elsewhere("Downloads"), names(language)[71])
    _show(language, show)
    with store:
        root = store.add_source(show)
        assert _look(store, language, root, first=True)["added"] == 3
        before = _rows(store)
        os.rename(show, show + " (moved)")
        result = _look(store, language, root, full=True)
        assert (result["reachable"], result["gone"]) == (False, True)
        downloads = os.path.dirname(show)
        os.rename(show + " (moved)", show)
        back = unplug(monkeypatch, downloads)
        try:
            result = _look(store, language, root, full=True)
            assert (result["reachable"], result["gone"]) == (False, False)
        finally:
            back()
        assert _rows(store) == before and _counts(store)[store.sources()[0]["path"]] == 3


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_look_records_its_folders_volume_and_a_folder_on_another_volume_now_is_away(language):
    """The look keeps the volume it read the folder on (the folder-time cache, beside Connect's video index); a later
    look whose folder is missing while another volume answers at that place says away."""
    import json
    store, data_dir = _empty(language)
    show = os.path.join(_elsewhere("Stick"), names(language)[71])
    _show(language, show)
    with store:
        root = store.add_source(show)
        _look(store, language, root, first=True)
        with open(sources.cache_path(language), encoding="utf-8") as f:
            cache = json.load(f)
        assert cache["roots"][str(root)]["dev"] == os.stat(show).st_dev
        cache["roots"][str(root)]["dev"] = os.stat(show).st_dev + 1        # read last on another volume
        with open(sources.cache_path(language), "w", encoding="utf-8") as f:
            json.dump(cache, f)
        shutil.rmtree(show)
        result = _look(store, language, root, full=True)
        assert (result["reachable"], result["gone"]) == (False, False)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_subst_drive_taken_away_is_away_and_its_folder_moved_on_it_is_gone(language):
    """A drive letter standing in for a NAS or a stick (`subst`): taken away, the show's folder is away — the letter's
    root can't be read; the letter back and the folder moved on it, gone."""
    store, data_dir = _empty(language)
    stand_in = _elsewhere("NAS")
    letter = _subst(stand_in)
    if letter is None:
        pytest.skip("subst can't make a drive letter here")
    try:
        show = letter + ":\\" + names(language)[71]
        _show(language, show)
        with store:
            root = store.add_source(show)
            assert _look(store, language, root, first=True)["added"] == 3
            before = _rows(store)
            _unsubst(letter)
            result = _look(store, language, root, full=True)
            assert (result["reachable"], result["gone"]) == (False, False), "an unplugged drive is never gone"
            assert sources.reach(show) == sources.AWAY
            assert _subst(stand_in) == letter or pytest.skip("the letter was taken meanwhile")
            os.rename(show, show + " (moved)")
            result = _look(store, language, root, full=True)
            assert (result["reachable"], result["gone"]) == (False, True)
            assert _rows(store) == before
    finally:
        _unsubst(letter)


# --- the moves join (D5 / MV-1) knows a gone folder from an away one ---------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_folder_moved_into_a_folder_read_already_joins_its_episodes_and_the_old_folder_counts_none(language):
    """Downloads/Show (its own source) moved into Anime, which is read: Anime's look attaches the episodes (no second
    copy) and, the old folder being gone (not away), says the originals moved — the old folder counts 0."""
    store, data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    anime = _elsewhere("Anime")
    files = _show(language, old)
    with store:
        root_a = store.add_source(old)
        _look(store, language, root_a, first=True)
        root_b = store.add_source(anime)
        _look(store, language, root_b)
        before = _rows(store)
        shutil.move(old, os.path.join(anime, title))
        _settle(anime)
        result = _look(store, language, root_b, full=True)
        assert (result["added"], result["attached"]) == (0, 3)
        assert _rows(store) == before
        assert _marked(store, files) == [True] * 3
        assert _counts(store) == {old: 0, anime: 3}
        detail = store.source_detail([root_a])[root_a]                 # its card still names the show, and where
        assert detail["shows"] and [os.path.normcase(p) for p in detail["found_in"]] == [os.path.normcase(anime)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiting_video_moved_out_of_a_gone_folder_stays_its_one_waiting_item(language):
    """A video with no subtitle yet (it waits in New arrivals) moved with its gone folder into a read one: the same
    waiting item, its new place recorded — never a second waiting row."""
    from tests.test_sources_scan import _video
    store, data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    _video(os.path.join(old, f"[Grp] {title} - 01.mkv"), body=b"\x1a\x45\xdf\xa3 waiting episode one")
    _settle(old)
    anime = _elsewhere("Anime")
    with store:
        root_a = store.add_source(old)
        _look(store, language, root_a)
        waiting = store.conn.execute("SELECT id FROM items WHERE availability = 'waiting'").fetchall()
        assert len(waiting) == 1
        root_b = store.add_source(anime)
        shutil.move(old, os.path.join(anime, title))
        _settle(anime)
        _look(store, language, root_b, full=True)
        assert store.conn.execute("SELECT id FROM items WHERE availability = 'waiting'").fetchall() == waiting
        assert _counts(store) == {old: 0, anime: 1}


# --- *Find its new folder…* (`SourceLooks.find_new_folder`): add_source, the look, the join ---------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_find_its_new_folder_when_it_is_read_already_joins_the_old_folders_episodes_with_no_second_copy(language):
    """Sonic's root 13 and root 19: the show copied to S:\\…\\Show and that folder read (its look attached the episodes
    to the same items, the old folder still there then), then the Downloads folder deleted. The old folder is gone and
    still counts its episodes; *Find its new folder…* on the read folder joins them there — no item, copy or file
    made, every row as it was — and says the old folder can stop being read."""
    store, data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    new = os.path.join(_elsewhere("Video", "Anime"), title)
    files = _show(language, old)
    with store:
        root_a = store.add_source(old)
        _look(store, language, root_a, first=True)
        shutil.copytree(old, new, copy_function=shutil.copy2)
        _settle(new)
        root_b = store.add_source(new)
        assert _look(store, language, root_b)["attached"] == 3
        shutil.rmtree(old)
        assert _counts(store) == {old: 3, new: 3}
        before, library = _rows(store), _tree(os.path.join(data_dir, ls.CONTENT_FOLDER))
    looks = _looks(language)
    heard = []
    try:
        assert looks.find_new_folder(root_a, new, heard.append)
        assert looks.idle(60)
    finally:
        looks.close()
        looks.idle(10)
    answer = heard[0]
    assert (answer["root"], answer["refused"], answer["joined"], answer["stop"]) == (root_b, None, 3, True)
    store = ls.open_store(language, *roots(language))
    try:
        assert _rows(store) == before and _tree(os.path.join(data_dir, ls.CONTENT_FOLDER)) == library
        assert _marked(store, files) == [True] * 3
        assert _counts(store) == {old: 0, new: 3}
        for item_id, *_rest in before:                     # Connect reads the episode at its new place
            record = connect_library.pairing_of(store, item_id)
            assert os.path.normcase(record["origin"]).startswith(os.path.normcase(new))
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_find_its_new_folder_not_read_yet_reads_it_and_joins_the_episodes(language):
    """The show moved to a folder nothing reads: *Find its new folder…* adds it (add_source), its look attaches every
    episode (added 0) and the old folder counts none."""
    store, data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    files = _show(language, old)
    with store:
        root_a = store.add_source(old)
        _look(store, language, root_a, first=True)
        before = _rows(store)
    new = os.path.join(_elsewhere("Archive"), title)
    shutil.move(old, new)
    _settle(new)
    looks, heard = _looks(language), []
    try:
        assert looks.find_new_folder(root_a, new, heard.append)
        assert looks.idle(60)
    finally:
        looks.close()
        looks.idle(10)
    answer = heard[0]
    assert answer["refused"] is None and answer["stop"] is True and answer["result"]["added"] == 0
    assert answer["joined"] == 3                                      # joined by its own look (D5): counted
    store = ls.open_store(language, *roots(language))
    try:
        assert _rows(store) == before and _marked(store, files) == [True] * 3
        assert _counts(store) == {old: 0, new: 3}
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_find_its_new_folder_when_the_old_one_is_back_or_only_away_joins_and_stops_nothing(language, monkeypatch):
    """The old folder came back meanwhile, or only its drive went (away): the new folder is read, but nothing says the
    old folder's episodes moved and it is not offered to stop (it isn't gone)."""
    store, data_dir = _empty(language)
    title = names(language)[71]
    downloads = _elsewhere("Downloads")
    old = os.path.join(downloads, title)
    new = os.path.join(_elsewhere("Copy"), title)
    files = _show(language, old)
    shutil.copytree(old, new, copy_function=shutil.copy2)
    _settle(new)
    with store:
        root_a = store.add_source(old)
        _look(store, language, root_a, first=True)
    for state in ("back", "away"):
        looks, heard, said = _looks(language), [], []
        looks.on_result = said.append
        os.rename(old, old + " (moved)")                               # a look sees it gone first: its card drawn
        assert looks.asked(refreshed=True) and looks.idle(60)
        assert next(r for r in said[-1]["sources"] if r["id"] == root_a)["gone"] is True
        os.rename(old + " (moved)", old)
        if state == "away":
            back = unplug(monkeypatch, downloads)
        try:
            assert looks.find_new_folder(root_a, new, heard.append)
            assert looks.idle(60)
        finally:
            looks.close()
            looks.idle(10)
        assert (heard[0]["refused"], heard[0]["joined"], heard[0]["stop"], heard[0]["state"]) == \
            (None, 0, False, sources.REACHED if state == "back" else sources.AWAY)
        row = next(r for r in said[-1]["sources"] if r["id"] == root_a)      # A3: the card goes with what Find found
        assert (row["reachable"], row["gone"]) == (state == "back", False)
    back()
    store = ls.open_store(language, *roots(language))
    try:
        assert _marked(store, files) == [False] * 3
        assert all(s["on"] for s in store.sources(all=True))
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_find_its_new_folder_when_its_look_cant_run_or_the_join_fails_never_stops_the_old_folder(language,
                                                                                                  monkeypatch):
    """Another look holding the library (busy): the new folder is read from now on (`later`), but nothing is joined yet
    and the old folder is not offered to stop — its card stays until a look joins its episodes. A join that fails
    after the folder was added says `failed` (never `refused`: the folder IS read now) and stops nothing."""
    store, data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    _show(language, old)
    with store:
        root_a = store.add_source(old)
        _look(store, language, root_a, first=True)
        key = sources._store_key(store)
    new = os.path.join(_elsewhere("Archive"), title)
    shutil.move(old, new)
    _settle(new)
    sources._RUNNING.add(key)                                       # another look holds the library
    try:
        looks, heard = _looks(language), []
        try:
            assert looks.find_new_folder(root_a, new, heard.append)
            assert looks.idle(60)
        finally:
            looks.close()
            looks.idle(10)
    finally:
        sources._RUNNING.discard(key)
    assert heard[0]["later"] is True and (heard[0]["joined"], heard[0]["stop"], heard[0]["refused"]) == (0, False, None)

    def broken(self, root_id, folder):
        raise ls.StoreBusy("the library is busy")
    monkeypatch.setattr(ls.Store, "join_moved", broken)
    looks, heard = _looks(language), []
    try:
        assert looks.find_new_folder(root_a, new, heard.append)
        assert looks.idle(60)
    finally:
        looks.close()
        looks.idle(10)
    assert heard[0]["root"] is not None and heard[0]["refused"] is None and heard[0]["failed"]
    assert heard[0]["stop"] is False


@pytest.mark.parametrize("language", LANGUAGES)
def test_find_its_new_folder_holding_none_of_its_episodes_stops_nothing(language):
    """The wrong folder picked (none of the show's episodes there): it is read now,
    but nothing joined, so the old folder isn't stopped — its card stays, and the answer says none were found."""
    store, data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    _show(language, old)
    with store:
        root_a = store.add_source(old)
        _look(store, language, root_a, first=True)
    shutil.rmtree(old)
    other = os.path.join(_elsewhere("Elsewhere"), names(language)[72])
    from tests.test_sources_scan import _text, _write
    _write(os.path.join(other, f"{names(language)[72]} - 01.{language}.srt"), _text(language, 7, " another show"))
    _settle(other)
    looks, heard = _looks(language), []
    try:
        assert looks.find_new_folder(root_a, other, heard.append)
        assert looks.idle(60)
    finally:
        looks.close()
        looks.idle(10)
    assert (heard[0]["refused"], heard[0]["joined"], heard[0]["stop"], heard[0]["state"]) == \
        (None, 0, False, sources.GONE)


@pytest.mark.parametrize("language", LANGUAGES)
def test_find_its_new_folder_refused_says_why_and_changes_nothing(language):
    """A folder Surasura can't read (its own data folder, a path that isn't a folder): the store's own reason, no root
    added, nothing joined, nothing to stop."""
    store, data_dir = _empty(language)
    old = os.path.join(_elsewhere("Downloads"), names(language)[71])
    _show(language, old)
    with store:
        root_a = store.add_source(old)
        _look(store, language, root_a, first=True)
        shutil.rmtree(old)
        before = store.sources(all=True)
    for path in (data_dir, os.path.join(_elsewhere("Nowhere"), "not there")):
        looks, heard = _looks(language), []
        try:
            assert looks.find_new_folder(root_a, path, heard.append)
            assert looks.idle(60)
        finally:
            looks.close()
            looks.idle(10)
        assert heard[0]["refused"] and heard[0]["root"] is None and heard[0]["stop"] is False
    store = ls.open_store(language, *roots(language))
    try:
        assert store.sources(all=True) == before
    finally:
        store.close()


# --- *Stop reading it*: the root off, nothing moved, one Undo ----------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_stop_reading_a_gone_folder_keeps_every_episode_and_file_and_undo_reads_it_again(language):
    """Through the window's writer: the gone folder is no longer read (off, its row kept); every item, its place, its
    copy, its records and the trash are exactly as they were — nothing on disk moves. Undo (Ctrl+Z, the toast's) turns
    it back on: gone again, its card back."""
    store, data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    _show(language, old)
    root = store.add_source(old)
    _look(store, language, root, first=True)
    store.set_tier([store.ids("now")[0]], "graduated")
    shutil.rmtree(old)
    before = (_rows(store), store.origins(), _tree(data_dir))
    w, heard = _writer(language)
    try:
        assert w.stop_reading(root, label="stopped")
        assert _until(lambda: heard.saved)
        change, label = heard.saved[0]
        assert label == "stopped" and change.kind == "stop_source"
        assert [s["id"] for s in store.sources()] == [] and store.sources(all=True)[0]["on"] is False
        assert (_rows(store), store.origins(), _tree(data_dir)) == before
        assert w.undo(label="undo")
        assert _until(lambda: heard.undone)
        assert [s["id"] for s in store.sources()] == [root]
        assert (_rows(store), store.origins(), _tree(data_dir)) == before
    finally:
        w.finish(time.monotonic() + 5)
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_undo_of_a_stop_leaves_a_folder_turned_back_on_since_as_it_is(language):
    """The value check (§6.11): turned back on meanwhile (*Read it where it is* again), the stop's Undo writes
    nothing and says it was left as it is; a stop of a folder not being read is no change."""
    store, data_dir = _empty(language)
    folder = os.path.join(_elsewhere("Media"), names(language)[71])
    _show(language, folder)
    with store:
        root = store.add_source(folder)
        change = store.stop_source(root)
        assert change is not None and change.kind == "stop_source"
        assert store.stop_source(root) is None
        assert store.add_source(folder) == root
        out = store.undo(change)
        assert out is not None and out.notes and [s["on"] for s in store.sources(all=True)] == [True]
        again = store.stop_source(root)
        store.undo(again)
        assert [s["on"] for s in store.sources(all=True)] == [True]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_writers_undo_of_a_stop_turned_back_on_meanwhile_says_it_couldnt_and_another_language_is_refused(language):
    """A4: the folder read again meanwhile (+ Add), the toast's Undo writes nothing and says *Can't undo* — never a
    quiet "undone". A5 (B2): a stop given for another language's library (root ids repeat across stores) is refused
    before anything is queued."""
    from app.qt.strings import MOVE_WORDS
    store, data_dir = _empty(language)
    folder = os.path.join(_elsewhere("Media"), names(language)[71])
    _show(language, folder)
    root = store.add_source(folder)
    w, heard = _writer(language)
    try:
        other = "zh" if language == "ja" else "ja"
        assert not w.stop_reading(root, label="stopped", language=other)
        assert w.stop_reading(root, label="stopped", language=language)
        assert _until(lambda: heard.saved)
        assert store.add_source(folder) == root                                 # read again meanwhile
        assert w.undo(label="undo")
        assert _until(lambda: heard.notes)
        assert heard.notes == [MOVE_WORDS["cant_undo"]] and heard.undone == []
        assert [s["on"] for s in store.sources(all=True)] == [True]
    finally:
        w.finish(time.monotonic() + 5)
        store.close()


def test_a_stop_on_a_busy_store_is_journalled_and_a_crash_replays_it_once(monkeypatch):
    """*Stop reading it* on a busy store waits in the writer's journal; after a crash the next start applies it once.
    One that landed before the crash is let go quietly."""
    from tests.test_services_moves import LockHolder, journal, journalled
    real = ls._WriteLock.acquire
    monkeypatch.setattr(ls._WriteLock, "acquire", lambda self, timeout=ls.LOCK_TIMEOUT: real(self, min(timeout, 0.2)))
    language = "ja"
    store, data_dir = _empty(language)
    folder = os.path.join(_elsewhere("Downloads"), names(language)[71])
    _show(language, folder)
    root = store.add_source(folder)
    _look(store, language, root, first=True)
    shutil.rmtree(folder)
    w, heard = _writer(language)
    w2 = w3 = None
    try:
        holder = LockHolder(store.db_path)
        w.stop_reading(root, label="stopped")
        assert _until(lambda: journalled(language) == [("stop_source", [])])
        w._abandon()                                                             # the crash
        holder.release()
        assert [s["on"] for s in store.sources(all=True)] == [True]
        w2, heard2 = _writer(language)
        assert w2.replay()
        assert _until(lambda: [s["on"] for s in store.sources(all=True)] == [False] and not w2.pending())
        w2.finish(time.monotonic() + 5)
        assert heard2.notes == []
        with store._writing():                                                   # (on again, for the next run)
            store.conn.execute("UPDATE roots SET kind = 'source' WHERE id = ?", (root,))
        holder = LockHolder(store.db_path)
        w3, heard3 = _writer(language)
        w3.stop_reading(root, label="stopped")
        assert _until(lambda: journalled(language) == [("stop_source", [])])
        w3._abandon()
        holder.release()
        store.stop_source(root)                                                  # it landed (another window's)
        w4, heard4 = _writer(language)
        try:
            assert w4.replay()
            assert _until(lambda: journal(language) is None and not w4.pending())
            w4.finish(time.monotonic() + 5)
            assert heard4.notes == [] and [s["on"] for s in store.sources(all=True)] == [False]
        finally:
            if not w4._abandoned:
                w4.finish(time.monotonic() + 5)
    finally:
        for writer in (w, w2, w3):
            if writer is not None and not writer._abandoned:
                writer.finish(time.monotonic() + 5)
        store.close()


# --- the data the card needs: the summary ------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_summary_names_a_gone_folder_its_shows_and_where_its_episodes_are_read_now(language, monkeypatch):
    """After a look, a gone folder's row says `gone`, the titles it holds, whether every one of its episodes is
    Finished (*Stop reading it* first) and the folders being read that hold them now (root 19). `gone(rows)` lists
    it for the card; `offline(rows)` lists it as today, `offline(rows, gone=False)` (the line once the card is drawn)
    never; an away folder is never `gone`."""
    store, data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    new = os.path.join(_elsewhere("Anime"), title)
    away_parent = _elsewhere("Stick")
    away = os.path.join(away_parent, names(language)[72])
    _show(language, old)
    from tests.test_sources_scan import _text, _write
    for n in (1, 2):                                                 # its own episodes (other bytes)
        _write(os.path.join(away, f"{names(language)[72]} - {n:02d}.{language}.srt"), _text(language, n, " stick"))
    _settle(away)
    with store:
        root_a, root_c = store.add_source(old), store.add_source(away)
        _look(store, language, root_a, first=True)
        _look(store, language, root_c, first=True)
        shutil.copytree(old, new, copy_function=shutil.copy2)
        _settle(new)
        _look(store, language, store.add_source(new))
        store.set_tier([i for i, e, _a in store.ordered("now") if title in e["physical_path"]] +
                       [i for i, e, _a in store.ordered("soon") if title in e["physical_path"]], "graduated")
    shutil.rmtree(old)
    real = sources._volume_at
    os.rename(away_parent, away_parent + " (unplugged)")             # the stick goes: what answers above it at its
    monkeypatch.setattr(sources, "_volume_at", lambda path: real(path) + (            # letter is another volume
        7 if os.path.normcase(os.fspath(path)) == os.path.normcase(os.path.dirname(away_parent)) else 0))
    looks, said = _looks(language), []
    looks.on_result = said.append
    try:
        assert looks.asked(refreshed=True)
        assert looks.idle(60)
    finally:
        looks.close()
        looks.idle(10)
        monkeypatch.setattr(sources, "_volume_at", real)
        os.rename(away_parent + " (unplugged)", away_parent)
    rows = {r["id"]: r for r in said[-1]["sources"]}
    assert (rows[root_a]["reachable"], rows[root_a]["gone"]) == (False, True)
    assert (rows[root_c]["reachable"], rows[root_c]["gone"]) == (False, False)
    assert rows[root_a]["shows"] == [title] and rows[root_a]["finished"] is True
    assert [os.path.normcase(p) for p in rows[root_a]["found_in"]] == [os.path.normcase(new)]
    assert [r["id"] for r in source_looks.gone(said[-1]["sources"])] == [root_a]
    assert [p for p, _n in source_looks.offline(said[-1]["sources"])] == [old, away]
    assert [p for p, _n in source_looks.offline(said[-1]["sources"], gone=False)] == [away]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_gone_folders_card_says_finished_only_when_every_episode_is(language):
    """*Stop reading it* goes first only for a show that is all Finished: one episode still in Current says not
    finished; the titles come most episodes first."""
    store, data_dir = _empty(language)
    folder = _elsewhere("Downloads", "Shows")
    first, second = names(language)[71], names(language)[72]
    _show(language, os.path.join(folder, first))
    from tests.test_sources_scan import _text, _write
    _write(os.path.join(folder, second, f"{second} - 01.{language}.srt"), _text(language, 9, " other"))
    _settle(folder)
    with store:
        root = store.add_source(folder)
        _look(store, language, root, first=True)
        ids = [i for t in ("now", "soon") for i, _e, _a in store.ordered(t)]
        store.set_tier(ids[:-1], "graduated")
        detail = store.source_detail([root])[root]
        assert detail["finished"] is False and len(detail["shows"]) == 2
        assert detail["found_in"] == []
        store.set_tier(ids[-1:], "graduated")
        assert store.source_detail([root])[root]["finished"] is True
        assert store.source_detail([root + 99]) == {}


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_join_reads_only_the_folder_picked_never_a_folder_whose_name_starts_like_it(language):
    """`…/Show` never holds `…/Show S2`: the old folder's episodes join the copies in the folder picked, even when a
    folder beside it, named like it, holds the same files too."""
    store, data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    anime = _elsewhere("Anime")
    new, twin = os.path.join(anime, title), os.path.join(anime, title + " S2")
    files = _show(language, old)
    with store:
        root_a = store.add_source(old)
        _look(store, language, root_a, first=True)
        for to in (twin, new):
            shutil.copytree(old, to, copy_function=shutil.copy2)
        _settle(anime)
        _look(store, language, store.add_source(twin))
        _look(store, language, store.add_source(new))
        shutil.rmtree(old)
        assert store.join_moved(root_a, new) == 3
        origins = store.origins()
        for f in files:
            assert origins[ls.path_key(os.path.abspath(f))].moved_to.startswith(ls.path_key(new).rstrip("/") + "/")
        assert store.join_moved(root_a, new) == 0                       # marked already: nothing twice


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_join_marks_only_an_original_that_is_gone_and_whose_bytes_are_there(language):
    """MV-A5 and D5: an original still on disk is a copy, never a move (the old folder back: nothing marked); a file in
    the new folder whose bytes differ (edited there since) is not that original — only the others join."""
    store, data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    new = os.path.join(_elsewhere("Anime"), title)
    files = _show(language, old)
    with store:
        root_a = store.add_source(old)
        _look(store, language, root_a, first=True)
        shutil.copytree(old, new, copy_function=shutil.copy2)
        _settle(new)
        _look(store, language, store.add_source(new))
        assert store.join_moved(root_a, new) == 0 and _marked(store, files) == [False] * 3
        shutil.rmtree(old)
        edited = os.path.join(new, os.path.basename(files[0]))
        st = os.stat(edited)
        assert store.update_origin(edited, st.st_size, st.st_mtime_ns, "0" * 64)
        assert store.join_moved(root_a, new) == 2
        assert _marked(store, files) == [False, True, True]
        for folder in (old, os.path.dirname(old)):                      # itself, or a folder above it: nothing
            assert store.join_moved(root_a, folder) == 0

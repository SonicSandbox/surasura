"""hato's episode of a show already in the library joins that show (Kura-HJ, 3.0.17; a Send report of 2026-11-19 —
Sonic ruled: by itself, no setting).

Why these matter: since hato 1.1 (2026-10-30) hato copies each subtitle into a folder of its own series —
`HighPriority/Hato/<series>/<file>` — while the store read only a file directly in `HighPriority/Hato` as hato's loose
drop. A file one folder down got the folder key `hato/<series>` (a key no show folder has: `Library/<series>` is
`<series>`), so it became a title of its own, shown as "Hato/<series>" beside the real show; the disk sync's row for it
(made a moment before hato's hand-off) was never given the record's show, and the record's AniList id then went onto
that title, pulling every later episode there. What a wrong answer would cost: a show split in two rows (the report:
"Hato/<show> · Ep 5–7" above "<show> · Ep 1–4"), Connect mining two titles, and no
way back. The files here are dropped where hato drops them (a folder per series, never flat), in both orders hato and
the disk sync can meet; every test runs for Japanese and Chinese under the per-test SURASURA_TEST_ROOT, with real words
from tests/Test Resources/.
"""

import hashlib
import json
import os

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, names, pieces_ok, roots, touch

ANILIST = 170730        # the show's AniList id as hato's record carries it (jimaku's entry)
ORDERS = ("handoff_first", "sync_first")


def _record(language, show, episode, anilist=ANILIST, **more):
    """hato's pairing record v1 for one episode (09-hato-layer §1; `show.title` is jimaku's entry name)."""
    key = "v1-" + hashlib.sha256(f"{show}|{episode}".encode("utf-8")).hexdigest()[:32]
    record = {"schema": 1, "content_key": key, "producer": "hato", "producer_version": "1.4.2", "language": language,
              "video_path": f"D:/Anime/{show}/{show} - {episode:02d}.mkv", "video_size": 1400000000 + episode,
              "verdict": "timed", "show": {"title": show, "season": 1, "episode": episode, "movie": False},
              "jimaku_entry_id": 4242, "anilist_id": anilist}
    record.update(more)
    return record


def _arrivals_on(store):
    store.bookkeeping({"arrivals_on": 1}, copy_carries=True)     # 3.0's library (D30), as in the report
    return store


def _show(store, data_dir, show, episodes=4):
    """The learner's own show as a source's copy brings it: `Library/<show>/<show> - NN.srt`, in Current. -> its title."""
    paths = [touch(data_dir, f"{ls.CONTENT_FOLDER}/{show}/{show} - {e:02d}.srt", f"{show} {e}\n")
             for e in range(1, episodes + 1)]
    return store.item(store.insert(paths, "now").added[0])["work_id"]


def _drop(data_dir, series, show, episode):
    """hato's copy, where hato puts it: its series' own folder inside the drop folder."""
    return touch(data_dir, f"{ls.HATO_FOLDER}/{series}/[SubsPlease] {show} - {episode:02d} (1080p).srt",
                 f"{series} {show} {episode}\n")


def _hand_over(store, data_dir, order, series, show, episode, language, **record):
    """One episode as hato and the disk sync meet it: the sync's row first (`sync_first`: the window's watch saw the
    copy before hato's `register`), or hato's hand-off alone. -> the item id."""
    path = _drop(data_dir, series, show, episode)
    if order == "sync_first":
        assert store.sync_disk()["added"], "the sync made its row for hato's copy"
    store.register(path, _record(language, record.pop("title", show), episode, **record))
    rel = ls.library_rel(data_dir, path)
    return store.conn.execute("SELECT id FROM items WHERE rel_key = ?", (ls.path_key(rel),)).fetchone()[0]


def _work(store, item_id):
    return store.item(item_id)["work_id"]


def _titles(store):
    return {w: (t, json.loads(ts or "[]"), fk) for w, t, ts, fk in
            store.conn.execute("SELECT id, title, titles, folder_key FROM works")}


def _no_hato_titles(store):
    """No title named by hato's folder (`Hato/<series>`), none keyed by it."""
    hato = ls.path_key("Hato") + "/"
    return [(w, t, fk) for w, (t, _ts, fk) in _titles(store).items()
            if t.startswith("Hato/") or (fk or "").startswith(hato)]


def test_a_hato_series_folder_has_its_shows_own_folder_key():
    """`HighPriority/Hato/<series>/x` is keyed as `<series>` (down to the series folder only), the same key as the
    learner's `Library/<series>` and a tier's `<series>` folder; a file directly in hato's folder stays loose (titled by
    its record); a learner's own `Hato` folder in another tier is his show folder, as before."""
    for language in LANGUAGES:
        show = names(language)[90]
        key = ls.path_key(show)
        assert ls.folder_key_of(f"{ls.HATO_FOLDER}/{show}/{show} - 05.srt") == key
        assert ls.folder_key_of(f"{ls.HATO_FOLDER}/{show}/extra/{show} - 05.srt") == key
        assert ls.folder_key_of(f"{ls.CONTENT_FOLDER}/{show}/{show} - 01.srt") == key
        assert ls.folder_key_of(f"HighPriority/{show}/{show} - 01.srt") == key
        assert ls.folder_key_of(f"{ls.HATO_FOLDER}/{show} - 05.srt") is None
        assert ls.folder_key_of(f"./{ls.HATO_FOLDER}/{show}/{show} - 05.srt") == key
        assert ls.folder_key_of(f"LowPriority/Hato/{show}/{show} - 01.srt") == ls.path_key(f"Hato/{show}")
        assert ls._below_tier(f"{ls.HATO_FOLDER}/{show}/{show} - 05.srt") == show


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("order", ORDERS)
def test_hatos_episodes_of_a_show_already_in_the_library_join_it_in_either_order(language, order):
    """The report's case: `Library/<show>` holds episodes 1–4; hato drops 5, 6 and 7 into `Hato/<show>/`. Each joins
    the show's one title — whether the disk sync's row came first or hato's hand-off — and the show takes the record's
    AniList id (so it never pulls the next episode elsewhere). No title named or keyed by hato's folder."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    show = names(language)[90]
    title = _show(store, data_dir, show)
    items = [_hand_over(store, data_dir, order, show, show, e, language) for e in (5, 6, 7)]
    assert [_work(store, i) for i in items] == [title] * 3
    assert _no_hato_titles(store) == []
    assert store.conn.execute("SELECT anilist_id FROM works WHERE id = ?", (title,)).fetchone()[0] == ANILIST
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("order", ORDERS)
def test_a_series_folder_named_otherwise_joins_the_show_its_record_names(language, order):
    """hato's series folder is jimaku's entry name, which may differ from the learner's folder: the record's show
    decides. With the sync first, its row's title (made by the folder alone) gives the episode to the record's show at
    hato's hand-off and is left empty; the next episode does the same. Nothing keyed by hato's folder stays in use."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    w = names(language)
    show, series = w[90], w[91]
    title = _show(store, data_dir, show)
    items = [_hand_over(store, data_dir, order, series, show, e, language) for e in (5, 6)]
    assert [_work(store, i) for i in items] == [title, title]
    assert _no_hato_titles(store) == []
    held = {w for (w,) in store.conn.execute("SELECT DISTINCT work_id FROM items")}
    assert [t for wid, (t, _ts, _fk) in _titles(store).items() if wid in held and t == series] == []
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("order", ORDERS)
def test_the_records_show_wins_over_the_folders_name_in_both_orders(language, order):
    """The record names its title first (K81): a series folder named like one of the learner's shows while the record's
    AniList id is another title's — the episode is that title's whether hato or the disk sync came first (the sync's
    row leaves the folder's title at the hand-off), and the folder's show keeps its own files."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    w = names(language)
    named, meant = w[90], w[91]
    folders = _show(store, data_dir, named)
    record_s = _show(store, data_dir, meant)
    with store._writing():
        store.conn.execute("UPDATE works SET anilist_id = ? WHERE id = ?", (ANILIST, record_s))
    item = _hand_over(store, data_dir, order, named, named, 5, language)
    assert _work(store, item) == record_s
    assert store.conn.execute("SELECT COUNT(*) FROM items WHERE work_id = ?", (folders,)).fetchone()[0] == 4
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_named_apart_only_by_punctuation_is_the_same_show(language):
    """`<show>!` from hato beside the learner's `<show>` (`episode_names.show_key`, a8: one show): hato's first episode
    joins it, as a new show folder of that name would."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    show = names(language)[90]
    title = _show(store, data_dir, show)
    item = _hand_over(store, data_dir, "handoff_first", f"{show}!", show, 5, language, title=f"{show}!")
    assert _work(store, item) == title
    assert _no_hato_titles(store) == []
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("order", ORDERS)
def test_a_show_new_to_the_library_is_one_title_named_by_its_show(language, order):
    """A show the learner doesn't have yet: hato's episodes are one title, named by the record's show (never
    "Hato/<series>"); the series folder's own name is kept among its titles when it differs (search finds it)."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    w = names(language)
    show, series = w[92], w[93]
    first, second = (_hand_over(store, data_dir, order, series, show, e, language) for e in (1, 2))
    assert _work(store, first) == _work(store, second)
    name, others, key = _titles(store)[_work(store, first)]
    assert key == ls.path_key(series) and "/" not in name
    assert name in (show, series) and (name == show or order == "sync_first")
    assert _no_hato_titles(store) == []
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_file_directly_in_hatos_folder_is_still_titled_by_its_record(language):
    """The flat drop (hato before 1.1, a pick) keeps its rule: loose, its record's show finds the learner's show."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    show = names(language)[90]
    title = _show(store, data_dir, show)
    path = touch(data_dir, f"{ls.HATO_FOLDER}/{show} - 05.srt", f"{show} 5\n")
    store.register(path, _record(language, show, 5))
    item = store.conn.execute("SELECT id FROM items WHERE rel_key = ?",
                              (ls.path_key(ls.library_rel(data_dir, path)),)).fetchone()[0]
    assert _work(store, item) == title
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_the_learner_named_keeps_its_episode(language):
    """The sync's title for hato's folder, renamed by the learner before hato's hand-off, is his: the episode stays."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    w = names(language)
    show, series = w[90], w[91]
    _show(store, data_dir, show)
    path = _drop(data_dir, series, show, 5)
    item = store.sync_disk()["added"][0]
    mine = _work(store, item)
    store.rename_work(mine, w[94])
    store.register(path, _record(language, show, 5))
    assert _work(store, item) == mine
    store.close()


# --------------------------------------------------------------------------- #
# The one-time rejoin of titles the old rule made (Sonic ruled: by itself; one Undo)
# --------------------------------------------------------------------------- #
def _old_rule(store, data_dir, monkeypatch, language, series, show, episodes, anilist=ANILIST):
    """3.0.16's library: hato's episodes dropped into `Hato/<series>/` and found by the disk sync first, read by the old
    rule (hato's folder only a loose drop's: `Hato/<series>` a show folder of its own) — one title "Hato/<series>"
    holding the record's AniList id. The helper's mark taken off (the test library's own run set it). -> the items."""
    items = []
    with monkeypatch.context() as patched:
        patched.setattr(ls, "HATO_FOLDER", "\0no folder")
        for e in episodes:
            path = touch(data_dir, f"HighPriority/Hato/{series}/[SubsPlease] {show} - {e:02d} (1080p).srt",
                         f"{series} {show} {e}\n")
            items.append(store.sync_disk()["added"][0])
            store.register(path, _record(language, show, e, anilist=anilist))
    with store._writing():
        store.conn.execute("DELETE FROM meta WHERE key = ?", (ls.HATO_FOLDERS_JOINED,))
    old = {_work(store, i) for i in items}
    assert len(old) == 1 and _titles(store)[old.pop()][0] == f"Hato/{series}", "the report's state"
    return items


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_old_rules_hato_title_joins_its_show_once_and_one_undo_brings_it_back(language, monkeypatch):
    """Sonic's library: "Hato/<show>" (Ep 5–7, the AniList id) beside the show (Ep 1–4). The helper's one-time pass
    joins it into the show: every episode the show's, the id with it, the path name gone from its names, the show's
    own name kept. It runs once (a mark); its one Undo puts the old title back as it was."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    show = names(language)[90]
    title = _show(store, data_dir, show)
    items = _old_rule(store, data_dir, monkeypatch, language, show, show, (5, 6, 7))
    old = _work(store, items[0])
    change = store.join_hato_folders()
    assert change is not None
    assert [_work(store, i) for i in items] == [title] * 3
    name, others, _key = _titles(store)[title]
    assert name == show and not [t for t in others if t.startswith("Hato/")]
    assert store.conn.execute("SELECT anilist_id FROM works WHERE id = ?", (title,)).fetchone()[0] == ANILIST
    assert _no_hato_titles(store) == [] and pieces_ok(store) is None
    assert store.join_hato_folders() is None, "once"
    later = _hand_over(store, data_dir, "handoff_first", show, show, 8, language)
    assert _work(store, later) == title, "the next episode follows the show"
    store.undo(change)
    assert [_work(store, i) for i in items] == [old] * 3
    assert _titles(store)[old][0] == f"Hato/{show}"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_rejoin_leaves_the_learners_own_answers_alone(language, monkeypatch):
    """Never a title the learner renamed, nor two titles the AniList ids say are two shows (that one only loses the
    "Hato/" path from its name: its show's, keyed by no folder — the series folder's key is the other show's), nor one
    he kept apart from the show (it stays exactly as it is: a rename would give both one name); one
    with no show to join is renamed by its show and keyed by its series' folder; a learner's own `Hato` show folder in
    another tier (not hato's drop folder) is untouched."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    w = names(language)
    named, apart, alone = w[90], w[91], w[92]
    _show(store, data_dir, named)
    other = _show(store, data_dir, apart)
    with store._writing():
        store.conn.execute("UPDATE works SET anilist_id = ? WHERE id = ?", (ANILIST + 1, other))
    renamed = _work(store, _old_rule(store, data_dir, monkeypatch, language, named, named, (5,))[0])
    store.rename_work(renamed, w[95])
    kept = _work(store, _old_rule(store, data_dir, monkeypatch, language, apart, apart, (5,), anilist=ANILIST + 2)[0])
    lone = _work(store, _old_rule(store, data_dir, monkeypatch, language, alone, alone, (1,), anilist=ANILIST + 3)[0])
    split = _show(store, data_dir, w[97])
    his_answer = _work(store, _old_rule(store, data_dir, monkeypatch, language, w[97], w[97], (5,),
                                        anilist=ANILIST + 4)[0])
    store.keep_apart([split, his_answer])
    his = store.item(store.insert([touch(data_dir, f"LowPriority/Hato/{w[96]}/{w[96]} - 01.srt")], "goal").added[0])
    his_title = _titles(store)[his["work_id"]]
    store.join_hato_folders()
    titles = _titles(store)
    assert titles[renamed][0] == w[95]
    assert kept != other and titles[kept][0] == apart and titles[kept][2] is None, "two AniList ids: two shows"
    assert titles[lone][0] == alone and titles[lone][2] == ls.path_key(alone)
    assert titles[his["work_id"]] == his_title
    assert titles[his_answer][0] == f"Hato/{w[97]}", "kept apart by him: as it stands, never renamed to the show's name"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_helpers_run_rejoins_them(language, monkeypatch):
    """The rejoin is the helper's (`maintain`, after the other one-time joins): his library gets it at its first run."""
    store = _arrivals_on(migrated(language))
    data_dir, user_files_dir = roots(language)
    show = names(language)[90]
    title = _show(store, data_dir, show)
    items = _old_rule(store, data_dir, monkeypatch, language, show, show, (5, 6))
    store.close()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert [_work(store, i) for i in items] == [title, title]
    assert store.meta().get(ls.HATO_FOLDERS_JOINED)
    store.close()


# --------------------------------------------------------------------------- #
# HATO-VIDEO-SHOW (a Send report of 2026-11-27): hato hands over an episode with no show — it joins the title whose
# videos sit beside its video
# --------------------------------------------------------------------------- #
# The report's shape, never its names: the learner's show is a source folder on a share, `<show> (year) [tvdbid-n]/
# Season 02/`, its subtitles copied into `Library/` with origin records naming each episode's video in that folder.
# hato couldn't match the show, so it named its series folder after the video's parent folder (`Season 02`) and sent a
# record with no `show` and no ids. Before the fix that drop became a title of its own, "Season 02" — and any other
# show's unmatched episode in a `Season 02` folder landed in the same false title. What a wrong answer costs: one show
# in two rows (Connect mining two titles), or two shows in one.
SEASON = "Season 02"


def _share(name="share"):
    """The share the learner's shows come from: a folder beside the test's data folder (another "drive")."""
    path = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", name)
    os.makedirs(path, exist_ok=True)
    return path


def _folder(show, n=0):
    return f"{show} ({2021 + n}) [tvdbid-{388200 + n}]"


def _episode_name(language, show, episode, n=0):
    w = names(language)
    return f"{show} ({2021 + n}) - S02E{episode:02d} - {w[100 + episode]} [WEBDL-1080p][AAC 2.0][x264]-WF.{language}"


def _season_show(store, data_dir, share, language, show, episodes, n=0, season=SEASON):
    """The learner's own show, as a source's look takes it in: each subtitle beside its video on the share, its copy
    in `Library/<folder>/<season>/`, its origin record naming the video. -> its title."""
    root = store.add_source(share)
    found = []
    for e in episodes:
        name = _episode_name(language, show, e, n)
        origin = os.path.join(share, _folder(show, n), season, name + ".srt")
        os.makedirs(os.path.dirname(origin), exist_ok=True)
        text = f"{names(language)[110 + e]}{show} {e}\n"
        with open(origin, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        rel = f"{ls.CONTENT_FOLDER}/{_folder(show, n)}/{season}/{name}.srt"
        touch(data_dir, rel, text)
        st = os.stat(origin)
        found.append({"origin": origin, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                      "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "show": _folder(show, n), "rel": rel,
                      "video_path": os.path.join(share, _folder(show, n), season, name + ".mkv"),
                      "video_size": 1300000000 + e})
    added = store.take_in(root, found).added
    works = {_work(store, i) for i in added}
    assert len(works) == 1, "one show, one title"
    return works.pop()


def _unmatched(language, share, show, episode, n=0, season=SEASON):
    """hato's record when it couldn't match the show (an unresolved run, or a person's pick): no `show`, no AniList /
    TMDB id; the video in the show's season folder, written with forward slashes (hato's own spelling)."""
    name = _episode_name(language, show, episode, n)
    video = os.path.join(share, _folder(show, n), season, name + ".mkv").replace("\\", "/")
    key = "v1-" + hashlib.sha256(f"{video}|{episode}".encode("utf-8")).hexdigest()[:32]
    return {"schema": 1, "content_key": key, "producer": "hato", "producer_version": "1.5.0", "language": language,
            "video_path": video, "video_size": 1300000000 + episode, "verdict": "timed"}


def _season_drop(store, data_dir, order, language, share, show, episode, n=0, season=SEASON):
    """hato's copy in `HighPriority/Hato/<season>/` (its series folder named after the video's parent), met in either
    order (the sync's row first, or the hand-off alone). -> the item id."""
    path = touch(data_dir, f"{ls.HATO_FOLDER}/{season}/{_episode_name(language, show, episode, n)}.srt",
                 f"{names(language)[120 + episode]}{show} {episode}\n")
    if order == "sync_first":
        assert store.sync_disk()["added"], "the sync made its row for hato's copy"
    store.register(path, _unmatched(language, share, show, episode, n, season))
    rel = ls.library_rel(data_dir, path)
    return store.conn.execute("SELECT id FROM items WHERE rel_key = ?", (ls.path_key(rel),)).fetchone()[0]


def _season_titles(store, season=SEASON):
    """Titles holding an item and named by hato's season folder alone."""
    held = {w for (w,) in store.conn.execute("SELECT DISTINCT work_id FROM items")}
    return [t for wid, (t, _ts, _fk) in _titles(store).items() if wid in held and t == ls.folder_title(season)]


def _count(store, work):
    return store.conn.execute("SELECT COUNT(*) FROM items WHERE work_id = ?", (work,)).fetchone()[0]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("order", ORDERS)
def test_an_unmatched_episode_joins_the_show_whose_videos_sit_beside_its_video(language, order):
    """The report's case: the show holds E05 and E06, their videos in `<share>/<show>/Season 02/`; hato hands over E07
    from `HighPriority/Hato/Season 02/` with no show and no id, its video in that same folder. The episode is the
    show's — never a title "Season 02" — whether the disk sync saw the copy first or not; the hand-off alone makes no
    stray title at the insert; the show's own names gain nothing of hato's folder."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    share = _share()
    show = names(language)[90]
    title = _season_show(store, data_dir, share, language, show, (5, 6))
    before = _titles(store)[title]
    item = _season_drop(store, data_dir, order, language, share, show, 7)
    assert _work(store, item) == title
    assert _season_titles(store) == []
    if order == "handoff_first":
        assert [t for t, _ts, _fk in _titles(store).values() if t == ls.folder_title(SEASON)] == [], "none made"
    assert _titles(store)[title] == before
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("order", ORDERS)
def test_two_shows_unmatched_episodes_in_one_season_folder_each_join_their_own_show(language, order):
    """Two shows hato couldn't match, both dropped into `HighPriority/Hato/Season 02/` (one folder key): each episode
    joins the show its video sits beside — never one title for both."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    share = _share()
    w = names(language)
    first = _season_show(store, data_dir, share, language, w[90], (5, 6), n=0)
    second = _season_show(store, data_dir, share, language, w[91], (1, 2), n=1)
    a = _season_drop(store, data_dir, order, language, share, w[90], 7, n=0)
    b = _season_drop(store, data_dir, order, language, share, w[91], 3, n=1)
    assert (_work(store, a), _work(store, b)) == (first, second)
    assert _season_titles(store) == []
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("order", ORDERS)
def test_an_unmatched_episode_with_no_show_beside_its_video_keeps_todays_title(language, order):
    """Unchanged: no title has videos in that folder (a show new to the library) — the episode is a title of its own,
    named by hato's folder as today, and the next episode of it joins that title."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    share = _share()
    show = names(language)[92]
    one = _season_drop(store, data_dir, order, language, share, show, 1)
    two = _season_drop(store, data_dir, order, language, share, show, 2)
    assert _work(store, one) == _work(store, two)
    assert _titles(store)[_work(store, one)][0] == ls.folder_title(SEASON)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("order", ORDERS)
def test_a_new_shows_unmatched_episode_never_follows_the_show_beside_it_in_hatos_folder(language, order):
    """hato's `Season 02` folder already holds one show's episode, now that show's; a show new to the library drops its
    unmatched episode into the same folder. The files beside it in hato's folder are no evidence (one folder, several
    shows): it is a title of its own, never the first show's."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    share = _share()
    w = names(language)
    known = _season_show(store, data_dir, share, language, w[90], (5, 6))
    joined = _season_drop(store, data_dir, order, language, share, w[90], 7)
    new = _season_drop(store, data_dir, order, language, share, w[92], 1, n=2)
    assert _work(store, joined) == known
    assert _work(store, new) != known and _count(store, known) == 3
    assert _titles(store)[_work(store, new)][0] == ls.folder_title(SEASON)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_titles_beside_its_video_are_the_learners_split_and_none_takes_it(language):
    """The learner split the show's folder into two titles (*Not part of this title*): with two titles holding videos
    there, the drop joins neither — today's title, and *Join with…* is the learner's."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    share = _share()
    w = names(language)
    show = w[90]
    title = _season_show(store, data_dir, share, language, show, (5, 6))
    six = store.conn.execute("SELECT id FROM items WHERE work_id = ? ORDER BY id DESC LIMIT 1", (title,)).fetchone()[0]
    store.split_work([six], w[96])
    item = _season_drop(store, data_dir, "handoff_first", language, share, show, 7)
    assert _work(store, item) not in (title, _work(store, six))
    assert _titles(store)[_work(store, item)][0] == ls.folder_title(SEASON)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("order", ORDERS)
def test_a_title_holding_hatos_folder_key_and_another_id_keeps_its_episode_in_both_orders(language, order):
    """hato's series folder is named like one of the learner's shows (its folder key) and that show carries an AniList
    id; the videos beside the drop's video are another show's, with another id. Two ids say two shows: the drop
    stays with the folder's show whichever order hato and the disk sync meet in (never crossed by the video)."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    share = _share()
    w = names(language)
    beside = _season_show(store, data_dir, share, language, w[90], (5, 6))
    folders = _show(store, data_dir, w[91])
    with store._writing():
        store.conn.execute("UPDATE works SET anilist_id = ? WHERE id = ?", (ANILIST, folders))
        store.conn.execute("UPDATE works SET anilist_id = ? WHERE id = ?", (ANILIST + 1, beside))
    path = touch(data_dir, f"{ls.HATO_FOLDER}/{w[91]}/{_episode_name(language, w[90], 7)}.srt", f"{w[91]} 7\n")
    if order == "sync_first":
        assert store.sync_disk()["added"]
    store.register(path, _unmatched(language, share, w[90], 7))
    item = store.conn.execute("SELECT id FROM items WHERE rel_key = ?",
                              (ls.path_key(ls.library_rel(data_dir, path)),)).fetchone()[0]
    assert _work(store, item) == folders
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_record_that_names_its_show_still_decides_by_its_show(language):
    """The record's own show comes first (K81): hato's record naming another of the learner's shows lands there, even
    with its video beside this show's videos."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    share = _share()
    w = names(language)
    beside = _season_show(store, data_dir, share, language, w[90], (5, 6))
    named = _show(store, data_dir, w[91])
    path = touch(data_dir, f"{ls.HATO_FOLDER}/{w[91]}/{_episode_name(language, w[90], 7)}.srt", f"{w[91]} 7\n")
    record = _unmatched(language, share, w[90], 7)
    record["show"] = {"title": w[91], "season": 1, "episode": 7, "movie": False}
    store.register(path, record)
    item = store.conn.execute("SELECT id FROM items WHERE rel_key = ?",
                              (ls.path_key(ls.library_rel(data_dir, path)),)).fetchone()[0]
    assert _work(store, item) == named != beside
    store.close()


# --- the one-time heal of titles 3.0.20 already split this way (Sonic ruled: the titles already split heal by
# themselves; a heal is a title change with its Undo, never a file moved)
def _heal_mark(store):
    with store._writing():
        store.conn.execute("DELETE FROM meta WHERE key = ?", (getattr(ls, "HATO_VIDEO_JOINED", "hato_video_joined"),))


def _split_before_the_fix(store, data_dir, language, share, show, episodes, monkeypatch, n=0, season=SEASON):
    """3.0.20's library: hato's unmatched episodes in a title "<season>" of their own beside the show (the video
    folder's rule off), the heal's mark taken off (the test library's own run set it). -> the items."""
    with monkeypatch.context() as patched:
        patched.setattr(ls.Store, "_video_folder_work", lambda *a, **k: None, raising=False)
        items = [_season_drop(store, data_dir, "handoff_first", language, share, show, e, n, season)
                 for e in episodes]
    _heal_mark(store)
    split = {_work(store, i) for i in items}
    assert len(split) == 1 and _titles(store)[next(iter(split))][0] == ls.folder_title(season), "the report's state"
    return items


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_season_title_already_split_off_joins_its_show_once_and_one_undo_brings_it_back(language, monkeypatch):
    """The report's library: "Season 02" (hato's E07) beside the show (E05, E06). The helper's one-time pass gives the
    episode to the show — its name and names unchanged (nothing of "Season 02" added), no file moved, no place
    changed; it runs once (a mark), the next unmatched episode joins the show by itself, and its one Undo puts the
    old title back as it was."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    share = _share()
    show = names(language)[90]
    title = _season_show(store, data_dir, share, language, show, (5, 6))
    before = _titles(store)[title]
    items = _split_before_the_fix(store, data_dir, language, share, show, (7,), monkeypatch)
    old = _work(store, items[0])
    rels = {i: store.item(i)["rel_path"] for i in items}
    places = store.conn.execute("SELECT id, tier, ord FROM items ORDER BY id").fetchall()
    change = store.join_hato_by_video()
    assert change is not None
    assert [_work(store, i) for i in items] == [title]
    assert _titles(store)[title] == before
    assert {i: store.item(i)["rel_path"] for i in items} == rels
    assert os.path.isfile(os.path.join(data_dir, *rels[items[0]].split("/"))), "the store never moves a file"
    assert store.conn.execute("SELECT id, tier, ord FROM items ORDER BY id").fetchall() == places
    assert _season_titles(store) == [] and pieces_ok(store) is None
    assert store.join_hato_by_video() is None, "once"
    later = _season_drop(store, data_dir, "sync_first", language, share, show, 8)
    assert _work(store, later) == title, "the next episode follows the show"
    store.undo(change)
    assert [_work(store, i) for i in items] == [old]
    assert _titles(store)[old][0] == ls.folder_title(SEASON)
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_heal_leaves_the_learners_answers_and_two_shows_alone(language, monkeypatch):
    """Never a split title the learner named or gave his cover, one he kept apart from the show, nor one holding two
    shows' episodes (its videos sit beside two titles: *Join with…* stays his); a split title of one show beside them
    heals. Each case
    in its own season folder (hato's drops of one season folder are one folder key)."""
    store = _arrivals_on(migrated(language))
    data_dir, _u = roots(language)
    w = names(language)
    shares = [_share(f"share{n}") for n in range(6)]
    seasons = ["Season 02", "Season 03", "Season 04", "Season 04", "Season 05", "Season 06"]
    shows = [_season_show(store, data_dir, shares[n], language, w[90 + n], (5, 6), n=n, season=seasons[n])
             for n in range(6)]

    def split(n):
        items = _split_before_the_fix(store, data_dir, language, shares[n], w[90 + n], (7,), monkeypatch, n=n,
                                      season=seasons[n])
        return _work(store, items[0])
    named = split(0)
    store.rename_work(named, w[98])
    apart = split(1)
    store.keep_apart([apart, shows[1]])
    mixed = split(2)
    with monkeypatch.context() as patched:                   # the other show's drop in the same `Season 04` folder
        patched.setattr(ls.Store, "_video_folder_work", lambda *a, **k: None, raising=False)
        extra = _season_drop(store, data_dir, "handoff_first", language, shares[3], w[93], 7, n=3, season=seasons[3])
    assert _work(store, extra) == mixed, "two shows' drops in one title"
    healed = split(4)
    covered = split(5)
    with store._writing():                                   # his own cover on it
        store.conn.execute("UPDATE works SET cover_source = 'user' WHERE id = ?", (covered,))
    _heal_mark(store)
    assert store.join_hato_by_video() is not None
    titles = _titles(store)
    assert titles[named][0] == w[98] and _count(store, named) == 1, "his name: his title"
    assert _count(store, apart) == 1 and _count(store, shows[1]) == 2, "kept apart by him"
    assert _count(store, mixed) == 2, "two shows' episodes: as it stands"
    assert _count(store, healed) == 0 and _count(store, shows[4]) == 3, "the one beside them heals"
    assert _count(store, covered) == 1, "his cover: his title"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_helpers_run_heals_them(language, monkeypatch):
    """The heal is the helper's (`maintain`, after the other one-time joins): his library gets it at its first run."""
    store = _arrivals_on(migrated(language))
    data_dir, user_files_dir = roots(language)
    share = _share()
    show = names(language)[90]
    title = _season_show(store, data_dir, share, language, show, (5, 6))
    items = _split_before_the_fix(store, data_dir, language, share, show, (7,), monkeypatch)
    store.close()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert [_work(store, i) for i in items] == [title]
    assert store.meta().get(ls.HATO_VIDEO_JOINED)
    store.close()

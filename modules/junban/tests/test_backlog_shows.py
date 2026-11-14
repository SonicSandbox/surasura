# SPDX-License-Identifier: GPL-3.0-or-later
"""The shows behind the backlog (A, Michi-C 2026-10-29; `tracks/pipeline/work/backlog-shows/scope.md`) and the one
source-name rule it shares with 順's footer and pins (`source_names`).

What a wrong answer costs a learner who arrives with an Anki Miner backlog: a show that IS on his PC said to be missing
(the footer's old misfire, Mattias's note 13), another show's episode taken for his (`show1` for `show10`), a Finished
show pulled back into his list, or 2,300 cards from one show offered as 2,300 things. Real Japanese and Chinese texts
from tests/Test Resources/ in a source folder beside the test's data folder; Anki stood in by its two read calls.
"""
import json
import os
import unicodedata

import pytest

from app import anki_connect
from app import library_store as ls
from modules.junban import backlog_shows as bs
from modules.junban import source_names as sn
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _text, _video, _write  # noqa: F401

SHOW = {"ja": ("月影の旅人", "夜市の灯", "海辺の約束"), "zh": ("月影旅人", "夜市小记", "海边的约定")}


# --- the one source-name rule ------------------------------------------------------------------------------------ #

def test_both_anki_miner_forms_name_the_same_file_and_a_near_name_never_does():
    path = "D:\\Anime\\[SubsPlease] 月影の旅人 (1080p)\\[SubsPlease] 月影の旅人 - 04 (1080p) [2BF87A0D].ja.srt"
    names = sn.names_of(path)
    assert sn.card_key("[SubsPlease] 月影の旅人 - 04 @ 00:01:02") in names                   # before 3.5: bare
    assert sn.card_key("[SubsPlease] 月影の旅人 (1080p) — [SubsPlease] 月影の旅人 - 04 (1080p) @ 0:01:02") in names
    assert sn.card_key("月影の旅人 — 月影の旅人 - 04 @ 00:01:02") in names                    # 3.10: each part cleaned
    assert sn.card_key("月影の旅人 - 04 @ 00:01:02") in names            # the bare name as 3.10 would clean it
    for other in ("月影の旅人 — 月影の旅人 - 40 @ 00:01:02",            # episode 40 is not episode 4
                  "月影の旅人 — 月影の旅人 - 04 特別編 @ 00:01:02",     # a longer label: never a substring
                  "他の番組 — 月影の旅人 - 04 @ 00:01:02"):           # another folder's episode of that name
        assert sn.card_key(other) not in names, other


def test_the_folder_and_the_name_stay_apart_and_a_bare_number_names_nothing():
    assert sn.card_key("Show — 01 @ 00:00:01") == "show/01"
    assert sn.card_key("Show01 @ 00:00:01") not in sn.names_of("Show/01.mkv")
    assert sn.names_of("Show/01.mkv") == {"show/01"}               # `01` alone says no show: no bare name
    assert sn.names_of("", None) == set()


def test_a_card_that_isnt_anki_miners_names_nothing():
    for misc in ("この単語は「旅」の意味です", "月影の旅人 - 04", "", None, " @ 00:01:00", "月影の旅人 @ soon"):
        assert sn.card_key(misc) is None, misc
    assert sn.card_key("月&nbsp;影 &amp; 旅人 — 第1話 @ 00:01:00") == "月影旅人/第1話"       # HTML as Anki stores it
    assert sn.series_of("[SubsPlease] 夜市小记 (1080p) — 夜市小记 - 02 @ 00:01:00") == "夜市小记"
    assert sn.series_of("夜市小记 - 02 @ 00:01:00") is None


# --- Junban-X3 (based on Mattias's #447, 3.0.10): 順's footer named two sources missing that were in his library ---- #
COLORFUL = "カラフル (文春文庫) - 森 絵都"                       # his audiobook's m4b, as its file is named
TRPG = "笑い過ぎて一生忘れられないTRPG"                         # his single YouTube video, as Anki Miner wrote it
ABROAD = "【留学なし】誰から何も言われずに"                       # in his library under another title: still named
AUDIOBOOK = {"ja": ("カラフル", f"//hemma/data/Japanese/Book Sync/カラフル/{COLORFUL}.m4b", f"Audio — {COLORFUL}"),
             "zh": ("活着", "D:/有声书/活着/活着 - 余华.m4b", "Audio — 活着 - 余华")}
SINGLE = {"ja": (f"Library/{TRPG}/{TRPG} [IIqUltT_x0c].srt", TRPG),
          "zh": ("Library/VLOG一个人的旅行纪录片完整版/VLOG一个人的旅行纪录片完整版 [BV1xx411c7mD].srt",
                 "VLOG一个人的旅行纪录片完整版")}


def _audiobook(files, title):
    """An audiobook item's record as the store keeps it (`audiobooks.record`): its files and the titles it carries."""
    return {"audiobook": {"files": list(files), "title": title, "titles": [title]}}


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_audiobooks_cards_name_its_own_file_by_anki_miners_audio_series(language):
    """`Audio — <the file's name>` (Anki Miner's fixed series) names the audiobook whose file it is — read from the
    item's record (`audiobook.files`), never from a file's own folder form; NFKC and full-width forms alike; another
    book of that series names nothing."""
    title, m4b, source = AUDIOBOOK[language]
    names = sn.names_of_record(_audiobook([m4b], title))
    assert sn.card_key(f"{source} @ 0:12:34") in names
    folder, stem = os.path.dirname(m4b), os.path.splitext(os.path.basename(m4b))[0]
    wide = sn.names_of_record(_audiobook([f"{folder}/{stem} ０１.m4b"], title))     # a full-width number: NFKC
    assert sn.card_key(f"{source} 01 @ 0:12:34") in wide and sn.card_key(f"{source} 1 @ 0:12:34") not in wide
    assert sn.card_key("Audio — 他の本 @ 0:12:34") not in names
    tagged = sn.names_of_record(_audiobook([f"{folder}/[朗読] {stem}.m4b"], title))   # 3.10 cleans the leading tag off
    assert sn.card_key(f"{source} @ 0:12:34") in tagged
    assert sn.card_key(f"Audio — [朗読] {stem} @ 0:12:34") in tagged                # 3.5.0 kept it: as written
    assert not any(k.startswith("audio/") for k in sn.names_of(m4b))              # a file's own name: no `Audio`
    assert sn.only_counted(sn.card_key(f"{source} @ 0:12:34"))


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_split_audiobooks_every_file_names_it_but_a_generic_files_name_never_does(language):
    """An audiobook split across files: each file's cards name it. A file whose name doesn't carry its book's title
    (`01`, `Track 01`, `Disc 1 Track 01`) is every audiobook's: it names nothing (a false *in your library* hides a
    missing book; a missed one is only said)."""
    title, m4b, source = AUDIOBOOK[language]
    folder, stem = os.path.dirname(m4b), os.path.splitext(os.path.basename(m4b))[0]
    split = [f"{folder}/{stem} {i:02d}.mp3" for i in (1, 2, 3)]
    names = sn.names_of_record(_audiobook(split, title))
    for i in (1, 2, 3):
        assert sn.card_key(f"{source} {i:02d} @ 0:00:10") in names, i
    assert sn.card_key(f"{source} 04 @ 0:00:10") not in names
    generic = [f"{folder}/{name}.mp3" for name in ("01", "Track 01", "Disc 1 Track 01", "Chapter 01")]
    assert sn.names_of_record(_audiobook(generic, title)) == set()
    assert sn.names_of_record({"audiobook": {"files": [m4b]}}) == set()          # no title known: nothing to carry
    for lone in ("Track 01", "Chapter 1", "audiobook"):     # a one-file book: its tags may give its own name as title
        record = {"audiobook": {"files": [f"{folder}/{lone}.mp3"], "title": lone, "titles": [lone, title]}}
        assert sn.names_of_record(record) == set(), lone


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_single_videos_bare_title_names_its_file_and_a_short_or_generic_name_never_does(language):
    """A single video (`<title>/<title> [id].srt`) has no episode: its bare title names it when the file is its
    folder's own title and the title is long enough to be its own (BARE_TITLE_MIN letters and digits, no special, no
    part). An extra inside a show's folder (`Creditless Opening`) and every short name stay folder forms only."""
    path, title = SINGLE[language]
    assert sn.card_key(f"{title} @ 0:01:02") in sn.names_of(path)
    wide = "".join(chr(ord(c) + 0xFEE0) if c.isascii() and c.isalnum() else c for c in title)     # ＴＲＰＧ, ＶＬＯＧ
    assert wide != title and unicodedata.normalize("NFKC", wide) == title
    assert sn.card_key(f"{wide} @ 0:01:02") in sn.names_of(path)
    assert sn.only_counted(sn.card_key(f"{title} @ 0:01:02"))
    for stem in ("Opening", "Trailer", "Extra", "Part 1", "OVA", "ED", "Creditless Opening", "Behind the Scenes",
                 "Interview with the cast", f"{title} Part 1"):
        assert all("/" in k for k in sn.names_of(f"他の番組/{stem}.ja.srt")), stem
    assert all("/" in k for k in sn.names_of(f"Library/{title} Part 1/{title} Part 1 [IIqUltT_x0c].srt"))  # a part
    for short in ("猫の動画", "Vlog", "旅行"):                                     # its folder's own, but too short
        assert all("/" in k for k in sn.names_of(f"Library/{short}/{short} [IIqUltT_x0c].srt")), short
    assert sn.card_key(f"{ABROAD} @ 0:00:05") not in sn.names_of(path)          # exact keys only: still missing


def test_a_show_and_its_episode_keeps_the_names_it_had():
    """The bare name of a show + an episode is what it was before Junban-X3, key for key."""
    assert sn.names_of("星の旅人/星の旅人 - 05.ja.srt") == {"星の旅人/星の旅人05", "星の旅人/星の旅人05ja", "星の旅人05",
                                                             "星の旅人05ja"}
    assert sn.names_of("夜市小记/夜市小记 - 02.zh.srt") == {"夜市小记/夜市小记02", "夜市小记/夜市小记02zh", "夜市小记02",
                                                         "夜市小记02zh"}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_pin_writes_by_folder_forms_only_never_a_bare_title_or_anki_miners_series(language):
    """Pins write Anki (*Study its cards first*, *Take its new cards out*): `bare=False` gives the folder forms alone —
    no single video's bare title, no `Audio — …`, no `YouTube — …`."""
    from modules.junban import pins
    path, title = SINGLE[language]
    assert sn.card_key(f"{title} @ 0:01:02") not in sn.names_of(path, bare=False)
    assert sn.card_key(f"{title} @ 0:01:02") not in pins.names_of(path)
    audio_title, m4b, _source = AUDIOBOOK[language]
    assert sn.names_of_record(_audiobook([m4b], audio_title), bare=False) == set()
    assert not any(k.startswith("audio/") for k in pins.names_of(m4b))
    assert sn.names_of_record({"media_type": "youtube", "title": title}, bare=False) == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_fetched_videos_record_title_names_it_by_youtube_and_bare(language):
    """The YouTube downloader's record keeps the video's title: `YouTube — <title>` (Anki Miner's fixed series) and the
    bare title name it — only a title long enough to be its own (`Trailer` is every channel's)."""
    _path, title = SINGLE[language]
    names = sn.names_of_record({"producer": "youtube", "media_type": "youtube", "title": title})
    assert sn.card_key(f"YouTube — {title} @ 0:01:02") in names and sn.card_key(f"{title} @ 0:01:02") in names
    assert sn.only_counted(sn.card_key(f"YouTube — {title} @ 0:01:02"))
    for generic in ("Trailer", "Opening", "", None):
        assert sn.names_of_record({"media_type": "youtube", "title": generic}) == set(), generic
    assert sn.names_of_record({"media_type": "anime", "title": title}) == set()  # another record's title: no video's
    assert not sn.only_counted("月影の旅人/月影の旅人04")


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_librarys_audiobook_item_carries_its_files_audio_names_found_by_a_look(language):
    """On a real library: an audiobook split in two MP3s, found by a look under the user's own folder — its item's
    names carry `Audio — <each file's name>` (the record's files, read by `library`); with `bare` False (pins) none."""
    from tests.test_audiobooks import _mp3
    from tests.test_audiobook_items import _settle
    title, m4b, source = AUDIOBOOK[language]
    stem = os.path.splitext(os.path.basename(m4b))[0]
    store, _data_dir = _empty(language)
    src = _drive("books")
    files = [_mp3(os.path.join(src, "Audio", title, f"{stem} {i:02d}.mp3"), seconds=1800,
                  frames={"TALB": title, "TRCK": str(i)}) for i in (1, 2)]
    _settle(*files)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
    [audio] = [i for i in bs.library(language) if any(k.startswith("audio/") for k in i.names)]
    for i in (1, 2):
        assert sn.card_key(f"{source} {i:02d} @ 0:00:10") in audio.names, i
    assert not any(k.startswith("audio/") for i in bs.library(language, bare=False) for k in i.names)


def test_a_key_two_titles_share_names_neither_but_one_titles_two_folders_keep_it():
    names = {1: {"season01/01"}, 2: {"season01/01"}, 3: {"x/1"}, 4: {"x/1"}}
    work = {1: 10, 2: 20, 3: 30, 4: 30}
    assert sn.shared_names(names, work.get) == {"season01/01"}
    assert sn.shared_names(names) == {"season01/01", "x/1"}


# --- the shows, on a real library -------------------------------------------------------------------------------- #

def _misc(source, i):
    return f"{source} @ 00:{i // 60 % 60:02d}:{i % 60:02d}"


def _library(language, first=False):
    """A source folder (the user's own, read where it is): show 1 in a release-named folder with its video, show 2 split
    across two season folders, then one look — `first` as setup's (Current), else a later look (New arrivals)."""
    one, two, _three = SHOW[language]
    store, data_dir = _empty(language)
    src = _drive("anime")
    folder = f"[SubsPlease] {one} (1080p)"
    _write(os.path.join(src, folder, f"[SubsPlease] {one} - 01 (1080p) [ABCD1234].{language}.srt"), _text(language, 1))
    _video(os.path.join(src, folder, f"[SubsPlease] {one} - 01 (1080p) [ABCD1234].mkv"))
    _write(os.path.join(src, two, "1", f"{two} - 01.{language}.srt"), _text(language, 2))
    _write(os.path.join(src, two, "2", f"{two} - 13.{language}.srt"), _text(language, 3))
    with store:
        root = store.add_source(src)
        ids = _look(store, language, root, first=first)["ids"]
    return store, ids


def _again(store):
    """The language's store opened again (a closed one can't be used twice)."""
    return ls.open_store(store.language, store.data_dir, store.user_files_dir)


def _notes(language, many=2300):
    """順's deck's new cards: `many` from show 1 (3.10's form), show 2's from both its folders in both forms, 40 from a
    show not on this PC, and cards with no Anki Miner source (made by hand, a Migaku hint)."""
    one, two, three = SHOW[language]
    notes, n = {}, 1000
    for i in range(many):
        notes[n] = _misc(f"{one} — {one} - 01", i)
        n += 1
    for i in range(30):
        notes[n] = _misc(f"{two} - 01", i)                          # before 3.5: the bare name
        notes[n + 1] = _misc(f"2 — {two} - 13", i)                  # 3.5+: its season folder — its name
        n += 2
    for i in range(40):
        notes[n] = _misc(f"{three} — {three} - 05", i)
        n += 1
    notes[n], notes[n + 1] = "", "この単語は「旅」の意味です"
    return notes


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_backlog_is_three_shows_two_on_this_pc_waiting_in_new_arrivals(language):
    store, ids = _library(language)
    one, two, three = SHOW[language]
    got = bs.look(_notes(language), bs.library(language))
    assert got["cards"] == 2300 + 60 + 40 and got["all"] == 2300 + 60 + 40 + 2
    shows = {s.title: s for s in got["shows"]}
    assert list(shows) == [one, two, three]                         # most cards first; titles as Anki Miner cleans them
    assert shows[one].cards == 2300 and shows[one].state == "waiting" and len(shows[one].ids) == 1
    assert shows[two].cards == 60 and shows[two].state == "waiting" and len(shows[two].ids) == 2     # both folders
    assert shows[three].state == "away" and shows[three].ids == ()
    assert sorted(bs.waiting_ids(bs.offer_record(got))) == sorted(ids)


@pytest.mark.parametrize("language", LANGUAGES)
def test_after_setups_first_look_the_shows_are_in_already_and_nothing_is_offered(language):
    _library(language, first=True)
    got = bs.look(_notes(language), bs.library(language))
    assert [s.state for s in got["shows"]] == ["in", "in", "away"]
    assert bs.waiting_ids(bs.offer_record(got)) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_finished_show_stays_finished_and_add_them_places_the_rest_at_soon_with_one_undo(language):
    store, ids = _library(language)
    one, two, _three = SHOW[language]
    items = {sn.clean(i.title.split("/")[0]): i for i in bs.library(language)}
    with _again(store) as store:
        store.finish([items[one].id])
    got = bs.look(_notes(language), bs.library(language))
    shows = {s.title: s for s in got["shows"]}
    assert shows[one].state == "finished" and shows[one].ids == ()
    record = bs.offer_record(got)
    wanted = bs.waiting_ids(record)
    assert sorted(wanted) == sorted(shows[two].ids) and len(wanted) == 2
    with _again(store) as store:
        change = store.place(wanted, "soon")                       # what *Add them* asks (`needs.give_shows`)
        assert change is not None
        tiers = dict(store.conn.execute("SELECT id, tier FROM items"))
    assert {tiers[i] for i in wanted} <= {"now", "soon"}             # Current, at the Soon line (a short Current: now)
    assert bs.waiting_ids(record, arrivals=[i for i, t in tiers.items() if t == "arrivals"]) == []
    assert [s.state for s in bs.look(_notes(language), bs.library(language))["shows"] if s.title == two] == ["in"]
    with _again(store) as store:
        store.undo(change)
        assert {r[0] for r in store.conn.execute("SELECT tier FROM items WHERE id IN (%s)" %
                                                 ",".join("?" * len(wanted)), wanted)} == {"arrivals"}


def test_empty_states_say_nothing():
    assert bs.look({}, ()) is None                                  # no new cards
    assert bs.look({1: "", 2: "手で作ったカード"}, ()) is None        # no Anki Miner card, no MiscInfo
    got = bs.look({1: "月影の旅人 — 月影の旅人 - 01 @ 00:00:01"}, ())   # no library (JSON mode): all away
    assert [s.state for s in got["shows"]] == ["away"] and bs.offer_record(got)["id"] == ""
    assert bs.offer_record(None) is None and bs.waiting_ids(None) == []


# --- reading Anki: only what changed, never a write ------------------------------------------------------------- #

class _Anki:
    def __init__(self, notes):
        self.notes, self.asked, self.decks = dict(notes), [], []

    def find_notes(self, url, query):
        assert url.startswith("http://127.0.0.1") and "is:new" in query
        self.decks.append(query.split('"')[1])
        return list(self.notes)

    def notes_info(self, url, ids, chunk=250):
        self.asked.append(list(ids))
        return [{"noteId": i, "fields": {"MiscInfo": {"value": self.notes[i], "order": 5}}} for i in ids]


@pytest.fixture
def anki(monkeypatch, tmp_path):
    monkeypatch.setattr("app.path_utils.get_local_data_path", lambda: str(tmp_path / "local"))
    fake = _Anki(_notes("ja", many=50))
    monkeypatch.setattr(anki_connect, "find_notes", fake.find_notes)
    monkeypatch.setattr(anki_connect, "notes_info", fake.notes_info)
    for name in ("invoke", "multi", "sync"):                       # never a write, never anything else
        monkeypatch.setattr(anki_connect, name, lambda *a, **k: pytest.fail(f"Anki asked {name}"))
    return fake


SETTINGS = {"junban_deck": "Mining", "anki_connect_url": "http://127.0.0.1:8765"}


def test_refresh_reads_each_note_once_and_keeps_its_offer(anki):
    _library("ja")
    first = bs.refresh("ja", SETTINGS)
    assert first["cards"] == 50 + 60 + 40 and len(anki.asked) == 1
    assert bs.offer("ja") == first
    assert bs.refresh("ja", SETTINGS) == first and len(anki.asked) == 1       # same notes: no notesInfo, no look
    anki.notes[99999] = "海辺の約束 — 海辺の約束 - 06 @ 00:00:09"
    again = bs.refresh("ja", SETTINGS)
    assert anki.asked[-1] == [99999] and again["cards"] == first["cards"] + 1   # only the new note's fields
    with open(bs.path("ja"), encoding="utf-8") as f:
        assert json.load(f)["deck"] == "Mining"


def test_no_deck_no_anki_or_no_store_is_no_offer_and_no_crash(anki, monkeypatch):
    assert bs.refresh("ja", {}) is None                             # no deck chosen
    assert not os.path.exists(bs.path("ja"))

    def closed(url, query):
        raise anki_connect.AnkiError("Anki isn't open", kind="unreachable")
    monkeypatch.setattr(anki_connect, "find_notes", closed)
    assert bs.refresh("ja", SETTINGS) is None and bs.offer("ja") is None


def test_the_old_bare_form_is_worked_out_only_when_a_card_carries_it(anki, monkeypatch):
    """At 20,000 files the bare name's show rule is most of the time: a deck whose cards all carry Anki Miner 3.5's
    folder form never pays for it, and still finds its shows."""
    _library("ja")
    one = SHOW["ja"][0]
    anki.notes = {n: _misc(f"{one} — {one} - 01", n) for n in range(10)}
    asked = []
    real = bs.library
    monkeypatch.setattr(bs, "library", lambda language, bare=True: (asked.append(bare), real(language, bare))[1])
    got = bs.refresh("ja", SETTINGS)
    assert asked == [False] and [s["state"] for s in got["shows"]] == ["waiting"]
    anki.notes[99] = _misc(f"{SHOW['ja'][1]} - 01", 99)                  # one card of the old form
    got = bs.refresh("ja", SETTINGS)
    assert asked == [False, True] and [s["state"] for s in got["shows"]] == ["waiting", "waiting"]
    assert all("/" in name for item in real("ja", bare=False) for name in item.names)


# --- the offer's rules on their own (mutants B1, B3, B4, B5): items as `library` gives them ------------------------- #
def _item(item_id, tier, work, title, names, text=True):
    return bs.Item(item_id, tier, work, title, frozenset(names), text)


def test_a_video_still_waiting_for_its_subtitle_is_never_offered():
    items = [_item(1, "arrivals", 10, "月影の旅人", {"月影の旅人/月影の旅人01"}, text=False)]
    got = bs.look({1: "月影の旅人 — 月影の旅人 - 01 @ 00:00:01"}, items)
    assert [(s.state, s.ids) for s in got["shows"]] == [("in", ())]


def test_a_show_partly_in_current_and_partly_finished_is_in_and_its_whole_arrived_piece_is_offered():
    items = [_item(1, "now", 10, "夜市小记", {"夜市小记/夜市小记01"}), _item(2, "graduated", 10, "夜市小记", {"夜市小记/夜市小记02"})]
    got = bs.look({1: "夜市小记 — 夜市小记 - 02 @ 00:00:01"}, items)
    assert [(s.state, s.ids) for s in got["shows"]] == [("in", ())]           # counted already: never "finished"
    items = [_item(3, "arrivals", 20, "月影の旅人", {"月影の旅人/月影の旅人01"}),
             _item(4, "arrivals", 20, "月影の旅人", {"月影の旅人/月影の旅人02"}),
             _item(5, "arrivals", 21, "海辺の約束", {"海辺の約束/海辺の約束01"})]
    got = bs.look({1: "月影の旅人 — 月影の旅人 - 01 @ 00:00:01"}, items)
    assert [(s.title, s.ids) for s in got["shows"]] == [("月影の旅人", (3, 4))]   # the show's episode 2 too, never another


def test_a_key_two_titles_share_puts_the_card_with_neither():
    items = [_item(1, "arrivals", 10, "月影の旅人", {"season01/01"}), _item(2, "arrivals", 11, "夜市の灯", {"season01/01"})]
    got = bs.look({1: "Season 01 — 01 @ 00:00:01"}, items)
    assert [(s.state, s.ids) for s in got["shows"]] == [("away", ())]


# --- reading Anki again (mutants B8, B9, B10, B11, B16) ---------------------------------------------------------- #
def test_a_note_gone_from_the_deck_leaves_the_tally_and_the_same_notes_work_nothing_out(anki, monkeypatch):
    _library("ja")
    first = bs.refresh("ja", SETTINGS)
    gone = next(iter(anki.notes))
    del anki.notes[gone]
    after = bs.refresh("ja", SETTINGS)
    assert after["cards"] == first["cards"] - 1 and after["all"] == first["all"] - 1
    monkeypatch.setattr(bs, "library", lambda *a, **k: pytest.fail("the library read again for the same notes"))
    assert bs.refresh("ja", SETTINGS) == after


def test_another_deck_is_read_whole_and_setups_page_deck_wins_over_the_settings(anki):
    _library("ja")
    bs.refresh("ja", SETTINGS)
    reads = len(anki.asked)
    assert bs.refresh("ja", {}, url="http://127.0.0.1:8765", deck="Other") is not None    # the page's deck, unsaved
    assert anki.decks[-1] == "Other" and len(anki.asked) == reads + 1                       # its notes read whole,
    assert len(anki.asked[-1]) == len(anki.notes)                                           # never the last deck's


def test_with_junban_switched_off_nothing_is_read(anki):
    assert bs.refresh("ja", dict(SETTINGS, enable_junban=False)) is None
    assert anki.decks == [] and not os.path.exists(bs.path("ja"))


# --- the review's SHOULD 3, 5, 7, 9 ------------------------------------------------------------------------------ #
def test_cards_of_an_episode_deleted_since_stay_with_their_show_never_a_second_away_one():
    """The review's SHOULD 3: ep 03 watched and deleted, ep 11 still here — one show, never `Sousou` "on this PC" and
    again "not on this PC". Only a folder one title alone owns: `Season 01` of two shows names neither."""
    items = [_item(1, "now", 10, "Frieren", {"葬送のフリーレン/葬送のフリーレン11"})]     # titled otherwise
    notes = {1: "葬送のフリーレン — 葬送のフリーレン - 11 @ 00:00:01", 2: "葬送のフリーレン — 葬送のフリーレン - 03 @ 00:00:02"}
    got = bs.look(notes, items)
    assert [(s.title, s.cards, s.state) for s in got["shows"]] == [("Frieren", 2, "in")]
    items = [_item(1, "now", 10, "月影の旅人", {"season01/01"}), _item(2, "now", 11, "夜市の灯", {"season01/02"})]
    got = bs.look({1: "Season 01 — 05 @ 00:00:01"}, items)
    assert [s.state for s in got["shows"]] == ["away"]


def test_anki_miners_audio_and_youtube_series_are_no_shows():
    """The review's SHOULD 5: an audiobook's cards (`Audio — <file>`) and a fetched video's (`YouTube — <title>`) are
    counted among the deck's cards, never as shows of their own."""
    notes = {1: "Audio — 夜市小记 第一章 @ 00:01:00", 2: "YouTube — 料理動画 @ 00:00:10",
             3: "月影の旅人 — 月影の旅人 - 01 @ 00:00:01"}
    got = bs.look(notes, ())
    assert [s.title for s in got["shows"]] == ["月影の旅人"] and got["cards"] == 1 and got["all"] == 3
    assert bs.look({1: "Audio — 夜市小记 第一章 @ 00:01:00"}, ()) is None


def test_junban_switched_off_or_the_deck_cleared_takes_the_offer_back(anki):
    """The review's SHOULD 7a: an offer kept from before says nothing once 順 is off or no deck is saved."""
    _library("ja")
    assert bs.refresh("ja", SETTINGS)
    assert bs.offer("ja", deck="Mining") is not None and bs.offer("ja", deck="Other") is None
    assert bs.refresh("ja", dict(SETTINGS, enable_junban=False)) is None
    assert bs.offer("ja") is None
    assert bs.refresh("ja", SETTINGS) and bs.refresh("ja", {}) is None and bs.offer("ja") is None


def test_the_same_notes_are_looked_at_again_once_the_library_moved(anki):
    """The review's SHOULD 7c: his anime folder added after the first sync — the same cards, the library moved: the
    offer is worked out again (no new Anki fields read)."""
    store, ids = _library("ja")
    first = bs.refresh("ja", SETTINGS)
    reads = len(anki.asked)
    with _again(store) as again:
        again.place(ids, "soon")
    after = bs.refresh("ja", SETTINGS)
    assert len(anki.asked) == reads and after != first
    assert not bs.waiting_ids(after)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_footers_names_take_the_counted_files_originals_too(language):
    """The review's SHOULD 9: a file the library keeps under another name (a hato copy, a source's copy) still names
    its show by its original and its video, as Anki Miner wrote it."""
    one = SHOW[language][0]
    _library(language, first=True)
    names = bs.counted_names(language, bare=False)
    assert sn.card_key(f"{one} — {one} - 01 @ 00:00:01") in names
    assert bs.counted_names(language, bare=False) is not None

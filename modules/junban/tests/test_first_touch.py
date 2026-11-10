# SPDX-License-Identifier: GPL-3.0-or-later
"""The first-touch backup and "Put Anki back the way it was before Surasura" (FT rows FT.1–FT.3; amendments K1–K14).

What a wrong answer would cost, most first:

  * **The order from before Surasura is kept once and never replaced** — a second run, a second writer racing the
    first, a later version: the file written before the first-ever write is the only record of it. One that parses
    broken is set aside, never deleted; one that can't be read just now refuses the run.
  * **Nothing reaches Anki without its record**: the order file and the journal line are on disk before the run's
    snapshot, each carrying the open profile, and a failure of either refuses the run with nothing written and no
    snapshot left unfinished.
  * **The put-back undoes only Junban's own changes**: a card you studied stays studied, one you suspended stays
    suspended (and one whose tag you took off), a flag you set and a field you edited stay yours, every card Surasura
    made (Connect's) stays as made. Cards added since go after the kept ones, in the order added — Surasura's own after
    yours. Pressed again after a cut, it finishes the job. Another profile open, Anki closed, a review: nothing changes.
  * **A positions-only move after the first is request for request** (no extra read, no disk).

Against the suites' fake collections (real state, real Japanese and Chinese words; never Anki).
"""
import json
import os
import threading
import time

import pytest

from modules.junban import auto, backfill, first_touch, reposition, spaced, undo
from modules.junban.tests.test_auto_actions import _ACTIONS, _OFF_THE_LIST, _auto, _backlog, _ids
from modules.junban.tests.test_backfill import FIELD, LAPIS, MIGAKU, BackfillCollection, _lapis, _Session
from modules.junban.tests.test_backfill import _settings as _fill_settings
from modules.junban.tests.test_reposition import (_JOURNEY, _LIBRARY, FIRST_NOTE, JPDB, UNRANKED, URL,  # noqa: F401
                                                  AnkiRefusal, _card_of, _collection, _patched, _results, _settings,
                                                  _tags_of, priority_rows, ranked_words, real_priority_csv,
                                                  touchup_backlog, write_priority_csv)
from modules.junban.tests.test_spaced_runs import ModCollection, _move_on_the_list

LATER_TAG = "Surasura::later"
CONNECT_TAG = "surasura::connect::job-20261013-1"


class _TagSearches:
    """The tag searches the put-back asks, on top of a fake collection: Surasura's made cards in a deck
    (`deck:"X" is:new "tag:surasura::connect::*"`), older suspends (`"tag:T" is:new is:suspended -"tag:…"`) and the
    notes carrying a tag (`findNotes "tag:T" -"tag:…"`) — Anki's own reading: a tag matches its children too."""

    @staticmethod
    def _has(note, tag):
        names = [str(name).casefold() for name in note.get("tags") or []]
        tag = tag.casefold()
        if tag.endswith("*"):
            return any(name.startswith(tag[:-1]) for name in names)
        return any(name == tag or name.startswith(tag + "::") for name in names)

    def _dispatch(self, action, params):
        query = params.get("query", "")
        if action in ("findNotes", "findCards") and '"tag:' in query:
            self.searches = getattr(self, "searches", []) + [(action, query)]
            tag = query.split('"tag:')[1].split('"')[0]
            deck = query.split('deck:"')[1].split('"')[0] if 'deck:"' in query else None

            def wanted(card):
                note = self.notes[card["note"]]
                return (self._has(note, tag)
                        and not ('-"tag:surasura::connect::*"' in query and self._has(note, "surasura::connect::*"))
                        and (deck is None or card["deckName"] == deck or card["deckName"].startswith(deck + "::"))
                        and ("is:new" not in query or card["type"] == 0)
                        and ("is:suspended" not in query or card["queue"] == -1))
            if action == "findNotes":
                return sorted({card["note"] for card in self.cards.values() if wanted(card)})
            return sorted(c for c, card in self.cards.items() if wanted(card))
        return super()._dispatch(action, params)


class PutBackCollection(_TagSearches, ModCollection):
    """Junban's fake collection (profile DevTest, mod times) with the put-back's tag searches."""


class FillBackCollection(_TagSearches, BackfillCollection):
    """Backfill's fake collection with the put-back's tag searches."""


def _fill_fake(*pairs):
    return FillBackCollection([p[1] for p in pairs], [p[0] for p in pairs], {"Lapis": LAPIS, "Migaku Japanese": MIGAKU})


@pytest.fixture(autouse=True)
def _fresh_cache():
    """The in-process 'covered' answers belong to one test's folder; dropped so a test can stand for a new process."""
    first_touch._COVERED.clear()
    first_touch._STARTED.clear()
    yield
    first_touch._COVERED.clear()
    first_touch._STARTED.clear()


def _order_files(language="ja"):
    return first_touch.orders(language)[0]


def _last(kind=None, language="ja", landed=None):
    lines = [line for line in first_touch.journal(language) if (kind is None or line.get("kind") == kind)
             and (landed is None or (line.get("landed") is True) == landed)]
    return lines[-1] if lines else None


def _note(word, note_id, tags=()):
    return {"noteId": note_id, "modelName": "Lapis", "tags": list(tags),
            "fields": {"Expression": {"value": word, "order": 0}, "Sentence": {"value": f"{word}の話。", "order": 1}}}


# =============================================================================================================== #
# FT.1 — the files
# =============================================================================================================== #
def test_the_order_file_is_created_once_and_a_second_run_never_replaces_it(tmp_path):
    first = first_touch.keep_order("ja", ["TheBank"], "deck", [(1789712080000, 2801), (1789712080001, 2800)],
                                   profile="DevTest")
    assert first and os.path.isfile(first)
    with open(first, encoding="utf-8") as handle:
        kept = handle.read()
    # The same process (the in-memory answer), then a "new process" (cache dropped): neither writes again.
    assert first_touch.keep_order("ja", ["TheBank"], "deck", [(1789712080000, 9999)], profile="DevTest") is None
    first_touch._COVERED.clear()
    assert first_touch.keep_order("ja", ["TheBank"], "deck", [(1789712080000, 9999)], profile="DevTest") is None
    with open(first, encoding="utf-8") as handle:
        assert handle.read() == kept
    data = json.loads(kept)
    assert data["cards"] == [[1789712080000, 2801], [1789712080001, 2800]] and data["profile"] == "DevTest"
    assert data["scope"] == ["TheBank"] and data["mode"] == "deck" and data["earlier"] is False
    assert abs(data["taken_ms"] - time.time() * 1000) < 60_000
    assert [name for name in os.listdir(first_touch.folder("ja")) if name.endswith(".tmp")] == []


def test_coverage_is_per_profile(tmp_path):
    """K1: the same deck name in another Anki profile is another collection — its order is kept on its own."""
    a = first_touch.keep_order("ja", ["TheBank"], "deck", [(1789712080000, 2800)], profile="DevTest")
    b = first_touch.keep_order("ja", ["TheBank"], "deck", [(1789712090000, 10)], profile="Sonic")
    assert a and b and a != b
    assert first_touch.covered("ja", ["TheBank"], "deck", "Sonic")
    assert not first_touch.covered("ja", ["TheBank"], "deck", "User 1")


def test_two_writers_racing_for_one_name_keep_the_first_and_neither_replaces_it(tmp_path):
    path = first_touch.order_path("ja", ["TheBank"], "deck", "DevTest")
    start, made = threading.Barrier(8), []

    def writer(n):
        start.wait()
        if first_touch._create_once(path, {"schema": 1, "writer": n}):
            made.append(n)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(made) == 1, made
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle)["writer"] == made[0]
    assert sorted(os.listdir(first_touch.folder("ja"))) == [os.path.basename(path)]      # no temporary left


def test_without_hard_links_the_create_is_exclusive_and_still_never_replaces(tmp_path, monkeypatch):
    """K13: elsewhere than Windows, `os.link`; a file system without hard links falls back to an O_EXCL create."""
    monkeypatch.setattr(os, "name", "posix")

    def no_links(source, target):
        raise PermissionError("hard links not supported")

    monkeypatch.setattr(os, "link", no_links, raising=False)
    path = first_touch.order_path("ja", ["TheBank"], "deck", "DevTest")
    assert first_touch._create_once(path, {"schema": 1, "writer": "first"}) is True
    assert first_touch._create_once(path, {"schema": 1, "writer": "second"}) is False
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle)["writer"] == "first"


def test_an_order_file_that_parses_broken_is_set_aside_and_its_replacement_says_earlier(tmp_path):
    path = first_touch.order_path("ja", ["TheBank"], "deck", "DevTest")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"schema": 1, "cards": [[17897')                  # cut short by a crash
    assert not first_touch.covered("ja", ["TheBank"], "deck", "DevTest")
    assert first_touch.set_aside("ja") == []                  # C6: a reader moves nothing
    assert first_touch.keep_order("ja", ["TheBank"], "deck", [(1789712080000, 2800)], profile="DevTest") == path
    aside = first_touch.set_aside("ja")
    assert len(aside) == 1
    with open(os.path.join(first_touch.folder("ja"), aside[0]), encoding="utf-8") as handle:
        assert handle.read() == '{"schema": 1, "cards": [[17897'
    assert _order_files()[0]["earlier"] is True               # K10: the order before it is no longer known


def test_an_order_file_that_cant_be_read_just_now_refuses_and_is_never_moved(tmp_path, monkeypatch):
    path = first_touch.keep_order("ja", ["TheBank"], "deck", [(1789712080000, 2800)], profile="DevTest")
    first_touch._COVERED.clear()
    real_open = open

    def held(name, *args, **kwargs):
        if os.path.abspath(str(name)) == os.path.abspath(path):
            raise PermissionError(13, "held by another program")
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr("builtins.open", held)
    with pytest.raises(OSError):         # C7: a run reads only the files named for it — TheBank's own, here
        first_touch.keep_order("ja", ["TheBank"], "deck", [], profile="DevTest")
    monkeypatch.setattr("builtins.open", real_open)
    assert os.path.isfile(path) and first_touch.set_aside("ja") == []
    assert len(_order_files()) == 1


def test_the_journal_appends_one_fsynced_line_per_write_and_a_line_cut_short_never_swallows_the_next(
        tmp_path, monkeypatch):
    synced = []
    real_fsync = os.fsync
    first_touch.started("ja")                 # C13: the record's start, kept once (its own fsync) before any line
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd)))
    first_touch.note("ja", "reorder", "DevTest", ["TheBank"], suspended=[1789712080003],
                     tags={LATER_TAG: [1789712000003]})
    path = os.path.join(first_touch.folder("ja"), first_touch.JOURNAL)
    with open(path, "ab") as handle:
        handle.write(b'{"kind": "reorder", "suspended": [17897')        # a crash mid-line
    first_touch.note("ja", "reorder", "DevTest", ["TheBank"], flags={1789712080004: [0, 7]})
    assert len(synced) == 2
    lines = first_touch.journal("ja")
    assert [line.get("suspended") or line.get("flags") for line in lines] == [[1789712080003],
                                                                              {"1789712080004": [0, 7]}]
    assert all(line["profile"] == "DevTest" and line["deck"] == ["TheBank"] for line in lines)      # K1
    assert first_touch.note("ja", "reorder", "DevTest", ["TheBank"], suspended=[], tags={}) is False
    with pytest.raises(ValueError):
        first_touch.note("ja", "reorder", None, ["TheBank"], suspended=[1])      # never a line without a profile
    assert len(first_touch.journal("ja")) == 2


def test_connects_batch_tags_are_never_journalled(tmp_path):
    """D6: `surasura::connect::<job>` is how *Undo this batch* finds the mined notes — never Surasura's to take off."""
    first_touch.note("ja", "reorder", "DevTest", ["TheBank"],
                     tags={CONNECT_TAG: [1789712000001], "SURASURA::Connect::job-2": [1789712000002],
                           "Surasura": [1789712000003]})
    assert _last()["tags"] == {"Surasura": [1789712000003]}


def test_japanese_and_chinese_keep_their_own_folders_and_cjk_nested_deck_names_make_valid_files(tmp_path):
    ja = first_touch.keep_order("ja", ["日本語::コア 2k"], "deck", [(1789712080000, 2800)], profile="ユーザー 1")
    zh = first_touch.keep_order("zh", ["中文::HSK 3级"], "deck", [(1789712090000, 100)], profile="ユーザー 1")
    assert os.path.dirname(ja) == first_touch.folder("ja") != os.path.dirname(zh) == first_touch.folder("zh")
    assert first_touch.folder("zh").endswith(os.path.join("User Files", "zh", "anki_first_touch"))
    assert ":" not in os.path.basename(ja) and "日本語" in os.path.basename(ja)
    assert first_touch.has_anything("ja") and first_touch.has_anything("zh")
    # Covered: the deck itself; never its parent, a sibling, or the same name in the other language.
    assert first_touch.covered("ja", ["日本語::コア 2k"], "deck", "ユーザー 1")
    assert not first_touch.covered("ja", ["日本語"], "deck", "ユーザー 1")
    assert not first_touch.covered("ja", ["日本語::コア 6k"], "deck", "ユーザー 1")
    assert not first_touch.covered("zh", ["日本語::コア 2k"], "deck", "ユーザー 1")


def test_an_all_decks_file_covers_its_own_decks_and_a_deck_file_never_covers_all_decks(tmp_path):
    first_touch.keep_order("ja", ["TheBank"], "deck", [], profile="DevTest")
    assert not first_touch.covered("ja", ["TheBank", "Kaishi 1.5k"], "all", "DevTest")
    first_touch.keep_order("ja", ["TheBank", "Kaishi 1.5k"], "all", [], profile="DevTest")
    assert first_touch.covered("ja", ["Kaishi 1.5k"], "deck", "DevTest")
    assert first_touch.covered("ja", ["TheBank", "Kaishi 1.5k"], "all", "DevTest")


def test_earlier_is_any_junban_or_backfill_file_in_either_language_at_the_first_touch(tmp_path):
    """D3 / K9 / C13: anything Junban or Backfill kept before the record — the first order kept is then Surasura's;
    a file taken later is never `earlier` (the record kept what Surasura did since)."""
    undo.record_ladder("zh", ["中文::HSK 3级"], floor=2800)           # the other language's spaced ladder, from 2.5
    first_touch.keep_order("ja", ["TheBank"], "deck", [], profile="DevTest")
    first_touch.keep_order("ja", ["Kaishi 1.5k"], "deck", [], profile="DevTest")
    earlier = {tuple(data["scope"]): data["earlier"] for data in _order_files()}
    assert earlier == {("TheBank",): True, ("Kaishi 1.5k",): False}


def test_the_journal_state_undoes_only_suspends_that_landed_and_follows_your_edits():
    lines = [{"fields": {"1": {"Patterns": {"before": "", "after": "<div>A</div>"}}}},
             {"fields": {"1": {"Patterns": {"before": "mine", "after": "<div>B</div>"}}}},     # you edited, then we
             {"fields": {"2": {"Patterns": {"before": "", "after": "<div>C</div>"}}}},
             {"fields": {"2": {"Patterns": {"before": "<div>C</div>", "after": "<div>D</div>"}}}},
             {"suspended": [5, 6, 9]},                                           # the intent
             {"suspended": [5, 6], "landed": True, "with_tag": LATER_TAG},        # 9 never landed
             {"unsuspended": [6]},
             {"flags": {"7": [0, 7]}}, {"flags": {"7": [7, 0]}}, {"flags": {"8": [3, 7]}},
             {"tags": {LATER_TAG: [1, 2]}}, {"tags_off": {LATER_TAG: [2]}}]
    state = first_touch._state(lines)
    assert state["fields"] == {(1, "Patterns"): ["mine", "<div>B</div>"], (2, "Patterns"): ["", "<div>D</div>"]}
    assert state["suspended"] == {5: LATER_TAG}
    assert state["flags"] == {7: [0, 0], 8: [3, 7]}
    assert state["tags"] == {(LATER_TAG, 1)}
    assert state["touched"] == {5, 6, 7, 8, 9}


# =============================================================================================================== #
# FT.2 — the hooks
# =============================================================================================================== #
@pytest.fixture
def deck(ranked_words, write_priority_csv):
    """30 new cards in TheBank: 24 ranked words in the reverse of the list's order, then 6 the list lacks."""
    write_priority_csv()
    words = ranked_words[:24] + UNRANKED
    cards, notes, _ = _collection(words, dues=list(range(2800 + len(words) - 1, 2799, -1)))
    return ModCollection(cards, notes)


def test_the_first_spaced_respace_keeps_the_order_before_it_with_no_extra_request(deck):
    before = {card_id: card["due"] for card_id, card in deck.cards.items()}
    with _patched(deck):
        report = reposition.run(_settings(), job=spaced.Job(cards=reposition.CardMap()))
    assert report["ok"] and report["numbering"]["kind"] == spaced.FULL and len(report["written"]) == 30
    [data] = _order_files()
    assert dict(data["cards"]) == before and data["profile"] == "DevTest" and data["scope"] == ["TheBank"]
    # The profile came from the job's own card map read (inside its `multi`): no request of the first touch's own.
    assert "getActiveProfile" not in deck.action_names


def test_a_positions_only_move_after_the_first_asks_nothing_new_and_reads_no_file(deck, ranked_words,
                                                                                  write_priority_csv, priority_rows,
                                                                                  monkeypatch):
    job = spaced.Job(automatic=True, cards=reposition.CardMap())     # the automatic re-order: positions only
    with _patched(deck):
        assert reposition.run(_settings(), job=job)["ok"]
    assert len(_order_files()) == 1
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, ranked_words[12:16])    # a move in Surasura
    deck.requests.clear()
    monkeypatch.setattr(first_touch, "_read_order", lambda path: pytest.fail("read the order files again"))
    with _patched(deck):
        report = reposition.run(_settings(), job=job)
    assert report["ok"] and report["written"]
    assert "getActiveProfile" not in deck.action_names
    assert first_touch.journal("ja") == []                     # positions only: no journal line


def test_a_manual_run_reads_the_profile_once_per_run_and_keeps_the_order_once(deck):
    """K1: a manual 順 run has no card map: one `getActiveProfile` per writing run (its journal lines carry it)."""
    with _patched(deck):
        assert reposition.run(_settings())["ok"]
    assert deck.action_names.count("getActiveProfile") == 1
    deck.cards[min(deck.cards)]["due"] = 1
    deck.requests.clear()
    first_touch._COVERED.clear()                              # a new process: the file answers
    with _patched(deck):
        assert reposition.run(_settings())["ok"]
    assert deck.action_names.count("getActiveProfile") == 1
    assert len(_order_files()) == 1


def test_an_acting_automatic_job_journals_its_suspends_tags_and_flags_before_its_snapshot_and_what_landed(
        tmp_path, monkeypatch):
    """HY-6: AutoJunban applies the saved actions; each is in the journal before anything reaches Anki, and what
    landed after (K3)."""
    fake = _backlog(tmp_path)
    seen = {}
    real_create = first_touch._create_once
    monkeypatch.setattr(first_touch, "_create_once",
                        lambda path, payload: (seen.setdefault("lines_at_order", list(first_touch.journal("ja"))),
                                               real_create(path, payload))[1])
    with _patched(fake):
        done = auto.reorder(_auto(), list_current=True)
    assert done["outcome"] == "ran", done
    off = _ids(fake, _OFF_THE_LIST)
    intent, landed = _last("reorder", landed=False), _last("reorder", landed=True)
    assert intent["suspended"] == off and intent["profile"] == "DevTest" and intent["deck"] == ["TheBank"]
    assert intent["flags"] == {str(card_id): [0, 7] for card_id in off}
    assert intent["tags"][LATER_TAG] == sorted(_card_of(fake, word)["note"] for word in _OFF_THE_LIST)
    assert landed["suspended"] == off and landed["with_tag"] == LATER_TAG
    assert seen["lines_at_order"] == []                      # the order file first, before any journal line
    [data] = _order_files()
    assert len(data["cards"]) == 6           # every unsuspended new card (洗濯機 is yours, suspended)


def test_a_connect_run_keeps_the_whole_scope_though_its_snapshot_holds_only_what_it_moves(tmp_path):
    from modules.junban.tests.connect_scene import scene
    from modules.junban.tests.connect_scene import settings as connect_settings
    fake = scene(tmp_path)
    new = {card_id: card["due"] for card_id, card in fake.cards.items() if card["queue"] == 0}     # not the parked
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        done = auto.reorder(connect_settings(), list_current=True, positions_only=True, run_id=run_id)
    assert done["outcome"] == "ran" and fake.writes
    assert undo.load("ja", run_id=run_id)["complete"] is True
    [data] = _order_files()
    assert dict(data["cards"]) == new           # every unsuspended new card, whatever the run's own snapshot holds


def test_a_journal_that_cant_be_written_refuses_the_run_with_nothing_written_and_no_snapshot(tmp_path, monkeypatch):
    fake = _backlog(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(first_touch, "note", fail)
    with _patched(fake):
        report = reposition.run(_auto())
    assert not report["ok"] and "disk full" in report["problems"][0]
    assert fake.writes == [] and fake.suspend_calls == [] and fake.tag_calls == [] and fake.flag_writes == []
    assert undo.load("ja") is None and not os.path.exists(undo.snapshot_path("ja"))


def test_an_order_file_that_cant_be_written_refuses_the_run_with_nothing_written(tmp_path, monkeypatch):
    fake = _backlog(tmp_path)

    def fail(path, payload):
        raise OSError("access denied")

    monkeypatch.setattr(first_touch, "_create_once", fail)
    with _patched(fake):
        report = reposition.run(_auto())
    assert not report["ok"] and "access denied" in report["problems"][0]
    assert fake.writes == [] and fake.suspend_calls == [] and undo.load("ja") is None
    assert first_touch.journal("ja") == []


def test_a_restore_journals_what_it_undid_once_it_landed(tmp_path):
    fake = _backlog(tmp_path)
    with _patched(fake):
        assert reposition.run(_auto())["ok"]
        restored = reposition.restore(_auto())
    assert restored["ok"], restored["problems"]
    line = _last("restore")
    off = _ids(fake, _OFF_THE_LIST)
    assert line["unsuspended"] == off and line["profile"] == "DevTest" and line["landed"] is True
    assert line["flags"] == {str(card_id): [7, 0] for card_id in off}
    assert line["tags_off"][LATER_TAG] == sorted(_card_of(fake, word)["note"] for word in _OFF_THE_LIST)
    state = first_touch._state(first_touch.journal("ja"))
    assert state["suspended"] == {} and state["tags"] == set() and all(a == b for a, b in state["flags"].values())


def test_backfill_journals_only_the_fields_it_writes_and_its_restore_journals_them_back(tmp_path):
    """K8: the fill's own edits, at its own call site — never the history its snapshot carries forward."""
    fake = _fill_fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ"))
    undo.save([], ["TheBank"], fields={"1789711000777": {"Patterns": {"before": "", "after": "<div>old</div>"}}},
              kind="backfill")
    undo.mark_complete("ja", kind="backfill")
    with _patched(fake):
        assert backfill.run(_fill_settings(), _Session())["ok"]
    line = _last("backfill")
    assert sorted((change["Patterns"]["before"], change["Patterns"]["after"]) for change in line["fields"].values()) \
        == sorted([("", FIELD["探検"]), ("", FIELD["大切"])])
    assert "1789711000777" not in line["fields"] and "1789711000777" in undo.load("ja", kind="backfill")["fields"]
    with _patched(fake):
        assert backfill.restore(_fill_settings())["ok"]
    back = _last("restore")
    assert sorted(change["Patterns"]["after"] for change in back["fields"].values()) == ["", ""]


def test_undo_save_journals_its_own_keys_never_fields_and_never_a_cut_runs(tmp_path):
    cut = {"cards": {"1789712080009": 2809}, "suspended": [1789712080009], "flags": {"1789712080009": 0}}
    undo.save({1789712080001: 2801}, ["TheBank"], suspended=[1789712080001], flags={1789712080001: 0},
              fields={"1789712000001": {"FreqSort": {"before": "54614", "after": "42"}}},
              automatic=True, cut=cut, profile="DevTest")
    line = _last()
    assert line["suspended"] == [1789712080001] and list(line["flags"]) == ["1789712080001"]
    assert "fields" not in line
    assert undo.load("ja")["suspended"] == [1789712080001, 1789712080009]      # the snapshot still merges both
    undo.save({1789712080001: 2801}, ["TheBank"], suspended=[1789712080002])     # no profile: no line (a test's)
    assert len(first_touch.journal("ja")) == 1


# =============================================================================================================== #
# FT.3 — plan() and put_back()
# =============================================================================================================== #
def _touched(tmp_path):
    """A deck Junban touched: the 順 run with every 'not on your list' action (4 suspended, flagged purple, tagged
    later; the moved notes tagged Surasura), then — afterwards — two cards you added, one Connect made (its batch
    tag), one studied, one flag you set yourself. 洗濯機 you suspended yourself before any of it."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    cards, notes, _ = _collection(["須藤", "散歩", "図書館", "冒険", "美術館", "新幹線", "洗濯機"])
    fake = PutBackCollection(cards, notes, actions=_ACTIONS)
    _card_of(fake, "洗濯機")["queue"] = -1
    original = {card_id: card["due"] for card_id, card in fake.cards.items()}
    with _patched(fake):
        assert reposition.run(_auto())["ok"]
    assert fake.writes
    stamp = int(time.time() * 1000)
    for n, (word, tags) in enumerate((("味噌汁", []), ("鳥取", []), ("眼鏡", [CONNECT_TAG])), 1):
        fake.notes[stamp + 100 + n] = _note(word, stamp + 100 + n, tags)
        fake.cards[stamp + n] = {"cardId": stamp + n, "note": stamp + 100 + n, "due": 9100 - n, "type": 0,
                                 "queue": 0, "deckName": "TheBank", "mod": 1_700_000_000}
    _card_of(fake, "散歩").update(type=2, queue=2, due=20380)
    _card_of(fake, "美術館")["flags"] = 1                     # you flagged it red since
    return fake, original, [stamp + 1, stamp + 2, stamp + 3]


def _surasura_tags(fake, word):
    return [tag for tag in _tags_of(fake, word) if tag.casefold().startswith("surasura") and tag != CONNECT_TAG]


def test_the_put_back_restores_only_junbans_changes_and_puts_added_cards_after_in_the_order_added(tmp_path):
    fake, original, added = _touched(tmp_path)
    with _patched(fake):
        planned = first_touch.plan(_auto())
    assert planned["ok"] and planned["profile"] == "DevTest" and not planned["wrong_profile"]
    assert planned["unsuspend"] == 4 and planned["added_after"] == 2 and planned["flags"] == 3
    assert planned["made_after"] == 1                       # C18: Surasura's made card, never counted as yours
    assert planned["made_left"] == 1 and planned["older_suspended"] == 0 and planned["nothing"] is False
    studied_before = dict(_card_of(fake, "散歩"))
    moved = sum(1 for w in ("須藤", "図書館", "冒険", "美術館", "新幹線")
                if _card_of(fake, w)["due"] != original[_card_of(fake, w)["cardId"]])
    assert moved and planned["cards_back"] == moved
    fake.requests.clear()
    with _patched(fake):
        report = first_touch.put_back(_auto())
    assert report["ok"], report
    for word in ("須藤", "図書館", "冒険", "美術館", "新幹線"):
        card = _card_of(fake, word)
        assert (card["due"], card["queue"]) == (original[card["cardId"]], 0), word
    assert _card_of(fake, "散歩") == studied_before                            # studied: untouched
    assert _card_of(fake, "洗濯機")["queue"] == -1                            # yours: still suspended
    top = max(due for card_id, due in original.items() if card_id != _card_of(fake, "洗濯機")["cardId"])
    # Yours in the order you added them, then the one Surasura made (K5).
    assert [fake.cards[card_id]["due"] for card_id in added] == [top + 1, top + 2, top + 3]
    assert [_card_of(fake, w).get("flags") for w in ("須藤", "図書館", "新幹線", "美術館")] == [0, 0, 0, 1]
    assert all(_surasura_tags(fake, word) == [] for word in ("須藤", "図書館", "冒険", "美術館", "新幹線"))
    assert _tags_of(fake, "眼鏡") == [CONNECT_TAG]                           # D6 / K5: as Connect made it
    assert report["done"]["cards"] == moved and report["done"]["added_after"] == 2
    assert report["done"]["made_after"] == 1
    assert report["done"]["unsuspended"] == 4 and report["done"]["flags"] == 3
    assert "before Surasura" in report["message"] and "1 card Surasura made after yours" in report["message"]
    assert "left as they are" not in report["message"]       # C20: the window's closing line says it, once


def test_junbans_own_changes_come_off_a_card_surasura_made_and_connects_stay(tmp_path):
    """C18 (IK9 / A-N4; K5 as Haya ruled): 須藤's note turns out to be one Connect made (its batch tag). Junban
    suspended, flagged and tagged it — those come off under K3's rules; Connect's batch tag stays (Connect's ledger
    and *Undo this batch* own the card), and the card goes after yours, counted apart."""
    fake, _original, _added = _touched(tmp_path)
    made = _card_of(fake, "須藤")
    fake.notes[made["note"]]["tags"].append(CONNECT_TAG)
    with _patched(fake):
        planned = first_touch.plan(_auto())
        report = first_touch.put_back(_auto())
    assert planned["made_left"] == 2 and planned["unsuspend"] == 4 and planned["made_after"] == 2
    assert report["ok"] and made["queue"] == 0 and made.get("flags") == 0
    assert fake.notes[made["note"]]["tags"] == [CONNECT_TAG]


def test_a_suspend_is_undone_only_while_its_note_still_carries_junbans_tag(tmp_path):
    """K3: you took 須藤's `Surasura::later` off — its suspension may be yours now: it stays."""
    fake, _original, _added = _touched(tmp_path)
    note = fake.notes[_card_of(fake, "須藤")["note"]]
    note["tags"] = [tag for tag in note["tags"] if tag != LATER_TAG]
    with _patched(fake):
        report = first_touch.put_back(_auto())
    assert report["ok"] and report["done"]["unsuspended"] == 3
    assert _card_of(fake, "須藤")["queue"] == -1 and _card_of(fake, "図書館")["queue"] == 0


def test_pressed_again_it_changes_nothing_and_after_a_cut_it_finishes_the_job(tmp_path):
    fake, original, added = _touched(tmp_path)
    fake.fail_write_chunk = fake.write_chunks + 1          # Anki goes away during the first position request
    with _patched(fake):
        cut = first_touch.put_back(_auto(junban_chunk_size=2))
    assert not cut["ok"] and "press it again" in cut["message"]
    with _patched(fake):
        finished = first_touch.put_back(_auto(junban_chunk_size=2))
    assert finished["ok"], finished
    assert _card_of(fake, "須藤")["due"] == original[_card_of(fake, "須藤")["cardId"]]
    top = max(due for card_id, due in original.items() if card_id != _card_of(fake, "洗濯機")["cardId"])
    assert [fake.cards[card_id]["due"] for card_id in added] == [top + 1, top + 2, top + 3]
    fake.requests.clear()
    with _patched(fake):
        again = first_touch.put_back(_auto())
    assert again["ok"] and again["done"] == dict.fromkeys(again["done"], 0)
    # FT.5 (the DevTest drill): with nothing left to do it says so, never "0 new cards back in their order"
    assert again["message"] == "Anki was already as it was before Surasura.", again["message"]
    writes = [r for r in fake.requests if r["action"] in ("suspend", "unsuspend", "removeTags", "addTags")
              or (r["action"] == "multi" and any(a["action"] in ("setSpecificValueOfCard", "updateNoteFields")
                                                 for a in r["params"]["actions"]))]
    assert writes == []


def test_a_suspend_you_made_after_junbans_restore_is_never_undone(tmp_path):
    fake, _original, _added = _touched(tmp_path)
    with _patched(fake):
        assert reposition.restore(_auto())["ok"]
    _card_of(fake, "須藤")["queue"] = -1                     # you suspend it yourself, afterwards
    with _patched(fake):
        assert first_touch.put_back(_auto())["ok"]
    assert _card_of(fake, "須藤")["queue"] == -1


def test_older_suspends_and_tags_are_counted_and_done_only_when_asked(tmp_path):
    """K4: a card Junban suspended and tagged before the record (not in the journal) — offered, default No."""
    fake, _original, _added = _touched(tmp_path)
    stamp = 1789712070000
    fake.notes[stamp + 100] = _note("鳥取", stamp + 100, [LATER_TAG])
    fake.cards[stamp] = {"cardId": stamp, "note": stamp + 100, "due": 2700, "type": 0, "queue": -1,
                         "deckName": "TheBank", "mod": 1_700_000_000}
    with _patched(fake):
        planned = first_touch.plan(_auto())
        assert planned["older_suspended"] == 1 and planned["older_tags"] == 1
        kept = first_touch.put_back(_auto())
        assert fake.cards[stamp]["queue"] == -1 and fake.notes[stamp + 100]["tags"] == [LATER_TAG]
        report = first_touch.put_back(_auto(), older=True)
    assert report["ok"] and kept["ok"]
    assert fake.cards[stamp]["queue"] == 0 and fake.notes[stamp + 100]["tags"] == []


def test_another_profile_open_refuses_and_names_the_one_to_open(tmp_path):
    fake, _original, _added = _touched(tmp_path)
    fake.profile = "Sonic"
    with _patched(fake):
        planned = first_touch.plan(_auto())
        fake.requests.clear()
        report = first_touch.put_back(_auto())
    assert planned["wrong_profile"] == "DevTest" and not planned["ok"]
    assert not report["ok"] and report["wrong_profile"] == "DevTest" and '"DevTest"' in report["message"]
    assert not [r for r in fake.requests if r["action"] in ("multi", "unsuspend", "removeTags")]


def test_anki_closed_refuses_and_says_nothing_was_changed(tmp_path):
    fake, _original, _added = _touched(tmp_path)
    fake.offline = True
    with _patched(fake):
        planned = first_touch.plan(_auto())
        report = first_touch.put_back(_auto())
    assert planned["anki_closed"] and report["anki_closed"]
    assert report["message"] == first_touch.ANKI_CLOSED and not report["ok"]


def test_reviewing_refuses_with_nothing_written_and_a_review_mid_way_stops_the_rest(tmp_path, monkeypatch):
    fake, original, _added = _touched(tmp_path)
    fake.reviewing = True
    fake.requests.clear()
    with _patched(fake):
        report = first_touch.put_back(_auto())
    assert not report["ok"] and report.get("reviewing")
    assert not [r for r in fake.requests if r["action"] in ("multi", "unsuspend", "removeTags")]
    # K14: asked again before each step — a review starting after the unsuspends stops the positions and the rest.
    fake.reviewing = False
    real_unsuspend = fake._suspend

    def then_review(action, card_ids):
        result = real_unsuspend(action, card_ids)
        if action == "unsuspend":
            fake.reviewing = True
        return result

    monkeypatch.setattr(fake, "_suspend", then_review)
    with _patched(fake):
        stopped = first_touch.put_back(_auto())
    assert not stopped["ok"] and stopped["reviewing"] and first_touch.REVIEWING_STOP in stopped["message"]
    assert stopped["done"]["unsuspended"] == 4 and stopped["done"]["cards"] == 0 and stopped["done"]["flags"] == 0
    assert _card_of(fake, "須藤")["due"] != original[_card_of(fake, "須藤")["cardId"]]


def test_nothing_kept_says_so_without_asking_anki(tmp_path):
    fake = ModCollection([], [])
    with _patched(fake):
        planned = first_touch.plan(_settings())
    assert planned["nothing"] and planned["problems"] == [first_touch.NOTHING] and fake.requests == []
    assert not first_touch.has_anything("ja")


def test_the_earliest_file_holding_a_card_wins_by_card_id_and_earlier_says_whose_order_it_was(tmp_path):
    cards, notes, _ = _collection(["須藤", "冒険", "散歩"], dues=[5000, 5001, 5002])
    fake = PutBackCollection(cards, notes)
    ids = sorted(fake.cards)
    for mode, scope, taken_ms, dues, earlier in (("deck", ["TheBank (old name)"], 1_791_000_000_000,
                                                  [2802, 2801, 2800], True),
                                                 ("all", ["Kaishi", "TheBank"], 1_791_000_500_000,
                                                  [3000, 3001, 3002], False)):
        first_touch._create_once(first_touch.order_path("ja", scope, mode, "DevTest"), {
            "schema": 1, "taken_at": "2026-10-01T08:00:00" if earlier else "2026-10-02T08:00:00",
            "taken_ms": taken_ms, "profile": "DevTest", "mode": mode, "scope": scope, "earlier": earlier,
            "cards": [[card_id, due] for card_id, due in zip(ids, dues)]})
    with _patched(fake):
        planned = first_touch.plan(_settings())
        report = first_touch.put_back(_settings())
    assert planned["earlier"] is True and planned["taken_at"] == "2026-10-01T08:00:00"
    # The deck was renamed since its file: the cards are found by id, and that earliest file's numbers win (K14).
    assert [fake.cards[card_id]["due"] for card_id in ids] == [2802, 2801, 2800]
    assert "the order Surasura kept on 2026-10-01" in report["message"]


def test_fields_back_only_where_you_havent_edited_them_and_only_when_asked(tmp_path):
    fake = _fill_fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ"), _lapis(2, "囲む", "かこむ"))
    with _patched(fake):
        assert backfill.run(_fill_settings(), _Session())["ok"]
    edited = next(n for n in fake.notes.values() if n["fields"]["Expression"]["value"] == "大切")
    edited["fields"]["Patterns"]["value"] = "<div>大切に — 私のメモ</div>"
    with _patched(fake):
        planned = first_touch.plan(_fill_settings())
    assert planned["ok"] and planned["fields_unedited"] == 2 and planned["fields_edited"] == 1
    with _patched(fake):
        kept = first_touch.put_back(_fill_settings(junban_auto_backfill=True), fields=False)
    assert kept["done"]["fields"] == 0 and kept["settings_changed"] == []
    assert sorted(n["fields"]["Patterns"]["value"] for n in fake.notes.values()) == sorted(
        [FIELD["探検"], FIELD["囲む"], "<div>大切に — 私のメモ</div>"])
    with _patched(fake):
        report = first_touch.put_back(_fill_settings(junban_auto_backfill=True), fields=True)
    assert report["ok"] and report["done"]["fields"] == 2
    assert sorted(n["fields"]["Patterns"]["value"] for n in fake.notes.values()) == sorted(
        ["", "", "<div>大切に — 私のメモ</div>"])
    assert report["settings_changed"] == ["junban_auto_backfill"]
    with open(os.path.join(str(tmp_path), "settings.json"), encoding="utf-8") as handle:
        assert json.load(handle)["junban_auto_backfill"] is False
    # AD-3 (P4.1): each put-back line names the decks whose fields came back (none when it left them), which is what
    # Connect's fill compares (`backfill._fields_put_back`), never the re-order's scope
    lines = [line for line in first_touch.journal("ja") if line["kind"] == "put_back"]
    assert [bool(line.get("field_decks")) for line in lines] == [False, True]
    assert backfill._fields_put_back("ja", _fill_settings().get("junban_backfill_deck")) is not None


def test_fields_backfill_filled_before_the_record_come_back_from_its_own_snapshot(tmp_path):
    """K7: a fill from before the record is only in `junban_backfill_undo.json` (true originals, carried forward)."""
    fake = _fill_fake(_lapis(0, "探検", "たんけん", patterns=FIELD["探検"]), _lapis(1, "大切", "たいせつ"))
    old = next(n for n in fake.notes.values() if n["fields"]["Expression"]["value"] == "探検")
    undo.save([], ["TheBank"], fields={str(old["noteId"]): {"Patterns": {"before": "", "after": FIELD["探検"]}}},
              kind="backfill")                                    # no profile: 2.5's fill, before the record
    undo.mark_complete("ja", kind="backfill")
    with _patched(fake):
        assert backfill.run(_fill_settings(), _Session())["ok"]       # one fill after the record (大切)
        planned = first_touch.plan(_fill_settings())
        report = first_touch.put_back(_fill_settings(), fields=True)
    assert planned["fields_unedited"] == 2 and report["done"]["fields"] == 2
    assert old["fields"]["Patterns"]["value"] == ""


def test_the_automatic_reorder_stands_aside_first_for_a_deck_put_back(tmp_path, monkeypatch):
    """D7 (FT-1's lean), K11: the recorded (language, deck) pair is cleared through `save_keys` — before any write
    reaches Anki — never the whole file."""
    with open(os.path.join(str(tmp_path), "settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"junban_replan_deck": "TheBank", "junban_replan_language": "ja", "junban_deck": "TheBank",
                   "ui_scale": 125}, handle)
    fake, _original, _added = _touched(tmp_path)
    from app import settings_manager
    real_save, seen = settings_manager.save_keys, {}

    def save_keys(changes, *args, **kwargs):
        seen["requests_before"] = [r["action"] for r in fake.requests[start:]]
        return real_save(changes, *args, **kwargs)

    monkeypatch.setattr(settings_manager, "save_keys", save_keys)
    start = len(fake.requests)
    with _patched(fake):
        report = first_touch.put_back(_auto(junban_replan_deck="TheBank", junban_replan_language="ja"))
    assert report["ok"] and report["settings_changed"] == ["junban_replan_deck"]
    assert not {"unsuspend", "removeTags"} & set(seen["requests_before"])
    with open(os.path.join(str(tmp_path), "settings.json"), encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved["junban_replan_deck"] == "" and saved["ui_scale"] == 125 and saved["junban_deck"] == "TheBank"
    assert "順" not in report["message"]            # K6: the window words it from `settings_changed`


def test_a_chinese_deck_is_put_back_from_its_own_folder(tmp_path):
    cards, notes, _ = _collection(["学习", "朋友", "开心"], dues=[7002, 7001, 7000], deck="中文::HSK 3级")
    fake = PutBackCollection(cards, notes)
    ids = sorted(fake.cards)
    first_touch.keep_order("zh", ["中文::HSK 3级"], "deck", [(card_id, 100 + n) for n, card_id in enumerate(ids)],
                           profile="DevTest")
    with _patched(fake):
        assert first_touch.plan(_settings(target_language="ja"))["nothing"]           # Japanese kept nothing
        report = first_touch.put_back(_settings(target_language="zh"))
    assert report["ok"] and [fake.cards[card_id]["due"] for card_id in ids] == [100, 101, 102]


# =============================================================================================================== #
# The build review's fixes (worker C; register reviews/FT-build-reviews.md, card work/FT-worker-C.md)
# =============================================================================================================== #
def _save_settings(tmp_path, **values):
    with open(os.path.join(str(tmp_path), "settings.json"), "w", encoding="utf-8") as handle:
        json.dump(values, handle, ensure_ascii=False)


def _writes(fake):
    return [r for r in fake.requests if r["action"] in ("suspend", "unsuspend", "removeTags", "addTags")
            or (r["action"] == "multi" and any(a["action"] in ("setSpecificValueOfCard", "updateNoteFields")
                                               for a in r["params"]["actions"]))]


def _new_card(fake, card_id, word, deck="TheBank", queue=0, tags=()):
    fake.notes[card_id - 1_000_000] = _note(word, card_id - 1_000_000, list(tags))
    fake.cards[card_id] = {"cardId": card_id, "note": card_id - 1_000_000, "due": 2700, "type": 0, "queue": queue,
                           "deckName": deck, "mod": 1_700_000_000}
    return fake.cards[card_id]


def test_c1_an_automatic_job_that_waited_on_a_put_back_stands_aside_and_writes_nothing(deck, tmp_path, monkeypatch):
    """A-B1 / IK3: the host read its settings, then waited for the Anki-write lock while a put-back held it and
    cleared the recorded deck. Holding the lock at last, the job reads the file again: the pair gone, it writes
    nothing, asks Anki nothing, and says why (`stands_aside`, which the host shows). While the file still holds the
    pair, the same job runs as ever."""
    from app import anki_connect, settings_manager
    _save_settings(tmp_path, junban_replan_deck="TheBank", junban_replan_language="ja", junban_deck="TheBank",
                   enable_junban=True)
    settings = _settings(junban_replan_deck="TheBank", junban_replan_language="ja")
    with _patched(deck):
        assert reposition.run(settings, job=spaced.Job(automatic=True, cards=reposition.CardMap()))["ok"]
    real_take = anki_connect.take_writer

    def put_back_held_it_first(*args, **kwargs):
        held = real_take(*args, **kwargs)
        settings_manager.save_keys({"junban_replan_deck": ""})          # what the put-back did meanwhile (K11)
        return held

    monkeypatch.setattr(anki_connect, "take_writer", put_back_held_it_first)
    deck.cards[min(deck.cards)]["due"] = 1                               # something the job would re-order
    deck.requests.clear()
    writes = list(deck.writes)
    with _patched(deck):
        report = reposition.run(settings, job=spaced.Job(automatic=True, cards=reposition.CardMap()))
    assert not report["ok"] and report["stands_aside"] is True and report["problems"]
    assert deck.writes == writes and deck.requests == []


def test_c2_an_all_decks_file_covers_only_its_own_decks_and_a_wider_run_keeps_a_file_for_the_rest(tmp_path):
    """A-B2: an "all decks" run over TheBank and Kaishi keeps those decks' order — never 日本語::Mining's, which
    it never read. A later run over all three keeps a file of its own (the earliest file still wins per card)."""
    first_touch.keep_order("ja", ["TheBank", "Kaishi 1.5k"], "all", [(1789712080000, 2800)], profile="DevTest")
    assert first_touch.covered("ja", ["Kaishi 1.5k"], "deck", "DevTest")
    assert first_touch.covered("ja", ["TheBank::文法"], "deck", "DevTest")            # a subdeck of one it holds
    assert not first_touch.covered("ja", ["日本語::Mining"], "deck", "DevTest")
    assert not first_touch.covered("ja", ["TheBank", "Kaishi 1.5k", "日本語::Mining"], "all", "DevTest")
    wider = first_touch.keep_order("ja", ["TheBank", "Kaishi 1.5k", "日本語::Mining"], "all",
                                   [(1789712080000, 2800), (1789712090000, 10)], profile="DevTest")
    assert wider and len(_order_files()) == 2
    assert first_touch.covered("ja", ["日本語::Mining"], "deck", "DevTest")


def test_c3_each_request_reads_its_cards_again_and_leaves_what_you_changed_after_the_survey(tmp_path, monkeypatch):
    """A-B3 / H2: the put-back plans from one read and writes a moment later. In between you take 須藤's later tag
    off (its suspension may be yours now) and flag 図書館 red: neither is written over."""
    fake, _original, _added = _touched(tmp_path)
    real_survey = first_touch._survey

    def then_you_change_them(*args, **kwargs):
        survey = real_survey(*args, **kwargs)
        note = fake.notes[_card_of(fake, "須藤")["note"]]
        note["tags"] = [tag for tag in note["tags"] if tag != LATER_TAG]
        _card_of(fake, "図書館")["flags"] = 1
        return survey

    monkeypatch.setattr(first_touch, "_survey", then_you_change_them)
    with _patched(fake):
        report = first_touch.put_back(_auto())
    assert _card_of(fake, "須藤")["queue"] == -1 and _card_of(fake, "図書館")["flags"] == 1
    assert _card_of(fake, "図書館")["queue"] == 0 and report["done"]["unsuspended"] == 3


def test_c3_a_field_you_edit_after_the_survey_is_left_as_you_wrote_it(tmp_path, monkeypatch):
    fake = _fill_fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ"))
    with _patched(fake):
        assert backfill.run(_fill_settings(), _Session())["ok"]
    mine = next(n for n in fake.notes.values() if n["fields"]["Expression"]["value"] == "大切")
    real_survey = first_touch._survey

    def then_you_edit(*args, **kwargs):
        survey = real_survey(*args, **kwargs)
        mine["fields"]["Patterns"]["value"] = "<div>大切に — 私のメモ</div>"
        return survey

    monkeypatch.setattr(first_touch, "_survey", then_you_edit)
    with _patched(fake):
        report = first_touch.put_back(_fill_settings(), fields=True)
    assert report["done"]["fields"] == 1 and mine["fields"]["Patterns"]["value"] == "<div>大切に — 私のメモ</div>"


def test_c4_a_card_map_this_run_didnt_read_never_names_the_profile(tmp_path):
    """IK1 / A-S3: a job carries a warm map from an earlier run (another profile was open then). This run — one of
    Connect's, which gathers the parked cards and so reads afresh, never through the map — asks Anki."""
    from modules.junban.tests.connect_scene import scene
    from modules.junban.tests.connect_scene import settings as connect_settings
    fake = scene(tmp_path)
    stale = reposition.CardMap()
    stale.key = ("Sonic", URL, ("TheBank",))
    with _patched(fake):
        done = auto.reorder(connect_settings(), list_current=True, positions_only=True,
                            run_id=undo.new_run_id("reorder"), job=spaced.Job(automatic=True, cards=stale))
    assert done["outcome"] == "ran", done
    assert stale.reads == 0
    [data] = _order_files()
    assert data["profile"] == ""            # Anki's own answer (this fake names none), never the map's "Sonic"


def test_c5_a_card_made_after_an_earlier_file_for_its_deck_goes_after_whatever_a_later_file_holds(tmp_path):
    """A-S1: TheBank's order was kept, then 散歩 was added, then an "all decks" run kept every deck — 散歩 too.
    TheBank's file says 散歩 came after it: it goes after the kept cards, never to the later file's number."""
    cards, notes, _ = _collection(["須藤", "冒険", "散歩"], dues=[5000, 5001, 5002])
    fake = PutBackCollection(cards, notes)
    a, b, c = sorted(fake.cards)
    deck_file = {"schema": 1, "taken_at": "2026-10-01T08:00:00", "taken_ms": c - 1, "profile": "DevTest",
                 "mode": "deck", "scope": ["TheBank"], "earlier": False, "cards": [[a, 2800], [b, 2801]]}
    all_file = dict(deck_file, taken_at="2026-10-02T08:00:00", taken_ms=c + 1000, mode="all",
                    scope=["Kaishi 1.5k", "TheBank"], cards=[[a, 3000], [b, 3001], [c, 3002]])
    for data in (deck_file, all_file):
        first_touch._create_once(first_touch.order_path("ja", data["scope"], data["mode"], "DevTest"), data)
    with _patched(fake):
        planned = first_touch.plan(_settings())
        assert first_touch.put_back(_settings())["ok"]
    assert [fake.cards[card]["due"] for card in (a, b, c)] == [2800, 2801, 3003]
    assert planned["added_after"] == 1


def test_c6_a_later_versions_order_file_covers_and_is_never_moved_or_put_back(tmp_path):
    """A-S2 / H9 / H10 / IK18: Surasura 3.1 kept TheBank's order in a schema this version can't read — it covers
    the deck (no second file), is never set aside, and is never put back from."""
    path = first_touch.order_path("ja", ["TheBank"], "deck", "DevTest")
    first_touch._create_once(path, {"schema": 2, "profile": "DevTest", "mode": "deck", "scope": ["TheBank"],
                                    "positions": {"1789712080000": 2800}})
    assert first_touch.covered("ja", ["TheBank"], "deck", "DevTest")
    assert first_touch.keep_order("ja", ["TheBank"], "deck", [(1789712080000, 2800)], profile="DevTest") is None
    assert first_touch.orders("ja", set_aside=True) == ([], []) and os.path.isfile(path)
    assert first_touch.set_aside("ja") == []


def test_c6_plan_moves_nothing_and_only_the_writer_sets_a_broken_file_aside(tmp_path):
    fake, _original, _added = _touched(tmp_path)
    broken = first_touch.order_path("ja", ["Kaishi 1.5k"], "deck", "DevTest")
    with open(broken, "w", encoding="utf-8") as handle:
        handle.write('{"schema": 1, "cards": [[17897')
    with _patched(fake):
        assert first_touch.plan(_auto())["ok"]
    assert os.path.isfile(broken) and first_touch.set_aside("ja") == []      # `plan` holds no lock: moves nothing
    with _patched(fake):
        assert first_touch.put_back(_auto())["ok"]
    assert not os.path.isfile(broken) and len(first_touch.set_aside("ja")) == 1


def test_c7_a_run_reads_only_the_order_files_named_for_its_deck(tmp_path, monkeypatch):
    """IK5 / H14: a fresh process's first run reads its deck's own file and the profile's "all decks" files — never
    every other deck's."""
    for name in ("Kaishi 1.5k", "中文::HSK 3级", "日本語::Mining", "TheBank"):
        first_touch.keep_order("ja", [name], "deck", [(1789712080000, 2800)], profile="DevTest")
    first_touch._COVERED.clear()
    real_open, read = open, []

    def watched(name, *args, **kwargs):
        if os.path.basename(str(name)).startswith(first_touch.ORDER_PREFIX):
            read.append(os.path.basename(str(name)))
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr("builtins.open", watched)
    assert first_touch.keep_order("ja", ["TheBank"], "deck", [], profile="DevTest") is None
    monkeypatch.setattr("builtins.open", real_open)
    assert read == [os.path.basename(first_touch.order_path("ja", ["TheBank"], "deck", "DevTest"))]


def test_c7_a_positions_only_move_with_no_card_map_asks_what_it_asked_before_the_record(
        ranked_words, write_priority_csv, priority_rows, tmp_path, monkeypatch):
    """IK5 / A-S9 / H11: the automatic step with no warm map (AutoJunban, `junban --auto`) reads the profile for its
    record and hands it to S1, which asked it anyway — the first respace and the move after it send the same
    requests, in the same order, as the same jobs with no record at all (each in a folder of its own)."""
    import shutil

    from app import anki_sync_rule
    write_priority_csv()
    with open(os.path.join(str(tmp_path), "results", "priority_learning_list.csv"), "rb") as handle:
        listed = handle.read()
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, ranked_words[12:16])
    with open(os.path.join(str(tmp_path), "results", "priority_learning_list.csv"), "rb") as handle:
        moved = handle.read()
    words = ranked_words[:24] + UNRANKED
    seen = {}
    for name in ("with_the_record", "before_it"):
        root = tmp_path / name
        (root / "results").mkdir(parents=True)
        (root / "persistent").mkdir()
        (root / "results" / "priority_learning_list.csv").write_bytes(listed)
        monkeypatch.setenv("SURASURA_TEST_ROOT", str(root))
        monkeypatch.setattr("app.path_utils.get_persistent_user_data_path", lambda root=root: str(root / "persistent"))
        monkeypatch.setattr(anki_sync_rule, "_path", lambda root=root: str(root / "anki_sync.json"))
        if name == "before_it":
            monkeypatch.setattr(reposition, "_keep_order", lambda *args, **kwargs: None)
        cards, notes, _ = _collection(words, dues=list(range(2800 + len(words) - 1, 2799, -1)))
        fake = ModCollection(cards, notes)
        with _patched(fake):
            assert reposition.run(_settings(), job=spaced.Job(automatic=True))["ok"]
        (root / "results" / "priority_learning_list.csv").write_bytes(moved)
        first = list(fake.requests)
        fake.requests.clear()
        first_touch._COVERED.clear()                          # the move in a new process: the file answers
        with _patched(fake):
            report = reposition.run(_settings(), job=spaced.Job(automatic=True))
        assert report["ok"] and report["written"]
        seen[name] = (first, list(fake.requests))
    shutil.rmtree(str(tmp_path / "before_it"), ignore_errors=True)
    assert seen["with_the_record"] == seen["before_it"]


def test_c8_the_put_back_refuses_when_the_profile_open_isnt_the_one_the_confirm_counted(tmp_path):
    """A-S4: the confirm was about one profile's cards; another open now (one with a record of its own, maybe) —
    nothing is written."""
    fake, _original, _added = _touched(tmp_path)
    fake.requests.clear()
    with _patched(fake):
        report = first_touch.put_back(_auto(), profile="Sonic")
    assert not report["ok"] and report["wrong_profile"] == "Sonic" and '"Sonic"' in report["message"]
    assert _writes(fake) == []


def test_c9_an_unfinished_snapshot_of_another_deck_stays_unfinished(tmp_path):
    """A-S5 / IK14: the put-back supersedes only the snapshots its record covers."""
    fake, _original, _added = _touched(tmp_path)
    undo.save({1789712099999: 10}, ["Kaishi 1.5k"])               # another deck's run, cut short
    with _patched(fake):
        assert first_touch.put_back(_auto())["ok"]
    assert undo.load("ja")["complete"] is False
    undo.save({_card_of(fake, "冒険")["cardId"]: 1}, ["TheBank"])   # this deck's, cut short
    with _patched(fake):
        assert first_touch.put_back(_auto())["ok"]
    assert undo.load("ja")["complete"] is True


def test_c10_older_changes_are_counted_only_in_the_records_decks(tmp_path):
    """A-S6 / IK17: a card suspended under Surasura's later tag in another deck is no part of this record."""
    fake, _original, _added = _touched(tmp_path)
    here = _new_card(fake, 1789712070000, "鳥取", queue=-1, tags=[LATER_TAG])
    there = _new_card(fake, 1789712070001, "眼鏡", deck="Kaishi 1.5k", queue=-1, tags=[LATER_TAG])
    with _patched(fake):
        planned = first_touch.plan(_auto())
        report = first_touch.put_back(_auto(), older=True)
    assert planned["older_suspended"] == 1 and planned["older_tags"] == 1 and report["ok"]
    assert here["queue"] == 0 and there["queue"] == -1
    assert fake.notes[there["note"]]["tags"] == [LATER_TAG]


def test_c11_a_suspend_whose_landed_line_was_lost_is_said_and_offered_with_the_older_changes(tmp_path, monkeypatch):
    """A-S7 / IK8: the run's `landed` line couldn't be written. The run says so; the put-back doesn't unsuspend
    those cards (K3: never confirmed) but offers them among the older changes, and keeps their notes' later tag."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    cards, notes, _ = _collection(["須藤", "散歩", "図書館", "冒険", "美術館", "新幹線", "洗濯機"])
    fake = PutBackCollection(cards, notes, actions=_ACTIONS)
    _card_of(fake, "洗濯機")["queue"] = -1                  # yours, suspended before any of it
    real_note = first_touch.note

    def landed_lost(language, kind, profile=None, deck=None, **items):
        if items.get("landed"):
            raise OSError("disk full")
        return real_note(language, kind, profile, deck, **items)

    monkeypatch.setattr(first_touch, "note", landed_lost)
    with _patched(fake):
        ran = reposition.run(_auto())
    monkeypatch.setattr(first_touch, "note", real_note)
    assert any("couldn't note which cards it suspended" in line for line in ran["problems"])
    off = [_card_of(fake, word) for word in _OFF_THE_LIST]
    assert all(card["queue"] == -1 for card in off)
    with _patched(fake):
        planned = first_touch.plan(_auto())
        report = first_touch.put_back(_auto())
    assert planned["unsuspend"] == 0 and planned["older_suspended"] == 4 and report["ok"]
    assert all(card["queue"] == -1 and LATER_TAG in fake.notes[card["note"]]["tags"] for card in off)


def test_c12_settings_that_cant_be_saved_refuse_before_anything_reaches_anki(tmp_path, monkeypatch):
    """A-S8: the automatic re-order must stand aside before the cards go back; a settings file that can't be saved
    (held, or not written) refuses the put-back with nothing written."""
    from app import settings_manager
    fake, _original, _added = _touched(tmp_path)
    asked = []

    def held(changes, *args, **kwargs):
        asked.append(kwargs)
        raise OSError("your settings file is being saved by another window or program just now")

    monkeypatch.setattr(settings_manager, "save_keys", held)
    fake.requests.clear()
    with _patched(fake):
        report = first_touch.put_back(_auto(junban_replan_deck="TheBank", junban_replan_language="ja"))
    assert not report["ok"] and "nothing was changed" in report["message"] and _writes(fake) == []
    assert asked == [{"strict": True, "wait": first_touch.SETTINGS_WAIT_S}]


def test_c13_earlier_is_decided_once_never_by_what_surasura_wrote_after_the_first_touch(tmp_path):
    """A-S10 / IK6: nothing of Junban's existed at the first touch. Junban's own files written since (a snapshot, a
    Chinese ladder) never make a later file `earlier` — in either language, in a new process too."""
    first_touch.keep_order("ja", ["TheBank"], "deck", [], profile="DevTest")
    undo.save({1789712080001: 2801}, ["TheBank"])
    undo.record_ladder("zh", ["中文::HSK 3级"], floor=2800)
    first_touch._STARTED.clear()
    first_touch.keep_order("ja", ["Kaishi 1.5k"], "deck", [], profile="DevTest")
    first_touch.keep_order("zh", ["中文::HSK 3级"], "deck", [], profile="DevTest")
    assert [data["earlier"] for data in _order_files()] == [False, False]
    assert [data["earlier"] for data in _order_files("zh")] == [False]


def test_c13_a_backfill_first_touch_keeps_the_answer_for_the_first_order_file(tmp_path):
    """2.5's reorder left its snapshot; after FT shipped, Backfill touched first (a journal line), then Junban: its
    first order file is Surasura's order of then (`earlier`), the next one isn't."""
    undo.save({1789712080001: 2801}, ["TheBank"])                    # 2.5's run, before the record
    undo.mark_complete("ja")
    first_touch.note("ja", "backfill", "DevTest", ["All decks"],
                     fields={"1789712000001": {"Patterns": {"before": "", "after": FIELD["探検"]}}})
    first_touch.keep_order("ja", ["TheBank"], "deck", [], profile="DevTest")
    first_touch.keep_order("ja", ["Kaishi 1.5k"], "deck", [], profile="DevTest")
    earlier = {tuple(data["scope"]): data["earlier"] for data in _order_files()}
    assert earlier == {("TheBank",): True, ("Kaishi 1.5k",): False}


def test_c14_a_put_back_not_asked_for_older_changes_never_reads_them(tmp_path):
    fake, _original, _added = _touched(tmp_path)
    fake.searches = []
    with _patched(fake):
        assert first_touch.put_back(_auto())["ok"]
    assert [query for action, query in fake.searches if action == "findNotes" or "is:suspended" in query] == []


def test_c16_backfills_automatic_step_goes_off_only_when_it_fills_a_deck_whose_fields_come_back(tmp_path):
    """IK4 (Haya's call): Backfill filled TheBank. Its automatic step set to fill TheBank, or all decks, goes off
    with the fields; set to fill Kaishi, it stays on."""
    fake = _fill_fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ"))
    with _patched(fake):
        assert backfill.run(_fill_settings(junban_backfill_deck="TheBank"), _Session())["ok"]
        same = first_touch.plan(_fill_settings(junban_auto_backfill=True, junban_backfill_deck="TheBank"))
        every = first_touch.plan(_fill_settings(junban_auto_backfill=True, junban_backfill_deck=""))
        other = _fill_settings(junban_auto_backfill=True, junban_backfill_deck="Kaishi 1.5k")
        elsewhere = first_touch.plan(other)
        report = first_touch.put_back(other, fields=True)
    assert same["backfill_fills"] == "TheBank" and every["backfill_fills"] == ""
    assert elsewhere["backfill_fills"] is None
    assert report["ok"] and report["done"]["fields"] == 2 and report["settings_changed"] == []


def test_c17_plan_says_the_automatic_reorder_will_stand_aside_for_the_deck(tmp_path):
    fake, _original, _added = _touched(tmp_path)
    with _patched(fake):
        planned = first_touch.plan(_auto(junban_replan_deck="TheBank", junban_replan_language="ja"))
        elsewhere = first_touch.plan(_auto(junban_replan_deck="Kaishi 1.5k", junban_replan_language="ja"))
    assert planned["stands_aside"] == "TheBank" and elsewhere["stands_aside"] is None


def test_c19_fields_chain_back_to_the_text_from_before_the_record(tmp_path):
    """IK13 / A-N1: Backfill filled 探検 before the record ("" → A, in its snapshot), and a fill after it wrote B over
    A (the journal: A → B) — the text from before Surasura is "". Junban's frequency field, rewritten every run, comes
    back to your own number from the reorder snapshot that carried it forward (54614 → 42 before the record, 42 → 40
    after: the snapshot holds 54614 → 40)."""
    fake = _fill_fake(_lapis(0, "探検", "たんけん", patterns="<div>B</div>"), _lapis(1, "大切", "たいせつ"))
    tanken, taisetsu = (next(n for n in fake.notes.values() if n["fields"]["Expression"]["value"] == word)
                        for word in ("探検", "大切"))
    taisetsu["fields"]["Glossary"]["value"] = "40"
    undo.save([], ["TheBank"], fields={str(tanken["noteId"]): {"Patterns": {"before": "", "after": "<div>A</div>"}}},
              kind="backfill")
    undo.mark_complete("ja", kind="backfill")
    undo.save([], ["TheBank"], fields={str(taisetsu["noteId"]): {"Glossary": {"before": "54614", "after": "40"}}})
    undo.mark_complete("ja")
    first_touch.note("ja", "backfill", "", ["TheBank"],
                     fields={str(tanken["noteId"]): {"Patterns": {"before": "<div>A</div>", "after": "<div>B</div>"}}})
    first_touch.note("ja", "reorder", "", ["TheBank"],
                     fields={str(taisetsu["noteId"]): {"Glossary": {"before": "42", "after": "40"}}})
    with _patched(fake):
        planned = first_touch.plan(_fill_settings())
        report = first_touch.put_back(_fill_settings(), fields=True)
    assert planned["fields_unedited"] == 2 and report["done"]["fields"] == 2
    assert tanken["fields"]["Patterns"]["value"] == "" and taisetsu["fields"]["Glossary"]["value"] == "54614"


def test_c22_a_profile_anki_doesnt_name_reads_the_same_on_every_path(tmp_path):
    """A-N3: the card map's read and the run's own both say "" — never the text "None" on one of them."""
    cards, notes, _ = _collection(["須藤", "冒険"])
    fake = PutBackCollection(cards, notes, profile=None)
    card_map = reposition.CardMap()
    with _patched(fake):
        card_map.read(URL, ["TheBank"])
        assert first_touch.open_profile(URL) == ""
    assert card_map.key[0] == ""


def test_c25_a_broken_file_that_cant_be_set_aside_refuses_the_run(tmp_path, monkeypatch):
    """H1: the broken file can't be moved aside (another program holds it) — the run writes nothing, never a run
    without its order kept."""
    path = first_touch.order_path("ja", ["TheBank"], "deck", "DevTest")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"schema": 1, "cards": [[17897')
    real_rename = os.rename

    def held(source, target):
        if ".unreadable-" in str(target):
            raise PermissionError(13, "held by another program")
        return real_rename(source, target)

    monkeypatch.setattr(os, "rename", held)
    with pytest.raises(OSError):
        first_touch.keep_order("ja", ["TheBank"], "deck", [(1789712080000, 2800)], profile="DevTest")
    monkeypatch.setattr(os, "rename", real_rename)
    with open(path, encoding="utf-8") as handle:
        assert handle.read() == '{"schema": 1, "cards": [[17897'


def test_c26_an_anki_refusal_reads_as_itself_not_as_anki_closed(tmp_path, monkeypatch):
    """H3: Anki answered and refused a search — the line says what it refused, never "Open Anki first"."""
    fake, _original, _added = _touched(tmp_path)
    real = fake._dispatch

    def refuse(action, params):
        if action == "findCards" and '"tag:' in params.get("query", ""):
            return AnkiRefusal("the collection is not available")
        return real(action, params)

    monkeypatch.setattr(fake, "_dispatch", refuse)
    with _patched(fake):
        planned = first_touch.plan(_auto())
        report = first_touch.put_back(_auto())
    assert not planned["ok"] and not planned["anki_closed"] and "not available" in planned["problems"][0]
    assert not report["ok"] and not report["anki_closed"] and "not available" in report["message"]


def test_c27_a_journal_line_whose_keys_arent_numbers_is_skipped(tmp_path):
    """H4 / H15: a line edited by hand (or by a later version) never stops the put-back."""
    fake, _original, _added = _touched(tmp_path)
    with open(os.path.join(first_touch.folder("ja"), first_touch.JOURNAL), "ab") as handle:
        handle.write(json.dumps({"kind": "reorder", "profile": "DevTest", "deck": ["TheBank"],
                                 "flags": {"須藤": [0, 7]}, "fields": {"x": {"Patterns": {"before": "", "after": "y"}}}},
                                ensure_ascii=False).encode("utf-8") + b"\n")
    with _patched(fake):
        planned = first_touch.plan(_auto())
        report = first_touch.put_back(_auto())
    assert planned["ok"] and report["ok"] and report["done"]["unsuspended"] == 4


def test_c27_plan_and_put_back_never_raise_and_the_last_journal_line_never_escapes(tmp_path, monkeypatch):
    """H6 / H15: a fault anywhere becomes a line; once Anki changed, the put-back's own record can't take the report
    down with it."""
    fake, _original, _added = _touched(tmp_path)
    real_survey, real_note = first_touch._survey, first_touch.note

    def broken(*args, **kwargs):
        raise RuntimeError("an unexpected fault")

    monkeypatch.setattr(first_touch, "_survey", broken)
    with _patched(fake):
        planned = first_touch.plan(_auto())
        report = first_touch.put_back(_auto())
    assert not planned["ok"] and "unexpected fault" in planned["problems"][0]
    assert not report["ok"] and "unexpected fault" in report["message"]
    monkeypatch.setattr(first_touch, "_survey", real_survey)

    def no_put_back_line(language, kind, *args, **kwargs):
        if kind == "put_back":
            raise ValueError("a value the journal can't hold")
        return real_note(language, kind, *args, **kwargs)

    monkeypatch.setattr(first_touch, "note", no_put_back_line)
    with _patched(fake):
        report = first_touch.put_back(_auto())
    assert report["ok"] and report["warnings"] and report["done"]["unsuspended"] == 4


def test_c28_a_blank_deck_name_never_holds_every_deck_under_it():
    """H7: "" + "::" is a prefix of every name that starts with "::" — a blank scope never holds anything."""
    assert not first_touch._in_scope({"scope": ["", "  "]}, "::Mining")
    assert not first_touch._in_scope({"scope": [""]}, "")
    assert first_touch._in_scope({"scope": ["日本語"]}, "日本語::Mining")


def test_m01_the_order_file_temporary_is_fsynced_before_it_is_renamed_into_place(tmp_path, monkeypatch):
    """M01: the order file's temporary is flushed and fsync'd before the create-once rename puts it under its name."""
    real_open, real_fsync, real_rename = open, os.fsync, os.rename
    target = first_touch.order_path("ja", ["TheBank"], "deck", "DevTest")
    names, events = {}, []

    def recording_open(name, *args, **kwargs):
        handle = real_open(name, *args, **kwargs)
        if str(name).startswith(target + "."):           # the order file's own temporary only
            names[handle.fileno()] = str(name)
        return handle

    def recording_fsync(fd):
        events.append(("fsync", names.get(fd)))
        real_fsync(fd)

    def recording_rename(source, destination):
        events.append(("rename", str(source), str(destination)))
        real_rename(source, destination)

    with monkeypatch.context() as patched:      # scoped: an undo() would also undo the harness's test root
        patched.setattr(os, "name", "nt")                # the Windows branch: rename is the create-once
        patched.setattr("builtins.open", recording_open)
        patched.setattr(os, "fsync", recording_fsync)
        patched.setattr(os, "rename", recording_rename)
        assert first_touch.keep_order("ja", ["TheBank"], "deck", [(1789712080000, 2800)], profile="DevTest") == target
    renames = [event for event in events if event[0] == "rename" and event[2] == target]
    assert len(renames) == 1, events
    source = renames[0][1]
    assert events.index(("fsync", source)) < events.index(renames[0]), events     # flushed to disk, then renamed
    with real_open(target, encoding="utf-8") as handle:
        assert "cards" in json.load(handle)


def test_m02_a_run_never_reads_another_profiles_all_decks_file(tmp_path, monkeypatch):
    """C7: a run reads the files named for its deck and THIS profile's "all decks" files, never another profile's."""
    first_touch.keep_order("ja", ["TheBank", "日本語::Mining"], "all", [(1789712080000, 2800)], profile="Sonic")
    sonic_file = os.path.basename(first_touch.order_path("ja", ["TheBank", "日本語::Mining"], "all", "Sonic"))
    first_touch._COVERED.clear()
    real_open, read = open, []

    def watched(name, *args, **kwargs):
        if os.path.basename(str(name)).startswith(first_touch.ORDER_PREFIX):
            read.append(os.path.basename(str(name)))
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr("builtins.open", watched)
    try:
        first_touch.keep_order("ja", ["TheBank"], "deck", [], profile="DevTest")
    finally:
        monkeypatch.setattr("builtins.open", real_open)
    assert sonic_file not in read


def test_m03_thebank_2_is_not_inside_thebank_though_its_name_starts_with_it():
    """A deck is within another only when equal or a "::" subdeck: "TheBank 2" is not under "TheBank" (M03)."""
    first_touch.keep_order("ja", ["TheBank", "Kaishi 1.5k"], "all", [(1789712080000, 2800)], profile="DevTest")
    assert first_touch.covered("ja", ["TheBank"], "deck", "DevTest")                  # the positive control
    assert first_touch.covered("ja", ["TheBank::文法"], "deck", "DevTest")
    assert not first_touch.covered("ja", ["TheBank 2"], "deck", "DevTest")
    assert not first_touch.covered("ja", ["TheBank 2", "TheBank"], "all", "DevTest")


def test_m04_a_connect_run_snapshot_alone_makes_the_first_order_file_earlier():
    """K9: a Connect run snapshot in the other language's runs folder is Junban having written before, so the first
    order file kept after it is `earlier: True` — the snapshot alone, with no ledger or Backfill file beside it."""
    undo.save({1789712080001: 2801}, ["TheBank"], language="zh", run_id=undo.new_run_id("reorder", language="zh"))
    first_touch.keep_order("ja", ["TheBank"], "deck", [], profile="DevTest")
    [data] = _order_files()
    assert data["earlier"] is True


def test_m05_a_journal_line_as_the_first_touch_decides_started_before_later_files(tmp_path):
    """C13: with nothing of Junban's on disk, a journal line (Backfill's first write) decides started.json at once;
    Backfill's snapshot written after it does not make the first order file `earlier`."""
    first_touch.note("ja", "backfill", "DevTest", ["All decks"],
                     fields={"1789712000001": {"Patterns": {"before": "", "after": FIELD["探検"]}}})
    undo.save([], ["All decks"], fields={"1789712000001": {"Patterns": {"before": "", "after": FIELD["探検"]}}},
              kind="backfill")
    first_touch.keep_order("ja", ["TheBank"], "deck", [], profile="DevTest")
    assert [data["earlier"] for data in _order_files()] == [False]


def test_m06_another_profiles_journal_lines_are_never_put_back(tmp_path):
    """K1: the put-back undoes only the open profile's journal lines — a line another profile wrote (Surasura
    unsuspended 須藤's card under "Sonic") never stops the open profile's put-back from unsuspending it."""
    fake, _original, _added = _touched(tmp_path)
    sudo_card = _card_of(fake, "須藤")["cardId"]
    first_touch.note("ja", "reorder", "Sonic", ["TheBank"], unsuspended=[sudo_card])
    with _patched(fake):
        report = first_touch.put_back(_auto())
    assert report["ok"], report
    assert report["done"]["unsuspended"] == 4                      # all four of Junban's, not three
    assert _card_of(fake, "須藤")["queue"] == 0


def test_m07_another_profiles_earlier_order_file_is_never_put_back_over_this_profiles_cards(tmp_path):
    """K1: an earlier order file of another profile (Sonic) for the same deck is left alone; the put-back restores
    DevTest's own numbers, and Sonic's file is neither applied nor changed."""
    fake, original, _added = _touched(tmp_path)
    ids = [card_id for card_id in original if card_id != _card_of(fake, "洗濯機")["cardId"]]
    path = first_touch.order_path("ja", ["TheBank"], "deck", "Sonic")
    first_touch._create_once(path, {
        "schema": 1, "taken_at": "2026-09-21T08:00:00", "taken_ms": 1_790_000_000_000, "profile": "Sonic",
        "mode": "deck", "scope": ["TheBank"], "earlier": True,
        "cards": [[card_id, 100 + n] for n, card_id in enumerate(ids)]})
    with open(path, "rb") as handle:
        before = handle.read()
    moved = sum(1 for w in ("須藤", "図書館", "冒険", "美術館", "新幹線")
                if _card_of(fake, w)["due"] != original[_card_of(fake, w)["cardId"]])
    assert moved                                            # the 順 run moved some of them, so the put-back has work
    with _patched(fake):
        report = first_touch.put_back(_auto())
    assert report["ok"], report
    for word in ("須藤", "図書館", "冒険", "美術館", "新幹線"):
        card = _card_of(fake, word)
        assert card["due"] == original[card["cardId"]], word   # DevTest's numbers, not Sonic's 100-plus
    with open(path, "rb") as handle:
        assert handle.read() == before


def test_m08_added_since_cards_go_after_the_highest_kept_number_whatever_the_list_order(tmp_path):
    """M08: a card added after the record goes after the HIGHEST due any order file holds, even when the file's
    list ends with a lower due — the last pair read is not the top."""
    cards, notes, _ = _collection(["須藤", "冒険", "散歩"], dues=[2801, 2800, 5002])
    fake = PutBackCollection(cards, notes)
    a, b, c = sorted(fake.cards)
    deck_file = {"schema": 1, "taken_at": "2026-10-01T08:00:00", "taken_ms": c - 1, "profile": "DevTest",
                 "mode": "deck", "scope": ["TheBank"], "earlier": False, "cards": [[a, 2801], [b, 2800]]}
    first_touch._create_once(first_touch.order_path("ja", deck_file["scope"], "deck", "DevTest"), deck_file)
    with _patched(fake):
        assert first_touch.put_back(_settings())["ok"]
    assert [fake.cards[card]["due"] for card in (a, b, c)] == [2801, 2800, 2802]


def test_m09_the_plan_never_counts_a_studied_card_for_unsuspending(tmp_path):
    """K3: a card you studied since Junban suspended it is not new any more — the plan leaves it out, and Put Anki
    back leaves it suspended (only still-new cards Junban suspended come back)."""
    fake, _original, _added = _touched(tmp_path)
    studied = _card_of(fake, "須藤")
    assert studied["queue"] == -1 and LATER_TAG in _tags_of(fake, "須藤")    # Junban's suspend, still tagged
    studied.update(type=2, queue=-1)                                          # studied since, still suspended
    with _patched(fake):
        planned = first_touch.plan(_auto())
        report = first_touch.put_back(_auto())
    assert planned["ok"] and planned["unsuspend"] == 3                       # 須藤 is not counted
    assert report["ok"] and report["done"]["unsuspended"] == 3
    assert _card_of(fake, "須藤")["queue"] == -1 and _card_of(fake, "須藤")["type"] == 2


def test_m10_the_re_read_skips_a_card_studied_or_unsuspended_since_the_survey(tmp_path, monkeypatch):
    """M10: the put-back re-reads each batch before it unsuspends; a card you studied since the survey, or unsuspended
    yourself since, is left as it is — 須藤 stays suspended and 図書館 is never sent."""
    fake, _original, _added = _touched(tmp_path)
    real_survey = first_touch._survey

    def studied_and_unsuspended(*args, **kwargs):
        survey = real_survey(*args, **kwargs)
        _card_of(fake, "須藤").update(type=2)                  # studied since the survey: a review card, still suspended
        _card_of(fake, "図書館")["queue"] = 0                   # unsuspended by you since the survey
        return survey

    monkeypatch.setattr(first_touch, "_survey", studied_and_unsuspended)
    with _patched(fake):
        first_touch.put_back(_auto())
    sent = [card_id for action, card_ids in fake.suspend_calls if action == "unsuspend" for card_id in card_ids]
    assert _card_of(fake, "須藤")["type"] == 2 and _card_of(fake, "須藤")["queue"] == -1
    assert _card_of(fake, "須藤")["cardId"] not in sent and _card_of(fake, "図書館")["cardId"] not in sent


def test_m11_a_card_in_a_filtered_deck_keeps_its_due_through_the_put_back(tmp_path):
    """The put-back moves only new cards in their home deck: a card Junban moved that is now in a filtered deck
    keeps the due it has, and its deck is left as it is."""
    fake, original, _ = _touched(tmp_path)
    card = _card_of(fake, "図書館")
    assert card["due"] != original[card["cardId"]]          # Junban moved it: the put-back would restore it at home
    card.update(odeck=card["deckName"], deckName="Filtered Deck")
    held = card["due"]
    with _patched(fake):
        assert first_touch.plan(_auto())["ok"]
        report = first_touch.put_back(_auto())
    assert report["ok"], report
    assert _card_of(fake, "図書館")["due"] == held
    assert _card_of(fake, "図書館")["deckName"] == "Filtered Deck"


def test_m12_a_journalled_tag_is_counted_only_on_a_note_that_still_carries_it(tmp_path):
    """M12: tags_off counts a note only while the note carries a journalled tag; once a note's Surasura tags are
    taken off by hand (Connect's batch tag kept), the next plan counts exactly one note fewer."""
    fake, _original, _added = _touched(tmp_path)
    # Unsuspended by hand, so Surasura::later is not held by a suspend line (`staying`) and the journal counts it.
    _card_of(fake, "図書館")["queue"] = 0
    with _patched(fake):
        before = first_touch.plan(_auto())
    assert before["ok"] and before["tags_off"] >= 1
    note = fake.notes[_card_of(fake, "図書館")["note"]]            # a moved note: it carries Surasura's later tag
    assert _surasura_tags(fake, "図書館")
    note["tags"] = [tag for tag in note["tags"] if tag == CONNECT_TAG or not tag.casefold().startswith("surasura")]
    assert _surasura_tags(fake, "図書館") == []
    with _patched(fake):
        after = first_touch.plan(_auto())
    assert after["ok"] and after["tags_off"] == before["tags_off"] - 1


def test_m13_an_older_note_matched_only_through_a_child_tag_is_not_surasuras(tmp_path):
    """K4: Anki's `tag:Surasura` also finds `Surasura::mine`; an older note is counted and put back only where
    it carries Surasura's tag itself."""
    fake, _original, _added = _touched(tmp_path)
    mine = _new_card(fake, 1789712070000, "鳥取", tags=["Surasura::mine"])
    kyoto = _new_card(fake, 1789712070100, "京都", tags=["Surasura"])
    with _patched(fake):
        planned = first_touch.plan(_auto())
        report = first_touch.put_back(_auto(), older=True)
    assert planned["older_suspended"] == 0 and planned["older_tags"] == 1 and report["ok"]
    assert fake.notes[mine["note"]]["tags"] == ["Surasura::mine"]
    assert fake.notes[kyoto["note"]]["tags"] == []


def test_m14_a_review_started_after_the_flags_stops_the_tag_removals(tmp_path, monkeypatch):
    """K14: a review that starts after Junban's flags go back stops the tag removals — Surasura's tags stay on."""
    from modules.junban import ankiconnect
    fake, _original, _added = _touched(tmp_path)
    tagged = {word: _surasura_tags(fake, word) for word in ("須藤", "図書館", "冒険", "新幹線", "美術館")}
    assert any(tagged.values())
    real_set_flags = ankiconnect.set_flags

    def then_review(url, pairs, chunk=150):
        result = real_set_flags(url, pairs, chunk=chunk)
        fake.reviewing = True                               # the user starts a review right after the flags request
        return result

    monkeypatch.setattr(ankiconnect, "set_flags", then_review)
    with _patched(fake):
        report = first_touch.put_back(_auto())
    assert not report["ok"] and report["reviewing"]
    assert report["done"]["flags"] == 3 and report["done"]["tags_off"] == 0
    assert {word: _surasura_tags(fake, word) for word in tagged} == tagged


def test_m15_another_languages_recorded_deck_does_not_stand_the_automatic_reorder_aside(tmp_path):
    """D7 (M15): the recorded (language, deck) pair stands the automatic re-order aside only when the pair is this
    language's (or names none) — a Chinese pair never holds the Japanese run's TheBank."""
    fake, _original, _added = _touched(tmp_path)
    with _patched(fake):
        ours = first_touch.plan(_auto(junban_replan_deck="TheBank", junban_replan_language="ja"))
        theirs = first_touch.plan(_auto(junban_replan_deck="TheBank", junban_replan_language="zh"))
    assert ours["stands_aside"] == "TheBank"
    assert theirs["stands_aside"] is None


def test_m16_backfills_automatic_step_that_is_off_is_never_switched_off(tmp_path):
    """M16 (C16): with Backfill's automatic step OFF, the plan names no fill and the put-back changes no setting —
    even for the deck Backfill filled; nothing is switched off that was never on."""
    fake = _fill_fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ"))
    with _patched(fake):
        assert backfill.run(_fill_settings(junban_backfill_deck="TheBank"), _Session())["ok"]
        off = _fill_settings(junban_auto_backfill=False, junban_backfill_deck="TheBank")
        plan = first_touch.plan(off)
        report = first_touch.put_back(off, fields=True)
    assert plan["backfill_fills"] is None
    assert report["ok"] and report["done"]["fields"] == 2
    assert report["settings_changed"] == []


def test_m17_a_backfill_subdeck_inside_a_put_back_deck_overlaps_it():
    """C16: Backfill's automatic deck overlaps a deck whose fields come back when either holds the other — here
    Backfill's TheBank::文法 is a subdeck of TheBank, the deck Backfill filled, so the automatic step goes off."""
    fake = _fill_fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ"))
    with _patched(fake):
        assert backfill.run(_fill_settings(junban_backfill_deck="TheBank"), _Session())["ok"]
        under = first_touch.plan(_fill_settings(junban_auto_backfill=True, junban_backfill_deck="TheBank::文法"))
    assert under["backfill_fills"] == "TheBank::文法"


def test_m18_a_put_back_cut_short_leaves_the_unfinished_snapshot_unfinished(tmp_path):
    """C9: a put-back that is cut short does not mark Junban's unfinished snapshot complete; pressed again, it does."""
    fake, _original, _added = _touched(tmp_path)
    undo.save({_card_of(fake, "冒険")["cardId"]: 1}, ["TheBank"])
    fake.fail_write_chunk = fake.write_chunks + 1
    with _patched(fake):
        cut = first_touch.put_back(_auto(junban_chunk_size=2))
    assert not cut["ok"]
    assert undo.load("ja")["complete"] is False
    fake.fail_write_chunk = None
    with _patched(fake):
        assert first_touch.put_back(_auto(junban_chunk_size=2))["ok"]
    assert undo.load("ja")["complete"] is True


def test_m19_a_snapshot_over_a_deck_the_record_lacks_stays_unfinished(tmp_path):
    """C9: a snapshot taken for two decks is superseded only when the record holds both — "TheBank" alone
    leaves it unfinished."""
    fake, _original, _added = _touched(tmp_path)
    undo.save({1789712099999: 10}, ["TheBank", "Kaishi 1.5k"])     # two decks, one of them not in the record
    assert undo.load("ja")["complete"] is False
    with _patched(fake):
        assert first_touch.put_back(_auto())["ok"]
    assert undo.load("ja")["complete"] is False


def test_m20_a_put_back_with_no_fields_leaves_backfills_unfinished_snapshot_unfinished(tmp_path):
    """C9: a put-back with no fields leaves Backfill's unfinished snapshot unfinished; its own Restore is
    the way back."""
    fake, _original, _added = _touched(tmp_path)
    note_id = str(_card_of(fake, "冒険")["note"])
    undo.save([], ["TheBank"], fields={note_id: {"Patterns": {"before": "", "after": "<div>x</div>"}}}, kind="backfill")
    with _patched(fake):
        assert first_touch.put_back(_auto())["ok"]
    assert undo.load("ja", kind="backfill")["complete"] is False


def test_m21_a_restore_that_sets_a_card_aside_again_journals_the_tag_it_went_with(tmp_path):
    """K3: a Restore's re-suspend line carries the tag it went with, so a later put-back can find and undo it."""
    cards, notes, _ = _collection(["須藤"], dues=[5000])
    fake = PutBackCollection(cards, notes)
    with _patched(fake):
        first_touch.restored("ja", URL, {}, ["TheBank"], suspended=[1789712080003], with_tag=LATER_TAG)
    assert _last("restore")["with_tag"] == LATER_TAG
    assert first_touch._state(first_touch.journal("ja"))["suspended"] == {1789712080003: LATER_TAG}


def test_m22_an_order_file_that_cant_be_written_refuses_the_run_even_when_started_was_kept(tmp_path, monkeypatch):
    """D2: a run whose order file can't be written writes nothing, even though `started.json` was kept before it."""
    fake = _backlog(tmp_path)
    first_touch.started("ja")
    assert os.path.exists(os.path.join(first_touch.folder("ja"), first_touch.STARTED))

    def fail(path, payload):
        raise OSError("access denied")

    monkeypatch.setattr(first_touch, "_create_once", fail)
    with _patched(fake):
        report = reposition.run(_auto())
    assert not report["ok"] and "access denied" in report["problems"][0]
    assert fake.writes == [] and fake.suspend_calls == [] and fake.tag_calls == [] and fake.flag_writes == []
    assert undo.load("ja") is None and first_touch.journal("ja") == []


def test_m24_a_job_whose_recorded_deck_now_names_another_deck_stands_aside(deck, tmp_path, monkeypatch):
    """C1: the recorded deck setting now names another deck, so an automatic job that waited on the Anki-write lock
    writes nothing, asks Anki nothing, and stands aside (`stands_aside`), as it does when the pair is gone."""
    from app import anki_connect, settings_manager
    _save_settings(tmp_path, junban_replan_deck="TheBank", junban_replan_language="ja", junban_deck="TheBank",
                   enable_junban=True)
    settings = _settings(junban_replan_deck="TheBank", junban_replan_language="ja")
    with _patched(deck):
        assert reposition.run(settings, job=spaced.Job(automatic=True, cards=reposition.CardMap()))["ok"]
    real_take = anki_connect.take_writer

    def another_deck_held_it_first(*args, **kwargs):
        held = real_take(*args, **kwargs)
        settings_manager.save_keys({"junban_replan_deck": "Kaishi 1.5k"})          # the recorded deck, moved on
        return held

    monkeypatch.setattr(anki_connect, "take_writer", another_deck_held_it_first)
    deck.cards[min(deck.cards)]["due"] = 1                                       # something the job would re-order
    deck.requests.clear()
    writes = list(deck.writes)
    with _patched(deck):
        report = reposition.run(settings, job=spaced.Job(automatic=True, cards=reposition.CardMap()))
    assert not report["ok"] and report["stands_aside"] is True and report["problems"]
    assert deck.writes == writes and deck.requests == []


def test_m25_a_restore_journals_no_flag_anki_refused(tmp_path, monkeypatch):
    """FT D4: a Restore whose flag writes Anki refuses journals no flags — only the flags that landed."""
    fake = _backlog(tmp_path)
    with _patched(fake):
        assert reposition.run(_auto())["ok"]
        asked = []

        def refuse(url, pairs, chunk=150):
            asked.extend(pairs)
            return [], [(card, "refused") for card, _flag in pairs]

        monkeypatch.setattr("modules.junban.ankiconnect.set_flags", refuse)
        reposition.restore(_auto())
    # the restore must really have asked Anki for flags, or the empty journal line below proves nothing
    assert asked, "the Restore never asked Anki for a flag"
    line = _last("restore")
    assert line is not None and not line.get("flags")


def test_m26_a_journal_line_that_cant_be_written_raises_and_leaves_no_snapshot_behind(tmp_path, monkeypatch):
    """D4: undo.save journals before it writes the snapshot, so a journal that fails leaves no snapshot
    (and no temporary)."""
    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(first_touch, "note", fail)
    with pytest.raises(OSError):
        undo.save({1789712080001: 2801}, ["TheBank"], suspended=[1789712080001], profile="DevTest")
    assert undo.load("ja") is None
    assert not os.path.exists(undo.snapshot_path("ja")) and not os.path.exists(undo.snapshot_path("ja") + ".tmp")


def test_m27_a_returning_words_unsuspended_cards_are_journalled():
    """D4: a returning word's unsuspend is journalled as `unsuspended`, so a put-back never takes Junban's
    earlier suspend of that card as still standing (K3)."""
    undo.save({1789712080005: 2805}, ["TheBank"], unsuspended=[1789712080005], profile="DevTest")
    line = _last()
    assert line["unsuspended"] == [1789712080005]


def test_m28_a_named_backfill_run_journals_the_field_it_fills(tmp_path):
    """K8: a named run (Connect's Backfill) journals each field it fills, with its before text."""
    pair = _lapis(0, "探検", "たんけん")
    note_id = pair[0]["noteId"]
    fake = _fill_fake(pair)
    with _patched(fake):
        report = backfill.run_named(_fill_settings(junban_backfill_deck="TheBank"), _Session(), [note_id],
                                    run_id="backfill-20261014-100000-000")
    assert report["ok"] and report["filled"] == [note_id]
    assert fake.notes[note_id]["fields"]["Patterns"]["value"] == FIELD["探検"]
    line = _last("backfill")
    assert line is not None and line["fields"][str(note_id)]["Patterns"] == {"before": "", "after": FIELD["探検"]}


def test_m23_a_reorder_journals_the_frequency_field_it_writes_with_its_old_and_new_value(touchup_backlog):
    """K8: a 順 run that writes a note's Frequency field journals it (before and after) in its own reorder line."""
    with _patched(touchup_backlog):
        report = reposition.run(_settings(junban_write_frequency=True))
    assert report["ok"] is True
    written = touchup_backlog.notes[FIRST_NOTE]["fields"]["Frequency"]["value"]
    assert written != JPDB, "the run wrote no Frequency entry, so there is nothing to journal"
    filled = [line for line in first_touch.journal("ja") if line.get("kind") == "reorder" and line.get("fields")]
    assert filled, "the reorder wrote a field and journalled nothing"      # its tag line comes after, from undo.save
    assert filled[0]["fields"][str(FIRST_NOTE)]["Frequency"] == {"before": JPDB, "after": written}

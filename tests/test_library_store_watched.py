"""W-1, the list side (K-W1; Sonic 2026-10-22): a watched episode steps its words back — ONE rule in the store.

An item counts (Generate's files, the Rarity preview's sums, the mine line, the Generate button) when its tier is
analysed and it isn't watched, or the library's own option `keep_watched` is on (absent = off). `library_store.counts`
and `counts_sql` are that rule, once each; every reader goes through them.

What a wrong answer would cost a learner:
  * a stone that moves nothing (the words of an episode he has watched stay up front), or one that moves the list
    without telling the journey (no Generate follows: the list and Anki's order stay stale);
  * a stone in Finished, in New arrivals or with the option on that starts a needless Generate;
  * read-only mode or a library rebuilt from its copy counting a different list from the store's;
  * a show put back from Finished that brings none of its words back (Q1 A: its stones clear, one Undo puts both back);
  * a watched file falling out of every text list (its sentences and its names' evidence lost).

Every test runs for Japanese and Chinese alike under the per-test SURASURA_TEST_ROOT, on libraries named with real
words from tests/Test Resources/ (the token store's test reads real subtitles and texts).
"""
import os
import sqlite3
from unittest.mock import patch

import pytest

from app import indexer, library_store as ls, sentence_corpus as sc, token_index as ti
from tests.test_library_store_commands import _events, _four_in_two, _last_log
from tests.test_library_store_groups import _library as _grouped_library, _members, _shows
from tests.test_library_store_support import LANGUAGES, migrated, pieces_ok, read_doc, roots
from tests.test_token_store_kept import _everything_counted, _library as _real_library, _run_indexer


def _scheduled(store):
    """Every path Generate would read, in its order."""
    return [e["physical_path"] for rows in store.schedule().values() for e in rows]


def _rel(store, item_id):
    return store.item(item_id)["rel_path"]


def _mark_raw(store, ids, value=1):
    """A watched mark written as build 2 wrote it: the column only, no `keep_watched` in meta (Q3)."""
    with store._writing():
        store.conn.executemany("UPDATE items SET watched = ? WHERE id = ?", [(value, i) for i in ids])


# --- the one rule ----------------------------------------------------------------------------------------------- #

def test_the_rule_reads_tiers_marks_and_the_option():
    """The truth table: only an analysed tier counts; a watched mark counts there only with the option on."""
    for tier in ls.ANALYSED:
        assert ls.counts(tier, 0, False) and ls.counts(tier, 0, True)
        assert not ls.counts(tier, 1, False) and ls.counts(tier, 1, True)
    for tier in ("graduated", "arrivals"):
        assert not any(ls.counts(tier, w, k) for w in (0, 1) for k in (False, True))


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_sql_rule_is_the_python_rule_for_every_tier_mark_and_option(language):
    """`counts_sql` picks exactly the rows `counts` does, on a real store's items table holding every tier marked and
    unmarked (as the tier CHECK is held equal to TIERS) — with and without a table alias."""
    store = migrated(language)
    goal = store.ids("goal")
    store.finish(goal[:2])
    store.set_tier(goal[2:4], "arrivals")
    rows = store.conn.execute("SELECT id, tier FROM items ORDER BY id").fetchall()
    _mark_raw(store, [i for n, (i, _t) in enumerate(rows) if n % 2])
    rows = store.conn.execute("SELECT id, tier, watched FROM items").fetchall()
    assert {(t, w) for _i, t, w in rows} == {(t, w) for t in ls.TIERS for w in (0, 1)}, "every case is in the table"
    for keep in (False, True):
        python = {i for i, t, w in rows if ls.counts(t, w, keep)}
        sql = {r[0] for r in store.conn.execute(f"SELECT id FROM items WHERE {ls.counts_sql(keep)}")}
        aliased = {r[0] for r in store.conn.execute(f"SELECT i.id FROM items i WHERE {ls.counts_sql(keep, 'i')}")}
        assert sql == python == aliased and python
    store.close()


# --- a stone in Current ----------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_watched_episode_leaves_the_list_and_un_marking_or_undo_brings_it_back_each_bumping_the_order(language):
    """A stone in Current takes its file out of Generate's list and bumps `order_version` (the journey's Generate and
    the re-plan follow) — a status write otherwise: `changed_in` and the pins untouched. Un-marking it, or one Undo,
    puts it back in its own place, bumping again."""
    store = migrated(language)
    ep = store.ids("now")[1]
    before, v = _scheduled(store), store.versions()
    changed_in = store.item(ep)["changed_in"]
    change = store.set_watched([ep])
    after = store.versions()
    assert _rel(store, ep) not in _scheduled(store)
    assert [p for p in before if p != _rel(store, ep)] == _scheduled(store), "nothing else moves"
    assert after["order_version"] == v["order_version"] + 1 and after["state_version"] == v["state_version"] + 1
    assert after["pins_version"] == v["pins_version"] and store.item(ep)["changed_in"] == changed_in
    assert store.journey_pending()
    store.undo(change)
    assert _scheduled(store) == before and store.versions()["order_version"] == v["order_version"] + 2
    store.set_watched([ep])
    assert store.set_watched([ep], False) is not None                  # un-marked by its stone
    assert _scheduled(store) == before and store.versions()["order_version"] == v["order_version"] + 4
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_mark_in_finished_in_new_arrivals_or_with_the_option_on_is_a_status_write(language):
    """Nothing that counts moves: no `order_version` bump (no Generate), the list unchanged; nor does its undo."""
    store = migrated(language)
    goal = store.ids("goal")
    store.finish([goal[0]])
    store.set_tier([goal[1]], "arrivals")
    store.set_library_options(keep_watched=True)
    ep = store.ids("soon")[0]
    before, order = _scheduled(store), store.versions()["order_version"]
    changes = [store.set_watched([goal[0]]), store.set_watched([goal[1]]), store.set_watched([ep])]
    assert all(c is not None for c in changes)
    assert _scheduled(store) == before and _rel(store, ep) in before, "the option on: a watched episode counts"
    for change in reversed(changes):
        store.undo(change)
    assert store.versions()["order_version"] == order
    assert store.set_watched([goal[2]], False) is None, "a no-op writes nothing"
    store.close()


# --- the option ------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_option_is_off_when_absent_and_bumps_the_order_only_when_a_watched_item_sits_in_an_analysed_tier(language):
    """`set_library_options(keep_watched=)`: absent is off (setting it off writes nothing); flipped with no watched
    item in Current or 6+ Months — none at all, or only in Finished — a status write; with one there, one bump each way
    (the flip and its undo), and the feed's options carry it."""
    store = migrated(language)
    assert "keep_watched" not in store.meta() and store.read_feed()["options"]["keep_watched"] == 0
    assert store.set_library_options(keep_watched=False) is None
    order = store.versions()["order_version"]
    on = store.set_library_options(keep_watched=True)
    assert on is not None and store.read_feed()["options"]["keep_watched"] == 1
    store.undo(on)
    assert "keep_watched" not in store.meta(), "its undo puts it back to absent"
    done = store.ids("goal")[0]
    store.finish([done])
    order = store.versions()["order_version"]
    store.set_watched([done])
    store.set_library_options(keep_watched=True)
    store.set_library_options(keep_watched=False)
    assert store.versions()["order_version"] == order, "a watched item in Finished: nothing that counts moves"
    ep = store.ids("soon")[2]
    store.set_watched([ep])
    order = store.versions()["order_version"]
    on = store.set_library_options(keep_watched=True)
    assert store.versions()["order_version"] == order + 1 and _rel(store, ep) in _scheduled(store)
    store.undo(on)
    assert store.versions()["order_version"] == order + 2 and _rel(store, ep) not in _scheduled(store)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_stones_marked_before_the_option_existed_count_as_watched_from_the_first_start(language):
    """Q3 A: a library whose episodes build 2 marked watched (no `keep_watched` in its meta) reads them as not counting
    at once — out of Generate's list, aside in the text lists, off the mine line."""
    store = migrated(language)
    now = store.ids("now")
    _mark_raw(store, now[:2])
    assert "keep_watched" not in store.meta()
    scheduled = _scheduled(store)
    counted, _kept, aside = store.text_lists()
    for item_id in now[:2]:
        assert _rel(store, item_id) not in scheduled and _rel(store, item_id) not in counted
        assert _rel(store, item_id) in aside
        assert item_id not in store._mine_ids(5)
    store.close()


# --- the readers ------------------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_text_lists_set_watched_files_aside_and_never_drop_one(language):
    """(counted, kept, aside): a watched file of Current (a missing one too: watched wins over "a missing item keeps
    counting") is aside, never counted; a watched file in Finished is kept, as Finished is; every item is in exactly
    one list. With the option on, nothing is aside. Counted is Generate's list."""
    store = migrated(language)
    data_dir, _u = roots(language)
    now, soon, goal = store.ids("now"), store.ids("soon"), store.ids("goal")
    os.remove(os.path.join(data_dir, _rel(store, soon[0])))
    store.sync_disk()
    assert store.item(soon[0])["availability"] == "missing"
    store.finish([goal[0]])
    store.set_watched([now[0], soon[0], goal[0]])
    counted, kept, aside = store.text_lists()
    assert set(aside) == {_rel(store, now[0]), _rel(store, soon[0])} and _rel(store, goal[0]) in kept
    every = [r[0] for r in store.conn.execute("SELECT rel_path FROM items")]
    assert sorted(counted + kept + aside) == sorted(every), "each file in exactly one list"
    assert set(counted) == set(_scheduled(store))
    store.set_library_options(keep_watched=True)
    counted, kept, aside = store.text_lists()
    assert aside == [] and {_rel(store, now[0]), _rel(store, soon[0])} <= set(counted)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_mine_line_skips_what_doesnt_count(language):
    """A watched episode at the top of Current has nothing left to mine: the line takes the next one, and Connect's log
    says so (it left, the next entered); the option on, it is back."""
    store = migrated(language)
    store.register_reader("connect")
    now = store.ids("now")
    top = store._mine_ids(3)
    assert top == now[:3]
    line = store._mine_ids(ls.MINE_LINE_DEFAULT)                       # the library's own line, as the log reads it
    mark = _last_log(store)
    store.set_watched([now[0]])
    assert store._mine_ids(3) == now[1:4]
    (came,) = set(store._mine_ids(ls.MINE_LINE_DEFAULT)) - set(line)
    assert sorted(e[:2] for e in _events(store, mark)) == sorted([(now[0], "left_mine_line"),
                                                                  (came, "entered_mine_line")])
    store.set_library_options(keep_watched=True)
    assert store._mine_ids(3) == top
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_current_file_watched_is_an_empty_list_and_no_generate_button(language):
    """K21's empty run: every file of Current watched leaves Generate nothing to read, as all-Finished does today; the
    option on, all of it counts again."""
    store = migrated(language, tiers=("now", "soon"))
    store.set_watched(store.ids("now") + store.ids("soon"))
    assert _scheduled(store) == [] and store.has_content() is False
    assert store.text_lists()[0] == []
    store.set_library_options(keep_watched=True)
    assert len(_scheduled(store)) == len(store.ids("now") + store.ids("soon")) and store.has_content() is True
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_watched_episode_of_a_group_leaves_alone_and_the_group_stays_whole(language):
    """The rule is per file, never per row or piece: one episode of a user-made group watched leaves the list; its
    group keeps every member, in order."""
    store = _grouped_library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    store.set_watched([mb[1]])
    scheduled = _scheduled(store)
    assert _rel(store, mb[1]) not in scheduled and all(_rel(store, i) in scheduled for i in ma + mb if i != mb[1])
    assert _members(store, pa) == ma + mb and pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_read_only_mode_reads_the_same_list_as_the_store_from_the_copy(language):
    """Read-only mode (the copy alone) reads the rule from the copy's own records and meta: the same list as the store,
    option off and on; a watched file is never walked back in as untracked."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    now, goal = store.ids("now"), store.ids("goal")
    store.finish([goal[0]])
    store.set_watched([now[1], goal[0], goal[3]])
    for keep in (False, True):
        store.set_library_options(keep_watched=keep)
        assert ls.export_copy(store)
        copy = ls.read_only_schedule(language, data_dir, user_files_dir)
        assert {k: [ls._strip(e["physical_path"]) for e in copy[k]] for k in store.schedule()} == \
               {k: [e["physical_path"] for e in rows] for k, rows in store.schedule().items()}, keep
    assert read_doc(user_files_dir)["surasura_library"]["meta"]["keep_watched"] == 1
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("keep", [None, True])
def test_the_option_and_the_stones_come_back_through_a_rebuild(language, keep):
    """The copy carries `keep_watched` when the store holds it (`COPY_META_KEYS`) and every stone in its records: a
    library rebuilt from it (a new PC) counts the same list; never set, it comes back absent (off)."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.set_watched([store.ids("now")[0], store.ids("soon")[1]])
    if keep:
        store.set_library_options(keep_watched=True)
    before = _scheduled(store)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    db = store.db_path
    store.close()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + ".elsewhere")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.meta().get("keep_watched") == (1 if keep else None)
    assert _scheduled(store) == before
    store.close()


# --- Put back from Finished (Q1 A) ------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("how", ["put_back", "move", "set_tier", "join"])
def test_leaving_finished_clears_the_stones_and_one_undo_puts_back_the_stones_and_the_show(language, how):
    """Q1 A: anything leaving Finished — *Put back*, a drag into Current, Promote / Demote, a part joined onto its show —
    clears the stones of what it brings back, so its words return at the next Generate; recorded on the same change, so
    one Undo puts the show back in Finished with its stones."""
    store = migrated(language)
    if how == "join":
        members, first, second = _four_in_two(store)
        back = members[2:]
    else:
        back = [i for i in store.ids("soon") if store.item(i)["parent_folder"]][:3]
    store.finish(back)
    store.set_watched(back)
    assert all(store.item(i)["tier"] == "graduated" and store.item(i)["watched"] == 1 for i in back)
    change = {"put_back": lambda: store.put_back_finished(back),
              "move": lambda: store.move(back, "now"),
              "set_tier": lambda: store.set_tier(back, "soon"),
              "join": lambda: store.join([first, second])}[how]()
    assert all(store.item(i)["watched"] == 0 for i in back)
    assert all(_rel(store, i) in _scheduled(store) for i in back), "its words come back"
    store.undo(change)
    assert all(store.item(i)["tier"] == "graduated" and store.item(i)["watched"] == 1 for i in back)
    store.close()


# --- the token store's lists (K-W2: set aside) ------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_indexer_sets_a_watched_file_aside_and_un_marking_brings_it_back_with_no_tokenizing(language, tmp_path):
    """The indexer hands the token store the set-aside list: a stone moves the episode out of every count — the counts,
    phrases and cut-off a Finished file leaves — keeps the name tables as they were, and tokenizes nothing; un-marked
    (or with Keep studying watched episodes on) it counts again, exactly as before, still with nothing tokenized."""
    store, data_dir, ids = _real_library(language)
    _run_indexer(language)
    with ti.open_store(language) as tokens:
        reference = _everything_counted(tokens, language)
    watched = list(ids)[0]
    store.set_watched([ids[watched]])
    files = [os.path.join(data_dir, p) for p in _scheduled(store)]
    assert ti._norm(watched) not in {ti._norm(p) for p in files}
    counted, more = indexer.token_store_lists(language, data_dir, files)
    assert ti._norm(watched) not in {ti._norm(p) for p in counted}
    assert [ti._norm(p) for p in more["aside"]] == [ti._norm(watched)] and watched not in more["kept"]
    finished = ti.open_store(language, path=str(tmp_path / "finished.db"))
    finished.reconcile(counted, ti.make_tokenizer(language), kept=[watched])
    tokenized, real = [], ti._tokenized

    def spy(paths, tokenize_file, workers):
        tokenized.extend(paths)
        return real(paths, tokenize_file, workers)

    with patch.object(ti, "_tokenized", spy):
        _run_indexer(language)
        with ti.open_store(language) as tokens:
            now = _everything_counted(tokens, language)
            assert tokens.aside_files() == [ti._norm(watched)]
            assert now.pop("names") == reference["names"], "a stone never changes the name tables"
            alone = _everything_counted(finished, language)
            alone.pop("names")
            assert now == alone, "set aside: every count a Finished file leaves"
        store.set_watched([ids[watched]], False)
        _run_indexer(language)
        with ti.open_store(language) as tokens:
            assert _everything_counted(tokens, language) == reference and tokens.aside_files() == []
        store.set_watched([ids[watched]])
        store.set_library_options(keep_watched=True)
        _run_indexer(language)
        with ti.open_store(language) as tokens:
            assert _everything_counted(tokens, language) == reference and tokens.aside_files() == []
    assert tokenized == [], "no move re-tokenizes"
    store.close()
    finished.close()


# --- the sentence sources (K-W3: counted + set aside) ----------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_watched_episode_still_gives_sentences_and_a_finished_show_none(language, tmp_path):
    """A stone never takes a sentence away: 例文 (`best_for`) and the sentence dictionary (`build`) still pick a watched
    episode's sentences — the dictionary right after the stone, before the indexer, its row set aside with nothing
    tokenized — while a Finished show's stay out, as ever. With Keep studying watched episodes on, 例文 is exactly what it
    was before the stone."""
    store, _data_dir, ids = _real_library(language)
    _run_indexer(language)
    watched, finished = list(ids)[0], list(ids)[2]
    with ti.open_store(language) as tokens:
        cached = {p: tokens.file_tokens(p) for p in ids}

    def only(path):
        """The sentences no other file holds."""
        return {s for s, _t in cached[path]} - {s for p in ids if p != path for s, _t in cached[p]}

    wanted = {(t[0], t[1]) for p in (watched, finished) for _s, toks in cached[p] for t in toks}

    def picked():
        return {text for found in sc.best_for(language, wanted).values() for _o, text, _s, _f in found}

    before = sc.best_for(language, wanted)
    assert only(watched) & picked() and only(finished) & picked(), "both files give sentences before"
    store.set_library_options(keep_watched=True)
    store.set_watched([ids[watched]])
    assert sc.best_for(language, wanted) == before, "Keep studying watched episodes: as before the stone"

    store.set_library_options(keep_watched=False)
    store.finish([ids[finished]])
    dictionary, tokenized = [], []
    real_export, real_tokenized = sc.export_dictionary, ti._tokenized

    def export(words, sources, *args, **kwargs):
        dictionary.extend(text for w in words.values() if w.best is not None for _r, text, _f, _s in w.best.result())
        return real_export(words, sources, *args, **kwargs)

    def spy(paths, tokenize_file, workers):
        tokenized.extend(paths)
        return real_tokenized(paths, tokenize_file, workers)

    with patch.object(sc, "export_dictionary", export), patch.object(ti, "_tokenized", spy):
        assert sc.build(language, str(tmp_path / "corpus.zip"), progress=lambda message: None)
    assert only(watched) & set(dictionary), "the sentence dictionary keeps a watched episode's sentences"
    assert not only(finished) & set(dictionary), "and leaves a Finished show's out"
    assert tokenized == [], "the stone re-tokenizes nothing"
    with ti.open_store(language) as tokens:
        assert tokens.aside_files() == [ti._norm(watched)], "its row set aside, never dropped"
    assert only(watched) & picked(), "例文 still picks a watched episode's sentence"
    assert not only(finished) & picked(), "and never a Finished show's"
    store.close()

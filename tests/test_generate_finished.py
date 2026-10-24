"""Finished is reference, as a watched episode is — and a run reads it (W-1b; Sonic 2026-10-23: watched = reference
"exactly as Finished").

A Finished file is never counted, but its text is the name tables' evidence and a sentence source, so it is part of
what a run reads: the run signature's "reference" part holds every set-aside file (`library_store.sets_aside`:
Finished, and the watched episodes while *Keep studying watched episodes* is off), the store's and read-only mode's
alike. What these prove, with Generate run as the dashboard starts it (`analyzer.py`, its own process):

  - a finished show imported whose text joins a name: `order_version` moves (the journey asks for its Generate) and
    Generate runs — the name is listed whole, its one use ahead; before this, Generate skipped and the list kept the
    name in pieces while the Rarity slider counted it whole;
  - a Finished file added or edited: Generate runs; nothing moved, or a Finished row only moved inside Finished (and
    its Undo): no order bump, Generate skips;
  - the store and its read-only copy list the same set-aside files (a video still waiting for its subtitle in neither);
  - a real Generate with one show Finished — its words are on the list with none of its
    uses, exactly; a name only it keeps whole stays whole (Japanese: Chinese has no library name tables); 例文 can
    pick its sentence; the drag's Undo gives the list back byte for byte.

What a wrong answer would cost a learner: a finished show imported to keep a sequel's character names whole, and the
list still splitting them into fake words until some unrelated change; or a Generate for nothing at every tidy-up
inside Finished. Japanese and Chinese alike, under the per-test SURASURA_TEST_ROOT, from real lines in
tests/Test Resources/ and the bundled samples.
"""
import os
import shutil
from collections import Counter

import pytest

from app import analyzer, library_store as ls, sentence_corpus as sc, token_index as ti
from tests.test_finished_reference import FINISHED, _library_words
from tests.test_generate_watched import (EDIT, FOLDERS, REUSED, SEEDS, SHOWS, _example_sentences, _generate,
                                         _occurrences, _plan_uses, _read, _token_store, _uses, _with_line)
from tests.plan_file_cases import _split_lines, _split_srt
from tests.test_library_store_support import LANGUAGES, entry, migrated, roots, write_manifest
from tests.test_token_store_aside import NAME, NAME_LINES, _cues, _show, _srt, _surfaces
from tests.test_token_store_kept import _library as _six_files, _run_indexer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME_AHEAD = "メロンベンチでまた会おうね。"      # the name's one use in the episode ahead


def _rel(data_dir, path):
    return os.path.relpath(path, data_dir).replace("\\", "/")


def _into_finished(language, show="終わった作品", sources=None):
    """Real files of FINISHED copied into Graduated/<show>/ (where the Finished importer copies): their paths."""
    data_dir, _u = roots(language)
    out = []
    for source in sources or FINISHED[language]:
        path = os.path.join(data_dir, ls.GRADUATED_FOLDER, show, os.path.basename(source))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copy2(os.path.join(REPO, *source.split("/")), path)
        out.append(path)
    return out


def _shows(language, names=False):
    """test_generate_watched's library — Show A Ep01–03 then Show B Ep01–03 in NOW, cut from the bundled samples, W_only
    seeded in A-Ep01 and W_later in A-Ep01 and B-Ep03 — and, with `names` (Japanese), the recurring name once in each
    of A's episodes and once in B-Ep01: (store, {name: path}, {name: item id})."""
    data_dir, user_files_dir = roots(language)
    (_only, only_line), (_later, later_a, later_b) = SEEDS[language]
    a_src, b_src = SHOWS[language]
    a_sub = a_src.endswith(".srt")
    a_eps = _split_srt(_read(a_src), 3) if a_sub else _split_lines(_read(a_src), 3)
    b_eps = _split_lines(_read(b_src), 3)
    a_eps[0] = _with_line(_with_line(a_eps[0], only_line, a_sub), later_a, a_sub)
    b_eps[2] = _with_line(b_eps[2], later_b, False)
    if names:
        a_eps = [_with_line(text, line, a_sub) for text, line in zip(a_eps, NAME_LINES)]
        b_eps[0] = _with_line(b_eps[0], NAME_AHEAD, False)
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    paths = {}
    for show, eps, ext in (("A", a_eps, ".srt" if a_sub else ".txt"), ("B", b_eps, ".txt")):
        folder = FOLDERS[language][show == "B"]
        for n, text in enumerate(eps, 1):
            rel = f"HighPriority/{folder}/ep0{n}{ext}"
            path = os.path.join(data_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            paths[f"{show}{n}"] = path
            doc["schedule"][ls.TIERS["now"][0]].append(entry(rel))
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    return store, paths, {name: store.item_id(_rel(data_dir, path)) for name, path in paths.items()}


# --------------------------------------------------------------------------- #
# 1. A Finished change is a run's change
# --------------------------------------------------------------------------- #
def test_a_finished_import_that_joins_a_name_makes_generate_run_and_lists_the_name_whole():
    """The six real Japanese files and a NOW episode holding the name once: Generated, the name isn't listed (in pieces).
    A finished show holding it once an episode is imported: the order moves (the journey's Generate follows), the
    index joins the name (the Rarity slider counts it whole, once) — and Generate runs and lists it whole, one use."""
    root = os.environ["SURASURA_TEST_ROOT"]
    store, data_dir, _ids = _six_files("ja")
    now_ep = os.path.join(data_dir, "HighPriority", "空の庭 続", "空の庭 続 第1話.srt")
    os.makedirs(os.path.dirname(now_ep), exist_ok=True)
    with open(now_ep, "w", encoding="utf-8", newline="\n") as f:
        f.write(_srt(_cues("phrases_sample.srt")[8:12] + [NAME_AHEAD]))
    store.insert([now_ep], "now")
    store.close()
    _generate(root, "ja")
    assert NAME not in {w for w, _r in _library_words(root, "ja")}, "in pieces: the episode alone is no evidence"
    _generate(root, "ja")

    store = ls.open_store("ja", data_dir, roots("ja")[1])
    order = store.versions()["order_version"]
    store.import_finished(_show(folder=f"{ls.GRADUATED_FOLDER}/空の庭/第1期"))
    assert store.versions()["order_version"] == order + 1 and store.journey_pending(), "the journey hears it"
    store.close()
    _run_indexer("ja")
    with ti.open_store("ja") as tokens:
        assert NAME in _surfaces(tokens, now_ep) and tokens.word_counts()[0].get((NAME, "")) == 1
    _raw, said = _generate(root, "ja", said=True)
    assert REUSED not in said, "the finished show is part of what the run reads: Generate runs"
    assert {uses for (w, _r), uses in _library_words(root, "ja").items() if w == NAME} == {1}, \
        "the list reads the name whole, as the Rarity slider does: its one use ahead"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_finished_file_added_or_edited_makes_generate_run_and_a_move_inside_finished_skips(language):
    """Generated twice: the second skips. A finished show imported: `order_version` +1, Generate runs. Nothing moved:
    skips. One Finished file moved above the other, and that move undone: no order bump, Generate skips (no run reads
    Finished's order). A Finished file edited (a real line added): Generate runs."""
    root = os.environ["SURASURA_TEST_ROOT"]
    store, _paths, _ids = _shows(language)
    data_dir = roots(language)[0]
    _generate(root, language)
    assert REUSED in _generate(root, language, said=True)[1]

    order = store.versions()["order_version"]
    show = _into_finished(language)
    store.import_finished(show)
    assert store.versions()["order_version"] == order + 1, "a Finished import moves what a run reads"
    assert REUSED not in _generate(root, language, said=True)[1], "a Finished file added: Generate runs"
    assert REUSED in _generate(root, language, said=True)[1], "nothing moved since: Generate skips"

    order = store.versions()["order_version"]
    first, second = (store.item_id(_rel(data_dir, p)) for p in show)
    change = store.move([second], "graduated", before_id=first)
    assert change is not None and store.ids("graduated")[:2] == [second, first], "the row moved"
    store.undo(change)
    assert store.ids("graduated")[:2] == [first, second]
    assert store.versions()["order_version"] == order, "a move inside Finished, and its Undo: no order bump"
    assert REUSED in _generate(root, language, said=True)[1], "and Generate skips"

    with open(show[0], encoding="utf-8") as f:
        text = f.read()
    with open(show[0], "w", encoding="utf-8", newline="") as f:
        f.write(_with_line(text, EDIT[language], False))
    assert REUSED not in _generate(root, language, said=True)[1], "a Finished file edited alone: Generate runs"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_what_changes_the_finished_files_bumps_the_order_once_and_nothing_else_does(language):
    """The store's order bumps for Finished, mirroring the watched marks': a Finished import (and its Undo) and a
    Finished item removed each bump `order_version` once; importing a file already Finished, a watched mark in
    Finished and Finished's own order (a move inside it) don't."""
    store = migrated(language)
    data_dir, _u = roots(language)
    show = _into_finished(language)
    v = lambda: store.versions()["order_version"]          # noqa: E731
    order = v()
    change = store.import_finished(show)
    assert v() == order + 1
    assert store.import_finished(show) is None and v() == order + 1, "already Finished: nothing"
    ids = [store.item_id(_rel(data_dir, p)) for p in show]
    store.set_watched([ids[0]])
    assert v() == order + 1, "a mark in Finished: set aside either way"
    store.undo(store.move([ids[1]], "graduated", before_id=ids[0]))
    assert v() == order + 1, "Finished's own order: no run reads it"
    store.undo(change)
    assert v() == order + 2 and not {store.item_id(_rel(data_dir, p)) for p in show} - {None}, "its Undo: once"
    change = store.import_finished(show)
    assert v() == order + 3
    ids = [store.item_id(_rel(data_dir, p)) for p in show]
    store.remove([ids[0]])
    assert v() == order + 4, "a Finished item removed: it leaves the set-aside files"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_store_and_read_only_mode_list_the_same_set_aside_files(language):
    """Finished items (one also watched), a watched NOW episode, and a Finished video still waiting for its subtitle:
    the store's set-aside list (`schedule(with_aside=True)`) and read-only mode's (the copy, `read_only_schedule`) hold
    the same files — Finished and the watched episode, the waiting video in neither (no text yet) — so both sign one
    "reference" part; with the option on, Finished alone."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    now, goal = store.ids("now"), store.ids("goal")
    store.finish(goal[:3])
    store.set_watched([now[1], goal[0]])
    with store._writing():
        store.conn.execute("UPDATE items SET availability = 'waiting' WHERE id = ?", (goal[2],))
    for keep in (False, True):
        store.set_library_options(keep_watched=keep)
        assert ls.export_copy(store)
        mine = store.schedule(with_aside=True)
        copy = ls.read_only_schedule(language, data_dir, user_files_dir, with_aside=True)
        listed = sorted(ls._strip(e["physical_path"]) for e in mine[ls.ASIDE])
        want = sorted(store.item(i)["rel_path"] for i in goal[:2] + ([] if keep else [now[1]]))
        assert listed == want, (keep, listed)
        assert sorted(ls._strip(e["physical_path"]) for e in copy[ls.ASIDE]) == listed, keep
        assert sorted(analyzer.aside_files(language, copy)) == sorted(analyzer.aside_files(language, mine)), keep
    store.close()


# --------------------------------------------------------------------------- #
# 2. The sentence dictionary and *What if I added it back?*
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_whose_every_show_is_finished_still_has_sentences_for_the_dictionary(language):
    """Every item finished: Generate lists nothing, but the sentence dictionary's "Add content first" check (Qt's
    window and the Tk dialog alike: `sentence_corpus.has_sources`) sees the set-aside files — reference gives
    sentences. An empty library still has none."""
    store = migrated(language)
    assert sc.has_sources(language), "a library with counted files"
    store.finish([i for tier in ls.ANALYSED for i in store.ids(tier)])
    store.close()
    assert not analyzer.resolve_found_files(language, verbose=False), "Generate lists nothing"
    assert sc.has_sources(language), "every show Finished: its sentences are still there to build from"
    try:
        from app.qt import sentence_dictionary_window as sdw
    except ImportError:                            # no Qt here: the Tk dialog's check is the same function
        sdw = None
    if sdw is not None:
        assert sdw.library_has_content(language)


def test_an_empty_library_has_no_sentences_for_the_dictionary():
    data_dir, user_files_dir = roots("ja")
    write_manifest(user_files_dir, {"schedule": {p: [] for p in ls.PHASES}})
    assert ls.maintain("ja", data_dir, user_files_dir) == ls.EXIT_DONE
    assert not sc.has_sources("ja")


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_sentence_dictionary_built_after_a_finished_item_is_removed_reads_nothing_again(language):
    """A Finished file indexed (set aside), then removed (its file to the trash: kept, text only): the sentence
    dictionary built then hands the token store the indexer's lists — the row stays, kept — so neither the build nor
    the next index reads the file again from the trash."""
    from tests.test_finished_reference import _spy_tokenizing
    from tests.test_token_store_kept import _remove
    store, data_dir, _ids = _six_files(language)
    show = _into_finished(language)
    store.import_finished(show)
    _run_indexer(language)
    _remove(store, data_dir, store.item_id(_rel(data_dir, show[0])), show[0])
    store.close()
    spy, tokenized = _spy_tokenizing()
    with spy:
        assert sc.build(language, os.path.join(roots(language)[1], "corpus.zip"), progress=lambda message: None)
        with ti.open_store(language) as tokens:
            assert ti._norm(show[0]) in tokens.kept_files(), "the removed Finished file's row stays, kept"
        _run_indexer(language)
    assert tokenized == [], "nothing read again from the trash"


def test_what_if_i_added_it_back_on_a_finished_row_counts_its_names_once():
    """The name met once in a NOW episode and once in a Finished episode: two uses, under the three a name needs, so
    the tables keep it in pieces. *What if I added it back?* on the Finished row: the file is the tables' evidence
    already (set aside), so adding it back changes no name — the names gate stays still (before, its record was
    added a second time: three uses, a name that joins, the estimate wrongly marked inexact)."""
    from tests.test_arrivals_worker import _Worker
    root = os.environ["SURASURA_TEST_ROOT"]
    store, data_dir, _ids = _six_files("ja")
    cues = _cues("placed_episode.srt")
    now_ep = os.path.join(data_dir, "HighPriority", "空の庭 続", "空の庭 続 第1話.srt")
    finished = os.path.join(data_dir, ls.GRADUATED_FOLDER, "空の庭", "空の庭 第1話.srt")
    for path, part, line in ((now_ep, cues[:4], NAME_AHEAD), (finished, cues[4:], NAME_LINES[0])):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_srt(part + [line]))
    store.insert([now_ep], "now")
    store.import_finished([finished])
    store.close()
    _generate(root, "ja")
    import json
    from tests.test_generate_watched import _child
    aside, joined = json.loads(_child(root, (                 # the token store Generate wrote, which the worker reads
        "import json; from app import token_index as ti; s = ti.open_store('ja'); "
        "print(json.dumps([s.aside_files(), sorted((s.names_tables() or {}).get('k') or {})], ensure_ascii=False)); "
        "s.close()")))
    assert ti._norm(finished) in aside and NAME not in joined, (aside, joined)
    worker = _Worker(root, "ja", ["--static", "--min-freq", "1"])
    try:
        answer = worker.ask({"id": 1, "op": "estimate", "path": finished})
    finally:
        worker.ask({"id": 2, "op": "quit"})
    assert "stale" not in answer["moved"], answer["moved"]
    assert "names" not in answer["moved"], answer["moved"]


# --------------------------------------------------------------------------- #
# 3. Finished enriches, never counts — a real Generate
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_one_show_finished_counts_none_of_its_uses_keeps_its_names_and_sentences_and_undo_gives_it_back(
        language, tmp_path):
    """Show A and Show B in NOW, Generated (Japanese: the recurring name once in each of A's three episodes and once in
    B-Ep01, so the library's table reads it whole). Show A dragged to Finished, Generated: W_only (met only in A) is
    off the list; W_later counts its B-Ep03 use alone; every word is the first run's count less Show A's uses exactly
    (the first run's per-file record), and each word the tokenizer counts as the list does is that less A's uses as
    the token store's own tokenizer counts them; Show A is set aside, never counted. Japanese: the name stays whole,
    one word with B-Ep01's one use — B alone reads it in pieces. 例文 still finds W_only's sentence in Show A. Undo
    of the drag: the list is the first run's, byte for byte."""
    root = os.environ["SURASURA_TEST_ROOT"]
    names = language == "ja"
    store, paths, ids = _shows(language, names=names)
    (only, _l), (later, _a, _b) = SEEDS[language]
    show_a = ["A1", "A2", "A3"]
    uses = _uses(language, paths)
    total = sum(uses.values(), Counter())

    first = _generate(root, language)
    listed = _occurrences(first)
    w_only, w_later = next(k for k in listed if k[0] == only), next(k for k in listed if k[0] == later)
    a_uses = sum((_plan_uses(root, language, paths[n]) for n in show_a), Counter())
    if names:
        assert {n for (w, _r), n in _library_words(root, "ja").items() if w == NAME} == {4}, "whole: A's 3, B's 1"
    tokens = _token_store(root, language)
    assert tokens[:2] == [6, 0], tokens

    change = store.finish([ids[n] for n in show_a])
    assert change is not None and store.journey_pending()
    finished = _occurrences(_generate(root, language))
    assert w_only not in finished, "a word met only in the finished show is off the list"
    assert finished[w_later] == uses["B3"][w_later], "W_later: its use ahead alone"
    assert finished == {key: n - a_uses[key] for key, n in listed.items() if n - a_uses[key]}, \
        "every word: the first run's count less Show A's uses, exactly"
    plain = [key for key, n in listed.items() if total[key] == n]
    assert len(plain) >= 0.9 * len(listed), len(plain)
    a_tokenized = sum((uses[n] for n in show_a), Counter())
    assert {key: a_uses[key] for key in plain} == {key: a_tokenized[key] for key in plain}, \
        "Show A's uses as the token store's own tokenizer counts them"
    after = _token_store(root, language)
    assert after[:2] == [3, 3], "Show A set aside: reference, never counted"
    assert after[2:] == tokens[2:], "the name tables byte for byte: Show A is still their evidence"

    if names:
        assert {n for (w, _r), n in _library_words(root, "ja").items() if w == NAME} == {1}, \
            "the name stays one word, its one use ahead"
        _run_indexer("ja")
        with ti.open_store("ja") as tokens_now:
            assert NAME in _surfaces(tokens_now, paths["B1"]), "read whole in B-Ep01"
        alone = ti.open_store("ja", path=str(tmp_path / "b_alone.db"))
        alone.reconcile([paths[n] for n in ("B1", "B2", "B3")], ti.make_tokenizer("ja"), ti.build_signature("ja"))
        assert NAME not in alone.names_tables()["k"], "without Show A the name is in pieces (the test can fail)"
        alone.close()

    with open(paths["A1"], encoding="utf-8") as f:
        episode = f.read()
    sentences = _example_sentences(root, language, w_only)
    assert sentences and all(text in episode for text in sentences), "例文 picks the finished show's sentence"

    store.undo(change)
    assert all(store.item(ids[n])["tier"] == "now" for n in show_a)
    assert _generate(root, language) == first, "the drag undone: the list is the first run's, byte for byte"
    store.close()

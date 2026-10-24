"""The journey's stones, the data half (Sonic 2026-10-23, "Yes include"; drill A2: "the journey shows A-Ep01 as
watched", and its step 6 end to end).

The report's per-file data (`globalData.progressive`, the journey's file list in order) names each episode's watched
mark, read from the library store in one read (`library_store.read_watched_marks`, `static_html_generator._journey_stones`):

  - a counted file that is watched (*Keep studying watched episodes* on): its entry as before plus `"watched": true`;
  - a watched file set aside (the option off): an entry IN ITS PLACE in the library's order, no counts —
    `{"filename", "watched": true, "aside": true, "words": [], "total_words": 0, "is_goal_content", "unlisted": []}` —
    its name at the same place in `file_order` (the inline Target Met order), never in `completed_files`;
  - no `watched` key: not watched. No stone, or no library store: the report is byte for byte what it was.
  - Finished stays out of the journey (its own view), stones or not.

A stone with the option on changes no run input, so the render signature carries the marks (`_stones_fingerprint`):
Generate re-renders and never re-analyses.

What a wrong answer would cost a learner: an episode he has watched vanishing from the journey (it looks lost, not
done), a stone that doesn't show until something else re-renders the report, or a stone left on an episode he put back.
Japanese and Chinese alike, under the per-test SURASURA_TEST_ROOT, with real text from the bundled samples.
"""
import json
import os
import re
import subprocess
import sys
from unittest.mock import patch

import pandas as pd
import pytest

from app import library_store as ls
from tests.plan_file_cases import _split_lines, _split_srt, child_env
from tests.test_generate_watched import SHOWS, _read
from tests.test_library_store_support import LANGUAGES, entry, migrated, roots, write_manifest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REUSED = "Nothing affecting the analysis changed"
# Real words from the bundled samples, for the hand-made lists of the fast tests
WORDS = {"ja": ("冒険", "図書館", "文化祭"), "zh": ("冒险", "夜市", "挑战")}


def _settings(language, **logic):
    """settings.json naming the report's language (the generator reads it there, as the dashboard has it)."""
    settings = {"target_language": language}
    if logic:
        settings["logic"] = logic
    with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)


def _payload(html):
    return json.loads(re.search(r"let globalData = (\{.*?\});\n", html, re.S).group(1))


def _report(root):
    with open(os.path.join(root, "results", "reading_list_static.html"), encoding="utf-8") as f:
        return _payload(f.read())


# --- the fast half: the generator on hand-made results over a real store ------------------------------------------ #

def _render(tmp_path, language, counted, theme="default", today=False):
    """Render a report whose progressive list holds one real word per file of `counted` (basenames, in order) and whose
    statistics name every one — `today`: with the stones step taken out, the report as it was before them. -> html."""
    results = tmp_path / "results"
    results.mkdir(exist_ok=True)
    word = WORDS[language]
    pd.DataFrame([{"Word": word[0], "Reading": "", "Tier": "Outside", "Score": 10, "Occurrences": 4,
                   "Count (High)": 1, "Count (Low)": 1, "Count (Goal)": 2, "Sources": counted[0],
                   "Context 1": f"{word[0]}{word[1]}。"}]
                 ).to_csv(results / "priority_learning_list.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"Sequence": i, "Source File": name, "Word": word[i % 3], "Reading": "", "Tier": "Outside",
                   "Score": 10, "Occurrences (Global)": 2, "Occurrences (File)": 2, "Count (High)": 0,
                   "Count (Low)": 0, "Count (Goal)": 2, "Context 1": f"{word[i % 3]}。"}
                  for i, name in enumerate(counted[:-1], 1)]       # the last file: every word known (Target Met)
                 ).to_csv(results / "progressive_learning_list.csv", index=False, encoding="utf-8-sig")
    with open(results / "file_statistics.json", "w", encoding="utf-8") as f:
        json.dump([{"File": name, "Total Words": 10, "Known Count": 9, "Coverage (%)": 90.0} for name in counted],
                  f, ensure_ascii=False)
    from app import static_html_generator as gen
    out = results / "reading_list_static.html"
    with patch.object(gen, "RESULTS_DIR", str(results)), \
            patch.object(gen, "PRIORITY_CSV", str(results / "priority_learning_list.csv")), \
            patch.object(gen, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")), \
            patch.object(gen, "OUTPUT_FILE", str(out)):
        if today:
            with patch.object(gen, "_journey_stones", lambda *a, **k: None):
                gen.generate_static_html(theme=theme, open_browser=False)
        else:
            gen.generate_static_html(theme=theme, open_browser=False)
    return out.read_text(encoding="utf-8")


def _now_names(store):
    return [os.path.basename(e["physical_path"]) for e in store.schedule()[ls.TIERS["now"][0]]]


@pytest.mark.parametrize("language", LANGUAGES)
def test_with_no_stone_or_no_store_the_report_is_byte_for_byte_what_it_was(language, tmp_path):
    # why: the stones must cost a library that has none nothing — not a byte of its report, and with no library store
    # (JSON mode) the reader gives nothing to place
    _settings(language)
    data_dir, user_files_dir = roots(language)
    assert ls.read_watched_marks(language, data_dir) is None, "no store: nothing to read"
    store = migrated(language)
    counted = _now_names(store)
    assert ls.read_watched_marks(language, data_dir) == [], "a store with no stone: nothing to place"
    assert _render(tmp_path, language, counted) == _render(tmp_path, language, counted, today=True)
    store.finish([store.ids("goal")[0]])
    store.set_watched([store.ids("graduated")[0]])
    assert ls.read_watched_marks(language, data_dir) == [], "a stone in Finished stays out of the journey"
    assert _render(tmp_path, language, counted) == _render(tmp_path, language, counted, today=True)
    store.close()
    with patch.object(ls, "STORE_LIVE", False):
        assert ls.read_watched_marks(language, data_dir) is None, "the store switched off: nothing to read"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_set_aside_stone_sits_in_its_place_with_no_counts_and_in_the_inline_order(language, tmp_path):
    # why: an episode the learner marked must show where it stands in his order — not vanish, and not be counted
    _settings(language, inline_completed_files=True)
    store = migrated(language)
    names = _now_names(store)
    second = store.ids("now")[1]
    store.set_watched([second])
    counted = [n for n in names if n != names[1]]
    data = _payload(_render(tmp_path, language, counted))
    shown = [e["filename"] for e in data["progressive"]]
    assert shown == [counted[0], names[1]] + counted[1:-1], "the stone in its place; the last file is Target Met"
    stone = data["progressive"][1]
    assert stone == {"filename": names[1], "watched": True, "aside": True, "words": [], "total_words": 0,
                     "is_goal_content": False, "unlisted": []}
    assert not any("watched" in e for e in data["progressive"] if e is not stone), "no other file is watched"
    assert data["file_order"] == [counted[0], names[1]] + counted[1:], "its name in the inline order, in its place"
    assert names[1] not in [f["filename"] for f in data["completed_files"]], "never Target Met"
    zen = _payload(_render(tmp_path, language, counted, theme="Zen Mode"))
    assert names[1] not in [e["filename"] for e in zen["progressive"]], "Zen shows no journey: no stone there"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_stone_on_a_6_months_episode_and_one_after_the_last_listed_file(language, tmp_path):
    # why: the 6+ chip follows the tier, and a stone after every counted file still has a place (the end)
    _settings(language)
    store = migrated(language)
    goal = store.ids("goal")
    store.set_watched([goal[-1]])
    order = [os.path.basename(e["physical_path"]) for tier in ls.ANALYSED for e in store.schedule()[ls.TIERS[tier][0]]]
    assert os.path.basename(store.item(goal[-1])["rel_path"]) not in order, "set aside: off Generate's list"
    data = _payload(_render(tmp_path, language, order))
    last = data["progressive"][-1]
    assert last["filename"] == os.path.basename(store.item(goal[-1])["rel_path"])
    assert last["aside"] and last["is_goal_content"], last
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_with_keep_studying_on_a_stone_marks_the_counted_entry_and_moves_only_the_render_signature(language, tmp_path):
    # why: with the option on a stone changes nothing a run reads, so only a re-render can show it
    import argparse
    from app import analyzer
    _settings(language)
    store = migrated(language)
    store.set_library_options(keep_watched=True)
    names = _now_names(store)
    args = argparse.Namespace(theme="default", zen_limit=0, language=language)
    found = analyzer.resolve_found_files(language, verbose=False, missing=True)
    run, render = analyzer.compute_run_signature(language, found, analyzer.parse_analysis_args([])), \
        analyzer.compute_render_signature(args)
    zen = argparse.Namespace(theme="Zen Mode", zen_limit=0, language=language)
    zen_render = analyzer.compute_render_signature(zen)
    store.set_watched([store.ids("now")[0], store.ids("now")[-1]])     # the last NOW file: Target Met
    found_after = analyzer.resolve_found_files(language, verbose=False, missing=True)
    assert found_after == found, "the option on: a stone counts on"
    assert analyzer.compute_run_signature(language, found_after, analyzer.parse_analysis_args([])) == run
    assert analyzer.compute_render_signature(args) != render, "the report must re-render"
    assert analyzer.compute_render_signature(zen) == zen_render, "Zen shows no journey: it never re-renders for one"
    data = _payload(_render(tmp_path, language, names))
    assert data["progressive"][0]["watched"] is True and data["progressive"][0]["words"], "counted AND watched"
    assert not any(e.get("aside") for e in data["progressive"])
    assert [f.get("watched") for f in data["completed_files"]] == [True], "a Target Met file is marked too"
    store.close()


def test_an_aside_file_whose_name_a_counted_file_has_gets_no_entry_of_its_own(tmp_path):
    # why: the per-file report knows a file by its basename; a second entry of one name would be two tabs for one
    # name (the template's maps keep one) — the counted file keeps its entry, never marked watched
    language = "zh"
    _settings(language)
    data_dir, user_files_dir = roots(language)
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    texts = _split_lines(_read(SHOWS[language][0]), 2)
    for n, rel in enumerate(("HighPriority/魔王/第01集.txt", "HighPriority/龙神/第01集.txt")):
        path = os.path.join(data_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(texts[n])
        doc["schedule"][ls.TIERS["now"][0]].append(entry(rel))
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    store.set_watched([store.ids("now")[0]])
    data = _payload(_render(tmp_path, language, ["第01集.txt", "其他.txt"]))
    assert [e["filename"] for e in data["progressive"]] == ["第01集.txt"]
    assert "watched" not in data["progressive"][0]
    store.close()


# --- the Generate half: real runs, as the dashboard starts them ---------------------------------------------------- #

def _library(language):
    """Show A Ep01–Ep03 then Show B Ep01–Ep03 in NOW, each episode named for its show, cut from the bundled samples'
    real text -> (store, {"A1": item id, ...}, {"A1": basename, ...})."""
    data_dir, user_files_dir = roots(language)
    a_src, b_src = SHOWS[language]
    a_sub = a_src.endswith(".srt")
    eps = {"A": _split_srt(_read(a_src), 3) if a_sub else _split_lines(_read(a_src), 3),
           "B": _split_lines(_read(b_src), 3)}
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    rels = {}
    for show, ext in (("A", ".srt" if a_sub else ".txt"), ("B", ".txt")):
        for n, text in enumerate(eps[show], 1):
            rel = f"HighPriority/Show{show}/Show{show}_ep0{n}{ext}"
            path = os.path.join(data_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            rels[f"{show}{n}"] = rel
            doc["schedule"][ls.TIERS["now"][0]].append(entry(rel))
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    return store, {k: store.item_id(rel) for k, rel in rels.items()}, {k: rel.rsplit("/", 1)[1] for k, rel in rels.items()}


def _generate(root, language):
    """A full Generate in its own process, as the dashboard runs it (the store's helper after) -> (report data, what it
    printed)."""
    cmd = [sys.executable, os.path.join(REPO, "app", "analyzer.py"), f"--language={language}", "--static",
           "--no-open", "--min-freq", "1"]
    p = subprocess.run(cmd, cwd=REPO, env=child_env(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
    subprocess.run([sys.executable, os.path.join(REPO, "app", "library_store.py"), "maintain", "--language", language],
                   cwd=REPO, env=child_env(root), capture_output=True)
    return _report(root), p.stdout


def _files(data):
    return [e["filename"] for e in data["progressive"]]


def _stones(data):
    return {e["filename"]: bool(e.get("aside")) for e in data["progressive"] + data["completed_files"]
            if e.get("watched")}


def _words(data, name):
    entry_ = next(e for e in data["progressive"] if e["filename"] == name)
    words = entry_["words"]
    return words["rows"] if isinstance(words, dict) else words


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_stone_then_its_undo_then_keep_studying_on_through_real_generates(language):
    root = os.environ["SURASURA_TEST_ROOT"]
    _settings(language)
    store, ids, names = _library(language)
    first, _said = _generate(root, language)
    assert _files(first) == [names[k] for k in ("A1", "A2", "A3", "B1", "B2", "B3")], "every episode has words"
    assert _stones(first) == {}, "no stone: no watched key anywhere"

    change = store.set_watched([ids["A2"]])
    marked, said = _generate(root, language)
    assert REUSED not in said, "a stone with the option off is a Generate (its words step back)"
    assert _files(marked) == _files(first), "the watched episode stays in its place in the journey"
    stone = marked["progressive"][1]
    assert stone["filename"] == names["A2"] and stone["aside"] and stone["words"] == [] and stone["total_words"] == 0
    assert _stones(marked) == {names["A2"]: True}
    assert names["A2"] not in [f["filename"] for f in marked["completed_files"]]

    store.undo(change)
    undone, _said = _generate(root, language)
    assert undone == first, "its Undo: the report data is the first run's"

    store.set_library_options(keep_watched=True)
    store.set_watched([ids["A2"]])
    kept, said = _generate(root, language)
    assert REUSED in said and "Re-rendering report" in said, "the option on: a re-render, never a re-analysis"
    assert _stones(kept) == {names["A2"]: False}, "counted AND watched"
    assert _words(kept, names["A2"]) == _words(first, names["A2"]), "its words still counted"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_drill_a2_step_6_every_episode_watched_then_finished_then_put_back_and_one_undo(language):
    # why: drill A2 step 6 — mark every A episode → Finish Show A → Put back → the stones clear and its words return;
    # one Undo puts back both the stones and the show (Q1 A). Read through the report data each time.
    root = os.environ["SURASURA_TEST_ROOT"]
    _settings(language)
    store, ids, names = _library(language)
    show_a = [ids[k] for k in ("A1", "A2", "A3")]
    a_names = [names[k] for k in ("A1", "A2", "A3")]
    first, _said = _generate(root, language)

    store.set_watched(show_a)
    watched, _said = _generate(root, language)
    assert _files(watched) == _files(first), "every A episode in its place"
    assert _stones(watched) == {n: True for n in a_names}, "each one a stone, set aside"
    assert all(_words(watched, n) == [] for n in a_names)

    store.finish(show_a)
    finished, _said = _generate(root, language)
    assert not set(a_names) & set(_files(finished)), "Finished stays out of the journey"
    assert _stones(finished) == {}

    back = store.put_back_finished(show_a)
    assert all(store.item(i)["watched"] == 0 for i in show_a), "put back: its stones clear"
    returned, _said = _generate(root, language)
    assert _stones(returned) == {}, "no stone left on the journey"
    assert _files(returned) == _files(first) and all(_words(returned, n) == _words(first, n) for n in a_names), \
        "its words return"

    store.undo(back)
    assert all(store.item(i)["tier"] == "graduated" and store.item(i)["watched"] == 1 for i in show_a), \
        "one Undo: the show back in Finished with its stones"
    undone, _said = _generate(root, language)
    assert _files(undone) == _files(finished) and _stones(undone) == {}, "as it was when finished"
    store.close()


# --- the review round (S-1 / IK-4, S-3 / IK-3, S-2) ----------------------------------------------------------------- #

# A Generate whose report is drawn after something happened to the store mid-run (the window stays live while a
# Generate runs): `mark` — the learner marks an episode just before the report is drawn; `locked` — the store can't be
# read at that moment. The analyzer runs as `python app/analyzer.py` does, its generator's stones step wrapped.
DRIVER = r'''
import os, runpy, sqlite3, sys
from app import library_store as ls, static_html_generator as gen
language, data_dir, user_files_dir, mode, item = sys.argv[1:6]
drawn = gen._journey_stones

def hooked(*a, **k):
    if mode == "mark":
        store = ls.open_store(language, data_dir, user_files_dir)
        try:
            store.set_watched([int(item)])
        finally:
            store.close()
        return drawn(*a, **k)
    def locked(self):
        raise sqlite3.OperationalError("database is locked")
    real, ls.Store.watched_marks = ls.Store.watched_marks, locked
    try:
        return drawn(*a, **k)
    finally:
        ls.Store.watched_marks = real

gen._journey_stones = hooked
sys.argv = ["analyzer.py", f"--language={language}", "--static", "--no-open", "--min-freq", "1"]
runpy.run_path(os.path.join(os.path.dirname(ls.__file__), "analyzer.py"), run_name="__main__")
'''


def _generate_during(root, language, mode, item, tmp_path):
    """A first, full Generate in its own process with DRIVER's `mode` happening as its report is drawn -> (report
    data, what it printed)."""
    driver = tmp_path / "stones_driver.py"
    driver.write_text(DRIVER, encoding="utf-8")
    data_dir, user_files_dir = roots(language)
    p = subprocess.run([sys.executable, str(driver), language, data_dir, user_files_dir, mode, str(item)], cwd=REPO,
                       env=child_env(root), capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
    subprocess.run([sys.executable, os.path.join(REPO, "app", "library_store.py"), "maintain", "--language", language],
                   cwd=REPO, env=child_env(root), capture_output=True)
    return _report(root), p.stdout


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_mark_landing_mid_generate_is_signed_as_drawn_so_its_undo_re_renders(language, tmp_path):
    # why (S-1): with *Keep studying* on, a mark made while a Generate runs shows in that report; signed with the
    # marks read at the run's start (none), its Undo made the next press reopen that report, the stone still on an
    # episode the learner un-marked. Signed as drawn, the Undo re-renders — and a press after that reopens (S19).
    root = os.environ["SURASURA_TEST_ROOT"]
    _settings(language)
    store, ids, names = _library(language)
    store.set_library_options(keep_watched=True)
    during, _said = _generate_during(root, language, "mark", ids["A2"], tmp_path)
    assert _stones(during) == {names["A2"]: False}, "the mark made mid-run is drawn: counted AND watched"

    store.set_watched([ids["A2"]], False)          # its Undo (the mark was the driver's process's change)
    after, said = _generate(root, language)
    assert REUSED in said and "Re-rendering report" in said, "its Undo re-renders the report"
    assert _stones(after) == {}, "no stone left on an episode he un-marked"
    _again, said = _generate(root, language)
    assert "Report already up to date" in said, "nothing changed since: the report is reopened, never redrawn"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_failed_marks_read_records_no_render_signature_so_the_next_press_re_renders(language, tmp_path):
    # why (IK-4): a report drawn while the store couldn't be read has no stones; recorded as current, the next press
    # reopened it — the learner's watched episode with no stone — until something else changed
    root = os.environ["SURASURA_TEST_ROOT"]
    _settings(language)
    store, ids, names = _library(language)
    store.set_library_options(keep_watched=True)
    store.set_watched([ids["A2"]])
    during, said = _generate_during(root, language, "locked", ids["A2"], tmp_path)
    assert _stones(during) == {}, "the marks couldn't be read: the report is drawn without them"
    after, said = _generate(root, language)
    assert REUSED in said and "Re-rendering report" in said, "never recorded as current: the next press re-renders"
    assert _stones(after) == {names["A2"]: False}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_report_draws_the_runs_language_marks_never_settings(language):
    # why (S-3): a Generate in one language while settings.json names the other (surasura-cli generate --lang) drew
    # the other language's marks: its own stones missing, and the other's set-aside episodes added to this journey
    root = os.environ["SURASURA_TEST_ROOT"]
    _settings("zh" if language == "ja" else "ja")
    store, ids, names = _library(language)
    store.set_watched([ids["A2"]])
    data, _said = _generate(root, language)
    assert _stones(data) == {names["A2"]: True}, "the run's own stone, in its place"
    assert _files(data)[1] == names["A2"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_with_no_stone_asks_one_indexed_question(language):
    # why (S-2, S19): with no stone, every Generate press asked "is there one?" by scanning every analysed row (about
    # 60-70 ms at 200k items, two or three times a press); a partial index on the watched rows answers at once. A store
    # made before the index gets it at its first open by a writer — and nothing else in it changes
    import sqlite3
    store = migrated(language)
    plan = " | ".join(r[-1] for r in store.conn.execute("EXPLAIN QUERY PLAN " + ls.STONES_EXIST_SQL).fetchall())
    assert "items_watched" in plan, plan
    data_dir, user_files_dir = roots(language)
    store.close()
    db = ls.library_db_path(language, data_dir)
    raw = sqlite3.connect(db)
    raw.execute("DROP INDEX items_watched")                                   # the store as an older build made it
    raw.commit()
    rows = raw.execute("SELECT * FROM items ORDER BY id").fetchall()
    version = raw.execute("PRAGMA user_version").fetchone()[0]
    raw.close()
    assert ls.read_watched_marks(language, data_dir) == [], "an older store reads as before, only slower"
    store = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert store.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'items_watched'").fetchone()
        assert store.conn.execute("SELECT * FROM items ORDER BY id").fetchall() == rows
        assert store.conn.execute("PRAGMA user_version").fetchone()[0] == version == ls.STORE_SCHEMA
    finally:
        store.close()

"""Example sentences that don't hang on the order (F7, RP-11; Sonic 2026-11-06: "build it with the new version only.
60 is fine.").

What these prove, with Generate run as the dashboard starts it (`analyzer.py`, its own process), on real text:
  - every list row's shortlist — 60 sentences by the whole library's counts and a hash of the text, at most 2 a file
    unless the spread can't fill it — is the same in any order of the library (RP-2's orders A, B and D, Japanese and
    Chinese); only which of them a row shows is the order's (tests/test_plan_engine.py: the re-pick is each order's
    Generate);
  - what the learner watched is a sentence source and never a count: with a show Finished, rows show its lines (their
    Src a Finished file), and every count the list shows is what it is with the same show set aside as watched —
    which lends its lines too (Sonic 2026-11-06: a watched episode "as if finished");
  - among equally easy sentences, a set-aside watched episode first, then Finished, the newest finished first — and
    finishing in another order is another run (the signature's "finished" part);
  - the shortlist's spread: a word met in one file keeps every good sentence it has there (no cap starves it);
  - the redraw from the plan (`--from-plan`) falls through to a Generate whenever more than the order moved.

What a wrong answer would cost a learner: sentences that jump after every drag (the old shortlist ranked with the
counts so far), a word's Context 3 left empty because one file held all its lines, a Finished show's lines never used,
or counted again on the list; a redraw that writes a list a Generate wouldn't.
"""
import csv
import io
import os
import shutil

import pytest

from app import analyzer, library_store as ls, plan_engine, plan_rules
from tests import plan_file_cases as cases
from tests.test_generate_finished import _shows
from tests.test_generate_watched import _generate
from tests.test_library_store_support import LANGUAGES, entry, roots, write_manifest

COUNTS = ("Word", "Reading", "Score", "Occurrences", "Count (High)", "Count (Low)", "Count (Goal)", "Tier", "Orth",
          "Forms")


def _rows(raw):
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def _contexts(row, n=3):
    return [(row.get(f"Context {i}") or "", row.get(f"Src {i}") or "") for i in range(1, n + 1)]


# --------------------------------------------------------------------------- #
# 1. The shortlist is the same in any order
# --------------------------------------------------------------------------- #
def _shortlists(root):
    """{(Word, Reading): sorted (text, source) of its shortlist and Finished sentences} from a run's plan file."""
    plan = plan_engine.load(os.path.join(root, "results", analyzer.PLAN_FILE))
    sources = [entry[0] for entry in plan.files] + [entry[0] for entry in plan.finished]
    out = {}
    for k, (_first, pool, audio) in plan.pools.items():
        out[tuple(plan.keys[k][:2])] = (sorted((plan.sentences[s][0], sources[plan.sentences[s][4]]) for s in pool),
                                        sorted((plan.sentences[s][0], sources[plan.sentences[s][4]]) for s in audio))
    return out


@pytest.mark.parametrize("case", ["rp2-ja", "rp2-zh"])
def test_every_rows_shortlist_is_the_same_in_any_order(tmp_path, case):
    # why: the shortlist is what a re-plan re-picks from; ranked with the counts so far it moved with every drag
    # (Haya-D: one drag re-picked 1–13 % of words; a reshuffle 87–99 %) — now only the pick may follow the order
    from tests.test_plan_file import _rp2_orders
    language = cases.ALL_CASES[case][0]
    found = {}
    for name in ("A", "B", "D"):
        root = str(tmp_path / name)
        cases.build(root, case, _rp2_orders(language)[name])
        cases.generate(root, case)
        found[name] = _shortlists(root)
    assert found["A"] and all(pool for pool, _audio in found["A"].values())
    for name in ("B", "D"):
        assert found[name].keys() == found["A"].keys(), name
        moved = [key for key in found["A"] if found[name][key] != found["A"][key]]
        assert moved == [], (name, moved[:5])


def test_a_word_met_in_one_file_keeps_every_good_sentence_it_has(tmp_path):
    # why: the spread (at most 2 a file) must never starve a word whose lines are all in one file — its Context 3
    # went empty when the cap stood alone; the uncapped best fill the shortlist past the spread
    root = os.environ["SURASURA_TEST_ROOT"]
    data_dir, user_files_dir = roots("ja")
    text = "灯台の光が見えた。夜の灯台は静かだった。白い灯台が海の近くにある。古い灯台が丘の上に立っている。"
    path = os.path.join(data_dir, "HighPriority", "one.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    doc["schedule"][ls.TIERS["now"][0]].append(entry("HighPriority/one.txt"))
    write_manifest(user_files_dir, doc)
    assert ls.maintain("ja", data_dir, user_files_dir) == ls.EXIT_DONE
    row = next(r for r in _rows(_generate(root, "ja")) if r["Word"] == "灯台")
    shown = [c for c, _s in _contexts(row)]
    assert all(shown) and len(set(shown)) == 3, shown


# --------------------------------------------------------------------------- #
# 2. Finished content: a source, never a count
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_finished_or_watched_show_lends_its_lines_and_counts_for_nothing(language):
    # why: Sonic, 2026-11-06 — "pulling sentences from finished content ... finished would be more valuable", and a
    # watched episode "as if finished"; a line already watched is a better example, but both are reference: never a use
    # on the list
    root = os.environ["SURASURA_TEST_ROOT"]
    store, paths, ids = _shows(language)
    show_a = [ids[f"A{n}"] for n in (1, 2, 3)]
    a_rel = {os.path.relpath(paths[f"A{n}"], roots(language)[0]).replace("\\", "/") for n in (1, 2, 3)}

    change = store.finish(show_a)
    assert change is not None
    finished = _rows(_generate(root, language))
    store.undo(change)
    assert store.set_watched(show_a) is not None                # set aside as well, but not Finished
    watched = _rows(_generate(root, language))
    store.close()

    assert [{c: r[c] for c in COUNTS} for r in finished] == [{c: r[c] for c in COUNTS} for r in watched], \
        "every count the same: a Finished show is never a use"
    for lists, what in ((finished, "Finished"), (watched, "watched")):
        assert any(src in a_rel for r in lists for _c, src in _contexts(r)), f"some rows show a {what} line"
        assert not any(src in a_rel for r in lists for _c, src in _contexts(r)[:1]), "never Context 1"


def _tiny(language="ja"):
    """NOW: one file holding 灯台 once, and one to mark watched; two shows to finish; each with one line for 灯台 as easy
    as the others' (short, no other unknown word): -> (store, {name: item id})."""
    data_dir, user_files_dir = roots(language)
    files = {"HighPriority/now.txt": "灯台を見た。",
             "HighPriority/watched.txt": "灯台さ。",
             f"{ls.GRADUATED_FOLDER}/一/a.txt": "灯台だ。",
             f"{ls.GRADUATED_FOLDER}/二/b.txt": "灯台か。"}
    for rel, text in files.items():
        path = os.path.join(data_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    doc["schedule"][ls.TIERS["now"][0]] += [entry(rel) for rel in files]
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    return store, {rel: store.item_id(rel) for rel in files}


def test_among_equally_easy_lines_the_newest_finished_comes_first():
    # why: "finished would be more valuable. Then recent" — of two equally easy Finished lines the one finished last
    # leads; finishing them the other way round turns them round (another run: the signature's "finished" part)
    root = os.environ["SURASURA_TEST_ROOT"]
    store, ids = _tiny()
    a, b = ids[f"{ls.GRADUATED_FOLDER}/一/a.txt"], ids[f"{ls.GRADUATED_FOLDER}/二/b.txt"]
    first = store.finish([a])
    second = store.finish([b])
    row = next(r for r in _rows(_generate(root, "ja")) if r["Word"] == "灯台")
    assert [c for c, _s in _contexts(row)] == ["灯台を見た。", "灯台か。", "灯台だ。"], _contexts(row)
    assert _contexts(row)[1][1].endswith("二/b.txt")
    store.undo(second)
    store.undo(first)
    store.finish([b])
    store.finish([a])
    raw, said = _generate(root, "ja", said=True)
    assert "reusing existing results" not in said, "finishing in another order is another run"
    row = next(r for r in _rows(_generate(root, "ja")) if r["Word"] == "灯台")
    assert [c for c, _s in _contexts(row)] == ["灯台を見た。", "灯台だ。", "灯台か。"], _contexts(row)
    # A NOW episode marked watched (set aside: Keep studying watched episodes is off) leads them: it is what the
    # learner is studying now (the store keeps no time it was watched: ahead of every Finished one)
    assert store.set_watched([ids["HighPriority/watched.txt"]]) is not None
    row = next(r for r in _rows(_generate(root, "ja")) if r["Word"] == "灯台")
    assert [c for c, _s in _contexts(row)] == ["灯台を見た。", "灯台さ。", "灯台だ。"], _contexts(row)
    store.close()


def test_the_signature_holds_the_finished_files_in_their_finish_order(tmp_path):
    # why: the pick follows the finish order, so two finish orders are two runs — never one reused for the other;
    # a watched episode (set aside, no rank) adds nothing to the part
    files = [str(tmp_path / name) for name in ("a.txt", "b.txt", "w.txt")]
    for path in files:
        with open(path, "w", encoding="utf-8") as f:
            f.write("灯台")
    args = analyzer.parse_analysis_args(["--language=ja"])
    one = analyzer.run_signature_parts("ja", [], args, [(files[0], "text", 1), (files[1], "text", 0),
                                                        (files[2], "text", None)])
    two = analyzer.run_signature_parts("ja", [], args, [(files[0], "text", 0), (files[1], "text", 1),
                                                        (files[2], "text", None)])
    # (a set-aside file with no rank is one aside_files never makes now — every set-aside file is ranked — but the
    # part reads only the ranked ones)
    assert one["reference"] == two["reference"], "the same files set aside"
    assert len(one["finished"]) == 2 and one["finished"] == two["finished"][::-1]
    assert plan_rules.signature_digest(one) != plan_rules.signature_digest(two)
    none = analyzer.run_signature_parts("ja", [], args, [(files[2], "text", None)])
    assert "finished" not in none, "no Finished content: the part isn't there (a library without signs as before)"


# --------------------------------------------------------------------------- #
# 3. The redraw falls through when more than the order moved
# --------------------------------------------------------------------------- #
def test_a_redraw_asked_after_a_known_word_change_is_a_generate():
    # why: a known word moves which words are listed: the plan can't serve it, so --from-plan must Generate in full
    root = os.environ["SURASURA_TEST_ROOT"]
    store, _paths, _ids = _shows("ja")
    store.close()
    _generate(root, "ja")
    stamp = analyzer.read_run_stamp(os.path.join(root, "results"))
    known = os.path.join(roots("ja")[1], "KnownWord.json")
    shutil.copy(os.path.join(cases.RES, "ja", "KnownWord.json"), known)
    import subprocess
    import sys
    p = subprocess.run([sys.executable, os.path.join(cases.REPO, "app", "analyzer.py"), "--language=ja", "--static",
                        "--no-open", "--min-freq", "1", "--from-plan"], cwd=cases.REPO, env=cases.child_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    assert "Redrew the journey" not in p.stdout and "generating" in p.stdout
    results = os.path.join(root, "results")
    assert analyzer.redrawn_for(results) is None, "a Generate: no redraw marker"
    assert analyzer.read_run_stamp(results) not in (None, stamp), "stamped as the new run"

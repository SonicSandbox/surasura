"""DSA-START (3.0.19): the window's start and a move, each read against the textbook choice, on RP-2's real library.

- **A move's numbers walk only what moved.** `Numbers.after_move` copied every file's *N new* and compared all of
  them after `Engine.move` (20,000 pairs a press at 20k), though the engine changes a file's *N new* only where a
  word's first file moved — it knows those files. Now it hands them over (`Engine.move(..., n_new_was=)`), and the
  numbers publish exactly those rows: the same rows, the same figures, nothing else walked.
- **G3: the redraw's check hashes in one call.** The keeper's redraw (`analyzer.py --from-plan`) asked
  `plan_engine.check` with the chunked digest meant for a worker beside the window (0.45 s at 20k against 0.03 s);
  the redraw is a process of its own, with no thread waiting beside it.

What a wrong answer would cost: a row that keeps an old *N new* after a drop (the learner sees a stale count until
the next start), or a row told it changed when it didn't (a rebuilt row: waste, never a wrong figure).
"""
import json
import os
import subprocess
import sys
import types

import pytest

from app import analyzer, plan_engine
from tests import plan_file_cases as cases


def _generated(language, root):
    root = str(root)
    case = f"rp2-{language}"
    cases.build(root, case)
    cases.generate(root, case, extra_env={"SURASURA_SENTENCE_TABLE": "2"})
    return root


@pytest.fixture(scope="module", params=["ja", "zh"])
def run(request, tmp_path_factory):
    """RP-2's real library of one language, Generated at level 2 (the shipped level)."""
    language = request.param
    root = _generated(language, tmp_path_factory.mktemp(f"dsa-start-{language}"))
    return types.SimpleNamespace(language=language, root=root, results=os.path.join(root, "results"),
                                 plan_path=os.path.join(root, "results", analyzer.PLAN_FILE), tmp=tmp_path_factory)


def _in_root(monkeypatch, root):
    """This process reads the module's root, as the window's own process reads its library."""
    monkeypatch.setenv("SURASURA_TEST_ROOT", root)
    monkeypatch.setenv("APPDATA", os.path.join(root, "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", os.path.join(root, "localappdata"))


class _Walked(list):
    """A list that counts the items an iteration hands out (`list(x)`, `zip(x, …)`, a for loop): the files walked."""
    walked = 0

    def __iter__(self):
        for value in list.__iter__(self):
            _Walked.walked += 1
            yield value


def _loaded_numbers(run, monkeypatch):
    from app.services import moves
    _in_root(monkeypatch, run.root)
    numbers = moves.Numbers(moves.store_opener(run.language), run.language, plan_file=run.plan_path)
    numbers.load()
    assert numbers.idle(60) and numbers.why() is None, numbers.why()
    return numbers


def _referee(run, eng):
    """A fresh engine over the moved engine's order now (`_numbers` from scratch): the figures a move must leave."""
    plan = plan_engine.load(run.plan_path, pools=False)
    referee = plan_engine.Engine(plan, list(eng._ids), numbers_only=True)
    referee._numbers([(eng._ids[f], plan_engine.TIERS[eng._tier[f]]) for f in eng._order])
    return referee


def test_a_moves_numbers_walk_only_the_files_the_engine_changed_and_equal_a_fresh_count(run, monkeypatch):
    """Two drops (a Soon title to NOW's top, then 6+ Months' last before Soon's last): each publishes exactly the
    rows whose figures moved — the moved title's and every title whose *N new* the engine changed — with a fresh
    count's figures, and walks none of the other files' *N new* (the counter: before, 2 × every file a press)."""
    numbers = _loaded_numbers(run, monkeypatch)
    try:
        eng = numbers._engine
        n_files = len(eng._n_new)
        assert n_files >= 6, n_files
        eng._n_new = _Walked(eng._n_new)
        tiers = {t: [eng._ids[f] for f in eng._order if plan_engine.TIERS[eng._tier[f]] == t]
                 for t in plan_engine.TIERS}
        assert tiers["soon"] and tiers["goal"], {t: len(v) for t, v in tiers.items()}
        drops = [([tiers["soon"][-1]], "now", {"before_id": tiers["now"][0]}),
                 ([tiers["goal"][-1]], "soon", {"before_id": tiers["soon"][0]})]
        for ids, tier, where in drops:
            before_version, before_table = numbers()
            before_table = dict(before_table)
            _Walked.walked = 0
            touched = numbers.after_move(ids, tier, **where)
            walked = _Walked.walked
            assert touched and ids[0] in touched, touched
            _v, table = numbers()
            referee = _referee(run, eng)
            for item, (_known, _counted, n_new) in table.items():
                f = referee._f_of.get(item)
                if f is not None:
                    assert n_new == referee._n_new[f], (item, n_new, referee._n_new[f])
            moved = {item for item in table if table[item] != before_table.get(item)}
            assert set(touched) == moved | {ids[0]}, (sorted(touched), sorted(moved))
            assert numbers.changed(before_version) == set(touched)
            assert walked == 0, f"{walked} of {n_files} files' N new walked for one move"
    finally:
        numbers.close()


_DIGESTS = """
import runpy, sys
from app import plan_rules
calls, digest = [], plan_rules.signature_digest
def counted(parts, order_free=False, chunked=True, *a, **k):
    calls.append(chunked)
    return digest(parts, order_free, chunked, *a, **k)
plan_rules.signature_digest = counted
sys.argv = [sys.argv[1]] + sys.argv[2:]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
finally:
    sys.stderr.write("\\nDIGESTS-CHUNKED %d of %d\\n" % (sum(1 for c in calls if c), len(calls)))
"""


def test_the_redraw_hashes_the_library_with_the_one_fast_call(run):
    """A show moved to the top, then the keeper's redraw (`--from-plan`), in a root of its own: it redraws, and no
    digest in its process takes the chunked path (before: `plan_engine.check`'s, at the window's default)."""
    from tests.test_e_redraw import _move
    root = _generated(run.language, run.tmp.mktemp(f"dsa-start-redraw-{run.language}"))
    _move(root, run.language, "top")
    env = cases.child_env(root)
    env["SURASURA_SENTENCE_TABLE"] = "2"
    p = subprocess.run([sys.executable, "-c", _DIGESTS, os.path.join(cases.REPO, "app", "analyzer.py"),
                        f"--language={run.language}", "--static", "--no-open", "--from-plan"],
                       cwd=cases.REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = p.stdout + p.stderr
    assert p.returncode == 0 and "Redrew the journey" in out, out[-3000:]
    line = [x for x in p.stderr.splitlines() if x.startswith("DIGESTS-CHUNKED ")][-1]
    chunked, total = int(line.split()[1]), int(line.split()[3])
    assert total >= 1, line
    assert chunked == 0, line


# --- G7: the run signature's stats from one listing per folder -------------------------------------------------- #

# G7 is out of 3.0.19 (the lead, 2026-11-25 21:3x): with it the window's first numbers load landed in its slow mode
# more often (the first view with numbers 4.5 -> ~6.2 s median at 20k). These tests are the behaviour expected when
# OPEN-RACE puts it back on top (commits 4a9e5eb7, 6a0f396a, 4e211d36): OPEN-RACE drops this mark.
_G7_OUT = pytest.mark.skip(reason="G7 (the signature's one listing a folder) held for OPEN-RACE: the expected "
                                  "behaviour once it is back on top (4a9e5eb7, 6a0f396a, 4e211d36)")

def _signing(language, tmp_path, monkeypatch):
    """RP-2's library of `language` built in a root of its own (no Generate: the signature reads only the files and
    the settings), plus a nested season folder of four CRLF episodes: (found files, args, the season's paths) as the
    numbers' check builds them (`plan_inputs`)."""
    from app import run_args, settings_manager
    root = str(tmp_path)
    cases.build(root, f"rp2-{language}")
    _in_root(monkeypatch, root)
    data = os.path.join(root, "data", language)
    with open(os.path.join(cases.RES, language, "context_test.txt"), encoding="utf-8") as f:
        text = f.read()
    season = os.path.join(data, "HighPriority", "季節 1")
    os.makedirs(season)
    manifest = os.path.join(root, "User Files", language, "master_manifest.json")
    with open(manifest, encoding="utf-8") as f:
        doc = json.load(f)
    for n in (1, 2, 3, 4):
        with open(os.path.join(season, f"第{n}話.txt"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(text)
        doc["schedule"][cases.PHASE["now"]].append({"physical_path": f"HighPriority/季節 1/第{n}話.txt",
                                                    "title": f"第{n}話", "origin_source": "Manual Import"})
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    found = analyzer.resolve_found_files(language, verbose=False, missing=True)
    episodes = [fp for fp, *_ in found if os.path.normpath(fp).startswith(season)]
    assert len(episodes) == 4
    args = analyzer.parse_analysis_args(run_args.analyzer_args(settings_manager.load_settings(), language)[1:])
    return found, args, episodes


def _stats_of(paths, monkeypatch):
    """Counts os.stat calls on `paths` (the content files) while a signature is read."""
    want, calls, real = {os.path.normcase(p) for p in paths}, [], os.stat

    def counted(p, *a, **k):
        if os.path.normcase(str(p)) in want:
            calls.append(p)
        return real(p, *a, **k)
    monkeypatch.setattr(os, "stat", counted)
    return calls


def _by_os_stat(found, args, language, monkeypatch):
    """The signature's parts with no listing (every path os.stat'ed): the bytes before G7."""
    from app import library_store
    with monkeypatch.context() as m:
        m.setattr(library_store, "_listed_stats", lambda folder, names: {})
        return analyzer.run_signature_parts(language, found, args)


@_G7_OUT
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_signature_lists_each_folder_once_and_signs_the_same_bytes_as_a_stat_per_file(language, tmp_path,
                                                                                          monkeypatch):
    """Before: one os.stat per content file at every check (20,000 at 20k, ~0.46 s; a start runs three such checks).
    Now a folder of LISTED_STATS files or more is listed once (os.scandir) and hands every file's st_mtime and
    st_size; a folder with fewer is stat'ed file by file as before (a listing costs more than a stat or two). The
    parts and the digest are byte for byte what a stat per file signs, in nested folders and CRLF files too; every
    file's figures equal os.stat's; a listing that raises leaves every path to os.stat, never a lost signature."""
    from app import library_store, plan_rules
    found, args, _episodes = _signing(language, tmp_path, monkeypatch)
    old = _by_os_stat(found, args, language, monkeypatch)
    by_folder = {}
    for fp, *_ in found:
        by_folder.setdefault(os.path.split(fp)[0], []).append(fp)
    big = {d for d, fps in by_folder.items() if len(fps) >= library_store.LISTED_STATS}
    small = [fp for d, fps in by_folder.items() if d not in big for fp in fps]
    assert big and small                    # both kinds in each language's library
    listings, real = [], library_store._listed_stats
    monkeypatch.setattr(library_store, "_listed_stats",
                        lambda folder, names: listings.append(folder) or real(folder, names))
    calls = _stats_of([fp for fp, *_ in found], monkeypatch)
    new = analyzer.run_signature_parts(language, found, args)
    assert sorted(calls) == sorted(small), f"{len(calls)} of {len(found)} content files os.stat'ed one by one"
    assert sorted(d for d in listings if d in by_folder) == sorted(big)     # each such folder listed once
    assert new == old
    assert plan_rules.signature_digest(new) == plan_rules.signature_digest(old)
    for fp, sig, *_ in new["files"]:
        st = os.lstat(fp)                   # the file's own figures, read apart from either path
        assert sig == [st.st_mtime, st.st_size], fp

    def raising(folder, names):
        raise OSError("the listing failed")
    monkeypatch.setattr(library_store, "_listed_stats", raising)
    assert analyzer.run_signature_parts(language, found, args) == old


@_G7_OUT
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_file_edited_or_removed_between_two_checks_is_seen_by_the_second(language, tmp_path, monkeypatch):
    """Nothing is kept across checks: a file edited between two signatures (its size and time moved) and a file
    removed (None: a missing item keeps its place) are in the second, as a stat per file signs them — never the
    first listing's figures. A listing shared across a start's passes would sign the old ones here."""
    found, args, episodes = _signing(language, tmp_path, monkeypatch)
    first = analyzer.run_signature_parts(language, found, args)
    edited, removed = episodes[0], episodes[-1]         # both in the season's folder: one the listing serves
    with open(edited, "a", encoding="utf-8") as f:
        f.write("\n追記の一行。\n" if language == "ja" else "\n补充的一行。\n")
    os.utime(edited, (cases.MTIME + 3600, cases.MTIME + 3600))
    os.remove(removed)
    second = analyzer.run_signature_parts(language, found, args)
    sig = {fp: s for fp, s, *_ in second["files"]}
    st = os.stat(edited)
    assert sig[edited] == [st.st_mtime, st.st_size] != {fp: s for fp, s, *_ in first["files"]}[edited]
    assert sig[removed] is None
    assert second == _by_os_stat(found, args, language, monkeypatch)


@_G7_OUT
@pytest.mark.skipif(os.name != "nt", reason="a path spelled in another case names the same file only on Windows")
def test_a_path_the_listing_spells_otherwise_is_stated_as_before(tmp_path, monkeypatch):
    """The listing is matched by the exact name: a found path in another case (the same file on Windows) isn't in it,
    and is os.stat'ed as before — the same bytes, never None."""
    found, args, _episodes = _signing("ja", tmp_path, monkeypatch)
    fp, *rest = found[0]                                # HighPriority's: a folder the listing serves
    folder, name = os.path.split(fp)
    found = [(os.path.join(folder, name.upper()), *rest)] + found[1:]
    calls = _stats_of([found[0][0]], monkeypatch)
    new = analyzer.run_signature_parts("ja", found, args)
    assert len(calls) == 1 and new["files"][0][1] is not None
    assert new == _by_os_stat(found, args, "ja", monkeypatch)

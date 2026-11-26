"""DSA-PHRASE (3.0.19): two passes a Generate or a start did again and again, each done once.

1. The finished files' set phrases. With phrase rows on (the Japanese default) the token store kept the phrases it found
   for counted files alone, so at every Generate the finished walk built every sentence of every finished file and
   searched each one for set phrases, and the walk's mask on ids (DSA-WALK) never applied there. The index now keeps a
   set-aside file's matches too, found once when the file is indexed; the finished walk reads them and walks its mask.
2. The start's stat pass. `Store.needs_reconcile` (the window's `index_needed` check at every start) and the reconcile
   stat'ed every listed file one by one (20k: 20,000 `os.stat` a pass); one `os.scandir` listing a folder gives the same
   size and modified time.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

from app import analyzer, phrases, token_index as ti

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
PHRASES_SAMPLE = os.path.join(RESOURCES, "ja", "phrases_sample.srt")


# ---------------------------------------------------------------------------------------------------- #
# 1. The finished files' set phrases, found once at index time
# ---------------------------------------------------------------------------------------------------- #
def _phrases_on(root, on=True):
    (root / "settings.json").write_text(json.dumps({"logic": {"phrase_rows": on}}), encoding="utf-8")
    analyzer.LOGIC["phrase_rows"] = on


@pytest.fixture
def two_files():
    """A ja library of two real files: a counted one (HighPriority) and one to set aside (Finished, nested as the
    Finished importer copies a show) whose sentences hold set phrases (気を付ける, 気が付く …) — (root, counted, aside)."""
    root = Path(os.environ["SURASURA_TEST_ROOT"])
    high = root / "data" / "ja" / "HighPriority"
    done = root / "data" / "ja" / "Graduated" / "終わった作品" / "第1期"
    high.mkdir(parents=True)
    done.mkdir(parents=True)
    counted = high / "placed_episode.srt"
    aside = done / "phrases_sample.srt"
    shutil.copy(os.path.join(RESOURCES, "ja", "placed_episode.srt"), counted)
    shutil.copy(PHRASES_SAMPLE, aside)
    (root / "User Files" / "ja").mkdir(parents=True)
    (root / "User Files" / "ja" / "KnownWord.json").write_text('{"words": []}', encoding="utf-8")
    _phrases_on(root)
    analyzer.SANITIZE_JA = True
    return root, str(counted), str(aside)


def _tallied(monkeypatch):
    """The files `phrases.tally` reads (each one a file searched for its phrases), by their first sentence."""
    read = []
    real = phrases.tally
    monkeypatch.setattr(phrases, "tally", lambda sentences, found, matches=None:
                        read.append(sentences[0][0] if sentences else "") or real(sentences, found, matches))
    return read


def test_the_index_keeps_a_finished_files_phrases_and_counts_none_of_them(two_files):
    # why: the finished walk can read a set-aside file's phrases only if the index keeps them; the phrase table (the
    # Rarity slider's count) and the arrivals gate's tallies must still count counted files alone — the same table as a
    # store that never saw the finished file
    root, counted, aside = two_files
    tok = ti.make_tokenizer("ja")
    store = ti.open_store("ja")
    alone = ti.open_store("ja", path=str(root / "alone.db"))
    try:
        store.reconcile([counted], tok, build_signature=ti.build_signature("ja"), aside=[aside])
        alone.reconcile([counted], tok, build_signature=ti.build_signature("ja"))
        found = store.phrase_matches([counted, aside])
        assert set(found) == {counted, aside}, "a set-aside file's matches are kept too"
        sentences, flat = found[aside]
        assert sentences == len(store.file_tokens(aside)) and flat and len(flat) % 4 == 0
        met = Counter(phrases.load().entry(index).word for index in flat[3::4])
        assert met["気を付ける"] == 3 and met["気が付く"] == 2, "every use the file holds, as a search finds them"
        assert store.phrase_table() == alone.phrase_table(), "the table counts counted files alone"
        assert store.phrase_tallies() == alone.phrase_tallies()
        assert store.phrase_sums() == alone.phrase_sums()
        assert store.phrase_matches([counted]) == alone.phrase_matches([counted])
    finally:
        store.close()
        alone.close()


def test_a_file_moving_between_counted_finished_and_kept_is_searched_only_when_it_needs_a_tally(two_files,
                                                                                                monkeypatch):
    # why: a class move re-tokenizes nothing (the module docstring); its phrases follow it the same way — to Finished
    # the matches stay as they were found (no search); to kept (never a sentence source) they go; back to counted the
    # file is searched once, for the tally the table sums
    root, counted, aside = two_files
    tok = ti.make_tokenizer("ja")
    sig = ti.build_signature("ja")
    store = ti.open_store("ja")
    try:
        store.reconcile([counted, aside], tok, build_signature=sig)
        before = store.phrase_matches([aside])[aside]
        read = _tallied(monkeypatch)
        store.reconcile([counted], tok, build_signature=sig, aside=[aside])
        assert read == [], "counted -> Finished: no file searched"
        assert store.phrase_matches([aside]) == {aside: before}
        store.reconcile([counted], tok, build_signature=sig, kept=[aside], aside=[])
        assert read == [] and store.phrase_matches([aside]) == {}, "kept: no matches, nothing searched"
        assert aside not in json.loads(store.get_meta("phrase_matches"))["files"]
        store.reconcile([counted], tok, build_signature=sig, aside=[aside], kept=[])
        assert len(read) == 1 and store.phrase_matches([aside]) == {aside: before}, "kept -> Finished: searched once"
        del read[:]
        store.reconcile([counted, aside], tok, build_signature=sig, aside=[])
        assert len(read) == 1, "Finished -> counted: searched once, for its tally"
        assert ti._norm(aside) in (store.phrase_tallies() or {}), "its tally counted again"
    finally:
        store.close()


def test_a_store_whose_last_table_kept_counted_files_alone_reads_the_finished_ones_in_once(two_files, monkeypatch):
    # why: a store indexed by the build before (schema 30, counted files' matches alone) is current by every stamp
    # but the new one, and a library that doesn't change would never read its Finished files in: they are, once,
    # with the counted files' tallies kept as they are
    root, counted, aside = two_files
    tok = ti.make_tokenizer("ja")
    sig = ti.build_signature("ja")
    store = ti.open_store("ja")
    try:
        store.reconcile([counted], tok, build_signature=sig, aside=[aside])
        kept = json.loads(store.get_meta("phrase_matches"))
        del kept["files"][ti._norm(aside)]
        for entry in kept["files"].values():
            del entry[4:]                       # the matches as the build before kept them: four numbers
        store.set_meta("phrase_matches", json.dumps(kept, ensure_ascii=False))
        state = json.loads(store.get_meta("phrases_state"))
        store.set_meta("phrases_state", json.dumps(state[:2]))
        assert store.phrase_matches([aside]) == {}
        read = _tallied(monkeypatch)
        store.reconcile([counted], tok, build_signature=sig, aside=[aside])
        assert len(read) == 1 and aside in store.phrase_matches([aside]), "the finished file read in, alone"
        store.reconcile([counted], tok, build_signature=sig, aside=[aside])
        assert len(read) == 1, "then current: nothing read again"
    finally:
        store.close()


# The finished walk counted in the child: PhraseSet.find calls and each walked file's mask (WalkFile.sentences).
_COUNT_HOOK = r"""
import atexit, json, os
from app import phrases as _ph, token_index as _ti
_c = {"find": 0, "masked": 0}
_find, _sentences = _ph.PhraseSet.find, _ti.WalkFile.sentences


def _counted_find(self, tokens, text):
    _c["find"] += 1
    return _find(self, tokens, text)


def _counted_sentences(self, mask):
    _c["masked"] += 1
    return _sentences(self, mask)
_ph.PhraseSet.find, _ti.WalkFile.sentences = _counted_find, _counted_sentences
if os.environ.get("DSA_PHRASE_SEARCH"):         # as before: no kept matches for a finished file — searched at Generate
    _matches = _ti.Store.phrase_matches
    _ti.Store.phrase_matches = lambda self, paths: {
        p: m for p, m in _matches(self, paths).items() if (self.conn.execute(
            "SELECT counted FROM files WHERE path=?", (_ti._norm(p),)).fetchone() or [0])[0] == 1}
atexit.register(lambda: open(os.environ["DSA_PHRASE_COUNT"] + "." + str(os.getpid()), "w").write(json.dumps(_c)))
"""


def _child_counts(base):
    total = Counter()
    for path in Path(base).parent.glob(Path(base).name + ".*"):
        total.update(json.loads(path.read_text()))
        path.unlink()
    return total


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_generate_searches_no_finished_sentence_for_set_phrases_and_walks_its_mask(tmp_path, language):
    # why: with phrase rows on (ja's default) every finished file's sentences were all built and searched at every
    # Generate. Real text: the token store's six files counted, a finished show of tests/Test Resources (its set phrases
    # among them), indexed once; then Generate: no sentence searched, each finished file walked on its mask, and the
    # lists byte for byte those of a Generate that searches the finished files as before. (zh has no set phrases: its
    # finished walk was already on its mask — a guard.)
    from tests.plan_file_cases import REPO, child_env
    from tests.test_finished_reference import FINISHED, _finished_show
    from tests.test_generate_missing_item import COMPARED
    from tests.test_token_store_kept import _library, _run_indexer
    root = os.environ["SURASURA_TEST_ROOT"]
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"logic": {"phrase_rows": True}}, f)
    store, _data_dir, ids = _library(language)
    sources = (["tests/Test Resources/ja/phrases_sample.srt"] + FINISHED["ja"]) if language == "ja" else None
    show = _finished_show(language, sources=sources)
    store.import_finished(show)
    store.close()
    _run_indexer(language)
    if language == "ja":
        with ti.open_store(language) as tokens:
            held = tokens.phrase_matches(show)
            assert set(held) == set(show) and held[show[0]][1], "the index found the finished show's phrases"
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(_COUNT_HOOK, encoding="utf-8")
    lists, counts = [], []
    # (the first Generate indexes the child's own token store, its finished files' phrases found then: not counted)
    for search in (None, False, True):
        env = child_env(root)
        env.update(SURASURA_FORCE_RUN="1", DSA_PHRASE_COUNT=str(tmp_path / "count"),
                   PYTHONPATH=str(hook) + os.pathsep + env["PYTHONPATH"])
        if search:
            env["DSA_PHRASE_SEARCH"] = "1"
        p = subprocess.run([sys.executable, os.path.join(REPO, "app", "analyzer.py"), f"--language={language}",
                            "--static", "--no-open", "--min-freq", "1"], cwd=REPO, env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
        made = {}
        for name in COMPARED:
            with open(os.path.join(root, "results", name), "rb") as f:
                made[name] = f.read()
        if search is None:
            _child_counts(tmp_path / "count")
            continue
        lists.append(made)
        counts.append(_child_counts(tmp_path / "count"))
    assert len(lists[0]["priority_learning_list.csv"].splitlines()) > 5, "some words listed"
    assert lists[0] == lists[1], "the kept matches list what a search lists"
    shipped, searched = counts
    assert shipped["find"] == 0, f"no sentence searched for set phrases at Generate: {shipped}"
    assert shipped["masked"] >= len(show), f"each finished file walked on its mask: {shipped}"
    if language == "ja":
        assert searched["find"] > 0 and searched["masked"] < shipped["masked"], ("the search as before", searched)


# ---------------------------------------------------------------------------------------------------- #
# 2. The start's stat pass: one listing a folder
# ---------------------------------------------------------------------------------------------------- #
def _every_resource():
    """Every real file under tests/Test Resources (nested folders, ja + zh, mixed scripts in their names)."""
    out = []
    for folder, _dirs, names in os.walk(RESOURCES):
        out += [os.path.join(folder, name) for name in names]
    return out


def test_one_listing_gives_every_files_signature_as_os_stat_does():
    # why: the listing replaces os.stat only if its numbers are os.stat's — the reconcile compares them with the rows
    # it wrote before, so one differing digit re-indexes a file at every start. Every real test file (nested), a file
    # that isn't there (None, as file_signature's OSError), a folder that isn't there, and the same file spelled twice
    paths = _every_resource()
    assert len(paths) > 50 and len({os.path.dirname(p) for p in paths}) > 3
    gone = os.path.join(RESOURCES, "ja", "no_such_file.srt")
    nowhere = os.path.join(RESOURCES, "no_such_folder", "x.txt")
    twice = os.path.join(RESOURCES, "ja", ".", os.path.basename(PHRASES_SAMPLE))
    found = ti._signatures(paths + [gone, nowhere, twice])
    assert {p: found[p] for p in paths} == {p: ti.file_signature(p) for p in paths}
    assert found[gone] is None and found[nowhere] is None
    assert found[twice] == ti.file_signature(PHRASES_SAMPLE)
    assert ti._signatures([]) == {}


def _stats_counted(monkeypatch):
    """Each `file_signature` (one os.stat a file) the token store makes."""
    asked = []
    real = ti.file_signature
    monkeypatch.setattr(ti, "file_signature", lambda path: asked.append(path) or real(path))
    return asked


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_start_check_and_the_reconcile_stat_no_file_one_by_one(tmp_path, language, monkeypatch):
    # why: `index_needed` (every start) and the reconcile (every index, every Generate) stat'ed each listed file once
    # more (20k: 20,000 os.stat, ~0.46 s a pass); one listing a folder reads them all. Real files in nested show folders;
    # the check still sees a file changed between two checks (the listing is read fresh each time, never kept), a file
    # gone, and a new one
    source = os.path.join(RESOURCES, language)
    data = Path(os.environ["SURASURA_TEST_ROOT"]) / "data" / language / "HighPriority"
    files = []
    for n, name in enumerate(sorted(n for n in os.listdir(source) if n.endswith((".srt", ".txt")))[:8]):
        folder = data / f"show{n % 3}" / f"第{n % 2 + 1}期"
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy(os.path.join(source, name), folder / name)
        files.append(str(folder / name))
    assert len(files) >= 6
    new = str(data / "show0" / "new.srt")
    store = ti.open_store(language)
    try:
        asked = _stats_counted(monkeypatch)
        store.reconcile(files, ti.make_tokenizer(language))
        assert asked == [], "the reconcile's signatures from the listings"
        assert store.needs_reconcile(files) is False
        assert asked == [], "the start's check: no file stat'ed one by one"
        time.sleep(0.05)
        with open(files[2], "a", encoding="utf-8") as f:
            f.write("\n")
        assert store.needs_reconcile(files) is True, "an edit between two checks is seen"
        store.reconcile(files, ti.make_tokenizer(language))
        assert store.needs_reconcile(files) is False and asked == []
        os.remove(files[4])
        assert store.needs_reconcile(files) is True, "a listed file gone: its text is kept first"
        store.reconcile(files, ti.make_tokenizer(language))
        assert store.needs_reconcile(files) is False, "then its row stays as it is"
        assert store.needs_reconcile(files + [new]) is False, "a listed file not there yet"
        shutil.copy(files[0], new)
        assert store.needs_reconcile(files + [new]) is True, "and there"
        assert set(asked) == {files[4], new}, "os.stat only for a name no listing gave"
    finally:
        store.close()

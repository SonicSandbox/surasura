"""The token store's set-aside class (W-1, K-W2): a watched episode leaves every count, and stays the names' evidence.

A watched episode (a stone, while the library's *Keep studying watched episodes* is off) leaves the list as Finished
does, but a stone must never change what a word IS. So the token store keeps the file's tokens (no re-tokenizing when it
moves between counted, aside and kept, either way), sums none of it — the counts, `bound`, the totals, the phrase table,
the name tables' adjustment, the Rarity slider's numbers and cut-off leave it exactly as they leave a Finished file —
and still reads it as the name tables' evidence (`reconcile(..., aside=)`, `files.aside`).

What a wrong answer would cost a learner:
  * a stone that re-tokenizes an episode (a slow index on every mark and un-mark);
  * a watched episode's words still in the Rarity slider's numbers, so the slider and the list disagree on the cut-off;
  * a character's name, met in every episode, splitting into pieces in the episodes still ahead once the first ones
    are watched (the name tables lose their evidence) — a flood of fake words on the list;
  * a Generate before the indexer dropping a watched episode's row, so its sentences and names are gone until the
    indexer tokenizes it all again.

Real Japanese and Chinese text (testing.md): the samples, the test resources and, for the names, a short show cut
from tests/Test Resources/ja's subtitles with a made-up recurring katakana name (メロン + ベンチ: two common words, a
name only through the library's table — tests/test_names.py), all under the per-test SURASURA_TEST_ROOT.
"""
import os
import re
import sqlite3
from collections import Counter

import pytest

from app import analyzer, token_index as ti
from tests.test_library_store_support import LANGUAGES, roots
from tests.test_token_store_kept import _counting, _everything_counted, _files, _kept_text, _lemmas, _library

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(REPO, "tests", "Test Resources", "ja")
NAME = "メロンベンチ"
# One use per episode: three uses — the library's floor — only with every episode; the name's pieces never stand alone.
NAME_LINES = ("メロンベンチで待ち合わせよう。", "メロンベンチの前に集合ね。", "今日もメロンベンチに座った。")


def _cues(name):
    """The cue texts of a real subtitle in tests/Test Resources/ja, in order."""
    with open(os.path.join(RES, name), encoding="utf-8") as f:
        blocks = re.split(r"\n\s*\n", f.read().strip())
    return [" ".join(block.splitlines()[2:]) for block in blocks if len(block.splitlines()) > 2]


def _srt(lines):
    out = []
    for i, line in enumerate(lines, 1):
        out.append(f"{i}\n00:00:{i * 2:02d},000 --> 00:00:{i * 2 + 1:02d},500\n{line}\n")
    return "\n".join(out)


def _show(folder="HighPriority/空の庭"):
    """A three-episode show (nested in its show folder) of real subtitle cues, the recurring name once in each: paths."""
    data_dir, _u = roots("ja")
    placed, phrases = _cues("placed_episode.srt"), _cues("phrases_sample.srt")
    parts = (placed[:5], placed[5:], phrases[:8])
    paths = []
    for n, (cues, name_line) in enumerate(zip(parts, NAME_LINES), 1):
        path = os.path.join(data_dir, *folder.split("/"), f"空の庭 第{n}話.srt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_srt(cues[:2] + [name_line] + cues[2:]))
        paths.append(path)
    return paths


def _names_bytes(store):
    """What the name tables are, byte for byte: the tables and the names Ignore names reads, as stored, and the
    records the arrivals gate sums."""
    return (store.get_meta("names_tables"), store.get_meta("names_words"), store.names_records())


def _surfaces(store, path):
    return [t[2] for _s, tokens in store.file_tokens(path) for t in tokens]


def _listed(store, paths, language):
    """What the list counts: the counted files' cached tokens, read as Generate reads them (the name tables applied),
    counted as the store's totals count (a token holding the language's script)."""
    listed = Counter()
    for path in paths:
        for _s, tokens in store.file_tokens(path):
            for lemma, reading, surface, *_rest in tokens:
                if analyzer.has_target_language(lemma, language) or analyzer.has_target_language(surface, language):
                    listed[(lemma, reading)] += 1
    return listed


def _counts_only(store, language):
    """Every count the list and the Rarity slider read (`_everything_counted` less the name tables, which read the
    set-aside files too)."""
    counted = _everything_counted(store, language)
    counted.pop("names")
    return counted


# --------------------------------------------------------------------------- #
# The class: never summed, moved with no tokenizing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_file_moves_counted_aside_kept_and_back_with_no_tokenizing(language, tmp_path):
    """Watched, then Finished, then put back, then watched and un-marked: each move re-tokenizes nothing; set aside,
    every count is a Finished file's (the reference store holds it kept); the dashboard's check sees each move and is
    quiet after it."""
    a, b, c, d, *_rest = _files(language)
    tok = _counting(language)
    store = ti.open_store(language)
    store.reconcile([a, b, c], tok, kept=[d])
    all_three = _everything_counted(store, language)
    tok.calls.clear()

    assert store.needs_reconcile([a, b], kept=[d], aside=[c]) is True, "a stone: its counts must move out"
    store.reconcile([a, b], tok, kept=[d], aside=[c])                    # c watched
    assert tok.calls == [], "a stone re-tokenizes nothing"
    assert store.aside_files() == [ti._norm(c)] and set(store.counted_files()) == {ti._norm(a), ti._norm(b)}
    assert store.kept_files() == [ti._norm(d)]
    assert store.needs_reconcile([a, b], kept=[d], aside=[c]) is False
    finished = ti.open_store(language, path=str(tmp_path / "finished.db"))
    finished.reconcile([a, b], ti.make_tokenizer(language), kept=[c, d])
    assert _counts_only(store, language) == _counts_only(finished, language), "set aside = Finished, for every count"
    assert store.names_tables() == all_three["names"], "...but still the names' evidence"
    # Not vacuous: c holds words a and b don't; they are cached, never counted.
    only_c = _lemmas(store, c) - _lemmas(store, a) - _lemmas(store, b)
    assert only_c and not only_c & {lemma for lemma, _r in store.word_counts()[0]}

    store.reconcile([a, b], tok, kept=[d, c], aside=[])                  # aside -> Finished: no count moves
    assert tok.calls == [] and _counts_only(store, language) == _counts_only(finished, language)
    assert set(store.kept_files()) == {ti._norm(c), ti._norm(d)} and store.aside_files() == []

    assert store.needs_reconcile([a, b, c], kept=[d], aside=[]) is True
    store.reconcile([a, b, c], tok, kept=[d], aside=[])                  # put back: counted again
    assert tok.calls == [] and _everything_counted(store, language) == all_three

    store.reconcile([a, b], tok, kept=[d], aside=[c])                    # watched again...
    store.reconcile([a, b, c], tok, kept=[d], aside=[])                  # ...and un-marked
    assert tok.calls == [] and _everything_counted(store, language) == all_three
    assert store.needs_reconcile([a, b, c], kept=[d], aside=[]) is False
    # A set-aside file's text is kept as a kept one's, from its first read (W-1b): c's, set aside above, and d's.
    assert set(_kept_text(store).held()) == {ti._norm(c), ti._norm(d)}
    store.close()
    finished.close()


def test_a_kept_aside_flip_reads_the_names_again_and_leaves_the_phrase_table_alone(monkeypatch):
    """Finished to watched and back (kept <-> aside) moves no count but the names' evidence: the name tables are
    computed again; the phrase table reads counted files alone, so it is neither counted again nor written (S19). A
    counted file set aside still moves it (not vacuous)."""
    a, b, _c, c, *_rest = _files("ja")         # c: its names change nothing the name tables join (a flip of
    tok = _counting("ja")                       # one that does reads the phrases again: they read through them)
    store = ti.open_store("ja")
    store.reconcile([a, b], tok, kept=[c])
    assert store.get_meta("phrases_state"), "the phrase table is counted here"
    written, names = [], []
    set_meta, update_names = ti.Store.set_meta, ti.Store._update_names_tables

    def spy_meta(self, key, value):
        written.append(key)
        return set_meta(self, key, value)

    def spy_names(self, *args, **kw):
        names.append(1)
        return update_names(self, *args, **kw)
    with monkeypatch.context() as patched:
        patched.setattr(ti.Store, "set_meta", spy_meta)
        patched.setattr(ti.Store, "_update_names_tables", spy_names)
        store.reconcile([a, b], tok, kept=[], aside=[c])                 # Finished -> watched in Current
        store.reconcile([a, b], tok, kept=[c], aside=[])                 # ... and back
        assert names == [1, 1] and [k for k in written if k.startswith("phrase")] == []
        store.reconcile([a], tok, kept=[c], aside=[b])                   # a counted episode watched
        assert names == [1, 1, 1] and "phrases" in written
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_or_changed_aside_file_is_read_once_and_never_summed(language, tmp_path):
    """An episode that arrives already watched is tokenized once (in the pool, as a counted file is), its text kept as
    a kept file's (W-1b: reference text outlives its file), and summed nowhere; edited while watched, it is read again,
    its kept text follows the edit, and it is still summed nowhere."""
    a, b, c, *_rest = _files(language)
    tok = _counting(language)
    store = ti.open_store(language)
    store.reconcile([a, b], tok, aside=[c])
    assert tok.calls.count(("file", ti._norm(c))) == 1
    alone = ti.open_store(language, path=str(tmp_path / "alone.db"))
    alone.reconcile([a, b], ti.make_tokenizer(language))
    assert _counts_only(store, language) == _counts_only(alone, language)
    assert _kept_text(store).held() == {ti._norm(c): False}, "its text kept, read from its file"
    with open(c, "a", encoding="utf-8") as f:
        f.write({"ja": "\n今日は雨が降っている。\n", "zh": "\n今天下雨了。\n"}[language])
    assert store.needs_reconcile([a, b], aside=[c]) is True
    store.reconcile([a, b], tok, aside=[c])
    assert tok.calls.count(("file", ti._norm(c))) == 2 and _counts_only(store, language) == _counts_only(alone, language)
    assert "今" in _kept_text(store).get(ti._norm(c))[0], "the kept text is the edited file's"
    store.close()
    alone.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_caller_with_one_list_leaves_the_aside_rows_alone(language, tmp_path):
    """Generate with the library store busy and the sentence dictionary (`reconcile_language`) know only the run's
    list: a set-aside row stays aside, its tokens and its place in no count; a caller that names the aside list
    (the indexer) drops one it no longer names, as a counted file leaves — taking no count with it."""
    a, b, c, *_rest = _files(language)
    alone = ti.open_store(language, path=str(tmp_path / "alone.db"))
    alone.reconcile([a, b], ti.make_tokenizer(language))
    with ti.open_store(language) as store:
        store.reconcile([a, b], ti.make_tokenizer(language), aside=[c])
        before = (_everything_counted(store, language), store.file_tokens(c))
    with ti.open_store(language) as store:
        store.reconcile([a, b], ti.make_tokenizer(language), build_signature=ti.build_signature(language))
        assert store.aside_files() == [ti._norm(c)]
    ti.reconcile_language(language, [a, b])
    with ti.open_store(language) as store:
        assert store.aside_files() == [ti._norm(c)]
        assert (_everything_counted(store, language), store.file_tokens(c)) == before
        store.reconcile([a, b], ti.make_tokenizer(language), aside=[])
        assert store.aside_files() == [] and store.file_tokens(c) == []
        # An aside row was never summed: its leaving takes nothing away (the counts are a and b's alone).
        assert _counts_only(store, language) == _counts_only(alone, language)
    alone.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_generate_with_the_library_store_unreadable_drops_no_row_its_list_doesnt_name(language, monkeypatch, tmp_path):
    """A stone on b after the last index, then a Generate while the library store is busy (or read-only): the run's
    list holds a alone (b and c are watched). b's row is still counted in the token store — it must not go (its
    tokens read again at the un-mark): every row the run's list doesn't name is handed on set aside, summed nowhere,
    so the list's counts are a's alone; the indexer's next pass, with the library's lists, tokenizes nothing."""
    from app import indexer
    a, b, c, *_rest = _files(language)
    tok = _counting(language)
    store = ti.open_store(language)
    store.reconcile([a, b], tok, aside=[c])                              # indexed: c watched earlier
    tokens = {p: store.file_tokens(p) for p in (b, c)}
    tok.calls.clear()
    with monkeypatch.context() as patched:
        patched.setattr(indexer, "token_store_lists", lambda *_a: (None, None))     # the library store can't be read
        counted, more = indexer.run_lists(language, os.path.dirname(a), [a], store)
    store.reconcile(counted, tok, **more)
    assert tok.calls == [] and {p: store.file_tokens(p) for p in (b, c)} == tokens
    assert store.counted_files() == [ti._norm(a)] and set(store.aside_files()) == {ti._norm(b), ti._norm(c)}
    alone = ti.open_store(language, path=str(tmp_path / "alone.db"))
    alone.reconcile([a], ti.make_tokenizer(language))
    assert _counts_only(store, language) == _counts_only(alone, language), "the list counts a alone"
    assert store.needs_reconcile([a], aside=[b, c]) is False, "the indexer's pass has nothing to do"
    assert indexer.run_lists(language, os.path.dirname(a), [a], store) == ([a], {})  # no library store: as before
    store.close()
    alone.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_before_the_aside_column_opens_with_no_rebuild(language, tmp_path):
    """A 3.0 store from before K-W2 (the counted flag, no aside column) gets the column in place — nothing aside,
    nothing wiped or re-tokenized, every number as it was (no SCHEMA_VERSION bump)."""
    files = _files(language)[:4]
    db = str(tmp_path / "before.db")
    store = ti.open_store(language, path=db)
    store.reconcile(files[:3], ti.make_tokenizer(language), build_signature=ti.build_signature(language),
                    kept=files[3:])
    before = _everything_counted(store, language)
    store.close()
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE files_old (path TEXT PRIMARY KEY, mtime REAL, size INTEGER, total INTEGER, counts BLOB, "
        "tokens BLOB, names BLOB, bound BLOB, counted INTEGER NOT NULL DEFAULT 1);"
        "INSERT INTO files_old SELECT path, mtime, size, total, counts, tokens, names, bound, counted FROM files "
        "ORDER BY rowid; DROP TABLE files; ALTER TABLE files_old RENAME TO files;")
    conn.commit()
    conn.close()

    tok = _counting(language)
    store = ti.open_store(language, path=db)
    assert "aside" in [r[1] for r in store.conn.execute("PRAGMA table_info(files)")]
    assert store.aside_files() == [] and store.kept_files() == [ti._norm(files[3])]
    assert _everything_counted(store, language) == before
    store.reconcile(files[:3], tok, build_signature=ti.build_signature(language), kept=files[3:])
    assert tok.calls == [] and _everything_counted(store, language) == before
    store.close()


def _before_the_aside_column(db):
    """The store at `db` as a 3.0 build before the set-aside mark left it: the counted flag, no aside column."""
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE files_old (path TEXT PRIMARY KEY, mtime REAL, size INTEGER, total INTEGER, counts BLOB, "
        "tokens BLOB, names BLOB, bound BLOB, counted INTEGER NOT NULL DEFAULT 1);"
        "INSERT INTO files_old SELECT path, mtime, size, total, counts, tokens, names, bound, counted FROM files "
        "ORDER BY rowid; DROP TABLE files; ALTER TABLE files_old RENAME TO files;")
    conn.commit()
    conn.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_reader_of_a_store_before_the_aside_column_reads_the_names_evidence_and_writes_nothing(language, tmp_path):
    """The arrivals worker opens the token store to read only: on a store no writer has opened since the set-aside
    mark came in, its name records are the counted files' (as that store reads them), never "no such column" — and the
    reader adds no column (readers never write)."""
    files = _files(language)[:4]
    db = str(tmp_path / "before.db")
    store = ti.open_store(language, path=db)
    store.reconcile(files[:3], ti.make_tokenizer(language), build_signature=ti.build_signature(language),
                    kept=files[3:])
    counted = [ti._decode_counts(r[0]) for r in store.conn.execute(
        "SELECT names FROM files WHERE names IS NOT NULL AND counted = 1 ORDER BY rowid")]
    store.close()
    _before_the_aside_column(db)
    reader = ti.open_reader(language, path=db)
    try:
        assert reader.names_records() == counted
        assert list(reader.iter_names_records()) == counted
    finally:
        reader.close()
    conn = sqlite3.connect(db)
    assert "aside" not in [r[1] for r in conn.execute("PRAGMA table_info(files)")]
    conn.close()


def test_a_build_before_the_aside_column_reads_an_aside_row_as_kept(tmp_path):
    """The column's guarantee to a build that doesn't know it (a rollback): an aside row is `counted` 0, so every sum
    that build reads (`counted = 1`) leaves it out, as this build does — neither build's counts go wrong."""
    a, b, c, *_rest = _files("ja")
    store = ti.open_store("ja", path=str(tmp_path / "s.db"))
    store.reconcile([a, b], ti.make_tokenizer("ja"), aside=[c])
    row = store.conn.execute("SELECT counted, aside FROM files WHERE path=?", (ti._norm(c),)).fetchone()
    assert tuple(row) == (0, 1)
    assert store.conn.execute("SELECT COALESCE(SUM(total), 0) FROM files WHERE counted = 1").fetchone()[0] == \
        store.total_tokens()
    store.close()


# --------------------------------------------------------------------------- #
# The names' evidence
# --------------------------------------------------------------------------- #
def test_the_name_tables_are_byte_identical_with_every_episode_watched_and_with_none(tmp_path):
    """A recurring name, once an episode: three uses — the floor — only with every episode. Watched one by one (and
    all of them, and from scratch), the name tables, the names Ignore names reads and the arrivals gate's records are
    byte for byte those of no episode watched, and the episode still ahead reads the name whole. Finished episodes are
    evidence too (W-1b); kept text alone (a New arrival, a removed item) isn't, and would split it: the proof the
    evidence is what holds it."""
    eps = _show()
    sig = ti.build_signature("ja")
    tok = _counting("ja")
    none = ti.open_store("ja", path=str(tmp_path / "none.db"))
    none.reconcile(eps, ti.make_tokenizer("ja"), sig)
    reference = _names_bytes(none)
    assert NAME in none.names_tables()["k"], "the show's name joins with every episode counted"

    store = ti.open_store("ja")
    store.reconcile(eps, tok, sig)
    tok.calls.clear()
    for watched in (1, 2, 3):
        store.reconcile(eps[watched:], tok, sig, aside=eps[:watched])
        assert _names_bytes(store) == reference, f"{watched} watched"
        assert tok.calls == []
    assert store.counted_files() == [] and store.total_tokens() == 0, "every episode watched: nothing counts"
    store.reconcile(eps[2:], tok, sig, aside=eps[:2])
    assert NAME in _surfaces(store, eps[2]), "the episode still ahead reads the name whole"
    assert (NAME, "") in store.word_counts()[0], "...and the list counts it as one word"
    store.reconcile(eps, tok, sig, aside=[])
    assert _names_bytes(store) == reference and tok.calls == []
    store.close()

    every = ti.open_store("ja", path=str(tmp_path / "every.db"))
    every.reconcile([], ti.make_tokenizer("ja"), sig, aside=eps)
    assert _names_bytes(every) == reference, "a library indexed with every episode already watched"
    every.close()

    # Finished is reference too (W-1b): the library hands its episodes over as set aside, so they hold the name whole.
    finished = ti.open_store("ja", path=str(tmp_path / "finished.db"))
    finished.reconcile(eps[2:], ti.make_tokenizer("ja"), sig, aside=eps[:2])
    # The tables and the names as stored; the records as a set (this store met the episode ahead first).
    assert _names_bytes(finished)[:2] == reference[:2], "Finished episodes are evidence, as watched ones are"
    assert sorted(map(repr, finished.names_records())) == sorted(map(repr, reference[2]))
    assert NAME in _surfaces(finished, eps[2])
    finished.close()
    # Kept text alone (New arrivals, removed items) is no evidence: one use is under the floor (the test can fail).
    kept = ti.open_store("ja", path=str(tmp_path / "kept.db"))
    kept.reconcile(eps[2:], ti.make_tokenizer("ja"), sig, kept=eps[:2])
    assert NAME not in kept.names_tables()["k"] and NAME not in _surfaces(kept, eps[2])
    kept.close()
    none.close()


def test_a_watched_episode_edited_to_hold_the_name_makes_the_name_tables_count_it(tmp_path):
    """The first episode, watched, holds no use of the show's name: two uses, under the floor, so the name isn't joined.
    Its subtitle is then edited (a corrected line holding the name): the episode is read again while still set aside,
    and its new use is the names' evidence at once — the third use, so the name tables join it and the episode still
    ahead reads it whole, as a library that never lacked the line does."""
    eps = _show()
    sig = ti.build_signature("ja")
    with open(eps[0], encoding="utf-8") as f:
        whole = f.read()
    with open(eps[0], "w", encoding="utf-8", newline="\n") as f:
        f.write(whole.replace(NAME_LINES[0], "公園で待ち合わせよう。"))
    store = ti.open_store("ja")
    store.reconcile(eps[1:], ti.make_tokenizer("ja"), sig, aside=eps[:1])
    assert NAME not in store.names_tables()["k"], "precondition: two uses are under the floor"
    with open(eps[0], "w", encoding="utf-8", newline="\n") as f:
        f.write(whole)
    store.reconcile(eps[1:], ti.make_tokenizer("ja"), sig, aside=eps[:1])
    reference = ti.open_store("ja", path=str(tmp_path / "reference.db"))
    reference.reconcile(eps[1:], ti.make_tokenizer("ja"), sig, aside=eps[:1])
    assert NAME in store.names_tables()["k"] and _names_bytes(store) == _names_bytes(reference)
    assert NAME in _surfaces(store, eps[2])
    store.close()
    reference.close()


def test_the_rarity_preview_counts_what_the_list_counts_with_watched_episodes(tmp_path):
    """Two episodes watched, the last ahead: the Rarity slider's totals (the name tables' joins included) are the list's
    count of the counted episode's cached tokens; the bound table and the phrase table are a Finished show's; the
    watched episodes' words and idioms (文化祭, 腑に落ちる in episode 2) reach neither."""
    eps = _show()
    sig = ti.build_signature("ja")
    store = ti.open_store("ja")
    store.reconcile(eps[2:], ti.make_tokenizer("ja"), sig, aside=eps[:2])
    counts, total = store.word_counts()
    listed = _listed(store, eps[2:], "ja")
    assert counts == dict(listed) and total == sum(listed.values())
    finished = ti.open_store("ja", path=str(tmp_path / "finished.db"))
    finished.reconcile(eps[2:], ti.make_tokenizer("ja"), sig, kept=eps[:2])
    assert store.bound_counts() == finished.bound_counts()
    assert store.phrase_table() == finished.phrase_table()
    assert store.phrase_tallies().keys() == {ti._norm(eps[2])}
    watched_words = {lemma for lemma, _r in _listed(store, eps[:2], "ja")} - {lemma for lemma, _r in listed}
    assert "文化祭" in watched_words and not watched_words & {lemma for lemma, _r in counts}
    preview = store.unknown_frequencies()
    assert not watched_words & {key.split("|")[0] for key, _n in preview["unknown"]}
    assert preview["total_tokens"] == total
    store.close()
    finished.close()


# --------------------------------------------------------------------------- #
# The indexer and Generate, through a real library store
# --------------------------------------------------------------------------- #
def _in_generates_process(root, language, code):
    """The last line `code` prints in a process with Generate's environment — its token store (the test root's, not
    this process's isolated one) and its library store."""
    from tests.test_generate_missing_item import _child
    head = (f"import hashlib, json, sys; from app import indexer, token_index as ti; "
            f"from app.path_utils import get_data_path; d = get_data_path('{language}'); ")
    return _child(root, head + code)


@pytest.mark.parametrize("language", LANGUAGES)
def test_generate_before_the_indexer_keeps_a_watched_files_row(language):
    """Indexed, then a stone, then a Generate before the indexer runs again: Generate's own list lacks the watched
    episode, but it reconciles with the library store's lists, so the row stays (set aside, its tokens cached as they
    were) and the indexer has nothing left to tokenize."""
    from tests.test_generate_missing_item import _generate
    root = os.environ["SURASURA_TEST_ROOT"]
    store, _data_dir, ids = _library(language)
    watched = list(ids)[0]
    index = f"sys.argv = ['indexer.py', '--language', '{language}']; indexer.main(); print('indexed')"
    row = (f"s = ti.open_store('{language}'); print(hashlib.sha256(json.dumps(s.file_tokens({watched!r}), "
           f"ensure_ascii=False).encode()).hexdigest(), s.aside_files() == [ti._norm({watched!r})])")
    assert _in_generates_process(root, language, index).endswith("indexed")
    before = _in_generates_process(root, language, row)
    assert before.endswith(" False"), before
    store.set_watched([ids[watched]])
    store.close()

    _generate(root, language)
    after = _in_generates_process(root, language, row)
    assert after == before.replace(" False", " True"), "Generate kept the watched episode's row, set aside"
    quiet = (f"c, m = indexer.token_store_lists('{language}', d, indexer._content_files(d, '{language}')); "
             f"s = ti.open_store('{language}'); print(s.needs_reconcile(c, **m))")
    assert _in_generates_process(root, language, quiet) == "False", "the indexer has nothing left to do"


@pytest.mark.parametrize("language", LANGUAGES)
def test_set_aside_files_text_is_written_a_few_at_a_time_never_all_held_at_once(language, monkeypatch, tmp_path):
    """A first index of many set-aside files (a big Finished library, or every watched episode after an upgrade) keeps
    each one's text as it is read, written to the kept-text file a few at a time (`KEPT_TEXT_BATCH`), so the index never
    holds every file's text at once: here at most two held, every text kept, the same as one write would keep. Both
    ways in: tokenized in the pool (new to the store), and read for a row the store already holds (counted, then set
    aside)."""
    files = _files(language)
    monkeypatch.setattr(ti, "KEPT_TEXT_BATCH", 2)
    sizes, real_put = [], ti._KeptText.put

    def put(self, rows):
        sizes.append(len(rows))
        return real_put(self, rows)
    monkeypatch.setattr(ti._KeptText, "put", put)
    tok = ti.make_tokenizer(language)
    store = ti.open_store(language, path=str(tmp_path / "pool.db"))
    store.reconcile(files[:1], tok, aside=files[1:])
    assert set(_kept_text(store).held()) == {ti._norm(p) for p in files[1:]}, "every set-aside file's text is kept"
    assert sizes and max(sizes) <= 2, sizes
    _kept_text(store).drop([ti._norm(p) for p in files[1:]])         # the kept-text file is the library's: empty it
    store.close()

    sizes.clear()
    held = ti.open_store(language, path=str(tmp_path / "held.db"))
    held.reconcile(files, tok)                                         # every row counted, no text kept
    held.reconcile(files[:1], tok, aside=files[1:])                    # then set aside: each text read now
    assert set(_kept_text(held).held()) == {ti._norm(p) for p in files[1:]}
    assert sizes and max(sizes) <= 2, sizes
    held.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_set_aside_file_back_on_the_disk_through_a_wipe_keeps_its_own_text_never_the_rebuilt_one(language):
    """A counted episode's file goes missing (an unplugged drive): its text is kept, rebuilt from its cached sentences.
    It comes back unchanged as it is set aside (watched, or Finished) in the same pass that wipes the token store (a new
    tokenizer identity): tokenized again in the pool, its text is kept as read from its file this time — never left as
    the rebuilt copy, which has lost the file's line breaks, for a later wipe to read back in."""
    a, b, *_rest = _files(language)
    tok = ti.make_tokenizer(language)
    store = ti.open_store(language)
    store.reconcile([a, b], tok, build_signature="one")
    away = b + ".away"
    os.replace(b, away)
    store.reconcile([a, b], tok, kept=[], build_signature="one")
    assert _kept_text(store).held() == {ti._norm(b): True}, "its file gone: rebuilt from the cached sentences"
    os.replace(away, b)                                     # back as it was: the same modified time and size
    store.reconcile([a], tok, kept=[], aside=[b], build_signature="two")
    assert ti._norm(b) in store.aside_files()
    assert _kept_text(store).held() == {ti._norm(b): False}, "read from its file"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_everyday_reconcile_of_set_aside_files_with_nothing_kept_writes_no_text_again(language, monkeypatch):
    """A library with Finished content (set aside) and no New arrival or removed item (no kept list): once their text is
    kept, a reconcile with nothing changed writes none of it again — the indexer never re-reads every Finished file at
    each pass."""
    a, b, c, *_rest = _files(language)
    tok = ti.make_tokenizer(language)
    store = ti.open_store(language)
    store.reconcile([a], tok, kept=[], aside=[b, c])
    assert set(_kept_text(store).held()) == {ti._norm(b), ti._norm(c)}
    written, real_put = [], ti._KeptText.put

    def put(self, rows):
        written.extend(rows)
        return real_put(self, rows)
    monkeypatch.setattr(ti._KeptText, "put", put)
    store.reconcile([a], tok, kept=[], aside=[b, c])
    assert written == [], "nothing changed: no text written again"
    store.close()


def test_an_alter_table_failure_other_than_a_duplicate_column_is_raised_not_passed_over(tmp_path):
    """The counted / aside columns are added by ALTER TABLE; a failure that is not a duplicate column (here a
    `files` that is a view, so the column can't be added) must raise, never read as the columns already being there."""
    conn = sqlite3.connect(str(tmp_path / "view.db"))
    try:
        conn.executescript(
            "CREATE TABLE files_base (path TEXT PRIMARY KEY);"
            "CREATE VIEW files AS SELECT path FROM files_base;")
        with pytest.raises(sqlite3.OperationalError) as info:
            ti._add_counted(conn)
        assert "duplicate column" not in str(info.value).lower()
    finally:
        conn.close()

"""The store's phrase tallies are not read once the state they were kept under is stale (E2.2 gate T1)."""

import json
import os

from app import token_index

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "ja")


def test_phrase_tallies_are_not_read_when_the_kept_state_no_longer_matches(tmp_path):
    """A store whose phrase tallies were kept under another phrase-data state reads as None, though every file's
    entry still matches its (mtime, size) — the arrivals gate must not trust tallies the store would not hand out
    today. The same store reads them as a dict before the state is rewritten, so the None is the stale state's doing."""
    files = [os.path.join(RESOURCES, "phrases_sample.srt")]
    store = token_index.open_store("ja", path=str(tmp_path / "t.db"))
    try:
        store.reconcile(files, token_index.make_tokenizer("ja"), build_signature=token_index.build_signature("ja"))
        assert isinstance(store.phrase_tallies(), dict)
        kept = json.loads(store.get_meta("phrase_files"))
        kept["state"] = "phrase data from another revision"
        store.set_meta("phrase_files", json.dumps(kept, ensure_ascii=False))
        assert store.phrase_tallies() is None
    finally:
        store.close()


def test_phrase_sums_are_the_tallies_summed_and_read_only_while_every_counted_file_is_current(tmp_path):
    """E2.3: the arrivals gate reads the phrases' sums one file's tally at a time (`Store.phrase_sums`) instead of
    every file's tallies at once — the same uses and spellings as summing `phrase_tallies`, over the counted files
    only (a kept file's tally never counts), and None whenever `phrase_tallies` is None: a stale state, or a counted
    file whose entry no longer matches its (mtime, size)."""
    from collections import Counter
    files = [os.path.join(RESOURCES, name) for name in ("phrases_sample.srt", "library_episode.ass")]
    store = token_index.open_store("ja", path=str(tmp_path / "t.db"))
    try:
        store.reconcile(files, token_index.make_tokenizer("ja"), build_signature=token_index.build_signature("ja"))
        tallies = store.phrase_tallies()
        uses, spellings = Counter(), {}
        for file_uses, _given in tallies.values():
            for index, (n, spelled) in file_uses.items():
                uses[int(index)] += n
                held = spellings.setdefault(int(index), [])
                held.extend(x for x in spelled if x not in held)
        assert uses, "the sample holds set phrases"
        assert store.phrase_sums() == (uses, spellings)
        kept = json.loads(store.get_meta("phrase_files"))
        path = next(iter(kept["files"]))
        kept["files"][path][1] += 1                     # one counted file's entry no longer matches its size
        store.set_meta("phrase_files", json.dumps(kept, ensure_ascii=False))
        assert store.phrase_tallies() is None and store.phrase_sums() is None
        kept["files"][path][1] -= 1
        kept["state"] = "phrase data from another revision"
        store.set_meta("phrase_files", json.dumps(kept, ensure_ascii=False))
        assert store.phrase_tallies() is None and store.phrase_sums() is None
    finally:
        store.close()


def _store_with(tmp_path, file_names, language="ja"):
    files = [os.path.join(RESOURCES, name) for name in file_names]
    store = token_index.open_store(language, path=str(tmp_path / f"{language}.db"))
    store.reconcile(files, token_index.make_tokenizer(language), build_signature=token_index.build_signature(language))
    return store


def _rewrite(store, kept):
    store.set_meta("phrase_files", json.dumps(kept, ensure_ascii=False))


def test_phrase_sums_add_one_phrase_over_files_and_keep_each_spelling_once(tmp_path):
    """E2.3 (planted bugs): a phrase met in two counted files gets both files' uses, and its spellings each once, in
    the order met. The sample library meets no phrase in two files, so the two files' tallies are written so."""
    store = _store_with(tmp_path, ("phrases_sample.srt", "library_episode.ass"))
    try:
        kept = json.loads(store.get_meta("phrase_files"))
        first, second = list(kept["files"])
        kept["files"][first][3] = {"7": [2, ["気がする", "気がした"]]}
        kept["files"][second][3] = {"7": [3, ["気がした", "気がして"]], "9": [1, ["腑に落ちる"]]}
        _rewrite(store, kept)
        uses, spellings = store.phrase_sums()
        assert uses == {7: 5, 9: 1}
        assert spellings == {7: ["気がする", "気がした", "気がして"], 9: ["腑に落ちる"]}
    finally:
        store.close()


def test_phrase_sums_are_none_when_a_counted_file_has_no_tally_or_the_names_changed(tmp_path):
    """E2.3 (review X3): a counted file the kept table holds no tally for (a phrase recount that failed after the
    reconcile counted it) would leave its uses out: None, as `phrase_tallies`. So is a table kept under other name
    tables' words (the digest)."""
    store = _store_with(tmp_path, ("phrases_sample.srt", "library_episode.ass"))
    try:
        kept = json.loads(store.get_meta("phrase_files"))
        assert store.phrase_sums() is not None
        _rewrite(store, dict(kept, files=dict(list(kept["files"].items())[:1])))
        assert store.phrase_tallies() is None and store.phrase_sums() is None
        _rewrite(store, dict(kept, names="the digest of other name tables"))
        assert store.phrase_tallies() is None and store.phrase_sums() is None
        _rewrite(store, kept)
        assert store.phrase_sums() is not None, "the same table written back reads again"
    finally:
        store.close()


def test_phrase_sums_skip_a_kept_files_tally_and_a_chinese_store_has_none(tmp_path):
    """E2.3 (review X3): a file kept, not counted (Finished, New arrivals), is never the gate's, though a tally for it
    sits in the kept table with its own (mtime, size). A Chinese store has no phrase table at all."""
    store = _store_with(tmp_path, ("phrases_sample.srt", "library_episode.ass"))
    try:
        kept = json.loads(store.get_meta("phrase_files"))
        path, mtime, size = store.conn.execute("SELECT path, mtime, size FROM files ORDER BY rowid").fetchone()
        others = {p: entry for p, entry in kept["files"].items() if p != path}
        store.conn.execute("UPDATE files SET counted = 0 WHERE path = ?", (path,))
        store.conn.commit()
        _rewrite(store, dict(kept, files=others))
        expected = store.phrase_sums()
        assert expected is not None, "the counted files' own tallies"
        _rewrite(store, dict(kept, files=dict(others, **{path: [mtime, size, None, {"7": [40, ["気がする"]]}, {}]})))
        assert store.phrase_sums() == expected, "the kept file's tally is not the gate's"
    finally:
        store.close()
    zh = token_index.open_store("zh", path=str(tmp_path / "zh.db"))
    try:
        assert zh.phrase_sums() is None
    finally:
        zh.close()


def test_phrase_sums_read_one_snapshot_while_the_indexer_commits_between_its_reads(tmp_path):
    """E2.3 (review X1): the check (state, names) and the tallies are read in one read transaction, as
    `phrase_tallies`' one value was: a new table another connection commits right after the check is not mixed in."""
    import sqlite3

    store = _store_with(tmp_path, ("phrases_sample.srt",))
    try:
        expected = store.phrase_sums()
        assert expected is not None and expected[0]
        kept = json.loads(store.get_meta("phrase_files"))
        path = next(iter(kept["files"]))
        for entry in kept["files"][path][3].values():
            entry[0] += 100
        writer = sqlite3.connect(str(tmp_path / "ja.db"), timeout=5)
        real = store.conn

        class Row:
            def __init__(self, row):
                self.row = row

            def fetchone(self):
                return self.row

        class Between:
            """The store's connection, with the indexer committing a new table right after the check is read."""

            def __getattr__(self, name):
                return getattr(real, name)

            def execute(self, sql, *args):
                cursor = real.execute(sql, *args)
                if "json_extract(value, '$.state')" in sql:
                    row = cursor.fetchone()
                    writer.execute("UPDATE meta SET value = ? WHERE key = 'phrase_files'",
                                   (json.dumps(kept, ensure_ascii=False),))
                    writer.commit()
                    return Row(row)
                return cursor

        store.conn = Between()
        try:
            assert store.phrase_sums() == expected, "the tallies read are the ones the check was read with"
        finally:
            store.conn = real
            writer.close()
        assert store.phrase_sums()[0] != expected[0], "read again, the new table is current and read"
    finally:
        store.close()


def test_phrase_sums_leave_a_transaction_its_caller_opened_open(tmp_path):
    """phrase_sums commits only the transaction it opened itself. A caller that holds one (the
    arrivals gate reads inside its own) keeps it open after the read, so the caller's own writes are not committed
    early."""
    store = _store_with(tmp_path, ("phrases_sample.srt", "library_episode.ass"))
    try:
        kept = json.loads(store.get_meta("phrase_files"))
        first, second = list(kept["files"])
        kept["files"][first][3] = {"7": [2, ["気がする", "気がした"]]}
        kept["files"][second][3] = {"7": [3, ["気がした", "気がして"]], "9": [1, ["腑に落ちる"]]}
        _rewrite(store, kept)
        store.conn.execute("BEGIN")
        try:
            result = store.phrase_sums()
            assert result is not None, "the read ran, so the caller's transaction is what is under test"
            assert store.conn.in_transaction, "the caller's transaction is still open after the read"
        finally:
            if store.conn.in_transaction:
                store.conn.execute("ROLLBACK")
    finally:
        store.close()


def test_phrase_sums_commit_the_transaction_it_opened_itself(tmp_path):
    """The other half of the rule. With no caller transaction, phrase_sums opens one for its reads
    and commits it, so nothing is left open after a plain call."""
    store = _store_with(tmp_path, ("phrases_sample.srt", "library_episode.ass"))
    try:
        kept = json.loads(store.get_meta("phrase_files"))
        first, second = list(kept["files"])
        kept["files"][first][3] = {"7": [2, ["気がする", "気がした"]]}
        kept["files"][second][3] = {"7": [3, ["気がした", "気がして"]], "9": [1, ["腑に落ちる"]]}
        _rewrite(store, kept)
        assert not store.conn.in_transaction, "no transaction is open before the call"
        result = store.phrase_sums()
        assert result is not None, "the read ran, so the commit is what is under test"
        assert not store.conn.in_transaction, "the transaction phrase_sums opened is committed after the read"
    finally:
        store.close()

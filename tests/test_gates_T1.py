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

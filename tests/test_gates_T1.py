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

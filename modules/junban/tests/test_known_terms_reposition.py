"""KNOWN-TERMS: the fast re-plan's known words (`reposition._known_sets`) go through the token store's per-term cache
(G8, `Store.known_terms`), as Generate and the indexer already did.

Why: KnownWord.json's signature moves with every card Connect writes, and each re-plan after one tokenized every known
term again (~10k terms, 1.3–1.8 s, #ZGBCD9). It reads the terms a Generate or the indexer left, tokenizes only the ones
not read before, and still writes nothing (it never kept the known words: the indexer does).

Real known-words files from tests/Test Resources (a slice, for speed), ja + zh; a temp store; the test root's files.
"""
import json
import os

import pytest

from app import analyzer
from app import token_index as ti
from app.path_utils import get_user_files_path
from modules.junban import reposition

_RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                          "tests", "Test Resources")
_NEW = {"ja": ("寝坊", "鯨幕", "雪洞", "勘違い"), "zh": ("夜市", "麻辣烫", "臭豆腐")}


def _known_file(language, extra=(), carded=False):
    """The real known-words file's first 300 known entries, plus `extra` terms a sync added; `carded`: one entry
    marked as Connect marks a card it made."""
    name = "KnownWord.json" if language == "ja" else "KnownWords.json"
    with open(os.path.join(_RESOURCES, language, name), encoding="utf-8-sig") as f:
        data = json.load(f)
    words = data["words"] if isinstance(data, dict) else data
    words = [w for w in words if w.get("knownStatus") == "KNOWN" and w.get("dictForm")][:300]
    held = {w["dictForm"] for w in words}
    words += [{"dictForm": term, "knownStatus": "KNOWN"} for term in extra if term not in held]
    if carded:
        words[0] = dict(words[0], carded=True)
    folder = get_user_files_path(language)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "KnownWord.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"words": words}, f, ensure_ascii=False)
    return path, held


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_re_plan_after_a_mine_tokenizes_only_the_known_terms_not_read_before(tmp_path, monkeypatch, language):
    cls = analyzer.JapaneseTokenizer if language == "ja" else analyzer.ChineseTokenizer
    name = "tokenize_sentences" if language == "ja" else "tokenize"
    real = getattr(cls, name)
    asked = []
    monkeypatch.setattr(cls, name, lambda self, text, *a, **k: (asked.append(text), real(self, text, *a, **k))[1])
    analyzer.SANITIZE_JA = language == "ja"
    settings = {"target_language": language}
    db = str(tmp_path / "store.db")
    path, held = _known_file(language)
    store = ti.open_store(language, path=db)
    try:                                        # a Generate (or the indexer) read them first and kept them
        analyzer.read_known_words(store, path, ti.known_signature(path), cls())
    finally:
        store.close()
    assert len(set(asked) & held) > 50

    new = [w for w in _NEW[language] if w not in held][:2]
    path, _held = _known_file(language, extra=new, carded=True)     # Connect's cards: the file moved
    del asked[:]
    tuples, lemmas, _ignore = reposition._known_sets(language, settings, ti.open_store(language, path=db))
    assert set(new) <= set(asked) and not set(asked) & held, "only the terms not read before are tokenized"
    assert (tuples, lemmas) == analyzer.load_known_words(path, cls())

    # It writes nothing: the store's signature cache still misses this file (the indexer keeps it, not the re-plan)
    store = ti.open_store(language, path=db)
    try:
        assert store.get_cached_known(ti.known_signature(path)) is None
    finally:
        store.close()

    # No store to be had (False): every term read, the same sets
    del asked[:]
    assert reposition._known_sets(language, settings, False)[:2] == (tuples, lemmas)
    assert set(asked) & held

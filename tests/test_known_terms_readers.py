"""KNOWN-TERMS: the sentence dictionary's known words (`sentence_corpus.known_sets`, which Connect's sentence step reads
at each episode it mines) go through the token store's per-term cache (G8, `Store.known_terms`), as Generate and the
indexer already did (`analyzer.read_known_words`).

Why: KnownWord.json's signature moves with every card Connect writes (its carded marks), and each miss of the store's
signature cache tokenized every known term again — ~10k terms, 1.3–1.8 s, five times in 70 s of one mine (#ZGBCD9).
After it, a move tokenizes only the terms not read before: the words it added, or none.

Real known-words files from tests/Test Resources (a slice, for speed), ja + zh; a temp store; the user's files in the
test root.
"""
import json
import os

import pytest

from app import analyzer
from app import sentence_corpus as sc
from app import token_index as ti
from app.path_utils import get_user_files_path

_NEW = {"ja": ("寝坊", "鯨幕", "雪洞", "勘違い"), "zh": ("夜市", "麻辣烫", "臭豆腐")}


def known_file(language, resources, extra=(), carded=False):
    """The real known-words file's first 300 known entries, plus `extra` terms a sync added; `carded`: one entry
    marked as Connect marks a card it made (the file moves, its terms don't)."""
    name = "KnownWord.json" if language == "ja" else "KnownWords.json"
    with open(os.path.join(resources, name), encoding="utf-8-sig") as f:
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


def counting(monkeypatch, language):
    """Every text a known term is read by the tokenizer with (its class method: `known_sets` makes its own)."""
    cls = analyzer.JapaneseTokenizer if language == "ja" else analyzer.ChineseTokenizer
    name = "tokenize_sentences" if language == "ja" else "tokenize"
    real = getattr(cls, name)
    asked = []

    def counted(self, text, *a, **k):
        asked.append(text)
        return real(self, text, *a, **k)
    monkeypatch.setattr(cls, name, counted)
    return asked


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_mine_that_moves_the_known_words_file_tokenizes_only_the_terms_it_added(
        tmp_path, monkeypatch, language, ja_resources_dir, zh_resources_dir):
    resources = ja_resources_dir if language == "ja" else zh_resources_dir
    analyzer.SANITIZE_JA = language == "ja"              # as every caller sets it before the known words are read
    settings = {"target_language": language}
    asked = counting(monkeypatch, language)
    path, held = known_file(language, resources)
    store = ti.open_store(language, path=str(tmp_path / "store.db"))
    kept = []
    real_keep = ti.Store._known_terms_value         # the terms' blob, made only when it is written (STORE-KEY)
    monkeypatch.setattr(ti.Store, "_known_terms_value", lambda self, *a: (kept.append(1), real_keep(self, *a))[1])
    try:
        first = sc.known_sets(language, store, settings)
        whole = set(asked)
        assert len(whole & held) > 3 and first[0] and first[1], "the first read reads the file's terms"
        assert kept == [1], "the terms kept for the next read"

        # A card Connect made: the file's signature moves, no term is new — nothing is tokenized, and the ~10k terms'
        # blob isn't written again for nothing
        known_file(language, resources, carded=True)
        del asked[:]
        again = sc.known_sets(language, store, settings)
        assert not set(asked) & held, "no term read before is tokenized again"
        assert again[:2] == first[:2]
        assert kept == [1], "no term changed: the terms' blob is not rewritten"

        # A sync's two new words: only those
        new = [w for w in _NEW[language] if w not in held][:2]
        assert len(new) == 2
        path, _held = known_file(language, resources, extra=new, carded=True)
        del asked[:]
        grown = sc.known_sets(language, store, settings)
        assert set(new) <= set(asked) and not set(asked) & held, "only the words the sync added are read"
        assert kept == [1, 1], "two terms more: kept"
        fresh = analyzer.load_known_words(path, analyzer.JapaneseTokenizer() if language == "ja"
                                          else analyzer.ChineseTokenizer())
        assert grown[:2] == fresh, "the very sets a fresh read of the whole file gives"
        assert grown[0] > first[0] and grown[1] > first[1]
    finally:
        store.close()


def test_with_nothing_held_in_the_store_every_term_is_read_once_and_an_empty_file_is_no_known_word(
        tmp_path, monkeypatch, ja_resources_dir):
    # why: the first read after an update (another tokenizer: the store's terms keyed to the old build) reads every
    # term, never an error; an empty KnownWord.json is no known word, and no term is tokenized
    asked = counting(monkeypatch, "ja")
    analyzer.SANITIZE_JA = True
    store = ti.open_store("ja", path=str(tmp_path / "store.db"))
    try:
        known_file("ja", ja_resources_dir)
        sc.known_sets("ja", store, {})
        store.set_meta("build_sig", "another tokenizer")
        known_file("ja", ja_resources_dir, carded=True)
        del asked[:]
        sc.known_sets("ja", store, {})
        assert len(set(asked)) > 3, "another build: every term read again"
        with open(os.path.join(get_user_files_path("ja"), "KnownWord.json"), "w", encoding="utf-8") as f:
            json.dump({"words": []}, f)
        del asked[:]
        tuples, lemmas, _ignore = sc.known_sets("ja", store, {})
        assert (tuples, lemmas, asked) == (set(), set(), [])
    finally:
        store.close()

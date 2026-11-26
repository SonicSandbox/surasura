"""STORE-KEY: a known-words miss in the token store works out its key once.

Why: the known-words cache's key holds, for Japanese, the names / phrases / pronouns switches (settings.json) and the
library's name tables (the `names_tables` blob) — `Store._known_key`. Each of the miss's steps worked it out again: the
caller's check, `read_known_words`' own second check, the per-term cache's read, and both writes — 5-6 settings.json
reads and as many blob parses a miss, and two commits when a word was added (two transactions). A card Connect writes
moves KnownWord.json, so a mine misses at every card. After it: one settings read, one parse and one commit a miss.

Real known-words files from tests/Test Resources (a slice, for speed), ja + zh; a temp store; the user's files in the
test root.
"""
import json
import os

import pytest

from app import analyzer, settings_manager
from app import sentence_corpus as sc
from app import token_index as ti
from app.path_utils import get_user_files_path

_NEW = {"ja": ("寝坊", "鯨幕"), "zh": ("夜市", "麻辣烫")}


def known_file(language, resources, extra=(), carded=False):
    """The real known-words file's first 200 known entries, plus `extra` terms a sync added; `carded`: one entry
    marked as Connect marks a card it made (the file moves, its terms don't)."""
    name = "KnownWord.json" if language == "ja" else "KnownWords.json"
    with open(os.path.join(resources, name), encoding="utf-8-sig") as f:
        data = json.load(f)
    words = data["words"] if isinstance(data, dict) else data
    words = [w for w in words if w.get("knownStatus") == "KNOWN" and w.get("dictForm")][:200]
    held = {w["dictForm"] for w in words}
    words += [{"dictForm": term, "knownStatus": "KNOWN"} for term in extra if term not in held]
    if carded:
        words[0] = dict(words[0], carded=True)
    folder = get_user_files_path(language)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "KnownWord.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"words": words}, f, ensure_ascii=False)
    return path


class Count:
    """What one miss costs: settings.json reads, name-table blob parses, commits, and the cache's lookups."""

    def __init__(self, monkeypatch, store):
        self.reads = self.parses = self.commits = self.looks = 0
        real_load, real_tables, real_get = settings_manager.load_settings, ti.Store.names_tables, ti.Store.get_cached_known

        def load(*a, **k):
            self.reads += 1
            return real_load(*a, **k)

        def tables(s, *a, **k):
            self.parses += 1
            return real_tables(s, *a, **k)

        def get(s, *a, **k):
            self.looks += 1
            return real_get(s, *a, **k)
        monkeypatch.setattr(settings_manager, "load_settings", load)
        monkeypatch.setattr(ti.Store, "names_tables", tables)
        monkeypatch.setattr(ti.Store, "get_cached_known", get)
        store.conn.set_trace_callback(lambda sql: setattr(self, "commits", self.commits + (sql.strip().upper() == "COMMIT")))

    def take(self):
        got = (self.reads, self.parses, self.commits, self.looks)
        self.reads = self.parses = self.commits = self.looks = 0
        return got


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_each_known_words_miss_reads_settings_once_parses_the_tables_once_and_commits_once(
        tmp_path, monkeypatch, language, ja_resources_dir, zh_resources_dir):
    # why: the mine's path (`sentence_corpus.known_sets`, at each card Connect writes) — the first read, a card's move
    # (no new term) and a sync's two new words each cost one key, one lookup and one commit. Chinese reads no
    # settings for its key (the names switches are Japanese only), so 0 there, before as after. Its ignore set's
    # Ignore names switch comes from the settings handed in (STORE-KEY 2), and so do the key's switches (ONE-READ): no
    # read of its own.
    resources = ja_resources_dir if language == "ja" else zh_resources_dir
    monkeypatch.setattr(analyzer, "SANITIZE_JA", language == "ja")
    keys = 1 if language == "ja" else 0
    reads = 0
    known_file(language, resources)
    settings = settings_manager.load_settings()         # as Connect loads them, before its read
    store = ti.open_store(language, path=str(tmp_path / "store.db"))
    try:
        count = Count(monkeypatch, store)
        first = sc.known_sets(language, store, settings)
        assert first[0] and first[1]
        assert count.take() == (reads, keys, 1, 1), "the first read: one key, one lookup, one commit"

        known_file(language, resources, carded=True)
        assert sc.known_sets(language, store, settings)[:2] == first[:2]
        assert count.take() == (reads, keys, 1, 1), "a card's move: one key, one lookup, one commit"

        path = known_file(language, resources, extra=_NEW[language], carded=True)
        grown = sc.known_sets(language, store, settings)
        assert count.take() == (reads, keys, 1, 1), "a word added: the signature and the terms in one commit"
        assert set(_NEW[language]) <= set(store.known_terms("asis")), "the added terms kept in that commit"
        count.take()                                      # (that check's own key read: not the next step's)
        tok = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
        assert grown[:2] == analyzer.load_known_words(path, tok), "the very sets a fresh read of the whole file gives"

        # A hit after it: one key, one lookup, nothing written
        assert sc.known_sets(language, store, settings)[:2] == grown[:2]
        assert count.take() == (reads, keys, 0, 1)
    finally:
        store.close()


def test_generates_own_read_misses_with_one_key_and_one_commit_and_a_readonly_read_writes_nothing(
        tmp_path, monkeypatch, ja_resources_dir):
    # why: Generate calls `read_known_words` with no check of its own (analyzer.main), and the arrivals view reads with
    # keep=False: one key each, and the read-only one never commits
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)
    path = known_file("ja", ja_resources_dir)
    store = ti.open_store("ja", path=str(tmp_path / "store.db"))
    try:
        count = Count(monkeypatch, store)
        tok = analyzer.JapaneseTokenizer()
        sig = ti.known_signature(path, "asis")
        known = analyzer.read_known_words(store, path, sig, tok)
        assert count.take() == (1, 1, 1, 1)
        path = known_file("ja", ja_resources_dir, extra=_NEW["ja"])
        sig = ti.known_signature(path, "asis")
        readonly = analyzer.read_known_words(store, path, sig, tok, keep=False)
        assert count.take() == (1, 1, 0, 1), "a reader that writes nothing: one key, no commit"
        assert readonly[0] > known[0]
        assert store.get_cached_known(sig) is None, "nothing kept"
    finally:
        store.close()


def test_the_keys_written_are_the_keys_a_fresh_lookup_works_out(tmp_path, monkeypatch, ja_resources_dir):
    # why: the key is handed down, never changed — a store written before still hits, and a switch flipped between
    # two misses still misses (the key read fresh at each miss: the dashboard's check sees what its indexer will)
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)
    path = known_file("ja", ja_resources_dir)
    store = ti.open_store("ja", path=str(tmp_path / "store.db"))
    try:
        sig = ti.known_signature(path, "asis")
        known = sc.known_sets("ja", store, {})
        assert store.get_meta("known_sig") == store._known_key(sig)
        assert store.known_terms("asis"), "the terms' blob keyed as a fresh lookup keys it"
        assert store.get_cached_known(sig) == known[:2]

        settings = settings_manager.load_settings()
        settings["logic"]["pronoun_bases"] = False
        settings_manager.save_settings(settings)
        assert store.get_cached_known(sig) is None, "a switch flipped: the next lookup misses"
        assert store.known_terms("asis") == {}

        # A names switch too (the key's names part, with the name tables' stamp)
        sc.known_sets("ja", store, {})
        assert store.get_cached_known(sig) is not None
        settings["logic"]["names_kanji"] = False
        settings_manager.save_settings(settings)
        assert store.get_cached_known(sig) is None, "a names switch flipped: the next lookup misses"
        assert "|names=1101:" in store._known_key(sig)
    finally:
        store.close()

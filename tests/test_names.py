"""Names are one word, not pieces (app/names.py; Settings -> Language & Parsing).

A name the dictionary lacks is cut by the tagger into pieces that are words or letters of their own, and the pieces
then count as those words. analyzer.join_affixes — the one place every Japanese caller reads words through — keeps
such a name one word:

- katakana names (logic.names_katakana): a katakana run no JPDB 2024 / Jiten headword spells, with a piece that is no
  common word, is one word; a compound of common listed words, a repeated sound, a stutter and a run of nothing but
  interjections (laughter, a cry) stay in pieces.
- names that recur in the library (logic.names_recurring): a run of common words the rule above leaves in pieces is
  one word when the library keeps using it as one (its rarer piece mostly inside it, 3+ uses) — a table the token
  store computes after indexing, applied to its cached tokens and to live text alike; once joined, a run stays
  joined until it is clearly no longer sticky.
- kanji names (logic.names_kanji): a run of kanji the tagger cuts, spelled as a person's name in JMnedict and no
  dictionary word, is one word where no guard says its pieces are words there — once the library holds it 3+ times.
- a story's own kanji terms (logic.names_work_terms): a run of one-kanji tokens the rules above leave in pieces is
  one word when the library keeps using it as one (the katakana gauge), no dictionary lists it and nothing says it
  is words; transcripts of auto-generated captions count toward nothing.

Made-up names, terms and sentences throughout (ミロナイ, ハルミナ, メロンベンチ, 奏汰, 焔魄陣, 玖崩): the katakana
rule is Japanese-wide; the library tables are built here from made-up libraries, never the user's.
"""
import json
import os
import re
from collections import Counter
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer, names, settings_manager
from app import token_index as ti


@pytest.fixture(scope="module")
def tokenizer():
    return analyzer.JapaneseTokenizer()


def _tokens(tokenizer, text):
    """(lemma, reading, surface, orth) of every counted token of `text`, as a run reads it."""
    analyzer.SANITIZE_JA = True
    return [token for _s, tokens in tokenizer.tokenize_sentences(text) for token in tokens]


def _surfaces(tokenizer, text):
    return [surface for _l, _r, surface, _o in _tokens(tokenizer, text)]


def _switch(monkeypatch, key, on):
    """A switch as a run reads it: settings.json's logic block, loaded into LOGIC when the analyzer starts."""
    monkeypatch.setitem(analyzer.LOGIC, key, on)


# A made-up name spelled with two common words (メロン + ベンチ), used four times; each piece alone once.
STATION = "メロンベンチは駅の前にある。\n今日もメロンベンチで待ち合わせた。\n"
SHOP = "メロンベンチの近くに店がある。\n昨日、メロンベンチに座った。\n"
PARK = "公園のベンチに座った。\nメロンを食べた。\n"


def _library(folder, files):
    """A made-up library indexed into a store of its own, as the indexer and Generate index one."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, text in files.items():
        path = folder / name
        path.write_text(text, encoding="utf-8")
        paths.append(str(path))
    store = ti.open_store("ja", path=str(folder / "store.db"))
    store.reconcile(paths, ti.make_tokenizer("ja"), build_signature=ti.build_signature("ja"))
    return store, paths


def _cached_surfaces(store, path):
    return [t[2] for _s, tokens in store.file_tokens(path) for t in tokens]


# --- katakana names ---------------------------------------------------------------------------------------------- #
def test_a_katakana_name_the_tagger_cuts_is_one_word_with_no_reading(tokenizer):
    """ミロナイ is cut ミロ + ナイ (two names UniDic knows) and no list spells the run: one word, keyed as the tagger
    keys a word its dictionary lacks — the spelling, no reading (never ミロ's and ナイ's readings run together)."""
    tokens = _tokens(tokenizer, "昨日、ミロナイが村に来た。")
    [name] = [t for t in tokens if t[2] == "ミロナイ"]
    assert name == ("ミロナイ", "", "ミロナイ", "ミロナイ")
    assert not {"ミロ", "ナイ"} & {t[0] for t in tokens}, "its pieces no longer count as words"


def test_the_switch_off_leaves_the_pieces_as_today(tokenizer, monkeypatch):
    """Off means today's behaviour: the tagger's pieces."""
    _switch(monkeypatch, "names_katakana", False)
    assert "ミロナイ" not in _surfaces(tokenizer, "昨日、ミロナイが村に来た。")
    assert {"ミロ", "ナイ"} <= set(_surfaces(tokenizer, "昨日、ミロナイが村に来た。"))


def test_compounds_and_listed_words_stay_the_words_they_are(tokenizer):
    """A run of common listed words the lists don't carry as one (ドラゴン + ケーキ) is a compound: it stays in pieces,
    each a word the learner may know. A run a headword spells (トートバッグ) is never a name: it is the dictionary word
    it spells — one word, with the lists' reading (analyzer's compound joins) — and without that table, the tagger's
    pieces."""
    assert _surfaces(tokenizer, "ドラゴンケーキを焼いた。")[:2] == ["ドラゴン", "ケーキ"]
    assert _tokens(tokenizer, "トートバッグを持って出かけた。")[0][:3] == ("トートバッグ", "トートバッグ", "トートバッグ")
    with patch.object(analyzer, "compound_joins", dict):
        assert _surfaces(tokenizer, "トートバッグを持って出かけた。")[:2] == ["トート", "バッグ"]


def test_a_repeated_sound_and_a_stutter_stay_in_pieces(tokenizer):
    """One piece repeated (ワン + ワン + ワン; アア + アッ, a final ッ aside) is a sound, and a stutter — a piece cut
    off with ッ, then a word starting with the same sound (バッ + バカ) — is the word said twice: neither is a name."""
    assert "ワンワンワン" not in _surfaces(tokenizer, "犬がワンワンワンと鳴いた。")
    assert "アアアッ" not in _surfaces(tokenizer, "アアアッ！")
    surfaces = _surfaces(tokenizer, "バッバカかお前は！")
    assert "バカ" in surfaces and "バッバカ" not in surfaces
    assert names.repeated(["ブンブン", "ブンブン"]) and names.repeated(["アア", "アッ"])
    assert names.stutter(["バ", "ッ", "バカ"]) and names.stutter(["ヤッ", "ヤバイ"])
    assert not names.repeated(["ハル", "ミナ"]) and not names.stutter(["ナイ", "ッ", "シュー"])


def test_laughter_and_cries_stay_in_pieces(tokenizer):
    """A run made only of interjections — every piece one the tagger reads as an interjection (アッ + ハハ, ウワ +
    アア) — is laughter or a cry, not a name: it stays in pieces, each the interjection it is. A run with any other
    piece may still be a name: ハイ + ミロ (an interjection, then a name) is one word, as before."""
    assert _surfaces(tokenizer, "アッハハ！") == ["アッ", "ハハ"]
    assert _surfaces(tokenizer, "ウワアア！") == ["ウワ", "アア"]
    assert _surfaces(tokenizer, "ｱｯﾊﾊ！") == ["ｱｯ", "ﾊﾊ"], "half-width is read as katakana: the same laugh"
    assert ("ハイミロ", "", "ハイミロ", "ハイミロ") in _tokens(tokenizer, "ハイミロが来た")


def test_half_width_katakana_and_spaces(tokenizer):
    """Half-width katakana is read as full-width (ﾐﾛﾅｲ is ミロナイ) and joins the same, keeping the text's own spelling
    as its surface; a space between two names keeps them two."""
    [name] = [t for t in _tokens(tokenizer, "ﾐﾛﾅｲが来た。") if t[0] == "ミロナイ"]
    assert name[1:3] == ("", "ﾐﾛﾅｲ")
    assert "ミロナイ" not in {t[0] for t in _tokens(tokenizer, "ミロ ナイが来た。")}


def test_without_the_table_no_run_is_joined(tokenizer, monkeypatch):
    """A missing table must never make every katakana run a name: the pieces stay, as the affix joins do."""
    monkeypatch.setattr(names, "_katakana_headwords", [None])
    assert "ミロナイ" not in _surfaces(tokenizer, "昨日、ミロナイが村に来た。")


def test_known_words_read_a_name_as_one_word(tmp_path, tokenizer):
    """KnownWord.json is read through the same tokenizer: knowing the name ミロナイ is knowing that one word — keyed
    as the list keys it. Its pieces are marked known too, as a known joined word's always are (時間帯 -> 時間) and as
    they were before the name was one word."""
    path = tmp_path / "KnownWord.json"
    path.write_text('[{"dictForm": "ミロナイ", "knownStatus": "KNOWN"}]', encoding="utf-8")
    analyzer.SANITIZE_JA = True
    known_tuples, known_lemmas = analyzer.load_known_words(str(path), tokenizer)
    assert ("ミロナイ", "") in known_tuples and "ミロナイ" in known_lemmas
    assert {"ミロ", "ナイ"} <= known_lemmas


def test_the_switch_is_in_the_store_build_signature_only_when_off(monkeypatch, tmp_path):
    """Flipping it re-reads every file (the cached tokens hold the joins); on, the default, adds nothing — a store
    built as shipped keeps its signature."""
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(settings_manager, "get_user_file", lambda name: str(settings))
    assert settings_manager.DEFAULT_SETTINGS["logic"]["names_katakana"] is True
    assert ti.build_signature("ja") == "ja|reinforce=False"
    settings.write_text('{"logic": {"names_katakana": false}}', encoding="utf-8")
    assert ti.build_signature("ja") == "ja|reinforce=False|names_katakana=off"
    assert ti.build_signature("zh") == "zh|reinforce=False", "a Chinese store never reads it"


def test_chinese_is_untouched(monkeypatch):
    """The names rules are Japanese only: the Chinese tokenizer never reaches them."""
    def boom(*args, **kwargs):
        raise AssertionError("a Chinese tokenizer reached the names rules")
    monkeypatch.setattr(names, "join_katakana", boom)
    monkeypatch.setattr(names, "join_library", boom)
    tok = analyzer.ChineseTokenizer()
    words = Counter(lemma for _s, tokens in tok.tokenize_sentences("我和朋友一起去北京。") for lemma, *_ in tokens)
    assert words["北京"] == 1


# --- names that recur in the library ---------------------------------------------------------------------------- #
def test_a_run_the_library_keeps_using_as_one_is_one_word_everywhere(tmp_path, tokenizer):
    """メロン + ベンチ is a run of common words (the katakana rule leaves it in pieces). Four uses, and each piece alone
    once: its stickiness — the share of its least-used piece's uses inside it — is 4 / 5. The table the index computes names it; the cached tokens every run reads, and live
    text (known words, Junban, the card matcher), both read it as one word, with no reading."""
    store, paths = _library(tmp_path / "lib", {"station.txt": STATION, "shop.txt": SHOP, "park.txt": PARK})
    try:
        tables = store.names_tables()
        assert tables["k"]["メロンベンチ"] == [0.8, "メロンベンチ", "", "メロンベンチ"]
        assert "メロンベンチ" in _cached_surfaces(store, paths[0])
        assert _cached_surfaces(store, paths[2])[:3] == ["公園", "の", "ベンチ"], "ベンチ alone is still ベンチ"
        # The cache holds each file as it reads alone, its candidates beside it: a new table needs no re-tokenizing.
        raw = ti._decode_tokens(store.conn.execute("SELECT tokens FROM files WHERE path=?",
                                                   (ti._norm(paths[0]),)).fetchone()[0])
        assert "メロンベンチ" not in [t[2] for _s, tokens in raw for t in tokens]
    finally:
        store.close()
    names.use_library_tables(tables)
    assert ("メロンベンチ", "", "メロンベンチ", "メロンベンチ") in _tokens(tokenizer, "駅でメロンベンチを探した。")


def test_the_floor_and_the_stickiness(tmp_path):
    """Too few uses, or a rarer piece that mostly lives outside the run, and the run stays in pieces."""
    store, _paths = _library(tmp_path / "few", {"station.txt": STATION})
    try:
        assert "メロンベンチ" not in store.names_tables()["k"], "two uses: under the floor of three"
    finally:
        store.close()
    alone = PARK + "古いベンチを直した。\nメロンを買った。\n新しいベンチを買った。\nメロンを切った。\n"
    store, _paths = _library(tmp_path / "alone", {"station.txt": STATION, "shop.txt": SHOP, "park.txt": alone})
    try:
        assert "メロンベンチ" not in store.names_tables()["k"], "4 / 7: its pieces are mostly words of their own here"
    finally:
        store.close()


def test_the_flip_guard_keeps_a_joined_run_until_it_is_clearly_not_sticky():
    """A run joined in the last tables stays joined while its stickiness is 0.5 or more — so a name doesn't flicker
    in and out as a library grows — and a new run needs 0.7."""
    def record(run_uses, piece_uses):
        return {"ks": {"メロンベンチ": {"メロン|ベンチ": run_uses}}, "p": {"メロン": 50, "ベンチ": piece_uses}}
    joined_before = {"k": {"メロンベンチ": [0.8, "メロンベンチ", "", "メロンベンチ"]}}
    assert "メロンベンチ" not in names.compute_tables([record(6, 10)])["k"], "0.6: not enough to join"
    assert "メロンベンチ" in names.compute_tables([record(6, 10)], joined_before)["k"], "0.6: enough to stay"
    assert "メロンベンチ" not in names.compute_tables([record(4, 10)], joined_before)["k"], "0.4: it goes"
    assert "メロンベンチ" in names.compute_tables([record(7, 10)])["k"], "0.7 joins"
    assert names.compute_tables([])["k"] == {}, "an empty library: an empty table"


def test_a_store_keeps_its_last_table_for_the_flip_guard(tmp_path):
    """The guard reads the tables the store last computed: a joined run survives a library change that leaves it
    between 0.5 and 0.7."""
    store, paths = _library(tmp_path / "lib", {"station.txt": STATION, "shop.txt": SHOP, "park.txt": PARK})
    try:
        assert "メロンベンチ" in store.names_tables()["k"]
        park = tmp_path / "lib" / "more.txt"
        park.write_text("古いベンチを直した。\nメロンを買った。\n", encoding="utf-8")     # 4 / 6: under 0.7, over 0.5
        store.reconcile(paths + [str(park)], ti.make_tokenizer("ja"), build_signature=ti.build_signature("ja"))
        assert store.names_tables()["k"]["メロンベンチ"][0] == 0.667
    finally:
        store.close()
    fresh, _paths = _library(tmp_path / "fresh", {"station.txt": STATION, "shop.txt": SHOP, "park.txt": PARK,
                                                  "more.txt": "古いベンチを直した。\nメロンを買った。\n"})
    try:
        assert "メロンベンチ" not in fresh.names_tables()["k"], "the same library indexed at once: 4 / 6 doesn't join"
    finally:
        fresh.close()


def test_the_recurring_switch_off_and_no_table_yet(tmp_path, tokenizer, monkeypatch):
    """Off means today's behaviour — the cached tokens and live text both in pieces — and needs no re-indexing (the
    switch is not in the cache's signature). Before the first index there is no table: names split as the katakana
    rule leaves them."""
    store, paths = _library(tmp_path / "lib", {"station.txt": STATION, "shop.txt": SHOP, "park.txt": PARK})
    try:
        assert "メロンベンチ" in _cached_surfaces(store, paths[0])
        _switch(monkeypatch, "names_recurring", False)
        assert "メロンベンチ" not in _cached_surfaces(store, paths[0])
        assert ti.build_signature("ja") == "ja|reinforce=False"
        names.use_library_tables(store.names_tables())
        assert "メロンベンチ" not in _surfaces(tokenizer, "駅でメロンベンチを探した。")
    finally:
        store.close()
    monkeypatch.setitem(analyzer.LOGIC, "names_recurring", True)
    names.forget_library_tables()
    assert names.library_tables() is None, "no store yet: no table"
    assert "メロンベンチ" not in _surfaces(tokenizer, "駅でメロンベンチを探した。")


def test_the_rarity_preview_counts_a_joined_name_as_the_list_does(tmp_path, monkeypatch):
    """The Rarity slider — and automatic rarity, which picks its band from the same numbers — reads the store's running
    totals, which hold each file as it reads alone; the list reads the cached tokens with the library's tables
    applied. The totals take the tables' joins too, so both count the same words with the switch on or off:
    メロンベンチ as one word four times, its pieces only where they stand alone."""
    store, paths = _library(tmp_path / "lib", {"station.txt": STATION, "shop.txt": SHOP, "park.txt": PARK})
    try:
        for recurring in (True, False):
            _switch(monkeypatch, "names_recurring", recurring)
            listed = Counter()
            for path in paths:
                for _s, tokens in store.file_tokens(path):
                    for lemma, reading, surface, _orth in tokens:
                        if analyzer.has_target_language(lemma, "ja") or analyzer.has_target_language(surface, "ja"):
                            listed[ti.make_key(lemma, reading)] += 1
            preview = store.unknown_frequencies()
            assert dict(preview["unknown"]) == dict(listed)
            assert preview["total_tokens"] == sum(listed.values())
            assert any(key.startswith("メロンベンチ|") for key in listed) is recurring
    finally:
        store.close()


def test_shared_data_never_reads_the_library_tables(tokenizer):
    """パターン data and the reference data are shared: they read text with library=False, so one user's library can
    never shape them — the katakana rule, Japanese-wide, still applies."""
    names.use_library_tables({"k": {"メロンベンチ": [1.0, "メロンベンチ", "", "メロンベンチ"]}, "stamp": "x"}, pin=True)
    nodes = tokenizer.tagger("駅でメロンベンチを探した。")
    assert "メロンベンチ" in [w.surface for w in analyzer.join_affixes(nodes)]
    nodes = tokenizer.tagger("駅でメロンベンチを探した。")
    assert "メロンベンチ" not in [w.surface for w in analyzer.join_affixes(nodes, library=False)]
    patterns_build = pytest.importorskip("modules.junban.patterns_build")
    sentences = list(patterns_build.iter_tokens("駅でメロンベンチを探した。", tokenizer.tagger, analyzer._sanitize_term,
                                                frozenset("。")))
    assert "メロンベンチ" not in [t.surface for sentence in sentences for t in sentence]


def test_the_known_words_cache_follows_the_tables_and_the_switches(tmp_path, monkeypatch):
    """A known name is one word only with the tables: a new table, or a switch flipped in settings.json, reads the
    known words again (the switches read fresh, as the dashboard's check and the indexer it launches both see them)."""
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(settings_manager, "get_user_file", lambda name: str(settings))
    store, _paths = _library(tmp_path / "lib", {"station.txt": STATION, "shop.txt": SHOP, "park.txt": PARK})
    try:
        sig = ti.known_signature(str(tmp_path / "KnownWord.json"))
        store.set_cached_known(sig, {("メロンベンチ", "")}, {"メロンベンチ"})
        assert store.get_cached_known(sig) is not None
        settings.write_text('{"logic": {"names_recurring": false}}', encoding="utf-8")
        assert store.get_cached_known(sig) is None, "a switch flipped"
        settings.write_text('{"logic": {"names_recurring": true}}', encoding="utf-8")
        assert store.get_cached_known(sig) is not None
        store.set_meta("names_tables", '{"k": {}, "stamp": "another"}')
        assert store.get_cached_known(sig) is None, "another table"
    finally:
        store.close()


def test_a_chinese_store_keeps_no_names(tmp_path):
    """Chinese is untouched: its store records no candidates and computes no tables."""
    path = tmp_path / "zh.txt"
    path.write_text("我们今天去北京。\n", encoding="utf-8")
    store = ti.open_store("zh", path=str(tmp_path / "zh.db"))
    try:
        store.reconcile([str(path)], ti.make_tokenizer("zh"))
        assert store.names_tables() is None
        assert store.conn.execute("SELECT names FROM files").fetchone()[0] is None
    finally:
        store.close()


# --- kanji names -------------------------------------------------------------------------------------------------- #
# 奏汰 is a given name in JMnedict and no dictionary word; the tagger cuts it 奏 + 汰.
SOTA = "奏汰が駅に来た。\n昨日は奏汰と話した。\n"


def test_a_kanji_name_joins_once_the_library_holds_it_three_times(tmp_path, tokenizer):
    """Three uses in the library, and 奏汰 is one word — in the cached tokens and in live text — with no reading
    (never 奏's and 汰's run together); two uses, and it stays in pieces (a chance meeting of two words rarely
    recurs)."""
    store, paths = _library(tmp_path / "three", {"a.txt": SOTA, "b.txt": "奏汰は笑った。\n"})
    try:
        tables = store.names_tables()
        assert tables["j"]["奏汰"][1:] == ["奏汰", "", "奏汰"]
        assert "奏汰" in _cached_surfaces(store, paths[0])
    finally:
        store.close()
    names.use_library_tables(tables)
    assert ("奏汰", "", "奏汰", "奏汰") in _tokens(tokenizer, "今日も奏汰に会った。")
    store, paths = _library(tmp_path / "two", {"a.txt": SOTA})
    try:
        assert "奏汰" not in store.names_tables()["j"], "two uses: under the floor"
        assert "奏汰" not in _cached_surfaces(store, paths[0])
    finally:
        store.close()


@pytest.mark.parametrize("text, spelling, why", [
    ("宮崎駿の映画を見た。", "宮崎駿", "a surname + a given name the tagger reads as such: a full name, two words"),
    ("１０円玉を拾った。", "円玉", "right after a number: a count, not a name"),
    ("マリア様に祈った。", "マリア様", "a name the tagger knows + a suffix"),
    ("お光達が笑っていた。", "光達", "a plural suffix last"),
])
def test_the_kanji_guards_keep_words_apart(tokenizer, text, spelling, why):
    """Each spelling is a person's name in JMnedict, but here its pieces are words: no candidate at all."""
    table = names.person_names()
    assert table.get(spelling), "the guard, not the name table, must be what refuses it"
    words = analyzer.join_affixes(tokenizer.tagger(text), library=False)
    assert spelling not in [c.spelling for c in names.kanji_candidates(words, table)], why


def test_the_kanji_switch_off_and_no_name_table(tmp_path, tokenizer, monkeypatch):
    """Off means today's behaviour, and needs only a Generate: the cached tokens still record the name, the switch
    only decides whether it is applied. Without the name table nothing is a candidate."""
    store, paths = _library(tmp_path / "lib", {"a.txt": SOTA, "b.txt": "奏汰は笑った。\n"})
    try:
        _switch(monkeypatch, "names_kanji", False)
        assert "奏汰" not in _cached_surfaces(store, paths[0])
        monkeypatch.setitem(analyzer.LOGIC, "names_kanji", True)
        assert "奏汰" in _cached_surfaces(store, paths[0])
    finally:
        store.close()
    monkeypatch.setattr(names, "_person_names", [None])
    record = names.Record()
    list(analyzer.JapaneseTokenizer(library=False).tokenize_sentences(SOTA, names=record))
    assert not record.data()["jc"] and not [span for span in record.data()["s"] if span[5] == "j"]


def test_a_long_lived_process_picks_up_newer_tables(tmp_path, monkeypatch):
    """A window open across a Generate (the dashboard, Junban) reads the tables from the language's token store, and
    looks again after a while: the tables the index just computed reach it without a restart."""
    folder = tmp_path / "lib"
    folder.mkdir()
    (folder / "station.txt").write_text(STATION, encoding="utf-8")
    ti.reconcile_language("ja", [str(folder / "station.txt")])
    assert "メロンベンチ" not in names.library_tables()["k"], "two uses: not yet"
    (folder / "shop.txt").write_text(SHOP, encoding="utf-8")
    ti.reconcile_language("ja", [str(folder / "station.txt"), str(folder / "shop.txt")])
    assert "メロンベンチ" not in names.library_tables()["k"], "read a moment ago: kept for a while"
    monkeypatch.setattr(names, "REFRESH", -1.0)   # below zero: two calls inside one Windows clock tick still read again
    assert "メロンベンチ" in names.library_tables()["k"], "then read again"


def test_only_indexing_reads_the_name_table(tmp_path, tokenizer, monkeypatch):
    """The person-name table is read only where files are indexed (the token store records candidates): a process
    that applies the library's small tables — known words, Junban, the report — never reads it, and the tables it keeps
    are hashes, not strings."""
    monkeypatch.setattr(names, "_person_names", [])
    names.use_library_tables({"k": {}, "j": {"奏汰": [2, "奏汰", "", "奏汰"]}, "stamp": "one name"}, pin=True)
    assert ("奏汰", "", "奏汰", "奏汰") in _tokens(tokenizer, "今日も奏汰に会った。")
    path = tmp_path / "KnownWord.json"
    path.write_text('[{"dictForm": "奏汰", "knownStatus": "KNOWN"}]', encoding="utf-8")
    assert ("奏汰", "") in analyzer.load_known_words(str(path), tokenizer)[0]
    assert names._person_names == [], "applying the tables never read the name table"
    list(analyzer.JapaneseTokenizer(library=False).tokenize_sentences(SOTA, names=names.Record()))
    table = names._person_names[0]
    assert table.get("奏汰") == names.GIVEN and table.get("司波") & names.SURNAME and table.get("駅前") == 0
    headwords = names.katakana_headwords()
    assert "トートバッグ" in headwords and "ミロナイ" not in headwords and len(headwords) > 100000


# --- katakana words the rule used to cut or glue ------------------------------------------------------------------ #
def test_a_katakana_name_leaves_the_head_of_a_word_written_on_in_hiragana(tokenizer):
    """サクサク + ジャ + がいも: the tagger cuts じゃがいも, written ジャがいも, at the script's edge, and the katakana
    rule used to glue its head to the sound word before it (サクサクジャ, no word at all). The head and the hiragana
    after it spell a headword (ジャガイモ), so the run ends before it — while a name's own particle never makes a
    word with its last piece: トゥー + リ + は stays トゥーリ, though リハ is a word too."""
    surfaces = _surfaces(tokenizer, "サクサクジャがいもが焼けた。")
    assert "サクサクジャ" not in surfaces and surfaces[0] == "サクサク"
    assert "トゥーリ" in _surfaces(tokenizer, "トゥーリは笑った。")
    assert "ミロナイ" in _surfaces(tokenizer, "ミロナイと話した。")


def test_a_katakana_headword_no_dictionary_join_makes_is_one_word(tokenizer, monkeypatch):
    """ブシン is a headword (JPDB 2024), too rare for the compound and affix tables, and the tagger cuts it into ブ —
    read as the prefix 無 'non-' — and シン. Its pieces are no words there, so it is one word, as an unlisted name
    would be; a headword made only of common words the tables don't hold stays in pieces as a compound does, and
    without the compound table a headword stays as the tagger cuts it."""
    tokens = _tokens(tokenizer, "今年のブシン祭が始まる。")
    assert ("ブシン", "", "ブシン", "ブシン") in tokens and "無" not in {t[0] for t in tokens}
    with patch.object(analyzer, "compound_joins", dict):
        assert "ブシン" not in _surfaces(tokenizer, "今年のブシン祭が始まる。")


# --- a story's own kanji terms ------------------------------------------------------------------------------------ #
# 焔魄陣 is a made-up technique: no dictionary holds it, and the tagger cuts it into three single kanji (焔 read as 炎).
HOMURA = "焔魄陣を放った。\n彼の焔魄陣は強い。\n"
JIN = "焔魄陣が光る。\n陣が崩れた。\n"
_RULE = "-" * 60


def _transcript(kind, body):
    """A transcript as the YouTube downloader writes it: six header lines naming the captions' kind, then the cues."""
    return f"技の解説\nチャンネル | 2026-09-01 | 10:00\nCaptions: ja ({kind})\nhttps://example.com/v\n\n{_RULE}\n{body}"


def _record(runs, q, **extra):
    """A record as the token store keeps one: `runs` [(sentence, spelling, kinds)] as spans of one-kanji runs, each a
    sentence of its own; `q` each kanji's uses standing alone."""
    spans = [[s, 0, len(spelling), 0, sum(k in "cg" for k in kinds), "w", spelling, 0, kinds]
             for s, spelling, kinds in runs]
    return dict({"s": spans, "q": q}, **extra)


def test_a_work_term_the_library_keeps_using_is_one_word_everywhere(tmp_path, tokenizer):
    """焔魄陣 three times and 焔 never alone: it sticks (1.0) and has its 3 uses, so the table the index computes names
    it — keyed as a word no dictionary has, the spelling with no reading. The cached tokens every run reads and live
    text (known words, Junban, the card matcher) both read it as one word; the cache itself still holds the pieces
    (a new table needs no re-reading), and 陣 alone is still 陣."""
    store, paths = _library(tmp_path / "lib", {"a.txt": HOMURA, "b.txt": JIN})
    try:
        tables = store.names_tables()
        assert tables["w"]["焔魄陣"] == [1.0, "焔魄陣", "", "焔魄陣"]
        assert _cached_surfaces(store, paths[0]) == ["焔魄陣", "を", "放っ", "た", "彼", "の", "焔魄陣", "は", "強い"]
        assert _cached_surfaces(store, paths[1])[-4:] == ["陣", "が", "崩れ", "た"], "陣 alone is still 陣"
        raw = ti._decode_tokens(store.conn.execute("SELECT tokens FROM files WHERE path=?",
                                                   (ti._norm(paths[0]),)).fetchone()[0])
        assert "焔魄陣" not in [t[2] for _s, tokens in raw for t in tokens]
    finally:
        store.close()
    names.use_library_tables(tables)
    assert ("焔魄陣", "", "焔魄陣", "焔魄陣") in _tokens(tokenizer, "昨日も焔魄陣を見た。")


def test_work_terms_floor_stickiness_and_flip_guard():
    """The katakana gauge: a run's uses over the lone uses of its least-used kanji. Under 3 uses or under 0.7 it stays
    in pieces; a term the last table joined stays down to 0.5."""
    def library(uses, lone):
        return [_record([(s, "焔魄陣", "ccc") for s in range(uses)], {"焔": lone, "魄": 50, "陣": 50})]
    joined_before = {"w": {"焔魄陣": [0.8, "焔魄陣", "", "焔魄陣"]}}
    assert "焔魄陣" not in names.compute_tables(library(2, 2))["w"], "two uses: under the floor of three"
    assert "焔魄陣" not in names.compute_tables(library(6, 10))["w"], "0.6: not enough to join"
    assert "焔魄陣" in names.compute_tables(library(6, 10), joined_before)["w"], "0.6: enough to stay"
    assert "焔魄陣" not in names.compute_tables(library(4, 10), joined_before)["w"], "0.4: it goes"
    assert names.compute_tables(library(7, 10))["w"]["焔魄陣"][0] == 0.7, "0.7 joins"
    assert names.compute_tables([])["w"] == {}, "an empty library: an empty table"


def test_a_kanji_name_is_taken_first_and_its_kanji_uses_leave_the_gauge(tmp_path, monkeypatch):
    """琴葉 (a given name in JMnedict) + 焔魄陣 is one run of five single kanji. The kanji name joins first (the
    library holds it 3 times) and the term joins in what it leaves — never 琴葉焔魄陣, never the name as a term. With
    kanji names off the whole run is one stretch no table holds: the name is never the terms' to take."""
    files = {"a.txt": "琴葉焔魄陣！\n琴葉は笑った。\n", "b.txt": "琴葉焔魄陣が光る。\n焔魄陣を放った。\n"}
    store, paths = _library(tmp_path / "lib", files)
    try:
        tables = store.names_tables()
        assert "琴葉" in tables["j"] and set(tables["w"]) == {"焔魄陣"}
        assert _cached_surfaces(store, paths[0])[:2] == ["琴葉", "焔魄陣"]
        _switch(monkeypatch, "names_kanji", False)
        assert _cached_surfaces(store, paths[0])[:5] == ["琴", "葉", "焔", "魄", "陣"]
        assert _cached_surfaces(store, paths[1])[-4:] == ["焔魄陣", "を", "放っ", "た"], "alone, it is still a term"
    finally:
        store.close()


def test_a_kanji_names_uses_leave_the_gauge():
    """魄 stands alone 10 times, 4 of them inside the kanji name 魄斗: those are the name's, not 魄's own, so the term
    焔魄 (5 uses) is measured against 6 — 0.83, and joins. Counted with them it would be 0.5, and stay in pieces."""
    runs = [(s, "焔魄", "cc") for s in range(5)] + [(s, "魄斗", "cc") for s in range(5, 9)]
    name = [[s, 0, 2, 0, 2, "j", "魄斗", 0] for s in range(5, 9)]
    record = _record(runs, {"焔": 20, "魄": 10, "斗": 4}, jc={"魄斗": 4}, jb={"魄斗": 2})
    record["s"] += name
    tables = names.compute_tables([record])
    assert "魄斗" in tables["j"] and tables["w"]["焔魄"][0] == 0.833
    # Where the name's guards refused it (so no name span was recorded there), 魄斗 is left as a stretch of its own:
    # still the kanji name's, never a term.
    elsewhere = _record([(s, "魄斗", "cc") for s in range(3)], {"魄": 3, "斗": 3})
    assert "魄斗" not in names.compute_tables([record, elsewhere])["w"]
    record["jc"] = {}
    assert "焔魄" not in names.compute_tables([record])["w"]


def test_a_work_term_is_never_a_dictionary_word(tmp_path, monkeypatch):
    """What a word is comes from Japanese as a whole: a spelling JMdict lists (鄭寧, Sōseki's 丁寧) is never the
    library's to join, however sticky, nor is one the compound or affix tables hold (their switches decide it). An
    unreadable JMdict list makes no term at all — it must never pass every spelling."""
    store, paths = _library(tmp_path / "lib", {"a.txt": "彼は鄭寧に頭を下げた。\n鄭寧に礼を言った。\n鄭寧に答えた。\n"})
    try:
        assert "鄭寧" not in store.names_tables()["w"] and "鄭寧" not in store.names_tables()["j"]
        assert "鄭寧" not in _cached_surfaces(store, paths[0])
    finally:
        store.close()
    library = [_record([(s, "焔魄陣", "ccc") for s in range(5)], {"焔": 5, "魄": 5, "陣": 5})]
    assert "焔魄陣" in names.compute_tables(library)["w"]
    monkeypatch.setattr(analyzer, "compound_joins", lambda: {"焔魄陣": ("焔魄陣", "エンハクジン", "N", 1)})
    assert "焔魄陣" not in names.compute_tables(library)["w"], "the compound table's word"
    monkeypatch.undo()
    monkeypatch.setattr(names, "_jmdict_kanji", [None])
    assert names.compute_tables(library)["w"] == {}, "no JMdict list: no term"


@pytest.mark.parametrize("spelling, kinds, joins, why", [
    ("蒼乃牙", "cgc", False, "a grammar piece (乃 read as a particle)"),
    ("焔之牙", "cgc", True, "a name's linking 之 inside it, as a kanji name may hold one"),
    ("谷君", "cc", False, "an honorific last: a name and its suffix are two words"),
    ("魄前", "cc", False, "a position word last"),
    ("七九", "nn", False, "numbers alone are numbers"),
    ("蒼十牙", "cnc", True, "a number inside a term"),
    ("零魄", "nc", True, "a number first — a family name the names dictionary lacks"),
])
def test_work_term_guards_one_by_one(spelling, kinds, joins, why):
    """Each run is sticky (1.0) with 5 uses, and no dictionary spells it: only its shape decides."""
    library = [_record([(s, spelling, kinds) for s in range(5)], {c: 5 for c in spelling})]
    assert (spelling in names.compute_tables(library)["w"]) is joins, why


def test_auto_caption_transcripts_do_not_count(tmp_path):
    """YouTube's speech recognition misspells a word the same way every time, so its transcripts never tell the library
    what a story's words are: their uses count toward nothing — a term met twice in hand-written captions and five
    times in auto-generated ones stays in pieces. A third hand-written use makes it a term, and then it is one word in
    the auto-generated transcript too. Auto-translated captions are the machine's too."""
    auto = _transcript("native auto", "焔魄陣が見えた 焔魄陣を放った\n焔魄陣だ 焔魄陣 焔魄陣\n")
    manual = _transcript("manual", "焔魄陣が見えた。\n焔魄陣を放った。\n")
    store, paths = _library(tmp_path / "lib", {"auto.txt": auto, "manual.txt": manual})
    try:
        assert "焔魄陣" not in store.names_tables()["w"], "two counted uses: the auto-generated five count for nothing"
        record = ti._decode_counts(store.conn.execute("SELECT names FROM files WHERE path=?",
                                                      (ti._norm(paths[0]),)).fetchone()[0])
        assert record["a"] == 1 and "a" not in ti._decode_counts(store.conn.execute(
            "SELECT names FROM files WHERE path=?", (ti._norm(paths[1]),)).fetchone()[0])
    finally:
        store.close()
    more = {"auto.txt": auto, "manual.txt": manual, "more.txt": "焔魄陣が光る。\n"}
    store, paths = _library(tmp_path / "more", more)
    try:
        assert "焔魄陣" in store.names_tables()["w"]
        assert "焔魄陣" in _cached_surfaces(store, paths[0]), "a term joins in auto-generated captions too"
    finally:
        store.close()
    translated = {"auto.txt": _transcript("auto-translated", "焔魄陣が見えた\n焔魄陣を放った\n焔魄陣だ\n"),
                  "manual.txt": manual}
    store, _paths = _library(tmp_path / "translated", translated)
    try:
        assert "焔魄陣" not in store.names_tables()["w"]
    finally:
        store.close()


def test_the_caption_kind_a_transcript_names():
    """The downloader's header names its captions' kind on its third line; any other text names none. extract_text
    tells a caller that asks (the token store) and gives the same text either way."""
    assert analyzer.caption_kind(_transcript("native auto", "こんにちは\n")) == "native auto"
    assert analyzer.caption_kind(_transcript("auto-translated", "")) == "auto-translated"
    assert analyzer.caption_kind(_transcript("manual", "こんにちは\n")) == "manual"
    assert analyzer.caption_kind("Captions: ja (native auto)\n今日は晴れ。\n") is None, "no header: a line of text"
    assert analyzer.AUTO_CAPTIONS == {"native auto", "auto-translated"}


def test_extract_text_reports_the_caption_kind_and_changes_nothing(tmp_path):
    path = tmp_path / "talk.txt"
    path.write_text(_transcript("native auto", "焔魄陣が見えた\n"), encoding="utf-8")
    facts = {}
    assert analyzer.extract_text(str(path), "ja", facts) == analyzer.extract_text(str(path), "ja") == "焔魄陣が見えた\n"
    assert facts == {"captions": "native auto"}
    book = tmp_path / "book.txt"
    book.write_text("焔魄陣が見えた。\n", encoding="utf-8")
    facts = {}
    analyzer.extract_text(str(book), "ja", facts)
    assert facts == {"captions": None}


def test_dropped_pieces_join_in_place(tmp_path, tokenizer):
    """A number or a kanji the tagger reads as a symbol is no word alone, so a term that holds one covers fewer
    counted tokens than it has pieces: 零魄 (零 a number) replaces 魄 alone, 蒼十三牙 its two words, and 玖崩 (both read
    as symbols) is put in where nothing was counted. The cached tokens and live text read them the same, and the
    Rarity slider's totals take each term's use and give back its counted pieces."""
    files = {"a.txt": "零魄を唱えた。\n蒼十三牙を放った。\n玖崩が光る。\n",
             "b.txt": "零魄を唱えた。\n蒼十三牙を放った。\n玖崩が光る。\n",
             "c.txt": "零魄を唱えた。\n蒼十三牙を放った。\n玖崩が光る。\n"}
    store, paths = _library(tmp_path / "lib", files)
    try:
        tables = store.names_tables()
        assert {"零魄", "蒼十三牙", "玖崩"} <= set(tables["w"])
        cached = [[t[2] for t in tokens] for _s, tokens in store.file_tokens(paths[0])]
        assert cached == [["零魄", "を", "唱え", "た"], ["蒼十三牙", "を", "放っ", "た"], ["玖崩", "が", "光る"]]
        adjust, total = store._names_adjustment()
        assert adjust[("零魄", "")] == 3 and adjust[("魄", "ハク")] == -3
        assert adjust[("蒼十三牙", "")] == 3 and adjust[("青", "アオ")] == -3 and adjust[("牙", "キバ")] == -3
        assert adjust[("玖崩", "")] == 3 and total == 3 - 3 + 3 - 6 + 3
    finally:
        store.close()
    names.use_library_tables(tables)
    live = [[t[2] for t in tokens] for _s, tokens in tokenizer.tokenize_sentences(files["a.txt"])]
    assert live == cached


def _names_adjust_in_one_pass(store):
    """The name tables' adjustments summed afresh over every file in one pass — what the store computed before it
    kept each file's share (Store._names_adjust) — the reference the kept shares are checked against."""
    tables = store.names_tables()
    if not tables:
        return {}
    spellings = {kind: set(table) for kind, table in tables.items() if isinstance(table, dict)}
    terms = spellings.get("w", ())
    combos = [(f"{r:d}{k:d}{t:d}", (bool(r), bool(k), bool(t)))
              for r in (1, 0) for k in (1, 0) for t in (1, 0) if r or k or t]
    deltas = {combo: [Counter(), 0, Counter()] for combo, _switches in combos}
    for tokens_blob, names_blob in store.conn.execute(
            "SELECT tokens, names FROM files WHERE names IS NOT NULL").fetchall():
        spans = ti._decode_counts(names_blob).get("s", [])
        if not any(span[6] in spellings.get(span[5], ()) or (span[5] == "w" and ti._holds_a_term(span[6], terms))
                   for span in spans):
            continue
        sentences = ti._decode_tokens(tokens_blob)
        alone = {}
        for combo, switches in combos:
            delta = deltas[combo]
            cuts = {}
            for s, a, b, token in names.chosen(sentences, spans, tables, *switches):
                cuts.setdefault(s, []).append((a, b, token))
                for (lemma, reading, surface, *_rest), sign in [(token, 1)] + [(p, -1) for p in sentences[s][1][a:b]]:
                    if analyzer.has_target_language(lemma, "ja") or analyzer.has_target_language(surface, "ja"):
                        delta[0][(lemma, reading)] += sign
                        delta[1] += sign
            for s, joins in cuts.items():
                text, tokens = sentences[s]
                pieces = alone.get(s)
                if pieces is None:
                    pieces = alone[s] = analyzer.bound_uses(text, tokens)
                joined, gone, beside, shift = list(tokens), set(), set(), 0
                for a, b, _token in joins:
                    gone.update(range(max(a - 1, 0), min(b + 1, len(tokens))))
                    if a:
                        beside.add(a - 1 - shift)
                    if b < len(tokens):
                        beside.add(a - shift + 1)
                    shift += b - a - 1
                for a, b, token in reversed(joins):
                    joined[a:b] = [token]
                for i in gone & pieces:
                    delta[2][(tokens[i][0], tokens[i][1])] -= 1
                for i in analyzer.bound_uses(text, joined, only=sorted(beside)):
                    delta[2][(joined[i][0], joined[i][1])] += 1
    return {combo: {"counts": [[l, r, n] for (l, r), n in counts.items() if n], "total": total,
                    "bound": [[l, r, n] for (l, r), n in pieces.items() if n]}
            for combo, (counts, total, pieces) in deltas.items()}


def test_the_name_adjustments_kept_per_file_equal_a_full_recompute(tmp_path, monkeypatch):
    """The Rarity slider's name-table adjustments remember each file's share, so a Generate after one file changed
    reads that file again — not every file holding a name. The stored adjustments stay byte for byte what summing
    every file afresh gives, after every kind of change: a file edited (holding a name, or none), removed and added
    back (a kanji name leaving the tables and joining them again: the files still holding it read otherwise), edited
    to the same size, a new file, the tokenizer's identity changing and a newer engine (every file read again), and a
    kept share that won't read. Katakana runs, kanji names and a work's terms together; a word glued to a name that is
    a piece before the join and after it (年 after a number: its share nets to nothing in one file, yet the summed
    words keep the order a single pass meets them); a nested folder, CRLF, an empty file."""
    folder = tmp_path / "lib"
    (folder / "deep" / "er").mkdir(parents=True)
    terms = "零魄を唱えた。\n蒼十三牙を放った。\n玖崩が光る。\n"
    files = {"station.txt": STATION, "shop.txt": SHOP, "park.txt": PARK, "a.txt": SOTA,
             "deep/er/b.txt": "奏汰は笑った。\r\n" + HOMURA, "c.txt": JIN, "d.txt": terms * 3, "empty.txt": "",
             "g.txt": "三年奏汰が来た。\n父奏汰が笑った。\n", "h.txt": "年奏汰と話した。\n"}
    store, paths = _library(folder, files)
    by_name = dict(zip(files, paths))
    signature = ti.build_signature("ja")
    shares = []
    real_share = store._names_share
    monkeypatch.setattr(store, "_names_share", lambda sentences, *rest: shares.append(sentences) or
                        real_share(sentences, *rest))

    def write(name, text):
        path = by_name[name]
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        stamp = os.path.getmtime(path) + 2 + len(shares)      # a new (mtime, size) whatever the clock's grain
        os.utime(path, (stamp, stamp))

    def reconcile(build_signature=signature):
        shares.clear()
        store.reconcile([p for p in by_name.values() if os.path.exists(p)], ti.make_tokenizer("ja"),
                        build_signature=build_signature)
        assert store.get_meta("names_adjust") == json.dumps(_names_adjust_in_one_pass(store), ensure_ascii=False)
        return len(shares)

    try:
        tables = store.names_tables()
        assert "メロンベンチ" in tables["k"] and "奏汰" in tables["j"] and {"焔魄陣", "零魄"} <= set(tables["w"])
        assert store.get_meta("names_adjust") == json.dumps(_names_adjust_in_one_pass(store), ensure_ascii=False)
        holding = len(json.loads(store.get_meta("names_adjust_files"))["files"])
        assert holding == 8, "every file holding a joined name has its share kept (not park.txt, not empty.txt)"
        bound = [lemma for lemma, _reading, _n in json.loads(store.get_meta("names_adjust"))["111"]["bound"]]
        assert bound.index("年") < bound.index("父"), "年 is met first, in the file where it nets to nothing"

        write("shop.txt", SHOP + "メロンベンチが好きだ。\n")
        assert reconcile() == 1, "one file holding a name changed: only it is read again"
        write("park.txt", PARK + "公園は広い。\n")
        assert reconcile() == 0, "a file holding no name: nothing is read again"
        removed = {name: by_name.pop(name) for name in ("a.txt", "g.txt")}
        for path in removed.values():
            os.remove(path)
        assert reconcile() == 1 and "奏汰" not in store.names_tables()["j"], \
            "奏汰 leaves the tables: b.txt (still holding a term) reads otherwise; h.txt now holds no name at all"
        by_name.update(removed)
        write("a.txt", SOTA)
        write("g.txt", files["g.txt"])
        assert reconcile() == 4 and "奏汰" in store.names_tables()["j"], "back: every file holding it"
        same_size = SHOP.replace("メロンベンチ", "メロンとパン", 1) + "メロンベンチが好きだ。\n"
        assert len(same_size.encode("utf-8")) == os.path.getsize(by_name["shop.txt"])
        write("shop.txt", same_size)
        assert reconcile() == 1, "the same size, a new time: read again"
        stamp = os.path.getmtime(by_name["shop.txt"])
        write("shop.txt", same_size + "メロンベンチ。\n")
        os.utime(by_name["shop.txt"], (stamp, stamp))
        assert reconcile() == 1, "a new size at the same time: read again"
        by_name["e.txt"] = str(folder / "e.txt")
        write("e.txt", HOMURA)
        assert reconcile() == 1
        by_name["lone.txt"] = str(folder / "lone.txt")
        write("lone.txt", "焔が燃えた。\n魄が抜けた。\n陣が崩れた。\n" * 6)
        assert reconcile() == 1 and "焔魄陣" not in store.names_tables()["w"], \
            "its kanji mostly stand alone now: the term leaves the tables — b.txt (still holding a name) reads " \
            "otherwise, the two files that held only the term hold no name now"
        by_name["k2.txt"] = str(folder / "k2.txt")
        write("k2.txt", STATION + "零魄を唱えた。\n")
        assert reconcile() == 1
        by_name["pieces.txt"] = str(folder / "pieces.txt")
        write("pieces.txt", "メロン。\nベンチ。\n" * 12)
        assert reconcile() == 1 and "メロンベンチ" not in store.names_tables()["k"], \
            "its words mostly stand alone now: the run leaves the tables — k2.txt (still holding a term) reads otherwise"
        holding = len(json.loads(store.get_meta("names_adjust_files"))["files"])
        assert reconcile(signature + "|another tokenizer") == holding, "every file read again: no share kept"
        monkeypatch.setattr(analyzer, "ENGINE_REVISION", analyzer.ENGINE_REVISION + 1)
        write("park.txt", PARK)
        assert reconcile(signature + "|another tokenizer") == holding, "a newer engine: no share kept"
        store.set_meta("names_adjust_files", "not json")
        write("park.txt", PARK + "\n")
        assert reconcile(signature + "|another tokenizer") == holding, "a share that won't read: computed again"
    finally:
        store.close()


def test_the_work_terms_switch_off(tmp_path, tokenizer, monkeypatch):
    """Off means today's behaviour — the cached tokens and live text in pieces, the Rarity slider counting the
    pieces — and needs no re-reading of any file (not in the cache's signature); the known words are read again. Before
    the first index there is no table: nothing joins."""
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(settings_manager, "get_user_file", lambda name: str(settings))
    store, paths = _library(tmp_path / "lib", {"a.txt": HOMURA, "b.txt": JIN})
    try:
        assert "焔魄陣" in _cached_surfaces(store, paths[0])
        sig = ti.known_signature(str(tmp_path / "KnownWord.json"))
        store.set_cached_known(sig, set(), set())
        _switch(monkeypatch, "names_work_terms", False)
        settings.write_text('{"logic": {"names_work_terms": false}}', encoding="utf-8")
        assert "焔魄陣" not in _cached_surfaces(store, paths[0])
        assert ti.build_signature("ja") == "ja|reinforce=False"
        assert store.get_cached_known(sig) is None, "the known words are read again"
        counts, _total = store.word_counts()
        assert ("焔魄陣", "") not in counts and counts[("炎", "ホノオ")] == 3
        names.use_library_tables(store.names_tables())
        assert "焔魄陣" not in _surfaces(tokenizer, "昨日も焔魄陣を見た。")
    finally:
        store.close()
    monkeypatch.setitem(analyzer.LOGIC, "names_work_terms", True)
    names.forget_library_tables()
    assert "焔魄陣" not in _surfaces(tokenizer, "昨日も焔魄陣を見た。"), "no store yet: no table"


def test_work_terms_edge_cases(tmp_path):
    """An empty file records nothing; a line of kanji the tagger reads only as symbols is a run like any other; CRLF
    reads as LF; a space inside a run makes two runs; nested folders are read like any; a kanji written as a
    compatibility ideograph (U+FA19, read as 神) keeps its written form in the joined word."""
    compat = "蒼" + chr(0xFA19) + "牙"         # 神 written as its compatibility ideograph
    files = {"empty.txt": "", "crlf.txt": "焔魄陣を放った。\r\n焔魄陣だ。\r\n",
             "deep/er/nested.txt": "焔魄陣が光る。\n焔 魄陣\n",
             "compat.txt": f"{compat}を放った。\n{compat}だ。\n{compat}が光る。\n",
             "symbols.txt": "玖崩\n"}
    for name in files:
        (tmp_path / "lib" / os.path.dirname(name)).mkdir(parents=True, exist_ok=True)
    store, paths = _library(tmp_path / "lib", files)
    try:
        tables = store.names_tables()
        assert "焔魄陣" in tables["w"] and "蒼神牙" in tables["w"] and "魄陣" not in tables["w"]
        empty = ti._decode_counts(store.conn.execute("SELECT names FROM files WHERE path=?",
                                                     (ti._norm(paths[0]),)).fetchone()[0])
        assert empty["s"] == [] and not empty["q"]
        assert _cached_surfaces(store, paths[1])[0] == "焔魄陣", "CRLF"
        [spaced] = [span for span in ti._decode_counts(store.conn.execute(
            "SELECT names FROM files WHERE path=?", (ti._norm(paths[2]),)).fetchone()[0])["s"] if span[6] == "魄陣"]
        assert spaced[5] == "w", "焔, then a space: 魄陣 is a run of its own"
        compat_tokens = [t for _s, tokens in store.file_tokens(paths[3]) for t in tokens]
        assert compat_tokens[0] == ["蒼神牙", "", compat, "蒼神牙"], "its text as written, its word as read"
        symbols = ti._decode_counts(store.conn.execute("SELECT names FROM files WHERE path=?",
                                                       (ti._norm(paths[4]),)).fetchone()[0])
        assert [span[6:] for span in symbols["s"]] == [["玖崩", 0, "xx"]]
    finally:
        store.close()


def test_live_text_looks_for_terms_only_where_one_can_stand(tokenizer, monkeypatch):
    """Live text (known words, Junban, the card matcher) looks for the runs of a line only where a term's first two
    kanji stand side by side, or where the line reads otherwise than it is written — then always: a term written with
    a compatibility ideograph still joins. A line with neither is passed over and reads exactly as it would have."""
    compat = "蒼" + chr(0xFA19) + "牙"
    names.use_library_tables({"k": {}, "j": {}, "w": {"焔魄陣": [1.0, "焔魄陣", "", "焔魄陣"],
                                                      "蒼神牙": [1.0, "蒼神牙", "", "蒼神牙"]}, "stamp": "live"}, pin=True)
    assert ("焔魄陣", "", "焔魄陣", "焔魄陣") in _tokens(tokenizer, "昨日も焔魄陣を見た。")
    assert ("蒼神牙", "", compat, "蒼神牙") in _tokens(tokenizer, f"彼は{compat}を放った。")
    before = _tokens(tokenizer, "今日は三人で公園に行った。")
    real = names.term_runs

    def must_not_run(*args, **kwargs):
        raise AssertionError("looked for runs on a line that holds no term")
    monkeypatch.setattr(names, "term_runs", must_not_run)
    assert _tokens(tokenizer, "今日は三人で公園に行った。") == before
    monkeypatch.setattr(names, "term_runs", real)


def test_the_cached_read_passes_over_runs_where_no_term_starts(monkeypatch):
    """The token store's cached read (Store.file_tokens; the Rarity slider's numbers) leaves out a recorded run of
    one-kanji pieces in which no term's first two kanji stand side by side — most runs are counts (一度, 十番隊) — and
    makes the same joins: the term still joins, and with the terms switched off no run is looked at."""
    analyzer.SANITIZE_JA = True
    record = names.Record()
    sentences = [[s, [list(token) for token in tokens]] for s, tokens in analyzer.JapaneseTokenizer(
        library=False).tokenize_sentences("一度は焔魄陣を見た。", names=record)]
    spans = record.data()["s"]
    assert sorted(span[6] for span in spans if span[5] == "w") == ["一度", "焔魄陣"]
    tables = {"k": {}, "j": {}, "w": {"焔魄陣": [1.0, "焔魄陣", "", "焔魄陣"]}, "stamp": "cached"}
    looked_at, real = [], names.choose
    monkeypatch.setattr(names, "choose", lambda cands, *rest: looked_at.extend(c.spelling for c in cands)
                        or real(cands, *rest))
    assert [token for _s, _a, _b, token in names.chosen(sentences, spans, tables)] == [
        ["焔魄陣", "", "焔魄陣", "焔魄陣"]]
    assert looked_at == ["焔魄陣"], "一度 holds no term's first two kanji: never looked at"
    looked_at.clear()
    assert list(names.chosen(sentences, spans, tables, terms=False)) == [] and looked_at == []


# --- JMdict's kanji spellings ------------------------------------------------------------------------------------- #
def test_jmdict_words_answer_from_the_shipped_kanji_forms(monkeypatch):
    """The guard asks JMdict's kanji forms (a run of kanji the tagger cut is written in kanji alone, so only such
    forms ever match one). Only the answers are kept, never the list's forms (a few dozen answers, not 233,000 forms
    in memory): a spelling asked again is answered without reading the list, a new one reads it again."""
    from app import jmdict_data
    from app.unicode_ranges import HAN
    real, reads = jmdict_data.kanji_forms, []
    monkeypatch.setattr(jmdict_data, "kanji_forms", lambda: reads.append(1) or real())
    monkeypatch.setattr(names, "_jmdict_kanji", [])
    asked = ("鄭寧", "十二支", "起承転結", "一発", "揚げる", "写輪眼")
    assert names.jmdict_words(asked) == {"鄭寧", "十二支", "起承転結", "一発", "揚げる"}
    assert set(names._jmdict_kanji[0]) == set(asked), "the answers, never the list"
    assert names.jmdict_words(["写輪眼", "鄭寧"]) == {"鄭寧"} and len(reads) == 1, "asked before: not read again"
    assert names.jmdict_words(["斬魄刀", "卍解", "霊圧"]) == set() and len(reads) == 2
    assert names.jmdict_words(()) == set() and len(reads) == 2
    kanji_alone = re.compile(f"[{HAN}]{{2,}}")
    forms = set(real().replace("\t", "\n").split("\n"))
    assert 120000 < sum(1 for form in forms if kanji_alone.fullmatch(form)) < 150000


@pytest.mark.parametrize("broken", [lambda: 1 / 0, lambda: "\n"], ids=["unreadable", "empty"])
def test_a_jmdict_list_that_cannot_be_read_answers_none(monkeypatch, broken):
    """A list that can't be read, or holds nothing, answers None — then no run is a term: an unreadable list must
    never pass every spelling. Remembered: it isn't read again."""
    from app import jmdict_data
    monkeypatch.setattr(names, "_jmdict_kanji", [])
    monkeypatch.setattr(jmdict_data, "kanji_forms", broken)
    assert names.jmdict_words(["焔魄陣"]) is None
    monkeypatch.setattr(jmdict_data, "kanji_forms", lambda: pytest.fail("read again"))
    assert names.jmdict_words(["焔魄陣", "鄭寧"]) is None


def test_the_shipped_kanji_spellings_say_which_entry_a_spelling_belongs_to():
    """app/jmdict_data.py keeps JMdict's kanji spellings entry by entry, so a later reader can tell one dictionary word
    from two: 生き and 活き are one entry, 集い is an entry of its own beside 集う, and 心する is no entry of 心."""
    from app import jmdict_data
    entries = {}
    for number, line in enumerate(jmdict_data.kanji_forms().split("\n")):
        for spelling in line.split("\t"):
            entries.setdefault(spelling, set()).add(number)
    assert entries["生き"] & entries["活き"]
    assert not entries["集い"] & entries["集う"]
    assert not entries["心する"] & entries["心"]
    assert jmdict_data.CREATED and jmdict_data.REVISION


# --- a whole run --------------------------------------------------------------------------------------------------- #
def _generate(tmp_path, files, known=()):
    """One real run (Generate) over a HighPriority library of `files` -> the priority list, as a DataFrame."""
    uf = tmp_path / "User Files" / "ja"
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text(
        json.dumps({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in known]}, ensure_ascii=False),
        encoding="utf-8")
    high = tmp_path / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    for name, body in files.items():
        (high / name).write_text(body, encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(tmp_path / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda l=None: str(tmp_path / "data" / l) if l else str(tmp_path / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(tmp_path / "User Files" / l) if l else str(tmp_path / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "1"]):
        analyzer.main()
    return pd.read_csv(results / "priority_learning_list.csv", encoding="utf-8-sig", keep_default_na=False)


def test_a_run_lists_each_name_once_and_knows_a_known_name(tmp_path):
    """Generate: the katakana name, the name the library keeps using and the kanji name are one row each, with no
    reading, and their pieces are no rows of their own; a known name (KnownWord.json, read with the tables the run just computed) is no
    row at all."""
    files = {"station.txt": STATION + "昨日、ミロナイが村に来た。\nミロナイは笑った。\n", "shop.txt": SHOP,
             "park.txt": PARK, "sota.txt": SOTA + "奏汰は笑った。\n"}
    listed = _generate(tmp_path / "first", files)
    rows = {w: (r, int(n)) for w, r, n in zip(listed["Word"], listed["Reading"], listed["Occurrences"])}
    assert rows["メロンベンチ"] == ("", 4) and rows["ミロナイ"] == ("", 2) and rows["奏汰"] == ("", 3)
    assert rows["ベンチ"][1] == 1 and "ミロ" not in rows and "ナイ" not in rows and "汰" not in rows
    listed = _generate(tmp_path / "second", files, known=("メロンベンチ",))
    assert "メロンベンチ" not in set(listed["Word"])


# --- the Settings window ------------------------------------------------------------------------------------------ #
def test_the_four_switches_in_settings_save_load_and_show_for_japanese_only(monkeypatch):
    """Settings -> Language & Parsing: four checkboxes, on by default, each with a tooltip that gives an example;
    shown for a Japanese library only. Ticking one saves it into settings.json's logic block — the dashboard rebuilds
    settings.json from scratch on every save, so an unlisted key would vanish. The katakana switch changes how every
    file reads, so it re-indexes the library; the other three use the library's tables — no file is read again (the
    known words are). The next start reads them back. One dashboard for all of it (one root per file)."""
    import tkinter as tk
    from tkinter import ttk
    import app.main as main_module
    from app import token_index

    real_tooltip, tipped = main_module.ToolTip, {}

    def recording(widget, text, *args, **kwargs):
        tipped[str(widget)] = text
        return real_tooltip(widget, text, *args, **kwargs)

    monkeypatch.setattr(main_module, "ToolTip", recording)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk is not available in this environment")
    root.withdraw()
    monkeypatch.setattr(tk, "_default_root", root)      # the dashboard's Tk variables belong to the default root
    settings_file = os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json")
    try:
        with patch.object(main_module.MasterDashboardApp, "check_updates_thread"):
            app = main_module.MasterDashboardApp(root)
        app.create_settings_window()
        frame = app.names_frame
        boxes = [w for w in frame.winfo_children() if isinstance(w, ttk.Checkbutton)]
        assert [b.cget("text") for b in boxes] == ["Katakana names as one word", "Names your library repeats as one word",
                                                   "Kanji names as one word",
                                                   "Kanji terms your library repeats as one word"]
        assert all(str(b) in tipped for b in boxes), "every toggle has a tooltip"
        assert "ミロ + ナイ → ミロナイ" in tipped[str(boxes[0])] and "奏 + 汰 → 奏汰" in tipped[str(boxes[2])]
        assert "laughter (アッハハ)" in tipped[str(boxes[0])], "what stays apart: laughter too"
        assert "斬魄刀" in tipped[str(boxes[3])] and "写輪眼" in tipped[str(boxes[3])], "both examples"
        assert "auto-generated captions" in tipped[str(boxes[3])]
        assert [app.var_names_katakana.get(), app.var_names_recurring.get(), app.var_names_kanji.get(),
                app.var_names_work_terms.get()] == [True] * 4
        assert frame.master is app.lang_options_frame and "Language & Parsing" in frame.master.master.cget("text")

        app.var_language.set("ja")
        assert frame.winfo_manager() == "pack"
        app.var_language.set("zh")
        assert frame.winfo_manager() == "", "Chinese has no such names"
        app.var_language.set("ja")

        # A store built as the settings stand, and a fresh known-words cache: only a choice can differ.
        store = token_index.open_store("ja")
        try:
            store.reconcile([], lambda path: {"sentences": [], "counts": {}},
                            build_signature=token_index.build_signature("ja"))
            known = os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", "ja", "KnownWord.json")
            store.set_cached_known(token_index.known_signature(known), set(), set())
        finally:
            store.close()

        def launches():
            app._indexer_busy = False
            with patch.dict(os.environ, {"SURASURA_NO_AUTOINDEX": ""}), patch.object(app, "run_command_async") as run:
                app._maybe_launch_indexer(force=True)
            return run.called

        def saved():
            with open(settings_file, encoding="utf-8") as handle:
                return json.load(handle)["logic"]

        assert not launches(), "nothing changed: no re-index"
        built = token_index.build_signature("ja")
        boxes[1].invoke()
        assert saved()["names_recurring"] is False
        boxes[2].invoke()
        assert saved()["names_kanji"] is False
        boxes[3].invoke()
        assert saved()["names_work_terms"] is False
        assert token_index.build_signature("ja") == built, "the library's tables: no file is read again"
        boxes[0].invoke()
        logic = saved()
        assert logic["names_katakana"] is False and logic["sentence_boundaries"], "the rest of the logic block is kept"
        assert token_index.build_signature("ja") != built and launches(), "every file reads differently: re-index"

        with open(settings_file, "w", encoding="utf-8") as handle:
            json.dump({"target_language": "ja", "logic": {"names_recurring": False}}, handle)
        app.load_settings()
        assert [app.var_names_katakana.get(), app.var_names_recurring.get(), app.var_names_kanji.get(),
                app.var_names_work_terms.get()] == [True, False, True, True], "a missing key reads as on"
    finally:
        root.destroy()

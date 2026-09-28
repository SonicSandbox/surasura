"""Names are one word, not pieces (app/names.py; Settings -> Language & Parsing).

A name the dictionary lacks is cut by the tagger into pieces that are words or letters of their own, and the pieces
then count as those words. analyzer.join_affixes — the one place every Japanese caller reads words through — keeps
such a name one word:

- katakana names (logic.names_katakana): a katakana run no JPDB 2024 / Jiten headword spells, with a piece that is no
  common word, is one word; a compound of common listed words, a repeated sound and a stutter stay in pieces.
- names that recur in the library (logic.names_recurring): a run of common words the rule above leaves in pieces is
  one word when the library keeps using it as one (its rarer piece mostly inside it, 3+ uses) — a table the token
  store computes after indexing, applied to its cached tokens and to live text alike; once joined, a run stays
  joined until it is clearly no longer sticky.
- kanji names (logic.names_kanji): a run of kanji the tagger cuts, spelled as a person's name in JMnedict and no
  dictionary word, is one word where no guard says its pieces are words there — once the library holds it 3+ times.

Made-up names and sentences throughout (ミロナイ, ハルミナ, メロンベンチ, 奏汰): the katakana rule is Japanese-wide;
the library tables are built here from made-up libraries, never the user's.
"""
import json
import os
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
    each a word the learner may know. A run a headword spells (トートバッグ) keeps the tagger's reading."""
    assert _surfaces(tokenizer, "ドラゴンケーキを焼いた。")[:2] == ["ドラゴン", "ケーキ"]
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
    assert not record.data()["jc"] and not record.data()["s"]


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
    monkeypatch.setattr(names, "REFRESH", 0.0)
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
def test_the_three_switches_in_settings_save_load_and_show_for_japanese_only(monkeypatch):
    """Settings -> Language & Parsing: three checkboxes, on by default, each with a tooltip that gives an example;
    shown for a Japanese library only. Ticking one saves it into settings.json's logic block — the dashboard rebuilds
    settings.json from scratch on every save, so an unlisted key would vanish. The katakana switch changes how every
    file reads, so it re-indexes the library; the other two use the library's tables — no file is read again (the
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
                                                   "Kanji names as one word"]
        assert all(str(b) in tipped for b in boxes), "every toggle has a tooltip"
        assert "ミロ + ナイ → ミロナイ" in tipped[str(boxes[0])] and "奏 + 汰 → 奏汰" in tipped[str(boxes[2])]
        assert [app.var_names_katakana.get(), app.var_names_recurring.get(), app.var_names_kanji.get()] == [True] * 3
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
        assert token_index.build_signature("ja") == built, "the library's tables: no file is read again"
        boxes[0].invoke()
        logic = saved()
        assert logic["names_katakana"] is False and logic["sentence_boundaries"], "the rest of the logic block is kept"
        assert token_index.build_signature("ja") != built and launches(), "every file reads differently: re-index"

        with open(settings_file, "w", encoding="utf-8") as handle:
            json.dump({"target_language": "ja", "logic": {"names_recurring": False}}, handle)
        app.load_settings()
        assert [app.var_names_katakana.get(), app.var_names_recurring.get(), app.var_names_kanji.get()] == \
            [True, False, True], "a missing key reads as on"
    finally:
        root.destroy()

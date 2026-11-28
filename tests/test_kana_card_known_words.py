"""A studied Anki card written in kana alone counts, in the known words, for the word its own sentence shows it to be.

Why: a かなう card whose sentence reads 敵う was placed as 敵う by Junban and the ✓ chip (they read a kana card through
its sentence: `anki_match.card_word_in_sentence`), while the list, the journey and the % still showed 敵う unknown — the
known-words sync wrote the bare かなう, and `analyzer.load_known_words` read it alone (適う, the tagger's guess). Now
the sync keeps each studied kana card's sentence beside KnownWord.json (`token_index.KANA_SENTENCES_FILE`; the file
itself stays append-only) and the known words read the card there, by the same rule — one source for all four.

A bare kana term with no sentence counts only for itself, as before: never a guess between 叶う, 敵う and 適う.
Real Japanese sentences; a fake AnkiConnect (never live Anki); the user's files in the test root (conftest).
"""
import json
import os
from unittest import mock

import pytest

from app import analyzer, anki_match, anki_sync
from app import token_index as ti
from app.path_utils import get_user_files_path
from tests.test_anki_sync import URL, FakeCollection

KANAU = "腕力では兄に<b>かないません</b>。"          # 'I can't match my brother for strength': 敵う
MAKU = "庭に水を<b>まく</b>。"                       # 'sprinkle water on the garden': 撒く (まく alone is 膜)
NOT_PLACED = "彼には<b>かなわない</b>よ。"           # かなわない is one word to the tagger: no token is かなう


@pytest.fixture(autouse=True)
def _ja():
    analyzer.SANITIZE_JA = True                     # as every run sets it before the known words are read
    yield


@pytest.fixture(scope="module")
def tok():
    return analyzer.JapaneseTokenizer()


def _known_file(entries, sentences=None, language="ja"):
    """KnownWord.json in the test root holding `entries` (dictForms, KNOWN, each a note id from 1), and — given
    `sentences` ({dictForm: [sentence, ...]}) — the side file the sync keeps beside it."""
    folder = get_user_files_path(language)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "KnownWord.json")
    words = [{"dictForm": term, "knownStatus": "KNOWN", "hasCard": 1, "ankiNoteId": n}
             for n, term in enumerate(entries, 1)]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"words": words}, f, ensure_ascii=False)
    side = ti.kana_sentences_path(path) if hasattr(ti, "kana_sentences_path") else os.path.join(
        folder, "anki_kana_sentences.json")
    if sentences:
        notes = {str(100 + i): [term, sentence] for i, (term, sentence) in
                 enumerate((t, s) for t, said in sentences.items() for s in said)}
        with open(side, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "notes": notes}, f, ensure_ascii=False)
    elif os.path.exists(side):
        os.remove(side)
    return path


# --------------------------------------------------------------------------- #
# The known words (analyzer.load_known_words)
# --------------------------------------------------------------------------- #
def test_a_studied_kana_card_counts_for_the_word_its_sentence_shows_and_never_its_homophones(tok):
    path = _known_file(["かなう", "まく"], {"かなう": [KANAU], "まく": [MAKU]})
    tuples, lemmas = analyzer.load_known_words(path, tok)
    assert ("敵う", "カナウ") in tuples and "敵う" in lemmas, "the word its sentence shows: the list's 敵う row"
    assert not {"叶う", "適う"} & lemmas, "homophones stay apart: neither the alone reading nor another"
    assert "撒く" in lemmas and "膜" not in lemmas, "まく in 水をまく is 撒く, never the 膜 it reads alone"
    assert {"かなう", "まく"} <= lemmas, "the card's own letters still count, as before"


def test_a_bare_kana_term_with_no_sentence_reads_as_it_always_did(tok):
    """No sentence kept (another source's entry, a card studied before the sync kept them): the term alone, as before."""
    path = _known_file(["かなう", "まく"])
    tuples, lemmas = analyzer.load_known_words(path, tok)
    assert "かなう" in lemmas and "敵う" not in lemmas and "叶う" not in lemmas
    assert "膜" in lemmas, "today's reading of a bare まく kept (no row moves without a sentence)"


def test_a_sentence_that_places_no_word_reads_the_card_as_itself_beside_one_that_does(tok):
    bare = analyzer.load_known_words(_known_file(["かなう"]), tok)
    alone = analyzer.load_known_words(_known_file(["かなう"], {"かなう": [NOT_PLACED]}), tok)
    assert alone == bare, "かなわない places no かなう token: the card is read as itself"
    both = analyzer.load_known_words(_known_file(["かなう"], {"かなう": [KANAU, NOT_PLACED]}), tok)
    assert both[1] == bare[1] | {"敵う"}, "two cards of one word: each sentence that places it counts its word"


def test_a_kanji_card_a_one_kana_card_and_a_card_not_known_never_read_a_sentence(tok):
    path = _known_file(["手伝う", "か"], {"手伝う": ["準備を<b>手伝って</b>くれた。"], "か": ["本当<b>か</b>？"]})
    with_sentences = analyzer.load_known_words(path, tok)
    assert with_sentences == analyzer.load_known_words(_known_file(["手伝う", "か"]), tok)
    # A word Still learning holds (not known): its kept sentence counts nothing.
    path = _known_file(["かなう"], {"かなう": [KANAU]})
    data = json.load(open(path, encoding="utf-8"))
    data["words"][0].update(knownStatus="LEARNING", hasCard=0)
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    assert analyzer.load_known_words(path, tok) == (set(), set())


def test_chinese_never_reads_the_kana_cards_file():
    """The rule is Japanese only: a Chinese known word reads as itself, whatever file sits beside it."""
    path = _known_file(["冒险"], {"冒险": ["我喜欢<b>冒险</b>。"]}, language="zh")
    zh = analyzer.ChineseTokenizer()
    with_file = analyzer.load_known_words(path, zh)
    os.remove(ti.kana_sentences_path(path))
    assert with_file == analyzer.load_known_words(path, zh) and "冒险" in with_file[1]


def test_the_per_term_cache_keys_a_kana_card_on_its_sentences_so_a_new_sentence_reads_only_that_term(tok, monkeypatch):
    """G8: a term read before isn't tokenized again. A kana card's sentences decide its words too, so they key it: the
    same file read again tokenizes nothing; a new sentence for it reads that one term again, never the others."""
    terms = {}
    analyzer.load_known_words(_known_file(["かなう", "冒険"], {"かなう": [KANAU]}), tok, terms)
    assert any(key.startswith("かなう\x00") for key in terms) and "冒険" in terms
    asked = []
    real = anki_match.card_word_in_sentence
    monkeypatch.setattr(anki_match, "card_word_in_sentence", lambda *a: (asked.append(a[1]), real(*a))[1])
    again = analyzer.load_known_words(_known_file(["かなう", "冒険"], {"かなう": [KANAU]}), tok, dict(terms))
    assert asked == [] and "敵う" in again[1], "read from the cache: no sentence read again"
    analyzer.load_known_words(_known_file(["かなう", "冒険"], {"かなう": [KANAU, MAKU]}), tok, dict(terms))
    assert sorted(asked) == sorted([KANAU, MAKU]), "only the term whose sentences changed is read again"


def test_the_known_signature_moves_with_the_kana_cards_file_and_is_unchanged_without_it():
    """Every cache of the known words and the run signature read `known_signature`: a sentence kept moves it; with no
    such file it is byte-identical to before (an upgrade re-normalizes nothing until the sync keeps one)."""
    path = _known_file(["かなう"])
    st = os.stat(path)
    assert ti.known_signature(path) == json.dumps([True, st.st_mtime, st.st_size])
    _known_file(["かなう"], {"かなう": [KANAU]})
    with_file = ti.known_signature(path)
    assert with_file != json.dumps([True, os.stat(path).st_mtime, os.stat(path).st_size])
    _known_file(["かなう"], {"かなう": [KANAU, MAKU]})
    assert ti.known_signature(path) != with_file


def test_an_unreadable_kana_cards_file_reads_every_term_as_itself(tok):
    path = _known_file(["かなう"])
    bare = analyzer.load_known_words(path, tok)
    with open(ti.kana_sentences_path(path), "w", encoding="utf-8") as f:
        f.write("{not json")
    assert analyzer.load_known_words(path, tok) == bare


def test_a_damaged_note_in_the_kana_cards_file_is_skipped_and_the_rest_still_read(tok):
    """One note cut short or not a pair (a hand edit, a damaged write) never stops the known words: it is skipped."""
    path = _known_file(["かなう"])
    with open(ti.kana_sentences_path(path), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "notes": {"1": ["かなう", KANAU], "2": 5, "3": ["まく"], "4": ["", ""]}}, f,
                  ensure_ascii=False)
    assert ti.kana_sentence_notes(path) == {"1": ["かなう", KANAU]}
    assert "敵う" in analyzer.load_known_words(path, tok)[1]


# --------------------------------------------------------------------------- #
# The sync keeps the sentences (anki_sync._keep_sentences)
# --------------------------------------------------------------------------- #
def _sync(fake, language="ja", decks=("TheBank",), **kw):
    with mock.patch("urllib.request.urlopen", fake):
        return anki_sync.sync(language, URL, list(decks), [], **kw)


def _kept(language="ja"):
    path = os.path.join(get_user_files_path(language), ti.KANA_SENTENCES_FILE)
    if not os.path.exists(path):
        return None
    return json.load(open(path, encoding="utf-8"))["notes"]


def _collection():
    fake = FakeCollection()
    kanau = fake.add("", fields=[("Expression", "かなう"), ("Sentence", KANAU)])
    fake.add("", fields=[("Expression", "冒険"), ("Sentence", "冒険の<b>準備</b>をする。")])
    fake.add("", fields=[("Expression", "かける"), ("Sentence", "")])          # kana, but no sentence to read
    return fake, kanau


def test_the_sync_keeps_each_studied_kana_cards_sentence_and_never_rewrites_an_entry():
    fake, kanau = _collection()
    assert _sync(fake).error is None
    assert _kept() == {str(kanau): ["かなう", KANAU]}, "only a kana card with a sentence"
    words = json.load(open(os.path.join(get_user_files_path("ja"), "KnownWord.json"), encoding="utf-8"))["words"]
    assert [w["dictForm"] for w in words] == ["かなう", "冒険", "かける"] and not any("sentence" in w for w in words)
    before = open(os.path.join(get_user_files_path("ja"), "KnownWord.json"), "rb").read()
    again = _sync(fake)
    assert again.mode == "delta" and again.added == 0, "its own write signs the state: the next sync is a delta"
    assert open(os.path.join(get_user_files_path("ja"), "KnownWord.json"), "rb").read() == before


def test_cards_studied_before_the_sentences_were_kept_are_read_once_by_one_full_sync():
    """A state saved under READING_VERSION 2 (every sync before this): the next sync reads every card in full, once — the
    kana card's sentence is kept, KnownWord.json is not written (nothing new) — and the one after is a delta."""
    fake, kanau = _collection()
    _sync(fake)
    os.remove(os.path.join(get_user_files_path("ja"), ti.KANA_SENTENCES_FILE))
    state_path = os.path.join(get_user_files_path("ja"), "anki_sync_state.json")
    state = json.load(open(state_path, encoding="utf-8"))
    known = os.path.join(get_user_files_path("ja"), "KnownWord.json")
    state.update(reading=2, known_sig=ti.known_signature(known))
    json.dump(state, open(state_path, "w", encoding="utf-8"))
    before = open(known, "rb").read()
    first = _sync(fake)
    assert first.mode == "full" and first.added == 0 and _kept() == {str(kanau): ["かなう", KANAU]}
    assert open(known, "rb").read() == before, "append-only: the full read rewrote no entry"
    assert _sync(fake).mode == "delta"


def test_an_edited_cards_sentence_is_read_again_and_a_card_no_longer_in_kana_drops_out():
    fake, kanau = _collection()
    _sync(fake)
    fake.edit(kanau, [("Expression", "かなう"), ("Sentence", "長年の夢が<b>かなった</b>。")])
    _sync(fake)
    assert _kept() == {str(kanau): ["かなう", "長年の夢が<b>かなった</b>。"]}
    fake.edit(kanau, [("Expression", "敵う"), ("Sentence", KANAU)])
    _sync(fake)
    assert _kept() == {}, "written in kanji now: its own lemma, no sentence needed"


def test_replace_keeps_only_the_sentences_of_the_cards_it_read():
    fake, kanau = _collection()
    _sync(fake)
    side = os.path.join(get_user_files_path("ja"), ti.KANA_SENTENCES_FILE)
    kept = json.load(open(side, encoding="utf-8"))
    kept["notes"]["1"] = ["まく", MAKU]                                       # a card since gone from the decks
    json.dump(kept, open(side, "w", encoding="utf-8"), ensure_ascii=False)
    with mock.patch("urllib.request.urlopen", fake):
        assert anki_sync.replace("ja", URL, ["TheBank"], []).error is None
    assert _kept() == {str(kanau): ["かなう", KANAU]}
    assert _sync(fake).mode == "delta", "Replace signs the state after the sentences: no full read again"


def test_a_chinese_sync_keeps_no_sentences(zh_resources_dir):
    zh = FakeCollection()
    zh.add("", deck="中文::词汇", model="Chinese (basic)", fields=[("Hanzi", "冒险"), ("Sentence", "我喜欢冒险。")])
    assert _sync(zh, language="zh", decks=["中文"]).error is None
    assert _kept("zh") is None


# --------------------------------------------------------------------------- #
# One source: the list and the journey, Junban and the ✓ chip agree
# --------------------------------------------------------------------------- #
def test_the_list_the_journey_junban_and_the_chip_read_one_known_word_for_a_kana_card(tmp_path, tok):
    """After a sync, one ja library: the run's known words (`read_known_words`, the list and the %), the store's cached
    normalization (the journey's and the ✓ chip's known set), Junban's known test and the chip's word for the card all
    say the かなう card is 敵う — known — and none says 叶う."""
    from app.services import card_chip
    from modules.junban import reposition
    fake, _kanau = _collection()
    _sync(fake)
    known = os.path.join(get_user_files_path("ja"), "KnownWord.json")
    store = ti.open_store("ja")
    try:
        suffix = store.known_suffix()
        tuples, lemmas = analyzer.read_known_words(store, known, ti.known_signature(known), tok)
        assert "敵う" in lemmas and "叶う" not in lemmas, "the list and the %"
        assert "敵う" in store.get_cached_known(ti.known_signature(known), suffix)[1], "the journey's read"
        chip_word = anki_match.card_word_in_sentence("かなう", KANAU, tok.tokenize)[0]
        assert chip_word == "敵う" and chip_word in card_chip._store_known(store, None)[1], "the ✓ chip"
    finally:
        store.close()
    assert reposition.known_test("ja", {}, tok)("かなう", KANAU), "Junban's known tier"

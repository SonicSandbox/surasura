"""The core match index (`app/anki_match.py`) — how a word on an Anki card is recognised as a word on
Surasura's list, for Junban's reorder and the report's backlog badge alike (Junban_Backlog_Spec).

Junban's suite (`modules/junban/tests/test_match.py`) exercises the same code through the re-export in
`modules/junban/match.py`; these tests pin it on its own, so it holds with `modules/` deleted (the
Prime Invariant). Real data throughout: the repo's analyser-made golden list and real Lapis notes.
"""
import csv
import json
import os
import subprocess
import sys

from app import anki_match

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_LIST = os.path.join(PROJECT_ROOT, "tests", "Test Resources", "ja", "expected_output.csv")


def _write_list(path, rows):
    """A list the way the analyser writes it: UTF-8 with a BOM, `Forms` `|`-joined."""
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Word", "Orth", "Forms"])
        writer.writerows(rows)
    return str(path)


def _note(model, fields):
    """A `notesInfo` reply, in Anki's own shape: {name: {"value": …, "order": n}}."""
    return {"noteId": 1789711432547, "modelName": model,
            "fields": {name: {"value": value, "order": order}
                       for order, (name, value) in enumerate(fields)}}


def test_importing_the_matcher_is_cheap():
    """The report generator and Junban's settings path both reach this file, so it must stay a pure,
    stdlib-only reader: no tokenizer, no GUI, no network. A CLEAN subprocess — pytest has already
    imported half of these in this process (mirrors `tests/test_lazy_imports.py`)."""
    watch = ("fugashi", "unidic_lite", "jieba", "pandas", "tkinter", "urllib.request")
    code = ("import app.anki_match; import sys; "
            "print(','.join(m for m in %r if m in sys.modules))" % (watch,))
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"importing app.anki_match failed:\n{result.stderr}"
    assert [m for m in result.stdout.strip().split(",") if m] == []


def test_the_real_golden_list_indexes_by_orth_and_by_word():
    """The analyser's own 160-row output (BOM, real columns): a katakana lemma the user would never
    type (ナカノ) and the spelling their content uses (中野) reach the same rank."""
    index = anki_match.build_index(GOLDEN_LIST)

    assert index.rank_of["中野"] == index.rank_of["ナカノ"] == 16
    assert index.rank_of["うう"] == 0
    assert index.marks_of, "markers are built for every row"


def test_a_mined_lapis_note_resolves_to_its_word_without_the_furigana():
    """Field 0 of anki_miner's note type, as it arrives: the reading in brackets, the sentence next
    to it. The bracket goes; nothing else changes."""
    note = _note("Lapis", [("Expression", "引[ひ]きずる"),
                           ("Sentence", "彼は足を引きずって歩いていた。")])
    assert anki_match.target_word(note, {}) == "引きずる"


# --------------------------------------------------------------------------- #
# WP-B2: spellings the content used, one-character keys, the kana fold
# --------------------------------------------------------------------------- #
def test_a_spelling_the_content_used_reaches_its_word(tmp_path):
    """The card says 見とれる, the list's word is 見惚れる — the same verb, and the content itself wrote
    it the card's way, so `Forms` carries it (a real miss on the user's backlog)."""
    path = _write_list(tmp_path / "list.csv", [("冒険", "冒険", ""),
                                               ("見惚れる", "見惚れる", "見とれる|見惚れ|見とれ")])
    index = anki_match.build_index(path, language="ja")

    assert anki_match.lookup("見とれる", index.rank_of, "ja") == "見とれる"
    assert index.rank_of["見とれる"] == index.rank_of["見惚れる"] == 1


def test_a_spelling_that_is_another_rows_own_word_stays_with_that_row(tmp_path):
    """生き is a spelling of 生きる in the content, but 生き is also a word of its own further down.
    A card that says 生き is the noun: an exact word always beats a borrowed spelling."""
    path = _write_list(tmp_path / "list.csv", [("生きる", "生きる", "生き|生きれ"),
                                               ("冒険", "冒険", ""),
                                               ("生き", "生き", "")])
    index = anki_match.build_index(path, language="ja")

    assert index.rank_of["生き"] == 2
    assert index.rank_of["生きれ"] == 0


def test_one_character_keys_in_japanese_are_only_a_rows_own_word(tmp_path):
    """谷 is the surname タニ's commonest spelling, and 見 a stem of 見る: as keys they matched real 谷
    and 見 cards to the wrong word. 猫 — a one-character word that IS the row's lemma (single
    characters switched on) — keeps its key."""
    path = _write_list(tmp_path / "list.csv", [("タニ", "谷", ""),
                                               ("見る", "見る", "見|見れ"),
                                               ("猫", "猫", "")])
    rank_of = anki_match.build_index(path, language="ja").rank_of

    assert "谷" not in rank_of and "見" not in rank_of
    assert rank_of["タニ"] == 0 and rank_of["見れ"] == 1
    assert rank_of["猫"] == 2


def test_chinese_keeps_its_one_character_words(tmp_path):
    """Most of Chinese's commonest words are one character (我, 看) — the guard is Japanese-only."""
    path = _write_list(tmp_path / "list.csv", [("我", "我", ""), ("图书馆", "图书馆", ""),
                                               ("看", "看", "")])
    rank_of = anki_match.build_index(path, language="zh").rank_of

    assert rank_of == {"我": 0, "图书馆": 1, "看": 2}


def test_katakana_on_the_card_finds_hiragana_in_the_list_and_back(tmp_path):
    """スルリ on the card, するり in the subtitles (a real miss); ピカピカ in the list, ぴかぴか on a
    card. The same word in the other kana script."""
    path = _write_list(tmp_path / "list.csv", [("するり", "するり", ""), ("ピカピカ", "ピカピカ", "")])
    rank_of = anki_match.build_index(path, language="ja").rank_of

    assert anki_match.lookup("スルリ", rank_of, "ja") == "するり"
    assert anki_match.lookup("ぴかぴか", rank_of, "ja") == "ぴかぴか"
    assert rank_of["ぴかぴか"] == 1


def test_the_kana_fold_never_displaces_a_word_really_spelled_that_way(tmp_path):
    """Two rows whose spellings differ only in script: each card keeps the row that writes it its
    way. The fold only fills a gap."""
    path = _write_list(tmp_path / "list.csv", [("馬鹿", "バカ", ""), ("冒険", "冒険", ""),
                                               ("ばか", "ばか", "")])
    rank_of = anki_match.build_index(path, language="ja").rank_of

    assert anki_match.lookup("ばか", rank_of, "ja") == "ばか" and rank_of["ばか"] == 2
    assert anki_match.lookup("バカ", rank_of, "ja") == "バカ" and rank_of["バカ"] == 0


def test_the_kana_fold_is_japanese_only_and_leaves_kanji_words_alone(tmp_path):
    path = _write_list(tmp_path / "list.csv", [("するり", "するり", ""), ("見惚れる", "見惚れる", "")])

    assert anki_match.lookup("スルリ", anki_match.build_index(path).rank_of) == ""
    assert anki_match.lookup("スルリ", anki_match.build_index(path, language="zh").rank_of, "zh") == ""
    assert anki_match.fold_kana("見惚れる") == "見惚れる"
    assert anki_match.fold_kana("ヴァイオリン") == "ゔぁいおりん"
    assert anki_match.fold_kana("スーパー") == "すーぱー"


def test_the_real_golden_list_has_no_borrowed_one_character_key():
    """On the analyser's own output, with the Japanese rules on: every one-character key left is
    some row's own word."""
    with open(GOLDEN_LIST, encoding="utf-8-sig", newline="") as handle:
        lemmas = {anki_match.normalize_word(row.get("Word")) for row in csv.DictReader(handle)}
    rank_of = anki_match.build_index(GOLDEN_LIST, language="ja").rank_of

    assert all(key in lemmas for key in rank_of if len(key) == 1)
    assert rank_of["中野"] == rank_of["ナカノ"] == 16


def test_lookup_answers_nothing_rather_than_guessing():
    """Empty states: no word, no list."""
    assert anki_match.lookup("", {"冒険": 0}, "ja") == ""
    assert anki_match.lookup(None, {"冒険": 0}, "ja") == ""
    assert anki_match.lookup("冒険", {}, "ja") == ""
    assert anki_match.lookup("散歩", {"冒険": 0}, "ja") == ""


# --------------------------------------------------------------------------- #
# WP-B3 (spec §11.1): the library map, and the journey's own numbers per list row
# --------------------------------------------------------------------------- #
def _write_map(path, words):
    """`results/library_frequency.json` as the analyser writes it since ENGINE_REVISION 11:
    [total, high, low, goal, first_file, score, spelling] per `lemma|reading`."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"settings": {"min_count": 2}, "words": words}, handle, ensure_ascii=False)
    return str(path)


def test_the_library_map_is_keyed_by_the_word_and_by_the_contents_spelling(tmp_path):
    """引き摺る is the lemma; anki_miner writes 引きずる, the spelling the content uses. Both reach
    the word's first file, score and total — the journey's sort key."""
    path = _write_map(tmp_path / "library_frequency.json", {
        "引き摺る|ヒキズル": [1, 1, 0, 0, 3, 10, "引きずる"],
        "冒険|ボウケン": [9, 6, 2, 1, 1, 72, "冒険"]})
    library = anki_match.load_library(path, "ja")

    assert library["引きずる"] == library["引き摺る"] == (3, 10, 1)
    assert anki_match.lookup("引きずる", library, "ja") == "引きずる"
    assert library["冒険"] == (1, 72, 9)


def test_the_library_map_follows_the_japanese_key_rules(tmp_path):
    """The same rules as the list: the surname タニ's one-kanji spelling 谷 is not a key, and a
    katakana card finds a hiragana word."""
    path = _write_map(tmp_path / "library_frequency.json", {
        "タニ|タニ": [2, 2, 0, 0, 5, 20, "谷"],
        "するり|スルリ": [1, 0, 1, 0, 4, 5, "するり"]})
    library = anki_match.load_library(path, "ja")

    assert "谷" not in library and library["タニ"] == (5, 20, 2)
    assert anki_match.lookup("スルリ", library, "ja") == "するり"


def test_a_spelling_two_readings_share_keeps_the_sense_the_library_leans_on(tmp_path):
    """上手 read じょうず and 上手 read かみて are two words to the analyser; a card that says 上手
    is placed by the one the library scores higher."""
    path = _write_map(tmp_path / "library_frequency.json", {
        "上手|ジョウズ": [4, 3, 1, 0, 2, 35, "上手"],
        "上手|カミテ": [1, 0, 0, 1, 9, 2, "上手"]})

    assert anki_match.load_library(path, "ja")["上手"] == (2, 35, 4)


def test_a_map_the_journey_cannot_be_read_from_places_nothing(tmp_path):
    """Empty states: a map written before revision 11 (its entries stop at the four counts), no map
    at all, and a damaged one — {} each time, and the caller says why."""
    old = _write_map(tmp_path / "old.json", {"冒険|ボウケン": [9, 6, 2, 1]})
    damaged = tmp_path / "damaged.json"
    damaged.write_text("{\"words\": ", encoding="utf-8")

    assert anki_match.load_library(old, "ja") == {}
    assert anki_match.load_library(str(tmp_path / "missing.json"), "ja") == {}
    assert anki_match.load_library(str(damaged), "ja") == {}


def test_the_lists_cut_off_is_read_from_the_map_and_nothing_else_passes_for_it(tmp_path):
    """Junban's "List first" holds a phrase to the list's own bar — the occurrences a word needs to
    make the list (the run's `min_count`; 10.97 on the reference library, a density-band floor). No
    map, a damaged one, one without the number, or `true` where the number belongs: None, and the
    caller says so rather than inventing a bar."""
    band = tmp_path / "band.json"
    band.write_text(json.dumps({"settings": {"min_count": 10.97}, "words": {}}), encoding="utf-8")
    without = tmp_path / "without.json"
    without.write_text(json.dumps({"settings": {}, "words": {}}), encoding="utf-8")
    boolean = tmp_path / "boolean.json"
    boolean.write_text(json.dumps({"settings": {"min_count": True}}), encoding="utf-8")
    damaged = tmp_path / "damaged.json"
    damaged.write_text("{\"settings\": ", encoding="utf-8")

    assert anki_match.library_floor(_write_map(tmp_path / "map.json", {})) == 2
    assert anki_match.library_floor(str(band)) == 10.97
    for path in (without, boolean, damaged, tmp_path / "missing.json"):
        assert anki_match.library_floor(str(path)) is None, path.name


def test_each_list_row_carries_the_journeys_numbers(tmp_path):
    """The progressive list's `Sequence`, `Score` and `Occurrences (Global)` — what a library word
    is placed among. The priority list has no `Sequence`: 0 there."""
    progressive = tmp_path / "progressive.csv"
    with open(progressive, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Sequence", "Word", "Orth", "Score", "Occurrences (Global)"])
        writer.writerows([(1, "冒険", "冒険", 72, 9), (4, "見惚れる", "見惚れる", 15, 3)])
    priority = tmp_path / "priority.csv"
    with open(priority, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Word", "Orth", "Score", "Occurrences"])
        writer.writerows([("冒険", "冒険", 72, 9)])

    assert anki_match.build_index(str(progressive), language="ja").journey_of == {
        "冒険": (1, 72, 9), "見惚れる": (4, 15, 3)}
    assert anki_match.build_index(str(priority), language="ja").journey_of == {"冒険": (0, 72, 9)}


# --------------------------------------------------------------------------- #
# L9 (spec §11.1 item 2): a phrase card placed where the library meets that run of words
# --------------------------------------------------------------------------- #
def _tokenizer():
    from app import analyzer
    analyzer.SANITIZE_JA = True
    return analyzer.JapaneseTokenizer()


def test_a_phrase_is_the_run_of_words_it_is_made_of_and_a_word_is_not_a_phrase():
    """気がつく is 気 + が + つく to the tokenizer anki_miner and Surasura share; 冒険 is one word and
    goes through the ordinary keys instead."""
    phrases = anki_match.phrase_lemmas(["気がつく", "冒険", "騎士団", ""], _tokenizer().tokenize)

    assert set(phrases) == {"気がつく", "騎士団"}
    assert len(phrases["気がつく"]) >= 2 and all(isinstance(lemma, str) for lemma in phrases["気がつく"])


def test_one_pass_finds_each_phrase_with_its_first_file_score_and_count():
    """The journey's key for a phrase: the file it is first met in (1-based, like `Sequence`), the
    file weights added up per occurrence (NOW 10, Soon 5), and how often it occurs."""
    tok = _tokenizer()
    files = {"第01話": ["雨の中を歩いた。"],
             "第02話": ["やっと気がついた。", "彼はまた気がついたようだ。"],
             "第03話": ["ふと気がつくと朝だった。"]}
    cache = {name: [(text, [list(t) for t in tokens])
                    for text, tokens in tok.tokenize_sentences("\n".join(lines))]
             for name, lines in files.items()}
    phrases = anki_match.phrase_lemmas(["気がつく", "騎士団"], tok.tokenize)

    found = anki_match.find_phrases(phrases, [("第01話", 10), ("第02話", 10), ("第03話", 5)],
                                    cache.__getitem__)

    assert found == {"気がつく": (2, 25, 3)}, "騎士団 is never met, so it is simply absent"


def _library_with_store(tmp_path, lines):
    """A sandboxed library of one NOW file, its token store filled, and a library map beside it."""
    import os as _os
    from app import token_index
    root = _os.environ["SURASURA_TEST_ROOT"]
    now = _os.path.join(root, "data", "ja", "HighPriority")
    _os.makedirs(now, exist_ok=True)
    path = _os.path.join(now, "第01話.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    token_index.reconcile_language("ja", [path])
    library_map = _write_map(tmp_path / "library_frequency.json", {"冒険|ボウケン": [1, 1, 0, 0, 1, 10, "冒険"]})
    return library_map, str(tmp_path / "phrase_places.json")


def test_phrase_places_are_read_once_per_library_map_and_then_cached(tmp_path, monkeypatch):
    """The pass is the expensive part (3.6 s on the real library), so it runs once per Generate —
    the map's fingerprint is the key — and only for phrases it has not seen. A new map reads again."""
    library_map, cache = _library_with_store(tmp_path, ["恩を売るつもりはない。", "冒険は続く。"])

    first = anki_match.phrase_places(["恩を売る", "騎士団"], "ja", cache, library_map)
    assert set(first) == {"恩を売る"} and first["恩を売る"][0] == 1

    def no_pass(*args, **kwargs):
        raise AssertionError("the library was read again for phrases it already checked")

    # A scoped patch: `monkeypatch.undo()` would also undo the sandbox's SURASURA_TEST_ROOT and send
    # the next read to the developer's real library (testing.md §5.1).
    with monkeypatch.context() as patched:
        patched.setattr(anki_match, "find_phrases", no_pass)
        assert anki_match.phrase_places(["恩を売る", "騎士団"], "ja", cache, library_map) == first

    import os as _os
    _os.utime(library_map, (1, 1))                      # a Generate rewrote the map
    calls = []
    real_pass = anki_match.find_phrases
    with monkeypatch.context() as patched:
        patched.setattr(anki_match, "find_phrases", lambda *a, **k: calls.append(1) or real_pass(*a, **k))
        assert anki_match.phrase_places(["恩を売る"], "ja", cache, library_map) == first
    assert calls == [1], "a new map means a new pass"


def test_phrases_are_japanese_only_and_need_a_library_map(tmp_path):
    """Chinese has no sentence of glued tokens to undo; with no map there is no journey to place by."""
    library_map, cache = _library_with_store(tmp_path, ["恩を売るつもりはない。"])

    assert anki_match.phrase_places(["恩を売る"], "zh", cache, library_map) == {}
    assert anki_match.phrase_places(["恩を売る"], "ja", cache, str(tmp_path / "none.json")) == {}


# --------------------------------------------------------------------------- #
# §5.4: the card's own sentence — how many OTHER words in it are still unknown
# --------------------------------------------------------------------------- #
def _unknown_unless(known):
    """The caller's verdict, as Junban gives it: a word with a target-language lemma of two or
    more characters that the learner does not know."""
    from app import analyzer

    def unknown(token):
        lemma = token[0]
        return (analyzer.has_target_language(lemma, "ja") and len(lemma) > 1
                and lemma not in known)
    return unknown


def test_the_bold_span_marks_the_word_as_the_card_conjugated_it():
    """anki_miner bolds the word as it was said — 多すぎます for the card 多すぎる — so the span is
    found even though the card's own spelling is not in the sentence."""
    text, start, end = anki_match.sentence_span("しかし 出場メンバーが <b>多すぎます</b>ね…。", "多すぎる")
    assert text[start:end] == "多すぎます"


def test_without_bold_the_words_first_occurrence_is_the_span_and_absent_is_none():
    text, start, end = anki_match.sentence_span("こいつは最低の評論家だよ。", "評論家")
    assert text[start:end] == "評論家"
    assert anki_match.sentence_span("こいつは最低の評論家だよ。", "冒険") is None
    assert anki_match.sentence_span("", "冒険") is None
    assert anki_match.sentence_span(None, "冒険") is None


def test_a_sentence_whose_other_words_are_known_makes_the_card_i_plus_one():
    """Every other word of 彼は毎日冒険に出かける known: the one new thing is 冒険 — i+1 (0). Known
    words are lemmas, as `load_known_words` files them: 出かける is 出掛ける to UniDic."""
    tokenize = _tokenizer().tokenize
    known = {"毎日", "出掛ける"}
    assert anki_match.unknowns_beside("冒険", "彼は毎日冒険に出かける。", tokenize,
                                      _unknown_unless(known)) == 0


def test_each_other_unknown_word_counts_and_the_cards_own_word_never_does():
    """新しい and 買う are new, 行く is known: two unknowns beside 眼鏡. A furigana-bracketed field
    reads the same."""
    tokenize = _tokenizer().tokenize
    unknown = _unknown_unless({"行く"})
    assert anki_match.unknowns_beside("眼鏡", "新しい<b>眼鏡</b>を買いに行った。", tokenize, unknown) == 2
    assert anki_match.unknowns_beside("眼鏡", "新[あたら]しい眼鏡[めがね]を買[か]いに行[い]った。",
                                      tokenize, unknown) == 2
    assert anki_match.unknowns_beside("眼鏡", "", tokenize, unknown) is None


# --------------------------------------------------------------------------- #
# Check matches (Junban_Backlog_Spec §16): the same word spelled another way — a SUGGESTION only.
# The words are the real backlog's (§12): cards the exact keys cannot place.
# --------------------------------------------------------------------------- #
_LIST = {"見惚れる": 957, "成り代わる": 2209, "引き延ばす": 3001, "過熱": 1343, "同行": 1344, "きゅっ": 2210}


def test_a_spelling_on_the_card_reaches_the_list_word_through_its_own_sentence():
    """anki_miner writes the dictionary form in the text's spelling (見とれる); the list keys UniDic's
    lemma (見惚れる). Read in its sentence, the card's word IS the token whose lemma is on the list."""
    tokenize = _tokenizer().tokenize
    seen = anki_match.suggest("見とれる", "思わず<b>見とれて</b>しまった。", tokenize, _LIST, "ja")
    assert seen == anki_match.Suggestion("見惚れる", "L6", "same word, other spelling", "みとれる")
    assert anki_match.suggest("なり代わる", "あいつに<b>なり代わって</b>やる。", tokenize, _LIST, "ja").key == "成り代わる"
    assert anki_match.suggest("引き伸ばす", "写真を引き伸ばす", tokenize, _LIST, "ja").key == "引き延ばす"


def test_without_a_sentence_only_a_word_with_kanji_is_read_on_its_own():
    """Alone, a kana word is read wrong too often — まく is 膜 to the tokenizer, not 撒く."""
    tokenize = _tokenizer().tokenize
    assert anki_match.suggest("見とれる", "", tokenize, _LIST, "ja").key == "見惚れる"
    assert anki_match.suggest("まく", "", tokenize, {"膜": 0}, "ja") is None


def test_a_noun_with_suru_and_a_sound_word_with_to_suggest_the_word_on_the_list():
    tokenize = _tokenizer().tokenize
    assert anki_match.suggest("同行する", "私も<b>同行する</b>よ", tokenize, _LIST, "ja") == \
        anki_match.Suggestion("同行", "L7", "+ する", "どうこう")
    assert anki_match.suggest("過熱する", "議論が<b>過熱し</b>ている。", tokenize, _LIST, "ja").key == "過熱"
    assert anki_match.suggest("きゅっと", "手を<b>きゅっと</b>握った。", tokenize, _LIST, "ja") == \
        anki_match.Suggestion("きゅっ", "L7", "+ と", "きゅっ")


def test_the_rules_measured_wrong_never_suggest_anything():
    """§4.4: a compound's part (伊勢海老 is not 伊勢 — dropped with L8, §16.1), a shared reading
    (布陣 is not 婦人), containment either way (ピーマン is not ピー, 夢見る is not 見る)."""
    tokenize = _tokenizer().tokenize
    for word, sentence, listed in (("伊勢海老", "伊勢海老のグリルを食べた。", {"伊勢": 0, "イセ": 0}),
                                   ("布陣", "布陣を敷く", {"婦人": 0}),
                                   ("ピーマン", "ピーマンは苦手だ。", {"ピー": 0}),
                                   ("夢見る", "夢見る少女", {"見る": 0})):
        assert anki_match.suggest(word, sentence, tokenize, listed, "ja") is None, word


def test_nothing_is_suggested_for_a_listed_word_for_chinese_or_without_a_tokenizer():
    tokenize = _tokenizer().tokenize
    assert anki_match.suggest("見惚れる", "思わず<b>見惚れて</b>しまった。", tokenize, _LIST, "ja") is None
    # Reached exactly through the kana fold (L4) — already placed, so never a question.
    assert anki_match.suggest("スルリ", "スルリと抜けた", tokenize, {"するり": 5}, "ja") is None
    assert anki_match.suggest("學習", "我們一起學習", tokenize, {"学习": 0}, "zh") is None
    assert anki_match.suggest("見とれる", "思わず見とれてしまった。", None, _LIST, "ja") is None
    assert anki_match.suggest("見とれる", "思わず見とれてしまった。", tokenize, {}, "ja") is None


def test_the_excerpt_marks_the_word_and_stays_one_short_line():
    assert anki_match.sentence_excerpt("思わず<b>見とれて</b>しまった。", "見とれる") == "思わず【見とれて】しまった。"
    long = "彼女は窓の外の景色にずっと" + "<b>見とれて</b>" + "いたので、先生に呼ばれても全く気がつかなかったらしい。"
    line = anki_match.sentence_excerpt(long, "見とれる", width=24)
    assert "【見とれて】" in line and len(line) <= 24 and line.startswith("…") and line.endswith("…")
    assert anki_match.sentence_excerpt("", "見とれる") == ""


def test_a_word_conjugated_in_a_sentence_without_bold_is_still_found_and_marked():
    """The real なり代わる card: no <b>, and the sentence says なり代わろう — the token that IS the
    card's word is found anywhere in its sentence, and marked as the sentence wrote it."""
    tokenize = _tokenizer().tokenize
    sentence = "こんな腕で この俺に なり代わろうとは"
    assert anki_match.suggest("なり代わる", sentence, tokenize, _LIST, "ja").key == "成り代わる"
    assert anki_match.sentence_excerpt(sentence, "なり代わる", tokenize=tokenize) ==         "こんな腕で この俺に 【なり代わろう】とは"

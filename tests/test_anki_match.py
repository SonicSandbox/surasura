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
    """The analyser's own 182-row output (BOM, real columns): a katakana lemma the user would never
    type (ナカノ) and the spelling their content uses (中野) reach the same rank. (Rank 20 once words
    kept their prefixes and suffixes: 高校生, 裁判長, おばあさん … joined the list above it —
    Patterns_Quality_Spec A; 19 since the parsing fixes read the sample's full-width １人 as 1 + 人, so
    一人 fell below it; 20 again since names stay whole — フータロー, cut in pieces before, counts all 6 of its
    uses and joined the list's head; 19 since a word stretched with a long mark is read as itself — いー keeps 2
    of its 3 uses and fell below it.)"""
    index = anki_match.build_index(GOLDEN_LIST)

    assert index.rank_of["中野"] == index.rank_of["ナカノ"] == 19
    assert index.rank_of["うう"] == 0
    assert index.marks_of, "markers are built for every row"


def test_a_mined_lapis_note_resolves_to_its_word_without_the_furigana():
    """Field 0 of anki_miner's note type, as it arrives: the reading in brackets, the sentence next
    to it. The bracket goes; nothing else changes."""
    note = _note("Lapis", [("Expression", "引[ひ]きずる"),
                           ("Sentence", "彼は足を引きずって歩いていた。")])
    assert anki_match.target_word(note, {}) == "引きずる"


# --------------------------------------------------------------------------- #
# A Japanese card's field holds ONE word — whatever was typed around it
# --------------------------------------------------------------------------- #
def test_a_japanese_card_field_is_read_as_the_one_word_it_holds():
    """Fields typed or edited by hand: the quotes or stop the word was typed in, a second line (Anki
    writes each line as a <br> or a <div>), a reading or an optional する in brackets, a second word after
    a list separator. None of it is the word — JMdict's headword, anki_miner's one note per word."""
    for raw, word in (("「撒く」", "撒く"), ("撒く。", "撒く"), ("撒く<br>まく", "撒く"),
                      ("撒く<div>まく</div>", "撒く"), ("<div>撒く</div><div>まく</div>", "撒く"),
                      ("仰ぐ（あおぐ）", "仰ぐ"), ("勉強(する)", "勉強"), ("上層部、首脳部", "上層部"),
                      ("撒く・巻く", "撒く"), ("撒く／巻く", "撒く"), ("撒く 巻く", "撒く"),
                      ("引[ひ]きずる", "引きずる"), ("冒険", "冒険")):
        assert anki_match.card_word(raw, "ja") == word, raw


def test_a_foreign_name_keeps_its_middle_dot_and_an_empty_field_holds_no_word():
    """Between katakana, ・ parts the pieces of ONE name (the 中黒 convention): ジョン・スミス is not ジョン. A
    field holding only a note in brackets keeps what it wrote; an image, an empty field or none holds no
    word at all — "" is an ordinary answer (`target_word`)."""
    assert anki_match.card_word("ジョン・スミス", "ja") == "ジョン・スミス"
    assert anki_match.card_word("（あおぐ）", "ja") == "あおぐ"
    for raw in ("", None, '<img src="paste-8f3a.jpg">', "<br>", "「」"):
        assert anki_match.card_word(raw, "ja") == "", raw


def test_a_half_width_field_is_read_as_the_word_in_full_width():
    """Half-width katakana and full-width digits are the same text in another form (Unicode NFKC), and the
    list's keys carry the form the tagger reads: ﾊﾞｼｯと is バシッと, ｼﾞｮﾝ･ｽﾐｽ is one name, ２年生 is 2年生."""
    for raw, word in (("ﾊﾞｼｯと", "バシッと"), ("ｼﾞｮﾝ･ｽﾐｽ", "ジョン・スミス"), ("｢ｶﾞｯｺｳ｣", "ガッコウ"),
                      ("２年生", "2年生"), ("仰ぐ（あおぐ）", "仰ぐ")):
        assert anki_match.card_word(raw, "ja") == word, raw
    tokenize = _tokenizer().tokenize
    word = anki_match.card_word("ﾊﾞｼｯと", "ja")
    assert anki_match.card_key(word, {"バシッ": 0, "冒険": 1}, "ja", None, tokenize) == ("バシッ", "L7")
    assert anki_match.card_word("ｶﾞｯｺｳ", "zh") == anki_match.normalize_word("ｶﾞｯｺｳ"), "Chinese as before"


def test_a_chinese_field_and_a_field_of_no_language_are_read_as_before():
    """What of a Chinese field is its word is an open question (学习 (xuéxí),
    学习 / 學習) — untouched; and with no language, a card is read exactly as `normalize_word` reads it."""
    for raw in ("学习 (xuéxí)", "学习 / 學習", "「学习」", "学习<br>xuéxí"):
        assert anki_match.card_word(raw, "zh") == anki_match.normalize_word(raw), raw
    assert anki_match.card_word("「撒く」") == "「撒く」"
    assert anki_match.card_word("撒く<br>まく") == anki_match.normalize_word("撒く<br>まく") == "撒くまく"


def test_target_word_reads_the_field_in_the_notes_language():
    """Junban's reorder passes the list's language; a caller that passes none reads a card as before."""
    note = _note("Lapis", [("Expression", "「撒く」<br>まく"), ("Sentence", "庭に水を撒く。")])
    assert anki_match.target_word(note, {}, "ja") == "撒く"
    assert anki_match.target_word(note, {}) == "「撒く」まく"


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
    assert rank_of["中野"] == rank_of["ナカノ"] == 19


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
    goes through the ordinary keys instead — and so is 騎士団, now that words keep their suffixes
    (Patterns_Quality_Spec.md Part A: 騎士 + 団 was a "phrase" before)."""
    phrases = anki_match.phrase_lemmas(["気がつく", "冒険", "騎士団", ""], _tokenizer().tokenize)

    assert set(phrases) == {"気がつく"}
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


def test_the_cards_own_word_said_again_is_never_an_unknown_beside_it():
    """The span is the <b>, else the first place the card's word is
    WRITTEN — and the same word said again is still the card's word, as the analyzer never counts its
    target's key. 撒け、撒け、撒くんだ！ had two unknowns beside 撒く, and an i+1 card dropped to "multi".
    Another new word still counts: 企む beside 撒く."""
    tokenize = _tokenizer().tokenize
    unknown = _unknown_unless(set())
    assert anki_match.unknowns_beside("撒く", "撒け、撒け、撒くんだ！", tokenize, unknown) == 0
    assert anki_match.unknowns_beside("撒く", "<b>撒い</b>た餌を撒いた。", tokenize, unknown) == 0
    assert anki_match.unknowns_beside("企む", "企む奴が企む。", tokenize, unknown) == 0
    assert anki_match.unknowns_beside("撒く", "企む奴が餌を<b>撒い</b>た。", tokenize, unknown) == 1


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


# --------------------------------------------------------------------------- #
# Placed with no question (Anki_Match_Consistency_Scope.md, 2026-09-26): an exact key, the user's "yes",
# or ONE word with an ending written onto it — `card_key`, shared by Junban and the report's label.
# --------------------------------------------------------------------------- #
def test_a_word_with_its_suru_or_to_is_that_word_with_no_question():
    """The user's 努力する and 仲良くする, a tester's バシッと and ひょいと (カラフル, mined by AnkiMiner): UniDic
    reads each as the word + する or と, and the list has the word. The user, 2026-09-26: "I'd prefer
    them to be one word" — so it is placed as the word, not offered as a question (L7)."""
    tokenize = _tokenizer().tokenize
    listed = {"努力": 0, "仲良く": 1, "バシッ": 2, "ひょい": 3, "同行": 4}
    for word, key in (("努力する", "努力"), ("仲良くする", "仲良く"), ("バシッと", "バシッ"),
                      ("ひょいと", "ひょい"), ("同行する", "同行")):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, "L7"), word
    assert anki_match.one_word(tokenize("努力する"))[0] == "努力"
    assert anki_match.one_word(tokenize("冒険"))[0] == "冒険"


def test_a_verb_of_its_own_a_phrase_or_a_bare_kana_word_is_never_read_as_a_list_word():
    """対する is ONE verb to UniDic (the 対 on the list is another word); 楽しみにする and クビにする carry
    two endings — their meaning moves, so they stay phrases; ずっと is a と-adverb of its own; まく alone
    is read as 膜 — a bare kana word is never read alone (Junban_Backlog_Spec §8 gotcha 2)."""
    tokenize = _tokenizer().tokenize
    listed = {"対": 0, "楽しみ": 1, "クビ": 2, "ずっ": 3, "膜": 4}
    for word in ("対する", "楽しみにする", "クビにする", "ずっと", "まく"):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == ("", ""), word
    assert anki_match.one_word(tokenize("楽しみにする")) is None
    assert anki_match.one_word(tokenize("気がつく")) is None


def test_the_users_answers_come_before_the_ending_and_a_no_is_never_overruled():
    """あおぐ is a bare kana word: only the user's "yes" (a tester's, カラフル) makes it 仰ぐ. A "no" to
    同行する being 同行 keeps it off the list, and an exact key needs no answer at all."""
    tokenize = _tokenizer().tokenize
    listed = {"仰ぐ": 0, "同行": 1, "冒険": 2}
    answers = {"あおぐ": {"target": "仰ぐ", "answer": "yes"}, "同行する": {"target": "同行", "answer": "no"}}
    assert anki_match.card_key("あおぐ", listed, "ja", answers, tokenize) == ("仰ぐ", "yes")
    assert anki_match.card_key("あおぐ", listed, "ja", None, tokenize) == ("", "")
    assert anki_match.card_key("同行する", listed, "ja", answers, tokenize) == ("", "")
    assert anki_match.card_key("冒険", listed, "ja", answers, tokenize) == ("冒険", "exact")


def test_chinese_and_a_missing_tokenizer_keep_exact_keys_and_answers_only():
    tokenize = _tokenizer().tokenize
    assert anki_match.card_key("学习", {"学习": 0}, "zh", None, tokenize) == ("学习", "exact")
    assert anki_match.card_key("努力する", {"努力": 0}, "ja", None, None) == ("", "")
    assert anki_match.card_key("努力する", {"努力": 0}, "zh", None, tokenize) == ("", "")


def test_a_word_in_its_inflected_form_is_its_dictionary_form():
    """The past, the polite form, the negative, the ちゃう contraction — a word's paradigm, which no
    dictionary lists as words of their own. A card 取り消した is the word 取り消す (JMdict's headword)."""
    tokenize = _tokenizer().tokenize
    listed = {"取り消す": 0, "行く": 1, "食べる": 2, "美しい": 3, "読む": 4}
    for word, key in (("取り消した", "取り消す"), ("行きません", "行く"), ("食べちゃった", "食べる"),
                      ("美しかった", "美しい"), ("読んだ", "読む"), ("食べなかった", "食べる")):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, "L7"), word
        assert anki_match.one_word(tokenize(word))[0] == key, word


def test_a_noun_with_suru_in_any_of_its_forms_is_that_noun():
    """する conjugates and the noun before it does not: 勉強した, 勉強しません, 勉強してる are 勉強する in the past,
    the polite negative, the progressive — ONE word + one ending, placed as 勉強 with no question, as 努力する
    is. Two endings (楽しみにした, クビにした: に then する) stay phrases — their meaning moves; voice is no
    inflection (勉強させる), and できる is a verb of its own (勉強できる)."""
    tokenize = _tokenizer().tokenize
    listed = {"勉強": 0, "キャンセル": 1, "努力": 2, "楽しみ": 3, "クビ": 4}
    for word, key in (("勉強した", "勉強"), ("勉強しました", "勉強"), ("勉強しない", "勉強"), ("勉強してる", "勉強"),
                      ("勉強しなかった", "勉強"), ("キャンセルした", "キャンセル"), ("努力しません", "努力")):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, "L7"), word
        assert anki_match.one_word(tokenize(word))[0] == key, word
    for word in ("楽しみにした", "クビにした", "勉強させる", "勉強できる", "勉強していた"):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == ("", ""), word
        assert anki_match.one_word(tokenize(word)) is None, word


def test_a_word_with_the_copula_in_any_of_its_forms_is_that_word():
    """The user, 2026-09-29: the copula's forms are placed at the word, as する's are. 静か and 元気 (な-adjectives) and
    学生 (a noun) don't conjugate — the copula after them does: だった, でした, じゃなかった, ではない, であった,
    ではありません. A particle before the copula keeps a phrase (気のせいだった), and UniDic reads 只者ではない's で as a
    particle — its meaning moves, it stays one; も adds a meaning of its own (静かでもない)."""
    tokenize = _tokenizer().tokenize
    listed = {"静か": 0, "元気": 1, "学生": 2, "気": 3, "只者": 4}
    for word, key in (("静かだった", "静か"), ("静かでした", "静か"), ("元気じゃなかった", "元気"), ("静かではない", "静か"),
                      ("元気でした", "元気"), ("学生だった", "学生"), ("静かであった", "静か"),
                      ("静かではありません", "静か")):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, "L7"), word
        assert anki_match.one_word(tokenize(word))[0] == key, word
    for word in ("気のせいだった", "只者ではない", "静かでもない"):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == ("", ""), word
        assert anki_match.one_word(tokenize(word)) is None, word


def test_a_kanji_card_read_alone_as_one_word_is_placed_as_the_label_marks_it():
    """The user, 2026-09-29: Junban and the report's "In Anki" label give one answer. A card with a kanji that
    reads alone as ONE word is that word — 逃げだす is UniDic's 逃げ出す, 引き伸ばす its 引き延ばす — placed with
    no question. A kana card read alone is the tagger's guess (まく -> 膜) and stays a question; a one-character
    card is a stem as often as a word (見 is 見る's) and never another row's; the user's "no" still wins."""
    tokenize = _tokenizer().tokenize
    listed = {"逃げ出す": 0, "引き延ばす": 1, "見惚れる": 2, "見る": 3, "膜": 4}
    for word, key in (("逃げだす", "逃げ出す"), ("引き伸ばす", "引き延ばす"), ("見とれる", "見惚れる")):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, "L6"), word
    for word in ("みとれる", "まく", "見"):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == ("", ""), word
    no = {"逃げだす": {"target": "逃げ出す", "answer": "no"}}
    assert anki_match.card_key("逃げだす", listed, "ja", no, tokenize) == ("", "")
    assert anki_match.whole_word_alone("逃げだす", tokenize("逃げだす"))
    assert not anki_match.whole_word_alone("見", tokenize("見"))


def test_voice_derivation_a_second_verb_or_a_kana_word_is_no_inflection():
    """Voice and derivation make words JMdict lists (待たせる, 優しさ — its さ an open question); ている and 始める
    are verbs of their own; かった is 買った, 勝った or 刈った — a kana card's dictionary form is the
    tagger's guess, so it is never read for its inflection. And the conjugated stem is the verb's: a
    card 考えた never lands on the noun 考え."""
    tokenize = _tokenizer().tokenize
    listed = {"待つ": 0, "優しい": 1, "食べる": 2, "買う": 3, "勝つ": 4, "駆る": 5, "考え": 6}
    for word in ("待たせる", "優しさ", "食べている", "食べ始める", "かった", "考えた"):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == ("", ""), word
    for word in ("待たせる", "優しさ", "食べている", "食べ始める", "かった"):
        assert anki_match.one_word(tokenize(word)) is None, word


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


# --------------------------------------------------------------------------- #
# Patterns_Quality_Spec §7: a word written with its tail — する, the copula's な / に, the particle に
# --------------------------------------------------------------------------- #
def test_a_tail_written_onto_a_word_is_known_by_its_lemma():
    """同行する, 斬新な and 一気に read alone are the word + する (為る), the copula's な (だ) and the
    particle に — the list has 同行, 斬新, 一気. Told apart by the lemma alone: the analyzer's tokens
    carry no part of speech."""
    tokenize = _tokenizer().tokenize
    for word, lemmas in (("同行する", ["同行", "為る"]), ("斬新な", ["斬新", "だ"]), ("一気に", ["一気", "に"])):
        tokens = tokenize(word)
        assert [token[0] for token in tokens] == lemmas, word
        assert anki_match.is_attached_tail(tokens[1][0]), word


def test_a_second_word_or_another_ending_is_not_a_tail():
    """伊勢海老's 海老 is a word of its own, 疲れた's た the past, 利用できる's できる a verb, 恩を's を
    another particle: none of these is a tail written onto a word (疲れた is still one word — 疲れる, in
    its paradigm: `test_a_word_in_its_inflected_form_is_its_dictionary_form`). A surface is not a lemma
    (する's is 為る), and an empty lemma is nothing."""
    tokenize = _tokenizer().tokenize
    for word in ("伊勢海老", "疲れた", "利用できる", "恩を"):
        tokens = tokenize(word)
        assert len(tokens) == 2 and not anki_match.is_attached_tail(tokens[1][0]), word
    for lemma in ("する", "", None):
        assert not anki_match.is_attached_tail(lemma), lemma

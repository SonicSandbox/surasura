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

import pytest

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
    """The analyser's own 200-row output (BOM, real columns): a katakana lemma the user would never
    type (ナカノ) and the spelling their content uses (中野) reach the same rank. (Rank 20 once words
    kept their prefixes and suffixes: 高校生, 裁判長, おばあさん … joined the list above it —
    Patterns_Quality_Spec A; 19 since the parsing fixes read the sample's full-width １人 as 1 + 人, so
    一人 fell below it; 20 again since names stay whole — フータロー, cut in pieces before, counts all 6 of its
    uses and joined the list's head; 19 since a word stretched with a long mark is read as itself — いー keeps 2
    of its 3 uses and fell below it; 22 since words made of words are one word — 優先席, 家庭教師 and 社会貢献
    joined the list above it; 21 since a polite お word is read through its known word — おばあさん sits lower; 22
    since a story's own kanji words the library keeps using are one word — the sample's 三玖, a name, joined the list
    near its head; 24 since set phrases are rows of their own — 席を譲る and このまま joined the list above it; 25 since
    one-kanji dictionary words are list words where they stand on their own — 門 joined the list above it; 28 since the
    words the tagger cuts at their grammar are words of their own — それで, なんで and どこにも joined the list above it.)"""
    index = anki_match.build_index(GOLDEN_LIST)

    assert index.rank_of["中野"] == index.rank_of["ナカノ"] == 28
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
    assert anki_match.card_word("ｶﾞｯｺｳ", "zh") == "ガッコウ", "a Chinese field is read in NFKC too"


@pytest.mark.parametrize("raw", ["学习 (xuéxí)", "学习（xuéxí）", "学习 xuéxí", "学习 / 學習", "「学习」",
                                 "学习<br>xuéxí", "学习[xue2 xi2]", "<ruby>学<rt>xué</rt></ruby><ruby>习<rt>xí</rt></ruby>",
                                 '<span class="tone2">学</span><span class="tone2">习</span>'])
def test_a_chinese_field_is_read_as_its_one_word(raw):
    """The shapes Chinese decks write a word in — pinyin after it, in brackets or not, both scripts, a second line,
    corner brackets — are all the word 学习, read as a Japanese field is."""
    assert anki_match.card_word(raw, "zh") == "学习"


def test_a_chinese_name_is_never_parted_at_its_dot_and_no_language_reads_as_before():
    """Chinese writes ・ or · between the parts of one foreign name (the 间隔号): 约翰・列侬 and 哈利·波特 are one
    name each. With no language, a card is read exactly as `normalize_word` reads it."""
    assert anki_match.card_word("约翰・列侬", "zh") == "约翰・列侬"
    assert anki_match.card_word("哈利·波特 (Hālì Bōtè)", "zh") == "哈利·波特"
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
    some row's own word — the one-kanji rows (門, 旬, 肝) included, each its own word."""
    with open(GOLDEN_LIST, encoding="utf-8-sig", newline="") as handle:
        lemmas = {anki_match.normalize_word(row.get("Word")) for row in csv.DictReader(handle)}
    rank_of = anki_match.build_index(GOLDEN_LIST, language="ja").rank_of

    assert all(key in lemmas for key in rank_of if len(key) == 1)
    assert {"門", "旬", "肝"} <= {key for key in rank_of if len(key) == 1}
    assert rank_of["中野"] == rank_of["ナカノ"] == 28


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
    # A sound word ending in っ + と is ONE token, the sound word shown with と: a list built since holds きゅっと
    # among its row's spellings, so the card is placed with no question. On a list without that spelling, the
    # card read in its sentence is still the same word — and `card_key` places it there first, with no question
    # (the sound word + と read apart: `test_a_sound_word_said_with_to_is_the_sound_word_the_list_writes_without`).
    assert anki_match.suggest("きゅっと", "手を<b>きゅっと</b>握った。", tokenize, _LIST, "ja") == \
        anki_match.Suggestion("きゅっ", "L6", "same word, other spelling", "きゅっ")
    assert anki_match.card_key("きゅっと", dict(_LIST, きゅっと=2210), "ja", None, tokenize) == ("きゅっと", "exact")
    assert anki_match.card_key("きゅっと", _LIST, "ja", None, tokenize) == ("きゅっ", "L7")


# --------------------------------------------------------------------------- #
# Placed with no question (Anki_Match_Consistency_Scope.md, 2026-09-26): an exact key, the user's "yes",
# or ONE word with an ending written onto it — `card_key`, shared by Junban and the report's label.
# --------------------------------------------------------------------------- #
def test_a_word_with_its_suru_or_to_is_that_word_with_no_question():
    """The user's 努力する and 仲良くする, a tester's バシッと and ひょいと (カラフル, mined by AnkiMiner): UniDic
    reads each as the word + する or と, and the list has the word. The user, 2026-09-26: "I'd prefer
    them to be one word" — so it is placed as the word, not offered as a question (L7). A sound word ending
    in っ + と (バシッと) is one token itself, the sound word shown with と: a list built since holds that
    spelling among the row's (its Forms), and the card lands there by its own spelling."""
    tokenize = _tokenizer().tokenize
    listed = {"努力": 0, "仲良く": 1, "バシッ": 2, "バシッと": 2, "ひょい": 3, "同行": 4}
    for word, key in (("努力する", "努力"), ("仲良くする", "仲良く"), ("ひょいと", "ひょい"), ("同行する", "同行")):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, "L7"), word
    assert anki_match.card_key("バシッと", listed, "ja", None, tokenize) == ("バシッと", "exact")
    assert anki_match.one_word(tokenize("努力する"))[0] == "努力"
    assert anki_match.one_word(tokenize("冒険"))[0] == "冒険"


def test_a_sound_word_said_with_to_is_the_sound_word_the_list_writes_without():
    """A card mined as バシッと when the content only ever writes バシッ (「バシッ」と, バシッ！): the tokenizer reads
    バシッと as ONE token — the sound word's own lemma and reading, written with its と — so the list has no
    バシッと among its spellings. The card is still the sound word + the ending と and lands on バシッ with no
    question, as it did when the tokenizer cut the と off. The same for a sound word whose reading ends in ト
    (コトッと — コト), one with a long vowel (ぎゅーっと) and half-width kana (ﾊﾞｼｯと: its dictionary spelling
    is バシッ). ずっと, ちょっと and はっと are と-adverbs of their own — their reading holds the と — and never
    lose it; a "no" to the pair is never overruled."""
    tokenize = _tokenizer().tokenize
    listed = {"バシッ": 0, "コトッ": 1, "ぎゅーっ": 2, "ずっ": 3, "ちょっ": 4, "はっ": 5}
    for word, key in (("バシッと", "バシッ"), ("コトッと", "コトッ"), ("ぎゅーっと", "ぎゅーっ"), ("ﾊﾞｼｯと", "バシッ")):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, "L7"), word
    # the kana fold still applies to the letters the card is written in (L4): ばしっと reaches the katakana row
    assert anki_match.card_key("ばしっと", {"ばしっ": 0}, "ja", None, tokenize) == ("ばしっ", "L7")
    for word in ("ずっと", "ちょっと", "はっと"):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == ("", ""), word
        assert len(anki_match.ending_apart(tokenize(word))) == 1, word
    no = {"バシッと": {"target": "バシッ", "answer": "no"}}
    assert anki_match.card_key("バシッと", listed, "ja", no, tokenize) == ("", "")
    # read apart only when the sound word + と is the card's only token: ドキッとする stays ドキッと + する
    assert anki_match.ending_apart(tokenize("ドキッとする")) == list(tokenize("ドキッとする"))
    assert anki_match.ending_apart([]) == []


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


def test_a_missing_tokenizer_keeps_exact_keys_and_answers_only():
    assert anki_match.card_key("学习", {"学习": 0}, "zh", None, None) == ("学习", "exact")
    assert anki_match.card_key("认真地", {"认真": 0}, "zh", None, None) == ("", "")
    assert anki_match.card_key("努力する", {"努力": 0}, "ja", None, None) == ("", "")
    assert anki_match.card_key("努力する", {"努力": 0}, "zh", None, _tokenizer().tokenize) == ("", "")


def _chinese():
    from app import analyzer
    return analyzer.ChineseTokenizer().tokenize


@pytest.mark.parametrize("word, listed, key", [
    ("认真地", ["他", "认真", "地", "学习"], "认真"),      # 地 does に's job: the adverb's word
    ("漂亮的", ["漂亮", "的"], "漂亮"),                   # 的 does な's
    ("我的", ["我", "的"], "我"),
    ("开开心心", ["开心"], "开心"),                       # a doubled form is its word
])
def test_a_chinese_card_read_alone_as_one_word_lands_on_it(word, listed, key):
    rank_of = {name: rank for rank, name in enumerate(listed)}
    assert anki_match.card_key(word, rank_of, "zh", None, _chinese()) == (key, "L7")
    no = {word: {"answer": "no", "target": key}}
    assert anki_match.card_key(word, rank_of, "zh", no, _chinese()) == ("", ""), "the user's no wins"


def test_a_chinese_word_ending_in_de_or_di_is_its_own_word():
    """目的 'purpose' and 土地 'land' are one token each: never 目 or 土."""
    rank_of = {"目": 0, "的": 1, "土": 2, "地": 3}
    for word in ("目的", "土地"):
        assert anki_match.card_key(word, rank_of, "zh", None, _chinese()) == ("", ""), word
        assert anki_match.one_word(_chinese()(word), "zh")[0] == word


@pytest.mark.parametrize("word, key", [("吃了", "吃"), ("去过", "去"), ("看着", "看")])
def test_a_chinese_card_with_its_aspect_after_a_verb_is_that_verb(word, key):
    """了 / 过 / 着 after ONE verb are its paradigm, no word of their own (as 取り消した is 取り消す): placed on the verb,
    told by jieba's own tags (analyzer.chinese_verb, handed in). Without the test, nothing comes off."""
    from app import analyzer
    rank_of = {"吃": 0, "去": 1, "看": 2, "人": 3, "好": 4}
    assert anki_match.card_key(word, rank_of, "zh", None, _chinese(), verb=analyzer.chinese_verb) == (key, "L7")
    assert anki_match.card_key(word, rank_of, "zh", None, _chinese()) == ("", "")


def test_an_aspect_comes_off_a_verb_only_and_never_a_word_listed_whole():
    """人了 has no verb before its 了; 好了 an adjective; 为了 'in order to' and 睡着 'asleep' are CC-CEDICT words the
    tokenizer keeps whole."""
    from app import analyzer
    rank_of = {"人": 0, "好": 1, "为": 2, "睡": 3}
    for word in ("人了", "好了", "为了", "睡着"):
        assert anki_match.card_key(word, rank_of, "zh", None, _chinese(), verb=analyzer.chinese_verb) == ("", ""), word


def test_one_chinese_word_takes_one_ending_only():
    tokens = [("认真", "", "认真", "认真"), ("地", "", "地", "地")]
    assert anki_match.one_word(tokens, "zh") == tokens[0]
    assert anki_match.one_word(tokens + [("学习", "", "学习", "学习")], "zh") is None
    assert anki_match.one_word([("学习", "", "学习", "学习"), ("中文", "", "中文", "中文")], "zh") is None
    assert anki_match.one_word([], "zh") is None


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
    """Voice makes words JMdict lists (待たせる); ている and 始める are verbs of their own; かった is 買った, 勝った or
    刈った — a kana card's dictionary form is the tagger's guess, so it is never read for its inflection. And the
    conjugated stem is the verb's: a card 考えた never lands on the noun 考え. (優しさ left this test: its さ is the
    adjective's own grammar — see the tests of a card's own grammar below.)"""
    tokenize = _tokenizer().tokenize
    listed = {"待つ": 0, "優しい": 1, "食べる": 2, "買う": 3, "勝つ": 4, "駆る": 5, "考え": 6}
    for word in ("待たせる", "食べている", "食べ始める", "かった", "考えた"):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == ("", ""), word
    for word in ("待たせる", "食べている", "食べ始める", "かった"):
        assert anki_match.one_word(tokenize(word)) is None, word


# --------------------------------------------------------------------------- #
# A card with the word's own grammar on it — a polite お / ご, a plural, a さ / み — is its word
# --------------------------------------------------------------------------- #
def test_a_card_with_a_polite_prefix_is_its_word():
    """The list has never had a row for お部屋: the tokenizer reads 御 + 部屋 and counts 部屋. So a card mined as
    お部屋 is 部屋 for Junban and the mark too, with no question; ご案内する takes the prefix and the する off; the
    user's "no" to that very pair still wins."""
    tokenize = _tokenizer().tokenize
    listed = {"部屋": 0, "挨拶": 1, "案内": 2, "話す": 3}
    for word, key in (("お部屋", "部屋"), ("ご挨拶", "挨拶"), ("ご案内する", "案内"), ("お話しする", "話す")):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, "L7"), word
        assert anki_match.one_word(tokenize(word))[0] == ("話す" if word == "お話しする" else key), word
    no = {"お部屋": {"answer": "no", "target": "部屋"}}
    assert anki_match.card_key("お部屋", listed, "ja", no, tokenize) == ("", "")


def test_a_plural_card_is_its_word():
    """たち, ら and ども are never joined onto a word, so 俺たち is 俺 + 達 wherever the list counts; the card is 俺.
    A kana card is looked up by the letters it is written in (おれ), never the lemma the tagger guesses."""
    tokenize = _tokenizer().tokenize
    listed = {"俺": 0, "お前": 1, "私": 2, "彼": 3, "おれ": 4}
    for word, key in (("俺たち", "俺"), ("お前ら", "お前"), ("お前たち", "お前"), ("私ども", "私"), ("彼ら", "彼"),
                      ("おれたち", "おれ")):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, "L7"), word
    assert anki_match.card_key("おれたち", {"俺": 0}, "ja", None, tokenize) == ("", "")


def test_an_adjective_made_a_noun_is_its_adjective():
    """優しさ is 優しい + さ to the tokenizer (an adjective takes no suffix join), so the list counts 優しい; the card
    is 優しい too. The stem is looked up by its dictionary form, never its surface: a row holding 優し is not reached."""
    tokenize = _tokenizer().tokenize
    listed = {"優しい": 0, "暑い": 1, "静か": 2, "大切": 3, "新鮮": 4}
    for word, key in (("優しさ", "優しい"), ("暑さ", "暑い"), ("静かさ", "静か"), ("大切さ", "大切"), ("新鮮み", "新鮮"),
                      ("お優しさ", "優しい")):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, "L7"), word
    assert anki_match.card_key("優しさ", {"優し": 0}, "ja", None, tokenize) == ("", "")


def test_what_is_no_polite_or_plural_grammar_stays_as_it_is():
    """やさしさ in kana could be 優しさ or 易しさ — the tagger's guess — so it keeps its さ. Two words before さ
    (男らしさ) stay a phrase; 見方 and 先生方 are not taken apart (UniDic's 方 tells no plural from a way); a dictionary
    お / ご word (お守り, ご苦労) is one token and its own word; 御 read ミ is kept (御心 is not 心); two endings stay a
    phrase; a card that is only お or only たち is left alone."""
    tokenize = _tokenizer().tokenize
    listed = {"優しい": 0, "男": 1, "見る": 2, "先生": 3, "守り": 4, "苦労": 5, "心": 6, "待つ": 7, "楽しみ": 8,
              "お茶": 9, "質": 10}
    for word in ("やさしさ", "男らしさ", "先生方", "お守り", "ご苦労", "御心", "お待ちください", "楽しみにする",
                 "お", "たち", ""):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == ("", ""), word
    assert anki_match.card_key("お茶する", listed, "ja", None, tokenize) == ("お茶", "L7")
    assert anki_match.one_word(tokenize("見方")) is None
    assert anki_match.affixes_off([("御", "オ", "お", "お")]) == [("御", "オ", "お", "お")]
    assert anki_match.card_key("お部屋", {"部屋": 0}, "zh", None, tokenize) == ("", "")
    assert anki_match.card_key("お部屋", {"部屋": 0}, "ja", None, None) == ("", "")


def test_the_grammar_sets_are_the_tokens_the_tagger_gives():
    """Each (lemma, reading) in the sets is what the tagger yields in a sentence — the test that keeps them honest."""
    tokenize = _tokenizer().tokenize
    seen = {tuple(t[:2]) for sentence in ("私たちは彼らが来るのを待った。", "野郎どもが騒いでいる。",
                                          "お部屋にご案内します。", "その優しさを忘れない。", "赤みが差した頬の丸みが好きだ。")
            for t in tokenize(sentence)}
    assert anki_match.POLITE_PREFIXES <= seen
    assert anki_match.PLURALS <= seen
    assert anki_match.NOMINALIZERS <= seen | {tuple(t[:2]) for t in tokenize("新鮮みに欠ける。")}


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
    """同行する, 斬新な and 最後に read alone are the word + する (為る), the copula's な (だ) and the
    particle に — the list has 同行, 斬新, 最後. Told apart by the lemma alone: the analyzer's tokens
    carry no part of speech. (一気に, which JMdict lists as an adverb of its own, is one word now.)"""
    tokenize = _tokenizer().tokenize
    for word, lemmas in (("同行する", ["同行", "為る"]), ("斬新な", ["斬新", "だ"]), ("最後に", ["最後", "に"])):
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


# --------------------------------------------------------------------------- #
# A hiragana card that is a common word never takes a name's (or a loanword's) row by its letters
# --------------------------------------------------------------------------- #
def test_a_hiragana_card_of_a_common_word_is_that_word_not_a_name_spelled_the_same(tmp_path):
    """The user, 2026-09-30: a hiragana ひかり card is the word 光 'light'. A list can hold the name ヒカリ, read from
    ひかりさん — its own word the card's letters in katakana, its commonest spelling ひかり — and the card's letters
    reach that row exactly. Read alone, ひかり is 光, one word with a kanji: not the name. The card goes to 光's own
    row when the list has one, else to none (then its sentence places it). Likewise だいぶ (大分 'considerably') is
    not the loanword ダイブ 'dive'. A katakana ヒカリ card is written the way the name is and still reaches it."""
    tokenize = _tokenizer().tokenize
    index = anki_match.build_index(_write_list(tmp_path / "names.csv", [
        ["ヒカリ", "ひかり", "光"], ["ダイブ", "ダイブ", ""], ["パン", "パン", ""]]), language="ja")
    assert index.words == ["ヒカリ", "ダイブ", "パン"]
    rank_of, words = index.rank_of, index.words
    assert anki_match.card_key("ひかり", rank_of, "ja", None, tokenize, words) == ("", "")
    assert anki_match.card_key("だいぶ", rank_of, "ja", None, tokenize, words) == ("", "")
    assert anki_match.card_key("ヒカリ", rank_of, "ja", None, tokenize, words) == ("ヒカリ", "exact")
    assert anki_match.card_key("ぱん", rank_of, "ja", None, tokenize, words) == ("ぱん", "exact"), \
        "read alone it IS the katakana word: no kanji, no other word"
    with_light = anki_match.build_index(_write_list(tmp_path / "light.csv", [
        ["ヒカリ", "ひかり", ""], ["光", "光", ""]]), language="ja")
    assert anki_match.card_key("ひかり", with_light.rank_of, "ja", None, tokenize, with_light.words) == ("光", "L6")
    no = {"ひかり": {"target": "光", "answer": "no"}}
    assert anki_match.card_key("ひかり", with_light.rank_of, "ja", no, tokenize, with_light.words) == ("", "")
    yes = {"ひかり": {"target": "ヒカリ", "answer": "yes"}}
    assert anki_match.card_key("ひかり", rank_of, "ja", yes, tokenize, words) == ("ヒカリ", "yes"), \
        "the user's yes (a character called ひかり) places it"


def test_without_the_rows_own_words_a_card_keeps_its_letters(tmp_path):
    """An index built by hand holds no rows' words, and a caller that passes none keeps today's exact keys — never an
    error. A kana card whose row is a kanji word (まく in 撒く's Forms) keeps it: only a row spelled as the card's
    letters in katakana is another word's."""
    tokenize = _tokenizer().tokenize
    index = anki_match.build_index(_write_list(tmp_path / "list.csv", [
        ["ヒカリ", "ひかり", ""], ["撒く", "撒く", "まく"]]), language="ja")
    assert anki_match.card_key("ひかり", index.rank_of, "ja", None, tokenize) == ("ひかり", "exact")
    assert anki_match.Index({}, {}, {}, {}).words is None
    assert anki_match.card_key("まく", index.rank_of, "ja", None, tokenize, index.words) == ("まく", "exact")
    assert anki_match.not_the_name("ひかり", "ひかり", index.rank_of, index.words, None) is None, "no tokenizer"


def test_a_card_for_a_storys_own_kanji_term_meets_its_row():
    """A story's own kanji term the library keeps using as one (app/names.py) is a list row of its own, keyed as a word
    no dictionary has — the spelling, no reading. A card mined for it meets that row by its exact key, and a card that
    wrote it with the copula reads through the same tables (焔魄陣 is a made-up technique, cut 焔 + 魄 + 陣)."""
    from app import names
    names.use_library_tables({"k": {}, "j": {}, "w": {"焔魄陣": [1.0, "焔魄陣", "", "焔魄陣"]}, "stamp": "term"},
                             pin=True)
    tokenize = _tokenizer().tokenize
    listed = {"焔魄陣": 0, "炎": 1}
    assert anki_match.card_key("焔魄陣", listed, "ja", None, tokenize) == ("焔魄陣", "exact")
    assert anki_match.card_key("焔魄陣だった", listed, "ja", None, tokenize) == ("焔魄陣", "L7")
    names.use_library_tables({"k": {}, "j": {}, "w": {}, "stamp": "none"}, pin=True)
    assert anki_match.card_key("焔魄陣だった", listed, "ja", None, tokenize) == ("", ""), "no table: pieces"


def test_a_phrase_card_lands_on_its_phrase_row_by_its_words():
    """With set phrases on the list (Settings' "Idioms and set phrases on your list"), a phrase row's Word is its words'
    lemmas joined — so a card read alone as those words lands there however either is spelled: 興味をもつ on the row
    興味を持つ, 気がついた on 気が付く (via "phrase"). The user's "no" to that row wins; a card that is one word + an
    ending is still that word (努力する -> 努力); without the switch, a phrase card lands nowhere by its words."""
    tokenize = _tokenizer().tokenize
    listed = {"努力": 0, "気がつく": 1, "気が付く": 1, "興味を持つ": 2}
    assert anki_match.card_key("興味をもつ", listed, "ja", None, tokenize, phrases=True) == ("興味を持つ", "phrase")
    assert anki_match.card_key("気が付く", listed, "ja", None, tokenize, phrases=True) == ("気が付く", "exact")
    assert anki_match.card_key("興味をもつ", listed, "ja", None, tokenize) == ("", ""), "switch off"
    no = {"興味をもつ": {"target": "興味を持つ", "answer": "no"}}
    assert anki_match.card_key("興味をもつ", listed, "ja", no, tokenize, phrases=True) == ("", "")
    assert anki_match.card_key("努力する", listed, "ja", None, tokenize, phrases=True) == ("努力", "L7")


def test_a_phrase_card_is_never_found_across_a_dropped_comma():
    """L9 finds a phrase card as its run of words in the library — but a run whose words stand on both sides of a comma
    the tokenizer dropped (気が、ついた) is no use of it: only the whole run of the sentence counts."""
    tok = _tokenizer()
    lines = ["やっと気がついた。", "気が、ついたら朝だった。"]
    cache = {"第01話": [(text, [list(t) for t in tokens])
                       for line in lines for text, tokens in tok.tokenize_sentences(line)]}
    phrases = anki_match.phrase_lemmas(["気がつく"], tok.tokenize)
    assert anki_match.find_phrases(phrases, [("第01話", 10)], cache.__getitem__) == {"気がつく": (1, 10, 1)}


# --------------------------------------------------------------------------- #
# One word or two: the dictionary decides (the user, 2026-09-30: "I would let the dictionary decide")
# --------------------------------------------------------------------------- #
def test_two_words_are_two_entries_of_the_dictionary():
    """A card's word and the word it is read as are two words when JMdict gives each an entry and none holds both:
    揚げる 'deep-fry' (its own entry) and 上げる 'raise', 心する 'take heed' and 心, the noun 集い 'a gathering' and the
    verb 集う, 一気に 'in one go' and 一気 'one breath', ことに 'especially' (a reading of 殊に) and 事. One word when an
    entry holds both (逃げだす is a spelling of 逃げ出す's), when the card's word has no entry (努力する: 努力 takes
    する), when the word it is read as is kana (ひょい, and すっ — the sound word of すっと, never the prefix 素っ that
    shares its sound), and for a じる verb and its ずる form (UniDic files 信じる under 信ずる)."""
    for word, lexeme in (("揚げる", "上げる"), ("心する", "心"), ("集い", "集う"), ("一気に", "一気"),
                         ("ことに", "事"), ("堪らない", "堪る"), ("20世紀", "世紀")):
        assert anki_match.two_words(word, lexeme), (word, lexeme)
    for word, lexeme in (("逃げだす", "逃げ出す"), ("努力する", "努力"), ("ひょいと", "ひょい"), ("すっと", "すっ"),
                         ("信じる", "信ずる"), ("感じる", "感ずる"), ("最後に", "最後"), ("部屋", "部屋"),
                         ("", "心"), ("心する", ""), ("Ｘする", "心")):
        assert not anki_match.two_words(word, lexeme), (word, lexeme)


def test_a_dictionary_that_cannot_be_read_sets_no_card_apart(monkeypatch):
    """A broken install costs the rule, never a card's place: with no dictionary every card matches as before."""
    monkeypatch.setattr(anki_match, "_dictionary", [None])
    assert not anki_match.two_words("揚げる", "上げる")
    assert anki_match.card_key("心する", {"心": 0}, "ja", None, _tokenizer().tokenize) == ("心", "L7")


def test_a_card_the_dictionary_lists_whole_lands_on_no_other_words_row():
    """心する, 一気に, 堪らない and 揚げる are words of their own in JMdict — the list's 心, 一気, 堪る and 上げる are
    other words — so Junban places each by its own sentence, and the mark marks none of those rows. Read alone, so
    is ことに (殊に's reading), never 事 + に. The user's "yes" to a pair still places the card there."""
    tokenize = _tokenizer().tokenize
    listed = {"心": 0, "一気": 1, "堪る": 2, "上げる": 3, "こと": 4}
    for word in ("心する", "一気に", "堪らない", "揚げる", "ことに"):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == ("", ""), word
    yes = {"心する": {"target": "心", "answer": "yes"}}
    assert anki_match.card_key("心する", listed, "ja", yes, tokenize) == ("心", "yes")
    assert anki_match.word_of_its_own("心する", tokenize("心する"), anki_match.one_word(tokenize("心する")))


def test_one_dictionary_word_still_lands_on_its_row():
    """Where the dictionary does not tell the card from the list's word, nothing changes: 努力する and お茶する are
    the noun + する (JMdict lists no entry for either whole), 最後に the noun + に, ひょいと the sound word + と,
    逃げだす a spelling of 逃げ出す, and 信じる UniDic's 信ずる — one verb in two conjugations."""
    tokenize = _tokenizer().tokenize
    listed = {"努力": 0, "お茶": 1, "最後": 2, "ひょい": 3, "逃げ出す": 4, "信ずる": 5}
    for word, key, via in (("努力する", "努力", "L7"), ("お茶する", "お茶", "L7"), ("最後に", "最後", "L7"),
                           ("ひょいと", "ひょい", "L7"), ("逃げだす", "逃げ出す", "L6"), ("信じる", "信ずる", "L6")):
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, via), word


def test_a_spelling_in_another_words_forms_is_not_that_row_unless_the_row_writes_it(tmp_path):
    """A list row's Forms hold every spelling its word was met in, and a verb's stem is spelled like the noun the
    dictionary makes of it: 生き (the noun 'living') in 生きる's, 集い in 集う's. The card is that noun, a word of its
    own, and lands on neither row. A row whose own spelling (its Orth) is the card's is the card's row, whatever word
    UniDic files it under: the content writes 治める, UniDic's 収める."""
    tokenize = _tokenizer().tokenize
    index = anki_match.build_index(_write_list(tmp_path / "list.csv", [
        ("生きる", "生きる", "生き|生きれ"), ("集う", "集う", "集い|集っ"), ("収める", "治める", "収め")]), language="ja")
    assert index.orths == ["生きる", "集う", "治める"]
    for word in ("生き", "集い"):
        assert anki_match.card_key(word, index.rank_of, "ja", None, tokenize, index.words,
                                   index.orths) == ("", ""), word
    for word in ("治める", "収める", "生きれ"):
        assert anki_match.card_key(word, index.rank_of, "ja", None, tokenize, index.words, index.orths) == (
            word, "exact"), word
    assert anki_match.another_word("生き", "生き", index.rank_of, index.words, index.orths)
    assert not anki_match.another_word("治める", "治める", index.rank_of, index.words, index.orths)


def test_a_cards_own_grammar_comes_off_whatever_entries_the_dictionary_gives_it():
    """JMdict lists お部屋, 俺たち and 暑さ as entries — yet a polite お, a plural and a さ are the word's own grammar,
    and the user decided those cards are their word, known through each other (2026-09-29). So they stay 部屋, 俺
    and 暑い."""
    tokenize = _tokenizer().tokenize
    listed = {"部屋": 0, "俺": 1, "暑い": 2}
    for word, key in (("お部屋", "部屋"), ("俺たち", "俺"), ("暑さ", "暑い")):
        assert anki_match.two_words(word, key), word
        assert anki_match.card_key(word, listed, "ja", None, tokenize) == (key, "L7"), word
        assert not anki_match.word_of_its_own(word, tokenize(word), anki_match.one_word(tokenize(word))), word


def test_a_question_is_never_asked_across_two_dictionary_words():
    """"Same word as one on your list?" asks nothing the dictionary has answered: 対する is a verb of its own (not
    the list's one-character 対 + する), and 揚げる in its sentence is no 上げる. A noun + する the dictionary does
    not list whole is still asked."""
    tokenize = _tokenizer().tokenize
    assert anki_match.suggest("対する", "彼に<b>対する</b>態度", tokenize, {"対": 0}, "ja") is None
    assert anki_match.suggest("揚げる", "天ぷらを<b>揚げた</b>。", tokenize, {"上げる": 0}, "ja") is None
    assert anki_match.suggest("同行する", "", tokenize, {"同行": 0}, "ja").key == "同行"


def test_the_shipped_dictionary_reads_a_kana_card_by_the_entries_its_reading_names():
    """app/jmdict_data.py's readings are kept only where a card in kana can be read as another word + something
    written onto it: ことに reads 殊に's entry, and ひょいと an entry written in kana alone (numbered past the kanji
    entries) — まく ends in nothing a card is read through, so it is not kept."""
    from app import jmdict_data
    kanji, readings = anki_match._dictionary_entries()
    lines = jmdict_data.kanji_forms().split("\n")
    assert [lines[number] for number in readings["ことに"]] == ["殊に\t異に"]
    assert all(number >= len(lines) for number in readings["ひょいと"])
    assert "まく" not in readings
    assert kanji.get("２０世紀") == kanji.get("20世紀") != frozenset()

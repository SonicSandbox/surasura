"""One-kanji words on the list (analyzer § One-character words).

With Settings -> "List one-kanji words only when they're dictionary words" on (exclude_single, the default), a
one-character word is a list word only when the language says it is a word: a one-kanji word general text uses as a
word of its own, that JMdict lists and that JMdict or both frequency lists call common (app/one_kanji_data.py) — 手,
顔, 年, and こと or しばしば written in kana. It counts only where it stands on its own: glued to another one-kanji piece
(斬 + 魄 + 刀) or right after a number (三 + 年) a use is a piece of something else — no use, example or unknown. A
one-character word the list can never offer (は, or スバル, which the tagger reads as the noun 昴) keeps no sentence
from i+1 anywhere, and the report names each file's one-kanji words the list can't offer. Off, every one-character
word is listed and every use counts, as before.

Real Japanese, made-up sentences; the app's own tokenizer, table and token store.
"""

import json
import os
import re
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer, phrases, sentence_corpus, token_index

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "web_app.html")


@pytest.fixture(scope="module")
def tokenizer():
    analyzer.SANITIZE_JA = True
    return analyzer.JapaneseTokenizer(library=False)


def _sentence(tokenizer, text):
    ((sentence, tokens),) = list(tokenizer.tokenize_sentences(text))
    return sentence, tokens


def _bound(tokenizer, text):
    sentence, tokens = _sentence(tokenizer, text)
    return [tokens[i][0] for i in sorted(analyzer.bound_uses(sentence, tokens))]


# --- the table and the rule -------------------------------------------------------------------------------------- #
def test_the_table_lists_dictionary_words_each_reading_on_its_own():
    """A one-kanji word the language calls a word is offered — written in kanji or in kana (こと is 事, しばしば 屡) —
    and nouns that mostly build words are too (部, 式, 感); a reading that is only a suffix (中 ちゅう, 的, 様 さま), the
    よう of ような, grammar, and a name the tagger reads as a rare noun (昴, from スバル) never are. Each reading is its
    own word: 中 read なか is offered, read ちゅう never; 時 read とき, and read じ by its own JMdict sense."""
    kind = analyzer.single_kind
    for key in (("手", "テ"), ("顔", "カオ"), ("目", "メ"), ("私", "ワタシ"), ("年", "ネン"), ("事", "コト"),
                ("物", "モノ"), ("為", "タメ"), ("屡", "シバシバ"), ("部", "ブ"), ("式", "シキ"), ("感", "カン"),
                ("中", "ナカ"), ("時", "トキ"), ("時", "ジ")):
        assert kind(key) == 2, key
    for key in (("中", "チュウ"), ("的", "テキ"), ("様", "サマ"), ("様", "ヨウ"), ("人", "ニン"), ("達", "タチ"),
                ("は", "ハ"), ("の", "ノ"), ("た", "タ"), ("昴", "スバル")):
        assert kind(key) == 1, key
    assert kind(("手紙", "テガミ")) == 0, "two characters: any word"
    assert kind(("は", "ハ"), False) == 0 and kind(("昴", "スバル"), False) == 0, "the rule off: every one counts"


def test_a_use_glued_to_another_piece_or_after_a_number_is_a_piece_of_something_else(tokenizer):
    """斬 + 魄 + 刀 is a term in pieces (手, beside kana, stands on its own); 年 right after 三 or 10 is a count, and
    前 glued to it is part of 三年前; 時 read じ after 何 is a count too. A word beside kana stands on its own, and so
    does こと written in kana."""
    assert _bound(tokenizer, "斬魄刀を手に取った。") == ["斬", "魄", "刀"]
    assert _bound(tokenizer, "三年前にこの町へ来た。") == ["年", "前"]
    assert _bound(tokenizer, "10年ぶりに兄と会った。") == ["年"]
    assert _bound(tokenizer, "何時に起きるの？") == ["時"]
    assert _bound(tokenizer, "年が明けて、雪が降った。") == []
    assert _bound(tokenizer, "そんなことは知らない。") == []


def test_a_one_kanji_word_after_a_numbers_counter_is_a_piece_of_the_count(tokenizer):
    """目 in ２時間目 'second period', 前 in 三週間前 'three weeks ago', 半 in 一時間半: a counter written in kanji right
    after a number, and the one-kanji word right after it belongs to the count — no use of 目 'eye'. A word after the
    particle の stands on its own (三の矢 'the third arrow'), and so does one after a word no number comes before
    (毎日目が疲れる)."""
    assert _bound(tokenizer, "２時間目は数学の授業だ。") == ["目"]
    assert _bound(tokenizer, "三週間前に会った。") == ["前"]
    assert _bound(tokenizer, "一時間半の遅刻だ。") == ["半"]
    assert _bound(tokenizer, "三の矢を放つ。") == []
    assert _bound(tokenizer, "毎日目が疲れる。") == []


def test_what_the_list_cant_offer_is_named_per_sentence_and_nothing_with_the_rule_off(tokenizer):
    """スバル (read as 昴) and the particles are never offered; 餌 is. Off, nothing is left out. Empty: nothing."""
    sentence, tokens = _sentence(tokenizer, "スバルは餌を撒いた。")
    assert {tokens[i][0] for i in analyzer.unoffered(sentence, tokens)} == {"昴", "は", "を", "た"}
    assert analyzer.unoffered(sentence, tokens, rule=False) == set()
    sentence, tokens = _sentence(tokenizer, "三年前にこの町へ来た。")
    assert {tokens[i][0] for i in analyzer.unoffered(sentence, tokens)} == {"年", "前", "に", "へ", "た"}
    assert analyzer.unoffered("", []) == set() and analyzer.bound_uses("", []) == set()


def test_the_report_names_rare_one_kanji_words_never_grammar_or_a_word_the_list_offers():
    """"Also in this file, not on your list": a name read as a common noun (昴) or a rare word (簪) — never grammar
    (the よう of ような, the plural たち), never a particle, and never a word the list offers in another reading (私,
    listed as わたし)."""
    assert analyzer.not_on_list(("昴", "スバル")) and analyzer.not_on_list(("簪", "カンザシ"))
    for key in (("様", "ヨウ"), ("達", "タチ"), ("私", "ワタクシ"), ("は", "ハ"), ("手紙", "テガミ")):
        assert not analyzer.not_on_list(key), key


# --- a whole Generate -------------------------------------------------------------------------------------------- #
DIARY = "\n".join([
    "彼は顔を上げた。",
    "顔を洗ってから出かけた。",
    "母の顔を思い出した。",
    "三年前にこの町へ来た。",
    "10年ぶりに兄と会った。",
    "年が明けて、雪が降った。",
    "年に一度の祭りがある。",
    "スバルは餌を撒いた。",
    "スバルが門を開けた。",
    "スバルと話した。",
    "第三条に書いてある。",
    "規則の条を読んだ。",
])
KNOWN = ("彼", "上げる", "洗う", "出かける", "母", "思い出す", "町", "来る", "振り", "兄", "会う", "明ける", "雪", "降る",
         "祭り", "有る", "餌", "門", "開ける", "話す", "この", "から", "書く", "規則", "読む")


@pytest.fixture
def diary():
    """One file of the diary under the sandbox root (SURASURA_TEST_ROOT, set by conftest)."""
    root = Path(os.environ["SURASURA_TEST_ROOT"])
    high = root / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    (high / "diary.txt").write_text(DIARY, encoding="utf-8")
    (root / "User Files" / "ja").mkdir(parents=True)
    (root / "User Files" / "ja" / "KnownWord.json").write_text(
        json.dumps({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in KNOWN]}, ensure_ascii=False),
        encoding="utf-8")
    (root / "results").mkdir()
    return root


def _run(root, *extra_args):
    """One Generate -> (priority list rows by Word, file_statistics.json's entries)."""
    results = root / "results"
    listed = results / "priority_learning_list.csv"
    if listed.exists():
        listed.unlink()
    with patch("app.analyzer.RESULTS_DIR", str(results)), \
            patch("app.analyzer.OUTPUT_CSV", str(listed)), \
            patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
            patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
            patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "1", *extra_args]):
        analyzer.main()
    rows = pd.read_csv(listed).fillna("").to_dict("records") if listed.exists() else []
    stats = json.loads((results / "file_statistics.json").read_text(encoding="utf-8"))
    return {row["Word"]: row for row in rows}, stats


def _contexts(row):
    return [row[k] for k in row if k.startswith("Context ") and row[k]]


def test_a_one_kanji_word_is_listed_by_the_uses_where_it_stands_on_its_own(diary):
    """顔 is a row of its 3 uses; 年 a row of the 2 it stands on its own in (三年, 10年 are counts) — and only those
    are its examples; neither the particles nor 昴 (スバル) is a row, nor 度 (only after 一 here)."""
    rows, _stats = _run(diary)
    assert rows["顔"]["Occurrences"] == 3
    assert rows["年"]["Occurrences"] == 2
    assert set(_contexts(rows["年"])) <= {"年が明けて、雪が降った。", "年に一度の祭りがある。"}
    for word in ("は", "を", "た", "の", "昴", "前", "度"):
        assert word not in rows, word


def test_a_word_the_list_cant_offer_keeps_no_sentence_from_i_plus_one(diary):
    """撒く's one sentence holds 昴 (スバル) and particles the learner never studied: strict i+1 keeps it all the same,
    since none of them can come from the list."""
    rows, _stats = _run(diary, "--only-i-plus-one")
    assert _contexts(rows["撒く"]) == ["スバルは餌を撒いた。"]


def test_each_file_names_its_one_kanji_words_the_list_cant_offer(diary):
    """file_statistics.json carries, per file, "Also in this file, not on your list": スバル (read 昴), 3 uses, and 条
    by its one use standing on its own (第三条's is a count) — never a particle or a prefix (第)."""
    _rows, stats = _run(diary)
    (entry,) = stats
    assert entry["Not On List"] == [["スバル", "昴", 3], ["条", "条", 1]]


def test_the_files_line_leaves_a_word_to_the_set_phrase_it_lives_only_inside(diary, monkeypatch):
    """腑 lives only inside 腑に落ちる: with phrase rows on, the phrase takes its uses, so the file's line never names it
    there — it is learned with the phrase, as on the list. With phrase rows off it is named like any one-kanji word the
    list can't offer."""
    found = phrases.load()
    assert phrases.bound_at(found.entry(found.of_word("腑に落ちる"))) == (0,)    # the premise: 腑 lives only inside it
    (diary / "data" / "ja" / "HighPriority" / "diary.txt").write_text(
        "今の説明でやっと腑に落ちた。\nなるほど、それなら腑に落ちる。\nスバルが門を開けた。\n", encoding="utf-8")
    for on, named in ((True, [["スバル", "昴", 1]]), (False, [["腑", "腑", 2], ["スバル", "昴", 1]])):
        (diary / "settings.json").write_text(json.dumps({"logic": {"phrase_rows": on}}), encoding="utf-8")
        monkeypatch.setitem(analyzer.LOGIC, "phrase_rows", on)
        rows, (entry,) = _run(diary)
        assert ("腑に落ちる" in rows) == on
        assert entry["Not On List"] == named, on


def test_with_the_rule_off_every_one_character_word_is_listed_and_every_use_counts(diary):
    rows, stats = _run(diary, "--include-single-chars")
    assert rows["年"]["Occurrences"] == 4 and "は" in rows and rows["昴"]["Occurrences"] == 3 and "度" in rows
    assert "Not On List" not in stats[0]


def test_the_rarity_slider_counts_a_one_kanji_word_as_the_list_does(diary):
    """The token store keeps each file's pieces (年 in 三年 and 10年, 前 in 三年前): the slider's numbers — and
    automatic rarity's — count a one-kanji list word by the uses Generate counts."""
    rows, _stats = _run(diary)
    store = token_index.open_store("ja")
    try:
        assert store.bound_counts()[("年", "ネン")] == 2
        unknown = dict(store.unknown_frequencies(skip_singles=True)["unknown"])
    finally:
        store.close()
    for word in ("顔", "年", "撒く"):
        row = rows[word]
        assert unknown[f"{word}|{row['Reading']}"] == row["Occurrences"], word
    assert not any(key.startswith(("昴|", "は|", "を|")) for key in unknown)


# --- the token store: a term the library joins ------------------------------------------------------------------- #
TERM_FILES = {"a.txt": "焔魄陣を放った。\n彼の焔魄陣は強い。\n", "b.txt": "焔魄陣が光る。\n陣が崩れた。\n"}


def test_the_store_takes_a_joined_terms_pieces_off_and_still_counts_what_the_list_counts(tmp_path):
    """焔魄陣 is a made-up term the library keeps using as one (the work-terms table joins it): as each file reads alone
    its 炎 (焔) and 陣 are pieces glued to each other; joined, they are no tokens at all. The store's totals take the
    joins — counts and pieces alike — so the slider counts 陣 by its one use standing on its own, as the list does."""
    folder = tmp_path / "lib"
    folder.mkdir()
    paths = []
    for name, text in TERM_FILES.items():
        (folder / name).write_text(text, encoding="utf-8")
        paths.append(str(folder / name))
    store = token_index.open_store("ja", path=str(folder / "store.db"))
    try:
        store.reconcile(paths, token_index.make_tokenizer("ja"), build_signature=token_index.build_signature("ja"))
        assert "焔魄陣" in (store.names_tables() or {}).get("w", {})
        raw = dict(store.conn.execute("SELECT lemma || '|' || reading, count FROM bound").fetchall())
        assert raw["陣|ジン"] == 3 and raw["炎|ホノオ"] == 3
        listed, pieces = Counter(), Counter()
        for path in paths:
            for text, tokens in store.file_tokens(path):
                for token in tokens:
                    listed[(token[0], token[1])] += 1
                for i in analyzer.bound_uses(text, tokens):
                    pieces[(tokens[i][0], tokens[i][1])] += 1
        assert listed[("陣", "ジン")] == 1 and not pieces[("陣", "ジン")]
        bound = store.bound_counts()
        assert bound.get(("陣", "ジン"), 0) == 0 and bound.get(("炎", "ホノオ"), 0) == 0
        unknown = dict(store.unknown_frequencies(skip_singles=True)["unknown"])
        assert unknown["陣|ジン"] == 1 and "炎|ホノオ" not in unknown
    finally:
        store.close()


# --- 例文 and the sentence dictionary ---------------------------------------------------------------------------- #
def test_the_sentence_dictionary_offers_what_the_list_offers(tokenizer):
    """An entry for 顔 and 年, from the sentences where they stand on their own; none for 昴 or a particle; neither is
    an unknown in 撒く's sentence. With the rule off, 昴 is an entry and every one-character word counts, as before."""
    sentences = [(text, [list(t) for t in tokens]) for text, tokens in tokenizer.tokenize_sentences(DIARY)]
    known = (set(), set(KNOWN), set())

    def collect(singles):
        return sentence_corpus.collect(["diary"], lambda path: sentences, "ja", known, (1, 100, 1, 100),
                                       singles=singles)
    words = collect(True)
    assert words[("顔", "カオ")].listed and words[("年", "ネン")].listed
    assert sorted(c[1] for c in words[("年", "ネン")].best.result()) == ["年が明けて、雪が降った。", "年に一度の祭りがある。"]
    assert ("昴", "スバル") not in words and ("は", "ハ") not in words
    (best,) = words[("撒く", "マク")].best.result()
    assert best[0][0] == 0, "昴 is no unknown beside 撒く"
    off = collect(False)
    assert off[("昴", "スバル")].listed
    (best,) = off[("撒く", "マク")].best.result()
    assert best[0][0] == 4, "off: 昴 and the three particles count, as they always did"


# --- a set phrase's readiness ------------------------------------------------------------------------------------ #
PHRASES = [
    ["手|に|入れる", "テ|ニ|イレル", "cgc", "手に入れる", "テニイレル"],
    ["昴|が|見える", "スバル|ガ|ミエル", "cgc", "昴が見える", "スバルガミエル"],
    ["腑|に|落ちる", "フ|ニ|オチル", "bgc", "腑に落ちる", "フニオチル"],
]


def test_a_phrase_waits_for_a_one_kanji_word_the_list_offers_and_never_for_one_it_cant():
    """手に入れる waits for 手 while 手 is new — 手 is on the list; a phrase never waits for a one-character word the
    list can't offer (昴) or for a word that lives only inside it (腑), which still gives the phrase its uses. Without
    the rule's answer (a caller that passes none) no one-character word is waited for."""
    found = phrases.PhraseSet(PHRASES)
    offered = lambda key: analyzer.single_kind(key) != 1      # noqa: E731 — the analyzer's own test
    hand = found.entry(found.of_word("手に入れる"))
    assert phrases.waiting(hand, lambda key: key[0] == "入れる", offered) == ((("手", "テ"),), False)
    assert phrases.waiting(hand, lambda key: key[0] in ("手", "入れる"), offered) == ((), True)
    assert phrases.waiting(hand, lambda key: key[0] == "入れる") == ((), False)
    star = found.entry(found.of_word("昴が見える"))
    assert phrases.waiting(star, lambda key: key[0] == "見える", offered) == ((), False)
    gut = found.entry(found.of_word("腑に落ちる"))
    assert phrases.waiting(gut, lambda key: key[0] == "落ちる", lambda key: True) == ((), False)
    assert phrases.bound_at(gut) == (0,)


# --- the report and Settings ------------------------------------------------------------------------------------- #
def _render(tmp_path, unlisted):
    """A report whose one file names `unlisted` in file_statistics.json; -> the file's entry in the page's data."""
    results = tmp_path / "results"
    results.mkdir(parents=True)
    pd.DataFrame([{"Word": "顔", "Reading": "カオ", "Tier": "Outside", "Score": 30, "Occurrences": 3,
                   "Count (High)": 3, "Count (Low)": 0, "Count (Goal)": 0, "Sources": "diary.txt",
                   "Context 1": "母の顔を思い出した。"}]
                 ).to_csv(results / "priority_learning_list.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"Sequence": 1, "Source File": "diary.txt", "Word": "顔", "Reading": "カオ", "Tier": "Outside",
                   "Score": 30, "Occurrences (Global)": 3, "Occurrences (File)": 3, "Count (High)": 3,
                   "Count (Low)": 0, "Count (Goal)": 0, "Context 1": "母の顔を思い出した。"}]
                 ).to_csv(results / "progressive_learning_list.csv", index=False, encoding="utf-8-sig")
    stats = {"File": "diary.txt", "Total Words": 40, "Known Count": 30, "Coverage (%)": 75.0}
    if unlisted is not None:
        stats["Not On List"] = unlisted
    (results / "file_statistics.json").write_text(json.dumps([stats], ensure_ascii=False), encoding="utf-8")

    from app import static_html_generator as gen
    out = results / "reading_list_static.html"
    with patch.object(gen, "RESULTS_DIR", str(results)), \
            patch.object(gen, "PRIORITY_CSV", str(results / "priority_learning_list.csv")), \
            patch.object(gen, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")), \
            patch.object(gen, "OUTPUT_FILE", str(out)):
        gen.generate_static_html(theme="default")
    payload = re.search(r"let globalData = (\{.*?\});\n", out.read_text(encoding="utf-8"), re.S)
    (entry,) = json.loads(payload.group(1))["progressive"]
    return entry


def test_the_report_carries_each_files_words_not_on_the_list(tmp_path):
    """The analyzer's per-file tally reaches the page with the file; a file with none carries an empty list."""
    assert _render(tmp_path / "a", [["スバル", "昴", 3], ["簪", "簪", 1]])["unlisted"] == [["スバル", "昴", 3],
                                                                                        ["簪", "簪", 1]]
    assert _render(tmp_path / "b", None)["unlisted"] == []


def test_the_per_file_line_is_the_reports_own_style_and_dictionary_extensions_read_only_the_words():
    """One small line under the file's comprehension bar, as "already in Anki" is: the words as text (Yomitan can look
    one up to make a card), the label, the counts and the dots drawn by CSS (hidden from dictionary extensions), a
    plain-language hover; a completed file shows it too."""
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    assert "function createUnlistedLine(unlisted)" in html and ".unlisted-line {" in html
    assert 'data-content="Also in this file, not on your list:" ' in html
    assert 'class="hidden-content unlisted-count"' in html and "migaku_ignore data-yomichan-ignore" in html
    assert "createUnlistedLine(unlisted)" in html and 'createUnlistedLine(stats["Not On List"])' in html
    assert "fileData.unlisted" in html


def test_the_setting_keeps_its_key_and_says_what_it_does():
    """Settings keeps exclude_single (on by default) under its new name and tooltip; the Rarity slider follows it."""
    from app import settings_manager
    assert settings_manager.DEFAULT_SETTINGS["exclude_single"] is True
    source = Path(TEMPLATE).parent.parent.joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'text="List one-kanji words only when they\'re dictionary words"' in source
    assert ('"Particles and endings (は, た) and pieces of names or made-up terms stay off your list. "\n'
            '                            "Words like 手, 目 and 顔 are listed."') in source
    assert '"exclude_single": self.var_exclude_single.get()' in source

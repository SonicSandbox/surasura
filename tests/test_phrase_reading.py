"""A set phrase's row shows the spelling the library uses and that spelling's own reading (ENGINE 40).

The row's identity stays (Word, Reading) — the lemmas joined and the dictionary's reading of its spelling (良い感じ
ヨイカンジ) — but the journey shows the library's spelling (Orth: いい感じ), and so it shows that spelling's reading
too: `Kana` (plan_rules.display_reading — kana as written, kanji as the dictionary reads them). And a phrase that ends
in a form of its own is that form only: ごめんなさい is never named ごめんなさる, だけじゃない is no だけでなく
(phrases.fixed_form, MATCHER_VERSION 6). Real lines: tests/Test Resources/ja/phrase_reading/phrase_reading_sample.srt (a folder of its own: the store tests' show names come from the top folder's files).
"""
import json
import os
import re
import shutil
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer, plan_engine, plan_rules

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "ja")
TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "web_app.html")


@pytest.mark.parametrize("orth, display, reading, shown", [
    # the library's kana where the dictionary's spelling has other kana (いい for よい)
    ("いい感じ", "よい感じ", "ヨイカンジ", "イイカンジ"),
    ("ほうがいい", "方がよい", "ホウガヨイ", "ホウガイイ"),
    ("ちょうどいい", "丁度よい", "チョウドヨイ", "チョウドイイ"),
    ("まあいっか", "まあいいか", "マアイイカ", "マアイッカ"),
    ("やるしかない", "やるっきゃない", "ヤルッキャナイ", "ヤルシカナイ"),
    ("しょうがない", "仕様がない", "シヨウガナイ", "ショウガナイ"),
    ("カッコつける", "格好つける", "カッコウツケル", "カッコツケル"),
    # a kanji the library writes in kana, the rest read as the dictionary reads its kanji
    ("目をつむる", "目を瞑る", "メヲツブル", "メヲツムル"),
    ("捨てたものじゃない", "捨てたもんじゃない", "ステタモンジャナイ", "ステタモノジャナイ"),
])
def test_the_reading_shown_is_the_shown_spellings_own(orth, display, reading, shown):
    # why: the card showed いい感じ beside ヨイカンジ — the library's spelling with the dictionary's reading
    assert plan_rules.display_reading(orth, display, reading) == shown


@pytest.mark.parametrize("orth, display, reading", [
    ("気に入る", "気に入る", "キニイル"),         # the same spelling: nothing to do
    ("気にいる", "気に入る", "キニイル"),         # the spelling already reads so (never the tagger's キニハイル)
    ("何もない", "何も無い", "ナニモナイ"),
    ("いつの間に", "いつの間に", "イツノマニ"),
    ("仲よい", "仲良い", "ナカイイ"),             # kana for a kanji the reading can't be split at: kept
    ("いつもとおり", "いつも通り", "イツモドオリ"),  # only the voicing differs: the dictionary's reading stays
    ("ＡＢＣがいい", "ＡＢＣがよい", "エービーシーガヨイ"),  # a letter: no reading to build
    ("", "よい感じ", "ヨイカンジ"),
])
def test_the_rows_reading_stays_where_the_spelling_gives_no_other(orth, display, reading):
    assert plan_rules.display_reading(orth, display, reading) == reading


def test_a_kanji_after_other_kana_keeps_the_rows_reading():
    # why (review): 声 is ゴエ only inside デカ声 — でかい声 would read デカイゴエ; a kanji's reading is taken only where
    # it stands after the same kana in both spellings (いい感じ: 感 after い in both)
    assert plan_rules.display_reading("でかい声", "デカ声", "デカゴエ") == "デカゴエ"
    assert plan_rules.display_reading("俺の家", "俺ん家", "オレンチ") == "オレンチ"
    assert plan_rules.display_reading("いい感じ", "よい感じ", "ヨイカンジ") == "イイカンジ"


def test_a_counter_or_iteration_mark_is_never_read_as_a_kana_of_its_own():
    # why (review): 三ヶ月 is さんかげつ, not サンヶゲツ
    assert plan_rules.display_reading("三ヶ月", "三か月", "サンカゲツ") == "サンカゲツ"
    assert plan_rules.display_reading("いすゞ", "いすず", "イスズ") == "イスズ"


def test_a_reading_the_spellings_cannot_line_up_one_way_only_stays():
    # why: in 見の見 read ミノノミ the first 見 is ミ or ミノ: a guess would put a wrong reading on the card — the
    # row's stays; so it does where one kanji would need two readings
    assert plan_rules.display_reading("見を見", "見の見", "ミノノミ") == "ミノノミ"
    assert plan_rules.display_reading("見を見", "見の見", "ミノカミ") == "ミノカミ"


@pytest.fixture
def run(tmp_path, monkeypatch):
    root = Path(os.environ["SURASURA_TEST_ROOT"])
    high = root / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    shutil.copy(os.path.join(RES, "phrase_reading", "phrase_reading_sample.srt"), high / "phrase_reading_sample.srt")
    uf = root / "User Files" / "ja"
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    (uf / "IgnoreList.txt").write_text("", encoding="utf-8")
    (root / "settings.json").write_text(json.dumps({"logic": {"phrase_rows": True}}), encoding="utf-8")
    monkeypatch.setitem(analyzer.LOGIC, "phrase_rows", True)
    results = root / "results"
    results.mkdir(exist_ok=True)
    with patch("app.analyzer.RESULTS_DIR", str(results)), \
            patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
            patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
            patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
            patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "2", "--static", "--no-open"]):
        analyzer.main()
    return results


def _rows(results, name):
    return pd.read_csv(results / name, keep_default_na=False).to_dict("records")


def test_a_generate_lists_a_phrase_in_the_librarys_spelling_and_its_reading(run):
    # why: the journey card is Orth + Kana; the row itself (Word, Reading) must not move — known words, the ignore
    # list, the In-Anki mark and the plan all match on it
    rows = {r["Word"]: r for r in _rows(run, "priority_learning_list.csv")}
    good = rows["良い感じ"]
    assert (good["Orth"], good["Reading"], good["Kana"]) == ("いい感じ", "ヨイカンジ", "イイカンジ")
    enough = rows["もう良い"]
    assert (enough["Orth"], enough["Reading"], enough["Kana"]) == ("もういい", "モウヨイ", "モウイイ")
    # its spelling already reads as the row does: no Kana of its own
    assert (rows["気に入る"]["Kana"], rows["気に入る"]["Reading"]) == ("", "キニイル")
    # only those phrase rows: every word's row, and every phrase written as its row reads, has no Kana
    assert {w for w, r in rows.items() if r["Kana"]} == {"良い感じ", "もう良い", "仕様が無い"}
    assert rows["仕様が無い"]["Kana"] == "ショウガナイ"
    progressive = [r for r in _rows(run, "progressive_learning_list.csv") if r["Word"] == "良い感じ"]
    assert progressive and all(r["Kana"] == "イイカンジ" for r in progressive)


def test_a_phrase_with_a_form_of_its_own_is_named_in_it_and_keeps_its_voicing(run):
    # why: the journey showed ごめんなさる (made up: なさる's dictionary form) and いつもとおり (UniDic drops the
    # voiced ど of どおり in its dictionary form)
    rows = {r["Word"]: r for r in _rows(run, "priority_learning_list.csv")}
    assert rows["御免為さる"]["Orth"] == "ごめんなさい" and rows["御免為さる"]["Kana"] == ""
    assert rows["何時も通り"]["Orth"] == "いつもどおり" and rows["何時も通り"]["Kana"] == ""
    # だけじゃない twice: another expression than だけでなく 'not only … but also' — no row for it
    assert "だけだ無い" not in rows


def test_the_replan_shows_the_same_kana_as_the_generate(run):
    # why: the journey's redraw after a move writes the engine's rows over the Generate's: Kana must survive it
    plan = plan_engine.load(str(run / analyzer.PLAN_FILE))
    assert plan.header["format"] == plan_engine.FORMAT == analyzer.PLAN_FORMAT == 4
    result = plan_engine.Engine(plan).result()
    # a format-4 plan whose phrase entries lack the spelling is refused whole, never half-read
    lines = [json.loads(line) for line in __import__("gzip").decompress(
        (run / analyzer.PLAN_FILE).read_bytes()).split(b"\n") if line]
    lines[0]["phrase_entries"] = [entry[:2] for entry in lines[0]["phrase_entries"]]
    broken = run / "broken.json.gz"
    broken.write_bytes(__import__("gzip").compress(b"\n".join(json.dumps(line, ensure_ascii=False).encode("utf-8")
                                                               for line in lines) + b"\n"))
    with pytest.raises(plan_engine.PlanError, match="phrase_entries"):
        plan_engine.load(str(broken))
    want = {(r["Word"], r["Reading"]): r["Kana"] for r in _rows(run, "priority_learning_list.csv")}
    assert {(r["Word"], r["Reading"]): r["Kana"] for r in result.priority} == want
    assert ("良い感じ", "ヨイカンジ") in want


def test_the_journey_shows_kana_where_there_is_one_and_keys_on_the_reading():
    # why: display only — the card and the search hit show Kana, the In-Anki key stays Word|Reading
    html = open(TEMPLATE, encoding="utf-8").read()
    assert "function shownReading(data)" in html
    assert 'data-reading="${shownReading(data)}"' in html
    assert "const reading = shownReading(row);" in html
    assert "row.Reading, row.Kana, ...forms" in html          # typing いいかんじ finds the いい感じ card
    assert re.search(r"return `\$\{data\.Word\}\|\$\{\(typeof data\.Reading === 'string'\) \? data\.Reading : ''\}`",
                     html)

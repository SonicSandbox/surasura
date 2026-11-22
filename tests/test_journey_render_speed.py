"""The journey v3 render's fast paths and its shape 1.1 (J-DATA; SPEC §5.4's budgets, TheForge
tracks/window/work/j-data/SHAPE.md): the list CSVs read without pandas, the learner's Kanjium copy read only when it
exists and only for unidic's misses, the meanings table streamed, the word memo in results/, and 1.1's additions (each
source's item id, the seven settings rows, the stamp in ms, a "0 of 0" snapshot drawn as no bar).

What a wrong answer would cost a learner: a word or a meaning that changes when the memo answers (a warm render must be
the cold one), a word spelled "NA" turned into nothing, the learner's own dictionary text kept in a file it must not be
in, a pitch file read that isn't there, a line the page can't name to ⚑ / Swap, or a growth bar of nothing."""
import base64
import csv
import gzip
import json
import lzma
import os
import time
import types

import pytest

from app import journey_render as jr
from app import own_dicts
from tests.test_journey_render_shape import WORDS, _decode, _rows, _stats

LANGUAGES = ("ja", "zh")


def _all(out):
    """Everything a page shows, decoded: the head (its stamp aside), each chunk, each blob."""
    head = dict(out.head, stamp=None)
    return head, [_decode(c) for c in out.chunks], {k: _decode(v) for k, v in out.blobs.items()}


# --- shape 1.1 ------------------------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_head_carries_all_seven_setting_rows_with_their_defaults_when_unset(language):
    out = jr.build(language, _rows(language, 3), _stats(3), pitch=jr.Pitch(language, kanjium={}))
    assert out.head["v"] == 1 and out.head["minor"] == 1        # additive: a v1 reader reads it as before
    assert out.head["settings"] == {"sentences": 3, "meanings": "en", "pitch": "shown", "source": "icon",
                                    "word_size": "m", "sentence_size": "m", "theme": "night", "keys": "qwerty"}


def test_a_setting_outside_its_choices_is_its_default_and_a_key_map_passes_as_text():
    settings = {"journey_theme": "neon", "journey_pitch": "hidden", "journey_source": None,
                "journey_keys": {"next": "j", "known": "k", 3: "x", "bad": 4}, "logic": {"context": {"max_contexts": 1}}}
    shown = jr.page_settings(settings, 1)
    assert shown["theme"] == "night" and shown["pitch"] == "hidden" and shown["source"] == "icon"
    assert shown["keys"] == {"next": "j", "known": "k"} and shown["sentences"] == 1
    assert jr.page_settings({"journey_keys": {}}, 3)["keys"] == "qwerty"


def test_the_stamp_is_the_render_time_in_milliseconds():
    before = time.time_ns() // 1_000_000
    out = jr.build("ja", _rows("ja", 2), _stats(2), pitch=jr.Pitch("ja", kanjium={}))
    after = time.time_ns() // 1_000_000
    assert out.head["stamp"].isdigit() and before <= int(out.head["stamp"]) <= after


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_source_names_its_store_item_so_every_timed_line_has_one_id(language):
    """A line's id is `<item id>:<start ms>` (the simple Swap's `line_id`): the item from the line's source row —
    also for a source outside the study order (a Finished one: ep -1) — and the start from its `at`."""
    items = {7: {"id": 7, "rel_path": "Show/ep01.srt", "tier": "now", "work_id": None, "parent_folder": "Show"},
             8: {"id": 8, "rel_path": "Show/ep02.srt", "tier": "now", "work_id": None, "parent_folder": "Show"},
             9: {"id": 9, "rel_path": "Done/fin01.srt", "tier": "now", "work_id": None, "parent_folder": "Done"}}
    facts = jr.StoreFacts(items, {}, [7, 8], {}, {}, {}, "e1")       # 9 is outside the study order (Finished)
    rows = _rows(language, 2)
    rows[0]["Src 1"] = "Done/fin01.srt"                              # one line from it

    class _Timed(jr.Sources):
        def times(self, rel, sentence):
            return 12.345, 14.0

    out = jr.build(language, rows, _stats(2), facts=facts, pitch=jr.Pitch(language, kanjium={}),
                   sources=_Timed(language))
    seen = {}
    for chunk in (_decode(c) for c in out.chunks):
        for label, kind, ep, play, link, item in chunk["src"]:
            seen[label] = (ep, item)
        for word in chunk["w"]:
            for line in word[9]:
                src = chunk["src"][line[1]]
                assert src[5] is not None and f"{src[5]}:{round(line[2] * 1000)}".endswith(":12345")
    by_item = {item: ep for ep, item in seen.values()}
    assert by_item[9] == -1 and by_item[7] >= 0                      # outside the order, still named


@pytest.mark.parametrize("language", LANGUAGES)
def test_without_a_store_a_source_has_no_item_and_its_lines_no_id(language):
    out = jr.build(language, _rows(language, 2), _stats(2), pitch=jr.Pitch(language, kanjium={}))
    for chunk in (_decode(c) for c in out.chunks):
        assert chunk["src"] and all(len(row) == 6 and row[5] is None for row in chunk["src"])


def test_a_snapshot_of_nothing_counted_is_no_growth_bar():
    """A file with no words has 0 of 0: no figure, never 0 %."""
    zero = {"known": 0, "counted": 0, "unknown": 0, "at": "2026-11-20T10:00:00", "prior": False}
    real = {"known": 81, "counted": 100, "unknown": 40, "at": "2026-11-03T10:00:00", "prior": True}
    assert jr.growth_row({"added": zero, "last": zero}) is None
    assert jr.growth_row({"added": zero, "done": real, "last": zero}) == [None, None, None, None, 81.0, 40,
                                                                           "2026-11-03", None]
    assert jr.growth_row({"added": real, "last": zero})[7] is None


# --- the word memo ---------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_warm_render_from_the_word_memo_is_the_cold_render(language, tmp_path, monkeypatch):
    path = str(tmp_path / jr.WORD_MEMO)
    keys = jr.memo_keys(language)
    rows = _rows(language, 4)
    plain = jr.build(language, rows, _stats(4), pitch=jr.Pitch(language))
    cold_memo = jr.WordMemo(path, *keys)
    cold = jr.build(language, rows, _stats(4), pitch=jr.Pitch(language), memo=cold_memo)
    cold_memo.save()
    assert os.path.exists(path) and _all(cold) == _all(plain)
    assert "meanings" in cold.blobs                                  # real words: real meanings to keep

    def never(*_a, **_k):
        raise AssertionError("a warm render looked it up again")
    monkeypatch.setattr(jr.Meanings, "_load", never)                 # no table scan
    monkeypatch.setattr(jr.Pitch, "_unidic", never)                  # no tagging
    warm = jr.build(language, rows, _stats(4), pitch=jr.Pitch(language), memo=jr.WordMemo(path, *keys))
    assert _all(warm) == _all(plain)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_memo_of_another_table_or_a_damaged_one_is_no_memo(language, tmp_path):
    path = str(tmp_path / jr.WORD_MEMO)
    rows = _rows(language, 3)
    first = jr.WordMemo(path, *jr.memo_keys(language))
    jr.build(language, rows, _stats(3), pitch=jr.Pitch(language), memo=first)
    first.save()
    stale = jr.WordMemo(path, "ja:1999-01-01", "unidic:0:0|kanjium:none")
    assert stale.meanings == {} and stale.pitch == {}
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"v": 1, "g_key": ')                               # cut mid-write
    broken = jr.WordMemo(path, *jr.memo_keys(language))
    again = jr.build(language, rows, _stats(3), pitch=jr.Pitch(language), memo=broken)
    assert _all(again) == _all(jr.build(language, rows, _stats(3), pitch=jr.Pitch(language)))


# The same spelling, read another way after a Generate: JMdict gives each reading its own meaning (上手 じょうず
# "skillful" / うわて "upper part"); Chinese has no reading, so its word changes.
CHANGED = {"ja": (("上手", "ジョウズ"), ("上手", "ウワテ")), "zh": (("长大", ""), ("长城", ""))}


@pytest.mark.parametrize("language", LANGUAGES)
def test_after_a_generate_changes_the_words_the_memo_never_serves_an_old_one(language, tmp_path):
    # A Generate rewrites the list (a word read another way, a word gone) while the last page's memo stays in
    # results/: the new page must be the cold render of the new list — never a meaning or pitch from the old one.
    path = str(tmp_path / jr.WORD_MEMO)
    keys = jr.memo_keys(language)
    (old_word, old_reading), (new_word, new_reading) = CHANGED[language]
    before = _rows(language, 4)
    before[0].update(Word=old_word, Orth=old_word, Forms=old_word, Reading=old_reading)
    memo = jr.WordMemo(path, *keys)
    jr.build(language, before, _stats(4), pitch=jr.Pitch(language), memo=memo)
    memo.save()
    after = [dict(row) for row in before[:1] + before[2:]]
    after[0].update(Word=new_word, Orth=new_word, Forms=new_word, Reading=new_reading)
    cold = jr.build(language, after, _stats(4), pitch=jr.Pitch(language))
    warm = jr.build(language, after, _stats(4), pitch=jr.Pitch(language), memo=jr.WordMemo(path, *keys))
    assert _all(warm) == _all(cold)
    old_page = jr.build(language, before, _stats(4), pitch=jr.Pitch(language))
    assert _all(cold)[2]["meanings"] != _all(old_page)[2]["meanings"]       # the change is one the page shows


def test_the_memo_is_pruned_to_the_page_and_never_holds_the_learners_own_dictionary(tmp_path):
    path = str(tmp_path / jr.WORD_MEMO)
    keys = jr.memo_keys("ja")
    secret = "私だけの辞書の定義"

    def own(pairs):
        return {pair: ("My dictionary", secret) for pair in pairs}
    memo = jr.WordMemo(path, *keys)
    jr.build("ja", _rows("ja", 4), _stats(4), settings={"journey_meanings": "yours_en"}, pitch=jr.Pitch("ja"),
             own=own, memo=memo)
    memo.save()
    held = open(path, encoding="utf-8").read()
    assert secret not in held
    fewer = jr.WordMemo(path, *keys)
    jr.build("ja", _rows("ja", 1, per_ep=1), _stats(1), pitch=jr.Pitch("ja"), memo=fewer)
    fewer.save()
    kept = json.load(open(path, encoding="utf-8"))
    assert len(kept["m"]) == 1 and len(kept["p"]) == 1             # only the one word this page shows


def test_an_empty_library_writes_an_empty_memo_and_a_valid_page(tmp_path):
    for language in LANGUAGES:
        memo = jr.WordMemo(str(tmp_path / f"{language}.json"), *jr.memo_keys(language))
        out = jr.build(language, [], [], pitch=jr.Pitch(language, kanjium={}), memo=memo)
        memo.save()
        assert out.head["eps"] == [] and out.chunks == [] and "meanings" not in out.blobs


# --- the list CSVs, without pandas --------------------------------------------------------------------------- #

def _write_csv(path, header, lines, newline):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator=newline)
        w.writerow(header)
        w.writerows(lines)


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_the_list_csv_keeps_a_word_spelled_like_nothing_or_a_number(tmp_path, newline):
    """pandas read "NA", "null" and "1" as NaN / a number; the page must show them as the words they are."""
    path = str(tmp_path / "progressive_learning_list.csv")
    header = ["Sequence", "Source File", "Word", "Reading", "Occurrences (Global)", "Context 1", "Src 1", "Score"]
    lines = [[1, "ep01.srt", "NA", "", 3, "NAって何？", "Show/ep01.srt", 9],
             [2, "ep01.srt", "null", "", "", "nullの話", "Show/ep01.srt", 9],
             [3, "ep01.srt", "1", "イチ"]]                           # a short line: its missing cells are empty
    _write_csv(path, header, lines, newline)
    rows = jr._records(path)
    assert [r["Word"] for r in rows] == ["NA", "null", "1"]
    assert "Score" not in rows[0] and "Sequence" not in rows[0]      # only the columns the page reads
    assert rows[2]["Context 1"] == "" and rows[1]["Occurrences (Global)"] == ""
    assert jr._num(rows[1]["Occurrences (Global)"]) == 0 and jr._text(rows[2]["Src 1"]) == ""
    assert rows[0]["Src 1"] is rows[1]["Src 1"]                      # a repeated path held once
    assert jr._records(str(tmp_path / "none.csv")) is None


def test_a_blank_line_is_no_row_and_a_count_written_as_nan_is_no_count(tmp_path):
    # A list ending in two newlines (or a blank line inside) must not become a word with no spelling; a count
    # cell reading "nan" / "inf" is an empty one, never a crash at int().
    path = str(tmp_path / "progressive_learning_list.csv")
    header = ["Sequence", "Source File", "Word", "Reading", "Occurrences (File)", "Context 1", "Src 1"]
    _write_csv(path, header, [[1, "ep01.srt", "冒険", "ボウケン", "nan", "冒険の始まり", "Show/ep01.srt"], [],
                              [1, "ep01.srt", "準備", "ジュンビ", "inf", "準備はいい？", "Show/ep01.srt"], []],
               chr(13) + chr(10))                                  # [] is a blank line
    rows = jr._records(path)
    assert [r["Word"] for r in rows] == ["冒険", "準備"]
    assert jr._num("nan") == 0 and jr._num("inf", 5) == 5
    out = jr.build("ja", rows, _stats(1), pitch=jr.Pitch("ja", kanjium={}))
    words = [w for chunk in out.chunks for w in _decode(chunk)["w"]]
    assert [w[0] for w in words] == ["冒険", "準備"] and all(w[7] == 0 for w in words)


def test_the_priority_csv_keeps_only_the_four_columns_its_order_and_owners_need(tmp_path):
    path = str(tmp_path / "priority_learning_list.csv")
    _write_csv(path, ["Word", "Orth", "Forms", "Reading", "Context 1", "Src 1"],
               [[w, w, w, r, "文", "a.srt"] for w, r in WORDS["ja"][:3]], "\n")
    rows = jr._records(path, jr.PRIORITY_COLUMNS, contexts=False)
    assert [r["Word"] for r in rows] == [w for w, _r in WORDS["ja"][:3]] and set(rows[0]) == jr.PRIORITY_COLUMNS


# --- the learner's Kanjium copy: read only when it is there, only for unidic's misses -------------------------- #

def test_no_kanjium_copy_is_never_opened_and_a_miss_is_no_pitch(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKI_MINER_HOME", str(tmp_path))
    monkeypatch.setattr(own_dicts, "kanjium", lambda *a, **k: pytest.fail("read a copy that isn't there"))
    pitch = jr.Pitch("ja")
    pitch.prepare([("ぬるぽ語", "ヌルポゴ"), ("準備", "ジュンビ")])
    assert pitch.of("ぬるぽ語", "ヌルポゴ") is None and pitch.of("準備", "ジュンビ")


def test_the_page_holds_the_cards_pitch_the_copy_first_then_the_cards_unidic_rule(tmp_path, monkeypatch):
    # One rule with the card (Anki Miner fills PitchPosition from Kanjium; Backfill's アクセント fill takes UniDic only
    # for an empty field, by modules/junban/readings.pitch): where the two disagree the page shows the card's.
    folder = tmp_path / "pitch" / "kanjium-pitch"
    folder.mkdir(parents=True)
    (folder / "source.txt").write_text("準備\tじゅんび\t(名)3\nぬるぽ語\tヌルポゴ\t(名)2,0\n他\tた\t1\n",
                                       encoding="utf-8")         # 準備 3 here, UniDic's 1: the copy must win
    monkeypatch.setenv("ANKI_MINER_HOME", str(tmp_path))
    readings = pytest.importorskip("modules.junban.readings")
    pitch = jr.Pitch("ja")
    pitch.prepare([("準備", "ジュンビ"), ("ぬるぽ語", "ヌルポゴ"), ("授業", "ジュギョウ"), ("東京", "トウキョウ")])
    assert pitch.of("準備", "ジュンビ") == "k:3" and pitch.of("ぬるぽ語", "ヌルポゴ") == "k:2,0"
    card, _why = readings.pitch("授業", "ジュギョウ", pitch.tagger)
    assert card and pitch.of("授業", "ジュギョウ") == card                # not in the copy: the card's UniDic rule
    assert pitch.of("東京", "トウキョウ") is None                       # a name: no UniDic pitch, as on the card
    assert own_dicts.kanjium(str(tmp_path), words={"他"}) == {"他": {"た": "1"}}
    # The memo keeps UniDic's answers only: the copy is the learner's own data, and results/ goes out with Send
    # report when its tick is on — a warm render reads the copy again and still shows the card's pitch.
    path = str(tmp_path / jr.WORD_MEMO)
    memo = jr.WordMemo(path, *jr.memo_keys("ja"))
    jr.Pitch("ja").prepare([("準備", "ジュンビ"), ("ぬるぽ語", "ヌルポゴ")], memo=memo)
    memo.save()
    assert "k:" not in open(path, encoding="utf-8").read()
    warm = jr.Pitch("ja")
    warm.prepare([("準備", "ジュンビ"), ("ぬるぽ語", "ヌルポゴ")], memo=jr.WordMemo(path, *jr.memo_keys("ja")))
    assert warm.of("準備", "ジュンビ") == "k:3" and warm.of("ぬるぽ語", "ヌルポゴ") == "k:2,0"


def test_without_junban_a_word_has_only_the_copys_pitch_and_the_page_still_renders(monkeypatch):
    # Junban is a module: the core render must run without it (no UniDic pitch then, never an error).
    import sys
    monkeypatch.setitem(sys.modules, "modules.junban", None)
    pitch = jr.Pitch("ja", kanjium={})
    pitch.prepare([("準備", "ジュンビ")])
    assert pitch.of("準備", "ジュンビ") is None
    assert jr.build("ja", _rows("ja", 2), _stats(2), pitch=jr.Pitch("ja", kanjium={})).chunks


# --- the shipped tables, streamed ------------------------------------------------------------------------------- #

def test_the_streamed_table_is_the_whole_table_and_a_cut_one_ends_without_hanging():
    from app import kanji_data
    whole = lzma.decompress(base64.b64decode(kanji_data.DATA)).split(b"\n")
    assert list(jr._table_lines(kanji_data, piece=4096)) == whole
    packed = lzma.compress("\n".join(f"{c}\t{i}" for i, c in enumerate("冒険文化祭準備授業")).encode("utf-8"))
    cut = types.SimpleNamespace(DATA=base64.b64encode(packed[:len(packed) // 2]).decode())
    assert isinstance(list(jr._table_lines(cut, piece=8)), list)

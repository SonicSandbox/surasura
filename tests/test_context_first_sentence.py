"""Context 1 is the sentence the learner first meets the word in (Sonic 2026-11-06: "Context 1 always promises the
first-meeting line").

The pick looks at a word's sentences and stops once it holds enough clean ones (twice the slots with recency on: 6 by
default). The first sentence was pinned to Context 1 only when the pick had reached it, so a first sentence the pool
kept behind 6 clean ones — its cost at the time the walk met it was higher (the word said twice in it, with a rarer word
beside it) — never showed, and a later sentence stood in for it (Haya-D's measurement: 1–8 % of words; 航空's first
sentence lost to a later one). Outside *Only i+1* the first sentence is looked at first now; under *Only i+1* a first
sentence with an unknown is skipped by design. Since F7 (ENGINE 36) the pick weighs every candidate (no early exit), so
under *Only i+1* an i+1 first sentence is one more candidate, and wins among equals as the nearest.

Every fixture below is built so the first sentence sits LAST in the pool, behind 8 clean sentences: each test of the
rule was red on the code before #297's fix (checked by hand when they were written).
"""

import csv
import json
from unittest.mock import patch

import pytest

from app import analyzer

# Japanese: 灯台 is said twice in its first sentence, beside two words still new at its place on the list (蜃気楼,
# 見える) — so the walk files that sentence after 8 clean ones, and it has unknowns.
JA_FIRST = "灯台から灯台へ、珍しい蜃気楼が見えました。"
JA_CLEAN = [
    "私は毎日その灯台を見ます。",
    "夜の灯台はとても静かでした。",
    "白い灯台が海の近くにあります。",
    "朝の灯台はとても白いです。",
    "古い灯台が丘にあります。",
    "遠くの灯台が夜に光ります。",
    "海の灯台はとても古いです。",
    "私の友達は灯台が好きです。",
]
JA_OTHER = ["友達と一緒に灯台を見ました。", "父は灯台の話が好きでした。"]     # one new word each
JA_KNOWN = ["私", "毎日", "海", "見る", "行く", "友達", "一緒", "夜", "静か", "白い", "近く", "ある", "とても", "朝",
            "父", "話す", "好き", "古い", "立つ", "丘", "上", "光る", "遠く", "する", "だ", "です", "ます", "た", "の",
            "は", "を", "に", "で", "と", "が", "も", "から", "へ", "珍しい", "その"]

ZH_FIRST = "从灯塔到灯塔，出现了罕见的海市蜃楼。"
ZH_CLEAN = [
    "我每天早上都去海边看灯塔。",
    "晚上的灯塔非常安静。",
    "海边附近有一座白色的灯塔。",
    "那座古老的灯塔在山上。",
    "远处的灯塔在晚上很亮。",
    "我的朋友非常喜欢灯塔。",
    "这座灯塔非常高，很漂亮。",
    "他每天早上都在灯塔附近。",
]
ZH_KNOWN = ["我", "每天", "都", "去", "看", "海边", "的", "很", "安静", "晚上", "白色", "在", "附近", "有", "早上",
            "朋友", "喜欢", "这", "那", "座", "古老", "山上", "远处", "亮", "了", "是", "我们", "他", "她", "非常", "从",
            "到", "出现", "罕见", "一", "高", "漂亮", "小", "我的"]


def _library(root, language, files, known):
    high = root / "data" / language / "HighPriority"
    high.mkdir(parents=True)
    uf = root / "User Files" / language
    uf.mkdir(parents=True)
    (root / "results").mkdir()
    (uf / "KnownWord.json").write_text(json.dumps(
        {"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in known]}, ensure_ascii=False), encoding="utf-8")
    for name, text in files.items():
        (high / name).write_text(text, encoding="utf-8")
    return root


def _episodes(first, clean, other=()):
    """The first sentence in the first file (files are walked in name order), then one sentence a file."""
    files = {"ep01.txt": first}
    for i, text in enumerate(list(clean) + list(other)):
        files[f"ep{i + 2:02d}.txt"] = text
    return files


def _run(root, language, extra=()):
    """A real Generate over `root` only (the analyzer's own bound names patched, as tests/test_audio_example.py does)."""
    results = root / "results"
    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(root / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda l=None: str(root / "data" / l) if l else str(root / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(root / "User Files" / l) if l else str(root / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", language, "--min-freq", "1"] + list(extra)):
        analyzer.main()
    path = results / "priority_learning_list.csv"
    with open(path, encoding="utf-8-sig") as f:
        return {r["Word"]: r for r in csv.DictReader(f)}


def _contexts(row, n=3):
    return [(row.get(f"Context {i}") or "").strip() for i in range(1, n + 1)]


@pytest.mark.parametrize("language, word, first, clean, known", [
    ("ja", "灯台", JA_FIRST, JA_CLEAN, JA_KNOWN),
    ("zh", "灯塔", ZH_FIRST, ZH_CLEAN, ZH_KNOWN),
], ids=["ja", "zh"])
def test_context_1_is_the_first_sentence_even_behind_six_clean_ones_and_with_a_new_word(
        tmp_path, language, word, first, clean, known):
    """The pick stops after 6 clean sentences, and the first one sat behind 8 of them: it is Context 1 all the same,
    new word and all, and Contexts 2–3 are the cleanest of the rest, in the pool's order."""
    root = _library(tmp_path, language, _episodes(first, clean, JA_OTHER if language == "ja" else ()), known)
    ctx = _contexts(_run(root, language)[word])
    assert ctx[0] == first, f"Context 1 should be where {word} is first met, got {ctx[0]!r}"
    assert ctx[1:] == clean[:2], "the other slots stay the cleanest sentences, as before"


def test_one_slot_is_the_first_sentence(tmp_path):
    """--max-contexts 1: the only slot is the first sentence (the pick then stops after 2 clean ones)."""
    root = _library(tmp_path, "ja", _episodes(JA_FIRST, JA_CLEAN, JA_OTHER), JA_KNOWN)
    row = _run(root, "ja", ["--max-contexts", "1"])["灯台"]
    assert row["Context 1"].strip() == JA_FIRST
    assert "Context 2" not in row


def test_only_i_plus_one_still_skips_a_first_sentence_with_a_new_word(tmp_path):
    """*Only i+1*: the first sentence has new words, so it is no example at all; the word keeps the cleanest ones."""
    root = _library(tmp_path, "ja", _episodes(JA_FIRST, JA_CLEAN, JA_OTHER), JA_KNOWN)
    row = _run(root, "ja", ["--only-i-plus-one"])["灯台"]
    ctx = _contexts(row)
    assert JA_FIRST not in ctx
    assert ctx == JA_CLEAN[:3]


def test_only_i_plus_one_weighs_an_i_plus_one_first_sentence_like_any_other(tmp_path):
    """*Only i+1* never pins the first sentence; it is one more candidate (F7: the pick weighs every one, no early
    exit). Here it is i+1 at 灯台's place, as clean as the others and in the file nearest the word's first meeting —
    its own —, so among equals it leads.

    景色 and 見える are said 15 times each, each in an i+1 sentence of its own (ep13, ep14), so both come before 灯台
    on the list, in *Only i+1* too: at 灯台's place the first sentence is i+1."""
    first = "灯台から灯台へ、美しい景色が見えました。"
    places = ["山", "川", "町", "森", "空", "島", "港", "村", "橋", "庭", "駅", "寺", "城", "湖", "谷"]
    files = _episodes(first, JA_CLEAN, JA_OTHER)
    files["ep13.txt"] = "".join(f"{p}の景色はきれいです。" for p in places)
    files["ep14.txt"] = "".join(f"{p}が見えます。" for p in places)
    root = _library(tmp_path, "ja", files, JA_KNOWN + ["美しい", "きれい"] + places)

    assert _contexts(_run(root, "ja")["灯台"])[0] == first, "outside *Only i+1* it is Context 1"
    (root / "results" / "priority_learning_list.csv").unlink()
    strict = _contexts(_run(root, "ja", ["--only-i-plus-one"])["灯台"])
    assert strict[0] == first, f"*Only i+1*: the nearest of equally clean sentences first: {strict}"
    assert set(strict[1:]) <= set(JA_CLEAN), strict



def test_only_i_plus_one_still_offers_a_first_sentence_too_long_for_the_pool(tmp_path):
    """A sentence over the hard cap (150 characters) is kept only as the word's first sentence, never in the pool:
    *Only i+1* still looks at it, so a word whose one i+1 sentence it is stays on the list (it was so before)."""
    first = "夜はとても静かで、" * 16 + "白い灯台が海の近くにあります。"
    assert len(first) > 150
    files = {"ep01.txt": first, "ep02.txt": "灯台の近くで珍しい蜃気楼を見ました。"}
    root = _library(tmp_path, "ja", files, JA_KNOWN)
    row = _run(root, "ja", ["--only-i-plus-one"]).get("灯台")
    assert row is not None, "灯台 has an i+1 sentence: its first one"
    assert row["Context 1"].strip() == first

def test_the_audio_slot_is_still_the_last_one(tmp_path):
    """--ensure-audio-example gives the LAST slot to a sentence you can hear, never Context 1: the first sentence (from
    a book here) stays first, the subtitle line takes slot 3, and no fourth column appears."""
    files = _episodes(JA_FIRST, JA_CLEAN, JA_OTHER)
    # Long (past preferred_max_chars), so the ordinary pick ranks it last: only the audio rule puts it in.
    line = "その夜、私は友達と一緒に海の近くにある古くて白い灯台を見に行きました、とても静かで、本当に美しい夜でした。"
    files["z_episode.srt"] = f"1\n00:00:01,000 --> 00:00:04,000\n{line}\n"
    root = _library(tmp_path, "ja", files, JA_KNOWN)
    row = _run(root, "ja", ["--max-contexts", "3", "--ensure-audio-example"])["灯台"]
    ctx = _contexts(row)
    assert ctx[0] == JA_FIRST
    assert ctx[1] == JA_CLEAN[0]
    assert ctx[2] == line and row["Src 3"].endswith(".srt")
    assert "Context 4" not in row


def test_a_phrase_rows_context_1_is_its_first_sentence(tmp_path):
    """A set phrase's row (気がする, Word 気が為る) picks through the same pass: its first sentence — the phrase said
    twice, beside a word still new (蜃気楼) — sat behind 9 clean ones, and is Context 1."""
    first = "そんな気がするし、蜃気楼を見た気がする。"
    clean = ["明日は彼が来る気がする。", "彼はまた来る気がする。", "何か変な気がするよ。", "今日は楽しくなる気がする。",
             "誰かが見ている気がする。", "また会える気がするね。", "どこか遠い音が聞こえる気がする。",
             "ずっと前からここにいる気がする。", "あの人を知っている気がする。"]
    known = ["私", "今日", "明日", "雨", "降る", "彼", "来る", "何か", "変", "そう", "そんな", "いい", "天気", "なる", "誰か",
             "見る", "いる", "会う", "楽しい", "思う", "また", "どこか", "遠い", "音", "聞こえる", "ずっと", "前", "ここ",
             "あの", "人", "知る", "だ", "です", "ます", "た", "の", "は", "を", "に", "で", "と", "が", "も", "から", "へ",
             "し", "気", "する", "よう", "な", "ね", "よ"]
    root = _library(tmp_path, "ja", _episodes(first, clean), known)
    ctx = _contexts(_run(root, "ja")["気が為る"])
    assert ctx[0] == first
    assert ctx[1:] == clean[:2]

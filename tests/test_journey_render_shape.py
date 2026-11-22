"""The journey v3 page's data (J-DATA; SPEC §5.1, its shape fixed in TheForge tracks/window/work/j-data/SHAPE.md):
`app/journey_render.build` from a Generate's outputs, Japanese and Chinese, with real lines from the bundled samples.

What a wrong answer would cost a learner: a page that never opens (NaN in its JSON, a `</script>` in a sentence), a
word shown twice or in the wrong episode, a chunk too heavy to open in a frame, a made-up pitch (平板 for a word nobody
knows), a growth bar with a "then" that never was, or the learner's own dictionary text where it must not go."""
import base64
import gzip
import json
import os
import re
import subprocess
import sys

import pytest

from app import journey_render as jr

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(REPO, "tests", "Test Resources")
# Real words and the samples' own lines (placed_episode.srt, night_market.srt)
WORDS = {"ja": [("冒険", "ボウケン"), ("文化祭", "ブンカサイ"), ("準備", "ジュンビ"), ("授業", "ジュギョウ"),
                ("大砲", "タイホウ"), ("校庭", "コウテイ"), ("展示", "テンジ"), ("気がつく", "キガツク")],
         "zh": [("夜市", ""), ("频道", ""), ("有名", ""), ("排队", ""), ("牛肉面", ""), ("珍珠", ""),
                ("欢迎", ""), ("台北", "")]}
SAMPLE = {"ja": "placed_episode.srt", "zh": "night_market.srt"}


def _lines(language):
    with open(os.path.join(RES, language, SAMPLE[language]), encoding="utf-8-sig") as f:
        return [l for l in f.read().splitlines() if l.strip() and not l[0].isdigit()]


def _rows(language, episodes, per_ep=2, sentences=3):
    """A progressive list: `episodes` files, `per_ep` new words each (cycling the real words, so later ones repeat
    and must be dropped), each with up to `sentences` of the sample's lines."""
    lines, words, rows = _lines(language), WORDS[language], []
    for e in range(episodes):
        for k in range(per_ep):
            word, reading = words[(e * per_ep + k) % len(words)]
            row = {"Sequence": e + 1, "Source File": f"ep{e + 1:02d}.srt", "Word": word, "Orth": word,
                   "Forms": f"{word}|{word}だ" if language == "ja" else word, "Reading": reading, "Kana": "",
                   "Occurrences (Global)": 6.0, "Occurrences (File)": 2.0, "Count (High)": 3.0, "Count (Low)": 1.0,
                   "Modality": "", "Score": 40.0}
            for n in range(1, sentences + 1):
                row[f"Context {n}"] = lines[(e + k + n) % len(lines)]
                row[f"Src {n}"] = f"Show/ep{(e + n) % episodes + 1:02d}.srt"
            rows.append(row)
    return rows


def _stats(episodes):
    return [{"File": f"ep{e + 1:02d}.srt", "Total Words": 400, "Known Count": 360, "Coverage (%)": 90.0}
            for e in range(episodes)]


class _NoPitch:
    def of(self, word, reading="", pinyin=""):
        return None if word == "大砲" else ("0" if pinyin == "" else "".join(c for c in pinyin if c.isdigit()))


def _decode(blob):
    return json.loads(gzip.decompress(blob).decode("utf-8"))


def _page(out):
    return "".join(jr.elements(out))


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_head_and_chunks_carry_each_word_once_at_its_first_episode(language):
    out = jr.build(language, _rows(language, 6), _stats(6), pitch=_NoPitch(), stamp=123)
    head = out.head
    assert head["v"] == jr.SHAPE and head["lang"] == language and head["stamp"] == "123"
    assert [e[1] for e in head["eps"]] == [f"ep{n:02d}.srt" for n in range(1, 7)]
    # 8 real words over 12 slots: the first four episodes teach them, the last two teach nothing new
    assert [e[7] for e in head["eps"]] == [2, 2, 2, 2, 0, 0]
    assert head["counts"] == {"eps": 6, "words": 8, "shows": 6, "with_new": 4}
    words = [w for chunk in out.chunks for w in _decode(chunk)["w"]]
    assert [w[0] for w in words] == [w for w, _r in WORDS[language]]
    for e, ep in enumerate(head["eps"]):
        assert all(words[i][5] == e for i in range(ep[8], ep[8] + ep[7]))
    assert head["chunks"] == [[0, 8]]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_page_json_is_utf8_never_ascii_escaped_and_never_nan(language):
    rows = _rows(language, 3)
    rows[0]["Kana"] = float("nan")                       # a CSV's empty cell, as pandas reads it
    rows[0]["Context 2"] = "</script><b>閉じない</b>"     # never closes the page's script
    rows[1]["Src 1"] = float("nan")
    out = jr.build(language, rows, _stats(3), pitch=_NoPitch())
    page = _page(out)
    assert "\\u" not in page.split('id="j-head">', 1)[1].split("</script>", 1)[0]
    assert "NaN" not in page
    assert page.count("</script>") == len(re.findall(r"<script ", page))
    head = json.loads(re.search(r'id="j-head">(.*?)</script>', page).group(1))
    assert head["eps"][0][2]                              # a shown title
    first = _decode(out.chunks[0])["w"]
    assert first[0][3] == ""                              # NaN -> empty kana, never "nan"
    assert first[0][9][1][0] == "</script><b>閉じない</b>"
    assert first[1][9][0][1:] == []                       # no source: the line carries its text alone
    json.loads(gzip.decompress(out.chunks[0]).decode("utf-8"), parse_constant=pytest.fail)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_an_empty_library_is_a_valid_page(language):
    out = jr.build(language, [], [], priority=[], pitch=_NoPitch())
    assert out.chunks == [] and out.head["eps"] == [] and out.head["shows"] == [] and out.head["chunks"] == []
    assert out.head["counts"] == {"eps": 0, "words": 0, "shows": 0, "with_new": 0}
    page = _page(out)
    assert 'id="j-head"' in page and 'id="j-c0"' not in page
    json.loads(re.search(r'id="j-head">(.*?)</script>', page).group(1))


def test_a_word_no_dictionary_knows_has_no_pitch_never_heiban():
    out = jr.build("ja", _rows("ja", 3), _stats(3), pitch=_NoPitch())
    words = {w[0]: w for w in _decode(out.chunks[0])["w"]}
    assert words["大砲"][8] is None and words["冒険"][8] == "0"


def test_real_pitch_from_unidic_and_none_for_an_unknown_word():
    pitch = jr.Pitch("ja", kanjium={})
    assert pitch.of("先生", "センセイ") == "3"
    assert pitch.of("箸", "ハシ") == "1" and pitch.of("橋", "ハシ") == "2"
    assert pitch.of("ゴニョゴニョスキー", "") is None          # unidic's unknown word: no data, never 0
    kanjium = jr.Pitch("ja", kanjium={"ゴニョゴニョスキー": {"ごにょごにょすきー": "(名)3"}})
    assert kanjium.of("ゴニョゴニョスキー", "ゴニョゴニョスキー") == "k:3"
    assert jr.Pitch("zh").of("夜市", "", "ye4 shi4") == "44"
    assert jr.Pitch("zh").of("夜市", "", "") is None


def test_chinese_words_take_their_pinyin_and_meaning_from_cc_cedict():
    out = jr.build("zh", _rows("zh", 2), _stats(2), pitch=jr.Pitch("zh"))
    words = {w[0]: w for w in _decode(out.chunks[0])["w"]}
    assert words["夜市"][2].lower().startswith("ye4") and words["夜市"][8] == "44"
    meanings = _decode(out.blobs["meanings"])
    assert any("market" in g for sense in meanings["0"] for g in sense[1])
    assert "kanji" not in out.blobs                      # the kanji hover is Japanese only


def test_japanese_meanings_and_kanji_for_the_page_words_only():
    known = ["冒頭", "危険", "準備運動", "文化"]
    out = jr.build("ja", _rows("ja", 2), _stats(2), pitch=_NoPitch(), known=known)
    meanings = _decode(out.blobs["meanings"])
    assert set(meanings) == {"0", "1", "2", "3"}
    assert any("adventure" in g for _pos, glosses in meanings["0"] for g in glosses)
    assert meanings["0"][0][0].startswith("noun")
    kanji = _decode(out.blobs["kanji"])
    assert set(kanji) == set("冒険文化祭準備授業")
    assert kanji["冒"][3] == "冒頭" and kanji["険"][3] == "危険" and kanji["授"][3] == ""
    assert "risk" in kanji["冒"][0]


def test_chunks_close_at_their_episode_cap_and_their_byte_cap(monkeypatch):
    monkeypatch.setattr(jr, "CHUNK_EPISODES", 2)
    out = jr.build("ja", _rows("ja", 4), _stats(4), pitch=_NoPitch())
    assert out.head["chunks"] == [[0, 4], [4, 4]]
    monkeypatch.setattr(jr, "CHUNK_EPISODES", 100)
    monkeypatch.setattr(jr, "CHUNK_BYTES", 400)          # one episode alone past the cap: split across chunks
    out = jr.build("ja", _rows("ja", 1, per_ep=6), _stats(1), pitch=_NoPitch())
    assert len(out.chunks) > 1 and sum(n for _w0, n in out.head["chunks"]) == 6
    for (w0, n), chunk in zip(out.head["chunks"], out.chunks):
        body = _decode(chunk)
        assert body["w0"] == w0 and len(body["w"]) == n
        for word in body["w"]:                           # each chunk names its own sources
            assert all(line[1] < len(body["src"]) for line in word[9] if len(line) > 1)
        if n > 1:                                        # the cap counts the chunk's source table too
            assert len(gzip.decompress(chunk)) <= jr.CHUNK_BYTES + 64


def test_the_byte_cap_counts_the_source_rows_a_word_brings_not_only_the_word(monkeypatch):
    # Each line from a file of its own with a long title: the chunk's source table outweighs its words. Counting only
    # the words' JSON, a chunk would close far past the cap (the page's budget is the chunk's bytes, table and all).
    monkeypatch.setattr(jr, "CHUNK_BYTES", 1500)
    rows = _rows("ja", 1, per_ep=8)
    for i, row in enumerate(rows):
        for n in (1, 2, 3):
            row[f"Src {n}"] = f"{'とある魔術の禁書目録' * 6}/第{i * 3 + n:02d}話.srt"
    out = jr.build("ja", rows, _stats(1), pitch=_NoPitch())
    assert len(out.chunks) > 1
    for (_w0, n), chunk in zip(out.head["chunks"], out.chunks):
        if n > 1:
            assert len(gzip.decompress(chunk)) <= jr.CHUNK_BYTES + 64, len(gzip.decompress(chunk))


def test_the_sentence_cap_follows_sentences_per_word():
    settings = {"logic": {"context": {"max_contexts": 1}}}
    out = jr.build("ja", _rows("ja", 2), _stats(2), settings=settings, pitch=_NoPitch())
    assert out.head["settings"]["sentences"] == 1
    assert all(len(w[9]) == 1 for w in _decode(out.chunks[0])["w"])


def test_marks_follow_todays_rules_and_the_anki_icon_only_on_the_row_that_owns_the_card():
    assert jr.marks_of({"Count (High)": 3, "Count (Low)": 1, "Occurrences (Global)": 6}, {}) == 1
    assert jr.marks_of({"Count (High)": 6, "Count (Low)": 0, "Occurrences (Global)": 6}, {}) == 2
    assert jr.marks_of({"Count (High)": 0, "Count (Low)": 0, "Occurrences (Global)": 6, "Modality": "reading"}, {}) == 4
    rows = [{"Word": "口説く", "Reading": "クドク", "Orth": "口説く", "Forms": "くどい|口説い"},
            {"Word": "くどい", "Reading": "クドイ", "Orth": "くどい", "Forms": ""}]
    owners = jr.anki_owners(rows, "ja")
    # a くどい card is くどい's row, never also 口説く's (whose Forms hold くどい)
    assert jr.in_anki(rows[1], {"くどい"}, owners, "ja") and not jr.in_anki(rows[0], {"くどい"}, owners, "ja")
    # a katakana card reaches its hiragana row through the fold
    kana = [{"Word": "するり", "Reading": "スルリ", "Orth": "するり", "Forms": ""}]
    assert jr.in_anki(kana[0], {"するり"}, jr.anki_owners(kana, "ja"), "ja")


def test_the_store_facts_name_each_episode_by_its_id_with_its_show_state_and_growth():
    items = {7: {"id": 7, "rel_path": "Show/ep01.srt", "tier": "now", "work_id": 3, "parent_folder": "Show",
                 "watched": 1, "availability": "present", "ord": 1, "source_type": "subtitle"},
             8: {"id": 8, "rel_path": "Show/ep02.srt", "tier": "now", "work_id": 3, "parent_folder": "Show",
                 "watched": 0, "availability": "missing", "ord": 2, "source_type": "subtitle"},
             9: {"id": 9, "rel_path": "Book/ep03.srt", "tier": "soon", "work_id": None, "parent_folder": "Book",
                 "watched": 0, "availability": "present", "ord": 1, "source_type": "text"}}
    works = {3: {"id": 3, "title": "星屑ステーション", "media_type": "anime"}}
    growth = {7: {"added": {"known": 81, "counted": 100, "unknown": 40, "at": "2026-11-03T10:00:00", "prior": False},
                  "done": {"known": 96, "counted": 100, "unknown": 9, "at": "2026-11-09T10:00:00", "prior": False},
                  "last": {"known": 97, "counted": 100, "unknown": 7, "at": "2026-11-21T10:00:00", "prior": False}}}
    facts = jr.StoreFacts(items, works, [7, 8, 9], {8: 2}, {8: ("2026-11-21T09:00:00", "press")}, growth, "e1")
    out = jr.build("ja", _rows("ja", 3), _stats(3), facts=facts, pitch=_NoPitch())
    eps = out.head["eps"]
    assert [e[0] for e in eps] == [7, 8, 9] and out.head["library"] == "e1"
    assert [out.head["shows"][e[3]][1] for e in eps] == ["星屑ステーション", "星屑ステーション", "Book"]
    assert out.head["shows"][0][3] == "sapphire" and [e[4] for e in eps] == [0, 0, 1]
    assert [e[9] for e in eps] == ["cut", "raw", "rock"]
    assert [e[10] for e in eps] == [1, 2 | 4, 0]
    assert eps[1][11] == ["2026-11-21", "press"] and eps[0][11] is None
    assert eps[0][12] == [81.0, 40, "2026-11-03", 0, 96.0, 9, "2026-11-09", 7]
    assert eps[1][12] is None and eps[2][12] is None     # no snapshot: no bar, never a made-up "then"


def test_set_aside_watched_items_keep_their_place_in_the_order():
    items = {i: {"id": i, "tier": "now", "ord": i, "watched": i == 2, "availability": "present"} for i in (1, 2, 3)}
    assert jr._with_aside([1, 3], items) == [1, 2, 3]
    items[4] = {"id": 4, "tier": "soon", "ord": 1, "watched": 1, "availability": "present"}
    assert jr._with_aside([1, 3], items) == [1, 2, 3, 4]


def test_yours_only_when_asked_and_a_failed_read_is_english_quietly():
    rows, stats = _rows("ja", 2), _stats(2)
    asked = []

    def own(keys):
        asked.append(keys)
        return {("冒険", "ボウケン"): ("大辞林", "危険を冒して行うこと。")}

    out = jr.build("ja", rows, stats, pitch=_NoPitch(), own=own)
    assert "yours" not in out.blobs and not asked       # English: never read
    out = jr.build("ja", rows, stats, settings={"journey_meanings": "yours_en"}, pitch=_NoPitch(), own=own)
    assert _decode(out.blobs["yours"]) == {"0": ["大辞林", "危険を冒して行うこと。"]}

    def broken(keys):
        raise OSError("locked")

    out = jr.build("ja", rows, stats, settings={"journey_meanings": "yours"}, pitch=_NoPitch(), own=broken)
    assert "yours" not in out.blobs and "meanings" in out.blobs


def test_the_frequent_order_is_an_index_list_of_the_words():
    rows = _rows("ja", 2)
    priority = list(reversed(rows)) + [{"Word": "未知", "Reading": "ミチ"}]
    out = jr.build("ja", rows, _stats(2), priority=priority, pitch=_NoPitch())
    assert out.head["orders"]["freq"] == [3, 2, 1, 0]


def test_write_page_puts_the_data_at_its_marker_once(tmp_path):
    out = jr.build("ja", _rows("ja", 2), _stats(2), pitch=_NoPitch())
    path = str(tmp_path / "page.html")
    jr.write_page(out, "<html><body><main></main>" + jr.MARKER + "<script>go()</script></body></html>", path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert jr.MARKER not in text and text.index('id="j-head"') < text.index("go()")
    with pytest.raises(ValueError):
        jr.write_page(out, "<html></html>", path)


def test_the_render_never_imports_qt_or_tk():
    code = ("import sys; import app.journey_render as j; j.build('ja', [], []); "
            "bad = [m for m in sys.modules if m.split('.')[0] in ('PyQt6', 'tkinter', '_tkinter')]; "
            "print(bad); sys.exit(1 if bad else 0)")
    done = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr

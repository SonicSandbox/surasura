"""A show's own name clues make its names one word, in that file alone (app/names.py § A show's own name clues).

A Netflix episode says who speaks — （柚葉） at the start of a line — and gives a name its reading (the ruby its player
showed, kept in the item's sidecar as "readings"; 陽向(ひなた) in a subtitle). Those are names in THAT file, whatever
the spelling is elsewhere: 紬 is 'pongee', 白鷺 an egret, 東雲 the dawn, and the tagger cuts 柚葉 into 柚 + 葉 and reads
it ゆずよう. Measured on a 25-episode Netflix season with Ignore names on: the names left on the list went from 24
rows (1,034 uses) to 15 (284), no word lost; a 2,000-file library of .srt files without labels reads in the same time.

The lines here are written for these tests in the shape Netflix's subtitles take (no show's own text).
"""
import json

import pytest

from app import analyzer, names, token_index
from app.path_utils import SIDECAR_SUFFIX


@pytest.fixture(autouse=True)
def _sanitized():
    analyzer.SANITIZE_JA = True         # as every Japanese run sets it (conftest restores the global)


def _transcript(body, title="第2話 放課後"):
    return (f"{title}\n雲の上の郵便屋さん |  | \nCaptions: ja (manual)\nhttps://www.netflix.com/watch/81234567\n\n"
            + "-" * 60 + "\n" + body + "\n")


EPISODE = "\n".join((
    "（柚葉）おはよう",
    "（紬）あっ 柚葉 おはよう",
    "（ゆずは）ゆずはっちって呼ばないで",
    "（白鷺）白鷺だよ 覚えてね",
    "（先生）席に着け",
    "（人形）こんにちは",
    "（母）ご飯よ",
    "（女子生徒）ねえ 聞いた？",
    "（２人）うわっ！",
    "（足音）",
    "紬って 本当に お人形みたい",
    "先生 おはようございます",
))


def _item(tmp_path, body=EPISODE, readings=None, name="雲の上の郵便屋さん S01E02 放課後 [netflix-81234567].txt"):
    path = tmp_path / name
    path.write_text(_transcript(body), encoding="utf-8")
    if readings is not None:
        (tmp_path / (path.stem + SIDECAR_SUFFIX)).write_text(
            json.dumps({"video_id": "81234567", names.SIDECAR_READINGS: readings}, ensure_ascii=False),
            encoding="utf-8")
    return str(path)


def _read(path):
    """(words as (lemma, surface) per line, clues): the file as the token store reads it."""
    facts = {}
    text = analyzer.extract_text(path, "ja", facts)
    tokenizer = analyzer.JapaneseTokenizer(library=False)
    sentences = list(tokenizer.tokenize_sentences(text, clues=facts.get("clues")))
    return [[(t[0], t[2]) for t in tokens] for _s, tokens in sentences], facts.get("clues")


def _surfaces(read):
    return [surface for line in read for _lemma, surface in line]


def _lemmas(read):
    return [lemma for line in read for lemma, _surface in line]


# --- which labels name a person --------------------------------------------------------------------------------- #
def test_the_labels_that_name_people_and_never_the_roles_or_the_sounds(tmp_path):
    """A label names a person when JMnedict spells a person so and the spelling is no common word first: 柚葉, 紬,
    ゆずは, 白鷺. Roles never — 先生 and 人形 are common words before they are names, 母 and 女子生徒 no names at all —
    nor a number (２人), nor a group alone on its line (a sound: （足音））."""
    clues = names.file_clues(_transcript(EPISODE))
    assert set(clues["n"]) == {"柚葉", "紬", "ゆずは", "白鷺"}, clues


def test_a_label_name_is_one_word_and_keyed_by_its_reading(tmp_path):
    """柚葉 is one word, not 柚 + 葉; ゆずは is one, not ゆず + は; each keyed by its reading in katakana, as UniDic keys a
    person's name."""
    read, _clues = _read(_item(tmp_path))
    assert "柚葉" in _surfaces(read) and "柚" not in _surfaces(read)
    assert ("ユズハ", "ゆずは") in [w for line in read for w in line]


def test_a_role_label_leaves_its_word_a_word(tmp_path):
    """（先生） names a role: 先生 said in a line stays the word 先生; お人形 stays a doll."""
    read, _clues = _read(_item(tmp_path))
    assert "先生" in _lemmas(read) and "人形" in _lemmas(read)


def test_never_right_after_the_prefix_o(tmp_path):
    """（PROVISIONAL）A name never takes the prefix お / ご: a label's spelling written after one is the word."""
    body = "（紬）おはよう\nお紬を 着てきたの"
    read, clues = _read(_item(tmp_path, body))
    assert "紬" in clues["n"]
    assert ("ツムギ", "紬") not in [w for line in read[1:] for w in line]


# --- readings the file gives ------------------------------------------------------------------------------------- #
def test_the_sidecars_reading_makes_a_name_the_tagger_misreads(tmp_path):
    """The sidecar's readings (the ruby Netflix showed): 陽向 read ひなた is a name — JMnedict reads it so, the tagger
    says ひむき and cuts it — and keyed ヒナタ. A reading JMnedict doesn't have for the spelling is no clue."""
    body = "陽向 早く来て\n大丈夫だよ 陽向\n今日は 晴天なり"
    read, clues = _read(_item(tmp_path, body, readings={"陽向": "ひなた", "晴天": "はれぞら"}))
    assert clues["n"] == {"陽向": "ヒナタ"}
    assert ("ヒナタ", "陽向") in [w for line in read for w in line]


def test_a_reading_in_parentheses_in_a_subtitle_is_a_clue_too(tmp_path):
    """An .srt written from Netflix's subtitles keeps the ruby as 柚葉(ゆずは): that file's 柚葉 is one name."""
    path = tmp_path / "雲の上 01.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\n柚葉(ゆずは) おはよう\n\n2\n00:00:03,000 --> 00:00:04,000\n"
                    "柚葉 遅いよ\n", encoding="utf-8")
    read, clues = _read(str(path))
    assert clues["n"] == {"柚葉": "ユズハ"}
    assert _surfaces(read).count("柚葉") == 2


def test_no_sidecar_and_no_reading_change_nothing(tmp_path):
    """A transcript without a sidecar, or one without readings, reads from its labels alone."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert _read(_item(tmp_path / "a"))[1] == _read(_item(tmp_path / "b", readings={}))[1] is not None


def test_a_label_with_a_space_before_its_line_and_a_reading_after_other_kanji(tmp_path):
    """（柚葉） はい — a rip's space after the label — still names her; 二年生柚葉(ゆずは): the reading is the name's at the
    run's end, never 二年生柚葉 whole."""
    clues = names.file_clues("（紬） はい\n二年生柚葉(ゆずは)です\n")
    assert clues["n"] == {"紬": "ツムギ", "柚葉": "ユズハ"}


# --- nicknames --------------------------------------------------------------------------------------------------- #
def test_a_nickname_after_o_is_left_as_read(tmp_path):
    """（PROVISIONAL）Never after お / ご, a nickname as much as a name; the line reads as the tagger reads it."""
    body = "（ゆずは）おはよう\nおゆずはっちが来た"
    read, _clues = _read(_item(tmp_path, body))
    assert "ゆずはっち" not in _surfaces(read)
    assert "".join(_surfaces(read[1:])) .replace("。", "") in "おゆずはっちが来た", "every character of the line kept"


def test_a_nickname_is_cut_out_of_the_line_first(tmp_path):
    """A name's reading + ちん / っち in hiragana is ONE name: ゆずは's label gives the reading; 遠野, written in the file,
    gives とおの (JMnedict reads it so). The rest of the line is read as before."""
    body = "（ゆずは）おはよう\nゆずはっちも 来たの？\n遠野が来た\nとおのっち 遅い"
    read, clues = _read(_item(tmp_path, body))
    assert {"ゆずは", "とおの"} <= set(clues["k"])
    assert "ゆずはっち" in _surfaces(read) and "とおのっち" in _surfaces(read)
    assert "来る" in _lemmas(read) and "遅い" in _lemmas(read)


# --- per file, and never a key a common word has ------------------------------------------------------------------ #
def test_a_name_in_one_show_is_a_word_in_another(tmp_path):
    """Per file only: 白鷺 is a name where a label says so, and an egret in another file — keyed apart (シラサギ is
    no common word's lemma), so Ignore names, which ignores lemmas library-wide, never hides the bird."""
    named, _ = _read(_item(tmp_path))
    other = tmp_path / "野鳥の本.txt"
    other.write_text("白鷺が 川辺に降りた。\n", encoding="utf-8")
    plain, clues = _read(str(other))
    assert clues is None
    assert ("シラサギ", "白鷺") in [w for line in named for w in line]
    assert ("白鷺", "白鷺") in [w for line in plain for w in line]


def test_ignore_names_counts_the_files_names_as_names(tmp_path):
    """What the token store records of the file's names — the lemmas Ignore names ignores — holds the label names'
    keys, never a common word's lemma."""
    facts = {}
    text = analyzer.extract_text(_item(tmp_path), "ja", facts)
    record = names.Record()
    record.clues = facts["clues"]
    list(analyzer.JapaneseTokenizer(library=False).tokenize_sentences(text, names=record, clues=record.clues))
    found = set(names.name_words([record.data()]))
    assert {"ユズハ", "ツムギ", "シラサギ"} <= found
    assert not found & {"白鷺", "紬", "先生", "人形"}
    assert record.data()["w"] == facts["clues"], "kept with the record: a file read back from its sentences reads alike"


def test_a_file_with_no_clue_reads_exactly_as_before(tmp_path):
    """No label, no reading: no clues, and the words are the tokenizer's own, token for token."""
    path = tmp_path / "日記.txt"
    path.write_text("柚葉と紬を買った。\n白鷺が飛ぶ。\n", encoding="utf-8")
    read, clues = _read(str(path))
    assert clues is None
    plain = [[(t[0], t[2]) for t in tokens] for _s, tokens in
             analyzer.JapaneseTokenizer(library=False).tokenize_sentences(analyzer.extract_text(str(path), "ja"))]
    assert read == plain


def test_chinese_is_untouched(tmp_path):
    """The rule is Japanese: a Chinese transcript gives no clues and reads as before."""
    path = tmp_path / "校园日记 [netflix-81234999].txt"
    path.write_text(_transcript("（小明）你今天怎么这么早？\n（小红）因为我想先复习一下"), encoding="utf-8")
    facts = {}
    analyzer.extract_text(str(path), "zh", facts)
    assert "clues" not in facts


def test_the_rebuilt_text_of_a_gone_file_keeps_its_clues():
    """A file gone from the disk is kept as its sentences; its clues ride on its record ("w"), so it reads again with
    them."""
    clues = {"n": {"柚葉": "ユズハ"}, "k": []}
    _text, facts = token_index._rebuilt_text([("柚葉 おはよう", [])], {"w": clues})
    assert facts["clues"] == clues


# --- Connect's reader -------------------------------------------------------------------------------------------- #
def test_connects_cue_reader_reads_the_names_as_the_store_does(tmp_path):
    """A subtitle's cues, read for a card, give the same words as a Generate: 柚葉 one word in both."""
    from app import cues
    path = tmp_path / "雲の上 02.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\n（柚葉）おはよう\n\n2\n00:00:03,000 --> 00:00:04,000\n"
                    "（紬）柚葉 遅いよ\n", encoding="utf-8")
    read = cues.read(str(path), "ja")
    words = [(t.lemma, t.surface) for t in cues.tokens(read, "ja")]
    store, _clues = _read(str(path))
    assert words == [w for line in store for w in line]
    assert ("ユズハ", "柚葉") in words

"""Card translations through Piyo (`app/card_translations.py`, Piyo-TR): which cards want one, the lines around each
card's sentence from the source Surasura knows, the check every answer passes (after Mattias's anki-sentence-translate,
MIT), the write through the one field writer, and its Undo.

What a wrong answer would cost: a translation written over the learner's own (or into the wrong field) loses his work
or breaks his card; a bad answer let through (two bolds, the Japanese left in, markup) shows on every review; the wrong
neighbouring lines (another episode's, a repeated line's other place) mislead the AI; a card of another language
offered wastes his AI's turn; an Undo of another path's record takes back audio.

Real data: the public-domain 蜘蛛の糸 / ごん狐 texts and the 喫茶店の朝 subtitle in `samples/ja/`, the 杜子春 line-up
subtitle in `tests/Test Resources/ja/audiobook_sync/`; notes shaped as Lapis cards; Anki is a fake answering as
AnkiConnect does.
"""
import os
import shutil
import sqlite3

import pytest

from app import card_translations as ct
from app.connect import sentence_audio as sa
from app.connect.ledger import Ledger
from tests.connect.test_sentence_audio import FakeAnki

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "samples", "ja")
SPIDER = os.path.join(SAMPLES, "HighPriority", "蜘蛛の糸（芥川龍之介）.txt")
CAFE = os.path.join(SAMPLES, "HighPriority", "喫茶店の朝.srt")
LAPIS = ["Expression", "ExpressionReading", "Sentence", "SentenceAudio", "Picture", "Hint", "MiscInfo"]


class Reads(FakeAnki):
    """The fake with the reads `cards` makes: note types, their fields, findNotes by the query's terms."""

    def __init__(self):
        super().__init__()
        self.models = {}
        self.queries = []

    def put(self, nid, model, values, tags=()):
        self.notes_[nid] = {"noteId": nid, "modelName": model, "tags": list(tags),
                            "fields": {k: {"value": values.get(k, ""), "order": i}
                                       for i, k in enumerate(self.models[model])}}

    def note_types(self):
        return list(self.models)

    def fields(self, model):
        return list(self.models.get(model) or ())

    def find(self, query):
        self.queries.append(query)
        terms = {t.split(":", 1)[0].strip('"'): t.split(":", 1)[1].strip('"')
                 for t in query.replace('" "', '"\n"').split("\n")}
        model = terms.get("note")
        out = []
        for nid, n in self.notes_.items():
            if n["modelName"] != model:
                continue
            ok = True
            for k, v in terms.items():
                if k == "note":
                    continue
                if k == "tag":
                    ok &= any(t.lower().startswith(v.rstrip("*").lower()) for t in n["tags"])
                elif k == "deck":
                    ok &= n.get("deck") == v
                elif v == "":
                    ok &= n["fields"].get(k, {}).get("value") == ""
                elif v == "_*":
                    ok &= n["fields"].get(k, {}).get("value", "") != ""
            if ok:
                out.append(nid)
        return out

    def notes(self, ids):
        return [self.notes_.get(n, {}) for n in ids]


def _anki():
    anki = Reads()
    anki.models = {"Lapis": LAPIS, "Basic": ["Front", "Back"], "Mine": ["Word", "Sentence", "SentenceTranslation"]}
    return anki


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    yield book
    book.close()


# --- which field ------------------------------------------------------------------------------------------------ #
def test_the_translation_field_is_a_named_one_else_hint_only_on_the_lapis_family():
    """`SentenceTranslation` (any case) wins; `Hint` counts only beside Sentence + SentenceAudio (our layout's 翻訳):
    a note type of the learner's own with a `Hint` for something else is never written."""
    assert ct.translation_field(LAPIS) == "Hint"
    assert ct.translation_field(["Word", "Sentence", "sentencetranslation", "Hint"]) == "sentencetranslation"
    assert ct.translation_field(["Front", "Back", "Hint"]) is None
    assert ct.translation_field(["Front", "Back"]) is None


# --- which cards ------------------------------------------------------------------------------------------------ #
def test_cards_are_the_empty_translations_with_a_sentence_connects_first_then_the_newest():
    """Connect's cards first (the tag, any case), then the rest newest first; a filled Hint, an empty sentence, a
    note type with no translation field and a Chinese sentence in a Japanese session are never offered; the word is
    the sentence's bold."""
    anki = _anki()
    s = "御釈迦様は極楽の<b>蓮池</b>のふちを、独りでぶらぶら御歩きになっていらっしゃいました。"
    anki.put(10, "Lapis", {"Expression": "蓮池", "Sentence": s})
    anki.put(11, "Lapis", {"Expression": "地獄", "Sentence": "その<b>地獄</b>の底に、犍陀多と云う男が一人"},
             tags=["Surasura::connect::4b52091b-7"])
    anki.put(12, "Lapis", {"Expression": "糸", "Sentence": "蜘蛛の糸", "Hint": "his own"})
    anki.put(13, "Lapis", {"Expression": "空", "Sentence": ""})
    anki.put(14, "Lapis", {"Expression": "我们", "Sentence": "我们走吧。"})
    anki.put(15, "Basic", {"Front": "蜘蛛", "Back": "spider"})
    anki.put(16, "Mine", {"Word": "罪人", "Sentence": "ほかの罪人と一しょに"})
    got = ct.cards(anki, "ja", around=0)
    assert [c["id"] for c in got["cards"]] == [11, 16, 10]
    assert got["cards"][2] == {"id": 10, "sentence": ct.plain(s), "word": "蓮池"}
    assert got["cards"][1]["word"] == "罪人", "no bold: the word field"


def test_the_limit_holds_and_left_says_how_many_wait(ledger):
    anki = _anki()
    for n in range(1, 8):
        anki.put(n, "Lapis", {"Expression": "糸", "Sentence": f"蜘蛛の糸が{n}本、するすると下りてきた。"})
    got = ct.cards(anki, "ja", limit=3, around=0)
    assert [c["id"] for c in got["cards"]] == [7, 6, 5] and got["left"] == 4
    assert len(ct.cards(anki, "ja", limit=500, around=0)["cards"]) == 7, "MOST caps it, never more"


def test_chinese_cards_are_han_without_kana():
    anki = _anki()
    anki.put(1, "Lapis", {"Expression": "故乡", "Sentence": "我冒了严寒，回到相隔二千余里，别了二十余年的<b>故乡</b>去。"})
    anki.put(2, "Lapis", {"Expression": "糸", "Sentence": "蜘蛛の糸"})
    assert [c["id"] for c in ct.cards(anki, "zh", around=0)["cards"]] == [1]


# --- the lines around ------------------------------------------------------------------------------------------- #
def _library(tmp_path, files):
    """A ledger with Connect's made outcomes and a library store with the items' files: {note: (file, line s, text)}."""
    from app import library_store
    data = tmp_path / "data"
    lib = data / "Library"
    lib.mkdir(parents=True)
    db = library_store.library_db_path("ja", str(data))
    os.makedirs(os.path.dirname(db), exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, rel_path TEXT)")
    led = Ledger(str(tmp_path / "ledger.sqlite"))
    for k, (note, (src, start, sentence)) in enumerate(sorted(files.items()), 1):
        shutil.copy(src, lib / os.path.basename(src))
        conn.execute("INSERT INTO items VALUES (?, ?)", (k, "Library/" + os.path.basename(src)))
        led.conn.execute("INSERT INTO jobs (language, item_id, state, created_at, updated_at) VALUES "
                         "('ja', ?, 'done', 'x', 'x')", (k,))
        job = led.conn.execute("SELECT max(id) FROM jobs").fetchone()[0]
        led.conn.execute("INSERT INTO outcomes (job_id, word, reading, line_start, sentence, outcome, note_id, "
                         "attempt) VALUES (?, ?, '', ?, ?, 'made', ?, 1)", (job, f"w{note}", start, sentence, note))
    conn.commit()
    conn.close()
    led.close()
    return str(tmp_path / "ledger.sqlite"), str(data)


def test_a_subtitle_cards_neighbours_are_the_cues_just_before_and_after(tmp_path):
    """The café dialogue: the card's line is found by its text; ±1 gives the cue before and after, ±2 two each."""
    from app import cues
    lines = [c.text for c in cues.read(CAFE, "ja") if c.counted]
    k = 5
    src = _library(tmp_path, {101: (CAFE, None, lines[k])})
    one = ct.context([101], "ja", 1, *src)
    assert one == {101: ([lines[k - 1]], [lines[k + 1]])}
    two = ct.context([101], "ja", 2, *src)
    assert two[101] == (lines[k - 2:k], lines[k + 1:k + 3])
    assert ct.context([101], "ja", 0, *src) == {}


def test_a_line_said_twice_is_placed_by_its_time_not_its_first_place(tmp_path):
    """A short line in a subtitle twice: the card's own place is the one nearest its line's start."""
    srt = tmp_path / "twice.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nいらっしゃいませ。\n\n2\n00:00:03,000 --> 00:00:04,000\n"
                   "はい。\n\n3\n00:00:05,000 --> 00:00:06,000\nコーヒーをください。\n\n4\n00:00:07,000 --> "
                   "00:00:08,000\nはい。\n\n5\n00:00:09,000 --> 00:00:10,000\n少々お待ちください。\n", encoding="utf-8")
    src = _library(tmp_path, {7: (str(srt), 7.0, "はい。")})
    assert ct.context([7], "ja", 1, *src)[7] == (["コーヒーをください。"], ["少々お待ちください。"])


def test_a_book_cards_neighbours_are_its_sentences_and_long_lines_are_cut_at_the_far_end(tmp_path):
    """蜘蛛の糸: a sentence the card holds as Anki Miner wrote it (spaces, line breaks and ruby out); its neighbours are
    the sentences before and after; a neighbour over LINE_MAX keeps its nearer end (before: its end; after: its
    start)."""
    lines = [t for _s, t in ct.lines_of(SPIDER, "ja")]
    k = next(i for i in range(1, len(lines) - 1) if len(lines[i - 1]) > ct.LINE_MAX and len(lines[i + 1]) > ct.LINE_MAX
             and len(lines[i]) > 10)
    src = _library(tmp_path, {5: (SPIDER, None, lines[k].replace("、", "、 "))})
    before, after = ct.context([5], "ja", 1, *src)[5]
    assert before == ["…" + lines[k - 1][-(ct.LINE_MAX - 1):]]
    assert after == [lines[k + 1][:ct.LINE_MAX - 1] + "…"]


def test_cards_surasura_didnt_make_get_their_sentence_alone(tmp_path):
    """Not in the ledger (or no ledger at all, or its file gone): no before / after, never a guess."""
    src = _library(tmp_path, {1: (CAFE, None, "nothing like it")})
    assert ct.context([1, 2], "ja", 1, *src) == {}
    assert ct.context([1], "ja", 1, str(tmp_path / "none.sqlite"), src[1]) == {}
    os.remove(os.path.join(src[1], "Library", os.path.basename(CAFE)))
    assert ct.context([1], "ja", 1, *src) == {}


def test_cards_hands_the_neighbours_on_with_the_card(tmp_path):
    from app import cues
    lines = [c.text for c in cues.read(CAFE, "ja") if c.counted]
    src = _library(tmp_path, {30: (CAFE, None, lines[3])})
    anki = _anki()
    anki.put(30, "Lapis", {"Expression": "x", "Sentence": lines[3]}, tags=["surasura::connect::a-1"])
    anki.put(31, "Lapis", {"Expression": "糸", "Sentence": "蜘蛛の糸"})
    got = ct.cards(anki, "ja", around=1, sources=src)["cards"]
    assert got[0]["before"] == [lines[2]] and got[0]["after"] == [lines[4]]
    assert "before" not in got[1] and "after" not in got[1]


# --- the check -------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("text, why", [
    ("", ct.EMPTY), ("   ", ct.EMPTY),
    ("The Buddha took the spider's thread.", ct.ONE_BOLD),
    ("The <b>Buddha</b> took the <b>spider</b>'s thread.", ct.ONE_BOLD),
    ("The Buddha took the <b>spider's thread.", ct.ONE_BOLD),
    ("The Buddha took the <b></b> thread.", ct.BOLD_EMPTY),
    ("The Buddha took the <b>蜘蛛</b>'s thread.", ct.BOLD_CJK),
    ("御釈迦様は<b>spider</b>の糸を取った。", ct.NOT_TRANSLATED),
    ("The Buddha took the <b>spider</b>'s <i>thread</i>.", ct.MARKUP),
    ("<b>spider</b> " + "and so on " * 50, ct.TOO_LONG.format(most=ct.TEXT_MOST)),
])
def test_a_bad_answer_is_refused_with_its_why(text, why):
    assert ct.check(text, "ja") == (None, why)


def test_a_good_answer_passes_escaped_and_a_cjk_target_language_keeps_its_bold():
    """One bold, its text escaped (an & or < of the AI's never becomes markup); into Chinese, the bold may be CJK."""
    assert ct.check("Tom & the <b>spider</b> said <hi>", "ja")[1] == ct.MARKUP
    assert ct.check("Tom &amp; the <b>spider</b> — 3 < 4", "ja") == ("Tom &amp; the <b>spider</b> — 3 &lt; 4", None)
    assert ct.check("佛祖拿起了<b>蜘蛛</b>的丝。", "ja", into="zh") == ("佛祖拿起了<b>蜘蛛</b>的丝。", None)
    assert ct.check("Kandata grabbed <B>the thread</B>.", "ja") == ("Kandata grabbed <b>the thread</b>.", None)


# --- the write and its Undo ------------------------------------------------------------------------------------- #
def test_write_checks_each_answer_and_writes_the_good_ones_in_one_batch_with_one_undo(ledger):
    """Good answers go into each note's own translation field (Lapis Hint, another's SentenceTranslation) in ONE
    writer call; a bad answer, a note gone, a note type with no translation field and a field filled meanwhile are
    each refused with why; the Undo takes the batch back."""
    anki = _anki()
    anki.put(1, "Lapis", {"Expression": "糸", "Sentence": "蜘蛛の<b>糸</b>"})
    anki.put(2, "Mine", {"Word": "罪人", "Sentence": "ほかの罪人と一しょに"})
    anki.put(3, "Lapis", {"Expression": "地獄", "Sentence": "地獄の底"})
    anki.put(4, "Basic", {"Front": "蜘蛛", "Back": "spider"})
    anki.put(5, "Lapis", {"Expression": "蓮", "Sentence": "蓮池のふち", "Hint": "typed meanwhile"})
    got = ct.write(anki, anki, ledger, [
        {"id": 1, "translation": "The spider's <b>thread</b>"},
        {"id": 2, "translation": "Together with the other <b>sinners</b>"},
        {"id": 3, "translation": "The bottom of hell"},
        {"id": 4, "translation": "A <b>spider</b>"},
        {"id": 5, "translation": "The edge of the <b>lotus</b> pond"},
        {"id": 9, "translation": "A <b>ghost</b>"},
        {"translation": "no id"}, "junk"], "ja")
    assert got["written"] == [1, 2]
    assert got["refused"] == {3: ct.ONE_BOLD, 4: ct.NO_FIELD, 5: sa.HAS_TEXT.format(field="Hint"), 9: sa.GONE}
    assert anki.value(1, "Hint") == "The spider's <b>thread</b>"
    assert anki.value(2, "SentenceTranslation") == "Together with the other <b>sinners</b>"
    assert anki.value(5, "Hint") == "typed meanwhile"
    assert all(ct.TAG in anki.notes_[n]["tags"] for n in (1, 2))
    assert len([k for k in ledger.conn.execute("SELECT key FROM meta WHERE key LIKE 'sentence_audio:%'")]) == 1
    done = ct.undo(anki, ledger, got["undo"])
    assert done["emptied"] == [1, 2] and anki.value(1, "Hint") == "" and anki.value(2, "SentenceTranslation") == ""


def test_nothing_good_writes_nothing_and_another_paths_record_is_never_undone_here(tmp_path, ledger):
    anki = _anki()
    anki.put(1, "Lapis", {"Expression": "糸", "Sentence": "蜘蛛の糸", "SentenceAudio": ""})
    assert ct.write(anki, anki, ledger, [{"id": 1, "translation": "no bold"}], "ja") == {
        "undo": None, "written": [], "refused": {1: ct.ONE_BOLD}}
    assert anki.calls == [] or all(c[0] == "notes" for c in anki.calls)
    clip = tmp_path / "a.mp3"
    clip.write_bytes(b"ID3\x04audio")
    audio = sa.fill(anki, ledger, {1: str(clip)}, by="add-audio")
    assert ct.undo(anki, ledger, audio["id"])["refused"] == "nothing to undo"
    assert anki.value(1).startswith("[sound:"), "the audio stays"

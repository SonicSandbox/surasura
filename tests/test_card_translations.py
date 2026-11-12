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
    """The fake with the reads `cards` makes: note types, their fields and templates, findNotes by the query's terms
    (a field empty / not empty / matching `re:`, `-` for not, the note type, deck and tag) as Anki's search reads them."""

    def __init__(self):
        super().__init__()
        self.models = {}
        self.fronts = {}            # note type -> its front template (default: the word alone; ours shows Hint on the back)
        self.queries = []

    def put(self, nid, model, values, tags=()):
        self.notes_[nid] = {"noteId": nid, "modelName": model, "tags": list(tags),
                            "fields": {k: {"value": values.get(k, ""), "order": i}
                                       for i, k in enumerate(self.models[model])}}

    def note_types(self):
        return list(self.models)

    def fields(self, model):
        return list(self.models.get(model) or ())

    def templates(self, model):
        return {"Card 1": {"Front": self.fronts.get(model, "{{Expression}}"),
                           "Back": '{{#Hint}}<div class="tr-reveal">{{Hint}}</div>{{/Hint}}'}}

    def find(self, query):
        import re
        self.queries.append(query)
        terms = [(neg == "-", t.split(":", 1)[0], t.split(":", 1)[1]) for neg, t in re.findall(r'(-?)"([^"]*)"', query)]
        out = []
        for nid, n in self.notes_.items():
            ok = True
            for neg, k, v in terms:
                value = n["fields"].get(k, {}).get("value")
                if k == "note":
                    hit = n["modelName"] == v
                elif k == "tag":
                    hit = any(t.lower().startswith(v.rstrip("*").lower()) for t in n["tags"])
                elif k == "deck":
                    hit = n.get("deck") == v
                elif v == "":
                    hit = value == ""
                elif v == "_*":
                    hit = value not in (None, "")
                elif v.startswith("re:"):
                    hit = value is not None and re.search(v[3:], value) is not None
                else:
                    raise AssertionError(f"a search term the fake doesn't know: {k}:{v}")
                ok &= hit != neg
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


def test_a_long_sentences_translation_may_be_long_and_the_limit_follows_the_sentence(ledger):
    """A long book sentence (the eval: 237 characters took 405-591 in English) passes up to 3 characters a sentence
    character; a short line's answer stays under TEXT_MOST."""
    lines = [t for _s, t in ct.lines_of(SPIDER, "ja")]
    long_one = "".join(sorted(lines, key=len)[-2:])          # a card cut from a long passage (two sentences)
    assert len(long_one) * ct.PER_CHAR > ct.TEXT_MOST + 50
    anki = _anki()
    anki.put(1, "Lapis", {"Expression": "x", "Sentence": long_one})
    anki.put(2, "Lapis", {"Expression": "糸", "Sentence": "蜘蛛の糸"})
    text = "The <b>Buddha</b> " + "walked on, " * ((ct.TEXT_MOST + 30) // 11)
    assert ct.TEXT_MOST < len(text) < len(long_one) * ct.PER_CHAR
    got = ct.write(anki, anki, ledger, [{"id": 1, "translation": text}, {"id": 2, "translation": text}], "ja")
    assert got["written"] == [1] and got["refused"] == {2: ct.TOO_LONG.format(most=ct.TEXT_MOST)}


def test_a_card_filled_between_the_search_and_the_read_is_not_offered():
    """Anki's search says the field is empty; by the read it isn't (the learner typed one): never offered."""
    anki = _anki()
    anki.put(1, "Lapis", {"Expression": "糸", "Sentence": "蜘蛛の糸"})
    anki.put(2, "Lapis", {"Expression": "地獄", "Sentence": "地獄の底"})
    found = anki.find

    def find_then_type(query):
        got = found(query)
        anki.notes_[2]["fields"]["Hint"]["value"] = "typed just now"
        return got
    anki.find = find_then_type
    assert [c["id"] for c in ct.cards(anki, "ja", around=0)["cards"]] == [1]


# --- review r1 (Opus adversary) ---------------------------------------------------------------------------------- #
def test_a_hint_the_front_shows_is_never_a_translation_field_stock_lapis_is_left_alone(ledger):
    """r1 B1: stock Lapis shows Hint on the card's front — a translation there gives every review away. A note type
    whose front template shows the field (any {{…Hint}} form) is never offered and never written; a named
    translation field the front shows is passed over too."""
    templates = {"Card": {"Front": "{{Expression}}<div class=hint>{{#Hint}}{{furigana:Hint}}{{/Hint}}</div>", "Back": ""}}
    assert ct.on_front("Hint", templates) and not ct.on_front("Hint", {"Card": {"Front": "{{Expression}}"}})
    assert ct.translation_field(LAPIS, templates) is None
    assert ct.translation_field(LAPIS + ["SentenceTranslation"], {"C": {"Front": "{{SentenceTranslation}}"}}) == "Hint"
    anki = _anki()
    anki.fronts["Lapis"] = templates["Card"]["Front"]
    anki.put(1, "Lapis", {"Expression": "糸", "Sentence": "蜘蛛の<b>糸</b>"})
    assert ct.cards(anki, "ja", around=0)["cards"] == [] and ct.count(anki) == 0
    got = ct.write(anki, anki, ledger, [{"id": 1, "translation": "The spider's <b>thread</b>"}], "ja")
    assert got["written"] == [] and got["refused"] == {1: ct.NO_FIELD} and anki.value(1, "Hint") == ""


def test_write_holds_a_note_to_the_rules_a_card_is_offered_by(ledger):
    """r1 S2: an id the AI made up (or a card's text talked it into) lands nowhere else: a vocab note type's
    Translation field (no Sentence), a card with no sentence or one in another language — each refused, unwritten."""
    anki = _anki()
    anki.models["Vocab"] = ["Word", "Translation"]
    anki.put(1, "Vocab", {"Word": "蜘蛛"})
    anki.put(2, "Lapis", {"Expression": "空", "Sentence": ""})
    anki.put(3, "Lapis", {"Expression": "我们", "Sentence": "我们走吧。"})
    anki.put(4, "Lapis", {"Expression": "糸", "Sentence": "蜘蛛の<b>糸</b>"})
    got = ct.write(anki, anki, ledger, [{"id": n, "translation": "The <b>spider</b>."} for n in (1, 2, 3, 4)], "ja")
    assert got["written"] == [4]
    assert got["refused"] == {1: ct.NO_FIELD, 2: ct.NOT_OFFERED, 3: ct.NOT_OFFERED}
    assert anki.value(1, "Translation") == "" and anki.value(3, "Hint") == ""


def test_the_script_is_asked_of_ankis_search_so_other_languages_never_crowd_the_scan():
    """r1 S3: 600 newer Chinese cards in a Japanese session: the search itself leaves them out (re:), so the Japanese
    card behind them is still found and counted."""
    anki = _anki()
    for n in range(100, 700):
        anki.put(n, "Lapis", {"Expression": "故乡", "Sentence": f"我回到了故乡{n}。"})
    anki.put(1, "Lapis", {"Expression": "糸", "Sentence": "蜘蛛の糸が下りてきた。"})
    assert [c["id"] for c in ct.cards(anki, "ja", around=0)["cards"]] == [1]
    assert ct.count(anki, language="ja") == 1 and ct.count(anki, language="zh") == 600
    assert any("re:" in q for q in anki.queries)


def test_a_paragraph_card_is_not_offered_and_a_long_word_is_cut():
    """r1 S4: the answer stays bounded per card: a sentence over SENTENCE_MOST goes unoffered, the word at most
    WORD_MOST characters."""
    anki = _anki()
    text = "".join(t for _s, t in ct.lines_of(SPIDER, "ja"))
    assert len(text) > ct.SENTENCE_MOST
    anki.put(1, "Lapis", {"Expression": "x", "Sentence": text})
    anki.put(2, "Lapis", {"Expression": "糸" * 60, "Sentence": "蜘蛛の糸が下りてきた。"})
    got = ct.cards(anki, "ja", around=0)["cards"]
    assert [c["id"] for c in got] == [2] and len(got[0]["word"]) == ct.WORD_MOST


def test_an_odd_subtitle_file_gives_its_cards_their_sentence_alone_never_a_failed_call(tmp_path, monkeypatch):
    """r1 S5: one file the cue reader can't read (an .ass with no Style column raised KeyError): its card goes with
    its sentence alone, the call doesn't fail."""
    ass = tmp_path / "odd.ass"
    ass.write_text("[Events]\nFormat: Layer, Start, End, Text\nDialogue: 0,0:00:01.00,0:00:02.00,こんにちは。\n",
                   encoding="utf-8")
    src = _library(tmp_path, {9: (str(ass), 1.0, "こんにちは。")})
    monkeypatch.setattr(ct, "lines_of", lambda path, language: (_ for _ in ()).throw(KeyError("Style")))
    assert ct.context([9], "ja", 1, *src) == {}


def _book(tmp_path, text):
    path = tmp_path / "book.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_a_book_line_said_twice_or_found_inside_another_gets_no_wrong_neighbours(tmp_path):
    """r1 S7: a book has no times. はい。 twice: no neighbours rather than line 1's (a guess could name the wrong
    speaker); はい inside これはいけない。: never placed there — its own line's neighbours."""
    twice = _book(tmp_path, "ごんは、ひとりぼっちの小狐でした。\nはい。\n兵十がうなぎをとっていました。\nはい。\n村の方から、かんかん鐘が鳴ってきました。\n")
    src = _library(tmp_path, {1: (twice, None, "はい。")})
    assert ct.context([1], "ja", 1, *src) == {}
    inside = tmp_path / "in"
    inside.mkdir()
    once = _book(inside, "これはいけない。\nはい\nごんは、そっと草の中から出てきました。\n")
    src = _library(inside, {2: (once, None, "はい")})
    assert ct.context([2], "ja", 1, *src)[2] == (["これはいけない。"], ["ごんは、そっと草の中から出てきました。"])


def test_another_languages_job_is_never_read_for_a_card(tmp_path):
    """r1 N11: item ids are each language's store's: a Chinese job's outcome never gives a Japanese card neighbours."""
    from app import cues
    lines = [c.text for c in cues.read(CAFE, "ja") if c.counted]
    src = _library(tmp_path, {11: (CAFE, None, lines[4])})
    conn = sqlite3.connect(src[0])
    conn.execute("UPDATE jobs SET language = 'zh'")
    conn.commit()
    conn.close()
    assert ct.context([11], "ja", 1, *src) == {}


def test_a_sound_tag_or_a_cloze_is_refused_and_line_breaks_become_one_line():
    """r1 N10: [sound:…] in the field would play; {{c1::…}} is a cloze; the translation is one line."""
    assert ct.check("The <b>spider</b> [sound:x.mp3]", "ja") == (None, ct.MARKUP)
    assert ct.check("The {{c1::<b>spider</b>}}", "ja") == (None, ct.MARKUP)
    assert ct.check("The <b>spider</b>\nspun a thread.", "ja") == ("The <b>spider</b> spun a thread.", None)


def test_every_read_cards_makes_goes_through_without_the_write_lock():
    """The DevTest drill found it: `modelTemplates` was refused as a write (off READ_ACTIONS). Every action the read
    adapter sends is a read the client lets through with no lock held."""
    import json as _json
    from unittest import mock
    from app import anki_connect
    sent = []

    class _Reply:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        action = _json.loads(req.data)["action"]
        sent.append(action)
        result = {"modelNames": ["Lapis"], "modelFieldNames": LAPIS, "modelTemplates": {}, "findNotes": [],
                  "notesInfo": []}[action]
        return _Reply(_json.dumps({"result": result, "error": None}).encode())
    with mock.patch("urllib.request.urlopen", urlopen):
        reads = ct.AnkiReads(anki_connect.DEFAULT_URL)
        assert ct.cards(reads, "ja", around=0) == {"cards": [], "left": 0}
    assert {"modelNames", "modelFieldNames", "modelTemplates", "findNotes"} <= set(sent)
    assert set(sent) <= anki_connect.READ_ACTIONS

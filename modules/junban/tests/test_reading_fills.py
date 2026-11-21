# SPDX-License-Identifier: GPL-3.0-or-later
"""Backfill's ふりがな and アクセント fills (Kantan-PF, a learner's report 2026-11-21: a card with no furigana and no
pitch, あくまでも in 「メリット、か。お前は<b>あくまでも</b>損得で…」).

Why they exist: on Lapis the AJT add-on writes SentenceFurigana (and pitch Kanjium lacks) as a card is added — only
when no Anki window is in front. Five of Connect's batches in a row (11-09 12:27–12:32) were added with Anki in front:
13 cards with an empty SentenceFurigana and nothing to say so. Connect's own fill of the cards it makes now writes an
empty SentenceFurigana and an empty PitchPosition itself (`backfill.MAKING`, in `run_named`), whatever Backfill's ticks
say and in any deck; Backfill's own runs offer both for older cards.

What this file guards, most costly first:
  * a filled field — AJT's per-word colour, Anki Miner's pitch — is never touched: empty fields only;
  * Connect's run fills both on the 11-09 card's shape, with the ticks at their default (パターン only) and the card
    in a deck that isn't Backfill's, and Restore takes them back;
  * the furigana is Anki's own form (what `{{furigana:SentenceFurigana}}` reads), the `<b>` round the word kept;
  * pitch only for one word read as the card reads it — never a phrase, a name or a cry (measured: 95% on one word,
    52% / 60% for a compound / a phrase — those stay empty).

Real Japanese: lines of `tests/Test Resources/ja/readings_sample.srt` and the 杜子春 book; real Lapis field names.
"""
import os

import pytest

from modules.junban import backfill, readings
from modules.junban.tests.test_backfill import BackfillCollection, _patched, _settings

URL = "http://127.0.0.1:8765"
FIRST_NOTE = 1794256356665          # the reported card's id: a real Connect note of 2026-11-09
FIRST_CARD = 1794256356700
LAPIS = ["Expression", "ExpressionFurigana", "ExpressionReading", "Sentence", "SentenceFurigana", "PitchPosition",
         "PitchCategories", "Patterns", "Glossary"]
RESOURCES = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tests", "Test Resources", "ja")


def _srt_lines(name):
    with open(os.path.join(RESOURCES, name), encoding="utf-8") as handle:
        blocks = handle.read().replace("\r\n", "\n").strip().split("\n\n")
    return [block.split("\n", 2)[2] for block in blocks]


LINES = _srt_lines("readings_sample.srt")


@pytest.fixture(scope="module")
def tagger():
    from app import analyzer
    return analyzer.JapaneseTokenizer().tagger


# --- the furigana itself ------------------------------------------------------------------------------------------- #
def test_the_sentence_reads_each_kanji_in_ankis_form_and_keeps_the_bold(tagger):
    line = LINES[5]                                             # 試合に勝って、大手を振って帰れますね。
    sentence = line.replace("大手を振って", "<b>大手を振って</b>")
    assert readings.sentence_furigana(sentence, tagger) == \
        "試合[しあい]に 勝[か]って、<b>大手[おおて]を 振[ふ]って</b>帰[かえ]れますね。"


def test_a_reading_goes_over_its_kanji_only_and_kana_words_stay_bare(tagger):
    # 気に入った: the okurigana outside the brackets; この / すごく / よ untouched; the space only before a kanji word
    assert readings.sentence_furigana("この店、すごく<b>気に入った</b>よ。", tagger) == \
        "この 店[みせ]、すごく<b>気[き]に 入[はい]った</b>よ。"
    assert readings.sentence_furigana(LINES[0], tagger) == "これ、いい 感[かん]じじゃない？"


def test_a_tag_inside_a_word_goes_to_its_edge_and_escapes_stay_escaped(tagger):
    # Anki Miner bolds whole words, but a hand-made card may bold half of one: the tag moves to the word's edge,
    # never splitting the reading; an escaped character stays escaped
    assert readings.sentence_furigana("<b>試</b>合 &amp; 駅", tagger) == "<b>試合[しあい]</b> &amp; 駅[えき]"


def test_an_old_book_sentence_is_read_whole_with_its_full_width_spaces(tagger):
    with open(os.path.join(RESOURCES, "books", "toshisyun_book.txt"), encoding="utf-8") as handle:
        line = handle.read().replace("\r\n", "\n").split("\n")[4]            # 　或春の日暮です。
    out = readings.sentence_furigana(line, tagger)
    assert out.startswith("　") and "春[はる]" in out and "日暮[ひぐれ]" in out
    assert "".join(ch for ch in out.replace(" ", "") if ch not in "[]") != line   # readings were added …
    assert _bare(out) == line.replace(" ", "")                                     # … and nothing else changed


def _bare(furigana):
    """The furigana with its readings and Anki's spaces taken out: the sentence again."""
    import re
    return re.sub(r"\[[^\]]*\]", "", furigana).replace(" ", "")


def test_an_empty_or_markup_only_sentence_gives_nothing(tagger):
    assert readings.sentence_furigana("", tagger) == ""
    assert readings.sentence_furigana("<br>", tagger) == ""


# --- the pitch ----------------------------------------------------------------------------------------------------- #
def test_one_word_gets_its_dictionary_accent(tagger):
    assert readings.pitch("試合", "しあい", tagger) == ("0", None)
    assert readings.pitch("帰る", "かえる", tagger) == ("1", None)
    assert readings.pitch("店", "みせ", tagger) == ("2", None)


def test_a_phrase_a_name_a_cry_or_another_reading_is_left_empty(tagger):
    # the measured line: a compound or a phrase can't be told reliably, a name's accent is its own, and a reading the
    # card doesn't share is another word's accent
    assert readings.pitch("大手を振る", "おおてをふる", tagger) == ("", "phrase")
    assert readings.pitch("あくまでも", "あくまでも", tagger) == ("", "phrase")         # the reported card
    assert readings.pitch("立川", "たちかわ", tagger) == ("", "name")
    assert readings.pitch("くくっ", "くくっ", tagger) == ("", "not a word")
    assert readings.pitch("店", "てん", tagger) == ("", "reading differs")
    assert readings.pitch("", "", tagger) == ("", "no word")


def test_a_kana_word_without_a_reading_field_is_read_as_written(tagger):
    assert readings.pitch("すごい", "", tagger)[1] is None
    assert readings.pitch("試合", "", tagger) == ("", "reading differs"), "kanji with no reading: never guessed"


# --- through Backfill --------------------------------------------------------------------------------------------- #
def _note(index, word, reading, sentence, furigana="", pitch="", deck="Surasura", studied=False):
    note_id, card_id = FIRST_NOTE + index, FIRST_CARD + index
    values = {"Expression": word, "ExpressionFurigana": word, "ExpressionReading": reading, "Sentence": sentence,
              "SentenceFurigana": furigana, "PitchPosition": pitch, "PitchCategories": "", "Patterns": "",
              "Glossary": f"<div>{word}</div>"}
    note = {"noteId": note_id, "modelName": "Lapis", "tags": ["Surasura::connect::36f67c74-249"], "cards": [card_id],
            "fields": {name: {"value": values[name], "order": i} for i, name in enumerate(LAPIS)}}
    card = {"cardId": card_id, "note": note_id, "due": 3100 + index, "deckName": deck,
            "type": 2 if studied else 0, "queue": 2 if studied else 0}
    return note, card


def _fake(*pairs):
    return BackfillCollection([p[1] for p in pairs], [p[0] for p in pairs], {"Lapis": LAPIS})


class _Session(backfill.Session):
    """Backfill's own session with only what ふりがな and アクセント read: the analyzer's tagger (no パターン
    databases, no list, nothing known) — so the real `value` branches are the ones tested."""

    def __init__(self):            # noqa: the databases and the known-words test are never loaded here
        from app import analyzer
        self.language, self.stores, self.sentences, self._looked_up = "ja", [], {}, set()
        self._words = analyzer.JapaneseTokenizer()
        self.tokenize, self.zh_script = None, None
        self.is_known = lambda word, sentence=None: False

    def value(self, fill, note, field):
        if fill.key == "patterns":
            return "", "not found"      # パターン's data isn't what is tested here
        return super().value(fill, note, field)


AJT = '<span class="ajt__word_info" pitch="ミセ:atamadaka">店[みせ]</span>'


def test_only_an_empty_field_is_filled_ajts_and_anki_miners_are_left_alone():
    bare = _note(0, "店", "みせ", "この<b>店</b>、すごく気に入ったよ。")
    filled = _note(1, "店", "みせ", "この<b>店</b>、すごく気に入ったよ。", furigana=AJT, pitch="2")
    fake = _fake(bare, filled)
    settings = _settings(junban_backfill_fills=["furigana", "pitch"])
    with _patched(fake):
        scope = backfill.gather(URL, settings)
    planned = backfill.plan(scope, _Session(), settings, auto=True)
    assert planned["edits"] == {bare[0]["noteId"]: {
        "SentenceFurigana": {"before": "", "after": "この<b>店[みせ]</b>、すごく 気[き]に 入[はい]ったよ。"},
        "PitchPosition": {"before": "", "after": "2"}}}
    assert planned["by_fill"]["furigana"].get("filled") == 1 and planned["by_fill"]["pitch"].get("filled") == 1


def test_connects_run_fills_the_reported_cards_shape_whatever_the_ticks_and_the_deck(tmp_path):
    """The 11-09 card: SentenceFurigana and PitchPosition empty, Backfill's ticks at their default (パターン only), the
    card in Connect's deck while Backfill's deck is another. Connect's run fills its furigana (and a one-word card's
    pitch), and the run's Restore takes them back."""
    reported = _note(0, "あくまでも", "あくまでも", "「メリット、か。お前は<b>あくまでも</b>損得で行動をするってことだよな」")
    one_word = _note(1, "試合", "しあい", "<b>試合</b>に勝って、大手を振って帰れますね。")
    fake = _fake(reported, one_word)
    before = {k: v["value"] for k, v in reported[0]["fields"].items()}
    settings = _settings(junban_backfill_deck="TheBank")            # not the deck the cards are in
    assert backfill._fills(settings) == ["patterns"]
    with _patched(fake):
        report = backfill.run_named(settings, _Session(), [reported[0]["noteId"], one_word[0]["noteId"]],
                                    run_id="backfill-20261121-120000-000")
    assert report["ok"], report
    assert sorted(report["filled"]) == [reported[0]["noteId"], one_word[0]["noteId"]]
    got = {nid: {k: v["value"] for k, v in fake.notes[nid]["fields"].items()} for nid in fake.notes}
    first, second = got[reported[0]["noteId"]], got[one_word[0]["noteId"]]
    assert first["SentenceFurigana"].startswith("「メリット、か。お 前[まえ]は<b>あくまでも</b>損得[そんとく]で")
    assert first["PitchPosition"] == "", "a phrase: left empty, never guessed"
    assert second["SentenceFurigana"].startswith("<b>試合[しあい]</b>に 勝[か]って") and second["PitchPosition"] == "0"
    assert {k for k in first if first[k] != before[k]} == {"SentenceFurigana"}
    with _patched(fake):
        back = backfill.restore_run(settings, "backfill-20261121-120000-000")
    assert back["ok"], back
    assert fake.notes[reported[0]["noteId"]]["fields"]["SentenceFurigana"]["value"] == ""
    assert fake.notes[one_word[0]["noteId"]]["fields"]["PitchPosition"]["value"] == ""


def test_a_chinese_session_never_offers_either_fill():
    assert all(fill.languages == ("ja",) for fill in backfill.FILLS if fill.key in backfill.MAKING)


def test_the_window_builds_nothing_first_for_these_two():
    from modules.junban import backfill_view as V
    from types import SimpleNamespace
    assert V.needs_build(SimpleNamespace(fills=["furigana", "pitch"]), "ja", False) is False
    assert V.needs_build(SimpleNamespace(fills=["patterns", "pitch"]), "ja", False) is True


# --- the review's cases (Haiku lenses, 2026-11-21) ----------------------------------------------------------------- #
def test_a_bold_on_the_kanji_alone_stays_on_it_and_a_reading_is_never_split(tagger):
    # 勝って (line 6): the bold ends inside the word but at its reading's edge — it stays there; on half of 試合 the
    # reading spans both kanji, so the bold goes to the reading's edge
    assert readings.sentence_furigana("<b>勝</b>って、", tagger) == "<b>勝[か]</b>って、"
    assert readings.sentence_furigana("<b>試</b>合", tagger) == "<b>試合[しあい]</b>"
    assert readings.sentence_furigana("すご<i>く</i>いい", tagger) == "すご<i>く</i>いい", "inside kana: exactly there"


def test_a_bracket_of_the_sentences_own_is_never_read_as_a_reading(tagger):
    out = readings.sentence_furigana("試合[注]に勝って", tagger)
    assert "&#91;" in out and "&#93;" in out and "[注]" not in out


def test_a_split_two_readings_could_make_is_read_whole():
    # 飼い犬 かいいぬ: か|い|いぬ or かい|い|ぬ — the whole word under the whole reading, as Anki Miner does
    assert readings._split("飼い犬", "かいいぬ") == [("飼い犬", "かいいぬ")]
    assert readings._split("取り引き", "とりひき") == [("取", "と"), ("り", ""), ("引", "ひ"), ("き", "")]


def test_a_word_with_no_accent_in_the_dictionary_says_so_and_a_kana_word_reads_as_written(tagger):
    assert readings.pitch("さん", "さん", tagger) == ("", "no pitch data")
    assert readings.pitch("すごい", "", tagger) == ("2", None)


def test_replace_ticked_never_overwrites_these_two():
    """Replace is the learner's tick for パターン and 例文: AJT's per-word colour and Anki Miner's pitch are kept."""
    filled = _note(0, "店", "みせ", "この<b>店</b>、すごく気に入ったよ。", furigana=AJT, pitch="2")
    fake = _fake(filled)
    settings = _settings(junban_backfill_fills=["furigana", "pitch"], junban_backfill_replace=True)
    with _patched(fake):
        scope = backfill.gather(URL, settings)
    planned = backfill.plan(scope, _Session(), settings)
    assert planned["edits"] == {} and planned["counts"] == {"filled": 2}


def test_connects_run_fills_a_card_in_backfills_own_deck_too():
    """The card in Backfill's deck: パターン (ticked) and the two always — none dropped for the deck's own notes."""
    pair = _note(0, "試合", "しあい", "<b>試合</b>に勝って、大手を振って帰れますね。", deck="TheBank")
    fake = _fake(pair)
    with _patched(fake):
        report = backfill.run_named(_settings(junban_backfill_deck="TheBank"), _Session(), [pair[0]["noteId"]],
                                    run_id="backfill-20261121-120100-000")
    fields = fake.notes[pair[0]["noteId"]]["fields"]
    assert report["ok"] and report["skipped"].get("other deck") is None
    assert fields["SentenceFurigana"]["value"].startswith("<b>試合[しあい]</b>") and fields["PitchPosition"]["value"] == "0"


def test_a_deck_whose_fields_you_put_back_gets_neither_by_itself(monkeypatch):
    """FT-1: after *Put Anki back*, Backfill doesn't fill that deck by itself — the two always-fills included."""
    pair = _note(0, "試合", "しあい", "<b>試合</b>に勝って。")
    fake = _fake(pair)
    monkeypatch.setattr(backfill, "_fields_put_back",
                        lambda language, deck: "put back" if deck == "Surasura" else None)
    with _patched(fake):
        report = backfill.run_named(_settings(junban_backfill_deck="TheBank"), _Session(), [pair[0]["noteId"]],
                                    run_id="backfill-20261121-120200-000")
    assert report["skipped"] == {"other deck": 1}
    assert fake.notes[pair[0]["noteId"]]["fields"]["SentenceFurigana"]["value"] == ""


def test_senrens_lowercase_fields_are_found_and_a_card_without_a_sentence_is_said():
    """Senren names them sentence / sentenceFurigana / pitchPositions; a card whose sentence is empty is told apart."""
    fields = ["word", "reading", "sentence", "sentenceFurigana", "pitchPositions"]
    notes, cards = [], []
    for i, (word, reading, sentence) in enumerate((("試合", "しあい", "<b>試合</b>に勝って。"), ("駅", "えき", ""))):
        values = {"word": word, "reading": reading, "sentence": sentence, "sentenceFurigana": "", "pitchPositions": ""}
        notes.append({"noteId": FIRST_NOTE + i, "modelName": "Senren", "tags": [], "cards": [FIRST_CARD + i],
                      "fields": {n: {"value": values[n], "order": k} for k, n in enumerate(fields)}})
        cards.append({"cardId": FIRST_CARD + i, "note": FIRST_NOTE + i, "due": 1, "deckName": "Surasura",
                      "type": 0, "queue": 0})
    fake = BackfillCollection(cards, notes, {"Senren": fields})
    settings = _settings(junban_backfill_fills=["furigana", "pitch"],
                         junban_backfill_note_languages={"Senren": "ja"}, junban_word_field={"Senren": "word"})
    with _patched(fake):
        scope = backfill.gather(URL, settings)
    planned = backfill.plan(scope, _Session(), settings, auto=True)
    assert scope["models"]["Senren"]["mapped"]["furigana"] == "sentenceFurigana"
    assert planned["edits"][FIRST_NOTE]["sentenceFurigana"]["after"].startswith("<b>試合[しあい]</b>")
    assert ("the card has no sentence" in planned["by_fill"]["furigana"]), planned["by_fill"]


def test_a_chinese_session_plans_neither_and_its_value_says_not_available():
    pair = _note(0, "试合", "", "试合")
    fake = _fake(pair)
    settings = _settings(target_language="zh", junban_backfill_fills=["furigana", "pitch"],
                         junban_backfill_note_languages={"Lapis": "zh"})

    class Chinese(_Session):
        def __init__(self):
            super().__init__()
            self.language = "zh"
    with _patched(fake):
        scope = backfill.gather(URL, settings)
    planned = backfill.plan(scope, Chinese(), settings, auto=True)
    assert planned["edits"] == {} and planned["counts"] == {"language": 2}
    note = {"word": "试合", "reading": "", "fields": {"Sentence": "试合"}}
    assert Chinese().value(backfill.FILLS[2], note, "SentenceFurigana") == ("", "not available")

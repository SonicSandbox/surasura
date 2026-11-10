# SPDX-License-Identifier: GPL-3.0-or-later
"""The source field (P1.4 row 1.4.6; K40: "Junban's banner reads MiscInfo; Anki Miner's source now lands in
MigakuCardId"; HC-B6: Surasura has the last say on its own fields).

Connect's Backfill fills the note's source field — the field Anki Miner's mapping names (P1.3 row 1.3.6) — with the
show and the episode, only when it is empty, only on the mapping's note type, only on a new card. A field holding
anything, a studied card and every other field stay as they are; its restore takes back only what still holds it.

Real Lapis fields (the Junban suite's), Anki Miner's source field mapped to MigakuCardId as 3.5 maps it.
"""
from modules.junban import backfill
from modules.junban.tests.test_backfill import LAPIS, BackfillCollection, _lapis, _patched, _Session, _settings

URL = "http://127.0.0.1:8765"
SOURCE = ("Frieren · 第05話", "Lapis", "MigakuCardId")


def _notes(*pairs, source=""):
    for note, _card in pairs:
        note["fields"]["MigakuCardId"] = {"value": source, "order": len(LAPIS)}
    return pairs


def _fake(*pairs):
    return BackfillCollection([p[1] for p in pairs], [p[0] for p in pairs], {"Lapis": LAPIS + ["MigakuCardId"]})


def test_the_source_text_is_the_show_and_the_episode():
    assert backfill.source_text(r"D:\Anime\Frieren\第05話.mkv") == "Frieren · 第05話"
    assert backfill.source_text(r"D:\Anime\Frieren\Frieren - 05.mkv") == "Frieren - 05", "the show said once"
    assert backfill.source_text("") == ""


def test_only_an_empty_source_field_of_a_new_card_on_the_mappings_note_type_is_filled():
    pairs = _notes(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ", studied=True))
    filled = _notes(_lapis(2, "囲む", "かこむ"), source="Anki Miner's own")[0]
    other = _lapis(3, "海", "うみ")
    other[0]["modelName"] = "Kiku"
    fake = _fake(*pairs, filled, other)
    fake.models["Kiku"] = LAPIS + ["MigakuCardId"]
    other[0]["fields"]["MigakuCardId"] = {"value": "", "order": len(LAPIS)}
    with _patched(fake):
        scope = backfill.gather_notes(URL, _settings(), [p[0]["noteId"] for p in (*pairs, filled, other)])
    edits = backfill.source_edits(scope, *SOURCE)
    first = pairs[0][0]["noteId"]
    assert edits == {first: {"MigakuCardId": {"before": "", "after": "Frieren · 第05話"}}}


def test_a_markup_only_field_counts_as_empty_and_a_word_does_not():
    blank = _notes(_lapis(0, "探検", "たんけん"), source="<br>")
    word = _notes(_lapis(1, "大切", "たいせつ"), source="TheBank 05")
    fake = _fake(*blank, *word)
    with _patched(fake):
        scope = backfill.gather_notes(URL, _settings(), [blank[0][0]["noteId"], word[0][0]["noteId"]])
    assert set(backfill.source_edits(scope, *SOURCE)) == {blank[0][0]["noteId"]}


def test_a_run_fills_the_source_beside_the_patterns_and_touches_no_other_field():
    pairs = _notes(_lapis(0, "探検", "たんけん"))
    fake = _fake(*pairs)
    note_id = pairs[0][0]["noteId"]
    before = {name: value["value"] for name, value in fake.notes[note_id]["fields"].items()}
    with _patched(fake):
        report = backfill.run_named(_settings(junban_backfill_deck="TheBank"), _Session(), [note_id], source=SOURCE,
                                    run_id="backfill-20261006-020000-000")
    assert report["ok"] and report["filled"] == [note_id]
    after = {name: value["value"] for name, value in fake.notes[note_id]["fields"].items()}
    assert {k for k in after if after[k] != before[k]} == {"Patterns", "MigakuCardId"}
    assert after["MigakuCardId"] == "Frieren · 第05話"


def test_without_a_mapped_source_field_nothing_is_written_there():
    pairs = _notes(_lapis(0, "探検", "たんけん"))
    fake = _fake(*pairs)
    with _patched(fake):
        scope = backfill.gather_notes(URL, _settings(), [pairs[0][0]["noteId"]])
    assert backfill.source_edits(scope, "Frieren · 第05話", "Lapis", None) == {}
    assert backfill.source_edits(scope, "", "Lapis", "MigakuCardId") == {}

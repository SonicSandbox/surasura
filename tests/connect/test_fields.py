"""The field mapping (app/connect/fields.py, P1.3 row 1.3.6): the deck, note type and fields come from Anki Miner's own
settings export, the word field must be the note type's first, and what Junban and Backfill read of a mined card —
the word, the sentence, the source (K40) — is named. Lapis as the user has it; a custom note type; each gap a plain
*Needs you*."""
import copy

import pytest

from app.connect import fields
from tests.connect.fake_anki_miner import LAPIS_EXPORT

LAPIS_FIELDS = ["Expression", "ExpressionFurigana", "ExpressionReading", "ExpressionAudio", "SelectionText",
                "MainDefinition", "DefinitionPicture", "Sentence", "SentenceFurigana", "SentenceAudio", "Picture",
                "Glossary", "Hint", "IsWordAndSentenceCard", "IsClickCard", "IsSentenceCard", "IsAudioCard",
                "PitchPosition", "PitchCategories", "Frequency", "FreqSort", "MiscInfo"]


def _export(**settings):
    out = copy.deepcopy(LAPIS_EXPORT)
    out["settings"].update(settings)
    return out


def test_lapis_maps_the_word_sentence_and_source_fields():
    mapping = fields.from_export(LAPIS_EXPORT)
    assert (mapping.deck, mapping.note_type) == ("DevTest", "Lapis")
    assert (mapping.word, mapping.sentence, mapping.source) == ("Expression", "Sentence", "MiscInfo")
    assert mapping.frequency_sort is None                   # unmapped ("") is left out
    assert "glossary" not in mapping.fields
    fields.check_note_type(mapping, LAPIS_FIELDS)           # the word field first, every mapped field present


def test_a_custom_note_type_with_its_own_names():
    mapping = fields.from_export(_export(anki_deck_name="日本語::採掘", anki_note_type="私のカード", anki_fields={
        "word": "単語", "sentence": "例文", "audio": "音声", "picture": "", "source": "出典"}))
    assert (mapping.deck, mapping.word, mapping.sentence, mapping.source) == ("日本語::採掘", "単語", "例文", "出典")
    fields.check_note_type(mapping, ["単語", "読み", "例文", "音声", "出典"])


@pytest.mark.parametrize("export, says", [
    ({"settings": {}, "configured": False}, "isn't set up for Japanese"),
    ({"anki_miner_settings": 1}, "couldn't be read"),
    (_export(anki_deck_name=""), "no deck"),
    (_export(anki_note_type="  "), "no note type"),
    (_export(anki_fields={"word": "", "sentence": "Sentence"}), "which field holds the word"),
    (_export(anki_fields=None), "field mapping couldn't be read"),
])
def test_an_export_that_cant_make_a_card_needs_you(export, says):
    with pytest.raises(fields.NeedsYou) as e:
        fields.from_export(export)
    assert says in e.value.message


def test_the_note_type_must_take_the_mapping():
    mapping = fields.from_export(LAPIS_EXPORT)
    with pytest.raises(fields.NeedsYou) as e:
        fields.check_note_type(mapping, None)                       # not in Anki at all
    assert '"Lapis"' in e.value.message
    with pytest.raises(fields.NeedsYou) as e:
        fields.check_note_type(mapping, ["Sentence"] + [f for f in LAPIS_FIELDS if f != "Sentence"])
    assert "first field" in e.value.message                         # IS:205: Anki checks the first for duplicates
    with pytest.raises(fields.NeedsYou) as e:
        fields.check_note_type(mapping, [f for f in LAPIS_FIELDS if f != "MiscInfo"])
    assert '"MiscInfo"' in e.value.message


def test_a_chinese_export_never_set_up_names_chinese():
    with pytest.raises(fields.NeedsYou) as e:
        fields.from_export({"configured": False, "settings": {}}, "zh")
    assert "Chinese" in e.value.message

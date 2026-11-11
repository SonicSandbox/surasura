"""Chinese cards through Anki Miner 3.12 (Zh-C, 2026-11-12; Sonic: "Yes to the Chinese leans, use his card although
they may have their own so they can map it"; the 3.0 plan's `tracks/pipeline/work/chinese-cards/`).

- **The fields** (`miner_settings.fields_for(language="zh")`): Anki Miner Note's Pinyin, MeasureWord and Traditional
  fields are mapped by name even when the profile's map doesn't name those roles yet; the Japanese-only furigana and
  pitch roles are left unmapped (Anki Miner 3.12 stops a Chinese run on them: its CHANGELOG's first fix).
- **The note type** (`miner_settings.plan`): Anki Miner Note offered first, its page said while Anki lacks it; a note
  type of the learner's own is mapped by the learner (`why: "map"`), the map checked (`map_problem`) before it is
  written — the word in the first field (Anki Miner's rule), a sentence field, no field twice.
- **Word audio** (`runfile.word_audio_on` / `config`, CLAUDE.md §1): a Chinese run file sends the word-audio role
  unmapped unless *Word audio from Google* is on, so no word goes to Google by default; Japanese is unchanged.

What a wrong answer would cost: every Chinese run stopped on a furigana field the note type lacks; Pinyin left empty
on every card; a learner's own Chinese note type refused or filled with the sentence in the word's field; a word sent
to Google behind the learner's back.

No Anki or Anki Miner is run: the AnkiConnect reads are stand-ins (`Anki`, as in test_anki_miner_settings_import).
"""
import pytest

from app.connect import miner_settings as MS
from app.connect import runfile
from app.connect.fields import Mapping
from tests.test_anki_miner_settings_import import DEFAULT_FIELDS, LAPIS, Anki

# Anki Miner Note v1.0.2's fields (3.12.0 `services/note_presets.py` _ANKI_MINER_NOTE_SIGNATURE, the first 28)
AM_NOTE = LAPIS + ["SentenceTranslation", "Language", "Pinyin", "Jyutping", "Traditional", "MeasureWord"]
# A learner's own Chinese note type, the kind a Pleco or HSK deck carries: no field named like Anki Miner's
OWN = ["汉字", "拼音", "意思", "例句", "例句音频", "图片"]
# The zh profile as Anki Miner 3.12's `settings-export --language zh` hands it over before any setup: the ja map's
# names with both furigana fields unmapped (`languages/_spaced/fields.py`), and none of the three Chinese keys yet
ZH_FIELDS = dict(DEFAULT_FIELDS, expression_furigana="", sentence_furigana="")
FRESH_ZH = {"anki_deck_name": "Anki Miner", "anki_note_type": "", "anki_fields": ZH_FIELDS}
ZH = {"anki_sync_decks": {"zh": ["中文::句子"]}, "junban_deck": "中文::句子"}
ALL = {"deck", "note_type", "fields"}


# --- the fields ------------------------------------------------------------------------------------------------------ #
def test_anki_miner_note_gets_pinyin_measure_word_and_traditional_and_no_furigana_or_pitch_for_chinese():
    fields = MS.fields_for(AM_NOTE, dict(ZH_FIELDS, pitch_position="PitchPosition", pitch_category="PitchCategories"),
                           language="zh")
    assert (fields["word"], fields["sentence"], fields["expression_reading"]) == ("Expression", "Sentence",
                                                                                 "ExpressionReading")
    assert (fields["expression_pinyin"], fields["measure_word"], fields["expression_traditional"]) == \
        ("Pinyin", "MeasureWord", "Traditional"), "mapped by name although the profile's map didn't name them"
    assert all(fields[r] == "" for r in ("expression_furigana", "sentence_furigana", "pitch_position",
                                         "pitch_category")), "Japanese-only: a mapped one stops a Chinese run (3.12)"


def test_japanese_keeps_its_furigana_and_pitch_and_gets_no_chinese_roles():
    fields = MS.fields_for(AM_NOTE, DEFAULT_FIELDS)
    assert fields["expression_furigana"] == "ExpressionFurigana" and fields["pitch_category"] == "PitchCategories"
    assert not set(MS.ZH_ROLES) & set(fields), "Pinyin on a Japanese card would be a field nobody fills"


# --- the note type --------------------------------------------------------------------------------------------------- #
def test_chinese_offers_anki_miner_note_first_and_every_note_type_the_learner_could_map():
    anki = Anki(["中文::句子"], {"Basic": ["Front", "Back"], "中文卡": OWN, "Lapis": LAPIS, MS.AM_NOTE: AM_NOTE,
                                 "Cloze": ["Text"]})
    what, asked = MS.plan(ZH, "zh", FRESH_ZH, ALL, anki)
    assert what == "ask" and asked["note_type"][0] == MS.AM_NOTE
    assert set(asked["note_type"]) == {MS.AM_NOTE, "Basic", "中文卡", "Lapis"}, "one field holds no word and sentence"
    assert "get" not in asked, "Anki has it: nothing to get"


def test_chinese_without_anki_miner_note_says_where_to_get_it():
    anki = Anki(["中文::句子"], {"中文卡": OWN})
    what, asked = MS.plan(ZH, "zh", FRESH_ZH, ALL, anki)
    assert what == "ask" and asked["note_type"] == ["中文卡"] and asked["get"] == MS.AM_NOTE_PAGE
    jp = Anki(["日本語"], {"Lapis": LAPIS})
    assert "get" not in MS.plan({}, "ja", dict(FRESH_ZH, anki_fields=DEFAULT_FIELDS), ALL, jp)[1]


def test_anki_miner_note_picked_is_written_with_its_chinese_fields_no_map_asked():
    anki = Anki(["中文::句子"], {MS.AM_NOTE: AM_NOTE, "中文卡": OWN})
    what, values = MS.plan(ZH, "zh", FRESH_ZH, ALL, anki, {"note_type": MS.AM_NOTE})
    assert what == "write" and values["anki_note_type"] == MS.AM_NOTE
    assert values["anki_fields"]["expression_pinyin"] == "Pinyin" and values["anki_fields"]["expression_furigana"] == ""


def test_the_learners_own_note_type_is_asked_as_a_map_with_its_fields_and_the_word_in_the_first():
    anki = Anki(["中文::句子"], {MS.AM_NOTE: AM_NOTE, "中文卡": OWN})
    what, asked = MS.plan(ZH, "zh", FRESH_ZH, ALL, anki, {"note_type": "中文卡"})
    assert what == "ask" and asked["why"] == "map" and asked["note"] == "中文卡" and asked["problem"] is None
    assert asked["note_fields"] == OWN and asked["roles"] == list(MS.MAPPED["zh"])
    assert asked["note_type"][0] == "中文卡", "the note type asked about stays picked, the others still offered"
    assert set(asked["map"]) == set(MS.MAPPED["zh"]) and asked["map"]["sentence"] == "", "nothing named like it"


def test_the_learners_map_is_written_whole_word_first_and_unmapped_roles_empty():
    anki = Anki(["中文::句子"], {"中文卡": OWN})
    given = {"sentence": "例句", "expression_reading": "拼音", "definition": "意思", "audio": "例句音频",
             "picture": "图片", "expression_pinyin": "", "expression_audio": ""}
    what, values = MS.plan(ZH, "zh", FRESH_ZH, ALL, anki, {"note_type": "中文卡", "fields": given})
    assert what == "write" and values["anki_note_type"] == "中文卡"
    fields = values["anki_fields"]
    assert list(fields)[0] == "word" and fields["word"] == "汉字", "Anki Miner's rule: the word in the first field"
    assert (fields["sentence"], fields["expression_reading"], fields["audio"]) == ("例句", "拼音", "例句音频")
    assert fields["expression_audio"] == "" and fields["measure_word"] == "" and fields["expression_furigana"] == ""
    taken = [f for f in fields.values() if f]
    assert len(taken) == len(set(taken)), "Anki Miner refuses one field for two roles"


@pytest.mark.parametrize("given, problem", [
    ({"sentence": ""}, "sentence"),                                # every card needs its sentence
    ({"sentence": "汉字"}, "word"),                                  # the first field is the word's
    ({"sentence": "例句", "definition": "汉字"}, "word"),
    ({"sentence": "例句", "definition": "例句"}, "twice"),
    ({"sentence": "例句", "picture": "Bild"}, "gone"),               # a field the note type no longer has
])
def test_a_map_that_cant_make_cards_is_asked_again_saying_why_and_nothing_is_written(given, problem):
    anki = Anki(["中文::句子"], {"中文卡": OWN})
    what, asked = MS.plan(ZH, "zh", FRESH_ZH, ALL, anki, {"note_type": "中文卡", "fields": given})
    assert what == "ask" and asked["why"] == "map" and asked["problem"] == problem
    assert asked["map"]["sentence"] == given["sentence"], "the learner's map comes back as they left it"
    assert MS.map_problem(OWN, given) == problem


def test_a_map_for_another_note_type_than_the_one_picked_is_never_used():
    """The learner picked another note type after the map showed: that one is asked, the old map never written."""
    anki = Anki(["中文::句子"], {"中文卡": OWN, "HSK": ["Hanzi", "Sentence", "Pinyin"]})
    what, asked = MS.plan(ZH, "zh", FRESH_ZH, ALL, anki, {"note_type": "HSK", "fields": None})
    assert what == "ask" and asked["note"] == "HSK" and asked["map"]["sentence"] == "Sentence"
    assert asked["map"]["expression_pinyin"] == "Pinyin", "the proposal matches by name"


# --- word audio (CLAUDE.md §1) ---------------------------------------------------------------------------------------- #
MAPPING = Mapping("中文::句子", MS.AM_NOTE, {"word": "Expression", "sentence": "Sentence", "audio": "SentenceAudio",
                                          "expression_audio": "ExpressionAudio"}, "Expression", "Sentence", None, None)


@pytest.mark.parametrize("settings, language, on", [
    ({}, "zh", False),                                     # off by default: nothing goes to Google
    ({"connect_zh_word_audio": False}, "zh", False),
    ({"connect_zh_word_audio": "yes"}, "zh", False),        # only a real True turns it on
    ({"connect_zh_word_audio": True}, "zh", True),
    ({}, "ja", True),                                      # Japanese word audio is Anki Miner's own: unchanged
    ({"connect_zh_word_audio": False}, "ja", True),
])
def test_word_audio_is_asked_for_chinese_only_while_its_switch_is_on(settings, language, on):
    assert runfile.word_audio_on(settings, language) is on


def test_a_chinese_run_file_with_word_audio_off_sends_the_word_audio_field_unmapped():
    off = runfile.config(MAPPING, "3.12.0", ["bold-target", "sentence-rules-off"], word_audio=False)
    assert off["anki_fields"]["expression_audio"] == "" and off["anki_fields"]["audio"] == "SentenceAudio"
    assert MAPPING.fields["expression_audio"] == "ExpressionAudio", "the profile's own mapping is never changed"
    on = runfile.config(MAPPING, "3.12.0", ["bold-target", "sentence-rules-off"])
    assert on["anki_fields"]["expression_audio"] == "ExpressionAudio"


@pytest.mark.parametrize("app, refused", [("3.11.0", True), ("3.12.0", False), ("3.13.1", False)])
def test_chinese_cards_wait_for_anki_miner_3_12_and_nothing_is_sent_to_an_older_one(tmp_path, monkeypatch, app,
                                                                                      refused):
    """Review SHOULD: Chinese was proven with Anki Miner 3.12 only (its Chinese field fix, word audio only into a
    mapped field). An older one gets nothing — the update's *Needs you* (kind `setup`) — and Japanese is unchanged."""
    from app.connect import anki_miner
    info = {"app": app, "features": ["named-words-whitelisted", "word-from-line", "bold-target",
                                     "sentence-rules-off"]}
    monkeypatch.setattr(anki_miner, "preflight", lambda *a, **k: (info, "surasura"))
    sent = []
    monkeypatch.setattr(anki_miner.runfile, "write", lambda path, data: sent.append(data) or path)

    class Sent(Exception):
        pass
    monkeypatch.setattr(anki_miner, "result_names", lambda *a: (_ for _ in ()).throw(Sent()))
    words = [{"word": "夜市", "reading": "", "surface": "夜市", "line_start": 4.1, "line_expansion": [0, 0],
              "sent": ["夜市"], "predicted_class": None}]
    for language in ("zh", "ja"):
        sent.clear()
        try:
            anki_miner._mine_held("am.exe", language, "zhc-1", "v.mp4", "v.srt", words, MAPPING, "Surasura",
                                  str(tmp_path), 1, 0.0, 60)
        except anki_miner.AnkiMinerError as e:
            assert language == "zh" and refused and e.kind == "setup" and "3.12" in e.message
            assert sent == [], "nothing sent to an Anki Miner that can't make them"
            continue
        except Sent:
            pass
        assert not (language == "zh" and refused) and len(sent) == 1, (language, app)


def test_the_word_audio_row_shows_for_chinese_with_connect_on_only_and_is_off_by_default():
    """Settings › Anki & mining: *Word audio from Google* (its one line names Google) — a Chinese learner's with
    Connect on; never Japanese's (its word audio is Anki Miner's own); off as shipped."""
    from app import settings_manager
    from app.qt import settings_catalog as catalog
    from app.qt import settings_strings
    row = catalog.ROW["connect_zh_word_audio"]
    assert row.keys == ("connect_zh_word_audio",) and row.section == "anki"
    assert row.when({"connect_enabled": True}, "zh", set()) and not row.when({"connect_enabled": True}, "ja", set())
    assert not row.when({"connect_enabled": False}, "zh", set())
    assert "Google" in settings_strings.ROWS["connect_zh_word_audio"][1], "the one line says where the word goes"
    assert settings_manager.DEFAULT_SETTINGS["connect_zh_word_audio"] is False


@pytest.mark.parametrize("settings, lang, on", [({}, "zh", False), ({"connect_zh_word_audio": True}, "zh", True),
                                                ({}, "ja", True)])
def test_connects_mine_step_hands_the_word_audio_switch_to_anki_miner_as_settings_json_says_now(monkeypatch, settings,
                                                                                               lang, on):
    """The runner's mine step reads the switch from settings.json as it is now (`Steps._settings`) and hands it to
    `mine_batch`: a Chinese run asks for word audio only while it is on."""
    from types import SimpleNamespace

    from app.cli import verbs
    from app.connect import anki_miner, runner
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "am.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup",
                        lambda loaded, lang, run_dir, held=None: (None, None, SimpleNamespace(word="Expression")))
    monkeypatch.setattr(verbs, "settings", lambda: dict(settings))
    seen = {}
    monkeypatch.setattr(anki_miner, "mine_batch",
                        lambda *a, **k: seen.update(k) or {"outcomes": [], "app": "3.12.0"})
    picked = {"video": "v.mp4", "subtitle": "v.srt", "offset": 0.0, "profile": None}
    runner.Steps({}).mine(lang, {"id": 1, "item_id": 1, "tag": "zh-1"}, picked, [{"word": "夜市", "reading": ""}], 1)
    assert seen["word_audio"] is on


@pytest.mark.parametrize("word_audio", [False, True])
def test_the_mine_call_writes_the_switch_into_its_run_file(tmp_path, monkeypatch, word_audio):
    from app.connect import anki_miner
    info = {"app": "3.12.0", "features": ["named-words-whitelisted", "word-from-line", "bold-target"]}
    monkeypatch.setattr(anki_miner, "preflight", lambda *a, **k: (info, "surasura"))
    sent = []
    monkeypatch.setattr(anki_miner.runfile, "write", lambda path, data: sent.append(data) or path)

    class Sent(Exception):
        pass
    monkeypatch.setattr(anki_miner, "result_names", lambda *a: (_ for _ in ()).throw(Sent()))
    words = [{"word": "夜市", "reading": "", "surface": "夜市", "line_start": 4.1, "line_expansion": [0, 0],
              "sent": ["夜市"], "predicted_class": None}]
    with pytest.raises(Sent):
        anki_miner._mine_held("am.exe", "zh", "zhc-1", "v.mp4", "v.srt", words, MAPPING, "Surasura", str(tmp_path),
                              1, 0.0, 60, word_audio=word_audio)
    assert sent[0]["config"]["anki_fields"]["expression_audio"] == ("ExpressionAudio" if word_audio else "")


def test_a_field_the_learner_gave_one_role_is_never_also_matched_by_name_to_another():
    """Mutant P3: the learner put the meaning in the note type's "Frequency" field; the frequency role, matched by
    name and not shown in the map, must not take it too (Anki Miner refuses one field for two roles)."""
    anki = Anki(["中文::句子"], {"中文卡": ["汉字", "例句", "Frequency"]})
    given = {"sentence": "例句", "definition": "Frequency"}
    what, values = MS.plan(ZH, "zh", FRESH_ZH, ALL, anki, {"note_type": "中文卡", "fields": given})
    fields = values["anki_fields"]
    assert what == "write" and fields["definition"] == "Frequency" and fields["frequency"] == ""
    taken = [f for f in fields.values() if f]
    assert len(taken) == len(set(taken))


@pytest.mark.parametrize("kana_notes, total, mostly", [(2, 3, True), (1, 2, False), (0, 0, False), (3, 3, True)])
def test_mostly_kana_is_more_than_half_of_the_note_types_newest_notes(monkeypatch, kana_notes, total, mostly):
    """Mutant B3: Backfill's own sign of a Japanese note type is MORE than half its notes with kana — one in two (a
    Chinese deck with a stray の) stays Chinese."""
    notes = [{"fields": {"Expression": {"value": "夜市" if i >= kana_notes else "よる"},
                         "Sentence": {"value": "我们去夜市。"}}} for i in range(total)]
    reads = MS.AnkiReads("http://127.0.0.1:8765")
    monkeypatch.setattr(reads, "_invoke", lambda action, **p: list(range(total)) if action == "findNotes" else notes)
    assert reads.mostly_kana("中文卡") is mostly

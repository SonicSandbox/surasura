"""A4M1-2b (lean taken — PROVISIONAL; Sonic 2026-10-27: "I honestly don't want to ever have to open anki miner.
Ever.") and A2-6:

- *Finish its setup* sets Anki Miner's deck, note type and fields — and a language its profile never mined — itself,
  with Anki Miner's own `settings-import` (Z-3, `anki_miner.settings_import`), from Surasura's own settings and Anki
  (`connect.miner_settings`); only into the profile Connect mines with, and never the one Anki Miner's window uses
  (Surasura's own "Surasura" profile is made instead, a copy of it); what can't be told is asked in Surasura's window;
- a Connect run told BUSY while that setup runs names the setup, never "Anki Miner is open: close it".

What a wrong answer would cost: the learner's cards made in a premade deck, or with a note type that drops their
sentence; the settings Anki Miner's window uses overwritten behind their back; a learner sent to Anki Miner's window
after all; a learner told to close an Anki Miner that isn't open.

No real Anki Miner or Anki is run: `anki_miner.api` and the AnkiConnect reads are stand-ins. Deck and note type names
are the kind a learner has (Lapis, Kiku, a 日本語 deck tree, a 中文 deck).
"""
import json
import os
import time

import pytest

from app import anki_connect
from app.connect import anki_miner, miner_settings as MS, runner, setup
from app.services import anki_miner_setup as M

MINER = "C:\\Users\\learner\\AppData\\Local\\Programs\\AnkiMiner\\AnkiMiner.exe"
LAPIS = ["Expression", "ExpressionFurigana", "ExpressionReading", "ExpressionAudio", "SelectionText", "MainDefinition",
         "DefinitionPicture", "Sentence", "SentenceFurigana", "SentenceAudio", "Picture", "Glossary", "Hint",
         "IsWordAndSentenceCard", "IsClickCard", "IsSentenceCard", "IsAudioCard", "PitchPosition", "PitchCategories",
         "Frequency", "FreqSort", "MiscInfo"]
SENREN = ["word", "reading", "sentence", "sentenceFurigana", "sentenceTranslation", "sentenceCard", "audioCard",
          "notes", "selectionText", "definition", "wordAudio", "sentenceAudio", "picture", "glossary", "hint",
          "pitchAccents", "pitchPositions", "pitchCategories", "frequencies", "freqSort", "miscInfo"]
BASIC = ["Front", "Back"]
# Anki Miner 3.10.1's default field map (config.py), as `settings-export` hands it over for a language never set up
DEFAULT_FIELDS = {"word": "Expression", "sentence": "Sentence", "definition": "MainDefinition", "glossary": "",
                  "picture": "Picture", "audio": "SentenceAudio", "expression_furigana": "ExpressionFurigana",
                  "expression_reading": "", "sentence_furigana": "SentenceFurigana", "sentence_reading": "",
                  "pitch_position": "", "pitch_category": "", "pitch_graph": "", "pitch_text": "", "frequency": "",
                  "frequency_sort": "", "source": "", "expression_audio": "", "sentence_translation": "",
                  "language": ""}
FRESH = {"anki_deck_name": "Anki Miner", "anki_note_type": "", "anki_fields": DEFAULT_FIELDS}


class Anki:
    """The AnkiConnect reads `plan` makes, stood in: `decks`, note types with their fields, each deck's newest notes'
    note type. `closed` raises as AnkiConnect does when Anki isn't open."""

    def __init__(self, decks=(), types=None, deck_types=None, closed=False):
        self._decks, self._types, self._deck_types, self.closed = list(decks), dict(types or {}), \
            dict(deck_types or {}), closed
        self.asked = []

    def _ask(self, what):
        self.asked.append(what)
        if self.closed:
            raise anki_connect.AnkiError("Anki isn't open", kind="offline")

    def decks(self):
        self._ask("decks")
        return list(self._decks)

    def note_types(self):
        self._ask("note_types")
        return list(self._types)

    def fields(self, note_type):
        self._ask(("fields", note_type))
        return list(self._types[note_type])

    def deck_note_type(self, deck):
        self._ask(("deck", deck))
        return self._deck_types.get(deck)


# --- miner_settings: which deck ------------------------------------------------------------------------------------- #
def test_the_deck_junban_keeps_in_order_for_this_language_wins():
    settings = {"junban_deck": "日本語::Mining", "junban_replan_deck": "日本語::Mining", "junban_replan_language": "ja",
                "anki_sync_decks": {"ja": ["日本語::Kaishi 1.5k", "日本語::Mining"]}}
    assert MS.deck_for(settings, "ja", ["Default", "日本語::Kaishi 1.5k", "日本語::Mining"]) == "日本語::Mining"


def test_junbans_deck_counts_only_when_it_is_one_of_this_languages_known_decks():
    """One `junban_deck` for both languages: a Chinese deck picked in a Chinese 順 window never takes Japanese cards."""
    settings = {"junban_deck": "中文::句子", "anki_sync_decks": {"ja": ["日本語::Mining"], "zh": ["中文::句子"]}}
    decks = ["日本語::Mining", "中文::句子"]
    assert MS.deck_for(settings, "ja", decks) == "日本語::Mining", "the one Japanese known-words deck"
    assert MS.deck_for(settings, "zh", decks) == "中文::句子"


def test_several_known_decks_and_no_junban_deck_is_not_guessed():
    settings = {"anki_sync_decks": {"ja": ["日本語::Kaishi 1.5k", "日本語::Mining"]}}
    assert MS.deck_for(settings, "ja", ["日本語::Kaishi 1.5k", "日本語::Mining"]) is None


def test_a_deck_anki_doesnt_have_is_never_named():
    """Another Anki profile open, a deck renamed: the settings' deck isn't one Anki can put cards in."""
    settings = {"junban_deck": "日本語::Mining", "junban_replan_deck": "日本語::Mining", "junban_replan_language": "ja",
                "anki_sync_decks": {"ja": ["日本語::Mining", "日本語::Core"]}}
    assert MS.deck_for(settings, "ja", ["日本語::Core"]) == "日本語::Core"
    assert MS.deck_for({}, "ja", ["Default"]) is None, "no settings: nothing named"


# --- miner_settings: which note type --------------------------------------------------------------------------------- #
@pytest.mark.parametrize("backfill, deck_type, want", [
    ({}, "Lapis", "Lapis"),                                       # the deck's own notes
    ({"Kiku": "ja"}, "Lapis", "Kiku"),                            # Backfill names another one for Japanese
    ({"Kiku": "ja", "Lapis": "ja"}, "Lapis", "Lapis"),            # Backfill names both: the deck's
    ({"Kiku": "ja", "Lapis": "ja"}, None, None),                  # an empty deck, two named: asked
    ({"Lapis": "zh"}, None, None),                                # named for Chinese only
    ({"Lapis": "ja"}, None, "Lapis"),
    ({}, "Basic (gone)", None),                                   # a note type Anki no longer has
])
def test_the_note_type_comes_from_the_decks_notes_or_backfills_note_languages(backfill, deck_type, want):
    settings = {"junban_backfill_note_languages": backfill}
    assert MS.note_type_for(settings, "ja", ["Basic", "Lapis", "Kiku"], deck_type) == want


# --- miner_settings: which fields ------------------------------------------------------------------------------------ #
def test_lapis_gets_every_field_anki_miner_fills_the_word_first():
    fields = MS.fields_for(LAPIS, DEFAULT_FIELDS)
    assert fields["word"] == "Expression" and list(fields)[0] == "word"
    assert (fields["sentence"], fields["glossary"], fields["expression_audio"], fields["pitch_category"],
            fields["frequency_sort"], fields["source"]) == ("Sentence", "Glossary", "ExpressionAudio",
                                                              "PitchCategories", "FreqSort", "MiscInfo")
    assert fields["sentence_reading"] == "" and fields["pitch_graph"] == "", "Lapis has no field for them"
    assert set(fields) == set(DEFAULT_FIELDS), "only the roles this Anki Miner knows"


def test_a_field_the_profile_already_maps_is_kept_while_the_note_type_has_it():
    """The learner's own choice (their card layout reads the source from SelectionText) is never moved."""
    fields = MS.fields_for(LAPIS, dict(DEFAULT_FIELDS, source="SelectionText", sentence="Hint"))
    assert fields["source"] == "SelectionText" and fields["sentence"] == "Hint"


def test_senren_is_filled_by_its_own_names_and_the_word_goes_in_its_first_field():
    fields = MS.fields_for(SENREN, DEFAULT_FIELDS)
    assert (fields["word"], fields["sentence"], fields["definition"], fields["audio"], fields["frequency"]) == \
        ("word", "sentence", "definition", "sentenceAudio", "frequencies")


def test_no_field_is_mapped_twice_and_a_taken_field_falls_back_to_its_own_name():
    """Anki Miner refuses two roles in one field; the word's field is never given to another role."""
    fields = MS.fields_for(LAPIS, dict(DEFAULT_FIELDS, sentence="Expression", definition="Glossary"))
    assert fields["sentence"] == "Sentence", "its current field is the word's: its own name instead"
    assert fields["definition"] == "Glossary" and fields["glossary"] == "", "Glossary went to the definition first"
    targets = [f for f in fields.values() if f]
    assert len(targets) == len(set(targets))


@pytest.mark.parametrize("note_fields", [BASIC, [], ["Expression"]])
def test_a_note_type_with_no_sentence_field_is_not_one_anki_miner_can_fill(note_fields):
    assert MS.fields_for(note_fields, DEFAULT_FIELDS) is None


# --- miner_settings.plan --------------------------------------------------------------------------------------------- #
JA = {"junban_deck": "日本語::Mining", "junban_replan_deck": "日本語::Mining", "junban_replan_language": "ja",
      "anki_sync_decks": {"ja": ["日本語::Mining"]}}


def test_a_fresh_anki_miner_gets_the_deck_note_type_and_fields_from_surasuras_own_settings():
    anki = Anki(["Default", "日本語::Mining"], {"Basic": BASIC, "Lapis": LAPIS}, {"日本語::Mining": "Lapis"})
    what, values = MS.plan(JA, "ja", FRESH, {"deck", "note_type", "fields"}, anki)
    assert what == "write" and values["anki_deck_name"] == "日本語::Mining" and values["anki_note_type"] == "Lapis"
    assert values["anki_fields"]["glossary"] == "Glossary"
    assert values["pitch_category_format"] == "romaji", "Lapis reads its pitch categories as romaji"


def test_only_what_its_check_says_is_wrong_is_written():
    anki = Anki(["日本語::Mining", "Anki Miner"], {"Lapis": LAPIS}, {"日本語::Mining": "Lapis"})
    current = {"anki_deck_name": "日本語::Gone", "anki_note_type": "Lapis", "anki_fields": DEFAULT_FIELDS}
    assert MS.plan(JA, "ja", current, {"deck"}, anki) == ("write", {"anki_deck_name": "日本語::Mining"})
    assert "note_types" not in anki.asked, "a note type that works is never looked at"
    what, values = MS.plan(JA, "ja", current, {"fields"}, anki)
    assert what == "write" and values["anki_note_type"] == "Lapis" and "anki_deck_name" not in values


def test_a_deck_its_settings_cant_tell_is_asked_with_this_languages_known_decks_first():
    settings = {"anki_sync_decks": {"ja": ["日本語::Mining", "日本語::Kaishi 1.5k"]}}
    anki = Anki(["Default", "日本語::Kaishi 1.5k", "日本語::Mining"], {"Lapis": LAPIS})
    what, asked = MS.plan(settings, "ja", FRESH, {"deck", "note_type", "fields"}, anki)
    assert what == "ask" and asked["note_type"] is None, "the deck first: its notes most often name the note type"
    assert asked["deck"] == ["日本語::Mining", "日本語::Kaishi 1.5k", "Default"]


def test_the_learners_choice_is_taken_then_the_decks_notes_name_the_note_type():
    settings = {"anki_sync_decks": {"ja": ["日本語::Mining", "日本語::Kaishi 1.5k"]}}
    anki = Anki(["日本語::Kaishi 1.5k", "日本語::Mining"], {"Basic": BASIC, "Kiku": LAPIS + ["RelatedExpression"]},
                {"日本語::Mining": "Kiku"})
    what, values = MS.plan(settings, "ja", FRESH, {"deck", "note_type", "fields"}, anki, {"deck": "日本語::Mining"})
    assert what == "write" and (values["anki_deck_name"], values["anki_note_type"]) == ("日本語::Mining", "Kiku")


def test_an_empty_deck_asks_the_note_type_with_backfills_first():
    settings = dict(JA, junban_backfill_note_languages={"Kiku": "ja", "Lapis": "ja", "中文句子": "zh"})
    anki = Anki(["日本語::Mining"], {"Basic": BASIC, "Lapis": LAPIS, "Kiku": LAPIS, "中文句子": LAPIS})
    what, asked = MS.plan(settings, "ja", FRESH, {"deck", "note_type", "fields"}, anki)
    assert what == "ask" and asked["deck"] is None
    assert asked["note_type"] == ["Kiku", "Lapis", "Basic", "中文句子"]


def test_a_chosen_note_type_without_a_sentence_field_is_asked_again_saying_why():
    anki = Anki(["日本語::Mining"], {"Basic": BASIC, "Lapis": LAPIS})
    what, asked = MS.plan(JA, "ja", FRESH, {"deck", "note_type", "fields"}, anki, {"note_type": "Basic"})
    assert what == "ask" and asked["why"] == "fields" and asked["note"] == "Basic"


def test_a_choice_anki_doesnt_have_is_never_written():
    """A deck renamed in Anki between the ask and the press: asked again, never written as typed."""
    settings = {"anki_sync_decks": {"ja": ["日本語::Mining", "日本語::Core"]}}
    anki = Anki(["日本語::Mining", "日本語::Core"], {"Lapis": LAPIS})
    what, _asked = MS.plan(settings, "ja", FRESH, {"deck"}, anki, {"deck": "日本語::Old"})
    assert what == "ask"


def test_anki_closed_raises_for_the_caller_to_go_on_without_it():
    with pytest.raises(anki_connect.AnkiError):
        MS.plan(JA, "ja", FRESH, {"deck"}, Anki(closed=True))


# --- anki_miner.settings_import: the verb --------------------------------------------------------------------------- #
@pytest.fixture
def api(monkeypatch):
    calls = []
    answer = {"result": {"profile": "surasura-1", "created": True, "invalid_fields": []}}

    def fake(path, args, timeout=anki_miner.QUICK_TIMEOUT, on_poll=None, bind=True):
        with open(args[1], encoding="utf-8") as f:
            sent = json.load(f)
        calls.append({"args": list(args), "bind": bind, "sent": sent})
        return {"schema": 1, "command": "settings-import", "ok": answer.get("ok", True),
                "error": answer.get("error"), "message": answer.get("message"), "result": answer["result"]}
    monkeypatch.setattr(anki_miner, "api", fake)
    return calls, answer


def test_settings_import_makes_a_profile_from_a_file_it_then_removes(api, tmp_path):
    calls, _answer = api
    values = {"anki_deck_name": "中文::句子", "anki_note_type": "Lapis"}
    result = anki_miner.settings_import(MINER, "zh", values, str(tmp_path), name="Surasura")
    assert result["profile"] == "surasura-1"
    [call] = calls
    assert call["args"][0] == "settings-import" and call["args"][2:] == ["--language", "zh", "--name", "Surasura"]
    assert call["sent"] == values and call["bind"] is False, "a settings write is finished, never cut"
    assert os.listdir(tmp_path) == [], "the file it read is gone"


def test_settings_import_into_an_existing_profile_and_never_both_or_neither(api, tmp_path):
    calls, _answer = api
    anki_miner.settings_import(MINER, "ja", {}, str(tmp_path), profile="surasura-1")
    assert calls[0]["args"][2:] == ["--language", "ja", "--profile", "surasura-1"] and calls[0]["sent"] == {}
    for kwargs in ({}, {"name": "Surasura", "profile": "surasura-1"}):
        with pytest.raises(ValueError):
            anki_miner.settings_import(MINER, "ja", {}, str(tmp_path), **kwargs)


def test_a_value_anki_miner_refused_is_named_never_taken_as_set(api, tmp_path):
    _calls, answer = api
    answer["result"] = {"profile": "surasura-1", "created": False, "invalid_fields": ["anki_fields"]}
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        anki_miner.settings_import(MINER, "ja", {"anki_fields": {}}, str(tmp_path), profile="surasura-1")
    assert e.value.kind == "refused" and "anki_fields" in e.value.message


@pytest.mark.parametrize("error, kind", [("BUSY", "busy"), ("BAD_ARGUMENTS", "refused"),
                                         ("PROFILE_UNREADABLE", "setup")])
def test_settings_import_refusals_keep_their_kind(api, tmp_path, error, kind):
    _calls, answer = api
    answer.update(ok=False, error=error, message="refused", result={})
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        anki_miner.settings_import(MINER, "ja", {}, str(tmp_path), name="Surasura")
    assert e.value.kind == kind
    assert os.listdir(tmp_path) == []


# --- setup.checks: deck / note type / fields are Surasura's to set ------------------------------------------------ #
def _checked(monkeypatch, features, items):
    """Connect's setup checks over a stand-in Anki Miner whose `check` fails `items` (Anki answering)."""
    monkeypatch.setattr(setup, "_anki", lambda url, on: (setup._check("anki", "ok", "Anki is open."), True))
    monkeypatch.setattr(setup, "_anki_profile", lambda *a: (setup._check("anki_profile", "ok", "ok"), "User 1"))
    monkeypatch.setattr(anki_miner, "find", lambda settings: MINER)
    monkeypatch.setattr(anki_miner, "version", lambda path: {"app": "3.10.1",
                                                             "features": ["named-words-whitelisted"] + features})
    monkeypatch.setattr(anki_miner, "profiles", lambda path: [{"id": "default", "name": "Default", "active": True}])
    failed = [{"name": n, "ok": False, "message": f"{n} not set"} for n in items]
    monkeypatch.setattr(anki_miner, "check", lambda path, language, profile=None: {
        "ready": False, "items": [{"name": "anki", "ok": True, "message": None}] + failed})
    checks, _found = setup._anki_miner({}, "zh", True)
    return {c["id"]: c for c in checks}["anki_miner_setup"]


def test_a_deck_and_note_type_missing_is_surasuras_to_set_in_its_own_words(monkeypatch):
    check = _checked(monkeypatch, ["setup", "settings-import"], ["deck", "note_type", "fields"])
    assert check["setup"] is True and check["items"] == ["deck", "fields", "note_type"]
    assert check["say"].startswith("Anki Miner doesn't know where your Chinese cards go yet")
    assert check["do"] == setup.SETTINGS_DO and "Open Anki Miner" not in check["do"]


def test_a_never_mined_language_needs_both_and_is_said_as_one_step(monkeypatch):
    check = _checked(monkeypatch, ["setup", "settings-import"], ["deck", "note_type", "fields", "dictionary"])
    assert check["setup"] is True and check["do"] == setup.BOTH_DO
    assert "dictionary" in check["items"] and "deck" in check["items"]


def test_an_anki_miner_without_settings_import_still_names_its_own_window(monkeypatch):
    """Before Z-3 Surasura can't set a deck: the old words, and no Finish its setup that would do nothing."""
    check = _checked(monkeypatch, ["setup"], ["deck", "note_type"])
    assert not check.get("setup") and "Open Anki Miner" in check["do"]


# --- services.anki_miner_setup.finish_setup with settings-import ------------------------------------------------- #
@pytest.fixture
def world(monkeypatch, tmp_path):
    """Anki Miner as Connect's checks and its API answer: `profiles` (one active), the profile Connect mines with, the
    language configured or not, the check's items; Anki's reads; every write recorded."""
    state = {"items": ["deck", "note_type", "fields", "dictionary"], "profile": "default", "configured": False,
             "profiles": [{"id": "default", "name": "Default", "active": True}], "imports": [], "runs": [],
             "anki": Anki(["日本語::Mining", "中文::句子"], {"Basic": BASIC, "Lapis": LAPIS},
                          {"中文::句子": "Lapis", "日本語::Mining": "Lapis"}),
             "busy": False, "after": None, "import_raises": None}

    def checks(settings, language, keep=True):
        if state["after"] is not None and (state["imports"] or state["runs"]):
            check = state["after"]
        else:
            check = setup._check("anki_miner_setup", "needs-you", "Anki Miner doesn't know …", setup.BOTH_DO)
            check.update(setup=True, items=list(state["items"]))
        return {"checks": [check], "anki_miner": {"path": MINER, "profile": state["profile"],
                                                  "features": ["setup", "settings-import"]}}

    def settings_export(path, language, out, profile=None):
        state.setdefault("exports", []).append((language, profile))
        return {"configured": state["configured"], "settings": dict(FRESH)}

    def settings_import(path, language, values, folder, name=None, profile=None):
        assert os.path.isdir(folder)
        if state["import_raises"] is not None:
            raise state["import_raises"]
        state["imports"].append({"language": language, "values": values, "name": name, "profile": profile})
        return {"profile": profile or "surasura-1", "created": bool(name), "invalid_fields": []}

    def run_setup(path, language, profile, progress_path, on_poll=None):
        state["runs"].append((language, profile))
        return {}
    monkeypatch.setattr(setup, "checks", checks)
    monkeypatch.setattr(anki_miner, "settings_export", settings_export)
    monkeypatch.setattr(anki_miner, "settings_import", settings_import)
    monkeypatch.setattr(anki_miner, "run_setup", run_setup)
    monkeypatch.setattr(anki_miner, "profiles", lambda path: [dict(p) for p in state["profiles"]])
    monkeypatch.setattr(MS, "AnkiReads", lambda url: state["anki"])
    monkeypatch.setattr(M, "_busy", lambda: state["busy"])
    from app import path_utils
    monkeypatch.setattr(path_utils, "get_local_data_path", lambda: str(tmp_path / "local"))
    state["after"] = setup._check("anki_miner_setup", "ok", "Anki Miner's own setup is finished.")
    M._FAILED.clear()
    yield state
    M._FAILED.clear()


ZH = {"anki_sync_decks": {"zh": ["中文::句子"], "ja": ["日本語::Mining"]}}


def test_a_never_mined_language_makes_surasuras_own_profile_then_runs_its_setup_there(world):
    """The learner's Anki Miner mines Japanese in its one profile, the one its window uses: Chinese gets Surasura's
    own profile (a copy of it), its deck, note type and fields from Surasura's settings, then its dictionaries."""
    assert M.finish_setup(ZH, "zh") == (M.SET_UP, None)
    [made] = world["imports"]
    assert (made["name"], made["profile"], made["language"]) == (anki_miner.DEFAULT_PROFILE, None, "zh")
    assert (made["values"]["anki_deck_name"], made["values"]["anki_note_type"]) == ("中文::句子", "Lapis")
    assert world["runs"] == [("zh", "surasura-1")], "its setup runs in the profile just made"


def test_surasuras_own_profile_is_updated_never_copied_again(world):
    world["profile"] = "surasura-1"
    world["profiles"] = [{"id": "default", "name": "Default", "active": True},
                         {"id": "surasura-1", "name": "Surasura", "active": False}]
    world["configured"] = True
    world["items"] = ["deck"]
    assert M.finish_setup(ZH, "zh") == (M.SET_UP, None)
    assert world["imports"] == [{"language": "zh", "values": {"anki_deck_name": "中文::句子"}, "name": None,
                                 "profile": "surasura-1"}]
    assert world["runs"] == [], "nothing of its setup's was missing"


@pytest.mark.parametrize("named, called", [("Surasura", "Surasura"), ("Mining", "Mining")])
def test_the_profile_anki_miners_window_uses_is_never_written(world, named, called):
    """The profile Connect mines with is the one Anki Miner's window uses (the learner switched to it there): Anki Miner
    never lets settings-import change it, and Surasura doesn't try — it says so, in its own window's words."""
    world["profile"] = "p-1"
    world["profiles"] = [{"id": "p-1", "name": called, "active": True}]
    result, detail = M.finish_setup(dict(ZH, connect_anki_miner_profile=named), "zh")
    assert result == M.SETUP_FAILED and f'"{called}" is the one its window uses' in detail
    assert world["imports"] == [] and world["runs"] == []


def test_a_deck_it_cant_tell_is_asked_while_the_language_and_dictionaries_go_on(world):
    settings = {"anki_sync_decks": {"zh": ["中文::句子", "中文::HSK"]}}
    world["anki"] = Anki(["中文::句子", "中文::HSK"], {"Lapis": LAPIS}, {"中文::HSK": "Lapis"})
    result, asked = M.finish_setup(settings, "zh")
    assert result == M.ASK and asked["deck"] == ["中文::句子", "中文::HSK"]
    assert [i["values"] for i in world["imports"]] == [{}], "the language alone: no deck written unasked"
    assert world["runs"] == [("zh", "surasura-1")]
    world["profile"], world["configured"], world["items"] = "surasura-1", True, ["deck", "note_type", "fields"]
    world["profiles"].append({"id": "surasura-1", "name": "Surasura", "active": False})
    world["imports"], world["runs"] = [], []                # the next press, its check still naming the deck
    assert M.finish_setup(settings, "zh", chosen={"deck": "中文::HSK"}) == (M.SET_UP, None)
    assert world["imports"][-1]["values"]["anki_deck_name"] == "中文::HSK"
    assert world["imports"][-1]["profile"] == "surasura-1"


def test_anki_closed_meanwhile_still_sets_up_the_language_and_dictionaries(world):
    world["anki"] = Anki(closed=True)
    world["after"] = setup._check("anki_miner_setup", "waiting", "Anki Miner can't reach Anki.")
    assert M.finish_setup(ZH, "zh") == (M.SET_UP, None)
    assert [i["values"] for i in world["imports"]] == [{}] and world["runs"] == [("zh", "surasura-1")]


def test_nothing_is_written_while_anki_miner_or_connect_runs(world):
    world["busy"] = True
    assert M.finish_setup(ZH, "zh") == (M.BUSY, None)
    assert world["imports"] == [] and world["runs"] == [] and "exports" not in world


def test_a_refused_import_is_said_and_its_setup_never_runs(world):
    world["import_raises"] = anki_miner.AnkiMinerError("refused", "Anki Miner didn't take anki_fields from Surasura.")
    result, detail = M.finish_setup(ZH, "zh")
    assert (result, detail) == (M.SETUP_FAILED, "Anki Miner didn't take anki_fields from Surasura.")
    assert world["runs"] == []


def test_written_but_still_wrong_is_never_called_finished(world):
    world["after"] = setup._check("anki_miner_setup", "needs-you", "Anki Miner doesn't know where …", setup.SETTINGS_DO)
    world["after"]["setup"] = True
    result, detail = M.finish_setup(ZH, "zh")
    assert result == M.SETUP_FAILED and "Anki Miner doesn't know where" in detail


def test_a_language_already_mined_with_its_deck_right_writes_nothing(world):
    world["configured"], world["items"] = True, ["dictionary"]
    assert M.finish_setup(ZH, "zh") == (M.SET_UP, None)
    assert world["imports"] == [] and world["runs"] == [("zh", "default")]


# --- A2-6: BUSY during Surasura's setup names the setup -------------------------------------------------------------- #
@pytest.fixture
def local(monkeypatch, tmp_path):
    from app import path_utils
    monkeypatch.setattr(path_utils, "get_local_data_path", lambda: str(tmp_path))
    return tmp_path / anki_miner.SETUP_STAGING


def test_setting_up_while_its_folder_or_progress_moved_lately(local):
    assert anki_miner.setting_up() is False, "no setup folder: no setup"
    local.mkdir()
    assert anki_miner.setting_up() is True
    old = time.time() - anki_miner.SETUP_FRESH_S - 60
    os.utime(local, (old, old))
    assert anki_miner.setting_up() is False, "left by a Surasura that quit mid-setup: stale once Anki Miner is done"
    (local / anki_miner.PROGRESS).write_text('{"stage": 2}', encoding="utf-8")
    os.utime(local, (old, old))
    assert anki_miner.setting_up() is True, "Anki Miner still writing its progress"


def test_a_connect_run_told_busy_during_the_setup_names_it_and_holds_every_episode(local):
    busy = anki_miner.AnkiMinerError("busy", "Another command-line or API run is working.")
    assert runner._miner_wait_or_needs(busy).reason == runner.ANKI_MINER_OPEN
    local.mkdir()
    wait = runner._miner_wait_or_needs(busy)
    assert wait.reason == runner.SETTING_UP and "close" not in wait.reason
    assert runner.holds_every(runner.SETTING_UP), "the next look starts from the top, as for Anki Miner's window"


def test_the_verbs_busy_code_names_the_setup_too(local):
    from app.cli.contract import CliError
    local.mkdir()
    assert runner._wait_or_needs(CliError("anki-miner-busy", "Anki Miner is busy"), "mining").reason == \
        runner.SETTING_UP

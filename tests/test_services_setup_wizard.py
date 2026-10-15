"""The setup wizard's services (`app/services/setup_wizard.py`, W3.5 part 3): what each page writes on *Next*, where it
starts, and the reads and jobs behind it.

What a wrong answer would cost: a page that writes a key it doesn't own (D29's `logic.automation`, another language's
decks) or writes on *Skip* — a first-run choice the user never made; *Set up again* showing choices the settings don't
hold, so a *Next* quietly changes them; the "keep them in order" consent that never reaches 順's automatic run (HY-9) or
reaches it without the user's yes; a first sync that rewrites the known words instead of appending, or starts while an
update waits for Surasura's programs; a level page showing numbers for an empty library, or other numbers than the
Rarity slider's.

Real settings files under the test's own root (SURASURA_TEST_ROOT); Anki is the suites' fake collection behind a
patched `urllib.request.urlopen` (loopback, never live Anki); the words, shows and texts are real Japanese and Chinese
from `tests/Test Resources/`.
"""
import json
import os
import sys
import threading
from unittest import mock

import pytest

from app import anki_sync, replan_preview, settings_manager, token_index, word_selection
from app.path_utils import get_user_files_path
from app.services import setup_wizard as SW
from app.services.jobs import JobRegistry
from app.services.settings import SettingsService
from tests import services_helpers as h
from tests.test_anki_sync import URL
from tests.test_anki_window import FakeAnki
from tests.test_library_store_support import LANGUAGES, migrated, roots

# A settings file as a user's looks before the wizard: a look, another language's decks, Connect's own keys.
BEFORE = {"theme": "Dark Flow", "app_theme": "dark", "anki_sync_decks": {"zh": ["中文::挖掘"]},
          "connect_mine_words": "list", "junban_tag": "Surasura"}


# Real words of each language's shared test text (the Anki window's suite picks the same).
WORDS = {"ja": ("冒険", "準備", "危険", "価値", "冒険家", "有名"), "zh": ("冒险", "危险", "挑战", "勇敢")}


def _words(language):
    """The language's real words that its shared test text holds, in WORDS' order."""
    with open(os.path.join(h.RESOURCES, language, "context_test.txt"), encoding="utf-8") as f:
        text = f.read()
    return [w for w in WORDS[language] if w in text]


def _saved_through_service(page, answers, language, before=BEFORE):
    """`save` on a real settings file: -> (what save returned, the file before, the file after)."""
    h.write_settings(before)
    service = SettingsService()
    returned = SW.save(service, page, answers, language)
    assert service.flush(10), "the write landed"
    return returned, dict(before), h.read_settings()


def _changed(before, after):
    return {k for k in set(before) | set(after) if before.get(k, object()) != after.get(k, object())}


# --- opening ------------------------------------------------------------------------------------------------------ #
def test_the_wizard_opens_until_setup_was_finished():
    assert SW.should_open({}) and SW.should_open({"onboarding_completed": False})
    assert SW.should_open({"onboarding_completed": "true"}), "only a real yes closes it (a hand edit is no answer)"
    assert not SW.should_open({"onboarding_completed": True})
    assert SW.PAGES == ("language", "known", "shows", "order", "cards", "level")
    assert SW.LATER == ("leave", "mark", "aside")


# --- each page's writes, exactly (and nothing else) ------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("page, answers, expected", [
    ("language", {"language": "zh"}, {"target_language": "zh"}),
    ("shows", {"covers": True}, {"covers_download": True}),
    ("shows", {"covers": False}, {"covers_download": False}),
    ("cards", {"make_cards": True}, {"connect_enabled": True}),
    ("cards", {"make_cards": False}, {"connect_enabled": False}),
    ("level", {"automatic": True, "band": "rare"}, {"logic": {"selection": {"auto": True}}}),
    ("level", {"automatic": False, "band": "uncommon"}, {"logic": {"selection": {"auto": False, "band": "uncommon"}}}),
])
def test_each_page_writes_its_own_keys_on_a_real_settings_file(language, page, answers, expected):
    returned, before, after = _saved_through_service(page, answers, language)
    assert _changed(before, after) == set(expected), "only the page's keys move; every other key is as it was"
    for key, value in expected.items():
        assert after[key] == value
    assert "automation" not in (after.get("logic") or {}), "never D29's switch"
    assert returned == SW.writes(page, answers, {}, language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_from_anki_writes_this_languages_decks_and_keeps_the_others(language):
    deck = "日本語::Mining" if language == "ja" else "中文::新词"
    returned, before, after = _saved_through_service("known", {"how": "anki", "decks": [deck]}, language)
    assert _changed(before, after) == {"anki_sync_decks"}
    expected = dict(BEFORE["anki_sync_decks"], **{language: [deck]})
    assert after["anki_sync_decks"] == expected == returned["anki_sync_decks"], "another language's decks are kept"
    assert "anki_sync_fields" not in after, "the fields are the Anki window's: the wizard never writes them"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("later, flags", [("leave", (False, False, False)), ("mark", (True, True, False)),
                                          ("aside", (True, False, True))])
def test_card_order_writes_the_consent_the_recorded_pair_the_deck_and_the_three_way_choice(language, later, flags):
    deck = "日本語::Mining" if language == "ja" else "中文::新词"
    answers = {"keep_in_order": True, "deck": deck, "later": later, "open_anki": True}
    _returned, before, after = _saved_through_service("order", answers, language)
    assert _changed(before, after) == {"junban_auto_actions", replan_preview.DECK, replan_preview.LANGUAGE,
                                       "junban_deck", "junban_later_tag", "junban_later_flag", "junban_later_suspend",
                                       "connect_open_anki"}
    assert after["junban_auto_actions"] is True and after["connect_open_anki"] is True
    assert (after[replan_preview.DECK], after[replan_preview.LANGUAGE], after["junban_deck"]) == (deck, language, deck)
    assert (after["junban_later_tag"], after["junban_later_flag"], after["junban_later_suspend"]) == flags
    assert after["junban_tag"] == "Surasura", "順's own moved-card tag is the user's, untouched"
    assert replan_preview.recorded_deck(after, language) == deck
    assert replan_preview.recorded_deck(after, "zh" if language == "ja" else "ja") is None, "never the other language's"


@pytest.mark.parametrize("language", LANGUAGES)
def test_card_order_without_the_consent_clears_the_recorded_pair(language):
    """Off, the pair is cleared to "": 順's deck alone never lets the window re-order Anki by itself."""
    deck = "日本語::Mining" if language == "ja" else "中文::新词"
    before = dict(BEFORE, **{replan_preview.DECK: deck, replan_preview.LANGUAGE: language, "junban_deck": deck,
                             "junban_auto_actions": True})
    _returned, _b, after = _saved_through_service(
        "order", {"keep_in_order": False, "deck": deck, "later": "leave", "open_anki": False}, language, before)
    assert after["junban_auto_actions"] is False and after[replan_preview.DECK] == after[replan_preview.LANGUAGE] == ""
    assert replan_preview.recorded_deck(after, language) is None and after["junban_deck"] == deck
    # No deck chosen (Anki not found, and Next anyway): the consent is kept as said, nothing is recorded, 順's deck stays.
    writes = SW.writes("order", {"keep_in_order": True, "deck": None, "later": "leave", "open_anki": False}, {}, language)
    assert writes[replan_preview.DECK] == "" and "junban_deck" not in writes


def test_finish_writes_only_onboarding_completed():
    h.write_settings(BEFORE)
    service = SettingsService()
    assert SW.finish(service) == {"onboarding_completed": True}
    assert service.flush(10)
    after = h.read_settings()
    assert _changed(BEFORE, after) == {"onboarding_completed"} and after["onboarding_completed"] is True


@pytest.mark.parametrize("page, answers", [
    ("known", {"how": "fresh", "decks": ["日本語::Mining"]}),     # Start fresh: nothing
    ("known", {"how": "import", "decks": []}),                   # Import a list: the importer writes its own
    ("known", {"how": "anki", "decks": []}),                     # From Anki with no deck ticked: nothing to sync
    ("cards", {"make_cards": None}),                             # the switch absent (Anki Miner not ready)
])
def test_a_page_with_nothing_to_write_leaves_the_file_byte_for_byte(page, answers):
    h.write_settings(BEFORE)
    with open(h.settings_path(), "rb") as f:
        raw = f.read()
    service = mock.Mock(wraps=SettingsService())
    assert SW.save(service, page, answers, "ja") == {}
    service.set.assert_not_called()
    with open(h.settings_path(), "rb") as f:
        assert f.read() == raw


def test_skip_writes_nothing_at_all():
    """*Skip* never calls `save`: a fresh profile skipped through every page has no settings file at all."""
    assert not os.path.exists(h.settings_path())
    service = SettingsService()
    SW.preselect(service.get(), "ja")                    # the pages opened and showed their preselects
    assert service.pending() == [] and service.flush(5)
    assert not os.path.exists(h.settings_path())


def test_answers_that_are_no_answer_are_refused():
    with pytest.raises(ValueError):
        SW.writes("language", {"language": "en"}, {}, "ja")
    with pytest.raises(ValueError):
        SW.writes("order", {"later": "delete"}, {}, "ja")
    with pytest.raises(ValueError):
        SW.writes("known", {"how": "guess"}, {}, "ja")
    with pytest.raises(ValueError):
        SW.writes("welcome", {}, {}, "ja")


# --- where each page starts --------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_fresh_profile_starts_on_the_drafts_recommended_choices(language):
    pre = SW.preselect(settings_manager.load_settings(), language)
    assert pre == {"language": {"language": language}, "known": {"how": "anki", "decks": []},
                   "shows": {"covers": True},
                   "order": {"keep_in_order": True, "deck": None, "later": "leave", "open_anki": False},
                   "cards": {"make_cards": True},
                   "level": {"automatic": True, "band": settings_manager.DEFAULT_SETTINGS["logic"]["selection"]["band"]}}


@pytest.mark.parametrize("language", LANGUAGES)
def test_set_up_again_reads_back_what_every_page_saved(language):
    """Every page saved with answers other than the preselects, then setup finished: *Set up again* starts each page on
    exactly what was saved — so a *Next* straight through changes nothing."""
    deck = "日本語::Mining" if language == "ja" else "中文::新词"
    answers = {"language": {"language": language}, "known": {"how": "anki", "decks": [deck]},
               "shows": {"covers": False},
               "order": {"keep_in_order": False, "deck": deck, "later": "aside", "open_anki": True},
               "cards": {"make_cards": False}, "level": {"automatic": False, "band": "rare"}}
    h.write_settings(BEFORE)
    service = SettingsService()
    for page in SW.PAGES:
        SW.save(service, page, answers[page], language)
    SW.finish(service)
    assert service.flush(10)
    settings = settings_manager.load_settings()
    assert SW.preselect(settings, language) == answers
    for later in SW.LATER:                                # each three-way choice reads back as itself
        SW.save(service, "order", dict(answers["order"], later=later, keep_in_order=True), language)
        assert service.flush(10)
        again = SW.preselect(settings_manager.load_settings(), language)["order"]
        assert again["later"] == later and again["keep_in_order"] is True
    before = h.read_settings()
    for page in SW.PAGES:                                 # Next straight through: the file holds what it held
        SW.save(service, page, SW.preselect(service.get(), language)[page], language)
    assert service.flush(10)
    assert h.read_settings() == before


def test_a_mix_of_later_actions_is_shown_as_its_nearest_choice():
    assert SW._later_of({"junban_later_flag": True}) == "mark"
    assert SW._later_of({"junban_later_tag": True, "junban_later_suspend": True}) == "aside"
    assert SW._later_of({"junban_later_suspend": True}) == "aside"
    assert SW._later_of({}) == "leave"


def test_the_consent_reads_back_off_when_the_pair_is_recorded_for_the_other_language():
    settings = {"onboarding_completed": True, "junban_auto_actions": True, "junban_deck": "日本語::Mining",
                replan_preview.DECK: "日本語::Mining", replan_preview.LANGUAGE: "ja"}
    assert SW.preselect(settings, "ja")["order"]["keep_in_order"] is True
    assert SW.preselect(settings, "zh")["order"]["keep_in_order"] is False


# --- HY-9: the consent reaches 順's automatic run ---------------------------------------------------------------- #
def test_the_consent_reaches_juns_automatic_run_and_its_absence_moves_positions_only():
    auto = pytest.importorskip("modules.junban.auto")     # a build without modules/ (the public CI) skips
    h.write_settings(BEFORE)
    service = SettingsService()
    SW.save(service, "order", {"keep_in_order": True, "later": "aside", "deck": "日本語::Mining", "open_anki": False},
            "ja")
    assert service.flush(10)
    settings = settings_manager.load_settings()
    assert replan_preview.recorded_deck(settings, "ja") == "日本語::Mining"
    decided = auto.decide_actions(dict(settings))
    assert decided["junban_later_suspend"] is True and decided["junban_later_tag"] is True, "suspend + tag kept"

    SW.save(service, "order", {"keep_in_order": False, "later": "aside", "deck": "日本語::Mining", "open_anki": False},
            "ja")
    assert service.flush(10)
    settings = settings_manager.load_settings()
    assert replan_preview.recorded_deck(settings, "ja") is None, "no recorded pair: the window never re-orders by itself"
    decided = auto.decide_actions(dict(settings))
    assert not decided["junban_later_suspend"] and not decided["junban_later_tag"] and not decided["junban_later_flag"]


# --- Anki: the look and the first sync -------------------------------------------------------------------------- #
@pytest.fixture
def ja_words():
    words = _words("ja")
    assert len(words) >= 6, "real Japanese words from the shared resources"
    return words


def test_the_look_lists_every_deck_with_its_studied_cards_and_picks_the_studied_ones(ja_words):
    fake = FakeAnki([{"word": w, "deck": "日本語::Mining"} for w in ja_words[:3]]
                    + [{"word": ja_words[3], "deck": "Kana", "new": True}], decks=["Grammar"])
    with mock.patch("urllib.request.urlopen", fake):
        look = SW.anki_look({}, "ja")
        again = SW.anki_look({"anki_sync_decks": {"ja": ["Grammar"]}}, "ja")
    assert look == {"open": True, "say": None, "decks": [("Grammar", 0), ("Kana", 0), ("日本語::Mining", 3)],
                    "preselected": ["日本語::Mining"]}, "a deck of new cards only is never picked"
    assert again["preselected"] == ["Grammar"], "the saved pick, as the settings hold it"
    assert dict(again["decks"])["日本語::Mining"] == 3
    assert not any(r["action"].startswith(("add", "update", "delete", "change")) for r in fake.requests), \
        "the look never writes Anki"


def test_the_look_says_anki_is_closed_or_what_it_asked_as_written(ja_words):
    with mock.patch("urllib.request.urlopen", FakeAnki(offline=True)):
        closed = SW.anki_look({}, "ja")
    assert closed == {"open": False, "say": None, "decks": [], "preselected": []}
    with mock.patch("urllib.request.urlopen", FakeAnki([{"word": ja_words[0]}], permission="denied")):
        asked = SW.anki_look({}, "ja")
    assert asked["open"] is False and asked["say"] and "grant" in asked["say"].lower()


class _Automation:
    def __init__(self):
        self.heard = []

    def anki_synced(self, result, language):
        self.heard.append((result.mode, language))


def _known_words(language):
    path = os.path.join(get_user_files_path(language), "KnownWord.json")
    with open(path, encoding="utf-8") as f:
        return [w["dictForm"] for w in json.load(f)["words"]]


def test_the_first_sync_is_an_anki_sync_job_that_appends_only(ja_words):
    """The user's own known words stay as they are; the decks' studied words are added after them."""
    path = os.path.join(get_user_files_path("ja"), "KnownWord.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mine = [{"dictForm": w, "knownStatus": "KNOWN"} for w in ja_words[:2]]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"words": mine}, f, ensure_ascii=False)
    registry, automation, ended, done = JobRegistry(), _Automation(), [], threading.Event()
    fake = FakeAnki([{"word": w, "deck": "日本語::Mining"} for w in ja_words[1:5]])
    with mock.patch("urllib.request.urlopen", fake):
        job = SW.first_sync(registry, {"anki_connect_url": URL}, "ja", ["日本語::Mining"],
                            lambda r: (ended.append(r), done.set()), automation)
        assert done.wait(10), "the sync ended"
    assert job.kind == "anki-sync" and job.on_quit == "detach"
    assert ended[0].error is None and ended[0].added == 3, "the word already known is not added twice"
    known = _known_words("ja")
    assert known[:2] == ja_words[:2] and sorted(known) == sorted(ja_words[:5]), "appended after the user's own"
    assert automation.heard == [("full", "ja")], "a first sync reads every card, and the automation hears it"
    assert anki_sync.load_state("ja").get("last_sync"), "after it, the automatic sync may run (never-synced gate)"
    assert not any(r["action"].startswith(("add", "update", "delete", "change")) for r in fake.requests)


def test_the_first_sync_reads_a_chinese_deck_into_the_chinese_known_words():
    words = _words("zh")[:3]
    assert len(words) == 3, "real Chinese words from the shared resources"
    registry, ended, done = JobRegistry(), [], threading.Event()
    with mock.patch("urllib.request.urlopen", FakeAnki([{"word": w, "deck": "中文", "model": "Chinese"} for w in words])):
        SW.first_sync(registry, {}, "zh", ["中文"], lambda r: (ended.append(r), done.set()))
        assert done.wait(10)
    assert ended[0].added == 3 and _known_words("zh") == words
    assert not os.path.exists(os.path.join(get_user_files_path("ja"), "KnownWord.json"))


def test_the_first_sync_is_refused_while_an_update_holds_the_children_and_needs_a_deck(monkeypatch):
    from app import updater
    registry = JobRegistry()
    assert SW.first_sync(registry, {}, "ja", [], lambda _r: None) is None, "no deck: nothing to read"
    monkeypatch.setattr(updater, "children_held", lambda: True)
    assert SW.first_sync(registry, {}, "ja", ["日本語::Mining"], lambda _r: None) is None
    assert registry.snapshot() == ()


# --- the library's rows ------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_library_rows_are_one_per_title_with_its_files_and_folder(language):
    assert SW.library_rows({}, language) == [], "no store: nothing to show"
    store = migrated(language, shows=2, episodes=3, loose=1, tiers=("now", "soon"))
    try:
        expected = store.conn.execute(
            "SELECT w.title, COUNT(*) FROM items i JOIN works w ON w.id = i.work_id GROUP BY w.id").fetchall()
    finally:
        store.close()
    rows = SW.library_rows({}, language)
    assert sorted((r["name"], r["count"]) for r in rows) == sorted(expected)
    assert [r["count"] for r in rows[:2]] == [3, 3], "NOW's shows first, in the library's order"
    data_dir = os.path.normcase(os.path.normpath(roots(language)[0]))
    for row in rows:
        assert os.path.isdir(row["folder"]) and os.path.normcase(row["folder"]).startswith(data_dir + os.sep)


# --- the level -------------------------------------------------------------------------------------------------- #
def _index(language):
    from app import indexer
    with mock.patch.object(sys, "argv", ["indexer.py", "--language", language]):
        indexer.main()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_level_is_none_on_an_empty_library_and_the_sliders_numbers_on_real_shows(language):
    assert SW.level_numbers({}, language) is None, "nothing counted: 'Counting your shows…'"
    assert not os.path.exists(token_index.store_path_for(language)), "never a store made just to look"
    h.seed_library(language)
    _index(language)
    settings = settings_manager.load_settings()
    numbers = SW.level_numbers(settings, language)
    assert numbers is not None and numbers["bands"] == word_selection.BANDS_ORDER
    assert numbers["automatic"] is True and numbers["chosen"] == numbers["auto_band"], "a fresh profile: Automatic"
    store = token_index.open_store(language)
    try:
        freqs = token_index.preview_frequencies(store, language, get_user_files_path(language))
        sel = settings["logic"]["selection"]
        previews = word_selection.band_previews(freqs, sel["bands_ppm"], sel["min_count"],
                                                freqs["total_tokens"] / store.file_count(), sel["minutes_per_file"])
    finally:
        store.close()
    assert numbers["auto_band"] == word_selection.auto_band(previews, sel["auto_max_words"]), "D13's own rule"
    for band, p in previews.items():
        assert numbers["numbers"][band] == {"words": p["word_count"], "coverage": p["coverage_percent"],
                                            "every_hours": p["hours_between"]}, "the Rarity slider's numbers"
    chosen = numbers["numbers"][numbers["chosen"]]
    assert (numbers["words"], numbers["coverage"], numbers["every_hours"]) == \
        (chosen["words"], chosen["coverage"], chosen["every_hours"])
    assert numbers["words"] > 0 and 0 < numbers["coverage"] <= 100

    again = dict(settings, onboarding_completed=True)
    again["logic"] = dict(settings["logic"], selection=dict(sel, auto=False, band="rare"))
    manual = SW.level_numbers(again, language)
    assert manual["automatic"] is False and manual["chosen"] == "rare" and manual["words"] == previews["rare"][
        "word_count"], "Set up again with a band of your own: that band"


# --- the Content Manager and Generate --------------------------------------------------------------------------- #
def test_the_content_manager_opens_as_a_child_job_for_the_language(monkeypatch):
    from app.services import tools
    asked = []
    monkeypatch.setattr(tools, "command", lambda argv, frozen=None: asked.append(list(argv)) or [
        sys.executable, "-c", "print('閉じました')"])
    registry, ended, done = JobRegistry(), [], threading.Event()
    job = SW.open_content_manager(registry, "zh", lambda code: (ended.append(code), done.set()))
    assert done.wait(20), "the child ended"
    assert asked == [["content_importer_gui.py", "--language", "zh"]]
    assert job.kind == "child" and job.on_quit == "detach" and ended == [0]
    with pytest.raises(ValueError):
        SW.open_content_manager(registry, "fr")


def test_generate_asks_the_windows_generate_and_says_whether_it_was_taken():
    class Services:
        def __init__(self, answer):
            self.answer, self.asked = answer, 0

        def generate(self):
            self.asked += 1
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer
    taken = Services(object())
    assert SW.generate(taken) is True and taken.asked == 1
    assert SW.generate(Services(None)) is False, "closing: nothing asked for"
    assert SW.generate(Services(RuntimeError("closed"))) is False

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
    """The keys that moved, the unfinished profile's page mark (`setup_passed`, its own test) left out."""
    return {k for k in set(before) | set(after) if before.get(k, object()) != after.get(k, object())} - {SW.PASSED}


# --- opening ------------------------------------------------------------------------------------------------------ #
def test_the_wizard_opens_until_setup_was_finished():
    assert SW.should_open({}) and SW.should_open({"onboarding_completed": False})
    assert SW.should_open({"onboarding_completed": "true"}), "only a real yes closes it (a hand edit is no answer)"
    assert not SW.should_open({"onboarding_completed": True, "setup_seen": "3.0"})
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
    assert _changed(before, after) == set(expected), "only the page's keys (and its mark) move"
    assert after["setup_passed"] == [page], "an unfinished profile remembers the page saved (IK2-2)"
    for key, value in expected.items():
        assert after[key] == value
    assert "automation" not in (after.get("logic") or {}), "never D29's switch"
    assert returned == SW.writes(page, answers, {}, language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_from_anki_writes_this_languages_decks_and_keeps_the_others(language):
    deck = "日本語::Mining" if language == "ja" else "中文::新词"
    returned, before, after = _saved_through_service("known", {"how": "anki", "decks": [deck]}, language)
    assert _changed(before, after) == {"anki_sync_decks", "anki_sync_auto"}
    expected = dict(BEFORE["anki_sync_decks"], **{language: [deck]})
    assert after["anki_sync_decks"] == expected == returned["anki_sync_decks"], "another language's decks are kept"
    assert "anki_sync_fields" not in after, "the fields are the Anki window's: the wizard never writes them"


@pytest.mark.parametrize("language", LANGUAGES)
def test_from_anki_turns_the_automatic_sync_on_so_the_page_stays_in_sync(language):
    """IK (page 2 promises "stays in sync"): the automatic known-words sync is gated on `anki_sync_auto`, off by
    default, and nothing else turns it on — *From Anki* with a deck does. Import, Start fresh and no deck never do
    (`test_a_page_with_nothing_to_write_leaves_the_file_byte_for_byte`)."""
    deck = "日本語::Mining" if language == "ja" else "中文::新词"
    assert settings_manager.load_settings().get("anki_sync_auto") is not True, "off by default"
    returned, _before, after = _saved_through_service("known", {"how": "anki", "decks": [deck]}, language)
    assert after["anki_sync_auto"] is True and returned["anki_sync_auto"] is True
    assert "automation" not in (after.get("logic") or {}), "never D29's switch"


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


def test_finish_writes_only_onboarding_completed_and_the_pages_seen():
    h.write_settings(BEFORE)
    service = SettingsService()
    assert SW.finish(service) == {"onboarding_completed": True, "setup_seen": SW.SETUP_VERSION}
    assert service.flush(10)
    after = h.read_settings()
    assert _changed(BEFORE, after) == {"onboarding_completed", "setup_seen"} and after["onboarding_completed"] is True
    assert not SW.should_open(after)


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
    settings = {"onboarding_completed": True, "setup_seen": "3.0", "junban_auto_actions": True,
                "junban_deck": "日本語::Mining",
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


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_library_row_says_its_kind_by_its_titles_media_type(language):
    # W3.2 Q3 (IK-9 / IK2-10): page 3 counts episodes, a book's parts or videos — never "12 files" for a show. A title
    # with no media type yet reads as a show (as its row's stones do); a book set by the user reads as reading.
    store = migrated(language, shows=2, episodes=3, loose=0, tiers=("now",))
    try:
        works = [w for (w,) in store.conn.execute("SELECT id FROM works ORDER BY id")]
        store.set_media_type([works[1]], "book")
        titles = dict(store.conn.execute("SELECT id, title FROM works").fetchall())
    finally:
        store.close()
    kinds = {r["name"]: r["kind"] for r in SW.library_rows({}, language)}
    assert kinds == {titles[works[0]]: "shows", titles[works[1]]: "reading"}


@pytest.mark.parametrize("language", LANGUAGES)
def test_samples_go_into_an_empty_library_once_and_are_synced_into_the_store(language):
    # W3.2 Q3: *Try it with samples first* without the Content Manager — copied into the empty tier folders, then those
    # folders synced, so page 3's rows hold them; a second press copies nothing (never over a learner's files).
    store = migrated(language, shows=1, episodes=1, loose=0, tiers=("soon",))
    store.close()
    n = SW.add_samples(language)
    if n == 0:
        pytest.skip("no bundled samples for this language in this checkout")
    rows = SW.library_rows({}, language)
    assert len(rows) >= 2, "the samples are in the store, beside the show that was there"
    assert SW.add_samples(language) == 0
    with pytest.raises(ValueError):
        SW.add_samples("fr")


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

    again = dict(settings, onboarding_completed=True, setup_seen="3.0")
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


# --- the review's rows (W3.5-wiz-SM adversary): Set up again changes only what the user changed ------------------ #
JA_KEPT = {"onboarding_completed": True, "setup_seen": "3.0", "junban_auto_actions": True,
           "junban_deck": "日本語::Mining",
           replan_preview.DECK: "日本語::Mining", replan_preview.LANGUAGE: "ja",
           "junban_later_tag": True, "junban_later_flag": False, "junban_later_suspend": True}
ORDER_KEYS = ("junban_auto_actions", replan_preview.DECK, replan_preview.LANGUAGE, "junban_deck", "junban_later_tag",
              "junban_later_flag", "junban_later_suspend", "connect_open_anki")


def test_set_up_again_in_chinese_keeps_japanese_card_order_and_its_consent():
    """AD-1: ja is kept in order (the pair recorded for ja); *Set up again* in 中文 shows the page off and with no deck
    (順's deck is Japanese's), and *Next* — untouched, or with a Chinese deck picked but the switch left off — never
    clears ja's consent, its pair or 順's deck."""
    before = dict(BEFORE, **JA_KEPT)
    order = SW.preselect(before, "zh")["order"]
    assert order["keep_in_order"] is False and order["deck"] is None, "never Japanese's deck shown as Chinese's"
    for answers in (order, dict(order, deck="中文::新词")):
        _r, _b, after = _saved_through_service("order", answers, "zh", before)
        assert {k: after.get(k) for k in ORDER_KEYS} == {k: before.get(k) for k in ORDER_KEYS}
        assert replan_preview.recorded_deck(after, "ja") == "日本語::Mining"
    # The user's own act: the switch turned on for a Chinese deck records Chinese (one 順 deck for both languages).
    _r, _b, after = _saved_through_service("order", dict(order, keep_in_order=True, deck="中文::新词"), "zh", before)
    assert replan_preview.recorded_deck(after, "zh") == "中文::新词" and after["junban_auto_actions"] is True


def test_next_keeps_a_consent_given_though_juns_deck_moved_since():
    """AD-2: the consent and the pair are ja's, but 順's deck was changed in 順 since (the host stands aside). The page
    reads back on, with 順's deck now; *Next* untouched revokes nothing."""
    before = dict(BEFORE, **dict(JA_KEPT, junban_deck="日本語::Sentences"))
    order = SW.preselect(before, "ja")["order"]
    assert order["keep_in_order"] is True and order["deck"] == "日本語::Sentences"
    _r, _b, after = _saved_through_service("order", order, "ja", before)
    assert {k: after.get(k) for k in ORDER_KEYS} == {k: before.get(k) for k in ORDER_KEYS}
    # Picking the deck again is a new yes for it: the pair follows 順's deck.
    _r, _b, after = _saved_through_service("order", dict(order, deck="日本語::Mining"), "ja", before)
    assert replan_preview.recorded_deck(after, "ja") == "日本語::Mining"


@pytest.mark.parametrize("mix", [{"junban_later_flag": True}, {"junban_later_suspend": True},
                                 {"junban_later_tag": True}])
def test_set_up_again_never_rewrites_a_mixed_later_choice_it_only_shows(mix):
    """AD-3: a mix set in 順 (a flag alone, suspend without the tag) is shown as its nearest choice; *Next* untouched
    leaves it as 順 holds it. Another choice picked is written as the three-way choice says."""
    later = {"junban_later_tag": False, "junban_later_flag": False, "junban_later_suspend": False}
    before = dict(BEFORE, onboarding_completed=True, setup_seen="3.0", **dict(later, **mix))
    order = SW.preselect(before, "ja")["order"]
    _r, _b, after = _saved_through_service("order", order, "ja", before)
    assert {k: after.get(k) for k in later} == {k: before.get(k) for k in later}
    other = next(choice for choice in SW.LATER if choice != order["later"])
    _r, _b, after = _saved_through_service("order", dict(order, later=other), "ja", before)
    assert (after["junban_later_tag"], after["junban_later_flag"], after["junban_later_suspend"]) == \
        SW.LATER_FLAGS[other]


def test_from_anki_merges_onto_the_file_as_it_is_never_a_stale_copy():
    """AD-4: the decks are merged onto settings.json as it is when written (the service's `update=`), never from the
    window's copy: Chinese decks another program saved after the window read the file survive, and an older pick of
    the same language queued by the Anki window before *Next* never wins over the wizard's."""
    h.write_settings(BEFORE)
    service = SettingsService()                                         # the window's copy: zh = 中文::挖掘
    settings_manager.save_keys({"anki_sync_decks": {"zh": ["中文::新词"]}})    # 2.x's Anki window, meanwhile
    SW.save(service, "known", {"how": "anki", "decks": ["日本語::Mining"]}, "ja")
    assert service.flush(10)
    assert h.read_settings()["anki_sync_decks"] == {"zh": ["中文::新词"], "ja": ["日本語::Mining"]}

    from app import anki_window
    service.set({}, update=anki_window.merge("ja", ["日本語::Old"], []))   # the Qt Anki window's older pick
    SW.save(service, "known", {"how": "anki", "decks": ["日本語::Sentences"]}, "ja")
    assert service.flush(10)
    assert h.read_settings()["anki_sync_decks"] == {"zh": ["中文::新词"], "ja": ["日本語::Sentences"]}


def _zh_note(word):
    """A Chinese note as a Chinese learner's deck holds it: no kana in any field."""
    return {"word": word, "deck": "中文::挖掘", "model": "Chinese",
            "fields": [("Hanzi", word), ("Sentence", f"我们需要{word}。"), ("Meaning", "an English gloss")]}


def test_the_look_preselects_only_the_decks_that_read_as_this_language_and_counts_each_deck_once(ja_words):
    """AD-5 (the draft: "the ones that look like this language's preselected") and AD-10: an Anki with a Japanese and
    a Chinese deck preselects each language's own, by the Backfill rule (most notes with kana -> Japanese); every
    deck is counted in one request, and no note type is read."""
    zh = _words("zh")
    fake = FakeAnki([{"word": w, "deck": "日本語::Mining"} for w in ja_words[:3]] + [_zh_note(w) for w in zh[:4]]
                    + [{"word": "Bonjour", "deck": "Français", "fields": [("Front", "Bonjour"), ("Back", "Hello")]}])
    with mock.patch("urllib.request.urlopen", fake):
        ja_look = SW.anki_look({}, "ja")
        zh_look = SW.anki_look({}, "zh")
        saved = SW.anki_look({"anki_sync_decks": {"zh": ["日本語::Mining"]}}, "zh")
    assert ja_look["preselected"] == ["日本語::Mining"]
    assert zh_look["preselected"] == ["中文::挖掘"], "a Japanese deck is never preselected for Chinese"
    assert dict(zh_look["decks"]) == {"Français": 1, "中文::挖掘": len(zh[:4]), "日本語::Mining": 3}
    assert saved["preselected"] == ["日本語::Mining"], "the user's own saved pick is kept as it is"
    queries = [sub["params"]["query"] for r in fake.requests if r["action"] == "multi"
               for sub in r["params"]["actions"] if sub["action"] == "findNotes"]
    assert len(queries) == 9 and len(set(queries)) == 3, "each deck's studied notes asked once a look"
    assert "modelNames" not in fake.actions and not any(
        r["action"].startswith(("add", "update", "delete", "change")) for r in fake.requests)


def test_the_first_sync_keeps_a_dated_copy_of_the_known_words_before_it_writes(ja_words):
    """AD-5 / CLAUDE.md §4: the first sync onto an existing KnownWord.json keeps a byte-for-byte copy in .trash first
    (`anki_sync.sync` keeps none: it only appends); no file, no copy; a copy that can't be made writes nothing."""
    from app import path_utils
    path = os.path.join(get_user_files_path("ja"), "KnownWord.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"words": [{"dictForm": ja_words[0], "knownStatus": "KNOWN"}]}, f, ensure_ascii=False)
    with open(path, "rb") as f:
        mine = f.read()
    trash = os.path.join(os.path.dirname(path), ".trash")

    def run(language, deck, notes):
        ended, done = [], threading.Event()
        with mock.patch("urllib.request.urlopen", FakeAnki(notes)):
            SW.first_sync(JobRegistry(), {}, language, [deck], lambda r: (ended.append(r), done.set()))
            assert done.wait(10)
        return ended[0]
    ja_notes = [{"word": w, "deck": "日本語::Mining"} for w in ja_words[:4]]

    assert run("ja", "日本語::Mining", ja_notes).added == 3
    [copy] = os.listdir(trash)
    assert copy.startswith("KnownWord.") and copy.endswith(".json")
    with open(os.path.join(trash, copy), "rb") as f:
        assert f.read() == mine, "the user's file as it was before the sync"

    with open(path, "rb") as f:
        now = f.read()

    def refused(_path, move=False):
        raise OSError("the disk is full")
    with mock.patch.object(path_utils, "backup_to_trash", refused):    # never monkeypatch.undo(): it undoes the sandbox
        result = run("ja", "日本語::Sentences", ja_notes + [{"word": ja_words[5], "deck": "日本語::Sentences"}])
    assert result.error and "copy" in result.error.lower()
    with open(path, "rb") as f:
        assert f.read() == now, "no copy, no write"

    assert os.environ.get("SURASURA_TEST_ROOT") and get_user_files_path("zh").startswith(os.environ["SURASURA_TEST_ROOT"])
    run("zh", "中文::挖掘", [_zh_note(w) for w in _words("zh")[:2]])
    assert not os.path.exists(os.path.join(get_user_files_path("zh"), ".trash")), "no known words yet: nothing to keep"


# --- upgrading from 2.x (WZ-8 / P4.1-3, Sonic 2026-10-15) ----------------------------------------------------------- #
# A settings file as Surasura 2.5 leaves it: setup finished there, its own choices made, none of 3.0's keys.
def _from_2x(language):
    deck = "日本語::Mining" if language == "ja" else "中文::新词"
    return {"target_language": language, "onboarding_completed": True, "theme": "Dark Flow",
            "anki_sync_decks": {language: [deck]}, "junban_deck": deck, "junban_tag": "Surasura",
            "junban_later_tag": True, "junban_later_flag": False, "junban_later_suspend": True,
            "logic": {"selection": {"auto": False, "band": "rare"}}}


def test_a_profile_set_up_in_2x_opens_the_wizard_once():
    """Why: the import brings 2.x's `onboarding_completed` over, so without the pages-seen mark an upgrader would never
    be asked 3.0's questions (card order's consent, cards made for you) — and with it shown forever, setup never ends."""
    two = {"onboarding_completed": True}
    assert SW.upgrading(two) and SW.should_open(two)
    assert not SW.upgrading({}) and not SW.upgrading({"onboarding_completed": False}), "a new profile isn't upgrading"
    assert not SW.should_open(dict(two, setup_seen=SW.SETUP_VERSION))
    assert SW.upgrading(dict(two, setup_seen="  ")), "a blank mark is no mark"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_2x_profile_starts_on_its_own_choices_and_the_recommended_ones_where_2x_never_asked(language):
    before = _from_2x(language)
    deck = before["junban_deck"]
    pre = SW.preselect(before, language)
    assert pre == {"language": {"language": language}, "known": {"how": "anki", "decks": [deck]},
                   "shows": {"covers": True},                                 # 2.x never had covers: recommended
                   "order": {"keep_in_order": True, "deck": deck, "later": "aside", "open_anki": False},
                   "cards": {"make_cards": True},                             # Connect is 3.0's: recommended
                   "level": {"automatic": False, "band": "rare"}}             # 2.x's own level
    # No decks saved in 2.x: *What you know* keeps what came over (the import already brought the known words)
    bare = dict(before, anki_sync_decks={})
    assert SW.preselect(bare, language)["known"] == {"how": "fresh", "decks": []}
    assert SW.writes("known", SW.preselect(bare, language)["known"], bare, language) == {}


@pytest.mark.parametrize("language", LANGUAGES)
def test_next_straight_through_on_an_upgrade_keeps_2x_choices_and_writes_3_0s_new_ones(language):
    """Next on every page as preselected, then Generate's finish: 2.x's own choices stay byte-equal in the file; only
    the choices 2.x never had are written — the consent with its recorded pair, covers, cards made — plus the sync
    that the From Anki page promises, and the pages seen."""
    before = _from_2x(language)
    h.write_settings(before)
    service = SettingsService()
    for page in SW.PAGES:
        SW.save(service, page, SW.preselect(service.get(), language)[page], language)
    SW.finish(service)
    assert service.flush(10)
    after = h.read_settings()
    for key in ("target_language", "anki_sync_decks", "junban_deck", "junban_later_tag", "junban_later_flag",
                "junban_later_suspend", "theme", "junban_tag"):
        assert after[key] == before[key], key
    assert after["logic"]["selection"] == {"auto": False, "band": "rare"}
    assert after["covers_download"] is True and after["connect_enabled"] is True
    assert "anki_sync_auto" not in after, "2.x's own Keep in sync is kept on an untouched page (R2-2)"
    assert after["junban_auto_actions"] is True
    assert replan_preview.recorded_deck(after, language) == before["junban_deck"]
    assert after["setup_seen"] == SW.SETUP_VERSION and not SW.should_open(after)
    assert "connect_open_anki" not in after, "2.x never had it and the page left it as it is: not written"


def test_closing_an_upgrades_wizard_records_only_the_pages_seen():
    """Skip and *Finish later* keep 2.x's settings as they are: the close writes the pages-seen mark alone."""
    before = _from_2x("ja")
    h.write_settings(before)
    service = SettingsService()
    assert SW.seen(service) == {"setup_seen": SW.SETUP_VERSION}
    assert service.flush(10)
    after = h.read_settings()
    assert _changed(before, after) == {"setup_seen"} and not SW.should_open(after)


def test_an_untouched_from_anki_keeps_a_2x_keep_in_sync_off_and_a_changed_one_turns_it_on():
    # R2-2: page 2 shows no switch for it, so only a way or decks the learner changed turn the automatic sync on
    before = dict(_from_2x("ja"), anki_sync_auto=False)
    known = SW.preselect(before, "ja")["known"]
    assert SW.writes("known", known, before, "ja") == {"anki_sync_decks": before["anki_sync_decks"]}
    changed = dict(known, decks=known["decks"] + ["Core 2k"])
    assert SW.writes("known", changed, before, "ja")["anki_sync_auto"] is True
    assert SW.writes("known", known, dict(before, onboarding_completed=False), "ja")["anki_sync_auto"] is True


@pytest.mark.parametrize("language", LANGUAGES)
def test_finish_later_then_back_shows_what_was_saved_not_the_recommended_choice(language):
    """IK2-2: covers turned off with Next, then *Finish later*: the wizard coming back shows covers off (an Enter-through
    never turns the learner's no back into a yes); the pages not passed yet still start at the recommended choice."""
    h.write_settings(BEFORE)
    service = SettingsService()
    SW.save(service, "language", {"language": language}, language)
    SW.save(service, "shows", {"covers": False}, language)
    assert service.flush(10)
    settings = settings_manager.load_settings()
    assert settings["setup_passed"] == ["language", "shows"] and SW.should_open(settings)
    pre = SW.preselect(settings, language)
    assert pre["shows"] == {"covers": False}
    assert pre["cards"] == {"make_cards": True} and pre["order"]["keep_in_order"] is True
    SW.finish(service)
    SW.save(service, "shows", {"covers": True}, language)          # Set up again: no more marks
    assert service.flush(10)
    assert h.read_settings()["setup_passed"] == ["language", "shows"]

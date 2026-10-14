"""P3.3 row 3.3.1: `app/connect/replan.current` — what Connect mines and orders from after the library moved, read the
way the window's re-order host reads it (`plan_engine.check` over the plan the last Generate wrote).

On a real library (tests/plan_file_cases.py's RP-2: twelve Japanese files, ten Chinese ones, across NOW, Soon and 6+
Months), generated once per test. What these prove:

  - its own order → "no" Generate, and the pick's ranks are the list's own (the CSV's places);
  - a move → "no" Generate, and the re-plan IS a full Generate of the new order on the plan columns (05 §1, the
    journey's referee `_differs`) — the parity that lets Connect skip the Generate — in Japanese and Chinese;
  - known words changed → re-plan now, Generate "after" mining; the level raised alone (the band, or Automatic
    rarity's band, to a rarer one) → "after", no re-plan (mine from the list as it is); a lowering, the band with
    another setting or a new file → Generate "first"; a new file → "first" (its words aren't
    counted yet);
  - no plan, a damaged plan, a plan the engine stands aside from (Coverage) → "first": today's path.

What a wrong answer would cost: cards picked by the last Generate's ranks after you moved an episode up (the words you
meet next mined last), or a Generate skipped when a new episode's words were never counted.
"""
import json
import os
import time
from types import SimpleNamespace

import pytest

from app import analyzer, library_store, settings_manager
from app.connect import replan
from app.services import journey
from tests import plan_file_cases as cases


def _settings_file(root, language, **over):
    settings = {"junban_deck": "TheBank", "junban_scope": "deck", "junban_replan_language": language,
                "junban_replan_deck": "TheBank", "junban_order": "content", "target_language": language}
    settings.update(over)
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)


def _generate(root, case, language):
    """A full Generate as the dashboard (and `surasura-cli generate`) starts it, so its signature is the one `current`
    computes in this process."""
    from app import run_args
    cases.generate(root, case, argv=run_args.analyzer_args(_loaded(language), language, headless=True)[1:])


def _loaded(language):
    settings = dict(settings_manager.load_settings())
    settings["target_language"] = language
    return settings


def _library(tmp_path, monkeypatch, case, language):
    root = str(tmp_path / "lib")
    env = cases.child_env(root)
    for name in ("SURASURA_TEST_ROOT", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, env[name])
    cases.build(root, case)
    _settings_file(root, language)
    from app.path_utils import ensure_data_setup, get_data_path, get_user_files_path
    ensure_data_setup(language)
    _generate(root, case, language)
    store = library_store.open_store(language, get_data_path(language), get_user_files_path(language))
    assert store is not None, "the Generate left no library store"
    return root, store


@pytest.fixture
def lib(tmp_path, monkeypatch):
    root, store = _library(tmp_path, monkeypatch, "rp2-ja", "ja")
    yield root, store
    store.close()


@pytest.fixture
def lib_zh(tmp_path, monkeypatch):
    root, store = _library(tmp_path, monkeypatch, "rp2-zh", "zh")
    yield root, store
    store.close()


def _csv_places(language):
    """The pick's ranks as today's path reads them: the last Generate's priority list (`verbs._listed`)."""
    from app.cli import verbs
    return verbs._listed(SimpleNamespace(wait=5.0), language)


def _move_later_to_top(store):
    """A move in the Content Manager: 6+ Months' last item to the top of NOW."""
    item = store.ids("goal")[-1]
    store.move([item], "now", before_id=store.ids("now")[0])
    return item


def _current(store, language="ja"):
    return replan.current(language, _loaded(language), store)


def test_its_own_order_needs_no_generate_and_ranks_as_the_lists_own(lib):
    root, store = lib
    got = _current(store)
    assert got.verdict is None and got.generate == "no", got.reason
    assert got.listed == _csv_places("ja"), "the re-plan of the run's own order ranks as its list"
    assert got.result.rows("content") and got.rows("priority") == got.result.priority


def _a_move_is_a_full_generate(root, store, case, language):
    # why: the whole point of P3.3 — the engine's re-plan stands in for the Generate a move used to cost; were its
    # numbers not the Generate's, Connect would mine (and Junban order) by ranks no list ever had
    before = _csv_places(language)
    _move_later_to_top(store)
    got = _current(store, language)
    assert got.verdict is None and got.generate == "no", got.reason
    assert got.listed != before, "the move changed the ranks (else this proves nothing)"
    assert got.versions["order_version"] == store.versions()["order_version"], "the versions read with the order"
    _generate(root, case, language)                     # the full Generate of the moved order: the referee
    assert journey._differs(got.result, journey._lists()) == "", "the plan columns are the Generate's"
    assert got.listed == _csv_places(language), "the pick's ranks are the Generate's"


def test_a_move_needs_no_generate_and_its_re_plan_is_a_full_generate_of_the_new_order(lib):
    _a_move_is_a_full_generate(*lib, "rp2-ja", "ja")


def test_in_chinese_too_a_moves_re_plan_is_a_full_generate_of_the_new_order(lib_zh):
    _a_move_is_a_full_generate(*lib_zh, "rp2-zh", "zh")


def test_known_words_changed_re_plans_now_and_generates_after_mining(lib):
    root, store = lib
    known = os.path.join(root, "User Files", "ja", "KnownWord.json")
    with open(known, encoding="utf-8") as f:
        data = json.load(f)
    with open(known, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)          # a new stat: the known words "changed"
    os.utime(known, (time.time() + 5, time.time() + 5))
    got = _current(store)
    assert got.verdict == ("replan-now", ("known",)) and got.generate == "after", got.verdict
    assert got.reason == "known" and got.result is not None and got.listed, "mined from the provisional re-plan"


def test_the_level_raised_mines_from_the_list_as_it_is_and_generates_after(lib):
    # why: the engine can't re-cut the list for another level (E3.2 D3), but a raise only adds words — the ones
    # already listed are right to mine from now; a Generate first would hold every card back for a whole analysis
    root, store = lib
    _settings_file(root, "ja", logic={"selection": {"band": "uncommon"}})         # occasional -> uncommon: rarer
    got = _current(store)
    assert got.verdict == ("generate-first", "settings") and got.generate == "after", got.verdict
    assert got.reason == "the level raised (occasional -> uncommon)", got.reason
    assert got.result is None and got.listed is None, "no re-plan: the pick reads the list as it is"


def test_the_level_lowered_generates_first(lib):
    # why: a lowering drops words — mined from the old list, they'd be cards for words the
    # Generate then takes off your list (P2.2: a lowering mines nothing)
    root, store = lib
    _settings_file(root, "ja", logic={"selection": {"band": "common"}})           # occasional -> common: commoner
    got = _current(store)
    assert got.verdict == ("generate-first", "settings") and got.generate == "first", got.verdict


@pytest.mark.parametrize("context", [{"max_chars": 120},              # a setting alone (the settings part)
                                     {"preferred_max_chars": 40}])    # the args too (--context-max)
def test_the_level_raised_with_a_sentence_length_change_generates_first(lib, context):
    # why: only the band put back can be the plan's — another setting with it re-cuts what the old list can't tell
    root, store = lib
    _settings_file(root, "ja", logic={"selection": {"band": "uncommon"}, "context": context})
    got = _current(store)
    assert got.verdict[0] == "generate-first" and got.generate == "first", got.verdict


def test_the_level_raised_with_a_new_file_generates_first(lib):
    # why: a new episode's words are counted by no list yet — the old list would mine around them
    root, store = lib
    from app.path_utils import get_data_path
    with open(os.path.join(get_data_path("ja"), "GoalContent", "new_episode.txt"), "w", encoding="utf-8") as f:
        f.write("新しい話が始まった。今日は学校で友達に会った。\n")
    library_store.sync_for_window(store)
    _settings_file(root, "ja", logic={"selection": {"band": "uncommon"}})
    got = _current(store)
    assert got.verdict == ("generate-first", "files") and got.generate == "first", got.verdict


def test_automatic_raritys_band_moving_rarer_mines_first_and_commoner_generates_first(lib):
    # Automatic rarity: the band in force is the one the store remembers (the signature's `auto_band` part), so a
    # raise there is a raise; a step back to a commoner band is a lowering
    root, store = lib
    from app.path_utils import get_data_path, get_user_files_path
    from app.word_selection import BANDS_ORDER as bands
    # RP-2's bands: Core lists 1 word, every rarer band the same 162 — so Automatic takes Core under 162 words (a
    # rarer band is there to move to) and Native at 850 (a commoner one is)
    for max_words, step, generate in ((100, +1, "after"), (850, -1, "first")):
        _settings_file(root, "ja", logic={"selection": {"auto": True, "auto_max_words": max_words}})
        _generate(root, "rp2-ja", "ja")
        chosen = library_store.read_auto_band("ja", get_data_path("ja"))
        assert chosen == (bands[0] if step > 0 else bands[-1]), chosen
        assert _current(store).generate == "no", "the Generate's own band: nothing moved"
        band = bands[bands.index(chosen) + step]
        assert library_store.record_auto_band("ja", get_data_path("ja"), get_user_files_path("ja"), band, 100)
        got = _current(store)
        assert got.verdict == ("generate-first", "auto_band") and got.generate == generate, (band, got.verdict)


def test_a_new_file_generates_first(lib):
    root, store = lib
    from app.path_utils import get_data_path
    path = os.path.join(get_data_path("ja"), "GoalContent", "new_episode.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("新しい話が始まった。今日は学校で友達に会った。\n")
    library_store.sync_for_window(store)
    got = _current(store)
    assert got.verdict == ("generate-first", "files") and got.generate == "first", got.verdict
    assert got.result is None and got.listed is None


def test_no_plan_or_a_damaged_one_generates_first(lib):
    root, store = lib
    path = os.path.join(root, "results", analyzer.PLAN_FILE)
    with open(path, "wb") as f:
        f.write(b"not a plan")
    got = _current(store)
    assert got.generate == "first" and got.verdict == ("generate-first", "plan") and got.result is None
    os.remove(path)
    got = _current(store)
    assert got.generate == "first" and got.verdict == ("generate-first", "no-plan") and got.listed is None


def test_a_plan_the_engine_stands_aside_from_generates_first(lib):
    # Coverage selection: the list's words depend on the order, so only a Generate can tell (D7)
    root, store = lib
    _settings_file(root, "ja", strategy="coverage")
    _generate(root, "rp2-ja", "ja")
    got = _current(store)
    assert got.verdict == ("stand-aside", "coverage") and got.generate == "first", got.verdict
    assert got.result is None


def test_an_error_reading_the_plan_is_todays_path_never_worse(lib, monkeypatch):
    root, store = lib
    monkeypatch.setattr(analyzer, "run_signature_parts", lambda *a, **k: 1 / 0)
    got = _current(store)
    assert got.generate == "first" and got.verdict == ("generate-first", "error") and got.result is None


def test_its_key_moves_with_a_move_a_new_plan_and_another_run(lib):
    root, store = lib
    got = _current(store)
    assert replan.key(store) == got.key, "nothing moved: the same key"
    _move_later_to_top(store)
    assert replan.key(store) != got.key, "a move"
    moved = replan.key(store)
    stamp = os.path.join(root, "results", analyzer.RUN_STAMP_FILE)
    with open(stamp, "a", encoding="utf-8") as f:
        f.write("x")
    assert replan.key(store) != moved, "another run"

"""K8 (alpha 4, Mattias's note 9; A4K-3 PROVISIONAL): a 2.x library's Goal folder read as one of his library folders
lands in Goal on setup's first look — `library_store._tier_2x`.

What a wrong answer would cost a learner: there is no content migration (Sonic 2026-10-23: shows and books come in
again through library folders), so Mattias pointed setup at his 2.x folders — and his 2,500 Goal items landed in
Current, to be dragged back one by one. His 2.x Goal stays his Goal; HighPriority and LowPriority land in Current as
before (in the order a look reads them); a show that already has rows in Current keeps its run there; a folder merely
NAMED like a tier anywhere else is read as any folder; and a later look (not setup's) still lands in New arrivals.

A synthetic 2.x library beside the alpha's (never Sonic's data): `<drive>/Surasura/User Files/ja/…` and
`…/data/<lang>/GoalContent|HighPriority/<show>/<episode>.srt`, real Japanese / Chinese texts from tests/Test Resources.
"""
import json
import os

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _text, _write  # noqa: F401

SHOWS = {"ja": ("月影の旅人", "星空喫茶"), "zh": ("夜市小记", "清河灯笼")}


def _old_library(language):
    """A 2.x install's folder: its User Files and its data folder's tier folders, one show in Goal, one in NOW."""
    top = os.path.join(_drive("old"), "Surasura")
    with open(os.path.join(_mk(top, "User Files", language), "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({}, f)
    goal_show, now_show = SHOWS[language]
    data = os.path.join(top, "data", language)
    for n in (1, 2, 3):
        _write(os.path.join(data, "GoalContent", goal_show, f"{goal_show} - {n:02d}.srt"),
               _text(language, n, extra=f"「{goal_show}」"))
        _write(os.path.join(data, "HighPriority", now_show, f"{now_show} - {n:02d}.srt"),
               _text(language, n + 3, extra=f"「{now_show}」"))
    return data


def _mk(*parts):
    path = os.path.join(*parts)
    os.makedirs(path, exist_ok=True)
    return path


def _tiers(store):
    return {t: [e["title"] for _i, e, _a in store.ordered(t)] for t in ("now", "soon", "goal", "arrivals")}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_2x_goal_folder_read_at_setup_lands_in_goal_and_its_now_folder_in_current(language):
    store, _data = _empty(language)
    data = _old_library(language)
    goal_show, now_show = SHOWS[language]
    with store:
        for tier_folder in ("GoalContent", "HighPriority"):
            root = store.add_source(os.path.join(data, tier_folder))
            _look(store, language, root, first=True)
        tiers = _tiers(store)
    assert [t for t in tiers["goal"] if goal_show in t] and len(tiers["goal"]) == 3
    assert not any(goal_show in t for t in tiers["now"] + tiers["soon"] + tiers["arrivals"])
    assert len([t for t in tiers["now"] + tiers["soon"] if now_show in t]) == 3


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_later_look_and_a_folder_only_named_like_a_tier_keep_the_usual_places(language):
    store, _data = _empty(language)
    data = _old_library(language)
    goal_show = SHOWS[language][0]
    named = os.path.join(_drive("media"), "GoalContent", goal_show + " 2")      # no 2.x data folder above it
    _write(os.path.join(named, "01.srt"), _text(language, 9, extra="「二期」"))
    with store:
        late = store.add_source(os.path.join(data, "GoalContent"))
        _look(store, language, late)                                            # a look after setup: New arrivals
        mine = store.add_source(os.path.dirname(named))
        _look(store, language, mine, first=True)                                # setup's, but not a 2.x folder
        tiers = _tiers(store)
    assert tiers["goal"] == []
    assert len(tiers["now"] + tiers["soon"]) == 1


def test_the_2x_tier_rule_reads_only_a_data_folders_own_tier_folders():
    sep = os.sep
    assert ls._tier_2x(sep.join(["D:", "Surasura", "data", "ja", "GoalContent", "A", "1.srt"])) == "goal"
    assert ls._tier_2x(sep.join(["D:", "Surasura", "data", "zh", "LowPriority", "A", "1.srt"])) == "soon"
    assert ls._tier_2x(sep.join(["D:", "Media", "GoalContent", "A", "1.srt"])) is None
    assert ls._tier_2x(sep.join(["D:", "data", "en", "GoalContent", "1.srt"])) is None
    assert ls._tier_2x(None) is None



def test_a_tier_folder_is_known_whatever_its_case():
    sep = os.sep
    assert ls._tier_2x(sep.join(["D:", "surasura", "Data", "JA", "goalcontent", "A", "1.srt"])) == "goal"



@pytest.mark.parametrize("order", [("GoalContent", "HighPriority"), ("HighPriority", "GoalContent")])
def test_a_show_split_between_2x_tiers_keeps_its_split_whichever_folder_is_picked_first(order):
    """The adversary's #1: a show partly moved up in 2.x (episode 1 in HighPriority, 2–3 in GoalContent) lands the
    same way in either pick order — its Goal episodes in Goal, never pulled into Current by the order of the picks."""
    language = "ja"
    store, _data = _empty(language)
    top = os.path.join(_drive("old"), "Surasura")
    with open(os.path.join(_mk(top, "User Files", language), "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({}, f)
    data = os.path.join(top, "data", language)
    show = SHOWS[language][0]
    _write(os.path.join(data, "HighPriority", show, f"{show} - 01.srt"), _text(language, 1, extra="「一」"))
    for n in (2, 3):
        _write(os.path.join(data, "GoalContent", show, f"{show} - {n:02d}.srt"), _text(language, n, extra="「二」"))
    with store:
        for tier_folder in order:
            root = store.add_source(os.path.join(data, tier_folder))
            _look(store, language, root, first=True)
        tiers = _tiers(store)
    assert len(tiers["goal"]) == 2 and len(tiers["now"] + tiers["soon"]) == 1

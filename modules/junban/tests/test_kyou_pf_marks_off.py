# SPDX-License-Identifier: GPL-3.0-or-later
"""Kyou-PF (Sonic 2026-11-20): Junban takes its own purple flag and `::later` tag off when they stop being true.

Sonic kept studying cards with purple flags: Junban flags a card purple (and tags it `Surasura::later`) when its word
is not on the list, and nothing ever took the flag off — not when the word came back (a parked card's tag came off,
#50, its flag stayed; a card only marked kept both), not once the card was studied. On his cards: 876 purple, at least
63 of them on the list again or studied. His rulings:

1. A card the list places again, or one you've studied, loses Junban's purple flag (the flag from before it back) and
   its `::later` tag — only a flag Junban's record says it put on (`first_touch.flagged`); never one you set.
2. A card Junban parked comes back when its word does, whatever *Set cards aside* says now.
3. The first clean-up waits for one press in 順 (the preview says it; Restore is its Undo); automatic runs keep it
   right after that.

What a wrong answer costs: a purple card at the front of his queue saying "not on your list" (the bug), a flag he set
himself wiped, a card he suspended himself unsuspended, or a clean-up of hundreds of cards he never saw coming.
Against the fake AnkiConnect collection (real Japanese words on Lapis fields; never Anki).
"""
import json
import os

import pytest

from modules.junban import auto, first_touch, junban_view, reposition, spaced, undo, unlisted
from modules.junban.tests.connect_scene import ConnectCollection, _has_tag, scene
from modules.junban.tests.connect_scene import settings as connect_settings
from modules.junban.tests.test_reposition import FIRST_CARD, _patched

LATER = "Surasura::later"
PURPLE = unlisted.FLAG_PURPLE

# (word, sentence, FreqSort, tags, queue): 散歩 / 冒険 / 走る are on the list (`_JOURNEY`), 須藤 is not, 老婆 is parked and
# on the list again, 図書館 is the one you studied.
ENTRIES = [
    ("散歩", "毎朝<b>散歩</b>に出かける。", 3000, [LATER], 0),      # Junban's purple; its word is back on the list
    ("冒険", "冒険が始まった。", 2000, [], 0),                        # on the list, purple — but you flagged it
    ("須藤", "須藤さんが来た。", 9000, [LATER], 0),                   # Junban's purple; still not on the list
    ("図書館", "図書館で本を読んだ。", 6000, [LATER], 0),             # Junban's purple; studied since
    ("老婆", "老婆が笑った。", 7000, [LATER], -1),                    # parked by Junban (purple too); on the list again
]


@pytest.fixture(autouse=True)
def _studied_read_unpaced():
    """Each test starts with no automatic job having read the studied cards (the pacing memo is the process's)."""
    reposition._STUDIED_AT.clear()
    yield
    reposition._STUDIED_AT.clear()


class StudiedCollection(ConnectCollection):
    """The scene's collection, also answering the clean-up's read of the cards you studied
    (`deck:"X" -is:new (flag:7 OR "tag:…")`) as Anki would."""

    def _dispatch(self, action, params):
        query = params.get("query", "")
        if action == "findCards" and "-is:new" in query:
            deck = query.split('deck:"')[1].split('"')[0]
            tag = query.split('"tag:')[1].split('"')[0]
            return sorted(c["cardId"] for c in self.cards.values()
                          if (c["deckName"] == deck or c["deckName"].startswith(deck + "::")) and c["type"] != 0
                          and (c.get("flags") == PURPLE or _has_tag(self.notes[c["note"]].get("tags"), tag)))
        return super()._dispatch(action, params)


def _scene(tmp_path, entries=None):
    fake = scene(tmp_path, ENTRIES if entries is None else entries)
    fake.__class__ = StudiedCollection
    for word in ("散歩", "冒険", "須藤", "図書館", "老婆"):
        try:
            fake.card_of(word)["flags"] = PURPLE
        except KeyError:
            pass
    try:
        studied = fake.card_of("図書館")
        studied.update(type=2, queue=2, due=400)       # a review card now: its due is a day number
    except KeyError:
        pass
    return fake


def _journal(fake, words=("散歩", "須藤", "図書館", "老婆"), since=FIRST_CARD, parked=("老婆",), swept=False):
    """The first-touch journal as earlier runs left it: Junban flagged `words` purple (from no flag) and tagged them,
    and parked `parked` — the first line at `since` (ms; a card made after it that the record never names is yours)."""
    lines = [{"flags": {str(fake.card_of(w)["cardId"]): [0, PURPLE] for w in words},
              "tags": {LATER: [fake.card_of(w)["note"] for w in words]}}]
    if parked:
        lines.append({"suspended": [fake.card_of(w)["cardId"] for w in parked], "landed": True, "with_tag": LATER})
    if swept:
        lines.append({first_touch.SWEPT: True})
    path = os.path.join(first_touch.folder("ja"), first_touch.JOURNAL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for n, items in enumerate(lines):
            f.write(json.dumps(dict({"at": "2026-11-01T09:00:00", "ms": since + n, "kind": "reorder",
                                     "profile": "DevTest", "deck": ["TheBank"]}, **items), ensure_ascii=False) + "\n")


def _tags(fake, word):
    return [str(t).lower() for t in fake.notes[fake.card_of(word)["note"]].get("tags") or ()]


def _flag(fake, word):
    return fake.card_of(word).get("flags") or 0


def _window_run(fake, **over):
    """A Reorder you press in the 順 window: its own job (`junban_view.window_job`), not automatic."""
    with _patched(fake):
        return reposition.run(connect_settings(**over), job=junban_view.window_job({}))


def _automatic(fake, **over):
    """The window's re-order host's job (`replan_preview.Host._write`): the settings decided as 順's automatic step
    decides them (`junban_auto_actions` on), an automatic spaced job applying them. (Connect's own step runs
    unattended, and never cleans: it only reorders, and suspends as the setting says.)"""
    chosen = auto.decide_actions(connect_settings(**dict({"junban_auto_actions": True}, **over)))
    job = spaced.Job(automatic=True)
    job.actions = True
    with _patched(fake):
        report = reposition.run(chosen, refresh=False, job=job)
    assert report["ok"], report["problems"]
    return report


# --- ruling 1: a card back on the list, or studied, loses Junban's purple and its tag ------------------------------ #
def test_a_card_back_on_the_list_loses_junbans_purple_flag_and_later_tag(tmp_path):
    fake = _scene(tmp_path)
    _journal(fake)
    report = _window_run(fake)
    assert report["ok"], report["problems"]
    assert _flag(fake, "散歩") == 0, "its word is on the list: no longer 'not on your list'"
    assert LATER.lower() not in _tags(fake, "散歩")
    assert "Back on your list or studied: took the purple flag off" in report["message"], report["message"]


def test_a_card_you_studied_loses_junbans_purple_flag_and_later_tag(tmp_path):
    fake = _scene(tmp_path)
    _journal(fake)
    _window_run(fake)
    assert _flag(fake, "図書館") == 0, "studied: the mark has done its job"
    assert LATER.lower() not in _tags(fake, "図書館")
    assert fake.card_of("図書館")["due"] == 400, "a review card's due is never touched"


def test_a_purple_flag_you_set_yourself_stays(tmp_path):
    # 冒険 is on the list and purple, but the record never names it and it was made after the record began: yours
    fake = _scene(tmp_path)
    _journal(fake)
    _window_run(fake)
    assert _flag(fake, "冒険") == PURPLE


def test_a_card_still_not_on_the_list_keeps_its_purple_flag_and_tag(tmp_path):
    fake = _scene(tmp_path)
    _journal(fake)
    _window_run(fake)
    assert _flag(fake, "須藤") == PURPLE and LATER.lower() in _tags(fake, "須藤"), "still true: not on your list"


def test_a_flag_put_back_by_a_restore_since_is_not_junbans_any_more(tmp_path):
    # the record's chain: Junban put purple on 散歩, a Restore took it off ([7, 0]), then you flagged it purple yourself
    fake = _scene(tmp_path)
    _journal(fake)
    path = os.path.join(first_touch.folder("ja"), first_touch.JOURNAL)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ms": FIRST_CARD + 9, "kind": "restore", "profile": "DevTest", "deck": ["TheBank"],
                            "flags": {str(fake.card_of("散歩")["cardId"]): [PURPLE, 0]}}) + "\n")
    _window_run(fake)
    assert _flag(fake, "散歩") == PURPLE, "the purple on it now is yours"


def test_a_card_from_before_the_record_whose_purple_a_restore_took_off_is_yours_once_you_flag_it_again(tmp_path):
    # mutant M14: the record names 散歩 (Restore took Junban's purple off it: [7, 0]); you flagged it purple since — the
    # fallback for a card made before the record never reaches a card the record names
    fake = _scene(tmp_path)
    _journal(fake, words=(), parked=("老婆",), since=FIRST_CARD + 10_000)
    path = os.path.join(first_touch.folder("ja"), first_touch.JOURNAL)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ms": FIRST_CARD + 10_009, "kind": "restore", "profile": "DevTest", "deck": ["TheBank"],
                            "flags": {str(fake.card_of("散歩")["cardId"]): [PURPLE, 0]}}) + "\n")
    _window_run(fake)
    assert _flag(fake, "散歩") == PURPLE, "the purple on it now is yours"


def test_with_no_record_a_purple_card_carrying_the_later_tag_made_before_it_is_junbans(tmp_path):
    # a flag Junban put on before its record began: the `::later` tag beside it says Junban's (`connect.junbans`' rule)
    fake = _scene(tmp_path)
    _journal(fake, words=(), parked=("老婆",), since=FIRST_CARD + 10_000)   # every card made before the record
    _window_run(fake)
    assert _flag(fake, "散歩") == 0, "made before the record, purple with Junban's tag: Junban's"
    assert _flag(fake, "冒険") == PURPLE, "purple without Junban's tag: yours"


def test_a_purple_from_before_the_record_comes_off_again_after_restore_put_it_back(tmp_path):
    # review (state lens): the clean-up journals [7, 0], Restore [0, 7] — a chain that starts from purple; Junban only
    # ever flags an unflagged card, so that purple is still its own, and the next clean-up takes it off again
    fake = _scene(tmp_path)
    _journal(fake, words=(), parked=("老婆",), since=FIRST_CARD + 10_000)   # 散歩's purple is from before the record
    settings = connect_settings()
    _window_run(fake)
    assert _flag(fake, "散歩") == 0
    with _patched(fake):
        assert reposition.restore(settings, confirmed=True)["ok"]
    assert _flag(fake, "散歩") == PURPLE
    _window_run(fake)
    assert _flag(fake, "散歩") == 0, "still Junban's purple: off again"


def test_the_preview_says_it_before_anything_is_written(tmp_path):
    fake = _scene(tmp_path)
    _journal(fake)
    with _patched(fake):
        _writes, stats = reposition.dry_run(connect_settings(), job=junban_view.window_job({}))
    clear = stats["clear"]
    assert clear["counts"] == {"flag": 3, "tag": 2}, clear     # 散歩 + 図書館 + 老婆's flags; 散歩's + 図書館's tags
    assert junban_view.clear_clause(stats) == (" Back on your list or studied: take the purple flag off 3 cards and "
                                              "the 'Surasura::later' tag off 2 notes.")
    assert fake.flag_writes == [] and not [c for c in fake.tag_calls if c[0] == "removeTags"], "a preview writes nothing"


def test_restore_puts_the_purple_flags_and_tags_back(tmp_path):
    fake = _scene(tmp_path)
    _journal(fake)
    settings = connect_settings()
    _window_run(fake)
    with _patched(fake):
        done = reposition.restore(settings, confirmed=True)
    assert done["ok"], done
    for word in ("散歩", "図書館"):
        assert _flag(fake, word) == PURPLE and LATER.lower() in _tags(fake, word), word
    # …and the record calls them Junban's again: the next clean-up takes them off again
    record = first_touch.flagged("ja")
    assert fake.card_of("散歩")["cardId"] in record["cards"]


def test_the_record_no_longer_calls_a_flag_junbans_once_it_came_off(tmp_path):
    fake = _scene(tmp_path)
    _journal(fake)
    _window_run(fake)
    record = first_touch.flagged("ja")
    assert fake.card_of("散歩")["cardId"] not in record["cards"]
    assert fake.card_of("須藤")["cardId"] in record["cards"], "still purple, still Junban's"


def test_a_flag_you_changed_after_the_preview_is_left_as_you_set_it(tmp_path):
    fake = _scene(tmp_path)
    _journal(fake)
    with _patched(fake):
        _writes, stats = reposition.dry_run(connect_settings(), job=junban_view.window_job({}))
    fake.card_of("散歩")["flags"] = 1                # you flagged it red meanwhile
    from app import anki_connect
    url = reposition._url(connect_settings())
    held, problem = anki_connect.take_writer("Kyou-PF's test", url)
    assert held is not None, problem
    with _patched(fake), held:
        done, failures, _ = reposition._apply_clear(url, stats["clear"], 150)
    assert _flag(fake, "散歩") == 1 and fake.card_of("散歩")["cardId"] not in done["flag"]
    assert not failures


# --- ruling 2: a parked card comes back when its word does, *Set cards aside* on or off ---------------------------- #
def test_with_set_cards_aside_off_a_card_junban_parked_comes_back_without_its_marks(tmp_path):
    fake = _scene(tmp_path)
    _journal(fake)
    report = _window_run(fake, junban_later_suspend=False)
    assert report["ok"], report["problems"]
    card = fake.card_of("老婆")
    assert card["queue"] == 0, "its word is back: unsuspended, though Set cards aside is off now"
    assert _flag(fake, "老婆") == 0 and LATER.lower() not in _tags(fake, "老婆")


def test_with_set_cards_aside_off_and_no_record_a_tagged_card_you_suspended_stays(tmp_path):
    # P1.4-adversary #3's case: with the suspend setting off and nothing recorded, a suspended card carrying the tag
    # may be one you suspended after Junban only tagged it — the record alone decides, so it stays
    fake = _scene(tmp_path)
    report = _window_run(fake, junban_later_suspend=False)
    assert report["ok"], report["problems"]
    assert fake.card_of("老婆")["queue"] == -1
    assert not [call for call in fake.suspend_calls if call[0] == "unsuspend"]


def test_a_run_reads_the_journal_once_for_its_flags_and_its_parked_cards(tmp_path, monkeypatch):
    # Kyou-KN (train 50's intent keeper, waste): the record of Junban's flags (does a clean-up run?) and of what it
    # parked (does a card come back?) are one read of changes.jsonl — it was read twice a run, and it only grows
    fake = _scene(tmp_path)
    _journal(fake)
    reads = []
    real = first_touch.journal
    monkeypatch.setattr(first_touch, "journal", lambda language: reads.append(language) or real(language))
    with _patched(fake):
        _writes, stats = reposition.dry_run(connect_settings(junban_later_suspend=False), job=junban_view.window_job({}))
    assert reads == ["ja"], reads
    # …and the parked cards it read are the record's own: 老婆 comes back by it, Set cards aside off
    assert first_touch.flagged("ja")["parked"] == first_touch.parked("ja")
    assert fake.card_of("老婆")["cardId"] in first_touch.parked("ja")["cards"]
    assert stats["clear"]["counts"]["flag"] == 3, stats["clear"]


def test_an_unreadable_journal_is_each_records_safe_side_from_one_read(tmp_path, monkeypatch):
    # the journal there but held: no flag Junban's, no clean-up done, no card Junban's to bring back — as `parked` alone
    fake = _scene(tmp_path)
    _journal(fake)
    real_open = open

    def held(path, *args, **kwargs):
        if str(path).endswith(first_touch.JOURNAL):
            raise PermissionError(13, "held by another program")
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr("builtins.open", held)
    record = first_touch.flagged("ja")
    assert record["cards"] == {} and record["since"] == 0 and record["swept"] is False
    assert record["parked"] == first_touch.parked("ja") == {"cards": set(), "named": set(), "notes": set(), "since": 0}


# --- ruling 3: the first clean-up waits for one press in 順 -------------------------------------------------------- #
def test_an_automatic_run_leaves_the_first_clean_up_to_a_press_in_junban(tmp_path):
    fake = _scene(tmp_path)
    _journal(fake)
    _automatic(fake, junban_later_suspend=False)
    assert _flag(fake, "散歩") == PURPLE and _flag(fake, "図書館") == PURPLE, "not yet: you haven't seen it"
    assert fake.card_of("老婆")["queue"] == -1, "nor does a parked card come back with Set cards aside off"
    assert not first_touch.swept("ja")


def test_after_the_first_press_automatic_runs_keep_the_marks_right(tmp_path):
    fake = _scene(tmp_path)
    _journal(fake, swept=True)                      # a run you started in 順 did the first clean-up
    _automatic(fake, junban_later_suspend=False)
    assert _flag(fake, "散歩") == 0 and _flag(fake, "図書館") == 0
    assert fake.card_of("老婆")["queue"] == 0 and _flag(fake, "老婆") == 0


def test_an_automatic_job_reads_the_studied_cards_at_most_once_every_ten_minutes(tmp_path, monkeypatch):
    # the waste lens: the host's job runs at every move; the studied cards change only as you review
    clock = [1000.0]
    monkeypatch.setattr(reposition.time, "monotonic", lambda: clock[0])
    fake = _scene(tmp_path)
    _journal(fake, swept=True)

    def studied_reads():
        return [r for r in fake.requests if r["action"] == "findCards" and "-is:new" in r["params"]["query"]]
    _automatic(fake)
    assert len(studied_reads()) == 1 and _flag(fake, "図書館") == 0
    _automatic(fake)
    assert len(studied_reads()) == 1, "a minute later: not read again"
    clock[0] += reposition.STUDIED_EVERY_S
    _automatic(fake)
    assert len(studied_reads()) == 2
    _window_run(fake)
    assert len(studied_reads()) == 3, "a run you start always reads them"


def test_a_press_whose_clean_up_did_not_land_leaves_the_first_clean_up_owed(tmp_path, monkeypatch):
    # the review: the mark says the clean-up was done — not when Anki refused it
    from modules.junban import ankiconnect
    fake = _scene(tmp_path)
    _journal(fake)
    monkeypatch.setattr(ankiconnect, "remove_tags",
                        lambda url, notes, tag, chunk=150: ([], [(n, "Anki refused") for n in notes or ()]))
    _window_run(fake)
    assert not first_touch.swept("ja")


def test_a_press_in_junban_marks_the_first_clean_up_done_even_with_nothing_to_take_off(tmp_path):
    fake = _scene(tmp_path, [ENTRIES[1]])           # only 冒険, your own purple: nothing of Junban's to take off
    _journal(fake, words=(), parked=())
    report = _window_run(fake)
    assert report["ok"], report["problems"]
    assert first_touch.swept("ja")


def test_a_positions_only_run_takes_nothing_off(tmp_path):
    # `junban_auto_actions` off: the host's job moves positions only (`decide_actions` strips the actions; with Connect
    # on it keeps *Set cards aside*, which brings a parked card back by itself — off here, so nothing does)
    fake = _scene(tmp_path)
    _journal(fake, swept=True)
    _automatic(fake, junban_auto_actions=False, junban_later_suspend=False)
    assert _flag(fake, "散歩") == PURPLE and fake.flag_writes == []
    assert fake.card_of("老婆")["queue"] == -1


def test_with_connect_on_a_positions_only_job_still_takes_no_flag_off(tmp_path):
    # `decide_actions` keeps *Set cards aside* for it while Connect is on — still positions only for the clean-up
    fake = _scene(tmp_path)
    _journal(fake, swept=True)
    _automatic(fake, junban_auto_actions=False)
    assert _flag(fake, "散歩") == PURPLE and _flag(fake, "図書館") == PURPLE
    assert not any(write[1] == 0 for write in fake.flag_writes)


def test_connects_own_step_never_cleans(tmp_path):
    # unattended (Connect's `junban --auto`): it reorders, and suspends as the setting says — nothing of the clean-up
    fake = _scene(tmp_path)
    _journal(fake, swept=True)
    with _patched(fake):
        done = auto.reorder(connect_settings(junban_auto_reorder=True, junban_auto_actions=True), list_current=True)
    assert done["outcome"] == "ran", done
    assert _flag(fake, "散歩") == PURPLE and _flag(fake, "図書館") == PURPLE


def test_a_run_without_the_window_or_an_automatic_job_is_still_2_5s(tmp_path):
    # 2.x's job-less run (the 2.5 gate's own path) takes nothing off: `test_preview_gate.py` pins it byte for byte
    fake = _scene(tmp_path)
    _journal(fake, swept=True)
    with _patched(fake):
        reposition.run(connect_settings())
    assert _flag(fake, "散歩") == PURPLE and _flag(fake, "図書館") == PURPLE


# --- the plan itself: Japanese and Chinese alike --------------------------------------------------------------------- #
class _Row:
    def __init__(self, card_id, note_id, word, tier, pinned=None):
        self.card_id, self.note_id, self.word, self.tier, self.pinned = card_id, note_id, word, tier, pinned


def _owner_all(_card_id, carries):
    return 0 if carries else None


def test_the_plan_reads_a_chinese_word_on_the_list_by_any_form():
    # 学习 is on the list (its row), 图书馆 is not; 爷爷 was put away by this run (`later`): never cleared beside it
    order = [_Row(1, 11, "学习", "rare"), _Row(2, 12, "图书馆", "rare"), _Row(3, 13, "爷爷", "rare")]
    notes = {11: {"tags": [LATER]}, 12: {"tags": [LATER]}, 13: {"tags": [LATER]}}
    clear = unlisted.plan_clear(order, {"学习": set()}, "zh", {1: PURPLE, 2: PURPLE, 3: PURPLE}, notes, _owner_all,
                                later={"cards": [3], "note_of": {3: 13}, "tag_notes": []})
    assert clear["flags"] == {1: 0} and clear["tag_notes"] == [11]


def test_the_plan_never_touches_a_card_you_left_alone_or_took_off_the_list():
    order = [_Row(1, 11, "散歩", "list"), _Row(2, 12, "冒険", "list")]
    notes = {11: {"tags": [LATER]}, 12: {"tags": [LATER]}}
    clear = unlisted.plan_clear(order, {"散歩": set(), "冒険": set()}, "ja", {1: PURPLE, 2: PURPLE}, notes, _owner_all,
                                exclude={1}, taken_off={2})
    assert clear == {}


def test_the_plan_keeps_the_tag_on_a_note_whose_other_card_stays_parked():
    order = [_Row(1, 11, "散歩", "list")]
    clear = unlisted.plan_clear(order, {"散歩": set()}, "ja", {1: PURPLE}, {11: {"tags": [LATER]}}, _owner_all,
                                keep_notes={11})
    assert clear["flags"] == {1: 0} and clear["tag_notes"] == []


def test_the_plan_puts_back_the_flag_from_before_junbans():
    order = [_Row(1, 11, "散歩", "list")]
    clear = unlisted.plan_clear(order, {"散歩": set()}, "ja", {1: PURPLE}, {11: {"tags": []}},
                                lambda card_id, carries: 3)          # it was green before Junban's purple
    assert clear["flags"] == {1: 3}


def test_a_snapshot_restores_only_flags_still_as_the_clean_up_left_them():
    saved = {"flags_off": {"1": 0, "2": 0, "3": 3, "4": 0}, "flags": {"4": 0}}
    pairs, skipped = undo.restore_flags_off(saved, {1: 0, 2: 1, 3: 3, 4: 0}, PURPLE)
    assert pairs == [(1, PURPLE), (3, PURPLE)] and skipped == 1, "card 2 you flagged red since: yours"
    # card 4: a cut run put Junban's purple on it and this one took it off — `restore_flags` puts back the flag from
    # before both (one Undo, both runs), never purple again

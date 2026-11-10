# SPDX-License-Identifier: GPL-3.0-or-later
"""Connect's ordering step (P1.4 row 1.4.8): after a batch, `surasura-cli junban --auto` places the batch's new cards —
positions only in 2.6 / 2.7 (G1.3-8) — with every guard of the automatic reorder, and a snapshot of its own.

§7.2's "same word" rule on this path: the step records no answer (only the 順 window asks, and saves them before its
Reorder writes); it plans on the answers already saved — a "yes" places a card with the list — and leaves the answers
file exactly as it found it.

E2.1 (Haya's spaced numbering) changes what numbers the step writes, not which cards it places or in what order: once
it lands, this file's order checks hold as they are (the numbers are E2.1's own tests' subject).

The scene (`connect_scene`) plus job 2's batch arriving at the back of the deck; the command line called in this
process, Anki a fake behind the patched transport.
"""
import io
import json
import os

import pytest

from modules.junban import pairs, undo
from modules.junban.tests.connect_scene import CONNECT_TAG, scene, settings
from modules.junban.tests.test_reposition import URL, _patched

BATCH_TAG = "surasura::connect::job-20261006-2"


def _batch(fake, words):
    """Job 2's new notes, mined after everything else, at the back of the deck."""
    added = []
    for word in words:
        note_id, card_id = max(fake.notes) + 1, max(fake.cards) + 1
        fake.notes[note_id] = {"noteId": note_id, "modelName": "Lapis", "tags": [BATCH_TAG], "fields": {
            "Expression": {"value": word, "order": 0}, "Sentence": {"value": f"<b>{word}</b>だ。", "order": 1},
            "FreqSort": {"value": "500", "order": 2}, "MiscInfo": {"value": "", "order": 3}}}
        fake.cards[card_id] = {"cardId": card_id, "note": note_id, "due": 3000 + len(added), "type": 0, "queue": 0,
                               "deckName": "TheBank"}
        added.append(card_id)
    return added


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """`surasura-cli` in this process, on the scene's saved settings (the preview on), the list current."""
    from app import analyzer
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(analyzer, "journey_is_current", lambda argv, lang: True)

    def call(*argv, **over):
        # 3.0: 順 has recorded its deck for Japanese — without the pair, every automatic Junban write stands aside
        saved = settings(**{"junban_replan_language": "ja", **over})
        if "junban_replan_deck" not in over:
            saved["junban_replan_deck"] = saved.get("junban_deck")
        saved.pop("junban_url", None)
        saved["anki_connect_url"] = URL
        with open(os.path.join(str(tmp_path), "settings.json"), "w", encoding="utf-8") as f:
            json.dump(saved, f, ensure_ascii=False)
        from app.cli import __main__ as main
        out = io.StringIO()
        code = main.main(list(argv), out=out)
        return code, json.loads(out.getvalue().splitlines()[-1])
    return call


@pytest.fixture
def two_x(monkeypatch):
    """2.6 / 2.7's rule, held here with the 3.0 line's flags off: an unattended run only reorders (G1.3-8), and Connect
    on strips the actions (HY-6's flag, `UNATTENDED_ACTIONS`, is the 3.0 line's)."""
    from modules.junban import connect
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", False)
    monkeypatch.setattr(connect, "UNATTENDED_ACTIONS", False)


def test_after_a_batch_the_step_places_its_cards_by_the_list_positions_only(tmp_path, cli, two_x):
    fake = scene(tmp_path)
    batch = _batch(fake, ["散歩", "須藤"])
    with _patched(fake):
        code, line = cli("junban", "--auto")
    assert code == 0, line
    assert line["moves"] > 0 and line["undo"].startswith("reorder-")
    assert fake.suspend_calls == [] and fake.tag_calls == [] and fake.flag_writes == [], "positions only"
    assert not {"reloadCollection", "guiDeckBrowser"} & set(fake.action_names), "never pulls you out of Anki"
    order = fake.queue_order()
    assert order[0] == "走る", "your own card first"
    # Job 2's 散歩 joins the list's 散歩 (file 1); its 須藤, on no list, goes with the cards placed by their sentence —
    # i+1 here, by its FreqSort (500) ahead of 眼鏡 (5,000).
    assert order[:5] == ["走る", "冒険", "散歩", "散歩", "須藤"]
    # 2.x-dev keeps `== 冒険's due + 2` here (the preview off: 2.5's dense block, one number a card); 3.0 (Haya's G2b):
    # the step numbers spaced always, so only the order is the step's to keep — the numbers are E2.1's
    assert fake.card_of("冒険")["due"] < fake.cards[batch[0]]["due"] < fake.cards[batch[1]]["due"] < \
        fake.card_of("眼鏡")["due"]
    saved = undo.load("ja", run_id=line["undo"])
    assert saved["complete"] is True and set(map(int, saved["cards"])) == {c for c, _ in fake.writes}
    assert not os.path.exists(undo.snapshot_path("ja")), "the window's Restore point is untouched"


def test_the_step_plans_on_the_answers_you_saved_and_never_writes_them(tmp_path, cli):
    """A "yes" you gave in 順 (大冒険 is 冒険) places job 2's 大冒険 with the list; the answers file is unchanged."""
    fake = scene(tmp_path)
    batch = _batch(fake, ["大冒険"])
    pairs.record("ja", [("大冒険", "冒険", True, "you")])
    path = pairs.pairs_path("ja")
    before = open(path, "rb").read()
    with _patched(fake):
        code, line = cli("junban", "--auto")
    assert code == 0, line
    assert open(path, "rb").read() == before
    assert fake.cards[batch[0]]["due"] < fake.card_of("散歩")["due"], "with the list's 冒険, ahead of 散歩"


def test_the_step_keeps_every_guard_of_the_automatic_reorder(tmp_path, cli):
    fake = scene(tmp_path)
    with _patched(fake):
        code, line = cli("junban", "--auto", junban_scope="all")
    assert code == 4 and line["code"] == "needs-you"
    fake.reviewing = True
    with _patched(fake):
        code, line = cli("junban", "--auto")
    assert code == 3 and line["code"] == "anki-busy"
    assert fake.writes == []


def test_on_3_0_with_the_preview_off_the_step_is_a_spaced_automatic_reorder_with_nothing_of_connects(tmp_path, cli):
    # 2.x-dev keeps 2.5's automatic reorder here (test_with_the_preview_off_the_step_is_2_5s_automatic_reorder: dense,
    # the window's snapshot, `undo` = junban_undo.json); 3.0 (Haya's G2b): spaced always — an automatic job keeps
    # today's baseline (E1.1 03 §5), never the window's Restore point. Still nothing of Connect's: no run snapshot,
    # no look for its notes
    fake = scene(tmp_path)
    with _patched(fake):
        code, line = cli("junban", "--auto", preview=False)
    assert code == 0 and line["undo"] == undo.FILENAMES["baseline"], line
    assert undo.load("ja") is None and undo.load("ja", "baseline")
    assert not os.path.isdir(undo.runs_folder("ja")) or os.listdir(undo.runs_folder("ja")) == []
    assert "findNotes" not in fake.action_names


def _review_starts_after(fake, asks):
    """You open a review in Anki once Surasura has asked `asks` time(s) whether you are reviewing."""
    seen = []

    def answer(self):
        seen.append(1)
        return len(seen) > asks
    fake.__class__ = type("ReviewStartsLater", (type(fake),),
                          {"reviewing": property(answer, lambda self, value: None)})
    return seen


def test_a_review_started_while_the_step_planned_is_never_written_into(tmp_path, cli):
    """The automatic reorder asks before it plans; planning takes seconds, so the step asks again inside the writer's
    hold, right before its snapshot (review P1.4-adversary #4): nothing written, no run snapshot."""
    fake = scene(tmp_path)
    _batch(fake, ["散歩"])
    seen = _review_starts_after(fake, 1)
    with _patched(fake):
        code, line = cli("junban", "--auto")
    assert code == 3 and line["code"] == "anki-busy"
    assert len(seen) == 2 and fake.writes == [] and fake.suspend_calls == []
    assert not os.path.isdir(undo.runs_folder("ja")) or os.listdir(undo.runs_folder("ja")) == []


def test_with_the_preview_on_the_dashboards_automatic_reorder_only_reorders_whatever_its_test_option_says(
        tmp_path, two_x):
    """G1.3-8: in 2.x every unattended run only reorders — the dashboard's automatic reorder too, with its
    settings.json-only `junban_auto_actions` on (review P1.4-intent-keeper D2, adversary #12)."""
    from modules.junban import auto
    fake = scene(tmp_path)
    with _patched(fake):
        done = auto.reorder(settings(junban_auto_actions=True), list_current=True)
    assert done["outcome"] == "ran", done
    assert fake.writes, "it still reorders"
    assert fake.suspend_calls == [] and fake.tag_calls == [] and fake.flag_writes == [], "positions only"


def test_on_3_0_after_a_batch_the_step_places_its_cards_then_suspends_as_your_setting_says(tmp_path, cli):
    # 2.x-dev: positions only (test_after_a_batch_the_step_places_its_cards_by_the_list_positions_only, held above with
    # the flag off); 3.0 (G1.3-8, W3.5 row 7, Haya's G2b): the step's spaced job carries the actions `auto.reorder`
    # decided — positions only plus Junban's suspend setting (on in the scene): every card off the list suspended and
    # tagged `::later` (never flagged: positions_only), the returning 老婆 unsuspended, all in the run's own snapshot
    fake = scene(tmp_path)
    batch = _batch(fake, ["散歩", "須藤"])
    with _patched(fake):
        code, line = cli("junban", "--auto")
    assert code == 0, line
    off = sorted([fake.card_of("須藤")["cardId"], fake.card_of("図書館")["cardId"], fake.card_of("眼鏡")["cardId"],
                  batch[1]])
    assert [ids for action, ids in fake.suspend_calls if action == "suspend"] == [off]
    assert ("unsuspend", [fake.card_of("老婆")["cardId"]]) in fake.suspend_calls
    assert fake.flag_writes == [], "positions only and the suspend setting: no flag"
    assert {tag for _action, _notes, tag in fake.tag_calls} == {"Surasura::later"}
    assert not {"reloadCollection", "guiDeckBrowser"} & set(fake.action_names), "never pulls you out of Anki"
    # Yours first, in the order you mined them — the scene's 老婆 too (no Connect tag, mined after Connect's first
    # card) — then the list's
    assert fake.queue_order()[:5] == ["走る", "老婆", "冒険", "散歩", "散歩"]
    assert fake.card_of("冒険")["due"] < fake.cards[batch[0]]["due"] < fake.cards[batch[1]]["due"] < \
        fake.card_of("眼鏡")["due"], "every card placed before the suspend"
    saved = undo.load("ja", run_id=line["undo"])
    assert saved["complete"] is True and saved["suspended"] == off
    assert saved["unsuspended"] == [fake.card_of("老婆")["cardId"]]
    assert not os.path.exists(undo.snapshot_path("ja")), "the window's Restore point is untouched"


def test_on_3_0_with_the_preview_on_the_dashboards_automatic_reorder_suspends_as_your_setting_says(tmp_path):
    # 2.x-dev: positions only whatever `junban_auto_actions` says (the test above, held with the flags off); 3.0
    # (G1.3-8, Haya's G2b): Junban's suspend setting is followed, and with no run id the window's snapshot is the one
    # restore point, as 2.5's automatic step kept. HY-6 (P3.3, `connect.UNATTENDED_ACTIONS`): Connect on no longer
    # strips your actions — with `junban_auto_actions` on, the flag comes with the suspend, as with Connect off
    from modules.junban import auto
    fake = scene(tmp_path)
    with _patched(fake):
        done = auto.reorder(settings(junban_auto_actions=True), list_current=True)
    assert done["outcome"] == "ran", done
    assert fake.writes and fake.flag_writes
    assert "Surasura::later" in {tag for _action, _notes, tag in fake.tag_calls}
    suspended = sorted(c for action, ids in fake.suspend_calls if action == "suspend" for c in ids)
    assert suspended and undo.load("ja")["suspended"] == suspended
    assert undo.load("ja", "baseline") is None

"""Kantan-MO (the mining model, Sonic 2026-11-21; TheForge `tracks/logic/work/mining-ordering/MODEL.md` + ADVERSARY.md):
Connect's side.

Three things decided what a learner studies and they overlapped — Level, Connect's *Words to make cards from* (Your
list / Every new word / Only i+1) and 順's *Order*. A tester picked *Only i+1* (read as "only i+1 words of my list"),
Connect made cards for words off his list and 順 set 308 of them aside. The model:

1. **One study order** (*As I'll meet it · By leverage*), the list's (`study_order`): 順's *Order* becomes it, a
   learner's pick carried over (read, never written); 順, Connect and the journey read it.
2. **The cap is a window over the study order:** the next N cards count; an episode ranking above the window's last
   card still goes (the lowest slide out: nothing suspended, nothing deleted). Only Connect's cards and yours made
   since Connect's first count (F22); *Cards for every new word*'s cards count too (F3).
3. ***Words to make cards from* retired** → Level + *Cards for every new word* (More options): *Every new word* reads
   as the switch on, *Only i+1* as off (your list).
4. **Raising the level never mines an episode again** (F1): its new words join the study order.

What a wrong answer costs: a learner's 順 order or word choice silently reset by the update; the cap blocked for
months by an old backlog, or never reached with the switch on (Anki cluttered); a show moved to the top of Current
waiting behind Goal's cards; hundreds of Anki Miner jobs for one move of the Level slider; 順 and the journey on
another order than Connect. Real Japanese and Chinese words; no Anki, no network.
"""
import contextlib
import io
import json
import os

import pytest

from app import anki_connect, settings_manager
from app.connect import library, runner, shelf


def _write_settings(saved):
    from app.path_utils import get_user_file
    path = get_user_file("settings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(saved, f, ensure_ascii=False)
    with open(path, "rb") as f:
        return path, f.read()


# --- 1 + 3. the settings: one study order, *Cards for every new word*, the learners' picks carried over ------------- #
@pytest.mark.parametrize("saved, order", [
    ({"junban_order": "priority"}, "priority"),       # 順's *By leverage* carries over
    ({"junban_order": "content"}, "content"),
    ({}, "content"),                                   # never picked: the default, as I'll meet it
    ({"junban_order": "priority", "study_order": "content"}, "content"),     # the study order, once saved, wins
    ({"junban_order": "Leverage?"}, "content"),        # a hand-edited value no choice names: the default
    ({"junban_order": " Priority "}, "priority"),      # hand-edited: read as 順 read it (lowercased, trimmed)
])
def test_the_study_order_carries_junbans_pick_over_and_nothing_is_written(saved, order):
    # why: the update must not reset the order a learner chose in 順 (it becomes the list's study order) — and
    # nothing automatic writes settings.json (settings criteria 11)
    path, before = _write_settings(dict(saved, target_language="ja"))
    loaded = settings_manager.load_settings()
    assert loaded["study_order"] == order and settings_manager.study_order(loaded) == order
    with open(path, "rb") as f:
        assert f.read() == before, "read only: settings.json untouched"


@pytest.mark.parametrize("saved, every", [
    ({"connect_mine_words": "unknown"}, True),        # *Every new word* -> the switch on
    ({"connect_mine_words": "i1"}, False),            # *Only i+1* -> your list (its intent: the sentence dial, later)
    ({"connect_mine_words": "list"}, False),
    ({}, False),
    ({"connect_mine_words": "unknown", "connect_every_word": False}, False),   # the switch, once saved, wins
])
def test_words_to_make_cards_from_becomes_cards_for_every_new_word(saved, every):
    path, before = _write_settings(dict(saved, target_language="ja"))
    loaded = settings_manager.load_settings()
    assert loaded["connect_every_word"] is every
    assert settings_manager.mine_mode(loaded) == ("unknown" if every else "list")
    with open(path, "rb") as f:
        assert f.read() == before


def test_the_readers_take_a_dict_a_frozen_copy_or_nothing():
    # why: Junban's runs and tests hand in plain dicts (no load_settings); the old key is the fallback there
    assert settings_manager.study_order({"junban_order": " Priority "}) == "priority"
    assert settings_manager.study_order(None) == "content"
    assert settings_manager.connect_every_word({"connect_mine_words": "unknown"}) is True
    assert settings_manager.connect_every_word({"connect_mine_words": "unknown", "connect_every_word": False}) is False
    assert settings_manager.connect_every_word(None) is False and settings_manager.mine_mode(None) == "list"


def test_junban_reads_the_study_order_and_its_window_no_longer_saves_an_order():
    # why: one home — the order lives in the list's settings; 順's window shows its preview in that order and saves
    # no order of its own (a second control for one setting)
    pytest.importorskip("modules.junban")
    from modules.junban import junban_view, reposition
    assert reposition._order({"study_order": "priority", "junban_order": "content"}) == "priority"
    assert reposition._order({"junban_order": "priority"}) == "priority", "an older dict: 順's own key"
    controls = junban_view.controls_from({"study_order": "priority", "junban_order": "content"}, False)
    assert controls["order"] == "priority"
    engine = junban_view.engine_settings({"study_order": "priority"}, controls, "ja")
    assert reposition._order(engine) == "priority"
    assert "junban_order" not in junban_view.window_keys(controls)


def test_the_settings_page_has_one_study_order_row_and_no_words_to_make_cards_from():
    from app.qt import settings_catalog as catalog
    ids = {row.id: row for row in catalog.ROWS}
    assert ids["study_order"].section == "level" and ids["study_order"].options == ("content", "priority")
    assert ids["connect_every_word"].adv, "More options"
    assert "connect_mine_words" not in ids and "junban_order" not in ids
    assert {"connect_mine_words", "junban_order"} <= set(catalog.NOT_SHOWN)


def test_the_journey_opens_on_the_study_orders_list_and_a_change_re_renders_only():
    # why: the journey reads the one study order too (F23): By leverage opens on the Priority List; the order is a
    # report setting — a re-render, never a re-analysis
    from app import settings_placement
    assert settings_placement.PLACED["study_order"] == "report"
    assert settings_placement.PLACED["connect_every_word"] == "neither"
    template = io.open(os.path.join("templates", "web_app.html"), encoding="utf-8").read()
    assert "globalStudyOrder === 'priority'" in template and "switchMainTab('priority')" in template
    source = io.open(os.path.join("app", "static_html_generator.py"), encoding="utf-8").read()
    assert "let globalStudyOrder = '{study_order}';" in source


# --- 4. raising the level never mines an episode again --------------------------------------------------------------- #
def test_a_level_raise_queues_no_job_and_counts_its_new_words(tmp_path):
    # why: F1 — a raise used to queue one Anki Miner job per already-mined episode (hundreds on a big library)
    from app.connect import level
    from app.connect.ledger import Ledger
    before = {("冒険", "ボウケン"), ("散歩", "サンポ")}
    raised = before | {("眼鏡", "メガネ"), ("老婆", "ロウバ")}
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        assert level.check(None, "ja", before, "run-1", {}, ledger=ledger)["first"]
        out = level.check(None, "ja", raised, "run-2", {"ep01.srt": ["眼鏡", "老婆"]}, ledger=ledger)
        assert out["queued"] == [] and out["new"] == 2
        assert not ledger.jobs("ja"), "no job: the new words join the study order"
        assert ledger.resort_owed("ja"), "the deck is re-sorted for the list's new words"


def test_a_level_job_queued_before_the_update_is_dropped_unless_under_way(tmp_path):
    from app.connect.ledger import LEVEL, Ledger
    from tests.connect.fake_steps import FakeSteps
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        jid = ledger.queue_level("ja", 5, {("眼鏡", "メガネ")}, store_id="store-1")
        steps = FakeSteps(str(tmp_path), {"line": {"ja": [5]}, "queue": {"ja": []}})
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        job = ledger.job_by_id(jid)
        assert job["kind"] == LEVEL and job["state"] == "dropped" and job["reason"] == runner.LEVEL_DROPPED
        assert not any(e[0] == "pick" for e in steps.log), "nothing mined for it"


# --- 2. the cap: a window over the study order ----------------------------------------------------------------------- #
class _Store:
    def __init__(self, items):
        self.items = items

    def item(self, item_id):
        return self.items.get(item_id)


def _steps(monkeypatch, lang, notes, made, listed, theirs=None, pinned=(), ahead=(), items=None, file_words=None,
           **settings):
    """`runner.Steps` over a stubbed Anki and store: `notes` the waiting notes, `made` {note: (item, lemma)} Connect's,
    `listed` the list's (Word, Reading) keys in leverage order, `theirs` {note: (word, tags)} your own, `ahead` the
    items still ahead of you in order, `file_words` the last Generate's {file: [lemma]}."""
    steps = runner.Steps(dict({"connect_enabled": True, "anki_sync_decks": {lang: ["日本語::Mining"]}}, **settings))
    store = _Store(items or {})
    steps._open = lambda _lang: contextlib.nullcontext(store)
    monkeypatch.setattr(shelf, "made_notes", lambda store: dict(made))
    monkeypatch.setattr(shelf, "pinned_items", lambda store: set(pinned))
    monkeypatch.setattr(library, "ahead", lambda store: list(ahead))
    monkeypatch.setattr(library, "made_words_all", lambda store: {w for _i, w in made.values()})
    monkeypatch.setattr(anki_connect, "find_notes", lambda url, query: list(notes))

    def notes_info(url, ids):
        return [{"noteId": n, "modelName": "Lapis", "tags": list((theirs or {}).get(n, ("", ()))[1]),
                 "fields": {"Word": {"value": (theirs or {}).get(n, ("", ()))[0], "order": 0}}} for n in ids]
    monkeypatch.setattr(anki_connect, "notes_info", notes_info)
    steps._plan_now = lambda _lang: None
    steps._list_order = lambda _lang: {k: i for i, k in enumerate(listed)}
    from app.cli import verbs
    monkeypatch.setattr(verbs, "_results_language", lambda: "none")
    steps._file_words = lambda _lang: dict(file_words or {})
    steps.cap = lambda _lang: 3
    return steps


LIST_JA = [("撒く", "マク"), ("血塗れ", "チマミレ"), ("眼鏡", "メガネ"), ("老婆", "ロウバ"), ("駐車場", "チュウシャジョウ"),
           ("冒険", "ボウケン")]


def test_your_backlog_from_before_connects_first_card_never_blocks_it(monkeypatch):
    # why: F22 — 2,000 old cards of your own for listed words held Connect at *Your 300 cards are waiting* for months;
    # only yours made since Connect's first card (a note id is its creation time) count, and a card carrying your own
    # tag whenever made (順's *yours*)
    made = {1000: (7, "撒く")}
    theirs = {500: ("眼鏡", ()), 600: ("老婆", ("immersion",)), 1500: ("血塗れ", ()), 1600: ("海原", ())}
    steps = _steps(monkeypatch, "ja", [500, 600, 1000, 1500, 1600], made, LIST_JA, theirs=theirs,
                   junban_own_tag="immersion")
    # Connect's 撒く + your 血塗れ (made after it) + your tagged 老婆; 眼鏡 is older backlog, 海原 off the list
    assert steps.waiting_count("ja") == 3


def test_before_connect_made_any_card_none_of_yours_count(monkeypatch):
    steps = _steps(monkeypatch, "ja", [10, 11], {}, LIST_JA, theirs={10: ("眼鏡", ()), 11: ("老婆", ())})
    assert steps.waiting_count("ja") == 0


@pytest.mark.parametrize("every, count", [(False, 1), (True, 3)])
def test_cards_for_every_new_word_count_toward_the_cap(monkeypatch, every, count):
    # why: F3 — with the switch on, the cards past your level are Connect's too: uncounted, Connect would mine until
    # 300 listed cards wait, a thousand more in Anki (the clutter, by another road)
    made = {1: (7, "撒く"), 2: (7, "海原"), 3: (7, "怒涛")}
    steps = _steps(monkeypatch, "ja", [1, 2, 3], made, LIST_JA, connect_every_word=every)
    assert steps.waiting_count("ja") == count


def test_as_ill_meet_it_a_show_moved_to_the_top_slides_in_and_goal_waits(monkeypatch):
    # why: the window — at the cap, an episode now ahead of the cards waiting (a show moved to the top of Current)
    # still gets its cards, and the lowest slide out; an episode behind them waits for you to study
    made = {1: (20, "撒く"), 2: (21, "血塗れ"), 3: (22, "眼鏡")}
    steps = _steps(monkeypatch, "ja", [1, 2, 3], made, LIST_JA, ahead=[5, 20, 21, 22, 30], study_order="content")
    assert runner._full(steps, "ja", job={"item_id": 5}) is None, "ahead of every waiting card: it goes"
    held = runner._full(steps, "ja", job={"item_id": 30})
    assert isinstance(held, runner.Wait) and "3 cards are waiting" in held.reason
    assert isinstance(runner._full(steps, "ja", job={"item_id": 22}), runner.Wait), "level with the last: waits"
    assert isinstance(runner._full(steps, "ja"), runner.Wait), "no job named (an older caller): the cap as before"


def test_a_finished_shows_rare_cards_slide_out_first_its_listed_ones_stay_first(monkeypatch):
    # why: Sonic — "can't make more than 5 cards if the other 295 were accumulated uncommon ones from shows you
    # completed": a card from content behind you, off your list (every-word on), is the first out of the window
    made = {1: (90, "海原"), 2: (20, "撒く"), 3: (91, "血塗れ")}           # 90, 91: finished (not ahead)
    steps = _steps(monkeypatch, "ja", [1, 2, 3], made, LIST_JA, ahead=[20, 25], study_order="content",
                   connect_every_word=True)
    assert runner._full(steps, "ja", job={"item_id": 25}) is None, "the finished show's 海原 slides out"


def test_by_leverage_an_episode_holding_a_better_word_slides_in(monkeypatch):
    # why: By leverage the window is the list's own order: an episode whose best new word ranks above the waiting
    # cards' last goes; one holding only rarer words waits
    made = {1: (20, "血塗れ"), 2: (21, "眼鏡"), 3: (22, "老婆")}             # list places 1, 2, 3
    items = {40: {"rel_path": "Show/ep40.srt"}, 41: {"rel_path": "Show/ep41.srt"}}
    words = {"ep40.srt": ["撒く", "冒険"], "ep41.srt": ["駐車場", "冒険", "老婆"]}
    steps = _steps(monkeypatch, "ja", [1, 2, 3], made, LIST_JA, items=items, file_words=words,
                   study_order="priority")
    assert runner._full(steps, "ja", job={"item_id": 40}) is None, "撒く (place 0) beats the window's 老婆 (3)"
    assert isinstance(runner._full(steps, "ja", job={"item_id": 41}), runner.Wait), "駐車場 (4): waits; 老婆 carded"


def test_chinese_slides_in_by_its_own_list(monkeypatch):
    listed = [("学习", "xué xí"), ("电脑", "diàn nǎo"), ("图书馆", "tú shū guǎn"), ("散步", "sàn bù")]
    made = {1: (20, "电脑"), 2: (21, "图书馆"), 3: (22, "散步")}
    items = {40: {"rel_path": "剧/第40集.srt"}}
    steps = _steps(monkeypatch, "zh", [1, 2, 3], made, listed, items=items, file_words={"第40集.srt": ["学习"]},
                   study_order="priority")
    assert runner._full(steps, "zh", job={"item_id": 40}) is None


def test_nothing_to_tell_waits_as_before(monkeypatch):
    # why: no list to read (every card counts, no order), or an episode with no file — the cap holds as it did
    made = {1: (20, "撒く"), 2: (21, "血塗れ"), 3: (22, "眼鏡")}
    steps = _steps(monkeypatch, "ja", [1, 2, 3], made, LIST_JA, items={}, study_order="priority")
    assert isinstance(runner._full(steps, "ja", job={"item_id": 99}), runner.Wait)
    steps = _steps(monkeypatch, "ja", [1, 2, 3], made, [], ahead=[5], study_order="content")
    steps._listed_keys = lambda _lang: {}
    assert isinstance(runner._full(steps, "ja", job={"item_id": 5}), runner.Wait)


def test_a_listed_card_from_content_behind_you_stays_in_the_window(monkeypatch):
    # why: a card for a word on your list cut from a show you've finished keeps its place at the front (its context
    # is fresh: Sonic's "context the learner remembers is the lever") — it never slides out for a later episode
    made = {1: (91, "血塗れ"), 2: (20, "撒く"), 3: (21, "眼鏡")}           # 91: finished (behind you)
    steps = _steps(monkeypatch, "ja", [1, 2, 3], made, LIST_JA, ahead=[20, 21, 25], study_order="content")
    assert isinstance(runner._full(steps, "ja", job={"item_id": 25}), runner.Wait)


def test_the_episodes_words_are_read_once_while_the_file_is_the_same(monkeypatch, tmp_path):
    # why (S19, the review): at the cap every job of every look asks for its episode's words — the last Generate's
    # file_words.json is read again only when it changed, and never another language's
    from app.cli import verbs
    path = tmp_path / "file_words.json"
    path.write_text(json.dumps({"第1話.srt": ["眼鏡", "老婆"]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(verbs, "_results_dir", lambda: str(tmp_path))
    monkeypatch.setattr(verbs, "_results_language", lambda: "ja")
    steps = runner.Steps({"connect_enabled": True})
    reads = []
    real = json.load
    monkeypatch.setattr(json, "load", lambda f: reads.append(1) or real(f))
    assert steps._file_words("ja") == {"第1話.srt": ["眼鏡", "老婆"]}
    assert steps._file_words("ja") == {"第1話.srt": ["眼鏡", "老婆"]} and reads == [1]
    path.write_text(json.dumps({"第2話.srt": ["駐車場"]}, ensure_ascii=False), encoding="utf-8")
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert steps._file_words("ja") == {"第2話.srt": ["駐車場"]} and reads == [1, 1]
    assert steps._file_words("zh") == {}, "results/ hold Japanese: never read as Chinese"


def test_the_order_ahead_is_walked_once_while_the_store_is_the_same(monkeypatch):
    # why (S19): at the cap each job of each look places the window; the walk of what's ahead (the whole library's
    # order) runs again only when the store's order or pins moved
    made = {1: (20, "撒く"), 2: (21, "血塗れ"), 3: (22, "眼鏡")}
    steps = _steps(monkeypatch, "ja", [1, 2, 3], made, LIST_JA, study_order="content")
    versions = {"order_version": 4, "pins_version": 1, "epoch": "e1"}
    store = _Store({})
    store.versions = lambda: dict(versions)
    steps._open = lambda _lang: contextlib.nullcontext(store)
    walks = []
    monkeypatch.setattr(library, "ahead", lambda store: walks.append(1) or [5, 20, 21, 22, 30])
    assert runner._full(steps, "ja", job={"item_id": 5}) is None
    assert isinstance(runner._full(steps, "ja", job={"item_id": 30}), runner.Wait) and walks == [1]
    versions["order_version"] = 5                       # a move: walked again, in the new order
    monkeypatch.setattr(library, "ahead", lambda store: walks.append(1) or [20, 21, 22, 30, 5])
    assert isinstance(runner._full(steps, "ja", job={"item_id": 5}), runner.Wait) and walks == [1, 1]

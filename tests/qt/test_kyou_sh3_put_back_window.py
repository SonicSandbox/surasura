"""Kyou-SH3 part 2, the window (PROVISIONAL words): Settings › Anki & mining's *Tidy waiting cards* row has a second
door, *Put back…* — off with its tip until a tidy is listed; its press reads the last 10 tidies on a worker and opens a
themed menu (newest first: when, how many cards, whether it went back already); an item runs that tidy's Undo
(`tidy.act_undo`, its id) on a worker, says it in the bar with *Needs you*'s own words, lists again and updates
*Needs you*. A tidy put back, or whose copy is gone, is shown so and can't be pressed.

What a wrong answer would cost a learner: the wrong tidy put back, one put back twice, Anki written from the window's
thread, or a press that says nothing.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import tidy  # noqa: E402
from app.qt import settings_live  # noqa: E402
from app.qt import settings_strings as S  # noqa: E402
from app.qt import strings  # noqa: E402
from tests.qt.conftest import wait_until  # noqa: E402

PAST = [{"id": 9, "at": "2026-11-21T05:10:00Z", "why": "auto", "cards": 37, "can": tidy.CAN},
        {"id": 7, "at": "2026-11-20T21:45:00Z", "why": "now", "cards": 1, "can": tidy.CAN},
        {"id": 5, "at": "2026-11-19T08:00:00Z", "why": "auto", "cards": 12, "can": tidy.PUT_BACK},
        {"id": 3, "at": "2026-11-18T08:00:00Z", "why": "auto", "cards": 4, "can": tidy.GONE}]


class _Needs:
    def __init__(self):
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1


@pytest.fixture
def settings_page(qapp, monkeypatch):
    from tests.qt.test_settings_live import Fakes, make
    listed = {"rows": [dict(p) for p in PAST]}
    main, read = threading.main_thread(), []

    def act_past(lang):
        read.append((lang, threading.current_thread() is not main))
        return [dict(p) for p in listed["rows"]]
    monkeypatch.setattr(tidy, "act_past", act_past)
    fakes = Fakes(monkeypatch)
    page, store, shell_ = make(fakes, data={"connect_enabled": True})
    shell_.needs_you = _Needs()
    return page, store, shell_, listed, read


def _menu(page):
    door = page.live.parts["connect_tidy"]["back"]
    assert wait_until(lambda: door.isEnabled(), 5)
    page.live.parts["connect_tidy"].pop("menu", None)        # (the menu this press opens, not an earlier one)
    door.click()
    assert wait_until(lambda: page.live.parts["connect_tidy"].get("menu") is not None, 5)
    return door, page.live.parts["connect_tidy"]["menu"]


def test_put_back_sits_beside_tidy_now_and_lists_the_tidies_read_on_a_worker(settings_page):
    page, store, shell_, listed, read = settings_page
    door, menu = _menu(page)
    assert door.text() == S.TIDY_PUT_BACK and door.toolTip() == S.TIDY_PUT_BACK_TIP
    assert door.parent() is page.live.parts["connect_tidy"]["tidy"].parent(), "on the Tidy row, beside Tidy now"
    acts = menu.actions()
    assert [a.text() for a in acts] == [settings_live.tidy_line(p) for p in PAST]
    assert acts[1].text().endswith("· 1 card") and acts[0].text().endswith("· 37 cards")
    assert acts[2].text().endswith(S.TIDY_PAST_BACK) and acts[3].text().endswith(S.TIDY_PAST_GONE)
    assert [a.isEnabled() for a in acts] == [True, True, False, False], "put back once; no copy, no press"
    assert all(a.toolTip() for a in acts) and menu.objectName() == "rowmenu"
    assert read and all(on_worker for _lang, on_worker in read) and read[-1][0] == "ja"
    assert store.calls == [], "the press writes no setting"
    menu.close()


@pytest.mark.parametrize("answer, said", [
    ({"back": 1, "missing": [], "skipped": []}, strings.NEEDS_TIDY_BACK_ONE),
    ({"back": 3, "missing": [], "skipped": [11]}, strings.NEEDS_TIDY_BACK.format(n=3) + strings.NEEDS_TIDY_SKIPPED_ONE),
    ({"why": tidy.NOT_UNDOABLE}, strings.NEEDS_TIDY_NOT_BACK.format(why=tidy.NOT_UNDOABLE)),
])
def test_an_older_tidy_goes_back_on_a_worker_says_it_and_updates_needs_you(settings_page, monkeypatch, answer, said):
    # why: the item runs that tidy's own Undo (its id, never the newest's), off the window's thread; the bar says it
    # with Needs you's words (left out: their words have cards again; or why not); the list and Needs you read again
    page, store, shell_, listed, read = settings_page
    main, undone = threading.main_thread(), []

    def act_undo(settings, lang, tidy_id):
        undone.append((lang, tidy_id, threading.current_thread() is not main))
        listed["rows"][1]["can"] = tidy.PUT_BACK
        return dict(answer)
    monkeypatch.setattr(tidy, "act_undo", act_undo)
    door, menu = _menu(page)
    reads = len(read)
    menu.actions()[1].trigger()
    assert wait_until(lambda: shell_.bar_line.lines[-1:] == [said], 5)
    assert undone == [("ja", 7, True)]
    assert wait_until(lambda: len(read) > reads, 5) and shell_.needs_you.refreshed == 1
    door, menu = _menu(page)
    assert not menu.actions()[1].isEnabled(), "put back: listed so, never pressed twice"
    menu.close()


def test_with_no_tidy_yet_put_back_is_off_and_says_why(qapp, monkeypatch):
    from tests.qt.test_settings_live import Fakes, make
    monkeypatch.setattr(tidy, "act_past", lambda lang: [])
    fakes = Fakes(monkeypatch)
    page, store, shell_ = make(fakes, data={"connect_enabled": True})
    door = page.live.parts["connect_tidy"]["back"]
    assert wait_until(lambda: page.live.past_tidies == [] if hasattr(page.live, "past_tidies") else False, 5)
    assert not door.isEnabled() and door.toolTip() == S.TIDY_PUT_BACK_NONE


def test_a_tidy_now_lists_its_tidy_in_put_back(qapp, monkeypatch):
    # why: the first tidy turns the door on without leaving Settings
    from tests.qt.test_settings_live import Fakes, make
    listed = []
    monkeypatch.setattr(tidy, "act_past", lambda lang: list(listed))
    monkeypatch.setattr(tidy, "act", lambda settings, lang, steps=None: (listed.append(dict(PAST[0])) or
                                                                         {"cards": 37, "id": 9}))
    fakes = Fakes(monkeypatch)
    page, store, shell_ = make(fakes, data={"connect_enabled": True})
    door = page.live.parts["connect_tidy"]["back"]
    assert wait_until(lambda: hasattr(page.live, "past_tidies"), 5) and not door.isEnabled()
    page.live.parts["connect_tidy"]["tidy"].click()
    assert wait_until(lambda: door.isEnabled(), 5) and door.toolTip() == S.TIDY_PUT_BACK_TIP


def test_the_words_are_short_and_the_line_reads_your_clock():
    assert all(len(t.split()) <= 12 for t in (S.TIDY_PUT_BACK_TIP, S.TIDY_PUT_BACK_NONE, S.TIDY_PAST_TIP,
                                              S.TIDY_PAST_BACK_TIP, S.TIDY_PAST_GONE_TIP))
    line = settings_live.tidy_line({"at": "2026-11-21T05:10:00Z", "cards": 37, "can": tidy.CAN})
    assert line.endswith("· 37 cards") and not line.startswith("0") and "Nov" in line
    assert settings_live.tidy_line({"at": None, "cards": 2, "can": tidy.GONE}).endswith(S.TIDY_PAST_GONE)


def test_another_language_reads_its_own_tidies(settings_page):
    # why: the door follows the language shown — a language with no tidy shows it off
    page, store, shell_, listed, read = settings_page
    door = page.live.parts["connect_tidy"]["back"]
    assert wait_until(lambda: door.isEnabled(), 5)
    listed["rows"] = []
    page.live._language(page.language)
    assert wait_until(lambda: not door.isEnabled(), 5) and door.toolTip() == S.TIDY_PUT_BACK_NONE


def test_a_list_that_cant_be_read_leaves_the_door_on_and_its_press_says_so(qapp, monkeypatch):
    # why: a ledger busy or too new is no answer — never "no tidy yet"; the press reads again and says why not
    from tests.qt.test_settings_live import Fakes, make

    def act_past(lang):
        raise OSError("the ledger is locked")
    monkeypatch.setattr(tidy, "act_past", act_past)
    fakes = Fakes(monkeypatch)
    page, store, shell_ = make(fakes, data={"connect_enabled": True})
    door = page.live.parts["connect_tidy"]["back"]
    assert wait_until(lambda: door.isEnabled(), 5) and door.toolTip() == S.TIDY_PUT_BACK_TIP
    door.click()
    assert wait_until(lambda: shell_.bar_line.lines[-1:] == [S.TIDY_PUT_BACK_UNREAD], 5)
    assert page.live.parts["connect_tidy"].get("menu") is None


def test_put_back_reacts_while_tidy_now_still_works(settings_page, monkeypatch):
    # why: every press reacts at once — the two doors of the row are two presses, not one
    page, store, shell_, listed, read = settings_page
    hold = threading.Event()
    monkeypatch.setattr(tidy, "act", lambda settings, lang, steps=None: (hold.wait(10), {"cards": 0})[1])
    door = page.live.parts["connect_tidy"]["back"]
    assert wait_until(lambda: door.isEnabled(), 5)
    page.live.parts["connect_tidy"]["tidy"].click()
    try:
        door, menu = _menu(page)
        assert menu.actions(), "the menu opened while Tidy now still works"
        menu.close()
    finally:
        hold.set()

"""The window's half of *Add audio to these cards* (Kura-AB3 A2; PROVISIONAL): a book lined up with its audiobook after
some of its cards were made says so on *Needs you* — *Add the narrator's voice* runs Connect's `add_audio` on a worker
(the arc turns meanwhile), then a toast with its *Undo* (Connect's `add_audio_undo`, on a worker too); a "couldn't"
(you're reviewing, Anki closed) says why and leaves the line. On the window's seed.

What a wrong answer would cost a learner: Anki written from the window's thread (a freeze for a whole book's clips), a
press with no Undo, an Undo that takes back another press's audio, or a line gone though nothing was added.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import runner
from app.qt import strings
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import button, world  # noqa: F401 (the fixture)

STAR = "星屑の剣士になりたくて！"


@pytest.fixture
def offer(world):  # noqa: F811
    main, got = threading.main_thread(), []
    answers = {"add_audio": {"ok": True, "filled": 5, "id": "17-ab", "title": STAR, "not_cut": 0, "why": None,
                             "say": None},
               "add_audio_undo": {"ok": True, "emptied": 5, "kept": 0, "say": None}}

    def rec(name):
        def call(*args):
            got.append((name, args, threading.current_thread() is not main))
            return answers[name]
        return call
    say = runner.ADD_AUDIO_ASK.format(title=STAR, n=8)
    connect = {"jobs": [], "needs": [{"id": 31, "kind": runner.ADD_AUDIO_NEED, "say": say, "item": 9, "seen_at": None,
                                      "at": "2026-11-10T05:00:00Z"}]}
    answers["kick"] = None
    _seed, win, _writer, ny = world(connect=connect, connect_calls={"add_audio": rec("add_audio"),
                                                                    "add_audio_undo": rec("add_audio_undo"),
                                                                    "kick": rec("kick")})
    entry = next(e for e in ny.entries if e.kind == runner.ADD_AUDIO_NEED)
    return win, ny, entry, got, answers


def test_the_books_line_offers_the_narrators_voice_with_a_tooltip(offer):
    _win, ny, entry, _got, _answers = offer
    assert entry.title == runner.ADD_AUDIO_ASK.format(title=STAR, n=8)
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"add_audio", "dismiss"}
    b = button(ny, entry.key, "add_audio")
    assert b.text() == strings.NEEDS_ACTIONS["add_audio"][0] and b.toolTip()


def test_the_press_runs_on_a_worker_then_its_toast_undoes_that_record_on_a_worker(offer):
    win, ny, entry, got, _answers = offer
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: any(g[0] == "add_audio" for g in got), 5)
    [(_name, args, on_worker)] = [g for g in got if g[0] == "add_audio"]
    assert on_worker and args[:2] == ("ja", 31)
    assert wait_until(lambda: [g for g in got if g[0] == "kick"], 5), "Connect kicked: the sync it owes"
    assert wait_until(lambda: win.toasts.alive and win.toasts.text, 5)
    assert win.toasts.text == strings.NEEDS_AUDIO_ADDED.format(n=5, title=STAR)
    undo = next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO)
    undo.click()
    assert wait_until(lambda: any(g[0] == "add_audio_undo" for g in got), 5)
    [(_name, args, on_worker)] = [g for g in got if g[0] == "add_audio_undo"]
    assert on_worker and args[:2] == ("ja", "17-ab")


def test_a_press_that_couldnt_says_why_and_leaves_no_undo(offer):
    win, ny, entry, got, answers = offer
    answers["add_audio"] = {"ok": False, "say": "You're reviewing in Anki. Add audio again when you're done."}
    said = []
    win.say = said.append
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: said, 5)
    assert said == ["You're reviewing in Anki. Add audio again when you're done."]
    assert not (win.toasts.alive and win.toasts.text == strings.NEEDS_AUDIO_ADDED.format(n=5, title=STAR))


def test_some_cards_not_cut_are_named_in_the_toast(offer):
    win, ny, entry, _got, answers = offer
    answers["add_audio"] = dict(answers["add_audio"], filled=3, not_cut=2, why="Anki Miner took too long.")
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: win.toasts.alive and win.toasts.text, 5)
    assert win.toasts.text == strings.NEEDS_AUDIO_SOME.format(n=3, title=STAR, m=2, why="Anki Miner took too long.")


def test_a_press_stopped_part_way_still_offers_its_undo_in_plain_words(offer):
    """r1 S4: Anki stopped answering after some cards were written — the bar's words are the window's (no command
    line), and the toast's Undo takes back what was written."""
    win, ny, entry, got, answers = offer
    answers["add_audio"] = {"ok": False, "id": "18-cd", "say": "Some of 「x」's cards got the narrator's voice before "
                                                             "this stopped (Anki isn't open). Undo takes them back; "
                                                             "adding again does the rest."}
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: win.toasts.alive and win.toasts.text, 5)
    assert "surasura-cli" not in win.toasts.text and win.toasts.text == answers["add_audio"]["say"]
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    assert wait_until(lambda: any(g[0] == "add_audio_undo" for g in got), 5)
    assert [g[1][1] for g in got if g[0] == "add_audio_undo"] == ["18-cd"]


# --- the book row's ⋯ (the lead's MUST): whenever such cards exist and a line-up is ready ------------------------ #
@pytest.fixture
def row_offer(qapp, monkeypatch):
    from PyQt6.QtCore import QPoint
    from tests.fixtures import window_seed
    from tests.qt.test_drag import open_window
    from tests.qt.test_item_menu import ItemWriter, rows_of
    seed = window_seed.build()
    win, services = open_window(qapp, seed, ItemWriter(seed.library, apply=False))
    main, got = threading.main_thread(), []
    answer = {"offer": {"epub": "D:/Books/星屑.epub", "title": STAR, "n": 8},
              "book": {"ok": True, "filled": 5, "id": "19-ef", "title": STAR, "not_cut": 0, "why": None, "say": None},
              "undo": {"ok": True, "emptied": 5, "kept": 0, "say": None}}

    def rec(name):
        def call(*args):
            got.append((name, args, threading.current_thread() is not main))
            return answer[name]
        return call
    win.items.add_audio_offer, win.items.add_audio_book, win.items.add_audio_undo = rec("offer"), rec("book"), rec("undo")
    answer["kick"] = None
    win.items.kick = rec("kick")
    row = rows_of(win)[4]
    from app.qt import item_menu
    monkeypatch.setattr(item_menu, "book_row", lambda r: r is row)      # (the seed's rows are videos: this, a book's)
    yield win, row, got, answer, (lambda: win.items.menu(row, win.mapToGlobal(QPoint(300, 300))))
    win.close()
    services.shutdown(0.5)


def _entry(m):
    return next((a for a in m.actions() if a.text() == strings.ITEM_MENU["add-audio"][0]), None)


def test_the_rows_menu_offers_it_before_open_its_folder_once_connect_answers_on_a_worker(row_offer):
    from app.qt import drag
    win, row, got, _answer, open_menu = row_offer
    m = open_menu()
    assert wait_until(lambda: _entry(m) is not None, 5)
    texts = [a.text() for a in m.actions()]
    assert texts.index(strings.ITEM_MENU["add-audio"][0]) + 1 == texts.index(strings.ITEM_MENU["folder"][0])
    assert "8 of its cards" in _entry(m).toolTip()
    [(_n, args, on_worker)] = [g for g in got if g[0] == "offer"]
    assert on_worker and args[0] == "ja" and args[1] == drag.ids_of(row)
    m.hide()


def test_no_offer_no_entry(row_offer):
    win, _row, got, answer, open_menu = row_offer
    answer["offer"] = None
    m = open_menu()
    assert wait_until(lambda: [g for g in got if g[0] == "offer"], 5)
    wait_until(lambda: False, 0.3)                      # (its answer had its turn on the window's thread)
    assert _entry(m) is None
    m.hide()


def test_the_rows_press_says_so_at_once_runs_on_a_worker_and_its_toast_undoes_it(row_offer):
    win, _row, got, _answer, open_menu = row_offer
    said = []
    real_say = win.say
    win.say = lambda text: (said.append(text), real_say(text))
    m = open_menu()
    assert wait_until(lambda: _entry(m) is not None, 5)
    _entry(m).trigger()
    assert said[:1] == [strings.NEEDS_AUDIO_RUNNING.format(title=STAR)], "the press reacts at once"
    assert wait_until(lambda: win.toasts.alive and win.toasts.text == strings.NEEDS_AUDIO_ADDED.format(n=5, title=STAR),
                      5)
    [(_n, args, on_worker)] = [g for g in got if g[0] == "book"]
    assert on_worker and args[:2] == ("ja", "D:/Books/星屑.epub")
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    assert wait_until(lambda: [g for g in got if g[0] == "undo"], 5)
    assert [g[1][1] for g in got if g[0] == "undo"] == ["19-ef"]


def test_a_press_that_couldnt_can_be_pressed_again(offer):
    """Mutant Q1: a "couldn't" leaves the line — pressed again at once, it asks Connect again."""
    win, ny, entry, got, answers = offer
    answers["add_audio"] = {"ok": False, "say": "You're reviewing in Anki. Add audio again when you're done."}
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: len([g for g in got if g[0] == "add_audio"]) == 1, 5)
    assert wait_until(lambda: button(ny, entry.key, "add_audio") is not None and
                      button(ny, entry.key, "add_audio").isEnabled(), 5)
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: len([g for g in got if g[0] == "add_audio"]) == 2, 5)


def test_an_earlier_menus_late_answer_never_lands_in_a_newer_menu(row_offer):
    """Mutant I2: ⋯ opened on the book, closed, opened again on another row whose answer is "nothing" — the first
    ask's answer, coming late, adds nothing to the menu open now."""
    win, row, got, answer, open_menu = row_offer
    gate, first = threading.Event(), []

    def slow(*args):
        if not first:
            first.append(1)
            gate.wait(5)
            return answer["offer_first"]
        return None
    answer["offer_first"] = answer["offer"]
    win.items.add_audio_offer = slow
    m = open_menu()
    m.hide()
    m = open_menu()                                     # (the same kept menu, open again)
    gate.set()
    wait_until(lambda: False, 0.5)
    assert _entry(m) is None
    m.hide()


def test_the_rows_press_kicks_connect_and_a_second_press_meanwhile_runs_nothing(row_offer):
    """r2 S3 / N9: the press owes Anki's sync (Connect kicked, on the worker); pressed again while it runs, nothing
    more is asked of Connect."""
    win, _row, got, answer, open_menu = row_offer
    gate = threading.Event()
    real = win.items.add_audio_book

    def slow(*args):
        gate.wait(5)
        return real(*args)
    win.items.add_audio_book = slow
    m = open_menu()
    assert wait_until(lambda: _entry(m) is not None, 5)
    offer = dict(answer["offer"])
    win.items.add_audio(offer)
    win.items.add_audio(offer)                          # pressed again while the first runs
    gate.set()
    assert wait_until(lambda: [g for g in got if g[0] == "kick"], 5)
    wait_until(lambda: False, 0.3)
    assert len([g for g in got if g[0] == "book"]) == 1
    assert all(on_worker for name, _a, on_worker in got if name == "kick")
    m.hide()


def test_no_entry_while_a_press_for_that_book_runs(row_offer):
    """Mutant I8: the book's cards are being given the narrator's voice now — ⋯ doesn't offer it again meanwhile."""
    win, _row, got, answer, open_menu = row_offer
    win.items._audio_running.add(answer["offer"]["epub"])
    m = open_menu()
    assert wait_until(lambda: [g for g in got if g[0] == "offer"], 5)
    wait_until(lambda: False, 0.3)
    assert _entry(m) is None
    m.hide()


def test_a_press_on_a_book_not_lined_up_asks_mine_now_on_its_first_part_through_the_windows_path(offer):
    """r4: Connect answers "line it up first" — the window asks *Mine now* for that part (its own path: its row turns,
    its job lines the book up, seen and stoppable there); the line stays."""
    win, ny, entry, got, answers = offer
    asked = []
    win.mine = type("Mine", (), {"ask_items": lambda self, text, ids: asked.append((text, ids))})()
    answers["add_audio"] = {"ok": False, "line_up": 42, "title": STAR, "say": "「x」 is lined up with its audiobook first"}
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: asked, 5)
    assert asked == [("「x」 is lined up with its audiobook first", [42])]


def test_a_row_of_no_books_part_asks_connect_nothing(row_offer):
    """Up next at 20,000 files: ⋯ on a video's row starts no worker for *Add the narrator's voice…* (an open makes
    nothing) — only a book's part can be a book's."""
    from PyQt6.QtCore import QPoint
    from tests.qt.test_item_menu import rows_of
    win, row, got, _answer, _open_menu = row_offer
    other = next(r for r in rows_of(win) if r is not row)
    m = win.items.menu(other, win.mapToGlobal(QPoint(300, 300)))
    wait_until(lambda: False, 0.3)
    assert not [g for g in got if g[0] == "offer"] and _entry(m) is None
    m.hide()

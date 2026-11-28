"""MARKS-NEW (3.0.21): a row's *N new* falls when words are marked Known or Ignore in the journey.

A tester marked 11 of a row's 65 new words in the journey and saw the row still say 65. The pieces each had a test of
their own (the door's route against a stand-in window, `test_journey_door`; the engine's `leave_out`,
`test_word_marks_engine`; the card's mark into a stand-in numbers, `test_word_peek`), none the whole path. This one
walks it as a learner does: the real window on a real library (tests/test_journey_stones' Show A and Show B, cut from
the bundled samples' real Japanese and Chinese), its own Generate (the analyzer in its own process), the journey's
door started as the window starts it, and the marks sent to it over HTTP as the page sends them (`words/mark`, the
session's token, a file page's `Origin: null`). Then the row's *N new* on the Current page, live; then the same marks
made while the window is closed and read at the next start.

What a wrong answer would cost a learner: the words they just marked in the journey still counted in the row they came
from — the row looking as if the marks did nothing — until some later Generate.
"""
import http.client
import json

import pytest

pytest.importorskip("PyQt6")
from app import door, path_utils, run_args
from app.qt import bridge, shell
from app.services import journey_door, word_lists, word_marks
from tests.qt.conftest import wait_until
from tests.test_journey_stones import _library
from tests.test_journey_stones_quiet import _argv, _the_childs_token_store  # noqa: F401  (an autouse fixture)


def _post(d, route, body):
    """One press as the journey page sends it: a simple POST, the token in the text/plain body, a file page's Origin."""
    conn = http.client.HTTPConnection("127.0.0.1", d.port, timeout=10)
    data = json.dumps(dict(body, token=d.token), ensure_ascii=False).encode("utf-8")
    conn.request("POST", f"/v1/{route}", body=data,
                 headers={"Host": f"127.0.0.1:{d.port}", "Content-Type": "text/plain", "Origin": "null"})
    r = conn.getresponse()
    out = r.status, json.loads(r.read().decode("utf-8"))
    conn.close()
    return out


def _open(qapp, language):
    services = shell.open_services()
    win = shell.open_window(qapp, services)
    win.first_frame.connect(win.start_duties)         # as main() connects them
    win.first_frame.connect(services.load_numbers)
    win.resize(1280, 900)
    win.show_first()
    page = win.page_widgets["current"]
    assert wait_until(lambda: page.view_model is not None and page.view_model.state == "full", 20)
    return services, win, page


def _close(services, win):
    win.close()
    shell.stop_door()
    services.shutdown(2.0)


def _rows(page):
    """{row key: (its *N new*, [each episode's *N new*])} as the Current page shows them."""
    return {row.key: (row.n_new, [e.n_new for e in row.episodes]) for row in page.view_model.rows}


def _new_words(services, row):
    """The row's new words, as its word card lists them (`Engine.words_of`: the sum of its episodes' *N new*)."""
    new, _before = services.writer.numbers._engine.words_of([e.id for e in row.episodes])
    return [w.word for w in new]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_words_marked_in_the_journey_take_the_rows_n_new_down_live_and_at_the_next_start(qapp, monkeypatch,
                                                                                         language):
    # why: the learner's flow — Generate, open the journey, mark some of a row's new words Known and some Ignore —
    # must take that row's *N new* down by the words marked, while the window is open; and marks the page sends with
    # the window closed reach the next start's numbers the same way
    monkeypatch.setattr(run_args, "analyzer_args", lambda settings, language=None, **k: _argv(language))
    monkeypatch.setattr(journey_door, "enabled", lambda: True)
    with open(path_utils.get_user_file("settings.json"), "w", encoding="utf-8") as f:
        json.dump({"target_language": language, "logic": {"automation": False}}, f)
    store, _ids, _names = _library(language)
    services, win, page = _open(qapp, language)
    try:
        numbers = services.writer.numbers
        assert wait_until(lambda: services.has_duties() and win.duties is not None, 20)
        bridge.run_in_worker(services.generate)
        assert wait_until(lambda: services.controller.state().state == "current", 180), services.controller.state()
        assert wait_until(lambda: numbers.why() is None and all(n is not None for n, _e in _rows(page).values()), 20)
        before = _rows(page)
        row = max(page.view_model.rows, key=lambda r: r.n_new)
        listed = _new_words(services, row)
        assert len(listed) == row.n_new >= 8, (row.title, row.n_new, listed)
        words = [w for w in dict.fromkeys(listed) if listed.count(w) == 1][:5]     # (a word with two readings: two rows)
        assert len(words) == 5

        shell.start_door(win)
        assert wait_until(lambda: door.current() is not None and door.current().port is not None, 10)
        d = door.current()
        marks = [{"word": w, "mark": "known"} for w in words[:3]] + [{"word": w, "mark": "ignore"} for w in words[3:]]
        word_lists._BACKED_UP.clear()
        status, answer = _post(d, "words/mark", {"lang": language, "marks": marks})
        assert status == 200 and answer["ok"] is True and answer["done"] == 5, answer
        assert wait_until(lambda: _rows(page)[row.key][0] == before[row.key][0] - 5, 5), (before[row.key],
                                                                                         _rows(page)[row.key])
        after = _rows(page)
        assert sum(after[row.key][1]) == after[row.key][0]                 # its episodes' *N new* fell with it
        for key, value in before.items():                                  # (a row with none of those words: as it was)
            if key != row.key:
                assert after[key][0] <= value[0]

        # Undo on the page: the words come back
        undone = _post(d, "words/undo", {"lang": language, "undo_id": answer["undo_id"]})[1]
        assert undone == {"ok": True, "done": 5}
        assert wait_until(lambda: _rows(page) == before, 5), (before, _rows(page))
    finally:
        _close(services, win)

    # The window closed: the page's waiting marks (or any list write) land, then the next start shows them left out
    word_lists._BACKED_UP.clear()
    result = word_marks.apply(language, [(w, "known") for w in words[:2]] + [(words[2], "ignore")])
    assert result.error is None and len(result.done) == 3
    services, win, page = _open(qapp, language)
    try:
        numbers = services.writer.numbers
        assert wait_until(lambda: numbers.why() is None and _rows(page).get(row.key, (None,))[0] is not None, 20)
        assert _rows(page)[row.key][0] == before[row.key][0] - 3, (before[row.key], _rows(page)[row.key])
    finally:
        _close(services, win)
        word_marks._UNDO.clear()
        store.close()

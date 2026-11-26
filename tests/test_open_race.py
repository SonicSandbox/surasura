"""OPEN-RACE (3.0.19): the window's first list is built once, with its numbers.

What a wrong answer would cost a learner: at a 20,000-file open the numbers' first load (the plan read, the staleness
check, the engine) and the library reader's first look (the whole feed, then a full build) began together and took
turns at Python's lock; which ran first was a race, so the first view with numbers landed at 3.3, 4.2 or 5.7-6.7 s,
and the list was built twice (once without the numbers, once with them). The reader's first look now waits for the
numbers' first answer (`moves.Numbers.wait_first`) — at most `FIRST_NUMBERS_S`, and never past a learner's command.

Runs on a real `library_store` (a small migrated library; Japanese and Chinese show names from tests/Test Resources)
and a plan of real words (`test_window_numbers_gc`'s). The numbers' load is held at a gate the test opens, so the order
is the test's, never a timing.
"""
import threading

import pytest

from app.services import library_reader
from app.services import moves as M
from tests.test_library_store_support import LANGUAGES
from tests.test_window_numbers_gc import _wait, window_library  # noqa: F401  (the fixture)


@pytest.fixture
def gate(monkeypatch):
    """The numbers' load held until the test opens it (`gate.set()`); `gate.fail` makes the held load raise."""
    g = threading.Event()
    g.fail = False
    real = M.Numbers._load_plan

    def held(self):
        assert g.wait(30), "the test never opened the gate"
        if g.fail:
            raise RuntimeError("a read that failed before its answer")
        return real(self)
    monkeypatch.setattr(M.Numbers, "_load_plan", held)
    yield g
    g.set()


def _with_numbers(reader):
    return reader.view() is not None and (reader._numbers_version or 0) >= 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_first_list_waits_for_the_numbers_first_answer_and_is_built_once_with_them(language, window_library,
                                                                                       gate):
    numbers, reader = window_library()
    numbers.load()                                          # (the window asks for it at its first frame, then starts
    reader.start()                                          # the reader: `shell._frame_flushed`)
    assert not _wait(lambda: reader.builds > 0, 0.6), "no list built without its numbers while they load"
    assert reader.view() is None and numbers.wait_first(0) is False
    gate.set()
    assert _wait(lambda: _with_numbers(reader), 30), numbers.why()
    assert numbers.why() is None and numbers.wait_first(0) is True
    assert reader.builds == 1, "one build, with the numbers — never one without them and then another"


@pytest.mark.parametrize("ask", ["urgent", "expect", "republish"])
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_learners_command_ends_the_wait_at_once(language, ask, window_library, gate):
    numbers, reader = window_library()
    numbers.load()
    reader.start()
    assert not _wait(lambda: reader.builds > 0, 0.3)
    {"urgent": reader.urgent, "expect": lambda: reader.expect({}),
     "republish": reader.republish}[ask]()                  # (a drop, a Move to Finished, the settle's ask)
    assert _wait(lambda: reader.view() is not None, 3), "the learner's command is never held back for the numbers"
    assert numbers.wait_first(0) is False, "(the numbers still on their way)"


@pytest.mark.parametrize("language", LANGUAGES)
def test_past_its_limit_the_list_is_built_without_them_and_again_once_they_land(language, window_library, gate,
                                                                                 monkeypatch):
    monkeypatch.setattr(library_reader, "FIRST_NUMBERS_S", 0.3)
    numbers, reader = window_library()
    numbers.load()
    reader.start()
    assert _wait(lambda: reader.view() is not None, 5), "a slow load never keeps the list away past the limit"
    assert not _with_numbers(reader)
    gate.set()
    assert _wait(lambda: _with_numbers(reader), 30), numbers.why()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_load_that_raises_before_its_answer_still_ends_the_wait(language, window_library, gate):
    numbers, reader = window_library()
    gate.fail = True
    numbers.load()
    reader.start()
    gate.set()
    assert _wait(lambda: numbers.wait_first(0), 5)
    assert _wait(lambda: reader.view() is not None, 2), "built at once, not at the wait's 5 s limit"


@pytest.mark.parametrize("language", LANGUAGES)
def test_with_no_load_asked_nothing_waits(language, window_library, gate):
    numbers, reader = window_library()                      # (a provider nobody asked: a test's, the command line's)
    assert numbers.wait_first(0) is True
    reader.start()
    assert _wait(lambda: reader.view() is not None, 3)

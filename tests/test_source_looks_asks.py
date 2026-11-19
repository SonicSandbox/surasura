"""Nothing waits on a share that doesn't answer (Kura-NA, a Send report of 2026-11-18: with the library's folders on a
NAS that wasn't answering, opening New arrivals' ⋯ to skip a folder "basically nearly froze").

The ⋯'s *Never read this folder* choices (`skippable`), Settings' *Skip a folder…* check (`skip_refused`) and the
arrival rows' folder names (`folders`) are reads of the library store alone — no folder is looked at. They used to wait
in line on the looks' one worker, behind a look listing a share that hangs (Windows gives a dead SMB share tens of
seconds per folder), so the menu's entry and Settings' answer came only after the look. Now they have a worker of their
own: they answer while a look hangs.

What a wrong answer costs a learner: a press that seems to do nothing for a minute (no entry in the menu, an arc that
turns), with a dead share as the only reason. The share's hang is faked (`sources.scan` held on an event); the episode
is a real Japanese / Chinese subtitle from tests/Test Resources/, the show name made up.
"""
import os
import threading
import time

import pytest

from app import library_store as ls
from app import sources
from app.services import source_looks
from tests import services_helpers as h
from tests.test_library_store_support import LANGUAGES
from tests.test_source_looks_busy import _folder, _library
from tests.test_sources_scan import _fresh_module_state  # noqa: F401

BUDGET_S = 0.5           # the window's press budget for an answer that reads the store alone (generous on a busy PC)


def _hanging_look(monkeypatch):
    """Every look from now on hangs (a share that doesn't answer) until the event is set -> (the event, the looks
    started)."""
    release, started = threading.Event(), []
    real = sources.scan

    def scan(*a, **kw):
        started.append(1)
        release.wait(30)
        return real(*a, **kw)
    monkeypatch.setattr(sources, "scan", scan)
    return release, started


def _ask(call):
    """`call(then)` -> (its answer, seconds it took)."""
    got, t0 = [], time.monotonic()
    assert call(got.append) is not False
    assert h.until(lambda: got, seconds=10), "never answered"
    return got[0], time.monotonic() - t0


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_skip_choices_and_folder_names_answer_while_a_look_hangs_on_a_share(language, monkeypatch):
    opener, data_dir, user_files_dir = _library(language)
    looks = source_looks.SourceLooks(opener, language, kind=lambda _p: "network")
    src = _folder(language)
    release = None
    try:
        answers = []
        assert looks.add(src, answers.append)
        assert h.until(lambda: answers, seconds=10) and looks.idle(10)
        with ls.open_store(language, data_dir, user_files_dir) as store:
            ids = [r[0] for r in store.conn.execute("SELECT id FROM items ORDER BY id")]
        assert len(ids) == 2
        release, started = _hanging_look(monkeypatch)
        assert looks.asked(refreshed=True)                       # a full look of the share: it hangs
        assert h.until(lambda: started, seconds=10), "the look never started"
        choices, took = _ask(lambda then: looks.skippable(ids, then))
        assert took < BUDGET_S, f"the ⋯'s choices waited {took:.2f} s behind the look"
        assert choices == [] or all(os.path.isabs(c) for c in choices)
        why, took = _ask(lambda then: looks.skip_refused(os.path.join(src, "Downloading"), then))
        assert took < BUDGET_S, f"Settings' check waited {took:.2f} s behind the look"
        assert why is None                                        # a folder inside one being read: it can be skipped
        names, took = _ask(lambda then: looks.folders(ids, then))
        assert took < BUDGET_S and set(names) == set(ids), took
    finally:
        if release is not None:
            release.set()
        looks.idle(30)
        looks.close()

"""The top-20 line moved from the window (P4.1 L2 row 4.1.14): Settings' *Mine automatically: the top N* writes the
store's mine line through the window's writer (`moves.Writer.set_options(mine_line=)`, W3.3 P6); the store logs the
files that crossed it as any move does (`entered_mine_line` / `left_mine_line`), the writer's after-commit hook (the
shell's `connect_after_commit`, row 4.1.6's rule) kicks Connect once, and Connect's next look queues the files that came
in — and drops a job whose file went out before its mining started.

What a wrong answer would cost: a raised line that mines nothing until the next start (the learner asked for more cards
and got none), or a lowered one that still mines files now below it. Real subtitles (the suite's own) in a store built
from folders, a real ledger under the test's root; the kick is stood in for (no process).
"""
import time

from app import library_store as ls
from app.connect import inbox, library, window_link
from app.connect.ledger import Ledger
from app.qt.strings import MOVE_WORDS
from app.services import moves
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _until(pred, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _look(lang):
    with c.store(lang) as s, Ledger() as ledger:
        return inbox.consume(s, lang, ledger)


def _writer(lang, kicks):
    """The window's writer on the language's store, its after-commit hook the shell's adapter's rule: one look, a
    kick when Connect has something unread."""
    data_dir, user_files = c.dirs(lang)
    link = window_link.Link(lang, lambda: {"connect_enabled": True}, kick=lambda settings: kicks.append(1) or object(),
                            running=lambda: False)
    w = moves.Writer(ls.StoreOpener(lang, data_dir, user_files, role="window"), lang,
                     journal_file=moves.journal_path(lang), words=MOVE_WORDS, retry=0.05,
                     after_commit=lambda _change, _op: link.after_change())
    w.start()
    return w


def _line(lang):
    with c.store(lang) as s:
        return library.mine_line(s)


def test_raising_the_line_from_settings_queues_the_files_that_came_into_it_and_lowering_it_drops_them():
    for lang in ("ja", "zh"):
        c.library(lang)
        with c.store(lang) as s:
            s.bookkeeping({"mine_line": 2}, copy_carries=True)
        _look(lang)                                             # Connect's first look: its reader and watermark
        before = _line(lang)
        assert len(before) == 2
        kicks = []
        w = _writer(lang, kicks)
        try:
            assert w.set_options(mine_line=4) is not None       # Settings' *the top 4*
            assert _until(lambda: w.pending() == 0 and kicks == [1]), "the writer's commit kicked Connect once"
            assert len(_line(lang)) == 4                        # (looked at once it landed: no second handle racing it)
            came_in = [i for i in _line(lang) if i not in before]
            assert len(came_in) == 2
            got = _look(lang)
            assert sorted(got["queued"]) == sorted(came_in), lang
            with Ledger() as ledger:
                assert {j["item_id"] for j in ledger.jobs(lang) if j["state"] == "queued"} == set(came_in)
            assert w.set_options(mine_line=2) is not None       # lowered again before any mining started
            assert _until(lambda: w.pending() == 0 and len(kicks) == 2), "the lowered line is unread too: one more kick"
            assert len(_line(lang)) == 2
            assert sorted(_look(lang)["dropped"]) == sorted(came_in)
        finally:
            w.finish(time.monotonic() + 5)

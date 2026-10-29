"""Known from Anki's window after the dashboard's automatic sync (P2.4 row 2.4.15; mutant P2.4-F36).

After a sync whose known-words signal has news, the window opens when there is anything to show: words marked known,
words taken from an accepted offer (each with its Undo), or a pending offer with cards. Words taken from an offer are
enough on their own: the window is 2.x's only Undo for them, and opening it is what saves them as shown.

What a wrong answer would cost: taken words you can never undo from the dashboard, and a record that keeps its news
forever. Same harness as test_anki_sync_wiring.py: tkinter is mocked, the worker runs in place, Anki is never reached.
"""
from unittest.mock import patch

from tests.test_anki_sync_wiring import _DashboardHarness

URL = "http://127.0.0.1:8765"


class TestKnownFromAnkiWindowAfterAnAutoSync(_DashboardHarness):
    def _sync_with(self, seen):
        """One automatic sync whose signal has news and whose window view is `seen`; then every call the worker
        queued for the window's thread is run -> the view's mock (it shows the worker reached the window's
        decision)."""
        from app import anki_connect, anki_sync
        from app.connect import known_signal_window
        target = self._call_sync(self._settings()).call_args.kwargs["target"]
        with patch.object(anki_connect, "address", return_value=URL), \
             patch.object(anki_connect, "probe", return_value={"ok": True}), \
             patch.object(anki_sync, "sync", return_value=None), \
             patch.object(anki_sync, "sync_backlog", return_value=None), \
             patch.object(anki_sync, "sync_young", return_value=(0, None)), \
             patch.object(anki_sync, "read_known_signal", return_value={"news": True}), \
             patch.object(known_signal_window, "view", return_value=seen) as view:
            target()
        for call in self.app.gui_queue.put.call_args_list:
            call.args[0]()
        return view

    def test_words_taken_from_an_offer_alone_open_the_window(self):
        seen = {"marked": [], "taken": [{"word": "上層部", "card": 1700000000011, "note": 1700000000021,
                                         "why": "offer"}],
                "offer": {}, "terms": ["suspended"]}
        self._sync_with(seen)
        self.app._known_signal_window.assert_called_once_with("ja", URL, seen)

    def test_words_marked_known_open_the_window(self):
        seen = {"marked": [{"word": "一生懸命", "card": 1700000000012, "note": 1700000000022, "why": "suspended"}],
                "taken": [], "offer": {}, "terms": ["suspended"]}
        self._sync_with(seen)
        self.app._known_signal_window.assert_called_once_with("ja", URL, seen)

    def test_nothing_to_show_opens_no_window(self):
        view = self._sync_with({"marked": [], "taken": [], "offer": {}, "terms": ["suspended"]})
        view.assert_called_once()           # the worker reached the window's decision: there was just nothing to show
        self.app._known_signal_window.assert_not_called()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Two Anki writers never write at once (E1.4 §W): every Junban writer takes the Anki-write lock.

What a wrong answer would cost, in order:
  * a fill's writes interleaved with a reorder's — two Surasura processes on one Anki: the second waits
    for the first to finish (its first write after the other's last), or, not waiting, is told who holds
    it — proved on a real loopback HTTP fake on a free port, with two child processes;
  * the automatic step writing over a window's run — it stands aside (`""`) and tries again later;
  * a window that waits forever, or writes after it was closed — it says who it waits for, then runs;
    closed mid-wait, it writes nothing;
  * a delayed write landing mid-review, or a Restore replaying a snapshot replaced while it waited.

Against the engine's FakeCollection (real Japanese words); never a live Anki.
"""
import http.server
import json
import os
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from app import anki_connect
from modules.junban import auto, backfill, reposition, undo
from modules.junban.backfill_gui import BackfillGui
from modules.junban.gui import JunbanGui
from modules.junban.tests.test_backfill import LAPIS, BackfillCollection, _Session, _fake, _lapis
from modules.junban.tests.test_backfill import _settings as _fill_settings
from modules.junban.tests.test_reposition import (_JOURNEY, _LIBRARY, FakeCollection, _collection, _patched,
                                                  _results, _settings)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_ACTIONS = ["setSpecificValueOfCard", "multi", "suspend", "unsuspend", "updateNoteFields"]


def _backlog(tmp_path, **kwargs):
    """冒険 / 散歩 on the list, 須藤 / 図書館 not, in the wrong order: a reorder has work to do."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    cards, notes, _ = _collection(["須藤", "散歩", "図書館", "冒険"])
    return FakeCollection(cards, notes, actions=tuple(_ACTIONS), **kwargs)


def _holder(verb="Backfill"):
    """Another writer (a thread here) holding the lock until the returned Event is set."""
    taken, done = threading.Event(), threading.Event()

    def hold():
        with anki_connect.writer(verb):
            taken.set()
            done.wait(30)
    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert taken.wait(5)
    return done, thread


# --- two processes on one Anki ---------------------------------------------------------------------- #
class _Server(http.server.ThreadingHTTPServer):
    """AnkiConnect on 127.0.0.1, a free port: the fake collection behind real HTTP. The first card
    position write waits at `barrier` until the test lets it through, so a reorder is held mid-write."""
    daemon_threads = True

    def __init__(self, collection):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.collection = collection
        self.state = threading.Lock()
        self.log = []                               # (monotonic time, action, sub-actions)
        self.first_write = threading.Event()        # the reorder's first position write has arrived
        self.barrier = threading.Event()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        payload = json.loads(body.decode("utf-8"))
        subs = [entry.get("action") for entry in (payload.get("params") or {}).get("actions") or []
                if isinstance(entry, dict)]         # `apiReflect` names actions as plain strings
        if "setSpecificValueOfCard" in subs and not self.server.first_write.is_set():
            self.server.first_write.set()
            self.server.barrier.wait(60)
        with self.server.state:
            self.server.log.append((time.monotonic(), payload["action"], subs))
            reply = self.server.collection(SimpleNamespace(data=body)).read()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)


_CHILD = r"""
import json, os, sys
from app import path_utils
path_utils.get_persistent_user_data_path = lambda: os.path.join(os.environ["SURASURA_TEST_ROOT"], "persistent")
role, settings, wait = sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3])
on_wait = lambda holder: print("waiting " + json.dumps(holder, ensure_ascii=False), flush=True)
if role == "reorder":
    from modules.junban import reposition
    report = reposition.run(settings, wait=wait, on_wait=on_wait)
else:
    from modules.junban import backfill
    from modules.junban.tests.test_backfill import _Session
    report = backfill.run(settings, _Session(), wait=wait, on_wait=on_wait)
print("report " + json.dumps({k: report.get(k) for k in ("ok", "busy", "problems", "written")},
                             ensure_ascii=False), flush=True)
"""


def _child(role, settings, wait):
    return subprocess.Popen([sys.executable, "-c", _CHILD, role, json.dumps(settings), json.dumps(wait)],
                            cwd=_ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"), stdout=subprocess.PIPE,
                            text=True, encoding="utf-8")


def _report(process):
    out, _ = process.communicate(timeout=120)
    lines = out.splitlines()
    report = [json.loads(line[len("report "):]) for line in lines if line.startswith("report ")]
    assert report, out
    return report[0], [json.loads(line[len("waiting "):]) for line in lines if line.startswith("waiting ")]


class _OneAnki(BackfillCollection):
    """One collection for both writers: 順's new-card search (`deck:"X" is:new …`) and Backfill's (by note
    type, or the young cards) each answered as its own fake answers it."""

    def _dispatch(self, action, params):
        query = (params or {}).get("query", "")
        if action == "findCards" and 'note:"' not in query and "prop:ivl" not in query:
            return self._find(query)
        return super()._dispatch(action, params)


def _is_write(subs, action):
    return anki_connect._write_in(action, {"actions": [{"action": name} for name in subs]}) is not None


def test_a_second_process_waits_for_the_first_and_never_writes_between_its_writes(tmp_path):
    reorder = _backlog(tmp_path)
    cards = list(reorder.cards.values())
    notes = [dict(note, modelName="Junban Basic") for note in reorder.notes.values()]
    for index, word, reading in ((0, "探検", "たんけん"), (1, "大切", "たいせつ")):
        note, card = _lapis(index, word, reading, deck="Mining")
        notes.append(note)
        cards.append(card)
    collection = _OneAnki(cards, notes, {"Lapis": LAPIS})
    collection.actions = list(_ACTIONS)
    server = _Server(collection)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        a = _child("reorder", _settings(junban_order="content", junban_chunk_size=1,
                                        anki_connect_url=server.url), 0)
        if not server.first_write.wait(90):
            a.kill()
            pytest.fail(f"the reorder never reached its first write: {a.communicate()[0]} {server.log}")

        # Not waiting: refused at once, naming the reorder.
        busy, _ = _report(_child("fill", _fill_settings(anki_connect_url=server.url), 0))
        assert busy["busy"] is True and busy["written"] == []
        assert busy["problems"][0].startswith("順 reorder is writing to Anki (since ")

        # Waiting: it says who it waits for, and writes only after the reorder's last write.
        b = _child("fill", _fill_settings(anki_connect_url=server.url), 60)
        time.sleep(1.0)
        server.barrier.set()
        reordered, _ = _report(a)
        filled, waited = _report(b)
    finally:
        server.barrier.set()
        server.shutdown()
    assert reordered["ok"] and reordered["written"]
    assert filled["ok"] and len(filled["written"]) == 2
    assert [holder["verb"] for holder in waited] == ["順 reorder"]
    writes = [(at, subs) for at, action, subs in server.log if _is_write(subs, action)]
    a_last = max(at for at, subs in writes if "updateNoteFields" not in subs)
    b_first = min(at for at, subs in writes if "updateNoteFields" in subs)
    assert b_first > a_last, "the fill's first write came after the reorder's last"


# --- the automatic step ------------------------------------------------------------------------------ #
def test_the_automatic_step_stands_aside_while_another_writer_holds_anki(tmp_path):
    fake = _backlog(tmp_path)
    done, thread = _holder("Backfill")
    try:
        with _patched(fake):
            assert auto.run_quietly(_settings(junban_order="content", junban_auto_reorder=True)) == ""
        fill = _fake(_lapis(0, "探検", "たんけん"))
        fill.actions = list(_ACTIONS)
        with _patched(fill), mock.patch.object(backfill, "Session", lambda settings: _Session()), \
                mock.patch.object(backfill, "rebuild_in_background", lambda *a, **k: None):
            assert auto.run_quietly(_fill_settings(enable_junban=True, junban_auto_backfill=True)) == ""
    finally:
        done.set()
        thread.join(5)
    assert fake.writes == [] and fill.note_writes == []
    with _patched(fake):                    # the next trigger, the writer gone: it runs as before
        message = auto.run_quietly(_settings(junban_order="content", junban_auto_reorder=True))
    # 2.x-dev keeps .startswith("順 (automatic): Reordered") (no job: 2.5's dense run); 3.0 (W3.5 row 7): spaced
    # always, whose first run says it spaced the cards out once, then "Reordered N cards."
    assert message.startswith("順 (automatic): ") and "Reordered" in message, message


# --- the windows ------------------------------------------------------------------------------------- #
def _junban_window():
    panel = mock.MagicMock()
    panel.q, panel._stop = queue.Queue(), threading.Event()
    panel._waiting = lambda holder: JunbanGui._waiting(panel, holder)
    return panel


def _drained(q):
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


def _run_while_held(work, close=None):
    """`work` on a worker thread while another writer holds the lock; after a moment the holder lets go —
    or, given `close`, the window closes instead."""
    done, thread = _holder("Backfill")
    worker = threading.Thread(target=work)
    worker.start()
    time.sleep(0.5)
    (close or done).set()
    worker.join(10)
    done.set()
    thread.join(5)
    assert not worker.is_alive()


def test_the_junban_window_waits_says_who_for_then_reorders(tmp_path):
    fake, panel = _backlog(tmp_path), _junban_window()
    with _patched(fake):
        _run_while_held(lambda: JunbanGui._reorder_worker(panel, _settings(junban_order="content")))
    items = _drained(panel.q)
    assert ("__MESSAGE__", "Waiting for Backfill to finish writing to Anki…", "warning") in items
    report = [item[1] for item in items if item[0] == "__REPORT__"][0]
    assert report["ok"] and not report.get("busy") and fake.writes


def test_closing_the_junban_window_mid_wait_writes_nothing(tmp_path):
    fake, panel = _backlog(tmp_path), _junban_window()
    with _patched(fake):
        _run_while_held(lambda: JunbanGui._reorder_worker(panel, _settings(junban_order="content")),
                        close=panel._stop)
    report = [item[1] for item in _drained(panel.q) if item[0] == "__REPORT__"][0]
    assert report["busy"] is True and fake.writes == []


def _backfill_window(fake):
    panel = mock.MagicMock()
    panel.q, panel._stop, panel.busy = queue.Queue(), threading.Event(), False
    panel._waiting = lambda holder: BackfillGui._waiting(panel, holder)
    settings = _fill_settings()
    with _patched(fake):
        panel._preview = backfill.preview(settings, _Session())
    panel._preview_key = panel._key.return_value = "key"
    panel._settings.return_value = settings
    panel._session_for.return_value = _Session()
    with mock.patch("modules.junban.gui.ask", lambda *a, **k: True):
        BackfillGui.on_fill(panel)
    return panel, panel._start.call_args.args[0]


def test_the_backfill_window_waits_says_who_for_then_fills():
    fake = _fake(_lapis(0, "探検", "たんけん"))
    panel, work = _backfill_window(fake)
    with _patched(fake):
        _run_while_held(work)
    items = _drained(panel.q)
    assert ("__MESSAGE__", "Waiting for Backfill to finish writing to Anki…", "warning") in items
    report = [item[1] for item in items if item[0] == "__REPORT__"][0]
    assert report["ok"] and fake.note_writes


def test_closing_the_backfill_window_mid_wait_writes_nothing():
    fake = _fake(_lapis(0, "探検", "たんけん"))
    panel, work = _backfill_window(fake)
    with _patched(fake):
        _run_while_held(work, close=panel._stop)
    report = [item[1] for item in _drained(panel.q) if item[0] == "__REPORT__"][0]
    assert report["busy"] is True and fake.note_writes == []


# --- checked again after a wait ---------------------------------------------------------------------- #
def test_after_a_wait_a_reorder_refuses_while_the_user_reviews(tmp_path):
    fake = _backlog(tmp_path, reviewing=True)
    result = {}
    with _patched(fake):
        _run_while_held(lambda: result.update(report=reposition.run(_settings(junban_order="content"), wait=5)))
    assert result["report"]["busy"] is True
    assert result["report"]["problems"] == [anki_connect.REVIEWING] and fake.writes == []


def test_after_a_wait_a_restore_of_a_replaced_snapshot_refuses(tmp_path):
    fake = _backlog(tmp_path)
    settings = _settings(junban_order="content")
    with _patched(fake):
        assert reposition.run(settings)["written"]
    confirmed = undo.load("ja")["written_at"]
    replaced = dict(undo.load("ja"), written_at="2099-01-01T00:00:00")   # the writer it waited for saved anew
    with open(undo.snapshot_path("ja"), "w", encoding="utf-8") as handle:
        json.dump(replaced, handle)
    fake.writes.clear()
    result = {}
    with _patched(fake):
        _run_while_held(lambda: result.update(report=reposition.restore(settings, wait=5, confirmed=confirmed)))
    assert result["report"]["busy"] is True
    assert result["report"]["problems"] == [anki_connect.CHANGED] and fake.writes == []


def test_after_a_wait_a_backfill_restore_of_a_replaced_snapshot_refuses():
    fake = _fake(_lapis(0, "探検", "たんけん"))
    with _patched(fake):
        assert backfill.run(_fill_settings(), _Session())["written"]
    confirmed = undo.load("ja", kind="backfill")["written_at"]
    with _patched(fake):
        assert backfill.run(_fill_settings(), _Session())["message"] == "Nothing to fill."
    path = undo.snapshot_path("ja", kind="backfill")
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(dict(data, written_at="2099-01-01T00:00:00"), handle)
    before = list(fake.note_writes)
    result = {}
    with _patched(fake):
        _run_while_held(lambda: result.update(report=backfill.restore(_fill_settings(), wait=5,
                                                                      confirmed=confirmed)))
    assert result["report"]["busy"] is True and result["report"]["problems"] == [anki_connect.CHANGED]
    assert fake.note_writes == before


def test_a_restore_that_did_not_wait_is_not_checked_again(tmp_path):
    # Uncontended nothing changes (rule 1): the confirmed snapshot is compared only after a wait.
    fake = _backlog(tmp_path)
    settings = _settings(junban_order="content")
    with _patched(fake):
        reposition.run(settings)
        assert reposition.restore(settings, confirmed="2000-01-01T00:00:00")["ok"]


# --- the windows' wiring (E1.4-adversary #3, #4) ------------------------------------------------------ #
def test_closing_either_window_sets_the_event_its_writers_wait_on():
    for window in (JunbanGui, BackfillGui):
        panel = mock.MagicMock()
        panel._stop, panel._session = threading.Event(), None
        window._close(panel)
        assert panel._stop.is_set(), window.__name__


def _restored_with(start):
    """Run the worker `on_restore` handed to `_start`; return the keyword arguments the restore got."""
    seen = {}
    record = lambda settings, **kwargs: seen.update(kwargs) or {"ok": True, "message": "", "problems": []}
    with mock.patch.object(reposition, "restore", record), mock.patch.object(backfill, "restore", record):
        start.call_args.args[0]()
    return seen


def test_the_junban_windows_restore_waits_cancels_and_carries_the_snapshot_it_asked_about(tmp_path):
    fake = _backlog(tmp_path)
    with _patched(fake):
        reposition.run(_settings(junban_order="content"))
    asked_about = undo.load("ja")["written_at"]
    panel = mock.MagicMock()
    panel.busy, panel._stop = False, threading.Event()
    panel._lang_code.return_value = "ja"
    with mock.patch("modules.junban.gui.ask", lambda *a, **k: True):
        JunbanGui.on_restore(panel)
    panel._restore_worker = lambda settings, confirmed=None: JunbanGui._restore_worker(panel, settings, confirmed)
    seen = _restored_with(panel._start)
    assert seen["wait"] is None and seen["cancel"] is panel._stop and seen["confirmed"] == asked_about


def test_the_backfill_windows_restore_carries_the_snapshot_the_question_described():
    fake = _fake(_lapis(0, "探検", "たんけん"))
    with _patched(fake):
        backfill.run(_fill_settings(), _Session())
    asked_about = undo.load("ja", kind="backfill")["written_at"]
    panel = mock.MagicMock()
    panel.busy, panel._stop = False, threading.Event()
    panel._lang_code.return_value = "ja"

    def ask(*args, **kwargs):
        # While the question is open, another Surasura's fill saves a newer snapshot.
        path = undo.snapshot_path("ja", kind="backfill")
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(dict(data, written_at="2099-01-01T00:00:00"), handle)
        return True
    with mock.patch("modules.junban.gui.ask", ask):
        BackfillGui.on_restore(panel)
    seen = _restored_with(panel._start)
    assert seen["wait"] is None and seen["cancel"] is panel._stop and seen["confirmed"] == asked_about


def test_a_backfill_restore_asked_for_an_unfinished_fill_still_restores_after_a_wait_while_that_fill_is_unfinished():
    """A Restore the user said yes to for Connect's unfinished fill waited for another writer; that fill is still
    the unfinished one, so the yes stands and its fields go back (the lock's changed check must not refuse it)."""
    note, card = _lapis(0, "探検", "たんけん", patterns="<div>〜を探検する</div>")
    fake = _fake((note, card))
    run_id = "backfill-20261006-040000-000"
    undo.save([], ["TheBank"], kind="backfill", run_id=run_id,
              fields={note["noteId"]: {"Patterns": {"before": "", "after": "<div>〜を探検する</div>"}}})
    assert undo.unfinished("ja", "backfill") == run_id
    result, waited = {}, []
    done, thread = _holder("Backfill")

    def release_once_waiting(holder):
        # The holder lets go only once the restore is really waiting, so the wait always happens (no timing guess).
        waited.append(holder)
        done.set()

    with _patched(fake):
        worker = threading.Thread(target=lambda: result.update(report=backfill.restore(
            _fill_settings(), wait=5, run=run_id, on_wait=release_once_waiting)))
        worker.start()
        worker.join(10)
    done.set()
    thread.join(5)
    assert not worker.is_alive()
    assert waited, "the restore never waited for the other writer, so the lock's changed check was not exercised"
    assert result["report"]["ok"], result["report"]
    assert fake.notes[note["noteId"]]["fields"]["Patterns"]["value"] == ""
    assert undo.unfinished("ja", "backfill") is None

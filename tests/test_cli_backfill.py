"""`surasura-cli backfill --tag <t> | --notes <ids> [--dry-run]` (P1.4 row 1.4.7; P0.3 03's later verb) → `filled`,
`skipped` (with reasons), `undo` (the run's snapshot id).

What it holds, most costly first:

  * **Only while the Connect preview is on**; off — or Junban not installed — it answers `skipped` and asks Anki
    nothing.
  * **Never while the Backfill window is open, on "All decks", or while you review** (`busy` / `needs-you` /
    `anki-busy`), and only ever under the Anki-write lock.
  * **Each note re-read just before it is written** (§7.2): a field you changed since the plan is left alone.
  * **New cards, empty fields only**, plus the source field (K40) from the job's own run folder; its own undo snapshot,
    refused while a fill never finished.

Against Junban's fake collection (real Japanese words, real Lapis fields) behind a patched transport; never a live Anki.
The module's own tests skip on a build without `modules/` (the public CI).
"""
import json
import os
import threading
from types import SimpleNamespace

import pytest

from app import locks
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

FAKE_URL = "http://127.0.0.1:18765"         # nothing listens here: only the patched transport answers
JOB = "job-20261006-1"
TAG = "surasura::connect::" + JOB


@pytest.fixture
def anki(monkeypatch):
    """Three new Lapis notes Connect's job made (探検 / 大切 — already holding パターン — / 囲む), one you mined
    (海), one of the job's in another deck, saved settings with the preview on, and the job's run folder."""
    tb = pytest.importorskip("modules.junban.tests.test_backfill")
    from modules.junban import backfill
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(backfill, "Session", lambda settings: tb._Session())

    class Tagged(tb.BackfillCollection):
        def _find_notes(self, query):
            if '"tag:' in query:
                tag = query.split('"tag:')[1].split('"')[0].lower()
                return sorted(n for n, note in self.notes.items()
                              if tag in [str(t).lower() for t in note.get("tags") or ()])
            return super()._find_notes(query)

    pairs = [tb._lapis(0, "探検", "たんけん"), tb._lapis(1, "大切", "たいせつ", patterns="<div>mine</div>"),
             tb._lapis(2, "囲む", "かこむ"), tb._lapis(3, "海", "うみ"), tb._lapis(4, "探検", "たんけん", deck="Other")]
    for index, (note, _card) in enumerate(pairs):
        note["fields"]["MiscInfo"] = {"value": "", "order": 5}
        note["tags"] = [] if index == 3 else [TAG]
    models = {"Lapis": tb.LAPIS + ["MiscInfo"]}
    fake = Tagged([p[1] for p in pairs], [p[0] for p in pairs], models)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)
    h.write_settings(anki_connect_url=FAKE_URL, connect_enabled=True, enable_junban=True,
                     junban_backfill_deck="TheBank", junban_backfill_fills=["patterns"])
    run_dir = os.path.join(h.root(), "local", "connect", "runs", JOB)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "run-1.json"), "w", encoding="utf-8") as f:
        json.dump({"episodes": [{"video_file": os.path.join(h.root(), "Frieren", "第05話.mkv")}]}, f, ensure_ascii=False)
    with open(os.path.join(run_dir, "settings-export.json"), "w", encoding="utf-8") as f:
        json.dump({"configured": True, "settings": {"anki_deck_name": "TheBank", "anki_note_type": "Lapis",
                                                    "anki_fields": {"word": "Expression", "sentence": "Sentence",
                                                                    "source": "MiscInfo"}}}, f)
    return SimpleNamespace(fake=fake, patched=tb._patched, field=tb.FIELD, note=tb.FIRST_NOTE)


def _field(fake, note_id, name):
    return fake.notes[note_id]["fields"][name]["value"]


def test_it_fills_the_jobs_new_notes_empty_fields_and_their_source_with_an_undo_of_its_own(anki):
    from modules.junban import backfill, undo
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 0, line
    n = anki.note
    assert _field(anki.fake, n, "Patterns") == anki.field["探検"]
    assert _field(anki.fake, n + 1, "Patterns") == "<div>mine</div>", "a field holding anything is never written"
    assert _field(anki.fake, n, "MiscInfo") == "Frieren · 第05話"
    assert _field(anki.fake, n + 3, "Patterns") == "", "your own note isn't the job's"
    assert _field(anki.fake, n + 4, "Patterns") == "", "the job's note in another deck is left alone"
    assert line["notes"] == 4 and line["filled"] == 3       # 探検, 大切 (its source only), 囲む
    assert line["skipped"] == {"other deck": 1, "already filled": 1}
    saved = undo.load("ja", kind="backfill", run_id=line["undo"])
    assert saved["complete"] is True and saved["kind"] == "backfill"
    assert not os.path.exists(undo.snapshot_path("ja", "backfill")), "never the window's Restore point"

    anki.fake.notes[n + 2]["fields"]["Patterns"]["value"] = "<div>yours now</div>"     # you edit one since
    with anki.patched(anki.fake):
        report = backfill.restore_run(dict(json.load(open(os.path.join(h.root(), "settings.json"))),
                                           target_language="ja"), line["undo"])
    assert report["ok"] and report["skipped"] == 1
    assert _field(anki.fake, n, "Patterns") == "" and _field(anki.fake, n, "MiscInfo") == ""
    assert _field(anki.fake, n + 2, "Patterns") == "<div>yours now</div>"


def test_a_dry_run_writes_nothing_and_says_what_it_would_fill(anki):
    from modules.junban import undo
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG, "--dry-run")
    assert code == 0 and line["dry_run"] and line["filled"] == 3 and line["undo"] is None
    assert anki.fake.note_writes == []
    assert not os.path.isdir(undo.runs_folder("ja")) or not os.listdir(undo.runs_folder("ja"))


def test_named_notes_are_filled_by_id(anki):
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--notes", f"{anki.note + 2},{anki.note + 3}")
    assert code == 0 and line["notes"] == 2 and line["filled"] == 1     # 囲む; 海 has nothing to add
    assert _field(anki.fake, anki.note + 2, "Patterns") == anki.field["囲む"]
    assert _field(anki.fake, anki.note + 2, "MiscInfo") == "", "no job named, no source"


def test_each_note_is_read_again_before_it_is_written(anki, monkeypatch):
    """§7.2: you edit 囲む's パターン while the fill plans; it is left as you wrote it, and counted."""
    from modules.junban import backfill
    planned = backfill.plan

    def plan_then_edit(*args, **kwargs):
        out = planned(*args, **kwargs)
        anki.fake.notes[anki.note + 2]["fields"]["Patterns"]["value"] = "<div>typed meanwhile</div>"
        return out
    monkeypatch.setattr(backfill, "plan", plan_then_edit)
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 0 and line["skipped"].get("changed since") == 1
    assert _field(anki.fake, anki.note + 2, "Patterns") == "<div>typed meanwhile</div>"


def test_a_fill_that_never_finished_refuses_the_next_until_it_is_put_back(anki):
    from modules.junban import backfill, undo
    anki.fake.refuse_note_writes = "collection is not open"
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 1 and line["code"] == "failed"
    assert undo.unfinished("ja", "backfill") is not None
    anki.fake.refuse_note_writes = ""
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 1 and "did not finish" in line["message"]
    settings = dict(json.load(open(os.path.join(h.root(), "settings.json"))), target_language="ja")
    with anki.patched(anki.fake):
        assert backfill.restore(settings)["ok"]                 # the window's Restore takes that run back first
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 0 and line["filled"] == 3


def test_never_on_all_decks(anki):
    h.write_settings(anki_connect_url=FAKE_URL, connect_enabled=True, enable_junban=True, junban_backfill_deck="")
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 4 and line["code"] == "needs-you" and anki.fake.requests == []


def test_never_while_you_review(anki):
    anki.fake.reviewing = True
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 3 and line["code"] == "anki-busy" and anki.fake.note_writes == []


def test_never_while_the_backfill_window_is_open(anki):
    gui = pytest.importorskip("modules.junban.backfill_gui")
    window = SimpleNamespace(_closing=False, _window_lock=None, _window_lock_guard=threading.Lock(),
                             _window_lock_owner=object(), _stop=threading.Event(), _session=None, busy=False,
                             destroy=lambda: None)
    worker = threading.Thread(target=gui.BackfillGui._hold_window_lock, args=(window,))    # as the window does
    worker.start()
    worker.join(10)
    assert locks.read_holder("backfill-window")["verb"] == "the Backfill window"
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 3 and line["code"] == "busy" and anki.fake.requests == []
    gui.BackfillGui._close(window)
    with locks.take("backfill-window", "the test's look", wait=5.0):
        pass
    assert window._window_lock is None


def test_with_the_preview_off_it_asks_anki_nothing(anki):
    h.write_settings(anki_connect_url=FAKE_URL, connect_enabled=False, enable_junban=True,
                     junban_backfill_deck="TheBank")
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 0 and line["skipped"] == "the Connect preview is off" and anki.fake.requests == []


def test_note_ids_that_are_not_numbers_are_a_usage_error(anki):
    code, line = h.call("backfill", "--notes", "12,abc")
    assert code == 2 and line["code"] == "usage"

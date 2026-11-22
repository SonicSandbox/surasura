# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixes found in review, each with the case that would have hurt a learner.

  * a write Anki cut part-way (a review started after 50 cards, Anki closed) left AI audio on cards with no Undo;
  * the frozen build lacked the CPU PyTorch list, so every CPU install failed;
  * a stray run lock left Install and Remove both refusing for good;
  * the voice's key and sentences could go through a system proxy;
  * Backfill hid the Undo once the beta was off or the voice removed, and a run that wrote nothing hid the last one's.
"""
import os
import urllib.request
from unittest import mock

import pytest

import modules.irodori as irodori
from app import anki_connect
from modules.irodori import make, runtime, server, writer
from modules.irodori.tests.fake_anki import FakeAnki
from modules.irodori.tests.test_irodori import FakeServer

URL = anki_connect.DEFAULT_URL
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture
def anki():
    fake = FakeAnki()
    with mock.patch("urllib.request.urlopen", fake):
        yield fake


@pytest.fixture
def no_ffmpeg(monkeypatch):
    monkeypatch.setattr(make, "_ffmpeg", lambda: None)


def test_a_write_cut_part_way_keeps_its_undo_reachable(anki, installed, shared_writer, no_ffmpeg, monkeypatch):
    real = shared_writer.fill

    def cut(anki, ledger, clips, field, tag, by, texts=None, verb=None):   # the contract's names: the seam checks
        # the shared writer wrote the first card, then you began reviewing: it raises with its record's id
        first = dict(list(clips.items())[:1])
        got = real(anki, ledger, first, field=field, tag=tag, by=by)
        e = shared_writer.Reviewing()
        e.sentence_audio_id = got["id"]
        raise e
    monkeypatch.setattr(shared_writer, "fill", cut)
    report = make.make_for_notes({}, "ja", list(anki.notes), srv=FakeServer(), source="backfill")
    assert not report["ok"] and report["run"] and report["written"] == [101]
    assert anki_connect.REVIEWING in report["problems"]
    assert irodori.last_run("ja")["run"] == report["run"]                 # the door's Undo finds it
    monkeypatch.setattr(shared_writer, "fill", real)
    undone = irodori.undo({}, "ja", report["run"])
    assert undone["ok"] and anki.notes[101]["SentenceAudio"] == ""


def test_any_failure_of_the_shared_writer_is_said_never_raised(anki, installed, shared_writer, monkeypatch):
    import sqlite3

    def locked(anki, ledger, clips, field, tag, by, texts=None, verb=None):
        raise sqlite3.OperationalError("database is locked")

    def locked_undo(anki, ledger, rid, verb=None):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(shared_writer, "fill", locked)
    got = writer.fill(URL, "ja", {101: __file__})
    assert not got["ok"] and "database is locked" in got["problems"][0] and got["run"] is None
    monkeypatch.setattr(shared_writer, "undo", locked_undo)
    assert not writer.undo(URL, "ja", "x")["ok"]


def test_the_build_carries_every_file_the_runtime_reads():
    spec = open(os.path.join(_REPO, "packaging", "Surasura.spec"), encoding="utf-8").read()
    for name in ("host.py", "requirements-server.txt", "requirements-torch-cpu.txt"):
        assert f"'{name}'" in spec, name
        assert os.path.isfile(os.path.join(os.path.dirname(runtime.__file__), name))
    assert "'voices'" in spec
    src = open(runtime.__file__, encoding="utf-8").read()
    assert src.count('os.path.join(here, "requirements-') == 2      # the two lists the install reads, both above


def test_nothing_installed_makes_no_folder_for_a_run_lock():
    assert runtime.running() is None and not os.path.exists(runtime.home())


def test_a_stray_lock_never_blocks_install_or_remove(monkeypatch):
    os.makedirs(runtime.home())
    open(os.path.join(runtime.home(), runtime.RUN_LOCK), "w").close()
    assert runtime.remove() == 0 and not os.path.exists(runtime.home())
    os.makedirs(runtime.home())
    open(os.path.join(runtime.home(), runtime.RUN_LOCK), "w").close()
    from modules.irodori.tests.test_irodori import FakeUv, _pins
    assert runtime.install(chosen="cpu", opener=_pins(monkeypatch), run=FakeUv())["installed"]


def test_the_voice_is_asked_on_loopback_without_any_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")
    srv = server.Server()
    handlers = getattr(getattr(srv.opener, "__self__", None), "handlers", [])
    assert handlers and not [h for h in handlers if isinstance(h, urllib.request.ProxyHandler) and h.proxies]
    assert urllib.request.getproxies().get("http")                   # (the proxy is set: the default opener uses it)


def test_backfills_undo_shows_with_the_beta_off_and_any_doors_run(anki, installed, shared_writer, no_ffmpeg):
    pytest.importorskip("PyQt6")
    from modules.irodori import qt_backfill
    report = make.make_for_notes({}, "ja", list(anki.notes), srv=FakeServer(), source="connect")
    on, last = qt_backfill._shown({"enable_irodori": False, "target_language": "ja"})
    assert on is False and last["run"] == report["run"]                 # Connect's book run: Undo offered here
    runtime.remove()
    on, last = qt_backfill._shown({"enable_irodori": True, "target_language": "ja"})
    assert on is False and last["run"] == report["run"]                 # the voice removed: its Undo still is


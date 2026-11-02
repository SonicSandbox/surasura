"""Send report's two writes the window's review asked to hold under `send_report._BUSY` (Mado, alpha 10; the program
lead's answer to the 19:58 note): a checked delete of the waiting zip, and *New code*.

What a wrong answer would cost: *Back*, a close or *Don't send* deleting a zip the tester never saw go away — an older
report kept after a failed send, or another window's newer one it is showing on What goes (its Send then has nothing to
send); *New code* and a send's end writing `report_send.json` at once, so the day's count is lost and a 6th send gets
through. Words are a learner's real ones; the fake receiver is on loopback only.
"""
import threading

import pytest

from app import report, scrub, send_report
from tests import scrub_probe as probe_person

WHAT = "「薬屋のひとりごと」第3話の単語がCurrentに出てこない。"
OTHER = "生词本里的“风景”显示了两次"


@pytest.fixture(autouse=True)
def _fresh_identity():
    scrub.reset()
    yield
    scrub.reset()


@pytest.fixture
def person(tmp_path, monkeypatch):
    return probe_person.make(tmp_path, monkeypatch)


def _held(fn, *args):
    """`fn(*args)` on a thread while another holds _BUSY: -> (whether it finished while held, its answer after)."""
    got = []
    with send_report._BUSY:
        t = threading.Thread(target=lambda: got.append(fn(*args)), daemon=True)
        t.start()
        t.join(0.3)
        early = bool(got)
    t.join(10)
    return early, got[0] if got else None


# --- discard(expect=) ---------------------------------------------------------------------------------------------- #
def test_a_checked_delete_leaves_another_waiting_zip_alone_and_deletes_its_own(person):
    report.save(WHAT, "第3話の単語が出ると思った")
    ob = send_report.build("ja", include_results=False)
    assert send_report.discard(expect="0" * 64) is False                          # not the zip it showed
    assert send_report.waiting() is not None and send_report.waiting().sha256 == ob.sha256
    assert send_report.discard(expect=ob.sha256) is True                         # its own: deleted
    assert send_report.waiting() is None
    assert send_report.discard(expect=ob.sha256) is False                        # nothing left to delete


def test_a_checked_delete_after_a_newer_build_keeps_the_newer_zip(person):
    report.save(WHAT)
    older = send_report.build("ja", include_results=False)
    report.save(OTHER)
    newer = send_report.build("ja", include_results=False)                       # another window's press, meanwhile
    assert newer.sha256 != older.sha256
    assert send_report.discard(expect=older.sha256) is False
    assert send_report.waiting().sha256 == newer.sha256 and len(report.listed()) == 2


def test_a_checked_delete_waits_for_a_build_or_a_send_under_way(person):
    report.save(WHAT)
    ob = send_report.build("ja", include_results=False)
    early, gone = _held(send_report.discard, ob.sha256)
    assert not early and gone is True                                            # checked and deleted only after


def test_an_unchecked_delete_still_deletes_whatever_waits(person):
    report.save(WHAT)
    send_report.build("ja", include_results=False)
    assert send_report.discard() is True and send_report.waiting() is None


# --- new_code() ---------------------------------------------------------------------------------------------------- #
def test_new_code_waits_for_a_send_under_way_so_the_days_count_is_never_lost(person):
    import datetime
    old = send_report.sender_code()
    early, code = _held(send_report.new_code)
    assert not early and code != old and code == send_report.sender_code()
    day = datetime.datetime.now().astimezone()
    send_report._save_state({**send_report._state(), "day": day.date().isoformat(), "sent": 4})
    send_report.new_code()
    assert send_report.sent_today(day) == 4                                      # (its read-modify-write keeps it)


def test_a_first_send_makes_its_code_under_the_lock_it_already_holds(person, monkeypatch):
    """No code yet: `send` makes one inside _BUSY (`headers`). It must not wait on itself."""
    from app import telemetry
    from tests.test_send_report import Receiver
    r = Receiver()
    monkeypatch.setattr(telemetry, "report_receiver", lambda env="production": r.url)
    try:
        report.save(WHAT)
        ob = send_report.build("ja", include_results=False)
        assert "sender" not in send_report._state()
        got = []
        t = threading.Thread(target=lambda: got.append(send_report.send(nonce=ob.nonce)), daemon=True)
        t.start()
        t.join(20)
        assert got and got[0].outcome == send_report.SENT
        sent = {k.lower(): v for k, v in r.got[0]["headers"].items()}["x-report-sender"]
        assert sent == send_report.sender_code()
    finally:
        r.close()

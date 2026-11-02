"""Send report's request half (`app/send_report.py`; SR-4a, `tracks/ship/work/send-report/SPEC.md` §3–5): the outbox,
the one POST and what each answer does — against a fake receiver on this PC's loopback (never the network).

What a wrong answer would cost: the telemetry id riding along with a report (the line says nothing identifies them); a
report sent without a press (a retry by itself, Q4) or a 6th time in a day; a sent report left on the list, so it goes
again next time; a failed send that loses the report or clears the list; a retry that makes a second #ID; a Discord
name sent that wasn't typed. Words are a learner's real ones.
"""
import base64
import datetime
import hashlib
import http.server
import json
import os
import threading
import time
import zipfile

import pytest

from app import path_utils, report, scrub, send_report, telemetry
from tests import scrub_probe as probe_person

WHAT = "「甄嬛传」第五集を見終わったのに、単語表が更新されなかった。"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_RECEIVER = telemetry.report_receiver                 # (the receiver fixture puts a fake in its place)


@pytest.fixture(autouse=True)
def _fresh_identity():
    scrub.reset()
    yield
    scrub.reset()


class Receiver:
    """A fake receiver on 127.0.0.1: records each request; answers with `self.answer` (status, body) or sleeps."""

    def __init__(self):
        self.got = []
        self.answer = (201, {"id": "K3Q7PM"})
        self.sleep = 0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.got.append({"path": self.path, "headers": dict(self.headers), "body": body})
                if outer.sleep:
                    time.sleep(outer.sleep)
                status, payload = outer.answer
                data = json.dumps(payload).encode("utf-8") if isinstance(payload, dict) else payload
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

            def log_message(self, *args):
                pass
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def receiver(monkeypatch):
    r = Receiver()
    monkeypatch.setattr(telemetry, "report_receiver", lambda env="production": r.url)
    yield r
    r.close()


@pytest.fixture
def saved(tmp_path, monkeypatch):
    """The probe person's PC with one saved report and a telemetry id on file."""
    probe_person.make(tmp_path, monkeypatch)
    return report.save(WHAT, "新しいカードが後ろに回ると思った", where="Report a problem")


def _x_headers(h):
    return {k: v for k, v in h.items() if k.lower().startswith("x-")}


# --- the press: the outbox ----------------------------------------------------------------------------------------- #
def test_the_press_makes_the_outbox_zip_beside_the_list_and_keeps_the_report_listed(saved):
    ob = send_report.build("ja")
    persistent = path_utils.get_persistent_user_data_path()
    assert os.path.dirname(ob.path) == os.path.join(persistent, send_report.OUTBOX_DIR)
    assert not ob.path.startswith(report.folder())
    assert [r.id for r in report.listed()] == [saved.id]                         # nothing sent yet: still listed
    assert send_report.waiting().nonce == ob.nonce and len(ob.nonce) == 32
    assert hashlib.sha256(open(ob.path, "rb").read()).hexdigest() == ob.sha256
    assert f"reports/{saved.id}/report.txt" in dict(ob.entries) and "MANIFEST.txt" in ob.describe()


def test_nothing_waiting_reads_nothing_and_makes_no_folder(tmp_path, monkeypatch):
    probe_person.make(tmp_path, monkeypatch)
    assert send_report.waiting() is None
    assert not os.path.exists(os.path.join(path_utils.persistent_root(), send_report.OUTBOX_DIR))


def test_a_new_press_replaces_the_waiting_zip_and_carries_the_reports_still_listed(saved, receiver):
    first = send_report.build("ja")
    second_report = report.save("二つ目の問題", "")
    again = send_report.build("ja")
    assert again.nonce != first.nonce and send_report.waiting().nonce == again.nonce
    assert {f"reports/{saved.id}/report.txt", f"reports/{second_report.id}/report.txt"} <= set(dict(again.entries))


def test_dont_send_deletes_the_zip_and_the_reports_stay(saved):
    send_report.build("ja")
    assert send_report.discard() is True
    assert send_report.waiting() is None and [r.id for r in report.listed()] == [saved.id]
    assert send_report.discard() is False


def test_the_guard_refusing_the_zip_leaves_no_outbox(saved, monkeypatch):
    monkeypatch.setattr(report, "_entry_bytes", lambda e, data, language, send, ident: (data + b" ztanprobe", None))
    with pytest.raises(report.Unsafe):
        send_report.build("ja")
    folder = os.path.join(path_utils.persistent_root(), send_report.OUTBOX_DIR)
    assert send_report.waiting() is None and os.listdir(folder) == []


# --- 10 MB ------------------------------------------------------------------------------------------------------- #
def _noise(n):
    return base64.b64encode(os.urandom(n)).decode("ascii")


def _big_results_and_log():
    results = os.path.join(path_utils.get_user_data_path(), "results")
    os.makedirs(results, exist_ok=True)
    with open(os.path.join(results, "reading_list.csv"), "w", encoding="utf-8") as f:
        f.write("Word,Orth,Context 1\n" + "".join(f"文化祭,文化祭,{_noise(300)}\n" for _ in range(1000)))
    logs = os.path.join(path_utils.get_local_data_path(), "logs")
    os.makedirs(logs, exist_ok=True)
    with open(os.path.join(logs, "cli.log"), "w", encoding="utf-8") as f:
        f.write("".join(f"verb=generate {_noise(300)}\n" for _ in range(1000)))


def test_over_the_size_results_go_first_then_each_log_keeps_its_end(saved, monkeypatch):
    _big_results_and_log()
    monkeypatch.setattr(send_report, "MAX_ZIP", 360 * 1024)                     # results ~300 KB, the log ~300 KB
    monkeypatch.setattr(send_report, "LOG_TAIL", 20 * 1024)
    ob = send_report.build("ja")
    names = dict(ob.entries)
    assert not any(n.startswith("results/") for n in names) and names["logs/cli.log"] > 200 * 1024
    assert any(x.startswith("results\\: left out (to keep the report under 10 MB)") for x in ob.left_out)
    monkeypatch.setattr(send_report, "MAX_ZIP", 100 * 1024)
    ob = send_report.build("ja")
    names = dict(ob.entries)
    assert names["logs/cli.log"] <= 20 * 1024 and ob.size <= 100 * 1024
    assert any(x.startswith("logs/cli.log: only its last") for x in ob.left_out)
    with zipfile.ZipFile(ob.path) as z:
        assert z.read("logs/cli.log").startswith(b"verb=generate ")              # cut at a whole line


def test_still_too_big_raises_and_leaves_no_outbox(saved, monkeypatch):
    _big_results_and_log()
    monkeypatch.setattr(send_report, "MAX_ZIP", 2 * 1024)
    with pytest.raises(send_report.TooBig):
        send_report.build("ja")
    assert send_report.waiting() is None
    assert not os.path.exists(os.path.join(path_utils.persistent_root(), send_report.OUTBOX_DIR,
                                           send_report.BUILDING))


# --- the request -------------------------------------------------------------------------------------------------- #
def test_the_request_carries_exactly_its_headers_and_the_zip_never_the_telemetry_id(saved, receiver):
    ob = send_report.build("ja")
    got = send_report.send()
    assert got.outcome == send_report.SENT and got.id == "K3Q7PM"
    req = receiver.got[0]
    assert req["path"] == "/report" and req["body"] == open(os.path.join(
        path_utils.get_persistent_user_data_path(), send_report.SENT_DIR, "K3Q7PM.zip"), "rb").read()
    x = _x_headers(req["headers"])
    assert set(x) == {"X-Surasura-Version", "X-Surasura-Language", "X-Surasura-Env", "X-Report-Nonce",
                      "X-Report-Sha256", "X-Report-Sender"}
    from app import __version__
    assert x["X-Surasura-Version"] == __version__ and x["X-Surasura-Language"] == "ja"
    assert x["X-Report-Nonce"] == ob.nonce and x["X-Report-Sha256"] == hashlib.sha256(req["body"]).hexdigest()
    assert x["X-Report-Sender"] == send_report.sender_code()
    assert req["headers"]["Content-Type"] == "application/zip" and "Cookie" not in req["headers"]
    everything = json.dumps(req["headers"]).lower().encode("utf-8") + req["body"].lower()
    assert probe_person.TELEMETRY_ID.encode("ascii") not in everything


@pytest.mark.parametrize("telemetry_on", [True, False])
def test_it_goes_with_telemetry_on_or_off_and_the_headers_are_the_same(saved, receiver, telemetry_on):
    with open(path_utils.get_settings_path(), "w", encoding="utf-8") as f:
        json.dump({"telemetry_enabled": telemetry_on}, f)
    send_report.build("ja")
    assert send_report.send().outcome == send_report.SENT
    assert "X-Report-Sender" in receiver.got[0]["headers"]
    assert probe_person.TELEMETRY_ID not in json.dumps(receiver.got[0]["headers"])


def test_a_sent_report_leaves_the_list_and_its_zip_is_kept_on_this_pc(saved, receiver):
    send_report.build("ja")
    send_report.send()
    assert report.listed() == [] and send_report.waiting() is None
    [(rid, when, path)] = send_report.sent_reports()
    assert rid == "K3Q7PM" and os.path.isfile(path) and send_report.sent_today() == 1


def test_a_known_nonce_answered_200_is_sent_too(saved, receiver):
    receiver.answer = (200, {"id": "A7F3QX"})
    send_report.build("ja")
    assert send_report.send().id == "A7F3QX" and report.listed() == []


@pytest.mark.parametrize("status, outcome", [(413, send_report.TOO_BIG), (429, send_report.BUSY),
                                             (503, send_report.PAUSED), (500, send_report.OFFLINE),
                                             (502, send_report.OFFLINE), (400, send_report.REFUSED),
                                             (404, send_report.REFUSED)])
def test_a_refusal_keeps_the_zip_and_the_list(saved, receiver, status, outcome):
    receiver.answer = (status, {"error": "no"})
    ob = send_report.build("ja")
    got = send_report.send()
    assert got.outcome == outcome and got.status == status and got.id is None
    assert send_report.waiting().nonce == ob.nonce and len(report.listed()) == 1
    assert send_report.sent_today() == 0


@pytest.mark.parametrize("answer", [b"not json", {"id": "k3q7pm"}, {"id": "K3Q7P"}, {"id": "K3Q7PI"}, {}])
def test_a_201_without_a_proper_id_is_not_taken_as_sent(saved, receiver, answer):
    receiver.answer = (201, answer)
    send_report.build("ja")
    assert send_report.send().outcome == send_report.REFUSED and len(report.listed()) == 1


def test_send_now_after_a_failure_sends_the_same_nonce_so_one_report_gets_one_id(saved, receiver):
    receiver.answer = (503, {"error": "paused"})
    ob = send_report.build("ja")
    send_report.send()
    receiver.answer = (201, {"id": "K3Q7PM"})
    assert send_report.send().outcome == send_report.SENT
    assert [r["headers"]["X-Report-Nonce"] for r in receiver.got] == [ob.nonce, ob.nonce]
    assert receiver.got[0]["body"] == receiver.got[1]["body"]


def test_no_connection_keeps_the_report_waiting(saved, monkeypatch):
    r = Receiver()
    url = r.url
    r.close()                                                                    # nothing listens there now
    monkeypatch.setattr(telemetry, "report_receiver", lambda env="production": url)
    send_report.build("ja")
    assert send_report.send().outcome == send_report.OFFLINE
    assert send_report.waiting() is not None and len(report.listed()) == 1


def test_a_receiver_that_doesnt_answer_in_time_is_offline(saved, receiver, monkeypatch):
    monkeypatch.setattr(send_report, "TIMEOUT", (2, 0.3))
    receiver.sleep = 1.0
    send_report.build("ja")
    assert send_report.send().outcome == send_report.OFFLINE and send_report.waiting() is not None


def test_the_sixth_send_of_a_day_is_refused_before_any_request(saved, receiver):
    for n in range(send_report.PER_DAY):
        report.save(f"問題 {n}", "")
        send_report.build("ja")
        receiver.answer = (201, {"id": f"K3Q7P{n}"})
        assert send_report.send().outcome == send_report.SENT
    report.save("六つ目", "")
    send_report.build("ja")
    got = send_report.send()
    assert got.outcome == send_report.LIMIT and len(receiver.got) == send_report.PER_DAY
    assert send_report.waiting() is not None and len(report.listed()) == 1


def test_the_days_count_starts_again_the_next_day(saved, receiver):
    today = datetime.datetime(2026, 11, 1, 23, 50).astimezone()
    data = {"day": today.date().isoformat(), "sent": send_report.PER_DAY}
    report._atomic_write(os.path.join(path_utils.get_persistent_user_data_path(), send_report.STATE_FILE),
                         json.dumps(data).encode("utf-8"))
    send_report.build("ja")
    assert send_report.send(now=today).outcome == send_report.LIMIT and receiver.got == []
    assert send_report.send(now=today + datetime.timedelta(minutes=20)).outcome == send_report.SENT


def test_nothing_waiting_is_an_error_never_a_request(saved, receiver):
    with pytest.raises(ValueError):
        send_report.send()
    assert receiver.got == []


def test_importing_and_looking_makes_no_request(saved, monkeypatch):
    """A window open with a report waiting sends nothing by itself (Q4)."""
    import requests
    calls = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: calls.append(a))
    send_report.build("ja")
    send_report.waiting(), send_report.sent_reports(), send_report.sender_code(), send_report.remembered_name()
    assert calls == []


# --- the Discord name and the sender code -------------------------------------------------------------------------- #
def test_the_discord_name_goes_only_when_typed_and_is_remembered(saved, receiver):
    send_report.build("ja")
    send_report.send(name="  ぞえ_probe  ")
    sent = receiver.got[0]["headers"]["X-Discord-Name"]
    assert "=" not in sent and base64.urlsafe_b64decode(sent + "=" * (-len(sent) % 4)).decode("utf-8") == "ぞえ_probe"
    assert send_report.remembered_name() == "ぞえ_probe"
    report.save("二回目", "")
    send_report.build("ja")
    send_report.send(name="")
    assert "X-Discord-Name" not in receiver.got[1]["headers"] and send_report.remembered_name() == ""


def test_a_name_over_32_characters_is_refused_before_any_request(saved, receiver):
    send_report.build("ja")
    with pytest.raises(ValueError):
        send_report.send(name="あ" * 33)
    assert receiver.got == [] and send_report.waiting() is not None


def test_the_sender_code_is_made_once_kept_and_new_code_replaces_it(saved):
    code = send_report.sender_code()
    assert len(code) == 8 and set(code) <= set(send_report.CROCKFORD)
    assert send_report.sender_code() == code
    fresh = send_report.new_code()
    assert fresh != code and send_report.sender_code() == fresh
    assert fresh not in probe_person.TELEMETRY_ID.upper()


def test_a_broken_state_file_is_read_as_a_new_one(saved):
    with open(os.path.join(path_utils.get_persistent_user_data_path(), send_report.STATE_FILE), "w") as f:
        f.write("{not json")
    assert send_report.sent_today() == 0 and send_report.remembered_name() == ""
    assert len(send_report.sender_code()) == 8


# --- where and as what -------------------------------------------------------------------------------------------- #
def test_from_source_or_a_dev_build_it_goes_as_test(monkeypatch):
    monkeypatch.setattr(path_utils, "is_frozen", lambda: False)
    monkeypatch.setattr(telemetry, "TELEMETRY_ENV", "production")
    assert send_report.env() == "test"
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    assert send_report.env() == "production"
    monkeypatch.setattr(telemetry, "TELEMETRY_ENV", "dev")
    assert send_report.env() == "test"


def test_the_built_in_receiver_is_the_builds_and_is_used_when_none_is_kept(monkeypatch, tmp_path):
    with open(os.path.join(ROOT, "packaging", "build_config.json"), encoding="utf-8") as f:
        assert telemetry.BUILT_IN_URL == json.load(f)["release"]["telemetry_url"]
    monkeypatch.setattr(telemetry, "TELEMETRY_URL", None)
    monkeypatch.setattr(telemetry, "_cached_url", lambda: None)
    assert telemetry.receiver_url() is None                                      # the heartbeat: still nowhere
    assert telemetry.report_receiver() == telemetry.BUILT_IN_URL
    monkeypatch.setattr(telemetry, "TELEMETRY_URL", "https://example.invalid/hb")
    assert telemetry.report_receiver() == "https://example.invalid/hb"


def test_a_test_report_goes_to_the_test_worker_never_the_live_one(saved, receiver, monkeypatch):
    """From source, a dev build or an alpha (env test): the test Worker, whatever address update.json kept."""
    monkeypatch.setattr(telemetry, "_cached_url", lambda: "https://surasura-telemetry.sonicswain.workers.dev")
    assert REAL_RECEIVER("test") == telemetry.BUILT_IN_TEST_URL != telemetry.BUILT_IN_URL
    asked = []
    monkeypatch.setattr(telemetry, "report_receiver", lambda env="production": asked.append(env) or receiver.url)
    send_report.build("zh")
    assert send_report.send().outcome == send_report.SENT and asked == ["test"]
    assert receiver.got[0]["headers"]["X-Surasura-Env"] == "test"


def test_the_heartbeat_in_dev_still_sends_nothing(monkeypatch):
    import requests
    calls = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(telemetry, "TELEMETRY_ENV", "dev")
    telemetry._send_heartbeat_thread("Multilingual-beta")
    assert calls == []


# --- sent copies --------------------------------------------------------------------------------------------------- #
def test_a_sent_copy_is_kept_90_days_then_removed(tmp_path, monkeypatch):
    probe_person.make(tmp_path, monkeypatch)
    folder = os.path.join(path_utils.get_persistent_user_data_path(), send_report.SENT_DIR)
    os.makedirs(folder)
    now = datetime.datetime.now().astimezone()
    for rid, days in (("K3Q7PM", 89), ("A7F3QX", 91)):
        path = os.path.join(folder, f"{rid}.zip")
        open(path, "wb").write(b"PK\x05\x06" + b"\x00" * 18)
        stamp = (now - datetime.timedelta(days=days)).timestamp()
        os.utime(path, (stamp, stamp))
    open(os.path.join(folder, "notes.txt"), "w").write("x")
    assert [rid for rid, _w, _p in send_report.sent_reports(now)] == ["K3Q7PM"]
    assert sorted(os.listdir(folder)) == ["K3Q7PM.zip", "notes.txt"]


def test_a_waiting_zip_changed_since_it_was_made_is_never_sent(saved, receiver):
    ob = send_report.build("ja")
    with open(ob.path, "ab") as f:
        f.write(b"\x00")
    assert send_report.waiting() is None                                         # its size no longer matches
    with pytest.raises(ValueError):
        send_report.send()
    assert receiver.got == []


def test_dont_send_removes_the_zip_itself(saved):
    ob = send_report.build("ja")
    send_report.discard()
    assert not os.path.exists(ob.path)
    assert os.listdir(os.path.dirname(ob.path)) == []


def test_a_redirect_is_never_followed_with_the_zip(saved, receiver):
    """A 307 / 308 would post the zip again to wherever it points: never."""
    other = Receiver()
    try:
        receiver.answer = (307, b"")
        real = receiver.server.RequestHandlerClass.send_response

        def to_other(handler, status, message=None):
            real(handler, status, message)
            if status == 307:
                handler.send_header("Location", other.url + "/report")
        receiver.server.RequestHandlerClass.send_response = to_other
        send_report.build("ja")
        assert send_report.send().outcome == send_report.REFUSED
        assert other.got == [] and send_report.waiting() is not None
    finally:
        other.close()

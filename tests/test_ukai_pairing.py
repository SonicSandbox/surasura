"""鵜飼 Ukai's pairing (app/services/ukai_pairing.py; Ukai SPEC §0 U4, §6 U-S1; the token's file adapted from #474):
`POST /v1/pair` -> the window's Allow card with a 4-digit code -> `GET /v1/pair/<id>` hands the token over once.

What a wrong answer would cost a learner: a web page, another extension or a replayed request getting the token (and
with it posting into their library or reading what waits to be recorded); a pairing nobody allowed; a *Not now* that
pairs anyway; *Forget Ukai* that still lets the old token in until a restart; the token in settings.json (it ships in
the release and leaves with every export) or a log; a card opened again and again by one Ukai asking in a loop; and,
until Ukai 1.0 ships with it, any of this switched on.

Through the real door on a free loopback port (EXT_PORT moved off 27631 whenever the class is on). Ukai's own
requests carry no lines of a language: the paired route is fed real ja / zh subtitle lines from `tests/Test Resources`.
"""
import http.client
import json
import os
import threading

import pysrt
import pytest

from app import door
from app.services import ukai_pairing as up

ID = "kbmfpngjjgdllneeigpgjifpgocmfgmb"
ORIGIN = "chrome-extension://" + ID
OTHER = "chrome-extension://aapbdbdomjkkjkaonfhkkikfgjllcleb"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind((door.HOST, 0))
        return s.getsockname()[1]


@pytest.fixture
def ukai(tmp_path, monkeypatch):
    """A door with Ukai's class on, its pairing's routes + one paired route (`POST /v1/echo`); `asked` the cards the
    window was asked to open; `clock` the pairing's."""
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    monkeypatch.setattr(door, "EXT_PORT", _free_port())
    asked, clock = [], Clock()
    pairing = up.Pairing(asked.append, where=str(tmp_path / "roaming" / up.FILE), clock=clock)
    echoed, errors = [], []

    def echo(call):
        body = call.json()
        echoed.append(body)
        return {"echo": body}

    d = door.Door({}, str(tmp_path / "results"), on_error=lambda path, e: errors.append((path, e)),
                  extension=pairing.extension({"POST /v1/echo": echo})).start()
    d.pairing, d.asked, d.clock, d.echoed, d.errors = pairing, asked, clock, echoed, errors
    d.file = tmp_path / "roaming" / up.FILE
    yield d
    d.stop()


def _ask(d, method, path, body=None, origin=ORIGIN, token=None):
    conn = http.client.HTTPConnection(door.HOST, d.ext_port, timeout=10)
    headers = {"Host": f"{door.HOST}:{d.ext_port}"}
    if origin is not None:
        headers["Origin"] = origin
    if token is not None:
        headers[door.EXT_TOKEN_HEADER] = token
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
    if data is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=headers)
    r = conn.getresponse()
    got = r.read()
    conn.close()
    return r.status, (json.loads(got.decode("utf-8")) if got else None)


def _pair_asked(d, origin=ORIGIN, version="1.0.0"):
    status, got = _ask(d, "POST", "/v1/pair", {"version": version}, origin=origin)
    assert status == 200, got
    return got


def _claim(d, pair_id, origin=None):
    return _ask(d, "GET", "/v1/pair/" + pair_id, origin=origin)     # (Chrome's GET carries no Origin)


def _cues(resources, lang, name):
    subs = pysrt.open(os.path.join(resources, lang, name), encoding="utf-8")
    return [[s.start.ordinal / 1000, s.end.ordinal / 1000, s.text] for s in subs[:3]]


# --- still off ----------------------------------------------------------------------------------------------------- #
def test_the_door_class_stays_off_so_nothing_pairs_until_ukai_ships():
    """Sonic's condition (U12): Ukai 1.0 and Surasura's half ship in one go, so the pairing lands switched off."""
    assert door.EXTENSION_ON is False


def _start_door_with(monkeypatch, on):
    """`shell.start_door` with a stand-in window and door.start recorded -> (the extension it was handed, asked)."""
    from app.qt import shell
    from app.services import journey_door
    monkeypatch.setattr(door, "EXTENSION_ON", on)
    monkeypatch.setattr(journey_door, "enabled", lambda: True)
    started, built = [], []
    monkeypatch.setattr(door, "start", lambda routes, folder, on_error=None, extension=None: started.append(extension))

    class Window:
        def door_routes(self):
            return {}

        def ukai_extension(self):
            built.append(True)
            return "ukai's class"

    shell.start_door(Window()).join(10)
    return started, built


def test_while_off_the_window_hands_the_door_no_ukai_class_and_builds_no_pairing(monkeypatch):
    started, built = _start_door_with(monkeypatch, False)
    assert started == [None] and built == [], "off: no pairing made, no card possible, nothing on 27631"


def test_once_on_the_window_hands_the_door_ukais_class_with_its_pairing(monkeypatch):
    started, built = _start_door_with(monkeypatch, True)
    assert started == ["ukai's class"] and built == [True]


# --- one Allow ----------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang, name", [("ja", "phrases_sample.srt"), ("zh", "night_market.srt")])
def test_it_pairs_in_one_allow_and_the_token_then_opens_the_paired_routes(ukai, test_resources_dir, lang, name):
    asked = _pair_asked(ukai)
    assert set(asked) == {"ok", "pair", "code", "wait_s"} and len(asked["code"]) == 4 and asked["code"].isdigit()
    [card] = ukai.asked
    assert (card.id, card.code, card.origin, card.ext_id, card.version) == (asked["pair"], asked["code"], ORIGIN, ID,
                                                                             "1.0.0")
    assert _claim(ukai, asked["pair"]) == (200, {"ok": True, "state": "waiting"}), "no token before the Allow"
    assert ukai.pairing.answer(card.id, True) is True
    status, got = _claim(ukai, asked["pair"])
    assert status == 200 and got["state"] == "allowed" and len(got["token"]) >= 32
    cues = _cues(test_resources_dir, lang, name)
    assert _ask(ukai, "POST", "/v1/echo", {"cues": cues}, token=got["token"]) == (
        200, {"ok": True, "echo": {"cues": cues}})


def test_the_token_is_handed_over_once_and_a_replayed_claim_gets_nothing(ukai):
    asked = _pair_asked(ukai)
    ukai.pairing.answer(asked["pair"], True)
    assert _claim(ukai, asked["pair"])[1]["state"] == "allowed"
    status, got = _claim(ukai, asked["pair"])
    assert status == 404 and got["kind"] == "gone" and "token" not in got


def test_another_extension_claiming_the_pairing_gets_nothing_and_the_asker_still_can(ukai):
    asked = _pair_asked(ukai)
    ukai.pairing.answer(asked["pair"], True)
    status, got = _claim(ukai, asked["pair"], origin=OTHER)
    assert status == 403 and "token" not in got
    assert _claim(ukai, asked["pair"], origin=ORIGIN)[1]["state"] == "allowed", "its own Origin, when it sends one"


def test_a_guessed_or_malformed_id_gets_nothing(ukai):
    asked = _pair_asked(ukai)
    ukai.pairing.answer(asked["pair"], True)
    wrong = ("A" if asked["pair"][0] != "A" else "B") + asked["pair"][1:]
    assert _claim(ukai, wrong)[0] == 404
    assert _claim(ukai, asked["pair"][:-1])[0] == 404, "not an id's shape: no such route"
    assert not ukai.file.exists()


@pytest.mark.parametrize("origin", [None, "https://www.netflix.com", "null", "chrome-extension://",
                                    "chrome-extension://KBMFPNGJJGDLLNEEIGPGJIFPGOCMFGMB",
                                    "chrome-extension://kbmfpngjjgdllneeigpgjifpgocmfgm",
                                    "chrome-extension://kbmfpngjjgdllneeigpgjifpgocmfgmb/",
                                    "moz-extension://kbmfpngjjgdllneeigpgjifpgocmfgmb"])
def test_only_an_extensions_own_origin_may_ask_to_pair(ukai, origin):
    status, got = _ask(ukai, "POST", "/v1/pair", {"version": "1.0.0"}, origin=origin)
    assert status == 403 and ukai.asked == [], origin


@pytest.mark.parametrize("version", ["１．０", "1.0.0; rm -rf", "x" * 33, 1, None])
def test_a_version_that_isnt_one_is_refused_before_any_card(ukai, version):
    status, got = _ask(ukai, "POST", "/v1/pair", {"version": version})
    assert status == 400 and ukai.asked == []


def test_a_version_left_out_still_pairs(ukai):
    status, got = _ask(ukai, "POST", "/v1/pair", {})
    assert status == 200 and ukai.asked[0].version == ""


def test_not_now_is_said_once_and_nothing_is_paired(ukai):
    asked = _pair_asked(ukai)
    assert ukai.pairing.answer(asked["pair"], False) is True
    assert _claim(ukai, asked["pair"]) == (200, {"ok": True, "state": "denied"})
    assert _claim(ukai, asked["pair"])[0] == 404
    assert ukai.pairing.pairing() is None and not ukai.file.exists()


def test_one_card_at_a_time_for_the_same_ukai_and_another_waits(ukai):
    """Ukai asking in a loop opens one card; a second extension can't stack a card over it."""
    first = _pair_asked(ukai)
    assert _pair_asked(ukai) == first and len(ukai.asked) == 1, "the same id and code, no second card"
    status, got = _ask(ukai, "POST", "/v1/pair", {"version": "1.0.0"}, origin=OTHER)
    assert status == 409 and got["kind"] == "busy" and len(ukai.asked) == 1
    ukai.pairing.answer(first["pair"], False)
    _claim(ukai, first["pair"])
    assert _pair_asked(ukai, origin=OTHER)["pair"] != first["pair"], "once answered and read, the next may ask"


def test_a_card_left_unanswered_lets_go_and_a_late_allow_pairs_nothing(ukai):
    asked = _pair_asked(ukai)
    ukai.clock.now += up.WAIT_S + 1
    assert _claim(ukai, asked["pair"])[0] == 404
    assert ukai.pairing.answer(asked["pair"], True) is False
    assert ukai.pairing.pairing() is None


def test_ukai_asking_again_after_the_allow_keeps_the_allow(ukai):
    """Review S-1: a retried POST between the learner's Allow and Ukai's GET is the same pairing, never a second
    card that throws the Allow away."""
    asked = _pair_asked(ukai)
    ukai.pairing.answer(asked["pair"], True)
    assert _pair_asked(ukai) == asked and len(ukai.asked) == 1
    assert _claim(ukai, asked["pair"])[1]["state"] == "allowed"


def test_ukai_asking_again_after_not_now_opens_a_new_card(ukai):
    """The learner pressed *Pair* in Ukai's menu again: a fresh card, a fresh code."""
    first = _pair_asked(ukai)
    ukai.pairing.answer(first["pair"], False)
    second = _pair_asked(ukai)
    assert second["pair"] != first["pair"] and len(ukai.asked) == 2


def test_an_answer_given_twice_counts_once(ukai):
    asked = _pair_asked(ukai)
    assert ukai.pairing.answer(asked["pair"], False) is True
    assert ukai.pairing.answer(asked["pair"], True) is False, "a Not now isn't turned into an Allow"
    assert _claim(ukai, asked["pair"])[1]["state"] == "denied"


def test_an_allow_nobody_claims_in_time_writes_no_token(ukai):
    asked = _pair_asked(ukai)
    ukai.clock.now += up.WAIT_S - 1                      # (a card open nearly the whole wait is still answered)
    assert ukai.pairing.answer(asked["pair"], True) is True
    ukai.clock.now += up.CLAIM_S + 1
    assert _claim(ukai, asked["pair"])[0] == 404 and not ukai.file.exists()


def test_a_card_the_window_couldnt_open_leaves_no_pairing_waiting(tmp_path):
    def broken(_request):
        raise RuntimeError("the window is gone")

    pairing = up.Pairing(broken, where=str(tmp_path / up.FILE))
    call = _Call({"Origin": ORIGIN}, {"version": "1.0.0"})
    with pytest.raises(RuntimeError):
        pairing.ask(call)
    assert pairing._pending is None, "the next ask opens a card again"


class _Call:
    def __init__(self, headers, body, groups=()):
        self.headers, self._body, self.groups = headers, body, groups

    def json(self, limit=None):
        return self._body


# --- the pairing file ---------------------------------------------------------------------------------------------- #
def _paired(d, origin=ORIGIN):
    asked = _pair_asked(d, origin=origin)
    d.pairing.answer(asked["pair"], True)
    return _claim(d, asked["pair"])[1]["token"]


def test_the_pairing_file_holds_the_token_origin_and_version_and_outlives_the_window(ukai):
    token = _paired(ukai)
    kept = json.loads(ukai.file.read_text(encoding="utf-8"))
    assert kept["token"] == token and kept["origin"] == ORIGIN and kept["version"] == "1.0.0" and kept["at"] > 0
    again = up.Pairing(None, where=str(ukai.file))
    assert again.pairing() == (ORIGIN, token), "the next start is still paired"
    assert not [n for n in os.listdir(ukai.file.parent) if n.endswith(".part")]


def test_the_pairing_file_is_a_part_that_stays_and_a_secret_send_report_leaves_out():
    from fnmatch import fnmatch
    from app import path_utils, report
    [row] = [r for r in path_utils.PARTS if fnmatch(up.FILE, r[1])]
    assert row[0] == "roaming" and row[3] == path_utils.STAYS, "Start over keeps the browser's Ukai paired"
    assert any(fnmatch(up.FILE, pattern) for pattern in report.SECRET_NAMES)


@pytest.mark.parametrize("text", ["", "{", "[]", json.dumps({"origin": "https://www.netflix.com", "token": "t" * 32}),
                                  json.dumps({"origin": ORIGIN, "token": "short"}),
                                  json.dumps({"origin": ORIGIN}), json.dumps({"token": "x" * 32}),
                                  # a token no answer could carry: a lone surrogate (the door's compare would raise
                                  # on it: review F-2), one of another shape
                                  '{"origin": "%s", "token": "%s"}' % (ORIGIN, "\\ud800" * 32),
                                  json.dumps({"origin": ORIGIN, "token": "ことば" * 11}),
                                  json.dumps({"origin": ORIGIN, "token": "x" * 33})])
def test_a_pairing_file_that_isnt_one_is_no_pairing(tmp_path, text):
    where = tmp_path / up.FILE
    where.write_text(text, encoding="utf-8")
    assert up.Pairing(None, where=str(where)).pairing() is None


def test_a_pairing_file_held_for_a_moment_is_read_again_at_the_next_call(tmp_path, monkeypatch):
    """Review S-5: a read that fails while another program holds the file (an antivirus scan) is no 'unpaired' for
    the whole session."""
    where = tmp_path / up.FILE
    where.write_text(json.dumps({"origin": ORIGIN, "token": "k" * 32, "version": "1.0.0", "at": 1}), encoding="utf-8")
    real, held = up._read, [True]

    def read(path):
        if held and held.pop():
            raise PermissionError(13, "held by another program")
        return real(path)

    monkeypatch.setattr(up, "_read", read)
    pairing = up.Pairing(None, where=str(where))
    assert pairing.pairing() is None
    assert pairing.pairing() == (ORIGIN, "k" * 32)


def test_the_token_is_never_written_into_settings_or_a_log(ukai, tmp_path):
    token = _paired(ukai)
    holders = []
    for where, _dirs, files in os.walk(tmp_path):
        for name in files:
            with open(os.path.join(where, name), "rb") as f:
                if token.encode("ascii") in f.read():
                    holders.append(name)
    assert holders == [up.FILE]
    root = os.environ.get("SURASURA_TEST_ROOT")
    if root:
        for where, _dirs, files in os.walk(root):
            for name in files:
                if name.endswith((".json", ".log", ".txt", ".jsonl")):
                    with open(os.path.join(where, name), "rb") as f:
                        assert token.encode("ascii") not in f.read(), name


def test_a_disk_that_wont_take_the_file_hands_no_token_leaves_no_copy_and_the_next_claim_tries_again(ukai):
    """The file's place taken by a folder: the real write fails at its replace. No token goes out, the part file
    holding it goes, the door logs nothing (its log line would name the pairing's id: review Sec-3), and once the
    place is free the same claim pairs."""
    asked = _pair_asked(ukai)
    ukai.pairing.answer(asked["pair"], True)
    ukai.file.mkdir(parents=True)
    status, got = _claim(ukai, asked["pair"])
    assert (status, got["kind"]) == (503, "busy") and "token" not in got and ukai.pairing.pairing() is None
    assert os.listdir(ukai.file.parent) == [up.FILE] and ukai.errors == []
    ukai.file.rmdir()
    assert _claim(ukai, asked["pair"])[1]["state"] == "allowed"
    assert not [n for n in os.listdir(ukai.file.parent) if n.endswith(".part")]


def test_forget_that_cant_remove_the_file_still_unpairs_this_session_and_says_so(ukai, monkeypatch):
    token = _paired(ukai)
    real = os.remove

    def held(path):
        if path.endswith(up.FILE):
            raise PermissionError(13, "held by another program")
        return real(path)

    monkeypatch.setattr(up.os, "remove", held)
    with pytest.raises(PermissionError):
        ukai.pairing.forget()
    assert _ask(ukai, "POST", "/v1/echo", {"n": 1}, token=token)[0] == 401


def test_forget_takes_a_part_file_left_by_a_crash_too(ukai):
    """A crash between the part's write and its replace leaves the token in `<file>.part`."""
    _paired(ukai)
    part = str(ukai.file) + ".part"
    with open(part, "w", encoding="utf-8") as f:
        f.write("{}")
    ukai.pairing.forget()
    assert os.listdir(ukai.file.parent) == []


# --- Forget, and a new pairing --------------------------------------------------------------------------------------- #
def test_forget_refuses_the_very_next_call_and_the_file_goes(ukai):
    token = _paired(ukai)
    assert _ask(ukai, "POST", "/v1/echo", {"n": 1}, token=token)[0] == 200
    ukai.pairing.forget()
    assert _ask(ukai, "POST", "/v1/echo", {"n": 2}, token=token)[0] == 401
    assert not ukai.file.exists() and ukai.pairing.pairing() is None
    assert ukai.echoed == [{"n": 1}]
    ukai.pairing.forget()                                # (twice: nothing to do, no error)


def test_forget_drops_an_allow_still_waiting_for_its_claim(ukai):
    asked = _pair_asked(ukai)
    ukai.pairing.answer(asked["pair"], True)
    ukai.pairing.forget()
    assert _claim(ukai, asked["pair"])[0] == 404 and not ukai.file.exists()


def test_a_new_allow_replaces_the_pairing_and_the_old_token_is_refused(ukai):
    old = _paired(ukai)
    asked = _pair_asked(ukai, origin=OTHER)
    assert ukai.asked[-1].replaces is True, "the card says it replaces the paired Ukai"
    assert _ask(ukai, "POST", "/v1/echo", {"n": 1}, token=old)[0] == 200, "until the new one is claimed"
    ukai.pairing.answer(asked["pair"], True)
    new = _claim(ukai, asked["pair"], origin=OTHER)[1]["token"]
    assert new != old
    assert _ask(ukai, "POST", "/v1/echo", {"n": 2}, token=old)[0] == 401
    assert _ask(ukai, "POST", "/v1/echo", {"n": 3}, token=new, origin=OTHER)[0] == 200
    assert _ask(ukai, "POST", "/v1/echo", {"n": 4}, token=new, origin=ORIGIN)[0] == 403, "its token, another's Origin"


def test_the_pairing_routes_never_answer_a_token_to_a_paired_call_without_one(ukai):
    """The two pairing routes are open (no token); every other route still needs the pairing."""
    _paired(ukai)
    assert _ask(ukai, "POST", "/v1/echo", {"n": 1})[0] == 401


def test_two_ukais_asking_at_once_open_one_card(ukai):
    answers = []

    def asks(origin):
        answers.append(_ask(ukai, "POST", "/v1/pair", {"version": "1.0.0"}, origin=origin)[0])

    threads = [threading.Thread(target=asks, args=(o,)) for o in (ORIGIN, OTHER, ORIGIN, OTHER)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(ukai.asked) == 1 and sorted(answers) == [200, 200, 409, 409]


# --- the card's words ---------------------------------------------------------------------------------------------- #
def test_a_store_id_is_named_and_any_other_id_gets_a_warning(ukai, monkeypatch):
    from app.qt import strings, ukai_allow
    monkeypatch.setitem(up.STORE_IDS, ID, "Chrome Web Store")
    _pair_asked(ukai)
    listed = ukai_allow.words(ukai.asked[-1])
    assert "Chrome Web Store" in listed and ukai.asked[-1].code in listed and "⚠" not in listed
    ukai.pairing.answer(ukai.asked[-1].id, False)
    _claim(ukai, ukai.asked[-1].id)
    _pair_asked(ukai, origin=OTHER)
    unlisted = ukai_allow.words(ukai.asked[-1])
    assert "⚠" in unlisted and OTHER.split("//")[1] in unlisted and strings.UKAI_ALLOW_REPLACES not in unlisted


# --- UKAI-S2: what Settings' row reads, and the module's routes on the window's class ---------------------------- #
def test_changed_is_told_after_a_claim_and_after_a_forget_even_one_that_cant_remove_the_file(tmp_path, monkeypatch):
    """Settings' Ukai row paints again from `changed` (the bridge's `ukai_changed`): at the claim that pairs, and at
    every forget — one whose file is held too (this session is unpaired all the same)."""
    told = []
    pairing = up.Pairing(lambda request: None, where=str(tmp_path / up.FILE), changed=lambda: told.append(1))
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    monkeypatch.setattr(door, "EXT_PORT", _free_port())
    d = door.Door({}, str(tmp_path / "results"), extension=pairing.extension()).start()
    try:
        d.pairing = pairing
        asked = _pair_asked(d)
        assert told == [], "asking is not pairing"
        pairing.answer(asked["pair"], True)
        assert told == [], "an Allow nobody claimed yet is not paired"
        assert _claim(d, asked["pair"])[0] == 200 and told == [1]
    finally:
        d.stop()
    pairing.forget()
    assert told == [1, 1]
    real = os.remove
    monkeypatch.setattr(up.os, "remove", lambda p: (_ for _ in ()).throw(PermissionError(13, "held"))
                        if p.endswith(up.FILE) else real(p))
    (tmp_path / up.FILE).write_text(json.dumps({"origin": ORIGIN, "token": "T" * 32}), encoding="utf-8")
    with pytest.raises(PermissionError):
        pairing.forget()
    assert told == [1, 1, 1]


def test_a_changed_that_raises_never_fails_the_pairing(ukai):
    ukai.pairing._changed = lambda: 1 / 0
    token = _paired(ukai)
    assert _ask(ukai, "POST", "/v1/echo", {"n": 1}, token=token)[0] == 200
    ukai.pairing.forget()
    assert ukai.pairing.pairing() is None


def test_paired_says_who_and_which_version_never_the_token(ukai):
    assert ukai.pairing.paired() is None
    token = _paired(ukai)
    got = ukai.pairing.paired()
    assert got == {"origin": ORIGIN, "version": "1.0.0"} and token not in json.dumps(got)


class _Bridge:
    def __init__(self):
        self.connected = []
        self.ukai_asked = type("S", (), {"connect": lambda _s, slot, *a: self.connected.append(slot)})()

    def ask_ukai(self, request):
        pass

    def ukai_changed(self):
        pass


def _window():
    from types import SimpleNamespace
    services = SimpleNamespace(writer=None, settings=SimpleNamespace(get=lambda: {"covers_download": False}))
    return SimpleNamespace(services=services, bridge=_Bridge(), _ukai_allow=lambda request: None)


def test_without_ukais_module_the_window_builds_no_class_and_nothing_listens(monkeypatch):
    """CLAUDE.md §2's module rule: `modules/ukai` gone, the window hands the door no Ukai class (None) and builds
    no pairing — Surasura runs as before."""
    import sys
    from app.qt.shell import ShellWindow
    monkeypatch.setitem(sys.modules, "modules.ukai", None)          # (an import of it raises ImportError)
    window = _window()
    assert ShellWindow.ukai_extension(window) is None
    assert not hasattr(window, "ukai_pairing") and window.bridge.connected == []


def test_with_ukais_module_the_class_carries_its_subtitle_route_behind_the_pairing(monkeypatch):
    from app.qt.shell import ShellWindow
    window = _window()
    ext = ShellWindow.ukai_extension(window)
    assert isinstance(ext, door.Extension) and isinstance(window.ukai_pairing, up.Pairing)
    fn, _groups, unpaired = ext.route("POST", "/v1/online-subtitle")
    assert unpaired is False, "the subtitle route is a paired one"
    hello, _g, open_ = ext.route("GET", "/v1/hello")
    assert open_ is True and "languages" in hello(None)

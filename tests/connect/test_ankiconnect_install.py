"""*Install AnkiConnect for me* (3.0.1, spec §10): `app/connect/ankiconnect_install.py` — Anki's folder and version, the
look, and the install route that writes into another program's folder (full tests, and mutants on the write path).

Every test runs on a throwaway Anki base folder (`ANKI_BASE` in a temp dir, a `prefs21.db` made the way Anki makes it:
a `profiles` table, the `_global` row a pickled dict) and never the real AnkiWeb: `_fetch`, the one network function,
is replaced by a stand-in that hands out an add-on built here the way AnkiWeb's 2026-10 AnkiConnect is laid out (the
probe: a 303 to `/svc/shared/download-addon/2055492159?t=…&minpt=…&maxpt=…&bidx=…`, a zip with `__init__.py`,
`manifest.json`, `config.json` at its root). `open_anki.running` is faked; the waits use a fake clock and sleep."""
import hashlib
import http.client
import io
import json
import os
import pickle
import sqlite3
import stat
import threading
import types
import urllib.error
import urllib.request
import zipfile

import pytest

from app.connect import ankiconnect_install as I
from app.connect import open_anki

POINT = 260902                                         # Anki 26.9.2, as the probe's prefs21.db held it
FINAL = ("https://ankiweb.net/svc/shared/download-addon/2055492159?t=1792032779&minpt=260800&maxpt=260800"
         "&bidx=2")
URL = "https://ankiweb.net/shared/download/2055492159?v=2.1&p=260902"
MANIFEST = {"package": "2055492159", "name": "Anki-Connect", "conflicts": ["AnkiConnectDev"]}
# the meta.json Anki itself writes for this download (the probe's fields: name from the add-on's own manifest,
# AnkiWeb's t / minpt / maxpt / bidx, on, conflicts, updated by Anki)
META = {"name": "Anki-Connect", "mod": 1792032779, "min_point_version": 260800, "max_point_version": 260800,
        "branch_index": 2, "disabled": False, "conflicts": ["AnkiConnectDev"], "update_enabled": True}
FILES = {
    "__init__.py": "# AnkiConnect\nimport aqt\n\nrequired_anki_version = (26, 8, 0)\n",
    "config.json": json.dumps({"apiKey": None, "webBindAddress": "127.0.0.1", "webBindPort": 8765}, indent=4),
    "config.md": "AnkiConnect の設定 — webBindPort: 8765\r\n",     # CRLF and Japanese: bytes kept as they came
    "manifest.json": json.dumps(MANIFEST, indent=4),
    "web.py": "# the web server\n",
}


def _zip(files=None, links=(), extra=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in (FILES if files is None else files).items():
            z.writestr(name, text)
        for name in links:                             # a symlink entry (unix mode lnk)
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "../../outside")
        for name, text in extra:
            z.writestr(zipfile.ZipInfo(name), text)
    return buf.getvalue()


class Response:
    """`_fetch`'s answer: read in chunks, its final address, its headers."""

    def __init__(self, body, final=FINAL, length=True, fail_at=None):
        self.body, self.final, self.pos = body, final, 0
        self.headers = {"Content-Length": str(len(body))} if length else {}
        self.fail_at = fail_at

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def geturl(self):
        return self.final

    def read(self, n=-1):
        if self.fail_at is not None and self.pos >= self.fail_at:
            raise self.fail_with
        chunk = self.body[self.pos:self.pos + (n if n and n > 0 else len(self.body))]
        self.pos += len(chunk)
        return chunk


class Net:
    """The stand-in for `_fetch`: every URL asked, one answer (or an exception) per call."""

    def __init__(self, answer=None):
        self.asked = []
        self.answer = answer if answer is not None else (lambda: Response(_zip()))

    def __call__(self, url):
        self.asked.append(url)
        got = self.answer()
        if isinstance(got, BaseException):
            raise got
        return got


def _prefs(base, meta):
    db = sqlite3.connect(os.path.join(base, "prefs21.db"))
    db.execute("create table if not exists profiles (name text primary key collate nocase, data blob not null)")
    db.execute("insert or replace into profiles values ('_global', ?)", (pickle.dumps(meta, protocol=4),))
    db.execute("insert or replace into profiles values ('DevTest', ?)", (pickle.dumps({"syncKey": None}, 4),))
    db.commit()
    db.close()


def _tree(folder):
    """Every file under `folder` -> its sha256 (the bytes, names relative)."""
    out = {}
    for root, _dirs, names in os.walk(folder):
        for name in names:
            path = os.path.join(root, name)
            with open(path, "rb") as f:
                out[os.path.relpath(path, folder)] = hashlib.sha256(f.read()).hexdigest()
    return out


@pytest.fixture
def anki(tmp_path, monkeypatch):
    """A throwaway Anki base that has run once (Anki 26.9.2), with another add-on in it; Windows; Anki closed."""
    base = tmp_path / "Anki2"
    (base / "addons21" / "1344485230").mkdir(parents=True)
    (base / "addons21" / "1344485230" / "__init__.py").write_text("# AJT Japanese\n", encoding="utf-8")
    (base / "addons21" / "1344485230" / "meta.json").write_text(
        json.dumps({"name": "AJT Japanese", "mod": 1786108069, "disabled": True}), encoding="utf-8")
    (base / "User 1").mkdir()
    (base / "User 1" / "collection.anki2").write_bytes(b"SQLite format 3\x00 the learner's collection")
    _prefs(str(base), {"ver": 1, "firstRun": False, "defaultLang": "ja_JP", "last_run_version": POINT,
                       "last_loaded_profile_name": "User 1", "answer_keys": {1: "1"}, "updates": True})
    monkeypatch.setenv("ANKI_BASE", str(base))
    monkeypatch.setattr(I, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setattr(I, "DOWNLOAD_ENABLED", True)
    state = {"running": [False]}

    def running():
        seq = state["running"]
        return seq.pop(0) if len(seq) > 1 else seq[0]
    monkeypatch.setattr(open_anki, "running", running)
    net = Net()
    monkeypatch.setattr(I, "_fetch", net)
    return types.SimpleNamespace(base=str(base), addons=str(base / "addons21"), net=net, state=state,
                                 others=_tree(str(base / "addons21" / "1344485230")),
                                 collection=_tree(str(base / "User 1")))


class Clock:
    def __init__(self):
        self.now, self.slept = 0.0, []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def _install(**kw):
    clock = kw.pop("clock", None) or Clock()
    kw.setdefault("confirm", lambda: True)
    ended = []
    result = I.install(kw.pop("on_progress", None), kw.pop("cancel", None), ended.append, clock=clock,
                       sleep=kw.pop("sleep", clock.sleep), **kw)
    assert ended == [result]                           # told once, at the end
    return result


def _untouched(anki, placed=False):
    """Nothing of Anki's but (when `placed`) the one new folder changed; both staging folders gone."""
    assert _tree(os.path.join(anki.addons, "1344485230")) == anki.others
    assert _tree(os.path.join(anki.base, "User 1")) == anki.collection
    assert not os.path.exists(os.path.join(anki.base, I.ANKI_STAGING))
    assert not os.path.exists(I.staging_folder()) or not os.listdir(I.staging_folder())
    assert sorted(os.listdir(anki.addons)) == sorted(["1344485230"] + ([I.CODE] if placed else []))


# --------------------------------------------------------------------------- #
# Anki's folder and version
# --------------------------------------------------------------------------- #
def test_anki_base_wins_and_a_folder_anki_never_ran_in_is_no_base(anki, tmp_path, monkeypatch):
    assert I.base() == anki.base
    os.remove(os.path.join(anki.base, "prefs21.db"))   # installed, never run: no prefs21.db
    assert I.base() is None
    assert I.look()["state"] == I.NO_BASE


def test_appdata_anki2_is_the_base_without_anki_base_and_never_under_a_test_root_unless_asked(anki, tmp_path,
                                                                                              monkeypatch):
    appdata = tmp_path / "Roaming"
    (appdata / "Anki2" / "addons21").mkdir(parents=True)
    _prefs(str(appdata / "Anki2"), {"last_run_version": 66})
    monkeypatch.delenv("ANKI_BASE")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path / "root"))
    assert I.base() is None                            # a test never reads %APPDATA%'s Anki by itself
    monkeypatch.setattr(I, "APPDATA_UNDER_TESTS", True)
    assert I.base() == str(appdata / "Anki2")
    assert I.anki_version(I.base()) == 66              # a 2.1.x Anki: its point version is the last number
    # a -b portable Anki: %APPDATA%\Anki2 unused (no prefs21.db) -> no base, only Copy code
    os.remove(str(appdata / "Anki2" / "prefs21.db"))
    assert I.base() is None


def test_the_version_is_the_one_anki_saved_and_a_pickle_with_anything_but_plain_values_is_refused(anki):
    assert I.anki_version(anki.base) == POINT
    ran = []

    class Evil:                                        # a pickle that would run code as it loads
        def __reduce__(self):
            return (ran.append, ("code ran",))
    _prefs(anki.base, {"last_run_version": POINT, "x": Evil()})
    assert I.anki_version(anki.base) is None and ran == []
    assert I.look()["state"] == I.NO_VERSION
    for meta in ({}, {"last_run_version": True}, {"last_run_version": "260902"}, {"last_run_version": 0}, [1, 2]):
        _prefs(anki.base, meta)
        assert I.anki_version(anki.base) is None, meta


def test_a_prefs_file_that_isnt_sqlite_or_has_no_global_row_is_no_version(anki):
    with open(os.path.join(anki.base, "prefs21.db"), "wb") as f:
        f.write(b"not a database")
    assert I.anki_version(anki.base) is None
    os.remove(os.path.join(anki.base, "prefs21.db"))
    db = sqlite3.connect(os.path.join(anki.base, "prefs21.db"))
    db.execute("create table profiles (name text, data blob)")
    db.commit()
    db.close()
    assert I.anki_version(anki.base) is None


# --------------------------------------------------------------------------- #
# The look
# --------------------------------------------------------------------------- #
def test_the_look_offers_the_install_and_changes_nothing(anki):
    before = _tree(anki.base)
    found = I.look()
    assert found["state"] == I.CAN_INSTALL and found["point"] == POINT and found["base"] == anki.base
    assert _tree(anki.base) == before and anki.net.asked == []


def test_ankiconnects_own_folder_or_any_add_on_naming_it_is_there_and_turned_off_is_said(anki):
    own = os.path.join(anki.addons, I.CODE)
    os.mkdir(own)
    assert I.look()["state"] == I.THERE
    os.rmdir(own)
    other = os.path.join(anki.addons, "anki-connect-dev")         # a hand-made copy under another name
    os.mkdir(other)
    with open(os.path.join(other, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"package": "anki-connect-dev", "name": "Anki-Connect (dev)"}, f)
    with open(os.path.join(other, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "Anki-Connect (dev)", "disabled": True}, f)
    found = I.look()
    assert found["state"] == I.THERE and found["disabled"] is True
    os.remove(os.path.join(other, "meta.json"))
    os.remove(os.path.join(other, "manifest.json"))
    os.rename(other, os.path.join(anki.addons, "12345"))
    with open(os.path.join(anki.addons, "12345", "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "AnkiConnect", "disabled": False}, f)
    assert I.look() == dict(I.look(), state=I.THERE, disabled=False)


def test_the_look_is_off_with_the_switch_off_and_elsewhere_than_windows(anki, monkeypatch):
    monkeypatch.setattr(I, "DOWNLOAD_ENABLED", False)
    assert I.look()["state"] == I.OFF
    monkeypatch.setattr(I, "DOWNLOAD_ENABLED", True)
    monkeypatch.setattr(I, "sys", types.SimpleNamespace(platform="darwin"))
    assert I.look()["state"] == I.NOT_WINDOWS


# --------------------------------------------------------------------------- #
# The install
# --------------------------------------------------------------------------- #
def test_the_install_places_one_new_folder_anki_reads_as_its_own_ankiweb_install(anki):
    progress = []
    assert _install(on_progress=lambda d, t: progress.append((d, t))) == I.INSTALLED
    assert anki.net.asked == [URL]                     # one request, Anki's own
    placed = os.path.join(anki.addons, I.CODE)
    for name, text in FILES.items():
        with open(os.path.join(placed, name), "rb") as f:
            assert f.read() == text.encode("utf-8"), name
    with open(os.path.join(placed, "meta.json"), encoding="utf-8") as f:
        assert json.load(f) == META
    assert sorted(os.listdir(placed)) == sorted(list(FILES) + ["meta.json"])
    assert progress and progress[-1][0] == progress[-1][1]
    _untouched(anki, placed=True)
    assert I.look()["state"] == I.THERE                # the next look: no button


def test_without_a_yes_or_with_the_switch_off_nothing_is_fetched_or_written(anki, monkeypatch):
    before = _tree(anki.base)
    assert _install(confirm=None) == I.DECLINED
    assert _install(confirm=lambda: False) == I.DECLINED
    monkeypatch.setattr(I, "DOWNLOAD_ENABLED", False)
    assert _install() == I.OFF
    monkeypatch.setattr(I, "DOWNLOAD_ENABLED", True)
    monkeypatch.setattr(I, "sys", types.SimpleNamespace(platform="linux"))
    assert _install() == I.OFF
    assert anki.net.asked == [] and _tree(anki.base) == before


def test_fetch_itself_refuses_with_the_switch_off(monkeypatch):
    monkeypatch.setattr(I, "DOWNLOAD_ENABLED", False)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: pytest.fail("an opener was built"))
    with pytest.raises(I._Refused):
        I._fetch(URL)


def test_anki_open_waits_while_shown_and_cancel_ends_it_with_nothing_fetched(anki):
    anki.state["running"] = [True]
    cancel = threading.Event()
    phases = []
    clock = Clock()

    def sleep(s):
        clock.sleep(s)
        if len(clock.slept) == 3:
            cancel.set()                               # the learner's Cancel while it waits
    assert _install(cancel=cancel, clock=clock, sleep=sleep, on_phase=phases.append) == I.CANCELLED
    assert phases == [I.WAITING] and set(clock.slept) == {I.WAIT_EVERY}
    assert anki.net.asked == []
    _untouched(anki)


def test_the_process_list_is_looked_at_only_while_the_waiting_line_is_on_screen(anki, monkeypatch):
    looks = []
    shown = {"now": False}
    clock = Clock()

    def running():
        looks.append(clock.now)
        return clock.now < 10
    monkeypatch.setattr(open_anki, "running", running)

    def sleep(s):
        clock.sleep(s)
        shown["now"] = clock.now >= 6                  # the line comes on screen at 6 s
    assert _install(clock=clock, sleep=sleep, shown=lambda: shown["now"]) == I.INSTALLED
    # the first look at once (the press was just made on screen), then none while hidden; the last is the check
    # before the rename
    assert looks[0] == 0 and min(looks[1:-1]) >= 6


def test_ten_minutes_of_anki_open_ends_it_with_nothing_fetched(anki):
    assert (I.WAIT_EVERY, I.WAIT_FOR) == (2.0, 600.0)  # AC-3 A: every 2 s, 10 minutes at most
    anki.state["running"] = [True]
    clock = Clock()
    assert _install(clock=clock) == I.STAYED_OPEN
    assert clock.now >= I.WAIT_FOR and clock.now < I.WAIT_FOR + 2 * I.WAIT_EVERY
    assert anki.net.asked == []
    _untouched(anki)
    assert I.said(I.STAYED_OPEN) == I.STAYED_OPEN_LINE


def test_a_process_list_that_cant_tell_never_writes_blind(anki):
    anki.state["running"] = [None]
    assert _install() == I.CANT_TELL
    assert anki.net.asked == []
    _untouched(anki)


def test_anki_started_between_the_download_and_the_rename_waits_again_and_then_installs(anki):
    # closed (the first wait), then open at the check before the rename, open once more, then closed
    anki.state["running"] = [False, True, True, False]
    phases = []
    assert _install(on_phase=phases.append) == I.INSTALLED
    assert phases == [I.WAITING, I.RUNNING] and anki.net.asked == [URL]
    _untouched(anki, placed=True)


def test_a_folder_that_appears_meanwhile_is_never_replaced(anki, monkeypatch):
    hand = os.path.join(anki.addons, I.CODE)

    def fetch(url):
        os.mkdir(hand)                                 # the learner installs it by hand during the download
        with open(os.path.join(hand, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("# the learner's own copy\n")
        return Response(_zip())
    monkeypatch.setattr(I, "_fetch", fetch)
    assert _install() == I.ALREADY
    with open(os.path.join(hand, "__init__.py"), encoding="utf-8") as f:
        assert f.read() == "# the learner's own copy\n"
    assert sorted(os.listdir(hand)) == ["__init__.py"]
    _untouched(anki, placed=True)


def test_the_rename_itself_never_replaces_a_folder_that_came_in_its_last_instant(anki, monkeypatch):
    real = I._present
    calls = []

    def present(folder):                               # nothing there at the last look, one there at the rename
        calls.append(folder)
        if len(calls) == 2:
            os.mkdir(os.path.join(anki.addons, I.CODE))
            with open(os.path.join(anki.addons, I.CODE, "keep.txt"), "w") as f:
                f.write("mine")
            return None
        return real(folder)
    monkeypatch.setattr(I, "_present", present)
    assert _install() == I.ALREADY
    assert os.listdir(os.path.join(anki.addons, I.CODE)) == ["keep.txt"]
    _untouched(anki, placed=True)


@pytest.mark.parametrize("why, answer, result", [
    ("a final address off AnkiWeb", lambda: Response(_zip(), final="https://cdn.example.net/x.zip?t=1&minpt=1&"
                                                                    "maxpt=1&bidx=1"), I.REFUSED),
    ("plain http", lambda: Response(_zip(), final=FINAL.replace("https", "http")), I.REFUSED),
    ("no meta in the address", lambda: Response(_zip(), final="https://ankiweb.net/svc/shared/download-addon/2055492159"),
     I.REFUSED),
    ("a size over the cap", lambda: Response(b"x" * (I.SIZE_CAP + 1)), I.REFUSED),
    ("over the cap with no length", lambda: Response(b"x" * (I.SIZE_CAP + 1), length=False), I.REFUSED),
    ("not a zip", lambda: Response(b"<html>AnkiWeb is down</html>"), I.REFUSED),
    ("no __init__.py", lambda: Response(_zip({"web.py": "x"})), I.REFUSED),
    ("a .. entry", lambda: Response(_zip(dict(FILES, **{"../evil.py": "x"}))), I.REFUSED),
    ("an absolute entry", lambda: Response(_zip(dict(FILES, **{"/evil.py": "x"}))), I.REFUSED),
    ("a drive entry", lambda: Response(_zip(dict(FILES, **{"C:/evil.py": "x"}))), I.REFUSED),
    ("a backslash entry", lambda: Response(_zip(dict(FILES, **{"..\\evil.py": "x"}))), I.REFUSED),
    ("a link entry", lambda: Response(_zip(links=("link.py",))), I.REFUSED),
    ("too many entries", lambda: Response(_zip(dict(FILES, **{f"f{i}.py": "" for i in range(I.ENTRY_CAP)}))),
     I.REFUSED),
    ("a meta.json of its own", lambda: Response(_zip(dict(FILES, **{"meta.json": "{}"}))), I.REFUSED),
    ("offline", lambda: urllib.error.URLError("no route"), I.OFFLINE),
    ("AnkiWeb has no branch", lambda: urllib.error.HTTPError(URL, 404, "Not Found", {}, None), I.NO_BRANCH),
    ("AnkiWeb down", lambda: urllib.error.HTTPError(URL, 503, "Down", {}, None), I.OFFLINE),
    ("a redirect off AnkiWeb", lambda: urllib.error.HTTPError(URL, 303, "a redirect away from AnkiWeb", {}, None),
     I.REFUSED),
])
def test_what_doesnt_look_like_ankiconnect_is_refused_and_nothing_is_left(anki, monkeypatch, why, answer, result):
    monkeypatch.setattr(I, "_fetch", Net(answer))
    assert _install() == result, why
    _untouched(anki)
    assert I.said(result).startswith("Couldn't install it for you: ")


def test_an_unpacked_size_over_the_cap_is_refused(anki, monkeypatch):
    monkeypatch.setattr(I, "UNPACKED_CAP", 100)
    assert _install() == I.REFUSED
    _untouched(anki)


def test_windows_blocking_the_file_says_so(anki, monkeypatch):
    blocked = OSError(22, "Operation did not complete successfully because the file contains a virus")
    blocked.winerror = 225
    response = Response(_zip(), fail_at=0)
    response.fail_with = blocked
    monkeypatch.setattr(I, "_fetch", Net(lambda: response))
    assert _install() == I.BLOCKED
    _untouched(anki)
    assert I.said(I.BLOCKED) == "Couldn't install it for you: Windows blocked the file."


def test_a_leftover_staging_folder_is_left_by_the_look_and_removed_by_the_next_install(anki):
    leftover = os.path.join(anki.base, I.ANKI_STAGING, I.CODE)
    os.makedirs(leftover)                              # an install killed before its rename
    with open(os.path.join(leftover, "__init__.py"), "w") as f:
        f.write("# half")
    assert I.look()["state"] == I.CAN_INSTALL          # Anki ignores it; the look never deletes
    assert os.path.exists(leftover)
    assert _install() == I.INSTALLED
    _untouched(anki, placed=True)


def test_one_install_at_a_time(anki):
    assert I._ONE_INSTALL.acquire(blocking=False)
    try:
        assert _install() == I.BUSY
    finally:
        I._ONE_INSTALL.release()
    assert anki.net.asked == []


def test_a_confirm_or_a_route_that_raises_ends_it_without_a_write(anki, monkeypatch):
    def boom():
        raise RuntimeError("the sheet went")
    assert _install(confirm=boom) == I.NOT_WRITTEN
    monkeypatch.setattr(I, "_check_zip", lambda path: (_ for _ in ()).throw(RuntimeError("bug")))
    assert _install() == I.NOT_WRITTEN
    _untouched(anki)


# --------------------------------------------------------------------------- #
# The network function
# --------------------------------------------------------------------------- #
class Opener:
    def __init__(self):
        self.handlers, self.opened = [], []

    def __call__(self, *handlers):
        self.handlers = list(handlers)
        return self

    def open(self, request, timeout=None):
        self.opened.append((request.full_url, request.get_header("User-agent"), timeout))
        return Response(_zip())


def test_fetch_asks_only_ankiweb_over_https_with_surasuras_user_agent(monkeypatch):
    monkeypatch.setattr(I, "DOWNLOAD_ENABLED", True)
    opener = Opener()
    monkeypatch.setattr(urllib.request, "build_opener", opener)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("the default opener was used"))
    with I._fetch(URL):
        pass
    from app import update_checker
    assert opener.opened == [(URL, update_checker._USER_AGENT, I.TIMEOUT_S)]
    assert any(isinstance(h, I._AnkiWebOnly) for h in opener.handlers)
    for url in ("http://ankiweb.net/shared/download/2055492159", "https://ankiweb.net.example.com/x",
                "https://user@ankiweb.net/x", "https://ankiweb.net:8443/x", "https://evil.net/x"):
        with pytest.raises(I._Refused):
            I._fetch(url)
    assert len(opener.opened) == 1


def test_a_redirect_off_ankiweb_is_refused_by_the_handler():
    handler = I._AnkiWebOnly()
    request = urllib.request.Request(URL)
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(request, None, 303, "See Other", {}, "https://cdn.example.net/AnkiConnect.zip")
    assert handler.redirect_request(request, None, 303, "See Other", {}, FINAL) is not None


# --------------------------------------------------------------------------- #
# As a job
# --------------------------------------------------------------------------- #
class Registry:
    def __init__(self):
        self.jobs = []

    def record(self, kind, label, cancel=None, on_quit="cancel", **kw):
        job = types.SimpleNamespace(kind=kind, label=label, cancel=cancel, on_quit=on_quit, holds=[], resumed=0,
                                    steps=[], ended=None)
        job.hold = lambda reason, needs=None: job.holds.append((reason, needs))
        job.resume = lambda: setattr(job, "resumed", job.resumed + 1)
        job.progress = lambda step, done=None, total=None: job.steps.append((step, done, total))
        job.finish = lambda ok=True, message=None, cancelled=False: setattr(job, "ended", (ok, message, cancelled))
        self.jobs.append(job)
        return job


def test_the_job_is_listed_from_the_yes_waits_while_anki_is_open_and_ends_with_the_reason(anki):
    registry = Registry()
    clock = Clock()
    assert I.install_as_job(registry, None, threading.Event(), None, confirm=lambda: False, clock=clock,
                            sleep=clock.sleep) == I.DECLINED
    assert registry.jobs == []                         # nothing listed without a yes
    anki.state["running"] = [True, True, False]
    assert I.install_as_job(registry, None, threading.Event(), None, confirm=lambda: True, clock=clock,
                            sleep=clock.sleep) == I.INSTALLED
    job = registry.jobs[0]
    assert (job.kind, job.label, job.on_quit) == (I.JOB_KIND, I.JOB_LABEL, "cancel")
    assert job.holds == [(I.JOB_WAITING, I.JOB_NEEDS)] and job.resumed == 1
    assert job.steps and job.ended == (True, None, False)
    os.rename(os.path.join(anki.addons, I.CODE), os.path.join(anki.base, "away"))
    anki.net.answer = lambda: urllib.error.URLError("offline")
    assert I.install_as_job(registry, None, threading.Event(), None, confirm=lambda: True, clock=clock,
                            sleep=clock.sleep) == I.OFFLINE
    assert registry.jobs[1].ended == (False, "Couldn't install it for you: couldn't reach AnkiWeb.", False)


def test_the_jobs_cancel_sets_the_routes_cancel(anki):
    registry = Registry()
    anki.state["running"] = [True]
    cancel = threading.Event()
    clock = Clock()

    def sleep(s):
        clock.sleep(s)
        registry.jobs[0].cancel(registry.jobs[0])      # the bottom bar's Cancel
    assert I.install_as_job(registry, None, cancel, None, confirm=lambda: True, clock=clock,
                            sleep=sleep) == I.CANCELLED
    assert registry.jobs[0].ended == (False, None, True) and anki.net.asked == []


def test_the_kind_is_in_the_windows_tables():
    from app.services import jobs, phase
    assert I.JOB_KIND in jobs.RESOURCES and I.JOB_KIND in phase.KINDS


# --- the review's rows (Mado-AC register A5, A8, A9, A10) ----------------------------------------------------------- #
@pytest.mark.parametrize("name", ["CON", "aux.py", "com1.txt", "LPT9", "nul.json", "web.py.", "web.py ", "a//b.py"])
def test_windows_device_names_and_names_windows_would_change_are_refused(anki, monkeypatch, name):
    monkeypatch.setattr(I, "_fetch", Net(lambda: Response(_zip(dict(FILES, **{name: "x"})))))
    assert _install() == I.REFUSED
    _untouched(anki)


class Faulty(Response):
    """A download that breaks after its first chunk."""

    def __init__(self, fault):
        super().__init__(_zip())
        self.fault = fault

    def read(self, n=-1):
        if self.pos:
            raise self.fault
        return super().read(10)


@pytest.mark.parametrize("fault", [ConnectionResetError(10054, "reset"), TimeoutError("timed out"),
                                   http.client.IncompleteRead(b"", 10)])
def test_a_network_fault_mid_download_is_couldnt_reach_ankiweb(anki, monkeypatch, fault):
    monkeypatch.setattr(I, "_fetch", Net(lambda: Faulty(fault)))
    assert _install() == I.OFFLINE
    _untouched(anki)


def test_an_ankiweb_refusal_other_than_not_found_is_couldnt_reach_ankiweb(anki, monkeypatch):
    monkeypatch.setattr(I, "_fetch", Net(lambda: urllib.error.HTTPError(URL, 429, "Too Many Requests", {}, None)))
    assert _install() == I.OFFLINE


def test_the_unpack_refuses_a_name_outside_its_folder_by_itself(tmp_path):
    # the second layer, proven alone (the zip check is the first)
    path = tmp_path / "a.zip"
    path.write_bytes(_zip(dict(FILES, **{"../evil.py": "x"})))
    with zipfile.ZipFile(path) as z:
        files = [i for i in z.infolist() if not i.is_dir()]
    with pytest.raises(I._Refused):
        I._unpack(str(path), files, str(tmp_path / "out" / I.CODE), META)
    assert not (tmp_path / "out" / "evil.py").exists()


def test_a_file_that_isnt_what_came_is_never_placed(anki, monkeypatch):
    real = zipfile.ZipFile.read

    def read(self, name, pwd=None):
        if str(getattr(name, "filename", name)) == "web.py":
            return b"changed"
        return real(self, name, pwd)
    monkeypatch.setattr(zipfile.ZipFile, "read", read)
    assert _install() == I.NOT_WRITTEN
    _untouched(anki)


def test_a_virus_check_holding_the_new_files_is_waited_for_twice(anki, monkeypatch):
    real = os.rename
    tries = []

    def rename(a, b):
        tries.append(a)
        if len(tries) < 3:
            raise PermissionError(5, "Access is denied")
        return real(a, b)
    monkeypatch.setattr(I.os, "rename", rename)
    assert _install() == I.INSTALLED and len(tries) == 3
    _untouched(anki, placed=True)
    real(os.path.join(anki.addons, I.CODE), os.path.join(anki.base, "away"))
    tries.clear()

    def refused(a, b):
        tries.append(a)
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(I.os, "rename", refused)
    assert _install() == I.NOT_WRITTEN and len(tries) == I.RENAME_TRIES
    assert not os.path.exists(os.path.join(anki.addons, I.CODE))


def test_the_first_look_at_the_process_list_is_at_once_even_off_screen(anki, monkeypatch):
    # A1: the press was just made on screen; the gate is for the waits after it
    looks = []
    monkeypatch.setattr(open_anki, "running", lambda: looks.append(1) or False)
    assert _install(shown=lambda: False) == I.INSTALLED
    assert len(looks) == 2                             # the first wait's look, and the check before the rename


def test_the_zip_check_alone_refuses_names_outside_the_add_on(tmp_path):
    # the first layer, proven alone (the unpack's own check is the second)
    for name in ("../evil.py", "/evil.py", "a/../../evil.py"):
        path = tmp_path / "z.zip"
        path.write_bytes(_zip(dict(FILES, **{name: "x"})))
        with pytest.raises(I._Refused):
            I._check_zip(str(path))
    path.write_bytes(_zip(links=("link.py",)))
    with pytest.raises(I._Refused):
        I._check_zip(str(path))


def test_ankiconnect_already_there_is_said_at_once_even_with_anki_open(anki):
    # the drill (2026-11-06): a second install with Anki open waited 10 minutes before it looked again
    os.mkdir(os.path.join(anki.addons, I.CODE))
    anki.state["running"] = [True]
    clock = Clock()
    assert _install(clock=clock) == I.ALREADY
    assert clock.slept == [] and anki.net.asked == []

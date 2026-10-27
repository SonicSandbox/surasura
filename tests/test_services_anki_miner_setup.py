"""The setup wizard's Anki Miner page, Qt-free (`app/services/anki_miner_setup.py`; W3.5 part 3, P1.5 04 §2–3).

What a wrong answer would cost:
  * the page saying *ready* while Anki Miner can't make a card (page 5 turns Connect on only then), or naming a fix
    the user can't act on — the known-words sync is page 2's, never this page's;
  * the wizard's look writing Connect's setup record (it must look with `keep=False`);
  * a dot whose meaning is its colour alone — every tip names its state in words;
  * a download nobody asked for: `install` fetches nothing until the learner's yes (`confirm`, before any byte), and
    with `DOWNLOAD_ENABLED` off the network function is never called — the releases page opens, as 2.x's *Install*;
  * with the route on: an installer run that GitHub's sha256 didn't vouch for, a file from a host that isn't GitHub's,
    an oversize stream, a cancel ignored, or a half file left in staging for the next try to trip on.

The route's tests keep the flag on and replace `_fetch` (the one network function) with a stand-in: a release answer
as GitHub gives it and a small installer body with its digest. The suite's network guard stays on throughout.
"""
import hashlib
import io
import os
import threading

import pytest

from app.connect import anki_miner, setup
from app.services import anki_miner_setup as M

# ---------------------------------------------------------------------------
# The look
# ---------------------------------------------------------------------------
MINER_PATH = "C:\\Users\\learner\\AppData\\Local\\Programs\\AnkiMiner\\AnkiMiner.exe"


def _c(id_, state, say, do=None, blocks=None):
    return setup._check(id_, state, say, do, blocks)


def _pieces(monkeypatch, anki="ok", ankiweb="ok", miner=None, found=None, known="ok"):
    """setup.checks' own pieces faked (Anki, its profile, AnkiWeb, the known-words sync, Anki Miner): `checks` runs as
    it is, so the look reads exactly what Connect's setup check returns."""
    anki_check = {"ok": _c("anki", "ok", "Anki is open, with AnkiConnect."),
                  "waiting": _c("anki", "waiting", "Anki isn't open. Connect waits until you open it.", "Open Anki"),
                  }[anki]
    answered = anki == "ok"
    monkeypatch.setattr(setup, "_anki", lambda url, open_anki_on: (anki_check, answered))
    profile = (_c("anki_profile", "ok", 'Connect makes your cards in Anki\'s profile "日本語".') if answered
               else _c("anki_profile", "not-checked", "Checked once Anki is open."))
    monkeypatch.setattr(setup, "_anki_profile",
                        lambda url, answered_, record, keep, use_open: (profile, "日本語" if answered else None))
    web = {"ok": _c("ankiweb", "ok", "Anki syncs with AnkiWeb when a session starts."),
           "needs-you": _c("ankiweb", "needs-you", "Anki isn't signed in to AnkiWeb, so your phone won't get the "
                           "cards.", "In Anki: click Sync and sign in", blocks=False)}[ankiweb]
    monkeypatch.setattr(setup, "_ankiweb", lambda record=None: web)
    sync = (_c("first_known_sync", "ok", "Your known words were last read from Anki on 2026-10-14 21:05.")
            if known == "ok" else
            _c("first_known_sync", "needs-you", "Surasura hasn't read the words you know from Anki yet.",
               "Sync once from Surasura's Anki window first"))
    monkeypatch.setattr(setup, "_first_known_sync", lambda settings, language: sync)
    monkeypatch.setattr(setup, "_anki_miner", lambda settings, language, answered_: (list(miner), found or {}))


def _miner(*states, version="3.7.0"):
    says = {"anki_miner": ("Anki Miner is installed.", None),
            "anki_miner_version": (f"Anki Miner {version} answers Surasura.", None),
            "anki_miner_profile": ('Connect makes cards with Anki Miner\'s profile "Surasura".', None),
            "anki_miner_setup": ("Anki Miner's own setup is finished.", None)}
    out = []
    for id_, state in zip(setup_ids(), states):
        say, do = says[id_]
        if state == "needs-you" and id_ == "anki_miner_setup":
            say, do = ("Anki Miner's own setup isn't finished (deck: no deck chosen).",
                       "Open Anki Miner and finish its setup")
        elif state == "needs-you" and id_ == "anki_miner_profile":
            say, do = ("Anki Miner has no profile named Surasura.",
                       "In Anki Miner: Manage profiles… → New, name it Surasura")
        elif state == "waiting" and id_ == "anki_miner_setup":
            say, do = ("Anki Miner can't reach Anki: Connect waits until Anki is open, then checks the rest of its "
                       "setup.", "Open Anki")
        elif state == "not-checked":
            say, do = ("Checked once Anki Miner answers.", None)
        out.append(_c(id_, state, say, do))
    return out


def setup_ids():
    return ("anki_miner", "anki_miner_version", "anki_miner_profile", "anki_miner_setup")


def _dots(result):
    return {name: (state, tip) for name, state, tip in result["dots"]}


def test_a_fresh_machine_without_anki_miner_is_missing_with_the_install_fix_and_no_record_written():
    """No fakes at all: under the test root Anki isn't asked (SURASURA_NO_ANKI_SYNC) and no Anki Miner is found, so
    the look is *missing*, its fix Connect's own install sentence — and with Connect's preview on in settings (where
    `checks`' default would write), the wizard's look writes no setup record."""
    settings = {"connect_enabled": True, "anki_sync_decks": {"ja": ["日本語::Core"]}}
    result = M.look(settings, "ja")
    assert result["state"] == "missing"
    assert result["version"] is None
    dots = _dots(result)
    assert [name for name, _s, _t in result["dots"]] == ["Anki", "AnkiWeb", "Anki Miner", "Its setup"]
    assert dots["Anki"][0] == "off"                         # not asked in a test run: off, never a warning
    assert dots["Anki Miner"][0] == "warn"
    assert dots["Anki Miner"][1].startswith("Anki Miner: Needs you. Anki Miner isn't installed.")
    assert dots["Its setup"][0] == "off"
    assert result["fix"]["do"] == f"Install Anki Miner ({setup.RELEASES})"
    assert not os.path.exists(setup.record_path())


def test_the_look_asks_connects_checks_with_keep_false(monkeypatch):
    """`keep=False` is passed explicitly: the wizard never records a profile or a check, whatever settings say."""
    seen = {}

    def checks(settings, language, keep=None, use_open_profile=False):
        seen.update(language=language, keep=keep)
        return {"checks": _miner("ok", "ok", "ok", "ok"), "anki_miner": {"path": MINER_PATH, "app": "3.7.0"}}

    monkeypatch.setattr(setup, "checks", checks)
    assert M.look({"connect_enabled": True}, "zh")["state"] == "ready"
    assert seen == {"language": "zh", "keep": False}


def test_ready_shows_four_green_dots_its_version_and_no_fix(monkeypatch):
    _pieces(monkeypatch, miner=_miner("ok", "ok", "ok", "ok"), found={"path": MINER_PATH, "app": "3.7.0"})
    result = M.look({}, "ja")
    assert result["state"] == "ready"
    assert result["version"] == "3.7.0"
    assert result["fix"] is None
    assert [state for _n, state, _t in result["dots"]] == ["ok", "ok", "ok", "ok"]
    # The tip names the state in words, then Connect's own sentence: status is never colour alone
    assert _dots(result)["Anki Miner"][1] == "Anki Miner: Ready. Anki Miner is installed."
    assert _dots(result)["Anki"][1] == "Anki: Ready. Anki is open, with AnkiConnect."


def test_ready_while_anki_is_closed_its_setup_waits_by_itself_and_the_anki_dot_is_off(monkeypatch):
    """Anki closed: Anki Miner's own check can't reach it and Connect waits by itself — nothing only the user can fix,
    so Anki Miner is still ready; the Anki dot is off (grey), never a warning."""
    _pieces(monkeypatch, anki="waiting", miner=_miner("ok", "ok", "ok", "waiting"),
            found={"path": MINER_PATH, "app": "3.7.0"})
    result = M.look({}, "ja")
    assert result["state"] == "ready"
    assert _dots(result)["Anki"][0] == "off"
    assert _dots(result)["Anki"][1].startswith("Anki: Not now. Anki isn't open.")
    assert _dots(result)["Its setup"][0] == "off"
    assert result["fix"] is None                            # waiting is never a fix


def test_too_old_from_the_version_it_answered(monkeypatch):
    miner = _miner("ok", "ok", "not-checked", "not-checked", version="3.4.0")
    miner[1] = _c("anki_miner_version", "needs-you", "Anki Miner 3.4.0 is too old for Surasura: Connect needs 3.5.0 "
                  "or later.", f"Update Anki Miner ({setup.RELEASES})")
    _pieces(monkeypatch, miner=miner, found={"path": MINER_PATH, "app": "3.4.0"})
    result = M.look({}, "ja")
    assert result["state"] == "too-old"
    assert result["version"] == "3.4.0"
    assert result["fix"]["do"] == f"Update Anki Miner ({setup.RELEASES})"
    assert _dots(result)["Anki Miner"][0] == "warn"


def test_too_old_when_the_installer_says_so_and_it_is_never_run(monkeypatch):
    """A build older than 3.5.0 is never run (`anki_miner.version` refuses it): no version answered, the installer's
    own version names it, and the state is still too-old."""
    miner = [_c("anki_miner", "ok", "Anki Miner is installed."),
             _c("anki_miner_version", "needs-you", "Anki Miner 3.2.1 is too old for Surasura: Connect needs 3.5.0 or "
                "later.", f"Update Anki Miner ({setup.RELEASES})"),
             _c("anki_miner_profile", "not-checked", "Checked once Anki Miner answers."),
             _c("anki_miner_setup", "not-checked", "Checked once Anki Miner answers.")]
    _pieces(monkeypatch, miner=miner, found={"path": MINER_PATH})
    monkeypatch.setattr(anki_miner, "installed_version", lambda: "3.2.1")
    result = M.look({}, "ja")
    assert result["state"] == "too-old"
    assert result["version"] == "3.2.1"


def test_needs_setup_names_its_own_setup_as_the_fix(monkeypatch):
    _pieces(monkeypatch, miner=_miner("ok", "ok", "ok", "needs-you"), found={"path": MINER_PATH, "app": "3.7.0"})
    result = M.look({}, "ja")
    assert result["state"] == "needs-setup"
    assert result["fix"] == {"say": "Anki Miner's own setup isn't finished (deck: no deck chosen).",
                             "do": "Open Anki Miner and finish its setup", "update": False}
    assert _dots(result)["Its setup"] == ("warn", "Its setup: Needs you. Anki Miner's own setup isn't finished "
                                                  "(deck: no deck chosen).")
    assert _dots(result)["Anki Miner"][0] == "ok"


def test_needs_setup_when_its_profile_is_missing_the_dot_shows_the_worst_of_its_checks(monkeypatch):
    _pieces(monkeypatch, miner=_miner("ok", "ok", "needs-you", "not-checked"),
            found={"path": MINER_PATH, "app": "3.7.0"})
    result = M.look({}, "ja")
    assert result["state"] == "needs-setup"
    assert _dots(result)["Its setup"][0] == "warn"           # needs-you beats the not-checked beside it
    assert "Manage profiles" in result["fix"]["do"]
    assert result["fix"]["update"] is False                  # a check that doesn't lead with the update


def test_before_37_the_fix_carries_its_update_mark_for_the_pages_update_button(monkeypatch):
    # setup.py marks the pre-3.7 profile check `update`; the look passes it on (the wizard shows *Update Anki Miner…*)
    miner = _miner("ok", "ok", "needs-you", "not-checked", version="3.6.0")
    miner[2]["update"] = True
    _pieces(monkeypatch, miner=miner, found={"path": MINER_PATH, "app": "3.6.0"})
    result = M.look({}, "ja")
    assert result["state"] == "needs-setup"
    assert result["fix"]["update"] is True and "Manage profiles" in result["fix"]["do"]


def test_a_check_that_stops_connect_is_the_fix_before_ankiweb_which_does_not(monkeypatch):
    """AnkiWeb signed out doesn't stop cards being made (`blocks` False): with Anki Miner's setup unfinished too, the
    page's one fix is Anki Miner's; alone, AnkiWeb's is the fix — and its dot warns either way."""
    _pieces(monkeypatch, ankiweb="needs-you", miner=_miner("ok", "ok", "ok", "needs-you"),
            found={"path": MINER_PATH, "app": "3.7.0"})
    result = M.look({}, "ja")
    assert result["fix"]["do"] == "Open Anki Miner and finish its setup"
    assert _dots(result)["AnkiWeb"][0] == "warn"
    _pieces(monkeypatch, ankiweb="needs-you", miner=_miner("ok", "ok", "ok", "ok"),
            found={"path": MINER_PATH, "app": "3.7.0"})
    result = M.look({}, "ja")
    assert result["state"] == "ready"
    assert result["fix"]["do"] == "In Anki: click Sync and sign in"


def test_the_known_words_sync_is_page_twos_never_this_pages_fix(monkeypatch):
    _pieces(monkeypatch, known="needs-you", miner=_miner("ok", "ok", "ok", "ok"),
            found={"path": MINER_PATH, "app": "3.7.0"})
    result = M.look({}, "ja")
    assert result["state"] == "ready"
    assert result["fix"] is None


def test_a_look_that_fails_never_raises_every_dot_off(monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("the setup check broke")

    monkeypatch.setattr(setup, "checks", broken)
    result = M.look({}, "ja")
    assert result["state"] == "missing"                      # under the test root no Anki Miner is found
    assert result["fix"] is None
    assert all(state == "off" and tip.endswith("It couldn't be checked.") for _n, state, tip in result["dots"])
    monkeypatch.setattr(anki_miner, "find", lambda settings: MINER_PATH)
    assert M.look({}, "ja")["state"] == "needs-setup"


def test_the_links_are_connects_own():
    from app.connect import settings_panel
    assert M.RELEASES is setup.RELEASES
    assert M.STAR_URL == settings_panel.STAR_URL


# ---------------------------------------------------------------------------
# The install route
# ---------------------------------------------------------------------------
# A small installer body (several chunks) and its digest, as GitHub's release answer names it
BODY = b"MZ\x90\x00" + ("アンキマイナー セットアップ 3.7.0\r\n".encode("utf-8") * 8000)
DIGEST = hashlib.sha256(BODY).hexdigest()
ASSET = "AnkiMiner-3.7.0-Windows-x86_64-Setup.exe"
DOWNLOAD = f"https://github.com/0xzerolight/anki_miner/releases/download/v3.7.0/{ASSET}"
STORED = "https://release-assets.githubusercontent.com/github-production-release-asset/1/abc?sp=r"


def _release(digest="sha256:" + DIGEST, size=len(BODY), url=DOWNLOAD, extra=()):
    assets = [{"name": "AnkiMiner-3.7.0-macOS-arm64.dmg", "size": 150_000_000, "digest": "sha256:" + "1" * 64,
               "browser_download_url": DOWNLOAD.replace(ASSET, "AnkiMiner-3.7.0-macOS-arm64.dmg")},
              {"name": "AnkiMiner-3.7.0-Linux-x86_64.AppImage", "size": 160_000_000, "digest": "sha256:" + "2" * 64,
               "browser_download_url": DOWNLOAD.replace(ASSET, "AnkiMiner-3.7.0-Linux-x86_64.AppImage")},
              {"name": ASSET, "size": size, "browser_download_url": url}]
    if digest is not None:
        assets[-1]["digest"] = digest
    return {"tag_name": "v3.7.0", "html_url": f"{setup.RELEASES}/tag/v3.7.0", "assets": assets + list(extra)}


class Response(io.BytesIO):
    """urllib's response as the route reads it: `read(n)`, `geturl()`, `headers`, a context manager."""

    def __init__(self, body, url=STORED, length=None):
        super().__init__(body)
        self.url = url
        self.headers = {"Content-Length": str(len(body) if length is None else length)}

    def geturl(self):
        return self.url


class Net:
    """The stand-in for `_fetch`: every call recorded, the release answer and the body handed out."""

    def __init__(self, release=None, body=BODY, final=STORED, length=None):
        self.release = _release() if release is None else release
        self.body, self.final, self.length, self.calls = body, final, length, []

    def __call__(self, url, as_json=False):
        self.calls.append((url, as_json))
        if as_json:
            return self.release
        return Response(self.body, self.final, self.length)


class Launcher:
    def __init__(self, error=None):
        self.error, self.started = error, []

    def __call__(self, path):
        if self.error:
            raise self.error
        with open(path, "rb") as f:
            self.started.append((path, f.read()))       # what was on disk when his installer was opened

        class Process:
            waited = False

            def wait(self):
                Process.waited = True
                return 0
        self.process = Process
        return Process()


@pytest.fixture
def route(monkeypatch):
    """The route switched on, on Windows, nothing running; the network, the launcher and the browser stand-ins."""
    net, launcher, opened = Net(), Launcher(), []
    monkeypatch.setattr(M.sys, "platform", "win32")
    monkeypatch.setattr(M, "_busy", lambda: False)
    monkeypatch.setattr(M, "_fetch", net)
    monkeypatch.setattr(M, "_launch", launcher)
    monkeypatch.setattr(M, "open_url", opened.append)
    monkeypatch.setattr(M.am_release, "APPROVED", "3.7.0")       # alpha 4 M5: the stand-in release is the approved one
    monkeypatch.setattr(M.am_release, "APPROVED_SHA256", DIGEST)

    class Route:
        pass
    r = Route()
    r.net, r.launcher, r.opened, r.ends, r.progress = net, launcher, opened, [], []
    r.run = lambda cancel=None, confirm=lambda: True: M.install(lambda done, total: r.progress.append((done, total)),
                                                        cancel, r.ends.append, confirm)
    return r


def _staging_empty():
    folder = M.staging_folder()
    return not os.path.exists(folder) or not os.listdir(folder)


def test_shipped_install_without_a_yes_fetches_nothing(monkeypatch):
    """The flag at its shipped value (on): no `confirm` handed in -> the releases page and not one call to the network
    function; a `confirm` that says no -> "declined", nothing fetched, nothing opened. The stand-in records any call."""
    assert M.DOWNLOAD_ENABLED is True
    calls, opened, ends = [], [], []
    monkeypatch.setattr(M.sys, "platform", "win32")
    monkeypatch.setattr(M, "_busy", lambda: False)
    monkeypatch.setattr(M, "_fetch", lambda *a, **k: calls.append(a) or pytest.fail("_fetch was called"))
    monkeypatch.setattr(M, "open_url", opened.append)
    monkeypatch.setattr(M, "_launch", lambda path: pytest.fail("an installer was opened"))
    assert M.install(None, None, ends.append) == "opened-releases"
    assert opened == [setup.RELEASES]
    assert M.install(None, None, ends.append, confirm=lambda: False) == "declined"
    assert calls == []
    assert opened == [setup.RELEASES]                        # a no opens nothing more
    assert ends == ["opened-releases", "declined"]
    assert not os.path.exists(M.staging_folder())


def test_switched_off_install_only_opens_the_releases_page(monkeypatch):
    """`DOWNLOAD_ENABLED` False (the one switch): even with a yes, the network function is never called and the
    browser gets Connect's releases page, as 2.x's *Install*."""
    monkeypatch.setattr(M, "DOWNLOAD_ENABLED", False)
    calls, opened, ends = [], [], []
    monkeypatch.setattr(M, "_fetch", lambda *a, **k: calls.append(a) or pytest.fail("_fetch was called"))
    monkeypatch.setattr(M, "open_url", opened.append)
    monkeypatch.setattr(M, "_launch", lambda path: pytest.fail("an installer was opened"))
    assert M.install(None, None, ends.append, confirm=lambda: True) == "opened-releases"
    assert calls == []
    assert opened == [setup.RELEASES]
    assert ends == ["opened-releases"]
    assert not os.path.exists(M.staging_folder())


def test_switched_off_the_network_function_itself_refuses(monkeypatch):
    """The gate is inside `_fetch` too: called directly with the flag off, it reaches nothing."""
    monkeypatch.setattr(M, "DOWNLOAD_ENABLED", False)
    with pytest.raises(M._Refused):
        M._fetch(M.release_api(), as_json=True)


def test_the_whole_route_hands_the_verified_installer_to_the_launcher_then_cleans_staging(route):
    asked = []
    result = route.run(confirm=lambda: asked.append(len(route.net.calls)) or True)
    assert result == "installer-closed"
    assert asked == [0]                                      # the yes came before any byte
    assert route.net.calls == [(M.release_api(), True), (DOWNLOAD, False)]
    [(path, on_disk)] = route.launcher.started
    assert os.path.basename(path) == ASSET
    assert os.path.dirname(path) == M.staging_folder()
    assert on_disk == BODY                                   # the whole file, verified, when his installer opened
    assert route.launcher.process.waited                     # the page checks again only once it closed
    assert route.progress[-1] == (len(BODY), len(BODY))
    assert len(route.progress) > 1 and all(a[0] < b[0] for a, b in zip(route.progress, route.progress[1:]))
    assert route.opened == []
    assert route.ends == ["installer-closed"]
    assert not os.path.exists(M.staging_folder())


def test_a_digest_that_does_not_match_opens_the_releases_page_and_leaves_nothing(route):
    route.net.release = _release(digest="sha256:" + hashlib.sha256(b"another file").hexdigest())
    assert route.run() == "opened-releases"
    assert route.launcher.started == []
    assert route.opened == [setup.RELEASES]
    assert _staging_empty()


@pytest.mark.parametrize("digest", [None, "", "md5:" + "a" * 32, "sha256:" + "z" * 64, "sha256:abc"])
def test_no_sha256_from_github_means_no_download_at_all(route, digest):
    route.net.release = _release(digest=digest)
    assert route.run() == "opened-releases"
    assert route.net.calls == [(M.release_api(), True)]         # the release answer only: the file is never asked for
    assert route.opened == [setup.RELEASES]
    assert _staging_empty()


def test_an_asset_larger_than_the_cap_is_never_downloaded(route):
    route.net.release = _release(size=M.SIZE_CAP + 1)
    assert route.run() == "opened-releases"
    assert route.net.calls == [(M.release_api(), True)]
    assert _staging_empty()


def test_a_stream_longer_than_the_release_says_stops_at_the_cap_and_leaves_nothing(route, monkeypatch):
    """The answer declares one size, the server sends more (no Content-Length): counted as it comes, cut off."""
    route.net.body, route.net.length = BODY + b"\x00" * (3 * M.CHUNK), 0
    assert route.run() == "opened-releases"
    assert route.launcher.started == []
    assert _staging_empty()
    monkeypatch.setattr(M, "SIZE_CAP", M.CHUNK)              # the cap itself, below the release's size
    route.net.release, route.net.body, route.net.length = _release(size=M.CHUNK), BODY, 0
    assert route.run() == "opened-releases"
    assert _staging_empty()


def test_a_content_length_that_differs_from_the_release_is_refused_before_a_byte(route):
    route.net.length = len(BODY) + 1
    assert route.run() == "opened-releases"
    assert route.launcher.started == []
    assert _staging_empty()


def test_an_installer_link_off_githubs_hosts_is_never_fetched(route):
    route.net.release = _release(url=f"https://example.com/mirror/{ASSET}")
    assert route.run() == "opened-releases"
    assert route.net.calls == [(M.release_api(), True)]
    assert _staging_empty()


def test_a_download_that_lands_off_githubs_hosts_is_refused(route):
    route.net.final = "https://cdn.example.net/AnkiMiner-Setup.exe"
    assert route.run() == "opened-releases"
    assert route.launcher.started == []
    assert _staging_empty()


def test_two_windows_installers_or_none_mean_the_releases_page(route):
    twin = {"name": "AnkiMiner-3.7.0-beta-Windows-x86_64-Setup.exe", "size": 10, "digest": "sha256:" + "3" * 64,
            "browser_download_url": DOWNLOAD}
    route.net.release = _release(extra=[twin])
    assert route.run() == "opened-releases"
    release = _release()
    release["assets"] = release["assets"][:2]
    route.net.release = release
    assert route.run() == "opened-releases"
    route.net.release = None                                 # GitHub didn't answer
    assert route.run() == "opened-releases"
    assert route.launcher.started == []


def test_cancel_mid_way_stops_quietly_and_leaves_no_half_file(route):
    # The learner's own Cancel: "cancelled", and no releases page opens behind the window (IK-13, W AD-6)
    stop = threading.Event()
    result = M.install(lambda done, total: (route.progress.append(done), stop.set()), stop, route.ends.append,
                       lambda: True)
    assert result == "cancelled"
    assert route.ends == ["cancelled"]
    assert route.opened == []
    assert len(route.progress) == 1                          # stopped at the next chunk
    assert route.launcher.started == []
    assert _staging_empty()
    # A callable cancel is honoured too
    assert route.run(cancel=lambda: True) == "cancelled"
    assert route.opened == []
    assert _staging_empty()


def test_declining_the_one_confirm_downloads_nothing_and_opens_nothing(route):
    assert route.run(confirm=lambda: False) == "declined"
    assert route.net.calls == []
    assert route.opened == []
    assert route.ends == ["declined"]
    assert _staging_empty()


def test_windows_blocking_the_installer_opens_the_releases_page(route, monkeypatch):
    blocked = OSError(22, "Operation did not complete successfully because the file contains a virus")
    blocked.winerror = 225
    monkeypatch.setattr(M, "_launch", Launcher(error=blocked))
    assert route.run() == "opened-releases"
    assert route.opened == [setup.RELEASES]
    assert _staging_empty()


def test_off_windows_the_releases_page_without_a_fetch(route, monkeypatch):
    monkeypatch.setattr(M.sys, "platform", "darwin")
    assert route.run() == "opened-releases"
    assert route.net.calls == []


def test_never_while_connect_runs_or_anki_miner_is_open(route, monkeypatch):
    """Busy before: nothing asked, nothing opened. Anki Miner started while it downloaded: the file goes, his
    installer is never opened."""
    monkeypatch.setattr(M, "_busy", lambda: True)
    assert route.run() == "busy"
    assert route.net.calls == [] and route.opened == []
    looks = iter([False, True])
    monkeypatch.setattr(M, "_busy", lambda: next(looks))
    assert route.run() == "busy"
    assert route.launcher.started == []
    assert _staging_empty()


def test_busy_reads_connects_lock_and_the_process_list(monkeypatch):
    from app import updater
    from app.connect import status
    monkeypatch.setattr(status, "running", lambda: False)
    monkeypatch.setattr(updater, "_snapshot", lambda: [(4, 0, "explorer.exe"), (88, 4, "anki.exe")])
    assert M._busy() is False
    monkeypatch.setattr(updater, "_snapshot", lambda: [(4, 0, "explorer.exe"), (90, 4, "AnkiMiner.exe")])
    assert M._busy() is True
    monkeypatch.setattr(updater, "_snapshot", lambda: [])
    monkeypatch.setattr(status, "running", lambda: True)
    assert M._busy() is True

    def broken():
        raise OSError("no process list")
    monkeypatch.setattr(status, "running", lambda: False)
    monkeypatch.setattr(updater, "_snapshot", broken)
    assert M._busy() is True                                 # a look that can't be made counts as busy


def test_a_staging_folder_left_by_a_crash_is_emptied_before_a_new_download(route):
    folder = M.staging_folder()
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "AnkiMiner-3.6.0-Windows-x86_64-Setup.exe"), "wb") as f:
        f.write(b"MZ half")
    assert route.run() == "installer-closed"
    assert not os.path.exists(folder)


@pytest.mark.parametrize("url, ok", [
    (M.release_api(), True), (DOWNLOAD, True), (STORED, True),
    ("https://objects.githubusercontent.com/a/b", True),
    ("http://github.com/0xzerolight/anki_miner", False),          # never plain http
    ("https://github.com.example.com/x", False),
    ("https://evil@github.com/x", False),
    ("https://github.com:8443/x", False),
    ("https://raw.githubusercontent.com/x", False),               # not a release host
    ("file:///C:/AnkiMiner-Setup.exe", False), (None, False),
])
def test_only_githubs_release_hosts_over_https(url, ok):
    assert M._github(url) is ok


def test_a_redirect_away_from_github_is_refused_before_it_is_followed():
    import urllib.error
    import urllib.request
    handler = M._GitHubOnly()
    request = urllib.request.Request(DOWNLOAD)
    assert handler.redirect_request(request, None, 302, "Found", {}, STORED) is not None
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(request, None, 302, "Found", {}, "https://cdn.example.net/Setup.exe")


def test_a_confirm_that_raises_fetches_nothing_and_opens_the_releases_page(route):
    def broken():
        raise RuntimeError("the dialog went away")
    assert route.run(confirm=broken) == "opened-releases"
    assert route.net.calls == []
    assert route.opened == [setup.RELEASES]


def test_on_end_raising_never_breaks_install(monkeypatch):
    monkeypatch.setattr(M, "DOWNLOAD_ENABLED", False)
    monkeypatch.setattr(M, "open_url", lambda url: None)

    def end(_result):
        raise RuntimeError("the page is gone")
    assert M.install(None, None, end) == "opened-releases"


# ---------------------------------------------------------------------------
# The review's rows (W3.5-wiz-SM adversary AD-6 … AD-9)
# ---------------------------------------------------------------------------
class Opener:
    """`urllib.request.build_opener`'s stand-in: the handlers it was built with, and one answer per open."""

    def __init__(self, body, final=M.release_api()):
        self.body, self.final, self.handlers, self.opened = body, final, [], []

    def __call__(self, *handlers):
        self.handlers.extend(handlers)
        return self

    def open(self, request, timeout=None):
        self.opened.append(request.full_url)
        return Response(self.body, self.final)


def _json(release):
    import json
    return json.dumps(release, ensure_ascii=False).encode("utf-8")


def test_the_release_answer_follows_githubs_hosts_only_and_is_capped(monkeypatch):
    """AD-6: the release answer names the installer and its sha256 — the trust anchor — so it comes the way the
    download does: redirects only within GitHub's hosts, the final address checked, the answer read up to a cap.
    Never urllib's default opener (no host check per hop)."""
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("the default opener was used"))
    opener = Opener(_json(_release()))
    monkeypatch.setattr(urllib.request, "build_opener", opener)
    assert M._fetch(M.release_api(), as_json=True) == _release()
    assert any(isinstance(h, M._GitHubOnly) for h in opener.handlers)
    assert opener.opened == [M.release_api()]

    monkeypatch.setattr(urllib.request, "build_opener", Opener(_json(_release()), final="https://api.example.net/x"))
    with pytest.raises(M._Refused):
        M._fetch(M.release_api(), as_json=True)
    monkeypatch.setattr(urllib.request, "build_opener", Opener(b"{" + b" " * M.JSON_CAP + b"}"))
    with pytest.raises(M._Refused):
        M._fetch(M.release_api(), as_json=True)


@pytest.mark.parametrize("url", [
    f"https://github.com/someone-else/anki_miner/releases/download/v3.7.0/{ASSET}",      # another account's release
    f"https://github.com/0xzerolight/anki_miner_fork/releases/download/v3.7.0/{ASSET}",
    f"https://github.com/0xzerolight/anki_miner/releases/download/../../../evil/x/releases/download/{ASSET}",
    f"https://objects.githubusercontent.com/0xzerolight/anki_miner/releases/download/v3.7.0/{ASSET}",
])
def test_an_installer_link_outside_anki_miners_own_releases_is_never_fetched(route, url):
    """AD-7: a GitHub host is not enough: the link must be 0xzerolight/anki_miner's own release download."""
    route.net.release = _release(url=url)
    assert route.run() == "opened-releases"
    assert route.net.calls == [(M.release_api(), True)]
    assert route.launcher.started == [] and _staging_empty()


def test_anki_miners_own_link_is_matched_without_regard_to_case(route):
    """GitHub's owner and repository names are case-insensitive."""
    route.net.release = _release(url=DOWNLOAD.replace("0xzerolight/anki_miner", "0xZeroLight/Anki_Miner"))
    assert route.run() == "installer-closed"


def test_an_installer_left_by_a_quit_is_emptied_at_the_next_look_but_never_during_an_install(monkeypatch):
    """AD-8: Surasura quit while his installer was open: the ~180 MB file stays in staging. The page's next look
    empties it — unless an install of this process is running now."""
    def broken(*a, **k):
        raise RuntimeError("Anki Miner's --api failed")
    monkeypatch.setattr(setup, "checks", broken)
    monkeypatch.setattr(anki_miner, "find", lambda settings: None)
    folder = M.staging_folder()
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, ASSET), "wb") as f:
        f.write(BODY)
    with M._ONE_INSTALL:
        M.look({}, "ja")
        assert os.listdir(folder) == [ASSET], "an install running now keeps its file"
    M.look({}, "ja")
    assert _staging_empty()


def test_one_install_at_a_time(route):
    """AD-9: a second Install while one runs (the wizard closed mid-install, then *Set up again*) is busy: nothing
    fetched, nothing opened, the first one's file untouched."""
    with M._ONE_INSTALL:
        assert route.run() == "busy"
    assert route.net.calls == [] and route.opened == [] and route.launcher.started == []
    assert route.run() == "installer-closed", "free again once it ended"


def test_the_installer_on_disk_is_checked_again_just_before_it_is_opened(route, monkeypatch):
    """AD-9: the sha256 is of the stream; the file opened is hashed again, so bytes changed on disk in between are
    never run."""
    download = M._download

    def then_changed(url, path, *rest):
        download(url, path, *rest)
        with open(path, "r+b") as f:
            f.write(b"XX")
    monkeypatch.setattr(M, "_download", then_changed)
    assert route.run() == "opened-releases"
    assert route.launcher.started == [] and _staging_empty()


# ---------------------------------------------------------------------------
# The install as a job in the window's registry (W AD-5 / IK-11)
# ---------------------------------------------------------------------------
def _route_standin(monkeypatch, result, seen):
    """`install` replaced by a stand-in that asks `confirm` first, as the route does, then reports progress and ends with
    `result` — recording what the registry held while it ran."""
    def install(on_progress, cancel, on_end, confirm=None):
        yes = confirm() if confirm is not None else False
        if not yes:
            return M.DECLINED if confirm is not None else M.OPENED_RELEASES
        seen["live"] = list(seen["registry"].live(M.JOB_KIND))
        on_progress(50, 100)
        seen["progress"] = seen["registry"].live(M.JOB_KIND)[0].progress
        seen["cancel"] = cancel
        return result
    monkeypatch.setattr(M, "install", install)


def test_the_install_is_a_job_from_the_learners_yes_until_its_route_ends(monkeypatch):
    from app.services.jobs import JobRegistry
    registry = JobRegistry()
    seen = {"registry": registry}
    _route_standin(monkeypatch, M.INSTALLER_CLOSED, seen)
    cancel = threading.Event()
    shown = []
    result = M.install_as_job(registry, lambda d, t: shown.append((d, t)), cancel, None, confirm=lambda: True)
    assert result == M.INSTALLER_CLOSED
    assert [j.label for j in seen["live"]] == [M.JOB_LABEL]                # listed while it ran: the bar shows it
    assert seen["progress"].done == 50 and seen["progress"].total == 100 and shown == [(50, 100)]
    assert registry.live(M.JOB_KIND) == ()                                 # ended with the route
    ended = [j for j in registry.snapshot() if j.kind == M.JOB_KIND]
    assert len(ended) == 1 and ended[0].state == "done" and not ended[0].cancelled


def test_the_jobs_cancel_and_the_quit_stop_the_download(monkeypatch):
    from app.services.jobs import JobRegistry
    registry = JobRegistry()
    cancel = threading.Event()
    asked = {}

    def install(on_progress, cancel_event, on_end, confirm=None):
        assert confirm()
        registry.quit(timeout=0.5)                                         # the window's quit while it downloads
        asked["set"] = cancel_event.is_set()
        return M.CANCELLED
    monkeypatch.setattr(M, "install", install)
    assert M.install_as_job(registry, lambda d, t: None, cancel, None, confirm=lambda: True) == M.CANCELLED
    assert asked["set"] is True
    ended = [j for j in registry.snapshot() if j.kind == M.JOB_KIND]
    assert ended and ended[0].cancelled


@pytest.mark.parametrize("confirm", [lambda: False, None])
def test_no_yes_lists_no_job(monkeypatch, confirm):
    from app.services.jobs import JobRegistry
    registry = JobRegistry()
    seen = {"registry": registry}
    _route_standin(monkeypatch, M.INSTALLER_CLOSED, seen)
    result = M.install_as_job(registry, lambda d, t: None, threading.Event(), None, confirm=confirm)
    assert result == (M.DECLINED if confirm is not None else M.OPENED_RELEASES)
    assert registry.snapshot() == ()


def test_the_install_kind_conflicts_with_nothing_but_itself():
    from app.services import jobs
    assert jobs.RESOURCES[M.JOB_KIND] == set()
    assert jobs.conflicts(M.JOB_KIND, M.JOB_KIND) and not jobs.conflicts(M.JOB_KIND, "generate")


def test_the_install_asks_github_for_the_approved_tag_never_the_latest(route):
    """Alpha 4 M5: the one release asked for is the approved version's tag (`am_release.APPROVED`), never
    `releases/latest` — a newer, untested Anki Miner is never installed by Surasura."""
    assert route.run() == "installer-closed"
    assert route.net.calls[0] == (f"https://api.github.com/repos/0xzerolight/anki_miner/releases/tags/v3.7.0", True)
    assert "latest" not in route.net.calls[0][0]


@pytest.mark.parametrize("approved, sha", [("3.10.1", None), (None, "0" * 64)])
def test_a_release_that_is_not_the_approved_version_or_installer_is_refused_before_any_byte(route, monkeypatch,
                                                                                               approved, sha):
    """Alpha 4 M5: GitHub answering another version than the approved one, or the approved version with another
    installer than the one approved (its sha256), downloads nothing: the releases page opens, staging stays empty."""
    if approved is not None:
        monkeypatch.setattr(M.am_release, "APPROVED", approved)     # the tag's answer still names 3.7.0
    if sha is not None:
        monkeypatch.setattr(M.am_release, "APPROVED_SHA256", sha)
    assert route.run() == "opened-releases"
    assert [c for c in route.net.calls if c[0] == DOWNLOAD] == [], "no byte of the installer"
    assert route.launcher.started == [] and _staging_empty()

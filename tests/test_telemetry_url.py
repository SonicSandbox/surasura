"""The telemetry receiver's address from update.json (2026-10-30, ship track).

The update check the app already makes reads update.json's `telemetry_url`; the telemetry keeps the last valid one in
the persistent data folder and the next heartbeat goes there, the build's .env TELEMETRY_URL being the fallback. The
opt-out, the dev-env skip and the forced event's anonymised id are unchanged. No network: GitHub's answers and
requests.get are stubbed, and every file lives under the test root (conftest's SURASURA_TEST_ROOT).
"""
import json
import os
import subprocess
import sys

import pytest
import requests  # the heartbeat imports it on its own thread: patched as requests.get

import package_app
from app import path_utils, telemetry
from app import update_checker as uc

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECEIVER = "https://surasura-telemetry.sonicswain.workers.dev"
MOVED = "https://telemetry.example.org/hb"
FALLBACK = "https://fallback.example.org/webhook"

_RELEASE = {
    "tag_name": "v3.0.1",
    "html_url": "https://github.com/SonicSandbox/surasura/releases/tag/v3.0.1",
    "assets": [{"name": "update.json", "browser_download_url": "https://x/update.json"},
               {"name": "update.json.sig", "browser_download_url": "https://x/update.json.sig"}],
}


def _check(monkeypatch, manifest):
    """One update check against a stubbed GitHub whose update.json is `manifest` (a dict, or raw text)."""
    text = manifest if isinstance(manifest, str) else json.dumps(manifest)
    monkeypatch.setattr(uc, "_http_json", lambda url, timeout=10: _RELEASE)
    monkeypatch.setattr(uc, "_http_text", lambda url, timeout=10: text)
    return uc.get_update_info()


def _cache_path():
    return os.path.join(path_utils.persistent_root(), telemetry.URL_CACHE)


@pytest.fixture
def production(monkeypatch):
    """A production build whose .env names FALLBACK, telemetry on; every heartbeat's GET recorded, none sent."""
    monkeypatch.setattr(telemetry, "TELEMETRY_ENV", "production")
    monkeypatch.setattr(telemetry, "TELEMETRY_URL", FALLBACK)
    settings = {"telemetry_enabled": True, "target_language": "ja"}
    monkeypatch.setattr(telemetry.settings_manager, "load_settings", lambda *a, **k: dict(settings))
    sent = []
    monkeypatch.setattr(requests, "get", lambda url, params=None, timeout=None: sent.append((url, params)))
    return settings, sent


# --- update.json with / without / with a bad telemetry_url -----------------------------------------------------------

def test_an_update_json_naming_a_receiver_sends_the_next_heartbeat_there(monkeypatch, production):
    """The check keeps the address; the heartbeat after it goes to the kept one, not .env's."""
    _settings, sent = production
    info = _check(monkeypatch, {"version": "3.0.1", "update_type": "full", "telemetry_url": RECEIVER})
    assert info.version == "3.0.1"
    assert telemetry.receiver_url() == RECEIVER
    telemetry._send_heartbeat_thread("Multilingual-beta")
    assert [url for url, _ in sent] == [RECEIVER]
    assert sent[0][1]["uid"] and sent[0][1]["env"] == "production"      # the heartbeat itself unchanged


def test_with_nothing_kept_the_heartbeat_goes_to_the_builds_env_address(monkeypatch, production):
    """No update.json key and no cache: .env's TELEMETRY_URL, as before this change."""
    _settings, sent = production
    _check(monkeypatch, {"version": "3.0.1", "update_type": "full"})
    assert not os.path.exists(_cache_path())
    telemetry._send_heartbeat_thread("Multilingual-beta")
    assert [url for url, _ in sent] == [FALLBACK]


def test_an_update_json_without_the_key_keeps_the_address_already_kept(monkeypatch, production):
    """A later release that names no receiver leaves the last one in place (only a valid address replaces it)."""
    _check(monkeypatch, {"version": "3.0.1", "telemetry_url": RECEIVER})
    _check(monkeypatch, {"version": "3.0.2"})
    assert telemetry.receiver_url() == RECEIVER


def test_a_new_address_replaces_the_kept_one(monkeypatch, production):
    """The receiver moved (Sonic's own domain later): the next check's address wins, without a release of the app."""
    _check(monkeypatch, {"version": "3.0.1", "telemetry_url": RECEIVER})
    _check(monkeypatch, {"version": "3.0.1", "telemetry_url": MOVED})
    assert telemetry.receiver_url() == MOVED
    with open(_cache_path(), encoding="utf-8") as f:
        assert json.load(f) == {"url": MOVED}


@pytest.mark.parametrize("bad", [
    "http://surasura-telemetry.sonicswain.workers.dev",          # not https
    "https://",                                                   # no host
    "https://user:secret@surasura-telemetry.example.org",         # credentials
    "https://surasura telemetry.example.org",                     # a space
    "https://surasura-telemetry.example.org/\nX-Header: 1",       # a line break
    "https://surasura-telemetry.example.org:port/",               # a port that isn't one
    "https://example.org/" + "a" * 300,                           # too long
    "file:///C:/Users/x/telemetry",
    "",
    42,
    None,
    ["https://surasura-telemetry.example.org"],
])
def test_a_bad_telemetry_url_is_ignored_and_the_kept_one_stays(monkeypatch, production, bad):
    _settings, sent = production
    _check(monkeypatch, {"version": "3.0.1", "telemetry_url": RECEIVER})
    info = _check(monkeypatch, {"version": "3.0.2", "update_type": "full", "telemetry_url": bad})
    assert info is not None and info.version == "3.0.2"                   # the update check itself unharmed
    assert telemetry.receiver_url() == RECEIVER
    telemetry._send_heartbeat_thread("Multilingual-beta")
    assert [url for url, _ in sent] == [RECEIVER]


def test_a_bad_telemetry_url_with_nothing_kept_falls_back_to_env(monkeypatch, production):
    _settings, sent = production
    _check(monkeypatch, {"version": "3.0.1", "telemetry_url": "http://plain.example.org"})
    assert not os.path.exists(_cache_path())
    telemetry._send_heartbeat_thread("Multilingual-beta")
    assert [url for url, _ in sent] == [FALLBACK]


def test_a_malformed_update_json_keeps_nothing(monkeypatch, production):
    info = _check(monkeypatch, "{ not json ]")
    assert info.update_type == "full"
    assert telemetry.receiver_url() == FALLBACK


def test_a_3x_manifest_names_its_receiver_only_when_signed(monkeypatch, production):
    """A format-2 update.json is trusted only with a good signature: an unsigned one's address is not kept."""
    manifest = {"version": "3.0.1", "format": 2, "telemetry_url": MOVED, "package": None}
    monkeypatch.setattr(uc, "_signature_ok", lambda *a, **k: False)
    assert _check(monkeypatch, manifest).signed is False
    assert telemetry.receiver_url() == FALLBACK
    monkeypatch.setattr(uc, "_signature_ok", lambda *a, **k: True)
    assert _check(monkeypatch, manifest).signed is True
    assert telemetry.receiver_url() == MOVED


def test_a_cache_that_cannot_be_written_never_fails_the_update_check(monkeypatch, production):
    def _boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(path_utils, "get_persistent_user_data_path", _boom)
    info = _check(monkeypatch, {"version": "3.0.1", "update_type": "full", "telemetry_url": RECEIVER})
    assert info.version == "3.0.1" and info.update_type == "full"
    assert telemetry.receiver_url() == FALLBACK


@pytest.mark.parametrize("content", ['{"url": "http://plain.example.org"}', "not json", '["x"]', ""])
def test_a_damaged_or_edited_cache_falls_back_to_env(production, content):
    os.makedirs(path_utils.persistent_root(), exist_ok=True)
    with open(_cache_path(), "w", encoding="utf-8") as f:
        f.write(content)
    assert telemetry.receiver_url() == FALLBACK


def test_the_same_address_again_is_not_rewritten(monkeypatch, production):
    _check(monkeypatch, {"version": "3.0.1", "telemetry_url": RECEIVER})
    os.utime(_cache_path(), (1_000_000_000, 1_000_000_000))
    _check(monkeypatch, {"version": "3.0.1", "telemetry_url": RECEIVER})
    assert os.path.getmtime(_cache_path()) == 1_000_000_000


# --- opted out, dev env: nothing sent ---------------------------------------------------------------------------------

def test_opted_out_a_heartbeat_sends_nothing_even_with_a_kept_address(monkeypatch, production):
    settings, sent = production
    _check(monkeypatch, {"version": "3.0.1", "telemetry_url": RECEIVER})
    settings["telemetry_enabled"] = False
    telemetry._send_heartbeat_thread("Multilingual-beta")
    assert sent == []


def test_opted_out_the_forced_update_event_goes_to_the_kept_address_anonymised(monkeypatch, production):
    """The forced event is unchanged (a throwaway id, open_count 0); it only follows the receiver."""
    settings, sent = production
    _check(monkeypatch, {"version": "3.0.1", "telemetry_url": RECEIVER})
    settings["telemetry_enabled"] = False
    telemetry._send_heartbeat_thread("Updated 2.9.0.6 -> 2.9.0.7", respect_optout=False)
    assert [url for url, _ in sent] == [RECEIVER]
    assert sent[0][1]["uid"].startswith("anon-") and sent[0][1]["open_count"] == 0


def test_a_dev_build_sends_nothing_and_starts_no_heartbeat(monkeypatch, production):
    _settings, sent = production
    _check(monkeypatch, {"version": "3.0.1", "telemetry_url": RECEIVER})
    monkeypatch.setattr(telemetry, "TELEMETRY_ENV", "dev")
    started = []
    monkeypatch.setattr(telemetry.threading, "Thread", lambda *a, **k: started.append(k))
    telemetry.init()
    telemetry.send_update_event("2.9.0.6")
    telemetry._send_heartbeat_thread("Multilingual-beta")
    telemetry._send_heartbeat_thread("Updated", respect_optout=False)
    assert started == [] and sent == []


def test_with_no_address_anywhere_nothing_is_sent(monkeypatch, production):
    _settings, sent = production
    monkeypatch.setattr(telemetry, "TELEMETRY_URL", None)
    telemetry._send_heartbeat_thread("Multilingual-beta")
    assert sent == []


# --- the cache survives a restart -------------------------------------------------------------------------------------

def test_the_kept_address_survives_a_restart(monkeypatch, production):
    """A fresh process (the next start) reads the address the last run's check kept, before any check of its own."""
    _check(monkeypatch, {"version": "3.0.1", "telemetry_url": RECEIVER})
    env = dict(os.environ, TELEMETRY_URL=FALLBACK, TELEMETRY_ENV="dev", PYTHONIOENCODING="utf-8")
    env.pop("PYTEST_CURRENT_TEST", None)
    code = "from app import telemetry; print(telemetry.receiver_url())"
    out = subprocess.run([sys.executable, "-c", code], cwd=PROJECT, env=env, capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == RECEIVER


# --- the release kit writes it ----------------------------------------------------------------------------------------

def test_the_shipped_build_config_names_the_live_receiver():
    assert package_app.load_build_config()["release"]["telemetry_url"] == RECEIVER


@pytest.mark.parametrize("value", [None, "http://surasura-telemetry.sonicswain.workers.dev", "not a url"])
def test_a_build_config_without_a_valid_telemetry_url_stops_the_build(tmp_path, value):
    with open(os.path.join(PROJECT, "packaging", "build_config.json"), encoding="utf-8") as f:
        config = json.load(f)
    if value is None:
        del config["release"]["telemetry_url"]
    else:
        config["release"]["telemetry_url"] = value
    path = tmp_path / "build_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="telemetry_url"):
        package_app.load_build_config(str(path))


def test_the_release_update_json_carries_the_receiver(tmp_path, monkeypatch):
    """_build_release writes `telemetry_url` into update.json (inside the signed bytes), and the client reads it back."""
    monkeypatch.delenv(package_app.SIGNING_KEY_ENV, raising=False)
    final = tmp_path / "Surasura"
    (final / "_internal").mkdir(parents=True)
    (final / "Surasura.exe").write_bytes(b"MZ stand-in")
    out = tmp_path / "out"
    out.mkdir()
    manifest = package_app._build_release(str(final), "3.0.1", package_app.load_build_config(), out_dir=str(out))
    with open(out / "update.json", encoding="utf-8") as f:
        written = json.load(f)
    assert manifest["telemetry_url"] == written["telemetry_url"] == RECEIVER
    assert uc.valid_telemetry_url(written["telemetry_url"]) == RECEIVER

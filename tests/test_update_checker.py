"""Tests for update detection & classification (app/update_checker.py).

Covers version parsing, the full classify_update decision matrix (including the
runtime-baseline boundary that protects a delta from landing on an incompatible runtime),
manifest parsing, and the fail-closed behaviour on missing/ malformed metadata or no
network. No real HTTP is performed — the GitHub/manifest layer is monkeypatched.
"""
import urllib.error
import pytest

from app import update_checker as uc
from app.update_checker import UpdateInfo, classify_update, parse_version, version_string


# --- version helpers ---------------------------------------------------------
def test_parse_version_handles_tags_and_bare_ints():
    assert parse_version("v1.0.0") == (1, 0, 0)
    assert parse_version("2.1") == (2, 1)
    assert parse_version("v2") == (2,)
    assert parse_version("Beta-Production-1.1") == (1, 1)
    assert parse_version("no-numbers-here") == (0, 0, 0)


def test_version_string_extracts_numeric_substring():
    assert version_string("v2.1") == "2.1"
    assert version_string("2.0.3") == "2.0.3"
    assert version_string("Surasura_v1.9") == "1.9"
    assert version_string("nightly") == ""


# --- classify_update matrix --------------------------------------------------
def _info(**kw):
    base = dict(
        version="2.1", update_type="app", runtime_baseline="2.0",
        sha256="abc", app_package_url="http://x/app.zip", full_url="http://x/full.zip",
        notes_url="http://x/notes",
    )
    base.update(kw)
    return UpdateInfo(**base)


def test_classify_none_when_up_to_date_or_older():
    assert classify_update("2.1", _info(version="2.1")) == "NONE"
    assert classify_update("2.2", _info(version="2.1")) == "NONE"
    assert classify_update("2.1", None) == "NONE"


def test_classify_app_when_eligible_delta():
    # Newer, declared app, has package+sha, current >= runtime_baseline.
    assert classify_update("2.0", _info(version="2.1", runtime_baseline="2.0")) == "APP"


def test_classify_full_when_marked_full():
    assert classify_update("2.0", _info(version="3.0", update_type="full")) == "FULL"


def test_classify_full_across_runtime_boundary():
    """Current version is BEHIND the release's runtime baseline -> must be manual/full.

    A 2.0 user cannot delta up to a 2.6 whose runtime changed at 2.5; dropping new app code
    on the old runtime would crash. classify_update must force FULL here even though the
    release is 'app' type.
    """
    assert classify_update("2.0", _info(version="2.6", runtime_baseline="2.5")) == "FULL"
    # But a user already past the baseline may delta.
    assert classify_update("2.5", _info(version="2.6", runtime_baseline="2.5")) == "APP"


def test_classify_full_when_metadata_incomplete():
    # 'app' but missing checksum -> cannot verify -> fail closed to FULL.
    assert classify_update("2.0", _info(version="2.1", sha256="")) == "FULL"
    # 'app' but no package asset -> FULL.
    assert classify_update("2.0", _info(version="2.1", app_package_url=None)) == "FULL"


# --- get_update_info (network + manifest layer, monkeypatched) ---------------
_RELEASE = {
    "tag_name": "v2.1",
    "html_url": "https://github.com/SonicSandbox/surasura/releases/tag/v2.1",
    "assets": [
        {"name": "Surasura_v2.1.zip", "browser_download_url": "http://x/Surasura_v2.1.zip"},
        {"name": "Surasura_app_v2.1.zip", "browser_download_url": "http://x/Surasura_app_v2.1.zip"},
        {"name": "update.json", "browser_download_url": "http://x/update.json"},
    ],
}


def _patch(monkeypatch, release, manifest_text):
    monkeypatch.setattr(uc, "_http_json", lambda url, timeout=10: release)
    monkeypatch.setattr(uc, "_http_text", lambda url, timeout=10: manifest_text)


def test_get_update_info_app_release(monkeypatch):
    _patch(monkeypatch, _RELEASE,
           '{"version":"2.1","update_type":"app","runtime_baseline":"2.0","sha256":"deadbeef","critical":false}')
    info = uc.get_update_info()
    assert info.version == "2.1"
    assert info.update_type == "app"
    assert info.runtime_baseline == "2.0"
    assert info.sha256 == "deadbeef"
    assert info.app_package_url == "http://x/Surasura_app_v2.1.zip"
    assert info.full_url == "http://x/Surasura_v2.1.zip"
    assert classify_update("2.0", info) == "APP"


def test_get_update_info_missing_manifest_is_full(monkeypatch):
    """A release with no update.json asset -> full (notify, never auto-apply)."""
    release = {"tag_name": "v2.1", "html_url": "http://x/notes",
               "assets": [{"name": "Surasura_v2.1.zip", "browser_download_url": "http://x/full.zip"}]}
    _patch(monkeypatch, release, None)
    info = uc.get_update_info()
    assert info.update_type == "full"
    assert classify_update("2.0", info) == "FULL"


def test_get_update_info_malformed_manifest_fails_closed(monkeypatch):
    _patch(monkeypatch, _RELEASE, "{ this is not valid json ]")
    info = uc.get_update_info()
    assert info.update_type == "full"  # fell back safely
    assert classify_update("2.0", info) == "FULL"


def test_get_update_info_critical_flag_parsed(monkeypatch):
    _patch(monkeypatch, _RELEASE,
           '{"version":"2.1","update_type":"app","runtime_baseline":"2.0","sha256":"x","critical":true}')
    info = uc.get_update_info()
    assert info.critical is True


def test_get_update_info_none_on_no_release(monkeypatch):
    def _raise_404(url, timeout=10):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(uc, "_http_json", _raise_404)
    assert uc.get_update_info() is None


def test_get_update_info_none_when_offline(monkeypatch):
    def _boom(url, timeout=10):
        raise OSError("network unreachable")
    monkeypatch.setattr(uc, "_http_json", _boom)
    assert uc.get_update_info() is None

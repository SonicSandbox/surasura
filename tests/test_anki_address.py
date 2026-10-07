"""One AnkiConnect address (E1.4 §A): `anki_connect.address(settings)`, read by every Anki caller.

2.x had two keys with the same default — `anki_connect_url` (the Anki sync, the dashboard's reads) and
`junban_url` (順, Backfill, the automatic step) — so a hand edit of one split the sync from Junban.
What this file holds:
  * the rule, over every case a settings.json can be in;
  * the dashboard's own Anki reads (the automatic sync, Generate's backlog read) and the Anki window
    reach the address set through either key — the Junban callers are proved in Junban's suite
    (`modules/junban/tests/test_anki_address_callers.py`);
  * a source guard: nothing reads either key but `address()` and the named exceptions;
  * the dashboard's full save writes a hand-edited `junban_url` as `anki_connect_url`.
"""
import json
import os
import re
from unittest.mock import MagicMock, patch

import pytest

from app import anki_connect, settings_manager
from tests.test_anki_sync_wiring import _DashboardHarness

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = anki_connect.DEFAULT_URL
CUSTOM = "http://127.0.0.1:18765"           # a non-default loopback port, as a second AnkiConnect would use
OTHER = "http://localhost:28765"


@pytest.mark.parametrize("settings, expected", [
    ({}, DEFAULT),                                                           # neither set
    (None, DEFAULT),
    ({"anki_connect_url": DEFAULT, "junban_url": DEFAULT}, DEFAULT),         # both at the default
    ({"anki_connect_url": DEFAULT, "junban_url": CUSTOM}, CUSTOM),           # a 2.x hand edit of Junban's
    ({"junban_url": CUSTOM}, CUSTOM),
    ({"anki_connect_url": CUSTOM, "junban_url": DEFAULT}, CUSTOM),           # the one key, edited
    ({"anki_connect_url": CUSTOM}, CUSTOM),
    ({"anki_connect_url": CUSTOM, "junban_url": OTHER}, CUSTOM),             # both custom: the one key wins
    ({"anki_connect_url": f"  {CUSTOM}\n", "junban_url": DEFAULT}, CUSTOM),  # whitespace
    ({"anki_connect_url": "   ", "junban_url": f" {OTHER} "}, OTHER),
    ({"anki_connect_url": "", "junban_url": ""}, DEFAULT),                   # empty strings
    ({"anki_connect_url": None, "junban_url": None}, DEFAULT),
])
def test_the_address_rule(settings, expected):
    assert anki_connect.address(settings) == expected


def test_two_different_custom_addresses_are_named_in_the_log_once(capsys):
    anki_connect._ADDRESS_NOTED.clear()
    settings = {"anki_connect_url": CUSTOM, "junban_url": OTHER}
    for _ in range(3):
        assert anki_connect.address(settings) == CUSTOM
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1 and CUSTOM in lines[0] and OTHER in lines[0]


# --- every caller reaches the address ---------------------------------------------------------------- #
class _Anki:
    """A patched `urlopen` that answers like a healthy AnkiConnect and records where it was asked."""

    def __init__(self):
        self.urls = []

    def __call__(self, request, timeout=None):
        self.urls.append(request.full_url)
        action = json.loads(request.data.decode("utf-8"))["action"]
        result = {"requestPermission": {"permission": "granted", "version": 6}, "version": 6}.get(action, [])
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"result": result, "error": None}).encode()
        return response


@pytest.fixture(params=["anki_connect_url", "junban_url"])
def custom_key(request):
    """Each caller twice: the port set only through the one key, then only through 2.x's Junban key."""
    return request.param


def test_the_anki_window_reads_the_address(custom_key):
    from app.anki_sync_gui import AnkiSyncGui
    window = MagicMock()
    window._saved_settings.return_value = {custom_key: CUSTOM}
    url = AnkiSyncGui._url(window)
    fake = _Anki()
    with patch("urllib.request.urlopen", fake):
        assert anki_connect.probe(url)["ok"]
    assert url == CUSTOM and fake.urls == [CUSTOM]


class TestTheDashboardsReads(_DashboardHarness):
    """The automatic sync and Generate's backlog read, run to the end on the captured thread."""

    def _run(self, method, settings):
        from app import anki_sync
        self.app.var_anki_backlog_on_generate = MagicMock()
        self.app.var_anki_backlog_on_generate.get.return_value = True
        with patch.object(self.main.settings_manager, "load_settings", return_value=settings), \
                patch.object(anki_sync, "load_state", return_value={"last_sync": "2026-09-18T12:00:00"}), \
                patch.object(self.main.threading, "Thread") as thread:
            getattr(self.MasterDashboardApp, method)(self.app, force=True) if method == "_maybe_anki_sync" \
                else getattr(self.MasterDashboardApp, method)(self.app)
        fake = _Anki()
        with patch("urllib.request.urlopen", fake), \
                patch.object(anki_sync, "sync", return_value=None) as sync, \
                patch.object(anki_sync, "sync_backlog", return_value=(0, None)) as backlog:
            thread.call_args.kwargs["target"]()
        return fake, sync, backlog

    def test_both_reads_reach_the_address_set_through_either_key(self):
        for key in ("anki_connect_url", "junban_url"):
            settings = dict(self._settings(), **{key: CUSTOM})
            fake, sync, backlog = self._run("_maybe_anki_sync", settings)
            self.assertEqual(set(fake.urls), {CUSTOM}, key)
            self.assertEqual(sync.call_args.args[1], CUSTOM)
            self.assertEqual(backlog.call_args.args[1], CUSTOM)
            fake, _sync, backlog = self._run("_maybe_backlog_sync", settings)
            self.assertEqual(set(fake.urls), {CUSTOM}, key)
            self.assertEqual(backlog.call_args.args[1], CUSTOM)


# --- the source guard -------------------------------------------------------------------------------- #
# Where the two keys may be named in code: `address()` itself, the core default, the run signature's
# non-analysis list, where each setting belongs (`PLACED`, W1.3) and the dashboard's save (which writes `address()`'s
# answer under the one key and takes the 2.x key out: it writes only its own keys onto the file as it is, W1.3).
_ALLOWED = {
    os.path.join("app", "anki_connect.py"): 2,
    os.path.join("app", "settings_manager.py"): 1,
    os.path.join("app", "analyzer.py"): 1,
    os.path.join("app", "settings_placement.py"): 1,
    os.path.join("app", "main.py"): 2,
}
_KEY = re.compile(r"""["'](anki_connect_url|junban_url)["']""")


def _code_files():
    for top in ("app", "modules"):
        for where, dirs, files in os.walk(os.path.join(_ROOT, top)):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", "vendor")]
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(where, name)
    yield os.path.join(_ROOT, "app_entry.py")


def test_no_code_reads_either_address_key_but_the_one_function():
    found = {}
    for path in _code_files():
        with open(path, encoding="utf-8") as handle:
            count = len(_KEY.findall(handle.read()))
        if count:
            found[os.path.relpath(path, _ROOT)] = count
    assert found == _ALLOWED


def test_the_dashboards_save_writes_a_hand_edited_junban_url_as_the_one_key():
    from app.main import MasterDashboardApp
    with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"target_language": "ja", "junban_url": CUSTOM}, f)
    loaded = settings_manager.load_settings()
    app = MagicMock()
    app._current_settings = loaded
    app.logic_settings = loaded["logic"]
    app._iv = lambda var, fallback: fallback
    saved = {}
    with patch.object(settings_manager, "save_settings", side_effect=lambda s, **k: saved.update(s)):
        MasterDashboardApp.save_settings(app, skip_ui=True)
    assert saved["anki_connect_url"] == CUSTOM
    assert "junban_url" not in saved, "the file then holds one address"

"""Connect's four settings (P1.3) and the dashboard's save: kept as the user set them, never written when they weren't
(intent review #7 — preview off, settings.json stays as 2.5 leaves it), and read by no run (never in a signature)."""
import json
import os
from unittest.mock import MagicMock, patch

from app import settings_manager
from app.path_utils import get_user_file

CONNECT = ("connect_mine_words", "connect_send_grammar", "connect_anki_miner_path", "connect_anki_miner_profile")


def _write(values):
    with open(get_user_file("settings.json"), "w", encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False)


def _dashboard_save():
    from app.main import MasterDashboardApp
    loaded = settings_manager.load_settings()
    app = MagicMock()
    app._current_settings = loaded
    app.logic_settings = loaded["logic"]
    app._iv = lambda var, fallback: fallback
    saved = {}
    with patch.object(settings_manager, "save_settings", side_effect=lambda s, **k: saved.update(s)):
        MasterDashboardApp.save_settings(app, skip_ui=True)
    return saved


def test_a_dashboard_save_never_writes_connects_defaults():
    _write({"target_language": "ja"})
    saved = _dashboard_save()
    assert not set(CONNECT) & set(saved)
    assert settings_manager.load_settings()["connect_mine_words"] == "list"      # the default still reads


def test_a_dashboard_save_keeps_what_the_user_set():
    _write({"target_language": "ja", "connect_mine_words": "i1", "connect_send_grammar": False,
            "connect_anki_miner_path": os.path.join("D:\\", "ツール", "AnkiMiner", "AnkiMiner.exe")})
    saved = _dashboard_save()
    assert saved["connect_mine_words"] == "i1" and saved["connect_send_grammar"] is False
    assert saved["connect_anki_miner_path"].endswith("AnkiMiner.exe")
    assert "connect_anki_miner_profile" not in saved


def test_a_dashboard_save_never_writes_junbans_preview_keys_and_keeps_them_once_set():
    """P1.4-1's two keys show in 順 only while Connect's preview is on: a dashboard save never writes their defaults
    into a settings.json without them (review P1.4-adversary #6), and keeps what the user set."""
    import pytest
    pytest.importorskip("modules.junban")
    _write({"target_language": "ja", "enable_junban": True, "junban_deck": "TheBank"})
    saved = _dashboard_save()
    assert saved["junban_deck"] == "TheBank", "Junban's other keys are carried as before"
    assert "junban_own_tag" not in saved and "junban_order_all" not in saved
    _write({"target_language": "ja", "enable_junban": True, "junban_own_tag": "immersion", "junban_order_all": True})
    saved = _dashboard_save()
    assert saved["junban_own_tag"] == "immersion" and saved["junban_order_all"] is True

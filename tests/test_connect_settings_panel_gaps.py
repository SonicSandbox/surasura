"""Settings → Connect (preview)'s gaps the P3.1 mutant pass found (2026-10-11), and the save they rest on.

What a wrong answer would cost: the cap box written to settings.json every time the focus leaves it, its value
unchanged — a write the user never asked for (S19: only what changed is written), and one that can land between
another window's read and write; a Chinese folder written under Japanese (Japanese's folders erased, D31); a refused
write that crashes every other window's plain save, or one Connect's controls never hear about. The panel on a hidden
root; settings.json is the test root's."""
import os

import pytest

from app import settings_manager
from app.connect import settings_panel
from tests import cli_helpers as h
from tests.connect_tk_helpers import read_settings, settings_bytes
from tests.test_connect_settings_panel import _panel, root  # noqa: F401  (the fixture)


def test_the_cap_left_as_it_was_writes_nothing(root, monkeypatch):
    panel, _tips, _pump, _before = _panel(root, {"connect_backlog_cap": {"ja": 200, "zh": 80}})
    assert panel.var_cap.get() == "200"
    saves = []
    real = settings_manager.save_keys
    monkeypatch.setattr(settings_manager, "save_keys", lambda *a, **k: (saves.append(1), real(*a, **k))[1])
    before = settings_bytes()
    panel._save_cap()                               # the focus leaves the box, 200 still in it
    panel.var_cap.set(" 200 ")                      # the same number, typed again with spaces
    panel._save_cap()
    assert saves == [] and settings_bytes() == before, "nothing written"
    panel.var_cap.set("150")
    panel._save_cap()
    assert saves == [1], "a changed cap is written"


def test_a_chinese_panels_added_folder_is_kept_under_zh_and_japanese_folders_stay(root, tmp_path):
    # Why a Chinese folder: the rule is per language; a Japanese folder already on disk must come through untouched.
    japanese = "D:\\アニメ"
    added = str(tmp_path / "电视剧" / "武林外传")
    panel, _tips, _pump, _before = _panel(root, {"connect_video_folders": {"ja": [japanese]}}, language="zh",
                                         ask_folder=lambda: added)
    panel.btn_add_folder.invoke()

    on_disk = read_settings()["connect_video_folders"]
    assert on_disk == {"ja": [japanese], "zh": [os.path.normpath(added)]}, \
        "the Chinese folder goes under zh; Japanese's folders are kept as they were"
    assert panel.list_folders.get(0, "end") == (os.path.normpath(added),), "the list shows the Chinese folder"


@pytest.fixture
def refused_write(monkeypatch):
    """settings.json can't be written: `save_settings` reports False, as it does when the disk refuses."""
    monkeypatch.setattr(settings_manager, "save_settings", lambda *a, **k: False)
    return settings_manager


def test_a_plain_save_whose_write_is_refused_returns_the_key_and_does_not_raise(refused_write):
    """Without `strict`, a refused write is not an error: the window gets its settings back, with its own key in
    them."""
    h.write_settings(target_language="ja")
    saved = refused_write.save_keys({"theme": "Dark Flow"})
    assert saved["theme"] == "Dark Flow"


def test_a_strict_save_whose_write_is_refused_raises_oserror(refused_write):
    """With `strict=True` (Connect's controls), the same refused write raises OSError so the control can say it
    wasn't saved."""
    h.write_settings(target_language="ja")
    with pytest.raises(OSError):
        refused_write.save_keys({"theme": "Dark Flow"}, strict=True)


def test_a_cap_kept_per_language_shows_300_for_a_language_it_doesnt_name(root):
    # The runner's cap for a language the dict doesn't name is 300 (P2.4-B-SD4); the box must show the same, never 0
    # ("no limit") — saving the shown value would lift the learner's cap
    assert settings_panel.cap_of({"ja": 200}, "zh") == 300
    panel, _tips, _pump, _before = _panel(root, {"connect_backlog_cap": {"ja": 200}}, language="zh")
    assert panel.var_cap.get() == "300"


def test_remove_takes_the_chosen_folder_not_the_first(root):
    first, second = "D:\アニメ\一期", "D:\アニメ\二期"
    panel, _tips, _pump, _before = _panel(root, {"connect_video_folders": {"ja": [first, second], "zh": []}})
    panel.list_folders.selection_set(1)
    panel.btn_remove_folder.invoke()
    assert read_settings()["connect_video_folders"] == {"ja": [first], "zh": []}
    assert panel.list_folders.get(0, "end") == (first,)

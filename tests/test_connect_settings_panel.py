"""Settings → Connect (preview)'s controls (P3.1 row 3.1.2; P1.5 05-surface U4): each one saved the moment it is
touched, with `save_keys`, its own key only.

What a wrong answer would cost: a control that writes the whole file (or a default beside its key) puts keys into a
2.5 user's settings.json and undoes another window's save; a Known-from-Anki dropdown that drops a term widens the
signal (marked alone instead of suspended + marked marks more words known); the Japanese video folders written as a
plain list erase the Chinese ones; a logs zip made on the screen's thread freezes the window; a button without a
tooltip breaks the GUI guidelines. The panel is built on a hidden root; settings.json is the test root's; Anki Miner
is never looked for (a fake check)."""
import os
import zipfile

import pytest

from app.connect import settings_panel, status
from tests import cli_helpers as h
from tests.connect_tk_helpers import Pump, Tips, on_main, read_settings, tk_root, widgets

NOT_INSTALLED = {"checks": [{"id": "anki_miner", "state": "needs-you", "say": "Anki Miner isn't installed."}],
                 "anki_miner": None}


@pytest.fixture
def root():
    r = tk_root()
    try:
        yield r
    finally:
        r.destroy()


def _panel(root, settings=None, language="ja", **kw):
    """The panel as the dashboard builds it: settings.json written first (as the user has it), the same dict shown."""
    on_disk = h.write_settings(connect_enabled=True, theme="Dark Flow", **(settings or {}))
    tips, pump = Tips(), Pump()
    panel = settings_panel.build(root, lambda: language, tips, dict(on_disk), checks=lambda s, lang: NOT_INSTALLED,
                                 post=pump.put, **kw)
    assert pump.run(root, lambda: panel.lbl_state.cget("text") == "Not installed")
    return panel, tips, pump, on_disk


def _written(before):
    """settings.json's keys that differ from `before` (added or changed) and the keys it lost."""
    after = read_settings()
    changed = {k: v for k, v in after.items() if before.get(k, object()) != v}
    lost = set(before) - set(after)
    return changed, lost


def test_each_control_writes_exactly_its_own_key(root):
    panel, _tips, _pump, before = _panel(root)

    panel.word_buttons["unknown"].invoke()
    assert _written(before) == ({"connect_mine_words": "unknown"}, set())
    before = read_settings()

    panel.chk_grammar.invoke()
    assert _written(before) == ({"connect_send_grammar": False}, set())
    before = read_settings()

    panel.combo_sync.set("Only at session start and Anki close")
    panel.combo_sync.event_generate("<<ComboboxSelected>>")
    root.update()
    assert _written(before) == ({"anki_sync_delay_min": "off"}, set())
    before = read_settings()

    panel.chk_open_anki.invoke()
    assert _written(before) == ({"connect_open_anki": True}, set())
    before = read_settings()

    panel.var_cap.set("150")
    panel._save_cap()
    assert _written(before) == ({"connect_backlog_cap": {"ja": 150, "zh": 300}}, set()), \
        "a number is every language's cap: Chinese keeps 300"
    before = read_settings()
    panel._save_cap()                       # the focus leaves the box again: unchanged, nothing written
    assert _written(before) == ({}, set())

    if panel.chk_reorder is not None:       # Junban's two automation switches (G1.2-15), shown with Junban only
        panel.chk_reorder.invoke()
        assert _written(before) == ({"junban_auto_reorder": True}, set())
        before = read_settings()
        panel.chk_backfill.invoke()
        assert _written(before) == ({"junban_auto_backfill": True}, set())


def test_a_cap_per_language_keeps_the_other_languages_own(root):
    panel, _tips, _pump, before = _panel(root, {"connect_backlog_cap": {"ja": 200, "zh": 80}}, language="zh")
    assert panel.var_cap.get() == "80", "Chinese shows its own cap"
    panel.var_cap.set("40")
    panel._save_cap()
    assert _written(before) == ({"connect_backlog_cap": {"ja": 200, "zh": 40}}, set())


def test_known_from_anki_is_an_and_of_the_picked_terms_and_none_is_off(root):
    panel, _tips, _pump, before = _panel(root, {"known_from_anki": ["suspended"]})
    assert panel.menu_known.cget("text") == "Suspended"
    labels = [panel.known_menu.entrycget(i, "label") for i in range(panel.known_menu.index("end") + 1)]
    assert labels[:2] == ["Suspended", "Marked"] and labels[2] == "Flag 1 (Red)" and len(labels) == 9

    panel.known_menu.invoke(labels.index("Marked"))
    assert _written(before) == ({"known_from_anki": ["suspended", "marked"]}, set()), "both must hold"
    assert panel.menu_known.cget("text") == "Suspended + Marked"

    panel.known_menu.invoke(labels.index("Suspended"))
    panel.known_menu.invoke(labels.index("Marked"))
    assert read_settings()["known_from_anki"] == [], "none picked: off"
    assert panel.menu_known.cget("text") == "Off"

    panel.known_menu.invoke(labels.index("Flag 3 (Green)"))
    panel.known_menu.invoke(labels.index("Suspended"))
    assert read_settings()["known_from_anki"] == ["suspended", "flag:3"], "in the setting's order"


def test_video_folders_change_only_this_languages_and_keep_chinese(root, tmp_path):
    added = str(tmp_path / "アニメ" / "ぼっち・ざ・ろっく")
    panel, _tips, _pump, before = _panel(root, {"connect_video_folders": {"zh": ["D:\\视频\\电视剧"]}},
                                         ask_folder=lambda: added)
    panel.btn_add_folder.invoke()
    assert _written(before) == ({"connect_video_folders": {"zh": ["D:\\视频\\电视剧"], "ja": [os.path.normpath(added)]}},
                                set())
    assert panel.list_folders.get(0, "end") == (os.path.normpath(added),)

    before = read_settings()
    panel.list_folders.selection_set(0)
    panel.btn_remove_folder.invoke()
    assert _written(before) == ({"connect_video_folders": {"zh": ["D:\\视频\\电视剧"], "ja": []}}, set())
    assert panel.list_folders.size() == 0


def test_a_plain_list_of_folders_converted_keeps_it_for_each_language(root, tmp_path):
    every = "D:\\Anime"
    added = str(tmp_path / "ドラマ")
    panel, _tips, _pump, before = _panel(root, {"connect_video_folders": [every]}, ask_folder=lambda: added)
    assert panel.list_folders.get(0, "end") == (every,), "a plain list is every language's"
    panel.btn_add_folder.invoke()
    assert read_settings()["connect_video_folders"] == {"ja": [every, os.path.normpath(added)], "zh": [every]}


def test_the_logs_zip_is_made_on_a_worker(root, tmp_path, monkeypatch):
    dest = str(tmp_path / "surasura-logs.zip")
    folder = status.logs_folder()
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "cli.log"), "w", encoding="utf-8") as f:
        f.write("2026-10-11 connect: 上層部 made\n")
    threads = []
    real = status.save_logs
    monkeypatch.setattr(status, "save_logs", lambda d: (threads.append(on_main()), real(d))[1])
    panel, _tips, pump, before = _panel(root, ask_save=lambda: dest)
    panel.btn_save_logs.invoke()
    assert pump.run(root, lambda: panel.logs_note.cget("text").startswith("Saved"))
    assert threads == [False], "never on the Tk thread"
    with zipfile.ZipFile(dest) as z:
        assert "logs/cli.log" in [n.replace("\\", "/") for n in z.namelist()]
    assert _written(before) == ({}, set()), "saving logs writes no setting"


def test_every_button_and_toggle_has_a_tooltip(root):
    from tkinter import ttk
    panel, tips, _pump, _before = _panel(root)
    controls = widgets(panel.frame, (ttk.Button, ttk.Checkbutton, ttk.Radiobutton, ttk.Menubutton, ttk.Combobox,
                                     ttk.Spinbox)) + widgets(panel.card_frame, (ttk.Button,))
    assert len(controls) >= 10
    missing = [str(w) for w in controls if not tips.has(w)]
    assert missing == []


# --- the review's rows (P3.1 W3) -----------------------------------------------------------------------------------

def test_a_save_that_fails_puts_each_control_back_and_says_why(root, monkeypatch):
    """H4: settings.json not written (the disk refusing) → the control shows the value still saved, and the reason."""
    from app import settings_manager
    panel, _tips, _pump, before = _panel(root, {"connect_backlog_cap": {"ja": 200, "zh": 80}})
    monkeypatch.setattr(settings_manager, "save_settings", lambda *a, **k: False)
    panel.word_buttons["i1"].invoke()
    assert panel.var_words.get() == "list"
    panel.chk_grammar.invoke()
    assert panel.var_grammar.get() is True
    panel.combo_sync.set("Right away")
    panel.combo_sync.event_generate("<<ComboboxSelected>>")
    root.update()
    assert panel.combo_sync.get() == "About a minute after"
    panel.var_cap.set("40")
    panel._save_cap()
    assert panel.var_cap.get() == "200"
    labels = [panel.known_menu.entrycget(i, "label") for i in range(panel.known_menu.index("end") + 1)]
    panel.known_menu.invoke(labels.index("Marked"))
    assert panel.known_vars["marked"].get() is False and panel.menu_known.cget("text") == "Suspended"
    assert panel.save_note.cget("text").startswith("Not saved: your settings file couldn't be written")
    assert panel.save_note.winfo_manager() == "pack"
    assert read_settings() == before


def test_the_value_shown_picked_again_writes_nothing(root):
    """IK11 (S19): re-picking the radio or the combo's shown value never rewrites settings.json."""
    from tests.connect_tk_helpers import settings_bytes
    panel, _tips, _pump, _before = _panel(root)
    first = settings_bytes()
    panel.word_buttons["list"].invoke()             # the default, shown: the key isn't in the file
    panel.combo_sync.set("About a minute after")
    panel.combo_sync.event_generate("<<ComboboxSelected>>")
    root.update()
    assert settings_bytes() == first and "connect_mine_words" not in read_settings()


def test_a_sync_value_settings_doesnt_offer_is_shown_as_itself_and_kept(root):
    """IK14: 順's "5 minutes after" (5) shows as itself, never as "About a minute after", and stays until another is
    picked."""
    from tests.connect_tk_helpers import settings_bytes
    panel, _tips, _pump, _before = _panel(root, {"anki_sync_delay_min": 5})
    assert panel.combo_sync.get() == "5 minutes after"
    assert "5 minutes after" in panel.combo_sync.cget("values")
    first = settings_bytes()
    panel.combo_sync.event_generate("<<ComboboxSelected>>")
    root.update()
    assert settings_bytes() == first, "picked again: kept, nothing written"
    panel.combo_sync.set("Right away")
    panel.combo_sync.event_generate("<<ComboboxSelected>>")
    root.update()
    assert read_settings()["anki_sync_delay_min"] == 0


def test_the_cap_and_the_folders_keep_another_languages_newer_value(root, tmp_path):
    """H15 / IK13 (D31): the panel's snapshot is older than the file — Chinese's cap and folders saved meanwhile (another
    window, another program) are kept when Japanese's change."""
    from app import settings_manager
    added = os.path.normpath(str(tmp_path / "アニメ"))
    panel, _tips, _pump, _before = _panel(root, {"connect_backlog_cap": {"ja": 200, "zh": 80},
                                                 "connect_video_folders": {"zh": ["D:\视频"]}},
                                          ask_folder=lambda: added)
    settings_manager.save_keys({"connect_backlog_cap": {"ja": 200, "zh": 120},
                                "connect_video_folders": {"zh": ["D:\视频", "E:\电视剧"]}})
    panel.var_cap.set("150")
    panel._save_cap()
    panel.btn_add_folder.invoke()
    saved = read_settings()
    assert saved["connect_backlog_cap"] == {"ja": 150, "zh": 120}
    assert saved["connect_video_folders"] == {"zh": ["D:\视频", "E:\电视剧"], "ja": [added]}


def test_the_whitelist_path_and_junban_are_looked_up_on_a_worker(root, monkeypatch):
    """H13 / H12: the whitelist's path makes its folder, Junban's presence is a file look: never the Tk thread."""
    from app.connect import anki_miner
    threads = []
    real = anki_miner.whitelist_path
    monkeypatch.setattr(anki_miner, "whitelist_path", lambda lang: (threads.append(("path", on_main())),
                                                                    real(lang))[1])
    monkeypatch.setattr(settings_panel, "junban_present", lambda: (threads.append(("junban", on_main())), True)[1])
    needs_setup = {"checks": [{"id": "anki_miner", "state": "ok"}, {"id": "anki_miner_version", "state": "ok"},
                              {"id": "anki_miner_profile", "state": "needs-you", "say": "No Surasura profile."}],
                   "anki_miner": {"path": "C:\\AnkiMiner.exe","app": "3.6.0"}}
    h.write_settings(connect_enabled=True)
    pump = Pump()
    panel = settings_panel.build(root, lambda: "ja", Tips(), {"connect_enabled": True},
                                 checks=lambda s, lang: needs_setup, post=pump.put)
    assert pump.run(root, lambda: panel.lbl_state.cget("text") != "Checking…")
    assert sorted(threads) == [("junban", False), ("path", False)]
    assert panel.chk_reorder is not None, "Junban found: its two switches show"


def test_the_stars_answer_never_raises(monkeypatch):
    """H5: even the local data folder unreachable (`star_path` itself failing) is printed, not raised."""
    def unreachable():
        raise RuntimeError("no local data folder")
    monkeypatch.setattr(settings_panel, "star_path", unreachable)
    assert settings_panel.answer_star("not-now") is False


@pytest.mark.parametrize("platform,command", [("darwin", "open"), ("linux", "xdg-open")])
def test_a_folder_opens_on_macos_and_linux_too(monkeypatch, platform, command):
    """IK12 (S17): `os.startfile` is Windows-only; the dashboard's own branches elsewhere."""
    import subprocess
    import sys
    opened = []
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(subprocess, "Popen", lambda args: opened.append(args))
    settings_panel.open_path("/home/learner/logs")
    assert opened == [[command, "/home/learner/logs"]]

"""Settings -> Language & Parsing: the "How parsing works" link opens the one-page guide (docs/How Parsing Works.md)
on GitHub, as the footer's Tutorial link opens docs/Tutorial.md. The page must exist in this repository under the name
the link opens — renaming one without the other breaks this test, not the link a learner clicks."""

import os
from unittest.mock import patch
from urllib.parse import unquote, urlparse

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GITHUB = "https://github.com/SonicSandbox/surasura/blob/main/"


def _main():
    """app.main as it is now: some toggle tests reload it with a mocked tkinter, so it is imported in each test, never
    once at the top of this file."""
    import app.main as main_module
    return main_module


def _opened_url():
    """The address the link hands the browser (no browser is started)."""
    main_module = _main()
    with patch.object(main_module.webbrowser, "open") as opened:
        main_module.MasterDashboardApp.open_parsing_guide(None)
    opened.assert_called_once()
    return opened.call_args[0][0]


def test_the_link_opens_the_guide_page_this_repository_ships():
    # The address names a file in docs/ that exists here: GitHub serves it once it is pushed.
    url = _opened_url()
    assert url.startswith(GITHUB), url
    page = unquote(urlparse(url).path).split("/blob/main/", 1)[1]
    assert page == "docs/How Parsing Works.md"
    assert os.path.isfile(os.path.join(REPO, page)), "the page the link opens is missing from docs/"


def test_a_browser_that_will_not_open_shows_a_message_instead_of_crashing():
    main_module = _main()
    with patch.object(main_module.webbrowser, "open", side_effect=OSError("no browser")), \
            patch.object(main_module.messagebox, "showerror") as shown:
        main_module.MasterDashboardApp.open_parsing_guide(None)
    shown.assert_called_once()
    assert "parsing guide" in shown.call_args[0][1]


def test_the_link_sits_under_the_parsing_switches_with_its_tooltip(monkeypatch):
    # Right below the one-kanji switch, the last of the parsing switches, for Japanese and Chinese alike; styled and
    # clicked like the footer's Tutorial link. The Chinese "Script:" tooltip says what Traditional writes since 2.4:
    # Taiwan's standard characters.
    import tkinter as tk
    from tkinter import ttk

    main_module = _main()
    real_tooltip, tipped = main_module.ToolTip, {}

    def recording(widget, text, *args, **kwargs):
        tipped[str(widget)] = text
        return real_tooltip(widget, text, *args, **kwargs)

    monkeypatch.setattr(main_module, "ToolTip", recording)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk is not available in this environment")
    root.withdraw()
    monkeypatch.setattr(tk, "_default_root", root)      # the dashboard's Tk variables belong to the default root
    try:
        with patch.object(main_module.MasterDashboardApp, "check_updates_thread"):
            app = main_module.MasterDashboardApp(root)
        app.create_settings_window()
        link = app.lbl_parsing_guide
        assert isinstance(link, ttk.Label) and link.cget("text") == "How parsing works"
        assert str(link.cget("style")) == "Link.TLabel" and str(link.cget("cursor")) == "hand2"
        assert "one-page guide" in tipped[str(link)], "the link has its tooltip"
        assert link.bind("<Button-1>"), "a click opens the guide"

        shown = link.master.pack_slaves()
        assert shown[shown.index(link) - 1].cget("text") == "List one-kanji words only when they're dictionary words"
        for language in ("zh", "ja"):
            app.var_language.set(language)
            assert link.winfo_manager() == "pack", "the guide covers both languages"

        script_tip = next(text for text in tipped.values()            # some tooltips are made when shown (a function)
                          if isinstance(text, str) and text.startswith("Read all Chinese content"))
        assert "Taiwan's standard characters" in script_tip and "rather than Taiwan" not in script_tip
    finally:
        root.destroy()

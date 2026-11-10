# SPDX-License-Identifier: GPL-3.0-or-later
"""YouTube Transcript Downloader — optional, self-contained Surasura module.

Pulls clean .txt transcripts from YouTube into the active language's Processed
folder. Lazy-imported behind a settings toggle; the app runs normally if absent.

This package owns its own settings (SETTINGS_DEFAULTS) and its launch entry points
(open_downloader / open_preview), so the core app only needs thin, generic hooks —
mirroring how the Immersion Architect module attaches.
"""

# Default settings contributed to the app when this module is present. The core
# settings_manager merges these in at load time, so a build without the module never
# sees or persists them. All default off — the feature is strictly opt-in.
SETTINGS_DEFAULTS = {
    "enable_youtube_transcripts": True,   # shows the transcript downloader button — ON by default when
                                          # the module is bundled (users can turn it off in Settings)
    "enable_youtube_preview": False,      # shows the "Preview against library" button + freq-map cache
    "youtube_risk_acknowledged": False,   # one-time acknowledgment for the downloader
}


def open_downloader(host, language=None, on_complete=None):
    """Open (or focus) the YouTube transcript downloader window.

    Minimal host contract: `host` may be the MasterDashboardApp (main page) or any object exposing
    `.root` (e.g. the Content Manager). Pass `language` (a code like 'ja') to run host-agnostically —
    the GUI then reads/writes the risk-ack via settings_manager instead of the app. `on_complete`
    fires with the new Processed entries after a successful download, so a host can route them (the
    Content Manager copies them into the active tier).

    On 3.0 `host` may be the main window (Qt): the window is `qt_window`'s, imported only here, following the main
    window's language — `language` is not used there (the Qt window always downloads for the main window's language,
    AD4-16); `on_complete(paths)` is where its created files go (W3.2's arrivals seam)."""
    if _qt_host(host):
        from modules.youtube_downloader import qt_window
        return qt_window.open(host, on_complete=on_complete)
    from tkinter import messagebox
    try:
        from modules.youtube_downloader.gui import YoutubeDownloaderGui
        parent = getattr(host, "root", host)
        win = getattr(host, "youtube_window", None)
        if win is None or not win.winfo_exists():
            # Only bind the GUI to the app when no explicit language is given (the main-page path);
            # a language-driven caller stays decoupled from the app object.
            app = host if language is None else None
            host.youtube_window = YoutubeDownloaderGui(
                parent, app=app, language=language, on_complete=on_complete)
        else:
            win.lift()
    except Exception as e:
        print(f"Error launching YouTube Downloader: {e}")
        messagebox.showerror("Error", f"Could not launch YouTube Downloader:\n{e}")


def risk_words():
    """(3.0, alpha 8) The downloader's risk tick, as setup's page 3 shows it: (label, tip) — the window's own words."""
    from modules.youtube_downloader import qt_strings
    return qt_strings.RISK, qt_strings.RISK_TIP


def fetch_first(shell, urls, language, said, ended):
    """(3.0, alpha 8) Setup's *YouTube*: each link's first video brought in, in the background (`qt_window.fetch_first`:
    `said(line)`, then `ended(created, problems)`, on the window's thread). -> the job."""
    from modules.youtube_downloader import qt_window
    return qt_window.fetch_first(shell, urls, language, said, ended)


from modules.youtube_downloader.qt_strings import STOPPED  # noqa: E402  (3.0, alpha 8: a run's stop line, words only)


def playlist_link(url):
    """(3.0, alpha 8) The YouTube playlist a pasted link names, as its page's address, or None (`downloader`'s)."""
    from modules.youtube_downloader import downloader
    return downloader.playlist_link(url)


def rest_waiting(language):
    """(3.0, alpha 8; a worker) Whether a playlist's rest, or transcripts not handed over yet, wait for this language."""
    import os
    from modules.youtube_downloader import downloader_view
    return os.path.exists(downloader_view.rest_path(language))


def bring_in_rest(shell, language, playlists=()):
    """(3.0, alpha 8) The rest of each playlist setup brought one video of, and of any an earlier run left unfinished,
    in the background (`qt_window.bring_in_rest`)."""
    from modules.youtube_downloader import qt_window
    return qt_window.bring_in_rest(shell, language, playlists)


def _qt_host(host):
    """The 3.0 main window (it carries the window's services and its bridge), not a Tk host (which has a `root`)."""
    return not hasattr(host, "root") and hasattr(host, "services") and hasattr(host, "bridge")


def open_preview(app):
    """Open the 'preview against library' flow, running a full analysis first if there's no cache.

    On 3.0 `app` may be the main window (Qt): the window is `qt_preview`'s, imported only here; it opens at once and
    asks for a Generate itself when there is no list for its language yet."""
    if _qt_host(app):
        from modules.youtube_downloader import qt_preview
        return qt_preview.open(app)
    from tkinter import messagebox
    try:
        from modules.youtube_downloader import preview as yt_preview
    except Exception as e:
        messagebox.showerror("Error", f"Could not load the Preview module:\n{e}")
        return
    if yt_preview.has_library_cache():
        _launch_preview_dialog(app)
        return
    # No cache yet: run a full analysis first, then open the preview when it's ready.
    messagebox.showinfo("Preparing preview",
                        "No analysis cache yet — running a full analysis first.\n"
                        "The preview will open automatically when it's ready.")
    app.run_analyzer()
    _poll_preview_cache(app)


def _poll_preview_cache(app, tries=0):
    try:
        from modules.youtube_downloader import preview as yt_preview
    except Exception:
        return
    if yt_preview.has_library_cache():
        _launch_preview_dialog(app)
    elif tries < 600:  # poll up to ~10 minutes while the analysis runs
        app.root.after(1000, lambda: _poll_preview_cache(app, tries + 1))


def _launch_preview_dialog(app):
    from tkinter import messagebox
    try:
        from modules.youtube_downloader.preview_gui import PreviewGui
        win = getattr(app, "preview_window", None)
        if win is None or not win.winfo_exists():
            app.preview_window = PreviewGui(app.root, app=app)
        else:
            win.lift()
    except Exception as e:
        print(f"Error launching Preview: {e}")
        messagebox.showerror("Error", f"Could not launch Preview:\n{e}")

# SPDX-License-Identifier: GPL-3.0-or-later
"""
Surasura-branded "Preview against library" dialog.

Clean and minimal: header, a prompt, one link field (Submit also fires on Enter),
and an off-by-default "add to front" toggle. Paste a video or playlist link; it
fetches the transcript(s), scores them against your cached library, and opens a
single-file Vocab-Journey preview that reuses the report UX (ignore/completed/sort).
"""

import os
import glob
import queue
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

from . import preview
from . import downloader as core
from . import ytdlp_manager

BG = '#1e1e1e'
SURFACE = '#2d2d2d'
TEXT = '#e0e0e0'
MUTED = '#9a9a9a'
ACCENT = '#bb86fc'
SECONDARY = '#03dac6'


class ToolTip:
    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 25
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, justify=tk.LEFT, background=SURFACE, foreground=TEXT,
                 relief=tk.SOLID, borderwidth=1, wraplength=220 if len(self.text) > 50 else 0,
                 padx=6, pady=4).pack()

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class PreviewGui(tk.Toplevel):
    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        self.q = queue.Queue()
        self.busy = False
        self._pl_answer = None

        self.lang = self._target_lang()
        self.lang_name = core.LANG_BY_CODE.get(self.lang, core.DEFAULT_LANG)

        self.title("Preview Against Library")
        self.configure(bg=BG)
        self.geometry("560x300")
        self.minsize(480, 280)
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._init_styles()
        self._build_ui()
        self.after(100, self._drain)

    def _target_lang(self):
        try:
            if self.app is not None:
                return self.app.var_language.get() or 'ja'
            from app import settings_manager
            return settings_manager.load_settings().get('target_language', 'ja')
        except Exception:
            return 'ja'

    def _init_styles(self):
        # ttk styles are process-global: only claim the base theme when standalone, else inherit the
        # host's (main app / Content Manager) so we never clobber it. Our P.* named styles paint this
        # window regardless. See app/ui_theme.ensure_styleable_theme.
        from app.ui_theme import ensure_styleable_theme
        style = ttk.Style(self)
        if ensure_styleable_theme(self):
            style.configure(".", background=BG, foreground=TEXT, fieldbackground=SURFACE, font=('Segoe UI', 10))
        style.configure("P.TFrame", background=BG)
        style.configure("P.TLabel", background=BG, foreground=TEXT)
        style.configure("PMuted.TLabel", background=BG, foreground=MUTED)
        style.configure("PHeader.TLabel", background=BG, foreground=SECONDARY, font=('Segoe UI', 16, 'bold'))
        style.configure("PState.TLabel", background=BG, foreground=SECONDARY, font=('Segoe UI', 9, 'bold'))
        style.configure("PDialogTitle.TLabel", background=BG, foreground=SECONDARY, font=('Segoe UI', 13, 'bold'))
        style.configure("P.TCheckbutton", background=BG, foreground=TEXT)
        style.map("P.TCheckbutton", background=[('active', BG)], foreground=[('active', ACCENT)])
        style.configure("P.TButton", background=SURFACE, foreground=TEXT, borderwidth=0,
                        padding=8, font=('Segoe UI', 10, 'bold'))
        style.map("P.TButton", background=[('active', ACCENT), ('pressed', ACCENT)],
                  foreground=[('active', BG), ('pressed', BG)])
        style.configure("P.TEntry", fieldbackground=SURFACE, foreground=TEXT, insertcolor=TEXT)

    def _build_ui(self):
        wrap = ttk.Frame(self, style="P.TFrame")
        wrap.pack(fill='both', expand=True, padx=18, pady=16)

        ttk.Label(wrap, text="Preview Against Library", style="PHeader.TLabel",
                  anchor='center').pack(fill='x')
        ttk.Label(wrap, text="Paste a YouTube or bilibili.tv link (video, playlist or season) to see\n"
                             "its vocab journey, scored against your existing library — without a full re-run.",
                  style="PMuted.TLabel", anchor='center', justify='center').pack(fill='x', pady=(4, 14))

        self.link = tk.StringVar()
        entry = ttk.Entry(wrap, textvariable=self.link, style="P.TEntry", font=('Segoe UI', 11))
        entry.pack(fill='x', ipady=4)
        entry.bind("<Return>", lambda e: self.on_submit())
        entry.focus_set()

        self.add_front = tk.BooleanVar(value=False)
        chk = ttk.Checkbutton(wrap, text="Add transcript to the front of NOW (for future runs)",
                              variable=self.add_front, style="P.TCheckbutton")
        chk.pack(anchor='w', pady=(12, 0))
        ToolTip(chk, "Off by default. If on, the transcript is copied to HighPriority at position 1 "
                     "so future analyses include it first. It does NOT mark any words as known.")

        bar = ttk.Frame(wrap, style="P.TFrame")
        bar.pack(side='bottom', fill='x', pady=(14, 0))
        self.state_lbl = ttk.Label(bar, text="● Ready", style="PState.TLabel")
        self.state_lbl.pack(side='left')
        self.go = ttk.Button(bar, text="Preview", command=self.on_submit, style="P.TButton", width=14)
        self.go.pack(side='right')
        ToolTip(self.go, "Fetch the transcript and open its journey against your library.")

        self.status = ttk.Label(wrap, text="", style="PMuted.TLabel", anchor='w', justify='left', wraplength=500)
        self.status.pack(side='bottom', fill='x', pady=(10, 0))

    # ----------------------------------------------------------------- helpers
    def _set_state(self, busy):
        self.busy = busy
        self.go.config(state='disabled' if busy else 'normal')
        self.state_lbl.config(text="● Processing…" if busy else "● Ready",
                              foreground=ACCENT if busy else SECONDARY)

    def _status(self, text):
        self.q.put(("__STATUS__", text))

    def _ask_full_playlist(self, count):
        """Marshal a branded yes/no to the main thread; block the worker until answered."""
        ev = threading.Event()

        def ask():
            self._pl_answer = self._branded_choice(
                "Playlist detected",
                f"This link is a playlist ({count} videos).\n\n"
                "Preview the full playlist, or just this one video?\n\n"
                "Each video is scored on its own against your library, so a full "
                "playlist lets you compare them and pick the best.",
                "Full playlist", "Just this video")
            ev.set()
        self.after(0, ask)
        ev.wait()
        return self._pl_answer

    def _branded_choice(self, title, message, yes_text, no_text):
        """A dark, on-brand modal yes/no (replaces the plain OS dialog). True=yes, False=no/Esc."""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.resizable(False, False)
        result = {"v": False}

        def choose(v):
            result["v"] = v
            dlg.destroy()

        dlg.bind("<Escape>", lambda e: choose(False))
        dlg.protocol("WM_DELETE_WINDOW", lambda: choose(False))

        frame = ttk.Frame(dlg, style="P.TFrame")
        frame.pack(fill='both', expand=True, padx=20, pady=18)
        ttk.Label(frame, text=title, style="PDialogTitle.TLabel").pack(anchor='w')
        ttk.Label(frame, text=message, style="P.TLabel", justify='left',
                  wraplength=360).pack(anchor='w', pady=(8, 18))
        btns = ttk.Frame(frame, style="P.TFrame")
        btns.pack(fill='x')
        yes = ttk.Button(btns, text=yes_text, style="P.TButton", command=lambda: choose(True))
        yes.pack(side='right')
        ttk.Button(btns, text=no_text, style="P.TButton",
                   command=lambda: choose(False)).pack(side='right', padx=(0, 8))

        dlg.update_idletasks()
        px, py, pw, ph = self.winfo_rootx(), self.winfo_rooty(), self.winfo_width(), self.winfo_height()
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        dlg.geometry(f"+{max(px + (pw - dw) // 2, 0)}+{max(py + (ph - dh) // 3, 0)}")
        yes.focus_set()
        dlg.grab_set()
        self.wait_window(dlg)
        return result["v"]

    # ----------------------------------------------------------------- actions
    def on_submit(self):
        if self.busy:
            return
        url = self.link.get().strip()
        if not url:
            return
        if not preview.has_library_cache():
            messagebox.showinfo("Run analysis first",
                                "No analysis cache yet. Run 'Generate Journey' once, then try again.",
                                parent=self)
            return
        self._set_state(True)
        threading.Thread(target=self._run, args=(url, self.add_front.get()), daemon=True).start()

    def _run(self, url, add_front):
        try:
            if core.site_of(url) == 'bilibili.com':
                self.q.put(("__ERR__", "bilibili.com only gives subtitles to signed-in users. Open "
                                       "the same show on bilibili.tv and paste that link instead."))
                return
            vid = preview.extract_video_id(url)
            self._status("Looking up link…")
            info = core._probe(url, lambda *_: None)
            is_playlist = bool(info and (info.get('_type') == 'playlist' or info.get('entries') is not None))

            target_url, single = url, True
            if is_playlist:
                count = len(info.get('entries') or [])
                if vid:  # watch?v=...&list=... → let the user choose
                    if not self._ask_full_playlist(count):
                        target_url, single = f"https://www.youtube.com/watch?v={vid}", True
                    else:
                        single = False
                else:
                    single = False  # pure playlist

            if single and vid and preview.video_in_library(vid, self.lang):
                self.q.put(("__ERR__", "That video is already in your library — nothing to preview."))
                return

            self._status("Fetching transcript…")
            ws = preview.reset_workspace()
            if not ytdlp_manager.ensure_available(lambda *_: None):
                self.q.put(("__ERR__", "Could not get yt-dlp. Check your connection and try again."))
                return
            core.extract([target_url], ws, lang=self.lang_name, channel_first=True, log=lambda *_: None)
            txts = sorted(glob.glob(os.path.join(ws, "**", "*.txt"), recursive=True))
            if not txts:
                if core.site_of(url) == 'bilibili':
                    self.q.put(("__ERR__", "No transcript found — this episode may not be available "
                                           "in your region, or has no subtitles in your language."))
                else:
                    self.q.put(("__ERR__", "No transcript found (the video may have no captions in your language)."))
                return

            self._status("Scoring against your library…")
            files = []
            for t in txts:
                words, _ = preview.analyze_transcript(t, self.lang)
                # Carry the transcript path too, so a sentence from the video can be linked to the
                # exact moment it's spoken (via the cue sidecar sitting beside it).
                files.append((os.path.splitext(os.path.basename(t))[0], words, t))

            out_html = os.path.join(ws, "preview.html")
            preview.generate_preview_html(files, self.lang, out_html)

            if add_front:
                added = preview.commit_to_front(txts, self.lang)
                self._status(f"Added {len(added)} file(s) to the front of NOW.")

            self.q.put(("__OPEN__", out_html))
        except preview.PreviewError as e:
            self.q.put(("__ERR__", str(e)))
        except Exception as e:
            self.q.put(("__ERR__", f"Unexpected error: {e}"))
        finally:
            self.q.put(('__DONE__',))

    # ------------------------------------------------------------------- drain
    def _drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple) and item:
                    tag = item[0]
                    if tag == '__DONE__':
                        self._set_state(False)
                    elif tag == '__STATUS__':
                        self.status.config(text=item[1], foreground=MUTED)
                    elif tag == '__ERR__':
                        self.status.config(text=item[1], foreground='#cf6679')
                    elif tag == '__OPEN__':
                        self.status.config(text="Opened preview.", foreground=SECONDARY)
                        self._open_report(item[1])
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._drain)

    def _open_report(self, path):
        """Open the temp report in an app window if 'open_app_mode' is on, else the browser."""
        try:
            from app import settings_manager
            if settings_manager.load_settings().get("open_app_mode", False):
                from app.static_html_generator import open_as_app
                open_as_app(path)
                return
        except Exception:
            pass
        try:
            webbrowser.open(f"file://{os.path.abspath(path)}")
        except Exception:
            pass

    def _on_close(self):
        # Single self-cleaning workspace: wipe on close unless we committed to library.
        try:
            preview.cleanup_workspace()
        except Exception:
            pass
        self.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    root.withdraw()
    PreviewGui(root)
    root.mainloop()

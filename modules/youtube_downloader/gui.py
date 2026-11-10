# SPDX-License-Identifier: GPL-3.0-or-later
"""
Surasura-branded GUI for the YouTube Downloader module.

A dark-mode Toplevel matching the Surasura design language (palette, ttk button
behaviour, Esc-to-close, tooltips). Extraction runs in a background thread, queue-
logged to a compact activity box, with a live Ready / Processing state indicator.

Layout (top -> bottom): centered title, link input, options, compact activity log,
risk acknowledgment, Extract; a bottom bar carries the state on the left and small
Open-folder / Update icons on the right.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from app import settings_manager
from app.path_utils import get_data_path, ensure_data_setup
from . import ytdlp_manager
from . import downloader as core

# --- Surasura palette (GUI_Design_Guidelines.md) ---
BG = '#1e1e1e'
SURFACE = '#2d2d2d'
TEXT = '#e0e0e0'
MUTED = '#9a9a9a'
ACCENT = '#bb86fc'
SECONDARY = '#03dac6'
ERROR = '#cf6679'

RISK_TOOLTIP = (
    "Acknowledge before use. Downloading from YouTube or bilibili.tv can hit temporary "
    "rate-limits (HTTP 429) and is a gray area under their Terms of Service. Use only for your "
    "own personal, offline study — it's your responsibility."
)


class ToolTip:
    """Hover tooltip per the Surasura GUI guidelines (wraps long text)."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
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
        wrap = 220 if len(self.text) > 50 else 0
        tk.Label(tw, text=self.text, justify=tk.LEFT, background=SURFACE,
                 foreground=TEXT, relief=tk.SOLID, borderwidth=1,
                 wraplength=wrap, padx=6, pady=4).pack()

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class YoutubeDownloaderGui(tk.Toplevel):
    def __init__(self, parent, app=None, language=None, on_complete=None):
        """host-agnostic: pass `language` (a code like 'ja'/'zh') to run without the main app, and
        `on_complete(created_paths)` to be notified of the new Processed entries after a download
        (the Content Manager uses it to copy them into the active tier)."""
        super().__init__(parent)
        self.app = app
        self.language = language
        self.on_complete = on_complete
        self.q = queue.Queue()
        self.busy = False
        # Set on close so a long backfill stops asking YouTube for things nobody is waiting for.
        # A plain flag, because Tk calls aren't safe from the worker thread.
        self._closing = False

        self.title("Video Transcripts")
        self.configure(bg=BG)
        self.geometry("620x560")
        self.minsize(540, 500)
        self.bind("<Escape>", lambda e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._init_styles()
        self._build_ui()
        self.after(100, self._drain)

    def _close(self):
        """Closing the window also stops a running backfill — it's a background chore, and there is
        no reason to keep hitting YouTube once nobody is watching."""
        self._closing = True
        self.destroy()

    # ----------------------------------------------------------------- styling
    def _init_styles(self):
        """Brand the window with dark buttons that turn purple on hover.

        ttk styles are process-global, so we must NOT switch the theme when embedded in a host
        (main app / Content Manager) — that would clobber the host. We only claim the base theme
        when launched standalone; either way our own YT.* named styles are what paint this window."""
        from app.ui_theme import ensure_styleable_theme
        style = ttk.Style(self)
        if ensure_styleable_theme(self):
            style.configure(".", background=BG, foreground=TEXT, fieldbackground=SURFACE,
                            font=('Segoe UI', 10))

        # Dropdown (Listbox) colors so the combobox menu matches the dark theme
        self.option_add('*TCombobox*Listbox.background', SURFACE)
        self.option_add('*TCombobox*Listbox.foreground', TEXT)
        self.option_add('*TCombobox*Listbox.selectBackground', ACCENT)
        self.option_add('*TCombobox*Listbox.selectForeground', BG)

        style.configure("YT.TFrame", background=BG)
        style.configure("YT.TLabel", background=BG, foreground=TEXT)
        style.configure("YTMuted.TLabel", background=BG, foreground=MUTED)
        style.configure("YTHeader.TLabel", background=BG, foreground=SECONDARY,
                        font=('Segoe UI', 18, 'bold'))
        style.configure("YTState.TLabel", background=BG, foreground=SECONDARY,
                        font=('Segoe UI', 9, 'bold'))

        style.configure("YT.TCheckbutton", background=BG, foreground=TEXT,
                        indicatorbackground=SURFACE, indicatorforeground=BG, focuscolor=BG)
        style.map("YT.TCheckbutton",
                  background=[('active', BG)], foreground=[('active', ACCENT)],
                  indicatorbackground=[('selected', ACCENT), ('active', SURFACE)],
                  indicatorforeground=[('selected', BG)])

        # Brand button: SURFACE by default -> ACCENT (purple) on hover/press, text -> BG
        style.configure("YT.TButton", background=SURFACE, foreground=TEXT,
                        borderwidth=0, padding=8, font=('Segoe UI', 10, 'bold'))
        style.map("YT.TButton",
                  background=[('active', ACCENT), ('pressed', ACCENT)],
                  foreground=[('active', BG), ('pressed', BG)])

        # Same behaviour, tighter padding, for the small bottom-bar icon buttons
        style.configure("YTIcon.TButton", background=SURFACE, foreground=TEXT,
                        borderwidth=0, padding=4, font=('Segoe UI', 12))
        style.map("YTIcon.TButton",
                  background=[('active', ACCENT), ('pressed', ACCENT)],
                  foreground=[('active', BG), ('pressed', BG)])

        style.configure("YT.TCombobox", fieldbackground=SURFACE, background=SURFACE,
                        foreground=TEXT, arrowcolor=ACCENT,
                        selectbackground=SURFACE, selectforeground=TEXT)
        # selectbackground/foreground for 'readonly' stop the field going white-highlighted after a
        # selection (the readonly combobox otherwise shows the value as selected text).
        style.map("YT.TCombobox", fieldbackground=[('readonly', SURFACE)],
                  foreground=[('readonly', TEXT)],
                  selectbackground=[('readonly', SURFACE)],
                  selectforeground=[('readonly', TEXT)])

    # ----------------------------------------------------------------- helpers
    def _lang_code(self):
        """Active language code. An explicit `language` (host-agnostic caller) wins; otherwise fall
        back to the main app, then to the saved target language."""
        if self.language:
            return self.language
        try:
            if self.app is not None:
                return self.app.var_language.get() or 'ja'
            return settings_manager.load_settings().get('target_language', 'ja')
        except Exception:
            return 'ja'

    def _default_lang(self):
        return core.LANG_BY_CODE.get(self._lang_code(), core.DEFAULT_LANG)

    def _ack_get(self):
        if self.app is not None:
            return bool(getattr(self.app, 'youtube_risk_acknowledged', False))
        return bool(settings_manager.load_settings().get('youtube_risk_acknowledged', False))

    def _ack_set(self, value):
        if self.app is not None:
            self.app.youtube_risk_acknowledged = value
            try:
                self.app.save_settings()
            except Exception:
                pass
        else:
            # Only this key, onto settings.json as it is: saving every loaded default wrote the other
            # modules' keys too (and put back retired ones, each a full Generate).
            settings_manager.save_keys({'youtube_risk_acknowledged': value})

    def _output_dir(self):
        code = self._lang_code()
        ensure_data_setup(code)
        return os.path.join(get_data_path(code), "Processed")

    # -------------------------------------------------------------------- view
    def _build_ui(self):
        wrap = ttk.Frame(self, style="YT.TFrame")
        wrap.pack(fill='both', expand=True, padx=16, pady=14)

        # --- Centered title + subtitle (TOP) ---
        ttk.Label(wrap, text="Video Transcripts", style="YTHeader.TLabel",
                  anchor='center').pack(fill='x')
        ttk.Label(wrap, text="Paste one link per line — YouTube videos, lists and playlists, "
                             "or bilibili.tv episodes and seasons.",
                  style="YTMuted.TLabel", anchor='center').pack(fill='x', pady=(2, 12))

        # --- Link input ---
        self.input = tk.Text(wrap, height=6, bg=SURFACE, fg=TEXT, insertbackground=TEXT,
                             relief='flat', highlightthickness=1, highlightbackground=SURFACE,
                             highlightcolor=ACCENT, font=("Consolas", 10), wrap='none',
                             padx=8, pady=8)
        self.input.pack(fill='x')

        # --- Options ---
        row = ttk.Frame(wrap, style="YT.TFrame")
        row.pack(fill='x', pady=12)

        ttk.Label(row, text="Language", style="YTMuted.TLabel").pack(side='left')
        self.lang = tk.StringVar(value=self._default_lang())
        lang_box = ttk.Combobox(row, textvariable=self.lang, values=list(core.LANGS.keys()),
                                state='readonly', width=10, style="YT.TCombobox")
        lang_box.pack(side='left', padx=(6, 16))
        # Drop focus after a pick so the value isn't left visually selected/highlighted.
        lang_box.bind("<<ComboboxSelected>>", lambda e: self.focus_set())
        ToolTip(lang_box, "Which captions to pull (manual → auto → auto-translated).")

        self.keep_ts = tk.BooleanVar(value=False)
        chk_ts = ttk.Checkbutton(row, text="Keep timestamps", variable=self.keep_ts, style="YT.TCheckbutton")
        chk_ts.pack(side='left')
        ToolTip(chk_ts, "Off = clean flowing text (best for analysis). On = one line per cue with [HH:MM:SS].")

        self.channel_first = tk.BooleanVar(value=True)
        chk_ch = ttk.Checkbutton(row, text="Channel name first", variable=self.channel_first, style="YT.TCheckbutton")
        chk_ch.pack(side='left', padx=(12, 0))
        ToolTip(chk_ch, "Prefix filenames with the channel so files sort together by uploader. "
                        "(YouTube only — bilibili.tv names no uploader; a season gets its own folder.)")

        # --- Activity label (the log itself is packed last so it fills the middle) ---
        ttk.Label(wrap, text="Activity", style="YTMuted.TLabel").pack(anchor='w')

        # --- Bottom bar: state (left) + Open-folder / Update icons (right) ---
        bottom = ttk.Frame(wrap, style="YT.TFrame")
        bottom.pack(side='bottom', fill='x', pady=(12, 0))

        self.state_lbl = ttk.Label(bottom, text="● Ready", style="YTState.TLabel")
        self.state_lbl.pack(side='left')

        btn_update = ttk.Button(bottom, text="⟳", command=self.on_update, style="YTIcon.TButton", width=3)
        btn_update.pack(side='right')
        ToolTip(btn_update, "Update the downloader engine (yt-dlp). Use this if extraction stops working.")

        btn_cues = ttk.Button(bottom, text="⏱", command=self.on_backfill,
                              style="YTIcon.TButton", width=3)
        btn_cues.pack(side='right', padx=(0, 6))
        ToolTip(btn_cues, "Fetch cue times for transcripts downloaded before this feature, so the "
                          "report can jump to the right moment in the video. Only captions are "
                          "re-fetched — your transcripts are never rewritten.")

        btn_open = ttk.Button(bottom, text="📂", command=self.open_output, style="YTIcon.TButton", width=3)
        btn_open.pack(side='right', padx=(0, 6))
        ToolTip(btn_open, "Open the Processed folder where transcripts are saved.")

        # --- Extract (below the log) ---
        actions = ttk.Frame(wrap, style="YT.TFrame")
        actions.pack(side='bottom', fill='x', pady=(10, 0))
        self.go = ttk.Button(actions, text="Extract", command=self.on_extract, style="YT.TButton", width=16)
        self.go.pack(side='right')
        ToolTip(self.go, "Download transcripts into your Processed folder.")

        # --- Risk acknowledgment (below the log) ---
        self.risk_ack = tk.BooleanVar(value=self._ack_get())
        self.risk_ack.trace_add("write", self._on_ack_toggle)
        chk_risk = ttk.Checkbutton(
            wrap, text="I understand the risks of downloading transcripts from YouTube and bilibili.tv",
            variable=self.risk_ack, style="YT.TCheckbutton")
        chk_risk.pack(side='bottom', anchor='w', pady=(10, 0))
        ToolTip(chk_risk, RISK_TOOLTIP)

        # --- Compact activity log (fills the space between options and the controls) ---
        self.log = tk.Text(wrap, height=5, bg=SURFACE, fg=TEXT, relief='flat',
                           highlightthickness=1, highlightbackground=SURFACE,
                           font=("Consolas", 9), wrap='word', padx=8, pady=8, state='disabled')
        self.log.pack(fill='both', expand=True, pady=(4, 0))

        self._sync_extract_state()

    # ------------------------------------------------------------------- state
    def _set_state(self, busy):
        if busy:
            self.state_lbl.config(text="● Processing…", foreground=ACCENT)
        else:
            self.state_lbl.config(text="● Ready", foreground=SECONDARY)

    def _on_ack_toggle(self, *_):
        self._ack_set(bool(self.risk_ack.get()))
        self._sync_extract_state()

    def _sync_extract_state(self):
        ok = bool(self.risk_ack.get()) and not self.busy
        self.go.config(state='normal' if ok else 'disabled')

    # ----------------------------------------------------------------- actions
    def open_output(self):
        out = self._output_dir()
        os.makedirs(out, exist_ok=True)
        try:
            os.startfile(out)  # Windows
        except AttributeError:
            import subprocess, sys
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', out])

    def on_extract(self):
        if self.busy:
            return
        if not self.risk_ack.get():
            messagebox.showwarning("Acknowledgment required",
                                   "Please acknowledge the risks before downloading.")
            return
        urls = [u for u in self.input.get('1.0', 'end').splitlines() if u.strip()]
        if not urls:
            self._write("Paste at least one YouTube or bilibili.tv link first.\n")
            return
        self.busy = True
        self._sync_extract_state()
        self._set_state(True)
        self._clear()
        threading.Thread(target=self._run_extract, args=(urls,), daemon=True).start()

    def _run_extract(self, urls):
        created = []
        try:
            exe = ytdlp_manager.ensure_available(self.q.put)
            if not exe:
                self.q.put("Cannot proceed without yt-dlp.")
                return
            out = self._output_dir()
            before = set(os.listdir(out)) if os.path.isdir(out) else set()
            core.extract(urls, out, lang=self.lang.get(),
                         keep_timestamps=self.keep_ts.get(),
                         channel_first=self.channel_first.get(), log=self.q.put)
            after = set(os.listdir(out)) if os.path.isdir(out) else set()
            created = [os.path.join(out, name) for name in sorted(after - before)]
        except Exception as e:
            self.q.put(f"\nUnexpected error: {e}")
        finally:
            # Carry the new Processed entries so a host (e.g. the Content Manager) can route them
            # into the active tier. Update runs emit a bare ('__DONE__',) so on_complete stays quiet.
            self.q.put(('__DONE__', created))

    def on_backfill(self):
        """Repair transcripts downloaded before cue sidecars existed. No risk acknowledgment gate:
        nothing new is downloaded, only cue timings for files already on disk.

        Confirms first — this is one network round-trip per video, so a large library is a long,
        rate-limit-prone run, and the count is the only way to know that up front."""
        if self.busy:
            return
        try:
            from app.path_utils import get_data_path
            pending = core.find_transcripts_missing_cues(get_data_path(self._lang_code()))
        except Exception as e:
            messagebox.showerror("Error", f"Could not scan for transcripts:\n{e}")
            return
        if not pending:
            self._write("Every transcript already has its cue times — nothing to backfill.\n")
            return
        n = len(pending)
        # Rough wall-clock: a request plus its pause, and a longer rest between batches.
        minutes = max(1, round((n * (core.REQUEST_PAUSE + 2.0)
                                + (n // core.BATCH_SIZE) * core.BATCH_PAUSE) / 60))
        if not messagebox.askyesno(
                "Fetch cue times",
                f"{n} transcript(s) have no cue times yet.\n\n"
                f"Surasura will re-fetch their captions from YouTube in batches of "
                f"{core.BATCH_SIZE}, pausing in between so we don't get rate-limited. "
                f"Rough estimate: {minutes} minute(s).\n\n"
                "You can close this window at any point to stop — finished ones are saved, and "
                "running it again picks up where it left off. Your transcripts themselves are "
                "never changed.\n\nStart?"):
            return
        self.busy = True
        self._sync_extract_state()
        self._set_state(True)
        self._clear()
        threading.Thread(target=self._run_backfill, daemon=True).start()

    def _run_backfill(self):
        try:
            if not ytdlp_manager.ensure_available(self.q.put):
                self.q.put("Cannot proceed without yt-dlp.")
                return
            # The WHOLE language folder, not just Processed: the copy the analyzer reads lives in a
            # tier, so that's the one that needs the sidecar beside it.
            from app.path_utils import get_data_path
            core.backfill_cues(get_data_path(self._lang_code()), lang=self.lang.get(),
                               log=self.q.put, should_stop=lambda: self._closing)
        except Exception as e:
            self.q.put(f"Backfill error: {e}")
        finally:
            # A bare __DONE__ so on_complete stays quiet — no new content was created.
            self.q.put(('__DONE__',))

    def on_update(self):
        if self.busy:
            return
        self.busy = True
        self._sync_extract_state()
        self._set_state(True)
        threading.Thread(target=self._run_update, daemon=True).start()

    def _run_update(self):
        try:
            ytdlp_manager.update(self.q.put)
        except Exception as e:
            self.q.put(f"Update error: {e}")
        finally:
            self.q.put(('__DONE__',))

    # ------------------------------------------------------------ log plumbing
    def _drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple) and item and item[0] == '__DONE__':
                    self.busy = False
                    self._sync_extract_state()
                    self._set_state(False)
                    created = item[1] if len(item) > 1 else None
                    if created and self.on_complete:
                        try:
                            self.on_complete(created)
                        except Exception:
                            pass
                else:
                    self._write(str(item) + '\n')
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._drain)

    def _write(self, text):
        self.log.config(state='normal')
        self.log.insert('end', text)
        self.log.see('end')
        self.log.config(state='disabled')

    def _clear(self):
        self.log.config(state='normal')
        self.log.delete('1.0', 'end')
        self.log.config(state='disabled')


if __name__ == '__main__':
    root = tk.Tk()
    root.withdraw()
    YoutubeDownloaderGui(root)
    root.mainloop()

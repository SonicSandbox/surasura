# SPDX-License-Identifier: GPL-3.0-or-later
""""Put Anki back the way it was before Surasura…" — the one flow behind both doors (FT-RUNBOOK D8).

    plan (a worker)  ->  one confirm with the counts  ->  [the fields question]  ->  put back (a worker)  ->  a line

The doors are 順's actions row and Settings → Data & System; both run `PutBack`, which is the seam 3.0's Qt
Settings takes at W3.3: it needs only a `post` that runs a callable on the UI thread, a `show` for a line, and
an `ask` of its own (`ask=` here; 順's themed dialog by default). Everything that reads or writes Anki lives in
`first_touch` (`plan` reads only, `put_back` writes); this file renders it and asks.

It keeps 順's rules (`gui.py`): nothing touches Tk from a worker, a dismissed question is a **no**, and Anki
closed, the wrong profile open or nothing kept is one plain line with nothing written. 順's own door refuses
while one of its runs is going (`JunbanGui.on_put_back`); Settings' door refuses while the 順 window is busy.

Imported lazily by `app/main.py` (try/except: Junban absent, the button is not shown), so the top of this file
imports nothing of Junban's but what it must.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk

# The text helpers live in `put_back_view` (Qt-free and Tk-free, so the 3.0 window shares them): imported here as
# they were defined, so every name of this module stays where it was.
from modules.junban.put_back_view import (ANKI_CLOSED, BUTTON_TEXT, BUTTON_TIP, NOTHING, NOTHING_LEFT,  # noqa: F401
                                          ONE_WAY, TITLE, _count, _date, _module, available, backfill_line,
                                          closing_lines, confirm_text, fields_question, older_question)


class PutBack:
    """One press of the button, from either door. Every callback but `post` runs on the UI thread.

    `post(fn)` runs `fn` on the UI thread (thread-safe); `show(line, tag)` writes one line; `busy(bool)`,
    `progress(done, total)` and `done(report)` are optional. `settings` is the dict to hand `first_touch`
    (read on the Tk thread by its door), or None to load it on the worker. `cancel` stops a wait for another Anki
    writer (the window closed); `on_wait(holder)` is called from the worker while it waits."""

    def __init__(self, parent, language, settings=None, post=None, show=None, busy=None, progress=None,
                 done=None, cancel=None, on_wait=None, ask=None):
        self.parent = parent
        self.language = language
        self.settings = settings
        self.post = post
        self.show = show or (lambda _line, _tag=None: None)
        self.busy = busy or (lambda _busy: None)
        self.progress = progress
        self.done = done
        self.cancel = cancel
        self.on_wait = on_wait
        self._ask = ask

    def ask(self, message, details=None, yes="Put back", no="Cancel", default=True):
        """A themed yes/no; `default` is what Enter answers (Esc and closing are always no)."""
        if self._ask is not None:
            return self._ask(message, details=details, yes=yes, no=no, default=default)
        from modules.junban import gui          # read at call time: the suites neuter `gui.ask`
        return gui.ask(self.parent, message, details=details, title=TITLE, yes=yes, no=no, default=default)

    def _settings(self):
        """The door's settings, or — read on the worker — the file's. C29: a file that can't be read gives Surasura's
        defaults (never an empty dict: the put-back reads Junban's address and tags from it), and says so."""
        if self.settings is not None:
            return dict(self.settings, target_language=self.language)
        from app import settings_manager
        try:
            loaded = settings_manager.load_settings(strict=True) or {}
        except Exception as e:
            line = f"Your settings couldn't be read ({e}): Surasura's defaults are used."
            self.post(lambda: self.show(line, "warning"))
            loaded = settings_manager.load_settings() or {}
        return dict(loaded, target_language=self.language)

    def start(self):
        self.busy(True)
        self.show("Reading Anki…")
        threading.Thread(target=self._plan_worker, daemon=True).start()

    # ------------------------------------------------------------------ workers
    def _plan_worker(self):
        try:
            if not _module().has_anything(self.language):
                result = {"ok": False, "nothing": True}
            else:
                settings = self._settings()
                result = _module().plan(settings, language=self.language)
                result = dict(result or {}, _settings=settings)
        except Exception as e:                  # a window must never lose its answer to a traceback
            result = {"ok": False, "problems": [str(e)]}
        self.post(lambda: self._planned(result))

    def _put_back_worker(self, settings, fields, older, plan):
        def progress(done, total):
            if self.progress is not None:
                self.post(lambda: self.progress(done, total))
        # `older` only when K4's question was asked: `plan` offers older changes only where `put_back` takes them.
        extra = {} if older is None else {"older": older}
        if (plan or {}).get("profile") is not None:     # C8: the profile the confirm was about, or nothing is written
            extra["profile"] = plan["profile"]
        try:
            report = _module().put_back(settings, language=self.language, fields=fields, progress=progress,
                                        wait=None, cancel=self.cancel, on_wait=self.on_wait, **extra)
        except Exception as e:
            report = {"ok": False, "message": "Nothing was put back.", "problems": [str(e)]}
        self.post(lambda: self._finished(report or {}, plan))

    # --------------------------------------------------------------- UI thread
    def _planned(self, plan):
        older = int(plan.get("older_suspended") or 0) + int(plan.get("older_tags") or 0)
        aside = list(plan.get("set_aside") or ())
        if aside:                               # K10: a broken order file was set aside (never deleted)
            self.show(f"{_count(len(aside), 'saved order')} couldn't be read and "
                      f"{'was' if len(aside) == 1 else 'were'} set aside: {', '.join(aside)}.", "warning")
        if plan.get("nothing") and not (plan.get("ok") and older):  # nothing kept, or all of it already back
            return self._end(NOTHING_LEFT if plan.get("ok") else NOTHING, "warning")
        if plan.get("anki_closed"):
            return self._end(ANKI_CLOSED, "problem")
        if plan.get("wrong_profile"):
            return self._end(f'Open the profile "{plan["wrong_profile"]}" in Anki first: nothing was changed.',
                              "problem")
        if not plan.get("ok"):
            problems = list(plan.get("problems") or ())
            for line in problems[:-1]:
                self.show(line, "problem")
            return self._end(problems[-1] if problems else "Nothing was changed.", "problem")
        question, details = confirm_text(plan)
        if not self.ask(question, details=details):
            return self._end("Nothing was changed.")
        fields = False
        if int(plan.get("fields_unedited") or 0):
            fields = bool(self.ask(fields_question(plan), yes="Put it back", no="Keep it"))
        older_answer = None
        if older:                               # K4: default No — Enter keeps them
            older_answer = bool(self.ask(older_question(plan), yes="Yes", no="No", default=False))
        self.show("Putting Anki back…")
        settings = plan.get("_settings") or self._settings()
        threading.Thread(target=self._put_back_worker, args=(settings, fields, older_answer, plan),
                         daemon=True).start()

    def _finished(self, report, plan=None):
        """`put_back`'s `message`, then K5 / K6's lines (`closing_lines`). A refusal's problem is its message: said
        once."""
        message = report.get("message") or ""
        for line in report.get("warnings") or ():
            self.show(line, "warning")
        for line in report.get("problems") or ():
            if line != message:
                self.show(line, "problem")
        self.show(message, "good" if report.get("ok") else "problem")
        for line in closing_lines(plan, report):
            self.show(line)
        self.busy(False)
        if self.done is not None:
            self.done(report)

    def _end(self, line, tag=None):
        self.show(line, tag)
        self.busy(False)
        if self.done is not None:
            self.done(None)


class PutBackWindow(tk.Toplevel):
    """Settings' door: a small window holding the flow's lines and progress. Esc closes it — and stops a wait for
    another Anki writer, as closing 順 does; a write already going finishes on its worker."""

    def __init__(self, parent, language):
        super().__init__(parent)
        from modules.junban.gui import ACCENT, BG, ERROR, SECONDARY, SURFACE, TEXT, ToolTip, init_styles
        self.q = queue.Queue()
        self._stop = threading.Event()
        self.busy = False
        self.title(f"Surasura - {TITLE}")
        self.configure(bg=BG)
        self.geometry("560x260")
        self.minsize(420, 200)
        self.bind("<Escape>", lambda _e: self._close())
        self.bind("<Destroy>", self._destroyed)         # C24: closed by its parent too, a waiting put-back stops
        self.protocol("WM_DELETE_WINDOW", self._close)
        init_styles(self)

        main = ttk.Frame(self, padding=10, style="Jun.TFrame")
        main.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main, text=BUTTON_TEXT, style="Jun.TLabel", wraplength=520).pack(anchor="w")
        row = ttk.Frame(main, style="Jun.TFrame")
        row.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        self.btn_close = ttk.Button(row, text="Close", width=12, style="Jun.TButton", command=self._close)
        self.btn_close.pack(side=tk.RIGHT)
        ToolTip(self.btn_close, "Close this window. A put-back already writing to Anki finishes first.")
        self.progress = ttk.Progressbar(main, style="Jun.Horizontal.TProgressbar", mode="determinate")
        self.progress.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        self.messages = tk.Text(main, height=6, bg=SURFACE, fg=TEXT, relief="flat", highlightthickness=1,
                                highlightbackground=SURFACE, font=("Consolas", 9), wrap="word", padx=8, pady=6,
                                state="disabled")
        self.messages.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.messages.tag_configure("problem", foreground=ERROR)
        self.messages.tag_configure("warning", foreground=ACCENT)
        self.messages.tag_configure("good", foreground=SECONDARY)

        self.flow = PutBack(self, language, post=self.q.put, show=self._write, busy=self._set_busy,
                            progress=self._show_progress, cancel=self._stop, on_wait=self._waiting)
        if not os.environ.get("SURASURA_NO_UI_TIMERS"):
            self.after(100, self._drain)

    def _close(self):
        self._stop.set()
        self.destroy()

    def _destroyed(self, event):
        if event.widget is self:
            self._stop.set()

    def _set_busy(self, busy):
        self.busy = busy

    def _show_progress(self, done, total):
        self.progress["maximum"] = max(1, total)
        self.progress["value"] = done

    def _waiting(self, holder):
        from app import anki_connect
        self.q.put(lambda: self._write(anki_connect.waiting_line(holder), "warning"))

    def _write(self, text, tag=None):
        if not text:
            return
        self.messages.config(state="normal")
        self.messages.insert("end", str(text) + "\n", (tag,) if tag else ())
        self.messages.see("end")
        self.messages.config(state="disabled")

    def _drain(self):
        self._drain_once()
        if self.winfo_exists():
            self.after(100, self._drain)

    def _drain_once(self):
        """Run what the workers posted, on the UI thread. Split out so a test can pump it. C30: a step that raises is
        shown, and the rest still run (the window never stops answering)."""
        while True:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                return
            if callable(item):
                try:
                    item()
                except Exception as e:
                    try:
                        self._write(f"Something went wrong showing this ({e}).", "problem")
                        self._set_busy(False)
                    except tk.TclError:
                        pass


def open_put_back(host):
    """Settings' door (`app/main.py`): the window for the dashboard's language, its flow started. Refused while
    the 順 window has a run of its own going (its answer would describe cards that run is moving). -> the window,
    or None when refused."""
    window = getattr(host, "junban_window", None)
    try:
        if window is not None and window.winfo_exists() and (window.busy or getattr(window, "_generating", False)):
            from tkinter import messagebox
            messagebox.showinfo(TITLE, "順 is working on your cards: try again once it has finished.",
                                parent=getattr(host, "settings_window", None) or getattr(host, "root", None))
            return None
    except tk.TclError:
        pass
    try:
        language = host.var_language.get() or "ja"
    except Exception:
        language = "ja"
    parent = getattr(host, "settings_window", None) or getattr(host, "root", host)
    put_back = PutBackWindow(parent, language)
    put_back.flow.start()
    return put_back

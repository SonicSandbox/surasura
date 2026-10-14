"""The Connect window (P3.1 row 3.1.6; P1.5 05-surface U3, 03-actors §4; RUNBOOK-P2.5 *The status contract*): one
Toplevel opened from the dashboard's Connect line or its *Needs you* badge, with three tabs and the Logs box.

- ***Needs you*** — each open need's sentence, its one action where its kind has one (*Show me how* · *How to check*
  · *Ask hato again*: hato's pairings back-filled on a worker, `hato.backfill`, P3.2; an untimed drop has none in
  2.x), its time and *Dismiss*; seen ones dimmed (*SEEN*), still listed. What is shown is marked seen
  (`status.mark_seen`, on a worker): the badge stops counting it.
- ***Batches*** — the finished batches with cards, newest first: title, cards made, not made by outcome, and ***Undo
  this batch***: the plan first (`undo.act`, nothing written), then Sonic's question — "Remove all of this episode's
  Anki cards that aren't studied?" with how many go, which stay and why, and the cards you had deleted yourself (they
  stay deleted) — then the undo, waiting while another program writes to Anki (Anki Miner holds Anki's write lock
  18–24 s a batch), then `undo.summary`'s words.
- ***Shelf*** — each restore point (cards, words, why, when, how many back) with *Put back* (none without Junban: the
  plain line instead), and the cards Surasura brought back today.
- **Logs** — *Open logs folder*, *Save logs to a file…*.
- **Anki Miner's update notice** (P3.2-AMN): *Anki Miner 3.8 is out* above the tabs while the record's
  `anki_miner_update` names one — a link to Anki Miner's releases page, as the dashboard's row shows it.

Every Connect call runs on a worker, never the Tk thread (the contract: an undo waits for Anki's write lock); the
window is only drawn from `after`. GUI_Design_Guidelines: the dark palette, ttk with this module's prefixed styles,
Esc closes, 10 px padding, a tooltip on every button. The tooltip is handed in: this module never imports app.main.
Imported only with Connect's preview on.
"""
import datetime
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

BG, SURFACE, TEXT, ACCENT, SECONDARY, ERROR = "#1e1e1e", "#2d2d2d", "#e0e0e0", "#bb86fc", "#03dac6", "#cf6679"
DIM = "#aaaaaa"
WRAP = 520
WAIT_FOR_WRITER_S = 120         # how long an undo keeps waiting for another program's Anki write (a few batches)
RETRY_GAP_S = 1.0               # at least this long between two tries while another program writes to Anki
QUESTION = "Remove all of this episode's Anki cards that aren't studied?"
WAITING = "Waiting for Anki: another program (Anki Miner?) is writing to it. Your undo goes on once it's done…"
UPDATE_WAITING = "Surasura is waiting to install an update; try again after it."
SETTINGS_UNREADABLE = "settings.json can't be read just now; try again."

# Each kind of need's one action: (button, what it does) — "logs" opens the logs folder; "hato" asks hato for its
# pairings again (`ask_hato`); text is shown under the entry
HOW = {
    "known-sync": ("Show me how", "Open Surasura's Anki window (the Anki button on the dashboard), choose the decks "
                                  "that hold the words you know, and press Sync now."),
    "generate": ("Show me how", "Press Generate on the dashboard. Connect goes on once the list is current."),
    "no-subtitle": ("Show me how", "Add the episode's subtitle to your library again in the Content Manager, or "
                                   "Dismiss this if you removed it on purpose."),
    "no-store": ("Show me how", "Open Surasura once (the dashboard) and let it finish starting, then wait for "
                                "Connect's next start. If it stays, close other Surasura programs."),
    "no-profile": ("Show me how", "Open Settings → Connect (preview): the Anki Miner card shows the steps."),
    "repick": ("How to check", "logs"),
    "mine-failed": ("How to check", "logs"),
    "error": ("How to check", "logs"),
    "no-pairing": ("Ask hato again", "hato"),
}
OUTCOMES = {"not_found": "not found", "no_definition": "no definition", "duplicate": "already a card",
            "uncertain": "not sure it was made", "media_failed": "media failed", "refused": "refused",
            "not_attempted": "not tried"}


def view(language):
    """The status record for `language` — read on a worker, never the Tk thread."""
    from app.connect import status
    return status.language_record(status.read([language]), language)


def when(utc_text):
    """A ledger's UTC time, as local `YYYY-MM-DD HH:MM`."""
    try:
        at = datetime.datetime.strptime(str(utc_text)[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return str(utc_text or "")
    return at.astimezone().strftime("%Y-%m-%d %H:%M")


def cards(n):
    """"1 card", "2 cards"."""
    return f"{n} card" if n == 1 else f"{n} cards"


def not_made_words(not_made):
    return ", ".join(f"{n} {OUTCOMES.get(o, o.replace('_', ' '))}" for o, n in sorted((not_made or {}).items()) if n)


def question(plan, at=None, others=()):
    """The confirm's words for an undo plan (`undo.summary` + {"language", "confirm": False}). `others`: the times of
    the episode's other batches in the list — then this batch's time (`at`) is named, and that the others stay."""
    lines = [QUESTION]
    if others:
        many = len(others) > 1
        lines.append(f"This batch was made {when(at)}. Its other batch{'es' if many else ''} "
                     f"({', '.join(when(o) for o in others)}) stay{'' if many else 's'}.")
    lines += ["", f"{cards(plan.get('delete', 0))} go{'es' if plan.get('delete', 0) == 1 else ''}."]
    keep = plan.get("keep") or []
    if keep:
        lines.append(f"{len(keep)} stay:")
        for entry in keep[:12]:
            lines.append(f"  {entry.get('word')}: {entry.get('why')}")
        if len(keep) > 12:
            lines.append(f"  … and {len(keep) - 12} more")
    if plan.get("gone"):
        lines.append(f"{plan['gone']} you had deleted yourself stay deleted.")
    lines += ["", "This can't be undone."]
    return "\n".join(lines)


def junban_present():
    """Is Junban installed (a file look: the caller's worker asks it, `show(..., junban=)`)."""
    from app.connect import setup
    return setup._present("modules.junban.reposition")


def wheel_scrolls(outer, canvas, can_scroll=lambda: True):
    """The wheel scrolls `canvas` while the pointer is over `outer` or anything in it: a bind tag on every widget under
    `outer` (Tk sends the parent a <Leave> as the pointer enters a child, so an Enter / Leave pair loses the wheel
    over the rows) — never `bind_all`, so no other window's wheel binding is touched. -> `tag_all`, to call again
    when widgets are added (bound to <Enter> here)."""
    tag = "Wheel" + str(canvas).replace(".", "_")
    canvas.bind_class(tag, "<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")
                      if can_scroll() else None)

    def tag_all(_e=None):
        stack = [outer]
        while stack:
            widget = stack.pop()
            tags = widget.bindtags()
            if tag not in tags:
                widget.bindtags(tags + (tag,))
            stack.extend(widget.winfo_children())
    outer.bind("<Enter>", tag_all, add="+")
    return tag_all


def _say(out):
    """An act's error or skip, in its plain words."""
    if isinstance(out, Exception):
        return getattr(out, "message", None) or str(out)
    if isinstance(out, dict) and out.get("skipped"):
        return f"Not done: {out['skipped']}."
    return None


def _busy_writer(out):
    return isinstance(out, Exception) and getattr(out, "code", None) == "busy" and \
        (getattr(out, "context", None) or {}).get("lock") == "anki-writer"


def writer_busy():
    """Does a live program hold Anki's write lock? A lock file this process can't open is no program: its refusal is
    said at once. Never raises."""
    try:
        from app import locks
        return locks.in_use("anki-writer") and locks.unopenable("anki-writer") is None
    except Exception:
        return False


def update_waits():
    """Is an update waiting to install (this dashboard's "Update now": no Anki write may begin)? Never raises."""
    try:
        from app import updater
        return updater.children_held()
    except Exception:
        return False


def wait_for_writer(call, on_wait, busy=None, update=None):
    """On a worker: `call()` (an `undo.act` that writes), tried again while a live program holds Anki's write lock —
    at least RETRY_GAP_S apart, for up to WAIT_FOR_WRITER_S, `on_wait()` called once, as the wait starts. A refusal no
    live program explains stops at once: an update waiting to install (UPDATE_WAITING), a lock file that can't be
    opened (the act's own words). The window's undo and put-back and the switch-off's put-back all wait here."""
    busy, update = busy or writer_busy, update or update_waits
    deadline = time.monotonic() + WAIT_FOR_WRITER_S
    said = False
    while True:
        if not said and busy():
            said = True
            on_wait()
        try:
            return call()
        except Exception as e:
            if not _busy_writer(e):
                raise
            if update():
                from app.cli.contract import CliError
                raise CliError("busy", UPDATE_WAITING, lock="anki-writer", held_by=None) from None
            if not busy() or time.monotonic() >= deadline:
                raise
        if not said:
            said = True
            on_wait()
        time.sleep(RETRY_GAP_S)


class ConnectWindow:
    """`record`: `view(language)`, read on the caller's worker. `act(settings, language, job=, shelf_run=,
    confirm=)`: `undo.act`; `settings()`: settings.json as it is now (read on the worker); `writer_busy()`: is Anki's
    write lock held by a live program; `update_waits()`: is an update waiting to install; `confirm(title, text)`: the
    question; `on_change()`: the dashboard's line reads again; `post(job)`: runs `job` on the Tk thread (the
    dashboard's queue); `open_url(url)`: the browser. Tests hand fakes for all of them."""

    def __init__(self, parent, language, tooltip, record, act=None, settings=None, writer_busy=None, confirm=None,
                 junban=None, on_change=None, logs_folder=None, save_logs=None, ask_save=None, mark_seen=None,
                 dismiss=None, post=None, update_waits=None, open_url=None):
        self.language, self.tooltip, self.record = language, tooltip, record or {}
        self._act, self._settings, self._writer_busy = act, settings, writer_busy
        self._update_waits = update_waits
        self.confirm = confirm or (lambda title, text: messagebox.askyesno(title, text, parent=self.win))
        self.junban = junban_present() if junban is None else junban
        self.on_change = on_change or (lambda: None)
        self._logs_folder, self._save_logs, self._mark_seen, self._dismiss = logs_folder, save_logs, mark_seen, dismiss
        self.ask_save = ask_save
        self._post = post
        self.open_url = open_url or webbrowser.open
        self.update_link = None     # P3.2-AMN: Anki Miner's notice, when there is one
        self.buttons = {}           # (tab, id, text) -> button: the tests press them
        self.notes = {}             # (tab, id) -> its note label
        win = self.win = tk.Toplevel(parent)
        win.title("Connect")
        win.configure(bg=BG)
        win.geometry("640x560")
        win.bind("<Escape>", lambda _e: win.destroy())
        self._style()
        frame = ttk.Frame(win, style="CW.TFrame", padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=self.record.get("line") or "Up to date", style="CW.Head.TLabel",
                  wraplength=WRAP).pack(anchor=tk.W, pady=(0, 8))
        self._update_notice(frame)
        close = ttk.Button(frame, text="Close", style="CW.TButton", command=win.destroy)
        close.pack(side=tk.BOTTOM, anchor=tk.E, pady=(8, 0))      # the bottom first: the tabs take what's left
        tooltip(close, "Close this window (Esc).")
        self._logs(frame)
        self.tabs = ttk.Notebook(frame, style="CW.TNotebook")
        self.tabs.pack(fill=tk.BOTH, expand=True)
        needs = self.record.get("needs") or []
        self._listed = {n["id"] for n in needs}                         # the tab's label follows the list
        self._unseen = {n["id"] for n in needs if not n.get("seen_at")}
        self.tab_needs = self._tab(self._needs_title())
        self.tab_batches = self._tab("Batches")
        self.tab_shelf = self._tab("Shelf")
        self._needs()
        self._batches()
        self._shelf()
        self._seen()

    # -- plumbing ------------------------------------------------------------------------------------------------ #
    def _update_notice(self, frame):
        """P3.2-AMN: *Anki Miner 3.8 is out* above the tabs (above *Needs you*), a link to its releases page."""
        from app.connect import status_row
        update = status_row.update_line(self.record)
        if update is None:
            return
        text, url = update
        link = ttk.Label(frame, text=text, style="CW.Link.TLabel", cursor="hand2")
        link.pack(anchor=tk.W, pady=(0, 8))
        link.bind("<Button-1>", lambda _e: self._open_update(url))
        self.tooltip(link, "Opens Anki Miner's releases page")
        self.update_link = link

    def _open_update(self, url):
        """A click on the notice: the releases page in the browser; a browser that fails is printed, never raised into
        Tk (as the dashboard row's)."""
        try:
            self.open_url(url)
        except Exception as e:
            print(f"Anki Miner's releases page wasn't opened: {e}")

    def _style(self):
        style = ttk.Style(self.win)
        style.configure("CW.TFrame", background=BG)
        style.configure("CW.Row.TFrame", background=SURFACE)
        style.configure("CW.TLabel", background=BG, foreground=TEXT)
        style.configure("CW.Row.TLabel", background=SURFACE, foreground=TEXT)
        style.configure("CW.Dim.TLabel", background=SURFACE, foreground=DIM)
        style.configure("CW.Meta.TLabel", background=SURFACE, foreground=DIM, font=("Segoe UI", 8))
        style.configure("CW.Note.TLabel", background=SURFACE, foreground=SECONDARY)
        style.configure("CW.Head.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI", 11, "bold"))
        style.configure("CW.Link.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI", 9, "underline"))
        style.configure("CW.TButton", background=SURFACE, foreground=TEXT)
        style.configure("CW.TLabelframe", background=BG, foreground=TEXT)
        style.configure("CW.TLabelframe.Label", background=BG, foreground=TEXT)
        style.configure("CW.TNotebook", background=BG, borderwidth=0)
        style.configure("CW.TNotebook.Tab", background=SURFACE, foreground=TEXT, padding=(10, 4))
        style.map("CW.TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", BG)])

    def _tab(self, title):
        """A tab whose list scrolls (a hundred batches don't fit) -> the frame its rows go in."""
        outer = ttk.Frame(self.tabs, style="CW.TFrame", padding=(0, 8, 0, 0))
        self.tabs.add(outer, text=title)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tab = ttk.Frame(canvas, style="CW.TFrame")
        item = canvas.create_window((0, 0), window=tab, anchor="nw")
        tab.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
        tag_all = wheel_scrolls(outer, canvas)
        tab.bind("<Configure>", tag_all, add="+")
        return tab

    def worker(self, job, then):
        """`job()` on a thread (never the Tk thread); `then(out)` drawn through `after` (an exception is the value)."""
        def run():
            try:
                out = job()
            except Exception as e:
                out = e
            self.post(lambda: then(out))
        threading.Thread(target=run, daemon=True).start()

    def post(self, job):
        """From a worker: `job` on the Tk thread — through the dashboard's queue (`post`), else `after`."""
        def guarded():
            try:
                if self.win.winfo_exists():
                    job()
            except tk.TclError:
                pass                # the window was closed meanwhile
        try:
            (self._post or (lambda j: self.win.after(0, j)))(guarded)
        except (tk.TclError, RuntimeError):
            pass

    def _button(self, parent, key, text, command, tip):
        button = ttk.Button(parent, text=text, style="CW.TButton", command=command)
        self.tooltip(button, tip)
        self.buttons[key + (text,)] = button
        return button

    def _done(self, key):
        """A button whose work is done goes (never left greyed on the screen)."""
        button = self.buttons.pop(key, None)
        if button is not None:
            button.destroy()

    def _row(self, tab):
        row = ttk.Frame(tab, style="CW.Row.TFrame", padding=8)
        row.pack(fill=tk.X, pady=(0, 6))
        return row

    def _empty(self, tab, text):
        ttk.Label(tab, text=text, style="CW.TLabel", wraplength=WRAP).pack(anchor=tk.W)

    def _act_call(self, **kw):
        settings = self._settings() if self._settings else _load_settings()
        act = self._act
        if act is None:
            from app.connect import undo
            act = undo.act
        return act(settings, self.language, **kw)

    # -- Needs you --------------------------------------------------------------------------------------------- #
    def _needs_title(self):
        """"Needs you (n)": n the entries still listed that were new when the window opened."""
        return f"Needs you ({len(self._unseen)})" if self._unseen else "Needs you"

    def _needs(self):
        needs = self.record.get("needs") or []
        if not needs:
            self._empty(self.tab_needs, "Nothing needs you.")
            return
        for need in needs:
            seen = bool(need.get("seen_at"))
            row = self._row(self.tab_needs)
            ttk.Label(row, text=need.get("say") or "", style="CW.Dim.TLabel" if seen else "CW.Row.TLabel",
                      wraplength=WRAP - 120).pack(anchor=tk.W)
            meta = when(need.get("at")) + (f" · {need['title']}" if need.get("title") else "") + \
                (" · SEEN" if seen else "")
            ttk.Label(row, text=meta, style="CW.Meta.TLabel").pack(anchor=tk.W)
            note = ttk.Label(row, text="", style="CW.Note.TLabel", wraplength=WRAP - 40)
            note.pack(anchor=tk.W)
            self.notes[("needs", need["id"])] = note
            buttons = ttk.Frame(row, style="CW.Row.TFrame")
            buttons.pack(anchor=tk.E)
            how = HOW.get(need.get("kind"))
            if how is not None:
                label, text = how
                if text == "logs":
                    command, tip = (lambda n=note: self.open_logs(n)), "Open Connect's logs, where what went wrong " \
                                                                       "is written."
                elif text == "hato":
                    command, tip = (lambda n=need: self.ask_hato(n)), "Ask hato for its pairings again: each file " \
                                                                      "it paired is matched to its video. The files " \
                                                                      "still without one are named in the logs."
                else:
                    command, tip = (lambda n=note, t=text: n.config(text=t)), "Show what fixes this."
                self._button(buttons, ("needs", need["id"]), label, command, tip).pack(side=tk.LEFT)
            self._button(buttons, ("needs", need["id"]), "Dismiss", lambda n=need, r=row: self.dismiss(n, r),
                         "Take it off this list. It comes back only if it happens again.").pack(side=tk.LEFT,
                                                                                               padx=(6, 0))

    def _seen(self):
        """What's shown is marked seen, on a worker: the badge stops counting it (it stays listed)."""
        ids = [n["id"] for n in self.record.get("needs") or () if not n.get("seen_at")]
        if not ids:
            return

        def job():
            if self._mark_seen is not None:
                return self._mark_seen(ids)
            from app.connect import status
            return status.mark_seen(ids)

        def done(out):
            if isinstance(out, Exception):          # the badge keeps counting them: say why, nothing read again
                print(f"Connect's Needs you weren't marked seen: {out}")
                self.logs_note.config(text=f"Couldn't mark these as seen just now: {_say(out)}")
                return
            self.on_change()
        self.worker(job, done)

    def dismiss(self, need, row):
        key = ("needs", need["id"], "Dismiss")
        self.buttons[key].config(state=tk.DISABLED)

        def job():
            if self._dismiss is not None:
                return self._dismiss(need["id"])
            from app.connect import status
            return status.dismiss(need["id"])

        def done(out):
            if isinstance(out, Exception):
                self.notes[("needs", need["id"])].config(text=f"Couldn't dismiss it: {out}")
                self.buttons[key].config(state=tk.NORMAL)
                return
            row.destroy()
            self._listed.discard(need["id"])
            self._unseen.discard(need["id"])
            self.tabs.tab(0, text=self._needs_title())
            if not self._listed:
                self._empty(self.tab_needs, "Nothing needs you.")
            self.on_change()
        self.worker(job, done)

    def ask_hato(self, need):
        """*Ask hato again* (P3.2): hato's pairings back-filled on a worker (`hato.backfill`), its words in the entry's
        note. None left without a pairing: the entry is fixed, its button goes."""
        key = ("needs", need["id"], "Ask hato again")
        note = self.notes[("needs", need["id"])]
        self.buttons[key].config(state=tk.DISABLED)
        note.config(text="Asking hato for its pairings…")

        def job():
            # read strictly: a settings.json caught half-saved read leniently is the defaults — the preview off
            settings = self._settings() if self._settings else _load_settings(strict=True)
            from app.connect import hato
            return hato.backfill(self.language, settings)

        def done(out):
            if isinstance(out, Exception):
                note.config(text=f"hato's pairings weren't read: {_say(out)}")
                self.buttons[key].config(state=tk.NORMAL)
                return
            from app.connect import hato
            note.config(text=hato.say(out))
            if out.get("need") == "fixed":
                self._done(key)             # every file paired: nothing left to ask
            else:
                self.buttons[key].config(state=tk.NORMAL)
            self.on_change()
        self.worker(job, done)

    # -- Batches ----------------------------------------------------------------------------------------------- #
    def _batches(self):
        batches = self.record.get("undo") or []
        if not batches:
            self._empty(self.tab_batches, "No batches of cards yet.")
            return
        for batch in batches:
            row = self._row(self.tab_batches)
            ttk.Label(row, text=batch.get("title") or "An episode", style="CW.Row.TLabel",
                      font=("Segoe UI", 10, "bold"), wraplength=WRAP - 160).pack(anchor=tk.W)
            missing = not_made_words(batch.get("not_made"))
            ttk.Label(row, text=f"{cards(batch.get('made', 0))} made" + (f" · not made: {missing}" if missing else "")
                      + f" · {when(batch.get('at'))}", style="CW.Meta.TLabel", wraplength=WRAP - 40).pack(anchor=tk.W)
            note = ttk.Label(row, text="", style="CW.Note.TLabel", wraplength=WRAP - 40)
            note.pack(anchor=tk.W)
            self.notes[("batch", batch["job"])] = note
            self._button(row, ("batch", batch["job"]), "Undo this batch", lambda b=batch: self.undo(b["job"]),
                         "Remove this episode's Anki cards that aren't studied. You're asked first.").pack(anchor=tk.E)

    def undo(self, job):
        key = ("batch", job, "Undo this batch")
        button, note = self.buttons[key], self.notes[("batch", job)]
        button.config(state=tk.DISABLED)
        note.config(text="Checking which cards can go…")
        batches = self.record.get("undo") or []
        batch = next((b for b in batches if b.get("job") == job), {})
        others = [b.get("at") for b in batches if b.get("job") != job and batch.get("item") is not None
                  and b.get("item") == batch.get("item")]           # the episode's other batches: they stay

        def planned(plan):
            said = _say(plan)
            if said:
                note.config(text=said)
                button.config(state=tk.NORMAL)
                return
            if not plan.get("delete"):
                note.config(text="No card of this batch can go: " + (
                    "; ".join(f"{k.get('word')} ({k.get('why')})" for k in plan.get("keep") or ()) or "none left")
                    + ".")
                button.config(state=tk.NORMAL)
                return
            if not self.confirm("Undo this batch", question(plan, batch.get("at"), others)):
                note.config(text="")
                button.config(state=tk.NORMAL)
                return
            note.config(text="Removing the cards…")
            self.worker(lambda: self._write(note, job=job, confirm=True), lambda out: done(out))

        def done(out):
            said = _say(out)
            if said:
                note.config(text=said)
                button.config(state=tk.NORMAL)
                return
            note.config(text=out.get("say") or "Done.")
            self._done(key)                 # the batch is undone: its button goes, the result stays said
            self.on_change()
        self.worker(lambda: self._act_call(job=job, confirm=False), planned)

    def _write(self, note, **kw):
        """On the worker: the write, waiting (and saying so, once) while another program holds Anki's write lock
        (`wait_for_writer`)."""
        return wait_for_writer(lambda: self._act_call(**kw), lambda: self.post(lambda: note.config(text=WAITING)),
                               busy=self._is_writer_busy, update=self._is_update_waiting)

    def _is_writer_busy(self):
        try:
            return self._writer_busy() if self._writer_busy is not None else writer_busy()
        except Exception:
            return False

    def _is_update_waiting(self):
        try:
            return self._update_waits() if self._update_waits is not None else update_waits()
        except Exception:
            return False

    # -- Shelf ------------------------------------------------------------------------------------------------- #
    def _shelf(self):
        shelf = self.record.get("shelf") or {}
        runs = shelf.get("runs") or []
        top = f"{cards(shelf.get('on_shelf', 0))} on the shelf (suspended until you need them)."
        if shelf.get("swap_ins"):
            top += f" {shelf['swap_ins']} came back today because you need their words again."
        ttk.Label(self.tab_shelf, text=top, style="CW.TLabel", wraplength=WRAP).pack(anchor=tk.W, pady=(0, 6))
        if not self.junban and runs:
            ttk.Label(self.tab_shelf, text="Putting the shelf back needs Junban (順), which isn't installed.",
                      style="CW.TLabel", wraplength=WRAP).pack(anchor=tk.W, pady=(0, 6))
        for run in runs:
            row = self._row(self.tab_shelf)
            ttk.Label(row, text=f"{cards(run.get('cards', 0))} · {run.get('why') or ''}", style="CW.Row.TLabel",
                      wraplength=WRAP - 40).pack(anchor=tk.W)
            words = "、".join(run.get("words") or ())
            ttk.Label(row, text=f"{when(run.get('at'))} · {run.get('back', 0)} back" + (f" · {words}" if words
                                                                                         else ""),
                      style="CW.Meta.TLabel", wraplength=WRAP - 40).pack(anchor=tk.W)
            note = ttk.Label(row, text="", style="CW.Note.TLabel", wraplength=WRAP - 40)
            note.pack(anchor=tk.W)
            self.notes[("shelf", run["run"])] = note
            if self.junban and run.get("back", 0) < run.get("cards", 0):
                self._button(row, ("shelf", run["run"]), "Put back", lambda r=run: self.put_back(r),
                             "Un-suspend these cards: they come back to your new cards, and Surasura never "
                             "shelves them again.").pack(anchor=tk.E)

    def put_back(self, run):
        key = ("shelf", run["run"], "Put back")
        button, note = self.buttons[key], self.notes[("shelf", run["run"])]
        left = run.get("cards", 0) - run.get("back", 0)
        if not self.confirm("Put back", f"Put {cards(left)} back into your new cards in Anki? Surasura never shelves "
                                        "them again."):
            return
        button.config(state=tk.DISABLED)
        note.config(text="Putting the cards back…")

        def done(out):
            said = _say(out)
            if said:
                note.config(text=said)
                button.config(state=tk.NORMAL)
                return
            note.config(text=f"{cards(out.get('back', 0))} back in your new cards.")
            self._done(key)                 # back in your new cards: nothing left to put back
            self.on_change()
        self.worker(lambda: self._write(note, shelf_run=run["run"], confirm=True), done)

    # -- Logs -------------------------------------------------------------------------------------------------- #
    def _logs(self, frame):
        box = ttk.LabelFrame(frame, text=" Logs", style="CW.TLabelframe", padding=8)
        box.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        row = ttk.Frame(box, style="CW.TFrame")
        row.pack(anchor=tk.W)
        note = ttk.Label(box, text="", style="CW.TLabel", wraplength=WRAP)
        self._button(row, ("logs",), "Open logs folder", lambda: self.open_logs(note),
                     "Open the folder with Surasura's and Connect's logs.").pack(side=tk.LEFT)
        self._button(row, ("logs",), "Save logs to a file…", lambda: self.save_logs(note),
                     "One zip of Surasura's logs and Anki Miner's results of the last 7 days, to attach to a "
                     "report. Never a key or a token.").pack(side=tk.LEFT, padx=(6, 0))
        note.pack(anchor=tk.W)
        self.logs_note = note

    def open_logs(self, note):
        def job():
            if self._logs_folder is not None:
                return self._logs_folder()
            from app.connect import settings_panel, status
            settings_panel.open_folder(status.logs_folder())
        self.worker(job, lambda out: note.config(text=f"Couldn't open the logs folder: {out}")
                    if isinstance(out, Exception) else None)

    def save_logs(self, note):
        from tkinter import filedialog
        dest = (self.ask_save or (lambda: filedialog.asksaveasfilename(
            parent=self.win, title="Save logs to a file", defaultextension=".zip",
            initialfile=f"surasura-logs-{datetime.date.today().isoformat()}.zip", filetypes=[("Zip", "*.zip")])))()
        if not dest:
            return
        note.config(text="Saving the logs…")

        def job():
            if self._save_logs is not None:
                return self._save_logs(dest)
            from app.connect import status
            return status.save_logs(dest)
        self.worker(job, lambda out: note.config(text=f"Couldn't save the logs: {out}" if isinstance(out, Exception)
                                                 else f"Saved {len(out)} files to {dest}"))


def _load_settings(strict=False):
    """settings.json as the window reads it; `strict`: one that can't be read just now raises, in plain words."""
    from app import settings_manager
    try:
        return settings_manager.load_settings(strict=strict) or {}
    except settings_manager.SettingsError:
        raise RuntimeError(SETTINGS_UNREADABLE) from None


def show(parent, language, tooltip, record, **kw):
    """The window, drawn from `record` (`view(language)`, read on the caller's worker)."""
    return ConnectWindow(parent, language, tooltip, record, **kw)

"""Settings → *Connect (preview)*'s controls and the Anki Miner card (P3.1 rows 3.1.2, 3.1.3; P1.5 05-surface U4–U6,
04-onboarding §2–§3): built only while the preview's switch is on — the switch itself is the dashboard's
(`app/main.py`), which imports this module only then.

- **U4:** each control a ttk widget with a tooltip, saved the moment it is touched with
  `settings_manager.save_keys({key: value})` — its own key only, onto settings.json as it is (the dashboard's save
  carries Connect's keys only as the file holds them, so a key nobody touched is never written).
- **U5:** the Anki Miner card: `setup.checks` on a worker → *Not installed* · *Installed <v> — needs setup* (the
  missing pieces named, the two guided steps with *Copy path*) · *Ready*; *Install* opens Anki Miner's releases page in
  the browser (no network call from Surasura), *Browse…*, *Open Anki Miner*, *Check again*.
- **U6:** the ⭐ suggestion, once Anki Miner is found installed, until one click or *Not now* — kept in local data
  (`<local data>/connect/star.json`), never settings.json; a small *⭐ Anki Miner on GitHub* link stays.

GUI_Design_Guidelines: the dark palette, ttk widgets with this module's own prefixed styles, 10 px padding, a tooltip on
every button and toggle. The tooltip is handed in (`tooltip(widget, text)`), so this module never imports app.main.
Every Connect call and every file look runs on a worker; the widgets are touched only on the Tk thread (`after`).
"""
import datetime
import json
import os
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, ttk

# The values written (pure: the tests read them) — in app/connect/settings_values.py since W3.3 P1, Tk-free, where
# the 3.0 window's Settings reads them too.
from app.connect.settings_values import (FLAG_COLOURS, KNOWN, LANGUAGES, SYNC, WORDS, cap_of,  # noqa: F401
                                         cap_value, folders_value, known_value, sync_choices, sync_label)

BG, SURFACE, TEXT, ACCENT, SECONDARY, ERROR = "#1e1e1e", "#2d2d2d", "#e0e0e0", "#bb86fc", "#03dac6", "#cf6679"
DIM = "#aaaaaa"
WRAP = 300
STAR_URL = "https://github.com/0xzerolight/anki_miner"
STAR_FILE = "star.json"

# The keys the panel shows: another window writing one (順's sync minute, its two switches) makes the panel stale
SHOWN = ("connect_mine_words", "connect_send_grammar", "anki_sync_delay_min", "connect_open_anki",
         "connect_backlog_cap", "known_from_anki", "connect_video_folders", "junban_auto_reorder",
         "junban_auto_backfill", "connect_anki_miner_path")


def save(key, value=None, merge=None):
    """One control's key, onto settings.json as it is (`save_keys`): never another key, never the whole file.
    `merge(current)`: the value worked out from the key as the file holds it at the write (the cap, the video folders:
    another language's newest value kept, D31). -> the file as saved; raises OSError when it wasn't written."""
    from app import settings_manager
    if merge is None:
        return settings_manager.save_keys({key: value}, strict=True)
    return settings_manager.save_keys(update=lambda on_disk: on_disk.__setitem__(key, merge(on_disk.get(key))),
                                      strict=True)


# --------------------------------------------------------------------------- #
# The star's answer (U6): local data, never settings.json
# --------------------------------------------------------------------------- #
def star_path():
    from app.connect import ledger
    return os.path.join(ledger.folder(), STAR_FILE)


def star_answered():
    try:
        with open(star_path(), "r", encoding="utf-8") as f:
            return bool((json.load(f) or {}).get("answer"))
    except (OSError, ValueError, AttributeError):
        return False


def answer_star(answer):
    """`starred` or `not-now`, kept so the suggestion doesn't come back. Never raises."""
    try:
        path = star_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = f"{path}.{os.getpid()}.tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump({"answer": answer, "at": datetime.datetime.now().isoformat(timespec="seconds")}, f)
        os.replace(temp, path)
        return True
    except Exception as e:
        print(f"The star's answer wasn't kept: {e}")
        return False


def card_state(result):
    """What the Anki Miner card shows, from `setup.checks` -> {"state": "missing" | "setup" | "ready", "say",
    "missing": [plain sentences], "steps": bool (the two guided steps), "path", "version"}."""
    checks = {c["id"]: c for c in (result or {}).get("checks") or ()}
    found = (result or {}).get("anki_miner") or {}
    first = checks.get("anki_miner") or {}
    if first.get("state") != "ok":
        return {"state": "missing", "say": "Not installed", "missing": [first.get("say")] if first.get("say") else [],
                "steps": False, "path": None, "version": None}
    version = found.get("app")
    pieces = [checks.get(i) for i in ("anki_miner_version", "anki_miner_profile", "anki_miner_setup")]
    missing = [c for c in pieces if c and c.get("state") != "ok"]
    if not missing:
        return {"state": "ready", "say": f"Ready — Anki Miner {version}" if version else "Ready", "missing": [],
                "steps": False, "path": found.get("path"), "version": version}
    profile = checks.get("anki_miner_profile") or {}
    return {"state": "setup", "say": f"Installed {version or ''} — needs setup".replace("  ", " "),
            "missing": [c["say"] for c in missing if c.get("say")], "steps": profile.get("state") == "needs-you",
            "path": found.get("path"), "version": version}


def open_folder(folder):
    os.makedirs(folder, exist_ok=True)
    open_path(folder)


def open_path(path):
    """A folder or a program opened as the system opens it (the dashboard's own branches, `open_data_folder`)."""
    import subprocess
    import sys
    if sys.platform == "win32":
        os.startfile(path)          # Windows: Explorer at the folder, or the program started
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def junban_present():
    import importlib.util
    try:
        return importlib.util.find_spec("modules.junban") is not None
    except (ImportError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# The panel
# --------------------------------------------------------------------------- #
class Panel:
    """Connect's controls and the Anki Miner card, built into `parent` (the dashboard's frame under the switch).
    `language()`: the dashboard's language now; `settings`: settings.json as loaded (the values shown);
    `checks(settings, language)`: `setup.checks` (tests hand a fake); `ask_folder` / `ask_file` / `ask_save`: the
    file dialogs (tests hand fakes); `post(job)`: runs `job` on the Tk thread (the dashboard's queue); `card_parent`:
    where the Anki Miner card goes (the dashboard's column, under the group)."""

    def __init__(self, parent, language, tooltip, settings, checks=None, ask_folder=None, ask_file=None,
                 ask_save=None, check_now=True, post=None, card_parent=None):
        self.parent, self.language, self.tooltip = parent, language, tooltip
        self.settings = dict(settings or {})
        self._checks = checks
        self._post = post
        self.ask_folder = ask_folder or (lambda: filedialog.askdirectory(parent=parent, title="Add a video folder"))
        self.ask_file = ask_file or (lambda: filedialog.askopenfilename(
            parent=parent, title="Where is Anki Miner?", filetypes=[("Anki Miner", "AnkiMiner.exe"),
                                                                    ("Programs", "*.exe"), ("All files", "*.*")]))
        self.ask_save = ask_save or (lambda: filedialog.asksaveasfilename(
            parent=parent, title="Save logs to a file", defaultextension=".zip",
            initialfile=f"surasura-logs-{datetime.date.today().isoformat()}.zip", filetypes=[("Zip", "*.zip")]))
        self._style()
        self.frame = ttk.Frame(parent, style="CP.TFrame")
        self.frame.pack(fill=tk.X)
        # The Anki Miner card beside the group (U5): its own frame where the dashboard puts it, else under the controls
        self.card_frame = ttk.Frame(card_parent, style="CP.TFrame") if card_parent is not None else             ttk.Frame(self.frame, style="CP.TFrame")
        self.card_frame.pack(fill=tk.X)
        self._build_controls()
        self._build_card()
        if check_now:
            self.check()

    # -- plumbing ------------------------------------------------------------------------------------------------ #
    def _style(self):
        style = ttk.Style(self.parent)
        style.configure("CP.TFrame", background=BG)
        style.configure("CP.TLabelframe", background=BG, foreground=TEXT)
        style.configure("CP.TLabelframe.Label", background=BG, foreground=TEXT)
        style.configure("CP.TLabel", background=BG, foreground=TEXT)
        style.configure("CP.Note.TLabel", background=BG, foreground=DIM, font=("Segoe UI", 8))
        style.configure("CP.State.TLabel", background=BG, foreground=SECONDARY, font=("Segoe UI", 10, "bold"))
        style.configure("CP.Bold.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 9, "bold"))
        style.configure("CP.Link.TLabel", background=BG, foreground=ACCENT)
        style.configure("CP.TCheckbutton", background=BG, foreground=TEXT)
        style.configure("CP.TRadiobutton", background=BG, foreground=TEXT)
        style.configure("CP.TButton", background=SURFACE, foreground=TEXT)
        style.configure("CP.TMenubutton", background=SURFACE, foreground=TEXT)
        style.configure("CP.TEntry", fieldbackground=SURFACE, foreground=TEXT)
        style.map("CP.TEntry", fieldbackground=[("readonly", SURFACE)], foreground=[("readonly", TEXT)])
        style.configure("CP.Star.TFrame", background=ACCENT)
        style.configure("CP.Star.TLabel", background=ACCENT, foreground=BG, font=("Segoe UI", 9))
        style.configure("CP.Star.TButton", background=SURFACE, foreground=TEXT, font=("Segoe UI", 11, "bold"),
                        padding=(10, 6))

    def worker(self, job, then):
        """`job()` on a thread; `then(out)` on the Tk thread (an exception becomes the value)."""
        def run():
            try:
                out = job()
            except Exception as e:
                out = e
            def draw():
                try:
                    if self.frame.winfo_exists():
                        then(out)
                except tk.TclError:
                    pass            # the panel went (the switch turned off, Settings closed)
            try:
                (self._post or (lambda j: self.frame.after(0, j)))(draw)
            except (tk.TclError, RuntimeError):
                pass
        threading.Thread(target=run, daemon=True).start()

    def _set(self, key, value=None, default=None, merge=None, revert=None):
        """One control's save -> True when saved (or nothing changed: the value shown picked again writes nothing,
        S19). Not written → `revert(the value still saved)` puts the control back and the reason is shown."""
        current = self.settings.get(key, default)
        if merge is None and (value == current or str(value) == str(current)):
            return True
        try:
            saved = save(key, value, merge)
        except Exception as e:
            print(f"Connect's setting {key} wasn't saved: {e}")
            self.save_note.config(text=f"Not saved: {e}. Try again in a moment.")
            if not self.save_note.winfo_ismapped():
                self.save_note.pack(anchor=tk.W, before=self.controls_first)
            if revert is not None:
                revert(current)
            return False
        self.settings[key] = saved.get(key, value) if merge is not None else value
        self.save_note.config(text="")
        return True

    def _check(self, parent, text, key, default, tip):
        var = tk.BooleanVar(parent, value=bool(self.settings.get(key, default)))
        chk = ttk.Checkbutton(parent, text=text, variable=var, style="CP.TCheckbutton",
                              command=lambda: self._set(key, bool(var.get()), default,
                                                        revert=lambda old: var.set(bool(old))))
        chk.pack(anchor=tk.W, pady=(4, 0))
        self.tooltip(chk, tip)
        return chk, var

    def _button(self, parent, text, command, tip, style="CP.TButton"):
        button = ttk.Button(parent, text=text, command=command, style=style)
        self.tooltip(button, tip)
        return button

    # -- U4: Connect's settings ------------------------------------------------------------------------------- #
    def _build_controls(self):
        f = ttk.Frame(self.frame, style="CP.TFrame")
        f.pack(fill=tk.X)
        self.controls = f
        # a save that failed says why here, above the controls (packed only then)
        self.save_note = ttk.Label(f, text="", style="CP.Note.TLabel", foreground=ERROR, wraplength=WRAP)

        self.controls_first = ttk.Label(f, text="Words to make cards from:", style="CP.TLabel")
        self.controls_first.pack(anchor=tk.W, pady=(6, 0))
        self.var_words = tk.StringVar(f, value=self.settings.get("connect_mine_words", "list"))
        self.word_buttons = {}
        for value, label, line in WORDS:
            radio = ttk.Radiobutton(f, text=label, value=value, variable=self.var_words, style="CP.TRadiobutton",
                                    command=lambda: self._set("connect_mine_words", self.var_words.get(), "list",
                                                              revert=self.var_words.set))
            radio.pack(anchor=tk.W, padx=(10, 0))
            ttk.Label(f, text=line, style="CP.Note.TLabel", wraplength=WRAP - 30).pack(anchor=tk.W, padx=(30, 0))
            self.tooltip(radio, f"{label}: {line[0].lower()}{line[1:]}")
            self.word_buttons[value] = radio

        self.chk_grammar, self.var_grammar = self._check(
            f, "Send grammar words", "connect_send_grammar", True,
            "Grammar words (particles, endings) get cards too. Names follow Ignore names in Language & Parsing.")

        row = ttk.Frame(f, style="CP.TFrame")
        row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(row, text="Sync Anki after tomorrow's cards change:", style="CP.TLabel").pack(anchor=tk.W)
        choices = sync_choices(self.settings.get("anki_sync_delay_min", 1))
        self.combo_sync = ttk.Combobox(row, values=[label for label, _v in choices], state="readonly", width=34)
        self.combo_sync.set(sync_label(choices, self.settings.get("anki_sync_delay_min", 1)))
        self.combo_sync.pack(anchor=tk.W, padx=(10, 0))
        self.combo_sync.bind("<<ComboboxSelected>>", lambda _e: self._set(
            "anki_sync_delay_min", dict(choices)[self.combo_sync.get()], 1,
            revert=lambda old: self.combo_sync.set(sync_label(choices, old))))
        self.tooltip(self.combo_sync, "When Surasura asks Anki to sync with AnkiWeb after it changed tomorrow's "
                                      "cards, so your phone gets them.")

        self.chk_open_anki, self.var_open_anki = self._check(
            f, "Open Anki for me when a session starts", "connect_open_anki", False,
            "When you open Surasura and Anki is closed, Surasura opens it, so your phone's reviews come in and "
            "your cards get made and ordered.")

        row = ttk.Frame(f, style="CP.TFrame")
        row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(row, text="Keep up to", style="CP.TLabel").pack(side=tk.LEFT)
        self.var_cap = tk.StringVar(row, value=str(cap_of(self.settings.get("connect_backlog_cap", 300),
                                                     self.language())))
        self.spin_cap = ttk.Spinbox(row, from_=0, to=5000, increment=10, width=6, textvariable=self.var_cap,
                                    command=self._save_cap)
        self.spin_cap.pack(side=tk.LEFT, padx=5)
        self.spin_cap.bind("<FocusOut>", lambda _e: self._save_cap())
        self.spin_cap.bind("<Return>", lambda _e: self._save_cap())
        ttk.Label(row, text="Surasura cards waiting", style="CP.TLabel").pack(side=tk.LEFT)
        self.tooltip(self.spin_cap, "Connect makes cards while fewer of its own new cards wait in Anki, for this "
                                    "language. 0: no limit. Your own cards never count.")

        row = ttk.Frame(f, style="CP.TFrame")
        row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(row, text="Known from Anki:", style="CP.TLabel").pack(side=tk.LEFT)
        current = self.settings.get("known_from_anki", ["suspended"])
        current = [current] if isinstance(current, str) else list(current or [])
        self.known_vars = {term: tk.BooleanVar(row, value=term in current) for term, _l in KNOWN}
        self.menu_known = ttk.Menubutton(row, style="CP.TMenubutton", width=24)
        menu = tk.Menu(self.menu_known, tearoff=False, bg=SURFACE, fg=TEXT, activebackground=ACCENT,
                       activeforeground=BG, selectcolor=ACCENT)
        for term, label in KNOWN:
            menu.add_checkbutton(label=label, variable=self.known_vars[term], command=self._save_known)
        self.menu_known["menu"] = menu
        self.known_menu = menu
        self.menu_known.pack(side=tk.LEFT, padx=(5, 0))
        self._known_text()
        self.tooltip(self.menu_known, "A card in every state you pick here marks its word known (all must hold: "
                                      "Suspended + Marked is both). None picked: off.")

        ttk.Label(f, text="Video folders (where Connect looks for a moved video):",
                  style="CP.TLabel").pack(anchor=tk.W, pady=(6, 0))
        row = ttk.Frame(f, style="CP.TFrame")
        row.pack(fill=tk.X)
        self.list_folders = tk.Listbox(row, height=3, bg=SURFACE, fg=TEXT, selectbackground=ACCENT,
                                       selectforeground=BG, highlightthickness=0, borderwidth=0,
                                       font=("Segoe UI", 9))
        self.list_folders.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._show_folders()
        buttons = ttk.Frame(row, style="CP.TFrame")
        buttons.pack(side=tk.LEFT, padx=(5, 0), anchor=tk.N)
        self.btn_add_folder = self._button(buttons, "Add…", self._add_folder,
                                           "Add a folder (and its subfolders) where your videos are.")
        self.btn_add_folder.pack(fill=tk.X)
        self.btn_remove_folder = self._button(buttons, "Remove", self._remove_folder,
                                              "Stop looking in the chosen folder.")
        self.btn_remove_folder.pack(fill=tk.X, pady=(2, 0))

        # Junban's two switches, shown once the worker found Junban installed (`_junban_checks`: a file look)
        self.chk_reorder = self.chk_backfill = None
        self.junban_row = ttk.Frame(f, style="CP.TFrame")
        self.junban_row.pack(fill=tk.X)

        row = ttk.Frame(f, style="CP.TFrame")
        row.pack(fill=tk.X, pady=(8, 0))
        self.btn_logs = self._button(row, "Open logs folder", self.open_logs,
                                     "Open the folder with Surasura's and Connect's logs.")
        self.btn_logs.pack(side=tk.LEFT)
        self.btn_save_logs = self._button(row, "Save logs to a file…", self.save_logs,
                                          "One zip of Surasura's logs and Anki Miner's results of the last 7 days, "
                                          "to attach to a report. Never a key or a token.")
        self.btn_save_logs.pack(side=tk.LEFT, padx=(5, 0))
        self.logs_note = ttk.Label(f, text="", style="CP.Note.TLabel", wraplength=WRAP)
        self.logs_note.pack(anchor=tk.W)

    def _save_cap(self):
        try:
            n = max(0, int(str(self.var_cap.get()).strip()))
        except ValueError:
            return                  # still typing: nothing saved
        current = self.settings.get("connect_backlog_cap", 300)
        if cap_of(current, self.language()) == n:
            return                  # unchanged (a focus leaving the box): nothing written (S19)
        language = self.language()
        # merged onto the cap as the file holds it at the write: another language's newer cap is kept (D31)
        self._set("connect_backlog_cap", merge=lambda on_disk: cap_value(300 if on_disk is None else on_disk,
                                                                          language, n),
                  revert=lambda old: self.var_cap.set(str(cap_of(old, language))))

    def _junban_checks(self, present):
        if not present or self.chk_reorder is not None:
            return
        self.chk_reorder, self.var_reorder = self._check(
            self.junban_row, "Re-order automatically", "junban_auto_reorder", False,
            "After a Generate and when Surasura comes back into focus, 順 puts your new cards in the list's "
            "order by itself (never while you review).")
        self.chk_backfill, self.var_backfill = self._check(
            self.junban_row, "Fill new cards automatically", "junban_auto_backfill", False,
            "After a re-order, Backfill fills your new cards' empty パターン and 例文 fields by itself.")

    def _known_text(self):
        picked = known_value({t for t, v in self.known_vars.items() if v.get()})
        names = dict(KNOWN)
        self.menu_known.config(text=" + ".join(names[t] for t in picked) if picked else "Off")

    def _save_known(self):
        def revert(old):
            old = [old] if isinstance(old, str) else list(old or [])
            for term, var in self.known_vars.items():
                var.set(term in old)
        self._set("known_from_anki", known_value({t for t, v in self.known_vars.items() if v.get()}),
                  ["suspended"], revert=revert)
        self._known_text()

    def _folders(self):
        from app.connect import videos
        return videos.configured(self.settings, self.language())

    def _write_folders(self, change):
        """`change(folders)` -> this language's folders, applied to them as the file holds them at the write (another
        language's newer folders kept, D31) -> True when saved."""
        from app.connect import videos
        language = self.language()

        def merge(on_disk):
            mine = videos.configured({"connect_video_folders": on_disk or []}, language)
            return folders_value(on_disk or [], language, change(list(mine)))
        return self._set("connect_video_folders", merge=merge)

    def _add_folder(self):
        folder = self.ask_folder()
        if not folder:
            return
        folder = os.path.normpath(folder)
        if folder in self._folders():
            return
        if self._write_folders(lambda folders: folders if folder in folders else folders + [folder]):
            self._show_folders()

    def _remove_folder(self):
        chosen = self.list_folders.curselection()
        if not chosen:
            return
        folder = self.list_folders.get(chosen[0])
        if self._write_folders(lambda folders: [f for f in folders if f != folder]):
            self._show_folders()

    def _show_folders(self):
        """The list as saved (another program's folders added meanwhile show too)."""
        self.list_folders.delete(0, tk.END)
        for folder in self._folders():
            self.list_folders.insert(tk.END, folder)

    def open_logs(self):
        def job():
            from app.connect import status
            open_folder(status.logs_folder())
        self.worker(job, lambda out: self.logs_note.config(
            text=f"Couldn't open the logs folder: {out}" if isinstance(out, Exception) else ""))

    def save_logs(self):
        dest = self.ask_save()
        if not dest:
            return
        self.btn_save_logs.config(state=tk.DISABLED)
        self.logs_note.config(text="Saving the logs…")

        def job():
            from app.connect import status
            return status.save_logs(dest)

        def done(out):
            self.btn_save_logs.config(state=tk.NORMAL)
            self.logs_note.config(text=f"Couldn't save the logs: {out}" if isinstance(out, Exception)
                                  else f"Saved {len(out)} files to {dest}")
        self.worker(job, done)

    # -- U5, U6: the Anki Miner card --------------------------------------------------------------------------- #
    def _build_card(self):
        card = ttk.LabelFrame(self.card_frame, text=" Anki Miner", style="CP.TLabelframe", padding=10)
        card.pack(fill=tk.X, pady=(5, 0))
        self.card = card
        ttk.Label(card, text="Makes your cards from your own videos. Free, made by Zero.", style="CP.Note.TLabel",
                  wraplength=WRAP).pack(anchor=tk.W)
        self.lbl_state = ttk.Label(card, text="Checking…", style="CP.State.TLabel", wraplength=WRAP)
        self.lbl_state.pack(anchor=tk.W, pady=(4, 0))
        self.star_box = None
        self.body = ttk.Frame(card, style="CP.TFrame")
        self.body.pack(fill=tk.X)
        link = ttk.Label(card, text="⭐ Anki Miner on GitHub", style="CP.Link.TLabel", cursor="hand2")
        link.pack(anchor=tk.W, pady=(6, 0))
        link.bind("<Button-1>", lambda _e: webbrowser.open(STAR_URL))
        self.tooltip(link, "Open Anki Miner's page on GitHub in your browser.")
        self.link_star = link

    def check(self):
        """`setup.checks` on a worker, then the card drawn from it."""
        self.lbl_state.config(text="Checking…")
        settings = dict(self.settings)
        language = self.language()

        def job():
            # every file look here, on the worker: the whitelist's path (it makes its folder) and Junban's presence
            from app.connect import anki_miner
            path = anki_miner.whitelist_path(language)
            if self._checks is not None:
                return self._checks(settings, language), star_answered(), path, junban_present()
            from app import settings_manager
            from app.connect import setup
            loaded = settings_manager.load_settings() or settings
            return setup.checks(loaded, language), star_answered(), path, junban_present()
        self.worker(job, self.show_card)

    def show_card(self, out):
        for child in self.body.winfo_children():
            child.destroy()
        if self.star_box is not None:
            self.star_box.destroy()
            self.star_box = None
        if isinstance(out, Exception):
            self.lbl_state.config(text=f"Couldn't check Anki Miner: {out}")
            self.state = None
            self._card_buttons(None)
            return
        result, answered, path, junban = out
        self._junban_checks(junban)
        state = card_state(result)
        self.state = state
        self.lbl_state.config(text=state["say"])
        if state["state"] != "missing" and not answered:
            self._star()
        for line in state["missing"]:
            ttk.Label(self.body, text=line, style="CP.TLabel", wraplength=WRAP).pack(anchor=tk.W, pady=(2, 0))
        if state["steps"]:
            self._steps(path)
        self._card_buttons(state)

    def _steps(self, path):
        ttk.Label(self.body, text="1. In Anki Miner: Manage profiles… → New, and name it Surasura.", style="CP.TLabel",
                  wraplength=WRAP).pack(anchor=tk.W, pady=(6, 0))
        ttk.Label(self.body, text="2. In that profile's Settings: Whitelist → choose file, and pick this file:",
                  style="CP.TLabel", wraplength=WRAP).pack(anchor=tk.W, pady=(2, 0))
        row = ttk.Frame(self.body, style="CP.TFrame")
        row.pack(fill=tk.X, padx=(10, 0))
        entry = ttk.Entry(row, width=30, style="CP.TEntry")
        entry.insert(0, path)
        entry.config(state="readonly")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        copy = self._button(row, "Copy path", lambda: self._copy(path),
                            "Copy the whitelist file's path, to paste into Anki Miner's file chooser.")
        copy.pack(side=tk.LEFT, padx=(5, 0))
        self.btn_copy = copy
        ttk.Label(self.body, text="Also turn on Bold the word in the sentence.", style="CP.Bold.TLabel",
                  wraplength=WRAP).pack(anchor=tk.W, pady=(4, 0))

    def _copy(self, text):
        self.frame.clipboard_clear()
        self.frame.clipboard_append(text)

    def _card_buttons(self, state):
        row = ttk.Frame(self.body, style="CP.TFrame")
        row.pack(fill=tk.X, pady=(6, 0))
        self.card_buttons = {}
        if state is None or state["state"] == "missing":
            self.card_buttons["Install"] = self._button(
                row, "Install", lambda: webbrowser.open(self._releases()),
                "Open Anki Miner's releases page in your browser: download the Windows Setup file and run it.")
            self.card_buttons["Browse…"] = self._button(
                row, "Browse…", self._browse, "Anki Miner is installed somewhere else: show Surasura where.")
        else:
            self.card_buttons["Open Anki Miner"] = self._button(
                row, "Open Anki Miner", self._open_miner, "Start Anki Miner, to finish its setup.")
        self.card_buttons["Check again"] = self._button(row, "Check again", self.check,
                                                        "Look at Anki Miner's setup again.")
        for i, button in enumerate(self.card_buttons.values()):
            button.pack(side=tk.LEFT, padx=(0 if i == 0 else 5, 0))

    @staticmethod
    def _releases():
        from app.connect import setup
        return setup.RELEASES

    def _browse(self):
        path = self.ask_file()
        if not path:
            return
        if self._set("connect_anki_miner_path", os.path.normpath(path)):
            self.check()

    def _open_miner(self):
        path = (self.state or {}).get("path")
        if not path:
            return

        def job():
            open_path(path)
        self.worker(job, lambda out: self.lbl_state.config(text=f"Couldn't open Anki Miner: {out}")
                    if isinstance(out, Exception) else None)

    def _star(self):
        box = ttk.Frame(self.card, style="CP.Star.TFrame", padding=10)
        box.pack(fill=tk.X, pady=(6, 0), before=self.body)
        self.star_box = box
        ttk.Label(box, text="Anki Miner is free and made by one person. A ⭐ on GitHub helps other learners find it.",
                  style="CP.Star.TLabel", wraplength=WRAP - 20).pack(anchor=tk.W)
        star = self._button(box, "⭐ Star Anki Miner on GitHub", self._starred,
                            "The Star button is at the top right; it needs a GitHub account.", style="CP.Star.TButton")
        star.pack(fill=tk.X, pady=(6, 0))
        later = self._button(box, "Not now", lambda: self._answer("not-now"), "Hide this suggestion.")
        later.pack(anchor=tk.E, pady=(4, 0))
        self.btn_star, self.btn_not_now = star, later

    def _starred(self):
        webbrowser.open(STAR_URL)
        self._answer("starred")

    def _answer(self, answer):
        if self.star_box is not None:
            self.star_box.destroy()
            self.star_box = None
        threading.Thread(target=answer_star, args=(answer,), daemon=True).start()

    def stale(self, loaded):
        """Does settings.json as `loaded` now hold another value for a key the panel shows than it was built with (or
        last saved)? Then its values and its "nothing changed" check are out of date."""
        return any((loaded or {}).get(key) != self.settings.get(key) for key in SHOWN)

    def destroy(self):
        for frame in (self.card_frame, self.frame):
            try:
                frame.destroy()
            except tk.TclError:
                pass


def build(parent, language, tooltip, settings, **kw):
    """The panel, under the switch (the dashboard calls it only with the preview on)."""
    return Panel(parent, language, tooltip, settings, **kw)

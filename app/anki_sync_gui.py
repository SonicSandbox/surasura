"""The Anki Known Words window: pull known words straight from Anki over AnkiConnect.

    probe  ->  pick decks + a field  ->  Sync now        (or: Replace with Anki / Restore previous)

Spec: `docs/agent instructions/Anki_Known_Sync_Spec.md` §5.6 / §5.9. The engine
(`app/anki_sync.py`) decides everything; this window renders it and asks. It mirrors the Junban
panel on purpose — the same connection light, the same palette, the same worker/queue pump — so the
two Anki windows read as one app.

**Nothing touches Tk from a worker.** Every AnkiConnect call runs on a daemon thread and talks to the
window only through `self.q`, drained by an `after()` pump. The pump and the opening probe are gated
on `SURASURA_NO_UI_TIMERS`: a pending `after` whose Tcl command died with the interpreter fires into
nothing for the rest of a test session, and a test must never reach the developer's live collection.

**Anki being closed is a state, not an error.** The window opens degraded and says so.

**Appending is the default; replacing is a deliberate act.** Sync only ever adds. Replace rebuilds the
list from Anki alone, so it sits behind a themed confirmation that states the before/after numbers,
Cancel is focused and Enter does not confirm it, and the previous file is backed up first so
Restore previous can undo it.

Theming: opened in-process over the dashboard (`default` theme), so it never switches the theme — it
claims the base style only when `ensure_styleable_theme` says it is standalone and otherwise layers
its own `Aks.*` styles (`GUI_Design_Guidelines.md` §2.1).
"""

import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

# --- Surasura palette (GUI_Design_Guidelines.md) --- #
BG = "#1e1e1e"
SURFACE = "#2d2d2d"
TEXT = "#e0e0e0"
MUTED = "#9a9a9a"
ACCENT = "#bb86fc"
SECONDARY = "#03dac6"
ERROR = "#cf6679"
DISABLED = "#5c5c5c"

TITLE = "Anki Known Words"
AUTO_FIELD = "Auto — first field"
NO_FIELD = "—"
LANG_NAMES = {"ja": "Japanese", "zh": "Chinese"}


class ToolTip:
    """Hover tooltip per the Surasura GUI guidelines (wraps text over 50 characters)."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 25
        self.tip = window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")
        wrap = 240 if len(self.text) > 50 else 0
        tk.Label(window, text=self.text, justify=tk.LEFT, background=SURFACE, foreground=TEXT,
                 relief=tk.SOLID, borderwidth=1, wraplength=wrap, padx=6, pady=4).pack()

    def _hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class ConfirmDialog(tk.Toplevel):
    """A themed yes/no. Esc, the close button and Enter all mean **no** — this only ever guards a
    rewrite of the user's known words, and a prompt that treats a stray keypress as consent is not
    a prompt. Cancel holds the focus."""

    def __init__(self, parent, message, details=None, yes="Replace", no="Cancel"):
        super().__init__(parent)
        self.answer = False
        self.title(f"Surasura - {TITLE}")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)

        frame = ttk.Frame(self, padding=18, style="Aks.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=message, style="Aks.TLabel", justify=tk.LEFT,
                  wraplength=440).pack(anchor="w")
        if details:
            ttk.Label(frame, text=details, style="AksMuted.TLabel", justify=tk.LEFT,
                      wraplength=440).pack(anchor="w", pady=(10, 0))

        buttons = ttk.Frame(frame, style="Aks.TFrame")
        buttons.pack(fill=tk.X, pady=(16, 0))
        decline = ttk.Button(buttons, text=no, width=12, style="Aks.TButton",
                             command=lambda: self._done(False))
        decline.pack(side=tk.RIGHT)
        ToolTip(decline, "Stop here. Your known words are not changed.")
        accept = ttk.Button(buttons, text=yes, width=12, style="Aks.TButton",
                            command=lambda: self._done(True))
        accept.pack(side=tk.RIGHT, padx=(0, 8))
        ToolTip(accept, "Go ahead. Your current list is backed up first.")

        self.bind("<Escape>", lambda _e: self._done(False))
        self.bind("<Return>", lambda _e: self._done(False))
        self.protocol("WM_DELETE_WINDOW", lambda: self._done(False))
        decline.focus_set()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.wait_window(self)

    def _done(self, answer):
        self.answer = answer
        self.destroy()


def ask(parent, message, details=None, yes="Replace", no="Cancel"):
    try:
        return ConfirmDialog(parent, message, details=details, yes=yes, no=no).answer
    except tk.TclError:
        text = message + ("\n\n" + details if details else "")
        return bool(messagebox.askyesno(TITLE, text, parent=parent))


def _ago(iso):
    """'just now' / '4 min ago' / '3 h ago' / '2 days ago' for a stored ISO timestamp."""
    try:
        seconds = (datetime.now() - datetime.fromisoformat(str(iso))).total_seconds()
    except (TypeError, ValueError):
        return ""
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


class AnkiSyncGui(tk.Toplevel):
    """The window. `app` is the dashboard when there is one."""

    def __init__(self, parent, app=None, language="ja"):
        super().__init__(parent)
        self.app = app
        self.language = language if language in LANG_NAMES else "ja"
        self.q = queue.Queue()
        self.busy = False
        self._closing = False
        self._job = 0                   # the running job's id; only ITS __DONE__ clears busy
        self._connected = False
        self._all_decks = []      # every deck Anki has
        self._counts = {}         # chosen deck -> studied notes
        self._models = {}         # model -> [field names, in order]

        saved = self._saved_settings()
        self.decks = list((saved.get("anki_sync_decks") or {}).get(self.language) or [])
        fields = list((saved.get("anki_sync_fields") or {}).get(self.language) or [])[:2]
        self.var_field1 = tk.StringVar(value=fields[0] if fields else AUTO_FIELD)
        self.var_field2 = tk.StringVar(value=fields[1] if len(fields) > 1 else NO_FIELD)
        self.var_suspended = tk.BooleanVar(value=bool(saved.get("anki_sync_include_suspended", False)))
        # The dashboard's own variables when it opened us — these two options live only here now,
        # beside the decks they depend on; the dashboard's trace saves them.
        self.var_auto = getattr(app, "var_anki_sync_auto", None) or \
            tk.BooleanVar(value=bool(saved.get("anki_sync_auto", False)))
        self.var_generate = getattr(app, "var_anki_auto_generate", None) or \
            tk.BooleanVar(value=bool(saved.get("anki_auto_generate", False)))

        self.title(f"Surasura - {TITLE}")
        self.configure(bg=BG)
        self.geometry("660x600")
        self.minsize(580, 520)
        self.bind("<Escape>", lambda _e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._init_styles()
        self._build_ui()
        self._render_decks()
        self._sync_controls()

        if not os.environ.get("SURASURA_NO_UI_TIMERS"):
            self.after(100, self._drain)
            self.after(30, self.refresh_known)
            self.after(50, self.refresh_connection)

    def _close(self):
        self._closing = True
        self.destroy()

    def sync_backfill_button(self):
        """Show "Backfill cards…" only while the dashboard offers it — Junban switched on and
        installed. Called on open and again whenever the Junban toggle changes."""
        try:
            offered = bool(self.app is not None and self.app.backfill_available())
        except Exception:
            offered = False
        try:
            packed = self.btn_backfill.winfo_manager() == "pack"
            if offered and not packed:
                self.btn_backfill.pack(side=tk.RIGHT, after=self.conn_lbl)
            elif not offered and packed:
                self.btn_backfill.pack_forget()
        except tk.TclError:
            pass

    def open_backfill(self):
        if self.app is not None and hasattr(self.app, "open_backfill"):
            self.app.open_backfill()

    # ------------------------------------------------------------------- settings
    def _url(self):
        from app import anki_connect
        return self._saved_settings().get("anki_connect_url") or anki_connect.DEFAULT_URL

    @staticmethod
    def _saved_settings():
        try:
            from app import settings_manager
            return settings_manager.load_settings() or {}
        except Exception:
            return {}

    def _snapshot(self):
        """Everything a worker needs, read HERE on the UI thread. Tk is not thread-safe: a worker
        calling var.get() raises 'main thread is not in main loop' outside mainloop and races
        inside it."""
        return {"url": self._url(), "decks": list(self.decks), "fields": self._fields(),
                "suspended": bool(self.var_suspended.get())}

    def _fields(self):
        """[] = auto (each note type's first field); otherwise up to two named fields."""
        first, second = self.var_field1.get(), self.var_field2.get()
        if not first or first == AUTO_FIELD:
            return []
        return [first] + ([second] if second and second not in (NO_FIELD, first) else [])

    def _save(self):
        """Write this window's own keys. Dicts are COPIED: settings_manager merges defaults with a
        shallow update, so the dict in loaded settings can be the one inside DEFAULT_SETTINGS.

        Written onto the file AS IT IS ON DISK, not onto the merged settings: those carry every
        installed module's defaults, and saving them wrote Speech's hidden `koe_*` keys for users
        who never revealed it (and changed the analysis fingerprint on every deck click)."""
        try:
            import json
            from app import settings_manager
            from app.path_utils import get_user_file
            try:
                with open(get_user_file("settings.json"), "r", encoding="utf-8") as f:
                    s = json.load(f)
                if not isinstance(s, dict):
                    raise ValueError("settings.json is not an object")
            except (OSError, ValueError):
                s = settings_manager.load_settings()
            decks = dict(s.get("anki_sync_decks") or {})
            decks[self.language] = list(self.decks)
            fields = dict(s.get("anki_sync_fields") or {})
            fields[self.language] = self._fields()
            s["anki_sync_decks"] = decks
            s["anki_sync_fields"] = fields
            s["anki_sync_include_suspended"] = bool(self.var_suspended.get())
            if self.app is None:
                s["anki_sync_auto"] = bool(self.var_auto.get())
                s["anki_auto_generate"] = bool(self.var_generate.get())
            settings_manager.save_settings(s)
        except Exception as e:
            self._set_result(f"Could not save your choices: {e}", ERROR)

    # ------------------------------------------------------------------- styling
    def _init_styles(self):
        from app.ui_theme import ensure_styleable_theme
        style = ttk.Style(self)
        if ensure_styleable_theme(self):
            style.configure(".", background=BG, foreground=TEXT, fieldbackground=SURFACE,
                            font=("Segoe UI", 10))

        self.option_add("*TCombobox*Listbox.background", SURFACE)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)

        style.configure("Aks.TFrame", background=BG)
        style.configure("Aks.TLabel", background=BG, foreground=TEXT)
        style.configure("AksMuted.TLabel", background=BG, foreground=MUTED)
        style.configure("AksHeader.TLabel", background=BG, foreground=SECONDARY,
                        font=("Segoe UI", 18, "bold"))
        style.configure("AksField.TLabel", background=BG, foreground=ACCENT,
                        font=("Segoe UI", 9, "bold"))
        style.configure("AksBad.TLabel", background=BG, foreground=ERROR,
                        font=("Segoe UI", 9, "bold"))
        style.configure("AksState.TLabel", background=BG, foreground=MUTED,
                        font=("Segoe UI", 10, "bold"))
        style.configure("AksStat.TLabel", background=BG, foreground=SECONDARY,
                        font=("Segoe UI", 22, "bold"))
        style.configure("AksDelta.TLabel", background=BG, foreground=SECONDARY,
                        font=("Segoe UI", 12, "bold"))
        style.configure("AksLink.TLabel", background=BG, foreground=ACCENT,
                        font=("Segoe UI", 9, "underline"))

        style.configure("Aks.TButton", background=SURFACE, foreground=TEXT, borderwidth=0,
                        padding=8, font=("Segoe UI", 10, "bold"))
        style.map("Aks.TButton",
                  background=[("active", ACCENT), ("pressed", ACCENT), ("disabled", SURFACE)],
                  foreground=[("active", BG), ("pressed", BG), ("disabled", "#6b6b6b")])
        style.configure("AksPrimary.TButton", background=ACCENT, foreground=BG, borderwidth=0,
                        padding=8, font=("Segoe UI", 10, "bold"))
        style.map("AksPrimary.TButton",
                  background=[("active", SECONDARY), ("pressed", SECONDARY), ("disabled", SURFACE)],
                  foreground=[("active", BG), ("pressed", BG), ("disabled", "#6b6b6b")])
        style.configure("AksIcon.TButton", background=SURFACE, foreground=TEXT, borderwidth=0,
                        padding=4, font=("Segoe UI", 11))
        style.map("AksIcon.TButton",
                  background=[("active", ACCENT), ("pressed", ACCENT), ("disabled", SURFACE)],
                  foreground=[("active", BG), ("pressed", BG), ("disabled", "#6b6b6b")])

        style.configure("Aks.TCheckbutton", background=BG, foreground=TEXT)
        style.map("Aks.TCheckbutton", background=[("active", BG), ("disabled", BG)],
                  foreground=[("active", ACCENT), ("disabled", DISABLED)],
                  indicatorcolor=[("selected", ACCENT), ("active", SURFACE), ("!selected", SURFACE)],
                  indicatorbackground=[("selected", ACCENT), ("active", SURFACE),
                                       ("!selected", SURFACE), ("disabled", BG)])

        style.configure("Aks.TCombobox", fieldbackground=SURFACE, background=SURFACE,
                        foreground=TEXT, arrowcolor=ACCENT,
                        selectbackground=SURFACE, selectforeground=TEXT)
        style.map("Aks.TCombobox",
                  fieldbackground=[("disabled", "#262626"), ("readonly", SURFACE)],
                  foreground=[("disabled", DISABLED), ("readonly", TEXT)],
                  selectbackground=[("readonly", SURFACE)], selectforeground=[("readonly", TEXT)],
                  arrowcolor=[("disabled", DISABLED)])

        style.configure("Aks.Horizontal.TProgressbar", thickness=4, background=ACCENT,
                        troughcolor=SURFACE, borderwidth=0)

        style.configure("Aks.Treeview", background=SURFACE, foreground=TEXT,
                        fieldbackground=SURFACE, borderwidth=0, font=("Segoe UI", 10),
                        rowheight=28)
        style.map("Aks.Treeview",
                  background=[("selected", "#3a3a3a")], foreground=[("selected", TEXT)])

    # -------------------------------------------------------------------- layout
    def _build_ui(self):
        main = ttk.Frame(self, padding=(16, 12), style="Aks.TFrame")
        main.pack(fill=tk.BOTH, expand=True)
        self._main = main

        # Title row: the name on the left, the connection light and ⟳ on the right.
        title_row = ttk.Frame(main, style="Aks.TFrame")
        title_row.pack(fill=tk.X)
        ttk.Label(title_row, text=TITLE, style="AksHeader.TLabel").pack(side=tk.LEFT)
        self.btn_recheck = ttk.Button(title_row, text="⟳", width=3, style="AksIcon.TButton",
                                      command=self.refresh_connection)
        self.btn_recheck.pack(side=tk.RIGHT)
        ToolTip(self.btn_recheck, "Check again whether Anki is running with AnkiConnect, and "
                                  "refresh the list of decks.")
        self.conn_var = tk.StringVar(value="● not checked yet")
        self.conn_lbl = ttk.Label(title_row, textvariable=self.conn_var, style="AksState.TLabel")
        self.conn_lbl.pack(side=tk.RIGHT, padx=(12, 10))
        self.conn_tip = ToolTip(self.conn_lbl, "")
        # Anki Backfill lives in the Junban module. The dashboard says whether it is offered — this
        # window never imports a module itself (spec I1) — and the button hides with Junban.
        self.btn_backfill = ttk.Button(title_row, text="Backfill cards…", style="Aks.TButton",
                                       command=self.open_backfill)
        ToolTip(self.btn_backfill, "Fill fields on your cards from Surasura.")
        self._title_row = title_row
        self.sync_backfill_button()

        ttk.Label(main,
                  text=f"Adds the words from {LANG_NAMES[self.language]} cards you've studied to your "
                       "known words. New cards are left alone, and nothing is ever removed.",
                  style="AksMuted.TLabel", justify=tk.LEFT, wraplength=620).pack(anchor="w", pady=(2, 12))

        # Bottom-up: everything below the deck list is packed against the BOTTOM first (in reverse
        # visual order), so shrinking the window only ever shortens the list — the actions can
        # never be pushed off-screen.
        self._build_actions(main)
        self._build_status(main)
        self._build_options(main)
        self._build_fields(main)
        self._build_decks(main)

    def _build_decks(self, parent):
        row = ttk.Frame(parent, style="Aks.TFrame")
        row.pack(fill=tk.BOTH, expand=True)
        ttk.Label(row, text="Decks", style="Aks.TLabel", width=11).pack(side=tk.LEFT, anchor="n", pady=(4, 0))

        col = ttk.Frame(row, style="Aks.TFrame")
        col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(col, columns=("deck", "studied", "remove"), show="",
                                 height=4, style="Aks.Treeview", selectmode="browse")
        self.tree.column("deck", width=300, anchor="w")
        self.tree.column("studied", width=120, anchor="e")
        self.tree.column("remove", width=36, anchor="center", stretch=False)
        self.tree.tag_configure("empty", foreground=MUTED)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Delete>", lambda _e: self._remove_selected())
        ToolTip(self.tree, "Words are read from these decks (and their subdecks). Click ✕ or press "
                           "Delete to remove one.")

        self.var_add = tk.StringVar(value="")
        self.add_box = ttk.Combobox(col, textvariable=self.var_add, state="readonly",
                                    style="Aks.TCombobox")
        # Packed before the list and against the bottom, so a short window shrinks the list
        # rather than hiding the way to add a deck.
        self.add_box.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.add_box.set("Add a deck…")
        self.add_box.bind("<<ComboboxSelected>>", lambda _e: self._add_deck())
        ToolTip(self.add_box, "Add another deck to read known words from.")

    def _build_fields(self, parent):
        section = ttk.Frame(parent, style="Aks.TFrame")
        section.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        parent = section
        row = ttk.Frame(parent, style="Aks.TFrame")
        row.pack(fill=tk.X)
        ttk.Label(row, text="Word field", style="Aks.TLabel", width=11).pack(side=tk.LEFT)
        self.box_field1 = ttk.Combobox(row, textvariable=self.var_field1, state="readonly",
                                       width=22, style="Aks.TCombobox", values=[AUTO_FIELD])
        self.box_field1.pack(side=tk.LEFT)
        self.box_field1.bind("<<ComboboxSelected>>", lambda _e: self._on_fields_changed())
        ToolTip(self.box_field1, "The field that holds the word. Auto uses each note type's first "
                                 "field — where Anki Miner and most decks keep it.")
        ttk.Label(row, text="Also read", style="Aks.TLabel").pack(side=tk.LEFT, padx=(16, 6))
        self.box_field2 = ttk.Combobox(row, textvariable=self.var_field2, state="readonly",
                                       width=18, style="Aks.TCombobox", values=[NO_FIELD])
        self.box_field2.pack(side=tk.LEFT)
        self.box_field2.bind("<<ComboboxSelected>>", lambda _e: self._on_fields_changed())
        ToolTip(self.box_field2, "Optionally read a second field too. Pick a word field first — "
                                 "a sentence field marks every word in the sentence as known.")

        self.resolved_var = tk.StringVar(value="")
        self.unresolved_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.resolved_var, style="AksField.TLabel",
                  wraplength=520, justify=tk.LEFT).pack(anchor="w", padx=(88, 0), pady=(4, 0))
        self.lbl_unresolved = ttk.Label(parent, textvariable=self.unresolved_var, style="AksBad.TLabel",
                                        wraplength=520, justify=tk.LEFT)

    def _build_options(self, parent):
        box = ttk.Frame(parent, style="Aks.TFrame")
        box.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        chk_susp = ttk.Checkbutton(box, text="Include suspended cards", variable=self.var_suspended,
                                   style="Aks.TCheckbutton", command=self._on_scope_changed)
        chk_susp.pack(anchor="w")
        ToolTip(chk_susp, "Count cards you've suspended as known. Off by default — suspended cards "
                          "are often ones you struggled with.")
        chk_auto = ttk.Checkbutton(box, text="Sync automatically when Anki is running",
                                   variable=self.var_auto, style="Aks.TCheckbutton",
                                   command=self._on_auto_changed)
        chk_auto.pack(anchor="w", pady=(4, 0))
        ToolTip(chk_auto, "When Anki is open, Surasura adds new known words on its own — at start-up "
                          "and when you come back to it.")
        chk_generate = ttk.Checkbutton(box, text="Generate when Anki adds known words",
                                       variable=self.var_generate, style="Aks.TCheckbutton",
                                       command=self._on_auto_changed)
        chk_generate.pack(anchor="w", pady=(4, 0))
        ToolTip(chk_generate, "When a sync brings in words you now know, Generate runs on its own in "
                              "the background, so your list is current — without opening the "
                              "report. At most every 10 minutes, and never while the Content "
                              "Manager, an import or a Generate is running.")

    def _build_status(self, parent):
        box = ttk.Frame(parent, style="Aks.TFrame")
        box.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        stat = ttk.Frame(box, style="Aks.TFrame")
        stat.pack(anchor="w")
        self.known_var = tk.StringVar(value="—")
        lbl_known = ttk.Label(stat, textvariable=self.known_var, style="AksStat.TLabel")
        lbl_known.pack(side=tk.LEFT)
        ToolTip(lbl_known, "Every word Surasura counts as known, from all your sources.")
        ttk.Label(stat, text="known words", style="AksMuted.TLabel").pack(side=tk.LEFT, padx=(8, 0), pady=(10, 0))
        self.delta_var = tk.StringVar(value="")
        ttk.Label(stat, textvariable=self.delta_var, style="AksDelta.TLabel").pack(
            side=tk.LEFT, padx=(10, 0), pady=(6, 0))
        # The new cards waiting in the same decks (anki_backlog.json) — shown only once there are any.
        self.backlog_var = tk.StringVar(value="")
        self.lbl_backlog = ttk.Label(box, textvariable=self.backlog_var, style="AksMuted.TLabel")
        ToolTip(self.lbl_backlog, "The new cards waiting to be learned in these decks, read with each "
                                  "sync. Junban (順) can put them in your journey's order.")

        self.result_var = tk.StringVar(value="")
        self.lbl_result = ttk.Label(box, textvariable=self.result_var, style="AksMuted.TLabel",
                                    wraplength=620, justify=tk.LEFT)
        self.lbl_result.pack(anchor="w", pady=(2, 0))

        self.progress = ttk.Progressbar(box, mode="indeterminate",
                                        style="Aks.Horizontal.TProgressbar")

    def _build_actions(self, parent):
        sep = tk.Frame(parent, height=1, bg=SURFACE)
        row = ttk.Frame(parent, style="Aks.TFrame")
        row.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        sep.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))

        links = ttk.Frame(row, style="Aks.TFrame")
        links.pack(side=tk.LEFT)
        self.lnk_apkg = ttk.Label(links, text="Import an .apkg file instead…", style="AksLink.TLabel",
                                  cursor="hand2")
        self.lnk_apkg.pack(anchor="w")
        self.lnk_apkg.bind("<Button-1>", lambda _e: self.open_apkg_importer())
        ToolTip(self.lnk_apkg, "Offline: read an exported deck file instead. That imports every "
                               "note in the file, studied or not.")
        self.lnk_restore = ttk.Label(links, text="Restore previous", style="AksLink.TLabel",
                                     cursor="hand2")
        self.lnk_restore.bind("<Button-1>", lambda _e: self.on_restore())
        ToolTip(self.lnk_restore, "Put back the known-words list from before the last Replace.")

        self.btn_sync = ttk.Button(row, text="Sync now", style="AksPrimary.TButton",
                                   command=self.on_sync)
        self.btn_sync.pack(side=tk.RIGHT)
        self.btn_sync.bind("<Shift-Button-1>", self._on_shift_sync)
        ToolTip(self.btn_sync, "Add the words from newly studied cards. Shift-click re-reads every "
                               "card instead of just the new ones.")
        self.btn_replace = ttk.Button(row, text="Replace with Anki…", style="Aks.TButton",
                                      command=self.on_replace)
        self.btn_replace.pack(side=tk.RIGHT, padx=(0, 8))
        ToolTip(self.btn_replace, "Rebuild your known words from Anki only. Your current list is "
                                  "backed up first.")

    # ------------------------------------------------------------------ decks
    def _render_decks(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not self.decks:
            self.tree.insert("", "end", values=("No decks chosen yet — add one below.", "", ""),
                             tags=("empty",))
            return
        for deck in self.decks:
            n = self._counts.get(deck)
            studied = f"{n:,} studied" if isinstance(n, int) else ""
            self.tree.insert("", "end", iid=f"deck::{deck}", values=(deck, studied, "✕"))

    def _refresh_add_box(self):
        offer = [d for d in self._all_decks if d not in self.decks]
        self.add_box.config(values=offer)
        # Offline we simply don't know Anki's decks yet — "No other decks" would be a false claim.
        self.add_box.set("Add a deck…" if offer or not self._connected else "No other decks")

    def _on_tree_click(self, event):
        if self.tree.identify_column(event.x) != "#3":
            return
        item = self.tree.identify_row(event.y)
        if item.startswith("deck::"):
            self._remove_deck(item[len("deck::"):])
            return "break"

    def _remove_selected(self):
        for item in self.tree.selection():
            if item.startswith("deck::"):
                self._remove_deck(item[len("deck::"):])

    def _remove_deck(self, deck):
        if self.busy or deck not in self.decks:
            return
        self.decks.remove(deck)
        self._on_scope_changed()

    def _add_deck(self):
        deck = self.var_add.get()
        if deck and deck in self._all_decks and deck not in self.decks:
            self.decks.append(deck)
            self._on_scope_changed()
        else:
            self._refresh_add_box()

    # --------------------------------------------------------------- field rows
    def _field_names(self):
        seen = []
        for names in self._models.values():
            for name in names:
                if name not in seen:
                    seen.append(name)
        return seen

    def _render_fields(self):
        names = self._field_names()
        first = self.var_field1.get()
        values1 = [AUTO_FIELD] + names + ([first] if first not in names and first != AUTO_FIELD else [])
        self.box_field1.config(values=values1)
        values2 = [NO_FIELD] + [n for n in names if n != first]
        self.box_field2.config(values=values2)
        if self.var_field2.get() == first:
            self.var_field2.set(NO_FIELD)

        from app import anki_sync
        chosen = self._fields()
        ok, bad = [], []
        for model, fields in sorted(self._models.items()):
            resolved = anki_sync.resolve_fields(fields, chosen)
            if resolved:
                ok.append(f"{model} → {' + '.join(resolved)}")
            else:
                bad.append(f"{model} → (no such field — skipped)")
        self.resolved_var.set("   ·   ".join(ok))
        self.unresolved_var.set("   ·   ".join(bad))
        # Only takes a line when there is something wrong to show.
        if bad and not self.lbl_unresolved.winfo_manager():
            self.lbl_unresolved.pack(anchor="w", padx=(88, 0))
        elif not bad and self.lbl_unresolved.winfo_manager():
            self.lbl_unresolved.pack_forget()

    def _on_fields_changed(self):
        self._render_fields()
        self._save()
        self._sync_controls()

    def _on_scope_changed(self):
        self._save()
        self._render_decks()
        self._refresh_add_box()
        self._sync_controls()
        if self._connected and not self.busy:
            snap = self._snapshot()
            self._start(lambda: self._scope_worker(snap))

    def _on_auto_changed(self):
        # With the dashboard, its own trace saves the setting; standalone, save it here.
        if self.app is None:
            self._save()

    # -------------------------------------------------------------------- state
    def _sync_controls(self):
        idle = not self.busy
        live = idle and self._connected
        can_sync = live and bool(self.decks)
        for widget, enabled in ((self.btn_sync, can_sync), (self.btn_replace, can_sync),
                                (self.btn_recheck, idle)):
            try:
                widget.config(state=tk.NORMAL if enabled else tk.DISABLED)
            except tk.TclError:
                pass
        for box, enabled in ((self.add_box, live), (self.box_field1, live)):
            try:
                box.config(state="readonly" if enabled else "disabled")
            except tk.TclError:
                pass
        try:
            # A second field only makes sense on top of a named first one (Auto is per note type).
            self.box_field2.config(state="readonly" if live and self._fields() else "disabled")
        except tk.TclError:
            pass

    def _set_busy(self, busy):
        self.busy = busy
        try:
            if busy:
                self.progress.pack(fill=tk.X, pady=(6, 0))
                self.progress.start(12)
            else:
                self.progress.stop()
                self.progress.pack_forget()
        except tk.TclError:
            pass
        self._sync_controls()

    def _set_result(self, text, color=MUTED):
        self.result_var.set(text)
        try:
            self.lbl_result.config(foreground=color)
        except tk.TclError:
            pass

    def _show_known(self, total, state=None, backlog=None):
        self.known_var.set(f"{int(total):,}")
        if backlog is not None:
            self._show_backlog(backlog)
        state = state or {}
        if state.get("last_backup"):
            if not self.lnk_restore.winfo_ismapped():
                self.lnk_restore.pack(anchor="w", pady=(2, 0))
        elif self.lnk_restore.winfo_ismapped():
            self.lnk_restore.pack_forget()
        if state.get("last_sync") and not self.result_var.get():
            added = state.get("last_added") or 0
            self._set_result(f"Last synced {_ago(state['last_sync'])} · +{added:,} word{'s' if added != 1 else ''}")

    def _show_backlog(self, count):
        """Shows "398 new cards in your backlog" under the total — nothing when none has been read."""
        count = int(count or 0)
        if count:
            self.backlog_var.set(f"{count:,} new card{'s' if count != 1 else ''} in your backlog")
            self.lbl_backlog.pack(anchor="w", before=self.lbl_result)
        else:
            self.backlog_var.set("")
            self.lbl_backlog.pack_forget()

    def _flash_delta(self, added):
        if added <= 0:
            return
        self.delta_var.set(f"+{added:,}")
        if not os.environ.get("SURASURA_NO_UI_TIMERS"):
            self.after(5000, lambda: self.winfo_exists() and self.delta_var.set(""))

    def _set_connection(self, report, decks, preselected, counts, models):
        self._connected = bool(report.get("ok"))
        if self._connected:
            # Short on purpose: the title row is narrow, and a clipped status reads as broken.
            version = report.get("version")
            self.conn_var.set("● connected")
            self.conn_tip.text = f"Anki is running (AnkiConnect {version})." if version else "Anki is running."
            self.conn_lbl.config(foreground=SECONDARY)
            self._all_decks = list(decks or [])
            if preselected is not None:
                # First open for this language: every deck that has studied cards, largest first.
                self.decks = list(preselected)
                self._save()
                if preselected:
                    self._set_result("Picked the decks you've studied cards in — remove any that "
                                     "aren't vocabulary, then press Sync now.")
            self._counts = dict(counts or {})
            self._models = dict(models or {})
        else:
            self.conn_var.set("● not connected")
            self.conn_lbl.config(foreground=ERROR)
            error = str(report.get("error") or "")
            self.conn_tip.text = error
            # A refused connection just means Anki is closed — say that, not the socket error.
            # Anything actionable (a permission prompt, an outdated add-on) is shown as written.
            actionable = any(w in error.lower() for w in ("permission", "grant", "missing", "update",
                                                          "stopped answering"))
            self._set_result(error if actionable else
                             "Anki isn't running. Start it with your profile open, then press ⟳.", ERROR)
        self._render_decks()
        self._refresh_add_box()
        self._render_fields()
        self._sync_controls()

    # ------------------------------------------------------------------ workers
    def refresh_connection(self):
        if self.busy:
            return
        self.conn_var.set("● checking…")
        self.conn_lbl.config(foreground=MUTED)
        snap = self._snapshot()
        self._start(lambda: self._probe_worker(snap))

    def _probe_worker(self, snap):
        from app import anki_connect, anki_sync
        url, susp = snap["url"], snap["suspended"]
        report = anki_connect.probe(url)
        if not report.get("ok"):
            if not report.get("error"):
                report["error"] = "Anki isn't reachable. Start Anki with your profile open, then press ⟳."
            self.q.put(("__CONN__", report, [], None, {}, {}))
            return
        try:
            decks = anki_connect.deck_names(url)
            preselected = None
            if not snap["decks"]:
                everything = anki_sync.deck_study_counts(url, decks, susp)
                preselected = [d for d, n in sorted(everything.items(), key=lambda kv: -kv[1]) if n > 0]
            chosen = preselected if preselected is not None else snap["decks"]
            counts = anki_sync.deck_study_counts(url, chosen, susp) if chosen else {}
            models = anki_sync.models_in_scope(url, chosen, susp) if chosen else {}
        except anki_connect.AnkiError as e:
            # Anki answered the probe, then went away (or refused) mid-read.
            self.q.put(("__CONN__", {"ok": False, "error": f"Anki stopped answering: {e}"}, [], None, {}, {}))
            return
        self.q.put(("__CONN__", report, decks, preselected, counts, models))

    def _scope_worker(self, snap):
        from app import anki_sync
        from app import anki_connect
        url, decks, susp = snap["url"], snap["decks"], snap["suspended"]
        try:
            counts = anki_sync.deck_study_counts(url, decks, susp) if decks else {}
            models = anki_sync.models_in_scope(url, decks, susp) if decks else {}
        except anki_connect.AnkiError as e:
            self.q.put(("__MESSAGE__", f"Couldn't read your decks from Anki: {e}"))
            return
        self.q.put(("__SCOPE__", counts, models))

    def refresh_known(self):
        """A read-only count, so it runs beside the probe rather than taking the busy flag."""
        def work():
            try:
                from app import anki_sync
                self.q.put(("__KNOWN__", anki_sync.count_known(self.language),
                            anki_sync.load_state(self.language), anki_sync.count_backlog(self.language)))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _on_shift_sync(self, _event):
        if str(self.btn_sync.cget("state")) != tk.DISABLED:
            self.on_sync(full=True)
        return "break"

    def on_sync(self, full=False):
        if self.busy or not self._connected or not self.decks:
            return
        self._set_result("Re-reading every card…" if full else "Syncing…")
        snap = self._snapshot()
        self._start(lambda: self._sync_worker(full, snap))

    def _sync_worker(self, full, snap):
        from app import anki_sync
        with self._lock():
            result = anki_sync.sync(self.language, snap["url"], snap["decks"], snap["fields"],
                                    include_suspended=snap["suspended"], full=full)
            # The same decks' new cards, as the automatic sync reads them (read-only on Anki). Only a
            # count here, so it can never cost the sync its result.
            if not result.error:
                try:
                    anki_sync.sync_backlog(self.language, snap["url"], snap["decks"], snap["fields"])
                except Exception:
                    pass
        self.q.put(("__RESULT__", result, anki_sync.load_state(self.language),
                    anki_sync.count_backlog(self.language)))

    def on_replace(self):
        if self.busy or not self._connected or not self.decks:
            return
        self._set_result("Reading Anki…")
        snap = self._snapshot()
        self._start(lambda: self._dry_run_worker(snap))

    def _dry_run_worker(self, snap):
        from app import anki_sync
        result = anki_sync.replace(self.language, snap["url"], snap["decks"], snap["fields"],
                                   include_suspended=snap["suspended"], dry_run=True)
        self.q.put(("__DRYRUN__", result))

    def _confirm_replace(self, dry):
        if dry.error:
            self._set_result(dry.error, ERROR)
            return
        self._set_result("")
        message = (f"Your known words will go from {dry.total_known:,} to {dry.added:,} "
                   f"(from Anki only).")
        details = ("Words from Migaku, Jiten or earlier imports will be removed. Your current list "
                   "is backed up first, and you can put it back with Restore previous.")
        if ask(self, message, details, yes="Replace", no="Cancel"):
            self._set_result("Replacing…")
            snap = self._snapshot()
            self._start(lambda: self._replace_worker(snap))

    def _replace_worker(self, snap):
        from app import anki_sync
        with self._lock():
            result = anki_sync.replace(self.language, snap["url"], snap["decks"], snap["fields"],
                                       include_suspended=snap["suspended"])
        self.q.put(("__RESULT__", result, anki_sync.load_state(self.language)))

    def on_restore(self):
        if self.busy:
            return
        if not ask(self, "Put back your known words from before the last Replace?",
                   "Your current list is backed up first, so this can be undone too.",
                   yes="Restore", no="Cancel"):
            return
        self._set_result("Restoring…")
        self._start(self._restore_worker)

    def _restore_worker(self):
        from app import anki_sync
        with self._lock():
            result = anki_sync.restore_previous(self.language)
        self.q.put(("__RESULT__", result, anki_sync.load_state(self.language)))

    def _lock(self):
        """Shared with the dashboard's auto-sync, so two appends can't interleave."""
        lock = getattr(self.app, "_anki_sync_lock", None)
        if lock is None:
            lock = self._own_lock = getattr(self, "_own_lock", None) or threading.Lock()
        return lock

    def _show_result(self, result, state, backlog=None):
        if result.error:
            self._set_result(result.error, ERROR)
        else:
            if result.mode == "replace":
                text = f"Replaced: your known words are now the {result.added:,} from Anki."
            elif result.mode == "restore":
                text = "Restored your previous known words."
            else:
                words = f"+{result.added:,} word{'s' if result.added != 1 else ''}"
                text = f"Synced just now · {words} · {result.scanned:,} card{'s' if result.scanned != 1 else ''} checked"
            self._set_result(text, SECONDARY if (result.added or result.mode != "delta") else MUTED)
            if result.mode not in ("replace", "restore"):
                self._flash_delta(result.added)
        self._show_known(result.total_known, state, backlog)
        if self.app is not None and hasattr(self.app, "_on_anki_sync_result"):
            try:
                self.app._on_anki_sync_result(result, auto=False)
            except Exception:
                pass

    def open_apkg_importer(self):
        """The offline path: the existing .apkg importer, launched exactly as the dashboard did."""
        if self.app is not None and hasattr(self.app, "run_anki_importer"):
            self.app.run_anki_importer()
            self._close()

    def _start(self, worker):
        # Each job's __DONE__ carries its id. Replace's confirm dialog opens while the dry run's own
        # __DONE__ is still queued; unlabelled, that stale message arrived after Replace had started
        # and marked the window idle mid-replace — Sync and Replace clickable again.
        self._job += 1
        self._set_busy(True)
        threading.Thread(target=self._guarded(worker, self._job), daemon=True).start()

    def _guarded(self, worker, job=None):
        def run():
            try:
                worker()
            except Exception as e:           # a window must never lose a result to a traceback
                self.q.put(("__MESSAGE__", f"Unexpected error: {e}"))
            finally:
                self.q.put(("__DONE__", job))
        return run

    # ------------------------------------------------------------------- pump
    def _drain(self):
        self._drain_once()
        if not self._closing and self.winfo_exists():
            self.after(100, self._drain)

    def _drain_once(self):
        try:
            while True:
                item = self.q.get_nowait()
                tag = item[0]
                if tag == "__CONN__":
                    self._set_connection(*item[1:])
                elif tag == "__SCOPE__":
                    self._counts, self._models = dict(item[1]), dict(item[2])
                    self._render_decks()
                    self._render_fields()
                elif tag == "__KNOWN__":
                    self._show_known(*item[1:])
                elif tag == "__RESULT__":
                    self._show_result(*item[1:])
                elif tag == "__DRYRUN__":
                    self._set_busy(False)
                    self._confirm_replace(item[1])
                elif tag == "__MESSAGE__":
                    self._set_result(item[1], ERROR)
                elif tag == "__DONE__":
                    # Only the RUNNING job's completion frees the window (see _start).
                    if len(item) < 2 or item[1] is None or item[1] == self._job:
                        self._set_busy(False)
        except queue.Empty:
            pass


def open_anki_sync(host):
    """Open (or focus) the window. `host` is the MasterDashboardApp. Never raises past a messagebox."""
    try:
        parent = getattr(host, "root", host)
        win = getattr(host, "anki_sync_window", None)
        if win is None or not win.winfo_exists():
            lang = host.var_language.get() if hasattr(host, "var_language") else "ja"
            host.anki_sync_window = AnkiSyncGui(parent, app=host, language=lang)
        else:
            win.lift()
            win.focus_force()
    except Exception as e:
        print(f"Error launching Anki Known Words: {e}")
        messagebox.showerror("Error", f"Could not open Anki Known Words:\n{e}")

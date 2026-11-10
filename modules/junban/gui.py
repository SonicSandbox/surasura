# SPDX-License-Identifier: GPL-3.0-or-later
"""The 順番 panel: the one place a user can move a card, and the one confirmation they get.

    probe  ->  choose a scope  ->  PREVIEW  ->  Reorder        (and, if it went wrong, Restore)

Everything below this file already decides everything; this one renders it and asks. Three rules
shape the whole window, and each of them exists because of what `setSpecificValueOfCard` is:

**The preview is the confirmation (invariant I5).** `Reorder` is disabled until a preview has been
generated *for the scope currently selected*, because AnkiConnect writes no undo entry and the write
syncs to AnkiWeb and mobile. Changing the deck or the scope throws the preview away and greys the
button again — a confirmation that describes a different deck from the one about to move is not a
confirmation. The table it shows is built from `stats["order"]`, the planner's own rows, so the
preview is not a second implementation of the ordering free to disagree with the one that writes.
That holds for the rows the user clicks off too (WP-O): the table is the checkbox `ttk` does not
have, and a click re-plans the whole answer through `plan` itself rather than patching the row —
so the numbers, the sentence and the order on screen are never one click out of date.

**Anki being closed is a state, not an error.** The connection row is a live probe and the panel
opens degraded when it fails — it says Anki has to be running rather than blowing up on the first
button press. Every engine call is wrapped: `dry_run` raises `AnkiError` when the connection dies
mid-read, and a preview that silently reported "0 cards" would read as "nothing to do".

**Nothing touches Tk from a worker.** Every long call (the probe, the preview, the writes, the
restore) runs on a daemon thread and speaks to the window only through `self.q`, drained by an
`after()` pump on the UI thread. The pump and the opening probe are both gated on
`SURASURA_NO_UI_TIMERS`, because a pending `after` whose Tcl command died with the interpreter
fires into nothing for the rest of a test session — and because a test must never reach the
developer's live collection.

Theming
-------
`ttk` styles are process-global. This window is opened in-process by the dashboard (`default`) and
could equally be opened from the Content Manager (`clam`), so it never switches the theme: it claims
the base style only when `ensure_styleable_theme` says it is standalone, and otherwise only layers
its own `Jun.*` named styles. See `GUI_Design_Guidelines.md` §2.1.

"Also update the cards" (WP-L)
------------------------------
The one group in this window that writes the user's own words rather than a queue position, and
therefore the one that arrives **collapsed**: a tag, the word's frequency number, an extra example
sentence. The two that overwrite anything are off until switched on and the sentence field has no
default at all, so the feature is simply absent until a field is named. Changing any of it throws
the preview away exactly as changing the deck does — the preview's single sentence is "will move 47
cards and tag 47 notes", and a preview taken with the tag off is not a confirmation of a run with it
on. The field pickers are filled from the note fields the last preview actually found, never from a
guess.

Two orders and three markers (WP-M / WP-N)
------------------------------------------
Two more compact rows under the scope. `Order:` chooses between the order the words will actually
be met in (the default) and raw leverage, `List first` puts the list's own words ahead of every
card it cut off as too rare, and `Phrases` places the phrase cards met as often as the list's words
as if they were on it; `Only:` narrows the run to words carrying ✦ / ⚖ / 📖.
All are part of `_scope_key`, because all change the order that is about to be written rather
than a detail of it, and the preview table carries a marker column so the glyphs are visible per
row before anything is written. A word the filter excludes is simply unmatched — it keeps its
current place, at the back — which is why nothing here needs a new ordering concept.

Settings
--------
The scope widgets and that group are the only settings this panel writes (`junban_scope`,
`junban_deck`, `junban_order`, `junban_unlisted`, `junban_phrases`, `junban_only_markers` and WP-L's six plus
`junban_tag_markers`),
and it writes them scalar. `junban_word_fields` is **copied, never
mutated**: `settings_manager` merges
module defaults with a shallow `dict.update()`, so the dict in loaded settings *is* the one inside
`SETTINGS_DEFAULTS` and editing it in place poisons the default for the whole process
(spec §13 #12).
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from app import replan_preview
from modules.junban import (connect, first_touch_gui, match, pairs, reposition, spaced, touchup, undo,
                            unlisted)

# WP-N. The glyphs the report uses, and the ONLY place they appear: the tags junban writes are ASCII
# (`Surasura::star`) because a tag has to be typable in Anki's search box. Here they are labels on a
# checkbox and a column in the preview, where a glyph is worth three words.
#
# All three are TEXT glyphs, never emoji. An emoji comes from a colour font that Anki's card
# renderer and several UI fonts simply do not carry, so it lands as a blank box — and these marks
# have to survive wherever the user ends up looking at them.
#
# `reading` was 📖, which was wrong twice over: it is an emoji, and in the report 📖 is the *epub
# source* icon, not the reading marker. The report uses 文 (`web_app.html:321`), so this now matches
# what the user already reads there.
#
# `lopsided` carries U+FE0E (variation selector-15) to force the text presentation of ⚖, which
# several platforms otherwise draw from the colour font.
MARKER_GLYPHS = {"star": "☆", "lopsided": "⚖︎", "reading": "文"}

# WP-O. What the `#` column shows for a row the user has clicked off. A `ttk.Treeview` has no
# checkbox and the panel has no room for a column of its own, so the sequence number doubles as
# one: a number means "in this run", this means "not". Text, never an emoji, for the same reason
# the markers are.
DESELECTED_GLYPH = "✗"

# Junban_Backlog_Spec §16: "Same word as one on your list?" — a tick box per row, text glyphs like
# the ones above, and at most this many rows tall (it scrolls beyond): the preview keeps the room.
CHECK_OFF, CHECK_ON = "☐", "☑"
CHECK_ROWS = 4


def returning_clause(stats):
    """" Back on your list: unsuspend 2 cards Junban had set aside." — MR-R3's promise (Connect's preview), stated
    before the write (I5); "" when there are none."""
    count = len((stats or {}).get("returning") or ())
    if not count:
        return ""
    return f" Back on your list: unsuspend {count} card{'' if count == 1 else 's'} Junban had set aside."


def marker_glyphs(marks):
    """The glyphs for one word's markers, in a stable order. `""` when it carries none (38%)."""
    marks = marks or ()
    return "".join(MARKER_GLYPHS[name] for name in match.MARKERS if name in marks)

# --- Surasura palette (GUI_Design_Guidelines.md) --- #
BG = "#1e1e1e"
SURFACE = "#2d2d2d"
TEXT = "#e0e0e0"
MUTED = "#9a9a9a"
ACCENT = "#bb86fc"
SECONDARY = "#03dac6"
ERROR = "#cf6679"

# Not in the guidelines' table: the dashboard already uses a dimmer grey for "here, but not yet
# your turn", and an unmatched row in the preview is exactly that.
DISABLED = "#5c5c5c"

TITLE = "順番 (Junban)"

# How many preview rows are rendered. The table IS the confirmation, so it shows the whole scope;
# this only stops a pathological collection (tens of thousands of new cards) from spending a minute
# inside Tk before the user can answer. The banner above says when it has been cut.
MAX_PREVIEW_ROWS = 4000


def window_job(settings):
    """The 順 window's own preview and run: spaced numbers (E1.1 03; one numbering for every Junban writer), its
    snapshot as in 2.5 (not automatic). 3.0 (E1.1 04 §5, W3.5 row 7): always — whatever D29, the language or the
    preview's box say (2.x numbered dense while the preview was off)."""
    return spaced.Job()


class ToolTip:
    """Hover tooltip per the Surasura GUI guidelines (wraps text over 50 characters). `text` is a string, or — as
    the dashboard's own — a zero-argument callable read on each hover, for a tip whose numbers change."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self.tip:
            return
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 25
        self.tip = window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")
        wrap = 240 if len(text) > 50 else 0
        tk.Label(window, text=text, justify=tk.LEFT, background=SURFACE, foreground=TEXT,
                 relief=tk.SOLID, borderwidth=1, wraplength=wrap, padx=6, pady=4).pack()

    def _hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class JunbanDialog(tk.Toplevel):
    """A themed yes/no, in the app's own palette.

    `tkinter.messagebox` hands off to the native Windows dialog, which arrives white and
    system-font in the middle of a dark window. Esc and the close button both mean **no**: this is
    only ever used in front of a write to the user's collection, and a prompt that treats being
    dismissed as consent is not a prompt.
    """

    def __init__(self, parent, message, details=None, title=TITLE, yes="Continue", no="Cancel", default=True):
        super().__init__(parent)
        self.answer = False

        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)

        frame = ttk.Frame(self, padding=18, style="Jun.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=message, style="Jun.TLabel", justify=tk.LEFT,
                  wraplength=420).pack(anchor="w")
        if details:
            ttk.Label(frame, text="\n".join(details), style="JunMuted.TLabel", justify=tk.LEFT,
                      wraplength=420).pack(anchor="w", pady=(10, 0))

        buttons = ttk.Frame(frame, style="Jun.TFrame")
        buttons.pack(fill=tk.X, pady=(16, 0))
        decline = ttk.Button(buttons, text=no, width=12, style="Jun.TButton",
                             command=lambda: self._done(False))
        decline.pack(side=tk.RIGHT)
        ToolTip(decline, "Stop here. Nothing in Anki is changed.")
        accept = ttk.Button(buttons, text=yes, width=12, style="Jun.TButton",
                            command=lambda: self._done(True))
        accept.pack(side=tk.RIGHT, padx=(0, 8))
        ToolTip(accept, "Go ahead.")

        self.bind("<Escape>", lambda _e: self._done(False))
        self.bind("<Return>", lambda _e: self._done(default))     # `default`: what Enter answers
        self.protocol("WM_DELETE_WINDOW", lambda: self._done(False))

        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.wait_window(self)

    def _done(self, answer):
        self.answer = answer
        self.destroy()


def ask(parent, message, details=None, title=TITLE, yes="Continue", no="Cancel", default=True):
    """A themed yes/no. Falls back to the native dialog only if the themed one cannot be built. `default` is what
    Enter answers (a question whose safe answer is no: FT's older changes)."""
    try:
        return JunbanDialog(parent, message, details=details, title=title, yes=yes, no=no, default=default).answer
    except tk.TclError:
        if details:
            message = message + os.linesep * 2 + os.linesep.join(list(details)[:12])
        return bool(messagebox.askyesno(title, message, parent=parent,
                                        **({} if default else {"default": messagebox.NO})))


def init_styles(window):
    """Layer the `Jun.*` styles on `window`; claim the base theme only when standalone.

    `ttk` styles are process-global, so switching the theme here would repaint whatever host
    opened us — which is exactly how the Content Manager once went white and unreadable
    (`GUI_Design_Guidelines.md` §2.1). Shared by 順 and the Anki Backfill window, so the two
    look alike by construction rather than by copy.
    """
    from app.ui_theme import ensure_styleable_theme
    style = ttk.Style(window)
    if ensure_styleable_theme(window):
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=SURFACE,
                        font=("Segoe UI", 10))

    # The combobox's dropdown is a Tk listbox, not a ttk widget, so it is themed by option.
    window.option_add("*TCombobox*Listbox.background", SURFACE)
    window.option_add("*TCombobox*Listbox.foreground", TEXT)
    window.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    window.option_add("*TCombobox*Listbox.selectForeground", BG)

    style.configure("Jun.TFrame", background=BG)
    style.configure("Jun.TLabel", background=BG, foreground=TEXT)
    style.configure("JunMuted.TLabel", background=BG, foreground=MUTED)
    style.configure("JunHeader.TLabel", background=BG, foreground=SECONDARY,
                    font=("Segoe UI", 18, "bold"))
    style.configure("JunField.TLabel", background=BG, foreground=ACCENT,
                    font=("Segoe UI", 9, "bold"))
    style.configure("JunState.TLabel", background=BG, foreground=MUTED,
                    font=("Segoe UI", 10, "bold"))
    style.configure("JunCheck.TLabel", background=BG, foreground=TEXT,
                    font=("Segoe UI", 10, "bold"))
    style.configure("JunCount.TLabel", background=BG, foreground=ACCENT,
                    font=("Segoe UI", 10, "bold"))
    style.configure("JunLink.TLabel", background=BG, foreground=MUTED,
                    font=("Segoe UI", 9, "underline"))

    style.configure("Jun.TButton", background=SURFACE, foreground=TEXT, borderwidth=0,
                    padding=8, font=("Segoe UI", 10, "bold"))
    style.map("Jun.TButton",
              # Disabled keeps the surface fill: BG on BG makes the button vanish rather than
              # read as "here, but not yet".
              background=[("active", ACCENT), ("pressed", ACCENT), ("disabled", SURFACE)],
              foreground=[("active", BG), ("pressed", BG), ("disabled", "#6b6b6b")])
    # A small secondary action (Anki Backfill's field target, "Copy card style"): room around its text.
    style.configure("JunSmall.TButton", background=SURFACE, foreground=TEXT, borderwidth=0,
                    padding=(12, 5), font=("Segoe UI", 9))
    style.map("JunSmall.TButton",
              background=[("active", ACCENT), ("pressed", ACCENT), ("disabled", SURFACE)],
              foreground=[("active", BG), ("pressed", BG), ("disabled", "#6b6b6b")])
    # A "?" / "ⓘ" that explains on hover.
    style.configure("JunHelp.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI", 10, "bold"))
    style.configure("JunIcon.TButton", background=SURFACE, foreground=TEXT, borderwidth=0,
                    padding=4, font=("Segoe UI", 11))
    style.map("JunIcon.TButton",
              background=[("active", ACCENT), ("pressed", ACCENT), ("disabled", SURFACE)],
              foreground=[("active", BG), ("pressed", BG), ("disabled", "#6b6b6b")])

    style.configure("Jun.TCheckbutton", background=BG, foreground=TEXT)
    style.map("Jun.TCheckbutton", background=[("active", BG), ("disabled", BG)],
              foreground=[("active", ACCENT), ("disabled", DISABLED)],
              # The indicator box itself is drawn by the base theme and defaults to white.
              indicatorcolor=[("selected", ACCENT), ("active", SURFACE), ("!selected", SURFACE)],
              indicatorbackground=[("selected", ACCENT), ("active", SURFACE),
                                   ("!selected", SURFACE), ("disabled", BG)])
    style.configure("Jun.TEntry", fieldbackground=SURFACE, foreground=TEXT,
                    insertcolor=TEXT, borderwidth=0, padding=4)
    style.map("Jun.TEntry", fieldbackground=[("disabled", "#262626")],
              foreground=[("disabled", DISABLED)])

    style.configure("Jun.TRadiobutton", background=BG, foreground=TEXT)
    style.map("Jun.TRadiobutton", background=[("active", BG), ("disabled", BG)],
              foreground=[("active", ACCENT), ("disabled", DISABLED)],
              indicatorcolor=[("selected", ACCENT), ("active", SURFACE), ("!selected", SURFACE)],
              indicatorbackground=[("selected", ACCENT), ("active", SURFACE),
                                   ("!selected", SURFACE), ("disabled", BG)])

    style.configure("Jun.TCombobox", fieldbackground=SURFACE, background=SURFACE,
                    foreground=TEXT, arrowcolor=ACCENT,
                    selectbackground=SURFACE, selectforeground=TEXT)
    style.map("Jun.TCombobox",
              fieldbackground=[("disabled", "#262626"), ("readonly", SURFACE)],
              foreground=[("disabled", DISABLED), ("readonly", TEXT)],
              selectbackground=[("readonly", SURFACE)], selectforeground=[("readonly", TEXT)],
              arrowcolor=[("disabled", DISABLED)])

    style.configure("Jun.Horizontal.TProgressbar", thickness=6, background=ACCENT,
                    troughcolor=SURFACE, borderwidth=0)
    style.configure("Jun.Vertical.TScrollbar", background=SURFACE, troughcolor=BG,
                    bordercolor=BG, arrowcolor=TEXT, darkcolor=SURFACE, lightcolor=SURFACE)

    # Named so the host's own Treeview styling is left alone — `Jun.Treeview` inherits the
    # Treeview layout while carrying only our colours.
    style.configure("Jun.Treeview", background=SURFACE, foreground=TEXT,
                    fieldbackground=SURFACE, borderwidth=0, font=("Segoe UI", 10),
                    rowheight=26)   # CJK at 10pt clips at ttk's default 20
    style.map("Jun.Treeview",
              background=[("selected", ACCENT)], foreground=[("selected", BG)])
    # A `configure` with no `map` is only half a style: ttk paints the ACTIVE and PRESSED
    # states from the base theme, whose active fill is near-white. Hovering the column headings
    # flashed them stark white against the dark panel. Every interactive element below carries
    # an explicit map for the same reason.
    style.map("Jun.Treeview.Heading",
              background=[("active", SURFACE), ("pressed", SURFACE)],
              foreground=[("active", TEXT), ("pressed", TEXT)],
              relief=[("active", "flat"), ("pressed", "flat")])
    style.configure("Jun.Treeview.Heading", background=BG, foreground=MUTED,
                    font=("Segoe UI", 9, "bold"), relief="flat")


class JunbanGui(tk.Toplevel):
    """The panel. `app` is the dashboard when there is one — it is only ever read, never driven."""

    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        self.q = queue.Queue()
        self.busy = False
        self._auto_previewed = False   # one automatic preview per window, not per probe
        # Card ids in the order the table is DRAWN. Fixed at the first render of a preview so a
        # deselected row stays where the user clicked it (see _in_display_order); cleared with
        # the preview, because a new read is a new list.
        self._display_order = []
        self._closing = False
        # Set when the window closes: a reorder or restore still waiting for another Anki writer stops
        # without writing (E1.4 §W).
        self._stop = threading.Event()
        # While open, the window holds `junban-window` (P0.3 04 §2): the automatic reorder and `surasura-cli junban
        # --auto` stand aside instead of moving the queue this preview describes. Taken and let go on a worker.
        self._window_lock = None
        self._window_lock_guard = threading.Lock()
        self._window_lock_owner = object()      # the hold outlives the worker that takes it (locks.take's `owner`)
        threading.Thread(target=self._hold_window_lock, daemon=True).start()

        # The scope a preview was generated for — `None` means "no preview", which is what keeps
        # Reorder disabled (I5). Compared against the live widgets, so switching decks invalidates.
        self._preview_scope = None
        self._decks = []                # deck names offered in the combobox (from Anki)
        self._connected = False

        # WP-O. The rows the user has clicked off, for THIS preview only — never a setting, never
        # saved, and dropped the moment the preview is (an exclusion the user cannot see is a trap).
        # The last dry run is kept beside it so a toggle can redraw the whole answer without going
        # back to Anki for it.
        self._deselected = set()        # card ids
        self._row_cards = {}            # tree item -> card id
        self._row_whys = {}             # card id -> why it was placed ("list #12"), before any toggle
        self._preview_stats = None
        self._preview_checks = None

        # §16. What the user has ticked in "Same word as one on your list?" — `{card_word: bool}`
        # for THIS preview, recorded only when Reorder is pressed and dropped with the preview, like
        # a clicked-off row. None until a preview has set it up.
        self._ticked = None
        self._show_earlier = False
        self._check_rows = {}           # check-list item -> card word

        # §16.9: is the list the preview reads up to date? The Generate button's own question, asked
        # of the dashboard (None: no dashboard, or it could not tell). False turns Preview order
        # into "Generate & preview" and keeps Reorder shut.
        self._list_current = None
        self._generating = False
        self._generate_tried = False

        self.title(f"Surasura - {TITLE}")
        self.configure(bg=BG)
        # Fits a 1280x720 display with the taskbar showing. The panel grew controls over time
        # and a default taller than the screen silently pushes the action row off the bottom,
        # which looks like the buttons are missing rather than like a window too big.
        self.geometry("780x660")
        self.minsize(700, 560)
        self.bind("<Escape>", lambda _e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._init_styles()
        self._build_ui()
        self._sync_buttons()

        # Guard the SCHEDULING, not the callback: a pending `after` whose Tcl command died with the
        # interpreter keeps firing for the rest of a test session — and the probe would reach the
        # developer's own live collection.
        if not os.environ.get("SURASURA_NO_UI_TIMERS"):
            self.after(100, self._drain)
            self.after(50, self.refresh_connection)

    def _hold_window_lock(self):
        """Take `junban-window` for as long as the window is open. Waits a moment, past another program's look at
        it; another Surasura's 順 window holding it, or no lock folder, leaves this one without it."""
        try:
            from app import locks
            held = locks.take("junban-window", "the 順 window", wait=2.0, owner=self._window_lock_owner)
        except Exception:
            return
        with self._window_lock_guard:
            if not self._closing:
                self._window_lock, held = held, None
        if held is not None:                    # closed meanwhile
            held.release()

    def _close(self):
        self._closing = True
        self._stop.set()
        with self._window_lock_guard:
            held, self._window_lock = self._window_lock, None
        if held is not None:
            threading.Thread(target=held.release, daemon=True).start()
        self.destroy()

    # ------------------------------------------------------------------- styling
    def _init_styles(self):
        """This window's styles — see `init_styles`."""
        init_styles(self)

    # -------------------------------------------------------------------- layout
    def _build_ui(self):
        main = ttk.Frame(self, padding=10, style="Jun.TFrame")
        main.pack(fill=tk.BOTH, expand=True)

        # The title shares its row with the connection light and the recheck button (see
        # _build_connection) — a status line does not earn a row of its own on a short screen.
        self._title_row = ttk.Frame(main, style="Jun.TFrame")
        self._title_row.pack(fill=tk.X)
        ttk.Label(self._title_row, text=TITLE, style="JunHeader.TLabel").pack(side=tk.LEFT)
        # One line, and wraplength so a narrow window folds it rather than truncating mid-word.
        # The screen this is designed against is 720px tall; every row of chrome the header takes
        # is a row the preview table loses, and the table is what the window exists to show.
        ttk.Label(main,
                  text="Puts the new cards waiting in Anki into Surasura's learn order. "
                       "Nothing is added, deleted or rescheduled.",
                  style="JunMuted.TLabel", justify=tk.LEFT, wraplength=740).pack(
            anchor="w", pady=(2, 8))

        # Bottom-up: the buttons and the message pane are packed against the bottom BEFORE the
        # table claims the rest, so shrinking the window can never push the actions off-screen.
        # Packed in reverse visual order for the same reason.
        self._build_connection(main)
        self._build_scope(main)
        self._build_order(main)
        self._build_touchups(main)
        self._build_match(main)
        self._build_checks(main)
        self._build_actions(main)
        self._build_preview(main)

    def _build_connection(self, parent):
        """The connection state rides on the TITLE row rather than taking one of its own.

        It is a status light, not a control — one word plus a dot. Giving it a full labelled row
        cost a row of the preview table on a 720px-tall screen, which is a bad trade for a line
        that says "connected" and nothing else.
        """
        row = self._title_row
        self.btn_recheck = ttk.Button(row, text="⟳", width=3, style="JunIcon.TButton",
                                      command=self.refresh_connection)
        self.btn_recheck.pack(side=tk.RIGHT)
        ToolTip(self.btn_recheck, "Check again whether Anki is running with AnkiConnect, and "
                                  "refresh the list of decks.")

        self.conn_var = tk.StringVar(value="● not checked yet")
        self.conn_lbl = ttk.Label(row, textvariable=self.conn_var, style="JunState.TLabel")
        self.conn_lbl.pack(side=tk.RIGHT, padx=(0, 10))
        self.btn_backfill = ttk.Button(row, text="Backfill…", style="JunIcon.TButton",
                                       command=self.open_backfill)
        self.btn_backfill.pack(side=tk.RIGHT, padx=(0, 12))
        ToolTip(self.btn_backfill, "Fill fields on your cards from Surasura.")

    def open_backfill(self):
        """The Anki Backfill window — the same one the Anki window opens: inside Surasura the
        dashboard keeps it, so either door brings the one window forward."""
        from modules.junban import open_backfill
        open_backfill(self.app if hasattr(self.app, "root") else self)

    def _build_scope(self, parent):
        row = ttk.Frame(parent, style="Jun.TFrame")
        row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(row, text="Scope:", style="Jun.TLabel", width=7).pack(side=tk.LEFT)

        saved = self._saved_settings()
        self.scope = tk.StringVar(value="all" if saved.get("junban_scope") == "all" else "deck")
        self.deck = tk.StringVar(value=str(saved.get("junban_deck") or ""))

        one = ttk.Radiobutton(row, text="This deck:", variable=self.scope, value="deck",
                              style="Jun.TRadiobutton", command=self._on_scope_changed)
        one.pack(side=tk.LEFT)
        ToolTip(one, "Reorder only the deck chosen here. Its subdecks are included, the same way "
                     "Anki's own deck search works.")

        self.deck_box = ttk.Combobox(row, textvariable=self.deck, state="readonly", width=28,
                                     style="Jun.TCombobox",
                                     values=[self.deck.get()] if self.deck.get() else [])
        self.deck_box.pack(side=tk.LEFT, padx=(6, 16))
        self.deck_box.bind("<<ComboboxSelected>>", lambda _e: self._on_deck_picked())
        ToolTip(self.deck_box, "Only decks that actually hold unsuspended new cards are listed — "
                               "reordering any other deck would do nothing.")

        every = ttk.Radiobutton(row, text="All decks", variable=self.scope, value="all",
                                style="Jun.TRadiobutton", command=self._on_scope_changed)
        every.pack(side=tk.LEFT)
        ToolTip(every, "Reorder every deck that has unsuspended new cards, as one queue.")

        self.counts_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.counts_var, style="JunMuted.TLabel").pack(
            anchor="w", padx=(56, 0))

    def _build_order(self, parent):
        """Two compact rows: which order to follow (WP-M), and which words to follow it for (WP-N).

            Order:  ( ) As I'll meet it    ( ) By leverage    [x] List first  [x] Phrases
            Only:   [ ] ✦ high leverage   [ ] ⚖ lopsided   [ ] 📖 reading

        Deliberately terse. The window is already dense, and the difference between the two orders
        takes a paragraph to explain properly — so the paragraph lives in the tooltip and the label
        says only which one you are picking.

        Both belong in `_scope_key`, exactly as the deck and the touch-ups do: changing either
        changes the order about to be written, and a preview of a different order is not a
        confirmation of this one (invariant I5).
        """
        saved = self._saved_settings()

        row = ttk.Frame(parent, style="Jun.TFrame")
        row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(row, text="Order:", style="Jun.TLabel", width=7).pack(side=tk.LEFT)

        self.order = tk.StringVar(
            value="priority" if saved.get("junban_order") == "priority" else "content")
        met = ttk.Radiobutton(row, text="As I'll meet it", variable=self.order, value="content",
                              style="Jun.TRadiobutton", command=self._on_scope_changed)
        met.pack(side=tk.LEFT)
        ToolTip(met, "Follow the order your own library will actually show you these words in — "
                     "file by file, through the study order in your library, then the best words "
                     "inside each file. The front of the queue is whatever you are about to watch "
                     "or read.")
        leverage = ttk.Radiobutton(row, text="By leverage", variable=self.order, value="priority",
                                   style="Jun.TRadiobutton", command=self._on_scope_changed)
        leverage.pack(side=tk.LEFT, padx=(16, 0))
        ToolTip(leverage, "Follow Surasura's priority list instead: the words that unlock the most "
                          "of your library first, wherever they happen to appear. Higher payoff per "
                          "word, but the very first word may not turn up for months.")

        # Junban_Backlog_Spec §12: the list's own words ahead of every card it cut off as too rare —
        # the user's rule (2026-09-23), and the default. Unticked, a word the list cut off goes where
        # the journey meets it, among the list's. A hand-set "back" (v1) reads as ticked and is kept.
        self._unlisted_saved = str(saved.get("junban_unlisted") or "").strip().lower()   # as the engine reads it
        self.list_first = tk.BooleanVar(value=self._unlisted_saved != "journey")
        first = ttk.Checkbutton(row, text="List first", variable=self.list_first,
                                style="Jun.TCheckbutton", command=self._on_scope_changed)
        first.pack(side=tk.LEFT, padx=(16, 0))
        ToolTip(first, "Every word on your list comes first, with the phrases you meet as often as "
                       "its words. The ones it cut off as too rare go after them. Untick to place "
                       "each where your journey meets it, among the list's words.")

        # Your list counts a phrase's words separately (気がつく is 気 + が + 付く), so Junban looks each
        # phrase card up whole in the library. On by default; unticked, they wait with the rest.
        self.phrases = tk.BooleanVar(value=saved.get("junban_phrases", True) is not False)
        phrases = ttk.Checkbutton(row, text="Phrases", variable=self.phrases,
                                  style="Jun.TCheckbutton", command=self._on_scope_changed)
        phrases.pack(side=tk.LEFT, padx=(12, 0))
        ToolTip(phrases, "Phrase and compound cards (気がつく, ことが出来る) that are no row of your list, "
                         "but that you meet as often as its words, are placed as if they were on it, with "
                         "the episode you first meet them in. A phrase your list has a row for (Settings' "
                         "\"Idioms and set phrases on your list\") goes on that row either way. Untick to "
                         "put the others with the rest.")

        # Junban_Backlog_Spec §17 (the user, 2026-09-24): a list card whose own sentence holds a list
        # word it comes before gets that word's card first, or waits. Off by default.
        self.ready_first = tk.BooleanVar(value=saved.get("junban_ready_first") is True)
        ready = ttk.Checkbutton(row, text="i+1 first", variable=self.ready_first,
                                style="Jun.TCheckbutton", command=self._on_scope_changed)
        ready.pack(side=tk.LEFT, padx=(12, 0))
        ToolTip(ready, "A card on your list whose own sentence still has a word from your list that "
                       "you'd learn after it: that word's card is brought right before it — when that "
                       "card is i+1 there — so you learn it first. Otherwise the card waits with the "
                       "cards of more new words. Words too rare for your list never count; a name counts "
                       "like any word unless Settings' Ignore names is on. Never a chain: a card brought "
                       "forward brings nothing else.")

        # Shares the Order row. Both answer "which words, in what order", and on a 720px-tall
        # screen a row of its own costs a row of the preview — which is the confirmation.
        marks = row
        ttk.Label(marks, text="Only:", style="Jun.TLabel").pack(side=tk.LEFT, padx=(24, 4))

        chosen = set(match.normalize_markers(saved.get("junban_only_markers")))
        self.only_markers = {}
        for marker, label, tip in (
                ("star", "high leverage",
                 "Reorder only the words the report stars — enough occurrences, and spread across "
                 "the content you are working towards. Leave every box unticked to reorder "
                 "everything."),
                ("lopsided", "lopsided",
                 "Reorder only the words that come almost entirely from one part of your library. "
                 "Useful for clearing out a single show's vocabulary; there are very few of them."),
                ("reading", "reading",
                 "Reorder only the words you will read but essentially never hear, so they can be "
                 "learned reading-first.")):
            variable = tk.BooleanVar(value=marker in chosen)
            self.only_markers[marker] = variable
            # The GLYPH alone. It is the same mark the report uses and the same one the preview's
            # own column shows two rows below, so the word beside it was pure duplication — and
            # spelled out, the three of them overflowed the row and clipped the last one off the
            # window. The meaning lives in the tooltip, which is what tooltips are for.
            box = ttk.Checkbutton(marks, text=MARKER_GLYPHS[marker], variable=variable,
                                  style="Jun.TCheckbutton", command=self._on_scope_changed)
            box.pack(side=tk.LEFT, padx=(0, 10))
            # Every box says the same thing at the end, because it is the non-obvious half: a word
            # that fails the filter is not dropped, it simply keeps the place it already had.
            ToolTip(box, tip + " Words that do not carry it keep their current order, at the back.")

        self._build_replan(parent, saved)

        # P1.4-1 (Sonic, 2026-10-06), with Connect's preview on only: your own cards go ahead of Connect's in the order
        # you mined them, never suspended — and you can say which they are, or order them by the list too.
        self.own_tag = self.order_all = None
        if not connect.preview_on(saved):
            return
        yours = ttk.Frame(parent, style="Jun.TFrame")
        yours.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(yours, text="My own cards have this tag:", style="Jun.TLabel").pack(side=tk.LEFT)
        self.own_tag = tk.StringVar(value=connect.own_tag(saved))
        entry = ttk.Entry(yours, textvariable=self.own_tag, width=16, style="Jun.TEntry")
        entry.pack(side=tk.LEFT, padx=(6, 0))
        entry.bind("<FocusOut>", lambda _e: self._on_scope_changed())
        entry.bind("<Return>", lambda _e: self._on_scope_changed())
        ToolTip(entry, "Cards you mine yourself go ahead of the ones Surasura Connect makes, in the order "
                       "you mined them, and are never suspended. Without a tag, that's every card without "
                       "Connect's tag mined since Connect's first. Type a tag (immersion) and every card "
                       "carrying it is yours too, whenever you mined it.")
        self.order_all = tk.BooleanVar(value=connect.order_all(saved))
        box = ttk.Checkbutton(yours, text="Order all cards by the list", variable=self.order_all,
                              style="Jun.TCheckbutton", command=self._on_scope_changed)
        box.pack(side=tk.LEFT, padx=(16, 0))
        ToolTip(box, "Put your own cards in your list's order too, among Connect's, instead of ahead of "
                     "them. They are still never suspended.")

    def _own_values(self):
        """`junban_own_tag` / `junban_order_all` as the window shows them; {} when the row isn't there (the
        Connect preview off): nothing of them is handed on or saved."""
        try:
            if self.own_tag is None:
                return {}
            return {"junban_own_tag": self.own_tag.get().strip(), "junban_order_all": bool(self.order_all.get())}
        except (AttributeError, tk.TclError):
            return {}

    # The fast re-plan's sync choices (E1.1 04 §3, S4: `anki_sync_delay_min`): the words shown -> the value saved.
    SYNC_CHOICES = (("about a minute after", 1), ("right away", 0), ("5 minutes after", 5),
                    ("only at start and Anki's close", "off"))

    def _build_replan(self, parent, saved):
        """The fast re-plan's preview (E1.1 04 §1; 2.6): one row under the order it keeps up to date.

            [ ] Re-order Anki as I move content (preview)    Sync AnkiWeb: [about a minute after ▾]

        Greyed, with the reason in its tooltip, where it can't run (D7: not one deck, Coverage, "Only i+1"). Saved
        only once touched (`_replan_values`): a window that just opens never writes its default into settings.json.
        It belongs in `_scope_key`: on, the preview and the run number spaced (03), and a preview of one numbering is
        no confirmation of the other (I5)."""
        row = ttk.Frame(parent, style="Jun.TFrame")
        row.pack(fill=tk.X, pady=(8, 0))
        # On for the language it was switched on in (its deck's: `junban_deck` is one key for both languages). The
        # window's language is fixed here, as it opens: a later switch of the dashboard's language never records the
        # other language with this window's deck (E3.1 review 3 R3).
        self._replan_language = self._lang_code()
        self.replan_on = tk.BooleanVar(value=saved.get("junban_replan_preview") is True
                                       and replan_preview.preview_language(saved) == self._replan_language)
        self._replan_saved_delay = saved.get("anki_sync_delay_min", 1)
        self._replan_touched = False
        self.replan_box = ttk.Checkbutton(row, text="Re-order Anki as I move content (preview)",
                                          variable=self.replan_on, style="Jun.TCheckbutton",
                                          command=self._on_replan_changed)
        self.replan_box.pack(side=tk.LEFT)
        ToolTip(self.replan_box, self._replan_tip)
        ttk.Label(row, text="Sync AnkiWeb:", style="Jun.TLabel").pack(side=tk.LEFT, padx=(16, 4))
        delay = saved.get("anki_sync_delay_min", 1)
        shown = next((label for label, value in self.SYNC_CHOICES if value == delay), None)
        self.sync_choice = tk.StringVar(value=shown or f"{delay} minutes after")
        self.sync_box = ttk.Combobox(row, textvariable=self.sync_choice, state="readonly", width=26,
                                     values=[label for label, _value in self.SYNC_CHOICES])
        self.sync_box.pack(side=tk.LEFT)
        self.sync_box.bind("<<ComboboxSelected>>", lambda _e: self._on_replan_changed())
        ToolTip(self.sync_box, "While Re-order as I move is on, Surasura asks Anki to sync with AnkiWeb once when it "
                               "first writes in a session (so reviews from your phone arrive first) and again this "
                               "long after a move changes tomorrow's cards. Anki's own sync on close does the rest. "
                               "Only your own AnkiWeb account, through Anki.")
        self._sync_replan_row()

    def _replan_tip(self):
        why = replan_preview.unavailable(self._settings()) if replan_preview.junban_present() else None
        tip = ("For this language's deck: moving content in the Content Manager re-orders Anki's new cards about a "
               "second later — tomorrow's "
               "cards first — without a Generate. While on, a Generate also re-orders Anki, every re-order keeps the "
               "numbers spaced out so a move rewrites only tens of cards (the first time, all of them, once), and "
               "Surasura asks Anki to sync (see Sync AnkiWeb). Turning it off renumbers your cards one after another "
               "at the next re-order.")
        return f"{why} {tip}" if why else tip

    def _sync_replan_row(self):
        """Grey the switch where it can't run (its reason in the tooltip), and the sync choice while it's off."""
        try:
            settings = self._settings()
            why = replan_preview.unavailable(settings)
            # Never greyed for "the deck changed": ticking it again is the way to this deck (review 3 R4).
            aside = bool(replan_preview.deck_set_aside(settings)) and \
                replan_preview.unavailable(dict(settings, junban_replan_deck="")) is None
            self.replan_box.state(["disabled"] if why and not aside and not self.replan_on.get() else ["!disabled"])
            self.sync_box.config(state="readonly" if self.replan_on.get() else "disabled")
        except (AttributeError, tk.TclError):
            pass

    def _replan_value(self):
        """`junban_replan_preview` as the box says it, or off if it is not built yet."""
        try:
            return bool(self.replan_on.get())
        except (AttributeError, tk.TclError):
            return False

    def _replan_values(self):
        """The row's keys for `_save_scope` — only once the user has touched it, and never once the dashboard's
        language is no longer the one this window opened in (its row and deck are that language's: review 3 R3)."""
        opened = getattr(self, "_replan_language", None) or self._lang_code()
        if self._lang_code() != opened:
            return {}
        # 3.0 (Haya's G3, W3.5 row 7): the user's pick of the deck in this window records the pair — this window's
        # language and its deck — box touched or not; the re-order host stands aside unless it holds
        # (`replan_preview.recorded_deck`). Only that pick (`_on_deck_picked`): never another checkbox, a
        # FocusOut save or 順's own first-deck pick — a Japanese deck still shown in a Chinese window would be
        # recorded for Chinese by an unrelated tweak. A deck picked in another language's window records that one.
        deck = self.deck.get().strip()
        picked = getattr(self, "_deck_picked", False)
        values = {"junban_replan_language": opened, "junban_replan_deck": deck} if deck and picked else {}
        if not getattr(self, "_replan_touched", False):
            return values
        # A minute set by hand (2, 10) shows as itself and is kept as it is until another choice is picked.
        delay = dict(self.SYNC_CHOICES).get(self.sync_choice.get(), self._replan_saved_delay)
        values.update({"junban_replan_preview": self._replan_value(), "anki_sync_delay_min": delay})
        return values

    def _on_deck_picked(self):
        """The user picked the deck in the list: the one save that records the (language, deck) pair (3.0)."""
        self._deck_picked = True
        try:
            self._on_scope_changed()
        finally:
            self._deck_picked = False

    def _on_replan_changed(self):
        self._replan_touched = True
        self._on_scope_changed()
        self._sync_replan_row()
        changed = getattr(self.app, "replan_preview_changed", None)
        if callable(changed):
            try:
                changed()               # the dashboard starts (or stops) its own part: switched on, a Generate first
            except Exception:
                pass

    def _order_value(self):
        """The chosen order, or the default if the widget is not built yet."""
        try:
            return "priority" if self.order.get() == "priority" else "content"
        except (AttributeError, tk.TclError):
            return reposition.DEFAULT_ORDER

    def _unlisted_value(self):
        """`junban_unlisted` as the "List first" box says it, or the default if it is not built yet."""
        try:
            if not self.list_first.get():
                return "journey"
        except (AttributeError, tk.TclError):
            return reposition.DEFAULT_UNLISTED
        return "back" if self._unlisted_saved == "back" else "list_first"

    def _phrases_value(self):
        """`junban_phrases` as the "Phrases" box says it, or on if it is not built yet."""
        try:
            return bool(self.phrases.get())
        except (AttributeError, tk.TclError):
            return True

    def _ready_first_value(self):
        """`junban_ready_first` as the "i+1 first" box says it, or off if it is not built yet."""
        try:
            return bool(self.ready_first.get())
        except (AttributeError, tk.TclError):
            return False

    def _only_marker_values(self):
        """The ticked markers, in `match.MARKERS` order. Empty means "everything"."""
        try:
            return tuple(name for name in match.MARKERS
                         if self.only_markers.get(name) is not None
                         and self.only_markers[name].get())
        except (AttributeError, tk.TclError):
            return ()

    def _build_touchups(self, parent):
        """The collapsed "Also update the cards" group (WP-L).

        Collapsed, because it is the only part of this window that writes the user's own words
        rather than a queue position and it should not be the first thing a hand falls on. Every
        control changes the preview's promise, so each one invalidates it the same way the deck
        picker does — a preview that says "and tag 47 notes" must be the preview of the run that
        does.
        """
        saved = self._saved_settings()

        header = ttk.Frame(parent, style="Jun.TFrame")
        header.pack(fill=tk.X, pady=(10, 0))
        self.touch_open = False
        self.touch_var = tk.StringVar(value="")
        # No fixed width: the caption grows as extras are switched on ("… (tag + markers)") and a
        # width=30 clipped it mid-word.
        self.btn_touch = ttk.Button(header, textvariable=self.touch_var, style="Jun.TButton",
                                    command=self._toggle_touchups)
        self.btn_touch.pack(side=tk.LEFT)
        ToolTip(self.btn_touch, "Optional extras that change the NOTES of the cards Junban moves — "
                                "a tag, the frequency number. Everything that writes into your own "
                                "fields is off until you switch it on, and Restore puts it all back.")

        self.touch_box = ttk.Frame(parent, style="Jun.TFrame", padding=(56, 6, 0, 0))

        # --- the tag: additive, and the only one that is on by default -------------------- #
        tag_row = ttk.Frame(self.touch_box, style="Jun.TFrame")
        tag_row.pack(fill=tk.X, pady=(0, 4))
        self.tag_on = tk.BooleanVar(value=bool(str(saved.get("junban_tag") or "").strip()))
        box = ttk.Checkbutton(tag_row, text="Tag the notes I move:", variable=self.tag_on,
                              style="Jun.TCheckbutton", command=self._on_touchup_changed)
        box.pack(side=tk.LEFT)
        ToolTip(box, "Adds a tag to every note whose card actually moved, so you can find them in "
                     "Anki's browser afterwards. It adds nothing else and removes nothing.")
        self.tag_name = tk.StringVar(value=str(saved.get("junban_tag") or "Surasura"))
        entry = ttk.Entry(tag_row, textvariable=self.tag_name, width=18, style="Jun.TEntry")
        entry.pack(side=tk.LEFT, padx=(6, 0))
        entry.bind("<FocusOut>", lambda _e: self._on_touchup_changed())
        entry.bind("<Return>", lambda _e: self._on_touchup_changed())
        ToolTip(entry, "The tag to add. Undo the last reorder takes this exact tag back off again, "
                       "and only from the notes Junban put it on.")

        # --- WP-N: the markers, as searchable sub-tags of the one above ------------------- #
        self.markers_on = tk.BooleanVar(value=bool(saved.get("junban_tag_markers")))
        box = ttk.Checkbutton(tag_row, text="…and ✦ ⚖ 📖", variable=self.markers_on,
                              style="Jun.TCheckbutton", command=self._on_touchup_changed)
        box.pack(side=tk.LEFT, padx=(8, 0))
        ToolTip(box, "Also adds the word's markers as sub-tags of the tag above — "
                     "Surasura::star, Surasura::lopsided, Surasura::reading — so you can browse or "
                     "build a filtered deck on just one of them inside Anki. Plain letters, not the "
                     "symbols, so they are typable in Anki's search box. A word with no marker gets "
                     "no extra tag.")

        # --- the frequency number: appends to a list, never replaces it ------------------- #
        freq_row = ttk.Frame(self.touch_box, style="Jun.TFrame")
        freq_row.pack(fill=tk.X, pady=(0, 4))
        self.freq_on = tk.BooleanVar(value=bool(saved.get("junban_write_frequency")))
        box = ttk.Checkbutton(freq_row, text="Add the word's frequency number to:",
                              variable=self.freq_on, style="Jun.TCheckbutton",
                              command=self._on_touchup_changed)
        box.pack(side=tk.LEFT)
        ToolTip(box, "Writes the word's place in your list into the note, as one more entry in the "
                     "frequency list — beside JPDB's, not instead of it. Nothing already there is "
                     "removed, and running again replaces Surasura's own entry rather than adding "
                     "a second.")
        self.freq_field = tk.StringVar(value=str(saved.get("junban_frequency_field") or "Frequency"))
        self.freq_box = ttk.Combobox(freq_row, textvariable=self.freq_field, width=18,
                                     style="Jun.TCombobox")
        self.freq_box.pack(side=tk.LEFT, padx=(6, 0))
        self.freq_box.bind("<<ComboboxSelected>>", lambda _e: self._on_touchup_changed())
        self.freq_box.bind("<FocusOut>", lambda _e: self._on_touchup_changed())
        ToolTip(self.freq_box, "Which field holds it. The list is the fields your own notes "
                               "actually have, filled in after a preview. A field a note does not "
                               "have is skipped, never created.")

        # --- the sort key: destructive, and separate so it cannot ride along --------------- #
        sort_row = ttk.Frame(self.touch_box, style="Jun.TFrame")
        sort_row.pack(fill=tk.X, pady=(0, 4))
        self.freqsort_on = tk.BooleanVar(value=bool(saved.get("junban_write_freqsort")))
        box = ttk.Checkbutton(sort_row,
                              text=f"…and overwrite the '{touchup.FREQSORT_FIELD}' sort number",
                              variable=self.freqsort_on, style="Jun.TCheckbutton",
                              command=self._on_touchup_changed)
        box.pack(side=tk.LEFT)
        ToolTip(box, f"Replaces the single number Anki's browser sorts by. Unlike the frequency "
                     f"list this REPLACES what is in '{touchup.FREQSORT_FIELD}', so your existing "
                     f"browser ordering changes. Restore puts it back. Off unless you want exactly "
                     f"this.")

        # --- Junban_Backlog_Spec §13: the cards NOT on the list. Checkboxes, so any combination
        # works; none ticked is "No action", the default. No delete, by design. ---------------- #
        later_row = ttk.Frame(self.touch_box, style="Jun.TFrame")
        later_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(later_row, text="Cards not on your list:", style="Jun.TLabel").pack(side=tk.LEFT)
        self.later_on = {}
        for key, label, tip in (
                ("tag", "Tag", "Adds the tag Surasura::later to the notes of every card placed after "
                               "your list, so you can find them in Anki's browser. Restore takes it "
                               "back off."),
                ("flag", "Flag purple", "Flags every card placed after your list purple. A card you "
                                        "already flagged another colour keeps your flag. Restore puts "
                                        "the old flags back."),
                ("suspend", "Suspend", "Suspends every card placed after your list, so it leaves "
                                       "your new-card queue — and tags it Surasura::later, so you "
                                       "can always find it again. Restore unsuspends exactly these "
                                       "cards, never ones you suspended yourself.")):
            self.later_on[key] = tk.BooleanVar(value=saved.get(f"junban_later_{key}") is True)
            box = ttk.Checkbutton(later_row, text=label, variable=self.later_on[key],
                                  style="Jun.TCheckbutton", command=self._on_touchup_changed)
            box.pack(side=tk.LEFT, padx=(8, 0))
            ToolTip(box, tip)
        self.later_state = tk.StringVar(value="")
        ttk.Label(later_row, textvariable=self.later_state, style="JunMuted.TLabel").pack(
            side=tk.LEFT, padx=(10, 0))

        self._sync_touchups()

    def _toggle_touchups(self):
        self.touch_open = not self.touch_open
        self._sync_touchups()

    def _sync_touchups(self):
        """Show or hide the group, and keep the header honest about what is switched on."""
        summary = []
        try:
            if self.tag_on.get() and self.tag_name.get().strip():
                summary.append("tag" + (" + markers" if self.markers_on.get() else ""))
            if self.freq_on.get() and self.freq_field.get().strip():
                summary.append("frequency")
            if self.freqsort_on.get():
                summary.append("sort number")
            later = [name for name in ("tag", "flag", "suspend") if self.later_on[name].get()]
            self.later_state.set("" if later else "No action")
            if later:
                summary.append("not on your list: " + " + ".join(later))
        except (tk.TclError, AttributeError):
            pass
        arrow = "▾" if self.touch_open else "▸"
        self.touch_var.set(f"{arrow}  Also update the cards" +
                           (f"  ({', '.join(summary)})" if summary else ""))
        try:
            if self.touch_open:
                self.touch_box.pack(fill=tk.X, after=self.btn_touch.master)
            else:
                self.touch_box.pack_forget()
        except tk.TclError:
            pass

    def _on_touchup_changed(self):
        """Any touch-up change invalidates the preview, exactly as changing the deck does.

        The preview states what the run will do — "will move 47 cards and tag 47 notes" — so a
        preview taken with different options is a confirmation of a different run (I5).
        """
        self._sync_touchups()
        self._on_scope_changed()

    def _build_match(self, parent):
        row = ttk.Frame(parent, style="Jun.TFrame")
        row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(row, text="Match:", style="Jun.TLabel", width=7).pack(side=tk.LEFT)
        self.match_var = tk.StringVar(value="Checking Anki…")
        ttk.Label(row, textvariable=self.match_var, style="Jun.TLabel").pack(side=tk.LEFT)

        # Which field each note type's word was read from. Shown before any write on purpose: field
        # 0 is an anki_miner invariant rather than an Anki one, and a wrong guess (Migaku's
        # `Sentence`) matches nothing and looks like the feature is broken (spec §18.1).
        self.fields_var = tk.StringVar(value="")
        # On the SAME row as the match count, not under it: on a 720px-tall screen every row this
        # does not take is another row of the preview table.
        ttk.Label(row, textvariable=self.fields_var, style="JunField.TLabel").pack(
            side=tk.LEFT, padx=(12, 0))

    def _build_checks(self, parent):
        """"Same word as one on your list?" (Junban_Backlog_Spec §16) — built here, shown only when a
        preview has something to check, so on most previews it takes no room at all.

        Just ticks, as the user asked: no Done, no Cancel, no Match all. A click or Space ticks a row
        and the preview below re-plans at once; Reorder records the answers. The rows say everything
        a glance needs — the card's word, the list word it may be, its rank, the reading, and the
        card's own sentence with the word marked.
        """
        self._checks_box = ttk.Frame(parent, style="Jun.TFrame")
        header = ttk.Frame(self._checks_box, style="Jun.TFrame")
        header.pack(fill=tk.X)
        ttk.Label(header, text="Same word as one on your list?", style="JunCheck.TLabel").pack(side=tk.LEFT)
        self.checks_count_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.checks_count_var, style="JunCount.TLabel").pack(
            side=tk.LEFT, padx=(8, 0))
        ttk.Label(header, text="tick the ones that are", style="JunMuted.TLabel").pack(
            side=tk.LEFT, padx=(10, 0))
        self.earlier_var = tk.StringVar(value="")
        self.lnk_earlier = ttk.Label(header, textvariable=self.earlier_var, style="JunLink.TLabel",
                                     cursor="hand2")
        self.lnk_earlier.bind("<Button-1>", lambda _e: self._toggle_earlier())
        ToolTip(self.lnk_earlier, "Show the words you answered before, to change an answer the same "
                                  "way: tick or untick it, then Reorder.")

        body = ttk.Frame(self._checks_box, style="Jun.TFrame")
        body.pack(fill=tk.X, pady=(4, 0))
        self.check_tree = ttk.Treeview(body, columns=("tick", "card", "list", "reading", "sentence"),
                                       show="", style="Jun.Treeview", selectmode="browse",
                                       height=CHECK_ROWS)
        for name, width, anchor, stretch in (("tick", 28, "center", False), ("card", 100, "w", False),
                                             ("list", 190, "w", False), ("reading", 100, "w", False),
                                             ("sentence", 300, "w", True)):
            self.check_tree.column(name, width=width, anchor=anchor, stretch=stretch)
        self.check_tree.tag_configure("ticked", foreground=ACCENT)
        self.check_tree.tag_configure("earlier", foreground=MUTED)
        self.check_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.check_bar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.check_tree.yview,
                                       style="Jun.Vertical.TScrollbar")
        self.check_tree.configure(yscrollcommand=self.check_bar.set)
        self.check_tree.bind("<Button-1>", self._on_check_clicked)
        self.check_tree.bind("<space>", self._on_check_space)
        ToolTip(self.check_tree, "Your card's word may be the word on your list, spelled another way. "
                                 "Tick it if it is — click the row or press Space — and the card moves "
                                 "up with your list's words. Nothing moves unless you tick it. Your "
                                 "answers are kept when you press Reorder, so a word is only asked "
                                 "about once.")

    def _build_preview(self, parent):
        box = ttk.Frame(parent, style="Jun.TFrame")

        columns = ("index", "position", "word", "marks", "rank", "deck")
        self.tree = ttk.Treeview(box, columns=columns, show="headings", style="Jun.Treeview",
                                 # "browse", not "none": a click has to leave a visible mark or
                                 # there is no telling which row you just acted on. The row
                                 # highlight is styled below rather than left to the base theme.
                                 selectmode="browse")
        # Widths leave room for the CENTRED heading over a right-aligned number, so
        # "new pos" cannot crowd the word beside it. `marks` sits beside the word rather than at the
        # end, because it is a property OF the word — and the preview is the only place the user
        # sees ✦ / ⚖ / 📖 before anything is written (WP-N).
        for name, title, width, anchor in (("index", "#", 46, "e"),
                                           ("position", "new pos", 90, "e"),
                                           ("word", "word", 150, "w"),
                                           # Derived, never spelled out: a hardcoded header drifts
                                           # from the glyphs in the rows below it the moment the
                                           # marks change — which is exactly what happened when
                                           # 📖 became 文.
                                           ("marks", "".join(MARKER_GLYPHS[m] for m in match.MARKERS),
                                            64, "center"),
                                           # Why the card goes where it goes: "list #412",
                                           # "phrase · 14× · Honzuki no Gekokujou - 21", "i+1",
                                           # "2 unknown", "known" (§5.4) — words, so left-aligned
                                           # and wide enough for an episode's short name.
                                           ("rank", "why", 250, "w"),
                                           ("deck", "deck", 130, "w")):
            # Headings stay CENTRED (ttk's default) even where the column is not. Anchoring each
            # heading to its column's edge was tried and is worse: a right-anchored "new pos" butts
            # straight into a left-anchored "word" and they read as one word.
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, anchor=anchor, stretch=(name in ("word", "deck")))
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Unmatched cards are greyed and sit below the matched block: the current list says nothing
        # about them, so they keep their order at the back rather than being promoted past a card
        # it ranks.
        self.tree.tag_configure("unmatched", foreground=DISABLED)
        self.tree.tag_configure("unchanged", foreground=MUTED)

        # WP-O: the table IS the toggle. A click anywhere on a row drops that card from the run and
        # `Space` does the same to the row the keyboard is on — no new checkbox, no new row of
        # chrome, because every row of chrome on a 720px screen is a row of this table.
        self.tree.bind("<Button-1>", self._on_row_clicked)
        self.tree.bind("<space>", self._on_row_space)
        ToolTip(self.tree, "Greyed rows are not on your list, so they go after it. Click a word on "
                           "your list to take it off: it goes with the cards not on your list, and "
                           "whatever you ticked for them applies to it too. Click a greyed card to "
                           "leave it alone: it keeps its order at the back and nothing touches it. "
                           "Click again to undo. Space does the same to the row you are on.")

        bar = ttk.Scrollbar(box, orient=tk.VERTICAL, command=self.tree.yview,
                            style="Jun.Vertical.TScrollbar")
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=bar.set)

        self.messages = tk.Text(parent, height=2, bg=SURFACE, fg=TEXT, relief="flat",
                                highlightthickness=1, highlightbackground=SURFACE,
                                font=("Consolas", 9), wrap="word", padx=8, pady=6,
                                state="disabled")
        # Starts HIDDEN — see _show_messages. It is packed on first use, before the progress
        # bar, so it always sits between the table and the buttons.

        self.progress = ttk.Progressbar(parent, style="Jun.Horizontal.TProgressbar",
                                        mode="determinate")
        self.progress.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))

        # Packed LAST so the bottom row and the message pane have already claimed their space —
        # the table then takes whatever is left, and the buttons survive any window size.
        box.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self._preview_box = box         # the check list (§16) is packed just above it
        self.messages.tag_configure("problem", foreground=ERROR)
        self.messages.tag_configure("warning", foreground=ACCENT)
        self.messages.tag_configure("good", foreground=SECONDARY)

    def _build_actions(self, parent):
        # FT (D8): the way back from everything Surasura did to this language's cards, on a row of its own under
        # Restore — beside it the actions row would run past a 780px window. Rarely pressed, so the small style.
        put_back = ttk.Frame(parent, style="Jun.TFrame")
        put_back.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        self.btn_put_back = ttk.Button(put_back, text=first_touch_gui.BUTTON_TEXT, style="JunSmall.TButton",
                                       command=self.on_put_back)
        self.btn_put_back.pack(side=tk.RIGHT)
        ToolTip(self.btn_put_back, first_touch_gui.BUTTON_TIP)

        row = ttk.Frame(parent, style="Jun.TFrame")
        row.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        # One width whatever it says — "Preview order", "Generate & preview", "Generating…" (§16.9).
        self.btn_preview = ttk.Button(row, text="Preview order", width=19, style="Jun.TButton",
                                      command=self.on_preview)
        self.btn_preview.pack(side=tk.LEFT)
        ToolTip(self.btn_preview, "Work out the new order and show it here. Nothing is written to "
                                  "Anki — this is what you check before reordering. When your list is "
                                  "out of date it reads Generate & preview: Surasura brings the list up "
                                  "to date first (the report is not opened), then shows the new order.")

        self.btn_restore = ttk.Button(row, text="Undo the last reorder", width=22,
                                      style="Jun.TButton", command=self.on_restore)
        self.btn_restore.pack(side=tk.RIGHT)
        ToolTip(self.btn_restore, "Put the cards back where they were before the last reorder, "
                                  "using the saved snapshot. Anki's own Undo cannot do this.")

        self.btn_reorder = ttk.Button(row, text="Reorder", width=14, style="Jun.TButton",
                                      command=self.on_reorder)
        self.btn_reorder.pack(side=tk.RIGHT, padx=(0, 8))
        ToolTip(self.btn_reorder, "Write the previewed order into Anki. Available once you have "
                                  "previewed the deck you are about to change.")

    # ------------------------------------------------------------------ settings
    def _lang_code(self):
        """The active language — the dashboard's live choice wins over the saved one."""
        try:
            if self.app is not None:
                return self.app.var_language.get() or "ja"
        except Exception:
            pass
        return str(self._saved_settings().get("target_language") or "ja")

    @staticmethod
    def _saved_settings():
        """Settings as they are on disk, never mutated. Degrades to the module defaults."""
        try:
            from app import settings_manager
            loaded = settings_manager.load_settings()
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            import modules.junban as junban
            return dict(junban.SETTINGS_DEFAULTS)

    def _settings(self):
        """What the engine is handed: the saved settings plus whatever the scope widgets say.

        A **fresh** dict every time, and a fresh `junban_word_fields` inside it. That dict is the
        very object living in `SETTINGS_DEFAULTS` — `settings_manager._optional_module_defaults()`
        merges module defaults with a shallow `dict.update()` — so editing it in place would poison
        the default for every later `load_settings()` in the process (spec §13 #12).
        """
        saved = self._saved_settings()
        overrides = saved.get("junban_word_fields")
        return dict(saved,
                    target_language=self._lang_code(),
                    junban_scope=self.scope.get(),
                    junban_deck=self.deck.get().strip(),
                    junban_word_fields=dict(overrides) if isinstance(overrides, dict) else {},
                    junban_order=self._order_value(),
                    junban_unlisted=self._unlisted_value(),
                    junban_phrases=self._phrases_value(),
                    junban_ready_first=self._ready_first_value(),
                    # A fresh list, for the same reason `junban_word_fields` is a fresh dict: a
                    # container in loaded settings IS the one inside `SETTINGS_DEFAULTS` after the
                    # shallow merge, and handing it out would let a caller poison it (spec §13 #12).
                    junban_only_markers=list(self._only_marker_values()),
                    junban_replan_preview=self._replan_value(),
                    # WP-O. A run-time key with no default and no home in `settings.json`: it says
                    # what the user clicked off in the preview they are looking at, and it dies with
                    # that preview. `_save_scope` names the keys it persists, so it cannot leak.
                    junban_exclude_cards=sorted(self._deselected),
                    **self._own_values(),
                    **self._touchup_settings())

    def _touchup_settings(self):
        """WP-L's six keys, as the widgets currently read them.

        An unticked checkbox sends the *disabling* value rather than leaving the saved one in
        place — an empty tag, an empty sentence field — so the engine can never be handed a
        half-off switch and the preview describes the boxes the user can see.
        """
        try:
            return {
                "junban_tag": self.tag_name.get().strip() if self.tag_on.get() else "",
                "junban_tag_markers": bool(self.markers_on.get()),
                "junban_write_frequency": bool(self.freq_on.get()),
                "junban_frequency_field": self.freq_field.get().strip(),
                "junban_write_freqsort": bool(self.freqsort_on.get()),
                "junban_later_tag": bool(self.later_on["tag"].get()),
                "junban_later_flag": bool(self.later_on["flag"].get()),
                "junban_later_suspend": bool(self.later_on["suspend"].get()),
            }
        except (AttributeError, tk.TclError, KeyError):
            # The group has not been built yet (or the window is going away). Writing nothing is
            # the only safe answer here, and it is also the default.
            return {"junban_tag": "", "junban_tag_markers": False,
                    "junban_write_frequency": False,
                    "junban_write_freqsort": False,
                    "junban_later_tag": False, "junban_later_flag": False,
                    "junban_later_suspend": False}

    def _scope_key(self):
        """What a preview is valid for. Changing ANY of it invalidates the preview.

        The touch-ups belong in here as much as the deck does: the preview's one sentence says
        "will move 47 cards and tag 47 notes", and a preview taken with the tag off is not a
        confirmation of a run with it on (I5).

        So do the order and the marker filter (WP-M/WP-N). They change the order itself rather than
        a side effect of it: the priority list's first word is not met until file #148 on the live
        library, while content order starts with file #1. A preview of one is not a confirmation of
        the other.

        And the dashboard's language: the run reads the list, the known words and the snapshot of
        whichever language is live when Reorder is pressed, so a preview of the other one is stale.
        """
        return (self._lang_code(), self.scope.get(), self.deck.get().strip(),
                self._order_value(), self._unlisted_value(), self._phrases_value(),
                self._ready_first_value(),
                self._only_marker_values(),
                tuple(sorted(self._own_values().items())),
                tuple(sorted(self._touchup_settings().items())),
                self._replan_value())

    def _save_scope(self):
        """Persist the scalars the panel owns — the scope, the order, and WP-L's touch-ups — and
        nothing else: onto settings.json as it is (`settings_manager.save_keys`). Saving every
        loaded default put back a retired key the dashboard had dropped, and each click then cost
        a full Generate.

        `junban_only_markers` is **assigned a fresh list**, never appended to: after
        `settings_manager`'s shallow merge, the list sitting in loaded settings can be the very
        object inside `SETTINGS_DEFAULTS` (spec §13 #12).
        """
        try:
            from app import settings_manager
            changes = {
                "junban_scope": self.scope.get(),
                "junban_deck": self.deck.get().strip(),
                "junban_order": self._order_value(),
                "junban_unlisted": self._unlisted_value(),
                "junban_phrases": self._phrases_value(),
                "junban_ready_first": self._ready_first_value(),
                "junban_only_markers": list(self._only_marker_values()),
            }
            changes.update(self._own_values())
            changes.update(self._touchup_settings())
            changes.update(self._replan_values())
            settings_manager.save_keys(changes)
        except Exception as e:
            self._write(f"Could not save the scope: {e}")

    def _on_scope_changed(self):
        """A different scope means the preview on screen describes a different set of cards.

        So it is thrown away and `Reorder` greys out again: the preview IS the confirmation, and
        confirming one deck then writing another is the failure this guards (I5).
        """
        self._preview_scope = None
        self._clear_preview()
        self.counts_var.set("")
        self.match_var.set("Press Preview order to refresh.")
        self.fields_var.set("")
        self._save_scope()
        self._sync_buttons()
        self._sync_replan_row()

    @staticmethod
    def _job(settings):
        """The window's own preview and run: always its spaced job (`window_job`), so a manual re-order gets S1's
        session sync before its first write (IK-11)."""
        return window_job(settings)

    # -------------------------------------------------------------------- state
    def _sync_buttons(self):
        """Who may be pressed right now. `Reorder` needs a preview of THIS scope (I5), made from an
        up-to-date list (§16.9) — while the list is out of date, Preview order is the way forward."""
        idle = not self.busy and not self._generating
        ready = idle and self._preview_scope == self._scope_key() and self._list_current is not False
        try:
            self.btn_preview.config(text="Generating…" if self._generating else
                                    "Generate & preview" if self._must_generate() else "Preview order")
        except tk.TclError:
            pass
        for widget, enabled in ((self.btn_preview, idle),
                                (self.btn_restore, idle),
                                (self.btn_recheck, idle),
                                (self.btn_reorder, ready),
                                (self.btn_put_back, idle and self._first_touch_kept())):
            try:
                widget.config(state=tk.NORMAL if enabled else tk.DISABLED)
            except tk.TclError:
                pass
        try:
            self.deck_box.config(state="readonly" if self.scope.get() == "deck" else "disabled")
        except tk.TclError:
            pass

    def _first_touch_kept(self):
        """Has Surasura kept anything to put back for this language (FT: local files only, never Anki)? C21: asked
        once per language, not at every button sync — `_first_touch_changed` asks again after a run, a restore and a
        put-back."""
        language = self._lang_code()
        kept = getattr(self, "_ft_kept", None)
        if kept is None or kept[0] != language:
            kept = self._ft_kept = (language, first_touch_gui.available(language))
        return kept[1]

    def _first_touch_changed(self):
        self._ft_kept = None

    def _set_busy(self, busy):
        self.busy = busy
        self._sync_buttons()

    def _set_connection(self, report, decks=None):
        """Paint the connection row, and refill the deck list while we have the answer.

        A failed probe is a *state*: the panel says Anki has to be running and stays usable, rather
        than the user finding out when they press a button.
        """
        self._connected = bool(report.get("ok"))
        if self._connected:
            version = report.get("version")
            self.conn_var.set(f"● connected (AnkiConnect {version})" if version else "● connected")
            self.conn_lbl.config(foreground=SECONDARY)
        else:
            self.conn_var.set("● not connected")
            self.conn_lbl.config(foreground=ERROR)
            self._write(report.get("error") or "Could not reach Anki.", "problem")
            self._write("Junban reads and writes through AnkiConnect, so Anki must be running with "
                        "a profile open. Start it and press ⟳.", "warning")

        if decks:
            self._decks = list(decks)
            current = self.deck.get().strip()
            values = list(decks) if not current or current in decks else list(decks) + [current]
            self.deck_box.config(values=values)
            if not current and self.scope.get() == "deck":
                # Nothing nominated yet: offering the first deck that actually has new cards beats
                # an empty box that reports "no deck is selected" on every press.
                self.deck.set(decks[0])
                self._save_scope()
        self._sync_buttons()

        if not self._connected:
            self.match_var.set("Anki is not running.")
            self.counts_var.set("")
            return

        # "It just works": the scope is already decided (one deck, or all of them), the preview is
        # read-only and takes about a second, so run it rather than making the user press a button
        # to see the thing the window exists to show. It is still a *preview* — I5 is unchanged,
        # because Reorder remains gated on one existing and matching the live scope.
        # Gate the SCHEDULING, not the callback (testing.md §5.4).
        if self._auto_previewed or os.environ.get("SURASURA_NO_UI_TIMERS"):
            return
        if self.scope.get() == "deck" and not self.deck.get().strip():
            return
        self._auto_previewed = True
        self.after(50, self.on_preview)

    # ------------------------------------------------------------------ actions
    def refresh_connection(self):
        """Probe Anki (and list its decks) off the UI thread."""
        if self.busy:
            return
        self.conn_var.set("● checking…")
        self.conn_lbl.config(foreground=MUTED)
        self._start(self._probe_worker)

    def _probe_worker(self):
        from modules.junban import ankiconnect
        settings = self._settings()
        url = reposition._url(settings)
        report = ankiconnect.probe(url)
        decks = []
        if report.get("ok"):
            try:
                decks = ankiconnect.deck_names_with_new(url)
            except Exception as e:
                self.q.put(("__MESSAGE__", f"Could not list your decks: {e}", "warning"))
        self.q.put(("__CONN__", report, decks))

    def on_preview(self):
        """The mandatory dry run. Reads Anki and the priority list; writes nothing, anywhere.

        With the list out of date (§16.9) the same button is "Generate & preview": the dashboard's
        Generate first, quietly, and this preview again by itself when it finishes (`on_list_updated`).
        """
        if self.busy or self._generating:
            return
        if self._must_generate():
            self._generate()
            return
        self._clear_messages()
        self._clear_preview()
        self.progress["value"] = 0
        self.match_var.set("Working it out…")
        # Read HERE, on the UI thread, and the preview is stamped with the key it was made FOR. The
        # deck, order and touch-up controls stay live while it runs, and a result that arrived after
        # one of them changed used to be stamped with the NEW key — unlocking Reorder for a run
        # nobody previewed. (Tk variables were also never the worker's to read.) So are the
        # dashboard's Generate arguments, for the worker's "is the list up to date?".
        settings, key, args = self._settings(), self._scope_key(), self._generate_args()
        self._start(lambda: self._preview_worker(settings, key, args))

    # ------------------------------------------------------- the list up to date (§16.9)
    def _generate_args(self):
        """The dashboard's Generate arguments, read from its widgets on this (the UI) thread — or None
        standalone, where there is no Generate to offer and nothing changes."""
        try:
            if self.app is not None and hasattr(self.app, "_analyzer_args") \
                    and hasattr(self.app, "run_analyzer"):
                return list(self.app._analyzer_args())
        except Exception:
            pass
        return None

    def _must_generate(self):
        """Out of date, with a dashboard that can bring it up to date: Preview order generates."""
        return self._list_current is False and self.app is not None and hasattr(self.app, "run_analyzer")

    def _generate(self):
        """The dashboard's own Generate, quietly — the report is not opened (the user, 2026-09-23) —
        after which it tells this window, and the preview runs again by itself. Never a write: the
        new order is still previewed before Reorder can be pressed (I5)."""
        self._generating = True
        self._generate_tried = True
        self._clear_messages()
        self._write("Bringing your list up to date — the new order shows here by itself when it's "
                    "done.", "good")
        self._sync_buttons()
        try:
            self.app.run_analyzer(quiet=True)
        except Exception as e:
            self._generating = False
            self._write(f"Generate could not start: {e}", "problem")
            self._sync_buttons()

    def on_list_updated(self):
        """The dashboard's call after ANY Generate finishes. A window that was waiting for one — out
        of date, or generating — previews again; one the user is working in is left alone."""
        if self._closing:
            return
        waiting = self._generating or self._list_current is False
        self._generating = False
        if waiting and not self.busy:
            self._list_current = None           # the preview's worker asks again
            self.on_preview()
        else:
            self._sync_buttons()

    @staticmethod
    def _is_list_current(args, language):
        """`app.main.journey_is_current` — the Generate button's ✓ — or None without a dashboard or
        when it cannot tell. `app.main` is already loaded in the dashboard's process."""
        if args is None:
            return None
        try:
            from app.main import journey_is_current
            return journey_is_current(args, language)
        except Exception:
            return None

    def _preview_worker(self, settings, key, args=None):
        current = self._is_list_current(args, settings.get("target_language") or "ja")
        checks = dict(reposition.preflight(settings), list_current=current)
        if current is not None:
            # The dashboard's answer covers the library AND the known words and settings; the
            # library-only warning would only say half of it, twice.
            checks["warnings"] = [line for line in checks.get("warnings") or []
                                  if line != reposition.STALE_WARNING]
        if not checks["ok"]:
            # Problems block, and are the whole answer: no point reading 152 cards to plan a run
            # that cannot happen.
            self.q.put(("__PREVIEW__", None, checks, key))
            return
        try:
            _writes, stats = reposition.dry_run(settings, job=window_job(settings))
        except Exception as e:
            self.q.put(("__PREVIEW__", None, {"ok": False, "problems": [str(e)],
                                              "warnings": checks["warnings"], "decks": []}, key))
            return
        stats = dict(stats)
        stats.update(self._context_counts(settings, checks.get("decks") or []))
        self.q.put(("__PREVIEW__", stats, checks, key))

    @staticmethod
    def _context_counts(settings, decks):
        """How many cards in scope junban will NOT touch.

        The planner reports `skipped_review` as 0 here and that is correct but misleading: the
        search is `is:new`, so review cards never reach it to be skipped. Saying "0 review cards
        (untouched)" to someone whose deck holds 17 of them reads as "it cannot see them" — the
        opposite of the reassurance the line exists to give. So count them directly.

        Best-effort: a failure returns nothing and the line simply omits the clause.
        """
        from modules.junban import ankiconnect
        url = reposition._url(settings)
        scope = decks if decks else []
        if not scope:
            return {}
        out = {}
        # `-is:new -is:suspended` rather than `is:review`: a card the user has started but not yet
        # graduated is `type=1 queue=1` (learning), which `is:review` does not match. Counting only
        # review cards under-reports exactly the cards someone has been actively studying — found
        # when the user did a few reviews in the test deck and 17 cards vanished from both totals.
        for key, clause in (("context_review", "-is:new -is:suspended"),
                            ("context_suspended", "is:suspended")):
            total = 0
            try:
                for deck in scope:
                    safe = ankiconnect.escape_query(deck)
                    total += len(ankiconnect.invoke("findCards", url, query=f'deck:"{safe}" {clause}'))
                out[key] = total
            except Exception:
                pass
        return out

    def on_reorder(self):
        """Write the order. Reachable only with a preview of this exact scope on screen (I5)."""
        if self.busy or self._generating or self._preview_scope != self._scope_key() \
                or self._list_current is False:
            return
        # §16: the answers first — the run reads them, so what it writes is what the preview showed
        # after the ticks (I5). Ticked = the same word, unticked = not, never asked again.
        answers = self._answers_to_record()
        if answers:
            try:
                pairs.record(self._lang_code(), answers)
            except OSError as e:
                self._write(f"Could not save your answers, so nothing was reordered: {e}", "problem")
                return
        self._clear_messages()
        self.progress["value"] = 0
        self._write("Reordering…")
        settings = self._settings()          # the settings the key above was just checked against
        self._start(lambda: self._reorder_worker(settings))

    def _reorder_worker(self, settings):
        try:
            # Another Anki writer (Backfill, a second Surasura) is waited for here, on the worker; the
            # status line says who, and closing the window stops the wait (E1.4 §W).
            report = reposition.run(settings, progress=self._progress, wait=None, cancel=self._stop,
                                    on_wait=self._waiting, job=window_job(settings))
        except Exception as e:                  # a panel must never lose a write to a traceback
            report = {"ok": False, "message": "Junban did not finish.", "problems": [str(e)],
                      "warnings": [], "written": [], "failures": []}
        self.q.put(("__REPORT__", report))

    def on_restore(self):
        """Replay the saved snapshot. The only way back — Anki writes no undo entry of its own.

        One of Connect's reorders that never finished comes first (P1.4, §7.2): it refuses every reorder until it is
        put back, so Restore names it — and offers it even when this window has no snapshot of its own."""
        if self.busy:
            return
        run = undo.unfinished(self._lang_code(), "reorder")
        if run is not None:
            if not ask(self, "An automatic reorder didn't finish. Put back the cards it moved?",
                       details=[undo.describe_run(self._lang_code(), run)], yes="Restore", no="Cancel"):
                return
            self._clear_messages()
            self.progress["value"] = 0
            self._write("Restoring…")
            settings = self._settings()
            self._start(lambda: self._restore_worker(settings, run=run))
            return
        # The manual run's snapshot or today's baseline — the newer, for this window's deck (03 §5).
        snapshot = undo.restorable(self._lang_code(), reposition._restore_scope(self._settings()))
        if not snapshot:
            self._clear_messages()
            self._write(undo.describe(None), "warning")
            return
        if not ask(self, "Put your cards back where they were before the last reorder?",
                   details=[undo.describe(snapshot)], yes="Restore", no="Cancel"):
            return
        self._clear_messages()
        self.progress["value"] = 0
        self._write("Restoring…")
        settings = self._settings()
        confirmed = snapshot.get("written_at")      # the snapshot the user said yes to
        self._start(lambda: self._restore_worker(settings, confirmed))

    def _restore_worker(self, settings, confirmed=None, run=None):
        try:
            report = reposition.restore(settings, progress=self._progress, wait=None, cancel=self._stop,
                                        on_wait=self._waiting, confirmed=confirmed, run=run)
        except Exception as e:
            report = {"ok": False, "message": "Nothing was restored.", "problems": [str(e)],
                      "warnings": [], "written": [], "failures": []}
        self.q.put(("__REPORT__", report))

    def on_put_back(self):
        """FT (D8): "Put Anki back the way it was before Surasura…" — `first_touch_gui.PutBack`, the flow Settings
        opens too. Refused while a run of this window's own is going; `plan()` and `put_back()` run on workers."""
        if self.busy or self._generating:
            return
        self._clear_messages()
        self.progress["value"] = 0
        first_touch_gui.PutBack(self, self._lang_code(), settings=self._settings(),
                                post=lambda fn: self.q.put(("__CALL__", fn)), show=self._write,
                                busy=self._set_busy, progress=self._show_progress, done=self._put_back_done,
                                cancel=self._stop, on_wait=self._waiting).start()

    def _show_progress(self, done, total):
        self.progress["maximum"] = max(1, total)
        self.progress["value"] = done

    def _put_back_done(self, report):
        """After a put-back the collection has moved on (the preview on screen is last minute's answer) and the
        recorded deck may be cleared (D7): the re-plan row reads it again."""
        self._first_touch_changed()
        if report is None:
            self._sync_buttons()
            return
        self._preview_scope = None
        self._sync_buttons()
        self._sync_replan_row()

    def _progress(self, done, total):
        """The writer's callback — runs on the worker thread, so it only posts to the queue."""
        self.q.put(("__PROGRESS__", done, total))

    def _waiting(self, holder):
        """The Anki-write lock is held elsewhere: said once, from the worker, through the queue."""
        from app import anki_connect
        self.q.put(("__MESSAGE__", anki_connect.waiting_line(holder), "warning"))

    def _start(self, worker):
        self._set_busy(True)
        threading.Thread(target=self._guarded(worker), daemon=True).start()

    def _guarded(self, worker):
        """Run a worker so that no failure can leave the panel stuck on 'busy'."""
        def run():
            try:
                worker()
            except Exception as e:
                self.q.put(("__MESSAGE__", f"Unexpected error: {e}", "problem"))
            finally:
                self.q.put(("__DONE__",))
        return run

    # --------------------------------------------------------------- rendering
    def _show_preview(self, stats, checks, key=None):
        """Render one dry run: the counts, the resolved fields, and the order itself.

        Kept whole and re-run from the top on every deselection (WP-O) rather than patched row by
        row: the table, the counts and the sentence are one statement of what Reorder will do, and a
        table that renumbered while the sentence still promised the old number would be a stale
        confirmation — which is the one thing I5 does not allow.
        """
        self._preview_stats = stats
        self._preview_checks = checks
        # Why each card was placed ("list #12", "library", "i+1", "known"), kept from BEFORE the
        # deselection is applied. A deselected card is planned as unmatched and so comes back with no
        # reason; the column still shows it, because "this is the 12th word you should learn and you
        # took it out" is the whole point of being able to see it.
        self._row_whys = {row.card_id: row.why for row in (stats or {}).get("order") or []}
        # §16: the ticks start as the answers the run would read — an earlier "yes" ticked.
        if self._ticked is None:
            self._ticked = {entry["word"]: entry.get("answer") == "yes"
                            for entry in (stats or {}).get("suggestions") or []}
        stats = self._with_deselection(stats)

        # §16.9: is the list the preview read up to date? Said LAST, below (the pane shows its end).
        if "list_current" in (checks or {}):
            self._list_current = checks.get("list_current")
            if self._list_current is not False:
                self._generate_tried = False
        for line in checks.get("warnings") or []:
            self._write(line, "warning")
        for line in checks.get("problems") or []:
            self._write(line, "problem")

        if stats is None:
            self.match_var.set("No preview — see below.")
            self.counts_var.set("Nothing was read from Anki.")
            self._preview_scope = None
            self._render_checks()
            self._sync_buttons()
            return

        considered = stats.get("considered", 0)
        parts = [f"{considered} new card{'' if considered == 1 else 's'} to reorder"]
        # Only claimed when actually counted — see _context_counts. Silence beats a confident 0.
        review = stats.get("context_review")
        if review is not None:
            parts.append(f"{review} in review or learning (untouched)")
        suspended = stats.get("context_suspended")
        if suspended:
            parts.append(f"{suspended} suspended (untouched)")
        self.counts_var.set(" · ".join(parts))
        # The filter, named where the match count is: "12 of 152 matched" with no explanation reads
        # as a disappointing result rather than as the user's own choice (WP-N).
        only = [name for name in stats.get("only_markers") or [] if name in MARKER_GLYPHS]
        filtered = (" · only " + " ".join(MARKER_GLYPHS[name] for name in only)) if only else ""
        # Junban_Backlog_Spec §11.1: words the list cut off, placed from the library where the
        # journey meets them. Named apart from the list's matches — they are not on the list. With
        # "List first", the phrases met as often as the list's words, placed among them.
        tiers = stats.get("tiers") or {}
        library = stats.get("library") or 0
        phrases = tiers.get("phrase", 0)
        placed = f" · {library} more from your library" if library else ""
        if phrases:
            placed += f" · {phrases} frequent phrase{'' if phrases == 1 else 's'} with them"
        self.match_var.set(f"{stats.get('matched', 0)} of {considered} new card"
                           f"{'' if considered == 1 else 's'} matched your current list"
                           f"{placed}{filtered}")
        if stats.get("library_missing") and stats.get("unlisted") == "journey":
            self._write("The words your list cut off wait at the back for now: press Generate in "
                        "Surasura once, and the next preview places them where your journey meets "
                        "them.", "warning")
        elif stats.get("library_missing"):
            self._write("Phrases wait with the rarer cards for now: press Generate in Surasura once, "
                        "and the next preview puts the ones you meet often with your list's words.",
                        "warning")
        # §5.4 / §5.5: the cards the library could not place, by what their sentence says — and the
        # words already known, with the hint the count is for (Junban never suspends).
        rest = [(tiers.get("i+1", 0), "i+1"), (tiers.get("multi", 0), "with more new words"),
                (tiers.get("rest", 0), "by frequency")]
        rest = " · ".join(f"{count} {label}" for count, label in rest if count)
        if rest:
            self._write(f"Then, by their own sentence: {rest}.", "")
        # §17: what "i+1 first" did, so the moves in the table are expected rather than surprising.
        ready = stats.get("ready_first") or {}
        moved = [f"{ready['pulled']} brought right before the card that needs {'it' if ready['pulled'] == 1 else 'them'}"
                 if ready.get("pulled") else "",
                 f"{ready['held']} wait{'s' if ready['held'] == 1 else ''} for a word {'its' if ready['held'] == 1 else 'their'} "
                 f"sentence needs" if ready.get("held") else ""]
        moved = " · ".join(part for part in moved if part)
        if moved:
            self._write(f"i+1 first: {moved}.", "")
        known = tiers.get("known", 0)
        if known:
            self._write(f"{known} card{' is a word' if known == 1 else 's are words'} you already "
                        "know — they go last. Suspend them in Anki if you don't need them.", "")
        for entry in stats.get("banner") or []:
            self._write(f"{entry['cards']} cards come from {entry['source']}, which isn't in your "
                        "library. Add its subtitles and Generate to rank them.", "warning")
        fields = stats.get("fields") or {}
        resolved = ", ".join(f'{model} → "{field}"' for model, field in sorted(fields.items()))
        self.fields_var.set(f"note types: {resolved}" if resolved else "")

        rows = self._in_display_order(stats.get("order") or [])
        # Every row the list knows, filtered or not — so a word left at the back under a marker
        # filter still shows the marker it does carry, and the filter reads as the reason.
        marks_of = stats.get("marks") or {}
        # WP-O: the deselected rows take no number, so what is left runs 1..N with no hole in it.
        # The number IS the claim "this card is in the run", and a gap in it would be a second,
        # quieter statement of the order that disagreed with the one being written.
        # Junban_Backlog_Spec §13: what the ticked actions will do to each card not on the list —
        # said on its own row, so the cards about to be suspended can be seen before Reorder.
        acts = self._later_acts(stats)
        taken_off = set(stats.get("taken_off_ids") or ())
        # §16: a row the user ticked (or unticked) says its new reason; one still to check names the
        # list word it may be, so the table and the check list above it read as one.
        retold = self._changed_ticks()
        suggested_marks = stats.get("suggested_marks") or {}
        index = 0
        for row in rows[:MAX_PREVIEW_ROWS]:
            off = row.card_id in self._deselected
            if off:
                tag = "unmatched"
            else:
                index += 1
                # Greyed: every card NOT placed with the list — not on it, so behind it, and what the
                # "not on your list" actions reach. The list's own rows stay bright.
                with_list = row.tier in unlisted.PLACED_WITH_LIST
                tag = "unmatched" if not with_list else ("unchanged" if not row.changed else "")
            why = ((row.why if row.word in retold else self._row_whys.get(row.card_id)) or row.why
                   or "—")
            if row.suggestion and row.tier != "list" and not off:
                why = f"{why} · {row.suggestion[0]}?"
            if off and row.card_id in taken_off:
                # Clicked off the list: it goes with the cards not on it (the user, 2026-09-23).
                why = f"{why}  → off your list" + (f", {acts[row.card_id]}" if acts.get(row.card_id) else "")
            elif off:
                why = f"{why}  · left alone"
            elif acts.get(row.card_id):
                why = f"{why}  → {acts[row.card_id]}"
            item = self.tree.insert("", "end",
                                    values=(DESELECTED_GLYPH if off else index,
                                            "" if off else row.position,
                                            row.word or "",
                                            marker_glyphs(marks_of.get(row.word) or (
                                                suggested_marks.get(row.word) if row.tier == "list"
                                                else None)),
                                            why,
                                            row.deck or ""),
                                    tags=(tag,) if tag else ())
            self._row_cards[item] = row.card_id
        if len(rows) > MAX_PREVIEW_ROWS:
            self._write(f"Showing the first {MAX_PREVIEW_ROWS} of {len(rows)} cards.", "warning")

        # The field pickers offer the fields these notes actually have, now that a preview has
        # been read. Guessing a field name is exactly what WP-L forbids.
        self._offer_fields(stats.get("field_names") or [])

        to_write = stats.get("to_write", 0)
        if to_write:
            self._write(f"Reorder will move {to_write} of {considered} card"
                        f"{'' if considered == 1 else 's'} in "
                        f"{', '.join(stats.get('decks') or []) or 'the chosen scope'}"
                        f"{self._touchup_clause(stats)}.{self._unmatched_clause(stats)}"
                        f"{self._deselected_clause(stats)}{self._later_clause(stats)}", "good")
        elif considered and self._later_clause(stats):
            # Nothing to move, but the cards not on the list still have something done to them
            # (§13) — Reorder does exactly that, and says so here first.
            self._write("Every card is already in the right place."
                        f"{self._later_clause(stats)}{self._deselected_clause(stats)}", "good")
        elif considered:
            self._write("Every card is already in the right place — Reorder would change nothing."
                        f"{self._deselected_clause(stats)}", "good")
        elif stats.get("empty_list"):             # M-W2-1: every file watched or Finished — said, not "no cards"
            self._write(reposition.EMPTY_LIST, "good")
        else:
            self._write("There are no new cards in this scope.", "warning")
        if self._list_current is False and self._must_generate():
            if self._generate_tried:
                self._write("Generate didn't bring the list up to date — see Surasura's log.", "problem")
            # One line: the pane shows its last, and what changed is the button's tooltip's to say.
            self._write("Your list is out of date — press Generate & preview to bring it up to date "
                        "first.", "warning")

        self._render_checks()

        # Only now is Reorder reachable, and only for the scope this preview describes. Synced
        # here rather than waiting for the worker's `__DONE__`: the gate belongs to the preview,
        # not to whichever message happens to arrive after it. `key` is the scope the preview was
        # MADE for; if the user changed anything while it ran, it no longer matches and Reorder
        # stays shut. Without one (a deselection re-render, on this thread) it is the current scope.
        self._preview_scope = self._scope_key() if key is None else key
        self._sync_buttons()

    # ------------------------------------------------------------- deselection (WP-O)
    def _with_deselection(self, stats):
        """The dry run as it stands with the clicked-off rows taken out of it.

        Re-planned by `plan` itself, not re-sorted here. The panel cannot read Anki again on every
        click, but it must not answer with a second implementation of the ordering either: the rows
        the last dry run produced are handed straight back to the planner with the deselected ids
        excluded, so what the table shows after a toggle is what `reposition.run` will write — it
        receives the same ids in `junban_exclude_cards` and reaches the same function.
        """
        if not stats:
            return stats
        # §16: a tick in "Same word as one on your list?" is re-planned the same way — the rows
        # turned into what the tick makes them (`with_answers`), then the planner itself.
        retold = self._changed_ticks()
        rows = stats.get("order") or []
        dropped = {row.card_id for row in rows} & self._deselected
        if not dropped and not retold:
            return stats
        from modules.junban.plan import replan, with_answers
        _writes, replanned = replan(with_answers(rows, retold) if retold else rows, dropped,
                                    number=stats.get("number"))   # the preview's numbering, if it is on
        merged = dict(stats)
        # Only the keys the new plan actually decides. `total`, the skip counts and everything the
        # engine attached (decks, marks, fields) describe the read, which has not changed.
        for key in ("order", "matched", "library", "tiers", "unmatched", "deselected", "taken_off",
                    "taken_off_ids", "to_write", "unchanged", "base"):
            merged[key] = replanned.get(key)
        if "numbering" in replanned:                 # the preview's own numbering, re-planned with the click
            merged["numbering"] = replanned["numbering"]
        # P4.2.3 (P2.2 adversary #14): the pinned count, re-planned with the click — a pinned card clicked off isn't
        # lifted, so the run lifts one fewer; none pinned any more, none counted (the plan leaves the key out)
        if "pinned" in replanned:
            merged["pinned"] = replanned["pinned"]
        else:
            merged.pop("pinned", None)

        # The touch-ups DO change: they land only on notes that are matched and actually moving, so
        # deselecting a matched card removes one. Narrowed with the engine's own `restrict` — the
        # same call the run itself makes — rather than by re-deriving the accounting here, which the
        # module owns. One pass over rows already in hand, so a toggle costs nothing.
        # A tick can put a card ON the list, which narrowing cannot add: the engine planned the
        # touch-ups of every card that could be on it (`touchups_all`), and that is what is narrowed.
        touchups = (stats.get("touchups_all") if retold else None) or stats.get("touchups")
        if touchups:
            still = {row.note_id for row in (replanned.get("order") or [])
                     if row.rank is not None and row.changed and row.note_id is not None}
            merged["touchups"] = touchup.restrict(touchups, still, touchup.options(self._settings()))
        # §13, re-planned by the engine's own planner: a word clicked OFF the list now joins the
        # cards the actions reach, and a card clicked to be left alone leaves them.
        settings = self._settings()
        later_opts = unlisted.options(settings)
        if unlisted.is_active(later_opts):
            taken = set(replanned.get("taken_off_ids") or ())
            merged["later"] = unlisted.plan(
                replanned.get("order") or [], stats.get("marks") or {}, self._lang_code(),
                stats.get("flags_of") or {}, stats.get("note_tags") or {}, later_opts,
                parent=touchup.options(settings).get("tag"), exclude=dropped - taken, taken_off=taken)
        return merged

    # --------------------------------------------- "Same word as one on your list?" (§16)
    def _changed_ticks(self):
        """`{card_word: ticked}` where the ticks differ from what the run would read today — the
        only words the preview has to re-plan, and the only earlier answers worth recording."""
        entries = (self._preview_stats or {}).get("suggestions") or []
        recorded = {entry["word"]: entry.get("answer") == "yes" for entry in entries}
        return {word: on for word, on in (self._ticked or {}).items()
                if word in recorded and recorded[word] != on}

    def _answers_to_record(self):
        """What Reorder records: every word still to check (ticked = yes, unticked = no — seen, and
        left), and an earlier answer only where the user changed it."""
        out = []
        for entry in (self._preview_stats or {}).get("suggestions") or []:
            on = bool((self._ticked or {}).get(entry["word"]))
            if entry.get("answer") is None or (entry.get("answer") == "yes") != on:
                out.append((entry["word"], entry["key"], on, entry.get("via")))
        return out

    def _render_checks(self):
        """Draw the check list — or hide it: it exists only while there is something to check (or
        the user asked to see their earlier answers). Its scroll position survives a tick."""
        entries = (self._preview_stats or {}).get("suggestions") or []
        pending = [entry for entry in entries if entry.get("answer") is None]
        earlier = [entry for entry in entries if entry.get("answer") is not None]
        shown = pending + (earlier if self._show_earlier else [])
        try:
            top = self.check_tree.yview()[0]
            for item in self.check_tree.get_children():
                self.check_tree.delete(item)
        except tk.TclError:
            return
        self._check_rows = {}
        if not shown:
            self._checks_box.pack_forget()
            if earlier:
                self._write_link(f"{len(earlier)} word{'' if len(earlier) == 1 else 's'} you answered "
                                 "before about spellings — ", "see or change them", self._toggle_earlier)
            return
        for entry in shown:
            on = bool((self._ticked or {}).get(entry["word"]))
            tags = ("ticked",) if on else (("earlier",) if entry.get("answer") is not None else ())
            item = self.check_tree.insert("", "end", tags=tags, values=(
                CHECK_ON if on else CHECK_OFF, entry["word"],
                f"→ {entry['key']}   #{entry['rank'] + 1:,}", entry.get("reading") or "",
                entry.get("excerpt") or ""))
            self._check_rows[item] = entry["word"]
        self.check_tree.configure(height=min(len(shown), CHECK_ROWS))
        if len(shown) > CHECK_ROWS:
            self.check_bar.pack(side=tk.RIGHT, fill=tk.Y)
        else:
            self.check_bar.pack_forget()
        self.check_tree.yview_moveto(top)
        self.checks_count_var.set(f"{len(pending)} to check" if pending else "all answered")
        if earlier:
            self.earlier_var.set("hide earlier answers" if self._show_earlier
                                 else f"earlier answers ({len(earlier)})")
            self.lnk_earlier.pack(side=tk.RIGHT)
        else:
            self.lnk_earlier.pack_forget()
        self._checks_box.pack(fill=tk.X, pady=(8, 0), before=self._preview_box)

    def _write_link(self, text, link, command):
        """A message line ending in a link — the way to the earlier answers when nothing is left to
        check, so the list itself takes no room."""
        self.messages.config(state="normal")
        self.messages.insert("end", text)
        self.messages.insert("end", link, ("link",))
        self.messages.insert("end", "\n")
        self.messages.tag_configure("link", foreground=ACCENT, underline=True)
        self.messages.tag_bind("link", "<Button-1>", lambda _e: command())
        self.messages.tag_bind("link", "<Enter>", lambda _e: self.messages.config(cursor="hand2"))
        self.messages.tag_bind("link", "<Leave>", lambda _e: self.messages.config(cursor=""))
        self.messages.config(state="disabled")
        self._show_messages(True)

    def _on_check_clicked(self, event):
        """A click anywhere on a row ticks it — the row is the checkbox, as in the table below."""
        if self.busy or self._generating:
            return "break"
        try:
            item = self.check_tree.identify_row(event.y)
        except tk.TclError:
            return "break"
        if item:
            self.check_tree.focus_set()
            self._toggle_check(item)
        return "break"

    def _on_check_space(self, _event=None):
        if not (self.busy or self._generating):
            item = self.check_tree.focus()
            if item:
                self._toggle_check(item)
        return "break"

    def _toggle_check(self, item):
        """Tick or untick one word, then redraw — the preview re-plans with it at once (I5)."""
        word = self._check_rows.get(item)
        if word is None or self._ticked is None:
            return
        self._ticked[word] = not self._ticked.get(word)
        self._rerender_preview()
        for again, name in self._check_rows.items():
            if name == word:
                self.check_tree.focus(again)
                self.check_tree.selection_set(again)

    def _toggle_earlier(self):
        self._show_earlier = not self._show_earlier
        self._rerender_preview()

    @staticmethod
    def _unmatched_clause(stats):
        """" 12 unmatched cards (greyed) keep their order at the back." — and nothing at zero, which
        is the usual answer now that every card is given a tier (Junban_Backlog_Spec §5.4)."""
        count = (stats or {}).get("unmatched") or 0
        if not count:
            return ""
        return (f" {count} unmatched card{'' if count == 1 else 's'} (greyed) "
                f"keep{'s its' if count == 1 else ' their'} order at the back.")

    @staticmethod
    def _deselected_clause(stats):
        """" 2 you took off your list go with the cards not on it. 1 you left alone keeps its
        current order." — and **nothing at all** at zero, the normal case.

        Two outcomes of one click (the user, 2026-09-23): a word on the list clicked off is treated
        as not on it; a card already not on it, clicked, is left alone.
        """
        stats = stats or {}
        taken = stats.get("taken_off") or 0
        alone = (stats.get("deselected") or 0) - taken
        text = ""
        if taken:
            text += (" 1 you took off your list goes" if taken == 1 else
                     f" {taken} you took off your list go") + " with the cards not on it."
        if alone == 1:
            text += " 1 you left alone keeps its current order."
        elif alone:
            text += f" {alone} you left alone keep their current order."
        return text

    def _on_row_clicked(self, event):
        """A click anywhere on a row toggles it — the whole row is the checkbox `ttk` lacks."""
        if self.busy:
            return None
        try:
            if self.tree.identify_region(event.x, event.y) not in ("cell", "tree"):
                return None                 # a heading, or a column separator being dragged
            item = self.tree.identify_row(event.y)
        except tk.TclError:
            return None
        if not item:
            return None
        self.tree.focus_set()               # so `Space` continues from where the mouse left off
        self._toggle_row(item)
        return "break"

    def _on_row_space(self, _event=None):
        """`Space` toggles the focused row — the same act, without a mouse.

        Returns "break" so ttk's own space binding (which toggles the *selection*) never runs: this
        table selects nothing, and two meanings for one key is how a user ends up excluding a card
        they meant to look at.
        """
        if self.busy:
            return "break"
        item = self.tree.focus()
        if item:
            self._toggle_row(item)
        return "break"

    def _toggle_row(self, item):
        """In or out of this run, then redraw — the preview is never one click out of date (I5)."""
        card_id = self._row_cards.get(item)
        if card_id is None:
            return
        if card_id in self._deselected:
            self._deselected.discard(card_id)
        else:
            self._deselected.add(card_id)
        self._rerender_preview()
        self._focus_card(card_id)

    def _in_display_order(self, order):
        """The rows in the order they are already ON SCREEN, not the order the plan now holds.

        Deselecting sends a card to the back of the plan, and following it there was miserable: the
        row you clicked leapt hundreds of places away, so undoing an accidental click meant hunting
        for it. Rows therefore keep the position they were first drawn in, and deselection is shown
        *in place* — `✗`, no number, greyed. Click again and it is right where you left it.

        This misrepresents nothing. The number in the `#` column is the claim "this card is in the
        run", and a deselected row does not carry one; the numbered rows still read 1..N in exactly
        the order they will be written. The plan is the plan — this is only where each row is drawn.

        A card the plan knows but the display has not seen yet (the first render, or a fresh
        preview) simply keeps the plan's own order.
        """
        rows = list(order)
        if not self._display_order:
            self._display_order = [row.card_id for row in rows]
            return rows
        display = self._display_order
        # §16: a ticked card really moves — it joins the list's words — so it is drawn where the plan
        # now puts it, just after the card before it; unticked, it is back where it was first drawn.
        retold = self._changed_ticks()
        if retold:
            moving = {row.card_id for row in rows if row.word in retold}
            display = [card_id for card_id in self._display_order if card_id not in moving]
            for i, row in enumerate(rows):
                if row.card_id in moving:
                    before = rows[i - 1].card_id if i else None
                    display.insert(display.index(before) + 1 if before in display else 0, row.card_id)
        rank = {card_id: i for i, card_id in enumerate(display)}
        unseen = len(rank)
        return sorted(rows, key=lambda row: rank.get(row.card_id, unseen))

    def _rerender_preview(self):
        """Redraw the last dry run with the deselections as they now stand. Reads nothing new.

        The scroll position is held across the redraw. Deselecting sends that row to the back of a
        list that can be hundreds long, and following it there yanked the whole table out from under
        the user on every click — they are working through the top of the list, and that is where
        the view should stay.
        """
        if self._preview_stats is None:
            return
        stats, checks = self._preview_stats, self._preview_checks
        try:
            top, _bottom = self.tree.yview()
        except tk.TclError:
            top = None
        self._clear_messages()
        self._clear_rows()
        self._show_preview(stats, checks or {})
        if top is not None:
            try:
                self.tree.yview_moveto(top)
            except tk.TclError:
                pass

    def _focus_card(self, card_id):
        """Keep the keyboard on the card just toggled, and SHOW it as selected.

        Deliberately no `see()`: scrolling to the row is what made the table jump. Focus and
        selection are enough — the highlight says which row was acted on, and the view stays put.
        """
        for item, cid in self._row_cards.items():
            if cid == card_id:
                try:
                    self.tree.focus(item)
                    self.tree.selection_set(item)
                except tk.TclError:
                    pass
                return

    @staticmethod
    def _later_acts(stats):
        """`{card_id: "tag + flag + suspend"}` — what §13's ticked actions will do to each card."""
        later = (stats or {}).get("later") or {}
        tagged = set(later.get("tag_notes") or ())
        flags, suspend = later.get("flags") or {}, set(later.get("suspend") or ())
        acts = {}
        for card_id in later.get("cards") or []:
            names = [name for name, hit in (("tag", (later.get("note_of") or {}).get(card_id) in tagged),
                                            ("flag", card_id in flags),
                                            ("suspend", card_id in suspend)) if hit]
            if names:
                acts[card_id] = " + ".join(names)
        return acts

    @staticmethod
    def _later_clause(stats):
        """" Not on your list: tag 40 notes, flag 52 cards purple and suspend 52 cards." — §13's
        promise, stated before the write (I5), and nothing at all when "No action" is chosen."""
        counts = ((stats or {}).get("later") or {}).get("counts") or {}
        parts = []
        for key, verb, noun, tail in (("tag", "tag", "note", ""),
                                      ("flag", "flag", "card", " purple"),
                                      ("suspend", "suspend", "card", "")):
            count = counts.get(key) or 0
            if count:
                parts.append(f"{verb} {count} {noun}{'' if count == 1 else 's'}{tail}")
        if not parts:
            return returning_clause(stats)
        text = " Not on your list: " + ", ".join(parts[:-1] + [("and " if len(parts) > 1 else "") + parts[-1]]) + "."
        kept = counts.get("flag_kept") or 0
        if kept:
            text += f" {kept} you flagged another colour keep{'s' if kept == 1 else ''} it."
        return text + returning_clause(stats)

    @staticmethod
    def _touchup_clause(stats):
        """" and tag 47 notes" — WP-L's promise, in the SAME sentence as the move.

        One sentence on purpose. The preview is the only confirmation there is (I5), and splitting
        "it will reorder your cards" from "it will also edit your notes" into two lines lets a user
        read one and act on it. Every number comes from the planner's own pass, so what is promised
        here and what reaches Anki cannot disagree.
        """
        counts = ((stats or {}).get("touchups") or {}).get("counts") or {}
        parts = []
        tagged = counts.get("tag") or 0
        if tagged:
            parts.append(f"tag {tagged} note{'' if tagged == 1 else 's'}")
        marked = counts.get("markers") or 0
        if marked:
            parts.append(f"add marker tags to {marked} note{'' if marked == 1 else 's'}")
        frequency = counts.get("frequency") or 0
        if frequency:
            parts.append(f"add the frequency number to {frequency} "
                         f"note{'' if frequency == 1 else 's'}")
        freqsort = counts.get("freqsort") or 0
        if freqsort:
            parts.append(f"OVERWRITE the sort number on {freqsort} "
                         f"note{'' if freqsort == 1 else 's'}")
        if not parts:
            return ""
        return ", and " + ", ".join(parts[:-1] + [("and " if len(parts) > 1 else "") + parts[-1]])

    def _offer_fields(self, names):
        """Fill the frequency field picker with the note fields actually found in scope.

        The user's own field names, read off their own notes — never a guessed default. Whatever
        they have already typed stays selected even if it is not in the list, so a field that
        belongs to a note type outside this scope is not silently dropped.
        """
        for box, variable in ((getattr(self, "freq_box", None), getattr(self, "freq_field", None)),):
            if box is None or variable is None:
                continue
            try:
                current = variable.get().strip()
                values = list(names)
                if current and current not in values:
                    values.append(current)
                box.config(values=values)
            except tk.TclError:
                pass

    def _show_report(self, report):
        """Render a finished run or restore. Problems are shown verbatim — `RestoreRefused`'s
        message names both scopes, and paraphrasing it would leave the user guessing."""
        for line in report.get("warnings") or []:
            self._write(line, "warning")
        for line in report.get("problems") or []:
            self._write(line, "problem")
        self._write(report.get("message") or "", "good" if report.get("ok") else "problem")
        failures = report.get("failures") or []
        if failures:
            self._write(f"{len(failures)} card(s) could not be changed; the first was "
                        f"{failures[0][0]}.", "problem")
        note_failures = report.get("note_failures") or []
        if note_failures:
            # A separate line, because these are NOTE ids: reporting them together with card ids
            # would give the user a number they cannot look up in Anki's browser.
            self._write(f"{len(note_failures)} note(s) could not be updated; the first was "
                        f"{note_failures[0][0]}.", "problem")
        if report.get("snapshot"):
            self._write(f"Previous order saved to {report['snapshot']}")
        # The collection has moved on: whatever the table shows is last minute's answer.
        self._preview_scope = None
        self._sync_buttons()

    def _clear_preview(self):
        """Throw the preview away — the rows AND the deselections that pointed at them.

        WP-O: a deselection is a decision about the rows on screen. A scope, order, filter or
        touch-up change replaces those rows, so keeping the card ids would leave the next run
        quietly missing cards for a reason no longer visible anywhere.
        """
        self._clear_rows()
        self._deselected.clear()
        # The drawn order belongs to the rows being thrown away; the next preview fixes its own.
        self._display_order = []
        self._preview_stats = None
        self._preview_checks = None
        # §16: the ticks were answers about these rows — unrecorded, they go with them.
        self._ticked = None
        self._show_earlier = False
        self._render_checks()

    def _clear_rows(self):
        """Just the table. Used by a redraw, which must keep the deselections it is redrawing."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._row_cards = {}

    def _write(self, text, tag=None):
        if not text:
            return
        self.messages.config(state="normal")
        self.messages.insert("end", str(text) + "\n", (tag,) if tag else ())
        self.messages.see("end")
        self.messages.config(state="disabled")
        self._show_messages(True)

    def _clear_messages(self):
        self.messages.config(state="normal")
        self.messages.delete("1.0", "end")
        self.messages.config(state="disabled")
        self._show_messages(False)

    def _show_messages(self, visible):
        """The message pane only exists while it has something to say.

        An empty bordered box is a dead grey rectangle, and on a 720px-tall screen it costs two
        rows of the preview table for nothing. Packed against the BOTTOM like the rest of the
        chrome, so re-showing it never pushes the action row off-screen.
        """
        try:
            mapped = bool(self.messages.winfo_ismapped())
            if visible and not mapped:
                self.messages.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0), before=self.progress)
            elif not visible and mapped:
                self.messages.pack_forget()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------- pump
    def _drain(self):
        """The pump: drain, then re-arm — but only while the window is still alive."""
        self._drain_once()
        if self.winfo_exists() and not self._closing:
            self.after(100, self._drain)

    def _drain_once(self):
        """One pass over the queue, on the UI thread. Split out so a test can pump it without
        arming a timer that would outlive the window."""
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple) and item:
                    tag = item[0]
                    if tag == "__CONN__":
                        self._set_connection(item[1], item[2])
                        continue
                    if tag == "__PREVIEW__":
                        self._show_preview(item[1], item[2], item[3] if len(item) > 3 else None)
                        continue
                    if tag == "__REPORT__":
                        self._first_touch_changed()     # a run or a restore: the record may have grown (C21)
                        self._show_report(item[1])
                        continue
                    if tag == "__PROGRESS__":
                        self.progress["maximum"] = max(1, item[2])
                        self.progress["value"] = item[1]
                        continue
                    if tag == "__MESSAGE__":
                        self._write(item[1], item[2] if len(item) > 2 else None)
                        continue
                    if tag == "__DONE__":
                        self._set_busy(False)
                        continue
                    if tag == "__CALL__":           # a step of the put-back's flow (FT), on this thread
                        try:
                            item[1]()
                        except Exception as e:      # C30: shown, and the pump goes on
                            self._write(f"Something went wrong showing this ({e}).", "problem")
                            self._set_busy(False)
                        continue
                self._write(item)
        except queue.Empty:
            pass


if __name__ == "__main__":          # pragma: no cover - manual launch
    root = tk.Tk()
    root.withdraw()
    JunbanGui(root)
    root.mainloop()

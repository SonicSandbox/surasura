# SPDX-License-Identifier: GPL-3.0-or-later
"""The Anki Backfill window — fill fields on Anki cards from Surasura (Patterns_Spec.md §17).

    probe  ->  PREVIEW  ->  Fill        (and Restore)

Reached from the Anki window and from 順, and one window either way: a second click brings it to the
front (`open_backfill`). It keeps 順's rules (`gui.py`):

* **The preview is the confirmation.** Fill stays off until a preview of the current choices is on
  screen; changing any choice throws the preview away. A fill re-reads each previewed note first and
  leaves one whose field changed since.
* **Anki closed is a state, not an error.** The light says so and the window stays usable.
* **Nothing touches Tk from a worker.** Work runs on daemon threads and reports through `self.q`,
  drained by an `after()` pump — gated on `SURASURA_NO_UI_TIMERS` for tests.
* **It never switches the host's theme.** It paints with 順's own `Jun.*` styles (`gui.init_styles`,
  shared, not copied) and uses 順's themed dialog for every confirmation.

Plain on purpose (the user, 2026-09-24: "a bit too dense"): one line under the title; one row per fill
— its tick box, a "?" that explains it simply, where it goes ("Lapis → Patterns"; the note-type
pickers behind it, in a small window) and its own extras; one summary line ("Fill 1,066 notes · 391
skipped") with the reasons behind an "ⓘ". A later fill is one more row.

The library's パターン set keeps up with the library (the user, 2026-10-01: "in the background … so it doesn't hold
the generate or anything hostage"): opening the window builds it again in the background once the library has grown
by a quarter since, and "Rebuild from my library" does it now — a quiet line while it runs, Preview and Fill reading
the set in use until the new one goes in (`backfill.rebuild_in_background`).

Built once. A choice redraws only its own widget; the preview table is filled in one batch. The
choices stay live while a job runs: the latest win — a preview made for earlier ones is dropped and
one for the new ones follows. The databases, the tagger and the known words load once per window
(`backfill.Session`) and are shared by every preview and fill until the language changes.
"""

import html
import os
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from modules.junban import backfill
from modules.junban import gui as junban_gui
from modules.junban import undo
from modules.junban.gui import (ACCENT, BG, ERROR, MUTED, SECONDARY, SURFACE, TEXT, ToolTip,
                                init_styles)

TITLE = "Anki Backfill"
ALL_DECKS = "All decks"
SKIP_LABEL = "— skip —"
MAX_PREVIEW_ROWS = 4000
# A note type's language in the Fields window (Patterns_Chinese_Spec.md D7): set, or not — "Language?".
LANGUAGE_LABELS = {"ja": "Japanese", "zh": "Chinese"}
UNSET_LABEL = "Language?"

# Pasted into a note type's Styling, it styles the パターン lines on any card — the field names each
# line's kind in its class (Anki_Card_Layout_Spec.md §5). Plain CSS: nothing to run.
CARD_STYLE = """/* Surasura パターン */
.pat-particle, .pat-form, .pat-frame, .pat-colloc { font-size: .85em; line-height: 1.7; }
.pat-particle, .pat-form, .pat-frame { opacity: .8; }
.pat-register { display: inline-block; margin-top: .4em; padding: .1em .6em; font-size: .75em;
                border: 1px solid currentColor; border-radius: 6px; opacity: .6; }
"""


def _lines_of(value):
    """A field's lines as one row of text: `〜に 34% · 〜を 24% / 探検する 19%`, `明日から冒険に… / …`."""
    parts = re.split(r"(?i)</div>|<br\s*/?>", value or "")
    return " / ".join(t for t in (html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in parts) if t)


def _short(name, width=22):
    return name if len(name) <= width else name[:width - 1] + "…"


class HelpTip:
    """A "?" or "ⓘ" that explains on hover: an optional title, then short sections — a header, one
    plain line, an example. `content` is `(title, sections)`, or a callable returning it."""

    def __init__(self, widget, content):
        self.widget, self.content, self.tip = widget, content, None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self.tip:
            return
        title, sections = self.content() if callable(self.content) else self.content
        if not title and not sections:
            return
        self.tip = window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{self.widget.winfo_rootx() + 18}+{self.widget.winfo_rooty() + 22}")
        frame = tk.Frame(window, bg=SURFACE, padx=14, pady=10, highlightthickness=1,
                         highlightbackground=MUTED)
        frame.pack()
        if title:
            tk.Label(frame, text=title, bg=SURFACE, fg=ACCENT, font=("Segoe UI", 10, "bold"),
                     justify=tk.LEFT).pack(anchor="w", pady=(0, 2))
        for header, line, example in sections:
            tk.Label(frame, text=header, bg=SURFACE, fg=TEXT, font=("Segoe UI", 9, "bold"),
                     justify=tk.LEFT).pack(anchor="w", pady=(6, 0))
            tk.Label(frame, text=line, bg=SURFACE, fg=TEXT, font=("Segoe UI", 9), justify=tk.LEFT,
                     wraplength=300).pack(anchor="w")
            if example:
                tk.Label(frame, text=example, bg=SURFACE, fg=MUTED, font=("Segoe UI", 9),
                         justify=tk.LEFT).pack(anchor="w")

    def _hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class FieldsDialog(tk.Toplevel):
    """Where one fill goes, per note type in the deck — the ones it fills first — and each note type's
    language: a note type is filled only with its own language's data, and one whose language is not
    set ("Language?") is never filled (Patterns_Chinese_Spec.md S3). Not modal: a choice is saved as it
    is made; Esc or Done closes it."""

    def __init__(self, owner, fill, models, on_change, on_language=None):
        super().__init__(owner)
        self.fill_key = fill.key
        self.title(f"Surasura - {fill.label}")
        self.configure(bg=BG)
        self.transient(owner)
        self.resizable(False, False)
        self.bind("<Escape>", lambda _e: self.destroy())
        frame = ttk.Frame(self, padding=18, style="Jun.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=f"Where {fill.label} goes", style="Jun.TLabel",
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w",
                                                     pady=(0, 10))
        self.vars, self.language_vars = {}, {}
        order = sorted(models.items(), key=lambda m: (not (m[1].get("mapped") or {}).get(fill.key),
                                                      -m[1]["count"], m[0]))
        for row, (name, info) in enumerate(order, start=1):
            ttk.Label(frame, text=f"{name}  ({info['count']:,})", style="Jun.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 16), pady=3)
            var = tk.StringVar(value=(info.get("mapped") or {}).get(fill.key) or SKIP_LABEL)
            box = ttk.Combobox(frame, textvariable=var, state="readonly", width=18,
                               style="Jun.TCombobox", values=[SKIP_LABEL] + list(info["fields"]))
            box.grid(row=row, column=1, sticky="w", pady=3)
            box.bind("<<ComboboxSelected>>", lambda _e, m=name, v=var: on_change(m, v.get()))
            ToolTip(box, f"The field it goes in, on {name} cards.")
            self.vars[name] = var
            language = tk.StringVar(value=LANGUAGE_LABELS.get(info.get("language"), UNSET_LABEL))
            pick = ttk.Combobox(frame, textvariable=language, state="readonly", width=11,
                                style="Jun.TCombobox", values=list(LANGUAGE_LABELS.values()) + [UNSET_LABEL])
            pick.grid(row=row, column=2, sticky="w", padx=(10, 0), pady=3)
            if on_language is not None:
                pick.bind("<<ComboboxSelected>>", lambda _e, m=name, v=language: on_language(m, v.get()))
            ToolTip(pick, f"The language of {name} cards. Not set, cards with kana are Japanese, and "
                          "others are never filled.")
            self.language_vars[name] = language
        done = ttk.Button(frame, text="Done", style="JunSmall.TButton", command=self.destroy)
        done.grid(row=len(order) + 1, column=2, sticky="e", pady=(14, 0))
        ToolTip(done, "Close. Your choices are saved.")


class DataDialog(tk.Toplevel):
    """Where パターン data comes from: Surasura's shared data (a download), or a package from another
    computer (an import) — for the language on screen (S11). Not modal; Esc or Close closes it."""

    def __init__(self, owner, on_download, on_import, language="ja"):
        super().__init__(owner)
        from modules.junban.patterns_package import shared_for
        shared = shared_for(language)
        name = LANGUAGE_LABELS.get(language, language)
        self.title("Surasura - パターン data")
        self.configure(bg=BG)
        self.transient(owner)
        self.resizable(False, False)
        self.bind("<Escape>", lambda _e: self.destroy())
        frame = ttk.Frame(self, padding=18, style="Jun.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="パターン data", style="Jun.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        text = (f"Surasura's shared {name} data: {shared['mb']} MB from GitHub, made from {shared['credit']}."
                if shared else f"Surasura has no shared {name} data yet. A package from another computer "
                               "still imports.")
        self.info = ttk.Label(frame, text=text, style="JunMuted.TLabel", wraplength=380, justify=tk.LEFT)
        self.info.pack(anchor="w", pady=(6, 14))
        row = ttk.Frame(frame, style="Jun.TFrame")
        row.pack(fill=tk.X)
        for text, command, tip, side in (
                ("Download", on_download, "Download it and put it in place. About a minute.", tk.LEFT),
                ("Import a file…", on_import, "A パターン package from another computer (.zip).", tk.LEFT),
                ("Close", self.destroy, "Close.", tk.RIGHT)):
            button = ttk.Button(row, text=text, style="JunSmall.TButton", command=command)
            button.pack(side=side, padx=(0, 8) if side == tk.LEFT else 0)
            ToolTip(button, tip)
            if text == "Download":
                self.btn_download = button
                if not shared:
                    button.state(["disabled"])


class BackfillGui(tk.Toplevel):
    """The window. `app` is the dashboard when there is one — read, never driven."""

    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        self.q = queue.Queue()
        self.busy = False
        self._closing = False
        # Set when the window closes: a fill or restore still waiting for another Anki writer stops
        # without writing (E1.4 §W).
        self._stop = threading.Event()
        self._connected = False
        self._auto_previewed = False
        self._preview_wanted = False    # a choice changed while a job ran: preview when it ends
        self._preview = None            # the last backfill.preview result
        self._preview_key = None        # the choices it was made for; None = no preview
        self._models = {}               # the deck's note types, from the last preview
        self._session = None
        self._session_language = None
        self._fields_dialog = None
        self._data_dialog = None
        self._downloaded_mb = -1
        self._building = None           # the language of the background build on the quiet line, while it runs
        self._swap = None               # a build ended: let the old set go at the first idle moment
        # While open, the window holds `backfill-window` (P1.4 row 1.4.7, as 順 holds `junban-window`): `surasura-cli
        # backfill` stands aside instead of filling the notes this preview describes. Taken and let go on a worker.
        self._window_lock = None
        self._window_lock_guard = threading.Lock()
        self._window_lock_owner = object()      # the hold outlives the worker that takes it (locks.take's `owner`)
        threading.Thread(target=self._hold_window_lock, daemon=True).start()

        saved = self._saved_settings()
        self.deck = tk.StringVar(value=backfill._deck(saved) or ALL_DECKS)
        self.cards = tk.StringVar(value=backfill._cards(saved))
        self.replace = tk.BooleanVar(value=backfill._replace(saved))
        chosen = backfill._fills(saved)
        self.fill_on = {fill.key: tk.BooleanVar(value=fill.key in chosen) for fill in backfill.FILLS}
        self._fields = backfill._field_map(saved)
        self._note_languages = backfill._note_languages(saved)

        self.title(f"Surasura - {TITLE}")
        self.configure(bg=BG)
        # Tall enough that the summary line and the progress bar stay in view with both fills' rows.
        self.geometry("780x660")
        self.minsize(680, 560)
        self.bind("<Escape>", lambda _e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)
        # The dashboard's language can change while this window is open: coming back to it, what is
        # offered follows (`_on_focus`, Patterns_Chinese_Spec.md S5).
        self.bind("<FocusIn>", self._on_focus, add="+")

        init_styles(self)
        self._build_ui()
        self._sync_buttons()

        # Gate the SCHEDULING, not the callback (testing.md §5.4).
        if not os.environ.get("SURASURA_NO_UI_TIMERS"):
            self.after(100, self._drain)
            self.after(50, self.refresh_connection)
            self.after(200, self._rebuild_if_grown)

    def _hold_window_lock(self):
        """Take `backfill-window` for as long as the window is open (`gui.JunbanGui._hold_window_lock`'s way)."""
        try:
            from app import locks
            held = locks.take("backfill-window", "the Backfill window", wait=2.0, owner=self._window_lock_owner)
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
        # Not while a worker is reading them: the session then goes with the worker, when it ends.
        session, self._session = self._session, None
        if session is not None and not self.busy:
            session.close()
        self.destroy()

    # -------------------------------------------------------------------- layout
    def _build_ui(self):
        main = ttk.Frame(self, padding=(16, 12), style="Jun.TFrame")
        main.pack(fill=tk.BOTH, expand=True)

        title_row = ttk.Frame(main, style="Jun.TFrame")
        title_row.pack(fill=tk.X)
        ttk.Label(title_row, text=TITLE, style="JunHeader.TLabel").pack(side=tk.LEFT)
        self.btn_recheck = ttk.Button(title_row, text="⟳", width=3, style="JunIcon.TButton",
                                      command=self.refresh_connection)
        self.btn_recheck.pack(side=tk.RIGHT)
        ToolTip(self.btn_recheck, "Check Anki again.")
        self.conn_var = tk.StringVar(value="● not checked yet")
        self.conn_lbl = ttk.Label(title_row, textvariable=self.conn_var, style="JunState.TLabel")
        self.conn_lbl.pack(side=tk.RIGHT, padx=(0, 10))
        ttk.Label(main, text="Fills fields from Surasura.", style="JunMuted.TLabel").pack(
            anchor="w", pady=(2, 12))

        # Bottom-up, as in 順: the actions and the messages are packed against the bottom first,
        # so a short screen shrinks the table and never pushes the buttons off.
        self._build_actions(main)
        self._build_scope(main)
        self._build_fills(main)
        self._build_preview(main)

    def _build_scope(self, parent):
        row = ttk.Frame(parent, style="Jun.TFrame")
        row.pack(fill=tk.X, before=self._anchor, side=tk.TOP)
        ttk.Label(row, text="Deck", style="Jun.TLabel").pack(side=tk.LEFT)
        self.deck_box = ttk.Combobox(row, textvariable=self.deck, state="readonly", width=20,
                                     style="Jun.TCombobox", values=[ALL_DECKS])
        self.deck_box.pack(side=tk.LEFT, padx=(8, 22))
        self.deck_box.bind("<<ComboboxSelected>>", lambda _e: self._on_choice())
        ToolTip(self.deck_box, "The deck to fill. Subdecks included.")

        ttk.Label(row, text="Cards", style="Jun.TLabel").pack(side=tk.LEFT)
        # "All" is every card but the new ones whose word you know — the label says less than that on
        # purpose ("All but known" read as "all but your known cards"); the tooltip says it whole.
        for value, text, tip in (("all", "All", "Every card, except new ones whose word you "
                                                "already know."),
                                 ("new", "New only", "Only cards you haven't studied yet.")):
            radio = ttk.Radiobutton(row, text=text, value=value, variable=self.cards,
                                    style="Jun.TRadiobutton", command=self._on_choice)
            radio.pack(side=tk.LEFT, padx=(10, 0))
            ToolTip(radio, tip)
        self.chk_replace = ttk.Checkbutton(row, text="Replace", variable=self.replace,
                                           style="Jun.TCheckbutton", command=self._on_choice)
        self.chk_replace.pack(side=tk.LEFT, padx=(22, 0))
        ToolTip(self.chk_replace, "Overwrite what's in the field. Restore puts it back.")

    def _build_fills(self, parent):
        """One row per fill, a hairline between: tick box, "?", where it goes, its own extras."""
        box = ttk.Frame(parent, style="Jun.TFrame")
        box.pack(fill=tk.X, pady=(14, 0), side=tk.TOP, before=self._anchor)
        self._targets, self._available, self._checks, self.help_tips = {}, {}, {}, {}
        for fill in backfill.FILLS:
            tk.Frame(box, height=1, bg=SURFACE).pack(fill=tk.X)
            row = ttk.Frame(box, style="Jun.TFrame")
            row.pack(fill=tk.X, pady=8)
            check = ttk.Checkbutton(row, text=fill.label, variable=self.fill_on[fill.key],
                                    style="Jun.TCheckbutton", command=self._on_choice)
            check.pack(side=tk.LEFT)
            # Whether it is offered, and what its tooltip and "?" say, follow the language (S5).
            self._checks[fill.key] = (check, ToolTip(check, fill.tip))
            help_icon = ttk.Label(row, text="?", style="JunHelp.TLabel", cursor="question_arrow")
            help_icon.pack(side=tk.LEFT, padx=(8, 0))
            self.help_tips[fill.key] = HelpTip(help_icon, lambda f=fill: backfill.help_for(f, self._lang_code()))
            if fill.key == "patterns":
                copy = ttk.Button(row, text="Copy card style", style="JunSmall.TButton",
                                  command=self.on_copy_style)
                copy.pack(side=tk.RIGHT)
                ToolTip(copy, "Style these lines on another note type.")
            target = ttk.Button(row, text="Fields…", style="JunSmall.TButton",
                                command=lambda f=fill: self.on_fields(f))
            target.pack(side=tk.RIGHT, padx=(0, 8))
            ToolTip(target, "Which field it goes in, for each note type.")
            self._targets[fill.key] = target
            if fill.key == "patterns":
                # Shown only while this computer has no general パターン database (`_show_get_data`).
                self.btn_get_data = ttk.Button(row, text="Get data…", style="JunSmall.TButton",
                                               command=self.on_get_data)
                ToolTip(self.btn_get_data, "Get パターン data: download Surasura's, or import yours.")
                # Shown only while there is a library set to rebuild (`_show_rebuild`); its numbers are read on hover.
                self.btn_rebuild = ttk.Button(row, text="Rebuild from my library", style="JunSmall.TButton",
                                              command=self.on_rebuild)
                self.rebuild_tip = ToolTip(self.btn_rebuild, lambda: backfill.rebuild_tip(self._lang_code()))
        tk.Frame(box, height=1, bg=SURFACE).pack(fill=tk.X)

    def _build_preview(self, parent):
        row = ttk.Frame(parent, style="Jun.TFrame")
        row.pack(fill=tk.X, pady=(12, 4), side=tk.TOP, before=self._anchor)
        self.summary_var = tk.StringVar(value="")
        ttk.Label(row, textvariable=self.summary_var, style="JunCount.TLabel").pack(side=tk.LEFT)
        # Packed only while there is something behind it (`_show_details`).
        self.details = ttk.Label(row, text="ⓘ", style="JunHelp.TLabel", cursor="question_arrow")
        self.details_tip = HelpTip(self.details, self._details)
        # A background build of the library's パターン, while it runs (`_watch_build`); empty otherwise.
        self.build_var = tk.StringVar(value="")
        ttk.Label(row, textvariable=self.build_var, style="JunMuted.TLabel").pack(side=tk.RIGHT)
        frame = ttk.Frame(parent, style="Jun.TFrame")
        frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP, before=self._anchor)
        columns = ("word", "fill", "action", "value")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", style="Jun.Treeview",
                                 selectmode="none")
        for column, text, width, stretch in (("word", "Word", 110, False),
                                             ("fill", "Fill", 70, False),
                                             ("action", "Result", 110, False),
                                             ("value", "What goes in", 420, True)):
            self.tree.heading(column, text=text, anchor="w")
            self.tree.column(column, width=width, stretch=stretch, anchor="w")
        self.tree.tag_configure("skip", foreground=MUTED)
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview,
                               style="Jun.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _build_actions(self, parent):
        row = ttk.Frame(parent, style="Jun.TFrame")
        row.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        self.btn_preview = ttk.Button(row, text="Preview", style="Jun.TButton", command=self.on_preview)
        self.btn_preview.pack(side=tk.LEFT)
        self.preview_tip = ToolTip(self.btn_preview, "")      # its text follows the button's (_sync_buttons)
        self.btn_fill = ttk.Button(row, text="Fill", style="Jun.TButton", command=self.on_fill)
        self.btn_fill.pack(side=tk.RIGHT)
        ToolTip(self.btn_fill, "Write the previewed fields to Anki.")
        self.btn_restore = ttk.Button(row, text="Restore", style="Jun.TButton", command=self.on_restore)
        self.btn_restore.pack(side=tk.RIGHT, padx=(0, 8))
        ToolTip(self.btn_restore, "Put back what was there before Backfill wrote.")

        self.progress = ttk.Progressbar(parent, mode="determinate",
                                        style="Jun.Horizontal.TProgressbar")
        self.progress.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        self.messages = tk.Text(parent, height=3, bg=SURFACE, fg=TEXT, relief=tk.FLAT, wrap=tk.WORD,
                                font=("Segoe UI", 9), state="disabled", highlightthickness=0,
                                padx=8, pady=6)
        for tag, colour in (("problem", ERROR), ("warning", ACCENT), ("good", SECONDARY)):
            self.messages.tag_configure(tag, foreground=colour)
        # Everything above packs `before` this, so it keeps its place at the top of the bottom stack.
        self._anchor = self.progress

    # ------------------------------------------------------------------ settings
    @staticmethod
    def _saved_settings():
        try:
            from app import settings_manager
            loaded = settings_manager.load_settings()
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            import modules.junban as junban
            return dict(junban.SETTINGS_DEFAULTS)

    def _lang_code(self):
        try:
            if self.app is not None:
                return self.app.var_language.get() or "ja"
        except Exception:
            pass
        return str(self._saved_settings().get("target_language") or "ja")

    def _choices(self):
        """The settings this window owns, as its widgets read now. Fresh containers every time."""
        deck = self.deck.get().strip()
        return {"junban_backfill_deck": "" if deck == ALL_DECKS else deck,
                "junban_backfill_cards": self.cards.get(),
                "junban_backfill_replace": bool(self.replace.get()),
                "junban_backfill_fills": [f.key for f in backfill.FILLS if self.fill_on[f.key].get()],
                "junban_backfill_fields": {fill: dict(models) for fill, models in self._fields.items()},
                "junban_backfill_note_languages": dict(self._note_languages)}

    def _settings(self):
        """What the engine is handed: the saved settings, the language, and this window's choices."""
        return dict(self._saved_settings(), target_language=self._lang_code(), **self._choices())

    def _key(self):
        choices = self._choices()
        fields = tuple(sorted((fill, tuple(sorted(models.items())))
                              for fill, models in choices.pop("junban_backfill_fields").items()))
        languages = tuple(sorted(choices.pop("junban_backfill_note_languages").items()))
        return (self._lang_code(), fields, languages,
                tuple(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in choices.items())))

    def _save(self):
        """This window's own keys, onto settings.json as it is (`settings_manager.save_keys`)."""
        try:
            from app import settings_manager
            settings_manager.save_keys(self._choices())
        except Exception as e:
            self._write(f"Could not save your choices: {e}", "problem")

    def _on_choice(self):
        """Any choice changes what a fill would write: the preview goes, and a new one follows."""
        self._clear_preview()
        self._save()
        self._sync_buttons()
        self._want_preview()

    def _needs_build(self):
        """Nothing to fill from yet (a library never built): Preview builds it first. Never started
        by itself — it takes about a minute."""
        language = self._lang_code()
        return any(language in f.languages for f in backfill.FILLS if self.fill_on[f.key].get()) \
            and not backfill.data_ready(language)

    # ------------------------------------------------------------------- state
    def _sync_availability(self):
        """Which fills the language on screen is offered — each tick box and its tooltip — read afresh
        on every sync, never once at construction (Patterns_Chinese_Spec.md S5)."""
        language = self._lang_code()
        for fill in backfill.FILLS:
            available = self._available[fill.key] = language in fill.languages
            check, tip = self._checks[fill.key]
            try:
                check.state(["!disabled"] if available else ["disabled"])
            except tk.TclError:
                pass
            tip.text = fill.tip if available else "Not for this language yet."

    def _on_focus(self, _event=None):
        """Back in the window: a preview made for the other language goes, and one for this follows."""
        if self._preview_key is not None and self._preview_key[0] != self._lang_code():
            self._clear_preview()
            self._want_preview()
        self._sync_buttons()

    def _sync_buttons(self):
        self._sync_availability()
        idle = not self.busy
        ready = idle and self._preview_key is not None and self._preview_key == self._key() \
            and bool((self._preview or {}).get("edits"))
        for widget, enabled in ((self.btn_preview, idle), (self.btn_restore, idle),
                                (self.btn_recheck, idle), (self.btn_fill, ready)):
            try:
                widget.config(state=tk.NORMAL if enabled else tk.DISABLED)
            except tk.TclError:
                pass
        for key, target in self._targets.items():
            try:
                target.config(state=tk.NORMAL if self._models and self._available[key] else tk.DISABLED)
            except tk.TclError:
                pass
        self._show_get_data()
        self._show_rebuild()
        build = self._needs_build()
        try:
            self.btn_preview.config(text="Build & preview" if build else "Preview")
        except tk.TclError:
            pass
        self.preview_tip.text = ("Builds what Surasura fills from — once, about a minute. Then "
                                 "previews." if build else "See what would be filled. Changes nothing.")

    def _show_get_data(self):
        """"Get data…" is there only while this computer has no general パターン database."""
        want = self._available.get("patterns") and not backfill.general_ready(self._lang_code())
        try:
            packed = self.btn_get_data.winfo_manager() == "pack"
            if want and not packed:
                self.btn_get_data.pack(side=tk.RIGHT, padx=(0, 8), after=self._targets["patterns"])
            elif not want and packed:
                self.btn_get_data.pack_forget()
            self.btn_get_data.config(state=tk.DISABLED if self.busy else tk.NORMAL)
        except tk.TclError:
            pass

    def _show_rebuild(self):
        """"Rebuild from my library" is there while the language on screen has a library set to rebuild — before
        there is one, Preview builds it ("Build & preview") — and off while a build runs."""
        want = self._available.get("patterns") and backfill.data_ready(self._lang_code())
        try:
            packed = self.btn_rebuild.winfo_manager() == "pack"
            if want and not packed:
                self.btn_rebuild.pack(side=tk.RIGHT, padx=(0, 8), after=self._targets["patterns"])
            elif not want and packed:
                self.btn_rebuild.pack_forget()
            self.btn_rebuild.config(state=tk.DISABLED if backfill.building() else tk.NORMAL)
        except tk.TclError:
            pass

    def _set_busy(self, busy):
        """Busy shows as the bar moving — back and forth until a job reports how far it is (the 例文
        pass file by file, a fill note by note), then filling. Idle, it is empty and still."""
        self.busy = busy
        self._sync_buttons()
        try:
            self.progress.stop()
            self.progress.config(mode="indeterminate" if busy else "determinate", value=0)
            # Gate the SCHEDULING (testing.md §5.4): the animation is ttk's own timer.
            if busy and not os.environ.get("SURASURA_NO_UI_TIMERS"):
                self.progress.start(15)
        except tk.TclError:
            pass

    def _set_connection(self, report, decks):
        self._connected = bool(report.get("ok"))
        if self._connected:
            version = report.get("version")
            self.conn_var.set(f"● connected (AnkiConnect {version})" if version else "● connected")
            self.conn_lbl.config(foreground=SECONDARY)
            values = [ALL_DECKS] + list(decks or [])
            current = self.deck.get()
            self.deck_box.config(values=values if current in values else values + [current])
        else:
            self.conn_var.set("● not connected")
            self.conn_lbl.config(foreground=ERROR)
            self._write("Start Anki with AnkiConnect, then press ⟳.", "warning")
        self._sync_buttons()
        # "It just works", as in 順: the choices are made and a preview only reads, so the first one
        # runs by itself — when the probe's job ends (`__DONE__`). Never under test: it reads Anki.
        if (self._connected and not self._auto_previewed and not self._needs_build()
                and not os.environ.get("SURASURA_NO_UI_TIMERS")):
            self._auto_previewed = True
            self._preview_wanted = True

    def _show_targets(self):
        for fill in backfill.FILLS:
            self._targets[fill.key].config(text=self._target_text(fill))

    def _target_text(self, fill):
        """Where a fill goes, on its button: "Lapis → Patterns", "2 note types", "Choose a field…"."""
        if not self._models:
            return "Fields…"
        mapped = [(name, (info.get("mapped") or {}).get(fill.key)) for name, info in self._models.items()]
        mapped = [(name, field) for name, field in mapped if field]
        if not mapped:
            return "Choose a field…"
        if len(mapped) > 1:
            return f"{len(mapped)} note types"
        return f"{_short(mapped[0][0])} → {mapped[0][1]}"

    def _details(self):
        """Behind the summary's ⓘ: how many were replaced and why the rest wait, in plain words — per
        fill, under its name, when more than one is ticked."""
        by_fill = (self._preview or {}).get("by_fill") or {}
        lines = []
        for fill in backfill.FILLS:
            counts = by_fill.get(fill.key)
            if counts is None:
                continue
            reasons = backfill.skipped(counts)
            if len(by_fill) > 1:
                done = counts.get("fill", 0) + counts.get("replace", 0)
                lines.append((fill.label, f"{done:,} to fill"
                              + (f" · {sum(n for _l, n in reasons):,} skipped" if reasons else ""), ""))
            if counts.get("replace"):
                lines.append((f"{counts['replace']:,} replaced", backfill.REASON_HELP["replace"], ""))
            for label, n in reasons:
                name = "phrase" if label == "phrases" and n == 1 else label
                lines.append((f"{n:,} {name}", backfill.REASON_HELP.get(label, ""), ""))
        return "", lines if any(header[0].isdigit() for header, _line, _ex in lines) else []

    # ------------------------------------------------------------------ actions
    def refresh_connection(self):
        if self.busy:
            return
        self.conn_var.set("● checking…")
        self.conn_lbl.config(foreground=MUTED)
        self._start(self._probe_worker)

    def _probe_worker(self):
        from app import anki_connect
        url = backfill._url(self._settings_snapshot)
        report = anki_connect.probe(url, required=backfill.REQUIRED_ACTIONS)
        decks = []
        if report.get("ok"):
            try:
                decks = sorted(anki_connect.deck_names(url))
            except Exception as e:
                self.q.put(("__MESSAGE__", f"Could not list your decks: {e}", "warning"))
        self.q.put(("__CONN__", report, decks))

    def _session_for(self, settings):
        """The window's `Session`, made on first use and again when the language changes. Worker
        thread only: loading it reads the databases and the known words."""
        language = settings.get("target_language") or "ja"
        if self._session is None or self._session_language != language:
            if self._session is not None:
                self._session.close()
            self._session = backfill.Session(settings)
            self._session_language = language
        return self._session

    def on_preview(self):
        """The button: Preview — or "Build & preview" while there is nothing to fill from yet."""
        if self.busy:
            return
        self._clear_messages()
        if self._needs_build():
            self._clear_preview()
            self.summary_var.set("Building… about a minute, once.")
            self._start(self._build_worker)
            return
        self._preview_now()

    def _want_preview(self):
        """After a choice: a new preview now, or when the job running ends — the latest choices win."""
        if not self._connected or self._needs_build():
            return
        if self.busy:
            self._preview_wanted = True
        else:
            self._preview_now()

    def _preview_now(self):
        """Start a preview of the choices on screen. The key goes with it: a result that comes back
        after a choice changed describes other cards, and is dropped (`_show_preview`)."""
        self._preview_wanted = False
        self._clear_preview()
        settings, key = self._settings(), self._key()
        self.summary_var.set("Reading your cards…")
        self._start(lambda: self._preview_worker(settings, key))

    def _preview_worker(self, settings, key):
        from app.anki_connect import AnkiError
        try:
            # The 例文 pass over the library takes seconds: its progress shows on the summary line.
            result = backfill.preview(settings, self._session_for(settings), status=self._status)
        except AnkiError as e:
            self.q.put(("__MESSAGE__", str(e), "problem"))
            self.q.put(("__SUMMARY__", ""))
            return
        self.q.put(("__PREVIEW__", result, key))

    def on_fill(self):
        if self.busy or self._preview_key != self._key() or not (self._preview or {}).get("edits"):
            return
        count = len(self._preview["edits"])
        # Through the module, not a name bound at import: the tests' guard patches `gui.ask`.
        if not junban_gui.ask(self, f"Fill {count:,} note{'' if count == 1 else 's'} in Anki?",
                              details=["What was in each field is saved first; Restore puts it back."],
                              title=TITLE, yes="Fill"):
            return
        settings, planned = self._settings(), self._preview
        # Another Anki writer (順, a second Surasura) is waited for on the worker; the status line says
        # who, and closing the window stops the wait (E1.4 §W).
        self._start(lambda: self.q.put(("__REPORT__", backfill.run(
            settings, self._session_for(settings), planned=planned, progress=self._progress,
            wait=None, cancel=self._stop, on_wait=self._waiting))))

    def on_restore(self):
        if self.busy:
            return
        # One of Connect's fills that never finished comes first (P1.4, §7.2): it refuses every fill until it is put
        # back, so Restore names it — and offers it even when this window has filled nothing itself.
        run = undo.unfinished(self._lang_code(), "backfill")
        if run is not None:
            if not junban_gui.ask(self, "An automatic fill didn't finish. Put back what it wrote?",
                                  details=[undo.describe_run(self._lang_code(), run)], title=TITLE, yes="Restore"):
                return
            settings = self._settings()
            self._start(lambda: self.q.put(("__REPORT__", backfill.restore(
                settings, wait=None, cancel=self._stop, on_wait=self._waiting, run=run))))
            return
        # The snapshot the question describes, read before it is asked: a restore that waited refuses once a fill
        # has replaced it (E1.4 §W).
        confirmed = (undo.load(self._lang_code(), kind="backfill") or {}).get("written_at")
        line = backfill.describe(self._lang_code())
        if not line:
            self._write("Nothing has been filled yet.", "warning")
            return
        if not junban_gui.ask(self, "Put back what was there before Backfill wrote?", details=[line],
                              title=TITLE, yes="Restore"):
            return
        settings = self._settings()
        self._start(lambda: self.q.put(("__REPORT__", backfill.restore(
            settings, wait=None, cancel=self._stop, on_wait=self._waiting, confirmed=confirmed))))

    def _waiting(self, holder):
        """The Anki-write lock is held elsewhere: said once, from the worker, through the queue."""
        from app import anki_connect
        self.q.put(("__MESSAGE__", anki_connect.waiting_line(holder), "warning"))

    def on_rebuild(self):
        """"Rebuild from my library": what opening the window does by itself once the library has grown a lot, now —
        in the background, so Preview and Fill keep working from the set in use meanwhile."""
        if backfill.building():
            return
        reinforce = self._saved_settings().get("reinforce_segmentation") is True
        if backfill.rebuild_in_background(self._lang_code(), reinforce):
            self._watch_build()
        else:
            self._write("Could not start the build.", "problem")

    def _rebuild_if_grown(self):
        """Opening the window: the library's パターン set is built again in the background when the library has grown
        by a quarter since it was built (`backfill.rebuild_in_background`) — nothing waits for it, and nothing is said
        unless it fails. Only while パターン is ticked and offered: 例文 reads the library itself."""
        if self.fill_on["patterns"].get() and self._available.get("patterns"):
            reinforce = self._saved_settings().get("reinforce_segmentation") is True
            backfill.rebuild_in_background(self._lang_code(), reinforce, when_grown=True)
            self._watch_build()

    def on_copy_style(self):
        self.clipboard_clear()
        self.clipboard_append(CARD_STYLE)
        self._write("Copied. In Anki: Tools › Manage Note Types › Cards › Styling — paste at the end.",
                    "good")

    def on_fields(self, fill):
        """Where one fill goes, per note type — its own small window, one at a time."""
        dialog = self._fields_dialog
        if dialog is not None and dialog.winfo_exists():
            if dialog.fill_key == fill.key:
                dialog.lift()
                dialog.focus_force()
                return
            dialog.destroy()
        if not self._models:
            return
        self._fields_dialog = FieldsDialog(self, fill, self._models,
                                           lambda model, value: self._on_mapping(fill, model, value),
                                           self._on_note_language)

    def on_get_data(self):
        """Where パターン data comes from — its own small window, one at a time."""
        dialog = self._data_dialog
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            dialog.focus_force()
            return
        self._data_dialog = DataDialog(self, self.on_download, self.on_import, self._lang_code())

    def on_download(self):
        from modules.junban import patterns_package
        self._downloaded_mb = -1
        language = self._lang_code()
        self._install(lambda: patterns_package.get_shared(progress=self._download_progress, language=language),
                      "Downloading…")

    def on_import(self):
        path = filedialog.askopenfilename(parent=self, title="Import パターン data",
                                          filetypes=[("Surasura パターン package", "*.zip")])
        if path:
            from modules.junban import patterns_package
            self._install(lambda: patterns_package.install(path, progress=self._progress), "Importing…")

    def _install(self, get, line):
        """A download or an import, on the worker. The session goes first — Windows will not replace a
        database that is open — and a fresh preview follows (`__INSTALLED__`)."""
        if self.busy:
            return
        if self._data_dialog is not None and self._data_dialog.winfo_exists():
            self._data_dialog.destroy()
        if self._session is not None:
            self._session.close()
            self._session = None
        self._clear_preview()
        self._clear_messages()
        self.summary_var.set(line)
        self._start(lambda: self._install_worker(get))

    def _install_worker(self, get):
        from modules.junban.patterns_package import PackageError
        try:
            names = get()
        except PackageError as e:
            self.q.put(("__MESSAGE__", str(e), "problem"))
            self.q.put(("__SUMMARY__", ""))
            return
        self.q.put(("__INSTALLED__", names))

    def _download_progress(self, done, total):
        """Bytes in, shown in whole MB — one line per MB, not per chunk."""
        mb = int(done / 1e6)
        if mb != self._downloaded_mb:
            self._downloaded_mb = mb
            self._status(f"Downloading… {mb} / {max(1, round(total / 1e6))} MB" if total else "Downloading…")

    def _on_mapping(self, fill, model, value):
        """One note type's field for one fill: saved, shown on the fill's button, previewed."""
        choice = backfill.SKIP if value == SKIP_LABEL else value
        self._fields.setdefault(fill.key, {})[model] = choice
        info = self._models.get(model)
        if info is not None:
            info["mapped"] = dict(info.get("mapped") or {}, **{fill.key: choice or None})
        self._show_targets()
        self._on_choice()

    def _on_note_language(self, model, label):
        """One note type's language, as the Fields window sets it: saved (a fresh dict), and previewed —
        "Language?" unsets it, and the kana rule decides again (`backfill.note_language`)."""
        code = next((code for code, name in LANGUAGE_LABELS.items() if name == label), None)
        languages = dict(self._note_languages)
        if code:
            languages[model] = code
        else:
            languages.pop(model, None)
        self._note_languages = languages
        info = self._models.get(model)
        if info is not None:
            info["language"] = code
        self._on_choice()

    def _build_worker(self):
        """Build the library's パターン data for the language on screen (a subprocess: CLAUDE.md §6)."""
        settings = self._settings_snapshot
        try:
            process = backfill.start_rebuild(settings.get("target_language") or "ja",
                                             settings.get("reinforce_segmentation") is True)
        except OSError as e:
            self.q.put(("__MESSAGE__", f"Could not start the build: {e}", "problem"))
            return
        if process is None:             # never two builds at once
            self.q.put(("__MESSAGE__", "Your library's パターン is being built in the background. Preview again "
                                       "when it's done.", "warning"))
            self.q.put(("__SUMMARY__", ""))
            return
        last = ""
        for line in process.stdout:
            line = line.strip()
            found = re.match(r"PROGRESS (\d+)/(\d+)", line)
            if found:
                self.q.put(("__PROGRESS__", int(found.group(1)), int(found.group(2))))
            elif line:
                last = line
        self.q.put(("__BUILT__", process.wait() == 0, last))

    def _progress(self, done, total):
        self.q.put(("__PROGRESS__", done, total))

    def _status(self, line):
        """A slow step's line ("Reading your library: 900 / 1,987 files…") on the summary line, and its
        numbers on the bar."""
        self.q.put(("__SUMMARY__", line))
        found = re.search(r"([\d,]+) / ([\d,]+)", line or "")
        if found:
            self._progress(int(found.group(1).replace(",", "")), int(found.group(2).replace(",", "")))

    def _start(self, worker):
        self._settings_snapshot = self._settings()
        self._set_busy(True)
        threading.Thread(target=self._guarded(worker), daemon=True).start()

    def _guarded(self, worker):
        def run():
            try:
                worker()
            except Exception as e:
                self.q.put(("__MESSAGE__", f"Unexpected error: {e}", "problem"))
            finally:
                self.q.put(("__DONE__",))
        return run

    # --------------------------------------------------------------- rendering
    def _show_preview(self, result, key):
        """Render one preview — unless the choices changed while it ran: then it describes other
        cards, and the preview of the new ones follows (`_want_preview`)."""
        if key != self._key():
            return
        self._models = (result.get("scope") or {}).get("models") or {}
        self._show_targets()
        self._clear_rows()
        rows = sorted(result.get("rows") or [],
                      key=lambda r: (r[3] not in ("fill", "replace"), r[3], r[1]))
        labels = {fill.key: fill.label for fill in backfill.FILLS}
        for _note_id, word, _field, action, value, fill_key in rows[:MAX_PREVIEW_ROWS]:
            writing = action in ("fill", "replace")
            self.tree.insert("", "end", values=(word, labels.get(fill_key, fill_key), backfill.reason(action),
                                                _lines_of(value) if writing else ""),
                             tags=() if writing else ("skip",))
        if rows:
            self.summary_var.set(backfill.summary(result))
        elif not any(var.get() for var in self.fill_on.values()):
            self.summary_var.set("Tick what to fill.")
        elif self._models:
            self.summary_var.set("Choose a field for these cards.")
        else:
            self.summary_var.set("No cards here.")
        self._preview, self._preview_key = result, key
        self._show_details(bool(self._details()[1]))
        self._sync_buttons()

    def _show_details(self, visible):
        try:
            packed = self.details.winfo_manager() == "pack"
            if visible and not packed:
                self.details.pack(side=tk.LEFT, padx=(8, 0))
            elif not visible and packed:
                self.details.pack_forget()
        except tk.TclError:
            pass

    def _show_report(self, report):
        for line in report.get("problems") or []:
            self._write(line, "problem")
        self._write(report.get("message") or "", "good" if report.get("ok") else "problem")
        # What was on screen described the notes before this; a new look is one click away.
        self._clear_preview()
        self._sync_buttons()

    def _clear_preview(self):
        self._preview, self._preview_key = None, None
        self._clear_rows()
        self.summary_var.set("")
        self._show_details(False)

    def _clear_rows(self):
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)

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
        """The message pane exists only while it has something to say (as in 順)."""
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
        self._drain_once()
        if self.winfo_exists() and not self._closing:
            self.after(100, self._drain)

    def _drain_once(self):
        try:
            while True:
                item = self.q.get_nowait()
                tag = item[0] if isinstance(item, tuple) and item else None
                if tag == "__CONN__":
                    self._set_connection(item[1], item[2])
                elif tag == "__PREVIEW__":
                    self._show_preview(item[1], item[2])
                elif tag == "__REPORT__":
                    self._show_report(item[1])
                elif tag == "__PROGRESS__":
                    if str(self.progress["mode"]) != "determinate":
                        self.progress.stop()
                        self.progress.config(mode="determinate")
                    self.progress["maximum"] = max(1, item[2])
                    self.progress["value"] = item[1]
                elif tag == "__MESSAGE__":
                    self._write(item[1], item[2] if len(item) > 2 else None)
                elif tag == "__SUMMARY__":
                    self.summary_var.set(item[1])
                elif tag == "__BUILT__":
                    self._on_built(item[1], item[2])
                elif tag == "__INSTALLED__":
                    self._write(f"Installed: {', '.join(item[1])}.", "good")
                    self.summary_var.set("")
                    self._preview_wanted = True
                elif tag == "__DONE__":
                    self._set_busy(False)
                    if self._preview_wanted and self._connected and not self._needs_build():
                        self._preview_now()
        except queue.Empty:
            pass
        self._watch_build()

    def _watch_build(self):
        """A background build of the library's パターン — this window's or the automatic step's: a quiet line while
        it runs; when it ends, the session lets the old set go at the first idle moment, so the new one goes in and
        the next preview reads it (Windows will not replace a database that is open); a failure is said once."""
        state = backfill.background()
        if state:
            language, done, total = state
            line = "Updating your library's パターン in the background…"
            line = f"{line} {done:,} / {total:,} files" if total else line
            if self.build_var.get() != line:
                self.build_var.set(line)
            if self._building is None:
                self._building = language
                self._sync_buttons()
        elif self._building is not None:
            self._swap, self._building = self._building, None
            self.build_var.set("")
            self._sync_buttons()
        if self._swap is not None and not self.busy:
            if os.path.exists(backfill.staged_path(self._swap)):
                if self._session is not None:
                    self._session.close()
                    self._session = None
                backfill.promote(self._swap)
            self._swap = None
            self._sync_buttons()
        note = backfill.failed_note()
        if note:
            self._write(note, "problem")

    def _on_built(self, ok, last):
        """The build ended. The session goes (its databases were the old ones); on success the preview
        it was for follows, when the job ends (`__DONE__`)."""
        if self._session is not None:
            self._session.close()
            self._session = None
        self.progress["value"] = 0
        self.summary_var.set("")
        if not ok:
            self._write(last or "The build failed.", "problem")
        elif self._needs_build():
            self._write("Built, but your library has nothing to fill from yet.", "warning")
        else:
            self._preview_wanted = True
        self._sync_buttons()

# SPDX-License-Identifier: GPL-3.0-or-later
"""順番 (junban) — optional, self-contained Surasura module: Anki's new-card queue, in Surasura's order.

The user mines indiscriminately with anki_miner and accumulates a large backlog of **new** cards.
Surasura already computes the optimal learn order for their library; `junban` makes the backlog
follow it. One button, in place, through AnkiConnect — it feeds anki_miner nothing and overrides
none of its settings. *Surasura decides the order; Anki keeps the cards.*

Scope discipline
----------------
This module never touches the analysis engine. It CONSUMES existing artifacts —
`results/priority_learning_list.csv` (read by column NAME, never by position) and the note fields
Anki already holds — and adds no engine hook, no report column and no new pip dependency:
AnkiConnect is driven with stdlib `urllib.request`, loopback only. Delete this folder and the app,
the report and the whole core test suite are unchanged; that is the Prime Invariant in
`docs/agent instructions/Adding_a_new_module.md`.

It creates nothing and deletes nothing, and it writes `due` on cards that are `type == 0 and
queue == 0` — never a review card, never a suspended one — after a full `{cardId: due}` snapshot,
because AnkiConnect's `setSpecificValueOfCard` hardcodes `skip_undo_entry=True` and ours is the only
undo there is.

It will also, **only when asked**, touch up the notes of the cards it moved: a tag and the word's
frequency number (WP-L). That is note *content*, a different class of
risk from a queue position — a wrong `due` comes back out of the snapshot, a clobbered field does
not exist anywhere else — so every one of those is off until switched on, saves the prior value
before writing, and never writes a field the user did not name. See `touchup.py`.

What is here
------------
`ankiconnect.py` (stdlib transport), `match.py` (the rank index built from the priority list),
`plan.py` (the pure planner that decides every new position), `undo.py` (the snapshot and the
restore), `reposition.py` (preflight, dry run, run, restore), `unlisted.py` (what happens to the
cards not on the list), `pairs.py` (the user's answers to "Same word as one on your list?") and
`auto.py` (the automatic reorder, a test option). The core dashboard
reaches it through `open_junban` — a 順 button and an "Enable Anki reordering" toggle that both
disappear when this folder does — and `auto.run_quietly`, lazily and inside try/except.

All heavy imports are deferred inside the functions, so `settings_manager` can import this package
just to read SETTINGS_DEFAULTS without paying for tkinter, pandas or a tokenizer on every launch.
"""

# Contributed to the app's settings only when this module is importable. The core defaults (and the
# shipped settings.json) stay free of these keys, so a build without the module never sees or
# persists them. Flat, top-level, and all-off: nothing here reaches the collection on its own.
SETTINGS_DEFAULTS = {
    # ON by default, unlike most optional modules. The toggle also gates the BUILD, so the module
    # is only present at all in a build whose developer opted in — "on" therefore means "on for
    # someone who already asked for it", which is the same reasoning `enable_youtube_transcripts`
    # uses. Reordering a backlog is a standard part of the workflow, not a power-user extra.
    "enable_junban": True,             # shows the 順 button; gates the build
    "junban_scope": "deck",            # "deck" (one nominated deck) | "all" (every deck with new cards)
    "junban_deck": "",                 # the nominated deck when scope is "deck"
    # Per-note-type word-field override, e.g. {"Migaku Japanese": "Target Word"} — field index 0 is
    # an anki_miner invariant, not an Anki one, and Migaku's type breaks it. Never mutate this dict
    # in place: `settings_manager` merges module defaults shallowly, so the loaded settings alias
    # this very object. Assign a fresh dict instead.
    "junban_word_fields": {},
    "junban_chunk_size": 150,          # sub-actions per `multi` call
    # Where the cards the list does not have go (Junban_Backlog_Spec §11, the panel's "List first"):
    # "list_first" — the list's words first, with the phrases met as often as the list's words among
    # them; then every rarer card by its own sentence, known words last. "journey" — a word the list cut
    # off is placed where the journey meets it, among the list's. "back" — v1: all of them in their
    # existing order behind the list's. Replaces v1's `junban_unmatched`, whose old default every
    # settings.json already holds.
    "junban_unlisted": "list_first",
    # The panel's "Phrases": a phrase or compound card (気がつく) the library meets as often as the
    # list's words is placed as they are. Off, every phrase card goes by its sentence with the rest.
    "junban_phrases": True,
    # The panel's "i+1 first" (Junban_Backlog_Spec §17): a card placed with the list whose OWN
    # sentence holds a list word it comes before gets that word's card brought right before it — when
    # that card is i+1 there — or else waits with the cards of more new words. A name counts like any
    # other word, unless Settings' Ignore names makes the library's names ignored words.
    "junban_ready_first": False,

    # --- WP-M: which of Surasura's two orders to follow ---------------------------------------- #
    # "content" is the DEFAULT, by the user's decision. It reads `progressive_learning_list.csv`,
    # whose row order is file order (the manifest's study order) then within-file score — the order
    # the words will actually be met in. "priority" reads `priority_learning_list.csv` instead, pure
    # leverage-first. They are genuinely different: on the live library the priority list's rank-0
    # word is not encountered until file #148, while content order starts with file #1's words
    # (priority ranks 350, 897, 981).
    "junban_order": "content",         # "content" (as I'll meet it) | "priority" (by leverage)

    # --- WP-N: the report's own markers ✦ star / ⚖ lopsided / 📖 reading ------------------------ #
    # Also add `Surasura::☆` / `::⚖` / `::文` beside the plain tag, hierarchical under the
    # `junban_tag` parent so everything junban did is one collapsible branch in Anki's browser.
    # Glyphs, by the user's choice (see touchup.MARKER_TAG_LEAF).
    "junban_tag_markers": False,
    # Empty means everything; otherwise a subset of ["star", "lopsided", "reading"], and only words
    # carrying one of them are matched at all. A word that fails it is simply UNMATCHED, which
    # already means "keeps its existing relative order, at the back" — no new ordering concept, and
    # nothing is stranded. Like `junban_word_fields` this is a container and therefore ALIASES the
    # object in these defaults once merged into loaded settings: copy it, never mutate it in place.
    "junban_only_markers": [],

    # --- WP-L: optional card touch-ups ------------------------------------------------------- #
    # These are the only settings in this module that write NOTE CONTENT rather than a queue
    # position, and that is a different class of risk: a wrong `due` comes straight back out of the
    # snapshot, while a clobbered field has destroyed something the user wrote and the snapshot is
    # the only copy. So the two that overwrite are off, and the one that is on adds a tag — purely
    # additive, removed again by the same undo, and never applied to a card that did not move.
    "junban_tag": "Surasura",          # tag added to notes whose card moved; "" disables
    "junban_write_frequency": False,   # append <li>Surasura: N</li> to the frequency field
    "junban_frequency_field": "Frequency",   # where — Lapis/Kiku hold a <ul> list here
    # Separate from the append above **on purpose**: `FreqSort` is one sort key the user's browser
    # ordering depends on, so overwriting it can never ride along with a harmless append.
    "junban_write_freqsort": False,
    # (The extra example sentence moved to Anki Backfill's 例文, 2026-09-24 — Patterns_Spec §17.6.)

    # --- the cards NOT on the list (Junban_Backlog_Spec §13, `unlisted.py`) ------------------ #
    # Any combination; none ticked is "No action", the default. Tag = `Surasura::later`; flag =
    # purple; suspend also tags, so a suspended card can always be found. All undone by Restore.
    # There is no delete, by design.
    "junban_later_tag": False,
    "junban_later_flag": False,
    "junban_later_suspend": False,
    # The show each card the list places is for, as a label (`Surasura::for::<show>`, `show_tags.py`; laptop round 8
    # #50, LF4-3): on, written where it changed by every re-order that writes more than positions. Not in Settings:
    # positions only (`auto._POSITIONS_ONLY`) turns it off for that run.
    "junban_show_tags": True,

    # --- the automatic reorder (`auto.py`) — a TEST option, switched to true by hand -------- #
    # After a Generate and when Surasura comes back into focus (at most every 5 minutes), for the
    # one deck saved in the panel, never while reviewing, never without a snapshot. Off, the
    # second key keeps it to positions; on, it applies everything the panel has saved.
    "junban_auto_reorder": False,
    "junban_auto_actions": False,

    # --- the fast re-plan's preview (E1.1 04 §1; `app/replan_preview.py`) ---------------------- #
    # 順's option "Re-order Anki as I move content (preview)". On: a move in the Content Manager re-orders
    # Anki's new cards about a second later, tomorrow's first; the automatic reorder runs after every
    # Generate; every Junban writer numbers spaced (`spaced.py`); a Generate also writes the plan file (on the
    # 3.0 line every Generate does, E1.2-1). Off (the default): 2.5, byte for byte. Saved only as the user set it
    # (3.0's dashboard saves only its own keys: the settings service, W1.3).
    "junban_replan_preview": False,
    "junban_replan_language": "",          # the language it was switched on in (its deck's); "" reads as Japanese
    "junban_replan_deck": "",              # the deck it was switched on for: 順's deck changed since -> it stands aside
    # --- your own cards, with Connect's preview on (P1.4-1, Sonic 2026-10-06; `connect.py`) --- #
    # Cards you mine yourself go ahead of Connect's, in the order you mined them, and are never suspended: a new card
    # without Connect's tag mined after Connect's first card, and any card carrying the tag you name here
    # ("immersion"), whenever mined. "Order all" puts every new card, yours too, in the list's order.
    "junban_own_tag": "",
    "junban_order_all": False,

    # --- Anki Backfill (`backfill.py`, `backfill_gui.py`; Patterns_Spec §17) --------------- #
    # Fills note fields — today パターン — from what Surasura knows. Its own window, its own snapshot.
    "junban_backfill_deck": "",            # "" = every deck
    "junban_backfill_cards": "all",        # "all" (but new cards whose word you know) | "new"
    "junban_backfill_replace": False,      # overwrite a filled field (saved first; Restore)
    "junban_backfill_fills": ["patterns"],     # the fills ticked — a container: copy, never mutate
    # {fill: {note type: field}}; a note type missing here maps by name (Patterns / パターン), and
    # "" means "don't fill it". A container again: assign a fresh dict (spec §13 #12).
    "junban_backfill_fields": {},
    # {note type: "ja" | "zh"}, set in the Fields window. Unset, a note type with kana in its notes is
    # Japanese and any other is filled by NO language until the user says which (Patterns_Chinese_Spec
    # D7, S3 — `backfill.note_language`). A container again: assign a fresh dict.
    "junban_backfill_note_languages": {},
    # A TEST option like the automatic reorder: after it, fill the NEW cards' EMPTY fields — never a
    # studied card, never a filled field, whatever the window is set to (`backfill.run_auto`).
    "junban_auto_backfill": False,
}

# AnkiConnect's optional `apiKey` is deliberately **not** a setting and must never become one:
# `settings.json` is read by `packaging/Surasura.spec` at build time and ships inside the release, so
# a credential here would be published. If it is ever supported it belongs in
# `get_persistent_user_data_path()`, the way `modules/koe/keystore.py` holds its own.

# Settings that exist in the dict above but that no shipping code reads YET. Empty, and it should
# stay that way: `reposition.py` honours scope, deck, endpoint, chunk size, the note-type field
# overrides, the unmatched placement, WP-M's `junban_order` and WP-N's `junban_only_markers`,
# `touchup.py` honours all six of WP-L's keys plus `junban_tag_markers`, and
# `app/main.py` owns `enable_junban`. The contract test asserts this set equals the settings nothing
# reads, so a newly added setting has to be either honoured or deliberately declared here. A switch
# that silently does nothing is worse than a missing one; settings.json claims otherwise, so the
# user believes it works.
NOT_YET_IMPLEMENTED = frozenset()


def open_junban(host):
    """Open (or focus) the Junban panel. `host` is the MasterDashboardApp (or anything with `.root`).

    Thin and lazy by contract: the core only ever needs this entry point, and every import that
    costs anything happens below, after we know the user actually asked for the window. It never
    raises past a messagebox — a failure here must not take the dashboard down.
    """
    from tkinter import messagebox
    try:
        from modules.junban.gui import JunbanGui
        parent = getattr(host, "root", host)
        win = getattr(host, "junban_window", None)
        if win is None or not win.winfo_exists():
            host.junban_window = JunbanGui(parent, app=host)
        else:
            win.lift()
    except Exception as e:
        # Everything, ImportError included: the panel exists now, so a failed import from inside it
        # is a real error (a missing `app.ui_theme`, a broken install) and must read as one rather
        # than as "not finished yet".
        print(f"Error launching Junban: {e}")
        messagebox.showerror("Error", f"Could not launch Junban:\n{e}")


def open_junban_qt(shell):
    """The 順 window on the 3.0 line (W3.4 row 6): Qt only now, when it opens (the module SOP's lazy import). -> the
    window (the shell's door says a failure in its bar)."""
    from modules.junban import qt_junban
    return qt_junban.open(shell)


def open_put_back_qt(shell):
    """"Put Anki back…" on the 3.0 line, Settings' door (W3.4 row 6). -> its window, or None when refused (順 busy)."""
    from modules.junban import qt_put_back
    return qt_put_back.open(shell)


def open_backfill(host):
    """Open the Anki Backfill window, or bring it to the front — ONE window, whichever door the user
    came through (the Anki window, via the dashboard, or 順). `host` keeps the window: the dashboard
    when there is one, else the 順 window. Never raises past a messagebox."""
    from tkinter import messagebox
    try:
        from modules.junban.backfill_gui import BackfillGui
        win = getattr(host, "backfill_window", None)
        if win is None or not win.winfo_exists():
            parent = getattr(host, "root", host)
            host.backfill_window = BackfillGui(parent, app=host if hasattr(host, "root") else None)
        else:
            win.deiconify()
            win.lift()
            win.focus_force()
    except Exception as e:
        print(f"Error launching Anki Backfill: {e}")
        messagebox.showerror("Error", f"Could not open Anki Backfill:\n{e}")


def open_backfill_qt(shell):
    """The 3.0 line's Anki Backfill window (W3.4 row 5, PyQt6): opened, or raised when open — ONE per main window,
    whichever door (the Settings tab's list of doors, the Anki window's "Backfill cards…", 順's "Backfill…"). `shell`
    is the main window. Lazy by contract: Qt is imported only here, when the user asked for the window; a failure is
    the caller's to show (the doors put it in the bottom bar, never a box)."""
    from modules.junban import qt_backfill
    return qt_backfill.open_window(shell)

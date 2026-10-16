"""Connect's switch, its work (W3.3 P5; moved from `app/main.py`, P3.1 row 3.1.1 / P3.2 row 3.2.4): no Qt, no Tk.

Every function runs on a worker and imports what it needs when called, as the Tk window's code did. The questions — the
put-back ask, "turn it off anyway?" — stay with the caller: a window asks, this module never does.

- `turn_on(languages, log)`  — each language's watermark, then (only once every one succeeded) `connect_enabled` saved
                               alone, then surasura.json refreshed -> (ok, saved, why); the caller runs `backfill` next
- `backfill(languages, saved, log)` — hato's pairings back-filled for each language Surasura is set up for
- `shelved(languages)`       — the cards on Connect's shelf Junban can put back
- `put_back(shelved, log, waiting)` — each restore point put back -> the reasons of those not put back
- `turn_off(was_on, log)`    — `connect_enabled` saved off, surasura.json refreshed, the readers dropped -> (ok, saved, why)
"""

import os

CONNECT_LANGUAGES = ("ja", "zh")
LANGUAGE_NAMES = {"ja": "Japanese", "zh": "Chinese"}

ON = "Connect is on: what you place in your top 20 from now on gets cards."
NOT_ON = "Connect wasn't switched on: {}. Nothing changed; try again."
NOT_SAVED = "the switch wasn't saved: {}"
BUSY = "{}: the library is busy; try again in a moment"
OFF = "Connect is off."
NOT_OFF = "Connect wasn't switched off: the switch wasn't saved: {}. It stays on; try again."
ASKING_HATO = "Asking hato for its pairings…"
NOT_READ = ("hato's pairings ({}) weren't read: {}. Connect stays on; ask again from its window when Needs you lists "
            "the files.")
PUT_BACK_WAITING = "Waiting for Anki: another program (Anki Miner?) is writing to it. Your shelved cards go back " \
                   "once it's done…"


def turn_on(languages=CONNECT_LANGUAGES, log=print):
    """Each language's watermark first (✅ G1.1-2: nothing placed while it was off is ever mined; the list it last
    looked at forgotten), then — only once every language's succeeded — `connect_enabled` saved alone (`save_keys`: a
    file the switch never touched never gains it), then surasura.json refreshed -> (True, the file as saved, None); a
    failure: nothing saved, the reason logged -> (False, None, the reason). Hato's back-fill is the caller's next step,
    on the same worker (`backfill`)."""
    from app import settings_manager
    failed = _watermarks(languages)
    saved = None
    if not failed:
        try:
            saved = settings_manager.save_keys({"connect_enabled": True}, strict=True,
                                               wait=settings_manager.LOCK_WAIT)    # read next: on disk first
        except Exception as e:
            failed = NOT_SAVED.format(e)
    if failed:
        log(NOT_ON.format(failed))
        return False, None, failed
    refresh_tools_entry(saved)          # surasura.json lists `register` now (hato registers its drops)
    log(ON)
    return True, saved, None


def _watermarks(languages):
    """Each language's watermark at its log's end and its last-looked-at list forgotten, each in its own try ->
    None, or the failures named by language."""
    failed = []
    try:
        from app import library_store
        from app.connect import level, library
        from app.connect.ledger import path as ledger_path
        from app.path_utils import get_data_path
    except Exception as e:
        return str(e)
    for lang in languages:
        try:
            store = library.open_store(lang, role="window")
            if store is not None:
                with store:
                    library.switch_on(store)
            elif os.path.exists(library_store.library_db_path(lang, get_data_path(lang))):
                # a library that's there but won't open (busy, damaged, read-only): its watermark isn't set
                failed.append(BUSY.format(LANGUAGE_NAMES.get(lang, lang)))
                continue
            if os.path.exists(ledger_path()):   # no ledger: no list looked at yet (and none made here)
                level.forget(lang)
        except Exception as e:
            failed.append(f"{LANGUAGE_NAMES.get(lang, lang)}: {e}")
    return "; ".join(failed) or None


def backfill(languages, saved, log=print):
    """On the switch-on's worker, after the save (P3.2 row 3.2.4; 09-hato-layer v2 §4): hato's pairings back-filled
    for each language Surasura is set up for (`hato.backfill`: none mined because of it). With hato's entry in the
    shared tools folder (hato.json), `log` says hato is being asked (it may take up to a minute a language), then each
    language's summary; without one (no hato here), nothing of it goes to `log` — Connect's log has why (printed). A
    failure is only said: the switch stays on."""
    try:
        from app.connect import hato
        shown = hato.connected()
    except Exception:
        shown = False
    if shown:
        log(ASKING_HATO)
    for lang in languages:
        name = LANGUAGE_NAMES.get(lang, lang)
        try:
            from app.connect import hato
            from app.path_utils import get_user_files_path
            if not os.path.isdir(get_user_files_path(lang)):
                continue
            line = hato.say(hato.backfill(lang, saved))
        except Exception as e:
            line = NOT_READ.format(name, e)
        if shown:
            log(line)
        else:
            print(line)


def shelved(languages=CONNECT_LANGUAGES):
    """{lang: (cards on the shelf, [its restore points with cards still on it])}, from the status record — only
    where Junban can put them back. Read on a worker; only for a switch that was on (it imports Connect)."""
    try:
        from app.connect import setup, status
        if not setup._present("modules.junban.reposition"):
            return {}
        records = status.read(list(languages))["languages"]
    except Exception as e:
        print(f"Connect's shelf wasn't read: {e}")
        return {}
    out = {}
    for lang, rec in records.items():
        shelf = rec.get("shelf") or {}
        runs = [r["run"] for r in shelf.get("runs") or () if (r.get("back") or 0) < (r.get("cards") or 0)]
        if shelf.get("on_shelf") and runs:
            out[lang] = (shelf["on_shelf"], runs)
    return out


def put_back(shelved, log=print, waiting=None):
    """On a worker: each restore point put back (`undo.act`), waiting for Anki's write lock as the Connect window
    does (`connect_window.wait_for_writer`; `waiting` called when it waits, else `PUT_BACK_WAITING` to `log`) -> the
    reasons of those not put back ([] when every one was)."""
    if waiting is None:
        waiting = lambda: log(PUT_BACK_WAITING)    # noqa: E731
    failed = []
    try:
        from app import settings_manager
        from app.connect import connect_window, undo
        settings = settings_manager.load_settings() or {}
    except Exception as e:
        return [str(e)]
    for lang, (_cards, runs) in shelved.items():
        for run in runs:
            try:
                out = connect_window.wait_for_writer(
                    lambda: undo.act(settings, lang, shelf_run=run, confirm=True), waiting)
                said = (f"Not done: {out['skipped']}." if out.get("skipped") else
                        f"{out.get('back', 0)} shelved {'card' if out.get('back', 0) == 1 else 'cards'} back in your new cards.")
                if out.get("skipped"):
                    failed.append(said)
            except Exception as e:
                said = f"Shelved cards weren't put back: {getattr(e, 'message', None) or e}"
                failed.append(said)
            log(said)
    return failed


def turn_off(was_on=True, log=print, languages=CONNECT_LANGUAGES):
    """The switch saved off (a running Connect stops at its next boundary), then surasura.json refreshed, then the
    readers dropped where the store can (`unregister_reader`, 3.0's; 2.x's store hasn't it: nothing) — only for a
    switch that was on -> (True, the file as saved, None); a failed save: nothing else done, the reason logged ->
    (False, None, the reason). The shelf is the caller's first (`shelved`, its ask, `put_back`)."""
    from app import settings_manager
    try:
        saved = settings_manager.save_keys({"connect_enabled": False}, strict=True,
                                           wait=settings_manager.LOCK_WAIT)
    except Exception as e:
        log(NOT_OFF.format(e))
        return False, None, NOT_SAVED.format(e)
    refresh_tools_entry(saved)          # surasura.json no longer lists `register`
    try:
        from app import library_store
        if was_on and hasattr(library_store.Store, "unregister_reader"):
            from app.connect import library
            for lang in languages:
                store = library.open_store(lang, role="window")
                if store is None:
                    continue
                with store:
                    if library.has_reader(store):
                        store.unregister_reader(library.READER)
    except Exception as e:
        print(f"Connect's readers weren't dropped: {e}")
    log(OFF)
    return True, saved, None


def refresh_tools_entry(settings=None):
    """surasura.json rewritten when a field differs (`tools_entry.refresh`), after the switch's save, on and off
    (`settings`: the file as saved). A failure is only printed to the log."""
    try:
        from app import tools_entry
        tools_entry.refresh(settings)
    except Exception as e:
        print(f"Shared tools file (surasura.json): {e}")

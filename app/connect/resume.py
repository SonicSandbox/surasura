"""Connect turned on again, by any writer (P4.1 row 4.1.9R; the intent keeper's B2 on the RUNBOOK, ✅ G1.1-2): one rule
for `settings_manager.connect_on` going from off to on, whichever of its two keys moved — Connect's own switch
(`connect_enabled`, *Make cards for me*) or D29's automation (`logic.automation`) — and whichever writer moved it
(Connect's switch, the automation row, the wizard's page, *Set up again*: the window Inbox's W-A7).

What happened while Connect was off is never mined: for each language

- the placement log's watermark at its end (`library.switch_on`): nothing placed while off is read;
- the list Connect last looked at forgotten (`level.forget`): the next look records the list as it is, so a level
  raise while off mines nothing;
- the asks watermark (`ledger.ASKS_FROM + lang` in the ledger's meta, the store's `mine_asked` time format): an ask
  made while off (*Mine this*, *Mine it too*) is older than it and never mined.

    turned_on(before, after, languages)   -> None (nothing to do, or done), or the failures named by language
    watermarks(languages)                 -> the same, unconditionally (a writer that knows it is switching on)

Call it on the writer's worker. Before the save where the writer can (a save that then fails leaves only a watermark
moved while off: harmless); after it is W-A7's order, which leaves a moment in which a kick could read the log first.
`before` is the settings as they were (None reads off: the watermarks set again, never too little). Light (02 §5):
the standard library, the store and the ledger.
"""
import os

CONNECT_LANGUAGES = ("ja", "zh")
LANGUAGE_NAMES = {"ja": "Japanese", "zh": "Chinese"}
BUSY = "{}: the library is busy; try again in a moment"


def turned_on(before, after, languages=CONNECT_LANGUAGES):
    """`connect_on(before)` off and `connect_on(after)` on → every language's watermarks (`watermarks`) -> None, or
    the failures named by language. On → on, off → off and on → off do nothing (None)."""
    from app import settings_manager
    if settings_manager.connect_on(before) or not settings_manager.connect_on(after):
        return None
    return watermarks(languages)


def watermarks(languages=CONNECT_LANGUAGES):
    """Each language's placement watermark at its log's end, its last-looked-at list forgotten and its asks watermark
    set now, each language in its own try -> None, or the failures named by language. A library that is there but
    won't open (busy, damaged, read-only) is a failure: its watermark isn't set, and nothing else of that language is
    written. No library yet: only the ledger's two marks (an ask needs a library; the ledger is made if it isn't
    there, so an ask made before Connect ever ran is never mined either)."""
    failed = []
    try:
        from app import library_store
        from app.connect import ledger as book
        from app.connect import level, library
        from app.path_utils import get_data_path
    except Exception as e:
        return str(e)
    for lang in languages:
        name = LANGUAGE_NAMES.get(lang, lang)
        try:
            store = library.open_store(lang, role="window")
            if store is not None:
                with store:
                    library.switch_on(store)
            elif os.path.exists(library_store.library_db_path(lang, get_data_path(lang))):
                failed.append(BUSY.format(name))
                continue
            with book.Ledger() as ledger:
                level.forget(lang, ledger)
                with ledger.transaction():
                    # the store's own time format (`mine_asked` is the store's `_now()`): the two compare as strings
                    ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                                        (book.ASKS_FROM + lang, library_store._now()))
        except Exception as e:
            failed.append(f"{name}: {e}")
    return "; ".join(failed) or None


# SPDX-License-Identifier: GPL-3.0-or-later
"""彩 Irodori — AI sentence audio for cards with none (an optional beta module; README.md is its spec).

The core reaches it only through these names, each import deferred and each call guarded (the app runs the same with
this folder absent):

* `SETTINGS_DEFAULTS` — the beta's switch, off.
* `on(settings)` — the beta switched on AND the voice installed AND the shared writer there: the only time any door
  offers AI audio.
* `make_for_notes(settings, language, note_ids, …)` — one run for these notes (Backfill's button, Connect's *Add
  audio to these cards*): only empty SentenceAudio, one Undo. `dry_run=True` counts.
* `queue_notes(language, note_ids, source)` / `run_queue(settings, language, should_stop)` — Connect's book cards made
  with *Make AI audio (beta)*: queued at the part's fill, made at the end of Connect's run.
* `undo(settings, language, run_id)` — that run put back (through the shared writer).
"""

SETTINGS_DEFAULTS = {
    "enable_irodori": False,            # Settings › App › Beta: AI audio for cards without audio (PROVISIONAL name)
    "irodori_voice": "k2-natural",      # the voice pack (README § Voice packs)
}


def enabled(settings):
    return bool((settings or {}).get("enable_irodori"))


def installed():
    from modules.irodori import runtime
    try:
        return runtime.ready()
    except Exception:
        return False


LANGUAGES = ("ja",)                     # the voice is Japanese: no door offers it in another language


def on(settings, language="ja"):
    """The beta on, its voice installed, the shared writer in the tree, and a Japanese library."""
    if not enabled(settings) or language not in LANGUAGES:
        return False
    from modules.irodori import writer
    return writer.available() and installed()


def make_for_notes(settings, language, note_ids, **kw):
    from modules.irodori import make
    return make.make_for_notes(settings, language, note_ids, **kw)


def find_empty(settings, deck=None):
    from app import anki_connect
    from modules.irodori import make
    return make.find_empty(anki_connect.address(settings or {}), deck)


def undo(settings, language, run_id, **kw):
    from app import anki_connect
    from modules.irodori import make, writer
    got = writer.undo(anki_connect.address(settings or {}), language, run_id)
    if got.get("ok"):
        make.mark_undone(language, run_id)
    return got


def last_run(language, source=None):
    """The newest AI-audio run not undone yet (`make.remembered`): {"run", "cards", "source", "at"} or None."""
    from modules.irodori import make
    return make.last_undoable(language, source)


def queue_notes(language, note_ids, source=None):
    from modules.irodori import queue
    return queue.add(language, note_ids, source)


def run_queue(settings, language, should_stop=None, say=None):
    from modules.irodori import queue
    return queue.run(settings, language, should_stop=should_stop, say=say)

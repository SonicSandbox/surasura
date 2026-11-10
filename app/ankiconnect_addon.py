"""AnkiConnect missing (alpha 8, Mado-A; Sonic's lean, QUESTIONS.md 2026-10-31): the one rule and the one set of words
every place that says AnkiConnect isn't answering shows — setup's Anki step (`app/qt/wizard.py`), Settings › Anki &
mining's *Connection* row (`app/qt/settings_live.py`), *Needs you*'s Anki line (`app/services/needs.py`,
`app/qt/needs.py`; Mado-N) and Connect's setup check (`app/connect/setup.py`).

- the add-on's code (`CODE`), for *Copy code* and for the places that can only say it (`steps_line(code=True)`);
- the three steps: *In Anki: Tools › Add-ons › Get Add-ons… → paste the code → restart Anki*;
- `needs_addon(look)`: whether a look that didn't reach Anki may be AnkiConnect missing (an Anki process seen, or it
  can't tell) — setup, Settings and *Needs you* show the steps then, never for an Anki seen closed. Connect's check
  takes no process look and has no button: it writes the steps, the code in them, under every closed answer;
- `running()`: is an Anki process running (the process list, `open_anki.running`; True / False / None);
- `look(url)`: the full look `needs_addon` reads — AnkiConnect asked once and, when nothing answered, the process list
  (Settings' *Check*, *Needs you*'s read: the two halves taken together, never a stale answer beside a fresh list);
- `answers(url, seen)`: the light look *Check again* runs by itself on (`app/qt/addon_steps.py`) — AnkiConnect asked
  once, a short wait; and the process list too while the last look saw no Anki running (`OPENED`: Anki opened without
  AnkiConnect, news once it has gone `SETTLE` s unanswered — the watch's count) or saw one (`GONE`: Anki closed).

Qt-free; nothing here writes anything.
"""
import os

CODE = "2055492159"                       # AnkiConnect's add-on code on AnkiWeb
EVERY = 3.0                               # s between the light looks while the steps (or *Anki isn't open*) show:
                                          # Connect's own tick (`status.TICKS["connect"]`)
LOOK_TIMEOUT = 1                          # s: the light look's wait (a closed Anki refuses at once)

NO_CONNECT = "Anki is open, but AnkiConnect isn't answering"
UNSURE = "Anki isn't open, or AnkiConnect isn't answering"
STEPS = ("Tools › Add-ons › Get Add-ons…", "paste the code", "restart Anki")
IN_ANKI = "In Anki: "
OPEN_FIRST = "Open Anki. If it's open already: "
COPY = "Copy code"
COPY_TIP = (f"Puts AnkiConnect's code, {CODE}, on the clipboard.\n"
            "• AnkiConnect is the free Anki add-on Surasura talks to Anki through")
COPIED = "Copied"
COPIED_LINE = "AnkiConnect's code is copied: paste it into Anki's Get Add-ons… box, then restart Anki."
COPIED_MS = 2000                          # *Copied* shows this long, then the button's name again
OPENED, GONE = "opened", "gone"           # `answers`' news besides AnkiConnect answering (True)
SETTLE = 10.0                             # s an Anki opened goes on not answering before it counts as AnkiConnect
                                          # missing (Mado-N A8N-1: a starting Anki loads its profile, and AnkiConnect
                                          # with it, first — *Open Anki* never flashes the steps)


def steps_line(code=False, unsure=False):
    """The three steps on one line; `code`: the code written in (a place with no *Copy code*); `unsure`: *Open Anki*
    first (a look that can't tell a closed Anki from AnkiConnect missing)."""
    paste = f"paste the code {CODE}" if code else STEPS[1]
    return (OPEN_FIRST if unsure else IN_ANKI) + " → ".join((STEPS[0], paste, STEPS[2]))


def needs_addon(look):
    """Should the steps show for this look? `look`: a probe's report or the wizard's `anki_look` answer, with its
    `running` (an Anki process seen True, none False, can't tell None; absent: not looked). True when Anki didn't
    answer and an Anki may be open: running True or None."""
    look = look or {}
    if look.get("ok") or look.get("open") or look.get("timed_out") or look.get("version") is not None:
        return False                                     # it answered (or is open and busy): never the add-on
    return "running" in look and look.get("running") is not False


def running():
    """(A worker.) Is an Anki running though AnkiConnect didn't answer? True / False, or None when it can't tell."""
    try:
        from app.connect import open_anki
        return open_anki.running()
    except Exception:
        return None


def look(url, timeout=LOOK_TIMEOUT):
    """(A worker.) The full look -> `anki_connect.probe`'s dict at `url` and, when nothing answered (refused, not
    busy), its `running` (`running()`): what `needs_addon` reads."""
    from app import anki_connect
    report = anki_connect.probe(url, timeout=timeout)
    if not report.get("ok") and report.get("version") is None and not report.get("timed_out"):
        report["running"] = running()
    return report


def answers(url, seen=None):
    """(A worker.) The light look: is there news for the full look? -> True: AnkiConnect answering at `url` (one ask,
    `LOOK_TIMEOUT` s at most; an Anki that answers but keeps Surasura out — a permission prompt — counts: the full look
    says what to do); `OPENED`: `seen` False (the last look saw no Anki running) and an Anki running now (AnkiConnect
    missing — or still loading: the watch waits `SETTLE` s); `GONE`: `seen` True and no Anki running now (closed: the
    steps go); else False. `seen` None: AnkiConnect alone is asked.
    Never asked under `SURASURA_NO_ANKI_SYNC` (the test suites, a developer's run): a window a test leaves open
    never reaches a live Anki by itself."""
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return False
    from app import anki_connect
    report = anki_connect.probe(url, timeout=LOOK_TIMEOUT)
    if report.get("ok") or report.get("version") is not None:
        return True
    if seen is None or report.get("timed_out"):
        return False
    now = running()
    if seen is False and now is True:
        return OPENED
    return GONE if seen is True and now is False else False

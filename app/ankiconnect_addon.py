"""AnkiConnect missing (alpha 8, Mado-A; Sonic's lean, QUESTIONS.md 2026-10-31): the one rule and the one set of words
every place that says AnkiConnect isn't answering shows — setup's Anki step (`app/qt/wizard.py`), Settings › Anki &
mining's *Connection* row (`app/qt/settings_live.py`) and Connect's setup check (`app/connect/setup.py`).

- the add-on's code (`CODE`), for *Copy code* and for the places that can only say it (`steps_line(code=True)`);
- the three steps: *In Anki: Tools › Add-ons › Get Add-ons… → paste the code → restart Anki*;
- `needs_addon(look)`: whether a look that didn't reach Anki may be AnkiConnect missing (an Anki process seen, or it
  can't tell) — the screens show the steps then, never for an Anki seen closed;
- `running()`: is an Anki process running (the process list, `open_anki.running`; True / False / None);
- `answers(url)`: the light look *Check again* runs by itself on (`app/qt/addon_steps.py`) — AnkiConnect asked once,
  a short wait, nothing else read.

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


def answers(url):
    """(A worker.) The light look: does AnkiConnect answer at `url` now? One ask, `LOOK_TIMEOUT` s at most; an Anki
    that answers but keeps Surasura out (a permission prompt) counts as answering — the full look says what to do.
    Never asked under `SURASURA_NO_ANKI_SYNC` (the test suites, a developer's run): a window a test leaves open
    never reaches a live Anki by itself."""
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return False
    from app import anki_connect
    report = anki_connect.probe(url, timeout=LOOK_TIMEOUT)
    return bool(report.get("ok") or report.get("version") is not None)

"""Connect's Anki session (P2.3; ✅ Q4-1, Q4-4, Q4-16; K59, K102, K105; P1.5 02-data-model N11, 06-edges E1–E4, E6):
when Connect asks Anki to sync, and when Anki is opened for you. **Never a rule of its own:** every decision is the
one sync rule's (`app/anki_sync_rule.py`, E1.1 04 §3: S1–S4), which the window and the fast re-plan follow too, through
its one state file per user — so a session never syncs twice, whichever Surasura program starts it.

- **S1, a session's start, eagerly** (Q4-4: "Sync once when a session starts (when Anki opens, or when Surasura starts
  with Anki open)"): `begin` asks for the session's sync before Connect reads what you studied (`known-sync`, the
  "fresh state" of Q4-1) or writes Anki — your phone's reviews come in first, so no position is written over a card
  you studied there, and the day's first re-order sees them. Inside a session nothing re-syncs (Q4-4 replaced the
  per-batch syncs of N31). A session starts when the rule says so: none yet, Anki seen closed since, another
  profile, or an hour without a Surasura write.
- **S2, Anki's close:** Anki's own *sync on close* carries the order up; Surasura can't see Anki close and sends
  nothing. A Surasura program that finds Anki closed records it (`look` → `closed_seen`): the next look starts a
  session, and a pending S3 sync is never sent after it.
- **S3:** `after_write` after Connect's writes (`front_changed`: a write that changed tomorrow's cards starts the
  wait; mining lower down doesn't); `settle` — a headless process waits for its pending sync before it exits.
- **E6, a sync that keeps failing:** each of Connect's sync points that asked AnkiWeb counts in the setup record
  (`sync_failures`, Connect's own: the rule's state stays E3.1's) — a failed sync adds one, any other answer starts
  again; three in a row, and the setup checks' AnkiWeb line is *Needs you* (`setup._ankiweb`). Fewer are a status line,
  retried at the next sync point.
- ***Open Anki for me*** (`connect_open_anki`, off by default): `at_window` is the one caller of `open_anki.start`,
  at the window's start only, never after mining and never from Connect, hato or a command-line verb.

Everything here runs only while Connect's preview is on (`connect_enabled`), and never under `SURASURA_NO_ANKI_SYNC`
(the test suites, a developer's run). Standard library only; no Tk. Every call that talks to Anki runs on a worker.
"""
import os
import time

LOOK_TIMEOUT = 3                # seconds a look waits for Anki (a closed port is refused at once)
BEGIN_WAIT_S = 10.0             # a headless `begin` waits this long for another Surasura writer (the window: none)
SETTLE_MARGIN_S = 120           # `settle` never waits past the rule's delay + this …
SETTLE_MAX_DELAY_S = 10 * 60    # … nor a delay longer than this: a longer one is left to Anki's own sync on close
                                # (S2), or to the re-plan's host when its preview is on
OPENING_EVERY_S = 5             # after Open Anki for me started Anki: a look this often …
OPENING_WAIT_S = 120            # … for up to this long
FAILS_TO_ASK = 3                # 06-edges E6: three sync points in a row whose sync failed → Needs you


def on(settings):
    """Connect's preview on, and Anki not switched off for this run."""
    return bool((settings or {}).get("connect_enabled")) and not os.environ.get("SURASURA_NO_ANKI_SYNC")


def look(url):
    """Is Anki there? `open` · `closed` (nothing answers on its port: recorded for the sync rule, `closed_seen`, so
    the next look starts a session) · `busy` (it didn't answer in time: open, never taken for closed, E3.1 review 3
    R6) · `unusable` (something answered, but not as AnkiConnect should: a permission prompt, a reply of another
    shape, an address that isn't this computer's — never "closed", so it starts no session and opens no Anki). One
    read-only request (`requestPermission`, as `probe` asks first). Never raises."""
    from app import anki_connect
    try:
        answer = anki_connect.invoke("requestPermission", url, timeout=LOOK_TIMEOUT)
    except anki_connect.AnkiError as e:
        if getattr(e, "timed_out", False):
            return "busy"
        if e.kind != "offline":
            return "unusable"
        try:
            from app import anki_sync_rule
            anki_sync_rule.closed_seen()
        except Exception:
            pass
        return "closed"
    except Exception:
        return "unusable"
    if isinstance(answer, dict) and answer.get("permission") not in (None, "granted"):
        return "unusable"
    return "open"


def counted(answer):
    """06-edges E6: one of Connect's sync points and what its sync answered, counted in the setup record
    (`sync_failures`): `failed: …` adds one; `synced`, `not-signed-in` or `full-sync` (AnkiWeb answered: the last two
    are named by the setup checks themselves) starts again; None or `anki-closed` (no sync was asked) counts nothing.
    -> the answer, as it was. Never raises: a count lost costs only a later *Needs you*."""
    if not isinstance(answer, str) or answer == "anki-closed":
        return answer
    try:
        from app.connect import setup
        record = setup.read_record()
        before = record.get("sync_failures") or 0
        before = before if isinstance(before, int) and not isinstance(before, bool) else 0
        if answer.startswith("failed"):
            # with the last sync that worked as the rule knows it then: a newer one breaks the row (`failing`)
            from app import anki_sync_rule
            seen = anki_sync_rule.read_state().get("synced_at") or 0
            setup.write_record(dict(record, sync_failures=before + 1, synced_at_seen=seen))
        elif before:
            setup.write_record(dict(record, sync_failures=0))
    except Exception:
        pass
    return answer


def failing(record=None, state=None):
    """E6: has Connect's sync failed FAILS_TO_ASK sync points in a row? A sync that worked since the last one counted
    — the re-plan's own, say (the rule's `synced_at`, `state`) — breaks the row."""
    if record is None:
        from app.connect import setup
        record = setup.read_record()
    if state is None:
        from app import anki_sync_rule
        state = anki_sync_rule.read_state()
    count = (record or {}).get("sync_failures")
    if not (isinstance(count, int) and not isinstance(count, bool) and count >= FAILS_TO_ASK):
        return False
    try:
        return float((state or {}).get("synced_at") or 0) <= float((record or {}).get("synced_at_seen") or 0)
    except (TypeError, ValueError):
        return True


def begin(url, settings, wait=BEGIN_WAIT_S, cancel=None):
    """S1 now: the session's sync when this starts a session -> what it answered (`synced` · `not-signed-in` ·
    `full-sync` · `failed: …`), or None (Connect off, no session starting, Anki closed or busy, a review in progress —
    the next look asks again — or another Surasura program holding Anki past `wait`: the session stays due, and the
    next look syncs it)."""
    if not on(settings):
        return None
    from app import anki_connect, anki_sync_rule
    if look(url) != "open":
        return None
    return counted(anki_sync_rule.before_write(url, wait=wait, cancel=cancel))


def waiting(url, settings):
    """None when Connect may read and write Anki now; else the one reason, in plain words — the status line's, never
    *Needs you* (06-edges E1–E3): Anki closed, busy, open on another profile than Connect's, or you reviewing. None
    too with Connect's preview off (nothing of Connect's waits) or Anki switched off for the run."""
    if not on(settings):
        return None
    from app import anki_connect
    state = look(url)
    if state == "closed":
        return "Waiting for Anki: it isn't open."
    if state == "busy":
        return "Waiting for Anki: it's busy."
    if state == "unusable":
        return "Waiting for Anki: it doesn't answer as AnkiConnect should (a permission prompt in Anki?)."
    from app.connect import setup
    mine = setup.anki_profile()
    if mine:
        try:
            open_now = anki_connect.invoke("getActiveProfile", url, timeout=5)
        except anki_connect.AnkiError:
            open_now = None
        if isinstance(open_now, str) and open_now and open_now != mine:
            return f'Waiting for Anki\'s profile "{mine}": "{open_now}" is open.'
    if anki_connect.reviewing(url):
        return "Waiting while you review in Anki."
    return None


def after_write(settings, front_changed):
    """S3's clock after a Connect write (whoever wrote counts as the session's last write): `front_changed` when it
    changed tomorrow's cards -> when the pending sync is due (wall time), or None."""
    if not on(settings):
        return None
    from app import anki_sync_rule
    return anki_sync_rule.wrote(bool(front_changed), settings)


def front_changed(report, per_day=None):
    """Did a Junban run numbered as 2.5 numbers (no fast re-plan job: that one tells the rule itself) change
    tomorrow's cards? Its plan's rows (`stats["order"]`: each card's due before and its new position) and the cards
    it wrote: a written card among the first N of the new order, or pushed out of them (`spaced.front_group`, the
    re-plan's own test; N = the deck's *New cards/day*, at least 20)."""
    written = set((report or {}).get("written") or ())
    order = ((report or {}).get("stats") or {}).get("order") or []
    if not written or not order:
        return False
    from modules.junban import spaced
    current = [(row.card_id, row.due) for row in order]
    news = [row.position for row in order]
    front = {card_id for card_id, _new in spaced.front_group(current, news, spaced.front_size(per_day))}
    return bool(written & front)


def per_day(url, deck):
    """The deck's *New cards/day* (Anki's own options, read-only), or None."""
    from app import anki_connect
    try:
        options = anki_connect.invoke("getDeckConfig", url, deck=deck, timeout=10)
    except anki_connect.AnkiError:
        return None
    new = (options or {}).get("new") if isinstance(options, dict) else None
    value = new.get("perDay") if isinstance(new, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def settle(url, settings, cancel=None, sleep=time.sleep, clock=time.time):
    """A headless process's last step (E1.1 04 §3: a pending sync never dies with its process): the pending S3 sync,
    sent when its time comes — a newer write restarts the wait — and never once Anki has closed (its own sync on close
    carried the order). Waits at most the rule's delay + SETTLE_MARGIN_S, and never for a delay over
    SETTLE_MAX_DELAY_S (a process isn't kept alive for hours: Anki's own sync on close carries the order, or the
    re-plan's host sends it while its preview is on). -> what the sync answered, `anki-closed`, or None (none pending, Connect off,
    cancelled, out of time)."""
    if not on(settings):
        return None
    from app import anki_sync_rule
    delay = anki_sync_rule.delay_s(settings) or 0.0
    if delay > SETTLE_MAX_DELAY_S:
        return None
    limit = clock() + delay + SETTLE_MARGIN_S
    while True:
        answer, next_look = anki_sync_rule.sync_if_due(url, settings, wait=max(0.0, limit - clock()), cancel=cancel)
        if next_look is None:
            return counted(answer)
        if (cancel is not None and cancel.is_set()) or clock() >= limit:
            return None
        sleep(max(0.2, min(next_look - clock(), 5.0, limit - clock())))


def at_window(settings, opening=False, say=None, sleep=time.sleep, clock=time.time):
    """The window's look at a session's start (the 2.x dashboard's; 3.0's window calls the same), on a worker: at the
    window's start (`opening`) and when it comes back into focus. With Connect's preview on:

    - Anki closed: recorded (the next look starts a session); at the window's start, with *Open Anki for me* on and no
      Anki running, Anki is started — once, on the profile Connect was set up with — and looked for every
      OPENING_EVERY_S for up to OPENING_WAIT_S (`say` tells the window's bar);
    - Anki open: `begin`, the session's sync when this starts one.

    -> {"anki": open · closed · busy · unusable, "opened": bool, "sync": its answer or None}, or None when Connect is
    off."""
    if not on(settings):
        return None
    from app import anki_connect
    url = anki_connect.address(settings)
    state, opened = look(url), False
    if state == "closed" and opening and settings.get("connect_open_anki"):
        from app.connect import open_anki, setup
        if open_anki.running() is not True and open_anki.start(setup.anki_profile()) is not None:
            opened = True
            if say:
                say("Opening Anki for you (Open Anki for me)…")
            deadline = clock() + OPENING_WAIT_S
            while state != "open" and clock() < deadline:
                sleep(OPENING_EVERY_S)
                state = look(url)
    answer = begin(url, settings, wait=0.0) if state == "open" else None     # the window never waits for a writer
    return {"anki": state, "opened": opened, "sync": answer}

"""Connect's setup checks (P2.3; P1.5 04-onboarding §1, S1–S8; 06-edges E1–E5, E9–E12, E28, W1): every piece Connect
needs, looked at in order, and for each one that's missing the plain sentence that names it and the one thing that
fixes it. Connect has no account to sign in to: what stands in for "signed out" is a piece not set up yet, and the
rule for it is to name it, offer its one action, and do everything else meanwhile.

`checks(settings, language)` -> {"ready", "checks", "anki_profile", "anki_miner"}. Each check is
`{"id", "state", "say", "do", "blocks"}`:

- `state`: `ok` · `waiting` (Connect waits by itself: Anki closed, another profile open, Anki Miner busy — the status
  line's, never *Needs you*) · `needs-you` (only you can fix it) · `not-checked` (it can't be looked at yet: it needs
  a piece above it) · `skipped` (a tool that isn't installed: its step is skipped, named once — E7, S8);
- `say`: one plain sentence; `do`: the one action, or None; `blocks`: whether it stops Connect making cards (a
  missing AnkiWeb login doesn't: the cards are made, your phone gets them once Anki is signed in).
- `ready`: nothing blocks.

The order (04 §1): Anki open with AnkiConnect (S1, E5) · Anki on the profile Connect was set up with (S2, E3) ·
AnkiWeb (E4; Anki's own sync on close carries the order up, S2 of the sync rule) · the first known-words sync (S3,
E28) · Anki Miner installed (S4) · its version (S5, E10, E12) · the Anki Miner profile Connect mines with (S7) · Anki
Miner's own setup (S6, `--api check`) · Junban and Backfill (S8) · *Open Anki for me* finding Anki (when it's on).
Anki Miner is asked `version` first, then `profiles`, then `check` (research/01: a build without `--api` opens its
window, so one its installer says is older than 3.5.0 is never run at all).

**The setup record** (02-data-model N12; what the window's setup page reads, W1.2 gap 10):
`<local data>/connect/setup.json` — the Anki profile Connect was set up with (taken the first time Anki answers),
where Anki Miner was found, its version and features, the profile Connect mines with, and the last checks per
language. Written atomically, only while Connect's preview is on; never `settings.json`, never anything of Anki
Miner's (its profiles and settings are its own: 01-scope, P1.5-10 / 14). From Anki Miner 3.7 every named word is
whitelisted (Z-1), so IS-R3's dedicated profile is optional (Sonic, 2026-10-07: "Optional. Use the profile as you
need."): the check names the profile Connect will mine with, and makes none.

Standard library only; no Tk, Qt or pandas. Anki is asked read-only (`probe`, `getActiveProfile`); nothing here
syncs, writes Anki or starts a program but Anki Miner's `--api` reads.
"""
import datetime
import importlib.util
import json
import os
import threading

RECORD = "setup.json"
RECORD_VERSION = 1
# What Connect itself asks of AnkiConnect (the mine step's tag, the review guard, the profile guard, the sync rule's
# sync, the note type's fields, a batch checked by its tag): a fork on port 8765 missing one is named (E5)
ANKI_ACTIONS = ("guiReviewActive", "getActiveProfile", "findNotes", "notesInfo", "addTags", "modelFieldNames",
                "sync")
# Anki Miner's `check` items (3.7.0 `cli/api/commands.py`): those it can't look at while Anki is closed, and those
# only its YouTube fetch needs (a video-only caller is ready without them: its own `ready` leaves them out)
ANKI_ITEMS = frozenset({"anki", "deck", "note_type", "fields"})
FETCH_ONLY = frozenset({"yt_dlp", "speech_model"})
RELEASES = "https://github.com/0xzerolight/anki_miner/releases"
ANKICONNECT_CODE = "2055492159"     # AnkiConnect's add-on code on AnkiWeb

OK, WAITING, NEEDS_YOU, NOT_CHECKED, SKIPPED = "ok", "waiting", "needs-you", "not-checked", "skipped"


def _check(id_, state, say, do=None, blocks=None):
    if blocks is None:
        blocks = state not in (OK, SKIPPED)
    return {"id": id_, "state": state, "say": say, "do": do, "blocks": bool(blocks)}


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# The record (N12)
# --------------------------------------------------------------------------- #
def record_path():
    from app.connect import ledger
    return os.path.join(ledger.folder(), RECORD)


def read_record():
    """The setup record as written, or {} (none yet, or unreadable). Never raises."""
    try:
        with open(record_path(), "r", encoding="utf-8") as f:
            record = json.load(f)
        return record if isinstance(record, dict) else {}
    except (OSError, ValueError):
        return {}


def write_record(record):
    """Atomically (temp + replace) -> written or not. A failure costs only a check asked again. Never raises."""
    path = record_path()
    temp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(dict(record, version=RECORD_VERSION), f, ensure_ascii=False, indent=1)
        os.replace(temp, path)
        return True
    except OSError:
        try:
            os.remove(temp)
        except OSError:
            pass
        return False


def anki_profile():
    """The Anki profile Connect was set up with, or None (not set up yet)."""
    name = read_record().get("anki_profile")
    return name if isinstance(name, str) and name else None


# --------------------------------------------------------------------------- #
# Anki (S1, S2, E3–E5)
# --------------------------------------------------------------------------- #
def _anki_off():
    return bool(os.environ.get("SURASURA_NO_ANKI_SYNC"))       # the test suites, a developer's run


def _anki(url, open_anki_on):
    """S1, E5 -> (check, Anki answered)."""
    from app import anki_connect
    if _anki_off():
        return _check("anki", NOT_CHECKED, "Anki isn't asked in this run (SURASURA_NO_ANKI_SYNC)."), False
    report = anki_connect.probe(url, required=ANKI_ACTIONS, timeout=3)
    if report.get("ok"):
        return _check("anki", OK, "Anki is open, with AnkiConnect."), True
    if report.get("missing"):         # it answered (`probe` says not ok whenever an action is missing)
        missing = ", ".join(f'"{name}"' for name in report["missing"])
        return _check("anki", NEEDS_YOU,
                      f"The Anki add-on that answers Surasura (AnkiConnect) can't do {missing}, which Connect needs.",
                      f"In Anki: Tools → Add-ons → Get Add-ons…, code {ANKICONNECT_CODE} (AnkiConnect), then restart "
                      "Anki."), True
    if report.get("timed_out"):
        return _check("anki", WAITING, "Anki is open but busy: it didn't answer in time. Connect tries again."), False
    when = ("Surasura opens it when you open Surasura (Open Anki for me)." if open_anki_on
            else "Connect waits until you open it; your cards are made then.")
    return _check("anki", WAITING, f"Anki isn't open (or AnkiConnect isn't installed in it). {when}",
                  "Open Anki"), False


def _anki_profile(url, answered, record, keep, use_open):
    """S2, E3 -> (check, Anki's open profile or None). `keep`: record the first profile seen (Connect's preview on);
    `use_open`: Connect works in the open profile from now on (`--use-anki-profile`). Sets `record["anki_profile"]`
    when it decides one (`checks` writes only what changed, onto the record as it is then)."""
    from app import anki_connect
    if not answered:
        return _check("anki_profile", NOT_CHECKED, "Checked once Anki is open."), None
    try:
        open_now = anki_connect.invoke("getActiveProfile", url, timeout=5)
    except anki_connect.AnkiError:
        open_now = None
    if not isinstance(open_now, str) or not open_now:
        return _check("anki_profile", WAITING, "Anki didn't say which profile is open. Connect asks again."), None
    mine = record.get("anki_profile")
    if (not mine or use_open) and keep:
        record["anki_profile"], record["anki_profile_at"] = open_now, _now()
        mine = open_now
    if not mine or mine == open_now:
        return _check("anki_profile", OK, f'Connect makes your cards in Anki\'s profile "{open_now}".'), open_now
    return _check("anki_profile", WAITING,
                  f'Anki is open on the profile "{open_now}", but Connect was set up with "{mine}". Connect waits '
                  f'until "{mine}" is open, so no cards land in the wrong profile.',
                  f'Switch Anki to "{mine}", or have Connect use "{open_now}" from now on'), open_now


def _ankiweb(record=None):
    """E4: what Surasura's own syncs found (the sync rule's state), and the note on Anki's own sync on close; E6:
    Connect's sync failed three sync points in a row (`anki_session.failing`, counted in the setup record)."""
    note = ("Anki sends Surasura's new order to AnkiWeb when it closes if its Preferences → Syncing → \"Synchronize "
            "automatically on profile open/close\" is on (Surasura can't see that setting).")
    try:
        from app import anki_sync_rule
        state = anki_sync_rule.read_state()
    except Exception:                       # the rule isn't here (an older build): nothing to say yet
        state = {}
    answer = state.get("sync")
    if answer == "not-signed-in":
        return _check("ankiweb", NEEDS_YOU, "Anki isn't signed in to AnkiWeb, so your phone won't get the cards and "
                      "the order Surasura makes until it is.", "In Anki: click Sync and sign in", blocks=False)
    if answer == "full-sync":
        return _check("ankiweb", NEEDS_YOU, "AnkiWeb wants a full sync, which only you can choose.",
                      "In Anki: click Sync and choose", blocks=False)
    from app.connect import anki_session
    if anki_session.failing(record, state):
        return _check("ankiweb", NEEDS_YOU, "Anki couldn't sync with AnkiWeb the last three times Surasura asked, so "
                      "your phone may be missing Surasura's cards and order.",
                      "In Anki: click Sync and see what it says", blocks=False)
    if answer == "failed":
        return _check("ankiweb", OK, "The last sync with AnkiWeb failed; Surasura tries again when the next one is "
                      "due. " + note, blocks=False)
    if state.get("synced_at"):
        at = datetime.datetime.fromtimestamp(float(state["synced_at"])).strftime("%H:%M")
        return _check("ankiweb", OK, f"Anki last synced with AnkiWeb for Surasura at {at}. " + note)
    return _check("ankiweb", OK, "Anki syncs with AnkiWeb when a session starts. " + note)


def _first_known_sync(settings, language):
    """S3, E28: a list made without your known words would make cards you know."""
    from app import anki_sync
    if not list(((settings or {}).get("anki_sync_decks") or {}).get(language) or []):
        return _check("first_known_sync", NEEDS_YOU, "Surasura doesn't know which Anki decks hold the words you "
                      "know yet, so Connect could make cards for words you know.",
                      "Open Surasura's Anki window, choose your decks and press Sync now")
    last = anki_sync.load_state(language).get("last_sync")
    if not last:
        return _check("first_known_sync", NEEDS_YOU, "Surasura hasn't read the words you know from Anki yet, so "
                      "Connect could make cards for words you know.", "Sync once from Surasura's Anki window first")
    return _check("first_known_sync", OK, f"Your known words were last read from Anki on {str(last)[:16]}.")


# --------------------------------------------------------------------------- #
# Anki Miner (S4–S7, E7–E12, W1)
# --------------------------------------------------------------------------- #
def version_tuple(text):
    from app.connect import anki_miner
    return anki_miner.version_tuple(text)


def _too_old(app):
    from app.connect import anki_miner
    return anki_miner.too_old(app)


def _miner_error(id_, e):
    """An AnkiMinerError as a check: busy waits, the rest only you can fix."""
    if e.kind in ("busy", "writer-busy"):
        return _check(id_, WAITING, "Anki Miner is busy (its window is mining, or its Word Curator is open). "
                      "Connect waits until it's free.")
    if e.kind == "anki-closed":
        return _check(id_, WAITING, "Anki Miner can't reach Anki: Connect waits until Anki is open.", "Open Anki")
    if e.kind == "quarantined":
        return _check(id_, NEEDS_YOU, e.message, "Windows Security → Protection history")
    if e.kind == "unknown-version":
        return _check(id_, NEEDS_YOU, e.message, "Update Surasura")
    if e.kind == "too-old":
        return _check(id_, NEEDS_YOU, e.message, f"Update Anki Miner ({RELEASES})")
    if e.kind == "needs-you":
        return _check(id_, NEEDS_YOU, e.message, "Choose a profile Anki Miner has, or make it in Anki Miner")
    return _check(id_, NEEDS_YOU, f"Anki Miner didn't answer Surasura's question: {e.message}", "Open Anki Miner "
                  "once to check it starts")


def _anki_miner(settings, language, answered):
    """S4–S7 -> [checks], and what the record keeps about Anki Miner."""
    from app.connect import anki_miner
    ids = ("anki_miner", "anki_miner_version", "anki_miner_profile", "anki_miner_setup")

    def rest(after, why):
        return [_check(i, NOT_CHECKED, why) for i in ids[ids.index(after) + 1:]]

    chosen = str((settings or {}).get("connect_anki_miner_path") or "").strip()
    path = anki_miner.find(settings)
    if path is None:
        if chosen:
            say = f"Anki Miner isn't where Surasura's Anki Miner setting says: {chosen}."
            do = "Choose Anki Miner's program again, or clear the setting so Surasura finds it"
        else:
            say = "Anki Miner isn't installed. Connect uses it to make your cards from your videos (free, made by Zero)."
            do = f"Install Anki Miner ({RELEASES})"
        return [_check("anki_miner", NEEDS_YOU, say, do)] + rest("anki_miner", "Checked once Anki Miner is installed."), {}
    found = {"path": path}
    out = [_check("anki_miner", OK, "Anki Miner is installed.")]
    try:
        info = anki_miner.version(path)     # never runs a build its installer says is older than 3.5.0
    except anki_miner.AnkiMinerError as e:
        return out + [_miner_error("anki_miner_version", e)] + rest("anki_miner_version",
                                                                    "Checked once Anki Miner answers."), found
    app, features = info.get("app"), list(info.get("features") or [])
    found.update(app=app, features=features)
    if _too_old(app):
        return out + [_check("anki_miner_version", NEEDS_YOU, f"Anki Miner {app} is too old for Surasura: Connect "
                             "needs 3.5.0 or later.", f"Update Anki Miner ({RELEASES})")] + \
            rest("anki_miner_version", "Checked once Anki Miner is updated."), found
    out.append(_check("anki_miner_version", OK, f"Anki Miner {app} answers Surasura."))

    name = (settings or {}).get("connect_anki_miner_profile") or anki_miner.DEFAULT_PROFILE
    try:
        listed = anki_miner.profiles(path)
        profile = anki_miner.choose_profile(info, listed, name)
    except anki_miner.AnkiMinerError as e:
        check = _miner_error("anki_miner_profile", e)
        if e.kind == "needs-you" and name == anki_miner.DEFAULT_PROFILE:
            check["do"] = ("In Anki Miner: Manage profiles… → New, name it Surasura; then in its Settings, Whitelist → "
                           f"choose file: {anki_miner.whitelist_path(language)}")
        return out + [check] + rest("anki_miner_profile", "Checked once Connect has an Anki Miner profile."), found
    called = next((entry.get("name") for entry in listed if entry.get("id") == profile), None) or profile
    found.update(profile=profile, profile_name=called)
    if profile is None:
        out.append(_check("anki_miner_profile", OK, "Connect makes cards with Anki Miner's current settings."))
    else:
        out.append(_check("anki_miner_profile", OK, f'Connect makes cards with Anki Miner\'s profile "{called}".'))

    try:
        ready = anki_miner.check(path, language, profile)
    except anki_miner.AnkiMinerError as e:
        return out + [_miner_error("anki_miner_setup", e)], found
    items = {item.get("name"): item for item in ready.get("items") or () if isinstance(item, dict)}
    failed = {name_: item for name_, item in items.items() if not item.get("ok") and name_ not in FETCH_ONLY}
    anki_down = "anki" in failed
    own = {name_: item for name_, item in failed.items() if not (anki_down and name_ in ANKI_ITEMS)}
    if ready.get("ready") is True:          # its own verdict; what only its YouTube fetch needs never counts
        out.append(_check("anki_miner_setup", OK, "Anki Miner's own setup is finished."))
    elif own:
        named = "; ".join(f"{name_}: {item.get('message') or 'not ready'}" for name_, item in own.items())
        out.append(_check("anki_miner_setup", NEEDS_YOU, f"Anki Miner's own setup isn't finished ({named}).",
                          "Open Anki Miner and finish its setup"))
    elif anki_down and not answered:
        out.append(_check("anki_miner_setup", WAITING, "Anki Miner can't reach Anki: Connect waits until Anki is "
                          "open, then checks the rest of its setup.", "Open Anki"))
    elif anki_down:
        out.append(_check("anki_miner_setup", NEEDS_YOU, "Anki Miner can't reach Anki, though Surasura can: its "
                          "AnkiConnect address may differ from Surasura's.", "Check Anki Miner's AnkiConnect address"))
    else:
        out.append(_check("anki_miner_setup", NEEDS_YOU, "Anki Miner says its own setup isn't finished.",
                          "Open Anki Miner and finish its setup"))
    return out, found


# --------------------------------------------------------------------------- #
# Junban, Backfill (S8), Open Anki for me
# --------------------------------------------------------------------------- #
def _present(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _modules():
    out = []
    if _present("modules.junban.reposition"):
        out.append(_check("junban", OK, "Junban puts your new cards in Surasura's order."))
    else:
        out.append(_check("junban", SKIPPED, "Junban isn't installed, so Connect leaves your new cards in the order "
                          "Anki Miner adds them."))
    if _present("modules.junban.backfill"):
        out.append(_check("backfill", OK, "Backfill fills your new cards' パターン and 例文 fields."))
    else:
        out.append(_check("backfill", SKIPPED, "Backfill isn't installed, so Connect leaves your new cards' fields as "
                          "Anki Miner fills them."))
    return out


def _open_anki(settings):
    if not ((settings or {}).get("connect_enabled") and settings.get("connect_open_anki")):
        return []
    from app.connect import open_anki
    command = open_anki.find()
    if command is None:
        return [_check("open_anki", NEEDS_YOU, "Open Anki for me is on, but Surasura can't find Anki where its "
                       "installer puts it, so it can't open it for you.", "Open Anki yourself, or reinstall it in "
                       "its usual place", blocks=False)]
    return [_check("open_anki", OK, "Open Anki for me: Surasura opens Anki when you open Surasura.")]


# --------------------------------------------------------------------------- #
# All of them
# --------------------------------------------------------------------------- #
def checks(settings, language, keep=None, use_open_profile=False):
    """Every check, in order -> {"ready", "checks", "anki_profile", "anki_miner", "recorded"}. `keep` (default:
    Connect's preview is on): write the setup record; off, nothing is written. `use_open_profile`: Connect works in
    the Anki profile open now (`surasura-cli setup --use-anki-profile`). Never raises for a missing piece."""
    from app import anki_connect
    settings = settings or {}
    keep = bool(settings.get("connect_enabled")) if keep is None else bool(keep)
    record = read_record()
    before = record.get("anki_profile")
    url = anki_connect.address(settings)
    anki, answered = _anki(url, bool(settings.get("connect_enabled") and settings.get("connect_open_anki")))
    profile, open_now = _anki_profile(url, answered, record, keep, use_open_profile)
    out = [anki, profile, _ankiweb(record), _first_known_sync(settings, language)]
    miner, found = _anki_miner(settings, language, answered)
    out += miner + _modules() + _open_anki(settings)
    written = False
    if keep:
        # Onto the record as it is now (another program may have written it while Anki Miner answered): only what
        # this look decided
        fresh = read_record()
        if record.get("anki_profile") != before:
            fresh["anki_profile"], fresh["anki_profile_at"] = record["anki_profile"], record.get("anki_profile_at")
        fresh["anki_miner"] = found or None
        fresh["checked_at"] = _now()
        fresh.setdefault("checks", {})[language] = [{"id": c["id"], "state": c["state"]} for c in out]
        written = write_record(fresh)
        record = fresh
    return {"ready": not any(c["blocks"] for c in out), "checks": out,
            "anki_profile": record.get("anki_profile") if keep else (record.get("anki_profile") or open_now),
            "anki_miner": found or None, "recorded": written}

"""The Anki window's rules (W3.4 row 3), Qt-free: what the Tk `AnkiSyncGui` decided inside its class (the inventory's
§5), moved beside the engine (`app/anki_sync.py`) so the Qt window (`app/qt/anki_window.py`) only paints the answers.

- **What is synced:** the word field and *Also read* (`fields`), the per-language merge of `anki_sync_decks` /
  `anki_sync_fields` the settings service applies to the file as it is (`merge`), the first-open pre-selection
  (`preselect`: every deck with studied cards, largest first — shown, and saved only on the user's first action: S16,
  IK-13), the resolved and skipped field lines (`field_lines`), which controls are live (`controls`).
- **What Anki said:** the connection's state in plain words (`connection`: a refused connection is "Anki isn't
  running"; a permission prompt, a missing action or an outdated add-on is shown as written), the reads a worker makes
  (`read_probe`, `read_scope`) and the window's numbers (`known_view`, `ago`, `result_view`, `restore_point`).
- **Every Sync / Replace / Restore is an `anki-sync` job** (`submit`): the kind W3.5's automatic sync checks
  (`automation.AutoSync.maybe`: never a second sync beside this one), refused while an update holds Surasura's children
  (`updater.children_held`, as the automatic sync); its result is told to the automation service as the Tk window told
  the dashboard (`Automation.anki_synced`: the quiet Generate, the indexer), from the job's own thread, so a window
  closed meanwhile loses nothing.
- **Replace and Restore write only what was confirmed:** the confirmation shows the dry run's numbers
  (`anki_sync.confirmed`) and the write carries them (`replace(expect=)`); Restore names its backup
  (`restore_previous(expect=)`). Changed meanwhile, nothing is written and the window asks again.

Nothing here touches a widget or waits on the caller's thread except the reads named as a worker's.
"""
import json
import os
import re
import threading
from collections import namedtuple
from datetime import datetime

from app import anki_connect, anki_sync

KIND = "anki-sync"                  # the job registry's kind (`jobs.RESOURCES`: the known-words resource)
LANGUAGES = ("ja", "zh")
# The errors shown as Anki wrote them: something the user can act on (a permission prompt, an add-on to update).
ACTIONABLE = ("permission", "grant", "missing", "update", "stopped answering")
_BACKUP_RE = re.compile(r"KnownWord\.(\d{8}-\d{6})(?:-\d+)?\.json$")

Probe = namedtuple("Probe", "report decks preselected counts models")
Known = namedtuple("Known", "total last_sync last_added backup backlog")
RestorePoint = namedtuple("RestorePoint", "name when now then")


# --- what is synced ------------------------------------------------------------------------------------------------- #
def saved(settings, language):
    """The window's choices for `language` as settings hold them -> (decks, fields, include_suspended)."""
    settings = settings or {}
    decks = [str(d) for d in ((settings.get("anki_sync_decks") or {}).get(language) or [])]
    chosen = [str(f) for f in ((settings.get("anki_sync_fields") or {}).get(language) or [])][:2]
    return decks, chosen, bool(settings.get("anki_sync_include_suspended", False))


def fields(first, second=None):
    """The word field and *Also read* -> what the engine reads: [] for Auto (each note type's first field), else the
    named field and, when one is named and differs, the second (the Tk `_fields`). A second field without a named
    first is never read (Auto is per note type)."""
    first = str(first or "").strip()
    second = str(second or "").strip()
    if not first:
        return []
    return [first] + ([second] if second and second != first else [])


def merge(language, decks, chosen):
    """The settings service's `update` for this window's two per-language keys (the Tk `_save`'s merge): `language`'s
    decks and fields written onto the file's own dicts — another language's choices, and another program's save
    meanwhile, kept. Copies: nothing the caller holds is shared with the file's dict."""
    decks, chosen = [str(d) for d in decks], [str(f) for f in chosen]

    def update(settings):
        for key, value in (("anki_sync_decks", decks), ("anki_sync_fields", chosen)):
            per_language = dict(settings.get(key) or {})
            per_language[language] = list(value)
            settings[key] = per_language
    return update


def preselect(counts):
    """The first open's pick (Anki_Known_Sync_Spec §5.6): every deck with studied cards, largest first."""
    return [deck for deck, n in sorted((counts or {}).items(), key=lambda kv: -kv[1]) if n > 0]


def field_names(models):
    """Every field of the note types in scope, in their order, once each."""
    seen = []
    for names in (models or {}).values():
        for name in names:
            if name not in seen:
                seen.append(name)
    return seen


def field_choices(models, first):
    """(the word field's named choices, *Also read*'s) — the first keeps a saved name Anki doesn't show (yet); the
    second never offers the word field itself."""
    names = field_names(models)
    first = str(first or "")
    firsts = names + ([first] if first and first not in names else [])
    return firsts, [n for n in names if n != first]


def field_lines(models, chosen):
    """The resolved and skipped field lines: -> ([(note type, [fields read])], [note types skipped]) in name order
    (`anki_sync.resolve_fields`: the note type that lacks the chosen field is skipped by the sync)."""
    resolved, skipped = [], []
    for model, names in sorted((models or {}).items()):
        read = anki_sync.resolve_fields(names, chosen)
        if read:
            resolved.append((model, read))
        else:
            skipped.append(model)
    return resolved, skipped


def controls(connected, busy, decks, chosen):
    """Which controls are live: Sync and Replace need Anki, a deck and the window idle; adding a deck and the word
    field need Anki; *Also read* a named word field; ⟳, removing a deck, the switches and Restore only that the window
    is idle (the inventory's defect 4: *Include suspended* changed mid-job left the counts stale)."""
    idle = not busy
    live = idle and bool(connected)
    return {"sync": live and bool(decks), "replace": live and bool(decks), "add": live, "field1": live,
            "field2": live and bool(chosen), "recheck": idle, "remove": idle, "suspended": idle, "restore": idle}


# --- what Anki said ------------------------------------------------------------------------------------------------- #
def connection(report):
    """-> ("connected", version or None) · ("closed", the error) · ("problem", the error as Anki wrote it): a refused
    connection just means Anki is closed; anything the user can act on is shown as written (the Tk `_set_connection`)."""
    report = report or {}
    if report.get("ok"):
        return "connected", report.get("version")
    error = str(report.get("error") or "")
    if any(word in error.lower() for word in ACTIONABLE):
        return "problem", error
    return "closed", error


def read_probe(url, decks, suspended):
    """(A worker.) Is Anki there, which decks has it, and — with no deck chosen yet — the first open's pick; the
    studied counts and the note types of the decks in scope. -> Probe. Never raises: an Anki that answered the probe
    and went away mid-read is a report that says so."""
    report = anki_connect.probe(url)
    if not report.get("ok"):
        return Probe(report, [], None, {}, {})
    try:
        names = anki_connect.deck_names(url)
        picked = None
        if not decks:
            picked = preselect(anki_sync.deck_study_counts(url, names, suspended))
        chosen = picked if picked is not None else list(decks)
        counts, models = read_scope(url, chosen, suspended)
    except anki_connect.AnkiError as e:
        return Probe({"ok": False, "error": f"Anki stopped answering: {e}"}, [], None, {}, {})
    return Probe(report, names, picked, counts, models)


def read_scope(url, decks, suspended):
    """(A worker.) -> ({deck: studied notes}, {note type: [fields]}) for `decks`. Raises AnkiError."""
    if not decks:
        return {}, {}
    return (anki_sync.deck_study_counts(url, decks, suspended),
            anki_sync.models_in_scope(url, decks, suspended))


def known_view(language):
    """(A worker.) The known-words total, the last sync, whether a backup can be put back, the backlog -> Known."""
    state = anki_sync.load_state(language)
    return Known(anki_sync.count_known(language), state.get("last_sync"), int(state.get("last_added") or 0),
                 state.get("last_backup") or None, anki_sync.count_backlog(language))


def ago(iso, now=None):
    """How long ago an ISO time was -> ("now", 0) · ("min", n) · ("h", n) · ("days", n), or None (the Tk `_ago`)."""
    try:
        seconds = ((now or datetime.now()) - datetime.fromisoformat(str(iso))).total_seconds()
    except (TypeError, ValueError):
        return None
    if seconds < 60:
        return "now", 0
    if seconds < 3600:
        return "min", int(seconds // 60)
    if seconds < 86400:
        return "h", int(seconds // 3600)
    return "days", int(seconds // 86400)


def result_view(result):
    """What a job's result says -> (kind, numbers): "error" (the engine's words, shown as they are) · "changed" (the
    numbers moved since they were confirmed: ask again) · "synced" · "replaced" · "restored"."""
    if result is None:
        return "error", {"text": ""}
    if result.error:
        return "error", {"text": result.error}
    if result.changed:
        return "changed", {}
    if result.mode == "replace":
        return "replaced", {"total": result.total_known, "added": result.added, "graduated": result.kept_graduated,
                            "ignored": result.kept_ignored}
    if result.mode == "restore":
        return "restored", {"total": result.total_known}
    return "synced", {"added": result.added, "scanned": result.scanned, "full": result.mode == "full"}


def backup_time(name):
    """When a known-words backup was made, from its name (`KnownWord.<YYYYmmdd-HHMMSS>[-n].json`), or None."""
    found = _BACKUP_RE.search(str(name or ""))
    if not found:
        return None
    try:
        return datetime.strptime(found.group(1), "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def restore_point(language):
    """(A worker.) What *Restore previous* would put back — RestorePoint(the backup's name, when it was made, the known
    total now, the backup's known total, None when it can't be read) — or None when there is none to put back."""
    from app.path_utils import get_user_files_path, read_text
    name = anki_sync.load_state(language).get("last_backup")
    if not name:
        return None
    path = os.path.join(get_user_files_path(language), ".trash", str(name))
    if not os.path.isfile(path):
        return None
    try:
        data = json.loads(read_text(path, language, errors="strict"))
        words = data.get("words") if isinstance(data, dict) else data
        then = len(anki_sync._known_keys(words if isinstance(words, list) else []))
    except (OSError, ValueError, UnicodeDecodeError):
        then = None
    return RestorePoint(str(name), backup_time(name), anki_sync.count_known(language), then)


# --- the jobs ------------------------------------------------------------------------------------------------------- #
def update_holds():
    """An update waits for Surasura's children (K75): no Anki read or write of the known words may begin."""
    try:
        from app import updater
        return bool(updater.children_held())
    except Exception:
        return False


def run_sync(language, url, decks, chosen, suspended, full=False):
    """(The job's thread.) *Sync now* (Shift-click: `full`, every card read again), then the same decks' new cards, as
    the automatic sync reads them — a backlog read that fails never costs the sync its result."""
    result = anki_sync.sync(language, url, decks, chosen, include_suspended=suspended, full=full)
    if not result.error:
        try:
            anki_sync.sync_backlog(language, url, decks, chosen)
        except Exception as e:
            print(f"Anki window: the backlog read failed ({e})")
    return result


def run_dry(language, url, decks, chosen, suspended):
    """(The job's thread.) Replace's dry run: the numbers, nothing written."""
    return anki_sync.replace(language, url, decks, chosen, include_suspended=suspended, dry_run=True)


def run_replace(language, url, decks, chosen, suspended, expect):
    """(The job's thread.) Replace, writing only while the confirmed numbers still hold."""
    return anki_sync.replace(language, url, decks, chosen, include_suspended=suspended, expect=expect)


def run_restore(language, expect, now=None):
    """(The job's thread.) Restore previous, putting back only the confirmed backup over the known total confirmed."""
    return anki_sync.restore_previous(language, expect=expect, now=now)


def tells(result):
    """Whether a job's result goes to the automation service: a sync, Replace or Restore that ran — never a dry run,
    nor a write that stopped because its numbers moved (it wrote nothing)."""
    return result is not None and result.mode != "dry-run" and not result.changed


def submit(registry, label, work, on_end, automation=None, language=None, on_quit="detach", moved=None):
    """`work()` (-> a SyncResult) as an `anki-sync` job labelled `label` (the user's words, for the bar); `on_end(result)`
    on the job's thread when it ended, after the result was told to the automation service (`anki_synced`, when
    `tells`) — `automation` is the service or a callable that returns it, asked when the job ends (the duties are made
    on a worker after the window opens: AD3-9). The job waits behind an automatic sync already running (the registry's
    table). At quit: a sync or a dry run is `detach` (it appends atomically under the known-words lock, or only reads);
    Replace and Restore pass `wait` — they write two files, the list and then the state naming its backup, and a quit
    between them would leave *Restore previous* naming the wrong backup (AD3-1). -> the Job, or None when an update
    holds the children (nothing submitted). `moved`: what the job ends saying when its write stopped because the
    confirmed numbers moved (nothing written; IK-46) — never a plain "done"."""
    if update_holds():
        return None

    def run(job):
        try:
            result = work()
        except Exception as e:                    # a window must never lose a result to a traceback
            result = anki_sync.SyncResult(error=f"Unexpected error: {e}")
        job.finish(ok=not result.error, message=result.error or (moved if result.changed else None))
        service = automation() if callable(automation) else automation
        if service is not None and tells(result):
            try:
                service.anki_synced(result, language)
            except Exception as e:
                print(f"Anki window: the automation service didn't hear the result ({e})")
        on_end(result)

    def start(job):
        threading.Thread(target=run, args=(job,), name="anki-window-job", daemon=True).start()
    return registry.submit(KIND, label, start, on_quit=on_quit)

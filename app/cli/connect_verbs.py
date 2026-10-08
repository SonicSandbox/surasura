"""surasura-cli's library verbs for Connect (P2.1; P1.5 09-hato-layer §2, P0.3 03-verbs): `register`, `place`, `finish`,
and `connect` (in P2.1: `--consume-only`, the inbox read once).

- `register` takes hato's pairing record v1 on stdin (`--pairing -`) or from a file — never on the command line, which
  is logged — and registers it in the library store. **With Connect's preview off it answers `skipped` and writes
  nothing** (master_manifest.json and the window's undo stack untouched): the preview off is 2.5.
- `connect` (P2.4) runs Connect's loop (`app/connect/runner.py`) until no job is left; `--consume-only` reads the
  inbox once and exits (P2.1).
- `place` and `finish` are a person's verbs, accepted from any program: each placement is logged with `--source`
  (✅ G1.3-5: another program's placement counts like yours, its name recorded). `finish` comes with Surasura 3.0
  (✅ P2.1-1): through 2.x the window's Graduate still marks an item's words known, and finish never does (✅ Q2-5).

Every store write is one short transaction (02 §9, S-R-6); with no store (JSON mode, read-only) nothing is written
(G1.1-10). Light by rule (02 §5): no Tk, Qt, pandas or requests; every import is inside the verb that needs it.
"""
import codecs
import hashlib
import json
import os
import re
import sys
import time

from app.cli import contract
from app.cli.contract import CliError
from app.cli.verbs import LANGUAGES, add_language, add_wait, language, require_set_up, settings

RECORD_MAX = 64 * 1024          # a record is well under 4 KiB; over 64 KiB is refused (09 §1)
_KEY = re.compile(r"v1-[0-9a-f]{64}")
_SHA = re.compile(r"[0-9a-f]{64}")
# The record v1's fields (09 §1): every one present (null where the table allows it)
REQUIRED = ("schema", "content_key", "producer", "producer_version", "language", "video_path", "video_size",
            "subtitle_path", "library_path", "subtitle_sha256", "verdict", "picked_by", "show", "jimaku_entry_id",
            "anilist_id", "tmdb_id", "subtitle_source", "paired_at")
_TEXT = ("producer", "producer_version", "video_path", "subtitle_path", "library_path", "verdict", "picked_by",
         "paired_at")
PREVIEW_OFF = "connect preview off"
TIER_OF = {"now": "now", "soon": "soon", "later": "goal"}


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #
def _bad(message, **context):
    return CliError("bad-data", message, **context)


def _open_store(lang):
    """The language's library store, or `needs-you` (none yet, JSON mode or read-only: nothing may be written)."""
    from app.connect import library
    store = library.open_store(lang, role="register")
    if store is None:
        raise CliError("needs-you", "Surasura's library isn't ready for this yet.", ask="Open Surasura once")
    return store


def _store_write(write, wait):
    """Run one short store write, retried while another program holds the library's write lock, for up to `wait`
    seconds (`--wait`) -> its result; still held -> `busy`."""
    from app import library_store
    deadline = time.monotonic() + max(0.0, wait or 0.0)
    while True:
        try:
            return write()
        except library_store.StoreBusy:
            if time.monotonic() >= deadline:
                raise CliError("busy", "Another Surasura program is changing the library. Try again in a moment.",
                               lock="library", held_by=None) from None
            time.sleep(0.25)
        except library_store.StoreReadOnly:
            raise CliError("failed", "Surasura's library can't be written just now. Open Surasura to see why.") \
                from None


def _kick(loaded):
    """Start Connect if it should run (P2.1 row 2.1.5); never fails the verb."""
    try:
        from app.connect import kick
        kick.kick(loaded)
    except Exception:
        contract.log.exception("Connect wasn't started")


_SOURCE = re.compile(r"[a-z0-9_-]{1,32}")
RESERVED = ("user", "undo", "sync")     # the names the store and the window log their own placements under


def _source(value):
    """`--source`: a short program name (as the placement log keeps it), never one the store or a person uses."""
    if not _SOURCE.fullmatch(value or "") or value in RESERVED or value.startswith("rule"):
        raise CliError("usage", "--source is your program's name: lowercase letters, digits, - or _, up to 32 "
                                f"(not {', '.join(RESERVED)} or rule…).")
    return value


# --------------------------------------------------------------------------- #
# register (09-hato-layer §2)
# --------------------------------------------------------------------------- #
def register_args(parser):
    add_language(parser)
    add_wait(parser)
    parser.add_argument("--pairing", required=True, metavar="-|FILE",
                        help="the pairing record (JSON): - to read it from stdin, or a file's path")
    parser.add_argument("--backfill", action="store_true",
                        help="a pairing made before Connect was switched on: recorded, never mined because of it")


def _no_constant(name):
    raise ValueError(f"{name} isn't JSON")          # NaN, Infinity: never into the store or its copy


def _read_record(source):
    """The record's bytes from stdin (`-`) or a file, strict UTF-8 (a BOM accepted) -> a dict, or `bad-data`."""
    if source == "-":
        stream = getattr(sys.stdin, "buffer", None)
        if stream is None:
            raise _bad("No pairing record on stdin.")
        data = stream.read(RECORD_MAX + 1)
    else:
        try:
            with open(source, "rb") as f:
                data = f.read(RECORD_MAX + 1)
        except OSError as e:
            raise _bad("The pairing record's file can't be read.", detail=str(e)) from None
    if len(data) > RECORD_MAX:
        raise _bad(f"The pairing record is over {RECORD_MAX // 1024} KiB.")
    if data.startswith(codecs.BOM_UTF8):
        data = data[len(codecs.BOM_UTF8):]
    try:
        record = json.loads(data.decode("utf-8"), parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError) as e:
        raise _bad("The pairing record isn't JSON in UTF-8.", detail=str(e)) from None
    if not isinstance(record, dict):
        raise _bad("The pairing record isn't a JSON object.")
    return record


def _check_record(record):
    """The record v1's shape (09 §1): `version-skew` for a newer schema, `bad-data` for anything malformed."""
    schema = record.get("schema")
    if isinstance(schema, bool) or not isinstance(schema, int) or schema < 1:
        raise _bad("The pairing record has no schema number.")
    if schema > 1:
        raise CliError("version-skew", f"This pairing record (schema {schema}) is newer than this Surasura reads. "
                                       "Update Surasura.", schema=schema)
    missing = [k for k in REQUIRED if k not in record]
    if missing:
        raise _bad("The pairing record is missing fields.", missing=missing)
    wrong = [k for k in _TEXT if not isinstance(record[k], str) or not record[k].strip()]
    if not isinstance(record["content_key"], str) or not _KEY.fullmatch(record["content_key"]):
        wrong.append("content_key")
    if not isinstance(record["subtitle_sha256"], str) or not _SHA.fullmatch(record["subtitle_sha256"]):
        wrong.append("subtitle_sha256")
    if record["language"] not in LANGUAGES:
        wrong.append("language")
    if isinstance(record["video_size"], bool) or not isinstance(record["video_size"], int) or record["video_size"] < 0:
        wrong.append("video_size")
    if record["show"] is not None and not isinstance(record["show"], dict):
        wrong.append("show")
    producer = record["producer"]
    if isinstance(producer, str) and (not _SOURCE.fullmatch(producer) or producer in RESERVED
                                      or producer.startswith("rule")):
        wrong.append("producer")        # a short program name: the placement log records it as who registered
    if wrong:
        raise _bad("The pairing record has fields Surasura can't read.", fields=wrong)


def _in_library(path, lang):
    """Is `path` an absolute path under the language's data folder? (checked before anything is written; the store
    refuses it too)"""
    from app.path_utils import get_data_path
    if not os.path.isabs(path):
        return False
    try:
        rel = os.path.relpath(os.path.abspath(path), get_data_path(lang))
    except ValueError:              # another drive (Windows)
        return False
    return not (rel in (os.curdir, os.pardir) or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel))


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def register(args):
    """hato's verb: the pairing record → the store (`library_store.register_headless`) → where the item is."""
    record = _read_record(args.pairing)
    _check_record(record)
    if args.lang and args.lang != record["language"]:
        raise CliError("usage", f"--lang {args.lang} but the record's language is {record['language']}.")
    lang = record["language"]
    key = record["content_key"]
    loaded = settings()
    if not loaded.get("connect_enabled"):
        return {"file_id": None, "landed": "skipped", "tier": None, "position": None, "pairing": None,
                "content_key": key, "skipped": PREVIEW_OFF}
    require_set_up(lang)

    path = record["library_path"]
    if not _in_library(path, lang):
        raise _bad("The subtitle's copy isn't inside Surasura's library folder.", library_path=path)
    if not os.path.isfile(path):
        raise _bad("The subtitle's copy in Surasura's library isn't there.", library_path=path)
    if _sha256(path) != record["subtitle_sha256"]:
        raise _bad("The subtitle's copy in Surasura's library isn't the file hato paired.", library_path=path)

    from app import library_store
    from app.connect import library, rules
    # Connect's watermark set before the registration (a store this call builds too), so the drop is logged after it
    reader = None if args.backfill else library.READER
    done = _store_write(lambda: library_store.register_headless(lang, path, record, backfill=args.backfill,
                                                                  looks=library_store.PROBE_LOOKS, reader=reader),
                        args.wait)
    if done.code == library_store.EXIT_BUSY:
        if library_store.update_staged(looks=library_store.PROBE_LOOKS):
            raise CliError("update-staged", "Surasura is installing an update. Try again once it has restarted.")
        raise CliError("busy", "Surasura's library is being looked after by another Surasura program. Try again "
                               "in a moment.", lock="library-maintenance", held_by=None)
    if done.code == library_store.EXIT_NEEDS_YOU:
        raise CliError("needs-you", "Surasura's library isn't set up yet.", ask="Open Surasura once")
    if done.code == library_store.EXIT_BAD_DATA:
        raise _bad("The subtitle's copy isn't inside Surasura's library folder.", library_path=path)
    if done.code != library_store.EXIT_DONE:
        raise CliError("failed", f"Surasura's library couldn't take the pairing (code {done.code}).")

    out = {"file_id": done.file_id, "landed": done.landed, "tier": done.tier, "position": done.position,
           "pairing": done.pairing, "content_key": key}
    if args.backfill:
        return out
    work = False
    store = library.open_store(lang, role="register")
    if store is not None:
        with store:
            if done.tier == "arrivals":
                # Every call while the item waits, so a retry after a failed first try still places it
                try:
                    rule = _store_write(lambda: rules.apply(store, done.file_id, record, loaded), args.wait)
                except ValueError:          # its anchor moved meanwhile: it waits, and hato's retry places it
                    contract.log.warning("a placing rule's anchor moved; item %s waits", done.file_id)
                    rule = None
                if rule:
                    out["rule"] = rule
                    out["tier"], out["position"] = store.place_of(done.file_id)
            from app.connect import inbox
            work = inbox.pending(store)
    if work:
        _kick(loaded)       # also on a retry: a crash after the commit never leaves the drop unread
    return out


# --------------------------------------------------------------------------- #
# place, finish (a person's verbs; P0.3 03-verbs)
# --------------------------------------------------------------------------- #
def _item_args(parser):
    add_language(parser)
    add_wait(parser)
    parser.add_argument("--file", type=int, required=True, metavar="ID",
                        help="the item's id (register's file_id)")
    parser.add_argument("--source", required=True, metavar="WHO",
                        help="who asks: your program's name, recorded with the placement")


def place_args(parser):
    _item_args(parser)
    parser.add_argument("--to", required=True, choices=("now", "soon", "later", "current"),
                        help="NOW, Soon or 6+ Months (2.x); current: the one Current list (Surasura 3.0)")
    parser.add_argument("--position", type=int, default=None, metavar="N",
                        help="its place there, from 1 (default: the top)")


def _item(store, item_id, lang):
    item = store.item(item_id)
    if item is None:
        raise _bad(f"There's no item {item_id} in the {lang} library.", file_id=item_id)
    return item


def _target(store, item_id, to, position):
    """Where `--to` / `--position` puts the item -> (tier, before_id, after_id): before the item now at that place,
    after the last when past the end, the top when no position (or 1). In *Current* (NOW, then Soon) a place right
    after NOW's last item stays in NOW."""
    if to == "current":
        now = [(i, "now") for i in store.ids("now") if i != item_id]
        others = now + [(i, "soon") for i in store.ids("soon") if i != item_id]
        tier = "now"
    else:
        tier = TIER_OF[to]
        now, others = [], [(i, tier) for i in store.ids(tier) if i != item_id]
    if position is None or position <= 1 or not others:
        return tier, None, None
    if position > len(others):
        return others[-1][1], None, others[-1][0]
    if now and position == len(now) + 1:
        return "now", None, now[-1][0]
    anchor, anchor_tier = others[position - 1]
    return anchor_tier, anchor, None


def place(args):
    """Put one item in a tier at a place, logged as `--source`'s placement; Connect kicked when it is on."""
    from app.connect import library
    if args.position is not None and args.position < 1:
        raise CliError("usage", "--position counts from 1.")
    source = _source(args.source)
    loaded = settings()
    lang = language(args, loaded)
    require_set_up(lang)
    store = _open_store(lang)
    with store:
        if args.to == "current" and not library.three_oh(store):
            raise CliError("usage", "--to current comes with Surasura 3.0. Use now, soon or later.")
        item = _item(store, args.file, lang)
        if item["tier"] == "graduated":
            raise _bad("That item is finished (Graduated). Bring it back from Surasura's window.", file_id=args.file)
        tier, before_id, after_id = _target(store, args.file, args.to, args.position)
        if loaded.get("connect_enabled"):
            _store_write(lambda: library.ensure_reader(store), args.wait)
        change = _store_write(lambda: library.place(store, args.file, tier, before_id=before_id, after_id=after_id,
                                                    source=source), args.wait)
        tier, position = store.place_of(args.file)
        if args.to == "current" and tier == "soon":
            position += len(store.ids("now"))           # its place in Current: NOW, then Soon
    if change is not None:
        _kick(loaded)
    return {"file_id": args.file, "tier": tier, "position": position, "moved": change is not None,
            "source": source}


def finish_args(parser):
    _item_args(parser)


def finish(args):
    """Move one item to *Finished* (3.0): no known word and no card changes (✅ Q2-5, Q2-6). Held to 3.0 (✅ P2.1-1)."""
    from app.connect import library
    source = _source(args.source)
    loaded = settings()
    lang = language(args, loaded)
    require_set_up(lang)
    store = library.open_store(lang, role="register")
    if store is None or not library.three_oh(store):
        if store is not None:
            store.close()
        raise CliError("usage", "finish comes with Surasura 3.0. Until then, use Graduate in Surasura's window "
                                "(it also marks the item's words known).")
    with store:
        _item(store, args.file, lang)
        change = _store_write(lambda: library.finish(store, args.file, source=source), args.wait)
        tier, position = store.place_of(args.file)
    return {"file_id": args.file, "tier": tier, "position": position, "finished": change is not None,
            "source": source}


# --------------------------------------------------------------------------- #
# connect (P2.1: the inbox, once; P2.4: the loop)
# --------------------------------------------------------------------------- #
ROUNDS = 20         # reads of the log a Connect makes before it leaves the rest to the next one


def connect_args(parser):
    import argparse
    parser.add_argument("--consume-only", action="store_true",
                        help="read the library's new placements into Connect's queue, then exit (no mining)")
    parser.add_argument("--looks", type=int, default=None, help=argparse.SUPPRESS)    # tests and drills: at most N


def connect(args):
    """Connect, one per install (its `connect` lock): a second one answers `skipped` at once. Started by `kick`. Reads
    every language's log (one lock for both: a kick for Chinese while a Japanese read runs is this run's work), and
    again after letting go of its lock while anything new was logged meanwhile — a kick that found it running is never
    lost."""
    loaded = settings()
    if not loaded.get("connect_enabled"):
        return {"skipped": PREVIEW_OFF}
    from app import locks
    from app.connect import inbox, kick, library
    from app.path_utils import get_user_files_path
    languages = [lang for lang in LANGUAGES if os.path.isdir(get_user_files_path(lang))]
    if not languages:
        raise CliError("not-set-up", "Surasura isn't set up yet. Open Surasura once to set it up.")
    if not args.consume_only:
        return _loop(loaded, languages, getattr(args, "looks", None))
    out = {lang: {"queued": [], "dropped": [], "reconciled": False, "read": 0, "missed": []} for lang in languages}
    rounds = 0
    while rounds < ROUNDS:
        try:
            held = locks.take(kick.LOCK, "Connect", wait=1.0)   # a kick's look holds it well under a millisecond
        except locks.Busy:
            if rounds == 0:
                return {"skipped": "already running"}
            break                                               # another Connect took over: it reads the rest
        rounds += 1
        with held:
            for lang in languages:
                store = library.open_store(lang)
                if store is None:
                    continue                                    # no store (JSON mode, read-only): nothing written
                with store:
                    got = _store_write(lambda: inbox.consume(store, lang), 10.0)
                    if rounds == 1:
                        out[lang]["level"] = _level(store, lang, loaded)     # P2.2: once a run, after the inbox
                mine = out[lang]
                mine["queued"] += got["queued"]
                mine["dropped"] += got["dropped"]
                mine["reconciled"] = mine["reconciled"] or got["reconciled"]
                mine["read"] += got["read"]
                mine["missed"] += got["missed"]
        if not any(_pending(lang) for lang in languages):
            break
    # A sync a writer verb left pending (S3) is sent before Connect exits, never once Anki has closed (P2.3; E1.1 04
    # §3: a pending sync never dies with its process). Outside Connect's lock: a kick meanwhile starts a reader.
    from app.cli.verbs import _session
    session = _session(loaded)
    if session is not None:
        from app import anki_connect
        session.settle(anki_connect.address(loaded), loaded)
    return {"languages": out, "rounds": rounds}


def _loop(loaded, languages, looks=None):
    """P2.4: Connect's loop under its one lock (a second Connect answers `skipped`), the cycle collector paused while
    it runs (`batch_gc`); a kick that came while it held the lock is read by the next one, started before this exits."""
    from app import batch_gc, locks
    from app.connect import kick, runner
    from app.connect.ledger import TooNew
    try:
        held = locks.take(kick.LOCK, "Connect", wait=1.0)
    except locks.Busy:
        return {"skipped": "already running"}
    try:
        with held:
            summary = batch_gc.without_cycle_collection(runner.run)(loaded, languages, looks=looks)
    except TooNew as e:
        raise CliError("needs-you", str(e), ask="Update Surasura") from None
    if not summary.get("stopped") and any(_pending(lang) for lang in languages):
        _kick(loaded)                   # logged after its last read: the next Connect reads it
    return summary


def _level(store, lang, loaded):
    """P2.2, the level raise's look (`app/connect/level.py`) on the list `results/` holds for this language: the
    newly listed words of the episodes already mined, top 20 first, as `level` jobs; None when there's no list of it
    to read (another language's, none yet, a Generate writing it)."""
    from app.connect import level
    try:
        read = _read_list(lang)
        if read is None:
            return None
        signature, listed, file_words = read
        return level.check(store, lang, listed, signature, file_words,
                           mode=loaded.get("connect_mine_words") or "list")
    except Exception as e:      # a busy ledger, a store that can't be read: this look is skipped, never the run
        return {"error": f"{type(e).__name__}: {e}"}


def _read_list(lang):
    """(the run signature, the list's keys {(Word, Reading)}, `file_words.json`) of the last Generate, read under
    `results` (a Generate writing them is waited for 5 s, then left to the next look) — or None."""
    from app.cli import verbs
    try:
        with contract.take_lock("results", "Connect reading the list", wait=5.0):
            holds = verbs._results_language()
            folder = verbs._results_dir()
            path = os.path.join(folder, verbs.PRIORITY_CSV)
            # Only a list known to be this language's: one whose language can't be told is no look (another
            # language's list recorded as this one's would make its whole list "newly listed" at its next Generate)
            if holds != lang or not os.path.exists(path):
                return None
            signature = verbs.read_run_stamp_here()
            if signature is None:
                return None                         # a Generate that didn't finish: its list may be cut short
            rows = verbs._read_rows(path)
            try:
                with open(os.path.join(folder, "file_words.json"), "r", encoding="utf-8") as f:
                    file_words = json.load(f)
            except (OSError, ValueError):
                file_words = {}
    except CliError:
        return None
    if not isinstance(file_words, dict):
        file_words = {}
    return signature, {(row.get("Word", ""), row.get("Reading", "")) for row in rows}, file_words


def _pending(lang):
    from app.connect import inbox, library
    store = library.open_store(lang)
    if store is None:
        return False
    with store:
        return inbox.pending(store)


# --------------------------------------------------------------------------- #
# setup (P2.3: the setup checks, P1.5 04-onboarding §1)
# --------------------------------------------------------------------------- #
def setup_args(parser):
    add_language(parser)
    parser.add_argument("--use-anki-profile", action="store_true",
                        help="Connect makes cards in the Anki profile open now, from now on")


def setup(args):
    """Every piece Connect needs, in order, each missing one named in plain words with its one action
    (`app/connect/setup.py`). Exit 0 whatever is missing: the list is the answer. With Connect's preview on the setup
    record is kept (`<local data>/connect/setup.json`); off, nothing is written. Asks Anki read-only and Anki Miner its
    `--api version`, `profiles` and `check`; never syncs, writes Anki or starts Anki."""
    loaded = settings()
    lang = language(args, loaded)
    require_set_up(lang)
    if args.use_anki_profile and not loaded.get("connect_enabled"):
        raise CliError("usage", "--use-anki-profile is for Connect's preview: switch it on first.")
    from app.connect import setup as checking
    contract.emit_progress("checking Anki and Anki Miner", 0, 1)
    out = checking.checks(loaded, lang, use_open_profile=args.use_anki_profile)
    if args.use_anki_profile:
        anki, profile = out["checks"][0], out["checks"][1]
        if anki["state"] != checking.OK:
            raise CliError("anki-closed", f"{anki['say']} Surasura can't see which profile to use until it answers.")
        if profile["state"] != checking.OK:
            raise CliError("failed", profile["say"])
        if not out["recorded"]:
            raise CliError("failed", "Surasura couldn't save Connect's setup record. Try again in a moment.")
    contract.emit_progress("done", 1, 1)
    return dict(out, language=lang, connect=bool(loaded.get("connect_enabled")))

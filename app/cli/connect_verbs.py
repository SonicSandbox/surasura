"""surasura-cli's library verbs for Connect (P2.1; P1.5 09-hato-layer §2, P0.3 03-verbs): `register`, `place`, `finish`,
and `connect` (in P2.1: `--consume-only`, the inbox read once).

- `register` takes hato's pairing record v1 on stdin (`--pairing -`) or from a file — never on the command line, which
  is logged — and registers it in the library store. **With Connect's preview off it answers `skipped` and writes
  nothing** (master_manifest.json and the window's undo stack untouched): the preview off is 2.5.
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


def _kick(lang, loaded):
    """Start Connect if it should run (P2.1 row 2.1.5); never fails the verb."""
    try:
        from app.connect import kick
        kick.kick(lang, loaded)
    except Exception:
        contract.log.exception("Connect wasn't started")


def _ensure_reader(lang, wait):
    """Connect's watermark before a write it must see (✅ G1.1-2): set once, the first time Connect is on."""
    from app.connect import library
    store = library.open_store(lang, role="register")
    if store is None:
        return
    with store:
        _store_write(lambda: library.ensure_reader(store), wait)


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
        record = json.loads(data.decode("utf-8"))
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
    if not args.backfill:
        _ensure_reader(lang, args.wait)      # the drop is logged, after the watermark
    done = _store_write(lambda: library_store.register_headless(lang, path, record, backfill=args.backfill,
                                                                  looks=library_store.PROBE_LOOKS), args.wait)
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
    if done.landed == "arrivals":
        store = library.open_store(lang, role="register")
        if store is not None:
            with store:
                rule = _store_write(lambda: rules.apply(store, done.file_id, record, loaded), args.wait)
                if rule:
                    out["rule"] = rule
                    out["tier"], out["position"] = store.place_of(done.file_id)
    if not (done.landed == "already" and done.pairing == "same"):
        _kick(lang, loaded)
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
                                                    source=args.source), args.wait)
        tier, position = store.place_of(args.file)
    if change is not None:
        _kick(lang, loaded)
    return {"file_id": args.file, "tier": tier, "position": position, "moved": change is not None,
            "source": args.source}


def finish_args(parser):
    _item_args(parser)


def finish(args):
    """Move one item to *Finished* (3.0): no known word and no card changes (✅ Q2-5, Q2-6). Held to 3.0 (✅ P2.1-1)."""
    from app.connect import library
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
        change = _store_write(lambda: library.finish(store, args.file, source=args.source), args.wait)
        tier, position = store.place_of(args.file)
    return {"file_id": args.file, "tier": tier, "position": position, "finished": change is not None,
            "source": args.source}


# --------------------------------------------------------------------------- #
# connect (P2.1: the inbox, once; the loop is P2.4's)
# --------------------------------------------------------------------------- #
def connect_args(parser):
    add_language(parser)
    parser.add_argument("--consume-only", action="store_true",
                        help="read the library's new placements into Connect's queue, then exit")


def connect(args):
    """Connect, one per install (its `connect` lock): a second one answers `skipped` at once. Started by `kick`."""
    loaded = settings()
    lang = language(args, loaded)
    if not loaded.get("connect_enabled"):
        return {"language": lang, "skipped": PREVIEW_OFF}
    if not args.consume_only:
        raise CliError("usage", "Connect's mining isn't built yet: run it with --consume-only.")
    require_set_up(lang)
    from app import locks
    from app.connect import inbox, kick, library
    try:
        held = locks.take(kick.LOCK, "Connect", wait=1.0)       # a kick's look holds it well under a millisecond
    except locks.Busy:
        return {"language": lang, "skipped": "already running"}
    with held:
        store = library.open_store(lang)
        if store is None:
            return {"language": lang, "skipped": "no library store"}
        with store:
            result = _store_write(lambda: inbox.consume(store, lang), 10.0)
    return {"language": lang, **result}

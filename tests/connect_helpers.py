"""Shared by P2.1's suites (register, place, finish, the inbox, Connect on demand, the placing rules, the start-up
notice): a library of real subtitles with its store built, hato-style drops and pairing records, under the test's own
root (`SURASURA_TEST_ROOT`). Titles and video paths are synthetic; the subtitles are the suite's real Japanese and
Chinese test files. P3.2 adds the stand-in hato-cli (`fake_hato`: hato 1.1.0 isn't released) and hato 1.1.0's records
(`hato_record`, `pairing_line`, `result_line`).
"""
import copy
import hashlib
import json
import os
import subprocess
import sys

from app import library_store
from tests import cli_helpers as h

RECORD = os.path.join(h.RESOURCES, "connect", "pairing_v1.json")
SUBTITLE = {"ja": ("ja", "phrases_sample.srt"), "zh": ("zh", "chinese_text_1.txt")}


def dirs(lang="ja"):
    return os.path.join(h.root(), "data", lang), os.path.join(h.root(), "User Files", lang)


def library(lang="ja", connect=True, arrivals=False, extra=3, **settings):
    """The suite's real files in NOW (plus `extra` more subtitles, so Chinese holds several too), settings (Connect on
    or off), the library store built from the folders and, for the 3.0 behaviour, its `arrivals_on` switch. Returns
    the data folder."""
    h.seed_library(lang, templates=False)
    for n in range(extra):
        drop(f"Notes {n + 1}.{lang}.srt", lang, folder="HighPriority")
    h.write_settings(target_language=lang, connect_enabled=connect, **settings)
    data_dir, user_files = dirs(lang)
    assert library_store.maintain(lang, data_dir, user_files, from_folders=True) == library_store.EXIT_DONE
    with store(lang) as s:          # 3.0 builds every library with New arrivals on (L3.1): off is the 2.x behaviour
        s.bookkeeping({"arrivals_on": 1 if arrivals else 0}, copy_carries=True)
    return data_dir


def store(lang="ja"):
    data_dir, user_files = dirs(lang)
    s = library_store.open_store(lang, data_dir, user_files)
    assert s is not None
    return s


def drop(name, lang="ja", folder=library_store.HATO_FOLDER):
    """A subtitle copied where hato copies it (`HighPriority/Hato/<name>`), as hato's file -> its path."""
    data_dir, _u = dirs(lang)
    target = os.path.join(data_dir, *folder.split("/"), name)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    sub_lang, sub_name = SUBTITLE[lang]
    with open(os.path.join(h.RESOURCES, sub_lang, sub_name), "rb") as f:
        data = f.read()
    with open(target, "wb") as f:
        f.write(data + f"\n{name}\n".encode("utf-8"))     # each copy its own bytes, as each episode's subtitle
    return target


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def record(path, video, lang="ja", show=None, **more):
    """hato's pairing record v1 for the library copy at `path`: the fixture with this file's sha256, a content key
    made from `video` (any text: tests need distinct videos, not real ones) and the show it names."""
    with open(RECORD, encoding="utf-8") as f:
        rec = json.load(f)
    rec = copy.deepcopy(rec)
    rec.update({"language": lang, "library_path": path, "subtitle_sha256": sha256(path),
                "content_key": "v1-" + hashlib.sha256(video.encode("utf-8")).hexdigest()})
    if show is not None:
        rec["show"] = show
    rec.update(more)
    return rec


def write_record(rec, name="record.json"):
    path = os.path.join(h.root(), name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    return path


def register_stdin(data, *args, env=None):
    """`surasura-cli register --pairing -` as hato calls it: the record's bytes on stdin -> (exit code, JSON lines)."""
    proc = subprocess.run([sys.executable, "-m", "app.cli", "register", "--pairing", "-", *args], input=data,
                          cwd=os.path.dirname(h.root()), env=h.child_env(**(env or {})), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=180)
    return proc.returncode, [json.loads(line) for line in proc.stdout.decode("ascii").splitlines()]


def events(s, after=0):
    """(item_id, kind, by) of the placement log after `after`."""
    return [tuple(r) for r in s.conn.execute("SELECT item_id, kind, by FROM placement_log WHERE id > ? ORDER BY id",
                                             (after,))]


def store_state(lang="ja"):
    """What a store write would move: every meta value, and the items, pairings and log rows counted."""
    with store(lang) as s:
        count = lambda table: s.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]     # noqa: E731
        return s.meta(), count("items"), count("pairings"), count("placement_log")


def snapshot():
    """Every file under the root a call must not write: all but the command line's own logs and locks and SQLite's
    side files — (size, modified time, sha256) each."""
    seen = {}
    for folder, _dirs, files in os.walk(h.root()):
        rel = os.path.relpath(folder, h.root())
        if rel.split(os.sep)[:2] in (["local", "logs"], ["local", "locks"]):
            continue
        for name in files:
            if name.endswith(("-wal", "-shm")):
                continue
            path = os.path.join(folder, name)
            st = os.stat(path)
            seen[os.path.relpath(path, h.root())] = (st.st_size, st.st_mtime_ns, sha256(path))
    return seen


# --------------------------------------------------------------------------- #
# The stand-in hato-cli (P3.2 row 3.2.5: hato 1.1.0 isn't released) and its records
# --------------------------------------------------------------------------- #
HATO_VERSION = "1.1.0"
REFERENCES = ("text-track", "picture-track", "speech-mask")     # tsubasa's three kinds (09-hato-layer v2, timing)

# The stand-in itself, written beside its plan: prints the plan's NDJSON as `hato-cli pairings --json` does (09-hato-layer
# v2 §4) after `delay` seconds, `pad` bytes of other lines first, exits with `exit`; each call recorded with its argv and
# whether its stdin was closed (a stdin left open would block it here: the caller's timeout says so).
_STAND_IN = r'''import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "plan.json"), encoding="utf-8") as f:
    plan = json.load(f)
closed = sys.stdin is None or sys.stdin.read() == ""
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin_closed": closed}) + "\n")
time.sleep(plan["delay"])
out = sys.stdout.buffer
pad = plan["pad"]
while pad > 0:
    line = b'{"type":"note","pad":"' + b"x" * min(pad, 1 << 20) + b'"}\n'
    out.write(line)
    pad -= len(line)
for line in plan["lines"] + ([plan["result"]] if plan["result"] is not None else []):
    out.write((line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)).encode("utf-8") + b"\n")
out.flush()
sys.exit(plan["exit"])
'''


class FakeHato:
    """The stand-in's command line (`cli`, what hato.json names), its plan and the calls it was given."""

    def __init__(self, folder, cli):
        self.folder, self.cli = folder, cli

    def plan(self, lines, result, exit=0, delay=0, pad=0):
        """What the next call prints: `lines` (dicts as JSON, strings as they are), then `result` (None: no result
        line), after `delay` seconds and `pad` bytes of other lines; it exits with `exit`."""
        with open(os.path.join(self.folder, "plan.json"), "w", encoding="utf-8") as f:
            json.dump({"lines": list(lines), "result": result, "exit": exit, "delay": delay, "pad": pad}, f,
                      ensure_ascii=False)

    def entry(self, **fields):
        """hato.json in the shared tools folder (09-hato-layer v2, hato's own entry), `fields` over hato 1.1.0's."""
        from app import tools_entry
        entry = {"schema": 1, "tool": "hato", "name": "hato", "version": HATO_VERSION, "cli": self.cli, "app": None,
                 "contract": 1, "verbs": ["pairings"], "updated": "2026-10-12T09:00:00Z"}
        entry.update(fields)
        folder = tools_entry.tools_dir()
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "hato.json"), "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)

    def calls(self):
        path = os.path.join(self.folder, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


def fake_hato(tmp, lines, result, exit=0, delay=0):
    """The stand-in hato-cli under `tmp` (a Python script, run through a .cmd on Windows as an installed command line
    is) and its hato.json in the shared tools folder — only ever a temp one (HOUSEKI_TOOLS_DIR) -> `FakeHato`."""
    assert os.environ.get("HOUSEKI_TOOLS_DIR"), "the stand-in's hato.json goes only into a temp tools folder"
    folder = os.path.join(str(tmp), "hato-cli")
    os.makedirs(folder, exist_ok=True)
    script = os.path.join(folder, "hato_cli.py")
    with open(script, "w", encoding="utf-8") as f:
        if sys.platform != "win32":
            f.write(f"#!{sys.executable}\n")
        f.write(_STAND_IN)
    if sys.platform == "win32":
        cli = os.path.join(folder, "hato-cli.cmd")
        with open(cli, "w", encoding="ascii", newline="\r\n") as f:
            f.write(f'@"{sys.executable}" "{script}" %*\n@exit /b %errorlevel%\n')
    else:
        cli = script
        os.chmod(script, 0o755)
    hato = FakeHato(folder, cli)
    hato.plan(lines, result, exit=exit, delay=delay)
    hato.entry()
    return hato


def video(name, size=None):
    """A synthetic video under the test root (its bytes its own: the name's hash repeated; over 128 KiB unless
    `size` says, so its content key reads head and tail) -> its path."""
    folder = os.path.join(h.root(), "videos")
    os.makedirs(folder, exist_ok=True)
    seed = hashlib.sha256(name.encode("utf-8")).digest()
    size = size if size is not None else 140000 + seed[0]
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write((seed * (size // len(seed) + 1))[:size])
    return path


def hato_record(path, episode, lang="ja", verdict="timed", reference="text-track", title="Example Show", **more):
    """A valid pairing record v1 as hato 1.1.0 writes it (09-hato-layer v2 §1, §1.2) for the library copy at `path`:
    a synthetic video of its own (`video`), keyed by `videos.content_key` as hato's `video_hash` keys it, the copy's
    sha256, and what goes with `verdict` (`timed` · `forced` · `extracted` · `untimed`)."""
    from app.connect import videos
    movie = video(f"{title} - {episode:02d}.mkv")
    ext = os.path.splitext(path)[1]
    timed = verdict in ("timed", "forced")
    rec = {
        "schema": 1,
        "content_key": videos.content_key(movie),
        "producer": "hato",
        "producer_version": HATO_VERSION,
        "language": lang,
        "video_path": movie,
        "video_size": os.path.getsize(movie),
        "subtitle_path": f"{os.path.splitext(movie)[0]}.{'jpn' if verdict == 'untimed' else lang}{ext}",
        "library_path": path,
        "subtitle_sha256": sha256(path),
        "verdict": verdict,
        "untimed_tier": "same" if verdict == "untimed" else None,
        "picked_by": "person" if verdict == "forced" else "hato",
        "timing": {"outcome": "REFUSED" if verdict == "forced" else "CONFIDENT",
                   "match_rate": 0.42 if verdict == "forced" else 0.91, "offset_s": -1.24, "segments": 1,
                   "reference": reference, "tsubasa_version": "0.1.10"} if timed else None,
        "show": {"title": title, "season": 1, "episode": episode, "movie": False},
        "jimaku_entry_id": None if verdict == "extracted" else 11407,
        "anilist_id": 154587,
        "tmdb_id": "tv:209867",
        "subtitle_source": {"provider": "video-track", "file_name": "日本語"} if verdict == "extracted" else
        {"provider": "jimaku", "file_name": f"[Example] {title} {episode:02d}{ext}"},
        "paired_at": f"2026-10-{1 + episode % 9:02d}T11:42:07Z",
    }
    assert rec["content_key"] is not None
    rec.update(more)
    return rec


def pairing_line(record, registered=None):
    """One line of `hato pairings --json`: the record with its `type` first and hato's `registered` mark last."""
    return {"type": "pairing", **record, "registered": registered}


def result_line(count, complete_since):
    return {"type": "result", "ok": True, "count": count, "complete_since": complete_since}


def iso(seconds):
    """A POSIX time as hato writes its times (ISO-8601 UTC, `Z`)."""
    import datetime
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

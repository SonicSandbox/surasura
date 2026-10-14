"""The end-to-end proof on the stand-in hato (P3.2 row 3.2.6; 09-hato-layer v2 §2–§4): Surasura and hato find each
other through the shared tools folder, and a hato drop and hato's back-fill go through Surasura's command line as hato
1.1.0 will make them — from source, in the test's own root, through real processes.

The story, in the order a person meets it:
  1. any surasura-cli call (`status --root R`) writes surasura.json: the command line to call, `status` only (Connect's
     preview off), and the drop folder of each language Surasura is set up for; hato, reading it, copies an episode
     and doesn't register it;
  2. the preview switched on (the watermark, then settings.json, as the window's switch does): the next call lists
     `register`, so hato starts registering its drops;
  3. hato reads surasura.json, copies a subtitle into `drop_folders["ja"]\\<series>\\` and pipes its record v1 to the
     command line surasura.json names (`register --lang ja --pairing - --wait 10`): the drop is at the top of NOW with
     its pairing, logged for Connect;
  4. the back-fill (the stand-in hato-cli's `pairings --json`, run as a real program) over the 60 old files in hato's
     flat folder and the copy made while the preview was off: each paired by its path, none logging an event —
     Connect's next read queues hato's live drop and none of the back-fill's.

What a wrong answer would cost:
  * `register` listed with the preview off: hato registers into a library whose user never switched Connect on (2.5
    must stay byte for byte); not listed with it on: hato only copies, and no drop is ever mined;
  * a drop folder that isn't the one the store treats as hato's: hato's files never reach the library, or land outside
    NOW's top;
  * a back-fill that logged an event: every episode in hato's folder mined at once, the flood Connect's watermark is
    there to stop.

Real Japanese and Chinese subtitles from tests/Test Resources (an .ass with a BOM and CRLF; each flat copy its own
bytes), synthetic titles and videos, the test's own root and its own shared tools folder (HOUSEKI_TOOLS_DIR): the real
one is never read or written."""
import json
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

from app import __version__, library_store, settings_manager, tools_entry
from app.cli.contract import CONTRACT
from app.connect import hato, inbox, library
from app.connect.ledger import Ledger
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

DAY = 86400.0
VERDICTS = ("timed", "timed", "forced", "extracted", "untimed")     # what hato 1.1.0 sends (09-hato-layer v2 §1.2)
SERIES = {"ja": "架空の番組", "zh": "夜市探访"}                       # synthetic titles: hato's per-series folders
SUBTITLE = {"ja": "library_episode.ass", "zh": "night_market.srt"}   # tests/Test Resources/<lang>/


@pytest.fixture(autouse=True)
def tools(tmp_path, monkeypatch):
    """The test's own shared tools folder, and the command line this source checkout advertises there (a wrapper for
    `python -m app.cli`, as an install's surasura-cli.exe): both inherited by every process the test starts."""
    folder = tmp_path / "houseki-tools"
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(folder))
    monkeypatch.setenv("SURASURA_TOOLS_CLI", _cli_wrapper(tmp_path))
    return folder


def _cli_wrapper(tmp_path):
    """`python -m app.cli` as one program (a .cmd on Windows, as hato would start an installed command line) -> its
    path. Why: hato calls what surasura.json's `cli` names, so the proof calls it too."""
    folder = tmp_path / "surasura"
    folder.mkdir()
    if sys.platform == "win32":
        path = folder / "surasura-cli.cmd"
        with open(path, "w", encoding="ascii", newline="\r\n") as f:
            f.write(f'@"{sys.executable}" -m app.cli %*\n@exit /b %errorlevel%\n')
    else:
        path = folder / "surasura-cli"
        path.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m app.cli "$@"\n', encoding="utf-8")
        os.chmod(path, 0o755)
    return str(path)


def _status(*args):
    """A surasura-cli call as a person or a tool makes it (read-only `status`, under `--root`): every call refreshes
    surasura.json before its verb."""
    code, lines = h.run_cli("status", "--root", h.root(), *args)
    assert code == 0 and h.answer(lines)["type"] == "result", lines


def _entry(tools):
    """surasura.json as written, its `updated` checked (ISO-8601 UTC) and set aside."""
    with open(tools / "surasura.json", encoding="utf-8") as f:
        entry = json.load(f)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", entry.pop("updated"))
    return entry


def _expected(verbs, langs):
    """09-hato-layer v2 §3: a source checkout's entry (no window exe), each set-up language's drop folder: the store's
    HATO_FOLDER under the root's data folder, absolute."""
    return {"schema": 1, "tool": "surasura", "name": "Surasura", "version": __version__,
            "cli": os.environ["SURASURA_TOOLS_CLI"], "app": None, "contract": CONTRACT, "verbs": verbs,
            "drop_folders": {lang: os.path.normpath(os.path.join(h.root(), "data", lang,
                                                                 *library_store.HATO_FOLDER.split("/")))
                             for lang in langs}}


def _hato_finds_surasura():
    """surasura.json as hato reads it (09-hato-layer v2 §3: the whole file, parsed; absent when its `cli` is gone or it
    is newer than hato speaks — the rule Surasura's own reader keeps)."""
    found = tools_entry.read("surasura")
    assert found is not None, "hato finds Surasura"
    return found


def _hato_copies(drop_folder, lang, name, source=None):
    """hato's copy of the subtitle it wrote beside the video (`source`, a real one from tests/Test Resources/<lang>),
    into its per-series folder under the drop folder surasura.json names (copied first: `register` stats the file)
    -> its path."""
    target = os.path.join(drop_folder, SERIES[lang], name)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(os.path.join(h.RESOURCES, lang, source or SUBTITLE[lang]), target)
    return target


def _hato_registers(cli, lang, record):
    """hato's hand-over (09-hato-layer v2 §2): its record v1 as UTF-8 JSON on stdin, never on the command line, to the
    command line surasura.json names -> (exit code, the answer's JSON lines)."""
    proc = subprocess.run([cli, "register", "--lang", lang, "--pairing", "-", "--wait", "10"],
                          input=json.dumps(record, ensure_ascii=False).encode("utf-8"),
                          cwd=os.path.dirname(h.root()), env=h.child_env(), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=180)
    return proc.returncode, [json.loads(line) for line in proc.stdout.decode("ascii").splitlines()]


def _at_the_top(record, file_id):
    """09-hato-layer v2 §2's answer for a new drop with the preview on: every field, and no other (no `verb`, no
    `skipped`, no `rule`)."""
    return {"type": "result", "contract": CONTRACT, "ok": True, "file_id": file_id, "landed": "now-top",
            "tier": "now", "position": 1, "pairing": "new", "content_key": record["content_key"]}


def _old(path, days=10):
    """A file hato copied long ago (before its pairings were complete): last changed `days` before now."""
    at = time.time() - days * DAY
    os.utime(path, (at, at))
    return path


def test_hato_finds_surasura_hands_over_a_drop_and_its_back_fill_pairs_sixty_old_files_mining_none(tmp_path, tools):
    # The library as a 2.5 user has it: 60 files hato copied into its flat folder before 1.1.0, synced by the window
    # long ago (items in NOW, no pairing), and Connect's preview off. No surasura.json yet.
    flat = [_old(c.drop(f"Example Show - {n:02d}.ja.srt")) for n in range(1, 61)]
    c.library(connect=False)
    assert not (tools / "surasura.json").exists()

    # 1. Any surasura-cli call writes surasura.json: hato learns where Surasura's command line is and where to drop,
    #    and — the preview off — not to register (2.5's library is never written by hato).
    _status()
    assert _entry(tools) == _expected(["status"], ["ja"])

    # hato, integrated while the preview is off, copies its next episode into its series folder and doesn't register
    # (`register` isn't listed): a file on disk the window hasn't synced, no item, no pairing — the back-fill's to pair.
    found = _hato_finds_surasura()
    assert found["verbs"] == ["status"]
    unsynced = _hato_copies(found["drop_folders"]["ja"], "ja", f"{SERIES['ja']} - 01.ja.ass", "tv_captions.ass")

    # 2. The preview switched on as the window's switch does it: Connect's watermark first, then settings.json. Nothing
    #    in this process rewrites surasura.json; the next call does, and lists `register`.
    with c.store() as s:
        library.switch_on(s)
    settings_manager.save_keys({"connect_enabled": True}, strict=True)
    assert _entry(tools)["verbs"] == ["status"]
    _status()
    assert _entry(tools) == _expected(["status", "register"], ["ja"])

    # 3. hato's side: integrated (surasura.json there, Japanese named), it copies its file into the series folder under
    #    the drop folder and registers only because `register` is listed. Its record goes on stdin.
    found = _hato_finds_surasura()
    assert "register" in found["verbs"] and set(found["drop_folders"]) == {"ja"}
    path = _hato_copies(found["drop_folders"]["ja"], "ja", f"{SERIES['ja']} - 02.ja.ass")
    record = c.hato_record(path, 2, title=SERIES["ja"])
    entry_file = tools / "surasura.json"
    written = entry_file.read_bytes(), os.stat(entry_file).st_mtime_ns
    code, lines = _hato_registers(found["cli"], "ja", record)
    assert code == 0, lines
    (answer,) = lines
    drop = answer["file_id"]
    assert answer == _at_the_top(record, drop) and isinstance(drop, int), answer
    assert (entry_file.read_bytes(), os.stat(entry_file).st_mtime_ns) == written, "nothing changed: not rewritten"
    with c.store() as s:
        assert s.ids("now")[0] == drop, "the drop at the top of NOW"
        stored = s.conn.execute("SELECT pairing FROM pairings WHERE item_id = ?", (drop,)).fetchone()
        assert json.loads(stored[0]) == record, "hato's record kept as it sent it"
        assert (drop, "entered_mine_line", "hato") in c.events(s), "logged for Connect, as hato's"
        assert inbox.pending(s)
        seq = library.log_seq(s)

    # 4. The back-fill the switch-on runs (here after hato's live drop, so hato's answer holds that pairing too, marked
    #    registered): the stand-in hato-cli started as a real program; the 60 old files paired by their paths, the
    #    preview-off copy added and paired, the live drop's line `same`; no file left unpaired (the 60 are older than
    #    `complete_since` and each is named).
    lines = [c.pairing_line(c.hato_record(p, n, verdict=VERDICTS[n % len(VERDICTS)], reference=c.REFERENCES[n % 3]))
             for n, p in enumerate(flat, 1)]
    lines.append(c.pairing_line(c.hato_record(unsynced, 1, title=SERIES["ja"])))
    lines.append(c.pairing_line(record, {"file_id": drop, "at": "2026-10-12T09:00:00Z"}))
    fake = c.fake_hato(tmp_path, lines, c.result_line(62, c.iso(time.time() - DAY)))
    out = hato.backfill("ja", settings_manager.load_settings(strict=True))
    assert (out["hato"], out["new"], out["same"], out["replaced"], out["refused"], out["unpaired"], out["stopped"],
            out["need"]) == (hato.ASKED, 61, 1, 0, [], [], None, None), out
    assert fake.calls() == [{"argv": ["pairings", "--json", "--lang", "ja"], "stdin_closed": True}]
    with c.store() as s:
        paired = {json.loads(p)["library_path"] for (p,) in s.conn.execute("SELECT pairing FROM pairings")}
        assert paired == set(flat) | {unsynced, path}, "the 60 paired by path, the preview-off copy, the live drop"
        # No back-filled item logs an event (the 60 are `already`; the added copy would be `entered_mine_line`, work
        # for Connect): only the items the added copy pushes below the top 20 are logged as having left it.
        assert {kind for _item, kind, _by in c.events(s, after=seq)} <= {"left_mine_line"}

    # Connect's next read: hato's live drop is work (it entered the top 20 after the watermark), none of the back-fill.
    with c.store() as s, Ledger() as ledger:
        assert inbox.consume(s, "ja", ledger)["queued"] == [drop]
        assert [job["item_id"] for job in ledger.jobs("ja")] == [drop], "one job: the live drop's, none back-filled"
    assert sorted(os.listdir(tools)) == ["hato.json", "surasura.json"], "each tool's own entry, no tmp left"


def test_a_chinese_drop_goes_to_chinese_drop_folder_and_lands_at_the_top_of_its_now(tools):
    """Chinese alone set up, the preview on: surasura.json names Chinese's drop folder only (no Japanese hand-off), and
    hato's Chinese drop there registers into the Chinese library at the top of NOW."""
    c.library("zh")
    _status("--lang", "zh")
    assert _entry(tools) == _expected(["status", "register"], ["zh"])
    found = _hato_finds_surasura()
    path = _hato_copies(found["drop_folders"]["zh"], "zh", f"{SERIES['zh']} - 01.zh.srt")
    record = c.hato_record(path, 1, lang="zh", title=SERIES["zh"])
    code, lines = _hato_registers(found["cli"], "zh", record)
    assert code == 0, lines
    (answer,) = lines
    assert answer == _at_the_top(record, answer["file_id"]), answer
    with c.store("zh") as s:
        assert s.ids("now")[0] == answer["file_id"]
        assert [json.loads(p)["library_path"] for (p,) in s.conn.execute("SELECT pairing FROM pairings")] == [path]
        assert (answer["file_id"], "entered_mine_line", "hato") in c.events(s)

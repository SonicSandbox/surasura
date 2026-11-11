"""Piyo's diagnose (`app/diagnose.py`): what Send report would show about this PC, short, for the learner's AI —
read through the report's own collectors and its scrub, and checked by the scrub's own guard before it goes.

What a wrong answer would cost: the learner's Windows name, PC, home folder, Anki profile or email in what their AI
reads (and its company keeps); a file, a folder, a setting, Anki or a lock changed by "just looking"; whole logs in the
answer (thousands of lines for one question); a part that can't be read stopping every other; or a failed part that
never says which word Anki refused. Real Japanese words and subtitles, a made-up person (tests/scrub_probe.py).
"""
import json
import os

import pytest

from app import anki_connect, diagnose, path_utils, report, scrub
from app.connect import ledger as book
from app.connect import runner
from tests import cli_helpers as h
from tests import connect_helpers as ch
from tests import scrub_probe as probe_person

SAID = "AnkiConnect error in 'addNotes': ['cannot create note for unknown reason']"
SENTENCE = "改札を抜けると、約束の場所に彼女が立っていた。"


@pytest.fixture(autouse=True)
def _fresh_identity():
    scrub.reset()
    yield
    scrub.reset()


@pytest.fixture
def no_anki(monkeypatch):
    """AnkiConnect stood in for: never the real one (the asks it was given, by address)."""
    asked = []

    def probe(url, required=(), timeout=5):
        asked.append(url)
        return {"ok": False, "version": None, "missing": [], "error": "Anki isn't open"}
    monkeypatch.setattr(anki_connect, "probe", probe)
    return asked


def _log(lines, name="app_debug_log.txt", newline="\n"):
    folder = os.path.join(path_utils.get_local_data_path(), "logs")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "a", encoding="utf-8", newline="") as f:
        f.write(newline.join(lines) + newline)


def _failed_job(word="約束"):
    """A failed part of item 33: three words, one made, and the one Anki Miner refused alone, with its reason."""
    with book.Ledger() as led:
        led.conn.execute("INSERT INTO jobs (language, item_id, state, created_at, updated_at, kind, picked) VALUES "
                         "('ja', 33, 'failed', '2026-11-09T20:00:00Z', '2026-11-09T20:06:00Z', 'mine', ?)",
                         (json.dumps({"words": [{"word": w, "reading": r} for w, r in
                                                (("約束", "やくそく"), ("改札", "かいさつ"), ("彼女", "かのじょ"))]},
                                     ensure_ascii=False),))
        job = led.conn.execute("SELECT MAX(id) FROM jobs").fetchone()[0]
        for w, r, outcome in (("約束", "やくそく", "uncertain"), ("改札", "かいさつ", "made"),
                              ("彼女", "かのじょ", "uncertain")):
            led.conn.execute("INSERT INTO outcomes (job_id, word, reading, orth, sentence, outcome, attempt) VALUES "
                             "(?, ?, ?, ?, ?, ?, 2)", (job, w, r, w, SENTENCE, outcome))
        led.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)",
                         (f"{runner.ALONE}{job}", json.dumps({"said": SAID, "words": [word]}, ensure_ascii=False)))
    return job


@pytest.fixture
def world(tmp_path, monkeypatch, no_anki):
    """The probe person's PC: a real library (the suite's Japanese subtitles), Connect on with a failed part, logs
    that name them, settings with a key in them."""
    p = probe_person.make(tmp_path, monkeypatch)
    ch.library("ja", connect=True, anki_sync_auto=True, koe_api_key="AIza-not-a-real-key",
               anki_export_folder=os.path.join(p.home, "Anki exports"))          # a setting naming the person
    job = _failed_job()
    video = os.path.join(p.home, "Videos", "葬送のフリーレン", "第3話.mkv")
    _log([f"2026-11-11 09:00:00.001 [12] window: opened {video}",
          f"2026-11-11 09:00:01.002 [12] connect: job {job} failed: Anki Miner stopped on {video}",
          f"2026-11-11 09:00:02.003 [12] ERROR mail to {probe_person.EMAIL} couldn't be sent",
          "2026-11-11 09:00:03.004 [12] connect: waiting for Anki to open",
          "2026-11-11 09:00:03.005 [12] connect: waiting for Anki to open",          # said once
          "Traceback (most recent call last):",
          f'  File "{p.home}\\scripts\\tool.py", line 2, in run',
          f"FileNotFoundError: {video}"], newline="\r\n")                          # Windows line ends
    return p, job


def _strings_in(text, p):
    return [s for s in p.strings if s and s.casefold() in text.casefold()]


# --- what it shows, through the report's collection and scrub ---------------------------------------------------- #
def test_every_part_is_the_reports_own_reading_with_the_learners_names_written_as_placeholders(world):
    p, job = world
    out = diagnose.diagnose(language="ja")
    assert set(out) == {"surasura", *diagnose.AREAS}
    text = json.dumps(out, ensure_ascii=False)
    assert _strings_in(text, p) == []                                    # no name in any part
    assert not scrub.identity(fresh=True).found(text)                    # nor in any form the guard knows
    assert "<email>" in text and "<file .mkv>" in text                   # (written as placeholders, not dropped)
    # Connect: the failed part's refused word and Anki Miner's reason; never its sentence, reading or other words
    failed = out["connect"]["ja"]["failed_parts"]
    # (its word count is left out as the report leaves it: one rule for both)
    assert failed == [{"job": job, "made": 1, "refused_words": ["約束"], "anki_miner_said": SAID}]
    assert SENTENCE not in text and "やくそく" not in text and "改札" not in text
    assert out["connect"]["on"] is True and out["connect"]["ja"]["jobs_by_state"] == {"failed": 1}
    # settings as the report keeps them: a key blanked, never shown
    assert "AIza" not in text
    assert out["anki"]["settings"]["anki_sync_auto"] is True
    assert "<you>" in out["anki"]["settings"]["anki_export_folder"]       # every string scrubbed, not only logs
    # the library's counts, by the names the learner sees (never HighPriority / NOW)
    assert out["library"]["items"].get("Current", 0) >= 4 and "HighPriority" not in text


def test_what_the_learner_watched_never_reaches_their_ai(world):
    # the answer goes to the learner's AI: a log line says what happened, never to which show, file or line
    out = diagnose.diagnose(language="ja")
    text = json.dumps(out, ensure_ascii=False)
    for content in ("葬送のフリーレン", "第3話", "Videos", "scripts", "tool.py"):
        assert content not in text, content
    log = out["app"]["log"]
    assert log[0] == "app_debug_log.txt | FileNotFoundError: <file .mkv>"
    assert any("Anki Miner stopped on <file .mkv>" in line for line in log)
    # ... while the refused word, the report's one exception, stays (Connect's own record)
    assert out["connect"]["ja"]["failed_parts"][0]["refused_words"] == ["約束"]


def test_a_quoted_name_and_a_command_line_event_lose_their_content(world):
    _log(['2026-11-11 12:00:00.000 [12] covers: AniList refused "Bocchi the Rock!" (HTTP 429)',
          "2026-11-11 12:00:00.500 [12] connect: waiting for 葬送のフリーレン to download"], name="cli.log")
    _log([json.dumps({"time": "2026-11-11T12:00:01Z", "verb": "connect", "exit": 1, "code": "failed",
                      "message": "Anki Miner failed on 「ぼっち・ざ・ろっく！」 ep 3"}, ensure_ascii=False)],
         name="cli-events.jsonl")
    lines = diagnose.log_lines()
    text = "\n".join(lines)
    assert "Bocchi" not in text and "ぼっち" not in text and "フリーレン" not in text
    assert "cli.log | 2026-11-11 12:00:00.500 [12] connect: waiting for … to download" in lines
    assert 'cli.log | 2026-11-11 12:00:00.000 [12] covers: AniList refused "…" (HTTP 429)' in lines
    assert "cli-events.jsonl | 2026-11-11T12:00:01Z connect failed Anki Miner failed on 「…」 ep 3" in lines


def test_the_log_is_only_its_newest_lines_that_matter_each_once_and_short(world):
    out = diagnose.diagnose("app", "ja")["app"]["log"]
    assert out[0].startswith("app_debug_log.txt | FileNotFoundError: ")          # the newest first
    assert sum("waiting for Anki to open" in line for line in out) == 1          # a repeat said once
    assert not any("Traceback (most recent" in line or "File \"" in line for line in out)    # its frames are noise
    assert not any("window: opened" in line for line in out)                     # a line that says nothing wrong
    assert all(not line.endswith("\r") for line in out)


def test_a_short_logs_first_line_counts_too(world):
    # read whole (shorter than LOG_READ): its first line is a whole line, never the cut-off part of one
    _log(["2026-11-11 11:00:00.000 [40] generate: failed to read 第3話.ja.srt"], name="generate.log")
    assert any(line.startswith("generate.log | ") and "failed to read" in line for line in diagnose.log_lines())


def test_a_long_log_is_cut_to_its_newest_few_lines(world):
    _log([f"2026-11-11 10:{n // 60:02d}:{n % 60:02d}.000 [12] store: refused move {n} " + "あ" * 300
          for n in range(200)], name="cli.log")
    lines = diagnose.log_lines()
    assert len(lines) <= diagnose.LOG_LINES
    from_cli = [line for line in lines if line.startswith("cli.log | ")]
    assert len(from_cli) == diagnose.LOG_LINES_PER_FILE and "move 199 " in from_cli[0]
    assert all(len(line.split(" | ", 1)[1]) <= diagnose.LINE_MAX for line in from_cli)


def test_an_area_is_its_part_only_and_anki_is_asked_only_when_its_part_is(world, no_anki):
    full = diagnose.diagnose(language="ja")
    assert "anki_open" not in full["anki"] and no_anki == []             # all of it: Anki never asked
    out = diagnose.diagnose("anki", "ja")
    assert set(out) == {"surasura", "anki"} and out["anki"]["anki_open"] is False
    assert len(no_anki) == 1 and no_anki[0].startswith(("http://127.0.0.1", "http://localhost"))
    assert set(diagnose.diagnose("hato", "ja")) == {"surasura", "hato"}
    with pytest.raises(ValueError):
        diagnose.diagnose("anki-miner", "ja")


def test_a_part_the_scrub_would_miss_is_left_out_whole(world, monkeypatch):
    # the guard reads every part again: a name the scrub let through (here: no scrub at all) leaves that part out
    monkeypatch.setattr(scrub.Identity, "scrub", lambda self, s: s)
    out = diagnose.diagnose(language="ja")
    assert out["app"] == diagnose.LEFT                                  # its log names the person
    assert _strings_in(json.dumps(out, ensure_ascii=False), world[0]) == []


def test_a_part_that_cant_be_read_says_why_and_the_rest_still_answer(world, monkeypatch):
    def broken(*_a):
        raise OSError(f"the ledger at {world[0].home} is locked")
    monkeypatch.setitem(diagnose.PARTS, "connect", broken)
    out = diagnose.diagnose(language="ja")
    assert out["connect"]["unreadable"] == "OSError: the ledger at <folder> is locked"      # never the home folder
    assert out["library"]["items"] and out["hato"] == {"found": False}


# --- read only ---------------------------------------------------------------------------------------------------- #
def _everything(*roots):
    """Every folder and file under `roots`: its size and time (a folder: that it is there). SQLite's own -shm / -wal
    beside a database are left aside: a `mode=ro` reader of a WAL database keeps its wal-index there (the report and
    `surasura-cli status` read the same way); the database itself is compared."""
    seen = {}
    for root in roots:
        for folder, dirs, files in os.walk(root):
            seen[folder] = "dir"
            for name in files:
                if name.endswith(("-shm", "-wal")):
                    continue
                st = os.stat(os.path.join(folder, name))
                seen[os.path.join(folder, name)] = (st.st_size, st.st_mtime_ns)
    return seen


def test_it_writes_nothing_anywhere(world, tmp_path):
    p, _job = world
    settings_path = path_utils.get_settings_path()
    before = _everything(h.root(), p.home, str(tmp_path))
    with open(settings_path, "rb") as f:
        settings_bytes = f.read()
    for area in (None,) + diagnose.AREAS:
        diagnose.diagnose(area, "ja")
    assert _everything(h.root(), p.home, str(tmp_path)) == before       # no file, no folder, no time changed
    with open(settings_path, "rb") as f:
        assert f.read() == settings_bytes


def test_nothing_set_up_yet_says_so_plainly(no_anki):
    out = diagnose.diagnose(language="ja")
    assert out["library"] == {"store": "none yet"}
    assert out["hato"] == {"found": False}
    assert out["connect"]["ja"]["state"] == "idle" and "failed_parts" not in out["connect"]["ja"]
    assert "log" not in out["app"]                                       # no log yet: no lines, no empty list
    assert out["surasura"]["version"] == report.build()["version"]


def test_chinese_reads_its_own_library(no_anki):
    ch.library("zh", connect=False)
    out = diagnose.diagnose("library", "zh")
    assert out["library"]["items"].get("Current", 0) >= 1
    assert diagnose.diagnose("library", "ja")["library"] == {"store": "none yet"}    # never the other language's

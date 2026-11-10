"""hato's back-fill: the gaps the P3.2 mutant pass found (research/mutants/JUDGED-P3.2.md) — planted bugs in
app/connect/hato.py that test_hato_backfill.py let through. Each test names its mutant.

Real Japanese subtitles from tests/Test Resources (each copy its own bytes, `connect_helpers.drop`), synthetic titles
and videos, the test's own root and its own shared tools folder (HOUSEKI_TOOLS_DIR); the stand-in hato-cli where a
real program is started, `run=` where only the answer's bytes matter."""
import datetime
import json
import logging
import os
import subprocess
import sys
import time

import pytest

from app import settings_manager
from app.cli import contract
from app.connect import hato
from app.connect import ledger as book
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

DAY = 86400.0


@pytest.fixture(autouse=True)
def tools(tmp_path, monkeypatch):
    """Every test's own shared tools folder: the real one is never read or written."""
    folder = tmp_path / "houseki-tools"
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(folder))
    return folder


def _settings():
    return settings_manager.load_settings(strict=True)


def _switched_on(lang="ja"):
    from app.connect import library
    with c.store(lang) as s:
        library.switch_on(s)


def _lines(paths, start=1, title="Example Show"):
    return [c.pairing_line(c.hato_record(path, n, title=title)) for n, path in enumerate(paths, start)]


def _answer(lines, result):
    """hato's answer as bytes: one JSON line each, as `hato pairings --json` prints them."""
    return b"".join(json.dumps(x, ensure_ascii=False).encode("utf-8") + b"\n" for x in list(lines) + [result])


def _old(path, days=10):
    at = time.time() - days * DAY
    os.utime(path, (at, at))
    return path


def _log():
    path = os.path.join(h.root(), "local", "logs", hato.LOG_FILE)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def _one_line(tmp_path, **record):
    """One pairing line for a library copy of a real Japanese subtitle (no store needed: `pairings` only parses)."""
    path = c.drop("Example Show - 01.ja.srt")
    return c.pairing_line(c.hato_record(path, 1, **record))


def _child(code):
    """A real program for `_run` to start: this Python running `code`."""
    return [sys.executable, "-c", code]


# --- the call itself ----------------------------------------------------------------------------------------------

def test_a_stopped_hato_is_stopped_with_every_process_it_started(monkeypatch):
    """P3.2-B27. hato installed as a .cmd starts its own python: stopping only the .cmd's process leaves that child
    running (and holding the pipe). On Windows the stop is `taskkill /T` — the whole tree."""
    seen = []
    monkeypatch.setattr(hato.sys, "platform", "win32")
    monkeypatch.setattr(hato.subprocess, "run", lambda argv, **kw: seen.append(argv))

    class Proc:
        pid = 4242

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 1
    hato._stop(Proc())
    assert seen and seen[0][0] == "taskkill" and "/T" in seen[0] and seen[0][-1] == "4242"


def test_the_callers_timeout_is_the_one_a_silent_hato_is_stopped_at():
    """P3.2-B28. A hato that never answers is stopped at the timeout the caller hands `_run` (1 s here), not at the
    module's 60 s."""
    t0 = time.monotonic()
    with pytest.raises(hato.Unavailable) as e:
        hato._run(_child("import time; time.sleep(20)"), 1.0)
    assert time.monotonic() - t0 < 10, "stopped near its own 1 s"
    assert "within 1 s" in e.value.reason


def test_an_answer_that_reaches_the_limit_exactly_is_read_on_and_stopped_not_waited_on(monkeypatch):
    """P3.2-B29. The reader stops only once it holds more than MAX_OUT bytes, so an answer whose first reads land on
    the limit exactly is read once more, found too big and stopped at once — never left blocked on a full pipe until
    the timeout."""
    monkeypatch.setattr(hato, "MAX_OUT", 65536)
    code = ("import sys, time; sys.stdout.buffer.write(b'x' * 300000); sys.stdout.buffer.flush(); time.sleep(20)")
    t0 = time.monotonic()
    _code, data = hato._run(_child(code), 8.0)
    assert len(data) > hato.MAX_OUT
    assert time.monotonic() - t0 < 6, "stopped as too big, not at the timeout"


def test_an_answer_of_exactly_the_limit_is_read(tmp_path, monkeypatch):
    """P3.2-B30. "Up to 16 MiB": an answer exactly MAX_OUT bytes long is read; one byte more is refused."""
    lines, result = [_one_line(tmp_path)], c.result_line(1, None)
    data = _answer(lines, result)
    monkeypatch.setattr(hato, "MAX_OUT", len(data))
    got, res = hato.pairings("hato-cli", "ja", run=lambda argv, timeout: (0, data))
    assert len(got) == 1 and res["ok"] is True
    with pytest.raises(hato.Unavailable):
        hato.pairings("hato-cli", "ja", run=lambda argv, timeout: (0, data + b" "))


def test_an_answer_starting_with_a_utf8_bom_is_read(tmp_path):
    """P3.2-B31. A Windows program may start its UTF-8 output with a BOM: the answer is still read."""
    data = b"\xef\xbb\xbf" + _answer([_one_line(tmp_path)], c.result_line(1, None))
    got, _res = hato.pairings("hato-cli", "ja", run=lambda argv, timeout: (0, data))
    assert [x["show"]["episode"] for x in got] == [1]


def test_a_record_holding_u2028_and_u0085_stays_one_line(tmp_path):
    """P3.2-B32. JSON may carry U+2028 / U+0085 unescaped inside a string (a show title from a web page): the answer
    is split on "\\n" alone, so that record stays one line and is read."""
    line = _one_line(tmp_path, title="例の番組 第二期\u0085特別編")
    got, _res = hato.pairings("hato-cli", "ja",
                              run=lambda argv, timeout: (0, _answer([line], c.result_line(1, None))))
    assert len(got) == 1 and got[0]["show"]["title"] == "例の番組 第二期\u0085特別編"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_line_holding_nan_or_infinity_is_not_json_and_nothing_is_used(tmp_path, constant):
    """P3.2-B33. Python's json reads NaN / Infinity, which JSON doesn't have: a line holding one makes the answer one
    that can't be trusted."""
    line = json.dumps(_one_line(tmp_path), ensure_ascii=False).replace('"match_rate": 0.91', f'"match_rate": {constant}')
    assert constant in line
    data = line.encode("utf-8") + b"\n" + json.dumps(c.result_line(1, None)).encode("utf-8") + b"\n"
    with pytest.raises(hato.Unavailable) as e:
        hato.pairings("hato-cli", "ja", run=lambda argv, timeout: (0, data))
    assert "isn't JSON (line 1)" in e.value.reason


@pytest.mark.parametrize("ok", [1, "yes", "true"])
def test_a_result_line_whose_ok_is_not_true_itself_is_no_result_line(tmp_path, ok):
    """P3.2-B34. Only `"ok": true` ends an answer: 1, "yes" or "true" is a hato that stopped part-way."""
    data = _answer([_one_line(tmp_path)], dict(c.result_line(1, None), ok=ok))
    with pytest.raises(hato.Unavailable) as e:
        hato.pairings("hato-cli", "ja", run=lambda argv, timeout: (0, data))
    assert "no result line" in e.value.reason


def test_progress_and_other_lines_are_not_pairings(tmp_path):
    """P3.2-B35. hato may print `progress` or other lines before its result: only `pairing` lines are registered —
    the others are neither registered nor counted as refused."""
    line = _one_line(tmp_path)
    lines = [{"type": "progress", "done": 0, "total": 1}, line, {"type": "note", "text": "一件"}]
    got, _res = hato.pairings("hato-cli", "ja", run=lambda argv, timeout: (0, _answer(lines, c.result_line(1, None))))
    assert got == [line]


@pytest.mark.parametrize("since", [1759276800, 17.5, ["2026-10-01T00:00:00Z"], {"at": "2026-10-01"}])
def test_a_complete_since_that_isnt_text_is_unavailable_never_a_crash(tmp_path, since):
    """P3.2-B37. `complete_since` sent as a number, a list or an object: the answer can't be used (Unavailable, so
    the back-fill says why), never an AttributeError out of `backfill` that the switch would print as a fault."""
    data = _answer([_one_line(tmp_path)], c.result_line(1, since))
    with pytest.raises(hato.Unavailable) as e:
        hato.pairings("hato-cli", "ja", run=lambda argv, timeout: (0, data))
    assert "no time" in e.value.reason


def test_a_complete_since_without_an_offset_is_utc():
    """P3.2-B38. hato writes UTC; a time without an offset is read as UTC, never as this computer's local time
    (which would move the line between "old" files and new ones by the time zone's hours). The mutant shows only where
    local time isn't UTC."""
    at = datetime.datetime(2026, 10, 1, 9, 30, tzinfo=datetime.timezone.utc).timestamp()
    assert hato._since({"complete_since": "2026-10-01T09:30:00"}) == at
    assert hato._since({"complete_since": "2026-10-01T09:30:00Z"}) == at


def test_a_child_that_closes_its_output_then_hangs_is_stopped_within_one_timeout():
    """P3.2-X04. A hato that closes stdout and then hangs: the wait for its exit is what is left of the one deadline,
    so the whole call is stopped near its timeout, never after two. (It closes stdout 3 s into a 4 s timeout: a wait of
    a whole timeout after that would end near 7 s.)"""
    code = "import os, time; time.sleep(3); os.close(1); time.sleep(30)"
    t0 = time.monotonic()
    with pytest.raises(hato.Unavailable):
        hato._run(_child(code), 4.0)
    assert time.monotonic() - t0 < 5.5, "one timeout (4 s), not nearly two"


def test_a_whitespace_only_line_between_records_is_skipped(tmp_path):
    """P3.2-X08. A lone carriage return or spaces between two records (CRLF output cut on "\\n") is no line at all,
    never a line that isn't JSON."""
    data = _answer([_one_line(tmp_path)], c.result_line(1, None)).replace(b"\n", b"\n\r\n  \t\n", 1)
    got, _res = hato.pairings("hato-cli", "ja", run=lambda argv, timeout: (0, data))
    assert len(got) == 1


def test_hato_absent_and_hato_unusable_are_told_apart(tmp_path):
    """P3.2-X13. No hato.json at all says hato isn't connected; an entry whose program is gone says the entry can't be
    used — the learner is sent to the right fix."""
    with pytest.raises(hato.Unavailable) as absent:
        hato.find()
    assert "isn't connected" in absent.value.reason
    fake = c.fake_hato(tmp_path, [], c.result_line(0, None))
    fake.entry(cli=str(tmp_path / "アンインストール済み" / "hato-cli.exe"))
    with pytest.raises(hato.Unavailable) as unusable:
        hato.find()
    assert "can't be used" in unusable.value.reason


# --- the back-fill's lock and its log -------------------------------------------------------------------------------

def test_a_back_fill_that_raises_lets_the_next_one_ask_hato(monkeypatch):
    """P3.2-B40. One back-fill at a time: a fault inside one still lets go of the lock, so the next *Ask hato again*
    asks hato instead of answering "being asked already" for as long as the window is open."""
    def boom(lang, wait, run, summary):
        raise RuntimeError("a fault of Surasura's own")
    monkeypatch.setattr(hato, "_backfill", boom)
    with pytest.raises(RuntimeError):
        hato.backfill("ja", {"connect_enabled": True})
    monkeypatch.setattr(hato, "_backfill", lambda lang, wait, run, summary: summary.update(hato=hato.ASKED))
    assert hato.backfill("ja", {"connect_enabled": True})["hato"] == hato.ASKED


def test_during_a_command_line_verb_no_hato_backfill_log_is_written():
    """P3.2-B41. With the command line's log open (its handler on `surasura-cli`), the back-fill's lines go to
    cli.log through it: no second file, hato-backfill.log, is opened beside it."""
    cli_log = logging.getLogger("surasura-cli")
    handler = logging.NullHandler()
    cli_log.addHandler(handler)
    try:
        out = hato.backfill("ja", {"connect_enabled": True})        # no hato.json: a warning is logged
    finally:
        cli_log.removeHandler(handler)
    assert "isn't connected" in out["hato"]
    assert not os.path.exists(os.path.join(contract.log_folder(), hato.LOG_FILE))


def test_each_back_fill_takes_its_file_handler_off_again():
    """P3.2-B42. In the window, each back-fill adds hato-backfill.log's handler and takes it off again: none left on
    the logger (each line written once, no file handle kept open on the log)."""
    before = list(hato.log.handlers)
    for _ in range(2):
        hato.backfill("ja", {"connect_enabled": True})
        assert hato.log.handlers == before
    assert _log().count("weren't read, nothing registered") == 2, "each back-fill's line written once"


def test_a_log_folder_that_fails_with_any_error_never_stops_the_back_fill(monkeypatch):
    """P3.2-X15. The logs folder can't be named (a RuntimeError, not an OSError, from the local data path): the
    back-fill runs to its end without its file."""
    def no_folder():
        raise RuntimeError("no local data folder")
    monkeypatch.setattr(contract, "log_folder", no_folder)
    out = hato.backfill("ja", {"connect_enabled": True})
    assert "isn't connected" in out["hato"]


# --- no pairing from hato -------------------------------------------------------------------------------------------

def test_a_back_fill_stopped_by_a_busy_library_still_notes_the_files_with_no_pairing(tmp_path, monkeypatch):
    """P3.2-B43. Only a switch-off skips the *Needs you* entry: a back-fill the library stopped part-way (busy) still
    names the old files no line names."""
    from app import library_store
    paths = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in (1, 2)]
    lonely = _old(c.drop("Example Show - 09.ja.srt"))
    c.library()
    _switched_on()

    def busy(language, path, pairing, **kw):
        raise library_store.StoreBusy("another Surasura program holds the library")
    monkeypatch.setattr(library_store, "register_headless", busy)
    c.fake_hato(tmp_path, _lines(paths), c.result_line(2, c.iso(time.time() - DAY)))
    out = hato.backfill("ja", _settings(), wait=0.2)
    assert out["stopped"] and out["stopped"] != hato.SWITCHED_OFF, out
    assert out["unpaired"] == [lonely] and out["need"] == "raised"


def test_settings_unreadable_at_the_no_pairing_step_is_logged_and_the_summary_returns(tmp_path, monkeypatch):
    """P3.2-B44. settings.json caught half-saved when it is read again before the *Needs you* entry
    (`settings-unreadable`, a CliError): the entry waits for the next back-fill, the reason is logged, and the
    summary still comes back — never an error out of `backfill`."""
    from app.cli import verbs
    from app.cli.contract import CliError
    _old(c.drop("Example Show - 09.ja.srt"))
    c.library()
    _switched_on()

    def unreadable():
        raise CliError("settings-unreadable", "Surasura's settings (settings.json) can't be read.")
    monkeypatch.setattr(verbs, "settings", unreadable)
    c.fake_hato(tmp_path, [], c.result_line(0, None))
    out = hato.backfill("ja", {"connect_enabled": True},
                        run=lambda argv, timeout: (0, _answer([], c.result_line(0, c.iso(time.time() - DAY)))))
    assert out["hato"] == hato.ASKED and out["need"] is None and out["unpaired"] == []
    assert "weren't noted" in _log()


def test_a_file_changed_exactly_at_complete_since_is_not_listed(tmp_path):
    """P3.2-B53. "Last changed before complete_since": a file whose modified time is that instant exactly is not
    one hato's pairings are complete for; one a second earlier is."""
    since = int(time.time() - DAY)
    at_the_line = c.drop("Example Show - 08.ja.srt")
    before = c.drop("Example Show - 09.ja.srt")
    c.library()
    _switched_on()
    os.utime(at_the_line, ns=(since * 10 ** 9, since * 10 ** 9))
    os.utime(before, ns=((since - 1) * 10 ** 9, (since - 1) * 10 ** 9))
    c.fake_hato(tmp_path, [], c.result_line(0, c.iso(since)))
    out = hato.backfill("ja", _settings())
    assert out["unpaired"] == [before]


def test_old_files_hato_paired_are_never_listed_as_unpaired(tmp_path):
    """P3.2-B54. A file hato paired long ago is matched to its line by its path as the file system compares paths
    (case and separators folded on Windows): it is never counted as a file with no pairing."""
    paired = [_old(c.drop(f"Example Show - {n:02d}.ja.srt")) for n in (1, 2)]
    lonely = _old(c.drop("Example Show - 09.ja.srt"))
    c.library()
    _switched_on()
    c.fake_hato(tmp_path, _lines(paired), c.result_line(2, c.iso(time.time() - DAY)))
    out = hato.backfill("ja", _settings())
    assert out["new"] == 2 and out["unpaired"] == [lonely], out


def test_no_file_left_without_a_pairing_makes_no_ledger(tmp_path):
    """P3.2-B55. Every file paired and no ledger yet: nothing is open to fix, so no ledger file is made."""
    paths = [_old(c.drop("Example Show - 01.ja.srt"))]
    c.library()
    _switched_on()
    c.fake_hato(tmp_path, _lines(paths), c.result_line(1, c.iso(time.time() - DAY)))
    out = hato.backfill("ja", _settings())
    assert out["new"] == 1 and out["unpaired"] == [] and out["need"] is None
    assert not os.path.exists(book.path())


def test_a_new_count_before_the_entry_was_seen_says_the_new_count(tmp_path):
    """P3.2-B57. The no-pairing entry raised (four files) and not looked at yet; hato asked again with a fifth file
    left: the one open entry now says five. Why: the ledger keeps one open entry a kind and rewrites only one already
    seen, so without the old entry fixed first the unseen one kept saying "4 files" while "raised" was answered."""
    from app.connect.ledger import Ledger
    for n in (3, 4, 5, 6):
        _old(c.drop(f"Example Show - {n:02d}.ja.srt"))
    c.library()
    _switched_on()
    c.fake_hato(tmp_path, [], c.result_line(0, c.iso(time.time() - DAY)))
    assert hato.backfill("ja", _settings())["need"] == "raised"
    _old(c.drop("Example Show - 07.ja.srt"))
    assert hato.backfill("ja", _settings())["need"] == "raised"
    with Ledger() as ledger:
        assert [n["say"] for n in ledger.needs("ja", listed=False)] == [hato.need_words(5)]

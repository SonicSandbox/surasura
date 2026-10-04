"""surasura-cli's contract (docs/agent instructions/3.0/P0.3-cli-contract/02-contract.md, P1.1): JSON lines on stdout,
exit codes 0–4, no dialog, the log and the events file under the local data folder, and the checks at start.

Each call runs `python -m app.cli` in its own process, from a working folder outside the checkout, with its own test
root: what a caller (Connect, hato) sees.
"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import textwrap

import pytest

from app import __version__, analyzer, token_index, updater
from app.cli import __main__ as cli
from app.cli import contract

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _first_line(resources_dir, name, n=0):
    with open(os.path.join(resources_dir, name), encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()][n]


@pytest.fixture
def root(tmp_path):
    """The test root a call runs under (marker: it lives only in tmp_path; removed with it)."""
    r = tmp_path / "root"
    r.mkdir()
    return r


def run_cli(root, *args, env=None, cwd=None):
    """One call, as a caller makes it. Returns (exit code, the JSON lines, stdout bytes, stderr text)."""
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(root))
    environment.pop("PYTHONUTF8", None)
    environment.update(env or {})
    work = cwd or os.path.join(str(root), "..")
    proc = subprocess.run([sys.executable, "-m", "app.cli", *args], cwd=work, env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    lines = [json.loads(line) for line in proc.stdout.decode("ascii").splitlines()]
    return proc.returncode, lines, proc.stdout, proc.stderr.decode("utf-8", "replace")


def _logs(root):
    return os.path.join(str(root), "local", "logs")


def _events(root):
    path = os.path.join(_logs(root), "cli-events.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f.read().splitlines()]


def _log_text(root):
    with open(os.path.join(_logs(root), "cli.log"), encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------- #
# Lines and exit codes
# --------------------------------------------------------------------------- #
def test_version_is_one_result_line_with_every_version(root):
    code, lines, raw, err = run_cli(root, "--version")
    assert code == 0 and err == ""
    assert lines == [{"type": "result", "contract": 1, "ok": True, "app": __version__,
                      "engine": analyzer.ENGINE_REVISION, "schema": token_index.SCHEMA_VERSION, "store": None}]
    assert not raw.startswith(b"\xef\xbb\xbf") and raw.endswith(b"}\n") and b"\r" not in raw    # no BOM; \n, never \r\n


def test_unknown_verb_is_a_usage_error_exit_2(root):
    code, lines, _raw, err = run_cli(root, "nope")
    assert code == 2 and err == ""
    assert len(lines) == 1 and lines[0]["type"] == "error" and lines[0]["code"] == "usage"
    assert lines[0]["ok"] is False and lines[0]["contract"] == 1 and lines[0]["message"]


def test_nothing_asked_is_a_usage_error(root):
    code, lines, _raw, _err = run_cli(root)
    assert code == 2 and [line["code"] for line in lines] == ["usage"]


def test_a_verbs_bad_argument_is_a_usage_error_not_argparse_text(root):
    # The subcommand's own parser follows the contract too: no usage text on stderr, one line, exit 2.
    code, lines, _raw, err = run_cli(root, "_selftest", "perhaps")
    assert code == 2 and err == "" and [line["code"] for line in lines] == ["usage"]


def test_help_is_plain_text_and_exit_0(root):
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(root))
    proc = subprocess.run([sys.executable, "-m", "app.cli", "--help"], cwd=str(root), env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert proc.returncode == 0
    assert b"--version" in proc.stdout and not proc.stdout.startswith(b"{")


def test_ok_echoes_japanese_escaped(root, ja_resources_dir):
    # A Japanese argument reaches the verb intact (wide argv) and comes back ASCII-escaped (M-6 8).
    sentence = _first_line(ja_resources_dir, "context_test.txt", 3)
    code, lines, raw, _err = run_cli(root, "_selftest", "ok", "--echo", sentence)
    assert code == 0 and lines == [{"type": "result", "contract": 1, "ok": True, "verb": "_selftest", "echo": sentence}]
    assert raw.isascii() and b"\\u" in raw


def test_ok_echoes_chinese(root, zh_resources_dir):
    line = _first_line(zh_resources_dir, "chinese_text_1.txt", 4)
    code, lines, _raw, _err = run_cli(root, "_selftest", "ok", "--echo", line)
    assert code == 0 and lines[0]["echo"] == line


def test_progress_lines_come_only_when_asked_and_the_result_is_last(root):
    code, lines, _raw, _err = run_cli(root, "_selftest", "ok")
    assert code == 0 and [line["type"] for line in lines] == ["result"]
    for args in (("--progress", "_selftest", "ok"), ("_selftest", "ok", "--progress")):    # either side of the verb
        code, lines, _raw, _err = run_cli(root, *args)
        assert code == 0 and [line["type"] for line in lines] == ["progress", "result"]
        assert lines[0] == {"type": "progress", "step": "self-test", "done": 1, "total": 1}


def test_raise_is_an_error_line_exit_1_a_traceback_in_the_log_and_an_event(root):
    code, lines, _raw, err = run_cli(root, "_selftest", "raise")
    assert code == 1 and err == ""
    assert len(lines) == 1 and lines[0]["code"] == "failed" and "RuntimeError" in lines[0]["message"]
    log = _log_text(root)
    assert "Traceback (most recent call last)" in log and "self-test: an exception, as asked" in log
    assert "verb=_selftest exit=1" in log
    events = _events(root)
    assert len(events) == 1 and events[0]["code"] == "failed" and events[0]["exit"] == 1
    assert events[0]["verb"] == "_selftest" and events[0]["message"] == lines[0]["message"]


def test_fail_is_exit_1_and_an_event(root):
    code, lines, _raw, _err = run_cli(root, "_selftest", "fail")
    assert code == 1 and lines[0]["code"] == "failed"
    assert [e["code"] for e in _events(root)] == ["failed"]


def test_every_error_code_has_its_exit_code():
    # 02 §3, the five exit codes (🧭 M-6 2).
    assert {code: contract.EXIT_CODES[code] for code in contract.EXIT_CODES} == {
        "failed": 1, "partial": 1, "crashed-child": 1, "bad-data": 1,
        "usage": 2, "not-set-up": 2, "version-skew": 2,
        "busy": 3, "anki-closed": 3, "anki-busy": 3, "anki-miner-busy": 3, "update-staged": 3,
        "needs-you": 4}


# --------------------------------------------------------------------------- #
# Log, events, the channel
# --------------------------------------------------------------------------- #
def test_one_log_line_per_call_in_local_data_never_in_the_callers_folder(root, tmp_path):
    work = tmp_path / "呼び出し元"          # the caller's own folder, Japanese name
    work.mkdir()
    run_cli(root, "--version", cwd=str(work))
    run_cli(root, "nope", cwd=str(work))
    log = _log_text(root)
    assert "verb=--version exit=0" in log and "exit=2" in log and "argv=['nope']" in log
    assert os.listdir(str(work)) == []


def test_root_option_moves_the_local_data_into_it(tmp_path):
    # --root is the tests' switch (02 §6): with no SURASURA_TEST_ROOT in the environment, the log lands in it.
    root = tmp_path / "テスト root"
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT)
    environment.pop("SURASURA_TEST_ROOT", None)
    proc = subprocess.run([sys.executable, "-m", "app.cli", "--root", str(root), "--version"], cwd=str(tmp_path),
                          env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert proc.returncode == 0
    assert "verb=--version exit=0" in _log_text(root)


def test_the_log_rotates_at_1mb_keeping_three(root):
    os.makedirs(_logs(root))
    log_path = os.path.join(_logs(root), "cli.log")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("2026-10-04 古い行\n" * (contract.LOG_BYTES // 10))
    for n in (1, 2, 3):
        with open(f"{log_path}.{n}", "w", encoding="utf-8") as f:
            f.write(f"old {n}\n")
    run_cli(root, "--version")
    assert os.path.getsize(log_path) < 1000 and "verb=--version" in _log_text(root)
    assert sorted(os.listdir(_logs(root))) == ["cli.log", "cli.log.1", "cli.log.2", "cli.log.3"]
    with open(f"{log_path}.2", encoding="utf-8") as f:
        assert f.read() == "old 1\n"


def test_events_keep_the_newest_200(root):
    # The file is appended to, and cut back to the newest 200 once it passes 400.
    os.makedirs(_logs(root))
    with open(os.path.join(_logs(root), "cli-events.jsonl"), "w", encoding="utf-8") as f:
        for n in range(2 * contract.EVENTS_KEPT - 1):
            f.write(json.dumps({"n": n}) + "\n")
    run_cli(root, "_selftest", "fail")
    assert len(_events(root)) == 2 * contract.EVENTS_KEPT            # 400: not cut yet
    run_cli(root, "_selftest", "fail")
    events = _events(root)
    assert len(events) == contract.EVENTS_KEPT
    assert events[0] == {"n": 2 * contract.EVENTS_KEPT - 1 - (contract.EVENTS_KEPT - 2)}
    assert [e.get("code") for e in events[-2:]] == ["failed", "failed"]


def test_concurrent_failures_never_lose_an_event(root):
    # Six calls failing at once, ten times each: every one of the 60 errors is in the file.
    script = textwrap.dedent("""
        import io
        from app.cli import __main__ as cli
        for _ in range(10):
            cli.main(["_selftest", "fail"], out=io.StringIO())
    """)
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(root))
    procs = [subprocess.Popen([sys.executable, "-c", script], cwd=str(root), env=environment,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(6)]
    for proc in procs:
        assert proc.wait(timeout=120) == 0, proc.stderr.read()
    events = _events(root)
    assert len(events) == 60 and {e["code"] for e in events} == {"failed"}
    assert "events file can't be written" not in _log_text(root)


def test_rotation_waits_while_another_call_holds_the_log(root):
    # Another surasura-cli has cli.log open: nothing shifts, no backup is lost; the next free start rotates.
    os.makedirs(_logs(root))
    log_path = os.path.join(_logs(root), "cli.log")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("2026-10-04 古い行\n" * (contract.LOG_BYTES // 10))
    for n in (1, 2, 3):
        with open(f"{log_path}.{n}", "w", encoding="utf-8") as f:
            f.write(f"old {n}\n")
    with open(log_path, "a", encoding="utf-8"):                # the other call
        for _ in range(3):
            assert run_cli(root, "--version")[0] == 0
    for n in (1, 2, 3):
        with open(f"{log_path}.{n}", encoding="utf-8") as f:
            assert f.read() == f"old {n}\n"
    assert os.path.getsize(log_path) > contract.LOG_BYTES
    run_cli(root, "--version")
    assert os.path.getsize(log_path) < 1000
    with open(f"{log_path}.2", encoding="utf-8") as f:
        assert f.read() == "old 1\n"


def test_an_event_is_never_lost_when_the_file_is_held_open(root):
    # Windows can't replace a file another process holds open (02 §8); the event is appended instead.
    os.makedirs(_logs(root))
    path = os.path.join(_logs(root), "cli-events.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"n": 0}) + "\n")
    with open(path, encoding="utf-8"):          # a reader (the window) holds it
        code, _lines, _raw, _err = run_cli(root, "_selftest", "fail")
    assert code == 1
    assert [e.get("code") for e in _events(root)] == [None, "failed"]
    assert [n for n in os.listdir(_logs(root)) if n.endswith(".tmp")] == []


def test_a_stray_print_goes_to_the_log_not_stdout(monkeypatch, tmp_path):
    # Any module that prints while a verb runs (the analyzer's settings warning, say) must not break the JSON channel.
    def noisy(_args):
        print("Warning: Could not load logic settings")
        return {"verb": "_selftest"}
    monkeypatch.setitem(cli.VERBS, "_selftest", (cli._selftest_args, noisy, False))
    out = io.StringIO()
    assert cli.main(["_selftest", "ok"], out=out) == 0
    assert [json.loads(line)["type"] for line in out.getvalue().splitlines()] == ["result"]
    with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "local", "logs", "cli.log"), encoding="utf-8") as f:
        assert "output: Warning: Could not load logic settings" in f.read()


def test_a_native_crash_leaves_a_trace_in_the_log(root):
    # faulthandler writes into cli.log (02 §4): a real access violation (0xC0000005 on Windows), no JSON line. The
    # crash report box is suppressed by faulthandler's own helper.
    script = textwrap.dedent("""
        import faulthandler, sys
        from app.cli import __main__ as m
        m.VERBS["_selftest"] = (m._selftest_args, lambda a: faulthandler._read_null(), False)
        sys.exit(m.main(["_selftest", "ok"]))
    """)
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(root))
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(root), env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert proc.returncode not in (0, 1, 2, 3, 4) and proc.stdout == b""
    log = _log_text(root)
    assert "Windows fatal exception: access violation" in log or "Fatal Python error" in log


# --------------------------------------------------------------------------- #
# Checks at start
# --------------------------------------------------------------------------- #
def test_the_update_marker_is_the_updaters():
    assert contract.UPDATE_MARKER == updater.MARKER_NAME


def test_a_staged_update_answers_update_staged_exit_3(root):
    (root / contract.UPDATE_MARKER).write_text("{}", encoding="utf-8")
    for args in (("--version",), ("_selftest", "ok")):
        code, lines, _raw, _err = run_cli(root, *args)
        assert code == 3 and lines[0]["code"] == "update-staged"


def test_a_held_update_lock_answers_update_staged_and_a_free_one_doesnt(root):
    locks = root / "local" / "locks"
    locks.mkdir(parents=True)
    lock = locks / "update.lock"
    lock.write_bytes(b"")
    code, _lines, _raw, _err = run_cli(root, "_selftest", "ok")
    assert code == 0                                             # the file alone isn't an update
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import msvcrt, sys, time
        f = open({str(lock)!r}, "r+b")
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        print("held", flush=True)
        time.sleep(60)
    """)], stdout=subprocess.PIPE) if sys.platform == "win32" else subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import fcntl, time
        f = open({str(lock)!r}, "r+b")
        fcntl.flock(f, fcntl.LOCK_EX)
        print("held", flush=True)
        time.sleep(60)
    """)], stdout=subprocess.PIPE)
    try:
        assert holder.stdout.readline().strip() == b"held"
        code, lines, _raw, _err = run_cli(root, "_selftest", "ok")
        assert code == 3 and lines[0]["code"] == "update-staged"
    finally:
        holder.kill()
        holder.wait()
    code, _lines, _raw, _err = run_cli(root, "_selftest", "ok")    # the OS released it with the holder
    assert code == 0


def _store(root, language, version):
    index = root / "index"
    index.mkdir(exist_ok=True)
    path = index / f"token_store_{language}.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()
    return path


def test_a_token_store_of_another_schema_is_version_skew_and_left_untouched(root):
    path = _store(root, "zh", token_index.SCHEMA_VERSION + 1)
    before = path.read_bytes()
    code, lines, _raw, _err = run_cli(root, "_selftest", "ok")
    assert code == 2 and lines[0]["code"] == "version-skew"
    assert lines[0]["language"] == "zh" and lines[0]["store_schema"] == token_index.SCHEMA_VERSION + 1
    assert path.read_bytes() == before and not os.path.exists(f"{path}-wal")
    code, lines, _raw, _err = run_cli(root, "--version")           # --version still says what it is
    assert code == 0 and lines[0]["schema"] == token_index.SCHEMA_VERSION


def test_a_token_store_of_this_schema_passes(root):
    _store(root, "ja", token_index.SCHEMA_VERSION)
    code, _lines, _raw, _err = run_cli(root, "_selftest", "ok")
    assert code == 0


def test_the_schema_check_opens_each_store_read_only(root, monkeypatch):
    # The check can never wipe or rebuild a store (02 §7: mode=ro from day one).
    _store(root, "ja", token_index.SCHEMA_VERSION)
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(root))
    monkeypatch.setattr(token_index, "store_path_for", lambda lang: str(root / "index" / f"token_store_{lang}.db"))
    opened = []
    real_connect = sqlite3.connect

    def spy(database, *args, **kwargs):
        opened.append((database, kwargs.get("uri")))
        return real_connect(database, *args, **kwargs)
    monkeypatch.setattr(contract.sqlite3, "connect", spy)
    contract.check_token_stores()
    assert len(opened) == 1 and opened[0][0].endswith("?mode=ro") and opened[0][1] is True


def test_every_line_is_flushed_as_it_is_written():
    # A caller reading --progress sees each line when it is written, not when the call ends (02 §2).
    class Recorder(io.StringIO):
        flushed = []

        def flush(self):
            self.flushed.append(self.getvalue().count("\n"))
            super().flush()
    out = Recorder()
    assert cli.main(["_selftest", "ok", "--progress"], out=out) == 0
    assert out.flushed[:2] == [1, 2]


def test_a_usage_error_under_root_logs_into_that_root(tmp_path):
    # --root is read before parsing, so even a wrong command never reaches the real local folder.
    root = tmp_path / "テスト root"
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT)
    environment.pop("SURASURA_TEST_ROOT", None)
    proc = subprocess.run([sys.executable, "-m", "app.cli", "--root", str(root), "nope"], cwd=str(tmp_path),
                          env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert proc.returncode == 2
    assert [e["code"] for e in _events(root)] == ["usage"]


def test_a_log_that_fails_while_writing_never_hangs_the_call(root):
    # A broken log (disk full, a dead handle) is dropped: logging's own report would otherwise loop through the
    # stand-in stderr into the log again.
    script = textwrap.dedent("""
        import sys
        from app.cli import __main__ as cli, contract
        real_open_log = contract.open_log
        def broken_open_log():
            real_open_log()
            handler = contract.log.handlers[0]
            handler.stream = open(handler.baseFilename, "a", encoding="utf-8")
            handler.stream.close()
        contract.open_log = broken_open_log
        sys.exit(cli.main(["_selftest", "ok"]))
    """)
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(root))
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(root), env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert proc.returncode == 0
    assert [json.loads(line)["type"] for line in proc.stdout.decode("ascii").splitlines()] == ["result"]


def test_a_verb_cannot_overwrite_the_envelope(monkeypatch):
    # A result whose fields say ok:false would read as a failure with exit 0: it is a failure instead.
    monkeypatch.setitem(cli.VERBS, "_selftest", (cli._selftest_args, lambda _a: {"ok": False}, False))
    out = io.StringIO()
    assert cli.main(["_selftest", "ok"], out=out) == 1
    line = json.loads(out.getvalue())
    assert line["type"] == "error" and line["ok"] is False


def test_an_in_process_call_gives_faulthandler_back(monkeypatch):
    # The caller's own crash handler (pytest's here) is restored when the call ends.
    import faulthandler
    faulthandler.enable(sys.__stderr__)          # as pytest's own plugin has it
    cli.main(["_selftest", "ok"], out=io.StringIO())
    assert faulthandler.is_enabled()

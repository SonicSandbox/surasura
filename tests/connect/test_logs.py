"""The logs zip Connect's status window saves (P2.5 row C2; `save_logs` in `app/connect/status.py`).

What each test holds still:

  * the zip holds Surasura's own logs folder (`cli.log`) and the Anki Miner result files of Connect's run folders
    from the last 7 days. A wrong answer would leave the person with a zip that cannot explain a failed run;
  * `settings-export.json` is never in the zip, even in a recent run folder. Anki Miner's settings may hold a key
    (CLAUDE.md §6), and a log zip is something a person attaches to a bug report;
  * a result file older than 7 days is left out. Without the cut-off the zip grows with every old run, and it
    carries results the person no longer needs to explain anything.

Why the monkeypatched logs folder: the real one is the person's own log folder, and no test may read or write it.
The run folders sit under the test root, where the ledger lives. No network, no sleeps.
"""
import os
import time
import zipfile

from app.connect import ledger as book
from app.connect import status


def _run_folder(job_id):
    # Connect's run folders sit beside the ledger, one per job.
    folder = os.path.join(os.path.dirname(book.path()), "runs", str(job_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def _write(path, text="{}"):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _zip_basenames(dest):
    with zipfile.ZipFile(dest) as z:
        return [os.path.basename(n) for n in z.namelist()]


def _logs_folder(monkeypatch, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    _write(str(folder / "cli.log"), "走り出す\n")
    monkeypatch.setattr(status, "logs_folder", lambda: str(folder))
    return folder


def test_logs_zip_holds_the_cli_log_and_recent_result_files(monkeypatch, tmp_path):
    # Both halves of the zip: Surasura's own log and a result file from a run this week.
    _logs_folder(monkeypatch, tmp_path)
    run = _run_folder(41)
    _write(os.path.join(run, "result-1.json"))
    dest = str(tmp_path / "logs.zip")

    names = status.save_logs(dest)

    assert names, "a zip with a log and a recent result must name what it holds"
    basenames = _zip_basenames(dest)
    assert "cli.log" in basenames
    assert "result-1.json" in basenames


def test_logs_zip_never_holds_settings_export(monkeypatch, tmp_path):
    # The settings export sits in a recent run folder, next to a result file the zip should keep. Only the
    # export is left out: it may hold a key.
    _logs_folder(monkeypatch, tmp_path)
    run = _run_folder(42)
    _write(os.path.join(run, "settings-export.json"), '{"key": "not for a zip"}')
    _write(os.path.join(run, "result-2.json"))
    dest = str(tmp_path / "logs.zip")

    status.save_logs(dest)

    basenames = _zip_basenames(dest)
    assert "settings-export.json" not in basenames
    assert "result-2.json" in basenames


def test_logs_zip_leaves_out_result_files_older_than_seven_days(monkeypatch, tmp_path):
    # One result file from eight days ago and one from today, in two runs. The old one must be left out; the
    # recent one must still be in, so the test cannot pass by dropping every result.
    _logs_folder(monkeypatch, tmp_path)
    old = _write(os.path.join(_run_folder(43), "result-old.json"))
    _write(os.path.join(_run_folder(44), "result-new.json"))
    eight_days_ago = time.time() - 8 * 86400
    os.utime(old, (eight_days_ago, eight_days_ago))
    dest = str(tmp_path / "logs.zip")

    status.save_logs(dest)

    basenames = _zip_basenames(dest)
    assert "result-new.json" in basenames
    assert "result-old.json" not in basenames

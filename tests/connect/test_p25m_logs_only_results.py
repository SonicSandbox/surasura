"""The logs zip takes only Anki Miner's result files from Connect's run folders (P2.5 mutant M17; `save_logs` in
`app/connect/status.py`).

What the test holds still: a run folder holds more than result files (for example `words.json`, the words a run
worked on). Only the `result*.json` files go into the zip. A wrong answer would put a run's other working files
into a zip a person attaches to a bug report, and those files can hold things the person did not mean to send.

Why the monkeypatched logs folder: the real one is the person's own log folder, and no test may read or write it.
The run folder sits under the test root, beside the ledger. No network, no sleeps.
"""
import os
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


def test_logs_zip_takes_only_result_files_from_a_run_folder(monkeypatch, tmp_path):
    # A run folder holds a result file and a words file. Only the result file is Anki Miner's output the zip
    # is for; the words file is the run's working data and stays out.
    _logs_folder(monkeypatch, tmp_path)
    run = _run_folder(41)
    _write(os.path.join(run, "result-1.json"))
    _write(os.path.join(run, "words.json"), '["上層部", "一生懸命"]')
    dest = str(tmp_path / "logs.zip")

    status.save_logs(dest)

    basenames = _zip_basenames(dest)
    assert "result-1.json" in basenames, "a recent result file is the one run file the zip keeps"
    assert "words.json" not in basenames, "a run's words file is working data, never sent in a log zip"

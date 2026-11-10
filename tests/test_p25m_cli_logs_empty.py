"""P2.5's mutant pass: `surasura-cli logs --save` with nothing to save answers 0 files.

The rule: when Surasura's logs folder is empty and Connect has no run folders, the saved zip holds no
files, so the answer's `files` is 0. A wrong count (the mutant reports 1 for an empty save) would tell
the user a zip holds a file it doesn't, and a support request would start from a file that isn't there.

Real temp folders, the real command line, no network, no sleeps.
"""
import os
import zipfile

from app.connect import status
from tests import cli_helpers as h


def test_logs_save_of_an_empty_folder_answers_zero_files(tmp_path, monkeypatch):
    # why: an empty logs folder and no runs folder beside the ledger is a fresh install's first save;
    # the answer must count the zip's contents (none), not the zip itself
    empty = tmp_path / "logs"
    empty.mkdir()
    monkeypatch.setattr(status, "logs_folder", lambda: str(empty))
    dest = str(tmp_path / "saved.zip")
    code, answer = h.call("logs", "--save", dest)
    assert code == 0 and answer["files"] == 0, answer
    # why: the count alone would pass a save that writes no zip, or a zip with entries; the zip is the rule
    assert os.path.exists(dest) and zipfile.ZipFile(dest).namelist() == []

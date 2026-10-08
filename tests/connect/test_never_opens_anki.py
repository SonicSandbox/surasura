"""Nothing starts Anki after mining (P2.3 row 2.3.7; ✅ Q4-16, K102; BRIEF: "Anki is never opened for you after
mining"): with Connect's preview on, *Open Anki for me* on and Anki closed, every path Connect, hato or another program
can take — `register`, `place`, `connect`, `pick` with a video, a mine batch, `setup`, `known-sync`, `junban --auto`,
`backfill` — leaves Anki closed. Only a window's session start may open it (`anki_session.at_window`), and the
source says so.

"Anki" here is a stand-in script that writes a file the moment it is started: the file never appears.
"""
import ast
import os
import re
import subprocess

import pytest

from app.connect import open_anki
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

APP = os.path.join(h.PROJECT_ROOT, "app")
STAND_IN = 'import os\nopen(os.environ["STAND_IN_OUT"], "w").write("Anki was started")\n'


@pytest.fixture
def anki_stand_in(tmp_path, monkeypatch):
    """Anki closed (nothing on its port), Open Anki for me on, and a stand-in "Anki" that leaves a mark if started;
    `open_anki.start` and every new process watched."""
    script = tmp_path / "anki_stand_in.py"
    script.write_text(STAND_IN, encoding="utf-8")
    mark = tmp_path / "anki-started.txt"
    monkeypatch.setenv(open_anki.STAND_IN, str(script))
    monkeypatch.setenv("STAND_IN_OUT", str(mark))
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)        # Anki is asked: it just isn't there
    starts, commands = [], []
    real_start, real_popen = open_anki.start, subprocess.Popen
    monkeypatch.setattr(open_anki, "start", lambda *a, **k: starts.append(a) or real_start(*a, **k))

    class Watched(real_popen):
        def __init__(self, args, *a, **k):
            commands.append(args)
            super().__init__(args, *a, **k)
    monkeypatch.setattr(subprocess, "Popen", Watched)

    def never():
        assert starts == [], "open_anki.start was called"
        assert not any(str(script) in " ".join(map(str, cmd if isinstance(cmd, (list, tuple)) else [cmd]))
                       for cmd in commands), commands
        assert not mark.exists(), "Anki was started"
    return never


def test_the_library_verbs_and_connect_never_open_anki(anki_stand_in):
    c.library("ja", connect=True, connect_open_anki=True)
    record = c.write_record(c.record(c.drop("Example Show - 05.ja.srt"), "video-05"))
    for argv in (["register", "--pairing", record], ["place", "--file", "1", "--to", "now", "--source", "test"],
                 ["connect", "--consume-only"], ["setup"], ["known-sync"], ["junban", "--auto"],
                 ["backfill", "--tag", "surasura::connect::job-1"]):
        h.call(*argv)
    anki_stand_in()


def test_picking_and_mining_never_open_anki(anki_stand_in, fake_miner, tmp_path):
    from app.connect import anki_miner, fields
    from tests.connect.fake_anki_miner import LAPIS_EXPORT
    library = h.seed_library("ja", templates=False)
    h.write_settings(connect_enabled=True, connect_open_anki=True, connect_anki_miner_path=fake_miner.path)
    subtitle = os.path.join(library, "phrases_sample.srt")
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")
    code, picked = h.call("pick", "--file", subtitle, "--video", str(video), "--words", "unknown", "--job", "job-1")
    assert code == 0 and picked["words"], picked
    fake_miner.plan(mine="anki-closed")                 # Anki Miner finds Anki closed: the batch is refused, Anki left
    with pytest.raises(anki_miner.AnkiMinerError) as refused:
        anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(video), subtitle,
                              picked["words"][:3],
                              fields.from_export(LAPIS_EXPORT), "Surasura", str(tmp_path / "runs" / "job-1"),
                              h.CLOSED_PORT)
    assert refused.value.kind in ("anki-closed", "setup")
    anki_stand_in()


def _callers():
    """Every source file of the app's and its modules' that starts Anki through `open_anki`, however it's imported."""
    found = []
    for top in (APP, os.path.join(h.PROJECT_ROOT, "modules")):
        for folder, _dirs, files in os.walk(top):
            for name in files:
                if not name.endswith(".py") or os.sep + "tests" + os.sep in os.path.join(folder, ""):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                if re.search(r"open_anki\.start\(|from\s+app\.connect\.open_anki\s+import|import\s+app\.connect\.open_anki",
                             text):
                    found.append(os.path.relpath(path, h.PROJECT_ROOT).replace(os.sep, "/"))
    return found


def test_only_a_windows_session_start_calls_open_anki_start():
    assert _callers() == ["app/connect/anki_session.py"], _callers()
    with open(os.path.join(APP, "connect", "anki_session.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "start" and getattr(node.func.value, "id", None) == "open_anki"]
    assert len(calls) == 1
    # the call sits under an `if` whose test reads the window's `opening` flag, inside `at_window`
    guards = []
    for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(function):
            if isinstance(node, ast.If) and any(c is calls[0] for c in ast.walk(node)):
                guards.append((function.name, {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}))
    assert guards and all(name == "at_window" for name, _ in guards)
    assert any("opening" in names for _name, names in guards), guards

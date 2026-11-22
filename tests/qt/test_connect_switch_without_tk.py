"""Connect's switch from the 3.0 window imports no tkinter (Mado-TK part 1: the Qt → Tk ties cut).

What a wrong answer would cost: turning Connect off with cards on its shelf went through the 2.x Tk window's module for
the wait on Anki's write lock — on a Python without Tk the put-back failed with an ImportError as its reason, and every
switch-off loaded Tk into the window's process. Each of the window's switch steps (`app/qt/settings_connect.py`'s
workers: on, off with nothing shelved, off with the shelf put back after a wait) runs here in a fresh process where
importing tkinter fails, as on a Python built without it; the put-back still waits out a busy writer and answers.
"""
import json
import os
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TK = ("tkinter", "_tkinter", "tkinterdnd2")


def test_every_switch_step_of_the_window_runs_with_tkinter_missing_and_the_put_back_waits_for_the_writer(tmp_path):
    import site
    root = tmp_path / "root"
    root.mkdir()
    env = dict(os.environ, PYTHONPATH=ROOT, SURASURA_TEST_ROOT=str(root), TELEMETRY_ENV="dev", TELEMETRY_URL="",
               APPDATA=str(tmp_path / "appdata"), LOCALAPPDATA=str(tmp_path / "localappdata"),
               XDG_DATA_HOME=str(tmp_path / "xdg"),
               PYTHONUSERBASE=site.getuserbase())     # the packages installed for this user stay importable
    for name in ("HOUSEKI_TOOLS_DIR", "SURASURA_TOOLS_CLI"):
        env.pop(name, None)                           # surasura.json under the test root, never a caller's folder
    for gate in ("SURASURA_NO_AUTOINDEX", "SURASURA_NO_ANKI_SYNC", "SURASURA_NO_UPDATE_CHECK"):
        env[gate] = "1"                               # no indexer, Anki or GitHub from a test
    script = textwrap.dedent(f"""
        import json, sys
        tried = []

        class NoTk:                                   # a Python built without Tk: importing it fails
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in {TK!r}:
                    tried.append(name)
                    raise ImportError("No module named " + repr(name) + " (a Python without Tk)")
                return None
        sys.meta_path.insert(0, NoTk())

        from app.cli.contract import CliError
        from app.connect import setup, undo
        from app.qt import settings_connect as scn
        present = setup._present
        setup._present = lambda name: True if name == "modules.junban.reposition" else present(name)
        # (Junban there either way: the shelf is read for real — Connect's status record, none on this empty root)

        class Store:                                  # the settings service's two calls the steps make
            def fresh(self):
                return {{}}

            def reload(self):
                return {{}}

        answers = [CliError("busy", "Another program is writing to Anki.", lock="anki-writer", held_by=None),
                   {{"language": "ja", "shelf": "shelf-2026-11-21-a", "back": 3, "confirm": True}}]
        acts, waits, lines = [], [], []

        def act(settings, language, job=None, shelf_run=None, confirm=False):
            acts.append([language, shelf_run, confirm])
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        undo.act = act
        undo.writer_busy = lambda: True               # Anki Miner holds the write lock for the first try
        undo.update_waits = lambda: False
        undo.RETRY_GAP_S = 0.01
        store = Store()
        on = scn._switch_on(store, lines.append)
        off = scn._switch_off_start(True, store, lines.append)
        back = scn._switch_off({{"ja": (3, ["shelf-2026-11-21-a"])}}, store, lines.append, lambda: waits.append(1))
        print("\\n" + json.dumps({{"on": list(on), "off": list(off), "back": list(back), "acts": acts,
                                   "waits": len(waits), "lines": lines, "tried": tried,
                                   "status_read": "app.connect.status" in sys.modules,
                                   "loaded": sorted(m for m in sys.modules if m.split(".")[0] in {TK!r})}}))
    """)
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(root), env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr[-3000:]
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    assert got["tried"] == [] and got["loaded"] == [], "a switch step reached for tkinter"
    assert got["on"] == [True, None], got["lines"]
    assert got["status_read"] is True, "the shelf was read (status), not skipped for a missing Junban"
    assert got["off"][:2] == ["off", True], got["lines"]
    assert got["acts"] == [["ja", "shelf-2026-11-21-a", True]] * 2, "as you (confirm), tried again after the wait"
    assert got["waits"] == 1, "the busy writer waited out, said once"
    assert "3 shelved cards back in your new cards." in got["lines"]
    assert got["back"][:2] == ["off", True], got["lines"]

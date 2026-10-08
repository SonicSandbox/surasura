"""P2.4's Part A proof on DevTest (row 2.4.9 (a); P1.5 07-tests §2): Connect's whole loop against the real Anki and Anki
Miner 3.7.0 — hato-style drops of a public subtitle and its short test video into a scratch library, `surasura-cli
connect` as a child, cards made, filled, ordered and synced; a Connect killed mid-batch and resumed; a burst of drops
timed (02 §4); then every card it made deleted and counted back to zero. Never run by the suites; by hand, with
locks/anki.lock taken by hand (board lines) and Anki open on DevTest:

    python tests/connect/live_loop_drill.py --profile DevTest --anki-miner <am.py guard> --am-home <a drill home> \\
        --subtitle <public .srt> --video <its test video> [--steps loop,kill,burst] [--burst 20]

- **Anki:** `getActiveProfile == "DevTest"` before anything and before teardown; anything else stops the drill.
- **Anki Miner:** only through the `am.py` guard, with a drill home of its own (`AM37_TEST_HOME`; deck DevTest, its
  AnkiConnect address live only while anki.lock names the guard's step) — never the user's own home or install.
- **Surasura:** a scratch test root (`SURASURA_TEST_ROOT`): its library, known words (the suite's), settings, ledger.
- **The mark and teardown:** every note Connect makes carries `surasura::connect::<job id>`; at the end every note of
  this run's jobs created after the drill began is deleted (holding `anki-writer`) and counted again: anything left
  fails the drill and is named.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESOURCES = os.path.join(REPO, "tests", "Test Resources")
# the burst's words, one a drop: dictionary words of two kanji or more the suite's known words don't hold
DROP_WORDS = ("蜃気楼", "灯台", "羅針盤", "潮騒", "珊瑚礁", "漁火", "帆船", "波止場", "入江", "干潟",
              "防波堤", "稲妻", "汽笛", "木枯らし", "陽炎", "雪崩", "氷柱", "夕凪", "渦潮", "灯籠")


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def _args():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--anki-miner", required=True, help="the am.py guard")
    ap.add_argument("--am-home", required=True, help="the drill's own Anki Miner home (AM37_TEST_HOME)")
    ap.add_argument("--subtitle", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--steps", default="loop,kill,burst")
    ap.add_argument("--burst", type=int, default=20)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--root", default=None)
    ap.add_argument("--keep", action="store_true", help="leave the cards (no teardown): never on a shared profile")
    return ap.parse_args()


class Drill:
    def __init__(self, a):
        self.a = a
        self.root = os.path.abspath(a.root or tempfile.mkdtemp(prefix="p24-drill-"))
        self.started_ms = int(time.time() * 1000)
        self.summary = {"root": self.root, "steps": {}}
        self.n = 0

    # --- Anki ---------------------------------------------------------------------------------------------- #
    def ask(self, action, **params):
        from app import anki_connect
        return anki_connect.invoke(action, self.a.url, timeout=30, **params)

    def devtest(self):
        try:
            return self.ask("getActiveProfile") == "DevTest"
        except Exception:
            return False

    # --- the scratch library ------------------------------------------------------------------------------- #
    def setup(self):
        os.environ["SURASURA_TEST_ROOT"] = self.root
        os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
        os.environ["AM37_TEST_HOME"] = os.path.abspath(self.a.am_home)
        data = os.path.join(self.root, "data", "ja", "HighPriority")
        os.makedirs(data, exist_ok=True)
        user = os.path.join(self.root, "User Files", "ja")
        os.makedirs(user, exist_ok=True)
        shutil.copy2(os.path.join(RESOURCES, "ja", "KnownWord.json"), os.path.join(user, "KnownWord.json"))
        if not os.path.isdir(os.path.join(self.root, "templates")):
            shutil.copytree(os.path.join(REPO, "templates"), os.path.join(self.root, "templates"))
        settings = {"target_language": "ja", "connect_enabled": True, "anki_connect_url": self.a.url,
                    "anki_sync_decks": {"ja": ["DevTest"]}, "anki_sync_fields": {"ja": ["Expression"]},
                    "enable_junban": True, "junban_deck": "DevTest",
                    "junban_backfill_deck": "DevTest", "connect_anki_miner_path": os.path.abspath(self.a.anki_miner),
                    "anki_sync_delay_min": 1,
                    # every word the suite's known words don't hold: the short public episode lists none (all but a
                    # few of its words are known), so its cards are its unknown words
                    "connect_mine_words": "unknown"}
        with open(os.path.join(self.root, "settings.json"), "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False)
        from app import library_store
        from app.path_utils import get_data_path, get_user_files_path
        assert library_store.maintain("ja", get_data_path("ja"), get_user_files_path("ja"),
                                      from_folders=True) == library_store.EXIT_DONE
        from app.connect import library
        store = library.open_store("ja")
        with store:
            store.bookkeeping({"mine_line": 20}, copy_carries=True)
            library.ensure_reader(store)
        # The person's own first "Sync now" (the known-words gate: never read behind their back), on the drill deck
        from app import anki_sync
        first = anki_sync.sync("ja", self.a.url, ["DevTest"], ["Expression"])
        assert first.error is None, first.error
        # Connect's setup, as the person's own: it records the Anki profile Connect makes cards in (the open one)
        from app.connect import setup as connect_setup
        connect_setup.checks(settings, "ja")
        assert connect_setup.anki_profile() == "DevTest", connect_setup.read_record()

    def drop(self):
        """A hato-style drop: the subtitle copied into hato's folder (its own bytes), registered with a `timed`
        pairing record naming the test video -> its item id."""
        from app import library_store
        from app.connect import library
        from app.path_utils import get_data_path
        self.n += 1
        name = f"Drill Show - {self.n:02d}.ja.srt"
        folder = os.path.join(get_data_path("ja"), *library_store.HATO_FOLDER.split("/"))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(self.a.subtitle, "rb") as f:
            data = f.read()
        # one new word a drop, on the last line's time (inside the video): every drop of the burst makes its own card,
        # so the burst times 20 real Anki Miner batches, not one batch and 19 empty picks
        times = re.findall(r"(\d\d:\d\d:\d\d,\d\d\d) --> (\d\d:\d\d:\d\d,\d\d\d)", data.decode("utf-8-sig"))
        start, end = times[-1] if times else ("00:00:01,000", "00:00:02,000")
        word = DROP_WORDS[(self.n - 1) % len(DROP_WORDS)]
        with open(path, "wb") as f:
            f.write(data + f"\n\n{9000 + self.n}\n{start} --> {end}\n{word}が見えた。\n".encode("utf-8"))
        with open(path, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        with open(os.path.join(RESOURCES, "connect", "pairing_v1.json"), encoding="utf-8") as f:
            record = json.load(f)
        record.update({"schema": 1, "language": "ja", "library_path": path, "subtitle_sha256": sha, "verdict": "timed",
                       "timing": {"outcome": "CONFIDENT", "offset_s": 0.0, "segments": 1, "reference": "subtitle"},
                       "video_path": os.path.abspath(self.a.video), "video_size": os.path.getsize(self.a.video),
                       "content_key": "v1-" + hashlib.sha256(f"drill-{self.n}-{time.time()}".encode()).hexdigest()})
        store = library.open_store("ja")
        with store:
            change = store.register(path, record)
        return change.added[0]

    def connect(self, looks=3, kill_when=None):
        """`surasura-cli connect` as a child -> (exit code, its answer, seconds). `kill_when(ledger path)`: polled
        every 0.2 s; when it says so the child and its own children are killed."""
        command = [sys.executable, "-m", "app.cli", "connect", "--looks", str(looks)]
        started = time.monotonic()
        child = subprocess.Popen(command, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if kill_when is not None:
            while child.poll() is None:
                if kill_when():
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(child.pid)], capture_output=True)
                    break
                time.sleep(0.2)
        out, _err = child.communicate(timeout=3 * 3600)
        text = out.decode("utf-8", errors="replace")
        lines = [json.loads(line) for line in text.splitlines() if line.startswith("{")]
        return child.returncode, (lines[-1] if lines else None), round(time.monotonic() - started, 1)

    def jobs(self):
        from app.connect.ledger import Ledger
        with Ledger() as ledger:
            return ledger.jobs("ja")

    def notes_of(self, job):
        """The notes carrying the job's tag (`<ledger uid>-<id>`)."""
        from app.connect import anki_miner, runfile
        return self.ask("findNotes", query=anki_miner.tag_query(runfile.job_tag(job["tag"])))

    # --- the steps ----------------------------------------------------------------------------------------- #
    def loop(self):
        item = self.drop()
        code, answer, seconds = self.connect()
        job = next(j for j in self.jobs() if j["item_id"] == item)
        notes = self.notes_of(job)
        out = {"exit": code, "seconds": seconds, "state": job["state"], "reason": job["reason"],
               "skipped": job["skipped"], "notes": len(notes), "answer": answer}
        self.summary["steps"]["loop"] = out
        say("loop", out)
        return job["state"] == "done" and notes

    def kill(self):
        from app.connect.ledger import Ledger
        item = self.drop()

        def mid_batch():
            try:
                with Ledger() as ledger:
                    for job in ledger.jobs("ja"):
                        if job["item_id"] == item and any(b["state"] == "running" for b in ledger.batches(job["id"])):
                            time.sleep(8)               # inside Anki Miner's run: some cards made, some not
                            return True
            except Exception:
                return False
            return False
        code1, _a, s1 = self.connect(kill_when=mid_batch)
        job = next(j for j in self.jobs() if j["item_id"] == item)
        before = len(self.notes_of(job))
        code2, answer, s2 = self.connect()
        job = next(j for j in self.jobs() if j["item_id"] == item)
        ids = self.notes_of(job)
        info = self.ask("notesInfo", notes=ids) if ids else []
        words = [((n.get("fields") or {}).get("Expression") or {}).get("value") for n in info]
        twice = sorted({w for w in words if words.count(w) > 1})
        out = {"killed_exit": code1, "notes_at_kill": before, "resumed_exit": code2, "state": job["state"],
               "notes": len(ids), "made_twice": twice, "seconds": [s1, s2]}
        self.summary["steps"]["kill"] = out
        say("kill", out)
        return job["state"] == "done" and not twice

    def burst(self):
        items = [self.drop() for _ in range(self.a.burst)]
        code, answer, seconds = self.connect(looks=3)
        from app.connect.ledger import Ledger
        with Ledger() as ledger:
            jobs = [j for j in ledger.jobs("ja") if j["item_id"] in items]
            ended = sorted(j["updated_at"] for j in jobs)
        out = {"drops": len(items), "exit": code, "seconds": seconds, "done": sum(j["state"] == "done" for j in jobs),
               "first_done": ended[0] if ended else None, "last_done": ended[-1] if ended else None,
               "states": sorted({j["state"] for j in jobs})}
        self.summary["steps"]["burst"] = out
        say("burst", out)
        return out["done"] == len(items)

    def teardown(self):
        from app import anki_connect
        if not self.devtest():
            self.summary["teardown"] = "SKIPPED: Anki isn't on DevTest; the notes are left — named below"
            return False
        ids = sorted({n for j in self.jobs() for n in self.notes_of(j) if n >= self.started_ms})
        with anki_connect.writer("P2.4 drill teardown", wait=60):
            if ids:
                self.ask("deleteNotes", notes=ids)
        left = sorted({n for j in self.jobs() for n in self.notes_of(j) if n >= self.started_ms})
        self.summary["teardown"] = {"deleted": len(ids), "left": left}
        say("teardown", self.summary["teardown"])
        return not left


def main():
    a = _args()
    if a.profile != "DevTest":
        sys.exit("REFUSED: the drill runs on the DevTest profile only")
    sys.path.insert(0, REPO)
    drill = Drill(a)
    if not drill.devtest():
        sys.exit("REFUSED: Anki isn't open on DevTest")
    drill.setup()
    ok = True
    try:
        for step in [s.strip() for s in a.steps.split(",") if s.strip()]:
            if not drill.devtest():
                sys.exit("STOPPED: Anki left the DevTest profile")
            ok = getattr(drill, step)() and ok
    finally:
        if not a.keep:
            ok = drill.teardown() and ok
        print(json.dumps(drill.summary, ensure_ascii=False, indent=1, default=str))
    say("PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

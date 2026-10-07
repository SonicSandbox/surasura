"""Shared by the services' suites (W1.3): another program holding a lock, a library of real test files under the test's
own root (`SURASURA_TEST_ROOT`), and a wait for a condition with a deadline (never a bare sleep)."""
import json
import os
import shutil
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES = os.path.join(PROJECT_ROOT, "tests", "Test Resources")
LIBRARY = {"ja": ("context_test.txt", "runaway_transcript.txt", "phrases_sample.srt"), "zh": ("chinese_text_1.txt",)}
KNOWN = {"ja": "KnownWord.json", "zh": "KnownWords.json"}

# A child that takes one lock for `verb` and holds it until its stdin closes: it prints "held" first.
_HOLDER = r"""
import sys
from app import locks
held = locks.take(sys.argv[1], sys.argv[2])
print("held", flush=True)
sys.stdin.read()
held.release()
"""


class Holder:
    """Another program holding a lock (a child Python, under the same test root), until `release()`."""

    def __init__(self, name, verb="another Surasura program"):
        env = dict(os.environ, PYTHONPATH=PROJECT_ROOT)
        self.proc = subprocess.Popen([sys.executable, "-c", _HOLDER, name, verb], cwd=PROJECT_ROOT, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline().strip()
        assert line == "held", self.proc.stderr.read()

    def release(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def root():
    return os.environ["SURASURA_TEST_ROOT"]


def settings_path():
    return os.path.join(root(), "settings.json")


def write_settings(values):
    with open(settings_path(), "w", encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False)


def read_settings():
    with open(settings_path(), encoding="utf-8") as f:
        return json.load(f)


def seed_library(lang="ja", files=None, copies=0):
    """Real files in NOW and their known words; `copies` more files made from the transcript (a Generate that takes a
    few seconds). Settings point Anki at a closed loopback port."""
    folder = os.path.join(root(), "data", lang, "HighPriority")
    os.makedirs(folder, exist_ok=True)
    for name in files or LIBRARY[lang]:
        shutil.copy2(os.path.join(RESOURCES, lang, name), os.path.join(folder, name))
    if copies:
        text = open(os.path.join(RESOURCES, "ja", "runaway_transcript.txt"), encoding="utf-8").read()
        for n in range(copies):
            with open(os.path.join(folder, f"episode_{n:02d}.txt"), "w", encoding="utf-8") as f:
                f.write(text[n * 37:] + text[: n * 37])
    user_files = os.path.join(root(), "User Files", lang)
    os.makedirs(user_files, exist_ok=True)
    shutil.copy2(os.path.join(RESOURCES, lang, KNOWN[lang]), os.path.join(user_files, "KnownWord.json"))
    os.makedirs(os.path.join(root(), "results"), exist_ok=True)
    if not os.path.exists(settings_path()):
        write_settings({"target_language": lang, "anki_connect_url": "http://127.0.0.1:9"})
    return folder


def until(condition, seconds=30.0, every=0.02):
    """Wait for `condition()` to be true, up to `seconds`: its last value."""
    deadline = time.monotonic() + seconds
    while True:
        value = condition()
        if value or time.monotonic() > deadline:
            return value
        time.sleep(every)


def timed(call):
    """(result, milliseconds) of one call on this thread."""
    start = time.perf_counter()
    result = call()
    return result, (time.perf_counter() - start) * 1000

"""Shared by the command line's suites (P1.2): a library made of real test files, settings, and calls of
`surasura-cli` both as a caller makes them (a child process) and in-process (for what only a patch can see).

Every call runs under the test's own root (`SURASURA_TEST_ROOT`, a temp folder): its marker is that it lives only
there, and the temp folder's removal is its teardown. Anki is only ever a fake: settings point AnkiConnect at a
closed loopback port unless a test hands it a fake's address.
"""
import io
import json
import os
import shutil
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES = os.path.join(PROJECT_ROOT, "tests", "Test Resources")
LIBRARY = {"ja": ("context_test.txt", "runaway_transcript.txt", "phrases_sample.srt"), "zh": ("chinese_text_1.txt",)}
KNOWN = {"ja": "KnownWord.json", "zh": "KnownWords.json"}
CLOSED_PORT = "http://127.0.0.1:9"          # nothing listens: Anki is "closed"


def root():
    return os.environ["SURASURA_TEST_ROOT"]


@pytest.fixture(autouse=True)
def same_token_store_as_the_children(monkeypatch):
    """conftest moves this process's token store to a folder of its own; a child process (the command line, the
    analyzer it starts) keeps it under the test root. In-process checks look where the children write. Imported by
    each command-line suite, which makes it theirs."""
    from app import token_index

    def path(language):
        folder = os.path.join(root(), "index")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, f"token_store_{language}.db")
    monkeypatch.setattr(token_index, "store_path_for", path)


def seed_library(lang="ja", files=None, templates=True):
    """A library of real files in NOW, its known words, and (for a report) the templates the test root resolves."""
    folder = os.path.join(root(), "data", lang, "HighPriority")
    os.makedirs(folder, exist_ok=True)
    for name in files or LIBRARY[lang]:
        shutil.copy2(os.path.join(RESOURCES, lang, name), os.path.join(folder, name))
    user_files = os.path.join(root(), "User Files", lang)
    os.makedirs(user_files, exist_ok=True)
    shutil.copy2(os.path.join(RESOURCES, lang, KNOWN[lang]), os.path.join(user_files, "KnownWord.json"))
    if templates and not os.path.isdir(os.path.join(root(), "templates")):
        shutil.copytree(os.path.join(PROJECT_ROOT, "templates"), os.path.join(root(), "templates"))
    return folder


def write_settings(**values):
    """settings.json as the window would leave it, Anki pointed at a closed port unless `values` say otherwise."""
    settings = {"target_language": "ja", "anki_connect_url": CLOSED_PORT}
    settings.update(values)
    with open(os.path.join(root(), "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)
    return settings


def child_env(**extra):
    env = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=root())
    env.pop("PYTHONUTF8", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    env.update({k: v for k, v in extra.items() if v is not None})
    for k, v in extra.items():
        if v is None:
            env.pop(k, None)
    return env


def run_cli(*args, env=None, timeout=300):
    """One call, as a caller makes it -> (exit code, its JSON lines)."""
    proc = subprocess.run([sys.executable, "-m", "app.cli", *args], cwd=os.path.dirname(root()),
                          env=child_env(**(env or {})), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout)
    lines = [json.loads(line) for line in proc.stdout.decode("ascii").splitlines()]
    return proc.returncode, lines


def start_cli(*args, env=None):
    """A call left running (to kill it, or to start another beside it)."""
    return subprocess.Popen([sys.executable, "-m", "app.cli", *args], cwd=os.path.dirname(root()),
                            env=child_env(**(env or {})), stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def call(*args):
    """One call in this process (a patch can see inside) -> (exit code, the JSON line)."""
    from app.cli import __main__ as cli
    out = io.StringIO()
    code = cli.main(list(args), out=out)
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    return code, lines[-1]


def answer(lines):
    """The result or error line (always last)."""
    return lines[-1]

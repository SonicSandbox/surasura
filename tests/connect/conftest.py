"""Connect's tests run against the fake Anki Miner only (07-tests §1): the real one — Sonic's own mining — is never
found, started or read, whatever is installed on the machine."""
import json
import os

import pytest

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_anki_miner.py")


@pytest.fixture(autouse=True)
def never_the_real_anki_miner(monkeypatch):
    # The installer's registry key and the default folder would find a real install: neither is looked at here.
    from app.connect import anki_miner
    monkeypatch.setattr(anki_miner, "_registry_location", lambda: None)
    monkeypatch.setattr(anki_miner, "_default_location", lambda: None)


class FakeAnkiMiner:
    """The fake's program path, its plan (what it answers) and the calls it was given."""

    def __init__(self, folder):
        self.path = FAKE
        self._plan = os.path.join(folder, "fake-plan.json")
        self._log = os.path.join(folder, "fake-calls.jsonl")
        self.plan()

    def plan(self, **answers):
        with open(self._plan, "w", encoding="utf-8") as f:
            json.dump(answers, f, ensure_ascii=False)

    def calls(self):
        if not os.path.exists(self._log):
            return []
        with open(self._log, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def commands(self):
        return [c["argv"][1] for c in self.calls() if "argv" in c and len(c["argv"]) > 1]

    def run_files(self):
        return [c["run_file"] for c in self.calls() if "run_file" in c]


@pytest.fixture
def fake_miner(tmp_path, monkeypatch):
    fake = FakeAnkiMiner(str(tmp_path))
    monkeypatch.setenv("FAKE_ANKI_MINER_PLAN", fake._plan)
    monkeypatch.setenv("FAKE_ANKI_MINER_LOG", fake._log)
    return fake

"""surasura.json's gaps the P3.2 mutant pass found (research/mutants/JUDGED-P3.2.md): planted bugs in
app/tools_entry.py that test_tools_entry.py let through. Each test names its mutant.

Every test runs in its own test root and its own tools folder (HOUSEKI_TOOLS_DIR); the real shared tools folder is
never touched. Install paths carry Japanese / Chinese names, as users' install paths routinely do."""
import json
import os
import sys
import types

import pytest

from app import path_utils, tools_entry
from app.cli import contract


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A data root holding Japanese set up (its User Files/ja), Chinese not."""
    r = tmp_path / "データ根"
    (r / "User Files" / "ja").mkdir(parents=True)
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(r))
    return r


@pytest.fixture
def tools(tmp_path, monkeypatch):
    folder = tmp_path / "tools"
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(folder))
    return folder


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """A frozen install: Surasura.exe and surasura-cli.exe side by side, the window's exe running."""
    install = tmp_path / "スラスラ 安装"
    install.mkdir()
    (install / "Surasura.exe").write_bytes(b"MZ")
    (install / "surasura-cli.exe").write_bytes(b"MZ")
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", str(install / "Surasura.exe"))
    return install


def _hato(tools, tmp_path, **fields):
    hato_cli = tmp_path / "ハト" / "hato-cli.exe"
    hato_cli.parent.mkdir(exist_ok=True)
    hato_cli.write_bytes(b"MZ")
    entry = {"schema": 1, "tool": "hato", "name": "hato", "version": "1.1.0", "cli": str(hato_cli), "app": None,
             "contract": 1, "verbs": ["pairings"], "updated": "2026-10-12T09:00:00Z"}
    entry.update(fields)
    tools.mkdir(exist_ok=True)
    (tools / "hato.json").write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    return entry


def test_a_relative_SURASURA_TOOLS_CLI_is_advertised_as_an_absolute_path(root, tools, tmp_path, monkeypatch):
    """P3.2-B05. hato starts the command line from its own working folder: a relative path written as it was given
    would name a program hato can't find. The entry names it absolute, resolved where Surasura ran."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SURASURA_TOOLS_CLI", os.path.join("開発", "surasura-cli.cmd"))
    got = tools_entry.entry({})
    assert os.path.isabs(got["cli"])
    assert got["cli"] == str(tmp_path / "開発" / "surasura-cli.cmd")


def test_an_entry_on_disk_that_is_a_json_list_is_rewritten_never_a_crash(root, tools, frozen):
    """P3.2-B09. Another program (or a broken write) left surasura.json as valid JSON that isn't an object: the
    refresh writes Surasura's entry over it. Why: comparing a list field by field raised, so the window's start and
    every command-line call would fail to refresh until someone deleted the file by hand."""
    tools.mkdir()
    (tools / "surasura.json").write_text('["スラスラ", 1]', encoding="utf-8")
    assert tools_entry.refresh({}) is True
    assert json.loads((tools / "surasura.json").read_text(encoding="utf-8"))["tool"] == "surasura"


def _sized_cli(tmp_path, monkeypatch, size):
    """SURASURA_TOOLS_CLI set so the entry as written is exactly `size` bytes (the name padded with ASCII letters,
    one byte each in the JSON)."""
    folder = tmp_path / "開発"

    def written(name):
        monkeypatch.setenv("SURASURA_TOOLS_CLI", str(folder / name))
        new = tools_entry.entry({})
        return len((json.dumps(new, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    base = written("surasura-cli.cmd")
    name = "s" * (size - base) + "surasura-cli.cmd"
    assert written(name) == size
    return name


def test_an_entry_of_exactly_4096_bytes_is_written_and_one_byte_more_is_refused(root, tools, tmp_path, monkeypatch):
    """P3.2-B15. §3's limit is "at most 4 KiB": an entry of exactly 4,096 bytes is written whole; 4,097 is refused."""
    _sized_cli(tmp_path, monkeypatch, tools_entry.MAX_BYTES)
    assert tools_entry.refresh({}) is True
    assert os.path.getsize(tools / "surasura.json") == tools_entry.MAX_BYTES
    _sized_cli(tmp_path, monkeypatch, tools_entry.MAX_BYTES + 1)
    assert tools_entry.refresh({}) is False
    assert os.path.getsize(tools / "surasura.json") == tools_entry.MAX_BYTES, "the old entry kept"


def test_a_replace_that_keeps_failing_sleeps_only_between_tries(root, tools, frozen, monkeypatch):
    """P3.2-B18. §3: "retried for up to 1 s" — ten waits between eleven tries, none after the last, so a reader that
    never lets go costs the window's worker or the command line one second, not more."""
    tools_entry.refresh({})
    sleeps = []
    monkeypatch.setattr(tools_entry, "time", types.SimpleNamespace(sleep=sleeps.append))

    def refused(src, dst):
        raise PermissionError(32, "The process cannot access the file because it is being used")
    monkeypatch.setattr(tools_entry.os, "replace", refused)
    assert tools_entry.refresh({"connect_enabled": True}) is False
    assert sleeps == [tools_entry.REPLACE_WAIT] * (tools_entry.REPLACE_TRIES - 1)


def test_an_entry_speaking_an_older_contract_is_read(tools, tmp_path):
    """P3.2-B23. Only a contract newer than Surasura's makes a tool absent: an older one (a hato built against
    contract 0) is still read, so it can still be asked."""
    assert contract.CONTRACT >= 1
    entry = _hato(tools, tmp_path, contract=contract.CONTRACT - 1)
    assert tools_entry.read("hato") == entry

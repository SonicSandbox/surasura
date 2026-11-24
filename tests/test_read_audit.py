"""tests/read_audit.py: the guard that no test reads a file the public repo ignores (Minato-TS, 2026-11-20).

Why: 2026-11-20, a lane's test leaned on this PC's lists/jmnedict.zip (git-ignored, so absent on GitHub's runner) and
went red on GitHub only, one CI cycle later. run_tests.py --guards and --touched-callers load the audit
(`-p tests.read_audit`, SURASURA_READ_AUDIT=ignored); these tests drive its hook and its git question directly.
"""
import os
import subprocess
import sys

import pytest

from tests import read_audit


def _git(root, *args):
    subprocess.run(["git", "-c", "user.name=Minato-TS", "-c", "user.email=minato-ts@example.invalid", *args], cwd=root,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def audited(tmp_path, monkeypatch):
    """A repository of its own as the audit's top folder, a test under way, nothing recorded yet."""
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(read_audit, "ROOT", os.path.normcase(str(root)))
    monkeypatch.setitem(read_audit._STATE, "test", "tests/test_x.py::test_reads")
    monkeypatch.setitem(read_audit._STATE, "reads", {})
    monkeypatch.setitem(read_audit._STATE, "written", set())
    return root


def test_a_read_under_the_top_folder_is_recorded_from_the_top(audited):
    path = audited / "lists" / "jmnedict.zip"
    read_audit._hook("open", (str(path), "r", os.O_RDONLY))
    assert read_audit._STATE["reads"] == {"tests/test_x.py::test_reads": {"lists/jmnedict.zip"}}


@pytest.mark.parametrize("args", [
    ("{root}/debug/test_times.json", "w", os.O_WRONLY | os.O_CREAT),       # written, never read
    ("{root}/debug/log.txt", "a", os.O_APPEND),
    ("{root}/../elsewhere/台本.txt", "r", os.O_RDONLY),                    # outside the repo
    ("{root}/app/__pycache__/x.cpython-311.pyc", "r", os.O_RDONLY),      # an import's cache
    ("{root}/.git/HEAD", "r", os.O_RDONLY),
    (7, "r", os.O_RDONLY),                                                  # a file descriptor
])
def test_writes_files_outside_the_repo_caches_and_descriptors_are_not_reads(audited, args):
    path = args[0].format(root=str(audited)) if isinstance(args[0], str) else args[0]
    read_audit._hook("open", (path, args[1], args[2]))
    assert read_audit._STATE["reads"] == {}


def test_a_file_the_run_wrote_and_read_back_is_its_own_never_named(audited):
    """(The review's false alarm: a test that writes an ignored output into the tree and reads it back has it on
    GitHub's runner too.)"""
    (audited / ".gitignore").write_text("results/\n", encoding="utf-8")
    _git(str(audited), "init", "-q")
    _git(str(audited), "add", "-A")
    _git(str(audited), "commit", "-q", "-m", "base")
    out = str(audited / "results" / "ja_frequency.csv")
    read_audit._hook("open", (out, "w", os.O_WRONLY | os.O_CREAT))
    read_audit._hook("open", (out, "r", os.O_RDONLY))
    assert read_audit._STATE["reads"] == {"tests/test_x.py::test_reads": {"results/ja_frequency.csv"}}
    assert read_audit.ignored_reads(read_audit._STATE["reads"], read_audit._STATE["written"]) == {}


def test_a_data_file_opened_while_a_module_is_imported_still_counts(audited, tmp_path, monkeypatch):
    """(The review's miss: a module that opens lists/jmnedict.zip as it is imported.) Only code an import reads is
    left out."""
    data = audited / "lists" / "names.txt"
    data.parent.mkdir()
    data.write_text("東京\n", encoding="utf-8")
    mod = tmp_path / "reads_at_import.py"
    mod.write_text(f"open({str(data)!r}, encoding='utf-8').read()\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.addaudithook(lambda e, a: read_audit._hook(e, a) if read_audit._STATE.get("probe") else None)
    monkeypatch.setitem(read_audit._STATE, "probe", True)
    import importlib
    importlib.import_module("reads_at_import")
    monkeypatch.setitem(read_audit._STATE, "probe", False)
    assert "lists/names.txt" in read_audit._STATE["reads"]["tests/test_x.py::test_reads"]


def test_nothing_is_recorded_between_tests(audited, monkeypatch):
    monkeypatch.setitem(read_audit._STATE, "test", None)
    read_audit._hook("open", (str(audited / "data" / "ja" / "本.txt"), "r", os.O_RDONLY))
    assert read_audit._STATE["reads"] == {}


def test_only_the_files_the_public_repo_ignores_are_named(audited):
    """Tracked: fine. Ignored (on this PC only): named. Untracked but not ignored (a new file the lane will commit):
    not this guard's — git status shows it."""
    (audited / ".gitignore").write_text("lists/\n*.local.json\n", encoding="utf-8")
    (audited / "tests").mkdir()
    (audited / "tests" / "台本.txt").write_text("雨が降る\n", encoding="utf-8")
    _git(str(audited), "init", "-q")
    _git(str(audited), "add", "-A")
    _git(str(audited), "commit", "-q", "-m", "base")
    reads = {"tests/test_a.py::test_one": {"tests/台本.txt", "lists/jmnedict.zip"},
             "tests/test_a.py::test_two": {"tests/台本.txt"},
             "tests/test_b.py::test_three": {"names.local.json", "tests/new_sample.srt"}}
    assert read_audit.ignored_reads(reads) == {"tests/test_a.py::test_one": ["lists/jmnedict.zip"],
                                               "tests/test_b.py::test_three": ["names.local.json"]}


def test_code_and_the_tolerated_paths_are_never_named_but_user_data_is(audited):
    """A whole-repo scan reads the private modules' sources where they are checked out (GitHub's runner has none, and
    the scan has less to read, never a red); the private docs' never-public list, the shard packer's times and a
    local-only test folder are read only when there. A user's own lists are another matter: named (2026-11-20's
    survey found a test reading the tree's User Files/ja lists)."""
    local = [folder for folder, _why in read_audit.TOLERATED if folder.startswith("tests/")][0]
    (audited / ".gitignore").write_text(f"modules/koe/\ndocs/agent instructions/\ndebug/\n{local}\nUser Files/\n",
                                        encoding="utf-8")
    _git(str(audited), "init", "-q")
    _git(str(audited), "add", "-A")
    _git(str(audited), "commit", "-q", "-m", "base")
    reads = {"tests/qt/test_scan.py::test_all": {"modules/koe/server.py", "docs/agent instructions/never-public.txt",
                                                  "debug/test_times.json", local + "台本.txt"},
             "tests/test_helper.py::test_lists": {"User Files/ja/Blacklist.txt", "modules/koe/voices/声.json"}}
    assert read_audit.ignored_reads(reads) == {"tests/test_helper.py::test_lists": [
        "User Files/ja/Blacklist.txt", "modules/koe/voices/声.json"]}


def test_a_local_only_tests_own_reads_are_never_named_but_a_public_tests_are(audited):
    """Why: the local-only parsing suite reads its own local data (debug/, docs/assets/zh_gold) and never runs on
    GitHub's runner; --touched-callers picked it by a name it shares with app/send_report.py (2026-11-22, train 59) and
    the audit went red on reads GitHub can never meet. A public test reading the same file is still named."""
    local = [folder for folder, _why in read_audit.TOLERATED if folder.startswith("tests/")][0]
    (audited / ".gitignore").write_text(f"debug/\ndocs/assets/zh_gold/\n{local}\n", encoding="utf-8")
    _git(str(audited), "init", "-q")
    _git(str(audited), "add", "-A")
    _git(str(audited), "commit", "-q", "-m", "base")
    reads = {local + "test_parsing_suite.py::test_variants": {"debug/parsing_fixes_run/step4/n2_joins.json",
                                                              "docs/assets/zh_gold/ud/zh_hk-ud-test.conllu"},
             local.replace("/", "\\") + "test_parsing_suite.py::test_case[ZH-SEG-1]": {"debug/分詞.json"},
             "tests/test_send_report.py::test_zip": {"docs/assets/zh_gold/ud/zh_hk-ud-test.conllu"}}
    assert read_audit.ignored_reads(reads) == {"tests/test_send_report.py::test_zip": [
        "docs/assets/zh_gold/ud/zh_hk-ud-test.conllu"]}


def test_the_top_folders_env_is_tolerated_but_never_a_users_file_or_another_env(audited):
    """Why: app/telemetry.py calls load_dotenv() as it is imported, which reads the top folder's .env when there is one
    (every working copy keeps a dev one; GitHub's runner has none, and telemetry then reads nothing): the first test of
    a run that imported telemetry went red on it, in every copy (2026-11-21). A tolerated file is that one file at that
    place: a .env in a user's folder, one under another name, or a file beside the shard packer's times is still
    named, and so is a user's own list."""
    (audited / ".gitignore").write_text(".env\n.env.*\ndebug/\nUser Files/\n", encoding="utf-8")
    _git(str(audited), "init", "-q")
    _git(str(audited), "add", "-A")
    _git(str(audited), "commit", "-q", "-m", "base")
    read_audit._hook("open", (str(audited / ".env"), "r", os.O_RDONLY))
    assert read_audit._STATE["reads"] == {"tests/test_x.py::test_reads": {".env"}}
    reads = {"tests/test_scrub.py::test_first": {".env", "debug/test_times.json"},
             "tests/test_send_report.py::test_zip": {".env", "User Files/.env", "User Files/ja/KnownWord.json",
                                                     ".env.local", "debug/test_times.json.bak"}}
    assert read_audit.ignored_reads(reads) == {"tests/test_send_report.py::test_zip": [
        ".env.local", "User Files/.env", "User Files/ja/KnownWord.json", "debug/test_times.json.bak"]}


def test_no_repository_means_no_verdict_never_a_pass(audited):
    assert read_audit.ignored_reads({"tests/test_a.py::test_one": {"lists/jmnedict.zip"}}) is None


def test_a_private_modules_own_tracked_data_is_tolerated_but_never_a_users_file(audited):
    """Why: a private module ships data in its own folder (modules/irodori/voices/*.json, the voices Piyo's tests list;
    modules/immersion_architect/architect_settings.json, read by that module's own suite). The public repo ignores
    modules/*, so the audit named them in every local run with the module checked out (2026-11-21), though they are
    there wherever the module is: GitHub's runner has neither the module nor its suite, and the public tests pass
    without it. Tolerated: a file under modules/ the private repo (the top folder's <name>.priv.git, as `git priv`)
    tracks. Still named: a module's file the private repo doesn't track (a download, a learner's own file), and
    anything outside modules/, even if the private repo tracked it."""
    (audited / ".gitignore").write_text("modules/*\nUser Files/\ndata/\nresults/\nsettings.json\n", encoding="utf-8")
    _git(str(audited), "init", "-q")
    _git(str(audited), "add", "-A")
    _git(str(audited), "commit", "-q", "-m", "base")
    shipped = ["modules/irodori/voices/woman-20s.json", "modules/immersion_architect/architect_settings.json",
               "settings.json", "data/ja/本.txt"]                     # (the last two: never tolerated, tracked or not)
    for rel in shipped:
        (audited / rel).parent.mkdir(parents=True, exist_ok=True)
        (audited / rel).write_text('{"name": "女性・20代"}\n', encoding="utf-8")
    priv = ["--git-dir=" + str(audited) + ".priv.git", "--work-tree=" + str(audited)]
    _git(str(audited), *priv, "init", "-q")
    _git(str(audited), *priv, "add", "-f", *shipped)
    _git(str(audited), *priv, "commit", "-q", "-m", "private")
    reads = {"tests/test_mcp_piyo_rounds.py::test_voices": {"modules/irodori/voices/woman-20s.json"},
             "modules/immersion_architect/tests/test_ia.py::test_load": {
                 "modules/immersion_architect/architect_settings.json"},
             "tests/test_mcp_steps_aside.py::test_lists": {"modules/irodori/voices/my-own.json",
                                                           "modules/irodori/runtime/model.safetensors",
                                                           "User Files/ja/KnownWord.json", "data/ja/本.txt",
                                                           "results/ja_frequency.csv", "settings.json"}}
    assert read_audit.ignored_reads(reads) == {"tests/test_mcp_steps_aside.py::test_lists": [
        "User Files/ja/KnownWord.json", "data/ja/本.txt", "modules/irodori/runtime/model.safetensors",
        "modules/irodori/voices/my-own.json", "results/ja_frequency.csv", "settings.json"]}


def test_without_the_private_repo_a_modules_data_is_still_named(audited):
    """No <name>.priv.git beside the top folder (or git can't read it): nothing more is tolerated, the read stays a red."""
    (audited / ".gitignore").write_text("modules/*\n", encoding="utf-8")
    _git(str(audited), "init", "-q")
    _git(str(audited), "add", "-A")
    _git(str(audited), "commit", "-q", "-m", "base")
    reads = {"tests/test_mcp_piyo_rounds.py::test_voices": {"modules/irodori/voices/woman-20s.json"}}
    assert read_audit.ignored_reads(reads) == {"tests/test_mcp_piyo_rounds.py::test_voices": [
        "modules/irodori/voices/woman-20s.json"]}

"""T1 B (Sonic, 2026-10-21): tsubasa ships as a third program in Surasura's bundle — tsubasa.exe, frozen from the
tsubasa-sync requirements.txt pins, beside Surasura.exe and surasura-cli.exe and sharing their _internal\\ — and "make
sure that tsubasa updates are included when needed". A tsubasa fix reaches users only in a Surasura update, so the pin
must be exact, the build must freeze exactly the pin, and a bundle whose tsubasa.exe isn't the pin (or lost its name
tables) must stop the build loudly, never ship. The build ritual moves the pin to tsubasa's latest release first
(packaging/tsubasa_pin.py). Nothing here runs PyInstaller or reaches GitHub: the spec is parsed, the build stubbed,
the release read through a stand-in."""
import ast
import importlib.util
import json
import os
import re
import sys
import warnings

import pytest

import package_app
from app import updater
from tests.test_packaging_config import _program, _stubbed_build

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(PROJECT, "packaging", "Surasura.spec")
ENTRY = os.path.join(PROJECT, "packaging", "tsubasa_entry.py")


def _pin_script():
    spec = importlib.util.spec_from_file_location("tsubasa_pin_under_test",
                                                  os.path.join(PROJECT, "packaging", "tsubasa_pin.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _requirements(tmp_path, text, newline="\n"):
    path = tmp_path / "requirements.txt"
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return str(path)


# --- the pin -------------------------------------------------------------------------------------------------------------

def test_the_shipped_requirements_pin_tsubasa_exactly():
    # An exact pin is what makes the bundle reproducible: a range would freeze whatever pip found that day.
    pin = package_app.tsubasa_pin()
    assert pin and re.fullmatch(r"\d+\.\d+\.\d+", pin)
    with open(os.path.join(PROJECT, "requirements.txt"), encoding="utf-8") as f:
        assert f"tsubasa-sync=={pin}" in [line.strip() for line in f]


def test_the_installed_tsubasa_is_the_pin_wherever_it_is_installed():
    # A developer or the package proof that installed requirements.txt freezes exactly the pin; an older tsubasa left
    # in this Python fails here, loudly, before any build. (The core shards on GitHub don't install tsubasa.)
    have = package_app.tsubasa_installed()
    if have is None:
        pytest.skip("tsubasa-sync is not installed in this Python")
    assert have == package_app.tsubasa_pin()


@pytest.mark.parametrize("text, pin", [
    ("pandas\njieba\ntsubasa-sync==0.1.10\n", "0.1.10"),
    ("# 翼: tsubasa's own package\ntsubasa-sync == 0.2.0   # pinned (T1 B)\n", "0.2.0"),
    ("TSUBASA_SYNC==1.0.3\n", "1.0.3"),                          # pip reads names in any case, - _ . alike
    ("tsubasa-sync>=0.1.10\n", None),                            # a range is no pin
    ("tsubasa-sync~=0.1.10\n", None),
    ("tsubasa-sync[all]==0.1.10\n", None),                       # extras would bring unapproved dependencies
    ("tsubasa-sync==0.1.10; python_version>='3.10'\n", None),    # a marker: maybe not installed at all
    ("tsubasa-sync==0.1.10\ntsubasa-sync==0.1.9\n", None),       # two pins: which one ships?
    ("pandas\nfugashi\n", None),
    ("tsubasa-sync-extras==0.1.10\n", None),                     # another package's name
    ("# tsubasa-sync==0.1.10\n", None),                          # a comment pins nothing
])
def test_only_one_exact_pin_counts(tmp_path, text, pin):
    assert package_app.tsubasa_pin(_requirements(tmp_path, text)) == pin


def test_the_pin_reads_through_a_bom_and_crlf_and_a_missing_file_is_no_pin(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_bytes(b"\xef\xbb\xbftsubasa-sync==0.1.10\r\npandas\r\n")
    assert package_app.tsubasa_pin(str(path)) == "0.1.10"
    assert package_app.tsubasa_pin(str(tmp_path / "absent.txt")) is None


# --- the bundled tsubasa.exe agrees with the pin (the post-build check) --------------------------------------------------

@pytest.mark.parametrize("answer, ok", [
    ((0, "tsubasa 0.1.10"), True),
    ((0, "tsubasa 0.1.9"), False),            # stale: an older tsubasa-sync was frozen
    ((1, "tsubasa 0.1.10"), False),           # its self-check failed: the name tables didn't ride along
    ((0, "tsubasa 0.1.10-dev"), False),
    ((None, "it won't run (FileNotFoundError)"), False),
    ((0, ""), False),
])
def test_a_bundle_whose_tsubasa_is_not_the_whole_pin_fails(tmp_path, answer, ok):
    asked = []
    failures, said = package_app.check_tsubasa(str(tmp_path), pin="0.1.10",
                                               version_of=lambda exe: asked.append(exe) or answer)
    assert asked == [os.path.join(str(tmp_path), "tsubasa.exe")]
    assert said == answer[1]
    assert (failures == []) is ok
    if not ok:
        assert "tsubasa 0.1.10" in failures[0] and repr(answer[1]) in failures[0]


def test_no_pin_fails_the_check_without_running_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(package_app, "tsubasa_pin", lambda path=None: None)
    failures, said = package_app.check_tsubasa(str(tmp_path), version_of=lambda exe: pytest.fail("ran"))
    assert said is None and "pins no tsubasa-sync" in failures[0]


def test_the_version_reader_reads_a_real_programs_first_line_and_survives_a_missing_one(tmp_path):
    # The real reader, on this Python (it prints "Python 3.x.y" for --version) and on a program that isn't there.
    code, first = package_app.tsubasa_version_of(sys.executable)
    assert code == 0 and first == f"Python {sys.version.split()[0]}"
    code, why = package_app.tsubasa_version_of(str(tmp_path / "無い" / "tsubasa.exe"))
    assert code is None and "won't run" in why


def test_the_check_command_reports_a_stale_tsubasa(tmp_path, monkeypatch, capsys):
    # `python package_app.py --check dist\Surasura` (the ritual's re-check) runs the tsubasa check too.
    folder, _config = _program(tmp_path)
    monkeypatch.setattr(package_app, "tsubasa_version_of", lambda exe: (0, "tsubasa 0.0.1"))
    source = open(os.path.join(PROJECT, "package_app.py"), encoding="utf-8").read()
    block = compile(source[source.index('if __name__ == "__main__":'):], "package_app.py", "exec")
    monkeypatch.setattr(sys, "argv", ["package_app.py", "--check", str(folder)])
    with pytest.raises(SystemExit) as stop:
        exec(block, dict(vars(package_app), __name__="__main__"))
    out = capsys.readouterr().out
    assert stop.value.code == 1 and "CHECKS FAILED" in out and "tsubasa 0.0.1" in out


# --- the build: refuses another tsubasa before freezing, and a stale bundle after ---------------------------------------

@pytest.mark.parametrize("installed", [None, "0.1.9", "9.9.9"])
def test_a_build_with_another_tsubasa_installed_stops_before_freezing(tmp_path, monkeypatch, capsys, installed):
    monkeypatch.setattr(package_app, "tsubasa_installed", lambda: installed)
    frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=False)
    assert frozen == [] and seen == {"returned": False}
    out = capsys.readouterr().out
    assert "Build aborted" in out and f"tsubasa-sync {package_app.tsubasa_pin()}" in out and str(installed or "none") in out


def test_a_build_whose_tsubasa_exe_is_stale_fails_before_its_zip_and_release(tmp_path, monkeypatch, capsys):
    pin = package_app.tsubasa_pin()
    monkeypatch.setattr(package_app, "tsubasa_installed", lambda: pin)
    monkeypatch.setattr(package_app, "tsubasa_version_of", lambda exe: (0, "tsubasa 0.0.1"))
    _frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=True)
    assert seen["returned"] is False and "release" not in seen
    out = capsys.readouterr().out
    assert "Build failed" in out and "tsubasa 0.0.1" in out
    assert not [n for n in os.listdir(tmp_path / "dist") if n.endswith(".zip")]


def test_a_build_with_the_pinned_tsubasa_passes_and_says_so(tmp_path, monkeypatch, capsys):
    pin = package_app.tsubasa_pin()
    monkeypatch.setattr(package_app, "tsubasa_installed", lambda: pin)
    monkeypatch.setattr(package_app, "tsubasa_version_of", lambda exe: (0, f"tsubasa {pin}"))
    _frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=False)
    assert seen["returned"] is True and "tsubasa.exe" in seen["checked"]
    assert f"tsubasa {pin}" in capsys.readouterr().out


# --- the program folder, the parts, the updater and the uninstaller carry it ---------------------------------------------

def test_tsubasa_is_one_of_the_programs_every_build_carries_and_the_updater_owns():
    assert "tsubasa.exe" in package_app.PROGRAM_EXES
    assert updater.TSUBASA_EXE_NAME == package_app.TSUBASA_EXE_NAME == "tsubasa.exe"
    assert "tsubasa.exe" in updater.OWNED_ENTRIES      # a later update moves it, never leaves it behind


def test_a_tsubasa_bump_is_its_own_small_part():
    # tsubasa's program and its name tables in one part of their own: a pin bump downloads that part, never the
    # runtime (numpy stays in runtime: the app's own).
    parts = package_app.load_build_config()["parts"]
    for path in ("tsubasa.exe", "_internal/tsubasa/data/aliases.tsv.gz", "_internal/tsubasa/data/decoration.json"):
        assert package_app.part_of(path, parts) == "tsubasa"
    assert package_app.part_of("_internal/tsubasaX/a.py", parts) == "runtime"
    assert package_app.part_of("_internal/numpy/__init__.pyc", parts) == "runtime"


def test_a_built_program_without_tsubasa_fails_its_checks(tmp_path):
    folder, config = _program(tmp_path)
    (folder / "tsubasa.exe").unlink()
    failures, _facts = package_app.check_program(str(folder), config)
    assert any("programs at the top" in f for f in failures)


def test_the_uninstaller_removes_tsubasa_exe_by_name():
    with open(os.path.join(PROJECT, "packaging", "surasura.iss"), encoding="utf-8-sig") as f:
        text = f.read()
    section = text[text.index("[UninstallDelete]"):text.index("[Code]")]
    assert 'Type: files; Name: "{app}\\tsubasa.exe"' in section


# --- the spec: a third slim Analysis, never in the app's import graph (K1) ------------------------------------------------

def test_the_spec_freezes_tsubasa_from_its_console_script_into_the_shared_collect():
    source = open(SPEC, encoding="utf-8").read()
    tree = ast.parse(source)
    block = source[source.index("tsubasa_a = Analysis("):source.index("tsubasa_pyz = PYZ(")]
    assert "'tsubasa_entry.py'" in block
    for excluded in ("'pandas'", "'PyQt6'", "'tkinter'", "'tsubasa.gui'", "'tsubasa.dev'", "'app'"):
        assert excluded in block, excluded
    exes = {kw.value.value for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "EXE"
            for kw in node.keywords if kw.arg == "name"}
    assert exes == {"Surasura", "surasura-cli", "tsubasa"}
    collect = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "COLLECT"]
    assert len(collect) == 1
    args = {a.id if isinstance(a, ast.Name) else f"{a.value.id}.{a.attr}" for a in collect[0].args}
    assert {"tsubasa_exe", "tsubasa_a.binaries", "tsubasa_a.datas"} <= args


def test_the_entry_is_tsubasas_own_console_script_and_nothing_else():
    tree = ast.parse(open(ENTRY, encoding="utf-8").read())
    imports = [(n.module, [a.name for a in n.names]) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert imports == [("tsubasa.cli", ["main"])]


def _imported_names(tree):
    """Every module a file imports: `import x`, `from x import y`, and `importlib.import_module("x")` /
    `__import__("x")` with a literal name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and \
                isinstance(node.args[0].value, str) and \
                (getattr(node.func, "attr", None) == "import_module" or getattr(node.func, "id", None) == "__import__"):
            yield node.args[0].value


def _python_files():
    yield from (os.path.join(PROJECT, name) for name in ("app_entry.py", "updater_helper.py", "package_app.py"))
    for top in ("app", "modules"):
        for root, _dirs, files in os.walk(os.path.join(PROJECT, top)):
            yield from (os.path.join(root, name) for name in files if name.endswith(".py"))


def test_nothing_of_surasuras_imports_tsubasa():
    # K1: tsubasa (GPL) is only ever run as a program; the bundle puts its code beside Surasura's, never inside.
    found = []
    for path in _python_files():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")              # another file's old escapes, not ours
                tree = ast.parse(open(path, encoding="utf-8").read())
        except (SyntaxError, UnicodeDecodeError):
            continue
        found += [os.path.relpath(path, PROJECT) for n in _imported_names(tree) if n.split(".")[0] == "tsubasa"]
    assert found == []


@pytest.mark.parametrize("source, seen", [
    ("import tsubasa", True), ("from tsubasa.cli import main", True), ("import tsubasa.api as api", True),
    ("importlib.import_module('tsubasa')", True), ("__import__('tsubasa.cli')", True),
    ("import tsubasa_helper", False), ("subprocess.run(['tsubasa', '--version'])", False),
])
def test_the_import_scan_sees_every_way_in(source, seen):
    names = list(_imported_names(ast.parse(source)))
    assert any(n.split(".")[0] == "tsubasa" for n in names) is seen


# --- the ritual's step: packaging/tsubasa_pin.py ---------------------------------------------------------------------------

def _release(tag):
    return lambda url: json.dumps({"tag_name": tag, "name": f"tsubasa {tag}"}).encode("utf-8")


@pytest.mark.parametrize("fetch, latest", [
    (_release("v0.1.11"), "0.1.11"),
    (_release("0.2.0"), "0.2.0"),
    (_release("nightly"), None),
    (lambda url: b"<html>rate limited</html>", None),
    (lambda url: (_ for _ in ()).throw(OSError("offline")), None),
])
def test_the_latest_release_is_read_from_its_tag(fetch, latest):
    assert _pin_script().latest_release(fetch) == latest


def test_the_release_is_asked_of_tsubasas_own_repository():
    asked = []
    _pin_script().latest_release(lambda url: asked.append(url) or b"{}")
    assert asked == ["https://api.github.com/repos/SonicSandbox/Tsubasa-sync/releases/latest"]


def test_a_pin_behind_the_release_fails_the_ritual_and_changes_nothing(tmp_path, monkeypatch, capsys):
    path = _requirements(tmp_path, "pandas\ntsubasa-sync==0.1.10\n")
    before = open(path, "rb").read()
    monkeypatch.setattr(package_app, "tsubasa_installed", lambda: "0.1.10")
    assert _pin_script().main([], fetch=_release("v0.1.11"), path=path) == 1
    assert open(path, "rb").read() == before
    assert "--bump" in capsys.readouterr().out


def test_bump_moves_only_the_pin_every_other_byte_kept(tmp_path, monkeypatch):
    path = _requirements(tmp_path, "pandas\n# 翼\ntsubasa-sync==0.1.10   # T1 B\nPyQt6==6.11.*", newline="\r\n")
    monkeypatch.setattr(package_app, "tsubasa_installed", lambda: "0.1.10")
    assert _pin_script().main(["--bump"], fetch=_release("v0.1.11"), path=path) == 0
    assert open(path, "rb").read() == \
        "pandas\r\n# 翼\r\ntsubasa-sync==0.1.11   # T1 B\r\nPyQt6==6.11.*".encode("utf-8")
    assert package_app.tsubasa_pin(path) == "0.1.11"


def test_bump_reads_past_a_byte_order_mark_on_the_pins_own_line(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_bytes(b"\xef\xbb\xbftsubasa-sync==0.1.10\npandas\n")
    _pin_script().bump("0.1.11", str(path))
    assert path.read_bytes() == b"\xef\xbb\xbftsubasa-sync==0.1.11\npandas\n"


def test_the_ritual_passes_only_when_pin_installed_and_release_agree(tmp_path, monkeypatch):
    path = _requirements(tmp_path, "tsubasa-sync==0.1.10\n")
    script = _pin_script()
    monkeypatch.setattr(package_app, "tsubasa_installed", lambda: "0.1.10")
    assert script.main([], fetch=_release("v0.1.10"), path=path) == 0
    monkeypatch.setattr(package_app, "tsubasa_installed", lambda: "0.1.9")     # this Python isn't the pin
    assert script.main([], fetch=_release("v0.1.10"), path=path) == 1


def test_an_unreachable_release_page_says_so_and_changes_nothing(tmp_path, monkeypatch, capsys):
    path = _requirements(tmp_path, "tsubasa-sync==0.1.10\n")
    before = open(path, "rb").read()
    monkeypatch.setattr(package_app, "tsubasa_installed", lambda: "0.1.10")
    assert _pin_script().main(["--bump"], fetch=lambda url: (_ for _ in ()).throw(OSError("offline")), path=path) == 2
    assert open(path, "rb").read() == before
    assert "by hand" in capsys.readouterr().out


def test_bump_refuses_a_requirements_file_without_exactly_one_tsubasa_line(tmp_path):
    path = _requirements(tmp_path, "pandas\n")
    with pytest.raises(ValueError):
        _pin_script().bump("0.1.11", path)

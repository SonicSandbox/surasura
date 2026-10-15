"""S3.1 row 3.1.5 (D1, D2, D8): the Inno Setup script and `package_app.py --installer`. The script is parsed as text
(every directive and flag the spec names; the uninstall list exact); the packager's defines are checked for the real
program and a test build; when Inno Setup's compiler is on this PC, the script is compiled over a tiny program folder
(a test build's defines only: nothing is installed here; the install / uninstall proof is the row's own run)."""
import os
import re
import subprocess
import sys
import uuid

import pytest

import package_app

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISS = os.path.join(PROJECT, "packaging", "surasura.iss")


def _text():
    with open(ISS, encoding="utf-8") as f:
        return f.read()


def _sections():
    """{section name (lower): [its lines]}, comments and blank lines dropped; the preprocessor lines under ''."""
    sections, current = {"": []}, ""
    for raw in _text().splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        match = re.fullmatch(r"\[(\w+)\]", line)
        if match:
            current = match.group(1).lower()
            sections.setdefault(current, [])
            continue
        sections[current].append(line)
    return sections


def _setup():
    directives = {}
    for line in _sections()["setup"]:
        key, _, value = line.partition("=")
        assert key.strip() not in directives, f"{key} given twice"
        directives[key.strip()] = value.strip()
    return directives


def _entries(section):
    """An Inno entry line -> {parameter: value}, e.g. Source / DestDir / Flags."""
    entries = []
    for line in _sections()[section]:
        params = {}
        for part in re.findall(r'(\w+):\s*("[^"]*"|[^;]+)', line):
            params[part[0]] = part[1].strip().strip('"')
        entries.append(params)
    return entries


def _defines():
    """The script's own defaults: #define <name> "<value>" inside its #ifndef blocks."""
    return dict(re.findall(r'^\s*#define (\w+) "([^"]*)"', _text(), re.M))


# --- the directives ----------------------------------------------------------------------------------------------------

def test_the_install_is_per_user_with_no_admin_prompt_into_its_own_fixed_folder():
    setup = _setup()
    assert setup["PrivilegesRequired"] == "lowest"
    assert "PrivilegesRequiredOverridesAllowed" not in setup        # never the "install for everyone" choice
    assert setup["DefaultDirName"] == r"{localappdata}\Programs\{#AppFolder}"
    assert setup["DisableDirPage"] == "yes" and setup["UsePreviousAppDir"] == "no"
    assert setup["ArchitecturesInstallIn64BitMode"] == "x64compatible"


def test_the_appid_is_fixed_and_the_uninstall_name_carries_no_version():
    setup = _setup()
    assert setup["AppId"] == "{{{#AppGuid}}"              # {{ = a literal brace: AppId {<GUID>}
    assert setup["UninstallDisplayName"] == "{#AppName}"
    assert "AppVersion" not in setup["UninstallDisplayName"] and setup["AppVersion"] == "{#AppVersion}"
    assert "#error" in _text()                             # no version given -> no installer


def test_the_mutexes_follow_the_data_name_and_restart_manager_closes_nothing():
    setup = _setup()
    assert setup["AppMutex"] == "{#DataName}.Running"
    assert setup["SetupMutex"] == "{#DataName}.Setup"
    assert setup["CloseApplications"] == "no"


def test_compression_is_lean():
    # Sonic, 2026-10-12: LZMA2, solid, nothing extra bundled.
    setup = _setup()
    assert setup["Compression"] == "lzma2" and setup["SolidCompression"] == "yes"
    assert not _sections().get("tasks") and not _sections().get("components")


def test_every_file_is_replaced_whatever_its_version_and_the_program_is_installed_as_built():
    files = _entries("files")
    assert files and all("ignoreversion" in e["Flags"].split() for e in files)
    assert [(e["Source"], e["DestDir"]) for e in files] == [(r"{#ProgramDir}\*", "{app}")]
    assert {"recursesubdirs", "createallsubdirs"} <= set(files[0]["Flags"].split())


def test_one_start_menu_entry_and_nothing_on_the_desktop():
    icons = _entries("icons")
    assert icons == [{"Name": r"{autoprograms}\{#AppName}", "Filename": r"{app}\Surasura.exe", "WorkingDir": "{app}"}]
    assert "desktop" not in _text().lower()


def test_launch_is_offered_after_an_interactive_install_only():
    run = _entries("run")
    assert len(run) == 1 and run[0]["Filename"] == r"{app}\Surasura.exe"
    assert set(run[0]["Flags"].split()) == {"postinstall", "skipifsilent", "nowait"}


def test_uninstall_deletes_exactly_what_an_update_may_add_and_never_a_wildcard():
    deletes = [(e["Type"], e["Name"]) for e in _entries("uninstalldelete")]
    assert deletes == [("filesandordirs", r"{app}\_internal"), ("files", r"{app}\Surasura.exe"),
                       ("files", r"{app}\surasura-cli.exe"), ("files", r"{app}\updater.exe"),
                       ("files", r"{app}\RELEASE_NOTES.md"), ("files", r"{app}\LICENSE")]
    assert not any("*" in name or "?" in name for _t, name in deletes)
    assert "uninstallrun" not in _sections() and "dirs" not in _sections()


# --- the library page and library.json ---------------------------------------------------------------------------------

def test_the_library_note_is_written_where_path_utils_reads_it():
    code = "\n".join(_sections()["code"])
    assert r"ExpandConstant('{localappdata}\Houseki\{#DataName}\library.json')" in code
    assert '\'{"version": 1, "install": \' + JsonString(ExpandConstant(\'{app}\')) + \', "library": \'' in code


def test_the_library_page_defaults_to_documents_and_takes_a_library_parameter():
    code = "\n".join(_sections()["code"])
    assert "CreateInputDirPage(wpSelectDir" in code
    assert r"ExpandConstant('{userdocs}\Surasura')" in code
    assert "ExpandConstant('{param:LIBRARY|}')" in code


def test_the_installer_never_creates_the_library_folder_and_the_uninstaller_deletes_nothing_of_its_own():
    code = "\n".join(_sections()["code"])
    assert re.findall(r"(ForceDirectories|CreateDir)\(([^)]*\)?)", code) == [("ForceDirectories",
                                                                             "ExtractFileDir(Note)")]
    assert "DelTree" not in code
    assert re.findall(r"DeleteFile\((\w+)\)", code) == ["Note"]    # only library.json, replaced by its new copy


def test_an_upgrade_keeps_library_json_unless_a_library_is_given():
    code = "\n".join(_sections()["code"])
    assert "KeepNote := (LibraryParam = '') and HasLibraryNote;" in code
    assert "if KeepNote then" in code and "Result := (PageID = LibraryPage.ID) and KeepNote;" in code


def test_a_library_inside_the_program_folder_is_refused_silently_too():
    code = "\n".join(_sections()["code"])
    assert "function PrepareToInstall" in code and "Result := LibraryProblem;" in code
    assert "MsgBox(Problem" not in code.replace("SuppressibleMsgBox(Problem", "")   # a silent run never hangs on a box


def test_a_folder_holding_a_program_is_never_the_library():
    """IK-1: a 2.x unzipped into Documents\\Surasura (Surasura.exe and _internal beside its library) is exactly the
    page's default; 3.0 would then work on the 2.x copy in place, and an upgrade skips the page, so nothing could fix
    it. The default steps aside to Documents\\<LibraryFallback> when that folder holds a program, and Next on a folder
    holding one is refused (LibraryProblem: the page, and a silent run's PrepareToInstall)."""
    code = "\n".join(_sections()["code"])
    assert re.findall(r"LibraryFallback = '([^']*)';", code) == ["Surasura Library"]      # the one place it is named
    assert "Surasura Library" not in code.replace("LibraryFallback = 'Surasura Library';", "")
    holds = code[code.index("function HoldsProgram"):code.index("end;", code.index("function HoldsProgram"))]
    assert "FileExists(AddBackslash(Folder) + 'Surasura.exe') or DirExists(AddBackslash(Folder) + '_internal')" in holds
    default = code[code.index("procedure InitializeWizard"):code.index("function ShouldSkipPage")]
    assert ("else if HoldsProgram(ExpandConstant('{userdocs}\\Surasura')) then\n"
            "LibraryPage.Values[0] := AddBackslash(ExpandConstant('{userdocs}')) + LibraryFallback\n"
            "else\n"
            "LibraryPage.Values[0] := ExpandConstant('{userdocs}\\Surasura');") in default
    problem = code[code.index("function LibraryProblem"):code.index("function InitializeSetup")]
    assert "else if HoldsProgram(LibraryFolder) then" in problem and "LibraryFallback" in problem


def test_the_python_side_names_the_same_fallback_and_the_same_marks():
    # The seam (Sonic's answer S3.1-7 pending): one constant each side; a different answer is a one-line change there.
    from app import import_2x
    code = "\n".join(_sections()["code"])
    assert f"LibraryFallback = '{import_2x.LIBRARY_FALLBACK}';" in code
    assert import_2x.PROGRAM_MARKS == ("Surasura.exe", "_internal")


def test_the_uninstallers_last_message_names_the_kept_previous_version():
    # IK-12: Houseki\<name> keeps more than the word index and logs: update\previous holds a whole earlier program,
    # kept for Go back. The last page says so, in plain words.
    code = "\n".join(_sections()["code"])
    message = code[code.index("procedure CurUninstallStepChanged"):]
    assert "update\\previous the earlier version it kept for Go ' +\n'back)" in message


def test_the_put_back_question_defaults_to_keeping_surasura_and_names_both_doors():
    # FT C23 (A-N5): Enter (the default button) is No — the uninstall stops, the way back stays; and the box names
    # both doors to Put Anki back: 順 and Settings -> Data & System.
    code = "\n".join(_sections()["code"])
    box = code[code.index("function InitializeUninstall"):]
    box = box[:box.index("end;")]
    assert "MB_YESNO or MB_DEFBUTTON2" in box
    assert "#$9806" in box and "Settings" in box and "Data & System" in box


# --- the packager's defines --------------------------------------------------------------------------------------------

def test_the_scripts_defaults_are_the_real_programs():
    defines = _defines()
    assert defines["AppGuid"] == package_app.APP_GUID
    assert defines["AppName"] == defines["AppFolder"] == defines["DataName"] == "Surasura"


def test_a_test_build_differs_from_the_real_program_in_every_name(tmp_path):
    real = package_app.installer_defines("3.0.0", "Surasura", str(tmp_path), "Surasura")
    test = package_app.installer_defines("3.0.0", "Surasura-test", str(tmp_path), "Surasura")
    assert real["AppGuid"] == package_app.APP_GUID and real["AppName"] == "Surasura"
    assert real["AppFolder"] == real["DataName"] == "Surasura"
    assert test["AppName"] == "Surasura (test)" and test["AppFolder"] == test["DataName"] == "Surasura-test"
    for key in ("AppGuid", "AppName", "AppFolder", "DataName"):
        assert real[key] != test[key], key
    assert f"{real['DataName']}.Running" != f"{test['DataName']}.Running"
    assert str(uuid.UUID(test["AppGuid"])).upper() == test["AppGuid"]
    assert package_app.installer_defines("3.0.0", "Surasura-test", str(tmp_path), "Surasura")["AppGuid"] == \
        test["AppGuid"]                                    # the same test name, the same AppId: an upgrade
    assert package_app.installer_defines("3.0.0", "Surasura-t2", str(tmp_path), "Surasura")["AppGuid"] != \
        test["AppGuid"]
    assert real["ProgramDir"] == os.path.abspath(str(tmp_path)) and real["AppVersion"] == "3.0.0"


# --- --installer -------------------------------------------------------------------------------------------------------

def _no_iscc(monkeypatch, tmp_path):
    monkeypatch.setattr(package_app, "ISCC_PLACES", (str(tmp_path / "nowhere" / "ISCC.exe"),))
    monkeypatch.setattr(package_app.shutil, "which", lambda name: None)


def test_no_inno_setup_is_a_clear_message_and_no_installer(tmp_path, monkeypatch, capsys):
    _no_iscc(monkeypatch, tmp_path)
    assert package_app.find_iscc() is None
    assert package_app.build_installer(str(tmp_path), "3.0.0", "Surasura-test", "Surasura") is None
    assert "Inno Setup 6's ISCC.exe was not found" in capsys.readouterr().out


def test_installer_without_inno_setup_stops_before_the_freeze(tmp_path, monkeypatch, capsys):
    _no_iscc(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(package_app, "get_version", lambda: "3.0.0")
    monkeypatch.setattr(package_app, "_python_version", lambda: (3, 11, 4))
    monkeypatch.setattr(package_app.subprocess, "run", lambda *a, **k: pytest.fail("nothing is frozen"))
    package_app.build(installer=True, skip_tests=True)
    assert "Build aborted: --installer" in capsys.readouterr().out


def _freeze_reached(tmp_path, monkeypatch, **build_args):
    """build(**build_args) on Python 3.11.2 -> whether it went on to PyInstaller (stubbed: it stops there)."""
    (tmp_path / "app").mkdir()
    with open(os.path.join(PROJECT, "app", "build_info.py"), "rb") as f:
        (tmp_path / "app" / "build_info.py").write_bytes(f.read())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(package_app, "get_version", lambda: "3.0.0")
    monkeypatch.setattr(package_app, "_python_version", lambda: (3, 11, 2))
    reached = []
    monkeypatch.setattr(package_app.subprocess, "run",
                        lambda cmd, **k: reached.append(cmd) or subprocess.CompletedProcess(cmd, 1))
    package_app.build(skip_tests=True, **build_args)
    return bool(reached)


def test_a_real_release_stops_on_a_python_below_the_floor(tmp_path, monkeypatch, capsys):
    assert not _freeze_reached(tmp_path, monkeypatch, release=True)
    assert "Build aborted: a release needs Python" in capsys.readouterr().out


def test_a_test_release_only_warns_on_a_python_below_the_floor(tmp_path, monkeypatch, capsys):
    assert _freeze_reached(tmp_path, monkeypatch, release=True, data_name="Surasura-test")
    assert "WARNING: building on Python" in capsys.readouterr().out


def test_the_real_name_in_another_case_is_no_test_release(tmp_path, monkeypatch, capsys):
    # `--release --data-name surasura` on Python 3.11.2 skipped the floor as a "test build"; it is the real
    # install's name on Windows, so the build stops before freezing.
    assert not _freeze_reached(tmp_path, monkeypatch, release=True, data_name="surasura")
    assert "Build aborted" in capsys.readouterr().out


# --- packaging/install_proof.py: only ever a test identity, only ever a stand-in profile --------------------------------

def _install_proof():
    import importlib.util
    spec = importlib.util.spec_from_file_location("install_proof_under_test",
                                                  os.path.join(PROJECT, "packaging", "install_proof.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["Surasura", "surasura", "SURASURA"])
def test_the_install_proof_refuses_the_real_name_in_any_case(tmp_path, monkeypatch, name):
    """`--data-name surasura` passed the proof's refusal; on Windows its program folder and Houseki folders are
    the real install's, which `uninstall` removes."""
    proof = _install_proof()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    with pytest.raises(SystemExit):
        proof.identity(name)
    assert proof.identity("Surasura-test")["name"] == "Surasura (test)"


@pytest.mark.skipif(sys.platform != "win32", reason="the install proof runs on Windows only")
@pytest.mark.parametrize("given", ["same", "case", "trailing separator"])
def test_the_install_proof_refuses_this_users_own_profile(tmp_path, monkeypatch, given):
    """`--profile C:\\Users\\<name>` made the "stand-in" the real profile: the real program folder, the real
    Houseki folders removed by `uninstall`. Refused before anything is moved or made (`isolate` never runs)."""
    proof = _install_proof()
    me = tmp_path / "Users" / "Michael"
    monkeypatch.setenv("USERPROFILE", str(me))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    isolated = []
    monkeypatch.setattr(proof, "isolate", lambda profile: isolated.append(profile) or pytest.fail("isolated"))
    profile = {"same": str(me), "case": str(me).upper(), "trailing separator": str(me) + os.sep}[given]
    with pytest.raises(SystemExit) as refused:
        proof.main(["uninstall", "--profile", profile])
    assert "own profile" in str(refused.value) and isolated == []
    assert not me.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="the install proof runs on Windows only")
def test_the_install_proof_takes_a_stand_in_profile(tmp_path, monkeypatch):
    proof = _install_proof()
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "Users" / "Michael"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))

    def stop_here(profile):
        raise RuntimeError(f"isolated in {profile}")
    monkeypatch.setattr(proof, "isolate", stop_here)
    with pytest.raises(RuntimeError, match="isolated in"):
        proof.main(["uninstall", "--profile", str(tmp_path / "Users" / "Michael" / "stand-in")])


@pytest.mark.skipif(sys.platform != "win32", reason="the install proof runs on Windows only")
def test_the_install_proof_points_the_swappers_recovery_entry_at_its_own_key_and_uninstall_removes_it(tmp_path,
                                                                                                       monkeypatch):
    """Every folder swap writes a next-sign-in entry (S3.1-6): in a proof run it goes under the stand-in profile's own
    HKCU\\Software\\SurasuraTests key — the one the swapper honours — never the user's RunOnce; the uninstall step
    takes the key away."""
    import winreg
    proof = _install_proof()
    for name in ("USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "SURASURA_TEST_RUNONCE",
                 "SURASURA_TEST_ROOT", "PYTEST_CURRENT_TEST"):
        # isolate() rewrites or removes each: put back exactly after (without SURASURA_TEST_ROOT every later test in
        # this process would write the real data folders)
        if name in os.environ:
            monkeypatch.setenv(name, os.environ[name])
        else:
            monkeypatch.delenv(name, raising=False)
    profile = str(tmp_path / "stand-in")
    proof.isolate(profile)
    key = os.environ["SURASURA_TEST_RUNONCE"]
    assert key.startswith("Software\\SurasuraTests\\install-proof-") and key.endswith("\\RunOnce")
    assert key == proof.proof_key(profile) + "\\RunOnce", "the same key for every step run in that profile"
    assert proof.proof_key(profile) != proof.proof_key(str(tmp_path / "another"))
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as made:
            winreg.SetValueEx(made, "SurasuraUpdateRecovery-test", 0, winreg.REG_SZ, "left by a cut-off swap")
        assert proof.forget_proof_key(profile) is False
        with pytest.raises(FileNotFoundError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, proof.proof_key(profile))
    finally:
        proof.forget_proof_key(profile)                                 # never left behind, whatever failed


ISCC = package_app.find_iscc()


@pytest.mark.skipif(not ISCC, reason="Inno Setup 6 is not on this PC")
def test_the_script_compiles_into_the_named_installer(tmp_path, monkeypatch):
    # A tiny program folder, a test build's defines (never the real AppId): ISCC builds Surasura-<ver>-setup.exe.
    program = tmp_path / "dist" / "Surasura"
    (program / "_internal").mkdir(parents=True)
    (program / "Surasura.exe").write_bytes(b"MZ")
    (program / "_internal" / "build_stamp.json").write_text('{"data_name": "Surasura-test"}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    out = package_app.build_installer(str(program), "3.0.0", "Surasura-test", "Surasura", out_dir=str(tmp_path / "dist"))
    assert out == str(tmp_path / "dist" / "Surasura-3.0.0-setup.exe") and os.path.getsize(out) > 100_000


@pytest.mark.skipif(not ISCC, reason="Inno Setup 6 is not on this PC")
def test_the_script_refuses_to_compile_without_a_version(tmp_path):
    result = subprocess.run([ISCC, "/Q", f"/O{tmp_path}", f"/DProgramDir={tmp_path}", ISS],
                            capture_output=True, text=True)
    assert result.returncode != 0 and not list(tmp_path.glob("*.exe"))

def test_no_line_starts_with_a_hash_but_a_preprocessor_directive():
    """Inno Setup's preprocessor reads any line that starts with # as its own directive — inside a { comment } and as
    a code line's continuation (#13#10) too — and stops the compile. The compile test runs only where Inno Setup is
    installed, so this one guards every run (FT's uninstaller question had two such lines)."""
    directives = ("#define", "#ifndef", "#ifdef", "#if ", "#else", "#elif", "#endif", "#error", "#include", "#expr",
                  "#pragma", "#undef", "#sub", "#endsub", "#for", "#emit")
    stray = [(number, line) for number, line in enumerate(_text().splitlines(), 1)
             if line.lstrip().startswith("#") and not line.lstrip().startswith(directives)]
    assert stray == []

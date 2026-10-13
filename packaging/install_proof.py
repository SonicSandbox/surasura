"""The package's install proof (S3.1 D19): each step of .github/workflows/package.yml that isn't a build, one command
each, runnable by hand on Windows from a THROWAWAY checkout (`version` rewrites app/__init__.py):

    python packaging/install_proof.py version old|new         a test build's version: build_config's release.min_from
                                                              (old), one past it (new)
    python packaging/install_proof.py key <file>              a throwaway Ed25519 signing key (64 hex), made once
    python packaging/install_proof.py install <folder> <library> --profile <p>   the test installer built into
                                                              <folder>, run silently
    python packaging/install_proof.py update <release> <key file> --profile <p>  the installed program updated to the
                                                              release in <release> (a build's dist) by the one-click path
    python packaging/install_proof.py uninstall --profile <p>  the test install removed silently, then its data folders

Only ever a TEST identity (`--data-name`, default Surasura-test: its own AppId, program folder, data folders and name
"Surasura (test)", S3.1-3); the real one is refused, and so is an install over a test install already there. Only ever
in a stand-in profile (`--profile`): this process and every one it starts — Setup, the programs, the swapper, the
uninstaller — get USERPROFILE, LOCALAPPDATA, APPDATA, TEMP and TMP inside it (Inno Setup's {localappdata},
{userappdata} and {userprograms} follow USERPROFILE, not LOCALAPPDATA: row 3.1.9b's probe), so the only thing outside
it is the test AppId's uninstall entry in HKCU, which the uninstall removes. `update`
is the window's Update button without the window: this process takes the installed program's place (frozen, its
folder, its version) and calls the same service — `update_checker` reads the release folder through
SURASURA_UPDATE_SOURCE and the throwaway key, `updater.prepare_update` assembles the new program from the parts it
needs, `arm_and_launch` hands over to the NEW release's swapper (updater.exe, frozen), which swaps the folder and proves
it (every file's sha256, `surasura-cli.exe --version`); a headless update, so no splash and no window. Each command
prints PROOF OK (exit 0) or PROOF FAILED with the reasons (exit 1)."""
import argparse
import glob
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import package_app  # noqa: E402

UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"     # under HKEY_CURRENT_USER (a per-user install)
SETUP_FLAGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
INNO_FILES = {"unins000.exe", "unins000.dat"}                           # Setup's own, beside the program


class Proof:
    def __init__(self):
        self.failures = []

    def check(self, ok, what):
        print(f"  {'ok  ' if ok else 'FAIL'} {what}", flush=True)
        if not ok:
            self.failures.append(what)
        return ok

    def end(self):
        print("PROOF OK" if not self.failures else "PROOF FAILED:\n  " + "\n  ".join(self.failures), flush=True)
        return 1 if self.failures else 0


def isolate(profile):
    """This process and its children in the stand-in profile `profile` (made when missing), laid out as Windows lays
    out a profile, so Inno Setup's folders and the program's (path_utils reads the variables) are the same ones."""
    profile = os.path.abspath(profile)
    local, roaming = os.path.join(profile, "AppData", "Local"), os.path.join(profile, "AppData", "Roaming")
    temp = os.path.join(local, "Temp")
    for folder in (local, roaming, temp, os.path.join(profile, "Documents")):
        os.makedirs(folder, exist_ok=True)
    os.environ.update(USERPROFILE=profile, LOCALAPPDATA=local, APPDATA=roaming, TEMP=temp, TMP=temp)
    for name in ("SURASURA_TEST_ROOT", "PYTEST_CURRENT_TEST"):
        os.environ.pop(name, None)
    print(f"Stand-in profile: {profile}")


def identity(data_name):
    """Where a test install of `data_name` lives -> {app_id, name, program, local, roaming, shortcut}. The real
    program's data name is refused (SystemExit)."""
    config = package_app.load_build_config()
    if data_name == config["data_name"] or not package_app.valid_data_name(data_name):
        raise SystemExit(f"refused: {data_name!r} is not a test build's data name")
    defines = package_app.installer_defines("0", data_name, PROJECT_ROOT, config["data_name"])
    local, roaming = os.environ["LOCALAPPDATA"], os.environ["APPDATA"]
    return {"app_id": "{" + defines["AppGuid"] + "}", "name": defines["AppName"],
            "program": os.path.join(local, "Programs", defines["AppFolder"]),
            "local": os.path.join(local, "Houseki", data_name), "roaming": os.path.join(roaming, "Houseki", data_name),
            "shortcut": os.path.join(roaming, "Microsoft", "Windows", "Start Menu", "Programs",
                                     defines["AppName"] + ".lnk")}


def uninstall_entry(app_id):
    """HKCU's uninstall entry <app_id>_is1 as {value name: value}, or None when there is none. Read only."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{UNINSTALL}\{app_id}_is1") as key:
            values, index = {}, 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    return values
                values[name] = value
                index += 1
    except OSError:
        return None


def _same(a, b):
    return isinstance(a, str) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _stamp(program):
    with open(os.path.join(program, "_internal", "build_stamp.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def _cli_version(program):
    """`surasura-cli.exe --version` of the installed program -> (exit code, its "app" or None)."""
    proc = subprocess.run([os.path.join(program, package_app.CLI_EXE_NAME), "--version"], capture_output=True,
                          timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        return proc.returncode, json.loads(proc.stdout.decode("utf-8").splitlines()[-1]).get("app")
    except (UnicodeDecodeError, ValueError, IndexError, AttributeError):
        return proc.returncode, None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- the commands ---------------------------------------------------------------------------------------------------

def cmd_version(which):
    min_from = package_app.load_build_config()["release"]["min_from"]
    numbers = min_from.split(".")
    version = min_from if which == "old" else ".".join(numbers[:-1] + [str(int(numbers[-1]) + 1)])
    path = os.path.join(PROJECT_ROOT, "app", "__init__.py")
    with open(path, "rb") as f:
        text = f.read()
    changed, count = re.subn(rb'^__version__ = "[^"\r\n]*"', f'__version__ = "{version}"'.encode("ascii"), text,
                             count=1, flags=re.M)
    if count != 1:
        raise SystemExit("app/__init__.py has no __version__ line")
    with open(path, "wb") as f:
        f.write(changed)
    print(f"app/__init__.py: __version__ = \"{version}\" ({which}; release.min_from is {min_from})")
    return 0


def cmd_key(path):
    if not os.path.isfile(path):
        with open(path, "w", encoding="ascii") as f:
            f.write(secrets.token_hex(32) + "\n")
    print("A throwaway signing key is ready (never printed).")
    return 0


def cmd_install(folder, library, ident):
    p = Proof()
    program = ident["program"]
    there = [x for x in (program, ident["local"], ident["shortcut"]) if os.path.exists(x)]
    if there or uninstall_entry(ident["app_id"]) is not None:
        raise SystemExit(f"refused: a test install is already here ({there or ident['app_id']}); uninstall it first")
    setups = glob.glob(os.path.join(folder, "Surasura-*-setup.exe"))
    if not p.check(len(setups) == 1 and not os.path.exists(library),
                   f"one installer in {folder} ({[os.path.basename(s) for s in setups]}), no library folder yet"):
        return p.end()
    log = os.path.join(os.path.dirname(os.path.abspath(library)), "setup-install.log")
    code = subprocess.run([setups[0], *SETUP_FLAGS, f"/LIBRARY={library}", f"/LOG={log}"], timeout=1200).returncode
    if not p.check(code == 0, f"silent install: Setup exit {code} (its log: {log})"):
        return p.end()
    version = _stamp(program)["version"]
    p.check(os.path.basename(setups[0]) == package_app.installer_name(version), f"{program} holds {version}")
    p.check(all(os.path.isfile(os.path.join(program, n)) for n in (*package_app.PROGRAM_EXES, "unins000.exe")),
            "the three programs and Inno's uninstaller in the program folder")
    try:
        with open(os.path.join(ident["local"], "library.json"), "r", encoding="utf-8") as f:
            note = json.load(f)
    except (OSError, ValueError):
        note = {}
    p.check(note.get("version") == 1 and _same(note.get("install"), program) and _same(note.get("library"), library),
            f"library.json names the program and the library ({note})")
    entry = uninstall_entry(ident["app_id"]) or {}
    p.check(entry.get("DisplayName") == ident["name"] and entry.get("DisplayVersion") == version and
            _same(entry.get("Inno Setup: App Path"), program),
            f"HKCU uninstall entry {ident['app_id']}_is1: {ident['name']} {version} "
            f"({entry.get('DisplayName')} {entry.get('DisplayVersion')})")
    p.check(os.path.isfile(ident["shortcut"]), f"Start-menu entry {os.path.basename(ident['shortcut'])}")
    code, said = _cli_version(program)
    p.check(code == 0 and said == version, f"installed surasura-cli.exe --version: exit {code}, {said}")
    p.check(not os.path.exists(library), "the library folder is never made by Setup or --version (D2, D3)")
    return p.end()


def cmd_update(release, key_file, ident):
    p = Proof()
    program = ident["program"]
    old = _stamp(program)["version"]
    with open(key_file, "r", encoding="ascii") as f:
        seed = bytes.fromhex(f.read().strip())
    # This process takes the installed program's place: frozen, its _internal, its exe — then the service.
    sys.frozen = True
    sys._MEIPASS = os.path.join(program, "_internal")
    sys.executable = os.path.join(program, "Surasura.exe")
    from app import ed25519, update_checker, updater
    os.environ[update_checker.UPDATE_SOURCE_ENV] = os.path.abspath(release)
    os.environ[update_checker.TEST_PUBKEY_ENV] = ed25519.public_key(seed).hex()
    updater.__version__ = old
    info = update_checker.get_update_info()
    if not p.check(info is not None and info.format == 2 and info.signed and info.package is not None,
                   f"the release in {release}: format 2, signed, its package read"):
        return p.end()
    new = info.version
    p.check(update_checker.installed_shape() == info.package.get("install_shape"),
            f"the installed program's install shape is the release's ({update_checker.installed_shape()})")
    cls = update_checker.classify_update(old, info)
    p.check(cls == "APP", f"{old} -> {new}: an update by its parts, not the installer ({cls})")
    p.check(updater.can_auto_apply(info), "an installed program may apply it")
    if p.failures:
        return p.end()
    started = time.monotonic()
    marker = updater.prepare_update(info, window=False)
    p.check(not {"qt", "dict"} & set(marker["parts"]),
            f"only the parts holding changed files fetched: {marker['parts']}")
    swapper = updater.arm_and_launch(marker)
    code = swapper.wait(timeout=900)
    try:
        with open(updater.result_path(), "r", encoding="utf-8") as f:
            result = json.load(f)
    except (OSError, ValueError):
        result = {}
    p.check(code == 0 and result.get("status") == "success",
            f"the new swapper: exit {code}, {result.get('status')}: {result.get('reason')} "
            f"({time.monotonic() - started:.0f} s)")
    # The swapped program, as Windows sees it.
    code, said = _cli_version(program)
    p.check(code == 0 and said == new, f"installed surasura-cli.exe --version: exit {code}, {said}")
    files = {f["path"]: f["sha256"] for f in info.package["files"]}
    found = set()
    for root, _dirs, names in os.walk(program):
        found.update(os.path.relpath(os.path.join(root, n), program).replace(os.sep, "/") for n in names)
    wrong = [path for path, want in files.items() if path not in found or
             _sha256(os.path.join(program, *path.split("/"))) != want]
    p.check(not wrong, f"every file of {new} holds its bytes ({len(files)} files; wrong: {wrong[:5]})")
    p.check(found - set(files) <= INNO_FILES, f"no file the release doesn't name ({sorted(found - set(files))[:5]})")
    entry = uninstall_entry(ident["app_id"]) or {}
    p.check(entry.get("DisplayVersion") == new and _same(entry.get("Inno Setup: App Path"), program),
            f"the uninstall entry says {entry.get('DisplayVersion')} (D8)")
    p.check(os.path.isfile(os.path.join(updater.previous_root(), old, "Surasura.exe")),
            f"{old} kept for Go back in update\\previous")
    return p.end()


def cmd_uninstall(ident):
    p = Proof()
    program = ident["program"]
    code = subprocess.run([os.path.join(program, "unins000.exe"), *SETUP_FLAGS], timeout=600).returncode
    p.check(code == 0, f"silent uninstall: exit {code}")
    deadline = time.monotonic() + 120
    while os.path.exists(program) and time.monotonic() < deadline:
        time.sleep(1)
    p.check(not os.path.exists(program), f"{program} gone")
    p.check(uninstall_entry(ident["app_id"]) is None, f"the uninstall entry {ident['app_id']}_is1 gone")
    p.check(not os.path.exists(ident["shortcut"]), "the Start-menu entry gone")
    p.check(os.path.isfile(os.path.join(ident["local"], "library.json")), "the data folders kept by the uninstall (D8)")
    # Then this test identity's own data folders, which an uninstall keeps by design.
    for folder in (ident["local"], ident["roaming"]):
        if os.path.isdir(folder):
            shutil.rmtree(folder)
            print(f"  removed {folder} (the test install's data)")
    return p.end()


def main(argv=None):
    parser = argparse.ArgumentParser(description="The package's install proof (S3.1 D19), one step at a time.")
    parser.add_argument("command", choices=["version", "key", "install", "update", "uninstall"])
    parser.add_argument("args", nargs="*")
    parser.add_argument("--data-name", default="Surasura-test", help="the test build's data name (never the real one)")
    parser.add_argument("--profile", help="install / update / uninstall: the stand-in profile folder (required)")
    a = parser.parse_args(argv)
    wants = {"version": 1, "key": 1, "install": 2, "update": 2, "uninstall": 0}[a.command]
    if len(a.args) != wants:
        parser.error(f"{a.command} takes {wants} argument(s)")
    if a.command == "version":
        if a.args[0] not in ("old", "new"):
            parser.error("version takes old or new")
        return cmd_version(a.args[0])
    if a.command == "key":
        return cmd_key(a.args[0])
    if sys.platform != "win32":
        raise SystemExit("the install proof runs on Windows only")
    if not a.profile:
        parser.error(f"{a.command} needs --profile: it never runs in the real profile")
    identity(a.data_name)                  # the real data name is refused before anything is made
    isolate(a.profile)
    ident = identity(a.data_name)          # its places inside the stand-in profile
    if a.command == "install":
        return cmd_install(os.path.abspath(a.args[0]), os.path.abspath(a.args[1]), ident)
    if a.command == "update":
        return cmd_update(a.args[0], a.args[1], ident)
    return cmd_uninstall(ident)


if __name__ == "__main__":
    sys.exit(main())

import os
import shutil
import subprocess
import sys
import argparse
import json
import re

CLI_EXE_NAME = "surasura-cli.exe"   # the headless command line, built beside Surasura.exe (packaging/Surasura.spec)
TSUBASA_EXE_NAME = "tsubasa.exe"    # tsubasa's command line, built beside them from the pinned tsubasa-sync (T1 B)
PROGRAM_EXES = ("Surasura.exe", CLI_EXE_NAME, TSUBASA_EXE_NAME, "updater.exe")   # exactly these at the top (S3.1 D17)

# The build's one configuration (S3.1 D15): the bundled modules, the Python and SQLite floors, UPX, the window's Qt
# modules and update.json's parts. packaging/Surasura.spec reads the same file; neither reads a settings.json.
BUILD_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packaging", "build_config.json")
OPTIONAL_MODULES = ("junban", "koe", "youtube_downloader", "reels", "immersion_architect")


def load_build_config(path=BUILD_CONFIG):
    """packaging/build_config.json, checked -> the dict. Raises ValueError naming what is wrong: a build never guesses."""
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    problems = []
    modules = config.get("modules")
    if not isinstance(modules, dict) or set(modules) != set(OPTIONAL_MODULES) or \
            not all(isinstance(v, bool) for v in modules.values()):
        problems.append(f"modules must give true/false for exactly {', '.join(OPTIONAL_MODULES)}")
    for key in ("python_min", "sqlite_min"):
        if not isinstance(config.get(key), str) or not _version_tuple(config.get(key)):
            problems.append(f"{key} must be a dotted version")
    if not valid_data_name(config.get("data_name")):
        problems.append("data_name must be a plain folder name (letters, digits, - and _)")
    if config.get("upx") is not False:
        problems.append("upx must be false: UPX stays off (S3.1 D15)")
    qt = config.get("qt_modules")
    if not isinstance(qt, list) or not qt or not all(isinstance(m, str) and m.startswith("Qt") for m in qt):
        problems.append("qt_modules must list the window's Qt modules")
    release = config.get("release")
    if not isinstance(release, dict) or not all(_version_tuple(release.get(k)) for k in ("min_from",
                                                                                         "installer_min_from")):
        problems.append("release must give min_from and installer_min_from")
    elif not _telemetry_url_ok(release.get("telemetry_url")):
        problems.append("release must give telemetry_url, the receiver's https address (update.json carries it)")
    parts = config.get("parts")
    names = [p.get("name") for p in parts if isinstance(p, dict)] if isinstance(parts, list) else []
    if not isinstance(parts, list) or not parts or len(names) != len(parts) or len(set(names)) != len(names) or \
            not all(isinstance(n, str) and n.isalnum() and n.islower() for n in names) or \
            not all(isinstance(p.get("paths"), list) and all(isinstance(x, str) for x in p["paths"]) for p in parts) or \
            parts[-1]["paths"] != [""]:
        problems.append('parts must be named lower-case parts with path lists, the last one [""] (every file left)')
    if problems:
        raise ValueError("packaging/build_config.json: " + "; ".join(problems))
    return config


def _telemetry_url_ok(value):
    """The client's own rule (`update_checker.valid_telemetry_url`): what the release writes, every 3.x reads."""
    from app import update_checker
    return update_checker.valid_telemetry_url(value) is not None


def _version_tuple(text):
    """'3.11.4' -> (3, 11, 4); anything else -> ()."""
    try:
        return tuple(int(p) for p in str(text).split(".")) if text else ()
    except ValueError:
        return ()


def valid_data_name(name, real_name=None):
    """The name of the program's own data folders (%LOCALAPPDATA%\\Houseki\\<data_name>): "Surasura", or a test
    build's own ("Surasura-test"), so a test build never shares a real install's folders. Letters, digits, - and _.
    With `real_name` (build_config's), the real name in another case ("surasura") is refused: Windows' folders ignore
    case, so its program and data folders would be the real install's."""
    return isinstance(name, str) and 0 < len(name) <= 64 and \
        all(c.isascii() and (c.isalnum() or c in "-_") for c in name) and \
        (real_name is None or name == real_name or name.casefold() != real_name.casefold())


def _python_version():
    return tuple(sys.version_info[:3])


def get_version():
    """Reads the version from app/__init__.py without importing the package."""
    init_path = os.path.join("app", "__init__.py")
    with open(init_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('__version__'):
                delim = '"' if '"' in line else "'"
                return line.split(delim)[1]
    return "0.0"

# Optional modules and the build config's flags that bundle them (mirrors packaging/Surasura.spec, which reads the
# same `modules` block). When a module will be included in the build, its own test suite must pass first.
def _included_module_test_dirs(modules):
    dirs = []
    # (The Immersion Architect is never bundled since 2.5 — sunset, RD-D9 — so its suite is no gate.)
    # YouTube Downloader: bundled when the build config names it.
    if modules.get("youtube_downloader") is True:
        d = os.path.join("modules", "youtube_downloader", "tests")
        if os.path.isdir(d):
            dirs.append(d)
    # Speech (Koe): bundled when named and present (it is hidden at runtime, not at build time), so its suite runs
    # whenever it ships.
    if modules.get("koe") is True:
        d = os.path.join("modules", "koe", "tests")
        if os.path.isdir(d):
            dirs.append(d)
    # Reels: bundled when named, so its suite runs before a build that ships it.
    if modules.get("reels") is True:
        d = os.path.join("modules", "reels", "tests")
        if os.path.isdir(d):
            dirs.append(d)
    # Junban: bundled when named, so its suite runs before a build that ships it.
    if modules.get("junban") is True:
        d = os.path.join("modules", "junban", "tests")
        if os.path.isdir(d):
            dirs.append(d)
    return dirs


def run_pre_build_tests(modules):
    """Run the core suite plus the suite of every module that will be bundled.

    Everything shipped must be testable before it builds. Returns True only if all pass.
    """
    suites = ["tests"] + _included_module_test_dirs(modules)
    print(f"Running pre-build tests for: {', '.join(suites)}")

    failed = []
    for suite in suites:
        print(f"\n--- pytest {suite} ---")
        result = subprocess.run([sys.executable, "-m", "pytest", suite, "-q"])
        if result.returncode != 0:
            failed.append(suite)

    if failed:
        print(f"\nPre-build tests FAILED in: {', '.join(failed)}")
        return False
    print("\nAll pre-build tests passed.")
    return True


RUNTIME_BASELINE_FILE = os.path.join("packaging", "runtime_baseline.txt")


def _read_runtime_baseline(default):
    """The earliest app version whose _internal runtime is compatible with new app code.

    Bumped ONLY when the bundled runtime changes (requirements.txt / Python / unidic). Kept
    in a versioned file so the release ritual can't silently forget it.
    """
    try:
        with open(RUNTIME_BASELINE_FILE, "r", encoding="utf-8") as f:
            val = f.read().strip()
            return val or default
    except Exception:
        return default


def _build_updater_exe(final_dist):
    """Build the standalone updater.exe and drop it next to Surasura.exe — every build: each 3.x program carries the
    swapper its next update runs (S3.1 D9), and its `app` part lists it."""
    print("Building updater.exe...")
    cmd = [
        sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
        "--distpath", "dist", "--workpath", "build",
        os.path.join("packaging", "updater.spec"),
    ]
    result = subprocess.run(cmd)
    src = os.path.join("dist", "updater.exe")
    if result.returncode != 0 or not os.path.exists(src):
        print("ERROR: updater.exe was not produced — auto-update will be disabled in this build.")
        return False
    shutil.copy2(src, os.path.join(final_dist, "updater.exe"))
    print("updater.exe bundled into the distribution.")
    return True


REQUIREMENTS_HASH_FILE = os.path.join("packaging", "requirements_hash.txt")


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _warn_if_runtime_changed(full_update):
    """Guard the app-vs-full decision: if requirements.txt changed but this isn't a
    --full-update, the bundled runtime may have moved and app deltas could land on an
    incompatible runtime. Warn loudly (and record the new hash on a full update)."""
    if not os.path.exists("requirements.txt"):
        return
    cur = _sha256("requirements.txt")
    stored = None
    try:
        with open(REQUIREMENTS_HASH_FILE, "r", encoding="utf-8") as f:
            stored = f.read().strip()
    except Exception:
        pass
    if full_update or stored is None:
        try:
            with open(REQUIREMENTS_HASH_FILE, "w", encoding="utf-8") as f:
                f.write(cur + "\n")
        except Exception:
            pass
    elif cur != stored:
        print("\n*** WARNING: requirements.txt changed since the last release, but this is an "
              "APP update. If the bundled runtime changed, abort and rebuild with --full-update. ***\n")


def _build_app_package(final_dist, version, full_update):
    """2.x's release artifacts (the 2.x line's packager, kept for its tests; a 3.x release is `_build_release`):
    the app-only package zip and update.json.

    The app package carries the code-bearing executable (Surasura.exe — its embedded archive
    holds ALL app code) plus the loose report templates. That is the correct minimal unit: in
    a onedir freeze the Python code is NOT loose under _internal/app (that's only assets), so
    replacing the exe is what actually updates the code. For a --full-update release we skip
    the package (users download the full zip) and publish only an update.json (update_type=full).

    Since 2.5 update.json also lists every file the package carries (`files`, K99): each entry's
    name (its path at the top of the zip — the same layout 2.4.0's updater reads), its destination
    in the install folder, its kind and its sha256 (a folder's: `updater.tree_sha256`). 2.5's
    updater swaps exactly that list; surasura-cli.exe is always in it (the app zip refuses a build without it).
    """
    import zipfile

    _warn_if_runtime_changed(full_update)

    baseline = version if full_update else _read_runtime_baseline(version)

    if full_update:
        # A runtime/major release: record the new runtime boundary for future app deltas.
        try:
            with open(RUNTIME_BASELINE_FILE, "w", encoding="utf-8") as f:
                f.write(version + "\n")
            print(f"runtime_baseline.txt updated to {version} (runtime boundary).")
        except Exception as e:
            print(f"Warning: could not update runtime_baseline.txt: {e}")

    manifest = {
        "version": version,
        "update_type": "full" if full_update else "app",
        "runtime_baseline": baseline,
        "critical": False,
        "sha256": "",
        "notes_url": f"https://github.com/SonicSandbox/surasura/releases/tag/v{version}",
    }

    if not full_update:
        exe_src = os.path.join(final_dist, "Surasura.exe")
        cli_src = os.path.join(final_dist, CLI_EXE_NAME)
        templates_dir = os.path.join(final_dist, "_internal", "templates")
        if not os.path.isfile(exe_src) or not os.path.isfile(cli_src) or not os.path.isdir(templates_dir):
            print(f"ERROR: Surasura.exe, {CLI_EXE_NAME} or _internal/templates missing; cannot build app package.")
            return
        pkg_path = os.path.join("dist", f"Surasura_app_v{version}.zip")
        notes_src = os.path.join(final_dist, "RELEASE_NOTES.md")
        manifest["files"] = _package_file_list(final_dist)
        with zipfile.ZipFile(pkg_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(exe_src, "Surasura.exe")
            z.write(cli_src, CLI_EXE_NAME)    # the command line (P1.1); the updater swaps it from 2.5 (K99)
            if os.path.isfile(notes_src):
                z.write(notes_src, "RELEASE_NOTES.md")   # refreshed in place on update (see build_marker)
            for root, dirs, files in os.walk(templates_dir):
                dirs.sort()
                files.sort()
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, templates_dir)
                    z.write(full, os.path.join("templates", rel))

        manifest["sha256"] = _sha256(pkg_path)
        print(f"App package: {pkg_path} ({os.path.getsize(pkg_path) // (1024 * 1024)} MB)")
        print(f"  sha256: {manifest['sha256']}")

    with open(os.path.join("dist", "update.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"update.json written (update_type={manifest['update_type']}, runtime_baseline={baseline}).")
    print("  -> Attach to the GitHub release: full zip"
          + ("" if full_update else ", app package zip") + ", update.json")


def _package_file_list(final_dist):
    """update.json's `files`: what the app package carries, each with its sha256 (K99). Names are the package's
    top-level paths (2.4.0's layout: Surasura.exe, templates/, RELEASE_NOTES.md)."""
    from app import updater
    files = [{"name": "Surasura.exe", "dest": "Surasura.exe", "kind": "file",
              "sha256": updater.sha256_file(os.path.join(final_dist, "Surasura.exe"))}]
    cli = os.path.join(final_dist, "surasura-cli.exe")
    if os.path.isfile(cli):
        files.append({"name": "surasura-cli.exe", "dest": "surasura-cli.exe", "kind": "file",
                      "sha256": updater.sha256_file(cli)})
    notes = os.path.join(final_dist, "RELEASE_NOTES.md")
    if os.path.isfile(notes):
        files.append({"name": "RELEASE_NOTES.md", "dest": "RELEASE_NOTES.md", "kind": "file",
                      "sha256": updater.sha256_file(notes)})
    files.append({"name": "templates", "dest": "_internal/templates", "kind": "dir",
                  "sha256": updater.tree_sha256(os.path.join(final_dist, "_internal", "templates"))})
    return files


# --- The 3.x update format (S3.1 D4, D5, D6) --------------------------------------------------------------------------
# A 3.x release lists every file of the program folder with its sha256 and size, each in one part (build_config's
# `parts`), and publishes each part as one zip; the client downloads only the parts holding a changed or missing file.
# update.json keeps 2.x's keys, written for 2.x readers (2.5 hands over to the installer when one is attached, older
# versions see a download), and adds `format: 2` + `package`, which only 3.x reads. update.json.sig is Ed25519 over the
# manifest's exact bytes, by the key in the file SURASURA_SIGNING_KEY_FILE names (never logged, never on a command line).

SIGNING_KEY_ENV = "SURASURA_SIGNING_KEY_FILE"
MANIFEST_NAME = "update.json"
SIGNATURE_NAME = "update.json.sig"


def part_of(path, parts):
    """The part a program file belongs to: the first part one of whose paths names it (a path ending in / is a
    folder, "" every file). -> the part's name, or None."""
    for part in parts:
        for prefix in part["paths"]:
            if prefix == "" or path == prefix or (prefix.endswith("/") and path.startswith(prefix)):
                return part["name"]
    return None


def program_files(final_dist, parts):
    """Every file of the built program folder: [{path, sha256, size, part}], sorted by path ('/'-separated)."""
    found = []
    for root, dirs, names in os.walk(final_dist):
        dirs.sort()
        for name in sorted(names):
            full = os.path.join(root, name)
            path = os.path.relpath(full, final_dist).replace(os.sep, "/")
            part = part_of(path, parts)
            if part is None:
                raise ValueError(f"{path} is in no part of packaging/build_config.json")
            found.append({"path": path, "sha256": _sha256(full), "size": os.path.getsize(full), "part": part})
    return sorted(found, key=lambda f: f["path"])


def canonical_json(manifest):
    """The manifest's bytes as they are signed and published: sorted keys, indent 2, UTF-8, a final newline."""
    return (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def read_signing_key(path):
    """The 32-byte Ed25519 private key in `path`: 32 raw bytes, or 64 hex characters. Raises ValueError, never
    quoting the file. 32 bytes of hex text are a hex key cut short, never a raw key."""
    with open(path, "rb") as f:
        raw = f.read(4096)
    if len(raw) == 32:
        if raw.strip() and all(c in b"0123456789abcdefABCDEF" for c in raw.strip()):
            raise ValueError("the signing key file holds 32 hex characters: a hex key has 64 (cut short?)")
        return raw
    try:
        seed = bytes.fromhex(raw.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):
        seed = b""
    if len(seed) != 32:
        raise ValueError("the signing key file holds neither 32 bytes nor 64 hex characters")
    return seed


def _build_release(final_dist, version, config, out_dir="dist", installer=None, needs_installer=False):
    """Write a 3.x release's update artifacts into `out_dir`: one zip per part (surasura_part_<name>_v<ver>.zip),
    update.json and, when a signing key is set, update.json.sig. `installer`: the built installer's path in `out_dir`
    (its 2.x hand-off block is written only then). `package.install_shape`: the .iss's shape (`install_shape`); a 3.x
    program stamped with another runs the installer. `needs_installer`: the manual override, for what the shape can't
    see (`--needs-installer`). -> the manifest dict, or None when SURASURA_SIGNING_KEY_FILE names a key that can't be
    used: then nothing is written (a release named a key, so it never goes out unsigned)."""
    import zipfile
    from app import ed25519

    key_file = os.environ.get(SIGNING_KEY_ENV)
    seed = None
    if key_file:
        try:
            seed = read_signing_key(key_file)
        except (OSError, ValueError) as e:
            print(f"\n*** ERROR: the signing key {SIGNING_KEY_ENV} names can't be used "
                  f"({e if isinstance(e, ValueError) else type(e).__name__}): no update.json written. ***")
            return None

    parts_rule = config["parts"]
    files = program_files(final_dist, parts_rule)
    parts = []
    for part in parts_rule:
        members = [f for f in files if f["part"] == part["name"]]
        if not members:
            continue
        asset = f"surasura_part_{part['name']}_v{version}.zip"
        path = os.path.join(out_dir, asset)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in members:
                z.write(os.path.join(final_dist, *f["path"].split("/")), f["path"])
        parts.append({"name": part["name"], "asset": asset, "sha256": _sha256(path), "size": os.path.getsize(path)})
        print(f"Part {part['name']}: {asset} ({len(members)} files, {os.path.getsize(path) / (1024 * 1024):.1f} MB)")

    manifest = {
        "version": version,
        "update_type": "full",
        "runtime_baseline": version,
        "critical": False,
        "sha256": "",
        "notes_url": f"https://github.com/SonicSandbox/surasura/releases/tag/v{version}",
        "telemetry_url": config["release"]["telemetry_url"],    # where 3.x's next heartbeat goes (signed with it)
        "format": 2,
        "package": {"parts": parts, "files": files, "needs_installer": bool(needs_installer),
                    "min_from": config["release"]["min_from"], "install_shape": install_shape()},
    }
    if installer:
        # 2.x's hand-off (S1.3-6): 2.5 runs this installer, its wizard showing (args empty); 2.4.0 and older see a
        # download. A 3.x release without an installer is "full" to every 2.x.
        manifest["update_type"] = "installer"
        manifest["installer"] = {"asset": os.path.basename(installer), "sha256": _sha256(installer), "args": [],
                                 "min_from": config["release"]["installer_min_from"]}

    data = canonical_json(manifest)
    with open(os.path.join(out_dir, MANIFEST_NAME), "wb") as f:
        f.write(data)
    print(f"update.json written (format 2, {len(files)} files in {len(parts)} parts, "
          f"update_type={manifest['update_type']} for 2.x).")

    sig_path = os.path.join(out_dir, SIGNATURE_NAME)
    if os.path.exists(sig_path):
        os.remove(sig_path)                                  # never a stale signature beside a new manifest
    if seed is None:
        print(f"\n*** WARNING: update.json is NOT signed (no {SIGNING_KEY_ENV} set). A 3.x install will only be "
              "told this release is out; it installs nothing unsigned. ***\n")
    else:
        with open(sig_path, "wb") as f:
            f.write(ed25519.sign(seed, data))
        import hashlib
        print(f"update.json.sig written (public key fingerprint "
              f"{hashlib.sha256(ed25519.public_key(seed)).hexdigest()[:16]}).")
    return manifest


# --- The installer (S3.1 D1, D2, D8) ----------------------------------------------------------------------------------
# packaging/surasura.iss, compiled by Inno Setup 6's ISCC into dist\Surasura-<ver>-setup.exe. A test build (any
# data_name but build_config's) gets its own AppId, name, program folder and mutex, so a test install never meets a
# real one (S3.1-3).
INSTALLER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packaging", "surasura.iss")
APP_GUID = "0EF53F4A-4995-48AA-A8EA-91649B265D82"   # the real program's AppId (made once, 2026-10-12): never change it
ISCC_PLACES = (r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe",       # installed for this user (S3.1-2)
               r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe")            # installed for everyone (GitHub's runner)


def install_shape(path=INSTALLER_SCRIPT):
    """What only the installer can change (S3.1 D7): the first 16 hex of the sha256 of packaging/surasura.iss, its
    comment and blank lines dropped (; and //, and a line that is one { } comment) and its [Files] section left out:
    the program's files ride in the parts. A line's line end and outer spaces never count. The build stamps it into
    the program and into update.json's package; a 3.x program stamped with another runs the installer
    (update_checker._classify_3x)."""
    import hashlib
    kept, in_files = [], False
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith((";", "//")) or \
                    (line.startswith("{") and not line.startswith("{$") and line.find("}") == len(line) - 1):
                continue
            if line.startswith("[") and line.endswith("]"):
                in_files = line.lower() == "[files]"
            if not in_files:
                kept.append(line)
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()[:16]


def installer_name(version):
    return f"Surasura-{version}-setup.exe"


def installer_defines(version, data_name, program_dir, real_name):
    """The .iss's defines. The real program: APP_GUID, "Surasura", %LOCALAPPDATA%\\Programs\\Surasura. A test build:
    an AppId of its own (derived from its data_name, so each test name has one), "Surasura (test)", and its data_name
    as the program folder, the data folder and the mutexes' name. The real name in another case is refused
    (ValueError, `valid_data_name`): its folders would be the real install's."""
    if not valid_data_name(data_name, real_name):
        raise ValueError(f"{data_name!r} is not a test build's data name (the real one is {real_name!r})")
    test = data_name.casefold() != real_name.casefold()
    import uuid
    return {
        "AppVersion": version,
        "AppGuid": str(uuid.uuid5(uuid.UUID(APP_GUID), data_name)).upper() if test else APP_GUID,
        "AppName": "Surasura (test)" if test else "Surasura",
        "AppFolder": data_name,
        "DataName": data_name,
        "ProgramDir": os.path.abspath(program_dir),
    }


def find_iscc():
    """Inno Setup 6's command-line compiler, or None."""
    for place in ISCC_PLACES:
        path = os.path.expandvars(place)
        if "%" not in path and os.path.isfile(path):
            return path
    return shutil.which("ISCC")


ISCC_MISSING = ("Inno Setup 6's ISCC.exe was not found (looked in %LOCALAPPDATA%\\Programs\\Inno Setup 6, "
                "%ProgramFiles(x86)%\\Inno Setup 6 and on PATH). Install Inno Setup 6.7.3, or build without "
                "--installer.")


def build_installer(final_dist, version, data_name, real_name, out_dir="dist"):
    """Compile packaging/surasura.iss over the built program folder -> the installer's path, or None (said why)."""
    iscc = find_iscc()
    if not iscc:
        print(f"Installer not built: {ISCC_MISSING}")
        return None
    out = os.path.join(out_dir, installer_name(version))
    if os.path.exists(out):
        os.remove(out)
    defines = installer_defines(version, data_name, final_dist, real_name)
    cmd = [iscc, "/Qp", f"/O{os.path.abspath(out_dir)}", f"/F{os.path.splitext(installer_name(version))[0]}"] + \
        [f"/D{name}={value}" for name, value in defines.items()] + [INSTALLER_SCRIPT]
    print(f"Compiling the installer ({defines['AppName']}, AppId {{{defines['AppGuid']}}}) ...")
    os.makedirs("debug", exist_ok=True)
    with open(os.path.join("debug", "installer_log.txt"), "w", encoding="utf-8") as log_file:
        result = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT)
    if result.returncode != 0 or not os.path.isfile(out):
        print(f"Installer build failed (ISCC exit {result.returncode}). Check debug/installer_log.txt.")
        return None
    print(f"Installer: {out} ({os.path.getsize(out) / (1024 * 1024):.1f} MB)")
    return out


BUILD_INFO = os.path.join("app", "build_info.py")


def source_commit(folder="."):
    """The trees a freeze is built from: "<public short head>", then "/<private short head>" when the private
    repository sits beside it (`<folder>.priv.git`, the copies' layout); "+" after a tree with changes ("?" when git
    couldn't say whether it has any). None when git
    can't say (the build goes on without it)."""
    def git(args, timeout):
        """(code, its output) of one git call, or None. Its own Popen: a build's PyInstaller calls go through
        `subprocess.run`, which the tests stand in for, and git is never one of them."""
        try:
            p = subprocess.Popen(["git", *args], cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True)
            try:
                out, _err = p.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()
                return None
            return p.returncode, out or ""
        except Exception:
            return None

    def head(*where):
        got = git([*where, "rev-parse", "--short=12", "HEAD"], 30)
        if got is None or got[0] != 0 or not got[1].strip():
            return None
        dirty = git([*where, "status", "--porcelain", "--untracked-files=no"], 120)    # "+" changes, "?" unknown
        mark = "?" if dirty is None or dirty[0] != 0 else ("+" if dirty[1].strip() else "")
        return got[1].strip() + mark
    public = head()
    if not public:
        return None
    here = os.path.abspath(folder)
    priv = here.rstrip("\\/") + ".priv.git"
    private = head(f"--git-dir={priv}", f"--work-tree={here}") if os.path.isdir(priv) else None
    return public + (f"/{private}" if private else "")


class _release_flag:
    """For a release's freeze: app/build_info.py says RELEASE_BUILD = True (so the exe ignores the update check's
    local-folder override), and is put back exactly as it was afterwards, whatever happens. With `build_id` (every
    build, S3.1 D18) it also carries BUILD_ID = "<id>" for the freeze, the id _internal/build_stamp.json records, so a
    program can tell its own build from the folder's; with `commit`, BUILD_COMMIT = "<public>[/<private>]"
    (`source_commit`), which Report a problem's zip names."""
    def __init__(self, on, build_id=None, commit=None):
        self.on = on
        self.build_id = build_id
        self.commit = commit
        self.saved = None

    def __enter__(self):
        if self.on or self.build_id:
            with open(BUILD_INFO, "rb") as f:
                self.saved = f.read()
            text = self.saved.decode("utf-8")
            if self.on:
                text = text.replace("RELEASE_BUILD = False", "RELEASE_BUILD = True")
                if "RELEASE_BUILD = True" not in text:
                    raise RuntimeError("app/build_info.py has no RELEASE_BUILD = False to set")
            if self.build_id:
                text = text.rstrip("\r\n") + f'\nBUILD_ID = "{self.build_id}"\n'
            if self.commit:                               # Report a problem's about.txt names the trees built from
                text = text.rstrip("\r\n") + f'\nBUILD_COMMIT = "{self.commit}"\n'
            with open(BUILD_INFO, "wb") as f:
                f.write(text.encode("utf-8"))
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            with open(BUILD_INFO, "wb") as f:
                f.write(self.saved)
        return False


DEFAULT_LISTS = {   # a new library's starting lists, from this tree's User Files/<lang>/ (2.x shipped the same files)
    "ja": ["frequency_list_ja_global50k.csv", "IgnoreList.txt", "Blacklist.txt"],
    "zh": ["IgnoreList.txt", "Blacklist.txt"],
}
LEGACY_JITEN_ZIPS = [   # Yomitan frequency lists from User Files/, bundled when present (Japanese)
    "jiten_freq_Anime.zip", "jiten_freq_Drama.zip", "jiten_freq_global.zip", "jiten_freq_Manga.zip",
    "jiten_freq_Movie.zip", "jiten_freq_NonFiction.zip", "jiten_freq_Novel.zip", "jiten_freq_VideoGame.zip",
    "jiten_freq_VisualNovel.zip", "jiten_freq_WebNovel.zip",
]
LIBRARY_NAMES = ("settings.json", "User Files", "data", "results")   # the library's, never the program folder's


def copy_default_lists(final_dist):
    """The bundled lists into _internal/defaults/<lang>/ (S3.1 D15): the program copies each one a library lacks into
    its User Files/<lang>/ at its first start (path_utils.copy_default_lists). -> the paths written."""
    written = []
    for lang, names in DEFAULT_LISTS.items():
        sources = [os.path.join("User Files", lang, n) for n in names]
        if lang == "ja":
            sources += [os.path.join("User Files", n) for n in LEGACY_JITEN_ZIPS]
        for src in sources:
            if os.path.isfile(src):
                folder = os.path.join(final_dist, "_internal", "defaults", lang)
                os.makedirs(folder, exist_ok=True)
                shutil.copy2(src, os.path.join(folder, os.path.basename(src)))
                written.append(f"_internal/defaults/{lang}/{os.path.basename(src)}")
    return written


def write_build_stamp(final_dist, version, build_id, data_name, shape):
    """_internal/build_stamp.json {version, build_id, data_name, install_shape} (S3.1 D18): each program compares its
    own with it at start; data_name names the program's own data folders (%LOCALAPPDATA%\\Houseki\\<data_name>);
    install_shape (`install_shape()`) is what the update check compares with a release's (D7)."""
    path = os.path.join(final_dist, "_internal", "build_stamp.json")
    with open(path, "wb") as f:
        f.write(canonical_json({"version": version, "build_id": build_id, "data_name": data_name,
                                "install_shape": shape}))
    return path


def _is_shape(value):
    return isinstance(value, str) and len(value) == 16 and all(c in "0123456789abcdef" for c in value)


def sqlite_version_of(dll):
    """The version a sqlite3.dll reports (sqlite3_libversion), read in a fresh Python so no sqlite already loaded
    answers instead. -> '3.53.4', or None when it can't be loaded."""
    code = ("import ctypes, sys; d = ctypes.CDLL(sys.argv[1]); d.sqlite3_libversion.restype = ctypes.c_char_p; "
            "print(d.sqlite3_libversion().decode('ascii'))")
    try:
        out = subprocess.run([sys.executable, "-I", "-c", code, os.path.abspath(dll)], capture_output=True,
                             text=True, timeout=60)
    except Exception:
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def swap_sqlite(final_dist, config):
    """Replace the frozen program's _internal/sqlite3.dll with the vendored sqlite.org build (S3.1 D16), after checking
    the vendored file's sha256. -> None, or the reason it failed."""
    vendored = os.path.join(os.path.dirname(BUILD_CONFIG), "..", *config["sqlite_dll"].split("/"))
    target = os.path.join(final_dist, "_internal", "sqlite3.dll")
    if not os.path.isfile(vendored) or _sha256(vendored) != config["sqlite_dll_sha256"]:
        return f"the vendored {config['sqlite_dll']} is missing or not the one build_config.json records"
    if not os.path.isfile(target):
        return "the build has no _internal/sqlite3.dll to replace"
    shutil.copy2(vendored, target)
    return None


def check_program(final_dist, config):
    """The post-build checks (S3.1 D15–D17), also runnable on a built folder: `python package_app.py --check
    dist\\Surasura`. -> (failures, facts): failures a list of reasons (empty = all passed)."""
    failures, facts = [], {}
    internal = os.path.join(final_dist, "_internal")
    # Exactly the four programs at the top, every build (updater.exe: the swapper, S3.1 D9; tsubasa.exe: T1 B).
    expected = set(PROGRAM_EXES)
    found = {n for n in os.listdir(final_dist) if n.lower().endswith(".exe")} if os.path.isdir(final_dist) else set()
    facts["exes"] = sorted(found)
    if found != expected:
        failures.append(f"the programs at the top are {sorted(found)}, not exactly {sorted(expected)}")
    # The library's folders and settings.json are never in the program folder.
    stray = [n for n in LIBRARY_NAMES if os.path.exists(os.path.join(final_dist, n))]
    if stray:
        failures.append(f"the program folder holds the library's {stray}")
    # Every top-level entry is one an update owns: a one-click update moves only app.updater.OWNED_ENTRIES (and what
    # the new release names), so any other would stay behind at the next update, never swapped or removed.
    from app import updater
    unowned = sorted(n for n in (os.listdir(final_dist) if os.path.isdir(final_dist) else ())
                     if n not in updater.OWNED_ENTRIES)
    if unowned:
        failures.append(f"the program folder's top holds {unowned}, which app.updater.OWNED_ENTRIES doesn't name: "
                        "an update would leave it behind (add it there first)")
    # SQLite at or above the floor, read from the frozen program's own DLL.
    version = sqlite_version_of(os.path.join(internal, "sqlite3.dll"))
    facts["sqlite"] = version
    if not version or _version_tuple(version) < _version_tuple(config["sqlite_min"]):
        failures.append(f"_internal/sqlite3.dll reports {version}, below the floor {config['sqlite_min']}")
    # The stamp.
    try:
        with open(os.path.join(internal, "build_stamp.json"), encoding="utf-8") as f:
            stamp = json.load(f)
        facts["stamp"] = stamp
        if set(stamp) != {"version", "build_id", "data_name", "install_shape"} or not stamp["build_id"] or \
                not valid_data_name(stamp["data_name"], config["data_name"]) or not _is_shape(stamp["install_shape"]):
            failures.append(f"_internal/build_stamp.json is not {{version, build_id, data_name, install_shape}}: "
                            f"{stamp}")
    except (OSError, ValueError) as e:
        failures.append(f"_internal/build_stamp.json can't be read ({e})")
    # The optional modules the build config leaves out (Koe since the 2.9 alpha, Sonic 2026-10-23; Reels; the Immersion
    # Architect): none of their code frozen into either Python program, none of their files under _internal.
    left_out = [m for m in OPTIONAL_MODULES if (config.get("modules") or {}).get(m) is not True]
    facts["left_out"] = left_out
    prefixes = tuple(f"modules.{m}" for m in left_out)
    for exe in ("Surasura.exe", CLI_EXE_NAME):
        path = os.path.join(final_dist, exe)
        if not os.path.isfile(path):
            continue                                        # the programs' own check names it
        frozen = frozen_modules(path)
        if frozen is None:
            failures.append(f"{exe}'s Python archive can't be read, so the modules left out ({left_out}) can't be "
                            "checked")
            continue
        inside = sorted(n for n in frozen if any(n == p or n.startswith(p + ".") for p in prefixes))
        if inside:
            failures.append(f"{exe} holds modules the build config leaves out: {inside[:5]}")
    stray = []
    for dirpath, _dirs, files in os.walk(internal):
        parts = os.path.relpath(dirpath, internal).replace(os.sep, "/").split("/")
        if any(parts[i:i + 2] == ["modules", m] for i in range(len(parts)) for m in left_out):
            stray += [os.path.join(dirpath, n) for n in files] or [dirpath]     # an empty folder imports too
    if stray:
        failures.append(f"_internal holds files of modules the build config leaves out: {stray[:5]}")
    # PyQt6: only the window's modules, with PyQt6's and Qt's licence notices.
    qt_folder = os.path.join(internal, "PyQt6")
    if os.path.isdir(qt_folder):
        pyds = sorted(n.split(".")[0] for n in os.listdir(qt_folder) if n.lower().endswith(".pyd"))
        facts["qt_modules"] = pyds
        extra = [m for m in pyds if m not in config["qt_modules"] and m != "sip"]
        if extra:
            failures.append(f"PyQt6 modules the window doesn't use were bundled: {extra}")
        for dist in ("PyQt6", "PyQt6-Qt6"):
            folder = os.path.join(internal, "licenses", dist)
            if not (os.path.isdir(folder) and os.listdir(folder)):
                failures.append(f"_internal/licenses/{dist} holds no licence notice")
    return failures, facts


def frozen_modules(exe):
    """The Python modules frozen into a built program (PyInstaller's PYZ archive inside `exe`) -> a set of names, or
    None when `exe` holds no archive this PyInstaller can read, or one that names none of Surasura's own `app`
    modules (a PYZ renamed or split by another PyInstaller: a reading that saw nothing proves nothing)."""
    try:
        from PyInstaller.archive.readers import CArchiveReader
        archive = CArchiveReader(exe)
        names = set()
        for entry in archive.toc:
            if entry.endswith(".pyz"):
                names.update(archive.open_embedded_archive(entry).toc)
        return names if any(n == "app" or n.startswith("app.") for n in names) else None
    except Exception:
        return None


def check_zip_licences(zip_path):
    """The download zip carries PyQt6's and Qt's licence notices whenever it carries PyQt6. -> the failures."""
    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
    if not any("/_internal/PyQt6/" in n for n in names):
        return []
    return [f"{os.path.basename(zip_path)} holds no _internal/licenses/{dist}/ notice" for dist in ("PyQt6", "PyQt6-Qt6")
            if not any(f"/_internal/licenses/{dist}/" in n for n in names)]


# --- tsubasa (T1 B, 2026-10-21) ----------------------------------------------------------------------------------------
# tsubasa.exe is frozen from the installed tsubasa-sync, the one requirements.txt pins exactly (`tsubasa-sync==X.Y.Z`).
# A build refuses an installed tsubasa-sync that isn't the pin (before freezing) and a built tsubasa.exe whose
# `--version` isn't the pin or says it lost its data (after): a stale tsubasa never ships. The build ritual first moves
# the pin to tsubasa's latest release (packaging/tsubasa_pin.py, Pre-build_check.md): a tsubasa fix reaches users in
# Surasura's next update, its own part (build_config's "tsubasa"). Nothing here imports tsubasa (K1).
TSUBASA_DIST = "tsubasa-sync"
REQUIREMENTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
_TSUBASA_LINE = re.compile(r"tsubasa[-_.]sync(?![\w.-])", re.I)
_TSUBASA_PIN = re.compile(r"tsubasa[-_.]sync\s*==\s*(\d+(?:\.\d+){1,3})\Z", re.I)


def tsubasa_pin(path=REQUIREMENTS):
    """The tsubasa-sync version requirements.txt pins -> 'X.Y.Z', or None unless exactly one line pins it exactly
    (a range, an extra, a marker or a second line is no pin)."""
    found = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if _TSUBASA_LINE.match(line):
                    pinned = _TSUBASA_PIN.match(line)
                    found.append(pinned.group(1) if pinned else None)
    except OSError:
        return None
    return found[0] if len(found) == 1 else None


def tsubasa_installed():
    """The tsubasa-sync version this Python freezes -> 'X.Y.Z', or None when it isn't installed (its metadata: never
    an import)."""
    from importlib import metadata
    try:
        return metadata.version(TSUBASA_DIST)
    except metadata.PackageNotFoundError:
        return None


def tsubasa_version_of(exe):
    """`<exe> --version` -> (exit code, its first line). tsubasa says `tsubasa <version>` first and exits 0 when the
    build is whole, 1 when its self-check found its name tables or numpy missing. (None, why) when it won't run."""
    try:
        done = subprocess.run([exe, "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"it won't run ({type(e).__name__})"
    lines = (done.stdout or "").splitlines()
    return done.returncode, (lines[0].strip() if lines else "")


def check_tsubasa(final_dist, pin=None, version_of=None):
    """The program's tsubasa.exe is the pinned tsubasa, whole -> (failures, the first line it said, or None)."""
    pin = tsubasa_pin() if pin is None else pin
    if not pin:
        return ["requirements.txt pins no tsubasa-sync==X.Y.Z"], None
    code, said = (version_of or tsubasa_version_of)(os.path.join(final_dist, TSUBASA_EXE_NAME))
    if code != 0 or said != f"tsubasa {pin}":
        return [f"{TSUBASA_EXE_NAME} --version says {said!r} (exit {code}), not a whole 'tsubasa {pin}': the bundle's "
                "tsubasa is stale or broken (pip install -r requirements.txt, then build again)"], said
    return [], said


def build(zip_output=False, skip_tests=False, release=False, full_update=False, data_name=None, installer=False,
          needs_installer=False):
    version = get_version()
    build_name = "Surasura"                 # stable install-folder name (must match the spec's BUILD_NAME)
    zip_name = f"Surasura_v{version}"        # versioned DOWNLOAD zip name (kept for the updater + humans)
    print(f"Building Readability Analyzer {zip_name}...")
    try:
        config = load_build_config()
    except (OSError, ValueError) as e:
        print(f"Build aborted: {e}")
        return False
    data_name = data_name or config["data_name"]
    if not valid_data_name(data_name, config["data_name"]):
        print(f"Build aborted: --data-name {data_name!r} is not a plain folder name, or is the real one "
              f"({config['data_name']!r}) in another case.")
        return False

    # A release always produces the full zip too; --full-update (2.x's runtime release) implies --release.
    if full_update:
        release = True
    if release:
        zip_output = True

    if _python_version() < _version_tuple(config["python_min"]):
        # P0.3 02-contract §8: on 3.11.2 a frozen console program with no stderr crashes on a usage error. A real
        # release stops; a test build (its own data_name), release or not, only warns.
        if release and data_name.casefold() == config["data_name"].casefold():
            print(f"Build aborted: a release needs Python {config['python_min']} or later "
                  f"(this is {sys.version.split()[0]}).")
            return False
        print(f"WARNING: building on Python {sys.version.split()[0]}; surasura-cli wants {config['python_min']} "
              "or later. A test build only: a real --release refuses it.")

    if installer and not find_iscc():
        print(f"Build aborted: --installer: {ISCC_MISSING}")
        return False
    try:
        shape = install_shape()
    except OSError as e:
        print(f"Build aborted: packaging/surasura.iss can't be read for the install shape ({e}).")
        return False
    pin, have = tsubasa_pin(), tsubasa_installed()
    if not pin or have != pin:
        print(f"Build aborted: requirements.txt pins tsubasa-sync {pin or '(no exact ==X.Y.Z)'}, and this Python has "
              f"{have or 'none'}: tsubasa.exe would be built from another tsubasa. Run pip install -r requirements.txt.")
        return False

    # Gate: everything being bundled must be testable first.
    if skip_tests:
        print("WARNING: --skip-tests set; skipping the pre-build test gate.")
    elif not run_pre_build_tests(config["modules"]):
        print("Build aborted: fix failing tests first (or pass --skip-tests to override).")
        return False

    # Clean previous build: a tree that can't be removed stops the build, so a stale dist\Surasura (one an earlier
    # build's program still holds open) is never packaged.
    for folder in ("dist", "build"):
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
            except OSError as e:
                print(f"Build aborted: {os.path.abspath(folder)} can't be removed ({e}). Close what holds it open "
                      "(an earlier build's Surasura, a window on it) and build again.")
                return False

    # PyInstaller Command
    # Use the spec file in packaging/ directory
    # distpath and workpath default to dist/ and build/ in the current directory
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath", "dist",
        "--workpath", "build",
        os.path.join("packaging", "Surasura.spec")
    ]

    print(f"Running: {' '.join(cmd)}")

    # Ensure debug folder exists for logs
    if not os.path.exists("debug"):
        os.makedirs("debug", exist_ok=True)

    import datetime
    import secrets
    build_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    with open(os.path.join("debug", "build_log.txt"), "w") as log_file, _release_flag(release, build_id, source_commit()):
        result = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT)

    if result.returncode != 0:
        print("Build failed. Check debug/build_log.txt for details.")
        return False

    # Post-Build: the program folder. It holds the program only (S3.1 D15): no settings.json, User Files\, data\ or
    # results\ — those are the library's, made at the program's first start.
    print("Creating Distribution Package...")
    final_dist = os.path.join("dist", build_name)
    if not os.path.exists(final_dist):
        print(f"Error: Build output not found at {final_dist}")
        return False

    print(f"Build output verified at {final_dist}")
    for exe_name in ("Surasura.exe", CLI_EXE_NAME):
        exe_path = os.path.join(final_dist, exe_name)
        if not os.path.isfile(exe_path):
            print(f"Error: {exe_name} not found in {final_dist}")
            return False
        print(f"  {exe_name}: {os.path.getsize(exe_path) / (1024 * 1024):.1f} MB")

    # 1. SQLite: the vendored sqlite.org build replaces the one Python 3.11 bundles (S3.1 D16).
    reason = swap_sqlite(final_dist, config)
    if reason:
        print(f"Build failed: {reason}.")
        return False

    # 2. The bundled lists, for a new library's first start.
    for path in copy_default_lists(final_dist):
        print(f"Bundled default list: {path}")

    # 3. Documentation, at the top of the program folder.
    docs_to_copy = [
        ("README.md", "README.md"),
        (os.path.join("docs", "UPDATE_INSTRUCTIONS.md"), "UPDATE_INSTRUCTIONS.md"),
        # Packaged under a STABLE name so it isn't version-stamped (and so an update refreshes it in place).
        # Content keeps its version header.
        (os.path.join("docs", "releases", f"RELEASE_v{version}.md"), "RELEASE_NOTES.md"),
        # Settings › App reads its licence line from it (app/credits.py).
        ("LICENSE", "LICENSE")
    ]
    for src, dst_name in docs_to_copy:
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(final_dist, dst_name))
        else:
            print(f"Warning: Documentation file not found: {src}")

    # 4. The build stamp (S3.1 D18).
    write_build_stamp(final_dist, version, build_id, data_name, shape)
    print(f"Build stamp: version {version}, build {build_id}, data folder name {data_name}, install shape {shape}")

    # 5. Bundle updater.exe BEFORE the checks, the zip, the installer and the release's file list: every build ships
    #    the swapper (S3.1 D9), a test build too.
    if not _build_updater_exe(final_dist):
        print("Build failed: every build needs updater.exe.")
        return False

    # 6. The post-build checks: exactly the four programs, no library, SQLite's floor, the stamp, PyQt6's modules and
    #    licences, and tsubasa.exe the pinned tsubasa. Any failure stops here (nothing is zipped).
    failures, facts = check_program(final_dist, config)
    tsubasa_failures, facts["tsubasa"] = check_tsubasa(final_dist)
    failures += tsubasa_failures
    print(f"Checks: programs {facts.get('exes')}, SQLite {facts.get('sqlite')}, "
          f"PyQt6 {facts.get('qt_modules', 'not bundled')}, {facts['tsubasa']}")
    if failures:
        print("Build failed:\n  " + "\n  ".join(failures))
        return False

    # 7. Create Zip Archive
    zipped = False
    if zip_output:
        print("Creating Zip Archive...")
        archive_base = os.path.join("dist", zip_name) # -> dist/Surasura_v<version>.zip
        try:
            # Nest under the stable 'Surasura/' folder (base_dir) so it extracts to Surasura/ instead
            # of a version-stamped folder that would look stale after an in-place update.
            shutil.make_archive(archive_base, 'zip', root_dir="dist", base_dir=build_name)
            print(f"Zip archive created: {archive_base}.zip")
            zipped = True
        except Exception as e:
            print(f"Warning: Could not create zip archive: {e}")
            if release:
                print("Build failed: a release needs its full zip.")
                return False
        zip_failures = check_zip_licences(archive_base + ".zip") if zipped else []
        if zip_failures:
            print("Build failed:\n  " + "\n  ".join(zip_failures))
            return False
    else:
        print("Skipping Zip Archive creation (use --zip to enable).")

    # 8. The installer (--installer): dist\Surasura as built, into dist\Surasura-<ver>-setup.exe.
    built_installer = None
    if installer:
        built_installer = build_installer(final_dist, version, data_name, config["data_name"])
        if built_installer is None:
            print("Build failed: --installer asked for the installer.")
            return False

    # 9. The 3.x update artifacts (parts, update.json, update.json.sig) — release only. The installer built just now
    #    rides as 2.x's hand-off (update_type "installer"); without one, update.json says "full".
    if release:
        if _build_release(final_dist, version, config, out_dir="dist", installer=built_installer,
                          needs_installer=needs_installer) is None:
            print("Build failed: the release's update.json was not written (see the error above).")
            return False
        print("  -> Attach to the GitHub release: the full zip, every surasura_part_*.zip, update.json"
              + (", update.json.sig" if os.path.isfile(os.path.join("dist", SIGNATURE_NAME)) else "")
              + (", the installer" if built_installer else ""))

    print("\n---------------------------------------------------")
    print(f"Build Complete! Package located at: {os.path.abspath(final_dist)}")
    if zipped:
        print(f"Zip Archive: {os.path.abspath(archive_base + '.zip')}")
    print("---------------------------------------------------")

    # Open the dist folder in File Explorer — never on a CI runner (CI set, as GitHub's runners do): there nobody looks,
    # and the open window holds dist, so the package proof's next step couldn't move it (Permission denied, 2026-10-15
    # to 10-22, with no process of ours holding it).
    if not os.environ.get("CI"):
        try:
            os.startfile(os.path.abspath("dist"))
        except Exception:
            pass
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and package Surasura.")
    parser.add_argument("--zip", action="store_true", help="Create a zip archive of the distribution folder.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip the pre-build test gate (not recommended).")
    parser.add_argument("--release", action="store_true",
                        help="Also emit the 3.x update artifacts (parts, update.json, update.json.sig). "
                             "Implies --zip. Refuses a Python below build_config's floor.")
    parser.add_argument("--full-update", action="store_true",
                        help="2.x's runtime release; on the 3.0 line the same as --release (every release lists "
                             "every file).")
    parser.add_argument("--data-name", default=None,
                        help="The program's data folder name in the build stamp (default: build_config's "
                             "data_name, 'Surasura'); a test build uses its own, e.g. Surasura-test.")
    parser.add_argument("--installer", action="store_true",
                        help="Also compile packaging/surasura.iss with Inno Setup 6 (ISCC) into "
                             "dist\\Surasura-<ver>-setup.exe; with --release, update.json carries it for 2.x.")
    parser.add_argument("--needs-installer", action="store_true",
                        help="With --release: every 3.x install takes this release through its installer, even when "
                             "packaging/surasura.iss's install shape is unchanged (e.g. a new install folder).")
    parser.add_argument("--check", metavar="FOLDER", default=None,
                        help="Only run the post-build checks on a built program folder (e.g. dist\\Surasura); "
                             "prints CHECKS OK or the failures.")
    args = parser.parse_known_args()[0]
    if args.check:
        checked, found = check_program(args.check, load_build_config())
        tsubasa_failures, found["tsubasa"] = check_tsubasa(args.check)
        checked += tsubasa_failures
        zips = [os.path.join(os.path.dirname(os.path.abspath(args.check)), n)
                for n in os.listdir(os.path.dirname(os.path.abspath(args.check)))
                if n.startswith("Surasura_v") and n.endswith(".zip")]
        for z in zips:
            checked += check_zip_licences(z)
        print(json.dumps(found, ensure_ascii=False))
        print("CHECKS OK" if not checked else "CHECKS FAILED:\n  " + "\n  ".join(checked))
        sys.exit(1 if checked else 0)
    # A failed build exits 1, so a workflow step or a script that runs it stops there.
    sys.exit(0 if build(zip_output=args.zip, skip_tests=args.skip_tests, release=args.release,
                        full_update=args.full_update, data_name=args.data_name, installer=args.installer,
                        needs_installer=args.needs_installer) else 1)

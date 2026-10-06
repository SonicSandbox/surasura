import os
import shutil
import subprocess
import sys
import argparse
import json

CLI_EXE_NAME = "surasura-cli.exe"   # the headless command line, built beside Surasura.exe (packaging/Surasura.spec)

def get_version():
    """Reads the version from app/__init__.py without importing the package."""
    init_path = os.path.join("app", "__init__.py")
    with open(init_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('__version__'):
                delim = '"' if '"' in line else "'"
                return line.split(delim)[1]
    return "0.0"

# Optional modules and the settings that cause them to be bundled (mirrors packaging/Surasura.spec).
# When a module will be included in the build, its own test suite must pass first.
def _included_module_test_dirs(settings):
    dirs = []
    # (The Immersion Architect is never bundled since 2.5 — sunset, RD-D9 — so its suite is no gate.)
    # YouTube Downloader: bundled when either feature is enabled.
    if settings.get("enable_youtube_transcripts", False) or settings.get("enable_youtube_preview", False):
        d = os.path.join("modules", "youtube_downloader", "tests")
        if os.path.isdir(d):
            dirs.append(d)
    # Speech (Koe): always bundled when present (it is hidden at runtime, not at build time), so
    # its suite runs whenever the folder is there.
    d = os.path.join("modules", "koe", "tests")
    if os.path.isdir(d):
        dirs.append(d)
    # Reels: bundled when enabled, so its suite runs before a build that ships it.
    if settings.get("enable_reels", False):
        d = os.path.join("modules", "reels", "tests")
        if os.path.isdir(d):
            dirs.append(d)
    # Junban: bundled when enabled, so its suite runs before a build that ships it.
    if settings.get("enable_junban", False):
        d = os.path.join("modules", "junban", "tests")
        if os.path.isdir(d):
            dirs.append(d)
    return dirs


def run_pre_build_tests():
    """Run the core suite plus the suite of every module that will be bundled.

    Everything shipped must be testable before it builds. Returns True only if all pass.
    """
    settings = {}
    try:
        with open("settings.json", "r", encoding="utf-8") as f:
            settings = json.load(f)
    except Exception as e:
        print(f"Warning: could not read settings.json for test selection: {e}")

    suites = ["tests"] + _included_module_test_dirs(settings)
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
    """Build the standalone updater.exe and drop it next to Surasura.exe (release only)."""
    print("Building updater.exe (release artifact)...")
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
    """Emit the release update artifacts: the app-only package zip and update.json.

    The app package carries the code-bearing executable (Surasura.exe — its embedded archive
    holds ALL app code) plus the loose report templates. That is the correct minimal unit: in
    a onedir freeze the Python code is NOT loose under _internal/app (that's only assets), so
    replacing the exe is what actually updates the code. For a --full-update release we skip
    the package (users download the full zip) and publish only an update.json (update_type=full).

    Since 2.5 update.json also lists every file the package carries (`files`, K99): each entry's
    name (its path at the top of the zip — the same layout 2.4.0's updater reads), its destination
    in the install folder, its kind and its sha256 (a folder's: `updater.tree_sha256`). 2.5's
    updater swaps exactly that list; surasura-cli.exe rides in it when the build has one.
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


BUILD_INFO = os.path.join("app", "build_info.py")


class _release_flag:
    """For a release's freeze: app/build_info.py says RELEASE_BUILD = True (so the exe ignores the update check's
    local-folder override), and is put back exactly as it was afterwards, whatever happens."""
    def __init__(self, on):
        self.on = on
        self.saved = None

    def __enter__(self):
        if self.on:
            with open(BUILD_INFO, "rb") as f:
                self.saved = f.read()
            text = self.saved.decode("utf-8").replace("RELEASE_BUILD = False", "RELEASE_BUILD = True")
            if "RELEASE_BUILD = True" not in text:
                raise RuntimeError("app/build_info.py has no RELEASE_BUILD = False to set")
            with open(BUILD_INFO, "wb") as f:
                f.write(text.encode("utf-8"))
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            with open(BUILD_INFO, "wb") as f:
                f.write(self.saved)
        return False


def build(zip_output=False, skip_tests=False, release=False, full_update=False):
    version = get_version()
    build_name = "Surasura"                 # stable install-folder name (must match the spec's BUILD_NAME)
    zip_name = f"Surasura_v{version}"        # versioned DOWNLOAD zip name (kept for the updater + humans)
    print(f"Building Readability Analyzer {zip_name}...")
    if sys.version_info < (3, 11, 4):
        # P0.3 02-contract §8: on 3.11.2 a frozen console program with no stderr crashes on a usage error.
        print(f"WARNING: building on Python {sys.version.split()[0]}; surasura-cli wants 3.11.4 or later.")

    # A release always produces the full zip too; --full-update implies --release.
    if full_update:
        release = True
    if release:
        zip_output = True

    # Gate: everything being bundled must be testable first.
    if skip_tests:
        print("WARNING: --skip-tests set; skipping the pre-build test gate.")
    elif not run_pre_build_tests():
        print("Build aborted: fix failing tests first (or pass --skip-tests to override).")
        return

    # Clean previous build
    if os.path.exists("dist"):
        try:
            shutil.rmtree("dist")
        except Exception:
            pass
    if os.path.exists("build"):
        try:
            shutil.rmtree("build")
        except Exception:
            pass

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
        
    with open(os.path.join("debug", "build_log.txt"), "w") as log_file, _release_flag(release):
        result = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT)
    
    if result.returncode != 0:
        print("Build failed. Check debug/build_log.txt for details.")
        return

    # Post-Build: Create Distribution Folder
    print("Creating Distribution Package...")
    final_dist = os.path.join("dist", build_name)
    
    # Clean previous distribution logic removed because we already cleaned dist at the start
    # and PyInstaller works directly in this folder now.


    # 1. Handle Built Files
    # The spec file is configured to output directly to dist/{build_name}
    # So we just need to verify it exists.
    
    if not os.path.exists(final_dist):
        print(f"Error: Build output not found at {final_dist}")
        return

    print(f"Build output verified at {final_dist}")
    for exe_name in ("Surasura.exe", CLI_EXE_NAME):
        exe_path = os.path.join(final_dist, exe_name)
        if not os.path.isfile(exe_path):
            print(f"Error: {exe_name} not found in {final_dist}")
            return
        print(f"  {exe_name}: {os.path.getsize(exe_path) / (1024 * 1024):.1f} MB")

    # 2. Copy User Files (SANITIZED)
    print("Copying User Files (Sanitized)...")
    dst_user_files_base = os.path.join(final_dist, "User Files")
    os.makedirs(dst_user_files_base, exist_ok=True)
    
    supported_languages = ["ja", "zh"]
    
    # A. Global Files (None Currently)

    # B. Language Specific User Files
    for lang in supported_languages:
        dst_user_files_lang = os.path.join(dst_user_files_base, lang)
        os.makedirs(dst_user_files_lang, exist_ok=True)
        
        # NOTE: KnownWord.json is explicitly EXCLUDED from build.
        # Users start with a clean slate.

        # Create/Copy Ignore List
        src_ignore = os.path.join("User Files", lang, "IgnoreList.txt")
        if os.path.exists(src_ignore):
             shutil.copy2(src_ignore, os.path.join(dst_user_files_lang, "IgnoreList.txt"))
        else:
            with open(os.path.join(dst_user_files_lang, "IgnoreList.txt"), "w", encoding="utf-8") as f:
                f.write("# Add words to ignore here (one per line)\n")

        # Copy Blacklist
        src_blacklist = os.path.join("User Files", lang, "Blacklist.txt")
        if os.path.exists(src_blacklist):
            print(f"Bundling Blacklist for {lang}...")
            shutil.copy2(src_blacklist, os.path.join(dst_user_files_lang, "Blacklist.txt"))
        
        # Copy Specific Frequency List (Only for JA)
        if lang == "ja":
            specific_freq_list = "frequency_list_ja_global50k.csv"
            src_freq = os.path.join("User Files", "ja", specific_freq_list)
            if os.path.exists(src_freq):
                print(f"Bundling specific frequency list: {specific_freq_list}")
                shutil.copy2(src_freq, os.path.join(dst_user_files_lang, specific_freq_list))
        
    # C. Copy Global Frequency Lists (CSV)
    # Removed: We only bundle the specific 'frequency_list_ja_global50k.csv' now.


    # D. Copy Legacy Yomitan Frequency Lists (Zips) - Optional/Legacy
    freq_lists_legacy = [
        "jiten_freq_Anime.zip",
        "jiten_freq_Drama.zip",
        "jiten_freq_global.zip",
        "jiten_freq_Manga.zip",
        "jiten_freq_Movie.zip",
        "jiten_freq_NonFiction.zip",
        "jiten_freq_Novel.zip",
        "jiten_freq_VideoGame.zip",
        "jiten_freq_VisualNovel.zip",
        "jiten_freq_WebNovel.zip",
    ]
    for freq_file in freq_lists_legacy:
        src_freq = os.path.join("User Files", freq_file)
        if os.path.exists(src_freq):
            shutil.copy2(src_freq, os.path.join(dst_user_files_base, freq_file))

    # 3. Create EMPTY Data Directories.
    # A fresh install ships with EMPTY tiers so the Content Manager's empty-state onboarding appears.
    # Sample content is bundled as a resource (see Surasura.spec datas) and seeded ONLY on demand via
    # the "Test with samples" action -> path_utils.seed_samples. Do NOT copy samples into data/ here.
    print("Creating empty data directories...")
    data_dir_base = os.path.join(final_dist, "data")
    for lang in supported_languages:
        for category in ["HighPriority", "LowPriority", "GoalContent", "Processed"]:
            os.makedirs(os.path.join(data_dir_base, lang, category), exist_ok=True)

    # 4. Create Results Directory
    os.makedirs(os.path.join(final_dist, "results"), exist_ok=True)
    
    # 5. Copy Documentation
    # 5. Copy Documentation
    # We copy these from the docs/ folder to the root of the distribution
    # so the user sees them immediately upon opening the folder.
    
    docs_to_copy = [
        ("README.md", "README.md"),
        (os.path.join("docs", "UPDATE_INSTRUCTIONS.md"), "UPDATE_INSTRUCTIONS.md"),
        # Packaged under a STABLE name so it isn't version-stamped (and so an app update can refresh
        # it in place — see _build_app_package + updater.build_marker). Content keeps its version header.
        (os.path.join("docs", "releases", f"RELEASE_v{version}.md"), "RELEASE_NOTES.md")
    ]

    for src, dst_name in docs_to_copy:
        if os.path.exists(src):
             shutil.copy2(src, os.path.join(final_dist, dst_name))
        else:
            print(f"Warning: Documentation file not found: {src}")

    # 6. Generate Clean Settings for Distribution
    print("Generating Clean Settings for Distribution...")
    try:
        from app import settings_manager
        # Get defaults
        clean_settings = settings_manager.get_default_settings()
        # Ensure 'hide_satoru' is GONE
        if "hide_satoru" in clean_settings:
            del clean_settings["hide_satoru"]
            
        settings_dst = os.path.join(final_dist, "settings.json")
        with open(settings_dst, 'w', encoding='utf-8') as f:
            json.dump(clean_settings, f, indent=4)
        print(f"Clean settings.json created at {settings_dst}")
    except Exception as e:
        print(f"Warning: Could not generate clean settings: {e}")

    # 6.5 Bundle updater.exe BEFORE zipping so the full package ships the helper (release only).
    if release:
        _build_updater_exe(final_dist)

    # 7. Create Zip Archive
    if zip_output:
        print("Creating Zip Archive...")
        archive_base = os.path.join("dist", zip_name) # -> dist/Surasura_v<version>.zip
        try:
            # Nest under the stable 'Surasura/' folder (base_dir) so it extracts to Surasura/ instead
            # of a version-stamped folder that would look stale after an in-place update.
            shutil.make_archive(archive_base, 'zip', root_dir="dist", base_dir=build_name)
            print(f"Zip archive created: {archive_base}.zip")
        except Exception as e:
            print(f"Warning: Could not create zip archive: {e}")
    else:
        print("Skipping Zip Archive creation (use --zip to enable).")

    # 8. Emit the auto-update artifacts (app package + update.json) — release only.
    if release:
        _build_app_package(final_dist, version, full_update)

    print("\n---------------------------------------------------")
    print(f"Build Complete! Package located at: {os.path.abspath(final_dist)}")
    if zip_output:
        print(f"Zip Archive: {os.path.abspath(archive_base + '.zip')}")
    print("---------------------------------------------------")

    # Open the dist folder in File Explorer
    try:
        os.startfile(os.path.abspath("dist"))
    except Exception:
        pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and package Surasura.")
    parser.add_argument("--zip", action="store_true", help="Create a zip archive of the distribution folder.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip the pre-build test gate (not recommended).")
    parser.add_argument("--release", action="store_true",
                        help="Also build updater.exe and emit the auto-update artifacts (app package zip + update.json). Implies --zip.")
    parser.add_argument("--full-update", action="store_true",
                        help="Mark this release as a full/manual update (runtime or major change). Sets update_type=full and advances runtime_baseline. Implies --release.")
    args = parser.parse_known_args()[0]
    build(zip_output=args.zip, skip_tests=args.skip_tests, release=args.release, full_update=args.full_update)

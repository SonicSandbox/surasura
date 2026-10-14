"""Shared by the 3.x update tests (S3.1 rows 3.1.3 and 3.1.4): a program folder shaped like a build, a signed 3.x
release built by the packager's own function into a local folder (read through SURASURA_UPDATE_SOURCE, never in a
release build), an installed program in a temp folder, and `FakeOps`, a stand-in for what the swapper asks of Windows.

The programs are fake exes (an MZ header and their version in their bytes), so the stand-in's `version()` reads what is
really in place: a swap that left the old command line reports the old version."""
import hashlib
import json
import os
import re
import sys
import uuid

import package_app
from app import build_info
from app import ed25519
from app import path_utils
from app import update_checker
from app import updater

PYTHON = sys.executable          # captured before any test points sys.executable at a fake Surasura.exe
SEED = hashlib.sha256("スラスラ swap test key (tests only)".encode("utf-8")).digest()
OLD, NEW = "3.0.0", "3.0.1"
APP_PART_FILES = ("Surasura.exe", "surasura-cli.exe", "updater.exe", "RELEASE_NOTES.md",
                  "_internal/base_library.zip", "_internal/build_stamp.json", "_internal/templates/web_app.html")
# What sits in an installed program folder besides the program: Inno's uninstaller, and the library's own folders and
# settings should an installed copy run portable (its library.json unreadable). Never moved, never named by a release.
FOREIGN = {
    "unins000.exe": b"MZ\x90\x00Inno Setup uninstaller",
    "unins000.dat": b"Inno Setup Uninstall Log (b)\x00" * 8,
    "User Files/ja/KnownWord.json": json.dumps({"words": [{"word": "上層部", "knownStatus": "KNOWN"},
                                                          {"word": "一生懸命", "knownStatus": "LEARNING"}]},
                                               ensure_ascii=False).encode("utf-8"),
    "data/zh/HighPriority/第一章.txt": "我们一起学习中文。\r\n今天很开心。\n".encode("utf-8"),
    "results/reading_list_static.html": "<p>語彙の旅</p>".encode("utf-8"),
    "settings.json": b'{"logic": {"phrase_rows": true}}',
}


def program(version):
    """A built program in miniature. The `app` part's files carry the version; Qt, the dictionaries and the runtime
    are the same in every version (so an ordinary release changes the app part alone)."""
    v = version.encode("ascii")
    return {
        "Surasura.exe": b"MZ\x90\x00window " + v + " 語彙の旅".encode("utf-8") * 32,
        "surasura-cli.exe": b"MZ\x90\x00cli " + v + b" " * 64,
        "updater.exe": b"MZ\x90\x00swapper " + v,
        "README.md": "# Surasura\n日本語と中文の読みやすさ\n".encode("utf-8"),
        "RELEASE_NOTES.md": f"# {version}\n- 上層 + 部 → 上層部\n".encode("utf-8"),
        "_internal/base_library.zip": b"PK\x03\x04 stdlib " + v,
        "_internal/build_stamp.json": json.dumps({"build_id": f"test-{version}", "data_name": "Surasura",
                                                  "version": version}).encode("ascii"),
        "_internal/templates/web_app.html": f"<h1>語彙の旅 {version}</h1>\n".encode("utf-8"),
        "_internal/PyQt6/QtCore.pyd": b"MZ\x90\x00qt 6.11 " * 50,
        "_internal/licenses/PyQt6/LICENSE": b"GNU GENERAL PUBLIC LICENSE\n",
        "_internal/unidic_lite/dicdir/sys.dic": "上層部\t名詞\n一生懸命\t副詞\n走り出す\t動詞\n".encode("utf-8") * 40,
        "_internal/jieba/dict.txt": "开心 3 a\n学习 5 v\n我们 9 r\n".encode("utf-8"),
        "_internal/python311.dll": b"MZ\x90\x00python 3.11",
        "_internal/sqlite3.dll": b"MZ\x90\x00sqlite 3.53.4",
    }


def old_program():
    """3.0.0 as installed: two files 3.0.1 no longer ships (both must go with the swap)."""
    files = program(OLD)
    files["UPDATE_INSTRUCTIONS.md"] = b"# Updating\n"
    files["_internal/old_only.dll"] = b"MZ\x90\x00a library 3.0.1 dropped"
    return files


def write_tree(root, files):
    for rel, data in files.items():
        path = os.path.join(str(root), *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)


def tree(root):
    """{relative '/' path: sha256} of every file under `root`."""
    found = {}
    for folder, _dirs, names in os.walk(str(root)):
        for name in names:
            full = os.path.join(folder, name)
            with open(full, "rb") as f:
                found[os.path.relpath(full, str(root)).replace(os.sep, "/")] = hashlib.sha256(f.read()).hexdigest()
    return found


def digests(files):
    return {rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()}


def build_release(tmp_path, monkeypatch, files=None, version=NEW, installer=None, needs_installer=False,
                  seed=SEED):
    """A signed 3.x release of `files` in a local folder the update check reads -> the folder."""
    final = tmp_path / f"dist-{version}" / "Surasura"
    write_tree(final, program(version) if files is None else files)
    out = tmp_path / f"release-{version}"
    out.mkdir()
    if installer is not None:
        (out / f"Surasura-{version}-setup.exe").write_bytes(installer)
    (tmp_path / "key.hex").write_text(seed.hex() + "\n", encoding="ascii")
    monkeypatch.setenv(package_app.SIGNING_KEY_ENV, str(tmp_path / "key.hex"))
    package_app._build_release(str(final), version, package_app.load_build_config(), out_dir=str(out),
                               installer=str(out / f"Surasura-{version}-setup.exe") if installer else None,
                               needs_installer=needs_installer)
    monkeypatch.setattr(build_info, "RELEASE_BUILD", False)
    monkeypatch.setenv(update_checker.UPDATE_SOURCE_ENV, str(out))
    monkeypatch.setenv(update_checker.TEST_PUBKEY_ENV, ed25519.public_key(SEED).hex())
    return out


def install(tmp_path, monkeypatch, files=None, version=OLD, layout="installed", foreign=True):
    """A frozen program in a temp folder with a Japanese name -> its folder. `layout`:
      installed  library.json names it (`installed_library` -> a library folder elsewhere) and Inno's files sit there
      unins      library.json unreadable: it runs portable (its user data beside the exe), but unins000.dat is there
      portable   neither: an unzipped copy, updated by hand"""
    root = tmp_path / "Programs" / "スラスラ 本番"
    write_tree(root, old_program() if files is None else files)
    if foreign:
        write_tree(root, {k: v for k, v in FOREIGN.items() if layout != "portable" or not k.startswith("unins")})
    library = tmp_path / "Documents" / "Surasura ライブラリ"
    library.mkdir(parents=True)
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(path_utils, "installed_library", lambda: str(library) if layout == "installed" else None)
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: str(library if layout == "installed" else root))
    monkeypatch.setattr(path_utils, "get_base_path", lambda: str(root / "_internal"))
    monkeypatch.setattr(updater.sys, "executable", str(root / "Surasura.exe"))
    monkeypatch.setattr(updater, "__version__", version)
    return root


def isolate_registry(monkeypatch):
    """Point the uninstall entry's root, in the app and the swapper, at a throwaway HKCU path (never created here):
    no test reads or writes the real Uninstall key. -> the path."""
    import updater_helper
    root = rf"Software\SurasuraTests\{uuid.uuid4().hex}\Uninstall"
    monkeypatch.setattr(updater, "UNINSTALL_ROOT", root)
    monkeypatch.setattr(updater_helper, "UNINSTALL_ROOT", root)
    return root


class FakeProcess:
    _next = 40000

    def __init__(self, exe, exits=None, code=0):
        FakeProcess._next += 1
        self.pid, self.exe, self.exits, self.code, self.polls, self.stopped = FakeProcess._next, exe, exits, code, 0, False

    def poll(self):
        self.polls += 1
        if self.stopped or (self.exits is not None and self.polls > self.exits):
            return self.code
        return None


class FakeOps:
    """What the swapper asks of Windows, scripted. `running`: pids a folder holds (a list, or a callable of the
    folder); `window`: the new window shows after that many looks (None: never); `exits` / `code`: the started
    program ends after that many polls with that code; `version`: what the command line says (default: read from
    the cli's own bytes); `setup`: run_setup's stand-in."""

    def __init__(self, running=(), window=0, exits=None, code=0, version=None, setup=None):
        self.running, self.window, self.exits, self.code = running, window, exits, code
        self.said, self.setup = version, setup
        self.started, self.stopped_pids, self.looks, self.setup_argv, self.processes = [], [], 0, None, []

    def processes_in(self, folder):
        return list(self.running(folder) if callable(self.running) else self.running)

    def start(self, exe):
        with open(exe, "rb") as f:
            self.started.append((exe, f.read()))
        self.process = FakeProcess(exe, self.exits, self.code)
        self.processes.append(self.process)
        return self.process

    def window_visible(self, pid):
        self.looks += 1
        return self.window is not None and self.looks > self.window

    def version(self, cli):
        if self.said is not None:
            return self.said
        try:
            with open(cli, "rb") as f:
                found = re.search(rb"cli (\d+\.\d+\.\d+)", f.read())
            return found.group(1).decode("ascii") if found else None
        except OSError:
            return None

    def stop(self, process):
        process.stopped = True

    def stop_pid(self, pid):
        self.stopped_pids.append(pid)

    def run_setup(self, argv):
        self.setup_argv = argv
        return self.setup(argv) if self.setup else 0

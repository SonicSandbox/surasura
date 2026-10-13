"""S3.1 row 3.1.2 (D4, D5, D6): the 3.x update.json serves 2.x and 3.x at once.

A 3.x release is built by the packager's own function (`package_app._build_release`) from a small program folder
shaped like a build, signed with a test key, into a local release folder read through the update check's override
(SURASURA_UPDATE_SOURCE, never in a release build). It is then read by:
  - v2.5.0's own app/update_checker.py and app/updater.py (loaded from `git show v2.5.0:…`): INSTALLER when the release
    carries an installer (2.5 hands over to it), FULL when it doesn't;
  - v2.4.0's rules (`git show v2.4.0:app/update_checker.py`): FULL;
  - this checkout's client: APP; tampered, wrong key, no signature: FULL (told only, nothing installed).
"""
import hashlib
import json
import os
import subprocess
import sys
import types
import urllib.request
import zipfile
from pathlib import Path

import pytest

import package_app
from app import build_info
from app import ed25519
from app import path_utils
from app import update_checker

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = hashlib.sha256("スラスラ test signing key (tests only)".encode("utf-8")).digest()
OTHER_SEED = hashlib.sha256(b"another key").digest()
INSTALLER = "Surasura-3.0.1-setup.exe"
STUB_INSTALLER = b"MZ\x90\x00stub-installer-\xe3\x81\x99\xe3\x82\x89" * 8


def _old_module(tag, path, name, monkeypatch):
    """A file as `tag` shipped it, loaded as its own module (the app package it imports is this checkout's)."""
    try:
        out = subprocess.run(["git", "show", f"{tag}:{path}"], cwd=PROJECT, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available")
    if out.returncode != 0:
        pytest.skip(f"{tag} is not in this clone")
    module = types.ModuleType(name)
    module.__file__ = os.path.join(PROJECT, path)
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(out.stdout.decode("utf-8"), f"{tag}:{path}", "exec"), module.__dict__)
    return module


def _program(root):
    """A built program folder in miniature: the three programs, the runtime, Qt, the dictionaries, templates."""
    files = {
        "Surasura.exe": b"MZ window 3.0.1",
        "surasura-cli.exe": b"MZ cli 3.0.1",
        "updater.exe": b"MZ swapper 3.0.1",
        "RELEASE_NOTES.md": "# 3.0.1\n- 語彙の旅\n".encode("utf-8"),
        "_internal/base_library.zip": b"PK stdlib",
        "_internal/build_stamp.json": b'{"build_id": "x", "data_name": "Surasura", "version": "3.0.1"}\n',
        "_internal/templates/web_app.html": "<h1>語彙の旅</h1>\n".encode("utf-8"),
        "_internal/PyQt6/QtCore.pyd": b"MZ qt",
        "_internal/licenses/PyQt6/LICENSE": b"GNU GENERAL PUBLIC LICENSE\n",
        "_internal/unidic_lite/dicdir/sys.dic": b"dic" * 100,
        "_internal/jieba/dict.txt": "吃 3 v\n".encode("utf-8"),
        "_internal/python311.dll": b"MZ python",
        "_internal/sqlite3.dll": b"MZ sqlite 3.53.4",
    }
    for rel, data in files.items():
        path = root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return files


@pytest.fixture
def release(tmp_path, monkeypatch):
    """-> make(installer=True, seed=SEED, **config_changes): a local 3.0.1 release folder, built and signed."""
    def make(installer=True, seed=SEED, needs_installer=False, min_from=None):
        final = tmp_path / "dist" / "Surasura"
        final.mkdir(parents=True)
        _program(final)
        out = tmp_path / "release"
        out.mkdir()
        if installer:
            (out / INSTALLER).write_bytes(STUB_INSTALLER)
        if seed is None:
            monkeypatch.delenv(package_app.SIGNING_KEY_ENV, raising=False)
        else:
            (tmp_path / "key.hex").write_text(seed.hex() + "\n", encoding="ascii")
            monkeypatch.setenv(package_app.SIGNING_KEY_ENV, str(tmp_path / "key.hex"))
        config = package_app.load_build_config()
        if min_from:
            config["release"]["min_from"] = min_from
        manifest = package_app._build_release(str(final), "3.0.1", config, out_dir=str(out),
                                              installer=str(out / INSTALLER) if installer else None,
                                              needs_installer=needs_installer)
        return out, manifest
    monkeypatch.setattr(build_info, "RELEASE_BUILD", False)
    return make


@pytest.fixture
def rehearsal(monkeypatch):
    """Point the update check at a release folder, trusting a test key (non-release build only)."""
    def point(folder, trusted=SEED):
        monkeypatch.setenv(update_checker.UPDATE_SOURCE_ENV, str(folder))
        if trusted is None:
            monkeypatch.delenv(update_checker.TEST_PUBKEY_ENV, raising=False)
        else:
            monkeypatch.setenv(update_checker.TEST_PUBKEY_ENV, ed25519.public_key(trusted).hex())
    return point


# --- what the packager writes ---------------------------------------------------------------------------------------------

def test_the_manifest_is_canonical_signed_and_lists_every_file(release, tmp_path):
    out, manifest = release()
    data = (out / "update.json").read_bytes()
    assert data == package_app.canonical_json(json.loads(data)) and data.endswith(b"}\n") and b"\r" not in data
    assert ed25519.verify(ed25519.public_key(SEED), data, (out / "update.json.sig").read_bytes())
    # 2.x's keys, written for 2.x readers, then the 3.x block.
    assert manifest["update_type"] == "installer" and manifest["format"] == 2
    assert manifest["installer"] == {"asset": INSTALLER, "sha256": hashlib.sha256(STUB_INSTALLER).hexdigest(),
                                     "args": [], "min_from": "2.5"}
    package = manifest["package"]
    assert package["min_from"] == "3.0.0" and package["needs_installer"] is False
    assert package["install_shape"] == package_app.install_shape()          # the .iss the build's installer is from
    built = tmp_path / "dist" / "Surasura"
    on_disk = {p.relative_to(built).as_posix() for p in built.rglob("*") if p.is_file()}
    assert {f["path"] for f in package["files"]} == on_disk
    for entry in package["files"]:
        content = built.joinpath(*entry["path"].split("/")).read_bytes()
        assert entry["sha256"] == hashlib.sha256(content).hexdigest() and entry["size"] == len(content)
    assert {f["path"]: f["part"] for f in package["files"]}["_internal/PyQt6/QtCore.pyd"] == "qt"
    # Each part: one zip holding exactly its files, its sha256 and size as recorded.
    assert [p["name"] for p in package["parts"]] == ["app", "qt", "dict", "runtime"]
    for part in package["parts"]:
        path = out / part["asset"]
        assert part["asset"] == f"surasura_part_{part['name']}_v3.0.1.zip"
        assert part["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest() and part["size"] == path.stat().st_size
        with zipfile.ZipFile(path) as z:
            assert sorted(z.namelist()) == sorted(f["path"] for f in package["files"] if f["part"] == part["name"])


def test_no_installer_writes_full_for_2x_and_no_installer_block(release):
    _out, manifest = release(installer=False)
    assert manifest["update_type"] == "full" and "installer" not in manifest


def test_no_signing_key_writes_no_signature_and_says_so_loudly(release, capsys):
    out, _manifest = release(seed=None)
    assert not (out / "update.json.sig").exists()
    assert "NOT signed" in capsys.readouterr().out


def test_the_key_is_never_printed(release, capsys):
    release()
    printed = capsys.readouterr().out
    assert SEED.hex() not in printed and ed25519.public_key(SEED).hex() not in printed


def test_an_unreadable_key_file_signs_nothing(release, tmp_path, monkeypatch, capsys):
    out, _ = release(seed=None)
    (tmp_path / "bad.key").write_text("not a key", encoding="ascii")
    monkeypatch.setenv(package_app.SIGNING_KEY_ENV, str(tmp_path / "bad.key"))
    (tmp_path / "dist2").mkdir()
    _program(tmp_path / "dist2")
    package_app._build_release(str(tmp_path / "dist2"), "3.0.1", package_app.load_build_config(), out_dir=str(out))
    assert not (out / "update.json.sig").exists()
    assert "not a key" not in capsys.readouterr().out


# --- 2.5.0's own client: INSTALLER with an installer, FULL without ----------------------------------------------------------

@pytest.fixture
def frozen_25(tmp_path, monkeypatch):
    root = tmp_path / "スラスラ 2.5"
    (root / "_internal").mkdir(parents=True)
    (root / "updater.exe").write_bytes(b"MZ")
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: str(root))
    monkeypatch.setattr(path_utils, "get_base_path", lambda: str(root / "_internal"))
    return root


def test_2_5_0_hands_a_3x_release_to_its_installer(release, rehearsal, frozen_25, monkeypatch):
    out, _ = release()
    rehearsal(out, trusted=None)                              # 2.5 knows nothing of signatures
    old_uc = _old_module("v2.5.0", "app/update_checker.py", "update_checker_v2_5_0", monkeypatch)
    old_up = _old_module("v2.5.0", "app/updater.py", "updater_v2_5_0", monkeypatch)
    old_up.__version__ = "2.5.0"
    info = old_uc.get_update_info()
    assert info.version == "3.0.1"
    cls = old_uc.classify_update("2.5.0", info)
    assert cls == "INSTALLER"
    assert old_up.effective_class(cls, info, skipped_version=None, auto_enabled=True,
                                  can_apply=old_up.can_auto_apply(info), failed_version=None) == "INSTALLER"
    monkeypatch.setitem(sys.modules, "app.update_checker", old_uc)      # 2.5's prepare_installer asks its own rules
    staged = old_up.prepare_installer(info)
    assert Path(staged["path"]).read_bytes() == STUB_INSTALLER and staged["args"] == []


def test_2_5_0_sees_a_3x_release_without_an_installer_as_a_download(release, rehearsal, frozen_25, monkeypatch):
    out, _ = release(installer=False)
    rehearsal(out, trusted=None)
    old_uc = _old_module("v2.5.0", "app/update_checker.py", "update_checker_v2_5_0", monkeypatch)
    old_up = _old_module("v2.5.0", "app/updater.py", "updater_v2_5_0", monkeypatch)
    info = old_uc.get_update_info()
    cls = old_uc.classify_update("2.5.0", info)
    assert cls == "FULL"
    assert old_up.effective_class(cls, info, None, True, old_up.can_auto_apply(info), None) == "FULL"


@pytest.mark.parametrize("installer", [True, False], ids=["with installer", "without"])
def test_2_4_0_sees_a_3x_release_as_a_download(release, monkeypatch, installer):
    out, _ = release(installer=installer)
    old_uc = _old_module("v2.4.0", "app/update_checker.py", "update_checker_v2_4_0", monkeypatch)
    assets = [{"name": p.name, "browser_download_url": p.as_uri()} for p in sorted(out.iterdir())]
    monkeypatch.setattr(old_uc, "_http_json", lambda url, timeout=10: {"tag_name": "v3.0.1", "html_url": "https://x",
                                                                       "assets": assets})
    monkeypatch.setattr(old_uc, "_http_text", lambda url, timeout=10: urllib.request.urlopen(url).read().decode("utf-8"))
    info = old_uc.get_update_info()
    assert info.version == "3.0.1"
    assert old_uc.classify_update("2.4.0", info) == "FULL"


# --- the 3.x client ---------------------------------------------------------------------------------------------------------

def test_a_3x_install_takes_a_signed_package_in_place(release, rehearsal):
    out, manifest = release()
    rehearsal(out)
    info = update_checker.get_update_info()
    assert info.format == 2 and info.signed is True and info.package == manifest["package"]
    assert update_checker.classify_update("3.0.0", info) == "APP"
    for part in info.package["parts"]:
        assert info.assets[part["asset"].lower()].startswith("file:")


def test_tampering_with_one_byte_is_told_only(release, rehearsal):
    out, _ = release()
    data = bytearray((out / "update.json").read_bytes())
    at = data.index(b'"sha256": "') + len(b'"sha256": "') + 3
    data[at] = ord("0") if data[at] != ord("0") else ord("1")
    (out / "update.json").write_bytes(bytes(data))
    rehearsal(out)
    info = update_checker.get_update_info()
    assert info.signed is False and info.package is None
    assert update_checker.classify_update("3.0.0", info) == "FULL"


def test_another_key_is_told_only(release, rehearsal):
    out, _ = release()
    rehearsal(out, trusted=OTHER_SEED)
    info = update_checker.get_update_info()
    assert info.signed is False and update_checker.classify_update("3.0.0", info) == "FULL"


def test_a_missing_signature_is_told_only(release, rehearsal):
    out, _ = release()
    (out / "update.json.sig").unlink()
    rehearsal(out)
    assert update_checker.classify_update("3.0.0", update_checker.get_update_info()) == "FULL"


def test_a_signature_of_the_wrong_size_is_told_only(release, rehearsal):
    out, _ = release()
    (out / "update.json.sig").write_bytes((out / "update.json.sig").read_bytes() * 20)     # 1,280 bytes: over the cap
    rehearsal(out)
    assert update_checker.classify_update("3.0.0", update_checker.get_update_info()) == "FULL"


def test_no_trusted_key_at_all_is_told_only(release, rehearsal, monkeypatch):
    """A release signed by a key the program doesn't hold (here: the production keys are not the test key) installs
    nothing in place; with the key trusted, it does."""
    out, _ = release()
    rehearsal(out, trusted=None)
    assert ed25519.public_key(SEED) not in update_checker.PUBLIC_KEYS
    assert update_checker.classify_update("3.0.0", update_checker.get_update_info()) == "FULL"
    monkeypatch.setattr(update_checker, "PUBLIC_KEYS", ())
    assert update_checker.classify_update("3.0.0", update_checker.get_update_info()) == "FULL"
    monkeypatch.setattr(update_checker, "PUBLIC_KEYS", (ed25519.public_key(SEED),))
    assert update_checker.classify_update("3.0.0", update_checker.get_update_info()) == "APP"


def test_the_production_key_is_one_32_byte_ed25519_public_key():
    """The shipped key: 32 bytes, a valid point (verify runs without error on a wrong signature and says False)."""
    assert len(update_checker.PUBLIC_KEYS) >= 1
    for key in update_checker.PUBLIC_KEYS:
        assert isinstance(key, bytes) and len(key) == 32
        assert ed25519.verify(key, b"surasura", bytes(64)) is False


def test_the_test_key_counts_only_in_a_rehearsal(monkeypatch):
    monkeypatch.setenv(update_checker.TEST_PUBKEY_ENV, ed25519.public_key(SEED).hex())
    production = [bytes(k) for k in update_checker.PUBLIC_KEYS]
    assert update_checker._trusted_keys(local=None) == production
    assert update_checker._trusted_keys(local="folder") == production + [ed25519.public_key(SEED)]


def test_a_release_build_never_reads_the_rehearsal_folder(release, rehearsal, monkeypatch):
    out, _ = release()
    rehearsal(out)
    monkeypatch.setattr(build_info, "RELEASE_BUILD", True)
    asked = []
    monkeypatch.setattr(update_checker, "_http_json", lambda url, timeout=10: asked.append(url) or None)
    assert update_checker.get_update_info() is None and asked


@pytest.mark.parametrize("current, installer, expected", [
    ("2.9.0", True, "INSTALLER"),      # below min_from 3.0.0: the installer must run
    ("2.9.0", False, "FULL"),
    ("3.0.1", True, "NONE"),
])
def test_below_min_from_the_installer_runs(release, rehearsal, current, installer, expected):
    out, _ = release(installer=installer)
    rehearsal(out)
    assert update_checker.classify_update(current, update_checker.get_update_info()) == expected


@pytest.mark.parametrize("installer, expected", [(True, "INSTALLER"), (False, "FULL")])
def test_a_release_that_needs_the_installer_runs_it(release, rehearsal, installer, expected):
    out, _ = release(installer=installer, needs_installer=True)
    rehearsal(out)
    assert update_checker.classify_update("3.0.0", update_checker.get_update_info()) == expected


def test_an_unsigned_release_never_reaches_the_installer_either(release, rehearsal):
    out, _ = release(needs_installer=True)
    (out / "update.json.sig").unlink()
    rehearsal(out)
    assert update_checker.classify_update("3.0.0", update_checker.get_update_info()) == "FULL"


def _resign(out, change):
    manifest = json.loads((out / "update.json").read_bytes())
    change(manifest)
    data = package_app.canonical_json(manifest)
    (out / "update.json").write_bytes(data)
    (out / "update.json.sig").write_bytes(ed25519.sign(SEED, data))


@pytest.mark.parametrize("change", [
    lambda m: m["package"]["parts"].pop(0),                                    # a file names a part not listed
    lambda m: m["package"]["parts"][0].update(asset="surasura_part_gone.zip"),  # a part's asset not in the release
    lambda m: m["package"]["files"][0].update(sha256="ABC"),
    lambda m: m["package"]["files"][0].update(size=True),
    lambda m: m["package"].update(needs_installer="no"),
    lambda m: m["package"].update(install_shape="1ff00720"),
    lambda m: m["package"].update(install_shape="ZZZZZZZZZZZZZZZZ"),
    lambda m: m["package"].update(files=[]),
    lambda m: m.update(package="all"),
], ids=["unknown part", "missing asset", "bad sha256", "bool size", "needs_installer not bool", "short shape",
        "shape not hex", "no files", "not a dict"])
def test_a_signed_but_malformed_package_is_told_only(release, rehearsal, change):
    out, _ = release()
    _resign(out, change)
    rehearsal(out)
    info = update_checker.get_update_info()
    assert info.signed is True and info.package is None
    assert update_checker.classify_update("3.0.0", info) == "FULL"


# --- the install shape (S3.1 D7): a release whose installer changes what only it can change runs it ---------------------

OTHER_SHAPE = "0123456789abcdef"


@pytest.fixture
def stamped(tmp_path, monkeypatch):
    """-> stamp(shape, frozen=True, raw=None): this program as an installed 3.0.0 whose _internal/build_stamp.json
    carries `shape` (None: an earlier 3.x's stamp, without one; `raw`: the file's bytes as given)."""
    def stamp(shape, frozen=True, raw=None):
        internal = tmp_path / "Programs" / "スラスラ" / "_internal"
        internal.mkdir(parents=True, exist_ok=True)
        data = {"build_id": "20261012T000000Z-0a1b2c3d", "data_name": "Surasura", "version": "3.0.0"}
        if shape is not None:
            data["install_shape"] = shape
        (internal / "build_stamp.json").write_bytes(raw if raw is not None else json.dumps(data).encode("utf-8"))
        monkeypatch.setattr(path_utils, "is_frozen", lambda: frozen)
        monkeypatch.setattr(path_utils, "get_base_path", lambda: str(internal))
    return stamp


@pytest.mark.parametrize("own, installer, needs_installer, expected", [
    ("same", True, False, "APP"),           # the .iss this program was built with: the parts alone
    ("other", True, False, "INSTALLER"),    # another shape: the release's installer runs, silently
    ("other", False, False, "FULL"),        # ... and with no installer in the release, a download
    (None, True, False, "APP"),             # an earlier 3.x's stamp, without a shape: the parts
    (None, True, True, "INSTALLER"),        # ... unless the release asks for its installer itself
    ("same", True, True, "INSTALLER"),      # the override, whatever the shapes say
], ids=["same shape", "another shape", "another shape, no installer", "no shape stamped", "no shape, the override",
        "same shape, the override"])
def test_the_install_shape_decides_between_the_parts_and_the_installer(release, rehearsal, stamped, own, installer,
                                                                       needs_installer, expected):
    out, manifest = release(installer=installer, needs_installer=needs_installer)
    assert manifest["package"]["install_shape"] != OTHER_SHAPE
    rehearsal(out)
    stamped({"same": manifest["package"]["install_shape"], "other": OTHER_SHAPE}.get(own))
    assert update_checker.classify_update("3.0.0", update_checker.get_update_info()) == expected


def test_a_release_without_a_shape_takes_the_parts(release, rehearsal, stamped):
    """A release written before the shape (or by hand without one) compares as the same: the parts."""
    out, _ = release()
    _resign(out, lambda m: m["package"].pop("install_shape"))
    rehearsal(out)
    stamped(OTHER_SHAPE)
    info = update_checker.get_update_info()
    assert info.package is not None and "install_shape" not in info.package
    assert update_checker.classify_update("3.0.0", info) == "APP"


def test_this_programs_shape_is_read_from_its_own_stamp_only_when_frozen(stamped):
    assert update_checker.installed_shape() is None                     # from source: no stamp of its own
    stamped("fedcba9876543210")
    assert update_checker.installed_shape() == "fedcba9876543210"
    stamped("fedcba9876543210", frozen=False)                           # a stamp where a source run's resources are
    assert update_checker.installed_shape() is None
    stamped(None)
    assert update_checker.installed_shape() is None
    stamped("FEDCBA9876543210")                                         # no shape the packager writes
    assert update_checker.installed_shape() is None
    stamped(None, raw=b"\xef\xbb\xbf" + json.dumps({"install_shape": "fedcba9876543210"}).encode("ascii"))
    assert update_checker.installed_shape() == "fedcba9876543210"      # a BOM, as Windows tools may write
    for raw in (b"{not json", b'["install_shape"]'):
        stamped(None, raw=raw)
        assert update_checker.installed_shape() is None

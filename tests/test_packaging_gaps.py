"""S3.1 row 3.1.3: gaps the Haiku mutant list found in the packager (tests/test_update_format3.py holds the rest). No
real signing key is read: each key here is a test seed in a temp folder."""
import hashlib

import pytest

import package_app
from tests.test_packaging_config import _program

SEED = hashlib.sha256("スラスラ test signing key (tests only)".encode("utf-8")).digest()


def test_a_key_file_holding_a_64_byte_secret_is_refused_before_anything_is_written(tmp_path):
    # Many tools save an Ed25519 secret as 64 bytes (the seed, then the public key): 128 hex characters. The key
    # reader takes exactly 32 bytes, so the build stops at the key ("no update.json written"). A reader taking any
    # length of 32 or more would hand the signer 64 bytes, and the build would fail only after writing an unsigned
    # update.json and its parts.
    secret = tmp_path / "secret.hex"
    secret.write_text((SEED + SEED).hex() + "\n", encoding="ascii")
    with pytest.raises(ValueError) as refused:
        package_app.read_signing_key(str(secret))
    assert SEED.hex() not in str(refused.value), "the file is never quoted"


def test_a_sqlite_exactly_at_the_floor_passes(tmp_path):
    # The floor is "at or above" (build_config's sqlite_min): a program carrying exactly the floor's SQLite is whole.
    # The vendored DLL is newer than today's floor, so only a floor raised to it tells "at" from "above".
    folder, config = _program(tmp_path)
    vendored = package_app.sqlite_version_of(str(folder / "_internal" / "sqlite3.dll"))
    failures, facts = package_app.check_program(str(folder), dict(config, sqlite_min=vendored))
    assert facts["sqlite"] == vendored and failures == []


def test_a_licence_folder_left_empty_holds_no_licence_notice(tmp_path):
    # PyQt6 is bundled only with its and Qt's licence notices: a licences folder that is there but empty (a copy step
    # that made the folder and copied nothing) carries none, and the build stops on it.
    folder, config = _program(tmp_path, licences=False)
    (folder / "_internal" / "licenses" / "PyQt6").mkdir(parents=True)
    (folder / "_internal" / "licenses" / "PyQt6-Qt6").mkdir(parents=True)
    (folder / "_internal" / "licenses" / "PyQt6-Qt6" / "LICENSE").write_text("GNU LESSER GENERAL PUBLIC LICENSE\n",
                                                                            encoding="utf-8")
    failures, _facts = package_app.check_program(str(folder), config)
    assert failures == ["_internal/licenses/PyQt6 holds no licence notice"]

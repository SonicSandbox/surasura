"""S3.1 row 3.1.2: gaps the Haiku mutant list found in the update check's reading of a 3.x release (tests/
test_update_format3.py holds the rest). Pure: no network, no download."""
import hashlib

from app import update_checker

ASSET = "surasura_part_app_v3.0.1.zip"


def test_a_package_holding_an_empty_file_is_read_whole():
    # A real program folder holds empty files (a package's `REQUESTED` or `py.typed` marker, an empty `__init__.py`):
    # a file of size 0 is a size. Refusing it would turn every such release into "told only" — nothing installed.
    package = {
        "parts": [{"name": "app", "asset": ASSET, "sha256": "ab" * 32, "size": 10}],
        "files": [{"path": "Surasura.exe", "sha256": "cd" * 32, "size": 5, "part": "app"},
                  {"path": "_internal/fugashi-1.3.0.dist-info/REQUESTED", "sha256": hashlib.sha256(b"").hexdigest(),
                   "size": 0, "part": "app"}],
        "needs_installer": False,
        "min_from": "3.0.0",
    }
    assert update_checker._read_package(package, {ASSET}) is package

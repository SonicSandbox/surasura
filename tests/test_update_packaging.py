"""End-to-end lock between the release packager and the in-app client.

package_app._build_app_package() writes the app-package zip + update.json attached to a
GitHub release. This proves what the packager emits is exactly what the client (app.updater)
accepts: the advertised sha256 matches the zip, and the zip passes extract_and_validate().
The app package is the code-bearing Surasura.exe + the loose templates/ dir.
"""
import os
import json

import package_app
from app import updater


EXE_BYTES = b"MZ\x90\x00fake-surasura-exe-\xe8\xaa\x9e" * 32


def _make_fake_dist(root, version):
    """Create a minimal final_dist with Surasura.exe + _internal/templates, like a real build."""
    final = os.path.join(root, f"Surasura_v{version}")
    internal = os.path.join(final, "_internal")
    os.makedirs(os.path.join(internal, "templates"), exist_ok=True)
    with open(os.path.join(final, "Surasura.exe"), "wb") as f:
        f.write(EXE_BYTES)
    with open(os.path.join(internal, "templates", "web_app.html"), "w", encoding="utf-8") as f:
        f.write("<h1>語彙の旅</h1>\n")
    return final


def test_app_package_matches_client_expectations(tmp_path, monkeypatch):
    version = "2.1"
    monkeypatch.chdir(tmp_path)
    os.makedirs("dist", exist_ok=True)
    final_dist = _make_fake_dist(str(tmp_path / "dist"), version)

    package_app._build_app_package(final_dist, version, full_update=False)

    pkg = os.path.join("dist", f"Surasura_app_v{version}.zip")
    manifest_path = os.path.join("dist", "update.json")
    assert os.path.exists(pkg)
    assert os.path.exists(manifest_path)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["update_type"] == "app"
    assert manifest["version"] == version

    # The client's checksum check must accept the packager's zip...
    assert updater.sha256_file(pkg).lower() == manifest["sha256"].lower()
    # ...and the client's validation must accept the packager's payload.
    payload = str(tmp_path / "payload")
    assert updater.extract_and_validate(pkg, payload) is True
    assert os.path.isfile(os.path.join(payload, "Surasura.exe"))


def test_full_update_manifest_has_no_package(tmp_path, monkeypatch):
    """A --full-update release publishes only update.json (update_type=full), no app package."""
    version = "3.0"
    monkeypatch.chdir(tmp_path)
    os.makedirs("dist", exist_ok=True)
    final_dist = _make_fake_dist(str(tmp_path / "dist"), version)

    package_app._build_app_package(final_dist, version, full_update=True)

    assert not os.path.exists(os.path.join("dist", f"Surasura_app_v{version}.zip"))
    with open(os.path.join("dist", "update.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["update_type"] == "full"
    assert manifest["runtime_baseline"] == version  # advanced the runtime boundary

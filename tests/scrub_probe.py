"""A made-up person on a made-up PC, for the scrub's tests (Send report, SR-1; the packet's §4 *Data*): every string a
report could name them by, set where Surasura reads it — the environment, Anki's folder, Connect's record, the
telemetry id — under the test's own folders, never the real profile."""
import json
import os
import socket
import platform
from types import SimpleNamespace

from app import path_utils, scrub

FOLDER = "Zoë Tanaka-Probe"          # a home folder with a space, a letter outside ASCII and a hyphen
ACCOUNT = "ztanprobe"                # a different USERNAME (a Microsoft account's folder isn't USERNAME)
SHORT = "ZOTANA~1"                   # its 8.3 short form
MACHINE = "DESKTOP-PROBE7"
ORG = "Probe Org"
PROFILE = "Probe Anki"
TELEMETRY_ID = "6f1c2d3e-4b5a-4c6d-8e7f-90a1b2c3d4e5"
EMAIL = "zoe.probe@example.co.jp"


def make(tmp_path, monkeypatch):
    """Set the probe person up. -> a namespace: `home`, `short_home`, `strings` (every identifying string, raw)."""
    home = tmp_path / "Users" / FOLDER
    roaming, local = home / "AppData" / "Roaming", home / "AppData" / "Local"
    for d in (roaming, local, home / "Videos", home / f"OneDrive - {ORG}" / "Documents",
              roaming / "Anki2" / PROFILE, roaming / "Anki2" / "User 1", roaming / "Anki2" / "addons21"):
        d.mkdir(parents=True, exist_ok=True)
    (roaming / "Anki2" / PROFILE / "collection.anki2").write_bytes(b"")
    (roaming / "Anki2" / "User 1" / "collection.anki2").write_bytes(b"")
    short_home = str(tmp_path / "Users" / SHORT)
    for name in ("HOME", "USER", "LOGNAME", "HOMEDRIVE", "HOMEPATH", "OneDrive", "OneDriveConsumer"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("USERNAME", ACCOUNT)
    monkeypatch.setenv("COMPUTERNAME", MACHINE)
    monkeypatch.setenv("USERDOMAIN", MACHINE)
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("OneDriveCommercial", str(home / f"OneDrive - {ORG}"))
    monkeypatch.setattr(socket, "gethostname", lambda: MACHINE.lower())
    monkeypatch.setattr(platform, "node", lambda: MACHINE)
    monkeypatch.setattr(scrub, "_short", lambda path: short_home if os.path.normcase(path) == os.path.normcase(
        str(home)) else None)
    persistent = path_utils.get_persistent_user_data_path()
    with open(os.path.join(persistent, "telemetry_id.json"), "w", encoding="utf-8") as f:
        json.dump({"uid": TELEMETRY_ID, "open_count": 3}, f)
    scrub.reset()
    keys = scrub._keys()
    return SimpleNamespace(home=str(home), short_home=short_home, keys=keys,
                           strings=[FOLDER, ACCOUNT, SHORT, MACHINE, ORG, PROFILE, TELEMETRY_ID, EMAIL] + keys)

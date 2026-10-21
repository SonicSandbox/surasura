"""tsubasa's pin against its latest release (T1 B, 2026-10-21; the build ritual, Pre-build_check.md).

    python packaging/tsubasa_pin.py           the pin, what this Python has and tsubasa's latest release: exit 0
                                              when all three agree, 1 when the pin is behind the release or this
                                              Python isn't the pin
    python packaging/tsubasa_pin.py --bump    moves requirements.txt's pin to the latest release (then: pip install
                                              -r requirements.txt, the suites, and the build)

The latest release is SonicSandbox/Tsubasa-sync's on GitHub (releases/latest): the build machine's one call here, never
the app's. Unreachable, or a tag that isn't a plain version: exit 2, nothing changed. Sonic's condition on T1 B: "make sure that tsubasa updates are included
when needed" — tsubasa.exe ships inside Surasura, so a tsubasa fix reaches users only through a Surasura update."""
import argparse
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import package_app  # noqa: E402

LATEST_URL = "https://api.github.com/repos/SonicSandbox/Tsubasa-sync/releases/latest"
_TAG = re.compile(r"v?(\d+(?:\.\d+){1,3})\Z")


def latest_release(fetch=None):
    """tsubasa's latest release on GitHub -> 'X.Y.Z' (its tag without the v), or None when it can't be read.
    `fetch(url)` -> the response's bytes (a test's stand-in)."""
    def _get(url):
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": "surasura-build"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    try:
        tag = json.loads((fetch or _get)(LATEST_URL)).get("tag_name")
    except Exception:
        return None
    found = _TAG.match(tag) if isinstance(tag, str) else None
    return found.group(1) if found else None


def bump(version, path=package_app.REQUIREMENTS):
    """requirements.txt's tsubasa-sync requirement becomes `tsubasa-sync==<version>`; every other byte stays (a byte
    order mark, the line's own comment, every line end)."""
    with open(path, "rb") as f:
        text = f.read().decode("utf-8")
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    out, done = [], 0
    for line in text[len(bom):].splitlines(keepends=True):
        body = line.rstrip("\r\n")
        requirement = body.split("#", 1)[0].rstrip()
        if package_app._TSUBASA_LINE.match(requirement.strip()):
            line = f"tsubasa-sync=={version}" + line[len(requirement):]
            done += 1
        out.append(line)
    if done != 1:
        raise ValueError(f"requirements.txt names tsubasa-sync on {done} lines, not one")
    with open(path, "wb") as f:
        f.write((bom + "".join(out)).encode("utf-8"))


def main(argv=None, fetch=None, path=package_app.REQUIREMENTS):
    parser = argparse.ArgumentParser(description="tsubasa's pin against its latest release.")
    parser.add_argument("--bump", action="store_true", help="move requirements.txt's pin to the latest release")
    args = parser.parse_args(argv)
    pin, have, latest = package_app.tsubasa_pin(path), package_app.tsubasa_installed(), latest_release(fetch)
    print(f"tsubasa: requirements.txt pins {pin or 'nothing exactly'}, this Python has {have or 'none'}, "
          f"the latest release is {latest or 'unknown (no answer from GitHub)'}")
    if latest is None:
        print("Can't read tsubasa's latest release: check it by hand before the build "
              "(https://github.com/SonicSandbox/Tsubasa-sync/releases).")
        return 2
    behind = pin is None or package_app._version_tuple(pin) < package_app._version_tuple(latest)
    if behind and args.bump:
        bump(latest, path)
        print(f"Pin moved to tsubasa-sync=={latest}. Next: pip install -r requirements.txt, the suites, then build.")
        return 0
    if behind:
        print(f"The pin is behind tsubasa {latest}: run python packaging/tsubasa_pin.py --bump.")
        return 1
    if have != pin:
        print("This Python isn't the pin: run pip install -r requirements.txt.")
        return 1
    print("OK: the build carries tsubasa's latest release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

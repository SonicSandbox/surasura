"""Write packaging/licenses/PyQt6-Qt6/Qt-third-party-notices.txt (DEV ONLY — run once per Qt version the build takes).

Why this exists
---------------
The program carries Qt's own DLLs and plugins (the PyQt6-Qt6 wheel). Qt is LGPL-3.0 (that wheel's LICENSE), but those
DLLs also compile in third-party code — PCRE2, FreeType, HarfBuzz, libpng, libjpeg, zlib, the Unicode data … —
each with its own licence that asks for its notice to ship. The wheel carries none of them. Qt lists each one in a
qt_attribution.json beside its code; this script reads those files at the Qt version's tag (GitHub's mirrors of
qtbase, qtsvg and qtimageformats) and writes every one the program's Qt parts carry, with its licence text, into one
file. package_app.py adds that file to PyQt6-Qt6's licence texts (`SUPPLIED_LICENCES`), and its --check refuses a build
whose PyQt6-Qt6 is another version than the file's first line names (`QT_NOTICES`).

Which ones: the Windows build of Qt Core, Gui, Network, Widgets and Svg (packaging/build_config.json's qt_modules) and
the plugins PyInstaller ships with them (platforms, styles, image formats, icon engines, TLS, network information);
Qt6Pdf and Mesa's software OpenGL never ship (build_config's qt_never_bundle). `CARRIED` names the attributions those
parts carry, `LEFT_OUT` every other one and why; an attribution in neither list stops the script, so a new one in a
later Qt is looked at, never dropped or added quietly.

    python scripts/build_qt_notices.py 6.11.2

Network: raw.githubusercontent.com and api.github.com, here only (a developer's run, never the app's).
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "packaging", "licenses", "PyQt6-Qt6", "Qt-third-party-notices.txt")
REPOS = ("qtbase", "qtsvg", "qtimageformats")
# The attributions (their Id) the program's Qt parts carry on Windows.
CARRIED = {
    # Qt Core
    "blake2", "doubleconversion", "easing", "md4", "md5", "pcre2", "pcre2-sljit", "rfc6234", "sha1", "sha3_endian",
    "sha3_keccak", "siphash", "tinycbor", "zlib", "tlexpected", "tika-mimetypes", "unicode-character-database",
    "unicode-cldr",
    # Qt Gui: its text, painting, RHI, the OpenGL and Vulkan headers, the PNG it reads itself
    "emoji-segmenter", "freetype", "freetype-zlib", "freetype-bdf", "freetype-pcf", "harfbuzz-ng",
    "icc-srgb-color-profile", "libpng", "md4c", "grayraster", "smooth-scaling-algorithm", "xserverhelper", "aglfn",
    "webgradients", "d3d12memoryallocator", "vulkanmemoryallocator", "rhi-miniengine-d3d12-mipmap", "opengl-headers",
    "opengl-es2-headers", "vulkan-xml-spec",
    # Qt Network · the Windows platform plugin · Qt Svg · the image format plugins
    "psl-data", "libpsl", "wintab", "xsvg", "libjpeg", "libtiff", "libwebp",
}
# Attributions the program's Qt parts don't carry on Windows -> why (Qt's own QtUsage words, shortened).
LEFT_OUT = {
    "extra-cmake-modules": "Qt's build system only", "kwin": "Qt's build system only",
    "cmake-runcmake-test-modules": "Qt's build system only", "android-gradle-wrapper": "Android packages only",
    "android-native-style": "the Android platform plugin", "forkfd": "Qt Core on Unix only",
    "pixman": "Qt GUI on ARM NEON only", "sqlite": "the Qt SQL plugin (not shipped)",
    "dejayvu": "the WebAssembly platform only", "xcb-xinput": "the XCB (Linux) platform plugin",
    "qeventdispatcher_cf": "Qt Core on macOS only", "libdbus-1-headers": "Qt D-Bus (not shipped)",
    "cocoa-platform-plugin": "the macOS platform plugin", "catch2": "Qt Test (not shipped)",
    "cycle": "Qt Test (not shipped)", "linuxperf": "Qt Test (not shipped)", "valgrind": "Qt Test (not shipped)",
}
LEFT_OUT_FOLDERS = ("src/3rdparty/wayland/",)       # the Wayland protocols: Linux's platform plugin only


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "build-qt-notices"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _attribution_files(repo, tag):
    tree = json.loads(_get(f"https://api.github.com/repos/qt/{repo}/git/trees/v{tag}?recursive=1"))
    return sorted(t["path"] for t in tree["tree"] if t["path"].endswith("qt_attribution.json"))


def _text(repo, tag, path):
    return _get(f"https://raw.githubusercontent.com/qt/{repo}/v{tag}/{path}").decode("utf-8-sig").replace("\r\n", "\n")


def _licence_paths(folder, entry):
    """The licence texts an attribution names (beside its json), else the repo's LICENSES/<SPDX id>.txt for each id in
    its LicenseId -> [repo path]."""
    named = entry.get("LicenseFiles") or entry.get("LicenseFile")
    if named:
        names = named if isinstance(named, list) else [named]
        return [os.path.normpath(os.path.join(folder, n)).replace(os.sep, "/") for n in names]
    ids = [t for t in entry.get("LicenseId", "").replace("(", " ").replace(")", " ").split()
           if t not in ("AND", "OR", "WITH")]
    return [f"LICENSES/{i}.txt" for i in ids]


def build(tag):
    entries, unknown = [], []
    for repo in REPOS:
        for path in _attribution_files(repo, tag):
            if path.startswith(LEFT_OUT_FOLDERS):
                continue
            data = json.loads(_text(repo, tag, path), strict=False)
            for entry in data if isinstance(data, list) else [data]:
                if entry.get("Id") in CARRIED:
                    entries.append((repo, os.path.dirname(path), entry))
                elif entry.get("Id") not in LEFT_OUT:
                    unknown.append(f"{repo}/{path}: {entry.get('Id')} ({entry.get('QtUsage')!r})")
    if unknown:
        sys.exit("New attributions: put each in CARRIED or LEFT_OUT first:\n  " + "\n  ".join(unknown))
    gone = CARRIED - {e[2].get("Id") for e in entries}
    if gone:
        print(f"Not in Qt {tag} any more (drop them from CARRIED): {sorted(gone)}")
    texts = {}
    lines = [f"Qt {tag} — the third-party components of the Qt parts Surasura's program carries",
             "",
             "The program carries Qt Core, Gui, Network, Widgets and Svg (Windows) and their plugins, from the",
             "PyQt6-Qt6 wheel (LGPL-3.0: its LICENSE, beside this file). Those parts compile in the components below,",
             "each under its own licence. Listed from Qt's qt_attribution.json files at the v" + tag + " tag of",
             "qtbase, qtsvg and qtimageformats (scripts/build_qt_notices.py); each licence text follows, once, at the",
             "end.",
             "Qt's own page of them: https://doc.qt.io/qt-6/licenses-used-in-qt.html", ""]
    for repo, folder, entry in sorted(entries, key=lambda e: e[2].get("Name", "").casefold()):
        licences = _licence_paths(folder, entry)
        for p in licences:
            texts.setdefault((repo, p), None)
        lines += ["=" * 100, entry.get("Name", entry.get("Id", "")),
                  f"  Version: {entry.get('Version') or '-'}",
                  f"  Used in: {' '.join((entry.get('QtUsage') or '').split())}",
                  f"  Licence: {entry.get('License') or ''} ({entry.get('LicenseId') or '-'})",
                  f"  Licence text: {', '.join(f'{repo}/{p}' for p in licences)}",
                  "  Copyright:"]
        copyright_ = entry.get("Copyright") or ""
        lines += ["    " + c.strip() for c in (copyright_ if isinstance(copyright_, list) else
                                                copyright_.splitlines()) if c.strip()]
        lines.append("")
    lines += ["", "#" * 100, "THE LICENCE TEXTS", "#" * 100, ""]
    for repo, p in sorted(texts):
        lines += ["=" * 100, f"{repo}/{p}", "=" * 100, _text(repo, tag, p).rstrip("\n"), ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{OUT}: {len(entries)} components, {len(texts)} licence texts (Qt {tag})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/build_qt_notices.py <Qt version, e.g. 6.11.2>")
    build(sys.argv[1])

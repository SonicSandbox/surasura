# SPDX-License-Identifier: GPL-3.0-or-later
"""パターン data packages (Patterns_Spec.md §18): the shared database other users download, and a user's
own databases carried to another computer. One zip format, one installer.

    <name>.zip   patterns_<lang>[_<source>].db …   the databases
                 package.json                      what they are, with each file's sha256
                 CREDITS.txt                       (the shared one: its sources and licence)

**Install is all or nothing, and only ever パターン databases**: each file is extracted beside its
destination and checked against its sha256 before any is put in place, and a package naming anything
else is refused. The destination is this computer's data folder (`path_utils`), where
`patterns_store.open_store` looks.

**The download** (the Anki Backfill window's "Get data…", user-started, never automatic — CLAUDE.md §1)
is a file in the app's own GitHub repository (`release_assets/patterns/`), fetched at the commit that
added it — a commit never changes, so an older app keeps getting the file it was pinned to — and
checked against its sha256: a file that does not match is refused. A new version of the data is a new
commit, a new `SHARED_URL` and a new `SHARED_SHA256` (release_assets/patterns/RELEASE.md).
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile

MANIFEST = "package.json"
# Version 5 (2026-10-01, builder 9): the same sources, rebuilt on 2.4's word rules — compounds one word, words the
# tagger cut at their endings whole, a one-kanji word's lines only where it stands on its own, a spelling the
# dictionary keeps apart a word of its own too, no numbers or symbols (Patterns_Quality_Spec.md, the dated notes).
# Version 4 (builder 7: the sweep's join table, §15.9) stays at 8f126cf, version 3 (builder 6: whole words, document
# counts, no row under the lookup's limits — §15.7) at f996b2c, version 2 (builder 5, + Leipzig's newscrawl) at
# 5bbd226 and version 1 at 539f6c2 for the apps pinned to them.
SHARED_URL = ("https://raw.githubusercontent.com/SonicSandbox/surasura/"
              "c923aa14ff4fabd4adc8cb02349adc8e712fadfc/release_assets/patterns/patterns_ja_shared.zip")
SHARED_SHA256 = "3013f1fe61e9c142f42d00e1300af73b6ab11a24b6804225c477772dd14509bd"
SHARED_MB = 32
SHARED_CREDIT = ("RealPersonaChat, Aozora Bunko, Wikipedia and Leipzig Corpora Collection news "
                 "(CC BY-SA 4.0)")
# Every other language's shared download, {url, sha256, mb, credit} (Patterns_Chinese_Spec.md WP-Z8).
# `shared_for` gives any language's: Japanese's from the names above, read when asked, so its pin lives
# in one place (S10). A language missing here has no shared data. Chinese version 3 (2026-10-01, its
# builder 3): the same sources (Tatoeba, KdConv, Wikipedia, Wikinews and Leipzig news, counted only), rebuilt
# on 2.4's one Chinese cut (`analyzer.chinese_cut`: dictionary words, no guesses; numbers no words; Taiwan's
# standard characters); version 2 (builder 2, rebuilt for 2.3 — Patterns_Quality_Spec.md §10) stays at
# f996b2c and version 1 (builder 1) at d62e646.
SHARED = {"zh": {"url": ("https://raw.githubusercontent.com/SonicSandbox/surasura/"
                         "c923aa14ff4fabd4adc8cb02349adc8e712fadfc/release_assets/patterns/patterns_zh_shared.zip"),
                 "sha256": "bf49ff3992cb8a79c800a782302e97b8495c935f0efdaeba43110e3d29784568",
                 "mb": 10,
                 "credit": "Tatoeba, KdConv, Wikipedia, Wikinews and Leipzig Corpora Collection news (CC BY-SA 4.0)"}}
LANGUAGE_NAMES = {"ja": "Japanese", "zh": "Chinese"}
# A package may only put パターン databases in place: patterns_ja.db, patterns_ja_balanced.db, …
_DB_NAME = re.compile(r"^patterns_([a-z]{2})(?:_[a-z]+)?\.db$")


class PackageError(Exception):
    """A package that cannot be installed; the message says why, in the user's words."""


def shared_for(language):
    """-> `language`'s shared download as {url, sha256, mb, credit}, or None: there is none yet."""
    if language == "ja":
        return {"url": SHARED_URL, "sha256": SHARED_SHA256, "mb": SHARED_MB, "credit": SHARED_CREDIT}
    return SHARED.get(language)


def destination():
    """This computer's data folder — where the パターン databases live."""
    from app.path_utils import get_persistent_user_data_path
    return get_persistent_user_data_path()


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack(paths, out_path, kind="personal", language="ja", extra=None, **info):
    """Zip the databases at `paths` into a package at `out_path` (written aside, then moved into place).
    `extra` = {name in the zip: text} (CREDITS.txt); `info` joins the manifest (licence, …)."""
    files = []
    tmp = out_path + ".part"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in paths:
                name = os.path.basename(path)
                if not _DB_NAME.match(name):
                    raise PackageError(f"{name} is not a パターン database.")
                files.append({"name": name, "sha256": _sha256(path), "bytes": os.path.getsize(path)})
                zf.write(path, name)
            manifest = dict(info, surasura="patterns", kind=kind, language=language, files=files,
                            created=datetime.datetime.now().isoformat(timespec="seconds"))
            zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
            for name, text in (extra or {}).items():
                zf.writestr(name, text)
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out_path


def read_manifest(zip_path):
    """-> the package's manifest, checked; PackageError when it is not a パターン package — or when a
    file's name says another language than the manifest does: one package is one language, so a
    Chinese one can never replace a Japanese database (Patterns_Chinese_Spec.md S10)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            manifest = json.loads(zf.read(MANIFEST).decode("utf-8"))
            names = set(zf.namelist())
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        raise PackageError("That file is not a Surasura パターン package.") from None
    if not isinstance(manifest, dict) or manifest.get("surasura") != "patterns":
        raise PackageError("That file is not a Surasura パターン package.")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise PackageError("That file is not a Surasura パターン package.")
    for entry in files:
        name = entry.get("name") if isinstance(entry, dict) else None
        found = _DB_NAME.match(name) if isinstance(name, str) else None
        if not found or name not in names or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256") or "")):
            raise PackageError("That package is damaged or not a パターン package.")
        if found.group(1) != manifest.get("language"):
            raise PackageError("That package mixes languages, so nothing was installed.")
    return manifest


def install(zip_path, progress=None):
    """Put a package's databases in this computer's data folder. -> the names installed.

    Every file is extracted beside its destination and checked before any replaces what is there —
    a damaged package changes nothing. `progress(done, total)` counts files."""
    manifest = read_manifest(zip_path)
    folder = destination()
    os.makedirs(folder, exist_ok=True)
    staged = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for n, entry in enumerate(manifest["files"], start=1):
                fd, tmp = tempfile.mkstemp(prefix=entry["name"] + ".", suffix=".part", dir=folder)
                staged.append((tmp, os.path.join(folder, entry["name"])))
                digest = hashlib.sha256()
                with os.fdopen(fd, "wb") as out, zf.open(entry["name"]) as src:
                    for chunk in iter(lambda: src.read(1 << 20), b""):
                        out.write(chunk)
                        digest.update(chunk)
                if digest.hexdigest() != entry["sha256"]:
                    raise PackageError(f"{entry['name']} in that package is damaged, so nothing was installed.")
                if progress:
                    progress(n, len(manifest["files"]))
        for tmp, final in staged:
            try:
                os.replace(tmp, final)
            except OSError:
                raise PackageError(f"{os.path.basename(final)} is in use. Close Surasura's other windows "
                                   "and try again.") from None
        return [entry["name"] for entry in manifest["files"]]
    finally:
        for tmp, _final in staged:
            if os.path.exists(tmp):
                os.remove(tmp)


def get_shared(progress=None, language="ja"):
    """Download Surasura's shared パターン data for `language`, check it against the pinned sha256,
    install it. -> the names installed. `progress(done, total)` counts bytes while downloading. A
    language with no shared data, or a package of another language, installs nothing (S10)."""
    from app.updater import download
    shared = shared_for(language)
    if shared is None:
        raise PackageError(f"There is no shared パターン data for {LANGUAGE_NAMES.get(language, language)} yet.")
    folder = tempfile.mkdtemp(prefix="surasura_patterns_")
    path = os.path.join(folder, os.path.basename(shared["url"]))
    try:
        try:
            download(shared["url"], path, progress_cb=progress)
        except OSError as e:                    # URLError, timeouts, a full disk
            raise PackageError(f"Could not download the パターン data ({e}).") from None
        if _sha256(path) != shared["sha256"]:
            raise PackageError("The download did not match Surasura's published file, so nothing was "
                               "installed.")
        if read_manifest(path).get("language") != language:
            raise PackageError("The download is another language's data, so nothing was installed.")
        return install(path)
    finally:
        shutil.rmtree(folder, ignore_errors=True)

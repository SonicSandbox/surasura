"""S3.1 row 3.1.6 — the 2.x -> 3.0 import (`app/import_2x.py`; SPEC D11, D12, D14).

What a wrong answer would cost, in order:
  * the old 2.x folder, or 2.x's own per-user folders, changed in any way — the user's way back to 2.x (CLAUDE.md §4);
  * a library that arrives incomplete without saying so: a file whose copy differs, a cancelled import that looks
    finished;
  * 2.x's content brought over after all (Sonic 2026-10-23: no content migration): `data\\`, the library store, or
    `master_manifest.json` — the library order 3.0's store would rebuild every show and book from;
  * an import over a 3.0 library that already holds the user's content, or a second import on top of the first;
  * the AnkiConnect address a 2.x user set in `junban_url` lost;
  * the Gemini key (Koe) written to a log.

Every root is a temp folder: the test root (conftest) is the new library, the program's own, so 2.x's per-user
folders are `<root>/legacy_local_root` and `<root>/legacy_persistent_root` and the store is `<root>/index`; the
Houseki roaming root is the test root's, `<root>/persistent_root` (%APPDATA% / XDG_DATA_HOME pointed into tmp_path
as well). Content, known words and list words are real Japanese and Chinese from tests/Test Resources/; folder names
carry both scripts, as users' paths do."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

import pytest

from app import import_2x, library_store as ls, path_utils, updater

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WAL_KEY = "import_wal_probe"
SECRET = "AIzaTestSecret-冒険-do-not-log"
JUNBAN = "http://127.0.0.1:8770"

# (tier folder, relative file name, resource) per language: real subtitles and texts
CONTENT = {
    "ja": [("HighPriority", "冒険/library_episode.ass", "ja/library_episode.ass"),
           ("HighPriority", "冒険/phrases_sample.srt", "ja/phrases_sample.srt"),
           ("LowPriority", "tv_captions.ass", "ja/tv_captions.ass"),
           ("GoalContent", "context_test.txt", "ja/context_test.txt")],
    "zh": [("HighPriority", "夜市/night_market.srt", "zh/night_market.srt"),
           ("LowPriority", "chinese_text_1.txt", "zh/chinese_text_1.txt"),
           ("GoalContent", "traditional_news.txt", "zh/traditional_news.txt")],
}
GRADUATED = {"ja": ["冒険", "今夜"], "zh": ["欢迎", "频道"]}
KNOWN_RESOURCE = {"ja": "ja/KnownWord.json", "zh": "zh/KnownWords.json"}


# --- helpers -------------------------------------------------------------------------------------------------------

def _root():
    return os.environ["SURASURA_TEST_ROOT"]


def _tree(folder):
    """Every file under `folder`: {relative path: (sha256, size, mtime_ns)}, and every folder — what "byte-identical,
    dates included" means here."""
    out = {}
    if not os.path.isdir(folder):
        return out
    for dirpath, dirs, files in os.walk(folder):
        for d in dirs:
            out[os.path.relpath(os.path.join(dirpath, d), folder) + os.sep] = None
        for name in files:
            path = os.path.join(dirpath, name)
            st = os.stat(path)
            with open(path, "rb") as f:
                out[os.path.relpath(path, folder)] = (hashlib.sha256(f.read()).hexdigest(), st.st_size,
                                                      st.st_mtime_ns)
    return out


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _write(path, data, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode, **({} if mode == "wb" else {"encoding": "utf-8"})) as f:
        f.write(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _resource(rel):
    with open(os.path.join(RESOURCES, *rel.split("/")), "rb") as f:
        return f.read()


def _known_words(language):
    """A real KnownWord.json, trimmed to 30 of its words (none of them a GraduatedList word)."""
    data = json.loads(_resource(KNOWN_RESOURCE[language]).decode("utf-8"))
    data["words"] = [w for w in data["words"] if w.get("dictForm") not in GRADUATED[language]][:30]
    return json.dumps(data, ensure_ascii=False, indent=2)


def _manifest(language, old):
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    for tier_folder, rel, _res in CONTENT[language]:
        phase = ls.TIERS[ls.TIER_OF_FOLDER[tier_folder]][0]
        path = f"{tier_folder}/{rel}"
        doc["schedule"][phase].append(ls.make_entry(path, "Manual Import", "subtitle" if path.endswith(
            (".srt", ".ass")) else "text"))
    return doc


def _old_install(base, store=True, note=True, settings=True, languages=("ja", "zh"), name="旧すらすら 2.5 旧版"):
    """A 2.x install as 2.5 leaves it: Surasura.exe and `_internal\\` beside the library (User Files\\, data\\,
    results\\, settings.json); per language real content in the tiers, a trash file 10 days old, KnownWord.json, a
    GraduatedList, an IgnoreList and master_manifest.json; in 2.x's local root the install note and (2.5) the library
    store — its `-wal` holding a committed row no checkpoint has written into the `.db` yet; in 2.x's roaming root the
    パターン databases, Koe's files, the telemetry id, a token store and yt-dlp."""
    old = os.path.join(str(base), name)
    _write(os.path.join(old, "Surasura.exe"), b"MZ 2.5 program")
    _write(os.path.join(old, "_internal", "base_library.zip"), b"PK program files")
    _write(os.path.join(old, "results", "reading_list_static.html"), "<html>冒険</html>")
    ten_days_ago = time.time() - 10 * 86400
    for language in languages:
        data, uf = os.path.join(old, "data", language), os.path.join(old, "User Files", language)
        for tier_folder, rel, res in CONTENT[language]:
            _write(os.path.join(data, tier_folder, *rel.split("/")), _resource(res))
        _write(os.path.join(data, "Processed", "snippets", "sample.txt"), _resource(CONTENT[language][-1][2]))
        os.makedirs(os.path.join(data, "Graduated"), exist_ok=True)            # an empty tier folder
        _write(os.path.join(data, ".trash", "removed_" + os.path.basename(CONTENT[language][0][1])),
               _resource(CONTENT[language][0][2]), mtime=ten_days_ago)
        _write(os.path.join(uf, "KnownWord.json"), _known_words(language))
        _write(os.path.join(uf, ".trash", "KnownWord.20260901-101010.json"), _known_words(language),
               mtime=ten_days_ago)
        _write(os.path.join(uf, "GraduatedList.txt"),
               "# Words from graduated content (automatically added)\n\n# Source: HighPriority (2 words graduated)\n"
               + "\n".join(GRADUATED[language]) + "\n")
        _write(os.path.join(uf, "IgnoreList.txt"), "# Add words to ignore here (one per line)\n番\n"
               if language == "ja" else "# Add words to ignore here (one per line)\n你好\n")
        _write(os.path.join(uf, ls.MANIFEST_NAME), json.dumps(_manifest(language, old), ensure_ascii=False,
                                                              indent=2))
        if store:
            _old_store(old, language)
    if settings:
        _write(os.path.join(old, "settings.json"), json.dumps(
            {"language": "ja", "junban_url": JUNBAN, "anki_connect_url": "http://127.0.0.1:8765",
             "junban_deck": "日本語::冒険", "logic": {"exclude_single": True}}, indent=4))
    roaming = path_utils.legacy_persistent_root()
    for fname, data in (("patterns_ja.db", b"SQLite format 3\x00 ja patterns"),
                        ("patterns_zh.db", b"SQLite format 3\x00 zh patterns"),
                        ("koe_credentials.json", json.dumps({"api_key": SECRET})),
                        ("koe_usage.json", json.dumps({"2026-10": 1234})),
                        ("telemetry_id.json", json.dumps({"uid": "2x-user-uid", "open_count": 77})),
                        ("token_store_ja.db", b"SQLite format 3\x00 cache"),
                        (os.path.join("bin", "yt-dlp.exe"), b"MZ yt-dlp")):
        if not os.path.exists(os.path.join(roaming, fname)):
            _write(os.path.join(roaming, fname), data)
    if note:
        notes = os.path.join(path_utils.legacy_local_root(), path_utils.INSTALLS_NOTE)
        entries = path_utils.read_install_note(notes)
        entries.append({"data_root": old, "exe": os.path.join(old, "Surasura.exe"), "version": "2.5.0",
                        "languages": list(languages), "last_run": "2026-10-05T21:00:00"})
        _write(notes, json.dumps(entries, ensure_ascii=False, indent=2))
    return old


def _old_store(old, language):
    """2.5's store for `language`, built by the store itself, then placed in 2.x's local root as a SET whose `-wal`
    holds one committed row (WAL_KEY) the `.db` doesn't have yet — as a 2.5 that was closed hard leaves it."""
    data, uf = os.path.join(old, "data", language), os.path.join(old, "User Files", language)
    assert ls.maintain(language, data, uf) == ls.EXIT_DONE
    built = ls.library_db_path(language, data)
    legacy = os.path.join(path_utils.legacy_local_root(), "libraries", os.path.basename(built))   # where 2.5 has it
    conn = sqlite3.connect(built, isolation_level=None)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (WAL_KEY, f"{language} 冒険 pending"))
        os.makedirs(os.path.dirname(legacy), exist_ok=True)
        for suffix in import_2x.STORE_SUFFIXES:
            shutil.copyfile(built + suffix, legacy + suffix)
    finally:
        conn.close()            # the built set (under the old folder's key in <root>/index) is left: never imported
    assert os.path.getsize(legacy + "-wal") > 0


def _meta(db, key):
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _protected():
    """The folders an import may only read: the old install's (added by the test), 2.x's local and roaming roots."""
    return [path_utils.legacy_local_root(), path_utils.legacy_persistent_root()]


@pytest.fixture
def roaming(tmp_path, monkeypatch):
    """The Houseki roaming root: the test root's, <root>/persistent_root (path_utils.get_persistent_user_data_path);
    %APPDATA% / XDG_DATA_HOME pointed into tmp_path as well, so nothing could reach the real one."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "Roaming"))
    return os.path.join(_root(), "persistent_root")


# --- the whole import ----------------------------------------------------------------------------------------------

def test_a_2_5_install_arrives_whole_and_the_old_folders_stay_byte_identical(tmp_path, roaming, capsys):
    old = _old_install(tmp_path)
    library = _root()
    before = {f: _tree(f) for f in [old] + _protected()}
    stages = []

    result = import_2x.run_import(old, library, progress=lambda stage, done, total: stages.append(stage))

    assert result["status"] == "done", result
    assert {f: _tree(f) for f in [old] + _protected()} == before, "the old folders were written"
    # Every byte of User Files\ with its date (the trash clock), but the library order
    olds = {k: v for k, v in _tree(old).items() if k.split(os.sep)[0] == "User Files"
            and not os.path.basename(k.rstrip(os.sep)).startswith("master_manifest")}
    news = _tree(library)
    merged = {os.path.join("User Files", lang, n) for lang in ("ja", "zh") for n in ("KnownWord.json",
                                                                                      "GraduatedList.txt")}
    for rel, value in olds.items():
        if rel in merged:
            continue
        assert news.get(rel) == value, rel
    assert result["counts"]["files"] == result["counts"]["copied"] == len([v for v in olds.values() if v])
    assert result["counts"]["bytes"] == sum(v[1] for v in olds.values() if v)
    assert not os.path.exists(os.path.join(library, "data")), "no content: shows and books come in again"
    assert not [rel for rel in news if "master_manifest" in rel], "no library order: the store would rebuild from it"
    assert not os.path.exists(os.path.join(library, "results")), "results\\ is regenerated, never copied"

    # GraduatedList merged once into the known words; the list itself set aside, byte for byte
    for lang in ("ja", "zh"):
        uf = os.path.join(library, "User Files", lang)
        assert not os.path.exists(os.path.join(uf, "GraduatedList.txt"))
        trash = os.path.join(uf, ".trash")
        retired = [n for n in os.listdir(trash) if n.startswith("GraduatedList.")]
        assert len(retired) == 1 and _sha(os.path.join(trash, retired[0])) == olds[
            os.path.join("User Files", lang, "GraduatedList.txt")][0]
        with open(os.path.join(uf, "KnownWord.json"), encoding="utf-8") as f:
            words = {w["dictForm"]: w for w in json.load(f)["words"]}
        for word in GRADUATED[lang]:
            assert words[word]["knownStatus"] == "KNOWN" and words[word]["source"] == "GraduatedList"
        assert result["graduated"][lang]["added"] == len(GRADUATED[lang])

    # settings.json: junban_url became the one address
    with open(path_utils.get_settings_path(), encoding="utf-8") as f:
        settings = json.load(f)
    assert settings["anki_connect_url"] == JUNBAN and "junban_url" not in settings
    assert settings["junban_deck"] == "日本語::冒険" and settings["logic"] == {"exclude_single": True}
    assert result["settings"] == "converted"

    # the store: nothing under the new library's name, nor a staging folder
    for lang in ("ja", "zh"):
        assert not os.path.exists(ls.library_db_path(lang, os.path.join(library, "data", lang)))
    assert "store" not in result
    assert not os.path.exists(os.path.join(path_utils.local_data_root(), "import_staging"))

    # roaming: パターン, Koe, the telemetry id over; the token store and yt-dlp left behind
    legacy = path_utils.legacy_persistent_root()
    for name in ("patterns_ja.db", "patterns_zh.db", "koe_credentials.json", "koe_usage.json", "telemetry_id.json"):
        assert _sha(os.path.join(roaming, name)) == _sha(os.path.join(legacy, name)), name
        assert result["roaming"][name] == "copied"
    assert not os.path.exists(os.path.join(roaming, "token_store_ja.db"))
    assert not os.path.exists(os.path.join(roaming, "bin"))

    # import.json: complete, from, counts and the sha256 summary; the secret nowhere
    note = import_2x.read_import_note()
    assert note["complete"] is True and note["from"] == old and note["to"] == library
    assert note["from_version"] == "2.5.0" and note["counts"]["files"] == result["counts"]["files"]
    assert note["sha256"] == result["sha256"] and note["sha256"]["files"] == result["counts"]["files"]
    with open(import_2x.note_path(), encoding="utf-8") as f:
        assert SECRET not in f.read()
    assert SECRET not in capsys.readouterr().out
    assert stages[0] == "files" and stages[-1] == "graduated" and "store" not in stages


def test_the_sha256_summary_names_every_file_and_its_hash(tmp_path, roaming):
    """The summary is the sha256 of `<path>\\t<sha256>` lines, in copy order: support can recompute it from the old
    folder alone."""
    old = _old_install(tmp_path, store=False, languages=("zh",))
    result = import_2x.run_import(old, _root())
    files, _folders = import_2x._plan_files(old)
    digest = hashlib.sha256()
    for rel, _size in files:
        digest.update(f"{rel.replace(os.sep, '/')}\t{_sha(os.path.join(old, rel))}\n".encode("utf-8"))
    assert result["sha256"] == {"files": len(files), "summary": digest.hexdigest()}


# --- finding the install ---------------------------------------------------------------------------------------------

def test_find_installs_reads_2_5s_note_newest_first_one_per_folder(tmp_path):
    a = _old_install(tmp_path / "a", store=False, name="Surasura 2.4")
    b = _old_install(tmp_path / "b", store=False, name="すらすら")
    gone = str(tmp_path / "removed install")
    notes = os.path.join(path_utils.legacy_local_root(), path_utils.INSTALLS_NOTE)
    _write(notes, json.dumps([
        {"data_root": a.upper() if os.name == "nt" else a, "version": "2.4.1", "last_run": "2026-09-20T10:00:00"},
        {"data_root": b, "version": "2.5.0", "last_run": "2026-10-05T21:00:00"},
        {"data_root": a, "version": "2.4.0", "last_run": "2026-09-01T10:00:00"},
        {"data_root": gone, "version": "2.5.0", "last_run": "2026-10-09T10:00:00"},
        "not an entry", {"version": "no folder"}], ensure_ascii=False))
    found = import_2x.find_installs()
    assert [e["version"] for e in found] == ["2.5.0", "2.4.1"]
    assert path_utils.local_data_root() not in notes, "2.x's note, never 3.0's own"


def test_no_note_finds_nothing_so_the_window_asks(tmp_path):
    _old_install(tmp_path, store=False, note=False)
    assert import_2x.find_installs() == []


# --- the guards --------------------------------------------------------------------------------------------------------

def test_a_running_old_program_is_refused(tmp_path, roaming, monkeypatch):
    old = _old_install(tmp_path, store=False)
    _write(os.path.join(old, "data", "ja", "Processed", "setup.exe"), b"MZ a user's file")   # the library: never listed
    asked = []

    def fake(images):
        asked.append(images)
        return {4242: os.path.join(old, "Surasura.exe")}

    monkeypatch.setattr(updater, "_processes_running", fake)
    before = _tree(_root())
    result = import_2x.run_import(old, _root())
    assert result["status"] == "refused" and result["reason"] == "running"
    assert result["running"] == [{"pid": 4242, "image": os.path.join(old, "Surasura.exe")}]
    assert os.path.join(old, "Surasura.exe") in asked[0]
    assert not any(os.sep + "data" + os.sep in i for i in asked[0])
    assert _tree(_root()) == before and import_2x.read_import_note() is None


@pytest.mark.skipif(sys.platform != "win32", reason="the process listing is Windows-only")
def test_a_real_process_running_from_the_old_folder_is_found(tmp_path):
    """The updater's own listing, by import: a copy of ping.exe running from the old folder holds it."""
    old = _old_install(tmp_path, store=False)
    ping = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE")
    if not os.path.isfile(ping):
        pytest.skip("no ping.exe")
    exe = os.path.join(old, "holder.exe")
    shutil.copyfile(ping, exe)
    proc = subprocess.Popen([exe, "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.3)
        check = import_2x.check_source(old)
        assert not check["ok"] and check["reason"] == "running"
        assert [r["pid"] for r in check["running"]] == [proc.pid]
    finally:
        proc.kill()
        proc.wait()
    assert import_2x.check_source(old)["ok"]


def test_a_library_holding_content_is_refused_and_a_fresh_starts_files_are_not_content(tmp_path, roaming):
    old = _old_install(tmp_path, store=False)
    library = str(tmp_path / "新しい図書館")
    # what a new 3.0 library's first start writes: folders, comment-only lists, a bundled default list
    for lang in ("ja", "zh"):
        os.makedirs(os.path.join(library, "data", lang, "HighPriority"))
        _write(os.path.join(library, "User Files", lang, "IgnoreList.txt"), "# Add words to ignore here\n")
        _write(os.path.join(library, "User Files", lang, "Blacklist.txt"), f"# {lang} Blacklist\n")
    _write(os.path.join(_root(), "defaults", "ja", "frequency_list_ja_global50k.csv"), "番,1\n")
    _write(os.path.join(library, "User Files", "ja", "frequency_list_ja_global50k.csv"), "番,1\n")
    assert import_2x.library_content(library) is None

    _write(os.path.join(library, "User Files", "ja", "IgnoreList.txt"), "# mine\n冒険\n")
    assert import_2x.library_content(library).endswith("IgnoreList.txt")
    os.remove(os.path.join(library, "User Files", "ja", "IgnoreList.txt"))
    episode = _write(os.path.join(library, "data", "zh", "HighPriority", "夜市.srt"), _resource("zh/night_market.srt"))
    before = _tree(library)
    result = import_2x.run_import(old, library)
    assert result["status"] == "refused" and result["reason"] == "not_empty" and result["found"] == episode
    assert _tree(library) == before and import_2x.read_import_note() is None


def test_a_users_list_named_like_a_bundled_default_is_content_and_is_never_copied_over(tmp_path, roaming):
    # Only the bundled default itself, byte for byte, is left out: a user's own IgnoreList in an existing 3.0 library
    # (named like the bundled one) makes it a library, so the import refuses it instead of copying 2.x's list over it.
    old = _old_install(tmp_path, store=False, languages=("ja",))
    library = str(tmp_path / "新しい図書館")
    _write(os.path.join(_root(), "defaults", "ja", "IgnoreList.txt"), "# 無視する単語\nです\n")
    _write(os.path.join(library, "User Files", "ja", "IgnoreList.txt"), "# 無視する単語\nです\n")
    assert import_2x.library_content(library) is None, "the bundled default as installed"
    mine = _write(os.path.join(library, "User Files", "ja", "IgnoreList.txt"), "# 無視する単語\nです\n冒険\n")
    assert import_2x.library_content(library) == mine
    before = _tree(library)
    result = import_2x.run_import(old, library)
    assert result["status"] == "refused" and result["reason"] == "not_empty" and result["found"] == mine
    assert _tree(library) == before


def test_an_old_program_started_during_the_import_stops_it_before_it_is_marked_done(tmp_path, roaming, monkeypatch):
    # The running check before the copy can't see a 2.x started meanwhile, whose store may move under the copy: it is
    # asked again once the stores are copied, and the import stops unfinished (run again once 2.x is closed).
    old = _old_install(tmp_path, languages=("ja",))
    looks = []

    def fake(images):
        looks.append(1)
        return {} if len(looks) == 1 else {4242: os.path.join(old, "Surasura.exe")}

    monkeypatch.setattr(updater, "_processes_running", fake)
    result = import_2x.run_import(old, _root())
    assert result["status"] == "failed" and "started during the import" in result["message"]
    assert len(looks) == 2 and import_2x.read_import_note()["complete"] is False


def test_the_record_keeps_the_graduated_lists_outcome(tmp_path, roaming):
    # A merge that failed for a language leaves the list where it is; the record says so for the window to show.
    old = _old_install(tmp_path, store=False, languages=("ja",))
    result = import_2x.run_import(old, _root())
    assert result["status"] == "done"
    assert import_2x.read_import_note()["graduated"] == result["graduated"]


def test_an_old_folder_that_cant_be_read_is_refused_before_anything_is_written(tmp_path, roaming, monkeypatch):
    # A file of the old folder that can't be read as the import plans its copy (held, or its permissions changed): the
    # import says so and stops before its record or any copy, instead of raising out of the window's thread.
    old = _old_install(tmp_path, store=False, languages=("ja",))
    before = {f: _tree(f) for f in [old] + _protected()}
    real = os.path.getsize

    def denied(path):
        if os.path.basename(path) == "IgnoreList.txt":
            raise PermissionError(13, "Access is denied", path)
        return real(path)

    monkeypatch.setattr(os.path, "getsize", denied)
    result = import_2x.run_import(old, _root())
    assert result["status"] == "refused" and result["reason"] == "error"
    assert "could not be read" in result["message"] and "IgnoreList.txt" in result["message"]
    assert import_2x.read_import_note() is None and import_2x.library_content(_root()) is None
    assert {f: _tree(f) for f in [old] + _protected()} == before


def test_a_record_that_cant_be_started_refuses_the_import_before_any_copy(tmp_path, roaming, monkeypatch):
    # import.json can't be written as the import starts (a full disk): without it a copy cut off later would never read
    # as unfinished, so nothing is copied and the import says why, instead of raising.
    old = _old_install(tmp_path, store=False, languages=("ja",))
    before = {f: _tree(f) for f in [old] + _protected()}

    def full(path, data):
        raise OSError(28, "No space left on device", path)

    monkeypatch.setattr(import_2x, "_write_json", full)
    result = import_2x.run_import(old, _root())
    assert result["status"] == "refused" and result["reason"] == "error" and "could not start" in result["message"]
    assert import_2x.read_import_note() is None and import_2x.library_content(_root()) is None, "nothing copied"
    assert {f: _tree(f) for f in [old] + _protected()} == before


def test_a_record_that_cant_be_closed_leaves_the_import_unfinished_and_the_next_run_finishes_it(tmp_path, roaming,
                                                                                                monkeypatch):
    # Every file copied, but the closing record can't be written (the disk filled): the import reports failed, never
    # done and never an exception; the record still reads unfinished from its start, so the next run resumes and ends
    # it, as the message says.
    old = _old_install(tmp_path, store=False, languages=("ja",))
    real = import_2x._write_json

    def full_at_the_end(path, data):
        if data.get("finished"):
            raise OSError(28, "No space left on device", path)
        return real(path, data)

    monkeypatch.setattr(import_2x, "_write_json", full_at_the_end)
    result = import_2x.run_import(old, _root())
    assert result["status"] == "failed" and result["reason"] == "failed"
    assert "record could not be written" in result["message"] and "run the import again" in result["message"]
    note = import_2x.read_import_note()
    assert note["complete"] is False and note["finished"] is None
    monkeypatch.setattr(import_2x, "_write_json", real)
    again = import_2x.run_import(old, _root())
    assert again["status"] == "done" and again["resumed"] is True
    assert import_2x.read_import_note()["complete"] is True
    # the first run's GraduatedList merge is not lost: the resume copies the old list and known words again (they
    # changed) and merges them again
    with open(os.path.join(_root(), "User Files", "ja", "KnownWord.json"), encoding="utf-8") as f:
        words = {w["dictForm"]: w for w in json.load(f)["words"]}
    for word in GRADUATED["ja"]:
        assert words[word]["knownStatus"] == "KNOWN" and words[word]["source"] == "GraduatedList"


def test_a_second_run_after_a_complete_import_is_refused(tmp_path, roaming):
    old = _old_install(tmp_path, store=False)
    assert import_2x.run_import(old, _root())["status"] == "done"
    after = _tree(_root())
    again = import_2x.run_import(old, _root())
    assert again["status"] == "refused" and again["reason"] == "already_imported"
    assert again["previous"]["complete"] is True
    # asked again: still never over the library it made
    forced = import_2x.run_import(old, _root(), again=True)
    assert forced["status"] == "refused" and forced["reason"] == "not_empty"
    assert _tree(_root()) == after


def test_cancel_midway_marks_the_library_incomplete_and_the_next_run_resumes(tmp_path, roaming):
    old = _old_install(tmp_path)
    before = {f: _tree(f) for f in [old] + _protected()}
    done = []
    result = import_2x.run_import(old, _root(), progress=lambda s, d, t: done.append(d) if s == "files" else None,
                                  cancel=lambda: len(done) >= 3)
    assert result["status"] == "cancelled" and result["counts"]["copied"] == 3
    note = import_2x.read_import_note()
    assert note["complete"] is False and note["status"] == "cancelled" and note["to"] == _root()
    assert not os.path.exists(path_utils.get_settings_path()), "nothing after the cancel"
    assert {f: _tree(f) for f in [old] + _protected()} == before

    # the folder now holds content, but it is this install's unfinished import: resumed, the copied files kept
    resumed = import_2x.run_import(old, _root())
    assert resumed["status"] == "done" and resumed["resumed"] is True
    assert resumed["counts"]["kept"] == 3 and resumed["counts"]["copied"] == resumed["counts"]["files"] - 3
    assert import_2x.read_import_note()["complete"] is True
    assert {f: _tree(f) for f in [old] + _protected()} == before


def test_a_restarted_import_copies_every_file_again(tmp_path, roaming):
    old = _old_install(tmp_path, store=False, languages=("zh",))
    done = []
    import_2x.run_import(old, _root(), progress=lambda s, d, t: done.append(d), cancel=lambda: len(done) >= 2)
    restarted = import_2x.run_import(old, _root(), restart=True)
    assert restarted["status"] == "done" and restarted["counts"]["kept"] == 0
    assert restarted["counts"]["copied"] == restarted["counts"]["files"]


def test_an_unfinished_import_from_another_install_is_refused(tmp_path, roaming):
    first = _old_install(tmp_path / "1", store=False, languages=("ja",))
    second = _old_install(tmp_path / "2", store=False, languages=("zh",), name="Surasura 2.4 夜市")
    done = []
    import_2x.run_import(first, _root(), progress=lambda s, d, t: done.append(d), cancel=lambda: len(done) >= 1)
    result = import_2x.run_import(second, _root())
    assert result["status"] == "refused" and result["reason"] == "other_import"


def test_a_library_inside_the_old_folder_is_refused(tmp_path, roaming):
    old = _old_install(tmp_path, store=False)
    for library in (os.path.join(old, "3.0 library"), old):
        result = import_2x.run_import(old, library)
        assert result["status"] == "refused" and result["reason"] == "same_folder"
    assert not os.path.exists(os.path.join(old, "3.0 library"))
    assert import_2x.run_import(old, old + " 3.0")["status"] == "done", "a folder beside it with a longer name is not in it"


def test_a_library_holding_a_program_is_refused_and_left_untouched(tmp_path, roaming):
    """IK-1: a folder holding a Surasura program — a 2.x unzipped into Documents\\Surasura, or a 3.0 install — is never
    a library: 3.0 would work on that copy in place, and an update or an uninstall replaces it. Either mark alone
    (Surasura.exe, `_internal`) is a program; the refusal names the fallback folder (the seam: one constant)."""
    old = _old_install(tmp_path, store=False)
    install = tmp_path / "Programs" / "すらすら 3.0"                     # a 3.0 program folder: no library in it
    _write(str(install / "Surasura.exe"), b"MZ 3.0 program")
    _write(str(install / "_internal" / "base_library.zip"), b"PK program files")
    before = _tree(str(install))
    result = import_2x.run_import(old, str(install))
    assert result["status"] == "refused" and result["reason"] == "holds_program"
    assert f"Documents\\{import_2x.LIBRARY_FALLBACK}" in result["message"]
    assert _tree(str(install)) == before, "nothing written into the program folder"
    for mark, make in (("Surasura.exe", lambda p: _write(str(p / "Surasura.exe"), b"MZ")),
                       ("_internal", lambda p: os.makedirs(p / "_internal"))):
        folder = tmp_path / f"一つだけ {mark}"
        folder.mkdir()
        make(folder)
        assert import_2x.holds_program(str(folder)), mark
        assert import_2x.run_import(old, str(folder))["reason"] == "holds_program", mark
    library = tmp_path / "空の図書館"
    library.mkdir()
    (library / "User Files").mkdir()
    assert not import_2x.holds_program(str(library)) and not import_2x.holds_program(str(tmp_path / "missing"))


def test_a_folder_without_a_library_is_refused(tmp_path):
    empty = str(tmp_path / "空")
    os.makedirs(empty)
    assert import_2x.check_source(empty)["reason"] == "not_2x"
    assert import_2x.check_source(str(tmp_path / "missing"))["reason"] == "missing"
    assert import_2x.run_import(empty, _root())["reason"] == "not_2x"


def test_a_copy_that_does_not_match_its_source_stops_the_import(tmp_path, roaming, monkeypatch):
    old = _old_install(tmp_path, store=False, languages=("ja",))
    real = shutil.copy2

    def damaged(src, dst, **kw):
        real(src, dst, **kw)
        if src.endswith("IgnoreList.txt"):
            with open(dst, "ab") as f:
                f.write(b"\x00")

    monkeypatch.setattr(shutil, "copy2", damaged)
    result = import_2x.run_import(old, _root())
    assert result["status"] == "failed" and "IgnoreList.txt" in result["message"]
    assert import_2x.read_import_note()["complete"] is False
    target = os.path.join(_root(), "User Files", "ja", "IgnoreList.txt")
    assert not os.path.exists(target) and not os.path.exists(target + import_2x.TMP_SUFFIX)


# --- Controlled Folder Access (D12) ------------------------------------------------------------------------------------

def test_a_writable_folder_is_made_and_left_clean(tmp_path):
    folder = str(tmp_path / "ドキュメント" / "Surasura")
    probe = import_2x.probe_library(folder)
    assert probe["ok"] and probe["created"] and os.listdir(folder) == []


def test_access_denied_names_controlled_folder_access_and_the_steps(tmp_path, roaming, monkeypatch):
    def denied(path):
        raise PermissionError(13, "Access is denied", path)

    monkeypatch.setattr(import_2x, "_write_probe", denied)
    folder = str(tmp_path / "ドキュメント" / "Surasura")
    probe = import_2x.probe_library(folder)
    assert not probe["ok"] and probe["reason"] == "access_denied"
    for words in ("Controlled folder access", "Windows Security", "Virus & threat protection",
                  "Ransomware protection", "Allow an app through Controlled folder access", "Surasura.exe",
                  "restart Surasura"):
        assert words in probe["message"], words
    assert not os.path.exists(str(tmp_path / "ドキュメント")), "the folders the probe made are removed"

    old = _old_install(tmp_path / "old", store=False)
    result = import_2x.run_import(old, folder)
    assert result["status"] == "refused" and result["reason"] == "access_denied"
    assert import_2x.read_import_note() is None


def test_another_write_error_is_not_called_controlled_folder_access(tmp_path, monkeypatch):
    def full(path):
        raise OSError(28, "No space left on device", path)

    monkeypatch.setattr(import_2x, "_write_probe", full)
    probe = import_2x.probe_library(str(tmp_path / "lib"))
    assert probe["reason"] == "error" and "Controlled" not in probe["message"]


# --- 2.4, the store, settings and roaming files -----------------------------------------------------------------------

def test_a_2_4_install_with_no_note_brings_its_lists_to_a_library_chosen_by_hand(tmp_path, roaming):
    old = _old_install(tmp_path, store=False, note=False, name="Surasura 2.4.0")
    assert import_2x.find_installs() == []
    library = str(tmp_path / "図書館 2.4")                     # not this program's library: chosen by hand
    result = import_2x.run_import(old, library)
    assert result["status"] == "done" and result["from_version"] is None
    for lang in ("ja", "zh"):
        assert os.path.isfile(os.path.join(library, "User Files", lang, "KnownWord.json"))
    assert not os.path.exists(os.path.join(library, "data"))
    # another library than this program's: settings beside it, the merge at that library's first start
    assert os.path.isfile(os.path.join(library, "settings.json"))
    assert not os.path.exists(path_utils.get_settings_path())
    assert result["graduated"] == "at the library's first start"
    assert os.path.isfile(os.path.join(library, "User Files", "ja", "GraduatedList.txt"))


def _store_items(language, library):
    """The 3.0 store's own first start on `library` (`maintain --from-folders`, as the window's helper runs it: the
    library order when there is one, else the library's folders) -> its item count."""
    data, uf = os.path.join(library, "data", language), os.path.join(library, "User Files", language)
    os.makedirs(data, exist_ok=True)                   # the library's first start makes its folders
    assert ls.maintain(language, data, uf, from_folders=True) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    db = ls.library_db_path(language, data)
    if not os.path.exists(db):
        return 0
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        conn.close()


def test_no_content_comes_over_so_the_new_store_starts_empty_even_from_2_5s_store_and_order(tmp_path, roaming):
    """Sonic 2026-10-23: no 2.x content migration. A 2.5 install with its store (a committed row in its `-wal`), its
    library order and the order's backups in `.trash` brings none of them, and the 3.0 store's own first start on the
    library finds nothing to rebuild. The control: the same library order alone, put where 2.x kept it, would bring
    every show back (the back door this closes)."""
    old = _old_install(tmp_path, languages=("ja",))
    uf_old = os.path.join(old, "User Files", "ja")
    _write(os.path.join(uf_old, ".trash", "master_manifest.20260901-101010.json"),
           json.dumps(_manifest("ja", old), ensure_ascii=False), mtime=time.time() - 86400)
    _write(os.path.join(uf_old, "master_manifest.json.bak"), json.dumps(_manifest("ja", old), ensure_ascii=False))
    _write(os.path.join(uf_old, "Master_Manifest-PC.JSON"), json.dumps(_manifest("ja", old), ensure_ascii=False))
    library = str(tmp_path / "図書館 3.0")
    result = import_2x.run_import(old, library)
    assert result["status"] == "done" and "store" not in result
    copied = {rel for rel in _tree(library) if not rel.endswith(os.sep)}
    assert not [rel for rel in copied if "master_manifest" in rel.lower()]   # a sync client's copy, any case
    assert not [rel for rel in copied if rel.split(os.sep)[0] != "User Files" and rel != "settings.json"], copied
    assert os.path.isfile(os.path.join(library, "User Files", "ja", ".trash", "KnownWord.20260901-101010.json"))
    assert _store_items("ja", library) == 0, "the new store found 2.x's content"

    control = str(tmp_path / "control")
    os.makedirs(os.path.join(control, "User Files", "ja"))
    shutil.copyfile(os.path.join(uf_old, ls.MANIFEST_NAME), os.path.join(control, "User Files", "ja",
                                                                          ls.MANIFEST_NAME))
    assert _store_items("ja", control) > 0, "the control: the library order alone brings the shows back"


def test_settings_conversion_follows_anki_connects_address():
    cases = [({"junban_url": JUNBAN}, JUNBAN),
             ({"junban_url": JUNBAN, "anki_connect_url": "http://127.0.0.1:8765"}, JUNBAN),
             ({"junban_url": JUNBAN, "anki_connect_url": "http://localhost:9000"}, "http://localhost:9000"),
             ({"junban_url": "http://127.0.0.1:8765"}, "http://127.0.0.1:8765")]
    for settings, address in cases:
        assert import_2x.convert_settings(settings) and settings == {"anki_connect_url": address}
    plain = {"anki_connect_url": "http://localhost:9000", "language": "zh"}
    assert import_2x.convert_settings(plain) == [] and plain == {"anki_connect_url": "http://localhost:9000",
                                                                  "language": "zh"}


def test_settings_without_junban_url_are_copied_byte_for_byte_and_a_3_0_file_is_backed_up(tmp_path, roaming):
    old = _old_install(tmp_path, store=False, languages=("zh",), settings=False)
    raw = '{\n  "language": "zh",\n  "zh_script": "traditional"\n}\n'
    _write(os.path.join(old, "settings.json"), raw)
    _write(path_utils.get_settings_path(), '{"language": "ja"}')
    result = import_2x.run_import(old, _root())
    assert result["settings"] == "copied"
    assert _sha(path_utils.get_settings_path()) == _sha(os.path.join(old, "settings.json"))
    trash = os.path.join(os.path.dirname(path_utils.get_settings_path()), ".trash")
    assert any(n.startswith("settings.") for n in os.listdir(trash))


def test_3_0s_own_roaming_files_are_kept_but_the_telemetry_id_is_carried_over(tmp_path, roaming):
    old = _old_install(tmp_path, store=False, languages=("ja",))
    _write(os.path.join(roaming, "patterns_ja.db"), b"SQLite format 3\x00 3.0's own download")
    _write(os.path.join(roaming, "telemetry_id.json"), json.dumps({"uid": "fresh-3.0", "open_count": 1}))
    result = import_2x.run_import(old, _root())
    assert result["roaming"]["patterns_ja.db"] == "kept" and result["roaming"]["telemetry_id.json"] == "copied"
    with open(os.path.join(roaming, "telemetry_id.json"), encoding="utf-8") as f:
        assert json.load(f)["uid"] == "2x-user-uid"
    with open(os.path.join(roaming, "patterns_ja.db"), "rb") as f:
        assert f.read().endswith(b"3.0's own download")


# --- dry run and the command line -------------------------------------------------------------------------------------

def test_a_dry_run_plans_and_writes_nothing(tmp_path, roaming):
    old = _old_install(tmp_path)
    library = str(tmp_path / "plan only")
    before = _tree(_root())
    result = import_2x.run_import(old, library, dry_run=True)
    assert result["status"] == "dry-run" and "store" not in result
    assert result["counts"]["files"] == len(import_2x._plan_files(old)[0])
    assert all(rel.split(os.sep)[0] == "User Files" and "master_manifest" not in rel
               for rel, _size in import_2x._plan_files(old)[0])
    assert result["settings"] == "convert" and "koe_credentials.json" in result["roaming"]
    assert "token_store_ja.db" not in result["roaming"]
    assert not os.path.exists(library) and _tree(_root()) == before and not os.path.exists(roaming)


def test_the_command_line_runs_a_dry_run(tmp_path, roaming):
    old = _old_install(tmp_path, store=False)
    library = str(tmp_path / "cli 図書館")
    out = subprocess.run([sys.executable, "-m", "app.import_2x", "--from", old, "--to", library, "--dry-run"],
                         cwd=PROJECT, capture_output=True, timeout=120, env=dict(os.environ, PYTHONUTF8="1"))
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    result = json.loads(out.stdout.decode("utf-8"))
    assert result["status"] == "dry-run" and result["to"] == library and not os.path.exists(library)
    assert SECRET not in out.stdout.decode("utf-8")
    refused = subprocess.run([sys.executable, "-m", "app.import_2x", "--from", str(tmp_path / "nowhere"),
                              "--to", library], cwd=PROJECT, capture_output=True, timeout=120,
                             env=dict(os.environ, PYTHONUTF8="1"))
    assert refused.returncode == 1 and json.loads(refused.stdout.decode("utf-8"))["reason"] == "missing"


def test_a_resumed_import_copies_again_a_file_that_differs_from_its_source(tmp_path, roaming):
    """Resuming keeps only copies whose sha256 matches the source: one changed since (or damaged) is copied again."""
    old = _old_install(tmp_path, store=False, languages=("zh",))
    done = []
    import_2x.run_import(old, _root(), progress=lambda s, d, t: done.append(d), cancel=lambda: len(done) >= 2)
    files, _folders = import_2x._plan_files(old)
    second = os.path.join(_root(), files[1][0])          # IgnoreList.txt: the merge never touches it
    with open(second, "ab") as f:
        f.write("夜市".encode("utf-8"))
    resumed = import_2x.run_import(old, _root())
    assert resumed["status"] == "done" and resumed["counts"]["kept"] == 1
    assert _sha(second) == _sha(os.path.join(old, files[1][0]))


def test_a_crash_midway_leaves_the_library_marked_incomplete(tmp_path, roaming):
    """import.json says `complete: false` from before the first file: a program killed mid-copy never looks done."""
    old = _old_install(tmp_path, store=False, languages=("ja",))

    def crash(stage, done, total):
        raise RuntimeError("power cut")

    with pytest.raises(RuntimeError):
        import_2x.run_import(old, _root(), progress=crash)
    note = import_2x.read_import_note()
    assert note["complete"] is False and note["from"] == old and note["finished"] is None

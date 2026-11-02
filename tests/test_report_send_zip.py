"""Both zips through the scrub (`app/report.py` `_write`; Send report SR-1, `tracks/ship/work/send-report/SPEC.md` §2.3,
§2.5, §8): real reports saved by `report.save`, logs written by the app's own writers (a traceback through the home
folder, the command line's events written `ensure_ascii`, the window lock's name), settings, the Anki sync's state,
Connect's record, Anki Miner's results and the last lists — every one naming a made-up person (`tests/scrub_probe.py`).

What a wrong answer would cost: one entry type the scrub skips sends that person's name, home folder or PC to Sonic's
storage under a line that says it doesn't; a zip whose MANIFEST no longer matches its bytes is refused by `open_report`;
a sent report that never leaves the list goes again and again; a scrub that eats deck names, titles and subtitle lines
leaves Sonic nothing to read. Checked both ways, in every form (raw, JSON-escaped, percent-encoded, UTF-16LE).
"""
import codecs
import hashlib
import importlib.util
import json
import os
import struct
import traceback
import zipfile
import zlib

import pytest

from app import path_utils, report, scrub
from tests import scrub_probe as probe_person

DECKS = ["日本語::Kaishi 1.5k", "日本語::Mining"]
TITLE = "進撃の巨人"
LINE_JA = "文化祭まで、あと三日しかないよ。"                 # tests/Test Resources/ja/placed_episode.srt
LINE_ZH = "今天我们要去台北的夜市吃东西。"                   # tests/Test Resources/zh/night_market.srt
WHAT = "「進撃の巨人」の第3話を終わったに入れたら、Ankiの並びが変わらなかった。ztanprobe より (zoe.probe@example.co.jp)"


def _png():
    """A small whole PNG, as Qt's grab().save() writes one (no text chunks)."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")) + chunk(b"IEND", b""))


PNG = _png()


@pytest.fixture(autouse=True)
def _fresh_identity():
    scrub.reset()
    yield
    scrub.reset()


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """The probe person's PC with everything a report reads, each piece naming them."""
    p = probe_person.make(tmp_path, monkeypatch)
    home = p.home
    video = os.path.join(home, "Videos", TITLE, "第3話.mkv")
    logs = os.path.join(path_utils.get_local_data_path(), "logs")
    # a real traceback through a module in the home folder, by the app log's own writer
    tool = os.path.join(home, "scripts", "probe_tool.py")
    _write(tool, b"def run(path):\n    raise FileNotFoundError(path)\n")
    spec = importlib.util.spec_from_file_location("probe_tool", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(video)
    except FileNotFoundError:
        path_utils.write_app_log(traceback.format_exc())
    # the window lock's name, as the single-instance log line writes it (its `_` form of the user's name)
    from app import instance_name
    monkeypatch.delenv("SURASURA_INSTANCE_NAME", raising=False)
    monkeypatch.setattr("getpass.getuser", lambda: probe_person.FOLDER)
    path_utils.write_app_log(f"single instance: listening on {instance_name.instance_name()}")
    # the install keys, in the lines that log them
    from app import library_store, library_watch
    db = library_store.library_db_path("ja", path_utils.get_data_path("ja"))
    path_utils.write_app_log(f"library store: opened {db}; bell {library_watch.bell_name(db, 0)}; "
                             f"local data {path_utils.install_key()}")
    # a real contract.fail: the command line's events file, ensure_ascii (Zoë lands as Zo\u00eb)
    from app.cli import contract
    contract.fail("not_found", f"no such file: {video}")
    _write(os.path.join(logs, "arrivals-worker-ja.log"), f"opened {video}\r\nmachine {probe_person.MACHINE}\r\n"
           .encode("utf-8"))                                                       # CRLF
    _write(os.path.join(logs, "nested", "deeper", "chore.log"), f"{home}\\AppData\\x\n".encode("utf-8"))
    _write(os.path.join(logs, "utf16.log"), codecs.BOM_UTF16_LE + f"走った {home}\n".encode("utf-16-le"))
    _write(os.path.join(logs, "utf16-nobom.log"), f"error {home}\\x\n".encode("utf-16-le"))
    _write(os.path.join(logs, "cp932.log"), f"{LINE_JA} {probe_person.ACCOUNT}\n".encode("cp932"))
    _write(os.path.join(logs, "broken.log"), b"\x81\x00\xfe\xfa" + probe_person.ACCOUNT.encode() + b"\xff\x00")
    # settings: folders under home, a Jiten key, the decks
    with open(path_utils.get_settings_path(), "w", encoding="utf-8") as f:
        json.dump({"connect_anki_miner_path": os.path.join(home, "AppData", "Local", "Anki Miner", "anki_miner.exe"),
                   "connect_video_folders": [os.path.join(home, "Videos"), "D:\\アニメ"],
                   "jiten_api_key": "jk-secret-1234", "anki_sync_decks": {"ja": DECKS, "zh": ["中文::句子"]}},
                  f, ensure_ascii=False)
    # the Anki sync's state, Connect's record, Anki Miner's run result with its video path
    from app import anki_sync
    _write(os.path.join(path_utils.get_user_files_path("ja"), anki_sync.STATE_FILE),
           json.dumps({"decks": DECKS, "note_ids": [1, 2, 3], "profile": probe_person.PROFILE},
                      ensure_ascii=False).encode("utf-8"))
    from app.connect import ledger, setup
    _write(setup.record_path(), json.dumps({"anki_profile": probe_person.PROFILE}).encode("utf-8"))
    run = os.path.join(os.path.dirname(ledger.path()), "runs", "20261101-1200", "result.json")
    _write(run, json.dumps({"state": "done", "video_path": video, "output": os.path.join(home, "Anki Miner")})
           .encode("utf-8"))
    # the last lists: a CSV whose Sources name the home folder, sources.json, the report page, a database
    results = os.path.join(path_utils.get_user_data_path(), "results")
    _write(os.path.join(results, "reading_list.csv"),
           f"Word,Orth,Context 1,Sources\r\n文化祭,文化祭,{LINE_JA},{video}\r\n".encode("utf-8-sig"))
    _write(os.path.join(results, "sources.json"), json.dumps({video: TITLE}, ensure_ascii=False).encode("utf-8"))
    _write(os.path.join(results, "reading_list_static.html"), f"<html>{home}</html>".encode("utf-8"))
    _write(os.path.join(results, "cache.db"), b"SQLite format 3\x00" + home.encode("utf-8"))
    # reports: one whose pictures were taken in picture mode, one from before 3.0.1 (FORMAT 1, no "scrubbed")
    new = report.save(WHAT, f"{LINE_ZH} {home}", [PNG], where="Settings", scrubbed=True)
    old = report.save("古いレポート", "", [PNG])
    p.new, p.old, p.video = new, old, video
    p.library = {"language": "ja", "sources": [{"path": os.path.join(home, "Videos", TITLE)}, {"path": "D:/アニメ"}]}
    return p


def _entries(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def _forms(s):
    """`s` as it could sit in a zip's bytes: each written form (scrub.forms), and as UTF-16LE."""
    out = {f.encode("utf-8") for f in scrub.forms(s)}
    out |= {s.encode("utf-16-le")}
    return {f.lower() for f in out}


def _assert_no_one_in(files, strings):
    for name, data in files.items():
        low = data.lower()
        for s in strings:
            for f in _forms(s):
                assert f not in name.lower().encode("utf-8"), (name, s)
                assert f not in low, (name, s, f)


# --- the zip Send report sends ------------------------------------------------------------------------------------ #
def test_the_send_zip_holds_no_identifying_string_in_any_form_and_keeps_the_learners_words(world, tmp_path):
    made = report.make_send_zip(str(tmp_path / "out" / "send.zip"), "ja", library=world.library)
    files = _entries(made.path)
    assert scrub.leaks(made.path) == []
    _assert_no_one_in(files, world.strings)
    everything = b"\n".join(d for n, d in files.items() if not n.endswith(".png")).decode("utf-8")
    for kept in DECKS + [TITLE, LINE_JA, LINE_ZH, "中文::句子", "D:\\\\アニメ", "第3話"]:
        assert kept in everything or json.dumps(kept)[1:-1] in everything, kept      # deck names, titles, lines stay
    for placeholder in ("\\Users\\<you>\\Videos", "<pc>", "<anki profile 1>", "<email>", "<install key>"):
        assert placeholder in everything.replace("\\\\", "\\"), placeholder
    assert "jk-secret-1234" not in everything                                    # (secrets blanked before, as ever)


def test_the_send_zip_leaves_out_what_it_cant_check_each_with_its_reason(world, tmp_path):
    made = report.make_send_zip(str(tmp_path / "send.zip"), "ja", library=world.library)
    names = set(_entries(made.path))
    left = "\n".join(made.left_out)
    assert "results/reading_list_static.html" not in names and \
        f"results/reading_list_static.html: {report.LEFT_PAGE}" in left
    assert f"reports/{world.old.id}/picture-1.png: {report.LEFT_PICTURE}" in left
    assert f"reports/{world.new.id}/picture-1.png" in names                      # taken in picture mode: it goes
    assert f"logs/broken.log: {report.LEFT_UNREAD}" in left
    assert f"results/cache.db: {report.LEFT_KIND}" in left
    for name in ("logs/utf16.log", "logs/utf16-nobom.log", "logs/cp932.log", "logs/arrivals-worker-ja.log",
                 "logs/nested/deeper/chore.log", "logs/cli-events.jsonl"):
        assert name in names, name                                               # read in their own encodings
    files = _entries(made.path)
    assert "走った" in files["logs/utf16.log"].decode("utf-8") and LINE_JA in files["logs/cp932.log"].decode("utf-8")
    assert files["logs/arrivals-worker-ja.log"].count(b"\r\n") == 2                # CRLF kept
    manifest = files["MANIFEST.txt"].decode("utf-8")
    assert report.LEFT_PAGE in manifest and report.LEFT_PICTURE in manifest


def test_the_manifest_names_each_entrys_scrubbed_sha256_and_the_list_clears_by_the_original(world, tmp_path):
    """F1: MANIFEST holds what's in the zip (open_report checks it); `_clear` compares the file on disk."""
    made = report.make_send_zip(str(tmp_path / "send.zip"), "ja", library=world.library)
    files = _entries(made.path)
    rows = [line.split("  ") for line in files["MANIFEST.txt"].decode("utf-8").splitlines()[1:] if line.count("  ") >= 2
            and len(line.split("  ")[0]) == 64]
    assert rows and {name for _h, _s, name in rows} == set(files) - {"MANIFEST.txt"}
    for digest, size, name in rows:
        assert hashlib.sha256(files[name]).hexdigest() == digest and int(size) == len(files[name])
    on_disk = open(os.path.join(world.new.path, report.REPORT_FILE), "rb").read()
    assert made.zipped[world.new.id] == hashlib.sha256(on_disk).hexdigest()
    assert files[f"reports/{world.new.id}/report.json"] != on_disk                 # (the zipped one is scrubbed)
    assert {r.id for r in report.listed()} == {world.new.id, world.old.id}         # not cleared: not sent yet
    report._clear(report.folder(), made.zipped, made.removed)
    assert report.listed() == []


def test_a_report_given_a_note_after_the_send_zip_was_made_stays_on_the_list(world, tmp_path):
    made = report.make_send_zip(str(tmp_path / "send.zip"), "ja")
    report.add_note(world.new.id, "二回目は大丈夫だった")
    report._clear(report.folder(), made.zipped, made.removed)
    assert [r.id for r in report.listed()] == [world.new.id]


@pytest.mark.parametrize("prefix", ["reports/", "logs/", "anki-miner/", "connect/", "anki/", "settings.json",
                                    "library/", "results/", "about.txt"])
def test_an_entry_type_the_scrub_skipped_is_caught_by_the_guard_and_no_zip_is_offered(world, tmp_path, monkeypatch,
                                                                                     prefix):
    """The mutant that skips the scrub for one entry type: the guard refuses the zip, the list stays whole."""
    real = report._entry_bytes

    def skips(e, data, language, send, ident):
        if e.name.startswith(prefix):
            return data + f"\n{world.home}\n".encode("utf-8"), None             # as it was, with the home in it
        return real(e, data, language, send, ident)
    monkeypatch.setattr(report, "_entry_bytes", skips)
    out = tmp_path / "send.zip"
    with pytest.raises(report.Unsafe) as got:
        report.make_send_zip(str(out), "ja", library=world.library)
    assert got.value.names and all(n.startswith(prefix) for n in got.value.names)
    assert not out.exists() and not os.path.exists(str(out) + report.PART)
    assert len(report.listed()) == 2
    log = open(os.path.join(path_utils.get_local_data_path(), "logs", "app_debug_log.txt"), encoding="utf-8").read()
    assert got.value.names[0] in log.splitlines()[-1]                           # the file named in the app log …
    assert probe_person.FOLDER not in log.splitlines()[-1]                      # … never the string


def test_the_send_zip_never_takes_the_outbox_the_sent_copies_or_the_ids_files(world, tmp_path):
    persistent = path_utils.get_persistent_user_data_path()
    for rel in ("report_outbox/report.zip", "report_sent/K3Q7PM.zip", "report_send.json"):
        _write(os.path.join(persistent, *rel.split("/")), b"PK\x03\x04 " + world.home.encode("utf-8"))
    made = report.make_send_zip(str(tmp_path / "send.zip"), "ja")
    names = " ".join(_entries(made.path))
    for never in ("report_outbox", "report_sent", "report_send", "telemetry_id"):
        assert never not in names
    unreadable = []
    report.listed(unreadable=unreadable)
    assert unreadable == []                                                      # the outbox is beside reports/


def test_empty_states_still_make_a_send_zip(tmp_path, monkeypatch):
    """No logs, no results, no Connect, no settings.json: the report and about.txt go, the rest said."""
    probe_person.make(tmp_path, monkeypatch)
    r = report.save("リストが空のまま", "")
    made = report.make_send_zip(str(tmp_path / "send.zip"), "zh", include_results=True)
    names = set(_entries(made.path))
    assert {f"reports/{r.id}/report.txt", f"reports/{r.id}/report.json", "about.txt", "MANIFEST.txt"} <= names
    assert any(x.startswith("settings.json: not there") for x in made.left_out)
    assert any(x.startswith("results\\: not there") for x in made.left_out)


def test_no_reports_no_send_zip(tmp_path, monkeypatch):
    probe_person.make(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        report.make_send_zip(str(tmp_path / "send.zip"), "ja")


def test_show_me_names_the_files_as_the_zip_will_hold_them(world, tmp_path):
    from app.connect import ledger
    run = os.path.join(os.path.dirname(ledger.path()), "runs", f"{probe_person.FOLDER}-run", "result.json")
    _write(run, b'{"state": "done"}')
    words = report.describe(report.plan("ja", library=world.library))
    assert "anki-miner/(you)-run/result.json" in words
    assert probe_person.FOLDER not in words and not scrub.found(words)


# --- Make the zip ------------------------------------------------------------------------------------------------- #
def test_make_the_zip_is_scrubbed_too_and_marks_what_it_couldnt_check(world, tmp_path):
    found = []
    path = report.make_zip(str(tmp_path / "Downloads"), "ja", library=world.library, found=found)
    files = _entries(path)
    checked = {n: d for n, d in files.items()
               if n not in ("results/cache.db", "logs/broken.log", f"reports/{world.old.id}/picture-1.png")}
    _assert_no_one_in(checked, world.strings)
    manifest = files["MANIFEST.txt"].decode("utf-8")
    for kept in ("results/reading_list_static.html", "results/cache.db", "logs/broken.log",
                 f"reports/{world.old.id}/picture-1.png"):
        assert kept in files and f"{kept}: {report.NOT_CHECKED}" in manifest, kept
    assert probe_person.FOLDER not in files["results/reading_list_static.html"].decode("utf-8")   # scrubbed as text
    assert found == [] and "May hold your Windows name" not in manifest
    assert report.listed() == []                                                 # made: the list empties, as before


def test_make_the_zip_with_a_guard_hit_warns_and_names_the_file_never_blocks(world, tmp_path, monkeypatch):
    real = report._entry_bytes

    def skips(e, data, language, send, ident):
        if e.name == "settings.json":
            return data + world.home.encode("utf-8"), None
        return real(e, data, language, send, ident)
    monkeypatch.setattr(report, "_entry_bytes", skips)
    found = []
    path = report.make_zip(str(tmp_path / "Downloads"), "ja", found=found)
    assert found == ["settings.json"] and os.path.isfile(path)
    assert f"settings.json: {report.MAY_NAME_YOU}" in _entries(path)["MANIFEST.txt"].decode("utf-8")


def test_a_report_saved_with_scrubbed_pictures_says_so_in_format_2(tmp_path, monkeypatch):
    probe_person.make(tmp_path, monkeypatch)
    r = report.save("設定の画面", "", [PNG], scrubbed=True)
    data = json.load(open(os.path.join(r.path, report.REPORT_FILE), encoding="utf-8"))
    assert data["format"] == 2 and data["scrubbed"] == 1 and report.listed()[0].scrubbed
    report.add_note(r.id, "メモ")
    assert json.load(open(os.path.join(r.path, report.REPORT_FILE), encoding="utf-8"))["scrubbed"] == 1
    plain = report.save("古い", "", [PNG])
    assert "scrubbed" not in json.load(open(os.path.join(plain.path, report.REPORT_FILE), encoding="utf-8"))


def test_an_error_naming_a_path_is_scrubbed_in_the_zips_list_and_in_show_me(world, tmp_path, monkeypatch):
    """A file that can't be read while the zip is written, and logs that can't be listed: their errors quote paths."""
    real = report._read_shared

    def held(path):
        if path.endswith("chore.log"):
            raise PermissionError(f"[WinError 32] in use: '{path}'")
        return real(path)
    monkeypatch.setattr(report, "_read_shared", held)
    path = report.make_zip(str(tmp_path / "Downloads"), "ja", library=world.library)
    manifest = _entries(path)["MANIFEST.txt"].decode("utf-8")
    assert "logs/nested/deeper/chore.log: couldn't be read" in manifest
    assert probe_person.FOLDER not in manifest and not scrub.found(manifest)
    from app.connect import status

    def unlistable(left_out=None):
        raise PermissionError(f"[WinError 5] Access is denied: '{world.home}\\AppData\\Local\\Houseki'")
    monkeypatch.setattr(status, "log_files", unlistable)
    report.save("もう一つ", "")
    words = report.describe(report.plan("ja"))
    assert "logs: couldn't be listed" in words and probe_person.FOLDER not in words and not scrub.found(words)


# --- the review's findings (register 2026-11-01) ------------------------------------------------------------------ #
def _open_report_accepts(name):
    """open_report's name rules (the Worker's tree): no control character or `<>:"|?*`, a known suffix."""
    import re
    return not re.search(r'[\x00-\x1f<>:"|?*]', name) and bool(
        name == "MANIFEST.txt" or re.search(r"\.(txt|log|json|jsonl|csv|png)(\.(\d{1,3}|old))?$", name, re.I))


def test_a_scrubbed_entry_name_is_one_open_report_and_windows_accept(world, tmp_path):
    from app.connect import ledger
    for run in (f"{probe_person.FOLDER}-run", f"{probe_person.ACCOUNT}-run"):    # two names the scrub makes one
        _write(os.path.join(os.path.dirname(ledger.path()), "runs", run, "result.json"), b'{"state": "done"}')
    made = report.make_send_zip(str(tmp_path / "send.zip"), "ja", library=world.library)
    names = list(_entries(made.path))
    assert "anki-miner/(you)-run/result.json" in names and "anki-miner/(you)-run/result-2.json" in names
    assert all(_open_report_accepts(n) for n in names), [n for n in names if not _open_report_accepts(n)]


@pytest.mark.parametrize("language, encoding", [("ja", "cp932"), ("zh", "gb18030")])
def test_a_mostly_utf8_log_with_a_stray_byte_never_hides_the_name_as_garbled_text(world, tmp_path, language,
                                                                                    encoding):
    """One byte that isn't UTF-8 made the whole file read as CP932 / GB18030, garbling a UTF-8 Zoë past the scrub."""
    logs = os.path.join(path_utils.get_local_data_path(), "logs")
    _write(os.path.join(logs, "mixed.log"), f"opened {world.home}\\Videos\n".encode("utf-8") + b"stderr: \x81\x40 ok\n")
    made = report.make_send_zip(str(tmp_path / "send.zip"), language, library=world.library)
    data = _entries(made.path)["logs/mixed.log"]
    for view in (data.decode("utf-8"), data.decode("utf-8").encode(encoding, "replace").decode("utf-8", "replace")):
        assert probe_person.FOLDER not in view and "Zo" + "ë" not in view
    assert b"\\Users\\<you>\\Videos" in data
    garbled = "opened C:\\Users\\Zoë Tanaka-Probe".encode("utf-8").decode(encoding, "replace")  # the old read
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("logs/mixed.log", garbled.encode("utf-8"))
    ident = scrub.Identity(homes=["C:\\Users\\Zoë Tanaka-Probe"])           # (only the garbled name to find)
    assert scrub.leaks(str(bad), ident, language) == ["logs/mixed.log"]     # the guard reads garbling back


def test_an_anki_profile_set_up_after_the_window_opened_is_scrubbed(world, tmp_path):
    scrub.identity()                                                             # the window opened
    _write(os.path.join(os.environ["APPDATA"], "Anki2", "Kenji", "collection.anki2"), b"")
    path_utils.write_app_log("connect: Anki is open on the profile Kenji")
    made = report.make_send_zip(str(tmp_path / "send.zip"), "ja", library=world.library)
    log = _entries(made.path)["logs/app_debug_log.txt"].decode("utf-8")
    assert "Kenji" not in log and "<anki profile" in log


def test_a_line_added_while_the_zip_is_written_is_scrubbed_in_what_goes_too(world, tmp_path, monkeypatch):
    real = report._read_shared

    def held(path):
        if path.endswith("chore.log"):
            raise PermissionError(f"[WinError 32] in use: '{path}'")
        return real(path)
    monkeypatch.setattr(report, "_read_shared", held)
    made = report.make_send_zip(str(tmp_path / "send.zip"), "ja", library=world.library)
    assert any("chore.log: couldn't be read" in x for x in made.left_out)
    assert not any(probe_person.FOLDER in x for x in made.left_out)


def test_a_crash_padded_log_is_read_without_its_nuls(world, tmp_path):
    logs = os.path.join(path_utils.get_local_data_path(), "logs")
    _write(os.path.join(logs, "crashed.log"), f"Traceback in {world.home}\n".encode("utf-8") + b"\x00" * 4096)
    made = report.make_send_zip(str(tmp_path / "send.zip"), "ja", library=world.library)
    data = _entries(made.path)["logs/crashed.log"]
    assert data.startswith(b"Traceback in ") and b"\x00" not in data and probe_person.FOLDER.encode() not in data


def test_a_log_cut_with_no_whole_line_starts_at_a_whole_character():
    data = ("あ" * 4000).encode("utf-8")
    cut = report._tail(data, 1001)                                               # 1001 is no multiple of 3
    assert cut.decode("utf-8") == "あ" * (len(cut) // 3)

"""Report a problem's saved list and its zip (`app/report.py`; the scope `tracks/ship/work/report/scope.md`).

What a wrong answer would cost: a tester's noted problems lost (a crash mid-save, a zip that failed but emptied the
list, a note that half-wrote report.json); a report another program's folder could be named into (a path outside the
list); a key, a token, a card's sentence or a subtitle's text in a zip the tester sends; a zip that says it holds what
it doesn't. Words are a learner's real ones (ja + zh), never ASCII stand-ins.
"""
import json
import os
import re
import sqlite3
import time
import zipfile

import pytest

from app import path_utils
from app import report as core

JA_WHAT = "「進撃の巨人」の第3話を終わったに入れたら、Ankiの並びが変わらなかった。\r\n二回目は大丈夫だった。"
JA_EXPECTED = "新しいカードが後ろに回ると思った"
ZH_WHAT = "把《甄嬛传》第五集拖到已看完以后，单词表没有更新。"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture
def root(tmp_path):
    """The saved list's folder, as the app makes it (the persistent folder under the test root)."""
    folder = core.folder()
    assert folder.startswith(os.environ["SURASURA_TEST_ROOT"])        # never the real %APPDATA%\Houseki
    return folder


def _zip(tmp_path, language="ja", include_results=True, library=None, root=None):
    dest = tmp_path / "Downloads"
    path = core.make_zip(str(dest), language, include_results, library, root=root)
    with zipfile.ZipFile(path) as z:
        return path, {n: z.read(n) for n in z.namelist()}


# --- the saved list -------------------------------------------------------------------------------------------- #
def test_a_saved_report_keeps_its_words_picture_and_build_and_survives_a_fresh_read(root):
    r = core.save(JA_WHAT, JA_EXPECTED, [PNG], where="the Current tab")
    again = core.listed()                                  # a restart: read from disk, nothing in memory
    assert [x.id for x in again] == [r.id]
    got = again[0]
    assert got.what == JA_WHAT.strip() and got.expected == JA_EXPECTED and got.where == "the Current tab"
    assert got.pictures == ["picture-1.png"]
    assert open(os.path.join(got.path, "picture-1.png"), "rb").read() == PNG
    assert got.build["version"] and "data_name" in got.build
    assert got.title() == "「進撃の巨人」の第3話を終わったに入れたら、Ankiの並びが変わらなかった。"


def test_the_list_is_oldest_first_and_counts_both_languages_reports(root):
    a = core.save(JA_WHAT)
    b = core.save(ZH_WHAT)                                 # in the same second: still in the order saved
    assert [x.id for x in core.listed()] == [a.id, b.id]
    assert core.count() == 2


def test_a_report_with_no_words_is_refused_and_nothing_is_written(root):
    with pytest.raises(ValueError):
        core.save("  \r\n ", JA_EXPECTED, [PNG])
    assert os.listdir(root) == []


def test_a_save_that_dies_part_way_leaves_nothing_on_the_list(root, monkeypatch):
    # The report.json write fails after the picture is on disk: the .part folder is removed, nothing listed.
    def broken(path, data):
        raise OSError("disk full")
    monkeypatch.setattr(core, "_atomic_write", broken)
    with pytest.raises(OSError):
        core.save(JA_WHAT, "", [PNG])
    assert core.listed() == [] and os.listdir(root) == []


def test_a_crash_mid_save_leaves_a_part_folder_the_list_never_shows(root):
    # A kill between the picture and the rename: a .part folder with a whole report.json in it stays unlisted.
    part = os.path.join(root, "20261024-210000-abcdef" + core.PART)
    os.makedirs(part)
    with open(os.path.join(part, core.REPORT_FILE), "w", encoding="utf-8") as f:
        json.dump({"what": JA_WHAT}, f, ensure_ascii=False)
    os.makedirs(os.path.join(root, "empty"))               # a folder with no report.json at all
    os.makedirs(os.path.join(root, "torn"))
    with open(os.path.join(root, "torn", core.REPORT_FILE), "w", encoding="utf-8") as f:
        f.write('{"what": "途中で')                        # torn JSON
    assert core.listed() == []


def test_more_pictures_than_the_cap_keeps_the_first_ones(root):
    r = core.save(JA_WHAT, "", [PNG] * (core.MAX_PICTURES + 2))
    assert len(r.pictures) == core.MAX_PICTURES


def test_a_note_is_added_and_kept_and_an_empty_note_is_refused(root):
    r = core.save(ZH_WHAT)
    core.add_note(r.id, "重启以后又出现了一次")
    core.add_note(r.id, "第二次在设置页面")
    got = core.listed()[0]
    assert [n["text"] for n in got.notes] == ["重启以后又出现了一次", "第二次在设置页面"]
    with pytest.raises(ValueError):
        core.add_note(r.id, "   ")
    assert len(core.listed()[0].notes) == 2


def test_a_note_that_fails_to_write_leaves_the_report_as_it_was(root, monkeypatch):
    r = core.save(JA_WHAT)
    before = open(os.path.join(r.path, core.REPORT_FILE), "rb").read()
    real = os.replace

    def refuse(src, dst):
        if dst.endswith(core.REPORT_FILE):
            raise PermissionError("held by a reader")
        return real(src, dst)
    monkeypatch.setattr(core.os, "replace", refuse)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        core.add_note(r.id, "もう一度")
    assert open(os.path.join(r.path, core.REPORT_FILE), "rb").read() == before
    assert [n for n in os.listdir(r.path) if n.endswith(".tmp")] == []     # no temp file left beside it


def test_remove_takes_it_off_the_list_and_undo_puts_it_back(root):
    a, b = core.save(JA_WHAT), core.save(ZH_WHAT)
    assert core.remove(a.id) is True
    assert [x.id for x in core.listed()] == [b.id]
    assert core.restore(a.id) is True
    assert sorted(x.id for x in core.listed()) == sorted([a.id, b.id])
    assert core.remove("20990101-000000-nothin") is False


@pytest.mark.parametrize("bad", ["..", "../settings.json", "removed", "a\\b", "x" + core.PART, "", None])
def test_a_report_id_never_names_a_path_outside_the_list(root, bad):
    for fn in (core.remove, core.restore, lambda rid: core.add_note(rid, "メモ")):
        with pytest.raises((ValueError, TypeError)):
            fn(bad)


# --- what goes in the zip -------------------------------------------------------------------------------------- #
def test_settings_lose_every_key_token_and_password_at_any_depth():
    got = core.strip_secrets({"target_language": "ja", "gemini_api_key": "AIzaSy-real", "koe": {"client_token": "t"},
                              "accounts": [{"password": "hunter2", "name": "ソニック"}], "anki_sync_decks": ["日本語"],
                              "empty_key": ""})
    assert got == {"target_language": "ja", "gemini_api_key": core.BLANKED, "koe": {"client_token": core.BLANKED},
                   "accounts": [{"password": core.BLANKED, "name": "ソニック"}], "anki_sync_decks": ["日本語"],
                   "empty_key": ""}


@pytest.mark.parametrize("name,secret", [(".env", True), ("prod.env", True), ("signing.key", True),
                                         ("koe_credentials.json", True), ("keystore.db-wal", True),
                                         ("my_api_key.txt", True), ("cli.log", False), ("app_debug_log.txt", False),
                                         ("ledger.sqlite-wal", False)])
def test_secret_names_are_the_collectors(name, secret):
    assert core.is_secret(name) is secret


def test_the_collectors_secret_names_are_this_list():
    # One rule: the PowerShell collector (for when the app won't open) keeps its own copy; it must say the same.
    ps1 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "agent instructions",
                       "3.0", "S3.1-package", "laptop-try", "Collect laptop evidence.ps1")
    if not os.path.exists(ps1):
        pytest.skip("the collector lives in the private repo")
    text = open(ps1, encoding="utf-8-sig").read()
    block = re.search(r"\$SecretNames = @\((.*?)\)", text, re.S).group(1)
    assert tuple(re.findall(r'"([^"]+)"', block)) == core.SECRET_NAMES


def _ledger_with_a_sentence():
    from app.connect import ledger as book
    with book.Ledger() as led:
        led.conn.execute("INSERT INTO jobs (language, item_id, state, created_at, updated_at, kind, words) "
                         "VALUES ('ja', 7, 'done', '2026-10-24T12:00:00Z', '2026-10-24T12:05:00Z', 'mine', ?)",
                         (json.dumps([["巨人", "きょじん"]], ensure_ascii=False),))
        job = led.conn.execute("SELECT id FROM jobs").fetchone()[0]
        led.conn.execute("INSERT INTO outcomes (job_id, word, reading, orth, sentence, outcome, attempt) VALUES "
                         "(?, '巨人', 'きょじん', '巨人', '壁の向こうに巨人がいた', 'made', 1)", (job,))
    return job


def test_the_zip_holds_each_report_and_what_sonic_needs_and_the_list_then_empties(root, tmp_path):
    a = core.save(JA_WHAT, JA_EXPECTED, [PNG])
    core.add_note(a.id, "二回目は大丈夫")
    b = core.save(ZH_WHAT, "", [])
    logs = os.path.join(path_utils.get_local_data_path(), "logs")
    os.makedirs(logs, exist_ok=True)
    with open(os.path.join(logs, "cli.log"), "w", encoding="utf-8") as f:
        f.write("verb=generate exit=0 0.512s argv=['generate', '--language', 'ja']\n")
    job = _ledger_with_a_sentence()
    library = {"language": "ja", "counts": {"current_rows": 12, "finished": 3}, "sources": [{"path": "D:/アニメ"}]}
    path, files = _zip(tmp_path, library=library)
    assert os.path.basename(path).startswith("Surasura-problems-") and path.endswith(".zip")
    assert files[f"reports/{a.id}/picture-1.png"] == PNG
    text = files[f"reports/{a.id}/report.txt"].decode("utf-8")
    assert JA_WHAT.strip() in text and JA_EXPECTED in text and "二回目は大丈夫" in text
    assert ZH_WHAT in files[f"reports/{b.id}/report.txt"].decode("utf-8")
    assert b"verb=generate" in files["logs/cli.log"]
    assert json.loads(files["library/summary.json"]) == library
    assert b"version:" in files["about.txt"]
    ledger = json.loads(files["connect/ledger.json"])
    assert [j["id"] for j in ledger["jobs"]] == [job] and ledger["outcomes"] == [{"job_id": job, "outcome": "made",
                                                                                   "n": 1}]
    everything = b"".join(files.values()).decode("utf-8", "replace")
    assert "壁の向こうに巨人がいた" not in everything                   # an outcome's sentence: never
    assert "きょじん" not in everything                                 # nor a job's words
    manifest = files["MANIFEST.txt"].decode("utf-8")
    for name in files:
        if name != "MANIFEST.txt":
            assert name in manifest
    assert core.listed() == []                                          # the list empties, only now
    assert not os.path.exists(os.path.join(root, a.id))


def test_a_zip_that_fails_part_way_leaves_no_zip_and_the_whole_list(root, tmp_path, monkeypatch):
    a = core.save(JA_WHAT, "", [PNG])
    real = zipfile.ZipFile.writestr

    def dies(self, name, data, *args, **kw):
        if name == "MANIFEST.txt":
            raise OSError("the drive was unplugged")
        return real(self, name, data, *args, **kw)
    monkeypatch.setattr(zipfile.ZipFile, "writestr", dies)
    with pytest.raises(OSError):
        core.make_zip(str(tmp_path / "out"), "ja")
    assert os.listdir(tmp_path / "out") == []                          # no .zip, no .zip.part
    assert [x.id for x in core.listed()] == [a.id]
    assert open(os.path.join(root, a.id, "picture-1.png"), "rb").read() == PNG


def test_a_zip_that_doesnt_read_back_whole_is_never_renamed_into_place(root, tmp_path, monkeypatch):
    core.save(JA_WHAT)
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: "reports/x/report.txt")
    with pytest.raises(OSError):
        core.make_zip(str(tmp_path / "out"), "ja")
    assert os.listdir(tmp_path / "out") == [] and core.count() == 1


def test_a_report_whose_picture_cant_be_read_makes_no_zip(root, tmp_path):
    r = core.save(JA_WHAT, "", [PNG])
    p = core.plan("ja", root=root)
    os.remove(os.path.join(r.path, "picture-1.png"))                   # gone between the plan and the zip
    entry = next(e for e in p.entries if e.name.endswith("picture-1.png"))
    with pytest.raises(OSError):
        core._read_shared(entry.source)
    # make_zip plans again (the picture no longer listed), so the zip is whole without it and says nothing is lost
    path, files = _zip(tmp_path, root=root)
    assert f"reports/{r.id}/picture-1.png" not in files


def test_a_report_saved_while_the_zip_is_written_stays_on_the_list(root, tmp_path, monkeypatch):
    first = core.save(JA_WHAT)
    real = core._manifest
    later = []

    def meanwhile(p, hashes):
        later.append(core.save(ZH_WHAT))                               # the tester saves another during the zip
        return real(p, hashes)
    monkeypatch.setattr(core, "_manifest", meanwhile)
    _path, files = _zip(tmp_path, root=root)
    assert f"reports/{first.id}/report.txt" in files
    assert [x.id for x in core.listed()] == [later[0].id]


def test_removed_reports_never_go_in_the_zip_and_are_cleared_by_it(root, tmp_path):
    keep, gone = core.save(JA_WHAT), core.save(ZH_WHAT)
    core.remove(gone.id)
    _path, files = _zip(tmp_path, root=root)
    assert not any(gone.id in n for n in files)
    assert not os.path.exists(os.path.join(root, core.REMOVED_DIR))


def test_an_old_part_folder_is_cleared_by_a_zip_but_a_fresh_one_is_left(root, tmp_path):
    core.save(JA_WHAT)
    old = os.path.join(root, "20261020-000000-oldold" + core.PART)
    fresh = os.path.join(root, "20261024-235959-fresh1" + core.PART)
    os.makedirs(old)
    os.makedirs(fresh)
    two_hours = time.time() - 7200
    os.utime(old, (two_hours, two_hours))
    _zip(tmp_path, root=root)
    assert not os.path.exists(old) and os.path.exists(fresh)          # a save under way keeps its folder


def test_no_reports_no_zip(root, tmp_path):
    with pytest.raises(ValueError):
        core.make_zip(str(tmp_path / "out"), "ja")
    assert not os.path.exists(tmp_path / "out")


def test_two_zips_in_one_second_get_their_own_names(root, tmp_path):
    import datetime
    now = datetime.datetime(2026, 10, 24, 21, 0, 0).astimezone()
    core.save(JA_WHAT)
    first = core.make_zip(str(tmp_path), "ja", now=now)
    core.save(ZH_WHAT)
    second = core.make_zip(str(tmp_path), "ja", now=now)
    assert first != second and os.path.exists(first) and os.path.exists(second)


def test_results_are_in_when_ticked_and_out_when_not(root, tmp_path):
    results = os.path.join(path_utils.get_user_data_path(), "results")
    os.makedirs(results, exist_ok=True)
    with open(os.path.join(results, "run_signature.txt"), "w", encoding="utf-8", newline="") as f:
        f.write("ja abc123\n")
    with open(os.path.join(results, "api_key.txt"), "w", encoding="utf-8") as f:
        f.write("sk-never")
    core.save(JA_WHAT)
    _p, files = _zip(tmp_path, root=root)
    assert files["results/run_signature.txt"] == b"ja abc123\n"
    assert "results/api_key.txt" not in files and b"sk-never" not in b"".join(files.values())
    core.save(JA_WHAT)
    _p, files = _zip(tmp_path, include_results=False, root=root)
    assert not any(n.startswith("results/") for n in files)
    assert "Include my last lists was unticked" in files["MANIFEST.txt"].decode("utf-8")


def test_settings_in_the_zip_are_stripped(root, tmp_path):
    path = path_utils.get_settings_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"target_language": "zh", "koe_api_key": "AIzaSy-real-key", "logic": {"zh_script": "simplified"}},
                  f, ensure_ascii=False)
    core.save(ZH_WHAT)
    _p, files = _zip(tmp_path, "zh", root=root)
    got = json.loads(files["settings.json"])
    assert got["koe_api_key"] == core.BLANKED and got["logic"] == {"zh_script": "simplified"}
    assert b"AIzaSy-real-key" not in b"".join(files.values())


def test_anki_sync_state_counts_its_note_ids_never_lists_them(root, tmp_path):
    from app import anki_sync
    folder = path_utils.get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, anki_sync.STATE_FILE), "w", encoding="utf-8") as f:
        json.dump({"last_sync": "2026-10-24T20:00:00", "last_added": 3, "note_ids": [1700000000001, 1700000000002]}, f)
    core.save(JA_WHAT)
    _p, files = _zip(tmp_path, root=root)
    got = json.loads(files["anki/anki_sync_state-ja.json"])
    assert got["note_ids"] == "2 ids" and got["last_added"] == 3


def test_a_log_named_like_a_secret_is_left_out_and_said(root, tmp_path):
    logs = os.path.join(path_utils.get_local_data_path(), "logs")
    os.makedirs(logs, exist_ok=True)
    with open(os.path.join(logs, "token-secret.log"), "w") as f:
        f.write("never")
    core.save(JA_WHAT)
    _p, files = _zip(tmp_path, root=root)
    assert "logs/token-secret.log" not in files
    assert "token-secret.log: a key or secret by its name" in files["MANIFEST.txt"].decode("utf-8")


def test_the_persistent_folder_is_never_walked_its_keys_never_taken(root, tmp_path):
    keys = os.path.join(path_utils.get_persistent_user_data_path(), "koe_credentials.json")
    with open(keys, "w", encoding="utf-8") as f:
        json.dump({"api_key": "AIzaSy-koe"}, f)
    core.save(JA_WHAT)
    _p, files = _zip(tmp_path, root=root)
    assert b"AIzaSy-koe" not in b"".join(files.values())


def test_show_me_names_every_file_the_zip_holds(root, tmp_path):
    r = core.save(JA_WHAT, "", [PNG])
    words = core.describe(core.plan("ja", root=root))
    for name in (f"reports/{r.id}/report.txt", f"reports/{r.id}/picture-1.png", "about.txt", "settings.json",
                 "library/summary.json", "MANIFEST.txt"):
        assert name in words
    assert "Left out:" in words and "never taken" in words
    _p, files = _zip(tmp_path, root=root)
    for name in files:
        assert name in words                                           # nothing in the zip the list didn't name


@pytest.mark.skipif(os.name != "nt", reason="links on Windows: a junction")
def test_a_linked_results_folder_is_never_walked(root, tmp_path):
    import subprocess
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "private.txt").write_text("巨人の秘密", encoding="utf-8")
    results = os.path.join(path_utils.get_user_data_path(), "results")
    if os.path.exists(results):
        os.rmdir(results)
    subprocess.run(["cmd", "/c", "mklink", "/J", results, str(elsewhere)], check=True, capture_output=True)
    try:
        core.save(JA_WHAT)
        _p, files = _zip(tmp_path, root=root)
        assert not any(n.startswith("results/") for n in files)
        assert "results\\: a link" in files["MANIFEST.txt"].decode("utf-8")
    finally:
        os.rmdir(results)                                               # the junction only, never its target
    assert (elsewhere / "private.txt").exists()


def test_a_frozen_build_names_its_commit_and_the_report_says_it(monkeypatch):
    from app import build_info
    import package_app
    monkeypatch.setattr(build_info, "BUILD_COMMIT", "1e72f8108fe1/8bbb85e136c4")
    assert core.build()["commit"] == "1e72f8108fe1/8bbb85e136c4"
    # the freeze's text: BUILD_COMMIT appended after BUILD_ID, read back as the module would
    text = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "build_info.py"),
                encoding="utf-8").read()
    assert "BUILD_COMMIT = None" in text
    namespace = {}
    exec(compile(text.rstrip("\r\n") + '\nBUILD_ID = "x"\nBUILD_COMMIT = "abc/def"\n', "build_info.py", "exec"),
         namespace)
    assert namespace["BUILD_COMMIT"] == "abc/def"
    assert package_app.source_commit(os.path.join(os.environ["SURASURA_TEST_ROOT"], "not-a-repo")) is None

"""The scrub (`app/scrub.py`; Send report, `tracks/ship/work/send-report/SPEC.md` §2): who "you" are on this PC, every
form their names can be written in, and the guard that reads a written zip again.

What a wrong answer would cost: the window promises "No personal data or identification is included" — a user name,
a home folder, a PC's name, an employer (OneDrive's organisation), a family member's Anki profile or a code that tags
one install for months, left in one escaped form the scrub didn't know, goes to Sonic's storage against that line. The
other way: a scrub that eats deck names, titles or words makes the report useless. Names are a made-up person's
(`tests/scrub_probe.py`), words a learner's real ones.
"""
import codecs
import json
import os
import re
import struct
import zipfile
import zlib

import pytest

from app import path_utils, scrub
from tests import scrub_probe as probe_person

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _fresh_identity():
    scrub.reset()
    yield
    scrub.reset()


@pytest.fixture
def probe(tmp_path, monkeypatch):
    return probe_person.make(tmp_path, monkeypatch)


def person(**more):
    """A hand-made Identity: Zoë's home and names, plus `more`."""
    base = dict(homes=[r"C:\Users\Zoë Tanaka-Probe"], users=["ztanprobe"], machines=["DESKTOP-PROBE7"],
                orgs=["Probe Org"], profiles=["Probe Anki", "User 1"], keys=["0123456789abcdef"],
                telemetry=["6f1c2d3e-4b5a-4c6d-8e7f-90a1b2c3d4e5"])
    base.update(more)
    return scrub.Identity(**base)


# --- every form ---------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("written", [
    r"C:\Users\Zoë Tanaka-Probe\Videos\進撃の巨人\01.srt",                       # as Windows writes it
    json.dumps(r"C:\Users\Zoë Tanaka-Probe\Videos\進撃の巨人", ensure_ascii=False),  # JSON: \\ between parts
    json.dumps(r"C:\Users\Zoë Tanaka-Probe\Videos\進撃の巨人"),                   # ensure_ascii: Zo\u00eb
    json.dumps(json.dumps(r"C:\Users\Zoë Tanaka-Probe\Videos")),                # JSON in JSON: \\\\ and \\u00eb
    json.dumps(r"C:\Users\Zoë Tanaka-Probe\x").replace(r"\u00eb", r"\u00EB"),    # upper-case hex
    ascii(r"C:\Users\Zoë Tanaka-Probe\Videos"),                                  # a repr / faulthandler: Zo\xeb
    repr(r"C:\Users\Zoë Tanaka-Probe\Videos".encode("utf-8")),                   # a bytes repr: Zo\xc3\xab
    "file:///C:/Users/Zo%C3%AB%20Tanaka-Probe/Videos/%E9%80%B2%E6%92%83.mkv",    # a file URL, percent-encoded
    "file:///C:/Users/Zo%c3%ab+Tanaka-Probe/Videos",                             # lower-case hex, + for a space
    "C:%5CUsers%5CZo%C3%AB%20Tanaka-Probe%5CVideos",                             # %5C separators
    "/c/Users/Zoë Tanaka-Probe/Videos",                                          # Git Bash
    "C:/Users/Zoë Tanaka-Probe/Videos",                                          # forward slashes
    "c:\\users\\ZOË TANAKA-PROBE\\videos",                                       # any letter case
    "C:\\Users\\Zoe\u0308 Tanaka-Probe\\Videos",                                 # NFD (macOS keeps é split)
    "surasura-window-Zo__Tanaka-Probe-1-0a1b2c3d4e5f",                           # the window lock's `_` form
])
def test_a_home_folder_in_every_form_it_is_written_in_loses_its_name(written):
    ident = person()
    out = ident.scrub(written)
    assert not ident.found(out), out
    assert "Tanaka" not in out and "Probe" not in out
    assert "<you>" in out


def test_a_home_keeps_its_drive_users_part_and_separators_and_the_titles_below_it():
    ident = person()
    assert ident.scrub(r"C:\Users\Zoë Tanaka-Probe\Videos\進撃の巨人\01.srt") == r"C:\Users\<you>\Videos\進撃の巨人\01.srt"
    assert ident.scrub('{"p": "C:\\\\Users\\\\Zoë Tanaka-Probe\\\\Videos"}') == \
        '{"p": "C:\\\\Users\\\\<you>\\\\Videos"}'
    assert ident.scrub("/c/Users/Zoë Tanaka-Probe/Videos") == "/c/Users/<you>/Videos"


def test_the_8_3_short_form_of_a_home_is_its_home_too():
    ident = person(homes=[r"C:\Users\Zoë Tanaka-Probe", r"C:\Users\ZOTANA~1"])
    assert ident.scrub(r"C:\Users\ZOTANA~1\AppData\Local\Temp\x.log") == r"C:\Users\<you>\AppData\Local\Temp\x.log"


def test_a_user_name_goes_as_a_whole_word_only_and_in_any_case():
    ident = person(users=["Michael"])
    assert ident.scrub("Michaelson met Michael, MICHAEL and michael2") == "Michaelson met <you>, <you> and michael2"
    assert ident.scrub("_Michael_ (Michael) Michael.txt") == "_<you>_ (<you>) <you>.txt"


@pytest.mark.parametrize("gap", ["%20", "\\n", "\\t", "\\x20", "\\u00e9", "%2F", "\\x5c", "\\u005c"])
def test_an_escape_beside_a_name_is_a_gap_never_a_letter(gap):
    """`%20Michael` is ' Michael': the C of %2C or the n of \\n is an escape's, not part of a word."""
    ident = person(users=["Michael"])
    assert ident.scrub(f"x{gap}Michael{gap}y") == f"x{gap}<you>{gap}y"


def test_a_name_in_other_letters_goes_wherever_it_stands():
    ident = person(homes=[r"C:\Users\田中"], users=["田中"])
    assert ident.scrub(r"C:\Users\田中\Videos") == r"C:\Users\<you>\Videos"
    assert ident.scrub("田中さんのPC、" + json.dumps("田中")) == "<you>さんのPC、\"<you>\""
    assert ident.scrub("__init__.py and __main__") == "__init__.py and __main__"     # (its lock form __ names no one)


def test_a_one_letter_user_is_scrubbed_only_as_a_home_folders_last_part():
    ident = person(homes=[r"D:\Profiles\z"], users=["z"])
    assert ident.scrub(r"D:\Profiles\z\Anki2 and a z alone, zebra") == r"D:\Profiles\<you>\Anki2 and a z alone, zebra"
    assert ident.users == []


def test_a_user_named_like_an_everyday_word_is_replaced_where_it_stands_alone():
    """The accepted price (§2.2 ⚖️): privacy over a tidy log."""
    ident = person(users=["user"])
    assert ident.scrub("the user pressed Send; username stays") == "the <you> pressed Send; username stays"


def test_machine_names_in_a_unc_path_and_a_domain_account():
    ident = person()
    out = ident.scrub(r"\\DESKTOP-PROBE7\share\a.srt and desktop-probe7\ztanprobe logged in")
    assert out == r"\\<pc>\share\a.srt and <pc>\<you> logged in"


def test_onedrives_organisation_is_named_by_no_one():
    ident = person()
    out = ident.scrub(r"C:\Users\Zoë Tanaka-Probe\OneDrive - Probe Org\Documents\本.epub")
    assert out == r"C:\Users\<you>\OneDrive - <org>\Documents\本.epub"


def test_anki_profiles_are_numbered_case_sensitive_and_ankis_default_stays():
    ident = person(profiles=["Probe Anki", "家族", "User 1"])
    out = ident.scrub('Anki is open on the profile "家族", but Connect was set up with "Probe Anki". User 1 too.')
    assert out == 'Anki is open on the profile "<anki profile 2>", but Connect was set up with "<anki profile 1>". ' \
                  'User 1 too.'
    assert ident.scrub("probe anki") == "probe anki"


def test_emails_sids_install_keys_and_the_telemetry_id():
    ident = person()
    out = ident.scrub("mail zoe.probe@example.co.jp · $Recycle.Bin\\S-1-5-21-1004336348-1177238915-682003330-1001\\x · "
                      "library_ja_0123456789ABCDEF.db · Surasura-bell-0123456789abcdef-0 · "
                      "uid 6F1C2D3E-4B5A-4C6D-8E7F-90A1B2C3D4E5")
    assert out == ("mail <email> · $Recycle.Bin\\<sid>\\x · library_ja_<install key>.db · "
                   "Surasura-bell-<install key>-0 · uid <telemetry id>")


def test_a_longer_hex_run_holding_a_key_is_another_hash_and_stays():
    ident = person()
    digest = "ff0123456789abcdefff"
    assert ident.scrub(digest) == digest


def test_deck_names_titles_words_and_subtitle_lines_stay():
    ident = person()
    kept = "日本語::Kaishi 1.5k · 中文::句子 · 進撃の巨人 第3話 · 文化祭まで、あと三日しかないよ。 · 今天我们要去台北的夜市吃东西。"
    assert ident.scrub(kept) == kept


def test_a_placeholder_is_never_a_hit_even_for_a_user_named_like_one():
    ident = person(users=["you"], machines=["pc"])
    out = ident.scrub("you on pc")
    assert out == "<you> on <pc>"
    assert not ident.found(out)
    assert ident.found("you")


def test_an_empty_or_unmatched_text_comes_back_as_it_is():
    ident = person()
    assert ident.scrub("") == ""
    line = "2026-11-01 12:00:00 generate ok 0.51s\r\n"
    assert ident.scrub(line) is line                                 # nothing to look for: the same string


# --- who you are, read from this PC ------------------------------------------------------------------------------- #
def test_identity_reads_every_source_on_this_pc(probe):
    ident = scrub.read_identity()
    assert any(os.path.normcase(h) == os.path.normcase(probe.home) for h in ident.homes)
    assert probe.short_home in ident.homes
    assert {probe_person.FOLDER, probe_person.ACCOUNT, probe_person.SHORT} <= set(ident.users)
    assert probe_person.MACHINE in ident.machines
    assert ident.orgs == [probe_person.ORG]
    assert probe_person.PROFILE in ident.profiles
    assert "User 1" not in ident.profiles and "addons21" not in ident.profiles
    assert probe_person.TELEMETRY_ID in ident.telemetry
    assert len(probe.keys) == 6 and set(probe.keys) <= set(ident.keys)


def test_each_install_key_is_the_one_its_own_code_makes(probe):
    """One rule: identity() asks the code that names each thing, never a copy of its hashing."""
    from app import instance_name, library_store, library_watch
    keys = set(scrub.read_identity().keys)
    assert path_utils.install_key() in keys
    assert instance_name.install_part() in keys
    for language in ("ja", "zh"):
        data_dir = path_utils.get_data_path(language)
        db = library_store.library_db_path(language, data_dir)
        assert library_store.library_key(data_dir) in keys and library_store.library_key(data_dir) in db
        assert library_watch.bell_key(db) in keys and library_watch.bell_key(db) in library_watch.bell_name(db, 0)


def test_connects_anki_profile_and_anki_miners_named_profile_are_read(probe):
    from app.connect import setup
    os.makedirs(os.path.dirname(setup.record_path()), exist_ok=True)
    with open(setup.record_path(), "w", encoding="utf-8") as f:
        json.dump({"anki_profile": "ゾーイ"}, f)
    with open(path_utils.get_settings_path(), "w", encoding="utf-8") as f:
        json.dump({"connect_anki_miner_profile": "Zoe Mining"}, f)
    assert {"ゾーイ", "Zoe Mining", probe_person.PROFILE} <= set(scrub.read_identity().profiles)
    with open(path_utils.get_settings_path(), "w", encoding="utf-8") as f:
        json.dump({"connect_anki_miner_profile": "Surasura"}, f)                     # Anki Miner's default: no one's
    assert "Surasura" not in scrub.read_identity().profiles


def test_a_source_that_fails_is_skipped_never_an_error(probe, monkeypatch):
    def broken():
        raise OSError("no network name")
    monkeypatch.setattr("socket.gethostname", broken)
    monkeypatch.setattr("app.path_utils.install_key", broken)
    monkeypatch.delenv("APPDATA")
    ident = scrub.read_identity()
    assert probe_person.ACCOUNT in ident.users and probe_person.MACHINE in ident.machines   # (COMPUTERNAME still)
    assert ident.profiles == []


def test_the_telemetry_id_is_read_never_made(tmp_path, monkeypatch):
    path = os.path.join(path_utils.persistent_root(), "telemetry_id.json")
    if os.path.exists(path):
        os.remove(path)
    assert scrub.read_identity().telemetry == []
    assert not os.path.exists(path)


def test_a_domain_account_names_the_domain_but_a_workgroup_doesnt(probe, monkeypatch):
    monkeypatch.setenv("USERDOMAIN", "PROBECORP")
    assert "PROBECORP" in scrub.read_identity().machines
    monkeypatch.setenv("USERDOMAIN", "WORKGROUP")
    assert "WORKGROUP" not in scrub.read_identity().machines


def test_macos_and_linux_homes_and_names(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", "/home/zoeprobe")
    monkeypatch.setenv("USER", "zoeprobe")
    ident = scrub.read_identity()
    assert "/home/zoeprobe" in ident.homes and "zoeprobe" in ident.users
    assert ident.scrub("/home/zoeprobe/.local/share/Anki2") == "/home/<you>/.local/share/Anki2"
    assert scrub.Identity(homes=["/Users/zoeprobe"]).scrub("/Users/zoeprobe/x") == "/Users/<you>/x"


def test_the_identity_is_worked_out_once_on_a_worker_and_cached(probe):
    assert not scrub.ready()
    t = scrub.prepare()
    t.join(30)
    assert scrub.ready() and scrub.prepare() is None
    assert scrub.identity() is scrub.identity()


# --- pictures: shown() ---------------------------------------------------------------------------------------------- #
def test_shown_scrubs_only_in_picture_mode_and_never_waits_for_the_identity(probe, monkeypatch):
    path = probe.home + r"\Videos"
    assert scrub.shown(path) == path                                 # no picture being taken
    with scrub.picture_mode() as ready:
        assert ready is False and scrub.shown(path) == path        # not worked out yet: never read here
    assert not scrub.ready()
    scrub.identity()
    with scrub.picture_mode() as ready:
        assert ready is True and probe_person.FOLDER not in scrub.shown(path) and "<you>" in scrub.shown(path)
    assert scrub.shown(path) == path


def test_picture_mode_ends_even_when_the_grab_raises(probe):
    scrub.identity()
    with pytest.raises(RuntimeError):
        with scrub.picture_mode():
            raise RuntimeError("grab failed")
    assert scrub.shown(probe.home) == probe.home


# --- reading an entry as text -------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw, language, text", [
    ("文化祭まで\r\nあと三日".encode("utf-8"), "ja", "文化祭まで\r\nあと三日"),            # CRLF kept
    (codecs.BOM_UTF8 + "腑に落ちた".encode("utf-8"), "ja", "腑に落ちた"),
    (codecs.BOM_UTF16_LE + "夜市".encode("utf-16-le"), "zh", "夜市"),
    ("error at C:\\x".encode("utf-16-le"), None, "error at C:\\x"),                  # UTF-16 without a BOM
    ("文化祭の準備".encode("cp932"), "ja", "文化祭の準備"),
    ("牛肉麵非常有名".encode("gb18030"), "zh", "牛肉麵非常有名"),
])
def test_an_entry_is_read_as_text_in_its_own_encoding(raw, language, text):
    assert scrub.decode(raw, language) == text


@pytest.mark.parametrize("raw", [b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", b"SQLite format 3\x00\x10\x00",
                                 bytes(range(256)), b"abc\x00"])
def test_bytes_that_arent_text_read_as_none(raw):
    assert scrub.decode(raw, "ja") is None


# --- the guard -------------------------------------------------------------------------------------------------- #
def _png(text=None):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    if text:
        out += chunk(b"tEXt", b"Comment\x00" + text.encode("latin-1"))
        out += chunk(b"zTXt", b"Source\x00\x00" + zlib.compress(text.encode("latin-1")))
    return out + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")) + chunk(b"IEND", b"")


def _zip(tmp_path, entries):
    path = tmp_path / "check.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return str(path)


def test_the_guard_passes_a_clean_zip(tmp_path):
    ident = person()
    path = _zip(tmp_path, {"logs/cli.log": "C:\\Users\\<you>\\Videos 文化祭\n".encode("utf-8"),
                           "reports/a/picture-1.png": _png(), "reports/a/picture-2.png": _png("made by Qt")})
    assert scrub.leaks(path, ident) == []


@pytest.mark.parametrize("name, data", [
    ("logs/cli.log", r"C:\Users\Zoë Tanaka-Probe\x".encode("utf-8")),
    ("logs/cli-events.jsonl", json.dumps({"m": r"C:\Users\Zoë Tanaka-Probe"}).encode("ascii")),
    ("logs/arrivals.log", "ztanprobe".encode("utf-16-le")),
    ("logs/odd.log", b"\xff\xfe" + "DESKTOP-PROBE7".encode("utf-16-le")),
    ("logs/half.log", b"x" + "ztanprobe".encode("utf-16-le")),                       # UTF-16 at the odd byte
    ("logs/ztanprobe.log", b"nothing in it"),                                        # the entry's name
    ("reports/a/picture-1.png", _png("C:\\Users\\Zoë Tanaka-Probe".encode("utf-8").decode("latin-1"))),
    ("reports/a/picture-2.png", b"\x89PNG broken"),                                  # can't be checked
    ("results/x.db", b"SQLite format 3\x00 ztanprobe"),                              # not text: can't be checked
])
def test_the_guard_names_each_entry_that_may_name_you(tmp_path, name, data):
    ident = person()
    path = _zip(tmp_path, {"about.txt": b"version: 3.0.0\n", name: data})
    assert scrub.leaks(path, ident) == [name]


# --- every path hashed into a name is one identity() knows ---------------------------------------------------------- #
# `hexdigest()[:` in app/: the four install keys (identity() asks each) and every other short hash, with why it names
# no install (a hash of content, or one per file, never logged as an install's code)
IDENTITY_KEYS = {("app/path_utils.py", "_install_key"), ("app/library_store.py", "library_key"),
                 ("app/library_watch.py", "bell_key"), ("app/instance_name.py", "install_part")}
NOT_AN_INSTALL = {
    ("app/analyzer.py", "_template_fingerprint"): "the two report templates' bytes",
    ("app/connect/fit_check.py", "version"): "one video's pairing record (its subtitle's size, time and sha256 with "
                                             "its path): one per video, kept in a job's pick, which no zip takes",
    ("app/connect/lineup.py", "spot_key"): "one subtitle's bytes with its audio's size and time: one per pair, kept "
                                          "in the spot-check's record and its run folder's name",
    ("app/connect/runner.py", "part_book"): "one EPUB's path: the folder of that book's copy, one per book, never "
                                          "one install's code",
    ("app/connect/sentence_audio.py", "clip_name"): "a sentence clip's audio bytes: its name in Anki's media, one "
                                                    "per clip, never a path or one install's code",
    ("app/connect/media_names.py", "fingerprint"): "a subtitle line's words",
    ("app/connect/media_names.py", "line_name"): "a line's key, times and fingerprint",
    ("app/library_store.py", "line_fingerprint"): "a subtitle line's words",
    ("app/library_store.py", "_store_split_book"): "one split book's folder and name inside the library (its rel "
                                                   "key, never an absolute path): its joined file's name, one per "
                                                   "book, never one install's code",
    ("app/names.py", "stamp_of"): "the name tables' content",
    ("app/plan_rules.py", "file_digest"): "one file's path with its stat: one per file, never one install's code",
    ("app/services/automation.py", "shows"): "the backlog record's content",
    ("app/services/covers.py", "keep_user_bytes"): "a cover picture's bytes",
    ("app/services/needs.py", "_digest"): "a card list's values",
    ("app/token_index.py", "_digest"): "a JSON value's content",
}


def _short_hashes():
    found = set()
    for folder, _dirs, files in os.walk(os.path.join(ROOT, "app")):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            func = None
            with open(path, encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"\s*def (\w+)", line)
                    if m:
                        func = m.group(1)
                    if "hexdigest()[:" in line:
                        found.add((rel, func))
    return found


def test_every_short_hash_in_the_app_is_an_install_key_identity_knows_or_hashes_no_install():
    found = _short_hashes()
    unknown = found - IDENTITY_KEYS - set(NOT_AN_INSTALL)
    assert not unknown, f"a new short hash: if it hashes a path, scrub.identity() asks it; else say why: {unknown}"
    assert IDENTITY_KEYS <= found                                    # (each still made where identity() asks)


# --- what the mutants asked for (one rule, one test) ------------------------------------------------------------- #
@pytest.mark.parametrize("sep", [r"\x5c", r"\u005c", "%2F", "%5C", r"\\", r"\\\\"])
def test_a_home_written_with_escaped_separators_loses_its_name(sep):
    ident = person(users=[])
    out = ident.scrub(sep.join(["C:", "Users", "Zoë Tanaka-Probe", "Videos"]))
    assert out == sep.join(["C:", "Users", "<you>", "Videos"])


def test_a_home_inside_another_homes_path_loses_both_names():
    """A test root (or a roaming profile) under a real home: the kept parent is scrubbed in its turn."""
    ident = scrub.Identity(homes=[r"C:\Users\michaelx", r"C:\Users\michaelx\Temp\Users\Zoë Tanaka-Probe"])
    assert ident.scrub(r"C:\Users\michaelx\Temp\Users\Zoë Tanaka-Probe\a.srt") == r"C:\Users\<you>\Temp\Users\<you>\a.srt"


def test_a_profile_written_with_upper_case_hex_escapes_still_goes():
    ident = scrub.Identity(profiles=["Zoë Anki"])
    assert ident.scrub('"Zo\\u00EB Anki" "Zo\\xEB Anki"') == '"<anki profile 1>" "<anki profile 1>"'
    assert ident.scrub("Zo%C3%AB%20Anki and Zo%c3%ab%20Anki") == "<anki profile 1> and <anki profile 1>"


def test_a_name_in_utf16_inside_other_bytes_is_found_by_the_guard(tmp_path):
    """UTF-16 of 田中 has no NUL byte: only the raw UTF-16LE scan sees it among UTF-8 bytes."""
    ident = scrub.Identity(users=["田中"])
    for lead in (b"log 0", b"log 01"):
        path = _zip(tmp_path, {"logs/mixed.log": lead + "田中".encode("utf-16-le") + b"\n"})
        assert scrub.leaks(path, ident) == ["logs/mixed.log"]


@pytest.mark.parametrize("chunk", ["zTXt", "iTXt", "iTXt-z"])
def test_the_guard_reads_each_kind_of_png_text_chunk(tmp_path, chunk):
    def make(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    text = r"C:\Users\Zoë Tanaka-Probe".encode("utf-8")
    body = {"zTXt": b"Source\x00\x00" + zlib.compress(text),
            "iTXt": b"Source\x00\x00\x00ja\x00\x00" + text,
            "iTXt-z": b"Source\x00\x01\x00ja\x00\x00" + zlib.compress(text)}[chunk]
    png = (b"\x89PNG\r\n\x1a\n" + make(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
           + make(chunk[:4].encode("ascii"), body) + make(b"IEND", b""))
    assert scrub.leaks(_zip(tmp_path, {"reports/a/picture-1.png": png}), person()) == ["reports/a/picture-1.png"]


def _only(monkeypatch, tmp_path, **env):
    """No home source but `env` (and the test root's own folders)."""
    for name in ("USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "USERNAME", "USER",
                 "LOGNAME", "COMPUTERNAME", "USERDOMAIN", "OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("socket.gethostname", lambda: "")
    monkeypatch.setattr("platform.node", lambda: "")
    monkeypatch.setattr("getpass.getuser", lambda: "")
    monkeypatch.setattr(scrub, "_short", lambda path: None)
    for k, v in env.items():
        monkeypatch.setenv(k, v)


HOME = r"C:\Users\Zoë Tanaka-Probe"


@pytest.mark.parametrize("env", [dict(USERPROFILE=HOME), dict(HOME=HOME), dict(HOMEDRIVE="C:", HOMEPATH=HOME[2:]),
                                 dict(APPDATA=HOME + r"\AppData\Roaming"), dict(LOCALAPPDATA=HOME + r"\AppData\Local")])
def test_each_home_source_alone_names_the_home(monkeypatch, tmp_path, env):
    _only(monkeypatch, tmp_path, **env)
    ident = scrub.read_identity()
    assert any(os.path.normcase(h) == os.path.normcase(HOME) for h in ident.homes), ident.homes
    assert "Zoë Tanaka-Probe" in ident.users


def test_the_short_form_alone_comes_from_a_home(monkeypatch, tmp_path):
    _only(monkeypatch, tmp_path, USERPROFILE=HOME)
    monkeypatch.setattr(scrub, "_short", lambda path: r"C:\Users\ZOTANA~1" if path == HOME else None)
    assert r"C:\Users\ZOTANA~1" in scrub.read_identity().homes


@pytest.mark.parametrize("source", ["USERNAME", "USER", "LOGNAME", "getuser"])
def test_each_user_name_source_alone_names_the_user(monkeypatch, tmp_path, source):
    _only(monkeypatch, tmp_path)
    if source == "getuser":
        monkeypatch.setattr("getpass.getuser", lambda: "ztanprobe")
    else:
        monkeypatch.setenv(source, "ztanprobe")
    assert "ztanprobe" in scrub.read_identity().users


@pytest.mark.parametrize("source", ["COMPUTERNAME", "gethostname", "node", "dotted"])
def test_each_machine_name_source_alone_names_the_pc(monkeypatch, tmp_path, source):
    _only(monkeypatch, tmp_path)
    if source == "COMPUTERNAME":
        monkeypatch.setenv("COMPUTERNAME", "DESKTOP-PROBE7")
    elif source == "gethostname":
        monkeypatch.setattr("socket.gethostname", lambda: "DESKTOP-PROBE7")
    elif source == "node":
        monkeypatch.setattr("platform.node", lambda: "DESKTOP-PROBE7")
    else:
        monkeypatch.setattr("socket.gethostname", lambda: "desktop-probe7.probe.example")
    ident = scrub.read_identity()
    assert "desktop-probe7" in {m.casefold() for m in ident.machines}
    assert ident.scrub(r"\DESKTOP-PROBE7\share") == r"\<pc>\share"


@pytest.mark.parametrize("where", ["env", "folder"])
def test_onedrives_organisation_comes_from_its_variable_or_a_home_folder(monkeypatch, tmp_path, where):
    home = tmp_path / "Users" / "zoe"
    (home / "OneDrive - Probe Org").mkdir(parents=True)
    if where == "env":
        _only(monkeypatch, tmp_path, OneDriveCommercial=str(tmp_path / "x" / "OneDrive - Probe Org"))
    else:
        _only(monkeypatch, tmp_path, USERPROFILE=str(home))
    assert scrub.read_identity().orgs == ["Probe Org"]


def test_an_anki_folder_without_a_collection_is_no_profile(monkeypatch, tmp_path):
    roaming = tmp_path / "Roaming"
    for name, collection in (("家族", True), ("addons21", False), ("logs", False)):
        (roaming / "Anki2" / name).mkdir(parents=True)
        if collection:
            (roaming / "Anki2" / name / "collection.anki2").write_bytes(b"")
    _only(monkeypatch, tmp_path, APPDATA=str(roaming))
    assert scrub.read_identity().profiles == ["家族"]


@pytest.mark.parametrize("missing", ["install_key", "install_part", "library_key", "bell_key"])
def test_each_install_key_source_is_its_own(probe, monkeypatch, missing):
    """Each of the four is read on its own: the other three are still there when one fails."""
    from app import instance_name, library_store, library_watch
    owner = {"install_key": path_utils, "install_part": instance_name, "library_key": library_store,
             "bell_key": library_watch}[missing]
    want = set(scrub.read_identity().keys)

    def broken(*a):
        raise OSError("gone")
    monkeypatch.setattr(owner, missing, broken)
    got = set(scrub.read_identity().keys)
    assert got and got < want                   # (a library's key is in its bell's database name: both go with it)


@pytest.mark.parametrize("written, scrubbed", [
    (r"C:\Users\z\Videos", r"C:\Users\<you>\Videos"),
    (r"C:\\Users\\z\\Videos", r"C:\\Users\\<you>\\Videos"),                         # JSON: a run of backslashes
    ("C:%5CUsers%5Cz%5CVideos", "C:%5CUsers%5C<you>%5CVideos"),
    ("C:%5cUsers%5cz%5cVideos", "C:%5cUsers%5c<you>%5cVideos"),
    (r"C:\x5cUsers\x5cz\x5cVideos", r"C:\x5cUsers\x5c<you>\x5cVideos"),             # (written out, not escapes)
    (r"C:\u005cUsers\u005cz\u005cVideos", r"C:\u005cUsers\u005c<you>\u005cVideos"),
    ("C:%2FUsers%2Fz%2FVideos", "C:%2FUsers%2F<you>%2FVideos"),
    ("/c/Users/z/Videos", "/c/Users/<you>/Videos"),                                   # Git Bash
    ("file:///C:/Users/z/Videos", "file:///C:/Users/<you>/Videos"),
])
def test_a_one_letter_home_is_found_through_every_separator_and_drive_form(written, scrubbed):
    """A one-letter name is no user name of its own: only the home's pattern (its separators, its drive) finds it."""
    ident = scrub.Identity(homes=[r"C:\Users\z"])
    assert ident.users == []
    assert ident.scrub(written) == scrubbed
    assert ident.scrub("a z alone") == "a z alone"


def test_the_longer_home_is_tried_first_so_a_home_inside_another_is_found_whole():
    ident = scrub.Identity(homes=[r"C:\Users\michaelx", r"C:\Users\michaelx\Temp\Users\z"])
    assert ident.scrub(r"C:\Users\michaelx\Temp\Users\z\a.srt") == r"C:\Users\<you>\Temp\Users\<you>\a.srt"


def test_a_redirected_home_drive_is_a_home_beside_the_profile(monkeypatch, tmp_path):
    """HOMEDRIVE + HOMEPATH can name a network home apart from USERPROFILE: both are homes."""
    _only(monkeypatch, tmp_path, USERPROFILE=r"C:\Users\zlocal", HOMEDRIVE="H:", HOMEPATH=r"\Profiles\zoeprobe")
    homes = {os.path.normcase(h) for h in scrub.read_identity().homes}
    assert {os.path.normcase(r"C:\Users\zlocal"), os.path.normcase(r"H:\Profiles\zoeprobe")} <= homes


def test_a_new_test_root_is_a_new_identity(monkeypatch, tmp_path):
    """The cache is per test root: another root's install keys are other keys (a test never scrubs with the last's)."""
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path / "a"))
    first = scrub.identity()
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path / "b"))
    second = scrub.identity()
    assert second is not first and path_utils.install_key() in second.keys and set(first.keys) != set(second.keys)


@pytest.mark.parametrize("raw", [codecs.BOM_UTF8 + b"log\x00line", codecs.BOM_UTF16_LE + "a\x00b".encode("utf-16-le"),
                                 "ab\x00\x00cd".encode("utf-16-le")])
def test_text_holding_a_nul_is_not_text(raw):
    assert scrub.decode(raw, "ja") is None


def test_an_anki_profile_named_like_a_deck_word_keeps_the_deck_names():
    ident = scrub.Identity(profiles=["Japanese", "Mining"])
    decks = '"decks": ["Japanese::Core 2k", "日本語::Mining"]'
    assert ident.scrub(decks) == decks
    assert ident.scrub("Anki is open on the profile Japanese") == "Anki is open on the profile <anki profile 1>"


def test_a_folder_starting_with_an_escape_letter_is_no_escape():
    ident = scrub.Identity(users=["ed"])
    assert ident.scrub(r"D:\Anime\Ted Lasso\ep1.mkv and \\Ted") == r"D:\Anime\Ted Lasso\ep1.mkv and \\Ted"
    assert ident.scrub("x\\ted") == "x\\t<you>"                                     # \t (a tab's escape) is a gap


@pytest.mark.parametrize("written", ["mailto:zoe.probe%40example.co.jp", '"zoe.probe\\u0040example.co.jp"',
                                     "zoe.probe\\x40example.co.jp"])
def test_an_escaped_at_still_makes_an_email(written):
    out = person().scrub(written)
    assert "<email>" in out and "example" not in out


def test_an_entra_id_sid_is_a_sid():
    assert person().scrub(r"C:\$Recycle.Bin\S-1-12-1-1234567890-1234567890-1234567890-1234567890\x") == \
        r"C:\$Recycle.Bin\<sid>\x"


def test_onedrive_personal_is_no_organisation(monkeypatch, tmp_path):
    home = tmp_path / "Users" / "zoe"
    (home / "OneDrive - Personal").mkdir(parents=True)
    (home / "OneDrive - Probe Org").mkdir()
    _only(monkeypatch, tmp_path, USERPROFILE=str(home))
    assert scrub.read_identity().orgs == ["Probe Org"]


def test_a_picture_with_bytes_after_its_end_or_an_unknown_chunk_is_not_checked(tmp_path):
    png = _png()
    odd_chunk = struct.pack(">I", 3) + b"zzZz" + b"abc" + b"\x00" * 4
    for bad in (png + "C:\\Users\\Zoë".encode("utf-8"), png[:-12] + odd_chunk + png[-12:]):
        assert scrub.leaks(_zip(tmp_path, {"reports/a/picture-1.png": bad}), person()) == ["reports/a/picture-1.png"]


def test_png_text_alone_is_read(tmp_path):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
           + chunk(b"tEXt", b"Comment\x00ztanprobe") + chunk(b"IEND", b""))
    assert scrub.leaks(_zip(tmp_path, {"reports/a/picture-1.png": png}), person()) == ["reports/a/picture-1.png"]


def test_utf16_big_endian_without_a_bom_is_read_as_big_endian():
    assert scrub.decode("error at C:\\x".encode("utf-16-be")) == "error at C:\\x"


def test_picture_mode_never_uses_another_test_roots_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path / "a"))
    scrub.reset(person())
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path / "b"))
    assert not scrub.ready()
    with scrub.picture_mode():
        assert scrub.shown(r"C:\Users\Zoë Tanaka-Probe") == r"C:\Users\Zoë Tanaka-Probe"


def test_a_name_placeholder_is_never_a_hit_either():
    ident = scrub.Identity(users=["you"])
    assert scrub.name("anki-miner/you-run/x.json", ident) == "anki-miner/(you)-run/x.json"
    assert not ident.found("anki-miner/(you)-run/x.json") and ident.found("anki-miner/you-run/x.json")


def test_a_non_ascii_name_goes_even_beside_ascii_letters_or_digits():
    ident = scrub.Identity(users=["田中", "Zoë"])
    assert ident.scrub("田中2号 and Zoëlle, xZoë") == "<you>2号 and <you>lle, x<you>"


# --- round 2's survivors (the Haiku list) ------------------------------------------------------------------------ #
def test_a_home_given_with_a_trailing_separator_is_the_same_home():
    for home in (r"C:\Users\z" + "\\", "C:/Users/z/"):
        assert scrub.Identity(homes=[home]).scrub(r"C:\Users\z\Videos") == r"C:\Users\<you>\Videos"


def test_a_short_organisation_name_still_goes():
    assert scrub.Identity(orgs=["ACME"]).scrub(r"C:\Users\x\OneDrive - ACME\a") == r"C:\Users\x\OneDrive - <org>\a"


def test_a_short_name_with_one_letter_outside_ascii_has_its_lock_form():
    assert scrub.Identity(users=["Zoë"]).scrub("surasura-window-Zo_-1-0a1b2c3d4e5f") == \
        "surasura-window-<you>-1-0a1b2c3d4e5f"


def test_the_longest_string_is_tried_first():
    ident = scrub.Identity(users=["zoe"], machines=["zoe-pc"])
    assert ident.scrub(r"\\zoe-pc\share and zoe") == r"\\<pc>\share and <you>"


def test_a_short_home_folder_is_still_a_home(monkeypatch, tmp_path):
    _only(monkeypatch, tmp_path, USERPROFILE=r"D:\z")
    assert r"D:\z" in scrub.read_identity().homes


def test_a_picture_named_after_you_is_a_hit(tmp_path):
    assert scrub.leaks(_zip(tmp_path, {"reports/a/ztanprobe.png": _png()}), person()) == ["reports/a/ztanprobe.png"]

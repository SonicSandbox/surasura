"""The word lists service (W3.3 P10; n16: `app/services/word_lists.py`) — the Ignore list and the Blacklist read,
added to and taken from.

What a wrong answer would cost: a user's hand-edited list rewritten (a comment, a blank line, a line end or a byte of
another line changed); a Shift_JIS / GB18030 list turned into a file nothing reads; a list no encoding reads whole
rewritten from a guess (every word it held lost); a write with no copy of the list as it was, or a copy made after the
write; a word added twice; KnownWord.json's other entries touched when one IGNORED entry is taken out; a write while
another program holds the known-words lock.
"""
import codecs
import json
import os
import shutil

import pytest

from app import anki_sync, path_utils
from app.services import word_lists


@pytest.fixture(autouse=True)
def _fresh_session():
    """Each test is a session of its own: the one-backup-per-file rule starts again."""
    word_lists._BACKED_UP.clear()
    yield
    word_lists._BACKED_UP.clear()


def _path(kind="ignore", language="ja"):
    path = word_lists.list_path(kind, language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _put(raw, kind="ignore", language="ja"):
    path = _path(kind, language)
    with open(path, "wb") as f:
        f.write(raw)
    return path


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _trash(language="ja"):
    folder = os.path.join(path_utils.get_user_files_path(language), ".trash")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


# A hand-edited list as users keep them: a comment, a blank line, a line with a gloss after the word, trailing spaces.
LF_LIST = "# 無視する単語\n冒険\n\n食べる - to eat\n毎日  \nストレート\n"


# --- adding keeps every line it doesn't change ------------------------------------------------------------------ #
def test_add_to_an_lf_list_appends_and_keeps_every_other_byte():
    old = LF_LIST.encode("utf-8")
    path = _put(old)
    change = word_lists.add("ignore", "ja", ["準備", "危険"])
    assert change.error is None and change.done == ["準備", "危険"]
    assert _bytes(path) == old + "準備\n危険\n".encode("utf-8")


def test_add_to_a_crlf_list_writes_crlf_and_keeps_every_other_byte():
    old = LF_LIST.replace("\n", "\r\n").encode("utf-8")
    path = _put(old)
    word_lists.add("ignore", "ja", ["準備"])
    assert _bytes(path) == old + b"\xe6\xba\x96\xe5\x82\x99\r\n"


def test_add_after_a_last_line_with_no_line_end_ends_it_first():
    old = "冒険\r\n毎日".encode("utf-8")
    path = _put(old)
    word_lists.add("ignore", "ja", ["準備"])
    assert _bytes(path) == old + "\r\n準備\r\n".encode("utf-8")


def test_add_to_a_utf8_bom_list_keeps_the_bom_once():
    old = codecs.BOM_UTF8 + LF_LIST.encode("utf-8")
    path = _put(old)
    word_lists.add("ignore", "ja", ["準備"])
    assert _bytes(path) == old + "準備\n".encode("utf-8")
    assert _bytes(path).count(codecs.BOM_UTF8) == 1


def test_add_to_a_utf16_list_writes_utf16_with_its_one_bom():
    old = codecs.BOM_UTF16_LE + LF_LIST.replace("\n", "\r\n").encode("utf-16-le")
    path = _put(old)
    word_lists.add("ignore", "ja", ["準備"])
    assert _bytes(path) == old + "準備\r\n".encode("utf-16-le")
    assert word_lists.read("ignore", "ja").entries[-1] == ("準備", "list")


def test_add_to_a_cp932_list_writes_cp932():
    # Windows' "ANSI" for Japanese: 2.x's rule (path_utils.append_text) adds in the file's own encoding.
    old = LF_LIST.replace("\n", "\r\n").encode("cp932")
    assert path_utils._decoding(old, "ja")[1] == "cp932"            # the witness: it really is read as Shift_JIS
    path = _put(old)
    word_lists.add("ignore", "ja", ["準備"])
    assert _bytes(path) == old + "準備\r\n".encode("cp932")


def test_a_word_cp932_cant_hold_rewrites_the_list_in_utf8_and_loses_nothing():
    # 2.x's rule: 𠮟る has no Shift_JIS character, so the whole list goes to UTF-8 (its line ends kept), a copy first.
    old = LF_LIST.replace("\n", "\r\n").encode("cp932")
    path = _put(old)
    change = word_lists.add("ignore", "ja", ["𠮟る"])
    assert change.done == ["𠮟る"] and change.backup is not None
    assert _bytes(path) == (LF_LIST.replace("\n", "\r\n") + "𠮟る\r\n").encode("utf-8")
    assert _bytes(change.backup) == old


def test_add_to_a_gb18030_chinese_list_writes_gb18030():
    text = "# zh Blacklist\r\n东西\r\n学习\r\n"
    old = text.encode("gb18030")
    assert path_utils._decoding(old, "zh")[1] == "gb18030"
    path = _put(old, "blacklist", "zh")
    word_lists.add("blacklist", "zh", ["夜市"])
    assert _bytes(path) == old + "夜市\r\n".encode("gb18030")
    assert [e.word for e in word_lists.read("blacklist", "zh").entries] == ["东西", "学习", "夜市"]


def test_a_missing_list_is_made_on_the_first_add_with_its_header():
    path = word_lists.list_path("blacklist", "ja")
    assert not os.path.exists(path)
    assert word_lists.read("blacklist", "ja").entries == []
    change = word_lists.add("blacklist", "ja", ["冒険"])
    assert change.done == ["冒険"] and change.backup is None
    assert _bytes(path) == "# ja Blacklist\n冒険\n".encode("utf-8")


def test_an_empty_list_takes_its_first_word_alone():
    path = _put(b"")
    word_lists.add("ignore", "ja", ["冒険"])
    assert _bytes(path) == "冒険\n".encode("utf-8")


def test_a_word_already_on_the_list_or_given_twice_is_added_once():
    old = LF_LIST.encode("utf-8")
    path = _put(old)
    change = word_lists.add("ignore", "ja", ["冒険", "準備", "準備", "食べる", " ", "# note"])
    # 冒険 is a line; 食べる is "食べる - to eat", read as the run reads it (cut at the first space or hyphen).
    assert change.done == ["準備"] and change.skipped == ["冒険", "食べる"]
    assert _bytes(path) == old + "準備\n".encode("utf-8")


def test_a_chinese_line_is_compared_whole_as_the_run_reads_it():
    # The run cuts a Japanese line at its first space (食べる - to eat is 食べる), never a Chinese one.
    old = "东西 dōngxi\n".encode("utf-8")
    path = _put(old, "blacklist", "zh")
    change = word_lists.add("blacklist", "zh", ["东西"])
    assert change.done == ["东西"]
    assert _bytes(path) == old + "东西\n".encode("utf-8")


def test_nothing_new_writes_nothing_and_makes_no_copy():
    old = LF_LIST.encode("utf-8")
    path = _put(old)
    before = os.stat(path).st_mtime_ns
    change = word_lists.add("ignore", "ja", ["冒険"])
    assert change.done == [] and change.skipped == ["冒険"] and change.backup is None
    assert os.stat(path).st_mtime_ns == before and _trash() == []


# --- removing keeps every other line ---------------------------------------------------------------------------- #
def test_remove_takes_exactly_that_line_and_keeps_every_other_byte():
    lines = ["# 無視する単語\r\n", "冒険\r\n", "\r\n", "食べる - to eat\r\n", "毎日  \r\n", "ストレート"]
    path = _put("".join(lines).encode("utf-8"))
    change = word_lists.remove("ignore", "ja", ["毎日"])            # read as written, trimmed
    assert change.done == ["毎日"] and change.skipped == []
    assert _bytes(path) == "".join(lines[:4] + lines[5:]).encode("utf-8")


def test_remove_takes_every_line_naming_the_word():
    path = _put("冒険\n毎日\n冒険\n".encode("utf-8"))
    change = word_lists.remove("ignore", "ja", ["冒険"])
    assert change.done == ["冒険"]
    assert _bytes(path) == "毎日\n".encode("utf-8")


def test_remove_from_a_cp932_list_keeps_it_cp932():
    old = "冒険\r\n毎日\r\n準備\r\n".encode("cp932")
    path = _put(old)
    word_lists.remove("ignore", "ja", ["毎日"])
    assert _bytes(path) == "冒険\r\n準備\r\n".encode("cp932")


def test_remove_from_a_utf16_list_keeps_its_bom_and_encoding():
    path = _put(codecs.BOM_UTF16_LE + "冒険\r\n毎日\r\n".encode("utf-16-le"))
    word_lists.remove("ignore", "ja", ["冒険"])
    assert _bytes(path) == codecs.BOM_UTF16_LE + "毎日\r\n".encode("utf-16-le")


def test_a_comment_is_never_removed_and_a_word_not_there_writes_nothing():
    old = LF_LIST.encode("utf-8")
    path = _put(old)
    change = word_lists.remove("ignore", "ja", ["# 無視する単語", "準備"])
    assert change.done == [] and change.skipped == ["# 無視する単語", "準備"]
    assert _bytes(path) == old and _trash() == []


def test_remove_from_a_missing_list_writes_nothing():
    change = word_lists.remove("blacklist", "zh", ["东西"])
    assert change.done == [] and change.skipped == ["东西"] and change.error is None
    assert not os.path.exists(word_lists.list_path("blacklist", "zh"))


# --- one dated copy per file per session, before the write ------------------------------------------------------ #
def test_the_first_write_keeps_one_verified_copy_and_the_second_none():
    old = LF_LIST.encode("utf-8")
    path = _put(old)
    first = word_lists.add("ignore", "ja", ["準備"])
    second = word_lists.remove("ignore", "ja", ["冒険"])
    assert first.backup is not None and second.backup is None
    assert _trash() == [os.path.basename(first.backup)]
    assert os.path.basename(first.backup).startswith("IgnoreList.") and first.backup.endswith(".txt")
    assert _bytes(first.backup) == old                              # the list as it was before any change


def test_each_list_gets_its_own_copy():
    _put("冒険\n".encode("utf-8"), "ignore")
    _put("毎日\n".encode("utf-8"), "blacklist")
    a = word_lists.add("ignore", "ja", ["準備"])
    b = word_lists.add("blacklist", "ja", ["準備"])
    assert a.backup and b.backup and len(_trash()) == 2


def test_the_copy_is_made_before_the_write(monkeypatch):
    old = LF_LIST.encode("utf-8")
    path = _put(old)
    seen = []
    real = anki_sync._atomic_write_bytes

    def write(p, data):
        seen.append((p, _trash(), _bytes(p)))                     # what is on disk as the write starts
        return real(p, data)
    monkeypatch.setattr(anki_sync, "_atomic_write_bytes", write)
    word_lists.add("ignore", "ja", ["準備"])
    assert len(seen) == 1
    p, trash, on_disk = seen[0]
    assert p == path and len(trash) == 1 and on_disk == old


def test_a_copy_that_fails_writes_nothing(monkeypatch):
    old = LF_LIST.encode("utf-8")
    path = _put(old)

    def fail(_path, move=False):
        raise OSError("the disk is full")
    monkeypatch.setattr(path_utils, "backup_to_trash", fail)
    change = word_lists.add("ignore", "ja", ["準備"])
    assert change.done == [] and "could not be backed up" in change.error and "the disk is full" in change.error
    assert _bytes(path) == old


def test_a_write_that_fails_leaves_the_list_as_it_was(monkeypatch):
    old = LF_LIST.encode("utf-8")
    path = _put(old)

    def fail(_p, _data):
        raise OSError("held open")
    monkeypatch.setattr(anki_sync, "_atomic_write_bytes", fail)
    change = word_lists.remove("ignore", "ja", ["冒険"])
    assert change.done == [] and "could not be written" in change.error
    assert _bytes(path) == old


# --- a list no encoding reads whole is never rewritten ---------------------------------------------------------- #
DAMAGED = "冒険\n毎日\n".encode("utf-8") + b"\xa0\x80\n"


def test_an_unreadable_list_is_never_written_and_says_why():
    assert path_utils._decoding(DAMAGED, "ja") == (None, None)    # the witness: no encoding reads it whole
    path = _put(DAMAGED)
    for change in (word_lists.add("ignore", "ja", ["準備"]), word_lists.remove("ignore", "ja", ["冒険"])):
        assert change.done == [] and "IgnoreList.txt can't be read" in change.error
    assert _bytes(path) == DAMAGED and _trash() == []


def test_an_unreadable_list_still_shows_its_words_and_says_it_cant_be_changed():
    _put(DAMAGED)
    listing = word_lists.read("ignore", "ja")
    assert listing.error and "IgnoreList.txt" in listing.error
    assert [e.word for e in listing.entries][:2] == ["冒険", "毎日"]


# --- reading ------------------------------------------------------------------------------------------------------ #
def test_read_gives_the_lines_as_written_in_order_comments_and_blanks_left_out():
    _put(LF_LIST.encode("utf-8"))
    listing = word_lists.read("ignore", "ja")
    assert listing.error is None
    assert listing.entries == [("冒険", "list"), ("食べる - to eat", "list"), ("毎日", "list"),
                               ("ストレート", "list")]


@pytest.fixture
def known_file(ja_resources_dir):
    """The real Migaku export (11,176 entries, 46 IGNORED) as this language's KnownWord.json."""
    dst = os.path.join(path_utils.get_user_files_path("ja"), "KnownWord.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(os.path.join(ja_resources_dir, "KnownWord.json"), dst)
    return dst


def _known_entries(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_the_ignore_list_shows_knownword_ignored_entries_and_the_blacklist_doesnt(known_file):
    _put("冒険\n".encode("utf-8"))
    entries = word_lists.read("ignore", "ja").entries
    assert entries[0] == ("冒険", "list")
    known = [e.word for e in entries if e.source == "known"]
    assert known[:3] == ["を", "は", "に"] and "良い" in known and len(known) == len(set(known))
    assert all(e.source == "list" for e in word_lists.read("blacklist", "ja").entries)


def test_removing_a_knownword_entry_takes_only_its_ignored_entries(known_file):
    before = _known_entries(known_file)
    change = word_lists.remove("ignore", "ja", ["良い"], source="known")
    assert change.done == ["良い"] and change.backup is not None
    after = _known_entries(known_file)
    # 良い is IGNORED and KNOWN in this file: only the IGNORED entry goes; every other entry and key is as it was.
    assert [w for w in before["words"] if not (w["dictForm"] == "良い" and w["knownStatus"] == "IGNORED")]         == after["words"]
    assert len(after["words"]) == len(before["words"]) - 1
    assert [w["knownStatus"] for w in after["words"] if w["dictForm"] == "良い"] == ["KNOWN"]
    assert {k: v for k, v in before.items() if k != "words"} == {k: v for k, v in after.items() if k != "words"}
    assert _known_entries(change.backup) == before
    assert "良い" not in [e.word for e in word_lists.read("ignore", "ja").entries if e.source == "known"]


def test_removing_a_knownword_entry_that_isnt_ignored_writes_nothing(known_file):
    old = _bytes(known_file)
    change = word_lists.remove("ignore", "ja", ["冒険"], source="known")
    assert change.done == [] and change.skipped == ["冒険"]
    assert _bytes(known_file) == old and _trash() == []


def test_a_name_is_never_removed_here():
    change = word_lists.remove("ignore", "ja", ["スドウ"], source="names")
    assert change.done == [] and "Ignore names" in change.error


# --- the known-words lock ------------------------------------------------------------------------------------------ #
def test_every_write_holds_the_known_words_lock(monkeypatch):
    from app import locks
    path = _put(LF_LIST.encode("utf-8"))
    held = []
    real = anki_sync._atomic_write_bytes

    def write(p, data):
        held.append(locks.held_here(anki_sync.known_lock_name("ja")))
        return real(p, data)
    monkeypatch.setattr(anki_sync, "_atomic_write_bytes", write)
    word_lists.add("ignore", "ja", ["準備"])
    word_lists.remove("ignore", "ja", ["準備"])
    assert held == [True, True]
    assert not locks.held_here(anki_sync.known_lock_name("ja"))     # released after
    assert _bytes(path) == LF_LIST.encode("utf-8")


def test_a_lock_held_by_another_program_changes_nothing(monkeypatch):
    old = LF_LIST.encode("utf-8")
    path = _put(old)
    monkeypatch.setattr(anki_sync, "hold_known_words",
                        lambda language, verb, wait=None: (None, ("Your known words are being updated by Sync.", {})))
    change = word_lists.add("ignore", "ja", ["準備"])
    assert change.busy and change.done == [] and "being updated" in change.error
    assert _bytes(path) == old and _trash() == []


def test_a_known_words_remove_holds_the_lock_and_is_refused_when_another_program_holds_it(known_file, monkeypatch):
    # KnownWord.json is the sync's file too: taking an IGNORED entry out is a read-modify-write that must hold
    # known-words-<lang>, and change nothing while another program (the Anki sync, Junban) holds it.
    from app import locks
    held = []
    real = anki_sync._atomic_write_json

    def write(p, data):
        held.append(locks.held_here(anki_sync.known_lock_name("ja")))
        return real(p, data)
    monkeypatch.setattr(anki_sync, "_atomic_write_json", write)
    assert word_lists.remove("ignore", "ja", ["良い"], source="known").done == ["良い"]
    assert held == [True] and not locks.held_here(anki_sync.known_lock_name("ja"))

    old, trash = _bytes(known_file), _trash()
    monkeypatch.setattr(anki_sync, "hold_known_words",
                        lambda language, verb, wait=None: (None, ("Your known words are being updated by Sync.", {})))
    change = word_lists.remove("ignore", "ja", ["を"], source="known")
    assert change.busy and change.done == [] and "being updated" in change.error
    assert _bytes(known_file) == old and _trash() == trash and held == [True]


def test_a_known_words_remove_whose_copy_fails_leaves_knownword_json_byte_identical(known_file, monkeypatch):
    old = _bytes(known_file)

    def fail(_path, move=False):
        raise OSError("the disk is full")
    monkeypatch.setattr(path_utils, "backup_to_trash", fail)
    change = word_lists.remove("ignore", "ja", ["良い"], source="known")
    assert change.done == [] and "could not be backed up" in change.error and "the disk is full" in change.error
    assert _bytes(known_file) == old and _trash() == []


def test_after_a_copy_that_failed_the_next_write_makes_one_before_it_writes(monkeypatch):
    # A copy refused once (antivirus, a cloud folder's lock) must not count as made: the next write in the session
    # copies the list first, and only then writes.
    old = LF_LIST.encode("utf-8")
    path = _put(old)
    real_backup = path_utils.backup_to_trash
    refused = []

    def flaky(p, move=False):
        if not refused:
            refused.append(p)
            raise OSError("held by another program")
        return real_backup(p, move=move)
    monkeypatch.setattr(path_utils, "backup_to_trash", flaky)
    seen = []
    real_write = anki_sync._atomic_write_bytes

    def write(p, data):
        seen.append((_trash(), _bytes(p)))                        # on disk as the write starts
        return real_write(p, data)
    monkeypatch.setattr(anki_sync, "_atomic_write_bytes", write)
    first = word_lists.add("ignore", "ja", ["準備"])
    assert first.done == [] and "could not be backed up" in first.error and seen == []
    second = word_lists.add("ignore", "ja", ["準備"])
    assert second.done == ["準備"] and second.backup is not None
    assert len(seen) == 1 and seen[0] == ([os.path.basename(second.backup)], old)
    assert _bytes(second.backup) == old


def test_the_list_is_read_again_under_the_lock(monkeypatch):
    # Edited by hand after the window read it: the write works on the file as it is when the lock is held.
    path = _put("冒険\n".encode("utf-8"))
    real = anki_sync.hold_known_words

    def hold(language, verb, wait=None):
        with open(path, "ab") as f:                              # the user's edit, just before the lock is had
            f.write("毎日\n".encode("utf-8"))
        return real(language, verb, wait)
    monkeypatch.setattr(anki_sync, "hold_known_words", hold)
    word_lists.add("ignore", "ja", ["準備"])
    assert _bytes(path) == "冒険\n毎日\n準備\n".encode("utf-8")


# --- pasted text ---------------------------------------------------------------------------------------------------- #
def test_words_in_gives_lemmas_shown_by_their_spelling(ja_resources_dir):
    with open(os.path.join(ja_resources_dir, "context_test.txt"), encoding="utf-8") as f:
        text = f.read().splitlines()[3] + "ケーキを食べた。"           # 彼は毎日冒険に出かけます。ケーキを食べた。
    found = word_lists.words_in(text, "ja")
    words = [c.word for c in found]
    assert "食べる" in words and "食べた" not in words               # the lemma, as the list counts it
    assert "冒険" in words and "出掛ける" in words
    assert words.index("冒険") < words.index("食べる")               # in the text's order
    assert "を" not in words and "は" not in words                   # grammar is no word the list offers
    assert len(words) == len(set(words))
    assert dict((c.word, c.spelling) for c in found)["出掛ける"] == "出かける"   # shown as the text spells it
    assert all(c.status == "new" for c in found)


def test_words_in_marks_listed_known_and_left_out(known_file):
    _put("冒険\n".encode("utf-8"), "ignore")
    _put("灯台\n".encode("utf-8"), "blacklist")
    found = {c.word: c.status for c in word_lists.words_in("冒険の準備で灯台の砂時計を見る。", "ja")}
    assert found["冒険"] == "listed"                                 # on this list (known too: the list wins)
    assert found["灯台"] == "left_out"                               # left out by the other list
    assert found["準備"] == "known"                                  # KNOWN in KnownWord.json
    assert found["砂時計"] == "new"
    blacklist = {c.word: c.status for c in word_lists.words_in("冒険の灯台", "ja", "blacklist")}
    assert blacklist == {"冒険": "known", "灯台": "listed"}         # the marks name the list asked about


def test_words_in_reads_chinese_as_the_library_cuts_it(zh_resources_dir):
    with open(os.path.join(zh_resources_dir, "chinese_text_1.txt"), encoding="utf-8") as f:
        line = next(l for l in f.read().splitlines() if "特朗普" in l)
    words = [c.word for c in word_lists.words_in(line, "zh", "blacklist")]
    assert "特朗普" in words and "台湾" in words
    assert "，" not in words and "：" not in words                    # punctuation is no word
    _put("台湾\n".encode("utf-8"), "blacklist", "zh")
    found = {c.word: c.status for c in word_lists.words_in(line, "zh", "blacklist")}
    assert found["台湾"] == "listed"


def test_words_in_an_empty_text_finds_nothing():
    assert word_lists.words_in("", "ja") == [] and word_lists.words_in("  \n", "zh") == []

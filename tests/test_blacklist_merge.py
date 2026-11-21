"""Blacklist.txt merged once into the Ignore list (Kotoba-WS2; Sonic 2026-11-19: one Ignore, everywhere —
`app/services/word_lists.py` `merge_blacklist`, `merge_blacklists`).

The two lists always did the same thing (every reader puts both into one ignore set), so the merge must change no word
any run reads. What a wrong answer would cost, in order:
  * a word lost — the Blacklist's words not all in the Ignore list after, or the Ignore list's own lines changed;
  * the Blacklist's own comments dropped, or the default header line carried in as noise;
  * a list written in another encoding or line end than it was (a Shift_JIS list 2.x reads turned to UTF-8 for no
    reason), or a word that encoding can't hold lost instead of the file going UTF-8;
  * a write with no dated, byte-identical copy first; the Blacklist lost instead of moved to `.trash`;
  * a second start (or one after a start cut off between the write and the move) adding the words again;
  * a write while another program holds the known-words lock, or of a list no encoding reads whole.

Real Japanese (the bundled default Blacklist's words, `tests/Test Resources/ja/context_test.txt`'s) and real Chinese
(`tests/Test Resources/zh/`). The autouse `_isolate_user_data_root` fixture puts `User Files/` in a temp root."""
import hashlib
import os

import pytest

from app import analyzer, anki_sync, path_utils
from app.services import first_run, word_lists

# The bundled ja default Blacklist (User Files/ja/Blacklist.txt as 2.x and 3.0 ship it): a BOM, the header, five words —
# one with a gloss the run cuts (そう-様態5 is そう), two the default Ignore list also holds (一人, 彼の).
JA_BLACKLIST = "﻿# ja Blacklist\n一人\n彼の\n為る\n其の\nそう-様態5\n"
JA_IGNORE = "﻿# Add words to ignore here (one per line)\n彼の\nんっ\nローズ\n丸で\n一人\nレム\n"
ZH_BLACKLIST = "# zh Blacklist\n# 人名\n小明 同學\n夜市\n臭豆腐\n"
ZH_IGNORE = "# Add words to ignore here (one per line)\n夜市\n"


def _path(name, language="ja"):
    folder = path_utils.get_user_files_path(language)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, name)


def _put(name, text, language="ja", encoding="utf-8", newline="\n"):
    path = _path(name, language)
    with open(path, "wb") as f:
        f.write(text.replace("\n", newline).encode(encoding))
    return path


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _trash(language="ja"):
    folder = os.path.join(path_utils.get_user_files_path(language), ".trash")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def _ignore_set(language):
    """The words every run ignores from the two lists, as `analyzer.load_ignore_set` reads them."""
    folder = path_utils.get_user_files_path(language)
    analyzer.SANITIZE_JA = language == "ja"
    words = set()
    for name in ("IgnoreList.txt", "Blacklist.txt"):
        words |= analyzer.load_simple_list(os.path.join(folder, name), "asis", language)
    return words


# --- nothing lost, nothing read differently ---------------------------------------------------------------- #
def test_japanese_blacklist_words_join_the_ignore_list_once_and_every_run_ignores_the_same_words():
    _put("IgnoreList.txt", JA_IGNORE)
    black = _put("Blacklist.txt", JA_BLACKLIST)
    old_black = _bytes(black)
    before = _ignore_set("ja")
    result = word_lists.merge_blacklist("ja")
    assert result["error"] is None
    assert result["added"] == 3 and result["present"] == 2          # 一人 and 彼の were on both: once
    assert _ignore_set("ja") == before                              # the run's set: not one word more or less
    text = _bytes(_path("IgnoreList.txt")).decode("utf-8-sig")
    assert text.startswith(JA_IGNORE.lstrip("﻿"))                  # the Ignore list's own lines untouched
    tail = text[len(JA_IGNORE) - 1:].splitlines()
    assert tail[0].startswith(word_lists.BLACKLIST_MARK)
    assert tail[1:] == ["為る", "其の", "そう-様態5"]                 # as typed, in order; the header not carried
    assert not os.path.exists(black)                                # moved, never deleted
    moved = [n for n in _trash() if n.startswith("Blacklist.")]
    assert len(moved) == 1 and _bytes(os.path.join(os.path.dirname(black), ".trash", moved[0])) == old_black


def test_chinese_lines_are_kept_as_typed_never_cut_at_a_space_and_comments_kept():
    _put("IgnoreList.txt", ZH_IGNORE, "zh")
    _put("Blacklist.txt", ZH_BLACKLIST, "zh")
    before = _ignore_set("zh")
    result = word_lists.merge_blacklist("zh")
    assert result["error"] is None and result["added"] == 2 and result["present"] == 1
    assert _ignore_set("zh") == before
    lines = _bytes(_path("IgnoreList.txt", "zh")).decode("utf-8").splitlines()
    assert lines[2].startswith(word_lists.BLACKLIST_MARK)
    assert lines[3:] == ["# 人名", "小明 同學", "臭豆腐"]          # the learner's comment kept; 夜市 once


def test_a_word_is_compared_as_the_run_reads_it_a_gloss_never_makes_a_second_line():
    # why: そう-様態5 is そう to every run (cut at the hyphen); the Ignore list's "そう - so" already names it
    _put("IgnoreList.txt", "# 無視\nそう - so\n")
    _put("Blacklist.txt", "そう-様態5\n為る\n")
    result = word_lists.merge_blacklist("ja")
    assert result["present"] == 1 and result["added"] == 1
    assert _bytes(_path("IgnoreList.txt")).decode("utf-8").splitlines()[-1] == "為る"


def test_the_ignore_list_is_backed_up_byte_for_byte_before_it_is_written():
    ignore = _put("IgnoreList.txt", JA_IGNORE)
    old = _bytes(ignore)
    _put("Blacklist.txt", JA_BLACKLIST)
    result = word_lists.merge_blacklist("ja")
    assert result["backup"] and _bytes(result["backup"]) == old


def test_a_shift_jis_crlf_ignore_list_keeps_its_encoding_and_line_ends():
    ignore = _put("IgnoreList.txt", "# 無視\r\n冒険\r\n", encoding="cp932")
    _put("Blacklist.txt", "# ja Blacklist\n食べる\n")
    word_lists.merge_blacklist("ja")
    raw = _bytes(ignore)
    assert raw.startswith("# 無視\r\n冒険\r\n".encode("cp932"))
    assert raw.endswith("食べる\r\n".encode("cp932")) and b"\n" not in raw.replace(b"\r\n", b"")


def test_a_word_the_ignore_lists_encoding_cannot_hold_turns_the_file_utf8_and_keeps_every_word():
    ignore = _put("IgnoreList.txt", "# 無視\n冒険\n", encoding="cp932")
    _put("Blacklist.txt", "𠮟る\n")                                   # 𠮟 has no Shift_JIS character
    word_lists.merge_blacklist("ja")
    assert _bytes(ignore).decode("utf-8").splitlines()[-1] == "𠮟る"
    assert "冒険" in _ignore_set("ja")


def test_a_utf16_blacklist_notepad_saved_is_merged_and_moved():
    # why: Windows' Notepad saves "Unicode" as UTF-16 with a BOM; its words are read and the file still moves (the
    # check before the move compares like with like, never raw bytes against a re-encoding)
    _put("IgnoreList.txt", JA_IGNORE)
    black = _path("Blacklist.txt")
    with open(black, "wb") as f:
        f.write("\ufeff# ja Blacklist\r\n為る\r\n其の\r\n".encode("utf-16-le"))
    result = word_lists.merge_blacklist("ja")
    assert result["error"] is None and result["added"] == 2
    assert not os.path.exists(black)
    assert _bytes(_path("IgnoreList.txt")).decode("utf-8-sig").splitlines()[-2:] == ["為る", "其の"]


def test_no_ignore_list_yet_one_is_made_with_its_header():
    _put("Blacklist.txt", JA_BLACKLIST)
    word_lists.merge_blacklist("ja")
    lines = _bytes(_path("IgnoreList.txt")).decode("utf-8").splitlines()
    assert lines[0] == word_lists.HEADERS["ignore"]
    assert lines[-5:] == ["一人", "彼の", "為る", "其の", "そう-様態5"]


def test_a_comment_only_blacklist_is_moved_and_the_ignore_list_is_untouched():
    ignore = _put("IgnoreList.txt", JA_IGNORE)
    old = _bytes(ignore)
    black = _put("Blacklist.txt", "# ja Blacklist\n\n")
    result = word_lists.merge_blacklist("ja")
    assert result["error"] is None and result["added"] == 0 and result["backup"] is None
    assert _bytes(ignore) == old
    assert not os.path.exists(black) and any(n.startswith("Blacklist.") for n in _trash())


# --- once ---------------------------------------------------------------------------------------------------- #
def test_a_second_start_changes_nothing():
    _put("IgnoreList.txt", JA_IGNORE)
    _put("Blacklist.txt", JA_BLACKLIST)
    word_lists.merge_blacklist("ja")
    after = _bytes(_path("IgnoreList.txt"))
    trash = _trash()
    result = word_lists.merge_blacklist("ja")
    assert result["listed"] == 0 and result["error"] is None
    assert _bytes(_path("IgnoreList.txt")) == after and _trash() == trash


def test_a_start_cut_off_between_the_write_and_the_move_adds_nothing_the_next_time(monkeypatch):
    # why: the words would be skipped as present anyway; the learner's own comment is what the marker keeps from
    # being written twice
    _put("IgnoreList.txt", JA_IGNORE)
    black = _put("Blacklist.txt", JA_BLACKLIST + "# 分け方の間違い\n")
    real = path_utils.backup_to_trash

    def no_move(path, move=False):
        if move:
            raise OSError("cut off")
        return real(path, move=move)

    monkeypatch.setattr(path_utils, "backup_to_trash", no_move)
    first = word_lists.merge_blacklist("ja")
    assert first["error"] and os.path.exists(black)
    written = _bytes(_path("IgnoreList.txt"))
    monkeypatch.setattr(path_utils, "backup_to_trash", real)
    again = word_lists.merge_blacklist("ja")
    assert again["error"] is None and again["added"] == 0
    assert _bytes(_path("IgnoreList.txt")) == written                 # the marker named this very file: nothing again
    assert written.decode("utf-8-sig").splitlines().count("# 分け方の間違い") == 1
    assert not os.path.exists(black)


def test_a_blacklist_saved_while_it_is_merged_is_never_moved_unread_and_merges_at_the_next_start(monkeypatch):
    # why: an editor saving the Blacklist during the start's merge: its new word must not go to .trash unmerged
    _put("IgnoreList.txt", JA_IGNORE)
    black = _put("Blacklist.txt", JA_BLACKLIST)
    real = anki_sync._atomic_write_bytes

    def save_meanwhile(path, data):
        real(path, data)
        _put("Blacklist.txt", JA_BLACKLIST + "冒険\n")             # the learner's editor, between the write and the move
    monkeypatch.setattr(anki_sync, "_atomic_write_bytes", save_meanwhile)
    first = word_lists.merge_blacklist("ja")
    assert first["error"] and os.path.exists(black) and not any(n.startswith("Blacklist.") for n in _trash())
    monkeypatch.setattr(anki_sync, "_atomic_write_bytes", real)
    again = word_lists.merge_blacklist("ja")
    assert again["error"] is None and again["added"] == 1 and not os.path.exists(black)
    lines = _bytes(_path("IgnoreList.txt")).decode("utf-8-sig").splitlines()
    assert lines[-1] == "冒険" and lines.count("為る") == 1


def test_a_blacklist_made_again_later_with_a_new_word_merges_only_that_word():
    _put("IgnoreList.txt", JA_IGNORE)
    _put("Blacklist.txt", JA_BLACKLIST)
    word_lists.merge_blacklist("ja")
    _put("Blacklist.txt", "# ja Blacklist\n冒険\n")                  # a 2.x start made it again; a word typed by hand
    result = word_lists.merge_blacklist("ja")
    assert result["added"] == 1
    lines = _bytes(_path("IgnoreList.txt")).decode("utf-8-sig").splitlines()
    assert lines[-1] == "冒険" and lines.count("為る") == 1
    assert sum(1 for line in lines if line.startswith(word_lists.BLACKLIST_MARK)) == 2


def test_the_marker_names_the_files_hash():
    _put("IgnoreList.txt", JA_IGNORE)
    black = _put("Blacklist.txt", JA_BLACKLIST)
    digest = hashlib.sha256(_bytes(black)).hexdigest()[:12]
    word_lists.merge_blacklist("ja")
    assert digest in _bytes(_path("IgnoreList.txt")).decode("utf-8-sig")


# --- refusals: nothing changed ----------------------------------------------------------------------------- #
def test_a_blacklist_no_encoding_reads_whole_is_left_for_the_user():
    ignore = _put("IgnoreList.txt", JA_IGNORE)
    old = _bytes(ignore)
    black = _path("Blacklist.txt")
    with open(black, "wb") as f:
        f.write(b"\xff\xfe\x00\xd8broken" + "冒険".encode("utf-8") + b"\x81")
    raw = _bytes(black)
    result = word_lists.merge_blacklist("ja")
    assert result["error"] and _bytes(ignore) == old and _bytes(black) == raw and _trash() == []


def test_an_ignore_list_no_encoding_reads_whole_is_never_written():
    ignore = _path("IgnoreList.txt")
    with open(ignore, "wb") as f:
        f.write(b"\xff\xfe\x00\xd8" + "冒険".encode("utf-8") + b"\x81")
    raw = _bytes(ignore)
    black = _put("Blacklist.txt", JA_BLACKLIST)
    result = word_lists.merge_blacklist("ja")
    assert result["error"] and _bytes(ignore) == raw and os.path.exists(black)


def test_a_backup_that_cannot_be_made_writes_nothing(monkeypatch):
    ignore = _put("IgnoreList.txt", JA_IGNORE)
    old = _bytes(ignore)
    black = _put("Blacklist.txt", JA_BLACKLIST)

    def fail(path, move=False):
        raise OSError("disk full")

    monkeypatch.setattr(path_utils, "backup_to_trash", fail)
    result = word_lists.merge_blacklist("ja")
    assert result["error"] and _bytes(ignore) == old and os.path.exists(black)


def test_a_write_that_fails_leaves_both_lists(monkeypatch):
    ignore = _put("IgnoreList.txt", JA_IGNORE)
    old = _bytes(ignore)
    black = _put("Blacklist.txt", JA_BLACKLIST)

    def fail(path, data):
        raise OSError("read-only")

    monkeypatch.setattr(anki_sync, "_atomic_write_bytes", fail)
    result = word_lists.merge_blacklist("ja")
    assert result["error"] and _bytes(ignore) == old and os.path.exists(black)


def test_another_programs_known_words_lock_is_refused_and_nothing_changes(monkeypatch):
    ignore = _put("IgnoreList.txt", JA_IGNORE)
    old = _bytes(ignore)
    black = _put("Blacklist.txt", JA_BLACKLIST)
    monkeypatch.setattr(anki_sync, "hold_known_words",
                        lambda language, verb, wait=None: (None, ("Your known words are being updated.", {})))
    result = word_lists.merge_blacklist("ja")
    assert result["error"] and _bytes(ignore) == old and os.path.exists(black)


def test_no_blacklist_does_nothing_and_makes_no_ignore_list():
    result = word_lists.merge_blacklist("zh")
    assert result["listed"] == 0 and result["error"] is None
    assert not os.path.exists(_path("IgnoreList.txt", "zh"))


def test_merge_all_does_both_languages_and_one_failure_never_stops_the_other(monkeypatch):
    _put("Blacklist.txt", JA_BLACKLIST)
    _put("Blacklist.txt", ZH_BLACKLIST, "zh")
    real = word_lists.merge_blacklist

    def ja_breaks(language):
        if language == "ja":
            raise RuntimeError("boom")
        return real(language)

    monkeypatch.setattr(word_lists, "merge_blacklist", ja_breaks)
    out = word_lists.merge_blacklists()
    assert out["ja"]["error"] and out["zh"]["error"] is None and out["zh"]["added"] == 3


# --- the start runs it; a new library never makes the file again -------------------------------------------- #
def test_a_waiting_blacklist_makes_the_start_run_and_the_run_merges_it():
    library = path_utils.get_user_data_path()
    _put("Blacklist.txt", JA_BLACKLIST)
    assert "ja" in first_run.lists_waiting(library)
    st = first_run.state()
    out = first_run.run(st)
    assert out["blacklist"]["ja"]["added"] == 5
    assert first_run.lists_waiting(library) == []


def test_a_new_library_makes_an_ignore_list_and_no_blacklist():
    path_utils.ensure_data_setup("ja")
    folder = path_utils.get_user_files_path("ja")
    assert os.path.isfile(os.path.join(folder, "IgnoreList.txt"))
    assert not os.path.exists(os.path.join(folder, "Blacklist.txt"))


def test_the_window_shows_the_ignore_and_known_lists_only():
    assert word_lists.KINDS == {"ignore": "IgnoreList.txt"}
    assert word_lists.LISTS == ("ignore", "known")

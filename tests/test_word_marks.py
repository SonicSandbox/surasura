"""Known and Ignore marked by hand (Kotoba-K: app/services/word_marks.py; Settings' Known tab).

What a wrong answer would cost: a user's known words or Ignore list damaged (another entry, a comment, a line end
changed; a write with no dated copy first; a file that can't be read rewritten from a guess), an Ignore that counts as
known (or a Known that doesn't), a mark that can't be taken back (the toggle's clear, the batch's Undo), an Anki
word taken out by a clear, the next Anki sync made a full one by every click (or kept a delta after a clear, so a
word Anki studied meanwhile never comes back), a Replace that drops what the learner said they know.
On the real Japanese and Chinese known-words files of Test Resources.
"""
import json
import os
import shutil

import pytest

from app import anki_sync, path_utils
from app.services import word_lists, word_marks

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
KNOWN_SAMPLE = {"ja": os.path.join(RES, "ja", "KnownWord.json"), "zh": os.path.join(RES, "zh", "KnownWords.json")}
# Words these files don't hold, as a learner would mark them: a name (Ignore), a word met in a show (Known)
NEW = {"ja": ("喫茶店", "ハルヒ", "山猫"), "zh": ("风筝", "鲁迅", "百草园")}   # (none in the samples' known words)


@pytest.fixture(autouse=True)
def _fresh_session():
    """Each test is a session of its own: one backup per file per session, and an empty undo stack."""
    word_lists._BACKED_UP.clear()
    word_marks._UNDO.clear()
    yield
    word_lists._BACKED_UP.clear()
    word_marks._UNDO.clear()


@pytest.fixture(params=["ja", "zh"])
def lang(request):
    """A user's real known words and an Ignore list with a comment, a gloss and CRLF line ends."""
    language = request.param
    uf = path_utils.get_user_files_path(language)
    os.makedirs(uf, exist_ok=True)
    shutil.copy(KNOWN_SAMPLE[language], os.path.join(uf, "KnownWord.json"))
    with open(os.path.join(uf, "IgnoreList.txt"), "wb") as f:
        f.write(("# 無視する単語\r\n冒険 - adventure\r\n\r\n" if language == "ja" else "# 忽略\r\n冒险\r\n\r\n")
                .encode("utf-8"))
    return language


def _known_path(language):
    return anki_sync._known_path(language)


def _ignore_path(language):
    return word_lists.list_path("ignore", language)


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _entries(language):
    return anki_sync._read_known_file(language)[1] or []


def _trash(language):
    folder = os.path.join(path_utils.get_user_files_path(language), ".trash")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


# --- Known and Ignore: two categories, kept apart ---------------------------------------------------------------- #
def test_known_counts_as_known_and_ignore_never_does(lang):
    word, name = NEW[lang][0], NEW[lang][1]
    before = anki_sync.count_known(lang)
    ignore_before = _bytes(_ignore_path(lang))
    r = word_marks.apply(lang, [(word, "known")])
    assert r.error is None and r.done == [(word, None, "known")]
    assert anki_sync.count_known(lang) == before + 1                   # the bar's figure, % known, Piyo's checks
    entry = [e for e in _entries(lang) if e.get("dictForm") == word]
    assert len(entry) == 1 and entry[0]["source"] == word_marks.MARKED_SOURCE and entry[0]["knownStatus"] == "KNOWN"
    assert _bytes(_ignore_path(lang)) == ignore_before                 # Known writes only the known words
    known_before = _bytes(_known_path(lang))
    r = word_marks.apply(lang, [(name, "ignore")])
    assert r.error is None and r.done == [(name, None, "ignore")]
    assert anki_sync.count_known(lang) == before + 1                   # an ignored word is never a known one
    assert _bytes(_known_path(lang)) == known_before
    assert _bytes(_ignore_path(lang)).endswith(f"{name}\r\n".encode("utf-8"))   # the list's own line ends
    assert word_marks.marks(lang)[word] == "known" and word_marks.marks(lang)[name] == "ignore"
    assert {word, name} <= word_marks.left_out(lang)


def test_the_ignore_list_keeps_every_byte_it_doesnt_change_and_a_clear_gives_it_back_whole(lang):
    old = _bytes(_ignore_path(lang))
    name = NEW[lang][1]
    word_marks.apply(lang, [(name, "ignore")])
    assert _bytes(_ignore_path(lang)).startswith(old)
    word_marks.apply(lang, [(name, None)])
    assert _bytes(_ignore_path(lang)) == old


def test_marking_one_clears_the_other_and_the_lit_side_again_clears_it(lang):
    word = NEW[lang][0]
    count = anki_sync.count_known(lang)
    word_marks.apply(lang, [(word, "ignore")])
    r = word_marks.apply(lang, [(word, "known")])                      # Ignore -> Known: the line goes
    assert r.done == [(word, "ignore", "known")] and word_marks.marks(lang)[word] == "known"
    assert word not in _bytes(_ignore_path(lang)).decode("utf-8")
    r = word_marks.apply(lang, [(word, "ignore")])                     # Known -> Ignore: the entry goes
    assert r.done == [(word, "known", "ignore")] and anki_sync.count_known(lang) == count
    assert not [e for e in _entries(lang) if e.get("dictForm") == word]
    r = word_marks.apply(lang, [(word, None)])
    assert r.done == [(word, "ignore", None)] and word not in word_marks.marks(lang)
    assert word_marks.apply(lang, [(word, None)]).done == []           # nothing marked: nothing written


def test_the_last_mark_of_a_word_in_one_call_wins(lang):
    word = NEW[lang][0]
    r = word_marks.apply(lang, [(word, "known"), (word, "ignore"), (word, "known")])
    assert r.done == [(word, None, "known")] and word_marks.marks(lang)[word] == "known"


def test_a_word_known_from_anki_is_never_written_again_nor_taken_out_by_a_clear(lang):
    anki = next(e["dictForm"] for e in _entries(lang) if anki_sync._is_known(e) and e.get("source") != "Surasura")
    old = _bytes(_known_path(lang))
    word_marks.apply(lang, [(anki, "known")])
    assert _bytes(_known_path(lang)) == old
    word_marks.apply(lang, [(anki, None)])
    assert _bytes(_known_path(lang)) == old and anki_sync.count_known(lang) > 0


def test_every_other_entry_and_key_of_the_known_words_file_is_kept(lang):
    before = json.loads(path_utils.read_text(_known_path(lang), lang))
    word = NEW[lang][2]
    word_marks.apply(lang, [(word, "known")])
    after = json.loads(path_utils.read_text(_known_path(lang), lang))
    assert {k: v for k, v in after.items() if k != "words"} == {k: v for k, v in before.items() if k != "words"}
    assert after["words"][:-1] == before["words"] and after["words"][-1]["dictForm"] == word
    word_marks.apply(lang, [(word, None)])
    assert json.loads(path_utils.read_text(_known_path(lang), lang))["words"] == before["words"]


# --- undo -------------------------------------------------------------------------------------------------------- #
def test_undo_puts_the_last_batch_back_as_it_was(lang):
    """*I know all of these*: one call for the title's words; its Undo puts each back, a word that was ignored too."""
    a, b, c = NEW[lang]
    word_marks.apply(lang, [(c, "ignore")])
    count = anki_sync.count_known(lang)
    r = word_marks.apply(lang, [(a, "known"), (b, "known"), (c, "known")])
    assert len(r.done) == 3 and anki_sync.count_known(lang) == count + 3
    assert word_marks.can_undo(lang)
    u = word_marks.undo(lang)
    assert u.error is None and sorted(w for w, _b, _a in u.done) == sorted([a, b, c])
    assert anki_sync.count_known(lang) == count and word_marks.marks(lang).get(c) == "ignore"
    assert a not in word_marks.marks(lang) and b not in word_marks.marks(lang)
    u = word_marks.undo(lang)                                          # the first apply, the Ignore
    assert c not in word_marks.marks(lang)
    assert word_marks.undo(lang).done == [] and not word_marks.can_undo(lang)


def test_a_batchs_undo_after_another_mark_undoes_the_batch_not_that_mark(lang):
    """A review's finding: *I know all of these*, then a ⊘ on another word — the batch's Undo puts back the batch (its
    own write, `undo_id`) and leaves the later Ignore as it is."""
    a, b, c = NEW[lang]
    batch = word_marks.apply(lang, [(a, "known"), (b, "known")])
    later = word_marks.apply(lang, [(c, "ignore")])
    assert batch.undo_id and later.undo_id and batch.undo_id != later.undo_id
    u = word_marks.undo(lang, batch.undo_id)
    assert sorted(w for w, _b, _a in u.done) == sorted([a, b])
    assert a not in word_marks.marks(lang) and b not in word_marks.marks(lang)
    assert word_marks.marks(lang)[c] == "ignore"
    assert word_marks.undo(lang, batch.undo_id).done == []                  # undone once: gone from the stack
    assert word_marks.undo(lang).done and c not in word_marks.marks(lang)    # the last write is still there


def test_a_glossed_ignore_line_reads_as_its_word(lang):
    """The run reads 冒険 - adventure as 冒険 (Japanese): the marks name it that way, so the numbers leave out 冒険."""
    if lang == "ja":
        assert word_marks.marks(lang).get("冒険") == "ignore" and "冒険 - adventure" not in word_marks.marks(lang)


def test_left_out_reads_nothing_when_neither_file_moved_since_the_plan(lang):
    word_marks.apply(lang, [(NEW[lang][0], "known")])
    newest = max(os.stat(p).st_mtime_ns for p in (_known_path(lang), _ignore_path(lang)))
    assert word_marks.left_out(lang, since_ns=newest + 1) == set()          # the plan's Generate read them
    assert NEW[lang][0] in word_marks.left_out(lang, since_ns=newest - 10 ** 9)
    assert NEW[lang][0] in word_marks.left_out(lang)


def test_a_refused_undo_stays_to_be_asked_again(lang, monkeypatch):
    word = NEW[lang][0]
    word_marks.apply(lang, [(word, "known")])
    with monkeypatch.context() as busy:
        busy.setattr(anki_sync, "hold_known_words", lambda language, verb, wait=None: (None, ("busy now", {})))
        r = word_marks.undo(lang)
        assert r.busy and r.error == "busy now" and word_marks.can_undo(lang)
    assert word_marks.undo(lang).done and word not in word_marks.marks(lang)


# --- the files' safety ------------------------------------------------------------------------------------------- #
def test_each_file_gets_a_dated_byte_verified_copy_before_its_first_write(lang):
    known_old, ignore_old = _bytes(_known_path(lang)), _bytes(_ignore_path(lang))
    r = word_marks.apply(lang, [(NEW[lang][0], "known"), (NEW[lang][1], "ignore")])
    trash = _trash(lang)
    assert len(r.backups) == 2 and len(trash) == 2
    folder = os.path.join(path_utils.get_user_files_path(lang), ".trash")
    copies = {name.split(".")[0]: _bytes(os.path.join(folder, name)) for name in trash}
    assert copies == {"KnownWord": known_old, "IgnoreList": ignore_old}
    word_marks.apply(lang, [(NEW[lang][2], "known")])                   # later writes: the session's copy holds
    assert len(_trash(lang)) == 2


def test_a_copy_that_fails_writes_nothing_at_all(lang, monkeypatch):
    known_old, ignore_old = _bytes(_known_path(lang)), _bytes(_ignore_path(lang))

    def broken(path, move=False):
        raise OSError("the disk is full")
    monkeypatch.setattr(path_utils, "backup_to_trash", broken)
    r = word_marks.apply(lang, [(NEW[lang][0], "known"), (NEW[lang][1], "ignore")])
    assert r.error and "backed up" in r.error and r.done == []
    assert _bytes(_known_path(lang)) == known_old and _bytes(_ignore_path(lang)) == ignore_old
    assert not word_marks.can_undo(lang)


def test_an_ignore_list_no_encoding_reads_is_never_written(lang):
    raw = "冒険\n毎日\n".encode("utf-8") + b"\xa0\x80\n"            # (test_services_word_lists' damaged list)
    if path_utils._decoding(raw, lang) != (None, None):
        pytest.skip(f"an encoding of {lang}'s reads these bytes")
    with open(_ignore_path(lang), "wb") as f:
        f.write(raw)
    known_old = _bytes(_known_path(lang))
    r = word_marks.apply(lang, [(NEW[lang][0], "known")])
    assert r.error and _bytes(_ignore_path(lang)) == raw and _bytes(_known_path(lang)) == known_old


def test_a_known_words_file_that_cant_be_read_is_never_written(lang):
    with open(_known_path(lang), "w", encoding="utf-8") as f:
        f.write('{"words": [ not json')
    raw = _bytes(_known_path(lang))
    r = word_marks.apply(lang, [(NEW[lang][0], "known")])
    assert r.error and _bytes(_known_path(lang)) == raw and r.done == []


def test_with_no_files_yet_the_first_marks_make_them(lang):
    os.remove(_known_path(lang))
    os.remove(_ignore_path(lang))
    r = word_marks.apply(lang, [(NEW[lang][0], "known"), (NEW[lang][1], "ignore")])
    assert r.error is None and len(r.done) == 2 and r.backups == []          # nothing to copy
    assert anki_sync.count_known(lang) == 1
    text = path_utils.read_text(_ignore_path(lang), lang)
    assert text.startswith("#") and NEW[lang][1] in text.splitlines()


def test_another_program_holding_the_known_words_writes_nothing(lang, monkeypatch):
    monkeypatch.setattr(anki_sync, "hold_known_words",
                        lambda language, verb, wait=None: (None, ("Your known words are being updated by Anki.", {})))
    old = _bytes(_known_path(lang))
    r = word_marks.apply(lang, [(NEW[lang][0], "known")])
    assert r.busy and r.done == [] and _bytes(_known_path(lang)) == old


@pytest.mark.parametrize("word", ["", "   ", "# a comment", "語" * 65, "改\n行"])
def test_a_word_no_list_could_hold_is_left_out(word):
    assert word_marks.clean([(word, "known")]) == []


def test_a_mark_that_isnt_one_is_refused():
    assert word_marks.apply("ja", [("家", "learned")]).error


# --- Anki's sync and Replace --------------------------------------------------------------------------------------- #
def test_a_mark_keeps_the_next_anki_sync_a_delta(lang):
    """The sync makes its next run a full one when KnownWord.json changed behind it (D4): a mark only adds or takes
    its own entries, so the sync's recorded signature moves with it — unless the sync was already behind."""
    anki_sync._save_state(lang, {"known_sig": anki_sync.known_signature(_known_path(lang)), "decks": ["Mining"]})
    word_marks.apply(lang, [(NEW[lang][0], "known")])
    assert anki_sync.load_state(lang)["known_sig"] == anki_sync.known_signature(_known_path(lang))
    anki_sync._save_state(lang, {"known_sig": "an older file", "decks": ["Mining"]})
    word_marks.apply(lang, [(NEW[lang][1], "known")])
    assert anki_sync.load_state(lang)["known_sig"] == "an older file"        # behind already: still behind


def test_a_cleared_known_mark_leaves_the_next_sync_a_full_one(lang):
    """A review's finding: a word marked Known, then studied in Anki (the delta sync appends nothing: it is known),
    then cleared — a sync that stayed a delta would never read that card again, and the word would stay off the list
    for good. Taking an entry out leaves the sync's signature behind: the next sync is a full one."""
    word = NEW[lang][0]
    word_marks.apply(lang, [(word, "known")])
    anki_sync._save_state(lang, {"known_sig": anki_sync.known_signature(_known_path(lang)), "decks": ["Mining"]})
    recorded = anki_sync.load_state(lang)["known_sig"]
    word_marks.apply(lang, [(word, None)])
    assert anki_sync.load_state(lang)["known_sig"] == recorded != anki_sync.known_signature(_known_path(lang))


def test_a_replace_from_anki_keeps_the_words_marked_known(lang):
    word = NEW[lang][0]
    word_marks.apply(lang, [(word, "known")])
    anki_words = [anki_sync._entry("新しい", 1, lang, "2026-11-15T10:00:00")]
    replaced, kept, _dropped = anki_sync.replaced_words(_known_path(lang), lang, list(anki_words))
    assert kept >= 1 and any(e.get("dictForm") == word and anki_sync._is_known(e) for e in replaced)


# --- Settings' word lists: the Known tab ---------------------------------------------------------------------------- #
def test_the_known_tab_lists_adds_and_takes_off_only_the_words_marked_known(lang):
    word, name = NEW[lang][0], NEW[lang][1]
    word_marks.apply(lang, [(name, "ignore")])
    change = word_lists.add(word_lists.KNOWN, lang, [word, word])
    assert change.done == [word] and change.error is None
    # Mado-LT 4: the Known tab is every known word, newest first — the one just marked on top, once
    listed = [e.word for e in word_lists.read(word_lists.KNOWN, lang).entries]
    assert listed[0] == word and listed.count(word) == 1 and name not in listed
    assert name in [e.word for e in word_lists.read("ignore", lang).entries]     # Ignore stays on the Ignore list
    change = word_lists.remove(word_lists.KNOWN, lang, [word, name])     # the Known tab's ✕: Known marks only
    assert change.done == [word] and change.skipped == [name]
    assert word not in [e.word for e in word_lists.read(word_lists.KNOWN, lang).entries]     # its mark gone
    assert name in [e.word for e in word_lists.read("ignore", lang).entries]     # its Ignore line stays


def test_an_ignore_list_that_cant_be_written_puts_the_known_words_back(lang, monkeypatch):
    """One write changes both files or neither: Known first, and an Ignore list the disk refuses puts KnownWord.json
    back byte for byte (a review's finding: a word moved Ignore -> Known lost its line)."""
    word, name = NEW[lang][0], NEW[lang][1]
    word_marks.apply(lang, [(word, "ignore")])
    known_old, ignore_old = _bytes(_known_path(lang)), _bytes(_ignore_path(lang))
    real = anki_sync._atomic_write_bytes

    def refuses_the_list(path, data):
        if os.path.basename(path) == "IgnoreList.txt":
            raise OSError("the file is held by another program")
        return real(path, data)
    monkeypatch.setattr(anki_sync, "_atomic_write_bytes", refuses_the_list)
    r = word_marks.apply(lang, [(word, "known"), (name, "ignore")])
    assert r.error and "Nothing was changed" in r.error and r.done == []
    assert _bytes(_known_path(lang)) == known_old and _bytes(_ignore_path(lang)) == ignore_old
    assert word_marks.marks(lang)[word] == "ignore"

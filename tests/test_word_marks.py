"""Known and Ignore marked by hand (Kotoba-K: app/services/word_marks.py; the journey's door route; Settings' Known tab).

What a wrong answer would cost: a user's known words or Ignore list damaged (another entry, a comment, a line end
changed; a write with no dated copy first; a file that can't be read rewritten from a guess), an Ignore that counts as
known (or a Known that doesn't), a mark that can't be taken back (the toggle's clear, the batch's Undo), an Anki
word taken out by a clear, the next Anki sync made a full one by every click, a Replace that drops what the learner
said they know, or a web page in the browser marking words through the door.
On the real Japanese and Chinese known-words files of Test Resources.
"""
import http.client
import json
import os
import shutil

import pytest

from app import anki_sync, door, path_utils
from app.services import word_lists, word_marks

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
KNOWN_SAMPLE = {"ja": os.path.join(RES, "ja", "KnownWord.json"), "zh": os.path.join(RES, "zh", "KnownWords.json")}
# Words these files don't hold, as a learner would mark them: a name (Ignore), a word met in a show (Known)
NEW = {"ja": ("喫茶店", "ハルヒ", "幽霊"), "zh": ("风筝", "鲁迅", "百草园")}


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


def test_a_refused_undo_stays_to_be_asked_again(lang, monkeypatch):
    word = NEW[lang][0]
    word_marks.apply(lang, [(word, "known")])
    monkeypatch.setattr(anki_sync, "hold_known_words", lambda language, verb, wait=None: (None, ("busy now", {})))
    r = word_marks.undo(lang)
    assert r.busy and r.error == "busy now" and word_marks.can_undo(lang)
    monkeypatch.undo()
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


def test_a_replace_from_anki_keeps_the_words_marked_known(lang):
    word = NEW[lang][0]
    word_marks.apply(lang, [(word, "known")])
    anki_words = [anki_sync._entry("新しい", 1, lang, "2026-11-15T10:00:00")]
    replaced, kept, _dropped = anki_sync.replaced_words(_known_path(lang), lang, list(anki_words))
    assert kept >= 1 and any(e.get("dictForm") == word and anki_sync._is_known(e) for e in replaced)


# --- the journey's door ------------------------------------------------------------------------------------------- #
@pytest.fixture
def opened(tmp_path):
    calls = []

    def mark_words(language, marks):
        calls.append((language, marks))
        return word_marks.apply(language, marks)
    d = door.Door({"words/mark": word_marks.door_route(mark_words)}, str(tmp_path)).start()
    d.calls = calls
    yield d
    d.stop()


def _post(d, body, origin="null", host=None):
    conn = http.client.HTTPConnection("127.0.0.1", d.port, timeout=10)
    headers = {"Host": host or f"127.0.0.1:{d.port}", "Content-Type": "text/plain", "Origin": origin}
    conn.request("POST", "/v1/words/mark", body=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers)
    r = conn.getresponse()
    out = r.status, json.loads(r.read().decode("utf-8"))
    conn.close()
    return out


def test_the_pages_marks_reach_the_word_lists_through_the_door(lang, opened):
    a, b, c = NEW[lang]
    status, answer = _post(opened, {"token": opened.token, "lang": lang, "marks": [
        {"word": a, "mark": "known"}, {"word": b, "mark": "ignore"}, {"word": c, "mark": "known"},
        {"word": c, "mark": ""}]})
    assert status == 200 and answer == {"ok": True, "done": 2}
    assert word_marks.marks(lang).get(a) == "known" and word_marks.marks(lang).get(b) == "ignore"
    assert c not in word_marks.marks(lang)


def test_a_web_page_or_a_wrong_token_marks_nothing(lang, opened):
    old = _bytes(_known_path(lang))
    body = {"token": opened.token, "lang": lang, "marks": [{"word": NEW[lang][0], "mark": "known"}]}
    assert _post(opened, body, origin="https://example.com")[0] == 403
    assert _post(opened, dict(body, token="wrong"))[0] == 403
    assert _post(opened, body, host="localhost:%d" % opened.port)[0] == 403
    assert opened.calls == [] and _bytes(_known_path(lang)) == old


@pytest.mark.parametrize("body", [{"lang": "fr", "marks": []}, {"lang": "ja", "marks": "冒険"},
                                  {"lang": "ja", "marks": [{"word": 3, "mark": "known"}]},
                                  {"lang": "ja", "marks": [{"word": "冒険", "mark": "learned"}]},
                                  {"lang": "ja", "marks": [{"word": "冒険", "mark": "known"}] * 501}])
def test_marks_the_door_cant_read_are_refused_and_let_go(opened, body):
    status, answer = _post(opened, dict(body, token=opened.token))
    assert status == 200 and answer["ok"] is False and answer["kind"] == "refused" and opened.calls == []


def test_a_write_that_couldnt_be_made_is_said_and_kept_by_the_page(lang, opened, monkeypatch):
    monkeypatch.setattr(anki_sync, "hold_known_words",
                        lambda language, verb, wait=None: (None, ("Your known words are being updated by Anki.", {})))
    answer = _post(opened, {"token": opened.token, "lang": lang, "marks": [{"word": NEW[lang][0], "mark": "known"}]})[1]
    assert answer == {"ok": False, "error": "Your known words are being updated by Anki.", "kind": "busy"}


# --- Settings' word lists: the Known tab ---------------------------------------------------------------------------- #
def test_the_known_tab_lists_adds_and_takes_off_only_the_words_marked_known(lang):
    word, name = NEW[lang][0], NEW[lang][1]
    word_marks.apply(lang, [(name, "ignore")])
    change = word_lists.add(word_lists.KNOWN, lang, [word, word])
    assert change.done == [word] and change.error is None
    assert [e.word for e in word_lists.read(word_lists.KNOWN, lang).entries] == [word]
    assert name in [e.word for e in word_lists.read("ignore", lang).entries]     # Ignore stays on the Ignore list
    change = word_lists.remove(word_lists.KNOWN, lang, [word, "冒険"])
    assert change.done == [word] and change.skipped == ["冒険"]
    assert word_lists.read(word_lists.KNOWN, lang).entries == []


# --- the journey page ---------------------------------------------------------------------------------------------- #
def _page():
    with open(os.path.join(os.path.dirname(RES), "..", "templates", "web_app.html"), encoding="utf-8") as f:
        return f.read()


def test_the_page_has_one_split_toggle_its_hotkeys_and_its_one_line_behind_a_question_mark():
    page = _page()
    assert "onclick=\"ignoreWord(" not in page and "function ignoreWord" not in page     # the browser-only Ignore went
    toggle = page[page.index("function markToggleHtml"):page.index("function wireMarkToggle")]
    assert "side('known', '✓ Known', 'k'" in toggle and "side('ignore', '⊘ Ignore', 'z'" in toggle
    assert 'class="mark-help"' in toggle and "aria-pressed" in toggle
    keys = page[page.index("// --- Smart Navigation ---"):]
    assert "const isKnown = e.key === 'k'" in keys and "'.mark-toggle .mk-known'" in keys


def test_the_page_asks_the_door_only_on_a_press_or_after_its_first_card():
    """The open stays as fast as today: nothing is sent while the page draws; waiting marks go after the first card is
    drawn, at a press, or as the tab comes back."""
    page = _page()
    load = page[page.index("window.addEventListener('load'"):]
    first = load.index("await fetchData();")
    assert load.index("setTimeout(doorFlush, 0)") > first
    import re
    callers = [page[max(0, m.start() - 160):m.start()] for m in re.finditer(r"(?<!function )doorFlush\(\)|setTimeout\(doorFlush", page)]
    # a press (markWord), the tab coming back (focus, visible), the rest of the queue, the first card — nothing else
    assert len(callers) == 5 and sum("markWord" in c or "saveMarks" in c for c in callers) >= 1
    assert "doorCall(" not in load[:first]
    flush = page[page.index("async function doorFlush"):page.index("window.addEventListener('focus'")]
    assert "doorCall('words/mark'" in flush and "ans.kind === 'refused'" in flush


def test_the_old_browser_only_ignores_are_carried_over_once():
    page = _page()
    carry = page[page.index("const markCarriedKey"):page.index("function markedOut")]
    assert "if (!localStorage.getItem(markCarriedKey))" in carry
    assert "markQueue.push({ word: w, mark: 'ignore' })" in carry and "localStorage.setItem(markCarriedKey, '1')" in carry


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

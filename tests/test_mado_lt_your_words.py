"""*Your words*' Known tab, read (Mado-LT 4: `word_lists.read("known", …)`, `word_lists.Entry`'s reading / origin /
created, `token_index.Store.readings`).

What a wrong answer would cost a learner: a word they know missing from the list, or shown twice; the newest words not
at the top (the order they became known is the point of the list); a word marked Still learning shown as known (or
dropped, so it can't be put back); a reading that is another word's, or Katakana where every other reading is
Hiragana; an import's words with no date sorted above the ones Surasura stamped; the window's list empty because one
entry is odd, or because the library has no token store yet.
"""
import json
import os
import shutil

import pytest

from app import anki_sync, path_utils, token_index
from app.services import word_lists, word_marks


def _known_path(language):
    path = os.path.join(path_utils.get_user_files_path(language), "KnownWord.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _write(language, words, wrap=True):
    path = _known_path(language)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"source": "test", "words": words} if wrap else words, f, ensure_ascii=False)
    return path


def _entry(word, source=None, created=None, reading="", status="KNOWN", has_card=0, **more):
    e = {"dictForm": word, "secondary": reading, "partOfSpeech": "", "language": "ja", "knownStatus": status,
         "hasCard": has_card, "tracked": 0, "created": created, "mod": 0, "isModern": 1}
    if source is not None:
        e["source"] = source
    e.update(more)
    return e


def _known(language="ja"):
    listing = word_lists.read(word_lists.KNOWN, language)
    assert listing.error is None, listing.error
    return listing.entries


# --- the order: newest first, by the date each word became known ---------------------------------------------------- #
def test_the_known_tab_is_every_known_word_once_newest_first_with_where_it_came_from(ja_resources_dir):
    """The Migaku export (11,582 entries, a few hundred of them not known: UNKNOWN, LEARNING, IGNORED), then what
    Surasura added after it — an Anki sync (ISO time), a word marked in Surasura, a 2.x Graduate — read as one list:
    each known word once, the dated ones newest first, the export's undated words after them, the file's newest first;
    a word known twice keeps the date and the origin of the first time it became known."""
    with open(os.path.join(ja_resources_dir, "KnownWord.json"), encoding="utf-8") as f:
        export = json.load(f)["words"]
    later = [_entry("風鈴", anki_sync.SOURCE, "2026-11-20T09:15:00", has_card=1),
             _entry("提灯", anki_sync.MARKED_SOURCE, "2026-11-21T18:02:11"),
             _entry("風鈴", anki_sync.MARKED_SOURCE, "2026-11-22T07:00:00"),        # known again later: still once
             _entry("灯台", anki_sync.GRADUATED_SOURCE, "2026-11-19T12:00:00"),
             _entry("看板", anki_sync.SOURCE, "2026-11-22T08:00:00", has_card=1)]    # in the export already
    _write("ja", export + later)
    rows = _known()
    words = [e.word for e in rows]
    assert len(words) == len(set(words))                                  # each once
    known_in_export = {e["dictForm"].strip() for e in export
                       if e.get("knownStatus") == "KNOWN" or e.get("hasCard") == 1}
    assert set(words) == known_in_export | {"風鈴", "提灯", "灯台", "看板"}            # every known word, no other
    assert "提灯" in words[:3] and "風鈴" in words[:3] and "灯台" in words[:3]   # this week's: on top
    assert words.index("提灯") < words.index("風鈴") < words.index("灯台")      # newest first
    top = {e.word: e for e in rows[:3]}
    assert top["風鈴"].origin == "anki" and top["風鈴"].source == "known"      # its first time: the Anki card
    assert top["提灯"].origin == "surasura" and top["灯台"].origin == "surasura"
    dated = [e.created for e in rows if e.created is not None]
    assert dated == sorted(dated, reverse=True)                            # the dated ones, newest first
    first_undated = next(i for i, e in enumerate(rows) if e.created is None)
    assert all(e.created is None for e in rows[first_undated:])            # no date: after every dated word
    assert rows[-1].word == export[0]["dictForm"]                          # ... the file's oldest last
    assert all(e.origin == "imported" for e in rows[3:])                   # Migaku's: no source of ours
    assert next(e for e in rows if e.word == "宝").reading == "たから"        # the entry's own reading
    old = next(e for e in rows if e.word == "看板")                        # known since the export: its place kept,
    assert old.origin == "imported" and words.index("看板") >= 3            # never moved up by a later card's sync


def test_a_chinese_learners_known_words_read_the_same_way(zh_resources_dir):
    """The Chinese export: every entry stamped in the same millisecond, so the file's order decides — newest (last)
    first; the pinyin is the entry's own."""
    shutil.copyfile(os.path.join(zh_resources_dir, "KnownWords.json"), _known_path("zh"))
    with open(_known_path("zh"), encoding="utf-8") as f:
        export = json.load(f)["words"]
    rows = _known("zh")
    assert [e.word for e in rows] == [e["dictForm"] for e in reversed(export)]
    assert rows[0].reading == export[-1]["secondary"] and rows[0].origin == "imported"


def test_migakus_millisecond_dates_and_the_syncs_iso_dates_sort_together():
    """Two formats in one file (`practice._created_ms`, the one parser): a Migaku word stamped later in
    milliseconds sorts above an older ISO one, and a date of 0 is no date."""
    _write("ja", [_entry("冒険", created="2026-01-05T10:00:00"),
                  _entry("毎日", created=1767600000000 + 86400000 * 30),             # ~ 2026-02-04, in ms
                  _entry("宝", created=0)])
    assert [e.word for e in _known()] == ["毎日", "冒険", "宝"]
    assert _known()[-1].created is None


# --- Still learning ------------------------------------------------------------------------------------------- #
def test_a_word_still_learning_stays_on_the_known_tab_as_learning_until_it_is_known_again():
    """Kyou-LR's rule (`word_marks` "learning"): the Anki entry is kept, turned not known — the Known tab shows the
    word as *learning* (its ○: the window can put it back), never as known, and never drops it. A newer card's sync
    makes it known again: then it reads known, dated from that card (the time it became known again)."""
    _write("ja", [_entry("看板", anki_sync.SOURCE, "2026-11-20T09:15:00", has_card=1),
                  _entry("提灯", anki_sync.SOURCE, "2026-11-21T09:15:00", has_card=1)])
    assert not word_marks.apply("ja", [("看板", "learning")]).error
    rows = {e.word: e for e in _known()}
    assert rows["看板"].source == "learning" and rows["提灯"].source == "known"
    path = _known_path("ja")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data["words"].append(_entry("看板", anki_sync.SOURCE, "2026-11-23T08:00:00", has_card=1))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    rows = {e.word: e for e in _known()}
    from app import practice
    assert rows["看板"].source == "known"
    assert rows["看板"].created == practice._created_ms("2026-11-23T08:00:00")   # known again: since the new card
    assert [e.word for e in _known()][0] == "看板"                              # ... so newest first


def test_a_word_known_only_by_its_surasura_mark_and_then_still_learning_leaves_the_known_tab():
    """Still learning on a word whose only entry was Surasura's own mark: the mark goes (`word_marks`), no entry is
    turned — the word is simply not known, and the next read has no row for it (the window keeps its ○ meanwhile)."""
    _write("ja", [_entry("提灯", anki_sync.MARKED_SOURCE, "2026-11-21T18:02:11")])
    assert not word_marks.apply("ja", [("提灯", "learning")]).error
    assert _known() == []


# --- empty states and odd files --------------------------------------------------------------------------------- #
def test_no_known_words_file_is_an_empty_list_and_no_error():
    assert not os.path.exists(_known_path("ja"))
    assert _known() == []


def test_an_unreadable_known_words_file_says_so_and_lists_nothing():
    with open(_known_path("ja"), "wb") as f:
        f.write(b"{ this is not json")
    listing = word_lists.read(word_lists.KNOWN, "ja")
    assert listing.entries == [] and listing.error


def test_odd_entries_are_skipped_and_never_empty_the_list():
    """A bare list (the old shape), a string where an entry should be, a blank word, an entry with no date or source:
    the good ones are listed, the rest skipped."""
    _write("ja", ["冒険", {"dictForm": "  ", "knownStatus": "KNOWN"}, {"knownStatus": "KNOWN"},
                  {"dictForm": "毎日", "knownStatus": "KNOWN"}, _entry("宝", status="IGNORED")], wrap=False)
    rows = _known()
    assert [(e.word, e.source, e.origin, e.created, e.reading) for e in rows] == [("毎日", "known", "imported", None,
                                                                                    "")]


# --- the reading: the entry's own, else the library's (the token store) ------------------------------------------ #
def _store(language, rows):
    store = token_index.open_store(language)
    store.conn.executemany("INSERT OR REPLACE INTO aggregate (lemma, reading, count) VALUES (?, ?, ?)", rows)
    store.conn.commit()
    store.close()


def test_a_word_whose_entry_has_no_reading_takes_the_one_the_library_uses_most_in_hiragana():
    """The sync writes `secondary` "": the token store's aggregate gives the reading the library uses the word with
    most (看板 read かんばん 12 times, カンパン once), in Hiragana as an entry's own reading is; an entry's own reading
    is never replaced; a word the library never met has none; a word in kana shows its own spelling's reading."""
    _store("ja", [("看板", "カンバン", 12), ("看板", "カンパン", 1), ("提灯", "チョウチン", 3), ("宝", "タカラ", 9),
                  ("冒険", "", 4)])
    _write("ja", [_entry("看板", anki_sync.SOURCE, "2026-11-20T09:15:00", has_card=1),
                  _entry("提灯", anki_sync.SOURCE, "2026-11-21T09:15:00", reading="ちょうちん", has_card=1),
                  _entry("冒険", anki_sync.SOURCE, "2026-11-22T09:15:00", has_card=1),
                  _entry("灯台", anki_sync.SOURCE, "2026-11-19T09:15:00", has_card=1)])
    rows = {e.word: e.reading for e in _known()}
    assert rows == {"看板": "かんばん", "提灯": "ちょうちん", "冒険": "", "灯台": ""}


def test_a_chinese_word_with_no_reading_takes_the_librarys_as_it_is():
    _store("zh", [("学习", "xué xí", 5)])
    _write("zh", [dict(_entry("学习", anki_sync.SOURCE, "2026-11-20T09:15:00", has_card=1), language="zh")])
    assert [(e.word, e.reading) for e in _known("zh")] == [("学习", "xué xí")]


def test_no_token_store_yet_leaves_the_readings_empty_and_the_list_whole():
    _write("ja", [_entry("看板", anki_sync.SOURCE, "2026-11-20T09:15:00", has_card=1)])
    assert not os.path.exists(token_index.store_path_for("ja"))
    assert [(e.word, e.reading) for e in _known()] == [("看板", "")]


def test_the_stores_readings_are_asked_a_chunk_at_a_time_and_pick_the_most_used(monkeypatch):
    """`Store.readings` over more lemmas than one query takes: every chunk asked, the most-used reading kept, an empty
    reading never picked, a lemma it doesn't hold absent."""
    monkeypatch.setattr(token_index, "READINGS_CHUNK", 2)
    _store("ja", [("看板", "カンバン", 12), ("看板", "カンパン", 1), ("提灯", "チョウチン", 3), ("宝", "タカラ", 9),
                  ("冒険", "", 4), ("冒険", "ボウケン", 2),
                  # (Mado-LT 5) the most-used reading after another, put in and sorted: picked by its count, never
                  # by the first row the query returns
                  ("上手", "ウワテ", 1), ("上手", "ジョウズ", 7)])
    store = token_index.open_reader("ja")
    try:
        found = store.readings(["看板", "提灯", "宝", "冒険", "灯台", "看板", "", "上手"])
    finally:
        store.close()
    assert found == {"看板": "カンバン", "提灯": "チョウチン", "宝": "タカラ", "冒険": "ボウケン", "上手": "ジョウズ"}


def test_the_ignore_tabs_entries_still_name_only_the_word_and_where_it_is_held():
    """Every other reader of `Entry` (the Ignore tab, its tests) is unchanged: the new fields default to None."""
    path = word_lists.list_path("ignore", "ja")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("冒険\n")
    entries = word_lists.read("ignore", "ja").entries
    assert entries == [word_lists.Entry("冒険", "list")] and entries[0][2:] == (None, None, None)

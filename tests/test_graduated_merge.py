"""S3.1 row 3.1.7 — GraduatedList.txt merged once into the known words (`app/graduated_merge.py`, SPEC D13, Q4-10).

KnownWord.json is the user's (CLAUDE.md §4), so what a wrong answer would cost, in order:
  * an entry the user had changed — an existing word rewritten, its IGNORED status turned KNOWN, the order moved;
  * a KnownWord.json that couldn't be read replaced by one built from the list alone;
  * a write with no dated, byte-identical copy kept first;
  * the list lost — it goes to `.trash` (never purged), only after the words are safely written;
  * a second start doing anything at all;
  * Replace (the Anki sync) dropping the merged words, which then turn into unknowns.

Real Japanese (`tests/Test Resources/ja/`: context_test.txt's words, a slice of the real Migaku KnownWord.json) and
real Chinese (`tests/Test Resources/zh/`: context_test.txt's words, KnownWords.json). The autouse
`_isolate_user_data_root` fixture puts `User Files/` in a temp root."""
import json
import os
import re
from unittest import mock

import pytest

from app import anki_sync, graduated_merge, locks, path_utils

HEADER = "# Words from graduated content (automatically added)\n"


def _folder(language):
    folder = path_utils.get_user_files_path(language)
    os.makedirs(folder, exist_ok=True)
    return folder


def _known_path(language):
    return os.path.join(_folder(language), "KnownWord.json")


def _list_path(language):
    return os.path.join(_folder(language), "GraduatedList.txt")


def _write_list(language, text, encoding="utf-8", newline="\n"):
    with open(_list_path(language), "wb") as f:
        f.write(text.replace("\n", newline).encode(encoding))


def _graduated(source, words):
    """One Graduate block, as content_importer_gui wrote it."""
    return f"\n# Source: {source} ({len(words)} words graduated)\n" + "".join(w + "\n" for w in words)


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _words(language):
    with open(_known_path(language), encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data["words"]


def _trash(language):
    trash = os.path.join(_folder(language), ".trash")
    return sorted(os.listdir(trash)) if os.path.isdir(trash) else []


def _snapshot(language):
    """Every file in User Files/<lang>/ and its .trash, with its bytes."""
    out = {}
    for where, _dirs, names in os.walk(_folder(language)):
        for name in names:
            path = os.path.join(where, name)
            out[os.path.relpath(path, _folder(language))] = _read_bytes(path)
    return out


@pytest.fixture
def ja_known(ja_resources_dir):
    """A slice of the real Migaku export: KNOWN, LEARNING, UNKNOWN and IGNORED entries, other top-level keys kept."""
    with open(os.path.join(ja_resources_dir, "KnownWord.json"), encoding="utf-8") as f:
        data = json.load(f)
    words = data["words"]
    picked = [w for w in words if w["knownStatus"] == "KNOWN"][:20]
    for status in ("LEARNING", "UNKNOWN", "IGNORED"):
        picked += [w for w in words if w["knownStatus"] == status][:3]
    data["words"] = picked
    with open(_known_path("ja"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


@pytest.fixture
def ja_words(ja_resources_dir):
    """Words of the real ja resource, none of them in the Migaku slice."""
    with open(os.path.join(ja_resources_dir, "context_test.txt"), encoding="utf-8") as f:
        text = f.read()
    words = ["冒険", "準備", "危険", "価値", "冒険家", "有名"]
    assert all(w in text for w in words)
    return words


@pytest.fixture
def zh_known(zh_resources_dir):
    with open(os.path.join(zh_resources_dir, "KnownWords.json"), encoding="utf-8") as f:
        data = json.load(f)
    with open(_known_path("zh"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


@pytest.fixture
def zh_words(zh_resources_dir):
    with open(os.path.join(zh_resources_dir, "context_test.txt"), encoding="utf-8") as f:
        text = f.read()
    words = ["冒险", "挑战", "勇敢", "坚强", "世界"]
    assert all(w in text for w in words)
    return words


# --- the merge ---------------------------------------------------------------------------------------------------------

def test_japanese_words_are_added_as_known_and_every_existing_entry_is_untouched(ja_known, ja_words):
    before = _read_bytes(_known_path("ja"))
    _write_list("ja", HEADER + _graduated("冒険/第1話.srt", ja_words[:3]) + _graduated("冒険/第2話.srt", ja_words[3:]))
    result = graduated_merge.merge("ja")
    assert result["error"] is None
    assert (result["listed"], result["added"], result["present"]) == (6, 6, 0)
    words = _words("ja")
    assert words[:len(ja_known["words"])] == ja_known["words"]          # nothing changed, nothing moved
    added = words[len(ja_known["words"]):]
    assert [w["dictForm"] for w in added] == ja_words
    for entry in added:
        assert entry["knownStatus"] == "KNOWN" and entry["hasCard"] == 0 and entry["source"] == "GraduatedList"
        assert entry["language"] == "ja" and "ankiNoteId" not in entry
        assert set(entry) == {"dictForm", "secondary", "partOfSpeech", "language", "knownStatus", "hasCard",
                              "tracked", "created", "mod", "isModern", "source"}      # anki_sync._entry's shape
    with open(_known_path("ja"), encoding="utf-8") as f:
        data = json.load(f)
    assert {k: v for k, v in data.items() if k != "words"} == {k: v for k, v in ja_known.items() if k != "words"}
    # The backup: dated, byte-identical to the file before; the list moved beside it.
    backup = os.path.join(_folder("ja"), ".trash", os.path.basename(result["backup"]))
    assert re.fullmatch(r"KnownWord\.\d{8}-\d{6}(-\d+)?\.json", os.path.basename(backup))
    assert _read_bytes(backup) == before
    assert not os.path.exists(_list_path("ja"))
    assert re.fullmatch(r"GraduatedList\.\d{8}-\d{6}(-\d+)?\.txt", os.path.basename(result["retired"]))
    assert os.path.isfile(result["retired"])
    assert anki_sync.count_known("ja") == len([w for w in ja_known["words"] if anki_sync._is_known(w)]) + 6


def test_chinese_words_are_added_as_known_as_the_list_spells_them(zh_known, zh_words):
    _write_list("zh", HEADER + _graduated("夜市.srt", zh_words) + "冒險\n")       # a Traditional line, kept as written
    result = graduated_merge.merge("zh")
    assert result["error"] is None and result["added"] == 6
    added = _words("zh")[len(zh_known["words"]):]
    assert [w["dictForm"] for w in added] == zh_words + ["冒險"]
    assert all(w["knownStatus"] == "KNOWN" and w["language"] == "zh" for w in added)
    assert _words("zh")[:len(zh_known["words"])] == zh_known["words"]


def test_unknown_and_learning_words_are_raised_known_ignored_and_known_ones_are_left_alone(ja_known):
    def pick(status):
        # A dictForm with no gloss to cut, and no card (a card makes it known already).
        return next(w for w in ja_known["words"] if w["knownStatus"] == status and w.get("hasCard") != 1
                    and not re.search(r"[-\s]", w["dictForm"]))
    by_status = {s: pick(s) for s in ("KNOWN", "LEARNING", "UNKNOWN", "IGNORED")}
    before = {s: dict(w) for s, w in by_status.items()}
    listed = [w["dictForm"] for w in by_status.values()] + ["冒険"]
    # The same word again, with spaces around: one entry, never a second.
    _write_list("ja", HEADER + _graduated("a.txt", listed) + "  冒険  \n")
    ignore = os.path.join(_folder("ja"), "IgnoreList.txt")
    black = os.path.join(_folder("ja"), "Blacklist.txt")
    for path, text in ((ignore, "# Add words to ignore here (one per line)\n為る\n"), (black, "# ja Blacklist\n其れ\n")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    lists_before = (_read_bytes(ignore), _read_bytes(black))
    result = graduated_merge.merge("ja")
    assert (result["added"], result["raised"], result["present"]) == (1, 2, 2)
    words = _words("ja")
    old = words[:len(ja_known["words"])]
    for status in ("LEARNING", "UNKNOWN"):
        raised = next(w for w in old if w["dictForm"] == before[status]["dictForm"])
        assert raised == dict(before[status], knownStatus="KNOWN", previousStatus=status,   # every other field kept
                              graduated=True)
    for status in ("KNOWN", "IGNORED"):
        assert next(w for w in old if w["dictForm"] == before[status]["dictForm"]) == before[status]
    untouched = [w for w in ja_known["words"] if w["dictForm"] not in (before["LEARNING"]["dictForm"],
                                                                      before["UNKNOWN"]["dictForm"])]
    assert [w for w in old if w["dictForm"] not in (before["LEARNING"]["dictForm"],
                                                    before["UNKNOWN"]["dictForm"])] == untouched
    assert [w["dictForm"] for w in words[len(ja_known["words"]):]] == ["冒険"]
    assert not any(w.get("knownStatus") == "IGNORED" and w["dictForm"] != before["IGNORED"]["dictForm"]
                   and w not in ja_known["words"] for w in words)
    assert (_read_bytes(ignore), _read_bytes(black)) == lists_before


def test_a_word_held_ignored_under_one_entry_is_never_raised_under_another(ja_known):
    learning = {"dictForm": "冒険", "secondary": "ぼうけん", "partOfSpeech": "", "language": "ja",
                "knownStatus": "LEARNING", "hasCard": 0, "tracked": 0, "created": 1, "mod": 1, "isModern": 1}
    ja_known["words"] += [learning, dict(learning, knownStatus="IGNORED")]
    with open(_known_path("ja"), "w", encoding="utf-8") as f:
        json.dump(ja_known, f, ensure_ascii=False, indent=2)
    before = _read_bytes(_known_path("ja"))
    _write_list("ja", HEADER + "冒険\n")
    result = graduated_merge.merge("ja")
    assert (result["raised"], result["present"], result["backup"]) == (0, 1, None)
    assert _read_bytes(_known_path("ja")) == before


def test_a_raise_whose_write_fails_leaves_every_entry_as_it_was(ja_known, monkeypatch):
    learning = next(w for w in ja_known["words"] if w["knownStatus"] == "LEARNING" and w.get("hasCard") != 1
                    and not re.search(r"[-\s]", w["dictForm"]))
    _write_list("ja", HEADER + learning["dictForm"] + "\n")
    before = _read_bytes(_known_path("ja"))
    monkeypatch.setattr(anki_sync, "_atomic_write_json", mock.Mock(side_effect=OSError("disk full")))
    result = graduated_merge.merge("ja")
    assert result["error"] and result["raised"] == 0
    assert _read_bytes(_known_path("ja")) == before and os.path.exists(_list_path("ja"))


def _hidden_by_the_list(language, monkeypatch):
    """Every word the list hid from a run, as the analyzer's ignore set read it (2.x's behaviour)."""
    from app import analyzer
    monkeypatch.setattr(analyzer, "SANITIZE_JA", language == "ja")     # as analyzer.main() sets it
    return analyzer.load_simple_list(_list_path(language), "asis", language)


def test_every_japanese_word_the_list_hid_is_known_after(ja_known, ja_words, monkeypatch):
    learning = next(w for w in ja_known["words"] if w["knownStatus"] == "LEARNING" and w.get("hasCard") != 1
                    and not re.search(r"[-\s]", w["dictForm"]))
    # Hiragana lines too: each also names the kanji word it is typed for (もとめる -> 求める), as the ignore set read it.
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words) + "冒険家-adventurer\nもとめる\nすばらしい\n"
                + learning["dictForm"] + "\n")
    hidden = _hidden_by_the_list("ja", monkeypatch)
    assert {"求める", "素晴らしい"} & hidden, "the ignore set names a hiragana line's kanji word"
    graduated_merge.merge("ja")
    known = anki_sync._known_keys(_words("ja"))
    assert hidden and {anki_sync._norm(w) for w in hidden} <= known


def test_every_chinese_word_the_list_hid_is_known_after(zh_known, zh_words, monkeypatch):
    _write_list("zh", HEADER + _graduated("夜市.srt", zh_words) + "冒險\n世界 各地\n")
    hidden = _hidden_by_the_list("zh", monkeypatch)
    graduated_merge.merge("zh")
    assert hidden and {anki_sync._norm(w) for w in hidden} <= anki_sync._known_keys(_words("zh"))


def test_a_second_start_changes_nothing(ja_known, ja_words):
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    graduated_merge.merge("ja")
    after = _snapshot("ja")
    again = graduated_merge.merge("ja")
    assert (again["listed"], again["added"], again["backup"], again["retired"], again["error"]) == (0, 0, None, None,
                                                                                                    None)
    assert _snapshot("ja") == after


def test_a_start_cut_off_between_the_write_and_the_move_adds_nothing_the_next_time(ja_known, ja_words, monkeypatch):
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    real = path_utils.backup_to_trash

    def no_move(path, move=False):
        if move:
            raise OSError("the list is open in Notepad")
        return real(path, move)

    monkeypatch.setattr(path_utils, "backup_to_trash", no_move)
    first = graduated_merge.merge("ja")
    assert first["added"] == 6 and first["error"] and os.path.exists(_list_path("ja"))
    written = _read_bytes(_known_path("ja"))
    monkeypatch.setattr(path_utils, "backup_to_trash", real)
    second = graduated_merge.merge("ja")
    assert (second["added"], second["present"], second["backup"], second["error"]) == (0, 6, None, None)
    assert _read_bytes(_known_path("ja")) == written
    assert not os.path.exists(_list_path("ja"))


@pytest.mark.parametrize("damaged", [
    b'{"words": [{"dictForm": "\xe5\x86\x92\xe9\x99\xba", "knownSt',     # cut off mid-write
    b'{"words": 5}',                                                     # another shape
    b"\xff\xfe\xfd not any encoding",                                    # no encoding reads it
])
def test_a_known_words_file_that_cannot_be_read_is_never_written(ja_words, damaged):
    with open(_known_path("ja"), "wb") as f:
        f.write(damaged)
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    before = _snapshot("ja")
    result = graduated_merge.merge("ja")
    assert result["error"] and result["added"] == 0
    assert _snapshot("ja") == before               # KnownWord.json, the list, no backup: all as they were


def test_a_backup_that_cannot_be_made_writes_nothing(ja_known, ja_words, monkeypatch):
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    before = _snapshot("ja")

    def refuse(path, move=False):
        raise OSError("the backup copy did not match the original")

    monkeypatch.setattr(path_utils, "backup_to_trash", refuse)
    result = graduated_merge.merge("ja")
    assert result["error"].startswith("Nothing was changed") and result["added"] == 0
    assert _snapshot("ja") == before


def test_a_write_that_fails_leaves_the_file_and_the_list(ja_known, ja_words, monkeypatch):
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    before = _read_bytes(_known_path("ja"))
    monkeypatch.setattr(anki_sync, "_atomic_write_json", mock.Mock(side_effect=OSError("disk full")))
    result = graduated_merge.merge("ja")
    assert result["error"] and result["added"] == 0
    assert _read_bytes(_known_path("ja")) == before and os.path.exists(_list_path("ja"))


def test_a_list_with_no_words_is_moved_to_trash_once_and_known_words_are_untouched(ja_known):
    raw = HEADER + "\n# Source: 冒険.txt (0 words graduated)\n\n"
    _write_list("ja", raw)
    before = _read_bytes(_known_path("ja"))
    result = graduated_merge.merge("ja")
    assert (result["listed"], result["added"], result["backup"], result["error"]) == (0, 0, None, None)
    assert _read_bytes(_known_path("ja")) == before
    assert not os.path.exists(_list_path("ja"))
    assert _trash("ja") == [os.path.basename(result["retired"])]
    with open(result["retired"], encoding="utf-8") as f:
        assert f.read() == raw
    assert graduated_merge.merge("ja")["retired"] is None and len(_trash("ja")) == 1


def test_no_list_does_nothing_and_never_makes_a_known_words_file():
    result = graduated_merge.merge("ja")
    assert (result["listed"], result["added"], result["retired"], result["error"]) == (0, 0, None, None)
    assert not os.path.exists(_known_path("ja")) and _trash("ja") == []


def test_no_known_words_file_yet_one_is_made_from_the_list(zh_words):
    _write_list("zh", HEADER + _graduated("夜市.srt", zh_words))
    result = graduated_merge.merge("zh")
    assert result["added"] == 5 and result["backup"] is None
    with open(_known_path("zh"), encoding="utf-8") as f:
        data = json.load(f)
    assert data["source"] == "GraduatedList" and [w["dictForm"] for w in data["words"]] == zh_words


def test_a_bare_list_known_words_file_stays_a_bare_list(ja_known, ja_words):
    with open(_known_path("ja"), "w", encoding="utf-8") as f:
        json.dump(ja_known["words"], f, ensure_ascii=False)
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words[:2]))
    graduated_merge.merge("ja")
    with open(_known_path("ja"), encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list) and data[:-2] == ja_known["words"]
    assert [w["dictForm"] for w in data[-2:]] == ja_words[:2]


def test_a_shift_jis_list_with_crlf_comments_and_a_gloss_is_read_as_the_ignore_set_read_it(ja_words):
    # Saved by Notepad in Windows' ANSI (CP932), CRLF; one line with a Migaku-style gloss, one blank, comments.
    text = HEADER + _graduated("冒険.txt", ja_words[:2]) + "冒険家-adventurer\n\n  有名  \n#価値\n"
    _write_list("ja", text, encoding="cp932", newline="\r\n")
    result = graduated_merge.merge("ja")
    assert [w["dictForm"] for w in _words("ja")] == ja_words[:2] + ["冒険家", "有名"]
    assert result["listed"] == 4


def test_a_chinese_line_is_never_cut_at_a_space():
    assert graduated_merge.list_words("# 注释\n世界 各地\n冒险-\n", "zh") == ["世界 各地", "冒险-"]
    assert graduated_merge.list_words("# 注釈\n世界 各地\n冒険-\n", "ja") == ["世界", "冒険"]


def test_a_damaged_list_is_left_for_the_user(ja_known):
    with open(_list_path("ja"), "wb") as f:
        f.write(HEADER.encode("utf-8") + b"\xe5\x86\x92\xff\xfe\n")
    before = _snapshot("ja")
    result = graduated_merge.merge("ja")
    assert result["error"] and _snapshot("ja") == before


def test_another_programs_known_words_write_is_waited_for_then_refused(ja_known, ja_words, monkeypatch):
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    before = _snapshot("ja")
    monkeypatch.setattr(anki_sync, "KNOWN_LOCK_WAIT", 0.3)
    held = locks.take(anki_sync.known_lock_name("ja"), "Anki known-words sync", owner=object())
    try:
        result = graduated_merge.merge("ja")
    finally:
        held.release()
    assert "Anki known-words sync" in result["error"] and _snapshot("ja") == before
    assert graduated_merge.merge("ja")["added"] == 6           # free again: merged


def test_the_lock_is_held_for_the_write(ja_known, ja_words, monkeypatch):
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    seen = []
    real = anki_sync._atomic_write_json
    monkeypatch.setattr(anki_sync, "_atomic_write_json",
                        lambda *a, **k: (seen.append(locks.held_in_process("known-words-ja")), real(*a, **k)))
    graduated_merge.merge("ja")
    assert seen == [graduated_merge.VERB]
    assert locks.held_in_process("known-words-ja") is None


def test_merge_all_does_both_languages_and_one_failure_never_stops_the_other(ja_known, ja_words, zh_words,
                                                                             monkeypatch):
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    _write_list("zh", HEADER + _graduated("夜市.srt", zh_words))
    results = graduated_merge.merge_all()
    assert (results["ja"]["added"], results["zh"]["added"]) == (6, 5)
    real = graduated_merge.merge
    monkeypatch.setattr(graduated_merge, "merge",
                        lambda lang: (_ for _ in ()).throw(RuntimeError("boom")) if lang == "ja" else real(lang))
    _write_list("zh", HEADER + _graduated("夜市.srt", ["夜市"]))
    results = graduated_merge.merge_all()
    assert "boom" in results["ja"]["error"] and results["zh"]["added"] == 1


# --- Replace keeps them -----------------------------------------------------------------------------------------------

def test_anki_replace_keeps_the_merged_words(ja_known, ja_words):
    from tests.test_anki_sync import URL, FakeCollection
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    graduated_merge.merge("ja")
    fake = FakeCollection([{"word": "危険"}, {"word": "素晴らしい"}])      # 危険 is on a card now as well
    with mock.patch("urllib.request.urlopen", fake):
        result = anki_sync.replace("ja", URL, ["TheBank"], [])
    assert result.error is None
    words = _words("ja")
    assert [w["dictForm"] for w in words if w.get("source") == "AnkiConnect"] == ["危険", "素晴らしい"]
    assert [w["dictForm"] for w in words if w.get("source") == "GraduatedList"] == [w for w in ja_words if w != "危険"]
    # Migaku's known / learning / unknown entries are gone; the words dismissed there (IGNORED) stay (W3.4-1)
    assert not any(w.get("source") not in ("AnkiConnect", "GraduatedList") and w["knownStatus"] != "IGNORED"
                   for w in words)
    assert result.kept_ignored == 3 and result.kept_graduated == 5


def test_the_replace_confirmations_total_after_counts_the_graduates_words_kept(ja_known, ja_words):
    # The dry run's "after" is the known total the write makes: Anki's words AND the past Graduates' words it keeps
    # (the Tk confirmation said "go from X to <Anki's count>", short by every kept word: its defect 2).
    from tests.test_anki_sync import URL, FakeCollection
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    graduated_merge.merge("ja")
    with mock.patch("urllib.request.urlopen", FakeCollection([{"word": "危険"}, {"word": "素晴らしい"}])):
        dry = anki_sync.replace("ja", URL, ["TheBank"], [], dry_run=True)
        assert (dry.added, dry.kept_graduated, dry.total_after) == (2, 5, 7)
        result = anki_sync.replace("ja", URL, ["TheBank"], [], expect=anki_sync.replace_numbers(dry))
    assert not result.changed and result.total_known == result.total_after == dry.total_after
    assert result.total_known == 2 + 5


def test_a_word_the_merge_raised_stays_known_through_anki_replace(ja_known):
    # A LEARNING word (here Migaku's) the list graduated is raised in place: Replace rebuilds the file from Anki, which
    # doesn't name it, and it stays known as the words the merge added do (D13), not dropped with Migaku's entries.
    from tests.test_anki_sync import URL, FakeCollection
    learning = next(w for w in ja_known["words"] if w["knownStatus"] == "LEARNING" and w.get("hasCard") != 1
                    and not re.search(r"[-\s]", w["dictForm"]))
    _write_list("ja", HEADER + _graduated("a.txt", [learning["dictForm"]]))
    assert graduated_merge.merge("ja")["raised"] == 1
    with mock.patch("urllib.request.urlopen", FakeCollection([{"word": "素晴らしい"}])):
        result = anki_sync.replace("ja", URL, ["TheBank"], [])
    assert result.error is None
    kept = [w for w in _words("ja") if w["dictForm"] == learning["dictForm"]]
    assert len(kept) == 1 and kept[0]["knownStatus"] == "KNOWN" and kept[0]["graduated"] is True


def test_a_replacer_naming_a_graduated_word_as_learning_writes_it_known(tmp_path):
    # A Jiten or Migaku import that names a graduated word as LEARNING writes it KNOWN (and marked); its other words
    # are left as the import says.
    path = tmp_path / "KnownWord.json"
    path.write_text(json.dumps({"words": [{"dictForm": "冒険", "knownStatus": "KNOWN", "source": "GraduatedList"}]},
                               ensure_ascii=False), encoding="utf-8")
    words = [{"dictForm": "冒険", "knownStatus": "LEARNING", "source": "Migaku"},
             {"dictForm": "準備", "knownStatus": "LEARNING", "source": "Migaku"}]
    assert anki_sync.kept_graduated(str(path), "ja", words) == []
    assert words[0] == {"dictForm": "冒険", "knownStatus": "KNOWN", "previousStatus": "LEARNING", "source": "Migaku",
                        "graduated": True}
    assert words[1] == {"dictForm": "準備", "knownStatus": "LEARNING", "source": "Migaku"}


def test_the_migaku_import_keeps_the_merged_words(ja_resources_dir, ja_words, tmp_path):
    import shutil
    from app.migaku_converter import convert_db_to_json
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    graduated_merge.merge("ja")
    db = tmp_path / "MigakuDb.db"                       # a copy: the resource is never opened in place
    shutil.copy2(os.path.join(ja_resources_dir, "MigakuDb.db"), db)
    assert convert_db_to_json(str(db), _known_path("ja"), language="ja") is True
    words = _words("ja")
    migaku = {anki_sync._norm(w["dictForm"]) for w in words if w.get("source") != "GraduatedList"}
    kept = [w["dictForm"] for w in words if w.get("source") == "GraduatedList"]
    assert kept == [w for w in ja_words if anki_sync._norm(w) not in migaku]
    assert all(w["knownStatus"] == "KNOWN" for w in words if w.get("source") == "GraduatedList")


def test_the_jiten_import_keeps_the_merged_words(ja_words):
    from app.jiten_converter import fetch_jiten_vocabulary
    _write_list("ja", HEADER + _graduated("冒険.txt", ja_words))
    graduated_merge.merge("ja")
    cards = [{"wordText": "危険", "state": 6, "cardId": 11, "reading": "きけん"},
             {"wordText": "旅", "state": 2, "cardId": 12, "reading": "たび"}]
    response = mock.MagicMock(status_code=200)
    response.json.return_value = cards
    with mock.patch("requests.get", return_value=response):
        assert fetch_jiten_vocabulary("key", _known_path("ja"), "ja") is True
    with open(_known_path("ja"), encoding="utf-8") as f:
        data = json.load(f)
    assert [w["dictForm"] for w in data["words"]] == ["危険", "旅"] + [w for w in ja_words if w != "危険"]
    assert data["statistics"]["totalWords"] == 2 + 5 and data["statistics"]["knownWords"] == 1 + 5

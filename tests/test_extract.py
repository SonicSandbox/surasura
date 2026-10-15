"""Extract, Qt-free (W3.4 row 2; `app/extract.py`): the File Importer's reading and splitting, moved as they are, run
in a child, with the port's fixes — the name cleaned, a taken name refused and `<name> 2` proposed (IK-1), an empty
extraction a failure, the new files added to the library through the store in the section chosen.

What a wrong answer would cost: a re-extraction under a used name overwriting library files or mixing two splits in one
show (the Tk window's `copytree(..., dirs_exist_ok=True)`), old rows (watched marks, Anki pairings) reattached to new
text, Put back left with no place; a name with `..` writing outside the library; "Success" for nothing; files dropped
into a section's folder behind the store's back, placed by the folder rule instead of the user's choice.

Real Japanese and Chinese text from `tests/Test Resources/`; every library is a real store in the test's root.
"""
import json
import os

import pytest

from app import extract, library_store as ls
from app.path_utils import get_data_path, get_user_files_path
from tests.test_library_store_support import library, write_manifest

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")


def _store_library(language):
    data_dir, user_files_dir, doc = library(language, shows=1, episodes=2, loose=0)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    return data_dir, user_files_dir


def _open(language):
    return ls.open_store(language, get_data_path(language), get_user_files_path(language))


def _paths(language, tier):
    store = _open(language)
    try:
        return [e["physical_path"] for _i, e, _a in store.ordered(tier)]
    finally:
        store.close()


def _text_file(tmp_path, language, name="本文.txt", times=6):
    src = os.path.join(RES, language, "chinese_text_1.txt" if language == "zh" else "context_test.txt")
    with open(src, encoding="utf-8") as f:
        text = f.read()
    path = tmp_path / name
    path.write_text(text * times, encoding="utf-8")
    return str(path)


def _snapshot(root):
    out = {}
    for where, _dirs, files in os.walk(root):
        for n in files:
            p = os.path.join(where, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = f.read()
    return out


# --- the name --------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("typed, cleaned", [
    ("第1巻", "第1巻"), ("  旅の記録  ", "旅の記録"), ("a/b\\c", "a_b_c"), ("第1巻: 旅?", "第1巻_ 旅_"),
    ("..", None), ("../..", None), ("...", None), ("", None), ("CON", None), ("nul.txt", None), ("本.", "本"),
])
def test_an_output_name_is_cleaned_or_refused(typed, cleaned):
    assert extract.clean_name(typed) == cleaned


def test_a_name_with_dots_and_separators_never_writes_outside_processed(tmp_path):
    src = _text_file(tmp_path, "ja")
    result = extract.extract(src, "../../escape", "ja", spawn=False)
    processed = os.path.join(get_data_path("ja"), "Processed")
    assert result.code == extract.EXIT_DONE
    assert os.path.isdir(os.path.join(processed, result.folder))
    assert os.path.dirname(os.path.join(processed, result.folder)) == processed
    assert not os.path.exists(os.path.join(get_data_path("ja"), "escape"))


def test_dot_dot_alone_is_refused_and_nothing_is_written(tmp_path):
    src = _text_file(tmp_path, "ja")
    before = _snapshot(get_data_path("ja")) if os.path.isdir(get_data_path("ja")) else {}
    result = extract.extract(src, "..", "ja", spawn=False)
    assert result.code == extract.EXIT_REFUSED and result.note == "name"
    after = _snapshot(get_data_path("ja")) if os.path.isdir(get_data_path("ja")) else {}
    assert after == before


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_name_taken_in_processed_or_a_section_is_refused_and_the_next_free_one_proposed(tmp_path, language):
    data_dir, _uf = _store_library(language)
    os.makedirs(os.path.join(data_dir, "Processed", "旅"))
    os.makedirs(os.path.join(data_dir, "GoalContent", "旅 2"))
    answer = extract.check_name("旅", language)
    assert answer == extract.Name("旅", True, "旅 3")
    assert extract.check_name("新しい本", language) == extract.Name("新しい本", False, None)


def test_a_taken_name_is_refused_and_nothing_in_the_library_moves(tmp_path):
    data_dir, _uf = _store_library("ja")
    show = os.listdir(os.path.join(data_dir, "HighPriority"))[0]
    before = _snapshot(data_dir)
    order = _paths("ja", "now")
    result = extract.extract(_text_file(tmp_path, "ja"), show, "ja", section="now", spawn=False)
    assert result.code == extract.EXIT_REFUSED and result.note == "taken"
    assert _snapshot(data_dir) == before                    # no file moved, overwritten or added
    assert _paths("ja", "now") == order


def test_a_name_the_store_keeps_in_its_trash_is_taken_so_put_back_keeps_its_place(tmp_path):
    data_dir, _uf = _store_library("ja")
    store = _open("ja")
    try:
        item_id, entry, _a = store.ordered("now")[0]
        rel = entry["physical_path"]
        trashed = ls.trash_file(data_dir, rel)
        store.remove([item_id], {item_id: trashed})
    finally:
        store.close()
    folder = os.path.dirname(os.path.join(data_dir, rel))
    for n in os.listdir(folder):                           # the show's other files out of the way, by the same road
        ls.trash_file(data_dir, os.path.relpath(os.path.join(folder, n), data_dir))
    os.rmdir(folder)
    name = os.path.basename(folder)
    assert not os.path.exists(os.path.join(data_dir, "HighPriority", name))
    assert extract.check_name(name, "ja").taken            # the store still holds it (its row's other episodes, trash)


# --- the options ------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("method, value, group, parts, fault", [
    ("length", "1500", False, None, None), ("length", "0", False, None, "length"),
    ("length", "-5", False, None, "length"), ("length", "千", False, None, "length"),
    ("delimiter", r"\n\d+\n", False, None, None), ("delimiter", "(", False, None, "pattern"),
    ("delimiter", "", False, None, "pattern"), ("length", "800", True, 3, None), ("length", "800", True, 0, "parts"),
])
def test_the_split_options_are_checked_before_anything_runs(method, value, group, parts, fault):
    assert extract.check_options(method, value, group, parts) == fault


def test_a_length_under_one_is_refused_by_the_split_itself():
    with pytest.raises(ValueError):
        extract.split_by_length("吾輩は猫である。", 0)


def test_a_pattern_with_groups_of_its_own_splits_where_it_matches():
    text = "第一章\n吾輩は猫である。\n第二章\n名前はまだ無い。"
    assert extract.split_by_delimiter(text, r"第(一|二)章") == ["第一章\n吾輩は猫である。", "第二章\n名前はまだ無い。"]
    # an optional group that doesn't match failed with a TypeError in the Tk split
    assert extract.split_by_delimiter("序\n#1 旅\n#2 帰り", r"#(\d)?\d* ") == ["序", "#1 旅", "#2 帰り"]
    assert extract.split_by_delimiter("前書き\n1\n本文", r"\n\d+\n") == ["前書き", "1\n本文"]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_split_by_length_ends_each_part_at_a_sentence_end(tmp_path, language):
    with open(_text_file(tmp_path, language), encoding="utf-8") as f:
        text = f.read()
    parts = extract.split_by_length(text, 200, 150)
    assert len(parts) > 1
    assert all(len(p) <= 200 + 150 for p in parts)
    assert any(p[-1] in "。？！.?!」』)\"']}" for p in parts[:-1])


# --- extraction --------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language, section", [("ja", "soon"), ("zh", "goal"), ("ja", "now")])
def test_the_parts_land_in_processed_and_enter_the_library_through_the_store_in_the_section_chosen(
        tmp_path, language, section):
    data_dir, _uf = _store_library(language)
    src = _text_file(tmp_path, language)
    result = extract.extract(src, "旅の本", language, section=section, value="300", spawn=False)
    assert result.code == extract.EXIT_DONE and result.in_library and result.parts > 1
    processed = os.path.join(data_dir, "Processed", "旅の本")
    assert sorted(os.listdir(processed))[0] == "旅の本_01.txt"
    folder = ls.FOLDER_OF_TIER[section]
    # Current is NOW then Soon: the store's Soon line may carry the last of them past it (its own rule)
    tiers = ("now", "soon") if section == "now" else (section,)
    listed = [p for t in tiers for p in _paths(language, t) if p.startswith(f"{folder}/旅の本/")]
    assert listed == [f"{folder}/旅の本/旅の本_{i:02d}.txt" for i in range(1, result.parts + 1)]   # in order
    for other in set(extract.SECTIONS) - set(tiers):
        assert not any("旅の本" in p for p in _paths(language, other))
    assert not [n for n in os.listdir(os.path.join(data_dir, "Processed")) if n.startswith(".")]   # no staging left


def test_without_a_section_the_parts_stay_in_processed_only(tmp_path):
    _store_library("ja")
    result = extract.extract(_text_file(tmp_path, "ja"), "下書き", "ja", spawn=False)
    assert result.code == extract.EXIT_DONE and not result.in_library
    assert not any("下書き" in p for t in extract.SECTIONS for p in _paths("ja", t))


def test_a_store_that_cannot_take_files_leaves_the_parts_in_processed_and_says_so(tmp_path, monkeypatch):
    data_dir, _uf = _store_library("ja")
    real = ls.open_store
    monkeypatch.setattr(ls, "open_store", lambda *a, **k: None if k.get("role") == "window" else real(*a, **k))
    result = extract.extract(_text_file(tmp_path, "ja"), "旅の本", "ja", section="soon", spawn=False)
    assert result.code == extract.EXIT_PROCESSED_ONLY and result.note == "store" and not result.in_library
    assert os.path.isdir(os.path.join(data_dir, "Processed", "旅の本"))
    assert not os.path.exists(os.path.join(data_dir, "LowPriority", "旅の本"))   # never copied behind the store


def test_a_refused_insert_sends_the_copies_to_the_trash_and_keeps_the_parts_in_processed(tmp_path, monkeypatch):
    data_dir, _uf = _store_library("ja")

    def refuse(self, *a, **k):
        raise ls.StoreBusy("the write lock is held")
    monkeypatch.setattr(ls.Store, "insert", refuse)
    result = extract.extract(_text_file(tmp_path, "ja"), "旅の本", "ja", section="soon", value="300", spawn=False)
    assert result.code == extract.EXIT_PROCESSED_ONLY and result.note == "insert"
    left = os.path.join(data_dir, "LowPriority", "旅の本")
    assert not os.path.exists(left)                        # its files trashed and the folders it made removed
    trashed = [n for n in os.listdir(os.path.join(data_dir, ".trash")) if n.startswith("旅の本_")]
    assert len(trashed) == result.parts                    # moved to the trash (its clock restarted), never deleted
    assert len(os.listdir(os.path.join(data_dir, "Processed", "旅の本"))) == result.parts


def test_an_insert_that_adds_nothing_sends_the_copies_to_the_trash_too(tmp_path, monkeypatch):
    """AD2-10: an insert that answers nothing added (every file a row already: a race) left the copies in the section's
    folder outside the store, for the disk sync to take in by the folder rule."""
    data_dir, _uf = _store_library("ja")
    monkeypatch.setattr(ls.Store, "insert", lambda self, *a, **k: None)
    result = extract.extract(_text_file(tmp_path, "ja"), "旅の本", "ja", section="soon", value="300", spawn=False)
    assert result.code == extract.EXIT_PROCESSED_ONLY and result.note == "insert"
    assert not os.path.exists(os.path.join(data_dir, "LowPriority", "旅の本"))
    trashed = [n for n in os.listdir(os.path.join(data_dir, ".trash")) if n.startswith("旅の本_")]
    assert len(trashed) == result.parts


def test_an_empty_file_is_a_failure_and_saves_nothing(tmp_path):
    empty = tmp_path / "空.txt"
    empty.write_text("\n\n  \n", encoding="utf-8")
    result = extract.extract(str(empty), "空", "ja", spawn=False)
    assert result.code == extract.EXIT_FAILED and result.note == "empty"
    assert not os.path.exists(os.path.join(get_data_path("ja"), "Processed", "空"))


def test_a_deck_field_with_no_text_is_a_failure(ja_resources_dir, monkeypatch):
    monkeypatch.setattr(extract, "deck_text", lambda path, field: "")
    result = extract.extract(os.path.join(ja_resources_dir, "testAnki.apkg"), "デッキ", "ja", field="Audio",
                             spawn=False)
    assert result.code == extract.EXIT_FAILED and result.note == "empty"


def test_a_deck_gives_its_fields_text_as_one_part(ja_resources_dir):
    from app import anki_db_import
    path = os.path.join(ja_resources_dir, "testAnki.apkg")
    field = anki_db_import.read_deck(path).default
    result = extract.extract(path, "デッキ", "ja", field=field, parts=3, spawn=False)
    folder = os.path.join(get_data_path("ja"), "Processed", "デッキ")
    assert result.code == extract.EXIT_DONE and result.parts == 1    # grouping never applies to a deck
    assert os.listdir(folder) == ["デッキ.txt"]
    with open(os.path.join(folder, "デッキ.txt"), encoding="utf-8") as f:
        assert f.read().strip()


def test_grouped_output_spreads_the_parts_over_folders(tmp_path):
    rels = extract.save_chunks_grouped([f"第{i}話" for i in range(10)], "本", 3, str(tmp_path / "本"))
    assert rels[0] == "本_1/本_1_01.txt" and rels[-1] == "本_3/本_3_02.txt" and len(rels) == 10
    assert sorted(os.listdir(tmp_path / "本")) == ["本_1", "本_2", "本_3"]
    assert extract.save_chunks_grouped(["一", "二"], "短", 5, str(tmp_path / "短")) == ["短_1/短_1_01.txt",
                                                                                        "短_2/短_2_01.txt"]


def test_a_text_file_is_read_in_its_own_encoding(tmp_path):
    cp932 = tmp_path / "古い.txt"
    cp932.write_bytes("吾輩は猫である。名前はまだ無い。".encode("cp932"))
    text, error = extract.extract_text_from_file(str(cp932), "ja")
    assert error is None and text.startswith("吾輩は猫である")


def test_a_subtitle_is_read_as_the_library_reads_it(ja_resources_dir):
    from app import analyzer
    path = os.path.join(ja_resources_dir, "phrases_sample.srt")
    text, error = extract.extract_text_from_file(path, "ja")
    assert error is None and text == analyzer.extract_text(path, "ja")


def _epub(path, chapters):
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier("w34-extract")
    book.set_title("旅の記録")
    book.set_language("ja")
    items = []
    for n, body in enumerate(chapters, 1):
        c = epub.EpubHtml(title=f"第{n}章", file_name=f"c{n}.xhtml", lang="ja")
        c.content = f"<html><body>{body}</body></html>"
        book.add_item(c)
        items.append(c)
    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items
    epub.write_epub(str(path), book)
    return str(path)


def test_an_epub_loses_its_ruby_readings_and_its_parts_carry_the_book_marker(tmp_path):
    from app.path_utils import SOURCE_MARKER
    src = _epub(tmp_path / "旅の記録.epub", ["<p><ruby>吾輩<rt>わがはい</rt></ruby>は猫である。</p><p>名前はまだ無い。</p>",
                                             "<h1>第二章</h1><p>どこで生れたかとんと見当がつかぬ。</p>"])
    text, error = extract.extract_text_from_file(src, "ja")
    assert error is None and "わがはい" not in text and "吾輩は猫である。\n名前はまだ無い。" in text
    result = extract.extract(src, "旅の記録", "ja", spawn=False)
    folder = os.path.join(get_data_path("ja"), "Processed", "旅の記録")
    with open(os.path.join(folder, SOURCE_MARKER), encoding="utf-8") as f:
        assert json.load(f) == {"source_type": "epub", "origin": "旅の記録.epub"}
    assert result.code == extract.EXIT_DONE


# --- the child ---------------------------------------------------------------------------------------------------- #
def test_the_child_prints_its_result_last_and_exits_with_its_code(tmp_path, capsys, monkeypatch):
    _store_library("ja")
    monkeypatch.setattr(ls, "spawn_maintain", lambda *a: None)
    code = extract.main(["--language", "ja", "--file", _text_file(tmp_path, "ja"), "--name", "旅の本",
                         "--section", "soon", "--value", "400"])
    last = capsys.readouterr().out.strip().splitlines()[-1]
    result = extract.parse_result(last)
    assert code == extract.EXIT_DONE == result.code and result.in_library and result.section == "soon"
    code = extract.main(["--language", "ja", "--file", _text_file(tmp_path, "ja"), "--name", "旅の本",
                         "--section", "soon"])
    assert code == extract.EXIT_REFUSED                    # the same name again: refused, nothing replaced


def test_the_child_refuses_bad_options_before_reading_anything(tmp_path, capsys):
    code = extract.main(["--language", "ja", "--file", str(tmp_path / "無い.txt"), "--name", "x", "--value", "0"])
    assert code == extract.EXIT_FAILED
    assert extract.parse_result(capsys.readouterr().out.strip().splitlines()[-1]).note == "length"


# --- the mutant pass's survivors --------------------------------------------------------------------------------- #
def test_the_section_folder_is_checked_again_just_before_the_copy(tmp_path):
    data_dir, _uf = _store_library("ja")
    source = tmp_path / "旅の本"
    source.mkdir()
    (source / "旅の本_01.txt").write_text("朝早く駅に着いた。", encoding="utf-8")
    os.makedirs(os.path.join(data_dir, "LowPriority", "旅の本"))          # taken meanwhile (another program)
    added, why = extract.add_to_library(str(source), "旅の本", ["旅の本_01.txt"], "ja", "soon", spawn=False)
    assert (added, why) == (False, "taken")
    assert os.listdir(os.path.join(data_dir, "LowPriority", "旅の本")) == []


def test_a_good_insert_asks_the_helper_to_write_the_librarys_copy(tmp_path, monkeypatch):
    _store_library("ja")
    asked = []
    monkeypatch.setattr(ls, "spawn_maintain", lambda language, *a: asked.append(language))
    result = extract.extract(_text_file(tmp_path, "ja"), "旅の本", "ja", section="soon", value="400")
    assert result.in_library and asked == ["ja"]


def _show_rows(store, data_dir):
    """The first show in NOW: its folder name and its items (id, rel)."""
    rows = [(i, e["physical_path"]) for i, e, _a in store.ordered("now")]
    folder = rows[0][1].rsplit("/", 1)[0]
    return folder.split("/")[-1], [(i, r) for i, r in rows if r.startswith(folder + "/")]


def test_a_name_the_store_still_lists_is_taken_though_its_folder_is_gone(tmp_path):
    """Its files gone from disk (the rows stay, marked missing): a new split must not reattach them."""
    data_dir, _uf = _store_library("ja")
    store = _open("ja")
    try:
        name, rows = _show_rows(store, data_dir)
    finally:
        store.close()
    for _i, rel in rows:
        ls.trash_file(data_dir, rel)
    os.rmdir(os.path.join(data_dir, "HighPriority", name))
    assert extract.check_name(name, "ja").taken


def test_a_name_only_the_stores_trash_holds_is_taken(tmp_path):
    """Every episode removed (Put back can restore them): the name stays taken while the trash keeps them."""
    data_dir, _uf = _store_library("ja")
    store = _open("ja")
    try:
        name, rows = _show_rows(store, data_dir)
        trashed = {i: ls.trash_file(data_dir, rel) for i, rel in rows}
        store.remove([i for i, _r in rows], trashed)
        assert not any(r.startswith(f"HighPriority/{name}/") for _i, e, _a in store.ordered("now")
                       for r in [e["physical_path"]])
    finally:
        store.close()
    os.rmdir(os.path.join(data_dir, "HighPriority", name))
    assert extract.check_name(name, "ja").taken


# --- a value that starts with a dash (the window glues every value to its option) ---------------------------------- #
def test_the_child_takes_a_dash_delimiter_and_a_dash_name_glued_to_their_options(tmp_path, capsys):
    """A chapter rule such as --- in a .txt, a name such as -draft: argparse read them as options (exit 2, no result
    line). Glued (`--value=---`), the child takes them as the Tk window did."""
    with open(os.path.join(RES, "ja", "context_test.txt"), encoding="utf-8") as f:
        text = f.read()
    src = tmp_path / "章.txt"
    src.write_text(f"{text}\n---\n{text}\n---\n{text}", encoding="utf-8")
    code = extract.main(["--language", "ja", f"--file={src}", "--name=-draft", "--split", "delimiter",
                         "--value=---"])
    result = extract.parse_result(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == extract.EXIT_DONE and result.parts == 3 and result.folder == "-draft"


def test_the_child_starts_no_store_helper_when_its_environment_says_so(tmp_path, monkeypatch, capsys):
    """A test that runs the real child sets NO_HELPER_ENV: the detached helper would outlive the test's folders (the
    hazard conftest's in-process patch can't reach in a child). Without it the child asks for the helper."""
    asked = []
    monkeypatch.setattr(extract, "extract", lambda *a, spawn=True, **k: asked.append(spawn) or
                        extract.Result(extract.EXIT_DONE, 1, "x", None, False, None))
    argv = ["--language", "ja", "--file", _text_file(tmp_path, "ja"), "--name", "旅の本"]
    monkeypatch.delenv(extract.NO_HELPER_ENV, raising=False)
    extract.main(argv)
    monkeypatch.setenv(extract.NO_HELPER_ENV, "1")
    extract.main(argv)
    assert asked == [True, False]


def test_a_long_name_is_cut_so_a_grouped_splits_paths_stay_short():
    """AD2-13: <section>/<name>/<name>_k/<name>_k_NN.txt holds the name three times — at 120 characters a grouped
    split passed Windows' 260-character path on a system without long paths."""
    assert extract.NAME_LIMIT <= 60
    assert len(extract.clean_name("吾輩は猫である" * 20)) == extract.NAME_LIMIT

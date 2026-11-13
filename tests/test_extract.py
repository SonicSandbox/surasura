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
    folder = ls.CONTENT_FOLDER                              # every new copy's folder (SRC K3); the place is the section
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
    assert not os.path.exists(os.path.join(data_dir, ls.CONTENT_FOLDER, "旅の本"))   # never copied behind the store


def test_a_refused_insert_sends_the_copies_to_the_trash_and_keeps_the_parts_in_processed(tmp_path, monkeypatch):
    data_dir, _uf = _store_library("ja")

    def refuse(self, *a, **k):
        raise ls.StoreBusy("the write lock is held")
    monkeypatch.setattr(ls.Store, "insert", refuse)
    result = extract.extract(_text_file(tmp_path, "ja"), "旅の本", "ja", section="soon", value="300", spawn=False)
    assert result.code == extract.EXIT_PROCESSED_ONLY and result.note == "insert"
    left = os.path.join(data_dir, ls.CONTENT_FOLDER, "旅の本")
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
    assert not os.path.exists(os.path.join(data_dir, ls.CONTENT_FOLDER, "旅の本"))
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
    os.makedirs(os.path.join(data_dir, ls.CONTENT_FOLDER, "旅の本"))      # taken meanwhile (another program)
    added, why, _title = extract.add_to_library(str(source), "旅の本", ["旅の本_01.txt"], "ja", "soon", spawn=False)
    assert (added, why) == (False, "taken")
    assert os.listdir(os.path.join(data_dir, ls.CONTENT_FOLDER, "旅の本")) == []


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


# --- AD2-12: what the tests didn't reach -------------------------------------------------------------------------- #
def test_an_epub_extracted_into_a_section_enters_the_library_as_a_book(tmp_path):
    """The book marker travels with the copy into the section's folder, and the store's rows say epub (the report's
    source badge) — not only the parts left in Processed."""
    from app.path_utils import SOURCE_MARKER
    data_dir, _uf = _store_library("ja")
    src = _epub(tmp_path / "旅の記録.epub", ["<p>吾輩は猫である。名前はまだ無い。</p>" * 40,
                                             "<h1>第二章</h1><p>どこで生れたかとんと見当がつかぬ。</p>" * 40])
    result = extract.extract(src, "旅の記録", "ja", section="goal", value="300", spawn=False)
    assert result.code == extract.EXIT_DONE and result.in_library
    copy = os.path.join(data_dir, ls.CONTENT_FOLDER, "旅の記録")
    with open(os.path.join(copy, SOURCE_MARKER), encoding="utf-8") as f:
        assert json.load(f)["source_type"] == "epub"
    store = _open("ja")
    try:
        rows = [e for _i, e, _a in store.ordered("goal") if e["physical_path"].startswith("Library/旅の記録/")]
    finally:
        store.close()
    assert len(rows) == result.parts and {e.get("source_type") for e in rows} == {"epub"}


# --- the round-2 mutant pass's survivors ------------------------------------------------------------------------ #
def test_a_copy_that_cant_go_to_the_trash_never_stops_the_others_or_the_answer(tmp_path, monkeypatch):
    """One copy held open by another program can't be moved: the rest still go to the trash, and the run still says
    the parts stay in Processed (never an error from the clean-up)."""
    data_dir, _uf = _store_library("ja")
    monkeypatch.setattr(ls.Store, "insert", lambda self, *a, **k: None)
    real, held = ls.trash_file, []

    def trash(data, rel):
        if not held:
            held.append(rel)
            raise PermissionError("held open by another program")
        return real(data, rel)
    monkeypatch.setattr(ls, "trash_file", trash)
    result = extract.extract(_text_file(tmp_path, "ja"), "旅の本", "ja", section="soon", value="300", spawn=False)
    assert result.code == extract.EXIT_PROCESSED_ONLY and result.note == "insert"
    trashed = [n for n in os.listdir(os.path.join(data_dir, ".trash")) if n.startswith("旅の本_")]
    assert len(trashed) == result.parts - 1 and held


# --- SRC K3: never a duplicate --------------------------------------------------------------------------------- #
def _items(language):
    store = _open(language)
    try:
        return store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        store.close()


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_K3_an_extract_of_a_book_already_in_adds_nothing_and_names_it(tmp_path, language):
    """The same book split the same way again (another name, so the name check lets it by): every part's bytes are
    an item's already — nothing copied, nothing added, the parts kept in Processed, and the answer names the book."""
    from app import importers_view
    data_dir, _uf = _store_library(language)
    src = _text_file(tmp_path, language)
    first = extract.extract(src, "旅の本", language, section="now", value="300", spawn=False)
    assert first.in_library
    count = _items(language)
    again = extract.extract(src, "旅の本 2", language, section="soon", value="300", spawn=False)
    assert again.code == extract.EXIT_PROCESSED_ONLY and again.note == "already" and not again.in_library
    assert again.title == "旅の本" and _items(language) == count
    assert not os.path.exists(os.path.join(data_dir, ls.CONTENT_FOLDER, "旅の本 2"))
    assert len(os.listdir(os.path.join(data_dir, "Processed", "旅の本 2"))) == again.parts
    assert importers_view.extract_outcome(again.code, again, "why") == (
        "already", {"parts": again.parts, "name": "旅の本 2", "section": "soon", "title": "旅の本"})
    line = extract.result_line(again)                      # the child's line carries the title to the window
    assert extract.parse_result(line).title == "旅の本"


def test_K3_a_split_with_one_part_already_in_copies_and_adds_only_the_new_parts(tmp_path):
    """A part whose bytes an item holds is never copied again; the others come in, in the section asked."""
    data_dir, _uf = _store_library("ja")
    source = tmp_path / "旅の本"
    source.mkdir()
    store = _open("ja")
    try:
        rel = store.ordered("now")[0][1]["physical_path"]
    finally:
        store.close()
    with open(os.path.join(data_dir, *rel.split("/")), "rb") as f:
        (source / "旅の本_01.txt").write_bytes(f.read())
    (source / "旅の本_02.txt").write_text("朝早く駅に着いた。", encoding="utf-8")
    added, why, _t = extract.add_to_library(str(source), "旅の本", ["旅の本_01.txt", "旅の本_02.txt"], "ja", "soon",
                                            spawn=False)
    assert (added, why) == (True, None)
    assert os.listdir(os.path.join(data_dir, ls.CONTENT_FOLDER, "旅の本")) == ["旅の本_02.txt"]
    assert "Library/旅の本/旅の本_02.txt" in _paths("ja", "soon") + _paths("ja", "now")


def test_a_file_that_vanishes_before_its_stat_is_skipped_and_the_rest_are_still_answered(tmp_path):
    """A part listed but gone by the time the sizes are read is no error: it is passed over, and the files still
    there are answered as held by the item they match."""
    # why: a file removed between the folder listing and its stat must not raise and abort the whole twin check.
    data_dir, _uf = _store_library("ja")
    store = _open("ja")
    try:
        item_id, entry, _a = store.ordered("now")[0]
        present = os.path.join(data_dir, *entry["physical_path"].split("/"))
    finally:
        store.close()
    # a twin of the item's file, outside the library, so its own row is never the match
    twin = tmp_path / "旅の本_twin.txt"
    with open(present, "rb") as f:
        twin.write_bytes(f.read())
    gone = str(tmp_path / "旅の本_vanished.txt")          # listed, never created: its stat raises
    store = _open("ja")
    try:
        held = store.items_holding([gone, str(twin)])
    finally:
        store.close()
    assert set(held) == {str(twin)}
    assert held[str(twin)][0] == item_id


# --- Kantan-B4 (Mattias, #testers 2026-11-12): a removed title added again ------------------------------------------ #
# He removed 消滅世界 and Extract later said its name was "taken": the name check counts the trash (so Put back keeps its
# place), and nothing pointed at Removed. Now the check names the Removed title it meets — by the name, or by the
# file's own bytes — with its days left; *Put back* is the Removed list's own command (the window's), and *Add as new*
# (`as_new`) gives the removed one the next free name in the trash and takes the name: never the learner's file.
def _removed_book(tmp_path, language, name="消滅世界", parts=0, epub=None):
    """A book extracted into Current (`parts`: grouped), then removed whole (each part's file to the trash,
    `Store.remove`, as Remove… does) -> (the EPUB's path, the trash ids, {the old split's file: its bytes})."""
    text = "<p>吾輩は猫である。名前はまだ無い。</p>" if language == "ja" else "<p>我们走在大路上。今天天气很好。</p>"
    src = epub or _epub(tmp_path / f"{name}.epub", [text * 40, text * 30])
    first = extract.extract(src, name, language, section="now", value="300", parts=parts, spawn=False)
    assert first.in_library
    data_dir = get_data_path(language)
    old = _snapshot(os.path.join(data_dir, "Processed", name))
    store = _open(language)
    try:
        rows = [(i, r) for i, r in store.conn.execute("SELECT id, rel_path FROM items ORDER BY id")
                if r.startswith(f"{ls.CONTENT_FOLDER}/{name}/")]
        change = store.remove([i for i, _r in rows], {i: ls.trash_file(data_dir, r) for i, r in rows})
    finally:
        store.close()
    return src, change.trash_ids, old


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_B4_a_name_only_a_removed_title_holds_names_that_title_and_its_days_left(tmp_path, language):
    """The name stays taken (Put back's place), but the answer names the Removed title holding it, so the window can
    offer it back — and says the name can be freed (nothing but the removed title and its own leftovers holds it)."""
    _store_library(language)
    src, trash_ids, _old = _removed_book(tmp_path, language)
    answer = extract.check_name("消滅世界", language, src)
    assert answer.taken and answer.proposal == "消滅世界 2"
    assert answer.removed["title"] == "消滅世界" and sorted(answer.removed["trash_ids"]) == sorted(trash_ids)
    assert answer.removed["days_left"] == ls.REMOVED_DAYS
    assert answer.free


def test_B4_the_same_epub_under_another_name_is_found_in_removed_by_its_bytes(tmp_path):
    """Typed under a new name (as he did), the book is still his removed one: its bytes say so."""
    _store_library("ja")
    src, trash_ids, _old = _removed_book(tmp_path, "ja")
    answer = extract.check_name("消滅世界 新版", "ja", src)
    assert not answer.taken and not answer.free
    assert answer.removed["title"] == "消滅世界" and sorted(answer.removed["trash_ids"]) == sorted(trash_ids)


def test_B4_another_book_under_a_free_name_meets_nothing_in_removed(tmp_path):
    _store_library("ja")
    _removed_book(tmp_path, "ja")
    other = _epub(tmp_path / "別の本.epub", ["<p>どこで生れたかとんと見当がつかぬ。</p>" * 30])
    assert extract.check_name("別の本", "ja", other) == extract.Name("別の本", False, None, None, False)


def test_B4_a_removed_title_put_back_names_nothing_any_more(tmp_path):
    """Put back since (its rows restored): the name is the library's again — taken by the title, never offered."""
    _store_library("ja")
    src, trash_ids, _old = _removed_book(tmp_path, "ja")
    store = _open("ja")
    try:
        rel_paths = {r["id"]: ls.put_back(store.data_dir, r["trashed_path"], r["rel_path"])[0]
                     for r in store.trash_rows(trash_ids)}
        store.restore(trash_ids, rel_paths)
    finally:
        store.close()
    answer = extract.check_name("消滅世界", "ja", src)
    assert answer.taken and answer.removed is None and not answer.free


def test_B4_a_name_a_live_title_holds_is_never_freed(tmp_path):
    """A show in the library: taken, nothing removed named, never freed — and an Add as new asked anyway moves nothing."""
    data_dir, _uf = _store_library("ja")
    show = os.listdir(os.path.join(data_dir, "HighPriority"))[0]
    answer = extract.check_name(show, "ja")
    assert answer.taken and answer.removed is None and not answer.free
    before, order = _snapshot(data_dir), _paths("ja", "now")
    result = extract.extract(_text_file(tmp_path, "ja"), show, "ja", section="now", spawn=False, as_new=True)
    assert result.code == extract.EXIT_REFUSED and result.note == "taken"
    assert _snapshot(data_dir) == before and _paths("ja", "now") == order


def test_B4_a_left_folder_holding_a_file_of_its_own_is_never_freed(tmp_path):
    """`Library/<name>` holding a file that isn't one of Surasura's marks: never moved, so the name isn't free."""
    data_dir, _uf = _store_library("ja")
    src, _ids, _old = _removed_book(tmp_path, "ja")
    stray = os.path.join(data_dir, ls.CONTENT_FOLDER, "消滅世界", "メモ.txt")
    with open(stray, "w", encoding="utf-8") as f:
        f.write("あとで読む。")
    answer = extract.check_name("消滅世界", "ja", src)
    assert answer.taken and answer.removed is not None and not answer.free
    result = extract.extract(src, "消滅世界", "ja", section="now", value="300", spawn=False, as_new=True)
    assert result.note == "taken" and os.path.isfile(stray)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_B4_add_as_new_takes_the_name_and_renames_the_removed_one_in_the_trash(tmp_path, language):
    """*Add as new*: the removed title becomes `消滅世界 2` in the trash (its Put back place, its title, its old split
    in Processed and its left folder, all renamed whole, nothing deleted); the new split takes 消滅世界; the learner's
    EPUB is untouched. Put back later brings the old one back as its own title, never mixed into the new one."""
    data_dir, _uf = _store_library(language)
    src, trash_ids, old = _removed_book(tmp_path, language)
    with open(src, "rb") as f:
        epub_bytes = f.read()
    result = extract.extract(src, "消滅世界", language, section="now", value="300", spawn=False, as_new=True)
    assert result.code == extract.EXIT_DONE and result.in_library and result.folder == "消滅世界"
    assert result.freed == "消滅世界 2"
    with open(src, "rb") as f:
        assert f.read() == epub_bytes                                   # the learner's file, never touched
    assert _snapshot(os.path.join(data_dir, "Processed", "消滅世界 2")) == old     # the old split, renamed whole
    assert os.path.isfile(os.path.join(data_dir, ls.CONTENT_FOLDER, "消滅世界 2", ".surasura_source.json"))
    store = _open(language)
    try:
        [entry] = store.removed()
        assert entry["title"] == "消滅世界 2" and sorted(entry["trash_ids"]) == sorted(trash_ids)
        rows = store.trash_rows(trash_ids)
        assert all(r["rel_path"].startswith(f"{ls.CONTENT_FOLDER}/消滅世界 2/") for r in rows)
        assert all(json.loads(r["entry"])["physical_path"] == r["rel_path"] for r in rows)
        new = [i for i, r in store.conn.execute("SELECT id, rel_path FROM items")
               if r.startswith(f"{ls.CONTENT_FOLDER}/消滅世界/")]
        assert len(new) == result.parts
        rel_paths = {r["id"]: ls.put_back(data_dir, r["trashed_path"], r["rel_path"])[0] for r in rows}
        store.restore(trash_ids, rel_paths)                             # Put back, later
        works = dict(store.conn.execute("SELECT i.rel_path, w.title FROM items i JOIN works w ON w.id = i.work_id"))
    finally:
        store.close()
    assert {t for r, t in works.items() if r.startswith(f"{ls.CONTENT_FOLDER}/消滅世界 2/")} == {"消滅世界 2"}
    assert {t for r, t in works.items() if r.startswith(f"{ls.CONTENT_FOLDER}/消滅世界/")} == {"消滅世界"}
    assert extract.check_name("消滅世界", language, src).removed is None


def test_B4_add_as_new_with_nothing_removed_under_the_name_is_a_plain_extract(tmp_path):
    """No removed title holds the name: `as_new` changes nothing — the split is added as any, nothing renamed."""
    data_dir, _uf = _store_library("ja")
    result = extract.extract(_text_file(tmp_path, "ja"), "旅の本", "ja", section="now", value="300", spawn=False,
                             as_new=True)
    assert result.in_library and result.freed is None
    assert not os.path.exists(os.path.join(data_dir, "Processed", "旅の本 2"))


def test_B4_a_store_that_refuses_the_rename_puts_the_folders_back(tmp_path, monkeypatch):
    """The trash's rename fails after the folders moved: they move back, nothing is extracted, the name stays taken."""
    data_dir, _uf = _store_library("ja")
    src, _ids, old = _removed_book(tmp_path, "ja")

    def refuse(*_a, **_k):
        raise ls.StoreConflict("busy")
    monkeypatch.setattr(ls.Store, "rename_removed", refuse)
    result = extract.extract(src, "消滅世界", "ja", section="now", value="300", spawn=False, as_new=True)
    assert result.code == extract.EXIT_REFUSED and result.note == "busy"      # said, never a plain "taken"
    assert _snapshot(os.path.join(data_dir, "Processed", "消滅世界")) == old
    assert not os.path.exists(os.path.join(data_dir, "Processed", "消滅世界 2"))
    assert os.listdir(os.path.join(data_dir, ls.CONTENT_FOLDER, "消滅世界")) == [".surasura_source.json"]
    assert extract.check_name("消滅世界", "ja", src).free


def test_B4_the_child_takes_as_new_and_reports_the_freed_name(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(extract.NO_HELPER_ENV, "1")
    _store_library("ja")
    src, _ids, _old = _removed_book(tmp_path, "ja")
    code = extract.main(["--language", "ja", f"--file={src}", "--name=消滅世界", "--section", "now", "--value=300",
                         "--as-new"])
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert code == extract.EXIT_DONE and extract.parse_result(last).freed == "消滅世界 2"


def test_B4_one_remove_of_two_titles_is_one_line_but_each_title_is_its_own_entry_when_split(tmp_path):
    """The Removed list keeps one line per Remove; the name check asks per title (`split=True`), so a Put back from
    Extract brings back that title alone, never the other one removed with it."""
    _store_library("ja")
    data_dir = get_data_path("ja")
    store = _open("ja")
    try:
        works = {}
        for i, w in store.conn.execute("SELECT id, work_id FROM items ORDER BY id"):
            works.setdefault(w, []).append(i)
        two = list(works.values())[:2]
        assert len(two) == 2
        ids = two[0] + two[1]
        rels = dict(store.conn.execute(f"SELECT id, rel_path FROM items WHERE id IN ({','.join('?' * len(ids))})", ids))
        store.remove(ids, {i: ls.trash_file(data_dir, r) for i, r in rels.items()})
        assert len(store.removed()) == 1
        split = store.removed(split=True)
    finally:
        store.close()
    assert len(split) == 2 and sum(e["count"] for e in split) == len(ids)


@pytest.mark.parametrize("whole", [False, True])
def test_B4_a_show_in_a_tier_folder_is_offered_back_but_its_folder_is_never_freed(tmp_path, whole):
    """A 2.x show folder (HighPriority/<show>): one episode removed (the rest still in the library), or every episode
    removed with the folder left — Removed names it, but the name is never freed: the folder is the learner's (or
    still holds the title), so *Add as new* moves nothing."""
    data_dir, _uf = _store_library("ja")
    store = _open("ja")
    try:
        name, rows = _show_rows(store, data_dir)
        gone = rows if whole else rows[:1]
        store.remove([i for i, _r in gone], {i: ls.trash_file(data_dir, r) for i, r in gone})
    finally:
        store.close()
    answer = extract.check_name(name, "ja")
    assert answer.taken and answer.removed is not None and not answer.free
    before = _snapshot(data_dir)
    result = extract.extract(_text_file(tmp_path, "ja"), name, "ja", section="now", spawn=False, as_new=True)
    assert result.note == "taken" and result.freed is None and _snapshot(data_dir) == before


# --- Kantan-B4, review round 1 ------------------------------------------------------------------------------------ #
def test_B4_r1_a_grouped_split_comes_back_whole_and_apart_after_add_as_new(tmp_path):
    """r1 #1, #2: a book split into folders (`消滅世界/消滅世界_1/…`, one title per folder) — the check offers every
    folder's files at once, and after *Add as new* its Put back lands each part under `消滅世界 2/` with its folder
    there, never in the new title's group folders."""
    data_dir, _uf = _store_library("ja")
    src, trash_ids, _old = _removed_book(tmp_path, "ja", parts=2)
    answer = extract.check_name("消滅世界", "ja", src)
    assert sorted(answer.removed["trash_ids"]) == sorted(trash_ids) and answer.free
    result = extract.extract(src, "消滅世界", "ja", section="now", value="300", parts=2, spawn=False, as_new=True)
    assert result.in_library and result.freed == "消滅世界 2"
    store = _open("ja")
    try:
        rows = store.trash_rows(trash_ids)
        rel_paths = {r["id"]: ls.put_back(data_dir, r["trashed_path"], r["rel_path"])[0] for r in rows}
        store.restore(trash_ids, rel_paths)
        back = {r: json.loads(e) for r, e in store.conn.execute(
            f"SELECT rel_path, entry FROM items WHERE id IN ({','.join('?' * len(rows))})", [r["item_id"] for r in rows])}
    finally:
        store.close()
    assert len(back) == len(trash_ids)
    for rel, entry in back.items():
        assert rel.startswith(f"{ls.CONTENT_FOLDER}/消滅世界 2/") and entry["physical_path"] == rel
        assert entry["parent_folder"] == ls.parent_folder_of(rel) and entry["parent_folder"].startswith("消滅世界 2/")


def test_B4_r1_one_book_removed_in_two_removes_is_offered_back_whole(tmp_path):
    """r1 #2: one part removed first, the rest later — two entries in Removed; Put back from Extract takes both."""
    data_dir, _uf = _store_library("ja")
    src = _epub(tmp_path / "消滅世界.epub", ["<p>吾輩は猫である。名前はまだ無い。</p>" * 40] * 2)
    assert extract.extract(src, "消滅世界", "ja", section="now", value="300", spawn=False).in_library
    store = _open("ja")
    try:
        rows = [(i, r) for i, r in store.conn.execute("SELECT id, rel_path FROM items ORDER BY id")
                if r.startswith(f"{ls.CONTENT_FOLDER}/消滅世界/")]
        ids = []
        for chunk in (rows[:1], rows[1:]):
            ids += store.remove([i for i, _r in chunk], {i: ls.trash_file(data_dir, r) for i, r in chunk}).trash_ids
        assert len(store.removed(split=True)) == 2
    finally:
        store.close()
    answer = extract.check_name("消滅世界", "ja", src)
    assert sorted(answer.removed["trash_ids"]) == sorted(ids) and answer.removed["count"] == len(rows)
    assert answer.removed["title"] == "消滅世界"


def test_B4_r1_a_removed_title_whose_files_were_purged_still_frees_its_name(tmp_path):
    """r1 #3: past 30 days its files are purged — it leaves the Removed list, but its rows still hold the name: the
    check says the name can be freed (nothing named), so it is never a dead end again."""
    data_dir, _uf = _store_library("ja")
    src, trash_ids, _old = _removed_book(tmp_path, "ja")
    store = _open("ja")
    try:
        for r in store.trash_rows(trash_ids):
            os.remove(os.path.join(data_dir, *r["trashed_path"].split("/")))     # the purge's doing
        assert store.removed() == []
    finally:
        store.close()
    answer = extract.check_name("消滅世界", "ja", src)
    assert answer.taken and answer.removed is None and answer.free
    result = extract.extract(src, "消滅世界", "ja", section="now", value="300", spawn=False, as_new=True)
    assert result.in_library and result.freed == "消滅世界 2"


def test_B4_r1_an_unreadable_file_renames_nothing(tmp_path):
    """r1 #4: *Add as new* of a file that can't be read: the removed title keeps its name and its folders."""
    data_dir, _uf = _store_library("ja")
    src, trash_ids, old = _removed_book(tmp_path, "ja")
    broken = tmp_path / "壊れた本.epub"
    broken.write_bytes(b"PK\x03\x04 not a book")
    result = extract.extract(str(broken), "消滅世界", "ja", section="now", value="300", spawn=False, as_new=True)
    assert result.code == extract.EXIT_FAILED and result.freed is None
    assert _snapshot(os.path.join(data_dir, "Processed", "消滅世界")) == old
    assert not os.path.exists(os.path.join(data_dir, "Processed", "消滅世界 2"))
    store = _open("ja")
    try:
        assert all(r["rel_path"].startswith(f"{ls.CONTENT_FOLDER}/消滅世界/") for r in store.trash_rows(trash_ids))
    finally:
        store.close()


def test_B4_r1_a_removed_title_still_in_the_library_elsewhere_is_never_freed(tmp_path):
    """r1 #6: the removed rows' title still holds an item (here: a show's episode made one of its items): renaming
    its rows would leave its folder key catching the new folder — so the name is never freed."""
    data_dir, _uf = _store_library("ja")
    src, trash_ids, _old = _removed_book(tmp_path, "ja")
    store = _open("ja")
    try:
        work = json.loads(store.trash_rows(trash_ids)[0]["item_state"])["columns"]["work_id"]
        with store._writing():
            item = store.conn.execute("SELECT id FROM items ORDER BY id LIMIT 1").fetchone()[0]
            store.conn.execute("UPDATE items SET work_id = ? WHERE id = ?", (work, item))   # (planted: one title)
    finally:
        store.close()
    answer = extract.check_name("消滅世界", "ja", src)
    assert answer.removed is not None and not answer.free


def test_B4_r1_the_names_own_removed_title_comes_before_one_met_by_its_bytes(tmp_path):
    """r1 #7: the EPUB was removed as 「別名」; another removed title holds the name 消滅世界 — the check names that
    one (the one *Add as new* would rename), never the book met by its bytes."""
    _store_library("ja")
    src, _bytes_ids, _old = _removed_book(tmp_path, "ja", name="別名")
    other = _epub(tmp_path / "別の本.epub", ["<p>どこで生れたかとんと見当がつかぬ。</p>" * 30])
    _x, name_ids, _old2 = _removed_book(tmp_path, "ja", name="消滅世界", epub=other)
    answer = extract.check_name("消滅世界", "ja", src)
    assert sorted(answer.removed["trash_ids"]) == sorted(name_ids) and answer.free
    assert extract.check_name("新しい名前", "ja", src).removed["title"] == "別名"   # (by its bytes, a free name)


def test_B4_r1_a_bytes_match_alone_never_frees_another_titles_name(tmp_path, monkeypatch):
    """r1 #7: only the bytes matched (the name's leftovers belong to nothing in the list): never free."""
    _store_library("ja")
    src, _ids, _old = _removed_book(tmp_path, "ja")
    monkeypatch.setattr(extract, "_in_removed", lambda *a, **k: ({"trash_ids": [99], "title": "別名", "titles": 1,
                                                                 "days_left": 3, "count": 1}, False))
    answer = extract.check_name("消滅世界", "ja", src)
    assert answer.taken and answer.removed["title"] == "別名" and not answer.free


def test_B4_r1_undo_of_the_original_remove_after_add_as_new_comes_back_under_the_new_name(tmp_path):
    """The Remove's own Undo (still on the window's stack) after *Add as new*: its rows come back where the trash now
    says — `消滅世界 2/` — never into the new title."""
    data_dir, _uf = _store_library("ja")
    src = _epub(tmp_path / "消滅世界.epub", ["<p>吾輩は猫である。名前はまだ無い。</p>" * 40] * 2)
    assert extract.extract(src, "消滅世界", "ja", section="now", value="300", spawn=False).in_library
    store = _open("ja")
    try:
        rows = [(i, r) for i, r in store.conn.execute("SELECT id, rel_path FROM items ORDER BY id")
                if r.startswith(f"{ls.CONTENT_FOLDER}/消滅世界/")]
        change = store.remove([i for i, _r in rows], {i: ls.trash_file(data_dir, r) for i, r in rows})
    finally:
        store.close()
    assert extract.extract(src, "消滅世界", "ja", section="now", value="300", spawn=False, as_new=True).freed
    store = _open("ja")
    try:
        trash = store.trash_rows(change.trash_ids)
        rel_paths = {r["id"]: ls.put_back(data_dir, r["trashed_path"], r["rel_path"])[0] for r in trash}
        store.undo(change, rel_paths=rel_paths)
        back = [r for (r,) in store.conn.execute(
            f"SELECT rel_path FROM items WHERE id IN ({','.join('?' * len(rows))})", [i for i, _r in rows])]
    finally:
        store.close()
    assert len(back) == len(rows) and all(r.startswith(f"{ls.CONTENT_FOLDER}/消滅世界 2/") for r in back)


def test_B4_add_as_new_renames_only_the_names_removed_title_never_another_one(tmp_path):
    """Mutant S1: two books in Removed; *Add as new* of 消滅世界 renames its rows and title alone — the other removed
    book keeps its place and its name (its Put back unchanged)."""
    _store_library("ja")
    other = _epub(tmp_path / "別の本.epub", ["<p>どこで生れたかとんと見当がつかぬ。</p>" * 30])
    _x, other_ids, _o = _removed_book(tmp_path, "ja", name="別の本", epub=other)
    store = _open("ja")
    try:
        before = {r["id"]: (r["rel_path"], r["entry"]) for r in store.trash_rows(other_ids)}
    finally:
        store.close()
    src, _ids, _old = _removed_book(tmp_path, "ja")
    assert extract.extract(src, "消滅世界", "ja", section="now", value="300", spawn=False, as_new=True).freed
    store = _open("ja")
    try:
        assert {r["id"]: (r["rel_path"], r["entry"]) for r in store.trash_rows(other_ids)} == before
        titles = sorted(e["title"] for e in store.removed())
    finally:
        store.close()
    assert titles == sorted(["別の本", "消滅世界 2"])


def test_B4_a_name_only_processed_holds_is_taken_and_never_freed(tmp_path):
    """Mutant F2: an earlier split into Processed only (no title, nothing removed) — taken as before, never offered."""
    data_dir, _uf = _store_library("ja")
    os.makedirs(os.path.join(data_dir, "Processed", "旅の記録"))
    answer = extract.check_name("旅の記録", "ja")
    assert answer.taken and answer.removed is None and not answer.free


def test_B4_with_no_library_yet_a_taken_name_is_answered_as_before(tmp_path):
    """No store at all (a first run): the check still answers — taken, the free name proposed, nothing freed."""
    os.makedirs(os.path.join(get_data_path("ja"), "Processed", "旅の記録"))
    assert extract.check_name("旅の記録", "ja") == extract.Name("旅の記録", True, "旅の記録 2", None, False)


def test_B4_a_missing_episode_of_another_title_under_the_name_never_lets_it_go(tmp_path):
    """Mutant F1: half the book removed, the other half made a title of its own and its files gone (rows kept,
    missing): the folder holds only the marker and the removed rows' title holds nothing — but an item is still listed
    under the name, so it is never freed."""
    data_dir, _uf = _store_library("ja")
    src = _epub(tmp_path / "消滅世界.epub", ["<p>吾輩は猫である。名前はまだ無い。</p>" * 40] * 2)
    assert extract.extract(src, "消滅世界", "ja", section="now", value="300", spawn=False).in_library
    store = _open("ja")
    try:
        rows = [(i, r) for i, r in store.conn.execute("SELECT id, rel_path FROM items ORDER BY id")
                if r.startswith(f"{ls.CONTENT_FOLDER}/消滅世界/")]
        half = len(rows) // 2
        store.remove([i for i, _r in rows[:half]], {i: ls.trash_file(data_dir, r) for i, r in rows[:half]})
        store.split_work([i for i, _r in rows[half:]], "別の題")
    finally:
        store.close()
    for _i, r in rows[half:]:
        os.remove(os.path.join(data_dir, *r.split("/")))
    answer = extract.check_name("消滅世界", "ja", src)
    assert answer.taken and not answer.free


def test_B4_a_title_the_learner_renamed_still_comes_back_apart(tmp_path):
    """Mutant S4: he had named the book 「Vanishing World」 (its old name kept among its names). After *Add as new*
    its old name is dropped from its names, so the new 消滅世界 is never joined to it by show."""
    data_dir, _uf = _store_library("ja")
    src = _epub(tmp_path / "消滅世界.epub", ["<p>吾輩は猫である。名前はまだ無い。</p>" * 40] * 2)
    assert extract.extract(src, "消滅世界", "ja", section="now", value="300", spawn=False).in_library
    store = _open("ja")
    try:
        rows = [(i, r, w) for i, r, w in store.conn.execute("SELECT id, rel_path, work_id FROM items ORDER BY id")
                if r.startswith(f"{ls.CONTENT_FOLDER}/消滅世界/")]
        old_work = rows[0][2]
        store.rename_work(old_work, "Vanishing World")
        store.remove([i for i, _r, _w in rows], {i: ls.trash_file(data_dir, r) for i, r, _w in rows})
    finally:
        store.close()
    assert extract.extract(src, "消滅世界", "ja", section="now", value="300", spawn=False, as_new=True).freed
    store = _open("ja")
    try:
        new = {w for r, w in store.conn.execute("SELECT rel_path, work_id FROM items")
               if r.startswith(f"{ls.CONTENT_FOLDER}/消滅世界/")}
        title, titles = store.conn.execute("SELECT title, titles FROM works WHERE id = ?", (old_work,)).fetchone()
    finally:
        store.close()
    assert new and old_work not in new
    assert title == "Vanishing World" and "消滅世界" not in json.loads(titles)

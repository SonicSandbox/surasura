"""Settings › Content's three rows from the mock (Sonic 2026-11-05: "2 lines. One for the term and then a row or 2 for
the buttons"): *Videos open in*, *Books open in* — what ▶ opens a file with — and *When you finish something* — what
finishing does to its new cards. Here the rules (Qt-free): which program ▶ hands a file to, how the finish choice is
read, the catalog's rows and what each change writes, and a settings import from another PC.

The window's halves (the picker, ▶'s open, the finish toast) are in tests/qt/test_open_in_and_finish_window.py."""
import json
import os

import pytest

from app import settings_manager, settings_placement
from app.qt import settings_catalog as catalog
from app.qt import settings_strings as S
from app.services import play, settings_io

MPV = "C:\\Program Files\\mpv\\mpv.exe"
CALIBRE = "C:\\Program Files\\Calibre2\\ebook-viewer.exe"
EPISODE = "D:\\アニメ\\ぼっち・ざ・ろっく！\\ぼっち・ざ・ろっく！ 第05話.mkv"
BOOK = "D:\\本\\本好きの下剋上 第一部 1.epub"
CHOSEN = {"open_video": "program", "open_video_program": MPV, "open_book": "program", "open_book_program": CALIBRE}


# --- which program ▶ hands a file to -------------------------------------------------------------------------------- #
def test_a_video_and_an_epub_each_go_to_their_own_chosen_program():
    assert play.program_for(CHOSEN, EPISODE, "anime") == MPV
    assert play.program_for(CHOSEN, EPISODE, None) == MPV                      # no type yet: a video (`media_type`'s rule)
    assert play.program_for(CHOSEN, BOOK, "lightnovel") == CALIBRE
    assert play.program_for(CHOSEN, BOOK.upper(), "book") == CALIBRE           # (the extension in any case)


def test_the_default_is_the_systems_program_and_a_kept_program_waits_while_default_is_picked():
    """`default` (the shipped value) opens with what Windows opens it with; a program kept from before is never used
    while the choice says default — it is only kept for picking "program" again."""
    assert play.program_for(settings_manager.DEFAULT_SETTINGS, EPISODE, "anime") is None
    assert play.program_for({}, EPISODE, "anime") is None
    assert play.program_for(dict(CHOSEN, open_video="default"), EPISODE, "anime") is None
    assert play.program_for(dict(CHOSEN, open_book="default"), BOOK, "book") is None


@pytest.mark.parametrize("path, media", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),     # YouTube: always its site
    ("D:\\オーディオブック\\本好きの下剋上 01.m4b", "audiobook"),     # audio: the system's player
    ("D:\\動画\\ぼっち 第05話.mp3", None),                              # an audio file a video's ▶ found
    ("D:\\本\\本好きの下剋上 第一部 1.txt", "book"),                     # a book with no EPUB: its text file
    ("", "anime"), (None, "anime"),
])
def test_links_audio_and_text_never_go_to_a_chosen_program(path, media):
    assert play.program_for(CHOSEN, path, media) is None


@pytest.mark.parametrize("held", ["", "   ", None, 7, ["C:\\mpv.exe"]])
def test_program_chosen_but_none_kept_or_hand_edited_reads_as_the_default(held):
    assert play.program_for(dict(CHOSEN, open_video_program=held), EPISODE, "anime") is None


def test_a_kept_program_is_read_stripped_and_a_settings_object_without_get_is_no_choice():
    assert play.program_for(dict(CHOSEN, open_video_program=f"  {MPV} "), EPISODE, "anime") == MPV
    assert play.program_for(None, EPISODE, "anime") is None


# --- the finish choice --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("held, read", [("ask", "ask"), ("keep", "keep"), ("out", "out"), ("Keep", "ask"),
                                        (None, "ask"), (True, "ask"), ("", "ask")])
def test_the_finish_choice_reads_a_hand_edited_value_as_the_question(held, read):
    assert settings_manager.finish_cards({"finish_cards": held}) == read


def test_the_finish_choice_defaults_to_asking_as_before_the_setting():
    assert settings_manager.DEFAULT_SETTINGS["finish_cards"] == "ask"
    assert settings_manager.finish_cards({}) == settings_manager.finish_cards(None) == "ask"


# --- the catalog's rows -------------------------------------------------------------------------------------------- #
def test_the_three_rows_sit_in_content_stacked_each_key_placed_as_never_a_run():
    content = [row.id for row in catalog.rows("content")]
    assert content.index("open_video") < content.index("open_book") < content.index("finish_cards")
    assert set(catalog.STACKED) == {"open_video", "open_book", "finish_cards"}
    for key in ("open_video", "open_video_program", "open_book", "open_book_program", "finish_cards"):
        assert settings_placement.PLACED[key] == "neither" and key in catalog.reachable()
        assert key in settings_manager.DEFAULT_SETTINGS
    for row_id in catalog.STACKED:
        row = catalog.ROW[row_id]
        assert row.kind == "choice" and catalog.visible(row, {}, "ja") and catalog.visible(row, {}, "zh")
        assert row.label and row.help and row.tip               # its ? and its tooltip (the Qt guide)


def test_a_program_rows_second_choice_reads_choose_until_one_is_kept_then_its_name_and_path():
    row = catalog.ROW["open_video"]
    assert catalog.options(row, {}, "ja") == (("default", "Your default player", ""), ("program", S.PROGRAM_PICK, ""))
    assert catalog.option_tips(row, {})["program"] == S.OPTION_TIPS["open_video"]["program"]
    kept = {"open_video_program": MPV}
    assert catalog.options(row, kept, "ja")[1] == ("program", "mpv", "")
    assert catalog.option_tips(row, kept) == dict(S.OPTION_TIPS["open_video"], program=MPV)
    assert catalog.program_label(catalog.ROW["open_book"], {"open_book_program": "/usr/bin/foliate"}) == \
        ("foliate", "/usr/bin/foliate")


def test_every_choice_has_its_own_tip():
    for row_id in catalog.STACKED:
        row = catalog.ROW[row_id]
        tips = catalog.option_tips(row, CHOSEN)
        assert all(tips.get(v) for v, _label, _line in catalog.options(row, CHOSEN, "ja")), row_id


@pytest.mark.parametrize("row_id, new, written", [
    ("open_video", "program", {"open_video": "program"}),           # the program kept: only the choice
    ("open_book", "program", {"open_book": "program"}),
    ("finish_cards", "out", {"finish_cards": "out"}),
    ("finish_cards", "keep", {"finish_cards": "keep"}),
])
def test_a_change_writes_only_its_choice_never_the_kept_program(row_id, new, written):
    settings = {"open_video_program": MPV, "open_book_program": CALIBRE}
    assert catalog.change(catalog.ROW[row_id], settings, "ja", new) == (written, None)


def test_picking_default_keeps_the_program_and_picking_what_is_held_writes_nothing():
    row = catalog.ROW["open_video"]
    assert catalog.change(row, CHOSEN, "ja", "default") == ({"open_video": "default"}, None)
    assert catalog.change(row, CHOSEN, "ja", "program") == ({}, None)
    assert catalog.change(catalog.ROW["finish_cards"], {}, "ja", "ask") == ({}, None)
    with pytest.raises(ValueError):
        catalog.change(catalog.ROW["finish_cards"], {}, "ja", "delete")      # never a choice that isn't there


def test_search_finds_each_row_by_its_words_and_its_choices():
    assert "open_video" in catalog.find("vlc", {}, "ja")
    assert "open_book" in catalog.find("epub", {}, "ja")
    assert "finish_cards" in catalog.find("leave them out", {}, "ja")
    assert "open_video" in catalog.find("mpv", {"open_video_program": MPV}, "ja")     # the program's name too


# --- a settings import from another PC ------------------------------------------------------------------------------ #
def _exported(tmp_path, settings):
    path = tmp_path / "Surasura settings 2026-11-05.json"
    path.write_text(json.dumps({settings_io.MARK: settings_io.FORMAT, "version": settings_io.app_version(),
                                "language": "ja", "settings": settings}, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_an_imported_program_this_pc_lacks_goes_back_to_the_default_with_its_choice(tmp_path):
    """Like Anki Miner's place: a program path from another PC is never run here (▶ would fail, or run something
    else of that name) — the choice and the path go back to their defaults; one this PC has is kept."""
    here = tmp_path / "mpv.exe"
    here.write_bytes(b"MZ")
    plan = settings_io.read(_exported(tmp_path, dict(CHOSEN, open_video_program=str(here),
                                                     finish_cards="out")))
    assert plan.refused is None
    assert plan.settings["open_video"] == "program" and plan.settings["open_video_program"] == str(here)
    assert "open_book" not in plan.settings and "open_book_program" not in plan.settings
    assert plan.settings["finish_cards"] == "out"


def test_an_imported_program_that_isnt_text_is_dropped_and_default_alone_is_kept(tmp_path):
    plan = settings_io.read(_exported(tmp_path, {"open_video": "program", "open_video_program": 5,
                                                 "open_book": "default", "open_book_program": ""}))
    assert "open_video" not in plan.settings and "open_video_program" not in plan.settings
    assert plan.settings["open_book"] == "default" and plan.settings["open_book_program"] == ""

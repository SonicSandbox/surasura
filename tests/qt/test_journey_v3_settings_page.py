"""Settings › App › Journey under journey v3 (J-SET; SPEC §1.4, the settings table, Sonic's answers 2026-11-22): the
Settings page with the journey's rows (`settings_catalog._journey_rows`).

What a wrong answer would cost: a row that writes another key, or more than its own; the section somewhere the page's
⚙ doesn't say (it says Settings › App › Journey); Reset (Journey) without its Undo; an old learner's Zen Mode or File
name shown as no choice at all.
"""
import pytest
from PyQt6.QtWidgets import QApplication

from app.qt import settings_catalog as catalog
from app.qt import settings_strings as S
from app.services import journey_settings as J
from tests.qt.test_settings_page import ALL_ON, make_page
from tests.qt import test_settings_page as T


@pytest.fixture(autouse=True)
def _no_direct_save(monkeypatch):
    from app import settings_manager

    def refused(*_a, **_k):
        raise AssertionError("the page saved settings.json itself: only the settings service may")
    monkeypatch.setattr(settings_manager, "save_settings", refused)
    monkeypatch.setattr(settings_manager, "save_keys", refused)


OLD = {"theme": "Zen Mode", "source_display": "filename", "zen_limit": 75, "show_words_per_day": False,
       "logic": {"inline_completed_files": True, "hide_audio_button": True, "context": {"max_contexts": 7}}}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_under_v3_every_visible_control_writes_exactly_its_keys(qapp, language):
    T.test_every_visible_control_writes_exactly_its_keys_and_a_per_language_one_keeps_the_other_language(
        qapp, language)


def test_journey_sits_under_app_between_connections_and_app_with_the_pages_rows(qapp):
    page, _store = make_page(ALL_ON, "ja")
    order = list(page.slabs)
    assert order.index("connect") < order.index("reading") < order.index("app")
    assert page.slabs["reading"].isVisibleTo(page)
    for row_id in catalog._V3_ROWS:
        assert page.rows[row_id].isVisibleTo(page), row_id
    for gone in ("theme", "source_display", "inline_completed_files", "hide_audio_button", "zen_limit",
                 "show_words_per_day", "max_contexts"):
        assert gone not in page.rows, gone
    assert page.rows["sentences_per_word"].isVisibleTo(page)


def test_an_old_learners_zen_mode_and_file_name_show_as_night_and_icon_name_and_nothing_is_written(qapp):
    page, store = make_page(OLD, "ja")
    QApplication.processEvents()
    assert page.rows["journey_theme"].controls[0].value() == J.NIGHT
    assert page.rows["journey_source"].controls[0].value() == "full"
    assert page.rows["sentences_per_word"].controls[0].value() == 7
    assert store.calls == []


def test_reset_journey_puts_the_pages_rows_back_in_one_write_and_its_undo_puts_them_back(qapp):
    data = dict(OLD, theme="Modern Light", journey_pitch="hidden", journey_word_size="l", journey_keys="dvorak",
                journey_first_meeting=False)
    page, store = make_page(data, "ja")
    page.slabs["reading"].reset.click()
    (changes, update), = store.calls
    assert update is None
    assert changes == {"theme": "Dark Flow", "source_display": "icon", "journey_pitch": "shown",
                       "journey_word_size": "m", "journey_keys": "qwerty", "journey_first_meeting": True}
    message, undo = page.last_toast
    assert message == S.RESET_DONE.format(section=S.SECTIONS["reading"])
    store.land()
    store.calls.clear()
    undo()
    assert store.calls == [({"theme": "Modern Light", "source_display": "filename", "journey_pitch": "hidden",
                             "journey_word_size": "l", "journey_keys": "dvorak", "journey_first_meeting": False},
                            None)]

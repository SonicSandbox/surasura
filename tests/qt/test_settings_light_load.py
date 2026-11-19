"""Settings' rows for mining that leaves the PC usable (Michi-LP, 2026-11-18; words PROVISIONAL).

- *Clips cut at once* under Anki & mining's More options: Automatic names this PC's number; a pick writes the number.
- The Beta list (the AI voice's group) at the end of App: *Run Anki Miner at low priority*, a switch, off. Without the
  AI voice's module (the public build) the list's name still stands above it.

What a wrong answer would cost: a switch under no Beta name (read as a finished feature); an Automatic that hides what
it picks; a pick that writes text ("3") Connect then reads as automatic.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QLabel

from app.connect import power
from app.qt import settings_controls as sc
from tests.qt.test_settings_page import ALL_ON, EVERYTHING, Recorder, _no_direct_save, make_page  # noqa: F401


def _beta_names(page):
    return [w for w in page.findChildren(QLabel)
            if w.objectName() == "settingsgroup" and w.accessibleName() == "Beta" and w.isVisibleTo(page)]


@pytest.mark.parametrize("found", [EVERYTHING, EVERYTHING - {"modules.irodori"}])
def test_the_low_priority_switch_stands_under_the_beta_name_off_with_or_without_the_ai_voice(qapp, found):
    page, store = make_page(ALL_ON, "ja", found=found)
    view = page.rows["connect_low_priority"]
    assert view.isVisibleTo(page)
    assert isinstance(view.controls[0], sc.Toggle) and view.controls[0].value() is False
    names = _beta_names(page)
    assert len(names) == 1, "one Beta list"
    assert names[0].geometry().top() < view.geometry().top()


def test_the_low_priority_switch_hides_with_connect_off(qapp):
    page, _store = make_page(dict(ALL_ON, connect_enabled=False), "ja", found=EVERYTHING - {"modules.irodori"})
    assert not page.rows["connect_low_priority"].isVisibleTo(page)
    assert _beta_names(page) == [], "no Beta name over nothing"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_clips_at_once_says_this_pcs_number_and_a_pick_writes_the_number(qapp, monkeypatch, language):
    monkeypatch.setattr(power, "clip_cuts", lambda setting="auto", **k: 4)
    page, store = make_page(ALL_ON, language)
    control = page.rows["connect_clip_cuts"].controls[0]
    assert isinstance(control, sc.Select) and control.value() == "auto"
    assert control._options[0][1] == "Automatic · 4 here"
    store.calls.clear()
    control.set_value(3)
    control.changed.emit(3)
    assert store.calls == [({"connect_clip_cuts": 3}, None)]

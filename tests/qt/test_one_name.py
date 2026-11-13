"""One name for Surasura's cards (Kantan-B2; AUDIT B6, Sonic's yes 2026-11-12): the learner sees *Cards made for you*
everywhere — setup, the Settings row, help, the bar, Needs you, 順's window, Piyo — and never *Connect*, *Make cards for
me* or *Surasura Connect* (Connect stays the feature's name in code, logs, the CLI's verbs, the README and the notes).

What a wrong answer would cost: one thing with four names (setup's *Cards made for you*, Settings' *Make cards for me*,
*Connect is off*, help's *Making cards*) — a new learner can't tell they are the same switch.

Every learner-facing string table is scanned: the window's (`app/qt/strings.py`, `settings_strings`, `wizard_strings`),
the rows' and Needs you's words (`view_rows.STRINGS`, `needs.STRINGS`), Connect's lines the window shows (`feed`'s,
the runner's waits) and 順's window (`modules/junban/qt_strings`, when it is there).
"""
import re

import pytest

pytest.importorskip("PyQt6")

from app.connect import feed, runner
from app.qt import settings_strings as S
from app.qt import strings
from app.qt import wizard_strings as W
from app.services import needs, view_rows

NAME = "Cards made for you"
OLD = re.compile(r"Make cards for me|Surasura Connect|(?<!Anki)\bConnect\b(?! with us)")   # (*Making cards*, the
#                                                         strip's job while it runs, is an activity, not the name)


def _texts(value, where):
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _texts(v, f"{where}[{k!r}]")
    elif isinstance(value, (tuple, list)):
        for i, v in enumerate(value):
            yield from _texts(v, f"{where}[{i}]")


def _module_texts(module, names=None):
    for name in names or dir(module):
        if name.isupper():
            yield from _texts(getattr(module, name), f"{module.__name__}.{name}")


def test_the_feature_is_called_cards_made_for_you_where_it_is_named():
    assert S.ROWS["connect_enabled"][0] == NAME and S.ROWS["connect_needs_miner"][0] == NAME
    assert S.ROWS["setup_mining"][0] == NAME
    assert strings.HELP_CARDS["cards"][0] == NAME
    assert W.MINER_READY.startswith(NAME) and W.STEPS["cards"] == NAME
    assert feed.OFF_CONNECT.startswith(NAME)


def test_no_learner_string_names_it_connect_or_make_cards_for_me():
    tables = [*_module_texts(strings), *_module_texts(S), *_module_texts(W),
              *_texts(view_rows.STRINGS, "view_rows.STRINGS"), *_texts(needs.STRINGS, "needs.STRINGS"),
              *_module_texts(feed, ("OFF_CONNECT", "OFF_AUTOMATION", "UNREADABLE", "NEXT_LOOK", "NEXT_START",
                                    "NEXT_UPDATING")),
              *_module_texts(runner, ("TURN", "BOOKS_WAIT", "AUDIO_WAIT", "SWITCHED_OFF", "REPLACED",
                                      "SHELF_NO_JUNBAN", "SEVERAL_FILES", "MINE_REFUSED_SAY", "MINE_FAILED_SAY"))]
    try:
        from modules.junban import qt_strings as junban
        tables += list(_module_texts(junban))
    except ImportError:
        pass
    old = [(where, text) for where, text in tables if OLD.search(text)]
    assert old == []

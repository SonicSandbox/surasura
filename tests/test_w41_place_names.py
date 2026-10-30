"""W4.1 (release check): the window says 3.0's place names — Current, Soon, Goal, Finished, New arrivals — never 2.x's
(NOW, 6+ Months, Graduated) or the folders behind them (CLAUDE.md §6). A bare 2.x tier folder on a Needs-you card reads
as its 3.0 place, and every word the window shows from `app.qt.strings` is checked."""
import re

import pytest

from app import library_store
from app.qt import settings_strings, strings, wizard_strings
from app.services import needs

OLD = re.compile(r"\bNOW\b|6\+ Months|HighPriority|LowPriority|GoalContent")


@pytest.mark.parametrize("folder, place", [("HighPriority", "Current"), ("LowPriority", "Soon"),
                                           ("GoalContent", "Goal")])
def test_a_bare_2x_tier_folder_reads_as_its_3_0_place(folder, place):
    assert needs.shown(folder) == place
    # a path under it drops the folder (unchanged): the show's own path, never the tier's name
    assert needs.shown(f"{folder}/ゆるキャン△/01.srt") == "ゆるキャン△/01.srt"


def test_no_label_is_a_2x_name():
    assert not [v for v in library_store.TIER_LABELS.values() if OLD.search(v)]


def _words(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _words(v)
    elif isinstance(value, (tuple, list)):
        for v in value:
            yield from _words(v)


def test_no_window_string_names_a_2x_place_or_folder():
    """Why: the ⋯ menu's Soon hover said "after what's in NOW" through alpha 6 — a 2.x word a 3.0 learner never sees."""
    found = [(module.__name__, name, w) for module in (strings, settings_strings, wizard_strings)
             for name, value in vars(module).items() if name.isupper() for w in _words(value) if OLD.search(w)]
    assert found == []

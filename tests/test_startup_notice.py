"""The start-up notice (P2.1 row 2.1.7): what another program registered while Surasura was closed, named once in the
window's bottom bar when it opens.

What a wrong answer would cost: a drop hato made overnight that nobody mentions sits at the top of NOW (or in New
arrivals) unnoticed; one named at every start, or one the user dragged in themselves named as an arrival, teaches the
user to ignore the line. With Connect's preview off the window must not import any of it. Real subtitles, synthetic
titles, the test's own root.
"""
import sys
import types

from app.connect import notice
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _hato(episode, producer="hato"):
    rec = c.record(c.drop(f"Example Show - {episode:02d}.ja.srt"), f"video-{episode}", producer=producer)
    code, line = h.call("register", "--pairing", c.write_record(rec))
    assert code == 0, line
    return line


def test_drops_registered_while_closed_are_named_once():
    c.library()
    assert notice.at_open("ja") is None, "the first session with Connect on: from now on"
    notice.at_close("ja")
    for episode in (5, 6, 7):
        _hato(episode)
    assert notice.at_open("ja") == "3 episodes arrived from hato while Surasura was closed"
    assert notice.at_open("ja") is None, "named once"


def test_one_drop_and_two_programs_read_plainly():
    c.library()
    notice.at_open("ja")
    _hato(5)
    assert notice.at_open("ja") == "1 episode arrived from hato while Surasura was closed"
    _hato(6)
    _hato(7)
    _hato(8, producer="another-tool")
    assert notice.at_open("ja") == "3 episodes arrived while Surasura was closed: 2 from hato, 1 from another-tool"


def test_what_arrived_while_the_window_was_open_is_never_named_at_the_next_start():
    c.library()
    notice.at_open("ja")
    _hato(5)                                    # seen in the open window
    notice.at_close("ja")
    assert notice.at_open("ja") is None


def test_a_persons_placements_and_the_placing_rules_are_no_arrivals():
    c.library(arrivals=True, arrivals_straight_sources=["hato"])
    notice.at_open("ja")
    with c.store() as s:
        item = s.ids("now")[-1]
    h.call("place", "--file", str(item), "--to", "now", "--source", "user")
    _hato(5)                                    # placed by hato, then moved by the rule: one arrival
    assert notice.at_open("ja") == "1 episode arrived from hato while Surasura was closed"


def test_opening_with_nothing_new_writes_nothing():
    c.library()
    notice.at_open("ja")
    stored = c.store_state()
    assert notice.at_open("ja") is None
    notice.at_close("ja")
    assert c.store_state() == stored


def test_with_the_preview_off_the_window_imports_nothing_of_it(monkeypatch):
    from app import main
    for name in [m for m in sys.modules if m.startswith("app.connect")]:
        monkeypatch.delitem(sys.modules, name)
    window = types.SimpleNamespace(_current_settings={"connect_enabled": False})
    main.MasterDashboardApp._arrivals_notice(window)
    assert not [m for m in sys.modules if m.startswith("app.connect")]

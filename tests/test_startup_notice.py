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
    c.library(arrivals=True, placing_rules={"hato": "top"})
    notice.at_open("ja")
    with c.store() as s:
        with s._writing():                      # the library as the user had it: added days ago
            s.conn.execute("UPDATE items SET added_at = '2026-10-01T09:00:00.000000Z'")
        item = s.ids("now")[-1]
        s.move([item], "now")                   # the user's own drag in the window
    code, _line = h.call("place", "--file", str(item), "--to", "soon",
                         "--source", "my-script")    # another program moving an item the user already had
    assert code == 0
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


def test_the_dashboards_save_carries_connects_keys_only_as_the_file_holds_them():
    """Intent review #18: a save never drops `connect_enabled` / `placing_rules` the user set, and never writes them into
    a settings.json that lacks them (or one that can't be read)."""
    import os
    from app import main
    keys = ["connect_enabled", "placing_rules"]
    path = os.path.join(h.root(), "settings.json")
    assert main.carry_as_written({"theme": "x"}, keys) == {"theme": "x"}, "no file"
    h.write_settings(connect_enabled=True, placing_rules={"hato": "top"})
    assert main.carry_as_written({}, keys) == {"connect_enabled": True, "placing_rules": {"hato": "top"}}
    h.write_settings()
    assert main.carry_as_written({}, keys) == {}, "a file without them"
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert main.carry_as_written({}, keys) == {}, "a file that can't be read"


def test_connect_losing_track_is_said_once_with_its_dates_and_count():
    """✅ P2.1-3: the 2.x preview's start-up notice says it once (3.0's Needs you offers the list)."""
    from app.connect import inbox
    from app.connect.ledger import Ledger
    c.library()
    notice.at_open("ja")
    with c.store() as s, Ledger() as ledger:
        s.bookkeeping({"mine_line": 2}, copy_carries=True)
        inbox.consume(s, "ja", ledger)
        s.bookkeeping({"reader_epoch:connect": -1})         # a Repair's new epoch: a gap
        inbox.consume(s, "ja", ledger)
        since = ledger.gaps("ja")[0]["since"][:10]
    line = notice.at_open("ja")
    assert line.startswith(f"Connect lost track of your moves from {since} to ") and \
        line.endswith(": 2 episodes in the top 20 have no cards"), line
    assert notice.at_open("ja") is None, "said once"

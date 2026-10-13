"""`status` shows Connect's record only while the Connect preview is on (P2.5, item C3).

What a wrong answer would cost: with the preview off, a caller that polls `status` would see a Connect record for a
feature the user has not switched on, and a status read would make a ledger file that Connect never asked for (a
read-only poll that creates a database). With the preview on, the record must say "Up to date" on a fresh install,
where no ledger exists yet, and `--words` must still be accepted by the verb.

In-process calls (`h.call`) through a real language folder under the test root; Anki is a closed port and nothing
starts Connect.
"""
import os

from app.path_utils import get_user_files_path
from app.connect import ledger as connect_ledger
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _set_up_ja():
    """The language's folders exist, as Surasura leaves them once it has been opened: `status` refuses before that."""
    os.makedirs(get_user_files_path("ja"), exist_ok=True)


def test_status_has_no_connect_record_while_the_preview_is_off():
    """Preview off (the default): the status line carries no `connect` key at all, so an old caller reads it as before."""
    _set_up_ja()
    h.write_settings()
    code, line = h.call("status")
    assert code == 0, line
    assert "connect" not in line, "a switched-off preview must not show Connect's record"


def test_status_shows_up_to_date_when_the_preview_is_on_and_no_ledger_exists():
    """Preview on, fresh install: no ledger yet, so the record is the empty one (`Up to date`, idle, not running)."""
    _set_up_ja()
    h.write_settings(connect_enabled=True)
    code, line = h.call("status")
    assert code == 0, line
    connect = line["connect"]
    assert connect["line"] == "Up to date"
    assert connect["state"] == "idle"
    assert isinstance(connect["running"], bool), "running is a flag, never a count or missing"


def test_status_with_the_preview_on_never_makes_a_ledger_file():
    """A poll is a look: reading Connect's record must not create the ledger the record came from (a status read that
    wrote a database would also change the folder under the window)."""
    _set_up_ja()
    h.write_settings(connect_enabled=True)
    code, line = h.call("status")
    assert code == 0, line
    assert not os.path.exists(connect_ledger.path()), "status made a ledger file"


def test_status_words_is_accepted_with_the_preview_on():
    """`--words` asks for Connect's preview list; the verb must take it (and still answer with the record)."""
    _set_up_ja()
    h.write_settings(connect_enabled=True)
    code, line = h.call("status", "--words")
    assert code == 0, line
    assert line["connect"]["line"] == "Up to date"

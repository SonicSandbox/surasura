"""`status --lang zh` with Connect's preview on carries Chinese's own record and Anki Miner's update notice (P3.2-AMN,
as the mutant pass found it untested, 2026-10-13).

What a wrong answer would cost: a caller asking about Chinese would get an error (Japanese's record looked up in a
record read for Chinese only) instead of Connect's line, and so no update notice either.

In-process calls (`h.call`) through a real language folder under the test root; Anki is a closed port and nothing
starts Connect.
"""
import os

from app.path_utils import get_user_files_path
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def test_status_for_chinese_carries_chineses_record_and_the_notice():
    """Mutant B42: the record handed to the CLI is the asked language's (zh), with the notice."""
    from app.connect import am_release, setup
    os.makedirs(get_user_files_path("zh"), exist_ok=True)
    h.write_settings(connect_enabled=True)
    setup.write_record({"anki_miner": {"path": "C:/x/AnkiMiner.exe", "app": "3.7.0"}})
    page = "https://github.com/0xzerolight/anki_miner/releases/tag/v3.8.0"
    am_release.check({"connect_enabled": True}, fetch=lambda: {"tag_name": "v3.8.0", "html_url": page})
    code, line = h.call("status", "--lang", "zh")
    assert code == 0, line
    assert line["language"] == "zh"
    assert line["connect"]["line"] == "Up to date"
    # alpha 4 M5: the notice offers the approved release, whatever newer one a check kept
    assert line["connect"]["anki_miner_update"] == {"version": am_release.APPROVED, "url": am_release.approved_page()}

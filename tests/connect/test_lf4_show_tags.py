"""Laptop round 8 #50 (LF4-3 = A): every card Connect makes names the show it was mined from.

Sonic: "I'd add the show title it came from, and probably the show that it's targeted for in case the 2 are
different". This file holds the first half, fixed at mining: Connect's run file sends Anki Miner the job's tag and
`Surasura::from::<show>` (Anki Miner joins an episode's tags to its profile's, whitespace-separated). The second
half, the show it's ordered for, moves with Junban's order (`modules/junban/tests/test_lf4_show_tags.py`).

What a wrong answer costs: a tag Anki splits into several (a title with spaces), a wrong show named, or a card that
loses Connect's own job tag (its batch could no longer be found in Anki). Against the fake Anki Miner and a real
library store built from the suite's subtitles; never Anki.
"""
import json

from app.connect import library, runfile
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.test_anki_miner import batch, words  # noqa: F401  (fixtures)


def test_a_show_title_is_one_tag():
    assert runfile.from_tag("Re Zero kara Hajimeru Isekai Seikatsu") == \
        "Surasura::from::Re_Zero_kara_Hajimeru_Isekai_Seikatsu"
    assert runfile.from_tag("陰の実力者になりたくて!  01") == "Surasura::from::陰の実力者になりたくて!_01"
    assert runfile.from_tag('Steins::Gate "0"') == "Surasura::from::Steins:Gate_0", "no extra level, no quotes"
    assert runfile.from_tag("") == "" and runfile.from_tag(None) == ""


def _episode(done):
    with open(done["run_file"], encoding="utf-8") as f:
        return json.load(f)["episodes"][0]


def test_the_run_file_carries_the_jobs_tag_and_the_show(batch, fake_miner, words):  # noqa: F811
    episode = _episode(batch(show="Hibike Euphonium"))
    assert episode["tags"].split() == ["surasura::connect::job-1", "Surasura::from::Hibike_Euphonium"]


def test_no_show_known_is_the_jobs_tag_alone(batch, fake_miner, words):  # noqa: F811
    assert _episode(batch())["tags"] == "surasura::connect::job-1"


def test_the_show_is_the_items_work_title():
    c.library()
    with c.store() as s:
        item_id = library.mine_line(s)[0]
        work = s.item(item_id).get("work_id")
        title = s.conn.execute("SELECT title FROM works WHERE id = ?", (work,)).fetchone()[0]
        assert library.show_title(s, item_id) == title
        assert library.show_title(s, 999999) is None


def test_a_title_in_decomposed_unicode_is_tagged_as_anki_keeps_it():
    # round 2 B5: a folder from a Mac names ざ as さ + ゛ (NFD); Anki keeps tags composed — the label must match it
    import unicodedata
    title = unicodedata.normalize("NFD", "ざつ旅")
    assert runfile.from_tag(title) == "Surasura::from::" + unicodedata.normalize("NFC", "ざつ旅")


def test_a_title_that_cannot_be_written_as_utf8_gives_no_tag_never_a_refused_run():
    # round 2 B8: a lone surrogate (an NTFS name) would make the run file refused at every attempt
    assert runfile.from_tag("Bocchi\ud800") == ""


def test_a_store_read_error_leaves_the_cards_without_a_show_never_fails_the_mining(monkeypatch):
    import sqlite3
    from types import SimpleNamespace

    from app.connect import runner

    class _Store:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def busy(_store, _item):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(library, "show_title", busy)
    steps = SimpleNamespace(_open=lambda lang: _Store())
    assert runner.Steps.show(steps, "ja", {"item_id": 1}) is None

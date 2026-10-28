"""F-6 (alpha 4 follow-ups register, NOTE): the report labels a card Connect made on the row it was made for
(`static_html_generator._connect_rows`, from Connect's record `made_words`), so that record is part of the render
signature (CLAUDE.md: anything the report is drawn from that no run reads goes in `compute_render_signature`).

What a wrong answer would cost: a Generate that reopens the old report after Connect made a card — its "In Anki" label
missing, or left on a row whose card was deleted — until something else re-rendered it.

The suite's real files are the library; the words and note ids are the kind Connect records (ヒトリ, 冒険).
"""
from app import analyzer
from app.connect import library
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _signature(lang="ja"):
    return analyzer.compute_render_signature(analyzer.parse_analysis_args(["--language", lang]))


def test_a_card_connect_makes_or_loses_re_renders_the_report_and_nothing_else_does():
    c.library("ja")
    with c.store("ja") as s:
        first, second = s.ids("now")[:2]
    assert library.made_fingerprint("ja") is None, "no record yet: no part"
    before = _signature()
    assert _signature() == before, "read twice, nothing changed: the same signature"
    with c.store("ja") as s:
        s.record_made(first, [("ヒトリ", [1789711432600]), ("冒険", [1789711432601, 1789711432602])])
    made = _signature()
    assert made != before, "a card Connect made re-renders"
    with c.store("ja") as s:
        s.record_made(first, [("ヒトリ", [1789711432600])])     # nothing new: no write, the same record
    assert _signature() == made
    with c.store("ja") as s:
        s.record_made(second, [("気配", [1789711432603])])
    again = _signature()
    assert again != made, "another episode's card too"
    with c.store("ja") as s:
        assert library.notes_gone(s, [1789711432601])          # a card deleted in Anki: its note id goes
    assert _signature() != again, "a card deleted re-renders (its label comes off)"


def test_chinese_reports_never_read_connects_record_so_it_is_no_part_of_theirs():
    c.library("zh")
    before = _signature("zh")
    with c.store("zh") as s:
        s.record_made(s.ids("now")[0], [("冒险", [1789711432700])])
    assert _signature("zh") == before


def test_the_label_switched_off_reads_no_record():
    c.library("ja", anki_backlog_on_generate=False)
    before = _signature()
    with c.store("ja") as s:
        s.record_made(s.ids("now")[0], [("ヒトリ", [1789711432600])])
    assert _signature() == before


def test_a_report_is_signed_with_the_record_it_was_drawn_from_never_one_read_after(monkeypatch):
    """Review (F-6): a card recorded while the report is drawn must leave the report signed with the record read
    before it — the next press then re-renders — never with the newer one (an old report taken as current)."""
    from app.connect import library as lib
    c.library("ja")
    args = analyzer.parse_analysis_args(["--language", "ja"])
    monkeypatch.setattr(lib, "made_fingerprint", lambda language: [3, "2026-10-28T10:00:00", 40.0])
    drawn_before = analyzer.signed_render(args, None, True, None)        # nothing recorded when it was drawn
    assert drawn_before != analyzer.compute_render_signature(args), "the next check sees the newer record"
    assert analyzer.signed_render(args, None, True) == analyzer.compute_render_signature(args)

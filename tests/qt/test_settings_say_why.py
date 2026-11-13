"""Settings say why (Kantan-S1; Kantan-X's EXPERIENCE.md §4–§5 and mock 03, Sonic: "clarification of sorts",
"Everything earns its place, with the user focus"; every word PROVISIONAL): the five places that hide value — Card order
(順 Junban), Fill your cards (Backfill), Cards made for you, Practise with your AI (Piyo), Subtitles for videos without
them (hato) — each say their plain name first (the module's name small beside it), one line on what you get, and, only
while something is missing, one line on what it needs with *Show me* (the page's own `reveal`) where that is elsewhere.

What a wrong answer would cost: a learner who meets *Backfill — fill your cards* and five switches never learns what a
card gains or why nothing happens (Anki closed); a needs line that says "needs Anki" while Anki is open (a wrong word is
worse than none: it shows only once Anki has answered, never while unread or being checked); a *Show me* that goes
nowhere; a renamed section a learner who knew "Junban" can no longer find by search; a needs line that costs a read on
the window's thread (it comes only from the Connection row's own answer).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.qt import settings_catalog as catalog
from app.qt import settings_controls as sc
from app.qt import settings_live as live
from app.qt import settings_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_settings_live import fakes, make  # noqa: F401 (the live rows' fake reads)
from tests.qt.test_settings_page import ALL_ON, _no_direct_save  # noqa: F401 (the autouse guard)

CLOSED = {"ok": False, "version": None, "missing": [], "error": "Anki is not running", "running": False}
OPEN = {"ok": True, "version": 6, "missing": [], "error": ""}
WHY_SECTIONS = ("junban", "backfill")


# --- the words (Qt-free) ------------------------------------------------------------------------------------------- #
def test_the_two_sections_say_their_plain_name_first_and_the_modules_name_small():
    assert S.SECTIONS["junban"] == "Card order" and S.SECTION_TAGS["junban"] == "順 Junban"
    assert S.SECTIONS["backfill"] == "Fill your cards" and S.SECTION_TAGS["backfill"] == "Backfill"
    assert set(S.SECTION_TAGS) == set(S.SECTION_WHY) == set(WHY_SECTIONS)        # a tag only with its why line
    for section_id in WHY_SECTIONS:
        assert S.SECTION_WHY[section_id] and "\n" not in S.SECTION_WHY[section_id]  # one line each


def test_the_rows_say_their_plain_name_first_with_the_tools_name_small():
    assert S.ROWS["practice_ai"][0] == "Practise with your AI" and S.ROW_TAGS["practice_ai"] == S.PRACTICE_NAME
    assert S.ROWS["hato"][0] == "Subtitles for videos without them" and S.ROW_TAGS["hato"] == "hato"
    # Cards made for you is already its plain name (Kantan-B2's one name): no tag
    assert "connect_enabled" not in S.ROW_TAGS and "connect_needs_miner" not in S.ROW_TAGS


@pytest.mark.parametrize("key", ["closed", "no_addon", "unsure", "denied", "busy"])
def test_card_order_and_fill_your_cards_need_anki_while_it_answers_not_connected(key):
    for section_id in WHY_SECTIONS:
        assert live.section_needs(section_id, key) == (S.NEEDS_ANKI, "anki_connection")


@pytest.mark.parametrize("key", [None, "unknown", "checking", "connected", "syncing", "failed"])
def test_no_needs_line_while_anki_is_unread_being_checked_or_answering(key):
    # never a wrong line: unread / a Check under way say nothing; connected or syncing needs nothing; a sync that
    # failed with Anki open and answering (a deck's or a field's error) never says "needs Anki" (adversary r1 #3)
    for section_id in WHY_SECTIONS:
        assert live.section_needs(section_id, key) is None
    assert live.section_needs("level", "closed") is None              # a section without a why line has no needs


def test_card_order_with_its_switch_off_needs_nothing_from_anki():
    # (adversary r1 #9) the line would send the learner away from the one thing to do: turn 順 on
    assert live.section_needs("junban", "closed", {"enable_junban": False}) is None
    assert live.section_needs("junban", "closed", {"enable_junban": True}) == (S.NEEDS_ANKI, "anki_connection")


def test_show_me_names_where_it_goes():
    assert live.where("anki_connection") == f"{S.SECTIONS['anki']} › {S.ROWS['anki_connection'][0]}"
    assert S.SHOW_ME_TIP.format(where=live.where("anki_connection")).endswith("Connection")


@pytest.mark.parametrize("query, section_id", [("junban", "junban"), ("順", "junban"), ("card order", "junban"),
                                               ("backfill", "backfill"), ("fill your cards", "backfill")])
def test_a_renamed_section_is_found_by_its_old_name_and_its_new_one(query, section_id):
    # a learner who knew "Junban" / "Backfill" finds the same rows by search, and so does one who reads the new name
    # (adversary r1 #7: "card order" found nothing); the section's every row, not only the ones that say it
    settings = dict(ALL_ON, target_language="ja")
    ctx = frozenset(catalog.MODULES)
    rows = {r.id for r in catalog.rows(section_id) if catalog.visible(r, settings, "ja", ctx)}
    assert rows and rows <= set(catalog.find(query, settings, "ja", ctx))
    assert not set(catalog.find("fill your cards", settings, "ja", ctx)) & {r.id for r in catalog.rows("level")}


def test_a_word_of_a_new_section_name_alone_never_floods_the_search_with_its_rows():
    # (adversary r2 #1) "order" or "cards" looks for a setting, not for every row of Card order
    settings = dict(ALL_ON, target_language="ja")
    ctx = frozenset(catalog.MODULES)
    assert "junban_later_flag" not in catalog.find("order", settings, "ja", ctx)
    assert "junban_later_flag" not in catalog.find("card", settings, "ja", ctx)      # (the name's first word alone)
    assert "junban_later_flag" in catalog.find("card order", settings, "ja", ctx)


# --- the page --------------------------------------------------------------------------------------------------------- #
def test_the_two_slabs_show_the_plain_name_the_tag_and_the_why_line_and_no_other_slab_does(qapp, fakes):  # noqa: F811
    page, store, shell = make(fakes, ALL_ON)
    for section in catalog.SECTIONS:
        slab = page.slabs[section.id]
        assert slab.name.text() == section.name.upper()
        if section.id in WHY_SECTIONS:
            assert slab.tag.text() == S.SECTION_TAGS[section.id] and slab.tag.isVisibleTo(page)
            # Kantan-S2 (Sonic 2026-11-13: "I don't like subtitles"): what you get is behind the head's ?, never a
            # line in sight; nothing missing yet, so no line under the head at all
            assert slab.why.toolTip() == S.SECTION_WHY[section.id] and slab.why.isVisibleTo(page)
            assert slab.why.parentWidget() is slab.head and slab.why.accessibleName()
            assert not slab.about.isVisibleTo(page)
            assert S.SECTION_WHY[section.id] not in _lines_in_sight(slab)
        else:
            assert not slab.tag.isVisibleTo(page) and not slab.about.isVisibleTo(page)
            assert not slab.why.isVisibleTo(page)
    assert page.nav["junban"].text() == "Card order · 順" and page.nav["backfill"].text() == "Fill your cards"
    assert page.nav["backfill"].accessibleName() == "Fill your cards · Backfill"          # the module's name heard
    assert "Backfill" in page.nav["backfill"].toolTip() and "順 Junban" in page.slabs["junban"].name.accessibleName()
    assert store.calls == []                                                        # showing it writes nothing


def test_the_needs_line_comes_with_ankis_answer_show_me_reveals_the_connection_and_it_goes_once_connected(
        qapp, fakes, monkeypatch):  # noqa: F811
    page, store, shell = make(fakes, ALL_ON)
    for section_id in WHY_SECTIONS:                       # Anki not looked at yet: no line (never a wrong one)
        assert not page.slabs[section_id].needs.isVisibleTo(page)
    reads = len(fakes.calls)
    fakes.probe = CLOSED
    page.live.check()
    assert wait_until(lambda: all(page.slabs[s].needs.isVisibleTo(page) for s in WHY_SECTIONS))
    assert fakes.names()[reads:] == ["probe_anki"]        # the Connection row's own look: no read of its own
    revealed = []
    monkeypatch.setattr(page, "reveal", lambda target: revealed.append(target) or True)
    for section_id in WHY_SECTIONS:
        slab = page.slabs[section_id]
        assert slab.needs_line.text() == S.NEEDS_ANKI
        assert isinstance(slab.show_me, sc.Door) and slab.show_me.text() == S.SHOW_ME
        assert slab.show_me.toolTip() == S.SHOW_ME_TIP.format(where=live.where("anki_connection"))
        slab.show_me.click()
    assert revealed == ["anki_connection", "anki_connection"]
    fakes.probe = OPEN
    page.live.check()
    assert wait_until(lambda: not any(page.slabs[s].needs.isVisibleTo(page) for s in WHY_SECTIONS))
    assert store.calls == []


def test_a_sync_on_its_way_keeps_the_needs_line_no_flicker_at_each_sync(qapp, fakes):  # noqa: F811
    # (adversary r1 #2) every automatic sync says "syncing" before its answer: the line must not go and come back
    from app.services import automation as automation_module
    page, store, shell = make(fakes, ALL_ON)
    page.bridge.automation_changed.emit(automation_module.State("anki-closed", "ja", 0, None, "Anki is closed", None, 3))
    assert wait_until(lambda: page.slabs["junban"].needs.isVisibleTo(page))
    page.bridge.automation_changed.emit(automation_module.State("syncing", "ja", 0, None, "", None, 3))
    QApplication.processEvents()
    assert page.slabs["junban"].needs.isVisibleTo(page) and page.slabs["backfill"].needs.isVisibleTo(page)


def test_turning_junban_off_takes_card_orders_needs_line_away(qapp, fakes):  # noqa: F811
    page, store, shell = make(fakes, ALL_ON)
    fakes.probe = CLOSED
    page.live.check()
    assert wait_until(lambda: page.slabs["junban"].needs.isVisibleTo(page))
    store.file["enable_junban"] = False
    page.bridge.settings_written.emit(["enable_junban"])
    assert wait_until(lambda: page.slabs["junban"].needs_now is None)
    assert not page.slabs["junban"].needs.isVisibleTo(page)


def test_a_check_under_way_keeps_the_needs_line_as_it_was_no_jump(qapp, fakes):  # noqa: F811
    page, store, shell = make(fakes, ALL_ON)
    fakes.probe = CLOSED
    page.live.check()
    assert wait_until(lambda: page.slabs["junban"].needs.isVisibleTo(page))
    page.live._checking = True                            # (as `check` leaves it while its look runs)
    page.live._paint_anki()
    assert page.slabs["junban"].needs.isVisibleTo(page)
    page.live._checking = False


def test_a_slab_built_after_ankis_answer_gets_its_needs_line_as_it_is_built(qapp, fakes):  # noqa: F811
    # the slabs are built in slices (a reveal may build Card order first): Anki's answer can come before the slab
    # exists, so each row built in it paints its needs line from what is known — no wait for Anki's next answer
    page, store, shell = make(fakes, ALL_ON)
    fakes.probe = CLOSED
    page.live.check()
    assert wait_until(lambda: page.slabs["junban"].needs.isVisibleTo(page))
    slab = page.slabs["backfill"]                         # the later slab alone not painted yet (Card order is)
    slab.set_needs(None)
    assert not slab.needs.isVisibleTo(page)
    page.live._built(catalog.rows("backfill")[0].id)
    assert slab.needs.isVisibleTo(page) and slab.needs_line.text() == S.NEEDS_ANKI


def test_a_slab_not_shown_yet_still_takes_its_needs_line(qapp, fakes):  # noqa: F811
    # (mutant M21) a slab hidden (mid-build, or by a search) takes its line directly, so it is right when it shows
    page, store, shell = make(fakes, ALL_ON)
    slab = page.slabs["backfill"]
    slab.setVisible(False)
    fakes.probe = CLOSED
    page.live.check()
    assert wait_until(lambda: page.slabs["junban"].needs_now is not None)
    assert slab.needs_now == (S.NEEDS_ANKI, "anki_connection") and slab.needs_line.text() == S.NEEDS_ANKI


def test_show_me_really_lands_on_the_connection_row(qapp, fakes, monkeypatch):  # noqa: F811
    page, store, shell = make(fakes, ALL_ON)
    fakes.probe = CLOSED
    page.live.check()
    assert wait_until(lambda: page.slabs["backfill"].needs.isVisibleTo(page))
    washed, wash = [], page._wash
    monkeypatch.setattr(page, "_wash", lambda view: washed.append(view) or wash(view))
    page.slabs["backfill"].show_me.click()
    QApplication.processEvents()
    assert washed == [page.rows["anki_connection"]]               # washed: the reveal's own mark (frozen motion
    #                                                               ends the wash at once, so it's caught as it starts)


def _lines_in_sight(widget):
    from PyQt6.QtWidgets import QLabel
    return [lab.text() for lab in widget.findChildren(QLabel) if lab.isVisibleTo(widget) and lab.text()
            and lab.objectName() != "helpmark"]


def test_the_rows_show_their_tag_and_their_what_you_get_line_behind_the_question_mark(qapp, fakes):  # noqa: F811
    page, store, shell = make(fakes, dict(ALL_ON, connect_enabled=False))
    for row_id, tag in S.ROW_TAGS.items():
        view = page.rows[row_id]
        assert view.tag.text() == tag and view.tag.isVisibleTo(page), row_id
        assert view.label.text() == S.ROWS[row_id][0]
    hato = page.rows["hato"]                                                     # Kantan-S2: what you get behind its ?
    assert not hato.help.isVisibleTo(page) and hato.mark.isVisibleTo(page) and hato.mark.toolTip() == S.ROWS["hato"][1]
    assert page.rows["practice_ai"].help.isVisibleTo(page)       # what goes to that AI's company: read before pressing
    assert page.live.parts["hato"]["mark"].accessibleName().startswith("hato:")   # (r1 #5) "not found" is hato's
    others = [v for r, v in page.rows.items() if r not in S.ROW_TAGS]
    assert others and not any(v.tag.isVisibleTo(page) for v in others)


def test_a_rows_tag_fits_in_its_words_width_so_the_label_wraps_and_never_runs_under_it(qapp, fakes):  # noqa: F811
    # (adversary r2, seen at text size L, 1000 px: the tag sat over the label and squeezed the status) the label's
    # least width leaves the tag's room inside the words' least width
    page, store, shell = make(fakes, ALL_ON)
    for row_id in S.ROW_TAGS:
        view = page.rows[row_id]
        view._fit_title()
        view._least = view.label.maximumWidth()           # the words held to the label's own width (a narrow row)
        view._fit_title()
        room = view.label.minimumWidth() + view.title.spacing() + view.tag.sizeHint().width()
        assert room <= view._least, row_id


@pytest.mark.parametrize("row_id, found", [("connect_enabled", True), ("connect_needs_miner", False)])
def test_cards_made_for_you_says_what_you_get_behind_its_question_mark(qapp, fakes, row_id, found):  # noqa: F811
    from tests.qt.test_settings_page import EVERYTHING
    tools = EVERYTHING if found else EVERYTHING - {"miner_found"}
    page, store, shell = make(fakes, dict(ALL_ON, connect_enabled=False), found=tools)
    view = page.rows[row_id]
    assert view.isVisibleTo(page) and not view.help.isVisibleTo(page)         # Kantan-S2: no line under the label
    assert view.mark.isVisibleTo(page)
    if row_id == "connect_enabled":                       # (r1 #1, blocking) its ? still opens the help card
        assert view.mark.card == "cards" and view.mark.toolTip().startswith(S.ROWS["connect_enabled"][1])
    if row_id == "connect_needs_miner":           # what you get + what it needs, behind the ?; *Set up Anki Miner ›*
        assert view.mark.toolTip() == f"{S.CARDS_WHY}{S.SEP}{S.NEEDS_MINER}"            # stays: the action
        assert page.live.parts["connect_needs_miner"]["door"].isVisibleTo(page)

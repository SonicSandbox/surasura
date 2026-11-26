"""ONB-1: setup's *How would you like to start?* (`wizard.StartPage`), the page after *Your list* while D1's *Make cards
for your first 20 episodes?* line waits for a yes. Tier: looks — behaviour tests, no mutants.

What a wrong answer would cost: cards mined before the learner said yes (the page is an offer, not a start); a
*Generate* that waits for the whole list before the start can be chosen (the first run held for minutes); a *Start*
pressed early that loses the choice; the page shown with Connect off (a start that can't make cards); a *Skip* that
answers the first cards' line (Needs you's card gone, nothing made).

The wizard calls `setup_wizard`'s START part through `test_wizard`'s stand-ins (`FakeApi`) extended with its names;
`start_numbers` is the real one (pure), over a view with a learner's own shows.
"""
import types

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from app import settings_manager
from app.qt import strings
from app.qt import wizard as W
from app.qt import wizard_strings as S
from app.services import setup_wizard as SW
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems
from tests.qt.test_wizard import NUMBERS, FakeApi, FakeMiner, GenState, go_to, make, miner_look, settle  # noqa: F401

BOCCHI = [("ep-bocchi-01", "第1話"), ("ep-bocchi-02", "第2話"), ("ep-bocchi-03", "第3話")]
FRIEREN = [("ep-frieren-%02d" % i, "第%d話" % i) for i in range(1, 18)]


def view(known=True):
    """The window's view: ぼっち・ざ・ろっく！ at the top, then 葬送のフリーレン — each episode's *N new* from the plan
    (None while the list is still being made)."""
    def row(work, title, eps, n):
        return types.SimpleNamespace(work_id=work, title=title, episodes=[
            types.SimpleNamespace(id=i, label=label, n_new=n if known else None) for i, label in eps])
    return types.SimpleNamespace(rows=[row("w-bocchi", "ぼっち・ざ・ろっく！", BOCCHI, 12),
                                       row("w-frieren", "葬送のフリーレン", FRIEREN, 9)])


class Reader:
    """The window's library reader: `view()` from any thread."""

    def __init__(self, v):
        self.v = v

    def view(self):
        return self.v


class StartApi(FakeApi):
    """`FakeApi` + the START part: `start_offered`, `start_items` (Connect's top-N rule), `start_numbers` (the real,
    pure one), `start_cards` (the yes: recorded, or raising), and `save(START)`'s writes."""

    def __init__(self, offered=True, fails=False, **kw):
        super().__init__(numbers=NUMBERS, **kw)
        self.offered = offered
        self.fails = fails
        self.started = []

    def writes(self, page, answers, settings, language):
        if page == SW.START:
            return {"connect_backlog_cap": {language: SW.START_SIZES[answers["start"]][1]}}
        return super().writes(page, answers, settings, language)

    def start_offered(self, settings, language):
        self.calls.append(("start_offered", language))
        return self.offered

    def start_items(self, language):
        self.calls.append(("start_items", language))
        top = [i for i, _l in BOCCHI + FRIEREN]
        return {s: top[:SW.START_SIZES[s][0]] for s in SW.starts()}

    def start_numbers(self, items, v, per_day):
        return SW.start_numbers(items, v, per_day)

    def start_cards(self, language, settings, start):
        self.started.append((language, start))
        if self.fails:
            raise OSError("the library store is held by another program")
        return ["ep-bocchi-01"]


def to_start(make, api=None, known=False, data=None):
    """A wizard on *Your list* with the first cards' line offered, then Generate pressed: (wiz, shell, api, settings,
    seen) — the list still being made."""
    api = api or StartApi()
    wiz, shell, api, settings, _m = make(api=api, data=dict({"connect_enabled": True, "words_per_day": 5},
                                                            **(data or {})))
    shell.services.library = Reader(view(known))
    settings.flushed = 0
    settings.flush = lambda timeout=None: setattr(settings, "flushed", settings.flushed + 1)   # (the service's own)
    seen = []
    wiz.finished.connect(seen.append)
    go_to(wiz, "level")
    assert wait_until(lambda: wiz.shown()[-1] == "start")
    settle(wiz)
    QTest.keyClick(wiz, Qt.Key.Key_Return)                         # Enter = Generate
    shell.bridge.generate_changed.emit(GenState("running", "Counting words", 3, 10))
    return wiz, shell, api, settings, seen


def test_generate_goes_straight_on_to_your_start_while_the_list_is_made_and_nothing_is_mined(make):
    wiz, shell, api, settings, seen = to_start(make)
    assert wiz.page.id == "start" and wiz.generating and seen == []
    assert wiz.steps.ids[-1] == "start" and wiz.steps.current == wiz.pages.index(wiz.by_id["start"])
    assert ("finish",) in api.calls and wait_until(lambda: ("generate",) in api.calls)    # (Generate: on a worker)
    assert wiz.btn_back.isHidden(), "no Back: the list is already being made (PROVISIONAL)"
    wiz.back()                                                     # (a Back press by key or reader: still here —
    assert wiz.page.id == "start"                                  # *Your list* would be held while the list is made)
    assert wiz.btn_next.text() == S.START and wiz.btn_next.isEnabled() and wiz.btn_next.toolTip() == S.START_TIP
    from app.services import generate
    assert wiz.say_line.text() == S.MAKING_SHORT.format(pct=generate.percent(GenState("running", "Counting words", 3, 10)))
    assert api.started == [] and not [c for c in api.calls if c[:2] == ("save", "start")], "nothing before Start"
    assert wiz.page.channel.value() == "full", "Full start pre-picked"


def test_without_the_first_cards_line_generate_closes_as_before(make):
    api = StartApi(offered=False)
    wiz, shell, api, settings, _m = make(api=api, data={"connect_enabled": True})
    seen = []
    wiz.finished.connect(seen.append)
    go_to(wiz, "level")
    assert wait_until(lambda: ("start_offered", "ja") in api.calls)
    assert wiz.shown() == W.ORDER and wiz.steps.ids == W.ORDER
    wiz.next()
    assert wiz.page.id == "level"
    shell.bridge.generate_changed.emit(GenState("running", "Counting words", 3, 10))
    shell.bridge.generate_changed.emit(GenState("current"))
    assert seen == ["generated"]


def test_another_language_drops_the_offer_until_its_own_line_is_read(make):
    # why: the offer is one language's line — Back to page 1 and another language must not reach *Your start* on it
    api = StartApi(offered=True)
    wiz, shell, api, settings, _m = make(api=api, data={"connect_enabled": True})
    go_to(wiz, "level")
    assert wait_until(lambda: wiz.shown()[-1] == "start")
    wiz._language_changed("zh")
    assert wiz._start_offered is False and wiz.by_id["start"].items is None


def test_arrows_choose_a_start_and_start_pressed_early_keeps_the_choice_and_closes(make):
    wiz, shell, api, settings, seen = to_start(make)
    full = wiz.page.cards["full"]
    full.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(full, Qt.Key.Key_Left)
    assert wiz.page.channel.value() == "small"
    settle(wiz)
    QTest.keyClick(wiz, Qt.Key.Key_Return)                         # Enter = Start, the list not made yet
    assert ("save", "start", {"start": "small"}, "ja") in api.calls
    assert settings.data["connect_backlog_cap"] == {"ja": 50}
    assert wait_until(lambda: seen == ["started"])
    assert api.started == [("ja", "small")] and settings.flushed == 1, "the cap on disk before Connect reads it"
    assert shell.bar[-1] == strings.NEEDS_FIRST_CARDS_MADE
    shell.bridge.generate_changed.emit(GenState("current"))       # the list ends after: nothing more from the wizard
    assert seen == ["started"]


def test_the_numbers_fill_in_as_the_list_is_made(make):
    wiz, shell, api, settings, seen = to_start(make)
    page = wiz.page
    assert wait_until(lambda: page.numbers is not None)
    assert page.top.text() == S.START_TOP.format(title="ぼっち・ざ・ろっく！") + " · " + S.START_PACE.format(n=5)
    small = page.cards["small"]
    assert small.big == "" and small.unit == S.START_COUNTING, "the cards aren't counted yet: counting, never 0"
    assert small.lines[0] == S.START_SHOW_EPS.format(show="ぼっち・ざ・ろっく！", first="第1話", last="第3話")
    assert api.calls.count(("start_items", "ja")) == 1
    shell.services.library.v = view(known=True)                   # the plan's *N new* came in
    wiz._library_moved()
    assert wait_until(lambda: small.big == "8")                    # 3 × 12 new = 36 cards ÷ 5 a day
    assert small.lines[1] == S.START_CARDS.format(n=36, cap=50)
    full = page.cards["full"]
    assert full.big == str(-(-(3 * 12 + 17 * 9) // 5)) and full.lines[0] == S.START_NEXT_EPS.format(
        eps=S.START_NEXT_N.format(n=20), titles=S.START_TITLES_N.format(n=2))
    assert api.calls.count(("start_items", "ja")) == 1, "the episodes are read once a page entry"
    shell.bridge.generate_changed.emit(GenState("current"))
    assert seen == [] and not wiz.generating and wiz.say_line.text() == "" and wiz.hairline.value is None


def test_skip_on_your_start_closes_with_the_first_cards_unanswered(make):
    wiz, shell, api, settings, seen = to_start(make)
    wiz.skip()
    assert seen == ["done"] and api.started == []
    assert not [c for c in api.calls if c[:2] == ("save", "start")]   # Needs you's *Make cards* card asks (PROVISIONAL)


def test_a_start_that_fails_says_so_and_closes_leaving_needs_you_asking(make):
    wiz, shell, api, settings, seen = to_start(make, api=StartApi(fails=True))
    wiz.next()
    assert wait_until(lambda: seen == ["done"])
    assert shell.bar[-1] == S.START_FAILED


def test_a_generate_that_cant_start_leaves_your_start_up(make):
    wiz, shell, api, settings, seen = to_start(make, api=StartApi(accepted=False))
    assert wait_until(lambda: not wiz.generating)
    assert seen == [] and wiz.page.id == "start" and shell.bar == [S.NOT_STARTED]
    wiz.next()
    assert wait_until(lambda: seen == ["started"])


def test_pre_studied_only_is_offered_only_with_its_switch(make, monkeypatch):
    wiz, *_ = make(api=StartApi())
    assert list(wiz.by_id["start"].cards) == ["small", "full"]
    monkeypatch.setitem(settings_manager.DEFAULT_SETTINGS, SW.PRESTUDIED_KEY, False)
    wiz, *_ = make(api=StartApi())
    assert list(wiz.by_id["start"].cards) == ["small", "full", "prestudied"]
    assert wiz.by_id["start"].cards["prestudied"].lines == ("", "")
    wiz.by_id["start"].show_numbers({"per_day": 5})
    assert wiz.by_id["start"].cards["prestudied"].unit == S.START_PACE_WORD


def test_chinese_setup_starts_on_its_own_language(make):
    wiz, shell, api, settings, seen = to_start(make, data={"target_language": "zh"})
    assert wiz.language == "zh" and wiz.page.channel.language == "zh"
    wiz.next()
    assert wait_until(lambda: seen == ["started"])
    assert api.started == [("zh", "full")] and settings.data["connect_backlog_cap"] == {"zh": 300}


def test_every_control_on_your_start_is_wired_tipped_and_named(make):
    wiz, *_ = to_start(make)
    found, walked = problems(wiz)
    assert walked >= 20 and found == []

"""`surasura-cli resort` (P2.2 row 2.2.5; P0.3 03-verbs: "Junban pins on spaced numbers"; HC-N7 as amended).

"Re-sort Anki's new cards now": the automatic reorder's own body — one deck, positions only, never while you review,
its own run snapshot while the Connect preview is on — with the user's *Study its cards first* items first (3.0) and
numbered by the one rule every Junban writer follows: the spaced ladder (E2.1) while the fast re-plan's preview is on,
2.5's dense block while it's off. What a wrong answer would cost: two writers numbering one deck two ways rewrite every
card on every turn (each write syncs to the phone), and a re-sort that ran with the preview off would change a 2.5
user's Anki behind their back. 2.x-dev keeps that rule; 3.0 (E1.1 04 §5, Haya's G2b): the spaced ladder always,
whatever the preview's box, D29 or the language say.

The Junban suite's fake collection (real Japanese words, a list in the results); never Anki.
"""
import os

import pytest

from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

FAKE_URL = "http://127.0.0.1:18765"         # nothing listens here: only the patched transport answers


@pytest.fixture
def deck(monkeypatch):
    rep = pytest.importorskip("modules.junban.tests.test_reposition")
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    rep._results(h.root(), progressive=rep._JOURNEY, library=rep._LIBRARY, floor=11)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)

    def setup(**over):
        cards, notes, _ = rep._collection(["須藤", "散歩", "図書館", "冒険", "眼鏡", "老婆"])
        fake = rep.FakeCollection(cards, notes, actions=("setSpecificValueOfCard", "multi", "suspend", "unsuspend"),
                                  **{k: over.pop(k) for k in ("reviewing", "offline") if k in over})
        # 3.0: 順 has recorded its deck for Japanese (`junban_replan_deck` / `_language`, a deck picked in 順's window
        # in Japanese) — without the pair, every automatic Junban write stands aside (Haya's G3)
        saved = rep._settings(**{**dict(junban_order="content", enable_junban=True, junban_later_tag=True,
                                        junban_later_flag=True, junban_later_suspend=True,
                                        junban_replan_deck="TheBank", junban_replan_language="ja"), **over})
        saved.pop("junban_url", None)
        h.write_settings(**{**saved, "anki_connect_url": FAKE_URL})
        return fake, rep._patched(fake)
    return setup


def _dues(fake):
    return {card_id: card["due"] for card_id, card in fake.cards.items()}


def test_with_the_connect_preview_off_it_writes_nothing(deck):
    """2.x: `resort` is the Connect preview's (P0.3 04 §5). Off, a 2.5 user's Anki is never touched."""
    fake, patched = deck(connect_enabled=False)
    with patched:
        code, line = h.call("resort")
    assert code == 0 and line["skipped"] == "the Connect preview is off", line
    assert line["moves"] == 0 and line["pinned_first"] == 0 and line["numbering"] is None
    assert fake.requests == [] and fake.writes == []


@pytest.mark.parametrize("over", [{}, {"logic": {"automation": False}}], ids=["box-off", "d29-off"])
def test_on_3_0_spaced_while_the_re_plan_preview_is_off_exactly_as_junban_auto(deck, over):
    """2.x-dev keeps 2.5's dense numbers while the re-plan preview is off
    (test_dense_while_the_re_plan_preview_is_off_exactly_as_junban_auto); 3.0 (E1.1 04 §5, Haya's G2b): spaced
    always — the box off, D29 off too — and the dry run says so as well. Still the same writes `junban --auto` makes
    on the same deck, positions only, with its own undo (Connect's run snapshot)."""
    fake, patched = deck(connect_enabled=True, junban_auto_actions=True, **over)
    with patched:
        code, preview = h.call("resort", "--dry-run")
        assert code == 0 and preview["numbering"] == "full" and fake.writes == [], preview
        code, line = h.call("resort")
    assert code == 0 and line["moves"] == preview["moves"] > 0 and line["numbering"] == "full" and line["undo"], line
    # 2.x-dev: positions only (`suspend_calls == []`); 3.0 (G1.3-8, W3.5 row 7, Haya's G2b): the run is unattended with
    # the Connect preview on, so Junban's suspend setting is followed — the cards off the list (須藤, 図書館, 眼鏡)
    # suspended and tagged `::later` after every position — and still no flag, no Surasura tag
    off = sorted(card_id for card_id, card in fake.cards.items()
                 if fake.notes[card["note"]]["fields"]["Expression"]["value"] in ("須藤", "図書館", "眼鏡"))
    assert fake.suspend_calls == [("suspend", off)] and fake.flag_writes == []
    assert {tag for _action, _notes, tag in fake.tag_calls} == {"Surasura::later"}
    resorted = _dues(fake)
    gaps = sorted(resorted.values())
    assert max(b - a for a, b in zip(gaps, gaps[1:])) > 1, "spaced, not a dense block"
    twin, patched_twin = deck(connect_enabled=True, junban_auto_actions=True, **over)
    with patched_twin:
        code, auto_line = h.call("junban", "--auto")
    assert code == 0 and auto_line["moves"] == line["moves"]
    assert _dues(twin) == resorted


def test_spaced_while_the_re_plan_preview_is_on_and_a_second_run_writes_nothing(deck):
    """The re-plan preview on: the deck is spaced out once (`full`), then only what changed moves (`delta`) — here
    nothing, so nothing is written. `junban --auto` numbers the same way (E2.1's one rule)."""
    fake, patched = deck(connect_enabled=True, junban_replan_preview=True)
    with patched:
        code, first = h.call("resort")
        assert code == 0 and first["numbering"] == "full" and first["moves"] > 0, first
        spaced_out = _dues(fake)
        code, second = h.call("resort")
    assert code == 0 and second["numbering"] == "delta" and second["moves"] == 0, second
    assert _dues(fake) == spaced_out
    gaps = sorted(due for due in spaced_out.values())
    assert max(b - a for a, b in zip(gaps, gaps[1:])) > 1, "spaced, not a dense block"
    twin, patched_twin = deck(connect_enabled=True, junban_replan_preview=True)
    with patched_twin:
        code, auto_line = h.call("junban", "--auto")
    assert code == 0 and _dues(twin) == spaced_out



def test_on_3_0_a_japanese_run_on_a_deck_recorded_for_chinese_writes_nothing(deck):
    """2.x-dev keeps 2.5's dense block for a Japanese re-sort while the preview was turned on in 順 for Chinese
    (test_dense_while_the_re_plan_preview_is_on_for_the_other_language: `replan_preview.is_on(settings, language)`,
    E3.1's rule) — it writes. 3.0 (Haya's G3): 順's deck is recorded for Chinese, so a Japanese run of it — `resort`,
    `junban --auto` and both dry runs — stands aside, naming the deck and the language it is recorded for; Anki is
    never asked."""
    fake, patched = deck(connect_enabled=True, junban_replan_preview=True, junban_replan_language="zh")
    said = "順's deck TheBank is recorded for Chinese — pick your Japanese deck in 順's window in Japanese"
    with patched:
        for verb in (("resort", "--dry-run"), ("resort",), ("junban", "--dry-run"), ("junban", "--auto")):
            code, line = h.call(*verb)
            assert code == 0 and line["skipped"] == said and line["moves"] == 0, (verb, line)
    assert fake.requests == [] and fake.writes == [] and fake.suspend_calls == []


def test_on_3_0_junban_auto_with_no_pair_recorded_for_its_language_writes_nothing(deck):
    """2.x-dev keeps no guard here: `junban --auto`, `resort` and Connect's step write `junban_deck` as given. 3.0
    (Haya's G3, the (language, deck) guard on every automatic Junban write): until 順 has recorded its deck for this
    language — a deck picked in 順's window in that language — the run and its dry run stand aside, a skip naming the
    deck and the language, as for 順 switched off; Anki is never asked. What it would cost: with the actions on, a
    Chinese run suspending and tagging every Japanese new card not on the Chinese list."""
    fake, patched = deck(connect_enabled=True, junban_auto_actions=True, junban_replan_deck="",
                         junban_replan_language="")
    said = "順's deck TheBank isn't recorded for Japanese — pick it in 順's window in Japanese"
    with patched:
        for verb in (("junban", "--auto"), ("junban", "--dry-run"), ("resort",), ("resort", "--dry-run")):
            code, line = h.call(*verb)
            assert code == 0 and line["skipped"] == said and line["moves"] == 0, (verb, line)
            assert line["undo"] is None, line
    assert fake.requests == [] and fake.writes == [] and fake.suspend_calls == [] and fake.tag_calls == []


def test_on_3_0_a_chinese_run_on_a_deck_recorded_for_japanese_writes_nothing_and_the_japanese_run_goes(deck):
    """3.0 (Haya's G3): `junban_deck` is one key for both languages. 順's deck is recorded for Japanese, so a Chinese
    `junban --auto` / `resort` stands aside — no position, no suspend, no tag — while the Japanese run on its recorded
    pair goes exactly as before: spaced, and the cards off the list suspended as the setting says."""
    fake, patched = deck(connect_enabled=True, junban_auto_actions=True)     # the pair: TheBank, Japanese
    os.makedirs(os.path.join(h.root(), "User Files", "zh"), exist_ok=True)
    said = "順's deck TheBank is recorded for Japanese — pick your Chinese deck in 順's window in Chinese"
    with patched:
        for verb in (("junban", "--auto", "--lang", "zh"), ("resort", "--lang", "zh"),
                     ("resort", "--dry-run", "--lang", "zh")):
            code, line = h.call(*verb)
            assert code == 0 and line["skipped"] == said and line["moves"] == 0, (verb, line)
        assert fake.requests == [] and fake.writes == [] and fake.suspend_calls == [] and fake.tag_calls == []
        code, line = h.call("junban", "--auto")
    assert code == 0 and line["moves"] > 0 and line["undo"], line
    off = sorted(card_id for card_id, card in fake.cards.items()
                 if fake.notes[card["note"]]["fields"]["Expression"]["value"] in ("須藤", "図書館", "眼鏡"))
    assert fake.suspend_calls == [("suspend", off)]

def test_a_dry_run_writes_nothing_and_previews_the_runs_moves(deck):
    fake, patched = deck(connect_enabled=True)
    with patched:
        code, preview = h.call("resort", "--dry-run")
        assert code == 0 and fake.writes == [] and preview["undo"] is None, preview
        code, line = h.call("resort")
    assert code == 0 and line["moves"] == preview["moves"] > 0


def test_the_automatic_reorders_guards_hold(deck):
    """All decks → needs you; reviewing → anki-busy; Anki closed → anki-closed (the shared body's answers)."""
    fake, patched = deck(connect_enabled=True, junban_scope="all")
    with patched:
        code, line = h.call("resort")
    assert code == 4 and line["code"] == "needs-you" and fake.writes == [], line
    fake, patched = deck(connect_enabled=True, reviewing=True)
    with patched:
        code, line = h.call("resort")
    assert line["code"] == "anki-busy" and fake.writes == [], line
    fake, patched = deck(connect_enabled=True, offline=True)
    with patched:
        code, line = h.call("resort")
    assert line["code"] == "anki-closed", line


def test_pinned_items_cards_first_on_the_3_0_line(deck, monkeypatch):
    """3.0 (`PINS`): the cards of the item pinned with *Study its cards first* go first, and the answer counts them."""
    connect = pytest.importorskip("modules.junban.connect")
    pins = pytest.importorskip("modules.junban.pins")
    monkeypatch.setattr(connect, "PINS", True)
    fake, patched = deck(connect_enabled=True)
    lifted = [fake.cards[c]["cardId"] for c in sorted(fake.cards)[-2:]]
    monkeypatch.setattr(pins, "groups", lambda language, cards, notes, pinned=None: [lifted])
    with patched:
        code, line = h.call("resort")
    assert code == 0 and line["pinned_first"] == 2, line
    order = sorted(fake.cards.values(), key=lambda c: (c["due"], c["cardId"]))
    assert {c["cardId"] for c in order[:2]} == set(lifted)


def test_junban_removed_it_says_so():
    """RD-S10: with the modules gone, `resort` answers `junban absent` (exit 0)."""
    from tests.test_cli_absent import _cli_without_modules
    h.seed_library("ja")
    h.write_settings(enable_junban=True, connect_enabled=True)
    code, line = _cli_without_modules("resort")
    assert code == 0 and line["skipped"] == "junban absent" and line["moves"] == 0, line


def test_a_dry_run_says_what_the_run_would_do_no_more(deck, monkeypatch):
    """A dry run asks the run's own questions first: 順 switched off, or a list older than the library, and the run
    wouldn't move a card — so neither does the dry run's answer (adversarial review #6)."""
    fake, patched = deck(connect_enabled=True, enable_junban=False)
    with patched:
        code, line = h.call("resort", "--dry-run")
    assert code == 0 and line["skipped"] == "順 is switched off" and line["moves"] == 0, line
    from app import analyzer
    fake, patched = deck(connect_enabled=True)
    monkeypatch.setattr(analyzer, "journey_is_current", lambda argv, lang: False)
    with patched:
        code, line = h.call("resort", "--dry-run")
    assert code == 0 and line["skipped"] == "the list is out of date: Generate first", line
    assert fake.requests == []


def test_on_3_0_the_deck_guard_leaves_all_decks_and_no_deck_to_the_runs_own_answer():
    """Haya's G3 guards one chosen deck: with All decks, or no deck chosen, `deck_aside` says nothing and the run's
    own answer speaks (every deck, or `needs-deck`), never "順's deck  isn't recorded" for a deck the user never
    picked, nor a guard on a leftover `junban_deck` while All decks is chosen (the planted-bug pass, row 7b)."""
    from app.cli import verbs
    unrecorded = {"junban_deck": "TheBank", "junban_replan_deck": "", "junban_replan_language": ""}
    assert verbs.deck_aside({**unrecorded, "junban_scope": "all"}, "ja") is None
    assert verbs.deck_aside({**unrecorded, "junban_scope": "deck", "junban_deck": "  "}, "ja") is None
    assert verbs.deck_aside({"junban_scope": "deck"}, "zh") is None
    assert verbs.deck_aside({**unrecorded, "junban_scope": "deck"}, "ja") == (
        "順's deck TheBank isn't recorded for Japanese — pick it in 順's window in Japanese")


def test_on_3_0_a_switched_off_junban_is_the_reason_before_the_deck(deck):
    """Both stand aside: 順 switched off and its deck not recorded for this language. The run names 順 switched off,
    the reason to fix first (turning 順 on is what lets its window record the deck); Anki is never asked."""
    fake, patched = deck(connect_enabled=True, enable_junban=False, junban_replan_deck="", junban_replan_language="")
    with patched:
        for verb in (("junban", "--auto"), ("resort",)):
            code, line = h.call(*verb)
            assert code == 0 and line["skipped"] == "順 is switched off" and line["moves"] == 0, (verb, line)
    assert fake.requests == [] and fake.writes == []

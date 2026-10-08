"""The known-from-Anki signal and its search (app/connect/known_signal.py: `signal`, `query`).

What the rule protects: a card suspended (or marked, or flagged) in Anki says "I know this", so the search must find
exactly the cards that carry every picked term, inside the chosen decks, and never Surasura's own suspensions
(Junban's "later", Connect's shelf) or Anki's leeches. What a wrong answer would cost: a wrong signal marks words
known that the learner never meant (a flood of false known words), or it turns Connect's preview on in 2.x by
accident (a request the user never asked for). Pure functions: no Anki is reached, no network, no temp folder.
"""
from app.connect import known_signal


NEVER_TERMS = "-tag:Surasura::later -tag:surasura::shelf -tag:leech"


def _on(**extra):
    """Settings with the 2.x preview on (`connect_enabled`) and anything else the test adds."""
    settings = {"connect_enabled": True}
    settings.update(extra)
    return settings


def test_default_signal_is_suspended_when_preview_on_and_no_list_saved():
    # The default term is "suspended" (Sonic: "Default to suspend"), used when settings.json has no list yet.
    assert known_signal.signal(_on()) == ["suspended"]


def test_signal_keeps_the_picked_terms_in_the_order_the_user_picked_them():
    # The "and" list is searched in the user's order; the order is kept, not sorted.
    picked = ["flag:3", "suspended", "marked"]
    assert known_signal.signal(_on(known_from_anki=picked)) == ["flag:3", "suspended", "marked"]


def test_signal_cleans_case_spaces_duplicates_and_unknown_terms():
    # A hand-edited settings.json can hold "Marked", padded spaces, a repeat and a typo; only valid terms survive,
    # each once, in first-seen order. "flag:9" is not one of the seven flags, so it is dropped.
    messy = [" Marked ", "flag:3", "marked", "flag:9", "bogus", "SUSPENDED"]
    assert known_signal.signal(_on(known_from_anki=messy)) == ["marked", "flag:3", "suspended"]


def test_empty_list_means_the_signal_is_off():
    # `known_from_anki: []` is the user's "off": nothing is searched, so nothing can be marked known.
    assert known_signal.signal(_on(known_from_anki=[])) == []


def test_signal_is_empty_when_connect_preview_is_off_even_with_terms_picked():
    # 2.x rule: with Connect's preview off, nothing of the signal runs, whatever the list says.
    settings = {"connect_enabled": False, "known_from_anki": ["suspended", "marked"]}
    assert known_signal.signal(settings) == []


def test_signal_is_empty_when_connect_enabled_key_is_missing():
    # A settings.json that never mentions Connect is a preview-off install: the default list must not apply.
    assert known_signal.signal({"known_from_anki": ["suspended"]}) == []


def test_signal_is_empty_with_no_settings_at_all():
    # The dashboard can call with None before settings load; that must answer "off", not crash.
    assert known_signal.signal(None) == []


def test_a_single_term_saved_as_text_is_read_as_a_one_term_list():
    # A hand-written settings.json may say "marked" rather than ["marked"]; it reads as the one term.
    assert known_signal.signal(_on(known_from_anki="marked")) == ["marked"]


def test_query_ands_the_terms_inside_the_decks_and_excludes_surasura_and_leeches():
    # Both terms must hold (AND), the deck scope is a single OR-group, and the three exclusions are always appended.
    text = known_signal.query(["suspended", "flag:3"], ["日本語::読書"])
    assert text == f'(deck:"日本語::読書") is:suspended flag:3 {NEVER_TERMS}'


def test_query_maps_marked_to_its_tag_and_passes_flags_through():
    text = known_signal.query(["marked"], ["日本語"])
    assert text == f'(deck:"日本語") tag:marked {NEVER_TERMS}'


def test_query_ors_several_decks_inside_one_scope_group():
    # Two decks are one OR-group: a card in either deck counts, and a duplicate deck is searched once.
    text = known_signal.query(["suspended"], ["日本語::読書", "日本語::会話", "日本語::読書"])
    assert text == f'(deck:"日本語::読書" OR deck:"日本語::会話") is:suspended {NEVER_TERMS}'


def test_query_escapes_quotes_in_a_deck_name():
    # A deck name holding a double quote must not close the quoted search term early (it becomes \").
    text = known_signal.query(["suspended"], ['My "quoted" deck'])
    assert text == f'(deck:"My \\"quoted\\" deck") is:suspended {NEVER_TERMS}'


def test_query_is_none_with_no_terms_or_no_decks():
    # Nothing to search for: None (the caller skips the Anki request), never a search for every card.
    assert known_signal.query([], ["日本語"]) is None
    assert known_signal.query(["suspended"], []) is None

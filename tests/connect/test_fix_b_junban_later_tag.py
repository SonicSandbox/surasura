"""Fix B, the known-from-Anki search: Junban's later tag counts as never, under the parent the user named.

What a wrong answer would cost: a user who named a Junban tag ("MyTag") would see cards Junban parked for later
(`MyTag::later`) marked as known words, because the search only excluded `Surasura::later`. The search must exclude
the later tag under the named parent, and still the Surasura one. With no parent named (or "Surasura") the later tag
is excluded once. No Anki is reached: `query` only builds the search text.
"""
from app.connect import known_signal


def test_a_named_junban_tag_later_is_never_counted_and_so_is_surasura_later():
    # Why: the parent the user named owns its own later tag; Surasura's stays excluded as well.
    search = known_signal.query(["suspended"], ["日本語"], {"junban_tag": "MyTag"})
    assert "-tag:MyTag::later" in search
    assert "-tag:Surasura::later" in search


def test_with_no_parent_named_or_surasura_the_later_tag_is_excluded_once():
    # Why: the parent is Surasura here, so the extra exclusion must not repeat the built-in one.
    for settings in (None, {}, {"junban_tag": "Surasura"}):
        search = known_signal.query(["suspended"], ["日本語"], settings)
        assert search.count("-tag:Surasura::later") == 1, settings


def test_take_its_new_cards_out_suspends_are_never_counted_under_the_named_parent_or_surasura():
    # Why (P4.1 L2, TF fix 1; D23): *Take its new cards out* suspends a show's unstudied cards and tags them
    # `<junban_tag>::out` (`unlisted.out_tag`). With the default signal (suspended) every one of them would mark its
    # word known — a whole show's words, none of them learnt. Both the named parent's and Surasura's are excluded.
    search = known_signal.query(["suspended"], ["日本語"], {"junban_tag": "MyTag"})
    assert "-tag:MyTag::out" in search
    assert "-tag:Surasura::out" in search
    for settings in (None, {}, {"junban_tag": "Surasura"}, {"junban_tag": "surasura"}):
        search = known_signal.query(["suspended"], ["中文"], settings)
        assert search.lower().count("-tag:surasura::out") == 1, settings

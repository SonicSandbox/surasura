"""tests/guard_lints.py: the three lints for the bugs people kept finding, on this tree and on a planted mistake each.
Read from the source, never run or imported: each fails at once on every machine.

What a wrong answer costs: a name only a test's stand-in carries is a feature silently off in the shipped app (a search
hit that opens Current instead of its own place); a second piece writing to Anki suspends cards another piece owns
(Connect's shelf: 236 cards behind Junban's back); a second reader of a shared idea disagrees with its owner (another
list, another deck, another pair of titles, another song test); a name defined twice keeps whichever came last.
"""
import os
import textwrap

from tests import guard_lints as G


def _plant(root, rel, source):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(source))
    return rel


# --- this tree ------------------------------------------------------------------------------------------------------ #
def test_every_window_name_the_app_reads_is_on_the_real_window_or_a_listed_seam():
    found = G.names_off_the_window()
    assert G.unexplained_names(found) == [], G.name_message(G.unexplained_names(found))
    assert G.stale_names(found) == [], G.stale_message(G.stale_names(found), "NAME_SEAMS")


def test_every_anki_write_is_a_listed_pieces_and_no_entry_is_left_over():
    found = G.anki_writes()
    assert G.unexplained_writes(found) == [], G.write_message(G.unexplained_writes(found))
    assert G.stale_writes(found) == [], G.stale_message(G.stale_writes(found), "ANKI_WRITERS")


def test_every_reader_of_a_shared_idea_is_its_owner_or_listed_and_no_entry_is_left_over():
    found = G.shared_readers()
    assert G.unexplained_readers(found) == [], G.reader_message(G.unexplained_readers(found))
    assert G.stale_readers(found) == [], G.stale_message(G.stale_readers(found), "SHARED_READERS")


def test_no_name_is_defined_twice_in_one_block_and_every_store_function_is_bound_once():
    found = G.duplicate_definitions()
    assert found == [], G.duplicate_message(found)
    twice, unbound = G.store_aliases()
    assert twice == [], f"{G.STORE_FILE}: bound again (the later binding wins): {twice} — keep one"
    assert unbound == [], f"{G.STORE_FILE}: a `_store_*` function no `Store.x = …` binds: {unbound} — bind it or " \
                          f"take it out"


def test_every_allowlist_entry_says_why_and_every_anki_writer_names_its_piece_and_row():
    assert all(isinstance(why, str) and len(why) > 20 for why in G.NAME_SEAMS.values())
    assert all(piece and row and len(why) > 10 for piece, row, why in G.ANKI_WRITERS.values())
    assert all(len(why) > 10 for owners in G.SHARED_OWNERS.values() for why in owners.values())
    assert all(len(why) > 10 for why in G.SHARED_READERS.values())
    assert {idea for idea, _p, _o in G.SHARED_READERS} <= set(G.SHARED_IDEAS) == set(G.SHARED_OWNERS)


def test_the_lints_read_the_apps_code_and_never_a_vendored_copy_or_a_test():
    files = G._code()
    assert "app/qt/shell.py" in files and "app/library_store.py" in files
    assert not any("/vendor/" in f or "/tests/" in f or f.startswith("tests/") for f in files)


# --- 1. the name lint ----------------------------------------------------------------------------------------------- #
_SHELL = """
    class Services:
        def __init__(self, chores=None):
            self.chores = chores

        def start(self):
            return getattr(self, "chores", None), getattr(self, "spare", None)


    class ShellWindow:
        tabs = ()

        def __init__(self, services):
            self.services = services

        def show_tab(self, name):
            return getattr(self, "dock", None)
"""


def test_a_name_the_real_window_lacks_is_found_with_its_file_line_and_the_fix(tmp_path):
    root = str(tmp_path)
    _plant(root, G.SHELL_FILE, _SHELL)
    page = _plant(root, "app/qt/planted.py", """
        class Page:
            def __init__(self, shell):
                self.shell = shell

            def go(self, hit):
                getattr(self.shell, "show_tab", None)
                getattr(self.shell, "tabs", ())
                show = getattr(self.shell, "show_goal", None)
                chores = getattr(self.shell.services, "chores", None)
                ghost = getattr(getattr(self.shell, "services", None), "chorse", None)
                return hasattr(self._shell, "open_arrival"), getattr(hit, "anything", None)
    """)
    found = G.names_off_the_window(root, [G.SHELL_FILE, page], G.window_names(root, [G.SHELL_FILE, page]))
    assert [(f[0], f[1], f[2], f[3]) for f in found] == [
        (page, "Page.go", 9, "show_goal"), (page, "Page.go", 11, "chorse"), (page, "Page.go", 12, "open_arrival"),
        (G.SHELL_FILE, "Services.start", 7, "spare"), (G.SHELL_FILE, "ShellWindow.show_tab", 17, "dock")]
    message = G.name_message(found[:1])
    assert f"{page}:9" in message and "show_goal" in message and "NAME_SEAMS" in message


def test_a_name_the_app_assigns_on_the_window_or_its_services_counts_as_its_own(tmp_path):
    # why: `services.arrivals_worker = …` (shell.py) is a real attribute the class body never names
    root = str(tmp_path)
    _plant(root, G.SHELL_FILE, _SHELL)
    page = _plant(root, "app/qt/planted.py", """
        def wire(shell, services):
            services.worker = object()
            shell.services.bell, other = 1, 2
            setattr(shell, "hook", print)
            return getattr(services, "worker", None), getattr(shell.services, "bell", 0), getattr(shell, "hook", None)
    """)
    files = [G.SHELL_FILE, page]
    assert [f for f in G.names_off_the_window(root, files, G.window_names(root, files)) if f[0] == page] == []


def test_a_call_wrapped_over_lines_is_read_and_a_keyword_or_a_comment_never_counts_as_an_assignment(tmp_path):
    # why: the text checks that spare a parse must never skip a wrapped getattr, nor let `f(shell.x, key=1)` or a
    # comment add `x` to the window's names; every target of `a, b = …` and of a chain `w = services.c = …` counts
    root = str(tmp_path)
    _plant(root, G.SHELL_FILE, _SHELL)
    page = _plant(root, "app/qt/planted.py", """
        def wire(shell, services, later):
            later(shell.status_text, sticky=True)
            # shell.legacy_panel = None once the old dialog is gone
            services.first, services.second = 1, 2
            worker = services.third = object()
            return (getattr(
                shell, "status_text", None), getattr(shell, "legacy_panel", None),
                getattr(services, "second", 0), getattr(services, "third", 0))
    """)
    files = [G.SHELL_FILE, page]
    found = [f for f in G.names_off_the_window(root, files, G.window_names(root, files)) if f[0] == page]
    assert [(f[2], f[3]) for f in found] == [(7, "status_text"), (8, "legacy_panel")]


def test_a_listed_seam_whose_gap_is_closed_is_stale_so_an_owed_entry_comes_out_when_its_fix_lands(tmp_path):
    # why: an owed entry fails once its gap is closed (Mado-SH's two search entries did, and came out in train 58)
    allow = {("app/qt/search.py", "SearchCut.reveal", "show_goal"): "owed"}
    _plant(str(tmp_path), "app/qt/search.py", "x = 1\n")
    assert G.stale_names([], allow, root=str(tmp_path)) == list(allow)
    assert G.unexplained_names([("app/qt/search.py", "SearchCut.reveal", 9, "show_goal", "")], allow) == []
    assert G.stale_names([], allow, root=str(tmp_path / "a-checkout-without-it")) == list(allow), \
        "a public file gone (renamed, deleted) leaves its entry stale"


def test_an_entry_in_a_private_module_this_checkout_hasnt_is_no_stale_entry_but_one_in_a_module_it_has_is(tmp_path):
    # why: GitHub's public checkout has no private modules: their entries must not fail there, and only there
    allow = {("modules/koe/window.py", "Window.show"): ("Koe", "row", "why")}
    assert G.stale_writes([], allow, root=str(tmp_path)) == []
    os.makedirs(os.path.join(str(tmp_path), "modules", "koe"))
    assert G.stale_writes([], allow, root=str(tmp_path)) == list(allow)


# --- 2. the roles lint ---------------------------------------------------------------------------------------------- #
def test_an_anki_write_from_an_unlisted_place_is_found_and_a_plans_key_is_not(tmp_path):
    root = str(tmp_path)
    rel = _plant(root, "app/connect/planted.py", """
        from app import anki_connect
        def cap(url, cards, later, on):
            anki_connect.invoke("suspend", url, cards=cards)
            anki_connect.invoke("addTags" if on else "removeTags", url, notes=cards, tags="x")
            anki_connect.invoke("findCards", url, query="deck:x")
            n = len(later.get("suspend") or ()) + later.count("unsuspend")
            return [{"action": "repositionNewCards", "params": {}}, {"action": "cardsInfo"}], n

        class Adapter:
            def park(self, anki, ids):
                anki.suspend(ids)
                self.ankiconnect.set_flags(self.url, ids)
    """)
    found = G.anki_writes(root, [rel])
    assert [(f[1], f[2], f[3]) for f in found] == [
        ("cap", 4, "suspend"), ("cap", 5, "addTags"), ("cap", 5, "removeTags"), ("cap", 8, "repositionNewCards"),
        ("Adapter.park", 12, "anki.suspend()"), ("Adapter.park", 13, "self.ankiconnect.set_flags()")]
    assert G.unexplained_writes(found) == found
    message = G.write_message(found[:1])
    assert f"{rel}:4" in message and "ANKI_WRITERS" in message and "ROLES.md" in message


def test_a_listed_writer_covers_its_function_and_its_nested_ones_and_goes_stale_when_gone(tmp_path):
    allow = {("app/connect/planted.py", "Steps"): ("Connect", "row", "why")}
    found = [("app/connect/planted.py", "Steps.tag_names", 3, "addTags")]
    assert G.unexplained_writes(found, allow) == []
    _plant(str(tmp_path), "app/connect/planted.py", "x = 1\n")
    assert G.stale_writes([], allow, root=str(tmp_path)) == list(allow)


def test_a_second_reader_of_a_shared_idea_is_found_and_a_write_a_docstring_or_a_plain_word_is_not(tmp_path):
    root = str(tmp_path)
    rel = _plant(root, "app/planted.py", '''
        """The deck (`junban_deck`) and the side_by_side pair, named in prose only: ♪ marks a song."""
        import re
        SONG = re.compile(r"(?i)opening|ending")
        PLAIN = re.compile(r"\\d+")

        def deck(settings):
            """Read side_by_side here? No: this docstring only mentions it."""
            return settings.get("junban_deck"), settings["junban_deck"], {"junban_deck": "x"}

        def save(settings, deck):
            settings["junban_deck"] = deck
            return open("priority_learning_list.csv"), "♪" in deck, "side_by_side"

        def is_known_card(word):
            return word in ("ok",)
    ''')
    found = G.shared_readers(root, [rel])
    assert [(f[0], f[2], f[3]) for f in found] == [
        ("the deck", "deck", 9), ("the known test", "is_known_card", 15),
        ("the list file", "save", 13), ("the side-by-side pair", "save", 13), ("the song rule", "<module>", 4),
        ("the song rule", "save", 13)]
    message = G.reader_message(found[:1])
    assert f"{rel}:9" in message and "SHARED_READERS" in message and "app/services/setup_wizard.py:junban_deck" in message


def test_a_song_pattern_wrapped_over_lines_and_the_deck_key_in_a_tuple_of_keys_are_found(tmp_path):
    # why: a wrapped `re.compile(` must not slip past the text check; a loop over a tuple of keys reads the deck too
    root = str(tmp_path)
    rel = _plant(root, "app/planted.py", """
        import re
        SUNG = re.compile(
            r"(?i)opening|lyric")
        def decks(settings):
            return [settings.get(k) for k in ("junban_deck", "anki_sync_decks")]
    """)
    found = G.shared_readers(root, [rel])
    assert [(f[0], f[2], f[3]) for f in found] == [("the deck", "decks", 6), ("the song rule", "<module>", 4)]


def test_a_shared_ideas_owner_reads_it_freely_and_a_listed_reader_goes_stale_when_gone(tmp_path):
    owners = {"the deck": {("app/a.py", "deck_for"): "owner"}}
    readers = {("the deck", "app/b.py", "*"): "a reader"}
    found = [("the deck", "app/a.py", "deck_for", 3), ("the deck", "app/b.py", "Page.save", 9),
             ("the deck", "app/c.py", "other", 4)]
    assert G.unexplained_readers(found, owners, readers) == [found[2]]
    _plant(str(tmp_path), "app/b.py", "x = 1\n")
    assert G.stale_readers(found[:1], owners, readers, root=str(tmp_path)) == list(readers)


# --- 3. the duplicate-definition rule ------------------------------------------------------------------------------- #
def test_a_name_defined_twice_in_one_block_is_found_and_a_setter_a_branch_or_another_scope_is_not(tmp_path):
    root = str(tmp_path)
    rel = _plant(root, "app/planted.py", """
        import functools
        def copy_dirty(self):
            return 1

        class Box:
            @property
            def size(self):
                return 1

            @size.setter
            def size(self, value):
                pass

            def open(self):
                def inner():
                    pass
                return inner

            def close(self):
                def inner():
                    pass
                return inner

            def open(self):
                return 2

        if functools:
            def pick():
                pass
        else:
            def pick():
                pass

        def copy_dirty(self):
            return 2
    """)
    found = G.duplicate_definitions(root, [rel])
    assert [(f[1], f[2], f[3], f[4]) for f in found] == [("<module>", 35, "copy_dirty", 3), ("Box", 25, "open", 15)]
    message = G.duplicate_message(found[:1])
    assert f"{rel}:35" in message and "first at line 3" in message


def test_a_store_function_bound_twice_or_never_is_found(tmp_path):
    root = str(tmp_path)
    rel = _plant(root, G.STORE_FILE, """
        class Store:
            pass

        def _store_a(self):
            pass

        def _store_b(self):
            pass

        def _carry(self):
            pass

        Store.a = _store_a
        Store._carry = _carry
        Store.a = _store_a
    """)
    assert G.store_aliases(root, rel) == ([(16, "Store.a")], [(8, "_store_b")])


def test_the_text_check_never_spares_a_file_a_parse_would_find_a_twin_in():
    # why: only a file `_twice_as_text` passes is parsed; it must pass every file holding a twin in one block
    assert G._twice_as_text("def a():\n    pass\ndef a():\n    pass\n")
    assert G._twice_as_text("class A:\n    def f(self):\n        def g():\n            pass\n    def f(self):\n")
    assert not G._twice_as_text("class A:\n    def f(self):\n        pass\nclass B:\n    def f(self):\n        pass\n")

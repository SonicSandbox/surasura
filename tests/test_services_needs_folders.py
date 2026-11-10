"""K3 / K1 (alpha 4): *Needs you* holds a mostly-gone folder as ONE card, and a mostly-gone library as ONE card first —
`needs.entries`' `files-folder` and `library-gone`, and `match_tree` (*Choose a folder…* on them).

What a wrong answer would cost a learner: a folder of copies moved or deleted made one card per show it held — Mattias
opened a Needs you of 3,000+ cards that looked frozen; a reinstall over the same folder brought back a dead library
whose every file was gone, card by card, with no way to start fresh from there. The guards matter as much: one show's
own folder gone stays that show's card (its lines' own answers), a folder only partly gone keeps its shows' cards, and
an unplugged drive is never "gone" (the offline line holds it, never *Remove*).

Views built from hand-made feed rows (`tests/test_services_needs`' helpers, real Japanese titles); `match_tree` on real
folders under the test's own root.
"""
import os

from app.services import needs
from tests.test_services_needs import MISSING, WORKS, _works, items_of, view_of, work  # noqa: F401 (a fixture)

SHOWS = ["葬送のフリーレン", "勇者のくせになまいきだ", "薬屋のひとりごと", "雪中悍刀行", "ぼっち・ざ・ろっく！",
         "チェンソーマン", "スパイファミリー"]


def _eps(title, n=4):
    return [f"{title} - {k:02d}.ja.srt" for k in range(1, n + 1)]


def _spec(folders, gone):
    """folders: [(work index, folder)]; gone: the work indexes whose every file is missing."""
    out = []
    for i, folder in folders:
        work(10 + i, SHOWS[i])
        out.append((10 + i, folder, _eps(SHOWS[i]), {k: MISSING for k in range(4)} if i in gone else {}))
    return out


def _kinds(entries):
    return [e.kind for e in entries]


def test_a_folder_of_three_shows_all_gone_is_one_card_and_its_shows_have_none():
    spec = _spec([(0, "Library/アニメ/A"), (1, "Library/アニメ/B"), (2, "Library/アニメ/C"),
                  (3, "Library/D"), (4, "Library/E"), (5, "Library/F"), (6, "Library/G")], gone={0, 1, 2})
    out = needs.entries(view_of(spec))
    folders = [e for e in out if e.kind == needs.FILES_FOLDER]
    assert len(folders) == 1 and needs.GONE not in _kinds(out) and needs.LIBRARY_GONE not in _kinds(out)
    card = folders[0]
    assert card.data["folder"] == "Library/アニメ" and card.data["n"] == 12 and len(card.lines) == 12
    assert card.actions == ("choose_folder", "remove") and card.title.startswith("12 files are gone")
    assert set(card.data["shows"]) == set(SHOWS[:3])
    assert sorted(needs.answer_keys(card)) == sorted(needs.item_key(i) for i in card.data["item_ids"])
    assert needs.BULK not in _kinds(out)                     # nothing left for *Remove all* to hold


def test_one_shows_own_folder_gone_stays_that_shows_card():
    spec = _spec([(0, "Library/A"), (3, "Library/D"), (4, "Library/E")], gone={0})
    out = needs.entries(view_of(spec))
    assert _kinds(out) == [needs.GONE]                      # one show: its lines keep their own answers


def test_a_folder_only_partly_gone_keeps_its_shows_cards():
    # two shows gone (8 files) beside four kept (16) in one folder: 8 of 24 is not most of it
    spec = _spec([(0, "Library/X/A"), (1, "Library/X/B"), (3, "Library/X/D"), (4, "Library/X/E"), (5, "Library/X/F"),
                  (6, "Library/X/G")], gone={0, 1})
    out = needs.entries(view_of(spec))
    assert needs.FILES_FOLDER not in _kinds(out) and _kinds(out).count(needs.GONE) == 2


def test_the_library_mostly_gone_is_one_card_first_with_start_fresh_and_no_show_cards():
    spec = _spec([(0, "Library/A"), (1, "Library/B"), (2, "Library/C"), (3, "Library/D"), (4, "Library/E"),
                  (5, "Library/F"), (6, "Library/G")], gone={0, 1, 2, 3, 4})
    out = needs.entries(view_of(spec), settled=True)
    assert out[0].kind == needs.LIBRARY_GONE
    assert needs.GONE not in _kinds(out) and needs.FILES_FOLDER not in _kinds(out) and needs.BULK not in _kinds(out)
    card = out[0]
    assert card.actions == ("start_fresh", "choose_folder") and card.data["n"] == 20 and card.data["files"] == 28
    assert card.data["folder"] == "Library" and "20 of 28" in card.title


def test_a_library_on_a_drive_that_is_offline_is_never_gone():
    spec = _spec([(0, "Library/A"), (1, "Library/B"), (2, "Library/C"), (3, "Library/D"), (4, "Library/E"),
                  (5, "Library/F")], gone={0, 1, 2, 3, 4, 5})
    root = needs.Root(path="E:\\Library", rel="Library", label="Drive E:")
    out = needs.entries(view_of(spec), offline_roots=[root], settled=True)
    assert _kinds(out) == [needs.OFFLINE]                  # IK-8: never *Start fresh*, never *Remove*


def test_a_library_partly_offline_never_reads_as_mostly_gone():
    """A drive linked into the library is unplugged: whatever is left local, the library card waits (its files may be
    the drive's), and the folder cards hold what is gone."""
    spec = _spec([(0, "Library/A"), (1, "Library/B"), (2, "Library/C"), (3, "Library/D"), (4, "Library/E"),
                  (5, "Linked/F"), (6, "Linked/G")], gone={0, 1, 2, 3, 4})
    root = needs.Root(path="E:\\Linked", rel="Linked", label="Drive E:")
    out = needs.entries(view_of(spec), offline_roots=[root], settled=True)
    assert needs.LIBRARY_GONE not in _kinds(out) and needs.FILES_FOLDER in _kinds(out)


def test_goals_files_count_toward_the_library_so_a_moved_current_folder_is_never_the_library_gone():
    """Current's 24 files gone, Goal holding 2,000 healthy ones: never "Most of your library's files are gone" (the
    adversary's #1) — a folder card holds them."""
    spec = _spec([(0, "Library/X/A"), (1, "Library/X/B"), (2, "Library/X/C"), (3, "Library/X/D"),
                  (4, "Library/X/E"), (5, "Library/X/F")], gone={0, 1, 2, 3, 4, 5})
    view = view_of(spec)
    view = view._replace(counts=view.counts._replace(goal_files=2000))
    out = needs.entries(view, settled=True)
    assert needs.LIBRARY_GONE not in _kinds(out) and _kinds(out).count(needs.FILES_FOLDER) == 1


def test_the_library_card_waits_for_every_folders_look_and_never_comes_from_the_cached_first_screen():
    """A copy a look can put back from its original is gone only until the run's looks (item 8a): until then no
    *Start fresh* — the folder cards hold the gone files. The first screen's cache (a part of Current) folds nothing."""
    spec = _spec([(0, "Library/A"), (1, "Library/B"), (2, "Library/C"), (3, "Library/D"), (4, "Library/E"),
                  (5, "Library/F"), (6, "Library/G")], gone={0, 1, 2, 3, 4})
    out = needs.entries(view_of(spec))
    assert needs.LIBRARY_GONE not in _kinds(out) and needs.FILES_FOLDER in _kinds(out)
    cached = view_of(spec)._replace(cached=True)
    assert needs.LIBRARY_GONE not in _kinds(needs.entries(cached, settled=True))
    assert needs.FILES_FOLDER not in _kinds(needs.entries(cached, settled=True))


def test_every_action_of_the_new_cards_is_one_the_window_can_draw_or_hides():
    """The intent keeper's #1: a card whose action the window has no label for broke the page's build. Each action
    of the folder's and the library's cards has the window's label, or waits hidden (WIRED_LATER)."""
    from app.qt import strings
    spec = _spec([(0, "Library/A"), (1, "Library/B"), (2, "Library/C"), (3, "Library/D"), (4, "Library/E"),
                  (5, "Library/F"), (6, "Library/G")], gone={0, 1, 2, 3, 4})
    cards = [needs.entries(view_of(spec), settled=True)[0], needs.entries(view_of(spec))[0]]
    assert {c.kind for c in cards} == {needs.LIBRARY_GONE, needs.FILES_FOLDER}
    for card in cards:
        for name in card.actions + tuple(a for ln in card.lines for a in ln.actions):
            assert name in strings.NEEDS_ACTIONS or name in needs.WIRED_LATER, name


def test_the_cards_keys_are_pruned_once_their_files_are_back(tmp_path, monkeypatch):
    monkeypatch.setattr(needs, "seen_path", lambda language: str(tmp_path / f"needs_seen_{language}.json"))
    gone_spec = _spec([(0, "Library/A"), (1, "Library/B"), (2, "Library/C"), (3, "Library/D"), (4, "Library/E"),
                       (5, "Library/F"), (6, "Library/G")], gone={0, 1, 2, 3, 4})
    card = needs.entries(view_of(gone_spec), settled=True)[0]
    assert card.kind == needs.LIBRARY_GONE
    needs.mark_seen("ja", [card.key])
    assert needs.prune("ja", view_of(gone_spec)) == 0       # still gone: still seen
    back_spec = _spec([(i, f"Library/{c}") for i, c in enumerate("ABCDEFG")], gone=set())
    assert needs.prune("ja", view_of(back_spec)) == 1       # back: its key goes, so gone again it counts again
    assert needs.read_seen("ja") == set() or card.key not in needs.read_seen("ja")


def test_the_librarys_folder_is_the_one_its_gone_files_share_whatever_their_case():
    assert needs._common_folder(["Library/アニメ/A/1.srt", "library/アニメ/B/2.srt"]) == "Library/アニメ"
    assert needs._common_folder(["Library/A/1.srt", "HighPriority/B/2.srt"]) == ""
    assert needs._common_folder(["Library/A/1.srt"]) == "Library/A"


def test_a_few_gone_files_never_fold(monkeypatch):
    """Under FOLDER_MIN gone files nothing can fold: the page builds the shows' cards without walking the library."""
    spec = _spec([(0, "Library/X/A"), (1, "Library/X/B")], gone={0, 1})
    called = []
    monkeypatch.setattr(needs, "_prefixes", lambda rel: called.append(rel) or [])
    out = needs.entries(view_of(spec))
    assert called == [] and _kinds(out).count(needs.GONE) == 2


def _write(path, text="字幕"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def test_choose_a_folder_matches_each_file_by_its_place_then_by_a_name_no_other_file_shares(tmp_path):
    picked = str(tmp_path / "moved")
    a1 = _write(os.path.join(picked, "A", "A - 01.ja.srt"))
    b2 = _write(os.path.join(picked, "elsewhere", "B - 02.ja.srt"))       # not at its place: found by its name
    _write(os.path.join(picked, "x", "C - 03.ja.srt"))
    _write(os.path.join(picked, "y", "C - 03.ja.srt"))                    # two share the name: never guessed
    lines = [needs.NeedLine(key=f"item:{i}", text="", item_id=i, label=n, number=None,
                            rel_path=f"Library/アニメ/{n.split(' ')[0]}/{n}", actions=())
             for i, n in enumerate(["A - 01.ja.srt", "B - 02.ja.srt", "C - 03.ja.srt"], start=1)]
    found = needs.match_tree(picked, "Library/アニメ", lines)
    assert [(ln.item_id, path) for ln, path in found] == [(1, a1), (2, b2)]
    assert [ln.item_id for ln, _p in needs.match_tree(picked, "library/アニメ", lines)] == [1, 2]   # a case apart
    sharp = [ln._replace(rel_path="Library/Straße/" + ln.rel_path.split("/", 2)[2]) for ln in lines]
    assert [ln.item_id for ln, _p in needs.match_tree(picked, "Library/STRASSE", sharp)] == [1, 2]  # ß is ss


def test_choose_a_folder_never_gives_one_file_to_two_gone_lines(tmp_path):
    """The adversary's #2: two gone lines named alike (two shows' `01.srt`), the picked folder holding one `01.srt`
    at A's place — A takes it by its place, and B never takes A's file by the name."""
    picked = str(tmp_path / "moved")
    a = _write(os.path.join(picked, "A", "01.srt"))
    lines = [needs.NeedLine(key=f"item:{i}", text="", item_id=i, label="01", number=1,
                            rel_path=f"Library/{show}/01.srt", actions=()) for i, show in ((1, "A"), (2, "B"))]
    assert [(ln.item_id, p) for ln, p in needs.match_tree(picked, "Library", lines)] == [(1, a)]
    elsewhere = str(tmp_path / "flat")
    _write(os.path.join(elsewhere, "x", "01.srt"))
    assert needs.match_tree(elsewhere, "Library", lines) == []      # two lines share the name: never guessed
    assert needs.match_tree(str(tmp_path / "not there"), "Library", lines) == []

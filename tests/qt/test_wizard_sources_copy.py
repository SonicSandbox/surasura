"""K5 (alpha 4, Sonic's 2026-10-25 answers): setup's first look shows its copy's progress and warns at 15,000 items —
`sources.scan(copying=)`, `setup_wizard.read_folders(copying=)`, the page's *Copying into your library…* and its big
library line; and a part this look just wrote is never hashed again (check b).

What a wrong answer would cost a learner: a 25,000-book library listed in a fraction of a second, then the page said
"Found 0 episodes…" for hours while every book was copied in — it looked frozen; and nothing told him a library past
the size Surasura is built for (20,000) was coming in. The measure: `tracks/logic/work/alpha4/k5/` (1,000 books, 60,676
parts, 20 minutes; a third of it re-reading parts the same look had just written).

A real empty library under the test's root, real Japanese texts in a source folder (`test_wizard_sources`' helpers).
"""
import os

from app import library_store as ls
from app import sources
from app.qt import wizard_strings as S
from app.services import setup_wizard
from tests.qt.test_wizard import go_to, make  # noqa: F401 (a fixture)
from tests.qt.test_wizard_sources import SHOWS, SourcesApi, _folder, _fresh_look_state, empty_library  # noqa: F401


def test_the_copy_counts_every_new_file_up_to_the_last(empty_library):
    told = []
    got = setup_wizard.read_folders("ja", [_folder("anime", SHOWS)], copying=lambda d, t: told.append((d, t)))
    total = sum(SHOWS.values())
    assert got["added"] == total
    assert told and told[-1] == (total, total)                        # the last word: every file dealt with
    assert all(t == total for _d, t in told) and [d for d, _t in told] == sorted(d for d, _t in told)


def test_a_part_the_look_just_wrote_is_never_read_again_to_compare_its_bytes(monkeypatch):
    """Check (b) asks whether a new part's bytes are an item's: two books whose parts are the same sizes (one character
    swapped for another of its length) — the second book's check meets the first's parts, whose bytes this look
    wrote and knows: none of our copies is read back (the measure: a third of a 1,000-book look did that)."""
    from tests.test_sources_scan import _chapters, _empty, _epub
    store, data_dir = _empty("ja")
    src = _drive_folder()
    chapters = _chapters()
    _epub(os.path.join(src, "Books", "一の巻.epub"), chapters)
    _epub(os.path.join(src, "Books", "二の巻.epub"), [c.replace("。", "、", 1) for c in chapters])
    read = []
    real = ls.sha256_of
    monkeypatch.setattr(ls, "sha256_of", lambda path: (read.append(path), real(path))[1])
    with store:
        root = store.add_source(src)
        got = sources.scan(store, "ja", root, first=True)
    assert got["added"] >= 4                                          # both books' parts in
    assert not [p for p in read if os.sep + ls.CONTENT_FOLDER + os.sep in p]   # no copy of ours read back


def _drive_folder():
    from tests.test_sources_scan import _drive
    return _drive("books")


def test_the_page_says_the_copy_and_warns_once_the_library_is_big(make, empty_library):
    wiz, _shell, _api, _settings, _m = make(api=SourcesApi())
    go_to(wiz, "shows")
    page = wiz.page
    page.show_copying(1204, 25000)
    assert page.reading_line.text() == S.COPYING.format(done=1204, total=25000)
    assert "1,204" in page.reading_line.text() and not page.btn_stop.isHidden()
    page.show_reading(setup_wizard.BIG_LIBRARY - 1, 300)
    assert "big library" not in page.reading_line.text()
    page.show_reading(setup_wizard.BIG_LIBRARY, 300)
    assert "big library" in page.reading_line.text() and "15,000" in page.reading_line.text()
    page.show_waiting(True)
    assert page.reading_line.text() == S.READ_WAITING
    page.show_waiting(False)                                          # the wait over: the count as it last stood
    assert "big library" in page.reading_line.text()

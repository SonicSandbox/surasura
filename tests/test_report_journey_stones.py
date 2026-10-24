"""The journey's stones, the template half (`templates/web_app.html`; Sonic 2026-10-23 "Yes include", JS-2: the
browser's ✓ *Mark complete* stays beside the stone, drawn clearly different).

The report's data names each watched episode (`tests/test_journey_stones.py`, the data half): `"watched": true` on a
counted file's entry (*Keep studying watched episodes* on), or an entry of its own in its place, `"aside": true`, no
counts (the option off). The sidebar draws:
  - a stone before the name of every watched file's tab — a small cut stone, sapphire, muted (the window's watched
    stone drawn flat): never a check and never green, so it never reads as the ✓ (green text, after the name);
  - on an aside file, *watched* where its count would be, and on a click a short panel in the window's own sentence,
    "Watched: its words leave your list." (never "No new words in this file", never a 0% bar); never opened by itself
    (the report opens on the first file still to study, and a ✓ advances past it);
  - nothing at all where no file is watched, or in an old report whose data has no `watched` key.

No test may open a browser (the harness refuses one), so the drawing is read from the template the report embeds; the
report itself is the generator's, from a real library store with real stones, Japanese and Chinese.
"""
import json
import os
import re

import pytest

from app import theme
from app.qt import strings

from tests.test_journey_stones import _now_names, _payload, _render, _settings
from tests.test_library_store_support import LANGUAGES, migrated

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "web_app.html")
GREEN = ("#4caf50", "76, 175, 80", "green")


def _template():
    with open(TEMPLATE, encoding="utf-8") as f:
        return f.read()


def _function(source, name):
    """The body of the template's `function name(...) { ... }`, by its braces."""
    start = source.index(f"function {name}(")
    i, depth = source.index("{", start), 0
    for j in range(i, len(source)):
        depth += {"{": 1, "}": -1}.get(source[j], 0)
        if depth == 0:
            return source[start:j + 1]
    raise AssertionError(name)


def _css(source, selector):
    return re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source).group(1)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_report_with_an_aside_stone_carries_the_template_that_draws_it(language, tmp_path):
    # why: the report a learner opens is the template plus the data: the stone shows only if both say so
    _settings(language)
    store = migrated(language)
    names = _now_names(store)
    store.set_watched([store.ids("now")[1]])
    html = _render(tmp_path, language, [n for n in names if n != names[1]])
    store.close()
    aside = [e for e in _payload(html)["progressive"] if e.get("aside")]
    assert [e["filename"] for e in aside] == [names[1]] and aside[0]["watched"] is True
    tab = _function(html, "createSidebarTab")
    branch = tab[tab.index("if (fileData.aside)"):tab.index("return tab;")]
    assert "journeyStone(fileData)" in branch and 'data-content="watched"' in branch, "the stone, *watched* in place"
    assert "fileData.words.length" not in branch, "no count on a file whose words aren't counted"
    assert "renderWatchedFile(fileData)" in branch
    panel = _function(html, "renderWatchedFile")
    assert "globalWatchedLeaves" in panel and "No new words" not in panel
    assert "updateMarkCompleteButton()" in panel, "the ✓ still marks it in the browser"
    # IK Decision 2 (⭐, PROVISIONAL): one sentence for one rule, the window's own — injected by the generator from the
    # one place it is written (`view_rows.STRINGS`, which the window's tooltip reads too)
    said = re.search(r"let globalWatchedLeaves = (\"[^\"]*\");", html)
    assert said and json.loads(said.group(1)) == strings.ROWS_STONE_LEAVES.strip() == \
        "Watched: its words leave your list."


def test_every_watched_tab_draws_the_stone_and_none_without_the_key():
    # why: no watched key is not watched — a library with no stone, and every report written before them, draw as they
    # did: the stone is an empty string unless the entry says `watched: true`
    source = _template()
    stone = _function(source, "journeyStone")
    assert "fileData.watched !== true" in stone and 'return ""' in stone
    tab = _function(source, "createSidebarTab")
    assert tab.count("${journeyStone(fileData)}") == 3, "the aside tab, a counted tab and a Target Met tab"
    counted = tab[tab.index("const inAnkiCount"):tab.index("} else {")]
    assert counted.index("${journeyStone(fileData)}") < counted.index("data-content=\"${safeFilename}\""), \
        "before the name (the ✓ comes after it)"


def test_the_stone_and_the_browsers_check_are_drawn_clearly_different():
    # why: JS-2 — both stay, and a learner must never read one for the other: the stone is a cut stone in sapphire,
    # the ✓ is green text; one is the library's mark, the other the browser's
    source = _template()
    svg = re.search(r"const JOURNEY_STONE_SVG = '([^']*)'", source).group(1)
    assert "<polygon" in svg and "✓" not in svg and "check" not in svg.lower()
    assert not any(g in svg.lower() for g in GREEN), "never green"
    assert "#1d4fae" in svg, "the window's sapphire (theme.GEM)"
    stone_css = _css(source, ".file-tab .journey-stone")
    assert not any(g in stone_css for g in GREEN) and "opacity" in stone_css, "muted, never green"
    check = _function(source, "applyCompletedStyle")
    assert "'Complete ✓'" in check and "completed-check" in check, "the ✓ is kept as it was"
    assert "#4caf50" in _css(source, ".file-tab .completed-check"), "...green text"
    title = re.search(r'class="journey-stone" title="([^"]*)"', _function(source, "journeyStone")).group(1)
    assert "Watched" in title and "complete" not in title.lower()


def test_a_set_aside_file_never_gets_the_target_days_box_from_the_check():
    # why: marking a set-aside file ✓ swaps the Target Days box in place; it has none (its words aren't counted), so
    # the swap leaves its panel alone instead of adding "0 words Completed"
    source = _template()
    swap = _function(source, "updateTargetDaysForCurrent")
    assert "querySelector('.watched-panel')" in swap


def test_the_report_opens_on_the_first_episode_still_to_study_and_the_check_skips_set_aside_ones():
    # why (JSW-A1 = IK Decision 1, ⭐ PROVISIONAL): a learner watches in order, so with Keep studying off the first
    # entries are usually set aside — opening on one shows "Watched" instead of the words of the episode he is on, and a
    # ✓ that advanced onto one would stop there. One rule picks the tab for both: words that still count, not ✓.
    # (The pick run in a browser is the recorded Edge check, `work/journey-stones/shots/a1_open_check.py`.)
    source = _template()
    tab = _function(source, "createSidebarTab")
    branch = tab[tab.index("if (fileData.aside)"):tab.index("return tab;")]
    assert "tab.dataset.aside" in branch, "the set-aside tab says so"
    rule = _function(source, "stillToStudy")
    assert "dataset.aside" in rule and "completedFiles.has" in rule and "#completed-section" in rule
    first = source[source.index("// Initial Load"):]
    first = first[:first.index("}, 50);")]
    assert "tabs.find(stillToStudy)" in first, "the first open skips set-aside and ✓ tabs"
    assert first.index("tabs.find(stillToStudy)") < first.index("tabs[0]"), "...and falls back to the first tab"
    advance = _function(source, "goToNextIncompleteFile")
    assert "stillToStudy(tabs[i])" in advance and "completedFiles.has" not in advance, "the ✓'s advance: the same rule"


def test_the_stone_sits_on_the_names_first_line_with_the_windows_light_edge():
    # why (IK Decision 3 ⭐ and IK 5): in the narrow sidebar a long name wrapped as a block below the stone, leaving the
    # stone alone on a line; and its dark base read at ~2:1 on the dark sidebar — the window's own light edge carries it
    source = _template()
    after = _css(source, ".file-tab .journey-stone ~ .hidden-content")
    assert "display: inline" in after, "the name flows on the stone's line"
    svg = re.search(r"const JOURNEY_STONE_SVG = '([^']*)'", source).group(1)
    assert theme.GEM["sapphire"][2] in svg and 'fill="none"' in svg, "the window's light edge (theme.GEM sapphire)"


# --- opened on one episode (Sonic 2026-10-24, the stones' choice 1: "if you use the option on an episode to 'see in
# journey' it should open up that one") ------------------------------------------------------------------------------ #
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_window_opens_the_report_on_an_episode_through_a_small_page_that_keeps_its_name(language, tmp_path,
                                                                                         monkeypatch):
    # why: Windows drops a file URL's #fragment on its way to the default browser, so the name rides in a small page
    # beside the report that replaces itself with the report at #file=<name>; every other way in opens the report as
    # before, with no page written
    from urllib.parse import unquote
    from app import static_html_generator as gen
    _settings(language)
    store = migrated(language)
    names = _now_names(store)
    store.set_watched([store.ids("now")[1]])                 # a set-aside episode: the window can still open on it
    _render(tmp_path, language, [n for n in names if n != names[1]])
    store.close()
    results = tmp_path / "results"
    opened, as_app = [], []
    monkeypatch.setattr(gen, "get_user_file", lambda name: str(results))
    monkeypatch.setattr(gen.webbrowser, "open", opened.append)
    monkeypatch.setattr(gen, "open_as_app", as_app.append)
    assert gen.open_report() is True
    assert opened == [f"file://{results / gen.REPORT_NAME}"] and not (results / gen.OPEN_ON_NAME).exists()
    assert gen.open_report(file=names[1]) is True
    page = results / gen.OPEN_ON_NAME
    assert opened[-1] == f"file://{page}"
    target = json.loads(re.search(r"location\.replace\((\"[^\"]*\")\)", page.read_text(encoding="utf-8")).group(1))
    assert target.startswith(gen.REPORT_NAME + "#file=") and unquote(target.split("#file=", 1)[1]) == names[1]
    assert names[1].encode("ascii", "ignore") != names[1].encode("utf-8"), "a real Japanese / Chinese name, quoted"
    assert gen.open_report(app_mode=True, file=names[0]) is True and as_app == [str(page)]
    assert unquote(page.read_text(encoding="utf-8").split("#file=", 1)[1].split('"', 1)[0]) == names[0]
    real_open = open

    def held(path, *a, **kw):                               # the page can't be written (a lock, results read-only)
        if str(path).endswith(gen.OPEN_ON_NAME):
            raise PermissionError(13, "held", str(path))
        return real_open(path, *a, **kw)
    monkeypatch.setattr("builtins.open", held)
    assert gen.open_report(file=names[1]) is True and opened[-1] == f"file://{results / gen.REPORT_NAME}", \
        "the report itself opens (JO-A5): never a failed open"
    monkeypatch.setattr("builtins.open", real_open)
    (results / gen.REPORT_NAME).unlink()
    assert gen.open_report(file=names[0]) is False, "no report: nothing opened"


def test_the_report_opens_on_the_asked_file_whatever_it_is_and_else_on_the_first_still_to_study():
    # why: the asked tab is clicked as it is — a set-aside one shows its Watched panel (its own onclick), a Target-met
    # one its page (JO-A1: every kind carries its name), one past the paged sidebar's first 50 rendered first (JO-A2),
    # brought into view and out of a collapsed Completed section (JO-A3); a name the report doesn't hold falls back to
    # the one rule. Run in a real browser (ja + zh, each case, and failing on the template before): the recorded Edge
    # check `tracks/window/work/journey-open/open_on_check.py` (no browser in pytest).
    source = _template()
    asked = _function(source, "fileFromHash")
    assert "'#file='" in asked and "decodeURIComponent" in asked and "return '';" in asked
    tab = _function(source, "createSidebarTab")
    assert tab.index("tab.dataset.file = item.data.filename") < tab.index("if (item.type === 'prog')"), \
        "every kind of tab is named, before the kinds part"
    assert "dataset.file " not in _function(source, "stillToStudy"), "the opening rule still reads counted tabs only"
    assert "return (i) =>" in _function(source, "setupInfiniteScroll"), "the paged sidebar renders up to an item"
    first = source[source.index("// Initial Load"):]
    first = first[:first.index("}, 50);")]
    assert first.index("loadThrough(at)") < first.index("querySelectorAll('.file-tab')"), "rendered before it looks"
    assert "t.dataset.file === asked" in first and "scrollIntoView" in first and "applyCompletedSectionState()" in first
    assert "localStorage" not in first, "a collapsed section opened for it is not saved"
    assert first.index("fileFromHash()") < first.index("tabs.find(stillToStudy)") < first.index("tabs[0]")


@pytest.mark.parametrize("language", LANGUAGES)
def test_with_keep_studying_on_the_watched_sentence_shows_nowhere(language, tmp_path):
    # why (Sonic 2026-10-24, choice 2: "if we have a setting that makes them continue to study then it wouldn't show
    # this correct?"): with the option on, a watched episode's words stay on the list, so "Watched: its words leave
    # your list." must say so nowhere — the window's stone tip (leaves False) and the report (the normal tab with its
    # count, never the set-aside panel) — while with it off both say it
    from types import SimpleNamespace
    from app.qt import rows
    from app.services import view_rows
    sentence = strings.ROWS_STONE_LEAVES.strip()
    ep = SimpleNamespace(label="Ep 2", watched=True, waiting=False)
    on = rows.stone_tip(ep, "", view_rows.mark_moves_list("now", ep, True))
    off = rows.stone_tip(ep, "", view_rows.mark_moves_list("now", ep, False))
    assert sentence not in on and sentence in off
    _settings(language)
    store = migrated(language)
    store.set_library_options(keep_watched=True)
    names = _now_names(store)
    store.set_watched([store.ids("now")[1]])
    data = _payload(_render(tmp_path, language, names))
    store.close()
    entry = [e for e in data["progressive"] if e["filename"] == names[1]]
    assert len(entry) == 1 and entry[0]["watched"] is True and entry[0]["words"], "its normal tab, with its count"
    assert not any(e.get("aside") for e in data["progressive"] + data["completed_files"]), \
        "no set-aside entry: renderWatchedFile (the sentence's one place in the report) is never reached"
    panel_calls = [m.start() for m in re.finditer(r"renderWatchedFile\(", _template())]
    branch = _function(_template(), "createSidebarTab")
    assert len(panel_calls) == 2 and "renderWatchedFile(fileData)" in branch[branch.index("if (fileData.aside)"):], \
        "the panel is drawn only from the aside branch (and defined once)"

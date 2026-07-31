"""The 文 reading badge and its "Show" filter option, in BOTH report templates.

There is no JS engine in this suite, so these templates are string contracts: the tests assert the
literal identifiers and classes survive. That is the established convention here (see
test_sort_filter_feature.py / test_completed_files_feature.py), and it is what stops a rename from
silently removing a feature from the shipped report.

zen_app.html duplicates the marker rendering rather than importing it, so every assertion is made
against both files on purpose — a badge added to only one template is invisible to Zen users.
"""

import os

import pytest


@pytest.fixture
def web_html(project_root):
    with open(os.path.join(project_root, "templates", "web_app.html"), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def zen_html(project_root):
    with open(os.path.join(project_root, "templates", "zen_app.html"), encoding="utf-8") as f:
        return f.read()


# --- the badge ------------------------------------------------------------------------------- #

def test_web_defines_the_reading_marker(web_html):
    assert ".marker-reading::before" in web_html
    assert 'content: "文"' in web_html
    assert "#d0a5ff" in web_html


def test_web_renders_the_badge_from_the_precomputed_column(web_html):
    """The verdict is computed by the analyzer; the browser only reads the column."""
    assert "data.Modality === 'reading'" in web_html
    assert "marker-reading" in web_html
    assert "is-reading" in web_html


def test_badge_is_additive_not_another_ternary_branch(web_html):
    """✦ and ⚖ are mutually exclusive; a reading word can also be high-leverage.

    The badge must therefore render as its own span appended after that ternary — if it became a
    third branch, every reading word would silently lose its ✦.
    """
    assert "${isReading ?" in web_html
    marker_line = next(l for l in web_html.splitlines() if "marker-lopsided\" title=" in l)
    assert "marker-reading" in marker_line, "badge must sit alongside the ✦/⚖ ternary, not inside it"
    assert marker_line.index("marker-lopsided") < marker_line.index("marker-reading")


def test_light_theme_gets_a_readable_colour(web_html):
    """Pale purple vanishes on a near-white background, so the light theme darkens it."""
    assert ".theme-modern-light .marker-reading::before" in web_html
    assert "#7c4dff" in web_html


def test_zen_renders_the_badge_too(zen_html):
    """Zen duplicates the markers; a badge added only to web_app is invisible here."""
    assert "--prio-reading" in zen_html
    assert ".prio-reading" in zen_html
    assert "data.Modality === 'reading'" in zen_html
    assert "文</span>" in zen_html


def test_zen_appends_rather_than_replaces_the_priority_icon(zen_html):
    """Same additive rule as the web template — `+=`, not a reassignment."""
    assert "prioIcon +=" in zen_html


# --- the Show filter ------------------------------------------------------------------------- #

def test_reading_is_a_filter_option(web_html):
    assert 'data-filter="reading"' in web_html
    assert "body.filter-reading .card:not(.is-reading)" in web_html
    assert "'filter-reading'" in web_html


def test_non_reading_is_a_filter_option(web_html):
    """The inverse view — 'show me only what I'll actually hear' — mirroring No ✦."""
    assert 'data-filter="non-reading"' in web_html
    assert "body.filter-non-reading .card.is-reading" in web_html
    assert "'filter-non-reading'" in web_html


def test_every_filter_state_has_a_body_class(web_html):
    """The lookup table and the CSS must agree, or a state silently filters nothing."""
    for state in ("priority", "non-priority", "reading", "non-reading"):
        assert f"'{state}': 'filter-{state}'" in web_html
        assert f"body.filter-{state} " in web_html


def test_hotkey_cycle_includes_both_reading_states(web_html):
    """`s` cycles the filter; a state missing from the cycle is menu-only."""
    assert "['all', 'priority', 'non-priority', 'reading', 'non-reading']" in web_html


def test_filter_button_titles_name_every_state(web_html):
    """The ⇅ button's tooltip must describe the active filter, including the new ones."""
    assert "reading (文) words" in web_html
    assert "non-reading words" in web_html


# --- end to end ------------------------------------------------------------------------------- #

def test_modality_column_survives_into_the_generated_report(tmp_path, monkeypatch, project_root):
    """A column the analyzer writes is useless if the generator drops it before the browser.

    Renders a report from a minimal CSV carrying real vocabulary and asserts the verdict arrives.
    """
    import pandas as pd
    from app import static_html_generator

    results = tmp_path / "results"
    results.mkdir()

    rows = [
        # 覗き込む is a genuine reading word; 会社 is everyday speech.
        {"Word": "覗き込む", "Reading": "ノゾキコム", "Tier": "Outside", "Score": 40,
         "Occurrences": 12, "Count (High)": 12, "Count (Low)": 0, "Count (Goal)": 0,
         "Modality": "reading", "Sources": "book.txt", "Context 1": "窓を覗き込む。"},
        {"Word": "会社", "Reading": "カイシャ", "Tier": "Outside", "Score": 30,
         "Occurrences": 9, "Count (High)": 9, "Count (Low)": 0, "Count (Goal)": 0,
         "Modality": "", "Sources": "book.txt", "Context 1": "会社に行く。"},
    ]
    pd.DataFrame(rows).to_csv(results / "priority_learning_list.csv", index=False,
                              encoding="utf-8-sig")
    prog = [dict(r, Sequence=1, **{"Source File": "book.txt", "Occurrences (Global)": r["Occurrences"],
                                   "Occurrences (File)": r["Occurrences"]}) for r in rows]
    pd.DataFrame(prog).to_csv(results / "progressive_learning_list.csv", index=False,
                              encoding="utf-8-sig")

    # The generator resolves its paths ONCE at import, so every one of them has to be redirected
    # individually — patching RESULTS_DIR alone still writes the report into the real results/.
    out = results / "reading_list_static.html"
    monkeypatch.setattr(static_html_generator, "RESULTS_DIR", str(results))
    monkeypatch.setattr(static_html_generator, "PRIORITY_CSV",
                        str(results / "priority_learning_list.csv"))
    monkeypatch.setattr(static_html_generator, "PROGRESSIVE_CSV",
                        str(results / "progressive_learning_list.csv"))
    monkeypatch.setattr(static_html_generator, "OUTPUT_FILE", str(out))

    static_html_generator.generate_static_html(theme="Dark Flow")

    html = out.read_text(encoding="utf-8")
    assert "Modality" in html, "the analyzer's verdict never reached the report payload"
    assert "reading" in html

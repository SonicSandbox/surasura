"""The 文 reading badge and its "Show" filter option, in the YouTube preview's page (templates/web_app.html), and the
analyzer's verdict reaching the journey page (its word's marks).

There is no JS engine in this suite, so these templates are string contracts: the tests assert the
literal identifiers and classes survive. That is the established convention here (see
test_sort_filter_feature.py / test_completed_files_feature.py), and it is what stops a rename from
silently removing a feature from the shipped report.

Zen's page (zen_app.html), which duplicated the marker, retired with the old journey page (J-RETIRE, 2026-11-23).
"""

import os

import pytest


@pytest.fixture
def web_html(project_root):
    with open(os.path.join(project_root, "templates", "web_app.html"), encoding="utf-8") as f:
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

def test_modality_column_survives_into_the_journey_page():
    """The analyzer's verdict reaches the journey page: a reading word's record carries the reading mark (bit 4 of
    its marks, `journey_render.marks_of`), an everyday word's does not (the old page's payload before J-RETIRE)."""
    import gzip
    import json
    from app import journey_render as jr
    rows = [  # 覗き込む is a genuine reading word; 会社 is everyday speech.
        {"Sequence": 1, "Source File": "book.txt", "Word": "覗き込む", "Reading": "ノゾキコム", "Modality": "reading",
         "Occurrences (Global)": 12.0, "Occurrences (File)": 12.0, "Count (High)": 12.0, "Count (Low)": 0.0,
         "Context 1": "窓を覗き込む。", "Src 1": "HighPriority/book.txt"},
        {"Sequence": 1, "Source File": "book.txt", "Word": "会社", "Reading": "カイシャ", "Modality": "",
         "Occurrences (Global)": 9.0, "Occurrences (File)": 9.0, "Count (High)": 9.0, "Count (Low)": 0.0,
         "Context 1": "会社に行く。", "Src 1": "HighPriority/book.txt"},
    ]
    out = jr.build("ja", rows, [{"File": "book.txt", "Total Words": 20, "Known Count": 10, "Coverage (%)": 50.0}],
                   stamp=1)
    marks = {w[0]: w[6] for blob in out.chunks for w in json.loads(gzip.decompress(blob).decode("utf-8"))["w"]}
    assert marks["覗き込む"] & 4 and not marks["会社"] & 4

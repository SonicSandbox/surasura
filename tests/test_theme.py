"""The 3.0 window's theme tokens (`app/theme.py`, W1.3; the window's spec 04 §4.2, 05 §5.5, A4).

What a wrong answer would cost: a colour that drifts from the mock Sonic signed (G1.6, "VERY close"); a mix the Qt
shell paints differently from the browser's `color-mix(in oklab)`; body text under the contrast floor in one theme; a
status colour (learned / heads-up / problem) that changes with the theme and stops meaning one thing.
"""
import re

import pytest

from app import theme

# The look test's theme.css (tracks/window/work/w02/mock-g16/theme.css, G1.6 round 3), the three shipped themes, copied
# verbatim: the module's token sets must equal it.
THEME_CSS = """
.theme-hb {
  --bg:          #111419;
  --surface:     #171b22;
  --raised:      #1f242d;
  --line:        #2a303a;
  --line-hi:     #3a4250;
  --ink:         #e9ecf1;
  --ink-dim:     #939cab;
  --ink-faint:   #626b79;
  --accent:      #62b6f2;
  --accent-2:    #b894ff;
  --accent-deep: #2a6fa8;
  --accent-wash: #1a2a3a;
}
.theme-sky {
  --bg:          #1a2533;
  --surface:     #21303f;
  --raised:      #2a3b4e;
  --line:        #34485e;
  --line-hi:     #456079;
  --ink:         #eef4fb;
  --ink-dim:     #a6b8cc;
  --ink-faint:   #7f93aa;
  --accent:      #8fd0fa;
  --accent-2:    #c7abff;
  --accent-deep: #3a86c4;
  --accent-wash: #24405a;
}
.theme-sapphire {
  --bg:          #0a1628;
  --surface:     #0f1f36;
  --raised:      #162a46;
  --line:        #1f3a5c;
  --line-hi:     #2c5079;
  --ink:         #eaf2fc;
  --ink-dim:     #9db5d3;
  --ink-faint:   #7894b6;
  --accent:      #4fb0f0;
  --accent-2:    #bc9cff;
  --accent-deep: #1b67b0;
  --accent-wash: #13355a;
}
"""


def _css_themes():
    out = {}
    for name, body in re.findall(r"\.theme-(\w+) \{(.*?)\}", THEME_CSS, re.S):
        out[name] = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-f]+);", body))
    return out


def test_the_three_shipped_themes_equal_the_look_tests_theme_css():
    """Blue, Lighter blue and Sapphire, token for token; Amethyst is not shipped."""
    css = _css_themes()
    assert set(theme.THEMES) == set(css) == {"hb", "sky", "sapphire"}
    for name, tokens in css.items():
        got = {k: theme.colours(name)[k] for k in tokens}
        assert got == tokens, name
    assert theme.DEFAULT_THEME == "sapphire"                 # Sonic, G2.3 (2026-10-08): Sapphire first


# research/09-visual-language.md's opaque table (Blue, computed in OKLab from the mock's CSS): the browser's answers.
RESEARCH_09_BLUE = {
    "header-top-opaque": "#192029", "tab-bar": "#14181e", "settings-nav": "#14171d", "settings-more": "#14171d",
    "side-column": "#15191f", "settings-even": "#1c242e", "settings-even-more": "#161c23",
    "arrivals-fill": "#1f2834", "arrivals-pressed": "#27394a", "arrivals-border": "#456987",
    "watched-chip-fill": "#21303e", "watched-chip-border": "#456987", "switch-on": "#2d475c",
    "top20-line": "#41607b", "finished-bucket-lit": "#222d30", "mine-inset-lit": "#1f2a2a",
    "source-hato-opaque": "#3b3234", "source-youtube-opaque": "#3e1f28", "source-anilist-opaque": "#143245",
    "status-in-opaque": "#233131", "status-mining-opaque": "#202e3b",
}


def _channels(hex_colour):
    return [int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)]


@pytest.mark.parametrize("name,expected", sorted(RESEARCH_09_BLUE.items()))
def test_every_blue_mix_equals_the_browsers_within_one_step(name, expected):
    """Qt can't mix colours: each `color-mix(in oklab)` is worked out here. Blue's must land on the browser's values
    (research/09), at most one step off per channel (rounding)."""
    got = theme.colours("hb")[name]
    assert len(got) == len(expected), (name, got, expected)       # opaque stays opaque: no alpha slipped in
    assert all(abs(a - b) <= 1 for a, b in zip(_channels(got), _channels(expected))), (name, got, expected)


def test_every_mix_the_mock_computes_is_worked_out_for_every_theme():
    """All 40 `color-mix` uses in the look test's mock.html (44 named mixes: a line can hold two — :777's second, the
    *Studying its cards first* ring, found at W2.2), each per theme, and each theme's differs from Blue's wherever a
    themed token goes in."""
    assert len(theme.MIXES) == 44
    for t in theme.THEMES:
        for name in theme.MIXES:
            assert re.fullmatch(r"#[0-9a-f]{6}([0-9a-f]{2})?", theme.colours(t)[name]), (t, name)
    assert theme.colours("sky")["settings-even"] != theme.colours("hb")["settings-even"]
    assert theme.colours("sapphire")["tab-bar"] != theme.colours("hb")["tab-bar"]


def test_a_mix_with_transparent_keeps_the_colour_at_its_share_as_alpha():
    """`color-mix(in oklab, X p%, transparent)` is X at p % alpha (premultiplied): the browser's rule."""
    assert theme.mix("#7fcf9f", 12, "transparent") == "#7fcf9f1f"
    assert theme.mix("#62b6f2", 70, "transparent") == "#62b6f2b3"


def test_two_shares_under_100_scale_the_alpha():
    """surface 70 % + accent 5 %: 75 % in all, so 75 % alpha (the header's top), as CSS Color 5 says."""
    assert theme.colours("hb")["header-top"].endswith("bf")


@pytest.mark.parametrize("t", theme.THEMES)
def test_body_text_passes_the_contrast_floor_in_every_theme(t):
    """ink and ink-dim at least 4.5:1 on surface and on raised (05 §5.5); ink-faint is decoration only."""
    c = theme.colours(t)
    for ink in ("ink", "ink-dim"):
        for ground in ("surface", "raised"):
            assert theme.contrast(c[ink], c[ground]) >= 4.5, (t, ink, ground)


def test_the_contrast_figures_are_a4s():
    """The figures A4 recorded from the look test (WCAG on surface), so the arithmetic is the one they used."""
    expected = {"hb": (14.6, 6.2, 3.2, 7.8), "sky": (12.2, 6.6, 4.3, 8.1), "sapphire": (14.7, 7.9, 5.3, 6.9)}
    for t, figures in expected.items():
        c = theme.colours(t)
        got = tuple(round(theme.contrast(c[k], c["surface"]), 1) for k in ("ink", "ink-dim", "ink-faint", "accent"))
        assert got == figures, t


def test_status_colours_and_source_chips_never_change_with_the_theme():
    """learned / heads-up / problem mean one thing everywhere: never themed, and no theme's accent is one of them."""
    for t in theme.THEMES:
        c = theme.colours(t)
        assert {k: c[k] for k in theme.STATUS} == dict(theme.STATUS)
        assert c["source-hato"] == theme.colours("hb")["source-hato"]
        assert c["accent"] not in theme.STATUS.values()
    assert theme.STATUS["ok"] == "#7fcf9f" and theme.STATUS["warn"] == "#e7bf72" and theme.STATUS["bad"] == "#c02040"


def test_the_text_size_scales_every_size_but_the_fixed_ones():
    """S 1 · M 1.15 (the default) · L 1.3: every type size and every size but the fixed ones (the hero cover, the
    switch)."""
    assert theme.TEXT_SIZES == {"S": 1.0, "M": 1.15, "L": 1.3} and theme.DEFAULT_TEXT_SIZE == "M"
    assert theme.font("row-title", "S") == (13.5, 600)
    assert theme.font("row-title", "L") == (17.55, 600)
    assert theme.font("hero-title") == (24.15, 700)          # 21 × 1.15, the mock's 650 drawn as 700
    assert theme.size("row", "L") == 72.8 and theme.size("row", "S") == 56
    assert theme.size("hero-cover-w", "L") == 88 and theme.size("switch-w", "L") == 36


def test_the_motion_tokens_are_the_mocks():
    """The easing and the two speeds, and every named duration the window's spec lists (05 §5.5)."""
    assert theme.EASE == (0.2, 0.7, 0.3, 1.0) and theme.FAST == 120 and theme.SLOW == 260
    m = theme.MOTION
    assert (m["gap-slide"], m["ghost-glide"], m["tray-fade"], m["side-panel"], m["toast-rise"]) == (190, 160, 140,
                                                                                                    260, 260)
    assert 140 <= m["overlay-pop"] <= 160 and m["toast-shown"] == 6500 and m["toast-shown-anki"] == 12000
    assert m["row-flash"] == 1600


def test_title_bar_and_palette_are_plain_hex_per_theme():
    """The Qt shell makes the title bar and the QPalette from plain hex: nothing here is a Qt object."""
    for t in theme.THEMES:
        for value in list(theme.TITLE_BAR[t].values()) + list(theme.palette(t).values()):
            assert re.fullmatch(r"#[0-9a-f]{6}", value), (t, value)
    assert theme.TITLE_BAR["sapphire"] == {"caption": "#0f1f36", "border": "#1f3a5c", "text": "#eaf2fc"}
    assert theme.palette("hb")["Window"] == "#111419"


def test_an_unknown_theme_falls_back_to_the_default_sapphire():
    """A hand-edited or retired theme name (Amethyst) paints the default, Sapphire since G2.3 — never fails the first
    paint."""
    assert theme.colours("am") is theme.colours("sapphire")
    assert theme.tokens("nonsense")["theme"] == "sapphire"


def test_font_families_put_each_languages_own_family_after_segoe():
    assert theme.font_families("ja")[:2] == ("Segoe UI", "Yu Gothic UI")
    assert theme.font_families("zh", "s")[1] == "Microsoft YaHei UI"
    assert theme.font_families("zh", "t")[1] == "Microsoft JhengHei UI"


def test_percentages_out_of_range_are_refused_and_over_100_scale_down():
    """CSS: a percentage outside 0–100 makes the mix invalid; two summing over 100 are scaled to 100 (opaque)."""
    with pytest.raises(ValueError):
        theme.mix("#62b6f2", 120, "#111419")
    with pytest.raises(ValueError):
        theme.mix("#62b6f2", -5, "#111419")
    assert theme.mix("#62b6f2", 60, "#111419", 60) == theme.mix("#62b6f2", 50, "#111419", 50)


def test_a_generated_cover_is_the_mocks_gradient_for_its_titles_hue():
    """A title with no cover gets the mock's painted one (W2.2): hsl(h 45% 30%) → hsl(h+40 40% 16%), h from the title.
    The same title always gives the same cover; two titles, two hues."""
    top, bottom = theme.generated_cover("星降る街の小さな工房")
    assert re.fullmatch(r"#[0-9a-f]{6}", top) and re.fullmatch(r"#[0-9a-f]{6}", bottom)
    assert theme.generated_cover("星降る街の小さな工房") == (top, bottom)
    assert theme.generated_cover("海辺の図书室") != (top, bottom)
    assert theme._hsl(0, 1.0, 0.5) == "#ff0000" and theme._hsl(120, 1.0, 0.25) == "#008000"
    assert theme.title_hue("") == 0 and 0 <= theme.title_hue("雷鸣之剑与见习魔女") < 360

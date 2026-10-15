"""The 3.0 window's theme tokens (`app/theme.py`, W1.3; the window's spec 04 §4.2, 05 §5.5, A4; the redesign scope).

What a wrong answer would cost: a colour that drifts from the redesign Sonic signed (2026-10-14, RS-1: the new palette,
flat, one theme); a retired theme name (an old settings.json) that fails the first paint instead of painting the night;
a mix the Qt shell paints differently from the browser's `color-mix(in oklab)`; body text under the contrast floor; a
surface darker than what it lies on (the brief's first rule); a status colour (learned / heads-up / problem) or a gem's
colour that stops meaning one thing.
"""
import re

import pytest

from app import theme

# The redesign's foundation brief (§3–4) and its reference page (list-r14m :651, :1742–1746, :1975; gem-kit.js :31),
# copied verbatim: the module must equal them.
BRIEF_ROOM = {
    "ground": "#070a0f", "content": "#04060a", "frame": "#0c1017", "goal-bar": "#10151e", "slab": "#0a0e15",
    "cut": "#05070c", "overlay": "#111a2b", "overlay-cut": "#090e18", "overlay-hover": "#182439", "ring": "#26d1cf",
}
REFERENCE_NIGHT = {
    "bg": "#04060a", "surface": "#0a0e14", "raised": "#101621", "line": "#161e2a", "line-hi": "#243044",
    "ink": "#e6ecf5", "ink-dim": "#7d8aa2", "ink-faint": "#56627a",
}
GEM_KIT = {"sapphire": ("#1d4fae", "#4b8ff0", "#d6e7ff"), "emerald": ("#13744f", "#3cc48f", "#d8f8ea"),
           "ruby": ("#98203a", "#e2546f", "#ffdbe3")}


def test_one_theme_ships_the_night():
    """RS-1: one theme in 3.0; Blue, Lighter blue and Sapphire are retired with their picker (themes return in 3.1)."""
    assert theme.THEMES == ("night",) and theme.DEFAULT_THEME == "night"
    assert set(theme.THEME_NAMES) == set(theme.THEMES)
    for table in (theme.IRIS, theme.GLOW, theme.TITLE_BAR):
        assert set(table) == {"night"}


def test_the_room_is_the_briefs():
    """The surfaces by layer, as the brief writes them (slate navy ✅, the rest ✍ used as written)."""
    c = theme.colours()
    assert {k: c[k] for k in BRIEF_ROOM} == BRIEF_ROOM
    assert c["dim"] == "#04060acc"                                   # the room dims: content at 80 %


def test_the_painters_tokens_are_the_references_night_set():
    """The names every painter reads take the night set the reference lays over the mock; `bg` is the content."""
    c = theme.colours()
    assert {k: c[k] for k in REFERENCE_NIGHT} == REFERENCE_NIGHT
    assert c["bg"] == c["content"]


def test_nearer_is_lighter_never_darker_than_what_it_lies_on():
    """The brief's first rule: the frame is lighter than the content, the overlay lighter than the frame, the Goal bar
    lighter than the frame it lifts from; a cut is darker than its surface (rule 4)."""
    c = theme.colours()

    def lum(name):
        r, g, b, _ = theme.parse(c[name])
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    assert lum("content") < lum("frame") < lum("goal-bar") < lum("overlay") < lum("overlay-hover")
    assert lum("cut") < lum("frame") and lum("overlay-cut") < lum("overlay")
    assert lum("content") < lum("ground") < lum("frame")


def test_the_iris_and_the_gems_are_the_briefs():
    """The iris `#36c9cf → #4f9cf0 → #a98bff` (✅, purple kept); the gems as gem-kit draws them, by kind (✅)."""
    assert [colour for _pos, colour in theme.IRIS["night"]] == ["#36c9cf", "#4f9cf0", "#a98bff"]
    assert dict(theme.GEM) == GEM_KIT
    assert dict(theme.KIND_GEM) == {"shows": "sapphire", "reading": "emerald", "videos": "ruby"}


def test_the_percent_bands_are_the_status_colours():
    """% ≥ 97 learned green, 93–96 ink, < 93 amber (brief §3 ✅): the same colours as the statuses."""
    assert theme.STATUS["ok"] == "#7fcf9f" and theme.STATUS["warn"] == "#e7bf72"


def test_every_mix_is_worked_out_and_none_is_left_for_a_retired_part():
    """Every mix resolves to a hex; the old mock's mixes for parts the redesign drops are gone, the new parts' (the
    frame's edge, the groove and its lip, a cut's walls, the well) are there."""
    c = theme.colours()
    for name in theme.MIXES:
        assert re.fullmatch(r"#[0-9a-f]{6}([0-9a-f]{2})?", c[name]), name
    for retired in ("arrivals-fill", "settings-even", "join-on", "finished-bucket-lit", "tab-bar", "header-top"):
        assert retired not in theme.MIXES
    for new in ("frame-edge", "groove", "groove-lip", "cut-wall-top", "cut-wall-low", "well-lit"):
        assert new in theme.MIXES


def test_the_mixes_land_on_the_browsers_values():
    """Qt can't mix colours: each `color-mix(in oklab)` is worked out here, as a browser does (these answers are
    Edge's own, headless, 2026-10-14, for the same inputs; one step at most per channel, for rounding)."""
    browser = {"top20-line": "#32536f", "watched-chip-fill": "#132230", "watched-chip-border": "#375d7d",
               "frame-edge": "#020305", "cut-wall-low": "#19212f", "well-lit": "#101a1b", "row-hover": "#0f141d"}
    c = theme.colours()
    for name, expected in browser.items():
        got = c[name]
        assert all(abs(int(got[i:i + 2], 16) - int(expected[i:i + 2], 16)) <= 1 for i in (1, 3, 5)), (name, got)


def test_a_mix_with_transparent_keeps_the_colour_at_its_share_as_alpha():
    """`color-mix(in oklab, X p%, transparent)` is X at p % alpha (premultiplied): the browser's rule."""
    assert theme.mix("#7fcf9f", 12, "transparent") == "#7fcf9f1f"
    assert theme.mix("#62b6f2", 70, "transparent") == "#62b6f2b3"


def test_two_shares_under_100_scale_the_alpha():
    """raised 70 % + accent 12 %: 82 % in all, so 82 % alpha (Generate's hover), as CSS Color 5 says."""
    assert theme.colours()["generate-hover"].endswith("d1")


def test_body_text_passes_the_contrast_floor_on_every_surface():
    """ink and ink-dim at least 4.5:1 on the content, a row, a raised control, the frame and an overlay (05 §5.5);
    ink-faint is decoration only. Under the hand (an overlay's hovered item) the text is ink."""
    c = theme.colours()
    for ink in ("ink", "ink-dim"):
        for ground in ("bg", "surface", "raised", "frame", "overlay"):
            assert theme.contrast(c[ink], c[ground]) >= 4.5, (ink, ground)
    assert theme.contrast(c["ink"], c["overlay-hover"]) >= 7


def test_the_contrast_figures():
    """The figures on a row's ground (WCAG), pinned so the arithmetic stays the one recorded here."""
    c = theme.colours()
    got = tuple(round(theme.contrast(c[k], c["surface"]), 1) for k in ("ink", "ink-dim", "ink-faint", "accent"))
    assert got == (16.3, 5.6, 3.2, 8.7)


def test_status_colours_and_source_chips_never_take_the_accent():
    """learned / heads-up / problem mean one thing everywhere: the accent is none of them."""
    c = theme.colours()
    assert {k: c[k] for k in theme.STATUS} == dict(theme.STATUS)
    assert c["accent"] not in theme.STATUS.values()
    assert theme.STATUS["bad"] == "#c02040"


def test_tooltips_and_toasts_are_overlays():
    """Brief §4: tooltips and toasts are layer 2, slate navy and solid (no see-through panel, rule 2 / §9)."""
    assert theme.FIXED["tooltip"] == theme.FIXED["toast"] == theme.ROOM["overlay"]
    assert theme.parse(theme.FIXED["tooltip"])[3] == 1.0


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


def test_title_bar_and_palette_are_plain_hex_in_the_frames_colour():
    """The Qt shell makes the title bar and the QPalette from plain hex: nothing here is a Qt object. The caption is the
    frame's colour, so the title bar and the header read as one frame."""
    for value in list(theme.TITLE_BAR["night"].values()) + list(theme.palette().values()):
        assert re.fullmatch(r"#[0-9a-f]{6}", value), value
    assert theme.TITLE_BAR["night"] == {"caption": "#0c1017", "border": "#161e2a", "text": "#e6ecf5"}
    assert theme.palette()["Window"] == "#04060a"


@pytest.mark.parametrize("retired", ["sapphire", "hb", "sky", "am", "nonsense", None])
def test_a_retired_or_unknown_theme_paints_the_night(retired):
    """An old settings.json naming Blue, Lighter blue or Sapphire (or a hand-edited name) paints the one theme — never
    fails the first paint."""
    assert theme.colours(retired) is theme.colours("night")
    assert theme.tokens(retired)["theme"] == "night"


def test_font_families_put_each_languages_own_family_after_segoe():
    assert theme.font_families("ja")[:2] == ("Segoe UI", "Yu Gothic UI")
    assert theme.font_families("zh", "s")[1] == "Microsoft YaHei UI"
    assert theme.font_families("zh", "t")[1] == "Microsoft JhengHei UI"


def test_a_path_is_never_drawn_in_a_family_that_turns_the_backslash_into_a_yen_sign():
    """Yu Gothic UI and Meiryo draw the backslash as a yen sign: every path takes its own family, Segoe UI first."""
    assert theme.PATH_FAMILY[0] == "Segoe UI"
    assert not set(theme.PATH_FAMILY) & {"Yu Gothic UI", "Yu Gothic", "Meiryo", "MS Gothic", "MS UI Gothic"}


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

"""The 3.0 window's look as data: three themes, every colour the mock mixes, the type scale, sizes, radii, shadows and
the motion tokens (W1.3; the window's spec 04 §4.2, 05 §5.5, A4).

Qt-free and Tk-free (a test imports this module alone and checks): the Qt shell builds its stylesheet and its dark
palette from these plain values (W2.1), the painters read the same names, and nothing else spells a colour.

Sources: the look test's `theme.css` (G1.6 round 3: `tracks/window/work/w02/mock-g16/theme.css`) for the token sets,
its `mock.html` for every `color-mix(in oklab, …)` (the line each mix comes from is named beside it), and A4 for the
type, sizes, radii, shadows and motion. Qt has no colour mixing, so each mix is worked out here once per theme, the way
a browser does it (CSS Color 5: OKLab, premultiplied alpha); a mix with `transparent` keeps its alpha (`#rrggbbaa`), and
`over()` lays such a colour on a ground when an opaque one is needed.
"""
import math
from types import MappingProxyType

THEMES = ("hb", "sky", "sapphire")          # `am` (Amethyst) is not shipped
DEFAULT_THEME = "hb"
THEME_NAMES = {"hb": "Blue", "sky": "Lighter blue", "sapphire": "Sapphire"}

# --- Colours: each theme's own (theme.css) ------------------------------------------------------------------------- #
_OWN = {
    "hb": {
        "bg": "#111419", "surface": "#171b22", "raised": "#1f242d", "line": "#2a303a", "line-hi": "#3a4250",
        "ink": "#e9ecf1", "ink-dim": "#939cab", "ink-faint": "#626b79",
        "accent": "#62b6f2", "accent-2": "#b894ff", "accent-deep": "#2a6fa8", "accent-wash": "#1a2a3a",
    },
    "sky": {
        "bg": "#1a2533", "surface": "#21303f", "raised": "#2a3b4e", "line": "#34485e", "line-hi": "#456079",
        "ink": "#eef4fb", "ink-dim": "#a6b8cc", "ink-faint": "#7f93aa",
        "accent": "#8fd0fa", "accent-2": "#c7abff", "accent-deep": "#3a86c4", "accent-wash": "#24405a",
    },
    "sapphire": {
        "bg": "#0a1628", "surface": "#0f1f36", "raised": "#162a46", "line": "#1f3a5c", "line-hi": "#2c5079",
        "ink": "#eaf2fc", "ink-dim": "#9db5d3", "ink-faint": "#7894b6",
        "accent": "#4fb0f0", "accent-2": "#bc9cff", "accent-deep": "#1b67b0", "accent-wash": "#13355a",
    },
}
# The iris (90°): the mark's run carried into the purple — the Up next edge, progress fills and the wordmark only.
IRIS = {
    "hb": ((0.0, "#36c9cf"), (0.45, "#4f9cf0"), (1.0, "#a98bff")),
    "sky": ((0.0, "#4fd6dc"), (0.45, "#6fb4f6"), (1.0, "#b9a0ff")),
    "sapphire": ((0.0, "#26d1cf"), (0.45, "#2f8fe0"), (1.0, "#a98bff")),
}
# The glow (`--glow`): a 1 px ring, then a soft drop (x, y, blur, spread, colour).
GLOW = {
    "hb": ("#62b6f255", (0, 10, 34, -10, "#3f8fe07a")),
    "sky": ("#8fd0fa55", (0, 10, 34, -10, "#5aa8ec7a")),
    "sapphire": ("#4fb0f055", (0, 10, 34, -10, "#1e83b97a")),
}
# Windows 11's title bar per theme: caption, border, caption text (05 §5.5). Windows 10 takes the dark bar.
TITLE_BAR = {
    "hb": {"caption": "#191f27", "border": "#2a303a", "text": "#e9ecf1"},
    "sky": {"caption": "#21303f", "border": "#34485e", "text": "#eef4fb"},
    "sapphire": {"caption": "#0f1f36", "border": "#1f3a5c", "text": "#eaf2fc"},
}

# Never themed: the status colours (glyph + label, no accent may look like them) and the source chips (theme.css
# :113–121; mock.html :519–521). `bad` is a fill only, with `bad-type` on it.
STATUS = MappingProxyType({"ok": "#7fcf9f", "warn": "#e7bf72", "bad": "#c02040", "bad-type": "#f8f0e0"})
SOURCE_INK = MappingProxyType({"hato": "#f8a890", "youtube": "#ff6f7a", "anilist": "#5ec6ff"})
# Hard-coded in the mock, not tokens (A4): the same in every theme.
FIXED = MappingProxyType({
    "tooltip": "#0c0f14f5", "toast": "#0d1015f0", "scrim": "#05070acc", "on-accent": "#0b1018",
    "cover-badge": "#000000b0", "cover-badge-hi": "#000000b8", "cover-badge-border": "#ffffff40",
    "watched-track": "#00000070", "cover-ink": "#f4efe6", "mark-shadow": "#1e83b940", "page": "#0a0b0f",
    "cover-ground": "#0c0d11",
})

# Every color-mix the mock computes: name -> (mock.html line, expression). An expression is a colour (a token name, a
# fixed name, `#hex` or "transparent") or ("mix", a, pa, b, pb) — `pb` None when CSS leaves it out.
MIXES = {
    "header-top": (166, ("mix", "surface", 70, "accent", 5)),       # sums to 75 %: 75 % alpha (laid over `bg`)
    "arrivals-border": (210, ("mix", "accent", 45, "line", None)),
    "arrivals-fill": (210, ("mix", "accent", 10, "surface", None)),
    "arrivals-pressed": (214, ("mix", "accent", 22, "surface", None)),
    "generate-hover": (228, ("mix", "raised", 70, "accent", 12)),   # sums to 82 %
    "generate-stale-glow": (230, ("mix", "accent", 70, "transparent", None)),
    "tab-bar": (235, ("mix", "surface", 55, "bg", None)),
    "tab-drop": (241, ("mix", "ok", 12, "transparent", None)),
    "status-in": (321, ("mix", "ok", 12, "transparent", None)),
    "status-part-ring": (322, ("mix", "ok", 40, "transparent", None)),
    "status-mining": (323, ("mix", "accent", 12, "transparent", None)),
    "status-nomedia-border": (334, ("mix", "warn", 55, "transparent", None)),
    "top20-line": (348, ("mix", "accent", 38, "line", None)),
    "watched-chip-fill": (375, ("mix", "accent", 20, "bg", None)),
    "watched-chip-border": (375, ("mix", "accent", 45, "line", None)),
    "side-column": (428, ("mix", "surface", 70, "bg", None)),
    "finished-bucket-lit": (467, ("mix", "ok", 12, "surface", None)),
    "mine-inset-lit": (471, ("mix", "ok", 14, "bg", None)),
    "source-hato": (519, ("mix", "#f8a890", 16, "transparent", None)),
    "source-youtube": (520, ("mix", "#ff3347", 17, "transparent", None)),
    "source-anilist": (521, ("mix", "#02a9ff", 16, "transparent", None)),
    "needs-row-border": (548, ("mix", "line", 60, "transparent", None)),
    "join-candidate-ring": (577, ("mix", "ok", 55, "transparent", None)),
    "join-candidate-outline": (577, ("mix", "ok", 70, "transparent", None)),
    "join-on": (578, ("mix", "ok", 9, "surface", None)),
    "settings-nav": (586, ("mix", "surface", 45, "bg", None)),
    "settings-row-border": (604, ("mix", "line", 60, "transparent", None)),
    "settings-even": (607, ("mix", "surface", 93, "accent", 7)),
    "settings-even-more": (608, ("mix", "bg", 50, ("mix", "surface", 93, "accent", 7), None)),
    "settings-group-border": (617, ("mix", "line", 60, "transparent", None)),
    "settings-more": (622, ("mix", "bg", 55, "surface", None)),
    "switch-on": (625, ("mix", "accent", 35, "bg", None)),
    "ok-icon": (645, ("mix", "ok", 16, "transparent", None)),
    "anilist-note": (658, ("mix", "#02a9ff", 9, "bg", None)),
    "anilist-note-border": (658, ("mix", "#02a9ff", 30, "line", None)),
    "level-stop-ring": (674, ("mix", "accent", 25, "transparent", None)),
    "placeholder-ring": (716, ("mix", "accent", 60, "transparent", None)),
    "slot-ring": (718, ("mix", "accent", 60, "transparent", None)),
    "wizard-steps": (737, ("mix", "surface", 45, "bg", None)),
    "wizard-done": (746, ("mix", "ok", 16, "transparent", None)),
    "star-border": (765, ("mix", "accent-2", 40, "transparent", None)),
    "star-fill": (766, ("mix", "accent-2", 10, "transparent", None)),
    "badge-new": (777, ("mix", "accent", 13, "transparent", None)),
}
# Opaque versions of the alpha mixes, laid on the ground the mock shows them on (research/09's table).
OVER = {"header-top": "bg", "status-in": "surface", "status-mining": "surface", "source-hato": "surface",
        "source-youtube": "surface", "source-anilist": "surface"}


# --- Colour arithmetic (CSS Color 4 / 5) --------------------------------------------------------------------------- #
def parse(color):
    """`#rgb`, `#rrggbb` or `#rrggbbaa` (or "transparent") -> (r, g, b, a), channels 0–255, alpha 0–1."""
    if color == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    h = color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) not in (6, 8):
        raise ValueError(f"not a colour: {color!r}")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
    return (float(r), float(g), float(b), a)


def hex_of(r, g, b, a=1.0):
    """(r, g, b[, a]) -> `#rrggbb`, or `#rrggbbaa` when not opaque. Channels rounded and clamped, as a browser does."""
    def byte(v):
        return max(0, min(255, int(math.floor(v + 0.5))))       # half up, as a browser rounds (never to even)
    out = "#%02x%02x%02x" % (byte(r), byte(g), byte(b))
    return out if a >= 1.0 - 1e-9 else out + "%02x" % byte(a * 255)


def _to_linear(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_linear(c):
    c = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return c * 255.0


def _cbrt(x):
    return x ** (1 / 3) if x >= 0 else -((-x) ** (1 / 3))


def to_oklab(r, g, b):
    r, g, b = _to_linear(r), _to_linear(g), _to_linear(b)
    l = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def from_oklab(L, a, b):
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (_from_linear(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
            _from_linear(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
            _from_linear(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s))


def _mix(c1, p1, c2, p2=None):
    """`mix` before rounding: (r, g, b, a) floats."""
    for p in (p1, p2):
        if p is not None and not 0 <= p <= 100:
            raise ValueError(f"a color-mix percentage is 0-100, not {p}")
    if p2 is None:
        p2 = 100 - p1
    total = p1 + p2
    if total <= 0:
        raise ValueError("color-mix percentages sum to zero")
    scale = min(total, 100) / 100.0
    w1, w2 = p1 / total, p2 / total
    (r1, g1, b1, a1), (r2, g2, b2, a2) = parse(c1), parse(c2)
    lab1, lab2 = to_oklab(r1, g1, b1), to_oklab(r2, g2, b2)
    alpha = a1 * w1 + a2 * w2
    if alpha <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    lab = [(x1 * a1 * w1 + x2 * a2 * w2) / alpha for x1, x2 in zip(lab1, lab2)]
    r, g, b = from_oklab(*lab)
    return (r, g, b, alpha * scale)


def mix(c1, p1, c2, p2=None):
    """CSS `color-mix(in oklab, c1 p1%, c2 p2%)`: each percentage 0–100; one left out is the rest of 100; two that sum
    over 100 are scaled down to it, two that sum under 100 scale the alpha by their sum; premultiplied alpha.
    -> `#rrggbb` or `#rrggbbaa`."""
    return hex_of(*_mix(c1, p1, c2, p2))


def over(color, ground):
    """`color` (a hex, or unrounded (r, g, b, a)) laid on an opaque `ground`, in sRGB as a browser composites ->
    `#rrggbb`."""
    r, g, b, a = parse(color) if isinstance(color, str) else color
    gr, gg, gb, _ = parse(ground)
    return hex_of(r * a + gr * (1 - a), g * a + gg * (1 - a), b * a + gb * (1 - a))


def contrast(c1, c2):
    """WCAG 2 contrast ratio of two opaque colours."""
    def lum(c):
        r, g, b, _ = parse(c)
        return 0.2126 * _to_linear(r) + 0.7152 * _to_linear(g) + 0.0722 * _to_linear(b)
    hi, lo = sorted((lum(c1), lum(c2)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# --- One theme's colours, everything worked out ---------------------------------------------------------------------- #
def _resolve(expr, own, exact=False):
    """An expression's colour: hex, or (exact) the unrounded (r, g, b, a) of a mix, for laying it on a ground."""
    if isinstance(expr, tuple):
        _, a, pa, b, pb = expr
        value = _mix(_resolve(a, own), pa, _resolve(b, own), pb)
        return value if exact else hex_of(*value)
    if expr.startswith("#") or expr == "transparent":
        return expr
    if expr in own:
        return own[expr]
    if expr in STATUS:
        return STATUS[expr]
    return FIXED[expr]


def _build(theme):
    own = dict(_OWN[theme])
    colours = dict(own)
    colours.update(STATUS)
    for name, (_line, expr) in MIXES.items():
        colours[name] = _resolve(expr, own)
    for name, ground in OVER.items():
        colours[name + "-opaque"] = over(_resolve(MIXES[name][1], own, exact=True), own[ground])
    return MappingProxyType(colours)


_COLOURS = {theme: _build(theme) for theme in THEMES}


def colours(theme=DEFAULT_THEME):
    """Every colour of `theme` by name (read-only): its own tokens, the status colours and every mix."""
    return _COLOURS[theme if theme in _COLOURS else DEFAULT_THEME]


def palette(theme=DEFAULT_THEME):
    """The dark palette's colours as plain hex, by Qt's role names (the Qt shell makes the QPalette from it)."""
    c = colours(theme)
    return MappingProxyType({
        "Window": c["bg"], "WindowText": c["ink"], "Base": c["surface"], "AlternateBase": c["raised"],
        "Text": c["ink"], "PlaceholderText": c["ink-faint"], "Button": c["raised"], "ButtonText": c["ink"],
        "BrightText": STATUS["bad-type"], "Highlight": c["accent-deep"], "HighlightedText": c["ink"],
        "ToolTipBase": over(FIXED["tooltip"], c["bg"]), "ToolTipText": c["ink"], "Link": c["accent"],
        "LinkVisited": c["accent-2"], "Light": c["line-hi"], "Midlight": c["line"], "Mid": c["line"],
        "Dark": c["bg"], "Shadow": "#000000", "DisabledText": c["ink-faint"],
    })


# --- Type ---------------------------------------------------------------------------------------------------------- #
FAMILY = ("Segoe UI",)
FAMILY_BY_LANGUAGE = {"ja": ("Yu Gothic UI", "Yu Gothic", "Meiryo"), "zh-hans": ("Microsoft YaHei UI",),
                      "zh-hant": ("Microsoft JhengHei UI",)}
MONO = ("Consolas", "Cascadia Mono")
LINE_HEIGHT = 1.45
TEXT_SIZES = {"S": 1.0, "M": 1.15, "L": 1.3}
DEFAULT_TEXT_SIZE = "M"
# The mock's weights 550 / 650 draw as 600 / 700 (Segoe UI has neither).
DRAWN_WEIGHT = {400: 400, 500: 500, 550: 600, 600: 600, 650: 700, 700: 700}
# name -> (base px, the mock's weight); every size × the text size.
TYPE = {
    "first-run-heading": (22, 400), "hero-title": (21, 650), "arrival-number": (19, 650), "wordmark": (18, 650),
    "page-heading": (17, 400), "panel-title": (16, 650), "dialog-title": (16, 650), "current-heading": (15, 650),
    "sheet-heading": (15, 650), "tray-heading": (14, 400), "needs-title": (14, 400), "help-mark": (14, 400),
    "row-title": (13.5, 600), "tab": (13.5, 600), "bucket": (13.5, 600), "settings-search": (13.5, 600),
    "body": (13, 550), "button": (13, 550), "menu-item": (13, 550), "input": (12.5, 400), "hero-sub": (12.5, 400),
    "segmented": (12.5, 400), "select": (12.5, 400), "number-field": (12.5, 400), "row-sub": (12, 400),
    "diff": (12, 400), "footer": (12, 400), "tooltip": (12, 500), "status-pill": (11.5, 600), "chip": (11.5, 600),
    "eyebrow": (11, 700), "badge": (11, 700), "mini": (11, 700), "group-label": (10.5, 700),
    "source-chip": (10.5, 650), "key-hint": (10.5, 700), "new-per-episode": (10, 600),
}
LETTER_SPACING_EM = {"eyebrow": 0.12, "group-label": 0.1}


def font_families(language="ja", script=None):
    """Segoe UI first, then the language's own family (so Han characters take its shapes): Japanese, or Chinese in
    Simplified (`script` "s" or "hans") or Traditional ("t" or "hant")."""
    if language == "zh":
        key = "zh-hant" if script in ("t", "hant", "tw") else "zh-hans"
    else:
        key = "ja"
    return FAMILY + FAMILY_BY_LANGUAGE[key]


def text_factor(text_size=DEFAULT_TEXT_SIZE):
    return TEXT_SIZES.get(text_size, TEXT_SIZES[DEFAULT_TEXT_SIZE])


def font(name, text_size=DEFAULT_TEXT_SIZE):
    """(px, drawn weight) of a type role at a text size."""
    px, weight = TYPE[name]
    return (round(px * text_factor(text_size), 2), DRAWN_WEIGHT[weight])


# --- Sizes, spacing, radii, shadows (A4) ---------------------------------------------------------------------------- #
# name -> px, scaled by the text size unless named in FIXED_SIZES.
SIZES = {
    "row": 56, "episode-row": 36, "row-cover-w": 31, "row-cover-h": 44, "hero-cover-w": 88, "hero-cover-h": 126,
    "col-diff": 118, "col-stat": 150, "col-acts": 118, "button": 32, "button-sm": 26, "icon-button": 28,
    "status-pill": 24, "search-w": 230, "search-w-narrow": 172, "search-h": 32, "generate": 34, "footer": 34,
    "goal-strip": 46, "bucket": 58, "tray": 452, "search-results": 470, "side-panel": 360, "side-panel-narrow": 316,
    "side-rail": 330, "settings-nav": 228, "settings-card-max": 820, "settings-search-max": 520,
    "settings-search-h": 38, "menu-min": 264, "pop": 390, "dialog": 560, "tooltip-max": 300, "switch-w": 36,
    "switch-h": 20, "arrival-number": 56, "icon-square": 26, "title-to-number": 28, "channel-cap": 130,
    "wizard-steps": 244,
}
FIXED_SIZES = frozenset({"hero-cover-w", "hero-cover-h", "switch-w", "switch-h"})
ICON_PX = (13, 20)                       # icons are fixed sizes in this range
WINDOW_MIN = (1000, 620)
NARROW_BELOW = 1150
SPACING = {"header": (12, 18, 11), "current-body": (16, 24, 84), "list-gap": 2, "settings-row": (11, 16),
           "settings-sub-indent": 36, "settings-card-gap": 16, "tray-row": (7, 8)}
RADII = {"r": 12, "r-sm": 8, "button": 9, "button-sm": 7, "icon-button": 7, "pill": 99, "cover-row": 5,
         "cover-tile": 7, "cover-goal": 6, "cover-stack": 3, "tray": 14, "search-results": 14, "menu": 11,
         "tooltip": 8, "toast": 12, "dialog": 16, "sheet": 16, "source-chip": 4}
# name -> (x, y, blur, spread, colour); the ghost adds a 1 px accent ring, the primary button glows on hover.
SHADOWS = {
    "tray": (0, 30, 70, -20, "#000000"), "search-results": (0, 30, 70, -20, "#000000"),
    "menu": (0, 24, 50, -16, "#000000"), "dialog": (0, 40, 90, -20, "#000000"),
    "toast": (0, 20, 40, -14, "#000000"), "tooltip": (0, 14, 32, -12, "#000000"),
    "sheet": (0, -30, 60, -20, "#000000"), "drag-ghost": (0, 24, 50, -12, "#000000cc"),
    "hero-cover": (0, 10, 26, -10, "#000000"), "primary-button": (0, 6, 18, -8, "accent"),
}


def size(name, text_size=DEFAULT_TEXT_SIZE):
    """A size in px at a text size (fixed sizes never scale)."""
    px = SIZES[name]
    return px if name in FIXED_SIZES else round(px * text_factor(text_size), 2)


# --- Motion (05 §5.5; A4 Motion) ------------------------------------------------------------------------------------ #
EASE = (0.2, 0.7, 0.3, 1.0)              # cubic-bezier(.2, .7, .3, 1)
FAST = 120                               # ms: hovers, the switch's track colour
SLOW = 260                               # ms
MOTION = MappingProxyType({
    "gap-slide": 190, "ghost-glide": 160, "ghost-removed": 150, "tray-fade": 140, "overlay-pop": 140,
    "tray-pop": 160, "side-panel": 260, "side-panel-shift": 24, "sheet": 260, "buckets": 260, "buckets-rise": 40,
    "dialog-scrim": 160, "dialog-card": 180, "toast-rise": 260, "toast-rise-px": 12, "toast-shown": 6500,
    "toast-shown-anki": 12000, "row-flash": 1600, "switch-knob": 260, "chevron": 260, "hover": FAST,
    "mining-spin": 1200, "footer-pulse": 1400, "generate-bar": 300, "tooltip-delay": 380, "tooltip-again": 60,
    "tooltip-again-within": 500, "fit-debounce": 80, "drag-start-px": 6, "click-swallow-after-drag": 50,
    "auto-scroll-px-per-frame": 12, "auto-scroll-edge": 50, "auto-scroll-dock": 48,
})


def tokens(theme=DEFAULT_THEME, text_size=DEFAULT_TEXT_SIZE):
    """Everything the shell needs for one theme at one text size, in one read-only mapping."""
    return MappingProxyType({
        "theme": theme if theme in _COLOURS else DEFAULT_THEME, "colours": colours(theme),
        "iris": IRIS.get(theme, IRIS[DEFAULT_THEME]), "glow": GLOW.get(theme, GLOW[DEFAULT_THEME]),
        "title_bar": TITLE_BAR.get(theme, TITLE_BAR[DEFAULT_THEME]), "palette": palette(theme),
        "text_factor": text_factor(text_size), "fonts": {name: font(name, text_size) for name in TYPE},
        "sizes": {name: size(name, text_size) for name in SIZES}, "radii": dict(RADII), "shadows": dict(SHADOWS),
        "ease": EASE, "fast": FAST, "slow": SLOW, "motion": MOTION,
    })

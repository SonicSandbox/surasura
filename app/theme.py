"""The 3.0 window's look as data: one theme (the redesign's night palette, flat), every colour it mixes, the type
scale, sizes, radii, shadows and the motion tokens (W1.3; the window's spec 04 §4.2, 05 §5.5, A4; the redesign scope).

Qt-free and Tk-free (a test imports this module alone and checks): the Qt shell builds its stylesheet and its dark
palette from these plain values (W2.1), the painters read the same names, and nothing else spells a colour.

**One theme in 3.0** (Sonic, 2026-10-14, RS-1: new layout + the new palette flat, one theme): Blue, Lighter blue and
Sapphire are retired with their picker; themes (a light one included) return in 3.1, with the stone texture, the light
and the celebrations. Sources: the redesign's foundation brief (Design Doctrine `trials/surasura-2026-10-09/
95-foundation-brief.md` §3–4: the room, the surfaces, the iris, the gems, the % bands; its ✍ values used as written,
slate navy ✅), its reference page `worlds/list-r14m.html` (the night token set it lays over the mock, line 651; the
overlays' stone, `.f-sv1`, line 1975; the frame, `.f-near`, lines 1741–1746) and `worlds/gem-kit.js` (`GEM`, line 31).
Qt has no colour mixing, so each mix is worked out here once, the way a browser does it (CSS Color 5: OKLab,
premultiplied alpha); a mix with `transparent` keeps its alpha (`#rrggbbaa`), and `over()` lays such a colour on a
ground when an opaque one is needed. A theme argument anywhere still reads the one theme: an old settings.json naming
Sapphire paints the night, and never fails.
"""
import math
from types import MappingProxyType

THEMES = ("night",)                         # one theme in 3.0 (RS-1); themes return in 3.1
DEFAULT_THEME = "night"
THEME_NAMES = {"night": "Night"}

# --- Colours: the theme's own tokens ---------------------------------------------------------------------------- #
# The names every painter and the stylesheet read: the night set the reference lays over the mock (list-r14m :651,
# `#win.theme-hb`), whose accents are the mock's Blue ones; `bg` is the content's ground (`.f-near .body`, :1742):
# the list, Finished, Needs you and Settings sit deepest.
_OWN = {
    "night": {
        "bg": "#04060a", "surface": "#0a0e14", "raised": "#101621", "line": "#161e2a", "line-hi": "#243044",
        "ink": "#e6ecf5", "ink-dim": "#7d8aa2", "ink-faint": "#56627a",
        "accent": "#62b6f2", "accent-2": "#b894ff", "accent-deep": "#2a6fa8", "accent-wash": "#1a2a3a",
    },
}
# The room and its surfaces by layer (brief §4): 0 the content's ground; 1 the frame (header, tabs, footer, the dock),
# nearer and a shade lighter; 1 cut (New arrivals, search, the buckets' wells), darker than its surface; 2 the overlays
# in slate navy (✅) with their cuts and the item under the hand; 3 a dialog, dimming the room. Nearer is lighter and
# bluer, never darker than what it lies on (rule 1); edges top and bottom only (rule 3).
ROOM = MappingProxyType({
    "ground": "#070a0f",                    # the room itself, behind everything
    "content": "#04060a",                   # layer 0: the list's ground (= `bg`)
    "frame": "#0c1017",                     # layer 1: header, tabs, footer, the dock
    "goal-bar": "#10151e",                  # Goal's bar, lifted very slightly off the dock
    "goal-bar-edge": "#1a2230",             # its edge (list-r14m :1746)
    "slab": "#0a0e15",                      # layer 0 slab: a Needs-you card
    "cut": "#05070c",                       # layer 1 cut: a floor (New arrivals, search, a bucket's well)
    "overlay": "#111a2b",                   # layer 2: menus, the level pop, the tray, results, tooltips, toasts ✅
    "overlay-cut": "#090e18",               # layer 2 cut: the pop's well, a dialog's input
    "overlay-hover": "#182439",             # layer 2: a menu item or tray row under the hand
    "overlay-edge-top": "#283752",          # an overlay's lit top edge (`.f-sv1` --ov-et)
    "overlay-edge-side": "#1a253a",         # its sides' hairline, as quiet as the face (--ov-es)
    "overlay-edge-bottom": "#0a101b",       # its darkest, bottom edge (--ov-eb)
    "ring": "#26d1cf",                      # the cyan ring: next (✅)
    # text on an overlay (list-r14m :1979 lightens the faint one inside overlays): grey text that says something
    # clears 4.5:1 on the overlay and on its item under the hand (Sonic: "Readability is critical"); the faint one is
    # for what's disabled or decorative
    "overlay-ink-dim": "#8693ab",
    "overlay-ink-faint": "#6d7b97",
    "dim": "#04060acc",                     # a dialog dims the room: the content's colour at 80 %
})
# The iris (90°): Surasura's run carried into the purple — the wordmark's second half, the tab's vein, progress (✅).
IRIS = {"night": ((0.0, "#36c9cf"), (0.45, "#4f9cf0"), (1.0, "#a98bff"))}
# The glow (`--glow`): a 1 px ring, then a soft drop (x, y, blur, spread, colour) — on the active thing only.
GLOW = {"night": ("#62b6f255", (0, 10, 34, -10, "#3f8fe07a"))}
# Windows 11's title bar: caption, border, caption text (05 §5.5), in the frame's colour. Windows 10 takes the dark bar.
TITLE_BAR = {"night": {"caption": "#0c1017", "border": "#161e2a", "text": "#e6ecf5"}}

# Never themed: the status colours (glyph + label, no accent may look like them) and the source chips (theme.css
# :113–121; mock.html :519–521). `ok` and `warn` are also the % bands (brief §3 ✅: ≥ 97 learned, 93–96 ink, < 93
# heads-up; `view_rows.pct_tone`), and amber is *needs you*. `bad` is a fill only, with `bad-type` on it.
STATUS = MappingProxyType({"ok": "#7fcf9f", "warn": "#e7bf72", "bad": "#c02040", "bad-type": "#f8f0e0"})
SOURCE_INK = MappingProxyType({"hato": "#f8a890", "youtube": "#ff6f7a", "anilist": "#5ec6ff"})
# The gems, by kind (brief §3: ✅ kinds, ✍ hexes; gem-kit.js `GEM`): base, light, edge. Sapphire = shows, emerald =
# reading (and Anki's *connected* light), ruby = videos.
GEM = MappingProxyType({
    "sapphire": ("#1d4fae", "#4b8ff0", "#d6e7ff"),
    "emerald": ("#13744f", "#3cc48f", "#d8f8ea"),
    "ruby": ("#98203a", "#e2546f", "#ffdbe3"),
})
KIND_GEM = MappingProxyType({"shows": "sapphire", "reading": "emerald", "videos": "ruby"})
# The stones' fixed colours (gem-kit.js, flat: rockFaces, rawFaces, GRAPHITE, crystalStops, the unlinked trillion):
# what a stone is made of whatever its kind (W3.1a, `app/qt/stones.py`).
STONE = MappingProxyType({
    "black": "#000000", "white": "#ffffff",
    "rock-dark": "#22262c", "rock-lit": "#6a717c", "rock-rim": "#181b20",
    "raw-pale": "#8a94a3", "raw-shade": "#2a2f37",
    "graphite-0": "#14171b", "graphite-1": "#262a31", "graphite-2": "#434a54", "graphite-3": "#6d7581",
    "ore-rim": "#0c0f13",
    "crystal-0": "#0a0e14", "crystal-1": "#1e2530", "crystal-2": "#3e4858",
    "unlinked-base": "#2a313c", "unlinked-light": "#56627a", "unlinked-edge": "#9aa6b8",
})
# Hard-coded, not tokens: the same whatever the theme. Tooltips and toasts are overlays: slate navy, solid (brief §4).
FIXED = MappingProxyType({
    "tooltip": ROOM["overlay"], "toast": ROOM["overlay"], "scrim": ROOM["dim"], "on-accent": "#0b1018",
    "cover-badge": "#000000b0", "cover-badge-hi": "#000000b8", "cover-badge-border": "#ffffff40",
    "watched-track": "#00000070", "cover-ink": "#f4efe6", "mark-shadow": "#1e83b940", "page": "#070a0f",
    "cover-ground": "#04060a",
})

# The mixes the painters read: name -> (where it comes from, expression). An expression is a colour (a token, room or
# fixed name, `#hex` or "transparent") or ("mix", a, pa, b, pb) — `pb` None when CSS leaves it out. The old mock's
# mixes for parts the redesign drops are retired with the themes (git history keeps them).
# **Invented here, not the brief's values:** frame-edge, groove, groove-lip, cut-wall-top, cut-wall-low and well-lit
# are Mado's flat stand-ins for what the brief describes in words (rule 3's edge, rule 4's groove, §5's lit lower wall
# of a hole, the well under the hand); the reference draws them with shadows and lighting a flat window can't. Each is
# one line to change once Sonic (or his design tools) names a value.
MIXES = {
    # the frame meets the list along its edge (top and bottom only); a divider is a groove: 1 px dark, then a lit lip
    "frame-edge": ("brief §4 rule 3", ("mix", "frame", 55, "#000000", None)),
    "groove": ("brief §4 rule 4", ("mix", "content", 45, "#000000", None)),
    "groove-lip": ("brief §4 rule 4", ("mix", "line-hi", 45, "transparent", None)),
    # a cut (New arrivals, search, a bucket's well): the top wall in shadow, the lower wall lit (brief §5: in a hole)
    "cut-wall-top": ("brief §5", ("mix", "cut", 40, "#000000", None)),
    "cut-wall-low": ("brief §5", ("mix", "line-hi", 55, "frame", None)),
    "well-lit": ("brief §2, the buckets", ("mix", "ok", 12, "cut", None)),
    # a row under the hand: the reference's ground for it, as written (list-r14m :663); W3.1a adds the lift
    "row-hover": ("list-r14m :663", "#0d121a"),
    # Generate (W3.1a moves it into the level pop) and its stale state
    "generate-hover": ("mock.html :228", ("mix", "raised", 70, "accent", 12)),       # sums to 82 %
    "generate-stale-glow": ("mock.html :230", ("mix", "accent", 70, "transparent", None)),
    # the statuses (glyph + label; W3.1a makes them icons and stones)
    "status-in": ("mock.html :321", ("mix", "ok", 12, "transparent", None)),
    "status-part-ring": ("mock.html :322", ("mix", "ok", 40, "transparent", None)),
    "status-mining": ("mock.html :323", ("mix", "accent", 12, "transparent", None)),
    "status-nomedia-border": ("mock.html :334", ("mix", "warn", 55, "transparent", None)),
    # the top-20 line (W3.1a: a groove, really subtle) and the watched chips (W3.1a: the string's stones)
    "top20-line": ("mock.html :348", ("mix", "accent", 38, "line", None)),
    "watched-chip-fill": ("mock.html :375", ("mix", "accent", 20, "bg", None)),
    "watched-chip-border": ("mock.html :375", ("mix", "accent", 45, "line", None)),
    "needs-row-border": ("mock.html :548", ("mix", "line", 60, "transparent", None)),
}

# Opaque versions of the alpha mixes, laid on the ground they show on.
OVER = {"status-in": "surface", "status-mining": "surface"}


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
    if expr in ROOM:
        return ROOM[expr]
    if expr in STATUS:
        return STATUS[expr]
    return FIXED[expr]


def _build(theme):
    own = dict(_OWN[theme])
    colours = dict(own)
    colours.update(ROOM)
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
# Windows' families first; then macOS's and Linux's (05 §5.11: other systems, 3.1–3.2), which Windows skips unread.
FAMILY_BY_LANGUAGE = {"ja": ("Yu Gothic UI", "Yu Gothic", "Meiryo", "Hiragino Sans", "Noto Sans CJK JP"),
                      "zh-hans": ("Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC"),
                      "zh-hant": ("Microsoft JhengHei UI", "PingFang TC", "Noto Sans CJK TC")}
MONO = ("Consolas", "Cascadia Mono")
# For a file's path: never a Japanese family first — Yu Gothic UI and Meiryo draw the backslash as ¥ (a path reads
# `E:¥Shows¥…`; found by the wizard's draft, 2026-10-14). Segoe UI first, then the language's own family (a Japanese
# or Chinese folder name still takes its shapes), whatever family the rest of the window takes (the brief's Yu Gothic UI,
# W3.1a, which wires every path through `path_font_families`).
PATH_FAMILY = ("Segoe UI",)


def path_font_families(language="ja", script=None):
    """The families a path is drawn in: Segoe UI first (its backslash), then the language's own."""
    return PATH_FAMILY + font_families(language, script)[1:]
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
    "body": (13, 550), "button": (13, 550), "button-sm": (12, 550), "menu-item": (13, 550), "input": (12.5, 400), "hero-sub": (12.5, 400),
    "segmented": (12.5, 400), "select": (12.5, 400), "number-field": (12.5, 400), "row-sub": (12, 400),
    "diff": (12, 400), "footer": (12, 400), "tooltip": (12, 500), "status-pill": (11.5, 600), "chip": (11.5, 600),
    "eyebrow": (11, 700), "badge": (11, 700), "mini": (11, 700), "group-label": (10.5, 700),
    "source-chip": (10.5, 650), "key-hint": (10.5, 700), "new-per-episode": (10, 600),
}
LETTER_SPACING_EM = {"eyebrow": 0.12, "group-label": 0.1}
# --- W2.2: the type roles the mock draws that A4 didn't name (the anatomy digest, tracks/window/work/w22) ---------- #
TYPE.update({
    "subline": (11.5, 400), "position": (12, 400), "tab-count": (12, 400), "needs-file": (11.5, 400), "month": (11.5, 700), "goal-label": (13, 650),
    "disk-mark": (11, 650), "episode-label": (13, 400), "date": (12, 400), "cover-title": (7, 700),
    "cover-title-large": (12, 700),
})
LETTER_SPACING_EM.update({"month": 0.1, "cover-title": 0.06, "cover-title-large": 0.06})
# --- end W2.2 -------------------------------------------------------------------------------------------------------- #


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
    "status-pill": 24, "search-w": 230, "search-w-narrow": 172, "search-h": 32, "generate": 34, "footer": 39,
    "goal-strip": 46, "bucket": 58, "tray": 452, "search-results": 470, "side-panel": 360, "side-panel-narrow": 316,
    "side-rail": 330, "settings-nav": 228, "settings-card-max": 820, "settings-search-max": 520,
    "settings-search-h": 38, "menu-min": 264, "pop": 390, "dialog": 560, "tooltip-max": 300, "switch-w": 36,
    "switch-h": 20, "arrival-number": 56, "icon-square": 26, "title-to-number": 28, "channel-cap": 130,
    "wizard-steps": 244,
}
# the footer: 39 px + the 1 px line above it = the Windows taskbar's 40 px at 100 % (Windows' scale only; G2.3 C3)
FIXED_SIZES = frozenset({"hero-cover-w", "hero-cover-h", "switch-w", "switch-h", "footer"})
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
    "bar-dot": (0, 0, 10, 0, "accent"),          # the bottom bar's dot glows (the mock's `.foot .dot`)
}


def size(name, text_size=DEFAULT_TEXT_SIZE):
    """A size in px at a text size (fixed sizes never scale)."""
    px = SIZES[name]
    return px if name in FIXED_SIZES else round(px * text_factor(text_size), 2)


# --- Motion (05 §5.5; A4 Motion) ------------------------------------------------------------------------------------ #
EASE = (0.2, 0.7, 0.3, 1.0)              # cubic-bezier(.2, .7, .3, 1)
FAST = 120                               # ms: hovers, the switch's track colour
SLOW = 260                               # ms
EASE_IN_OUT = (0.42, 0.0, 0.58, 1.0)     # CSS `ease-in-out`: the bar's pulse (the mock's `pulse 1.4s ease-in-out`)
MOTION = MappingProxyType({
    "gap-slide": 190, "ghost-glide": 160, "ghost-removed": 150, "tray-fade": 140, "overlay-pop": 140,
    "tray-pop": 160, "side-panel": 260, "side-panel-shift": 24, "sheet": 260, "buckets": 260, "buckets-rise": 40,
    "dialog-scrim": 160, "dialog-card": 180, "toast-rise": 260, "toast-rise-px": 12, "toast-shown": 6500,
    "toast-shown-anki": 12000, "row-flash": 1600, "switch-knob": 260, "chevron": 260, "hover": FAST,
    "mining-spin": 1200, "footer-pulse": 1400, "generate-bar": 300, "tooltip-delay": 380, "tooltip-again": 60,
    "tooltip-again-within": 500, "fit-debounce": 80, "drag-start-px": 6, "click-swallow-after-drag": 50,
    "auto-scroll-px-per-frame": 12, "auto-scroll-edge": 50, "auto-scroll-dock": 48,
    # distances (px) the overlays travel as they open (M2.1; the mock's `pop` −4 px, `dlgin` +10 px)
    "pop-shift": 4, "dialog-rise": 10, "toast-bottom": 48,
})
# Springs on the one clock (W3.1a §3; the reference's touches, ref-extract §8): a preset is (ω rad/s, ζ). ζ 1 is
# critically damped (home without passing it), under 1 overshoots and settles. Distances in px.
SPRINGS = MappingProxyType({
    "hover-lift": (13.5, 1.0),           # a row on the ground lifts under the hand (97 % at ≈ .4 s)
    "hover-release": (13.5, 0.5),        # ... and falls with ζ .5 until it passes rest, then critically home from below
    "hover-neighbour": (13.5, 1.0),      # its neighbours ease apart after it
    "inset": (24.0, 1.0),                # fall into place (r5Inset): down to `inset-px` at 1/ω ≈ 42 ms, then home
    "drag-part": (22.0, 1.0),            # neighbours parting under a drag: the reference's own parting (an arrival's
                                         # covers, crit ω 22) — 92 % by the old tween's 190 ms, and never past the slot
    "slot": (28.3, 0.5),                 # a well's slot opening under the hand (2π·4.5)
    "vein-lead": (34.0, 1.0),            # the tab vein's leading end
    "vein-tail": (22.0, 1.0),            # ... and its trailing end
    "press": (36.0, 1.0),                # a press going down
    "release": (26.0, 1.0),              # ... and coming back
    "lift-px": 2, "neighbour-px": 1.5, "inset-px": 1.5,
    "sub-step-ms": 6,                    # the physics' step: never longer, whatever the frame interval
    "catch-up-ms": 1000,                 # a stalled clock (a sleep, a long step) catches up at most this much
    "rest-x": 0.005, "rest-v": 0.05,     # at rest: |x − target| and |v| (per s) under these, then it snaps home
})


# --- W2.2: the generated cover (the fallback and the offline look, 05 §5.6; mock.html `pieceCover`) --------------- #
def _hsl(h, s_, l_):
    """CSS hsl() -> `#rrggbb` (h in degrees, s and l 0–1)."""
    h = (h % 360) / 360.0
    def f(n):
        k = (n + h * 12) % 12
        a = s_ * min(l_, 1 - l_)
        return 255.0 * (l_ - a * max(-1.0, min(k - 3, 9 - k, 1.0)))
    return hex_of(f(0), f(8), f(4))


def title_hue(title):
    """The mock's hue for a title with no cover: (h·31 + code point) mod 360 over its characters."""
    h = 0
    for ch in title or "":
        h = (h * 31 + ord(ch)) % 360
    return h


def generated_cover(title):
    """(top, bottom) of a title's painted cover: a 160° gradient from hsl(h 45% 30%) to hsl(h+40 40% 16%)."""
    h = title_hue(title)
    return _hsl(h, 0.45, 0.30), _hsl(h + 40, 0.40, 0.16)
# --- end W2.2 -------------------------------------------------------------------------------------------------------- #


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

"""The help cards' catalog (the help cards' spec §4, §6.1; HG-1…HG-5): one card per area of the window, opened by its
**?** (and by *Why?*, and by the strip's ?), and the automation tour (item 11, HG-4) — the automatic features' cards
in a row. Qt-free: the words live in the window's strings table (`app/qt/strings.py`, `HELP_CARDS`), the files beside
the app (`app/assets/help/`).

- **A card** — `Card(id, area, settings, try_it, clip, stills)`: `settings` the Settings target its *Open its
  settings* reveals (`SettingsPage.reveal`'s: a row id or a section id), `try_it` the press its *Try it* runs (one that
  exists already, real, small, and undoable or read-only: §6.5), `clip` whether it has a moving clip (else stills).
  A card's files are `<id>.webp` (the clip), `<id>-poster.png` (its *after*, shown first and under Reduced motion) and
  `<id>-<n>.png` (the stills), listed with their sha256s in `clips.json` (the recorder's, WP4). A card whose files
  aren't there yet opens with its words alone — never an error.
- **A card whose part is missing doesn't show** (§4.1): `available(card_id, has_module)` — without the Junban module,
  `junban` and `backfill` leave *All help* and the tour, and their ?s aren't made. One rule, for *All help*, the tour
  and the window's `help_mark()`.
- **The screen cards** (HC-4): the main ? opens the card of the screen in view (`SCREEN_CARD`); a screen with none
  opens *All help*.
- **The tour** (item 11; §4.3): `TOUR`'s cards that are `available`, one after another, *n of N*; nothing remembered.
"""
import functools
import json
import os
from collections import namedtuple

Card = namedtuple("Card", "id area settings try_it clip stills", defaults=(None, None, True, 0))

# The 17 cards (§4.1), in *All help*'s order. `settings`: a `settings_catalog` row or section id; `try_it`: the
# window's press (`TRY_IT`).
CARDS = (
    Card("current", "screens", settings="mine_line"),
    Card("circles", "screens", clip=False, stills=9),
    Card("needs", "screens"),
    Card("finished", "screens", settings="finish_cards"),
    Card("stones", "library", settings="keep_watched"),
    Card("moving", "library"),
    Card("arrivals", "library", settings="placing_rules"),
    Card("groups", "library"),
    Card("level", "words", settings="level"),
    Card("journey", "words"),
    Card("known", "words", settings="anki_sync_auto", try_it="sync_known"),
    Card("cards", "anki", settings="connect_enabled", try_it="mine_top"),
    Card("junban", "anki", settings="enable_junban", try_it="junban"),
    Card("backfill", "anki", settings="backfill_patterns", clip=False, stills=1),
    Card("generate", "automatic", settings="automation", try_it="update_journey"),
    Card("piyo", "more", settings="practice_ai", clip=False, stills=1),
    Card("automation", "automatic", settings="automation", clip=False, stills=1),
)
BY_ID = {c.id: c for c in CARDS}
AREAS = ("screens", "library", "words", "anki", "automatic", "more")   # *All help*'s headings, in order

# The window's presses a *Try it* runs (§6.5): each one the window already has
TRY_IT = ("sync_known", "mine_top", "junban", "update_journey")

# The main ?'s card for the screen in view (HC-4); Settings' own section card, where its section has one (`SECTION`)
SCREEN_CARD = {"current": "current", "finished": "finished", "needs": "needs", "settings": "automation"}
SECTION_CARD = {"known": "known", "junban": "junban", "backfill": "backfill", "level": "level", "arrivals": "arrivals",
                "connect": "piyo", "anki": "cards"}

# The tour (item 11), in this order; `arrivals` and `stones` stand for their automatic part (the placing rules, what
# the last Done does)
TOUR = ("automation", "cards", "known", "generate", "junban", "backfill", "arrivals", "stones")

# The cards that need an optional module (§4.1, S10): absent → not in *All help* or the tour, and no ? for them
NEEDS_MODULE = {"junban": "junban", "backfill": "junban"}

ASSETS = os.path.join("app", "assets", "help")
MANIFEST = "clips.json"


@functools.lru_cache(maxsize=None)
def module_present(name):
    """Whether optional module `name` is installed (`modules/<name>/`), never importing it — looked once a session (a
    module isn't installed while the window runs)."""
    try:
        import importlib.util
        return importlib.util.find_spec(f"modules.{name}") is not None
    except (ImportError, ValueError):
        return False


def available(card_id, has_module=None):
    """Whether card `card_id` shows (a known id whose module is there). `has_module(name)`: a test's stand-in."""
    if card_id not in BY_ID:
        return False
    need = NEEDS_MODULE.get(card_id)
    return need is None or bool((has_module or module_present)(need))


def all_help(has_module=None):
    """*All help*: [(area, [card id, …])] — the available cards, by area, in order."""
    out = []
    for area in AREAS:
        ids = [c.id for c in CARDS if c.area == area and available(c.id, has_module)]
        if ids:
            out.append((area, ids))
    return out


def tour(has_module=None):
    """The tour's cards that show, in order (*n of N* counts these)."""
    return tuple(c for c in TOUR if available(c, has_module))


def screen_card(screen, section=None):
    """The main ?'s card for `screen` (a tab: current · finished · needs · settings; `section`: Settings' section in
    view), or None (*All help*)."""
    if screen == "settings" and section in SECTION_CARD:
        return SECTION_CARD[section]
    return SCREEN_CARD.get(screen)


def folder():
    """The help files' folder (frozen or from source)."""
    from app.path_utils import get_resource
    return get_resource(ASSETS)


def files(card_id, base=None):
    """{"clip": path or None, "poster": path or None, "stills": [path, …]} — only the files that are there."""
    base = base or folder()
    card = BY_ID.get(card_id)

    def there(name):
        path = os.path.join(base, name)
        return path if os.path.isfile(path) else None
    out = {"clip": None, "poster": None, "stills": []}
    if card is None:
        return out
    if card.clip:
        out["clip"] = there(f"{card_id}.webp")
        out["poster"] = there(f"{card_id}-poster.png")
    out["stills"] = [p for p in (there(f"{card_id}-{n}.png") for n in range(1, (card.stills or 0) + 1)) if p]
    return out


def manifest(base=None):
    """`clips.json` as a dict ({} when it isn't there or can't be read)."""
    try:
        with open(os.path.join(base or folder(), MANIFEST), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

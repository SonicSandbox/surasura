"""New arrivals' placing rules (P2.1 row 2.1.6; ✅ Q2-3): an arrival waits in *New arrivals* unless a rule the user
turned on places it. Each rule is a setting, off by default (RD-S16: arrivals never place themselves without a setting
the user turned on), and they exist only where New arrivals do (3.0: the store's `arrivals_on`). Through 2.x hato's
drops keep landing at the top of NOW (✅ Q4-11) and nothing here runs.

One rule places an item, never two: the first that applies wins.
1. **Continuing shows** (`arrivals_continuing_shows`, HC-N6; ✅ P2.1-2: off by default, Sonic turns it on): the next
   episode of a show in Current goes right after its previous one there (before its next one when only later
   episodes are in Current). A show whose episodes are all in Finished or 6+ Months: the new one goes to the top of
   Current (✅ Q4-9). The show is the one the pairing record names (`show.title`, `show.season`; K81), never the folder.
2. **Straight into Current** (`arrivals_straight_sources`: the programs whose drops skip New arrivals, e.g. "hato"):
   the top of Current.

Each placement is logged under the rule's name (`rule:<name>`), so the placement log says what placed it.
"""
from app.connect import library

CONTINUING = "continuing-shows"
STRAIGHT = "straight-into-current"


def _show(record):
    """(title, season, episode) the record names, or None (a re-sync's record carries no show)."""
    show = (record or {}).get("show")
    if not isinstance(show, dict):
        return None
    title, episode = show.get("title"), show.get("episode")
    if not isinstance(title, str) or not title.strip() or isinstance(episode, bool) \
            or not isinstance(episode, (int, float)):
        return None
    return title.strip().casefold(), show.get("season"), episode


def _sources(settings):
    value = settings.get("arrivals_straight_sources") or []
    if isinstance(value, str):
        value = [value]
    return {str(v).strip().casefold() for v in value if str(v).strip()}


def _continuing(store, item_id, record):
    """Where the continuing-shows rule puts the item: (tier, before_id, after_id), or None when the library holds no
    other episode of its show."""
    mine = _show(record)
    if mine is None:
        return None
    title, season, episode = mine
    others = []         # (episode, item_id, tier)
    for other_id, records in library.pairings(store).items():
        if other_id == item_id:
            continue
        for rec in records:
            show = _show(rec)
            if show and show[0] == title and show[1] == season and show[2] != episode:
                others.append((show[2], other_id))
                break
    if not others:
        return None
    current = []
    for ep, other_id in others:
        item = store.item(other_id)
        if item is None:
            continue
        if item["tier"] in ("now", "soon"):
            current.append((ep, other_id, item["tier"]))
    if not current:
        return ("now", None, None)                  # Q4-9: a finished show's new episode, the top of Current
    earlier = [c for c in current if c[0] < episode]
    if earlier:
        _ep, prev_id, tier = max(earlier)
        return (tier, None, prev_id)
    _ep, next_id, tier = min(current)
    return (tier, next_id, None)


def apply(store, item_id, record, settings):
    """Place an arrival by the first rule that applies -> the rule's name, or None (it waits in New arrivals)."""
    if not library.three_oh(store):
        return None
    item = store.item(item_id)
    if item is None or item["tier"] != "arrivals":
        return None
    if settings.get("arrivals_continuing_shows"):
        where = _continuing(store, item_id, record)
        if where is not None:
            tier, before_id, after_id = where
            library.place(store, item_id, tier, before_id=before_id, after_id=after_id, source=f"rule:{CONTINUING}")
            return CONTINUING
    producer = str((record or {}).get("producer") or "").strip().casefold()
    if producer and producer in _sources(settings):
        library.place(store, item_id, "now", source=f"rule:{STRAIGHT}")
        return STRAIGHT
    return None

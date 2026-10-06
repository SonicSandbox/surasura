"""New arrivals' placing rules (P2.1 row 2.1.6; ✅ Q2-3, D30): an arrival waits in *New arrivals* unless a rule the
user turned on places it. The rules are one setting, `placing_rules` = {source: target}, empty by default (RD-S16:
arrivals never place themselves without a setting the user turned on), and they exist only where New arrivals do (3.0:
the store's `arrivals_on`). Through 2.x hato's drops keep landing at the top of NOW (✅ Q4-11) and nothing here runs.
The shape is the store's (L2.2 05 §5.12, agreed with Kura): from L3.1 `register` reads it itself and this step goes.

- **Sources:** the record's `producer` (`hato`, any other program's name); `<producer>:<channel id>` for a record that
  names its channel (`channel_id`), which wins over the producer's own line (`youtube:<id>` over `youtube`).
- **Targets:** `wait` (the default) · `top` (the top of Current) · `after-show` (HC-N6, ✅ P2.1-2: the next episode of a
  show in Current right after its previous one there, before its next one when only later episodes are; a show whose
  other episodes are all in Finished or 6+ Months → the top of Current, ✅ Q4-9; a show with episodes still waiting and
  none in Current, or none at all → it waits) · `soon` / `goal` (the top of Soon / 6+ Months) · `finished`.

One rule places an item, never two. Its placement is the user's own action (D30): logged `by` the source, explicit.
"""
from app.connect import library

TARGETS = ("wait", "top", "after-show", "soon", "goal", "finished")
SET_ASIDE = ("graduated", "goal")       # Finished, 6+ Months: a show there is one the user finished or put off


def _season(value):
    """A season as a number: none named is the first (09 §1: `season` int | null); "2" is 2."""
    if value is None:
        return 1
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


def _show(record):
    """(title, season, episode) the record names, or None (a re-sync's record carries no show)."""
    show = (record or {}).get("show")
    if not isinstance(show, dict):
        return None
    title, episode = show.get("title"), show.get("episode")
    if not isinstance(title, str) or not title.strip() or isinstance(episode, bool) \
            or not isinstance(episode, (int, float)):
        return None
    return title.strip().casefold(), _season(show.get("season")), episode


def rule_for(record, settings):
    """(source, target) of the rule for this record's arrival, or None: wait."""
    rules = settings.get("placing_rules")
    if not isinstance(rules, dict):
        return None
    producer = str((record or {}).get("producer") or "").strip()
    channel = (record or {}).get("channel_id")
    for source in ([f"{producer}:{channel}"] if channel else []) + [producer]:
        target = rules.get(source)
        if target in TARGETS and target != "wait":
            return source, target
        if target == "wait":
            return None
    return None


def _after_show(store, item_id, record):
    """Where `after-show` puts the item: (tier, before_id, after_id), or None when it waits."""
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
                item = store.item(other_id)
                if item is not None:
                    others.append((show[2], other_id, item["tier"]))
                break
    current = [o for o in others if o[2] in ("now", "soon")]
    if not current:
        if others and all(o[2] in SET_ASIDE for o in others):
            return ("now", None, None)              # Q4-9: a finished show's new episode, the top of Current
        return None
    earlier = [c for c in current if c[0] < episode]
    if earlier:
        _ep, prev_id, tier = max(earlier)
        return (tier, None, prev_id)
    _ep, next_id, tier = min(current)
    return (tier, next_id, None)


def apply(store, item_id, record, settings):
    """Place an arrival by its source's rule -> the target it was placed by, or None (it waits in New arrivals)."""
    if not library.three_oh(store):
        return None
    item = store.item(item_id)
    if item is None or item["tier"] != "arrivals":
        return None
    found = rule_for(record, settings)
    if found is None:
        return None
    source, target = found
    if target == "finished":
        library.finish(store, item_id, source=source, explicit=1)
        return target
    if target == "after-show":
        where = _after_show(store, item_id, record)
        if where is None:
            return None
    else:
        where = ({"top": "now"}.get(target, target), None, None)
    tier, before_id, after_id = where
    library.place(store, item_id, tier, before_id=before_id, after_id=after_id, source=source, explicit=1)
    return target

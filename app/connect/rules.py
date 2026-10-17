"""New arrivals' placing rules (P2.1 row 2.1.6; ✅ Q2-3, D30): an arrival waits in *New arrivals* unless a rule the
user turned on places it. The rules are one setting, `placing_rules` = {source: target}, `after-show` for hato and the
folders Surasura reads by default (Decision 1, lean: SRC-2's "if the show exists, it should just pair"; empty, every
arrival waits), and they exist only where New arrivals do (3.0: the store's `arrivals_on`). Through 2.x hato's drops
keep landing at the top of NOW (✅ Q4-11) and nothing here runs. The shape is the store's (L2.2 05 §5.12, agreed
with Kura): from L3.1 `register` reads it itself and this step goes.

- **Sources:** the record's `producer` (`hato`, any other program's name); `<producer>:<channel id>` for a record that
  names its channel (`channel_id`), which wins over the producer's own line (`youtube:<id>` over `youtube`).
- **Targets:** `wait` (a source with no line too) · `top` (the top of Current) · `after-show` (HC-N6, ✅ P2.1-2: the
  next episode of a show in Current right after its previous one there, before its next one when only later episodes
  are; a show whose other episodes are all in Finished or 6+ Months → the top of Current, ✅ Q4-9; a show with
  episodes still waiting and none in Current, or none at all → it waits; the store's `place(where="after-show")`, by
  the item's title) · `soon` / `goal` (the top of Soon / 6+ Months) · `finished`.

One rule places an item, never two. Its placement is the user's own action (D30): logged `by` the source, explicit.
"""
from app.connect import library

TARGETS = ("wait", "top", "after-show", "soon", "goal", "finished")


def rule_for(record, settings):
    """(source, target) of the rule for this record's arrival, or None: wait."""
    rules = settings.get("placing_rules")
    if not isinstance(rules, dict):
        return None
    producer = str((record or {}).get("producer") or "hato").strip()   # no producer: hato's (as the store reads it)
    channel = (record or {}).get("channel_id")
    for source in ([f"{producer}:{channel}"] if channel else []) + [producer]:
        target = rules.get(source)
        if target in TARGETS and target != "wait":
            return source, target
        if target == "wait":
            return None
    return None


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
    if target == "after-show":          # the store's own rule, as `register` and a folder's take-in place (Decision 1)
        return target if store.place([item_id], "after-show", by=source, explicit=1) is not None else None
    library.place(store, item_id, {"top": "now"}.get(target, target), source=source, explicit=1)
    return target

"""New arrivals' placing rules (P2.1 row 2.1.6; ✅ Q2-3, D30): an arrival waits in *New arrivals* unless a rule the
user turned on places it. The rules are one setting, `placing_rules` = {source: target}, `after-show` for hato and the
folders Surasura reads by default (Decision 1, lean: SRC-2's "if the show exists, it should just pair"), merged per
key (a source the file doesn't name keeps its default; only an explicit `wait` makes it wait), and they exist only
where New arrivals do (3.0: the store's `arrivals_on`). Through 2.x hato's drops keep landing at the top of NOW (✅
Q4-11) and nothing here runs. The shape is the store's (L2.2 05 §5.12, agreed
with Kura): from L3.1 `register` reads it itself and this step goes.

- **Sources:** the record's `producer` (`hato`, any other program's name); `<producer>:<channel id>` for a record that
  names its channel (`channel_id`), which wins over the producer's own line (`youtube:<id>` over `youtube`).
- **Targets:** `wait` (a source with no line too) · `top` (the top of Current) · `after-show` (HC-N6, ✅ P2.1-2: the
  next episode of a show in Current right after its previous one there, before its next one when only later episodes
  are; a show whose other episodes are all in Finished or 6+ Months → the top of Current, ✅ Q4-9; a show with
  episodes still waiting and none in Current, or none at all → it waits; the store's `place(where="after-show")`, by
  the item's title) · `soon` / `goal` (the top of Soon / 6+ Months) · `finished`. Kura-SO (Sonic 2026-11-19): `top`,
  `soon` and `goal` never put a new episode ahead of an earlier one of its show there — it joins the show in episode
  order (`top` / `soon` in Current, `goal` in 6+ Months) — and an item with no episode order goes after what is there
  (the end of Soon / 6+ Months; `top`: after its own title's rows in Current) — the store's `place_by_rule`.

One rule places an item, never two. Its placement is the user's own action (D30): logged `by` the source, explicit.
"""
from app.connect import library

TARGETS = ("wait", "top", "after-show", "soon", "goal", "finished")


def rule_for(record, settings):
    """(source, target) of the rule for this record's arrival, or None: wait. The rules merged per key
    (`settings_manager.placing_rules`): a source `settings` doesn't name keeps its default."""
    from app.settings_manager import placing_rules
    rules = placing_rules((settings or {}).get("placing_rules"))
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
    store.place_by_rule(item_id, target, record, source)    # as `register` places one: a new episode joins its
    return target                                           # show in episode order there (Kura-SO)


HELD_WAIT_S = 5.0       # how long the list's own write waits for a library another program is writing


def place_held(settings, languages=("ja", "zh")):
    """Kantan-G: New arrivals resumed — the hato drops its pause kept waiting (`connect_verbs.register_record` →
    `Store.hold_drops`) placed by their rules now, oldest first, as hato's register would have placed them; one the
    learner placed meanwhile, or whose rule is now *wait*, stays where it is (`apply`). Then Connect kicked when the
    placements gave it something to read. A worker's call -> {language: the drops placed}. Each drop is forgotten
    only once settled (`Store.forget_drops`): a library busy or absent, or one that fails part-way, keeps the rest for
    the next resume."""
    placed = {}
    for lang in languages:
        work = False
        try:
            store = library.open_store(lang, role="window")
            if store is None:
                continue
            with store:
                held = store.held_drops()
                if not held:
                    continue
                done, settled = [], []
                try:
                    for drop in held:
                        try:
                            if apply(store, drop["id"], drop, settings):
                                done.append(drop["id"])
                        except ValueError:          # its anchor moved meanwhile: it waits there, as an unpaused
                            pass                    # register's does for hato's retry
                        settled.append(drop["id"])
                finally:
                    _forget(store, settled)         # (a busy library mid-way: what wasn't tried stays held)
                placed[lang] = done
                from app.connect import inbox
                work = bool(done) and inbox.pending(store)
        except Exception as e:                      # never the window's fault: the drops wait in New arrivals
            print(f"New arrivals ({lang}): hato's waiting drops weren't placed: {e!r}")
        if work:
            try:
                from app.connect import kick
                kick.kick(settings)
            except Exception as e:
                print(f"Connect wasn't started after New arrivals resumed: {e!r}")
    return placed


def _forget(store, ids):
    """`Store.forget_drops`, retried while another program writes the library for up to HELD_WAIT_S; still busy, the
    drops stay held (the next resume finds each where it is now: one placed already is skipped by `apply`)."""
    import time
    from app import library_store
    deadline = time.monotonic() + HELD_WAIT_S
    while ids:
        try:
            return store.forget_drops(ids)
        except library_store.StoreBusy:
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.1)

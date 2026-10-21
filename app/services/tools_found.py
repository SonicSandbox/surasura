"""Which of the other tools are here — one answer for Settings, *Needs you*, Anki Miner's card in Connections and the
setup wizard (laptop fixes row 13; its review's B2-7 / IK2-3: each had decided it on its own).

- `tools_found(settings)` -> `Found(hato, miner)`: `hato` — its usable entry in the shared tools folder
  (`tools_entry.read`, as its Connections row reads it); `miner` — `MISSING` or `INSTALLED` (`anki_miner.find`: the
  path chosen, else where its installer puts it). Two file looks: a worker's call, never the window's thread. A look
  that fails counts its tool absent (its rows stay hidden, nothing is written).
- `hato_version()`: hato's version from that entry ("" when it names none), or None: not here.
- `miner_level(state)`: a fuller look's state — the wizard's (`anki_miner_setup.look`: missing · too-old · needs-setup
  · ready) or the card's (`settings_values.card_state`: missing · setup · ready) — on the same scale: `MISSING`,
  `INSTALLED` (too old, or its own setup not finished) or `READY`.
- `make_cards_shown(level, on=False)`: **the** answer to "when is *Make cards for me* offered" — once Anki Miner is
  installed (any level above `MISSING`: what Settings and *Needs you* can know without asking Anki or running Anki
  Miner; what still needs doing is said beside it — the wizard's fix line, the card's steps, Connect's own reason), or
  while it is on already (M3: the switch is the way off; then, off, it collapses to the "needs Anki Miner" line).

Qt-free, light: the standard library and the two readers named above.
"""
from collections import namedtuple

MISSING, INSTALLED, READY = "missing", "installed", "ready"
_LEVEL = {"missing": MISSING, "ready": READY}            # every other state of a look: installed, not ready yet

Found = namedtuple("Found", "hato miner")


def hato_version():
    """hato's version from its entry in the shared tools folder ("" when it names none), or None: not installed."""
    from app import tools_entry
    entry = tools_entry.read("hato")
    if entry is None:
        return None
    version = entry.get("version")
    return str(version) if isinstance(version, (str, int, float)) and not isinstance(version, bool) else ""


def tools_found(settings, log=print):
    """(A worker.) -> Found(hato: bool, miner: MISSING | INSTALLED). `log(text)`: a look that failed, said once."""
    hato = False
    try:
        hato = hato_version() is not None
    except Exception as e:
        log(f"looking for hato: {e}")
    miner = MISSING
    try:
        from app.connect import anki_miner
        if anki_miner.find(settings or {}):
            miner = INSTALLED
    except Exception as e:
        log(f"looking for Anki Miner: {e}")
    return Found(hato=hato, miner=miner)


def miner_level(state):
    """A fuller look's Anki Miner state on the one scale (None: not looked yet -> MISSING)."""
    return _LEVEL.get(state, INSTALLED) if state else MISSING


def make_cards_shown(level, on=False):
    """Whether *Make cards for me* is offered: Anki Miner installed (or ready), or the switch on already (M3)."""
    return bool(on) or level in (INSTALLED, READY)

"""The freeze switch (W2.1; the window's spec 07 §7.1, 05 §5.10): tests and captures see every look at once.

With it on, nothing waits on a timer to look right: the tooltip bubble shows without its delay, and M2.1's animation
clock jumps every motion to its end. It is the harness's switch (`SURASURA_FREEZE_MOTION=1`, or `set_frozen(True)`),
never a user setting: reduced motion (Settings › App › *Motion*) is M2.1's and separate.
"""
import os

_forced = None


def frozen():
    """True while motion is frozen (the environment's switch, unless a caller set it)."""
    if _forced is not None:
        return _forced
    return os.environ.get("SURASURA_FREEZE_MOTION") == "1"


def set_frozen(value):
    """Force the switch on or off (None: back to the environment's)."""
    global _forced
    _forced = None if value is None else bool(value)

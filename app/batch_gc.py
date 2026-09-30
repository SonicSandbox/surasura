"""The cycle collector, paused while a batch run works.

A Generate, the background indexer and the sentence dictionary each build large tables that live until the run ends —
every word's counts and example sentences, the known words, the word tables — and make almost no reference cycles (a
few hundred small objects in a whole run). Python's cycle collector still walks all of those tables each time enough
new objects have piled up: dozens of times a run, about a quarter of an everyday Generate. Reference counting frees
memory as usual while it is paused, and the collector is back as it was once the run returns.
"""

import functools
import gc


def without_cycle_collection(run):
    """Decorate a batch run's entry point (the subprocess's main): the cycle collector is off while it runs."""
    @functools.wraps(run)
    def wrapper(*args, **kwargs):
        was_on = gc.isenabled()
        gc.disable()
        try:
            return run(*args, **kwargs)
        finally:
            if was_on:
                gc.enable()
    return wrapper

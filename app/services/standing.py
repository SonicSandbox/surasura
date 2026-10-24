"""Standing lines (round 8 row 54; the scope `row45-54-scope.md` §4, Sonic's Q3): a line that stays while its state
does gets a ✕ that hides it until that state changes. Qt-free; `app/qt/standing.py` paints the ✕.

Sonic: "I can't remove that line. it just sits there." The rule, one for every standing line: **✕ hides a line until
its state changes.** The lines: a source folder a look couldn't reach (the offline line), the bottom bar's failure,
the update chip, a page's read-only line. Lines that go by themselves (work running, a line just said) and the quiet
marks get none.

- **A line's key names what it reports** (`key(kind, …)`): `line:offline:<the folder's path_key>`,
  `line:failure:<its time>|<its words>`, `line:update:<version>|<state>`, `line:readonly:<reason>`. ✕ records the
  key; the line shows again when its state brings another key (a newer failure, another version or state, another
  reason), or when its trouble ended and came back (`Hidden.shows` with no state lets the kind's keys go).
- **The run lines** (failure, update, read-only) are this session's: `Hidden`, in memory — the status service's for
  the failure (`StatusService.dismiss_failure`: still listed in *Needs you*), the shell's for the other two. The next
  start shows them again; the update's lasting answer is *Skip this version*.
- **The offline line's** are kept across restarts in the *Needs you* seen file's `answered` list
  (`needs.seen_path`: local data, per language) and pruned by that file's rule, a key going with its trouble
  (`needs.prune(..., lines=)`): a folder a look reached again, or one no longer read. So a folder away stays quiet
  until it comes back, and asks again once it goes away again. *Keep waiting* is the same dismissal under its own
  name. Written and read on a worker (`keep`, `looked`), never the window's thread.
- **Never settings.json:** a dismissal is a state, not a choice.
"""
import os

PREFIX = "line:"
OFFLINE, FAILURE, UPDATE, READ_ONLY = "offline", "failure", "update", "readonly"


def key(kind, *parts):
    """A line's key: its kind and what it reports (`None` parts as empty)."""
    return f"{PREFIX}{kind}:" + "|".join("" if p is None else str(p) for p in parts)


def kind_of(line_key):
    """The kind a line's key is of, or None for a key that isn't a line's."""
    if not isinstance(line_key, str) or not line_key.startswith(PREFIX):
        return None
    kind, sep, _rest = line_key[len(PREFIX):].partition(":")
    return kind if sep else None


def offline_key(path):
    """A source folder's offline key: the store's one comparison key for its path (a case or slash apart is one)."""
    from app.library_store import path_key
    return key(OFFLINE, path_key(os.path.abspath(path)))


def failure_key(at, text):
    return key(FAILURE, at, text)


def update_key(version, state):
    return key(UPDATE, version, state)


def read_only_key(reason):
    return key(READ_ONLY, reason)


class Hidden:
    """The keys ✕ hid, for this session (memory only). One thread's: the window's, or the status service's lock."""

    def __init__(self, keys=()):
        self._keys = set(keys)

    def hide(self, *keys):
        """✕: these lines hidden -> how many were new."""
        new = {k for k in keys if k and k not in self._keys}
        self._keys |= new
        return len(new)

    def shows(self, line_key, kind):
        """Whether a line of `kind` whose state is `line_key` shows. No state (None: the line has nothing to say): its
        trouble ended, so the kind's keys go — the same state later shows again."""
        if line_key is None:
            self.only(kind, ())
            return False
        return line_key not in self._keys

    def hid(self, line_key):
        """Whether ✕ hid the line `line_key` — a read, nothing let go (a page's: the window says when its trouble
        ended, `only`)."""
        return line_key in self._keys

    def only(self, kind, keys):
        """Only `keys` of `kind` stay hidden (the rest of that kind went with their trouble) -> how many went."""
        keys = set(keys)
        gone = {k for k in self._keys if kind_of(k) == kind and k not in keys}
        self._keys -= gone
        return len(gone)

    def keys(self, kind=None):
        return frozenset(k for k in self._keys if kind is None or kind_of(k) == kind)


# --- the offline line: kept in the Needs-you seen file (a worker's calls: file reads and writes) -------------------- #
def not_back(sources):
    """The offline keys still to keep for a look's `sources` ({path, on, reachable}): each folder being read that no
    look has reached this run (away, or not looked at yet). A folder reached again, or no longer read, lets its go."""
    return {offline_key(r["path"]) for r in sources or ()
            if r.get("path") and r.get("on", True) and r.get("reachable") is not True}


def kept(language):
    """The offline lines hidden (✕ or *Keep waiting*), from the seen file -> frozenset of keys."""
    from app.services import needs
    return frozenset(k for k in needs.read_answered(language) if kind_of(k) == OFFLINE)


def keep(language, keys):
    """✕ / *Keep waiting* on the offline line: its folders' keys kept in the seen file -> how many were new."""
    from app.services import needs
    return needs.answer(language, [k for k in keys or () if kind_of(k) == OFFLINE])


def looked(language, summary):
    """A look's summary (the looks' worker): the seen file pruned by its sources, then `kept_lines` (the offline keys
    still hidden) added to a copy of it. A seen file that can't be read or written leaves the summary as it was."""
    if not isinstance(summary, dict) or "sources" not in summary:
        return summary
    from app.services import needs
    language = summary.get("language") or language
    try:
        needs.prune(language, None, lines=not_back(summary.get("sources")))
        return dict(summary, kept_lines=kept(language))
    except Exception as e:
        print(f"Standing lines: the offline line's answers weren't read: {e!r}")
        return summary

"""Whether a show is still airing, from AniList (3.0.1 item 5; the spec: the planning folder's
`tracks/books/work/airing/SPEC.md`, A1–A8 PROVISIONAL): a show in Current whose every episode is watched never finishes
by itself while AniList says it is still airing, or while AniList lists more episodes than its files reach
(`drag.when_done`). Qt-free, Tk-free, standard library only; the request itself is the covers' (`covers_online`).

**AniList only holds a show back** (A5): `holds` gives "airing" or "more", else None — and None leaves the files' dates
to decide, as 3.0 did. AniList's "finished" never finishes a show sooner (`view_rows.still_arriving` gets `airing=True`
or None, never False).

**What is sent** (CLAUDE.md §1, *Covers*): AniList ids only (`Q_AIRING`, `BATCH` a query), through the covers fetcher's
own `_post` — its throttle (one AniList budget, A3), its headers, its switch: nothing while `covers_download` is off
(AA-1), asked again before every request. Never a title search. Only for the ids the library reader hands over: shows in
Current with an id and at most one file left unwatched (`near_end`, A1), and only when their kept answer is due (`due`,
A2). A refused, failed or timed-out ask keeps the old answer and is asked again `RETRY_S` later (A3).

**The cache** (A4): `<local data>/airing_<lang>.json` — `{"v": 1, "shows": {"<id>": {"status", "episodes", "next_at",
"asked_at"}}}`, per install and per language, written whole (`.tmp`, then renamed); only the ids asked are touched; a
file that can't be read is empty. Kept answers are used while the switch is off; *Remove downloaded covers* clears them
(`Airing.clear`, A7). The reader reads it on its own thread, again only when the file moved (`Kept`).
"""
import json
import math
import os
import threading
import time

from app.services import view_rows

AIRING = ("RELEASING", "NOT_YET_RELEASED", "HIATUS")     # AniList's statuses that hold a show back
ENDED = ("FINISHED", "CANCELLED")
BATCH = 50                          # ids a query (AniList's page)
DAY_S = 24 * 3600                   # an airing show's answer is asked again after this …
AIRED_S = 3600                      # … or this long after its next episode's air time, whichever comes first
ENDED_S = 30 * DAY_S                # an ended show's (its episode count can still be corrected)
UNKNOWN_S = 7 * DAY_S               # no row for the id (deleted, merged), or a status AniList adds later
RETRY_S = 15 * 60                   # a failed ask (the covers' own `RETRY_S`)
REPLACE_TRIES, REPLACE_WAIT_S = 3, 0.05     # the cache's rename, while the reader may have it open (Windows)
WAIT_S = 10.0

Q_AIRING = ("query ($ids: [Int]) { Page(perPage: 50) { media(id_in: $ids) { id status episodes "
            "nextAiringEpisode { episode airingAt } } } }")


def airing_id(work):
    """A work's AniList id (A8): `anilist_id`, else an AniList cover's numeric `cover_ref` (a cover found by search, or
    one the learner picked from AniList), else None. Never searched for."""
    if not work:
        return None
    for value in (work.get("anilist_id"), work.get("cover_ref") if work.get("cover_source") == "anilist" else None):
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit() and value.isascii() and int(value) > 0:
            return int(value)
    return None


def _number(value):
    """A finite number, else None (a hand-edited `Infinity` or `NaN` is no count and no time)."""
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return value if ok else None


def holds(entry, episodes):
    """What AniList's kept answer `entry` says of a show whose files are `episodes` (A5): "airing" (still airing,
    whatever its files), "more" (AniList lists more episodes than its highest numbered file), or None — nothing that
    holds it back: the files' dates decide."""
    if not isinstance(entry, dict):
        return None
    if entry.get("status") in AIRING:
        return "airing"
    total = _number(entry.get("episodes"))
    if total is not None and view_rows.episodes_short(episodes, total):
        return "more"
    return None


def _answer(entry):
    """What an answer says, without when it was asked."""
    return {k: v for k, v in entry.items() if k != "asked_at"} if isinstance(entry, dict) else None


def due(entry, now):
    """Whether `entry` (a kept answer, or None) is asked again at `now` (seconds since the epoch; A2)."""
    if not isinstance(entry, dict):
        return True
    asked = _number(entry.get("asked_at"))
    if asked is None or asked > now:
        return True                                 # no time, or one ahead of the clock: nothing to trust
    status = entry.get("status")
    if status in AIRING:
        nxt = _number(entry.get("next_at"))
        return now - asked > DAY_S or (nxt is not None and asked < nxt + AIRED_S <= now)
    if status in ENDED:
        return now - asked > ENDED_S
    return now - asked > UNKNOWN_S


def near_end(rows, works):
    """The AniList ids of Current's titles near their end (A1): a row of one work with an id (`airing_id`) and at most
    one of its files (`view_rows.to_finish`'s) left unwatched — in the rows' order, each once. A group, or a row of
    no title, never."""
    out = []
    for r in rows:
        if getattr(r, "group", False) or r.work_id is None:
            continue
        eps = view_rows.to_finish(r.episodes)
        if not eps or sum(1 for e in eps if not e.watched) > 1:
            continue
        aid = airing_id(works.get(r.work_id))
        if aid is not None and aid not in out:
            out.append(aid)
    return out


def of_rows(rows, works, shows):
    """{work_id: kept answer} for Current's `rows` (the view's `airing`): what `drag.when_done` reads."""
    out = {}
    if not shows:
        return out
    for r in rows:
        if getattr(r, "group", False) or r.work_id is None:
            continue
        aid = airing_id(works.get(r.work_id))
        entry = shows.get(str(aid)) if aid is not None else None
        if isinstance(entry, dict):
            out[r.work_id] = entry
    return out


# --- the cache ------------------------------------------------------------------------------------------------------ #
def cache_path(language):
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), f"airing_{language}.json")


def read(path):
    """The kept answers {"<id>": entry} at `path`; {} when there is none or it can't be read."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    shows = data.get("shows") if isinstance(data, dict) and data.get("v") == 1 else None
    return {k: v for k, v in shows.items() if isinstance(v, dict)} if isinstance(shows, dict) else {}


def _write(path, shows):
    """`shows` to `path` whole (`.tmp`, then renamed). False when it couldn't be written."""
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "shows": shows}, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        for turn in range(REPLACE_TRIES):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:                 # Windows: the reader's `Kept` has it open this moment
                if turn == REPLACE_TRIES - 1:
                    raise
                time.sleep(REPLACE_WAIT_S)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


class Kept:
    """The library reader's copy of the cache (its own thread): `shows()` reads the file again only when it moved
    (S19) — the same dict while it hasn't."""

    def __init__(self, language, path=None):
        self.language = language
        self.path = path
        self._stamp = None
        self._shows = {}

    def shows(self):
        try:
            if self.path is None:
                self.path = cache_path(self.language)
            st = os.stat(self.path)
            stamp = (st.st_mtime_ns, st.st_size)
        except (OSError, RuntimeError):
            stamp = None                            # none yet (or no local folder: a test with no root)
        if stamp != self._stamp:
            self._stamp = stamp
            self._shows = read(self.path) if stamp is not None else {}
        return self._shows


# --- the asks ------------------------------------------------------------------------------------------------------- #
class Airing:
    """`want(ids)` (the reader's thread; returns at once) keeps the due ones; its own thread asks them, `BATCH` a query,
    through `post(variables, query)` — the covers fetcher's `_post` (its throttle, headers and switch; it raises when
    nothing was answered) — and only while `on()` (the covers' `on`). Each answer is written into the cache; then
    `on_change()` (the reader: the next view reads it, A6)."""

    def __init__(self, language, post, on, path=None, clock=time.time, retry_s=RETRY_S, background=True):
        self.language = language
        self.post = post
        self.on = on
        self.path = path
        self.clock = clock
        self.retry_s = retry_s
        self.background = background        # False (tests): no thread — the caller runs `run_once()` itself
        self.on_change = None
        self._cond = threading.Condition()
        self._shows = None                  # the cache as this service knows it (read at the first ask)
        self._queue = []
        self._later = {}                    # id -> when a failed ask is asked again
        self._wanted = set()                # the reader's last near-end ids: a queued or retried id no longer in
        #                                     them (finished, moved out of Current, watched back) is never sent
        self._gen = 0                       # moved by `clear`: an answer asked before it is never kept after it
        self._stop = False
        self._thread = None

    def _path(self):
        if self.path is None:
            self.path = cache_path(self.language)
        return self.path

    def _known(self):
        if self._shows is None:
            try:
                self._shows = read(self._path())
            except RuntimeError:
                self._shows = {}
        return self._shows

    def want(self, ids):
        """The ids of Current's titles near their end (`near_end`): each one whose kept answer is due, not queued and
        not waiting for a retry, queued; they replace the last ids handed (an empty list too). -> how many (0 with the
        switch off: nothing kept)."""
        ids = list(ids or ())
        with self._cond:
            self._wanted = set(ids)
        if not ids or not self.on():
            return 0
        now = self.clock()
        n = 0
        with self._cond:
            if self._stop:
                return 0
            shows = self._known()
            for i in ids:
                if i in self._queue or self._later.get(i, now) > now or not due(shows.get(str(i)), now):
                    continue
                self._later.pop(i, None)
                self._queue.append(i)
                n += 1
            if n:
                self._start()
                self._cond.notify_all()
        return n

    def stop(self, timeout=5):
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def clear(self):
        """*Remove downloaded covers* (A7): the kept answers gone, the file removed; nothing asked is forgotten."""
        with self._cond:
            self._shows = {}
            self._later.clear()
            self._gen += 1
            try:
                os.remove(self._path())
            except (OSError, RuntimeError):
                pass
        self._changed()

    def _start(self):
        if self.background and self._thread is None and not self._stop:
            self._thread = threading.Thread(target=self._run, name=f"airing-{self.language}", daemon=True)
            self._thread.start()

    def _run(self):
        while True:
            with self._cond:
                while not self._stop and not self._queue:
                    soonest = min(self._later.values(), default=None)
                    if soonest is not None and soonest <= self.clock():
                        break
                    self._cond.wait(WAIT_S if soonest is not None else None)
                if self._stop:
                    return
            try:
                self.run_once()
            except Exception as e:                  # the thread never dies of an error
                print(f"Airing: a round failed: {e!r}")

    def run_once(self):
        """One round: the queued ids and the retries that are due, `BATCH` a query. -> how many answers were kept."""
        with self._cond:
            now = self.clock()
            for i, t in list(self._later.items()):
                if i not in self._wanted:
                    del self._later[i]              # no longer near its end in Current: never asked
                elif t <= now and i not in self._queue:
                    del self._later[i]
                    self._queue.append(i)
            todo, self._queue = [i for i in self._queue if i in self._wanted], []
        if not todo or not self.on():
            return 0                                # switched off: nothing asked, nothing kept (a later want asks)
        kept = 0
        for at in range(0, len(todo), BATCH):
            kept += self._ask(todo[at:at + BATCH])
        return kept

    def _ask(self, chunk):
        with self._cond:
            gen = self._gen
        try:
            data = self.post({"ids": list(chunk)}, Q_AIRING)
        except Exception:
            if self.on():                           # off or stopped: dropped (a later `want` asks again)
                with self._cond:
                    for i in chunk:
                        self._later[i] = self.clock() + self.retry_s
            return 0
        found = {}
        for m in ((data or {}).get("Page") or {}).get("media") or ():
            if isinstance(m, dict) and isinstance(m.get("id"), int):
                found[m["id"]] = m
        now = self.clock()
        with self._cond:
            if self._stop or gen != self._gen:
                return 0                            # stopped, or *Remove downloaded covers* came meanwhile
            before = self._known()
            shows = dict(before)
            for i in chunk:
                m = found.get(i)
                nxt = (m or {}).get("nextAiringEpisode") or {}
                shows[str(i)] = {"status": m.get("status") if m and isinstance(m.get("status"), str) else "unknown",
                                 "episodes": _number(m.get("episodes")) if m else None,
                                 "next_at": _number(nxt.get("airingAt")) if isinstance(nxt, dict) else None,
                                 "asked_at": now}
            self._shows = shows
            _write(self._path(), shows)
            moved = any(_answer(before.get(str(i))) != _answer(shows[str(i)]) for i in chunk)
        if moved:
            self._changed()                         # S19: an answer the same as before (only its time) builds nothing
        return len(chunk)

    def _changed(self):
        tell = self.on_change
        if tell is not None:
            try:
                tell()
            except Exception as e:
                print(f"Airing: the reader wasn't told: {e!r}")

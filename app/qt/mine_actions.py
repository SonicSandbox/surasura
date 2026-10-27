"""Connect's actions in the window (P4.1 L2: rows 4.1.11 and 4.1.12's two hidden hooks; the P4.1 RUNBOOK's C2, C3, C6,
IK S3, S7). What the rows, Finished, the arrivals and *Needs you* ask for, routed:

- **One way to ask for mining (C2):** *Mine now* (Waiting's icon) and *Mine this* (a *Mine* status) — the rows'
  `mine_requested` —, Finished's *Mine* / *Mine it too* and the arrivals' *Mine them too* are all `Writer.ask_mining(ids)`,
  given through the drag controller's tickets (its toast's Undo, Ctrl+Z). The writer's after-commit hook
  (`shell.connect_after_commit`) then kicks Connect. A book's or a text's makes no ask: Anki Miner mines video only, so
  the bar says it waits for Anki Miner to read books (alpha 4 M1; K67, IK S3).
- ***Link…*** (No video's): the system's file picker, videos only (`runner.VIDEO_EXTENSIONS`) → `Writer.link_video`.
- ***Find its folder…*** (MV-2, Sonic: yes; a *No video* whose video left the folder it was in — Connect's line
  names it, `view_rows.Status.moved`): the system's folder picker, opened near where it was, then Settings' own *Add
  a folder…* (`settings_sources.add_folder`: `Store.add_source` and its look, on the looks' worker) — one way in;
  the store's join (MV-1) makes the show find its episodes there, and the look that recorded their videos kicks
  Connect (the shell's `_sources_looked`). Offered on the status's menu and on the episode's ⋯.
- ***Mine text*** (C6) and *Needs you*'s *Mine the text only* are gone (alpha 4 M1, Sonic 2026-10-27: "I honestly
  don't want to ever have to open anki miner. Ever."): nothing here opens Anki Miner's window. A book waits quietly
  (`view_rows`' *Waits for Anki Miner*) and Connect mines it by itself once Anki Miner reads books.
- **Connect off** (`settings_manager.connect_on` false): the rows' `connect_off` holds why (`feed.OFF_*`): their buttons
  ask nothing and their tips say why; the other asks say it in the bar. Read on a worker when the window opens and when
  Connect's switch or D29's automation is written.

- ***Make their cards*** (a gap in *Needs you*): Connect's ordinary work, never an ask (P4.1 WF, IK D-1 lean (a);
  P2.1-3): `connect.actions.make_cards` queues the gap's episodes as Connect's own jobs — nothing you deleted comes
  back — in the gap's own language, Connect is kicked, then the entry is answered as *Leave them* answers it.
- **The bulk asks** (Finished's *Mine* / *Mine it too*, the arrivals' *Mine them too*) ask by the rows' rule
  (`rows.asked_files`): never a file in Anki, being mined, or whose cards were deleted (P4.1 WF, adversary S5).
- **An episode's own ⋯** (row 28, Michi's row 24b ask): *Mine now* exactly where the episode's pill would be *Mine
  now* (`rows.action_of`, its tip the pill's), picked as the pill is clicked (`mine_row`, its ids the pill's).
- **Pressed, its pills turn at once** (round 8 row 45, the trial): each file asked for is a press of the window's
  (`mine:<language>:<id>` in `win.presses`, IK-3: the header's hairline runs with it) and is marked in each list
  (`RowsView.press_ids`, painted before the ask is handed to the writer). Its press ends when its status moves
  (Connect read the ask: `RowsView.press_moved`), the ask is refused (failed) or undone (the ticket's `told`), the
  language switches (`settle_all`), or — A-4 — `SETTLE_S` after the ask was saved: Connect not running, Anki closed, on
  battery, the pill gives way to Connect's own state and its reason (a wait is a state, never an endless *starting*).
  Saved, the feed is looked at now. Asked again while they turn, nothing is asked.
- ***Stop*** (R47, laptop rows 47 + 56; Michi's seam): a *Mining* pill whose job can still be stopped (`feed.Item.
  stoppable`, while Connect may run) is a button, and the episode's ⋯ offers *Stop mining* on the same rule
  (`rows.action_of`). Pressed, the file is a press of the window's (`stop:<language>:<job>`) and its pill reads
  *Stopping…* — painted before the stop is handed to a worker (`connect.actions.stop`, then the feed looked at now) —
  until the file leaves Mining (stopped: it waits for your *Mine now*; `RowsView.stop_moved`). Refused (the job past
  its stop point, or gone), the pill is its own again and the bar says why. This episode only: Connect goes on to the
  next (Sonic LF4-5 = A).
Nothing here reads the store or the settings on the window's thread: the writes are the writer's, the looks a worker's.
"""
import os

import itertools

from PyQt6 import sip
from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QApplication, QFileDialog

from app import path_utils
from app.qt import bridge, drag, item_menu, rows, strings
from app.qt import press as qpress

OFF_KEYS = frozenset(("connect_enabled", "logic.automation", "automation"))
SETTLE_S = 6.0          # an ask saved, then its pill's press ends (A-4: two of Connect's 3 s looks; PROVISIONAL)


def connect_off(settings):
    """Why Connect may not run now (the feed's own off line: `feed.OFF_CONNECT` / `feed.OFF_AUTOMATION`), or None."""
    from app import settings_manager
    from app.connect import feed
    if settings_manager.connect_on(settings):
        return None
    return feed._off(settings).line


def _video_patterns():
    """(A worker.) The picker's filter: the videos Connect can make cards from."""
    from app.connect import runner
    return " ".join("*" + ext for ext in runner.VIDEO_EXTENSIONS)


def _make_cards(language, gap_id):
    """(A worker.) Connect's `actions.make_cards`: the gap's episodes queued -> how many, or False."""
    from app.connect import actions
    return actions.make_cards(language, gap_id)


def _stop(language, job_id):
    """(A worker.) Connect's `actions.stop` -> True when the stop was recorded."""
    from app.connect import actions
    return actions.stop(language, job_id)


class MineActions(QObject):
    """Made by the shell when it has a writer (as Finished's actions). The controller, the writer and the language are
    the window's as they are at each call (a language switch rebuilds `win.moves`: nothing here is rebuilt)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.off = None                              # why Connect may not run (None: it may), read on a worker
        self.pick_file = lambda title, folder, patterns: QFileDialog.getOpenFileName(
            self.win, title, folder, strings.LINK_FILTER.format(patterns=patterns))[0]     # (tests replace it)
        self.pick_folder = lambda title, folder: QFileDialog.getExistingDirectory(self.win, title, folder)  # (tests)
        self.lists = [page.list for page in win.page_widgets.values() if hasattr(getattr(page, "list", None),
                                                                                  "mine_requested")]
        self.make_cards = _make_cards                # (tests replace it)
        self.stop_job = _stop                        # R47 (tests replace it)
        self._stops = {}                             # R47: file id -> its Stop's press key
        self._asked = {}                             # round 8 row 45: file id -> (its ask's number, its press's key)
        self._asks = itertools.count(1)
        for lst in self.lists:
            lst.press_moved = self.settle
            lst.stop_moved = self.stopped                # --- R47
            lst.stop_requested.connect(lambda row, ask: self.stop(ask))
            lst.mine_requested.connect(self.mine_row)
            lst.link_requested.connect(lambda row, ep, lst=lst: self.link(row, ep, lst))
            lst.find_folder_requested.connect(lambda row, ep: self.find_folder(ep))         # --- MV-2
        fin = getattr(win, "finished", None)
        if fin is not None:
            fin.on_mine = lambda row: self.mine_row(row, self._askable(row.episodes))      # P4.1 WF (S5)
            fin.on_mine_too = lambda row: self.mine_row(row, self._askable(row.episodes))
        tray = getattr(win, "arrivals_tray", None)
        if tray is not None:
            tray.mine_too = self.mine_ids
        needs = getattr(win, "needs_you", None)
        if needs is not None:
            needs.hooks["make_cards"] = self._needs_make_cards
            needs.rewire()
        items = getattr(win, "items", None)
        if items is not None:                        # --- row 28 (Michi's row 24b ask): an episode's ⋯ offers *Mine now*
            items.episode_hooks.append(self.episode_entries)
        win.bridge.settings_written.connect(self._settings_written)
        self.read_off()

    # --- Connect off ------------------------------------------------------------------------------------------- #
    def read_off(self):
        get = self.win.services.settings.get
        bridge.run_in_worker(lambda: connect_off(get()), then=self._off_read,
                             failed=lambda info: print(f"Connect's switch wasn't read: {info[1]}"))

    def _off_read(self, why):
        self.off = why
        for lst in self.lists:
            lst.connect_off = why

    def _settings_written(self, keys):
        if OFF_KEYS & set(keys or ()):
            self.read_off()

    # --- asking for mining (C2) ------------------------------------------------------------------------------ #
    @staticmethod
    def _askable(episodes):
        """The files of `episodes` an ask may name (`rows.asked_files`' *Mine this* rule: not in Anki, not being mined,
        their cards not deleted, on disk) -> their ids."""
        return [e.id for e in rows.asked_files("mine", episodes)]

    def mine_row(self, row, ids):
        """*Mine now* / *Mine this* / Finished's *Mine* and *Mine it too*: the ask for the files Anki Miner can mine
        (`videos_of`), the others left out and the toast saying so; none of them a video: the bar says they wait for
        Anki Miner to read books (alpha 4 M1). Nothing left to ask for: the bar says so."""
        ids = list(dict.fromkeys(ids))
        if not ids:
            self.win.say(strings.MINE_NOTHING)
            return None
        videos, other = videos_of(row, ids)
        if not videos:
            self.win.say(_waits_line(other))
            return None
        text = strings.MINE_ASKED if len(videos) == len(ids) else strings.MINE_ASKED_VIDEOS
        return self._ask(text.format(title=row.title), (row.key,), videos)

    def mine_ids(self, ids):
        """The arrivals' *Mine them too*: of `ids`, the files the rows' rule may ask for (P4.1 WF, S5), told by the
        tray's own rows' episodes (a file the tray doesn't show isn't asked for); none left: the bar says so. Of those,
        the videos are asked for (`videos_of`, each tray row by its own files' types, as `mine_row`), the others left out
        and the toast saying so; none of them a video: the bar says they wait for Anki Miner to read books."""
        if self.off:                                 # Connect off: that is why nothing is asked, said first
            self.win.say(self.off)
            return None
        tray = getattr(self.win, "arrivals_tray", None)
        arrivals = [a for g in (getattr(tray, "groups", None) or ()) for a in g.rows]
        known = {e.id: e for a in arrivals for e in a.episodes}
        ids = self._askable([known[i] for i in dict.fromkeys(ids) if i in known])
        if not ids:
            self.win.say(strings.MINE_NOTHING)
            return None
        videos, other = set(), None
        for a in arrivals:
            v, o = videos_of(a, [e.id for e in a.episodes if e.id in ids])
            videos.update(v)
            other = other or o
        asked = [i for i in ids if i in videos]
        if not asked:
            self.win.say(_waits_line(other))
            return None
        if len(asked) < len(ids):
            text = strings.MINE_ASKED_N_VIDEOS[len(asked) == 1].format(n=len(asked))
        else:
            text = strings.MINE_ASKED_ONE if len(ids) == 1 else strings.MINE_ASKED_N.format(n=len(ids))
        return self._ask(text, (), asked)

    def _ask(self, text, keys, ids):
        """-> the writer's number, or None (Connect off: said in the bar; the store refused: the controller says)."""
        if self.off:
            self.win.say(self.off)
            return None
        moves = self.win.moves
        if moves is None or moves.refused() is not None:
            return None
        presses = qpress.presses_of(self.win)
        lang = getattr(self.win, "language", "")
        keys_of = {i: f"mine:{lang}:{i}" for i in ids}
        if all(presses.get(k).live() for k in keys_of.values()):
            return None                              # round 8 row 45: asked already, still turning — asked once
        n = next(self._asks)
        for i, key in keys_of.items():               # ... each file a press (the hairline runs, painted now) …
            qpress.begin(None, key, win=self.win, at=qpress.NOWHERE)     # (its pills are its mark: below)
            self._asked[i] = (n, key)
        for lst in self.lists:                       # ... and its pills turn now, painted before the ask is handed over
            lst.press_ids(ids)
        ticket = drag.Ticket(text, keys, ids)
        ticket.told = lambda event: self._told(event, ids, n)
        writer = moves.writer
        try:                                         # (refused: the ticket is told so: failed; the controller says why)
            return moves._give(ticket, lambda t: writer.ask_mining(ids, label=t))
        except Exception as e:                       # never a press left turning
            self.settle(ids, why=e)
            raise

    def _told(self, event, ids, n):
        """Round 8 row 45: the ask saved — Connect's feed looked at now, not at its next tick, and its presses end
        `SETTLE_S` later if Connect hasn't moved them by then (A-4); refused — failed; undone — done."""
        if event == "saved":
            refresh = getattr(getattr(self.win.services, "status", None), "refresh_soon", None)
            if refresh is not None:
                refresh("connect")
            QTimer.singleShot(int(SETTLE_S * 1000), lambda: None if sip.isdeleted(self) else
                              self.settle([i for i in ids if self._asked.get(i, (None,))[0] == n]))
            return
        self.settle(ids, why=event if event == "refused" else None)

    def settle(self, ids, why=None):
        """The presses of the files `ids` end (done, or failed `why`), and their pills are their own again in every
        list."""
        presses = qpress.presses_of(self.win)
        for i in ids:
            got = self._asked.pop(i, None)
            if got is not None:
                p = presses.get(got[1])
                if p.live():
                    qpress.end(p, self.win, failed=why is not None, why=why)
        for lst in self.lists:
            lst.unpress(ids)

    def settle_all(self):
        """A language switch: no pressed Mine now (nor Stop, R47) of the language left."""
        self.settle(list(self._asked) + [i for lst in self.lists for i in lst.pressed_ids])
        self.stopped(list(self._stops) + [i for lst in self.lists for i in lst.stopping_ids])

    # --- R47: a Mining pill's *Stop* ------------------------------------------------------------------------------ #
    def stop(self, ask):
        """*Stop* on the file `ask` names (`rows.Ask`: its job): its pill reads *Stopping…* now — painted before the
        worker is handed the stop — until the file leaves Mining (`stopped`); refused, it is its own again and the bar
        says why. Connect off: nothing is stopped and the bar says why. Pressed again meanwhile: nothing."""
        if ask is None or ask.job is None:
            return None
        if self.off:
            self.win.say(self.off)
            return None
        lang = getattr(self.win, "language", "")
        key = f"stop:{lang}:{ask.job}"
        if qpress.presses_of(self.win).get(key).live():
            return None                              # pressed already: still stopping
        ids = list(ask.ids)
        marked = [lst.press_stop(ids) for lst in self.lists]     # *Stopping…* painted now, before the worker
        shown = any(marked)                          # R47-A2: no list shows it — the press ends with the worker
        # IK-2 (intent keeper round 8, finding 2): its pill is its one mark; only a pill no list shows takes the bar's arc
        p = qpress.begin(None, key, win=self.win, at=qpress.NOWHERE if shown else None)
        for i in ids:
            self._stops[i] = key
        status = getattr(self.win.services, "status", None)

        def done(ok):
            if sip.isdeleted(self):
                return
            if not ok or not shown:
                self._end_stop(ids, why=None if ok else strings.MINE_STOP_REFUSED)
                return
            refresh = getattr(status, "refresh_soon", None)
            if refresh is not None:
                refresh("connect")                   # the feed looked at now: *Stopping…* is Connect's from there

        def broke(info):
            if not sip.isdeleted(self):
                self._end_stop(ids, why=strings.MINE_STOP_FAILED.format(why=info[0] if info else ""))
        bridge.run_in_worker(self.stop_job, lang, ask.job, then=done, failed=broke)
        return p

    def stopped(self, ids, late=False):
        """The files `ids` left Mining (stopped, or no longer mined): their Stop presses end, done. `late` (R47-A1):
        still Mining, but Connect dropped the stop as it began naming the clips — ended refused, the bar says so."""
        self._end_stop(ids, why=strings.MINE_STOP_TOO_LATE if late else None)

    def _end_stop(self, ids, why=None):
        """The Stop presses of `ids` end (done, or failed `why`); every list lets them go. `why` goes to the bar only
        when a press of this window's ended here (R47-A3: never one a language switch or the feed already ended)."""
        presses = qpress.presses_of(self.win)
        ended = False
        for i in ids:
            key = self._stops.pop(i, None)
            if key is not None and key not in self._stops.values():
                p = presses.get(key)
                if p.live():
                    qpress.end(p, self.win, failed=why is not None, why=why)
                    ended = True
        for lst in self.lists:
            lst.unstop(ids)
        if why is not None and ended:
            self.win.say(why)

    # --- row 28 (Michi's row 24b ask): an episode's own ⋯ ----------------------------------------------------- #
    def episode_entries(self, row, ep):
        """`ep`'s ⋯ (`item_menu.ItemActions.episode_hooks`): *Mine now* exactly when its pill would be *Mine now*
        (`rows.action_of`, the pill's one rule — whatever it offers *Mine now* on), its tip the pill's — Connect off,
        the entry is there and its tip says why; a write, so greyed by the menu while the store is read-only; picked,
        the pill's own path (`mine_row`: off, nothing is asked and the bar says why). R47: *Stop mining* exactly when
        its pill is *Stop* (never while Connect is off), its tip the pill's; no store write, so never greyed for one;
        picked, the pill's own `stop` — the menu has closed, so the pill shows the press. -> [Entry]"""
        if ep.status is None:
            return []
        name, tip, ask = rows.action_of(ep.status, (ep,), self.off, ep.media_word or row.media_word)
        moved = getattr(ep, "moved", None) or getattr(ep.status, "moved", None)
        if moved:                                    # --- MV-2: its video left its folder
            return [item_menu.Entry("ep-find-folder", strings.ROWS_FIND_FOLDER,
                                    strings.ROWS_FIND_FOLDER_TIP.format(folder=moved), True,
                                    payload=lambda: self.find_folder(ep), writes=True)]
        if name == rows.STOP:                        # --- R47
            return [item_menu.Entry("ep-stop", strings.MINE_STOP_ENTRY, tip, True, payload=lambda: self.stop(ask))]
        if name != "mine-now":
            return []
        return [item_menu.Entry("ep-mine-now", strings.ROWS_ACTION_NAMES["mine-now"], tip, True,
                                payload=lambda: self.mine_row(row, list(ask.ids)), writes=True)]
    # --- end row 28

    # --- Link… ------------------------------------------------------------------------------------------------ #
    def link(self, row, ep, lst=None):
        """No video's *Link…*: a video chosen in the system's picker → the writer's `link_video` (refused there with
        its words, as Needs you's). Round 8 row 45: the picker opens only after a worker (the video types), so the
        row's status turns from the press (`lst`'s, IK-2; none: the bar's arc) until the picker shows."""
        if self.win.moves is None:
            return
        folder = os.path.dirname(os.path.join(path_utils.get_data_path(self.win.language),
                                              *(ep.rel_path or "").split("/")))
        at = qpress.row_mark(lst, [ep.id], "no-media") if lst is not None else None

        def pick(patterns):
            moves = self.win.moves
            path = self.pick_file(strings.LINK_TITLE.format(label=ep.label), folder, patterns)
            if not path or moves is None or moves.refused() is not None:
                return
            writer = moves.writer
            moves._give(drag.Ticket(strings.LINKING_ONE.format(label=ep.label), (row.key,), (ep.id,)),
                        lambda t: writer.link_video(ep.id, path, label=t))
        qpress.run(None, ("link", ep.id), _video_patterns, then=pick, failed=lambda info: self.win.say(str(info[1])),
                   win=self.win, at=at)

    # --- MV-2: Find its folder… ------------------------------------------------------------------------------ #
    def find_folder(self, ep):
        """*Find its folder…*: the folder picker, opened at the folder above where its video was (never stat'ed here:
        the window's thread waits on no disk; the picker falls back on its own when it's gone), then Settings' *Add a
        folder…* with the folder picked (`settings_sources.add_folder`: the store's `add_source` and its look —
        refused there, greyed or said, as on Settings' page). -> True when a folder was asked for."""
        from app.qt import settings_sources
        why = settings_sources.why_not(self.win)
        if why is not None:                         # the library can't take a folder now: said, never a silent picker
            self.win.say(why)
            return False
        moved = getattr(ep, "moved", None) or getattr(getattr(ep, "status", None), "moved", None)
        where = os.path.dirname(moved or "")
        folder = self.pick_folder(strings.FIND_FOLDER_TITLE.format(label=ep.label), where)
        if not folder:
            return False
        return bool(settings_sources.add_folder(self.win, self.win, folder))

    def _needs_make_cards(self, entry, _line=None):
        """A gap's *Make their cards* (P4.1 WF, IK D-1 lean (a)): Connect's ordinary work, not an ask — so no store
        write to refuse or undo later (adversary S3). On a worker: `actions.make_cards` in the entry's own language
        (*Needs you*'s, the language the gap came from — never the writer's of the language open now, adversary S4),
        Connect kicked when it queued any (as *Mine anyway* is), and only then the entry answered as *Leave them*
        answers it; the bar says how many episodes' cards come next, and *Needs you* is read again. Connect off:
        refused in the bar, nothing answered."""
        if self.off:
            self.win.say(self.off)
            return
        needs = self.win.needs_you
        gap_id = (entry.data or {}).get("gap_id")
        if needs is None or gap_id is None:
            return
        from app.services import needs as service
        make, kick, read_settings = self.make_cards, needs.connect_calls.get("kick"), needs.read_settings
        language, keys = needs.language, service.answer_keys(entry)

        def run():
            made = make(language, gap_id)
            if made is False:
                return made                         # no such gap, no ledger: nothing written, nothing answered
            if made and kick is not None:
                try:
                    kick(read_settings() or {})
                except Exception as e:              # a kick that fails leaves the jobs queued: the next start runs them
                    print(f"Connect wasn't kicked: {e}")
            service.answer(language, keys)
            return made
        needs._press("make_cards", entry, run, then=lambda made: needs._connect_done(_made_words(made)))   # (its arc)


def _waits_line(ep):
    """The bar's line for a *Mine* on files Anki Miner can't mine yet (alpha 4 M1, A4M1-3): audio's when the first such
    file is a podcast's or an audiobook's (`Episode.text`), else books'."""
    return strings.MINE_AUDIO_WAIT if getattr(ep, "text", None) == "audio" else strings.MINE_BOOKS_WAIT


def videos_of(row, ids):
    """K67 (IK S3: Anki Miner mines video only), one rule for one file and for many: of `ids`, the files that are
    videos, each by its own type (`Episode.media_word`; the row's for a first screen's cache from before — LM11b: a
    group holds several types) -> (their ids in order, the first other file's episode or None)."""
    by = {e.id: e for e in row.episodes}
    word = getattr(row, "media_word", "video")
    videos, other = [], None
    for i in ids:
        ep = by.get(i)
        if ((ep.media_word if ep is not None else None) or word) == "video":
            videos.append(i)
        elif other is None:
            other = ep
    return videos, other


def _made_words(made):
    if made is False:
        return strings.MAKE_CARDS_GONE
    if not made:
        return strings.MAKE_CARDS_NONE
    return strings.MAKE_CARDS_QUEUED[made == 1].format(n=made)

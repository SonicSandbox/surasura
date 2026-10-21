"""Connect's actions in the window (P4.1 L2: rows 4.1.11 and 4.1.12's two hidden hooks; the P4.1 RUNBOOK's C2, C3, C6,
IK S3, S7). What the rows, Finished, the arrivals and *Needs you* ask for, routed:

- **One way to ask for mining (C2):** *Mine now* (Waiting's icon) and *Mine this* (a *Mine* status) — the rows'
  `mine_requested` —, Finished's *Mine* / *Mine it too* and the arrivals' *Mine them too* are all `Writer.ask_mining(ids)`,
  given through the drag controller's tickets (its toast's Undo, Ctrl+Z). The writer's after-commit hook
  (`shell.connect_after_commit`) then kicks Connect. A non-video item's *Mine this* makes no ask: it is *Mine text* (K67,
  IK S3: Anki Miner mines video only).
- ***Link…*** (No video's): the system's file picker, videos only (`runner.VIDEO_EXTENSIONS`) → `Writer.link_video`.
- ***Mine text*** (C6), and *Needs you*'s *Mine the text only*: Anki Miner's own window (as Settings' *Open Anki Miner*
  does) with the file's path on the clipboard, and a toast saying so — mining by hand.
- **Connect off** (`settings_manager.connect_on` false): the rows' `connect_off` holds why (`feed.OFF_*`): their buttons
  ask nothing and their tips say why; the other asks say it in the bar. Read on a worker when the window opens and when
  Connect's switch or D29's automation is written.

- ***Make their cards*** (a gap in *Needs you*): Connect's ordinary work, never an ask (P4.1 WF, IK D-1 lean (a);
  P2.1-3): `connect.actions.make_cards` queues the gap's episodes as Connect's own jobs — nothing you deleted comes
  back — in the gap's own language, Connect is kicked, then the entry is answered as *Leave them* answers it.
- **The bulk asks** (Finished's *Mine* / *Mine it too*, the arrivals' *Mine them too*) ask by the rows' rule
  (`rows.asked_files`): never a file in Anki, being mined, or whose cards were deleted (P4.1 WF, adversary S5).
Nothing here reads the store or the settings on the window's thread: the writes are the writer's, the looks a worker's.
"""
import os

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication, QFileDialog

from app import path_utils
from app.qt import bridge, drag, rows, strings, windows

OFF_KEYS = frozenset(("connect_enabled", "logic.automation", "automation"))


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


def _miner_and_file(settings, path):
    """(A worker.) -> (Anki Miner's program or None, the file's path)."""
    from app.connect import anki_miner
    return anki_miner.find(settings), path


class MineActions(QObject):
    """Made by the shell when it has a writer (as Finished's actions). The controller, the writer and the language are
    the window's as they are at each call (a language switch rebuilds `win.moves`: nothing here is rebuilt)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.off = None                              # why Connect may not run (None: it may), read on a worker
        self.pick_file = lambda title, folder, patterns: QFileDialog.getOpenFileName(
            self.win, title, folder, strings.LINK_FILTER.format(patterns=patterns))[0]     # (tests replace it)
        self.lists = [page.list for page in win.page_widgets.values() if hasattr(getattr(page, "list", None),
                                                                                  "mine_requested")]
        self.make_cards = _make_cards                # (tests replace it)
        for lst in self.lists:
            lst.mine_requested.connect(self.mine_row)
            lst.link_requested.connect(self.link)
            lst.mine_text_requested.connect(lambda row, ep: self.mine_text(ep.label, ep.rel_path))
        fin = getattr(win, "finished", None)
        if fin is not None:
            fin.on_mine = lambda row: self.mine_row(row, self._askable(row.episodes))      # P4.1 WF (S5)
            fin.on_mine_too = lambda row: self.mine_row(row, self._askable(row.episodes))
        tray = getattr(win, "arrivals_tray", None)
        if tray is not None:
            tray.mine_too = self.mine_ids
        needs = getattr(win, "needs_you", None)
        if needs is not None:
            needs.hooks["mine_text_only"] = self._needs_mine_text
            needs.hooks["make_cards"] = self._needs_make_cards
            needs.rewire()
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
        """*Mine now* / *Mine this* / Finished's *Mine* and *Mine it too*: the ask, or a non-video item's *Mine text*.
        Nothing left to ask for: the bar says so."""
        ids = list(dict.fromkeys(ids))
        if not ids:
            self.win.say(strings.MINE_NOTHING)
            return None
        if getattr(row, "media_word", "video") != "video":         # K67: Anki Miner mines video only
            ep = next((e for e in row.episodes if e.id == ids[0]), row.episodes[0])
            return self.mine_text(ep.label, ep.rel_path)
        return self._ask(strings.MINE_ASKED.format(title=row.title), (row.key,), ids)

    def mine_ids(self, ids):
        """The arrivals' *Mine them too*: of `ids`, the files the rows' rule may ask for (P4.1 WF, S5), told by the
        tray's own rows' episodes (a file the tray doesn't show isn't asked for); none left: the bar says so."""
        if self.off:                                 # Connect off: that is why nothing is asked, said first
            self.win.say(self.off)
            return None
        tray = getattr(self.win, "arrivals_tray", None)
        known = {e.id: e for g in (getattr(tray, "groups", None) or ()) for a in g.rows for e in a.episodes}
        ids = self._askable([known[i] for i in dict.fromkeys(ids) if i in known])
        if not ids:
            self.win.say(strings.MINE_NOTHING)
            return None
        text = strings.MINE_ASKED_ONE if len(ids) == 1 else strings.MINE_ASKED_N.format(n=len(ids))
        return self._ask(text, (), ids)

    def _ask(self, text, keys, ids):
        """-> the writer's number, or None (Connect off: said in the bar; the store refused: the controller says)."""
        if self.off:
            self.win.say(self.off)
            return None
        moves = self.win.moves
        if moves is None or moves.refused() is not None:
            return None
        writer = moves.writer
        return moves._give(drag.Ticket(text, keys, ids), lambda t: writer.ask_mining(ids, label=t))

    # --- Link… ------------------------------------------------------------------------------------------------ #
    def link(self, row, ep):
        """No video's *Link…*: a video chosen in the system's picker → the writer's `link_video` (refused there with
        its words, as Needs you's)."""
        if self.win.moves is None:
            return
        folder = os.path.dirname(os.path.join(path_utils.get_data_path(self.win.language),
                                              *(ep.rel_path or "").split("/")))

        def pick(patterns):
            moves = self.win.moves
            path = self.pick_file(strings.LINK_TITLE.format(label=ep.label), folder, patterns)
            if not path or moves is None or moves.refused() is not None:
                return
            writer = moves.writer
            moves._give(drag.Ticket(strings.LINKING_ONE.format(label=ep.label), (row.key,), (ep.id,)),
                        lambda t: writer.link_video(ep.id, path, label=t))
        bridge.run_in_worker(_video_patterns, then=pick, failed=lambda info: self.win.say(str(info[1])))

    # --- Mine text (C6) --------------------------------------------------------------------------------------- #
    def mine_text(self, label, rel_path):
        """Anki Miner's own window, the file's path on the clipboard, a toast saying so (never hidden: K67)."""
        path = os.path.join(path_utils.get_data_path(self.win.language), *(rel_path or "").split("/"))
        get = self.win.services.settings.get
        bridge.run_in_worker(lambda: _miner_and_file(get(), path), then=lambda found: self._open_miner(label, found),
                             failed=lambda info: self.win.say(strings.MINE_TEXT_NO_MINER))

    def _open_miner(self, label, found):
        miner, path = found
        if not miner:
            self.win.say(strings.MINE_TEXT_NO_MINER)
            return
        QApplication.clipboard().setText(path)
        if not windows.open_url(miner):
            self.win.say(strings.MINE_TEXT_NOT_OPENED.format(path=miner))
            return
        self.win.toasts.show(strings.MINE_TEXT_COPIED.format(name=label))

    def _needs_mine_text(self, entry, line):
        line = line if line is not None else (entry.lines[0] if entry.lines else None)
        if line is not None:
            self.mine_text(line.label, line.rel_path)

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
        bridge.run_in_worker(run, then=lambda made: needs._connect_done(_made_words(made)), failed=needs._failed)


def _made_words(made):
    if made is False:
        return strings.MAKE_CARDS_GONE
    if not made:
        return strings.MAKE_CARDS_NONE
    return strings.MAKE_CARDS_QUEUED[made == 1].format(n=made)

# SPDX-License-Identifier: GPL-3.0-or-later
"""The YouTube transcript downloader in Qt (W3.4 row 4; the RUNBOOK's row 4; the intent keeper's IK-5, IK-15).

A secondary window (`app/qt/windows.py`), as clean as it can be (try a9.1, Sonic: "as few buttons / most visual and
condensed yet balanced as possible"; nothing it did is gone, only folded): its heading with a ? (what it does, on
hover); the links (one per line) — the one way in; the one-time risk acknowledgment (saved alone, by this window — or
setup's page 3, alpha 8 — when the user ticks or unticks it: never on open, never by anything else), on the window
until it is given, then in ⋯ (unticked there, back on the window); a run's bar (how many of its videos are read, else
turning); one row: the caption language, ⋯ (*Fill missing timestamps* — asks first with the count and the time —,
*Update yt-dlp*, *Open the Processed folder*, *Open the log*, the risk tick) and *Download* (off until the risk is
acknowledged); and the status line (the last thing the run said — a transcript written as ✓ its name —; the whole run
in the log). With *Download covers* on (Settings; Sonic 2026-11-02, Mado-Y2), the video it downloads shows beside the
bar — the link's video, then each transcript's as it is written —: its thumbnail through the covers' own fetcher
(`covers_online.Fetcher.video_cover`: the same request a title's cover makes, or the cached file with none), fetched
and decoded on a worker; off, no picture and nothing asked; offline or failed, quietly no picture. No *Channel name
first* (try a9.1, Sonic: "we don't need the channel first anymore"): the channel always leads a YouTube file's name,
as setup's and a playlist's rest always had it; no *Keep timestamps* (alpha 8): each line's time is always kept beside
the text, in its cue sidecar.

The rules are `downloader_view`'s; this file paints them. **Each run is a `youtube` job** (the bottom bar shows it
with its last line; Cancel there stops it; quitting stops it — `on_quit="cancel"`; IK-31): one yt-dlp run at a time
across the windows — a run the closed window left still stopping holds the next one back, and the window says so
(AD4-9). The job's thread is its own (a download can take many minutes: never a pool thread), its inputs taken here
first, its log opened by the run (AD4-5), its lines brought back by a `bridge.Relay`. **X while a run goes** (try a9.1)
puts the window into its icon in the bottom bar and the run goes on; the icon's right-click *Stop*, the bar's Cancel,
*Close* there or the app's quit stop a download or a timestamp fill at once: the yt-dlp child running then is ended (`downloader.stopping`). A run
that ends after its window closed says its last line in the bottom bar. **The created files go to the `on_complete
(paths)` the run started with** (AD4-15) — W3.2 routes them into the library's arrivals; until then the door passes
none and the files wait in Processed, which the status line says (IK-32).
"""
import html
import re
import threading
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QProgressBar, QPushButton

from app.qt import bridge, confirm, windows
from app.qt import press as qpress
from app.services import jobs as jobs_module
from modules.youtube_downloader import downloader as core
from modules.youtube_downloader import downloader_view as view
from modules.youtube_downloader import qt_strings as S

NAME = "youtube-downloader"
KIND = "youtube"                                            # app/services/jobs.py RESOURCES
_LABELS = {"download": S.JOB_DOWNLOAD, "fill": S.JOB_FILL, "update": S.JOB_UPDATE}
# the downloader's count (`… 4 of 12 videos read`) and the fill's (`… 10/50 done, pausing …`), at the line's start only
_COUNTED = re.compile(r"…\s*(\d+)\s*(?:of|/)\s*(\d+)\s+(videos read|done)")
# a transcript written: `[ok] (manual) <name> [id].txt` — the kind only as the downloader writes it (a fill's line has
# none, and a title's own bracket stays its own)
_WRITTEN = re.compile(r"\[ok\]\s+(?:\((?:manual|native auto|auto-translated)\)\s+)?(.+?)"
                      r"(?:\s+\[((?:bilibili-)?[\w-]+)\])?\.txt$")
PICTURE_GAP_S = 10                                          # the video's picture changes at most this often (s):
#   a playlist's transcripts land one after another; one picture each would be a request each
_RUNNING_WORDS = {"download": S.KEPT_DOWNLOADING, "fill": S.KEPT_FILLING, "update": S.KEPT_UPDATING}


class DownloaderWindow(windows.SecondaryWindow):
    def __init__(self, shell, on_complete=None, language=None):
        super().__init__(shell, S.DOWNLOADER_TITLE, language)
        self.setObjectName("youtubewindow")
        self.on_complete = on_complete
        self.running = None                                 # "download" · "fill" · "update" while one runs
        self.job = None                                     # the run's job (the registry's)
        self._job_state = None                              # its state as last shown
        self._last_log = None                               # the log of the last run this window started
        self._lines = bridge.Relay(self)
        self._lines.said.connect(self._line)
        # W3.2-2 (IK-L1-2): the done line's link opens the main window's New arrivals tray
        self.status.linkActivated.connect(lambda _href: getattr(self.shell, "open_arrivals", lambda: None)())
        heard = getattr(shell, "bridge", None)
        if heard is not None:
            heard.jobs_changed.connect(self._follow)

        # try a9.1 (Sonic: "as few buttons / most visual and condensed yet balanced as possible"): the heading and its ?
        # (what the window does, behind a hover), the links — the one way in — then one row: the captions, ⋯ (the rest,
        # folded: nothing it did is gone) and Download, the one action; a run shows as a bar, not more words
        head = QHBoxLayout()
        heading = QLabel(S.DOWNLOADER_HEADING, self)
        heading.setObjectName("windowheading")
        self.help = QLabel(S.HELP, self)
        self.help.setObjectName("helpmark")
        self.help.setToolTip(S.HELP_TIP)
        self.help.setAccessibleName(S.HELP_NAME)
        self.help.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(heading)
        head.addWidget(self.help)
        head.addStretch(1)
        self.body.addLayout(head)

        self.links = QPlainTextEdit(self)
        self.links.setPlaceholderText(S.LINKS_HINT)
        self.links.setToolTip(S.LINKS_TIP)
        self.links.setAccessibleName(S.LINKS_NAME)
        self.links.setTabChangesFocus(True)
        self.links.setMinimumHeight(self.links.fontMetrics().lineSpacing() * 4)
        self.body.addWidget(self.links, 1)

        # the one-time acknowledgment: on the window until it is given; after, in ⋯ (ticked there, it can be taken back)
        acknowledged = bool(shell.services.settings.get().get("youtube_risk_acknowledged", False))
        self.risk = self._toggle(S.RISK, S.RISK_TIP, acknowledged)
        self.risk.toggled.connect(self._risk_toggled)       # connected after the state is set: opening writes nothing
        self.risk.setVisible(not acknowledged)
        self.body.addWidget(self.risk)

        self.progress = QProgressBar(self)                  # a run, shown: how far through its videos (else turning)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName(S.PROGRESS_NAME)
        self.progress.setVisible(False)
        # Mado-Y2: the video it downloads, beside the bar (only with *Download covers* on; else never shown)
        self.picture = QLabel(self)
        self.picture.setAccessibleName(S.PICTURE_NAME)
        tall = self.links.fontMetrics().lineSpacing() * 4
        self.picture.setFixedSize(round(tall * 16 / 9), tall)
        self.picture.setVisible(False)
        self._picture = {"want": None, "shown": None, "busy": False, "run": 0, "at": None, "timer": False}
        #   the video asked · shown · a fetch on its way · which run's (a fetch landing after its run ended shows
        #   nothing) · when the last fetch began · a later one waiting for its gap
        bar = QHBoxLayout()
        bar.setSpacing(self.body.spacing())
        bar.addWidget(self.picture)
        bar.addWidget(self.progress, 1)
        self.body.addLayout(bar)

        actions = QHBoxLayout()
        caption = QLabel(S.LANGUAGE_LABEL, self)
        self.caption = QComboBox(self)
        for name in core.LANGS:
            self.caption.addItem(name, name)
        self.caption.setToolTip(S.LANGUAGE_TIP)
        self.caption.setAccessibleName(S.LANGUAGE_LABEL)
        self.caption.setProperty("kind", "choice")
        caption.setBuddy(self.caption)
        self._caption_for(self.language)
        self.more = self._button(S.MORE, S.MORE_TIP, self._show_more)    # a button as Download is: one row, one frame
        self.more.setAccessibleName(S.MORE_NAME)
        self.more.ensurePolished()
        self.more.setMinimumWidth(self.more.sizeHint().height())      # at least square beside Download
        self.more_menu = menu = QMenu(self.more)
        menu.setToolTipsVisible(True)
        self.backfill = self._action(menu, S.BACKFILL, S.BACKFILL_TIP, self._ask_backfill)
        self.update_button = self._action(menu, S.UPDATE, S.UPDATE_TIP, self._update)
        menu.addSeparator()
        self.open_folder = self._action(menu, S.OPEN_FOLDER, S.OPEN_FOLDER_TIP, self._open_folder)
        self.open_log = self._action(menu, S.OPEN_LOG, S.OPEN_LOG_TIP, self._open_log)
        menu.addSeparator()
        self.risk_item = self._action(menu, S.RISK, S.RISK_TIP, lambda: self.risk.setChecked(self.risk_item.isChecked()))
        self.risk_item.setCheckable(True)
        self.risk_item.setChecked(acknowledged)
        self.download = self._button(S.DOWNLOAD, S.DOWNLOAD_TIP, self._download)
        self.download.setProperty("kind", "primary")
        actions.addWidget(caption)
        actions.addWidget(self.caption)
        actions.addStretch(1)
        actions.addWidget(self.more)
        actions.addWidget(self.download)
        self.body.addLayout(actions)
        self._sync()

    def _toggle(self, text, tip, on):
        box = QCheckBox(text, self)
        box.setToolTip(tip)
        box.setAccessibleName(text)
        box.setProperty("kind", "toggle")
        box.setChecked(on)                                  # before any connection: a restored state is no click
        return box

    def _button(self, text, tip, slot):
        b = QPushButton(text, self)
        b.setToolTip(tip)
        b.setAccessibleName(text)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.clicked.connect(lambda _c=False: slot())
        return b

    def _action(self, menu, text, tip, slot):
        """One of ⋯'s items (what were buttons before try a9.1): its words, its tip on hover."""
        act = menu.addAction(text)
        act.setToolTip(tip)
        act.triggered.connect(lambda _c=False: slot())
        return act

    def _show_more(self):
        """⋯: its menu under it (Fill missing timestamps, Update yt-dlp, the folder, the log, the risk tick)."""
        self.more_menu.popup(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def _caption_for(self, language):
        self.caption.setCurrentIndex(max(0, self.caption.findData(view.default_caption_language(language))))

    # --- state --------------------------------------------------------------------------------------------------- #
    def _sync(self):
        idle = self.running is None
        for b, on in ((self.download, idle and self.risk.isChecked()), (self.backfill, idle),
                      (self.update_button, idle)):
            if b.isEnabled() != on:
                b.setEnabled(on)
        if self.progress.isHidden() != idle:                # a run shown as a bar: turning until it counts videos
            # (`isHidden`, never `isVisible`: a run ending while the window is in its icon still hides its bar)
            self.progress.setRange(0, 0)
            self.progress.setVisible(not idle)
        if idle and (self._picture["want"] or not self.picture.isHidden()):     # its picture goes with the run
            self._picture.update(want=None, shown=None, run=self._picture["run"] + 1, at=None)
            self.picture.clear()
            self.picture.setVisible(False)

    def _risk_toggled(self, on):
        """The user's own tick: `youtube_risk_acknowledged` alone, through the settings service (never reverted by
        anything else: the Tk dashboard's save wrote its stale copy back, inv defect 1)."""
        self.shell.services.settings.set({"youtube_risk_acknowledged": bool(on)})
        if self.risk_item.isChecked() != bool(on):
            self.risk_item.setChecked(bool(on))
        if not on:                                          # taken back in ⋯: on the window again, beside the Download
            self.risk.setVisible(True)                      # ... it turns off
        self._sync()

    def language_changed(self, language):
        self._caption_for(language)

    # --- the runs: one `youtube` job each ------------------------------------------------------------------------ #
    def _start(self, kind, body, line, write=True):
        """`body(log, should_stop)` as a job: started by the registry when no other YouTube run goes, stopped by a
        cancel (the bar, the window's close, the app's quit). Its end comes back through a relay on the main window
        (it outlives this one)."""
        self.running = kind
        self.status.setTextFormat(Qt.TextFormat.PlainText)  # (the last run's link gone)
        if write:
            self.begin_write()
        self._write = write
        self.say(line)
        self._sync()
        stop = threading.Event()
        state = {"started": False}
        lines = self._lines.call
        on_complete = self.on_complete                      # the run's own (AD4-15)
        ends = bridge.Relay(parent=self.shell)
        ends.said.connect(lambda payload: self._ended(ends, payload))
        log = view.RunLog(None, kind)                       # its file is opened by the run's first line (AD4-5)
        self._last_log = log

        def start(job):
            state["started"] = True
            threading.Thread(target=run, args=(job,), name=f"youtube-{kind}", daemon=True).start()

        def cancel(_job):
            stop.set()
            if not state["started"]:                        # never started: its window still hears the end
                ends.call((kind, None, None, True, on_complete))

        def run(job):
            def said(text):
                text = str(text)
                if text.strip():
                    job.progress(text.strip())              # the bar's line while it runs
                lines(text)
            log.on_line = said
            result, error = None, None
            try:
                result = body(log, stop.is_set)
            except Exception as e:                           # said in the window, never raised into the thread
                error = str(e) or type(e).__name__
            finally:
                log.close()
            cancelled = stop.is_set()
            if error is not None:
                job.finish(ok=False, message=S.FAILED.format(why=error))
            else:
                job.finish(ok=True, cancelled=cancelled)
            ends.call((kind, result, error, cancelled, on_complete))
        self.job = self.shell.services.registry.submit(KIND, _LABELS[kind], start, cancel=cancel, on_quit="cancel")
        self._job_state = None
        self._follow(self.shell.services.registry.snapshot())

    def _follow(self, views):
        """While the run's job waits for another YouTube run, the line says so; once it runs, what it does."""
        job = self.job
        if job is None or self.gone:
            return
        view_ = next((v for v in views if v.id == job.id), None)
        if view_ is None or view_.state == self._job_state:
            return
        self._job_state = view_.state
        if view_.state == jobs_module.WAITING:
            self.say(S.WAITING)
        elif view_.state == jobs_module.RUNNING and self.status.text() == S.WAITING:
            self.say({"download": S.DOWNLOADING, "fill": S.FILLING, "update": S.UPDATING}.get(self.running, ""))

    def _line(self, line):
        """A line the run said: its count moves the bar (`… 4 of 12 videos read`), a written transcript shows by its
        name (`[ok] (manual) <name> [id].txt` → ✓ <name>); the whole line stays in the log."""
        if not (line and line.strip() and self.job is not None):
            return
        text = line.strip()
        counted = _COUNTED.match(text)
        if counted:
            done, total = int(counted.group(1)), int(counted.group(2))
            if total > 0 and (self.progress.maximum(), self.progress.value()) != (total, min(done, total)):
                self.progress.setRange(0, total)
                self.progress.setValue(min(done, total))
            # the download's count, said short beside its bar; the fill's line says why it pauses: said whole
            self.say(S.COUNTED.format(done=min(done, total), total=total) if counted.group(3) == "videos read"
                     else text)
            return
        written = _WRITTEN.match(text)
        if written and self.running == "download":
            self._show_video(written.group(2))
        self.say(S.WROTE.format(name=written.group(1)) if written else text)

    # --- the video it downloads (Mado-Y2: only with *Download covers* on) -------------------------------------------- #
    def _show_video(self, video_id):
        """The picture beside the bar becomes `video_id`'s thumbnail (a YouTube id; a bilibili one, or none, changes
        nothing) — asked of the covers' fetcher on a worker, one at a time and at most every `PICTURE_GAP_S`: the
        newest video asked meanwhile is the next one fetched, the ones between never asked (a playlist's transcripts
        come one after another). *Download covers* off, no library, or the fetcher already the next language's (the
        window's switch waits for its run): nothing asked, no picture."""
        if not video_id or video_id.startswith("bilibili-") or not core.video_id(f"https://youtu.be/{video_id}"):
            return
        if self.shell.services.settings.get().get("covers_download") is not True:
            return
        self._picture["want"] = video_id
        self._next_picture()

    def _next_picture(self):
        state = self._picture
        video_id = state["want"]
        if state["busy"] or video_id is None or video_id == state["shown"] or self.running != "download":
            return
        wait = 0 if state["at"] is None else PICTURE_GAP_S - (time.monotonic() - state["at"])
        if wait > 0:
            if not state["timer"]:
                state["timer"] = True
                QTimer.singleShot(round(wait * 1000) + 1, self.alive(self._gap_over))
            return
        make = getattr(self.shell, "cover_fetcher", None)
        fetcher = make() if callable(make) else None
        if fetcher is None or getattr(fetcher, "language", self.language) != self.language:
            return
        state["at"] = time.monotonic()
        from app import theme
        from app.qt import covers as qcovers
        state["busy"] = True
        run = state["run"]
        size, dpr = self.picture.size(), self.picture.devicePixelRatioF()
        bridge.run_in_worker(_video_picture, fetcher, video_id, self.language, size.width(), size.height(), dpr,
                             theme.RADII["cover-tile"], qcovers.decode,
                             then=self.alive(lambda image: self._pictured(run, video_id, image)),
                             failed=self.alive(lambda _info: self._pictured(run, video_id, None)))

    def _gap_over(self):
        self._picture["timer"] = False
        self._next_picture()

    def _pictured(self, run, video_id, image):
        """(The window's thread.) A thumbnail decoded — or None: off, offline, failed — shown while the run it was asked
        for still goes; then the next video asked meanwhile."""
        state = self._picture
        state["busy"] = False
        if run != state["run"] or state["want"] is None:   # its run ended meanwhile: nothing shown (the next run's
            self._next_picture()                            # ... video asked now)
            return
        state["shown"] = video_id
        if image is not None and self.running == "download":
            pix = QPixmap.fromImage(image)
            pix.setDevicePixelRatio(image.devicePixelRatio())
            self.picture.setPixmap(pix)
            self.picture.setVisible(True)
        elif image is None and not self.picture.isHidden():        # never another video's picture over this one
            self.picture.clear()
            self.picture.setVisible(False)
        self._next_picture()

    def _ended(self, relay, payload):
        try:
            relay.deleteLater()
        except RuntimeError:                                # gone with the main window already
            pass
        kind, result, error, cancelled, on_complete = payload
        if error is not None:
            line = S.FAILED.format(why=error)
        elif cancelled:
            line = S.STOPPED_KEPT.format(what=S.new_transcripts(len(result))) if result else S.STOPPED
        elif kind == "download":
            line = self._handed(result or [], on_complete)
        else:
            line = S.FINISHED
        if self.gone:                                       # the window closed meanwhile: the bar says it
            windows.say_in_bar(self.shell, line)
            return
        self.job = None
        self.running = None
        self.say(line)
        if self._write:
            self.end_write(line)
        self._sync()

    def _handed(self, created, on_complete):
        """The created files (only entries that weren't there before) to the run's `on_complete`, as the Tk window
        handed them to the Content Manager; no callback yet (W3.2): they wait in Processed, and the line says so."""
        if not created:
            return S.NONE_NEW
        if on_complete is None:
            return S.NEW_IN_PROCESSED.format(what=S.new_transcripts(len(created)))
        try:
            on_complete(list(created))
        except Exception as e:
            return S.FAILED.format(why=e)
        line = S.NEW_ROUTED.format(what=S.transcripts_handed(len(created)))
        if not self.gone and getattr(self.shell, "arrivals_tray", None) is not None:     # W3.2-2: links to the tray
            self.status.setTextFormat(Qt.TextFormat.RichText)
            return f'{html.escape(line)} <a href="arrivals">{html.escape(S.SEE_IN_ARRIVALS)}</a>'
        return line

    def _download(self):
        if self.running is not None or not self.risk.isChecked():
            return
        urls = view.links(self.links.toPlainText())
        if not urls:
            self.say(S.NO_LINKS)
            return
        language, caption = self.language, self.caption.currentData()
        self._start("download", lambda log, stop: view.run_extract(urls, language, caption, False, True, log,
                                                                   should_stop=stop), S.DOWNLOADING)
        self._show_video(next((v for v in map(core.video_id, urls) if v), None))      # the link's video, at once

    def _ask_backfill(self):
        if self.running is not None:
            return
        self.running = "scan"
        self._sync()
        self.say(S.SCANNING)
        language = self.language
        bridge.run_in_worker(view.pending_backfill, language, then=self.alive(lambda p: self._scanned(language, p)),
                             failed=self.alive(self._scan_failed))

    def _scan_failed(self, info):
        self.running = None
        self._sync()
        self.say(S.SCAN_FAILED.format(why=info[0]))

    def _scanned(self, language, pending):
        self.running = None
        self._sync()
        if not pending:
            self.say(S.NOTHING_TO_FILL)
            return
        n = len(pending)
        self.say("")
        confirm.ask(self, S.BACKFILL_ASK_TITLE,
                    S.BACKFILL_ASK_BODY.format(what=S.transcripts_without(n), batch=core.BATCH_SIZE,
                                               minutes=S.minutes(view.backfill_minutes(n))),
                    S.BACKFILL_YES.format(what=S.cue_times(n)), S.BACKFILL_YES_TIP, no_tip=S.BACKFILL_NO_TIP,
                    on_answer=lambda yes: self._backfill(yes, language))

    def _backfill(self, yes, language):
        if not yes or self.running is not None:
            return
        if language != self.language:                       # the question was this language's (AD4-14)
            self.say(S.FILL_LANGUAGE_CHANGED)
            return
        caption = self.caption.currentData()
        self._start("fill", lambda log, stop: view.run_backfill(language, caption, log, stop), S.FILLING)

    def _update(self):
        if self.running is not None:
            return
        self._start("update", lambda log, stop: view.run_update(log, should_stop=stop), S.UPDATING, write=False)

    # --- folders ------------------------------------------------------------------------------------------------- #
    def _open_folder(self):
        """The processed folder found and opened on a worker (`press.open`: never the window's thread), the window's
        corner arc turning meanwhile (a menu's press, IK-2: ⋯'s item since try a9.1)."""
        language = self.language
        qpress.open(self, lambda: view.processed_folder(language), key="youtube:folder",
                    failed=self.alive(lambda info: self.say(S.FOLDER_FAILED.format(why=info[0]))))

    def _open_log(self):
        """The log of the last run this window started (its path known once it wrote a line), else the newest of the
        actions' logs — looked for and opened on a worker (`press.open`); none yet says so (AD4-14)."""
        known = self._last_log.path if self._last_log is not None else None
        qpress.open(self, lambda: known or view.newest_log(), key="youtube:log",
                    then=self.alive(self._log_found),
                    failed=self.alive(lambda info: self.say(S.FOLDER_FAILED.format(why=info[0]))))

    def _log_found(self, path):
        if not path:
            self.say(S.NO_LOG)

    # --- its icon: X while it runs, Stop ------------------------------------------------------------------------- #
    def stoppable(self):
        return self.job is not None

    def stop_work(self):
        """Its icon's *Stop* (or the bar's Cancel): the run's job cancelled — the window stays, saying *Stopped*."""
        if self.job is not None:
            self.job.cancel()

    def closeEvent(self, event):
        """X while a run goes (try a9.1, Sonic: "if they X out of the youtube while it's going, shouldn't it either
        minimize or warn them?"): into its icon in the bottom bar, the run going on — the first time, the bar says how
        to stop it (its icon's right-click). Idle, or closed for good (the app's quit, its icon's *Close*): closed, and
        a run stopped (its job cancelled — nothing is started on a thread here, IK-28)."""
        if self.job is not None and not self.for_good and not self.gone:
            event.ignore()
            self.tuck_away()
            told = windows.main_of(self).__dict__.setdefault("_youtube_told_tucked", [False])
            if not told[0]:
                told[0] = True
                line = _RUNNING_WORDS.get(self.running, S.KEPT_DOWNLOADING)
                if callable(getattr(self.shell, "say", None)):
                    self.shell.say(line)                    # the bar's answer to what was just done: kept for its time
                else:
                    windows.say_in_bar(self.shell, line)
            return
        super().closeEvent(event)
        if event.isAccepted() and self.job is not None:
            self.job.cancel()


def _video_picture(fetcher, video_id, language, w, h, dpr, radius, decode):
    """(A worker.) A YouTube video's thumbnail as the window's picture: the covers cache's file (`video_cover`: cached,
    or fetched with *Download covers* on) decoded to w × h × dpr, cropped to fill it (hqdefault's letterbox bars fall
    outside a 16:9 box), its corners rounded as a tile's (`app/qt/covers.decode`). -> a QImage, or None."""
    path = fetcher.video_cover(video_id)
    if not path:
        return None
    out = decode((None, "youtube", video_id, path, False), "tile", w, h, dpr, language, None, radius, 0.5, 1.0, None)
    return out[0] if out else None


def open(shell, on_complete=None):
    """The downloader of `shell`: raised when open, else made and shown. `on_complete(paths)`: where the created files
    go (W3.2's arrivals); a later opener's callback replaces an earlier one for the next run (a run in flight keeps
    the one it started with)."""
    win = windows.show(shell, NAME, lambda s: DownloaderWindow(s, on_complete=on_complete))
    if on_complete is not None:
        win.on_complete = on_complete
    return win


# --- alpha 8 (Sonic's try): setup's *YouTube* — each link's first video, in the background ----------------------- #
def fetch_first(shell, urls, language, said, ended):
    """Setup's bring-in page: each link's one video (its own, or its playlist's first: `core.extract(first_only=True)`)
    fetched as a `youtube` job on a thread of its own (`_fetch`). On the window's thread: `said(line)` for each line it
    says, then `ended(created, problems)` — the new transcripts' paths and the plain-words lines of what went wrong
    (`view.problems`). -> the job."""
    caption = view.default_caption_language(language)
    return _fetch(shell, S.JOB_SETUP, lambda log, stop: view.run_extract(
        urls, language, caption, False, True, log, should_stop=stop, first_only=True), said, ended)


def _fetch(shell, label, work, said, ended, settle=None, automatic=False):
    """One background YouTube run (setup's first videos, a playlist's rest): `work(log, should_stop)` -> the created
    paths, run as a `youtube` job on a thread of its own — one yt-dlp run at a time with the downloader's, the bottom
    bar showing its last line ("… 12 of 44 videos read"), its Cancel and the app's quit stopping it (a stalled
    download ends itself: `core.STALL_S`). `settle(created, problems, stopped)`: on the run's thread before the job
    ends (the app's quit waits for that, never for the window's thread) — for a job cancelled before it started, on a
    thread of its own. Then, on the window's thread, `ended(created, problems)`; `said(line)` for each line.
    `automatic` (a playlist's rest): a user's own YouTube job asked for later goes first. -> the job."""
    stop = threading.Event()
    state = {"started": False}
    lines, ends = bridge.Relay(parent=shell), bridge.Relay(parent=shell)
    lines.said.connect(said)

    def end(payload):
        for relay in (lines, ends):
            try:
                relay.deleteLater()
            except RuntimeError:                            # gone with the main window already
                pass
        ended(*payload)
    ends.said.connect(end)

    def start(job):
        state["started"] = True
        threading.Thread(target=run, args=(job,), name="youtube-setup", daemon=True).start()

    def settled(created, found, stopped):
        if settle is not None:
            try:
                settle(list(created), found, stopped)
            except Exception as e:                           # (its record unwritten: the next start asks again)
                print(f"YouTube: a run's record couldn't be written: {e!r}")

    def cancel(_job):
        stop.set()
        if not state["started"]:                            # (A8P-9) its record is settled as a stop too
            threading.Thread(target=lambda: (settled([], [S.STOPPED], True), ends.call(([], [S.STOPPED]))),
                             name="youtube-unstarted", daemon=True).start()

    def run(job):
        heard = []

        def say(text):
            text = str(text)
            heard.append(text)
            if text.strip():
                job.progress(text.strip())
                lines.call(text.strip())
        log = view.RunLog(say, "download")
        created, error = [], None
        try:
            created = work(log, stop.is_set)
        except Exception as e:                               # said on the screen, never raised into the thread
            error = str(e) or type(e).__name__
        finally:
            log.close()
        found = view.problems(heard) + ([S.FAILED.format(why=error)] if error else [])
        if stop.is_set():                                   # (A8B-11) a stop is said as one, never as errors
            found = [S.STOPPED] if not created else found
        settled(created, found, stop.is_set())
        job.finish(ok=error is None, cancelled=stop.is_set(), message=S.FAILED.format(why=error) if error else None)
        ends.call((list(created), found))
    return shell.services.registry.submit(KIND, label, start, cancel=cancel, automatic=automatic, on_quit="cancel")


# --- alpha 8 (Sonic: "it should still get the whole playlist … in the background"): a playlist's rest ------------ #
def _runs(shell):
    """{language: its rest run under way} of one main window (kept on it: a window gone takes its runs with it)."""
    return shell.__dict__.setdefault("_youtube_rest", {})


def bring_in_rest(shell, language, playlists=()):
    """The rest of each playlist setup brought one video of (`playlists`: their links, `core.playlist_link`) — and of
    any an earlier run left unfinished — in the background: recorded first (`view.rest_update`, so a quit before it
    ran still resumes; transcripts no longer on disk dropped), then one automatic `youtube` job (`_fetch`: a user's own
    YouTube job asked for meanwhile goes first, the rest stopping for it and coming after) reading the videos not in
    the library's folder yet (`new_only`: the first video, what a stopped run fetched and what the learner removed are
    never read again), its line in the bottom bar. Each transcript is recorded as it is written; they go where the
    downloader's go (`windows.youtube_arrivals`: New arrivals, or placed by the user's rules), with the ones an earlier
    run wrote but never handed over. A run already under way takes the new ones after it. Called by setup (with its
    links) and at each start (none: the record's).

    How a run ends (PROVISIONAL, Mado-P): every video read -> done; Cancel in the bar -> the rest of it dropped
    (the YouTube window can bring it in any time); the app's quit -> goes on at the next start; no connection, YouTube
    refusing for now, a stall or a run past its time -> kept (at once again when it brought something; after
    `view.REST_TRIES` runs in a row that brought nothing, dropped and said)."""

    def recorded(state):
        if not state["playlists"] and not state["unrouted"]:
            return
        live = _runs(shell).get(language)
        if live is not None:
            live["again"] = True                            # its end starts the next run with the record
            return
        _run_rest(shell, language, state)
    bridge.run_in_worker(view.rest_update, language, list(playlists), (), (), (), True, then=recorded,
                         failed=lambda info: windows.say_in_bar(shell, S.REST_FAILED.format(why=info[0])))


def _run_rest(shell, language, state):
    playlists, unrouted = list(state["playlists"]), list(state["unrouted"])
    caption = view.default_caption_language(language)
    services = shell.services
    entry = {"again": False, "outcome": "done", "yielded": False}

    def yielding():
        """A user's own YouTube job waits for this one (a Download, a preview, setup's first videos): stop for it."""
        return any(not v.automatic and v.state == jobs_module.WAITING for v in services.registry.live(KIND))

    def work(log, stop):
        if not playlists:
            return []

        def stopping():
            if stop():
                return True
            if yielding():
                entry["yielded"] = True
                return True
            return False
        return view.run_extract(playlists, language, caption, False, True, log, should_stop=stopping, new_only=True,
                                written=lambda path: view.rest_update(language, unrouted=[path]))

    def settle(created, problems, stopped):
        closing = getattr(services, "closing", None)
        done, tried = (), ()
        if stopped:
            entry["outcome"] = "quit" if closing is not None and closing.is_set() else "cancel"
            done = playlists if entry["outcome"] == "cancel" else ()
        elif entry["yielded"]:
            entry["outcome"], entry["again"] = "yield", True
        elif view.rest_kept(problems, False):
            entry["outcome"] = "progress" if created else "wait"
            entry["again"] = entry["again"] or bool(created)
            tried = () if created else playlists
        else:
            done = playlists
        after = view.rest_update(language, done=done, unrouted=created, tried=tried,
                                 fruitful=playlists if created else ())
        spent = [p for p in tried if after["tries"].get(p, 0) >= view.REST_TRIES]
        if spent:
            view.rest_update(language, done=spent)
            entry["outcome"] = "spent"

    def ended(created, problems):
        runs = _runs(shell)
        if runs.get(language) is entry:
            runs.pop(language, None)
        paths = list(dict.fromkeys(list(created) + unrouted))
        why = _plain(next((p for p in problems if p != S.STOPPED), ""))
        tail = {"wait": S.REST_LATER.format(why=why), "quit": S.REST_LATER.format(why=S.REST_STOPPED),
                "spent": S.REST_SPENT.format(why=why, tries=view.REST_TRIES), "cancel": S.REST_CANCELLED,
                "yield": S.REST_YIELDED, "progress": S.REST_MORE}.get(entry["outcome"], "")

        def again(_state=None):
            if entry["again"] and entry["outcome"] != "quit":
                bring_in_rest(shell, language)

        def landed(waiting, placed, missed):
            windows.say_in_bar(shell, rest_line(windows.arrived_line(waiting, placed, missed), why, tail))
            bridge.run_in_worker(view.rest_update, language, (), (), (), paths, then=again,     # (A8P-11) the next
                                 failed=lambda info: print(f"YouTube: the rest's record: {info[0]!r}"))  # reads it after
        if paths:
            try:
                windows.youtube_arrivals(shell, then=landed, quiet=True)(paths)
                return
            except Exception as e:                           # no library, another one, read-only: said
                why = str(e)
        windows.say_in_bar(shell, rest_line("", why, tail))
        again()
    try:
        _fetch(shell, S.rest_job(max(1, len(playlists))), work, lambda _line: None, ended, settle=settle,
               automatic=True)
    except Exception as e:                                   # the registry refused it (at quit): the record keeps it
        windows.say_in_bar(shell, S.REST_FAILED.format(why=e))
        return
    _runs(shell)[language] = entry


def _plain(problem):
    """A run's problem line as the bar says it: without the link or the video it names (`could not read <link>: …`)."""
    text = str(problem or "")
    named = re.match(r"(?:could not read \S+|video [\w-]+|episode [\w-]+): (.+)$", text)
    return named.group(1) if named else text


def rest_line(arrived, why, tail):
    """The bottom bar's line once a playlist's rest ended: what came in (`windows.arrived_line`'s words), then why one
    didn't — or what happens next (`tail`: it waits for the next start, was cancelled, goes on…)."""
    head = S.REST_CAME.format(what=arrived) if arrived else ""
    end = tail or why
    if not head:
        return tail or (S.REST_NOTHING_BUT.format(why=why) if why else S.REST_NOTHING)
    return f"{head} · {end}" if end else head

"""Connect's loop (P2.4 Part A; ORDER P2.4; P1.5 02-data-model §2, §2a, §4; 06-edges E1–E32): `surasura-cli connect`
without `--consume-only`. For every job the inbox queued (P2.1) and every level job (P2.2), in top-20 order, the next
day's words first:

    sync → known-sync → re-plan (generate first only when the plan can't serve) → pick → fit check → mine →
    backfill → junban → [generate after mining → junban] → sync

- **Once a run, never per episode** (02 §4): the session's sync (`anki_session.begin`, P2.3: before Connect reads
  what you studied), one known-sync, then the plan's verdict (P3.3, K78: `replan.current`). A move or a placement of
  counted items is **re-planned** — mined and ordered from the engine's re-plan, no Generate in the loop; known words
  moved, new files placed (P4.1 C5) or the level raised alone → mined first (from the provisional re-plan, or the
  list as it is), then **one Generate after mining** and a follow-up re-order from its plan, the level look on the
  new run (F11, `_after_mining`); a changed file, a lowered level, no plan, another engine → one Generate first, as
  before (`generate`'s own "nothing changed"; a failed one → *Needs you* with its log, E29, and mining waits for a
  current list). Prepared per language, the first time a language has work.
- **One Anki Miner batch at a time** (E19), each job's words in one batch. **The carded set is read again for every
  pick** (P2.2 adversary #3: a word a higher job just carded is skipped — `pick.carded` asks Anki itself), together
  with every word Connect has ever made (the store's `made_words`, G1.3-4: a card you deleted is never made again).
  **The profile is pinned from pick to mine** (P1.3-AM37 #5): Anki Miner's active profile looked at again at mine
  time; another one → picked again.
- **Every step saved before and after** (02 §2; the ledger's `set_state`): a killed Connect resumes from the last
  saved step. A batch left `running` is in doubt: its notes are found by the job's tag first (E25, E14), recorded,
  and only the words still in doubt are tried again — once; a second failure → *Needs you*. Nothing is mined twice.
- **Waiting** (02 §2, one reason at a time): Anki closed (E1), you reviewing (E2, asked before each write), another
  profile (E3) — the session's `waiting` —, on battery (E32), Anki Miner open (E8), another program writing Anki: each
  may end while Connect runs, so it **stays running and looks again every 2 minutes** at below-normal priority (02
  §2a). No video (E15: a cloud placeholder is never opened), not timed (E16, named once in *Needs you*), a language
  Connect makes no cards in (E24; Chinese cards since Zh-C, 2026-11-12: `CARD_LANGUAGES`) and a setup Anki Miner lacks
  wait for the next start. Not timed (Michi-NT, Mattias #XP44T6): the same subtitle
  re-timed beside its video (tsubasa's own output) is checked in its copy's place and mined from when timed; a copy
  that changed since its check, or *Check again* (`actions.check_again`), lets it go again in this run. **It exits when no job is left**, or when every job left waits
  for the next start. **It never opens Anki** (Q4-16: only the window's *Open Anki for me*).
- **Never waiting with no window open** (Haya-CL, Mattias 3.0.2: "a bunch of surasura-cli.exe running after having
  closed Surasura"; lean, PROVISIONAL): those 2-minute looks go on only while a Surasura window is open (its running
  mark, `Steps.window_open`). When what is left only waits and no window is open — closed, crashed or killed — Connect
  exits instead of pausing, and a pause ends within UPDATE_LOOK_S of the last window closing; the window's next start
  (or hato's next hand-over) starts it again and the waits are read from the ledger as before. Work it can do now (a
  batch, a hato drop with the window closed) is still done first. And a Connect whose program folder now holds another
  build (`Steps.replaced`: Setup or a swap put a newer Surasura under it) stops at the next step boundary and starts the
  folder's own Connect (`connect_verbs._loop`): never an old version's Connect working on beside a new one.
- **An item that left the top 20** before mining → dropped; once mining started → it finishes (E18). A job of another
  store (the library set up again: a new `store_id`) is dropped before mining (P2.1 adversary #12). Never one carrying
  an ask, nor a level job beyond the line on 3.0 (P4.1 C3, C4: `inbox.keeps`).
- **Asks first** (P4.1 C3): a job carrying an ask (*Mine now*, *Mine this*, *Mine it too*) goes before the top 20,
  the newest ask first; only a job an ask made (kind `asked`) makes again a word whose card you deleted (N15, IK S1);
  one for a book or a text ends skipped with K67's line (IK S3).
- **A missing tool** (🧭 Q4-2, RD-S10): Anki Miner absent → the job `skipped`, named; Backfill or Junban absent → that
  step skipped and named on the job (`skipped`), the loop goes on.
- **An update staged** (E26): the run stops at the next step boundary (the command line refuses to start one) —
  between two Anki Miner batches of a job too, and within UPDATE_LOOK_S of its 2-minute pause (P3.1 row 3.1.8, K99:
  the update waits for Connect, never kills it; the ledger resumes the job where it stopped).
- **The store:** one short write a batch (`library.record_batch`: the receipt + the made words, role `connect`); a
  write the window holds past the store's 5 s waits for the next look.

Every Anki call runs through `Steps` (the command line's own verbs, in this process); a test hands its own. Wrapped by
`app/batch_gc.py` (CLAUDE.md §6): nothing here keeps a reference cycle per job.
"""
import datetime
import json
import logging
import os
import shutil
import time
from types import SimpleNamespace

from app import youtube_hold
from app.connect import fit_check, inbox, stopping
from app.connect.lineup import SPEECH_ASK, SPEECH_FAILED     # Stage B: the speech model's question
from app.connect.ledger import (ASKED, BEFORE_MINING, IN_FLIGHT, LEVEL, OPEN, PREPARE_KINDS, STOPPED_REASON,
                                Ledger)

log = logging.getLogger("surasura-cli")

LOOK_EVERY_S = 120              # 02 §2a: while every job waits on something outside Connect
OFFER_EVERY = 5                 # Kura-AB3 A2 r2 S4: the paired books looked at for *Add audio* at the first look and
                                # every this many after (about 10 min at LOOK_EVERY_S; by looks: no clock read)
UPDATE_LOOK_S = 5               # K99: inside that pause, an update staged is looked for this often
WAIT_S = 10.0                   # a verb's --wait inside the run (another Surasura writer, a Generate)
ALL_GONE_MIN = 10               # the deleted-card check: this many notes or more, all gone at once -> nothing marked

# The plain lines a waiting job shows (the status line's, never Needs you)
ON_BATTERY = "On battery: cards are made once this computer is plugged in."
ANKI_MINER_OPEN = "Anki Miner is open: close it to make cards."
# A2-6: told BUSY while Surasura's *Finish its setup* runs Anki Miner's setup (`anki_miner.setting_up`): nothing to close
SETTING_UP = "Anki Miner is finishing its setup: cards are made once it's done."
WRITER_BUSY = "Another program is writing to Anki."
SHELF_NO_JUNBAN = "The shelf is off: it needs Junban (順), which isn't installed. Connect waits at the cap."
REVIEWING = "Waiting while you review in Anki."
ANKI_CLOSED = "Waiting for Anki: it isn't open."
# A call to Anki that failed while Anki answers (one slow or refused request: laptop round 5 review A1) — that
# episode's own wait on Anki — one that clears by itself (a plain wait, never amber: `anki_needs_you`) — and never
# one that holds every episode
ANKI_SLOW = "Waiting for Anki: it didn't answer in time."
NO_VIDEO = "No video: its video isn't on this computer (or isn't downloaded yet)."
# Z-16 (Michi-AB A1/A5, PROVISIONAL): an audiobook's or a podcast's episode while Anki Miner mines audio — its audio file
# isn't found (`Steps.audio`), or one transcript spans several audio files (its lines can't be told apart by file)
NO_AUDIO = "No audio: its audio file isn't on this computer."
NO_TEXT = "Nothing to cut its cards from yet: this audiobook has no text of its own (its book's, or a question open)."
SEVERAL_FILES = ("One transcript for {n} audio files: Connect can't tell which file each line is in, so its cards "
                 "wait. A subtitle file for each audio file, named like it, is mined.")
# Michi-AB Stage B (AB-Q2/Q3, PROVISIONAL): a book paired with its audiobook waits while Anki Miner lines them up (its
# cards then come with their sentence audio); the row says so with *Stop* (`lining_up`: the feed's LINING_UP)
LINING_UP = "Lining up its audiobook…"
LINING_UP_FILE = LINING_UP + " file {k} of {n}"
LINING_UP_MODEL = LINING_UP + " downloading Anki Miner's speech model first"
LINING_UP_BATTERY = LINING_UP + " once this computer is plugged in"
LINING_UP_STOPPING = LINING_UP + " stopping"
LINING_UP_AFTER = LINING_UP + " after another book's (one at a time)"
LINING_UP_STOPPED = "Lining up its audiobook stopped: Mine now goes on from where it was."
CHECKING_MODEL = "Checking its timing… downloading Anki Miner's speech model first"
# AB-Q2: the speech model's one question (once for the language, a standing *Needs you* line every book waiting on it
# holds: `actions.speech_model` answers it) — and, its download failed, asked again with Anki Miner's reason
SPEECH_NEED = "speech-model"
LINEUP_PAIR = "lineup:"         # ledger meta: `lineup:<job id>` -> the pair a part waits on (its *Stop* reads it: B-9)
# AB-Q4: the one plain line of a book whose audiobook doesn't follow it closely, or skips passages (`lineup.partial_line`)
PARTIAL_NEED = "audiobook-partial"
# Mattias's field report (3.0.0, 2026-11-11 #5; PROVISIONAL words): a part Anki Miner stopped on twice — the job's
# reason (`status`'s `failed`, the row's *Try again*) and its *Needs you* line, which names the way on
MINE_FAILED = "Anki Miner stopped twice while making its cards"
MINE_FAILED_SAY = ("{title}: Anki Miner stopped twice while making its cards. Try again makes the rest; the cards "
                   "it made are kept.")
# … and when its runs failed for some words alone (`ALONE`, below): which words, and Anki Miner's own words for why
# (Anki's *cannot create note …* in the field; a clip ffmpeg couldn't cut reads the same way: review r3 N1). Michi-RM3:
# its own *Needs you* kind (MINE_REFUSED: *Skip this word* beside *Try again*, `actions.skip_refused`); and when Anki's
# answer is its fields check's "unknown reason" — a cloze state, proven on DevTest: a field holds cloze marks on a note
# type that isn't a cloze one — the line says so in plain words (PROVISIONAL words)
MINE_REFUSED = "mine-refused"
MINE_REFUSED_SAY = ("{title}: Anki Miner couldn't make the cards for {words} ({why}){hint}. Skip this word and the rest "
                    "of the part is done, and it's never asked again; Try again tries it once more. The cards it made "
                    "are kept.")
UNKNOWN_REASON = "cannot create note for unknown reason"     # AnkiConnect's words for a cloze state of Anki's check
CLOZE_HINT = (": a dictionary's text for this word looks like an Anki cloze ({{c1::…}}), and Anki refuses it on "
              "this note type")      # (Mattias found it: a grammar dictionary's example sentences, 2026-11-12)
FAILED_KINDS = ("mine-failed", MINE_REFUSED)
LINE_UP_FAILED = ("「{title}」: Anki Miner couldn't line it up with its audiobook ({why}), so its cards are made without "
                  "sentence audio.")
# Kura-AB2 (Mattias's 3.0.0 field report, issue 3; PROVISIONAL): a book about to be mined with no audiobook paired
# asks first — ONE standing *Needs you* question a book (its first part's need: every part held by its words,
# `feed.HELD`), *Pick its audiobook…* (the window pairs it: `Store.pick_audiobook_book`) · *Mine without audio*
# (`actions.book_audiobook`) · *Dismiss* (mined as the book). Its record and answer live in the ledger's meta, by
# language: `BOOK_ASKED<lang>:<item>` -> {key, epub} (the part it is asked by), `BOOK_SAID<lang>:<key>` -> the answer
# (`book_key`: the EPUB's sha256, else its path). Never a book already paired, never once the speech model was
# declined, never without Anki Miner's `sync`.
BOOK_AUDIO_NEED = "book-audiobook"
BOOK_AUDIO_ASK = ("Do you have 「{title}」's audiobook? Its cards can carry the narrator's voice: pick it, or mine the "
                  "book without audio.")
BOOK_ASKED, BOOK_SAID = "book_audio_asked:", "book_audio_said:"
# Kura-AB3 A2 (PROVISIONAL, spec `tracks/pipeline/work/AB3/add-audio-spec.md` L2): once a book first lines up with its
# audiobook, the cards Connect made from it before — text-only — are offered the narrator's voice: ONE standing *Needs
# you* line a book (on the audiobook's item, as AB-Q4's line), asked once (`ADD_AUDIO_ASKED<lang>:<book key>` -> {epub,
# item, title}, kept whatever the answer). *Add the narrator's voice* = `actions.add_audio` (`add_audio.act`). Asked at
# each paired book not asked yet, at `run`'s looks whatever the queue (`_add_audio_offers`, every OFFER_EVERY looks,
# the lead's MUST, Mattias's books were all mined before — no part is picked again), and at a part's own line-up. Its
# record keeps the book's Connect notes then (`notes`: made before it lined up, text-only) — the only ones offered. A press, from the line or the book row's ⋯,
# keeps the notes it looked at (`ADD_AUDIO_SEEN<lang>:<book key>` -> [note ids]): the row offers only the others.
ADD_AUDIO_NEED = "book-add-audio"
ADD_AUDIO_ASK = ("「{title}」 is lined up with its audiobook now — add the narrator's voice to the cards Connect made "
                 "from it before, where they have none?")
ADD_AUDIO_ASKED = "add_audio_asked:"
ADD_AUDIO_SEEN = "add_audio_seen:"
ADD_AUDIO_WAIT = ("「{title}」 has its audiobook now: the cards Connect made from it before can get the narrator's "
                  "voice — line it up and add it?")
ADD_AUDIO_WAITING, ADD_AUDIO_LINED, ADD_AUDIO_GONE = "waiting", "lined", "gone"   # the record's stage: offered
# before its line-up / after / it can't be lined up any more (its line fixed)
NO_AUDIOBOOK, DISMISSED = "none", "dismissed"     # *Mine without audio*; the card dismissed
# Iro-AA (PROVISIONAL): *Make AI audio (beta)* — mined as *Mine without audio*, then each part's new cards queued for the
# AI voice (`modules.irodori`, the beta: off by default, absent in a build without it) when the part fills
# (`_queue_ai_audio`, the job marked `AI_JOB<id>` at its pick), their audio made once the run's jobs are through
# (`_ai_audio`): only an empty SentenceAudio, through the shared writer, one Undo a part
AI_AUDIO = "ai"
AI_JOB = "ai_audio_job:"
# Kura-AB3 (PROVISIONAL): an audiobook's own timed subtitle lines its book up when its last cue ends inside the audio's
# length and this much (a subtitle of a longer cut is another recording's); its spot-check's answer of its own: *Trust
# my subtitles' timing* on (never listened to)
OWN_SLACK_S = 30.0
OWN_TRUSTED = "trusted"
# MV-2 (Sonic: yes, 2026-10-23): a source folder's episode whose video left the folder it was in, the source folder
# still there (`video_left`) — the same *No video* wait (`no_video`), its line naming the folder; the window's *Find
# its folder* adds the folder picked as a source, and the store's join (MV-1) does the rest
MOVED = "This episode's video isn't where it was ({folder})."
# E24: the languages Connect makes cards in — Chinese too since Zh-C (2026-11-12: Anki Miner 3.12's Chinese, Sonic's
# "Yes to the Chinese leans"). `CHINESE` is the reason a 3.0.x ledger's Chinese job may still carry: such a job is
# picked up again at Connect's next start like any waiting one
CARD_LANGUAGES = ("ja", "zh")
CHINESE = "Chinese cards come later."
# Laptop round 8 #47 (LF4-5 ⭐ A): a job you stopped waits for your next ask; the cards it made are kept
STOPPED_BY_YOU = STOPPED_REASON
# Laptop round 9 #56: an open job with no reason of its own while Connect works on another (`status` computes it for
# the record; never written to the ledger)
TURN = "Waiting its turn: Connect is making another episode's cards now."
# Laptop round 8 #49 (LF4-1 ⭐ A, PROVISIONAL): a level raise's job for an episode you've watched, or whose video is gone
WATCHED = "you've watched it: its new words go to the episodes ahead of you"
LEVEL_NO_VIDEO = "Its video isn't on this computer: its new words' cards wait for it."
# Alpha 4 M1 (Sonic 2026-10-27: "I honestly don't want to ever have to open anki miner. Ever."): until Anki Miner reads
# books (`anki_miner.mines`: round 2's Z-9), a book's or a text's job — Connect's own, an ask, a gap's — is set
# aside with this line (`_books_aside`): never picked, never a *No video* card, nothing on the circles. Once Anki Miner
# reads them, they're queued again by themselves (`ledger.reopen_skipped`): nothing to undo. K67's asked-only rule is
# this one now.
BOOKS_WAIT = "Waits for Anki Miner to read books: Connect makes its cards by itself once Anki Miner can."
# A4M1-3 (lean taken, PROVISIONAL): an audiobook's or a podcast's the same way, until Anki Miner mines audio (Z-16)
AUDIO_WAIT = "Waits for Anki Miner to mine audio: Connect makes its cards by itself once Anki Miner can."
WAIT_REASONS = {"books": BOOKS_WAIT, "audio": AUDIO_WAIT}       # `library.waits_for`'s kinds -> the job's line
# Z-9: a book or a text Anki Miner couldn't open (`SOURCE_UNREADABLE`, with its reason) — *Needs you*, plain: nothing
# here sends you to Anki Miner (alpha 4 M1); the job is tried again at Connect's next start
BOOK_UNREADABLE = "{title}: Anki Miner couldn't read this book or text ({why})."
UNKNOWN = "unknown"         # `Steps.waiting_items`: an audio item whose video can't be looked for now (never moved)
# Alpha 6 try #6: the list a Generate left unfinished (`verbs.UNFINISHED`) is a wait for the language, never *Needs
# you*: every episode waits with this line (`holds_every`), the next look prepares again (Connect Generates when no one
# else has) and a finished list ends it
NO_LIST = "Waiting for a current list: Generate didn't finish."
LIBRARY_BUSY = "Surasura's library is busy: tried again shortly."
STOPPED_FOR_UPDATE = "Surasura is installing an update."
ANKI_OFF = "Anki is switched off for this run (SURASURA_NO_ANKI_SYNC)."
NO_WORDS = "no words to make cards from"
SWITCHED_OFF = "Connect was switched off."
# Haya-CL: the program folder now holds another build (a newer Surasura installed under a running Connect)
REPLACED = "Surasura was updated: the new version's Connect takes over."
MINER_ABSENT = "Anki Miner isn't installed"
# ASK-SONIC P2.4-8 ⭐ (a): with your list in another language, Connect waits rather than replace it with its own
# Generate (False: it goes ahead, as before)
WAIT_FOR_OTHER_LIST = True
OTHER_LIST = "Waiting: your list is in {}. Cards are made once a Japanese list is current again."
LANGUAGE_NAMES = {"ja": "Japanese", "zh": "Chinese"}

# `Steps.order`'s answer when the plan can't serve the re-order now and the Generate after mining will (P3.3, F11)
DEFERRED = "deferred"

# Anki Miner's settled outcomes: a word with one of these is never sent again for the job
UNSETTLED = (None, "uncertain", "not_attempted")
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".webm", ".avi", ".m4v", ".mov", ".ts")
TS_MIN = 1 << 20                # a `.ts` under this size is TypeScript, not a video (K6, S9: by the listing's stat)


def mac_copy(name):
    """Is this a Mac's `._` copy (AppleDouble, on a NAS or exFAT drive: metadata, never a video or a text)? The one dot
    rule — Connect's video index and the library's look (`sources._listing`) both ask it; any other leading dot is a
    name (`.hack SIGN - 01.mkv`, a `.hack` folder). The folders a Mac makes are `library_store.SKIP_DIRS`'."""
    return name.startswith("._")


def video_name(name):
    """Can a file of this name be a video? One of VIDEO_EXTENSIONS, and never a Mac's `._` copy (`mac_copy`). The
    name's half of `video_file`, for a listing before its stat."""
    return not mac_copy(name) and name.lower().endswith(VIDEO_EXTENSIONS)


def video_file(name, size):
    """Is a listed file a video? `video_name`, and never a `.ts` under TS_MIN (TypeScript). `size`: the listing's stat,
    nothing read. Connect's video index (`videos._list`) reads it; the library's look and Needs you's video listing are
    to call it too (asked of their owners), so that what counts as a video file is one rule."""
    return video_name(name) and not (name.lower().endswith(".ts") and size < TS_MIN)
_PLACEHOLDER = 0x1000 | 0x40000 | 0x400000      # OFFLINE · RECALL_ON_OPEN · RECALL_ON_DATA_ACCESS (a cloud file)


class Wait(Exception):
    """A job waits: `reason` (plain words), `look` (True: it may end while Connect runs — look again in 2 minutes),
    `resume` (the step it goes on from; None: from the start)."""

    def __init__(self, reason, look=True, resume=None):
        super().__init__(reason)
        self.reason, self.look, self.resume = reason, look, resume


class Needs(Exception):
    """Something only you can fix: named once in *Needs you* (`kind`, `say`); the job waits for the next start.
    `whole`: the language's trouble, never the episode's (a setting, Anki Miner's setup, the library): recorded once
    for the language (no item), whatever the number of episodes it stops (alpha 6 try #6). `standing` (Michi-YT): the
    language's trouble recorded once as `whole` is (no item), but only the episodes it reaches wait on it (an online
    title's download: the others go on). `once` (Michi-YT): the episode's own trouble that stays as it is (a private
    video): counted once while it stands, never again at each start once seen (`Ledger.need(standing=)`)."""

    def __init__(self, kind, say, whole=False, standing=False, once=False):
        super().__init__(say)
        self.kind, self.say, self.whole, self.standing, self.once = kind, say, whole, standing, once


class Skip(Exception):
    """A step's tool isn't installed (`why`): the step is skipped and named."""

    def __init__(self, why):
        super().__init__(why)
        self.why = why


class Repick(Exception):
    """What the words were picked for changed (Anki Miner's profile, the pairing): pick again."""


class _Again(Repick):
    """Pick again from the same subtitle in other bytes (`_fit`) — the one beside its video (Michi-NT), or its library
    copy re-timed by tsubasa (Michi-NT2) — never a change of what the words were picked for: it counts as none of
    `_job`'s re-picks (each at most once a pass: `_fit` never switches from the file beside, a job is re-timed once)."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(loaded, languages, steps=None, ledger=None, sleep=None, cancel=None, looks=None):
    """The loop, until no job is left (or every job left waits for the next start) -> a summary per language:
    {"done", "dropped", "skipped", "failed": [item ids], "waiting": {item id: reason}, "needs": [say, …]}, plus
    "looks" and, when it stopped early, "stopped". `looks`: at most this many looks (tests); `cancel`: an Event;
    `sleep`: a test's own pause, called once with the whole of it (default: `time.sleep` in UPDATE_LOOK_S steps,
    ended early by an update staged)."""
    steps = steps or Steps(loaded, live=True)
    steps.lower_priority()
    _sweep_online(steps)                    # Michi-YT: a video a killed Connect left goes before anything else
    _release_check(loaded)
    own = ledger is None
    ledger = ledger or Ledger()
    summary = {"languages": {lang: _empty() for lang in languages}, "looks": 0}
    for lang in languages:                  # F9: a crash's *updating your list* mark is cleared by the next run
        _updating(ledger, lang, False)
        _working(ledger, lang, False)       # alpha 3 A2: and its *working through the episodes* mark
    prepared = set()            # the languages whose sync, known-sync and Generate ran this run (02 §4: once)
    begun = set()               # the languages this run has worked on (the status line's *i of n* counts from then)
    undos_looked = set()        # the languages whose half-done undos this run has finished (once a run)
    parked = {}                 # jobs waiting for the next start: never tried again this run (adversary P2.4-A #11)
                                # — {job id: its ask when parked}; a newer ask tries it again (#42, review r42 #3)
    try:
        while True:
            summary["looks"] += 1
            _woken(steps, ledger, parked)   # a kick before this look is answered by it: no extra look after (S19)
            _copy_changed(ledger, parked)   # Michi-NT: a not-timed episode's subtitle fixed meanwhile
            outside = work = battery = unread = False
            for lang in languages:
                stop = _stop(steps)
                if stop:
                    summary["stopped"] = stop
                    return summary
                if _consume(steps, ledger, lang):
                    outside = work = unread = True      # the inbox couldn't be read: looked at again, never lost
                if lang not in undos_looked:    # an undo a kill left half-way: finished whatever else runs (#5)
                    undos_looked.add(lang)
                    _finish_undos(steps, ledger, lang)
                if (summary["looks"] - 1) % OFFER_EVERY == 0:     # Kura-AB3 A2 r2 B1: whatever the queue
                    _add_audio_offers(steps, ledger, lang)          # (a book mined out has no job)
                if not _open_jobs(ledger, lang, parked):
                    _gone_look(steps, lang)     # nothing to mine: the deleted-cards look all the same (once a run)
                    continue
                work = True
                if lang not in begun:
                    ledger.mark_run(lang)
                    begun.add(lang)
                out = summary["languages"][lang]
                earlier, out["waiting"] = out["waiting"], {}    # this pass's waits alone, then added to the run's
                try:
                    outside |= _language(steps, ledger, lang, prepared, parked, out)
                finally:
                    _working(ledger, lang, False)   # the pass ended: what is left waits for the next look (A2)
                battery |= ON_BATTERY in out["waiting"].values()
                out["waiting"] = {**earlier, **out["waiting"]}
                _said(steps, lang, out)
                stop = _stop(steps)                 # staged or switched off while its jobs ran: this step boundary
                if stop:
                    summary["stopped"] = stop
                    return summary
            if summary.get("stopped"):
                break
            if looks is not None and summary["looks"] >= looks:
                break
            if not work or not outside:
                # nothing to look at again — unless a kick came during this pass (a video linked while Connect mined
                # another episode: Michi-VF review B1) and let a parked job go: then one more pass, never an exit
                # that leaves it parked for a start no one makes (a link puts nothing in the inbox)
                if not (_woken(steps, ledger, parked) and any(_open_jobs(ledger, lang, parked) for lang in languages)):
                    break
                continue
            if not _window_open(steps):
                # Haya-CL: what is left only waits and no Surasura window is open: Connect ends here, never a
                # surasura-cli.exe looking every 2 minutes for hours after the window closed; the window's next start
                # (or hato's next hand-over) starts it again, and the ledger keeps every wait
                summary["no_window"] = True
                if unread:
                    summary["inbox_unread"] = True      # `connect_verbs._loop`: no start again for its pending inbox
                log.info("Connect: what is left waits and no Surasura window is open: it stops until the next start")
                break
            if not _pause(LOOK_EVERY_S, sleep, cancel, lambda: steps.update_staged() or _plugged_in(steps, battery)
                          or _woken(steps, ledger, parked) or _replaced(steps) or not _window_open(steps)):
                summary["stopped"] = "cancelled"
                break
        return summary
    finally:
        if own:
            ledger.close()
        try:
            steps.settle()                  # a pending sync is sent before Connect exits (P2.3)
        except Exception:
            log.exception("Connect's pending sync wasn't sent")
        _sweep_online(steps)                # Michi-YT: no downloaded video outlives the run
        if hasattr(steps, "_woken"):        # the last wake mark it read: one written since (a link while it settled,
            summary["wake_seen"] = steps._woken     # Michi-VF review r2) starts the next Connect (`connect_verbs._loop`)


def _release_check(loaded):
    """P3.2-AMN: Anki Miner's once-a-day release check (`am_release`): its attempt saved here, then GitHub asked on a
    daemon thread: mining never waits on it (Connect's exit gives it what is left of 5 s + 1 s, `connect_verbs._loop`).
    Preview off, not due → no thread. -> the thread or None."""
    try:
        from app.connect import am_release
        return am_release.start(loaded)
    except Exception:
        log.exception("Anki Miner's release check wasn't started")
        return None


def _said(steps, lang, out):
    """What the shelf did this run, in the run's summary (intent keeper P2.4-B #1, S16: an automation is seen)."""
    said = (getattr(steps, "said", None) or {}).get(lang)
    if said:
        out["shelf"] = list(said)
    aside = (getattr(steps, "stood_aside", None) or {}).get(lang)
    if aside:                               # P4.1 C8: the order step stood aside for a deck you put back
        out["stood_aside"] = aside


def _stop(steps):
    """Why the run stops at this step boundary, or None: an update staged (E26), Connect switched off (S16, D29: read
    again at every look and before each job, adversary P2.4-A #3)."""
    if steps.update_staged():
        return STOPPED_FOR_UPDATE
    if not steps.enabled():
        return SWITCHED_OFF
    if _replaced(steps):
        return REPLACED
    return None


def _replaced(steps):
    """Haya-CL: does this Connect's program folder hold another build now (`Steps.replaced`)? A stand-in without
    the look, or a look that fails, says no (logged)."""
    replaced = getattr(steps, "replaced", None)
    if replaced is None:
        return False
    try:
        return bool(replaced())
    except Exception:
        log.warning("Connect couldn't look at its program's build; it goes on", exc_info=True)
        return False


WINDOW_KINDS = ("window", "dashboard", None)      # app_entry's mark kinds of a start that opens a window (None: a
                                                    # record not written yet — a window just starting counts as one)


def _a_window(kind):
    """Is a running mark of `kind` a window's? The 3.0 window ("window"), the 2.x Tk window ("dashboard"), and a
    window started with a flag (`Surasura.exe --hud`: app_entry names the mark after its first argument)."""
    return kind in WINDOW_KINDS or (isinstance(kind, str) and kind.startswith("-"))


def _window_open(steps):
    """Haya-CL: is a Surasura window open (`Steps.window_open`)? Only then does Connect wait out its 2-minute looks.
    A stand-in without the look, or a look that fails, says yes (logged): the wait as before 3.0.3, never an exit
    that leaves work for nobody."""
    window_open = getattr(steps, "window_open", None)
    if window_open is None:
        return True
    try:
        return bool(window_open())
    except Exception:
        log.warning("Connect couldn't look for an open window; it waits as before", exc_info=True)
        return True


def _consume(steps, ledger, lang):
    """The inbox and the level raise's look, and the jobs skipped for want of Anki Miner queued again once it's there
    (intent keeper P2.4-A #11) -> True when it failed (a busy or read-only store, a ledger error: looked at again;
    adversary P2.4-A #5)."""
    try:
        steps.consume(lang, ledger)
        if ledger.skipped_for(lang, MINER_ABSENT) and steps.miner_found():
            line = steps.mine_line(lang)
            with ledger.transaction():
                ledger.reopen_skipped(lang, line, MINER_ABSENT)
        _books_aside(steps, ledger, lang, ledger.jobs(lang, states=OPEN))
    except Exception:
        log.exception("Connect couldn't read its inbox (%s); it looks again", lang)
        return True
    return False


def _books_aside(steps, ledger, lang, jobs, reopen=True):
    """Alpha 4 M1 / A4M1-3: for each kind Anki Miner can't mine yet (`steps.mines`: books and texts, audio), each of
    `jobs` still before its mining (queued, waiting, or left mid-pick by a kill: `_resume_of` in BEFORE_MINING, no batch
    started) whose item is of that kind (`steps.waiting_items`: `library.waits_for`, the rows' rule too) ends `skipped`
    with its line (`WAIT_REASONS`), before any pick — so it is no open job, no *No video*, nothing on the circles; once
    it can, every job set aside for that kind is queued again (its ask kept; one beyond the line is dropped at its start
    as any). -> how many set aside. A store busy now: none set aside, none queued again (looked at again next look);
    `reopen` False (a job's own start): only the setting aside (round 2 R2-2)."""
    mines, kinds_of = getattr(steps, "mines", None), getattr(steps, "waiting_items", None)
    if mines is None or kinds_of is None:
        return 0
    waiting = {kind for kind in WAIT_REASONS if not mines(lang, kind)}
    if reopen and any(ledger.skipped_for(lang, reason) for reason in WAIT_REASONS.values()):
        # every job set aside whose item no longer waits for that kind is queued again — its kind mined now, its
        # title's type corrected, its video found (review A2-2): nothing to undo
        aside = {}
        for j in ledger.jobs(lang, states=("skipped",)):
            for kind, reason in WAIT_REASONS.items():
                if j.get("reason") == reason:
                    aside.setdefault(kind, set()).add(j["item_id"])
        still = kinds_of(lang, set().union(*aside.values())) if aside else {}
        for kind, ids in aside.items() if still is not None else ():      # a busy store: every job stays aside
            back = [i for i in ids if kind not in waiting or still.get(i) not in (kind, UNKNOWN)]
            if back:
                with ledger.transaction():
                    ledger.reopen_skipped(lang, back, WAIT_REASONS[kind])
    if not waiting:
        return 0
    jobs = [j for j in jobs if _resume_of(j) in BEFORE_MINING and not _started(ledger, j["id"])]
    kinds = (kinds_of(lang, {j["item_id"] for j in jobs}) if jobs else None) or {}
    n = 0
    for job in jobs:
        kind = kinds.get(job["item_id"])
        if kind in waiting:
            reason = WAIT_REASONS[kind]
            ledger.set_state(job["id"], "skipped", reason=reason, skipped={"mining": reason})
            n += 1
    return n


def _open_jobs(ledger, lang, parked, tried=()):
    """The open jobs this pass may try: never one `tried`, nor one parked for the next start — unless you asked for it
    since it was parked (a *Mine now* on it: your press tries it again in this run, laptop round 7 #42)."""
    return [j for j in ledger.open_jobs(lang)
            if not (j["id"] in parked and parked[j["id"]] == j.get("asked_at")) and j["id"] not in tried
            and not ledger.held_by_stop(j)]     # laptop round 8 #47: one you stopped waits for your next ask


def _empty():
    return {"done": [], "dropped": [], "skipped": [], "failed": [], "waiting": {}, "needs": []}


def _pause(seconds, sleep, cancel, staged):
    """The pause between looks -> False when cancelled. Looks for an update staged every UPDATE_LOOK_S and ends at
    once when one is (the loop's next `_stop` names it): the update waits seconds for a sleeping Connect, never 2
    minutes (K99). A test's own `sleep` (no `cancel`) is called once, with the whole pause."""
    if cancel is None and sleep is not None:
        sleep(seconds)
        return True
    wait = cancel.wait if cancel is not None else time.sleep
    waited = 0
    while waited < seconds:
        step = min(UPDATE_LOOK_S, seconds - waited)
        if wait(step):
            return False                # the Event set (time.sleep answers None)
        waited += step
        if staged():
            break
    return True


def _plugged_in(steps, battery):
    """Episodes wait on battery and the plug is back: the pause ends now, so the next look mines them first, in order,
    within seconds (laptop round 5 #34; `_pause` asks every UPDATE_LOOK_S), never after the 2-minute look. `battery`:
    the pass that just ended left one waiting on battery (its own summary: no ledger read in the pause, S19,
    IK-r2-8). A power look that fails is no wake (logged): the run goes on (R2-10)."""
    on_battery = getattr(steps, "on_battery", None)
    if not battery or on_battery is None:
        return False
    try:
        return not on_battery()
    except Exception:
        log.warning("Connect couldn't look at the power; the pause goes on", exc_info=True)
        return False


def _kicked(steps):
    """Was Connect kicked during the pause (a *Mine now*, a placement, a setting that lets waiting episodes go:
    `kick.kick` stamps its wake mark when Connect already runs)? The pause ends, so the next look reads the ask within
    seconds, never at the 2-minute look (laptop round 7 #42). A look that fails is no wake (logged)."""
    kicked = getattr(steps, "kicked", None)
    if kicked is None:
        return False
    try:
        return kicked()
    except Exception:
        log.warning("Connect couldn't look at its wake mark; the pause goes on", exc_info=True)
        return False


def _woken(steps, ledger, parked):
    """`_kicked`, and a kick that may have found videos (`kick.VIDEOS`: a look that recorded videos while an episode
    waits on one — *Find its folder…*'s) lets the jobs parked on their video go again this run: a Connect running for
    other jobs tries them at its next look, never only at its next start. Any other kick (a *Mine now*, a placement,
    a setting) leaves them parked (S19: no stat of a dead share per episode per drag). -> whether it was kicked."""
    from app.connect import kick
    woke = _kicked(steps)
    if not woke:
        return False
    # an answer that queued a parked job again (Stage B: the speech model's question, a restarted line-up) lets it go
    # again this run — never a job still waiting as it was parked
    for job_id in [j for j in parked if (ledger.job_by_id(j) or {}).get("state") == "queued"]:
        del parked[job_id]
    if woke != kick.VIDEOS:
        return True
    for job_id in [j for j in parked if no_video((ledger.job_by_id(j) or {}).get("reason"))]:
        del parked[job_id]
    return True


def _ordered(jobs, line):
    """The open jobs: those carrying an ask first, the newest ask first (*Mine now*, *Mine this*, *Mine it too*: P4.1
    C3); then the top 20's order (the next day's words first); then the rest oldest first (a level raise's beyond the
    line — the rest of Current, then Goal — in the order it queued them, C4)."""
    from app.connect.ledger import stamp_key
    place = {item_id: n for n, item_id in enumerate(line)}
    asked = sorted((j for j in jobs if j.get("asked_at")), key=lambda j: (stamp_key(j["asked_at"]), -j["id"]),
                   reverse=True)
    rest = sorted((j for j in jobs if not j.get("asked_at")), key=lambda j: (place.get(j["item_id"], len(place)),
                                                                              j["id"]))
    return asked + rest


def _waiting_all(ledger, lang, parked, out, reason, look, tried=()):
    """Every open job waits with `reason` — but one waiting for its video keeps that, its own wait (review IK #5), and
    one `tried` this pass keeps the wait it was given (an asked job's ANKI_SLOW on battery: R2-4, IK-r2-7)."""
    for job in _open_jobs(ledger, lang, parked, tried):
        if job["state"] == "waiting" and no_video(job.get("reason")):
            out["waiting"][job["item_id"]] = job["reason"]
            continue
        _wait(ledger, job, Wait(reason, look, _resume_of(job)), out, parked)
    return look


def _language(steps, ledger, lang, prepared, parked, out):
    """Every open job of one language, once -> True when one waits on something outside Connect (look again). The top
    20 and the inbox are read again before each job (adversary P2.4-A #2): an episode moved out mid-burst is dropped,
    a new first one goes next."""
    if lang not in CARD_LANGUAGES:      # E24: a language Connect makes no cards in waits (none since Zh-C)
        return _waiting_all(ledger, lang, parked, out, CHINESE, False)
    wait = store_now = None
    only_asked = False          # on battery with a *Mine now* waiting: this pass mines the asked ones alone (M-3)
    try:
        wait = _blocked(steps, lang, None)
        if wait is not None and wait.reason == ON_BATTERY and any(j.get("asked_at") for j in
                                                                  _open_jobs(ledger, lang, parked)):
            only_asked = True
            wait = _blocked(steps, lang, None, asked=True)
        if wait is None:
            with _held():                   # two store reads, one open
                steps.mine_line(lang)       # the store answers first: never an empty top 20 for a busy one
                store_now = steps.store_id(lang)
            if lang not in prepared:
                steps.prepare(lang, ledger)
                prepared.add(lang)
                _fixed(ledger, lang, kinds=PREPARE_KINDS)     # the sync, known-sync and Generate went through
    except Wait as w:
        wait = Wait(w.reason, w.look)       # its fields only: never the caught exception's frame (#17)
    except Needs as n:
        if ledger.need(lang, n.kind, n.say):
            out["needs"].append(n.say)
        wait = Wait(n.say, look=False)
    if wait is not None:
        return _waiting_all(ledger, lang, parked, out, wait.reason, wait.look)
    outside = False
    tried = set()
    look = False                # the inbox and the level looked at again before the next job (after a job, or F11)
    while True:
        if look and _consume(steps, ledger, lang):
            outside = True
        jobs = _open_jobs(ledger, lang, parked, tried)
        if not jobs:
            # B-6: the episodes are through — the Generate after mining and F11's re-order are no episode's turn (a job
            # the window queues meanwhile never reads "Connect is making another episode's cards"); the next job marks
            # it again
            _working(ledger, lang, False)
            if _after_mining(steps, ledger, lang, out, on_battery=only_asked):
                look = True     # the level look on the new run: the jobs it queued run in this run (no second prepare)
                continue
            if not only_asked and _ai_audio(steps, ledger, lang, parked, tried):
                look = True     # Iro-AA: a part came in while the AI voice worked: it goes first, the voice after
                continue
            break
        failed = None
        try:
            line = steps.mine_line(lang)
        except Wait as w:
            failed = (w.reason, w.look)
        except Needs as n:
            if ledger.need(lang, n.kind, n.say):
                out["needs"].append(n.say)
            failed = (n.say, False)
        if failed is not None:
            return _waiting_all(ledger, lang, parked, out, failed[0], failed[1], tried) or outside
        job = _ordered(jobs, line)[0]
        if only_asked and not job.get("asked_at"):     # the asked ones are mined: the rest still wait for the plug
            return _waiting_all(ledger, lang, parked, out, ON_BATTERY, True, tried) or outside
        tried.add(job["id"])
        look = True
        _working(ledger, lang, True)        # alpha 3 A2: the ones behind wait their turn, between two episodes too
        try:
            _job(steps, ledger, lang, job, store_now, set(line), out)
            ended = ledger.job_by_id(job["id"]) or {}
            if ended.get("state") in ENDED:     # its troubles went, but a step it ended without (Backfill…) stands
                keep = _skipped_says(ended)
                if ended.get("kind") == LEVEL:  # Mattias #5: a level raise says nothing of a failed part's words
                    keep |= _failed_says(ledger, lang, job["item_id"])
                elif ended.get("state") in ("done", "undone"):  # Michi-RM2: the part went through: its records go
                    _forget_alone(ledger, lang, job["item_id"])     # (never skipped: reopened; nor dropped: unmined)
                keep |= _add_audio_says(ledger, lang, job["item_id"])     # Kura-AB3 A2 r1 S6: the book's line stays
                _fixed(ledger, lang, item_id=job["item_id"], keep=keep)
                _book_orphans(ledger, lang)    # Kura-AB2: a book's question no part waits on any more
        except Wait as w:
            _wait(ledger, job, w, out, parked)
            outside |= w.look
            if w.reason == NO_LIST and ("again", lang) not in prepared:
                # the next look prepares again: Connect Generates if no one else has — once a run (a list that stays
                # unfinished after it waits for the next Generate, never a Generate every look)
                prepared.discard(lang)
                prepared.add(("again", lang))
            if holds_every(w.reason):
                # on battery, or a wait on Anki: every episode keeps its place and the next look starts from the top
                # (laptop round 5 #24) — never a later one (or the next show) before the one that waited
                return _waiting_all(ledger, lang, parked, out, w.reason, w.look, tried) or outside
        except Needs as n:
            if _need(ledger, lang, n, job):
                out["needs"].append(n.say)
            _wait(ledger, job, Wait(n.say, look=False, resume=_resume_of(ledger.job_by_id(job["id"]))), out, parked)
            if n.whole:                     # the language's trouble: every episode waits on it, named once
                return _waiting_all(ledger, lang, parked, out, n.say, False, tried) or outside
        except Exception as e:              # R15: a fault of one job never ends the run nor hides it
            log.exception("Connect's job %s stopped on an error", job["id"])
            say = f"Connect stopped on an error while making an episode's cards ({type(e).__name__}): {e}"
            if ledger.need(lang, "error", say, item_id=job["item_id"], job_id=job["id"]):
                out["needs"].append(say)
            _wait(ledger, job, Wait(say, look=False, resume=_resume_of(ledger.job_by_id(job["id"]))), out, parked)
        finally:
            if not _looks_again(ledger, job, parked):
                _drop_online(steps, job)    # Michi-YT: its downloaded video goes however the job ended (a re-mine
            #                                 downloads it again) — kept only for a wait this run looks at again
        if _stop(steps):
            break
    return outside


def _after_mining(steps, ledger, lang, out, on_battery=False):
    """F11 (P3.3): this run mined from a plan that waits for a Generate (known words moved, or the level raised
    alone) — once the language's jobs have run this pass (done, or waiting): the Generate, the plan read again, one
    follow-up re-order from it (the re-sort owed until it lands) -> True when the Generate went through (the loop's
    next look is the level look on the new run). Never while stopped (an update staged, switched off — looked at
    again after the Generate, before the follow-up writes Anki); once a run (the mark is the steps'). A Generate that
    waits or fails leaves the re-sort owed; mining is already done. `on_battery`: the pass mined the asked jobs alone
    (M-3) — a *Mine now* press is the yes for its episode's cards, never for the Generate (D-r2-1 a, Sonic's lean):
    not started, it stays owed — the steps' mark, for a later pass of this run with jobs to run once plugged in; the
    next run's plan (`replan.current`) marks it again until a Generate lands — and its follow-up re-order with it, as
    that re-order waits for the plug."""
    after = getattr(steps, "generate_after", None)
    if after is None or on_battery or _stop(steps):
        return False
    try:
        ran = after(lang, ledger)
    except Wait as w:
        log.info("Connect: the Generate after mining waits (%s): %s", lang, w.reason)
        ran = None
    except Needs as n:
        if ledger.need(lang, n.kind, n.say):
            out["needs"].append(n.say)
        ran = None
    except Exception:                       # mining is done: a fault here never ends the run (R15)
        log.exception("Connect's Generate after mining stopped on an error (%s)", lang)
        ran = None
    if ran is False:
        return False
    try:
        with ledger.transaction():
            ledger.owe_resort(lang)         # the follow-up re-order: owed until it lands (the next job's step pays it)
    except Exception:                       # R15: a ledger fault here never ends the run (final adversary #3)
        log.exception("Connect couldn't mark the re-sort owed after its Generate (%s)", lang)
    if ran is None:
        return False
    if _stop(steps):                        # switched off or an update staged during the Generate: no Anki write
        return False                        # (S16, D29, E26) — the re-sort stays owed
    _follow_up(steps, lang, ledger)
    return True


def _follow_up(steps, lang, ledger):
    """F11's one re-order from the Generate's new plan (a move made meanwhile is served at its time). Anki closed, a
    review, a skip or a failure: the re-sort stays owed."""
    try:
        if _blocked(steps, lang, None) is not None:
            return
        deferred = steps.order(lang, None) == DEFERRED
    except (Wait, Needs, Skip) as e:
        log.info("Connect: the follow-up re-order waits (%s): %s", lang, e)
        return
    except Exception:
        log.exception("Connect's follow-up re-order stopped on an error; the re-sort stays owed")
        return
    if not deferred:
        try:
            with ledger.transaction():
                ledger.resort_paid(lang)
        except Exception:                   # R15: logged, the run goes on; the re-sort stays owed (#3)
            log.exception("Connect couldn't mark the re-sort paid (%s); it stays owed", lang)


# A job that ended one of these ways took its item's needs with it (03 §4: fixed by itself); `failed` just named one
ENDED = ("done", "dropped", "skipped", "undone")


def _fixed(ledger, lang, kinds=None, item_id=None, keep=()):
    """Needs whose cause went away (03 §4), each named once in the log -> how many."""
    rows = ledger.fix(lang, kinds=kinds, item_id=item_id, keep=keep)
    for row in rows:
        log.info("Connect: fixed by itself (%s, %s): %s", lang, row["kind"], row["say"])
    return len(rows)


# The language's needs (`Needs.whole`) each step's going through fixes: a list read, Anki Miner set up, Backfill's
# and 順's deck chosen (alpha 6 try #6: each named once, gone once it works)
# (mining: Anki Miner's own needs too, `verbs._MINER_CODES`' — its setup among them, `fields.NeedsYou`'s kind)
WHOLE_STEPS = {"picking": ("list-unreadable", "no-store", "known-words-unreadable", "mine-words-setting"),
               "mining": ("anki-refused",), "recording": ("no-store",), "filling": ("backfill-deck",),
               "ordering": ("junban-deck",)}
# The words an alpha 6 Connect recorded once per episode for these (`verbs`' constants): fixed as the step goes through
OLD_SAYS = {"picking": ("UNFINISHED",), "filling": ("BACKFILL_ONE_DECK",), "ordering": ("JUNBAN_ONE_DECK",)}


def _need(ledger, lang, need, job):
    """`need` recorded -> True when it counts (`Ledger.need`): the episode's own, or once for the language
    (`Needs.whole`: no item); the copies an earlier Connect recorded per episode go (`_fixed_said`)."""
    if getattr(need, "standing", False) and not need.whole:
        return ledger.need(lang, need.kind, need.say, job_id=job["id"], standing=True)     # Michi-YT: once
    if not need.whole:
        return ledger.need(lang, need.kind, need.say, item_id=job["item_id"], job_id=job["id"],
                           standing=bool(getattr(need, "once", False)))
    _fixed_said(ledger, lang, (need.say,))
    return ledger.need(lang, need.kind, need.say, standing=True)     # a state: never counted again while it stands


def _through(ledger, lang, step):
    """`step` went through: the language's needs it fixes (WHOLE_STEPS) fixed by themselves, and the per-episode
    copies an alpha 6 Connect recorded of them (OLD_SAYS: *Generate didn't finish* — a wait now — and the decks)."""
    from app.cli import verbs
    kinds = WHOLE_STEPS[step]
    if step == "mining":
        kinds += tuple(f"anki-miner-{kind}" for kind, code in verbs._MINER_CODES.items() if code == "needs-you")
    _fixed(ledger, lang, kinds=kinds)
    _fixed_said(ledger, lang, tuple(getattr(verbs, name) for name in OLD_SAYS.get(step, ())))


def _fixed_said(ledger, lang, says):
    for row in ledger.fix_said(lang, says):
        log.info("Connect: fixed by itself (%s, %s, item %s): %s", lang, row["kind"], row["item_id"], row["say"])


def _failed_says(ledger, lang, item_id):
    """The words of the item's open *Anki Miner stopped* lines (Mattias #5): only a new try of its words ends them."""
    return {r[0] for r in ledger.conn.execute("SELECT say FROM needs WHERE language = ? AND item_id = ? AND kind IN "
                                              "(?, ?) AND fixed_at IS NULL", (lang, item_id) + FAILED_KINDS)}


def _skipped_says(job):
    """The words of the steps a job ended without (its `skipped` column): their needs stay open (03 §4)."""
    try:
        return set((json.loads(job.get("skipped") or "{}") or {}).values())
    except (ValueError, AttributeError):
        return set()


def _finish_undos(steps, ledger, lang):
    """`steps.finish_undos` once a run per language, before anything else; Anki not answering leaves them for the
    next run (logged, never a reason not to go on)."""
    finish = getattr(steps, "finish_undos", None)
    if finish is None or not ledger.pending_undos(lang):
        return
    try:
        finish(lang, ledger)
    except Exception:
        log.exception("Connect couldn't finish an undo left half-way; it tries again next run")


def _gone_look(steps, lang):
    """Row 2.4.14's look (`steps.notes_gone`, once a run) for a language with no open job too: before, only `prepare`
    asked it, so cards deleted in Anki kept their episode's ✓ *N in Anki* until another episode was mined (Mattias,
    alpha 3). Read-only on Anki; Anki not answering leaves it for the next pass (logged, never a reason to stop)."""
    look = getattr(steps, "notes_gone", None)
    if look is None:
        return
    try:
        # Anki's own state gates it as it gates every touch of Anki in a run (`SURASURA_NO_ANKI_SYNC`, Anki closed or
        # busy, another profile, you reviewing); the battery doesn't: one read-only request (as an ask's, M-3)
        if _blocked(steps, lang, None, asked=True) is not None:
            return
        look(lang)
    except (Wait, Needs):
        pass                            # no store for this language, or it's busy: nothing to look at now
    except Exception as e:
        log.warning("Connect's deleted-card check didn't finish; it looks again: %s", e)


def _blocked(steps, lang, resume, asked=False):
    """`steps.blocked` as a Wait resuming at `resume` (it answers a reason, or a Wait of its own), or None. `asked`:
    for a job carrying an ask, on battery is no reason (Sonic 2026-10-22, M-3 A: a *Mine now* press is the yes for
    that one episode) — Anki's own state still is (`steps.session_blocked`)."""
    why = steps.blocked(lang)
    if asked and why == ON_BATTERY:
        session = getattr(steps, "session_blocked", None)
        why = session(lang) if session is not None else None
    if why is None:
        return None
    if isinstance(why, Wait):
        return Wait(why.reason, why.look, resume)
    return Wait(why, resume=resume)


def _resume_of(job):
    if job["state"] in IN_FLIGHT:
        return job["state"]
    return job.get("resume") if job["state"] == "waiting" else None


def _started(ledger, jid):
    """Has a batch of the job reached Anki Miner (anything but a call it refused)? Until then the job can still be
    dropped, picked again and checked again (adversary P2.4-A #1)."""
    return any(b["state"] != "refused" for b in ledger.batches(jid))


def _wait(ledger, job, wait, out, parked=None):
    """The job waits with one reason. Until a batch has reached Anki Miner it keeps no step to resume at: it picks
    again from the list as it is then (so it can be dropped, its pairing is checked again, and it never holds the
    level raise's look, `ledger.in_flight`; adversary P2.4-A #1); once one has, it resumes at mining at the earliest
    (it finishes, E18). A wait for the next start parks it for this run."""
    resume = wait.resume
    if resume in BEFORE_MINING or resume == "mining":
        resume = "mining" if _started(ledger, job["id"]) else None
    if wait.reason != STOPPED_BY_YOU and ledger.is_stopped(job["id"]):
        wait = Wait(STOPPED_BY_YOU, look=False, resume=wait.resume)     # review A10: a stop's stone says so
    now = ledger.job_by_id(job["id"]) or {}
    if (now.get("state"), now.get("reason"), now.get("resume")) != ("waiting", wait.reason, resume):
        ledger.set_state(job["id"], "waiting", reason=wait.reason, resume=resume)   # the same wait: nothing written (S19)
    if now.get("reason") != wait.reason:    # one line a change, never a look's (alpha 2's try: the log never said why)
        log.info("Connect: job %s (item %s) waits: %s", job["id"], job["item_id"], wait.reason)
    out["waiting"][job["item_id"]] = wait.reason
    if parked is not None and not wait.look:
        parked[job["id"]] = now.get("asked_at")


def _held():
    """One store handle for store reads back to back (L3.3's `library_store.held()`, §6.12): each `open_store` inside
    it returns the span's handle. Only around store reads: never around Anki or AnkiConnect, Anki Miner, a lock's
    wait, the tokenizer or tsubasa (seconds to minutes: a store marked damaged meanwhile couldn't be set aside by
    Repair while the handle stays open; adversary L3.3 wiring #1-#3)."""
    from app import library_store
    return library_store.held()


def _updating(ledger, lang, on):
    """F9 (P4.1 row 4.1.7): Connect's own Generate marked (`on`) or cleared in the ledger's meta, each in its own short
    transaction; nothing written when the mark already reads so (S19). A ledger fault is logged, never a reason not to
    Generate (R15). `ledger` None: nothing to mark."""
    if ledger is None:
        return
    try:
        if not on and ledger.updating(lang) is None:
            return
        with ledger.transaction():
            if on:
                ledger.mark_updating(lang)
            else:
                ledger.updated(lang)
    except Exception:
        log.exception("Connect couldn't %s its *updating your list* mark (%s)", "set" if on else "clear", lang)


def _working(ledger, lang, on):
    """Alpha 3 A2 (the waits' adversary): this look working through the language's episodes, marked (`on`) from its
    first episode until its pass ends, or cleared, in the ledger's meta (`working:<lang>`), each in its own short
    transaction; nothing written when the mark already reads so (S19). Between two episodes nothing is in flight for
    a moment: the mark keeps the ones behind on *its turn* (`status._turns`), never a flip to *Connect's next look* at
    every episode's end. A ledger fault is logged, never a reason not to mine (R15)."""
    try:
        if (ledger.working(lang) is not None) == bool(on):
            return
        with ledger.transaction():
            if on:
                ledger.mark_working(lang)
            else:
                ledger.worked(lang)
    except Exception:
        log.exception("Connect couldn't %s its *working through the episodes* mark (%s)", "set" if on else "clear",
                      lang)


def _job(steps, ledger, lang, job, store_now, line, out):
    """One job from where it stands to `done` (or a finished state). Raises Wait / Needs."""
    jid, item_id = job["id"], job["item_id"]
    step = _resume_of(job)
    droppable = step in BEFORE_MINING and not _started(ledger, jid)
    foreign = bool(job.get("store_id") and store_now and job["store_id"] != store_now)
    if foreign and droppable:
        ledger.set_state(jid, "dropped", reason="the library was set up again")
        out["dropped"].append(item_id)
        return
    if not job.get("store_id") and droppable:
        # queued before SCHEMA 3 (the 2.x preview's inbox): which library it came from isn't known, so it is never
        # mined into this one (P2.1 adversary #12) — named as a gap, as a read of the log Connect can't trust is
        ledger.set_state(jid, "dropped", reason="queued before Connect kept its library's identity")
        with ledger.transaction():
            ledger.add_gap(lang, [item_id])
        out["dropped"].append(item_id)
        return
    if droppable and item_id not in line and not inbox.keeps(job):     # an ask, a level raise beyond the line (P4.1)
        ledger.set_state(jid, "dropped", reason="left the top 20")
        out["dropped"].append(item_id)
        return
    if (droppable and job.get("kind") != ASKED and not job.get("asked_at")
            and not (ledger.picked(jid) or {}).get("forced")             # your *Mine anyway* on it too (round 2 B6)
            and getattr(steps, "watched", lambda _l, _j: False)(lang, job)):     # your ask on it is a yes (A1)
        # laptop round 8 #49 (LF4-1 = A): 3.0's rule, `level.WATCHED_GIVES_NO_NEW_CARDS` — no new cards on Connect's
        # own from an episode you've watched, a first mining or a level raise; its words go to the episodes that hold
        # them ahead of you
        ledger.set_state(jid, "dropped", reason=WATCHED)
        out["dropped"].append(item_id)
        return
    if droppable and _books_aside(steps, ledger, lang, [job], reopen=False):
        # alpha 4 M1: a job queued since this look read its inbox (a press's), set aside as the inbox's are
        out["skipped"].append(item_id)
        return
    record = not foreign
    _stop_here(steps, ledger, lang, job, step, record)
    if droppable:
        # at the cap, the shelf tried: one count, no pick and no write (S19, review B adv #2); never an ask (#42)
        full = _full(steps, lang, asked=bool(job.get("asked_at")))
        if full is not None:
            raise full
    try:
        # laptop round 9 #56: the job's Stop asked by every program waited on in these steps (`stopping.wait`): a
        # look-up still under way at a press is ended, and the job stops before the step it was in
        with stopping.watching(lambda: _stop_pressed(ledger, jid)):
            repicks = 0             # a profile or pairing that changed since the pick: picked again (at most twice)
            while repicks < 3:
                try:
                    if step in (None, "picking"):
                        _stop_here(steps, ledger, lang, job, step, record)
                        got = _pick(steps, ledger, lang, job, record)
                        _through(ledger, lang, "picking")
                        if got is None:
                            out["done"].append(item_id)
                            return
                        step = "filling" if got == "filling" else "fit-check"
                    if step == "fit-check":
                        _stop_here(steps, ledger, lang, job, step, record)
                        _fit(steps, ledger, lang, job)
                        step = "mining"
                    if step == "mining":
                        _stop_here(steps, ledger, lang, job, step, record)
                        _mine(steps, ledger, lang, job, record=record)
                        _drop_online(steps, job)    # Michi-YT: its clips and pictures are made: the video goes now
                        step = "filling"
                    break
                except _Again:
                    step = "picking"            # Michi-NT: the same subtitle, another file — no re-pick spent
                except Repick:
                    step = "picking"
                    repicks += 1
            else:
                raise Needs("repick", "Anki Miner's profile or the episode's pairing keeps changing; nothing was "
                            "mined.")
    except _Finished as f:
        out["skipped" if f.state == "skipped" else "failed"].append(item_id)
        return
    except stopping.Stopped:
        ended = True                        # #56: a program it waited on ended at your press
    else:
        ended = False
    if ended:
        # outside the handler: the Wait keeps no frame of the ended program (#17)
        _stopped(steps, ledger, lang, job, step, record)
    if step == "filling":
        _fill(steps, ledger, lang, job)
        step = "ordering"
    if step == "ordering":
        _order(steps, ledger, lang, job)
    ledger.set_state(jid, "done", reason=None)
    ledger.forget_stop(jid)                 # a *Stop* pressed while its cards were filled and ordered: nothing left
    out["done"].append(item_id)


def _stop_here(steps, ledger, lang, job, step, record):
    """Laptop round 8 #47: *Stop* pressed on this job -> it stops here, before `step` (nothing of the step done): the
    press used up, the job waits for your next ask (`Ledger.held_by_stop`), resuming at `step`."""
    if step in ("filling", "ordering") or not ledger.stop_asked(job["id"]):
        return                              # its cards are made: it finishes (seconds), the press forgotten at its end
    _stopped(steps, ledger, lang, job, step, record)


def _stopped(steps, ledger, lang, job, step, record):
    """The job stops before `step` at your press. Every stop comes here: `_stop_here`'s, a program ended mid-step
    (laptop round 9 #56) and the batch Anki Miner ended (`_stopped_mid_batch`). The cards its batches made so far
    are kept first (`_keep_made`); only then is the press used up, so the job reads *Stopping…* until it has
    stopped (row 56), the ask it carried kept (`Ledger.mark_stopped`) -> Wait for your next ask."""
    made = _keep_made(steps, ledger, lang, job, record)
    now = ledger.job_by_id(job["id"]) or {}
    if lining_up(now.get("reason")):        # Stage B (AB-Q3): *Stop* while its audiobook is lined up stops that too
        row = ledger.conn.execute("SELECT value FROM meta WHERE key = ?", (f"{LINEUP_PAIR}{int(job['id'])}",)).fetchone()
        if row is not None:
            from app.connect import lineup
            lineup.stop(row[0])
        elif getattr(steps, "stop_line_up", None) is not None:
            try:
                steps.stop_line_up(lang, job)
            except (Wait, Needs):
                log.info("Connect: job %s's line-up couldn't be found to stop (the library is busy)", job["id"])
    ledger.mark_stopped(job["id"], now.get("asked_at"))
    log.info("Connect: job %s stopped by you before %s (%d words made so far)", job["id"], step or "its pick",
             len(made))
    raise Wait(STOPPED_BY_YOU, look=False, resume=step)


def _keep_made(steps, ledger, lang, job, record):
    """A job you stopped keeps the cards its batches made (#47's batch you stopped; row 56: any stop once a batch has
    made some): recorded in the store (made words, no receipt: the episode isn't mined yet) and their clips named,
    before Anki's next sync. A store busy now is no matter: the resumed job records them all. -> {word: [note id]}"""
    made = _made(ledger, job["id"])
    if made and record:
        try:
            steps.record(lang, job, made, None, _tag(job))
        except (Wait, Needs):               # review A7: the resumed job records them all
            log.info("Connect: the store couldn't take job %s's cards now; they're recorded when it goes on",
                     job["id"])
        _name_media_at_end(steps, ledger, lang, job)
    return made


def lining_up(reason):
    """Is a job's reason a book waiting while its audiobook is lined up (`LINING_UP…`: the row's *Stop*)?"""
    return isinstance(reason, str) and reason.startswith(LINING_UP)


def _lining(reason, pair):
    """A wait on a pair's line-up (looked at again), naming the pair (`_line_up` keeps it for the part's *Stop*)."""
    wait = Wait(reason)
    wait.pair = pair
    return wait


def _newer(asked, at):
    """Is the ask `asked` (the ledger's or the store's stamp) newer than `at` (Connect's) — B-19: compared as keys."""
    from app.connect.ledger import stamp_key
    return bool(asked) and stamp_key(asked) > stamp_key(at)


def _keep_pair(ledger, jid, pair):
    """The pair a part waits on, kept for its *Stop* (`_stopped`: no store read at the press, review B-9) — written
    only when it changed (S19)."""
    key = f"{LINEUP_PAIR}{int(jid)}"
    row = ledger.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None or row[0] != pair:
        with ledger.transaction():
            ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, pair))


def _free_stopped(ledger, lang):
    """A stopped line-up started again (a *Mine now* on one part): the book's other parts parked on the stop are
    queued again, and the run woken so it tries them now (`_woken`: review B-8)."""
    freed = [j["id"] for j in ledger.jobs(lang, states=("waiting",)) if j.get("reason") == LINING_UP_STOPPED]
    for jid in freed:
        ledger.set_state(jid, "queued")
    if freed:
        from app.connect import kick
        kick.wake()


def _line_up(steps, ledger, lang, job, book):
    """Michi-AB Stage B: a book's part whose EPUB Hon paired with its audiobook, lined up first (`steps.line_up`) -> the
    line-up its words are cut from ({key, grade, files}), or None (no audiobook, nothing to line up, given up: mined as
    the book). Raises Wait while it lines up (LINING_UP…, looked at again), and for the speech model's one question
    (SPEECH_NEED: recorded once for the language, the book held by it). AB-Q4's plain line recorded once a book."""
    line_up = getattr(steps, "line_up", None)
    if line_up is None or not book or not book[1]:
        return None
    try:
        got = line_up(lang, job, book[1])
    except Wait as w:
        if getattr(w, "pair", None):
            _keep_pair(ledger, job["id"], w.pair)
        if getattr(w, "restarted", False):
            _free_stopped(ledger, lang)
        if lining_up(w.reason):
            _book_answered(ledger, lang, book[1])     # paired and lining up now: the book asks no more
        raise
    if got and got.get("book_ask"):
        if _book_question(ledger, lang, got):
            raise Wait(got["book_ask"])
        _mark_ai_audio(ledger, lang, job, got)
        return None
    _book_answered(ledger, lang, book[1])
    if not got:
        return None
    if got.get("ask"):
        if ledger.need(lang, SPEECH_NEED, got["ask"], standing=True):
            log.info("Connect: asks for Anki Miner's speech model (%s)", lang)
        raise Wait(got["ask"], look=False)
    if got.get("line") and got.get("item_id") is not None:
        ledger.need(lang, PARTIAL_NEED, got["line"], item_id=got["item_id"], standing=True)
    if got.get("lineup") and got.get("item_id") is not None:
        _add_audio_offer(steps, ledger, lang, book[1], got["item_id"])
    return got.get("lineup")


def _mark_ai_audio(ledger, lang, job, got):
    """Iro-AA: a part of a book answered *Make AI audio (beta)* — its job marked (`AI_JOB<id>`), so its new cards are
    queued for the AI voice when it fills. Read first: an unmarked book writes nothing."""
    key, epub = got.get("key"), got.get("epub")
    keys = [k for k in dict.fromkeys((key, book_key(epub) if epub else None)) if k]
    if not any(_meta(ledger, f"{BOOK_SAID}{lang}:{k}") == AI_AUDIO for k in keys):
        return
    mark = f"{AI_JOB}{int(job['id'])}"
    if _meta(ledger, mark) is None:
        with ledger.transaction():
            ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (mark, "1"))


def _queue_ai_audio(steps, ledger, lang, job, ids):
    """Iro-AA: the marked part's new cards handed to the AI voice's waiting list (`steps.queue_ai_audio`), its mark
    gone. A failure is logged: the cards stay as Anki Miner made them (without audio), never a reason to stop."""
    mark = f"{AI_JOB}{int(job['id'])}"
    if _meta(ledger, mark) is None:
        return
    queue = getattr(steps, "queue_ai_audio", None)
    try:
        if queue is not None:
            queue(lang, ids, job)
        with ledger.transaction():
            ledger.conn.execute("DELETE FROM meta WHERE key = ?", (mark,))
    except Exception:
        log.warning("Connect couldn't queue job %s's cards for AI audio", job["id"], exc_info=True)


def _ai_audio(steps, ledger, lang, parked, tried=()):
    """Iro-AA: once the language's jobs are through this pass, the AI voice's waiting list made (`steps.ai_audio`). It
    stops between two sentences — and the pass goes on — when a part comes in meanwhile (an open job: *Mine now*, a
    placement read; AI audio never holds a part back), for Connect's stop or an update staged, on battery, and when
    the session can't write now (you review, Anki closed, another profile: `_blocked`). -> True when it stopped for a
    part (the loop looks again). Never raises."""
    make = getattr(steps, "ai_audio", None)
    if make is None or _stop(steps):
        return False
    came = []
    from app.connect import kick
    woken = kick.wake_stamp()

    def should_stop():
        # a part waiting (*Mine now*), or a kick since the pass began — a placement in the library, a press: the
        # inbox is read by the loop's next look (review r2 #3)
        if _open_jobs(ledger, lang, parked, tried) or kick.wake_stamp() != woken:
            came.append(True)
            return True
        return bool(_stop(steps) or getattr(steps, "on_battery", lambda: False)() or
                    _blocked(steps, lang, None) is not None)
    try:
        make(lang, should_stop=should_stop)
    except Exception:
        log.warning("Connect's AI audio stopped on an error (%s)", lang, exc_info=True)
    return bool(came)


def _add_audio_says(ledger, lang, item):
    """The words of `item`'s open *Add the narrator's voice* line (its job's end leaves it: r1 S6)."""
    return {r[0] for r in ledger.conn.execute("SELECT say FROM needs WHERE language = ? AND kind = ? AND item_id = ? "
                                              "AND fixed_at IS NULL", (lang, ADD_AUDIO_NEED, item))}


def _add_audio_offers(steps, ledger, lang):
    """Kura-AB3 A2 (the lead's MUST): each book paired with its audiobook whose line isn't asked yet — or waits for its
    line-up — looked at read only: lined up now (paired since, its own subtitle checked or trusted, a sync finished) →
    its earlier cards offered (`_add_audio_offer`); able to be lined up, not yet → offered too, its press asking *Mine
    now* on its first part (`actions.add_audio_book`), whose job lines it up, seen and stoppable on its row. Never a
    listen or a sync started here (review A2 r4 B1). A book asked reads the ledger alone (S19). A busy library or a
    file away: the next pass. Never fails the pass."""
    books, lined_up = getattr(steps, "paired_books", None), getattr(steps, "lined_up", None)
    lineable = getattr(steps, "lineable", None)
    if books is None or lined_up is None:
        return
    try:
        pairs = books(lang)
    except Exception as e:                      # (a Wait: the library busy) the next pass
        log.info("Connect: couldn't read the paired books (%s): %s", lang, e)
        return
    for epub, item, sha in pairs:
        rec = _json_or_none(_meta(ledger, f"{ADD_AUDIO_ASKED}{lang}:{book_key(epub, sha)}"))
        if rec is not None and rec.get("stage") != ADD_AUDIO_WAITING:
            continue
        try:
            lined = lined_up(lang, epub)
            able = bool(lined) or (lineable is not None and lineable(lang, epub))
        except Exception as e:
            log.info("Connect: couldn't look at a book's line-up (%s): %s", lang, e)
            continue
        if lined:
            _add_audio_offer(steps, ledger, lang, epub, lined.get("item_id", item))
        elif able and rec is None:
            _add_audio_offer(steps, ledger, lang, epub, item, lined=False)
        elif not able and rec is not None:      # waiting, and it can't be lined up any more (r5 S2): the line goes
            _add_audio_gave_up(ledger, lang, f"{ADD_AUDIO_ASKED}{lang}:{book_key(epub, sha)}", rec)


def _add_audio_gave_up(ledger, lang, key, rec):
    """A waiting book's line fixed: kept together, nothing found or given up since — never "line it up" for good."""
    with ledger.transaction():
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                            (key, json.dumps(dict(rec, stage=ADD_AUDIO_GONE), sort_keys=True, ensure_ascii=False)))
        ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE language = ? AND kind = ? AND item_id = ? AND "
                            "fixed_at IS NULL", (_now(), lang, ADD_AUDIO_NEED, rec.get("item")))
    log.info("Connect: a book's earlier cards can't get the narrator's voice now (%s, item %s)", lang, rec.get("item"))


def _add_audio_offer(steps, ledger, lang, epub, item, lined=True):
    """Kura-AB3 A2: the book `epub`'s cards Connect made before its line-up (the store's made words of its parts, kept
    in its record at the first ask: `notes`) offered the narrator's voice once — ADD_AUDIO_NEED on the audiobook's
    `item`, worded ADD_AUDIO_ASK once it is lined up, ADD_AUDIO_WAIT before (`lined` False: its record's stage
    `waiting`, and the line says so again — counted again — when it lines up). A look that changes nothing reads the
    ledger alone (S19). Never fails the mine."""
    made = getattr(steps, "made_before", None)
    try:
        got = made(lang, epub) if made is not None else None
    except Exception as e:                      # the offer is a nicety: the mine goes on
        log.info("Connect: couldn't count a book's earlier cards (%s): %s", lang, e)
        return
    if got is None:
        return
    title, notes, sha = got
    key = f"{ADD_AUDIO_ASKED}{lang}:{book_key(epub, sha)}"     # by its bytes: a moved book is asked once (r1 S1)
    rec = _json_or_none(_meta(ledger, key))
    if rec is not None and (rec.get("stage") != ADD_AUDIO_WAITING or not lined):
        return
    # (a waiting record's list is the cards so far — each made as the book, text-only: r5 S3 — frozen once lined up:
    # the cards made since carry the narrator)
    say = (ADD_AUDIO_ASK if lined else ADD_AUDIO_WAIT).format(title=title)
    with ledger.transaction():
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(
            {"epub": os.path.abspath(epub), "item": item, "title": title, "notes": notes,
             "stage": ADD_AUDIO_LINED if lined else ADD_AUDIO_WAITING}, sort_keys=True, ensure_ascii=False)))
        if notes and ledger.need(lang, ADD_AUDIO_NEED, say, item_id=item, standing=True):
            log.info("Connect: offers the narrator's voice for a book's earlier cards (%s, item %s)", lang, item)


def book_key(epub, sha256=None):
    """Kura-AB2: a book's answer key — its EPUB's sha256 (the answer follows a moved or renamed book; a new edition is
    asked again), else its path."""
    from app import library_store
    return f"sha256:{sha256}" if sha256 else f"path:{library_store.path_key(os.path.abspath(epub))}"


def _meta(ledger, key):
    row = ledger.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _json_or_none(text):
    try:
        got = json.loads(text)
    except (TypeError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def _book_question(ledger, lang, got):
    """Kura-AB2: the book's one question (`Steps._book_audio`'s `got`: its words, the part it is asked by, its key and
    EPUB) -> True while it holds the book (each part held by its words, looked at again at each look: an audiobook
    paired since, by any door, lets it go); False — answered (*Mine without audio*, by its sha256 or its path), or its
    card dismissed (kept as an answer, so a later part never asks again): mined as the book. A question the same EPUB
    asked by another part before (its first part left the library) goes, so one card stands for the book; another copy
    of the same bytes elsewhere is a book of its own (its answer shared: the same key). Read first: a look that
    changes nothing writes nothing and takes no lock (S19)."""
    item, key, say, epub = got["item_id"], got["key"], got["book_ask"], os.path.abspath(got["epub"])
    if any(_meta(ledger, f"{BOOK_SAID}{lang}:{k}") for k in dict.fromkeys((key, book_key(epub)))):
        return False
    record = json.dumps({"key": key, "epub": epub}, sort_keys=True, ensure_ascii=False)
    lo = f"{BOOK_ASKED}{lang}:"
    mine = f"{lo}{item}"
    stale = [k for k, v in ledger.conn.execute("SELECT key, value FROM meta WHERE key >= ? AND key < ?",
                                               (lo, lo[:-1] + ";")).fetchall()
             if k != mine and (_json_or_none(v) or {}).get("epub") == epub]
    open_need = ledger.conn.execute("SELECT say, dismissed_at FROM needs WHERE language = ? AND kind = ? AND "
                                    "item_id = ? AND fixed_at IS NULL", (lang, BOOK_AUDIO_NEED, item)).fetchone()
    if not stale and _meta(ledger, mine) == record and open_need is not None and open_need[0] == say and \
            open_need[1] is None:
        return True                                 # asked already, as it is: nothing to write
    with ledger.transaction():
        for meta_key in stale:
            ledger.conn.execute("DELETE FROM meta WHERE key = ?", (meta_key,))
            ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE language = ? AND kind = ? AND item_id = ? AND "
                                "fixed_at IS NULL", (_now(), lang, BOOK_AUDIO_NEED, int(meta_key[len(lo):])))
        if _meta(ledger, mine) != record:
            ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (mine, record))
        if ledger.need(lang, BOOK_AUDIO_NEED, say, item_id=item, standing=True):
            log.info("Connect: asks whether a book has its audiobook (%s, item %s)", lang, item)
        elif open_need is not None and open_need[1] is not None:
            # *Dismiss*: you let it be — mined as the book, never held for good; kept, since the part whose job ends
            # takes its needs with it and the next part would ask again
            ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                                (f"{BOOK_SAID}{lang}:{key}", DISMISSED))
            return False
    return True


def _book_orphans(ledger, lang):
    """Kura-AB2: a book's question no waiting part holds any more (its parts' jobs ended without an answer — dropped,
    skipped, removed — while the part it is asked by has no job to take it along) fixed, by itself: never a card that
    nothing clears. A job's end; nothing open: the ledger read alone."""
    open_needs = [n for n in ledger.needs(lang, listed=False) if n["kind"] == BOOK_AUDIO_NEED]
    if not open_needs:
        return
    held = {j.get("reason") for j in ledger.jobs(lang, states=("waiting",))}
    for n in open_needs:
        if n["say"] not in held:
            _fixed_book(ledger, lang, n["item_id"])


def _fixed_book(ledger, lang, item):
    """The book question asked by part `item` fixed — that question alone, never the part's other needs (03 §4)."""
    with ledger.transaction():
        ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE language = ? AND kind = ? AND item_id = ? AND "
                            "fixed_at IS NULL", (_now(), lang, BOOK_AUDIO_NEED, item))
    log.info("Connect: fixed by itself (%s, %s): item %s", lang, BOOK_AUDIO_NEED, item)


def _book_answered(ledger, lang, epub):
    """Kura-AB2: the book `epub` asks no more (an audiobook paired since — *Pick its audiobook…*, a look, Hon's own
    question — or Anki Miner can't line it up now): its open question fixed, by itself; never the asking part's other
    needs. Nothing open: the ledger read alone."""
    open_ids = {n["item_id"] for n in ledger.needs(lang, listed=False) if n["kind"] == BOOK_AUDIO_NEED}
    if not open_ids:
        return
    want = os.path.abspath(epub)
    for item in sorted(open_ids):
        rec = _json_or_none(_meta(ledger, f"{BOOK_ASKED}{lang}:{item}")) or {}
        if rec.get("epub") == want:
            _fixed_book(ledger, lang, item)


def _pick(steps, ledger, lang, job, record=True):
    """The pick step -> what it picked; None when it found no word (the job done with nothing to make); "filling"
    when it found none after an earlier batch made some (those recorded, then filled and ordered: adversary #6)."""
    jid = job["id"]
    book = _reading_source(steps, lang, job)        # Z-9: a book or a text, once Anki Miner reads them
    # Stage B: its audiobook lined up first — before the step is written: a part waiting on the line-up writes its
    # row only when its line changes (review B-15)
    lined = _line_up(steps, ledger, lang, job, book) if book is not None else None
    web = _online(steps, lang, job) if book is None else None      # Michi-YT: an online title's episode
    # (an online one: no download's percent from an earlier try — in the same one write, S19)
    ledger.set_state(jid, "picking", **({"progress": None} if web is not None else {}))
    subtitle = None
    if web is not None:
        fetched = _download(steps, ledger, lang, job, web)
        if fetched is None:                         # no Anki Miner to fetch it: as a pick that finds none
            _record_made(steps, ledger, lang, job, record)
            ledger.set_state(jid, "skipped", reason=MINER_ABSENT, skipped={"mining": MINER_ABSENT})
            raise _Finished("skipped")
        video, subtitle = fetched
    else:
        video = steps.video(lang, job) if book is None else None
    heard = None                                    # Z-16: an audio item's own wait line, when nothing is found
    if book is None and video is None:
        video, heard = _audio(steps, lang, job)     # an audio file, once Anki Miner mines audio
    if book is None and video is None and job.get("kind") == LEVEL and not job.get("asked_at"):
        # laptop round 8 #49 (LF4-1 ⭐ A): a level raise never asks for a video — an episode already mined whose video
        # is gone waits quietly (its own reason: never *Needs you*'s *No video*), and goes on at a start that finds the
        # video again (review A8: its new words aren't lost); your ask on it asks for the video as any (A1)
        raise Wait(heard or LEVEL_NO_VIDEO, look=False)
    if book is None and video is None and heard:
        raise Wait(heard, look=False)               # parked as *No video* is: looked at again at the next start
    if book is None and video is None:
        folder = steps.video_moved(lang, job)
        raise Wait(MOVED.format(folder=folder) if folder else NO_VIDEO, look=False)
    pairing = steps.pairing(lang, job)
    before = ledger.picked(jid) or {}
    # Michi-NT (Mattias #XP44T6): its library copy wasn't timed, and the same subtitle re-timed beside its video was
    # found (`_fit`, `retimed_beside`) — picked from that file, for that video, while it is there
    beside = before.get("beside") if book is None and subtitle is None else None
    if beside and (before.get("video") != video or not os.path.isfile(beside)):
        beside = None
    if book is not None:
        got = steps.pick(lang, job, None, reading=book[0])
    elif subtitle is not None:
        got = steps.pick(lang, job, video, subtitle=subtitle)      # its own captions, fetched with it
    elif beside:
        got = steps.pick(lang, job, video, subtitle=beside)
    else:
        got = steps.pick(lang, job, video)
    declined = ledger.declined(lang, job["item_id"])     # Anki Miner turned them down once: never sent again (#19)
    if got.get("anki_miner"):
        # laptop round 8 #52 (LF4-4 ⭐ A): a word this Anki Miner has no definition for, in any episode, is no card here
        # either (a name: sent once a version, never again with every episode)
        declined |= ledger.uncardable(lang, got["anki_miner"])
        declined |= ledger.skipped_words(lang, got["anki_miner"])     # Michi-RM3: *Skip this word*, any part
    words = [w for w in got.get("words") or [] if (w.get("word"), w.get("reading")) not in declined]
    picked = {"words": words, "file": got.get("file"), "subtitle": got.get("subtitle"),
              "video": video, "pairing": fit_check.version(pairing), "profile": got.get("profile"),
              "anki_miner": got.get("anki_miner")}
    if isinstance(pairing, dict) and (pairing.get("verdict") == "transcribed" or (
            pairing.get("producer") == "source" and steps.heard(lang, job))):
        picked["from_audio"] = True                 # Michi-NS (Q5): its subtitle was made from its audio: tagged
        #                                             (Hato-SP: and one another tool made, by its name: `library.heard`)
    if web is not None:
        picked["online"], picked["names"] = web["site"], web["names"]     # Michi-YT: its Source names the transcript
    if book is not None:
        picked["reading"], picked["book"] = book    # the file Anki Miner reads; the EPUB its cards are placed in
        if lined:
            picked["lineup"] = lined                # Stage B: its words cut from the audiobook where it was heard
    if beside:
        picked["beside"], picked["copy"] = beside, before.get("copy")
        picked["beside_at"] = _stamp(beside)    # the file as checked: changed or gone before a batch -> picked again
        picked["part_way"] = bool(before.get("part_way"))   # Michi-NT2: the copy's own verdict, for its re-time
    if before.get("forced") and before.get("pairing") == picked["pairing"] and before.get("video") == video:
        picked["forced"] = True     # *Mine anyway* (row 4.1.9) holds for the pairing and video you said it for (D5: a
        #                             marked origin's video standing in is another file); a new one clears it
    if got.get("absent"):
        _record_made(steps, ledger, lang, job, record)
        ledger.set_state(jid, "skipped", reason=MINER_ABSENT, picked=picked, skipped={"mining": MINER_ABSENT})
        raise _Finished("skipped")
    if not picked["words"]:
        if _made(ledger, jid):
            ledger.set_state(jid, "mining", picked=picked)
            _record_made(steps, ledger, lang, job, record)
            ledger.set_state(jid, "filling")
            return "filling"
        # an episode with nothing to make: its receipt (Mado's W2.2 ask: a finished zero-card job writes mined_at)
        steps.record(lang, job, {}, _now() if job.get("kind") != "level" else None, None)
        ledger.set_state(jid, "done", reason=NO_WORDS, picked=picked, skipped={"mining": NO_WORDS})
        return None
    ledger.set_state(jid, "fit-check", picked=picked)
    return picked


def _online(steps, lang, job):
    """Michi-YT: the online title a job's episode is (`Steps.online`: {"site", "url", "names"}), or None — a stand-in
    Steps without the look is never one."""
    look = getattr(steps, "online", None)
    return look(lang, job) if look is not None else None


DOWNLOADING = "downloading"     # the job's saved progress step while its video comes down (`status._progress`)


def _download(steps, ledger, lang, job, web):
    """Michi-YT: an online title's video and its captions for the job (`Steps.download`, Anki Miner's `fetch`) ->
    (video, subtitle), or None when there's no Anki Miner. On mains power only, as any mining (an ask on battery is
    its yes, M-3 A): the wait before any download. Its percent saved as it goes (`DOWNLOADING`, every PROGRESS_STEP);
    the language's download trouble fixed once a video came down. Raises Wait / Needs / `stopping.Stopped`."""
    wait = _blocked(steps, lang, None, asked=bool(job.get("asked_at")))
    if wait is not None:
        raise wait
    jid, shown = job["id"], [None]

    def progress(percent):
        if percent // PROGRESS_STEP == shown[0]:
            return
        shown[0] = percent // PROGRESS_STEP
        try:
            ledger.set_state(jid, "picking", progress={"step": DOWNLOADING, "percent": int(percent)})
        except Exception:
            log.warning("Connect couldn't save the download's progress", exc_info=True)
    progress(0)
    got = steps.download(lang, job, web, progress)
    ledger.set_state(jid, "picking", progress=None)
    if got is not None:
        from app.connect import online
        _fixed(ledger, lang, kinds=(online.KIND,))
    return got


def _looks_again(ledger, job, parked):
    """Michi-YT (review M1): is the job waiting on something this run looks at again (Anki Miner's window open, you
    reviewing, another writer: a 2-minute look)? Then its downloaded video stays for that look — a wait never fetches
    the whole video again each look; the run's end sweeps it. A job ended, stopped, or parked for the next start: no."""
    try:
        now = ledger.job_by_id(job["id"]) or {}
    except Exception:
        return False
    return now.get("state") == "waiting" and job["id"] not in parked and now.get("reason") != STOPPED_BY_YOU


def _drop_online(steps, job):
    """Michi-YT: the job's downloaded video gone (none: nothing done) — never a reason for the job to fail."""
    drop = getattr(steps, "drop_online", None)
    if drop is not None:
        try:
            drop(job)
        except Exception:
            log.exception("Connect couldn't remove job %s's downloaded video", job.get("id"))


def _sweep_online(steps):
    sweep = getattr(steps, "sweep_online", None)
    if sweep is not None:
        try:
            sweep()
        except Exception:
            log.exception("Connect couldn't look for downloaded videos left from before")


def _audio(steps, lang, job):
    """Z-16: the audio file an episode with no video is cut from while Anki Miner mines audio (`steps.audio`, A1) ->
    (its path or None, an audio item's own wait line or None). With no path, an audio item waits with its line
    (`NO_AUDIO`, `SEVERAL_FILES`, `NO_TEXT`), parked as *No video* is (looked at again at the next start, never every
    look: review AB-1), never *No video*; any other item's *No video* follows as before."""
    audio, mines = getattr(steps, "audio", None), getattr(steps, "mines", None)
    if audio is None or mines is None or not mines(lang, "audio"):
        return None, None
    return audio(lang, job)


def _reading_source(steps, lang, job):
    """Z-9: (the file Anki Miner reads, the EPUB or None) for a job whose item is a book or a text while Anki Miner
    reads them (`steps.mines`; the item by `library.waits_for`, the rows' one rule: `steps.reading`), else None — a
    video's job, exactly as before."""
    reading, mines = getattr(steps, "reading", None), getattr(steps, "mines", None)
    if reading is None or mines is None or not mines(lang, "books"):
        return None
    return reading(lang, job)


def _part_read(steps, lang, job, picked):
    """Michi-BK (report #BS0A1K): `picked` for one Anki Miner call — a book's part reads its own copy of the book
    (`steps.part_book`, made again right before each call: every part of a book shares the copy's one place), else
    `picked` as it is (a video, a text, a copy that couldn't be made: the whole EPUB, as before). The ledger keeps
    naming the EPUB."""
    make = getattr(steps, "part_book", None)
    if make is None or not picked.get("book") or picked.get("reading") != picked["book"]:
        return picked
    named = make(lang, job, picked["book"])
    return dict(picked, reading=named) if named else picked


class _Finished(Exception):
    """The job ended here in a finished state other than done (its state already saved)."""

    def __init__(self, state):
        super().__init__(state)
        self.state = state


# LF56-1 (Sonic 2026-10-23: "One thing about the 4%, unsure"): a timing check with no answer (tsubasa timed out or
# couldn't start) is tried at this many looks running, then named in *Needs you* as not timed (*Mine anyway*)
FIT_TRIES = 3
FIT_TRY = "fit_try:"            # ledger meta: `fit_try:<job id>` -> the looks running tsubasa gave no answer
MINE_ANYWAY_HINT = "Mine anyway to cut its lines where the subtitle puts them."


def _fit_tries(ledger, jid, failed):
    """The job's timing checks with no answer running: one more when `failed` (-> the count), else forgotten (0)."""
    key = f"{FIT_TRY}{int(jid)}"
    row = ledger.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if not failed:
        if row is not None:                     # only a count to forget is written (S19)
            with ledger.transaction():
                ledger.conn.execute("DELETE FROM meta WHERE key = ?", (key,))
        return 0
    with ledger.transaction():
        try:
            tries = int(row[0]) + 1 if row else 1
        except (TypeError, ValueError):
            tries = 1
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(tries)))
        return tries


RETIMED = "retimed:"            # ledger meta: `retimed:<job id>` -> when its library copy was given to tsubasa to re-time
RETIMED_FOLDER = "retimed"      # in a job's run folder: tsubasa's re-timed copy, until it takes the copy's place
RETIME_PART = ".retimed.part"   # beside the copy: its re-timed bytes, flushed, until `os.replace` (never S5's `.part`)
UNSURE_FILE = "undetermined.json"   # in a job's run folder: tsubasa's undetermined spans of its re-timed copy (Tsu-U)


def _retime(steps, ledger, lang, job, video, copy):
    """Michi-NT2 (based on Mattias's #364): the library copy `copy` re-timed by tsubasa in its own place (`Steps.retime`)
    -> True. Once a job (`RETIMED`, marked before tsubasa is asked: a Connect killed meanwhile never asks again and
    again) — given back when tsubasa gave no answer this time, the copy changed meanwhile, or at your *Stop*;
    *Check again* lets it be asked once more. A stand-in Steps without it, no video, or a failure: False, the
    copy as it was, the job named not timed. Your *Stop* ends it as the check does."""
    do = getattr(steps, "retime", None)
    if do is None or not video or not copy:
        return False
    key = f"{RETIMED}{int(job['id'])}"
    if ledger.conn.execute("SELECT 1 FROM meta WHERE key = ?", (key,)).fetchone() is not None:
        return False
    with ledger.transaction():
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, _now()))
    try:
        done = do(lang, job, video, copy)
    except stopping.Stopped:
        _unmark(ledger, key)                # your *Stop*: asked again when the job goes on
        raise
    except Exception:                       # a re-time that fails is no reason for the job to fail: not timed, named
        log.warning("Connect couldn't have tsubasa re-time job %s's subtitle", job.get("id"), exc_info=True)
        return False
    if done is None:                        # no answer this time, or its copy changed meanwhile: asked at the next check
        _unmark(ledger, key)
    if done:
        log.info("Connect: job %s: tsubasa re-timed its library copy, every part its own shift: %s", job["id"], copy)
    return bool(done)


def _unmark(ledger, key):
    with ledger.transaction():
        ledger.conn.execute("DELETE FROM meta WHERE key = ?", (key,))


def _stamp(path):
    """[path, size, modified time] of a file as it is now, or None (no path, or it can't be read)."""
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    return [path, st.st_size, st.st_mtime_ns]


def _copy_changed(ledger, parked):
    """Michi-NT (Mattias #XP44T6): a job parked as not timed whose library copy changed since it was checked (you
    re-timed it, or its original changed and the library copied it again) goes again in this run — never only at the
    next start. One stat of a local file a parked job, each look; nothing written."""
    for job_id in list(parked):
        checked = (ledger.picked(job_id) or {}).get("checked")
        if not isinstance(checked, list) or len(checked) != 3:
            continue
        now = _stamp(checked[0])
        if now is not None and now != checked:      # (a copy gone is the next start's: never let go each look)
            del parked[job_id]


def _retimed(steps, lang, job, picked):
    """The same subtitle re-timed beside the job's video (`Steps.retimed`), or None — a stand-in Steps without the
    look never has one."""
    look = getattr(steps, "retimed", None)
    video, copy = picked.get("video"), picked.get("file")
    if look is None or not video or not copy:
        return None
    try:
        return look(lang, job, video, copy)
    except Exception:                       # a look that fails is no subtitle beside it: the copy's verdict stands
        log.warning("Connect couldn't look beside job %s's video for its subtitle", job.get("id"), exc_info=True)
        return None


def retimed_beside(video, copy, language):
    """Michi-NT (Mattias #XP44T6): a subtitle beside `video`, named after it (`<video's name>.ja.srt`: where tsubasa
    writes a subtitle it re-timed to that video, as a player looks for it), with no language mark or the library's,
    that holds the very lines of the library's `copy` (the same subtitle, re-timed — never another release) in other
    bytes -> its path (the newest of several), else None. One listing of the video's folder and a read of each such
    file; asked only once the copy was found not timed. Never an audio file's."""
    from app import cues
    from app.connect.anki_miner import is_audio
    from app.episode_names import identity, video_stems
    if is_audio(video):
        return None
    folder, name = os.path.split(video)
    stem = os.path.splitext(name)[0].lower()
    try:
        names = os.listdir(folder or ".")
    except OSError:
        return None
    found = []
    for n in names:
        path = os.path.join(folder, n)
        if not n.lower().endswith(cues.SUBTITLES) or stem not in {s.lower() for s in video_stems(n)}:
            continue
        langs = identity(n).languages
        if (langs and language not in langs) or os.path.normcase(os.path.abspath(path)) == \
                os.path.normcase(os.path.abspath(copy)):
            continue
        stamp = _stamp(path)
        if stamp is not None and _on_disk(path):     # never a cloud placeholder: its read would download it (RD-S1)
            found.append((stamp[2], path))
    for _at, path in sorted(found, reverse=True):
        if same_subtitle(copy, path, language):
            return path
    return None


def same_subtitle(copy, other, language, dropped=0):
    """Is `other` the subtitle `copy` is, re-timed — the very lines (`cues.read`'s texts, in order: CRLF or LF, a BOM
    or none read alike) in other bytes, less exactly the `dropped` cues tsubasa says it left out (in a stretch its
    video doesn't hold: Michi-NT2's re-time)? No line, or a file that can't be read: no."""
    from app import cues
    try:
        with open(copy, "rb") as f, open(other, "rb") as g:
            if f.read() == g.read():
                return False
        lines = [c.text for c in cues.read(copy, language)]
        kept = [c.text for c in cues.read(other, language)]
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    if not lines or not kept or len(lines) - len(kept) != dropped:
        return False
    rest = iter(lines)                      # `kept` in `lines`' order, nothing new (a subsequence)
    return all(any(line == text for line in rest) for text in kept)


def _fit(steps, ledger, lang, job):
    jid = job["id"]
    picked = ledger.picked(jid) or {}
    ledger.set_state(jid, "fit-check")
    pairing = steps.pairing(lang, job)
    if fit_check.version(pairing) != picked.get("pairing"):
        raise Repick()                      # E17: hato re-timed it, or a new subtitle
    if picked.get("reading"):
        picked["offset"] = 0.0              # Z-9: a book's sentences have no times: nothing to check
        ledger.set_state(jid, "mining", picked=picked)
        return
    if picked.get("online"):
        # Michi-YT: an online title's video and its captions came down together (Anki Miner's `fetch`), timed to that
        # video by YouTube — mined at their own times (as fit_check releases Surasura's own `youtube` records); a
        # video gone since (a later run: it was dropped) is fetched again by a new pick
        if not _on_disk(picked.get("video") or ""):
            raise Repick()
        picked["offset"] = 0.0
        ledger.set_state(jid, "mining", picked=picked)
        return
    if picked.get("forced"):
        # *Mine anyway* (G1.3-6, E16; P4.1 row 4.1.9): you chose to mine it not timed — tsubasa isn't asked, and the
        # lines are cut where the subtitle puts them (no shift)
        log.info("Connect: job %s mined anyway: not timed", jid)
        picked["offset"] = 0.0
        ledger.set_state(jid, "mining", picked=picked)
        return
    verdict, who, why, offset = steps.fit(lang, job, pairing, picked.get("video"), picked.get("file"))
    if who == SPEECH_NEED:                  # AB-Q5: the spot-check needs the speech model — its one question
        ledger.need(lang, SPEECH_NEED, why, standing=True)
        raise Wait(why, look=False)
    if verdict == fit_check.TIMED and who == "you":
        log.info("Connect: job %s mined at its subtitle's own times: you trust your subtitles' timing", jid)
    tries = _fit_tries(ledger, jid, verdict == fit_check.RETRY)
    if verdict == fit_check.RETRY:
        # tsubasa couldn't answer this time: asked again at the next look — FIT_TRIES looks running at most (LF56-1:
        # a check that times out on this PC every time held the episode at the hourglass for ever)
        if tries < FIT_TRIES:
            raise Wait(f"{why} (try {tries} of {FIT_TRIES})")
        if picked.pop("beside", None):      # Michi-NT: the next pick (and a *Mine anyway*) is the copy's again
            ledger.set_state(jid, "fit-check", picked=picked)
        title = steps.title(lang, job)
        gave_up = f"{why.split(';')[0]}, {FIT_TRIES} looks running, so Connect stopped trying. {MINE_ANYWAY_HINT}"
        raise Needs("not-timed", f"{title}: {gave_up}" if title else gave_up)
    if verdict != fit_check.TIMED:
        was = picked.pop("beside", None)
        part_way = who == "tsubasa" and fit_check.part_way(why)     # this check's: the copy's, unless `was`
        if was:
            # Michi-NT: the subtitle beside its video wasn't timed either — the next check starts from the copy again
            log.info("Connect: job %s: the subtitle beside its video isn't timed either: %s", jid, was)
            part_way = picked.pop("part_way", False)                # the copy's own verdict, kept at the switch
        elif who == "tsubasa" and verdict == fit_check.NOT_TIMED:
            # Michi-NT (Mattias #XP44T6): the library's copy isn't timed — the same subtitle re-timed beside its video
            # (tsubasa's own output, named after the video) is checked in its place: timed, its cards are cut from it
            other = _retimed(steps, lang, job, picked)
            if other:
                log.info("Connect: job %s: its subtitle re-timed beside its video is checked: %s", jid, other)
                picked["beside"], picked["copy"], picked["part_way"] = other, picked.get("file"), part_way
                ledger.set_state(jid, "fit-check", picked=picked)
                raise _Again()
        copy = picked.get("copy") if was else picked.get("file")
        if part_way and _retime(steps, ledger, lang, job, picked.get("video"), copy):
            # Michi-NT2 (based on Mattias's #364): its timing changes part-way — tsubasa re-timed the library's copy
            # itself, every segment its own shift: picked again from it and checked again (a copy that still changes
            # part-way is named, never re-timed twice a job)
            ledger.set_state(jid, "fit-check", picked=picked)
            raise _Again()
        # the library's copy as checked (never one beside a video: a share is never looked at each look) — a change
        # to it lets the job go again in this run (`_copy_changed`)
        picked["checked"] = _stamp(picked.get("copy") if was else picked.get("file"))
        ledger.set_state(jid, "fit-check", picked=picked)
        title = steps.title(lang, job)
        raise Needs("not-timed", f"{title}: {why}" if title else why)
    picked["offset"] = offset               # the shift Anki Miner cuts the lines by (intent keeper P2.4-A #1)
    ledger.set_state(jid, "mining", picked=picked)


def _mine(steps, ledger, lang, job, record=True):
    """The mine step: the words not settled yet, in one batch (tried again after a batch in doubt; a second crash
    ends it), then the mining's one store write — every batch's made words and the receipt together (`record`: False
    for a job of a store set up again since). Raises Wait, Needs, Repick, and _Finished when the job ends here
    (skipped, failed)."""
    jid = job["id"]
    picked = ledger.picked(jid) or {}
    words = picked.get("words") or []
    by_key = {(w["word"], w["reading"]): w for w in words}
    ran = False                     # a batch ran in this call: the next one waits for an update staged meanwhile
    for _ in range(3):              # a batch in doubt is tried once more; a second failure ends it
        batches = ledger.batches(jid)
        last = batches[-1] if batches else None
        if last is not None and last["state"] == "running":
            # Connect was stopped mid-batch (its Anki Miner ended with it): what reached Anki is found by the job's
            # tag first, never mined twice; Connect's own stop is no failure of Anki Miner's (adversary #18)
            found = steps.by_tag(lang, job, picked, [w for w in words if _outcome(ledger, jid, w) in UNSETTLED])
            ledger.end_batch(jid, last["attempt"], "uncertain", _enriched(found, by_key))
            batches = ledger.batches(jid)
        todo = [w for w in words if _outcome(ledger, jid, w) in UNSETTLED]
        if not todo:
            break
        if picked.get("online") and not _on_disk(picked.get("video") or ""):
            raise Repick()                  # Michi-YT: resumed in a later run, its video dropped: fetched again —
            #                                 only while a word is left to send (a batch in doubt read back first)
        doubt = any(_outcome(ledger, jid, w) == "uncertain" for w in todo)
        if doubt and _failures(ledger, jid) >= 2:
            _fail_mining(steps, ledger, lang, job, record)
        if fit_check.version(steps.pairing(lang, job)) != picked.get("pairing"):
            raise Repick()                  # E17 before every batch (intent keeper #7): hato re-timed it meanwhile
        if picked.get("beside") and _stamp(picked["beside"]) != picked.get("beside_at"):
            raise Repick()                  # Michi-NT: the subtitle beside its video changed or went since its check
        wait = _blocked(steps, lang, "mining", asked=bool(job.get("asked_at")))
        if wait is not None:
            raise wait
        if not _started(ledger, jid):       # P2.4 Part B: the cap before a job's first batch, never mid-episode
            wait = _at_cap(steps, ledger, lang, todo, asked=bool(job.get("asked_at")))
            if wait is not None:
                raise wait
        _stop_here(steps, ledger, lang, job, "mining", record)     # #47: between two batches too
        if ran and steps.update_staged():
            # between two Anki Miner batches (K99): stopped here, every outcome saved; the next run resumes at mining
            # and sends only the words still unsettled
            raise Wait(STOPPED_FOR_UPDATE, look=False, resume="mining")
        had = ledger.job_by_id(jid).get("attempt") or 0
        refused = bool(batches) and batches[-1]["state"] == "refused" and batches[-1]["attempt"] == had
        attempt = had if refused else had + 1      # a call Anki Miner refused never ran: its number reused (#20)
        in_doubt = any(b["state"] == "uncertain" for b in batches)
        ledger.set_state(jid, "mining", progress=None)      # a new batch: no progress yet (laptop round 5 #23)
        ledger.start_batch(jid, attempt, steps.run_dir(job))
        ran = True
        steps.on_progress = _Progress(ledger, jid)
        steps.should_stop = stopping.pressed    # #47: Anki Miner's batch cancelled at a press (the job's one check)
        try:
            got = _mine_batch(steps, ledger, lang, job, picked, todo, attempt)
        except Wait as w:
            ledger.end_batch(jid, attempt, "refused")
            raise Wait(w.reason, w.look, "mining") from None
        except (Repick, Needs, stopping.Stopped):
            # #56: a look-up ended at your press is refused too: the batch never ran, never a failure
            ledger.end_batch(jid, attempt, "refused")
            raise
        except Skip as s:
            ledger.end_batch(jid, attempt, "refused")
            _record_made(steps, ledger, lang, job, record)
            _name_media_at_end(steps, ledger, lang, job)
            ledger.set_state(jid, "skipped", reason=s.why, skipped=_skipped(ledger, jid, "mining", s.why))
            raise _Finished("skipped") from None
        finally:
            steps.on_progress = steps.should_stop = None
        _through(ledger, lang, "mining")    # Anki Miner took the batch: its setup, the deck and note type are there
        stopped = bool(got.get("stopped"))
        if got.get("tag_pending"):          # the names' tag Anki didn't take: added before filling (adversary #7)
            pending = sorted(set(_pending(ledger, jid)) | set(got["tag_pending"]))
            ledger.set_state(jid, "mining", tag_pending=json.dumps(pending))
        try:
            if stopped or got.get("doubt") or any(o["outcome"] == "uncertain" for o in got["outcomes"]):
                # #47: a batch you stopped is read back by the job's tag like one in doubt: every card that reached
                # Anki recorded, none sent twice
                # a word Anki Miner doesn't account for may be in Anki: found by the job's tag first, never sent twice
                found = steps.by_tag(lang, job, picked, [w for w in todo if _row(got, w) in UNSETTLED])
                got["outcomes"] = _merge(got["outcomes"], found)
            elif in_doubt:
                # tried again after a batch in doubt: a word it calls a duplicate may be this job's own card (#4)
                dup = [w for w in todo if _row(got, w) == "duplicate"]
                if dup:
                    got["outcomes"] = _merge(got["outcomes"], steps.by_tag(lang, job, picked, dup), ("duplicate",))
        except Wait as w:
            # Anki went away before the tag check: Anki Miner's own outcomes kept, the rest in doubt (adversary #16)
            ledger.end_batch(jid, attempt, "uncertain", _enriched(got["outcomes"], by_key), anki_miner=got.get("app"))
            if got.get("anki_said"):        # Mattias #5 (review r2 B1): Anki's refusal kept, as below
                _keep_alone(ledger, jid, got["anki_said"], got.get("refused"))
            if got.get("doubt") and not stopped and got.get("then") is None:
                _count_failure(ledger, jid)     # (never for a word-at-a-time batch a wait cut short)
            raise Wait(w.reason, w.look, "mining") from None
        state = "uncertain" if any(o["outcome"] == "uncertain" for o in got["outcomes"]) else "done"
        ledger.end_batch(jid, attempt, state, _enriched(got["outcomes"], by_key), anki_miner=got.get("app"))
        if got.get("anki_said") and state == "uncertain":    # Mattias #5: Anki refused a card: next, a word at a time
            _keep_alone(ledger, jid, got["anki_said"], got.get("refused"))
        then = got.get("then")              # a word-at-a-time batch a wait cut short: its words not all sent
        if got.get("doubt") and not stopped and then is None:
            _count_failure(ledger, jid)     # only a run that crashed or timed out: an unknown status is no crash
        if any(o["outcome"] == "made" for o in got["outcomes"]):
            steps.after_write(lang)         # new cards: the session's sync clock (S3), Junban or not (adversary #12)
        if stopped:
            _stopped_mid_batch(steps, ledger, lang, job, record)
        if isinstance(then, Wait):          # (its cards recorded above; it resumes at mining)
            raise Wait(then.reason, then.look, "mining")
        if then is not None:
            raise then
    left = [w for w in words if _outcome(ledger, jid, w) in UNSETTLED]
    if _failures(ledger, jid) >= 2 and any(_outcome(ledger, jid, w) == "uncertain" for w in left):
        _fail_mining(steps, ledger, lang, job, record)     # a second crash in the last try
    if left:                                # Anki Miner never accounted for them, three times: named, not mined
        never = f"{len(left)} words Anki Miner never made or turned down"
        ledger.set_state(jid, "mining", skipped=_skipped(ledger, jid, "mining", never))
    try:
        with ledger.transaction():
            ledger.set_state(jid, "mining", progress={"step": "naming"})     # the row's step (laptop round 5 #23)
            ledger.forget_stop(jid)     # row 56: naming is past the stop point (`ledger.stoppable`): a press is over
        _name_media(steps, ledger, lang, job, picked)   # P2.4-4: one file a line, before Anki's next sync
    except Wait as w:
        raise Wait(w.reason, w.look, "mining") from None
    # the store write after the rename: a rename that waits (you review) leaves nothing written to do again at every
    # look (adversary B #6, S19)
    _record_made(steps, ledger, lang, job, record)
    ledger.set_state(jid, "filling")


# Mattias's field report (3.0.0, #5): ledger meta `alone:<job id>` -> {"said": what Anki said when it refused a batch of
# the job (Anki Miner's MINING_FAILED, not transient: AnkiConnect's *cannot create note …*), "words": the words it went on
# refusing a word at a time} — the job's next batches send each word in a call of its own, so one card Anki won't take
# never holds back the others, and the failure line names only the words Anki refused alone
ALONE = "alone:"


def _keep_alone(ledger, jid, said, words=()):
    had = _alone(ledger, jid) or {}
    value = {"said": str(said), "words": list(dict.fromkeys(list(had.get("words") or ()) + list(words or ())))}
    with ledger.transaction():
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                            (f"{ALONE}{int(jid)}", json.dumps(value, ensure_ascii=False)))


def _forget_alone(ledger, lang, item_id):
    """Michi-RM2: the item's jobs' `alone:` records removed — once one of its jobs (not a level raise) ended done or
    undone; never skipped (`ledger.reopen_skipped` queues that job again under its id, its failures kept: its record
    too) nor dropped (it dropped before mining: it tried none of the failed part's words, whose *Try again* stands —
    review r2). A failed part keeps its own (the problem report names its words). A ledger write that fails is
    logged: a record left is tidiness, never a reason to stop."""
    try:
        with ledger.transaction():
            ledger.conn.execute("DELETE FROM meta WHERE key IN (SELECT ? || id FROM jobs WHERE language = ? AND "
                                "item_id = ?)", (ALONE, lang, item_id))
    except Exception:
        log.warning("Connect couldn't tidy the alone records of item %s", item_id, exc_info=True)


def _alone(ledger, jid):
    """{"said", "words"} when Anki refused a batch of the job (`ALONE`), else None."""
    row = ledger.conn.execute("SELECT value FROM meta WHERE key = ?", (f"{ALONE}{int(jid)}",)).fetchone()
    try:
        got = json.loads(row[0]) if row is not None else None
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def _mine_batch(steps, ledger, lang, job, picked, todo, attempt):
    """One batch -> `steps.mine`'s answer. Mattias #5: after Anki refused a batch of the job (`_alone`), each word goes
    in a call of its own (its own run, `<attempt>-<n>`), so the words Anki takes get their cards and only the ones it
    refuses stay in doubt (`refused`: those words) — merged as one batch, the way `Steps.mine` merges a line-up's
    calls. Not every word sent: your *Stop* between two (`stopped`); a wait, a *Needs you* or a look-up ended at a
    press before a later word (`then`: the caller records the batch, counts no failure, then raises it); a skip or a
    re-pick (the next batch meets it as itself). Every word is tried, a refusal after a refusal too (a give-up cut good
    words, every *Try again* the same way: review r2 B2): a deck, a note type or fields Anki Miner can't use are its
    setup check's before each call (`anki_miner.preflight`: *Needs you*). What still fails for every word (a video
    ffmpeg can't read, a full disk) costs one run a word once, then the part fails as any (review r3 N2)."""
    if not _alone(ledger, job["id"]):
        return steps.mine(lang, job, _part_read(steps, lang, job, picked), todo, attempt)
    got, out, refused = {}, None, []
    for n, word in enumerate(todo):
        if n and stopping.pressed():
            out["stopped"] = True           # #47: pressed between two words: the rest wait with the job
            break
        try:
            done = steps.mine(lang, job, _part_read(steps, lang, job, picked), [word], attempt if n == 0 else
                              f"{attempt}-{n}")
        except (Wait, Needs, stopping.Stopped) as e:
            if out is None:
                raise
            out["then"] = e
            break
        except (Skip, Repick):
            if out is None:
                raise
            break
        row = (done.get("outcomes") or [None])[0]
        if row is not None:
            got[(word["word"], word["reading"])] = row
        if done.get("anki_said") and (row is None or row.get("outcome") in UNSETTLED):
            refused.append(word["word"])
        if out is None:
            out = dict(done, outcomes=None)
        else:
            for flag in ("doubt", "stopped", "anki_said"):
                out[flag] = out.get(flag) or done.get(flag)
            out["tag_pending"] = list(out.get("tag_pending") or ()) + list(done.get("tag_pending") or ())
        if done.get("stopped"):
            break
    out["outcomes"] = [got.get((w["word"], w["reading"])) or dict(_unsure(w), outcome="not_attempted") for w in todo]
    out["refused"] = refused
    return out


def _stop_pressed(ledger, jid):
    """(The job's check, `stopping.watching`: asked by every program the runner waits on, every second — Anki Miner's
    poll and look-ups, tsubasa.) Has *Stop* been pressed on the job? A read that fails is no press (logged): the job
    goes on."""
    try:
        return ledger.stop_asked(jid)
    except Exception:
        log.warning("Connect couldn't look for a Stop on job %s", jid, exc_info=True)
        return False


def _stopped_mid_batch(steps, ledger, lang, job, record):
    """#47: the batch Anki Miner ended at your *Stop*: the job stops at mining as every stop does (`_stopped`: its
    cards recorded and renamed, then it waits for your next ask, the words still unmade)."""
    words = (ledger.picked(job["id"]) or {}).get("words") or []
    if not any(_outcome(ledger, job["id"], w) in UNSETTLED for w in words):
        # every word settled before the cancel took (review A3): nothing left to stop — the job finishes its cards
        ledger.forget_stop(job["id"])
        return
    _stopped(steps, ledger, lang, job, "mining", record)


PROGRESS_STEP = 5               # percent: the job's progress is saved when it moves this far, or its stage changes


class _Progress:
    """Where Anki Miner's run stands, saved in the job while it mines (laptop round 5 #23: the row moves, never *0/57*
    to the end) — only when its stage changes or its percent (`anki_miner.percent`) moves PROGRESS_STEP (S19: a few
    writes a run). Called on the runner's own thread, between its waits on Anki Miner; a write that fails is logged,
    never a reason to stop the batch."""

    def __init__(self, ledger, jid):
        self.ledger, self.jid, self.last = ledger, jid, None

    def __call__(self, progress):
        from app.connect import anki_miner
        key = (progress["stage"], anki_miner.percent(progress) // PROGRESS_STEP)
        if key == self.last:
            return
        self.last = key
        try:
            self.ledger.set_state(self.jid, "mining", progress=progress)
        except Exception:
            log.warning("Connect couldn't save the batch's progress", exc_info=True)


def _name_media(steps, ledger, lang, job, picked=None):
    """The job's made notes' clip and picture renamed by the line (every batch's: a rename a Wait put off is done
    by the next look)."""
    lines = [(o["note_id"], o["line_start"], o["line_end"], o["sentence"]) for o in ledger.outcomes(job["id"])
             if o["outcome"] == "made" and o["note_id"] is not None]
    if lines:
        steps.name_media(lang, job, picked if picked is not None else (ledger.picked(job["id"]) or {}), lines)


def _name_media_at_end(steps, ledger, lang, job):
    """A job that ends here (skipped, failed) still renames the cards it made; one that can't now is left (logged):
    the names are tidiness, never a reason to keep the job (review B #4)."""
    try:
        _name_media(steps, ledger, lang, job)
    except Exception:
        log.warning("Connect couldn't rename the media of a job that ended", exc_info=True)


def _made(ledger, jid):
    """{word: [note id, …]} of the job's made outcomes."""
    made = {}
    for o in ledger.outcomes(jid):
        if o["outcome"] == "made" and o["note_id"] is not None:
            made.setdefault(o["word"], []).append(o["note_id"])
    return made


def _record_made(steps, ledger, lang, job, record):
    """The mining's one store write: every card the job made (G1.3-4 reads it) and the receipt — before any finished
    state too (adversary #6). A busy store → the job waits at mining (`record`: False for a store set up again)."""
    if not record:
        return
    try:
        steps.record(lang, job, _made(ledger, job["id"]), _now() if job.get("kind") != "level" else None, _tag(job))
    except Wait as w:
        raise Wait(w.reason, w.look, "mining") from None
    _through(ledger, lang, "recording")


def _pending(ledger, jid):
    try:
        return json.loads((ledger.job_by_id(jid) or {}).get("tag_pending") or "[]")
    except ValueError:
        return []


def _fail_mining(steps, ledger, lang, job, record=True):
    """A second failure (E11): the cards it did make recorded (and their order owed), the job `failed`, named once in
    Needs you; nothing is tried a third time."""
    _record_made(steps, ledger, lang, job, record)
    _name_media_at_end(steps, ledger, lang, job)
    if _made(ledger, job["id"]):
        with ledger.transaction():
            ledger.owe_resort(lang)
    ledger.set_state(job["id"], "failed", reason=MINE_FAILED)
    # a new try's failure is news (Mattias #5: every *Try again* reacts): an earlier job's entry for the item — seen,
    # dismissed — gives way to this one, which counts again
    title = steps.title(lang, job) or "An episode"
    alone = _alone(ledger, job["id"]) or {}
    said, refused = alone.get("said"), set(alone.get("words") or ())
    words = [w["word"] for w in (ledger.picked(job["id"]) or {}).get("words") or ()
             if w["word"] in refused and _outcome(ledger, job["id"], w) in UNSETTLED]
    if said and words:              # Mattias #5: the words Anki refused alone: named, with Anki's reason
        named = ", ".join(words[:3]) + (f" and {len(words) - 3} more" if len(words) > 3 else "")
        say = MINE_REFUSED_SAY.format(title=title, words=named, why=said,
                                      hint=CLOZE_HINT if UNKNOWN_REASON in str(said) else "")
        kind = MINE_REFUSED
    else:
        say, kind = MINE_FAILED_SAY.format(title=title), "mine-failed"
    with ledger.transaction():
        ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE language = ? AND item_id = ? AND kind IN (?, ?) "
                            "AND fixed_at IS NULL AND COALESCE(job_id, -1) != ?",
                            (_now(), lang, job["item_id"]) + FAILED_KINDS + (job["id"],))
        ledger.need(lang, kind, say, item_id=job["item_id"], job_id=job["id"])
    raise _Finished("failed")


def held_by_cap(asked):
    """Does the cap hold this job? Never one carrying an ask (*Mine now*, *Mine this*, *Mine it too*): your press is the
    yes for that episode's cards, past the cap as past the battery (Sonic's M-3 A, laptop round 7 #42). The one rule
    `_full` and `_at_cap` read."""
    return not asked


def _full(steps, lang, asked=False):
    """Before a job's pick: a Wait when Connect's waiting cards are at the cap and this run's shelf has had its try (it
    can free nothing more until you study), else None — one request, so a job waiting at the cap is never picked
    again at every look. `asked`: the job carries an ask (`held_by_cap`)."""
    if not held_by_cap(asked) or not getattr(steps, "shelf_tried", lambda _lang: False)(lang):
        return None
    cap = steps.cap(lang)
    if not cap:
        return None
    count = steps.waiting_count(lang)
    if count is None or count < cap:
        return None
    return Wait(f"Your {count} cards are waiting: Connect makes more as you study them.", resume="mining")


def _at_cap(steps, ledger, lang, todo, asked=False):
    """P2.4 Part B (the cap, the shelf): a Wait when Connect's waiting cards are at the learner's cap, else None. At the
    cap the shelf is asked first (once a run, only on a big gap); what it frees may let this batch go. `asked`: the
    job carries an ask — never held, nothing shelved for it (`held_by_cap`)."""
    if not held_by_cap(asked):
        return None
    cap = steps.cap(lang)
    if not cap:
        return None
    count = steps.waiting_count(lang)
    if count is None or count < cap:
        return None
    if steps.shelve(lang, ledger, todo, count, cap):
        count = steps.waiting_count(lang)
        if count is not None and count < cap:
            return None
    return Wait(f"Your {count} cards are waiting: Connect makes more as you study them.", resume="mining")


def _outcome(ledger, jid, word):
    row = ledger.conn.execute("SELECT outcome FROM outcomes WHERE job_id = ? AND word = ? AND reading = ?",
                              (jid, word["word"], word["reading"])).fetchone()
    return row[0] if row else None


def _row(got, word):
    key = (word["word"], word["reading"])
    return next((o["outcome"] for o in got["outcomes"] if (o["word"], o["reading"]) == key), None)


def _merge(outcomes, found, also=()):
    """Anki Miner's outcomes, a word it left unsettled (or one of `also`) replaced by its card found by tag."""
    better = {(o["word"], o["reading"]): o for o in found if o["outcome"] == "made"}
    return [better.get((o["word"], o["reading"]), o) if o["outcome"] in UNSETTLED or o["outcome"] in also else o
            for o in outcomes]


def _enriched(outcomes, by_key):
    """Anki Miner's outcomes with the pick's line (start, end, sentence) and predicted class (N6, D1)."""
    out = []
    for o in outcomes:
        w = by_key.get((o["word"], o["reading"]), {})
        out.append(dict(o, orth=w.get("orth"), line_start=w.get("line_start", o.get("line_start")),
                        line_end=w.get("line_end"), sentence=w.get("line_text"), predicted=w.get("predicted_class")))
    return out


def _failures(ledger, jid):
    return int(ledger.job_by_id(jid).get("failures") or 0)


def _count_failure(ledger, jid):
    with ledger.transaction():
        ledger.conn.execute("UPDATE jobs SET failures = failures + 1 WHERE id = ?", (jid,))


def _skipped(ledger, jid, step, why):
    """The job's skipped steps, with `step` named (its `skipped` column, read and added to)."""
    row = ledger.job_by_id(jid) or {}
    try:
        had = json.loads(row.get("skipped") or "{}")
    except ValueError:
        had = {}
    had[step] = why
    return had


def _fill(steps, ledger, lang, job):
    jid = job["id"]
    ledger.set_state(jid, "filling")
    ids = ledger.undo_record(jid)
    if not ids:
        ledger.set_state(jid, "ordering")
        return
    _queue_ai_audio(steps, ledger, lang, job, ids)     # Iro-AA: before Backfill, which fills other fields
    wait = _blocked(steps, lang, "filling", asked=bool(job.get("asked_at")))
    if wait is not None:
        raise wait
    pending = _pending(ledger, jid)
    if pending:                             # the names' tag, before anything else touches the notes (adversary #7)
        steps.tag_names(lang, pending)
        ledger.set_state(jid, "filling", tag_pending=None)
    try:
        steps.fill(lang, job, ids)
    except Wait as w:
        raise Wait(w.reason, w.look, "filling") from None
    except Skip as s:
        ledger.set_state(jid, "ordering", skipped=_skipped(ledger, jid, "filling", s.why))
        return
    except Needs as n:
        _need(ledger, lang, n, job)
        had = json.loads((ledger.job_by_id(jid) or {}).get("skipped") or "{}").get("filling")
        ledger.set_state(jid, "filling", skipped=_skipped(ledger, jid, "filling", n.say))
        if had is None and not n.whole:     # Backfill failed: tried again at the next start, once (adversary #13);
            # a setting of the language's (no deck chosen) waits for you, never the episode: it goes on unfilled
            raise Wait(n.say, look=False, resume="filling") from None
        ledger.set_state(jid, "ordering")
        return
    _through(ledger, lang, "filling")
    skipped = json.loads((ledger.job_by_id(jid) or {}).get("skipped") or "{}")
    if skipped.pop("filling", None) is not None:        # filled at its second try: nothing left to name
        ledger.set_state(jid, "ordering", skipped=skipped or None)
        return
    ledger.set_state(jid, "ordering")


def _order(steps, ledger, lang, job):
    jid = job["id"]
    ledger.set_state(jid, "ordering")
    if not ledger.undo_record(jid) and not ledger.resort_owed(lang):
        return
    wait = _blocked(steps, lang, "ordering", asked=bool(job.get("asked_at")))
    if wait is not None:
        raise wait
    try:
        deferred = steps.order(lang, job) == DEFERRED
    except Wait as w:
        raise Wait(w.reason, w.look, "ordering") from None
    except Skip as s:
        ledger.set_state(jid, "ordering", skipped=_skipped(ledger, jid, "ordering", s.why))
        return
    except Needs as n:
        _need(ledger, lang, n, job)
        ledger.set_state(jid, "ordering", skipped=_skipped(ledger, jid, "ordering", n.say))
        return
    if not deferred:                        # 順 ran (a deferred order never asked it): its deck is there
        _through(ledger, lang, "ordering")
    with ledger.transaction():
        if deferred:
            ledger.owe_resort(lang)         # the Generate after mining orders Anki from its new list (F11)
        else:
            ledger.resort_paid(lang)


# --------------------------------------------------------------------------- #
# The real steps: the command line's own verbs, in this process
# --------------------------------------------------------------------------- #
class Steps:
    """What the loop asks of Anki, Anki Miner, the store and the list. Each method raises Wait / Needs / Skip /
    Repick as the loop reads them; a test hands its own (`tests/connect/test_runner.py`)."""

    def __init__(self, loaded, live=False):
        self.loaded = loaded
        self.live = live            # the run's own steps: what may change while it runs (the cap) read from the file
        from app.connect import kick
        self._woken = kick.wake_stamp()     # the wake mark as the run found it: a kick since ends a pause (#42)
        self._began = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())     # the ledger's stamps' form
        from app import anki_connect
        self.url = anki_connect.address(loaded)
        self._current = {}          # {lang: replan.Current}: the plan this run mines and orders from (P3.3)
        self._after = {}            # {lang: why}: a Generate owed once this run's mining is done (F11)
        self._served = set()        # the languages whose run plan the engine serves (prepare's, the Generate after
                                    # mining's): a plan read since that it can't serve defers the re-order (#4)
        self._anki_miner_sets = {}  # {lang: the set}: this run's Anki Miner look-ups, read once (LF-mining row 25)
        self._gone_looked = set()   # the languages whose deleted-cards look ran this run (`notes_gone`: once a run)

    # --- the run ------------------------------------------------------------------------------------------- #
    def lower_priority(self):
        from app.connect import power
        power.lower_priority()

    def update_staged(self):
        from app import library_store
        return library_store.update_staged(looks=library_store.PROBE_LOOKS)

    def window_open(self):
        """Haya-CL: is a Surasura window open — any install of this data name (`locks.running_others`: a running mark
        of kind "window"; a mark whose record can't be read yet, a window just starting, counts as one)?"""
        from app import locks
        return any(_a_window(r.get("kind")) for r in locks.running_others())

    def replaced(self):
        """Haya-CL: does the program folder hold another build than this running program (`build_info.stamp_skew`:
        Setup or a swap put a newer Surasura under it)? From source: never."""
        from app import build_info
        return build_info.stamp_skew() is not None

    def kicked(self):
        """Has a kick stamped the wake mark since the last look at it (`kick.wake_stamp`)? Then the mark is taken as
        seen: one wake a kick. -> False, True, or `kick.VIDEOS` for a kick that may have found videos (MV-2)."""
        from app.connect import kick
        now = kick.wake_stamp()
        if now == self._woken:
            return False
        self._woken = now
        if not (isinstance(now, str) and now.endswith("-" + kick.VIDEOS)):
            return True
        self._videos_again()
        return kick.VIDEOS

    def _videos_again(self):
        """A kick that may have found videos (a video linked, a video folder added: Michi-VF, Mattias 3.0.0): the
        folders settings.json holds now, and a language whose folders changed has its video index made again at its
        next use (`_videos`) — a folder you add while this run waits on an episode's video is looked in this run, never
        only at Connect's next start. Unchanged folders keep the run's index (its one re-list a run: S19). An
        unreadable settings.json keeps the folders the run had."""
        from app.connect import videos
        try:
            from app.cli import verbs
            now = verbs.settings()
        except Exception:
            log.warning("Connect couldn't read the video folders again; it keeps this run's", exc_info=True)
            return
        was = getattr(self, "_video_folders", None) or self.loaded
        made = getattr(self, "_video_index", {})
        for lang in [lang for lang in made if videos.configured(now, lang) != videos.configured(was, lang)]:
            del made[lang]
        self._video_folders = now

    def enabled(self):
        """Connect's switch as settings.json holds it now (read again at every look and before each job): off, or
        a file that can't be read, stops the run. 3.0 (P3.3 C1): D29's switch (`logic.automation`) off stops it too —
        no automatic mining with the automation off (the one gate, `settings_manager.connect_on`: P4.1 row 4.1.1)."""
        from app import settings_manager
        from app.cli import verbs
        try:
            return settings_manager.connect_on(verbs.settings())
        except Exception:
            return False

    def settle(self):
        from app.cli.verbs import _session
        session = _session(self.loaded)
        if session is not None:
            session.settle(self.url, self.loaded)

    # --- the library --------------------------------------------------------------------------------------- #
    def _store(self, lang):
        from app.connect import library
        store = library.open_store(lang)
        if store is None:
            raise Needs("no-store", "Surasura's library isn't ready for Connect: open Surasura once.", whole=True)
        return store

    def consume(self, lang, ledger):
        """The inbox and the level raise's look (P2.1, P2.2), as `connect --consume-only` reads them."""
        from app.cli import connect_verbs
        from app.connect import inbox, library
        store = library.open_store(lang)
        if store is None:
            return
        with store:
            connect_verbs._store_write(lambda: inbox.consume(store, lang, ledger), WAIT_S)
            connect_verbs._level(store, lang, self.loaded)

    def _open(self, lang):
        """The language's store for a read or write the loop can't do without -> the store; a store busy past the
        store's own wait → Wait (looked at again); none to write (JSON mode, read-only, damaged) → Needs."""
        from app import library_store
        from app.connect import library
        from app.path_utils import get_data_path
        store = library.open_store(lang)
        if store is not None:
            return store
        mode, reason = library_store.check_mode(lang, get_data_path(lang), busy_wait=0.0)
        if mode == "store" or reason == "busy":
            raise Wait(LIBRARY_BUSY)
        raise Needs("no-store", "Surasura's library can't be written just now, so Connect can't make cards. Open "
                                "Surasura to see why.", whole=True)

    def mine_line(self, lang):
        from app.connect import library
        with self._open(lang) as store:
            return library.mine_line(store)

    def store_id(self, lang):
        from app.connect import library
        with self._open(lang) as store:
            return library.store_id(store)

    def waiting_items(self, lang, item_ids):
        """Alpha 4 M1 / A4M1-3 (was P4.1's K67 `text_only`): of `item_ids`, those Anki Miner can't mine yet ->
        {item id: kind} by `library.waits_for` (books and texts by their file's type, in one store read; audio by
        their title's type, and only while no video is found for it — a video podcast is mined as before, review
        A2-1); an audio item whose video lookup can't answer now is UNKNOWN (neither set aside nor queued again); a
        busy store → None (nothing moves: the next look asks again, round 2 R2-1)."""
        from app.connect import library
        try:
            store = self._open(lang)
        except (Wait, Needs):
            return None
        out, audio = {}, []
        with store:
            for i in item_ids:
                item = store.item(i) or {}
                kind = library.waits_for(item, library.media_of(store, item))
                if kind == "audio":
                    audio.append(i)
                elif kind:
                    out[i] = kind
        for i in audio:
            try:
                if self.video(lang, {"item_id": i, "language": lang}) is None:
                    out[i] = "audio"
            except (Wait, Needs):
                out[i] = UNKNOWN            # can't be told now: left as it is (round 2 R2-1)
        return out

    def mines(self, lang, kind):
        """Alpha 4 M1 / A4M1-3: can Connect make cards from `kind` ("books", "audio") now — this Surasura knows its ask
        and the Anki Miner its setup record last found names it (`anki_miner.mines`)? No record yet: no."""
        from app.connect import anki_miner
        return anki_miner.mines_now(kind)

    def show(self, lang, job):
        """The title of the show the job's episode belongs to (its work's), for the cards' `Surasura::from::` tag; None
        when the store can't say (busy, no work): the cards then carry no show tag, never a wrong one."""
        from app.connect import library
        try:
            store = self._open(lang)
        except (Wait, Needs):
            return None
        try:
            with store:
                return library.show_title(store, job["item_id"])
        except Exception:               # round 2 B8: a store that can't be read here never fails the mining
            return None

    def watched(self, lang, job):
        """Laptop round 8 #49: is the job's episode one Connect makes no new cards from on its own (`level.watched_out`:
        marked watched, while 3.0's rule holds)? A busy store -> False (the job goes on as before)."""
        try:
            store = self._open(lang)
        except (Wait, Needs):
            return False
        with store:
            item = store.item(job["item_id"]) or {}
        from app.connect import level
        return level.watched_out(item)

    def title(self, lang, job):
        try:
            store = self._open(lang)
        except (Wait, Needs):
            return None                     # a title only names the episode in a message
        with store:
            item = store.item(job["item_id"]) or {}
        entry = item.get("entry") or {}
        return entry.get("title") or (os.path.basename(item.get("rel_path") or "") or None)

    def pairing(self, lang, job):
        """The item's pairing; a busy store is a Wait, never "no pairing" (adversary P2.4-A #10)."""
        from app.connect import library
        with self._open(lang) as store:
            return library.pairing_of(store, job["item_id"])

    def heard(self, lang, job):
        """Hato-SP: was the item's text made from its video's audio by another tool (`library.heard`)? A busy
        store is a Wait."""
        from app.connect import library
        with self._open(lang) as store:
            return library.heard(store, job["item_id"])

    def reading(self, lang, job):
        """Z-9: (the file Anki Miner reads, the EPUB or None) when the job's item is a book or a text
        (`library.waits_for`), else None (`connect.reading.source`: the EPUB a part was cut from, else the item's own
        text). A busy store is a Wait."""
        from app.connect import library, reading
        with _held():
            with self._open(lang) as store:
                item = store.item(job["item_id"]) or {}
                if library.waits_for(item) != "books":
                    return None
                pairing = library.pairing_of(store, job["item_id"])
            path = self.subtitle(lang, job)
        if not path:
            return None
        found, book = reading.source(path, pairing)
        return reading.as_text(found, self.run_dir(job), lang), book

    def subtitle(self, lang, job):
        from app.path_utils import get_data_path
        with self._open(lang) as store:
            item = store.item(job["item_id"])
        if item is None:
            return None
        return os.path.join(get_data_path(lang), *str(item["rel_path"]).replace("\\", "/").split("/"))

    def video(self, lang, job):
        """The episode's video on this computer: hato's pairing names it; else a video beside the subtitle with its
        name; else one beside the original it was copied from (K21: a folder's or + Add's origin, `beside_origin`);
        else the video index (P2.5 row 2.5.8, G1.3-12: the paired videos' folders and the ones you added — by
        name, and size when the pairing gives one). None when there's none, or only a cloud placeholder (never
        opened, RD-S1)."""
        with _held():                       # the store's two reads, one open; the disk is looked at after
            pairing = self.pairing(lang, job) or {}
            named = pairing.get("video_path")
            paired = isinstance(named, str) and bool(named)
            subtitle = None if paired else self.subtitle(lang, job)
        from app.connect import videos
        was = lambda: self.moved_videos(lang, job)      # noqa: E731  (D5: read only once its own video is gone)
        if paired:                          # the index is made (and listed) only once the named path isn't on disk
            return paired_video(pairing, lambda names, size: self._videos(lang).find(names, size), was=was)
        if not subtitle:
            return None
        names = videos.names_for(subtitle)
        origin = origin_of(pairing)
        if origin:
            names += videos.names_for(origin)   # a copy renamed `name (2)` in Library/: the original's name finds it
        moved = moved_video(was()) if pairing.get("producer") == "source" else None    # a source record's own
        return beside(subtitle) or beside_origin(pairing) or moved or self._videos(lang).find(names)

    def online(self, lang, job):
        """Michi-YT: the online title the job's episode is (its item a YouTube or bilibili.tv transcript) ->
        `online.of`'s {"site", "url", "names"}, else None. A busy store is a Wait."""
        from app.connect import online
        with _held():
            with self._open(lang) as store:
                item = store.item(job["item_id"]) or {}
            if not online.is_online(item):
                return None
            pairing = self.pairing(lang, job)
        return online.of(lang, item, pairing)

    def download(self, lang, job, web, on_progress=None):
        """Michi-YT (Sonic 2026-11-07): the online title's video and its captions, fetched by Anki Miner (`online.fetch`)
        into Connect's own folder for this job -> (video, subtitle); kept for the job while this run works on it (a
        pick again after a profile change fetches nothing); None when Anki Miner isn't installed. The YouTube risk tick
        (`youtube_risk_acknowledged`, the downloader's own) is its yes. Raises Needs (`online.KIND`: the language's
        trouble `standing`, else the episode's, with its title), Wait (an update staged mid-download: it ended, the
        video goes), `stopping.Stopped` (your *Stop*: Anki Miner ended within a second)."""
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import anki_miner, online
        kept = getattr(self, "_fetched", {}).get(str(job["id"]))
        if kept and all(_on_disk(p) for p in kept):
            return kept
        if self._settings(lang).get("youtube_risk_acknowledged") is not True:
            raise Needs(online.KIND, online.NOT_TICKED, standing=True)

        def own(say):
            title = self.title(lang, job)
            return Needs(online.KIND, f"{title}: {say}" if title else say, once=True)
        held = getattr(self, "_online_trouble", {}).get(lang)
        if held:                            # review S4: offline / a bot check this run: no other fetch tried
            raise Needs(online.KIND, held, standing=True)
        if web.get("site") != "youtube":
            raise own(online.BILIBILI)
        if not web.get("url"):
            raise own(online.NO_LINK)
        miner = anki_miner.find(self.loaded)
        if miner is None:
            return None
        try:
            setup = verbs._anki_miner_setup(self.loaded, lang, self.run_dir(job), held=self._anki_miner_held(lang))
        except CliError as e:
            raise _wait_or_needs(e, None, self.url) from None
        if setup is None:
            return None
        if "Z-8" not in anki_miner.features(setup[0]):
            raise Needs(online.KIND, online.NO_FETCH, standing=True)
        staged = []

        def should_end():
            if self.update_staged():
                staged.append(True)
                return True
            return False
        try:
            got = online.fetch(miner, setup[1], lang, job["id"], web["url"], on_progress=on_progress,
                               should_end=should_end)
        except stopping.Stopped:
            if staged:
                raise Wait(STOPPED_FOR_UPDATE, look=False) from None
            raise
        except online.Trouble as t:
            if t.standing:
                if t.say in online.HELD or youtube_hold.is_words(t.say):    # offline, a bot check (its hold,
                    # Yt-B), no room: no other fetch this run (review r2 S1)
                    self._online_trouble = dict(getattr(self, "_online_trouble", {}), **{lang: t.say})
                raise Needs(online.KIND, t.say, standing=True) from None
            raise own(t.say) from None
        except anki_miner.AnkiMinerError as e:
            self._anki_miner_held(lang).clear()
            raise _miner_wait_or_needs(e, self.url) from None
        self._fetched = dict(getattr(self, "_fetched", {}), **{str(job["id"]): got})
        return got

    def drop_online(self, job):
        """Michi-YT: the job's downloaded video gone (`online.drop`), and forgotten."""
        from app.connect import online
        getattr(self, "_fetched", {}).pop(str(job["id"]), None)
        online.drop(job["id"])

    def sweep_online(self):
        from app.connect import online
        self._fetched = {}
        online.sweep()

    def audio(self, lang, job):
        """Z-16 (Michi-AB A1, PROVISIONAL): the audio file an episode with no video is cut from -> (path, None); else
        (None, the wait line for an audio item — `NO_AUDIO`, `SEVERAL_FILES`, `NO_TEXT` — or None for any other item:
        its *No video*). One rule: an audiobook's own item is cut from its record's one file while its transcript is
        its text (`library.audiobook_file`; several files: `SEVERAL_FILES`, A5; no text of its own: `NO_TEXT`), never
        from a file looked for beside anything (its origin is its own first file: review AB-2); any other item from an
        audio file with the subtitle's own name beside it, or beside the file it was copied from (`beside` /
        `beside_origin`, the audio extensions) — only when the item is audio (`library.waits_for`: an audiobook's or
        a podcast's title) or that file is an audiobook's the library knows (one subtitle per audio file): an anime
        episode whose video is gone is never mined from an audio file beside it (review AB-3). A cloud placeholder is
        never one (`_on_disk`)."""
        from app.audiobooks import AUDIO_EXTENSIONS
        from app.connect import library
        with _held():                       # the store's reads, one open; the disk is looked at after
            pairing = self.pairing(lang, job) or {}
            subtitle = self.subtitle(lang, job)
            with self._open(lang) as store:
                item = store.item(job["item_id"]) or {}
                heard = library.waits_for(item, library.media_of(store, item)) == "audio"
                own = library.audiobook_file(store, job["item_id"])
                known = library.audiobook_files(store) if own is None and not heard else None
        if own is not None:
            path, n = own
            if path:
                return (path, None) if _on_disk(path) else (None, NO_AUDIO)
            return None, (SEVERAL_FILES.format(n=n) if n > 1 else NO_TEXT)
        found = (beside(subtitle, AUDIO_EXTENSIONS) if subtitle else None) or \
            beside_origin(pairing, AUDIO_EXTENSIONS)
        if found and (heard or os.path.normcase(os.path.abspath(found)) in known):
            return found, None
        return None, (NO_AUDIO if heard else None)

    def moved_videos(self, lang, job):
        """D5 (MV-A5): (path, size) of the videos the item's origins marked moved named (`library.moved_videos`);
        () with no store to read (nothing marked there). A busy store is a Wait."""
        from app.connect import library
        try:
            store = self._open(lang)
        except Needs:
            return ()
        with store:
            return library.moved_videos(store, job["item_id"])

    def video_moved(self, lang, job):
        """MV-2: the folder this episode's video left (`video_left`), asked once `video` found none -> it, or None."""
        from app.connect import library
        with _held():
            pairing = self.pairing(lang, job) or {}
            try:
                store = self._open(lang)
            except Needs:
                return None
            with store:
                root = library.moved_of(store, job["item_id"], pairing).root
        return video_left(pairing, root)

    def _videos(self, lang):
        """The language's video index, refreshed once a run, the first time a video is missing (S19: only folders
        whose time moved are listed again). The folders the store reads as sources (SRC M1: the ones on) are indexed
        as the folders you added are, as deep: a subtitle in `Show/Subs/` finds `Show/ep.mkv`, and a video that came
        after its subtitle is found by name. A source offline keeps what it last listed (the index's own rule)."""
        from app.connect import library, videos
        made = getattr(self, "_video_index", {})
        if lang not in made:
            with self._open(lang) as store:
                shallow = sorted({os.path.dirname(r["video_path"]) for records in library.pairings(store).values()
                                  for r in records if isinstance(r, dict) and isinstance(r.get("video_path"), str)
                                  and r["video_path"]})
                sources = [s["path"] for s in store.sources(counts=False)]
            index = videos.Index(lang)
            added = getattr(self, "_video_folders", None) or self.loaded     # read again at a videos kick (Michi-VF)
            index.refresh(shallow, videos.configured(added, lang), sources=sources)
            made[lang] = index
            self._video_index = made
        return made[lang]

    def record(self, lang, job, made, mined_at, batch):
        """The mining's one store write (receipt + made words): a busy store is looked at again, one that can't be
        written is Needs you — the job never goes on without its record (G1.3-4 reads it)."""
        from app import library_store
        from app.connect import library
        with self._open(lang) as store:
            try:
                library.record_batch(store, job["item_id"], made, mined_at, batch)
            except library_store.StoreBusy:
                raise Wait(LIBRARY_BUSY) from None
            except library_store.StoreReadOnly:
                raise Needs("no-store", "Surasura's library can't be written just now, so Connect can't record the "
                                        "cards it made. Open Surasura to see why.", whole=True) from None

    # --- Anki and its tools -------------------------------------------------------------------------------- #
    def blocked(self, lang):
        """The one reason Connect can't touch Anki now, or None: on battery first, then the session's (Anki closed,
        busy, another profile, no profile named yet, you reviewing — the session records the first one Anki names
        as Connect's, laptop round 5 #22)."""
        from app.connect import power
        if os.environ.get("SURASURA_NO_ANKI_SYNC"):     # the test suites, a developer's run: Anki is never reached
            return Wait(ANKI_OFF, look=False)
        if power.on_battery():
            return ON_BATTERY
        return self.session_blocked(lang)

    def session_blocked(self, lang):
        """The session's reason alone (Anki closed, busy, another profile, none named yet, you reviewing), or None —
        what still holds a job carrying an ask on battery (M-3)."""
        from app.connect import anki_session
        if os.environ.get("SURASURA_NO_ANKI_SYNC"):
            return Wait(ANKI_OFF, look=False)
        return anki_session.waiting(self.url, self.loaded)

    def on_battery(self):
        from app.connect import power
        return power.on_battery()

    def queue_ai_audio(self, lang, note_ids, job):
        """Iro-AA: a book part's new cards on the AI voice's waiting list (`modules.irodori`; absent: nothing)."""
        try:
            from modules import irodori
        except ImportError:
            return 0
        return irodori.queue_notes(lang, note_ids, source={"job": job.get("id"), "item": job.get("item_id")})

    def ai_audio(self, lang, should_stop):
        """Iro-AA: the AI voice's waiting list made — the beta on, the voice installed, the shared writer there; else it
        waits (`irodori.run_queue`). settings.json read now, and again between two sentences: the beta switched off in
        the window stops it (review r2 #4). The cards it wrote: the session's sync clock, as any new write (S3)."""
        try:
            from modules import irodori
        except ImportError:
            return None
        from app import settings_manager

        def fresh():
            try:
                return settings_manager.load_settings(strict=True)
            except Exception:
                return {}                       # unreadable now: read as off (nothing made)
        got = irodori.run_queue(fresh(), lang, should_stop=lambda: bool(should_stop() or not irodori.enabled(fresh())))
        if got.get("written"):              # each run's Undo is kept by the module (`irodori.last_run`)
            log.info("Connect: AI sentence audio added to %d cards (%s)", got["written"], lang)
            self.after_write(lang)
        return got

    def after_write(self, lang):
        """New cards made: the session's sync clock (S3; P2.3's rule), then the Anki backlog read again, so the
        window's count of new cards follows within its 3 s look (laptop round 5 #27: whoever adds cards reads the
        backlog after) — never fatal."""
        from app.cli import verbs
        from app.connect import anki_session
        try:
            anki_session.after_write(self.loaded, True)
        except Exception:
            log.exception("Connect couldn't note its write for Anki's sync")
        try:
            verbs._backlog_read(self.loaded, lang, after_cards=True)
        except Exception:
            log.exception("Connect couldn't read Anki's new cards again")

    def miner_found(self):
        from app.connect import anki_miner
        return anki_miner.find(self.loaded) is not None

    def tag_names(self, lang, note_ids):
        """The names' tag Anki didn't take after a batch, added now under Anki's write lock (never while you
        review)."""
        from app import anki_connect, locks
        from app.connect import runfile
        try:
            held = anki_connect.writer("Connect's name tags", wait=WAIT_S)
        except locks.Busy:
            raise Wait(WRITER_BUSY, resume="filling") from None
        with held:
            try:
                if anki_connect.reviewing(self.url):
                    raise Wait(REVIEWING, resume="filling")
                anki_connect.invoke("addTags", self.url, notes=list(note_ids), tags=runfile.NAME_TAG)
            except anki_connect.AnkiError as e:
                raise _anki_wait(self.url, "filling", e) from None

    def prepare(self, lang, ledger):
        """Once a run, per language: the session's sync, one known-sync, then the plan's verdict (P3.3,
        `replan.current`): a Generate first only when the plan can't serve the library as it stands (a changed file,
        no plan, another engine, a lowered level: "first"); known words, new files alone (P4.1 C5) or a level raise
        ("after"): marked, the Generate runs once mining is done (`generate_after`, F11); only the order moved
        ("no"): no Generate at all."""
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import anki_session
        holds = verbs._results_language()
        if WAIT_FOR_OTHER_LIST and holds and holds != lang:
            raise Wait(OTHER_LIST.format(LANGUAGE_NAMES.get(holds, holds)))
        anki_session.begin(self.url, self.loaded)
        ns = SimpleNamespace(lang=lang, wait=WAIT_S, full=False, force=False)
        try:
            verbs.known_sync(ns)
        except CliError as e:
            if e.code in ("anki-closed", "anki-busy", "busy", "settings-unreadable"):
                raise (_anki_wait(self.url) if e.code == "anki-closed" else Wait(e.message)) from None
            raise Needs("known-sync", e.message) from None
        got = self.current(lang, fresh=True)        # after the known-sync: its new words are part of the verdict
        if got.generate == "first":
            self._generate(ns, "Generate didn't finish, so Connect waits for a current list.", ledger)
            got = self.current(lang, fresh=True)
        if got.generate == "after":
            self._after[lang] = got.reason
        else:
            self._after.pop(lang, None)
        self._serves(lang, got)
        self._shelved = set()
        try:
            self.notes_gone(lang)
            self.shelf_session(lang, ledger)
        except ImportError:                 # Junban isn't installed: no shelf, named (S10)
            self._say(lang, SHELF_NO_JUNBAN)
        except Exception:                   # never a reason not to mine: looked at again next run
            log.exception("Connect's shelf look or deleted-notes check didn't finish")

    def _generate(self, ns, say, ledger=None):
        """`surasura-cli generate` in this process: a moment's state (another Generate, settings.json caught
        mid-save) is a Wait, anything else *Needs you* with its log (E29). P4.1 row 4.1.7 (F9): `ledger`'s
        `generating:<lang>` mark is set while it runs and cleared however it ends — the status line's *Connect is
        updating your list*."""
        from app.cli import verbs
        from app.cli.contract import CliError
        _updating(ledger, ns.lang, True)
        try:
            return verbs.generate(ns)
        except CliError as e:
            if e.code in ("busy", "settings-unreadable"):     # exit 3: a moment's state, looked at again
                raise Wait(e.message) from None
            raise Needs("generate", f"{say} {e.message}") from None
        finally:
            _updating(ledger, ns.lang, False)

    def _settings(self, lang):
        """settings.json as it is now, for `lang` (the analyzer's argv is built from it), else this run's."""
        from app.cli import verbs
        try:
            loaded = verbs.settings()
        except Exception:
            loaded = self.loaded
        return dict(loaded, target_language=lang)

    def current(self, lang, fresh=False):
        """P3.3: the plan this run mines and orders from (`replan.current`), kept for the run and read again when
        the store's order or pins, the plan file or the run stamp moved since (`replan.key`: a move mid-run is
        re-planned before the next pick or re-order), or the settings the verdict reads (`replan.settings_key`: the
        band lowered with the window closed is read again, never ordered from the old plan: #4, H10). A busy store is
        a Wait; none to read is Needs (`_open`). A key that can't be read counts as moved: `replan.current`'s guarded
        read answers (review H9)."""
        from app.connect import replan
        kept = self._current.get(lang)
        settings = self._settings(lang)
        with self._open(lang) as store:
            if kept is not None and not fresh:
                try:
                    same = (replan.key(store) == kept.key
                            and replan.settings_key(settings, lang) == kept.settings_key)
                except Exception:
                    same = False
                if same:
                    return kept
            got = replan.current(lang, settings, store, previous=kept)
        self._current[lang] = got
        return got

    def _plan_now(self, lang):
        """`current`; a busy store is a Wait (the pick, the shelf and the re-order wait and look again, as every
        busy-store read does: review H8); None only when there is no store to read (Needs: they read the list as
        today, never worse)."""
        try:
            return self.current(lang)
        except Needs:
            return None

    def generate_after(self, lang, ledger):
        """F11: the Generate a plan marked "after" owes, once this run's mining is done -> True when it ran (the
        plan read again from its new list), False when none was owed. Raises Wait / Needs from the Generate (mining
        already done: only the list's refresh waits). The Generate going through is what counts: a plan that can't
        be read again just now (a busy store) is the follow-up's to read (review H5)."""
        why = self._after.pop(lang, None)
        if why is None:
            return False
        log.info("Connect: Generate after mining (%s): %s", lang, why)
        self._generate(SimpleNamespace(lang=lang, wait=WAIT_S, full=False, force=False),
                       "Generate didn't finish after Connect made its cards: your list catches up at the next one.",
                       ledger)
        try:
            self._serves(lang, self.current(lang, fresh=True))
        except (Wait, Needs) as e:
            log.info("Connect: the plan after the Generate is read at the follow-up (%s): %s", lang, e)
        return True

    def _serves(self, lang, got):
        """The run's plan, read fresh (prepare's, the Generate after mining's): does the engine serve it (`_served`;
        #4)? None of it -> the re-order reads the list as today (stand-aside, coverage)."""
        if got is not None and got.result is not None:
            self._served.add(lang)
        else:
            self._served.discard(lang)

    # --- P2.4 Part B: the cap, the shelf, media names, deleted cards ------------------------------------------- #
    def _anki(self):
        from app.connect import shelf
        return shelf.AnkiConnectAnki(self.url)

    def cap(self, lang=None):
        """`connect_backlog_cap` for `lang` — one cap per language (Sonic 2026-10-08, P2.4-B-SD4 changed; charter D31):
        a number is every language's cap, `{lang: n}` each its own (300 for one it doesn't name); 0: no cap; not a
        number: the default (review B #1) — `settings_values.cap_of`, Settings' own reading. The run's steps (`live`)
        read settings.json as it is now (`_settings`), so a cap raised in Settings reaches a Connect already waiting
        at the old one (laptop round 7 #42); a test's steps read the dict they were handed."""
        from app.connect.settings_values import cap_of
        loaded = self._settings(lang) if self.live else self.loaded
        return cap_of(loaded.get("connect_backlog_cap", 300), lang)

    def waiting_count(self, lang):
        """The cards waiting in Anki for `lang` — one count everywhere (laptop round 7 #41, Sonic's B3-2 A, 2026-10-22):
        every new, unsuspended note in the decks you chose for it plus Connect's own, wherever they are
        (`anki_sync.backlog_query(decks, connect=True)`: the bottom bar's *Anki · N waiting* is that search's saved
        answer, `anki_backlog.json`). A suspended card isn't waiting: your suspend says "known", Surasura's sets it
        aside. Your own new cards count toward the cap too. One cap per language (D31): Connect's notes count only
        those this language's store made (the tag spans every language; review r2 #2). Decks read as settings.json
        holds them now (`live`). Notes, as the bottom bar counts them."""
        from app import anki_connect, anki_sync
        from app.connect import shelf
        loaded = self._settings(lang) if self.live else self.loaded
        decks = list((loaded.get("anki_sync_decks") or {}).get(lang) or [])
        with self._open(lang) as store:
            made = shelf.made_notes(store)
        try:
            notes = set(anki_connect.find_notes(self.url, anki_sync.backlog_query(decks))) if decks else set()
            notes |= set(anki_connect.find_notes(self.url, anki_sync.backlog_query([], connect=True))) & set(made)
        except anki_connect.AnkiError as e:
            raise _anki_wait(self.url, "mining", e) from None
        return len(notes)

    def _list_order(self, lang):
        """{(Word, Reading): place} in the list's own order (Junban's), or None: the re-plan's (P3.3) when the plan
        serves the library as it stands, else the last Generate's list."""
        from app.cli import verbs
        from app.cli.contract import CliError
        got = self._plan_now(lang)
        if got is not None and got.listed is not None:
            return got.listed
        try:
            return verbs._listed(SimpleNamespace(wait=WAIT_S), lang)
        except CliError:
            return None

    def shelve(self, lang, ledger, todo, count, cap):
        """At the cap, once a run per language: the shelf's plan (a big gap only), shelved -> how many. A look that
        waits (you review, another writer, Anki gone) spends no try (review B #2, #3)."""
        from app import anki_connect, locks
        from app.connect import shelf
        if lang in getattr(self, "_shelved", set()):
            return 0
        try:
            shelved = self._shelve(lang, ledger, todo, count, cap)
        except ImportError:                 # Junban isn't installed: the shelf is skipped and named (S10)
            self._shelved = getattr(self, "_shelved", set()) | {lang}
            self._say(lang, SHELF_NO_JUNBAN)
            return 0
        except shelf.Reviewing:
            raise Wait(REVIEWING, resume="mining") from None
        except locks.Busy:
            raise Wait(WRITER_BUSY, resume="mining") from None
        except anki_connect.AnkiError as e:
            raise _anki_wait(self.url, "mining", e) from None
        self._shelved = getattr(self, "_shelved", set()) | {lang}
        return shelved

    def shelf_tried(self, lang):
        """Has this run's shelf had its one try for `lang`?"""
        return lang in getattr(self, "_shelved", set())

    def _shelve(self, lang, ledger, todo, count, cap):
        from app.connect import shelf
        order = self._list_order(lang) or {}
        ranks = shelf.ranks(order)
        with self._open(lang) as store:
            made = shelf.made_notes(store)
            # never the cards of an episode you asked for (*Mine now*: mined past the cap, `held_by_cap`) — the shelf
            # taking them would undo your press (laptop round 7 #42, review r42 #2); the ledger keeps every ask
            pinned = shelf.pinned_items(store) | {j["item_id"] for j in ledger.jobs(lang)       # this run's asks
                                                  if j.get("asked_at") and (j["state"] not in ENDED
                                                                            or (j.get("updated_at") or "") >= self._began)}
            finished = shelf.finished_items(store, made)
            holder = self._top_words(lang, store)
        anki = self._anki()
        kept = shelf.kept(ledger)               # taken off the shelf by you: never shelved again (✅ P2.5-2)
        waiting = [c for c in shelf.cards(anki, shelf.WAITING_QUERY, made) if c.card_id not in kept]
        for card in waiting:
            card.rank = ranks.get(card.word, shelf.NOT_LISTED)
        needed = [ranks.get(w["word"], shelf.NOT_LISTED) for w in todo]
        chosen = shelf.plan(waiting, needed, cap, count, pinned, holder, finished)
        if not chosen:
            return 0
        if len(chosen) < count + len(needed) - cap:
            # the count holds your own new cards too (B3-2 A), the shelf takes only Connect's: shelving that can't
            # bring the batch under the cap suspends cards for nothing (review r2 #3) — nothing is shelved
            self._say(lang, f"the shelf can't make room: {count} cards wait, {len(chosen)} of Connect's could go.")
            return 0
        run = shelf.shelve(anki, ledger, lang, chosen, "the cap: less relevant than the top 20's next words")
        self._say(lang, f"{len(chosen)} of Connect's waiting cards went to the shelf (suspended in Anki, tagged "
                        f"{shelf.SHELF_TAG}; restore point {run}).")
        return len(chosen)

    def _say(self, lang, line):
        log.info("Connect's shelf (%s): %s", lang, line)
        self.said = getattr(self, "said", {})
        self.said.setdefault(lang, []).append(line)

    def shelf_session(self, lang, ledger):
        """Once a run: a shelved card you un-suspended loses its tag; a shelved word the top 20 needs comes back."""
        from app.connect import shelf
        anki = self._anki()
        shelf.tidy(anki, ledger)
        with self._open(lang) as store:
            made = shelf.made_notes(store)
            finished = shelf.finished_items(store, made)
            holder = self._top_words(lang, store)
        shelved = shelf.cards(anki, f"{shelf.SHELVED_QUERY} is:suspended", made)
        back = [c for c in shelved if c.word in holder]
        if back:
            done = shelf.bring_back(anki, ledger, lang, back, finished, holder.get)
            self._say(lang, f"{done['back']} shelved cards came back: the top 20 needs their words again.")

    def _top_words(self, lang, store):
        """{word: the top-20 item that holds it} — the swap-in brings these back and the shelf never takes them
        (adversary B #5): the list's words per file (`file_words.json`), by each line item's file name."""
        from app.cli import connect_verbs
        from app.connect import library
        line = library.mine_line(store)
        names = {i: os.path.basename((store.item(i) or {}).get("rel_path") or "") for i in line}
        read = connect_verbs._read_list(lang)
        file_words = (read[2] if read else {}) or {}
        holder = {}
        for item in line:
            for word in file_words.get(names.get(item), ()) or ():
                holder.setdefault(word, item)
        return holder

    def finish_undos(self, lang, ledger):
        """An *Undo this batch* a kill left half-way (recorded before Anki was written) finished now (P2.5, intent
        keeper #4): its gone notes' words freed, the job `undone`."""
        if not ledger.pending_undos(lang):
            return 0
        from app.connect import library, undo
        return undo.finish_pending(undo.AnkiConnectUndo(self.url), ledger, lang, lambda: library.open_store(lang))

    def notes_gone(self, lang):
        """Row 2.4.14: the store's note ids (yours and Connect's) checked against Anki once a run; the gone ones
        told to the store (`Store.notes_gone`, L3.3). Nothing when Anki doesn't answer, when it is open on another
        profile now (known-sync and Generate ran since the run's first look), or when every one of 10 or more notes
        reads as gone (another collection answering, never a learner's day: logged, looked at again next run;
        adversary L3.3 wiring #4). Once a run per language (`prepare`'s, or `run`'s for a language with nothing to
        mine): a look Anki didn't answer is asked again."""
        if lang in self._gone_looked:
            return []
        from app.connect import anki_session, library, shelf
        with self._open(lang) as store:
            ids = library.note_ids(store)
        gone = shelf.gone_notes(self._anki(), ids)
        if gone and anki_session.waiting(self.url, self.loaded) is not None:
            return []                       # another profile now: nothing marked, asked again (never `looked`)
        if gone and len(gone) == len(ids) >= ALL_GONE_MIN:
            log.warning("Connect's deleted-card check: Anki has none of the %d notes the library holds; nothing "
                        "marked gone", len(ids))
            gone = []
        elif gone:
            with self._open(lang) as store:
                library.notes_gone(store, gone)
        self._gone_looked.add(lang)         # only once the look is done: one that raised is asked again
        return gone

    def name_media(self, lang, job, picked, lines):
        """P2.4-4: the batch's clip and picture renamed by the line (`media_names.rename`). The field mapping is this
        run's, else the job's own settings export (a run after a kill: review B #4); Anki busy or gone -> a Wait
        (review B #2); some of its actions failed -> that episode's own wait (R2-1)."""
        from app import anki_connect, locks
        from app.connect import media_names
        if picked.get("reading"):
            return None                     # Z-9: a book's cards have no clip; their picture is the book's cover
        from app.connect.anki_miner import is_audio
        # Z-16: an audio episode's picture is the audio's cover, one file for every card — never renamed per line (a
        # copy per card: review AB-4); its clip is
        audio = is_audio(picked.get("video"))
        fields = getattr(self._job_mapping(job), "fields", None) or self._export_fields(lang, job)
        if not lines or not fields:
            return None
        pairing = self.pairing(lang, job) or {}
        key = pairing.get("content_key")
        if not key:
            with self._open(lang) as store:
                key = (store.item(job["item_id"]) or {}).get("rel_key") or f"item-{job['item_id']}"
        try:
            return media_names.rename(media_names.AnkiConnectMedia(self.url), lines, key, fields.get("audio"),
                                      None if audio else fields.get("picture"))    # the clip renamed (review AB-4)
        except media_names.Reviewing:
            raise Wait(REVIEWING, resume="mining") from None
        except locks.Busy:
            raise Wait(WRITER_BUSY, resume="mining") from None
        except media_names.Partial:         # the rest is done: that episode's own wait, finished at the next look (R2-1)
            raise Wait(ANKI_SLOW, resume="mining") from None
        except anki_connect.AnkiError as e:
            raise _anki_wait(self.url, "mining", e) from None

    def _job_mapping(self, job):
        """The field mapping this run's `mine` set — only for the job it mined; another job (resumed with nothing left
        to mine) reads its own settings export (adversary B #16)."""
        if getattr(self, "_mapping_job", None) != job.get("id"):
            return None
        return getattr(self, "_mapping", None)

    def _export_fields(self, lang, job):
        """{role: field} from the settings export Anki Miner wrote in the job's run folder, or {}."""
        from app.connect import fields
        try:
            with open(os.path.join(self.run_dir(job), "settings-export.json"), encoding="utf-8") as f:
                return dict(fields.from_export(json.load(f), lang).fields)
        except Exception:
            return {}

    def _anki_miner_held(self, lang):
        """This run's set of Anki Miner look-ups for `lang` (version answer, profile id, field mapping, export: filled
        by `verbs._anki_miner_setup`), handed to the pick and the mine step so an episode starts Anki Miner for `check`
        and `mine` alone (row 25). Emptied by any failure of Anki Miner or of the look-ups, and read again once 15
        minutes old (`verbs.SETUP_FOR_S`)."""
        return self._anki_miner_sets.setdefault(lang, {})

    def run_dir(self, job):
        from app.cli.verbs import _connect_folder
        return os.path.join(_connect_folder(), "runs", _tag(job))

    def part_book(self, lang, job, epub):
        """Michi-BK: the copy of `epub` holding the job's part (`reading.part_book`, Hon's record from the pairing),
        written at the book's one place in Connect's folder (`books/<the EPUB's path, hashed>/<its name>`: one cover in
        Anki for the whole book, one copy on disk a book) -> its path, or None: the whole EPUB, as before — logged, and
        never a reason not to mine. A busy store is a Wait."""
        import hashlib
        from app.cli.verbs import _connect_folder
        from app.connect import reading
        record = reading.chapter(self.pairing(lang, job))
        if record is None:
            return None
        key = hashlib.sha1(os.path.normcase(os.path.abspath(epub)).encode("utf-8")).hexdigest()[:12]
        try:
            named, why = reading.part_book(epub, record, os.path.join(_connect_folder(), "books", key))
        except Exception as e:
            named, why = None, f"{type(e).__name__}: {e}"
        if named is None:
            log.info("Connect: job %s reads the whole book %s (%s)", job["id"], os.path.basename(epub), why)
        return named

    def pick(self, lang, job, video, reading=None, subtitle=None):
        """`subtitle` (Michi-YT): the file the words are picked from instead of the library's (an online title's own
        captions, fetched with its video: the transcript keeps whole seconds only)."""
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import library
        given = subtitle
        with _held():                       # the store's reads, one open; never around `verbs.pick` (Anki Miner)
            subtitle = given or self.subtitle(lang, job)
            with self._open(lang) as store:      # every word Connect ever made, or no pick at all
                made = library.made_words_for(store, job)   # P4.1: an asked job makes a deleted card again (N15)
            # P3.3: the re-plan's ranks (a move served), else the list's (None) — its look at the store's versions in
            # the same open; a re-plan when something moved is the engine's (sub-second, no tokenizer, no Anki)
            got = self._plan_now(lang)
        if subtitle is None or not os.path.isfile(subtitle):
            raise Needs("no-subtitle", "An episode's subtitle isn't in Surasura's library any more.")
        ns = SimpleNamespace(lang=lang, file=subtitle, video=video, reading=reading, words=None, job=str(job["id"]),
                             wait=WAIT_S, made=made, listed=got.listed if got is not None else None,
                             held=self._anki_miner_held(lang),
                             unsure=self.unsure(job, subtitle) if reading is None else [])   # Tsu-U
        try:
            out = verbs.pick(ns)
        except CliError as e:
            ns.held.clear()                 # row 25: read again after any failure
            holds = verbs._results_language() if e.code == "not-set-up" else None
            if WAIT_FOR_OTHER_LIST and holds and holds != lang:     # you Generated another language meanwhile
                raise Wait(OTHER_LIST.format(LANGUAGE_NAMES.get(holds, holds))) from None
            raise _wait_or_needs(e, None, self.url) from None
        miner = out.get("anki_miner") or {}
        return {"words": out.get("words") or [], "file": subtitle, "subtitle": out.get("subtitle"),
                "profile": miner.get("profile"), "anki_miner": miner.get("app"),
                "absent": out.get("skipped") == "anki miner absent"}

    def fit(self, lang, job, pairing, video, subtitle):
        """-> (verdict, who, why, offset): `subtitle` is the library's copy (hato's sha256 is checked on it);
        `connect_trust_timing` (off by default; read from settings.json as it is now, so a switch turned mid-run counts
        for the next episode) mines an episode nothing here can check at its own times. An audio file's subtitle is
        spot-checked by listening (AB-Q5, `_spot`) while Anki Miner can, before anything else is asked."""
        from app.connect import anki_miner
        trust = self._settings(lang).get("connect_trust_timing") is True
        spot = None
        if not trust and anki_miner.is_audio(video) and anki_miner.can_now(anki_miner.SPOT_CHECK):
            spot = lambda: self._spot(lang, job, video, subtitle)      # noqa: E731
        return fit_check.fit(pairing, video, subtitle, trust=trust, spot=spot)

    def retimed(self, lang, job, video, subtitle):
        """Michi-NT: the same subtitle re-timed beside the episode's video (`retimed_beside`), or None."""
        return retimed_beside(video, subtitle, lang)

    def retime(self, lang, job, video, copy):
        """Michi-NT2 (based on Mattias's #364): the library copy `copy` re-timed by tsubasa (`fit_check.retime`, written
        in the job's own run folder, removed after) put in its place by S5's own rule (`sources.put_copy`: the old copy
        into the data folder's `.trash` first, purged 30 days on; the new one written beside it, then `os.replace`)
        -> True; else False and the copy as it was; None: not now (no answer from tsubasa, or the copy changed
        while it was re-timed — the library's own re-copy wins, and its text is checked next). Only a copy inside the
        language's `Library` (`sources.inside_library`: a hato / 2.x file, a `Library` that leads elsewhere, never),
        only the same subtitle (`same_subtitle`: its very lines, less the cues tsubasa says it dropped). Written whole
        and flushed (`sources._copy_part`) under a name of its own (`RETIME_PART`: never the look's `.part`), and the
        copy checked unchanged right before its place is taken. Its original is left as it is: one that changes is
        copied over it again (S5), and checked again."""
        from app import sources
        from app.path_utils import get_data_path
        data_dir = get_data_path(lang)
        try:
            rel = os.path.relpath(copy, data_dir).replace("\\", "/")
        except ValueError:                  # another drive: never inside
            return False
        full = sources.inside_library(data_dir, rel)
        if full is None or not os.path.isfile(full):
            return False
        out_dir = os.path.join(self.run_dir(job), RETIMED_FOLDER)
        part = full + RETIME_PART
        was = _stamp(full)
        try:
            made = fit_check.retime(video, full, out_dir)
            if made == fit_check.RETRY:
                return None
            if made is None or not same_subtitle(full, made.path, lang, made.dropped):
                log.info("Connect: job %s: tsubasa gave no re-timed copy of the same subtitle; its copy kept", job["id"])
                return False
            sources._copy_part(made.path, part)
        except OSError:
            sources._drop(part)
            return False
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
        if _stamp(full) != was:             # the library copied its original in meanwhile (S5): that text first
            sources._drop(part)
            log.info("Connect: job %s: its copy changed while tsubasa re-timed it; checked again", job["id"])
            return None
        placed = sources.put_copy(data_dir, full, part)
        if placed:
            self._keep_unsure(job, full, made.undetermined)
        return placed

    def _keep_unsure(self, job, copy, spans):
        """Tsu-U (based on Mattias's Tsubasa-sync #2): the spans tsubasa left undetermined in the copy it just re-timed,
        kept in the job's run folder (`UNSURE_FILE`) for that copy as written — the next pick cuts no card from a line
        inside one (`unsure`). None: the file removed (a re-time with none leaves none from before). A write that fails
        is logged: the cards are then cut as they would be without it."""
        path = os.path.join(self.run_dir(job), UNSURE_FILE)
        try:
            if not spans:
                if os.path.exists(path):
                    os.remove(path)
                return
            os.makedirs(os.path.dirname(path), exist_ok=True)
            record = {"copy": os.path.normcase(os.path.abspath(copy)), "stamp": _stamp(copy),
                      "spans": [[lo, hi] for lo, hi in spans]}
            with open(path + ".part", "w", encoding="utf-8") as f:
                json.dump(record, f)
            os.replace(path + ".part", path)
            log.info("Connect: job %s: tsubasa can't place its cut within %s; no card from a line there", job["id"],
                     ", ".join(f"{lo:.1f}–{hi:.1f} s" for lo, hi in spans))
        except OSError:
            log.warning("Connect couldn't keep job %s's unsure spans", job.get("id"), exc_info=True)

    def unsure(self, job, subtitle):
        """Tsu-U: tsubasa's undetermined spans [(lo, hi)] for `subtitle`, kept at the job's re-time (`_keep_unsure`) —
        only for that very copy, unchanged since (a copy written again since is checked again: no old span); else []."""
        try:
            with open(os.path.join(self.run_dir(job), UNSURE_FILE), encoding="utf-8") as f:
                record = json.load(f)
            if (not isinstance(record, dict) or not subtitle
                    or record.get("copy") != os.path.normcase(os.path.abspath(subtitle))
                    or record.get("stamp") != _stamp(subtitle)):
                return []
            return fit_check.undetermined({"undetermined": record.get("spans")})
        except (OSError, ValueError, TypeError):
            return []

    def _miner_profile(self, lang, job):
        """(Anki Miner's path, the profile Connect mines with) for a line-up or a spot-check — the pick's look-ups
        (row 25), else read; None when Anki Miner isn't installed. Raises Wait / Needs as the mine step does."""
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import anki_miner
        miner = anki_miner.find(self.loaded)
        if miner is None:
            return None
        try:
            setup = verbs._anki_miner_setup(self.loaded, lang, self.run_dir(job), held=self._anki_miner_held(lang))
        except CliError as e:
            raise _wait_or_needs(e, None, self.url) from None
        return (miner, setup[1]) if setup is not None else None

    def speech(self, lang, miner, profile, downloading=LINING_UP_MODEL):
        """AB-Q1/Q2 (Sonic 2026-11-02, PROVISIONAL): may Anki Miner listen now? -> "ready" (a model it has — never a
        second download, never asked: `anki_miner.speech_ready`), "no" (you said *Not now*: no sentence audio, Anki
        Miner never asked again — review B-11), or the one question's words (unanswered; or its download failed or was
        stopped: asked again with why, the words kept until answered — B-4, B-6). Your yes: Anki Miner's own `setup
        --speech-model --model small` started (`lineup.start_speech`) and Wait while it downloads; its window open
        (BUSY) is a wait, started again, never a failure (B-5); a setup a Connect that quit left running is waited for
        (B-17)."""
        from app.connect import anki_miner, lineup
        said = lineup.answer()
        if said == "no":
            return "no"
        state = lineup.look(lineup.SPEECH)
        status = state.get("status")
        if status == lineup.RUNNING or (status == lineup.INTERRUPTED and not state.get("busy")
                                        and anki_miner.setting_up()):
            raise Wait(downloading)
        try:
            if anki_miner.speech_ready(miner, lang, profile, lineup.folder(lineup.SPEECH)):
                return "ready"
        except anki_miner.AnkiMinerError as e:
            raise _miner_wait_or_needs(e, self.url) from None
        if said == "yes" and status in (lineup.FAILED, lineup.DONE, lineup.STOPPED) and not state.get("said"):
            # its download ended, stopped or failed, and still nothing to listen with: the question again, with why —
            # never a second download nobody asked for
            why = "it was stopped" if status == lineup.STOPPED else \
                state.get("message") or "Anki Miner says it still isn't ready"
            ask = lineup.SPEECH_FAILED.format(why=why)
            lineup.write(lineup.SPEECH, dict(state, said=True, ask=ask))
            lineup.clear_answer()
            return ask
        if said != "yes":
            return state.get("ask") if state.get("said") and state.get("ask") else lineup.SPEECH_ASK
        busy = state.get("busy")
        try:
            lineup.start_speech(miner, lang, profile)
        except anki_miner.AnkiMinerError as e:
            raise _miner_wait_or_needs(e, self.url) from None
        raise Wait(ANKI_MINER_OPEN if busy else downloading)

    def line_up(self, lang, job, epub):
        """Michi-AB Stage B (`runner._line_up`): the book `epub` lined up with the audiobook Hon paired with it ->
        None (none paired, Anki Miner can't, you kept them apart in sound — *Keep them together* —, you said *Not now*
        to the speech model: mined as the book); {"lineup": its usable line-up or None, "line": AB-Q4's plain line,
        "item_id": the audiobook's}; {"ask": the speech model's question}. Raises Wait while it lines up (`file k of
        n`; its `pair`), while another book's does (one at a time: review B-2), while a stopped one hasn't ended (B-1),
        downloads the model, or waits for the plug, and after your *Stop* until your next *Mine now* (`restarted`
        then). Nothing lined up at all: the store's mark (once), so *Needs you* asks the one question, and the book is
        mined as it is. Given up (TRIES failures) until a *Mine now* newer than the last failure (B-18). Kura-AB3: an
        audiobook whose own timed subtitle is the book's is lined up by it, never synced (`_own_timing`)."""
        from app.connect import anki_miner, library, lineup
        sync = anki_miner.can_now(anki_miner.LINE_UP)
        if not sync and not anki_miner.mines_now("audio"):
            return None
        with self._open(lang) as store:
            ab = library.audiobook_of_book(store, epub)
            if ab is None:
                return self._book_audio(store, epub) if sync else None
        if ab["lineup"] == "kept":
            return None                     # *Keep them together*: no sentence audio, as you said (review B1)
        own = self._own_timing(lang, job, ab)
        if own is not None:
            return own
        if not sync or not ab["key"]:
            return None
        key = ab["key"]
        state = lineup.look(key)
        status = state.get("status")
        asked = job.get("asked_at")
        if status == lineup.DONE:
            # its files as the store holds them now (review B-3: the pair's key is the files' sizes in order, so a moved
            # audiobook is the same files at their new place); a file away is never sent (`lineup.cues`)
            files = [dict(f, audio_file=ab["files"][k] if k < len(ab["files"]) else f.get("audio_file"))
                     for k, f in enumerate(state.get("files") or ())]
            line = lineup.partial_line(state, ab["title"])
            lined = {"status": lineup.DONE, "key": key, "grade": state.get("grade"), "files": files} \
                if lineup.usable(state) else None
            return {"lineup": lined, "line": line, "item_id": ab["item_id"]}
        if status == lineup.NONE:
            if ab["lineup"] != "none":
                self._mark_line_up(lang, ab, "none")
            return None
        if status == lineup.RUNNING:
            raise _lining(LINING_UP_FILE.format(k=lineup.file_line(state)[0], n=lineup.file_line(state)[1]), key)
        if lineup.running(key):             # stopped, its child not ended yet: never a second run on its folder
            raise _lining(LINING_UP_STOPPING, key)
        if status == lineup.STOPPED and not state.get("own_stop") and not _newer(asked, state.get("stopped_at")):
            raise Wait(LINING_UP_STOPPED, look=False)
        if status in (lineup.FAILED, lineup.NO_MODEL) and (state.get("tries") or 0) >= lineup.TRIES and \
                not _newer(asked, state.get("failed_at")):
            why = state.get("message") or state.get("code") or "no answer"
            return {"lineup": None, "item_id": ab["item_id"],
                    "line": LINE_UP_FAILED.format(title=ab["title"], why=why)}
        if lineup.other_running(key):
            raise _lining(LINING_UP_AFTER, key)
        if self.on_battery() and not asked:
            raise Wait(LINING_UP_BATTERY)       # hours of listening: never on battery unless you asked for it
        found = self._miner_profile(lang, job)
        if found is None:
            return None
        miner, profile = found
        said = self.speech(lang, miner, profile)
        if said == "no":
            return None
        if said != "ready":
            return {"ask": said}
        missing = [f for f in ab["files"] if not _on_disk(f)]
        if missing or not _on_disk(epub):
            return None                         # an audio file or the book away: mined as the book this time
        try:
            lineup.start_sync(miner, lang, profile, key, epub, ab["files"])
        except anki_miner.AnkiMinerError as e:
            raise _miner_wait_or_needs(e, self.url) from None
        log.info("Connect: lining up %s with its audiobook (%d files)", ab["title"], len(ab["files"]))
        wait = _lining(LINING_UP_FILE.format(k=1, n=len(ab["files"])), key)
        wait.restarted = status == lineup.STOPPED
        raise wait

    def _own_timing(self, lang, job, ab, look_only=False):
        """Kura-AB3 (Mattias's 3.0.2 report; PROVISIONAL): the paired audiobook `ab` (`library.audiobook_of_book`) whose
        own timed subtitle Hon found this book's (`timing`: its copy in the library) — one audio file, an `.srt`, both
        on this computer, its last cue inside the audio's length — is the book's line-up as it is (`lineup.own`: no
        sync) -> {"lineup", "line": None, "item_id"}; else None (lined up as before). Its timing to that audio is
        checked or trusted, the one rule an audiobook's own subtitle has alone (`fit_check.fit`, review S1): heard in
        time by the spot-check (`_own_spot`), or *Trust my subtitles' timing* on (`connect_trust_timing`: no speech
        model at all). Never a wrong clip (review B2): not heard in time, not checked now, or — once Anki Miner's own
        line-up said this audio doesn't follow the book (nothing lined up, a grade of C or D) — anything but heard in
        time, is None. A sync still running for the pair is stopped once its subtitle is used (S2). `look_only`
        (*Add audio to these cards*' plan, `lined_up`): never a listen, never a stop, nothing written."""
        from app.connect import lineup
        from app.path_utils import get_data_path
        rel = ab.get("timing")
        if not rel or len(ab["files"]) != 1 or not rel.lower().endswith(".srt"):
            return None
        audio, srt = ab["files"][0], os.path.join(get_data_path(lang), *rel.split("/"))
        if not _on_disk(audio) or not os.path.isfile(srt):
            return None
        found = lineup.srt_cues(srt)
        seconds = ab.get("seconds")
        if not found or (isinstance(seconds, (int, float)) and seconds > 0 and
                         max(end for _s, end, _t in found) > seconds + OWN_SLACK_S):
            return None                     # timed to a longer cut than this audio (S1)
        synced = (lineup.read if look_only else lineup.look)(ab["key"]) if ab["key"] else {}
        doubt = synced.get("status") == lineup.NONE or (
            synced.get("status") == lineup.DONE and synced.get("grade") not in lineup.GOOD)
        # never a listen while Anki Miner's own line-up is done and good (it cuts the cards: review r2 S2) or still
        # running (each look would listen again beside it: r2 S3) — only a kept or trusted answer counts then
        listen = not look_only and not lineup.usable(synced) and not (ab["key"] and lineup.running(ab["key"]))
        said = self._own_spot(lang, job, audio, srt, listen=listen)
        if said not in (lineup.MATCHED, OWN_TRUSTED) or (doubt and said != lineup.MATCHED):
            log.info("Connect: %s's own subtitle isn't used for its timing (%s)", ab["title"], said or "unchecked")
            return None
        if not look_only and ab["key"] and lineup.running(ab["key"]):
            lineup.stop(ab["key"])
            lineup.write(ab["key"], dict(lineup.read(ab["key"]), own_stop=True))   # Connect's, never yours (r2 N5)
        return {"lineup": lineup.own(ab["key"], audio, srt), "line": None, "item_id": ab["item_id"]}

    def lineable(self, lang, epub):
        """Kura-AB3 A2 r4/r5: would a part's job line the book `epub` up with its audiobook (`line_up`'s own exits,
        mirrored — review A2 r5 S1)? Paired; Anki Miner mines books (Z-9: else the job is set aside before its pick)
        and lines them up (Z-17); not *Keep them together*, nothing found, a poor line-up kept, given up (TRIES), *Not
        now* to the speech model; its audio and the book on this computer. Read only."""
        from app.connect import anki_miner, library, lineup
        if not self.mines(lang, "books") or not anki_miner.can_now(anki_miner.LINE_UP):
            return False
        with self._open(lang) as store:
            ab = library.audiobook_of_book(store, epub)
        if ab is None or ab["lineup"] in ("kept", "none") or not ab["key"]:
            return False
        state = lineup.read(ab["key"])
        status = state.get("status")
        if status == lineup.NONE or (status == lineup.DONE and not lineup.usable(state)) or (
                status in (lineup.FAILED, lineup.NO_MODEL) and (state.get("tries") or 0) >= lineup.TRIES):
            return False
        if lineup.answer() == "no" and not (ab.get("timing") and self._settings(lang).get("connect_trust_timing")):
            return False                        # (no listen, no sync: only a trusted own subtitle would line it up)
        return all(_on_disk(f) for f in ab["files"]) and _on_disk(epub)

    def first_part(self, lang, epub):
        """Kura-AB3 A2 r4: the book's first part in the library (its *Mine now* lines the book up), or None."""
        from app.connect import library
        with self._open(lang) as store:
            return (library.book_of(store, epub) or {}).get("item")

    def paired_books(self, lang):
        """Kura-AB3 A2: [(EPUB, its audiobook's item)] the store pairs (`library.paired_books`), read only."""
        from app.connect import library
        with self._open(lang) as store:
            return library.paired_books(store)

    def made_before(self, lang, epub):
        """Kura-AB3 A2: (the book's title, the notes Connect made from its parts so far — [ids] —, its EPUB's sha256
        or None) — the store read only."""
        from app.connect import add_audio, library
        with self._open(lang) as store:
            notes = add_audio.made_notes(store, add_audio.book_items(store, epub))
            book = library.book_of(store, epub)
        return ((book or {}).get("title") or os.path.splitext(os.path.basename(epub))[0], sorted(notes),
                (book or {}).get("sha256"))

    def lined_up(self, lang, epub):
        """*Add audio to these cards* (Kura-AB3): the book `epub`'s line-up as it stands, read only -> {"lineup" (its
        cues, as the pick hands them to the mine), "item_id" (the audiobook's), "title"}, or None (no audiobook paired,
        *Keep them together*, nothing usable yet). Its own subtitle checked or trusted (`_own_timing`, look only), else
        a finished sync of grade A/B (its files where the store holds them now) — never a sync started, a listen, a
        stop or a write. A busy store is a Wait."""
        from app.connect import library, lineup
        with self._open(lang) as store:
            ab = library.audiobook_of_book(store, epub)
        if ab is None or ab["lineup"] == "kept":
            return None
        own = self._own_timing(lang, {"id": "add-audio", "asked_at": None}, ab, look_only=True)
        if own is not None:
            return dict(own, title=ab["title"])
        state = lineup.read(ab["key"]) if ab["key"] else {}
        if not lineup.usable(state):
            return None
        files = [dict(f, audio_file=ab["files"][k] if k < len(ab["files"]) else f.get("audio_file"))
                 for k, f in enumerate(state.get("files") or ())]
        return {"lineup": {"status": lineup.DONE, "key": ab["key"], "grade": state.get("grade"), "files": files},
                "item_id": ab["item_id"], "title": ab["title"]}

    def _own_spot(self, lang, job, audio, srt, listen=True):
        """AB-Q5's spot-check of an audiobook's own subtitle for `_own_timing` -> lineup.MATCHED / NOT_MATCHED (kept per
        subtitle and audio, `lineup.spot_kept`); OWN_TRUSTED (*Trust my subtitles' timing* on: never listened to, as
        `Steps.fit` asks it first); None (not checked: no speech model — the sync's path after asks the one question
        —, *Not now* said to it, Anki Miner absent, or a check that gave no verdict now: a call that failed or timed
        out — looked at again next time). Raises Wait on battery before an unasked listen (as the sync waits). A kept *not in time* wins over your trust (review r2 S1:
        never a clip heard out of time); `listen` False: only a kept or trusted answer, never a call."""
        from app.connect import anki_miner, lineup
        kept = lineup.spot_kept(lineup.spot_key(audio, srt))
        if kept == lineup.NOT_MATCHED:
            return kept
        if self._settings(lang).get("connect_trust_timing") is True:
            return OWN_TRUSTED
        if kept is not None or not listen or lineup.answer() == "no" or not anki_miner.can_now(anki_miner.SPOT_CHECK):
            return kept
        found = self._miner_profile(lang, job)
        if found is None:
            return None
        miner, profile = found
        try:
            if not anki_miner.speech_ready(miner, lang, profile, lineup.folder(lineup.SPEECH)):
                return None
            if self.on_battery() and not job.get("asked_at"):
                raise Wait(LINING_UP_BATTERY)
            said = lineup.spot_check(miner, lang, profile, audio, srt)
        except anki_miner.AnkiMinerError as e:
            if e.kind == "setup":
                anki_miner._SPEECH.clear()
            log.info("Connect: the spot-check of %s couldn't run now (%s)", os.path.basename(srt), e.message)
            return None
        return said

    def _book_audio(self, store, epub):
        """Kura-AB2: the book `epub`, no audiobook paired -> None (mined as the book: *Not now* to the speech model,
        or it isn't in the library); else the one question for `runner._book_question`, which reads its answer in the
        ledger: {"book_ask": BOOK_AUDIO_ASK, "item_id": its first part, "key": `book_key`, "epub"}. Hon's own question
        about an audiobook for it (H-8) may stand beside it: *Pick its audiobook…* lists that audiobook first, and
        either answer that pairs them lets the book go."""
        from app.connect import library, lineup
        if lineup.answer() == "no":
            return None
        book = library.book_of(store, epub)
        if book is None:
            return None
        return {"book_ask": BOOK_AUDIO_ASK.format(title=book["title"]), "item_id": book["item"],
                "key": book_key(epub, book["sha256"]), "epub": os.path.abspath(epub)}

    def _mark_line_up(self, lang, ab, status):
        """The store's mark on the audiobook's records (`Store.mark_audiobook_lineup`): nothing lined up — *Needs you*
        asks the one question. A busy store: marked at the next look."""
        try:
            with self._open(lang) as store:
                store.mark_audiobook_lineup(ab["item_id"], ab["key"], status, by="connect")
        except (Wait, Needs):
            pass

    def stop_line_up(self, lang, job):
        """*Stop* on a book waiting while its audiobook is lined up (AB-Q3): its sync's cancel file (`lineup.stop`).
        The book's EPUB from its part's origin (`reading.source`); nothing else read."""
        from app.connect import library, lineup, reading
        ab = None
        with _held():
            with self._open(lang) as store:
                pairing = library.pairing_of(store, job["item_id"])
            path = self.subtitle(lang, job)
            epub = reading.source(path, pairing)[1] if path else None
            if epub:
                with self._open(lang) as store:
                    ab = library.audiobook_of_book(store, epub)
        if ab is not None and ab["key"]:
            lineup.stop(ab["key"])

    def _spot(self, lang, job, video, subtitle):
        """AB-Q5's spot-check for `fit_check.fit` -> lineup.MATCHED / NOT_MATCHED; None when it can't be checked now
        (Anki Miner absent, a call that failed: the rules after it decide, as before); (NOT_TIMED, SPEECH_NEED, the
        question, 0.0) when Anki Miner has no speech model and you haven't said *Not now* (the question; your yes
        downloads it, and the check runs then). Raises Wait while the model downloads."""
        from app.connect import anki_miner, lineup
        found = self._miner_profile(lang, job)
        if found is None:
            return None
        miner, profile = found
        kept = lineup.spot_kept(lineup.spot_key(video, subtitle))
        if kept in (lineup.MATCHED, lineup.NOT_MATCHED):
            return kept
        said = self.speech(lang, miner, profile, downloading=CHECKING_MODEL)
        if said == "no":
            return None
        if said != "ready":
            return fit_check.NOT_TIMED, SPEECH_NEED, said, 0.0
        try:
            return lineup.spot_check(miner, lang, profile, video, subtitle)
        except anki_miner.AnkiMinerError as e:
            if e.kind == "setup":
                anki_miner._SPEECH.clear()
            log.info("Connect: the spot-check of %s couldn't run now (%s)", os.path.basename(subtitle), e.message)
            return None

    def mine(self, lang, job, picked, words, attempt):
        """One Anki Miner batch -> {"outcomes", "app", "doubt"} (doubt: the run crashed or timed out — the words it
        doesn't account for are found by tag). Stage B: a book lined up with its audiobook (`picked["lineup"]`) goes
        as one call a part — each audio file's words as its audio episode, cut at their sentence's cue, the rest as
        the book (`lineup.split`); outcomes in the words' order. A call that fails after another made cards returns
        those, the rest not attempted: the next batch sends only them (and meets the failure again, as itself)."""
        lined = picked.get("lineup") if picked.get("reading") else None
        if not lined:
            return self._mine_one(lang, job, picked, words, attempt)
        from app.connect import lineup
        groups, rest = lineup.split(words, lined)
        runs = [dict(picked, video=audio, subtitle=srt, reading=None, offset=0.0, _words=ws)
                for (audio, srt), ws in groups.items()]
        if rest:
            runs.append(dict(picked, _words=rest))
        got, out = {}, None
        for n, run in enumerate(runs):
            ws = run.pop("_words")
            try:
                done = self._mine_one(lang, job, run, ws, attempt if n == 0 else f"{attempt}-{n}")
            except (Wait, Needs, Skip, Repick, stopping.Stopped):
                if not got:
                    raise
                break                       # the cards made so far kept; the rest sent by the next batch
            for w, o in zip(ws, done["outcomes"]):
                got[(w["word"], w["reading"])] = o
            if out is None:
                out = dict(done, outcomes=None)
            else:
                out["doubt"] = out.get("doubt") or done.get("doubt")
                out["stopped"] = out.get("stopped") or done.get("stopped")
                out["tag_pending"] = list(out.get("tag_pending") or ()) + list(done.get("tag_pending") or ())
            if done.get("stopped"):
                break                       # your *Stop*: the next files' words wait with the job
        out["outcomes"] = [got.get((w["word"], w["reading"])) or dict(_unsure(w), outcome="not_attempted")
                           for w in words]
        return out

    def _mine_one(self, lang, job, picked, words, attempt):
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import anki_miner, runfile
        miner = anki_miner.find(self.loaded)
        if miner is None:
            raise Skip("Anki Miner isn't installed")
        run_dir = self.run_dir(job)
        held = self._anki_miner_held(lang)      # row 25: the pick's look-ups, kept (the setup empties it on a failure)
        try:
            setup = verbs._anki_miner_setup(self.loaded, lang, run_dir, held=held)
        except CliError as e:
            raise _wait_or_needs(e, "mining", self.url) from None
        if setup is None:
            raise Skip("Anki Miner isn't installed")
        mapping = self._mapping = setup[2]
        self._mapping_job = job.get("id")
        try:
            done = anki_miner.mine_batch(miner, lang, _tag(job), picked["video"], picked["subtitle"], words,
                                         mapping, self.loaded.get("connect_anki_miner_profile") or "Surasura",
                                         run_dir, self.url, attempt=attempt, wait=WAIT_S,
                                         subtitle_offset=float(picked.get("offset") or 0.0),
                                         expect_profile=picked.get("profile"),
                                         on_progress=getattr(self, "on_progress", None), known=setup[:2],
                                         should_stop=getattr(self, "should_stop", None),
                                         show=self.show(lang, job), reading=picked.get("reading"),
                                         from_audio=bool(picked.get("from_audio")), names=picked.get("names"),
                                         word_audio=runfile.word_audio_on(self._settings(lang), lang))
        except anki_miner.AnkiMinerError as e:
            held.clear()                        # any Anki Miner failure (a profile changed too): read again next time
            if e.kind == "profile-changed":
                raise Repick() from None
            if e.kind == "no-reading":          # Z-9: another Anki Miner since the pick: the book waits as before,
                from app.connect import setup   # the record told what is installed (or it is queued again at once)
                setup.note_anki_miner(e.verdict)
                raise Skip(BOOKS_WAIT) from None
            if e.kind == "no-audio":            # Z-16: the same for audio — it waits as audio does
                from app.connect import setup
                setup.note_anki_miner(e.verdict)
                raise Skip(AUDIO_WAIT) from None
            if e.kind == "unreadable" and picked.get("reading"):
                title = self.title(lang, job) or os.path.basename(picked["reading"])
                raise Needs("book-unreadable", BOOK_UNREADABLE.format(title=title, why=e.message)) from None
            if e.kind == "cancelled" and getattr(e, "stopped", False):
                # #47: you stopped it before its result was written: what reached Anki is found by the job's tag
                return {"outcomes": [dict(_unsure(w)) for w in words], "app": None, "doubt": True, "stopped": True}
            if e.kind in ("crashed", "timeout"):
                return {"outcomes": [dict(_unsure(w)) for w in words], "app": None, "doubt": True}
            raise _miner_wait_or_needs(e, self.url) from None
        # in doubt: a crash or a timeout after the run (`error`), or a run Anki Miner itself says failed
        if picked.get("reading"):
            self._place(lang, job, picked, done.get("outcomes") or [])
        run = done.get("run") or {}
        doubt = bool(done.get("error")) or (bool(run) and not run.get("ok"))
        # Mattias #5: Anki refused a card (Anki Miner's MINING_FAILED, not transient — AnkiConnect's *cannot create
        # note …*): its words, in doubt, go a word at a time next (`runner._mine_batch`); a crash is no such answer
        said = (run.get("message") or run.get("error") if run.get("error") == "MINING_FAILED" and not
                run.get("failure_is_transient") and not done.get("error") else None)
        return {"outcomes": done.get("outcomes") or [], "app": done.get("app"), "doubt": doubt,
                "tag_pending": done.get("tag_pending") or [], "stopped": bool(done.get("stopped")), "anki_said": said}

    def _place(self, lang, job, picked, outcomes):
        """Z-9: each card Anki Miner made from a book put on its part (`connect.reading.place`, Hon's chapter record):
        `part` its item id; one whose sentence lies in another part than the job's (the same sentence twice in the
        book) is `other_line`, as a video's card cut from another line is, and logged. A text (no EPUB), a book whose
        parts carry no record, a store busy now: not placed (the card is the job's part's, as it was picked)."""
        from app.connect import library, reading
        book = picked.get("book")
        if not book or not any(o.get("location") for o in outcomes):
            return
        try:
            with self._open(lang) as store:
                parts = library.book_parts(store, book)
        except (Wait, Needs):
            return
        documents = reading.documents_of(book)
        lines = {(w["word"], w["reading"]): w.get("line_text") for w in picked.get("words") or ()}
        for o in outcomes:
            if not o.get("location"):
                continue
            o["part"] = reading.place(o["location"], lines.get((o["word"], o["reading"])), parts, documents)
            o["other_line"] = o["part"] is not None and o["part"] != job["item_id"]
            if o["other_line"]:
                log.info("Connect: job %s's card for %s took its sentence from another part of the book (%s, %s)",
                         job["id"], o["word"], o["location"], o["part"])

    def by_tag(self, lang, job, picked, words):
        """Which of `words` reached Anki, found by the job's tag (read-only) -> outcomes (made / uncertain)."""
        from app import anki_connect
        from app.connect import anki_miner, fields
        field = getattr(self._job_mapping(job), "word", None)
        if field is None:
            try:
                with open(os.path.join(self.run_dir(job), "settings-export.json"), encoding="utf-8") as f:
                    field = fields.from_export(json.load(f), lang).word
            except Exception:
                field = None
        if field is None:
            return [_unsure(w) for w in words]
        for w in words:
            w.setdefault("sent", [w["word"]])
        try:
            return anki_miner.uncertain_by_tag(self.url, _tag(job), words, field)
        except anki_connect.AnkiError as e:
            raise _anki_wait(self.url, "mining", e) from None

    def fill(self, lang, job, note_ids):
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import runfile
        # the job's tag beside its notes: the source field (K40) is read from its run folder (adversary P2.4-A #8)
        ns = SimpleNamespace(lang=lang, wait=WAIT_S, notes=",".join(str(n) for n in note_ids),
                             tag=runfile.job_tag(_tag(job)), dry_run=False)
        try:
            out = verbs.backfill(ns)
        except CliError as e:
            raise _wait_or_needs(e, "filling", self.url) from None
        if isinstance(out.get("skipped"), str):         # absent, the preview off, Anki switched off: named
            raise Skip(out["skipped"])

    def order(self, lang, job):
        """Junban's automatic re-order (`junban --auto`'s body) — P3.3: from the engine's rows when the plan serves
        the library as it stands (`record_planned` after a clean run), with your 順 actions as every automatic
        re-order applies them on 3.0 (HY-6, C2: `positions_only` False). A plan that waits for the Generate after
        mining with no re-plan to order from (the level raised) -> DEFERRED: that Generate's follow-up orders. `job`:
        None for the follow-up.

        A newer order planned or made while this one was written (the window's host wrote one while Connect waited
        for `anki-writer`, or you moved), or a Generate that landed meanwhile without a move (known words, the band:
        `_junban_auto` tells it, review M1 and the final adversary's #2) -> re-planned and, when the re-plan's
        verdict is "no", ordered once more — once, never a loop (`Host._replan`'s own rule); any other verdict, or a
        newer one again after that second write -> DEFERRED (the re-sort stays owed: the next look re-orders, #1).
        Here, not in `_junban_auto`: the step holds the run's plan (`current`, read fresh).

        A plan read since the run's own that the engine can't serve (the settings, or a file, moved mid-run: `current`
        reads it again) -> DEFERRED: never the old plan's rows written and recorded planned (#4, H10)."""
        from app.cli import verbs
        from app.cli.contract import CliError
        got = self._plan_now(lang)
        if lang in self._after and (got is None or got.result is None):
            return DEFERRED
        if lang in self._served and got is not None and got.result is None:
            return DEFERRED
        for again in (False, True):
            ns = SimpleNamespace(lang=lang, wait=WAIT_S, auto=True, dry_run=False, current=got, positions_only=False)
            try:
                out = verbs.junban(ns)
            except CliError as e:
                raise _wait_or_needs(e, "ordering", self.url) from None
            if out.get("skipped") == "junban absent":
                raise Skip("Junban isn't installed")
            if out.get("skipped"):          # 順 off, an update waiting, the list out of date: named, the re-sort owed
                raise Skip(str(out["skipped"]))
            if out.get("stood_aside"):
                # P4.1 C8 (FT-1): you put this deck back while the step waited for `anki-writer` — nothing written, a
                # plain line in the run's summary, no job error and no re-sort owed (the deck isn't Surasura's to
                # re-order until you pick it in 順 again)
                log.info("Connect: the re-order stood aside (%s): %s", lang, out["stood_aside"])
                self.stood_aside = dict(getattr(self, "stood_aside", None) or {}, **{lang: str(out["stood_aside"])})
                return None
            if not getattr(ns, "newer", False):
                return None
            if again:                       # newer again during the second write: owed, never a third (#1)
                log.info("Connect: a newer order again while it wrote Anki's (%s): the re-sort stays owed", lang)
                return DEFERRED
            log.info("Connect: a newer order was planned while it wrote Anki's (%s): ordering once more", lang)
            got = self.current(lang, fresh=True)
            if got.generate != "no":        # the re-plan's verdict decides (#2): only one the engine serves as is
                return DEFERRED


def _tag(job):
    """The job's name in its tag and run folder (the ledger's `tag`: unique past a lost ledger)."""
    return job.get("tag") or str(job["id"])


def _unsure(word):
    return {"word": word["word"], "reading": word["reading"], "outcome": "uncertain", "note_id": None,
            "line_start": word.get("line_start")}


def anki_wait(reason):
    """Is `reason` a wait on Anki — closed, busy, not answering as it should, another profile or none named yet, you
    reviewing, another program writing to it? (The window's feed shows these as *Waiting for Anki*.)"""
    from app.connect import anki_session
    return isinstance(reason, str) and (
        reason in (ANKI_CLOSED, ANKI_SLOW, REVIEWING, WRITER_BUSY, anki_session.CLOSED, anki_session.BUSY,
                   anki_session.UNUSABLE, anki_session.REVIEWING, anki_session.NO_PROFILE_YET,
                   anki_session.NO_PROFILE_DECKS)
        or reason.startswith(anki_session.OTHER_PROFILE.split("{")[0]))


def anki_needs_you(reason):
    """Is `reason` a wait on Anki that only you can end — Anki closed, a permission prompt (it doesn't answer as
    AnkiConnect should), another profile open, or none named yet / none holding your decks? (Alpha 2's try, T1: the
    window's one rule for amber, *needs you*.) A wait that clears by itself — you reviewing, Anki busy, another program
    writing to it, one slow answer — is not: the window shows it as a plain wait."""
    from app.connect import anki_session
    return isinstance(reason, str) and (
        reason in (ANKI_CLOSED, anki_session.CLOSED, anki_session.UNUSABLE, anki_session.NO_PROFILE_YET,
                   anki_session.NO_PROFILE_DECKS)
        or reason.startswith(anki_session.OTHER_PROFILE.split("{")[0]))


def holds_every(reason):
    """Does a wait with `reason` hold every episode, not only the one it stopped (laptop round 5 #24)? On battery, a
    wait on Anki (never ANKI_SLOW: Anki answers, one request of that episode's failed), Anki Miner's window open, or
    your list in another language: the pass ends there, every episode keeps its place, and the next look starts from
    the top — a later episode (or the next show) is never mined before the ones that waited. A list a Generate left
    unfinished (NO_LIST) too: it is the language's, never one episode's (alpha 6 try #6)."""
    if not isinstance(reason, str) or reason == ANKI_SLOW:
        return False
    return (reason in (ON_BATTERY, ANKI_MINER_OPEN, SETTING_UP, NO_LIST) or reason.startswith(OTHER_LIST.split("{")[0])
            or anki_wait(reason))


# AnkiConnect's answers that name a refusal lasting until you act (IK-r2-2, PROVISIONAL): a deck, note type (model),
# note or field not found, or a note it can't create — matched in its message, ignoring case (`lasting_refusal`)
LASTING_REFUSALS = ("deck was not found", "deck not found", "model was not found", "model not found",
                    "note type not found", "note was not found", "note not found", "field was not found",
                    "field not found", "field is missing", "cannot create note")
ONE_NOTE_REFUSALS = ("note was not found", "note not found", "cannot create note")     # one episode's, never all


def lasting_refusal(error):
    """Does AnkiConnect's answer name a refusal that lasts (LASTING_REFUSALS)? The one rule `_anki_wait` reads for
    every caller: *Needs you* for these, the episode's own wait for every other answer."""
    text = str(error).casefold()
    return any(part in text for part in LASTING_REFUSALS)


def _anki_wait(url, resume=None, error=None):
    """A call to Anki that failed, as the wait it is (laptop round 5 #26): Anki is called closed only when its port
    refuses (`anki_session.look`); one that doesn't answer in time — its own sync, a laptop under load — is *busy*;
    one that answers now (that one request failed) is ANKI_SLOW, the episode's own wait. With Anki switched off for
    the run (SURASURA_NO_ANKI_SYNC: the suites, a developer's run) it is never asked: *it isn't open*. `error`: the
    AnkiError caught — Anki answered (`action`, `protocol`): a refusal that lasts (`lasting_refusal`: a deck or note
    type gone) is no wait but *Needs you* (review IK #3: never retried every 2 minutes in silence); any other answer
    (a profile switching, a sync, Anki closing: "collection is not available") is ANKI_SLOW (IK-r2-2)."""
    from app.connect import anki_session
    if error is not None and getattr(error, "kind", None) in ("action", "protocol"):
        if lasting_refusal(error):          # a deck, note type or field gone is the language's; one note, the job's
            return Needs("anki-refused", f"Anki turned down Connect's request: {error}",
                         whole=not any(part in str(error).casefold() for part in ONE_NOTE_REFUSALS))
        return Wait(ANKI_SLOW, resume=resume)
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return Wait(ANKI_CLOSED, resume=resume)
    state = anki_session.look(url)
    return Wait({"closed": ANKI_CLOSED, "unusable": anki_session.UNUSABLE, "open": ANKI_SLOW}.get(
        state, anki_session.BUSY), resume=resume)


def _wait_or_needs(error, resume, url=None):
    """A verb's CliError as the loop reads it: Anki or another writer busy → Wait (look again), else → Needs. Its
    `anki-closed` (any failed probe) is named by the session's look (`_anki_wait`). A list a Generate left unfinished
    (`list: unfinished`) is NO_LIST; a need naming the language's own trouble (`need`: a deck to choose, Anki Miner's
    setup) is that kind, once for the language (`Needs.whole`, alpha 6 try #6)."""
    if error.code == "anki-closed":
        return _anki_wait(url, resume)
    context = getattr(error, "context", None) or {}
    if error.code == "busy" and context.get("list") == "unfinished":
        return Wait(NO_LIST, resume=resume)
    if context.get("need"):
        return Needs(context["need"], error.message, whole=True)
    if error.code in ("anki-busy", "busy", "anki-miner-busy", "settings-unreadable"):
        say = {"anki-busy": REVIEWING, "anki-miner-busy": _miner_busy()}.get(error.code, error.message)
        if error.code == "anki-busy" and context.get("anki") == "busy":     # Anki busy with its sync (#370)
            from app.connect import anki_session
            say = anki_session.BUSY
        return Wait(say, resume=resume)
    return Needs(error.code, error.message)


def _miner_busy():
    """Anki Miner's BUSY as the wait says it: its setup running from Surasura (A2-6), else its window open."""
    from app.connect import anki_miner
    return SETTING_UP if anki_miner.setting_up() else ANKI_MINER_OPEN


def _miner_wait_or_needs(error, url=None):
    if error.kind == "busy":
        return Wait(_miner_busy(), resume="mining")
    if error.kind == "writer-busy":
        return Wait(WRITER_BUSY, resume="mining")
    if error.kind == "reviewing":
        return Wait(REVIEWING, resume="mining")
    if error.kind == "anki-closed":
        return _anki_wait(url, "mining")
    if error.kind == "absent":
        return Skip("Anki Miner isn't installed")
    from app.cli.verbs import _MINER_CODES
    return Needs(f"anki-miner-{error.kind}", error.message, whole=_MINER_CODES.get(error.kind) == "needs-you")


def _on_disk(path):
    """A file really on this computer: there, and not a cloud placeholder (whose read would download it, RD-S1)."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    return not (getattr(st, "st_file_attributes", 0) & _PLACEHOLDER)


def paired_video(pairing, find, on_disk=None, was=()):
    """The video a pairing names (`video_path`), on this computer -> its path; else one its item's origins marked
    moved named (`was`: `library.Moved.was`, or a call that reads it: only once the named path is gone); else, moved, the one `find(names, size)` (a video index's
    lookup) gives by its name and size, when its bytes say it is the paired video; else None. One rule for Connect
    (`Runner.video`) and the window's ▶ (`app/services/play.py`): the two never disagree. `on_disk`: "on this
    computer" as the caller asks it (▶'s looks: a share offline waited on once a round), `_on_disk` unless given."""
    from app.connect import videos
    named = pairing.get("video_path")
    if (on_disk or _on_disk)(named):
        return named                        # the named path is trusted as it is: never read (a stat only)
    if pairing.get("producer") == "source":     # a marked row stands in for its own item's source record only: hato's
        left = moved_video(was() if callable(was) else was, on_disk)    # and a link's are judged by their bytes below
        if left:
            return left
    size = pairing.get("video_size")
    found = find([os.path.basename(named)], size if isinstance(size, int) and size > 0 else None)
    # away from its named path, a file of that name and size is the paired video only when its bytes say so
    # (09-hato-layer v2 §1.1): another episode under the same name is never mined as this one. A source
    # folder's record keeps the video's key as `video_key` (its row is keyed by the origin: SRC B1), and one
    # with no key takes no moved video; every other record is judged as before Sources (review H14)
    if pairing.get("producer") == "source":
        key = pairing.get("video_key")
        refused = found is not None and (key is None or videos.content_key(found) != key)
    else:
        refused = found is not None and videos.content_key(found) != pairing.get("content_key")
    if refused:
        log.info("Connect: %s has the paired video's name and size but not its content; not used", found)
        return None
    return found


def moved_video(was, on_disk=None):
    """D5 (Kura's MV-A5: a `moved_to` mark is never trusted alone): the first video an origin marked moved named that
    is still on this computer at the size the store recorded -> its path (a stat, as a pairing's own path is: a file
    of another size there now is another file); else None. `was`: `library.Moved.was` ((path, size), the newest origin
    first)."""
    for path, size in was or ():
        if (on_disk or _on_disk)(path):
            try:
                if size is None or os.stat(path).st_size == size:
                    return path
            except OSError:
                continue
    return None


def video_left(pairing, root, reachable=None):
    """MV-2: the folder a source folder's episode's video was in (its record's `video_path`), when the video isn't
    there any more while the source folder it was read from is (`root`: that folder's path, `library.Moved.root`; one
    that can't be reached — a drive unplugged, a share offline — is no move: the store's own rule, `sources._lost`)
    -> that folder; else None (another program's record, no video named, one outside that source folder — its own
    drive may be the one unplugged —, the video there: a cloud placeholder of it too, it isn't downloaded, it didn't
    move). A stat or two, never a listing. One rule for Connect's *No video* line
    and ▶'s. `reachable(root)`: whether the source folder is there, as the caller asks it (▶'s looks: a share
    offline waited on once a round), `os.path.isdir` unless given."""
    if (pairing or {}).get("producer") != "source" or not isinstance(root, str) or not root:
        return None
    named = pairing.get("video_path")
    if not isinstance(named, str) or not os.path.isabs(named):
        return None
    from app.library_store import path_key
    if not path_key(os.path.abspath(named)).startswith(path_key(os.path.abspath(root)).rstrip("/") + "/"):
        return None
    if not (reachable or os.path.isdir)(root):
        return None
    if os.path.lexists(named):
        return None
    return os.path.dirname(named)


_MOVED_HEAD, _MOVED_TAIL = MOVED.split("{")[0], MOVED.split("}")[1]


def moved_folder(reason):
    """The folder MV-2's line names (`MOVED`), or None for any other reason."""
    if isinstance(reason, str) and reason.startswith(_MOVED_HEAD) and reason.endswith(_MOVED_TAIL) and \
            len(reason) > len(_MOVED_HEAD) + len(_MOVED_TAIL):
        return reason[len(_MOVED_HEAD):-len(_MOVED_TAIL)]
    return None


def no_video(reason):
    """Is `reason` a wait for the episode's video — *No video* (`NO_VIDEO`), or MV-2's moved line (`MOVED`)?"""
    return reason == NO_VIDEO or moved_folder(reason) is not None


def origin_of(pairing):
    """The original an item's text was copied from, as its origin record names it (`producer` "source": a folder's
    look, or + Add's / a drop's, `via` "add") -> its path; else None. One rule for Connect and the window's ▶."""
    origin = (pairing or {}).get("origin") if (pairing or {}).get("producer") == "source" else None
    return origin if isinstance(origin, str) and origin else None


def beside_origin(pairing, exts=None, unlisted=None, listings=None):
    """K21 (laptop fixes): the video beside the original an item's text was copied from (`origin_of`), with its name,
    on disk -> its path; else None (no record, another producer's, none there, a placeholder). A listing and a stat,
    never a read. Qt-free: Connect's `video()` asks it after `beside(subtitle)`; ▶ asks it too, with `exts`,
    `unlisted` and `listings` as `beside` takes them (an audio item's ▶; a share offline; a round of ▶'s looks)."""
    origin = origin_of(pairing)
    return beside(origin, exts, unlisted, listings) if origin else None


def beside(subtitle, exts=None, unlisted=None, listings=None):
    """A video next to the subtitle with its name (`Show - 05.mkv` for `Show - 05.ja.srt`), on disk -> its path; None
    when there's none, `unlisted` when its folder can't be listed (a share offline: the window's ▶ says so). `exts`:
    what is looked for, the video extensions unless given (an audio item's ▶ looks for audio). `listings` ({folder: its
    names}, a caller's own — + Add's many files, ▶'s round of looks): each folder listed once across calls (H6), one
    that couldn't be listed too (False: a share offline is tried once, never once a file)."""
    from app.episode_names import video_stems
    folder, name = os.path.split(subtitle)
    stems = video_stems(name)               # LM1a: its stem, without the marks the one rule reads, NFC and NFD
    names = listings.get(folder) if listings is not None else None
    if names is None:
        try:
            names = {n.lower(): n for n in os.listdir(folder or ".")}
        except OSError:
            names = False
        if listings is not None:
            listings[folder] = names
    if names is False:
        return unlisted
    for s in stems:
        for ext in exts or VIDEO_EXTENSIONS:
            found = names.get((s + ext).lower())
            if found and _on_disk(os.path.join(folder, found)):
                return os.path.join(folder, found)
    return None

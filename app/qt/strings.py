"""Every user string of the window (W2.1 on; the window's spec 05 §5.12, 01 §1.5: one table, so the app can be
translated later). Code under `app/qt/` names a string from here, never writes one inline. Log lines are not user
strings and stay with their code.
"""

# The window (G1.2-17: the subtitle lives in the title, not the header).
WINDOW_TITLE = "Surasura — The Immersion Architect"
WORDMARK = ("Sura", "sura")                   # the second half wears the iris
WORDMARK_NAME = "Surasura"
LANGUAGE_NAMES = {"ja": "日本語", "zh": "中文"}

# The tabs: name, tooltip (D17: every button and toggle has one).
TABS = {
    "current": ("Current", "What you're working through now, in the order you'll meet it"),
    "finished": ("Finished", "What you've finished: a record, and still a source of sentences"),
    "needs": ("Needs you", "Something here waits for a look or a decision from you"),
    "settings": ("Settings", "Every setting, on one page"),
}
TABS_NAME = "Sections"

# Each page until its step builds it (W2.2 Current, W3.2 Finished and Needs you, W3.3 Settings).
PAGE_WAITING = "This page arrives in a later build of 3.0."

# --- W2.2: the first screens (Current, Finished, Needs you; the painted rows) ------------------------------------ #
CURRENT_HEADING = "Current"
CURRENT_HEADING_TIP = "What you're working through, in the order you'll watch and read it"
CURRENT_EMPTY = ("Nothing in Current yet", "What you'll watch and read next shows here, in order")
FINISHED_HEADING = "Finished"
FINISHED_HELP = "?"
FINISHED_HELP_NAME = "About Finished"
FINISHED_HELP_TIP = ("<b>A record of what you've worked through.</b> Your list is ordered by how often a word turns up "
                     "in what you're <i>going</i> to watch and read. You won't meet a finished show again, so its words "
                     "stop pushing your list around — but its sentences can still be your examples")
FINISHED_EMPTY = ("Nothing finished yet", "What you finish is kept here: a record, and a source of sentences")
NEEDS_HEADING = "Needs you"
NEEDS_EMPTY = ("Nothing needs you", "When something waits on you, it shows here")
TAB_COUNT = "{name}  {count}"                   # Finished's records, Needs you's unseen entries
GOAL_NAME = "Goal"
LIST_NAMES = {"current": "Current", "finished": "Finished", "needs": "Needs you"}
STATE_LINES = {
    "getting-ready": "Getting your library ready… Your list shows as it was; nothing can be moved until it's done.",
    "busy": "Updating your library…",
    "read-only": "Read-only: {reason}. Nothing can be moved until it's fixed.",
    "migration-failed": "Read-only: your library couldn't be brought into 3.0's store, so it shows as it was. "
                        "Open the logs folder (the bar) and send it in; nothing of yours was changed.",
}
READ_ONLY_REASONS = {
    "damaged": "the library needs a repair — Surasura keeps its last good copy; send the logs folder (the bar) in",
    "made by a newer Surasura": "your library was saved by a newer Surasura — update Surasura to change it",
    "busy": "another program is saving your library — it opens as soon as that's done",
}
READ_ONLY_IO = "Surasura can't read the library's file — check its drive is there, then restart Surasura"
PLAY_FAILED = "Couldn't open {name}: {why}"
PLAY_NOT_ON_DISK = "it isn't on disk"
PLAY_NO_MEDIA_BESIDE = "no {word} beside it on disk"
GOAL_ACCESSIBLE = "{name}: {line}"
ROWS_PCT = "{pct}%"
ROWS_MORE_CHIP = "+{n}"
ROWS_DOT = "·"
ROWS_NEW_WORD = "new"
ROWS_DASH = "—"
ROWS_UP_NEXT = "UP NEXT"
ROWS_SOURCE = {"hato": "Hato", "youtube": "YouTube", "anilist": "AniList"}
ROWS_HERO_STATS = "{pct}% known · {n} new words"
ROWS_HERO_STATS_NONE = "not analysed yet"
ROWS_VERB = {"video": "Watch", "audio": "Listen", "EPUB": "Read", "file": "Open"}
ROWS_NO_MEDIA_BUTTON = "No {word}"
ROWS_ONLINE_BUTTON = "Online"
ROWS_STUDYING = "Studying its cards first"         # after a painted up arrow (G2.3 R3)
ROWS_STUDYING_TIP = "Its new cards go first in Anki until they're studied"
ROWS_TICK_WATCHED = "Watched"
ROWS_TICK_NOT = "Not watched yet"
ROWS_MORE_CHIPS = "{n} more"
ROWS_FAILURE_LINE = "Its details are in the logs folder (the bar's Open the logs folder)"
# The string of stones, read out for a screen reader (W3.1a; `stone_plan.words`): "8 of 12 watched, 3 in Anki".
STRING_WORDS = {
    "of_watched": "{k} of {n} watched", "in_anki": "{n} in Anki",
    "one_watched": "Watched", "one_not": "Not watched yet", "one_in_anki": "in Anki",
    "join": ", ",
}
# --- end W2.2 ---------------------------------------------------------------------------------------------------------- #

# The bottom bar.
BAR_NAME = "Status"
BAR_FAILURE_PREFIX = "⚠ "
BAR_LOGS = "Open the logs folder"
BAR_LOGS_TIP = "Open the folder where Surasura keeps its logs, to look at them or send them"
BAR_FAILURE_TIP = "The newest problem a command-line run reported. Its details are in the logs folder"

# The look (G1.2-21): shown only if a live switch is ever too slow.
RESTART_TO_APPLY = "Restart Surasura to apply"

# The frame-time HUD (a developer's overlay, SURASURA_HUD=1).
HUD_LINE = "step p95 {sp} max {sm} >4ms {so}  ·  frame p95 {fp} max {fm}"

# --- M2.1: toasts (05 §5.4) and the motion
TOAST_UNDO = "Undo"
TOAST_UNDO_TIP = "Undo this change"

# --- W3.5: the dashboard's duties (the header's Generate and journey, the bar's marks, the update) ------------------ #
GENERATE = "Generate"
GENERATE_CURRENT = "Generate ✓"
GENERATE_QUEUED = "Generate · waiting"
GENERATE_RUNNING = "Generating… {pct} %"
GENERATE_RUNNING_NO_PCT = "Generating…"
GENERATE_STOPPING = "Stopping…"
GENERATE_FAILED = "Generate ⚠"
GENERATE_WAITING = "Waiting to start"
GENERATE_TIP = "Build your list and your journey from your library and the words you know\n• Click to generate"
GENERATE_CURRENT_TIP = ("Your list is up to date: nothing in your library, your known words or your settings changed "
                        "since your last Generate\n• Click to generate again anyway")
GENERATE_STALE_TIP = "Something changed since your last Generate, so your list is out of date\n• Click to generate"
GENERATE_QUEUED_TIP = "{line}\n• Click to cancel"
GENERATE_RUNNING_TIP = "Generating your list: {step}\n• Click to stop before your list is written"
GENERATE_WRITING_TIP = "Generating your list: {step}. It can't stop part-way here, and finishes in a moment"
GENERATE_FAILED_TIP = "Generate didn't finish: {message}\n• Click to try again"
GENERATE_AUTO_TIP = ("Generating by itself, because Anki brought in words you know: {step}\n• Click to generate now: "
                     "your own run takes its place and opens your journey")
GENERATE_LOG = "Open the log"
GENERATE_LOG_TIP = "Open the last Generate's log, to see what went wrong"
GENERATE_PROGRESS_NAME = "Generate's progress"
JOURNEY_TIP = "Your list with its sentences, in its own window\n• Click to open your journey"
JOURNEY_NONE_TIP = "Your journey appears after your first Generate"
JOURNEY_FAILED = "Couldn't open your journey: {why}"
HELP = "?"
HELP_NAME = "Help"
HELP_TIP = "Help\n• Click for the online guide"
HELP_GUIDE = "Online guide"

# The bottom bar's marks: statuses with tooltips (W3.3 makes them open Settings' sections).
BAR_KNOWN = "{n:,} known"
BAR_KNOWN_TIP = "The words you know: from Anki and your own known-words list"
BAR_ANKI = {
    "syncing": "Anki: syncing…",
    "synced": "Anki ✓",
    "anki-closed": "Anki closed — work waits",
    "failed": "Anki ⚠",
    "off": "Automatic sync off",
}
BAR_ANKI_TIP = {
    "syncing": "Reading the words you know from Anki",
    "synced": "Your known words are up to date with Anki",
    "synced-added": "Your known words are up to date with Anki: {n:,} new since the last sync",
    "anki-closed": "Anki isn't open: the sync and Anki's re-order wait until it is",
    "failed": "The last sync from Anki didn't finish: {message}",
    "off": "Surasura doesn't read the words you know from Anki by itself: the automatic sync is off",
}
BAR_LEVEL_AUTO = "Auto · {band}"
BAR_LEVEL_AUTO_NONE = "Auto"
BAR_LEVEL_TIP = "Your level: your list holds the words at least as common as {band}"
BAR_LEVEL_AUTO_TIP = ("Your level, chosen for you: the rarest band whose list stays short, {band} now")
BAR_LEVEL_AUTO_NONE_TIP = "Your level is chosen for you after your first Generate"
# W3.5 row 7: the re-order's line (the host's own words, said whole in its tooltip), Connect's, AnkiWeb's, the dot.
# The re-order's tip promises nothing: the line beside it may say it stands aside.
BAR_REPLAN_TIP = "{line}\n\nAnki's new cards in your list's order: what Surasura is doing about it, or why it waits"
BAR_CONNECT_TIP = "What Surasura Connect is doing with your cards in this language"
JOURNEY_DOT = "●"
JOURNEY_DOT_NAME = "Your journey's sentences are catching up"
# The dot's tip: "by itself" only while the automation is on (D29: the journey's Generate runs), else press Generate.
JOURNEY_DOT_TIP = ("Your journey's sentences are catching up with your newest list: a Generate brings them in by "
                   "itself. Your journey opens meanwhile, with the sentences it has")
JOURNEY_DOT_TIP_PRESS = ("Your journey's sentences are catching up with your newest list: press Generate to bring them "
                         "in. Your journey opens meanwhile, with the sentences it has")

# The update: the bar's mark, the sheet, Needs you's cards.
UPDATE_READY = "Update ready"
UPDATE_DOWNLOADING = "Downloading update {pct} %"
UPDATE_DOWNLOADING_NO_PCT = "Downloading update…"
UPDATE_RESTART = "Restart to update"
UPDATE_HANDING = "Restarting to update…"
UPDATE_MARK_IDLE_TIP = "Shown when a new Surasura is ready to install"
UPDATE_MARK_TIP = "Surasura v{version} is ready\n• Click to see what it is and update"
UPDATE_MARK_DOWNLOADING_TIP = "Downloading Surasura v{version}\n• Click to see its progress"
UPDATE_MARK_WAIT_TIP = "Surasura v{version} is downloaded and waits for what's still running\n• Click to see what it waits for"
UPDATE_MARK_HANDING_TIP = "Surasura closes, the update installs, and Surasura opens again by itself"
UPDATE_SHEET_TITLE = "Surasura v{version}"
UPDATE_SHEET_CRITICAL = "Surasura v{version}: an important update"
UPDATE_DOWNLOADING_LINE = "Downloading the update… {pct} %"
UPDATE_DOWNLOADING_LINE_NO_PCT = "Downloading the update…"
UPDATE_WAITING_LINE = "The update is downloaded. It installs once these finish:"
UPDATE_INSTALLING_LINE = "Installing: Surasura closes and opens again by itself"
UPDATE_PROGRESS_NAME = "The update's download"
UPDATE_NOTES = "What's new ↗"
UPDATE_NOTES_TIP = "Open this version's release notes in your browser"
UPDATE_NOW = "Update now"
UPDATE_NOW_TIP = "Download the update and install it: Surasura closes for a moment and opens again"
UPDATE_DOWNLOAD = "Download"
UPDATE_DOWNLOAD_TIP = "Open the release page in your browser, to download this version yourself"
UPDATE_SKIP = "Skip this version"
UPDATE_SKIP_TIP = "Don't offer this version again (a newer one is still offered)"
UPDATE_LATER = "Later"
UPDATE_LATER_TIP = "Close this: the update stays offered in the bar"
UPDATE_STOP = "Stop it"
UPDATE_STOP_NAME = "Stop it: {name}"
UPDATE_STOP_TIP = "Stop {name} now, so the update can install"
UPDATE_STOP_ALL = "Stop all and update now"
UPDATE_STOP_ALL_TIP = "Stop everything listed that can be stopped, then install the update"
UPDATE_CANCEL = "Cancel"
UPDATE_CANCEL_TIP = "Don't install it now: the update stays offered (Esc does the same)"
NEEDS_UPDATE_TITLE = "Install the update"
NEEDS_UPDATE_LINE = "Surasura v{version} is ready to install"
NEEDS_UPDATE_FAILED_TITLE = "The update didn't finish"
UPDATED = "Updated to v{version} ✓"

# Closing while an Anki write runs (E20: it finishes its batch first, and a line says so) — the bar's one line, and
# the reason a job asked for meanwhile waits.
QUIT_FINISHING = "Finishing with Anki first… the window closes by itself"
QUIT_FINISHING_LIST = "Finishing your list first… the window closes by itself"
QUIT_HELD = "Surasura is closing"
QUIT_CLOSING_TIP = "Surasura is closing: it finishes what can't stop part-way, then closes by itself"

# --- W3.1a frame (app/qt/frame.py): the level ▾ and its pop, the footer's emerald and known corner, the Goal dock and
# its wells. The level's words are the old chip's (BAR_LEVEL_*); Generate's are the button's (GENERATE_*).
LEVEL_WAITING = "Level"                               # the ▾ before the level is first read
LEVEL_NAME = "Your level: {level}"
LEVEL_TIP = "{level}\n• Click for Generate and your journey"
LEVEL_TIP_MARK = "{level}\n{mark}\n• Click for Generate and your journey"
LEVEL_MARKS = {
    "failed": "⚠ The last Generate didn't finish",
    "stale": "Something changed since your last Generate: your list is out of date",
    "journey": "Your journey's sentences are catching up",
}
LEVEL_POP_NAME = "Your level, Generate and your journey"
LEVEL_POP_HEADING = "YOUR LEVEL"
LEVEL_POP_AUTO = {True: "Automatic: on — Surasura picks the band for you",
                  False: "Automatic: off — the band stays where you set it"}
LEVEL_JOURNEY = "Open your journey ↗"
FOOT_ANKI = "Anki"
FOOT_ANKI_NAME = "Anki: {words}"
FOOT_ANKI_TIP = "{words}\n{tip}"
FOOT_ANKI_ANKIWEB = "{tip}\n\n{ankiweb}"
FOOT_KNOWN = "known"
FOOT_KNOWN_TIP = "{tip}\n{left:,} to {next:,}"
WELLS = {"soon": "Soon", "goal": "Goal", "finished": "Finished"}
WELL_SUBS = {"soon": "next in line", "goal": "someday · in no order", "finished": "newest first"}
WELL_TIPS = {"soon": "Soon: drop it here and it comes up next in line",
             "goal": "Goal: drop it here for someday, in no order",
             "finished": "Finished: drop it here when you're done with it"}
WELL_UNLIT_SPLIT = "Finished: a split's first part finishes with its last part, not on its own"
WELL_UNLIT_MIX = "Finished: hato's mix never finishes, it keeps bringing new videos"
WELLS_NAME = "Where it can go: {wells}"

# --- W3.1a rows (app/qt/rows.py): Current's one-line row, the string on it, Up Next flat, the grooves. A row's other
# words are W2.2's (ROWS_*) and view_rows'.
ROWS_MORE_TIP = "More\n• Click for what you can do with it"
ROWS_MOVE_TIP = {"up": "Move up one\n• Click to move it up one place",
                 "down": "Move down one\n• Click to move it down one place"}
ROWS_MINE_NOW_TIP = "{tip}\n• Click to mine it now"
ROWS_MINE_NOW_LATER = "Mine now arrives with Anki Miner's step, in a later build"
ROWS_NO_MEDIA_LATER = "{tip}\nLink… · Mine text: in a later build"
ROWS_STONE_TIP = "{label}{state}\n• Click to mark it {action}"
ROWS_STONE_STATE = {"cut": " · watched", "raw": " · {n} cards in Anki", "rock": ""}
ROWS_STONE_MISSING = " · no {word} on disk"
ROWS_STONE_ACTION = {True: "not watched", False: "watched"}
ROWS_DONE = "Done"
ROWS_DONE_TIP = "Mark {ep} watched\n• Click: the one after it comes up next"
ROWS_DONE_ALL_TIP = "Every file of it is watched"
ROWS_HERO_KNOWN = "{pct}% known · "
ROWS_HERO_NEW_LINK = "{n} new words ↗"
ROWS_JOURNEY_TIP = "Open your journey at this episode\n• It opens in its own window"
ROWS_TOP_LINE_WHERE = "{tip}\nIts setting: Settings → Anki & mining, in a later build"
ROWS_SOON_LINE_WHERE = "{tip}\nWhere Soon starts is a setting: Settings, in a later build"
ROWS_ACCESSIBLE_STRING = "{line} · {string}"

# --- W3.1a footer (W31A-1 / W31A-2): the re-order's and Connect's lines as quiet marks (their words in the hover), and
# the cards waiting in Anki beside the emerald.
FOOT_REPLAN_MARK = "⇅"
FOOT_REPLAN_NAME = "Anki's re-order"
FOOT_CONNECT_MARK = "⇄"
FOOT_CONNECT_NAME = "Surasura Connect"
FOOT_CONNECT_TIP = "{line}\n\n" + BAR_CONNECT_TIP
FOOT_ANKI_WAITING = "Anki · {n:,} waiting"
FOOT_ANKI_WAITING_TIP = "{n:,} new cards wait in Anki, in the decks the sync reads"

# --- W3.1a drag: the window's writer (app/services/moves.py `Writer(words=MOVE_WORDS)`, its notes: moves.WORDS's keys)
MOVE_WORDS = {
    "saving": "Saving your moves…",
    "cant_undo": "Can't undo — that item changed since",
    "nearest": "That spot changed meanwhile — placed next to the nearest item instead",
    "top": "That spot changed meanwhile — placed at the top instead",
    "crash_one": "1 move from before the crash couldn't be applied",
    "crash_many": "{n} moves from before the crash couldn't be applied",
    "read_only": "Your library can't be saved right now: {reason}",
    "failed": "That change couldn't be saved: {error}",
}

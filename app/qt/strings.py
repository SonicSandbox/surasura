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
ROWS_JOURNEY_TIP = "Your journey: your list with its sentences\n• Click to open it in its own window"
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
FOOT_ANKI_WAITING_TIP = "{n:,} new notes wait in Anki, in the decks the sync reads"   # backlog notes, not cards (AD-8)

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
    "not_content": "Only text and subtitle files can be added — left out: {names}",
}
# --- W3.2 S2: the writer's new commands (moves.WORDS) --------------------------------------------------------------- #
MOVE_WORDS.update({
    "put_back_as": "Put back under a new name (the old one was taken): {names}",
})
# --- end W3.2 S2
# --- W3.2 B: the YouTube downloader's files into New arrivals (its status line and the bottom bar, once they land)
YT_ARRIVED_WAITING = "{what} in New arrivals"
YT_ARRIVED_PLACED = "{what} placed by your rules for new arrivals"
YT_ARRIVED_BOTH = "{waiting} in New arrivals · {placed} placed by your rules"
YT_ARRIVED_LABEL = "New transcripts"
YT_READ_ONLY = "your library can't be saved right now ({reason}): the transcripts wait in Processed"
YT_NO_LIBRARY = "no library is open: the transcripts wait in Processed"


def yt_transcripts(n):
    return f"{n} transcript" if n == 1 else f"{n} transcripts"
# --- end W3.2 B
# the drag in the window (app/qt/drag.py): its toasts (A2's toast list), the ⋯ menu, the bar's lines
DRAG_UP_NEXT = "{title} is up next"
DRAG_PLACED = "{title} placed at #{n}"
DRAG_PLACED_MINES = "{title} placed at #{n} · it mines itself"
DRAG_SOON = "{title} → Soon · #{n}, after the first {files} files"
DRAG_SOON_NO_COUNT = "{title} → Soon · #{n}"
DRAG_GOAL = "{title} moved to Goal · its cards keep their place"
DRAG_FINISHED = "{title} finished · its cards stay put"
DRAG_KEEP = "Keep"
DRAG_KEEP_TIP = "Keep its new cards in your order, as they are"
DRAG_TAKE_OUT = "Take its new cards out"
DRAG_TAKE_OUT_TIP = "Its new cards leave your order. None is deleted: Undo puts them back"
DRAG_TAKEN_OUT = "{title}: its new cards are out of your order"
DRAG_ADDED = "Added {name} at #{n} · analysed on the next Generate"
DRAG_ADDED_N = "Added {count} files at #{n} · analysed on the next Generate"
DRAG_GONE = "That item was removed"
DRAG_REFUSED = "Your library can't be saved right now: {reason}"
DONE_NEXT = "✓ {title} {ep} watched · next: {next}"
DONE_ONE = "✓ {title} {ep} watched"
DONE_UNDONE = "{title} {ep} marked not watched"
DONE_ALL = "✓ All {n} watched — finished with it?"
DONE_MOVE_FINISHED = "Move to Finished"
DONE_MOVE_FINISHED_TIP = "Move it to Finished: a record of what you've worked through"
MENU_NAME = "What you can do with {title}"
MENU_ITEMS = {
    "up-next": ("Up next", "Make it the next thing you watch or read"),
    "soon": ("Soon", "Move it to Soon: next in line, after what's in NOW"),
    "goal": ("Goal", "Move it to Goal: someday, in no order"),
    "finished": ("Finished", "Move it to Finished: you're done with it"),
    "journey": ("See it in your journey", "Open your journey (your list with its sentences) in its own window"),
}
MENU_REFUSED_TIP = "Your library can't be saved right now: {reason}"
ROWS_SAVING = "saving…"

# --- W3.4: the ported windows — the base (windows.py, confirm.py) and row 1 (the frequency lists, the sentence
# dictionary). The Settings tab lists the ported windows' doors until W3.3 / W3.2 give each its row (IK-16).
SECONDARY_TITLE = "{name} — Surasura"
WINDOW_STATUS_NAME = "What this window is doing"
LAUNCHERS_NAME = "Windows that open from here until their Settings rows arrive"
OPEN_FAILED = "{name} couldn't open: {why}"
CONFIRM_NO = "Cancel"
CONFIRM_NO_TIP = "Leave everything as it is (Esc does the same)"

# The frequency lists (from the Tk Frequency List Manager)
FREQ_NAME = "Frequency lists"
FREQ_TIP = "Add or remove general frequency lists (CSV): the report shows how common each word is in them"
FREQ_LIST_NAME = "Your frequency lists for this language"
FREQ_LIST_TIP = ("Surasura already makes a frequency list from your own content. These general lists add a column, "
                 "to see how common each word is elsewhere")
FREQ_EMPTY = "No frequency lists yet: get one, then add it"
FREQ_ADD = "Add…"
FREQ_ADD_TIP = ("Choose one or more CSV frequency lists to add\n"
                "• A list with the same name is replaced: the old one is kept in the trash folder")
FREQ_REMOVE = "Remove…"
FREQ_REMOVE_TIP = "Remove the selected lists\n• They move to the trash folder in User Files: nothing is deleted"
FREQ_REMOVE_NONE_TIP = "Select a list to remove it"
FREQ_GET = "Get lists ↗"
FREQ_GET_TIP = "Open jiten.moe/other in your browser: frequency lists to download"
FREQ_GET_URL = "https://jiten.moe/other"
FREQ_CREDIT = "Credit to mattias ↗"
FREQ_CREDIT_TIP = "Open the page of mattias in your browser"
FREQ_CREDIT_URL = "https://github.com/mattias"
FREQ_PICK_TITLE = "Add frequency lists"
FREQ_PICK_FILTER = "CSV files (*.csv)"
FREQ_ADDED = "Added: {n}"
FREQ_KEPT = "the old {name} is in the trash folder"
FREQ_SAME = "{name} is this list already"
FREQ_ADD_FAILED = "{name} couldn't be added: {why}"
FREQ_REMOVE_ONE = "Remove {name}?"
FREQ_REMOVE_MANY = "Remove {n} frequency lists?"
FREQ_REMOVE_BODY_ONE = "It moves to the trash folder in User Files, never deleted. Your next Generate reads without it."
FREQ_REMOVE_BODY_MANY = ("They move to the trash folder in User Files, never deleted. Your next Generate reads without "
                         "them.")
FREQ_REMOVE_YES = "Remove"
FREQ_REMOVE_YES_TIP = "Move the lists to the trash folder"
FREQ_REMOVED = "Removed: {n}, kept in the trash folder"
FREQ_REMOVE_FAILED = "{name} couldn't be removed: {why}"
FREQ_READ_FAILED = "The lists couldn't be read: {why}"

# The sentence dictionary (from the Tk dashboard's export dialog)
DICT_NAME = "Sentence dictionary"
DICT_TIP = ("A Yomitan dictionary of up to 8 of the best sentences for every word in your library — hover a word in "
            "your browser to see them")
DICT_SOURCE = "Show where each sentence came from"
DICT_SOURCE_TIP = ("Adds a short file name under each sentence. Off keeps the popup cleaner\n"
                   "• Off: hovering a sentence still shows where it came from")
DICT_EXPORT = "Export…"
DICT_EXPORT_TIP = "Choose where to save the dictionary, then build it"
DICT_EXPORT_BUSY_TIP = "The dictionary is being built: its progress is in the bar"
DICT_SAVE_TITLE = "Save the sentence dictionary"
DICT_SAVE_FILTER = "Zip files (*.zip)"
DICT_CHECKING = "Looking at your library…"
DICT_EMPTY = "Add content to your library first: the dictionary is built from your own files"
DICT_JOB = "Building the sentence dictionary"
DICT_RUNNING = "Building {title}…"
DICT_READY = "{title} is ready. {summary}"
DICT_NOTE = "In Yomitan: Settings → Dictionaries → Import. Delete an older one there first."
DICT_NOTE_TIP = ("Import {file}\n"
                 "• Yomitan won't import a second dictionary with the same name: delete the older one first")
DICT_FAILED = "The dictionary couldn't be made: the log says why"
DICT_STOPPED = "Stopped: nothing was made"
DICT_WAITING_FOR = "Waiting its turn: {what} runs first, then the dictionary builds"
DICT_WAITING = "Waiting to start: {reason}"
DICT_REPLACE_ONE = "Replace {name}?"
DICT_REPLACE_BODY = "A file with that name is there already. The new dictionary takes its place."
DICT_REPLACE_YES = "Replace"
DICT_REPLACE_YES_TIP = "Build the dictionary over the file that is there"
DICT_OPEN_FOLDER = "Open folder"
DICT_OPEN_FOLDER_TIP = "Open the folder the dictionary was saved in"
DICT_OPEN_LOG = "Open the log"
DICT_OPEN_LOG_TIP = "Open the export's log: it says why it stopped"

# --- W3.4 row 6: 順 Junban (+ Put Anki back) — the doors on the Settings tab's list (until W3.3 gives them rows)
JUNBAN_DOOR = "順 Junban"
JUNBAN_DOOR_TIP = "Reorder Anki's new cards to Surasura's learn order: preview first, then Reorder. Needs Anki open."
PUT_BACK_DOOR = "Put Anki back…"
PUT_BACK_DOOR_TIP = ("Put Anki's new cards back the way they were before Surasura changed them. Asks first, with the "
                     "counts. Needs Anki open.")

# --- W3.4 row 5: Backfill (its door; the window's own words are Junban's: modules/junban/qt_strings.py)
BACKFILL_DOOR = "Anki Backfill"
BACKFILL_DOOR_TIP = "Fill fields on your Anki cards from Surasura: パターン and 例文"
# --- W3.4 row 2: the known-word importers (.apkg, Migaku, Jiten) and Extract (app/qt/importers.py) ---------------- #
IMPORTERS_LAUNCH_APKG = "Known words from a deck…"
IMPORTERS_LAUNCH_APKG_TIP = ("Every word in one field of an exported Anki deck (.apkg) becomes a known word\n"
                             "• Offline: it imports every note in the file, studied or not")
IMPORTERS_LAUNCH_MIGAKU = "Migaku…"
IMPORTERS_LAUNCH_MIGAKU_TIP = "Replace your known words with Migaku's, from its database export"
IMPORTERS_LAUNCH_JITEN = "Jiten…"
IMPORTERS_LAUNCH_JITEN_TIP = "Replace your known words with your Jiten account's (Japanese only)"
IMPORTERS_LAUNCH_EXTRACT = "Extract…"
IMPORTERS_LAUNCH_EXTRACT_TIP = ("Split an EPUB, a text or subtitle file, or a deck's sentences into parts\n"
                                "• They're added to the section you choose")
IMPORTERS_LOG = "Open the log"
IMPORTERS_LOG_TIP = "Open what the last run printed, line by line"
IMPORTERS_BUSY = "Working… (it carries on if you close this window)"
IMPORTERS_WAITING_FOR = "Waiting its turn: {what} runs first"
IMPORTERS_WAITING = "Waiting to start: {reason}"
IMPORTERS_FAILED = "That didn't work: {why}"
IMPORTERS_FAILED_PLAIN = "That didn't work. Open the log to see why"
IMPORTERS_READ_FAILED = "That file couldn't be read: {why}"
KNOWN_CHANGED = "Your known words changed since you said yes, so nothing was replaced: here are the numbers now"
KNOWN_UNREADABLE = ("Your known words file can't be read, so nothing is replaced: fix it, or put a backup from its "
                    "trash folder back first")

# .apkg known words
APKG_NAME = "Known words from a deck"
APKG_LINE = "Every word in the field you choose becomes a known word"
APKG_FILE_NAME = "The deck file"
APKG_FILE_HINT = "An exported Anki deck (.apkg)"
APKG_BROWSE = "Choose a deck…"
APKG_BROWSE_TIP = "Choose an exported Anki deck (.apkg) to read."
APKG_PICK_TITLE = "Choose an Anki deck"
APKG_PICK_FILTER = "Anki decks (*.apkg);;All files (*.*)"
APKG_FIELD_NAME = "The field whose words become known"
APKG_PREVIEW_NAME = "The first notes of that field"
APKG_EVERY_NOTE = "Imports every note in the file. To import only studied cards, use Sync now in Anki known words."
APKG_IMPORT = "Import"
APKG_IMPORT_TIP = ("Add every word in the chosen field to your known words. Existing entries are kept, and words you "
                   "have ignored stay ignored.")
APKG_READING = "Reading the deck…"
APKG_READ = "{notes:,} notes · {fields} fields"
APKG_NOT_A_DECK = "Choose an .apkg file: an Anki deck you exported"
APKG_ASK_TITLE = "Add these words to your known words ({language})?"
APKG_ASK_BODY = ("Every word in the “{field}” field of all {notes:,} notes becomes a known word, studied or not — words "
                 "you are still learning too. Words you know stay as they are; ignored words stay ignored. Your list "
                 "is backed up first.")
APKG_ASK_YES = "Add the words"
APKG_ASK_YES_TIP = "Read the deck and add its words to your known words"
APKG_DONE = "Added {added:,} new words and marked {raised:,} known · {total:,} words in your list"
APKG_NOTHING = "No new words: your known words are as they were"

# Migaku
MIGAKU_NAME = "Known words from Migaku"
MIGAKU_STEP1 = "1  In Migaku's browser, open the console (F12), paste this and press Enter:"
MIGAKU_CODE_NAME = "The line that downloads Migaku's database"
MIGAKU_COPY = "Copy"
MIGAKU_COPY_TIP = ("Copy the line, then paste it into the browser's console (F12) and press Enter\n"
                   "• Migaku downloads its database as a .db file")
MIGAKU_COPIED = "Copied: paste it into the console (F12) and press Enter"
MIGAKU_STEP2 = "2  Import the downloaded .db file:"
MIGAKU_FIND = "Find it for me"
MIGAKU_FIND_TIP = "Look for Migaku's export among the 3 newest .db files in your Downloads folder"
MIGAKU_CHOOSE = "Choose a file…"
MIGAKU_CHOOSE_TIP = "Choose Migaku's database export (.db) yourself"
MIGAKU_PICK_TITLE = "Choose Migaku's database file"
MIGAKU_PICK_FILTER = "Databases (*.db);;All files (*.*)"
MIGAKU_LOOKING = "Looking in Downloads…"
MIGAKU_NO_DB = "No .db files in your Downloads folder"
MIGAKU_NOT_MIGAKU = "Found .db files, but none is a Migaku export (no word list in it)"
MIGAKU_NOT_A_DB = "That file isn't a Migaku export (no word list in it)"
MIGAKU_EMPTY = "That export has no words for this language: nothing to import"
MIGAKU_ASK_TITLE = "Replace your known words ({language}) with Migaku's?"
MIGAKU_SAVED = "%Y-%m-%d %H:%M"                 # the export's time, as its question shows it
MIGAKU_SAVED_UNKNOWN = "?"
MIGAKU_ASK_BODY = ("{file} · saved {time}\n"
                   "Known words: {now:,} → {after:,}.{kept}\n"
                   "Words from Anki, Jiten or earlier imports that Migaku doesn't have are removed. Your current "
                   "list is backed up first.")
# A replace's kept lines (one, many), each said only when it keeps any (W3.4-1: every replace keeps the dismissed words)
KEPT_GRADUATED = ("{n:,} word from past Graduates kept", "{n:,} words from past Graduates kept")
KEPT_IGNORED = ("{n:,} ignored word kept", "{n:,} ignored words kept")
MIGAKU_ASK_YES = "Replace known words"
MIGAKU_ASK_YES_TIP = "Replace your known words with Migaku's: the current list is kept as a dated backup"
MIGAKU_DONE = "Known words replaced with Migaku's · the old list is backed up in the trash folder"

# Jiten
JITEN_NAME = "Known words from Jiten"
JITEN_KEY_NAME = "Your Jiten API key"
JITEN_KEY_HINT = "Paste your Jiten API key"
JITEN_GET_KEY = "Get a key ↗"
JITEN_GET_KEY_TIP = ("Open jiten.moe's API settings in your browser\n"
                     "• Copy your API key there, then paste it here")
JITEN_SHOW = "Show"
JITEN_SHOW_TIP = "Show the key as you type it (it's never saved)"
JITEN_IMPORT = "Import"
JITEN_IMPORT_TIP = ("Fetch your Jiten words first, then decide\n"
                    "• Nothing changes until you confirm")
JITEN_CREDIT = "Credit to mattias"
JITEN_CREDIT_TIP = "Open mattias's GitHub page in your browser"
JITEN_NO_KEY = "Paste your API key first"
JITEN_JAPANESE_ONLY = "Jiten holds Japanese words only: switch to Japanese to import"
JITEN_FETCHING = "Fetching your Jiten words…"
JITEN_ASK_TITLE = "Replace your known words with Jiten's?"
JITEN_ASK_BODY = ("Known words: {now:,} → {after:,}.{kept}\n"
                  "Words from Anki, Migaku or earlier imports that Jiten doesn't have are removed. Your current list "
                  "is backed up first.")
JITEN_ASK_YES = "Replace known words"
JITEN_ASK_YES_TIP = "Replace your known words with Jiten's: the current list is kept as a dated backup"
JITEN_EMPTY = "Jiten returned no words: nothing to import"
JITEN_DONE = "Known words replaced with Jiten's · the old list is backed up in the trash folder"
JITEN_URL = "https://jiten.moe/settings/api"
JITEN_CREDIT_URL = "https://github.com/mattias"

# Extract
EXTRACT_NAME = "Extract"
EXTRACT_FILE_NAME = "The file to extract"
EXTRACT_FILE_HINT = "An EPUB, a text or subtitle file, or an Anki deck"
EXTRACT_BROWSE = "Choose a file…"
EXTRACT_BROWSE_TIP = "Choose an EPUB, a text or subtitle file, or an Anki deck (.apkg)"
EXTRACT_PICK_TITLE = "Choose a file to extract"
EXTRACT_PICK_FILTER = ("Supported files (*.epub *.txt *.md *.srt *.ass *.ssa *.apkg);;Anki decks (*.apkg);;"
                       "EPUB files (*.epub);;Text files (*.txt *.md);;Subtitle files (*.srt *.ass *.ssa);;"
                       "All files (*.*)")
EXTRACT_OUT_NAME = "The new folder's name"
EXTRACT_OUT_HINT = "Name of the new folder"
EXTRACT_BY_LENGTH = "By length"
EXTRACT_BY_LENGTH_TIP = "Parts of about this many characters, each ended at a sentence's end"
EXTRACT_BY_PATTERN = "By pattern"
EXTRACT_BY_PATTERN_TIP = "A new part starts wherever this pattern (a regular expression) matches"
EXTRACT_VALUE_NAME = "The length, or the pattern"
EXTRACT_GROUP = "Group output into parts"
EXTRACT_GROUP_TIP = "Put the parts into this many folders inside the new one"
EXTRACT_PARTS_NAME = "How many folders"
EXTRACT_FIELD_NAME = "The field holding the sentences"
EXTRACT_PREVIEW_NAME = "The first notes of that field"
EXTRACT_DECK_LINE = "Only a deck of 100 % immersion content"
EXTRACT_UNDERSTAND = "I understand"
EXTRACT_UNDERSTAND_TIP = ("Only use an Anki deck if it is 100 % immersion content: otherwise your list's frequencies "
                          "go wrong\n• It's an alternative to adding subtitles or a visual novel's text")
EXTRACT_SECTION_NAME = "The section the parts go to"
EXTRACT_SECTIONS = {"now": "Current", "soon": "Soon", "goal": "Goal"}
EXTRACT_GO = "Extract"
EXTRACT_GO_TIP = "Split the file into parts and add them to the chosen section"
EXTRACT_CHECKING = "Checking the name…"
EXTRACT_BAD_NAME = "That name can't be a folder's name: try another"
EXTRACT_TAKEN = "“{name}” is taken in your library, so nothing would be replaced: “{proposal}” is filled in"
EXTRACT_FAULTS = {"length": "The length must be a whole number of at least 1",
                  "pattern": "The pattern isn't a usable regular expression",
                  "parts": "The number of folders must be a whole number of at least 1"}
EXTRACT_DONE = "Extracted {parts:,} parts into {section}: “{name}”"
EXTRACT_DONE_PROCESSED = "Extracted {parts:,} parts into Processed › {name}"
EXTRACT_PROCESSED_ONLY = ("Extracted {parts:,} parts into Processed › {name}: the library didn't take them, so "
                          "nothing was added to {section}")
EXTRACT_EMPTY = "No text was found in it: nothing was saved"

# --- W3.4 row 3: the Anki window (app/qt/anki_window.py; its rules in app/anki_window.py) ---------------------------
ANKI_NAME = "Anki known words"
ANKI_DOOR = "Anki known words"
ANKI_DOOR_TIP = "Read your known words from the cards you've studied in Anki: decks, fields, Sync now and Replace"
ANKI_LANGUAGES = {"ja": "Japanese", "zh": "Chinese"}
ANKI_HEADING_TIP = ("Sync adds the words from {language} cards you've studied to your known words: new cards are left "
                    "alone, and nothing is removed\n• Replace rebuilds your known words from Anki instead (your list "
                    "is backed up first)")
ANKI_STATE_UNCHECKED = "● not checked yet"
ANKI_STATE_CHECKING = "● checking…"
ANKI_STATE_CONNECTED = "● connected"
ANKI_STATE_CLOSED = "● not connected"
ANKI_STATE_NAME = "Anki's state"
ANKI_STATE_TIP = "Anki is running."
ANKI_STATE_TIP_VERSION = "Anki is running (AnkiConnect {version})."
ANKI_CLOSED_LINE = "Anki isn't running. Start it with your profile open, then press ⟳."
ANKI_RECHECK = "⟳"
ANKI_RECHECK_NAME = "Check again"
ANKI_RECHECK_TIP = "Check again: whether Anki is running with AnkiConnect, and its list of decks"
ANKI_BACKFILL = "Backfill cards…"
ANKI_BACKFILL_TIP = "Fill fields on your cards from Surasura"
ANKI_DECKS = "Decks"
ANKI_DECKS_TIP = "Words are read from these decks (and their subdecks)\n• ✕ or Delete removes one"
ANKI_NO_DECKS = "No decks chosen yet — add one below."
ANKI_STUDIED = "{n:,} studied"
ANKI_REMOVE = "✕"
ANKI_REMOVE_NAME = "Remove {deck}"
ANKI_REMOVE_TIP = "Remove {deck}: its cards are no longer read (words already known stay known)"
ANKI_ADD = "Add a deck…"
ANKI_ADD_NONE = "No other decks"
ANKI_ADD_TIP = "Add another deck to read known words from"
ANKI_FIELD = "Word field"
ANKI_FIELD_AUTO = "Auto — first field"
ANKI_FIELD_TIP = ("The field that holds the word. Auto uses each note type's first field — where Anki Miner and most "
                  "decks keep it")
ANKI_ALSO = "Also read"
ANKI_ALSO_NONE = "—"
ANKI_ALSO_TIP = ("Optionally read a second field too. Pick a word field first — a sentence field marks every word in "
                 "the sentence as known")
ANKI_RESOLVED = "{model} → {fields}"
ANKI_RESOLVED_JOIN = "   ·   "
ANKI_FIELDS_JOIN = " + "
ANKI_SKIPPED = "{model} → (no such field — skipped)"
ANKI_SUSPENDED = "Include suspended cards"
ANKI_SUSPENDED_TIP = ("Count cards you've suspended as known. Off by default — suspended cards are often ones you "
                      "struggled with")
ANKI_AUTO = "Sync automatically when Anki is running"
ANKI_AUTO_TIP = "When Anki is open, Surasura adds new known words on its own — at start-up and when you come back to it"
ANKI_GENERATE = "Generate when Anki adds known words"
ANKI_GENERATE_TIP = ("When a sync brings in words you now know, Generate runs on its own in the background, so your "
                     "list is current. At most every 10 minutes, never beside another Generate or an import")
ANKI_KNOWN = "known words"
ANKI_KNOWN_TIP = "Every word Surasura counts as known, from all your sources"
ANKI_TOTAL_NAME = "Known words"
ANKI_DELTA = "+{n:,}"
ANKI_BACKLOG = {1: "{n:,} new card in your backlog", 0: "{n:,} new cards in your backlog"}
ANKI_BACKLOG_TIP = ("The new cards waiting to be learned in these decks, read with each sync. Junban (順) can put them in "
                    "your journey's order")
ANKI_AGO = {"now": "just now", "min": "{n} min ago", "h": "{n} h ago", "days": "{n} days ago", "day": "1 day ago"}
ANKI_LAST = "Last synced {ago} · +{n:,} words"
ANKI_PICKED = "Picked the decks you've studied cards in — remove any that aren't vocabulary, then press Sync now."
ANKI_APKG = "Import an .apkg instead…"
ANKI_APKG_TIP = "Offline: read an exported deck file instead. That imports every note in the file, studied or not"
ANKI_RESTORE = "Restore previous…"
ANKI_RESTORE_TIP = ("Put back the known-words list saved before your last Replace or Restore\n• Asks first, with both "
                    "totals")
ANKI_REPLACE = "Replace with Anki…"
ANKI_REPLACE_TIP = "Rebuild your known words from Anki only. Your current list is backed up first\n• Asks first, with the numbers"
ANKI_SYNC = "Sync now"
ANKI_SYNC_TIP = "Add the words from newly studied cards\n• Shift-click: re-read every card instead of just the new ones"
ANKI_SYNCING = "Syncing…"
ANKI_REREADING = "Re-reading every card…"
ANKI_READING = "Reading Anki…"
ANKI_REPLACING = "Replacing…"
ANKI_RESTORING = "Restoring…"
ANKI_READING_BACKUP = "Reading your previous list…"
ANKI_SCOPE_FAILED = "Couldn't read your decks from Anki: {error}"
ANKI_UPDATE_WAITS = "An update is waiting to install, so Anki isn't read now: try again once it's installed or cancelled."
ANKI_SYNCED = "Synced just now · +{added:,} words · {scanned:,} cards checked"
ANKI_REPLACED = "Replaced: {total:,} known words now — {added:,} from Anki"
ANKI_REPLACED_GRADUATED = " · {graduated:,} from past Graduates"
ANKI_REPLACED_IGNORED = {1: " · 1 ignored word kept", 0: " · {ignored:,} ignored words kept"}
ANKI_RESTORED = "Restored your previous known words: {total:,} known"
ANKI_NOTHING_TO_RESTORE = "There is no previous list to restore."
ANKI_JOB_SYNC = "Syncing known words from Anki"
ANKI_JOB_DRY = "Reading Anki for Replace"
ANKI_JOB_REPLACE = "Replacing your known words with Anki's"
ANKI_JOB_RESTORE = "Restoring your previous known words"
ANKI_REPLACE_TITLE = "Replace your known words with Anki's?"
ANKI_REPLACE_AGAIN_TITLE = "Anki changed since you looked: replace with these numbers?"
# The Replace confirmation's body, a line each; a "kept" line only when something is kept (IK-44, Sonic's W3.4-1).
ANKI_REPLACE_HEAD = "Known words: {now:,} → {after:,}"
ANKI_REPLACE_ANKI = "• {n:,} from Anki"
ANKI_REPLACE_GRADUATED = {1: "• 1 word from past Graduates kept", 0: "• {n:,} words from past Graduates kept"}
ANKI_REPLACE_IGNORED = {1: "• 1 ignored word kept", 0: "• {n:,} ignored words kept"}
ANKI_REPLACE_TAIL = ("Known words from Migaku, Jiten or other imports that Anki doesn't have are removed. Your current "
                     "list is backed up first; Restore previous puts it back.")
ANKI_REPLACE_YES = "Replace"
ANKI_REPLACE_YES_TIP = ("Go ahead. Your current list is backed up first, as a dated copy (KnownWord.<date>.json) in "
                        "your known words' .trash folder")
ANKI_WAITING_FOR = "Waiting its turn: {what} runs first"
ANKI_WAITING = "Waiting to start: {reason}"
ANKI_REPLACE_MOVED_JOB = "Nothing replaced: Anki changed"
ANKI_RESTORE_MOVED_JOB = "Nothing restored: your known words changed"
ANKI_REPLACE_MOVED_CLOSED = ("Nothing replaced: Anki changed after you said yes. Open Anki known words to see the new "
                             "numbers.")
ANKI_RESTORE_MOVED_CLOSED = "Nothing restored: your previous known words changed after you said yes."
ANKI_KEEP_TIP = "Stop here. Your known words are not changed (Esc and Enter do the same)"
ANKI_RESTORE_TITLE = "Put back your known words from {when}?"
ANKI_RESTORE_TITLE_UNDATED = "Put back your previous known words?"
ANKI_WHEN = "%d %b %Y, %H:%M"
ANKI_RESTORE_BODY = "Known words: {now:,} → {then:,}\nYour current list is backed up first, so this can be undone too."
ANKI_RESTORE_BODY_UNREAD = ("Known words now: {now:,}. The previous list couldn't be counted.\nYour current list is "
                            "backed up first, so this can be undone too.")
ANKI_RESTORE_YES = "Restore"
ANKI_RESTORE_YES_TIP = "Put it back. Your current list is backed up first"
ANKI_RESTORE_CHANGED = "Your known words changed since you asked; here are the numbers now."
# --- W3.4 row 4: Koe and YouTube — their doors on the Settings tab's list (the windows' own words are each module's
# qt_strings.py)
DOOR_TRANSCRIPTS = "Video transcripts"
DOOR_TRANSCRIPTS_TIP = "Download YouTube and bilibili.tv transcripts into your Processed folder"
DOOR_PREVIEW = "Preview a video"
DOOR_PREVIEW_TIP = "See a video's vocab journey against your library before adding it"
DOOR_SPEECH = "Speech"
DOOR_SPEECH_TIP = "Speech (声): the Gemini key, the voice and the daily limit for spoken sentences"

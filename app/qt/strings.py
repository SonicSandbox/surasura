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
JOURNEY = "Your journey ↗"
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
BAR_ANKIWEB_TIP = "Surasura's own syncs of Anki with AnkiWeb: when the last one ran, or when the next one starts"
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
APKG_EVERY_NOTE = "Imports every note in the file. To import only studied cards, use Sync from Anki."
APKG_IMPORT = "Import"
APKG_IMPORT_TIP = ("Add every word in the chosen field to your known words. Existing entries are kept, and words you "
                   "have ignored stay ignored.")
APKG_READING = "Reading the deck…"
APKG_READ = "{notes:,} notes · {fields} fields"
APKG_NOT_A_DECK = "Choose an .apkg file: an Anki deck you exported"
APKG_ASK_TITLE = "Add these words to your known words?"
APKG_ASK_BODY = ("Every word in the “{field}” field of all {notes:,} notes becomes a known word, studied or not. "
                 "Words you know stay as they are; ignored words stay ignored. Your list is backed up first.")
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
MIGAKU_ASK_TITLE = "Replace your known words with Migaku's?"
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

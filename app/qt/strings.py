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
# --- W3.2 Q4: Finished's actions (app/qt/finished.py): Put back, ⋯, *What if I added it back?*, the importer -------- #
FIN_PUT_BACK = "Put back"
FIN_PUT_BACK_TIP = ("Put back: to the top of Current, its cards back in your order\n"
                    "• Click to put it back (Undo takes it back to Finished)")
FIN_MORE_TIP = "More\n• Click for what you can do with it (Enter on the keyboard)"
FIN_MENU_NAME = "What you can do with {title}"
FIN_MENU = {
    "what-if": ("What if I added it back?", "How many new words it would bring at the top of Current — nothing moves"),
    "put-back": ("Put back", "To the top of Current, its cards back in your order"),
    "pin": ("Study its cards first", "Its cards come first in your Anki order"),
    "unpin": ("Done with its cards", "Its cards go back to their place in your order"),
    "cards": ("Its {n} cards in Anki", "What happens to its new cards"),
    "cards-none": ("Its cards in Anki", "What happens to its new cards"),
    # P4.1 L2 (TF fix 10, IK #6; W1.2: "unstudied cards suspended and tagged, never deleted"): what Anki sees
    "cards-out": ("Leave its new cards out of your order",
                  "Its new cards leave your order: suspended in Anki and tagged, never deleted. Put back brings them "
                  "back"),
    "cards-in": ("Put them back in the order", "Its new cards come back into your order, unsuspended in Anki"),
    "mine": ("Mine", "Make its cards"),
    "mine-too": ("Mine it too", "Make cards for what isn't mined yet"),
    "folder": ("Open its folder", "Open the folder its files are in"),
}
FIN_REFUSED_TIP = "Your library can't be saved right now: {reason}"
FIN_PUT_BACK_DONE = "{title} is back at the top of Current"
FIN_PINNED = "{title}: its cards come first"
FIN_UNPINNED = "{title}: done with its cards"
FIN_CARDS_OUT = "{title}: its new cards are out of your order"
FIN_CARDS_IN = "{title}: its new cards are back in your order"
FIN_NO_FOLDER = "{title}'s folder isn't there any more"
WHATIF_NAME = "What if you added {title} back"
WHATIF_HEADING = "WHAT IF I ADDED IT BACK?"
WHATIF_LINE = "At the top of Current it would bring {n} new words · {pct} known"
WHATIF_DASH = "—"
WHATIF_PCT = "{pct} %"
WHATIF_WORDS = "The first new words you'd meet: {words}"
WHATIF_NO_WORDS = "No new words in it: you know every word of it on your list"
WHATIF_NO_PLAN = "Generate once and it can count the new words too"
WHATIF_NONE = "Can't count it right now"
WHATIF_PUT_BACK_TIP = "Put back: to the top of Current, its cards back in your order"
WHATIF_JOURNEY = "Open your journey"
WHATIF_JOURNEY_TIP = "Open your journey: your list with its sentences, in its own window"
WHATIF_CLOSE_TIP = "Close: nothing moves (Esc)"
WHATIF_CLOSE_NAME = "Close"
FIN_IMPORT = "Add what you finished before…"
FIN_IMPORT_TIP = ("Add what you finished before Surasura: copied into Finished, dated Earlier\n"
                  "• Its words don't move your list; its sentences can be your examples")
FIN_IMPORT_FILES = ("Files…", "Choose subtitle or text files you finished")
FIN_IMPORT_FOLDER = ("A folder…", "Choose a folder of what you finished (it keeps its name)")
FIN_IMPORT_PICK = "Add what you finished before"
FIN_IMPORT_STOP = "Stop adding"
FIN_IMPORT_STOP_TIP = "Stop adding: what was copied so far goes to the trash, nothing is added"
FIN_IMPORTED = "Added {n} to Finished"
FIN_IMPORTED_ONE = "Added {name} to Finished"
FIN_IMPORT_NOTHING = "Nothing new to add: it's in Finished already"
FIN_IMPORT_STOPPED = "Stopped: nothing was added"
FIN_IMPORT_LATER = "Still saving what you finished before: it's added once the library can be saved"
FIN_IMPORT_FAILED = "Couldn't add it to Finished: {why}"
FIN_IMPORT_IN_LIBRARY = "{name} is in your library already: finish it from its row, with the choice for its cards"
FIN_IMPORT_IN_LIBRARY_N = "{n} of these are in your library already: finish them from their rows"
# --- end W3.2 Q4
# --- W3.2 Q8: the rest of Current's ⋯ (app/qt/item_menu.py), the ✂ seam and drop-to-join -------------------------- #
ITEM_MENU = {
    "pin": ("Study its cards first", "Its cards come first in your Anki order"),
    "unpin": ("Done with its cards", "Its cards go back to their place in your order"),
    "type": ("What is it?", "Say what it is: its words, its icon and how it counts follow"),
    "split": ("Split here…", "Make the episodes after this point a part of its own (one Undo joins them back)"),
    "join": ("Join with…", "Join another part of the same title to this one, in episode order"),
    "cover": ("Change cover…", "Choose the picture it shows"),
    "folder": ("Open its folder", "Open the folder its files are in"),
    "remove": ("Remove…", "Take it out of your library: its files go to the trash for 30 days (asks first)"),
    # LM11b G4: on what Ctrl+click picked ({n}: the rows and episodes picked)
    "group": ("Group…", "Put these {n} into one row in Current\n• Undo takes them apart again"),
    # LM11b G3: on a group's ⋯ (IK-5), and *Same show as…* on a show's own row (IK-6)
    "rename": ("Rename…", "Give this group a name of its own (left empty, it is named after its shows again)"),
    "ungroup": ("Ungroup", "Put each show back in a row of its own, where it is: nothing is lost\n"
                           "• Undo groups them again"),
    "same-show": ("Same show as…", "Make this part of another show: it and its new episodes go into that show "
                                   "(asks first)"),
}
# a submenu longer than a page (`item_menu.MENU_PAGE`) goes on in a submenu of its own, page by page
MENU_MORE = ("More…", "The rest of this list")
# row 28: an opened row's episode's own ⋯ ({ep}: the episode as ⋯ names it; {action}: its stone's click,
# `ROWS_STONE_ACTION`) — its *Play* is ▶'s own verb and tip
ITEM_EP_MARK = ("Mark {action}", "Mark {ep} {action}\n• Undo takes it back")
ITEM_EP_MENU_NAME = "What you can do with {ep}"
ITEM_UNGROUPED = "Ungrouped {title}"
ITEM_RENAME_ASK = "Rename this group"
ITEM_RENAME_BODY = "Leave it empty to name it after its shows again."
ITEM_RENAME_YES = "Rename"
ITEM_RENAME_YES_TIP = "Give the group this name"
ITEM_RENAMED = "Renamed {title} to {name}"
ITEM_RENAME_CLEARED = "{title} is named after its shows again"
ITEM_SAME_SHOW_PICK = "{title} · {where}"
ITEM_SAME_SHOW_PICK_TIP = "Make this part of {title} (asks first)"
# the confirm's words as Sonic approved them (GW-1, 2026-10-21): {b} this row's show, {a} the one picked
ITEM_SAME_SHOW_ASK = "Make {b} part of {a}?"
ITEM_SAME_SHOW_BODY = "New episodes of {b} will go into {a}. Undo works until you close Surasura."
ITEM_SAME_SHOW_YES = "Make one show"
ITEM_SAME_SHOW_YES_TIP = "Make {b} part of {a}: one show from now on"
ITEM_SAME_SHOW_DONE = "{b} is now part of {a}"
ITEM_GROUPED = "Grouped {n} into one row"
ITEM_TYPES = {"anime": "Anime", "drama": "Drama", "movie": "Movie", "youtube": "YouTube", "podcast": "Podcast",
              "audiobook": "Audiobook", "book": "Book", "lightnovel": "Light novel", "manga": "Manga", "game": "Game",
              "text": "Text"}
ITEM_TYPE_TIP = "It's a {kind}"
ITEM_TYPE_GUESS = ("Let Surasura tell", "Surasura works it out from its files again")
ITEM_TYPE_DONE = "{title} is now {kind}"
ITEM_TYPE_GUESSED = "Surasura tells what {title} is again"
ITEM_SPLIT_AFTER = "After {ep}"
ITEM_SPLIT_AFTER_TIP = "Split it after {ep}: {rest} becomes a part of its own"
ITEM_SPLIT_HERE = "Split here (after {ep})"
ITEM_SPLIT_DONE = "Split {title}: {rest} is a part of its own"
ITEM_JOIN_PART = "{range} · {where}"
ITEM_JOIN_PART_TIP = "Join {range} to this part, in episode order"
ITEM_JOIN_WHERE = {"now": "#{n} in Current", "soon": "#{n} in Current (Soon)", "goal": "in Goal",
                   "graduated": "in Finished", "arrivals": "in New arrivals"}
ITEM_JOINED = "Joined {range}"
ITEM_RANGE = "Ep {a}–{b}"
ITEM_RANGE_ONE = "Ep {a}"
ITEM_RANGE_FILES = "{n} files"
ITEM_PINNED = "{title}: its cards come first"
ITEM_UNPINNED = "{title}: done with its cards"
ITEM_REMOVE_ASK = "Remove {title}?"
ITEM_REMOVE_BODY = "Its {n} files go to the trash for 30 days. Undo puts them back where they were."
ITEM_REMOVE_BODY_ONE = "Its file goes to the trash for 30 days. Undo puts it back where it was."
ITEM_REMOVE_YES = "Remove {n} files"
ITEM_REMOVE_YES_ONE = "Remove 1 file"
ITEM_REMOVE_YES_TIP = "Take it out of your library: its files go to the trash for 30 days"
ITEM_REMOVED = "Removed {title}"
SEAM_LABEL = "✂ Split here"
SEAM_TIP = "✂ Split here\n• Click to make {rest} a part of its own"
JOIN_LABEL = "Drop to join"
# LM11b G2: another show dropped on a show once the hand rests on it (`item_menu.JOIN_REST_MS`): one row of both
JOIN_GROUP_LABEL = "Drop to group"
ITEM_GROUPED_WITH = "Grouped {other} with {title}"
# --- end W3.2 Q8
# K6: ⋯ › *Never read this folder* › the item's folder and each one above it inside its source folder
ITEM_SKIP = ("Never read this folder", "Leave a folder out of your library for good: pick it")
ITEM_SKIP_TIP = ("Never read {path}\nEverything of it leaves your library (to the trash for 30 days; Undo brings it "
                 "back); nothing in the folder is changed")
ITEM_SKIPPED = "{name} won't be read again"
NEEDS_HEADING = "Needs you"
NEEDS_EMPTY = ("Nothing needs you", "When something waits on you, it shows here")
TAB_COUNT = "{name}  {count}"                   # Finished's records, Needs you's unseen entries
GOAL_NAME = "Goal"
LIST_NAMES = {"current": "Current", "finished": "Finished", "needs": "Needs you"}
STATE_LINES = {
    # (W3.2 P0, IK0-1: no line promises rows the window can't show — it reads no JSON copy; G1.2-18's rows from the
    # copy are a named follow-up)
    "getting-ready": "Getting your library ready… Your list shows here once it's done; until then nothing can be moved.",
    "busy": "Updating your library…",
    "read-only": "Read-only: {reason}. Nothing can be moved until it's fixed.",
    "migration-failed": "Your library couldn't be brought into 3.0's store, so it can't show here yet. "
                        "Open the logs folder (the bar) and send it in; nothing of yours was changed.",
}
READ_ONLY_REASONS = {
    "damaged": "the library needs a repair — Surasura keeps its last good copy; send the logs folder (the bar) in",
    "made by a newer Surasura": "your library was saved by a newer Surasura — update Surasura to change it",
    "busy": "another program is saving your library — it opens as soon as that's done",
}
READ_ONLY_IO = "Surasura can't read the library's file — check its drive is there, then restart Surasura"
PLAY_FAILED = "Couldn't open {name}: {why}"
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
ROWS_LOOKING_BUTTON = "Looking…"                   # R55-A: Up Next before the video check answered
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
STANDING_HIDE = "✕"                                         # round 8 row 54: every standing line's (app/qt/standing.py)
STANDING_HIDE_TIP = "Hide this until it changes"
STANDING_HIDE_NAME = "Hide"

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
                     "your own run takes its place")
GENERATE_LOG = "Open the log"
GENERATE_LOG_TIP = "Open the last Generate's log, to see what went wrong"
GENERATE_PROGRESS_NAME = "Generate's progress"
JOURNEY_TIP = "Your list with its sentences, in its own window\n• Click to open your journey"
JOURNEY_NONE_TIP = "Your journey appears after your first Generate"
JOURNEY_FAILED = "Couldn't open your journey: {why}"
# The header's button beside the level ▾ (laptop fixes: the journey never opens by itself, only from here or a link)
HEADER_JOURNEY = "Journey ↗"
HEADER_JOURNEY_NAME = "Open your journey"
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
BAR_LEVEL_AUTO_TIP = ("Your level, chosen for you: the commonest band whose list holds enough words, {band} now")
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
# --- row 35: closing while helpers go on without the window (`jobs.detached_at_quit`; the shell's sheet)
QUIT_DETACHED_TITLE = "Still finishing: {labels}"
QUIT_DETACHED_JOIN = " · "
QUIT_DETACHED_BODY = "They finish by themselves."
QUIT_DETACHED_CONNECT = "Connect finishes the cards it's making by itself."
QUIT_DETACHED_QUIT = "Quit"
QUIT_DETACHED_QUIT_TIP = "Close Surasura now: what is still finishing goes on and ends by itself (Esc does the same)"
QUIT_DETACHED_STOP = "Stop and quit"
QUIT_DETACHED_STOP_TIP = ("End the library's upkeep now, then close. Surasura picks it up again as it closes, or at "
                          "its next start. Connect isn't stopped")
# --- end row 35

# --- W3.1a frame (app/qt/frame.py): the level ▾ and its pop, the footer's emerald and known corner, the Goal dock and
# its wells. The level's words are the old chip's (BAR_LEVEL_*); Generate's are the button's (GENERATE_*).
LEVEL_WAITING = "Level"                               # the ▾ before the level is first read
LEVEL_NAME = "Your level: {level}"
LEVEL_TIP = "{level}\n• Click to change your level, Generate, or open your journey"
LEVEL_TIP_MARK = "{level}\n{mark}\n• Click to change your level, Generate, or open your journey"
LEVEL_MARKS = {
    "failed": "⚠ The last Generate didn't finish",
    "stale": "Something changed since your last Generate: your list is out of date",
    "journey": "Your journey's sentences are catching up",
}
LEVEL_POP_NAME = "Your level, Generate and your journey"
# W3.1b: the Level menu (the brief's pop: only words, %, how often, the slider, Automatic)
LEVEL_POP_HEADING = "Level"
LEVEL_POP_HELP = "?"
LEVEL_POP_HELP_NAME = "What the level is"
LEVEL_POP_HELP_TIP = ("How rare a word can be and still make your list.\nRaise it: more words join your list. "
                      "Lower it: nothing is deleted.\n• Click for the level's settings")
LEVEL_POP_AUTO_WORD = "Automatic"
LEVEL_POP_AUTO_TIP = ("Surasura picks the level for you and moves it as you learn: the commonest one whose list "
                      "holds enough words\n• Click to turn it on or off")
LEVEL_POP_SLIDER_NAME = "Your level"
LEVEL_POP_SLIDER_TIP = ("Your level: common on the left, rare on the right\n• Drag the gem or click a chamber; "
                        "picking one turns Automatic off")
LEVEL_POP_READ_HOURS = "≈{words} words · {coverage}% · every {hours} h"
LEVEL_POP_READ_MINUTES = "≈{words} words · {coverage}% · every {minutes} min"
LEVEL_POP_READ_NO_TIME = "≈{words} words · {coverage}%"
LEVEL_POP_AUTO_WAITING = "Automatic picks your level after your first Generate"
LEVEL_POP_COVERAGE = "Your list follows its coverage target: {n}%"
LEVEL_POP_COVERAGE_TIP = ("The level does nothing while your list is set by coverage\n• Change it in Settings › Level "
                          "(the gear)")
LEVEL_POP_GEAR_NAME = "Level settings"
LEVEL_POP_GEAR_TIP = "Level settings\n• Click to open them in Settings"
LEVEL_JOURNEY = "Open your journey ↗"
FOOT_ANKI = "Anki"
FOOT_ANKI_NAME = "Anki: {words}"
FOOT_ANKI_TIP = "{words}\n{tip}"
FOOT_ANKI_ANKIWEB = "{tip}\n\n{ankiweb}"
FOOT_KNOWN = "known"
FOOT_KNOWN_TIP = "{tip}\n{left:,} to {next:,}\n{click}"
FOOT_KNOWN_NAME = "Known words"                              # the count's button before a count is read
FOOT_KNOWN_NONE_TIP = "{name}: not counted yet\n{click}"
FOOT_KNOWN_CLICK = "Click to sync now"                       # Q30: the count's click, through the one sync path
FOOT_KNOWN_CLICK_ANKI = "Click to open the Anki window: choose your decks there"     # no decks yet (IK-7)
FOOT_KNOWN_SYNCING = "Syncing with Anki now…"
# A click's sync refused (AD-6): AutoSync's own answer, said in the bar ("no-decks" / "never-synced" open the Anki window)
FOOT_KNOWN_REFUSED = {"update-staged": "Not synced: an update is waiting to install, and Anki waits for it",
                      "running": "A sync with Anki is running already",
                      "off": "Not synced: Anki is switched off for this run",
                      "failed": "Not synced: the sync with Anki couldn't be started (the log says why)"}
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
ROWS_EP_MORE_TIP = "More: this episode\n• Click for what you can do with it"
ROWS_MOVE_TIP = {"up": "Move up one\n• Click to move it up one place",
                 "down": "Move down one\n• Click to move it down one place"}
# a click that asks for more than one file says how many (AD-2: Up Next's status acts on its whole row, as every row's
# does), one string with the count as the toasts' (`MAKE_CARDS_QUEUED`): {one file?: words}
ROWS_WAITING_TIP = "{label}\n{tip}"                  # row 38: *Waiting* is its icon alone; its hover names it first
ROWS_MINE_NOW_TIP = {True: "{tip}\n• Click to mine it now", False: "{tip}\n• Click to mine its {n} waiting files now"}
# --- P4.1 L2: the stones' actions (4.1.11): Mine this, No video's Link… · Mine text, and why nothing happens while
# Connect is off (IK S7); the window's routing (`app/qt/mine_actions.py`)
ROWS_MINE_THIS_TIP = {True: "{tip}\n• Click to mine it now", False: "{tip}\n• Click to mine its {n} files now"}
ROWS_NO_MEDIA_TIP = "{tip}\n• Click to link its video, or to mine its text in Anki Miner"
ROWS_ACTION_OFF = "{tip}\n{why}"
ROWS_ACTION_KEY = "→ then Enter: {action}"
ROWS_ACTION_NAMES = {"mine-now": "Mine now", "mine-this": "Mine this", "no-media": "Link… or Mine text"}
# round 8 row 45 (trial): *Mine now* pressed — its pill turns from the frame of the press until Connect says more; its
# hover is the one place words show (Sonic: "there are sometimes when text may be useful but be intentional")
ROWS_ASKED_TIP = "Asked · starting…"
ROWS_LINK = "Link…"
ROWS_LINK_TIP = "Choose its video: its cards get their pictures and audio from it"
ROWS_MINE_TEXT = "Mine text"
ROWS_MINE_TEXT_TIP = "Open Anki Miner to mine its text by hand: its file's path is copied for you"
MINE_ASKED = "{title}: its cards come next"
# LM11b G5 (K67): a group of videos and other files — only its videos asked
MINE_ASKED_VIDEOS = "{title}: its videos' cards come next · Anki Miner mines video only, so its other files are left out"
MINE_ASKED_N = "{n} files: their cards come next"
# LM11b fix round: New arrivals' *Mine them too* with videos and other files — only the videos asked (`videos_of`)
MINE_ASKED_N_VIDEOS = {True: "1 video: its cards come next · Anki Miner mines video only, so the other files are left out",
                       False: "{n} videos: their cards come next · Anki Miner mines video only, so the other files are "
                              "left out"}
# --- P4.1 WF (the reviews' word fixes, IK S5): one file said as one; a book's button opens Anki Miner (never "mine it
# now"); C6's toast says Connect waits while Anki Miner's window is open (the N1 disposition); a bulk ask with nothing
# left to ask for; a gap's *Make their cards* as Connect's ordinary work (D-1 lean (a)), counted, no title pasted
MINE_ASKED_ONE = "1 file: its cards come next"
MINE_NOTHING = "Nothing to ask for: their cards are in Anki already, being made, or were deleted"
ROWS_MINE_TEXT_THIS_TIP = "{tip}\n• Click to mine its text by hand in Anki Miner"
MAKE_CARDS_QUEUED = {True: "1 episode's cards come next", False: "{n} episodes' cards come next"}
MAKE_CARDS_NONE = "Nothing left to make: Connect has each of those episodes already"
MAKE_CARDS_GONE = "Connect has no record of those episodes now: nothing was made"
# --- end P4.1 WF
MINE_TEXT_COPIED = ("Anki Miner is opening · {name}'s path is copied: paste it there to mine its text. Connect waits "
                    "while Anki Miner's window is open")
MINE_TEXT_NO_MINER = "Anki Miner isn't installed: set it up in Settings, then Mine text"
MINE_TEXT_NOT_OPENED = "Couldn't open Anki Miner: {path}"
LINK_TITLE = "Choose the video for {label}"
LINK_FILTER = "Videos ({patterns})"
LINKING_ONE = "Linking {label}'s video"
# --- end P4.1 L2
ROWS_STONE_TIP = "{label}{state}\n• Click to mark it {action}"
ROWS_STONE_STATE = {"cut": " · watched", "raw": " · {n} cards in Anki", "rock": ""}
ROWS_STONE_MISSING = " · no {word} on disk"
ROWS_STONE_ACTION = {True: "not watched", False: "watched"}
ROWS_STONE_LEAVES = "\nWatched: its words leave your list."    # W-1: while *Keep studying watched episodes* is off
ROWS_DONE = "Done"
ROWS_DONE_TIP = "Mark {ep} watched\n• Click: the one after it comes up next"
ROWS_DONE_ALL_TIP = "Every file of it is watched\n• Click to move it to Finished"
ROWS_DONE_ALL_MIX_TIP = "Every file of it is watched"         # hato's mix never finishes (G3.2)
ROWS_HERO_KNOWN = "{pct}% known · "
ROWS_HERO_NEW_LINK = "{n} new words ↗"
ROWS_JOURNEY_TIP = "Your journey: your list with its sentences\n• Click to open it in its own window"
ROWS_TOP_LINE_WHERE = "{tip}\n• Click to change it: Settings → Anki & mining"     # P4.1 L2 (row 4.1.14)
ROWS_SOON_LINE_WHERE = "{tip}\nWhere Soon starts is a setting: Settings → Content"
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
    "already_in": "Already in your library: {titles}",   # SRC K3: a drop whose bytes are an item's
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
YT_OTHER_LIBRARY = "the language changed while they downloaded: the transcripts wait in the other library's Processed"
YT_NOT_ADDED = "{what} couldn't be added (gone, or not in your library folder)"


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
DRAG_TAKE_OUT = "Leave its new cards out of your order"      # IK-1: Finished's ⋯ words, one name for one action
DRAG_TAKE_OUT_TIP = ("Its new cards leave your order: suspended in Anki and tagged, never deleted. Undo or Put back "
                     "brings them back")         # P4.1 L2 (TF fix 10, IK #6)
DRAG_TAKEN_OUT = "{title}: its new cards are out of your order"
DRAG_ADDED = "Added {name} at #{n} · analysed on the next Generate"
DRAG_ADDED_N = "Added {count} files at #{n} · analysed on the next Generate"
DRAG_GONE = "That item was removed"
DRAG_REFUSED = "Your library can't be saved right now: {reason}"
# W3.2 P0: a language switch, and a library that couldn't be opened
SWITCHING = "Switching to {name}… Nothing can be moved until its library is open"
MOVE_NOT_SAVED = "That change wasn't saved: try it again"
LIBRARY_NOT_OPENED = "Your library couldn't be opened. Open the logs folder (the bar) and send it in"
DONE_NEXT = "✓ {title} {ep} watched · next: {next}"
DONE_ONE = "✓ {title} {ep} watched"
DONE_UNDONE = "{title} {ep} marked not watched"
# --- W-1 (Sonic 2026-10-22, Q4): while *Keep studying watched episodes* is off — the first mark (once per library), the
# un-mark
DONE_LEFT = "✓ {ep} watched — its words left your list."
DONE_KEEP = "Keep studying them"
DONE_KEEP_TIP = "Opens Settings at Keep studying watched episodes"
DONE_OK = "OK"
DONE_OK_TIP = "Leave them off your list"
DONE_UNDONE_BACK = "{ep} not watched — its words are back."
# --- end W-1
DONE_ALL = "✓ All {n} watched — finished with it?"
DONE_MOVE_FINISHED = "Move to Finished"
DONE_MOVE_FINISHED_TIP = "Move it to Finished: a record of what you've worked through"
# --- LM11b G5: one show of a group all watched, the group's other shows not yet (GW-2 ⭐ A)
DONE_SHOW_IN_GROUP = "✓ {show}: all {n} watched — finished with it?"
DONE_MOVE_SHOW_FINISHED = "Move {show} to Finished"
DONE_MOVE_SHOW_FINISHED_TIP = "Move {show}'s {n} files to Finished, under its own name\n• The group keeps the rest"
# --- end LM11b G5
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
# --- W3.2 Q1: New arrivals — the header's inset and its tray (app/qt/arrivals.py) ---------------------------------- #
ARRIVALS = "New arrivals"
ARRIVALS_NAME = "New arrivals · {n} files"
ARRIVALS_NAME_ONE = "New arrivals · 1 file"
ARRIVALS_TIP = "New arrivals: {n} files waiting for a place\n• Open the tray to put them where you want them"
ARRIVALS_TIP_ONE = "New arrivals: 1 file waiting for a place\n• Open the tray to put it where you want it"
TRAY_NAME = "New arrivals: what came in, newest first"
TRAY_CLOSE = "✕"
TRAY_CLOSE_NAME = "Close"
TRAY_CLOSE_TIP = "Close the tray (Esc, Back or a click outside close it too)"
TRAY_ALL_FINISHED = "✓ All to Finished"
TRAY_ALL_FINISHED_TIP = "Record every already-watched arrival as finished\n• Then choose whether their new cards stay"
TRAY_ALL_TITLES = "{n} watched titles"
TRAY_MINE_TOO = "Mine them too"
TRAY_MINE_TOO_TIP = "Make cards from the already-watched arrivals as well"
TRAY_ICON = {
    "top": ("Top", "Top · Add to the top of Current, the next thing you watch or read"),
    "finished": ("Finished", "Finished · Record it as finished: you've watched it already\n• Then choose whether its "
                             "new cards stay"),
}
TRAY_MORE_NAME = "More"
TRAY_MORE_TIP = "More · Place it elsewhere, open its folder, or remove it"
TRAY_MENU_NAME = "Where {title} goes"
TRAY_NO_SHOW = "None of its show is in Current: Top of Current puts it there"                 # W3.2 fix round (N1)
TRAY_MENU = {
    "top": ("Top of Current", "The top of Current: the next thing you watch or read"),
    "after-show": ("After its show", "Right after the episodes of its show already in Current"),
    "soon": ("Soon", "Soon: next in line in Current, after what's at its top"),
    "goal": ("Goal", "Goal: someday, in no order"),
    "finished": ("Finished", "Record it as finished: you've watched it already"),
    "folder": ("Open its folder", "Show its files in Explorer"),
    "remove": ("Remove…", "Send its files to the trash (kept 30 days; Undo puts them back). Asks first"),
}
TRAY_PLACED = {
    "top": "{title} is at the top of Current",
    "after-show": "{title} placed after its show",
    "soon": "{title} → Soon",
    "goal": "{title} moved to Goal",
}
TRAY_REMOVE_TITLE = "Remove {title}?"
TRAY_REMOVE_BODY = "Its {n} files go to the trash, kept there for 30 days. Undo puts them back."
TRAY_REMOVE_BODY_ONE = "Its file goes to the trash, kept there for 30 days. Undo puts it back."
TRAY_REMOVE_YES = "Remove {n} files"
TRAY_REMOVE_YES_ONE = "Remove 1 file"
TRAY_REMOVE_YES_TIP = "Send them to the trash. Undo on the next message puts them back"
TRAY_REMOVED = "{title} removed · in the trash for 30 days"
TRAY_NO_FOLDER = "Couldn't open its folder: {path}"
TRAY_NUMBER_NONE = "—"
TRAY_NUMBER_UNIT = "new / {unit}"
# --- end W3.2 Q1
# --- W3.2 Q2: Goal's sheet (goal_sheet.py) ------------------------------------------------------------------------ #
GOAL_SHEET_NAME = "Goal: everything you'll get to someday"
GOAL_SHEET_TIP = "Goal: someday, in no order. Drag a title into Current, or use its ⋯"
GOAL_SHEET_CLOSE = "✕"
GOAL_SHEET_CLOSE_NAME = "Close Goal"
GOAL_SHEET_CLOSE_TIP = "Close Goal (Esc, or click anywhere outside it)"
GOAL_TILE_MORE = "⋯"
GOAL_TILE_MORE_NAME = "What you can do with {title}"
GOAL_TILE_MORE_TIP = "What you can do with {title}: move it, open its folder or remove it (Enter)"
GOAL_MENU_ITEMS = {
    "top": ("Move to the top", "Bring {first} up to the top of Current; the rest stays in Goal"),
    "top-all": ("Move to the top", "Bring it up to the top of Current"),
    "soon": ("Move to Soon", "Bring {first} up to the top of Soon; the rest stays in Goal"),
    "soon-all": ("Move to Soon", "Bring it up to the top of Soon"),
    "finished": ("Move to Finished", "Move all of it to Finished: you're done with it"),
    "folder": ("Open its folder", "Show its files in File Explorer"),
    "remove": ("Remove…", "Send its {n} files to the trash (kept 30 days). You're asked first"),
}
GOAL_UP = "{title} {first} moved up from Goal · #{n} · the rest stays in Goal"
GOAL_UP_ALL = "{title} moved up from Goal · #{n}"
GOAL_SOON = "{title} {first} → Soon · #{n} · the rest stays in Goal"
GOAL_SOON_ALL = "{title} → Soon · #{n}"
GOAL_REMOVE_ASK = "Remove {title}?"
GOAL_REMOVE_BODY = "Its {n} files go to the trash, kept for 30 days. Undo puts them back."
GOAL_REMOVE_BODY_ONE = "Its file goes to the trash, kept for 30 days. Undo puts it back."
GOAL_REMOVE_YES = "Remove {n} files"
GOAL_REMOVE_YES_ONE = "Remove 1 file"
GOAL_REMOVE_YES_TIP = "Send them to the trash (kept 30 days); the toast's Undo puts them back"
GOAL_REMOVED = "{title} removed · {n} files in the trash for 30 days"
GOAL_REMOVED_ONE = "{title} removed · its file is in the trash for 30 days"
GOAL_FOLDER_FAILED = "Couldn't open the folder of {title}"
# --- end W3.2 Q2

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
# A replace's lines (one, many), each said only when there are any: past Graduates' words kept; the words ignored in
# Migaku it drops (every replace is a clean slate from its source; only Migaku writes ignored words, the Ignore list
# file is never touched). IGNORED_BACK is the one wording of all three replaces: Anki's lines below are made from it.
KEPT_GRADUATED = ("{n:,} word from past Graduates kept", "{n:,} words from past Graduates kept")
IGNORED_BACK = ("{n:,} word you ignored in Migaku is no longer ignored (the backup keeps it)",
                "{n:,} words you ignored in Migaku are no longer ignored (the backup keeps them)")
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
EXTRACT_ALREADY = "Already in your library: “{title}” · the {parts:,} parts stay in Processed › {name}"   # SRC K3
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
ANKI_REPLACED_IGNORED = {1: " · " + IGNORED_BACK[0], 0: " · " + IGNORED_BACK[1]}
ANKI_RESTORED = "Restored your previous known words: {total:,} known"
ANKI_NOTHING_TO_RESTORE = "There is no previous list to restore."
ANKI_JOB_SYNC = "Syncing known words from Anki"
ANKI_JOB_DRY = "Reading Anki for Replace"
ANKI_JOB_REPLACE = "Replacing your known words with Anki's"
ANKI_JOB_RESTORE = "Restoring your previous known words"
ANKI_REPLACE_TITLE = "Replace your known words with Anki's?"
ANKI_REPLACE_AGAIN_TITLE = "Anki changed since you looked: replace with these numbers?"
# The Replace confirmation's body, a line each; the Graduates' and the ignored line only when there are any (IK-44).
ANKI_REPLACE_HEAD = "Known words: {now:,} → {after:,}"
ANKI_REPLACE_ANKI = "• {n:,} from Anki"
ANKI_REPLACE_GRADUATED = {1: "• 1 word from past Graduates kept", 0: "• {n:,} words from past Graduates kept"}
ANKI_REPLACE_IGNORED = {1: "• " + IGNORED_BACK[0], 0: "• " + IGNORED_BACK[1]}
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
# --- W3.2 Q3: search your library (app/qt/search.py) and + Add (app/qt/add_menu.py) ----------------------------------- #
SEARCH_PLACEHOLDER = "Search your library"
SEARCH_NAME = "Search your library"
SEARCH_TIP = "Search your library: a title by its kana, kanji or romaji name\n• / or Ctrl+K · Esc clears, then closes"
SEARCH_KEY = "/"
SEARCH_RESULTS_NAME = "What your library holds for “{query}”"
SEARCH_NONE = "Nothing in your library matches “{query}”"
SEARCH_MORE = "and {n:,} more"
SEARCH_PLAY = "▶"
SEARCH_TOP = "⤒"
SEARCH_PLAY_NAME = "Play"
SEARCH_PLAY_TIP = "Play: open its next episode, as its row's ▶ does"
SEARCH_TOP_NAME = "Top"
SEARCH_TOP_TIP = {
    "current": "Top: make it the next thing you watch or read",
    "goal": "Top: bring its next part up to the top of Current; the rest stays in Goal",
    "arrivals": "Top: put it up next, out of New arrivals",
    "finished": "Top: put it back at the top of Current, its cards back in your order",
}
SEARCH_SHOW_TIP = {
    "current": "Show it in Current",
    "goal": "Show it in Goal",
    "arrivals": "Show it in New arrivals",
    "finished": "Show it in Finished",
}
ADD_NAME = "Add"
ADD_TIP = "Add: files, a folder, a book or deck, a video's subtitles, or pasted text"
ADD_MENU_NAME = "What you can add to your library"
ADD_ITEMS = {
    "files": ("Files…", "Add subtitle or text files: with their show when it's in Current, else at the top of Current"),
    "folder": ("A folder…", "Read a folder where it is: Surasura keeps its own copy of the text and looks there again "
                            "for new episodes\nA show it hasn't shown you yet waits in New arrivals"),
    "extract": ("EPUB or Anki deck…", "Turn an EPUB or an Anki deck into text you can add"),
    "youtube": ("YouTube or bilibili…", "Bring in a YouTube or bilibili.tv video's subtitles from its link"),
    "paste": ("Paste text…", "Paste text and give it a title: it's added as one text file"),
}
ADD_DROP_LINE = "Or drop files anywhere in your list"
ADD_PICK_FILES = "Add files to your library"
ADD_PICK_FOLDER = "Add a folder to your library"
ADD_PICK_FILTER = "Subtitles and text (*.srt *.ass *.ssa *.txt *.md);;All files (*)"
ADD_NOTHING = "Nothing to add in {name}: no subtitle or text files"
ADD_FOLDER_FAILED = "{name} couldn't be read: {why}"
PASTE_NAME = "Paste text"
PASTE_HEADING = "Paste text"
PASTE_TITLE_PLACEHOLDER = "Its title"
PASTE_TITLE_NAME = "The text's title"
PASTE_TEXT_PLACEHOLDER = "Paste the text here"
PASTE_TEXT_NAME = "The text"
PASTE_DEFAULT_TITLE = "Pasted text"
PASTE_ADD = "Add"
PASTE_ADD_TIP = "Add it to your library as one text file, at the top of Current"
PASTE_CANCEL = "Cancel"
PASTE_CANCEL_TIP = "Close without adding anything (Esc does the same)"
PASTE_FAILED = "The pasted text couldn't be saved: {why}"
PASTE_KEPT = "The pasted text wasn't added. It is kept in {folder}"                     # W3.2 fix round (N7)
# --- end W3.2 Q3
# --- SRC W1b: the source folders Surasura reads where they are (app/services/source_looks.py, app/qt/shell.py) ------ #
SOURCES_OFFLINE = "{path} isn't reachable; its {n:,} episodes are kept"
SOURCES_OFFLINE_ONE = "{path} isn't reachable; its episode is kept"
SOURCES_OFFLINE_NONE = "{path} isn't reachable"
SOURCES_OFFLINE_TIP = "Nothing is moved or marked while a folder is away: Surasura looks again when it's back"
SOURCES_KEEP_WAITING = "Keep waiting"                       # round 8 row 54: the offline line's ✕, in words
SOURCES_KEEP_WAITING_TIP = "Hide this until the folder is back"
SOURCES_READING = "Reading {name}: {found:,} found in {shows:,} shows…"
SOURCES_READ = "Reading {name} where it is: {added:,} new"
SOURCES_READ_ARRIVALS = "Reading {name} where it is: {added:,} new · the shows you haven't seen wait in New " \
                        "arrivals"
SOURCES_QUEUED = "Reading {name} where it is, after the look under way…"
SOURCES_READ_LATER = "Reading {name} where it is: its first look comes with the next one"
SOURCES_READ_NOTHING = "Reading {name} where it is: nothing new in it yet"
SOURCES_UNREACHABLE = "Reading {name} where it is: it can't be reached now · Surasura looks again later"
SOURCES_REFUSED = "{name} can't be read where it is: {reason}"
SOURCES_NO_LIBRARY = "your library isn't open"
SOURCES_FROM = "from {name}"
# --- end SRC W1b
# --- W3.2 Q5: Needs you's cards, their buttons and what they say (app/qt/needs.py; the entries' own words are
# `app/services/needs.STRINGS`) ------------------------------------------------------------------------------------- #
NEEDS_EMPTY_TEXT = "\n".join(NEEDS_EMPTY)
NEEDS_ACTIONS = {   # action name -> (label, tooltip)
    "find_videos": ("Find videos", "Look in the show's folder and your video folders for each episode's video, by its "
                                   "number. Nothing is linked until you say so"),
    "link_these": ("Link these · {n}", "Link each video found to its episode, so its cards get their pictures and "
                                       "audio"),
    "find_all": ("Find all missing videos", "Look for every show's missing videos at once, by episode number"),
    "choose_folder": ("Choose a folder…", "Point these files at the folder they're in now: each is matched by its "
                                          "name, else by its episode number"),
    "choose_file": ("Choose file…", "Point this episode at its file, wherever it is now in your library folder"),
    "choose_video": ("Choose file…", "Choose this episode's video yourself"),
    "keep_words": ("Keep its words", "Leave it as it is: its words still count toward your list, and it stops "
                                     "asking"),
    "keep_all": ("Keep all their words", "Leave every missing file as it is: their words still count, and they stop "
                                         "asking"),
    "remove": ("Remove", "Send it to the trash (kept 30 days): its words stop counting. Undo puts it back"),
    "remove_episode": ("Remove episode", "Send this episode to the trash (kept 30 days). Undo puts it back"),
    "remove_all": ("Remove all", "Send every missing file below to the trash (kept 30 days). Never a drive that's "
                                 "only offline. Undo puts them back"),
    "this_one": ("This one", "It's this missing file, moved or renamed: it keeps its place, its ✓ and its cards"),
    "its_new": ("It's new", "None of these: it joins your library as a new file"),
    "mine_anyway": ("Mine anyway", "Make its cards without timing them to the video"),
    "ask_hato": ("Ask hato again", "Ask hato for the videos it paired, now"),
    "dismiss": ("Dismiss", "Take this off the list"),
    "leave_them": ("Leave them", "Make no cards for them: they stop asking"),
    "make_cards": ("Make their cards", "Make the cards Connect missed"),
    "first_cards": ("Make cards", "Make cards for these episodes now, and for what comes into your top 20 from now on.\n"
                                  "• Change it any time: Settings › Anki"),
    "not_now": ("Not now", "Make no cards for them now. Nothing else changes.\n"
                           "• Turn it on any time: Settings › Anki"),
    # … the same line once setup's page 5 turned *Make cards for me as I watch* on: it asks only about these episodes
    "first_cards_on": ("Make cards", "Make cards for these episodes now.\n"
                                     "• What comes into your top 20 later gets its cards already: Settings › Anki"),
    "not_now_on": ("Not now", "Make no cards for these episodes. Nothing else changes:\n"
                              "• What comes into your top 20 later still gets its cards"),
    "mark_known": ("Mark them known", "Their words count as known from now on: your list and journey follow at the "
                                      "next Generate"),
    "leave_known": ("Leave them", "Their words stay as they are, and these cards stop asking. Cards you suspend or "
                                  "mark from now on still count"),
    "mine_text_only": ("Mine the text only", "Make its cards from the subtitles alone, with no picture or audio"),
    "open_logs": ("Open the logs folder", "Open the folder where Surasura keeps its logs, to look at them or send them"),
    "save_logs": ("Save logs to a file…", "Save the last week's logs into one zip file you can send"),
}
NEEDS_LOOKING = "Looking…"
NEEDS_MORE_LINES = "and {n} more"
NEEDS_LOOK_FAILED = "Couldn't look for its videos: {why}"
NEEDS_REMOVE_TITLE_ONE = "Remove {name}?"
NEEDS_REMOVE_TITLE = "Remove {n} files?"
NEEDS_REMOVE_BODY = "They go to the trash, kept 30 days; their words stop counting. Undo puts them back where they were."
NEEDS_REMOVE_YES_ONE = "Remove it"
NEEDS_REMOVE_YES = "Remove {n} files"
NEEDS_REMOVE_YES_TIP = "Send them to the trash (30 days)"
NEEDS_REMOVED_ONE = "{name} went to the trash (30 days)"
NEEDS_REMOVED = "{n} files went to the trash (30 days)"
NEEDS_RELINKED = "{label} points at its file again"
NEEDS_RELINKED_N = "{k} of {n} files found in that folder and pointed at"
NEEDS_RELINKED_NONE = "Nothing in that folder has these files' names or episode numbers"
NEEDS_LINKING = "Linking {n} videos to their episodes"
NEEDS_LINKING_ONE = "Linking {label}'s video"
NEEDS_KEPT = "Kept: their words still count"
NEEDS_FIRST_CARDS_MADE = "Cards are made by themselves from now on · change it in Settings › Anki"
NEEDS_FIRST_CARDS_LATER = "Turn it on any time in Settings › Anki"
NEEDS_FIRST_CARDS_MADE_ON = "Cards are being made for them"
NEEDS_FIRST_CARDS_LATER_ON = "No cards for them · what comes into your top 20 later still gets its cards"
NEEDS_FIRST_CARDS_NOT_ON = "No cards were made: {why}"
NEEDS_KNOWN_MARKED = "{n} words are known now · your list follows at the next Generate"
NEEDS_KNOWN_MARKED_NONE = "Their words were known already"
NEEDS_KNOWN_LEFT = "Left as they are · cards you suspend or mark from now on still count"
NEEDS_FIRST_CARDS_AUTOMATION_OFF = "automatic actions are off in Settings; turn them on, then ask again"
NEEDS_ITS_NEW = "{name} joins your library as a new file"
NEEDS_ASKED_HATO = "Asked hato for its videos"
NEEDS_MINE_ANYWAY = "It mines without timing, in turn"
NEEDS_MINE_ANYWAY_NOT = "Nothing to mine there any more"
NEEDS_DISMISSED = "Taken off the list"
NEEDS_SAVED_LOGS = "Logs saved to {path}"
NEEDS_SAVE_LOGS_TITLE = "Save logs to a file"
NEEDS_CHOOSE_FILE_TITLE = "Choose {label}'s file"
NEEDS_CHOOSE_VIDEO_TITLE = "Choose {label}'s video"
NEEDS_CHOOSE_FOLDER_TITLE = "Choose the folder they're in now"
NEEDS_FAILED = "That couldn't be done: {why}"
# --- end W3.2 Q5
# --- W3.2 Q6: Change cover… (the ⋯ menu's entries, `app/qt/covers.cover_menu_entries`), its toasts and notes
COVER_MENU = {
    "choose": ("Choose an image…", "Use a picture from this computer as its cover. It's copied into your User Files and "
                                  "kept, even when another picture is found"),
    "generated": ("Use a generated cover", "Show its painted cover from now on, even when a picture is found beside "
                                           "its files"),
}
COVER_PICK_TITLE = "Choose a cover image"
COVER_PICK_FILTER = "Images (*.jpg *.jpeg *.png *.gif *.webp)"
COVER_CHOSEN = "New cover for {title}"
COVER_GENERATED = "{title} shows its generated cover"
COVER_NOT_IMAGE = "That file isn't a picture Surasura can use as a cover"
COVER_CANT = "The library can't be changed right now, so its cover stays as it is"
# --- end W3.2 Q6
# --- W3.2 L3: Change cover…'s online entries (only with Download covers on) and its words
COVER_ONLINE = ("Find it online…", "Look its name up on AniList and choose one of the top five covers")
COVER_PASTE = ("Paste a link", "Use the cover of the AniList, TMDB or YouTube page whose link you copied")
COVER_LOOKING = "Looking {title} up on AniList…"
COVER_CANDIDATE_TIP = "Use this cover for {title}. It's kept, even when another picture is found"
COVER_NONE_FOUND = "No cover found on AniList for {title}"
COVER_LOOKUP_FAILED = "AniList couldn't be reached, so no cover was looked up for {title}. Try again later"
COVER_FETCHING = "Fetching the cover for {title}…"
COVER_LOOKUP_BROKE = "The cover lookup for {title} stopped with an error: {why}"
COVER_PASTE_NOT_A_LINK = "Copy an AniList, TMDB or YouTube link first, then choose Paste a link"
COVER_PASTE_WHY = {
    "off": "Download covers is off in Settings → Connections, so nothing was looked up or fetched",
    "no_key": "TMDB covers aren't available yet: copy an AniList or YouTube link instead",
    "failed": "That cover couldn't be fetched. Check the link, or try again later",
}
COVERS_REMOVED = "Downloaded covers removed. Pictures beside your files come back by themselves"
COVERS_REMOVE_NONE = "There's no library open, so there are no downloaded covers to remove"
# --- end W3.2 L3
# --- round 8 row 45, P3: the shared press helpers and the main window's sweep (press.py)
OPEN_IT = "It"
OPEN_NOT_OPENED = "the system didn't open it"
REFRESH_FAILED = "Your folders couldn't be looked at just now: {why}"
REFRESH_NOT_LOOKED = "the look stopped"
# --- end round 8 row 45, P3

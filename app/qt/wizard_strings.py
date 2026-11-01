"""Every word the setup wizard shows (W3.5 part 3; the signed draft `wizard-draft/WIZARD-DRAFT.md`, WZ-1…WZ-7, RS-7).

One table, so the wizard can be translated with the rest of the window (`app/qt/strings.py` is the window's; the wizard
keeps its own, as a module keeps its `qt_strings.py`). RS-7: the title says the benefit, at most one short line under
it, nothing about what's under the hood; anything longer is a tooltip, with its action on a "• " line of its own.
"""

# --- the frame -------------------------------------------------------------------------------------------------------- #
NAME = "Setting up Surasura"
FINISH_LATER = "Finish later"
FINISH_LATER_TIP = ("Close setup and go to your list. What you've already set up is kept.\n"
                    "• Finish it any time: Settings → Set up again")
BACK = "Back"
BACK_TIP = "The step before. Your choices stay as you left them."
SKIP = "Skip"
SKIP_TIP = "Leave this step for now: nothing is changed. You can set it in Settings later."
NEXT = "Next"
NEXT_TIP = "Keep these choices and go on.\n• Enter"
GENERATE = "Generate"
GENERATE_TIP = "Make your list from your shows now, and open it when it's ready.\n• Enter"
KEY_ENTER = "Enter"
STEPS_NAME = "Setup steps"
STEP_DONE_NAME = "{name}, done"
STEP_HERE_NAME = "{name}, this step"
STEPS = {"language": "Your language", "known": "What you know", "shows": "Your shows", "order": "Card order",
         "cards": "Cards made for you", "level": "Your list"}
RECOMMENDED = "RECOMMENDED"
SWITCH_TIP = "{name}\n{tip}"                # a switch has no words of its own: its tip names it first
ANKI_CLOSED = "Anki isn't open"
# §C11: Anki open, AnkiConnect not answering (an Anki process seen) — or a look that can't tell the two apart
ANKI_NO_CONNECT = "Anki is open, but AnkiConnect isn't answering"
ANKI_NO_CONNECT_HOW = ("In Anki, install the AnkiConnect add-on (Tools › Add-ons › Get Add-ons…, code 2055492159), "
                       "then restart Anki and press Check again.")
ANKI_NO_CONNECT_CARD = "AnkiConnect isn't answering"          # the From Anki card's short line
ANKI_UNSURE = "Anki isn't open, or AnkiConnect isn't answering"
ANKI_UNSURE_CARD = "Anki closed, or no AnkiConnect"
ANKI_UNSURE_HOW = ("Open Anki. If it's open already, install the AnkiConnect add-on (Tools › Add-ons › Get Add-ons…, "
                   "code 2055492159), then restart Anki and press Check again.")
CHECK_AGAIN = "Check again"
CHECK_AGAIN_TIP = "Look for Anki again, once it's open."
CHECKING = "Looking for Anki…"
# Brought over from Surasura 2 (WZ-8): the whole setup once, each page showing the choices already made there
UPGRADE_LINE = ("Welcome to Surasura 3. Your choices from Surasura 2 are already picked; "
                "what's new starts at the recommended choice.")

# --- 1 · your language ------------------------------------------------------------------------------------------------ #
LANGUAGE_TITLE = "What are you learning?"
LANGUAGE_LINE = "Surasura builds your word list from the shows, books and videos you choose."
LANGUAGE_HINT = "← → to choose · Enter to go on"
LANGUAGE_GLYPHS = {"ja": "日本語", "zh": "中文"}
LANGUAGE_WORDS = {"ja": "Japanese", "zh": "Chinese"}
LANGUAGE_TIPS = {"ja": "Japanese: your list, your example sentences and your cards in Japanese.",
                 "zh": "Chinese: your list, your example sentences and your cards in Chinese."}
LANGUAGE_CHOICE_NAME = "Language"

# --- 2 · what you know ------------------------------------------------------------------------------------------------ #
KNOWN_TITLE = "Skip the words you already know"
KNOWN_LINE = "Words you know fade out, so only the new ones are left to learn."
# the faded sentence: (words, the one new word's index) per language; the new word is the one the vein marks
KNOWN_SENTENCE = {"ja": (("この", "店", "の", "ラーメン", "は", "本当", "に", "絶品", "だ"), 7),
                  "zh": (("这", "家", "店", "的", "拉面", "真", "是", "绝品"), 7)}
KNOWN_SENTENCE_NAME = "A sentence where only the new word stays bright"
KNOWN_HOW_NAME = "Where your known words come from"
FROM_ANKI = "From Anki"
FROM_ANKI_OPEN = "Anki is open · stays in sync"
FROM_ANKI_TIP = ("Read the words you know from the Anki decks you study, and keep them in sync.\n"
                 "• Your cards are only read: nothing in Anki is changed")
IMPORT_LIST = "Import a list"
IMPORT_LIST_LINE = "Migaku · Jiten · a file"
IMPORT_LIST_TIP = "Bring in the words you know from Migaku, Jiten or an Anki deck file."
START_FRESH = "Start fresh"
START_FRESH_LINE = "Nothing to bring in"
START_FRESH_TIP = "Start with no known words. Surasura learns them as you go."
DECKS = "Read these decks"
DECKS_NAME = "Decks to read"
DECK_CARDS = "{n:,} cards"
DECK_TIP = "{deck}: {n:,} cards you've studied.\n• Click to read this deck, or to leave it out"
NO_DECKS = "Anki has no decks with studied cards yet."
IMPORT_MIGAKU = "Migaku…"
IMPORT_MIGAKU_TIP = "Open the Migaku import: the words you know, from Migaku's export."
IMPORT_JITEN = "Jiten…"
IMPORT_JITEN_TIP = "Open the Jiten import: the words you know, from your Jiten account."
IMPORT_FILE = "An Anki deck file…"
IMPORT_FILE_TIP = "Open the deck-file import: the words you know, from an .apkg file."
SYNC_STARTED = "Reading the words you know from Anki…"
UPGRADE_KNOWN_LINE = "The words you know came over from Surasura 2."
KEEP_CAME_OVER = "Keep what came over"
KEEP_CAME_OVER_LINE = "Nothing more to bring in"
KEEP_CAME_OVER_TIP = "Keep the words you know from Surasura 2, as they are.\n• Add more any time: Settings"

# --- 3 · your shows --------------------------------------------------------------------------------------------------- #
SHOWS_TITLE = "Bring in what you'll watch and read"
SAMPLES = "Try it with samples first"
SAMPLES_TIP = "Not sure yet? Start with a few samples to see how it works.\n• Copies a few sample files into your library"
SAMPLES_ADDED_LINE = "Added {n:,} samples: they show here in a moment."     # (W3.2 Q3: page 3 takes + Add's actions)
SAMPLES_NONE = "Samples go into an empty library only: yours has files already."
ROWS_NAME = "What's in your library"
ROW_COUNT = {"shows": ("1 episode", "{n:,} episodes"), "reading": ("a book", "a book · {n:,} parts"),
             "videos": ("1 video", "{n:,} videos")}
ROW_FILES = ("1 file", "{n:,} files")
ROW_LINE = "{count} · {folder}"
ROWS_MORE = "and {n:,} more"
COVERS = "Show covers"
COVERS_LINE = "Sends each show's AniList id or name to AniList, and a video's id to YouTube. Nothing else."
COVERS_TIP = ("Covers for your shows, looked up by each show's name.\n"
              "• Turn it off any time: Settings")
COVERS_PICTURE_NAME = "A plain tile becomes the show's cover"
UPGRADE_SHOWS_LINE = ("Your known words and settings came over from Surasura 2. "
                      "Add the folders your shows and books are in.")
# the folders your shows and books are in (SRC W1a): read where they are, each text copied into your library
FOLDERS = "Where are your shows and books?"
FOLDERS_NAME = "The folders your shows and books are in"
PICK_FOLDER = "Choose a folder…"
PICK_ANOTHER = "Add another folder…"
PICK_FOLDER_TIP = ("Choose a folder your shows and books are in: Surasura reads them where they are.\n"
                   "• You sort it show by show next; the rest wait in New arrivals (Surasura 2 tiers are kept)\n"
                   "• Nothing in it is changed; each new episode joins your library by itself")
PICK_TITLE = "Where are your shows and books?"
# Alpha 8 (Sonic: "You just pick the file or you pick the folder"): a file, a folder, or YouTube links — each kind found
PICK_FILE = "Choose a file…"
PICK_FILE_TIP = ("Choose an episode's subtitles or its video, a text or an EPUB: Surasura sees which it is.\n"
                 "• It goes at the top of Current; nothing in the file is changed")
PICK_FILE_TITLE = "Choose a file"
PICK_FILE_FILTER = "Subtitles, videos, texts and books ({patterns});;All files (*)"
FILE_NOT_READ = "{name}: Surasura reads subtitles, texts and EPUBs only."
# alpha 8 (A8P-L6, Sonic "Yes do that"): a video chosen as a file — its subtitle found beside it by the library's rule
VIDEO_LOOKING = "Looking beside {name} for its subtitle…"
VIDEO_SUBTITLE = "{name}: its subtitle {subtitle} comes in."
VIDEO_SUBTITLE_BEST = "{name}: {subtitle} comes in (the best of {n} subtitles beside it)."
VIDEO_NO_SUBTITLE = ("{name}: no subtitle beside it, and Surasura reads a video's subtitle file, not the video. "
                     "Choose its folder to look through it, its Subs folder too.")
VIDEO_NO_SUBTITLE_PLAIN = ("{name}: no subtitle beside it, and Surasura reads a video's subtitle file, not the video. "
                           "Choose its subtitle file instead.")
VIDEO_STILL_LOOKING = "Still looking for your video's subtitle: Next again in a moment."
VIDEO_ITS_FOLDER = "Choose its folder"
VIDEO_ITS_FOLDER_NAME = "Choose the folder {folder}"
VIDEO_ITS_FOLDER_TIP = ("Read the video's whole folder instead, as Choose a folder… does:\n"
                        "• Each video's subtitle is found by its name, a Subs folder too")
FILES_ADDED = "Bringing in {what}: they go at the top of Current."
FILES_N = ("1 file", "{n:,} files")
BOOK_ADDED = "{name} is in Current: {parts} parts."
BOOK_FAILED = "{name} couldn't be brought in: {why}"
YOUTUBE = "YouTube…"
YOUTUBE_TIP = ("Paste YouTube links, one a line. Each line's first video comes in while setup finishes.\n"
               "• A playlist: its other videos come in after, in the background (the bottom bar shows them)")
YOUTUBE_NAME = "YouTube links, one a line"
YOUTUBE_HINT = "One link a line: a video, or a playlist (its first video now, the rest after)"
YOUTUBE_RISK_LINE = "YouTube can turn requests away for a while; it's for your own study."
YOUTUBE_NEEDS_RISK = "Tick “{risk}” to bring in from YouTube, or clear the links."
YOUTUBE_NONE = "Paste a YouTube link first: one a line."
YOUTUBE_BUSY = "Your last links are still coming in: press Next again once they're in, or add these later."
YOUTUBE_HAD = "already in your library: nothing new came in"
YOUTUBE_NOT_ADDED = "couldn't be added to your library: they wait in Processed"
FILES_NOT_ADDED = "Your files couldn't be added just now: your library can't be saved. Try Next again in a moment."
FOLDER_REMOVE = "Remove"
FOLDER_REMOVE_NAME = "Remove {folder}"
FOLDER_REMOVE_TIP = "Leave it out: nothing is read from it."
FOLDER_REFUSED = "{folder}: {why}"
# K6: a folder inside the ones picked that is never read (a backup, a game's files), skipped before the first look
SKIP_FOLDER = "Skip a folder…"
SKIP_FOLDER_TIP = ("Choose a folder inside one you picked that Surasura should never read (a backup, a game's files)\n"
                   "• Nothing in it is changed; Settings › Content lists it to read again")
SKIP_TITLE = "A folder Surasura never reads"
SKIPPED_ROW = "Skipped: {folder}"
SKIP_REMOVE = "Read it after all"
SKIP_REMOVE_NAME = "Read {folder} after all"
SKIP_REMOVE_TIP = "Read this folder after all: it isn't skipped."
READING = "Found {episodes} in {shows}…"
# a7 (DIAGNOSIS 2), Mado-O: the first read lands in New arrivals for the sort screen: said where it happens
READ_DONE = "Found {episodes} in {shows}: any not sorted wait in New arrivals."
READ_STOPPED = "Stopped: {episodes} in {shows} came in, kept for you to sort."
READ_UNREACHABLE = "{folder} isn't reachable: nothing was read from it."
READ_FAILED = "{folder} couldn't be read: {why}"
READ_BUSY = "Surasura is already reading your folders: try again in a moment."
COPYING = "Copying into your library: {done:,} of {total:,} files…"                       # K5
READ_BIG = "{line} · That's a big library: over 15,000 items. You can Stop and pick fewer folders."   # K5 (A4K-4)
EVERY_CORE = "Use every core"                                                              # K5 C4
EVERY_CORE_LINE = "Reads your library faster; the computer is busier while it does. Settings › Content has it too."
EVERY_CORE_TIP = ("On: reading and copying your library use every core of your computer, so it ends sooner.\n"
                  "Off: half of them, so the computer stays quick to use")
READ_WAITING = "Waiting for your library: another part of Surasura is saving. Reading goes on by itself…"   # K4
READ_NOT_READY = "Your library isn't ready yet: try again in a moment."
EPISODES = ("1 episode", "{n:,} episodes")
SHOWS_N = ("1 show", "{n:,} shows")
STOP = "Stop"
STOP_TIP = "Stop reading now. What came in so far is kept."
STOPPING = "Stopping…"

# --- 4 · card order --------------------------------------------------------------------------------------------------- #
ORDER_TITLE = "Your cards, in the order you'll meet the words"
ORDER_TODAY = "Today"
ORDER_WITH = "With\nSurasura"
ORDER_CARDS = {"ja": ("宇宙", "絶品", "約束", "匂い"), "zh": ("宇宙", "绝品", "约定", "味道")}
ORDER_EPISODES = (1, 1, 2, 5)              # the in-order row: the episode each word first comes up in
ORDER_EPISODE = "episode {n}"
ORDER_PICTURE_NAME = "Your new cards, scattered today, in the order of your shows with Surasura"
KEEP_ORDER = "Let Surasura keep them in order by itself"
KEEP_ORDER_LINE = "After each new list and each move; never while you review"
KEEP_ORDER_TIP = ("Puts your new cards in the order you'll meet the words, and tags the cards it moves Surasura.\n"
                  "• Undo: 順 → Restore")
DECK = "New cards are in"
DECK_PICK_TIP = "The deck your new cards are in: the one Surasura keeps in order."
LATER = "Cards for words not on your list"
LATER_NAME = "Cards for words not on your list"
LATER_CHOICES = {"leave": "Leave them", "mark": "Mark them", "aside": "Set them aside"}
LATER_TIPS = {"leave": "Leaves them as they are, after the cards for words on your list.",
              "mark": "Tags them Surasura::later and flags them purple.\n• Undo: 順 → Restore",
              "aside": ("Suspends them and tags them Surasura::later.\nThey come back when the word is on your list.\n"
                        "• Undo: 順 → Restore")}
OPEN_ANKI = "Open Anki when Surasura opens"
OPEN_ANKI_LINE = "So the reviews from your phone count"
OPEN_ANKI_TIP = "Starts Anki with Surasura, so what you reviewed on your phone is read in."
ORDER_OFF = "Card order is switched off: turn 順 on in Settings to use it."
ORDER_ABSENT = "Card order (順) isn't part of this Surasura."
ORDER_AUTOMATION_OFF = "Automatic actions are off in Settings: this starts once they're on."
# Michi-C (A7B-1…A7B-3 PROVISIONAL): the shows behind the deck's new cards — the first sentence is *Needs you*'s
# (`app/services/needs.backlog_head`: *Your 2,300 new cards come from 14 shows; 12 are on this PC.*), then one of these
BEHIND_LOOKING = "Looking at where your new cards came from…"
BEHIND_WAIT = ("1 of them waits in New arrivals.", "{k} of them wait in New arrivals.")
BEHIND_IN = "They're in your list: their cards go in the order you'll meet the words."
BEHIND_NONE = "Add their subtitles to put their cards in order."
BEHIND_ADD = "Add them"
BEHIND_ADD_TIP = ("Puts these shows from New arrivals into your list, at Soon: their cards go in the order you'll meet "
                  "the words.\n• Undo: the toast, or Ctrl+Z")
BEHIND_ADDED = "Added: their cards go in the order you'll meet the words."
BEHIND_NOT_ADDED = "Nothing was added: your library can't be changed just now. Try again in a moment."

# --- 5 · cards made for you ------------------------------------------------------------------------------------------- #
CARDS_TITLE = "Cards that make themselves"
CARDS_LINE = "From the episode you're watching: the line, its audio and a picture."
CARDS_PICTURE_NAME = "A line from an episode becomes an Anki card with its audio and a picture"
CARDS_LINE_SAMPLE = {"ja": ("この店のラーメンは本当に絶品だ", "ぜっぴん", "絶品"),
                     "zh": ("这家店的拉面真是绝品", "juépǐn", "绝品")}
MINER_MISSING = "Anki Miner makes the cards"
MINER_MISSING_LINE = "It isn't installed yet · free"
MINER_READY = "Make cards for me as I watch"
MINER_READY_LINE = "Anki Miner {version} · ready for Surasura"
MINER_READY_TIP = ("Anki Miner makes a card for a new word from the episode you're watching: the line, its audio and a "
                   "picture.\n• Turn it off any time: Settings")
MINER_LOOKING = "Looking for Anki Miner…"
MINER_FIX_TIP = "Something only you can fix before cards can be made."
STAR = "★"
STAR_ASK = "Like Anki Miner?"
STAR_LINK = "Star it on GitHub"
STAR_TIP = "Anki Miner is free and made by one person: a star on GitHub helps.\n• Opens its page in your browser"
MINER_UPDATE_FIRST = "Anki Miner 3.7 or newer needs no setup here. Update it and press Check again."
MINER_BY_HAND = "Or keep this Anki Miner and make its profile by hand:"
COPY_PATH = "Copy path"
COPY_PATH_TIP = "Copy the file's path, to paste into Anki Miner's file chooser."
PATH_COPIED = "The path is copied: paste it into Anki Miner's file chooser."
PATH_NAME = "The file to choose in Anki Miner"
INSTALL = "Install Anki Miner…"
INSTALL_TIP = "Get Anki Miner, free: its installer, from its GitHub release.\n• Asks before it downloads"
UPDATE_MINER = "Update Anki Miner…"
UPDATE_MINER_TIP = ("Get the newest Anki Miner, free: its installer, from its GitHub release.\n"
                    "• Asks before it downloads")
INSTALL_OPENED = "Install Anki Miner from the page in your browser, then check again."
INSTALL_STOPPED = "Download stopped."
INSTALL_BUSY = "Anki Miner or Surasura's card making is running: close it, then try again."
INSTALL_ASK_TITLE = "Download Anki Miner?"
INSTALL_ASK_BODY = ("About 180 MB, from Anki Miner's own GitHub release, checked before it opens.\n"
                    "Its installer opens when it's done.")
INSTALL_ASK_YES = "Download"
INSTALL_ASK_YES_TIP = "Download Anki Miner's installer and open it."
INSTALL_ASK_NO = "Not now"
INSTALL_ASK_NO_TIP = "Nothing is downloaded."
DOWNLOADING = "{mb:.0f} of {of:.0f} MB"
DOWNLOADING_NAME = "Downloading Anki Miner"
CANCEL_DOWNLOAD = "Cancel"
CANCEL_DOWNLOAD_TIP = "Stop the download. Nothing is left behind."
MINER_CHECK_TIP = "Look for Anki Miner again, once it's installed or set up."
# A4M1-2 (lean taken, PROVISIONAL): Surasura runs Anki Miner's own setup — never "open Anki Miner"
FINISH_SETUP = "Finish its setup"
FINISH_SETUP_TIP = ("Anki Miner downloads its dictionaries by itself, as its own setup does, and Surasura sets its "
                    "deck and note type from yours.\n• Nothing to open: it runs in the background, a few minutes")
# A4M1-2b: what Surasura can't tell from your settings is chosen here, never in Anki Miner's window
MINER_DECK = "New cards go in"
MINER_DECK_TIP = "The Anki deck Anki Miner puts your new cards in. Surasura sets it in Anki Miner for you."
MINER_NOTE_TYPE = "Note type"
MINER_NOTE_TYPE_TIP = ("The kind of card Anki Miner makes (Lapis, Kiku…). Surasura sets it in Anki Miner for you, "
                       "with its fields.")
MINER_ASK_DECK = "Which deck should Anki Miner put your new cards in? Choose it, then press Finish its setup again."
MINER_ASK_NOTE = ("Which note type should Anki Miner make your cards with? Choose it, then press Finish its setup "
                  "again.")
MINER_ASK_FIELDS = ("“{note}” has no Sentence field, so Anki Miner can't make your cards with it. Choose another "
                    "note type, then press Finish its setup again.")
SETUP_SAID = {"set-up": "Anki Miner's setup is finished.{detail}",
              "busy": "Anki Miner or Surasura's card making is running: Anki Miner's setup waits until it's done. "
                      "Try again then.{detail}",
              "failed": "Anki Miner's setup didn't finish: {detail}",
              "missing": "Anki Miner isn't installed where Surasura looked.",
              "ready": "Anki Miner's setup is already finished.",
              "rest": "Anki Miner's setup went as far as Surasura can take it. Still missing: {detail}",
              "ask": "Choose where Anki Miner puts your cards, then press Finish its setup again.{detail}"}
DOTS = ("Anki", "AnkiWeb", "Anki Miner", "Its setup")
DOT_STATE = {"ok": "ready", "warn": "needs you", "off": "not yet"}
DOT_NAME = "{name}: {state}"

# --- 6 · your list ---------------------------------------------------------------------------------------------------- #
LEVEL_TITLE = "Your list"
LEVEL_LINE = "How much there is to learn, and how much of your shows you'll understand."
LEVEL = "Level"
AUTOMATIC = "Automatic"
AUTOMATIC_TIP = ("Surasura picks the level for you, at least 850 words ahead, and moves it as you learn.\n"
                 "• Moving the slider picks one yourself")
SLIDER_NAME = "Level"
SLIDER_TIP = "Fewer, only the most common words to the left; more, rarer words to the right.\n• ← → to move"
SLIDER_LOW = "the most common words"
SLIDER_HIGH = "rarer words"
WORDS = "words to learn"
COVERAGE = "of your shows understood"
EVERY = "between meetings with each word"
WORDS_N = "{n:,}"
COVERAGE_N = "{pct:.0f}%"
EVERY_N = "{h:.0f} h"
EVERY_MIN = "{m:.0f} min"
NONE_YET = "—"
COUNTING = "Counting your shows…"
DISCORD = "Questions? Join us on Discord"                     # 3.0: the last page's one line (a link, in the browser)
DISCORD_TIP = "Surasura's Discord: ask anything, or tell us what went wrong.\n• Opens it in your browser"
NO_SHOWS = "Add a show first, and the numbers show here."
# a7 (DIAGNOSIS 1, Sonic): the first Generate reads the whole library — said in the line he watches
MAKING = "Making your list… The first time reads every show and book, so it can take a few minutes."
MAKING_PCT = "Making your list… {pct} % · The first time can take a few minutes."
NOT_STARTED = "Your list couldn't start: press Generate at the top when you're ready."

# --- after page 3: the load screen and the sort screen (Sonic 2026-10-30) ------------------------------------------- #
LOAD_NAME = "Getting your library ready"
LOAD_MARK_NAME = "Surasura"
LOAD_SCAN = "Reading your library · {episodes} in {shows}"
LOAD_COPY = "Bringing your files in · {done:,} of {total:,}"
LOAD_WAIT = "Waiting for your library…"
LOAD_INDEX = "Reading the words · {done:,} of {total:,}"
LOAD_INDEX_START = "Reading the words…"
LOAD_COVERS = "Finding covers · {done:,} of {total:,}"
LOAD_COVERS_START = "Finding covers…"
LOAD_ANKI = "Bringing in your known words from Anki…"
LOAD_YOUTUBE = "Bringing in your videos from YouTube…"                        # alpha 8: the load waits for it last
YOUTUBE_FETCHING = "YouTube · bringing in {what}…"
YOUTUBE_VIDEOS = ("1 video", "{n:,} videos")
YOUTUBE_DONE = "YouTube · {what} in New arrivals"
YOUTUBE_PLACED = "YouTube · {what} in your library"
YOUTUBE_FAILED = "YouTube · {why}"
YOUTUBE_SOME_FAILED = "YouTube · {what} in New arrivals · {why}"
YOUTUBE_REST = ("the first of its playlist: the rest follows in the background",           # alpha 8: a playlist's
                "the first of {n:,} playlists: the rest follows in the background")         # rest, after setup
YOUTUBE_REST_ONLY = ("its playlist follows in the background", "their {n:,} playlists follow in the background")
LOAD_STOP = "Stop"
LOAD_STOP_TIP = ("Stop here and sort what was read so far. Nothing read is lost; a folder not reached yet stays on "
                 "the page to read again.")
LOAD_STOPPING = "Stopping…"
LOAD_LINES = ("Come back after an episode",
              "Your shows are read once, so every list after this is quick",
              "Make a tea; this part only happens once",
              "Every word you already know will fade from your list",
              "The bigger the library, the better the list")
SORT_NAME = "Sort your library"
SORT_TITLE = "Where does each one go?"
SORT_LINE = "Sort the one at the top. The next one comes up by itself."
SORT_COUNT = "{n:,} left to sort"
SORT_GROUPS = {"new": "NEW", "watched": "ALREADY WATCHED"}
# (key, label, tip, the key's name on screen): Soon first, the one key that isn't an arrow (Sonic 2026-10-30)
SORT_CHOICES = (("soon", "Soon", "Below Current's Soon line: after what you're on now. It still counts toward your "
                                 "list.", "S"),
                ("now", "Current", "Study it now: it goes to the top of Current.", "→"),
                ("goal", "Goal", "Someday, in no order: what you'll get to later. It counts toward your list.", "↓"),
                ("finished", "Finished", "Watched or read already: a record, and still a source of sentences. Its "
                                         "words stop pushing your list around.", "↑"),
                ("ignore", "Ignore", "Never read its folder again, when the folder holds only this; otherwise it's "
                                     "taken out of your library. Your files stay where they are; Undo brings it "
                                     "back.", "←"))
SORT_UNDO = "Undo"
SORT_UNDO_TIP = "Bring back the last one you sorted.\n• Ctrl+Z"
SORT_REST = "Put the rest in…"
SORT_REST_TIP = "Every title still here in one place, at once. One Undo brings them all back."
SORT_DONE = "Done"
SORT_DONE_TIP = "Go on. Anything still here waits in New arrivals."
SORT_CLOSE_TIP = "Close. Anything still here waits in New arrivals.\n• Esc"
SORT_MORE = "and {n:,} more"
SORT_EMPTY = "All sorted."
SORT_PLACED = {"now": "{title} → Current", "soon": "{title} → Soon", "goal": "{title} → Goal",
               "finished": "{title} → Finished", "ignore": "{title} ignored"}
SORT_REST_PLACED = "{n:,} titles → {place}"
# Mado-O (alpha 8, Sonic 2026-10-31: "the ability to reset from the beginning")
SORT_OVER = "Start sorting over"
SORT_OVER_TIP = ("Everything you sorted here goes back to be sorted again, including the ones you ignored, and you "
                 "start from the top. Undo puts your sorting back.")
SORT_OVER_ASK = "Start sorting over?"
SORT_OVER_BODY = ("The {n:,} titles you sorted here go back to New arrivals, including the ones you ignored, and you "
                  "start again from the top. A title you've moved since stays where you put it. Undo puts your "
                  "sorting back.")
SORT_OVER_BODY_ONE = ("The title you sorted here goes back to New arrivals, even if you ignored it, and you start again "
                      "from the top. Undo puts it back.")
SORT_OVER_BODY_PLAIN = ("The {n:,} titles you sorted here go back to New arrivals, and you start again from the top. A "
                        "title you've moved since stays where you put it. Undo puts your sorting back.")
SORT_OVER_BODY_PLAIN_ONE = ("The title you sorted here goes back to New arrivals, and you start again from the top. Undo "
                            "puts it back.")
SORT_OVER_YES = "Start over"
SORT_OVER_YES_TIP = "Put them back to sort, and start from the top."
SORT_OVER_SAID = "{n:,} titles back to sort"
SORT_OVER_SAYING = "Putting {n:,} titles back to sort…"
SORT_OVER_SAYING_ONE = "Putting 1 title back to sort…"
SORT_OVER_SAID_ONE = "1 title back to sort"
SORT_KEYS_NAME = "Keys"

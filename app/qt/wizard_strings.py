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
CHECK_AGAIN = "Check again"
CHECK_AGAIN_TIP = "Look for Anki again, once it's open."
CHECKING = "Looking for Anki…"

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

# --- 3 · your shows --------------------------------------------------------------------------------------------------- #
SHOWS_TITLE = "Bring in what you'll watch and read"
ADD_CONTENT = "Add content…"
ADD_CONTENT_TIP = "Add shows, books and videos: a folder, files or subtitles.\n• Opens the Content Manager"
YOUTUBE = "YouTube link…"
YOUTUBE_TIP = "Bring in a YouTube or bilibili video's subtitles from its link."
SAMPLES = "Try it with samples first"
SAMPLES_TIP = "Not sure yet? Start with a few samples to see how it works.\n• Opens the Content Manager, which has them"
ROWS_NAME = "What's in your library"
ROW_COUNT = {"shows": ("1 episode", "{n:,} episodes"), "reading": ("a book", "{n:,} books"),
             "videos": ("1 video", "{n:,} videos")}
ROW_FILES = ("1 file", "{n:,} files")
ROW_LINE = "{count} · {folder}"
ROWS_MORE = "and {n:,} more"
COVERS = "Show covers"
COVERS_LINE = "Sends each show's name to AniList or TMDB. Nothing else."
COVERS_TIP = ("Covers for your shows, looked up by each show's name.\n"
              "• Turn it off any time: Settings")
COVERS_PICTURE_NAME = "A plain tile becomes the show's cover"
CONTENT_OPEN = "The Content Manager is open: what you add shows here when you close it."

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
DOTS = ("Anki", "AnkiWeb", "Anki Miner", "Its setup")
DOT_STATE = {"ok": "ready", "warn": "needs you", "off": "not yet"}
DOT_NAME = "{name}: {state}"

# --- 6 · your list ---------------------------------------------------------------------------------------------------- #
LEVEL_TITLE = "Your list"
LEVEL_LINE = "How much there is to learn, and how much of your shows you'll understand."
LEVEL = "Level"
AUTOMATIC = "Automatic"
AUTOMATIC_TIP = ("Surasura picks the level for you, about 850 words ahead, and moves it as you learn.\n"
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
NO_SHOWS = "Add a show first, and the numbers show here."
MAKING = "Making your list…"
MAKING_PCT = "Making your list… {pct} %"
NOT_STARTED = "Your list couldn't start: press Generate at the top when you're ready."

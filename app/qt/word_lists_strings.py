"""The strings of *Words to leave out* (W3.3 P10, n16: `app/qt/word_lists_window.py`) — its own table beside
`strings.py`, as a module keeps its `qt_strings.py`, until Settings' table (`settings_strings.py`) takes them in."""

WORD_LISTS_NAME = "Words to leave out"
WORD_LISTS_TIP = "Words every Generate leaves out: Ignore, Blacklist, known.\n• Paste text to pick."

WORD_LISTS_KINDS = (("ignore", "Ignore list", "Words you never want on your list: IgnoreList.txt"),
                    ("blacklist", "Blacklist", "Words you never want on your list: Blacklist.txt"),
                    ("known", "Marked known", "Words you marked known in Surasura: they count as known\n"
                                              "• Kept in your known words file, KnownWord.json"))
WORD_LISTS_KINDS_NAME = "Which list"

WORD_LISTS_SEARCH = "Search the words"
WORD_LISTS_SEARCH_NAME = "Search this list"
WORD_LISTS_COUNT = "{n} words"
WORD_LISTS_COUNT_ONE = "1 word"
WORD_LISTS_COUNT_SHOWN = "{shown} of {n} words"
WORD_LISTS_LIST_NAME = "The words on this list"
WORD_LISTS_LIST_TIP = "These words are left out, never counted unknown.\n• ✕ or Delete removes."
WORD_LISTS_ROW_LIST = "{word}\n• ✕ takes it off the list"
WORD_LISTS_ROW_KNOWN = ("{word}: ignored in your known words file (KnownWord.json)\n"
                        "• ✕ takes it off there, after asking")
WORD_LISTS_KNOWN_REMOVE = "Take {word} off your known words file?"
WORD_LISTS_KNOWN_REMOVE_BODY = ("Its ignored entry leaves KnownWord.json. Adding the word back puts it on the Ignore "
                                "list, not back in KnownWord.json.")
WORD_LISTS_KNOWN_REMOVE_YES = "Take it off"
WORD_LISTS_KNOWN_REMOVE_YES_TIP = "Remove the word's ignored entry from KnownWord.json"
WORD_LISTS_ROW_NAMES = "{word}: a name, left out while Ignore names is on\n• Turn Ignore names off to count names again"
WORD_LISTS_MARK_KNOWN = "{word}   · known words file"
WORD_LISTS_MARK_NAMES = "{word}   · name"
WORD_LISTS_REMOVE_MARK = "✕"
WORD_LISTS_EMPTY = "No words on this list yet: add one below, or paste text to pick its words"
WORD_LISTS_READING = "Reading the list…"
WORD_LISTS_READ_FAILED = "The list couldn't be read: {why}"

WORD_LISTS_ADD_FIELD = "Add a word"
WORD_LISTS_ADD_FIELD_NAME = "A word to add"
WORD_LISTS_ADD_FIELD_TIP = "Type a word, press Enter.\n• Several: separate with spaces."
WORD_LISTS_ADD = "Add"
WORD_LISTS_ADD_TIP = "Add the words typed beside it to this list"

WORD_LISTS_PASTE = "Paste text…"
WORD_LISTS_PASTE_TIP = ("Paste a sentence or a page: Surasura reads its words as your library does, "
                        "and you pick the ones to add\n• Click again to hide it")
WORD_LISTS_TEXT_NAME = "Text to pick words from"
WORD_LISTS_TEXT_HINT = "Paste a sentence or a page here"
WORD_LISTS_FIND = "Find words"
WORD_LISTS_FIND_TIP = "Split the text into words to keep or drop."
WORD_LISTS_FINDING = "Reading the text…"
WORD_LISTS_FIND_FAILED = "The text couldn't be read: {why}"
WORD_LISTS_FOUND_NONE = "No words to add in that text"
WORD_LISTS_CHIPS_NAME = "The words found: keep or drop each"
WORD_LISTS_CHIPS_TIP = "Each word found\n• Click or Space keeps or drops it."
WORD_LISTS_CHIP = {"new": "{spelling}\n• Kept: it goes on the list",
                   "known": "{spelling}: a word you know\n• Dropped: tick it to leave it out anyway",
                   "left_out": "{spelling}: already left out by your other list\n• Dropped: tick it to add it here too",
                   "listed": "{spelling}: already on this list"}
WORD_LISTS_ADD_KEPT = "Add {n} words"
WORD_LISTS_ADD_KEPT_ONE = "Add 1 word"
WORD_LISTS_ADD_KEPT_TIP = "Add the kept words to this list\n• As dictionary forms."

WORD_LISTS_ADDED = "Added: {words}"
WORD_LISTS_ALREADY = "Already on the list: {words}"
WORD_LISTS_REMOVED = "Taken off: {words}"
WORD_LISTS_NOT_THERE = "Not on the list any more: {words}"
WORD_LISTS_BACKUP = "a copy of the list as it was is in the trash folder in User Files"
WORD_LISTS_WRITE_FAILED = "Nothing was changed: {why}"

"""Every user string of the Settings page (W3.3; the window's spec 05 §5.7, §5.12: one table, so the app can be
translated later) — Settings' own table beside `strings.py`, as a module keeps its `qt_strings.py`. No Qt.

Settings keeps its words (C-scope Q6): the old mock's labels and one-line help (`mock-g16` `sectionBody`); where the
mock's words carry a meaning 2.4 changed (A5: the one-kanji words, Junban's unlisted cards), 2.4's meaning in the mock's
voice. A tooltip is 2.4's own where 2.4 had one, else the help line. Help is one line, never an essay; no fixed seed
numbers (N5). `app/qt/settings_catalog.py` names each row's strings by its row id.
"""
from app.connect.settings_values import WORDS as MINE_WORDS   # *Words to make cards from*: Connect's own words
from app.practice import NAME as PRACTICE_NAME       # the practice chat's name (A6): one place, app/practice.py

# --- the page ----------------------------------------------------------------------------------------------------- #
SEARCH_PLACEHOLDER = "Search settings"
SEARCH_KEY_TIP = "Press / to search"
SEARCH_NONE = "No setting matches “{q}”."
MORE_OPTIONS = "More options · {n}"
FEWER_OPTIONS = "Fewer options"
CHANGE = "Change ›"
CHANGE_TIP = "Go to {section}"
COMING_LATER = "coming later"
COMING_WITH_HATO = "coming with hato"
SET_UP_MINER = "Set up Anki Miner ›"                                  # row 13: the needs-Anki-Miner line's door
SET_UP_MINER_TIP = "Go to Anki Miner in Connections: install it, or show Surasura where it is"
CONNECTED = "connected"
NOT_CONNECTED = "not connected"
CHECK = "Check"
CHECK_TIP = "Checks AnkiConnect, the deck and the note type"
INSTALLED = "installed · {version}"
NOT_INSTALLED = "not installed"
OPEN = "Open"
LEVEL_AUTOMATIC = "Automatic"
LEVEL_AUTOMATIC_TIP = "Surasura picks the level for you: the commonest one whose list holds at least {n} words"
LEVEL_READOUT = "≈{words} words · {coverage}% of your content · every {hours} hours"    # S4: never "% known"
NEW_CARDS_FROM_ANKI = "· from Anki (deck: {deck})"
CHANGE_IN_ANKI = "Change in Anki…"
CHANGE_IN_ANKI_TIP = "Asks first, naming the deck"
MINE_LINE_BEFORE = "the top"
MINE_LINE_AFTER = "files"
SOON_LINE_AFTER = "files"
RULE_FROM = "From"
RULE_ADD = "+ rule"
RULE_ADD_TIP = "Add a rule: a source, and where its arrivals go"
FOLDER_ADD = "+ folder"
FOLDER_ADD_TIP = "Choose a folder"
RANGE_TO = "to"
UNIT_CHARACTERS = "characters"
UNIT_PER_WORD = "per word"
UNIT_TIMES = "times"
UNIT_WORDS = "words"
UNIT_SECONDS = "seconds"
UNIT_PERCENT = "%"
README_POINTER = "Each source's files and licence are in README's Data Credits."
OFFER_AGAIN = "Offer {version} again"
OFFER_AGAIN_TIP = "You chose Skip this version. Offer it again as a one-click update."
SEARCH_KEY = "/"
SEARCH_NAME = "Search settings"
NAV_NAME = "Settings sections"
MORE_TIP = "Shows this section's other settings, the ones most people never change"
FEWER_TIP = "Hides this section's other settings again"
LINK_OPEN = "Open ↗"
HOW_PARSING_URL = "https://github.com/SonicSandbox/surasura/blob/main/docs/How%20Parsing%20Works.md"
DISCORD_URL = "https://surasura.dev/app/discord"      # the server's invite, by redirect (in the browser, never an app call)
WEBSITE_URL = "https://surasura.dev"                  # Surasura's website (in the browser, never an app call)
ISSUES_URL = "https://github.com/SonicSandbox/surasura/issues"
LINK_URLS = {"how_parsing_works": HOW_PARSING_URL, "discord": DISCORD_URL,   # a link row's page, by its id
             "website": WEBSITE_URL}
FOLDER_PICK_TITLE = "Where videos are looked for"

# --- the controls' own words (settings_controls.py; moved here from its top, W3.3 P3) ------------------------------ #
ADD = "Add"                                      # an empty bed's words when the page names none
REMOVE_NAME = "Remove {item}"                    # a list tablet's ✕, for screen readers (the accessible description)
CROSS = "✕"
TICK = "✓"                                       # a multi-pick tablet's mark when lit (Q31: never a choice's vein)
PICKED_NONE = "None picked"                       # a set of tablets with none picked, for screen readers
STATUS_NAME = "{name}: {words}"                  # the status mark, for screen readers

# --- the sections (the mock's order, with Language & Parsing after Level: 05 §5.7) --------------------------------- #
SECTIONS = {
    "setup": "Your setup", "known": "Known words", "anki": "Anki & mining", "junban": "Junban — card order",
    "backfill": "Backfill — fill your cards", "level": "Level — rarity", "parsing": "Language & Parsing",
    "content": "Content", "arrivals": "New arrivals", "connect": "Connections", "reading": "Journey",
    "sentences": "Sentences", "export": "Export", "app": "App",
}

# --- the group names inside a section ------------------------------------------------------------------------------ #
GROUPS = {
    "counts_as_known": "What counts as known", "from_library": "Cards from your library",
    "in_anki": "Cards already in Anki", "anki": "Anki", "names": "Names", "words_phrases": "Words and phrases",
    "houseki": "Houseki tools", "not_on_list": "Cards not on your list",
}

# --- the doors (a window, or an action, a row opens) ---------------------------------------------------------------- #
DOORS = {
    "anki": ("Anki…", "Choose your decks and the field each card's word is in"),
    "migaku": ("Migaku", "Import from Migaku"),
    "jiten": ("Jiten", "Import from Jiten"),
    "apkg_known": (".apkg", "Import an Anki deck file"),
    "word-lists": ("Ignore list · Blacklist", "Opens your Ignore list and Blacklist"),
    "junban": ("Preview order",
               "Shows the new order and why, before anything moves; Undo the last reorder is there too"),
    "put-back": ("Put Anki back…", "Puts Anki's new cards back the way they were before Surasura first changed them"),
    "backfill": ("Preview", "Shows exactly what goes into each card; Fill and Restore are there too"),
    "extract": ("Extract…", "EPUBs and Anki decks, split into parts"),
    "youtube-downloader": ("YouTube…", "Download a video's captions straight into your library"),
    "youtube-preview": ("Preview a video…", "Score a video against your words before you add it"),
    "koe": ("Speech settings…", "Set the API key, voice and delivery for spoken sentences"),
    "sentence-dictionary": ("Export", "Exports Surasura Corpus for Yomitan"),
    "frequency-lists": ("Add…", "Add or remove a frequency list"),
    "library-folders": ("Manage folders…", "Opens your folders: stop reading one, read a skipped one again, or look "
                                           "in them all again"),
}
# A row whose door says something else than the opener's own words: row id -> {opener: (label, tooltip)}
ROW_DOORS = {
    "junban_scope": {"junban": ("Choose the deck…", "Opens Junban’s window, where the deck is chosen")},   # a6 #9
    "junban_backfill_cards": {"backfill": ("Choose the deck…", "Opens Backfill’s window, where the deck is "
                                                               "chosen")},                                # W4.1
    "backfill_fields": {"backfill": ("Fields…", "Opens Backfill, where each fill's field and each note type's "
                                                "language are set")},
}

# --- the rows: row id -> (label, one-line help, tooltip, search words) --------------------------------------------- #
ROWS = {
    # Your setup (five live summaries; each line is P4's)
    "setup_known": ("Known words", "", "Go to Known words", "known words sync anki import"),
    "setup_anki": ("Anki", "", "Go to Anki & mining", "anki connected deck waiting"),
    "setup_mining": ("Mining", "", "Go to Anki & mining", "mining mine cards top"),
    "setup_level": ("Level", "", "Go to Level", "level band automatic"),
    "setup_cards": ("Cards in Anki", "", "Go to Junban", "cards in anki ordered filled junban backfill"),

    # Known words
    "known_road": ("Your known words come from",
                   "Anki: a word counts once you’ve studied its card, and stays in sync. Import: a one-time list from "
                   "Migaku, Jiten or an Anki deck file — it replaces what’s there, and a backup is kept",
                   "Where your known words come from", "source where they come from anki import migaku jiten apkg"),
    "anki_decks": ("Decks", "", "The decks your known words come from; change them in the Anki window",
                   "decks anki fields word field"),
    "anki_sync_auto": ("Keep in sync while Anki is open", "",
                       "When Anki is open, Surasura adds new known words on its own — at start-up and when you come "
                       "back to it", "sync automatically anki open"),
    "anki_auto_generate": ("Re-generate when new words come in", "In the background, at most every 10 minutes",
                           "When a sync brings in words you now know, Generate runs on its own in the background, so "
                           "your list is current — without opening the report. At most every 10 minutes, and never "
                           "while an import or a Generate is running", "generate automatically new known words"),
    "known_import": ("Import from", "Replaces your known words — a backup is kept",
                     "Import your known words from Migaku, Jiten or an Anki deck file", "import migaku jiten apkg"),
    "words_to_leave_out": ("Words to leave out", "Never suggested: your Ignore list and Blacklist",
                           "Opens your Ignore list and Blacklist", "ignore blacklist leave out never suggested"),
    "use_every_core": ("Use every core", "Reads a big library faster; the computer is busier meanwhile",
                       "Off: reading and copying a library uses half your computer's cores, so it stays quick to use. "
                       "On: every core — a first read of thousands of books ends sooner", "cores speed faster cpu"),
    # a7 (DIAGNOSIS 3): this row and *Count as known in Anki* under it answer one question two ways — each says so
    # (A7S-1: the sync reads studied cards only — `anki_sync.scope_query`'s `-is:new`; the signal reads new ones too)
    "anki_sync_include_suspended": ("Count suspended cards as known", "Cards you studied, then suspended",
                                    "Cards you studied and then suspended count as known, whenever you suspended "
                                    "them. Off by default: a suspended card is often one you struggled with. New cards "
                                    "you suspend never count here — for those, use Count as known in Anki below",
                                    "suspended known"),
    "known_from_anki": ("Count as known in Anki",
                        "A card counts only when it is in every state you pick, all at once",
                        "Suspend (or mark, or flag) a card in Anki to say “I know this”: its word turns known at the "
                        "next sync, and you can undo it. A card counts only when it is in every state you pick — "
                        "Suspended + Marked counts only cards both suspended and marked. Cards already suspended are "
                        "asked about once. New cards count too. None picked: off. Count suspended cards as known, "
                        "above, counts every studied card you've suspended, whenever",
                        "known from anki suspended marked flag"),

    # Anki & mining
    "anki_connection": ("Connection", "Through the free AnkiConnect add-on", "Whether Surasura reaches Anki now",
                        "ankiconnect status connection"),
    "new_cards_a_day": ("New cards a day",
                        "Anki’s own setting for {deck}. Surasura reads it, and changes it only when you say so",
                        "Anki's new cards a day for the deck, and the pace behind the “reach your target in N days” "
                        "line",
                        "new cards a day anki per day limit deck pace words per day"),
    "connect_enabled": ("Make cards for me",
                        "Episodes you place at the top of Current get Anki cards made by Anki Miner, by themselves",
                        "Surasura Connect: when you place an episode at the top of Current, Anki Miner makes its cards "
                        "and Surasura orders them. Needs Anki and Anki Miner. Nothing placed before you turn it on",
                        "connect make cards mine automatically anki miner"),
    # row 13 (laptop fixes): *Make cards for me* while Anki Miner isn't found (and Connect is off)
    "connect_needs_miner": ("Make cards for me", "Needs Anki Miner: set it up in Connections",
                            "Surasura Connect makes your cards with Anki Miner. Once it is installed, this switch "
                            "appears here", "connect make cards mine automatically anki miner needs"),
    "connect_mine_words": ("Words to make cards from",
                           "“Your list” uses i+1 lines where it can and takes the other words too. “Only i+1” skips "
                           "them",
                           "Which words of an episode become cards. Your list: every unknown word on your list, in "
                           "the list's order, each on an i+1 line when it has one. Only i+1: only words with an i+1 "
                           "line, on your list or not",
                           "words to make cards from mine mode which words all unknown i+1 list"),
    "mine_line": ("Mine automatically", "The files at the top of Current mine themselves the moment they’re placed",
                  "How many files at the top of Current mine themselves", "auto top mines itself mine line"),
    "connect_send_grammar": ("Send grammar words", "Particles and endings get cards too",
                             "Grammar words (particles, endings) get cards too. Names follow Ignore names in Language "
                             "& Parsing", "grammar particles endings send"),
    "connect_open_anki": ("When Anki is closed", "New cards wait until you open Anki — or Surasura opens it for you",
                          "When you open Surasura and Anki is closed, Surasura can open it, so your phone's reviews "
                          "come in and your cards get made and ordered", "closed open anki start session"),
    "connect_backlog_cap": ("Keep up to", "new cards waiting in Anki, for this language. 0: no limit",
                            "Surasura makes cards while fewer new cards wait in Anki for this language: yours and "
                            "Surasura's. Suspended cards never count. 0: no limit",
                            "cap backlog waiting keep up to limit"),
    # a7 (DIAGNOSIS 5): an extra, under More options — the library's folders are always searched
    "connect_video_folders": ("More video folders",
                              "Your library’s own folders are always searched. Add one only if your videos live "
                              "somewhere else",
                              "Videos are found beside their subtitles and in your library’s folders, with their "
                              "subfolders. Add a folder here (for this language) only for videos kept outside them",
                              "video folders pair moved where videos looked for more"),
    "connect_trust_timing": ("Trust my subtitles’ timing",
                             "When nothing on this PC can check them, mine at the subtitles’ own times",
                             "Surasura mines an episode by itself only once hato or tsubasa has checked its subtitles "
                             "play in time with the video. With neither on this PC, every episode waits for Mine "
                             "anyway. Turn this on if your subtitles are already synced. hato’s untimed subtitles "
                             "still wait", "trust timing synced subtitles not timed tsubasa"),
    # Q29: one choice — where your own cards go — and the tag that marks them under it
    "junban_order_all": ("Your own cards", "The cards you make yourself, never marked or suspended as not on your list",
                         "First: the cards you made yourself go ahead of the ones Surasura Connect makes, in the order "
                         "you made them. In your list's order: they go among Connect's, by your list. Either way they "
                         "are never marked or suspended as not on your list", "own cards first order all list manual "
                         "yomitan"),
    "junban_own_tag": ("Their tag", "Every card carrying it is yours too, whenever you made it",
                       "Type a tag (immersion): every card carrying it counts as your own, even one made before "
                       "Connect's first card, so it goes as chosen above and is never suspended. Empty: your own cards "
                       "are the ones you made after Connect's first", "own cards tag immersion manual yomitan"),
    "anki_sync_delay_min": ("Sync Anki after tomorrow's cards change",
                            "Surasura asks Anki to sync before its first write of a session, then this long after a "
                            "change",
                            "Surasura asks Anki to sync with AnkiWeb before its first write of a session, so reviews "
                            "from your phone arrive first. After a re-order that changes tomorrow's cards it syncs again "
                            "this long after, while the automation or Connect is on. Otherwise Anki's own sync on close "
                            "sends it. Only your own AnkiWeb account, through Anki",
                            "sync ankiweb delay minute phone"),
    "automation": ("Run things by themselves",
                   "Off stops Anki's re-order as you move, the background Generate and the automatic re-order",
                   "On by default. Turn it off only on a slow computer: Backfill's automatic step and the automatic "
                   "Generate keep their own switches", "automation automatic background off slow"),
    "journey_settle_s": ("Wait before the background Generate", "After your last move",
                         "Seconds after your last move before your journey updates in the background",
                         "journey settle wait seconds background generate"),
    "journey_settle_battery_s": ("…on battery", "The same wait while a laptop runs on its battery",
                                 "Seconds after your last move before your journey updates, on battery",
                                 "journey settle battery laptop seconds"),
    "connect_anki_miner_profile": ("Anki Miner profile", "The Anki Miner profile Connect mines with",
                                   "The Anki Miner profile Connect mines with", "anki miner profile"),
    "anki_connect_url": ("AnkiConnect address", "Only this computer’s own address (127.0.0.1) is used",
                         "AnkiConnect on this computer only: any other address is refused", "address url ankiconnect"),

    # Junban
    "enable_junban": ("Order your backlog with Surasura",
                      "Moves new cards only — reviews and learning cards are never touched",
                      "Shows 順, which reorders the new cards already in your Anki into Surasura's learn order",
                      "junban reorder order backlog enable"),
    "junban_scope": ("Which cards", "This deck is chosen in Junban’s window", "This deck, or every deck with new cards",
                     "scope deck all decks"),
    "junban_order": ("Order", "", "As you'll meet the words in your content, or by leverage first",
                     "order leverage meet content priority"),
    "junban_unlisted": ("Cards too rare for your list go",
                        "After your list, mixed in where you meet them, or at the back",
                        "After it: every word on your list comes first, the rarer cards after it by their own sentence. "
                        "Mixed in: each where your journey meets it, among the list's words. At the back: in their "
                        "own order, behind the list's", "list first rare unlisted mixed back"),
    # Q31: switches that work together, never one pick-one row
    "junban_phrases": ("Idioms and set phrases go with your list",
                       "A phrase card you meet as often as your list's words is placed as if on it",
                       "On: an idiom or set phrase card (気がつく) your library meets as often as your list's words is "
                       "placed among them, as if on your list. Off: it goes by its own sentence, with the rarer cards",
                       "phrases idioms set phrase list first"),
    "junban_ready_first": ("i+1 first: bring the word a card's sentence needs right before it",
                           "A card's new word in its sentence gets its card first",
                           "On: when a card's own sentence holds a word of your list that comes after it, that word's "
                           "card is brought right before it when it is i+1 there; otherwise the card waits with the "
                           "cards of more new words. Off: your list's order alone", "first i+1 ready sentence needs"),
    "junban_later_tag": ("Tag them Surasura::later", "Placed after your list, and marked. Restore takes it back",
                         "Cards not on your list get the tag Surasura::later. Restore takes it back off",
                         "not on list later tag"),
    "junban_later_flag": ("Flag them purple", "", "Cards not on your list get Anki's purple flag. Restore takes it off",
                          "not on list later flag purple"),
    "junban_later_suspend": ("Suspend them", "Tagged too, so you can always find them",
                             "Cards not on your list are suspended, and tagged Surasura::later too. Restore puts each "
                             "back", "not on list later suspend"),
    "junban_auto_reorder": ("Reorder by itself after Generate", "",
                            "After a Generate, and when you come back to Surasura, the deck saved in Junban is "
                            "reordered on its own", "auto reorder automatic generate"),
    "junban_auto_actions": ("…and tag, flag or suspend then", "The automatic reorder applies Junban's marks too",
                            "Off, the automatic reorder moves cards only; on, it applies everything Junban has saved",
                            "auto actions tag flag suspend"),
    "junban_door": ("", "", "Preview order · Undo the last reorder", "preview restore undo order"),
    "put_back": ("Put Anki back", "The way it was before Surasura first changed it",
                 "Puts Anki's new cards back in the order they had before Surasura first changed them, and takes "
                 "Surasura's tags, flags and suspensions off", "put back undo restore first touch"),
    "junban_write_frequency": ("Write Surasura’s rank into a field", "Beside JPDB’s, never instead of it",
                               "Writes the word's place in your list into the note, as one more entry in the frequency "
                               "list. Nothing already there is removed", "frequency rank field write"),
    "junban_frequency_field": ("Field", "", "Which field holds it. A field a note does not have is skipped",
                               "frequency field"),
    "junban_write_freqsort": ("…and overwrite the FreqSort sort number", "Replaces the number Anki’s browser sorts by",
                              "Replaces the single number Anki's browser sorts by. Restore puts it back. Off unless you "
                              "want exactly this", "freqsort sort number overwrite"),
    "junban_tag_markers": ("Tag ✦ ⚖ 📖 markers", "As sub-tags of the tag below",
                           "Also adds the word's markers as sub-tags — Surasura::star, ::lopsided, ::reading — so you "
                           "can build a filtered deck on one of them", "markers star lopsided reading tag"),
    # IK-4: glyph tablets again — a tick on each one picked (Q31's rule), never a choice's vein
    "junban_only_markers": ("Only words marked", "None picked: every word",
                            "Reorder only the words carrying one of these marks; the rest keep their order, at the "
                            "back. While one is picked, Idioms and set phrases and i+1 first don't apply",
                            "only markers star lopsided reading filter high leverage"),
    "junban_tag": ("Tag the notes I move", "Empty: no tag",
                   "Adds this tag to every note whose card moved. Restore takes it back off", "tag notes moved"),
    "junban_chunk_size": ("Cards per write", "", "How many cards go to Anki in one request", "chunk cards per write"),

    # Backfill
    "backfill_patterns": ("Fill パターン", "How the word is used",
                          "Backfill fills each card's パターン field: how the word is used", "patterns fill パターン"),
    "backfill_sentence": ("Fill 例文", "Two more sentences from your own content",
                          "Backfill fills each card's 例文 field: two more sentences from your own content",
                          "sentences examples fill 例文"),
    "junban_backfill_cards": ("Which cards", "The deck is chosen in Backfill’s window",
                              "All: every card except new ones whose word you know. New only: cards you haven't "
                              "studied yet", "deck cards new all"),
    "junban_backfill_replace": ("Replace what’s already in the field", "Off: only empty fields are filled",
                                "Overwrite what's in the field. Restore puts it back", "replace overwrite"),
    "junban_auto_backfill": ("Fill new cards by itself", "After each reorder",
                             "After a reorder, fill the new cards' empty fields — never a studied card, never a filled "
                             "field", "auto backfill automatic fill"),
    "backfill_door": ("", "", "Preview · Fill · Restore", "preview fill restore"),
    "backfill_fields": ("Fields, by note type", "Found by name; otherwise choose",
                        "Which field each fill goes in, and each note type's language", "fields note type lapis"),

    # Level
    "level": ("Level", "", "Your level: your list holds the words at least as common as it",
              "level difficulty band rarity automatic"),
    "strategy": ("Or aim for a coverage %",
                 "Instead of a level: include words until your content reaches this share",
                 "Level, or a target coverage of your content", "coverage mode strategy"),
    "target_coverage": ("Coverage", "The share of your content you aim to know", "Target coverage, in percent",
                        "coverage percent target"),
    "show_words_per_day": ("Show target days on your journey", "", "Show 'Target Days' in your report",
                           "target days words per day"),
    "min_count": ("A word must appear at least", "", "Fewer appearances than this and a word is never listed",
                  "min count appear at least"),
    "minutes_per_file": ("Minutes per file", "For the “every N hours” estimate",
                         "How long a file takes you, for the “every N hours” estimate", "minutes per file"),
    "auto_max_words": ("Automatic keeps at least", "Words ahead of you",
                       "With Automatic on: the commonest level whose list holds at least this many words",
                       "automatic max words ahead"),

    # Language & Parsing
    "zh_script": ("Script", "Chinese shown as each file writes it, or all in one script",
                  "Read all Chinese content and known words in one script, so 学习 and 學習 count as one word. Your "
                  "files are not changed", "script simplified traditional chinese"),
    "paren_readings": ("Readings in parentheses",
                       "Kana in ( ) right after kanji in a book, as in 山田(やまだ), are read as that kanji’s reading "
                       "and left out, like ruby",
                       "Drops a kanji's reading written after it in brackets, so it isn't counted twice. Katakana "
                       "there is often a note, so it stays by default", "readings parentheses ruby kana book"),
    "names_katakana": ("Keep katakana names whole", "A katakana name no dictionary spells stays one word, not pieces",
                       "A katakana name no dictionary lists stays one word: ミロ + ナイ → ミロナイ. Repeated sounds and "
                       "laughter stay apart", "names katakana whole"),
    "names_recurring": ("Names the library keeps using",
                        "A katakana run your library keeps using as one word is one word",
                        "Ordinary katakana words your content keeps using together, and hardly ever apart, become one "
                        "word. Takes effect at the next Generate", "names recurring library"),
    "names_kanji": ("Kanji names (JMnedict)",
                    "A person’s name from JMnedict that your library uses again and again is one word",
                    "A person's name cut into kanji is one word when JMnedict lists it and your library keeps using "
                    "it: 奏 + 汰 → 奏汰. Takes effect at the next Generate", "names kanji jmnedict person"),
    "names_work_terms": ("A work’s own terms",
                         "A story’s own kanji words, used again and again as one, are one word. Auto-generated "
                         "captions don’t count",
                         "Kanji words a story makes up — 斬魄刀, 写輪眼 — become one word when your library keeps "
                         "using them together. A dictionary word never joins this way", "terms work story kanji"),
    "ignore_names": ("Ignore names",
                     "Names leave your list and never count as new in a sentence. Off: you learn them like any word",
                     "On: people's names (田中, ミロナイ) are ignored words — off your list, never unknown in a "
                     "sentence. Takes effect at the next Generate", "ignore names"),
    "phrases_and_titles": ("Phrases and titles as one word", "予想通り and 元首相 are one word. Off: their parts, 予想 + 通り",
                           "On: 予想通り, こと自体, 元首相 and もののけ姫 each count as one word. Off: they count as "
                           "their parts", "phrases titles compound"),
    "pronoun_bases": ("Pronouns with a suffix as one word", "何様 and お前さん are one word. Off: 何 + 様",
                      "On: 何様, 俺様, お前さん and それなり each count as one word. Off: they count as their parts",
                      "pronouns suffix"),
    "phrase_rows": ("Idioms as rows",
                    "Set phrases you meet often get rows of their own: 気がする, 腑に落ちる. Their words keep their rows",
                    "Adds dictionary phrases your library uses often as rows of their own, each ready once you know "
                    "the words in it", "idioms set phrases rows"),
    "exclude_single": ("List one-kanji words only when they’re dictionary words",
                       "A one-kanji word is listed where it stands on its own as a word, as 手 and 顔 do. Off: every "
                       "one-character word is listed",
                       "Particles and endings (は, た) and pieces of names or made-up terms stay off your list. Words "
                       "like 手, 目 and 顔 are listed", "one kanji single character exclude"),
    "how_parsing_works": ("How parsing works", "", "Every rule, with examples — opens in your browser",
                          "how parsing works guide examples"),

    # Content
    "target_language": ("Language", "", "The language you're learning", "language japanese chinese"),
    "soon_line": ("Soon starts after",
                  "For now a count · later worked out from how much you watch a day, about 3 weeks in",
                  "How many files of Current come before Soon", "soon weeks after soon line"),
    # W-1 (Sonic 2026-10-22, Q4): a library's own option, beside its Soon line (settings_store.py)
    "keep_watched": ("Keep studying watched episodes",
                     "Off: when you mark an episode watched, its words leave your list and their cards move back.",
                     "On: an episode you mark watched keeps its words on your list and its cards where they are\n"
                     "Not the same as Study its cards first, which keeps one show's cards at the front.",
                     "watched episode stone keep study list"),
    "library_folders": ("Library folders", "Read where they are: Surasura keeps its own copy of their text and "
                                           "looks in them again for new episodes",
                        "The folders Surasura reads where they are", "library folders source read where they are "
                                                                     "stop reading look again manage skipped "
                                                                     "read again"),
    # A7O-6 (Sonic 2026-10-30): named for what it does — the same files, the order cleared (was *Start a fresh library*)
    "fresh_library": ("Sort my library again",
                      "Clears your order and tiers into a backup and reads every folder again into Current",
                      "Clear your order and read your folders again; the old order is kept in a backup",
                      "sort library again order tiers fresh reset start over clear read again"),
    "split_books_by": ("Split books by", "Each book you add: its chapters, each cut into parts; or even parts across "
                                         "the book. Books already in keep their parts",
                       "How a book is cut into parts when you add it", "split books chapters even parts epub"),
    "split_length": ("Split books into parts of", "EPUBs and Anki decks, when you extract them",
                     "The character limit for each part when a file is split", "split epub length"),
    "enable_youtube_transcripts": ("YouTube transcripts", "Download a video’s captions straight into your library",
                                   "Show the transcript downloader (YouTube and bilibili.tv)", "youtube transcripts"),
    "enable_youtube_preview": ("YouTube preview", "Score a video against your words before you add it",
                               "Show 'Preview against library', and keep the library's word counts ready for it",
                               "youtube preview score"),
    "content_doors": ("Add from", "", "Extract a book or a deck, or download from YouTube",
                      "extract youtube download preview"),

    # New arrivals
    "placing_rules": ("Where new arrivals go", "A show's next episode joins it; the rest wait here, in New arrivals",
                      "A source, and where its arrivals go", "where new arrivals go rules source hato youtube channel "
                      "wait top"),

    # Connections
    "anki_miner": ("Anki Miner", "Makes your cards from your own videos. Free, made by Zero.\n"
                                 "He's awesome. Please give him some love :)",
                   "Anki Miner's state, and what it still needs", "anki miner install setup"),
    "hato": ("hato", "Finds subtitles for your shows, and sends new episodes to New arrivals",
             "Whether hato is installed", "hato install houseki suite subtitles"),
    "practice_ai": (f"{PRACTICE_NAME} — practise with your AI",
                    "Practise your words with your AI. What it's told goes to that AI's company",
                    "Copy the setup for your AI app, then paste it to your AI. A short story is a good first try",
                    "piyo ぴよ practice practise ai claude codex desktop mcp chat tutor copy setup"),
    "practice_keep_rounds": ("Keep practice rounds",
                             "Your rounds stay on this computer so you can do one again, and what you ask your AI to "
                             "keep comes back in later rounds. Off: nothing is kept",
                             "Keep each practice round in your User Files, to do again and to build on",
                             "practice rounds keep save again history context ai"),
    "jimaku": ("jimaku", "Subtitles for anime. Its key will come from hato", "jimaku's key, through hato",
               "jimaku key api subtitles"),
    "anilist": ("AniList", "Brings the shows on your AniList into New arrivals, and fetches their subtitles. Never video",
                "AniList", "anilist anime list account subtitles"),
    "more_from_houseki": ("More from Houseki",
                          "Each tool works on its own, and does more alongside the others. New ones appear here as "
                          "they’re released", "More tools from Houseki", "houseki suite install tools"),

    # Journey
    "theme": ("Look", "", "The report's look", "theme look dark flow report"),
    "open_app_mode": ("Open in its own window",
                      "Its own browser window, so Yomitan and your other tools still work on it. Off: a tab",
                      "Open the report in its own browser window", "open window tab browser"),
    "source_display": ("Where a sentence came from", "", "Show which file each example sentence came from",
                       "source badge file name"),
    "word_search_enabled": ("Word lookup button (⌕)", "More real sentences from Nadeshiko",
                            "A search icon beside each word, opening more real sentences on Nadeshiko",
                            "word lookup search nadeshiko"),
    "anki_backlog_on_generate": ("Label words already in Anki", "A word whose card is already waiting in Anki is marked",
                                 "Mark each word that already has a new card waiting in your Anki decks",
                                 "label backlog anki waiting card mark"),
    "inline_completed_files": ("Show ‘Target met’ in place", "Met files keep their order instead of moving down",
                               "Keep met files in order instead of moving them down", "target met inline completed"),
    "hide_audio_button": ("Hide the audio button", "No speaker icon on the report’s sentences",
                          "Hide the speaker icon in the report", "audio button speaker hide"),
    "word_search_category": ("Lookup examples from", "", "Which kind of sentences the lookup opens",
                             "lookup nadeshiko category anime"),
    "zen_limit": ("Zen mode shows", "", "How many words Zen mode shows", "zen limit"),
    "enable_koe": ("Speak sentences (Gemini)", "On your own key; each sentence goes to Google to be spoken",
                   "Click a sentence's source badge in the report to hear it read aloud. Needs a Gemini API key and "
                   "sends that sentence to Google", "speech speak koe gemini voice"),
    "koe_door": ("Speech settings", "The key, voice and delivery", "Set the API key, voice and delivery",
                 "speech settings voice key"),

    # Sentences
    "sentence_length": ("Length", "Shorter or longer ones are still used, just later",
                        "Preferred length for example sentences", "length chars sentence"),
    "max_contexts": ("Up to", "", "Most example sentences per word", "max sentences per word"),
    "ensure_audio_example": ("Always include one with audio", "",
                             "If none of a word's examples came from a video, the last one does — so you can always "
                             "study it by ear", "audio example video"),
    "only_i_plus_one": ("Only i+1 sentences", "Every other word already known",
                        "Swaps a word's media sentence for an i+1 example when it isn't already i+1", "i+1 only"),
    "max_chars": ("Never longer than", "", "Longer sentences are never examples (a word's own is kept)",
                  "hard cap max chars"),

    # Export
    "sentence_dictionary": ("Sentence dictionary for Yomitan",
                            "Up to eight of your own sentences beside every word you hover",
                            "A Yomitan dictionary of the best sentences for every word in your library",
                            "yomitan corpus sentence dictionary"),
    "export_frequency_list": ("Frequency list", "Migaku · Yomitan · text",
                              "Export Surasura's frequency list for Migaku or Yomitan", "frequency list export"),
    "export_reading_words": ("Reading words", "Words you’ll read more than hear",
                             "A Yomitan list of words you'll read but hardly ever hear", "reading words export"),
    "export_sentence_list": ("Sentence list for Anki", "A CSV of your list with its sentences",
                             "An Anki-ready CSV with sentences from your report", "csv sentence list anki export"),
    "sentence_dictionary_source": ("Show where each sentence came from", "In the Yomitan popup",
                                   "A short file name under each sentence in the Yomitan popup",
                                   "source sentence dictionary"),
    "frequency_lists": ("Add a frequency list", "Shows its tier beside each word", "Add or remove a frequency list",
                        "add frequency list"),

    # App
    "text_size": ("Text size", "Applied when Surasura restarts: it offers to at once", "The window's text size",
                  "text size font bigger smaller read zoom restart"),
    "app_motion": ("Motion",
                   "Follow Windows: as Windows’ Show animations is set. Reduced: nothing slides, rows jump into place, "
                   "short fades stay", "How much the window moves", "motion animation reduced slide fade"),
    "auto_update_enabled": ("Update automatically", "One click for small releases",
                            "Offer one-click in-app updates for small releases. Big ones always download by hand",
                            "update automatic"),
    "telemetry_enabled": ("Anonymous usage counts", "No words, files or content — ever",
                          "Send anonymous usage counts", "telemetry anonymous usage"),
    "logs": ("Processing log", "", "Opens the logs folder", "log logs processing"),
    "data_credits": ("Data credits", "The dictionaries and word lists Surasura ships or is built from, each with its "
                     "licence", "Every data source, with its licence",
                     "data credits licence license jmdict jmnedict unidic cedict jpdb jiten"),
    "discord": ("Join the Surasura Discord", "Questions, help, and a place to report a problem",
                "Opens Surasura's Discord server in your browser", "discord community help chat support join server"),
    "website": ("Surasura website", "Surasura's home page, surasura.dev", "Opens surasura.dev in your browser",
                "website homepage home page site web download surasura.dev"),
    "version": ("Version {version}", "", "Opens the data folder", "version data folder"),
    "set_up_again": ("Set up again", "Walks through the first steps again", "Opens the setup again",
                     "set up again wizard setup"),
    "settings_file": ("Your settings", "Save them to a file, or bring them in from one: for the next version or a new "
                      "computer", "Export or import every setting",
                      "settings export import save backup move new computer pc file"),
    # --- W3.2 L3: Connections' covers (the window's spec 01 §1.3: the switch says in one line what is sent)
    "covers_download": ("Download covers", "Sends each show's AniList id or name to AniList, and a video's id to "
                        "YouTube. Nothing else.", "Fetch your shows' covers from AniList (YouTube videos: their own thumbnail)",
                        "covers download pictures anilist thumbnails posters"),
    "remove_downloaded_covers": ("Remove downloaded covers", "The pictures you chose and those beside your files stay",
                                 "Delete every cover Surasura downloaded; pictures beside your files come back by "
                                 "themselves", "remove delete downloaded covers cache pictures"),
    # --- end W3.2 L3
}

# *Count as known in Anki* with two states or more picked: its line names them (`settings_catalog.help_line`)
KNOWN_ALL_OF = "Counts only cards that are {states}, all at once"
KNOWN_FLAGS = "A card has one flag at a time: {flags} counts no card"           # two flags picked (A7S-7)

# Backfill's fills by name (`junban_backfill_fills`' values): its two switches, and Your setup's line
FILLS = {"patterns": "パターン", "sentence": "例文"}

# --- the choices: row id -> {value: label}; choice cards also have a line under each -------------------------------- #
OPTIONS = {
    "known_road": {"anki": "Anki", "import": "Import a list"},
    "connect_mine_words": {value: label for value, label, _line in MINE_WORDS},
    "connect_open_anki": {False: "Wait for me", True: "Open Anki for me"},
    "junban_order_all": {False: "First, in the order you made them", True: "In your list’s order"},
    "known_from_anki": {"suspended": "Suspended", "marked": "Marked", "flag:1": "Flag 1 (Red)",
                        "flag:2": "Flag 2 (Orange)", "flag:3": "Flag 3 (Green)", "flag:4": "Flag 4 (Blue)",
                        "flag:5": "Flag 5 (Pink)", "flag:6": "Flag 6 (Turquoise)", "flag:7": "Flag 7 (Purple)"},
    "junban_scope": {"deck": "This deck", "all": "All decks"},
    "junban_order": {"content": "As I’ll meet it", "priority": "By leverage"},
    "split_books_by": {"chapters": "Chapters", "even": "Even parts"},
    "junban_unlisted": {"list_first": "After it", "journey": "Mixed in", "back": "At the back"},
    "junban_only_markers": {"star": "✦", "lopsided": "⚖", "reading": "📖"},
    "backfill_patterns": {"patterns": FILLS["patterns"]}, "backfill_sentence": {"sentence": FILLS["sentence"]},
    "junban_backfill_cards": {"all": "All", "new": "New only"},
    "strategy": {"freq": "Level", "coverage": "Coverage %"},
    "zh_script": {"asis": "As written", "s": "Simplified", "t": "Traditional"},
    "paren_readings": {"hiragana": "Hiragana", "any": "Any kana", "off": "Off"},
    "target_language": {"ja": "日本語", "zh": "中文"},
    "placing_rules": {"wait": "Wait here, in New arrivals", "top": "Top of Current", "after-show": "After its show",
                      "soon": "Soon", "goal": "Goal", "finished": "Finished"},
    "theme": {"Default (Dark)": "Default (Dark)", "Dark Flow": "Dark Flow", "Midnight (Vibrant)": "Midnight (Vibrant)",
              "Modern Light": "Modern Light", "Zen Mode": "Zen Mode"},
    "source_display": {"off": "Hidden", "icon": "Icon", "filename": "File name", "full": "Icon + file name"},
    "word_search_category": {"all": "All", "anime": "Anime", "liveaction": "Live action", "youtube": "YouTube"},
    "text_size": {"S": "Small", "M": "Medium", "L": "Large"},
    "app_motion": {"follow": "Follow Windows", "full": "Full", "reduced": "Reduced"},
}
# The line under each choice card (Connect's own words, P3.1)
OPTION_LINES = {
    "connect_mine_words": {value: line for value, _label, line in MINE_WORDS},
}
# An option's own tooltip (a choice's or a tablet's), where its label alone doesn't say it
OPTION_TIPS = {
    "junban_only_markers": {"star": "High leverage: the words the report stars",
                            "lopsided": "Lopsided: words that come almost entirely from one part of your library",
                            "reading": "Reading: words you'll read but essentially never hear"},
    "junban_order_all": {False: "Your own cards go ahead of Connect's, in the order you made them",
                         True: "Your own cards go among Connect's, in your list's order"},
}

# --- P4: the live rows (settings_live.py): Your setup, the level readout, the statuses, App's rows, the credits, Export
SEP = " · "
# Your setup's lines (each says less when a fact can't be read: never a wrong number)
SETUP_KNOWN = "{n:,} known"
SETUP_FROM_ANKI = "from Anki ({decks})"
SETUP_IMPORTED = "from an imported list"
SETUP_CONNECT_OFF = "Connect is off: you make your cards yourself"
SETUP_AUTOMATIC = "Automatic"
SETUP_WORDS = "≈{words:,} words"
SETUP_COVERAGE = "{coverage}% of your content"                                  # S4: never "% known"
SETUP_ORDER = {"content": "ordered as you’ll meet them", "priority": "ordered by leverage"}
SETUP_NOT_ORDERED = "not reordered"
SETUP_FILLED = "{fills} filled {how}"
SETUP_FILLED_AUTO = "automatically"
SETUP_FILLED_HAND = "by hand"
SETUP_NOTHING_FILLED = "nothing filled"
# The level readout under the slider, when the time between meetings is under an hour, or unknown
READOUT_HOURS = "≈{words} words · {coverage}% of your content · about every {hours} hours"   # S4
READOUT_MINUTES = "≈{words} words · {coverage}% of your content · about every {minutes} minutes"
READOUT_NO_TIME = "≈{words} words · {coverage}% of your content"
# Connection (Anki): the emerald's words (S6: never colour alone)
ANKI_WORDS = {
    "connected": "connected", "closed": "Anki is closed", "busy": "Anki is open but isn’t answering",
    "denied": "Anki hasn’t let Surasura in yet", "failed": "the last sync from Anki didn’t finish",
    "syncing": "reading Anki…", "checking": "checking…", "unknown": "not checked yet",
}
ANKI_TIP = "Whether Surasura reaches Anki now, through AnkiConnect"
CHECK_LIVE_TIP = "Asks Anki now whether AnkiConnect answers"
INSTALLED_PLAIN = "installed"
# App's rows
LOGS_OPEN = "View"
DATA_FOLDER = "Data folder"
DATA_FOLDER_TIP = "Opens the data folder"
CREDITS_VIEW = "View"
CREDITS_TITLE = "Data credits"
CREDITS_NAME = "Data credits: every source, with its licence"
CREDITS_DONE = "Done"
CREDITS_DONE_TIP = "Closes the credits (Esc)"
CREDITS_README_ALSO = "README's Data Credits also names: {names}"
OFFER_AGAIN_NAME = "Offer the skipped version again"
# *Text size*: applied when Surasura starts again, so it asks at once (laptop fixes, row 15)
TEXT_SIZE_RESTART_ASK = "Restart now to apply?"
TEXT_SIZE_RESTART_BODY = "{size} text shows once Surasura starts again. It reopens here, at the same size and place."
# ... and while a Generate runs nothing is asked: a quit would stop it and nothing starts it again (B2-3)
TEXT_SIZE_AFTER_GENERATE = "Restart Surasura once Generate finishes to apply"
TEXT_SIZE_RESTART_YES = "Restart now"
TEXT_SIZE_RESTART_YES_TIP = "Closes Surasura and opens it again with the new text size"
TEXT_SIZE_RESTART_NO = "Later"
TEXT_SIZE_RESTART_NO_TIP = "Keep working: the new size shows the next time Surasura starts"
# Export: the format pop, the outcome in the bar
EXPORT = "Export"
COVERS_REMOVE = "Remove"                    # --- W3.2 L3: *Remove downloaded covers*' button
EXPORT_NEXT = "Save as…"
EXPORT_NEXT_TIP = "Choose where the file goes"
EXPORT_FORMAT_NAME = "Format"
EXPORT_CONFIRM_TIP = "Goes on to choose where the CSV goes"
EXPORT_RUNNING = "Exporting {name}…"
EXPORT_BUSY = "Another export is running: one at a time"

# --- P8: Connect's switch, the Anki Miner card, *New cards a day* (settings_connect.py) ------------------------------ #
# Connect's switch: its outcome in the bar (the Tk log's words, `app/connect/switch.py`) and 2.x's two questions
SWITCH_NOT_ON = "Connect wasn't switched on: {}. Nothing changed; try again."
SWITCH_NOT_OFF = "Connect wasn't switched off: {}. It stays on; try again."
SWITCH_BROKE = "Connect's switch didn't finish: {}. It shows what is saved."
SWITCH_ALREADY_ON = "Connect was already on (switched on in another window): nothing else changed."
PUT_BACK_ASK = "Put the {n} shelved {cards} back into your new cards?"
PUT_BACK_BODY = ("Connect turns off either way, on Leave them or Esc too: the cards then stay on the shelf, suspended "
                 "until you put them back.")
PUT_BACK_YES = "Put them back"
PUT_BACK_YES_TIP = "Your shelved cards go back into your new cards, then Connect turns off"
PUT_BACK_NO = "Leave them"
PUT_BACK_NO_TIP = "Connect turns off; the shelved cards stay suspended (Esc does the same)"
OFF_ANYWAY_ASK = "Turn Connect off anyway?"
OFF_ANYWAY_BODY = ("Some shelved cards weren't put back:\n{failed}\n\nThe cards on the shelf stay suspended until you "
                   "put them back.")
OFF_ANYWAY_YES = "Turn Connect off"
OFF_ANYWAY_YES_TIP = "Connect turns off; the cards still on the shelf stay suspended"
OFF_ANYWAY_NO = "Keep it on"
OFF_ANYWAY_NO_TIP = "Connect stays on (Esc does the same)"
STAYS_ON = "Connect stays on: put the shelved cards back from its window, or turn it off again."
# The Anki Miner card (U5, U6; AM★: the star line beside Install). The Tk panel's words.
MINER_CHECKING = "Checking…"
MINER_NOT_CHECKED = "Couldn't check Anki Miner: {}"
MINER_STEP_1 = "1. In Anki Miner: Manage profiles… → New, and name it Surasura."
MINER_STEP_2 = "2. In that profile's Settings: Whitelist → choose file, and pick this file:"
MINER_STEP_BOLD = "Also turn on Bold the word in the sentence."
MINER_PATH_NAME = "The whitelist file's path"
# A6: the practice server's Copy buttons (Connections' *Piyo ぴよ — practise with your AI*), one per AI app (mcp_server.APPS)
PRACTICE_APPS = {"claude-code": "Claude Code", "codex": "Codex", "claude-desktop": "Claude Desktop"}
PRACTICE_COPY_TIP = ("Copies the setup for {app}: paste it to {app} (it runs it for you), or follow it yourself")
PRACTICE_COPIED = "Copied"
PRACTICE_COPIED_LINE = "The setup for {app} is copied: paste it to {app}."
# A7 (Sonic's first try, 2026-10-30: "How do i start piyo conversation?"): under the Copy buttons, both ways to start a
# round (the slash form, its words and example: app/cli/mcp_server.SLASH_EXAMPLE and the prompt's arguments, a test keeps
# them equal; the plain request: app/practice.STARTER)
PRACTICE_THEN = ("Then, to start a round:\n"
                 "• In Claude Code, type /surasura:practice and four words: how many (1–20) · who's talking (friend, "
                 "coworker, boss, customer, senpai, kohai, shopkeeper, teacher, child) · what kind (chat, reading: a "
                 "short story, quiz) · from what (soon: your list's next words, latest: what you watch or read next, "
                 "mix). Type / and it's listed as /surasura:practice (MCP).\n"
                 "• For example: /surasura:practice 5 friend reading soon\n"
                 "• Or, in Claude Code, Codex or Claude Desktop, just say it: “{starter}”")
# A7 (Sonic, 2026-10-30: the row's words no longer than *Download covers*'): what leaves and how to start, behind its ?
PRACTICE_HELP = "?"
PRACTICE_HELP_NAME = "About Piyo"
PRACTICE_LEAVES = ("<b>What leaves:</b> your AI app runs Surasura on this computer. What Surasura tells it (your known "
                   "words, your list's next words, lines from your library, what you kept from past rounds) goes to "
                   "that AI's company, as anything you type there does. Nothing else leaves.")
PRACTICE_STARTER = "Copy a starter message"
PRACTICE_STARTER_TIP = ("Copies a first message for your AI, once Piyo is added: a short story with 5 of your words. "
                        "A story is a good first try")
PRACTICE_STARTER_COPIED_LINE = "The starter message is copied: paste it to your AI."
COPY_PATH = "Copy path"
COPY_PATH_TIP = "Copy the whitelist file's path, to paste into Anki Miner's file chooser."
PATH_COPIED = "The whitelist file's path is copied: paste it into Anki Miner's file chooser."
INSTALL_MINER = "Install Anki Miner…"
INSTALL_MINER_TIP = "Get Anki Miner, free: its installer, from its GitHub release.\n• Asks before it downloads"
# A5F2: what only Anki Miner's installer brings (an older Anki Miner, its ffmpeg): the same route, as the update
UPDATE_MINER_BUTTON = "Update Anki Miner…"
UPDATE_MINER_BUTTON_TIP = ("Get the Anki Miner Surasura works with, free: its installer, from its GitHub release.\n"
                           "• Asks before it downloads")
BROWSE_MINER = "Browse…"
BROWSE_MINER_TIP = "Anki Miner is installed somewhere else: show Surasura where."
BROWSE_MINER_TITLE = "Where is Anki Miner?"
BROWSE_MINER_FILTER = "Anki Miner (AnkiMiner.exe);;Programs (*.exe);;All files (*)"
OPEN_MINER = "Open Anki Miner"
# A4M1-2 (lean taken, PROVISIONAL): its own window, for its own settings — Surasura never needs it opened
OPEN_MINER_TIP = ("Start Anki Miner's own window, for its own settings.\n"
                  "• Surasura never needs it open: Connect runs Anki Miner by itself")
FINISH_MINER_SETUP = "Finish its setup…"
FINISH_MINER_SETUP_NO_WIZARD = "The setup couldn't open here: close Settings and press Finish its setup again."
FINISH_MINER_SETUP_TIP = ("Anki Miner still needs its dictionaries, or its deck and note type: Surasura sets them "
                          "for you, on the setup's Anki Miner page.\n• Nothing to open in Anki Miner")
MINER_NOT_OPENED = "Couldn't open Anki Miner: {}"
CHECK_AGAIN = "Check again"
CHECK_AGAIN_TIP = "Look at Anki Miner's setup again."
STAR_LINE = "Like Anki Miner? Star it on GitHub ★"
STAR_LINE_TIP = ("Opens Anki Miner's page on GitHub in your browser. The Star button is at the top right; it needs "
                 "a GitHub account.")
STAR_ASK = "Anki Miner is free and made by one person. A ⭐ on GitHub helps other learners find it."
STAR_BUTTON = "⭐ Star Anki Miner on GitHub"
STAR_BUTTON_TIP = "The Star button is at the top right; it needs a GitHub account."
NOT_NOW = "Not now"
NOT_NOW_TIP = "Hide this suggestion."
STAR_LINK = "⭐ Anki Miner on GitHub"
STAR_LINK_TIP = "Open Anki Miner's page on GitHub in your browser."
MINER_UPDATE = "Anki Miner {version} is out"
MINER_UPDATE_TIP = "Opens Anki Miner's releases page in your browser"
# *New cards a day* (G1.2-5; NEW_CARDS_FROM_ANKI, CHANGE_IN_ANKI and its tip are above)
NEW_CARDS_READING = "Reading Anki…"
NEW_CARDS_NO_DECK = "Junban’s deck"
NEW_CARDS_DECK = "“{deck}”"
NEW_CARDS_FIELD_TIP = "The number to set in Anki: nothing changes there until you press Change in Anki… and say yes"
NEW_CARDS_UNREAD_TIP = "{why} Until Anki can be read, this is the report's pace: new words a day."
NEW_CARDS_ASK = "Change New cards a day in Anki?"
NEW_CARDS_YES = "Set it to {n}"
NEW_CARDS_YES_TIP = "Writes the new number into the deck's options group in Anki"
NEW_CARDS_SAME = "Anki's New cards a day for “{deck}” is already {n}."
NEW_CARDS_WAITING = "Waiting for Anki…"
NEW_CARDS_BROKE = "New cards a day wasn't changed: {}"
NEW_CARDS_DECK_MOVED = ("New cards a day wasn't changed: Junban's deck is “{deck}” now, not “{asked}”. Nothing was "
                        "written; look at it again.")
NEW_CARDS_VALUE_MOVED = ("New cards a day for “{deck}” is now {n} in Anki — it changed while you were asked. Nothing "
                         "was written; look at it again.")
NEW_CARDS_UNREAD_NOW = "New cards a day wasn't changed: Anki can't be read now. Nothing was written."

# --- P6: the store's two lines; *Set up again* (settings_store.py) ------------------------------------------------- #
STORE_FILES = "files"
STORE_NO_LIBRARY_TIP = "Opens with your library"
STORE_NOT_SAVED = "Not saved: {reason}"
SET_UP_AGAIN_OPEN = "Start ›"

# --- a6: *Your settings* — export and import (settings_io.py; SI-1…SI-5, PROVISIONAL) ------------------------------- #
SETTINGS_EXPORT = "Export settings…"
SETTINGS_EXPORT_TIP = ("Save every setting to one file, for the next version or a new computer\nYour known words, "
                       "word lists and library aren't in it, and no key or password ever is")
SETTINGS_EXPORT_TITLE = "Save your settings"
SETTINGS_IMPORT = "Import settings…"
SETTINGS_IMPORT_TIP = ("Replace every setting with the ones in a file you exported\nYour settings now are kept in a "
                       "dated copy first. Surasura asks before it replaces anything")
SETTINGS_IMPORT_TITLE = "Import settings"
SETTINGS_FILES = "Surasura settings (*.json)"
SETTINGS_IMPORT_YES_TIP = "Replace your settings with these, keep a dated copy of yours, then restart"
SETTINGS_IMPORT_NO = "Cancel"
SETTINGS_IMPORT_NO_TIP = "Keep your settings as they are"
SETTINGS_IMPORT_AFTER_GENERATE = "Import your settings once Generate finishes: Surasura restarts to use them"
SETTINGS_FAILED = "Couldn't do that: {why}"

# --- SRC W1b: *Library folders* (settings_sources.py) ------------------------------------------------------------ #
SOURCES_ADD = "Add a folder…"
SOURCES_ADD_TIP = "Read another folder where it is\nA show Surasura hasn't shown you yet waits in New arrivals"
SOURCES_LOOK = "Look again"
SOURCES_LOOK_TIP = "Look in every folder for new episodes now (the Refresh key does the same)"
SOURCES_STOP = "Stop reading"
SOURCES_STOP_TIP = ("Stop looking in {path} for new episodes\nIts {n:,} episodes stay in your library; Undo, or adding "
                    "the folder again, reads it on from where it was")
SOURCES_STOP_NAME = "Stop reading {path}"
SOURCES_PICK_TITLE = "A folder for Surasura to read where it is"
SOURCES_COUNT = "{n:,} episodes"
SOURCES_COUNT_ONE = "1 episode"
SOURCES_AWAY = "{count} · not reachable now"
SOURCES_LISTING = "Looking at your folders…"
SOURCES_NONE = "No folders yet: Surasura reads only what you add"
SOURCES_STOPPED = "Stopped reading {path}: its {n:,} episodes stay in your library"
SOURCES_STOPPED_ONE = "Stopped reading {path}: its episode stays in your library"
# K6: the folders inside them Surasura never reads (⋯ › *Never read this folder*, setup's *Skip a folder…*)
SOURCES_SKIPPED = "Skipped folders"
SOURCES_READ_AGAIN = "Read again"
SOURCES_READ_AGAIN_NAME = "Read {path} again"
SOURCES_READ_AGAIN_TIP = ("Read {path} again\nIts files come back into your library at once; a show you haven't had "
                          "yet waits in New arrivals")
SOURCES_READ_AGAIN_DONE = "{path} is read again: its files come back into your library"
# Q7: *Skip a folder…* under them (the wizard's picker and its refusal's words: `wizard_strings.SKIP_TITLE`,
# `FOLDER_REFUSED`; the toast: `strings.ITEM_SKIPPED`, ⋯'s)
SOURCES_SKIP = "Skip a folder…"
SOURCES_SKIP_TIP = ("Choose a folder inside one Surasura reads that it should never read (a backup, a show's extras)\n"
                    "Everything of it leaves your library (to the trash for 30 days; Undo brings it back); nothing in "
                    "the folder is changed")
# (Sonic's lean B, 2026-10-24, PROVISIONAL: it turns until saved; its line and Undo in this window, the toast's one Undo)
SOURCES_SKIP_QUEUED = "Skipping {name} after the look under way…"
SOURCES_SKIP_UNDO_TIP = "Undo this skip: its files come back into your library where they were"
SOURCES_SKIP_SWITCHED = "Nothing skipped: the library changed to another language meanwhile"
# Row 32 (laptop round 4): the page's summary, and the folders in their own window (*Manage folders…*)
SOURCES_FOLDERS = "{n:,} folders"
SOURCES_FOLDERS_ONE = "1 folder"
SOURCES_AWAY_N = "{n:,} not reachable now"
SOURCES_SKIPPED_N = "{n:,} skipped"
FOLDERS_NAME = "Library folders"
FOLDERS_LINE = "Surasura reads these folders where they are and looks in them again for new episodes."

# --- K7: *Sort my library again…* (settings_sources.py: FreshRow; the store's `start_fresh`; A7O-6: wording only) --- #
FRESH_OPEN = "Sort my library again…"
FRESH_TIP = ("Kept: your folders, your skipped folders and, unless you choose to forget them, your known words\n"
             "Cleared into one dated backup in User Files' .trash: your order, tiers, New arrivals and subtitle "
             "pairings\nThen every folder is read again into Current")
FRESH_RUNNING_TIP = "Clearing your order into a backup…"
FRESH_ASK = "Sort your library again?"
FRESH_BODY = ("Kept: your folders and your skipped folders, your settings, your cards in Anki (a card you deleted "
              "is never made again) and, unless you tick the box, your known words.\n\n"
              "Cleared into one dated backup (User Files › .trash › library-reset-…; its reset.json says how to put "
              "it back): your order, tiers, New arrivals, subtitle pairings and the copies Surasura keeps of your "
              "files.\n\n"
              "Then every folder is read again into Current, in name order — episodes you removed too. A video "
              "still waiting for its subtitles waits in New arrivals; a book's text comes back only when its folder "
              "is read.")
# The sheet's counts (the store's `fresh_counts`), each line only when its count isn't 0
FRESH_GONE = "Only in the backup, never back: {parts}."
FRESH_GONE_ADDED = "{n} file{s} you added with + Add from outside your folders"
FRESH_GONE_YOUTUBE = "{n} YouTube transcript{s}"
FRESH_GONE_OTHER = "{n} other text{s} with no folder to read again (pasted, hato's, from before 3.0)"
FRESH_SUSPENDED = ("{n} card{s} Surasura took out of your learning order stay suspended in Anki: unsuspend them "
                   "there if you want them back.")
FRESH_NOT_ALL_BACK = "Not all of your library could be put back: the rest is in {folder}"
FRESH_UNFINISHED = ("Sorting your library again stopped part way: your old library may be in its backup, {folder} "
                    "(reset.json there says how to put it back)")
FRESH_YES = "Sort again"
FRESH_YES_TIP = "Clear your order into a backup and read your folders again"
FRESH_KNOWN = "Also forget my known words"
FRESH_KNOWN_TIP = ("KnownWord.json is kept in the backup and replaced by an empty one\nWords from your Anki cards come "
                   "back at the next Anki sync")
FRESH_DONE = "Your order is in the backup: reading your folders again…"
FRESH_DONE_KNOWN_KEPT = "Your order is in the backup: reading your folders again… Your known words were kept: {why}"
FRESH_REFUSED = "Nothing was changed. {reason}"
FRESH_FAILED = "Nothing was changed: {reason}"
FRESH_NOT_WRITABLE = "Your library can't be written now: {reason}"

# --- PR: *Where new arrivals go* — the placing rules' lines (settings_rules.py; RULE_FROM, RULE_ADD, its tip above) -- #
RULE_LINE_TIP = "Where arrivals from {source} go. Wait here: they wait in New arrivals for you"
RULE_LINE_NAME = "Where arrivals from {source} go"
RULE_LINE_WORDS = "From {source}"
RULE_CHANNEL = "{producer} · channel {channel}"
RULE_FOLDERS = "your folders"                       # the `source` line: the folders Surasura reads where they are
RULE_FOLDER = "folder {folder}"
RULE_HELD = "“{value}” · waits"
RULE_SEEN_NONE = "No other source seen yet"
RULE_TYPE = "Another source…"
RULE_TYPE_TIP = "Type a program's name (hato), or a program and a channel (youtube:<channel id>)"
RULE_TYPE_PLACEHOLDER = "youtube:<channel id>"
RULE_TYPE_NAME = "A source for a new rule"
RULE_NEW_TIP = "A new rule for {source}: pick where its arrivals go. Nothing is saved while it says Wait here"

# --- round 8 row 45 (P5): a press whose wait is worth naming — its words held in the bar while it runs ------------- #
SWITCH_TURNING_ON = "Turning on Make cards for me…"
SWITCH_TURNING_OFF = "Turning off Make cards for me…"

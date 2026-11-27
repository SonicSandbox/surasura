"""Every user string of the Settings page (W3.3; the window's spec 05 §5.7, §5.12: one table, so the app can be
translated later) — Settings' own table beside `strings.py`, as a module keeps its `qt_strings.py`. No Qt.

Settings keeps its words (C-scope Q6): the old mock's labels and one-line help (`mock-g16` `sectionBody`); where the
mock's words carry a meaning 2.4 changed (A5: the one-kanji words, Junban's unlisted cards), 2.4's meaning in the mock's
voice. A tooltip is 2.4's own where 2.4 had one, else the help line. Help is one line, never an essay; no fixed seed
numbers (N5). `app/qt/settings_catalog.py` names each row's strings by its row id.
"""
from app import ankiconnect_addon as _addon         # AnkiConnect missing: the one set of words (alpha 8)
from app.practice import NAME as PRACTICE_NAME       # the practice chat's name (A6): one place, app/practice.py
from app.anki_words import SOURCES as ANKI_SOURCES  # Piyo's sources from Anki (Piyo-AK): one table, app/anki_words.py
from app.plan_rules import SENTENCE_TABLE           # E-LENGTH: *Length*'s words once the sentence table is on

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
SET_UP_MINER_TIP = "Goes to Anki Miner in Connections: install it or point to it."
CONNECTED = "connected"
NOT_CONNECTED = "not connected"
CHECK = "Check"
CHECK_TIP = "Checks AnkiConnect, the deck and the note type"
INSTALLED = "installed · {version}"
# Michi-HD (Mattias 2026-11-11; lean taken, PROVISIONAL): hato installed where Surasura can't see it — *Find hato…*
HATO_NOT_FOUND = "not found"
FIND_HATO = "Find hato…"
FIND_HATO_TIP = "Already have hato? Pick its folder.\n• It opens once to connect."
FIND_HATO_TITLE = "Where is hato?"
FIND_HATO_BUSY = "Opening hato so it can connect…"
HATO_CONNECTED = "hato {version} is connected"
HATO_CONNECTED_PLAIN = "hato is connected"
HATO_NOT_CONNECTED = {                       # `tools_found.open_hato` / `hato_seen`'s why -> the bar's words
    "not-hato": "No hato in that folder: pick the folder you unpacked hato into",
    "not-installed": "hato connects only to an installed Surasura, and this copy isn't installed",
    "not-started": "hato couldn't be opened from that folder",
    "no-answer": "hato opened but didn't connect. If hato was open already, quit it from its tray icon, then press "
                 "Find hato… again (hato 1.1 or later connects to Surasura)",
    "another-hato": "Another copy of hato was open already, so Surasura uses that one",
}
HATO_FIND_FAILED = "Surasura couldn't connect hato: the log says why"
# Hato-UP (3.0.18; Sonic 2026-11-21): hato's own daily update, started by Surasura (`services.hato_update.status`) —
# the row's words, its version first, and each one's line behind the mark (its hover; ≤ 12 words). PROVISIONAL: the
# words, and OUT (a newer hato this copy can't install itself). HATO-UPDATING (3.0.20): *updating…* only while hato
# says it is installing; READY (a release waiting for a press in hato's window) — its words and line PROVISIONAL
HATO_UPDATE_WORDS = {
    "up-to-date": "{version} · up to date",
    "updating": "{version} · updating…",
    "ready": "{version} · {latest} ready in hato",
    "couldnt-check": "{version} · couldn't check",
    "out": "{version} · {latest} is out",
}
HATO_UPDATE_TIPS = {
    "up-to-date": "Surasura has hato check for its updates once a day.",
    "updating": "hato is installing {latest} by itself, quietly.",
    "ready": "Open hato to install {latest}: it waits for your press there.",
    "couldnt-check": "hato couldn't reach its updates. Surasura tries again tomorrow.",
    "out": "hato can't update this copy itself: download {latest} from hato's page.",
}
OPEN = "Open"
LEVEL_AUTOMATIC = "Automatic"
LEVEL_AUTOMATIC_TIP = "Picks your level: the commonest one holding at least {n} words."
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
HELP_MARK = "?"                                       # a9.1: a row's description, behind its ? (`RowView`)
HELP_MARK_NAME = "About {label}"
HOW_PARSING_URL = "https://github.com/SonicSandbox/surasura/blob/main/docs/How%20Parsing%20Works.md"
DISCORD_URL = "https://surasura.dev/app/discord"      # the server's invite, by redirect (in the browser, never an app call)
WEBSITE_URL = "https://surasura.dev"                  # Surasura's website (in the browser, never an app call)
ISSUES_URL = "https://github.com/SonicSandbox/surasura/issues"
STAR_URL = "https://github.com/SonicSandbox/surasura"   # the star ask's and App's row (in the browser, never an app call)
# a9.1 (Sonic: "a button for each that launches"; wording PROVISIONAL): App's *Connect with us* block, a button per
# page, each saying what it does — label, tooltip, page
LINKS = {"github": ("⭐ Star on GitHub", "Opens Surasura's GitHub page in your browser: free and made by one person, a "
                                        "⭐ helps other learners find it", STAR_URL),
         "discord": ("Join the community", "Opens Surasura's Discord server in your browser: questions, help, and a "
                                           "place to report a problem", DISCORD_URL),
         "website": ("Visit the website", "Opens surasura.dev, Surasura's home page, in your browser", WEBSITE_URL)}
# a link's page, by its name: the block's buttons, and Parsing's *How parsing works* row
LINK_URLS = dict({name: url for name, (_label, _tip, url) in LINKS.items()}, how_parsing_works=HOW_PARSING_URL)
FOLDER_PICK_TITLE = "Where videos are looked for"
# *Videos open in* / *Books open in* (Sonic 2026-11-05): the program option before one is chosen, its *Change…*, the
# picker (PROVISIONAL)
PROGRAM_PICK = "Choose a program…"
PROGRAM_CHANGE = "Change…"
PROGRAM_CHANGE_TIP = "Choose another program"
PROGRAM_PICK_TITLE = {"open_video": "The program videos open in", "open_book": "The program EPUBs open in"}
PROGRAM_FILTER = {"win32": "Programs (*.exe)"}                   # other systems: every file

# --- the controls' own words (settings_controls.py; moved here from its top, W3.3 P3) ------------------------------ #
ADD = "Add"                                      # an empty bed's words when the page names none
REMOVE_NAME = "Remove {item}"                    # a list tablet's ✕, for screen readers (the accessible description)
CROSS = "✕"
TICK = "✓"                                       # a multi-pick tablet's mark when lit (Q31: never a choice's vein)
PICKED_NONE = "None picked"                       # a set of tablets with none picked, for screen readers
STATUS_NAME = "{name}: {words}"                  # the status mark, for screen readers
TOGGLE_STATE = {True: "On", False: "Off"}        # a switch's state, for screen readers (Fresh-U row 12)

# --- the sections (the mock's order, with Language & Parsing after Level: 05 §5.7) --------------------------------- #
SECTIONS = {
    "setup": "Your setup", "known": "Known words", "anki": "Anki & mining", "junban": "Card order",
    "backfill": "Fill your cards", "level": "Level", "parsing": "Language & Parsing",
    "content": "Content", "arrivals": "New arrivals", "connect": "Connections", "reading": "Journey",
    "sentences": "Sentences", "export": "Export", "app": "App",
}
# Fine-tune (Mado-EZA: EZ-4, EZ2-9; every word PROVISIONAL): the nav's three heads over the sections, a changed row's
# dot and its *back to it*, *↺ Reset section* (never usage counts, updates, automation, the language or folders), the
# toast a save shows with its Undo, and a closed *More options* fold's values on one line
HEADS = {"cards": "Cards", "library": "Library", "app": "App"}
CHANGED_NAME = "You changed this"
CHANGED_TIP = "You changed this · default: {default}\n• Click: back to it"
RESET_SECTION = "↺ Reset section"
RESET_SECTION_TIP = ("This section's settings back to their defaults\n"
                     "• Never usage counts, updates, automation, language or folders")
RESET_NOTHING = "Nothing here differs from its default"
RESET_DONE = "↺ {section}: back to defaults"
SAVED = "✓ Saved"
FOLDED_VALUE = "{label}: {value}"
FOLDED_SEP = " · "
VALUE_NONE = "none"
VALUE_COUNT = "{n} added"
# S1 · Settings say why (Kantan-S1; Kantan-X's EXPERIENCE.md §5, mock 03; every word PROVISIONAL): the sections that
# hide value say their plain name first, the module's name small beside it, and one line on what you get under it; a
# needs line only while something is missing, with *Show me* where that is (the page's `reveal`)
SECTION_TAGS = {"junban": "順 Junban", "backfill": "Backfill"}
NAV_TAGS = {"junban": "順"}                                     # the nav's (mock 03): 順's glyph, as the bar's circle
SECTION_NAMED = "{name} · {tag}"                               # a tagged section, for the nav's tip and screen readers
SECTION_WHY = {
    "junban": "New Anki cards come in the order you'll meet their words.",
    "backfill": "Adds to your Anki cards how each word is usually used (パターン), two more sentences from your own "
                "content (例文), and the furigana and pitch a card is missing. Restore puts every card back",
}
ROW_TAGS = {"practice_ai": PRACTICE_NAME, "hato": "hato", "ai_audio": "Beta"}       # a row's tool, small beside its plain name
NEEDS_ANKI = "Needs Anki open and connected"
NEEDS_MINER = "Needs Anki Miner (free)"
CARDS_WHY = "Cards for episodes at the top of Current, made by themselves."   # (before Anki Miner's found)
SHOW_ME = "Show me ›"
SHOW_ME_TIP = "Goes to {where}"
WHERE = "{section} › {row}"
SHOW_ME_PLAIN = "Goes to the setting it needs"
SHOW_ME_NAME = "{need}: {show}"                                 # *Show me*, for screen readers

# --- the group names inside a section ------------------------------------------------------------------------------ #
GROUPS = {
    "loop": "Your daily loop", "from_library": "Cards from your library",
    "in_anki": "Cards already in Anki", "anki": "Anki", "names": "Names", "words_phrases": "Words and phrases",
    "houseki": "Houseki tools", "not_on_list": "Cards not on your list", "beta": "Beta",
    "card_sound": "Card sound",
}

# --- the doors (a window, or an action, a row opens) ---------------------------------------------------------------- #
DOORS = {
    "anki": ("Anki…", "Choose your decks and the field each card's word is in"),
    "migaku": ("Migaku", "Import from Migaku"),
    "jiten": ("Jiten", "Import from Jiten"),
    "apkg_known": (".apkg", "Import an Anki deck file"),
    "word-lists": ("Known · Ignore…", "Opens the words you know and the words you ignore"),
    "junban": ("Junban…", "Opens Junban’s window: choose the deck, preview the new order and why before anything "
                          "moves, undo the last reorder"),
    "put-back": ("Put Anki back…", "Puts Anki's new cards back the way they were before Surasura first changed them"),
    "backfill": ("Backfill…", "Opens Backfill’s window: choose the deck and each note type's fields, see exactly what "
                              "goes into each card, Fill and Restore"),
    "extract": ("Extract…", "EPUBs and Anki decks, split into parts"),
    "youtube-downloader": ("YouTube…", "Download a video's captions straight into your library"),
    "youtube-preview": ("Preview a video…", "Score a video against your words before you add it"),
    "koe": ("Speech settings…", "Set the API key, voice and delivery for spoken sentences"),
    "sentence-dictionary": ("Export", "Exports Surasura Corpus for Yomitan"),
    "frequency-lists": ("Add…", "Add or remove a frequency list"),
    "unmined-words": ("Words…", "Opens the words whose cards you deleted in Anki: Surasura never mines them again, "
                                "unless you allow one"),
    "library-folders": ("Manage folders…", "Opens your folders: stop reading one, read a skipped one again, or look "
                                           "in them all again"),
}
# A row whose door says something else than the opener's own words: row id -> {opener: (label, tooltip)} (a9.1: none
# — Junban's and Backfill's windows have one door each, on their *Which cards* row)
ROW_DOORS = {}

# --- the rows: row id -> (label, one-line help, tooltip, search words) --------------------------------------------- #
ROWS = {
    # Your setup (five live summaries; each line is P4's)
    "setup_known": ("Known words", "", "Go to Known words", "known words sync anki import"),
    "setup_anki": ("Anki", "", "Go to Anki & mining", "anki connected deck waiting"),
    "setup_mining": ("Cards made for you", "", "Go to Anki & mining", "cards made for you mining mine cards top"),
    "setup_level": ("Level", "", "Go to Level", "level band automatic"),
    "setup_cards": ("Cards in Anki", "", "Go to Card order", "cards in anki ordered filled junban backfill"),

    # Known words
    "known_road": ("Your known words come from",
                   "Anki stays in sync. Import is one-time; a backup is kept.",
                   "Where your known words come from", "source where they come from anki import migaku jiten apkg"),
    "anki_decks": ("Decks", "", "Decks your known words come from; change in the Anki window.",
                   "decks anki fields word field"),
    "anki_sync_auto": ("Keep in sync while Anki is open", "",
                       "Adds new known words by itself when Anki is open.", "sync automatically anki open"),
    "anki_auto_generate": ("Re-generate when new words come in", "In the background, at most every 10 minutes",
                           "Re-generates by itself after new known words arrive.",
                           "generate automatically new known words"),
    "known_import": ("Import from", "Replaces your known words — a backup is kept",
                     "Import your known words from Migaku, Jiten or an Anki deck file", "import migaku jiten apkg"),
    # Kotoba-WS2 (Sonic 2026-11-19, one word standard: Known · Ignore; the Blacklist merged into the Ignore list) — the
    # old names stay search words (criteria 10)
    "words_to_leave_out": ("Your words", "",
                           "Opens the words you know and the words you ignore",
                           "your words ignore ignored ignore list blacklist leave out never suggested known marked"),
    "use_every_core": ("Use every core", "Reads a big library faster; the computer is busier meanwhile",
                       "Off: half your cores, stays quick. On: all cores, faster.", "cores speed faster cpu"),
    # Kantan-B3 (Sonic 2026-11-18): the default is Suspended + Marked — a plain suspend often means "a bad sentence,
    # I still want the word" (the ? line, ≤ 12 words: PROVISIONAL)
    # Mado-LT (3.0.18, WL mock 04; PROVISIONAL words): the loop's three move cards — the move, then what you do to its
    # card in Anki (the control); the ? line says what happens at the next sync. Known keeps *Count as known in Anki*'s
    # key and its search words (it moved here from Known words' More options)
    "known_from_anki": ("✓ Known",
                        "Default: Suspended + Marked. A plain suspend never counts; once synced, delete freely",
                        "A card in every state you pick turns its word known.",     # Kotoba-WS2: ≤ 12 words (rule 8)
                        "known from anki suspended marked flag count as known in anki count suspended cards as known "
                        "include suspended studied then suspended review loop daily loop move phone"),
    "loop_swap_flag": ("⇄ Swap",
                       "At the next sync Surasura gives the word a better sentence",       # FS-2: either way
                       "Suspend a card with this flag: a different sentence, please.",
                       "swap different sentence better sentence flag green review loop daily loop move phone"),
    # FS-2 (the full Swap, SCOPE § 4, decisions 5, 6, 9; PROVISIONAL words): what Swap gives the card, under its flag
    "swap_in_place": ("Swap gives",
                      "Same card: it keeps its reviews; its sentence, audio and picture change. Cards you made or "
                      "changed by hand get a new card. A phone edit before Anki syncs may be lost.",
                      "Same card keeps its reviews; a new card starts the word again.",
                      "swap in place same card new sentence keep reviews due date rewrite full swap better sentence "
                      "new card daily loop"),
    "loop_ignore_flag": ("✕ Ignore",
                         "At the next sync its word goes on your Ignore list; once synced, delete freely",
                         "Suspend a card with this flag: not a word to learn.",
                         "ignore flag red not a word name noise review loop daily loop move phone ignored"),

    # Anki & mining
    "anki_connection": ("Connection", "Through the free AnkiConnect add-on", "Whether Surasura reaches Anki now",
                        "ankiconnect status connection"),
    "new_cards_a_day": ("New cards a day",
                        "Anki's own setting for {deck}; changed only when you say so.",
                        "Anki's new cards a day; sets the pace of the target line.",
                        "new cards a day anki per day limit deck pace words per day"),
    "connect_enabled": ("Cards made for you",
                        "Anki Miner makes cards for episodes at the top of Current.",
                        "Cards made for you: when you place an episode at the top of Current, Anki Miner makes its cards "
                        "and Surasura orders them. Needs Anki and Anki Miner. Nothing placed before you turn it on",
                        "cards made for you connect make cards mine automatically anki miner"),
    # row 13 (laptop fixes): *Cards made for you* while Anki Miner isn't found (and Connect is off)
    # S1: what you get (the switch's own line) behind its ? (Kantan-S2); what it needs is its shown line
    # (`catalog.help_line`); *Set up Anki Miner ›* is its Show me
    "connect_needs_miner": ("Cards made for you", CARDS_WHY,
                            "Needs Anki Miner. This switch appears once it's installed.",
                            "connect make cards mine automatically anki miner needs "
                            + NEEDS_MINER),
    # Kantan-MO (PROVISIONAL words): *Words to make cards from* retired — Level decides, this adds the rest
    "connect_every_word": ("Cards for every new word",
                           "Words past your level get cards too; they count toward Keep up to.",
                           "Also make cards for words rarer than your level.",
                           "every new word all unknown words past my level rare words mine all words to make cards "
                           "from which words i+1"),
    # Kantan-SD (PROVISIONAL words): the sentence dial — how a card's sentence is chosen, in plain words
    "connect_sentence_dial": ("Card sentences",
                              "Best looks through your whole library: first a sentence with no other new word, then "
                              "one whose video is there (a book's too, with its audiobook or the AI voice on), then "
                              "one with words you're still learning and from a show you saw lately. Nearest keeps the "
                              "episode's own line.",
                              "Best: the clearest sentence in your library. Nearest: the episode's own line.",
                              "sentence dial best nearest which sentence card sentence line example context young "
                              "words recently learned i+1 better sentence"),
    # Kyou-A (Sonic's answers 1–5, 2026-11-15): the library's own option (settings_store.py) — Mado-PZ2 (Sonic,
    # 2026-11-19): one switch, *Learn two shows at once*; found by "parallel" too, never with it in its name
    "new_cards_from": ("Learn two shows at once",
                       "On: your new cards a day split evenly between Current's first two titles, the most useful "
                       "words first. Off: Current in order. Study its cards first still goes ahead",
                       "On: Current's first two titles side by side. Off: Current in order.",
                       "parallel side by side two shows both shows at the same time new cards top two titles split "
                       "order mine new cards come from"),
    "mine_line": ("Mine automatically", "The files at the top of Current mine themselves the moment they’re placed",
                  "How many files at the top of Current mine themselves", "auto top mines itself mine line"),
    "connect_send_grammar": ("Send grammar words", "Particles and endings get cards too",
                             "Also make cards for particles and endings.", "grammar particles endings send"),
    # Zh-C (PROVISIONAL words): the one line says where the word goes
    "connect_zh_word_audio": ("Word audio from Google",
                              "Sends each new card's word to Google for audio.",
                              "Word audio from Google: each new card's word is sent to Google.",
                              "word audio google text to speech tts "
                              "pronunciation chinese"),
    "connect_open_anki": ("When Anki is closed", "New cards wait until Anki opens; Surasura can open it.",
                          "Opens Anki when you open Surasura, so phone reviews come in.",
                          "closed open anki start session"),
    "connect_backlog_cap": ("Keep up to", "new cards waiting in Anki, for this language. 0: no limit",
                            "Stop making cards when this many new cards on your list wait. 0: no limit.",   # Kyou-SH (PROVISIONAL)
                            "cap backlog waiting keep up to limit"),
    # PRESTUDIED-MINE (3.0.20, PROVISIONAL): Connect waits for an episode's pre-studied mark in the journey
    "connect_prestudied_only": ("Mine only episodes I’ve pre-studied",
                                "Surasura makes an episode’s cards only once you’ve gone through it in the journey "
                                "and marked it pre-studied. Mine now still makes them.",
                                "Waits to make an episode’s cards until you pre-study it in the journey.",
                                "pre-studied prestudied journey ready first only marked study before mine wait"),
    # Kyou-SH2 (PROVISIONAL): Tidy — by itself past 1.5 × the limit; this press past the limit
    "connect_tidy": ("Tidy waiting cards", "Past 1.5 × your limit, Surasura deletes the cards it made that you never "
                                           "studied, down to your limit, lowest first. A copy is kept: Undo in Needs "
                                           "you.",
                     "Deletes now its never-studied cards past your limit; Undo brings them back.",
                     "tidy clean clear delete cards waiting backlog clutter limit cap overflow put back undo restore"),
    # REMAKE (3.0.19, PROVISIONAL): *Make my new cards again…* — every never-studied card in Surasura's deck deleted
    # (a copy kept), then made again by Connect with the best sentence
    "connect_remake": ("Make my new cards again", "Deletes every card in Surasura's deck you never studied, then "
                                                  "Surasura makes them again with the best sentence. A copy is kept.",
                       "Start your new cards clean: the studied ones stay; Put back… brings these back.",
                       "remake make again new cards clean start fresh delete unstudied backlog legacy old rebuild"),
    # a7 (DIAGNOSIS 5): an extra, under More options — the library's folders are always searched
    "connect_video_folders": ("More video folders",
                              "Library folders are searched already. Add others only if needed.",
                              "Extra folders for videos kept outside your library.",
                              "video folders pair moved where videos looked for more"),
    "connect_trust_timing": ("Trust my subtitles’ timing",
                             "No checker here: mine at the subtitles' own times.",
                             "Mine only once subtitles are checked in sync. On: trust them.",
                             "trust timing synced subtitles not timed tsubasa"),
    # Kantan-B2 (PROVISIONAL words)
    "unmined_words": ("Words it won't mine again", "Cards you deleted in Anki",
                      "A card you delete in Anki is never made again by itself. These are its words: allow one again "
                      "and the next episode that has it makes its card", "deleted cards words mine again allow "
                      "never made again record reset"),
    # Michi-T1 (Sonic 2026-11-17; PROVISIONAL: label and line for Sonic)
    "connect_spot_every_episode": ("Check every episode’s audio first",
                                   "Slower: Surasura listens to each episode before its cards, not once a release",
                                   "Surasura listens to a few lines of one episode of each release while it mines, "
                                   "and holds the release if its audio doesn’t say its subtitles’ lines (a dub, "
                                   "another language). On: every episode is listened to before its cards are "
                                   "made. Only with Anki Miner’s speech model on this PC",
                                   "audio check every episode dub language listen speech safe"),
    # Q29: one choice — where your own cards go — and the tag that marks them under it
    "junban_order_all": ("Your own cards", "Your own cards: never marked or suspended as not on your list.",
                         "First: the cards you made yourself go ahead of the cards made for you, in the order "
                         "you made them. In your list's order: they go among the cards made for you, by your list. Either way they "
                         "are never marked or suspended as not on your list", "own cards first order all list manual "
                         "yomitan"),
    "junban_own_tag": ("Their tag", "Every card carrying it is yours too, whenever you made it",
                       "Your own cards' tag: never suspended. Empty: after the first auto card.",
                       "own cards tag immersion manual yomitan"),
    "anki_sync_delay_min": ("Sync Anki after tomorrow's cards change",
                            "Syncs before the first write, then this long after a change.",
                            "Syncs with AnkiWeb before the first write, then this long after changes.",
                            "sync ankiweb delay minute phone"),
    "automation": ("Run things by themselves",
                   "Off stops all background re-ordering and Generate.",
                   "Turn off only on a slow computer.", "automation automatic background off slow"),
    "journey_settle_s": ("Wait before the background Generate", "After your last move",
                         "Seconds after your last move before your journey updates in the background",
                         "journey settle wait seconds background generate"),
    "journey_settle_battery_s": ("…on battery", "The same wait while a laptop runs on its battery",
                                 "Seconds after your last move before your journey updates, on battery",
                                 "journey settle battery laptop seconds"),
    "connect_anki_miner_profile": ("Anki Miner profile", "The Anki Miner profile your cards are made with",
                                   "The Anki Miner profile the cards made for you use", "anki miner profile"),
    "anki_connect_url": ("AnkiConnect address", "Only this computer’s own address (127.0.0.1) is used",
                         "AnkiConnect on this computer only: any other address is refused", "address url ankiconnect"),

    # Junban
    "enable_junban": ("Order your backlog with Surasura",
                      "Moves new cards only — reviews and learning cards are never touched",
                      "Shows 順: reorder your new Anki cards into learn order.",
                      "junban reorder order backlog enable"),
    "junban_scope": ("Which cards", "This deck is chosen in Junban’s window", "This deck, or every deck with new cards",
                     "scope deck all decks choose the deck change the deck which deck mining deck new cards deck "
                     "preview order restore undo the last reorder"),
    # Q31
    "junban_phrases": ("Idioms and set phrases go with your list",
                       "Common phrase cards are ordered like list words.",
                       "On: common set phrases (気がつく) are ordered like list words.",
                       "phrases idioms set phrase list first"),
    # Kyou-MO (the mining model; PROVISIONAL words): your own cards only — Surasura's are never set aside
    "junban_off_list": ("Your own cards", "",
                        "Leave: after your list. Set aside: at the back, tagged ::later.",
                        "not on list rare unlisted leave back set aside later tag own cards"),
    "junban_later_flag": ("…and flag them purple", "", "Set-aside cards get a purple flag. Restore removes it.",
                          "not on list later flag purple set aside"),
    "junban_later_suspend": ("…and suspend them", "", "Set-aside cards are suspended too. Restore undoes it.",
                             "not on list later suspend set aside"),
    "junban_auto_reorder": ("Reorder by itself after Generate", "",
                            "Reorders the saved deck by itself after Generate and on return.",
                            "auto reorder automatic generate"),
    "junban_auto_actions": ("…and tag, flag or suspend then", "The automatic reorder applies Junban's marks too",
                            "Off: auto-reorder only moves cards. On: applies all saved options.",
                            "auto actions tag flag suspend"),
    "put_back": ("Put Anki back", "The way it was before Surasura first changed it",
                 "Puts Anki's new cards back in the order they had before Surasura first changed them, and takes "
                 "Surasura's tags, flags and suspensions off", "put back undo restore first touch"),
    "junban_write_frequency": ("Write Surasura’s rank into a field", "Beside JPDB’s, never instead of it",
                               "Writes the word's place in your list into the note, as one more entry in the frequency "
                               "list. Nothing already there is removed", "frequency rank field write"),
    "junban_frequency_field": ("Field", "", "Which field holds it. Notes without that field are skipped.",
                               "frequency field"),
    "junban_write_freqsort": ("…and overwrite the FreqSort sort number", "Replaces the number Anki’s browser sorts by",
                              "Overwrites Anki's sort number. Restore puts it back. Off by default.",
                              "freqsort sort number overwrite"),
    "junban_tag_markers": ("Tag ✦ ⚖ 📖 markers", "As sub-tags of the tag below",
                           "Adds marker sub-tags (::star, ::reading) for filtered decks.",
                           "markers star lopsided reading tag"),
    # IK-4: glyph tablets again — a tick on each one picked (Q31's rule), never a choice's vein
    "junban_only_markers": ("Only words marked", "None picked: every word",
                            "Reorder only words with these marks; the rest go to the back.",
                            "only markers star lopsided reading filter high leverage"),
    "junban_tag": ("Tag the notes I move", "Empty: no tag",
                   "Tags every moved note. Restore removes the tag.", "tag notes moved"),
    "junban_chunk_size": ("Cards per write", "", "How many cards go to Anki in one request", "chunk cards per write"),

    # Backfill
    "backfill_patterns": ("Fill パターン", "How the word is used",
                          "Backfill fills each card's パターン field: how the word is used", "patterns fill パターン"),
    "backfill_sentence": ("Fill 例文", "Two more sentences from your own content",
                          "Backfill fills each card's 例文 field: two more sentences from your own content",
                          "sentences examples fill 例文"),
    # Kantan-PF (PROVISIONAL words): a card's missing furigana / pitch — Connect's own cards get both whatever these say
    "backfill_furigana": ("Fill ふりがな", "The sentence's reading, when a card has none",
                          "Backfill fills each card's empty SentenceFurigana from its sentence",
                          "furigana reading ruby fill ふりがな"),
    "backfill_pitch": ("Fill アクセント", "The word's pitch accent, when a card has none",
                       "Backfill fills each card's empty PitchPosition: one word only, never a phrase or a name",
                       "pitch accent fill アクセント"),
    "junban_backfill_cards": ("Which cards", "The deck is chosen in Backfill’s window",
                              "All: every card except known new ones. New only: unstudied cards.",
                              "deck cards new all choose the deck preview fill restore fields note "
                                             "type lapis"),
    "junban_backfill_replace": ("Replace what’s already in the field", "Off: only empty fields are filled",
                                "Overwrite what's in the field. Restore puts it back", "replace overwrite"),
    "junban_auto_backfill": ("Fill new cards by itself", "After each reorder",
                             "After a reorder, fill empty fields of unstudied cards only.",
                             "auto backfill automatic fill"),

    # Level
    "level": ("Level", "", "Your level: your list holds the words at least as common as it",
              "level difficulty band rarity automatic"),
    # Kantan-MO (PROVISIONAL words): the list's one study order — Connect, 順 and the journey read it
    "study_order": ("Study order", "The order your cards are made in, 順 sorts them by, and your journey opens on.",
                    "As you'll meet the words in your content, or by leverage first",
                    "study order leverage meet content priority junban order reorder cards order"),
    "strategy": ("Or aim for a coverage %",
                 "Instead of a level: include words until your content reaches this share",
                 "Level, or a target coverage of your content", "coverage mode strategy"),
    "target_coverage": ("Coverage", "The share of your content you aim to know", "Target coverage, in percent",
                        "coverage percent target"),
    "min_count": ("A word must appear at least", "", "Fewer appearances than this and a word is never listed",
                  "min count appear at least"),
    "minutes_per_file": ("Minutes per file", "For the “every N hours” estimate",
                         "How long a file takes you, for the “every N hours” estimate", "minutes per file"),
    "auto_max_words": ("Automatic keeps at least", "Words ahead of you",
                       "Automatic: the commonest level that holds at least this many words.",
                       "automatic max words ahead"),

    # Language & Parsing
    "zh_script": ("Script", "Chinese shown as each file writes it, or all in one script",
                  "Read all Chinese content and known words in one script, so 学习 and 學習 count as one word. Your "
                  "files are not changed", "script simplified traditional chinese"),
    "paren_readings": ("Readings in parentheses",
                       "Kana in brackets after kanji is treated as ruby and left out.",
                       "Drops a kanji's reading written after it in brackets, so it isn't counted twice. Katakana "
                       "there is often a note, so it stays by default", "readings parentheses ruby kana book"),
    "names_katakana": ("Keep katakana names whole", "A katakana name no dictionary spells stays one word, not pieces",
                       "A katakana name no dictionary lists stays one word: ミロ + ナイ → ミロナイ. Repeated sounds and "
                       "laughter stay apart", "names katakana whole"),
    "names_recurring": ("Names the library keeps using",
                        "A katakana run you keep seeing as one is one word.",
                        "Katakana words used together all the time become one word.", "names recurring library"),
    "names_kanji": ("Kanji names (JMnedict)",
                    "A JMnedict name your library uses a lot is one word.",
                    "A person's name cut into kanji is one word when JMnedict lists it and your library keeps using "
                    "it: 奏 + 汰 → 奏汰. Takes effect at the next Generate", "names kanji jmnedict person"),
    "names_work_terms": ("A work’s own terms",
                         "A story's own kanji words, used together, become one word.",
                         "Kanji words a story makes up — 斬魄刀, 写輪眼 — become one word when your library keeps "
                         "using them together. A dictionary word never joins this way", "terms work story kanji"),
    "ignore_names": ("Ignore names",
                     "Names leave your list and never count as new. Off: learn them.",
                     "On: names (田中) are ignored, never counted as new. Next Generate.", "ignore names"),
    "phrases_and_titles": ("Phrases and titles as one word", "予想通り and 元首相 are one word. Off: their parts, 予想 + 通り",
                           "On: phrases like 予想通り or もののけ姫 count as one word.", "phrases titles compound"),
    "pronoun_bases": ("Pronouns with a suffix as one word", "何様 and お前さん are one word. Off: 何 + 様",
                      "On: 俺様, お前さん count as one word. Off: as parts.",
                      "pronouns suffix"),
    "phrase_rows": ("Idioms as rows",
                    "Set phrases you meet often get their own rows: 気がする, 腑に落ちる.",
                    "Adds common dictionary phrases as rows of their own.", "idioms set phrases rows"),
    "exclude_single": ("List one-kanji words only when they’re dictionary words",
                       "One-kanji words are listed only when they stand alone (手). Off: all.",
                       "Particles, endings and name pieces stay off; 手, 目, 顔 are listed.",
                       "one kanji single character exclude"),
    # Kotoba-OP (3.0.17; the name PROVISIONAL for Sonic): off, a show's opening and ending songs are out of the counts
    "count_song_lyrics": ("Count song lyrics (OP / ED)",
                          "Opening and ending songs repeat every episode. Off: their lyrics don't count.",
                          "Off: a show's OP / ED lyrics don't count. Next Generate.",
                          "songs lyrics op ed opening ending karaoke"),
    "how_parsing_works": ("How parsing works", "", "Every rule, with examples — opens in your browser",
                          "how parsing works guide examples"),

    # Content
    "target_language": ("Language", "", "The language you're learning", "language japanese chinese"),
    "soon_line": ("Soon starts after",
                  "A count for now; later based on how much you watch.",
                  "How many files of Current come before Soon", "soon weeks after soon line"),
    # W-1 (Sonic 2026-10-22, Q4): a library's own option, beside its Soon line (settings_store.py)
    "keep_watched": ("Keep studying watched episodes",
                     "Off: watched episodes' words leave your list; their cards move back.",
                     "On: watched episodes keep their words and cards in place.",
                     "watched episode stone keep study list"),
    "library_folders": ("Library folders", "Read in place: keeps a text copy and checks for new episodes.",
                        "The folders Surasura reads where they are", "library folders source read where they are "
                                                                     "stop reading look again manage skipped "
                                                                     "read again"),
    # A7O-6 (Sonic 2026-10-30): named for what it does (was *Start a fresh library*); Fresh library 3.0.1: two choices
    "fresh_library": ("Sort again or start over",
                      "Re-sort your library, or start over like a new PC. Both reversible.",
                      "Re-sort or start over; both can be put back.",
                      "sort library again order tiers fresh reset start over completely everything new pc clear read "
                      "again put back backup restore"),
    # Sonic 2026-11-05 (the mock's rows, "2 lines. One for the term and then a row or 2 for the buttons"); PROVISIONAL
    "open_video": ("Videos open in", "Opens videos with Windows' program or one you choose.",
                   "What ▶ opens a video with", "open play video player program vlc mpv watch"),
    "open_book": ("Books open in", "Opens EPUBs with Windows' program or one you choose.",
                  "What ▶ opens an EPUB with", "open read book epub reader program"),
    "finish_cards": ("When you finish something", "What happens to its new cards in Anki. Leaving them out suspends "
                                                  "and tags them, never deletes them: Undo or Put back brings them "
                                                  "back",
                     "What finishing something does to its new cards in Anki",
                     "finish finished done new cards keep leave out suspend order"),
    "split_books_by": ("Split books by", "Each book you add: its chapters, each cut into parts; or even parts across "
                                         "the book. Books already in keep their parts",
                       "How a book is cut into parts when you add it", "split books chapters even parts epub"),
    "split_length": ("Split books into parts of", "EPUBs and Anki decks, when you extract them",
                     "The character limit for each part when a file is split", "split epub length extract add from"),
    # a9.1: *Add from* went — Extract… and YouTube… are in + Add; *Preview a video…* is on its switch's row
    "enable_youtube_transcripts": ("YouTube transcripts", "Download a video’s captions straight into your library, "
                                                          "from + Add",
                                   "Show the transcript downloader (YouTube and bilibili.tv) in + Add",
                                   "youtube transcripts download add from bilibili"),
    "enable_youtube_preview": ("YouTube preview", "Score a video against your words before you add it",
                               "Show 'Preview against library' and keep word counts ready.",
                               "youtube preview score a video"),

    # New arrivals
    "placing_rules": ("Where new arrivals go", "A show's next episode joins it; the rest wait in New arrivals.",
                      "A source, and where its arrivals go", "where new arrivals go rules source hato youtube channel "
                      "wait top"),

    # Connections
    "anki_miner": ("Anki Miner", "Makes your cards from your own videos. Free, made by Zero.\n"
                                 "He's awesome. Please give him some love :)",     # (a no-break space: ":)" never alone)
                   "Anki Miner's state, and what it still needs", "anki miner install setup"),
    "hato": ("Subtitles for videos without them",
    "Finds subtitles for your shows, and sends new episodes to New arrivals",
             "Whether hato is installed", "hato install houseki suite subtitles"),
    "practice_ai": ("Practise with your AI",
                    "Your AI quizzes you. What it's told goes to that AI's company.",
                    "Copy the setup, paste it to your AI. Try a short story.",
                    "piyo ぴよ practice practise ai claude codex desktop mcp chat tutor copy setup"),
    "practice_keep_rounds": ("Keep practice rounds",
                             "Rounds stay on this PC to redo. Off: nothing is kept.",
                             "Keep each practice round in User Files, to redo and build on.",
                             "practice rounds keep save again history context ai"),
    "jimaku": ("jimaku", "Subtitles for anime. Its key will come from hato", "jimaku's key, through hato",
               "jimaku key api subtitles"),
    "anilist": ("AniList", "Adds your AniList shows to New arrivals; fetches subtitles, never video.",
                "AniList", "anilist anime list account subtitles"),
    "more_from_houseki": ("More from Houseki",
                          "Each tool works alone, better together. New ones appear here.", "More tools from Houseki",
                          "houseki suite install tools"),

    # Journey
    "theme": ("Look", "", "Your journey's look", "theme look dark flow report journey"),
    "open_app_mode": ("Open in its own window",
                      "Own browser window, so Yomitan still works. Off: a tab.",
                      "Open your journey in its own browser window", "open window tab browser"),
    "source_display": ("Where a sentence came from", "", "Show which file each example sentence came from",
                       "source badge file name"),
    "word_search_enabled": ("Word lookup button (⌕)", "More real sentences from Nadeshiko",
                            "A search icon beside each word, opening more real sentences on Nadeshiko",
                            "word lookup search nadeshiko"),
    "anki_backlog_on_generate": ("Label words already in Anki",
    "A word whose card is already waiting in Anki is marked",
                                 "Mark words that already have a new card waiting.",
                                 "label backlog anki waiting card mark"),
    # The journey's line player — PROVISIONAL words (the default is settings_manager's `line_player`)
    "line_player": ("Play a line's own audio",
                    "▶ plays the sentence from its episode, repeated with a pause.",
                    "Play each sentence's own audio on your journey, looped with a pause",
                    "play line audio loop repeat chorus listen pause"),
    "word_search_category": ("Lookup examples from", "", "Which kind of sentences the lookup opens",
                             "lookup nadeshiko category anime"),
    "enable_koe": ("Speak sentences (Gemini)", "On your own key; each sentence goes to Google to be spoken",
                   "Hear a sentence read aloud (Gemini key; sentence goes to Google).",
                   "speech speak koe gemini voice"),
    "koe_door": ("Speech settings", "The key, voice and delivery", "Set the API key, voice and delivery",
                 "speech settings voice key"),

    # Sentences
    # E-LENGTH (PROVISIONAL, the sentence choice's spec § 9 A4): once the sentence table is on, *Length* is the length
    # a learner likes best — its ? one line, nothing under the label
    "sentence_length": (("Length", "The sentence length you like best. Others are still used, a little later.",
                         "The sentence length you like best", "length chars sentence") if SENTENCE_TABLE >= 1 else
                        ("Length", "Shorter or longer ones are still used, just later",
                         "Preferred length for example sentences", "length chars sentence")),
    "max_contexts": ("Up to", "", "Most example sentences per word", "max sentences per word"),
    "ensure_audio_example": ("Always include one with audio", "",
                             "A word always gets one video example, so you can hear it.", "audio example video"),
    "only_i_plus_one": ("Only i+1 sentences", "Every other word already known",
                        "Swaps a media sentence for an i+1 example when it isn't i+1.", "i+1 only"),
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
                             "An Anki-ready CSV with sentences from your journey", "csv sentence list anki export"),
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
    "update_check_enabled": ("Check for updates", "Checks GitHub for a new version at start. Off: no request.",
                             "Check GitHub at start for a new Surasura or Anki Miner.",
                             "update check updates new version github offline privacy network"),
    "auto_update_enabled": ("Update automatically", "One click for small releases",
                            "One-click updates for small releases; big ones by hand.",
                            "update automatic"),
    # Michi-LP (PROVISIONAL words): the Beta list's switch, and Connect's clips at once (More options)
    "connect_low_priority": ("Run Anki Miner at low priority",
                             "Mining waits for whatever else you run, so cards take longer",
                             "Beta: Anki Miner and its clip cutting use only the CPU nothing else wants",
                             "low priority anki miner ffmpeg cpu fans slow busy beta idle"),
    "connect_clip_cuts": ("Clips cut at once",
                          "Fewer: a quieter PC while cards are made. Automatic: from this PC, fewer on battery",
                          "How many clips Anki Miner cuts at the same time. Anki Miner's own setting stays as it is",
                          "clips cut parallel ffmpeg workers cpu fans laptop desktop load"),
    # Iro-AA, moved to *Card sound* by VOICE-SETUP (PROVISIONAL words): the AI voice, still a beta
    "ai_audio": ("AI voice", "A voice made on this computer reads a card's sentence when no real sound is found for it. "
                 "Nothing is sent anywhere.",
                 "Use the AI voice (beta) for cards with no real sound",
                 "ai audio voice tts beta irodori sentence card sound made ahead test pack"),
    "card_sound_add": ("Add sound", "Cards with no sentence audio get the sound of their own line, from your episode or "
                                    "its audiobook. Only empty fields are filled.",
                       "Puts real sound on every card that can get it now; Undo takes it off again.",
                       "add sound audio sentence audio clip episode audiobook cards missing silent fill"),
    "card_sound_remove_ai": ("Remove all AI audio", "Takes the AI voice's clips off your cards. A copy of each is kept, "
                                                    "so Undo puts them back.",
                             "Removes the AI voice's sound from your cards; your own audio stays.",
                             "remove ai audio voice tts clips delete undo sound"),
    "telemetry_enabled": ("Anonymous usage counts", "No words, files or content — ever",
                          "Send anonymous usage counts", "telemetry anonymous usage"),
    # a9.1: the one way to the logs (the bar's *Open the logs folder* went; Send report carries them), beside the
    # data folder (the *Version* row's door until a9.1)
    "logs": ("Folders", "Your library's data, and the logs Surasura keeps", "Opens the folder in your file manager",
             "log logs processing log data folder files"),
    "data_credits": ("Data credits", "The dictionaries and word lists used, with licences.",
    "Every data source, with its licence",
                     "data credits licence license jmdict jmnedict unidic cedict jpdb jiten"),
    # a9.1 (Sonic: "combine the rows for website, github, and discord into one"): a block, a button per page
    "surasura": ("Connect with us", "", "Surasura's pages, each in your browser",
                 "connect with us website homepage home page site web download surasura.dev discord community help "
                 "chat support join server star github stars like repository source"),
    "version": ("Version {version}", "", "Copies the version number, for a message or a report", "version copy about"),
    "set_up_again": ("Set up again", "Walks through the first steps again", "Opens the setup again",
                     "set up again wizard setup"),
    "settings_file": ("Your settings", "Save settings to a file, or load them from one.",
    "Export or import every setting",
                      "settings export import save backup move new computer pc file"),
    # --- W3.2 L3: Connections' covers (the window's spec 01 §1.3: the switch says in one line what is sent)
    # 3.0.1 item 5 (AA-1, PROVISIONAL): the same switch asks AniList whether a show near its end is still airing
    "covers_download": ("Download covers", "Sends AniList a show's name or id, YouTube a video's id. Nothing else.",
    "Fetch covers from AniList or YouTube; checks if a "
                                                               "show still airs.",
                        "covers download pictures anilist thumbnails posters"),
    "remove_downloaded_covers": ("Remove downloaded covers", "The pictures you chose and those beside your files stay",
                                 "Delete downloaded covers; pictures beside your files come back.",
                                 "remove delete downloaded covers cache pictures"),
    # --- end W3.2 L3
}

# *Count as known in Anki* with two states or more picked: its line names them (`settings_catalog.help_line`)
KNOWN_ALL_OF = "Counts only cards that are {states}, all at once"
KNOWN_FLAGS = "A card has one flag at a time: {flags} counts no card"           # two flags picked (A7S-7)
# Kotoba-WS2: a pick saved before holds red or green, which never count (the review loop's Ignore and Swap)
KNOWN_RED_GREEN = "Your Swap and Ignore flags never count as known: pick again"          # Kotoba-WS2 (PROVISIONAL)

# Backfill's fills by name (`junban_backfill_fills`' values): its four switches, and Your setup's line
FILLS = {"patterns": "パターン", "sentence": "例文", "furigana": "ふりがな", "pitch": "アクセント"}

# --- the choices: row id -> {value: label}; choice cards also have a line under each -------------------------------- #
OPTIONS = {
    "surasura": {name: label for name, (label, _tip, _url) in LINKS.items()},      # its buttons (searched as choices)
    "known_road": {"anki": "Anki", "import": "Import a list"},
    "connect_open_anki": {False: "Wait for me", True: "Open Anki for me"},
    "junban_order_all": {False: "First, in the order you made them", True: "In your list’s order"},
    "known_from_anki": {"suspended": "Suspended", "marked": "Marked", "flag:1": "Flag 1 (Red)",
                        "flag:2": "Flag 2 (Orange)", "flag:3": "Flag 3 (Green)", "flag:4": "Flag 4 (Blue)",
                        "flag:5": "Flag 5 (Pink)", "flag:6": "Flag 6 (Turquoise)", "flag:7": "Flag 7 (Purple)"},
    "junban_scope": {"deck": "This deck", "all": "All decks"},
    # Mado-LT: a move's flag, said as the move is (one formula: what you do to the card)
    "loop_swap_flag": {n: f"Suspend + {colour} flag" for n, colour in enumerate(
        ("Red", "Orange", "Green", "Blue", "Pink", "Turquoise", "Purple"), 1)},
    "loop_ignore_flag": {n: f"Suspend + {colour} flag" for n, colour in enumerate(
        ("Red", "Orange", "Green", "Blue", "Pink", "Turquoise", "Purple"), 1)},
    "swap_in_place": {True: "Same card, new sentence", False: "A new card"},          # FS-2 (PROVISIONAL)
    "study_order": {"content": "As I’ll meet it", "priority": "By leverage"},
    "connect_sentence_dial": {"best": "Best", "nearest": "Nearest"},
    "split_books_by": {"chapters": "Chapters", "even": "Even parts"},
    "open_video": {"default": "Your default player", "program": PROGRAM_PICK},     # "program": its name once chosen
    "open_book": {"default": "Your EPUB reader", "program": PROGRAM_PICK},
    "finish_cards": {"ask": "Ask each time", "keep": "Keep its cards", "out": "Leave them out"},
    "junban_off_list": {"leave": "Leave them", "back": "At the back", "aside": "Set aside"},
    "junban_only_markers": {"star": "✦", "lopsided": "⚖", "reading": "📖"},
    "backfill_patterns": {"patterns": FILLS["patterns"]}, "backfill_sentence": {"sentence": FILLS["sentence"]},
    "backfill_furigana": {"furigana": FILLS["furigana"]}, "backfill_pitch": {"pitch": FILLS["pitch"]},
    "junban_backfill_cards": {"all": "All", "new": "New only"},
    "strategy": {"freq": "Level", "coverage": "Coverage %"},
    "zh_script": {"asis": "As written", "s": "Simplified", "t": "Traditional"},
    "paren_readings": {"hiragana": "Hiragana", "any": "Any kana", "off": "Off"},
    "target_language": {"ja": "日本語", "zh": "中文"},
    "placing_rules": {"wait": "Wait here, in New arrivals", "top": "Top of Current", "after-show": "After its show",
                      "soon": "Soon", "goal": "Goal", "finished": "Finished"},
    "theme": {"Default (Dark)": "Default (Dark)", "Dark Flow": "Dark Flow", "Midnight (Vibrant)": "Midnight (Vibrant)",
              "Modern Light": "Modern Light"},
    "source_display": {"off": "Hidden", "icon": "Icon", "filename": "File name", "full": "Icon + file name"},
    "word_search_category": {"all": "All", "anime": "Anime", "liveaction": "Live action", "youtube": "YouTube"},
    "text_size": {"S": "Small", "M": "Medium", "L": "Large"},
    "app_motion": {"follow": "Follow Windows", "full": "Full", "reduced": "Reduced"},
    "connect_clip_cuts": {"auto": "Automatic", 1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6"},
}
CLIP_CUTS_AUTO = "Automatic · {n} here"         # Michi-LP: the number Automatic picks on this PC now
# The line under each choice card (Connect's own words, P3.1)
OPTION_LINES = {}
# An option's own tooltip (a choice's or a tablet's), where its label alone doesn't say it
OPTION_TIPS = {
    "junban_only_markers": {"star": "High leverage: the words your journey stars",
                            "lopsided": "Lopsided: words that come almost entirely from one part of your library",
                            "reading": "Reading: words you'll read but essentially never hear"},
    "swap_in_place": {True: "The card keeps its reviews and due date; its sentence, audio and picture change.",
                      False: "A new card from the better sentence; the old one leaves your reviews."},     # FS-2
    "junban_order_all": {False: "Your own cards go ahead of the made-for-you cards.",
                         True: "Your own cards go among the made-for-you cards, in list order."},
    "open_video": {"default": "▶ opens a video in the program Windows opens it with",
                   "program": "▶ opens a video in a program you choose"},       # once chosen: its path
    "open_book": {"default": "▶ opens an EPUB in the program Windows opens it with",
                  "program": "▶ opens an EPUB in a program you choose"},
    "finish_cards": {"ask": "Finishing asks: keep its cards in order, or leave them out.",
                     "keep": "Its new cards stay in your order, as they are",
                     "out": "Its new cards leave your order: suspended and tagged, never deleted."},
}

# --- P4: the live rows (settings_live.py): Your setup, the level readout, the statuses, App's rows, the credits, Export
SEP = " · "
# Your setup's lines (each says less when a fact can't be read: never a wrong number)
SETUP_KNOWN = "{n:,} known"
SETUP_FROM_ANKI = "from Anki ({decks})"
SETUP_IMPORTED = "from an imported list"
SETUP_CONNECT_OFF = "Off: you make your cards yourself"
SETUP_MINE_WORDS = {False: "Your list", True: "Every new word"}     # Kantan-MO: *Cards for every new word* off / on
SETUP_AUTOMATIC = "Automatic"
SETUP_WORDS = "≈{words:,} words"
SETUP_COVERAGE = "{coverage}% of your content"                                  # S4: never "% known"
SETUP_ORDER = {"content": "ordered as you’ll meet them", "priority": "ordered by leverage"}
SETUP_NOT_ORDERED = "not reordered"
SETUP_ORDER_OFF = "kept in order by itself: off"                # Fresh-U row 2: 順 on, its automatic order off
SETUP_FILLED = "{fills} filled {how}"
SETUP_FILLED_AUTO = "automatically"
SETUP_FILLED_HAND = "by hand"
SETUP_NOTHING_FILLED = "nothing filled"
SETUP_DECK = "“{deck}”"                 # Kantan-T (PROVISIONAL): *Cards in Anki* leads with Junban's deck
# Kantan-T (PROVISIONAL): *Which cards* names Junban's deck in sight (the deck setup picked; *Junban…* beside it changes it)
JUNBAN_DECK_LINE = "Deck: “{deck}”"
JUNBAN_NO_DECK = "No deck chosen yet"
JUNBAN_ALL_DECKS = "Every deck with new cards"     # *All decks*: still a line in sight (a choice never moves the page)
# The level readout under the slider, when the time between meetings is under an hour, or unknown
READOUT_HOURS = "≈{words} words · {coverage}% of your content · about every {hours} hours"   # S4
READOUT_MINUTES = "≈{words} words · {coverage}% of your content · about every {minutes} minutes"
READOUT_NO_TIME = "≈{words} words · {coverage}% of your content"
# Connection (Anki): the emerald's words (S6: never colour alone)
ANKI_WORDS = {
    "connected": "connected", "closed": "Anki is closed", "busy": "Anki is open but isn’t answering",
    "no_addon": _addon.NO_CONNECT, "unsure": _addon.UNSURE,               # AnkiConnect may be missing: the wizard's
    "denied": "Anki hasn’t let Surasura in yet", "failed": "the last sync from Anki didn’t finish",
    "syncing": "reading Anki…", "checking": "checking…", "unknown": "not checked yet",
}
ANKI_TIP = "Whether Surasura reaches Anki now, through AnkiConnect"
CHECK_LIVE_TIP = "Ask Anki now if AnkiConnect answers.\n• It also checks every few seconds."
INSTALLED_PLAIN = "installed"
# App's rows
LOGS_OPEN = "Logs"
LOGS_OPEN_TIP = "Open the logs folder, to look or send."
DATA_FOLDER = "Data folder"
DATA_FOLDER_TIP = "Opens the folder your library's data is kept in"
VERSION_COPY = "Copy"
VERSION_COPIED = "Copied"
VERSION_COPIED_LINE = "Surasura {version} is copied"
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
TIDY_NOW = "Tidy now"                       # --- Kyou-SH2: *Tidy waiting cards*' button (PROVISIONAL)
TIDY_DONE = "{n} cards tidied · Undo in Needs you"
TIDY_DONE_ONE = "A card tidied · Undo in Needs you"
TIDY_NONE = "Nothing to tidy: {why}"
TIDY_CANT = "Not tidied: {why}"
# Kyou-SH3 part 2 (PROVISIONAL): *Put back…* — the last 10 tidies, each with its Undo
TIDY_PUT_BACK = "Put back…"
TIDY_PUT_BACK_NAME = "Put back an earlier tidy"
TIDY_PUT_BACK_TIP = "Put back the cards an earlier tidy deleted."
TIDY_PUT_BACK_NONE = "No tidy yet: nothing to put back."
TIDY_PUT_BACK_UNREAD = "Couldn't read the tidies just now: try again in a moment."
TIDY_PAST = "{when} · {n} cards"
TIDY_PAST_ONE = "{when} · 1 card"
TIDY_PAST_BACK = " · put back"
TIDY_PAST_GONE = " · its copy is missing"
TIDY_PAST_TIP = "Put these cards back in Anki."
TIDY_PAST_BACK_TIP = "Already put back: a tidy goes back once."
TIDY_PAST_GONE_TIP = "Its copy isn't on disk any more, so it can't go back."
# REMAKE (3.0.19; PROVISIONAL words): *Make my new cards again…*'s press, its sheet and its answers
REMAKE_NOW = "Make my new cards again…"
# --- AUDIO-FILL (PROVISIONAL words): *Card sound*'s two presses
SOUND_ADD = "Add sound"
SOUND_COUNT = "{n:,} cards can get sound now"
SOUND_COUNT_ONE = "1 card can get sound now"
SOUND_COUNT_NONE = "Every card that can get sound has it"
SOUND_COUNT_TIP = "Counted the last time Surasura looked at your cards"
SOUND_REMOVE = "Remove all AI audio…"
SOUND_REMOVE_NONE = "No card has AI audio"
SOUND_REMOVE_ASK = "Remove the AI audio from {n:,} cards?"
SOUND_REMOVE_ASK_ONE = "Remove the AI audio from 1 card?"
SOUND_REMOVE_BODY = ("Only the AI voice's clips go; your own audio and real sound stay. A copy of each is kept: Undo "
                     "puts them back.")
SOUND_REMOVE_VOICE_ON = "The AI voice is still on, so cards due soon get it again. Switch it off above to keep them silent."
SOUND_REMOVE_YES = "Remove"
SOUND_REMOVE_YES_TIP = "Takes the AI clips off these cards now"
SOUND_REMOVED = "The AI audio is off {n:,} cards"
SOUND_REMOVED_ONE = "The AI audio is off 1 card"
SOUND_CANT = "Not done: {why}"
SOUND_BACK = "The AI audio is back on {n:,} cards"
SOUND_BACK_KEPT = "The AI audio is back on {n:,} cards · {k:,} you changed since keep yours"
REMAKE_ASK = "Delete {n} new cards and make them again?"
REMAKE_ASK_ONE = "Delete 1 new card and make it again?"
REMAKE_ASK_BEFORE = "Delete the {n} cards from before Surasura and make them again?"
REMAKE_ASK_BEFORE_ONE = "Delete the 1 card from before Surasura and make it again?"
REMAKE_DONE_LATER = "{n} cards deleted · made again once your library is free · Put back… to undo"
REMAKE_COUNTS = "Made by Surasura, never studied: {made}"
REMAKE_KEPT = "Kept: {kept} ({whys})"
REMAKE_SYNC = "Anki syncs before and after the copy is made, so a card you study on your phone stays."
REMAKE_EDITS = "Edits you made to these cards go with them; they stay in the copy. Put back… brings them all back."
REMAKE_BEFORE = "Also the {n} cards from before Surasura"
REMAKE_BEFORE_ONE = "Also the 1 card from before Surasura"
REMAKE_BEFORE_TIP = "Cards of the same note type in Surasura's deck that Surasura didn't make. Off: they stay."
REMAKE_YES = "Delete and make again"
# the pace is the backlog cap (`connect_backlog_cap`, *Keep up to*, the row above), never a daily rate: Connect refills
# up to it as fast as it mines, then more as the learner studies (REMAKE 3's words fix; PROVISIONAL)
REMAKE_PACE = "Surasura makes them again: up to {cap} waiting in Anki (Keep up to, above), then more as you study."
REMAKE_PACE_ALL = "Surasura makes them all again as it mines (Keep up to, above: 0, no limit)."
REMAKE_YES_TIP = "Deletes them now. Surasura makes them again: up to {cap} waiting (Keep up to), then more as you study."
REMAKE_YES_TIP_ALL = "Deletes them now. Surasura makes them all again as it mines (Keep up to: 0, no limit)."
REMAKE_DONE = "{n} cards deleted · {q} to make again · Put back… to undo"
REMAKE_STUDIED = " · kept, you studied them meanwhile: {words}"
REMAKE_NONE = "Nothing to make again: {why}"
REMAKE_CANT = "Not done: {why}"
EXPORT_NEXT = "Save as…"
EXPORT_NEXT_TIP = "Choose where the file goes"
EXPORT_FORMAT_NAME = "Format"
EXPORT_CONFIRM_TIP = "Goes on to choose where the CSV goes"
EXPORT_RUNNING = "Exporting {name}…"
EXPORT_BUSY = "Another export is running: one at a time"

# --- P8: Connect's switch, the Anki Miner card, *New cards a day* (settings_connect.py) ------------------------------ #
# Connect's switch: its outcome in the bar (the Tk log's words, `app/connect/switch.py`) and 2.x's two questions
SWITCH_NOT_ON = "Cards made for you wasn't switched on: {}. Nothing changed; try again."
SWITCH_NOT_OFF = "Cards made for you wasn't switched off: {}. It stays on; try again."
SWITCH_BROKE = "Cards made for you's switch didn't finish: {}. It shows what is saved."
SWITCH_ALREADY_ON = "Cards made for you was already on (switched on in another window): nothing else changed."
PUT_BACK_ASK = "Put the {n} shelved {cards} back into your new cards?"
PUT_BACK_BODY = ("Cards made for you turns off either way, on Leave them or Esc too: the cards then stay on the shelf, suspended "
                 "until you put them back.")
PUT_BACK_YES = "Put them back"
PUT_BACK_YES_TIP = "Shelved cards return to your new cards; the switch turns off."
PUT_BACK_NO = "Leave them"
PUT_BACK_NO_TIP = "Cards made for you turns off; shelved cards stay suspended (Esc)."
OFF_ANYWAY_ASK = "Turn Cards made for you off anyway?"
OFF_ANYWAY_BODY = ("Some shelved cards weren't put back:\n{failed}\n\nThe cards on the shelf stay suspended until you "
                   "put them back.")
OFF_ANYWAY_YES = "Turn it off"
OFF_ANYWAY_YES_TIP = "Cards made for you turns off; shelved cards stay suspended."
OFF_ANYWAY_NO = "Keep it on"
OFF_ANYWAY_NO_TIP = "Cards made for you stays on (Esc does the same)"
STAYS_ON = "Cards made for you stays on: put the shelved cards back from its window, or turn it off again."
# The Anki Miner card (U5, U6; AM★: the star line beside Install). The Tk panel's words.
MINER_CHECKING = "Checking…"
# Michi-DK (PROVISIONAL): Anki Miner's own deck isn't the one Surasura shows — both named (Surasura's cards go to its
# own; Anki Miner never lets another program change the deck its window mines into)
MINER_DECKS = "Surasura's cards go to “{ours}” · cards you mine in Anki Miner go to “{own}”"
MINER_NOT_CHECKED = "Couldn't check Anki Miner: {}"
MINER_STEP_1 = "1. In Anki Miner: Manage profiles… → New, and name it Surasura."
MINER_STEP_2 = "2. In that profile's Settings: Whitelist → choose file, and pick this file:"
MINER_STEP_BOLD = "Also turn on Bold the word in the sentence."
MINER_PATH_NAME = "The whitelist file's path"
# A6: the practice server's Copy buttons (Connections' *Piyo ぴよ — practise with your AI*), one per AI app (mcp_server.APPS)
PRACTICE_APPS = {"claude-code": "Claude Code", "codex": "Codex", "claude-desktop": "Claude Desktop"}
PRACTICE_COPY_TIP = "Copy the setup for {app}: paste it there, or follow it yourself."
PRACTICE_COPIED = "Copied"
PRACTICE_COPIED_LINE = "The setup for {app} is copied: paste it to {app}."
# A7 (Sonic's first try, 2026-10-30: "How do i start piyo conversation?"): under the Copy buttons, both ways to start a
# round (the slash form, its words and example: app/cli/mcp_server.SLASH_EXAMPLE and the prompt's arguments, a test keeps
# them equal; the sources from Anki from their one table; the plain request: app/practice.STARTER)
PRACTICE_THEN = ("Then, to start a round:\n"
                 "• In Claude Code, type /surasura:practice and four words: how many (1–20) · who's talking (friend, "
                 "coworker, boss, customer, senpai, kohai, shopkeeper, teacher, child) · what kind (chat, reading: a "
                 "short story, quiz, produce: say words you know) · from what (soon: the next words on your journey, top: your list's top words, "
                 "mix; from Anki: " + ", ".join(ANKI_SOURCES) + "). Type / and it's listed as /surasura:practice "
                 "(MCP).\n"
                 "• For example: /surasura:practice 5 friend reading soon\n"
                 "• Or, in Claude Code, Codex or Claude Desktop, just say it: “{starter}”")
# A7 (Sonic, 2026-10-30: the row's words no longer than *Download covers*'): what leaves and how to start, behind its ?
PRACTICE_HELP = "?"
PRACTICE_HELP_NAME = "About Piyo"
PRACTICE_HELP_CLICK = "<br>• Click: its help card"
HELP_MARK_CARD = "{text}\n• Click: its help card"         # a row's ? whose area has a help card
PRACTICE_LEAVES = ("<b>What leaves:</b> your AI app runs Surasura on this computer. What Surasura tells it (your known "
                   "words, your next words, lines from your library, what you kept from past rounds) goes to "
                   "that AI's company, as anything you type there does. Nothing else leaves.")
PRACTICE_STARTER = "Copy a starter message"
PRACTICE_STARTER_TIP = "Copies a first message for your AI: a short story, 5 words."
# Kantan-B2 (AUDIT A4, finding 10; PROVISIONAL): Piyo's row says its last round, so a learner sees it worked
PIYO_LAST_ROUND = "Last round: {date} · {n:,} words"
PIYO_LAST_ROUND_ONE = "Last round: {date} · 1 word"
PIYO_NO_ROUND = "No round yet: paste the setup into your AI."
PIYO_NOT_KEPT = "Rounds aren't kept: Keep practice rounds is off"
PIYO_ROUND_TIP = "Your newest practice round with Piyo, as kept on this computer"
PRACTICE_STARTER_COPIED_LINE = "The starter message is copied: paste it to your AI."
COPY_PATH = "Copy path"
COPY_PATH_TIP = "Copy the whitelist file's path, to paste into Anki Miner's file chooser."
PATH_COPIED = "The whitelist file's path is copied: paste it into Anki Miner's file chooser."
INSTALL_MINER = "Install Anki Miner…"
INSTALL_MINER_TIP = "Get Anki Miner, free, from GitHub.\n• Asks before it downloads"
# A5F2: what only Anki Miner's installer brings (an older Anki Miner, its ffmpeg): the same route, as the update
UPDATE_MINER_BUTTON = "Update Anki Miner…"
UPDATE_MINER_BUTTON_TIP = "Get the Anki Miner Surasura works with, free, from GitHub.\n• Asks before it downloads"
BROWSE_MINER = "Browse…"
BROWSE_MINER_TIP = "Anki Miner is installed somewhere else: show Surasura where."
BROWSE_MINER_TITLE = "Where is Anki Miner?"
BROWSE_MINER_FILTER = "Anki Miner (AnkiMiner.exe);;Programs (*.exe);;All files (*)"
OPEN_MINER = "Open Anki Miner"
# A4M1-2 (lean taken, PROVISIONAL): its own window, for its own settings — Surasura never needs it opened. Choice 87
# (Sonic, 2026-11-09: "say so in hover"): the profile Connect mines with, as the card's check found it
# (`setup.checks`' `anki_miner.profile_name`; `choose_profile`: the setting's, else your usual one), named once checked
OPEN_MINER_TIP_PLAIN = "Open Anki Miner's own window.\n• Surasura never needs it open."
OPEN_MINER_TIP = "Open Anki Miner's own window.\n• Cards use its “{profile}” profile: another profile's don't apply"
OPEN_MINER_TIP_CURRENT = "Open Anki Miner's own window.\n• Cards use the settings it shows."
FINISH_MINER_SETUP = "Finish its setup…"
FINISH_MINER_SETUP_NO_WIZARD = "The setup couldn't open here: close Settings and press Finish its setup again."
FINISH_MINER_SETUP_TIP = "Finish Anki Miner's dictionaries, deck and note type.\n• Nothing to open."
MINER_NOT_OPENED = "Couldn't open Anki Miner: {}"
MINER_ALREADY_OPEN = "Anki Miner is already open."       # Disc-T1: its window's marker found (PROVISIONAL words)
CHECK_AGAIN = "Check again"
CHECK_AGAIN_TIP = "Look at Anki Miner's setup again."
STAR_LINE = "Like Anki Miner? Star it on GitHub ★"
STAR_LINE_TIP = "Opens Anki Miner's GitHub page; Star is top right (needs an account)."
STAR_ASK = "Anki Miner is free and made by one person. A ⭐ on GitHub helps other learners find it."
STAR_BUTTON = "⭐ Star Anki Miner on GitHub"
STAR_BUTTON_TIP = "Star is top right; it needs a GitHub account."
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
NEW_CARDS_FIELD_TIP = "The number to set in Anki; nothing changes until you press Change."
NEW_CARDS_UNREAD_TIP = "{why} Until Anki is readable: your journey's new words a day."
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
SETTINGS_EXPORT_TIP = "Save every setting to one file. No library, known words, lists or keys."
SETTINGS_EXPORT_TITLE = "Save your settings"
SETTINGS_IMPORT = "Import settings…"
SETTINGS_IMPORT_TIP = "Replace all settings with an exported file. Yours are backed up first."
SETTINGS_IMPORT_TITLE = "Import settings"
SETTINGS_FILES = "Surasura settings (*.json)"
SETTINGS_IMPORT_YES_TIP = "Replace your settings, keep a dated copy, then restart."
SETTINGS_IMPORT_NO = "Cancel"
SETTINGS_IMPORT_NO_TIP = "Keep your settings as they are"
SETTINGS_IMPORT_AFTER_GENERATE = "Import your settings once Generate finishes: Surasura restarts to use them"
SETTINGS_FAILED = "Couldn't do that: {why}"

# --- SRC W1b: *Library folders* (settings_sources.py) ------------------------------------------------------------ #
SOURCES_ADD = "Add a folder…"
SOURCES_ADD_TIP = "Read another folder in place.\n• New shows wait in New arrivals."
SOURCES_LOOK = "Look again"
SOURCES_LOOK_TIP = "Look in every folder for new episodes now (Refresh does the same)."
SOURCES_STOP = "Stop reading"
SOURCES_STOP_TIP = "Stop checking {path} for new episodes.\n• Its {n:,} episodes stay in your library"
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
SOURCES_READ_AGAIN_TIP = "Read {path} again.\n• Files return at once; new shows wait in New arrivals."
SOURCES_READ_AGAIN_DONE = "{path} is read again: its files come back into your library"
# Q7: *Skip a folder…* under them (the wizard's picker and its refusal's words: `wizard_strings.SKIP_TITLE`,
# `FOLDER_REFUSED`; the toast: `strings.ITEM_SKIPPED`, ⋯'s)
SOURCES_SKIP = "Skip a folder…"
SOURCES_SKIP_TIP = ("Never read a folder inside one that is read.\n• Its files go to the trash for 30 days; Undo "
                    "brings them back")
# (Sonic's lean B, 2026-10-24, PROVISIONAL: it turns until saved; its line and Undo in this window, the toast's one Undo)
SOURCES_SKIP_UNDO_TIP = "Undo the skip: its files return to your library."
SOURCES_SKIP_SWITCHED = "Nothing skipped: the library changed to another language meanwhile"
# Row 32 (laptop round 4): the page's summary, and the folders in their own window (*Manage folders…*)
SOURCES_FOLDERS = "{n:,} folders"
SOURCES_FOLDERS_ONE = "1 folder"
SOURCES_AWAY_N = "{n:,} not reachable now"
SOURCES_SKIPPED_N = "{n:,} skipped"
FOLDERS_NAME = "Library folders"
FOLDERS_LINE = "Surasura reads these folders where they are and looks in them again for new episodes."

# --- K7 + Fresh library 3.0.1: *Sort again or start over…* (settings_sources.py: FreshRow, the sheet) -------------- #
FRESH_OPEN = "Sort again or start over…"
FRESH_TIP = "Sort again from scratch, or start over like a new PC. Reversible."
FRESH_RUNNING_TIP = "Sorting your library again…"
FRESH_SETTING_ASIDE = "Setting your order aside…"
FRESH_GENERATING = "A Generate is running: once it has finished, this can go on."
FRESH_UPDATING = "An update is being installed: once it has finished, this can go on."
FRESH_SHEET = "Sort again or start over"
FRESH_CLOSE = "Close"
FRESH_CLOSE_TIP = "Close. Nothing is changed.\n• Esc"
FRESH_BACK = "Back"
FRESH_BACK_TIP = "Back. Nothing is changed.\n• Esc"
FRESH_SORT_HEAD = "Sort my library again"
FRESH_SORT_BODY = ("Your folders, known words and settings stay. Your order, tiers, Finished and New arrivals go into "
                   "a backup. Surasura reads your folders again and you sort each title.")
FRESH_SORT_CARDS = "Shows you sort into your top 20 get cards, as when you drag them there."      # FL-1, Connect on
FRESH_SORT = "Sort again"
FRESH_SORT_TIP = "Back up your order, re-read folders, sort each title. Known words stay."
FRESH_FOLDERS = "Change folders…"
FRESH_FOLDERS_TIP = "Add, remove or skip folders first; nothing changes until Sort again."
FRESH_FOLDERS_BUSY = "Setup is open: finish it or close it first."
FRESH_FOLDERS_REFUSED = "A folder you changed wasn't changed: {why}"
FRESH_OVER_HEAD = "Start over completely"
FRESH_OVER_BODY = ("Your library, settings, known words and everything Surasura worked out go into one dated backup. "
                   "Anki and your own folders and files are never touched. Surasura opens again and setup starts "
                   "from the beginning.")
FRESH_OVER = "Start over…"
FRESH_OVER_TIP = "Back up everything Surasura keeps and start setup again. Asks first."
FRESH_OVER_ASK = "Start over completely?"
FRESH_OVER_ASK_BODY = ("Surasura will close and open again, then setup starts from the beginning. Everything it keeps "
                       "goes into one dated backup, and Put back brings it back.")
FRESH_OVER_YES = "Start over"
FRESH_OVER_YES_TIP = "Close Surasura, set everything aside in one backup and start setup again"
FRESH_OVER_GENERATING = "A Generate is running: start over once it has finished."
FRESH_RESTART_FAILED = "Nothing was changed: Surasura couldn't start itself again ({why})."
FRESH_BACKUPS = "Backups"
FRESH_LOOKING = "Looking for backups…"
FRESH_KINDS = {"sorted-again": "Sorted again", "started-over": "Started over", "put-back-over": "Put back over"}
FRESH_STOPPED = "stopped part way"
FRESH_SIZE_WAIT = "…"
FRESH_SIZE_MB = "{mb:,} MB"
FRESH_SIZE_GB = "{gb:,.1f} GB"
FRESH_PUT_BACK = "Put back…"
FRESH_PUT_BACK_TIP = "Bring this back. What you have now is backed up first."
FRESH_PUT_IT_BACK = "Put it back"
FRESH_PUT_IT_BACK_TIP = "Stopped part way: put your library back as before. Asks first."
FRESH_SHOW = "Show in folder"
FRESH_SHOW_TIP = "Open this backup's folder"
FRESH_SHOW_ALL = "Show all {n:,}"
FRESH_SHOW_ALL_TIP = "List every backup, oldest last"
FRESH_PB_ASK = "Put back your library from {date}?"
FRESH_PB_BODY = ("Comes back: your order, tiers, Finished and New arrivals as they were on {date}, and the folder list "
                 "then. Your library now goes into a backup of its own, so you can switch back.")
FRESH_PB_KNOWN = "Your known words stay as they are now; the ones from then are in the backup."          # P9
FRESH_PB_STOPPED_ASK = "Put your library back as it was?"
FRESH_PB_STOPPED_BODY = ("Sorting your library again was stopped part way on {date}. This puts your library back as "
                         "it was before.")
FRESH_PB_FINISH_BODY = ("Putting your library back was stopped part way on {date}, after the library itself came back. "
                        "This finishes it.")
FRESH_OVER_STOPPED_TIP = "Start over stopped part way. start-over.json lists where each part is."
FRESH_PB_OVER_ASK = "Put back everything from {date}?"
FRESH_PB_OVER_BODY = ("Surasura will close and open again with everything as it was on {date}: library, settings, "
                      "known words. What you have now goes into a backup of its own.")
FRESH_PB_YES = "Put back"
FRESH_PB_YES_TIP = "Put this back; what you have now is backed up first."
FRESH_PB_RUNNING = "Putting your library back…"
FRESH_PB_DONE = "Your library from {date} is back"
FRESH_PB_DONE_PLAIN = "Your library is back"
FRESH_PB_REFUSED = "Nothing was put back. {reason}"
FRESH_PB_FAILED = "Nothing was put back: {reason}"
FRESH_SORTED = "Library sorted again"
FRESH_SORTED_NOTHING = "Library sorted again: nothing to sort"
FRESH_SORTED_STOPPED = "Library sorted again: your folders come in as New arrivals"
FRESH_TOAST_PUT_BACK = "Put back"
FRESH_TOAST_PUT_BACK_TIP = "Put back the library you had before sorting again"
# The sheet's counts (the store's `fresh_counts`), each line only when its count isn't 0
FRESH_GONE = "Only in the backup, never back: {parts}."
FRESH_GONE_ADDED = "{n} file{s} you added with + Add from outside your folders"
FRESH_GONE_YOUTUBE = "{n} YouTube transcript{s}"
FRESH_GONE_OTHER = "{n} other text{s} with no folder to read again (pasted, hato's, from before 3.0)"
FRESH_SUSPENDED_OVER = "{n} card{s} Surasura took out of your learning order stay suspended in Anki."
FRESH_NOT_ALL_BACK = "Not all of your library could be put back: the rest is in {folder}"
FRESH_UNFINISHED = ("Sorting your library again stopped part way: put it back from Settings › Content › Sort again "
                    "or start over ({folder})")
FRESH_DONE = "Your order is in the backup: reading your folders again…"
FRESH_REFUSED = "Nothing was changed. {reason}"
FRESH_FAILED = "Nothing was changed: {reason}"
FRESH_NOT_WRITABLE = "Your library can't be written now: {reason}"

# --- PR: *Where new arrivals go* — the placing rules' lines (settings_rules.py; RULE_FROM, RULE_ADD, its tip above) -- #
RULE_LINE_TIP = "Where {source} arrivals go. Wait here: they wait in New arrivals."
RULE_LINE_NAME = "Where arrivals from {source} go"
RULE_LINE_WORDS = "From {source}"
RULE_CHANNEL = "{producer} · channel {channel}"
RULE_FOLDERS = "your folders"                       # the `source` line: the folders Surasura reads where they are
RULE_FOLDER = "folder {folder}"
RULE_HELD = "“{value}” · waits"
RULE_SEEN_NONE = "No other source seen yet"
RULE_TYPE = "Another source…"
RULE_TYPE_TIP = "Type a program (hato) or program and channel (youtube: )."
RULE_TYPE_PLACEHOLDER = "youtube:<channel id>"
RULE_TYPE_NAME = "A source for a new rule"
RULE_NEW_TIP = "New rule for {source}: pick where its arrivals go. Wait here saves nothing."

# --- round 8 row 45 (P5): a press whose wait is worth naming — its words held in the bar while it runs ------------- #
SWITCH_TURNING_ON = "Turning on Cards made for you…"
SWITCH_TURNING_OFF = "Turning off Cards made for you…"


# --- Journey v3's rows (J-SET; SPEC §1.4, the settings table; every word PROVISIONAL): Settings' Journey rows
# (`settings_catalog._journey_rows`). The page's ⚙ says the same names (templates/journey/).
ROWS.update({
    "journey_pitch": ("Pitch and tones", "", "Each word's pitch accent, or its tones in Chinese",
                      "pitch accent tones chinese show hide f"),
    "journey_meanings": ("Meanings", "Yours: the dictionaries you added to Anki Miner",
                         "Which dictionary the meaning pane shows",
                         "meanings dictionary definition english jmdict cc-cedict yours anki miner gloss"),
    "journey_source": ("Where each line is from", "", "How each sentence shows the episode it came from",
                       "source where from file episode icon name hover badge"),
    "journey_first_meeting": ("Where you'll first meet it", "The sentence you first meet the word in, marked",
                              "Show the line you first meet each word in", "first meeting meet sentence line marked"),
    "journey_word_size": ("Word size", "", "How big the word is on your journey", "word size text font big small"),
    "journey_sentence_size": ("Sentence size", "", "How big the sentences are on your journey",
                              "sentence size text font big small"),
    "journey_theme": ("The page's theme", "", "Your journey's look: Night or Light",
                      "theme look night light dark journey page"),
    "journey_keys": ("Keys", "One key of your own: the page's ⚙ › Keys", "The keys your journey answers to",
                     "keys keyboard shortcuts qwerty dvorak hotkeys"),
    "sentences_per_word": ("Sentences per word",
                           "All: every sentence kept for a word, up to about 85 — Generate and your lists grow with it",
                           "Most example sentences per word, on your journey and in your lists",
                           "max sentences per word examples all contexts up to"),
})
_SIZES = {"s": "Small", "m": "Medium", "l": "Large"}
OPTIONS.update({
    "journey_pitch": {"shown": "Shown", "hidden": "Hidden until F"},
    "journey_meanings": {"en": "English", "yours_en": "Yours, then English", "yours": "Yours only"},
    "journey_source": {"icon": "Icon", "full": "Icon + name", "hover": "Only on hover"},
    "journey_word_size": _SIZES,
    "journey_sentence_size": _SIZES,
    "journey_theme": {"Dark Flow": "Night", "Modern Light": "Light"},
    "journey_keys": {"qwerty": "QWERTY", "dvorak": "Dvorak"},
    "sentences_per_word": {**{n: str(n) for n in range(1, 11)}, 0: "All"},
})

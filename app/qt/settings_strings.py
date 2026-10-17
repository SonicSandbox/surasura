"""Every user string of the Settings page (W3.3; the window's spec 05 §5.7, §5.12: one table, so the app can be
translated later) — Settings' own table beside `strings.py`, as a module keeps its `qt_strings.py`. No Qt.

Settings keeps its words (C-scope Q6): the old mock's labels and one-line help (`mock-g16` `sectionBody`); where the
mock's words carry a meaning 2.4 changed (A5: the one-kanji words, Junban's unlisted cards), 2.4's meaning in the mock's
voice. A tooltip is 2.4's own where 2.4 had one, else the help line. Help is one line, never an essay; no fixed seed
numbers (N5). `app/qt/settings_catalog.py` names each row's strings by its row id.
"""

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
FOLDER_PICK_TITLE = "Where videos are looked for"

# --- the controls' own words (settings_controls.py; moved here from its top, W3.3 P3) ------------------------------ #
ADD = "Add"                                      # an empty bed's words when the page names none
REMOVE_NAME = "Remove {item}"                    # a list tablet's ✕, for screen readers (the accessible description)
CROSS = "✕"
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
    "houseki": "Houseki tools",
}

# --- the doors (a window, or an action, a row opens) ---------------------------------------------------------------- #
DOORS = {
    "anki": ("Anki…", "Choose your decks and the field each card's word is in"),
    "migaku": ("Migaku", "Import from Migaku"),
    "jiten": ("Jiten", "Import from Jiten"),
    "apkg_known": (".apkg", "Import an Anki deck file"),
    "word-lists": ("Ignore list · Blacklist", "Opens your Ignore list and Blacklist"),
    "junban": ("Preview order",
               "Shows the new order and why, before anything moves; Restore previous order is there too"),
    "put-back": ("Put Anki back…", "Puts Anki's new cards back the way they were before Surasura first changed them"),
    "backfill": ("Preview", "Shows exactly what goes into each card; Fill and Restore are there too"),
    "extract": ("Extract…", "EPUBs and Anki decks, split into parts"),
    "youtube-downloader": ("YouTube…", "Download a video's captions straight into your library"),
    "youtube-preview": ("Preview a video…", "Score a video against your words before you add it"),
    "koe": ("Speech settings…", "Set the API key, voice and delivery for spoken sentences"),
    "sentence-dictionary": ("Export", "Exports Surasura Corpus for Yomitan"),
    "frequency-lists": ("Add…", "Add or remove a frequency list"),
}
# A row whose door says something else than the opener's own words: row id -> {opener: (label, tooltip)}
ROW_DOORS = {
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
    "anki_sync_include_suspended": ("Count suspended cards as known", "",
                                    "Count cards you've suspended as known. Off by default — suspended cards are often "
                                    "ones you struggled with", "suspended known"),

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
    "connect_mine_words": ("Words to make cards from", "", "Which words of an episode become cards",
                           "words to make cards from mine mode which words all unknown i+1 list"),
    "mine_line": ("Mine automatically", "The files at the top of Current mine themselves the moment they’re placed",
                  "How many files at the top of Current mine themselves", "auto top mines itself mine line"),
    "connect_send_grammar": ("Send grammar words", "Particles and endings get cards too",
                             "Grammar words (particles, endings) get cards too. Names follow Ignore names in Language "
                             "& Parsing", "grammar particles endings send"),
    "connect_open_anki": ("When Anki is closed", "New cards wait until you open Anki — or Surasura opens it for you",
                          "When you open Surasura and Anki is closed, Surasura can open it, so your phone's reviews "
                          "come in and your cards get made and ordered", "closed open anki start session"),
    "connect_backlog_cap": ("Keep up to", "Surasura cards waiting in Anki, for this language. 0: no limit",
                            "Connect makes cards while fewer of its own new cards wait in Anki, for this language. 0: "
                            "no limit. Your own cards never count", "cap backlog waiting keep up to limit"),
    "known_from_anki": ("Count as known in Anki", "A card in every state you pick marks its word known",
                        "A card in every state you pick here marks its word known (all must hold: Suspended + Marked "
                        "is both). None picked: off", "known from anki suspended marked flag"),
    "connect_video_folders": ("Where videos are looked for", "Surasura pairs a subtitle with its video by name",
                              "The folders (and their subfolders) where Connect looks for a moved video, for this "
                              "language", "video folders pair moved"),
    "junban_own_tag": ("Your own cards first",
                       "Cards you made yourself go before Surasura’s, in the order you made them — never suspended",
                       "Cards you mine yourself go ahead of the ones Surasura Connect makes, in the order you mined "
                       "them, and are never suspended. Type a tag (immersion) and every card carrying it is yours too",
                       "own cards first tag manual yomitan"),
    "junban_order_all": ("Order all cards by the list", "Your own cards in your list’s order too, never suspended",
                         "Put your own cards in your list's order too, among Connect's, instead of ahead of them. They "
                         "are still never suspended", "order all cards list own"),
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
    "junban_first": ("First", "What leads the order",
                     "Phrases: phrase cards you meet as often as your list's words are placed as if on it. i+1 first: "
                     "a card's new word in its sentence gets its card first", "first phrases i+1 ready"),
    "junban_later": ("Cards not on your list", "Placed after your list, and marked. Restore takes it back",
                     "Tag them Surasura::later, flag them purple, or suspend them (tagged too). Restore puts each back",
                     "not on list later suspend flag tag"),
    "junban_auto_reorder": ("Reorder by itself after Generate", "",
                            "After a Generate, and when you come back to Surasura, the deck saved in Junban is "
                            "reordered on its own", "auto reorder automatic generate"),
    "junban_auto_actions": ("…and tag, flag or suspend then", "The automatic reorder applies Junban's marks too",
                            "Off, the automatic reorder moves cards only; on, it applies everything Junban has saved",
                            "auto actions tag flag suspend"),
    "junban_door": ("", "", "Preview order · Restore previous order", "preview restore order"),
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
    "junban_only_markers": ("Only words marked", "None picked: every word",
                            "Reorder only the words carrying one of these marks; the rest keep their order, at the "
                            "back", "only markers star lopsided reading filter"),
    "junban_tag": ("Tag the notes I move", "Empty: no tag",
                   "Adds this tag to every note whose card moved. Restore takes it back off", "tag notes moved"),
    "junban_chunk_size": ("Cards per write", "", "How many cards go to Anki in one request", "chunk cards per write"),

    # Backfill
    "junban_backfill_fills": ("Fill", "パターン: how the word is used · 例文: two more sentences from your own content",
                              "Which fields Backfill fills", "patterns sentences fill パターン 例文"),
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
    "placing_rules": ("Where new arrivals go", "Empty: every arrival waits here, in New arrivals",
                      "A source, and where its arrivals go", "where new arrivals go rules source hato youtube channel "
                      "wait top"),

    # Connections
    "anki_miner": ("Anki Miner", "Makes your cards from your own videos. Free, made by Zero",
                   "Anki Miner's state, and what it still needs", "anki miner install setup"),
    "hato": ("hato", "Finds subtitles for your shows, and sends new episodes to New arrivals",
             "Whether hato is installed", "hato install houseki suite subtitles"),
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
    "text_size": ("Text size", "Applied the next time Surasura starts", "The window's text size",
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
    "version": ("Version {version}", "", "Opens the data folder", "version data folder"),
    "set_up_again": ("Set up again", "Walks through the first steps again", "Opens the setup again",
                     "set up again wizard setup"),
    "covers_download": ("Download covers", "Pictures for your shows and books", "Download covers",
                        "covers download pictures"),
}

# --- the choices: row id -> {value: label}; choice cards also have a line under each -------------------------------- #
OPTIONS = {
    "known_road": {"anki": "Anki", "import": "Import a list"},
    "connect_mine_words": {"list": "Your list", "unknown": "Every unknown word", "i1": "Only i+1"},
    "connect_open_anki": {False: "Wait for me", True: "Open Anki for me"},
    "known_from_anki": {"suspended": "Suspended", "marked": "Marked", "flag:1": "Flag 1 (Red)",
                        "flag:2": "Flag 2 (Orange)", "flag:3": "Flag 3 (Green)", "flag:4": "Flag 4 (Blue)",
                        "flag:5": "Flag 5 (Pink)", "flag:6": "Flag 6 (Turquoise)", "flag:7": "Flag 7 (Purple)"},
    "junban_scope": {"deck": "This deck", "all": "All decks"},
    "junban_order": {"content": "As I’ll meet it", "priority": "By leverage"},
    "junban_unlisted": {"list_first": "After it", "journey": "Mixed in", "back": "At the back"},
    "junban_first": {"junban_phrases": "Phrases", "junban_ready_first": "i+1 first"},
    "junban_later": {"junban_later_tag": "Tag", "junban_later_flag": "Flag purple", "junban_later_suspend": "Suspend"},
    "junban_only_markers": {"star": "✦", "lopsided": "⚖", "reading": "📖"},
    "junban_backfill_fills": {"patterns": "パターン", "sentence": "例文"},
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
    "connect_mine_words": {"list": "Words on your list that you don't know and have no card yet.",
                           "unknown": "Every word of the episode you don't know yet.",
                           "i1": "Only words with a line whose other words you know."},
}
# A tablet's tooltip, where its glyph alone doesn't say it
OPTION_TIPS = {
    "junban_only_markers": {"star": "High leverage: the words the report stars",
                            "lopsided": "Lopsided: words that come almost entirely from one part of your library",
                            "reading": "Reading: words you'll read but essentially never hear"},
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
# Export: the format pop, the outcome in the bar
EXPORT = "Export"
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
COPY_PATH = "Copy path"
COPY_PATH_TIP = "Copy the whitelist file's path, to paste into Anki Miner's file chooser."
PATH_COPIED = "The whitelist file's path is copied: paste it into Anki Miner's file chooser."
INSTALL_MINER = "Install Anki Miner…"
INSTALL_MINER_TIP = "Get Anki Miner, free: its installer, from its GitHub release.\n• Asks before it downloads"
BROWSE_MINER = "Browse…"
BROWSE_MINER_TIP = "Anki Miner is installed somewhere else: show Surasura where."
BROWSE_MINER_TITLE = "Where is Anki Miner?"
BROWSE_MINER_FILTER = "Anki Miner (AnkiMiner.exe);;Programs (*.exe);;All files (*)"
OPEN_MINER = "Open Anki Miner"
OPEN_MINER_TIP = "Start Anki Miner, to finish its setup."
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

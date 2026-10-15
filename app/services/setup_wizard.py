"""The setup wizard's services (W3.5 part 3; the signed draft `wizard-draft/WIZARD-DRAFT.md`, WZ-1…WZ-7), Qt-free: what
each of the six pages starts with, what it writes on *Next*, and the reads and jobs behind it. The Qt pages
(`app/qt/wizard.py`) only paint the answers.

- **The pages** (`PAGES`): your language · what you know · your shows (and covers) · card order (and the "may Surasura
  keep them in order" consent, HY-9) · cards made for you · your list (the level, then Generate).
- **What a page writes** (`writes`, pure): exactly its keys, on *Next*, one `set` call (`save`) — nothing earlier;
  *Skip* calls nothing, so it writes nothing. `finish` writes `onboarding_completed` (Generate, or *Skip* on the last
  page; never *Finish later*). Never `logic.automation` (D29's one switch also covers the automatic sync and Generate;
  its default is on).
- **Where a page starts** (`preselect`): a profile that never finished setup gets the draft's preselects (the
  recommended choices); *Set up again* (`onboarding_completed` True) gets what the settings say now.
- **The reads** (`anki_look`, `library_rows`, `level_numbers`) are a worker's: Anki through the Anki window's own reads
  (`app/anki_window.py`), the library through a read-only handle of the store, the level through the Rarity slider's
  recipe (`token_index.preview_frequencies`, `word_selection.band_previews`, D13's `auto_band`).
- **The jobs** (`first_sync`, `open_content_manager`) go through the registry: the first known-words sync is the Anki
  window's `anki-sync` job (the user's own first sync — `anki_sync.may_sync`'s "never-synced" gate — the wizard's *Next*
  is that act; append-only; refused while an update holds Surasura's children); the Content Manager is the 2.x window
  as a child (`tools.run`), until W3.2's *+ Add*.

Nothing here waits on the caller's thread except the calls named as a worker's.
"""
import os

PAGES = ("language", "known", "shows", "order", "cards", "level")
LATER = ("leave", "mark", "aside")
LANGUAGES = ("ja", "zh")
KNOWN_HOW = ("anki", "import", "fresh")

# WZ-3: the three-way choice for cards of words not on your list -> (junban_later_tag, _flag, _suspend).
LATER_FLAGS = {"leave": (False, False, False), "mark": (True, True, False), "aside": (True, False, True)}
CONTENT_MANAGER_KIND = "child"          # the Tk dashboard's kind for its children: the automatic Generate waits for it
CONTENT_MANAGER_LABEL = "Content Manager"
LISTED_TIERS = ("now", "soon", "goal", "arrivals")    # page 3's rows: what is in the library (never the graduated)


# --- opening ---------------------------------------------------------------------------------------------------- #
def should_open(settings):
    """The wizard opens while setup was never finished (`onboarding_completed` not True)."""
    return (settings or {}).get("onboarding_completed") is not True


def _language(language):
    language = str(language or "").strip().lower()
    if language not in LANGUAGES:
        raise ValueError(f"not a language: {language!r}")
    return language


def _later_of(settings):
    """The three-way choice the three later-actions read as: suspend → *Set them aside*, a tag or a flag → *Mark them*
    (a mix such as a flag alone is shown as its nearest), none → *Leave them*."""
    if settings.get("junban_later_suspend") is True:
        return "aside"
    if settings.get("junban_later_tag") is True or settings.get("junban_later_flag") is True:
        return "mark"
    return "leave"


def preselect(settings, language):
    """Every page's starting answers -> {page: answers} (the answers' shapes are `writes`'). A profile that never
    finished setup: the draft's preselects (From Anki, covers on, kept in order, *Leave them*, cards made, Automatic);
    *Set up again*: what the settings say now. The language, the saved decks and 順's deck are always the settings'."""
    from app import anki_window
    settings = settings or {}
    language = language if language in LANGUAGES else "ja"
    decks = anki_window.saved(settings, language)[0]
    deck = str(settings.get("junban_deck") or "").strip() or None
    band = ((settings.get("logic") or {}).get("selection") or {}).get("band")
    if should_open(settings):
        return {"language": {"language": language},
                "known": {"how": "anki", "decks": decks},
                "shows": {"covers": True},
                "order": {"keep_in_order": True, "deck": deck, "later": "leave", "open_anki": False},
                "cards": {"make_cards": True},
                "level": {"automatic": True, "band": band}}
    from app import replan_preview
    kept = settings.get("junban_auto_actions") is True and replan_preview.recorded_deck(settings, language) is not None
    auto = ((settings.get("logic") or {}).get("selection") or {}).get("auto") is True
    return {"language": {"language": language},
            "known": {"how": "anki" if decks else "fresh", "decks": decks},
            "shows": {"covers": settings.get("covers_download") is True},
            "order": {"keep_in_order": kept, "deck": deck, "later": _later_of(settings),
                      "open_anki": settings.get("connect_open_anki") is True},
            "cards": {"make_cards": settings.get("connect_enabled") is True},
            "level": {"automatic": auto, "band": band}}


# --- writing ---------------------------------------------------------------------------------------------------- #
def writes(page, answers, settings, language):
    """Pure: exactly the keys `page` writes on *Next* for `answers` -> {key: value} (top-level names, dotted `logic.…`
    paths), `settings` the settings now (for the merges), `language` the wizard's language. {} when the page has
    nothing to write (Start fresh, Import a list — the importer writes its own —, From Anki with no deck, the cards
    switch absent: `make_cards` None)."""
    from app import replan_preview
    answers = answers or {}
    settings = settings or {}
    if page == "language":
        return {"target_language": _language(answers.get("language"))}
    language = _language(language)
    if page == "known":
        how = answers.get("how")
        if how not in KNOWN_HOW:
            raise ValueError(f"not a way to know words: {how!r}")
        decks = [str(d) for d in (answers.get("decks") or []) if str(d).strip()]
        if how != "anki" or not decks:
            return {}
        per_language = {k: list(v) for k, v in dict(settings.get("anki_sync_decks") or {}).items()}
        per_language[language] = decks          # this language's entry; another language's kept (`anki_window.merge`)
        return {"anki_sync_decks": per_language}
    if page == "shows":
        return {"covers_download": bool(answers.get("covers"))}
    if page == "order":
        later = answers.get("later", "leave")
        if later not in LATER:
            raise ValueError(f"not a choice for cards not on your list: {later!r}")
        tag, flag, suspend = LATER_FLAGS[later]
        deck = str(answers.get("deck") or "").strip()
        kept = bool(answers.get("keep_in_order")) and bool(deck)
        out = {"junban_auto_actions": bool(answers.get("keep_in_order")),
               replan_preview.DECK: deck if kept else "",
               replan_preview.LANGUAGE: language if kept else "",
               "junban_later_tag": tag, "junban_later_flag": flag, "junban_later_suspend": suspend,
               "connect_open_anki": bool(answers.get("open_anki"))}
        if deck:
            out["junban_deck"] = deck
        return out
    if page == "cards":
        if answers.get("make_cards") is None:
            return {}
        return {"connect_enabled": bool(answers.get("make_cards"))}
    if page == "level":
        if answers.get("automatic"):
            return {"logic.selection.auto": True}
        out = {"logic.selection.auto": False}
        if answers.get("band"):
            out["logic.selection.band"] = str(answers["band"])
        return out
    raise ValueError(f"not a page: {page!r}")


def save(settings_service, page, answers, language):
    """*Next* on `page`: its keys (`writes`, merged onto the settings now) in one `set` call -> the dict written.
    Safe on a window's thread (`set` queues)."""
    from app.services.settings import thaw
    changes = writes(page, answers, thaw(settings_service.get()), language)
    if changes:
        settings_service.set(changes)
    return changes


def finish(settings_service):
    """Setup done (Generate pressed, or *Skip* on the last page): `onboarding_completed` -> the dict written."""
    changes = {"onboarding_completed": True}
    settings_service.set(changes)
    return changes


# --- the reads (a worker's) ----------------------------------------------------------------------------------- #
def anki_look(settings, language):
    """(A worker.) Is Anki open, and which decks has it -> {"open", "say" (None, or what Anki said that the user can
    act on, as written: a permission prompt, an add-on to update), "decks" [(name, studied cards)], "preselected"
    [names]} — the saved decks, else the Anki window's first-open pick (every deck with studied cards, largest first).
    Never raises."""
    from app import anki_connect, anki_sync, anki_window
    settings = settings or {}
    saved, _fields, suspended = anki_window.saved(settings, language)
    url = anki_connect.address(settings)
    probe = anki_window.read_probe(url, saved, suspended)
    state, said = anki_window.connection(probe.report)
    if state != "connected":
        return {"open": False, "say": said if state == "problem" else None, "decks": [], "preselected": []}
    counts = dict(probe.counts)
    missing = [name for name in probe.decks if name not in counts]
    try:
        counts.update(anki_sync.deck_study_counts(url, missing, suspended) if missing else {})
    except anki_connect.AnkiError as e:
        print(f"Setup: Anki's deck counts couldn't be read ({e})")
    decks = [(name, int(counts.get(name) or 0)) for name in probe.decks]
    picked = probe.preselected if probe.preselected is not None else list(saved)
    return {"open": True, "say": None, "decks": decks, "preselected": list(picked)}


def library_rows(settings, language):
    """(A worker.) What is in the library now, one row per title (a show, a book) -> [{"name", "count" (its files),
    "folder" (where its first file is)}] in the library's order (NOW, Soon, 6+ Months, New arrivals); [] for an empty
    library or no store. A read-only look: the store is never built or migrated here."""
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    data_dir = get_data_path(language)
    try:
        store = library_store.open_store(language, data_dir, get_user_files_path(language), role="reader")
    except Exception as e:
        print(f"Setup: the library couldn't be read ({e})")
        return []
    if store is None:
        return []
    try:
        roots = {rid: path for rid, path in store.conn.execute("SELECT id, path FROM roots")}
        rank = " ".join(f"WHEN '{t}' THEN {n}" for n, t in enumerate(LISTED_TIERS))
        rows = store.conn.execute(
            "SELECT i.work_id, w.title, i.rel_path, i.root_id FROM items i LEFT JOIN works w ON w.id = i.work_id "
            f"WHERE i.tier IN ({', '.join('?' * len(LISTED_TIERS))}) ORDER BY CASE i.tier {rank} END, i.ord, i.id",
            LISTED_TIERS).fetchall()
    except Exception as e:
        print(f"Setup: the library couldn't be read ({e})")
        return []
    finally:
        store.close()
    titles = {}
    for work_id, title, rel, root_id in rows:
        folder_rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
        key = ("work", work_id) if work_id is not None else ("folder", root_id, folder_rel)
        row = titles.get(key)
        if row is None:
            base = roots.get(root_id) or data_dir
            name = title or (folder_rel.rsplit("/", 1)[-1] if "/" in folder_rel else "") or rel.rsplit("/", 1)[-1]
            titles[key] = row = {"name": name, "count": 0,
                                 "folder": os.path.normpath(os.path.join(base, *folder_rel.split("/")))}
        row["count"] += 1
    return list(titles.values())


def level_numbers(settings, language):
    """(A worker.) The last page's numbers, from the Rarity slider's own recipe -> {"bands" [band keys, slider order],
    "chosen", "automatic", "auto_band" (the band Automatic picks: D13's rule, `word_selection.auto_band`), "words",
    "coverage" (0–100), "every_hours" (None when it can't be said) for the chosen band, and "numbers" {band: {"words",
    "coverage", "every_hours"}} for every band}; None while nothing is counted yet (an empty library, the shows still
    being read). `automatic` and the band are the page's preselects (`preselect`)."""
    from app import analyzer, library_store, token_index, word_selection
    from app.path_utils import get_data_path, get_user_files_path
    from app.zh_script import effective
    settings = settings or {}
    logic = settings.get("logic") or {}
    sel = logic.get("selection") or {}
    user_files = get_user_files_path(language)
    try:
        if not os.path.exists(token_index.store_path_for(language)):
            return None                                       # nothing indexed: never a store made just to look
        token_index.prepare_preview(language, user_files)
        for key in ("names_recurring", "names_kanji", "names_work_terms"):     # as the level chip sets them
            analyzer.LOGIC[key] = bool(logic.get(key, True))
        script = effective(language, settings.get("zh_script", "asis"))
        store = token_index.open_store(language)
        try:
            freqs = token_index.preview_frequencies(store, language, user_files, script)
            if freqs is None:
                return None
            previews = word_selection.band_previews(
                freqs, sel.get("bands_ppm"), sel.get("min_count", word_selection.DEFAULT_MIN_COUNT),
                freqs["total_tokens"] / (store.file_count() or 1),
                sel.get("minutes_per_file", word_selection.MINUTES_PER_FILE))
        finally:
            store.close()
        try:
            remembered = library_store.read_auto_band(language, get_data_path(language))
        except Exception:
            remembered = None
        try:
            auto = word_selection.auto_band(previews, sel.get("auto_max_words", word_selection.DEFAULT_AUTO_MAX_WORDS),
                                            remembered=remembered)
        except (TypeError, ValueError):                       # a hand-edited line: your own band (`automation.level`)
            auto = None
    except Exception as e:
        print(f"Setup: the level couldn't be counted ({e})")
        return None
    if not previews:
        return None
    level = preselect(settings, language)["level"]
    saved = sel.get("band") if sel.get("band") in previews else word_selection.BANDS_ORDER[0]
    auto = auto or saved
    chosen = auto if level["automatic"] else saved
    numbers = {band: {"words": int(p["word_count"]), "coverage": float(p["coverage_percent"]),
                      "every_hours": p["hours_between"]} for band, p in previews.items()}
    return dict({"bands": [b for b in word_selection.BANDS_ORDER if b in previews], "chosen": chosen,
                 "automatic": bool(level["automatic"]), "auto_band": auto, "numbers": numbers}, **numbers[chosen])


# --- the jobs ----------------------------------------------------------------------------------------------------- #
def first_sync(registry, settings, language, decks, on_end, automation=None):
    """*Next* on From Anki: the user's first known-words sync of `decks`, as the Anki window's *Sync now* runs it — an
    `anki-sync` job (append-only; the automatic sync never starts beside it), its result told to the automation service
    and then `on_end(result)` on the job's thread. -> the Job, or None: no deck, or an update holds Surasura's children
    (nothing submitted)."""
    from app import anki_connect, anki_window
    from app.services.automation import SYNC_LABEL
    decks = [str(d) for d in (decks or []) if str(d).strip()]
    if not decks:
        return None
    settings = settings or {}
    _saved, chosen, suspended = anki_window.saved(settings, language)
    url = anki_connect.address(settings)
    return anki_window.submit(registry, SYNC_LABEL,
                              lambda: anki_window.run_sync(language, url, decks, chosen, suspended),
                              on_end, automation, language)


def open_content_manager(registry, language, on_end=None):
    """*Add content…*: the 2.x Content Manager window for `language`, a child job (`tools.run`; its kind the Tk
    dashboard's children's, which the automatic Generate waits for; one at a time). It goes on if the window quits (the
    user may be in the middle of adding). `on_end(returncode)` when it closes. -> the Job."""
    from app.services import tools
    return tools.run(registry, CONTENT_MANAGER_KIND, CONTENT_MANAGER_LABEL,
                     ["content_importer_gui.py", "--language", _language(language)], on_end=on_end, on_quit="detach")


def generate(services):
    """(A worker: it writes the settings first.) *Generate* on the last page: the window's own Generate
    (`services.generate()`) -> True when it was accepted."""
    try:
        return services.generate() is not None
    except Exception as e:
        print(f"Setup: Generate couldn't be asked for ({e})")
        return False

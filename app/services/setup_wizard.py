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
- **Upgrading from 2.x** (`upgrading`; Sonic's WZ-8 / P4.1-3 answer, 2026-10-15): set up in 2.x (`onboarding_completed`
  True) but never shown 3.0's pages (`setup_seen` empty), the whole wizard opens once. Each page shows what the 2.x
  settings hold; a choice 2.x never had (covers, keeping cards in order, cards made for you) starts at the recommended
  one, as for a new user. Any close records the pages seen (`seen`), *Skip* and *Finish later* writing nothing else.
  `setup_seen` holds the version whose pages were seen (`SETUP_VERSION`), so a later version can show its new ones.
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
SEEN = "setup_seen"             # the version whose setup pages the learner has seen ("" never: a 2.x profile)
SETUP_VERSION = "3.0"           # this version's pages (3.1 may show only the pages added since: the follow-up list)


# --- opening ---------------------------------------------------------------------------------------------------- #
def should_open(settings):
    """The wizard opens while setup was never finished (`onboarding_completed` not True), and once for a profile set
    up in 2.x that never saw these pages (`upgrading`)."""
    return (settings or {}).get("onboarding_completed") is not True or upgrading(settings)


def _new(settings):
    """A profile that never finished setup: every page's preselect is the recommended one, and *Next* writes it all."""
    return (settings or {}).get("onboarding_completed") is not True


def upgrading(settings):
    """Set up in 2.x (`onboarding_completed` True: 2.x's first run, brought over by the import) and never shown this
    version's pages (`setup_seen` empty)."""
    settings = settings or {}
    return settings.get("onboarding_completed") is True and not str(settings.get(SEEN) or "").strip()


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


def _pair(settings):
    """The recorded pair's language ("" when no deck is recorded): 順's switch was turned on for that language."""
    from app import replan_preview
    if not str(settings.get(replan_preview.DECK) or "").strip():
        return ""
    return str(settings.get(replan_preview.LANGUAGE) or "").strip().lower() or "?"


def preselect(settings, language):
    """Every page's starting answers -> {page: answers} (the answers' shapes are `writes`'). A profile that never
    finished setup: the draft's preselects (From Anki, covers on, kept in order, *Leave them*, cards made, Automatic);
    *Set up again*: what the settings say now; a profile brought over from 2.x (`upgrading`): what its settings say,
    and the recommended choice where 2.x never asked (covers on, kept in order, cards made) — without saved decks,
    *What you know* keeps what came over (`fresh`: nothing more brought in). The language, the saved decks and 順's deck
    are always the settings' — never 順's deck while it is the one recorded for the other language (one `junban_deck`
    for both: AD-1)."""
    settings = settings or {}
    language = language if language in LANGUAGES else "ja"
    decks, deck, band = _reads(settings, language)
    if _new(settings):
        return {"language": {"language": language},
                "known": {"how": "anki", "decks": decks},
                "shows": {"covers": True},
                "order": {"keep_in_order": True, "deck": deck, "later": "leave", "open_anki": False},
                "cards": {"make_cards": True},
                "level": {"automatic": True, "band": band}}
    out = _current(settings, language, decks, deck, band)
    if upgrading(settings):         # brought over from 2.x: what 2.x never asked starts at the recommended choice
        out["shows"]["covers"] = True
        out["order"]["keep_in_order"] = True
        out["cards"]["make_cards"] = True
    return out


def _reads(settings, language):
    """(this language's saved decks, 順's deck — None while it is the other language's recorded one —, the band)."""
    from app import anki_window, replan_preview
    decks = anki_window.saved(settings, language)[0]
    deck = str(settings.get("junban_deck") or "").strip() or None
    if _pair(settings) not in ("", language) and deck == str(settings.get(replan_preview.DECK) or "").strip():
        deck = None
    return decks, deck, ((settings.get("logic") or {}).get("selection") or {}).get("band")


def _current(settings, language, decks, deck, band):
    """What the settings say now, as every page's answers (*Set up again*; what *Card order*'s *Next* compares with)."""
    # The consent reads back on while it is given for this language — though 順's deck moved since (AD-2: the host
    # stands aside until the pair is recorded again; a *Next* never revokes the yes).
    kept = settings.get("junban_auto_actions") is True and _pair(settings) == language
    auto =((settings.get("logic") or {}).get("selection") or {}).get("auto") is True
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
        out = {"anki_sync_decks": per_language}
        # The page's "stays in sync" (IK): the automatic known-words sync is gated on `anki_sync_auto`, off by default —
        # turned on by a new profile's From Anki, or by a way or decks the learner changed; an untouched page on *Set up
        # again* or an upgrade keeps the setting as it is (R2-2: 2.x's own *Keep in sync*).
        was = None if _new(settings) else _current(settings, language, *_reads(settings, language))["known"]
        if was is None or was["how"] != "anki" or list(was["decks"]) != decks:
            out["anki_sync_auto"] = True
        return out
    if page == "shows":
        return {"covers_download": bool(answers.get("covers"))}
    if page == "order":
        later = answers.get("later", "leave")
        if later not in LATER:
            raise ValueError(f"not a choice for cards not on your list: {later!r}")
        tag, flag, suspend = LATER_FLAGS[later]
        deck = str(answers.get("deck") or "").strip()
        keep = bool(answers.get("keep_in_order"))
        kept = keep and bool(deck)
        open_anki = bool(answers.get("open_anki"))
        # *Set up again* writes only what the user changed on the page (AD-1…3): a choice shown as it was — a mix of
        # later actions shown as its nearest, a consent given for the other language — is never written over.
        was = None if _new(settings) else _was_order(settings, language)
        out = {}
        if was is None or keep != was["keep_in_order"] or deck != (was["deck"] or ""):
            if kept:
                out.update({"junban_auto_actions": True, replan_preview.DECK: deck, replan_preview.LANGUAGE: language,
                            "junban_deck": deck})
            elif _pair(settings) in ("", language):   # never the other language's consent, pair or 順's deck
                out.update({"junban_auto_actions": keep, replan_preview.DECK: "", replan_preview.LANGUAGE: ""})
                if deck:
                    out["junban_deck"] = deck
        if was is None or later != was["later"]:
            out.update({"junban_later_tag": tag, "junban_later_flag": flag, "junban_later_suspend": suspend})
        if was is None or open_anki != was["open_anki"]:
            out["connect_open_anki"] = open_anki
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


def _was_order(settings, language):
    """*Card order* as the settings say now (never the upgrade's recommended consent: it is written once chosen)."""
    return _current(settings, language, *_reads(settings, language))["order"]


def _decks_update(language, decks):
    """The settings service's `update` for the known page: `language`'s decks written onto the file's own
    `anki_sync_decks` as it is when written — another language's entry, and another program's save meanwhile, kept
    (`anki_window.merge`'s rule, for the decks alone: the wizard never writes `anki_sync_fields`)."""
    decks = [str(d) for d in decks]

    def update(settings):
        per_language = dict(settings.get("anki_sync_decks") or {})
        per_language[language] = list(decks)
        settings["anki_sync_decks"] = per_language
    return update


def save(settings_service, page, answers, language):
    """*Next* on `page`: its keys (`writes`, merged onto the settings now) in one `set` call -> the dict written.
    The known page's decks go as an `update=` (AD-4): merged onto the file as it is when written, never the window's
    copy. Safe on a window's thread (`set` queues)."""
    from app.services.settings import thaw
    changes = writes(page, answers, thaw(settings_service.get()), language)
    if page == "known" and changes:
        language = _language(language)
        settings_service.set({k: v for k, v in changes.items() if k != "anki_sync_decks"},
                             update=_decks_update(language, changes["anki_sync_decks"][language]))
    elif changes:
        settings_service.set(changes)
    return changes


def finish(settings_service):
    """Setup done (Generate pressed, or *Skip* on the last page): `onboarding_completed`, and this version's pages seen
    -> the dict written."""
    changes = {"onboarding_completed": True, SEEN: SETUP_VERSION}
    settings_service.set(changes)
    return changes


def seen(settings_service):
    """A 2.x profile's wizard closed (*Finish later*, or the window's quit): this version's pages seen, so it opens
    once — nothing else written (`onboarding_completed` is already True) -> the dict written."""
    changes = {SEEN: SETUP_VERSION}
    settings_service.set(changes)
    return changes


# --- the reads (a worker's) ----------------------------------------------------------------------------------- #
SAMPLE = 20                     # notes read per preselected deck to tell its language (Backfill's kana rule)


def _studied(url, names, suspended):
    """{deck: [its studied note ids]} in ONE request — `anki_sync.deck_study_counts`' query, the ids kept so the
    language can be read from them (a failed slot is no notes). Raises AnkiError."""
    from app import anki_connect, anki_sync
    replies = anki_connect.multi([{"action": "findNotes", "params": {"query": anki_sync.scope_query([d], suspended)}}
                                  for d in names], url)
    out = {}
    for deck, reply in zip(names, list(replies) + [None] * (len(names) - len(replies))):
        result = reply.get("result") if isinstance(reply, dict) and reply.get("error") is None else None
        out[deck] = result if isinstance(result, list) else []
    return out


def _reads_as(notes):
    """A deck's language from its notes: "ja" when more than half hold kana in a field (Backfill's rule,
    `modules/junban/backfill.note_language`: every real Japanese note type does), "zh" when more than half hold Han
    and it isn't Japanese, else None (another language, or nothing to read)."""
    import re
    from app.unicode_ranges import HAN, KANA_LETTERS
    kana_re, han_re = re.compile(f"[{KANA_LETTERS}]"), re.compile(f"[{HAN}]")
    texts = [" ".join(str(f.get("value") if isinstance(f, dict) else f or "") for f in (n.get("fields") or {}).values())
             for n in notes if isinstance(n, dict)]
    if not texts:
        return None
    if sum(1 for t in texts if kana_re.search(t)) * 2 > len(texts):
        return "ja"
    return "zh" if sum(1 for t in texts if han_re.search(t)) * 2 > len(texts) else None


def anki_look(settings, language):
    """(A worker.) Is Anki open, and which decks has it -> {"open", "say" (None, or what Anki said that the user can
    act on, as written: a permission prompt, an add-on to update), "decks" [(name, studied cards)], "preselected"
    [names]} — the saved decks, else the Anki window's first-open pick (every deck with studied cards, largest first:
    `anki_window.preselect`) of the decks that read as this language (the draft; AD-5: a Japanese deck is never
    preselected for Chinese). One read: every deck counted once, a few notes of the picked ones (AD-10). Never raises."""
    from app import anki_connect, anki_window
    settings = settings or {}
    saved, _fields, suspended = anki_window.saved(settings, language)
    url = anki_connect.address(settings)
    report = anki_connect.probe(url)
    if report.get("ok"):
        try:
            names = anki_connect.deck_names(url)
            studied = _studied(url, names, suspended)
            picked = list(saved)
            if not picked:
                picked = anki_window.preselect({deck: len(ids) for deck, ids in studied.items()})
                sample = {deck: list(studied[deck][:SAMPLE]) for deck in picked}
                wanted = sorted({i for ids in sample.values() for i in ids})
                by_id = {n.get("noteId"): n for n in anki_connect.notes_info(url, wanted) if isinstance(n, dict)}
                picked = [deck for deck in picked
                          if _reads_as([by_id.get(i) for i in sample[deck]]) == language]
            decks = [(name, len(studied.get(name) or ())) for name in names]
            return {"open": True, "say": None, "decks": decks, "preselected": picked}
        except anki_connect.AnkiError as e:
            report = {"ok": False, "error": f"Anki stopped answering: {e}"}       # `read_probe`'s report
    state, said = anki_window.connection(report)
    return {"open": False, "say": said if state == "problem" else None, "decks": [], "preselected": []}


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
    return anki_window.submit(registry, SYNC_LABEL, lambda: _first_sync(language, url, decks, chosen, suspended),
                              on_end, automation, language)


def _first_sync(language, url, decks, chosen, suspended):
    """(The job's thread.) The sync, after a dated copy of the user's KnownWord.json (CLAUDE.md §4,
    `path_utils.backup_to_trash`; AD-5): `anki_sync.sync` only appends and keeps none, and this first one runs on a
    *Next* over decks the wizard preselected. Taken under the known-words lock the sync then holds itself (a
    thread holding it is never refused), so the copy is the file the sync writes onto. No copy, no sync."""
    from app import anki_sync, anki_window, path_utils
    held, refused = anki_sync.hold_known_words(language, "Anki known-words sync")
    if refused is not None:
        return anki_sync.SyncResult(mode="full", error=refused[0], busy=True, held_by=refused[1],
                                    total_known=anki_sync.count_known(language))
    try:
        try:
            path_utils.backup_to_trash(os.path.join(path_utils.get_user_files_path(language), anki_sync.KNOWN_FILE))
        except OSError as e:
            return anki_sync.SyncResult(mode="full", error=f"Could not keep a copy of your known words first, so "
                                        f"nothing was changed: {e}", total_known=anki_sync.count_known(language))
        return anki_window.run_sync(language, url, decks, chosen, suspended)
    finally:
        if held is not None:
            held.release()


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

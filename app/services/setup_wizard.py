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
- **The folders your shows and books are in** (SRC W1a; RUNBOOK §1b S1 + D1): page 3's picks are checked by the store's
  own rule (`folder_refused`), then on *Next* added and given setup's first look (`read_folders`: `Store.add_source`,
  `sources.scan(first=True)` — Current, quietly), a worker's; anything taken in offers *Needs you*'s one line, *Make
  cards for your first 20 episodes?*, whose *Make cards* logs them as entering the mine line by the user's choice
  (`first_cards`, after Connect's switch is on). *Skip a folder…* (K6): a folder inside the picked ones checked by the
  store's rule (`skip_refused`), skipped on *Next* before its folder's first look (`read_folders(skips=)`).

Nothing here waits on the caller's thread except the calls named as a worker's.
"""
import os
import time

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
PASSED = "setup_passed"         # the pages a profile that never finished saved with *Next* (shown as saved next time)
BIG_LIBRARY = 15000             # K5 (Sonic 2026-10-25): setup's first look warns once it has found this many items
BUSY_WAIT_S = 0.5               # K4: a busy library (another save, another look) is asked again this often while page
                                # 3 waits — never given up on (*Stop* ends the wait)


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
        draft = {"language": {"language": language},
                 "known": {"how": "anki", "decks": decks},
                 "shows": {"covers": True},
                 "order": {"keep_in_order": True, "deck": deck, "later": "leave"},
                 "cards": {"make_cards": True, "open_anki": False},
                 "level": {"automatic": True, "band": band}}
        passed = [p for p in PAGES if p in (settings.get(PASSED) or [])]
        if passed:                  # *Finish later*, then back: a page already saved shows what it saved (IK2-2)
            now = _current(settings, language, decks, deck, band)
            draft.update({p: now[p] for p in passed})
        return draft
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
            "order": {"keep_in_order": kept, "deck": deck, "later": _later_of(settings)},
            "cards": {"make_cards": settings.get("connect_enabled") is True,
                      "open_anki": settings.get("connect_open_anki") is True},
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
        return out
    if page == "cards":
        if answers.get("make_cards") is None:
            return {}
        out = {"connect_enabled": bool(answers.get("make_cards"))}
        open_anki = answers.get("open_anki")
        # Connect's: only with *Make cards* on (alpha 3 IK-4); *Set up again* writes it only when it changed (AD-1…3)
        if answers.get("make_cards") and open_anki is not None and (
                _new(settings) or bool(open_anki) != (settings.get("connect_open_anki") is True)):
            out["connect_open_anki"] = bool(open_anki)
        return out
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
    settings = thaw(settings_service.get())
    changes = writes(page, answers, settings, language)
    mark = _passed(settings, page) if changes else {}
    if page == "known" and changes:
        language = _language(language)
        settings_service.set(dict({k: v for k, v in changes.items() if k != "anki_sync_decks"}, **mark),
                             update=_decks_update(language, changes["anki_sync_decks"][language]))
    elif changes:
        settings_service.set(dict(changes, **mark))
    return changes


def _passed(settings, page):
    """A profile that never finished setup: `page` among the pages saved with *Next* (`PASSED`, in page order), so
    *Finish later* and back shows what was saved, never the recommended choice over it -> {} once setup finished."""
    if not _new(settings):
        return {}
    had = settings.get(PASSED) or []
    return {PASSED: [p for p in PAGES if p in had or p == page]}


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
    "folder" (where its first file is), "kind" (W3.2 Q3: "shows" · "reading" · "videos" by the title's media type, as
    the rows' stones read it; None for files no title holds)}] in the library's order (NOW, Soon, 6+ Months, New arrivals); [] for an empty
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
            "SELECT i.work_id, w.title, i.rel_path, i.root_id, w.media_type FROM items i "
            "LEFT JOIN works w ON w.id = i.work_id "
            f"WHERE i.tier IN ({', '.join('?' * len(LISTED_TIERS))}) ORDER BY CASE i.tier {rank} END, i.ord, i.id",
            LISTED_TIERS).fetchall()
    except Exception as e:
        print(f"Setup: the library couldn't be read ({e})")
        return []
    finally:
        store.close()
    from app.services.stone_plan import _KIND             # --- W3.2 Q3: a title's kind, as its row's stones read it
    titles = {}
    for work_id, title, rel, root_id, media_type in rows:
        folder_rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
        key = ("work", work_id) if work_id is not None else ("folder", root_id, folder_rel)
        row = titles.get(key)
        if row is None:
            base = roots.get(root_id) or data_dir
            name = title or (folder_rel.rsplit("/", 1)[-1] if "/" in folder_rel else "") or rel.rsplit("/", 1)[-1]
            titles[key] = row = {"name": name, "count": 0,
                                 "folder": os.path.normpath(os.path.join(base, *folder_rel.split("/"))),
                                 "kind": _KIND.get(media_type, "shows") if work_id is not None else None}
        row["count"] += 1
    return list(titles.values())


def add_samples(language):
    """(A worker; W3.2 Q3.) *Try it with samples first*: the bundled samples copied into the tier folders that are still
    empty (`path_utils.seed_samples`, the Content Manager's own), then those folders synced into the store, as the
    Content Manager synced them (`sync_for_window`) -> how many were copied (0: the library has files)."""
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path, seed_samples
    language = _language(language)
    n = seed_samples(language)
    if n:
        try:
            store = library_store.open_store(language, get_data_path(language), get_user_files_path(language),
                                             role="window")
            if store is not None:
                with store:
                    library_store.sync_for_window(store, [library_store.FOLDER_OF_TIER[t]
                                                          for t in library_store.ANALYSED])
        except Exception as e:
            print(f"Setup: the samples' folders couldn't be synced now ({e}); the next sync takes them in")
    return n


def _window_store(language, role="window"):
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    return library_store.open_store(language, get_data_path(language), get_user_files_path(language), role=role)


def folder_refused(language, path):
    """(A worker; SRC W1a.) Why page 3 can't read `path` as a folder of shows and books — the store's own rule (B3,
    `NotASource`'s plain words: Surasura's own folders, a whole drive, the user folder, not a folder) — or None. No
    library yet: None (going on says so). Nothing is written."""
    store = _window_store(_language(language), role="reader")
    if store is None:
        return None
    try:
        return store._not_a_source(path)
    finally:
        store.close()


def skip_refused(language, path, chosen=()):
    """(A worker; K6.) Why page 3 can't skip `path` (*Skip a folder…*) — the store's own rule
    (`library_store.skip_refusal`'s plain words) over the folders already read and the ones `chosen` on the page — or
    None. No library yet: the chosen folders alone. Nothing is written."""
    from app import library_store
    sources, skipped = [(None, p) for p in chosen or ()], []
    store = _window_store(_language(language), role="reader")
    if store is not None:
        try:
            sources += store._read_sources()
            skipped = [f["key"] for f in store.skipped_folders()]
        finally:
            store.close()
    return library_store.skip_refusal(path, sources, skipped)[0]


class _Waiting(Exception):
    """(Inside `read_folders`.) Another look is reading the library: wait for it, as for a busy store."""


def _patient(call, stop, waiting):
    """K4 (alpha 4, Mattias's note 5: page 3 said "couldn't be read: the library is busy" and gave up): `call()`, asked
    again every BUSY_WAIT_S while the library is busy — another window's or program's save (`StoreBusy`), or another
    look reading it — with `waiting(True)` once it has to wait and `waiting(False)` when it goes on. -> `call()`'s
    answer, or `_STOPPED` when *Stop* was pressed while it waited (a look keeps what it took in before)."""
    from app import library_store
    told = False
    try:
        while True:
            try:
                return call()
            except (library_store.StoreBusy, _Waiting):
                pass
            if stop is not None and stop():
                return _STOPPED
            if not told and waiting is not None:
                waiting(True)
                told = True
            time.sleep(BUSY_WAIT_S)
    finally:
        if told and waiting is not None:
            waiting(False)


_STOPPED = object()


def read_folders(language, paths, progress=None, stop=None, skips=(), waiting=None, copying=None):
    """(A worker; SRC W1a.) *Next* on page 3 with folders picked: each one added (`Store.add_source`) and given its first
    look (`sources.scan(first=True)`: SRC-1 — Current, by show, quietly: no card is made for them by itself, S1) ->
    {"ready", "found", "shows", "added", "stopped", "busy", "read" [path], "refused" [(path, why)], "unreachable"
    [path], "failed" [(path, why)], "offered"}. `read`: the folders this call dealt with (taken in, refused,
    unreachable, failed); the others — after a Stop, or a look already running — weren't looked at, to read later.
    `progress(found, shows)`: every folder's so far; `stop()` is asked between files — a stopped look keeps what it
    took in. `skips` (K6, *Skip a folder…*): folders inside them never read — each skipped (`Store.skip_folder`) as soon
    as the folder holding it is added, before its look; one no folder read holds is refused (`refused`, its reason).
    K4: a busy library — another save, another look — is waited for (`waiting(True)` / `waiting(False)`,
    page 3's *Waiting for your library…*) and the read goes on by itself; *Stop* ends the wait (`stopped`; the folder
    not reached stays listed). `busy` stays False (kept for an older caller). K5: `copying(done, total)` while a
    folder's new files are copied in (`sources.scan`'s, that folder's); page 3 warns once `found` reaches BIG_LIBRARY.
    `ready` False: no library yet (nothing done). Episodes taken into the mine line → the one *Needs you* line,
    *Make cards for your first 20 episodes?* (D1); none there (Current was already full: *Set up again*, an upgrade)
    → no line."""
    from app import library_store, sources
    from app.connect import library
    from app.services import needs
    language = _language(language)
    out = {"ready": True, "found": 0, "shows": 0, "added": 0, "stopped": False, "busy": False, "read": [],
           "refused": [], "unreachable": [], "failed": [], "offered": False}
    store = _window_store(language)
    if store is None:
        return dict(out, ready=False)
    taken, pending = [], list(skips or ())
    with store:
        for path in paths:
            if stop is not None and stop():
                out["stopped"] = True
                break
            try:
                root = _patient(lambda path=path: store.add_source(path), stop, waiting)
            except library_store.NotASource as e:
                out["refused"].append((path, e.reason))
                out["read"].append(path)
                continue
            except Exception as e:                       # a damaged store: this folder's, never the others'
                out["failed"].append((path, str(e)))
                out["read"].append(path)
                continue
            if root is _STOPPED:
                out["stopped"] = True
                break
            halted = False
            for skip in list(pending):                   # K6: before its look, so nothing of it is ever read
                try:
                    if _patient(lambda skip=skip: store.skip_folder(skip), stop, waiting) is _STOPPED:
                        halted = True                    # stopped before its skip: its look never runs (unread)
                        break
                    pending.remove(skip)
                except library_store.NotASource:
                    pass                                 # (inside a folder added later, perhaps)
                except Exception as e:
                    out["failed"].append((skip, str(e)))
                    pending.remove(skip)
            if halted:
                out["stopped"] = True
                break
            before = (out["found"], out["shows"])

            def told(found, shows, before=before):
                if progress is not None:
                    progress(before[0] + found, before[1] + shows)
            def look(root=root, told=told):
                got = sources.scan(store, language, root, first=True, progress=told, stop=stop, copying=copying)
                if got.get("busy"):
                    raise _Waiting()                     # another look is reading: wait for it, then look
                return got
            try:
                got = _patient(look, stop, waiting)     # a busy store mid-look: what came in is kept, the look goes on
            except Exception as e:                       # one folder's failure never ends the others' looks
                out["failed"].append((path, str(e)))
                out["read"].append(path)
                continue
            if got is _STOPPED:
                out["stopped"] = True
                break
            out["read"].append(path)
            if not got.get("reachable", True):
                out["unreachable"].append(path)
                continue
            for key in ("found", "shows", "added"):
                out[key] += int(got.get(key) or 0)
            taken += list(got.get("ids") or ())
            if got.get("stopped"):
                out["stopped"] = True
                break
        if not (out["stopped"] or out["busy"]):
            out["refused"] += [(s, store.skip_refused(s) or library_store.SKIP_OUTSIDE) for s in pending]
        try:
            in_line = bool(set(taken) & set(library.mine_line(store))) if taken else False
        except Exception as e:
            print(f"Setup: the mine line couldn't be read ({e})")
            in_line = False
    if in_line:
        try:
            needs.offer(language, needs.FIRST_CARDS)
            out["offered"] = True
        except Exception as e:                           # the seen file held or newer: the line isn't offered
            print(f"Setup: the cards line couldn't be offered ({e})")
    return out


def first_cards(language, settings, data_dir=None):
    """(A worker; D1's *Make cards*, once Connect is on.) The mine line's episodes — the first 20 of Current, there since
    setup's first scan, which logs nothing — logged as entering it by the user's own choice (`Store.enter_mine_line`,
    explicit, by "user"): Connect's inbox makes their jobs; then Connect kicked (`kick.kick`: nothing while it's off)
    -> the ids logged ([]: no library)."""
    from app import library_store
    from app.connect import kick, library
    from app.path_utils import get_data_path, get_user_files_path
    language = _language(language)
    store = library_store.open_store(language, data_dir or get_data_path(language), get_user_files_path(language),
                                     role="window")
    if store is None:
        return []
    with store:
        library.ensure_reader(store)                     # Connect's watermark first: what is logged next is read
        ids = store.enter_mine_line(by="user")
    try:
        kick.kick(settings or {})
    except Exception as e:                               # its next start reads the log anyway
        print(f"Setup: Connect wasn't started now ({e})")
    return ids


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

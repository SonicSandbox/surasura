"""What the window derives from the library (W2.2; the window's spec 02 §2.2–2.4): pure functions, Qt-free, so every
rule is tested without a window and the window only paints the answers.

From the store's feed rows (items and works by id, `FEED_ITEM_FIELDS` / `FEED_WORK_FIELDS`) and its options (the Soon
line, the mine line), the plan's numbers per item, each item's cards and the items being mined now, `build` makes one
frozen `View`:
- **Current** = NOW then Soon, in `(ord, id)`; **a row is a piece**: one contiguous run of one work's items in one tier
  (by `piece_id`; a run without one by its work, then its folder: 3.0-dev's stores before L3.1 seeded pieces) — but a
  show the Soon line runs through is one row, above the line (`soon_from`, P-LF-16: the tiers stay per file).
- **The hero** is Current's first row, its *Up next* the first episode not watched (02 §2.2).
- **The top-20 line** follows the store's mine line: the top *n* **available** files of Current mine themselves
  (`_mine_ids`); the line is drawn after the row holding the *n*-th, and not at all with fewer (the mock: none under 20).
  **The Soon line** is drawn where Soon starts (the store keeps the tiers on its line, a count of files) — after a show
  it runs through, never inside it.
- ***% known*** is one number everywhere (QT-E8, G1.2-4): known tokens ÷ counted tokens, summed over the piece (never a
  mean of per-file percents); none before a Generate (an em dash, never 0 %). ***N new*** is the list words the piece is
  first to bring (summed).
- **One status vocabulary** for a row (the hero's head too: its row's, Q33) and an open row's episodes (the mock's
  `stHTML`, in its order): ✓ *N in Anki* · *Mining* · *Waiting* · ✓ *k/n · Mine rest* · *Mine* · *No video* / *Video
  removed* — and the on-disk mark (⌀ N) beside it when something isn't there. *In Anki* only while its cards are there
  (Sonic, 2026-10-07): a file mined whose cards are all gone reads a faint *No cards in Anki* (Sonic's shelf ruling:
  never *Waiting*, never mined again unless asked; an asked-for mining outranks it). Status is a glyph and a label (and
  a tone the painter maps to a colour), never colour alone.
- Goal's strip, Finished by month (newest first; no date → *Earlier*), Needs you's entries (each show with files the top
  20 waits on that aren't on disk), the badges, the header's subline, each row's accessible text, and the section's
  state (full · empty · loading · getting ready · read-only; busy beside any of them).
- **New arrivals' tray** (W3.2 S1): a row per piece of the arrivals tier, newest first by `added_at`, *New* then
  *Already watched*, each with its source chip, its one line and the number slot the arrivals worker's estimates fill
  (*N new / ep*). The badge stays the file count.

Every user-facing word is here or in the window's strings; nothing here imports Qt, Tk or pandas (the import guard).
"""
import re
from collections import namedtuple

from app.connect import feed as connect_feed     # P4.1 L2: Connect's kinds (a light module: no Qt, no Tk)
from app.episode_names import identity           # LM1a: the one reading of a file name (pure)
from app.path_utils import infer_source_type
from app.services import stone_plan

CACHE_ROWS = 40                         # the first screen's rows kept in window_cache_<lang>.json
LANGUAGE_NAMES = {"ja": "日本語", "zh": "中文"}
HATO_FOLDER = "HighPriority/Hato/"
LEARNED_AT = 97                         # ≥ → the learned colour (research/09)
HEADS_UP_BELOW = 93                     # < → heads-up
CHIPS_SHOWN = 12
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")

# media words and verbs by the work's media type (`library_store.MEDIA_TYPES`; None → video: `media_type()`'s rule)
MEDIA_WORD = {"anime": "video", "drama": "video", "movie": "video", "youtube": "video", "podcast": "audio",
              "audiobook": "audio", "book": "EPUB", "lightnovel": "EPUB", "manga": "EPUB", "game": "file",
              "text": "file", None: "video"}
VERB = {"video": "Watch", "audio": "Listen", "EPUB": "Read", "file": "Open"}
EPISODIC = ("anime", "drama", "movie", None)

Status = namedtuple("Status", "kind label tip tone")          # tone: ok · accent · dim · ink · faint · warn
# --- R47 (laptop rows 47 + 56): `stop`, the Connect job a *Mining* status's *Stop* stops (`feed.Item.job`, while
# `feed.Item.stoppable`), else None. Never in the first screen's cache (Connect's state isn't known from a cache)
Status = namedtuple("Status", Status._fields + ("stop",), defaults=(None,))
# --- MV-2: `moved`, the folder a *No video* status's video left (`feed.Item.moved`: the status offers *Find its
# folder*), else None
Status = namedtuple("Status", Status._fields + ("moved",), defaults=(None, None))
Mark = namedtuple("Mark", "count tone tip")                    # the on-disk mark (⌀ N)
Episode = namedtuple("Episode", "id label number title watched cards mining missing removed in_top pct n_new "
                                "status mark rel_path play_tip can_play deleted waiting", defaults=(False, False))
#   waiting (SRC K5 / W1b): a video found in a source folder with no subtitle yet — never played, read or mined
Episode = namedtuple("Episode", Episode._fields + ("media_word",), defaults=(False, False, None))
#   media_word (LM11b G1): its own show's (`MEDIA_WORD`) — a group holds several types; None in a cache from before
Episode = namedtuple("Episode", Episode._fields + ("work_id", "show"),
                     defaults=tuple(Episode._field_defaults.values()) + (None, None))
#   work_id, show (LM11b G5): the work it is of, and in a group its show's name as the group labels it (None in a
#   run); both None in a cache from before. What *Move {show} to Finished* takes and names (`drag.show_finished`)
Episode = namedtuple("Episode", Episode._fields + ("show_key",),
                     defaults=tuple(Episode._field_defaults.values()) + (None,))
#   show_key: in a group, which show it is of (`_show_key`: its work, else its folder) — where an opened group's show
#   lines stand (`rows.show_starts`); None in a run and in a cache from before
Episode = namedtuple("Episode", Episode._fields + ("ask",), defaults=tuple(Episode._field_defaults.values()) + (None,))
#   ask (row 55): what ▶'s lookup is asked for it — (rel_path, media) — or None where ▶ can't be anyway (missing,
#   waiting for its subtitle, online, Connect's *No video*); `play.Looks` answers it, `build(playable=)` reads the answer
Episode = namedtuple("Episode", Episode._fields + ("looking",),
                     defaults=tuple(Episode._field_defaults.values()) + (False,))
#   looking (row 55, R55-A): asked and not answered yet — Up Next says *Looking…*, never *No video* before the check
Episode = namedtuple("Episode", Episode._fields + ("moved",),
                     defaults=tuple(Episode._field_defaults.values()) + (None,))
#   moved (MV-2): the folder its video left — Connect's line (`feed.Item.moved`), else ▶'s own look's
#   (`play.MovedAway`): its ⋯ offers *Find its folder…*, Connect on or off, any language, mined or not
#   answered; False with no looker and in a cache from before
Row = namedtuple("Row", "key index tier work_id piece_id media media_word verb title title_ep line source n_files n_watched "
                        "pct pct_tone n_new status mark episodes next_index studying date cover_title accessible "
                        "description chips more_chips play_tip can_play cards_out string", defaults=(False, None))
#   cards_out (W3.2 Q4): a piece with an item out of the learning order (`in_learning_order` 0: Finished's *Leave its
#   new cards out of your order*) — ⋯ shows *Put them back in the order* then; never painted
#   string: a Current row's (stone plan, its need at its tightest — `stone_plan`, fz 1), planned here, on the reader's
#   thread, once per row content (W3.1a B2); None on Finished's rows and on the first screen's cached rows
Chip = namedtuple("Chip", "text watched next mined tip")
Line = namedtuple("Line", "kind after tip split")              # drawn after row `after` (0-based in Current);
#                                                                 `split`: the row's first `split` files are above it
Goal = namedtuple("Goal", "titles files covers line tip works", defaults=((),))     # works: W3.2 Q2 (below)
# --- W3.2 Q2: Goal's sheet — one tile per title in Goal's order (`works`), each with its pieces in order (a piece's
# files and its range): *Move to the top* / *Soon* and a drag take the first piece, the rest stays in Goal (G2). Not in
# the first screen's cache (the first frame shows no sheet)
GoalWork = namedtuple("GoalWork", "key work_id title cover_title media source n_files line pieces item_ids folder "
                                  "tip accessible")       # folder: its first file's, in the data folder (*Open its folder*)
GoalPiece = namedtuple("GoalPiece", "item_ids line piece_id", defaults=(None,))
#   piece_id (LM11b G3, IK-6): the piece its files are — what *Same show as…* joins a Goal show by; None when made
#   without one. Tiles never enter the first screen's cache
# --- end W3.2 Q2
Month = namedtuple("Month", "label rows")
Need = namedtuple("Need", "key work_id title line episodes cover_title")
Arrival = namedtuple("Arrival", "key work_id piece_id item_ids rel_paths title media media_word source chip channel "
                                "line cards no_media parts n_files watched group added_at cover_title per_ep tip "
                                "accessible")
#   one New arrivals row (W3.2 S1): a piece of the arrivals tier. `source` the chip's colour key (hato · youtube ·
#   anilist · disk), `chip` its word; `line` *Ep x–y* or a video's channel; `parts` the one line as (text, tone):
#   the line, *N in Anki* (ok), *N files gone* (warn); `group` "new" or "watched" (every file watched); `per_ep` the
#   estimate's *N new* (at the top of Current) over its files, rounded — None until every file has one
ArrivalGroup = namedtuple("ArrivalGroup", "kind label rows")
Counts = namedtuple("Counts", "current_rows current_files goal_titles goal_files finished arrivals arrival_files")
View = namedtuple("View", "language mode reason state busy loading cached rows lines goal finished needs counts "
                          "subline badges worst arrivals arrival_groups", defaults=(None, (), ()))
# --- P4.1 L2: `connect`, the Connect feed the view was built with (`app/connect/feed.Feed`, or None: no Connect) —
# its `on` tells the stones whether they may act (IK S7). Never in the first screen's cache
View = namedtuple("View", View._fields + ("connect",), defaults=tuple(View._field_defaults.values()) + (None,))
# --- end P4.1 L2
# --- LM11b: `epoch`, the store's epoch the view was read at (a library rebuilt or reset has another: the window's picks
# go with it), or None (no store read)
View = namedtuple("View", View._fields + ("epoch",), defaults=tuple(View._field_defaults.values()) + (None,))
# --- W-1: `keep_watched`, the library's *Keep studying watched episodes* as the feed's options gave it (the stones' tip
# line, the first mark's toast, an episode's *Mine now*); False in the first screen's cache
View = namedtuple("View", View._fields + ("keep_watched",), defaults=tuple(View._field_defaults.values()) + (False,))
#   worst: Current's rows below Up Next, the most-needing string per kind of Anki count beside it (`worst_needs`)
#   arrivals: the tray's rows as it shows them (New, then Already watched; each newest first); arrival_groups: the
#   groups that hold any, in that order. Neither is in the first screen's cache (the first frame shows no tray)
# --- W3.2 Q6: each row's, card's, tray row's and Goal cover's record, as the window decodes it (`app/qt/covers.py`)
CoverRef = namedtuple("CoverRef", "work_id source ref path locked")
Row = namedtuple("Row", Row._fields[:Row._fields.index("string")] + ("cover",) + Row._fields[Row._fields.index("string"):],
                 defaults=(None,) + tuple(Row._field_defaults.values()))
#   before `string`, which stays last (the first screen's cache writes it None; a cache from before reads cover None)
Need = namedtuple("Need", Need._fields + ("cover",), defaults=(None,))
Arrival = namedtuple("Arrival", Arrival._fields + ("cover", "waiting"), defaults=(None, 0))   # SRC W1b: no subtitles
# --- P4.1 WF (adversary S5): a tray row's files as Current's rows hold them (`Episode`), so *Mine them too* asks by the
# rows' rule (never a file in Anki or whose cards were deleted). Never in the first screen's cache (the tray isn't)
Arrival = namedtuple("Arrival", Arrival._fields + ("episodes",), defaults=((),))
Goal = namedtuple("Goal", Goal._fields + ("cover_refs",), defaults=tuple(Goal._field_defaults.values()) + ((),))    # beside `covers`, the first nine works'
# --- W3.2 L3: a Goal tile's cover record (the sheet paints its picture)
GoalWork = namedtuple("GoalWork", GoalWork._fields + ("cover",), defaults=(None,))
# --- end W3.2 L3
GoalWork = namedtuple("GoalWork", GoalWork._fields + ("group",), defaults=(None, False))     # LM11b G1: a group's tile
# --- P-LF-16: `soon_from`, the index of the first Soon file of a show the Soon line runs through (the store's line is a
# count of files, so it can fall inside a show): the window never splits a show at the line (Sonic, 2026-10-21: "it
# should show after the series in the UI and a soon show should be added after that series") — the show is one row
# above the line, its files from `soon_from` on still Soon for the count and Generate (where a drop after it lands:
# `app/qt/drag.tail_tier`). None on every other row; before `string`, which stays last. `soon_piece`: those Soon
# files' own piece (a piece is in one tier), what ✂ *Split here* splits among them (`split_piece`, B2-2)
Row = namedtuple("Row", Row._fields[:Row._fields.index("string")] + ("soon_from", "soon_piece") + ("string",),
                 defaults=tuple(Row._field_defaults.values())[:-1] + (None, None, None))
# --- LM11b G1: `group`, a piece of kind 'group' (the learner's own row of several shows: Kura's LM11): its stored name or
# "<first show> + N more", its first episode's show's work, cover and type, each episode read by its own show's type.
# Before `string`, which stays last (a first screen's cache from before reads it falsy)
#   works: the distinct work ids its episodes are of, in episode order — a run's `(work_id,)`, a row of no work `()`
Row = namedtuple("Row", Row._fields[:Row._fields.index("string")] + ("group", "works", "string"),
                 defaults=tuple(Row._field_defaults.values())[:-1] + (False, (), None))
# --- end LM11b G1


def cover_of(work):
    """A work's cover record (`CoverRef`), or None for a row without a work: what the window needs to find its picture
    (`app/services/covers.image_path`) — a new record is a new row (the reader's cache keeps a row while its work is
    the same object)."""
    if not work or work.get("id") is None:
        return None
    return CoverRef(work["id"], work.get("cover_source"), work.get("cover_ref"), work.get("cover_path"),
                    bool(work.get("cover_locked")))
# --- end W3.2 Q6

STRINGS = {
    "dash": "—",
    # a status's words (its glyph is painted beside them: check · spinner · hourglass · card-plus · no-video)
    "in_anki": "{n}", "in_anki_words": "{n} in Anki", "mining_kn": "Mining · {k}/{n}", "mining": "Mining…",
    "mining_pct": "Mining · {pct}%", "tip_mining_doing": "Making its cards now: {doing}",
    "tip_ask_battery": "{tip}\n• Click to mine this one now, on battery",
    "tip_ask_anki": "{tip}\n• Click: it goes first once Anki answers",
    "waiting": "Waiting", "waiting_kn": "{k}/{n} · Waiting", "mine_rest": "{k}/{n} · Mine rest", "mine": "Mine",
    "no_media": "No {word}", "no_media_n": "No {word} · {n}", "removed": "{Word} removed",
    "deleted": "No cards in Anki", "deleted_n": "No cards in Anki · {n}",
    "tip_deleted": "It was mined, but none of its cards are in Anki now: cards you deleted aren't made again "
                   "unless you ask",
    "tip_in_anki": "Mined · {n} cards in Anki", "tip_in_anki_k": "{k} mined · {n} cards in Anki",
    "tip_mining": "Making its cards now",
    # R47 (laptop rows 47 + 56, PROVISIONAL words): Stop's states, and an ask Connect has read (its own status)
    "stopping": "Stopping…", "tip_stopping": "Stopping: the cards made so far are kept",
    "tip_finishing": "\nFinishing its cards: too far along to stop", "asked": "Asked",
    "tip_asked": "Its cards come next",
    "tip_waiting": "In your top {line}: it mines by itself, in turn",
    "tip_mine_rest": "{k}/{n} mined · the rest isn't in your top {line} yet",
    "tip_mine": "Not in your top {line}: it isn't mined yet",
    # row 13 (laptop fixes): Connect off — no top line, so no "top" in the words either
    "tip_mine_rest_off": "{k}/{n} mined", "tip_mine_off": "It isn't mined yet",
    "tip_no_media": "No {word} on disk{top}\n• Link one for pictures and audio, or mine the text on its own",
    "tip_no_media_top": " — it's in your top {line}, so it's waiting for one",
    "tip_removed": "Its {word} was removed after it was mined. The cards keep their pictures and audio",
    # --- P4.1 L2: what Connect's feed says of an item (row 4.1.10; the reason lines are the runner's)
    "tip_connect_no_media": "{tip}\n• Link one for pictures and audio, or mine the text on its own",
    # MV-2 (Sonic: yes): its video left the folder it was in — Connect's line names it; *Find its folder* adds the
    # folder you pick as one Surasura reads, and the show finds its episodes there
    "tip_connect_moved": "{tip}\n• Find its folder, link its video, or mine the text on its own",
    "play_moved": "{tip}\n• Find its folder: in its ⋯ menu, or on its No {word}",
    "not_timed": "Not timed", "tip_not_timed": "{words}: its cards wait for you\n• Check it plays in time, then "
                                                "Mine anyway: in Needs you",
    # T2 (alpha 2's try, Sonic's correction): a refusal whose Needs you entry you dismissed — skipped, no waiting
    "tip_skipped": "Not timed to its video: skipped, as you dismissed it\n• Checked again when its subtitle or video "
                   "changes",
    # --- end P4.1 L2
    # a tooltip's action on a line of its own, as a bullet (G2.3 T1); never a "( … )" a line break can cut
    "mark_missing": "{eps}: {gone}",                  # R55-C (Sonic): Up Next's own words, which episodes first
    "mark_removed": "{Word} deleted after mining: {eps}\nThe cards keep their pictures and audio; only ▶ can't play it",
    "play": "{verb} {name} in your {player}\nThe {word} beside its subtitle file",
    "play_online": "Its video is online: opening it from here comes in a later build",
    # row 55: ▶'s own lookup found nothing to open (PROVISIONAL words)
    "play_not_found": "No {word} found for it on this computer, so there is nothing to {verb_l} from here",
    # R55-A (Sonic): before the check has answered, Up Next says *Looking…*; its tip says only that (A-11)
    "play_looking": "Looking for its {word} on this computer…",
    # --- W3.2 Q5: an item whose content file is gone says so (its *video* is Connect's, S3), never "no video"
    "play_missing": "Its file is gone from your library folder\n• Point it at its file in Needs you",
    "play_missing_plain": "Its file is gone from your library folder, so it can't {verb_l} from here",
    "play_removed": "Its {word} was removed\n• Link it to {verb_l} it from here: Needs you, in a later build",
    # --- SRC W1b: a video found in a source folder, its subtitle not there yet (K5's `waiting`)
    "play_waiting": "No subtitles yet: its {word} is in your folder, its subtitle file isn't\nIt can be watched and "
                    "mined once one arrives there",
    "no_subs": "No subtitles yet", "no_subs_n": "No subtitles yet · {n}",
    "tip_no_subs": "Its {word} is in your folder, its subtitle file isn't yet: nothing to read or mine until one "
                   "arrives. Surasura fills it in by itself",
    "arr_no_subs": "no subtitles yet",
    "eps_more": " and {n} more",
    "player": {"video": "video player", "audio": "audio player", "EPUB": "e-book reader", "file": "default app"},
    # a book split by its chapters (Hon, alpha 4): its part's name after its number, `extract.part_label`'s
    "chapter": "Chapter {c}", "chapter_part": "Chapter {c} · Part {x}", "titled_part": "{title} · Part {x}",
    "ep": "Ep {n}", "part": "Part {n}", "num": "#{n}", "eps": "Ep {a}–{b}", "parts": "Parts {a}–{b}",
    "nums": "#{a}–{b}", "videos": "{n} videos", "video": "1 video", "watched": "{k} of {n} watched",
    # a watched file set aside (Keep studying watched episodes off): the stone's tooltip and the report's panel (JS-1)
    "watched_leaves": "Watched: its words leave your list.",
    "channel_n": "{n} videos · {title}",
    "top_tip": "Everything above this line mines itself: your top {n} files",
    "top_tip_split": "Everything above this line mines itself: your top {n} files — of {title}, its first {k} of {m}",
    "soon_tip": "Soon: what's below this line comes after your first {n} files. It still counts toward your list",
    "soon_tip_nocount": "Soon: what's below this line comes after what's above it. It still counts toward your list",
    "goal_line": "{titles} titles · {files} files", "goal_one": "1 title · {files} files",
    "goal_empty": "Goal is empty",
    "goal_tip": "Someday, in no order: what you'll get to later. It counts toward your list",
    "earlier": "Earlier", "studying": "↑ Studying its cards first",
    "need_title_one": "{title} · {ep} has no {word}", "need_title_n": "{title} · {n} {unit} have no {word}",
    "need_line_one": "In your top {line}, so it's waiting on its {word} — each card's picture and audio come from it.",
    "need_line_n": "In your top {line}, so they're waiting on their {word} — each card's picture and audio come from it.",
    "need_ep": "no {word}", "unit_eps": "episodes", "unit_parts": "parts", "unit_files": "files",
    "subline": "{lang} · {rows} in Current · {files} files", "subline_empty": "{lang} · nothing added yet",
    "pct": "{pct}% known", "new": "{n} new", "hero_stats": "{pct}% known · {n} new words",
    "hero_stats_none": "not analysed yet",
    "acc_row": "{title} · {pct} · {new} · {status}", "acc_pct_none": "not analysed",
    "acc_hero": "Up next: {title} {ep} · {pct} · {new} · all of it: {status}",     # AD-9: the status is its row's
    # New arrivals (W3.2 S1): the tray's groups, its source chips and each row's one line and number
    "arr_new": "New", "arr_watched": "Already watched",
    "chip": {"hato": "hato", "youtube": "YouTube", "anilist": "AniList", "disk": "disk"},
    "arr_cards": "{n} in Anki", "arr_no_media": "{n} files gone", "arr_no_media_one": "1 file gone",   # W3.2 Q5
    "per_ep": "{n} new / {unit}", "per_unit": {"eps": "ep", "videos": "video", "parts": "part"},
    "arr_units": {"eps": ("episode", "episodes"), "videos": ("video", "videos"), "parts": ("part", "parts")},
    "arr_each": {"eps": "an episode", "videos": "a video", "parts": "a part"},
    "per_ep_tip": "About {n} new words {each} if you put it at the top of Current\n{files} {units} · an estimate "
                  "until analysed",
    "per_ep_tip_none": "{files} {units} · its new words are counted when it first shows: an estimate until analysed",
    "acc_arrival": "{title} · {line} · {number}", "acc_per_ep_none": "not counted yet",
    # --- W3.2 Q2: Goal's tiles
    "goal_count": "{n} {units}",
    "goal_tile_tip": "{title} · {line}\nDrag it into Current to bring up {first}, or ⋯ to move it",
    "acc_goal_tile": "{title} · {line}",
    # --- end W3.2 Q2
    # --- LM11b G1: a group's row (its name until the learner gives it one; its next episode with its show)
    "group_name": "{first} + {n} more", "group_line": "{n} files · {k} shows", "group_ep": "{show} · {label}",
    "group_line_channels": "{n} videos · {k} channels",       # every show in it a YouTube channel
    "mixed_word": "media",            # a group's status word when its files are of different types (No media · 2)
}

_EXT = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_YT_ID = re.compile(r"\s*\[[0-9A-Za-z_-]{6,11}\]$")
_CHAPTER = re.compile(r".+?_([0-9]{2,}) \(([0-9]+)(?:-([0-9]+))?\)(?: (.+))?")  # `extract.part_name`'s chapter part
_PLAIN_PART = re.compile(r".*_[0-9]{2,}")                                              # `<base>_NN`: a part, no chapter


# --- small pieces ---------------------------------------------------------------------------------------------------- #
def journey_episode(row):
    """The episode a row's way into the journey opens on (its ⋯ *See it in your journey*, Up Next's ↗): its next one;
    a row whose every episode is watched, its first (Sonic 2026-10-24, JO-3). None for a row with none."""
    eps = getattr(row, "episodes", None) or ()
    if not eps:
        return None
    return eps[0] if all(e.watched for e in eps) else eps[row.next_index]


def stem(name):
    """A file's name without its extension or a YouTube id in brackets."""
    return _YT_ID.sub("", _EXT.sub("", name or "")).strip()


def chapter_part(name):
    """A book's part named by its chapter (`<book>_07 (3-2) 第一章 出会い.txt`) -> (its number, its label: *第一章 出会い ·
    Part 2*, *Chapter 3 · Part 2*, *プロローグ*, *Chapter 3*), else None."""
    if not str(name or "").lower().endswith(".txt") or _PLAIN_PART.fullmatch(stem(name)):
        return None                              # a video's or a subtitle's name is never a book's part
    m = _CHAPTER.fullmatch(stem(name))
    if m is None:
        return None
    number, c, x, title = int(m.group(1)), m.group(2), m.group(3), m.group(4)
    if title:
        return number, STRINGS["titled_part"].format(title=title, x=x) if x else title
    return number, STRINGS["chapter_part"].format(c=c, x=x) if x else STRINGS["chapter"].format(c=c)


def episode_number(name):
    """The episode (or part) number a file's name gives, or None: `S01E05`, `第5話`, `ep05`, `Show - 05`, `Show 05 …` —
    LM1a's one rule (`episode_names.identity`), a bare number read too (the window has no folder to ask); a special
    (`OVA 01`, `- 01 (OVA)`) has none here (A4: never *Ep 1*, nor episode 1's video offered for it)."""
    chapter = chapter_part(name)                 # a book's part named by its chapter: its number, never its title's
    if chapter is not None:
        return chapter[0]
    n = identity(name, bare_numbers=True)
    return None if n.special else n.episode


def runs(numbers):
    """[3, 4, 5, 7] -> [(3, 5), (7, 7)]."""
    out = []
    for n in sorted(set(numbers)):
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def range_text(media, numbers, count):
    """The row's range: *Ep 1–8*, *Ep 1–4, 6*, *#28–34, 36*, *Parts 5–12*, *3 videos*; without numbers for every file,
    the count (*8 episodes*)."""
    if media == "youtube":
        return STRINGS["video"] if count == 1 else STRINGS["videos"].format(n=count)
    if media in EPISODIC:
        one, many, unit = STRINGS["ep"], STRINGS["eps"], STRINGS["unit_eps"]
    elif media == "podcast":
        one, many, unit = STRINGS["num"], STRINGS["nums"], STRINGS["unit_eps"]
    else:
        one, many, unit = STRINGS["part"], STRINGS["parts"], STRINGS["unit_parts"]
    if not numbers or len(numbers) != count:
        return f"{count} {unit}"
    rs = runs(numbers)
    if len(rs) == 1:
        a, b = rs[0]
        return one.format(n=a) if a == b else many.format(a=a, b=b)
    head = many.split("{")[0]
    return head + ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in rs)


def pct_of(known, counted):
    return None if not counted else 100.0 * known / counted


def pct_tone(pct):
    """The *% known* colour (status colours, never themed): learned · heads-up · plain."""
    if pct is None:
        return "plain"
    r = round(pct)
    if r >= LEARNED_AT:
        return "ok"
    if r < HEADS_UP_BELOW:
        return "warn"
    return "plain"


def pct_text(pct):
    return STRINGS["dash"] if pct is None else f"{round(pct)}%"


def thousands(n):
    return f"{n:,}"


def month_label(stamp):
    """`2026-09-02T…` -> *September 2026*; None -> *Earlier*."""
    if not stamp or len(stamp) < 7:
        return STRINGS["earlier"]
    try:
        y, m = int(stamp[:4]), int(stamp[5:7])
        return f"{MONTHS[m - 1]} {y}"
    except (ValueError, IndexError):
        return STRINGS["earlier"]


def day_label(stamp):
    """`2026-09-02T…` -> *Sep 2*."""
    if not stamp or len(stamp) < 10:
        return ""
    try:
        return f"{MONTHS[int(stamp[5:7]) - 1][:3]} {int(stamp[8:10])}"
    except (ValueError, IndexError):
        return ""


def media_type_guess(counts, anilist_id=None, tmdb_id=None):
    """A title's type when nobody said — L3.1's `library_store.media_type_guess`, the same rule (computed on read,
    never stored): from its items' source types ({type: count}) and its ids; None → *Video*."""
    if not counts:
        return None
    kind = max(counts, key=lambda k: (counts[k], k or ""))
    if kind in ("youtube", "bilibili"):
        return "youtube"
    if kind == "epub":
        return "book"
    if kind == "text":
        return "text"
    if kind == "subtitle":
        if tmdb_id and str(tmdb_id).startswith("movie:"):
            return "movie"
        if anilist_id:
            return "anime"
        if tmdb_id and str(tmdb_id).startswith("tv:"):
            return "drama"
    return None


def source_of(item, work):
    """hato · youtube · anilist · None: where an item came from (its chip's colour)."""
    if (item.get("rel_path") or "").startswith(HATO_FOLDER):
        return "hato"
    if item.get("source_type") in ("youtube", "bilibili") or (work or {}).get("media_type") == "youtube":
        return "youtube"
    if (work or {}).get("anilist_id"):
        return "anilist"
    return None


# --- pieces ------------------------------------------------------------------------------------------------------- #
def ordered_tier(items, tier):
    rows = [r for r in items.values() if r.get("tier") == tier]
    rows.sort(key=lambda r: (r.get("ord") or 0.0, r["id"]))
    return rows


def _same_show(a, b):
    """Whether two items are of one show: one work; without one, one folder — whatever their pieces (the NOW and Soon
    runs of a show the Soon line cuts are two pieces, a piece being in one tier: the row keeps the NOW piece's id, its
    Soon files their own, `soon_piece`)."""
    if a.get("work_id") is not None or b.get("work_id") is not None:
        return a.get("work_id") == b.get("work_id")
    return a.get("parent_folder") is not None and a.get("parent_folder") == b.get("parent_folder")


def split_piece(row, k):
    """✂ *Split here* before the row's `k`-th episode (0-based), by that episode's own piece: a show the Soon line runs
    through holds two (`piece_id` up to `soon_from`, `soon_piece` from it) -> (piece_id, the episode's place in that
    piece), or None where the split would change nothing — the first file of a piece (the Soon line already parts the
    show there) or a run with no piece (B2-2). One piece on both sides of the line (a store before L3.1's seeding):
    that piece, the episode's place in the row."""
    cut = getattr(row, "soon_from", None)
    if cut is not None and k >= cut and row.soon_piece != row.piece_id:
        piece, at = row.soon_piece, k - cut
    else:
        piece, at = row.piece_id, k
    return (piece, at) if piece is not None and at > 0 else None


def soon_line_after(rows):
    """The row the Soon line is drawn under, or None — one rule for the reader's view and the drag's (`drag.lines_for`):
    under a show the line runs through (`soon_from`, P-LF-16) — even when that show holds the whole of Soon (B2-9) —
    else under the row before Soon's first; none with nothing above Soon."""
    for i, row in enumerate(rows):
        if getattr(row, "soon_from", None) is not None:
            return i
        if row.tier == "soon":
            return i - 1 if i > 0 else None
    return None


def pieces(rows):
    """Contiguous runs of one piece (`piece_id`; without one: one work, then one folder) -> [[item, …], …]."""
    out = []
    last = None
    for r in rows:
        key = ("p", r["piece_id"]) if r.get("piece_id") is not None else \
            ("w", r["work_id"]) if r.get("work_id") is not None else ("f", r.get("parent_folder") or r["id"])
        if out and key == last:
            out[-1].append(r)
        else:
            out.append([r])
            last = key
    return out


_pieces = pieces                        # `build`'s name for it (its `pieces` argument is the feed's, LM11b G1)


# --- statuses ---------------------------------------------------------------------------------------------------- #
def _eps_list(eps):
    labels = [e.label for e in eps[:3]]
    more = len(eps) - 3
    return ", ".join(labels) + (STRINGS["eps_more"].format(n=more) if more > 0 else "")


def _said(line):
    """A row's spoken line with an empty part left out (row 36: no *N new* yet says nothing, never a dash)."""
    return line.replace(" ·  · ", " · ")


def spoken(status):
    """A status as a screen reader says it: the pill shows ✓ and the number only (G2.3 R2), the words go with it."""
    if status is not None and status.kind == "in_anki":
        return STRINGS["in_anki_words"].format(n=status.label)
    return status.label if status is not None else ""


def status_of(eps, word, line_n):
    """One status for a set of episodes (a row's, or one episode's), in the mock's order (`stHTML`): every item mined →
    *N in Anki*; any being mined → *Mining*; an unmined one that can be mined in the top → *Waiting*; some mined, the
    rest ready → *Mine rest*; none mined, ready → *Mine*; nothing left that could be mined → *No video*. And the
    on-disk mark beside it when something isn't there. `line_n` None: Connect is off — no top, so no *Waiting* (row 13:
    nothing mines by itself) and no "top" in the tips."""
    n = len(eps)
    mined = [e for e in eps if e.cards or e.mined]
    k = len(mined)
    cards = sum(e.cards for e in eps)
    # mined, then its cards deleted by the learner: never made again unless asked (Sonic, 2026-10-07), so not Waiting
    deleted = [e for e in eps if getattr(e, "deleted", False) and not (e.cards or e.mined)]
    unmined = [e for e in eps if not (e.cards or e.mined or getattr(e, "deleted", False))]
    ready = [e for e in unmined if not e.missing and not getattr(e, "waiting", False)]
    no_subs = [e for e in unmined if getattr(e, "waiting", False)]     # SRC W1b: nothing to mine until one arrives
    missing = [e for e in eps if e.missing and not e.removed and not getattr(e, "deleted", False)]   # waits on nothing
    removed = [e for e in eps if e.removed]
    top_missing = [e for e in missing if e.in_top]
    Word = word[:1].upper() + word[1:]
    n -= len(deleted)                                              # k/n counts what can still be in Anki
    if any(e.mining for e in eps):                                 # an asked-for mining outranks a deletion
        # every episode already in Anki (a level raise mines one again): *Mining…*, no episode count beside its
        # episode's card count (alpha 3 intent keeper #5)
        label = STRINGS["mining"] if n <= 1 or k == n else STRINGS["mining_kn"].format(k=k, n=n)
        st = Status("mining", label, STRINGS["tip_mining"], "accent")
    elif not unmined and deleted and not k:                        # mined, its cards gone: plain, no Anki mark
        st = Status("deleted", STRINGS["deleted"] if len(deleted) == 1 else
                    STRINGS["deleted_n"].format(n=len(deleted)), STRINGS["tip_deleted"], "faint")
    elif not unmined:                                              # every item mined (or its cards deleted)
        label = STRINGS["in_anki"].format(n=cards)      # mined = its cards are there, so cards > 0 (B-13, IK-27)
        tip = STRINGS["tip_in_anki"].format(n=cards) if n == 1 else STRINGS["tip_in_anki_k"].format(k=k, n=cards)
        st = Status("in_anki", label, tip, "ok")
    elif any(e.in_top for e in ready):
        label = STRINGS["waiting"] if not k else STRINGS["waiting_kn"].format(k=k, n=n)
        st = Status("waiting", label, STRINGS["tip_waiting"].format(line=line_n), "dim")
    elif ready and k:
        st = Status("mine_rest", STRINGS["mine_rest"].format(k=k, n=n),
                    STRINGS["tip_mine_rest" if line_n is not None else "tip_mine_rest_off"].format(k=k, n=n,
                                                                                                    line=line_n), "ok")
    elif ready:
        st = Status("mine", STRINGS["mine"], STRINGS["tip_mine" if line_n is not None else "tip_mine_off"].format(
            line=line_n), "ink")
    elif no_subs and len(no_subs) == len(unmined):                  # SRC W1b: only videos waiting for subtitles
        label = STRINGS["no_subs"] if len(no_subs) == 1 else STRINGS["no_subs_n"].format(n=len(no_subs))
        return Status("no_subs", label, STRINGS["tip_no_subs"].format(word=word), "faint"), None
    else:                                                          # nothing left that could be mined
        top = any(e.in_top for e in unmined)
        label = STRINGS["no_media"].format(word=word) if len(unmined) == 1 else \
            STRINGS["no_media_n"].format(word=word, n=len(unmined))
        tip = STRINGS["tip_no_media"].format(word=word, top=STRINGS["tip_no_media_top"].format(line=line_n)
                                             if top else "")
        st = Status("no_media", label, tip, "warn" if top else "faint")
        mark = Mark(len(removed), "faint", STRINGS["mark_removed"].format(Word=Word, eps=_eps_list(removed))) \
            if removed else None
        return st, mark
    mark = None
    if missing:
        mark = Mark(len(missing), "warn" if top_missing else "faint",
                    STRINGS["mark_missing"].format(eps=_eps_list(missing), gone=STRINGS["play_missing"]))
    elif removed:
        mark = Mark(len(removed), "faint", STRINGS["mark_removed"].format(Word=Word, eps=_eps_list(removed)))
    return st, mark


# --- building ------------------------------------------------------------------------------------------------------ #
def _episode(item, work, media, numbers, cards, mining, in_top, line_n, connect=None, show=None, show_key=None,
             playable=None):
    name = item.get("title") or (item.get("rel_path") or "").rsplit("/", 1)[-1]
    chapter = None if media == "youtube" or media in EPISODIC or media == "podcast" else chapter_part(name)
    number = None if media == "youtube" else episode_number(name)
    if chapter:
        label = chapter[1]
    elif media == "youtube":
        label = stem(name)
    elif number is None:
        label = stem(name)
    elif media in EPISODIC:
        label = STRINGS["ep"].format(n=number)
    elif media == "podcast":
        label = STRINGS["num"].format(n=number)
    else:
        label = STRINGS["part"].format(n=number)
    known, counted, n_new = numbers.get(item["id"], (0, 0, None))
    missing = item.get("availability") == "missing"
    waiting = item.get("availability") == "waiting"          # SRC W1b: a video with no subtitle yet
    c = cards.get(item["id"], 0)
    # in Anki only while its cards are there (Sonic, 2026-10-07): the receipt `mined_at` outlives a card the learner
    # deleted, so it never shows ✓, a mined chip or "the cards keep their pictures and audio" on its own
    mined = c > 0
    word = MEDIA_WORD.get(media, "video")
    verb = VERB[word]
    online = item.get("source_type") in ("youtube", "bilibili")      # its video is online: no address for it yet
    said = connect.get(item["id"]) if connect is not None else None
    # row 55 (Sonic: "if it doesn't find the media, there shouldn't be a play button"): ▶ only where ▶'s own lookup
    # (`play.Looks`, its answers `playable`) found the file — never asked where it can't be, nor where Connect says
    # *No video* of what ▶ would open as a video (the two never disagree; Connect's lookup is a video's: IK-3); with
    # no looker (`playable` None) as before. Asked and not answered yet: `looking` (R55-A)
    no_video = said is not None and said.kind == connect_feed.NO_VIDEO and word == "video"
    ask = None if missing or waiting or online or no_video else (item.get("rel_path"), media)
    looking = ask is not None and playable is not None and item["id"] not in playable
    can_play = ask is not None and (playable is None or bool(playable.get(item["id"])))
    # mining: Connect is making its cards now — an episode already in Anki that a level raise mines again too (alpha 2's
    # try, T3: its row showed only ✓, so no row said where the strip's arc was); a level job that waits keeps ✓
    ep = Episode(id=item["id"], label=label, number=number, title=stem(name), watched=bool(item.get("watched")),
                 cards=c, mining=item["id"] in mining, missing=missing, removed=missing and mined,
                 in_top=in_top, pct=pct_of(known, counted), n_new=n_new, status=None, mark=None,
                 rel_path=item.get("rel_path"), play_tip="", can_play=can_play, waiting=waiting,
                 media_word=MEDIA_WORD.get(media, "video"), work_id=item.get("work_id"), show=show, show_key=show_key,
                 ask=ask, looking=looking)
    asked = item.get("mine_asked")                    # asked again after it was mined: it mines again (Sonic's "unless asked")
    deleted = bool(item.get("mined_at")) and not mined and not (asked and str(asked) > str(item["mined_at"]))
    ep = ep._replace(deleted=deleted)
    st, mark = status_of([_Shim(ep, mined)], word, line_n)
    if connect is not None:                          # --- P4.1 L2: what Connect says of it (row 4.1.10)
        st = _connected(st, said, word)
    # MV-2: the folder its video left — Connect's line, else ▶'s own look's answer (`play.MovedAway`: a str, falsy)
    left = getattr(said, "moved", None) if no_video else None
    answer = playable.get(item["id"]) if playable is not None and not left else None
    left = left or (str(answer) if isinstance(answer, str) else None)     # a plain str: `MovedAway` is falsy
    if left and st.kind == "no_media" and not getattr(st, "moved", None):
        from app.connect.runner import MOVED
        st = st._replace(moved=left, tip=STRINGS["tip_connect_moved"].format(tip=MOVED.format(folder=left)))
    if online:
        tip = STRINGS["play_online"]
    elif waiting:
        tip = STRINGS["play_waiting"].format(word=word)
    elif missing:
        tip = (STRINGS["play_removed"] if mined else STRINGS["play_missing_plain"] if deleted else
               STRINGS["play_missing"]).format(word=word, verb_l=verb.lower())
    elif looking:
        tip = STRINGS["play_looking"].format(word=word)                          # R55-A (A-11): nothing said yet
    elif no_video and getattr(said, "moved", None):
        tip = STRINGS["play_moved"].format(tip=said.tip, word=word)              # MV-2: Connect's line, its way on
    elif left:
        from app.connect.runner import MOVED
        tip = STRINGS["play_moved"].format(tip=MOVED.format(folder=left), word=word)    # MV-2: ▶'s own look's
    elif not can_play:
        tip = STRINGS["play_not_found"].format(word=word, verb_l=verb.lower())    # row 55 (or Connect's *No video*)
    else:
        tip = STRINGS["play"].format(verb=verb, name=label, player=STRINGS["player"][word], word=word)
    return ep._replace(status=st, mark=mark, play_tip=tip, moved=left)


# --- P4.1 L2: Connect's feed in the statuses (row 4.1.10, W-A1) -------------------------------------------------- #
def _connected(st, item, word):
    """A status as Connect's feed tells it (`feed.Item`, or None: as it was). An item with its cards in Anki, or with
    no file on disk (the disk's *No video*), keeps its own; *Mining* gives way only to *Mining*. Connect's *Mining*
    counts its cards made of the words picked (*Mining · 3/12*); its *No video* (the subtitle's video not found) is
    the amber warning; *Not timed* waits on *Mine anyway* in Needs you; a job asked for that Connect has read is
    *Asked* (R47: its own status, its reason as its tip); a job waiting (on Anki, on battery, its turn) is *Waiting*
    with the job's own reason as its tip (C7). R47: a *Mining* job that can be stopped carries its job (`stop`: the
    pill's *Stop*), one stopping says *Stopping…*."""
    if item is None or st.kind in ("in_anki", "no_media") or (st.kind == "mining" and item.kind != connect_feed.MINING):
        return st
    if item.kind == connect_feed.MINING:
        # R47 (laptop rows 47 + 56): *Stop* pressed, the job not stopped yet -> *Stopping…*; while it can be stopped
        # its *Stop* (`stop`: the job); past the stop point (naming its clips) its hover says it is finishing
        if item.stopping:
            return Status("mining", STRINGS["stopping"], STRINGS["tip_stopping"], "accent")
        stop = item.job if item.stoppable else None
        if item.progress is not None:       # Anki Miner's run, as it goes (laptop round 5 #23, PROVISIONAL text: lean A)
            tip = STRINGS["tip_mining_doing"].format(doing=item.doing)
            return Status("mining", STRINGS["mining_pct"].format(pct=item.progress),
                          tip if stop is not None or item.job is None else tip + STRINGS["tip_finishing"], "accent",
                          stop)
        label = STRINGS["mining_kn"].format(k=item.made, n=item.total) if item.total else STRINGS["mining"]
        tip = STRINGS["tip_mining"]
        return Status("mining", label, tip if stop is not None or item.job is None else tip + STRINGS["tip_finishing"],
                      "accent", stop)
    if item.kind == connect_feed.ASKED:     # R47: asked, and Connect has read the ask — its own status, its reason
        return Status("asked", STRINGS["asked"], STRINGS["tip_asked"] if item.tip == item.words else item.tip, "accent")
    if item.kind == connect_feed.NO_VIDEO:
        moved = getattr(item, "moved", None)                # MV-2: its video left its folder
        return Status("no_media", STRINGS["no_media"].format(word=word),
                      STRINGS["tip_connect_moved" if moved else "tip_connect_no_media"].format(tip=item.tip), "warn",
                      moved=moved)
    if item.kind == connect_feed.NOT_TIMED:
        return Status("waiting", STRINGS["not_timed"], STRINGS["tip_not_timed"].format(words=item.words), "warn")
    if item.kind == connect_feed.SKIPPED:   # T2: refused, its entry dismissed — quiet, never a *Waiting* to mine
        return Status("waiting", STRINGS["not_timed"], STRINGS["tip_skipped"], "faint")
    # a wait on Anki or on the battery takes *Mine now* as every *Waiting* does (P4.1's C3, "an ask never overrides a
    # wait", as amended by Sonic 2026-10-22, M-3 A): on battery the press is the yes for that one episode; waiting for
    # Anki it goes first once Anki answers — its hover says which. Warn only while it waits on you (Anki closed, a
    # prompt, another profile: `ANKI`; another Needs you entry: `HELD`); a wait on Anki that clears by itself
    # (`ANKI_WAIT`: you reviewing, Anki busy) and on battery are plain ones, as on the strip (alpha 2's try, T1;
    # A3W-5, Sonic 2026-10-24 night; `runner.anki_needs_you`)
    tone = "warn" if item.kind in (connect_feed.ANKI, connect_feed.HELD) else "dim"
    tip = item.tip
    if item.kind in (connect_feed.ANKI, connect_feed.ANKI_WAIT, connect_feed.BATTERY):
        tip = STRINGS["tip_ask_battery" if item.kind == connect_feed.BATTERY else "tip_ask_anki"].format(tip=item.tip)
    return Status("waiting", st.label if st.kind == "waiting" else STRINGS["waiting"], tip, tone)


def names_click(status):
    """Does a *Waiting*'s hover already say what its click does (a wait on Anki or on the battery: `tip_ask_anki` /
    `tip_ask_battery`)? The rows' button adds no second click line then — told by its words, never its colour (alpha 3:
    a battery or reviewing wait is no longer amber)."""
    if status.kind != "waiting" or not status.tip:
        return False
    return any(status.tip.endswith(STRINGS[k].split("{tip}", 1)[1]) for k in ("tip_ask_anki", "tip_ask_battery"))


def _row_connected(st, eps, connect, word):
    """A row's status as Connect tells it: its first episode (in order) whose status Connect's feed changes — never
    one with its cards in Anki or whose cards were deleted (P4.1 WF, adversary S1: a level job on an episode already
    mined is no reason to turn the row's *Mine rest* into *Waiting*, whose *Mine now* asks for its other files)."""
    for e in eps:
        if e.cards or e.deleted:
            continue
        item = connect.get(e.id)
        if item is not None:
            new = _connected(st, item, word)
            if new is not st:
                return new
    return st
# --- end P4.1 L2


class _Shim:
    """An episode as `status_of` reads it (`mined`: its cards are in Anki — never the receipt alone)."""
    __slots__ = ("label", "cards", "mined", "missing", "removed", "in_top", "mining", "deleted", "waiting")

    def __init__(self, ep, mined):
        self.label, self.cards, self.mined, self.deleted = ep.label, ep.cards, mined, ep.deleted
        self.missing, self.removed, self.in_top, self.mining = ep.missing, ep.removed, ep.in_top, ep.mining
        self.waiting = getattr(ep, "waiting", False)


def _media(work, files, guessed):
    """A work's media type as its row reads it: typed, else the store's guess from the title's files, else (no title)
    from these files; a YouTube or bilibili first file a video's."""
    media = work.get("media_type")
    if media is None and guessed is not None and work:   # nobody typed it: the store's guess, from the title's files
        media = guessed.of(work)                         # (L3.1's rule; review IK-24)
    elif media is None:                                  # no title: from this piece's files
        counts = {}
        for it in files:
            kind = _kind(it)
            counts[kind] = counts.get(kind, 0) + 1
        media = media_type_guess(counts, work.get("anilist_id"), work.get("tmdb_id"))
    if media is None and files[0].get("source_type") in ("youtube", "bilibili"):
        media = "youtube"
    return media


def _show_key(item):
    """Which show of a group an item is of: its work, else its folder (else itself)."""
    w = item.get("work_id")
    return ("w", w) if w is not None else ("f", item.get("parent_folder") or item["id"])


def _show_name(work, item):
    name = item.get("title") or (item.get("rel_path") or "").rsplit("/", 1)[-1]
    return work.get("title") or work.get("youtube_channel") or item.get("parent_folder") or stem(name)


def _group(meta, piece, works, guessed):
    """A group's shows (LM11b G1), one reading for its row and its Goal tile -> (shows {key: files}, kinds {key: media},
    names {key: name}, title, line): its name the learner's, else "<first show> + N more"; its line *N files · K shows*
    (*N videos · K channels* when every show is a channel)."""
    shows = {}
    for it in piece:
        shows.setdefault(_show_key(it), []).append(it)
    kinds = {k: _media(works.get(fs[0].get("work_id")) or {}, fs, guessed) for k, fs in shows.items()}
    names = {k: _show_name(works.get(fs[0].get("work_id")) or {}, fs[0]) for k, fs in shows.items()}
    lead = names[_show_key(piece[0])]
    title = meta.get("title") or (STRINGS["group_name"].format(first=lead, n=len(shows) - 1) if len(shows) > 1
                                  else lead)
    line = STRINGS["group_line_channels" if all(m == "youtube" for m in kinds.values()) else "group_line"].format(
        n=len(piece), k=len(shows))
    return shows, kinds, names, title, line


def _status_word(eps):
    """A group's status word: the one media word its missing files share (what *No …* and the ⌀ mark speak of), else
    the one all its files share, else the neutral *media* — a group of a video and an EPUB never says "No video" of
    the EPUB."""
    words = {e.media_word for e in eps if e.missing} or {e.media_word for e in eps}
    return next(iter(words)) if len(words) == 1 else STRINGS["mixed_word"]


def _row(index, tier, piece, works, numbers, cards, mining, in_top_ids, line_n, finished=False, guessed=None,
         connect=None, meta=None, playable=None):
    first = piece[0]
    work = works.get(first.get("work_id")) or {}
    group = _is_group(meta, piece)                       # LM11b G1: `meta`, the feed's piece (a group's)
    if group:                                            # each show by its own files and type; the row by the first's
        shows, kinds, names, group_title, group_line = _group(meta, piece, works, guessed)
        media = kinds[_show_key(first)]
        eps = [_episode(it, works.get(it.get("work_id")) or {}, kinds[_show_key(it)], numbers, cards, mining,
                        it["id"] in in_top_ids, line_n, connect, names[_show_key(it)], _show_key(it), playable)
               for it in piece]
    else:
        media = _media(work, piece, guessed)
        eps = [_episode(it, work, media, numbers, cards, mining, it["id"] in in_top_ids, line_n, connect,
                        playable=playable) for it in piece]
    word = MEDIA_WORD.get(media, "video")
    shims = [_Shim(e, bool(e.cards)) for e in eps]
    said = _status_word(eps) if group else word      # LM11b G1: never "No video" for a group's EPUB
    st, mark = status_of(shims, said, line_n)
    if connect is not None:                          # --- P4.1 L2
        st = _row_connected(st, eps, connect, said)
    n = len(eps)
    n_watched = sum(1 for e in eps if e.watched)
    known = sum(numbers.get(it["id"], (0, 0, 0))[0] for it in piece)
    counted = sum(numbers.get(it["id"], (0, 0, 0))[1] for it in piece)
    news = [numbers[it["id"]][2] for it in piece if it["id"] in numbers and numbers[it["id"]][2] is not None]
    pct = pct_of(known, counted)
    n_new = sum(news) if news else None
    channel = work.get("title") or work.get("youtube_channel")
    single_video = media == "youtube" and n == 1 and not group
    if group:                                            # LM11b G1: its name, else "<first show> + N more"
        title, line = group_title, group_line
    elif single_video:
        title = eps[0].title
        line = channel or ""
    elif media == "youtube":
        title = channel or eps[0].title
        nxt = next((e for e in eps if not e.watched), eps[-1])
        line = STRINGS["channel_n"].format(n=n, title=nxt.title)
    else:
        title = work.get("title") or first.get("parent_folder") or eps[0].title
        nums = [e.number for e in eps if e.number is not None]
        line = range_text(media, nums, n)
    if not finished and 0 < n_watched < n and not single_video:
        line = f"{line} · " + STRINGS["watched"].format(k=n_watched, n=n)
    next_index = next((i for i, e in enumerate(eps) if not e.watched), n - 1)
    nxt = eps[next_index]
    if group:
        title_ep = STRINGS["group_ep"].format(show=names[_show_key(piece[next_index])], label=nxt.label)
    else:
        title_ep = nxt.label if (n > 1 or media in EPISODIC) and media != "youtube" else ""
    chips = ()
    more = 0
    if n > 1:
        chips = tuple(Chip(text=str(e.number) if e.number is not None else "•", watched=e.watched,
                           next=(i == next_index), mined=bool(e.cards),
                           tip=e.label + (f" · {e.cards} cards in Anki" if e.cards else ""))
                      for i, e in enumerate(eps[:CHIPS_SHOWN]))
        more = max(0, n - CHIPS_SHOWN)
    studying = bool(first.get("pinned")) and any(it.get("pinned") for it in piece)
    stamp = max((it.get("graduated_at") or "" for it in piece), default="") or None
    acc_pct = STRINGS["acc_pct_none"] if pct is None else STRINGS["pct"].format(pct=round(pct))
    acc_new = STRINGS["new"].format(n=n_new) if n_new is not None else ""          # row 36: the number or nothing
    accessible = _said(STRINGS["acc_row"].format(title=title, pct=acc_pct, new=acc_new, status=spoken(st))) \
        if not finished \
        else f"{title} · {spoken(st) if st.kind in ('in_anki', 'mining') else line}"
    key = f"p{first['piece_id']}" if first.get("piece_id") is not None else f"i{first['id']}"
    string = None
    if not finished:                                     # its string planned here, never on the window's thread (B2)
        plan = stone_plan.plan(eps, next_index, media, key, source_of(first, work) == "hato")
        string = (plan, max(stone_plan.tightest(plan), stone_plan.ahead(plan)))
    return Row(key=key, index=index, tier=tier, work_id=first.get("work_id"), piece_id=first.get("piece_id"),
               media=media, media_word=word, verb=VERB[word], title=title, title_ep=title_ep,
               line=line, source=source_of(first, work), n_files=n, n_watched=n_watched, pct=pct,
               pct_tone=pct_tone(pct), n_new=n_new, status=st, mark=mark, episodes=tuple(eps), next_index=next_index,
               studying=studying, date=day_label(stamp) if finished else "",
               cover_title=(names[_show_key(first)] if group else work.get("title") or title),
               accessible=accessible, description=line, chips=chips, more_chips=more, play_tip=nxt.play_tip,
               can_play=nxt.can_play, string=string, cover=cover_of(work), group=group,
               works=tuple(dict.fromkeys(it["work_id"] for it in piece if it.get("work_id") is not None)),
               cards_out=any(it.get("in_learning_order", 1) == 0 for it in piece))     # --- W3.2 Q4


class RowCache:
    """Rows kept between builds (the reader holds one): a piece whose items and work are the same objects as last time
    (the reader's copy replaces a row's dict only when the feed changed it) and whose cards, mining and place in the top
    are unchanged gives back last time's `Row` — the same object, so the window repaints nothing for it. A new numbers
    version clears it — or, when the numbers say which items they changed (`begin(..., changed=)`: a drop moves *N new*
    on a few rows), only the rows holding one of them."""

    def __init__(self):
        self.rows = {}
        self.version = None
        self.hits = self.misses = 0
        self.same_global = False                      # set by `begin`: nothing global moved since the last build
        self._glob = self._cards = None
        self._connect = None                          # P4.1 L2: the Connect feed's items the last build read
        self._next = {}
        self.guess_seen, self.guess_counts = {}, {}   # `_Guesses`: each row counted once, kept while it is the same object
        # the ids changed since the counts were last brought up to date, kept until a build counts (a build with no
        # untyped title on the list never does: review 2026-10-08, the Haiku pass, four lenses); None: unknown, all
        self.guess_pending = None
        self.sections = {}                            # "goal" / "finished": what `build` made of them last (`_kept`)
        self.worst = None                             # the last build's `worst_needs` (kept while equal: one object)

    def note_changed(self, changed):
        """The item ids the feed changed or let go since the last build (None: unknown — every item looked at)."""
        if changed is None or self.guess_pending is None:
            self.guess_pending = None                # a full count is owed: it stays owed until a build counts
        else:
            self.guess_pending |= set(changed)

    def begin(self, version, cards=None, mining=None, in_top=None, line_n=None, changed=None, connect=None):
        """`changed`: the item ids the numbers changed since the cache's version (None: unknown — every row again)."""
        if version != self.version:
            changed = None if changed is None else set(changed)
            self.rows = {} if changed is None else \
                {k: v for k, v in self.rows.items() if changed.isdisjoint(it["id"] for it in v[2])}
            self.version = version
        glob = (id(cards), frozenset(mining or ()), frozenset(in_top or ()), line_n)
        self.same_global = glob == self._glob and cards is self._cards and connect is self._connect   # P4.1 L2
        self._glob, self._cards, self._connect = glob, cards, connect
        self._next = {}

    def end(self):
        self.rows = self._next


def _is_group(meta, piece):
    """Whether `piece` reads as a group (LM11b G1): its feed piece is of kind 'group' and holds two shows or more. LM11b
    G5: one holding a single show is that show's run, as the store makes it (`_settle_kinds`) — read so while the
    reader builds in a write the store hasn't made yet (`LibraryReader.expect`). One rule for its row, its Goal tile and
    the Soon line (H-B4)."""
    if meta is None or meta.get("kind") != "group":
        return False
    first = _show_key(piece[0])
    return any(_show_key(it) != first for it in piece)


def _group_meta(metas, piece):
    """The feed's piece (`build(pieces=)`) of a piece of kind 'group', else None — its kind alone (a group the Soon line
    cuts between its shows holds one show each side; Goal reads a group's runs together)."""
    meta = metas.get(piece[0].get("piece_id")) if metas else None
    return meta if meta is not None and meta.get("kind") == "group" else None


def _group_of(metas, piece):
    """The feed's piece of a piece that reads as a group (`_is_group`), else None (LM11b G1)."""
    meta = _group_meta(metas, piece)
    return meta if _is_group(meta, piece) else None


_Sig = namedtuple("_Sig", "n line_n hero cards mining in_top guess connect play")
#   a cached row's signature (`_cached_row`), read by name: read by place, the fast path once took Connect's part
#   (the last, added in P4.1 L2) for the type guess and kept a row whose guess had moved. `play` (row 55): its items'
#   ▶ answers — checked on the fast path too, so new answers rebuild only the rows whose answer moved


def _same(a, b):
    """A row's makings beside its items — its work, or a group's (meta, works…) — the same objects as last time."""
    return a is b or (type(a) is tuple and type(b) is tuple and len(a) == len(b) and all(x is y for x, y in zip(a, b)))


def _guess(guessed, work):
    return guessed.of(work) if guessed is not None and work and work.get("media_type") is None else None


def _cached_row(cache, index, tier, piece, works, numbers, cards, mining, in_top, line_n, finished, guessed, hero,
                connect=None, soon_from=None, soon_piece=None, meta=None, playable=None):
    """`meta`: a group's piece from the feed (LM11b G1), else None. `playable`: ▶'s answers (row 55), else None."""
    if cache is None:
        row = _row(index, tier, piece, works, numbers, cards, mining, in_top, line_n, finished, guessed, connect, meta,
                   playable)
        row = _as_hero(row) if hero else row
        return row._replace(soon_from=soon_from, soon_piece=soon_piece) if soon_from is not None else row  # P-LF-16
    first = piece[0]
    work = works.get(first.get("work_id"))
    if meta is None:
        made = work
        # a title nobody typed: its guess is read from all its files, so another piece's new file can move it (reviews
        # 2026-10-08, the Haiku pass: a cached row kept the old type)
        guess = _guess(guessed, work)
    else:                                            # LM11b G1: a group is its piece's meta and every show's work
        group_works = tuple(works.get(w) for w in dict.fromkeys(it.get("work_id") for it in piece))
        made = (meta,) + group_works
        guess = tuple(_guess(guessed, w) for w in group_works)
    key = (tier, finished, first.get("piece_id"), first["id"])
    hit = cache.rows.get(key)
    same_items = hit is not None and _same(hit[1], made) and len(hit[2]) == len(piece) and \
        all(a is b for a, b in zip(hit[2], piece))
    # row 55: as shown — found, not found, and not answered yet (R55-A: Up Next's *Looking…*, its tip) each its own
    play = None if playable is None else tuple(playable.get(it["id"]) for it in piece)
    if same_items and cache.same_global and hit[0].hero == hero and hit[0].guess == guess and hit[0].play == play:
        sig = hit[0]                                 # nothing global moved: the same objects are the same row
    else:
        sig = _Sig(len(piece), line_n, hero, tuple(cards.get(it["id"], 0) for it in piece),
                   tuple(it["id"] in mining for it in piece), tuple(it["id"] in in_top for it in piece), guess,
                   None if connect is None else tuple(connect.get(it["id"]) for it in piece),     # --- P4.1 L2
                   play)
    if same_items and hit[0] == sig and (hit[3].soon_from, hit[3].soon_piece) == (soon_from, soon_piece):  # same cut
        row = hit[3]
        if row.index != index:
            row = row._replace(index=index)
        cache.hits += 1
    else:
        row = _row(index, tier, piece, works, numbers, cards, mining, in_top, line_n, finished, guessed, connect, meta,
                   playable)
        if hero:
            row = _as_hero(row)
        if soon_from is not None:                    # P-LF-16
            row = row._replace(soon_from=soon_from, soon_piece=soon_piece)
        cache.misses += 1
    cache._next[key] = (sig, made, tuple(piece), row)
    return row


def _as_hero(h):
    """The hero reads as it's painted: its next episode's numbers with the episode, and its row's own status (Q33: as
    every row) said as the whole's — "all of it", never in one breath with the episode's (AD-9)."""
    nxt = h.episodes[h.next_index]
    return h._replace(accessible=_said(STRINGS["acc_hero"].format(
        title=h.title, ep=h.title_ep, status=spoken(h.status),
        pct=STRINGS["acc_pct_none"] if nxt.pct is None else STRINGS["pct"].format(pct=round(nxt.pct)),
        new="" if nxt.n_new is None else STRINGS["new"].format(n=nxt.n_new))).replace("  ", " "))


def _by_tier(items):
    """Each tier's items in `(ord, id)` order — one pass, one sort per tier."""
    out = {t: [] for t in ("arrivals", "now", "soon", "goal", "graduated")}
    for r in items.values():
        out.setdefault(r.get("tier"), []).append(r)
    for rows in out.values():
        rows.sort(key=lambda r: (r.get("ord") or 0.0, r["id"]))
    return out


def _current_items(items):
    return ordered_tier(items, "now") + ordered_tier(items, "soon")


def _kind(item):
    """A file's source type as the store counts it for a guess (`library_store.media_type`): its stamped type, else
    its extension (`infer_source_type`; an unstamped .epub or .txt is text, an .srt a subtitle — review IK-29)."""
    return infer_source_type(item.get("rel_path") or "", declared=item.get("source_type"))


class _Guesses:
    """A title's media type when nobody said (`media_type_guess` over **all** its files, as L3.1's store guesses it):
    the files counted by title, once a build, when a title nobody typed is on the list. A cached row keeps the guess in
    its key, so another piece's new file that moves the title's type rebuilds it. With the reader's RowCache the counts
    are kept between builds and only the rows the feed replaced are counted again (review C-6: ~5 ms a build at 20,000
    files, holding Python's lock against the window's thread)."""

    def __init__(self, items, cache=None):
        self.items = items
        self.cache = cache
        self.counts = None

    def of(self, work):
        if self.counts is None:
            self.counts = self._count()
        return media_type_guess(self.counts.get(work.get("id")), work.get("anilist_id"), work.get("tmdb_id"))

    def _count(self):
        seen, counts = ({}, {}) if self.cache is None else (self.cache.guess_seen, self.cache.guess_counts)

        def add(entry, n):
            c = counts.setdefault(entry[1], {})
            c[entry[2]] = c.get(entry[2], 0) + n
            if c[entry[2]] <= 0:
                del c[entry[2]]
                if not c:
                    del counts[entry[1]]
        pending = None if self.cache is None else self.cache.guess_pending
        if self.cache is not None:
            self.cache.guess_pending = set()             # brought up to date below: from here on, only what changes
        if pending is not None and seen:
            # the reader said which ids changed (speed round 5: a walk of all 20,000 items on every build, on the
            # reader's thread, holding Python's lock against the window's); the rest are the same objects
            for i in pending:
                r, old = self.items.get(i), seen.get(i)
                if old is not None and old[0] is r:
                    continue
                if old is not None:
                    add(seen.pop(i), -1)
                if r is not None:
                    seen[i] = entry = (r, r.get("work_id"), _kind(r))
                    add(entry, 1)
            return counts
        for i, r in self.items.items():
            old = seen.get(i)
            if old is not None and old[0] is r:          # the same row object: the feed didn't change it
                continue
            if old is not None:
                add(old, -1)
            seen[i] = entry = (r, r.get("work_id"), _kind(r))
            add(entry, 1)
        if len(seen) > len(self.items):                  # rows gone from the feed
            for i in [i for i in seen if i not in self.items]:
                add(seen.pop(i), -1)
        return counts


def stat_kind(status):
    """What a row shows at rest right of its string, as far as its width goes: its Anki count ("in_anki", the label),
    mining's icon ("mining"), or nothing (None)."""
    if status is None:
        return None
    if status.kind == "in_anki":
        return ("in_anki", status.label)
    return "mining" if status.kind == "mining" else None


def worst_needs(rows):
    """For the one title width every Current row shares (W3.1a B2): over `rows` (Current's below Up Next, as the window
    reads them), the string that needs the most room for each kind of Anki count shown beside it — {kind: (need, plan)},
    kind None (no count), "mining" or ("in_anki", its label). The window adds each kind's own width (its font's) and
    takes the largest: a few numbers, never a walk over every row on its thread."""
    out = {}
    for row in rows:
        if row.string is None:
            continue
        kind = stat_kind(row.status)
        plan, need = row.string
        hit = out.get(kind)
        if hit is None or need > hit[0]:
            out[kind] = (need, plan)
    return out


def keep_watched(options):
    """W-1: the library's *Keep studying watched episodes* in the feed's `options` (absent: off)."""
    try:
        return bool(int((options or {}).get("keep_watched") or 0))
    except (TypeError, ValueError):
        return False


def mark_moves_list(tier, ep, keep):
    """W-1: does marking `ep` (an episode of a row in `tier`) watched, or not, move what the list counts? The store's
    one rule (`library_store.counts`, `keep` the library's `keep_watched`); a video waiting for its subtitle is in no
    list, watched or not (`Store.schedule`). What the stone's tip, the mark's toast and its one-time hint say."""
    from app.library_store import counts
    return not getattr(ep, "waiting", False) and counts(tier, False, keep) != counts(tier, True, keep)


def _mine_ids(current, n, keep=False):
    """The store's `_mine_ids`: the top `n` available files of Current, in order (a video waiting for its subtitle is
    never one: SRC W1b) that count by the store's one rule (`library_store.counts`, W-1: a watched one while `keep`,
    the library's `keep_watched`, is off has nothing left to mine)."""
    from app.library_store import counts
    out = []
    for r in current:
        if len(out) >= n:
            break
        if r.get("availability") not in ("missing", "waiting") and counts(r.get("tier"), r.get("watched"), keep):
            out.append(r["id"])
    return out


def _kept(cache, name, tier_rows, changed, changed_works, more=()):
    """What the last build made of a tier shown whole (Goal, Finished), when nothing in it can have changed: the
    reader's tier list is the same object (it makes a new one when an item moves in or out), none of its items is
    among the ids the feed changed, none of its works among the works it changed, and `more` (anything else it shows)
    is equal. Else None: built again (S19; review IK-36 — at 20,000 files they were walked on every build)."""
    if cache is None or changed is None or changed_works is None:
        return None
    hit = cache.sections.get(name)
    if hit is None or hit[0] is not tier_rows or hit[3] != more:
        return None
    if not hit[1].isdisjoint(changed) or not hit[2].isdisjoint(changed_works):
        return None
    return hit[4]


def _keep(cache, name, tier_rows, work_ids, more, made):
    if cache is not None:
        cache.sections[name] = (tier_rows, frozenset(r["id"] for r in tier_rows), frozenset(work_ids), more, made)


# --- New arrivals (W3.2 S1) --------------------------------------------------------------------------------------- #
def _arrival_unit(media):
    return "videos" if media == "youtube" else "eps" if media in EPISODIC or media == "podcast" else "parts"


def per_episode(item_ids, estimates):
    """*N new / ep*: the estimates' *N new* (each file asked with the earlier ones placed, IK-5) summed over the files
    and divided by them, rounded — None while any file has none (a dash until every answer is in)."""
    if not item_ids or estimates is None:
        return None
    vals = [estimates.get(i) for i in item_ids]
    if any(v is None for v in vals):
        return None
    return int(sum(vals) / len(vals) + 0.5)


def _arrival(piece, works, cards, estimates, guessed):
    """One tray row from one piece of the arrivals tier: titled as Current's rows are (`_row`), its source from hato's
    folder, its files' type and the work's AniList id (the feed carries no pairing: see `source_of`), else the disk."""
    row = _row(0, "arrivals", piece, works, {}, cards, set(), set(), 20, finished=True, guessed=guessed)
    first = piece[0]
    work = works.get(first.get("work_id")) or {}
    media, eps = row.media, row.episodes
    n = len(eps)
    source = row.source or "disk"
    channel = (work.get("title") or work.get("youtube_channel")) if media == "youtube" else None
    if media == "youtube" and n == 1:
        line = channel or ""
    else:
        line = range_text(media, [e.number for e in eps if e.number is not None], n)
    ids = tuple(it["id"] for it in piece)
    n_cards = sum(cards.get(i, 0) for i in ids)
    no_media = sum(1 for e in eps if e.missing)
    parts = ((line, "dim"),) if line else ()
    if n_cards:
        parts += ((STRINGS["arr_cards"].format(n=n_cards), "ok"),)
    if no_media:
        parts += ((STRINGS["arr_no_media_one" if no_media == 1 else "arr_no_media"].format(n=no_media), "warn"),)
    waiting = sum(1 for e in eps if e.waiting)                      # SRC W1b: K5's videos with no subtitle yet
    if waiting:
        parts += ((STRINGS["arr_no_subs"], "dim"),)
    watched = all(e.watched for e in eps)
    unit = _arrival_unit(media)
    one, many = STRINGS["arr_units"][unit]
    per_ep = per_episode(ids, estimates)
    if per_ep is None:
        tip = STRINGS["per_ep_tip_none"].format(files=n, units=one if n == 1 else many)
        number = STRINGS["acc_per_ep_none"]
    else:
        tip = STRINGS["per_ep_tip"].format(n=per_ep, each=STRINGS["arr_each"][unit], files=n,
                                           units=one if n == 1 else many)
        number = STRINGS["per_ep"].format(n=per_ep, unit=STRINGS["per_unit"][unit])
    return Arrival(key=row.key, work_id=row.work_id, piece_id=row.piece_id, item_ids=ids,
                   rel_paths=tuple(it.get("rel_path") for it in piece), title=row.title, media=media,
                   media_word=row.media_word, source=source, chip=STRINGS["chip"][source], channel=channel, line=line,
                   cards=n_cards, no_media=no_media, parts=parts, n_files=n, watched=watched,
                   group="watched" if watched else "new",
                   added_at=max((it.get("added_at") or "" for it in piece), default="") or None,
                   cover_title=row.cover_title, per_ep=per_ep, tip=tip, cover=row.cover, waiting=waiting,  # Q6, W1b
                   episodes=eps,                                                            # P4.1 WF
                   accessible=STRINGS["acc_arrival"].format(title=row.title, line=" · ".join(t for t, _ in parts),
                                                            number=number).replace(" ·  · ", " · "))


def _arrivals(cache, tier_rows, works, cards, estimates, guessed, changed, changed_works):
    """The tray's rows and groups (RUNBOOK §1 *The tray*): one per piece, newest first by `added_at` (a piece by its
    newest file; equal stamps keep the store's order), *New* then *Already watched*. With the reader's cache an
    unchanged tier gives back last build's objects (`_kept`), and a piece whose items, work, cards, estimates and guess
    are the same gives back its row — the window repaints only the rows that moved (S19)."""
    ps = pieces(tier_rows)
    estimates = estimates or {}

    def sig(p):
        work = works.get(p[0].get("work_id"))
        guess = guessed.of(work) if work and work.get("media_type") is None else None
        return (tuple(cards.get(it["id"], 0) for it in p), tuple(estimates.get(it["id"]) for it in p), guess)
    sigs = tuple(sig(p) for p in ps)
    kept = _kept(cache, "arrivals", tier_rows, changed, changed_works, sigs)
    if kept is not None:
        return kept[0], kept[1]
    hit = cache.sections.get("arrivals") if cache is not None else None
    before = hit[4][2] if hit is not None else {}
    entries, made = {}, []
    for p, s in zip(ps, sigs):
        first = p[0]
        work = works.get(first.get("work_id"))
        key = f"p{first['piece_id']}" if first.get("piece_id") is not None else f"i{first['id']}"
        old = before.get(key)
        if old is not None and old[1] is work and old[2] == s and len(old[0]) == len(p) and \
                all(a is b for a, b in zip(old[0], p)):
            row = old[3]
        else:
            row = _arrival(p, works, cards, estimates, guessed)
        entries[key] = (tuple(p), work, s, row)
        made.append(row)
    made.sort(key=lambda a: a.added_at or "", reverse=True)          # stable: equal stamps keep the store's order
    rows = tuple(a for a in made if a.group == "new") + tuple(a for a in made if a.group == "watched")
    if hit is not None and len(hit[4][0]) == len(rows) and all(a is b for a, b in zip(hit[4][0], rows)):
        rows, groups = hit[4][0], hit[4][1]                         # nothing moved: the same objects
    else:
        groups = tuple(ArrivalGroup(kind, STRINGS[label], tuple(a for a in rows if a.group == kind))
                       for kind, label in (("new", "arr_new"), ("watched", "arr_watched"))
                       if any(a.group == kind for a in rows))
    _keep(cache, "arrivals", tier_rows, {r.get("work_id") for r in tier_rows}, sigs, (rows, groups, entries))
    return rows, groups


# --- W3.2 Q2: Goal's sheet ----------------------------------------------------------------------------------------- #
def _goal_group(key, ps, works, guessed, meta):
    """A group in Goal (LM11b G1, IK-7): a tile of its own, named and counted as its row is (`_group`), its cover its
    first episode's show's — never folded into that show's tile. `ps`: every run of the group, in Goal's order (another
    title may stand between them, H-B3) — its files one piece: one GoalPiece, brought up whole."""
    piece = [it for p in ps for it in p]
    first = piece[0]
    work = works.get(first.get("work_id")) or {}
    shows, kinds, names, title, line = _group(meta, piece, works, guessed)
    ids = tuple(it["id"] for it in piece)
    return GoalWork(key=key, work_id=first.get("work_id"), title=title, cover_title=names[_show_key(first)],
                    media=kinds[_show_key(first)], source=source_of(first, work) or "disk", n_files=len(piece),
                    line=line, pieces=(GoalPiece(item_ids=ids, line=line, piece_id=first.get("piece_id")),), item_ids=ids,
                    folder=(first.get("rel_path") or "").rpartition("/")[0],
                    tip=STRINGS["goal_tile_tip"].format(title=title, line=line, first=title),
                    accessible=STRINGS["acc_goal_tile"].format(title=title, line=line), cover=cover_of(work),
                    group=True)


def _goal_work(key, ps, works, guessed):
    """One tile: a title's pieces in Goal (in Goal's order), titled as Current's rows are, *N episodes / videos /
    parts* over all its files, each piece's range (*Ep 1–12*)."""
    first = ps[0][0]
    work = works.get(first.get("work_id")) or {}
    media = work.get("media_type")
    if media is None and work and guessed is not None:
        media = guessed.of(work)
    if media is None and first.get("source_type") in ("youtube", "bilibili"):
        media = "youtube"
    files = [it for p in ps for it in p]
    name = first.get("title") or (first.get("rel_path") or "").rsplit("/", 1)[-1]
    title = (work.get("title") or work.get("youtube_channel")) if media == "youtube" else None
    title = title or work.get("title") or first.get("parent_folder") or stem(name)
    unit = _arrival_unit(media)
    one, many = STRINGS["arr_units"][unit]
    line = STRINGS["goal_count"].format(n=thousands(len(files)), units=one if len(files) == 1 else many)
    pieces_ = []
    for p in ps:
        nums = [] if media == "youtube" else \
            [episode_number(it.get("title") or (it.get("rel_path") or "").rsplit("/", 1)[-1]) for it in p]
        nums = [n for n in nums if n is not None]
        pieces_.append(GoalPiece(item_ids=tuple(it["id"] for it in p), line=range_text(media, nums, len(p)),
                                 piece_id=p[0].get("piece_id")))
    return GoalWork(key=key, work_id=first.get("work_id"), title=title, cover_title=work.get("title") or title,
                    media=media, source=source_of(first, work) or "disk", n_files=len(files), line=line,
                    pieces=tuple(pieces_), item_ids=tuple(it["id"] for it in files),
                    folder=(first.get("rel_path") or "").rpartition("/")[0],
                    tip=STRINGS["goal_tile_tip"].format(title=title, line=line, first=pieces_[0].line),
                    accessible=STRINGS["acc_goal_tile"].format(title=title, line=line),
                    cover=cover_of(work))           # --- W3.2 L3


def goal_tiles(goal_items, works, guessed=None, before=None, metas=None):
    """Goal's tiles (`Goal.works`), in Goal's order: its pieces grouped by title (a piece with no title: by itself; a
    group, LM11b G1: by itself, `metas` the feed's pieces). `before`: the last build's {key: (items, work, guess,
    tile)} — a title whose items and work are the same objects and whose guess is equal gives back its tile (S19).
    -> (tiles, entries)."""
    groups, order, group_meta = {}, [], {}
    for p in pieces(goal_items):
        first = p[0]
        meta = _group_meta(metas, p)                 # its runs read together below (`_is_group`, H-B3 / H-B4)
        key = f"p{first['piece_id']}" if meta is not None else \
            f"w{first['work_id']}" if first.get("work_id") is not None else \
            f"p{first['piece_id']}" if first.get("piece_id") is not None else f"i{first['id']}"
        if meta is not None:
            group_meta[key] = meta
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)
    before = before or {}
    entries, tiles = {}, []
    for key in order:
        ps = groups[key]
        items = tuple(it for p in ps for it in p)
        meta = group_meta.get(key)
        if meta is not None and not _is_group(meta, items):
            meta = None                              # one show (H-B4): that show's run tile, as its row reads
        if meta is None:
            work = works.get(ps[0][0].get("work_id"))
            guess = guessed.of(work) if guessed is not None and work and work.get("media_type") is None else None
        else:                                        # a group: its meta and every show's work, as its row (G1)
            group_works = tuple(works.get(w) for w in dict.fromkeys(it.get("work_id") for it in items))
            work, guess = (meta,) + group_works, tuple(_guess(guessed, w) for w in group_works)
        old = before.get(key)
        if old is not None and _same(old[1], work) and old[2] == guess and len(old[0]) == len(items) and \
                all(a is b for a, b in zip(old[0], items)):
            tile = old[3]
        else:
            tile = _goal_work(key, ps, works, guessed) if meta is None else _goal_group(key, ps, works, guessed, meta)
        entries[key] = (items, work, guess, tile)
        tiles.append(tile)
    return tuple(tiles), entries
# --- end W3.2 Q2


def build(items, works, options, numbers=None, cards=None, mining=(), language="ja", mode="store", reason=None,
          loading=False, busy=False, cache=None, tiers=None, changed=None, changed_works=None, numbers_changed=None,
          estimates=None, connect=None, pieces=None, playable=None):
    """The window's view of the library (see the module's doc). `items` / `works`: {id: feed row}; `options`: the
    feed's {soon_line, mine_line, arrivals_on}; `numbers`: (version, {item_id: (known, counted, n_new)}) or the dict;
    `cards`: {item_id: count}; `mining`: item ids being mined now; `changed`: with `cache`, the item ids changed or gone
    since the cache's last build (None: unknown, every item looked at); `changed_works`: the same for works;
    `numbers_changed`: with `cache`, the item ids whose numbers changed since the version it last built with (None:
    unknown — on a new version every row is built again); `estimates`: {item_id: *N new* at the top} for New arrivals'
    files, as the arrivals worker answers (W3.2 S1: a missing one leaves its row's number None); `connect`: Connect's
    feed (`app/connect/feed.Feed`, P4.1 L2 row 4.1.10) — its items' statuses on the rows and episodes (`_connected`)
    and its mining set beside `mining`; None: as without Connect; a Feed that is off (or not looked yet: `feed.NOT_LOOKED`)
    — no Connect statuses, and no top line or *Waiting* (row 13: nothing mines by itself); `pieces`: the feed's
    {piece_id: {id, title, kind}} (LM11b G1) — a Current piece of kind 'group' is a group's row (`_row`); `playable`:
    ▶'s answers ({item_id: found}, `play.Looks`, row 55) — Current's ▶ only where found; None: no looker, as before."""
    numbers_version = None
    if isinstance(numbers, tuple):
        numbers_version, numbers = numbers
    numbers = numbers or {}
    cache_version = numbers_version if numbers_version is not None else id(numbers)
    cards = cards or {}
    mining = set(mining or ())
    # --- P4.1 L2: Connect's feed (row 4.1.10): its items by id; off or none → None (no Connect statuses on the rows;
    # an off Feed also takes the top line and *Waiting* away: row 13, below)
    feed_items = connect.items if connect is not None and connect.on else None
    if feed_items is not None:
        mining |= set(connect.mining)
    # row 13 (laptop fixes): a Feed that is off (Connect's switch, D29's automation, or no look yet: B2-8) — nothing
    # mines by itself, so no top line and no *Waiting* on the rows (no Feed at all, as before: the line and statuses)
    off = connect is not None and not connect.on
    # --- end P4.1 L2
    options = options or {}
    line_n = options.get("mine_line")
    line_n = 20 if line_n is None else int(line_n)
    tiers = tiers if tiers is not None else _by_tier(items)
    current = tiers["now"] + tiers["soon"]
    keep = keep_watched(options)                                  # W-1
    top_ids = [] if off else _mine_ids(current, line_n, keep)    # row 13: Connect off → nothing "in the top"
    # every item above the line's place (missing ones included) is "in the top": the line falls after the n-th available
    in_top = set()
    if top_ids:
        last = top_ids[-1]
        for r in current:
            in_top.add(r["id"])
            if r["id"] == last:
                break
    if cache is not None:
        cache.begin(cache_version, cards, mining, in_top, line_n, numbers_changed, feed_items)
    if cache is not None:
        cache.note_changed(changed)
    guessed = _Guesses(items, cache)
    rows = []
    now_pieces, soon_pieces = _pieces(tiers["now"]), _pieces(tiers["soon"])
    soon_from = soon_piece = None
    # LM11b G1: a group the line runs through is one piece in both tiers (Kura's LM11: one row, its key once) — at a
    # show inside it too; a group never takes a run or another group beside it, nor a run a group (the store's
    # `_fix_pieces`): the Soon line stays between them
    straddle = False
    if now_pieces and soon_pieces:
        a, b = now_pieces[-1], soon_pieces[0]
        if _group_meta(pieces, a) is not None or _group_meta(pieces, b) is not None:
            straddle = a[0].get("piece_id") == b[0].get("piece_id")
        else:
            straddle = _same_show(a[-1], b[0])
    if straddle:
        # P-LF-16: the Soon line falls inside this show — one row above the line, the line after it (tiers unchanged)
        soon_from, soon_piece = len(now_pieces[-1]), soon_pieces[0][0].get("piece_id")
        now_pieces[-1] = now_pieces[-1] + soon_pieces.pop(0)
    for tier, tier_pieces in (("now", now_pieces), ("soon", soon_pieces)):
        for n, piece in enumerate(tier_pieces):
            cut = soon_from if tier == "now" and n == len(tier_pieces) - 1 else None
            rows.append(_cached_row(cache, len(rows) + 1, tier, piece, works, numbers, cards, mining, in_top,
                                    None if off else line_n, False, guessed, hero=not rows, connect=feed_items,
                                    soon_from=cut, soon_piece=soon_piece if cut is not None else None,
                                    meta=_group_of(pieces, piece), playable=playable))
    worst = worst_needs(rows[1:])
    if cache is not None:
        if worst == cache.worst:
            worst = cache.worst                         # the same object while equal: the window works nothing out
        cache.worst = worst
    lines = []
    if len(top_ids) >= line_n and line_n > 0:
        last = top_ids[-1]
        at = next(i for i, row in enumerate(rows) if any(e.id == last for e in row.episodes))
        row = rows[at]
        k = next(j for j, e in enumerate(row.episodes) if e.id == last) + 1
        if k < len(row.episodes):                       # the line runs through this row: only its first k mine
            tip = STRINGS["top_tip_split"].format(n=line_n, title=row.title, k=k, m=len(row.episodes))
            lines.append(Line("top", at, tip, k))
        else:
            lines.append(Line("top", at, STRINGS["top_tip"].format(n=line_n), None))
    soon_at = soon_line_after(rows)
    if soon_at is not None:
        k = options.get("soon_line")
        tip = STRINGS["soon_tip"].format(n=k) if k else STRINGS["soon_tip_nocount"]
        lines.append(Line("soon", soon_at, tip, None))
    # Goal: titles are works, files all their items
    goal_items = tiers["goal"]
    # --- W3.2 Q2: the tiles read every Goal title (not only the strip's nine) and an untyped title's guess
    g_hit = cache.sections.get("goal") if cache is not None else None
    g_more = tuple((w, guessed.of(works[w])) for w in g_hit[4][2]) if g_hit is not None and \
        all(w in works for w in g_hit[4][2]) else (object(),) if g_hit is not None else ()
    # --- end W3.2 Q2
    kept = _kept(cache, "goal", goal_items, changed, changed_works, g_more)
    if kept is not None:
        goal, n_goal_works = kept[0], kept[1]
    else:
        goal_works = list(dict.fromkeys(r.get("work_id") for r in goal_items))   # in order, one pass (a list's `in`
        # was quadratic: ~90 ms a build at 20,000 files, bench 7)
        # --- W3.2 Q2: the tiles (a title unchanged gives back its tile), every title watched, an untyped one's guess
        tiles, g_entries = goal_tiles(goal_items, works, guessed, g_hit[4][3] if g_hit is not None else None,
                                      pieces)                                        # LM11b G1: a group's tile
        heads = [t.work_id for t in tiles]          # a title is a tile, by its key (H-B2: an untitled piece its own,
        #                                             a group one): its first file's work for the strip's covers
        covers = tuple((works.get(w) or {}).get("title") or "" for w in heads[:9])
        if goal_items:
            g_line = STRINGS["goal_one"].format(files=thousands(len(goal_items))) if len(heads) == 1 else \
                STRINGS["goal_line"].format(titles=len(heads), files=thousands(len(goal_items)))
        else:
            g_line = STRINGS["goal_empty"]
        old_goal = g_hit[4][0] if g_hit is not None else None
        if old_goal is not None and len(old_goal.works) == len(tiles) and \
                all(a is b for a, b in zip(old_goal.works, tiles)):
            tiles = old_goal.works                       # every tile the same: the same tuple
        goal = Goal(titles=len(heads), files=len(goal_items), covers=covers, line=g_line, tip=STRINGS["goal_tip"],
                    works=tiles,
                    cover_refs=tuple(cover_of(works.get(w)) for w in heads[:9]))             # W3.2 Q6
        n_goal_works = len(heads)
        g_untyped = tuple(w for w in goal_works if w in works and works[w].get("media_type") is None)
        _keep(cache, "goal", goal_items, goal_works, tuple((w, guessed.of(works[w])) for w in g_untyped),
              (goal, n_goal_works, g_untyped, g_entries))
        # --- end W3.2 Q2
    # Finished: newest first, by month; no date last (*Earlier*). Its rows read the cards, the mining set, the line and
    # the numbers (`same_global`, the cache's version) and an untyped title's guess (from all its files, any tier)
    fin_items = tiers["graduated"]
    hit = cache.sections.get("finished") if cache is not None else None
    guesses = tuple((w, guessed.of(works[w])) for w in hit[4][2]) if hit is not None and guessed is not None and \
        all(w in works for w in hit[4][2]) else None
    kept = _kept(cache, "finished", fin_items, changed, changed_works,
                 (cache.version, guesses) if cache is not None and cache.same_global else (object(),))
    if kept is not None:
        finished, n_fin, _untyped, rows_kept = kept
        cache._next.update(rows_kept)                # its rows stay in the row cache for the next time it's built
    else:
        fin_pieces = _pieces(fin_items)
        before = set(cache._next) if cache is not None else None
        fin_rows = [_cached_row(cache, 0, "graduated", p, works, numbers, cards, mining, (), line_n, True, guessed,
                                False, feed_items) for p in fin_pieces]
        stamp_of = {}
        for p in fin_pieces:
            key = f"p{p[0]['piece_id']}" if p[0].get("piece_id") is not None else f"i{p[0]['id']}"
            stamp_of[key] = max((it.get("graduated_at") or "" for it in p), default="")
        fin_rows.sort(key=lambda r: stamp_of.get(r.key, ""), reverse=True)
        months, by_label = [], {}
        for r in fin_rows:
            label = month_label(stamp_of.get(r.key))
            if label not in by_label:
                by_label[label] = []
                months.append(label)
            by_label[label].append(r)
        if STRINGS["earlier"] in months:                 # *Earlier* always last
            months.remove(STRINGS["earlier"])
            months.append(STRINGS["earlier"])
        finished = tuple(Month(m, tuple(by_label[m])) for m in months)
        n_fin = len(fin_rows)
        if cache is not None:
            fin_works = {r.get("work_id") for r in fin_items}
            untyped = tuple(w for w in fin_works if w in works and works[w].get("media_type") is None)
            rows_kept = {k: v for k, v in cache._next.items() if k not in before}
            more = (cache.version, tuple((w, guessed.of(works[w])) for w in untyped)) if cache.same_global \
                else (object(),)
            _keep(cache, "finished", fin_items, fin_works, more, (finished, n_fin, untyped, rows_kept))
    # Needs you: each show whose unmined files in the top wait on a missing file
    needs = []
    by_work, order = {}, []
    for row in rows:
        waiting = [e for e in row.episodes if e.missing and not e.removed and e.in_top and not e.deleted]
        if not waiting:
            continue
        key = row.work_id if row.work_id is not None else row.key
        if key not in by_work:
            by_work[key] = (row, [])
            order.append(key)
        by_work[key][1].extend(waiting)
    for key in order:
        row, waiting = by_work[key]
        word = MEDIA_WORD.get(row.media, "video")
        unit = STRINGS["unit_eps"] if row.media in EPISODIC else STRINGS["unit_files"] \
            if row.media == "youtube" else STRINGS["unit_parts"]
        if len(waiting) == 1:
            title = STRINGS["need_title_one"].format(title=row.title, ep=waiting[0].label, word=word)
            line = STRINGS["need_line_one"].format(line=line_n, word=word)
        else:
            title = STRINGS["need_title_n"].format(title=row.title, n=len(waiting), unit=unit, word=word)
            line = STRINGS["need_line_n"].format(line=line_n, word=word)
        needs.append(Need(key=row.key, work_id=row.work_id, title=title, line=line,
                          episodes=tuple((e.label, STRINGS["need_ep"].format(word=word)) for e in waiting),
                          cover_title=row.cover_title, cover=row.cover))                   # W3.2 Q6
    arrivals = tiers["arrivals"]
    arrival_rows, arrival_groups = _arrivals(cache, arrivals, works, cards, estimates, guessed, changed, changed_works)
    if cache is not None:
        cache.end()
    counts = Counts(current_rows=len(rows), current_files=len(current), goal_titles=n_goal_works,
                    goal_files=len(goal_items), finished=n_fin,
                    arrivals=len(arrival_rows), arrival_files=len(arrivals))
    lang = LANGUAGE_NAMES.get(language, "")
    if rows:
        subline = STRINGS["subline"].format(lang=lang, rows=counts.current_rows, files=counts.current_files)
    elif not items:
        subline = STRINGS["subline_empty"].format(lang=lang)
    else:
        subline = STRINGS["subline"].format(lang=lang, rows=0, files=0)
    if mode == "json":                              # the mode's bar first: a library that can't be used says so
        state = "getting-ready"
    elif mode == "read-only":
        state = "read-only"
    elif loading:
        state = "loading"
    else:
        state = "full" if rows else "empty"
    badges = {"needs": len(needs), "arrivals": counts.arrival_files, "finished": counts.finished}
    return View(language=language, mode=mode, reason=reason, state=state, busy=busy, loading=loading, cached=False,
                rows=tuple(rows), lines=tuple(lines), goal=goal, finished=finished, needs=tuple(needs), counts=counts,
                subline=subline, badges=badges, worst=worst, arrivals=arrival_rows, arrival_groups=arrival_groups,
                connect=connect,                    # --- P4.1 L2
                keep_watched=keep)                  # --- W-1


# --- the first screen's cache (02 §2.1) ---------------------------------------------------------------------- #
def _plain(value):
    """namedtuples -> lists (JSON), recursively."""
    if isinstance(value, tuple) and hasattr(value, "_fields"):
        return [_plain(v) for v in value]
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def to_cache(view, rows=CACHE_ROWS):
    """The first `rows` rows of Current, the lines among them, the counts, the subline and the Goal strip: what the
    first frame shows before the store is read."""
    kept = view.rows[:rows]
    return {"rows": _plain([r._replace(string=None) for r in kept]),     # planned again as it's read (`_row_from`)
            "lines": _plain([ln for ln in view.lines if ln.after < len(kept)]),
            "goal": _plain(view.goal)[:5], "counts": _plain(view.counts), "subline": view.subline,   # (W3.2 Q2: no tiles)
            "badges": dict(view.badges), "keep_watched": bool(view.keep_watched)}                # W-1


def _row_from(data):
    r = Row(*data)
    st = Status(*r.status[:4]) if r.status else None             # R47: never a cached Stop
    mk = Mark(*r.mark) if r.mark else None
    eps = tuple(ep._replace(status=Status(*ep.status[:4]) if ep.status else None,
                            mark=Mark(*ep.mark) if ep.mark else None,
                            show_key=tuple(ep.show_key) if ep.show_key else None,     # (JSON wrote it as a list)
                            ask=tuple(ep.ask) if ep.ask else None)                    # row 55 (the same)
                for ep in (Episode(*e) for e in r.episodes))
    chips = tuple(Chip(*c) for c in r.chips)
    r = r._replace(status=st, mark=mk, episodes=eps, chips=chips,
                   cover=CoverRef(*r.cover) if r.cover else None,                  # W3.2 Q6
                   works=tuple(r.works or ()))                                     # LM11b G1
    plan = stone_plan.plan(r.episodes, r.next_index, r.media, r.key, r.source == "hato")     # planned again, not kept
    return r._replace(string=(plan, max(stone_plan.tightest(plan), stone_plan.ahead(plan))))


def from_cache(data, language="ja"):
    """A `View` of the cached first screen (state *loading*, `cached` True), or None when the data isn't ours."""
    try:
        rows = tuple(_row_from(r) for r in data["rows"])
        return View(language=language, mode="store", reason=None, state="loading", busy=False, loading=True,
                    cached=True, rows=rows, lines=tuple(Line(*ln) for ln in data["lines"]), goal=Goal(*data["goal"]),
                    finished=(), needs=(), counts=Counts(*data["counts"]), subline=data["subline"],
                    badges=dict(data.get("badges") or {}), worst=worst_needs(rows[1:]),
                    keep_watched=bool(data.get("keep_watched")))           # W-1: absent (an older cache): off
    except (KeyError, TypeError, ValueError):
        return None

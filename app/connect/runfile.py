"""The run file Anki Miner's `--api mine` reads (P1.3 row 1.3.4; API.md "mine", the Integration Spec §4.2).

Anki Miner refuses a run file it can't trust, whole (`BAD_RUN_FILE`): an unknown key at any level, `"config": null`,
a value of the wrong type, more than 8 MB, and (3.6.0) a string holding an unpaired surrogate. So this writes only the
keys the version it was asked of accepts, checks every string before a byte is written, and writes the file strict
UTF-8 without a BOM (K61), replaced atomically.

`config` is Surasura's say over the run (IS:270–277): every filter of Anki Miner's off, so the words Surasura names are
the words it mines — deck, note type and fields from Anki Miner's own settings export (`fields.py`). Two of those keys,
`deduplicate_sentences` and `use_i_plus_one_filter`, go only to a version that still needs them: 3.5 and 3.6 take
them; 3.7 turns both off for every run itself (`sentence-rules-off`, Z-4) and takes them only as false. So they're sent
only when `features` doesn't say the rules are off already and the version is 3.6 or older; a refusal naming them is
answered by the caller writing the file again without them, once (a build between the two, am-upstream D1).

What Anki Miner 3.7 adds is used only where `version`'s `features` names it (08-zero: a name, never a version number):
`bold-target` (Z-5): the target bolded in the card's sentence, `bold_target_in_sentence` in `config`; `word-from-line`
(Z-2): a named word its line holds but Anki Miner's own reading doesn't is made from that line, so each word goes as
one entry, with the word as the line writes it (`surface`) and its reading (`word_requests`); `dry-run` (Z-7): a
top-level `dry_run` that reports what the run would make, with no media, no Anki and no lock.
"""
import json
import math
import os
import re

SCHEMA = 1
MAX_BYTES = 8 * 1024 * 1024
RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
TAG_PREFIX = "surasura::connect::"
NAME_TAG = "surasura::name"     # on every card of a name (G1.3), added after mining: Anki Miner tags by episode

# The keys `config` may hold (Anki Miner 3.5.0 `cli/api/settings.py` ALLOWED_OVERLAY_KEYS; 3.7.0 adds the bold, and
# takes the two sentence keys only as false)
CONFIG_KEYS = frozenset((
    "anki_deck_name", "anki_note_type", "anki_fields", "card_type", "card_type_marker_fields",
    "allow_duplicate_cards", "merge_incomplete_cues", "max_parallel_workers", "min_frequency_rank",
    "max_frequency_rank", "use_blacklist", "use_whitelist", "max_sentence_duration_seconds", "max_sentence_chars",
    "exclude_hiragana_only_words", "exclude_katakana_only_words", "deduplicate_sentences", "use_i_plus_one_filter",
    "bold_target_in_sentence"))
RUN_KEYS = frozenset(("schema", "run_dir", "profile", "language", "config", "episodes", "dry_run"))
SENTENCE_KEYS = ("deduplicate_sentences", "use_i_plus_one_filter")

# The names in Anki Miner's `features` (API.md "version") the run file acts on
SENTENCE_RULES_OFF = "sentence-rules-off"       # Z-4: the two sentence keys are no longer needed
BOLD_TARGET = "bold-target"                     # Z-5: `bold_target_in_sentence` in config
WORD_FROM_LINE = "word-from-line"               # Z-2: a named word made from its line; `surface`, `reading`
DRY_RUN = "dry-run"                             # Z-7: `dry_run` in the run file

# IS:271–275: every filter off. `use_whitelist` stays the profile's own: before Z-1 the "Surasura" profile's whitelist
# is how the named words pass his name lists (N10, P1.5-14); from 3.7 every named word is whitelisted, any profile.
FILTERS_OFF = {
    "min_frequency_rank": 0, "max_frequency_rank": 0,
    "use_blacklist": False,
    "exclude_hiragana_only_words": False, "exclude_katakana_only_words": False,
    "max_sentence_duration_seconds": 0, "max_sentence_chars": 0,
    "allow_duplicate_cards": False,
}


class RunFileError(ValueError):
    """A run file Anki Miner would refuse: never written."""


def version_tuple(app):
    """'3.6.0' -> (3, 6, 0); a version that can't be read -> None."""
    parts = re.findall(r"\d+", str(app or ""))[:3]
    return tuple(int(p) for p in parts) if parts else None


def sends_sentence_keys(app, features=()):
    """Does a run file for Anki Miner `app` (with `features`) carry the two sentence keys as false (§ above)?"""
    if SENTENCE_RULES_OFF in (features or ()):
        return False
    version = version_tuple(app)
    return version is not None and version[:2] <= (3, 6)


def config(mapping, app, features=(), sentence_keys=None):
    """The run's `config`: every filter off, and the deck, note type and fields `mapping` names (fields.Mapping); the
    target bolded in its sentence where Anki Miner takes that (Z-5, 08-zero: sent per run; Junban and Backfill read
    the bold, K56). `sentence_keys` overrides the version's rule (the caller's one retry without them)."""
    out = dict(FILTERS_OFF)
    out.update(anki_deck_name=mapping.deck, anki_note_type=mapping.note_type, anki_fields=dict(mapping.fields))
    if sends_sentence_keys(app, features) if sentence_keys is None else sentence_keys:
        out.update(deduplicate_sentences=False, use_i_plus_one_filter=False)
    if BOLD_TARGET in (features or ()):
        out["bold_target_in_sentence"] = True
    return out


def job_tag(job):
    """The tag on every note one job makes: `surasura::connect::<job>` (HC-B2: its cards are counted by it)."""
    return TAG_PREFIX + job


def from_line(features=()):
    """Does this Anki Miner make a named word from its line (Z-2, `word-from-line`)?"""
    return WORD_FROM_LINE in (features or ())


def entries(word, features=()):
    """The names one picked word goes as. Before Z-2: its card front, and Surasura's Word when pick added it (IS:235;
    the Word finds the card the front misses, else comes back `duplicate` or `not_found`). Once Anki Miner makes a
    word from its line: the card front alone. A second name could be made from the same line as a second card of the
    same word (事 found inside 仕事 on the line where Anki Miner read こと into a longer expression), and the front with
    the word as written and its reading already reaches what the Word did."""
    return list(word["sent"][:1]) if from_line(features) else list(word["sent"])


def word_requests(words, features=()):
    """The run file's `words` for picked words (pick.pick's): each name `entries` gives, with the line's start in
    seconds and its expansion, always sent (IS:260). Where Anki Miner makes a word from its line (Z-2), the entry also
    carries the word as this line writes it (`surface`, when it differs: 借り for 借りる, a set phrase's own words) and
    the reading its card front is said with here (`front_reading`: hiragana, as Anki Miner writes readings; やっぱり,
    never its lemma's やはり). The reading chooses among dictionary entries, so the card is Surasura's word."""
    out, made = [], from_line(features)
    for word in words:
        for name in entries(word, features):
            entry = {"word": name, "line_start": float(word["line_start"]),
                     "line_expansion": [int(n) for n in word["line_expansion"]]}
            if made:
                surface, reading = word.get("surface"), word.get("front_reading")
                if surface and surface.strip() and surface != name:
                    entry["surface"] = surface
                if reading and reading.strip():
                    entry["reading"] = reading
            out.append(entry)
    return out


def episode(run_id, video, subtitle, words, tags="", subtitle_offset=0.0):
    """One episode of a run: its video and subtitle (absolute paths), the words, the job's tags, and the subtitle's
    offset from the fit check (0 until tsubasa's check is wired, P2.4) — always sent (IS:269)."""
    return {"run_id": run_id, "video_file": os.path.abspath(video), "subtitle_file": os.path.abspath(subtitle),
            "subtitle_offset": float(subtitle_offset), "tags": tags, "words": list(words)}


def build(run_dir, language, episodes, profile=None, run_config=None, dry_run=False):
    """The whole run file. `run_dir` must exist when Anki Miner reads it (write() makes it). No `profile`: Anki Miner's
    active one. `dry_run` (Z-7, only to a build naming `dry-run`): what the run would make; nothing is made."""
    data = {"schema": SCHEMA, "run_dir": os.path.abspath(run_dir), "language": language, "episodes": list(episodes)}
    if profile:
        data["profile"] = profile
    if run_config is not None:
        data["config"] = run_config
    if dry_run:
        data["dry_run"] = True
    return data


def check(data):
    """Raise RunFileError for what Anki Miner would refuse before it mines: a key it doesn't take, an empty word
    list, a run id it can't name a folder by, two episodes with one id, a time that isn't a finite number of 0 or
    more, an empty `surface`, `reading` or `line_text` (3.7.0), a `dry_run` that isn't true or false, and any string
    holding an unpaired surrogate (3.6.0)."""
    unknown = set(data) - RUN_KEYS
    if unknown:
        raise RunFileError(f"the run file has unknown keys: {sorted(unknown)}")
    if "dry_run" in data and not isinstance(data["dry_run"], bool):
        raise RunFileError("dry_run must be true or false")
    if "config" in data:
        if not isinstance(data["config"], dict):
            raise RunFileError("config must be an object")
        bad = set(data["config"]) - CONFIG_KEYS
        if bad:
            raise RunFileError(f"config has keys Anki Miner doesn't take: {sorted(bad)}")
    episodes = data.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        raise RunFileError("a run file names at least one episode")
    ids = [e.get("run_id") for e in episodes]
    if len(set(ids)) != len(ids):
        raise RunFileError("two episodes share a run_id")
    for e in episodes:
        if not isinstance(e.get("run_id"), str) or not RUN_ID.fullmatch(e["run_id"]):
            raise RunFileError(f"a run_id may hold only letters, digits, - and _ (at most 64): {e.get('run_id')!r}")
        if not e.get("words"):
            raise RunFileError(f"episode {e['run_id']} names no word (there is no 'all')")
        for w in e["words"]:
            start = w.get("line_start")
            if start is not None and (isinstance(start, bool) or not isinstance(start, (int, float))
                                      or not math.isfinite(start) or start < 0):
                raise RunFileError(f"line_start must be a finite number of 0 or more: {start!r}")
            if not str(w.get("word", "")).strip():
                raise RunFileError("a word is empty")
            for key in ("surface", "reading", "line_text"):
                if key in w and (not isinstance(w[key], str) or not w[key].strip()):
                    raise RunFileError(f"a word's {key} is empty")
    _strings(data)


def _strings(value, where="run file"):
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise RunFileError(f"{where} holds an unpaired surrogate: {value!r}") from None
    elif isinstance(value, dict):
        for key, item in value.items():
            _strings(key, where)
            _strings(item, f"{where}.{key}")
    elif isinstance(value, list):
        for item in value:
            _strings(item, where)


def write(path, data):
    """Check `data`, then write it to `path` as strict UTF-8 without a BOM (K61), atomically (a temp file, then
    os.replace); the folders it names (`run_dir`, the file's own) are made. Returns the path."""
    check(data)
    raw = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")      # strict: a surrogate raises above
    if len(raw) > MAX_BYTES:
        raise RunFileError(f"the run file would be {len(raw)} bytes; Anki Miner reads at most {MAX_BYTES}")
    os.makedirs(data["run_dir"], exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


def without_sentence_keys(data):
    """`data` with the two sentence keys taken out of its config (the caller's one retry after a refusal)."""
    out = dict(data)
    if isinstance(out.get("config"), dict):
        out["config"] = {k: v for k, v in out["config"].items() if k not in SENTENCE_KEYS}
    return out

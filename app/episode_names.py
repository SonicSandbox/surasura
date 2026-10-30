"""Episode names (LM1a, the library model's root rule): ONE reading of a file name, which every reader asks.

Seven readers each read a name their own way — the look's `_tag`, `_episode_of`, `_release` and season folder
(`sources`), the store's `show_of_name`, the window's `episode_number` (`services/view_rows`), Connect's `names_for`
(`connect/videos`) and the covers' season folder (`services/covers`) — and they disagreed (adversary A33: `Show - 05 -
Title 12` was episode 12 in the window and 5 in the look; `3_Japanese` was 3 and nothing). Each now calls this; none
keeps a pattern of its own (Sonic: one shared rule, never a second copy).

`identity(name, folder_name=None, bare_numbers=False)` -> `Name`:

- **stem**: the name without its extension and the marks read below, as written (the video a subtitle goes with is
  named so: `Show - 05.ja.forced.srt` → `Show - 05`).
- **language / languages / flags / bilingual** (A6, A7): dot tags read from the right (`.ja.forced`; a flag either
  side of the language; `.hi` is hearing-impaired, never Hindi; a second language tag ends the reading), a bracket
  group that holds only marks (`[jpn]`, `[CHS]`, `(JPN)`, `[GB_JP]`, `[简日双语]`; never the leading `[group]`), AM's
  `_track3_[jpn]`, an underscore's word (`_karaoke`), `N_Language` (`3_Japanese`: a track named by its language, no
  episode or show of its own, A11); a re-timer's mark (`.synced`, `.retimed`: `retimed`, LF-17) comes off too; the
  Chinese fansub marks (`CHS CHT SC TC GB BIG5 简 繁 简体 繁體`). A bracket or an
  underscore reads a short list (never `[Fin]`, `[END]`: no language); a dot tag ISO 639-2's codes and, of 639-1's
  two letters, only the languages the app names (`.ab`, a release site's tag, is no tag: the text decides). Flags:
  `forced sdh hi cc signs songs s&s karaoke op ed commentary lyrics`. Two languages in one mark (`chs&jpn`, `GB_JP`, `简日双语`) =
  `bilingual` (`language` None, both in `languages`): picked only when nothing monolingual exists.
- **show**: the show as written (NFKC), a store's `show_of_name`: every `[…]` / `(…)` tag, resolution and hash, a
  version and the episode marker with all after it come off; a season stays in it (`S2`, `2期`, `II`; `S02E05` reads
  `… S2`); `[group][show][05]` reads the bracket before the number; None when nothing but digits and marks is left.
- **season** (A2): `SxxEyy`, a show ending in `S2` / `Season 2` / `2nd Season` / `第2期` / `2期` / `II`, else the
  season folder `folder_name` names (`season_folder`); None when none is written (the key reads it as season 1).
- **episode / episodes / version / part**: K4's markers (` - 05`, `E05`, `Ep 5`, `Episode 5`, `#05`, `第05話`, `05話`,
  `05集`, `S01E05`; `- 05v2` is version 2), a special's own number (`OVA 01`), `[05]` / `[第05话]` in the bracketed
  layout (A6); a range claims every number in it (`05-06`, `S01E05-E06`, `第5-6話`: A13); a part written after the
  number (`Part 2`, `Pt 2`, `前編 / 中編 / 後編`, `CD2`, `05a / 05b`, in brackets too: A3) — one before it is the show's
  (`Final Season Part 2 - 05`).
  With `bare_numbers` (the caller says every name of that pattern reads one: A10; the window, which has no folder to
  ask) the last bare number is the episode too — never a year (19xx / 20xx), a date or a resolution.
- **special** (A4): `OVA OAD SP Special Movie 劇場版 総集編 特別編 番外編 Recap NCOP NCED PV CM Menu Preview` as a whole
  word (`Spice` holds none) before the episode marker (`Show OVA - 01`), as a special's own number (`OVA 01`) or a
  bracket holding just the mark (`(OVA)`, `[Menu]`) — never the leading `[group]` (`[SP-Fansub]`), a release tag
  (`(CMカット)`, `[SP Ver]`) or the title after the number (review A2): the mark (`'OVA'`), else False.
- **group** (A28, LM2): (the leading `[tag]`, the name before the episode marker, the folder), folded: two episodes of
  one release share it whatever comes after their numbers.
- **release** (H13): the name without its release's marks (`[group]`, `(1080p)`, a hash, a version, its tags and
  extension), folded.
- **key**: (show folded without its season, season (1 when none written; `S00`, the specials season, is 0: review A1),
  episode, part, special) — the one thing every "same episode?" question compares. A special is in it: an OVA's 01 is
  never episode 1. PROVISIONAL (Sonic 2026-10-21: accepted for building, to be checked in use), as the look's grouping
  by it is.

Names are compared NFKC-folded (which composes: a Mac's NFD name is its NFC name, A24); `video_stems` gives both forms
for the names compared as written. Pure: the standard library only (no Qt, no store), any thread may ask.
"""
import os
import re
import unicodedata
from functools import lru_cache
from typing import NamedTuple


class Name(NamedTuple):
    show: object            # str or None
    season: object          # int or None
    episode: object         # int, float (12.5) or None
    episodes: tuple         # every number it claims: (5, 6) for `05-06`; () with no episode
    part: object            # int or None
    version: int            # 2 for `- 05v2`, else 1
    special: object         # the mark ('OVA', '劇場版') or False
    group: tuple            # (leading tag, name before the episode marker, folder), folded
    language: object        # 'ja', 'zh', 'other' or None (none, or two: `bilingual`)
    languages: frozenset
    flags: frozenset
    bilingual: bool
    retimed: bool           # LF-17: a re-timer's mark (`.synced`) came off its stem
    stem: str               # the name without its extension and its marks, as written
    release: str            # H13: without its release's marks, folded
    key: tuple              # (show, season, episode, part, special)
    year: object            # A3: the year written before the episode marker ('2009'), else None


# --- the marks ------------------------------------------------------------------------------------------------- #

# A dot tag's language (`Show - 05.ja.srt`, `.pt-BR`): ISO 639-2 (B and T), a few names; `sc` / `tc` are Chinese here,
# never Sardinian; a tag not listed is no tag. Of ISO 639-1's two letters only the languages the app names (ours, and
# the subtitle languages it names: `_NAMED`): a two-letter tag is as often a release's own (`.ab`, AnimeBytes', is no
# Abkhazian: Mattias 2026-10-27, his whole show refused) — another is no tag, and the file's text decides (the look's
# one language rule, `sources._refusal`). PROVISIONAL (Kura alpha 5, to be checked in use)
_NAMED = {"en": "english", "ko": "korean", "es": "spanish", "fr": "french", "de": "german", "pt": "portuguese",
          "ru": "russian", "it": "italian", "ar": "arabic", "vi": "vietnamese", "th": "thai", "id": "indonesian"}
_ISO_639_2 = ("aar abk ave afr aka amh arg ara asm ava aym aze bak bel bul bih bis bam ben tib bod bre bos cat che "
              "cha cos cre cze ces chu chv wel cym dan ger deu div dzo ewe gre ell eng epo spa est baq eus per fas "
              "ful fin fij fao fre fra fry gle gla glg grn guj glv hau heb hin hmo hrv hat hun arm hye her ina ind "
              "ile ibo iii ipk ido ice isl ita iku jav geo kat kon kik kua kaz kal khm kan kor kau kas kur kom cor "
              "kir lat ltz lug lim lin lao lit lub lav mlg mah mao mri mac mkd mal mon mar may msa mlt bur mya nau "
              "nob nde nep ndo dut nld nno nor nbl nav nya oci oji orm ori oss pan pli pol pus por que roh run rum "
              "ron rus kin san srd snd sme sag sin slo slk slv smo sna som alb sqi srp ssw sot sun swe swa tam tel "
              "tgk tha tir tuk tgl tsn ton tur tso tat twi tah uig ukr urd uzb ven vie vol wln wol xho yid yor zha "
              "zul fil scc scr")
_JA = "ja jp jpn jap japanese 日本語 日本语 日语 日文".split()
_ZH = ("zh zho chi chs cht sc tc gb big5 chinese cmn yue 中文 简体 繁体 繁體 简中 繁中 简体中文 繁體中文 繁体中文 简繁 "
       "中文简体 中文繁体 simplified traditional").split()                                       # (D4)
_LANGS = dict.fromkeys(list(_NAMED) + list(_NAMED.values()) + _ISO_639_2.split(), "other")
_LANGS.update(dict.fromkeys(_JA, "ja"))
_LANGS.update(dict.fromkeys(_ZH, "zh"))
LANGS = _LANGS                  # the one language table: the look's named-folder rule reads it too (`Subs/<language>`)
# A bracket's or an underscore's language: a short list (a release's `[Fin]` is no Finnish, `[IT]` no Italian)
_MARKS = dict.fromkeys("en eng english kor korean spa spanish fre fra french ger deu german por portuguese rus "
                       "russian ita italian ara arabic vie vietnamese tha thai ind indonesian 英 英文 英语 英語".split(),
                       "other")
_MARKS.update(dict.fromkeys(_JA + "日 日語".split(), "ja"))
_MARKS.update(dict.fromkeys(_ZH + "简 簡 繁 簡體 中".split(), "zh"))
_FLAGS = frozenset({"forced", "sdh", "hi", "cc", "signs", "songs", "s&s", "karaoke", "op", "ed", "commentary",
                    "lyrics"})      # a track's flags (Plex, Jellyfin, Bazarr, Anki Miner), never a language
# A re-timer's mark ending a subtitle's name (LF-17: `<video>.ja.synced.srt`, either side of the language): no flag, it
# comes off the stem (the file is that video's episode) and says the file was re-timed; `.alt` stays an unknown tag
RETIMED = frozenset({"synced", "sync", "resync", "resynced", "retimed", "timed"})
_CJK = re.compile(r"((?:简体|簡體|繁体|繁體|简中|繁中|中文|日文|日语|日語|日本語|英文|英语|英語|[简簡繁中日英])+)"
                  r"(双语|雙語|双字|雙字)?(?:内嵌|內嵌|内封|內封|外挂|外掛|字幕)?")
_CJK_PART = re.compile(r"简体|簡體|繁体|繁體|简中|繁中|中文|日文|日语|日語|日本語|英文|英语|英語|[简簡繁中日英]")
_SPLIT = re.compile(r"\s*[&+_,/・·]\s*|\s+")
_BRACKET = re.compile(r"[\[［]([^\[\]［］]*)[\]］]|[(（]([^()（）]*)[)）]|【([^【】]*)】")
_TRACK = re.compile(r"[_. ]track\d{1,2}$", re.I)
_UNDERSCORE = re.compile(r"_([^_\s\[\]()［］（）.]+)$")
_N_LANGUAGE = re.compile(r"\d{1,2}[_ ]([^\W\d_]+)")

# --- the numbers ----------------------------------------------------------------------------------------------- #

_EXT = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_TAGS = re.compile(r"\[[^\]]*\]|\([^)]*\)")                      # [group], [ABCD1234], (1080p): never the show
_JUNK = re.compile(r"\b(?:\d{3,4}[pi]|\d{3,4}x\d{3,4}|(?=[0-9A-F]*\d)[0-9A-F]{8})\b")
_SEASON_EP = re.compile(r"\bS(\d{1,2})[ ._-]?E(\d{1,4})(?:(?:-E?|E)(\d{1,4}))?", re.I)  # S01E13, S01E05-E06
_EPISODE = re.compile(r"(?:\s[-–~]\s*|\b(?:EP(?:ISODE)?|E)\.?\s?|#\s?)(\d{1,4}(?:\.\d)?)([abc])?(?:v(\d+))?"
                      r"(?:[-~–](\d{1,4}))?\b"                                       # - 16, E13, #13, - 05a, - 05-06
                      r"|第\s?(\d{1,4})(?:\s?[-~–]\s?(\d{1,4}))?\s?[話话集回]"     # 第13話, 第13集, 第5-6話
                      r"|(?<![\d.])(\d{1,4})(?:\s?[-~–]\s?(\d{1,4}))?\s?[話话集]", re.I)   # 13話, 05集 (A6)
_SPECIAL_NUMBER = re.compile(r"(?<![A-Za-z0-9])(?:OVA|OAD|SP|Specials?|NC\s?OP|NC\s?ED|PV|CM|Recap|Preview)\s?"
                             r"(\d{1,3})(?:v(\d+))?\b", re.I)
_BRACKET_NUMBER = re.compile(r"\[第?(\d{1,4}(?:\.\d)?)(?:v(\d+))?(?:[-~](\d{1,4}))?\s*[話话集回]?\s*(?:END|Fin|完)?\]",
                             re.I)                              # [05], [05v2], [05 END], [第05话] (A6)
_Y = r"(?:19|20)\d\d"                                            # a year: the ONE pattern every year read uses
_YEAR = re.compile(_Y)
_DATE = re.compile(_Y + r"[-./]\d{1,2}[-./]\d{1,2}")
_YEAR_TAG = re.compile(r"[\[(（［](" + _Y + r")[\])）］]")                  # `Show (2009)`, `Show [2023]` (A3)
_YEAR_DASH = re.compile(r"\s[-–~]\s*(" + _Y + r")\s*$")                   # `Show - 2019` before ` - 05` (A7)
# The four Japanese special words mark a special wherever they stand (`Show - 05 特別編`: LM1b, PROVISIONAL)
_JA_SPECIAL = re.compile(r"劇場版|総集編|特別編|番外編")
# A video of an extra, by a mark anywhere in its name: never an episode's video, never waiting (never `CM` here: a
# `(CMカット)` recording is an episode; a bracket holding just `(CM)` is the special's own mark, NEVER_WAIT's)
_EXTRA = re.compile(r"(?<![A-Za-z])(?:NC\s?OP|NC\s?ED|(?-i:OP|ED|PV)|Creditless|Trailer|Teaser|Menu|Preview)"
                    r"(?:\s?\d{1,2})?(?![A-Za-z])|ノンクレジット|ノンテロップ", re.I)
# Another audio's release (A5): `Dual Audio`, `Dub`, `Multi` (never `Multi-Subs`, which says nothing of the audio)
_DUBBED = re.compile(r"(?<![a-z])(?:dual|dub|dubbed|multi(?![\s._-]?subs?))(?![a-z])", re.I)
_BARE = re.compile(r"(?:^|(?<=[\s\-#]))(\d{1,4})(?:v(\d+))?(?=\s|$)", re.I)
_VERSION = re.compile(r"(?:(?<=\d)|\s)v\d+$", re.I)
_DOT_VERSION = re.compile(r"\.v\d{1,2}", re.I)                   # `Show - 05.v2.srt`: its video is `Show - 05` (A5)
_SPACES = re.compile(r"\s+")
_SPECIAL = re.compile(r"(?<![A-Za-z0-9])(OVA|OAD|SP|Specials?|Movie|Recap|NC\s?OP|NC\s?ED|PV|CM|Menu|Preview)"
                      r"(?:\d{1,3})?(?![A-Za-z])|(劇場版|総集編|特別編|番外編)", re.I)
_PART = re.compile(r"(?<![A-Za-z])(?:Part|Pt)\.?\s?(\d{1,2})(?!\d)|([前中後后])[編篇编]|(?<![A-Za-z])CD\s?(\d)(?!\d)",
                   re.I)
_PART_OF = {"前": 1, "中": 2, "後": 3, "后": 3, "a": 1, "b": 2, "c": 3}
_KANJI_NUMBER = {c: n for n, c in enumerate("一二三四五六七八九十", 1)}
_SHOW_SEASON = re.compile(r"\s+(?:S(\d{1,2})|Season\s*(\d{1,2})|(\d{1,2})(?:st|nd|rd|th)\s+Season|"
                          r"第\s*(\d{1,2}|[一二三四五六七八九十])\s*[期季]|(\d{1,2})\s*期)$", re.I)
_SHOW_ROMAN = re.compile(r"\s+(II|III|IV|V|VI)$")
_ROMAN = {"II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}
_SHOW_SPECIAL = re.compile(r"\s+(?:OVA|OAD|SP|Specials?|Movie|Recap|劇場版|総集編|特別編|番外編)$|"
                           r"^(?:劇場版|総集編|特別編|番外編)\s+", re.I)
# A special's videos that never wait for a subtitle of their own (A32): a creditless opening or ending, a promotion, an
# advert, a menu — never an episode to read
NEVER_WAIT = frozenset({"NCOP", "NCED", "PV", "CM", "MENU", "PREVIEW"})
# A folder that is only a season or the specials (S12): the look puts the source's name in front, the covers look one
# folder up for its art
_SEASON_FOLDER = re.compile(r"s[\s._-]?(\d{1,3})|(?:(?:season|series)[\s._-]*(\d{1,3})|"
                            r"(\d{1,2})(?:st|nd|rd|th)[\s._-]*season|"
                            r"第\s*(\d{1,3}|[一二三四五六七八九十])\s*[期季部]|シーズン\s*(\d{1,3}))"
                            r"(?P<tail>[\s._\-–~:(\[].*)?|(\d{1,3})\s*期", re.I)
_SPECIALS_FOLDER = re.compile(r"specials?|sps?|extras?|ova|oad", re.I)
_SPECIALS_WORD = {"ova": "OVA", "oad": "OAD", "extra": "Extras", "extras": "Extras"}   # the rest: `Specials`
_KATAKANA_FOLD = {c: c - 0x60 for c in range(0x30A1, 0x30F7)}     # ァ…ヶ → ぁ…ゖ (as `library_store.search_fold`)


def fold(text):
    """A name folded for comparing: NFKC (composed: an NFD name is its NFC name), case-folded, katakana as hiragana,
    whitespace runs as one space — `library_store.search_fold` without its Chinese script step (a reader comparing
    shows of one language folds the key's show again with it)."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", str(text)).casefold().translate(_KATAKANA_FOLD)
    return _SPACES.sub(" ", folded).strip()


def language_of(tag):
    """A dot tag's or a language folder's language (`ja`, `zh-Hans`, `English`): 'ja', 'zh', 'other' or None."""
    tag = unicodedata.normalize("NFKC", tag or "").strip().casefold()
    return _LANGS.get(tag) or _LANGS.get(re.split(r"[-_]", tag)[0])


def _mark(text, table):
    """The languages and flags one mark holds — a dot tag (`table` = every ISO code), a bracket's text or an
    underscore's word (the short list) — as (languages, flags, said bilingual: `双语`), or None when it holds anything
    else (two languages in it are bilingual too: `_marks` counts them)."""
    t = unicodedata.normalize("NFKC", text).strip().casefold()
    if not t:
        return None
    if t in _FLAGS:
        return frozenset(), frozenset({t}), False
    langs, flags, two = set(), set(), False
    for token in _SPLIT.split(t):
        if not token:
            continue
        cjk = _CJK.fullmatch(token)
        if token in _FLAGS:
            flags.add(token)
        elif table.get(token) or ("-" in token and _LANGS.get(token.split("-")[0])):
            langs.add(table.get(token) or _LANGS[token.split("-")[0]])
        elif cjk:
            langs.update(_MARKS[p] for p in _CJK_PART.findall(cjk.group(1)))
            two = two or bool(cjk.group(2))
        else:
            head = table.get(re.split(r"[-_]", t)[0])            # `zh_cn`, `ja_JP`: the language before its region
            return (frozenset({head}), frozenset(), False) if head and "&" not in t and "+" not in t else None
    if not langs and not flags:
        return None
    return frozenset(langs), frozenset(flags), two


def _marks(stem):
    """(stem without its marks, languages, flags, bilingual, a track named by its language, re-timed): the dot tags
    from the right (a second language tag ends them, as it always did; a re-timer's mark comes off), then every bracket of marks but the leading one, AM's
    `_track3`, an underscore's word (never `_hi` / `_cc`: a word, not a flag), and `N_Language`."""
    langs, flags, two, retimed = set(), set(), [], False

    def take(m):
        langs.update(m[0])
        flags.update(m[1])
        two.append(m[2])

    while True:
        base, dot = os.path.splitext(stem)
        if base and unicodedata.normalize("NFKC", dot[1:]).casefold() in RETIMED:
            retimed, stem = True, base
            continue
        m = _mark(dot[1:], _LANGS) if base and dot[1:] else None
        if m is None or (m[0] and langs):
            break
        take(m)
        stem = base
    for b in reversed(list(_BRACKET.finditer(stem))):
        m = _mark(next(g for g in b.groups() if g is not None), _MARKS) if b.start() > 0 else None
        if m is not None:
            take(m)
            left, right = stem[:b.start()], stem[b.end():]
            stem = left.rstrip(" ") + right if not right or right.startswith(" ") else left + right
    track = _N_LANGUAGE.fullmatch(unicodedata.normalize("NFKC", stem).strip())
    track = track and _MARKS.get(track.group(1).casefold())
    if track:                                                   # `3_Japanese`: its language, and nothing else
        langs.add(track)
    while not track:
        tail = stem.rstrip(" _")
        t, u = _TRACK.search(tail), _UNDERSCORE.search(tail)
        m = _mark(u.group(1), _MARKS) if u and u.group(1).casefold() not in ("hi", "cc") else None
        if t is None and m is None:
            break
        if t is None:
            take(m)
        stem = tail[:(t or u).start()]
    return stem, frozenset(langs), frozenset(flags), any(two) or len(langs) >= 2, bool(track), retimed


def _number(value):
    value = float(value)
    return int(value) if value.is_integer() else value


def _clean(prefix):
    """A show as `show_of_name` writes it, from the text before its episode marker: resolution and hash tags, a
    version, runs of spaces and the marks at its ends off; None when only digits and marks are left."""
    name = _JUNK.sub(" ", prefix)
    name = _VERSION.sub("", name.strip())
    name = _SPACES.sub(" ", name).strip(" -–~._")
    return None if re.fullmatch(r"[\W\d_]*", name) else name


def _season(show):
    """(the show without a season written at its end, that season) — `Show S2`, `Show 2nd Season`, `Show II`."""
    m = _SHOW_SEASON.search(show) or _SHOW_ROMAN.search(show)
    if not m:
        return show, None
    if m.re is _SHOW_ROMAN:
        return show[:m.start()], _ROMAN[m.group(1)]
    value = next(g for g in m.groups() if g is not None)
    return show[:m.start()], _KANJI_NUMBER.get(value) or int(value)


def season_folder(name):
    """A folder that is only a season (`Season 2`, `S2`, `2nd Season`, `第2期`, `2期`, `シーズン2`, `Season 2 - Arc`) ->
    its number; one of the specials (`Specials`, `SPs`, `Extras`, `OVA`, `OAD`) -> 'special'; else None."""
    text = unicodedata.normalize("NFKC", name or "").strip()
    if _SPECIALS_FOLDER.fullmatch(text):
        return "special"
    m = _SEASON_FOLDER.fullmatch(text)
    if not m:
        return None
    tail = m.re.groupindex["tail"]
    value = next(g for n, g in enumerate(m.groups(), 1) if g is not None and n != tail)
    return _KANJI_NUMBER.get(value) or int(value)


def folder_title(path):
    """A title named by its folder below the tier (L2.2 05 §5.3 (4)), read by `season_folder`: a season folder is the
    folder above it and its season, written out (`Frieren/S01` → `Frieren Season 1`, `Frieren/第2期` → `Frieren
    Season 2`; a season the folder above already says is said once: `Show S01/Season 01`, `Show.S01/S01` → `Show
    Season 1`; an arc after it stays:
    `Season 2 - Arc` → `… Season 2 - Arc`); a specials folder the folder above and `Specials` (`OVA`, `OAD`, `Extras`
    keep their word). Any other path is as written (one folder: its name; nothing above it). Pure."""
    parts = (path or "").split("/")
    kind = season_folder(parts[-1]) if len(parts) > 1 else None
    if kind is None:
        return path or ""
    above = folder_title("/".join(parts[:-1]))
    if not above.strip():
        return path                                     # no show above it to name it with
    text = unicodedata.normalize("NFKC", parts[-1]).strip()
    if kind == "special":
        return f"{above} {_SPECIALS_WORD.get(text.casefold(), 'Specials')}"
    show, said = _season(above)
    if said is None:                                    # `Show.S01`, `Show_Season_1`: a release's dots or underscores
        show, said = _season(re.sub(r"[._]+", " ", above).strip())
    if said == kind and show.strip():
        above = show.rstrip(" -–~._")
    tail = (_SEASON_FOLDER.fullmatch(text).group("tail") or "").strip(" ._")
    return f"{above} Season {kind}" + (f" {tail}" if tail else "")


def _special(text, whole=False):
    m = (_SPECIAL.fullmatch if whole else _SPECIAL.search)(text.strip())
    if not m:
        return False
    if m.group(2):
        return m.group(2)
    mark = re.sub(r"\s", "", m.group(1)).upper()
    return "SPECIAL" if mark == "SPECIALS" else mark


def _part(texts):
    for text in texts:
        m = _PART.search(text)
        if m:
            return int(m.group(1)) if m.group(1) else _PART_OF[m.group(2)] if m.group(2) else int(m.group(3))
    return None


@lru_cache(maxsize=65536)         # a look asks of one name several times (its tag, episode, release, key); I10: a
#                                   20k library's next look finds its names still kept (8,192 kept none of them)
def identity(name, folder_name=None, bare_numbers=False):
    """The one reading of a file name (the module's docstring): `name` a file name or a path (its last part is read);
    `folder_name` the folder it sits in (a season folder gives a name without one its season; the group names it);
    `bare_numbers` when the caller says every name of its pattern reads a bare number (A10). Pure (its answers
    kept for the last names asked: the same name is read once)."""
    raw = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = _EXT.sub("", raw)
    stem, langs, flags, two, track, retimed = _marks(stem)
    text = unicodedata.normalize("NFKC", stem)
    lead = re.match(r"\s*\[([^\]]*)\]", text)
    inside = [next(g for g in b.groups() if g is not None) for b in _BRACKET.finditer(text)]
    plain = _TAGS.sub(" ", text).replace("_", " ")
    if " " not in plain.strip() and plain.count(".") >= 2:        # Show.Name.S01E13.1080p: dots are the spaces
        plain = plain.replace(".", " ")
    season, number, upto, version, letter, prefix, rest, suffix = None, None, None, None, None, plain, "", ""
    m = None if track else _SEASON_EP.search(plain)
    if m:
        season, number, upto = int(m.group(1)), m.group(2), m.group(3)
        prefix, rest = plain[:m.start()], plain[m.end():]
        suffix = "" if season <= 1 else f" S{season}"
        cut = _EPISODE.search(prefix)
        prefix = prefix[:cut.start()] if cut else prefix
    elif not track:
        m = _marker(plain)
        if m:
            number = m.group(1) or m.group(5) or m.group(7)
            letter, version, upto = m.group(2), m.group(3), m.group(4) or m.group(6) or m.group(8)
            prefix, rest = plain[:m.start()], plain[m.end():]
        else:
            m = _SPECIAL_NUMBER.search(plain) or (_bare(plain) if bare_numbers else None)
            if m:
                number, version = m.group(1), m.group(2)
                prefix, rest = plain[:m.start(1)], plain[m.end():]
    year = _YEAR_DASH.search(prefix) if m is not None and not track else None
    if year:                                                    # A7: `Show - 2019 - 05` is episode 5 of `Show`
        prefix = prefix[:year.start()]
    show = None if track else _clean(prefix)
    # A2: a special's mark before the episode marker (`Show OVA - 01`, `劇場版 …`; a special's own number's: `OVA 01`)
    # or a bracket holding just the mark (`(OVA)`, `[Menu]`) — never the leading `[group]` (`[SP-Fansub]`), a release
    # tag (`(CMカット)`, `[SP Ver]`) or the title after the number (`- S01E05 - A Very Special Day`)
    special = _special(prefix) or next((s for s in (_special(g, whole=True) for g in inside[1 if lead else 0:]) if s),
                                       False) or (_JA_SPECIAL.search(rest).group(0) if _JA_SPECIAL.search(rest) else False)
    if number is None and not track:
        b = next((b for b in _BRACKET_NUMBER.finditer(text)
                  if b.start() > 0 and not _YEAR.fullmatch(b.group(1))), None)
        if b:
            number, version, upto = b.group(1), b.group(2), b.group(3)
            before = _TAGS.findall(text[:b.start()])
            if show is None and before and (len(before) > 1 or not lead):
                show = _clean(before[-1][1:-1])
            rest = text[b.end():]
    if version is None:
        v = re.match(r"\s?v(\d+)", rest, re.I)
        version = v.group(1) if v else 1
    episode = None if number is None else _number(number)
    episodes = () if episode is None else (episode,)
    if upto and isinstance(episode, int) and episode < int(upto) <= episode + 99:
        episodes = tuple(range(episode, int(upto) + 1))
    part = _PART_OF.get((letter or "").casefold()) or _part(([rest] if episode is not None else [plain]) + inside)
    base, written = _season(show or "")
    if season is None:
        season = written
    if season is None and folder_name:
        s = season_folder(folder_name)
        season = s if isinstance(s, int) else None
    show = None if show is None else show + suffix
    base = _SHOW_SPECIAL.sub("", base) if special else base
    language = next(iter(langs)) if len(langs) == 1 else None
    release = _JUNK.sub(" ", _TAGS.sub(" ", text))
    release = re.sub(r"(?<=\d)v\d+\b", "", release, flags=re.I)
    release = " ".join(release.replace("_", " ").split()).casefold()
    group = (fold(lead.group(1)) if lead and lead.start() == 0 else "", fold(_clean(prefix) or show or ""),
             fold(folder_name))
    # the key: what "the same episode" is (PROVISIONAL, Sonic 2026-10-21: to be checked in use); A1: S00 stays 0; A3:
    # a year written in the name (`Show (2009)`, `Show - 2019 - 05`) keeps a remake apart, and a title of digits alone
    # (`86 - 05`, `22/7 - 05`) is keyed by its digits, never ''
    # (a year tag only before the episode marker: everything after the number is ignored, A28)
    year = year.group(1) if year else next((t.group(1) for t in _YEAR_TAG.finditer(text, lead.end() if lead else 0)
                                            if episode is not None and _after(text[t.end():])), None)
    shown = fold(base) or (fold(re.sub(r"[\W_]+", " ", _JUNK.sub(" ", prefix))) if show is None and episode is not None else "")
    key = (f"{shown} ({year})" if year else shown, 1 if season is None else season, episode, part, special)
    return Name(show, season, episode, episodes, part, int(version), special, group, language, langs, flags, two,
                retimed, stem, release, key, year)


def _after(text):
    """Does an episode marker follow (`text`: what comes after a year tag)? Then the tag was before the number."""
    plain = _TAGS.sub(" ", text)
    return bool(_SEASON_EP.search(plain) or _EPISODE.search(plain) or _SPECIAL_NUMBER.search(plain) or
                _BRACKET_NUMBER.search(text))


def extra(name):
    """A video of an extra — a creditless opening or ending, a promotion, an advert, a trailer, a menu, a preview — by
    its special mark (`NEVER_WAIT`) or such a mark anywhere in its name (`<show> - 01 - NCOP`): never an episode's
    video (the look's number join) and never a waiting item (A32)."""
    n = identity(name)
    return n.special in NEVER_WAIT or bool(_EXTRA.search(n.stem))


def dubbed(name):
    """A5: a video named as another audio's release (`Dual Audio`, `Dub`, `Multi`): taken after the others."""
    return bool(_DUBBED.search(str(name or "")))


def _marker(text):
    """The episode marker of a name: the first, unless its number is a year (19xx / 20xx) with another marker after it
    (A7: `Show - 2019 - 05` is episode 5; `Show - 2019` alone stays 2019, a long show's number)."""
    first = None
    for m in _EPISODE.finditer(text):
        if first is None:
            first = m
        if not _YEAR.fullmatch(m.group(1) or m.group(5) or m.group(7) or ""):
            return m
    return first


def _bare(text):
    """A10: the last bare number (with its version) of a name, never a year, a date or a resolution; None if none."""
    def blank(m):                                               # offsets kept: the caller cuts the name by them
        return " " * len(m.group(0))
    text = _DATE.sub(blank, _JUNK.sub(blank, text))
    found = [m for m in _BARE.finditer(text) if not _YEAR.fullmatch(m.group(1))]
    return found[-1] if found else None


def video_stems(name):
    """The names (without an extension) a video this subtitle goes with may have: its own stem and its stem without
    the marks `identity` reads (`Show - 05.ja.forced.srt` → `Show - 05`, `Show - 05 [CHS].ass` → `Show - 05`), and
    without one dot tag of up to three letters no list holds (a release's own: `ep01.alt.srt` goes with `ep01.mkv`, as
    it always did) or a version's (`.v2`, A5; `Show 1.5` never with `Show 1`), each in NFC and NFD (A24: a video from a
    Mac or a zip is named in NFD)."""
    raw = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    out = []
    stems = [os.path.splitext(raw)[0], identity(raw).stem]
    for stem in stems[:2]:                                      # (the stem as written, then without the marks read)
        base, tag = os.path.splitext(stem)
        if base and (tag[1:].isalpha() and len(tag) <= 4 or _DOT_VERSION.fullmatch(tag)):
            stems.append(base)
    for stem in stems:
        for form in (stem, unicodedata.normalize("NFC", stem), unicodedata.normalize("NFD", stem)):
            if form and form not in out:
                out.append(form)
    return out


# T2-B6 (LM3, PROVISIONAL): a book file's edition marks — a bracket holding an edition word (`(第2版)`, `【新装版】`,
# `[Revised Edition]`, `(v2)`), or one ending the name after a space (`改訂版`, `第二版`, `2nd Edition`, `v2`); never a
# bare number (`<book> 2` is its second volume)
_EDITION_WORD = (r"(?:[^\s()\[\]【】]*版|\bedition\b|\bed\.|\brevised\b|\brev\.|\bv\d+\b|\bver\.?\s*\d+\b|改訂|改订|"
                 r"増補|增补|修订|修訂|新装)")
_EDITION_MARK = re.compile(rf"\s*[(\[【][^)\]】]*?{_EDITION_WORD}[^)\]】]*[)\]】]\s*$|"
                           rf"[\s_\-]+(?:\d+(?:st|nd|rd|th)\s+)?{_EDITION_WORD}\s*$", re.IGNORECASE)


def edition_name(name):
    """T2-B6 (LM3, PROVISIONAL; IK-L3-4: beside the other name readings, `sources` reads it): a book file's name with
    its edition marks off (`_EDITION_MARK`, from its end, NFKC, case-folded): two EPUBs in one folder whose names read
    the same are one book's editions. '' for nothing left."""
    stem = unicodedata.normalize("NFKC", os.path.splitext(name)[0]).strip()
    while True:
        shorter = _EDITION_MARK.sub("", stem).strip()
        if shorter == stem or not shorter:
            return shorter.casefold() if shorter else ""
        stem = shorter

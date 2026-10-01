"""What JMdict says about the joined words — read at build time only, never by the app.

Why this exists
---------------
Three kinds of joined word need a dictionary's judgement that the frequency lists cannot give:

  The fringe       compounds that are a title or a phrase rather than a word of their own. They are joined like
                   every compound, and Settings -> "Phrases and titles as one word" can put them back in their
                   parts. JMdict (the EDRDG's Japanese-English dictionary) decides which they are, never a hand list:
                     a title    — JMdict knows the spelling only as the name of a work, a product, a company or an
                                  organization (もののけ姫, 人間失格, 仮面ライダー);
                     a phrase   — JMdict lists it, but never as a noun: only as an expression, an adverb, an
                                  interjection or a modifier (予想通り 'as expected', こと自体, 毎日毎日) — unless it
                                  marks it an idiom, a four-character idiom or a sound word (沈思黙考, ぎくぎく);
                     a prefix   — its first part is, first of all, a prefix (元首相: 元 'former'; 同世代: 同 'the
                                  same'), and the whole reads as its parts do (仮初め, かりそめ, is no 仮 + 初め).
                   A loanword is never fringe (ゲームオーバー, アイフォン): its parts are pieces of a foreign word, and a
                   katakana word is kept whole when in doubt.
  お / ご words     that the share of uses leaves as a prefix + a word, but that JMdict lists as a word of their own
                   with a meaning the bare word lacks (お守り 'amulet', お帰り 'welcome home', お笑い 'comedy') —
                   not a sense marked polite, honorific or humble, and no gloss the bare word has; a bare word's
                   sense marked as an abbreviation (守り 'amulet') is the prefixed word shortened, so it doesn't
                   count against it.
  Unlisted kana    compounds spelled in katakana alone that JMdict doesn't list (ビルデ = ビル + デ: the lists' tails
                   hold pieces of foreign names). Inside a longer katakana run that is a name as a whole (ビルデイング,
                   an old spelling of 'building'), such a compound gives way and the name stays one word; one JMdict
                   lists (フジテレビ) is a word and keeps its join (フジテレビ + アナウンサー).
  Nouns            that the text writes with a verb's stem (立ち[立つ] + 位置, 待ち[待つ] + 時間), or that a card's word
                   read alone gives as verbs (出来る + 損なう): a noun compound JMdict lists as a noun may have a
                   verb's stem stand in it, and the tokenizer joins such a run too.

scripts/build_reference_data.py calls `fringe`, `unlisted`, `ogo_exceptions` and `lists_as_noun` when JMdict_e.gz is in
docs/assets/reference_lists/ (gitignored) and writes their result to app/dictionary_data.py, which carries the
EDRDG's attribution (CC BY-SA 4.0). Only the spellings these functions pick ship; JMdict itself never does.

Usage:  python scripts/jmdict_flags.py [--jmdict PATH]    # writes debug/jmdict_flags.md, the lists to read

Standard library only, and app/unicode_ranges.py (pure); the tagger, where the report needs one, is the app's.
"""

import gzip
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.unicode_ranges import HAN  # noqa: E402  (pure: no imports of its own)
JMDICT = os.path.join(ROOT, "docs", "assets", "reference_lists", "JMdict_e.gz")
REPORT = os.path.join(ROOT, "debug", "jmdict_flags.md")

FRINGE, TITLE = 1, 2                    # the flags: a title is fringe too (3), so the switch puts it in its parts
UNLISTED = 4                            # a katakana compound JMdict doesn't list: never fringe, never behind the switch
NAME_TAGS = frozenset(("work", "product", "organization", "company"))
NOUN_TAGS = frozenset(("n", "pn"))
PHRASE_TAGS = frozenset(("exp", "adv", "adv-to", "int", "adj-no", "adj-na"))
UNIT_TAGS = frozenset(("yoji", "id", "proverb", "on-mim"))
PREFIX_TAGS = frozenset(("pref", "n-pref"))
POLITE_TAGS = frozenset(("pol", "hon", "hum"))
NOUN_POS = frozenset(("n", "n-adv", "n-t", "n-suf"))     # a noun: common, adverbial, temporal, or used as a suffix
OGO_PREFIXES = {"お": ("お",), "ご": ("ご",), "御": ("お", "ご", "ぎょ", "おん", "み")}

_ENTITY = re.compile(r'<!ENTITY\s+(\S+)\s+"([^"]*)">')
_CREATED = re.compile(r"JMdict created:\s*([0-9-]+)")
_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_KATAKANA = re.compile(r"^[ァ-ヺー]+$")
_HAN = re.compile(f"[{HAN}]")
_BRACKETS = re.compile(r"\([^)]*\)")


def _open(path):
    return gzip.open(path, "rb") if path.endswith(".gz") else open(path, "rb")


def _header(path):
    """-> ({entity text: entity name}, the "created" date or "") — from the DTD, before <JMdict>."""
    names, created_on = {}, ""
    with _open(path) as f:
        for raw in f:
            line = raw.decode("utf-8")
            m = _ENTITY.search(line)
            if m:
                names.setdefault(m.group(2), m.group(1))
            m = _CREATED.search(line)
            if m:
                created_on = m.group(1)
            if line.lstrip().startswith("<JMdict>"):
                break
    return names, created_on


def created(path=JMDICT):
    """The file's "JMdict created" date ("2026-09-28"), or "" when it names none."""
    return _header(path)[1]


def load(path=JMDICT):
    """Every JMdict entry as a plain dict, streamed:
    {"seq": int, "kanji": [(keb, pri, inf)], "kana": [(reb, pri, restr, nokanji, inf)],
     "senses": [{"pos", "misc", "field", "gloss", "xref", "stagk", "stagr", "lsource"}]} — tuples of strings, each tag
    kept as its entity name ("n", "exp", "abbr", "work"). A sense with no part of speech takes the one before it, as
    JMdict's DTD says. A missing file raises FileNotFoundError."""
    names, _ = _header(path)

    def tag(text):
        return names.get(text, text)

    entries = []
    with _open(path) as f:
        for _event, el in ET.iterparse(f, events=("end",)):
            if el.tag != "entry":
                continue
            kanji = [(k.findtext("keb"), tuple(p.text for p in k.findall("ke_pri")),
                      tuple(tag(i.text) for i in k.findall("ke_inf"))) for k in el.findall("k_ele")]
            kana = [(r.findtext("reb"), tuple(p.text for p in r.findall("re_pri")),
                     tuple(x.text for x in r.findall("re_restr")), r.find("re_nokanji") is not None,
                     tuple(tag(i.text) for i in r.findall("re_inf"))) for r in el.findall("r_ele")]
            senses, pos = [], ()
            for s in el.findall("sense"):
                pos = tuple(tag(p.text) for p in s.findall("pos")) or pos
                senses.append({
                    "pos": pos,
                    "misc": tuple(tag(m.text) for m in s.findall("misc")),
                    "field": tuple(tag(m.text) for m in s.findall("field")),
                    "gloss": tuple(g.text or "" for g in s.findall("gloss")),
                    "xref": tuple(x.text for x in s.findall("xref")),
                    "stagk": tuple(x.text for x in s.findall("stagk")),
                    "stagr": tuple(x.text for x in s.findall("stagr")),
                    "lsource": tuple(x.get(_LANG, "eng") for x in s.findall("lsource")),
                })
            entries.append({"seq": int(el.findtext("ent_seq")), "kanji": kanji, "kana": kana, "senses": senses})
            el.clear()
    return entries


# --- Finding a word -------------------------------------------------------------------------------- #

def hiragana(text):
    """カタカナ in ひらがな, without the ・ JMdict writes inside some loanwords: a reading compares either way."""
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text).replace("・", "")


def index(entries):
    """-> ({written form: [entry]}, {kana form: [entry]})."""
    by_kanji, by_kana = defaultdict(list), defaultdict(list)
    for entry in entries:
        for keb, *_ in entry["kanji"]:
            by_kanji[keb].append(entry)
        for reb, *_ in entry["kana"]:
            by_kana[reb].append(entry)
    return by_kanji, by_kana


def _readings(entry):
    return {hiragana(reb) for reb, *_ in entry["kana"]}


def lookup(idx, spelling, reading):
    """The entries that write `spelling` and read `reading` (katakana or hiragana): its kanji form with that
    reading, else — a word written in kana — its kana form."""
    by_kanji, by_kana = idx
    read = hiragana(reading)
    found = [e for e in by_kanji.get(spelling, ()) if read in _readings(e)]
    if not found:
        found = [e for e in by_kana.get(spelling, ()) if read in _readings(e)]
    return found


# --- The fringe ------------------------------------------------------------------------------------ #

def is_title(entries):
    """JMdict knows the spelling only as a name: every sense names a work, a product, a company or an organization
    (もののけ姫; not スラムダンク, which is the basketball word too)."""
    senses = [s for e in entries for s in e["senses"]]
    return bool(senses) and all(NAME_TAGS.intersection(s["misc"]) for s in senses)


def is_phrase(entries):
    """JMdict lists it, but never as a noun: every sense is used the way a phrase is — as an expression, an adverb,
    an interjection or a modifier with の / な (予想通り, こと自体, 毎日毎日, ダメダメ), not as a verb, an adjective, a
    suffix or a counter — and none is marked an idiom or a sound word (沈思黙考, ぎくぎく: units of their own)."""
    senses = [s for e in entries for s in e["senses"]]
    return bool(senses) and all(PHRASE_TAGS.intersection(s["pos"]) and not NOUN_TAGS.intersection(s["pos"])
                                and not UNIT_TAGS.intersection(s["misc"]) for s in senses)


def is_loanword(entries, spelling):
    """A katakana spelling JMdict gives no kanji form (or doesn't list): a loanword (ゲームオーバー, マイペース,
    アイフォン — whose other form is ｉＰｈｏｎｅ, no kanji). ダメダメ is 駄目駄目, no loanword."""
    return bool(_KATAKANA.match(spelling)) and not any(_HAN.search(keb) for e in entries for keb, *_ in e["kanji"])


def is_prefixed(idx, reading, parts):
    """Its first part is, first of all, a prefix — an entry of that spelling and reading whose first sense is a
    prefix and no noun (元 'former' in 元首相, 同 'the same' in 同世代) — and the whole reads as its parts do (仮初め
    is かりそめ, a word of its own reading, not 仮 + 初め)."""
    if len(parts) < 2 or hiragana(reading) != hiragana("".join(p[1] for p in parts)):
        return False
    first = parts[0]
    for entry in lookup(idx, first[0], first[1]):
        pos = set(entry["senses"][0]["pos"]) if entry["senses"] else set()
        if pos & PREFIX_TAGS and not pos & NOUN_TAGS:
            return True
    return False


def fringe_class(idx, spelling, reading, parts):
    """"title", "phrase", "prefix" or None — why a compound is fringe (the report lists each). A loanword never is:
    its parts are pieces of a foreign word (アイ + フォン), and a katakana word is kept whole when in doubt."""
    entries = lookup(idx, spelling, reading)
    if is_loanword(entries, spelling):
        return None
    if is_title(entries):
        return "title"
    if is_phrase(entries):
        return "phrase"
    if is_prefixed(idx, reading, parts):
        return "prefix"
    return None


def fringe(entries, compounds):
    """{spelling: flags} for the compounds JMdict makes fringe: FRINGE | TITLE (3) for a title, FRINGE (1) for a
    phrase or a prefix + a word. `compounds` is the compound table, {spelling: [lemma, reading, kind, flags,
    parts]} with parts [[lemma, reading, free], ...]; the flags already in it are not read. A compound verb (kind
    "V": 取り掛かる, 打ち明ける) is a word, never a phrase or a title — JMdict lists it as a verb, not as a noun."""
    idx, flags = index(entries), {}
    for spelling, (_lemma, reading, kind, _flags, parts) in compounds.items():
        why = None if kind == "V" else fringe_class(idx, spelling, reading, parts)
        if why:
            flags[spelling] = FRINGE | TITLE if why == "title" else FRINGE
    return flags


# --- A katakana word JMdict doesn't list ------------------------------------------------------------------- #

def unlisted(entries, compounds):
    """{spelling: UNLISTED} for the compounds spelled in katakana alone that JMdict has as no headword and no reading
    (ビルデ = ビル + デ, ローデ, デリア: a piece of a foreign name deep in the frequency lists' tails), written with its ・
    or without (イート・イン is イートイン). Such a compound gives way to a katakana name around it (ビルデイング stays one
    word); one JMdict lists (フジテレビ, イートイン) is a word, and stays one inside a longer run. `compounds` is the
    compound table (its keys are read)."""
    by_kanji, by_kana = index(entries)
    listed = {form.replace("・", "") for form in list(by_kanji) + list(by_kana)}
    return {spelling: UNLISTED for spelling in compounds if _KATAKANA.match(spelling) and spelling not in listed}


# --- A noun a verb's stem may stand in --------------------------------------------------------------------- #

def lists_as_noun(idx, spelling, reading):
    """Does JMdict list `spelling` read `reading` as a noun — some sense a common noun, an adverbial or temporal one,
    or one used as a suffix (出来損ない, 待ち時間, 思い通り)? The build lets a verb's stem stand in such a compound
    where the text writes one there (立ち[立つ] + 位置)."""
    return any(NOUN_POS.intersection(sense["pos"]) for entry in lookup(idx, spelling, reading)
               for sense in entry["senses"])


# --- お / ご words ------------------------------------------------------------------------------------ #

def _gloss_key(gloss):
    """A gloss compared case- and bracket-free: "(one's) side" is "side"."""
    return " ".join(_BRACKETS.sub(" ", gloss).lower().split())


def _bare(spelling, reading):
    """-> [(bare spelling, bare reading)] for an お / ご / 御 word: the word after its prefix, read as the whole
    reads after the prefix's own reading (御守り おまもり -> 守り まもり; 御社 おんしゃ -> 社 しゃ)."""
    read = hiragana(reading)
    for prefix in OGO_PREFIXES.get(spelling[:1], ()):
        if read.startswith(prefix) and len(read) > len(prefix) and len(spelling) > 1:
            yield spelling[1:], read[len(prefix):]


def word_entries(idx, spellings, readings):
    """The entries of one word written several ways — each spelling's (`lookup`), except that a kana spelling's count
    only where they hold one of the word's kanji spellings too (ごえん is 御縁 here, never 誤嚥 'aspiration')."""
    kanji = [s for s in spellings if _HAN.search(s)]
    found = []
    for spelling in spellings:
        for entry in lookup(idx, spelling, readings[spelling]):
            if entry in found:
                continue
            if kanji and not _HAN.search(spelling) and not {keb for keb, *_ in entry["kanji"]}.intersection(kanji):
                continue
            found.append(entry)
    return found


def own_senses(idx, spellings, readings):
    """-> (the senses that make an お / ご word a word of its own (§ above), its entries, its bare word's entries),
    for one word written as `spellings` ({spelling: reading} in `readings`). The bare word is read from the word's
    kanji spellings where it has any (a kana one, まもり, would meet every homophone)."""
    entries = word_entries(idx, spellings, readings)
    kanji = [s for s in spellings if _HAN.search(s)] or list(spellings)
    bare = []
    for spelling in kanji:
        for word, read in _bare(spelling, readings[spelling]):
            bare.extend(e for e in lookup(idx, word, read) if e not in bare and e not in entries)
    bare_glosses = {_gloss_key(g) for e in bare for s in e["senses"] if "abbr" not in s["misc"] for g in s["gloss"]}
    own = [s for e in entries for s in e["senses"]
           if not POLITE_TAGS.intersection(s["misc"]) and not bare_glosses.intersection(map(_gloss_key, s["gloss"]))]
    return own, entries, bare


def ogo_exceptions(entries, candidates):
    """{spelling: [lemma, reading]} — the お / ご words of `candidates` that JMdict lists as words of their own.
    `candidates` is {spelling: [lemma, reading]}, every spelling of one word under one lemma (the build's groups);
    a word is decided once, for all its spellings, and every spelling of a word that passes comes back as given."""
    idx, groups = index(entries), defaultdict(list)
    for spelling, (lemma, _reading) in candidates.items():
        groups[lemma].append(spelling)
    out = {}
    for spellings in groups.values():
        if own_senses(idx, spellings, {s: candidates[s][1] for s in spellings})[0]:
            out.update((s, list(candidates[s])) for s in spellings)
    return out


# --- The lists for the user -------------------------------------------------------------------------- #

def _senses_line(entries, limit=2):
    """One line of what JMdict says: each sense's parts of speech, marks and first glosses."""
    out = []
    for sense in [s for e in entries for s in e["senses"]][:limit]:
        marks = ",".join(sense["pos"] + sense["misc"])
        out.append(f"{'; '.join(sense['gloss'][:2])} ({marks})")
    return " / ".join(out)


def _why_not(entries, own):
    if not entries:
        return "JMdict doesn't list it"
    if all(POLITE_TAGS.intersection(s["misc"]) for e in entries for s in e["senses"]):
        return "every sense is the polite / honorific / humble word"
    return "every sense is polite or has a gloss the bare word has"


def report(entries, compounds, candidates, path=REPORT, jmdict=JMDICT):
    """Write the lists for the user (Markdown): every fringe compound by class, and every お / ご candidate joined or
    left, each with what JMdict says."""
    from datetime import date
    idx = index(entries)
    lines = [f"# What JMdict says about the joined words ({date.today()})", "",
             f"JMdict created {created(jmdict) or '(no date)'} — {len(entries):,} entries. "
             f"{len(compounds):,} compounds and {len(candidates):,} お / ご spellings read.", ""]
    classes = defaultdict(list)
    for spelling, (_lemma, reading, kind, _flags, parts) in sorted(compounds.items()):
        why = None if kind == "V" else fringe_class(idx, spelling, reading, parts)
        if why:
            classes[why].append((spelling, reading, _senses_line(lookup(idx, spelling, reading))))
    lines += ["## The fringe — behind \"Phrases and titles as one word\"", "",
              f"{sum(map(len, classes.values())):,} of {len(compounds):,} compounds: "
              + f"{len(classes['title']):,} titles, {len(classes['phrase']):,} phrases, "
              f"{len(classes['prefix']):,} a prefix + a word; a loanword never (its parts are pieces of a foreign "
              "word).", ""]
    for why, heading in (("title", "Titles — JMdict knows them only as the name of a work, product, company or "
                                   "organization"),
                         ("phrase", "Phrases — JMdict lists them, never as a noun, and no idiom or loanword"),
                         ("prefix", "A prefix + a word — the first part is first of all a JMdict prefix")):
        lines += [f"### {heading} ({len(classes[why]):,})", "", "| word | reading | JMdict |", "| :-- | :-- | :-- |"]
        lines += [f"| {s} | {r} | {j} |" for s, r, j in classes[why]]
        lines.append("")
    groups = defaultdict(list)
    for spelling, (lemma, _reading) in candidates.items():
        groups[lemma].append(spelling)
    joined, left = [], []
    for lemma, spellings in sorted(groups.items()):
        own, word, _bare_entries = own_senses(idx, spellings, {s: candidates[s][1] for s in spellings})
        name = " / ".join(spellings)
        if own:
            joined.append(f"| {name} | {'; '.join(own[0]['gloss'][:2])} "
                          f"({','.join(own[0]['pos'] + own[0]['misc'])}) |")
        else:
            left.append(f"| {name} | {_why_not(word, own)} — {_senses_line(word, 1) or '-'} |")
    lines += ["## お / ご words the share leaves split", "",
              f"{len(groups):,} words: {len(joined):,} join (JMdict lists a meaning the bare word lacks), "
              f"{len(left):,} stay a prefix + a word.", "",
              f"### Joined ({len(joined):,}) — the sense that makes each a word of its own", "",
              "| word | own sense |", "| :-- | :-- |"] + joined
    lines += ["", f"### Left as a prefix + a word ({len(left):,})", "", "| word | why |", "| :-- | :-- |"] + left
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Write the fringe and お / ご lists JMdict decides (debug/, local).")
    parser.add_argument("--jmdict", default=JMDICT, help="JMdict_e.gz or JMdict_e.xml")
    parser.add_argument("--compounds", help="a JSON file {spelling: [lemma, reading, kind, flags, parts]} "
                                            "(default: app/reference_data.py's compound table)")
    parser.add_argument("--ogo", help="a JSON file {spelling: [lemma, reading]} of お / ご words the share left split")
    parser.add_argument("--out", default=REPORT)
    args = parser.parse_args()
    if args.compounds:
        with open(args.compounds, encoding="utf-8") as f:
            compounds = json.load(f)
    else:
        from app import reference_data
        compounds = getattr(reference_data, "compound_joins", dict)()
    candidates = {}
    if args.ogo:
        with open(args.ogo, encoding="utf-8") as f:
            candidates = json.load(f)
    print(f"Reading {args.jmdict} (JMdict created {created(args.jmdict)})...")
    entries = load(args.jmdict)
    print(f"  {len(entries):,} entries; wrote {report(entries, compounds, candidates, args.out, args.jmdict)}")


if __name__ == "__main__":
    main()

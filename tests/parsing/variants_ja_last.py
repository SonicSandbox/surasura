"""The last small parsing round (lane LR, 2026-09-30) — five rules judged on the suite before anything in app/ changes.
Each patches the pipeline where the app looks it up, so every caller (the tokenizer, the known words, U9's see-through,
the sentence dictionary, パターン) reads text through it.

    verb-aux-raw / -common / -unit / verb-aux
        #35: a verb + auxiliaries the tagger reads where JMdict lists the whole as a word of its own (くだらない =
        下る + ない, 思いがけない, 知らせる) is that word. -raw: every such spelling (a kana one only for an entry JMdict
        marks usually written in kana, or with no kanji form); -common: and JMdict marks the spelling common (a priority
        tag: ichi / news / spec / gai / nf); -unit: and the lists rank it about as often as the shared set's text holds the
        run (R7's unit test, ratio <= 8, the phrase rows' gate); verb-aux: the lean (see the variant).
    word-particles-raw / -unit / word-particles
        #36: a word + particles (いつも = いつ + も, ちなみに = 因み + に) or particles opening a clause (でも = で + も)
        that JMdict lists as an adverb or a conjunction (never an entry it files only as an expression) is that word.
    surname-name / surname-name-floor
        #40: a common word JMnedict lists as a surname, 2+ characters with a kanji, standing right before a name — a
        person's name the tagger reads, a katakana word it doesn't know, or a spelling UniDic lists as a given name
        (御行) — is the surname, not the common word (朽木 キュウボク 'rotten wood' in 朽木ルキア). -floor: only a full
        name the library holds 3+ times (names may use the library).
    pronoun-bases
        #19: a pronoun may carry a suffix in Part A (何様, 俺様, どちら様, お前さん, それなり), the join table patched in
        memory with the headwords that adds — the plural guard first taught to read 方 by the list's reading (あなた方
        アナタガタ never joins).
    katakana-stretch-drop / -any
        #20: a katakana word stretched inside — two or more marks, a wave dash, a dash run (today read with one ー) — that
        is no word with one ー is read without it when that is a word (ジャ～ック is ジャック); -any: whatever it gives.

All read data/variants/lr_last.json (lr_last_data.py beside it wrote it from JMdict, JMnedict, the lists and lane LR's
pass over the shared set's text).
"""
import json
import os
import re

from app import analyzer, names, reference_data
from app.unicode_ranges import HAN
from tests.parsing import harness
from tests.parsing.harness import Token, patched
from tests.parsing.variants import after_join, variant

DATA = os.path.join(harness.DATA, "variants", "lr_last.json")
_DATA = {}
_read = analyzer._read
UNIT_RATIO = 8


def data():
    """lr_last.json (lr_last_data.py) — read once, when a variant is entered."""
    if not _DATA:
        if not os.path.isfile(DATA):
            raise FileNotFoundError(f"{DATA} is missing — PYTHONIOENCODING=utf-8 python "
                                    "tests/parsing/data/variants/lr_last_data.py")
        with open(DATA, encoding="utf-8") as handle:
            _DATA.update(json.load(handle))
        _DATA["surname_set"] = frozenset(_DATA.get("surnames", ()))
        _DATA["given_set"] = frozenset(_DATA.get("given", ()))
        _DATA["full_name_set"] = frozenset(_DATA.get("full_names", ()))
    return _DATA


def _spaced(word):
    return bool(getattr(word, "white_space", ""))


def join_runs(words, runs, table):
    """`words` with each (i, end, key) of `runs` joined into the one word `table[key]` names."""
    if not runs:
        return words
    out, last = [], 0
    for i, end, key in runs:
        e = table[key]
        out.extend(words[last:i])
        out.append(analyzer._joined(words[i:end], key, e["pos1"], (e["lemma"], e["reading"])))
        last = end
    out.extend(words[last:])
    return out


# --- #35: a verb + auxiliaries JMdict lists whole ---------------------------------------------------------------- #
def verb_aux_runs(words, table):
    """(i, end, key) of each verb + auxiliaries run whose key `table` holds, the longest from the left: a word that
    conjugates by the verb and the auxiliaries as read, the last in its dictionary form (知ら + せ -> 知らせる, くだら +
    なかっ -> くだらない); any other word as written (思わず, 思わぬ)."""
    out, n, i = [], len(words), 0
    while i < n:
        w, found = words[i], None
        if w.feature.pos1 == "動詞" and not w.is_unk:
            j = i + 1
            while j < n and words[j].feature.pos1 == "助動詞" and not _spaced(words[j]):
                j += 1
            if j > i + 1:
                for end in range(j, i + 1, -1):
                    written = "".join(_read(x) for x in words[i:end - 1])
                    last = words[end - 1]
                    key = written + _read(last)                 # a word that doesn't conjugate: as written
                    e = table.get(key)
                    if e is None or e["match"] != "surface":
                        key = written + (last.feature.orthBase or _read(last))
                        e = table.get(key)
                        if e is not None and e["match"] != "base":
                            e = None
                    if e is not None:
                        found = (i, end, key)
                        break
        if found:
            out.append(found)
            i = found[1]
        else:
            i += 1
    return out


def _gated(name, gate):
    return {k: e for k, e in data()[name].items() if gate(e)}


def unit(e):
    """R7's unit test as the phrase rows take it: JPDB 2024 (else Jiten) ranks the whole at most UNIT_RATIO times rarer
    than the rank its runs have among the shared set's words."""
    listed = e["jpdb"] or e["jiten"]
    return listed is not None and e.get("rank") is not None and listed / e["rank"] <= UNIT_RATIO


def unit_both(e):
    """R7 on both lists: JPDB 2024 AND Jiten each rank the whole within UNIT_RATIO of the run's rank in the text (Jiten
    alone takes greedy matches as words: それを, 何を, ここに)."""
    return (e["jpdb"] is not None and e["jiten"] is not None and e.get("rank") is not None
            and max(e["jpdb"], e["jiten"]) / e["rank"] <= UNIT_RATIO)


NEGATIVE = frozenset(("ない", "ず"))                          # UniDic's lemmas: ない; ず for ず / ぬ / ん
VOICE = frozenset(("せる", "させる", "れる", "られる"))
# The light verbs (scripts/build_phrase_data.LIGHT): する / なる / ある / いる / できる and their polite forms — される
# and させる are する's passive and causative, grammar, never a word of their own here.
LIGHT = frozenset(("為る", "成る", "有る", "居る", "出来る", "為さる", "致す", "御座る"))


def _shape(e, auxes):
    return all(a in auxes for a in e["aux"]) and e.get("verb", [""])[0] not in LIGHT


def verb_aux_neg(e):
    """JMdict marks the spelling common, and the auxiliaries are the negative (くだらない, 思いがけない, 思わず)."""
    return e["common"] and _shape(e, NEGATIVE)


def verb_aux_voice(e):
    """JMdict marks the spelling common, and the auxiliaries are voice (知らせる, 済ませる, 思われる)."""
    return e["common"] and _shape(e, VOICE)


def verb_aux_lean(e):
    """The lean (a question for the user): JMdict marks the spelling common, and the auxiliaries make a word — the
    negative or voice — never only tense, politeness or aspect (変わった, しまった, すみません), never after a light
    verb (される, させる)."""
    return e["common"] and _shape(e, NEGATIVE | VOICE)


def curated(e):
    """JMdict's editors list the spelling as a word (a priority tag of a curated word list: ichi — the
    Ichimango goi bunrui shuu — or spec), not only as a frequent string of the news (news / nf): 変わらない 'constant'
    (news1) is 変わる's negative in nearly every use; つまらない (ichi1), 知らせる (ichi1) are words."""
    return e.get("curated", False)


def verb_aux_curated(e):
    """The lean, refined: a curated word (`curated`), the negative or voice, never after a light verb."""
    return curated(e) and _shape(e, NEGATIVE | VOICE)


CAUSATIVE = frozenset(("せる", "させる"))


def verb_aux_curated_active(e):
    """The curated lean without the passive: a curated word, the negative or the causative (知らせる, 済ませる), never
    the passive (思われる, 救われる: in most uses the verb's own passive, by someone)."""
    return curated(e) and _shape(e, NEGATIVE | CAUSATIVE)


VERB_AUX_GATES = {"raw": lambda e: True, "common": lambda e: e["common"], "unit": unit, "neg": verb_aux_neg,
                  "voice": verb_aux_voice, "lean": verb_aux_lean, "curated": verb_aux_curated,
                  "curated-active": verb_aux_curated_active}


_KANA_ONLY = re.compile("^[ぁ-ゟァ-ヿ]+$")


def in_place(words, run, table):
    """A run joins where its word stands as the dictionary says it does: a word JMdict marks usually written in kana
    only when the text writes it so (済まない is 済む's negative, すまない 'sorry' — as a usually-kana pre-noun phrase
    counts only in kana), a pre-noun word only before a noun (いらぬ心配, never いらぬ！)."""
    i, end, key = run
    e = table[key]
    if e.get("uk") and not _KANA_ONLY.match("".join(w.surface for w in words[i:end])):
        return False
    if e["pos1"] == "連体詞" and not (end < len(words) and words[end].feature.pos1 in ("名詞", "代名詞")):
        return False
    return True


def _verb_aux_variant(gate, placed=False):
    table = _gated("verb_aux", VERB_AUX_GATES[gate])

    def post(words):
        runs = verb_aux_runs(words, table)
        if placed:
            runs = [r for r in runs if in_place(words, r, table)]
        return join_runs(words, runs, table)
    with after_join(post):
        yield


@variant("verb-aux-raw", "#35: every verb + auxiliaries run JMdict lists whole is that word (a kana spelling only for "
         "an entry usually written in kana) — no gate, the rule's reach.")
def _verb_aux_raw():
    yield from _verb_aux_variant("raw")


@variant("verb-aux-common", "#35, JMdict marking the spelling a common word (ichi / news / spec / gai / nf).")
def _verb_aux_common():
    yield from _verb_aux_variant("common")


@variant("verb-aux-unit", "#35, the lists ranking it about as often as general text holds the run (R7, ratio <= 8).")
def _verb_aux_unit():
    yield from _verb_aux_variant("unit")


@variant("verb-aux-neg", "#35, JMdict common and the negative only (くだらない, つまらない, 思いがけない, 思わず).")
def _verb_aux_neg():
    yield from _verb_aux_variant("neg")


@variant("verb-aux-voice", "#35, JMdict common and voice only (知らせる, 済ませる, 待たせる, 思われる).")
def _verb_aux_voice():
    yield from _verb_aux_variant("voice")


@variant("verb-aux-curated", "#35: a curated JMdict word (ichi / spec), the negative or voice, never after a light "
         "verb; a usually-kana word only written in kana, a pre-noun word only before a noun.")
def _verb_aux_curated():
    yield from _verb_aux_variant("curated", placed=True)


@variant("verb-aux-curated-active", "#35, curated, the negative or the causative only (never the passive).")
def _verb_aux_curated_active():
    yield from _verb_aux_variant("curated-active", placed=True)


@variant("verb-aux", "#35 as leaned: JMdict marks it common, and its auxiliaries make a word (the negative, voice) — "
         "never tense, politeness or aspect alone.")
def _verb_aux():
    yield from _verb_aux_variant("lean")


# --- #36: a word + particles JMdict lists as an adverb or a conjunction ------------------------------------------ #
_CONTENT = frozenset(("名詞", "代名詞", "副詞", "形状詞", "連体詞", "接続詞", "感動詞"))
_BREAKS = frozenset(("補助記号", "空白"))
_CLOSERS = frozenset("」』）)】〕〉》］]｝}’”〟")       # a closing bracket or quote: a quoted name takes a particle


def _clause_start(words, i):
    """Nothing before words[i] on the line but punctuation that opens or separates (never a closing bracket or quote:
    『アラジン』でも is the title + で + も)."""
    if i == 0:
        return True
    prev = words[i - 1]
    return prev.feature.pos1 in _BREAKS and not (prev.surface and prev.surface[-1] in _CLOSERS)


def word_particle_runs(words, table):
    """(i, end, key) of each run — a word + up to three particles, or particles opening a clause (nothing before them
    on the line but punctuation: a case particle needs a word) — whose spelling `table` holds, longest from the left."""
    out, n, i = [], len(words), 0
    while i < n:
        w, found = words[i], None
        p1 = w.feature.pos1
        if (p1 in _CONTENT and not w.is_unk) or (p1 == "助詞" and _clause_start(words, i)):
            j = i + 1
            while j < n and j - i <= 3 and words[j].feature.pos1 == "助詞" and not _spaced(words[j]):
                j += 1
            for end in range(j, i + 1, -1):
                key = "".join(_read(x) for x in words[i:end])
                if key in table:
                    found = (i, end, key)
                    break
        if found:
            out.append(found)
            i = found[1]
        else:
            i += 1
    return out


def optional_particle(e):
    """An adverb + と (ポンと, ひょいと, ちらと): the と is optional and the word is the adverb's (CJ-1A keeps them apart;
    only a sound word ending in っ joins its と)."""
    return e.get("first_pos1") == "副詞" and e["aux"] == ["と"]


def word_particles_lean(e):
    """The lean (a question for the user): JMdict marks the spelling common, both lists rank it as a word about as often
    as the text holds the run (R7 on JPDB 2024 and Jiten), and it is no adverb + an optional と."""
    return e["common"] and unit_both(e) and not optional_particle(e)


def word_particles_narrow(e):
    """A narrower lean (a question for the user): a curated JMdict adverb or conjunction (ichi / spec), R7 on both
    lists, whose first word is a closed-class word — particles opening a clause (でも), a pronoun (いつも, それとも), an
    adverb with more than an optional と / に after it (どうにか; never すぐに, ちらと) — or a bound noun (因み in
    ちなみに); never a free noun's adverbial use (本当に is 本当 + に, ために ため + に)."""
    if not (curated(e) and unit_both(e)):
        return False
    first = e.get("first_pos1")
    if first in ("助詞", "代名詞"):
        return True
    if first == "副詞":
        return e["aux"] not in (["と"], ["に"])
    return bool(e.get("bound"))


def blocked(words, run):
    """Does a longer dictionary spelling hold the run here — on the tokens' bounds, reaching before or after it (か +
    どう + か is かどうか, an expression; それに + し + て + も それにしても)? Then the run is that spelling's piece."""
    i, end, key = run
    longer = data().get("blockers", {}).get(key)
    if not longer:
        return False
    longer = set(longer)
    n = len(words)
    for a in range(max(0, i - 3), i + 1):
        for b in range(end, min(n, end + 4) + 1):
            if (a < i or b > end) and "".join(_read(w) for w in words[a:b]) in longer:
                return True
    return False


WORD_PARTICLE_GATES = {"raw": lambda e: True, "unit": unit, "common": lambda e: e["common"],
                       "both": unit_both, "lean": word_particles_lean, "narrow": word_particles_narrow}


def _word_particle_variant(gate, longest=False):
    table = _gated("word_particles", WORD_PARTICLE_GATES[gate])

    def post(words):
        runs = word_particle_runs(words, table)
        if longest:
            runs = [r for r in runs if not blocked(words, r)]
        return join_runs(words, runs, table)
    with after_join(post):
        yield


@variant("word-particles-raw", "#36: every word + particles run (or particles opening a clause) JMdict lists as an "
         "adverb or a conjunction is that word — no gate, the rule's reach.")
def _word_particles_raw():
    yield from _word_particle_variant("raw")


@variant("word-particles-unit", "#36, the lists ranking it about as often as general text holds the run (R7: JPDB "
         "2024, else Jiten).")
def _word_particles_unit():
    yield from _word_particle_variant("unit")


@variant("word-particles-common", "#36, JMdict marking the spelling common.")
def _word_particles_common():
    yield from _word_particle_variant("common")


@variant("word-particles", "#36 as leaned: JMdict common, R7 on both lists, never an adverb + an optional と.")
def _word_particles():
    yield from _word_particle_variant("lean")


@variant("word-particles-narrow-longest", "#36, narrow, and a run inside a longer dictionary spelling (かどうか, "
         "それにしても, よくも悪くも, なんとなく) stays that spelling's pieces.")
def _word_particles_narrow_longest():
    yield from _word_particle_variant("narrow", longest=True)


@variant("word-particles-narrow", "#36, narrower: a curated JMdict adverb or conjunction (R7 on both lists) whose first "
         "word is a closed-class word (particles opening a clause, a pronoun, an adverb with more than an optional "
         "と / に) or a bound noun (因み): いつも, ちなみに, どうにか, でも, それとも — never 本当に, ために.")
def _word_particles_narrow():
    yield from _word_particle_variant("narrow")


# --- #40: a surname read as a common word before a name ---------------------------------------------------------- #
_KATAKANA = re.compile(r"^[ァ-ヺー-ヾ]+$")
_HAN_RE = re.compile(f"[{HAN}]")


def _listed(spelling, pos4):
    """UniDic's own entry for `spelling` as a person's name of the kind `pos4` (姓 a surname, 名 a given name)."""
    for f in names._listed_as(spelling):
        if f.pos2 == "固有名詞" and f.pos3 == "人名" and f.pos4 == pos4:
            return f
    return None


def name_kind(v, d):
    """What makes words[i + 1] a name (or None): the tagger reads a person's name; a katakana word it doesn't know (or
    a name the names layers made); a spelling UniDic lists as a given name, read as a common word; a JMnedict given
    name with a kanji that no list carries as a word."""
    f = v.feature
    if f.pos2 == "数詞":
        return None
    text = _read(v)
    if isinstance(v, analyzer.JoinedWord) and v.is_unk:
        return "names-layer"                    # a name app/names.py made one word (一護, グリムジョー)
    if f.pos2 == "固有名詞" and f.pos3 == "人名":
        # a given name; never a surname (a surname + a surname is no full name: 後々 + 臼井), and never a foreign name
        # the dictionary knows (神の御子 + イエス, 第三皇子 + クロヴィス: a title before a Western given name)
        return "person" if f.pos4 != "姓" and not _KATAKANA.match(text) else None
    if _KATAKANA.match(text):
        return "katakana" if v.is_unk else None
    if _HAN_RE.search(text) and f.pos1 == "名詞":
        if _listed(text, "名") is not None:
            return "given-listed"
        if text in d["given_set"]:
            return "given-jmnedict"
    return None


def surname_runs(words, d, floor=False):
    """(i, kind) of each common word JMnedict lists as a surname (2+ characters, a kanji) right before a name."""
    out = []
    for i in range(len(words) - 1):
        w, v = words[i], words[i + 1]
        f = w.feature
        if w.is_unk or f.pos1 != "名詞" or f.pos2 in ("固有名詞", "数詞") or _spaced(v):
            continue
        s = _read(w)
        if len(s) < 2 or s not in d["surname_set"] or not _HAN_RE.search(s):
            continue
        kind = name_kind(v, d)
        if kind is None:
            continue
        if floor and s + _read(v) not in d["full_name_set"]:
            continue
        out.append((i, kind))
    return out


def as_name(w, pos4):
    """`w` read as the person's name it spells: UniDic's own entry for it when it lists one (朽木: クツキ), else a name
    its dictionary lacks — the spelling as the lemma, no reading (as app/names.py keys one)."""
    s = _read(w)
    f = _listed(s, pos4)
    if f is None:
        f = w.feature._replace(pos1="名詞", pos2="固有名詞", pos3="人名", pos4=pos4, lemma=s, lForm="", kana="",
                               pron="", pronBase="", kanaBase="", form="", formBase="", orth=s, orthBase=s,
                               cType="*", cForm="*")
    return Token(w.surface, f, False)


def join_surnames(words, floor=False):
    d = data()
    runs = surname_runs(words, d, floor)
    if not runs:
        return words
    out = list(words)
    for i, kind in runs:
        out[i] = as_name(words[i], "姓")
        if kind == "given-listed":
            out[i + 1] = as_name(words[i + 1], "名")
    return out


@variant("surname-name", "#40: a common word JMnedict lists as a surname right before a name (a person's name the tagger "
         "reads, a katakana word it doesn't know, a spelling UniDic lists as a given name) is the surname: 朽木ルキア.")
def _surname_name():
    with after_join(join_surnames):
        yield


@variant("surname-name-floor", "#40, only for a full name the library holds 3+ times (names may use the library).")
def _surname_name_floor():
    with after_join(lambda words: join_surnames(words, floor=True)):
        yield


# --- #19: pronoun bases in Part A ---------------------------------------------------------------------------------- #
def _pronoun(word):
    return not word.is_unk and word.feature.pos1 == "代名詞"


def join_affix_runs_pronouns(words, joins):
    """analyzer._join_affix_runs, with a pronoun a base for the suffixes after it (何 + 様, お前 + さん) — never after a
    prefix."""
    out, i, n = [], 0, len(words)
    _is_base, _suffixed, _NOUN_SUFFIXES = analyzer._is_base, analyzer._suffixed, analyzer._NOUN_SUFFIXES
    while i < n:
        w = words[i]
        f = w.feature
        found = None
        if f.pos1 == "接頭辞":
            if (i + 1 < n and _is_base(words[i + 1], honorific=f.lemma == "御")
                    and not (i and words[i - 1].feature.pos2 == "数詞")):
                base = words[i + 1]
                found = _suffixed(words, i + 1, _read(w) + _read(base),
                                  "名詞" if base.feature.pos1 == "動詞" else base.feature.pos1, joins)
                if found and f.lemma == "御" and _is_base(base):
                    own = _suffixed(words, i + 1, _read(base), base.feature.pos1, joins)
                    if own and own[0] > found[0]:
                        found = None
        elif (i + 1 < n and (words[i + 1].feature.pos1 == "接尾辞" or _read(words[i + 1]) in _NOUN_SUFFIXES)
                and (_is_base(w) or _pronoun(w)) and not (i and words[i - 1].feature.pos2 == "数詞")):
            found = _suffixed(words, i, _read(w), "代名詞" if _pronoun(w) else f.pos1, joins)
        if found and found[0] > i:
            end, key, pos1 = found
            out.append(analyzer._joined(words[i:end + 1], key, pos1, joins[key]))
            i = end + 1
        else:
            out.append(w)
            i += 1
    return out


def plural_suffix(tokens, reading):
    """Does a run whose last piece is a plural suffix by the list's reading end it (あなた + 方, アナタガタ)?"""
    return bool(tokens) and analyzer._plural(_read(tokens[-1]), reading)


def suffixed_plural_guard(words, end, key, pos1, joins):
    """analyzer._suffixed, a word the table holds refused where its last suffix is a plural by the list's reading — and
    a nominalizer (さ, み) never after a pronoun, as never after a な-word (これ + さ is the particle さ: これさ)."""
    def holds(k, last):
        return k in joins and not analyzer._plural(last, joins[k][1])
    found = (end, key, pos1) if key in joins else None
    while end + 1 < len(words):
        s = words[end + 1]
        f = s.feature
        if f.pos1 == "接尾辞":
            category, spelled = analyzer._SUFFIX_POS.get(f.pos2), f.orthBase or _read(s)
        elif f.pos1 == "名詞" and _read(s) in analyzer._NOUN_SUFFIXES:
            category, spelled = "名詞", _read(s)
        else:
            break
        if (category is None or _read(s) in analyzer._NEVER_JOINED or f.lemma in analyzer._NEVER_JOINED
                or (f.lemma == "方" and f.lForm == "ガタ")
                or (_read(s) in analyzer._NOMINALIZERS
                    and (pos1 in ("形状詞", "代名詞") or words[end].feature.pos3 == "形状詞可能"))):
            break
        key, pos1, end = key + spelled, category, end + 1
        if holds(key, _read(s)):
            found = (end, key, pos1)
    return found


@variant("pronoun-bases", "#19: a pronoun may carry a suffix (何様, 俺様, お前さん, それなり) — the join table with the "
         "headwords that adds, the plural guard reading 方 by the list's reading (あなた方 never joins).")
def _pronoun_bases():
    merged = {**reference_data.affix_joins(), **{w: tuple(e) for w, e in data()["pronoun_joins"].items()}}
    with patched(reference_data, "affix_joins", lambda: merged), \
            patched(analyzer, "_join_affix_runs", join_affix_runs_pronouns), \
            patched(analyzer, "_suffixed", suffixed_plural_guard):
        yield


# --- #20: a stretched katakana word the dictionary lacks --------------------------------------------------------- #
_KATAKANA_LETTER = re.compile("[ァ-ヺヽ-ヿ]")
_KATAKANA_RUN = re.compile("[ァ-ヺー-ヿ]")
_STRETCH_CHARS = frozenset("ー〜～─━―—")


def known_katakana(spelling):
    """A katakana spelling the dictionaries know as one word: a headword of the lists, or one the tagger reads alone as
    one word it knows."""
    listed = names.katakana_headwords()
    return (listed is not None and spelling in listed) or names._read_whole(spelling) is not None


def stretch_drops(text, read, at, need_known=True):
    """The indices of `text` holding a katakana word's stretch to read as nothing (§ the variant)."""
    drop = set()
    for k, ch in enumerate(read):
        if ch != "ー" or not 0 < k < len(read) - 1 or text[at[k]:at[k + 1]] == "ー":
            continue                                    # no stretch here: one ー as written is the word's own
        if not (_KATAKANA_LETTER.match(read[k - 1]) and _KATAKANA_LETTER.match(read[k + 1])):
            continue
        a, b = k, k + 1
        while a > 0 and _KATAKANA_RUN.match(read[a - 1]):
            a -= 1
        while b < len(read) and _KATAKANA_RUN.match(read[b]):
            b += 1
        if known_katakana(read[a:b]):
            continue
        if need_known and not known_katakana(read[a:k] + read[k + 1:b]):
            continue
        drop.update(range(at[k], at[k + 1]))
    return drop


def _stretch_variant(need_known):
    real = analyzer.Tagger.__call__

    def call(self, text, unread=()):
        if not unread and not _STRETCH_CHARS.isdisjoint(text):
            read, at = analyzer.tagger_text(text)
            if at is not None:
                drop = stretch_drops(text, read, at, need_known)
                if drop:
                    read2, at2 = analyzer.tagger_text(text, drop)
                    if "ー" in read2 and analyzer._STRETCH_DROPPED_RE.search(read2):
                        drop |= analyzer._lone_marks(read2, at2, self._tagger(read2))
                    return real(self, text, drop)
        return real(self, text, unread)
    return patched(analyzer.Tagger, "__call__", call)


@variant("katakana-stretch-drop", "#20: a katakana word stretched inside (two or more marks, a wave dash, a dash run) "
         "that is no word with one ー is read without the mark when that makes a word (ジャ～ック is ジャック).")
def _katakana_stretch_drop():
    with _stretch_variant(True):
        yield


@variant("katakana-stretch-drop-any", "#20, the mark dropped whenever one ー makes no word, whatever the word without "
         "it is.")
def _katakana_stretch_drop_any():
    with _stretch_variant(False):
        yield

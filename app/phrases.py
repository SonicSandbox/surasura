"""Idioms and set phrases on the list — the dictionary's set phrases, found in the words a sentence already has.

Why this exists
---------------
The tokenizer cuts text into words and never joins a phrase: 気がする is 気 + が + する, 腑に落ちる is 腑 + に + 落ちる,
もしかしたら is もしか + する + た. That is right for counting words — every word keeps its own row — but it means the
list could offer the pieces of an idiom, never the idiom itself. With Settings -> Language & Parsing -> "Idioms and set
phrases on your list" on (logic.phrase_rows), the analyzer looks for JMdict's set phrases in the words it already has
and gives each phrase the library meets as often as the list's cut-off asks a row of its own.

A phrase is found by its words' lemmas, so any form of it counts: 気がついた, 気が付いて and 気がつく are all 気が付く,
and 目を輝かせて is 目を輝かせる. But a phrase that ends in a form of its own — もしかしたら's たら, そういうことなら's
なら, never the dictionary form た or だ; ごめんなさい's なさい, ざまあみろ's みろ, 何にせよ's せよ, だけでなく's なく — is
that form only: そういうことだ, 何にする and だけじゃない are other expressions (`fixed_form`). A phrase JMdict classes only as a pre-noun adjectival (ああいう, こういう, ひどすぎる — adj-pn) stands
only before a word of its own (ああいう人, ああいうの), never inflected: ああ言って is the words 'say so'
(`before_a_noun`) — and one JMdict says is usually written in kana (そういった, どういう) only as written in kana:
with the verb's kanji, そう言ったのは is 'that he said so'. At each place in a sentence the longest phrase wins and the
search goes on after it (no overlaps). A phrase whose words stand on both sides of a comma or any other mark the
tokenizer dropped (気が、付いた), or that ends in another form than its own, is no phrase there: the next shorter one at
that place is tried instead.

Each word of a phrase has a role: grammar (a particle, an ending, a prefix or suffix, an auxiliary verb after て), a
light verb or adjective (する, なる, ある, いる, できる, ない, いい), or a real word — and a real word that lives only
inside the phrase (腑 in 腑に落ちる: JPDB 2024 ranks it alone rarer than the phrase) is learned with the phrase. A phrase
is ready to learn once every other real word in it is known (`waiting`).

A grammar expression JMdict lists (かもしれない, として, について, なければならない — `Phrase.grammar`) is a row of its
own the same way, learned as one unit: every word in it that isn't grammar is the expression's there (知れる in
かもしれない gives its use to the row; 気心が知れる is 知れる's), and Connect sends it as it sends grammar words. One ending
in a verb JMdict doesn't conjugate is the expression only uninflected before a word of its own (`AS_WRITTEN`: という人, never
と言った); one ending in て is none before an auxiliary verb (`TE_AUXILIARIES`: ついている is 付く); one opening with
the stem よう (ようにする, ようになる: after a verb) is none right after の (口のようにして is the simile 'like').

The phrases themselves are app/phrase_data.py, built from JMdict by scripts/build_phrase_data.py. Pure: no tkinter,
no settings, no tagger — the Rarity slider's process counts phrases with it too, and nothing imports it while the
switch is off.
"""

import functools
import re
import unicodedata
from collections import namedtuple
from itertools import compress

from app.unicode_ranges import HAN

# Each word's role in its phrase: a real word ("c"), a real word that lives only inside the phrase ("b", learned with
# it), a light verb or adjective ("l") or grammar ("g").
CONTENT, BOUND, LIGHT, GRAMMAR = "c", "b", "l", "g"

Phrase = namedtuple("Phrase", "key readings roles display word reading prenoun grammar", defaults=(0, 0))
Phrase.__doc__ = """One set phrase: `key` its words' lemmas, `readings` theirs (UniDic lForm), `roles` one letter per
word (above), `display` the dictionary's commonest spelling; `word` and `reading` are the list row's Word and Reading —
the lemmas joined (気が付く, 若しか為るた) and the dictionary's reading of the spelling shown (キガツク, モシカシタラ);
`prenoun`: 1 when JMdict classes it only as a pre-noun adjectival, 2 when it also says it is usually written in kana
(`before_a_noun`), else 0; `grammar`: 1 for a grammar expression (かもしれない, として: every word in it is the
expression's there, and Connect sends it as it sends grammar words — `connect_send_grammar`), 2 for one ending in a word
JMdict gives no conjugation class (という, に対する: found only as a pre-noun phrase is, `before_a_noun`), else 0."""

# The aspect verbs after a verb's て (UniDic lemmas): a grammar expression ending in て followed by one is no expression
# there — 本体についている is 付く 'be attached' + ている, never について 'about'. Only these: a verb that is also a word of
# its own after one (教師として来た, この件について見ていきましょう) leaves the expression standing.
TE_AUXILIARIES = frozenset(("居る", "有る", "仕舞う", "置く"))

# What `find` finds: bump it whenever a change here finds other phrases in the same words — the token store then counts
# every file's phrases again (token_index.Store._update_phrases), as it does for new phrase data, and reads the known
# words again (a known sentence's phrases are known: analyzer.load_known_words, Store._known_key). 6: a phrase ending
# in a form of its own is that form whatever its last word (`fixed_form`: ごめんなさい, 何にせよ, だけでなく), and
# `spellings` writes such a match as it is and keeps the voicing the text gives its last word (いつもどおり).
MATCHER_VERSION = 6

# Phrase.prenoun: a pre-noun adjectival JMdict says is usually written in kana (its "uk" on every sense).
KANA_ONLY = 2
# Phrase.grammar: a grammar expression ending in a verb JMdict gives no conjugation class — という, に対する — is the
# expression only uninflected, before a word of its own (という人, に対する考え), as a pre-noun phrase is: と言った is 言う 'said', and so is
# a sentence's hearsay 〜という。 (`before_a_noun`).
AS_WRITTEN = 2

_END = None          # the trie's mark for "a phrase ends here" (a lemma is never None)
_HIRAGANA = {code: code - 0x60 for code in range(0x30A1, 0x30F7)}      # katakana -> hiragana, for str.translate
_KANJI = re.compile(f"[{HAN}]")             # Unicode's Han (app/unicode_ranges.py)
_KANA = re.compile("[ぁ-ゖァ-ヶ]")             # a kana letter: what an ending is spelled in
_O_ROW = frozenset("おこごそぞとどのほぼぽもよろをょオコゴソゾトドノホボポモヨロヲョ")   # before う: a long vowel (そう)


def before_a_noun(phrase, tokens, start, end, text):
    """Does the match `tokens[start:end]` of a pre-noun adjectival (`Phrase.prenoun`: JMdict's adj-pn) stand as one —
    uninflected, its last word as its spelling ends (罪なき, 唾棄すべき) or in its dictionary form (どう言う), and straight
    before a word of its own (ああいう人, どう言う意味) or the 'one' の (ああいうの), a space between at most (ああいう
    毛色)? Never at the end of a sentence or before grammar (ああいうよ), never inflected (ああ言って). A word of its
    own: a lemma not in hiragana alone — UniDic spells every particle's and ending's lemma in hiragana, a noun's,
    adjective's or verb's almost always with a kanji or katakana. One JMdict says is usually written in kana
    (`prenoun` 2: そういった, ああいう, どういう) is the phrase only as written in kana: with the verb's kanji, そう言ったのは
    and そう言ったはず are nearly always 'said so', a relative clause — and the rarer kanji-written どう言う意味 is
    given up with them."""
    if end == len(tokens):
        return False
    if phrase.prenoun == KANA_ONLY and _KANJI.search("".join(token[2] for token in tokens[start:end])):
        return False
    last = tokens[end - 1]
    if not (phrase.display.endswith(last[2]) or last[2] == last[3]):
        return False
    lemma = tokens[end][0] or ""
    if lemma != "の" and all("ぁ" <= ch <= "ゟ" for ch in lemma):
        return False
    run = "".join(token[2] for token in tokens[start:end + 1])
    return run in text or run in "".join(text.split())


def fixed_form(phrase):
    """Can `phrase` end in a form of its own — its spelling not ending in its last word's dictionary form? Grammar
    (spelled in kana): its spelling doesn't end in that form (もしかしたら: た as たら; そういうことなら: だ as なら) —
    then only that form is the phrase. Any other word, which the spelling may write in kanji: its spelling ends in
    another kana than the lemma's reading does — an imperative or a stem of its own (ごめんなさい: なさる as なさい,
    ざまあみろ, 何にせよ: する as せよ, 何でもあり), a continuative (だけでなく: ない as なく) — and each match then says
    whether that is a form of the word it ends in (`own_form`: 手間が省ける is the potential 省ける's dictionary form,
    not 省く's). One ending in the dictionary form (目を輝かせる, 気に食わない, あっという間に, いい感じ — a noun) is the
    phrase in any form, as a real word's are."""
    last = phrase.readings[-1].translate(_HIRAGANA)
    if phrase.roles[-1] == GRAMMAR:
        return not phrase.display.endswith(last)
    end = phrase.display[-1:]
    return bool(_KANA.match(end)) and end.translate(_HIRAGANA) != last[-1:]


def own_form(phrase, base):
    """Does `phrase` (`fixed_form`) end in a form of its own of the word a match ends in — `base`, that word in its
    dictionary form as the text writes it? Grammar: always. Any other word: its spelling ends in another kana than
    `base` does (ごめんなさい's い, never なさる's る; だけでなく's く, never ない's い) — not where either ends in a
    kanji (すぐそば is 直ぐ傍: no ending to tell them apart), not the dictionary form (手間が省ける, 手間が省けた: the
    potential 省ける), and not a spelling that only writes the word shorter: a long vowel short (あっそ is あっそう) or
    a word's last kana left off (万全を期す is 万全を期する)."""
    if phrase.roles[-1] == GRAMMAR:
        return True
    display = phrase.display
    end, last = display[-1:], base[-1:]
    if not (_KANA.match(end) and _KANA.match(last)) or end.translate(_HIRAGANA) == last.translate(_HIRAGANA):
        return False
    head = base[:-1]
    if display.endswith(head) and (len(head) > 1 or (last in "うウ" and head in _O_ROW)):
        return False
    return True


def ends_as(phrase, surface):
    """Does a match whose last word the text spells `surface` end as `phrase`'s own form does (`own_form`)? Grammar:
    its spelling ends in `surface` (そういうことなら, never そういうことだ). Any other word: `surface` ends in the kana
    the spelling ends in, katakana read as hiragana — the form is the ending, the kanji or kana before it the writer's
    (あっち行け and あっちいけ; ちょい待ち, never ちょい待って)."""
    display = phrase.display
    if display.endswith(surface):
        return True
    return phrase.roles[-1] != GRAMMAR and surface[-1:].translate(_HIRAGANA) == display[-1:].translate(_HIRAGANA)


class PhraseSet:
    """Every phrase, and the trie that finds them in a sentence's words (`find`)."""

    def __init__(self, entries):
        """`entries`: [key, readings, roles, display, reading, prenoun, grammar] per phrase — key and readings
        `|`-joined, as app/phrase_data.py stores them; `reading` (the row's, the display's own) defaults to the words'
        readings run together, `prenoun` (0, 1 or 2) and `grammar` (0 or 1) to 0 — or Phrase tuples."""
        self.entries = []
        self._by_word = {}
        self._trie = self.firsts = self._fixed = None   # made on the first search (Generate mostly reads the store's)
        same = {}                           # one string per lemma, reading and roles, however many phrases hold it
        for entry in entries:
            if not isinstance(entry, Phrase):
                key, readings, roles, display = entry[:4]
                key = tuple([same.setdefault(s, s) for s in key.split("|")])
                readings = tuple([same.setdefault(s, s) for s in readings.split("|")])
                reading = entry[4] if len(entry) > 4 and entry[4] else "".join(readings)
                entry = Phrase(key, readings, same.setdefault(roles, roles), display, "".join(key), reading,
                               int(entry[5] or 0) if len(entry) > 5 else 0, int(entry[6] or 0) if len(entry) > 6 else 0)
            self._by_word.setdefault(entry.word, len(self.entries))
            self.entries.append(entry)

    def _search(self):
        """The trie `find` walks — each phrase's lemmas, one level a word — the lemmas a phrase starts with, and
        whether each phrase has a form of its own (`fixed_form`)."""
        if self._trie is None:
            trie = {}
            for index, entry in enumerate(self.entries):
                node = trie
                for lemma in entry.key:
                    node = node.setdefault(lemma, {})
                node[_END] = index
            self._fixed = [fixed_form(entry) for entry in self.entries]
            self._trie, self.firsts = trie, frozenset(trie)
        return self._trie

    def __len__(self):
        return len(self.entries)

    def entry(self, index):
        """The Phrase at `index` (what `find` returns)."""
        return self.entries[index]

    def of_word(self, word):
        """The index of the phrase whose list row is `word` (its lemmas joined: 気が付く), or None."""
        return self._by_word.get(word)

    def find(self, tokens, text):
        """[(start, end, index)] — the phrases in one sentence: `tokens` are the analyzer's (lemma, reading, surface,
        orth), `text` the sentence they were read from. Longest first at each place, then on after it; a match that
        ends in another form than the phrase's own (`fixed_form`), a pre-noun adjectival standing before no noun or
        written with a kanji where it is usually written in kana (`before_a_noun`), or a match whose surfaces are
        not one run of `text` (it stood across a mark the tokenizer dropped), is none, and the next shorter phrase at
        that place is tried. Most sentences hold no phrase's first word and are passed over in C."""
        trie = self._trie if self._trie is not None else self._search()
        lemmas = [token[0] for token in tokens]
        firsts = self.firsts
        if firsts.isdisjoint(lemmas):
            return []
        found, n, after, fixed, entries = [], len(lemmas), 0, self._fixed, self.entries
        for i in list(compress(range(n), map(firsts.__contains__, lemmas))):   # where a phrase can start (in C)
            if i < after:
                continue                    # inside the phrase just found
            node, ends, j = trie[lemmas[i]], [], i + 1
            while True:
                index = node.get(_END)
                if index is not None:
                    ends.append((j, index))
                if j == n:
                    break
                node = node.get(lemmas[j])
                if node is None:
                    break
                j += 1
            for end, index in reversed(ends):
                entry = entries[index]
                last = tokens[end - 1]
                if fixed[index] and own_form(entry, last[3]) and not ends_as(entry, last[2]):
                    continue                # そういうことだ is not そういうことなら, だけじゃない not だけでなく
                if (entry.prenoun or entry.grammar == AS_WRITTEN) and not before_a_noun(entry, tokens, i, end, text):
                    continue                # ああ言って is not ああいう, と言った not という
                if entry.grammar and end < n and lemmas[end] in TE_AUXILIARIES and entry.key[-1] == "て":
                    continue                # 本体についている is not について
                if entry.grammar and i and entry.key[0] == "様" and lemmas[i - 1] == "の":
                    continue                # 口のようにして is the simile のように, not ようにする
                if "".join(token[2] for token in tokens[i:end]) in text:
                    found.append((i, end, index))
                    after = end
                    break
        return found


def waiting(phrase, known, offered=None):
    """(the words `phrase` waits for, whether every real word in it is known) — `known((lemma, reading))` is the
    caller's test: known, ignored, or read through known words. A phrase is ready once it waits for nothing: grammar and
    light words never count, and neither does a word that lives only inside the phrase (it is learned with it) or a
    one-character word the list can never offer (it would wait forever). `offered((lemma, reading))` says whether the
    list offers a one-character word (analyzer.single_kind: a one-kanji dictionary word — 手に入れる waits for 手 while
    手 is new); None, none is. A ready phrase whose real words are all known sits lower on the list, as a word read
    through known words does."""
    words, all_known = [], True
    for role, key in zip(phrase.roles, zip(phrase.key, phrase.readings)):
        if role not in (CONTENT, BOUND) or known(key):
            continue
        all_known = False
        if role == CONTENT and (len(key[0]) > 1 or (offered is not None and offered(key))):
            words.append(key)
    return tuple(words), all_known


def bound_at(phrase):
    """The positions in `phrase` of the words that live only inside it (their uses there are the phrase's)."""
    return tuple(k for k, role in enumerate(phrase.roles) if role == BOUND)


def spellings(tokens, start, end, phrase):
    """(the phrase in its dictionary form, the phrase as written) for one match `tokens[start:end]`: 気がついた is
    (気がつく, 気がつい), 目を輝かせて (目を輝かせる, 目を輝かせ) — its last word in the dictionary form the text spells
    it in, with the voiced first sound the text gives it (いつもどおり, 怖気づく: UniDic's dictionary form is とおり,
    つく) — and a phrase that ends in a form of its own (`own_form`) or as its own spelling does is written as it is
    (ごめんなさい, ざまあみろ, もしかしたら, 我関せず: the dictionary form of ず is spelled ぬ). The first names the row
    (its Orth, the commonest); the second is searchable (Forms)."""
    last = tokens[end - 1]
    head = "".join([token[2] for token in tokens[start:end - 1]])
    written = head + last[2]
    if phrase.display.endswith(last[2]) or (fixed_form(phrase) and own_form(phrase, last[3])):
        return written, written
    return head + _voiced_as(last[3], last[2]), written


def _voiced_as(base, surface):
    """`base` (a word's dictionary form) with the voiced first sound `surface` (how the text spells it) gives it — the
    sound a word takes inside a compound (通り in いつもどおり, 付く in 怖気づく), which UniDic's dictionary form leaves
    out; else `base` as it is."""
    if surface[:1] != base[:1] and unicodedata.normalize("NFD", surface[:1])[:1] == base[:1]:
        return surface[:1] + base[1:]
    return base


def tally(sentences, phrase_set, matches=None):
    """What one file's sentences hold of the phrases: ({index: [uses, [spellings]]}, {"lemma|reading": the uses its
    words that live only inside a phrase give that phrase}). The token store keeps one per file; `table` sums them.
    `matches`, a list, also receives every match, four numbers each — sentence, start, end, index — what Generate
    reads instead of finding the phrases again (`Store.phrase_matches`)."""
    uses, taken = {}, {}
    for number, (text, tokens) in enumerate(sentences):
        for start, end, index in phrase_set.find(tokens, text):
            if matches is not None:
                matches += (number, start, end, index)
            phrase = phrase_set.entry(index)
            entry = uses.get(index)
            if entry is None:
                entry = uses[index] = [0, []]
            entry[0] += 1
            for spelled in spellings(tokens, start, end, phrase):
                if spelled not in entry[1]:
                    entry[1].append(spelled)
            for k in bound_at(phrase):
                name = f"{tokens[start + k][0]}|{tokens[start + k][1]}"
                taken[name] = taken.get(name, 0) + 1
    return uses, taken


def table(tallies, phrase_set):
    """The library's phrase table from its files' `tally`s: {"rows": {"Word|Reading": [uses, [spellings, the
    dictionary's among them]]}, "taken": {"lemma|reading": uses}} — what the Rarity slider counts a phrase row by
    (token_index.unknown_distribution), as Generate's list does."""
    rows, taken = {}, {}
    for uses, given in tallies:
        for index, (n, spelled) in uses.items():
            phrase = phrase_set.entry(int(index))
            row = rows.get(phrase.word + "|" + phrase.reading)
            if row is None:
                row = rows[phrase.word + "|" + phrase.reading] = [0, [phrase.display]]
            row[0] += n
            row[1].extend(s for s in spelled if s not in row[1])
        for name, n in given.items():
            taken[name] = taken.get(name, 0) + n
    return {"rows": rows, "taken": taken}


def known_whole(phrase, spelled, known_tuples, known_lemmas, ignore):
    """Is the learner done with `phrase` as a whole — its row's Word, the dictionary's spelling or a spelling the text
    gives it (`spelled`) among the known words or on the ignore lists, or its Word known in its reading? (A known
    phrase is no row; its words are known already, as every known entry's words are.)"""
    if (phrase.word, phrase.reading) in known_tuples:
        return True
    return any(s in known_lemmas or s in ignore for s in (phrase.word, phrase.display, *spelled))


@functools.lru_cache(maxsize=1)
def load():
    """The phrases app/phrase_data.py ships, as one PhraseSet per process — or None when they can't be read."""
    try:
        from app import phrase_data
        rows = phrase_data.phrases()
    except Exception:
        return None
    return PhraseSet(rows) if rows else None

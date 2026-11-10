# SPDX-License-Identifier: GPL-3.0-or-later
"""パターン lookup and formatter — from a card's word to its lines (Patterns_Spec.md WP-P3, §16).

    <div class="pat-particle pat-src-conversational">〜が 30% · 〜は 23%</div>
    <div class="pat-form pat-src-conversational">大切な 59% · 大切に 20%</div>
    <div class="pat-colloc pat-src-conversational">気持ち悪い · 気持ちが分かる · 気持ちを伝える</div>
    <div class="pat-frame pat-src-conversational">そんな〜 · という〜 · ちょっと〜</div>
    <div class="pat-register">書き言葉</div>

`Anki_Card_Layout_Spec.md` §5 is the contract, and it is binding. Each line names its kind in its class
(`pat-particle`, `pat-form`, `pat-colloc`, `pat-frame`, `pat-register`) and the template files it by
that; a line without one is sorted by its CONTENT (`%` → particles, `×N` → collocations, else frames).
Items are split on `·` / `・` / a full-width space / two spaces, so an item that itself holds one of
those characters, or a line marker, is dropped, never written: a katakana name with `・` would split a
line in two, and a frame holding `%` would be filed as particles on an older template.

Everything here is pure except `tokenizer()`, which builds the fugashi callable the lookup needs.
The database is read through `patterns_store.Store`; nothing here touches Anki.
"""

import html
import re
from collections import Counter

from app.unicode_ranges import KANA

# The user, 2026-09-24: the two commonest particles (the ones a learner takes note of — one row on
# the card), two forms of the word itself, four collocations, three frames.
CAPS = {"particle": 2, "form": 2, "colloc": 4, "frame": 3}

# Written style (the user, 2026-09-24): a word's rate in the conversational corpus against its rate
# in the balanced corpus's written half — literature, Wikipedia, news: balanced minus conversational,
# which it contains. Only a strong lean earns the tag; most words are used both ways (目 0.7, 経験 1.0,
# 研究 0.5 — subtitles speak plenty of written vocabulary), while 及び (20×), 即ち (10×) and 設立
# (507 spoken / 5,208 written) lean written. There is no spoken tag: subtitles are DRAMA, so a show's
# topics lean "spoken" too (海鮮丼 38× on 80 uses, 聖杯, 黙示録), and the user chose the written tag
# alone until speech is measured on the unscripted chats (RealPersonaChat, NUCC) instead.
# 4.0 while numbers, symbols and Latin words counted as tokens; the same line on builder 8's counting, measured.
REGISTER_LEAN = 4.155      # at least this many times rarer in speech
REGISTER_MIN = 50          # uses across both halves before a lean means anything
WRITTEN = "書き言葉"
# Per language: (lean, minimum uses, label); a language with no row has no register. Chinese has none in
# v1 (Patterns_Chinese_Spec.md D9, its gate WP-Z6): the only speech it may share — Tatoeba, KdConv's talk
# of films and music, CrossWOZ's hotel bookings — is too small and too narrow, and at these thresholds
# 3,457 of the 6,000 commonest words would carry 书面语, 政府 and 比赛 among them.
REGISTER = {"ja": (REGISTER_LEAN, REGISTER_MIN, WRITTEN)}
# A Japanese card's shares are of ALL the word's uses — particles and forms alike, the way a learner reads
# them: 〜を 9% on 反省 is 9 of every 100 uses (Patterns_Quality_Spec.md decision 2; it was a share of the
# particle slots, and 〜を 26% on 利用 described 1% of its uses). Under 5% says nothing; a particle needs
# at least MIN_PARTICLE uses too, or one stray use of a twenty-use word would read 〜を 5%.
MIN_SHARE = 0.05
MIN_PARTICLE = 3
MIN_SLOTS = 10         # Chinese: fewer measure-word or coverb slots than this and no shares are shown
# A Japanese pairing or frame must be real, common and specific (decision 4): seen in at least MIN_DOCS
# documents — one book saying it thirty times is that book's (再度生老人, F7) — and at least MIN_STRENGTH
# logDice — below it the partner goes with everything (反省が来る −0.3, 啓示とする −4.3; F5). No floor
# grows with the word's frequency (the user, U8): only strength tells 反省を踏まえる from 反省が来る.
MIN_DOCS = 3
MIN_STRENGTH = 2.0
# Filler (F6): `{w}という` fits any noun (it passes strength for 56 of 4,977 words, all generic). The
# demonstrative and ような frames show only where they ARE the word's use — そのまま 32%, この辺, その通り —
# not where they merely fit a noun (この事件 7.8 strength, 8.7% of its uses): U11.
FILLER = {"ja": frozenset(("{w}という",)),
          "zh": frozenset(("是{w}",))}              # "is X" — shown on 1,837 Chinese words (§10 E1)
DEMONSTRATIVES = {"ja": frozenset(("その〜", "この〜", "あの〜", "どの〜", "こんな〜", "そんな〜", "あんな〜",
                                   "どんな〜", "ような〜")),
                  "zh": frozenset(("这个〜", "那个〜", "这些〜", "那些〜", "这种〜", "那种〜", "各〜", "每个〜"))}
DEMONSTRATIVE_SHARE = 0.10
# The frames a language's builder writes only from demonstratives: Chinese's F1 is always 这 / 那 / 哪 / 每 /
# 某 / 各 with or without a measure word (这家〜, 各种〜, 这项〜 — 149 of them in the shared set), so the 10% rule
# holds for all of them, not only the eight named above (U11's "one rule for both languages").
DEMONSTRATIVE_SECTIONS = {"zh": frozenset(("F1",))}
# A Chinese coverb row (P) whose slots cover under this share of the word's uses says little: 突然 在〜 58%
# rested on 4.9% of its uses, 帮助's on 4.0%, 认真's on 2.9%, while 影响 对〜 has 8.9% and 见面 与〜 33.8%
# (measured after 在…下 left the coverb slots, 2026-09-25). A measure-word row (Q) keeps its own line: a
# measure word is only used when counting (Patterns_Quality_Spec.md §10 E4).
COVERB_COVERAGE = 0.06
# A card whose lines rest on fewer uses than this in their source is thin: the label turns amber
# (decision 3, U5) — colour only, no count on the card.
THIN_USES = 50
# A construction (…を受ける, …に受ける, この〜) holding less than this share of the word's items of one
# kind gets no slot of its own; its items can still appear after the leaders, by logDice.
SECTION_SHARE = 0.05

# Anything the template would read as a separator or a line marker (§5): `·`, `・`, a full-width
# space, two spaces, `%`, `×`, or an `x` followed by a digit.
_UNSAFE_RE = re.compile(r"[·・　%×]| {2}|x\d")


def safe(item):
    """True when `item` can go into the field without being split or mis-filed by the template."""
    return bool(item) and not _UNSAFE_RE.search(item)


def lines_for(store, lemma, reading):
    """-> {"particle": [(p, share[, side])], "side": "after" | "before", "form": [(item, share)],
    "colloc": [(item, count)], "frame": [(item, count)]}.

    `side` is where a particle sits: after a noun (探検に), before a verb or an adjective, which it
    attaches to from the left (…を受ける, …が深い, …が大切). A Japanese database since builder 6 stores
    each particle row's own side — a する-noun takes を before it too (を〜 on 利用) — and its shares are
    of all the word's uses; a Chinese one keeps its own line 1 (Patterns_Quality_Spec.md §10 E4), shares
    of the slots, on the word's side. A form's share is of all the word's uses. Collocations and frames
    pass `_kept` (Japanese) and are ordered by `_spread`. The caps are applied by `format_patterns`,
    after the separator check. Each rule is gated by the database's own language (§8.2)."""
    found = store.word(lemma, reading)
    total = found[2] if found else 0
    language = store.meta().get("language") or "ja"
    out = {"particle": [], "side": "after" if found and found[1] == "名詞" else "before",
           "form": [], "colloc": [], "frame": []}
    stored = store.all_patterns(lemma, reading)
    rows = stored.get("particle", [])
    if language == "ja":
        # 〜の is an adverbial word's line alone (再度の襲撃; the user, decision 6): an ordinary noun's の
        # stays out (D4). Ties break on the particle, so the same counts always write the same field.
        adverb = bool(found) and found[1] == "副詞"
        shares = sorted(((row[0], row[1] / total, row[3]) for row in rows
                         if total and row[1] >= MIN_PARTICLE and (adverb or row[0] != "の")),
                        key=lambda s: (-s[1], s[0], s[2] or ""))
        out["particle"] = [s for s in shares if s[1] >= MIN_SHARE and safe(s[0])][:CAPS["particle"]]
    else:
        slots = sum(row[1] for row in rows)
        coverb = bool(rows) and all(row[3] == "P" for row in rows)
        if slots >= MIN_SLOTS and not (coverb and slots < COVERB_COVERAGE * total):
            shares = sorted(((row[0], row[1] / slots) for row in rows), key=lambda s: (-s[1], s[0]))
            out["particle"] = [s for s in shares if s[1] >= MIN_SHARE and safe(s[0])][:CAPS["particle"]]
    if total:
        out["form"] = sorted(((row[0], row[1] / total) for row in stored.get("form", [])),
                             key=lambda f: (-f[1], f[0]))
    for kind in ("colloc", "frame"):
        kept = _kept(stored.get(kind, []), kind, total, language)
        out[kind] = _spread(kept) if kind == "colloc" else _one_long_partner(_spread(kept), kept)
    return out


def _kept(rows, kind, total, language):
    """The pairings or frames that are real, common and specific (decision 4): seen in MIN_DOCS
    documents (a database without the count — builder 5 and before — skips that test), at least
    MIN_STRENGTH strong and MIN_PATTERN common; no filler pairing; a demonstrative frame only where it
    covers DEMONSTRATIVE_SHARE of the word's uses. A language without these rules keeps every row."""
    if language not in FILLER:
        return rows
    from modules.junban.patterns_build import MIN_PATTERN
    filler, demonstratives = FILLER[language], DEMONSTRATIVES[language]
    demonstrative_sections = DEMONSTRATIVE_SECTIONS.get(language, frozenset())
    return [row for row in rows
            if (len(row) < 5 or row[4] is None or row[4] >= MIN_DOCS)
            and (row[2] is None or row[2] >= MIN_STRENGTH) and row[1] >= MIN_PATTERN
            and not (kind == "colloc" and row[0] in filler)
            and not (kind == "frame" and (row[0] in demonstratives or row[3] in demonstrative_sections)
                     and row[1] < DEMONSTRATIVE_SHARE * total)]


def _one_long_partner(frames, rows):
    """`frames` (in card order) with at most one multi-character compound partner (経済 → 〜政策), and
    that one only where it is at least as common as the one-character partner it would push off the
    row (反省 → 〜会 · 〜点 · 〜文): the user's U10 — news and Wikipedia are full of noun + noun runs. With
    a free slot it pushes nothing off (幼少 → 〜期 · 〜時 · 〜時代), and an item the card cannot show
    (`safe`) never takes a slot."""
    section = {row[0]: row[3] for row in rows}
    frames = [(item, count) for item, count in frames if safe(item)]
    out, long_taken = [], False
    for n, (item, count) in enumerate(frames):
        if section.get(item) == "F4m":
            if long_taken:
                continue
            # What would have filled the row's last slot, and is pushed off by this one.
            rest = [(other, c) for other, c in frames[n + 1:] if section.get(other) != "F4m"]
            room = CAPS["frame"] - len(out) - 1
            pushed = rest[room] if 0 <= room < len(rest) else None
            if pushed is not None and section.get(pushed[0]) == "F4" and pushed[1] > count:
                continue
            long_taken = True
        out.append((item, count))
    return out


def _spread(rows):
    """[(item, count, logdice, section[, files])] in logDice order -> [(item, count)] in the order a
    card shows them: first the strongest item of each construction holding at least SECTION_SHARE of
    them — the commonest construction first — then all the rest by logDice.

    The user, 2026-09-24: the collocations should give "the jist of how it's used but also what it
    pairs with", pulled "from the most useful sections". By logDice alone a word's four often come
    from one construction — four objects of one verb. Rows without a section (a builder-1 database)
    are one construction, which leaves them in plain logDice order."""
    seen, unique = set(), []
    for item, count, _, section, *_ in rows:
        if item not in seen:
            seen.add(item)
            unique.append((item, count, section or ""))
    total = sum(count for _, count, _ in unique)
    leaders, sizes = {}, Counter()
    for item, count, section in unique:
        leaders.setdefault(section, (item, count))
        sizes[section] += count
    first = [leaders[s] for s in sorted(sizes, key=lambda s: (-sizes[s], s))
             if sizes[s] >= SECTION_SHARE * total]
    chosen = {item for item, _ in first}
    return first + [(item, count) for item, count, _ in unique if item not in chosen]


def format_patterns(lines, word, source=None, thin=False):
    """-> the field's HTML, or "" when no line qualifies (the block then disappears — §5's no-data
    state). `word` fills the `{w}` in a form or a collocation, so it shows the card's own spelling.

    Each line's div names its kind (`pat-particle` …) and, when `source` is given, the database the
    lines came from (`pat-src-conversational`) — the template reads both, for the column and for a
    quiet source cue (Anki_Card_Layout_Spec.md §5) — and `pat-thin` when they rest on few uses (the
    label turns amber). A particle carries `〜` on its side: `〜が` after a noun, `を〜` before a verb or
    an adjective — its own side where the line says it, else the word's. Each form is a line of its own
    (the user: "they are longer and it looks better to have them on their own line"). Collocations
    carry no count: the order already says which is strongest (the user, 2026-09-24)."""
    out = []
    word_side = lines.get("side", "after")
    particles = [(f"〜{p}" if ((side[0] if side else None) or word_side) == "after" else f"{p}〜")
                 + f" {round(share * 100)}%"
                 for p, share, *side in lines.get("particle", []) if safe(p)][:CAPS["particle"]]
    if particles:
        out.append(("particle", " · ".join(particles)))
    forms = [f"{text} {round(share * 100)}%" for text, share in
             ((item.replace("{w}", word), share) for item, share in lines.get("form", []))
             if safe(text)][:CAPS["form"]]
    out.extend(("form", form) for form in forms)
    collocs = [text for text in (item.replace("{w}", word) for item, _ in lines.get("colloc", []))
               if safe(text)][:CAPS["colloc"]]
    if collocs:
        out.append(("colloc", " · ".join(collocs)))
    frames = [item for item, _ in lines.get("frame", []) if safe(item)][:CAPS["frame"]]
    if frames:
        out.append(("frame", " · ".join(frames)))
    marks = (f" pat-src-{source}" if source else "") + (" pat-thin" if thin else "")
    return "".join(f'<div class="pat-{kind}{marks}">{html.escape(line, quote=False)}</div>'
                   for kind, line in out)


def _is_attached(token):
    """The copula's な / に, the particle に, or する — written onto a word, not a second word. The test
    is core's, so the report's "In Anki" label and this lookup read a card's word the same way."""
    from app.anki_match import is_attached_tail
    return is_attached_tail(token[0])


# A card spelled in numerals alone (一, 千, 二十, 千万) — see `resolve_key`.
_NUMERAL_RE = re.compile("[〇零一二三四五六七八九十百千万億兆0-9０-９]+")


def resolve_key(word, reading, store, tokenize):
    """-> ((lemma, reading), None) or (None, reason) — Patterns_Spec.md §7.

    `word` is the card's word, already normalised (`match.normalize_word`); `reading` is its
    `ExpressionReading`, or "". `tokenize(text)` -> [(lemma, reading, pos1, pos2)] content tokens; its
    `read(text)`, when it has one (`tokenizer`), also says how many numbers the text holds.

    A card the dictionary keeps apart from the word it is read as (`match.two_words`: 心する is no 心 + する, 揚げる
    no 上げる) takes none of that word's lines: only a word the database holds as the card writes it — its lemma, or
    its main spelling (the database's own orth: 帰る is how the library writes UniDic's 返る). The builder counts such
    a spelling as its own word (`patterns_build._entry`), so the database holds 揚げる, 撮る and 帰る under themselves."""
    from modules.junban.match import affixes_off, fold_kana, two_words
    if not word:
        return None, "no word"
    read = getattr(tokenize, "read", None)
    tokens, numbers = read(word) if read else (tokenize(word), 0)
    # A number is no word (the list's rule), so a card that holds one reads as it did before numbers stopped
    # counting: a number alone is no word (一, 二十 — and 千, which the tagger alone reads as the name セン), and
    # 何年, 世界一 or 十分 goes by its whole spelling (十分, a word the texts hold whole), never by what is left
    # once the number is dropped (何年 is not 年). A numeral inside a joined word (二十歳) belongs to that word.
    if (numbers == 1 and not tokens) or (not numbers and len(tokens) == 1 and tokens[0][3] == "固有名詞"
                                          and _NUMERAL_RE.fullmatch(word)):
        return None, "phrase"
    if numbers:
        if all(token[2] in ("名詞", "接頭辞", "接尾辞") for token in tokens):
            found = store.by_orth(word)
            return (found[0][:2], None) if found else (None, "not found")
        return None, "phrase"
    bare = affixes_off(tokens, kana=bool(_KANA_WORD.fullmatch(word)))
    if len(bare) < len(tokens):
        # The word's own grammar on the card — お部屋, 俺たち, 優しさ: the tokenizer keeps it apart and the
        # list counts the word, so the card takes the word's lines (優しい's list 優しさ as a form).
        word, tokens = None, bare
    if len(tokens) == 2 and _is_attached(tokens[1]):
        # The card wrote the word with its な / に / する attached (斬新な, 深入りする — 41 of the user's Lapis
        # notes); the list knows it as 斬新, 深入り. Not a word the dictionary gives an entry of its own, apart
        # from the word before its ending (心する, 一気に): that is no word the database holds — a phrase to it.
        if word is not None and two_words(word, tokens[0][0]):
            return None, "phrase"
        word, tokens = None, tokens[:1]
    if len(tokens) > 1:
        # A compound noun (奨学金 = 奨学 + 金) is counted as a word of its own; anything else with
        # two or more tokens is a phrase (D3: 話が弾む), skipped in v1.
        if all(token[2] in ("名詞", "接頭辞", "接尾辞") for token in tokens):
            found = store.by_orth(word)
            if found:
                return found[0][:2], None
            return None, "not found"
        return None, "phrase"
    if word is None:
        lemma, lform = tokens[0][:2]
        return ((lemma, lform), None) if store.word(lemma, lform) else (None, "not found")
    # A word the database holds under another spelling is the card's only when it is written as the card is — its
    # lemma or its main spelling — or the dictionary does not keep the two apart (揚げる is no 上げる).
    candidates = [(lemma, lform, count) for lemma, lform, count in store.by_orth(word)
                  if lemma == word or not two_words(word, lemma) or (store.word(lemma, lform) or ("",))[0] == word]
    if reading and candidates:                                  # step 3: the reading disambiguates
        want = fold_kana(reading)
        for lemma, lform, _ in candidates:
            if fold_kana(lform) == want:
                return (lemma, lform), None
    if candidates:                                              # step 4: best-evidenced reading
        lemma, lform, _ = candidates[0]                         # (感じる -> 感ずる lands here)
        return (lemma, lform), None
    if tokens and not two_words(word, tokens[0][0]):            # step 5: through the lemma
        lemma, lform = tokens[0][:2]
        if store.word(lemma, lform):
            return (lemma, lform), None
        for other, _ in store.readings(lemma):
            return (lemma, other), None
    return None, "not found"


def patterns_for(word, reading, store, tokenize, source=None):
    """-> (html, reason). `html` is "" with a reason when the card should stay empty."""
    return _patterns_and_uses(word, reading, store, tokenize, source)[:2]


def _patterns_and_uses(word, reading, store, tokenize, source=None, thin=False):
    """-> (html, reason, the word's uses in `store`)."""
    key, reason = resolve_key(word, reading, store, tokenize)
    if key is None:
        return "", reason, 0
    found = store.word(*key)
    count = found[2] if found else 0
    if count < store.floor():
        return "", f"too rare ({count} < {store.floor()})", count
    out = format_patterns(lines_for(store, *key), _bare_word(word, tokenize), source, thin)
    return out, (None if out else "no pattern clears the floors"), count


def _bare_word(word, tokenize):
    """The card's word without the な / に / する it was written with (斬新な, 一気に, 深入りする) — what
    `{w}` stands for. The lookup drops that tail (`resolve_key`); filled in with it, the lines read
    斬新ななアイデア, 一気にに広まる and 深入りするする 79% (the Japanese goldens found it, 2026-09-25).
    Likewise without its own grammar (`resolve_key`): お部屋 is 部屋, 俺たち 俺, and 優しさ the adjective 優しい —
    never 優しさい or お部屋部屋."""
    from modules.junban.match import NOMINALIZERS, POLITE_PREFIXES, affixes_off
    tokens = tokenize(word or "")
    bare = affixes_off(tokens, kana=bool(_KANA_WORD.fullmatch(word or "")))
    if len(bare) < len(tokens):
        if tuple(tokens[-1][:2]) in NOMINALIZERS and len(bare) == 1 and bare[0] is tokens[-2]:
            return bare[0][0]                           # 優しさ: the adjective, as its lines show it
        if tuple(tokens[0][:2]) in POLITE_PREFIXES and word.startswith(("お", "ご", "御")):
            word = word[1:]
        if bare[-1] is not tokens[-1]:
            word = _PLURAL_END.sub("", word) or word
        tokens = bare
    if len(tokens) == 2 and _is_attached(tokens[1]):
        for tail in ("する", "な", "に"):
            if word.endswith(tail):
                return word[:-len(tail)]
    return word


# The order a card is filled from (user, 2026-09-24): the conversational corpus first — it reads best
# on cards and agrees best with NLT on collocations — then the balanced one, then the one Surasura can
# share (RealPersonaChat + Aozora + Wikipedia, Patterns_Spec §18: where the two personal ones are, it
# is not), then the user's own library, the only one that knows their character names and niche words.
SOURCE_ORDER = ("conversational", "balanced", "shared", "library")
# Per language; a language not here is not offered anything — never given Japanese's.
SOURCE_ORDERS = {"ja": SOURCE_ORDER, "zh": ("conversational", "balanced", "shared", "library")}


def sources_for(language):
    """The fill order for `language`, or () when it has none (Patterns_Chinese_Spec.md S2)."""
    return SOURCE_ORDERS.get(language, ())


def patterns_from_sources(word, reading, stores, tokenize, language="ja", script=None):
    """-> (html, reason, source). `stores` is [(name, Store or None)] in fill order. The card takes the
    first source that gives it the full four collocations, else the one that gives the most — the
    earlier on a tie (the user, 2026-09-24: "4 in total would be nice (if there are)"; on their 1,457
    Lapis notes that is 671 cards with four, against 401 when the first source to fill anything won).
    Nothing fills it -> ("", the first source's reason, None). A Chinese card (`language` zh) is looked
    up and written by patterns_zh, in its own script (`script`: the user's zh_script)."""
    if language == "zh":
        from modules.junban import patterns_zh
        return patterns_zh.from_sources(word, stores, script)
    # A source whose word has fewer than THIN_USES uses is thin: the first source with four pairings
    # that is NOT thin wins, else the first with four, else the richest — 呈する took 42 uses where the
    # next source had 554 (Patterns_Quality_Spec.md §8.2).
    best, first, full = None, None, None
    for name, store in stores:
        if store is None:
            continue
        out, reason, uses = _patterns_and_uses(word, reading, store, tokenize, source=name)
        if not out:
            first = first or reason
            continue
        n, thin = _collocations(out), uses < THIN_USES
        if best is None or n > best[0]:
            best = (n, out, name, thin)
        if n >= CAPS["colloc"]:
            if not thin:
                full = (n, out, name, thin)
                break
            full = full or (n, out, name, thin)
    chosen = full or best
    if chosen:
        _n, out, name, thin = chosen
        if thin:
            out = re.sub(r'<div class="(pat-[^"]*)">', r'<div class="\1 pat-thin">', out)
        balanced = dict(stores).get("balanced")
        label = None
        # A name has no register: ユウカ is rarer in subtitles than in Wikipedia, not "written" (the
        # databases keep only 名詞, so the card's own word is asked). Nor has an adverb written in kana
        # alone — にこにこ, そっと, ぼんやり: novels' narration uses them far more than talk does, yet
        # nobody calls them written language (the user, 2026-09-25); 予め, 些か, 恰も keep theirs.
        if balanced is not None and not _is_name(word, tokenize):
            key = resolve_key(word, reading, balanced, tokenize)[0]
            if not _kana_adverb(word, key, balanced):
                label = register_of(key, stores)
        return out + (f'<div class="pat-register">{label}</div>' if label else ""), None, name
    return "", first or "no database built", None


def _is_name(word, tokenize):
    """Is the card's word a name — UniDic's proper noun (ユウカ, 田中), or a katakana name the names layer made one word
    of from pieces that are no words (スドウ, ス + ドウ to the tagger: a word its dictionary lacks, a common noun to it —
    `tokenizer`'s `joined_names`)?"""
    tokens = tokenize(word or "")
    joined_names = getattr(tokenize, "joined_names", None)
    made = joined_names(word or "") if joined_names else ()
    return bool(tokens) and all((len(token) > 3 and token[3] == "固有名詞") or (k < len(made) and made[k])
                                for k, token in enumerate(tokens))


_PLURAL_END = re.compile("(?:たち|達|ら|等|ども|共)$")      # how a plural is written (match.PLURALS)
_KANA_WORD = re.compile(f"[{KANA}]+")      # the kana blocks (app/unicode_ranges.py)


def _kana_adverb(word, key, store):
    """Is the card's word an adverb written in kana alone (にこにこ, ニヤリ, そっと)?"""
    return (key is not None and bool(_KANA_WORD.fullmatch(word or ""))
            and (store.word(*key) or ("", "", 0))[1] == "副詞")


def _collocations(field):
    """How many collocations `field` shows — the items of its `pat-colloc` line."""
    return sum(len(line.split(" · "))
               for line in re.findall(r'<div class="pat-colloc[^"]*">([^<]*)</div>', field))


def register_of(key, stores, language="ja"):
    """-> the language's written label (WRITTEN for Japanese), or None when word `key` does not lean
    hard toward writing — or there is no telling: either general database missing, or too few uses
    (`REGISTER_MIN`). The balanced corpus contains the conversational one, so a word's written count is
    the difference of the two. The thresholds are the language's row of `REGISTER` — a language without
    one has no register."""
    if language not in REGISTER:
        return None
    lean_needed, least, label = REGISTER[language]
    by_name = dict(stores)
    spoken_db, balanced = by_name.get("conversational"), by_name.get("balanced")
    if key is None or spoken_db is None or balanced is None:
        return None
    try:
        spoken_tokens = int(spoken_db.meta().get("tokens") or 0)
        written_tokens = int(balanced.meta().get("tokens") or 0) - spoken_tokens
    except ValueError:
        return None
    spoken = (spoken_db.word(*key) or ("", "", 0))[2]
    written = (balanced.word(*key) or ("", "", 0))[2] - spoken
    if spoken_tokens <= 0 or written_tokens <= 0 or written < 0 or spoken + written < least:
        return None
    lean = ((spoken + 1) / spoken_tokens) / ((written + 1) / written_tokens)
    return label if lean <= 1 / lean_needed else None


def open_sources(language="ja"):
    """-> [(name, Store or None)] in the language's fill order (`sources_for`); a database not built
    yet is None."""
    from modules.junban.patterns_store import open_store
    return [(name, open_store(language=language, name=None if name == "library" else name))
            for name in sources_for(language)]


def tokenizer(tagger=None):
    """-> tokenize(text) -> [(lemma, reading, pos1, pos2)] content tokens, keyed exactly as the
    builder keys them (lemma sanitised, reading = lForm, prefixes and suffixes joined). `tagger` reuses
    the analyzer's tagger the caller already holds — a Backfill session shares one with its known-words
    test. `tokenize.read(text)` -> (the same tokens, how many numbers the text holds outside a joined word):
    a number is no token, and `resolve_key` must still know it was there (何年 is not 年). `tokenize.joined_names(text)`
    -> for each of those tokens, whether the katakana names layer made it one word from pieces that are no words — one
    its dictionary lacks (スドウ: `names.one_word`) — for `_is_name`."""
    from app.analyzer import JoinedWord, Tagger, _sanitize_term, affix_joins, join_affixes, word_lemma
    if tagger is None:
        tagger = Tagger()   # reads text as the analyzer does (ﾅｲﾌ is ナイフ)
    joins = affix_joins()

    def read(text):
        out, numbers = [], 0
        for w in join_affixes(tagger(text), joins, library=False):   # as the builder reads (no library tables)
            lemma = word_lemma(w)    # the tokenizer's own test: no punctuation, space, symbol or number
            if lemma is None:
                numbers += w.feature.pos2 == "数詞"      # 二十 inside 二十歳 is that word's: no number here
                continue
            f = w.feature
            out.append((_sanitize_term(lemma), f.lForm or f.kana or "", f.pos1, f.pos2))
        return out, numbers

    def tokenize(text):
        return read(text)[0]

    def joined_names(text):
        return [isinstance(w, JoinedWord) and w.is_unk
                for w in join_affixes(tagger(text), joins, library=False) if word_lemma(w) is not None]
    tokenize.read = read
    tokenize.joined_names = joined_names
    return tokenize

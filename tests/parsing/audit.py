"""The random audit — how complete the suite is, measured instead of guessed.

    python tests/parsing/audit.py sample --out debug/parsing_suite/audit/<date>   # batches for the reviewers
    python tests/parsing/audit.py flags  --out debug/parsing_suite/audit/<date>   # every flag with its parse
    python tests/parsing/audit.py score  --out debug/parsing_suite/audit/<date>   # REPORT.md from verdicts.json
    python tests/parsing/audit.py lock   --out debug/parsing_suite/audit/<date>   # verified sentences -> LOCK cases
    python tests/parsing/audit.py sample --lang zh --out debug/parsing_suite/audit/<date>-zh --seed <new>
    python tests/parsing/audit.py lock   --lang zh --out debug/parsing_suite/audit/<date>-zh

The whole procedure — reviewers, verification, growing the suite: Parsing_Suite.md §13. Chinese
(Chinese_Build_Spec.md §6) samples general text instead — docs/assets/corpora/zh/_text, an equal share per source, as
the Chinese library is four bundled samples — reads each line with ChineseTokenizer under the pins, and locks the
verified lines as ZH-ORD cases (cases_zh_ordinary.py), never one of Leipzig's (counts only).

`sample` draws N sentences uniformly from the user's library (the token store, read-only — the sentences as the
app cleaned and cached them), parses each with the app's own tokenizer under the suite's pins, and writes review
batches: the sentence and every token as surface【lemma・reading・pos】 with the suite's marks. Hidden among them are
known-wrong sentences from the suite's TARGET cases ("canaries"): how many the reviewers catch says how many real
problems they miss. Which items are canaries is in key.json, never in a batch. Reviewers write review_<n>.jsonl
beside their batch; `flags` gathers what they flagged, with the parse, for verification. The audit only reads.
"""
import argparse
import json
import os
import random
import sqlite3
import sys
import types
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from tests.parsing import evaluators, harness  # noqa: E402

STORE = os.path.join(os.environ.get("APPDATA", ""), "SonicSandbox", "Surasura", "token_store_ja.db")
MARKS = {"drop": "⊘", "single": "¹"}
CORPUS_ZH = os.path.join(REPO, "docs", "assets", "corpora", "zh", "_text")
# Each general-text source's licence, for a locked case's source line; Leipzig's text is counts only, never locked.
LICENCES_ZH = {"tatoeba": "CC BY 2.0 FR", "kdconv": "Apache-2.0", "crosswoz": "Apache-2.0",
               "wikipedia": "CC BY-SA 4.0", "wikinews": "CC BY 4.0", "leipzig_news": "Leipzig, counts only",
               "leipzig_web": "Leipzig, counts only"}

RUBRIC = """\
# Parsing audit — batch {n}

You are checking how a Japanese parser split and read real sentences from a learner's library (anime subtitles,
novels, YouTube transcripts, scripture …). Judge each item as a Japanese linguist would, by the dictionaries'
standard (JMdict / 大辞林), for THIS context. Work briskly: most items are fine.

Each item: `文:` the sentence as the app stored it; `語:` every token as surface【lemma・reading・pos】.
Marks: `+` the app joined this word from pieces (新幹線, 利用者 — intended); `¹` a one-character word the list can't
offer here — grammar, a kanji no dictionary lists alone, or a one-kanji word standing as a piece of something else
(年 in 三年) — so it is no use and no new word (by design); `⊘` the app does not count this token at all. A one-kanji
word WITHOUT ¹ (手, 顔) is a list word like any other: judge its lemma and reading.

A PROBLEM is one of:
- SEG   a word cut into pieces that aren't words (カヌレ → か + 濡れ), or pieces glued wrongly (旧市 + 庁舎 for 旧 + 市庁舎)
- LEMMA the dictionary form or word identity is wrong here (行っ → 行う where it means 行く; だいぶ → ダイブ 'dive')
- READ  the reading is wrong here (今日 read コンニチ where it is きょう; 辛い read ツライ where it means 'spicy')
- JUNK  something counted that isn't language here: a sound cue ([音楽]), a citation abbreviation, markup leftovers
        (<>, \\), a fragment of a stretched word (いー from ふる～い), a symbol
- DROP  a real word marked ⊘ (not counted): half-width ﾅｲﾌ, a word in rare kanji …
- SENT  the sentence itself is broken: cut mid-sentence, two merged, a 。 added or punctuation lost, digits or Latin
        letters missing from what was said, or not speech/text at all (a header, a timestamp)
- NAME  a name read as common words, or a common word read as a name
- OTHER anything else wrong a learner would care about (say what)

NOT problems (the app's design): particles and auxiliaries as separate words; UniDic's lemma conventions when the
word is right (する → 為る, いる → 居る, a kanji lemma for kana text, katakana readings); a `¹` word's being off the
list; `⊘`
on punctuation or symbols; the `+` joins of prefixes / suffixes.

impact: `high` if it would put a wrong or junk word on a learner's list, hide a real one, or make the sentence look
easier or harder than it is; else `low`. confidence: `high` / `med` / `low` — when unsure, flag it with `low`
rather than deliberating; every flag is verified afterwards.

Write `review_{n}.jsonl` in this folder, ONE line per item, in order:
{{"id": "S001", "ok": true}}
{{"id": "S002", "ok": false, "problems": [{{"type": "SEG", "span": "…", "what": "…", "should": "…", "impact": "high", "confidence": "high"}}]}}
Read only this batch file. Don't open any other file, don't run anything.

"""


RUBRIC_ZH = """\
# Parsing audit — batch {n}

You are checking how a Chinese parser split real sentences of general text (dialogue, news, an encyclopedia, the web,
Tatoeba). Judge each item as a Chinese linguist would, by the dictionaries' standard (CC-CEDICT, 现代汉语词典), for
THIS context. Work briskly: most items are fine.

Each item: `文:` the line as the source wrote it; `語:` every token as surface【word】 — the word the app counts it
as (a doubled form is shown at its word: 开开心心【开心】); `⊘` the app does not count this text at all; `‖` a
sentence boundary.

A PROBLEM is one of:
- SEG    a word cut into pieces that aren't words (乳 + 酪 for 乳酪), or neighbours glued into a non-word (他来, 我要)
- NAME   a name cut into characters that count as everyday words (巴 / 拿 / 纳 / 德), or a common word read as a name
- NUM    a number counted as a word, or a word made of numerals that counts nothing dropped (千万 'by all means')
- LEMMA  a doubled form on the wrong word's row (爸爸妈妈【爸妈】 is fine; 马马虎虎 'so-so' is no 马虎)
- SENT   the sentence itself is broken: cut mid-sentence, two merged, punctuation lost
- JUNK   something counted that isn't language here: markup, a URL piece, a stray symbol
- DROP   a real word marked ⊘ (not counted)
- SCRIPT a Traditional word cut wrong, or spelled in a script the line doesn't use
- OTHER  anything else wrong a learner would care about (say what)

NOT problems (the app's design): particles and aspect markers as words of their own (了, 的, 吧, 着, 过); one-character
words; numbers ⊘; a doubled form shown at its word; a separable verb in pieces (洗 / 了 / 个 / 澡); `⊘` on
punctuation or symbols.

impact: `high` if it would put a wrong or junk word on a learner's list, hide a real one, or make the sentence look
easier or harder than it is; else `low`. confidence: `high` / `med` / `low` — when unsure, flag it with `low`
rather than deliberating; every flag is verified afterwards.

Write `review_{n}.jsonl` in this folder, ONE line per item, in order:
{{"id": "S001", "ok": true}}
{{"id": "S002", "ok": false, "problems": [{{"type": "SEG", "span": "…", "what": "…", "should": "…", "impact": "high", "confidence": "high"}}]}}
Read only this batch file. Don't open any other file, don't run anything.

"""


def _zh_units(ctx, text):
    """Every stretch of `text` as the app reads it, under the suite's pins: [{"surface", "word", "fate"}], a token
    counted ("count", its word — a doubled form's base) or the text it skips ("drop": numbers, punctuation), one
    sentence after another ({"surface": "‖"} between)."""
    with harness.pinned(types.SimpleNamespace(lang="zh", ctx={})):
        sentences = list(ctx.tokenizer("zh").tokenize_sentences(text))
    units = []
    for s_text, tokens in sentences:
        if units:
            units.append({"surface": "‖", "word": "", "fate": "break"})
        cursor = 0
        for word, _reading, surface, _orth in tokens:
            found = s_text.find(surface, cursor) if surface else -1
            if found < 0:
                continue
            gap = s_text[cursor:found].strip()
            if gap:
                units.append({"surface": gap, "word": "", "fate": "drop"})
            units.append({"surface": surface, "word": str(word), "fate": "count"})
            cursor = found + len(surface)
        gap = s_text[cursor:].strip()
        if gap:
            units.append({"surface": gap, "word": "", "fate": "drop"})
    return units


def _zh_line(units):
    return " · ".join(u["surface"] if u["fate"] == "break" else
                      f"{u['surface']}【{u['word']}】" if u["fate"] == "count" else u["surface"] + MARKS["drop"]
                      for u in units) or "(no token)"


def _corpus_lines(root):
    """{source: [line, ...]} — every line of 4-160 characters holding a Chinese character, per source folder."""
    from app.unicode_ranges import HAN
    han = __import__("re").compile(f"[{HAN}]")
    out = {}
    for source in sorted(os.listdir(root)):
        folder = os.path.join(root, source)
        if not os.path.isdir(folder):
            continue
        lines = out.setdefault(source, [])
        for name in sorted(os.listdir(folder)):
            if name.endswith(".txt"):
                with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as handle:
                    lines.extend(line.strip() for line in handle
                                 if 4 <= len(line.strip()) <= 160 and han.search(line))
    return out


def _units(ctx, text):
    """Every token of `text` as the app parses it, under the suite's pins (SANITIZE_JA, the frozen settings)."""
    with harness.pinned(types.SimpleNamespace(lang="ja", ctx={})):
        return evaluators._ja_units(ctx.tokenizer("ja"), text)


def _line(units):
    return " · ".join(f"{u['surface']}【{u['lemma']}・{u['reading']}・{u['pos']}】" + ("+" if u["joined"] else "")
                      + MARKS.get(u["fate"], "") for u in units) or "(no token)"


def _library_sentences():
    """[(file short name, sentence)] — every cached sentence that holds a token, in store order."""
    conn = sqlite3.connect("file:" + STORE.replace("\\", "/") + "?mode=ro", uri=True)
    out = []
    try:
        for path, blob in conn.execute("SELECT path, tokens FROM files ORDER BY path"):
            name = os.path.splitext(os.path.basename(path))[0][:60]
            for text, tokens in (json.loads(zlib.decompress(blob).decode("utf-8")) if blob else []):
                if tokens and text.strip():
                    out.append((name, text))
    finally:
        conn.close()
    return out


def _canaries(k, rng, lang="ja"):
    """k known-wrong library sentences from the suite's TARGET cases (one line, one sentence), spread over
    categories — each with the problem the suite records for it. Chinese: any source's (its library is four
    samples)."""
    from tests.parsing.cases import CASES
    pool = [c for c in CASES if c.status == "TARGET" and c.layer == f"tokens_{lang}" and c.lang == lang
            and (lang != "ja" or str(c.source).startswith("library")) and "\n" not in c.text
            and 4 <= len(c.text) <= 160]
    by_cat = {}
    for case in pool:
        by_cat.setdefault(case.category, []).append(case)
    for cases in by_cat.values():
        rng.shuffle(cases)
    picked, cats = [], sorted(by_cat)
    while len(picked) < k and any(by_cat.values()):
        for cat in cats:
            if by_cat[cat] and len(picked) < k:
                picked.append(by_cat[cat].pop())
    return picked


def sample(args):
    rng = random.Random(args.seed)
    ctx = harness.Context(os.path.join(args.out, "_scratch"))
    harness.load_evaluators()
    zh = getattr(args, "lang", "ja") == "zh"
    if zh:
        # An equal share per source (dialogue, news, encyclopedia, web, Tatoeba): a size-weighted draw would be
        # mostly Wikipedia.
        corpus = _corpus_lines(args.source or CORPUS_ZH)
        sources = [source for source in corpus if corpus[source]]
        share, extra = divmod(args.n, len(sources))
        items = []
        for k, source in enumerate(sources):
            want = min(len(corpus[source]), share + (1 if k < extra else 0))
            items.extend({"kind": "random", "source": source, "text": line}
                         for line in rng.sample(corpus[source], want))
        sentences = [(source, line) for source in sources for line in corpus[source]]
    else:
        sentences = _library_sentences()
        chosen = rng.sample(range(len(sentences)), args.n)
        items = [{"kind": "random", "source": sentences[i][0], "text": sentences[i][1]} for i in chosen]
    for case in _canaries(args.batches * args.canaries, rng, "zh" if zh else "ja"):
        # A canary wears a real library file's name, so nothing about it gives it away (the 2026-09-27 run leaked
        # one through a debug path in its source).
        items.append({"kind": "canary", "source": rng.choice(sentences)[0],
                      "text": case.text, "case": case.id, "span": case.span, "category": case.category,
                      "known": (case.basis or case.note or "")[:300]})
    randoms = [it for it in items if it["kind"] == "random"]
    canaries = [it for it in items if it["kind"] == "canary"]
    batches = [randoms[b::args.batches] + canaries[b::args.batches] for b in range(args.batches)]
    key, number = {}, 0
    os.makedirs(args.out, exist_ok=True)
    for b, batch in enumerate(batches, 1):
        rng.shuffle(batch)
        lines = [(RUBRIC_ZH if zh else RUBRIC).format(n=b)]
        for item in batch:
            number += 1
            sid = f"S{number:03d}"
            item["units"] = _zh_units(ctx, item["text"]) if zh else _units(ctx, item["text"])
            parse = _zh_line(item["units"]) if zh else _line(item["units"])
            key[sid] = {k: v for k, v in item.items() if k != "units"} | {"batch": b, "parse": parse}
            lines.append(f"### {sid} · {item['source']}\n文: {item['text']}\n語: {parse}\n")
        with open(os.path.join(args.out, f"batch_{b}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    with open(os.path.join(args.out, "key.json"), "w", encoding="utf-8") as f:
        json.dump({"seed": args.seed, "library_sentences": len(sentences), "items": key,
                   **({"lang": "zh"} if zh else {})}, f, ensure_ascii=False, indent=1)
    print(f"{len(sentences):,} {'corpus lines' if zh else 'library sentences'}; {len(randoms)} drawn (seed {args.seed})"
          f" + {len(canaries)} canaries -> {args.batches} batches in {args.out}")


def flags(args):
    with open(os.path.join(args.out, "key.json"), encoding="utf-8") as f:
        key = json.load(f)["items"]
    seen, out, missing = set(), [], []
    for name in sorted(os.listdir(args.out)):
        if not (name.startswith("review_") and name.endswith(".jsonl")):
            continue
        with open(os.path.join(args.out, name), encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                row = json.loads(raw)
                seen.add(row["id"])
                if not row.get("ok"):
                    item = key[row["id"]]
                    out.append(f"## {row['id']} · batch {item['batch']} · {item['kind']}"
                               + (f" ({item['case']})" if item["kind"] == "canary" else "")
                               + f" · {item['source']}\n文: {item['text']}\n語: {item['parse']}")
                    for p in row.get("problems", []):
                        out.append(f"  - {p.get('type')} [{p.get('impact')}/{p.get('confidence')}] "
                                   f"{p.get('span')}: {p.get('what')} → {p.get('should')}")
                    out.append("")
    missing = sorted(set(key) - seen)
    with open(os.path.join(args.out, "flags.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"{len(seen)} reviewed, {sum(1 for l in out if l.startswith('## '))} flagged items, "
          f"{len(missing)} not reviewed: {missing[:10]}")


def score(args):
    """REPORT.md from the key, the reviews and verdicts.json (the verifier's calls):

    {"S017": {"problems": [{"i": 0, "verdict": "confirmed" | "rejected", "type": "SEG", "class": "…",
                            "impact": "high" | "low", "covered": "JA-CMP-012" | null}],
              "missed": [{"type": …, "class": …, "impact": …, "covered": …, "span": …}],   # found by the verifier
              "caught": true | false}}                                                     # canaries only
    """
    with open(os.path.join(args.out, "key.json"), encoding="utf-8") as f:
        drawn = json.load(f)
    key = drawn["items"]
    with open(os.path.join(args.out, "verdicts.json"), encoding="utf-8") as f:
        verdicts = json.load(f)
    reviewed = set()
    for name in os.listdir(args.out):
        if name.startswith("review_") and name.endswith(".jsonl"):
            with open(os.path.join(args.out, name), encoding="utf-8") as f:
                reviewed |= {json.loads(line)["id"] for line in f if line.strip()}
    randoms = [sid for sid, item in key.items() if item["kind"] == "random" and sid in reviewed]
    canaries = [sid for sid, item in key.items() if item["kind"] == "canary" and sid in reviewed]

    def confirmed(sid):
        v = verdicts.get(sid, {})
        return [p for p in v.get("problems", []) if p.get("verdict") == "confirmed"] + v.get("missed", [])

    flagged = sum(1 for sid in randoms if verdicts.get(sid, {}).get("problems"))
    wrong = [sid for sid in randoms if confirmed(sid)]
    high = [sid for sid in randoms if any(p.get("impact") == "high" for p in confirmed(sid))]
    problems = [p for sid in randoms for p in confirmed(sid)]
    rejected = sum(1 for sid in randoms for p in verdicts.get(sid, {}).get("problems", [])
                   if p.get("verdict") == "rejected")
    # A canary is a fair test only when its known problem is one the rubric asks for (the verifier sets caught to
    # true / false); caught = null — e.g. a transparent compound left split — stays out of the recall.
    fair = [sid for sid in canaries if verdicts.get(sid, {}).get("caught") is not None]
    caught = [sid for sid in fair if verdicts[sid]["caught"]]
    recall = len(caught) / len(fair) if fair else None
    covered = [p for p in problems if p.get("covered")]
    by_type, by_class = {}, {}
    for p in problems:
        by_type[p.get("type", "?")] = by_type.get(p.get("type", "?"), 0) + 1
        entry = by_class.setdefault(p.get("class", "?"), {"n": 0, "covered": p.get("covered"), "impact": set()})
        entry["n"] += 1
        entry["impact"].add(p.get("impact", "?"))
    n = len(randoms)
    lines = [f"# Parsing audit — {os.path.basename(os.path.normpath(args.out))}", "",
             f"Random sentences reviewed: **{n}** (of {sum(1 for i in key.values() if i['kind'] == 'random')} drawn "
             f"from {drawn['library_sentences']:,}).",
             f"- flagged by a reviewer: {flagged} · confirmed wrong: **{len(wrong)} ({len(wrong) / n:.0%})** · "
             f"with a high-impact problem: **{len(high)} ({len(high) / n:.0%})** · flags rejected: {rejected}",
             f"- confirmed problems: {len(problems)} — covered by a suite case: **{len(covered)}"
             f" ({len(covered) / len(problems):.0%})**" if problems else "- confirmed problems: 0",
             f"- canaries caught: {len(caught)} of {len(fair)} fair ({len(canaries) - len(fair)} not a rubric problem)"
             + (f" → reviewer recall ≈ {recall:.0%}; true share of sentences with a problem ≈ "
                f"{min(1.0, len(wrong) / n / recall):.0%}" if recall else ""),
             "", "## By type", "", "| type | problems |", "| :-- | --: |"]
    lines += [f"| {t} | {c} |" for t, c in sorted(by_type.items(), key=lambda kv: -kv[1])]
    lines += ["", "## By class", "", "| class | problems | impact | covered by |", "| :-- | --: | :-- | :-- |"]
    lines += [f"| {c} | {e['n']} | {'/'.join(sorted(e['impact']))} | {e['covered'] or '**not covered**'} |"
              for c, e in sorted(by_class.items(), key=lambda kv: -kv[1]["n"])]
    lines += ["", "## Canaries", "", "| id | case | caught |", "| :-- | :-- | :-- |"]
    lines += [f"| {sid} | {key[sid].get('case')} | "
              f"{'yes' if sid in caught else ('no' if sid in fair else 'not a rubric problem')} |" for sid in canaries]
    with open(os.path.join(args.out, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:8]))


ORDINARY = os.path.join(REPO, "tests", "parsing", "cases", "cases_ja_ordinary.py")
ORDINARY_ZH = os.path.join(REPO, "tests", "parsing", "cases", "cases_zh_ordinary.py")
ORDINARY_ZH_HEAD = '''"""Ordinary Chinese text — random lines of general text an audit verified correct, locked whole (category P).

The Chinese twin of cases_ja_ordinary.py: the rest of the suite holds hard cases; these hold plain text, so a change
that quietly breaks everyday sentences shows up too. Written by `python tests/parsing/audit.py lock --lang zh`
(Chinese_Build_Spec.md §6): each is a line of docs/assets/corpora/zh/_text a reviewer passed (or whose flags were all
rejected), never one of Leipzig's (counts only). If one flips, read the diff before calling it a regression: the old
answer may have been a reviewer's miss. Group ORD belongs to this file."""
from tests.parsing.case import Case

CASES = [
'''
ORDINARY_HEAD = '''"""Ordinary text — random library sentences an audit verified correct, locked whole (category P).

The rest of the suite holds hard cases; these hold plain text, so a change that quietly breaks everyday sentences
shows up too (the user, 2026-09-27: "a selection of text it gets right, that we need to make sure it doesn't fail
later"). Written by `python tests/parsing/audit.py lock` (Parsing_Suite.md §13): each is a sentence a reviewer passed
(or whose flags were all rejected) — reviewer recall on canaries was ~88%, so if one of these flips, read the diff
before calling it a regression: the old answer may have been a miss. Group ORD belongs to this file."""
from tests.parsing.case import Case

CASES = [
'''


def lock(args):
    """Lock every random sentence the audit verified correct as a whole-sentence LOCK case (category P)."""
    if getattr(args, "lang", "ja") == "zh":
        return _lock_zh(args)
    from tests.parsing.case import Case
    with open(os.path.join(args.out, "key.json"), encoding="utf-8") as f:
        drawn = json.load(f)
    key = drawn["items"]
    verdicts_path = os.path.join(args.out, "verdicts.json")
    verdicts = json.load(open(verdicts_path, encoding="utf-8")) if os.path.exists(verdicts_path) else {}
    reviewed = set()
    for name in os.listdir(args.out):
        if name.startswith("review_") and name.endswith(".jsonl"):
            with open(os.path.join(args.out, name), encoding="utf-8") as f:
                reviewed |= {json.loads(line)["id"] for line in f if line.strip()}

    def clean(sid):
        v = verdicts.get(sid, {})
        return not v.get("missed") and not any(p.get("verdict") == "confirmed" for p in v.get("problems", []))

    existing = open(ORDINARY, encoding="utf-8").read() if os.path.exists(ORDINARY) else ""
    numbers = [int(n) for n in __import__("re").findall(r"""["']JA-ORD-(\d+)["']""", existing)]
    number = max(numbers, default=0)
    ctx = harness.Context(os.path.join(args.out, "_scratch"))
    harness.load_evaluators()
    entries, skipped = [], 0
    label = os.path.basename(os.path.normpath(args.out))
    for sid in sorted(key):
        item = key[sid]
        if item["kind"] != "random" or sid not in reviewed or not clean(sid) or repr(item["text"]) in existing:
            continue
        probe = Case(id="JA-ORD-000", lang="ja", layer="tokens_ja", category="P", text=item["text"], span="",
                     expect={}, basis="", status="LOCK")
        observed = harness.evaluate(probe, ctx).observed
        expect = {"units": evaluators.show_units(observed)}
        if evaluators.compare_units(observed, expect):      # the notation can't hold it (a [ or | in a surface)
            skipped += 1
            continue
        number += 1
        entries.append(
            f"    Case(id={f'JA-ORD-{number:03d}'!r}, lang='ja', layer='tokens_ja', category='P',\n"
            f"         text={item['text']!r}, span='',\n"
            f"         expect={expect!r},\n"
            f"         basis={'Random library sentence, every token reviewed and passed (audit ' + label + ', seed ' + str(drawn['seed']) + ', ' + sid + ').'!r},\n"
            f"         status='LOCK', source={'library: ' + item['source']!r}, refs=({'audit ' + label + ' ' + sid!r},)),\n")
    body = existing[:existing.rstrip().rfind("]")] if existing else ORDINARY_HEAD
    with open(ORDINARY, "w", encoding="utf-8") as f:
        f.write(body + "".join(entries) + "]\n")
    print(f"{len(entries)} ordinary sentences locked in {os.path.relpath(ORDINARY, REPO)} "
          f"(JA-ORD up to {number:03d}); {skipped} skipped (notation can't hold them)")


def _lock_zh(args):
    """lock --lang zh: every random line the audit verified correct as a whole-line LOCK case (ZH-ORD, category P,
    layer tokens_zh, expect {"seg": the line's seg}) in cases_zh_ordinary.py — never a Leipzig line (counts only)."""
    from tests.parsing.case import Case
    with open(os.path.join(args.out, "key.json"), encoding="utf-8") as f:
        drawn = json.load(f)
    key = drawn["items"]
    verdicts_path = os.path.join(args.out, "verdicts.json")
    verdicts = json.load(open(verdicts_path, encoding="utf-8")) if os.path.exists(verdicts_path) else {}
    reviewed = set()
    for name in os.listdir(args.out):
        if name.startswith("review_") and name.endswith(".jsonl"):
            with open(os.path.join(args.out, name), encoding="utf-8") as f:
                reviewed |= {json.loads(line)["id"] for line in f if line.strip()}

    def clean(sid):
        v = verdicts.get(sid, {})
        return not v.get("missed") and not any(p.get("verdict") == "confirmed" for p in v.get("problems", []))

    existing = open(ORDINARY_ZH, encoding="utf-8").read() if os.path.exists(ORDINARY_ZH) else ""
    numbers = [int(n) for n in __import__("re").findall(r"""["']ZH-ORD-(\d+)["']""", existing)]
    number = max(numbers, default=0)
    ctx = harness.Context(os.path.join(args.out, "_scratch"))
    harness.load_evaluators()
    entries, skipped = [], 0
    label = os.path.basename(os.path.normpath(args.out))
    for sid in sorted(key):
        item = key[sid]
        if (item["kind"] != "random" or sid not in reviewed or not clean(sid) or repr(item["text"]) in existing
                or item["source"].startswith("leipzig")):
            continue
        probe = Case(id="ZH-ORD-000", lang="zh", layer="tokens_zh", category="P", text=item["text"], span="",
                     expect={}, basis="", status="LOCK")
        expect = {"seg": harness.evaluate(probe, ctx).observed["seg"]}
        if expect["seg"].startswith("("):              # no sentence, or a span split: nothing to hold
            skipped += 1
            continue
        number += 1
        licence = LICENCES_ZH.get(item["source"], "?")
        entries.append(
            f"    Case(id={f'ZH-ORD-{number:03d}'!r}, lang='zh', layer='tokens_zh', category='P',\n"
            f"         text={item['text']!r}, span='',\n"
            f"         expect={expect!r},\n"
            f"         basis={'Random line of general text, every token reviewed and passed (audit ' + label + ', seed ' + str(drawn['seed']) + ', ' + sid + ').'!r},\n"
            f"         status='LOCK', source={'corpus: ' + item['source'] + ' (' + licence + ')'!r}, "
            f"refs=({'audit ' + label + ' ' + sid!r},)),\n")
    body = existing[:existing.rstrip().rfind("]")] if existing else ORDINARY_ZH_HEAD
    with open(ORDINARY_ZH, "w", encoding="utf-8") as f:
        f.write(body + "".join(entries) + "]\n")
    print(f"{len(entries)} ordinary lines locked in {os.path.relpath(ORDINARY_ZH, REPO)} "
          f"(ZH-ORD up to {number:03d}); {skipped} skipped (nothing to hold)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("sample", "flags", "score", "lock"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--lang", choices=("ja", "zh"), default="ja",
                        help="zh: general text instead of the library (Chinese_Build_Spec.md §6)")
    parser.add_argument("--source", default=None, help="zh: the corpus folder (default docs/assets/corpora/zh/_text)")
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--batches", type=int, default=6)
    parser.add_argument("--canaries", type=int, default=5, help="per batch")
    parser.add_argument("--seed", type=int, default=20260927)
    args = parser.parse_args()
    {"sample": sample, "flags": flags, "score": score, "lock": lock}[args.command](args)


if __name__ == "__main__":
    main()

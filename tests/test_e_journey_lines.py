"""E-JOURNEY (part 2): the page shows the reader's lines, and ⇄ / *Add now* take the line pressed (SPEC § 10.3
*E-JOURNEY*; § 5.2's row *the journey's ⇄ and Add now with a chosen line*: the line the learner pressed must be one the
reader can return).

At release 2 a word's sentences on the list are the one reader's (`analyzer.ListSentences`, the Generate's and the
redraw's); the page shows them from the list's columns (`journey_render.sentences_of`), and a line's id is the simple
Swap's `<item id>:<start ms>` (`swap.line_id`; the page's `lineId`), its start found from its text in its subtitle
(`journey_render.Sources.prepare`). The door's two presses (`swap/queue`, `card/make`) find the line again by that id
(`door_routes._line`: the press's one store read). What these prove on a level-2 Generate of real Japanese and Chinese
subtitles — each episode beside a video (an empty file: the page only needs to find one to give a line its ▶ time):
  - every line the page shows a word is the list's, in the list's order (no line added, dropped or moved);
  - every subtitle line the page gives an id resolves at the door to a line holding that very sentence, in the item
    the page names — never "gone", never another sentence — so the card cut from it is the sentence pressed;
  - a line said twice in its file (repeated_lines: an echo cue) still resolves to its own words;
  - a book's line gets the page's own key (no time in a file), which the door refuses as today.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from tests import plan_file_cases as cases

LEVEL_2 = {"SURASURA_SENTENCE_TABLE": "2"}

# RP-2's library with more episodes: real subtitles from tests/Test Resources (repeated_lines: the same line said twice)
_EXTRA = {"ja": [("now", "repeated_lines.ja.srt")],
          "zh": [("now", "night_market.srt"), ("now", "repeated_lines.zh.srt")]}


def _case(language):
    name = f"e-journey-lines-{language}"
    if name not in cases.ALL_CASES:
        base_language, library, shipped, args = cases.ALL_CASES[f"rp2-{language}"]

        def with_subtitles():
            return library() + [(tier, file, cases._read(os.path.join(cases.RES, language, file)))
                                for tier, file in _EXTRA[language]]
        cases.ALL_CASES[name] = (base_language, with_subtitles, shipped, args)
    return name


# The page as the browser reads it: each word's lines and their source rows, each line's id by the page's rule
# (`lineId`: the source's item, else its episode's, and the line's start), each id pressed at the door (`_line`)
_PRESS = r"""
import base64, csv, gzip, json, os, re, sys
from app import settings_manager
from app.connect import door_routes, runner, swap
language, root = sys.argv[1], sys.argv[2]
results = os.path.join(root, "results")
html = open(os.path.join(results, "reading_list_static.html"), encoding="utf-8").read()
head = json.loads(re.search(r'<script type="application/json" id="j-head">(.*?)</script>', html, re.S).group(1))
eps = head.get("eps") or []
listed = {}
with open(os.path.join(results, "priority_learning_list.csv"), encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        listed.setdefault(r["Word"], []).append(r)
steps = runner.Steps(settings_manager.load_settings())
out = {"words": [], "lines": [], "books": 0}
for blob in re.findall(r'<script type="application/gzip-base64" id="j-c\d+">(.*?)</script>', html):
    chunk = json.loads(gzip.decompress(base64.b64decode(blob)).decode("utf-8"))
    for w in chunk["w"]:
        rows = listed.get(w[0]) or []
        page = [ln[0] for ln in w[9] or ()]
        if len(rows) == 1:              # (a word listed under two readings: the page's row is one of them)
            row = rows[0]
            numbers = sorted(int(k[8:]) for k in row if k.startswith("Context ") and k[8:].isdecimal())
            have = [row[f"Context {n}"] for n in numbers if row[f"Context {n}"]]
            out["words"].append([w[0], page, have[:len(page)]])
        for ln in w[9] or ():
            src = chunk["src"][ln[1]] if len(ln) > 1 and ln[1] is not None else None
            at = ln[2] if len(ln) > 2 else None
            e = eps[src[2]] if src and src[2] is not None and src[2] >= 0 and src[2] < len(eps) else None
            item = src[5] if src and len(src) > 5 and src[5] is not None else (e[0] if e else None)
            if item is None or not isinstance(at, (int, float)):
                out["books"] += 1       # the page's own key: no line a card can be cut from
                continue
            lid = swap.line_id(item, at)
            got = door_routes._line(steps, language, lid)
            out["lines"].append([w[0], ln[0], lid, item, None if got is None else [got[0], got[1]]])
print(json.dumps(out, ensure_ascii=False))
"""


@pytest.fixture(scope="module", params=["ja", "zh"])
def page(request, tmp_path_factory):
    """A level-2 Generate of the language's library, its episodes' videos beside them; the page's lines pressed."""
    language = request.param
    case = _case(language)
    root = str(tmp_path_factory.mktemp(f"e-journey-lines-{language}"))
    cases.build(root, case)
    data = os.path.join(root, "data", language)
    for folder, _dirs, names in os.walk(data):
        for name in names:
            if name.endswith(".srt"):
                video = os.path.join(folder, name[:-4] + ".mp4")
                with open(video, "wb"):
                    pass                # (an empty file: found is all the page asks for a ▶ time)
                os.utime(video, (cases.MTIME, cases.MTIME))
    cases.generate(root, case, extra_env=LEVEL_2)
    env = cases.child_env(root)
    env.update(LEVEL_2)
    p = subprocess.run([sys.executable, "-c", _PRESS, language, root], cwd=cases.REPO, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    got = json.loads(p.stdout.strip().splitlines()[-1])
    shutil.rmtree(root, ignore_errors=True)
    return language, got


def test_the_pages_lines_for_a_word_are_the_lists_in_its_order(page):
    # why: the page shows what the list (the reader) chose — `sentences_of` reads the same columns at release 2; a
    # line added, dropped or moved would make the page's first sentence not the card's
    language, got = page
    assert got["words"], f"{language}: the page holds no word"
    for word, shown, have in got["words"]:
        assert shown == have, (language, word, shown, have)


def test_every_subtitle_line_the_page_names_is_the_line_the_door_finds(page):
    # why: ⇄ and *Add now* make the card from the line pressed (`swap.make_card(line_id=…)`): an id that found
    # another sentence, or none ("gone"), would cut a card from a line the learner didn't press, or refuse a good one
    from app.connect import sentences
    language, got = page
    assert got["lines"], f"{language}: no line on the page has a ▶ time (the episodes' videos were not found)"
    for word, text, lid, item, found in got["lines"]:
        assert found is not None, (language, word, text, lid, "the door says gone")
        assert found[0] == item, (language, word, lid, found)
        assert sentences.same_line(text, {found[1]}), (language, word, text, lid, found[1])


def test_a_line_said_twice_in_its_file_resolves_to_its_own_words(page):
    # why: edge case — an echo cue (the same line twice, 0.25 s apart: repeated_lines) gives two cues one text; the
    # page's time is one of them and the door finds that cue, never the next line's words
    from app.connect import sentences
    language, got = page
    echo = {"ja": "図書館の鍵を忘れちゃった", "zh": "我们明天去夜市吃牛肉面吧"}[language]
    hits = [(text, lid, found) for _w, text, lid, _item, found in got["lines"] if sentences.same_line(echo, {text})]
    assert hits, f"{language}: no word on the page shows the echoed line (the case no longer reaches it)"
    for text, lid, found in hits:
        assert found is not None and sentences.same_line(text, {found[1]}), (language, text, lid, found)


def test_a_books_line_gets_no_id_a_card_can_be_cut_from(page):
    # why: a line of a book or a text has no time in a file — the page keys it itself (`p<hash>`), and the door's
    # line check (`swap._parse_line_id`) refuses that, as today: nothing is asked of Swap for it
    from app.connect import door_routes, swap
    language, got = page
    assert got["books"] > 0, f"{language}: RP-2's books gave the page no line"
    assert swap._parse_line_id("p1a2b3c4d") is None
    assert door_routes.LINE_MAX >= len("123456:7200000")


# --- two lines that start together (two speakers at once): the id names a start, the word tells them apart ---

class _Steps:
    """Connect's steps as the press reads them: the item's subtitle (repeated_lines: cues 4 and 5 start at 7.000 s)."""

    def __init__(self, path):
        self.path = path

    def subtitle(self, language, job):
        return self.path


@pytest.mark.parametrize("word, said", [("でも", "でも まだ半分しか読んでない"), ("窓口", "早く窓口に返却しないと"),
                                        (None, "早く窓口に返却しないと")])
def test_two_lines_that_start_together_are_told_apart_by_the_word_pressed(word, said):
    # why: found by the page's test above — a subtitle where two speakers talk at once has two cues with one start, so
    # the line id (`<item>:<start ms>`) names both; ⇄ / *Add now* on the second made a card from the first's sentence.
    # The press is for a word (the door's body, the swap's row): of the cues at that start, the first that holds it.
    # No word, or none holds it: the first, as before (the clip: both cues are one span of audio)
    from app.connect import door_routes, swap
    steps = _Steps(os.path.join(cases.RES, "ja", "repeated_lines.ja.srt"))
    lid = swap.line_id(6, 7.0)
    got = swap.line_cue(steps, "ja", lid, word=word)
    assert got is not None and got[0] == 6 and got[1].text.replace("\n", " ") == said, (word, got)
    assert swap._resolve_line_id(steps, "ja", lid, word) == (6, got[1].text)
    if word is not None:
        assert door_routes._line(steps, "ja", lid, word) == (6, got[1].text)


def test_a_word_at_a_start_no_line_holds_takes_the_first_line_as_before():
    # why: edge case — a word inflected past its dictionary form (読む in 読んでない) or a start one cue alone has: the
    # first cue at that start, today's answer, never "gone"
    from app.connect import swap
    steps = _Steps(os.path.join(cases.RES, "ja", "repeated_lines.ja.srt"))
    assert swap.line_cue(steps, "ja", swap.line_id(6, 7.0), word="読む")[1].text == "早く窓口に返却しないと"
    assert swap.line_cue(steps, "ja", swap.line_id(6, 1.0), word="ない")[1].text == "図書館の鍵を忘れちゃった"
    assert swap.line_cue(steps, "ja", swap.line_id(6, 99.0), word="でも") is None

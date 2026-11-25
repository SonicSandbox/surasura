"""E-JOURNEY (the flip): a journey line with no audio shows a muted speaker while *Always include one with audio* is
on (SPEC § 4.5: such lines stay in their true order, marked silent).

The list's one reader (`analyzer.ListSentences`) keeps the shown lines no audio is heard from — `Line.heard` silent:
a book or a text with no audiobook and no AI voice — beside the text it keeps (results/shown.json.gz, "silent"); the
render reads them (`journey_render.silent_lines`) only at release 2 and while the setting is on, and gives each such
line a 5th field, 1; the page draws a muted speaker in the place of a ▶ that can't play. What these prove, on RP-2's
real Japanese and Chinese libraries (tests/plan_file_cases.py), each through a full Generate at level 2 in a child
process as the dashboard runs it (the setting on in its settings.json), then the page drawn again with the setting
off and at level 0:
  - the reader's silent lines are exactly the shown lines from a text (no audiobook, AI voice off) — none from a
    subtitle episode; with the AI voice on, none (its lines are heard), and the file says so;
  - the page's data marks each such line and no other with the setting on, none with it off or below release 2, and
    its lines otherwise the same;
  - in headless Edge, a marked line shows the muted speaker (its name, tip and label) and no ▶; with the setting off
    no line does; a marked line whose file can play keeps its ▶ (the mark is never beside a ▶ that plays).
"""
import base64
import csv
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import types

import pytest

from app import journey_render, plan_rules
from tests import plan_file_cases as cases

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journey_page_fixture as fx  # noqa: E402
from journey_page_edge import find_edge  # noqa: E402

SHOWN = "shown.json.gz"
PAGE = "reading_list_static.html"
CHUNK = re.compile(r'<script type="application/gzip-base64" id="j-c(\d+)">([A-Za-z0-9+/=]+)</script>')
TEXT_KINDS = ("text", "epub")       # a book or a text: heard from nothing without an audiobook or the AI voice


def _env(root, level=2):
    env = cases.child_env(root)
    env["SURASURA_SENTENCE_TABLE"] = str(level)
    return env


def _child(root, script, *args, level=2):
    p = subprocess.run([sys.executable, "-c", script, *args], cwd=cases.REPO, env=_env(root, level),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    return p.stdout


def _setting(root, on):
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"ensure_audio_example": on}, f)


_RENDER = r"""
import sys
from app import static_html_generator as gen
gen._write_journey(sys.argv[1], open_browser=False)
"""


def _drawn(root, language, name, on, level=2):
    """The journey drawn again from the root's last Generate (the window's own call), the setting `on` and the
    switch at `level` -> the page's path, kept as `name`."""
    _setting(root, on)
    _child(root, _RENDER, language, level=level)
    keep = os.path.join(root, name)
    shutil.copy(os.path.join(root, "results", PAGE), keep)
    return keep


@pytest.fixture(scope="module", params=["ja", "zh"])
def run(request, tmp_path_factory):
    """One case's library, Generated at level 2 with *Always include one with audio* on; its page as the Generate
    wrote it, and drawn again with the setting off and at level 0 (setting on)."""
    language = request.param
    root = str(tmp_path_factory.mktemp(f"e-silent-{language}"))
    case = f"rp2-{language}"
    cases.build(root, case)
    _setting(root, True)
    cases.generate(root, case, extra_env={"SURASURA_SENTENCE_TABLE": "2"})
    results = os.path.join(root, "results")
    on = os.path.join(root, "page-on.html")
    shutil.copy(os.path.join(results, PAGE), on)
    off = _drawn(root, language, "page-off.html", False)
    below = _drawn(root, language, "page-level-0.html", True, level=0)
    _setting(root, True)
    return types.SimpleNamespace(language=language, case=case, root=root, results=results, on=on, off=off,
                                 below=below, tmp=tmp_path_factory)


def _shown_file(results):
    with gzip.open(os.path.join(results, SHOWN), "rb") as f:
        return json.loads(f.read())


def _listed_pairs(results):
    """{(Src, Context)} of every line the progressive list shows (the page's own rows)."""
    with open(os.path.join(results, "progressive_learning_list.csv"), encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    n = sum(1 for c in (rows[0] if rows else {}) if c.startswith("Context ") and c[8:].isdecimal())
    return {(r[f"Src {i}"], r[f"Context {i}"]) for r in rows for i in range(1, n + 1) if r[f"Context {i}"]}


def _page_lines(path):
    """[(the line as the page holds it, its source's row or None)] of every word in the page's chunks (a source's
    number is its chunk's: a marked line's longer JSON may close a chunk sooner, so lines are compared by the row)."""
    with open(path, encoding="utf-8") as f:
        html = f.read()
    found = sorted((int(n), data) for n, data in CHUNK.findall(html))
    assert found, "the page holds its chunks"
    out = []
    for _n, data in found:
        chunk = json.loads(gzip.decompress(base64.b64decode(data)))
        for w in chunk["w"]:
            for ln in w[9]:
                out.append((ln, chunk["src"][ln[1]] if len(ln) > 1 and ln[1] is not None else None))
    return out


def _kind(src):
    return src[1] if src else None


def _marked(ln):
    return len(ln) > 4 and ln[4] == 1


def _bare(ln, src):
    """The line without its mark and with its source's row for its number, as an unmarked one is written (no time:
    no trailing nulls)."""
    out = [ln[0], src] + list(ln[2:4])
    while out and out[-1] is None:
        out.pop()
    return out


# ---- the reader ----

def test_the_reader_keeps_as_silent_every_shown_line_from_a_text_and_none_from_a_subtitle(run):
    # why: SPEC § 4.5 — a line no audio is heard from (a book or a text with no audiobook, the AI voice off) is the
    # one the journey marks; a subtitle episode's line is heard (its own clip), never marked (RP-2's Chinese library
    # is texts only: there every shown line is silent)
    pairs = _listed_pairs(run.results)
    assert pairs, "the list shows lines"
    assert all(src.endswith((".txt", ".srt")) for src, _ in pairs), "RP-2 holds texts and subtitles only"
    data = _shown_file(run.results)
    silent = {tuple(p) for p in data.get("silent") or ()}
    texts = {(src, text) for src, text in pairs if src.endswith(".txt")}
    assert texts and silent == texts, (len(silent), len(texts), sorted(silent ^ texts)[:3])
    if run.language == "ja":
        assert any(src.endswith(".srt") for src, _ in pairs), "RP-2's Japanese list shows subtitle lines too"


_AI_ON = r"""
import json, sys
from app import analyzer
from app.connect import sentences as connect_sentences
connect_sentences.ai_voice = lambda *a, **k: True       # the AI voice on, installed, this language
language, results, keys = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
chooser = analyzer.ListSentences(language, 3, results_dir=results)
got = chooser([tuple(k) for k in keys], None)
chooser.keep()
print(json.dumps({"rows": 0 if got is None else len(got), "shown": len(chooser.kept), "silent": len(chooser.silent)}))
"""


def test_with_the_ai_voice_on_no_shown_line_is_silent_and_the_kept_file_says_so(run, tmp_path):
    # why: a book's line the AI voice can say is heard (its card gets the voice's audio): never marked. The kept file
    # is written again when only its silent lines moved (the AI voice switched on since), so the page reads none
    results = str(tmp_path / "results")
    shutil.copytree(run.results, results)
    before = _shown_file(results)
    assert before.get("silent"), "the Generate kept silent lines (the AI voice off)"
    with open(os.path.join(results, "progressive_learning_list.csv"), encoding="utf-8-sig", newline="") as f:
        keys = [[r["Word"], r["Reading"]] for r in csv.DictReader(f)]
    out = json.loads(_child(run.root, _AI_ON, run.language, results, json.dumps(keys, ensure_ascii=False))
                     .strip().splitlines()[-1])
    assert out["rows"] and out["shown"] and out["silent"] == 0, out
    after = _shown_file(results)
    assert "silent" not in after, "no silent line: the file as before the mark"
    if run.language == "zh":        # texts only: the voice moves every line alike, so the same lines are shown
        assert after["lines"] == before["lines"], "written again for its silent part alone"
    assert after["run_signature"] == before["run_signature"]


# ---- the page's data ----

def test_the_page_marks_each_silent_line_only_while_the_setting_is_on_at_release_2(run):
    # why: SPEC § 4.5 — with *Always include one with audio* on, a line with nothing to hear it from is marked in its
    # true place; off (the default) or below release 2, the page is the page of before
    on = _page_lines(run.on)
    marked = [(ln, src) for ln, src in on if _marked(ln)]
    assert marked, "the Generate's own page marks the silent lines"
    wrong = [(ln, src) for ln, src in on if _marked(ln) != (_kind(src) in TEXT_KINDS)]
    assert not wrong, (len(wrong), wrong[:3])
    assert all(len(ln) == 5 for ln, _ in marked), "the mark is the 5th field, nothing after it"
    if run.language == "ja":
        assert any(_kind(src) == "subtitle" for _ln, src in on), "subtitle lines are on the page, unmarked"
    for path in (run.off, run.below):
        lines = _page_lines(path)
        assert not [ln for ln, _ in lines if len(ln) > 4], (os.path.basename(path), "no line carries a 5th field")
        # the same lines otherwise: the mark adds nothing else to the page's data
        assert [_bare(ln, src) for ln, src in lines] == [_bare(ln, src) for ln, src in on], os.path.basename(path)


def test_silent_lines_reads_the_kept_file_only_at_release_2_with_the_setting_on(run, monkeypatch, tmp_path):
    # why: the render's one read of the mark — the kept file's silent part; nothing below release 2, with the setting
    # off, with no file or a damaged one (the page then marks nothing: never a failed render)
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 2)
    want = {tuple(p) for p in _shown_file(run.results)["silent"]}
    assert want
    assert journey_render.silent_lines(run.results, {"ensure_audio_example": True}) == want
    assert journey_render.silent_lines(run.results, {"ensure_audio_example": False}) == set()
    assert journey_render.silent_lines(run.results, {}) == set()
    assert journey_render.silent_lines(run.results, None) == set()
    assert journey_render.silent_lines(str(tmp_path), {"ensure_audio_example": True}) == set(), "no file"
    with open(os.path.join(str(tmp_path), SHOWN), "wb") as f:
        f.write(b"not gzip")
    assert journey_render.silent_lines(str(tmp_path), {"ensure_audio_example": True}) == set(), "a damaged file"
    other = str(tmp_path / "other")
    os.makedirs(other)
    shutil.copy(os.path.join(run.results, "plan.json.gz"), other)
    data = dict(_shown_file(run.results), run_signature="another run")
    with gzip.open(os.path.join(other, SHOWN), "wb") as f:
        f.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    assert journey_render.silent_lines(other, {"ensure_audio_example": True}) == set(), "another run's kept file"
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 1)
    assert journey_render.silent_lines(run.results, {"ensure_audio_example": True}) == set(), "below release 2"


# ---- the page, in headless Edge ----

needs_edge = pytest.mark.skipif(not find_edge(), reason="Edge isn't installed")

# Every word drawn in turn (the first `LIMIT`): for each line shown, [its number, marked, the mute's role / label /
# tip or null, the ▶'s state: true shown, false hidden (.none), null none]
_DRAW = r"""(async () => {
  const J = window.__J, p = J.page, rows = [], LIMIT = %d;
  for (let i = 0; i < p.count() && rows.length < LIMIT; i++) {
    await J.loadEp(i);
    const s = J.seq(i) || [];
    for (let wi = 0; wi < s.length && rows.length < LIMIT; wi++) {
      const id = s[wi], w = J.wordNow(id);
      if (!w) continue;
      J.go(i, wi);
      const els = document.querySelectorAll("#stage .ln[data-li]"), ks = J.shownLines(id, w).ks;
      rows.push([id, els.length, ks.map((k, q) => {
        const el = els[q], m = el && el.querySelector(".pl.mute"), b = el && el.querySelector("button.pl[data-play]");
        return [k, w[9][k][4] === 1, m ? [m.getAttribute("role"), m.getAttribute("aria-label"), m.getAttribute("data-tip")] : null,
                b ? !b.classList.contains("none") : null];
      })]);
    }
  }
  return rows;
})()"""


def _draw(e, path, limit=100_000):
    assert e.open("file:///" + path.replace("\\", "/")), e.errors()
    rows = e.evaluate(_DRAW % limit)
    assert rows, "the page drew its words"
    assert len(rows) == min(limit, e.evaluate("window.__J.page.head.counts.words")), "every word drawn"
    for _id, n, lines in rows:
        assert n == len(lines), "one line element a line shown"
    return [line for _id, _n, lines in rows for line in lines]


def _mute_ok(mute):
    role, label, tip = mute
    return role == "img" and label == "No audio" and (tip or "").startswith("No audio: ")


@needs_edge
def test_the_page_shows_a_muted_speaker_on_each_silent_line_and_none_with_the_setting_off(run):
    # why: the learner sees which lines have nothing to hear — the speaker in the ▶'s place, named first in its tip;
    # with the setting off the page is as before
    from journey_page_edge import Edge
    with Edge() as e:
        on = _draw(e, run.on)
        off = _draw(e, run.off)
        errs = e.errors()
    assert not errs, errs
    muted = [line for line in on if line[2] is not None]
    assert muted, "the silent lines drawn show the muted speaker"
    assert all(line[1] for line in muted) and all(line[2] is not None for line in on if line[1]), \
        "a muted speaker on each marked line and on no other"
    assert all(_mute_ok(line[2]) for line in muted), muted[:3]
    assert all(line[3] is None for line in muted), "no ▶ beside the muted speaker"
    assert not [line for line in off if line[1] or line[2] is not None], "the setting off: no line marked or muted"
    assert all(line[3] is not None for line in off), "the setting off: every line has its ▶ (shown or hidden)"


@needs_edge
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_marked_line_its_file_can_play_keeps_its_play_button(tmp_path, lang):
    # why: the mark stands only where ▶ can't play (SPEC § 4.5's mark replaces nothing that works). On the fixture
    # (no door), every other line is marked: an .mp3 line with a time plays (▶ kept), the rest show the speaker when
    # marked and the hidden ▶ when not
    from journey_page_edge import Edge
    parts = fx.build(lang, 40)
    can = {}
    for c in parts["chunks"]:
        for j, w in enumerate(c["w"]):
            for k, ln in enumerate(w[9]):
                can[(c["w0"] + j, k)] = c["src"][ln[1]][3].endswith(".mp3") and ln[2] is not None
                if k % 2 == 0:
                    ln.append(1)
    path = os.path.join(str(tmp_path), f"marked-{lang}.html")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(fx.assemble(parts))
    with Edge() as e:
        assert e.open("file:///" + path.replace("\\", "/")), e.errors()
        rows = e.evaluate(_DRAW % 400)
        errs = e.errors()
    assert rows and not errs, errs
    seen = {"marked, plays": 0, "mute": 0, "hidden": 0}
    for wid, _n, lines in rows:
        for k, marked, mute, play in lines:
            assert marked == (k % 2 == 0), (wid, k)
            if can[(wid, k)]:
                assert mute is None and play is True, (wid, k, "a line that plays keeps its ▶")
                seen["marked, plays"] += marked
            elif marked:
                assert mute is not None and _mute_ok(mute) and play is None, (wid, k, mute, play)
                seen["mute"] += 1
            else:
                assert mute is None and play is False, (wid, k, "no mark: the hidden ▶ of before")
                seen["hidden"] += 1
    assert all(seen.values()), seen

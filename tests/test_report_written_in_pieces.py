"""The report's HTML is written in pieces — the template's, the data, the settings — never joined into one string: the
data (tens of MB of ASCII) joined with a file name's emoji became a string of four bytes a character, copied again by
each replacement (the favicon, the logo), some 300 MB at a Generate's peak. The file is byte for byte what joining the
whole and replacing in it wrote — user text holding the very strings replaced (<head>, the heading) included."""

import json
import os
import random
from functools import reduce
from unittest.mock import patch

import pandas as pd

from app import static_html_generator as gen

MARKER = "let globalData = null;"
ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(gen.__file__))), "app", "assets", "images",
                    "app_icon.png")
HEAD = ("<head>", "<head>\n    <link rel=\"icon\" href=\"data:image/png;base64,iVBORw0KGgo=\">")
LOGO = ("<h1>Surasura List</h1>", "<div style=\"display:flex;\"><img alt=\"Logo\"><h1>Surasura List</h1></div>")


def _as_one_string(template, injected, replacements):
    """What the report was before it was written in pieces: the whole joined, each replacement made in it."""
    return reduce(lambda text, pair: text.replace(*pair), replacements, template.replace(MARKER, "".join(injected)))


def _injected(data, sources):
    """The pieces generate_static_html puts in the template's place: the data, then the settings."""
    return ["let globalData = ", json.dumps(data).replace("</", "<\\/"),
            ";\n        let globalTheme = 'default';\n        let globalSources = "
            + json.dumps(sources, ensure_ascii=False).replace("</", "<\\/") + ";"]


def test_the_pieces_are_the_one_string_for_text_that_holds_what_is_replaced():
    """Sentences, file names and the template holding <head>, the heading, their parts, ';' and '}' anywhere — the
    joined pieces equal the one string, with no replacement, one, or both; a template with the marker twice, or none."""
    rng = random.Random(20261001)
    bits = ["冒険に出かけた。", "<head>", "<he", "ad>", "<h1>Surasura List</h1>", "<h1>Surasura", " List</h1>", ";", "}",
            "{", "let", "let globalData = null;", "</script>", "\r\n", "\n", "🥲", "ﾅｲﾌ", "<", "= "]

    def text(n):
        return "".join(rng.choice(bits) for _ in range(rng.randint(0, n)))

    for _ in range(400):
        data = {"words": [[text(6), text(3)] for _ in range(rng.randint(0, 4))], "title": text(4)}
        sources = [text(5) for _ in range(rng.randint(0, 3))]
        markers = rng.choice([0, 1, 1, 1, 2])
        template = text(8) + "".join(MARKER + text(8) for _ in range(markers))
        injected = _injected(data, sources)
        for replacements in ([], [HEAD], [HEAD, LOGO], [LOGO]):
            assert "".join(gen._html_pieces(template, injected, replacements)) == \
                _as_one_string(template, injected, replacements), (template, injected, replacements)


def _results(tmp_path):
    """A small run's results: a word whose example holds <head> and the heading as text, from a file whose name holds
    an emoji (text beyond Latin-1 in the sources)."""
    results = tmp_path / "results"
    results.mkdir()
    source = "@旅の記録 - 冒険の始まり🥲 [abc].txt"
    pd.DataFrame([{"Word": "冒険", "Reading": "ボウケン", "Tier": "Outside", "Score": 10, "Occurrences": 4,
                   "Count (High)": 1, "Count (Low)": 1, "Count (Goal)": 2, "Sources": source,
                   "Context 1": "看板に<head>と<h1>Surasura List</h1>と書いてあった。",
                   "Context 2": "冒険に出かけた。\r\n</script>"}]
                 ).to_csv(results / "priority_learning_list.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"Sequence": 1, "Source File": source, "Word": "冒険", "Reading": "ボウケン", "Tier": "Outside",
                   "Score": 10, "Occurrences (Global)": 4, "Occurrences (File)": 1, "Count (High)": 0,
                   "Count (Low)": 0, "Count (Goal)": 2, "Context 1": "冒険に出かけた。"}]
                 ).to_csv(results / "progressive_learning_list.csv", index=False, encoding="utf-8-sig")
    (results / "sources.json").write_text(json.dumps({source: {"name": source, "type": "youtube"}},
                                                     ensure_ascii=False), encoding="utf-8")
    return results


def test_the_written_report_is_the_one_string_byte_for_byte(tmp_path):
    """End to end: the file generate_static_html writes holds exactly the one string the pieces join to (the favicon
    and the logo made in it, newlines written as the platform writes them), and the data piece is plain ASCII — the
    string that never meets the sources' emoji."""
    results = _results(tmp_path)
    out = results / "reading_list_static.html"
    seen = []
    real = gen._html_pieces

    def recording(template, injected, replacements=()):
        seen.append((template, list(injected), list(replacements)))
        return real(template, injected, replacements)

    with patch.object(gen, "RESULTS_DIR", str(results)), \
         patch.object(gen, "PRIORITY_CSV", str(results / "priority_learning_list.csv")), \
         patch.object(gen, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")), \
         patch.object(gen, "OUTPUT_FILE", str(out)), patch.object(gen, "_html_pieces", recording), \
         patch("app.path_utils.get_icon_path", lambda: ICON):
        gen.generate_static_html(theme="default", open_browser=False)
    [(template, injected, replacements)] = seen
    assert [old for old, _new in replacements] == ["<head>", "<h1>Surasura List</h1>"], "the favicon and the logo"
    expected = _as_one_string(template, injected, replacements)
    assert out.read_bytes() == expected.replace("\n", os.linesep).encode("utf-8")
    assert injected[1].isascii(), "the data piece stays ASCII (its emoji escaped), whatever the other pieces hold"
    assert "\\ud83e\\udd72" in injected[1], "the file name's emoji, escaped in the data"
    assert expected.count("data:image/png;base64,") >= 3, "the favicon in the template's <head> and the sentence's"

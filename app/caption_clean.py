"""Japanese TV captions (字幕放送), cleaned for card-making (P1.3 row 1.3.2, HC-B27; ✅ G1.3-11: in Surasura).

A broadcast .ass writes a word's reading as a row of its own in small type above it ({\\fscx50\\fscy50}ようし), cuts one
caption into rows that share one timing, and ends a row that runs on with an arrow (➡). Read as they are, the reading
rows are lines of their own — a word's card can be cut from a furigana row — the rows of one caption are separate
lines, and an arrow ends up in a card's sentence. `clean(content)` returns the file with:

- every reading row dropped: an event whose text is kana only and is drawn in small type (an override's \\fscx and
  \\fscy, or its style's ScaleX / ScaleY, both at most SMALL percent);
- the rows a caption is cut into joined: back-to-back events with one start, one end, one style colour — what a
  Generate already reads as one caption (`analyzer._captions`) — become one event, the rows kept apart by \\N;
- an arrow at the end of a row taken off (a dash stays: it can be speech drawn out) — in the copy a job hands Anki
  Miner (`arrows=True`, its cards' sentences). A Generate and the cue reader read the arrows (`arrows=False`): an arrow
  is how a row says its sentence runs on (`analyzer.close_cue`), so it is no text there either, but the row it ends
  isn't closed as a sentence. The lines and their times are the same both ways.

Everything else is the file's own, byte for byte as text. `copy_for(path, folder)` writes the cleaned copy a job reads
— the pick and Anki Miner both, so their lines and times are the same lines and times (IS:293) — UTF-8 without a BOM;
an .srt needs none and is read where it is. Standard library only.
"""
import os
import re

from app import analyzer
from app.path_utils import read_text

SMALL = 60                                  # percent: a reading row's type is half size (50) on broadcast captions
ARROWS = "➡➨→⇒➔►"
_SCALE_RE = re.compile(r"\\fsc([xy])(\d+(?:\.\d+)?)")
_KANA_ONLY_RE = re.compile(r"^[\u3041-\u309f\u30a1-\u30ffー・\s　]+$")


def _fields(line, count):
    """A Dialogue line's fields: the part before "Dialogue:" kept apart, the text field whole (it may hold commas)."""
    head, rest = line.split(":", 1)
    return head, rest.split(",", count - 1)


def clean(content, arrows=True):
    """`content` (an .ass / .ssa file's text) cleaned (§ above); `arrows`: take the rows' arrows off too."""
    lines = content.split("\n")
    styles, scale_x, scale_y, colour_at = {}, None, None, 3
    fields, events, out = None, False, []
    for line in lines:
        bare = line.strip()
        if bare.startswith("[") and bare.endswith("]"):
            events = bare == "[Events]"
        elif not events and bare.startswith("Format:"):
            names = [f.strip() for f in bare[7:].split(",")]
            scale_x = names.index("ScaleX") if "ScaleX" in names else None
            scale_y = names.index("ScaleY") if "ScaleY" in names else None
            colour_at = names.index("PrimaryColour") if "PrimaryColour" in names else 3
        elif not events and bare.startswith("Style:"):
            parts = [p.strip() for p in bare[6:].split(",")]
            small = all(i is not None and i < len(parts) and _number(parts[i]) <= SMALL for i in (scale_x, scale_y))
            colour = analyzer._ass_colour_value(parts[colour_at]) if colour_at < len(parts) else ""
            styles[parts[0]] = (small, colour)
        elif events and bare.startswith("Format:"):
            fields = [f.strip() for f in bare[7:].split(",")]
        out.append(line)
    if fields is None or "Text" not in fields:
        return content
    at = {name: fields.index(name) for name in ("Start", "End", "Style", "Text") if name in fields}
    count = len(fields)

    cleaned, last = [], None                # last: (index in cleaned, start, end, colour) of the event to join onto
    for line in out:
        if not line.lstrip().startswith("Dialogue:"):
            cleaned.append(line)
            last = None if line.strip() else last
            continue
        head, parts = _fields(line.rstrip("\r"), count)
        if len(parts) < count:
            cleaned.append(line)
            last = None
            continue
        text = parts[at["Text"]]
        style_small, style_colour = styles.get(parts[at["Style"]].strip(), (False, ""))
        if _reading_row(text, style_small):
            continue
        text = _arrow_off(text) if arrows else text
        timing = (parts[at["Start"]].strip(), parts[at["End"]].strip())
        colour = analyzer._ass_colour(text, style_colour, {k: c for k, (_s, c) in styles.items()})
        if last is not None and last[1:] == (*timing, colour):
            index = last[0]
            h, p = _fields(cleaned[index], count)
            p[at["Text"]] = p[at["Text"]] + "\\N" + text
            cleaned[index] = h + ":" + ",".join(p)
            continue
        parts[at["Text"]] = text
        cleaned.append(head + ":" + ",".join(parts))
        last = (len(cleaned) - 1, *timing, colour)
    return "\n".join(cleaned)


def _number(text):
    try:
        return float(text)
    except ValueError:
        return 100.0


def _reading_row(text, style_small):
    """Is this event a reading row: kana only, in small type (its own \\fscx / \\fscy, else its style's)?"""
    seen = {axis: float(value) for axis, value in _SCALE_RE.findall(text)}
    small = (seen.get("x", 100.0 if not style_small else 0.0) <= SMALL
             and seen.get("y", 100.0 if not style_small else 0.0) <= SMALL)
    words = analyzer._ASS_BLOCK_RE.sub("", text).replace("\\N", "").replace("\\n", "").replace("\\h", "")
    return small and bool(words.strip()) and bool(_KANA_ONLY_RE.match(words))


def _arrow_off(text):
    """`text` without the arrow its row ends on (after any closing override blocks)."""
    end = len(text)
    while True:
        blocks = list(analyzer._ASS_BLOCK_RE.finditer(text[:end]))
        if blocks and blocks[-1].end() == end:
            end = blocks[-1].start()
            continue
        break
    head = text[:end].rstrip()
    stripped = head.rstrip(ARROWS).rstrip()
    return text if stripped == head else stripped + text[end:]


def copy_for(path, folder, language="ja"):
    """The subtitle a job reads: an .ass / .ssa file's cleaned copy written into `folder` (UTF-8, no BOM, its own
    name), or `path` itself for any other subtitle."""
    if not str(path).lower().endswith((".ass", ".ssa")):
        return path
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, os.path.basename(path))
    if os.path.abspath(dest) == os.path.abspath(path):
        raise ValueError("the cleaned copy would overwrite the subtitle itself")
    tmp = f"{dest}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(clean(read_text(path, language)))
    os.replace(tmp, dest)
    return dest

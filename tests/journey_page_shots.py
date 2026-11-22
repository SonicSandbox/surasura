"""Pictures of the journey page for a person to look at (not a test): ja / zh, Night / Light, 100 % and 150 %, at 1280,
800 and 390 px wide, on the fixture, the meaning open on the first episode with words.

    python tests/journey_page_shots.py <out folder> [episodes]
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import journey_page_fixture as fx  # noqa: E402
from journey_page_edge import Edge  # noqa: E402

SHOW = """(async () => {
  const J = window.__J, p = J.page;
  let E = 0;
  for (let i = 0; i < p.count(); i++) { const e = p.ep(i); if (!e.watched && e.new >= 3 && e.id != null) { E = i; break; } }
  J.setSetting("theme", "%s");
  J.go(E, 1); await J.loadEp(E); J.drawWord();
  if (!J.S.open.meaning) J.doAction("meaning");
  await J.blob("meanings"); await J.blob("kanji"); J.drawDesk();
  await new Promise((r) => setTimeout(r, 300));
  return true;
})()"""


def shoot(out, n=2000):
    os.makedirs(out, exist_ok=True)
    folder = tempfile.mkdtemp(prefix="j-page-shots-")
    made = []
    for lang in ("ja", "zh"):
        path = os.path.join(folder, f"journey-{lang}.html")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(fx.assemble(fx.build(lang, n)))
        url = "file:///" + path.replace("\\", "/")
        views = [(w, s, t) for t in ("night", "light") for s in (1.0, 1.5) for w in (1280,)]
        views += [(w, 1.0, "night") for w in (800, 390)]
        for width, scale, theme in views:
            with Edge(width, 800, scale) as e:
                e.open(url)
                e.evaluate(SHOW % theme)
                time.sleep(0.2)
                name = os.path.join(out, f"{lang}-{theme}-{int(scale * 100)}-{width}.png")
                e.screenshot(name)
                made.append(name)
    return made


if __name__ == "__main__":
    for p in shoot(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 2000):
        print(p)

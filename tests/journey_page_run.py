"""Run the journey page's self-checks in headless Edge: one page assembled from the fixture (or J-DATA's render), opened
twice (the second open is the warm one, as the speed rows are measured), `?selftest=1` and its query, the results back.

    python tests/journey_page_run.py ja 2000 [query] [--html out.html]
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import journey_page_fixture as fx  # noqa: E402
from journey_page_edge import Edge  # noqa: E402

SELFTEST = os.path.join(HERE, "journey_page_selftest.js")


def page_file(folder, lang, n, rail_css=None, rail_js=None, parts=None):
    with open(SELFTEST, encoding="utf-8") as f:
        st = f.read()
    path = os.path.join(folder, f"journey-{lang}-{n}.html")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(fx.assemble(parts or fx.build(lang, n), rail_css=rail_css, rail_js=rail_js, extra_js=st))
    return path


def run(path, query="", width=1280, height=800, seconds=120):
    url = "file:///" + path.replace("\\", "/")
    with Edge(width, height) as e:
        e.open(url)                                      # cold, then warm (the speed rows' way)
        e.open(url + "?selftest=1" + ("&" + query if query else ""), until="window.__selftest && window.__selftest.total", seconds=seconds)
        res = e.evaluate("JSON.stringify(window.__selftest || null)")
        errs = e.errors()
    return (json.loads(res) if res else None), errs


if __name__ == "__main__":
    lang, n = sys.argv[1], int(sys.argv[2])
    query = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else ""
    folder = os.environ.get("J_PAGE_OUT") or tempfile.mkdtemp(prefix="j-page-run-")
    t = time.time()
    path = page_file(folder, lang, n)
    print(f"page {os.path.getsize(path) / 1e6:.2f} MB, built in {time.time() - t:.1f} s")
    res, errs = run(path, query)
    if not res:
        print("NO RESULT", errs)
        sys.exit(2)
    for name, good, detail in res["out"]:
        if not good or "-v" in sys.argv:
            print(("ok   " if good else "FAIL ") + name + (" — " + detail if detail else ""))
    print("errors:", errs)
    print("speed:", json.dumps(res["SPEED"]))
    if "--budgets" in sys.argv:
        for b in res["BUDGETS"]:
            print("budget:", " | ".join(str(x) for x in b))
    print(f"{res['pass']}/{res['total']}")

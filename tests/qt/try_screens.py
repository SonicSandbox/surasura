"""G2.3's local build (W2.2 row 6): the 3.0 window on the stand-in store, for Sonic to try the first screens — never a
release, and nothing of his read or written.

    python tests/qt/try_screens.py [--files N] [--language ja|zh] [--theme sapphire|hb|sky] [--size S|M|L]
                                   [--mode store|json|read-only]

It makes a temp folder, sets it as the window's whole world (`SURASURA_TEST_ROOT`: its settings, its window state, its
library), builds the synthetic seed there (invented titles; `--files` 2,000 or 20,000 for a big library), and opens the
shell on it: Current (the hero, the rows, the top-20 and Soon lines, the Goal strip), Finished and Needs you. Display
only: rows open and close, ▶ looks for a video beside the file; moving things arrives with the next build (W3.1).
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Try the 3.0 window's first screens on an invented library")
    ap.add_argument("--files", type=int, default=0, help="0: the small seed (about 40 rows); else 2000, 20000…")
    ap.add_argument("--language", default="ja", choices=("ja", "zh"))
    ap.add_argument("--theme", default="sapphire", choices=("sapphire", "hb", "sky"),
                    help="sapphire (the default since G2.3) · hb: Blue · sky: Lighter blue")
    ap.add_argument("--size", default="M", choices=("S", "M", "L"))
    ap.add_argument("--mode", default="store", choices=("store", "json", "read-only"))
    ap.add_argument("--keep", action="store_true", help="keep the temp folder afterwards")
    a = ap.parse_args(argv)
    work = tempfile.mkdtemp(prefix="surasura-try-screens-")
    os.environ["SURASURA_TEST_ROOT"] = work
    os.environ.pop("QT_QPA_PLATFORM", None)
    # the test root is also where bundled resources are read: without the mark the header showed no logo (G2.3 C1)
    shutil.copytree(os.path.join(ROOT, "app", "assets"), os.path.join(work, "app", "assets"))
    with open(os.path.join(work, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"target_language": a.language, "app_theme": a.theme, "text_size": a.size,
                   "zh_script": "s"}, f)
    from PyQt6.QtWidgets import QApplication

    from app.qt import shell
    from app.services import library_reader
    from tests.fixtures import window_seed

    reason = {"json": "not ready", "read-only": "damaged"}.get(a.mode)
    seed = window_seed.build(files=a.files or window_seed.SMALL, language=a.language, root=work, mode=a.mode,
                             reason=reason)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    shell.prepare_process()
    reader = library_reader.LibraryReader(seed.opener, language=a.language, numbers=seed.numbers,
                                          mining=seed.mining, cache_file=library_reader.cache_path(a.language),
                                          freeze_gc=True)
    services = shell.Services(library=reader)
    window = shell.open_window(app, services)
    window.show_first()
    try:
        return app.exec()
    finally:
        services.shutdown()
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

# SPDX-License-Identifier: GPL-3.0-or-later
"""The preview's scoring child (W3.4 row 4; the adversary's AD4-2, the intent keeper's IK-29): from source
`python modules/youtube_downloader/preview_child.py --language <l> --out <html> <transcript>…`, frozen
`Surasura.exe youtube_preview --headless …` (app_entry.py). The tokenizer and the analyzer's globals live here, in a
process of their own, never in the window's; `preview.child_main` answers in one line."""
import os
import sys

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    if sys.path and os.path.abspath(sys.path[0] or ".") == here:
        sys.path.pop(0)                                   # the module's own folder never shadows a top-level import
    from modules.youtube_downloader import preview
    sys.exit(preview.child_main(sys.argv[1:]))

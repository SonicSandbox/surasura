# Licence texts the build supplies

`package_app.py` (step 3b) copies every bundled part's licence texts into the program's `_internal\licenses\` and lists
them in its `INDEX.txt`. Most come from the installed distribution itself (its `LICENSE`, `COPYING`, `NOTICE` files and
its `.dist-info/licenses/`). These parts ship without one, so their texts are kept here, unchanged, as their upstream
repositories publish them (fetched 2026-11-10):

| Folder | Part | Licence | From |
| --- | --- | --- | --- |
| `jieba/` | jieba 0.42.1 (its sdist installs no licence file) | MIT | https://github.com/fxsjy/jieba/blob/master/LICENSE |
| `pysrt/` | pysrt 1.1.2 (its sdist installs no licence file) | GPL-3.0 | https://github.com/byroot/pysrt/blob/master/LICENCE.txt |
| `OpenCC/` | OpenCC 1.4.2's tables, distilled into `app/zh_script_data.py` | Apache-2.0 | https://github.com/BYVoid/OpenCC/blob/ver.1.4.2/LICENSE |
| `PyQt6-Qt6/` | Qt 6.11.2's own third-party components (`Qt-third-party-notices.txt`: PCRE2, FreeType, HarfBuzz, libpng, libjpeg, zlib, the Unicode data …), which the PyQt6-Qt6 wheel carries compiled in but ships no notice of | each its own (the file lists them) | written by `scripts/build_qt_notices.py 6.11.2` from Qt's `qt_attribution.json` files at the `v6.11.2` tag of https://github.com/qt/qtbase, qtsvg and qtimageformats; a PyQt6-Qt6 of another version stops `--check` until it is run again |

A folder is named after the part as `package_app.licence_components` names it (a distribution's own name). A new
bundled part without a licence file stops the build, named: add its text here (and a row above), or, after a review,
name it in `package_app.LICENCE_EXCEPTIONS`.

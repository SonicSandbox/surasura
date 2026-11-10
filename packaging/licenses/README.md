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
| `OpenSSL/` | OpenSSL 3.5 for Qt's TLS (`libssl-3-x64.dll`, `libcrypto-3-x64.dll`), when the build finds them on its PATH | Apache-2.0 | https://github.com/openssl/openssl/blob/openssl-3.5/LICENSE.txt |

A folder is named after the part as `package_app.licence_components` names it (a distribution's own name). A new
bundled part without a licence file stops the build, named: add its text here (and a row above), or, after a review,
name it in `package_app.LICENCE_EXCEPTIONS`.

"""The data credits (W3.3 P1): every data source Surasura ships or is built from, with its licence, and the licence
line of Surasura itself. Moved from `app/main.py` (a pure move: the Tk dashboard imports them from here under its own
names) so the 3.0 window's Settings reads them without Tk. Pure: no Tk, no Qt.
"""
import os
import re
import sys

from app import path_utils


# Settings -> Data & System -> Credits (a hover): every data source Surasura ships or is built from — the licences ask
# for it wherever the data goes, and an in-place update carries only the app, never README. Keep it with README's Data
# Credits, and with the generated modules that name their source (app/*_data.py). {jmdict} is JMdict's own date.
DATA_CREDITS = """Data credits — what Surasura ships or is built from

Dictionaries
• JMdict and JMnedict (JMdict created {jmdict}) — the Electronic Dictionary Research and Development Group (EDRDG), CC BY-SA 4.0: the set phrases, which compounds are phrases or titles, the お / ご words of their own, the words the tokenizer cuts at their grammar (くだらない, いつも), kanji spellings, the one-kanji words the list can offer, and person names (via anki_miner's name lists). Those tables are shared under the same licence.
• UniDic, as unidic-lite — the UniDic Consortium, BSD licence; read by MeCab (BSD) through fugashi (MIT): how Japanese is split into words.
• jieba — MIT licence: how Chinese is split into words.
• OpenCC 1.4.2 — Carbo Kuo and contributors, Apache License 2.0: Simplified and Traditional Chinese, Traditional in Taiwan's standard characters.
• CC-CEDICT — MDBG, CC BY-SA 4.0: which of jieba's phrases are words, the numbers and doubled forms Chinese counts as their word, the Traditional spellings read as their Simplified pair, the surnames a name jieba guesses starts with, and the Chinese measure words. Those tables (app/cedict_data.py, and those phrases of app/zh_script_data.py) are shared under the same licence.
• Universal Dependencies Chinese treebanks (GSDSimp, HK, CFL) — CC BY-SA 4.0: which Chinese counts are a number and a measure word (一个 is 一 + 个).

Frequency lists (ranks only)
• JPDB 2024 and Jiten: which compounds, affixed words, set phrases, adverbs cut at their particles and one-kanji words are words, and which words live only inside a phrase.
• TMW Netflix, Anime & J-drama, Novels and VN lists: the 文 reading-word badge.

Text, counted into statistics only (never a sentence)
• RealPersonaChat — Yamashita et al. (2023), CC BY-SA 4.0.
• Aozora Bunko — public-domain works, via aozorabunko-clean (CC BY 4.0).
• Japanese and Chinese Wikipedia — Wikipedia contributors, CC BY-SA 4.0.
• Leipzig Corpora Collection — Universität Leipzig, CC BY 4.0: Japanese news and web text, Chinese news.
• Tatoeba — CC BY 2.0 FR. KdConv — Zhou et al. (2020), Apache License 2.0. Chinese Wikinews — CC BY 4.0.

The shared パターン data is shared under CC BY-SA 4.0."""


def data_credits():
    """DATA_CREDITS with JMdict's date, as the shipped dictionary table records it ("unknown" when it can't be read)."""
    try:
        from app import dictionary_data
        created = dictionary_data.JMDICT_CREATED
    except Exception:
        created = ""
    return DATA_CREDITS.replace("{jmdict}", created or "unknown")


# The services' logos the 3.0 window's Settings › Connections shows (W3.3 PL; app/qt/logos.py, app/assets/logos/),
# each with the notice its owner asks for (the planning folder's tracks/window/work/w33/logos/LOGOS.md). Kept apart
# from DATA_CREDITS, which stays 2.4's text: the Tk dashboard never shows these logos. The TMDB notice is the API
# terms' own wording, word for word.
LOGO_CREDITS = """Logos

• Anki® is a registered trademark of Ankitects Pty Ltd. Surasura is not affiliated with or endorsed by the Anki project: it is SonicSandbox's own work. https://apps.ankiweb.net — Anki's icon (Settings › Connections) and its outline star (the bottom bar's phase strip) are copyright Alex Fraser, AGPL-3.0, used unmodified under its limited alternative licence (app/assets/logos/LICENSE-anki.txt).
• Anki Miner icon © 0xzerolight (Zero), GPL-3.0 (app/assets/logos/LICENSE-anki_miner.txt), https://github.com/0xzerolight/anki_miner; its 鉱 is an outline from Shippori Mincho B1 (SIL OFL 1.1).
• hato and tsubasa icons — SonicSandbox, GPL-3.0-or-later.
• This application uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB."""


# The covers the 3.0 window downloads with *Download covers* on (W3.2 Q7, `app/services/covers_online.py`): never
# shipped, fetched on the user's machine. Kept apart from DATA_CREDITS (2.4's text: the Tk dashboard downloads none).
COVER_CREDITS = """Covers (only with Download covers on)

• AniList (https://anilist.co) — anime covers, fetched from AniList's API and image server.
• YouTube — a video's own thumbnail (i.ytimg.com)."""


# The AI voice's beta (Iro-AA, `modules/irodori`): downloaded on the learner's *Install* only, never shipped; shown
# while the module is in the program
AI_VOICE_CREDITS = """AI sentence audio (beta, only once installed)

• Irodori-TTS v4.1 Small and Irodori-TTS-Server (https://github.com/Aratako/Irodori-TTS) — Aratako, MIT. Its model card asks that no real person's voice be copied without their consent.
• Semantic-DACVAE-Japanese (the voice's codec) — Aratako, MIT.
• SilentCipher (the inaudible watermark on every AI clip) — Sony, MIT.
• Installed with uv (Astral, MIT / Apache 2.0), its own Python and PyTorch (BSD)."""


def _ai_voice_here():
    import importlib.util
    try:
        return importlib.util.find_spec("modules.irodori") is not None
    except (ImportError, ValueError):
        return False


# The user's own content (Sonic, 2026-11-02): the installer's agreement page (packaging/agreement.txt) and README's
# *Your content* say it in full; the Data credits card ends with it in one line.
CONTENT_NOTE = """Your content

• Surasura provides no content: you are responsible for the content you use with it. Use only content you own or have the right to use (README's Your content)."""


# Surasura's own licence and the libraries the program bundles (the licence switch, 3.0): the GPL asks that the
# source be offered wherever the program goes, and the bundled libraries keep their notices (the build, package_app.py
# step 3b, copies every bundled part's texts into _internal\licenses and lists them in its INDEX.txt: `bundled()`).
SOFTWARE_NOTE = """Surasura and the software it bundles

• Surasura — SonicSandbox, GNU General Public License version 3 or later, with an additional permission (LICENSE and LICENSE-EXCEPTION.md beside the program). It comes with no warranty. Its source code is free to get, read and change: https://github.com/SonicSandbox/surasura. Versions up to 2.5.x were released under the MIT License (licenses\\Surasura-MIT-before-3.0.txt).
• The window: PyQt6 — Riverbank Computing, GPL-3.0; Qt 6 — The Qt Company, LGPL-3.0.
• Every library and part it bundles keeps its own licence — among them tsubasa (GPL-3.0-or-later), pysrt (GPL-3.0), EbookLib (AGPL-3.0-or-later), pandas and numpy (BSD), fugashi, jieba and Beautiful Soup (MIT), requests (Apache License 2.0). Each one's licence text is in the program's _internal\\licenses folder, listed in its INDEX.txt with its version; Qt's own third-party components are listed at https://doc.qt.io/qt-6/licenses-used-in-qt.html.
• The source code of each bundled library is its own project's, at the version INDEX.txt names: the Python packages' on PyPI (https://pypi.org), Qt's at https://download.qt.io/archive/qt/."""

# The build's list of the bundled software (package_app.py step 3b): <the program's _internal>\licenses\INDEX.txt, one
# "name · version · licence · its texts" line each.
BUNDLED_INDEX = ("licenses", "INDEX.txt")


def bundled():
    """The software the program bundles, as its _internal\\licenses\\INDEX.txt lists it -> [(name, version, licence)];
    [] from source or when the index can't be read."""
    if not path_utils.is_frozen():
        return []
    try:
        with open(os.path.join(getattr(sys, "_MEIPASS", ""), *BUNDLED_INDEX), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    rows = []
    for line in lines:
        cells = line.split(" · ")
        if line.strip() and not line.startswith("#") and len(cells) >= 4:
            rows.append((cells[0].strip(), cells[1].strip(), cells[2].strip()))
    return rows


def software_note():
    """`SOFTWARE_NOTE`, then each part the program bundles with its version and licence (`bundled()`), when listed."""
    rows = bundled()
    if not rows:
        return SOFTWARE_NOTE
    listed = "\n".join(f"  {name} {version} — {licence}" if version != "-" else f"  {name} — {licence}"
                       for name, version, licence in rows)
    return SOFTWARE_NOTE + "\n\nBundled with this program (_internal\\licenses\\INDEX.txt)\n" + listed


def all_credits():
    """`data_credits()` followed by the logos' and the covers' credits, Surasura's own licence and the software it
    bundles (`software_note()`), then the user's own content (`CONTENT_NOTE`): what the 3.0 window's Data credits
    shows."""
    voice = AI_VOICE_CREDITS + "\n\n" if _ai_voice_here() else ""
    return data_credits() + "\n\n" + LOGO_CREDITS + "\n\n" + COVER_CREDITS + "\n\n" + voice + software_note() + \
        "\n\n" + CONTENT_NOTE


# --- Surasura's own licence (the `LICENSE` file: its first line and its copyright line) --------------------------- #
LICENCE_FILE = "LICENSE"
# Since 3.0 `LICENSE` is the GPL's own text: it names no program, says no "or later", and its copyright line is the
# Free Software Foundation's (on the licence's words, never on Surasura). So a GPL version 3 `LICENSE` is named as
# Surasura applies it, with the copyright line of Surasura's own notice beside it (the written exception).
EXCEPTION_FILE = "LICENSE-EXCEPTION.md"
GPL_TITLE, GPL_VERSION = "GNU GENERAL PUBLIC LICENSE", "Version 3,"
GPL_NAME = "GNU General Public License, version 3 or later (GPL-3.0-or-later)"
_LICENCE = []               # read once, the first time it is asked for


def _licence_folders():
    """Where `LICENSE` is looked for: the project root from source; beside the program (README's folder) and in its
    bundle when frozen."""
    if path_utils.is_frozen():
        return [os.path.dirname(sys.executable), getattr(sys, "_MEIPASS", "")]
    return [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]


def _text_lines(path):
    """The file's lines that hold text, stripped; None when it can't be read."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return [text.strip() for text in f.read().splitlines() if text.strip()]
    except (OSError, UnicodeDecodeError):
        return None


def licence_line():
    """`LICENSE`'s first line and its copyright line ("MIT License · Copyright (c) 2026 SonicSandbox"), read once; for
    the GPL version 3 text, `GPL_NAME` and the copyright line of `LICENSE-EXCEPTION.md` beside it ("GNU General Public
    License, version 3 or later (GPL-3.0-or-later) · Copyright (C) 2026 SonicSandbox"; the name alone without that
    file); "" when no `LICENSE` can be read (the caller shows the line only when there is one)."""
    if not _LICENCE:
        line = ""
        for folder in filter(None, _licence_folders()):
            lines = _text_lines(os.path.join(folder, LICENCE_FILE))
            if lines:
                gpl = lines[0] == GPL_TITLE and len(lines) > 1 and lines[1].startswith(GPL_VERSION)
                notice = (_text_lines(os.path.join(folder, EXCEPTION_FILE)) or []) if gpl else lines[1:]
                copyright_line = next((text for text in notice if text.lower().startswith("copyright")), "")
                line = " · ".join(text for text in (GPL_NAME if gpl else lines[0], copyright_line) if text)
                break
        _LICENCE.append(line)
    return _LICENCE[0]


def __getattr__(name):
    """`LICENCE_LINE`: `licence_line()`, read the first time it is asked for (PEP 562)."""
    if name == "LICENCE_LINE":
        return licence_line()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# --- README's Data Credits, checked against DATA_CREDITS (S11) ----------------------------------------------------- #
# README's own names for a source DATA_CREDITS names in other words.
README_ALIASES = {"Japanese Wikipedia": "Wikipedia", "Chinese Wikipedia": "Wikipedia", "Anki Miner": "anki_miner"}
_LINK = re.compile(r"\[([^\]]+)\]\(")


def readme_sources(readme_text):
    """The sources a credits text links to (each link's words), in its order: README's *Data Credits* section, or the
    whole credits page (`docs/CREDITS.md`, titled `# Credits`), where README's credits moved on 2026-11-09."""
    match = re.search(r"^##[^\n]*Data Credits[^\n]*\n(.*?)(?=^## |\Z)", readme_text or "", re.M | re.S)
    if match:
        body = match.group(1)
    elif re.match(r"\s*# Credits\b", readme_text or ""):
        body = readme_text
    else:
        return []
    seen = []
    for name in _LINK.findall(body):
        if name not in seen:
            seen.append(name)
    return seen


def missing_from_credits(readme_text):
    """The credits text's sources the in-app credits (data, covers, logos) don't name: [] when the app covers them."""
    named = DATA_CREDITS + "\n" + COVER_CREDITS + "\n" + LOGO_CREDITS + "\n" + AI_VOICE_CREDITS
    return [name for name in readme_sources(readme_text) if README_ALIASES.get(name, name) not in named]

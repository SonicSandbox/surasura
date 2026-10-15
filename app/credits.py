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


# --- Surasura's own licence (the `LICENSE` file: its first line and its copyright line) --------------------------- #
LICENCE_FILE = "LICENSE"
_LICENCE = []               # read once, the first time it is asked for


def _licence_folders():
    """Where `LICENSE` is looked for: the project root from source; beside the program (README's folder) and in its
    bundle when frozen."""
    if path_utils.is_frozen():
        return [os.path.dirname(sys.executable), getattr(sys, "_MEIPASS", "")]
    return [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]


def licence_line():
    """`LICENSE`'s first line and its copyright line ("MIT License · Copyright (c) 2026 SonicSandbox"), read once; ""
    when no `LICENSE` can be read (the caller shows the line only when there is one)."""
    if not _LICENCE:
        line = ""
        for folder in filter(None, _licence_folders()):
            try:
                with open(os.path.join(folder, LICENCE_FILE), "r", encoding="utf-8-sig") as f:
                    lines = [text.strip() for text in f.read().splitlines() if text.strip()]
            except (OSError, UnicodeDecodeError):
                continue
            if lines:
                copyright_line = next((text for text in lines[1:] if text.lower().startswith("copyright")), "")
                line = " · ".join(text for text in (lines[0], copyright_line) if text)
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
README_ALIASES = {"Japanese Wikipedia": "Wikipedia", "Chinese Wikipedia": "Wikipedia"}
_LINK = re.compile(r"\[([^\]]+)\]\(")


def readme_sources(readme_text):
    """The sources README's *Data Credits* section links to (each link's words), in its order."""
    match = re.search(r"^##[^\n]*Data Credits[^\n]*\n(.*?)(?=^## |\Z)", readme_text or "", re.M | re.S)
    if not match:
        return []
    seen = []
    for name in _LINK.findall(match.group(1)):
        if name not in seen:
            seen.append(name)
    return seen


def missing_from_credits(readme_text):
    """README's Data Credits sources DATA_CREDITS doesn't name: [] when the in-app credits cover README's."""
    return [name for name in readme_sources(readme_text) if README_ALIASES.get(name, name) not in DATA_CREDITS]

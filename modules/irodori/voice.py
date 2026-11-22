# SPDX-License-Identifier: GPL-3.0-or-later
"""Voice packs and the K2 caption — who says the line, and how (README § The engine, § Voice packs).

A **voice pack** is one JSON file: `voices/<id>.json` beside this file (shipped) or `<runtime>/voices/<id>.json`
(added later: a fine-tuned voice is a pack, no code change). It holds `id`, `version`, `name`, `speed`, `steps`
(null: the model's own), an optional `lora` (a LoRA adapter file under the runtime) and `voice` (a reference voice the
server knows, "none" for words only), and `captions`: the caption's parts by who speaks. A pack whose `captions` is
null sends no caption (a fine-tuned voice that needs none). A pack may instead hold one `caption` and one `seed` for
every line (`"for": "listening"`: a listening round's voice, the same person on all its lines).

The **caption** (K2, the engine as tested): who would say the line out loud, to whom, with a modest emotion, asking for
natural everyday speech at a normal pace. On the learner's PC there is no AI to ask, so the line's own words decide
(`speaker`, PROVISIONAL): a man's words → a man, a woman's → a woman, else a woman (the tested captions chose one
for 6 lines of 8). A caption never says K2's banned words (narration, calm, slow …): they pull the model toward a read-aloud voice.
"""
import hashlib
import html
import json
import os
import re

DEFAULT = "k2-natural"
MAX_CAPTION = 50
BANNED = ("落ち着いた", "ナレーター", "ナレーション", "語り口", "語る", "朗読", "読んでいる", "読み上げ", "ゆっくり",
          "ゆったり", "静か", "穏やか", "かすれ", "ハスキー", "息まじり", "ささやき", "囁")
# a man's / a woman's own words: a pronoun anywhere, a sentence-final particle at a clause's end only
_END = r"(?=[。！？!?…、」』）)\s]|$)"
MALE = re.compile(r"俺|僕|おれ|ぼく|オレ|ボク|わし|(?:ぜ|だぞ|ぞ|だな|だろ|かよ|じゃねえ|ねえよ)" + _END)
FEMALE = re.compile(r"あたし|アタシ|(?:わよ|かしら|のよ|だわ|ですわ|わね|のね)" + _END)     # never てよ: 待てよ is a man's
QUESTION = re.compile(r"[？?]\s*[」』]?\s*$|(?:ですか|ますか|でしょうか|かな)[。]?\s*$")
EXCLAIM = re.compile(r"[！!]")
REQUEST = re.compile(r"ください|下さい|てくれ|お願い|ませんか")
KANA = re.compile(r"[ぁ-ゖァ-ヺ]")          # a Japanese line has kana: Chinese never reaches the voice
MAX_CHARS = 200


def _folders(runtime_home=None):
    out = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")]
    if runtime_home:
        out.append(os.path.join(runtime_home, "voices"))
    return out


def packs(runtime_home=None):
    """Every voice pack found -> {id: pack}; a pack added under the runtime replaces a shipped one of the same id only
    when its `version` is higher. An unreadable file is skipped."""
    found = {}
    for folder in _folders(runtime_home):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
                    pack = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(pack, dict) or not isinstance(pack.get("id"), str):
                continue
            had = found.get(pack["id"])
            if had is None or int(pack.get("version") or 0) > int(had.get("version") or 0):
                found[pack["id"]] = pack
    return found


def pack(pack_id=None, runtime_home=None):
    """The pack named (else the default); the default when the one named is gone."""
    found = packs(runtime_home)
    return found.get(pack_id or DEFAULT) or found.get(DEFAULT)


def speaker(text):
    """Who says the line: "male" / "female" by its own words, else "female" (PROVISIONAL)."""
    male, female = bool(MALE.search(text)), bool(FEMALE.search(text))
    return "male" if male and not female else "female"


def delivery(text):
    """How: "ask" (a question), "request", "exclaim", else "tell"."""
    line = text.strip()
    if QUESTION.search(line):
        return "ask"
    if REQUEST.search(line):
        return "request"
    if EXCLAIM.search(line):
        return "exclaim"
    return "tell"


def caption(text, voice_pack):
    """The K2 caption for `text` from the pack's parts -> a string ≤ MAX_CAPTION, or None (the pack sends none). A
    pack's one `caption` is every line's."""
    fixed = (voice_pack or {}).get("caption")
    if isinstance(fixed, str) and fixed:
        return fixed[:MAX_CAPTION]
    parts = (voice_pack or {}).get("captions")
    if not parts:
        return None
    who = parts["who"][speaker(text)]
    how = parts["how"].get(delivery(text)) or parts["how"]["tell"]
    return f"{who}{how}"[:MAX_CAPTION]


def seed(text, voice_pack=None):
    """The same sentence always gets the same take (its text's hash): made again, it sounds the same. A pack's one
    `seed` is every line's (with its one caption: the same person on every line)."""
    fixed = (voice_pack or {}).get("seed")
    if isinstance(fixed, int) and not isinstance(fixed, bool):
        return fixed
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16) % 100000


_RUBY = re.compile(r"<rt>.*?</rt>|<rp>.*?</rp>", re.S)
_TAGS = re.compile(r"<[^<>]*>")
_BRACKET_FURIGANA = re.compile(r" ?([^\s\[\]]+)\[[^\[\]]*\]")       # Anki's 漢字[かんじ]
_SOUND = re.compile(r"\[sound:[^\]]*\]")
_CLOZE = re.compile(r"\{\{c\d+::(.*?)(?:::[^}]*)?\}\}", re.S)


def sentence_text(value):
    """A card's Sentence field as the voice should read it: [sound:], cloze marks, ruby, HTML and Anki's 漢字[かんじ]
    taken off, entities read, spaces closed up."""
    text = _SOUND.sub("", value or "")
    text = _CLOZE.sub(r"\1", text)
    text = _RUBY.sub("", text)
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = _TAGS.sub("", text)
    text = html.unescape(text)
    text = _BRACKET_FURIGANA.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def usable(text):
    """Why the voice can't read `text` -> None (it can), "no Japanese", "too long" (never cut: PROVISIONAL)."""
    if not text or not KANA.search(text):
        return "no Japanese"
    if len(text) > MAX_CHARS:
        return "too long"
    return None

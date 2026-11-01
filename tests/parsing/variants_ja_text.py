"""The options of a text-reading setting (cases_ja_text.py) — what a Japanese book's text holds that isn't text.

TXT-PAREN-READINGS is a setting since 2026-09-27 (settings.json logic.paren_readings, the user's answer): kana alone
in parentheses right after kanji — 玖渚友(くなぎさ・とも), 窮鼠（きゅうそ） — is that kanji's reading, the typographic
stand-in for ruby, and goes as F3's Aozora 《ruby》 does. A plain run measures its default, "hiragana" (a hiragana
group, with ・ ー, goes; a katakana group after kanji is as often an aside naming who is meant, 自分（モロナイ）, or a
loanword gloss, 複製（コピー）, as a reading, 凸（デコ）). The other two options:

    paren-readings-any   "any": a katakana or mixed group goes too
    paren-readings-off   "off": every group is text (as before the setting)

Measured read-only on the user's library the same day (data/ja HighPriority, LowPriority, GoalContent: 1,620 .txt,
no .md): 40 such groups in 28 files — 19 readings (15 names in hiragana, 凸（デコ） / 凹（ボコ） ×4), 6 glosses
(複製（コピー） ×2, 傾向（ホメオスタシス）, 章（チャプター）, 月光会（ルーナー・ソサエティー）, 心（りっしんべん）) and 15
asides (GS「堕落（アダムとエバの）」 ×9, ぶどう園（イスラエル）, 株（キリスト）, 預言者（アビナダイ）, 自分（アマリキヤ）,
自分（モロナイ）, 批評家（ウィリアム・エンプソン）). The hiragana ones: 16 — 15 readings and the radical's name
りっしんべん, no aside.

A variant here sets the option as settings.json would: the frozen settings the pins re-apply to every case
(harness.frozen_logic) gain the key, and analyzer.strip_text_conventions reads it off LOGIC as a run does.
"""
from tests.parsing import harness
from tests.parsing.harness import patched
from tests.parsing.variants import variant


def _paren_readings(option):
    """The frozen settings with logic.paren_readings set to `option`, for every case the run pins."""
    real = harness.frozen_logic

    def logic():
        return dict(real(), paren_readings=option)
    return patched(harness, "frozen_logic", logic)


@variant("paren-readings-any",
         "TXT-PAREN-READINGS set to 'Any kana' (logic.paren_readings = \"any\"): a katakana group after kanji goes "
         "too (凸（デコ）, but also the asides 自分（アマリキヤ）, 複製（コピー）) — 15 of the library's 40 groups are asides.")
def _paren_readings_any():
    with _paren_readings("any"):
        yield


@variant("paren-readings-off",
         "TXT-PAREN-READINGS set to 'Keep as text' (logic.paren_readings = \"off\"): every group in parentheses is "
         "text, as before the setting — 玖渚友(くなぎさ・とも) counts ナギサ + 共 again.")
def _paren_readings_off():
    with _paren_readings("off"):
        yield

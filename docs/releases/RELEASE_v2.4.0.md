# Surasura v2.4.0 - Release Notes

## Summary
- **Parsing rebuilt** - every word counted as the word it is
- **Idioms on your list** - new
- **One-kanji words on your list** - new
- **Names stay whole** - plus a new Ignore names option
- **Chinese parsing rebuilt** - real words, not guesses
- **Automatic rarity** - new: the Rarity slider moves on as you learn
- **Generate keeps up with Anki** - runs after every sync that adds known words
- **Everyday Generate faster** - 17 s → 12.5 s, on less memory
- **Anki, Junban and Backfill** - agree on more cards
- **Backfill パターン rebuild themselves** - new
- **How Parsing Works guide** - new, opened from Settings ([read it](https://github.com/SonicSandbox/surasura/blob/main/docs/How%20Parsing%20Works.md))

> After updating, your first Generate re-reads your whole library once. Anki Backfill downloads its new パターン data
> once (32 MB Japanese, 10 MB Chinese).

## Parsing
What counts as one word, with examples: [How Parsing Works](https://github.com/SonicSandbox/surasura/blob/main/docs/How%20Parsing%20Works.md)

- **Compounds**: 上層 + 部 → 上層部
- **Compound verbs**: 走る + 出す → 走り出す
- **Compound + suffix**: 同性愛 + 者 → 同性愛者
- **Split words**: 出来 + 損ない → 出来損ない
- **Chance pairs**: 間 + 話 in 長い間話した → stay two words
- **Cut endings**: 下る + ない → くだらない
- **Adverbs**: いつ + も → いつも
- **Pronoun suffixes**: 何 + 様 → 何様
- **Phrases and titles**: 予想 + 通り → 予想通り
- **お / ご words**: お + 守り → お守り
- **Katakana names**: グリム + ジョー → グリムジョー
- **Katakana words**: 無 + しん → ブシン
- **Repeated names**: シャドウ + ガーデン → シャドウガーデン
- **Kanji names**: 一 + 護 → 一護
- **Story terms**: 斬 + 魄 + 刀 → 斬魄刀
- **Idiom rows**: 気 + が + する → 気がする
- **Idioms wait**: 本題に入る waits until you know 本題
- **Idiom-only words**: 眉根 → learned with 眉根を寄せる
- **Idioms read right**: 彼のほう 'his side' → not 彼の方 'that person'
- **そういった**: 'such' only before a noun, never そう言った 'said so'
- **One-kanji words**: 手, 顔, 声 → on your list
- **Counts**: 年 in 三年, 目 in ２時間目 → part of the count
- **One-character words**: は, a rare kanji → no longer an unknown in a sentence
- **Readable compounds**: 上層部, with 上層 and 部 known → half score
- **Rare compounds**: 前言撤回 → counts toward 撤回
- **Example sentences**: 撤回's → its own, not 前言撤回's
- **Numbers**: 二十, 百 → not words
- **Greek letters**: デルタ, アルファ → words
- **Dashes**: 祈り－心 → a dash, not から
- **Fillers**: ま + あ → まあ
- **Panting**: ハァハァハァ → はあはあ
- **Sound + と**: ドキッ + と → ドキッと
- **Shouts**: ザ + ック → ザ─────ック
- **Half-width**: ﾅｲﾌ → ナイフ
- **Wide digits**: ５０ → 50
- **Stretched words**: すご～い → すごい
- **Stretched katakana**: ジャ～ック → ジャック
- **Rare kanji**: 𩸽, 𠮷 → counted · 𠮟られた → 叱る
- **Old encodings**: Shift_JIS, GBK, Big5 files → read
- **Damaged files**: one bad byte → the rest still counts
- **.ssa subtitles**: → read
- **Subtitle markup**: 「階で待つ」 → 「30階で待つ」
- **Caption labels**: [音楽], アサ： → dropped
- **Karaoke lines**: → skipped
- **Aozora ruby**: 漢字《かんじ》 → 漢字
- **Book readings**: 山田太郎(やまだ・たろう) → 山田太郎
- **Scripture marks**: verse references, ①② → dropped
- **Trailing dots**: くっ… → no 。 added
- **Quotes**: 「晴れ。雨」と言った → one sentence
- **Quotes in a row**: 「はい。」「いいえ。」と答えた → one sentence
- **Two-line captions**: 《昨日は雨で / 家にいた》 → one sentence
- **Next-line brackets**: ｡ then ｢ → ｢ starts the next sentence
- **Two speakers**: one caption → two sentences
- **Chinese guesses**: 他来 → 他 + 来
- **Chinese phrases**: 吃了饭 → 吃 + 了 + 饭
- **Chinese numbers**: 三千五百 → not a word
- **Chinese doubles**: 开开心心 → 开心
- **Traditional as written**: 為什麼 → one word
- **Taiwan characters**: 喫飯 → 吃飯
- **Chinese 著**: 著急 → 着急
- **Chinese sentences**: …… and ； → no longer cut a sentence
- **Chinese two-line captions**: 我觉得 / 他不会来 → one sentence

## New Settings
Settings → Language & Parsing, unless noted.

| Setting | Default |
| :-- | :-- |
| Idioms and set phrases on your list | On |
| List one-kanji words only when they're dictionary words | On |
| Phrases and titles as one word | On |
| Pronouns with a suffix as one word | On |
| Katakana names as one word | On |
| Names your library repeats as one word | On |
| Kanji names as one word | On |
| Kanji terms your library repeats as one word | On |
| Ignore names | Off |
| Readings in ( ) in books | Hiragana only |
| How parsing works (opens the guide) | — |
| Sentences & Logic → Automatic rarity | Off |
| Data & System → Data credits | — |
| Reinforce Chinese segmentation | Removed |

## Speed
A 2,000-file library (4.3 million words), same machine and session.

| | 2.3.1 | 2.4 |
| :-- | --: | --: |
| Everyday Generate, after an Anki sync | 17.1 s | 12.5 s |
| Everyday Generate, after a new episode or book | 17.2 s | 13.1 s |
| Peak memory, everyday Generate | 890 MB | 700 MB |
| First Generate after updating (once) | 71 s | 72 s |
| Re-reading the whole library | 51 s | 58 s |
| Sentence dictionary export | 12.3 s | 16.5 s |
| Rarity slider, each move | 0.10 s | 0.17 s |
| Words on your list | 2,467 | 3,586 |

## Anki, Junban and Backfill
- **Card read as its word**: 撒く / まく → 撒く · 勉強した → 勉強 · ﾊﾞｼｯと → バシッと
- **Polite and plural cards**: お部屋 → 部屋 · 俺たち → 俺
- **Another spelling**: 逃げだす → 逃げ出す, without asking
- **Dictionary decides the word**: 心する is not 心 · 揚げる is not 上げる
- **Number words**: a 何人 card isn't known through 人
- **One-character cards**: a 見 card isn't 見る
- **Kana card of a common word**: ひかり → 光, not the name ヒカリ
- **Known cards go last** in Junban
- **Phrase cards** land on their idiom row
- **例文** finds your card's own word
- **例文, sentence dictionary and 順** read sentences as your list does
- **Edited cards** read again on the next sync
- **Sentences with spaces** count every word as known
- **Migaku "Ignored" words** stay ignored
- **"In Anki" mark**: one row per card
- **Chinese cards**: 认真地 → 认真 · 吃了 → 吃
- **Chinese decks** never taken for Japanese
- **パターン**: compounds get lines (株式会社) · 揚げる, 撮る get their own · one-kanji lines from the word's own uses · numbers and symbols get none · Chinese lines from the new Chinese parsing
- **Backfill パターン rebuild themselves** when your library grows by a quarter, in the background; **Rebuild from my library** does it now

## Generate and the Report
- **Automatic Generate** after an Anki sync always runs, with a spinner on the button
- **One Generate at a time**: pressing Generate during one waits for it
- **Report opens at once** after an automatic Generate
- **Automatic rarity** (new, off): picks the rarest band with 850 words or fewer; the slider shows Rarity (auto)
- **Not on your list**: under each file, the one-kanji words your list can't offer, with counts
- **Cleaner examples first**: a sentence with a new idiom goes after cleaner ones
- **Rarity slider** counts names, compounds, idioms and one-kanji words as your list does
- **Settings changes** in 順, Backfill, Speech and other windows no longer force a full Generate

## Fixes
- KnownWord.json, Ignore list or settings.json saved with a BOM no longer stops Generate
- Excel "CSV UTF-8" frequency lists load
- GraduatedList.txt keeps its encoding
- The Ignore list understands する (する, それ)
- The Rarity slider notices a list you just saved
- さっ, ふっ and いら removed from the default Ignore list
- The Chinese "Script" tooltip is right (Taiwan's characters)
- Speech (声) appears with a settings.json saved with a BOM

## Dictionary Data
| Source | Used for |
| :-- | :-- |
| JMdict (2026-09-28), JMnedict — EDRDG, CC BY-SA 4.0 | Compounds, names, idioms, one-kanji words, card meanings |
| JPDB 2024, Jiten | How common a word is |
| CC-CEDICT, Universal Dependencies Chinese treebanks — CC BY-SA 4.0 | Chinese words |
| OpenCC TWVariants — Apache-2.0 | Taiwan's characters |

Every source: **Settings → Data & System → Data credits**.

## Setup Instructions
1. Extract the zip file.
2. Run `Surasura.exe`.

## Usage Tutorial
[Tutorial](https://github.com/SonicSandbox/surasura/blob/main/docs/Tutorial.md) · [How Parsing Works](https://github.com/SonicSandbox/surasura/blob/main/docs/How%20Parsing%20Works.md)

---

## UPDATE INSTRUCTIONS
> **On v2.0 or later?** One-click in-app update: **⬆ Update available** at the bottom-left of the dashboard →
> **Update now**. Your known words, lists, content, results, settings and library order are never touched.

On **v1.9 or earlier**, or updating by hand:
- Download and unzip the new release.
- Move your **User Files** (Ignore list, freq lists, blacklist, GraduatedList) into `User Files/<language>/`.
- Move your **content** into `data/<language>/`.

**Note:** Back up your User Files and data before updating manually.

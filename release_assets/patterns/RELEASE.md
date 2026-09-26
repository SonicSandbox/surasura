# Surasura's shared パターン data (Japanese)

`patterns_ja_shared.zip` is what the app downloads when a user presses **Get data… → Download** in the
Anki Backfill window. It is **published by being committed here**. The app fetches it from this
repository at the commit that added it, and accepts **only that exact file**. Both the URL and the
sha256 live in `modules/junban/patterns_package.py` (`SHARED_URL`, `SHARED_SHA256`). A commit never
changes, so every app version keeps getting the file it was built for. No GitHub release is needed.

**Pinned now: version 4** (builder 7, 2026-09-25). Checked on 2026-09-25 by downloading the URL: the sha256
matched, and the app's own download installed it. The same sources and rules as version 3, rebuilt on Surasura's
corrected join table (Patterns_Quality_Spec.md §15.9): the spellings of one お / ご word are one word (おやすみ
and お休み, ご存じ and ご存知), お話し and お帰り are お + a word, 複雑さ is 複雑 + さ. 2.3 counts version 3
(builder 6) as not ready, so 2.3 must ship with this pin.
- **Size:** 67,491 words, and a 32.2 MB zip. sha256
  `ea3bdd8e415b8d2194f953179150d0e6b64526bc461d1f080ce68f565419b416`.
- **The gate:** every yardstick equal to version 3's — the NLT gold 13/18 top particles and 29/90 top-5
  pairings, cards filled from it 88.3% of the known words tested. Patterns_Quality_Spec.md §15.9 has the
  numbers.

      https://raw.githubusercontent.com/SonicSandbox/surasura/8f126cfb8523c661d09c2dab2870c98f2189646f/release_assets/patterns/patterns_ja_shared.zip
      sha256 ea3bdd8e415b8d2194f953179150d0e6b64526bc461d1f080ce68f565419b416

**Version 3** (builder 6, 2026-09-25) stays reachable for the app versions pinned to it. Checked on
2026-09-25 by downloading the URL: the sha256 matched, and the app's own download installed it. The same
sources as version 2, rebuilt for Surasura 2.3's パターン (Patterns_Quality_Spec.md): words keep their prefixes
and suffixes (新幹線, 可能性), each pattern carries the number of documents it is in, and the pairings and
frames under the lookup's fixed limits (fewer than 3 documents, strength under 2, fewer than 3 uses) are left
out.
- **Size:** 67,509 words, and a 32.2 MB zip. sha256
  `7882e6ab80e8d712a878cbf942ebc5edeec9a8ea8ea5f81ef833c243bfd38527`.
- **The gate:** this file's yardsticks held against version 2 — the NLT gold, 13/18 top particles and 29/90
  top-5 pairings on both — and cards filled from it went from 84.9% to 88.3% of the known words tested.
  Patterns_Quality_Spec.md §15.7 has the numbers.

      https://raw.githubusercontent.com/SonicSandbox/surasura/f996b2c19d9866a2748cbf2b9130471e75ea9d0a/release_assets/patterns/patterns_ja_shared.zip
      sha256 7882e6ab80e8d712a878cbf942ebc5edeec9a8ea8ea5f81ef833c243bfd38527

**Version 2** (builder 5, 2026-09-25) stays reachable for the app versions pinned to it. It adds modern news from the Leipzig Corpora
Collection, and its zip is 29.2 MB. Checked on 2026-09-25 by downloading the URL: the sha256 matched,
and the app's own download installed it.
- **What goes in:** Japanese newscrawl 2015–2019. Translations are dropped (foreign outlets' Japanese
  editions), and so are shop pages. News is counted only: no sentence of it is in the file.
- **Aozora and Wikipedia:** each is cut to about 13M words, so the news gets an equal share.
- **The gate:** it passed every yardstick against version 1. Patterns_Spec.md §19.1 has the numbers.

      https://raw.githubusercontent.com/SonicSandbox/surasura/5bbd22621f8bec3f305e122f6b52638ae172cd0e/release_assets/patterns/patterns_ja_shared.zip
      sha256 e35d2e45899e6c6528692f182bad5fc7509e4bcfbd012434754b0604cfa4d9a3

**Version 1** (builder 4) stays reachable for the app versions pinned to it. It was made from
RealPersonaChat, Aozora Bunko and Japanese Wikipedia, and its zip is 26.8 MB.

      https://raw.githubusercontent.com/SonicSandbox/surasura/539f6c2003325b5a875867eab977c505be7b00ba/release_assets/patterns/patterns_ja_shared.zip
      sha256 0d7146aa97d02409c552c3e44f7d97d221d0680713f057095c7276274102c985

Credits are in `CREDITS.txt`, which is also inside the zip. The file is CC BY-SA 4.0. This folder is
not part of the app build.

# Surasura's shared パターン data (Chinese)

`patterns_zh_shared.zip` is the same thing for Chinese cards. It works the same way: published by being
committed here, then pinned. The pin is `SHARED["zh"]` in `modules/junban/patterns_package.py`: the
commit's raw URL, the zip's sha256, its size in MB and its credit line.

**Pinned now: version 2** (Chinese builder 2, 2026-09-25). Checked on 2026-09-25 by downloading the URL: the
sha256 matched, and the app's own download installed it. The same sources as
version 1, rebuilt for Surasura 2.3 (Patterns_Quality_Spec.md §10): the same pairing filters as Japanese,
coverb rows only where they cover enough of a word's uses, no 演唱会-type forms, adverbs' pairings, and
Tatoeba's sentences counted as documents of their own. 2.3 counts version 1 (builder 1) as not ready, so
2.3 must ship with this pin.
- **Size:** 53,608 words, and a 9.4 MB zip. sha256
  `5afa2d4c0667788946acc17c3e466454bb15cf3d1551241ff8d9e12811d95d58`.
- **The check:** against version 1, each read by its own code (Patterns_Quality_Spec.md §15.7).

      https://raw.githubusercontent.com/SonicSandbox/surasura/f996b2c19d9866a2748cbf2b9130471e75ea9d0a/release_assets/patterns/patterns_zh_shared.zip
      sha256 5afa2d4c0667788946acc17c3e466454bb15cf3d1551241ff8d9e12811d95d58

**Version 1** (Chinese builder 1, 2026-09-25) stays reachable for the app versions pinned to it. Checked on 2026-09-25 by downloading the URL:
the sha256 matched, and the app's own download installed it.

      https://raw.githubusercontent.com/SonicSandbox/surasura/d62e6464c494f2e2494e797a3326a999f733b25b/release_assets/patterns/patterns_zh_shared.zip
      sha256 ac9e50f83ef82b21bec96ab8e44fb2be240367a235daa534f52575c8d84e8907

- **What goes in:** 17.8M words from Tatoeba, KdConv's film and music talk, Chinese Wikipedia (16M
  characters), Chinese Wikinews, and Leipzig's Chinese news (16M characters: 2007–09, 2020, and the
  Traditional newscrawl of 2011). News is counted only: no sentence of it is in the file.
- **What stays out:** CrossWOZ and KdConv's travel talk, which are booking templates.
- **Size:** 53,615 words, and a 9.5 MB zip. sha256
  `ac9e50f83ef82b21bec96ab8e44fb2be240367a235daa534f52575c8d84e8907`.
- **The gate:** the agent judged it (Patterns_Chinese_Spec.md §16.1, WP-Z6). There is no written-style
  tag for Chinese.

Credits are in `CREDITS_zh.txt`, which is also inside the zip as `CREDITS.txt`, next to KdConv's
Apache licence. The file is CC BY-SA 4.0.

To make a new version of the Chinese data:

1. Run `python docs/assets/corpora/prepare_zh.py` in the background (about 9 minutes). Then run
   `python docs/assets/corpora/build_shared_zh.py`, which builds a candidate in
   `docs/assets/corpora/out/shared_zh/`.
2. Compare it with the pinned file. `gate.py` is for Japanese only, so do it by hand:
   - unzip the pinned zip to a temp folder;
   - run `python docs/assets/zh_gold/compare_zh.py pinned=<temp>\patterns_zh_shared.db
     candidate=docs\assets\corpora\out\shared_zh\patterns_zh_shared.db`;
   - read the same pair on the review page (`review_patterns_zh.py`, same arguments).

   Adopt it only if no measure-word, coverb or filled number is lower, and no new word reads wrong.
   When the builder or the lookup changed as well, the numbers move by design: compare each side by its
   own code instead (`docs/assets/corpora/tools/zh/zh_check.py both --code <a copy of modules/junban from
   before the change>`) and read what moved.
3. Run `build_shared_zh.py --publish`. It copies the zip and `CREDITS_zh.txt` here.
4. Commit and push them. Update the README credits if the sources changed.
5. Pin `SHARED["zh"]` in `modules/junban/patterns_package.py` to the commit that added the zip
   (`git log -1 --format=%H -- release_assets/patterns/patterns_zh_shared.zip`). Set the zip's sha256,
   its size in MB and the credit line. Update the Chinese pin test in
   `modules/junban/tests/test_side_by_side.py` (it checks the size), and this file.
6. Check before shipping: download the URL and compare its sha256. Also install it with the app's own
   `get_shared(language="zh")` into a scratch data folder. Then ship the app release that carries the new
   pin.

## A new version of the data

1. Run `python docs/assets/corpora/build_shared.py`. It builds a candidate in
   `docs/assets/corpora/out/shared/`.
2. Run `python docs/assets/corpora/gate.py`. It compares the candidate against the pinned file and
   writes `GATE.md`. Adopt only if no yardstick is lower. When the code changed with the data, run
   `gate.py --today-code <a copy of modules/junban from before the change> --today-library <the library
   database from before>`, so "today" is what users have today, and explain every yardstick that moved.
3. Run `python docs/assets/corpora/build_shared.py --publish`. It copies the zip and `CREDITS.txt` here.
4. Commit and push them. Update the README credits if the sources changed.
5. Put that commit's full hash into `SHARED_URL` and the zip's sha256 into `SHARED_SHA256`. Update
   `SHARED_MB` and `SHARED_CREDIT` to match, and update this file.
6. Check before shipping: download the URL and compare its sha256
   (`certutil -hashfile <zip> SHA256`). Then ship the app release that carries the new pin.

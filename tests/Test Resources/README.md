# Test Resources — where each file comes from

Every text here is public domain, written for Surasura's tests (CC0), or made by the app from those. Nothing is taken
from a learner's own library, cards or word lists. Audited 2026-11-11 (the 3.0 test-data audit); files replaced then
stay in git history.

| File | What it is | Source |
| --- | --- | --- |
| `ja/MigakuDb.db` | a Migaku-shaped database (its `WordList` table): 2,948 Japanese words, 30 German | built for the tests: the commonest dictionary forms of the app's own `frequency_list_ja_global50k.csv`; statuses and times made up |
| `ja/KnownWord.json` | that database as the app's Migaku import writes it | made by `app/migaku_converter.py` from `ja/MigakuDb.db` (its `exportDate` and `databaseFile` set by hand) |
| `ja/testAnki.apkg` | a legacy Anki package: 200 basic words, a vocabulary note and a marked sentence note each | written for the tests (words, sentences, English); a few stand-in media files |
| `ja/testAnki2.apkg`, `ja/ankiTest3.apkg` | modern Anki packages (zstd): four mined cards | the sentences are from the public-domain samples (蜘蛛の糸, ごん狐); glossaries and pitch graphs written for the tests |
| `ja/audiobook_sync/toshisyun_*.srt` | 杜子春 (芥川龍之介, 1920) as timed lines | public domain (青空文庫) |
| `ja/runaway_transcript.txt` | one run-on spoken sentence, as speech recognition writes it | written for the tests |
| `zh/chinese_text_1.txt` | a news-style page about an exhibition (Simplified, one Traditional 臺) | written for the tests |
| `ja/expected_output.csv`, `zh/asis_tokens_golden.json`, `plan_file_base_hashes.json` | recorded outputs | made by the app from the samples and the files here |
| everything else (`ja/*.srt`, `ja/*.ass`, `ja/context_test.txt`, `ja/airing/`, `ja/phrase_reading/`, `zh/*.txt`, `zh/*.srt`, `zh/KnownWords.json`, the frequency lists, `settings/`, `connect/`, `anilist/`) | lines, settings and records shaped like the real thing | written for the tests; `anilist/search_answers.json` is AniList's answers for public catalogue entries (titles, ids, years, cover links) |

# SPDX-License-Identifier: GPL-3.0-or-later
"""The match index — how a word on an Anki card is recognised as a word on Surasura's list.

The code lives in core now, in `app/anki_match.py` (Junban_Backlog_Spec §5.1): the report's Anki
backlog badge needs the same answer Junban's reorder does, and core never imports `modules/`. Every
name is re-exported here, so every call site (`match.build_index`, `match.target_word`, ...) and
every test keeps working unchanged — the precedent is `ankiconnect.py`, which re-exports
`app/anki_connect.py` the same way.
"""

from app.anki_match import (AFFIX_SPELLINGS, CONTEXT_COLUMNS, MARKER_DEFAULTS, MARKERS,  # noqa: F401
                            NOMINALIZERS, PLURALS, POLITE_PREFIXES, TOTAL_COLUMNS, ZH_ASPECTS, ZH_CARD_ENDINGS,
                            Index, affixes_off, another_word, build_index, card_key, connect_row, find_phrases,
                            fold_kana,
                            one_word, two_words, word_of_its_own,
                            library_floor, load_index,
                            load_library, load_rank_index, lookup, marker_thresholds,
                            normalize_markers,
                            normalize_word, phrase_lemmas, phrase_places, sentence_span,
                            sentence_excerpt, suggest, Suggestion, unknowns_beside,
                            resolve_word_field, row_markers, row_total, target_word, unknown_markers)

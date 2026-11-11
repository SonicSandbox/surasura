# SPDX-License-Identifier: GPL-3.0-or-later
"""The match index (WP-D) — the half of the feature that decides whether a card is recognised at all.

Everything here is pure: no Anki, no network, no tokenizer. The data is real — the divergent
lemma/orth pairs below are the measured ones from spec §4 (`引きずって` -> lemma `引き摺る`, orth
`引きずる`), and one test loads the repo's real 160-row golden list rather than a hand-made one, so
the reader is exercised against a file the analyser actually produced.

Why this matters more than it looks: a word the index misses is not an error anywhere. It is simply
an unmatched card that quietly keeps its old position, and the user sees a reorder that "didn't do
much". 20.6% of their mined words depend on the `Orth` key alone.
"""
import csv
import os

import pytest

from modules.junban.match import (load_rank_index, normalize_word, resolve_word_field, target_word)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# A slice shaped like the live priority list, with the real lemma/orth divergences the feature
# exists for. Ranks 0-4 really are character names on the user's library (spec §13 #9) — no proper
# noun filter, by decision §15 Q2 — so the fixture starts the way the real file does.
_ROWS = [
    # Word,      Orth,       Reading
    ("アルマ",   "アルマ",   "アルマ"),
    ("ルッツ",   "ルッツ",   "ルッツ"),
    ("スドウ",   "須藤",     "スドウ"),      # the show writes 須藤; UniDic's lemma is katakana
    ("御伽話",   "お伽話",   "オトギバナシ"),  # anki_miner writes the orth_base お伽話
    ("引き摺る", "引きずる", "ヒキズル"),     # 引きずって -> lemma 引き摺る, orth 引きずる
    ("寧ろ",     "むしろ",   "ムシロ"),
    ("冒険",     "冒険",     "ボウケン"),
    ("食べる",   "食べる",   "タベル"),
    ("老婆",     "老婆",     "ロウバ"),
]


def _write_list(path, rows, header=("Word", "Orth", "Reading")):
    """Write a priority list the way the analyser does — UTF-8 **with a BOM**, Excel's dialect.

    The BOM is not incidental: `static_html_generator` emits it, and a reader that opens the file as
    plain `utf-8` gets `\\ufeffWord` as its first column name and silently matches nothing.
    """
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return str(path)


@pytest.fixture
def rank_of(tmp_path):
    return load_rank_index(_write_list(tmp_path / "priority_learning_list.csv", _ROWS))


# --- normalisation ------------------------------------------------------------------------------ #
def test_a_plain_word_is_returned_unchanged():
    assert normalize_word("冒険") == "冒険"


def test_anki_furigana_brackets_are_stripped():
    """`食べる[たべる]` is what an Anki field with a reading looks like. Keeping the bracket means the
    word never matches; keeping the reading means it matches the wrong thing."""
    assert normalize_word("食べる[たべる]") == "食べる"
    assert normalize_word(" 老婆[ろうば]") == "老婆"


def test_inline_furigana_keeps_the_okurigana():
    """Migaku-style furigana binds to the kanji only — 食[た]べる must keep べる, not lose it."""
    assert normalize_word("食[た]べる") == "食べる"
    assert normalize_word("引[ひ]き摺[ず]る") == "引き摺る"


def test_multi_segment_furigana_does_not_leave_a_space_behind():
    """Anki separates ruby segments with a space. A mined word never contains one, so the separator
    has to go with the bracket or 冒険 turns into two unmatchable halves."""
    assert normalize_word("冒険[ぼう] 家[か]") == "冒険家"


def test_html_and_sound_tags_are_stripped():
    """Mined cards carry `[sound:…]` and formatting from the source page."""
    assert normalize_word("<b>老婆</b>[sound:rec_1789711432.mp3]") == "老婆"
    assert normalize_word("<div style='font-size:2em'>御伽話</div>") == "御伽話"


def test_ruby_readings_do_not_fuse_onto_the_word():
    """Stripping tags naively turns <ruby>冒険<rt>ぼうけん</rt></ruby> into 冒険ぼうけん, which matches
    nothing on either side — so the ruby reading goes first (same guard as `app/anki_utils`)."""
    assert normalize_word("<ruby>冒険<rt>ぼうけん</rt></ruby>") == "冒険"


def test_an_image_only_field_yields_an_empty_string():
    """A picture-only field is ordinary on a mined card. It must reduce to "" and be skipped, not
    crash the run and not be treated as a word."""
    assert normalize_word('<img src="paste-8f2c.jpg">') == ""
    assert normalize_word('<img src="paste-8f2c.jpg"') == ""      # truncated tag, no closing angle
    assert normalize_word("<br>") == ""


def test_entities_are_unescaped_after_the_tags_not_before():
    """Unescaping first would turn `&lt;b&gt;` into markup and then strip it, deleting real text."""
    assert normalize_word("&lt;冒険&gt;") == "<冒険>"
    assert normalize_word("老婆&nbsp;") == "老婆"


def test_zero_width_characters_are_dropped():
    """Invisible in the Anki editor, fatal to a string comparison, and impossible to fix by hand.
    Written as escapes on purpose: a literal ZWSP here would be unreviewable."""
    padded = "\u200b\u5fa1\u200d\u4f3d\ufeff\u8a71\u00ad"
    assert padded != "\u5fa1\u4f3d\u8a71"
    assert normalize_word(padded) == "\u5fa1\u4f3d\u8a71"        # 御伽話


def test_decomposed_kana_is_normalised_to_nfc():
    """Mac clipboards hand over decomposed kana: が as か + U+3099 is a different string from the
    CSV's precomposed が, and nothing in a plain comparison would ever say so."""
    decomposed = "\u304b\u3099\u307e\u3093"
    assert decomposed != "\u304c\u307e\u3093"
    assert normalize_word(decomposed) == "\u304c\u307e\u3093"    # がまん


def test_crlf_and_padding_collapse():
    """Fields pasted from Windows subtitles arrive with CRLF and stray spacing."""
    assert normalize_word("  冒険\r\n") == "冒険"


def test_case_is_never_folded():
    """Lowercasing is meaningless for JA/ZH and destructive for the romaji and Latin entries that do
    turn up in real decks."""
    assert normalize_word("Ａｎｋｉ") == "Ａｎｋｉ"
    assert normalize_word("NHK") == "NHK"


def test_non_strings_and_blanks_are_empty():
    """`notesInfo` payloads are version-dependent; a missing value must not become a traceback."""
    assert normalize_word(None) == ""
    assert normalize_word("") == ""
    assert normalize_word(12) == ""
    assert normalize_word("   ") == ""


# --- the rank index ------------------------------------------------------------------------------ #
def test_the_row_index_is_the_rank(rank_of):
    """The file is already in learn order — no column is consulted for the rank."""
    assert rank_of["アルマ"] == 0
    assert rank_of["冒険"] == 6


def test_a_word_only_reachable_by_its_orth_matches(rank_of):
    """THE case the `Orth` column was added for: the card says お伽話, the list says 御伽話.
    Measured at 20.6% of single-token mined words on the live collection."""
    assert rank_of["お伽話"] == 3
    assert rank_of["御伽話"] == 3           # the lemma still works, for an unconjugated hit


def test_a_conjugating_verb_matches_by_its_orth(rank_of):
    """anki_miner writes `orth_base` for 動詞/形容詞: 引きずって mines as 引きずる, never 引き摺る."""
    assert rank_of["引きずる"] == 4
    assert rank_of["引き摺る"] == 4


def test_a_kanji_spelling_reaches_a_katakana_lemma(rank_of):
    """The report would tell the user to learn スドウ while their show writes 須藤."""
    assert rank_of["須藤"] == 2
    assert rank_of["スドウ"] == 2


def test_orth_and_word_of_one_row_share_a_rank(rank_of):
    """Several keys reaching one rank is the point — that is what clusters a word's cards."""
    assert rank_of["むしろ"] == rank_of["寧ろ"] == 5


def test_a_repeated_key_keeps_the_lower_rank(tmp_path):
    """A spelling that appears again further down must never be demoted: the first (best) rank wins,
    or a word the user should learn now sinks to the bottom of the queue."""
    rows = list(_ROWS) + [("お伽話", "お伽話", "オトギバナシ")]
    index = load_rank_index(_write_list(tmp_path / "list.csv", rows))
    assert index["お伽話"] == 3, "rank 9 overwrote rank 3"


def test_orth_is_inserted_before_word(tmp_path):
    """Precedence within a row. Here row 1's `Orth` collides with row 0's `Word`; the orth is the
    primary key, so it must already be claimed by row 0 and row 1 must not steal it."""
    rows = [("冒険", "ぼうけん", "ボウケン"), ("散歩", "冒険", "サンポ")]
    index = load_rank_index(_write_list(tmp_path / "list.csv", rows))
    assert index["冒険"] == 0
    assert index["散歩"] == 1


def test_a_list_with_no_orth_column_still_loads(tmp_path):
    """Older result folders predate D4 entirely. They must load and match on the lemma alone rather
    than raise — the user should not have to re-run a multi-minute analysis to use the feature."""
    rows = [(word, reading) for word, _orth, reading in _ROWS]
    index = load_rank_index(_write_list(tmp_path / "list.csv", rows, header=("Word", "Reading")))
    assert index["御伽話"] == 3
    assert "お伽話" not in index            # nothing to match it with, and that is honest
    assert len(index) == len(_ROWS)


def test_a_blank_orth_cell_falls_back_to_the_word(tmp_path):
    rows = [("冒険", "", "ボウケン"), ("老婆", "老婆", "ロウバ")]
    index = load_rank_index(_write_list(tmp_path / "list.csv", rows))
    assert index == {"冒険": 0, "老婆": 1}


def test_an_unusable_row_still_consumes_its_rank(tmp_path):
    """A row that yields no key must not shift every row beneath it — the rank IS the row index, and
    quietly renumbering the list would reorder the user's whole backlog by one."""
    rows = [("冒険", "冒険", "ボウケン"), ("", "", ""), ("老婆", "老婆", "ロウバ")]
    index = load_rank_index(_write_list(tmp_path / "list.csv", rows))
    assert index["老婆"] == 2


def test_an_empty_list_yields_an_empty_index(tmp_path):
    """Empty state: the user has run an analysis that produced no words."""
    assert load_rank_index(_write_list(tmp_path / "list.csv", [])) == {}


def test_a_missing_list_yields_an_empty_index(tmp_path):
    """Empty state: a first run, before any analysis exists. Whether the list is present at all is
    preflight's question; raising here would take the panel down instead of explaining itself."""
    assert load_rank_index(str(tmp_path / "nope.csv")) == {}
    assert load_rank_index("") == {}


def test_an_unreadable_list_degrades_to_no_matches(tmp_path):
    """A directory where the CSV should be. No matches is a survivable answer on the way to a
    collection write; an exception is not."""
    (tmp_path / "priority_learning_list.csv").mkdir()
    assert load_rank_index(str(tmp_path / "priority_learning_list.csv")) == {}


def test_the_real_golden_list_loads_with_its_orth_divergence():
    """Against the repo's actual 200-row analyser output rather than a fixture of our own making —
    it carries the BOM, the real column set, and 52 rows whose orth differs from the lemma.

    `ナカノ` / `中野` is the same shape as `スドウ` / `須藤`: a katakana lemma the user would never
    recognise, reachable only through the spelling their content actually uses."""
    path = os.path.join(_ROOT, "tests", "Test Resources", "ja", "expected_output.csv")
    index = load_rank_index(path)

    assert index, "the golden list produced no keys — is the BOM being read as part of 'Word'?"
    # 16 before words kept their affixes (高校生, おばあさん…); 20 until the tagger read １人 as 1 + 人; 20 again once
    # names stay whole (フータロー's 6 uses join the head); 19 once stretched words read as themselves (いー fell
    # below); 22 since words made of words are one word (優先席, 家庭教師 and 社会貢献 join above it); 21 since a polite
    # お word is read through its known word (おばあさん sits lower); 22 since a story's own kanji words are one word (the
    # sample's 三玖, a name, joins near the head); 24 since set phrases are rows of their own (席を譲る and このまま join
    # above it); 25 since one-kanji dictionary words are list words where they stand on their own (門 joins above it);
    # 28 since the words the tagger cuts at their grammar are words of their own (それで, なんで and どこにも join above it);
    # 29 since grammar expressions are rows of their own (とする joins above it). (All on the old samples' 中野 /
    # ナカノ; on the public-domain samples, 2026-11-10, Hon-SM: the café episode's 早川 / ハヤカワ, rank 5; rank 8 since the
    # fixture known-words list is a learner who knows the commonest 3,000 words, 2026-11-11, Hon-TR: もう, まで … show.)
    assert index["早川"] == index["ハヤカワ"] == 8
    with open(path, encoding="utf-8-sig", newline="") as handle:
        first = next(csv.DictReader(handle))
    assert index[first["Word"]] == index[first["Orth"]] == 0, "the list's head row is rank 0 by either key"
    assert index["極楽"] == 3


# --- resolving the word field --------------------------------------------------------------------- #
def test_field_zero_is_the_default():
    """anki_miner's preflight enforces it (Anki dedups on field 0), so it is the right default for
    every note type it made: Lapis and Kiku put Expression at 0, Senren puts word at 0."""
    assert resolve_word_field("Lapis", ["Expression", "Sentence", "Audio"], {}) == "Expression"
    assert resolve_word_field("Senren", ["word", "sentence"], {}) == "word"


def test_the_override_map_beats_field_zero():
    """`Migaku Japanese` has `Sentence` at index 0 while its word lives in `Target Word`. Field 0 is
    an anki_miner invariant, not an Anki one — ordering a backlog by whole sentences would match
    nothing and look like the feature is broken."""
    fields = ["Sentence", "Target Word", "Definitions", "Images"]
    overrides = {"Migaku Japanese": "Target Word"}
    assert resolve_word_field("Migaku Japanese", fields, overrides) == "Target Word"


def test_an_override_for_another_note_type_is_ignored():
    overrides = {"Migaku Japanese": "Target Word"}
    assert resolve_word_field("Lapis", ["Expression", "Sentence"], overrides) == "Expression"


def test_an_override_is_matched_case_insensitively():
    """Typed by hand in a settings dialog; it should not lose to 'expression' vs 'Expression'."""
    assert resolve_word_field("Kiku", ["Sentence", "Expression"],
                              {"Kiku": "expression"}) == "Expression"


def test_a_stale_override_falls_back_to_field_zero():
    """A misspelled or renamed field must not resolve to a field that does not exist. The panel shows
    the resolved name before any write, so the fallback reads as the wrong field on screen rather
    than failing silently at match time."""
    fields = ["Sentence", "Target Word"]
    assert resolve_word_field("Migaku Japanese", fields, {"Migaku Japanese": "Target Wrod"}) == "Sentence"


def test_a_note_type_with_no_fields_resolves_to_nothing():
    assert resolve_word_field("Lapis", [], {}) == ""
    assert resolve_word_field("Lapis", None, None) == ""


def test_a_blank_override_is_ignored():
    assert resolve_word_field("Lapis", ["Expression"], {"Lapis": "   "}) == "Expression"


# --- reading a note ------------------------------------------------------------------------------- #
def _note(model, fields):
    """A `notesInfo` reply, in Anki's own shape: {name: {"value": …, "order": n}}."""
    return {"noteId": 1789711432547, "modelName": model,
            "fields": {name: {"value": value, "order": order}
                       for order, (name, value) in enumerate(fields)}}


def test_a_lapis_note_resolves_to_its_expression():
    note = _note("Lapis", [("Expression", "お伽話"), ("Sentence", "祖母がお伽話を聞かせてくれた。")])
    assert target_word(note, {}) == "お伽話"


def test_a_migaku_note_resolves_through_the_override_map(ja_sentences):
    """Field 0 holds a real sentence from the shared test resources. Picking it would hand the
    planner a sentence as a word — matched against nothing, and invisible until the user wonders why
    their Migaku cards never move."""
    note = _note("Migaku Japanese", [("Sentence", ja_sentences[3]), ("Target Word", "冒険")])
    assert target_word(note, {"Migaku Japanese": "Target Word"}) == "冒険"
    assert target_word(note, {}) == normalize_word(ja_sentences[3]), "without the override it is field 0"


def test_the_order_value_decides_field_zero_not_the_dict_order():
    """JSON round-trips have no obligation to preserve insertion order, and 'field 0' is meaningless
    if the wrong one is trusted."""
    note = {"modelName": "Lapis", "fields": {
        "Sentence": {"value": "老婆は静かに頷いた。", "order": 1},
        "Expression": {"value": "老婆", "order": 0},
    }}
    assert target_word(note, {}) == "老婆"


def test_a_furigana_field_resolves_to_the_bare_word():
    note = _note("Lapis", [("Expression", "引[ひ]きずる"), ("Reading", "ひきずる")])
    assert target_word(note, {}) == "引きずる"


def test_an_image_only_field_is_skipped_not_crashed_on():
    """The empty answer is an ordinary one: the planner treats the card as unmatched and leaves its
    position alone, which is better than moving it on a guess."""
    note = _note("Lapis", [("Expression", '<img src="paste-8f2c.jpg">'), ("Sentence", "冒険だ。")])
    assert target_word(note, {}) == ""


def test_a_malformed_note_is_empty_rather_than_fatal():
    """Everything is read with `.get()`: cardsInfo/notesInfo payloads are version-dependent, and this
    runs immediately before a write that has no Anki-side undo."""
    assert target_word(None, {}) == ""
    assert target_word({}, {}) == ""
    assert target_word({"modelName": "Lapis"}, {}) == ""
    assert target_word({"modelName": "Lapis", "fields": {}}, {}) == ""
    assert target_word({"modelName": "Lapis", "fields": {"Expression": "老婆"}}, {}) == "老婆"


def test_a_note_field_missing_its_order_does_not_become_field_zero():
    """An entry with no order sorts last rather than pretending to be the word field."""
    note = {"modelName": "Lapis", "fields": {
        "Expression": {"value": "冒険", "order": 0},
        "Notes": {"value": "覚えにくい"},
    }}
    assert target_word(note, {}) == "冒険"


# --- the two halves together ---------------------------------------------------------------------- #
def test_a_mined_card_finds_its_rank(rank_of):
    """End to end, as the planner will use it: anki_miner's spelling on the card, Surasura's lemma in
    the list, one rank out the other side."""
    note = _note("Lapis", [("Expression", "引きずる[ひきずる]"),
                           ("Sentence", "彼は足を引きずって歩いていた。")])
    word = target_word(note, {})
    assert word == "引きずる"
    assert rank_of[word] == 4


def test_an_unmatched_card_is_simply_absent(rank_of):
    """No error, no fallback, no guess — just a word the list has never seen."""
    note = _note("Lapis", [("Expression", "準備")])
    assert target_word(note, {}) not in rank_of


def test_the_match_index_is_cores_re_exported_unchanged():
    """The matcher moved to `app/anki_match.py` so the report's backlog badge can share it (core never
    imports `modules/`). Every name Junban uses must be the SAME object, not a copy that could drift:
    a second matcher would let the report and the reorder disagree about the same card."""
    from app import anki_match
    from modules.junban import match

    names = ("normalize_word", "target_word", "resolve_word_field", "build_index", "load_index",
             "load_rank_index", "lookup", "fold_kana", "load_library", "library_floor", "phrase_lemmas",
             "find_phrases", "phrase_places", "sentence_span", "unknowns_beside", "row_markers",
             "row_total",
             "marker_thresholds", "normalize_markers", "unknown_markers", "Index", "MARKERS",
             "MARKER_DEFAULTS", "CONTEXT_COLUMNS", "TOTAL_COLUMNS")
    for name in names:
        assert getattr(match, name) is getattr(anki_match, name), name


def test_importing_the_match_index_costs_nothing():
    """`settings_manager` imports this package on every settings load, so nothing reachable from it
    may drag in a tokenizer. The tokenizer fallback of spec §6 is deliberately NOT implemented here
    for exactly this reason — a `from fugashi import ...` at the top of this file would put Unidic on
    the critical path of every launch, feature on or off.

    A clean subprocess, mirroring `tests/test_lazy_imports.py`: checking `sys.modules` in-process
    proves nothing, because pytest's own plugins have already imported half of these."""
    import subprocess
    import sys

    watch = ("fugashi", "unidic_lite", "jieba", "pandas", "tkinter", "urllib.request")
    code = ("import modules.junban.match; import sys; "
            "print(','.join(m for m in %r if m in sys.modules))" % (watch,))
    env = {**os.environ, "PYTHONPATH": _ROOT, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)

    assert result.returncode == 0, f"importing modules.junban.match failed:\n{result.stderr}"
    assert [m for m in result.stdout.strip().split(",") if m] == []

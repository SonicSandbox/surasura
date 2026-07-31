"""Frequency-list lookups must bridge unidic's orthographic lemmas to ordinary spellings.

The analyzer tokenizes with unidic, which returns lemmas like 為る / 矢張り / 其れ. Every frequency
list stores する / やっぱり / それ. Before the bridge existed the single most common verb in Japanese
reported as "Outside" in the Tier column, and any feature that joins an analyzer lemma to a list
rank silently saw nothing for those words.

Real vocabulary throughout — these are exactly the words that broke, not invented tokens.
"""



from app import analyzer


# (unidic lemma the analyzer emits, spelling a frequency list actually stores)
ORTHOGRAPHIC_PAIRS = [
    ("為る", "する"),
    ("無い", "ない"),
    ("其れ", "それ"),
    ("此の", "この"),
    ("矢張り", "やっぱり"),
    ("然し", "しかし"),
    ("有り難う", "ありがとう"),
    ("成る", "なる"),
    ("出来る", "できる"),
]


def test_alias_table_bridges_unidic_lemmas_to_list_spellings():
    """The generated table must map every known orthographic lemma to its ordinary spelling."""
    for lemma, spelling in ORTHOGRAPHIC_PAIRS:
        assert analyzer._spelling_alias(lemma) == spelling, (
            f"{lemma} should resolve to {spelling}"
        )


def test_tier_label_found_via_alias():
    """A lemma absent from the list is still tiered when its spelling is present.

    This is the actual bug: 為る is never in a frequency list, する is at rank 12, and the word
    used to come back Outside.
    """
    freq_data = {"Global": {"する": 12, "ない": 26, "それ": 23}}

    assert analyzer.get_tier_label("為る", freq_data) == [("Global", "1")]
    assert analyzer.get_tier_label("無い", freq_data) == [("Global", "1")]
    assert analyzer.get_tier_label("其れ", freq_data) == [("Global", "1")]


def test_direct_hit_beats_alias():
    """When the lemma itself is in the list, its OWN rank wins.

    呉れる appears in some lists at its own (rare) rank while its alias くれる is far more common.
    Crediting the alias would report the word as commoner than the entry we actually matched.
    """
    freq_data = {"Global": {"呉れる": 35769, "くれる": 473}}

    tiers = analyzer.get_tier_label("呉れる", freq_data)
    # rank 35769 -> beyond the last threshold -> Tier 5, NOT the Tier 1 that 473 would give.
    assert tiers == [("Global", "5")]


def test_word_with_no_alias_and_no_entry_is_outside():
    """Unknown words must still report Outside — the bridge must not invent matches."""
    freq_data = {"Global": {"する": 12}}
    assert analyzer.get_tier_label("覗き込む", freq_data) == []


def test_multiple_lists_each_resolved_independently():
    """Each list is consulted on its own; a hit in one must not leak into another."""
    freq_data = {
        "Anime": {"する": 9},
        "Novels": {},          # 為る/する in neither form
    }
    assert analyzer.get_tier_label("為る", freq_data) == [("Anime", "1")]


def test_empty_freq_data_is_safe():
    """No frequency lists loaded is a normal state (fresh install), not an error."""
    assert analyzer.get_tier_label("為る", {}) == []


def test_missing_reference_data_degrades_quietly(monkeypatch):
    """If the generated table is absent the app must still run — tiers just lose the bridge.

    Guards the CLAUDE.md rule that optional/bundled extras never crash the app.

    Both the sys.modules entry AND the attribute on the `app` package have to go: once a
    submodule has been imported, `from app import reference_data` resolves it as an attribute
    and never consults sys.modules at all.
    """
    import sys
    import app

    monkeypatch.setitem(sys.modules, "app.reference_data", None)
    monkeypatch.delattr(app, "reference_data", raising=False)

    assert analyzer._spelling_alias("為る") is None

    freq_data = {"Global": {"する": 12}}
    assert analyzer.get_tier_label("為る", freq_data) == []      # degraded, but no exception


def test_reference_data_import_is_lazy_and_tables_decode():
    """The shipped tables must decode, and stay out of import cost until asked for."""
    from app import reference_data

    aliases = reference_data.aliases()
    ranks = reference_data.spoken_ranks()

    assert len(aliases) > 10_000, "alias table looks truncated"
    assert len(ranks) > 10_000, "spoken-rank table looks truncated"
    assert reference_data.REVISION

    # Spoken ranks are ints; 0 is the documented sentinel for "beyond the reference corpora".
    assert all(isinstance(v, int) and v >= 0 for v in list(ranks.values())[:500])


def test_spoken_ranks_reflect_real_modality():
    """Sanity-check the shipped ranks against words whose modality is not in dispute."""
    from app import reference_data
    ranks = reference_data.spoken_ranks()

    # 会社 is everyday speech; 佇む is novel-narration vocabulary you essentially never hear.
    assert 0 < ranks.get("会社", 10 ** 9) < 5_000
    assert ranks.get("佇む", 0) > 40_000

    # Narration verbs are exactly what the table is for.
    assert "覗き込む" in ranks and "囁く" in ranks


def test_build_time_pos_filter_removes_names_and_interjections():
    """Proper nouns and interjections must never reach the table.

    Absence from a spoken corpus is mostly evidence of being a character name, not of being
    literary — without this filter the output is a cast list. unidic catches the names it knows
    (固有名詞) and every interjection (感動詞).
    """
    from app import reference_data
    ranks = reference_data.spoken_ranks()

    for name in ("ルッツ", "エミリア"):           # tagged 固有名詞
        assert name not in ranks, f"{name} is a proper noun and must be filtered at build time"
    for interjection in ("んっ", "ふふ"):          # tagged 感動詞
        assert interjection not in ranks


def test_names_unknown_to_unidic_are_left_for_runtime_dispersion():
    """Documents the division of labour, so nobody 'fixes' this by widening the POS filter.

    unidic tags アルマ as 普通名詞 — it simply doesn't know the word is a character name — so the
    build-time filter cannot catch it. It is instead removed at runtime by series dispersion:
    アルマ occurs in ONE work, whereas real prose vocabulary is spread across many.
    """
    from app import reference_data
    assert "アルマ" in reference_data.spoken_ranks()

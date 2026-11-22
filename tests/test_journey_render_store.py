"""The journey v3 page's episodes from a real library store (J-DATA; SPEC §3.2, §5.3): `journey_render.store_facts`
reads the store through its own readers only (`read_feed`, `scheduled_ids`, `cards_of`; pre-studied and growth once
their lanes land), never writes, and a store without those readers is an honest empty state.

What a wrong answer would cost a learner: the page naming an episode by another's id (a pre-studied press landing on
the wrong episode), a stone or a growth bar from nowhere, or the render changing the library it only reads."""
import os

import pytest

from app import journey_render as jr
from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, roots


@pytest.mark.parametrize("language", LANGUAGES)
def test_store_facts_follow_the_study_order_by_item_id_and_write_nothing(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = [i for i, _tier in store.scheduled_ids()]
    assert ids                                           # a real library: its episodes to name
    versions = store._versions() if hasattr(store, "_versions") else None
    store.close()
    db = ls.library_db_path(language, data_dir)
    before = os.stat(db).st_mtime_ns
    facts = jr.store_facts(language, data_dir, user_files_dir)
    assert facts is not None and facts.order[:len(ids)] == ids
    assert set(facts.order) <= set(facts.items) and facts.library
    assert facts.pre == {} or isinstance(facts.pre, dict)
    assert os.stat(db).st_mtime_ns == before
    if versions is not None:
        again = ls.open_store(language, data_dir, user_files_dir)
        assert again._versions() == versions
        again.close()
    out = jr.build(language, [], [], facts=facts, pitch=jr.Pitch(language, kanjium={}))
    assert [e[0] for e in out.head["eps"]] == facts.order
    assert all(e[9] in ("cut", "raw", "nothing", "rock") for e in out.head["eps"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_store_is_no_facts_and_the_page_names_episodes_by_file(language):
    data_dir, user_files_dir = roots(language)
    assert jr.store_facts(language, data_dir, user_files_dir) is None
    out = jr.build(language, [], [{"File": "ep01.srt", "Coverage (%)": 88.5}], pitch=jr.Pitch(language, kanjium={}))
    assert out.head["eps"][0][0] is None and out.head["eps"][0][6] == 88.5


def test_a_store_without_growth_or_pre_studied_readers_draws_neither(monkeypatch):
    store = migrated("ja")
    data_dir, user_files_dir = roots("ja")
    store.close()
    monkeypatch.delattr(ls.Store, "growth_of", raising=False)
    monkeypatch.delattr(ls.Store, "prestudied_marks", raising=False)
    facts = jr.store_facts("ja", data_dir, user_files_dir)
    assert facts.growth == {} and facts.pre == {}
    out = jr.build("ja", [], [], facts=facts, pitch=jr.Pitch("ja", kanjium={}))
    assert all(e[11] is None and e[12] is None for e in out.head["eps"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_growth_comes_from_the_stores_own_snapshots_per_episode_and_nothing_counted_is_no_bar(language):
    """Kura-GS's snapshots (#585), read through `growth_of`: each episode its own figures, never summed into its
    show; a file with no words (0 of 0) has no bar, not 0 %."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = [i for i, _tier in store.scheduled_ids()]
    feed = {row["id"]: row for row in store.read_feed()["items"]}
    first, second = feed[ids[0]]["rel_path"], feed[ids[1]]["rel_path"]
    store.record_growth({first: (60, 100, 25), second: (0, 0, 0)})
    store.close()
    facts = jr.store_facts(language, data_dir, user_files_dir)
    out = jr.build(language, [], [], facts=facts, pitch=jr.Pitch(language, kanjium={}))
    growth = {e[0]: e[12] for e in out.head["eps"]}
    assert growth[ids[0]][:2] == [60.0, 25] and growth[ids[0]][7] == 25   # added = last: the first Generate's
    assert growth[ids[1]] is None
    assert all(len(show) == 4 for show in out.head["shows"])               # a show carries no "+N" of its own

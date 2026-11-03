"""3.0's Sources, K6 for a subtitle found through its video: the library's one language rule (`sources._refusal`) holds
for every text new to the library, whatever video it pairs with.

A look pairs a subtitle with its video by name (`Movie.srt` beside `Movie.mkv`) and, when that video is already an
item's, records the file on that item. The pairing used to stand in for the language check, so an English `.srt` a
learner keeps beside a movie or an episode already in became one of its texts: English "words" on the list, cards made
from the wrong lines, and a later switch free to make it the episode's text. Setup's *Choose a file…* with a video
(`subtitles_for_video`) took the same shortcut by the name's tag alone. What a wrong answer would cost a learner:
  * an English (or other-language) subtitle recorded on an episode, listed, mined or switched in as its text;
  * a real Japanese / Chinese subtitle with no language tag refused because it was found through its video;
  * the English file read again on every look (it is remembered by its stats, as every refused text is).

The subtitles are real: `placed_episode.srt` (ja) and `night_market.srt` (zh) from tests/Test Resources/, and their
English translations beside them, copied byte for byte (CRLF, as the resources are).
"""
import os
import time

import pytest

from app import sources
from app.connect import library
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _spy_reads, _video  # noqa: F401

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
OURS = {"ja": os.path.join("ja", "placed_episode.srt"), "zh": os.path.join("zh", "night_market.srt")}
ENGLISH = {"ja": os.path.join("ja", "placed_episode_english.srt"), "zh": os.path.join("zh", "night_market_english.srt")}
OUR_TAG = {"ja": "ja", "zh": "zh"}
# nested as a learner keeps them: a drive's folder, the show, a season folder
SHOW = os.path.join("Anime", "Tsukikage", "Season 1")


def _copy(resource, path, age=60):
    """The resource's bytes at `path` (its CRLF kept), settled `age` seconds back."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(os.path.join(RESOURCES, resource), "rb") as f:
        body = f.read()
    with open(path, "wb") as f:
        f.write(body)
    t = time.time() - age
    os.utime(path, (t, t))
    return path


def _origins(store):
    return {k: (o.item_id, bool(o.version)) for k, o in store.origins().items()}


def _paired_subtitle(store, item_id):
    return os.path.normcase(os.path.normpath((library.pairing_of(store, item_id) or {}).get("origin") or ""))


def test_the_english_resources_are_crlf_and_hold_no_word_of_ours():
    """The fixtures are what the scenarios claim: CRLF line ends, English lines only (refused in both libraries), and
    the subtitles they translate are the libraries' own language."""
    for language in LANGUAGES:
        with open(os.path.join(RESOURCES, ENGLISH[language]), "rb") as f:
            english = f.read()
        with open(os.path.join(RESOURCES, OURS[language]), "rb") as f:
            ours = f.read()
        assert b"\r\n" in english and english.count(b"\n") == english.count(b"\r\n")
        assert sources._refusal(english, "ja") == sources._refusal(english, "zh") == "script"
        assert sources._refusal(ours, language) is None


# --- 1 · the look: a subtitle named like a video that is already an item's ---------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_an_english_srt_named_like_a_movie_already_in_is_never_its_text(language, monkeypatch):
    """A movie in through its video's own subtitle folder (`Subs/<video>/`, A11) — no episode number, so nothing but its
    video ties a later file to it. An untagged English `Movie.srt` put beside the video is refused by the one language
    rule: never recorded on the movie, nothing copied, Connect's subtitle still the Japanese / Chinese one — and the
    next look doesn't read it again (remembered by its stats)."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    folder = os.path.join(src, SHOW)
    _video(os.path.join(folder, "Movie.mkv"))
    ours = _copy(OURS[language], os.path.join(folder, "Subs", "Movie", "dialogue.srt"))
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1
        before = _origins(store)
        (item_id, _v), = before.values()
        assert _paired_subtitle(store, item_id) == os.path.normcase(os.path.normpath(ours))
        english = _copy(ENGLISH[language], os.path.join(folder, "Movie.srt"))
        got = _look(store, language, root, full=True)
        assert got["added"] == 0 and got["switched"] == 0
        assert _origins(store) == before, "the English file is recorded on nothing"
        assert _paired_subtitle(store, item_id) == os.path.normcase(os.path.normpath(ours))
        read = []
        _spy_reads(monkeypatch, read)
        _look(store, language, root, full=True)
        assert english not in read, "a refused text is not read again until it changes"


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_untagged_subtitle_of_ours_named_like_a_movie_already_in_still_joins_it(language):
    """The rule refuses by what a file holds, never by how it was found: a second release of the movie's dialogue in
    our language, untagged and named like the video, is still recorded on the movie (its video's item), as before."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    folder = os.path.join(src, SHOW)
    _video(os.path.join(folder, "Movie.mkv"))
    _copy(OURS[language], os.path.join(folder, "Subs", "Movie", "dialogue.srt"))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        (item_id, _v), = _origins(store).values()
        again = os.path.join(folder, "Movie.srt")
        _copy(OURS[language], again)
        with open(again, "ab") as f:                         # another release: other bytes, the same dialogue
            f.write(b"\r\n")
        os.utime(again, (time.time() - 60, time.time() - 60))
        _look(store, language, root, full=True)
        assert [v for k, v in _origins(store).items() if k.endswith("/movie.srt")] == [(item_id, False)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_english_srt_beside_an_episode_already_in_is_never_one_of_its_texts(language):
    """A numbered episode in with its subtitle, then an untagged English file paired by its number: kept out by the
    same rule (never a text, never a version), the episode's subtitle unchanged."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    folder = os.path.join(src, SHOW)
    _video(os.path.join(folder, "Tsukikage - 01.mkv"))
    ours = _copy(OURS[language], os.path.join(folder, "Subs", "Tsukikage - 01", "dialogue.srt"))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _origins(store)
        (item_id, _v), = before.values()
        _copy(ENGLISH[language], os.path.join(folder, "Tsukikage - 01.srt"))
        _copy(ENGLISH[language], os.path.join(folder, "[Fan] Tsukikage - 01.srt"))
        got = _look(store, language, root, full=True)
        assert got["added"] == 0 and got["switched"] == 0 and _origins(store) == before
        assert _paired_subtitle(store, item_id) == os.path.normcase(os.path.normpath(ours))


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_tagged_pair_brings_in_ours_and_never_the_english_one(language):
    """`.ja.srt` + `.en.srt` (`.zh.srt` for Chinese) beside a video, first look and after: ours is the episode's text,
    the English one is never anything."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    folder = os.path.join(src, SHOW)
    _video(os.path.join(folder, "Tsukikage - 02.mkv"))
    ours = _copy(OURS[language], os.path.join(folder, f"Tsukikage - 02.{OUR_TAG[language]}.srt"))
    english = _copy(ENGLISH[language], os.path.join(folder, "Tsukikage - 02.en.srt"))
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1
        (item_id, _v), = _origins(store).values()
        assert _paired_subtitle(store, item_id) == os.path.normcase(os.path.normpath(ours))
        os.utime(english, (time.time() - 30, time.time() - 30))   # touched: looked at again
        _look(store, language, root, full=True)
        assert list(_origins(store).values()) == [(item_id, False)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_english_srt_named_like_the_video_never_keeps_our_untagged_one_out(language):
    """First look, both untagged: the English file named exactly like the video ranks first (made for it), is refused,
    and our file behind it (paired by its number) is the episode's text."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    folder = os.path.join(src, SHOW)
    _video(os.path.join(folder, "[Grp] Tsukikage - 03 [1080p].mkv"))
    _copy(ENGLISH[language], os.path.join(folder, "[Grp] Tsukikage - 03 [1080p].srt"))
    ours = _copy(OURS[language], os.path.join(folder, "Tsukikage - 03 [Kiriya].srt"))
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1
        (item_id, _v), = _origins(store).values()
        assert _paired_subtitle(store, item_id) == os.path.normcase(os.path.normpath(ours))
        assert os.path.basename(library.pairing_of(store, item_id)["video_path"]) == "[Grp] Tsukikage - 03 [1080p].mkv"


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_english_pick_refused_through_its_video_gives_way_to_our_file_behind_it(language):
    """B5 through a video already an item's: the movie in; then an English `Movie.ass` (the `.ass` first in the order)
    and our `Movie.srt` arrive together. The English one is refused and ours, behind it, is recorded on the movie."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    folder = os.path.join(src, SHOW)
    _video(os.path.join(folder, "Movie.mkv"))
    _copy(OURS[language], os.path.join(folder, "Subs", "Movie", "dialogue.srt"))
    with open(os.path.join(RESOURCES, ENGLISH[language]), encoding="utf-8") as f:
        cues = [c.splitlines() for c in f.read().strip().split("\n\n")]
    events = "".join(f"Dialogue: 0,0:00:{n:02d}.00,0:00:{n + 1:02d}.00,Default,{' '.join(c[2:])}\r\n"
                     for n, c in enumerate(cues, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        (item_id, _v), = _origins(store).values()
        english = os.path.join(folder, "Movie.ass")
        with open(english, "w", encoding="utf-8", newline="") as f:
            f.write("[Events]\r\nFormat: Layer, Start, End, Style, Text\r\n" + events)
        os.utime(english, (time.time() - 60, time.time() - 60))
        _copy(OURS[language], os.path.join(folder, "Movie.srt"))
        _look(store, language, root, full=True)
        got = {k.rsplit("/", 1)[1]: v for k, v in _origins(store).items()}
        assert got.get("movie.srt") == (item_id, False) and "movie.ass" not in got


# --- 2 · a text already in, its bytes changed: never another language's copied in ------------------------------- #

def _episode_in(language, store):
    """`Tsukikage - 01` in, its subtitle beside its video: (root, the original, the item, its copy's path)."""
    src = _drive("Media")
    folder = os.path.join(src, SHOW)
    _video(os.path.join(folder, "Tsukikage - 01.mkv"))
    original = _copy(OURS[language], os.path.join(folder, f"Tsukikage - 01.{OUR_TAG[language]}.srt"))
    root = store.add_source(src)
    (item_id,) = _look(store, language, root, first=True)["ids"]
    return root, original, item_id, os.path.join(store.data_dir, *store.item(item_id)["rel_path"].split("/"))


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_original_saved_over_with_english_is_never_copied_over_the_item(language):
    """S5 follows an original's new text into its copy; English saved over the Japanese / Chinese original (a subtitle
    tool, a download into the same name) is refused by the one rule: the copy keeps our text."""
    store, data_dir = _empty(language)
    with store:
        root, original, item_id, copy = _episode_in(language, store)
        with open(copy, "rb") as f:
            before = f.read()
        _copy(ENGLISH[language], original, age=30)
        got = _look(store, language, root, full=True)
        assert got["recopied"] == 0
        with open(copy, "rb") as f:
            assert f.read() == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_gone_is_never_copied_back_from_an_english_original(language, monkeypatch):
    """Item 8a copies a missing copy back from the item's latest original. A library made before this fix may hold an
    English file recorded on its movie (the look let it through: replayed here with the rule off for one look); with
    the copy gone, the copy comes back from our original, never the English one recorded later."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    folder = os.path.join(src, SHOW)
    _video(os.path.join(folder, "Movie.mkv"))
    _copy(OURS[language], os.path.join(folder, "Subs", "Movie", "dialogue.srt"))
    with store:
        root = store.add_source(src)
        (item_id,) = _look(store, language, root, first=True)["ids"]
        copy = os.path.join(data_dir, *store.item(item_id)["rel_path"].split("/"))
        with open(copy, "rb") as f:
            before = f.read()
        _copy(ENGLISH[language], os.path.join(folder, "Movie.srt"))
        with monkeypatch.context() as old:
            old.setattr(sources, "_refusal", lambda *_a, **_k: None)
            _look(store, language, root, full=True)
        assert sorted(v for v in _origins(store).values()) == [(item_id, False)] * 2   # (the old library's state)
        os.remove(copy)
        store.sync_disk()
        assert store.item(item_id)["availability"] == "missing"
        assert _look(store, language, root, full=True)["restored"] == 1
        with open(copy, "rb") as f:
            assert f.read() == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_version_saved_over_with_english_is_never_switched_in(language):
    """LM3 switches to a better version of the pick's own group (the `.ass` over the `.srt`); a signs-only `.ass`
    passed over as thin, later saved over with English dialogue, is judged again and refused by the one rule — never
    switched in as the episode's text."""
    from tests.test_sources_scenarios import _THIN
    store, data_dir = _empty(language)
    src = _drive("Media")
    folder = os.path.join(src, SHOW)
    t = OUR_TAG[language]
    _copy(OURS[language], os.path.join(folder, f"[SubsA] Tsukikage - 01.{t}.srt"))
    with store:
        root = store.add_source(src)
        (item_id,) = _look(store, language, root, first=True)["ids"]
        copy = os.path.join(data_dir, *store.item(item_id)["rel_path"].split("/"))
        with open(copy, "rb") as f:
            before = f.read()
        signs = os.path.join(folder, f"[SubsA] Tsukikage - 01.{t}.ass")
        with open(signs, "w", encoding="utf-8", newline="\n") as f:
            f.write(_THIN[language] + "; signs\n")
        os.utime(signs, (time.time() - 60, time.time() - 60))
        assert _look(store, language, root)["switched"] == 0
        _copy(ENGLISH[language], signs, age=30)
        assert _look(store, language, root, full=True)["switched"] == 0
        assert _look(store, language, root, full=True)["switched"] == 0
        assert os.path.exists(copy)
        with open(copy, "rb") as f:
            assert f.read() == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_use_another_groups_subtitles_never_switches_in_an_english_file(language):
    """*Use [B]'s subtitles* (LM2's switch, the learner's own): group B's episode 1 saved over with English after the
    look recorded it is never switched in — that episode keeps A's text, B's episode 2 is switched as asked."""
    from tests.test_sources_groups import _group_b, _show, _work
    store, data_dir = _empty(language)
    src = _drive("Anime")
    _show_name, a, b, _v = _show(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        rows = store.conn.execute("SELECT id, rel_path FROM items ORDER BY id").fetchall()
        _copy(ENGLISH[language], b[1], age=30)
        _look(store, language, root, full=True)                    # (its record follows the file: LM3)
        store.switch_group(_work(store), _group_b(store))
        held = {}
        for item_id, _rel in rows:
            rel = store.item(item_id)["rel_path"]
            with open(os.path.join(data_dir, *rel.split("/")), "rb") as f:
                held[item_id] = f.read()
        with open(os.path.join(RESOURCES, ENGLISH[language]), "rb") as f:
            english = f.read()
        with open(a[1], "rb") as f1, open(b[2], "rb") as f2:
            assert [held[i] for i, _r in rows[:2]] == [f1.read(), f2.read()]
        assert english not in held.values()


@pytest.mark.parametrize("language,title", (("ja", "星屑の剣士になりたくて！"), ("zh", "西游记")))
def test_an_audiobooks_transcript_is_never_copied_back_from_an_english_original(language, title):
    """Item 8a for an audiobook's transcript: its copy gone and its original saved over with English — nothing is
    copied back (the item waits for its text), never the English."""
    from tests.test_audiobook_transcripts import _alone
    store, data_dir, src, _m4b, srt = _alone(language, title)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        (item_id,) = [r[0] for r in store.conn.execute("SELECT id FROM items")]
        copy = os.path.join(data_dir, *store.item(item_id)["rel_path"].split("/"))
        os.remove(copy)
        store.sync_disk()
        _copy(ENGLISH[language], srt, age=30)
        assert _look(store, language, root, full=True)["restored"] == 0
        assert not os.path.exists(copy)


# --- 3 · setup's *Choose a file…* with a video ------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_chosen_videos_subtitles_never_include_an_untagged_english_one(language, tmp_path):
    """`subtitles_for_video`: an untagged English `.srt` named like the video ranks first by name, yet holds none of our
    language — never offered. Only English beside it: none (setup says so and offers the folder). Ours untagged,
    paired by its number: offered; ours tagged and named like the video: offered first."""
    folder = tmp_path / "Anime" / "Tsukikage"
    video = _video(str(folder / "Tsukikage - 04.mkv"))
    english = _copy(ENGLISH[language], str(folder / "Tsukikage - 04.srt"))
    _copy(ENGLISH[language], str(folder / "Tsukikage - 04.eng.srt"))
    assert sources.subtitles_for_video(video, language) == []
    plain = _copy(OURS[language], str(folder / "Tsukikage - 04 [Kiriya].srt"))
    assert sources.subtitles_for_video(video, language) == [plain]
    ours = _copy(OURS[language], str(folder / f"Tsukikage - 04.{OUR_TAG[language]}.srt"))
    got = sources.subtitles_for_video(video, language)
    assert english not in got and got[0] == ours


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_chosen_videos_subtitle_in_the_other_library_language_is_never_offered(language, tmp_path):
    """The Chinese dialogue beside a video in a Japanese library (and the Japanese in a Chinese one), untagged: the
    rule reads it, not its name."""
    other = "zh" if language == "ja" else "ja"
    folder = tmp_path / "Shows"
    video = _video(str(folder / "Episode 05.mkv"))
    _copy(OURS[other], str(folder / "Episode 05.srt"))
    assert sources.subtitles_for_video(video, language) == []

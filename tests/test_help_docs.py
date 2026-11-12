"""Surasura's help for the learner's AI (`app/help_docs.py`): the user docs that ship, as a short list of topics, one
section at a time, and a search over them — made from this checkout, or read from the index a built program carries.

What a wrong answer would cost: an AI that reads the whole manual for one question (the list of topics long, a
section the size of a document); an answer from the wrong version's docs; a question in Japanese or Chinese that
finds nothing; a topic two places share answered from the wrong one; or the help naming anything that isn't a user's
doc. The real docs of this checkout; made-up docs only for the shapes the real ones don't have.
"""
import json
import os

import pytest

import package_app
from app import __version__, help_docs, path_utils
from app.qt import help_words


def _full(root=help_docs.ROOT):
    """The index a built program carries: the docs and the window's own words (`package_app.write_help`)."""
    return help_docs.build(root, window=help_words.topics())


def _forget():
    for fn in (help_docs.index, help_docs._search_table):
        getattr(fn, "cache_clear", lambda: None)()


@pytest.fixture(autouse=True)
def _fresh_index():
    _forget()
    yield
    _forget()


@pytest.fixture
def built(monkeypatch):
    """The help read as a built program reads it: the docs and the window's own words."""
    full = _full()
    monkeypatch.setattr(help_docs, "index", lambda: full)
    return full


def never_public():
    """The words no public text may say, kept outside the public repo (None there: the check is skipped)."""
    path = os.path.join(help_docs.ROOT, "docs", "agent instructions", "never-public.txt")
    try:
        with open(path, encoding="utf-8") as f:
            return [w.strip().casefold() for w in f if w.strip() and not w.startswith("#")]
    except OSError:
        return None


def _write(root, rel, text, newline="\n"):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(text)


def _titles(index):
    return [t["title"] for t in index["topics"]]


# --- made from the real docs ------------------------------------------------------------------------------------- #
def test_the_index_is_this_versions_short_list_of_topics_and_groups(built):
    idx = built
    assert idx["version"] == __version__ and idx["format"] == help_docs.FORMAT
    titles = _titles(idx)
    for title in ("Get started", "Known limits", "The guide", "Questions", "How parsing works", "Settings",
                  "In the window", "Updating Surasura"):
        assert title in titles
    assert not {"Q&A / FAQ", "Motivation", "Credits"} & set(titles)    # a pointer, or no help to anyone
    text = help_docs.topics_text()
    # the AI's first read is short: one line a topic, the groups folded (a few hundred tokens at most)
    assert len(text) < 1200 and len(text.splitlines()) == len(titles) + 1
    assert f"Questions {help_docs.MORE} " in text


def test_every_title_is_unique_and_a_shared_one_names_its_group():
    idx = _full()
    seen = [help_docs._key(t["title"]) for g in idx["topics"] for t in [g] + list(g.get("topics") or ())]
    assert len(seen) == len(set(seen))
    cards = next(t for t in idx["topics"] if t["title"] == "In the window")
    # "Level" is a Settings section and a help card: the second says where it is from
    assert "Level (In the window)" in [t["title"] for t in cards["topics"]]


def test_the_faq_is_one_topic_a_question_under_its_heading():
    faq = next(t for t in _full()["topics"] if t["title"] == "Questions")
    online = next(t for t in faq["topics"] if t["title"].startswith("Does Surasura go online?"))
    assert online["under"] == "Core Concepts" and "Send report" in online["text"]
    # an answer that starts in bold (Settings › Export …) is the answer, never a question of its own
    assert not any(t["title"].startswith("Settings › Export") for t in faq["topics"])
    assert all(t["title"].endswith("?") for t in faq["topics"])


def test_settings_and_the_help_cards_say_what_the_window_says():
    from app.qt import settings_catalog, strings
    idx = _full()
    settings = next(t for t in idx["topics"] if t["title"] == "Settings")
    names = [t["title"].removesuffix(" (Settings)") for t in settings["topics"]]   # (New arrivals: the guide's too)
    assert names == [s.name for s in settings_catalog.SECTIONS if any(
        r.label and (r.help or r.tip) for r in settings_catalog.rows(s.id))]
    anki = next(t for t in settings["topics"] if t["title"] == "Anki & mining")
    assert "- Connection: Through the free AnkiConnect add-on" in anki["text"]
    assert "{" not in anki["text"]                                       # a row's placeholders never shown raw
    cards = next(t for t in idx["topics"] if t["title"] == "In the window")
    making = next(t for t in cards["topics"] if t["title"] == strings.HELP_CARDS["cards"][0])
    assert strings.HELP_ALSO["cards"] in making["text"]


def test_the_newest_release_notes_only_and_never_their_download_block():
    idx = _full()
    notes = [t for t in idx["topics"] if t["title"].startswith("What's new in ")]
    versions = sorted((f for f in os.listdir(os.path.join(help_docs.ROOT, "docs", "releases"))
                       if help_docs._NOTES.match(f)),
                      key=lambda f: tuple(int(p) for p in help_docs._NOTES.match(f).group(1).split(".")))
    newest = [help_docs._NOTES.match(f).group(1) for f in reversed(versions)][:help_docs.NOTES_KEPT]
    assert [t["title"] for t in notes] == [f"What's new in {v}" for v in newest]
    assert __version__ in newest[0]
    for group in notes:
        assert not any(t["title"].startswith("Download") for t in group["topics"])


def test_a_section_is_its_words_and_where_it_sits_a_group_its_topics(built):
    text = help_docs.topic_text("Known limits")
    assert text.startswith("Known limits\n") and "Anki must be open" in text
    online = help_docs.topic_text("Does Surasura go online")                 # a title's start
    assert online.startswith("Questions › Core Concepts › Does Surasura go online?")
    assert help_docs.topic_text("  known LIMITS ") == text                   # any case, any spacing
    assert help_docs.topic_text("Settings › Level").startswith("Settings › Level\n")
    group = help_docs.topic_text("How parsing works")
    assert "Compound words are one word" in group and "Its " in group
    assert help_docs.topic_text("no such topic at all") is None
    assert help_docs.topic_text("") is None


@pytest.mark.parametrize("query, expect, within", [
    ("What leaves my computer? Does it go online?", "Does Surasura go online?", 1),
    ("上層部", "Compound words are one word", 2),       # a Japanese term, no tokenizer (and the page it reads beside)
    ("学习 學習", "Why does 学习 show up separately from 學習?", 1),                 # a Chinese one
    ("how do I report a bug", "Where do I report it?", 1),
])
def test_the_search_finds_the_section_a_question_needs(built, query, expect, within):
    hits = help_docs.search(query)
    assert any(expect in where for where, _t in hits[:within]), [w for w, _t in hits]
    assert len(hits) <= 3


def test_a_search_with_nothing_to_find_says_so(built):
    assert help_docs.search("") == [] and help_docs.search("the and of") == []      # only words that say nothing
    assert help_docs.search_text("zzqx flibbertigibbet") is None
    assert len(help_docs.search("anki", limit=99)) == help_docs.SEARCH_MAX


def test_a_long_hit_is_cut_and_says_where_the_rest_is(built):
    out = help_docs.search_text("What's new in 3.0.0 window library books cards journey", limit=5)
    for part in out.split("\n\n## "):
        assert len(part) < help_docs.TEXT_MAX + 200


def test_the_help_names_nothing_but_the_users_own_docs():
    # the help is a user's: never a private folder, a planning note or how Surasura is made
    words = never_public()
    if words is None:
        pytest.skip("the list of words no public text may say isn't in this checkout")
    text = json.dumps(_full(), ensure_ascii=False).casefold()
    for word in words:
        assert word not in text, word


# --- made from other docs: the shapes the real ones don't have --------------------------------------------------- #
def test_crlf_docs_code_blocks_numbering_emoji_pictures_and_links(tmp_path):
    root = str(tmp_path / "checkout")
    _write(root, "README.md", "<div>\n\n# Surasura\n\n![badge](x.svg)\n\n## 🛠️ 2. Get started\r\nPoint it at "
                              "[your folder](docs/Tutorial.md) and see [the site](https://surasura.dev).\r\n"
                              "```\r\n# not a heading\r\n```\r\n**Bold** and *soft*.\r\n\r\n\r\n\r\n## Known limits\r\n"
                              "- Windows only\r\n## Motivation\r\nWhy.\r\n", newline="")
    _write(root, "docs/Tutorial.md", "# Guide\n\nIntro.\n\n## 1. Setup (once)\n\n| A | B |\n\n### Deeper\n\nMore.\n")
    _write(root, "docs/Surasura FAQ.md", "# FAQ\n\nWelcome.\n\n### Core\n\n**Is it free?**\nYes, GPL.\n\n---\n")
    idx = help_docs.build(root)
    start = next(t for t in idx["topics"] if t["title"] == "Get started")
    assert "# not a heading" in start["text"]                    # a code block's # line stays text
    assert "your folder" in start["text"] and "docs/Tutorial.md" not in start["text"]
    assert "the site (https://surasura.dev)" in start["text"]
    assert "**" not in start["text"] and "soft" in start["text"] and "\n\n\n" not in start["text"]
    assert "Motivation" not in _titles(idx)
    guide = next(t for t in idx["topics"] if t["title"] == "The guide")
    assert guide["text"] == "Intro." and [t["title"] for t in guide["topics"]] == ["Setup (once)", "Deeper"]
    assert guide["topics"][1]["under"] == "Setup (once)"
    faq = next(t for t in idx["topics"] if t["title"] == "Questions")
    assert faq["topics"] == [{"title": "Is it free?", "text": "Yes, GPL.", "under": "Core"}]


def test_no_docs_at_all_still_answers_with_the_windows_own_words(tmp_path):
    idx = _full(str(tmp_path / "empty"))
    assert _titles(idx) == ["Settings", "In the window"]          # an empty doc is no topic
    assert package_app.write_help(str(tmp_path / "dist"), root=str(tmp_path / "empty")) is False   # never shipped so


# --- a built program reads the index made as it was packaged ----------------------------------------------------- #
def test_a_built_program_reads_its_packaged_index_never_the_docs(tmp_path, monkeypatch):
    dist = str(tmp_path / "dist")
    assert package_app.write_help(dist, root=help_docs.ROOT) is True
    path = os.path.join(dist, "_internal", help_docs.FILE)
    with open(path, encoding="utf-8") as f:
        packaged = json.load(f)
    assert packaged == json.loads(json.dumps(_full()))
    # a source checkout's own help is its docs alone (the window's words are read only at packaging time)
    assert [t for t in _titles(help_docs.build()) if t in ("Settings", "In the window")] == []
    # a built program: the index from its _internal, even with a different one on disk beside it
    packaged["topics"][0]["text"] = "As packaged."
    with open(path, "w", encoding="utf-8") as f:
        json.dump(packaged, f)
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(path_utils, "get_resource", lambda rel: os.path.join(dist, "_internal", rel))
    monkeypatch.setattr(help_docs, "build", lambda *a, **k: pytest.fail("a built program never reads the docs"))
    assert help_docs.index()["topics"][0]["text"] == "As packaged."
    # in the program's own part, so an update carries it with the program
    assert package_app.part_of("_internal/" + help_docs.FILE.replace(os.sep, "/"),
                               package_app.load_build_config()["parts"]) == "app"


def test_a_built_program_without_its_index_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(path_utils, "get_resource", lambda rel: str(tmp_path / "nowhere" / rel))
    with pytest.raises(OSError):
        help_docs.index()


def test_the_place_a_search_prints_opens_that_topic_and_a_group_opens_by_its_start(built):
    where, text = help_docs.search("Can my list update itself when I learn words in Anki?")[0]
    assert where.count(" › ") == 2                                   # group › heading › title
    assert help_docs.topic_text(where) == f"{where}\n{text}"
    assert help_docs.topic_text("parsing").startswith("How parsing works\n")


def test_one_japanese_or_chinese_character_is_a_question_too(built):
    hits = help_docs.search("層")                                     # 上層部 in the docs: one character still finds it
    assert hits and any("上層部" in text for _w, text in hits)

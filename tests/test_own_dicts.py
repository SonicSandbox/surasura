"""The learner's own Anki Miner dictionaries, read for the journey's *Yours* (J-DATA; SPEC §5.1, §5.2):
`app/own_dicts.py` — read-only, in chain order, first hit; a missing, locked or foreign index is no hit, quietly.

What a wrong answer would cost a learner: the page saying something other than what their card will say (the wrong
dictionary first, a disabled one read), a page that fails to build because Anki Miner changed its format, markup from
a dictionary running inside the page, or a write into Anki Miner's folder."""
import json
import os
import sqlite3

import pytest

from app import own_dicts

SCHEMA = ("CREATE TABLE entries (id INTEGER PRIMARY KEY, term TEXT NOT NULL, reading TEXT, content TEXT NOT NULL, "
          "tags TEXT NOT NULL DEFAULT '', rules TEXT NOT NULL DEFAULT '', score INTEGER DEFAULT 0, sequence INTEGER);"
          "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);")


def _dict(root, dict_id, title, rows):
    folder = os.path.join(root, "dicts", dict_id)
    os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(os.path.join(folder, "index.sqlite"))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO meta VALUES ('source_name', ?)", (title,))
    conn.executemany("INSERT INTO entries (term, reading, content, score, sequence) VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _chain(root, *entries):
    with open(os.path.join(root, "gui_config.json"), "w", encoding="utf-8") as f:
        json.dump({"dictionary_chain": [{"kind": "indexed", "dict_id": d, "enabled": on} for d, on in entries]}, f)


@pytest.fixture
def home(tmp_path):
    root = str(tmp_path / ".anki_miner")
    _dict(root, "daijirin", "大辞林", [
        ("冒険", "ぼうけん", '<li><div>危険を冒して行うこと。</div><div>成功の確かでないことをあえてすること。</div></li>', 5, 10),
        ("支度", "したく", "<ul><li>用意すること。準備。</li></ul>", 5, 11)])
    _dict(root, "jmdict-english", "JMdict", [
        ("冒険", "ぼうけん", "<li>adventure</li>", 1, 20), ("峠", "とうげ", "<li>mountain pass</li>", 1, 21)])
    own_dicts._MEMO.clear()
    return root


def test_the_first_dictionary_in_the_chain_with_a_hit_wins_as_main_definition(home):
    _chain(home, ("daijirin", True), ("jmdict-english", True))
    found = own_dicts.lookup([("冒険", "ボウケン"), ("峠", "トウゲ"), ("未知語", "ミチゴ")], root=home)
    assert found[("冒険", "ボウケン")] == ("大辞林", "危険を冒して行うこと。\n成功の確かでないことをあえてすること。")
    assert found[("峠", "トウゲ")] == ("JMdict", "mountain pass")
    assert ("未知語", "ミチゴ") not in found


def test_a_disabled_dictionary_is_never_read(home):
    _chain(home, ("daijirin", False), ("jmdict-english", True))
    assert own_dicts.lookup([("冒険", "ボウケン")], root=home) == {("冒険", "ボウケン"): ("JMdict", "adventure")}


def test_markup_comes_out_as_plain_text_never_html(home):
    _dict(home, "odd", "Odd", [("冒険", "ぼうけん", '<script>alert(1)</script><b onclick="x">冒</b>&amp;険', 9, 1)])
    _chain(home, ("odd", True))
    title, text = own_dicts.lookup([("冒険", "ボウケン")], root=home)[("冒険", "ボウケン")]
    assert "<" not in text and ">" not in text and text.endswith("冒&険")


def test_a_redirect_row_is_followed_one_hop(home):
    _dict(home, "jitendex", "Jitendex", [("気付く", "きづく", "⟶ 気づく", 9, -30), ("気づく", "きづく", "<li>to notice</li>", 1, 30)])
    _chain(home, ("jitendex", True))
    assert own_dicts.lookup([("気付く", "キヅク")], root=home)[("気付く", "キヅク")] == ("Jitendex", "to notice")


def test_without_anki_miner_or_with_a_foreign_index_nothing_is_found_quietly(home, tmp_path):
    assert own_dicts.lookup([("冒険", "ボウケン")], root=str(tmp_path / "nobody")) == {}
    folder = os.path.join(home, "dicts", "broken")
    os.makedirs(folder)
    with open(os.path.join(folder, "index.sqlite"), "wb") as f:
        f.write(b"not a database")
    _dict(home, "otherschema", "Other", [])
    conn = sqlite3.connect(os.path.join(home, "dicts", "otherschema", "index.sqlite"))
    conn.execute("DROP TABLE entries")
    conn.commit()
    conn.close()
    _chain(home, ("broken", True), ("otherschema", True), ("../escape", True), ("jmdict-english", True))
    assert own_dicts.lookup([("冒険", "ボウケン")], root=home) == {("冒険", "ボウケン"): ("JMdict", "adventure")}
    with open(os.path.join(home, "gui_config.json"), "w", encoding="utf-8") as f:
        f.write("{ not json")
    assert own_dicts.lookup([("冒険", "ボウケン")], root=home) == {}


def test_a_dictionary_whose_path_sqlite_cannot_take_is_no_hit_never_an_error(home, monkeypatch):
    # A relative home (ANKI_MINER_HOME set to "dicts") can't become a file: URI; the lookup must still answer.
    _chain(home, ("daijirin", True), ("jmdict-english", True))
    real = own_dicts._open
    monkeypatch.setattr(own_dicts, "_open", lambda path: real("relative/index.sqlite") if "daijirin" in path else real(path))
    assert own_dicts.lookup([("冒険", "ボウケン")], root=home) == {("冒険", "ボウケン"): ("JMdict", "adventure")}


def test_nothing_is_written_into_anki_miner_s_folder(home):
    _chain(home, ("daijirin", True))
    before = {os.path.join(d, f): os.stat(os.path.join(d, f)).st_mtime_ns for d, _s, fs in os.walk(home) for f in fs}
    own_dicts.lookup([("冒険", "ボウケン"), ("支度", "シタク")], root=home)
    after = {os.path.join(d, f): os.stat(os.path.join(d, f)).st_mtime_ns for d, _s, fs in os.walk(home) for f in fs}
    assert after == before                               # no journal, no wal, no file touched


def test_a_changed_dictionary_is_read_again(home):
    _chain(home, ("jmdict-english", True))
    assert own_dicts.lookup([("峠", "トウゲ")], root=home)
    conn = sqlite3.connect(os.path.join(home, "dicts", "jmdict-english", "index.sqlite"))
    conn.execute("UPDATE entries SET content = '<li>(mountain) pass; ridge</li>' WHERE term = '峠'")
    conn.commit()
    conn.close()
    os.utime(os.path.join(home, "dicts", "jmdict-english", "index.sqlite"), ns=(1, 1))
    assert own_dicts.lookup([("峠", "トウゲ")], root=home)[("峠", "トウゲ")][1] == "(mountain) pass; ridge"


def test_the_learner_s_kanjium_copy_is_read_as_it_is(home):
    folder = os.path.join(home, "pitch", "kanjium-pitch")
    os.makedirs(folder)
    with open(os.path.join(folder, "source.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write("一生懸命\tいっしょうけんめい\t5\n遠く\tとおく\t(副)0,(名)3\n")
    table = own_dicts.kanjium(home)
    assert table["一生懸命"] == {"いっしょうけんめい": "5"} and table["遠く"]["とおく"] == "(副)0,(名)3"
    assert own_dicts.kanjium(os.path.join(home, "none")) == {}

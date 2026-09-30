"""The names data build — scripts/build_name_data.py, run at build time only — and JMdict's kanji spellings it ships.

The build distils the dictionaries into three generated modules: the katakana headwords, JMnedict's person names and
JMdict's kanji spellings entry by entry (app/jmdict_data.py). The last one keeps a story's own kanji terms apart from
the words any dictionary lists (鄭寧 is Sōseki's 丁寧), and — kept by entry — says which dictionary word a spelling
belongs to. The dictionary below is real: entries quoted from JMdict (the EDRDG's Japanese-English dictionary, CC BY-SA
4.0), cut to what these tests need.
"""

import gzip
import importlib.util
import json
import os

import pytest

_JMDICT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE JMdict [
<!ELEMENT JMdict (entry*)>
<!ENTITY n "noun (common) (futsuumeishi)">
<!ENTITY v5u "Godan verb with 'u' ending">
<!ENTITY adv "adverb (fukushi)">
<!ENTITY rK "rarely used kanji form">
<!ENTITY sK "search-only kanji form">
]>
<!-- JMdict created: 2026-09-28 -->
<JMdict>
<entry><ent_seq>1378500</ent_seq><k_ele><keb>生き</keb></k_ele><k_ele><keb>活き</keb></k_ele><r_ele><reb>いき</reb></r_ele><sense><pos>&n;</pos><gloss>living</gloss></sense></entry>
<entry><ent_seq>1333530</ent_seq><k_ele><keb>集い</keb></k_ele><r_ele><reb>つどい</reb></r_ele><sense><pos>&n;</pos><gloss>meeting</gloss></sense></entry>
<entry><ent_seq>1333540</ent_seq><k_ele><keb>集う</keb></k_ele><r_ele><reb>つどう</reb></r_ele><sense><pos>&v5u;</pos><gloss>to meet</gloss></sense></entry>
<entry><ent_seq>1427360</ent_seq><k_ele><keb>丁寧</keb></k_ele><k_ele><keb>叮嚀</keb><ke_inf>&rK;</ke_inf></k_ele><k_ele><keb>鄭寧</keb><ke_inf>&sK;</ke_inf></k_ele><r_ele><reb>ていねい</reb></r_ele><sense><pos>&n;</pos><gloss>polite</gloss></sense></entry>
<entry><ent_seq>2085080</ent_seq><r_ele><reb>ああ</reb></r_ele><sense><pos>&adv;</pos><gloss>like that</gloss></sense></entry>
</JMdict>
"""


@pytest.fixture(scope="module")
def bnd():
    """scripts/build_name_data.py — it runs at build time and never ships, so it is no package."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "build_name_data.py")
    spec = importlib.util.spec_from_file_location("build_name_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lists(folder):
    """The build's inputs, in miniature: two frequency lists, JMnedict's name wordsets and JMdict."""
    (folder / "anki_miner_wordsets").mkdir(parents=True)
    (folder / "JPDB 2024.json").write_text(json.dumps(["トートバッグ", ["冬月", "トウゲツ"]], ensure_ascii=False),
                                           encoding="utf-8")
    (folder / "Jiten.json").write_text(json.dumps(["ドキドキ"], ensure_ascii=False), encoding="utf-8")
    (folder / "anki_miner_wordsets" / "surnames.txt").write_text("司波\n冬月\n", encoding="utf-8")
    (folder / "anki_miner_wordsets" / "given-names.txt").write_text("奏汰\n", encoding="utf-8")
    with gzip.open(folder / "JMdict_e.gz", "wt", encoding="utf-8") as handle:
        handle.write(_JMDICT)
    return folder


def test_jmdict_kanji_forms_keep_every_kanji_spelling_entry_by_entry(bnd, tmp_path):
    """One line per entry that has a kanji form, its forms in JMdict's order — search-only and rare forms too (鄭寧 is
    a search-only form of 丁寧) — and the lines sorted; an entry written in kana alone has none."""
    lines, created, forms = bnd.jmdict_kanji_forms(str(_lists(tmp_path)))
    assert lines == ["丁寧\t叮嚀\t鄭寧", "生き\t活き", "集い", "集う"]
    assert created == "2026-09-28" and forms == 7


def test_a_missing_jmdict_is_an_error_never_an_empty_table(bnd, tmp_path):
    """An empty list would pass every spelling as no dictionary word: the build stops instead."""
    with pytest.raises(FileNotFoundError):
        bnd.jmdict_kanji_forms(str(tmp_path))


def test_the_build_writes_the_tables_and_keeps_one_whose_inputs_did_not_change(bnd, tmp_path):
    """All three modules are written and read back; built again from the same inputs, a table that differs only in its
    Revision line is kept as it is (its file untouched), and one whose inputs changed is written."""
    lists = str(_lists(tmp_path / "lists"))
    out = {name: str(tmp_path / f"{name}.py") for name in ("name_data", "katakana_data", "jmdict_data")}
    bnd.main(lists, out["name_data"], out["katakana_data"], out["jmdict_data"])

    def load(name):
        spec = importlib.util.spec_from_file_location(name, out[name])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    jmdict = load("jmdict_data")
    assert jmdict.kanji_forms().split("\n") == ["丁寧\t叮嚀\t鄭寧", "生き\t活き", "集い", "集う"]
    assert jmdict.CREATED == "2026-09-28" and "CC BY-SA 4.0" in jmdict.__doc__
    assert load("name_data").surnames() == ["司波"], "冬月 is a word too (JPDB 2024)"
    assert "ドキドキ" in load("katakana_data").katakana_headwords()

    with open(out["jmdict_data"], encoding="utf-8") as handle:
        text = handle.read()
    stale = text.replace(f'REVISION = "{jmdict.REVISION}"', 'REVISION = "2000-01-01"')
    with open(out["jmdict_data"], "w", encoding="utf-8") as handle:
        handle.write(stale)
    assert bnd._write(out["jmdict_data"], text) is False, "only the Revision line differs: kept"
    with open(out["jmdict_data"], encoding="utf-8") as handle:
        assert handle.read() == stale
    assert bnd._write(out["jmdict_data"], text.replace("集う", "集る")) is True, "the table changed: written"

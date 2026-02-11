import fugashi
import json
import sys
import re

def is_pure_katakana(text):
    return bool(re.fullmatch(r'[\u30A0-\u30FF]+', text))

def has_kanji(text):
    return bool(re.search(r'[\u4E00-\u9FAF]', text))

def test_katakana_mapping():
    try:
        tagger = fugashi.Tagger()
    except Exception as e:
        with open("repro_output.txt", "w", encoding="utf-8") as f:
            f.write(f"Error creating tagger: {e}\n")
        return

    test_words = ["カセキ", "マイク", "タバコ", "メガネ", "サクラ", "スモモ"]
    output = []
    
    for word in test_words:
        output.append(f"Word: {word}")
        for w in tagger(word):
            output.append(f"  Surface: {w.surface}")
            output.append(f"  Lemma: {w.feature.lemma}")
            output.append(f"  POS1: {w.feature.pos1}")
            output.append(f"  Kana: {w.feature.kana}")
            output.append(f"  IsPureKatakana(Surface): {is_pure_katakana(w.surface)}")
            output.append(f"  HasKanji(Lemma): {has_kanji(w.feature.lemma if w.feature.lemma else '')}")
        output.append("-" * 20)

    with open("repro_output.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(output))

if __name__ == "__main__":
    test_katakana_mapping()

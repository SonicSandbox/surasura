"""The report's per-file view: each file's words in the list's own order, the files in the order the journey meets
them — also when two files share a name (01.srt in two series), whose words the view shows under that name together.
The rows are split by file once for the whole list (a table per file cost about a second on a large library)."""

import json
import math
import re
from unittest.mock import patch

import pandas as pd


def _render(tmp_path, rows):
    results = tmp_path / "results"
    results.mkdir()
    pd.DataFrame([{"Word": "冒険", "Reading": "ボウケン", "Tier": "Outside", "Score": 10, "Occurrences": 4,
                   "Count (High)": 1, "Count (Low)": 1, "Count (Goal)": 2, "Sources": "01.srt",
                   "Context 1": "冒険に出かけた。"}]
                 ).to_csv(results / "priority_learning_list.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"Sequence": seq, "Source File": name, "Word": word, "Reading": reading, "Tier": "Outside",
                   "Score": 10, "Occurrences (Global)": 2, "Occurrences (File)": 1, "Count (High)": 0,
                   "Count (Low)": 0, "Count (Goal)": 2, "Context 1": context}
                  for seq, name, word, reading, context in rows]
                 ).to_csv(results / "progressive_learning_list.csv", index=False, encoding="utf-8-sig")
    from app import static_html_generator as gen
    out = results / "reading_list_static.html"
    with patch.object(gen, "RESULTS_DIR", str(results)), \
         patch.object(gen, "PRIORITY_CSV", str(results / "priority_learning_list.csv")), \
         patch.object(gen, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")), \
         patch.object(gen, "OUTPUT_FILE", str(out)):
        gen.generate_static_html(theme="default", open_browser=False)
    payload = re.search(r"let globalData = (\{.*?\});\n", out.read_text(encoding="utf-8"), re.S)
    view = {}
    for item in json.loads(payload.group(1))["progressive"]:
        keys, table = item["words"]["keys"], item["words"]["rows"]
        view[item["filename"]] = [dict(zip(keys, row)) for row in table]
    return view


def test_each_file_keeps_its_words_in_list_order_and_a_shared_name_is_one_group(tmp_path):
    view = _render(tmp_path, [
        (1, "01.srt", "冒険", "ボウケン", "冒険に出かけた。"),
        (1, "01.srt", "図書館", "トショカン", "図書館で本を読んだ。"),
        (2, "02.srt", "約束", "ヤクソク", "約束を守った。"),
        (3, "01.srt", "勇気", "ユウキ", ""),                      # another series' 01.srt; no example
        (4, "吾輩は猫である.txt", "吾輩", "ワガハイ", "吾輩は猫である。"),
    ])
    assert list(view) == ["01.srt", "02.srt", "吾輩は猫である.txt"]
    assert [w["Word"] for w in view["01.srt"]] == ["冒険", "図書館", "勇気"]
    assert [w["Word"] for w in view["02.srt"]] == ["約束"]
    first = view["01.srt"][0]
    assert (first["Reading"], first["Sequence"], first["Occurrences (File)"], first["Context 1"]) == \
        ("ボウケン", 1, 1, "冒険に出かけた。")
    assert math.isnan(view["01.srt"][2]["Context 1"])         # an empty cell: NaN, as the report always had it

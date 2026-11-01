"""Words learners reported — problems (and non-problems) found in other people's libraries, kept so the answer holds.

Each case names the report it came from. A report whose cause was outside Surasura (another tool) still gets a LOCK
here, so the part that IS Surasura's stays right. Group owned by this file: RPT (docs/agent instructions/
Parsing_Suite.md, "Ids")."""
from tests.parsing.case import Case

_REPORT = "doc: a learner's report on their own library, 2026-09-30"

CASES = [
    # --- 出来損ない: the list showed 損ない, and a 出来損ない card was placed as a phrase ---------------------------- #
    Case(id="JA-RPT-001", lang="ja", layer="tokens_ja", category="F",
         text="あの出来損ないの人間兵器のために。", span="出来損ない",
         expect={"units": "出来損ない[*]"},
         basis="出来損ない 'a failure, a botch, a good-for-nothing' is one word (JMdict 出来損ない; JPDB 2024 and Jiten "
               "both list 出来損ない デキソコナイ). In a sentence the tagger reads it as two nouns, 出来 (デキ) + 損ない "
               "(ソコナイ), so the list offers 損ない — a different word ('harm, a failing') — and this sentence is "
               "given as its example. The compound table misses it: its builder reads each headword ALONE, where "
               "出来損ない comes out as two verbs (出来る + 損なう), and a verb + 〜損なう is left apart on purpose "
               "(言い損なう, 見損なう: a regular 'fail to' pattern) — so the in-sentence noun reading is never keyed.",
         status="LOCK", decision="IN-TEXT-COMPOUNDS", source=_REPORT,
         refs=("debug/parsing_fixes_run/AFTER_LANDING.md (the 出来損ない report)",
               "debug/parsing_fixes_run/in_text_compounds/REPORT.md"),
         note="Promoted LOCK 2026-09-30: fixed by the in-text compound build (lane IT) — the build also reads its "
              "reference text, where 出来損ない is 出来 + 損ない, and keys the word as the text writes it."),
    Case(id="JA-RPT-002", lang="ja", layer="tokens_ja", category="F",
         text="出来損ない", span="出来損ない",
         expect={"units": "出来損ない[*]"},
         basis="The same word written alone, as a card holds it: the tagger reads 出来る + 損なう (two verbs), so the "
               "card is a phrase to Junban and lands on no row. One word, as in a sentence.",
         status="LOCK", decision="IN-TEXT-COMPOUNDS", source=_REPORT,
         note="Promoted LOCK 2026-09-30: fixed by the in-text compound build (lane IT) — JMdict lists 出来損ない as a "
              "noun and the text writes it with a verb's stem, so it carries the mark 8 and a line that is the word "
              "alone (出来る + 損なう: a run ending in a stem, nothing after it) joins as the noun."),
    Case(id="JA-RPT-003", lang="ja", layer="tokens_ja", category="H",
         text="健康を損なう。", span="損なう",
         expect={"units": "損なう[損なう]"},
         basis="The verb 損なう 'to harm' on its own is its own word, and stays one: a fix for 出来損ない must not glue "
               "it to anything.",
         status="LOCK", source="constructed"),
    Case(id="JA-RPT-101", lang="ja", layer="card_key", category="K",
         text="出来損ない", span="出来損ない",
         expect={"key": ""},
         basis="A 出来損ない card must never land on the 損ない row — a different word; sorting the card there would "
               "teach 'harm' for 'good-for-nothing'. The fix is 出来損ない as a row of its own (JA-RPT-001).",
         status="LOCK", source=_REPORT, ctx={"list": ["損ない"]}),
    Case(id="JA-RPT-102", lang="ja", layer="card_key", category="K",
         text="出来損ない", span="出来損ない",
         expect={"key": "出来損ない", "via": "exact"},
         basis="Once the list holds 出来損ない, the card lands on it by its spelling.",
         status="LOCK", source=_REPORT, ctx={"list": ["出来損ない"]}),

    # --- もったいぶる: reported as unmatched; the cause was another tool — Surasura's part stays right ------------ #
    Case(id="JA-RPT-004", lang="ja", layer="tokens_ja", category="E",
         text="そんなにもったいぶるなよ。", span="もったいぶる",
         expect={"units": "もったいぶる[もったいぶる]"},
         basis="もったいぶる 'to put on airs' is one word (もったい + the suffix ぶる joined), in 2.3.1 and since.",
         status="LOCK", source=_REPORT),
    Case(id="JA-RPT-103", lang="ja", layer="card_key", category="K",
         text="もったいぶる", span="もったいぶる",
         expect={"key": "もったいぶる", "via": "exact"},
         basis="A card spelled exactly もったいぶる lands on its row by its spelling. (The report's miss was another "
               "tool's, 2026-09-30.)",
         status="LOCK", source=_REPORT, ctx={"list": ["もったいぶる"]}),
]

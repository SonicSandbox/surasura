"""The set phrases on the list — the decision behind them, merged into the register by decisions.py.

Decided 2026-09-30: PHRASE-ROWS (Phrase_Bundle_Spec.md §0, every lean taken, with the user's adjustments).
"""
from tests.parsing.decisions import Decision

ALL = (
    Decision(
        "PHRASE-ROWS", "2026-09-30",
        "JMdict's set phrases (気がする, 腑に落ちる, もしかしたら) as rows of their own on the list: which phrases, when "
        "is one ready, where does it sit, what do its words keep, and what does it do to other words' sentences?",
        "Rows (Settings 'Idioms and set phrases on your list', on; additive — the tokenizer still never joins one, "
        "JT-EXPRESSIONS). A phrase is a JMdict headword (no title; a kanji spelling only where the tokenizer reads it "
        "as JMdict does — its reading said as the words read, or read alone giving them: 彼の方 あのかた is no 彼 'he' "
        "+ の + 方, added 2026-10-01) read alone as 2–5 words built like a phrase (two "
        "real words, or one + a light verb or adjective; never one word + grammar, a card read as one word + an "
        "ending — どうしよう, なんで stay their words — or a word said twice), a unit in general text (JPDB 2024, else "
        "Jiten, ranks it at most 8x rarer than its count in the shared set's text would), found by its lemmas, the "
        "longest first, never across a mark the tokenizer dropped — one that ends in grammar in a form of its own "
        "(もしかしたら's たら, そういうことなら's なら) only in that form, and one JMdict classes only as a pre-noun "
        "adjectival (adj-pn: ああいう, 罪なき) or sends to one (そういった, 'see そういう') only uninflected before a "
        "word of its own — and one it says is usually written in kana (そういった, どういう) only as written so. A "
        "row at a word's own "
        "cut-off unless known or "
        "ignored as a whole, or its lemmas joined are a word the library holds. Ready once every real word is known — "
        "grammar, light words, one-character words and a word JPDB ranks rarer alone than the phrase (it lives only "
        "inside it) never count; ready with every real word known -> half score; waiting -> it sorts after its word, "
        "and its own sentences count that word. A word living only inside its phrase gives the phrase its uses there. "
        "Other words' sentences: a new phrase never counts as an unknown (B4 soft): it only puts a sentence after "
        "cleaner ones among a word's examples. Junban places a phrase card on its row by its lemmas; the Rarity slider "
        "and automatic rarity count phrase rows.",
        "Phrase_Bundle_Spec.md §0 answered 2026-09-30 — every lean (B1–B8), B3 (掛け替え lives on in its row "
        "掛け替えのない), B4 in its soft form (the full form measured on the built rows — 11,742 of the user's i+1 sentences would become i+2, 44 words lose every i+1 sentence — and declined by the user 2026-09-30: \"All your leans are good\"), B8 the Credits hover. "
        "The words a phrase holds are judged Japanese-wide (JMdict, JPDB 2024 / Jiten, general text), never from the "
        "user's library; the library decides only what is frequent enough. The pre-noun rule's kana half "
        "(Parsing_Future_Work.md #29) is the user's yes to its optional patch.",
        "A word JPDB ranks just below its phrase is learned through it even where met alone (傾ける in 耳を傾ける, 加減 "
        "in いい加減); a phrase whose words are all known sits lower though it means more than its words (気がする); a "
        "phrase general text meets far more often than the lists rank it is dropped (いいと思う) while a "
        "conversational phrase rare in formal text passes (そうやって); a near-duplicate stays a second row "
        "(あっという間 / あっという間に, 腑に落ちる / 腑に落ちない); そういった 'like that' still counts 'said so' "
        "written in kana before a noun or の (そういったのは — a relative clause), and a genuine one written with the "
        "verb's kanji is missed (どう言う意味, ああ言う連中); a phrase card's sentence with a new phrase in it "
        "still reads as i+1 for the word. The matcher never asks a word's reading: がたが来る 'get rickety' still "
        "counts あの方が来られた 'that person came' (JA-PHR-042) — a reading check refused about 1,450 right matches "
        "on the user's library (その後 あと / ご, 溜め息を吐く つく / はく: the tagger says such words differently from "
        "sentence to sentence); the user, 2026-10-01: leave it, log it (Parsing_Future_Work.md #63). The reading "
        "test on the build also drops a real idiom the tokenizer cuts into other words (同病相憐れむ → 同 + 病相 + "
        "憐れむ; 満を持して; the 性質 spelling of 性質の悪い — the idiom keeps its row as たちの悪い): on the user's "
        "library 7 idioms lose their row (11 sentences, none on the list) and 5 a spelling (9 sentences), while 18 "
        "rows that were other words go (~165 sentences: 口の端 'gossip' for every corner of a mouth, on the list; 其者 "
        "for その者; 彼の方 for 彼のほう 'his side') — the user, 2026-10-01: 'go build it … mark down idioms that we "
        "lose' (phrase_readings/LOST_IDIOMS.md; winning them back: Parsing_Future_Work.md #64).",
        "decided", ("Phrase_Bundle_Spec.md §0, §6, §14", "debug/phrase_data.md")),
)

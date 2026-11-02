"""The set phrases on the list (PHR) — what is a phrase, where one is found, and when it is ready (PHRASE-ROWS;
Phrase_Bundle_Spec.md §10). Layer: evaluators_ja_phrases.py's `phrases` — the shipped phrase data and the app's own
matcher on the case's text.

Each token-layer LIMIT under JT-EXPRESSIONS (the expression stays in pieces in the tokenizer: JA-CMP-058 to 063,
JA-AFX-277, JA-SND-040, JA-VRB-016) has its partner here, with the same text: the phrase is found and can be a row of
its own. The rest are the spec's matcher, rule, readiness and score cases, on made-up sentences.
"""
from tests.parsing.case import Case

_SPEC = "Phrase_Bundle_Spec.md §0, §10"
_RULE = "Phrase_Bundle_Spec.md §0 Q5, §6.1"
_READY = "Phrase_Bundle_Spec.md §0 Q1-Q3, §6.6"
_EXAMPLES = "debug/parsing_fixes_run/phrase_readings/REPORT.md (the user's card examples, 2026-10-01: A)"


def _found(id, text, span, name, partner, basis):
    return Case(id=id, lang="ja", layer="phrases", category="F", text=text, span=span, expect={"found": [name]},
                basis=basis, status="LOCK", decision="PHRASE-ROWS", source="library: the token case's own line",
                refs=(_SPEC, f"tokens partner {partner}"))


CASES = [
    # --- the token layer's expressions, found as phrases (partners) ---------------------------------------------- #
    _found("JA-PHR-001", "え…無理無理気持ち悪い。", "気持ち悪い", "気持ち悪い", "JA-CMP-058",
           "気持ち悪い 'gross' (JMdict, an adjective there): a noun + an adjective, two real words — a phrase row."),
    _found("JA-PHR-002", "申し訳ないけどほら。", "申し訳ない", "申し訳ない", "JA-CMP-059",
           "申し訳ない 'I'm sorry': 申し訳 + the light ない — a phrase row."),
    _found("JA-PHR-003", "ないのはしょうがない。", "しょうがない", "仕様が無い", "JA-CMP-060",
           "しょうがない 'it can't be helped': read 仕様 + が + ない — the phrase is found by those lemmas."),
    Case(id="JA-PHR-005", lang="ja", layer="phrases", category="F", text="いや～なんだかんだ言ってさ。",
         span="なんだかんだ", expect={"found": ["なんだかんだ"]},
         basis="なんだかんだ 'one thing or another' (JMdict 何だかんだ): 何 + だ + かん + だ, two real words. Here the "
               "tagger reads いや～な as 嫌 + な (the stretch), and the phrase's words are not there to find.",
         status="TARGET", source="library: the token case's own line", refs=(_SPEC, "tokens partner JA-CMP-062"),
         note="The matcher is right; the line's tokens are not (the stretched いや～ takes な). A clean sentence: "
              "JA-PHR-027."),
    Case(id="JA-PHR-027", lang="ja", layer="phrases", category="F", text="なんだかんだ言って、楽しかった。",
         span="なんだかんだ", expect={"found": ["なんだかんだ"]},
         basis="なんだかんだ 'one thing or another' (JMdict 何だかんだ): found as 何 + だ + かん + だ.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    _found("JA-PHR-006", "「それは間違いない。", "間違いない", "間違いない", "JA-CMP-063",
           "間違いない 'certain': 間違い + the light ない."),
    _found("JA-PHR-007", "お気に入りの服。", "お気に入り", "お気に入り", "JA-AFX-277",
           "お気に入り 'favourite' (a JMdict noun built from a phrase): お + 気 + に + 入る."),
    _found("JA-PHR-008", "あっという間にできていく。", "あっという間", "あっという間に", "JA-SND-040",
           "あっという間 / あっという間に: both JMdict phrases; the longer is the one met here (longest first)."),
    _found("JA-PHR-009", "ドエムの心にあった驚愕は、知らぬ間に燃え上がるような嫉妬に塗りつぶされた。", "知らぬ間に",
           "知らぬ間に", "JA-VRB-016", "知らぬ間に 'before one knows it': 知る + ぬ + 間 + に."),
    Case(id="JA-PHR-004", lang="ja", layer="phrases", category="F", text="なんで今日に限って。", span="なんで",
         expect={"found": []},
         basis="なんで 'why' is a JMdict adverb (何で): one word since 2026-10-01 (the tokenizer joins the words "
               "it cuts at their particles), so no phrase — the list counts なんで itself.",
         status="LOCK", decision="CUT-WORD-PARTICLES", source="library: the token case's own line",
         refs=(_RULE, "tokens partner JA-CMP-061")),

    # --- the matcher ------------------------------------------------------------------------------------------------ #
    Case(id="JA-PHR-010", lang="ja", layer="phrases", category="F", text="やっと気がついた。", span="気がつい",
         expect={"found": ["気が付く"]},
         basis="気がついた is 気がつく in the past: a phrase is found by its lemmas (気 + が + 付く), in any form.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    Case(id="JA-PHR-011", lang="ja", layer="phrases", category="F", text="気が、付くと朝だった。", span="",
         expect={"not_found": ["気が付く"]},
         basis="気が、付く: the comma the token store drops separates the words — they stand side by side as lemmas, "
               "never as one run of the sentence: no phrase there.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC, "JA-JBN-069")),
    Case(id="JA-PHR-012", lang="ja", layer="phrases", category="F", text="その説明はどうも腑に落ちない。", span="腑に落ち",
         expect={"found": ["腑に落ちない"]},
         basis="腑に落ちない is a JMdict expression of its own and a unit in general text (JPDB #177,991 against its "
               "count there): a near-duplicate of 腑に落ちる, kept as its own row (the user: near-duplicates stay "
               "two rows).",
         status="LOCK", decision="PHRASE-ROWS", refs=(_RULE,)),
    Case(id="JA-PHR-013", lang="ja", layer="phrases", category="F", text="夏休みはあっという間に終わった。", span="",
         expect={"found": ["あっという間に"], "not_found": ["あっという間"]},
         basis="Longest first, no overlaps: あっという間に is met, never also the あっという間 inside it.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    Case(id="JA-PHR-028", lang="ja", layer="phrases", category="F", text="なるほど、そういうことだ。", span="",
         expect={"not_found": ["そういうことなら"]},
         basis="そういうことなら 'if that's the case' ends in なら, a form of its own (だ's): そういうことだ 'that's how "
               "it is' holds the same lemmas but is another expression — no そういうことなら there.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    Case(id="JA-PHR-029", lang="ja", layer="phrases", category="F", text="ここまで来たら、もう戻れない。",
         span="ここまで来たら", expect={"found": ["ここまで来たら"]},
         basis="ここまで来たら 'now that it has come this far': found in its own form, たら.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    Case(id="JA-PHR-030", lang="ja", layer="phrases", category="F", text="やっとここまで来たんだ。", span="",
         expect={"not_found": ["ここまで来たら"]},
         basis="ここまで来た is the past, not ここまで来たら's conditional: no phrase there.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    Case(id="JA-PHR-031", lang="ja", layer="phrases", category="F", text="子供たちは目を輝かせて話を聞いた。",
         span="目を輝かせ", expect={"found": ["目を輝かせる"]},
         basis="目を輝かせる 'eyes light up' ends in its dictionary form (せる): found in any form, here 目を輝かせて.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    Case(id="JA-PHR-032", lang="ja", layer="phrases", category="F", text="あの子はああいう人が好きだ。", span="ああいう",
         expect={"found": ["ああいう"]},
         basis="ああいう 'that sort of' is what JMdict classes only as a pre-noun adjectival (exp, adj-pn): found "
               "uninflected, straight before a word of its own (人).",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    Case(id="JA-PHR-033", lang="ja", layer="phrases", category="F", text="先生は昨日ああ言っていた。", span="",
         expect={"not_found": ["ああいう"]},
         basis="ああ言って is the words 'say so', inflected — a pre-noun adjectival never is: no ああいう there.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    Case(id="JA-PHR-034", lang="ja", layer="phrases", category="F", text="そういった問題はよくある。", span="そういった",
         expect={"found": ["そういった"]},
         basis="そういった 'such' (JMdict: an expression it sends to そういう, a pre-noun adjectival) before a noun.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    Case(id="JA-PHR-035", lang="ja", layer="phrases", category="F", text="彼は確かにそう言った。", span="",
         expect={"not_found": ["そういった", "そう言った"]},
         basis="そう言った。 'he said so' ends the sentence: the words, never そういった 'such'.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    Case(id="JA-PHR-036", lang="ja", layer="phrases", category="F", text="君がそう言ったのは覚えている。", span="",
         expect={"not_found": ["そういった", "そう言った"]},
         basis="'that you said so' — a relative clause before の, written with the verb's kanji (言), as most of these "
               "are. JMdict marks そういった usually written in kana, so it is found only so: here, the words.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    Case(id="JA-PHR-037", lang="ja", layer="phrases", category="F", text="それはどう言う意味ですか。", span="どう言う",
         expect={"found": ["どういう"]},
         basis="どう言う意味 'what do you mean' is どういう 'what kind of' written with the verb's kanji. JMdict marks "
               "どういう usually written in kana, and the rule reads a kanji-written one as the words 'say': it misses "
               "this one — the price of そう言ったのは (JA-PHR-036).",
         status="LIMIT", decision="PHRASE-ROWS", refs=(_SPEC, "JA-PHR-036")),
    Case(id="JA-PHR-038", lang="ja", layer="phrases", category="F", text="君がそういったのは覚えている。", span="",
         expect={"not_found": ["そういった", "そう言った"]},
         basis="'that you said so' written in kana: the relative clause before の reads as a pre-noun place, and the "
               "app counts it as そういった 'such' (rare: in kana it is nearly always 'such').",
         status="LIMIT", decision="PHRASE-ROWS", refs=(_SPEC, "JA-PHR-036")),

    # --- the rule --------------------------------------------------------------------------------------------------- #
    Case(id="JA-PHR-014", lang="ja", layer="phrases", category="F", text="それはいいと思う。", span="",
         expect={"not_found": ["良いと思う", "いいと思う", "其れは", "それは"]},
         basis="それは is one word + grammar; いいと思う is the words side by side — general text meets it far more "
               "often than JPDB ranks it (the unit test drops it).",
         status="LOCK", decision="PHRASE-ROWS", refs=(_RULE,)),
    Case(id="JA-PHR-015", lang="ja", layer="phrases", category="F", text="うんうん、そうだね。", span="",
         expect={"not_found": ["うんうん"]}, basis="One word said twice is no phrase.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_RULE,)),
    Case(id="JA-PHR-016", lang="ja", layer="phrases", category="F", text="どうしよう、遅れちゃう。", span="どうしよう",
         expect={"found": ["どうしよう"]},
         basis="どうしよう 'what shall I do' is a JMdict expression, but a card the app reads as one word + an ending "
               "(どう + する, as 努力する is 努力) is that word: no phrase row, by the rule.",
         status="LIMIT", decision="PHRASE-ROWS", refs=(_RULE, "JA-JBN-068")),
    Case(id="JA-PHR-017", lang="ja", layer="phrases", category="F", text="彼らは来なかった。", span="",
         expect={"not_found": ["彼ら"]}, basis="彼ら is one word + a plural: the list counts 彼.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_RULE,)),
    Case(id="JA-PHR-018", lang="ja", layer="phrases", category="F", text="こと自体が問題だ。", span="",
         expect={"not_found": ["こと自体", "事自体"]},
         basis="こと自体 is a compound the tokenizer makes one word (with 'Phrases and titles as one word' on) — and a "
               "compound-table spelling is never a phrase row either way.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_RULE,)),

    # --- readiness, the score, the words that live only inside -------------------------------------------------- #
    Case(id="JA-PHR-019", lang="ja", layer="phrases", category="L", text="では本題に入ろう。", span="本題に入ろう",
         expect={"ready": False, "waits_for": ["本題"], "score": "full"}, ctx={"known": ["入る"]},
         basis="本題に入る waits for 本題 while 本題 is new: learning both at once would be i+2. JPDB ranks 本題 alone "
               "well above the phrase — it is a word of its own, not one living inside it.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_READY,)),
    Case(id="JA-PHR-020", lang="ja", layer="phrases", category="L", text="では本題に入ろう。", span="本題に入ろう",
         expect={"ready": True, "waits_for": [], "score": "half"}, ctx={"known": ["本題", "入る"]},
         basis="Every real word known: ready, and at half score — readable through words already known.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_READY,)),
    Case(id="JA-PHR-021", lang="ja", layer="phrases", category="L", text="やっと腑に落ちた。", span="腑に落ち",
         expect={"ready": True, "score": "full", "bound": ["腑"]}, ctx={"known": ["落ちる"]},
         basis="腑 lives only inside 腑に落ちる (JPDB ranks it alone rarer than the phrase) and is one character: never "
               "waited for — the phrase is ready with 腑 new, at full score (腑 is still the new thing).",
         status="LOCK", decision="PHRASE-ROWS", refs=(_READY,)),
    Case(id="JA-PHR-022", lang="ja", layer="phrases", category="L", text="彼は眉根を寄せた。", span="眉根を寄せ",
         expect={"ready": True, "score": "full", "bound": ["眉根"]}, ctx={"known": ["寄せる"]},
         basis="眉根 lives only inside 眉根を寄せる: learned with it — ready, full score.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_READY,)),
    Case(id="JA-PHR-023", lang="ja", layer="phrases", category="L", text="そんな気がする。", span="気がする",
         expect={"ready": True, "score": "half"}, ctx={"known": ["気"]},
         basis="気がする: 気 known, する light: every real word known — half score.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_READY,)),
    Case(id="JA-PHR-024", lang="ja", layer="phrases", category="L", text="手っ取り早い方法だ。", span="手っ取り早い",
         expect={"ready": True, "bound": ["手っ取り"]}, ctx={"known": ["早い"]},
         basis="手っ取り is no word on its own — it lives only inside 手っ取り早い, whose uses it gives the phrase (it "
               "leaves the list).",
         status="LOCK", decision="PHRASE-ROWS", refs=(_READY,)),
    Case(id="JA-PHR-025", lang="ja", layer="phrases", category="L", text="やっと気がついた。", span="気がつい",
         expect={"ready": False, "waits_for": ["付く"], "score": "full"},
         basis="With nothing known 気がつく waits for 付く; never for 気 — one character, never a list row.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_READY,)),
    Case(id="JA-PHR-026", lang="ja", layer="phrases", category="L", text="かけがえのない友達だ。", span="かけがえのない",
         expect={"found": ["かけがえのない"], "bound": ["掛け替え"]},
         basis="The user's B3: 掛け替え lives on inside its phrase row 掛け替えのない ('irreplaceable'), the useful "
               "unit; only the bare fragment row leaves.",
         status="LOCK", decision="PHRASE-ROWS", refs=("Phrase_Bundle_Spec.md top: B3",)),
    # --- the last round (lane LR, 2026-10-01): a phrase keyed through a word the tagger cuts ---------------------- #
    Case(id="JA-PHR-039", lang="ja", layer="phrases", category="F", text="会計を済ませてから帰った。", span="会計を済ませ",
         expect={"found": ["会計を済ませる"]},
         basis="会計を済ませる 'settle the bill' (JMdict) is found by its words' lemmas, now 会計 + を + 済ませる (the verb "
               "JMdict lists, no longer 済む + せる): the phrase data is rebuilt with the joins.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_SPEC,)),
    # --- a dictionary spelling the tokenizer reads as other words (the user's card examples, 2026-10-01) ---------- #
    Case(id="JA-PHR-040", lang="ja", layer="phrases", category="F", text="やっぱり彼のほうが背が高い。", span="",
         expect={"not_found": ["彼の方"]},
         basis="彼のほう 'his side' is 彼 'he' + の + 方 (ほう). JMdict's 彼の方 'that person' is あのかた / かのかた: read "
               "alone the old spelling is 彼 + の + 方 too, so its phrase took every 'his side' (14 on the user's library, "
               "all of them).",
         status="LOCK", decision="PHRASE-ROWS", refs=(_RULE, _EXAMPLES),
         note="Fixed 2026-10-01 (ENGINE 30): the build keys a spelling only where the tokenizer reads it as JMdict does."),
    Case(id="JA-PHR-041", lang="ja", layer="phrases", category="F", text="彼の娘は医者だ。", span="",
         expect={"not_found": ["彼の娘"]},
         basis="'his daughter': 彼 + の + 娘. JMdict's 彼の娘 'that girl' (あのこ) is no 彼 'he'.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_RULE, _EXAMPLES),
         note="Fixed 2026-10-01 (ENGINE 30): the build keys a spelling only where the tokenizer reads it as JMdict does."),
    Case(id="JA-PHR-042", lang="ja", layer="phrases", category="F", text="あの方が来られた。", span="",
         expect={"not_found": ["がたが来る"]},
         basis="'that person came': あの + 方 (かた) + が + 来る. がたが来る 'get rickety' is found by its words' lemmas — "
               "its がた is the tagger's 方 (がた) — and the matcher never asks a word's reading.",
         status="LIMIT", decision="PHRASE-ROWS", refs=(_RULE, _EXAMPLES),
         note="Accepted 2026-10-01 (the user: leave it, log it — Parsing_Future_Work.md): a reading check when matching "
              "refused about 1,450 right matches on the user's library (その後 あと / ご, 溜め息を吐く つく / はく — the "
              "tagger says such words differently from sentence to sentence) to stop this one (1 of がたが来る's 2)."),
    Case(id="JA-PHR-043", lang="ja", layer="phrases", category="F", text="彼は口の端を少し上げた。", span="",
         expect={"not_found": ["口の端"]},
         basis="口の端 'the corner of the mouth' (くちのはし). JMdict's 口の端 is 'gossip' (くちのは): read 口 + の + 端, it "
               "took every corner of a mouth — a row on the user's list with 30 uses, all of them.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_RULE, _EXAMPLES),
         note="Fixed 2026-10-01 (ENGINE 30): the build keys a spelling only where the tokenizer reads it as JMdict does."),
    Case(id="JA-PHR-044", lang="ja", layer="phrases", category="F", text="その者は前に進み出た。", span="",
         expect={"not_found": ["其者"]},
         basis="その者 'that person'. JMdict's 其者 (それしゃ) 'an expert, a geisha', read その + 者, took them (54 on the "
               "user's library).",
         status="LOCK", decision="PHRASE-ROWS", refs=(_RULE, _EXAMPLES),
         note="Fixed 2026-10-01 (ENGINE 30): the build keys a spelling only where the tokenizer reads it as JMdict does."),
    Case(id="JA-PHR-045", lang="ja", layer="phrases", category="F", text="この間はありがとう。", span="この間",
         expect={"found": ["この間"]},
         basis="この間 'the other day' (このあいだ): read alone the tagger says 間 ま, but JMdict reads 間 あいだ too — the "
               "spelling's words are the phrase's. A reading test on the build must keep it.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_RULE, _EXAMPLES)),
    Case(id="JA-PHR-046", lang="ja", layer="phrases", category="F", text="彼は意志の強い人だ。", span="意志の強い",
         expect={"found": ["意志の強い"]},
         basis="意志の強い 'strong-willed': read alone the tagger says 強い シイ; JMdict reads 強い つよい — the phrase's own "
               "word. A reading test on the build must keep it.",
         status="LOCK", decision="PHRASE-ROWS", refs=(_RULE, _EXAMPLES)),
    Case(id="JA-PHR-047", lang="ja", layer="phrases", category="F", text="あいつは性質の悪い冗談を言う。",
         span="性質の悪い", expect={"found": ["性質の悪い"]},
         basis="性質の悪い 'nasty' (たちのわるい) — the same idiom as 質の悪い. Read alone the tagger says 性質 せいしつ, a "
               "reading JMdict never gives this spelling.",
         status="LIMIT", decision="PHRASE-ROWS", refs=(_RULE, _EXAMPLES, "Parsing_Future_Work.md #64"),
         note="Accepted 2026-10-01 (ENGINE 30; the user: \"go build it. your lean. But mark down idioms that we lose\"): "
              "the build's reading test drops this spelling; the idiom keeps its row as たちの悪い / 質の悪い."),
    Case(id="JA-PHR-048", lang="ja", layer="phrases", category="F", text="まさに同病相憐れむだな。",
         span="同病相憐れむ", expect={"found": ["同病相憐れむ"]},
         basis="同病相憐れむ 'misery loves company': the tagger cuts it 同 + 病相 + 憐れむ — no reading of those words says "
               "どうびょうあいあわれむ, but the cut is the same in every sentence, so its words find the proverb.",
         status="LIMIT", decision="PHRASE-ROWS", refs=(_RULE, _EXAMPLES, "Parsing_Future_Work.md #64"),
         note="Accepted 2026-10-01 (ENGINE 30; the user: \"at some point it would be nice to get them working\"): the "
              "build's reading test drops it — no other spelling keeps the row. Winning it back: #64."),
]

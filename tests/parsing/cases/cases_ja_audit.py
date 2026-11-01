"""Problem kinds the random audit found that no case held (audit 2026-09-27, Parsing_Suite.md §13).

Each came from a random library sentence, verified by hand; the expectation is the answer the language justifies
(WORD-IDENTITY). Group AUD belongs to this file; later audits add their new kinds here."""
from tests.parsing.case import Case, srt

_REF = "audit 2026-09-27"
_REF2 = "audit 2026-09-29"
_REF3 = "audit 2026-09-30"

CASES = [
    Case(id="JA-AUD-001", lang="ja", layer="tokens_ja", category="H",
         text="9そこでこの御方は、片手を差し伸べて人々に言われた。", span="御方",
         expect={"units": "御方[御方,*,*]"},
         basis="御方 (おかた, 'that honoured person'; JMdict 御方) is a word of its own; UniDic files it under 味方 "
               "'ally' — historically 味方 comes from 御方, but they are two words today, and the scripture means Christ.",
         status="TARGET", source="library: 3nephi_11", refs=(f"{_REF} S206",),
         note="High impact: every 御方 counts as a use of 味方."),
    Case(id="JA-AUD-002", lang="ja", layer="tokens_ja", category="H",
         text="そして、彼らはレーマン人に会った。", span="人",
         expect={"units": "人[人,ジン,*]¹"},
         basis="The suffix 人 after a people's name is じん (レーマン人 'Lamanites', like 日本人 / アメリカ人); UniDic reads "
               "it ニン after a katakana name.",
         status="TARGET", source="library: mosiah_20", refs=(f"{_REF} S075",)),
    Case(id="JA-AUD-003", lang="ja", layer="tokens_ja", category="H",
         text="17さて、ラコーニアスは、ニーファイ人の全軍隊に連隊長を任命し、強盗たちが荒れ野から攻めて来るときに軍隊を"
              "指揮できるようにした。", span="人",
         expect={"units": "人[人,ジン,*]¹"},
         basis="As JA-AUD-002: ニーファイ人 is 'Nephites' — the people-suffix じん.",
         status="TARGET", source="library: 3nephi_3", refs=(f"{_REF} S098",)),
    Case(id="JA-AUD-004", lang="ja", layer="text", category="A",
         text=("6さて、わたしモロナイはこれらのことについて少々述べたい。\n"
               "7わが子よ、あなたはそのような重大な①罪を犯さなければよかったものを。\n"
               "8見よ、わたしはあなたに言う。\n"), span="わが",
         expect={"contains": ["わが子よ、あなたはそのような重大な罪を犯さなければよかったものを。"],
                 "words": ["我が"], "not_words": ["把"]},
         basis="わが子 is 我が子 'my child'. The verse number 7 glued to the line makes UniDic read 7わ as a count (把 'bundles'); "
               "the number is the file's apparatus, not the sentence (as JA-TXT-031 / 032 for citations and footnote "
               "marks) — verses numbered line after line, 6, 7, 8, are the book's numbering.",
         status="LOCK", source="library: alma_39 (verse 7); verses 6 and 8 are the library's Moroni and Ether "
                               "(tests/test_verse_numbers.py), numbered here as one chapter",
         refs=(f"{_REF} S065", "F3", "tests/test_text_conventions.py"),
         note="Moved from tokens_ja (the store's cached line) to the file, where the number is (F3): the tokenizer "
              "reads what the reader gives it. The same line's ① made 罪 read ザイ as a suffix (JA-TXT-032's class)."),
    Case(id="JA-AUD-005", lang="ja", layer="tokens_ja", category="H",
         text="バッバカかお前は！", span="バッ",
         expect={"units": "バッ[*,*,*]⊘"},
         basis="A stammer — the first sound of the next word, cut off with っ (バッ…バカ) — is a disfluency, not a word; "
               "today it is read as 婆 'old woman'.",
         status="TARGET", source="library: [coalgirls]_code_geass_04", refs=(f"{_REF} S067",),
         note="A rule has to be principled, not a list: a syllable (+ っ / 、 / …) directly followed by a word that begins "
              "with the same syllable."),
    Case(id="JA-AUD-006", lang="ja", layer="tokens_ja", category="H",
         text="「や、やべえ……俺……堀北に惚れちまったかも……」", span="や",
         expect={"units": "や[*,*,*]⊘"},
         basis="As JA-AUD-005: や、やべえ is a stammer on やべえ, not the particle や.",
         status="TARGET", source="library: ようこそ実力至上主義の教室へ1_48", refs=(f"{_REF} S276",)),
    Case(id="JA-AUD-007", lang="ja", layer="tokens_ja", category="E",
         text="知者や学者を辱める御言葉が、これまで何度も②幼い子供に与えられてきた。", span="御言葉",
         expect={"units": "御言葉[御言葉,ミコトバ,*]"},
         basis="御言葉 (みことば, 'the Word'; JMdict 御言葉) is one word; today 御 (read オ) + 言葉.",
         status="TARGET", source="library: alma_32", refs=(f"{_REF} S070",)),
    Case(id="JA-AUD-008", lang="ja", layer="tokens_ja", category="G",
         text="ヘヘ…ちいっとヤツらのことを侮ってたな。", span="ヘヘ",
         expect={"units": "ヘヘ[*,*,感動詞]"},
         basis="ヘヘ is a laugh (JMdict へへ int. 'heh heh'), one interjection — not two of へえ 'oh really'.",
         status="TARGET", source="library: ヴィンランド・サガ.s01e12", refs=(f"{_REF} S140",)),
    Case(id="JA-AUD-009", lang="ja", layer="tokens_ja", category="G",
         text="ンンッ…。", span="ンンッ",
         expect={"units": "ンンッ[*,*,*]⊘"},
         basis="ンンッ is a vocalization (a moan), not vocabulary; today it is counted as a listable noun.",
         status="TARGET", source="library: bleach - 267", refs=(f"{_REF} S324",),
         note="A fix needs a principled test that tells a vocalization from an unknown name — サテラ also has no reading."),
    # --- the second audit (2026-09-29, seed 20260929): the new problem kinds (SUMMARY.md) ---------------------------- #
    Case(id="JA-AUD-010", lang="ja", layer="tokens_ja", category="I",
         text="サクサクジャがいも完成でございます。", span="サクサクジャがいも",
         expect={"not_words": ["サクサクジャ", "街"]},
         basis="サクサク 'crispy' (a sound word) + じゃがいも 'potato' (JMdict, here written ジャがいも): two words. The "
               "katakana-names rule glues the sound word to the katakana head of the next word (サクサクジャ) and leaves "
               "がい read as 街 'town'.",
         status="TARGET", source="library: kousei cooking (youtube)", refs=(f"{_REF2} S211", "JA-NAM-414"),
         note="High impact. Half fixed 2026-09-30 (lane N4): names layer 1 no longer glues サクサク to the head of "
              "ジャがいも (JA-NAM-414, LOCK); ジャがいも itself is still read 蛇 + 街 + も — a word split at its script's "
              "edge, which no layer joins yet."),
    Case(id="JA-AUD-011", lang="ja", layer="tokens_ja", category="C",
         text="親指と人差し指を口の中に突っ込んでぴいーーーっと指笛を吹いている人や、「ジャ─────ック！」と黄色い声を上げ"
              "ている人もいる。", span="ジャ─────ック",
         expect={"units": "ジャ─────ック[ジャック]", "not_words": ["蛇", "ック"]},
         basis="ジャ─────ック is the name ジャック shouted, stretched with box-drawing dashes (─ U+2500) used as a long mark: "
               "one word, as a ～ stretch is its word (すご～い). Today ジャ is read as 蛇 'snake' and ック is a junk noun.",
         status="LOCK", decision="KATAKANA-STRETCH-DROP", source="library: ぼくはイエローでホワイトで、ちょっとブルー_17",
         refs=(f"{_REF2} S146",),
         note="High impact. Fixed 2026-09-30 (lane AF): a dash run between katakana where the word goes on after ッ is "
              "a stretch, read as one ー — ジャーック, as ジャ～ック is (STRETCH-MARKS keeps a katakana stretch's ー); the "
              "name ジャック would need a katakana stretch the dictionary lacks dropped (a question, Future Work). "
              "Fixed 2026-10-01 (lane LR): ジャーック is no word and ジャック is — read without the stretch (KATAKANA-STRETCH-DROP)."),
    Case(id="JA-AUD-012", lang="ja", layer="tokens_ja", category="I",
         text="『ブシン祭』予選Ｂブロック決勝、この試合もジミナの勝利で終わった。", span="ブシン",
         expect={"not_words": ["無", "しん"]},
         basis="ブシン祭 is a festival's name, ブシン its katakana name: no prefix 無 (ブ) and no word しん inside it. UniDic "
               "reads ブ as the prefix 無 and シン as しん.",
         status="LOCK", decision="NAMES-UNLISTED-KATAKANA", source="library: 陰の実力者-2_27",
         refs=(f"{_REF2} S105", "JA-AFX-243"),
         note="High impact. Fixed 2026-09-30 (lane N4): ブシン is a headword the dictionary joins don't hold, cut into a "
              "prefix and a word — one word now, keyed as a word no dictionary has."),
    Case(id="JA-AUD-013", lang="ja", layer="tokens_ja", category="I",
         text="十文字会頭…", span="十文字",
         expect={"units": "十文字[*]"},
         basis="十文字 (Jūmonji) is a surname (JMnedict) — here the student-council head's; the numeral 十 is part of the "
               "name, not a number to drop, and 文字 'letter' is not in the sentence.",
         status="LIMIT", decision="NAMES-KANJI", source="library: the irregular at magic high school s01e05",
         refs=(f"{_REF2} S051",),
         note="Accepted 2026-09-30 (lane N4): 十文字 is also a dictionary word ('cross': JPDB 2024 #33,947, Jiten, JMdict), "
              "and a name that is also a dictionary word stays as the dictionary leaves it (NAMES-KANJI's price: 冬月, "
              "伊吹, 一葉); the compound build keeps the word apart as a count (JT-NUMERAL-WORDS: 文字 counts letters, "
              "and the lists read 一文字 イチモンジ as they read 十文字). Names layer 4 can't reach it: 文字 is no single "
              "kanji. 零崎 (S181), a family name no dictionary holds, is layer 4's: JA-NAM-403, LOCK."),
    Case(id="JA-AUD-014", lang="ja", layer="tokens_ja", category="E",
         text="よね汚らしい人間どもめわが苦しみと憎しみを知るがよいって言ってドロドロドロっと消えてしまうこの時の中声がですね"
              "めちゃくちゃ良くてですねこれあの俳優さんの喉にマイ", span="どもめ",
         expect={"not_words": ["揉める"]},
         basis="人間どもめ is 人間 + the plural ども + the contemptuous め ('you wretched humans'). UniDic cuts it as the "
               "prefix ど + 揉める 'to quarrel', which is not in the sentence.",
         status="TARGET", source="library: the irregular at magic high school s01e12", refs=(f"{_REF2} S228 (canary)",),
         note="A reviewers' miss on a canary sentence (JA-SND-237's), found by the orchestrator. High impact: every use "
              "counts toward 揉める. Measured 2026-09-30 (lane AF): 6 uses in the library, all Nどもめ (愚か者どもめ, ガキ"
              "どもめ); UniDic reads どもめ so even alone, and ども + め only before a particle (人間どもめが). Not built: the "
              "tagger's 4th-best reading holds ども + め, and no rule the decisions allow picks it — a prefix ど never "
              "comes before a verb in Japanese, but UniDic puts other prefixes there (お話し, 相変わらず), so a test of "
              "ど alone would be a rule for one string (Future Work)."),
    Case(id="JA-AUD-015", lang="ja", layer="tokens_ja", category="I",
         text="池くらいのレベルで落とせるような女の子じゃないと思うぞ、櫛田は。", span="櫛田",
         expect={"units": "櫛田[*,クシダ,*]"},
         basis="櫛田 is read くしだ (JMnedict), as UniDic itself reads it elsewhere in the same book (S005): one name, one "
               "reading. Read クシタ here, it makes a second list row for the same person.",
         status="LIMIT", decision="UNIDIC-LEMMA", source="library: ようこそ実力至上主義の教室へ1_15",
         refs=(f"{_REF2} S234", f"{_REF2} S005"),
         note="Accepted 2026-09-30 (lane N4): UniDic holds two surname entries spelled 櫛田 (クシタ, クシダ) and picks one "
              "by context, and a name's identity is UniDic's lemma — for a proper noun its reading — so the two readings "
              "are two rows (UNIDIC-LEMMA's price: between two entries for one spelling it picks by context). Joining "
              "them would need a names reading table (the shipped JMnedict data holds spellings only), the library's "
              "majority reading (a library-made rule, WORD-IDENTITY), or keying every name UniDic knows by its spelling "
              "(NAMES-STAY: a name UniDic knows keeps its katakana lemma, and every known name's key would move)."),
    Case(id="JA-AUD-016", lang="ja", layer="tokens_ja", category="I",
         text="......いくら見た目に手を加えたところで、麗乃の興味は本にしか向かっていないから無駄なのにな。", span="麗乃",
         expect={"units": "麗乃[*,ウラノ,*]"},
         basis="麗乃 is the heroine's given name, read うらの (本須麗乃, Motosu Urano); UniDic gives it レイノ.",
         status="LIMIT", decision="UNIDIC-LEMMA", source="library: honzukiv1_25", refs=(f"{_REF2} S275",),
         note="Accepted: a name's reading comes from UniDic (its one fixed reading), and no dictionary of Japanese "
              "gives this one — the row is still one word, under a wrong reading."),
    Case(id="JA-AUD-017", lang="ja", layer="tokens_ja", category="G",
         text="ああ～その棚はあっちあっち。", span="ああ～",
         expect={"units": "ああ～[*]"},
         basis="ああ～ is the interjection ああ 'ah', stretched: one word, as すご～い is すごい. UniDic cuts it into two "
               "one-kana interjections (あ + あ～).",
         status="LOCK", decision="FILLER-PIECES", source="library: コンフィデンスマンjp s01e04", refs=(f"{_REF2} S007",),
         note="Fixed 2026-09-30 (lane AF): two fillers, each one kana, that read alone as one interjection are it."),
    Case(id="JA-AUD-018", lang="ja", layer="tokens_ja", category="G",
         text="うーん、この時期に中国に行くっていうのは、ちょっと大丈夫なの？ってなんか何人かからコメントもらったりもしたんで"
              "すけどで、私自身も実際ちょっと大丈夫かな？って思っていたところはあったんですけどまあやっぱり政治的な問題だけ"
              "で全然中国の方、私が出会った方は本当に優しかった。", span="まあ",
         expect={"units": "まあ[*]"},
         basis="まあ 'well' is one interjection (JMdict); UniDic cuts it into ま + あ inside unpunctuated speech.",
         status="LOCK", decision="FILLER-PIECES", source="library: peko peko vlog #27 (youtube)", refs=(f"{_REF2} S096",),
         note="Fixed 2026-09-30 (lane AF): ま + あ read alone is the adverb まあ."),
    Case(id="JA-AUD-019", lang="ja", layer="tokens_ja", category="G",
         text="ハァハァハァ…", span="ハァハァハァ",
         expect={"not_words": ["ハァハァハァ"]},
         basis="Panting said three times is the sound word はあはあ repeated, no word of its own; as a whole it becomes "
               "an unknown noun no dictionary lists.",
         status="LOCK", decision="REPEATED-SOUNDS", source="library: bleach - 270", refs=(f"{_REF2} S149",),
         note="As repeated sounds stay apart from the names layers (ワンワンワン). Fixed 2026-09-30 (lane AF): はあはあ's "
              "row, shown ハァハァハァ."),
    Case(id="JA-AUD-020", lang="ja", layer="text", category="B",
         text="ﾑﾀﾞだぜ｡｢ﾏｼﾞかよ｣\n", span="｡｢",
         expect={"not_contains": ["｡｢"]},
         basis="Half-width ｡ ends the sentence and half-width ｢ opens the next one: the bracket belongs to the next "
               "line's sentence, never to the end of this one (as 。「 in full width).",
         status="LOCK", decision="GLUED-OPENER", source="library: bleach - 157 (the second line constructed)",
         refs=(f"{_REF2} S014",),
         note="The audit's sentence is 'ﾑﾀﾞだぜ｡｢' as the token store split it. Fixed 2026-09-30 (lane AF): the tagger "
              "reads ｡｢ as one symbol (it knows neither half-width form); the bracket after the stop opens the next "
              "sentence. The store's splitter is this one (token_index.make_tokenizer)."),
    Case(id="JA-AUD-021", lang="ja", layer="tokens_ja", category="H",
         text="情に流されやすいってんならまだ格好もつくが、ただ状況に流されやすいだけだってんだから、全く以て中途半端だ。",
         span="以て",
         expect={"units": "以て[以て,モッテ,*]"},
         basis="全く以て 'utterly' — 以て is もって (JMdict 以て), the word; UniDic reads it モテ as a prefix.",
         status="LIMIT", decision="UNIDIC-LEMMA", source="library: 戯言2_07", refs=(f"{_REF2} S123",),
         note="Accepted: a rare written form UniDic misreads; the word is still counted (low impact). Confirmed "
              "2026-09-30 (lane AF): 1 use in the library; UniDic reads 以て before a noun as its prefix entry モテ, "
              "and its next-best reading is the verb (以 = 持つ + て), as it reads 書面を以て — never the word 以て; "
              "only a word-sense rule would pick (JT-SENSE)."),
    Case(id="JA-AUD-022", lang="ja", layer="tokens_ja", category="E",
         text="何様？」", span="何様",
         expect={"units": "何様[*]"},
         basis="何様 'who do you think you are' is a JMdict and Jiten headword with a meaning of its own; UniDic cuts it "
               "into 何 + the honorific 様 — a dictionary word ending in an honorific (U17-HONORIFIC-WORDS).",
         status="LOCK", decision="PRONOUN-BASES", source="library: utsuronohakov1_29", refs=(f"{_REF2} S308",),
         note="Accepted 2026-09-30 (lane AF): 何 is a pronoun (代名詞), and JT-PART-A takes no pronoun as a base (its "
              "price: お前 + さん). Measured: letting a pronoun carry a suffix adds 98 headwords to the join table "
              "(それなり, お前さん, これっぽっち, 俺様, どちら様, 何様, あなた様, 私なり …; library uses: それなり 119, 俺様 "
              "~75, お前さん ~45, これっぽっち 22, 何様 15) but also the plurals あなた方 / 貴方方 (the plural guard reads "
              "方 by its lForm, which the tagger gives as カタ there) and colloquial collisions (私家 シカ for わたし家). "
              "Needs a table rebuild: a question for the user (lane AF HANDOFF). "
              "Fixed 2026-10-01 (lane LR): a pronoun carries a suffix while the pronouns switch is on (PRONOUN-BASES), the plural guard reading 方 by the lists' reading."),
    Case(id="JA-AUD-023", lang="ja", layer="tokens_ja", category="D",
         text="GS「救い－幼い子供たちの救い」", span="－",
         expect={"absent": True},
         basis="The full-width dash － is punctuation between a heading's two parts, not the particle から; UniDic reads it "
               "から and it is counted.",
         status="LOCK", decision="DASH-NOT-A-WORD", source="library: moroni_8", refs=(f"{_REF2} S321",),
         note="Fixed 2026-09-30 (lane AF): dash punctuation is never a word, in a heading or anywhere."),
    # --- lane AF's guards (2026-09-30): the edges of the rules built for the second audit's kinds ------------------- #
    Case(id="JA-AUD-024", lang="ja", layer="tokens_ja", category="C",
         text="「衛兵さ───ん!!」", span="さ───ん",
         expect={"units": "さ───ん[さん,サン,*]"},
         basis="衛兵さーん — 'Guard!' called out: the honorific さん stretched with box-drawing dashes before the ん that "
               "ends the word, one word as さ～ん is. Read apart, さ was the particle and ん the interjection んっ.",
         status="LOCK", decision="DASH-STRETCH", source="library: rezerov1_24 (and rezerov2_24)"),
    Case(id="JA-AUD-025", lang="ja", layer="tokens_ja", category="C",
         text="「な、何──ッ」", span="何──ッ",
         expect={"units": "何[何,ナニ,*] | ─[─,,補助記号]⊘ | ─[─,,補助記号]⊘ | ッ[っ,,補助記号]⊘"},
         basis="何──ッ — 'Wha—!': a shout whose stretch ends in its catch ッ. The word is 何; read as a stretch (何ーッ) "
               "the tagger made 何 + つ, so a dash before a ッ that ends the word stays a dash.",
         status="LOCK", decision="DASH-STRETCH", source="library: 陰の実力者-4_36"),
    Case(id="JA-AUD-026", lang="ja", layer="tokens_ja", category="C",
         text="「寝込みを襲われたのかも──って、ああ、あいた、これ僕様ちゃん大失敗。", span="かも──って",
         expect={"words": ["って"], "not_words": ["持つ"]},
         basis="のかも──って — 'maybe — I mean': the dash pauses before the quotative って, a word of its own that begins "
               "with っ. Read as a stretch, もーって became 持って.",
         status="LOCK", decision="DASH-STRETCH", source="library: 戯言1_51"),
    Case(id="JA-AUD-027", lang="ja", layer="tokens_ja", category="C",
         text="背後に立つのは桃髪のメイド──ラムだ。", span="メイド──ラム",
         expect={"units": "メイド[*] | ─[─,,補助記号]⊘ | ─[─,,補助記号]⊘ | ラム[*]"},
         basis="メイド──ラム — 'the maid — Ram': the dash between two katakana words; read as a stretch the two would be "
               "one katakana run (メイドーラム).",
         status="LOCK", decision="DASH-STRETCH", source="library: rezerov4_26",
         note="ラム is the character's name read as ラム 'lamb' — the names layers' matter, not this case's."),
    Case(id="JA-AUD-028", lang="ja", layer="tokens_ja", category="G",
         text="うえ～ん…", span="うえ～ん",
         expect={"not_words": ["上", "円", "縁"]},
         basis="うえ～ん is crying (the sound うえーん). Its fillers う + え〜 read alone as 上 'above', and え〜 + ん as no "
               "interjection: no word is made of them.",
         status="LOCK", decision="FILLER-PIECES", source="library: the irregular at magic high school.s01e13"),
    Case(id="JA-AUD-029", lang="ja", layer="tokens_ja", category="G",
         text="騒がんでええ｡", span="ええ",
         expect={"units": "ええ[良い,*,*]"},
         basis="Kansai ええ is いい 'good / fine' (騒がんでええ 'no need to make a fuss'), the adjective 良い; UniDic reads "
               "ええ alone as the interjection 'yes'.",
         status="LIMIT", decision="FILLER-PIECES", source="library: bleach - 220",
         note="Was え + え (two fillers), now ええ 'yes': one wrong word instead of two."),
    Case(id="JA-AUD-030", lang="ja", layer="tokens_ja", category="G",
         text="いえいえ会長こそ。", span="いえいえ",
         expect={"units": "いえ[いえ,イエ,*] | いえ[いえ,イエ,*]"},
         basis="いえいえ 'no, no' is いえ twice; the tagger cut it into four one-kana fillers. Pairs join left to right.",
         status="LOCK", decision="FILLER-PIECES",
         source="library: かぐや様は告らせたい～天才たちの恋愛頭脳戦～-シーズン1-10"),
    Case(id="JA-AUD-031", lang="ja", layer="tokens_ja", category="G",
         text="一角のために…ﾌﾌﾌﾌ…｡", span="ﾌﾌﾌﾌ",
         expect={"words": ["ふふ"], "not_words": ["フフフフ"]},
         basis="A laugh said four times, in half-width katakana (read フフフフ): the sound word ふふ, which UniDic lists "
               "said twice; in this line it was an unknown word of its own.",
         status="LOCK", decision="REPEATED-SOUNDS", source="library: bleach - 229",
         note="Alone the line ﾌﾌﾌﾌ…｡ reads as ﾌﾌ + ﾌﾌ, two of ふふ — as right."),
    Case(id="JA-AUD-032", lang="ja", layer="tokens_ja", category="G",
         text="「シャ、シャ、シャシャシャシャシャ、シャドウ様が!?」", span="シャシャシャシャシャ",
         expect={"absent": True},
         basis="A stammer on シャドウ, no word: シャ said over is the start of the name, not the sound しゃしゃ.",
         status="LIMIT", decision="REPEATED-SOUNDS", source="library: 陰の実力者-4_40",
         note="Was the unknown word シャシャシャシャシャ, now しゃしゃ — junk either way (JA-AUD-005's stammers)."),
    Case(id="JA-AUD-033", lang="ja", layer="tokens_ja", category="G",
         text="ヘヘヘ！", span="ヘヘヘ",
         expect={"not_words": ["ヘヘヘ"]},
         basis="ヘヘヘ is the laugh へへ said three times, no word of its own; the tagger leaves it a word it doesn't "
               "know, and reads ヘヘ alone as two words (屁 + へ), so the repeated-sound rule can't reach it.",
         status="TARGET", source="library: bleach - 311", refs=("JA-AUD-008",),
         note="Fixed with JA-AUD-008 (ヘヘ read as one interjection)."),
    Case(id="JA-AUD-034", lang="ja", layer="text", category="B",
         text="乱菊さんも冬獅郎君も放っておくとｸﾞﾁｬｸﾞﾁｬにしちゃうからな…｡((ほんまに困るわ))\n", span="｡((",
         expect={"not_contains": ["｡(("], "contains": ["((ほんまに困るわ))"]},
         basis="The next line's (( (a thought in parentheses) opens its own sentence; the tagger reads ｡(( as one symbol.",
         status="LOCK", decision="GLUED-OPENER", source="library: bleach - 141 (the thought constructed)"),
    Case(id="JA-AUD-035", lang="ja", layer="text", category="B",
         text="言っただろう〝君は僕が常に— 〞。〝それが答えだ〞\n", span="。〝",
         expect={"not_contains": ["。〝"]},
         basis="〞 closes the quotation, 。 ends the sentence and 〝 opens the next quotation; the tagger reads 〞。〝 as "
               "one symbol.",
         status="LOCK", decision="GLUED-OPENER", source="library: bleach - 269 (the second quotation constructed)"),
    Case(id="JA-AUD-036", lang="ja", layer="tokens_ja", category="D",
         text="GS「人（霊を持つ存在としての）－人の価値」", span="－",
         expect={"absent": True},
         basis="The full-width dash between a scripture heading's two parts is punctuation, not 対 'versus' — UniDic's "
               "word for it here.",
         status="LOCK", decision="DASH-NOT-A-WORD", source="library: mosiah_25 (and mosiah_28, alma_24, alma_31)"),
    Case(id="JA-AUD-037", lang="ja", layer="tokens_ja", category="C",
         text="ヤツの作った霊骸は悔しいが完璧に我々をコピ－しているのだよ。", span="コピ－",
         expect={"units": "コピ－[コピー,*,*]"},
         basis="コピ－ is コピー 'copy' with its long vowel typed as a full-width dash: one word. The tagger reads コピ as "
               "コーヒー and the dash as マイナス (no word since lane AF).",
         status="TARGET", source="library: bleach - 320",
         note="Found 2026-09-30 (lane AF), a new kind: a katakana long vowel written with a dash (also ルル―シュ for "
              "ルルーシュ). A single dash between katakana is as often the dash between two words (イスラエル－イスラエル "
              "の集合), so a rule needs more than its position (Future Work)."),
    # --- audit 2026-09-30 (seed 20260930): the kinds no case held -------------------------------------------- #
    Case(id="JA-AUD-038", lang="ja", layer="tokens_ja", category="H",
         text="そんなことはくだらない。", span="くだらない",
         expect={"units": "くだらない[*,*,形容詞]"},
         basis="くだらない 'worthless, trivial' is one adjective (JMdict 下らない, adj-i). The tagger reads 下る 'descend' + "
               "the negative ない, so the list counts 下る — another word — for every くだらない.",
         status="LOCK", decision="CUT-VERB-AUX", source="library: pivot 公式チャンネル (YouTube)", refs=(f"{_REF3} S292",),
         note="High impact. A new kind (audit 2026-09-30): a JMdict word the tagger reads as a verb + an auxiliary "
              "(also 思いがけない, 知らせる). A rule in the spirit of CARD-SENSE (the dictionary decides): join a verb + "
              "auxiliary run when JMdict lists the whole as its own entry and JPDB / Jiten rank it — measured as a "
              "variant first (Future Work)."),
    Case(id="JA-AUD-039", lang="ja", layer="tokens_ja", category="H",
         text="思いがけない提案だ。", span="思いがけない",
         expect={"units": "思いがけない[*,*,形容詞]"},
         basis="思いがけない 'unexpected' is one adjective (JMdict 思いがけない). The tagger reads 思い掛ける + ない, putting the "
               "rare verb 思い掛ける on the list.",
         status="LOCK", decision="CUT-VERB-AUX", source="library: ようこそ実力至上主義の教室へ1_12", refs=(f"{_REF3} S112",),
         note="As JA-AUD-038: a verb + auxiliary the dictionary lists whole."),
    Case(id="JA-AUD-040", lang="ja", layer="tokens_ja", category="H",
         text="さて、（アモロン）王はゼラヘムラの地を去って、王妃に自分の兄弟の死について知らせ、大勢の兵を集めて、西の海に"
              "近い境の地でニーファイ人と戦うために軍隊を進めていた。", span="知らせ",
         expect={"units": "知らせ[知らせる]"},
         basis="知らせる 'to inform' is a verb of its own (JMdict 知らせる). Here the tagger reads 知る + the causative せる, so "
               "the list counts 知る.",
         status="LOCK", decision="CUT-VERB-AUX", source="library: alma_52", refs=(f"{_REF3} S123",),
         note="As JA-AUD-038. For cards, CARD-INFLECTIONS already treats voice as part of the word (待たせる, 知らせる)."),
    Case(id="JA-AUD-041", lang="ja", layer="tokens_ja", category="F",
         text="まあお前らはいつもふざけてばっかだけどさ。", span="いつも",
         expect={"units": "いつも[*,*,副詞]"},
         basis="いつも 'always' is one adverb (JMdict 何時も). The tagger reads いつ 'when' + the particle も here, so いつも is "
               "never counted and いつ takes its use.",
         status="LOCK", decision="CUT-WORD-PARTICLES", source="library: s01e10.青い嵐", refs=(f"{_REF3} S020", f"{_REF3} S023"),
         note="A new kind (audit 2026-09-30): a JMdict word the tagger cuts into a word + particles (also ちなみに, どうにか, "
              "でも, それとも). Usually the tagger reads いつも whole; it splits in some contexts. Joining by the dictionary "
              "would need a guard for the true いつ + も (いつも来ない is 'always', but いつも何も is rare) — measure first."),
    Case(id="JA-AUD-042", lang="ja", layer="tokens_ja", category="F",
         text="ちなみに今の時間は十一時。", span="ちなみに",
         expect={"units": "ちなみに[*,*,接続詞]"},
         basis="ちなみに 'by the way' is one word (JMdict 因みに, conj). The tagger reads the noun 因み + に, so the list "
               "offers ちなみ — a word that lives almost only inside ちなみに.",
         status="LOCK", decision="CUT-WORD-PARTICLES", source="library: 戯言2_45", refs=(f"{_REF3} S160",),
         note="As JA-AUD-041."),
    Case(id="JA-AUD-043", lang="ja", layer="tokens_ja", category="F",
         text="そのまま倒れているロム爺の側に近寄り、巨体を引きずってどうにか壁際へ。", span="どうにか",
         expect={"units": "どうにか[*,*,副詞]"},
         basis="どうにか 'somehow' is one adverb (JMdict 如何にか). The tagger reads どう + に + か.",
         status="LOCK", decision="CUT-WORD-PARTICLES", source="library: rezerov1_35", refs=(f"{_REF3} S240",),
         note="As JA-AUD-041."),
    Case(id="JA-AUD-044", lang="ja", layer="tokens_ja", category="F",
         text="「拙者、幼い頃より父親にサバイバル技術を叩き込まれ、ジャングルでも一人で生き抜けるよう鍛えられたでござる。",
         span="生き抜ける",
         expect={"units": "生き抜ける[生き抜く]"},
         basis="生き抜ける is the potential form of 生き抜く 'to survive' (JMdict, a lexical compound verb the compound build "
               "joins). The tagger reads 生きる + 抜ける 'come out', so the lemma run 生きる + 抜ける never meets 生き抜く's "
               "parts and 抜ける takes a wrong use.",
         status="TARGET", source="library: ようこそ実力至上主義の教室へ3_10", refs=(f"{_REF3} S097",),
         note="High impact. A new kind (audit 2026-09-30): a compound verb's potential form read as two verbs — the "
              "family of the 'verb split in context' repairs left out of the compound build (Future Work #8)."),
    Case(id="JA-AUD-045", lang="ja", layer="tokens_ja", category="F",
         text="さて、モロナイはこのことを知り、さらにレーマン人が国境を越えているのを知ると、自分がこれまでそれらの人々を"
              "守るために精いっぱい努めてきたにもかかわらず、彼らがかたくなであるのを非常に怒った。", span="精いっぱい",
         expect={"units": "精いっぱい[精一杯]"},
         basis="精いっぱい is 精一杯 'with all one's might' (JPDB #3,397) written partly in kana. The compound joins 精 + 一 + 杯 "
               "written in kanji (JA-CMP-230); here the tagger reads いっぱい as one word (一杯), so the parts differ and 精 "
               "stands alone.",
         status="TARGET", source="library: alma_51", refs=(f"{_REF3} S193",),
         note="High impact (精 takes the use). A new kind (audit 2026-09-30): a compound written partly in kana whose kana "
              "part the tagger reads as one word."),
    Case(id="JA-AUD-046", lang="ja", layer="tokens_ja", category="F",
         text="あなたがたが祝福にあずかった後、父は、『あなたの子孫により、地のすべての部族が祝福を受けるであろう』と言って"
              "アブラハムと交わした聖約を果たされる。", span="聖約",
         expect={"units": "聖約[*]"},
         basis="聖約 'covenant' is the scriptures' own term, one word; no dictionary lists it (not in JMdict), so only the "
               "library exception can make it one: a work's own kanji term (NAMES-WORK-TERMS, layer 4). Today 聖 (a "
               "prefix) + 約 (a noun), both bound pieces since the one-kanji rule — the term is never counted at all.",
         status="TARGET", source="library: 3nephi_20", refs=(f"{_REF3} S119",),
         note="A new kind (audit 2026-09-30): a work's term made of a prefix + a one-kanji noun. Layer 4 likely misses it: "
              "聖 is used in many other words, so the stickiness of the run stays under 0.7 — measure on the store once "
              "it is rebuilt with layer 4."),
    Case(id="JA-AUD-047", lang="ja", layer="tokens_ja", category="C",
         text="あっそぶ〜！", span="あっそぶ",
         expect={"units": "あっそぶ[遊ぶ]"},
         basis="あっそぶ〜 is 遊ぶ said playfully, drawn out with a small っ inside the word (あ・っ・そぶ). Today あっ + そう + ぶ "
               "(a symbol): そう takes a use, 遊ぶ none.",
         status="TARGET", source="library: bleach - 246", refs=(f"{_REF3} S304",),
         note="A new kind (audit 2026-09-30), rare: STRETCH-MARKS reads ～ and ー inside a word, never a small っ (which is "
              "also a real sound: あっそう 'oh, really')."),
    Case(id="JA-AUD-048", lang="ja", layer="tokens_ja", category="H",
         text="•モーサヤ書", span="書",
         expect={"units": "書[書,ショ,*]¹"},
         basis="書 after a scripture book's name is the suffix 'book of' (しょ), as in アルマ書. After モーサヤ — a name the "
               "katakana names layer joins from モーサ + ヤ — the tagger had read the 書 as 書き (カキ), and it stays so: "
               "書き takes a use from every heading of the book.",
         status="TARGET", source="library: alma_33", refs=(f"{_REF3} S221",),
         note="A new kind (audit 2026-09-30): the tagger's reading of the word after a name it cut, kept after the name "
              "is joined."),
    Case(id="JA-AUD-049", lang="ja", layer="tokens_ja", category="H",
         text="くださ…", span="くださ",
         expect={"units": "くださ[下さる]"},
         basis="くださ… is ください cut off as the speaker trails away; the tagger reads 下す 'hand down', a word that isn't "
               "there.",
         status="TARGET", source="library: ヴィンランド・サガ.s01e15", refs=(f"{_REF3} S269",),
         note="A new kind (audit 2026-09-30): a word cut off mid-way read as another word. JA-ELLIPSIS keeps … a pause; "
              "a rule would have to know the cut word from the next cue."),
    Case(id="JA-AUD-050", lang="ja", layer="text", category="B",
         text=srt("＜　そうだ　幽霊が見えて　優越感を\n感じたことなんてなかった。", "俺は\n憧れていたものになれたんだ＞"),
         span="＞",
         expect={"not_contains": ["＞。"]},
         basis="Japanese broadcast captions put narration and inner voice inside ＜ ＞ across several cues; the closing ＞ "
               "ends that voice the way 」 ends a quotation, so no 。 belongs after it. Today the ＞ is no closing mark "
               "(Unicode files it as a math sign), so the cue gets 。 appended: 「…なれたんだ＞。」.",
         status="TARGET", source="library: bleach - 343 (two of the five cues)", refs=(f"{_REF3} S218",),
         ctx={"ext": ".srt"},
         note="Low: the mark shows in an example sentence; no word moves."),
]

"""What JMdict says about the joined words — scripts/jmdict_flags.py, read at build time only.

The build asks JMdict three things the frequency lists can't answer. Which joined compounds are a title or a phrase
rather than a word of their own (Settings -> "Phrases and titles as one word" can put those back in their parts)?
Which katakana compounds does no dictionary list (ビルデ = ビル + デ), so that they give way to a katakana name around
them? And which お / ご words, left as a prefix + a word by how often the bare word is used, are words of their own
with a meaning the bare word lacks (お守り 'amulet')? The dictionary below is real: entries quoted from JMdict (the EDRDG's
Japanese-English dictionary, CC BY-SA 4.0), a few long ones cut to the senses these tests need.
"""

import gzip
import importlib.util
import os

import pytest

_DTD = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE JMdict [
<!ELEMENT JMdict (entry*)>
<!ENTITY n "noun (common) (futsuumeishi)">
<!ENTITY exp "expressions (phrases, clauses, etc.)">
<!ENTITY adv "adverb (fukushi)">
<!ENTITY adj-no "nouns which may take the genitive case particle 'no'">
<!ENTITY n-pref "noun, used as a prefix">
<!ENTITY n-suf "noun, used as a suffix">
<!ENTITY pref "prefix">
<!ENTITY ctr "counter">
<!ENTITY vs "noun or participle which takes the aux. verb suru">
<!ENTITY vt "transitive verb">
<!ENTITY v1 "Ichidan verb">
<!ENTITY rK "rarely used kanji form">
<!ENTITY int "interjection (kandoushi)">
<!ENTITY abbr "abbreviation">
<!ENTITY hon "honorific or respectful (sonkeigo) language">
<!ENTITY pol "polite (teineigo) language">
<!ENTITY work "work of art, literature, music, etc. name">
<!ENTITY product "product name">
<!ENTITY organization "organization name">
<!ENTITY company "company name">
<!ENTITY char "character">
<!ENTITY yoji "yojijukugo">
<!ENTITY uk "word usually written using kana alone">
<!ENTITY sK "search-only kanji form">
<!ENTITY io "irregular okurigana usage">
<!ENTITY ik "word containing irregular kana usage">
<!ENTITY sports "sports">
<!ENTITY med "medicine">
<!ENTITY unc "unclassified">
<!ENTITY vidg "video games">
<!ENTITY on-mim "onomatopoeic or mimetic word">
<!ENTITY adv-to "adverb taking the 'to' particle">
<!ENTITY adj-f "noun or verb acting prenominally">
]>
<!-- JMdict created: 2026-09-28 -->
<JMdict>
"""

_ENTRIES = [
    # お守り 'amulet', and the same spelling read おもり 'babysitting'; the bare 守り read まもり and もり.
    "<entry><ent_seq>1002060</ent_seq><k_ele><keb>お守り</keb><ke_pri>ichi1</ke_pri></k_ele><k_ele><keb>御守り</keb>"
    "</k_ele><r_ele><reb>おまもり</reb><re_pri>ichi1</re_pri></r_ele><sense><pos>&n;</pos><gloss>charm</gloss>"
    "<gloss>amulet</gloss><gloss>talisman</gloss></sense></entry>",
    "<entry><ent_seq>2268160</ent_seq><k_ele><keb>お守り</keb></k_ele><k_ele><keb>御守り</keb><ke_inf>&sK;</ke_inf>"
    "</k_ele><r_ele><reb>おもり</reb></r_ele><sense><pos>&n;</pos><pos>&vs;</pos><pos>&vt;</pos><gloss>babysitting"
    "</gloss><gloss>babysitter</gloss><gloss>nanny</gloss></sense><sense><pos>&n;</pos><pos>&vs;</pos><pos>&vt;</pos>"
    "<gloss>taking care of</gloss><gloss>looking after</gloss><gloss>accompanying</gloss></sense></entry>",
    "<entry><ent_seq>1327100</ent_seq><k_ele><keb>守り</keb></k_ele><k_ele><keb>護り</keb></k_ele><r_ele>"
    "<reb>まもり</reb></r_ele><sense><pos>&n;</pos><gloss>protection</gloss><gloss>defense</gloss><gloss>defence"
    "</gloss></sense><sense><pos>&n;</pos><gloss>providence</gloss></sense><sense><pos>&n;</pos><xref>守り札</xref>"
    "<xref>守り袋</xref><misc>&abbr;</misc><gloss>amulet</gloss><gloss>charm</gloss><gloss>talisman</gloss></sense>"
    "</entry>",
    "<entry><ent_seq>1327090</ent_seq><k_ele><keb>守り</keb></k_ele><r_ele><reb>もり</reb></r_ele><sense><pos>&n;"
    "</pos><gloss>babysitting</gloss><gloss>babysitter</gloss></sense><sense><pos>&n;</pos><gloss>protecting</gloss>"
    "<gloss>keeping</gloss><gloss>keeper</gloss></sense></entry>",
    # 予想通り 'as expected' and its parts: 通り read どおり is a suffix entry of its own.
    "<entry><ent_seq>1543180</ent_seq><k_ele><keb>予想通り</keb></k_ele><k_ele><keb>予想どおり</keb></k_ele><r_ele>"
    "<reb>よそうどおり</reb></r_ele><sense><pos>&adv;</pos><pos>&adj-no;</pos><gloss>as expected</gloss><gloss>as "
    "predicted</gloss></sense></entry>",
    "<entry><ent_seq>1543130</ent_seq><k_ele><keb>予想</keb></k_ele><r_ele><reb>よそう</reb></r_ele><sense><pos>&n;"
    "</pos><pos>&vs;</pos><pos>&vt;</pos><pos>&adj-no;</pos><gloss>expectation</gloss><gloss>prediction</gloss>"
    "</sense></entry>",
    "<entry><ent_seq>1432930</ent_seq><k_ele><keb>通り</keb></k_ele><r_ele><reb>どおり</reb></r_ele><r_ele><reb>どうり"
    "</reb><re_inf>&ik;</re_inf></r_ele><sense><pos>&n-suf;</pos><gloss>in accordance with</gloss><gloss>following"
    "</gloss></sense><sense><pos>&n-suf;</pos><gloss>roughly</gloss><gloss>about</gloss></sense></entry>",
    "<entry><ent_seq>1432920</ent_seq><k_ele><keb>通り</keb></k_ele><r_ele><reb>とおり</reb></r_ele><sense><pos>&n;"
    "</pos><gloss>street</gloss><gloss>road</gloss></sense><sense><pos>&n;</pos><gloss>the same way (as)</gloss>"
    "<gloss>as (follows, stated, expected, etc.)</gloss></sense><sense><pos>&ctr;</pos><gloss>counter for sets of "
    "things</gloss></sense></entry>",
    # 元首相 'former prime minister': 元 read もと is first of all the prefix 'former' in one entry, 'origin' in another.
    "<entry><ent_seq>1912520</ent_seq><k_ele><keb>元首相</keb></k_ele><r_ele><reb>もとしゅしょう</reb></r_ele><sense>"
    "<pos>&n;</pos><gloss>former prime minister</gloss><gloss>former premier</gloss></sense></entry>",
    "<entry><ent_seq>2219590</ent_seq><k_ele><keb>元</keb></k_ele><k_ele><keb>旧</keb></k_ele><r_ele><reb>もと</reb>"
    "</r_ele><sense><pos>&adj-no;</pos><pos>&n-pref;</pos><gloss>former</gloss><gloss>ex-</gloss></sense><sense>"
    "<pos>&n;</pos><pos>&adv;</pos><gloss>formerly</gloss><gloss>previously</gloss></sense></entry>",
    "<entry><ent_seq>1260670</ent_seq><k_ele><keb>元</keb></k_ele><k_ele><keb>本</keb></k_ele><r_ele><reb>もと</reb>"
    "</r_ele><sense><pos>&n;</pos><gloss>origin</gloss><gloss>source</gloss></sense><sense><pos>&n;</pos><gloss>"
    "basis</gloss><gloss>foundation</gloss></sense></entry>",
    "<entry><ent_seq>1329300</ent_seq><k_ele><keb>首相</keb></k_ele><r_ele><reb>しゅしょう</reb></r_ele><sense><pos>"
    "&n;</pos><gloss>prime minister</gloss><gloss>premier</gloss></sense></entry>",
    "<entry><ent_seq>2513530</ent_seq><k_ele><keb>こと自体</keb></k_ele><k_ele><keb>事自体</keb></k_ele><r_ele><reb>"
    "ことじたい</reb></r_ele><sense><pos>&exp;</pos><gloss>(the thing) itself</gloss></sense></entry>",
    # Titles: もののけ姫 is only a film; 造幣局 is the Japan Mint and any mint; 仮面ライダー is read かめんライダー.
    "<entry><ent_seq>5741623</ent_seq><k_ele><keb>もののけ姫</keb></k_ele><r_ele><reb>もののけひめ</reb></r_ele>"
    "<sense><pos>&n;</pos><misc>&work;</misc><gloss>Princess Mononoke (1997 animated film)</gloss></sense></entry>",
    "<entry><ent_seq>2868630</ent_seq><k_ele><keb>造幣局</keb></k_ele><r_ele><reb>ぞうへいきょく</reb></r_ele><sense>"
    "<pos>&n;</pos><gloss>mint</gloss><gloss>mint bureau</gloss></sense></entry>",
    "<entry><ent_seq>5746881</ent_seq><k_ele><keb>造幣局</keb></k_ele><r_ele><reb>ぞうへいきょく</reb></r_ele><sense>"
    "<pos>&n;</pos><misc>&organization;</misc><gloss>Japan Mint</gloss></sense></entry>",
    "<entry><ent_seq>2859834</ent_seq><r_ele><reb>スラムダンク</reb></r_ele><r_ele><reb>スラム・ダンク</reb></r_ele>"
    "<sense><pos>&n;</pos><field>&sports;</field><gloss>slam dunk</gloss></sense></entry>",
    "<entry><ent_seq>5740914</ent_seq><r_ele><reb>スラムダンク</reb></r_ele><sense><pos>&n;</pos><misc>&work;</misc>"
    "<gloss>Slam Dunk (manga series)</gloss></sense></entry>",
    "<entry><ent_seq>5161027</ent_seq><k_ele><keb>仮面ライダー</keb></k_ele><r_ele><reb>かめんライダー</reb></r_ele>"
    "<sense><pos>&n;</pos><misc>&work;</misc><misc>&char;</misc><gloss>Kamen Rider (TV series, the titular "
    "character)</gloss></sense></entry>",
    "<entry><ent_seq>5008659</ent_seq><k_ele><keb>ｉＰｈｏｎｅ</keb></k_ele><r_ele><reb>アイフォーン</reb></r_ele>"
    "<r_ele><reb>アイフォン</reb></r_ele><sense><pos>&n;</pos><misc>&product;</misc><gloss>iPhone</gloss></sense>"
    "</entry>",
    # Words of their own, though a part is also a suffix (部, 会) or the whole is a noun JMdict lists.
    "<entry><ent_seq>2639980</ent_seq><k_ele><keb>上層部</keb></k_ele><r_ele><reb>じょうそうぶ</reb></r_ele><sense>"
    "<pos>&n;</pos><gloss>top brass</gloss><gloss>upper echelon</gloss></sense></entry>",
    "<entry><ent_seq>1353710</ent_seq><k_ele><keb>上層</keb></k_ele><r_ele><reb>じょうそう</reb></r_ele><sense><pos>"
    "&n;</pos><gloss>upper stratum (classes, stories, storeys)</gloss><gloss>upper layer</gloss></sense></entry>",
    "<entry><ent_seq>1379380</ent_seq><k_ele><keb>生徒</keb></k_ele><r_ele><reb>せいと</reb></r_ele><sense><pos>&n;"
    "</pos><gloss>pupil</gloss><gloss>student</gloss><gloss>schoolchild</gloss></sense></entry>",
    "<entry><ent_seq>1499290</ent_seq><k_ele><keb>部</keb></k_ele><r_ele><reb>ぶ</reb></r_ele><sense><pos>&n;</pos>"
    "<pos>&n-suf;</pos><gloss>department (in an organization, company, etc.)</gloss><gloss>division</gloss></sense>"
    "<sense><pos>&n;</pos><pos>&n-suf;</pos><gloss>club (at a school, university, etc.)</gloss><gloss>team</gloss>"
    "</sense></entry>",
    "<entry><ent_seq>1830290</ent_seq><k_ele><keb>生徒会</keb></k_ele><r_ele><reb>せいとかい</reb></r_ele><sense>"
    "<pos>&n;</pos><gloss>student council</gloss></sense></entry>",
    "<entry><ent_seq>1198170</ent_seq><k_ele><keb>会</keb></k_ele><r_ele><reb>かい</reb></r_ele><sense><pos>&n;</pos>"
    "<pos>&n-suf;</pos><gloss>meeting</gloss><gloss>assembly</gloss></sense><sense><pos>&n;</pos><pos>&n-suf;</pos>"
    "<gloss>society</gloss><gloss>association</gloss><gloss>club</gloss></sense></entry>",
    "<entry><ent_seq>1293250</ent_seq><k_ele><keb>再度確認</keb></k_ele><r_ele><reb>さいどかくにん</reb></r_ele>"
    "<sense><pos>&n;</pos><gloss>reconfirmation</gloss><gloss>double check</gloss></sense></entry>",
    # A prefix only where the word reads as its parts: 同世代 どう + せだい, but 仮初め is かりそめ.
    "<entry><ent_seq>2399340</ent_seq><k_ele><keb>同世代</keb></k_ele><r_ele><reb>どうせだい</reb></r_ele><sense>"
    "<pos>&n;</pos><gloss>same generation</gloss><gloss>one's generation</gloss></sense></entry>",
    "<entry><ent_seq>1451730</ent_seq><k_ele><keb>同</keb></k_ele><r_ele><reb>どう</reb></r_ele><sense><pos>&pref;"
    "</pos><gloss>the same</gloss><gloss>the said</gloss></sense><sense><pos>&unc;</pos><gloss>likewise</gloss>"
    "</sense></entry>",
    "<entry><ent_seq>1187590</ent_seq><k_ele><keb>仮初め</keb></k_ele><r_ele><reb>かりそめ</reb></r_ele><sense><pos>"
    "&adj-no;</pos><pos>&n;</pos><misc>&uk;</misc><gloss>temporary</gloss><gloss>transient</gloss></sense></entry>",
    "<entry><ent_seq>1187290</ent_seq><k_ele><keb>仮</keb></k_ele><k_ele><keb>仮り</keb><ke_inf>&io;</ke_inf>"
    "</k_ele><r_ele><reb>かり</reb></r_ele><sense><pos>&adj-no;</pos><pos>&pref;</pos><gloss>temporary</gloss>"
    "<gloss>provisional</gloss></sense><sense><pos>&adj-no;</pos><gloss>fictitious</gloss></sense></entry>",
    # A compound verb, and 打ち read うち, a prefix of emphasis.
    "<entry><ent_seq>1588130</ent_seq><k_ele><keb>打ち明ける</keb></k_ele><r_ele><reb>うちあける</reb></r_ele>"
    "<sense><pos>&v1;</pos><pos>&vt;</pos><gloss>to confide</gloss><gloss>to reveal</gloss></sense></entry>",
    "<entry><ent_seq>2859852</ent_seq><k_ele><keb>打ち</keb><ke_inf>&rK;</ke_inf></k_ele><r_ele><reb>ぶち</reb>"
    "</r_ele><r_ele><reb>うち</reb></r_ele><sense><pos>&pref;</pos><misc>&uk;</misc><gloss>adds emphasis to the "
    "following verb or indicates that the action is done forcefully or violently</gloss></sense></entry>",
    # An idiom, a sound word, a prenominal word and a loanword: units of their own, whatever JMdict calls them.
    "<entry><ent_seq>2453850</ent_seq><r_ele><reb>ぎくぎく</reb></r_ele><sense><pos>&adv;</pos><pos>&adv-to;</pos>"
    "<pos>&vs;</pos><misc>&on-mim;</misc><gloss>jerkily</gloss></sense></entry>",
    "<entry><ent_seq>2253780</ent_seq><k_ele><keb>心血管</keb></k_ele><r_ele><reb>しんけっかん</reb></r_ele><sense>"
    "<pos>&adj-f;</pos><gloss>cardiovascular</gloss></sense></entry>",
    "<entry><ent_seq>1431720</ent_seq><k_ele><keb>沈思黙考</keb></k_ele><r_ele><reb>ちんしもっこう</reb></r_ele>"
    "<sense><pos>&exp;</pos><misc>&yoji;</misc><gloss>being lost in deep thought</gloss></sense></entry>",
    "<entry><ent_seq>1048410</ent_seq><r_ele><reb>ゲームオーバー</reb></r_ele><sense>"
    "<pos>&exp;</pos><field>&vidg;</field><gloss>game over</gloss></sense></entry>",
    # Katakana names JMdict lists: フジテレビ as written, エア・タヒチ only with its ・.
    "<entry><ent_seq>5070153</ent_seq><r_ele><reb>フジテレビ</reb></r_ele><sense><pos>&n;</pos><misc>&company;</misc>"
    "<gloss>Fuji Television</gloss><gloss>Fuji TV</gloss></sense></entry>",
    "<entry><ent_seq>5016608</ent_seq><r_ele><reb>エア・タヒチ</reb></r_ele><sense><pos>&n;</pos><misc>&company;</misc>"
    "<gloss>Air Tahiti</gloss></sense></entry>",
    # お / ご words and their bare words.
    "<entry><ent_seq>1612780</ent_seq><k_ele><keb>お帰り</keb></k_ele><k_ele><keb>御帰り</keb><ke_inf>&sK;</ke_inf>"
    "</k_ele><r_ele><reb>おかえり</reb></r_ele><sense><pos>&n;</pos><misc>&hon;</misc><gloss>return</gloss></sense>"
    "<sense><pos>&int;</pos><xref>お帰りなさい</xref><misc>&abbr;</misc><gloss>welcome home</gloss></sense></entry>",
    "<entry><ent_seq>1221250</ent_seq><k_ele><keb>帰り</keb></k_ele><r_ele><reb>かえり</reb></r_ele><sense><pos>&n;"
    "</pos><gloss>return</gloss><gloss>coming back</gloss></sense></entry>",
    "<entry><ent_seq>2453580</ent_seq><k_ele><keb>お部屋</keb></k_ele><k_ele><keb>御部屋</keb></k_ele><r_ele><reb>"
    "おへや</reb></r_ele><sense><pos>&n;</pos><xref>部屋・1</xref><misc>&pol;</misc><gloss>room</gloss></sense><sense>"
    "<pos>&n;</pos><misc>&pol;</misc><gloss>apartment</gloss><gloss>flat</gloss></sense></entry>",
    "<entry><ent_seq>1499320</ent_seq><k_ele><keb>部屋</keb></k_ele><r_ele><reb>へや</reb></r_ele><sense><pos>&n;"
    "</pos><gloss>room</gloss><gloss>chamber</gloss></sense><sense><pos>&n;</pos><gloss>apartment</gloss><gloss>flat"
    "</gloss></sense></entry>",
    "<entry><ent_seq>1270380</ent_seq><k_ele><keb>御社</keb></k_ele><r_ele><reb>おんしゃ</reb></r_ele><sense><pos>"
    "&n;</pos><misc>&hon;</misc><gloss>your company</gloss></sense><sense><pos>&n;</pos><misc>&hon;</misc><gloss>"
    "your shrine</gloss></sense></entry>",
    "<entry><ent_seq>2015400</ent_seq><k_ele><keb>社</keb></k_ele><r_ele><reb>しゃ</reb></r_ele><sense><pos>&n;"
    "</pos><misc>&abbr;</misc><gloss>company</gloss><gloss>firm</gloss></sense><sense><pos>&ctr;</pos><gloss>"
    "counter for companies, shrines, etc.</gloss></sense></entry>",
    "<entry><ent_seq>1002100</ent_seq><k_ele><keb>お手洗い</keb></k_ele><k_ele><keb>御手洗</keb></k_ele><r_ele><reb>"
    "おてあらい</reb></r_ele><sense><pos>&n;</pos><gloss>toilet</gloss><gloss>restroom</gloss><gloss>lavatory</gloss>"
    "</sense></entry>",
    "<entry><ent_seq>1328020</ent_seq><k_ele><keb>手洗い</keb></k_ele><r_ele><reb>てあらい</reb></r_ele><sense><pos>"
    "&n;</pos><gloss>washing one's hands</gloss></sense><sense><pos>&n;</pos><xref>お手洗い</xref><gloss>restroom"
    "</gloss><gloss>lavatory</gloss><gloss>toilet</gloss></sense></entry>",
    "<entry><ent_seq>2803760</ent_seq><k_ele><keb>ご縁</keb></k_ele><k_ele><keb>御縁</keb></k_ele><r_ele><reb>ごえん"
    "</reb></r_ele><sense><pos>&n;</pos><misc>&pol;</misc><gloss>fate</gloss><gloss>chance</gloss></sense><sense>"
    "<pos>&n;</pos><misc>&pol;</misc><gloss>relationship</gloss><gloss>tie</gloss></sense></entry>",
    "<entry><ent_seq>1177490</ent_seq><k_ele><keb>縁</keb></k_ele><r_ele><reb>えん</reb></r_ele><sense><pos>&n;"
    "</pos><gloss>fate</gloss><gloss>destiny</gloss></sense><sense><pos>&n;</pos><gloss>relationship</gloss><gloss>"
    "bond</gloss></sense></entry>",
    "<entry><ent_seq>2125960</ent_seq><k_ele><keb>誤嚥</keb></k_ele><r_ele><reb>ごえん</reb></r_ele><sense><pos>&n;"
    "</pos><pos>&vs;</pos><field>&med;</field><gloss>breathing in (of a foreign body, food, etc.)</gloss><gloss>"
    "pulmonary aspiration</gloss></sense></entry>",
]


def _module():
    """scripts/jmdict_flags.py — it runs at build time and never ships, so it is no package."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "jmdict_flags.py")
    spec = importlib.util.spec_from_file_location("jmdict_flags", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


jf = _module()


def _write(path, entries=_ENTRIES, newline="\n"):
    text = (_DTD + "\n".join(entries) + "\n</JMdict>\n").replace("\n", newline)
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "wb") as f:
        f.write(text.encode("utf-8"))
    return str(path)


@pytest.fixture(scope="module")
def entries(tmp_path_factory):
    return jf.load(_write(tmp_path_factory.mktemp("jmdict") / "JMdict_e.gz"))


def _compound(reading, *parts):
    """One entry of the compound table: [lemma, reading, kind, flags, parts], parts [lemma, reading, free]."""
    return ["", reading, "N", 0, [[lemma, read, 1] for lemma, read in parts]]


COMPOUNDS = {
    "予想通り": _compound("ヨソウドオリ", ("予想", "ヨソウ"), ("通り", "トオリ")),
    "こと自体": _compound("コトジタイ", ("事", "コト"), ("自体", "ジタイ")),
    "元首相": _compound("モトシュショウ", ("元", "モト"), ("首相", "シュショウ")),
    "もののけ姫": _compound("モノノケヒメ", ("物の怪", "モノノケ"), ("姫", "ヒメ")),
    "仮面ライダー": _compound("カメンライダー", ("仮面", "カメン"), ("ライダー", "ライダー")),
    "スラムダンク": _compound("スラムダンク", ("スラム", "スラム"), ("ダンク", "ダンク")),
    "造幣局": _compound("ゾウヘイキョク", ("造幣", "ゾウヘイ"), ("局", "キョク")),
    "アイフォン": _compound("アイフォン", ("アイ", "アイ"), ("フォン", "フォン")),
    "上層部": _compound("ジョウソウブ", ("上層", "ジョウソウ"), ("部", "ブ")),
    "生徒会": _compound("セイトカイ", ("生徒", "セイト"), ("会", "カイ")),
    "再度確認": _compound("サイドカクニン", ("再度", "サイド"), ("確認", "カクニン")),
    "秘密結社": _compound("ヒミツケッシャ", ("秘密", "ヒミツ"), ("結社", "ケッシャ")),
    "同世代": _compound("ドウセダイ", ("同", "ドウ"), ("世代", "セダイ")),
    "仮初め": _compound("カリソメ", ("仮", "カリ"), ("初め", "ハジメ")),
    "沈思黙考": _compound("チンシモッコウ", ("沈思", "チンシ"), ("黙考", "モッコウ")),
    "ゲームオーバー": _compound("ゲームオーバー", ("ゲーム", "ゲーム"), ("オーバー", "オーバー")),
    "打ち明ける": ["", "ウチアケル", "V", 0, [["打ち", "ウチ", 1], ["明ける", "アケル", 1]]],
    "ぎくぎく": _compound("ギクギク", ("ぎく", "ギク"), ("ぎく", "ギク")),
    "心血管": _compound("シンケッカン", ("心", "シン"), ("血管", "ケッカン")),
}


def test_the_dictionary_reads_the_same_plain_or_gzipped_with_either_line_ending(tmp_path, entries):
    # The build reads JMdict_e.gz as the EDRDG ships it; an unpacked .xml (a Windows copy with CRLF) reads the same.
    plain = jf.load(_write(tmp_path / "JMdict_e.xml", newline="\r\n"))
    assert len(plain) == len(entries) == len(_ENTRIES)
    assert jf.created(_write(tmp_path / "again.gz")) == "2026-09-28"
    # Tags come back by their entity names, the way JMdict's documentation writes them.
    welcome = next(e for e in plain if e["seq"] == 1612780)
    assert [(s["pos"], s["misc"], s["gloss"]) for s in welcome["senses"]] == [
        (("n",), ("hon",), ("return",)), (("int",), ("abbr",), ("welcome home",))]
    assert welcome["kanji"][1] == ("御帰り", (), ("sK",))


def test_a_missing_dictionary_raises_so_the_build_can_report_what_it_skipped(tmp_path):
    # The build checks for the file and prints what it leaves out; a wrong path must never read as "no flags".
    with pytest.raises(FileNotFoundError):
        jf.load(str(tmp_path / "JMdict_e.gz"))


def test_the_four_examples_the_settings_switch_names_are_fringe(entries):
    # The tooltip promises these four split when the switch is off. Each is fringe for its own reason:
    # 予想通り and こと自体 are listed only as an adverb / an expression, 元首相 starts with the prefix 元 'former',
    # and もののけ姫 is only a film's name (a title is fringe too: 3 = fringe + title).
    flags = jf.fringe(entries, COMPOUNDS)
    assert {w: flags.get(w) for w in ("予想通り", "こと自体", "元首相", "もののけ姫")} == {
        "予想通り": 1, "こと自体": 1, "元首相": 1, "もののけ姫": 3}
    idx = jf.index(entries)
    assert [jf.fringe_class(idx, w, COMPOUNDS[w][1], COMPOUNDS[w][4])
            for w in ("予想通り", "こと自体", "元首相", "もののけ姫")] == ["phrase", "phrase", "prefix", "title"]


def test_words_of_their_own_are_never_fringe(entries):
    # 上層部 and 生徒会 are nouns JMdict lists, though 部 and 会 are also suffixes (and 上層, 生徒 are nouns, no
    # prefixes); 再度確認 is a noun in JMdict
    # ('reconfirmation') and joins like any compound; 秘密結社 isn't in this dictionary at all — no entry is no
    # reason to split a word.
    flags = jf.fringe(entries, COMPOUNDS)
    for word in ("上層部", "生徒会", "再度確認", "秘密結社"):
        assert word not in flags, word


def test_a_title_is_a_spelling_jmdict_knows_only_as_a_name(entries):
    # 造幣局 names the Japan Mint, but it is also any mint: it stays one word either way (so does スラムダンク, a
    # manga and the basketball word — a loanword besides). 仮面ライダー's JMdict reading mixes the scripts
    # (かめんライダー) and still meets the list's カメンライダー.
    flags = jf.fringe(entries, COMPOUNDS)
    assert "造幣局" not in flags and "スラムダンク" not in flags
    assert flags["仮面ライダー"] == 3


def test_an_idiom_and_a_loanword_stay_whole(entries):
    # 沈思黙考 is an expression JMdict marks as a four-character idiom — a unit of meaning. A loanword's parts are
    # pieces of a foreign word (ゲーム + オーバー, アイ + フォン), never fringe, whatever JMdict calls the whole:
    # an expression, or a product whose other form (ｉＰｈｏｎｅ) holds no kanji.
    flags = jf.fringe(entries, COMPOUNDS)
    for word in ("沈思黙考", "ゲームオーバー", "アイフォン"):
        assert word not in flags, word


def test_a_sound_word_and_a_prenominal_word_are_no_phrases(entries):
    # JMdict lists neither as a noun, but ぎくぎく 'jerkily' is a sound word (a unit of its own) and 心血管
    # 'cardiovascular' a word used only before a noun — not the way a phrase is used.
    flags = jf.fringe(entries, COMPOUNDS)
    assert "ぎくぎく" not in flags and "心血管" not in flags


def test_a_compound_verb_is_never_fringe(entries):
    # JMdict lists 打ち明ける 'to confide' as a verb — never a noun — and 打ち is first of all a prefix of emphasis;
    # a verb is a word all the same, never a phrase or a title the switch would split.
    assert "打ち明ける" not in jf.fringe(entries, COMPOUNDS)


def test_a_prefix_makes_a_phrase_only_where_the_word_reads_as_its_parts(entries):
    # 同 is first of all the prefix 'the same', so 同世代 is 同 + 世代. 仮 is a prefix too, but 仮初め reads かりそめ,
    # not かり + はじめ: a word of its own reading.
    flags = jf.fringe(entries, COMPOUNDS)
    assert flags.get("同世代") == 1
    assert "仮初め" not in flags


def test_a_katakana_compound_jmdict_does_not_list_is_marked_to_give_way_to_a_name(entries):
    # ビルデ (ビル + デ) is no word of JMdict's: a piece of a foreign name the frequency lists carry in their tails, so
    # it gives way to a katakana name around it (ビルデイング). フジテレビ and the loanwords are listed — エア・タヒチ
    # only with its ・, the same word — and 秘密結社, missing from this dictionary, is no katakana word: none is marked.
    compounds = dict(COMPOUNDS, ビルデ=_compound("ビルデ", ("ビル", "ビル"), ("デ", "デ")),
                     フジテレビ=_compound("フジテレビ", ("フジ", "フジ"), ("テレビ", "テレビ")),
                     エアタヒチ=_compound("エアタヒチ", ("エア", "エア"), ("タヒチ", "タヒチ")))
    assert jf.unlisted(entries, compounds) == {"ビルデ": 4}
    # the mark is never fringe: the "Phrases and titles" switch (flags & 1) never reads it
    assert not jf.UNLISTED & jf.FRINGE and not set(jf.unlisted(entries, compounds)) & set(jf.fringe(entries, compounds))


def test_omamori_joins_because_the_bare_words_amulet_sense_is_its_abbreviation(entries):
    # 守り read まもり has the sense 'amulet' too, marked as an abbreviation: it is お守り shortened, so it doesn't
    # count against the お word. Every spelling of the word comes back with the lemma and reading it was given.
    candidates = {"お守り": ["お守り", "オマモリ"], "おまもり": ["お守り", "オマモリ"], "御守り": ["お守り", "オマモリ"]}
    assert jf.ogo_exceptions(entries, candidates) == candidates


def test_the_reading_decides_which_word_a_spelling_is(entries):
    # お守り read おもり is another word, 'babysitting', weighed against 守り read もり: the reading picks the entries.
    idx = jf.index(entries)
    own, word, bare = jf.own_senses(idx, ["お守り"], {"お守り": "オマモリ"})
    assert ([e["seq"] for e in word], [e["seq"] for e in bare], own[0]["gloss"][:2]) == (
        [1002060], [1327100], ("charm", "amulet"))
    own, word, bare = jf.own_senses(idx, ["お守り"], {"お守り": "オモリ"})
    assert ([e["seq"] for e in word], [e["seq"] for e in bare], [s["gloss"][0] for s in own]) == (
        [2268160], [1327090], ["taking care of"])


def test_okaeri_joins_with_every_spelling_of_the_word(entries):
    # お帰り's 'return' is only honorific, but 'welcome home' is a meaning 帰り lacks.
    candidates = {"お帰り": ["お帰り", "オカエリ"], "おかえり": ["お帰り", "オカエリ"], "御帰り": ["お帰り", "オカエリ"]}
    assert jf.ogo_exceptions(entries, candidates) == candidates


def test_polite_words_and_shared_meanings_stay_a_prefix_and_a_word(entries):
    # お部屋 is only the polite 'room'; 御社 only the honorific 'your company'; お手洗い 'toilet' is what 手洗い means
    # too; お名前 isn't in this dictionary at all.
    candidates = {"お部屋": ["お部屋", "オヘヤ"], "御部屋": ["お部屋", "オヘヤ"], "御社": ["御社", "オンシャ"],
                  "お手洗い": ["お手洗い", "オテアライ"], "お名前": ["お名前", "オナマエ"]}
    assert jf.ogo_exceptions(entries, candidates) == {}


def test_a_kana_spelling_is_decided_by_its_own_word_not_a_homophone(entries):
    # ごえん is also 誤嚥 'aspiration', a meaning 縁 lacks — but it is ご縁 here, which is only the polite 'fate'.
    candidates = {"ご縁": ["ご縁", "ゴエン"], "ごえん": ["ご縁", "ゴエン"], "御縁": ["ご縁", "ゴエン"]}
    assert jf.ogo_exceptions(entries, candidates) == {}


def test_nothing_to_read_flags_nothing(entries):
    # Empty inputs, or a dictionary with no entries, give empty tables — never an error.
    assert jf.fringe(entries, {}) == {}
    assert jf.unlisted(entries, {}) == {}
    assert jf.ogo_exceptions(entries, {}) == {}
    assert jf.fringe([], COMPOUNDS) == {}
    assert jf.ogo_exceptions([], {"お守り": ["お守り", "オマモリ"]}) == {}


def test_the_report_lists_the_fringe_and_the_polite_words_for_the_user(tmp_path, entries):
    candidates = {"お守り": ["お守り", "オマモリ"], "お部屋": ["お部屋", "オヘヤ"]}
    path = jf.report(entries, COMPOUNDS, candidates, str(tmp_path / "flags.md"), _write(tmp_path / "j.xml"))
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "JMdict created 2026-09-28" in text
    assert "| もののけ姫 | モノノケヒメ |" in text and "| 予想通り | ヨソウドオリ |" in text
    assert "| お守り | charm; amulet (n) |" in text
    assert "| お部屋 | every sense is the polite / honorific / humble word" in text

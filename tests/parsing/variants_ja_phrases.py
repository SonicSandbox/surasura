"""Prototype rules for the set phrases on the list (PHRASE-ROWS) — what the switch and the bound-word rule decide.

    phrase-rows-off         Settings' "Idioms and set phrases on your list" off: no phrase is read anywhere — the
                            frozen settings gain phrase_rows false (Junban's layer reads it), the token store's
                            reader says off, and the matcher holds no phrase.
    phrase-bound-additive   Q3 (b), the other side of the decision: no word lives only inside its phrase — every word
                            keeps every use, and a word the phrase holds that the learner doesn't know is waited for
                            like any other (腑に落ちる waits for 腑 — or would, but 腑 is one character).
    phrase-prenoun-off      no pre-noun rule: a phrase JMdict classes only as a pre-noun adjectival (ああいう,
                            こういう, 罪なき) is found wherever its words stand, ああ言って 'say so' and an
                            inflected 罪なく too.
    phrase-prenoun-kana-off the pre-noun rule without its kana half: a pre-noun phrase JMdict says is usually written
                            in kana (そういった, どういう) is found written with the verb's kanji too — そう言ったのは
                            'that he said so' as そういった.
"""
from tests.parsing import harness
from tests.parsing.harness import patched
from tests.parsing.variants import variant


@variant("phrase-rows-off",
         "The switch off: no set phrase is found, placed or waited for (the list as it was before phrase rows).")
def _phrase_rows_off():
    from app import phrases, token_index
    real = harness.frozen_logic
    with patched(harness, "frozen_logic", lambda: dict(real(), phrase_rows=False)), \
            patched(token_index, "phrase_rows_on", lambda language: False), \
            patched(phrases, "load", lambda: phrases.PhraseSet([])):
        yield


@variant("phrase-bound-additive",
         "Q3 (b): no word lives only inside its phrase — 眉根 in 眉根を寄せる is waited for like any new word, and "
         "every word keeps its uses inside its phrase.")
def _phrase_bound_additive():
    from app import phrases
    shipped = phrases.load()
    plain = phrases.PhraseSet([p._replace(roles=p.roles.replace("b", "c")) for p in shipped.entries])
    with patched(phrases, "load", lambda: plain):
        yield


@variant("phrase-prenoun-off",
         "No pre-noun rule: ああいう, こういう and 罪なき are found wherever their words stand — ああ言って 'say so' "
         "and an inflected 罪なく too.")
def _phrase_prenoun_off():
    from app import phrases
    shipped = phrases.load()
    plain = phrases.PhraseSet([p._replace(prenoun=False) for p in shipped.entries])
    with patched(phrases, "load", lambda: plain):
        yield


@variant("phrase-prenoun-kana-off",
         "The pre-noun rule without its kana half: そういった and どういう are found written with the verb's kanji too "
         "— そう言ったのは 'that he said so' as そういった, and どう言う意味 found again.")
def _phrase_prenoun_kana_off():
    from app import phrases
    shipped = phrases.load()
    plain = phrases.PhraseSet([p._replace(prenoun=min(p.prenoun, 1)) for p in shipped.entries])
    with patched(phrases, "load", lambda: plain):
        yield

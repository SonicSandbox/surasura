"""Practice with your own AI (H9, Sonic 2026-10-28): the checker the learner's AI calls on every draft it writes.

The AI writes a short reply in the learner's language; `Checker.check` reads it as the list reads a library — Japanese
through the tokenizer (`join_affixes`, `word_lemma`, the names layers), the one-character rule (`analyzer.unoffered`)
and `LearningView` (a word read through its known word, a compound of known parts, a rare compound as its parts);
Chinese through `chinese_cut` / `chinese_word` in the library's script — against the words the list counts as known
(KnownWord.json, the Ignore, Blacklist and Graduated lists, KnownWord.json's IGNORED entries). No rule of its own about
what a word is: it only counts.

What a reply may bring in (Sonic, P-1), by mode:
- `chat`: at most one new word in the reply, and only in a sentence where every other word is known;
- `reading` (a story, a longer reading): at most one new word in any sentence, new words under 3 % of the words.
A new word must be one of the learner's upcoming words (the top of their list) or an easy common noun (`easy_noun`).

A Checker loads once — the tagger, the join tables, the known words — and checks a reply in a few milliseconds; the
MCP server (app/cli/mcp_server.py) keeps one per language for its session. Reads only: nothing is written anywhere.
`tests/test_practice.py`.
"""
import json
import os

MODES = ("chat", "reading")
READING_SHARE = 0.03            # a reading's new words: under 3 % of its words (Sonic, P-1)
RECENT = 100                    # the newest known words, the ones a round uses first
# An easy common noun (PROVISIONAL technical rule, scope.md): ja — UniDic's 普通名詞 ranked in the top EASY_JA_RANK
# of spoken Japanese (reference_data.spoken_ranks: TMW Netflix + Anime & J-drama); zh — jieba's tag `n` among its own
# top EASY_ZH_RANK words by count.
EASY_JA_RANK = 5000
EASY_ZH_RANK = 5000


def _known_file(language):
    from app.path_utils import get_user_files_path
    return os.path.join(get_user_files_path(language), "KnownWord.json")


def recent_terms(path, language, limit=RECENT):
    """KnownWord.json's known words, newest first by `created` (each Anki sync stamps the words it adds), at most
    `limit`. An entry without a date is never among them; a file that can't be read gives none."""
    from app.path_utils import read_text
    try:
        data = json.loads(read_text(path, language))
    except (OSError, ValueError):
        return []
    entries = data.get("words", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    dated = []
    for e in entries:
        if (isinstance(e, dict) and (e.get("knownStatus") == "KNOWN" or e.get("hasCard") == 1)
                and isinstance(e.get("dictForm"), str) and e["dictForm"].strip()):
            when = _created_ms(e.get("created"))
            if when:
                dated.append((when, e["dictForm"]))
    dated.sort(key=lambda pair: pair[0], reverse=True)
    return [term for _created, term in dated[:limit]]


def _created_ms(value):
    """An entry's `created` as milliseconds since 1970: Surasura's Anki sync writes an ISO time, Migaku's export a
    number of milliseconds (0 when unknown). None when there is none."""
    from datetime import datetime
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip()).timestamp() * 1000
        except ValueError:
            return None
    return None


class Checker:
    """The learner's words for `language`, read once. `upcoming`: the (lemma, reading)s of the learner's next words
    (the top of their list) — the new words a reply may bring in besides easy nouns. `settings` defaults to
    settings.json as a run reads it; `known` ((known_tuples, known_lemmas, ignore)) and `library` ((uses, floor), the
    last Generate's counts) are for tests and callers that hold them already."""

    def __init__(self, language, upcoming=(), settings=None, known=None, library=None, recent=None):
        from app import analyzer, settings_manager, zh_script
        if language not in ("ja", "zh"):
            raise ValueError("language must be ja or zh")
        self.language = language
        settings = settings_manager.load_settings() if settings is None else settings
        analyzer.SANITIZE_JA = language == "ja"            # as every run sets it, before known words are read
        self.japanese = language == "ja"
        self.rule = self.japanese and bool(settings.get("exclude_single", True))
        self.script = zh_script.effective(language, settings.get("zh_script", "asis"))
        if self.japanese:
            self.tokenizer = analyzer.JapaneseTokenizer()
        else:
            self.tokenizer = analyzer.ChineseTokenizer(script=self.script)
        self.known_path = _known_file(language)
        self._known_sets = known
        self._library = library
        self._recent_given = recent
        self.upcoming = set(upcoming or ())
        self._easy = {}
        self._signature = None
        self._load()
        # Paid here, once: the tagger's first call and the tables an easy-noun ask reads.
        if self.japanese:
            from app import reference_data
            reference_data.spoken_ranks()
        else:
            _zh_tag("人")
            _zh_rank("人")
        self.check("ok")

    # --- loading ---------------------------------------------------------------------------------------------- #
    def _load(self):
        from app import analyzer
        if self._known_sets is None:
            known_tuples, known_lemmas = analyzer.load_known_words(self.known_path, self.tokenizer)
            ignore = analyzer.load_ignore_set(os.path.dirname(self.known_path), self.script, self.language)
        else:
            known_tuples, known_lemmas, ignore = self._known_sets
        self.known_tuples, self.known_lemmas, self.ignore = set(known_tuples), set(known_lemmas), set(ignore)
        terms = recent_terms(self.known_path, self.language) if self._recent_given is None else self._recent_given
        self.recent_terms = list(terms)
        self.recent = {}                                    # (lemma, reading) -> its place, 0 the newest
        for at, term in enumerate(terms):
            for lemma, reading, _surface, _orth in self.tokenizer.tokenize(term):
                self.recent.setdefault((lemma, reading), at)
        library = self._library
        if library is None and self.japanese:
            from app import sentence_corpus
            try:
                library = sentence_corpus.library_counts(self.language)
            except Exception:
                library = None
        self.view = analyzer.LearningView(*(library or (None, 0)), known=self._is_listed_known,
                                          parts=analyzer.compound_parts() if self.japanese else {},
                                          joins=analyzer.affix_joins() if self.japanese else {},
                                          tagger=self.tokenizer.tagger if self.japanese else None)
        self._memo = {}
        self._signature = self._stat()

    def _stat(self):
        try:
            st = os.stat(self.known_path)
            return st.st_mtime_ns, st.st_size
        except OSError:
            return None

    def refresh(self):
        """Read the known words again when KnownWord.json changed (a sync mid-session); a stat when it didn't."""
        if self._known_sets is None and self._stat() != self._signature:
            self._load()

    def recent_words(self, limit=RECENT):
        """The newest known words as the learner wrote them, newest first."""
        return self.recent_terms[:limit]

    # --- the rules -------------------------------------------------------------------------------------------- #
    def _is_listed_known(self, key):
        return key[0] in self.ignore or key[0] in self.known_lemmas or key in self.known_tuples

    def _known(self, key):
        found = self._memo.get(key)
        if found is None:
            found = self._memo[key] = self._is_listed_known(key) or self.view.readable(key)
        return found

    def easy_noun(self, key, orth):
        """Is `key` an easy common noun (EASY_JA_RANK / EASY_ZH_RANK above)? Asked once per word."""
        found = self._easy.get(key)
        if found is None:
            found = self._easy[key] = self._easy_ja(key, orth) if self.japanese else self._easy_zh(key)
        return found

    def _easy_ja(self, key, orth):
        from app import reference_data
        rank = reference_data.spoken_ranks().get(key[0]) or 0
        if not 0 < rank <= EASY_JA_RANK:
            return False
        nodes = self.tokenizer.tagger(orth)
        return len(nodes) == 1 and nodes[0].feature.pos1 == "名詞" and nodes[0].feature.pos2 == "普通名詞"

    def _easy_zh(self, key):
        from app import zh_script
        word = zh_script.to_simplified(key[0])
        return _zh_tag(word) == "n" and _zh_rank(word) <= EASY_ZH_RANK

    # --- the check -------------------------------------------------------------------------------------------- #
    def check(self, text, mode="chat"):
        """The verdict on `text` in `mode` (MODES) -> {"pass", "reasons", "sentences", "new_words", "new_share",
        "words", "known_used", "recent_used"}. `reasons` are instructions in plain words, empty on a pass."""
        from app import analyzer
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        sentences, new_words, known_used, recent_used = [], {}, {}, {}
        counted = new_uses = 0
        lang = self.language
        for s_text, tokens in self.tokenizer.tokenize_sentences(str(text or "").replace("\r\n", "\n")):
            skip = analyzer.unoffered(s_text, tokens) if self.rule else ()
            present = {}
            for t_no, (lemma, reading, surface, orth) in enumerate(tokens):
                if not (analyzer.has_target_language(lemma, lang) or analyzer.has_target_language(surface, lang)):
                    continue        # markup, numbers, ASCII — never a word (the list skips them too)
                if t_no in skip:
                    continue        # a one-character word the list can't offer here: nothing to learn
                counted += 1
                key = (lemma, reading)
                present.setdefault(key, orth or surface)
                if self._known(key):
                    known_used.setdefault(key, orth or surface)
                    if key in self.recent:
                        recent_used.setdefault(key, orth or surface)
                else:
                    new_uses += 1
            if any(key in self.view.parts and self.view.rare(key) for key in present):
                # a rare compound counts as its parts, as in the report (never its own parts against itself)
                units = {unit for key in present for unit in self.view.units(key)}
                new = [unit for unit in units if not self._known(unit) and analyzer.single_kind(unit, self.rule) != 1]
                new = [(unit, present.get(unit, unit[0])) for unit in new]
            else:
                new = [(key, shown) for key, shown in present.items() if not self._known(key)]
            entry = []
            for key, shown in new:
                why = ("upcoming" if key in self.upcoming else "easy noun" if self.easy_noun(key, shown) else None)
                word = {"word": shown, "lemma": key[0], "reading": key[1], "allowed": why is not None,
                        "why": why or "not on the learner's upcoming list and not an easy common noun"}
                entry.append(word)
                new_words.setdefault(key, word)
            sentences.append({"text": s_text, "new": entry})
        share = (new_uses / counted) if counted else 0.0
        reasons = self._reasons(mode, sentences, new_words, share)
        return {"pass": not reasons, "reasons": reasons, "mode": mode, "sentences": sentences,
                "new_words": list(new_words.values()), "new_share": round(share, 4), "words": counted,
                "known_used": len(known_used), "recent_used": [shown for _key, shown in
                                                               sorted(recent_used.items(),
                                                                      key=lambda kv: self.recent[kv[0]])]}

    @staticmethod
    def _reasons(mode, sentences, new_words, share):
        reasons = []
        if not any(s["text"] for s in sentences):
            return ["There is no Japanese or Chinese text to check. Write the reply in the learner's language."]
        for no, sentence in enumerate(sentences, 1):
            new = sentence["new"]
            if len(new) > 1:
                names = "、".join(w["word"] for w in new)
                reasons.append(f"Sentence {no} has {len(new)} words the learner doesn't know ({names}). Keep at most "
                               f"one: replace {new[-1]['word']} with a word they know, or split the sentence.")
        for word in new_words.values():
            if not word["allowed"]:
                reasons.append(f"{word['word']} is new to the learner and isn't one of their upcoming words or an "
                               f"easy everyday noun. Replace it with a word they know.")
        if mode == "chat" and len(new_words) > 1:
            names = "、".join(w["word"] for w in new_words.values())
            reasons.append(f"A chat reply may bring in one new word; this one has {len(new_words)} ({names}). Keep "
                           f"the one that matters most and replace the others with words they know.")
        if mode == "reading" and share >= READING_SHARE:
            reasons.append(f"New words are {share:.1%} of this reading; keep them under {READING_SHARE:.0%}. Replace "
                           f"some with words the learner knows, or make the reading longer with known words.")
        return reasons


# --- Chinese: jieba's own tags and counts, read once (analyzer.chinese_verb reads the same table) ---------------- #
_ZH_RANKS = {}


def _zh_tag(word):
    from app import analyzer
    analyzer.chinese_verb(word)                      # loads analyzer._ZH_TAGS once
    return str((analyzer._ZH_TAGS[0] if analyzer._ZH_TAGS else {}).get(word) or "")


def _zh_rank(word):
    """`word`'s place among jieba's dictionary words by count, 1 the commonest; a word it lacks is past every rank."""
    if not _ZH_RANKS:
        import jieba
        jieba.dt.check_initialized()
        top = sorted(((count, w) for w, count in jieba.dt.FREQ.items() if count > 0), reverse=True)
        _ZH_RANKS.update((w, at) for at, (_count, w) in enumerate(top[:EASY_ZH_RANK * 2], 1))
    return _ZH_RANKS.get(word, EASY_ZH_RANK * 2 + 1)


_CHECKERS = {}


def check_text(text, language, mode="chat", upcoming=None):
    """`Checker.check` on a Checker kept for `language` (made on the first call; `upcoming` replaces its upcoming
    words when given) — re-reading the known words when KnownWord.json changed."""
    checker = _CHECKERS.get(language)
    if checker is None:
        checker = _CHECKERS[language] = Checker(language, upcoming or ())
    else:
        checker.refresh()
        if upcoming is not None:
            checker.upcoming = set(upcoming)
    return checker.check(text, mode)

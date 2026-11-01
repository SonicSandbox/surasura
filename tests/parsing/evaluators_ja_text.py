"""Layers for text reading (cases_ja_text.py) — the paths a file takes besides the token store's.

The core `text` layer (evaluators.py) reads a file the way the token store does: analyzer.extract_text, then
tokenize_sentences. Three more paths decide what a file contributes, and each runs the app's own code:

    layer           text is                                 expect keys
    text_scan       a file dropped into a tier folder       read + the text layer's keys
    text_report     a file (as the text layer takes it)     the text layer's keys (sentences as the report shows)
    text_extract    a file the Content Manager's Extract    the text layer's keys
                    converts (.epub: its chapter's XHTML;
                    .srt / .ass / .txt as the file holds it)
    user_file       a file the user keeps in User Files/    error, has, hasnt
                    (a word list, KnownWord.json, a
                    frequency list) as their editor saved it
"""
import dataclasses
import io
import os
import zipfile
from unittest import mock

from app import analyzer, path_utils, settings_manager
from tests.parsing import evaluators, harness
from tests.parsing.harness import EVALUATORS, evaluator

_TEXT_KEYS = ("sentences", "contains", "not_contains", "words", "not_words")


def _file_name(case):
    """The file's name as the text layer writes it (ctx: name, else "case" + ext)."""
    return case.ctx.get("name") or "case" + case.ctx.get("ext", ".txt")


def _show_text(observed):
    return EVALUATORS["text"].show(observed)


# --- text_scan ---------------------------------------------------------------------------------------------- #
def _compare_scan(observed, expect):
    problems = []
    if "read" in expect and expect["read"] != observed["read"]:
        problems.append(f"read: expected {expect['read']}, got {observed['read']}")
    return problems + evaluators.compare_text(observed, {k: v for k, v in expect.items() if k != "read"})


@evaluator("text_scan", expects=("read",) + _TEXT_KEYS, compare=_compare_scan,
           show=lambda observed: _show_text(observed) if observed["read"] else "(not read)")
def text_scan(case, ctx):
    """A file dropped into a tier folder, as a run finds it: the analyzer's scan — and the indexer and the
    Content Manager, which share path_utils.CONTENT_EXTENSIONS — takes a file only when is_content_file accepts
    its name (ctx: name, else "case" + ext). A file it takes is read the text layer's way; one it skips
    contributes nothing. -> {"read", "sentences", "words"}."""
    if not path_utils.is_content_file(_file_name(case)):
        return {"read": False, "sentences": [], "words": []}
    return dict(evaluators.text(case, ctx), read=True)


# --- text_report -------------------------------------------------------------------------------------------- #
@evaluator("text_report", expects=_TEXT_KEYS, compare=evaluators.compare_text, show=_show_text)
def text_report(case, ctx):
    """The file's sentences as the report shows them as examples (a list's Context columns): the text layer's
    sentences, each finished as analyzer.main finishes a Japanese context — stripped, then strip_verse_number with
    the run's tagger (a verse number before the sentence goes; a number that counts something stays). Display
    only: the words are the text layer's, what the run counts."""
    observed = evaluators.text(case, ctx)
    sentences = [sentence.strip() for sentence in observed["sentences"]]
    if case.lang == "ja":
        tagger = ctx.tokenizer("ja").tagger
        sentences = [analyzer.strip_verse_number(sentence, tagger) for sentence in sentences]
    return {"sentences": sentences, "words": observed["words"]}


# --- text_extract ----------------------------------------------------------------------------------------------- #
_CONTAINER = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
              '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
              '</rootfiles></container>')
_OPF = ('<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">urn:uuid:parsing-suite'
        '</dc:identifier><dc:title>case</dc:title><dc:language>ja</dc:language></metadata>'
        '<manifest><item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="c1"/></spine></package>')


def _epub(xhtml):
    """The smallest EPUB a reader accepts, holding one chapter: mimetype (stored, first), container.xml,
    content.opf and the chapter's XHTML exactly as the case gives it."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as book:
        book.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        book.writestr("META-INF/container.xml", _CONTAINER)
        book.writestr("OEBPS/content.opf", _OPF)
        book.writestr("OEBPS/chapter.xhtml", xhtml.encode("utf-8"))
    return out.getvalue()


def _split_length(ctx):
    """Extract's chunk length as the importer's window reads it — settings.json's split_length, else 1500 — from the
    frozen settings (harness.SETTINGS_SNAPSHOT), through the app's own settings_manager like harness.frozen_logic."""
    def read():
        path = os.path.join(harness.DATA, harness.SETTINGS_SNAPSHOT, "settings.json")
        with mock.patch.object(settings_manager, "get_settings_path", lambda: path), harness.quiet():
            return int(settings_manager.load_settings().get("split_length", 1500))
    return ctx.memo(("extract", "split_length"), read)


@evaluator("text_extract", expects=_TEXT_KEYS, compare=evaluators.compare_text, show=_show_text)
def text_extract(case, ctx):
    """A file through the Content Manager's Extract (epub_importer.FileImporterApp, its extraction methods run
    without a window): the text extract_text_from_file pulls out — an .epub's chapters, an .srt's or an .ass's
    lines, a text file — cut by split_by_length at the frozen settings' split_length and saved as .txt files
    (save_chunks: UTF-8), each then read as a content file the text layer's way. An .epub case's `text` is its one
    chapter's XHTML, packed into a minimal EPUB; any other is the file's content (ctx: ext, encoding)."""
    from app.epub_importer import FileImporterApp      # tkinter, ebooklib and bs4: only the cases that need it
    importer = FileImporterApp.__new__(FileImporterApp)
    importer.logic_settings = analyzer.LOGIC            # the pinned settings (split_overflow)
    importer.language = case.lang                       # the window's language: which encodings a file may be in
    ext = case.ctx.get("ext", ".txt")
    data = _epub(case.text) if ext == ".epub" else case.text.encode(case.ctx.get("encoding", "utf-8"))
    extracted, error = importer.extract_text_from_file(ctx.write(_file_name(case), data))
    if error:
        raise RuntimeError(f"Extract failed: {error}")
    sentences, words = [], set()
    for chunk in importer.split_by_length(extracted, _split_length(ctx)):
        saved = evaluators.text(dataclasses.replace(case, text=chunk, ctx={"ext": ".txt"}), ctx)
        sentences.extend(saved["sentences"])
        words.update(saved["words"])
    return {"sentences": sentences, "words": sorted(words)}


# --- user_file -------------------------------------------------------------------------------------------------- #
def _compare_user_file(observed, expect):
    problems = harness.compare_keys(observed, {key: value for key, value in expect.items() if key == "error"})
    return harness.compare_members(problems, "entries", set(observed["entries"]), expect, "has", "hasnt")


@evaluator("user_file", expects=("error", "has", "hasnt"), compare=_compare_user_file,
           show=lambda observed: (f"(stops the run: {observed['error']})" if observed["error"]
                                  else " · ".join(observed["entries"]) or "(nothing)"))
def user_file(case, ctx):
    """A file the user keeps in User Files/<lang>/, as their editor saved it — its name (ctx: name, default
    IgnoreList.txt) and its bytes (ctx: encoding, default utf-8; a leading "\ufeff" is a BOM) — read by the loader a
    run reads it with, for the case's language: a word list (load_simple_list: its entries), KnownWord.json
    (load_known_words: the known lemmas) or a frequency list, frequency_list_<lang>_<name>.csv
    (load_yomitan_frequency_list: its words). A loader that raises stops the run (Generate) — reported as `error`.
    -> {"entries": sorted, "error": ""} or {"entries": [], "error": "<exception>: <message>"}."""
    name = case.ctx.get("name", "IgnoreList.txt")
    path = ctx.write(name, case.text.encode(case.ctx.get("encoding", "utf-8")))
    script = ctx.script(case)
    try:
        if name == "KnownWord.json":
            entries = analyzer.load_known_words(path, ctx.tokenizer(case.lang, script))[1]
        elif name.startswith("frequency_list_"):
            entries = analyzer.load_yomitan_frequency_list(path, script, case.lang)
        else:
            entries = analyzer.load_simple_list(path, script, case.lang)
    except Exception as exc:
        return {"entries": [], "error": f"{type(exc).__name__}: {exc}"}
    return {"entries": sorted(str(entry) for entry in entries), "error": ""}

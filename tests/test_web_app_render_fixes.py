"""Regression guards for three web_app.html rendering bugs (output-html-02/04/05), asserted
straight from the template so a future edit can't silently reintroduce them:
- escapeHtml wrapped every double-quote in spaces (` &quot; `), corrupting displayed text.
- the regex-escape character class was malformed, so words with regex-special chars mis-highlighted.
- the audio button inlined the raw sentence into an onclick JS string, so a double-quote in the
  sentence prematurely closed the HTML attribute.
"""
import os

TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "web_app.html",
)


def _template():
    with open(TEMPLATE, encoding="utf-8") as f:
        return f.read()


def test_escapehtml_quote_has_no_surrounding_spaces():
    html = _template()
    assert 'replace(/"/g, "&quot;")' in html
    assert 'replace(/"/g, " &quot; ")' not in html  # the old, corrupting form


def test_regex_escape_character_class_is_valid():
    html = _template()
    assert r"replace(/[.*+?^${}()|[\]\\]/g, '\\$&')" in html
    assert r"replace(/[.*+?^${}()|[\\]\\]/g, '\\$&')" not in html  # the old, broken class


def test_audio_button_uses_data_attribute_not_inline_string():
    html = _template()
    assert 'data-audio="${audioSource}"' in html
    assert "playAudio(this.dataset.audio, this)" in html
    assert "playAudio('${audioText}', this)" not in html  # the old, fragile inline form

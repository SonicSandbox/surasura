"""The window's own words for Piyo's help (`app/help_docs.py`): each Settings section's rows and the help cards, as
help topics. Qt-free (the words tables only); read at packaging time (`package_app.write_help`), so a built program's
help says what its window says. Nothing outside the window imports this.
"""
import re

_PLACE = re.compile(r"\{[^{}]*\}")


def topics():
    """[the Settings group, the help cards' group], in the help index's shape."""
    return [settings_group(), cards_group()]


def settings_group():
    """Each Settings section a topic: every row's label, its one-line help and its tooltip."""
    from app.qt import settings_catalog as catalog
    topics = []
    for section in catalog.SECTIONS:
        lines = []
        for row in catalog.rows(section.id):
            label = _PLACE.sub("…", row.label or "").strip()
            said = [_PLACE.sub("…", s).strip() for s in (row.help, row.tip) if s]
            said = [s for i, s in enumerate(said) if s and s not in said[:i] and s != label]
            if label and said:
                lines.append(f"- {label}: " + ". ".join(s.rstrip(".") for s in said))
        if lines:
            topics.append({"title": section.name, "text": "\n".join(lines)})
    return {"title": "Settings", "text": "Every setting is on the Settings page; each row's ? says what it does.",
            "topics": topics}


def cards_group():
    """The window's help cards: what each part of the window is, and an example."""
    from app.qt import strings
    from app.services import help_cards
    topics = []
    for card in help_cards.CARDS:
        words = strings.HELP_CARDS.get(card.id)
        if not words:
            continue
        title, what, example = words
        lines = [what]
        if card.id == "automation":
            lines += [f"- {line}" for line in strings.HELP_AUTOMATION_LIST]
        if example:
            lines.append(f"For example: {example}")
        if strings.HELP_ALSO.get(card.id):
            lines.append(strings.HELP_ALSO[card.id])
        topics.append({"title": title, "text": "\n".join(lines)})
    return {"title": "In the window", "text": "The help cards: the ? beside each part of the window opens its card.",
            "topics": topics}

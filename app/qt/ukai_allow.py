"""鵜 Ukai's Allow card (UKAI-S1; Ukai SPEC §0 U4: one Allow, nothing typed). Ukai asked to pair
(`app/services/ukai_pairing.py`, on the door's thread, through the bridge's `ukai_asked`): the window comes to the
front and asks with the one confirmation card (`confirm.ask`), naming the 4-digit code Ukai's menu shows, the store an
id came from (an id no store gave: a warning line), and that a new pairing replaces the one kept. *Allow* is the
switch; *Not now*, Esc, Back or a click beside the card answer No. Shown only while `door.EXTENSION_ON` (the window
builds Ukai's pairing only then: `ShellWindow.ukai_extension`).
"""
from app.qt import confirm, strings


def words(request):
    """The card's body for `request` (a `ukai_pairing.Request`): its lines in order."""
    lines = [strings.UKAI_ALLOW_CODE.format(code=request.code)]
    if request.store:
        lines.append(strings.UKAI_ALLOW_STORE.format(store=request.store))
    else:
        lines.append(strings.UKAI_ALLOW_UNLISTED.format(ext_id=request.ext_id))
    if request.replaces:
        lines.append(strings.UKAI_ALLOW_REPLACES)
    return "\n\n".join(lines)


def ask(window, pairing, request):
    """(The GUI thread.) The card in `window`, brought to the front (Ukai's press asked for it); its answer to
    `pairing.answer` -> the card. An earlier Ukai card still open is dropped first: its pairing was let go (one
    pairing waits at a time), so its answer would pair nothing."""
    before = getattr(window, "_ukai_card", None)
    if before is not None:
        try:
            before.drop()
        except RuntimeError:                              # (deleted already: answered and gone)
            pass
    window.bring_to_front()
    window._ukai_card = confirm.ask(window, strings.UKAI_ALLOW_TITLE, words(request), strings.UKAI_ALLOW_YES,
                                    strings.UKAI_ALLOW_YES_TIP, no=strings.UKAI_ALLOW_NO,
                                    no_tip=strings.UKAI_ALLOW_NO_TIP,
                                    on_answer=lambda yes: pairing.answer(request.id, yes))
    return window._ukai_card

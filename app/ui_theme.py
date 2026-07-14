"""Shared ttk theming helper for optional module windows.

ttk styles are **process-global**: switching the active theme (`Style.theme_use`) or reconfiguring
the base `"."` style changes EVERY ttk widget in the interpreter, not just the window doing it. So a
module window that wants dark, brand-styled buttons must NOT unconditionally take over the theme —
doing so clobbers whatever host opened it in-process. The main app uses the ``default`` theme; the
Content Manager uses ``clam``; a module hard-coding ``theme_use('default')`` in its constructor
silently wrecks the Content Manager the moment it's opened from there.

The rule this encodes: **a host owns the base theme; a module inherits it and only layers its own
named styles.** A module should claim the global theme only when it was launched standalone — the
tell is that a native platform theme (which ignores ttk widget colors) is still active because no
host set one.

Usage in a module's style setup::

    from app.ui_theme import ensure_styleable_theme
    style = ttk.Style(self)
    if ensure_styleable_theme(self):
        # standalone: we own the base, so set it up
        style.configure(".", background=BG, foreground=TEXT, ...)
    # always register the module's OWN *named* styles (additive, safe under any styleable theme):
    style.configure("YT.TButton", ...)
"""
from tkinter import ttk

# Native platform ttk themes that ignore widget ``background``/``foreground``, so our dark named
# styles wouldn't render. If one of these is active, no host has themed us — we're standalone.
_NATIVE_UNSTYLEABLE = {"vista", "xpnative", "winnative", "aqua", "classic"}


def ensure_styleable_theme(widget, preferred="default"):
    """Guarantee a ttk theme that honors widget colors, without clobbering a host.

    If the current global theme is a native, unstyleable one (we're standalone), switch to
    ``preferred`` and return ``True`` — the caller should then configure the base ``"."`` style.
    If a host has already set a styleable theme, leave it untouched and return ``False`` — the
    caller must only register its own *named* styles and inherit everything else.
    """
    style = ttk.Style(widget)
    try:
        if style.theme_use() in _NATIVE_UNSTYLEABLE:
            style.theme_use(preferred)
            return True
    except Exception:
        pass
    return False

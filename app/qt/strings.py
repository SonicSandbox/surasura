"""Every user string of the window (W2.1 on; the window's spec 05 §5.12, 01 §1.5: one table, so the app can be
translated later). Code under `app/qt/` names a string from here, never writes one inline. Log lines are not user
strings and stay with their code.
"""

# The window (G1.2-17: the subtitle lives in the title, not the header).
WINDOW_TITLE = "Surasura — The Immersion Architect"
WORDMARK = ("Sura", "sura")                   # the second half wears the iris
WORDMARK_NAME = "Surasura"
LANGUAGE_NAMES = {"ja": "日本語", "zh": "中文"}

# The tabs: name, tooltip (D17: every button and toggle has one).
TABS = {
    "current": ("Current", "What you're working through now, in the order you'll meet it"),
    "finished": ("Finished", "What you've finished: a record, and still a source of sentences"),
    "needs": ("Needs you", "Something here waits for a look or a decision from you"),
    "settings": ("Settings", "Every setting, on one page"),
}
TABS_NAME = "Sections"
TAB_WITH_COUNT = "{name}  {count}"             # Needs you's unseen entries

# Each page until its step builds it (W2.2 Current, W3.2 Finished and Needs you, W3.3 Settings).
PAGE_WAITING = "This page arrives in a later build of 3.0."

# The bottom bar.
BAR_NAME = "Status"
BAR_FAILURE_PREFIX = "⚠ "
BAR_LOGS = "Open the logs folder"
BAR_LOGS_TIP = "Open the folder where Surasura keeps its logs, to look at them or send them"
BAR_FAILURE_TIP = "The newest problem a command-line run reported. Its details are in the logs folder"

# The look (G1.2-21): shown only if a live switch is ever too slow.
RESTART_TO_APPLY = "Restart Surasura to apply"

# The frame-time HUD (a developer's overlay, SURASURA_HUD=1).
HUD_LINE = "step p95 {sp} max {sm} >4ms {so}  ·  frame p95 {fp} max {fm}"

# --- M2.1: toasts (05 §5.4) and the motion
TOAST_UNDO = "Undo"
TOAST_UNDO_TIP = "Undo this change"

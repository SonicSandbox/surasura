"""The 2.x window for *known from Anki* (P2.4 row 2.4.15): when Surasura opens and its known-words sync has marked
words known because you suspended their cards, a small window says so — *You suspended N cards since … — marked
known* — with **Undo** per word (the word off your known words, its card back in your reviews, ✅ P2.4-6); and, once,
the offer for the cards already suspended when the signal was first read (*Mark their words known?*). 3.0's place for
it is the new window's Inbox (Mado's).

GUI_Design_Guidelines: the dark palette, ttk widgets, Esc closes, 10 px padding, a tooltip on every button. Every
Anki call runs on a worker; the window only posts to Tk through `after`. Imported only with Connect's preview on.
"""
import threading
import tkinter as tk
from tkinter import ttk

BG, SURFACE, TEXT, ACCENT, SECONDARY, ERROR = "#1e1e1e", "#2d2d2d", "#e0e0e0", "#bb86fc", "#03dac6", "#cf6679"
SHOWN_MAX = 30              # words listed; the rest are counted


def _since(marked):
    first = min((m.get("at") or "" for m in marked), default="")
    return first.replace("T", " ")[:16] if first else "your last sync"


def show(parent, language, url, tooltip, offer=None, marked=None):
    """The window, or None when there is nothing to say. `tooltip(widget, text)`: the app's ToolTip."""
    from app.connect import known_signal
    marked = known_signal.unshown(language) if marked is None else marked
    if offer is None:
        offer = (known_signal.load(language).get("offer") or {})
    pending = offer.get("state") == "pending" and offer.get("cards")
    if not marked and not pending:
        return None
    win = tk.Toplevel(parent)
    win.title("Known from Anki")
    win.configure(bg=BG)
    win.bind("<Escape>", lambda _e: win.destroy())
    style = ttk.Style(win)
    style.configure("KS.TFrame", background=BG)
    style.configure("KS.TLabel", background=BG, foreground=TEXT)
    style.configure("KS.Head.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI", 11, "bold"))
    style.configure("KS.Note.TLabel", background=BG, foreground=SECONDARY)
    style.configure("KS.TButton", background=SURFACE, foreground=TEXT)
    frame = ttk.Frame(win, style="KS.TFrame", padding=10)
    frame.pack(fill=tk.BOTH, expand=True)

    def worker(job, then):
        def run():
            try:
                out = job()
            except Exception as e:          # Anki closed, the known-words lock held: said, nothing changed
                out = e
            win.after(0, lambda: then(out))
        threading.Thread(target=run, daemon=True).start()

    if marked:
        words = list(dict.fromkeys(m["word"] for m in marked))
        ttk.Label(frame, text=f"You suspended {len(marked)} cards since {_since(marked)} — marked known",
                  style="KS.Head.TLabel").pack(anchor=tk.W, pady=(0, 6))
        for word in words[:SHOWN_MAX]:
            row = ttk.Frame(frame, style="KS.TFrame")
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=word, style="KS.TLabel").pack(side=tk.LEFT)
            state = ttk.Label(row, text="", style="KS.Note.TLabel")
            state.pack(side=tk.RIGHT, padx=(6, 0))
            button = ttk.Button(row, text="Undo", style="KS.TButton")
            button.pack(side=tk.RIGHT)

            def undo(w=word, b=button, s=state):
                b.config(state=tk.DISABLED)
                worker(lambda: known_signal.undo(language, w, url),
                       lambda out: s.config(text=("Couldn't undo: " + str(out)) if isinstance(out, Exception)
                                            else "Undone: back in your reviews"))
            button.config(command=undo)
            tooltip(button, f"Take {word} off your known words and un-suspend its card in Anki, so it comes back to "
                            "your reviews.")
        if len(words) > SHOWN_MAX:
            ttk.Label(frame, text=f"… and {len(words) - SHOWN_MAX} more", style="KS.TLabel").pack(anchor=tk.W)

    if pending:
        cards = offer["cards"]
        ttk.Label(frame, text=f"{len(cards)} cards were already suspended in Anki. Mark their words known?",
                  style="KS.Head.TLabel").pack(anchor=tk.W, pady=(10, 6))
        row = ttk.Frame(frame, style="KS.TFrame")
        row.pack(anchor=tk.W)
        note = ttk.Label(frame, text="", style="KS.Note.TLabel")
        note.pack(anchor=tk.W, pady=(4, 0))
        yes = ttk.Button(row, text="Mark them known", style="KS.TButton")
        no = ttk.Button(row, text="Leave them", style="KS.TButton")

        def answered(text):
            yes.config(state=tk.DISABLED)
            no.config(state=tk.DISABLED)
            note.config(text=text)
        yes.config(command=lambda: worker(lambda: known_signal.accept_offer(language),
                                          lambda out: answered(("Couldn't mark them: " + str(out))
                                                               if isinstance(out, Exception)
                                                               else f"{len(out)} words marked known")))
        no.config(command=lambda: (known_signal.decline_offer(language), answered("Left as they are")))
        yes.pack(side=tk.LEFT, padx=(0, 6))
        no.pack(side=tk.LEFT)
        tooltip(yes, "Every word of those suspended cards becomes known in Surasura (you can undo each later).")
        tooltip(no, "Leave them: only cards you suspend from now on mark their words known.")

    close = ttk.Button(frame, text="Close", style="KS.TButton", command=win.destroy)
    close.pack(anchor=tk.E, pady=(10, 0))
    tooltip(close, "Close this window (Esc).")
    known_signal.mark_shown(language)
    return win

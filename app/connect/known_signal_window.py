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
SHOWN_MAX = 30              # words listed a heading; the rest are counted, and listed the next time (adversary B #9)


def _since(marked):
    first = min((m.get("at") or "" for m in marked), default="")
    return first.replace("T", " ")[:16] if first else "your last sync"


def view(language, with_offer=True):
    """What the window shows, read from the record — on a worker, never the screen's thread (intent keeper P2.4-B #4)
    -> {"marked", "taken", "offer", "terms"}, or None when the record can't be read (left as it is, review B #17).
    `with_offer`: False once this dashboard session has shown the pending offer (shown until answered, once a
    session: intent keeper P2.4-B #5, #10)."""
    from app.connect import known_signal
    try:
        state = known_signal.load(language)
    except known_signal.Unreadable as e:
        print(e)
        return None
    live = [m for m in state.get("marked") or () if not m.get("shown") and not m.get("undone")]
    return {"marked": [m for m in live if m.get("why") != "offer"], "taken": [m for m in live if m.get("why") == "offer"],
            "offer": (state.get("offer") or {}) if with_offer else {}, "terms": state.get("terms") or ["suspended"]}


def show(parent, language, url, tooltip, offer=None, marked=None, taken=None, terms=None):
    """The window, or None when there is nothing to say. `tooltip(widget, text)`: the app's ToolTip. `marked`: the
    words your signal marked; `taken`: the offer's words you accepted (each with Undo too: adversary B #9); `offer`:
    the record's pending offer. The app hands them in from `view` (read on its worker); one not handed in is read
    here (tests)."""
    from app.connect import known_signal
    if marked is None or offer is None or taken is None:
        seen = view(language)
        if seen is None:
            return None
        marked = seen["marked"] if marked is None else marked
        taken = seen["taken"] if taken is None else taken
        offer = seen["offer"] if offer is None else offer
        terms = terms or seen["terms"]
    terms = terms or ["suspended"]
    pending = offer.get("state") == "pending" and offer.get("cards")
    if not marked and not taken and not pending:
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
            except Exception as e:          # Anki closed or busy, the known-words lock held: said (review B #13)
                out = e
            win.after(0, lambda: then(out))
        threading.Thread(target=run, daemon=True).start()

    listed = set()

    def words_with_undo(entries, head):
        words = list(dict.fromkeys(m["word"] for m in entries))
        ttk.Label(frame, text=head, style="KS.Head.TLabel").pack(anchor=tk.W, pady=(0, 6))
        for word in words[:SHOWN_MAX]:
            listed.add(word)
            row = ttk.Frame(frame, style="KS.TFrame")
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=word, style="KS.TLabel").pack(side=tk.LEFT)
            state = ttk.Label(row, text="", style="KS.Note.TLabel")
            state.pack(side=tk.RIGHT, padx=(6, 0))
            button = ttk.Button(row, text="Undo", style="KS.TButton")
            button.pack(side=tk.RIGHT)

            def undo(w=word, b=button, s=state):
                b.config(state=tk.DISABLED)

                def done(out):
                    if isinstance(out, Exception):
                        s.config(text="Couldn't undo: " + str(out))
                        b.config(state=tk.NORMAL)       # try again (review B #13)
                    else:
                        s.config(text="Undone: back in your reviews" if out.get("unsuspended") else "Undone")
                worker(lambda: known_signal.undo(language, w, url), done)
            button.config(command=undo)
            tooltip(button, f"Take {word} off your known words"
                            + (" and un-suspend its card in Anki, so it comes back to your reviews."
                               if "suspended" in terms else "."))
        if len(words) > SHOWN_MAX:
            ttk.Label(frame, text=f"… and {len(words) - SHOWN_MAX} more, listed here next time",
                      style="KS.TLabel").pack(anchor=tk.W)

    if marked:
        head = (f"You suspended {len(marked)} cards" if "suspended" in terms
                else f"{len(marked)} cards took your Known-from-Anki mark")
        words_with_undo(marked, f"{head} since {_since(marked)} — marked known")
    if taken:
        words_with_undo(taken, f"{len(set(m['word'] for m in taken))} words from the cards already suspended — "
                               "marked known as you asked")

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
        yes.config(command=lambda: worker(lambda: known_signal.accept_offer(language, url),
                                          lambda out: answered(("Couldn't mark them: " + str(out))
                                                               if isinstance(out, Exception)
                                                               else f"{len(out)} words marked known: each "
                                                               "with Undo here next time")))
        no.config(command=lambda: worker(lambda: known_signal.decline_offer(language),
                                         lambda out: answered(("Couldn't answer: " + str(out))
                                                              if isinstance(out, Exception) else "Left as they are")))
        yes.pack(side=tk.LEFT, padx=(0, 6))
        no.pack(side=tk.LEFT)
        tooltip(yes, "Every word of those suspended cards becomes known in Surasura (you can undo each later).")
        tooltip(no, "Leave them: only cards you suspend from now on mark their words known.")

    close = ttk.Button(frame, text="Close", style="KS.TButton", command=win.destroy)
    close.pack(anchor=tk.E, pady=(10, 0))
    tooltip(close, "Close this window (Esc).")
    if listed:      # on a worker: a save never runs on the screen's thread (intent keeper P2.4-B #4)
        threading.Thread(target=known_signal.mark_shown, args=(language, set(listed)), daemon=True).start()
    return win

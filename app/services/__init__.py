"""The window's Qt-free services (W1.3; the window's spec 04 §4.1–4.2, 01 §1.6): settings, the job registry, the
Generate controller, the PROGRESS reader and the status snapshot.

The window decides nothing: it reads their snapshots and hands them commands. None of them imports Qt, Tk or pandas (a
test imports each alone and checks), so they run headless, in tests and under either window. Their callbacks run on
their own worker threads; a window turns them into its own events (the Tk dashboard through its queue, the Qt window
through `app/qt/bridge.py`, W2.1) and never touches a widget from one.
"""

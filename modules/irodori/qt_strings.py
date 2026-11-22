# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI voice's words in the 3.0 window (terse, the app's style)."""

ABOUT = ("An AI voice, made on this computer: nothing is sent anywhere. It fills a card's sentence audio only when the "
         "card has none.")
NEEDS_INSTALL = "Needs a one-time download: about {gb} GB."
# The time a sentence takes is said only in the line's hover, never on screen
TIME_CPU = ("On your processor: about 15–34 seconds a sentence, made in the background. A 300-card book takes about "
            "2–3 hours.")
TIME_GPU = "On your graphics card ({card}): a few seconds a sentence, made in the background."
INSTALLED = "Installed · {gb} GB · {where}"
WHERE_CPU, WHERE_GPU = "on your processor", "on your graphics card"
OLDER = "An older version is installed. Install the new one to use it."
LOOKING = "Looking…"

INSTALL, INSTALL_TIP = "Install", "Downloads the voice and its programs into this computer's Surasura folder"
STOP, STOP_TIP = "Stop", "Stops the download. Install picks up where it stopped"
REMOVE, REMOVE_TIP = "Remove", "Deletes the voice and its programs. The audio already on your cards stays"
INSTALLING = "Installing the AI voice: {step} of {of} — {what}…"
INSTALLED_DONE = "The AI voice is installed"
INSTALL_STOPPED = "Install stopped. Press Install to go on"
INSTALL_FAILED = "The AI voice wasn't installed: {why}"
REMOVED = "The AI voice was removed · {gb} GB freed"
REMOVE_FAILED = "The AI voice wasn't removed: {why}"

# Anki Backfill's button (`qt_backfill.py`)
BACKFILL, BACKFILL_TIP = ("AI sentence audio (beta)…",
                          "Counts the cards here with no sentence audio, then makes it with the AI voice. Never over "
                          "audio a card already has")
COUNTING = "Counting the cards with no sentence audio…"
MAKE, MAKE_TIP = ("Make it", "Makes the AI audio for these cards, in the background: about 15–34 seconds a "
                                "sentence on a processor, a few on a graphics card. Undo takes it off again")
MAKING = "Making AI audio: {done} of {of}…"
UNDO, UNDO_TIP = "Undo AI audio", "Takes the AI audio this run added off its cards (a card you changed since stays)"

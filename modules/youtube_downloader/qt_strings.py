# SPDX-License-Identifier: GPL-3.0-or-later
"""Every user string of the YouTube module's Qt windows (`qt_window.py`: the transcript downloader; `qt_preview.py`:
the preview against the library): one table, so the windows can be translated (the Qt GUI guide §3). No Qt here.
Section names are the user's (Current · Soon · Goal), never the folders'."""

# --- the transcript downloader ---
DOWNLOADER_TITLE = "Video Transcripts"
DOWNLOADER_HEADING = "Video Transcripts"
LINKS_NAME = "Links, one per line"
LINKS_HINT = "One link per line — YouTube videos, lists and playlists, or bilibili.tv episodes and seasons"
LINKS_TIP = "Paste one link per line. bilibili.com links are refused: open the show on bilibili.tv instead."
# try a9.1 (Sonic: "as few buttons / most visual and condensed yet balanced as possible"): what the window does, behind
# its ?; the rest of its actions in ⋯; a run shown as a bar
HELP = "?"
HELP_NAME = "About Video Transcripts"
HELP_TIP = ("<b>Bring in videos to learn from.</b> Paste YouTube or bilibili.tv links — videos, lists, playlists, "
            "episodes or seasons — and press Download: each video's captions come into your library as a transcript, "
            "its channel first in its name, every line's time kept so a sentence can open its moment in the video."
            "<br>• Captions: which to pull (manual → auto → auto-translated)"
            "<br>• ⋯: fill missing timestamps, update yt-dlp, the Processed folder, the log, the risks"
            "<br>• Close it while it downloads: it goes on in its icon at the bottom right")
MORE = "⋯"
MORE_NAME = "More"
MORE_TIP = ("More: fill missing timestamps · update yt-dlp · open the Processed folder · open the log · "
            "I understand the risks")
PROGRESS_NAME = "How far the run is"
PICTURE_NAME = "The video being downloaded"
COUNTED = "{done} of {total} videos"                                 # beside the bar: how far through the list
WROTE = "✓ {name}"                                                 # a transcript written, as the run goes
KEPT_DOWNLOADING = "Still downloading — right-click its icon to stop"   # X while it runs: it goes on in its icon
KEPT_FILLING = "Still fetching cue times — right-click its icon to stop"
KEPT_UPDATING = "Still updating yt-dlp — right-click its icon to stop"
LANGUAGE_LABEL = "Captions"
LANGUAGE_TIP = "Which captions to pull (manual → auto → auto-translated)."
RISK = "I understand the risks"
RISK_TIP = ("Acknowledge before use. Downloading from YouTube or bilibili.tv can hit temporary rate-limits (HTTP 429) "
            "and is a gray area under their Terms of Service. Use only for your own personal, offline study — it's your "
            "responsibility.\n• Download stays off until this is ticked"
            "\n• It also lets Connect download a video for a few minutes to make its cards: the video is deleted as "
            "soon as its cards are made")
DOWNLOAD = "Download"
DOWNLOAD_TIP = "Download the transcripts into your Processed folder"
BACKFILL = "Fill missing timestamps"
BACKFILL_TIP = ("Fetch cue times for transcripts downloaded before Surasura kept them, so the report can jump to the "
                "right moment in the video.\n• Asks first with the count and the time; your transcripts are never "
                "rewritten")
UPDATE = "Update yt-dlp"
UPDATE_TIP = "Update the downloader engine (yt-dlp). Use this if downloading stops working."
OPEN_FOLDER = "Open the Processed folder"
OPEN_FOLDER_TIP = "Open the Processed folder where transcripts are saved"
OPEN_LOG = "Open the log"
OPEN_LOG_TIP = "Open the full log of the last download, timestamp fill or update"

NO_LINKS = "Paste at least one YouTube or bilibili.tv link first."
DOWNLOADING = "Downloading…"
SCANNING = "Looking for transcripts without cue times…"
NOTHING_TO_FILL = "Every transcript already has its cue times — nothing to fill."
SCAN_FAILED = "Couldn't look for transcripts: {why}"
FILLING = "Fetching cue times…"
UPDATING = "Updating yt-dlp…"
FAILED = "Something went wrong: {why}"
FINISHED = "Finished."
NONE_NEW = "Finished: no new transcripts."
# Until W3.2 routes them into the library (its arrivals), the new files stay where yt-dlp put them (IK-32).
NEW_IN_PROCESSED = "{what} in Processed."
NEW_ROUTED = "Finished: {what} handed to your library."
SEE_IN_ARRIVALS = "See them in New arrivals"                         # W3.2-2: the done line's link to the tray
STOPPED = "Stopped."
STOPPED_KEPT = "Stopped. {what} in Processed."
WAITING = "Waiting for the other video run to end…"
FILL_LANGUAGE_CHANGED = "The language changed while you were asked, so nothing was fetched. Ask again for this language."
NO_LOG = "No log yet: nothing has run."
FOLDER_FAILED = "Couldn't open the folder: {why}"
# The bottom bar's names for the runs (each a job: the bar shows it, Cancel stops it, quitting stops it)
JOB_DOWNLOAD = "Downloading video transcripts"
JOB_FILL = "Fetching cue times"
JOB_UPDATE = "Updating yt-dlp"
JOB_PREVIEW = "Previewing a video"
JOB_SETUP = "Bringing in videos from YouTube"                      # alpha 8: setup's first videos
# alpha 8 (Sonic: "it should still get the whole playlist"): a playlist's rest, in the background after setup
REST_CAME = "YouTube · the rest of your playlist: {what}"
REST_NOTHING = "YouTube · the rest of your playlist: nothing new to bring in"
REST_NOTHING_BUT = "YouTube · the rest of your playlist didn't come in: {why}"
REST_LATER = "the rest of your playlist waits ({why}): it goes on the next time Surasura starts"
REST_STOPPED = "stopped"
REST_CANCELLED = "cancelled: the YouTube window can bring in the rest of the playlist any time"
REST_YIELDED = "the rest of your playlist goes on after your other YouTube run"
REST_MORE = "more of your playlist comes in now"
REST_SPENT = "the rest of your playlist didn't come in after {tries} tries ({why}): the YouTube window can bring it in"
REST_FAILED = "YouTube · the rest of your playlist couldn't be noted: {why}"

BACKFILL_ASK_TITLE = "Fetch cue times?"
BACKFILL_ASK_BODY = ("{what} no cue times yet. Surasura re-fetches their captions from YouTube in batches of {batch}, "
                     "pausing in between so it isn't rate-limited. Rough estimate: {minutes}.\n\nClose this window at "
                     "any point to stop — finished ones are saved, and running it again picks up where it left off. "
                     "Your transcripts themselves are never changed.")
BACKFILL_YES = "Fetch {what}"
BACKFILL_YES_TIP = "Start fetching the missing cue times (close the window to stop)"
BACKFILL_NO_TIP = "Don't fetch anything now (Esc does the same)"

# --- the preview against the library ---
PREVIEW_TITLE = "Preview Against Library"
PREVIEW_HEADING = "Preview against your library"
PREVIEW_LINK_NAME = "Video link"
PREVIEW_LINK_HINT = "A YouTube or bilibili.tv link (video, playlist or season)"
PREVIEW_LINK_TIP = ("See a video's vocab journey scored against your existing library — without a full re-run.\n"
                    "• Enter starts the preview")
ADD_FRONT = "Add to the front of Current"
ADD_FRONT_TIP = ("Off by default, for this preview only. If on, the transcript is added at the top of Current so future "
                 "runs include it first. It does NOT mark any words as known.")
PREVIEW = "Preview"
PREVIEW_TIP = "Fetch the transcript and open its journey against your library"
PREVIEW_OPENED = "Opened the preview."
PREVIEW_ADDED = "Opened the preview. Added {what} to the front of Current."
PREVIEW_NOT_ADDED = "Opened the preview. {why}"
PLAYLIST_TITLE = "This link is a playlist"
PLAYLIST_BODY = "It holds {count} videos. Preview the full playlist, or just this one video?"
PLAYLIST_FULL = "Full playlist"
PLAYLIST_FULL_TIP = "Score every video in the playlist, each on its own against your library"
PLAYLIST_ONE = "Just this video"
PLAYLIST_ONE_TIP = "Score only the video the link points at (Esc does the same)"
GENERATE_TITLE = "Generate your list first?"
GENERATE_YES = "Generate"
GENERATE_YES_TIP = "Generate your list now; the preview runs by itself when it's ready"
GENERATE_NO_TIP = "Don't Generate now (Esc does the same)"
GENERATING = "Generating your list… the preview runs by itself when it's ready."
GENERATE_FAILED = "Generate didn't finish, so there is nothing to preview against yet."


# --- the preview's pipeline (`preview.run_preview`, `preview.Runs`; moved from preview.py: one table, AD4-13) ---
BILIBILI_COM_REFUSED = ("bilibili.com only gives subtitles to signed-in users. Open the same show on bilibili.tv and "
                        "paste that link instead.")
NO_CACHE = "There is no list to compare with yet: Generate your list first, then preview."
OTHER_LANGUAGE = ("Your last list was made for another language: Generate this language's list first, then "
                  "preview.")
ALREADY_IN_LIBRARY = "That video is already in your library — nothing to preview."
NO_YTDLP = "Could not get yt-dlp. Check your connection and try again."
NO_TRANSCRIPT_BILIBILI = ("No transcript found — this episode may not be available in your region, or has no "
                          "subtitles in your language.")
NO_TRANSCRIPT = "No transcript found (the video may have no captions in your language)."
UNEXPECTED = "Unexpected error: {why}"
SCORE_FAILED = "Couldn't score the video ({why}). The log says more: {log}"
STORE_BUSY = "Your library is busy for a moment, so nothing was added. Try again."
STORE_DAMAGED = "Your library can't take new files until it's repaired (Needs you says how), so nothing was added."
LOOKING_UP = "Looking up link…"
FETCHING = "Fetching transcript…"
SCORING = "Scoring against your library…"

# --- counts, said in words (IK-33: never "(s)") ---
def plural(n, one, many):
    return one.format(n=n) if n == 1 else many.format(n=n)


def new_transcripts(n):
    return plural(n, "{n} new transcript waits", "{n} new transcripts wait")


def transcripts_handed(n):
    return plural(n, "{n} new transcript", "{n} new transcripts")


def transcripts_without(n):
    return plural(n, "{n} transcript has", "{n} transcripts have")


def minutes(n):
    return plural(n, "{n} minute", "{n} minutes")


def cue_times(n):
    return plural(n, "{n} cue time", "{n} cue times")


def files(n):
    return plural(n, "{n} file", "{n} files")


def rest_job(n):
    return plural(n, "Bringing in the rest of your YouTube playlist", "Bringing in the rest of your {n} YouTube playlists")

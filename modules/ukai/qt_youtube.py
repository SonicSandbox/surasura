# SPDX-License-Identifier: GPL-3.0-or-later
"""鵜 Ukai's YouTube links, the window's half (UKAI-S3; #474's `windows._youtube_links`, by mattias): the links
`youtube.route` handed to the window's thread, run by the YouTube downloader. A `qt_` file: the only part of the
module that reaches the window."""


def run(shell, urls, release):
    """(The window's thread.) The links run as the downloader's window runs pasted ones (`fetch_links`), the
    transcripts into New arrivals as its own do (`youtube_arrivals`, which says how many arrived). Its progress in the
    bar as it goes (`BarLines`), and said when it ends with none new; `release()` once it ends (or fails to start)."""
    from app.qt import applog, windows
    from modules.ukai.youtube import NO_LIBRARY, NONE_NEW, STARTED, BarLines

    def say(line):
        windows.say_in_bar(shell, line)
    try:
        from modules.youtube_downloader import fetch_links
        writer = shell.services.writer
        if writer is None:                          # (the library closed since the route's look)
            release()
            say(NO_LIBRARY)
            return
        arrived = windows.youtube_arrivals(shell)
        say(STARTED.format(n=len(urls)))

        def ended(created, problems):
            release()
            if problems:
                say(problems[0])
            if created:
                try:
                    arrived(created)
                except RuntimeError as e:           # (the library switched meanwhile: they wait in Processed)
                    say(str(e))
                except Exception as e:              # (never out of the window's slot: logged, they wait there)
                    applog.log("ukai", f"YouTube links' transcripts: {e!r}")
            elif not problems:
                say(NONE_NEW)
        fetch_links(shell, list(urls), writer.language, BarLines(say), ended)
    except Exception as e:                          # the downloader gone or broken: logged, the app goes on
        release()
        applog.log("ukai", f"YouTube links: {e!r}")

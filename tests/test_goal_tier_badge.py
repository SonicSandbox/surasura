"""The YouTube preview's page (templates/web_app.html, `modules/youtube_downloader/preview.py`) marks a file from your
Goal with a quiet "Goal" chip (3.0's name; 2.x said "6+").

The journey's own chip (the old page's sidebar, its tier from the schedule) retired with the old journey page
(J-RETIRE, 2026-11-23): the journey page reads each episode's tier from the library store.
"""
import os

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "templates", "web_app.html")


def test_the_chip_is_quiet_and_hidden_from_dictionary_extensions():
    """Themed outline, text drawn by CSS (so Yomitan/Migaku never read it), a plain-language hover
    — and no trace of the old saturated green "G" or its internal "Goal Content" name."""
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    assert 'class="tier-chip" data-content="Goal"' in html
    assert 'title="From your Goal: someday, in no order" migaku_ignore data-yomichan-ignore' in html
    assert ".tier-chip::after" in html
    assert 'title="Goal Content">G</span>' not in html
    # 3.0's window names the list Goal: no 2.x tier name reaches the report's words (the chip, its hover; the ✦ hover never named one)
    assert "6+ months" not in html and 'data-content="6+"' not in html

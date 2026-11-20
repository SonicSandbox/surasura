"""app/child_io.py (Haya-CL 3.0.17): a child's stdout / stderr to a parent that has gone — the window closed first, its
pipe with it — goes nowhere, never an exception, and the child can tell (`parent_gone`).

What a wrong answer would cost: a cancelled Generate's last line raising into Surasura.exe's Critical Error box on the
learner's screen after he closed the window (Sonic's laptop, 3.0.16); or a child that can't tell its window left and
works on for nobody.

A real OS pipe whose reading end is closed (Windows answers a write with OSError 22, elsewhere BrokenPipeError).
"""
import io
import os

import pytest

from app import child_io


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setitem(child_io._state, "gone", False)


def _closed_pipe():
    read, write = os.pipe()
    os.close(read)
    return open(write, "w", encoding="utf-8")


def test_a_line_to_a_parent_that_has_gone_goes_nowhere_and_says_so(fresh):
    stream = child_io.guarded(_closed_pipe())
    print('{"type": "error", "code": "cancelled", "message": "Generate を取り消しました"}', file=stream, flush=True)
    assert child_io.parent_gone()
    print("Processing 第01話.srt...", file=stream, flush=True)     # everything after: nowhere, quietly
    stream.flush()
    stream.close()


def test_a_parent_still_reading_gets_every_line_and_nothing_is_gone(fresh):
    read, write = os.pipe()
    stream = child_io.guarded(open(write, "w", encoding="utf-8"))
    print("認真 · 上層部", file=stream, flush=True)
    stream.close()
    with open(read, encoding="utf-8") as f:
        assert f.read() == "認真 · 上層部\n"
    assert not child_io.parent_gone()


def test_a_closed_stream_counts_as_gone_too(fresh):
    inner = io.StringIO()
    inner.close()
    stream = child_io.guarded(inner)
    assert stream.write("勇气") == 2 and child_io.parent_gone()
    stream.close()


def test_text_the_stream_cant_hold_is_no_parent_gone(fresh):
    # a UnicodeEncodeError is a ValueError: it must stay the caller's error, never silence the child for good
    stream = child_io.guarded(io.TextIOWrapper(io.BytesIO(), encoding="ascii"))
    with pytest.raises(UnicodeEncodeError):
        stream.write("上層部")
    assert not child_io.parent_gone()


def test_guarding_is_idempotent_and_leaves_none_alone(monkeypatch):
    stream = child_io.guarded(io.StringIO())
    assert child_io.guarded(stream) is stream and child_io.guarded(None) is None
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    child_io.guard_std_streams()
    child_io.guard_std_streams()
    import sys
    assert sys.stdout._stream is out and sys.stderr._stream is err
    assert sys.stdout.getvalue() == ""                        # the stream's own attributes pass through

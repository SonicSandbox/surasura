"""hato's content key, byte for byte (P3.2 row 3.2.3; 09-hato-layer v2 §1.1): `videos.content_key` must equal hato's
`video_hash` — "v1-" + sha256 of the size as 8 bytes little-endian, then the whole file up to 131,072 bytes, else its
first and last 65,536 bytes.

What a wrong answer would cost: the key is how Connect tells a paired video found away from its named path from
another file of the same name and size. A key that differs from hato's by one byte (big-endian, an overlap read twice,
the boundary on the wrong side) refuses every moved episode for good; a key read from a file still being copied could
match a half-written file and mine its lines against the wrong audio.

The seven vectors are hato's own (09-hato-layer v2 §1.1): byte i = i % 251, files written in the test's temp folder.
"""
import os

import pytest

from app.connect import videos

VECTORS = [
    (0, "v1-af5570f5a1810b7af78caf4bc70a660f0df51e42baf91d4de5b2328de0e83dfc"),           # empty
    (1000, "v1-a596f696db9299c940c4dbdc5184bd859baa40d980cbd1472f0610998da0971d"),        # under 64 KiB
    (65536, "v1-3192f0200afc272bf234494004343e428a932e979a8b840cd14da25465b442a7"),       # exactly 64 KiB
    (100000, "v1-35ad68a7b9d386a036d20004ecb65b14ae2d42d8861480babaa36bfea33580cd"),      # between 64 and 128 KiB
    (131072, "v1-316145b76fc25a90874a7d8d32948df2bbac7fb27295ff6e8ada20d663622ed2"),      # 128 KiB: read whole
    (131073, "v1-359195e004e4bfd1a0a6fdbb6a51f0eb1640d0832fe345e4a356713a3a341573"),      # one over: head + tail
    (300000, "v1-4b07ea24a4bef035d540cdbb9d00020d83e09245e2455baebe498315e35e1fbd"),      # over 128 KiB
]


def _file(tmp_path, size, name="ぼっち・ざ・ろっく！ 05.mkv"):
    path = tmp_path / name
    path.write_bytes(bytes(i % 251 for i in range(size)))
    return str(path)


@pytest.mark.parametrize("size, key", VECTORS, ids=[str(size) for size, _key in VECTORS])
def test_the_content_key_is_hatos_video_hash_for_each_of_the_seven_vectors(tmp_path, size, key):
    # why: one recipe on both sides, or a moved episode is never recognised (or a wrong one is)
    assert videos.content_key(_file(tmp_path, size)) == key


def test_a_file_that_cant_be_read_has_no_key(tmp_path):
    # why: a missing file or a folder is no video; the caller treats None as "not the paired one", never a crash
    assert videos.content_key(str(tmp_path / "ない.mkv")) is None
    assert videos.content_key(str(tmp_path)) is None


@pytest.mark.parametrize("size", [100000, 300000])
def test_a_file_that_changes_while_it_is_read_has_no_key(tmp_path, monkeypatch, size):
    # why: a video still being copied (it grows) or replaced in place (same size, new time) is not yet the file hato
    # hashed — a key from it could name the wrong bytes. Both a whole read and a head + tail read are covered.
    path = _file(tmp_path, size)
    real = videos._key_body

    def grows(p, n):
        body = real(p, n)
        with open(p, "ab") as f:
            f.write(b"\0" * 10)
        return body

    monkeypatch.setattr(videos, "_key_body", grows)
    assert videos.content_key(path) is None, "grew during the read"

    path = _file(tmp_path, size, name="ぼっち・ざ・ろっく！ 06.mkv")

    def rewritten(p, n):
        body = real(p, n)
        st = os.stat(p)
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))      # same size, written again
        return body

    monkeypatch.setattr(videos, "_key_body", rewritten)
    assert videos.content_key(path) is None, "modified during the read"

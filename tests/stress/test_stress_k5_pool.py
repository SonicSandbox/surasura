"""Stress (opt-in: `python run_tests.py --stress`): the look's writing threads (K5 C2, `sources._write_parts_at_once`)
given many books' parts at once, some writes failing at random, by pools of one to four threads. What must hold whatever
the interleaving: the call ends only once every write it started has ended (nothing written behind its back after it
returns or raises); on success every part is on disk whole; after a failure only parts that were started are on disk,
each whole (how many started before the cancel is the machine's: a busy one lets the worker start more). No timing is
asserted.

Real Japanese chapters (tests/Test Resources) as the parts' bytes."""
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import sources

ROUNDS = 150


def _chapters():
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources", "ja")
    text = "".join(open(os.path.join(folder, name), encoding="utf-8").read()
                   for name in sorted(os.listdir(folder)) if name.endswith(".txt"))
    return [text[i:i + 4000].encode("utf-8") for i in range(0, min(len(text), 40000), 4000)] or ["第一章".encode()]


@pytest.mark.parametrize("threads", [1, 2, 4])
def test_parts_written_by_many_threads_end_with_the_call_whole_or_not_at_all(tmp_path, monkeypatch, threads):
    chapters = _chapters()
    real = sources._write_part
    seed = random.randrange(1 << 30)
    rnd = random.Random(seed)
    started, lock, failing = [], threading.Lock(), set()

    def write(part, data):
        with lock:
            started.append(part)
        if part in failing:
            raise OSError("the disk said no")
        return real(part, data)
    monkeypatch.setattr(sources, "_write_part", write)
    with ThreadPoolExecutor(threads) as pool:
        for r in range(ROUNDS):
            folder = tmp_path / f"book-{r}"
            folder.mkdir()
            jobs = [(str(folder / f"{n}.part"), rnd.choice(chapters)) for n in range(rnd.randint(2, 9))]
            failing.clear()
            if rnd.random() < 0.5:
                failing.add(rnd.choice(jobs)[0])
            started.clear()
            try:
                sources._write_parts_at_once(pool, jobs)
                ok = True
            except OSError:
                ok = False
            ran = list(started)                         # every write the call started, frozen as it returned
            on_disk = sorted(str(folder / name) for name in os.listdir(folder))
            idle = threading.Barrier(threads + 1)       # every worker at the barrier: none can still be writing
            for _ in range(threads):
                pool.submit(idle.wait, 30)
            idle.wait(30)
            assert sorted(str(folder / name) for name in os.listdir(folder)) == on_disk, \
                f"seed {seed} round {r}: a part written after the call ended"
            assert started == ran, f"seed {seed} round {r}: a write started after the call ended"
            if ok:
                assert not failing and on_disk == sorted(p for p, _d in jobs), f"seed {seed} round {r}"
            else:
                assert failing and set(on_disk) <= set(ran) - failing, f"seed {seed} round {r}: a part not started"
            for part, data in jobs:
                if part in on_disk:
                    with open(part, "rb") as f:
                        assert f.read() == data, f"seed {seed} round {r}: {part} not whole"

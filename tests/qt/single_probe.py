"""One start of the window's single-instance claim, for tests/qt/test_single_instance.py's races (offscreen, its own
pipe name and test root from the environment). Prints one line: `first <activations>` after `HOLD` seconds of
listening, or how it ended (`handed-over`, `gave-up`)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
assert os.environ.get("SURASURA_TEST_ROOT"), "a probe never runs against the real local data folder"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.qt.single import SingleInstance  # noqa: E402

app = QApplication(sys.argv[:1])
# A start line: both starts claim at the same moment, however long each took to load Qt (a cold CI runner once took
# longer than the first's whole hold, so the two never overlapped and both were, correctly, first).
barrier = os.environ.get("PROBE_BARRIER")
if barrier:
    open(os.path.join(barrier, f"ready-{os.getpid()}"), "w").close()
    deadline = time.monotonic() + 60
    while len(os.listdir(barrier)) < int(os.environ.get("PROBE_PARTIES", "2")) and time.monotonic() < deadline:
        time.sleep(0.005)
instance = SingleInstance()
if instance.claim(sys.argv[1:], wait=float(os.environ.get("PROBE_WAIT", "10"))):
    activations = []
    instance.activated.connect(activations.append)
    end = time.monotonic() + float(os.environ.get("HOLD", "2"))
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    print(f"first {len(activations)}", flush=True)
    instance.release()
else:
    print(instance.outcome, flush=True)

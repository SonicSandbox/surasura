"""A test's Python child: no browser or viewer opens from it (open_guard.py). Found first on the child's PYTHONPATH,
which the test harness gives every Python child of Surasura's code; this folder holds nothing else, so it shadows no
module. A sitecustomize further along the path (a test's own hook) still runs, after the guard."""
import os
import sys

try:
    import open_guard
    open_guard.install(qt=False)
except Exception as e:          # never stop the child: say it, and the run's own checks go on
    sys.stderr.write(f"tests/open_guard_site: the open guard couldn't install ({e!r})\n")

_here = os.path.normcase(os.path.dirname(os.path.abspath(__file__)))
for _folder in sys.path:
    _hook = os.path.join(_folder or os.getcwd(), "sitecustomize.py")
    _there = os.path.dirname(os.path.abspath(_hook))
    if (os.path.normcase(_there) != _here and os.path.isfile(_hook)
            and not os.path.isfile(os.path.join(_there, "open_guard.py"))):     # a copy of this folder: never chained
        import runpy
        runpy.run_path(_hook, run_name="sitecustomize")
        break

"""A test's Python child: no browser or viewer opens from it (open_guard.py). Found first on the child's PYTHONPATH,
which the test harness gives every Python child; this folder holds nothing else, so it shadows no module."""
try:
    import open_guard
    open_guard.install(qt=False)
except Exception as e:          # never stop the child: say it, and the run's own checks go on
    import sys
    sys.stderr.write(f"tests/open_guard_site: the open guard couldn't install ({e!r})\n")

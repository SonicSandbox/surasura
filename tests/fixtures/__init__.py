"""Test data the suites share (W2.2 on): the synthetic window seed and the stand-in store."""

from tests import user_bases

# A probe that builds the seed by hand (no pytest, no harness) reads per-user folders as the window does — a row asks
# whether Connect's setup record exists, which makes %LOCALAPPDATA%\Houseki\Surasura\<install key>: the bases move to
# a folder of its own first, removed when it exits (tests/user_bases.py). Under pytest the harness already moved them.
user_bases.isolate()

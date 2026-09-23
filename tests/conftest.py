"""Make an uninstalled checkout importable by the tests.

Two things a test run needs that a bare `git clone` does not provide, both
found by the first real CI runs on 260923 and neither reproducible on a
developer machine where fiducial happens to be pip-installed.

**The repo root on `sys.path`.** `run_all.py` hands pytest the `tests/`
directory, so that becomes the rootdir and the repo root is never added.
Most test files insert it themselves; `test_pytest_plugin.py` and
`test_pointers.py` did not, and those are precisely the two that failed.
Doing it here covers every file, including ones not written yet. Subprocess
tests need it too -- `test_pointers.py` runs `python -m fiducial check` in a
temp directory that inherits neither this edit nor a usable cwd -- so it also
goes into `PYTHONPATH`.

**The pytest plugin.** `pytester` starts a real pytest session, which finds
the plugin through the `pytest11` entry point that only a pip install creates.
The CI workflow runs the suite *before* installing, on purpose, to prove the
package is stdlib-only.

Registering it from here has one trap, and it is the reason this file says
`fiducial` rather than the module path. pluggy keys plugins by name: adding
`fiducial.pytest_plugin` where the entry point already registered the same
module as `fiducial` raises

    ValueError: Plugin already registered under a different name

which kills the entire session -- the collision the plugin itself hit on
260922. Using the entry point's own name makes the second registration a
no-op instead of a crash, so this works identically installed or not.

What is deliberately NOT proven here is that the entry point is wired, since
this file papers over its absence. The workflow proves that separately, after
installing, by grepping `pytest --help`. A test that needs the package
installed cannot also be the test that it installs correctly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_existing = os.environ.get("PYTHONPATH", "")
if str(_ROOT) not in _existing.split(os.pathsep):
    os.environ["PYTHONPATH"] = (
        f"{_ROOT}{os.pathsep}{_existing}" if _existing else str(_ROOT)
    )


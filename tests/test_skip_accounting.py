"""A test may skip for something the environment lacks, and for nothing else.

Why this needed its own decision
--------------------------------
The floor counts what *executed*, deliberately. Rule (5)'s two corpus-dependent
tests therefore put every corpus-less checkout below it and failed a suite that
was perfectly healthy -- which is every CI run and every fresh clone. Measured:
`191 passed, 2 skipped`, floor 193, exit 1.

The wrong fixes, and why
------------------------
- **Count skips as executions.** The floor stops meaning "ran" and every future
  skip is free. That is the equivalence this package exists to refuse.
- **Lower the floor to 191.** The two corpus tests could then stop running on
  the machine that *does* have the corpus, and nothing would say so.
- **Compute the floor per environment.** A bound derived from the thing it
  bounds is not a bound -- measured here once already, when a probe deleted a
  test file and the suite went 91 -> 41 still exiting 0.
- **Allow a fixed NUMBER of skips.** Tried, shipped, and broken by the build
  matrix the same day: 3 skips on 3.13 and 16 on 3.10, because one
  `skipif(sys.version_info < (3, 11))` guards a 12-case `parametrize`. Both
  counts are right for their interpreter and no constant is right for both.

What is here instead: a skip is accepted when its REASON names something the
environment cannot supply -- the private corpus, an uninstalled `pre-commit`,
a stdlib module that does not exist before 3.11. The reasons are listed in
`run_all.ALLOWED_SKIP_REASONS`, in the diff, and a skip for any other reason
still fails the run. That is the property the count was protecting, stated
directly instead of approximated by a number somebody has to maintain.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: This file is excluded from the copies it makes. Without that exclusion the
#: copy contains these same tests, whose run makes another copy, and the suite
#: forks without bound -- measured the first time this file ran: 1500+ temp
#: directories before it was killed.
#:
#: `test_pytest_plugin.py` goes too, for a sharper reason: `pytester` finds the
#: plugin through the installed `pytest11` entry point, which names the REAL
#: checkout's module. Inside a copy that resolves to a different copy of the
#: package, so those eleven tests fail there however healthy they are -- and
#: their output lands in the parent's stdout, which is how CI once reported
#: eleven failures for a suite whose only real failure was this file.
IGNORE = shutil.ignore_patterns(
    ".git",
    "__pycache__",
    ".pytest_cache",
    "*.egg-info",
    Path(__file__).name,
    "test_pytest_plugin.py",
)


def _runner():
    """`run_all.py` imported as a module, for checking its logic directly."""
    spec = importlib.util.spec_from_file_location(
        "run_all", REPO / "tests" / "run_all.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    """Run the suite with HOME pointed somewhere empty, i.e. no corpus."""
    env = dict(os.environ)
    env["HOME"] = env["USERPROFILE"] = str(home)
    return subprocess.run(
        [sys.executable, "tests/run_all.py"],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


def _checkout(tmp: Path, home: Path) -> Path:
    """A copy of the repo to mutate, so probes never touch the real tree.

    The copy's floor is MEASURED from the copy, before anything is mutated.
    An earlier version derived it by subtracting hand-maintained constants;
    one drifted, the copy's floor came out too low, and the shrink probe
    stopped failing on a suite that had genuinely lost three tests. The
    probe's own bookkeeping had disabled the probe.
    """
    dst = tmp / "pg"
    shutil.copytree(REPO, dst, ignore=IGNORE)

    # Two passes: the runner checks `defined` BEFORE running pytest, so with
    # this file absent a single pass exits early and never prints a count.
    floor = dst / "tests" / "EXPECTED_TESTS"
    floor.write_text("executed = 0\ndefined  = 0\n", encoding="utf-8")

    baseline = _run(dst, home)
    executed = re.search(r"pytest executed (\d+) test", baseline.stdout)
    defined = re.search(r"defined=\s*(\d+)", baseline.stdout.split("TOTAL")[-1])
    assert executed and defined, baseline.stdout + baseline.stderr
    floor.write_text(
        f"executed = {executed.group(1)}\ndefined  = {defined.group(1)}\n",
        encoding="utf-8",
    )
    return dst


@pytest.fixture
def empty_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


# --- the reason list, checked directly ------------------------------------


def test_an_environmental_skip_is_accepted() -> None:
    """Each listed reason, in the shape pytest actually prints it."""
    mod = _runner()
    out = (
        "SKIPPED [1] tests/test_pointers.py:185: reference corpus not on this machine\n"
        "SKIPPED [1] tests/test_precommit_framework.py:32: pre-commit not installed; "
        "the framework path is unproven here\n"
        "SKIPPED [12] tests/test_config.py:43: no tomllib to compare against\n"
    )
    assert mod._unexplained_skips(out) == []


def test_a_skip_for_any_other_reason_fails() -> None:
    """The property the old count was protecting, stated directly."""
    mod = _runner()
    out = (
        "SKIPPED [1] tests/test_pointers.py:185: reference corpus not on this machine\n"
        "SKIPPED [1] tests/test_literals.py:9: flaky, look at this later\n"
    )
    unexplained = mod._unexplained_skips(out)
    assert len(unexplained) == 1
    assert "flaky" in unexplained[0], "the reason is reported, not just a count"


def test_the_reasons_are_committed_in_the_source() -> None:
    """A tolerance that can be widened without review is not a tolerance."""
    src = (REPO / "tests" / "run_all.py").read_text(encoding="utf-8")
    assert "ALLOWED_SKIP_REASONS = (" in src
    for reason in ("reference corpus", "pre-commit not installed", "no tomllib"):
        assert f'"{reason}"' in src


def test_the_parsers_read_only_the_summary_line() -> None:
    """Counting every `N passed` in stdout summed the subprocesses too.

    Measured 260923: 571 reported where 202 ran, because the probes below
    print the output of the runs they make. A miscount that inflates satisfies
    the floor for entirely the wrong reason.
    """
    mod = _runner()
    nested = (
        "5 passed, 1 skipped in 0.10s\n"
        "some other output\n"
        "196 passed, 3 skipped in 19.81s\n"
    )
    assert mod._parse_pytest_total(nested) == 196
    assert mod._parse_pytest_skipped(nested) == 3


# --- and end to end, against a real checkout -------------------------------


def test_a_corpus_less_checkout_passes(tmp_path: Path, empty_home: Path) -> None:
    """The case that made this necessary: CI, and anyone who clones the repo."""
    r = _run(_checkout(tmp_path, empty_home), empty_home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "not environmental" not in r.stdout + r.stderr


def test_a_real_shrink_still_fails_without_the_corpus(
    tmp_path: Path, empty_home: Path
) -> None:
    """Tests renamed out of collection must fail even where skips are excused.

    If excusing the environmental skips also excused three deleted tests, the
    allowance would be the hole it is meant to be guarding.
    """
    repo = _checkout(tmp_path, empty_home)
    target = repo / "tests" / "test_literals.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace("def test_", "def notatest_", 3),
        encoding="utf-8",
    )
    r = _run(repo, empty_home)
    assert r.returncode != 0, "a suite that lost three tests reported success"

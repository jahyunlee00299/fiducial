"""Run every test in this directory, and refuse to be silent about how many ran.

Why this file exists
--------------------
Measured 260922: `tests/test_docs.py` is written in pytest style (fixtures,
``parametrize``, ``pytest.raises``) while the other four are self-running
stdlib scripts with a ``__main__`` block listing their cases.  CI ran every
file as ``python tests/test_<x>.py``.  For the pytest-style file that imports
the module, defines 28 functions, calls none of them, and exits 0.

So 28 of 70 test functions -- the whole of rule (4) -- were counted as passing
without executing.  A deliberately broken assertion in that file still exited
0 via the CI path and failed only under pytest.  That is precisely the failure
this package exists to name: a check that cannot fail, read as evidence.

The fix is not "make every file stdlib-style".  It is to run the suite through
a runner that *collects*, and then to **assert the collected count**, because a
runner that silently collects nothing looks exactly like a runner that passes.

Two paths, deliberately
-----------------------
``pytest``      -- the real path.  Collects both styles; the stdlib-style files
                   expose plain ``test_*`` functions, so pytest runs them too.
``--stdlib``    -- the fallback for an environment with no pytest at all.  It
                   runs the four self-running files and **reports the shortfall
                   out loud** rather than implying the suite is complete.

Either way the count is printed and compared against a floor.  A suite that
shrinks silently is the bug; the floor is what makes the shrink loud.

The floor is COMMITTED, not computed
------------------------------------
The first version of this file derived the floor from the files it was about to
run.  A refutation probe deleted one test file and renamed one test function out
of collection: the suite went 91 -> 41 and still exited 0, because the floor had
shrunk with it.  A bound computed from the thing it is bounding is not a bound.

So the floor lives in ``tests/EXPECTED_TESTS`` -- one committed number, in the
diff, reviewed like anything else.  It is a ratchet in the same sense as rule
(3)'s coverage baseline: raise it when tests are added, and lowering it has to
be a deliberate edit somebody signs off on rather than a silent side effect of
deleting a test.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: Why a test is allowed not to run: something the ENVIRONMENT cannot supply,
#: never something the code chose. Matched against pytest's own skip reasons.
#:
#: A fixed count was tried first and does not survive contact with a build
#: matrix. Measured 260923: 3 skips on 3.13, 16 on 3.10, because one
#: `skipif(sys.version_info < (3, 11))` guards a 12-case `parametrize` that
#: compares the fallback reader against `tomllib`. Both numbers are correct
#: for their interpreter, and no single constant is right for both.
#:
#: Matching the reason instead says what actually matters -- every skip names
#: a missing corpus, a missing tool, or a missing stdlib module -- while a
#: skip added for any other reason still fails the run, which is the property
#: the count was there to protect.
ALLOWED_SKIP_REASONS = (
    "reference corpus",          # the private corpus, absent everywhere but one machine
    "pre-commit not installed",  # the framework path is genuinely unproven without it
    "no tomllib",                # 3.10 has no stdlib TOML to differential-test against
    "not a git checkout",        # a copied tree has no .git; CI does, and asserts so
    "PEtab corpus",              # 35 public models, cloned locally, absent in CI
    "no PyYAML",                 # the differential test needs a second reader
)

#: The committed floor: how many tests this suite is known to execute.  Read
#: from a file rather than computed, because a floor derived from the files
#: under test drops whenever a test is removed -- measured, and it let a
#: 91 -> 41 collapse exit 0.
FLOOR_FILE = HERE / "EXPECTED_TESTS"


def declared_counts() -> dict[str, tuple[int, int]]:
    """Per file: (test functions defined, test functions a bare `python <file>` runs).

    The second number is what CI used to measure.  Reading it from the source
    rather than from a run is deliberate: it is the number that was wrong, and
    it must be visible next to the number that is right.
    """
    out: dict[str, tuple[int, int]] = {}
    for path in sorted(HERE.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defined = {
            n.name
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        }
        listed: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and isinstance(node.iter, (ast.List, ast.Tuple)):
                listed |= {e.id for e in node.iter.elts if isinstance(e, ast.Name)}
        out[path.name] = (len(defined), len(listed & defined))
    return out


def read_floor() -> tuple[int, int] | None:
    """The committed floors: (executed tests, defined test functions).

    Two numbers, because they are in different units and each catches a
    different way of losing coverage:

    * **executed** -- what pytest actually ran.  ``parametrize`` expands one
      function into several cases, so this is larger than the function count
      (91 vs 70 here).  It drops when collection silently narrows.
    * **defined** -- test functions present in the source.  It drops when a
      test is deleted or renamed out of collection.

    Comparing one against the other is a unit error.  The first version of this
    file did exactly that and failed a clean suite, which is how the two got
    separated.
    """
    if not FLOOR_FILE.is_file():
        return None
    nums: list[int] = []
    for line in FLOOR_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        try:
            nums.append(int(val.strip() if val else key))
        except ValueError:
            return None
    if len(nums) != 2:
        return None
    return nums[0], nums[1]


def report_shape() -> int:
    """Print how each file is wired, and return the total defined."""
    counts = declared_counts()
    width = max(len(n) for n in counts)
    total_defined = total_self = 0
    for name, (defined, self_run) in counts.items():
        total_defined += defined
        total_self += self_run
        flag = ""
        if defined and not self_run:
            flag = "  <- pytest-style: a bare `python <file>` runs NONE of these"
        print(f"  {name:<{width}}  defined={defined:3d}  self-running={self_run:3d}{flag}")
    print(f"  {'TOTAL':<{width}}  defined={total_defined:3d}  self-running={total_self:3d}")
    return total_defined


def run_pytest(floor: int) -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(HERE), "-q", "-rs"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print(proc.stdout)
    if proc.stderr.strip():
        print(proc.stderr, file=sys.stderr)

    collected = _parse_pytest_total(proc.stdout)
    if collected is None:
        print(
            "run_all: could not read a test count out of pytest's output. "
            "Treating that as a failure -- an unreadable count is not a pass.",
            file=sys.stderr,
        )
        return 2
    skipped = _parse_pytest_skipped(proc.stdout)
    print(
        f"run_all: pytest executed {collected} test(s); floor is {floor}."
        + (f" {skipped} skipped." if skipped else "")
    )

    # A skip is NOT an execution, and the floor deliberately does not count
    # one. But a test that CANNOT run here has not stopped working, and
    # failing the run for it would fail every clean checkout and half a build
    # matrix. So skips are allowed when they name an environmental cause, and
    # the reasons are listed above rather than counted.
    unexplained = _unexplained_skips(proc.stdout)
    if unexplained:
        print(
            "run_all: skipped for a reason that is not environmental:",
            file=sys.stderr,
        )
        for reason in unexplained:
            print(f"    {reason}", file=sys.stderr)
        print(
            "A skip is a test that stopped running. If the environment "
            "genuinely cannot supply it, add the reason to "
            "ALLOWED_SKIP_REASONS so it sits in the diff.",
            file=sys.stderr,
        )
        return 1

    if collected + skipped < floor:
        print(
            f"run_all: only {collected} test(s) ran ({skipped} skipped) but "
            f"{floor} are expected. A suite that shrinks without anyone "
            "deleting a test is collecting less than it should -- that is "
            "the bug.",
            file=sys.stderr,
        )
        return 1
    return proc.returncode


def _summary_line(text: str) -> str | None:
    """pytest's own final summary line, and only that one.

    Measured 260923: scanning the whole of stdout counted 571 tests where 198
    ran. `tests/test_skip_accounting.py` runs pytest in a subprocess and prints
    what it got, so the parent's stdout contains several summary lines and
    summing across all of them adds up the children too. The floor then reads
    as satisfied for entirely the wrong reason -- a miscount that inflates is
    no better than one that deflates.

    pytest's summary is always the LAST line carrying a duration, so that is
    what is taken.
    """
    import re

    for line in reversed(text.splitlines()):
        if re.search(r"\b(passed|failed|error|errors|xfailed|xpassed|skipped)\b", line) \
           and re.search(r"\bin\s[\d.]+s", line):
            return line
    return None


def _parse_pytest_total(text: str) -> int | None:
    """Sum passed/failed/error/xfail out of pytest's summary line."""
    import re

    line = _summary_line(text)
    if line is None:
        return None
    total = None
    for word in ("passed", "failed", "error", "errors", "xfailed", "xpassed"):
        for m in re.finditer(rf"(\d+)\s+{word}\b", line):
            total = (total or 0) + int(m.group(1))
    return total


def _parse_pytest_skipped(text: str) -> int:
    """How many tests pytest reported as skipped.

    Counted separately from the total because a skip is not an execution. The
    floor stays a count of what RAN; this number only ever excuses the skips
    whose reason names something the environment cannot supply.
    """
    import re

    line = _summary_line(text)
    if line is None:
        return 0
    return sum(int(m.group(1)) for m in re.finditer(r"(\d+)\s+skipped\b", line))


def _unexplained_skips(text: str) -> list[str]:
    """Skip reasons in `-rs` output that no entry in ALLOWED_SKIP_REASONS covers.

    Returns the reasons themselves, not a count: a number tells you something
    went quiet, the reason tells you what.
    """
    import re

    out = []
    for line in text.splitlines():
        m = re.match(r"SKIPPED \[\d+\]\s*(.+)", line.strip())
        if not m:
            continue
        reason = m.group(1)
        if not any(ok in reason for ok in ALLOWED_SKIP_REASONS):
            out.append(reason)
    return out


def run_stdlib(floor: int) -> int:
    """No pytest available. Run what can run, and say what could not."""
    counts = declared_counts()
    ran = failed = 0
    skipped_files: list[tuple[str, int]] = []
    for name, (defined, self_run) in counts.items():
        if defined and not self_run:
            skipped_files.append((name, defined))
            continue
        proc = subprocess.run(
            [sys.executable, str(HERE / name)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        print(f"=== {name} ===")
        print(proc.stdout.strip())
        if proc.returncode != 0:
            failed += 1
            print(proc.stderr, file=sys.stderr)
        ran += self_run

    print(f"\nrun_all (--stdlib): {ran} of {floor} defined test(s) executed.")
    if skipped_files:
        # The whole point. Never let this read as a clean run.
        print(
            "run_all: the following file(s) are pytest-style and were NOT run "
            "by this fallback. They are UNCHECKED here, not passing:",
            file=sys.stderr,
        )
        for name, defined in skipped_files:
            print(f"  {name}: {defined} test(s) unchecked", file=sys.stderr)
        print(
            "run_all: install pytest and re-run without --stdlib for the real "
            "suite. Exiting 2 (cannot check), not 0.",
            file=sys.stderr,
        )
        return 2
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    print("test suite shape:")
    defined = report_shape()
    print()

    if "--write-floor" in argv:
        # Run once, on adoption or after deliberately adding tests. Writing the
        # floor is a separate act from checking it, so that the number that
        # guards the suite is never produced by the same run it is guarding.
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(HERE), "-q", "-rs"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        print(proc.stdout)
        executed = _parse_pytest_total(proc.stdout)
        if proc.returncode != 0 or executed is None:
            print("run_all: refusing to record a floor from a run that did not "
                  "pass cleanly.", file=sys.stderr)
            return 2
        FLOOR_FILE.write_text(
            "# Two floors, in two different units. A ratchet: raise them when\n"
            "# tests are added. Lowering either must be a deliberate, reviewed\n"
            "# edit -- never a silent side effect of deleting a test.\n"
            f"executed = {executed}\n"
            f"defined  = {defined}\n",
            encoding="utf-8",
        )
        print(f"run_all: recorded floors executed={executed} defined={defined} "
              f"in {FLOOR_FILE.name}")
        return 0

    floors = read_floor()
    if floors is None:
        print(
            f"run_all: no usable floor in {FLOOR_FILE}. Without it a suite that "
            "collects nothing is indistinguishable from one that passes, which "
            "is the whole failure this runner exists to catch. Create it with "
            "--write-floor. Exiting 2 (cannot check), not 0.",
            file=sys.stderr,
        )
        return 2

    executed_floor, defined_floor = floors

    if defined < defined_floor:
        # Caught before running anything: test functions were removed from the
        # source. Deleting a test and its floor in one commit is allowed; doing
        # it silently is what this catches.
        print(
            f"run_all: only {defined} test function(s) are defined but the "
            f"committed floor is {defined_floor}. Tests were removed. If that "
            "was intended, lower the floor in the same commit so the decision "
            "is in the diff.",
            file=sys.stderr,
        )
        return 1

    floor = executed_floor

    if "--stdlib" in argv:
        return run_stdlib(floor)
    try:
        import pytest  # noqa: F401
    except ImportError:
        print(
            "run_all: pytest is not installed. Falling back to the stdlib "
            "runner, which cannot execute the pytest-style file(s) above.",
            file=sys.stderr,
        )
        return run_stdlib(floor)
    return run_pytest(floor)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""pytest plugin: rule (3) against the tests that actually ran.

    pytest --fiducial-spec .fiducial/params_spec.yaml

What this adds over `fiducial coverage`
-----------------------------------------
The CLI reads the test tree as source.  It answers "is there an assertion
somewhere in these files that names this key", which is a static question, and
it is the right one for a pre-commit hook scanning staged files.

Inside a pytest session a second question becomes answerable, and the CLI
cannot reach it: **was that test collected and did it run?**  Those differ more
often than they look:

* a test skipped by a marker, a missing dependency, or a platform guard
* a test deselected by ``-k``, ``-m`` or a ``--lf`` rerun
* a test in a file that failed to import, so the whole module is an error and
  every gate it held is gone
* a test in a directory ``testpaths`` no longer covers

In every one of those the source still contains the assertion, so rule (3) is
satisfied and the parameter reads as gated -- while nothing checked it on this
run.  That is the package's own thesis one level up: a gate that did not
execute is evidence of nothing, and the suite is green either way.

So the plugin reports **two numbers**, and the gap between them is the finding:

    fiducial rule (3): 49 declared keys
      gated in source : 38
      gated by a test that RAN this session : 31
      -> 7 key(s) gated only by tests that did not run

What it deliberately does not claim
-----------------------------------
That a test *ran* says nothing about whether its assertion is sensitive to the
parameter.  The reference corpus holds three keys set by a test that asserts
``rate == 0`` at a manufactured equilibrium where the numerator is structurally
zero -- the assertion holds for any value they take.  That is mutation
testing's question, and mutation testing answers it by running the suite with
the value changed.  This plugin does not attempt it, and neither does rule (3).

The mapping from a test to the keys it gates is the same static one rule (3)
already uses, so every caveat in ``coverage.py`` applies unchanged: a
MENTIONED verdict means "no gate found by the patterns implemented here", not
"no gate".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from . import config as _config
from . import coverage as _coverage


def pytest_addoption(parser) -> None:
    group = parser.getgroup("fiducial")
    group.addoption(
        "--fiducial-spec",
        action="store",
        default=None,
        metavar="PATH",
        help="YAML spec declaring measured parameters. Reports which of them "
        "are gated only by tests that did not run this session.",
    )
    group.addoption(
        "--fiducial-strict",
        action="store_true",
        default=False,
        help="fail the session when a declared key has no gate among the "
        "tests that ran.",
    )
    parser.addini(
        "fiducial_spec",
        "YAML spec declaring measured parameters (see --fiducial-spec).",
        default="",
    )


class FiducialPlugin:
    """Collects which test files actually ran, then re-runs rule (3) over them."""

    def __init__(self, spec: Path, field: str, strict: bool) -> None:
        self.spec = spec
        self.field = field
        self.strict = strict
        #: Files holding at least one test that EXECUTED. Skips and errors are
        #: excluded on purpose -- a skipped test gates nothing on this run.
        #: (file, test function name) pairs, NOT just files.
        #:
        #: File granularity is not enough, and this was measured rather than
        #: reasoned: with `-k alpha` deselecting `test_beta`, a file-level
        #: count still reported both keys as gated, because `test_alpha` in
        #: the same file kept the whole file in the "ran" set. The gap the
        #: plugin exists to report was invisible at that resolution.
        self.ran: set[tuple[Path, str]] = set()
        self.collected: set[Path] = set()
        self.failed_to_import: set[Path] = set()
        self._verdict: dict | None = None

    # -- collection -------------------------------------------------------
    def pytest_collection_modifyitems(self, items) -> None:
        for item in items:
            try:
                self.collected.add(Path(str(item.fspath)).resolve())
            except Exception:
                continue

    def pytest_collectreport(self, report) -> None:
        # A module that would not import is not "no tests" -- it is a module
        # whose gates all vanished, which is exactly the case that otherwise
        # reads as a clean run.
        if report.failed and getattr(report, "fspath", None):
            try:
                self.failed_to_import.add(Path(str(report.fspath)).resolve())
            except Exception:
                pass

    # -- execution --------------------------------------------------------
    def pytest_runtest_logreport(self, report) -> None:
        if report.when != "call":
            return
        if report.outcome not in ("passed", "failed"):
            return          # skipped / xfailed gate nothing on this run
        try:
            path = Path(str(report.fspath)).resolve()
        except Exception:
            return
        # `nodeid` is "tests/test_x.py::test_name" or
        # "...::TestClass::test_name[param]". The function name is what the
        # AST pass can match, so strip the parametrisation and take the last
        # component.
        name = report.nodeid.rsplit("::", 1)[-1].split("[", 1)[0]
        self.ran.add((path, name))

    # -- verdict ----------------------------------------------------------
    def verdict(self) -> dict:
        """Compute once; both the summary and the exit status read this.

        Deliberately NOT computed inside `pytest_terminal_summary`. That hook
        is invoked from *inside* the terminal reporter's own
        `pytest_sessionfinish`, so a plugin setting a flag there and reading
        it from its own `pytest_sessionfinish` gets the ordering wrong --
        measured: strict mode printed its message and still exited 0, a gate
        that reports and does not block. Caching the verdict makes the hook
        order irrelevant instead of relying on `trylast`.
        """
        if self._verdict is not None:
            return self._verdict

        try:
            keys = _coverage.load_declared_keys(self.spec, self.field)
        except (OSError, ValueError) as exc:
            self._verdict = {"error": str(exc), "failed": True}
            return self._verdict

        in_source = self._gated(keys, sorted(self.collected | self.failed_to_import))
        in_ran = self._gated_by_executed(keys)
        self._verdict = {
            "error": None,
            "keys": keys,
            "in_source": in_source,
            "in_ran": in_ran,
            "phantom": sorted(in_source - in_ran),
            "ungated": [k for k in keys if k not in in_ran],
            "failed": bool(self.strict and [k for k in keys if k not in in_ran]),
        }
        return self._verdict

    # -- report -----------------------------------------------------------
    def pytest_terminal_summary(self, terminalreporter) -> None:
        write = terminalreporter.write_line
        v = self.verdict()

        if v["error"]:
            write("")
            write(f"fiducial rule (3): cannot check -- {v['error']}", red=True)
            return

        keys, in_source, in_ran = v["keys"], v["in_source"], v["in_ran"]
        phantom, ungated = v["phantom"], v["ungated"]

        write("")
        write(f"fiducial rule (3): {len(keys)} declared key(s)")
        write(f"  gated in source                        : {len(in_source)}")
        write(f"  gated by a test that RAN this session  : {len(in_ran)}")

        if phantom:
            write(
                f"  -> {len(phantom)} key(s) gated ONLY by tests that did not run:",
                yellow=True,
            )
            for key in phantom:
                write(f"       {key}", yellow=True)
            if self.failed_to_import:
                write(
                    f"     ({len(self.failed_to_import)} module(s) failed to "
                    "import; every gate they held is gone)",
                    yellow=True,
                )
            write(
                "     A gate that did not execute is evidence of nothing. "
                "Deselection (-k/-m/--lf), a skip marker, or an import error "
                "leaves the assertion in the source while nothing checked the "
                "parameter on this run.",
            )
        elif in_source:
            write("  (every gate found in source also ran)")

        if v["failed"]:
            write(
                f"fiducial rule (3): {len(ungated)} declared key(s) have no "
                f"gate among the tests that ran: {', '.join(ungated[:8])}"
                + (" ..." if len(ungated) > 8 else ""),
                red=True,
            )

    def _gated(self, keys, files) -> set[str]:
        """The keys rule (3) counts as gated, restricted to ``files``."""
        if not files:
            return set()
        try:
            results = _coverage.analyse(keys, files, [])
        except ValueError:
            return set()
        return {r.key for r in results if not r.is_gap}

    def _gated_by_executed(self, keys) -> set[str]:
        """The same question, but only over test functions that EXECUTED.

        Rule (3)'s analyser takes files, so the executed subset is written out
        as a synthetic module per source file: module-level statements (the
        constants rule (3) follows, the imports an assert may need) plus only
        those test functions this session actually ran.

        Module-level code is kept deliberately. A project that holds its keys
        in `ENZYME_A_FITTED_KEYS = (...)` and asserts over that name would
        otherwise lose every gate the moment the constant left the picture --
        rule (3) learned that one the hard way, and dropping it here would
        re-introduce the same false gap inside the plugin.
        """
        import ast
        import tempfile

        if not self.ran:
            return set()

        by_file: dict[Path, set[str]] = {}
        for path, name in self.ran:
            by_file.setdefault(path, set()).add(name)

        written: list[Path] = []
        tmpdir = Path(tempfile.mkdtemp(prefix="fiducial_ran_"))
        for path, names in by_file.items():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError):
                continue
            kept: list[ast.stmt] = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name in names:
                        kept.append(node)
                elif isinstance(node, ast.ClassDef):
                    methods = [
                        m for m in node.body
                        if not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                        or m.name in names
                    ]
                    if any(
                        isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and m.name in names
                        for m in node.body
                    ):
                        kept.append(
                            ast.ClassDef(
                                name=node.name, bases=node.bases,
                                keywords=node.keywords, body=methods or [ast.Pass()],
                                decorator_list=[], type_params=[],
                            )
                        )
                else:
                    kept.append(node)          # imports, constants, fixtures
            if not kept:
                continue
            out = tmpdir / f"test_{len(written)}_{path.stem}.py"
            try:
                out.write_text(
                    ast.unparse(ast.Module(body=kept, type_ignores=[])),
                    encoding="utf-8",
                )
            except Exception:
                continue
            written.append(out)

        return self._gated(keys, written)


def pytest_configure(config) -> None:
    spec_opt = config.getoption("--fiducial-spec") or config.getini(
        "fiducial_spec"
    )
    if not spec_opt:
        # Also accept the project's [tool.fiducial] spec, so a repo that has
        # already declared it does not declare it twice.
        try:
            cfg = _config.load(start=Path(str(config.rootpath)))
        except _config.ConfigError:
            return
        if not cfg.spec:
            return
        spec_opt, field = cfg.spec, cfg.spec_field
    else:
        try:
            cfg = _config.load(start=Path(str(config.rootpath)))
            field = cfg.spec_field
        except _config.ConfigError:
            field = "learnable_keys"

    spec = Path(spec_opt)
    if not spec.is_absolute():
        spec = Path(str(config.rootpath)) / spec

    plugin = FiducialPlugin(
        spec, field, config.getoption("--fiducial-strict")
    )
    # NOT "fiducial": the entry point already registered THIS MODULE under
    # that name, and pluggy raises `Plugin name already registered` on the
    # collision -- an INTERNALERROR that takes down the whole session, not a
    # warning. Measured: every test in tests/test_pytest_plugin.py failed this
    # way on the first run. The session-scoped collector needs its own name.
    config.pluginmanager.register(plugin, "fiducial-session")
    config._fiducial = plugin


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Turn a strict failure into a non-zero exit status.

    `trylast` is load-bearing. `pytest_terminal_summary` is invoked from
    *inside* the terminal reporter's own `pytest_sessionfinish`, so an
    unordered hook here runs BEFORE the summary and reads a `_failed` flag
    that does not exist yet. Measured: strict mode printed its message and
    still exited 0 -- a gate that reports and does not block, which is the
    shape that gets ignored.
    """
    plugin = getattr(session.config, "_fiducial", None)
    if plugin is None:
        return
    if plugin.verdict().get("failed"):
        session.exitstatus = 1


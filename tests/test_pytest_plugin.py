"""The pytest plugin: rule (3) against the tests that actually ran.

The claim under test is narrow and it is the plugin's whole reason to exist.
`fiducial coverage` reads the test tree as source and answers "is there an
assertion here that names this key". Inside a session a second question is
answerable: did that assertion RUN? A test can be skipped, deselected by
`-k`/`-m`, dropped by `--lf`, or sit in a module that failed to import -- and
in every one of those the source still satisfies rule (3) while nothing
checked the parameter on that run.

So each test below arranges a divergence between the two numbers and asserts
the plugin reports it. A plugin that merely re-ran the CLI would pass none of
them.

These use pytest's own `pytester` fixture, which runs a real pytest session in
a temporary directory -- the plugin is exercised through the same entry point a
consumer gets, not by calling its functions.
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]


SPEC = """learnable_keys:
  - alpha
  - beta
"""


def _write_project(pytester, test_body: str, spec: str = SPEC):
    pytester.makefile(".yaml", params_spec=spec)
    pytester.makepyfile(test_gates=test_body)
    return pytester


# --------------------------------------------------------------------------
# the plugin is inert unless asked
# --------------------------------------------------------------------------

def test_silent_without_a_spec(pytester):
    """Installing fiducial must not change an unrelated project's runs."""
    pytester.makepyfile(test_x="def test_ok():\n    assert True\n")
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)
    assert "fiducial rule (3)" not in result.stdout.str()


# --------------------------------------------------------------------------
# the two numbers, and the gap between them
# --------------------------------------------------------------------------

def test_reports_both_numbers(pytester):
    _write_project(
        pytester,
        "def test_alpha():\n"
        "    alpha = 1\n"
        "    assert alpha == 1\n"
        "def test_beta():\n"
        "    beta = 2\n"
        "    assert beta == 2\n",
    )
    result = pytester.runpytest("--fiducial-spec", "params_spec.yaml")
    result.assert_outcomes(passed=2)
    out = result.stdout.str()
    assert "fiducial rule (3): 2 declared key(s)" in out
    assert "gated in source" in out
    assert "RAN this session" in out


def test_deselection_makes_a_gate_phantom(pytester):
    """-k drops a test; its assertion is still in the source.

    This is the divergence the CLI cannot see. `fiducial coverage` on this
    same tree reports both keys gated, because both assertions are there.
    """
    _write_project(
        pytester,
        "def test_alpha():\n"
        "    alpha = 1\n"
        "    assert alpha == 1\n"
        "def test_beta():\n"
        "    beta = 2\n"
        "    assert beta == 2\n",
    )
    result = pytester.runpytest(
        "--fiducial-spec", "params_spec.yaml", "-k", "alpha"
    )
    result.assert_outcomes(passed=1, deselected=1)
    out = result.stdout.str()
    assert "gated ONLY by tests that did not run" in out
    assert "beta" in out


def test_a_skipped_test_gates_nothing_on_this_run(pytester):
    _write_project(
        pytester,
        "import pytest\n"
        "def test_alpha():\n"
        "    alpha = 1\n"
        "    assert alpha == 1\n"
        "@pytest.mark.skip(reason='platform')\n"
        "def test_beta():\n"
        "    beta = 2\n"
        "    assert beta == 2\n",
    )
    result = pytester.runpytest("--fiducial-spec", "params_spec.yaml")
    result.assert_outcomes(passed=1, skipped=1)
    out = result.stdout.str()
    assert "gated ONLY by tests that did not run" in out
    assert "beta" in out


def test_everything_ran_says_so(pytester):
    """The converse. A report that only ever warns is indistinguishable from
    one that is stuck."""
    _write_project(
        pytester,
        "def test_alpha():\n"
        "    alpha = 1\n"
        "    assert alpha == 1\n"
        "def test_beta():\n"
        "    beta = 2\n"
        "    assert beta == 2\n",
    )
    result = pytester.runpytest("--fiducial-spec", "params_spec.yaml")
    out = result.stdout.str()
    assert "every gate found in source also ran" in out
    assert "gated ONLY by tests that did not run" not in out


# --------------------------------------------------------------------------
# strict mode
# --------------------------------------------------------------------------

def test_strict_fails_the_session_on_an_ungated_key(pytester):
    _write_project(
        pytester,
        "def test_alpha():\n"
        "    alpha = 1\n"
        "    assert alpha == 1\n",
    )
    result = pytester.runpytest(
        "--fiducial-spec", "params_spec.yaml", "--fiducial-strict"
    )
    result.assert_outcomes(passed=1)
    assert result.ret != 0, "strict mode did not fail the session"
    assert "no gate among the tests that ran" in result.stdout.str()


def test_without_strict_the_session_still_passes(pytester):
    """Reporting must not become blocking by accident."""
    _write_project(
        pytester,
        "def test_alpha():\n"
        "    alpha = 1\n"
        "    assert alpha == 1\n",
    )
    result = pytester.runpytest("--fiducial-spec", "params_spec.yaml")
    result.assert_outcomes(passed=1)
    assert result.ret == 0


def test_strict_passes_when_every_key_is_gated(pytester):
    _write_project(
        pytester,
        "def test_alpha():\n"
        "    alpha = 1\n"
        "    assert alpha == 1\n"
        "def test_beta():\n"
        "    beta = 2\n"
        "    assert beta == 2\n",
    )
    result = pytester.runpytest(
        "--fiducial-spec", "params_spec.yaml", "--fiducial-strict"
    )
    assert result.ret == 0


# --------------------------------------------------------------------------
# a spec that cannot be read must be loud
# --------------------------------------------------------------------------

def test_missing_spec_is_reported_not_ignored(pytester):
    pytester.makepyfile(test_x="def test_ok():\n    assert True\n")
    result = pytester.runpytest("--fiducial-spec", "nope.yaml")
    assert "cannot check" in result.stdout.str()


def test_empty_spec_is_reported(pytester):
    """A spec yielding no keys would make every check pass vacuously."""
    _write_project(
        pytester,
        "def test_ok():\n    assert True\n",
        spec="learnable_keys:\n",
    )
    result = pytester.runpytest("--fiducial-spec", "params_spec.yaml")
    assert "cannot check" in result.stdout.str()


# --------------------------------------------------------------------------
# it reads the project's own config
# --------------------------------------------------------------------------

def test_spec_can_come_from_tool_fiducial(pytester):
    """A repo that already declared `spec` must not declare it twice."""
    pytester.makefile(".yaml", params_spec=SPEC)
    pytester.makepyfile(
        test_gates="def test_alpha():\n    alpha = 1\n    assert alpha == 1\n"
    )
    pytester.makefile(
        ".toml",
        **{"pyproject": '[tool.fiducial]\nspec = "params_spec.yaml"\n'},
    )
    result = pytester.runpytest()
    assert "fiducial rule (3)" in result.stdout.str()

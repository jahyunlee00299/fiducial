"""A brand-new repo adopts fiducial with a config file and no flags.

This is the connectivity test, and it is the one that would have caught the
failure the unit tests cannot see: a setting that loads correctly, validates
correctly, and reaches no rule. Every test in `test_config.py` would still pass
with `[tool.fiducial]` wired to nothing.

So each case here runs the real CLI in a subprocess against a throwaway repo
and asserts on the exit code and the output. Three of them assert a DIFFERENCE
made by a setting -- a config that changes no outcome is a config that is not
connected.

Found while writing these, and pinned below:

* `python -m fiducial` did not work at all: the package had no
  `__main__.py`, so every probe failed until one was added. The console script
  needs an install; a hook or a CI step running from a checkout does not have
  one.
* the first version of `test_setting_absent_does_not_flag` passed while
  fiducial was completely unrunnable -- "not flagged" was true because
  nothing ran. An absence is evidence only once the run is known to have
  happened, so it now requires the rule's own summary line first. This is the
  same mistake, in a test, that the package exists to catch in a scanner.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(cwd: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "fiducial", *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    return proc.returncode, proc.stdout + proc.stderr


CONFIG = """[project]
name = "newrepo"

[tool.fiducial]
rules = ["literals", "names", "docs"]
keys = ["alpha"]
literals_paths = ["src/"]
names_paths = ["configs/"]
docs_paths = ["docs/"]
extend_self_declaring_keys = ["fit_ref"]
locales = ["en"]
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for sub in ("configs", "src", "docs"):
        (tmp_path / sub).mkdir()

    # rule (2) bait. `fit_ref` is NOT one of fiducial's default
    # self-declaring keys, and its value is a PATH -- which is exactly the
    # combination the setting governs: a path points at another artefact
    # unless the key is one that declares this file's own identity.
    (tmp_path / "configs" / "model_v3.yaml").write_text(
        "fit_ref: out/run_v4/fit.json\ndescription: legacy name, v3\n",
        encoding="utf-8",
    )
    (tmp_path / "configs" / "model_v9.yaml").write_text(
        "fit_ref: out/run_v9/fit.json\n", encoding="utf-8"
    )
    # rule (1) bait
    (tmp_path / "src" / "model.py").write_text(
        "def build(params):\n"
        "    alpha = params.get('alpha', 0.73)\n"
        "    return alpha\n",
        encoding="utf-8",
    )
    # rule (4) bait
    (tmp_path / "docs" / "SPEC.md").write_text(
        "# Spec\n\ntemperature 30\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "derived.md").write_text(
        "---\nssot:\n  source: SPEC.md\n  repeats:\n    temperature: 30\n---\n\n"
        "The step runs at temperature 45.\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------
# the whole path, no flags
# --------------------------------------------------------------------------

def test_check_with_no_flags_runs_every_configured_rule(repo):
    code, out = run(repo, "check")
    assert code == 1
    assert "alpha" in out, "rule (1) did not run from config"
    assert "model_v3" in out, "rule (2) did not run from config"
    assert "temperature" in out, "rule (4) did not run from config"


def test_output_names_the_config_it_used(repo):
    """Which file configured this run is part of the result, not a detail."""
    _, out = run(repo, "check")
    assert "config:" in out and "pyproject.toml" in out


def test_a_clean_repo_exits_zero(repo):
    """A gate that only ever says no is indistinguishable from a broken one."""
    (repo / "configs" / "model_v3.yaml").write_text(
        "fit_ref: out/run_v3/fit.json\n", encoding="utf-8")
    (repo / "src" / "model.py").write_text(
        "def build(params):\n    return params['alpha']\n", encoding="utf-8")
    (repo / "docs" / "derived.md").write_text(
        "---\nssot:\n  source: SPEC.md\n  repeats:\n    temperature: 30\n---\n\n"
        "The step runs at temperature 30.\n", encoding="utf-8")
    code, out = run(repo, "check")
    assert code == 0, out


# --------------------------------------------------------------------------
# settings that must change the outcome
# --------------------------------------------------------------------------

def test_setting_present_flags_the_file(repo):
    code, out = run(repo, "check", "--rules", "names")
    assert "model_v3" in out
    assert code == 1


def test_setting_absent_does_not_flag(repo):
    """The converse. Together these two prove the setting is connected.

    The `fiducial names:` assertion is load-bearing: without it this test
    passed while the CLI was not runnable at all.
    """
    (repo / "pyproject.toml").write_text(
        CONFIG.replace('extend_self_declaring_keys = ["fit_ref"]\n', ""),
        encoding="utf-8",
    )
    _, out = run(repo, "check", "--rules", "names")
    assert "fiducial names:" in out, "the rule did not run; silence proves nothing"
    assert "model_v3" not in out


def test_locale_selection_changes_what_is_suppressed(repo):
    """`locales` must reach rule (4), not merely validate."""
    (repo / "docs" / "derived.md").write_text(
        "---\nssot:\n  source: SPEC.md\n  repeats:\n    temperature: 30\n---\n\n"
        "이전에는 temperature 45 이었다\n",
        encoding="utf-8",
    )
    _, en_out = run(repo, "check", "--rules", "docs")
    assert "fiducial docs:" in en_out
    assert "45" in en_out, "en-only wrongly suppressed a Korean past-tense line"

    (repo / "pyproject.toml").write_text(
        CONFIG.replace('locales = ["en"]', 'locales = ["ko"]'), encoding="utf-8")
    _, ko_out = run(repo, "check", "--rules", "docs")
    assert "fiducial docs:" in ko_out
    assert "45" not in ko_out, "ko did not suppress a past-tense line"


# --------------------------------------------------------------------------
# the exit contract, aggregated
# --------------------------------------------------------------------------

def test_a_check_that_would_run_nothing_is_cannot_check(tmp_path):
    """The silence this package was built after.

    A config naming no runnable rule produces exactly the same output as a
    clean repo, so it must not produce the same exit code.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[tool.fiducial]\nrules = []\nnames_paths = []\ndocs_paths = []\n",
        encoding="utf-8",
    )
    code, out = run(tmp_path, "check")
    assert code == 2, out


def test_cannot_check_outranks_violations(repo):
    """One rule finding things does not excuse another rule not running."""
    (repo / "pyproject.toml").write_text(
        CONFIG.replace('literals_paths = ["src/"]', 'literals_paths = ["nowhere/"]'),
        encoding="utf-8",
    )
    code, out = run(repo, "check")
    assert code == 2, out


def test_a_misspelled_setting_is_reported(repo):
    """A typo leaves the default in force while the author believes otherwise."""
    (repo / "pyproject.toml").write_text(
        CONFIG.replace("literals_paths", "literal_paths"), encoding="utf-8")
    _, out = run(repo, "check")
    assert "literal_paths" in out and "NO effect" in out


def test_module_entry_point_exists(repo):
    """`python -m fiducial` must work without installing the package.

    It did not: there was no `__main__.py`, and every probe in this file
    failed with "cannot be directly executed" until one was added. A hook or
    CI step running against a checkout has no console script.
    """
    code, out = run(repo, "--help")
    assert code == 0, out
    assert "check" in out

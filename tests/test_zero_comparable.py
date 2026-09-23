"""Rule (2): files read, none comparable, is blind -- not clean.

Found 260923 by pointing `fiducial check` at fiducial's own repository:
one YAML scanned, no file carrying a version token in both its name and its
own fields, reported `names clean` and exit 0.

That was the one place this package granted itself the pass it refuses
everywhere else. Rule (1) refuses an empty `--keys`. Rule (4) refuses a corpus
where no document declares an SSOT. The CLI refuses a zero-file match. All
three on the same reasoning -- a check that cannot fail gets believed -- while
rule (2) read its files, compared none of them, and said clean.

Why this one needs an off switch and the others do not
------------------------------------------------------
Comparability here is a property of the FILES, decided after reading them, not
of the invocation. A project whose configs legitimately carry no version token
in their names would get exit 2 on every commit forever, which is the shape
that gets a guard bypassed -- and a bypassed guard protects nothing. The case
is real and is in this repo's own ledger: one project's 14 SSOT configs carry no
version tokens at all.

So the escape hatch exists, and it is deliberately a written setting rather
than a default: `names_allow_zero_comparable = true` sits in the diff where a
reviewer sees it, instead of the rule being silent by accident for a year.
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


@pytest.fixture
def unversioned(tmp_path: Path) -> Path:
    """Configs that carry no version token anywhere -- nothing to compare."""
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "alpha.yaml").write_text(
        "threshold: 3\nlabel: alpha\n", encoding="utf-8")
    (tmp_path / "configs" / "beta.yaml").write_text(
        "threshold: 4\nlabel: beta\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def versioned(tmp_path: Path) -> Path:
    """One honest file: name and fields agree. Comparable, and clean."""
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "model_v7.yaml").write_text(
        "run_id: model_v7\n", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------
# the defect
# --------------------------------------------------------------------------

def test_zero_comparable_is_cannot_check_not_clean(unversioned):
    code, out = run(unversioned, "names", "configs")
    assert code == 2, out
    assert "0 comparable" in out
    assert "blind" in out


def test_the_message_says_how_to_make_it_a_pass(unversioned):
    """An error that does not name its own remedy gets worked around."""
    _, out = run(unversioned, "names", "configs")
    assert "names_allow_zero_comparable" in out


# --------------------------------------------------------------------------
# the escape hatch, both ways
# --------------------------------------------------------------------------

def test_flag_turns_it_into_a_pass(unversioned):
    code, out = run(unversioned, "names", "--allow-zero-comparable", "configs")
    assert code == 0, out


def test_config_setting_turns_it_into_a_pass(unversioned):
    (unversioned / ".fiducial.toml").write_text(
        'names_paths = ["configs"]\nnames_allow_zero_comparable = true\n',
        encoding="utf-8",
    )
    code, out = run(unversioned, "names")
    assert code == 0, out


def test_the_setting_reaches_check_too(unversioned):
    """`check` builds each rule's namespace by hand -- a known trap.

    The ledger records it: a new CLI flag must be added in two places or
    `check` silently uses the default. This is the test that catches that.
    """
    (unversioned / ".fiducial.toml").write_text(
        'rules = ["names"]\nnames_paths = ["configs"]\n'
        'names_allow_zero_comparable = true\n',
        encoding="utf-8",
    )
    code, out = run(unversioned, "check")
    assert code == 0, out
    assert "fiducial names:" in out, "the rule did not run"


def test_check_without_the_setting_still_refuses(unversioned):
    (unversioned / ".fiducial.toml").write_text(
        'rules = ["names"]\nnames_paths = ["configs"]\n', encoding="utf-8")
    code, out = run(unversioned, "check")
    assert code == 2, out


# --------------------------------------------------------------------------
# it must not swallow the cases either side of it
# --------------------------------------------------------------------------

def test_a_comparable_clean_file_still_exits_zero(versioned):
    """A gate that only says no is indistinguishable from a broken one."""
    code, out = run(versioned, "names", "configs")
    assert code == 0, out
    assert "1 comparable" in out


def test_a_real_violation_still_exits_one(tmp_path):
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "model_v3.yaml").write_text(
        "run_id: model_v4\n", encoding="utf-8")
    code, out = run(tmp_path, "names", "configs")
    assert code == 1, out


def test_the_allow_flag_does_not_hide_a_real_violation(tmp_path):
    """The hatch covers blindness, never a finding.

    If it suppressed violations too, a project that set it once to quiet a
    legacy directory would stop being checked entirely -- the failure this
    whole rule exists to prevent, reintroduced through its own escape hatch.
    """
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "model_v3.yaml").write_text(
        "run_id: model_v4\n", encoding="utf-8")
    code, out = run(tmp_path, "names", "--allow-zero-comparable", "configs")
    assert code == 1, out


def test_zero_files_is_still_a_different_error(tmp_path):
    """"No files at all" and "files but nothing comparable" are distinct.

    Both are exit 2, but the remedies differ -- fix the paths vs. accept that
    your configs are unversioned -- so the messages must not converge.
    """
    (tmp_path / "configs").mkdir()
    code, out = run(tmp_path, "names", "configs")
    assert code == 2
    assert "matched 0 config files" in out
    assert "names_allow_zero_comparable" not in out

"""The hooks, run through the real pre-commit framework.

`.pre-commit-hooks.yaml` had sat in this repo as `declared, unproven` since the
ledger was written: the file existed and nothing had ever run it through
pre-commit.com. Declared-and-unproven is the state this package complains
about, so these tests close it.

What only the framework can prove: pre-commit builds its own isolated
virtualenv from this repo's pyproject and invokes the hook from there. That is
the part a direct CLI call cannot stand in for, and it is precisely what broke
a previous hook in this author's setup -- the comment at the top of
`.pre-commit-hooks.yaml` records it: a hook that hard-coded `python` resolved
to the wrong interpreter on one machine and blocked EVERY commit, including
clean ones.

These are skipped when pre-commit is not installed, and they build a venv on
first run, so they are slow by nature. That is the cost of proving the thing
rather than asserting it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

pre_commit = pytest.importorskip(
    "pre_commit", reason="pre-commit not installed; the framework path is unproven here"
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


@pytest.fixture(scope="module")
def head() -> str:
    rev = _git(REPO_ROOT, "rev-parse", "HEAD").stdout.strip()
    if not rev:
        pytest.skip("fiducial is not a git checkout here")
    return rev


@pytest.fixture(scope="module")
def pc_home(tmp_path_factory) -> Path:
    """One pre-commit cache for the module: the venv build is the slow part."""
    return tmp_path_factory.mktemp("pc_home")


def run_hooks(repo: Path, pc_home: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pre_commit", "run", "--all-files"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env={**os.environ, "PRE_COMMIT_HOME": str(pc_home)},
    )
    return proc.returncode, proc.stdout + proc.stderr


def make_repo(tmp_path: Path, head: str, hooks: str) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".pre-commit-config.yaml").write_text(
        f"repos:\n  - repo: {REPO_ROOT.as_posix()}\n    rev: {head}\n"
        f"    hooks:\n{hooks}",
        encoding="utf-8",
    )
    return tmp_path


BOTH_HOOKS = (
    "      - id: fiducial-names\n"
    "      - id: fiducial-literals\n"
    '        args: [--keys, "alpha"]\n'
)


# --------------------------------------------------------------------------
# the framework path works at all
# --------------------------------------------------------------------------

def test_hooks_block_a_violating_repo(tmp_path, head, pc_home):
    repo = make_repo(tmp_path, head, BOTH_HOOKS)
    (repo / "configs").mkdir()
    (repo / "configs" / "model_v3.yaml").write_text(
        "run_id: model_v4\n", encoding="utf-8")
    (repo / "model.py").write_text(
        "def build(params):\n    return params.get('alpha', 0.73)\n",
        encoding="utf-8")
    _git(repo, "add", "-A")

    code, out = run_hooks(repo, pc_home)
    assert code != 0, out
    assert "model_v3" in out, "rule (2) did not report through the framework"
    assert "alpha" in out, "rule (1) did not report through the framework"


def test_hooks_pass_a_clean_repo(tmp_path, head, pc_home):
    """A hook that only ever fails gets removed, and then protects nothing."""
    repo = make_repo(tmp_path, head, BOTH_HOOKS)
    (repo / "configs").mkdir()
    (repo / "configs" / "model_v3.yaml").write_text(
        "run_id: model_v3\n", encoding="utf-8")
    (repo / "model.py").write_text(
        "def build(params):\n    return params['alpha']\n", encoding="utf-8")
    _git(repo, "add", "-A")

    code, out = run_hooks(repo, pc_home)
    assert code == 0, out


# --------------------------------------------------------------------------
# the zero-comparable rule, through the framework
# --------------------------------------------------------------------------

def test_unversioned_repo_fails_by_default(tmp_path, head, pc_home):
    """pre-commit treats ANY non-zero exit as a failure, exit 2 included.

    So the "blind, not clean" rule has real teeth here -- and real cost, which
    is why the message has to name its own remedy.
    """
    repo = make_repo(tmp_path, head, "      - id: fiducial-names\n")
    (repo / "configs").mkdir()
    (repo / "configs" / "alpha.yaml").write_text("threshold: 3\n", encoding="utf-8")
    _git(repo, "add", "-A")

    code, out = run_hooks(repo, pc_home)
    assert code != 0
    assert "names_allow_zero_comparable" in out, (
        "the failure did not tell the adopter how to accept it -- this is the "
        "shape that gets a hook deleted rather than configured"
    )


def test_the_hatch_is_reachable_through_pre_commit_args(tmp_path, head, pc_home):
    """An escape hatch a hook cannot reach is not an escape hatch."""
    repo = make_repo(
        tmp_path, head,
        "      - id: fiducial-names\n"
        "        args: [--allow-zero-comparable]\n",
    )
    (repo / "configs").mkdir()
    (repo / "configs" / "alpha.yaml").write_text("threshold: 3\n", encoding="utf-8")
    _git(repo, "add", "-A")

    code, out = run_hooks(repo, pc_home)
    assert code == 0, out

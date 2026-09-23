"""Config discovery follows the scanned tree, not the caller's cwd.

Found 260923 by pointing `fiducial names` at a public repository
(Benchmark-Models-PEtab) from inside this package's own checkout: fiducial's
own `names_allow_zero_comparable = true` was discovered from the cwd and
applied to the foreign tree, so a rule that compared nothing exited 0. The
same command from a neutral directory exited 2. A verdict on a tree must not
depend on where the command happens to run.
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
def two_trees(tmp_path: Path) -> tuple[Path, Path]:
    """`host` permits zero-comparable; `foreign` has no config at all."""
    host = tmp_path / "host"
    host.mkdir()
    (host / ".fiducial.toml").write_text(
        "names_allow_zero_comparable = true\n", encoding="utf-8")
    foreign = tmp_path / "foreign"
    (foreign / "configs").mkdir(parents=True)
    (foreign / "configs" / "alpha.yaml").write_text(
        "threshold: 3\n", encoding="utf-8")
    return host, foreign


def test_host_config_does_not_leak_onto_a_foreign_tree(two_trees):
    host, foreign = two_trees
    code, out = run(host, "names", str(foreign / "configs"))
    assert code == 2, out
    assert "blind" in out


def test_verdict_is_the_same_from_any_cwd(two_trees, tmp_path):
    host, foreign = two_trees
    target = str(foreign / "configs")
    assert run(host, "names", target)[0] == run(tmp_path, "names", target)[0]


def test_the_scanned_trees_own_config_still_applies(two_trees):
    host, foreign = two_trees
    (foreign / ".fiducial.toml").write_text(
        "names_allow_zero_comparable = true\n", encoding="utf-8")
    code, out = run(host, "names", str(foreign / "configs"))
    assert code == 0, out


def test_a_glob_is_anchored_at_its_fixed_prefix(two_trees):
    host, foreign = two_trees
    code, out = run(host, "names", str(foreign / "configs" / "*.yaml"))
    assert code == 2, out


def test_paths_under_two_configs_refuse_rather_than_pick_one(two_trees):
    host, foreign = two_trees
    (host / "configs").mkdir()
    (host / "configs" / "beta.yaml").write_text("threshold: 4\n", encoding="utf-8")
    code, out = run(host, "names", str(host / "configs"), str(foreign / "configs"))
    assert code == 2, out
    assert "different configs" in out


def test_explicit_config_still_wins(two_trees):
    host, foreign = two_trees
    code, out = run(host, "--config", str(host / ".fiducial.toml"), "names",
                    str(foreign / "configs"))
    assert code == 0, out


def test_no_paths_still_discovers_from_cwd(two_trees):
    """`fiducial check` and bare `names` read *_paths from the cwd project."""
    host, _ = two_trees
    (host / "configs").mkdir()
    (host / "configs" / "beta.yaml").write_text("threshold: 4\n", encoding="utf-8")
    (host / ".fiducial.toml").write_text(
        'names_paths = ["configs"]\nnames_allow_zero_comparable = true\n',
        encoding="utf-8")
    code, out = run(host, "names")
    assert code == 0, out

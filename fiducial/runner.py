"""`fiducial check` -- run the configured rules in one pass.

Why this exists
---------------
Five rules, five subcommands, five different argument shapes: ``literals``
refuses to run without ``--keys``, ``coverage`` requires ``--spec`` and a test
path, ``names`` and ``docs`` take paths but different ones.  Adopting the tool
meant writing four invocations and keeping them in step with the repo layout
by hand, in every hook and every CI file that called it.

``fiducial check`` reads ``[tool.fiducial]`` and runs what the project
declared.  The per-rule subcommands stay: they are what you reach for when
investigating one finding, and what a pre-commit hook uses to scan only the
staged files of one type.

The exit contract is the package's, unchanged
---------------------------------------------
``0`` clean, ``1`` violations, ``2`` the check could not be performed.  Across
several rules the aggregation is deliberately pessimistic:

* any rule that could not run -> ``2`` for the whole command, even if another
  rule found violations.  "Could not check" outranks "checked and found
  things", because a partial scan reported as a result is the failure this
  package exists to refuse.
* otherwise any violation -> ``1``.
* ``0`` only when every configured rule ran and every one was clean.

And a ``check`` that would run NOTHING is itself exit ``2``.  A config naming
no rules, or naming rules whose paths are all empty, produces the same
reassuring silence as a clean repo, and that silence is what this package was
built after.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from . import config as _config

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_CANNOT_CHECK = 2

#: Rules `check` runs when the config does not say. Only the two that need no
#: project-specific declaration: `literals` needs keys and `coverage` needs a
#: spec, so running them unconfigured would either fail or pass vacuously.
DEFAULT_RULES = ("names", "docs")


@dataclass
class RuleOutcome:
    rule: str
    code: int
    reason: str = ""

    @property
    def label(self) -> str:
        return {
            EXIT_OK: "clean",
            EXIT_VIOLATIONS: "violations",
            EXIT_CANNOT_CHECK: "CANNOT CHECK",
        }.get(self.code, f"exit {self.code}")


def rules_to_run(cfg: _config.Config) -> tuple[str, ...]:
    """Which rules this project declared, or the safe default."""
    if cfg.rules:
        return cfg.rules
    chosen = list(DEFAULT_RULES)
    # Only add the rules that have what they need to be meaningful.
    if cfg.keys and cfg.literals_paths:
        chosen.insert(0, "literals")
    if cfg.spec and cfg.tests_paths:
        chosen.append("coverage")
    return tuple(chosen)


def aggregate(outcomes: list[RuleOutcome]) -> int:
    """Pessimistic combination. See the module docstring for why."""
    if not outcomes:
        return EXIT_CANNOT_CHECK
    if any(o.code == EXIT_CANNOT_CHECK for o in outcomes):
        return EXIT_CANNOT_CHECK
    if any(o.code == EXIT_VIOLATIONS for o in outcomes):
        return EXIT_VIOLATIONS
    return EXIT_OK


def summarise(outcomes: list[RuleOutcome], cfg: _config.Config) -> str:
    lines = ["", "fiducial check:"]
    for o in outcomes:
        suffix = f" -- {o.reason}" if o.reason else ""
        lines.append(f"  {o.rule:<9} {o.label}{suffix}")
    where = cfg.path if cfg.path else "no config file (defaults)"
    lines.append(f"  config: {where}")
    if cfg.unknown:
        # A typo in a setting name leaves the default in force while the author
        # believes they changed it. Never silent.
        lines.append(
            f"  unknown setting(s): {', '.join(cfg.unknown)} -- these had NO "
            "effect. Check the spelling against the README."
        )
    return "\n".join(lines)


def missing_paths_note(rule: str, configured: tuple[str, ...]) -> str:
    if configured:
        return f"no files matched {list(configured)}"
    return (
        f"{rule} has no paths configured. Set {rule}_paths in "
        "[tool.fiducial], or run the subcommand directly with explicit paths."
    )

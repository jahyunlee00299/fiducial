"""rule (1) — a measured quantity sitting in the source as a bare literal.

The claim this rule makes is narrow and deliberately so: *if a key is declared
to be fitted/measured, then a hard-coded value for that key is a defect*, even
when the code around it looks careful.  Two shapes matter.

``silent_fallback``
    ``params.get("eta", 1.0)`` and its relatives.  When the key is absent the
    code proceeds with a plausible number instead of stopping.  In a fitting
    pipeline that yields a *wrong fit* rather than a failure, which is strictly
    worse: the run completes, the number looks reasonable, and nothing
    distinguishes it from a real one.  This shape is already detected by
    ``params_strict_check.py`` in this author's config repo; it is reimplemented
    here so the package stands alone, and that prior implementation remains the
    reference for the spec format.

``bare_literal``
    The same constant assigned directly -- ``eta = 1.0`` -- with no provenance
    anywhere in reach.  Magic-number linters see the assignment but ask only
    "was it given a name?", which this passes trivially.  The question that
    matters is "where did the number come from?", and no linter surveyed asks
    it.

Why a key list is required, and why that is a feature
-----------------------------------------------------
Both shapes are legal, ordinary Python.  ``timeout = 30`` deserves no
complaint.  The rule only has force once a key has been *declared* to stand for
something measured, so the caller supplies that declaration and the checker
refuses to run without it.  A checker that guessed which numbers were physical
would be wrong constantly and would be switched off within a day.

This is also where the rule departs from its nearest neighbours.  drift-linter
(``drift.py`` L690-694) and scicode-lint's ``rep-003``
(``pattern.toml:51``) both treat ``dict.get(key, default)`` as the *safe* form --
absence is handled, so the code is fine.  Against a declared measured key we
invert that judgement: the default is the defect, precisely because it prevents
the loud failure that would have surfaced the missing measurement.  The
inversion is the contribution; the AST walk is not novel and a ``semgrep``
``metavariable-regex`` rule can express much of the same matching.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

#: Methods that take a "use this when the key is missing" second argument.
_FALLBACK_METHODS = {"get", "pop", "setdefault"}

#: Numbers that carry no physical claim on their own.  Flagging ``x = 0`` or a
#: ``+1`` index as an unsourced measurement is how a checker earns its way into
#: a permanent ignore list, so they are exempt regardless of the key.
_UNREMARKABLE = {0, 1, -1, 2, 100}

#: Defaults that mean "this term is switched off" (0.0) or "this scale is
#: neutral" (1.0) rather than "here is a value somebody measured".
#:
#: Measured on the reference codebase: of 705 silent-fallback hits across 1,554
#: files, 575 (82%) defaulted to exactly 0.0 or 1.0 -- `BASE.setdefault(
#: "vmax_futile_nadph", 0.0)`, `BASE.setdefault("xr_activity_scale", 1.0)`.
#: Those are a caller composing a baseline with optional terms disabled, not a
#: fabricated measurement, and reporting all 705 would bury the 130 that matter.
#:
#: This is a REPORTING split, not a silent drop: `include_neutral=True` returns
#: them, because "the term was off and nobody noticed" is a real failure mode --
#: just a different one, and one the caller should opt into looking for.
_NEUTRAL_DEFAULTS = {0.0, 1.0}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    col: int
    key: str
    kind: str          # "silent_fallback" | "bare_literal"
    snippet: str
    neutral: bool = False   # default was 0.0/1.0 -- "switched off", not a measurement

    def explain(self) -> str:
        if self.kind == "silent_fallback":
            why = (
                f"'{self.key}' is declared measured, but this supplies a default "
                "when it is absent. The run then continues on a value nobody "
                "measured, which produces a wrong result instead of a failure."
            )
        else:
            why = (
                f"'{self.key}' is declared measured, but this assigns a literal "
                "with no provenance in reach. Record where the number came from, "
                "or read it from the source that owns it."
            )
        return f"{self.path}:{self.line}:{self.col}: [{self.kind}] {why}\n    {self.snippet}"


def _literal(node: ast.AST) -> float | int | None:
    """The numeric value of ``node``, including negation; else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool):
            return None
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _literal(node.operand)
        return None if inner is None else -inner
    return None


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class _Visitor(ast.NodeVisitor):
    """Walks one module, collecting both shapes for the declared keys."""

    def __init__(
        self,
        path: Path,
        keys: frozenset[str],
        source_lines: Sequence[str],
        neutral_defaults: frozenset[float] = frozenset(_NEUTRAL_DEFAULTS),
    ):
        self.path = path
        self.keys = keys
        self.lines = source_lines
        #: Which defaults mean "this term is switched off" rather than "a
        #: measurement was invented". 0.0/1.0 here; a project whose neutral
        #: element is something else (a log-space model where it is 1.0, a
        #: ratio centred on 100) sets its own in [tool.fiducial].
        self.neutral_defaults = neutral_defaults
        self.found: list[Finding] = []

    def _snippet(self, lineno: int) -> str:
        if 1 <= lineno <= len(self.lines):
            return self.lines[lineno - 1].strip()[:160]
        return ""

    def _record(self, node: ast.AST, key: str, kind: str, neutral: bool = False) -> None:
        self.found.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                key=key,
                kind=kind,
                snippet=self._snippet(node.lineno),
                neutral=neutral,
            )
        )

    # params.get("eta", 1.0) / .pop(...) / .setdefault(...)
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _FALLBACK_METHODS
            and len(node.args) == 2
        ):
            key = _const_str(node.args[0])
            default = _literal(node.args[1])
            if key in self.keys and default is not None:
                self._record(
                    node, key, "silent_fallback",
                    neutral=default in self.neutral_defaults,
                )
        self.generic_visit(node)

    # eta = 1.0   /   self.eta = 1.0   /   eta: float = 1.0
    def visit_Assign(self, node: ast.Assign) -> None:
        self._assignment(node.targets, node.value, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Measured on the reference implementation: omitting AnnAssign made an
        # audit report "0 items" where 56 existed. Annotated assignment is the
        # same statement with a type on it.
        if node.value is not None:
            self._assignment([node.target], node.value, node)
        self.generic_visit(node)

    def _assignment(
        self, targets: Iterable[ast.AST], value: ast.AST, node: ast.AST
    ) -> None:
        val = _literal(value)
        if val is None or val in _UNREMARKABLE:
            return
        for t in targets:
            name = (
                t.id if isinstance(t, ast.Name)
                else t.attr if isinstance(t, ast.Attribute)
                else None
            )
            if name in self.keys:
                self._record(node, name, "bare_literal")

    # params["eta"] = 1.0 is an assignment through a subscript; treat the
    # subscript key as the name.
    def visit_Subscript(self, node: ast.Subscript) -> None:
        self.generic_visit(node)


def scan_source(
    path: Path,
    source: str,
    keys: Iterable[str],
    include_neutral: bool = False,
    neutral_defaults: Iterable[float] | None = None,
) -> list[Finding]:
    """Findings for ``source``.

    ``include_neutral`` adds the 0.0/1.0 defaults -- the "term switched off"
    family.  They are excluded by default because they outnumber the real hits
    roughly 4:1 on the reference codebase and drown them.
    """
    keyset = frozenset(keys)
    if not keyset:
        raise ValueError(
            "no declared keys: every check would pass vacuously. "
            "Pass the keys that stand for measured quantities."
        )
    tree = ast.parse(source, filename=str(path))
    neutral = (
        frozenset(_NEUTRAL_DEFAULTS)
        if neutral_defaults is None
        else frozenset(float(x) for x in neutral_defaults)
    )
    v = _Visitor(path, keyset, source.splitlines(), neutral)
    v.visit(tree)
    found = v.found if include_neutral else [f for f in v.found if not f.neutral]
    return sorted(found, key=lambda f: (f.line, f.col))


def scan_file(
    path: Path,
    keys: Iterable[str],
    include_neutral: bool = False,
    neutral_defaults: Iterable[float] | None = None,
) -> list[Finding]:
    return scan_source(
        path,
        path.read_text(encoding="utf-8", errors="replace"),
        keys,
        include_neutral=include_neutral,
        neutral_defaults=neutral_defaults,
    )

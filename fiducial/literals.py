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
import fnmatch
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


#: Characters that make a declared key a pattern rather than a name.
_GLOB = set("*?[")


class KeyMatcher:
    """Declared keys: exact names, plus glob patterns for families of names.

    Why patterns. A foreign project names one quantity in many ways --
    ``k_17``, ``k_cat_f``, ``kcat_r6``, ``Titer_gL`` -- and the exact-name form
    only catches the spelling the caller already knew. Measured 260923 on
    Bioindustrial-Park commit 6001ed0ef5: the author corrected
    ``k_ref.setdefault('k_17', 44.0)`` to the live 0.1077 (a 400x stale
    default). That line is this rule's target shape, but ``--keys`` had to
    name ``k_17`` in advance to see it; ``k_*`` finds it without knowing.

    A pattern is still a DECLARATION, not a guess: the caller says which
    family is measured, the checker does not infer it. Exact names match
    exactly (unchanged); patterns match case-insensitively, because a family
    declared as ``*titer*`` that misses ``Titer`` is the silent miss this
    package exists to name.
    """

    def __init__(self, keys: Iterable[str]):
        keys = [k for k in keys if k]
        self.exact = frozenset(k for k in keys if not _GLOB & set(k))
        self.patterns = tuple(k.lower() for k in keys if _GLOB & set(k))

    def __bool__(self) -> bool:
        return bool(self.exact or self.patterns)

    def __call__(self, name: str | None) -> bool:
        if not name:
            return False
        if name in self.exact:
            return True
        low = name.lower()
        return any(fnmatch.fnmatchcase(low, p) for p in self.patterns)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    col: int
    key: str
    kind: str          # "silent_fallback" | "bare_literal"
    snippet: str
    neutral: bool = False   # default was 0.0/1.0 -- "switched off", not a measurement
    #: The literal itself, when the node held a plain number. Carried because a
    #: caller comparing one key across files needs the VALUE, and re-parsing it
    #: out of `snippet` means writing a second, worse number parser against
    #: source text that may hold several numbers. `None` where the node was not
    #: a bare constant.
    value: float | None = None

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


#: Arithmetic on two literals is still a literal. Measured on a public
#: corpus: a pressure fix (`P=6 * 101325` -> `P=2.1 * 101325`, commit
#: 6ee1389052) was invisible because the value is a `BinOp`, not a
#: `Constant` -- and writing a measured quantity times its unit is ordinary
#: in scientific code (`6 * 101325` for six atmospheres, `30 + 273.15` for a
#: temperature). Reading only `Constant` misses that whole shape.
_FOLDABLE = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b if b else None,
    ast.Pow: lambda a, b: a ** b,
}


def _literal(node: ast.AST) -> float | int | None:
    """The numeric value of ``node``, including negation and folded arithmetic.

    Folding is deliberately shallow: both operands must themselves be
    literals, so `6 * 101325` folds and `6 * scale` does not. A value that
    depends on a name is not a literal -- it has a provenance, which is the
    whole thing this rule is looking for.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool):
            return None
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _literal(node.operand)
        return None if inner is None else -inner
    if isinstance(node, ast.BinOp):
        op = _FOLDABLE.get(type(node.op))
        if op is None:
            return None
        left, right = _literal(node.left), _literal(node.right)
        if left is None or right is None:
            return None
        try:
            return op(left, right)
        except (ZeroDivisionError, OverflowError, ValueError):
            return None
    return None


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _target_name(t: ast.AST) -> str | None:
    """`eta` / `obj.eta` / `params["eta"]` -> "eta"."""
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute):
        return t.attr
    if isinstance(t, ast.Subscript):
        return _const_str(t.slice)
    return None


class _Visitor(ast.NodeVisitor):
    """Walks one module, collecting both shapes for the declared keys."""

    def __init__(
        self,
        path: Path,
        keys: "KeyMatcher",
        source_lines: Sequence[str],
        neutral_defaults: frozenset[float] = frozenset(_NEUTRAL_DEFAULTS),
        call_keywords: bool = False,
    ):
        self.path = path
        self.keys = keys
        self.lines = source_lines
        #: Which defaults mean "this term is switched off" rather than "a
        #: measurement was invented". 0.0/1.0 here; a project whose neutral
        #: element is something else (a log-space model where it is 1.0, a
        #: ratio centred on 100) sets its own in [tool.fiducial].
        self.neutral_defaults = neutral_defaults
        self.call_keywords = call_keywords
        self.found: list[Finding] = []

    def _snippet(self, lineno: int) -> str:
        if 1 <= lineno <= len(self.lines):
            return self.lines[lineno - 1].strip()[:160]
        return ""

    def _record(
        self,
        node: ast.AST,
        key: str,
        kind: str,
        neutral: bool = False,
        value: float | int | None = None,
    ) -> None:
        self.found.append(
            Finding(
                path=self.path,
                line=node.lineno,
                col=node.col_offset,
                key=key,
                kind=kind,
                snippet=self._snippet(node.lineno),
                neutral=neutral,
                value=None if value is None else float(value),
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
            if self.keys(key) and default is not None:
                self._record(
                    node, key, "silent_fallback",
                    neutral=default in self.neutral_defaults,
                    value=default,
                )
        self._keywords(node)
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
            name = _target_name(t)
            if self.keys(name):
                self._record(node, name, "bare_literal", value=val)

    # --- shapes a foreign project stores parameters in -------------------
    # The rule began on one codebase whose parameters are module names and
    # attributes. Other projects keep the same number in a dict, pass it as
    # a keyword, or default it in a signature. Each is the same claim -- a
    # measured key bound to a literal -- in a different container.
    #
    # Note: a `visit_Subscript` stub used to sit here with a comment saying
    # `params["eta"] = 1.0` was handled. It was a no-op; the shape was never
    # caught. The subscript form now goes through `_target_name`.

    def visit_Dict(self, node: ast.Dict) -> None:
        # {"eta": 0.87}
        for k, v in zip(node.keys, node.values):
            name = _const_str(k) if k is not None else None
            val = _literal(v)
            if self.keys(name) and val is not None and val not in _UNREMARKABLE:
                self._record(v, name, "bare_literal", value=val)
        self.generic_visit(node)

    def _keywords(self, node: ast.Call) -> None:
        # dict(eta=0.87) always; run(eta=0.87) only when asked.
        #
        # A keyword argument names a parameter of the CALLEE, not of this
        # project. Measured 260923 on the reference codebase with keys
        # eta,kla_scale: reading every call's keywords took the run from 43
        # findings to 217, and 48+ of the new ones were pymoo's
        # `SBX(prob=0.9, eta=15)` / `PM(eta=20)` -- a crossover distribution
        # index that shares a name with the effectiveness factor and nothing
        # else. `dict(...)` builds the project's own mapping, so its keys are
        # the project's names. Other callees are opt-in (`call_keywords`) for
        # a codebase whose constructors take measured values directly, such
        # as Bioindustrial-Park's `Stream(..., price=0.73)`.
        is_dict = isinstance(node.func, ast.Name) and node.func.id == "dict"
        if not (is_dict or self.call_keywords):
            return
        for kw in node.keywords:
            val = _literal(kw.value)
            if self.keys(kw.arg) and val is not None and val not in _UNREMARKABLE:
                self._record(kw.value, kw.arg, "bare_literal", value=val)

    def _defaults(self, node) -> None:
        # def f(eta=0.87): -- a signature default is the same silent
        # fallback as params.get("eta", 0.87): omit the argument and the run
        # proceeds on a number nobody measured.
        a = node.args
        positional = a.posonlyargs + a.args
        pairs = list(zip(positional[len(positional) - len(a.defaults):], a.defaults))
        pairs += [(arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
        for arg, default in pairs:
            val = _literal(default)
            if self.keys(arg.arg) and val is not None:
                self._record(
                    default, arg.arg, "silent_fallback",
                    neutral=val in self.neutral_defaults,
                    value=val,
                )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._defaults(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._defaults(node)
        self.generic_visit(node)


def scan_source(
    path: Path,
    source: str,
    keys: Iterable[str],
    include_neutral: bool = False,
    neutral_defaults: Iterable[float] | None = None,
    call_keywords: bool = False,
) -> list[Finding]:
    """Findings for ``source``.

    ``include_neutral`` adds the 0.0/1.0 defaults -- the "term switched off"
    family.  They are excluded by default because they outnumber the real hits
    roughly 4:1 on the reference codebase and drown them.
    """
    keyset = KeyMatcher(keys)
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
    v = _Visitor(path, keyset, source.splitlines(), neutral, call_keywords)
    v.visit(tree)
    found = v.found if include_neutral else [f for f in v.found if not f.neutral]
    return sorted(found, key=lambda f: (f.line, f.col))


def scan_file(
    path: Path,
    keys: Iterable[str],
    include_neutral: bool = False,
    neutral_defaults: Iterable[float] | None = None,
    call_keywords: bool = False,
) -> list[Finding]:
    return scan_source(
        path,
        path.read_text(encoding="utf-8", errors="replace"),
        keys,
        include_neutral=include_neutral,
        neutral_defaults=neutral_defaults,
        call_keywords=call_keywords,
    )

"""rule (3) — a declared parameter with no gate asserting anything about it.

Rules (1) and (2) ask whether a number is *shaped* wrongly. This one asks a
different question, and it is the one that lets a project rot quietly:

    a key was added to the declaration, and nobody ever wrote a check for it.

Nothing else catches that. Rule (1) stays silent unless the key also happens to
be hard-coded or silently defaulted; a key that is plumbed correctly and never
tested produces no finding at all. The suite stays green because the assertions
that would fail were never written.

Measured on the reference project (49 declared learnable keys, 66 test files):

    12  appear inside an `assert`            -> a real gate
    26  appear in tests but never in assert  -> looks covered, asserts nothing
    11  appear nowhere in tests              -> no gate at all

The middle band is why "is the key mentioned in tests/?" is not a usable test.
A key shows up in 13 files as a dict entry, a fixture parameter, a config
literal -- everywhere except a line that claims something about it. Counting
mentions reports 38/49 covered; counting assertions reports 12/49. The second
number is the true one, and the gap between them is the finding.

Deliberately NOT claimed
------------------------
Appearing in an assert is necessary, not sufficient. `assert "frac_nox" in
params` mentions the key inside an assertion while asserting nothing about its
value. This rule reports the *floor*, not a guarantee -- it finds keys with
provably no check, and does not certify the ones it passes. A tool that claimed
otherwise would be the same false comfort it exists to remove.

Measured limits of this approach (260921)
-----------------------------------------
The classifier was rewritten four times against the same corpus, and each time a
band of keys it had called "no gate" turned out to be gated by a mechanism that
leaves no key name in the source:

  1. raw text          golden case came out clean (header comments narrate it)
  2. comments stripped still clean (prose fields repeat the version)
  3. golden JSON       11 keys compared by `for k, v in want.items()`
  4. module constants  11 keys held in `ENZYME_A_FITTED_KEYS = (...)`

A fifth band was then found by hand and is NOT implemented: keys held in a LOCAL
tuple inside the test body (`for k in ("k_mtf", "K_mtf", "qo2_basal")`), keys
that are VALUES in a mapping a generic loop walks (`CATALOG_TO_SSOT`), and keys
set via `setattr` whose gate asserts a downstream physical consequence (SSE
invariance, a Haldane equilibrium, a QSSA residual) rather than the value.

The pattern across all five: **a real gate need not name its parameter.** Each
round of pattern-matching shrinks the false-gap band without ever closing it, so
a MENTIONED verdict means "no gate found by the patterns implemented here", not
"no gate". That is why only ABSENT is wired to block.

And the error runs both ways. In this corpus `km_p_enzyme_a`, `km_q_enzyme_a` and
`ki_p_enzyme_a` are set by a test that then asserts `rate == 0` at a manufactured
equilibrium -- but the rate's numerator is structurally zero there and those
three appear only in the denominator, so the assertion holds for ANY value they
take. A gate that cannot fail, wearing the shape of one. This rule would call
them ASSERTED once the local-tuple pattern were added, which is worse than
calling them MENTIONED: a false gap costs someone an afternoon, a false gate
costs the thing the gate was for.

Deciding whether an assertion is actually sensitive to a parameter is mutation
testing's question, not a static one, and mutation testing answers it by running
the suite. This rule does not attempt it and must not be read as having done so.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence


class Coverage(str, Enum):
    ASSERTED = "asserted"      # named inside an assert -- a real gate exists
    PINNED = "pinned"          # value frozen in a baseline/fixture the tests compare
    MENTIONED = "mentioned"    # present in tests, but never inside an assert
    ABSENT = "absent"          # not in the test tree at all


@dataclass(frozen=True)
class KeyCoverage:
    key: str
    level: Coverage
    mention_files: tuple[str, ...] = ()
    assert_files: tuple[str, ...] = ()
    pin_files: tuple[str, ...] = ()

    @property
    def is_gap(self) -> bool:
        return self.level not in (Coverage.ASSERTED, Coverage.PINNED)

    def explain(self) -> str:
        if self.level is Coverage.PINNED:
            where = ", ".join(self.pin_files[:2])
            return (
                f"{self.key}: value pinned in {where}. A test compares that file "
                "key-by-key at runtime, so the parameter is gated even though its "
                "name never appears in an assert."
            )
        if self.level is Coverage.ABSENT:
            return (
                f"{self.key}: declared as a fitted/measured parameter, but it "
                "does not appear anywhere in the test tree. Nothing checks it, "
                "and nothing will notice when it changes."
            )
        where = ", ".join(self.mention_files[:3])
        more = f" (+{len(self.mention_files) - 3} more)" if len(self.mention_files) > 3 else ""
        return (
            f"{self.key}: appears in tests ({where}{more}) but never inside an "
            "assert. It is carried through fixtures and configs while no test "
            "claims anything about it -- the suite stays green either way."
        )


def _module_constant_members(tree: ast.Module) -> dict[str, set[str]]:
    """Module-level ``NAME = (...)`` / ``{...}`` collections, as name -> members.

    Only string members are collected, and only for assignments at module scope.
    """
    out: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if value is None:
            continue
        members: set[str] = set()
        if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            members = {
                e.value for e in value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }
        elif isinstance(value, ast.Dict):
            members = {
                k.value for k in value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
        if not members:
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out[t.id] = members
    return out


def _assert_named_keys(source: str) -> set[str]:
    """Every string literal and attribute/name that occurs inside an `assert`.

    Parsed rather than grepped: a line-based search attributes a key to an
    assertion whenever both happen to share a line, and misses a multi-line
    assert entirely -- which is the usual shape once a message is attached.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    # A test may collect the keys into a module constant and assert over it:
    #     ENZYME_A_FITTED_KEYS = ("kcat_enzyme_a", "km_a_enzyme_a", ...)
    #     assert not {k for k in ENZYME_A_FITTED_KEYS if ...}
    # The key names then appear only in the constant, never in the assert. Map
    # constant -> members so that naming the constant inside an assert credits
    # everything it holds.
    constants = _module_constant_members(tree)

    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        # The assertion's message is not part of its claim. `assert x == 1,
        # "k_mtf_sub must be the identity"` asserts nothing about k_mtf, and a
        # line-based search credited three keys on exactly that basis
        # (`k_mtf` inside `k_mtf_sub`, `qo2_basal` inside a regex string,
        # `log_ratio_fdh` inside an assertion that it is ABSENT). Walk the test
        # expression only, and take string constants as whole tokens.
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                # Whole-token only: a key must BE the string, not sit inside it.
                found.add(sub.value)
            elif isinstance(sub, ast.Name):
                found.add(sub.id)
                found |= constants.get(sub.id, set())
            elif isinstance(sub, ast.Attribute):
                found.add(sub.attr)

    # A `for k in CONST:` loop whose body asserts is the same claim written as a
    # statement. Credit the constant when an assert appears anywhere inside.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.comprehension)):
            continue
        it = node.iter
        name = it.id if isinstance(it, ast.Name) else None
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute):
            # CONST.items() / .keys()
            if isinstance(it.func.value, ast.Name):
                name = it.func.value.id
        if not name or name not in constants:
            continue
        if isinstance(node, ast.comprehension):
            found |= constants[name]
            continue
        if any(isinstance(n, ast.Assert) for n in ast.walk(node)):
            found |= constants[name]
    return found


_WORD = re.compile(r"[A-Za-z_]\w*")


def _keys_in_json(path: Path) -> set[str]:
    """Every dict key anywhere in a JSON document."""
    import json

    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return set()

    found: set[str] = set()
    stack = [doc]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            found.update(node.keys())
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found


def analyse(
    keys: Iterable[str],
    test_files: Sequence[Path],
    data_files: Sequence[Path] = (),
) -> list[KeyCoverage]:
    """Classify each declared key against the test tree.

    ``data_files`` are baselines/fixtures the tests compare against -- a golden
    JSON, a recorded snapshot. A parameter frozen in one of those IS gated, but
    its name never appears in the source: the comparison iterates the file at
    runtime (``for key, expected in want.items()``), so no AST pass can see it.

    Measured: 8 of the 28 keys this rule first called "mentioned-only" were in
    fact pinned in ``tests/golden/golden_baseline.json`` and compared by
    ``test_scalars_exact``. Reporting those as gaps would have sent someone to
    write a second gate for a parameter that already had one -- the rule's own
    false-positive mode, and worse than silence because it costs work.
    """
    keyset = list(dict.fromkeys(keys))
    if not keyset:
        raise ValueError(
            "no declared keys: every key would trivially be covered. "
            "Point --spec at the file that declares them."
        )
    if not test_files:
        raise ValueError(
            "no test files: every key would report as ABSENT, which says "
            "nothing about the project. Check the test path."
        )

    mentions: dict[str, list[str]] = {k: [] for k in keyset}
    asserts: dict[str, list[str]] = {k: [] for k in keyset}
    pins: dict[str, list[str]] = {k: [] for k in keyset}

    for path in data_files:
        present = _keys_in_json(path)
        for k in keyset:
            if k in present:
                pins[k].append(path.as_posix())

    for path in test_files:
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        words = set(_WORD.findall(src))
        asserted = _assert_named_keys(src)
        name = path.as_posix()
        for k in keyset:
            if k in words:
                mentions[k].append(name)
            if k in asserted:
                asserts[k].append(name)

    out = []
    for k in keyset:
        if asserts[k]:
            level = Coverage.ASSERTED
        elif pins[k]:
            level = Coverage.PINNED
        elif mentions[k]:
            level = Coverage.MENTIONED
        else:
            level = Coverage.ABSENT
        out.append(
            KeyCoverage(
                key=k,
                level=level,
                mention_files=tuple(mentions[k]),
                assert_files=tuple(asserts[k]),
                pin_files=tuple(pins[k]),
            )
        )
    return out


def load_declared_keys(spec_path: Path, field: str = "learnable_keys") -> list[str]:
    """Read a key list out of a YAML spec without requiring PyYAML.

    The core stays dependency-free, so this reads the one shape it needs: a
    top-level `field:` followed by `  - name` entries. If the project's spec is
    richer than that, pass keys explicitly instead.
    """
    keys: list[str] = []
    grabbing = False
    for line in spec_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{field}:"):
            grabbing = True
            continue
        if grabbing:
            m = re.match(r"\s+-\s+([A-Za-z_]\w*)", line)
            if m:
                keys.append(m.group(1))
                continue
            stripped = line.strip()
            if stripped and not line.startswith(" ") and not stripped.startswith("#"):
                break
    if not keys:
        raise ValueError(
            f"no keys found under '{field}:' in {spec_path}. "
            "A spec that yields nothing makes every check vacuous."
        )
    return keys


def load_waivers(spec_path: Path, field: str = "coverage_waivers") -> dict[str, str]:
    """Read ``field:`` as a mapping of key -> reason.

    Some parameters SHOULD NOT have a gate, and the project knows why. In the
    reference project ``kd_e_xr`` and ``kd_e_enzyme_a`` are marked "deliberately
    absent" in the golden builder: they are not ``__init__`` kwargs and travel a
    second configuration path, so a gate written for them would assert a
    fiction. Forcing one produces a test that is worse than no test.

    So a waiver is allowed -- but it costs something. It lives in the spec next
    to the declaration, so it is reviewed with the parameter and appears in the
    diff, and it MUST carry a reason. A bare key is refused: "we skipped this"
    with no reason recorded is exactly what rots, and an undocumented waiver is
    indistinguishable from an oversight six months later.

    Shape::

        coverage_waivers:
          kd_e_enzyme_a: "not an __init__ kwarg; merged into enzyme_a_params upstream"
    """
    waivers: dict[str, str] = {}
    grabbing = False
    for line in spec_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{field}:"):
            grabbing = True
            continue
        if grabbing:
            m = re.match(r"\s+([A-Za-z_]\w*)\s*:\s*(.*)$", line)
            if m:
                key, reason = m.group(1), m.group(2).strip().strip("\"'")
                if not reason:
                    raise ValueError(
                        f"waiver for '{key}' in {spec_path} has no reason. "
                        "A waiver without a recorded reason is indistinguishable "
                        "from an oversight -- write why this key needs no gate."
                    )
                waivers[key] = reason
                continue
            stripped = line.strip()
            if stripped and not line.startswith(" ") and not stripped.startswith("#"):
                break
    return waivers

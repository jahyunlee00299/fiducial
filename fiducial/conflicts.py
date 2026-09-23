"""One declared key, bound to different numbers in different places.

Why this exists (measured, 260923-24, on two public research repositories)
--------------------------------------------------------------------------
Rule (1) reports each bare literal on its own. That is the right unit for
"this number has no provenance", and the wrong unit for the defect the same
scan keeps walking past::

    k_ref.setdefault('k_17', 44.0)      # one file
    k_ref.setdefault('k_17', 0.1077)    # another

Those are two findings of rule (1) and one defect: a factor of 400 between two
places that both claim to hold the same measured quantity. The author of
`Bioindustrial-Park` fixed exactly this in commit `6001ed0ef5`, which is what
makes it a verifiable case rather than a plausible story.

The signal is already in the corpus, and was visible before this module::

    titer   2.003 / 1.208                    (Bioindustrial-Park)
    eta     0.535 / 0.6187 / 0.6252 / 0.445  (a reference codebase)

Nothing reported it, because no rule looked ACROSS findings.

What a conflict is, and what it is not
--------------------------------------
A conflict needs a declared key bound to **two or more distinct values**. The
same value repeated in fifteen files is not a conflict -- it is duplication,
which rule (1) already reports one site at a time and which a reader can act on
without this view.

Deliberately not decided here: **which value is right**. The tool sees that two
places disagree; it has no way to know whether 44.0 is the typo or 0.1077 is.
Proposing one would be the substitution this package exists to refuse, so a
conflict carries every site and no fix.

Why values are compared exactly
-------------------------------
No tolerance. Two readings of one quantity that differ at all differ for a
reason -- a rounded copy, a unit slip, a stale edit -- and each is worth
seeing. A tolerance would silently absorb the rounded-copy case, which is a
real defect class: the reference project measured `_MW_CAOH2 = 74.09` against
74.09268 producing calcium atoms in a mass balance that read as closed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable


#: A file that exists to exercise code rather than to run it. The distinction
#: is load-bearing, not cosmetic -- see `find()`.
_TEST_MARKERS = ("/tests/", "/test/")


def _is_test(path: str) -> bool:
    posix = str(path).replace("\\", "/")
    name = posix.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or any(m in posix for m in _TEST_MARKERS)
    )


def _scope(path: str) -> str:
    """The package a file belongs to, as a crude namespace.

    `titer` in `biorefineries/cane` and `titer` in `biorefineries/microalgae`
    are different quantities that share a generic name. Comparing them
    produced findings that read as contradictions and were not; measured on a
    574-file corpus, that one collision accounted for nine of the values under
    a single key.
    """
    parts = str(path).replace("\\", "/").split("/")[:-1]  # drop the filename

    # A layout anchor names the directory that holds packages, so the package
    # is the segment AFTER it -- `biorefineries/cane`, not `biorefineries`.
    # Measured: without dropping the filename first, a file sitting directly
    # under the anchor (`src/model.py`) produced a scope of `src/model.py`,
    # which put it in a different bucket from every test and reported nothing.
    for anchor in ("biorefineries", "packages"):
        if anchor in parts:
            i = parts.index(anchor)
            return "/".join(parts[: i + 2])

    # `src/` and `tests/` are two halves of ONE project, not two scopes. A
    # conflict between code and its tests is the defect this rule exists for,
    # so the layout directory is stripped rather than used as a boundary.
    while parts and parts[-1] in ("src", "lib", "tests", "test"):
        parts.pop()
    return "/".join(parts)


@dataclass(frozen=True)
class Site:
    """One place a key was bound to a value."""

    path: str
    line: int
    value: float
    kind: str

    @property
    def is_test(self) -> bool:
        return _is_test(self.path)

    def __str__(self) -> str:
        where = "test" if self.is_test else "code"
        return f"{self.path}:{self.line}: {self.value!r} ({self.kind}, {where})"


@dataclass(frozen=True)
class Conflict:
    """One declared key, bound to more than one distinct value.

    ``sites`` holds every binding, including the repeated ones: a reader
    deciding which value is right needs to know that 44.0 appears once and
    0.1077 nine times, and a view that collapsed to distinct values would
    throw that away.
    """

    key: str
    sites: tuple[Site, ...]

    @property
    def values(self) -> tuple[float, ...]:
        """The distinct values, in the order first seen."""
        out: list[float] = []
        for s in self.sites:
            if s.value not in out:
                out.append(s.value)
        return tuple(out)

    @property
    def spread(self) -> float:
        """max / min, as a bare ratio. ``inf`` when a value is zero.

        Reported because magnitude separates a rounding difference from a
        transcription error, and the second is the one that ruins a result:
        `k_17` differs by 409x, `titer` by 1.66x. Both are findings; only one
        of them is obviously not a rounding choice.
        """
        vals = [abs(v) for v in self.values if v != 0]
        if not vals or len(self.values) < 2:
            return 1.0
        lo, hi = min(vals), max(vals)
        if any(v == 0 for v in self.values):
            return float("inf")
        return hi / lo

    def explain(self) -> str:
        shown = ", ".join(repr(v) for v in self.values)
        ratio = "∞" if self.spread == float("inf") else f"{self.spread:.3g}x"
        head = (
            f"{self.key}: bound to {len(self.values)} different values "
            f"({shown}) across {len(self.sites)} places, spread {ratio}. "
            "Both claim to be the same measured quantity, so at least one is "
            "wrong -- and nothing in the code says which."
        )
        body = "\n".join(f"    {s}" for s in self.sites)
        return f"{head}\n{body}"


def find(findings: Iterable[Any]) -> list[Conflict]:
    """Keys whose value in the CODE disagrees with the value elsewhere.

    The first version of this grouped by key alone and was measured at 1
    real finding in 20 -- an adversarial audit read every flagged site and
    refuted 19. The corpus was 93% test fixtures (240 of 259 sites), and
    fixtures disagree with each other by design: `10x` monotonicity probes,
    `2x` scenario variants, per-test dicts of arbitrary round numbers, one
    recurring regression sample fanned across every key.

    So the comparison is now anchored. A conflict needs at least one site in
    non-test code, and that site's value is what everything else is compared
    against:

        code 0.1077, test 0.1077   agree, nothing reported
        code 0.1077, test 44.0     REPORTED -- the fixture never followed
        test 1.0, test 10.0        ignored -- two fixtures, not a claim
        code A/x, code B/y         compared only within one package

    That is not a heuristic about which files matter. It is what the defect
    actually looks like: the measured value in `k_17` was corrected to 0.1077
    in the code, and three test files still carry 44.0 -- a 409x stale copy
    that every one of those tests asserts against.

    What this still does NOT do, measured
    -------------------------------------
    It does not separate a stale fixture from a deliberate one. On the same
    corpus `k_15`, `k_16` and `k_17` are indistinguishable on every structural
    signal tried -- number of test files carrying a value the code lacks (3 in
    all three cases), files carrying no code value at all (2, 3, 2) -- and yet
    `k_17` is a real stale copy while the other two are `10x` monotonicity
    probes. The difference lives in what the test MEANS, which is not in the
    literal.

    So the output is a ranked list to read, not a verdict to act on: five
    findings a person can check in a minute, from twenty that were mostly
    noise. Guessing further would delete the one that mattered -- `k_17`
    survives only because the filter stayed at the code-versus-fixture line
    and did not push past it.

    Findings whose ``value`` is ``None`` are skipped: the node was not a plain
    number, so there is nothing to compare. They remain rule (1) findings and
    are reported there.
    """
    by_scope: dict[tuple[str, str], list[Site]] = defaultdict(list)
    for f in findings:
        value = getattr(f, "value", None)
        if value is None:
            continue
        path = str(f.path)
        site = Site(path=path, line=f.line, value=float(value), kind=f.kind)
        by_scope[(f.key, _scope(path))].append(site)

    out: list[Conflict] = []
    for (key, _scope_name), sites in sorted(by_scope.items()):
        code = {s.value for s in sites if not s.is_test}
        # Nothing in the code declares this, so there is no value for a
        # fixture to disagree WITH -- only fixtures disagreeing with each
        # other, which is what they are for.
        if not code:
            continue
        if len({s.value for s in sites}) < 2:
            continue
        out.append(Conflict(key=key, sites=tuple(sites)))
    return out

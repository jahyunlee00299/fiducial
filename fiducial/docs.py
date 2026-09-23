"""rule (4) — a derived document asserting a value its own SSOT contradicts.

Why this exists (measured, on a process-modelling repo, 260721 / 260728 / 260922):

Rules (1)-(3) all look at code and config.  This one looks at prose, because
that is where the same drift kept landing and no gate was watching.

    260721  a PFD said moisture 0.35 where the SSOT said 0.03, conversion 98%
            where the SSOT said 93.56%, residence 24 h where the SSOT said 36 h
    260728  `n_recryst_stages` drifted the same way
    260922  a PFD draft asserted pH 5.0 for a step the SSOT holds at pH 10

Three occurrences of one species.  The reference project already had four gates
(`freshness_gate`, `manuscript_number_gate`, `doc_number_gate`, and a silent-
fallback test) and every one of them is *radial*: each compares a document
against a canonical JSON.  Two documents that disagree with each other about the
same quantity are, structurally, invisible to all four -- and a search of that
repo's `scripts/` for any document-to-document comparison returned nothing.

So the gap is not "a gate was switched off".  There was no gate of this shape.

[Why the comparison must be declared, not inferred]

The obvious design is to scan every document for every number and group by
label -- which is what `numeric_consistency_check.py` does for a .docx.  On a
54-document corpus of research prose that produces noise faster than signal:
the same figure legitimately appears as a citation of prior art ("CN101904484A
uses pH 5.0"), as a retracted value ("we said 24 h; it is 36 h"), and as a
target distinct from an operating point.  A gate that cannot tell those apart
reports thirty findings, and thirty findings is a gate nobody reads.  The
reference project learned this in its own `doc_number_gate`, which went from 47
findings to 1 by narrowing what it would look at.

So a document states, in machine-readable form, which document is upstream of it
and which quantities it is repeating rather than originating:

    ---
    ssot:
      source: docs/PROCESS_CONDITIONS.md
      repeats:
        pH: 10
        residence_h: 36
    ---

Only declared quantities are compared.  Everything else in the prose is left
alone, deliberately: this rule does not try to understand the document, it holds
the author to what the author declared.

[Why an undeclared corpus is exit 2, not exit 0]

At adoption, the reference corpus had **0 of 53 documents** carrying any front
matter (measured 260922).  A rule that silently finds nothing to compare would
therefore have reported "clean" forever while the third recurrence of the very
bug it was written for sat in the tree.  That is the failure this whole package
exists to refuse -- see the module docstring in `cli.py` -- so a scan that can
compare nothing exits 2 (cannot check), never 0.

[What this rule does not do]

It does not verify that the SSOT document is itself right; rule (4) only
establishes that the copy matches the original.  It does not follow chains more
than one hop -- if A declares B and B declares C, A is checked against B alone.
And it does not read code: a document repeating a value that lives in a .py
constant is rule (1)'s business, not this one's.
"""

from __future__ import annotations

import re
from . import locales as _locales
from . import quantities as _quantities
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# --------------------------------------------------------------------------
# front matter
# --------------------------------------------------------------------------

#: A YAML front-matter block: the file opens with `---` and closes on the next
#: `---` at column 0.  Anchored at the start of the file, because a `---`
#: appearing later in a markdown document is a horizontal rule, not a fence.
_FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL)


class DeclarationError(ValueError):
    """The front matter exists but does not say something usable.

    Raised rather than skipped.  A malformed declaration is the one case where
    silence is most dangerous: the author believes the document is gated.
    """


@dataclass(frozen=True)
class Declaration:
    """What a document says about where its numbers came from."""

    path: Path
    source: Path
    repeats: dict[str, Any]


def _parse_front_matter(text: str) -> dict | None:
    """The document's ``ssot:`` front matter, or ``None`` if it has none.

    Parsed without PyYAML, the same way ``coverage.load_declared_keys`` reads a
    spec: this package ships with no dependencies, and the one shape needed here
    is small and fixed --

        ssot:
          source: <path>
          repeats:
            <label>: <number>

    Anything richer is refused with a message rather than half-understood.  A
    declaration that silently parses to the wrong thing is worse than one that
    does not parse at all, because the author believes it is in force.
    """
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return None

    block = m.group(1)
    if not re.search(r"^ssot:\s*$", block, re.MULTILINE):
        # No ssot: key, or `ssot: something` on one line — the latter is a
        # declaration shaped wrongly and must be reported, not ignored.
        if re.search(r"^ssot:\s*\S", block, re.MULTILINE):
            raise DeclarationError(
                "`ssot:` must be a mapping with `source:` and `repeats:`"
            )
        return {}

    out: dict[str, Any] = {}
    repeats: dict[str, Any] = {}
    in_ssot = in_repeats = False

    for raw in block.splitlines():
        if re.match(r"^\S", raw):                       # back to column 0
            in_ssot = in_repeats = raw.startswith("ssot:")
            continue
        if not in_ssot:
            continue
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())
        if indent <= 2:
            in_repeats = False
            km = re.match(r"^\s*([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
            if not km:
                continue
            key, val = km.group(1), km.group(2).strip()
            if key == "repeats":
                in_repeats = True
                if val:
                    raise DeclarationError(
                        "`ssot.repeats:` must be a block mapping of "
                        "quantity -> value, one per line"
                    )
                continue
            out[key] = _scalar(val)
        elif in_repeats:
            km = re.match(r"^\s*([^:#]+?)\s*:\s*(.+?)\s*$", line)
            if km:
                # A label often needs quoting in YAML (`"NAD⁺": 5`, `"pH": 10`).
                # Strip them: the quotes belong to the file format, not to the
                # label being searched for in the prose.
                label = km.group(1).strip().strip('"').strip("'")
                if label:
                    repeats[label] = _scalar(km.group(2))

    out["repeats"] = repeats
    return {"ssot": out}


#: `<label in this document> as <label in the source document>`.
_ALIAS_RE = re.compile(r"\s+as\s+", re.IGNORECASE)


def _split_alias(label: str) -> tuple[str, str, str]:
    """``(document label, separator, source label)``.

    A bare label means both documents use the same word.
    """
    parts = _ALIAS_RE.split(label, maxsplit=1)
    if len(parts) == 2:
        return parts[0], " as ", parts[1]
    return label, "", label


def _strip_front_matter(text: str) -> str:
    """The document body, with the declaration removed.

    Line numbers are preserved (the block is replaced by blank lines) so that a
    reported line still matches what an editor shows.
    """
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return text
    return "\n" * text.count("\n", 0, m.end()) + text[m.end():]


def _scalar(text: str) -> Any:
    """A YAML scalar, restricted to what a declaration may hold."""
    s = text.strip().strip('"').strip("'")
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def read_declaration(path: Path, root: Path | None = None) -> Declaration | None:
    """Parse ``path``'s SSOT declaration.

    Returns ``None`` when the document makes no claim at all (no front matter,
    or front matter without an ``ssot:`` block) -- that is not an error, it is a
    document this rule has nothing to say about.  A declaration that is present
    but unusable raises ``DeclarationError``.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    data = _parse_front_matter(text)
    if not data or "ssot" not in data:
        return None

    block = data["ssot"]
    if not isinstance(block, dict):
        raise DeclarationError("`ssot:` must be a mapping with `source:` and `repeats:`")

    source = block.get("source")
    if not source or not isinstance(source, str):
        raise DeclarationError("`ssot.source:` must name the upstream document")

    repeats = block.get("repeats")
    if not repeats:
        raise DeclarationError(
            "`ssot.repeats:` is missing or empty. A declaration naming a source "
            "but no quantities compares nothing, which reads as clean."
        )

    base = root if root is not None else path.parent
    src = (base / source) if not Path(source).is_absolute() else Path(source)
    return Declaration(path=path, source=src, repeats=dict(repeats))


# --------------------------------------------------------------------------
# finding a declared quantity's value inside the upstream document
# --------------------------------------------------------------------------

#: A number as documents actually write it, thousands separators included.
#: 🔴 Without the `(?:,\d{3})*` group, `2,000 t/yr` matched as `2` and then the
#: fractional branch read `2,000` as `2.0` — a target of 2,000 t/yr reported as
#: the value 2.0. A gate that misreads the number it is comparing is worse than
#: no gate, so this is pinned by a test.
_NUM = r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?"

#: Markup and syntax that sit between a label and its value in real documents.
#: Measured on the reference corpus: values live inside mermaid node labels
#: (`pH 10 · <=30 degC`), inside table cells (`| pH | 10 |`), and inside bold
#: runs (`**pH 10**`).  Stripping these is what lets one pattern serve all three.
_NOISE_RE = re.compile(r"<br\s*/?>|[*`|]+")

#: Korean particles and copulas that attach directly to a number and would
#: otherwise be read as part of it or block the match.  `pH 10이`, `36시간으로`.
#: These now live in `locales.KO`; the alternation is built from whichever
#: locales are active so that an English-only project never carries them.
def _tail_pattern(locale: "_locales.LocaleSet") -> str:
    if not locale.value_tail:
        return ""
    return "(?:" + "|".join(re.escape(t) for t in locale.value_tail) + ")?"


def _joiner_pattern(locale: "_locales.LocaleSet") -> str:
    joiners = locale.label_joiners or ("=", ":")
    return "(?:" + "|".join(re.escape(j) for j in joiners) + ")?"


#: A range, not a value: `pH 4~8`, `7.5-10.5`, `4 – 8`, `4 to 8`.
#: 🔴 Measured on the reference corpus (562-line PFD, 260922): both of the
#: rule's only two findings were `pH 4~8` read as `4.0`. A range is a stated
#: tolerance band, and comparing its lower bound against a single operating
#: point is a category error -- the document and its SSOT are not in conflict.
#: Ranges are therefore skipped, not flagged: deciding whether an operating
#: point sits inside a declared band is a different check than this one.
_RANGE_TAIL = re.compile(
    r"\A\s*(?:~|-|–|—|to\b|±)\s*" + _NUM,
)


def _value_pattern(
    label: str, locale: "_locales.LocaleSet | None" = None
) -> re.Pattern[str]:
    """Match ``label`` followed by a number, tolerating markup and particles."""
    loc = locale or _locales.DEFAULT
    return re.compile(
        re.escape(label)
        + r"\s*" + _joiner_pattern(loc) + r"\s*"
        + r"(?:약|approx\.?|about)?\s*"
        + r"(?P<value>" + _NUM + r")"
        + _tail_pattern(loc),
        re.IGNORECASE,
    )


#: A markdown table row: `| 반응 시간 | 24 h |`.  The label sits in one cell and
#: the value in another, so a pattern anchored on "label then number" never sees
#: it.  Measured on the reference corpus: the confirmed-specification documents
#: keep almost every quantity in exactly this shape, so without this the rule is
#: blind to the documents most worth checking.
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
#: Separator row (`|---|---|`) — structure, never data.
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _table_pairs(line: str, label: str) -> list[float]:
    """Values from a table row whose *other* cells name ``label``.

    Only fires when one cell matches the label as a whole (after markup is
    stripped), so `| 반응 시간 | 24 h |` is read while a row merely mentioning
    the word in a sentence is not.
    """
    m = _TABLE_ROW_RE.match(line)
    if not m or _TABLE_SEP_RE.match(line):
        return []
    cells = [_NOISE_RE.sub(" ", c).strip() for c in m.group(1).split("|")]
    norm = label.strip().lower()
    if not any(c.lower() == norm for c in cells):
        return []

    out: list[float] = []
    for cell in cells:
        if cell.lower() == norm:
            continue
        vm = re.match(r"\A(?P<value>" + _NUM + r")", cell)
        if not vm:
            continue
        rest = cell[vm.end("value"):]
        if _RANGE_TAIL.match(rest):
            continue
        try:
            out.append(float(vm.group("value").replace(",", "")))
        except ValueError:
            continue
    return out


def find_values(
    text: str, label: str, locale: "_locales.LocaleSet | None" = None
) -> list[tuple[int, float, str]]:
    """Every ``(line_number, value, line)`` where ``label`` carries a number."""
    out: list[tuple[int, float, str]] = []
    seen: set[tuple[int, float]] = set()
    pat = _value_pattern(label, locale)
    for i, raw in enumerate(text.splitlines(), start=1):
        line = _NOISE_RE.sub(" ", raw)
        for value in _table_pairs(raw, label):
            if (i, value) not in seen:
                seen.add((i, value))
                out.append((i, value, raw.strip()))
        for m in pat.finditer(line):
            # `pH 4~8` states a band, not an operating point. Reading its lower
            # bound as the value produced 2 of 2 findings on the reference
            # corpus, both wrong.
            if _RANGE_TAIL.match(line[m.end("value"):]):
                continue
            value = float(m.group("value").replace(",", ""))
            if (i, value) in seen:      # already reported via the table path
                continue
            seen.add((i, value))
            out.append((i, value, raw.strip()))
    return out


# --------------------------------------------------------------------------
# telling an assertion apart from a citation or a retraction
# --------------------------------------------------------------------------

#: The line is describing a *past* or *rejected* value, or is quoting somebody
#: else's process.  Both lists now live in `locales`: the English half (`~~`,
#: `superseded`, an `X -> Y` correction) is always on, and the Korean half
#: (`폐기`, `였다`, `선례`, `특허`) comes with `locales = ["ko"]`.
#:
#: Why these exist at all.  Without the history markers every audit trail and
#: every "we corrected X to Y" sentence becomes a finding, which is the
#: documented way these checks get switched off.  Without the citation markers
#: the rule flags `CN101904484A uses pH 5.0` -- a true sentence about prior
#: art -- and teaches the author to disable the gate.  The original lists were
#: borrowed wholesale from the reference project's `doc_number_gate`, which
#: tuned them against a real corpus.
#:
#: A patent/DOI/URL identifier is recognised structurally rather than by word,
#: so it needs no locale.
_ID_CITATION_RE = re.compile(
    r"\b(?:[A-Z]{2}\d{6,}[A-Z]?\d*"          # CN101904484A, US4322569A
    r"|doi:|https?://"
    r"|et\s+al\.)",
    re.IGNORECASE,
)


def is_assertion(
    line: str, locale: "_locales.LocaleSet | None" = None
) -> bool:
    """Does this line state the value as currently true *for this process*?"""
    loc = locale or _locales.DEFAULT
    if any(mark in line for mark in loc.history_markers):
        return False
    if _ID_CITATION_RE.search(line):
        return False
    if any(mark in line for mark in loc.citation_markers):
        return False
    return True


# --------------------------------------------------------------------------
# the comparison
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """A declared quantity asserted with a value the SSOT does not carry."""

    path: Path
    source: Path
    label: str
    declared: Any
    found: float
    line_no: int
    line: str
    source_values: list[float]

    def explain(self) -> str:
        src = (
            ", ".join(str(v) for v in self.source_values)
            if self.source_values
            else "(quantity not found in the source document)"
        )
        return (
            f"{self.path}:{self.line_no}: {self.label} asserted as {self.found} "
            f"but {self.source} carries {src}\n"
            f"    {self.line}"
        )


@dataclass(frozen=True)
class SourceGap:
    """A declared quantity that one side of the comparison never states.

    Reported separately from a value mismatch because the remedy differs: a
    mismatch means one of two numbers is wrong, a gap means the declaration
    describes a comparison that is not happening.

    🔴 Both directions matter, and the second one is the dangerous one.

    ``side="source"``  the upstream document never states the quantity, so
        there is nothing to check against.

    ``side="document"``  the declaring document never states it either -- under
        that label.  Measured while wiring this rule: a real derived document
        declared `반응 시간` and `생산 규모`, and the run came back "0
        violations" because the document writes the same quantities as `시간`
        and in a differently-worded table.  Nothing was compared, and the
        output was indistinguishable from agreement.  That is precisely the
        shape of blindness this package refuses, so it is named rather than
        counted as clean.
    """

    path: Path
    source: Path
    label: str
    side: str = "source"

    def explain(self) -> str:
        if self.side == "document":
            return (
                f"{self.path}: declares `{self.label}` as repeated from "
                f"{self.source}, but states no value for it under that label -- "
                "nothing is being compared. Use the label the prose actually "
                "uses, or drop the declaration."
            )
        return (
            f"{self.path}: declares `{self.label}` as repeated from {self.source}, "
            f"but that document never states it -- nothing is being compared."
        )


def check(
    decl: Declaration,
    rel_tol: float = 0.0,
    locale: "_locales.LocaleSet | None" = None,
) -> tuple[list[Finding], list[SourceGap], list[_quantities.UnitMismatch]]:
    """Compare one document's repeated quantities against its declared source.

    Returns ``(findings, gaps, units)``. A unit mismatch is separate from a
    value mismatch because it is found under the opposite condition: the
    numbers have to AGREE for it to matter, so folding the two together
    would hide it behind the check that just passed.
    """
    if not decl.source.is_file():
        raise DeclarationError(f"declared source does not exist: {decl.source}")

    src_text = _strip_front_matter(decl.source.read_text(encoding="utf-8", errors="replace"))
    # 🔴 The declaration must not be part of what is checked. Without this the
    # front matter's own `residence_h: 36` is read as prose, matches itself, and
    # every declared quantity reports agreement whether or not the document says
    # anything at all -- a gate that always passes.
    doc_text = _strip_front_matter(decl.path.read_text(encoding="utf-8", errors="replace"))

    findings: list[Finding] = []
    gaps: list[SourceGap] = []
    units: list[_quantities.UnitMismatch] = []

    for label, declared in decl.repeats.items():
        # Two documents rarely use one word for one quantity: the reference
        # repository's own pair calls the same number `생산 규모` upstream and
        # `목표 생산량` downstream. A declaration may therefore give the
        # upstream label after `as`, e.g. `목표 생산량 as 생산 규모: 2000`.
        label, _, src_label = (x.strip() for x in _split_alias(label))
        src_pairs = [
            (v, line)
            for _, v, line in find_values(src_text, src_label, locale)
            if is_assertion(line, locale)
        ]
        src_hits = [v for v, _ in src_pairs]
        if not src_hits:
            gaps.append(
                SourceGap(
                    path=decl.path, source=decl.source, label=src_label, side="source"
                )
            )
            continue

        doc_hits = [
            (n, v, line)
            for n, v, line in find_values(doc_text, label, locale)
            if is_assertion(line, locale)
        ]
        if not doc_hits:
            # The declaration promises this quantity is repeated here, and it is
            # not -- at least not under this label. Silence here reads exactly
            # like agreement.
            gaps.append(
                SourceGap(
                    path=decl.path, source=decl.source, label=label, side="document"
                )
            )
            continue

        for line_no, value, line in doc_hits:
            if any(_agrees(value, s, rel_tol) for s in src_hits):
                # The numbers match. That is exactly when a unit error is
                # invisible: 48 h and 48 min agree on every axis this rule
                # checked before, and differ by a factor of 60.
                mismatch = _unit_disagreement(
                    decl, label, value, line_no, line, src_pairs, rel_tol
                )
                if mismatch is not None:
                    units.append(mismatch)
                continue
            findings.append(
                Finding(
                    path=decl.path,
                    source=decl.source,
                    label=label,
                    declared=declared,
                    found=value,
                    line_no=line_no,
                    line=line,
                    source_values=sorted(set(src_hits)),
                )
            )

    return findings, gaps, units


def _agrees(a: float, b: float, rel_tol: float) -> bool:
    """Two readings of one quantity, within ``rel_tol`` relative tolerance."""
    if a == b:
        return True
    if rel_tol <= 0:
        return False
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) / scale <= rel_tol


def scan(
    paths: Iterable[Path],
    root: Path | None = None,
    rel_tol: float = 0.0,
    locale: "_locales.LocaleSet | None" = None,
) -> tuple[
    list[Finding], list[SourceGap], list[Path],
    list[tuple[Path, str]], list[_quantities.UnitMismatch],
]:
    """Check every declared document in ``paths``.

    Returns ``(findings, gaps, declared_paths, errors)``.  ``declared_paths`` is
    what the caller needs to decide whether anything was checked at all -- an
    empty list means this rule compared nothing, which is never a pass.
    """
    findings: list[Finding] = []
    gaps: list[SourceGap] = []
    units: list[_quantities.UnitMismatch] = []
    declared: list[Path] = []
    errors: list[tuple[Path, str]] = []

    for p in paths:
        try:
            decl = read_declaration(p, root=root)
        except DeclarationError as exc:
            errors.append((p, str(exc)))
            continue
        if decl is None:
            continue
        declared.append(p)
        try:
            f, g, u = check(decl, rel_tol=rel_tol, locale=locale)
        except DeclarationError as exc:
            errors.append((p, str(exc)))
            continue
        findings.extend(f)
        gaps.extend(g)
        units.extend(u)

    return findings, gaps, declared, errors, units


def _unit_disagreement(
    decl: Declaration,
    label: str,
    value: float,
    line_no: int,
    line: str,
    src_pairs: list[tuple[float, str]],
    rel_tol: float,
) -> "_quantities.UnitMismatch | None":
    """The unit written here, against the unit the upstream writes.

    Only reached when the NUMBERS already agree, which is the whole point: a
    quantity that matches in magnitude and differs in unit passes every other
    check this rule makes. Measured before this existed::

        SSOT.md    | reaction time | 48 h |
        DERIVED.md   reaction time 48 min.

        $ fiducial docs --root .        # exit 0, 0 violations

    A factor of sixty, reported as agreement.

    Deliberately narrow. Nothing here knows which unit is *correct* and
    nothing converts between them; it compares what the upstream wrote with
    what this document wrote, the same declared-versus-written comparison the
    rule already makes for the number. Where either side writes no unit at
    all there is nothing to compare, and silence is not a finding -- a
    document that states a bare number is making no claim about units.
    """
    found_unit = _unit_of(line, value)
    if found_unit is None:
        return None

    # The upstream reading whose number this one matched is the one whose unit
    # it has to match; a different quantity's unit proves nothing.
    for src_value, src_line in src_pairs:
        if not _agrees(value, src_value, rel_tol):
            continue
        declared_unit = _unit_of(src_line, src_value)
        if declared_unit is None:
            continue
        if _quantities.normalise_unit(declared_unit) == _quantities.normalise_unit(
            found_unit
        ):
            return None
        return _quantities.UnitMismatch(
            path=decl.path,
            source=decl.source,
            label=label,
            declared_unit=declared_unit,
            found_unit=found_unit,
            line_no=line_no,
            line=line.strip(),
        )
    return None


def _unit_of(line: str, value: float) -> str | None:
    """The unit written after ``value`` in ``line``, or None.

    `unit_after` takes a character offset; the comparison above has a number.
    Finding where that number is written is this function's whole job, and it
    is separate because "which token on this line IS the value" has more than
    one right answer: `48` appears inside `1.48` and inside `480`. The scan
    walks numeric runs and compares parsed values, so a substring never
    matches by accident.
    """
    import re as _re

    for m in _re.finditer(r"-?\d+(?:[.,]\d+)?", line):
        text = m.group(0).replace(",", ".")
        try:
            if float(text) != value:
                continue
        except ValueError:
            continue
        unit = _quantities.unit_after(line, m.end())
        if unit is not None:
            return unit
    return None

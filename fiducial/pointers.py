"""rule (5) — an index entry that points at something which is not there.

Why this exists (measured, on a private research repo used as the reference
corpus, 260923):

    models/params/param_registry.json

registers 152 fitted parameter sets.  **88 of them (58%) cannot be resolved.**
The registry is the documented way to load a fit -- ``ParamRegistry.load_params(
param_id)`` reads it -- so the failure is not cosmetic:

    >>> ParamRegistry().load_params("run_260403_a")
    FileNotFoundError: .../models/params/calibrated_run_260403_a_params.json

That id is the one the manuscript-adjacent plotting scripts quote by name.  The
file exists; it is one directory down, in ``archive/``.  Commit ``d928acba``
("reorganize params/ into active/archive/gpo/test subdirs") moved the files and
left every ``file`` field in the index spelling the old location.

Two distinct pointer species, and they need different verdicts
--------------------------------------------------------------
The 88 split cleanly, which is why this rule reports them apart rather than as
one count:

    moved   69   the named basename exists exactly one directory away
                 (archive/ 64, gpo/ 4, test/ 1).  Zero ambiguity -- no basename
                 occurs in two directories -- so each one has a single correct
                 repair and a tool can propose it.
    gone    19   the basename occurs nowhere in the tree.  16 are
                 ``de_mpsp_*_smoke`` run outputs, 2 are ``lsq_10d_*``, 1 is
                 ``literature_baseline``.  There is nothing to repair; the
                 entry either names a deleted artefact or was never written.

Reporting a single "88 broken" would hide that 69 are mechanically repairable
and 19 are a data-loss question a person has to answer.  A checker that cannot
tell those apart produces a number nobody can act on.

The second pointer kind: an id, not a path
-------------------------------------------
The same registry carries ``parent_id`` on each entry, and **30 of them name an
id that is not registered** (``enzyme_a_17d_fit_wide``, ``lsq_16d_softmax_bo1bo2s4_
noBC``, ...).  That is the identical defect in a different notation -- a pointer
whose target does not exist -- and it breaks lineage rather than loading.  It is
checked here because splitting it into its own rule would mean two tools reading
the same file to ask the same question.

Why rule (2) does not catch this
---------------------------------
Rule (2) compares version tokens between a file's name and its contents.  These
entries carry no version token at all, and the lie is not in a name-vs-content
disagreement: the entry is internally consistent and simply describes a file
that is not there.  Consistency checks cannot see a missing referent.  That is
the gap this rule closes, and it is a shape that kept recurring across four
separate audits: a copy that drifted from its upstream, of which a pointer to
a moved file is the mechanically detectable case.

Deliberate non-goals
--------------------
We do not follow URLs, globs, or anything requiring the network or a shell.  A
pointer is checked only against the filesystem, relative to the index file's own
directory, because that is the resolution the loader itself performs.  Entries
that carry no pointer field are not violations: an index row that makes no claim
cannot make a false one -- the same reasoning rule (2) applies to files carrying
no version token on one side.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

# Keys whose value names a FILE.  ``file`` and ``path`` are the common spellings;
# the rest were found in this corpus.  A project with different field names
# supplies its own through ``[tool.fiducial]``.
FILE_KEYS = frozenset({"file", "path", "filename", "filepath", "source", "src"})

# Keys whose value names ANOTHER ENTRY in the same index, by id.
ID_KEYS = frozenset({"parent_id", "parent", "extends", "base", "derived_from"})

# Where the entries live inside the document.  ``entries`` is this corpus's
# spelling; a bare mapping of id -> entry is the other common shape and is
# handled without configuration (see ``_entries``).
ENTRY_CONTAINERS = ("entries", "items", "records", "index")


@dataclass(frozen=True)
class Pointer:
    """One pointer found in one index entry.

    ``kind`` is ``"file"`` or ``"id"``.  ``target`` is the raw value as written,
    never normalised, so the report quotes what the file actually says.
    """

    entry_id: str
    key: str
    kind: str
    target: str


@dataclass(frozen=True)
class Broken:
    """A pointer whose target does not exist, and what can be done about it.

    ``candidates`` holds resolvable relocations for a file pointer: paths,
    relative to the index's directory, where that basename actually occurs.

    The distinction that matters is the length of that list:

        1 candidate   the file moved and the repair is unambiguous
        0 candidates  nothing by that name exists anywhere -- a person decides
        2+ candidates the basename is ambiguous; proposing one would be a guess

    Measured on the reference corpus: 69 pointers had exactly one candidate,
    19 had none, and **zero were ambiguous**.  The 2+ case is handled anyway
    because a corpus where it does occur is exactly where an automatic repair
    would do damage.
    """

    pointer: Pointer
    candidates: tuple[str, ...] = ()

    @property
    def repairable(self) -> bool:
        """Exactly one relocation exists, so the fix is determined, not guessed."""
        return len(self.candidates) == 1

    def explain(self) -> str:
        p = self.pointer
        if p.kind == "id":
            return (
                f"{p.entry_id}: {p.key} = {p.target!r} names an entry that is not "
                "in this index. The lineage stops here -- anything walking it "
                "reads a parent that was never registered."
            )
        if self.repairable:
            return (
                f"{p.entry_id}: {p.key} = {p.target!r} does not exist, but that "
                f"basename does, at {self.candidates[0]!r}. The file moved and "
                "the index was not updated; loading this entry raises "
                "FileNotFoundError."
            )
        if self.candidates:
            joined = ", ".join(repr(c) for c in self.candidates)
            return (
                f"{p.entry_id}: {p.key} = {p.target!r} does not exist and the "
                f"basename occurs in several places ({joined}). Pick one by hand "
                "-- guessing here would point the index at the wrong artefact."
            )
        return (
            f"{p.entry_id}: {p.key} = {p.target!r} does not exist anywhere under "
            "the index's directory. Either the artefact was deleted and the "
            "entry should go, or it was never written and the entry is a claim "
            "about a run whose output nobody kept."
        )


@dataclass(frozen=True)
class Report:
    """What one index file yielded.

    ``checked`` is the number of pointers actually resolved.  It is reported
    even when nothing is broken, and that is not decoration: rule (2) shipped a
    bug where "0 comparable" read as clean, and a probe in the same package
    passed because fiducial had not run at all.  A count of zero checked
    pointers is the signature of both, so the caller is always told.
    """

    index: Path
    checked: int
    broken: tuple[Broken, ...]

    @property
    def blind(self) -> bool:
        """Nothing was resolvable, so a clean result proves nothing."""
        return self.checked == 0

    @property
    def repairable(self) -> tuple[Broken, ...]:
        return tuple(b for b in self.broken if b.repairable)

    def summary(self) -> str:
        if self.blind:
            return f"{self.index}: no pointers found -- nothing was checked"
        n = len(self.broken)
        if not n:
            return f"{self.index}: {self.checked} pointers, all resolve"
        fixable = len(self.repairable)
        return (
            f"{self.index}: {n} of {self.checked} pointers broken "
            f"({fixable} relocatable, {n - fixable} needing a decision)"
        )


def _entries(doc: Any) -> dict[str, Any]:
    """The id -> entry mapping inside a loaded index document.

    Two shapes are accepted without configuration: a document with a container
    key (``{"version": 1, "entries": {...}}``, this corpus) and a bare mapping
    of id to entry.  Anything else yields nothing rather than guessing -- a
    wrong guess about structure would report every row as broken, which is a
    louder failure than reporting none.
    """
    if not isinstance(doc, dict):
        return {}
    for key in ENTRY_CONTAINERS:
        inner = doc.get(key)
        if isinstance(inner, dict):
            return inner
    if all(isinstance(v, dict) for v in doc.values()) and doc:
        return doc
    return {}


def pointers(
    doc: Any,
    file_keys: frozenset[str] = FILE_KEYS,
    id_keys: frozenset[str] = ID_KEYS,
) -> list[Pointer]:
    """Every pointer in ``doc``, in entry order.

    A ``None`` value is skipped, not reported.  ``parent_id: null`` is how this
    corpus spells "this is a root", and calling a root a dangling pointer would
    flag the one entry that is definitionally correct.
    """
    out: list[Pointer] = []
    for entry_id, entry in _entries(doc).items():
        if not isinstance(entry, dict):
            continue
        for key, value in entry.items():
            if not isinstance(value, str) or not value:
                continue
            low = key.lower()
            if low in file_keys:
                out.append(Pointer(entry_id, key, "file", value))
            elif low in id_keys:
                out.append(Pointer(entry_id, key, "id", value))
    return out


def _relocations(root: Path, target: str) -> tuple[str, ...]:
    """Paths under ``root`` whose basename matches ``target``'s, as POSIX strings.

    Sorted so the report is reproducible across filesystems; ``rglob`` order is
    not guaranteed and a checker whose output reorders between runs cannot be
    diffed in CI.
    """
    name = Path(target).name
    if not name:
        return ()
    found = sorted(p for p in root.rglob(name) if p.is_file())
    return tuple(p.relative_to(root).as_posix() for p in found)


def inspect_doc(
    index: Path,
    doc: Any,
    root: Path | None = None,
    file_keys: frozenset[str] = FILE_KEYS,
    id_keys: frozenset[str] = ID_KEYS,
) -> Report:
    """Resolve every pointer in an already-loaded ``doc``.

    ``root`` defaults to the index file's own directory, because that is what
    the loader resolves against.  Passing it explicitly is for indexes whose
    paths are relative to a project root instead.
    """
    base = root if root is not None else index.parent
    known = set(_entries(doc))
    found: list[Broken] = []
    checked = 0
    for ptr in pointers(doc, file_keys, id_keys):
        checked += 1
        if ptr.kind == "id":
            if ptr.target not in known:
                found.append(Broken(ptr))
            continue
        if (base / ptr.target).exists():
            continue
        found.append(Broken(ptr, _relocations(base, ptr.target)))
    return Report(index=index, checked=checked, broken=tuple(found))


def inspect_file(
    index: Path,
    root: Path | None = None,
    file_keys: frozenset[str] = FILE_KEYS,
    id_keys: frozenset[str] = ID_KEYS,
) -> Report:
    """Load ``index`` as JSON and resolve its pointers.

    A malformed index raises rather than returning an empty report.  An index
    that cannot be parsed is an index whose pointers are unknown, and reporting
    "0 broken" for it would be the false all-clear this package exists to
    remove.
    """
    doc = json.loads(index.read_text(encoding="utf-8"))
    return inspect_doc(index, doc, root, file_keys, id_keys)


def scan(
    indexes: Iterable[Path],
    root: Path | None = None,
    file_keys: frozenset[str] = FILE_KEYS,
    id_keys: frozenset[str] = ID_KEYS,
) -> list[Report]:
    """One report per index, in path order, including the clean ones.

    Clean reports are kept rather than filtered because the caller needs the
    ``checked`` count to tell "everything resolves" from "nothing was looked
    at".  Rule (2) learned this the hard way: it reported a corpus with nothing
    comparable as clean, exit 0, and the blind case was indistinguishable from
    the healthy one.
    """
    return [inspect_file(p, root, file_keys, id_keys) for p in sorted(indexes)]


def repair_plan(report: Report) -> dict[str, str]:
    """``entry_id`` -> corrected path, for the unambiguous relocations only.

    Entries whose target is gone, or whose basename is ambiguous, are absent
    from the plan by construction. A repair tool that had to filter those out
    itself would eventually forget to.
    """
    return {
        b.pointer.entry_id: b.candidates[0]
        for b in report.broken
        if b.repairable and b.pointer.kind == "file"
    }

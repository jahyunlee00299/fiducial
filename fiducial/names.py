"""rule (2) — a file name that contradicts the file's own contents.

Why this exists (measured, on a private research repo used as the reference
corpus, 260919-260920):

    scripts/_refactor/configs/mpsp/optimizer_run_v15b_flask_5d_rpm150.yaml

carries `v15b` in its name while five interior fields all say `v16`
(`fit_json`, `parent_id`, `run_id`, `out_dir`, `meta_extra.variant`).  Line 13
of that very file admits it -- "260806: fit_json advanced v15b -> v16" -- and
the name was never updated.  A second file, `..._v15b_flask_7d_...`, carries the
same contradiction, and `optimizer_run_v17_..._pvrefit.yaml` extends one of them,
so a human reading the lineage sees "v17 <- v15b" where the truth is
"v17 <- v16".

The execution impact was checked and is nil: the children override every one of
those fields, so no v16 value ever propagates.  This is a lie told to a reader,
not a corrupted run -- and that is precisely why no test catches it.

Scope, deliberately narrow: we compare VERSION TOKENS only.  Other name tokens
in that corpus (``_det`` for mc_n=1, ``Nd`` for dimension count, ``NNh`` for the
reaction-time bound, ``rpm150``) were audited and all agree with their contents.
Widening the rule past version tokens would have produced only false positives
on the one corpus where we have ground truth.

The base rate is low and must be quoted honestly: of 127 files carrying a
version token on BOTH sides, 2 disagree with no overlap (1.6%), or 3 under the
stricter "set mismatch" reading (2.4%).  See ``Verdict`` below -- the choice
between those two readings is a real decision, not a detail, and the caller
makes it explicitly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# A version token: v1, v15b, v8_v3, V2.  Anchored on a word boundary so that
# `rev15` or `flask5d` never register as versions.
_VERSION_RE = re.compile(r"(?<![A-Za-z0-9])[vV](\d+[a-zA-Z]?)(?![A-Za-z0-9])")


def version_tokens(text: str) -> set[str]:
    """Every version token in ``text``, normalised to lower case.

    >>> sorted(version_tokens("optimizer_run_v15b_flask_5d"))
    ['v15b']
    >>> sorted(version_tokens("optimizer_run_b_v8_v3_s3soft"))
    ['v3', 'v8']
    """
    return {f"v{m.group(1).lower()}" for m in _VERSION_RE.finditer(text)}


@dataclass(frozen=True)
class Verdict:
    """One file's name-vs-content comparison.

    ``mismatch_strict``  -- the two token sets share nothing at all.  This is the
        conservative reading: the name and the contents agree on no version
        whatsoever.  Base rate on the reference corpus: 2/127 = 1.6%.

    ``mismatch_set``  -- the two sets are unequal.  This is the stricter reading
        and it catches one more real case: ``_archive/optimizer_run_b_v8_v3_...``
        is named ``v8_v3`` while its ``fit_json`` is ``run_b_ratio_v8_v4``, and
        its own ``parent_id`` comment confesses "legacy name only; actual
        fit_json is v4".  The shared ``v8`` hides it from the strict reading.
        Base rate: 3/127 = 2.4%.

    Reporting only ``mismatch_strict`` would miss that file, which is the same
    species of lie.  Reporting only ``mismatch_set`` raises the noise floor.  We
    compute both and let the caller pick; ``fiducial`` defaults to ``set``
    because the extra case it catches was real and the extra noise it admits was
    zero on the reference corpus.
    """

    path: Path
    name_tokens: frozenset[str]
    content_tokens: frozenset[str]

    @property
    def mismatch_strict(self) -> bool:
        return bool(self.name_tokens) and bool(self.content_tokens) and not (
            self.name_tokens & self.content_tokens
        )

    @property
    def mismatch_set(self) -> bool:
        return bool(self.name_tokens) and bool(self.content_tokens) and (
            self.name_tokens != self.content_tokens
        )

    @property
    def undecidable(self) -> bool:
        """Only one side carries a version token, so there is nothing to compare.

        On the reference corpus: 17 files are content-only and 2 are name-only.
        These are NOT violations -- a config that declares a version inside and
        keeps a neutral file name is fine.  Counting them would inflate the base
        rate with files that never made a claim.
        """
        return bool(self.name_tokens) != bool(self.content_tokens)

    def is_violation(self, mode: str = "set") -> bool:
        if mode == "strict":
            return self.mismatch_strict
        if mode == "set":
            return self.mismatch_set
        raise ValueError(f"mode must be 'strict' or 'set', got {mode!r}")

    def explain(self, mode: str = "set") -> str:
        name = ", ".join(sorted(self.name_tokens)) or "(none)"
        content = ", ".join(sorted(self.content_tokens)) or "(none)"
        return (
            f"{self.path}: name says {name} but contents say {content}. "
            "Rename the file or correct the fields -- a lineage token that "
            "disagrees with the file's own fields misleads every human reader "
            "of the `extends` chain, even when the loaded values are right."
        )


def strip_comments(text: str) -> str:
    """Drop ``#`` comments, keeping line structure.

    Measured, and the reason this function exists: scanning raw text made the
    reference golden case come out CLEAN.  That file's header comments narrate
    its own history -- "v15b lineage sibling of...", "fit_json advanced v15b ->
    v16", "v18/v19/v20 at 0.100/0.124/1.000 mM" -- so the raw text carries
    ``v15b`` and the name's token found a match in prose that merely *describes*
    the change.  The strict reading then reported no mismatch on the exact file
    the rule was built from.

    A comment explaining that the version moved is not the file declaring its
    version.  Only assigned values speak for the file, so comments come out
    before the comparison.

    ``#`` inside a quoted string is left alone; the scanner would otherwise
    truncate values like ``note: "run #3"``.
    """
    out = []
    for line in text.splitlines():
        quote = None
        cut = len(line)
        for i, ch in enumerate(line):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "#":
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


# Fields that exist to be read by a person, not resolved by the loader.  A
# version token here is narration, exactly like a comment: `description:` on the
# reference file still says "v15b 8cond fit" and `note:` mentions the canonical
# v8 sibling, while every field the loader actually resolves says v16.  Counting
# prose would have let the golden case pass the strict reading -- measured.
PROSE_KEYS = frozenset({"description", "note", "notes", "comment", "summary", "title"})

# Fields that deliberately name a DIFFERENT artefact: the parent this config
# inherits from, the warm-start it resumes.  A version token here is a pointer,
# not a self-declaration, so a child may legitimately carry its parent's version.
#
# Measured: without this exclusion the "set" reading fired on 27/127 files
# instead of 3.  Nearly all of the excess were honest children -- `v18c` naming
# `v18` on its `extends:` line, `v17` naming `v15b` on its.  Those files are not
# lying about themselves; they are correctly citing a parent.  Folding a pointer
# into the file's own identity turns ordinary lineage into a violation and would
# have made the rule unusable on the one corpus where ground truth exists.
REFERENCE_KEYS = frozenset({"extends", "base", "inherit", "inherits", "warm_start", "from"})

# A value that is a PATH points at another artefact by construction, whatever
# the key is called.  Keying the exclusion on the key name alone proved too
# brittle: `extends:` covered the children, but `ratio_source:` (a separate
# ratio fit) and `warm_path:` (a warm-start origin) leaked the same way, each
# under a key nobody would think to list in advance.  Recognising the SHAPE of
# the value catches the whole family, including keys not invented yet.
#
# `fit_json`, `parent_id`, `run_id`, `out_dir` are deliberately NOT excluded:
# they are how the reference file declares which fit it IS, and dropping them
# would silence the golden case.  `fit_json` and `out_dir` do hold paths, so the
# discriminator cannot be "is a path" alone -- it is "is a path AND the key is
# not one of the self-declaring ones".
SELF_DECLARING_KEYS = frozenset(
    {"fit_json", "parent_id", "run_id", "out_dir", "variant", "id", "name"}
)

_PATHLIKE_RE = re.compile(r"[\\/]")

_KEY_RE = re.compile(r"^\s*(?:-\s*)?([A-Za-z_][\w.-]*)\s*:")


def strip_nonself_fields(
    text: str,
    prose_keys: frozenset[str] = PROSE_KEYS,
    reference_keys: frozenset[str] = REFERENCE_KEYS,
    self_declaring_keys: frozenset[str] = SELF_DECLARING_KEYS,
) -> str:
    """Blank out the VALUE of any ``key: value`` that does not speak for this file.

    Two kinds are dropped -- narration (``description:``) and pointers to other
    artefacts (``extends:``).  The key itself is kept so line numbers and
    structure survive; only the value goes, because that is where the foreign
    version sits.
    """
    drop = prose_keys | reference_keys
    out = []
    for line in text.splitlines():
        m = _KEY_RE.match(line)
        if not m:
            out.append(line)
            continue
        key = m.group(1).split(".")[-1].lower()
        value = line[m.end():]
        is_reference = key in drop or (
            key not in self_declaring_keys and _PATHLIKE_RE.search(value)
        )
        out.append(line[: m.end()] if is_reference else line)
    return "\n".join(out)


def inspect_text(
    path: Path,
    text: str,
    prose_keys: frozenset[str] = PROSE_KEYS,
    reference_keys: frozenset[str] = REFERENCE_KEYS,
    self_declaring_keys: frozenset[str] = SELF_DECLARING_KEYS,
) -> Verdict:
    """Compare ``path``'s stem against the versions the file declares ABOUT ITSELF.

    Three things are removed before comparing, and each was forced by a
    measurement that the previous version failed -- none was chosen up front:

    1. comments -- a header narrating "fit_json advanced v15b -> v16" explains
       the file, it does not declare it.  Without this the golden case came out
       CLEAN under the strict reading.
    2. prose values (``description``, ``note``) -- same thing in fields the
       loader carries but never resolves.  Without this the golden case STILL
       came out clean: its ``description`` repeats "v15b" while all five
       resolved fields say v16.
    3. reference values (``extends``, ``base``) -- these name a different
       artefact on purpose.  Without this the "set" reading fired on 27/127
       files instead of 3, nearly all of them honest children citing a parent.

    What remains is the set of versions this file asserts as its own.
    """
    body = strip_nonself_fields(
        strip_comments(text), prose_keys, reference_keys, self_declaring_keys
    )
    return Verdict(
        path=path,
        name_tokens=frozenset(version_tokens(path.stem)),
        content_tokens=frozenset(version_tokens(body)),
    )


def inspect_file(
    path: Path,
    prose_keys: frozenset[str] = PROSE_KEYS,
    reference_keys: frozenset[str] = REFERENCE_KEYS,
    self_declaring_keys: frozenset[str] = SELF_DECLARING_KEYS,
) -> Verdict:
    return inspect_text(
        path,
        path.read_text(encoding="utf-8", errors="replace"),
        prose_keys,
        reference_keys,
        self_declaring_keys,
    )


def scan(
    paths: Iterable[Path],
    mode: str = "set",
    prose_keys: frozenset[str] = PROSE_KEYS,
    reference_keys: frozenset[str] = REFERENCE_KEYS,
    self_declaring_keys: frozenset[str] = SELF_DECLARING_KEYS,
) -> list[Verdict]:
    """Every violating file among ``paths``, in path order.

    Reading failures are not swallowed: a file we cannot read is a file we
    cannot clear, and pretending otherwise is the silence this package exists to
    remove.

    The three key sets are parameters rather than constants because they are
    this corpus's field names. ``inspect_text`` already took two of them and
    ``scan``/``inspect_file`` swallowed the defaults, so no caller could reach
    them -- a knob wired to nothing. A project whose configs declare themselves
    with different field names now supplies its own through
    ``[tool.fiducial]``.
    """
    out: list[Verdict] = []
    for p in sorted(paths):
        v = inspect_file(p, prose_keys, reference_keys, self_declaring_keys)
        if v.is_violation(mode):
            out.append(v)
    return out

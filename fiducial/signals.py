"""Structured findings, for a caller that is a program rather than a person.

Why this exists
---------------
The five rules were written for a human reading a terminal, and the prose they
emit is the good part: each `explain()` says what is wrong *and why it matters*.
But the audience has changed. A person who sets parameters by hand rarely runs
a checker like this -- they already know where their numbers came from. An LLM
writing the code does not, and `params.get("eta", 0.87)` is precisely what a
model does when it needs a number it does not have.

So the rules matter most when the caller is an agent, and an agent needs
something the prose cannot give it: **what to do about each finding**.

Three exit codes are not enough for that
----------------------------------------
`0/1/2` tells a caller whether anything was found. It does not distinguish

    the file moved and the correction is determined
    the file is gone and only a person knows where

Both are certain violations. One is safe to fix unattended; the other must not
be guessed at. Collapsing them loses the distinction exactly where it matters,
and an agent that treats them alike will invent a path.

Two axes, because one cannot carry it
-------------------------------------
    confidence   is this finding real?        certain | needs_review
    fix          can it be repaired, and may  (absent) | safe/auto
                 the caller apply it alone?   | unsafe/suggest_only

They are independent, which is the whole reason for two of them. Rule (5)'s
"gone" case is *certain* with no fix. Rule (2) fires on 1.6% of comparable
files, so it is *needs_review* -- yet its repair is mechanical. A single
severity ladder would have to put those two somewhere, and wherever it put
them would be wrong for one of them.

Borrowed, not invented
----------------------
`applicability: safe | unsafe` is Ruff's, measured from `ruff check
--output-format=json` (0.16.0) rather than taken from its docs. `apply: auto |
suggest_only` is ESLint's `fix` versus `suggestions` split: one the tool
applies, the other it only offers.

SARIF was considered and rejected. Its `level` has no value for "the check
could not run", and `kind: notApplicable` means "did not apply here", not "should
have been checked and was not" -- which is this package's entire argument. Its
`fixes[]` carries no safety grade either, so the two fields that matter here
would both land in non-standard `properties`. A five-rule tool does not need a
multi-level envelope to say that.

What a consumer can rely on
---------------------------
Every finding carries `status`, `confidence`, `rule`, `message`. `fix` is
present only when a repair exists, so `"fix" in finding` is the question "can
this be automated at all", and `finding["fix"]["apply"] == "auto"` is "may I do
it without asking". Nothing else needs to be parsed out of prose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

#: A finding is a real violation, or a report that the rule could not run.
#: There is no "warning" tier: a rule that fires has decided, and a rule that
#: could not decide says so with `cannot_check` instead of softening its verdict.
Status = Literal["violation", "cannot_check"]

#: `certain`      -- the rule's own logic settles it, no judgement left
#: `needs_review` -- real by the rule's definition, but the base rate is low
#:                   enough, or the case marginal enough, that a caller should
#:                   look before acting
Confidence = Literal["certain", "needs_review"]

#: Ruff's vocabulary, and its meaning: does applying this change what the code
#: or config MEANS? `safe` does not, `unsafe` might.
Applicability = Literal["safe", "unsafe"]

#: ESLint's split. `auto` may be applied by the caller unattended; the agent
#: instructions below say so in words as well.
ApplyMode = Literal["auto", "suggest_only"]

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Fix:
    """A repair, and how much authority the caller has to apply it.

    ``edit`` is deliberately loose. Rule (5) can name a field and its corrected
    value; rules (1) and (3) cannot propose anything mechanical at all and so
    produce no ``Fix``. Inventing a uniform edit format across five rules that
    repair five different kinds of artefact would produce a shape that fits
    none of them.
    """

    applicability: Applicability
    apply: ApplyMode
    edit: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"applicability": self.applicability, "apply": self.apply}
        if self.edit is not None:
            out["edit"] = self.edit
        return out


@dataclass(frozen=True)
class Signal:
    """One finding, in the form a program consumes.

    ``message`` is the rule's own ``explain()`` text, unchanged. It is the part
    that says *why* the finding matters, and an agent deciding what to do with
    a finding needs that as much as a person does -- so it is carried, not
    replaced by a code.
    """

    rule: str
    status: Status
    confidence: Confidence
    message: str
    path: str | None = None
    entry: str | None = None
    line: int | None = None
    key: str | None = None
    fix: Fix | None = None
    #: What the caller should do. Spelled out rather than left implied: an
    #: agent reading one finding in isolation has no access to this docstring.
    action: str = ""

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "status": self.status,
            "confidence": self.confidence,
            "message": self.message,
        }
        for name in ("path", "entry", "line", "key"):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        if self.fix is not None:
            out["fix"] = self.fix.as_dict()
        if self.action:
            out["action"] = self.action
        return out


# --------------------------------------------------------------------------
# what the caller should do, per shape of finding
# --------------------------------------------------------------------------

#: These strings ship inside the output on purpose. An agent handling one
#: finding does not read this module, and a caller that has to be told
#: separately how to interpret `apply: auto` is a caller that will guess.
ACTION = {
    "auto": (
        "Apply the fix. It is determined -- there is exactly one correct "
        "repair and it does not change what anything means."
    ),
    "choose": (
        "Do not pick one yourself. Show the candidates and let a person "
        "choose; guessing here points the artefact at the wrong target."
    ),
    "investigate": (
        "No mechanical repair exists. Find where the value actually came "
        "from and record it, or read it from the source that owns it. Do not "
        "substitute a plausible number."
    ),
    "ask": (
        "A person has to decide. The artefact this names is missing entirely, "
        "so nothing in the repository can supply the answer."
    ),
    "review": (
        "Check before acting. The rule is right by its own definition, but "
        "this shape has a low enough base rate that the finding deserves a "
        "look rather than an edit."
    ),
    "configure": (
        "The rule could not run. Fix the invocation or the configuration -- "
        "this is not a clean result, and treating it as one is the failure "
        "this tool exists to refuse."
    ),
}


def _rel(path: Any) -> str:
    return str(path)


def from_pointers(reports: list[Any]) -> list[Signal]:
    """Rule (5). The three-way split is already computed; this names it.

    ``candidates`` carries the whole decision:

        1     the file moved, one correct target      -> safe/auto
        0     nothing by that name exists anywhere    -> no fix, ask a person
        2+    ambiguous                               -> unsafe/suggest_only

    All three are ``certain`` -- the registry demonstrably does not resolve.
    What differs is who is allowed to act, which is exactly why confidence and
    fix are separate fields.
    """
    out: list[Signal] = []
    for report in reports:
        if report.blind:
            out.append(
                Signal(
                    rule="pointers",
                    status="cannot_check",
                    confidence="certain",
                    message=report.summary(),
                    path=_rel(report.index),
                    action=ACTION["configure"],
                )
            )
            continue

        for broken in report.broken:
            ptr = broken.pointer
            if ptr.kind == "id":
                out.append(
                    Signal(
                        rule="pointers",
                        status="violation",
                        confidence="certain",
                        message=broken.explain(),
                        path=_rel(report.index),
                        entry=ptr.entry_id,
                        key=ptr.key,
                        action=ACTION["ask"],
                    )
                )
                continue

            if broken.repairable:
                fix = Fix(
                    applicability="safe",
                    apply="auto",
                    edit={"field": ptr.key, "to": broken.candidates[0]},
                )
                action = ACTION["auto"]
            elif broken.candidates:
                fix = Fix(
                    applicability="unsafe",
                    apply="suggest_only",
                    edit={"field": ptr.key, "candidates": list(broken.candidates)},
                )
                action = ACTION["choose"]
            else:
                fix = None
                action = ACTION["ask"]

            out.append(
                Signal(
                    rule="pointers",
                    status="violation",
                    confidence="certain",
                    message=broken.explain(),
                    path=_rel(report.index),
                    entry=ptr.entry_id,
                    key=ptr.key,
                    fix=fix,
                    action=action,
                )
            )
    return out


def from_literals(findings: list[Any]) -> list[Signal]:
    """Rule (1). No mechanical repair exists, and that is the point.

    The tool knows the number has no provenance; it cannot know what the
    provenance was. Emitting a fix here would invite an agent to write in a
    plausible source, which is the failure mode the rule was built to catch --
    so every finding is ``investigate``, with no ``fix`` key at all.

    ``neutral`` lowers confidence rather than hiding the finding: a default of
    0.0 or 1.0 usually means "switched off" rather than "a measurement was
    invented", so it is reported and flagged for a look.
    """
    return [
        Signal(
            rule="literals",
            status="violation",
            confidence="needs_review" if f.neutral else "certain",
            message=f.explain(),
            path=_rel(f.path),
            line=f.line,
            key=f.key,
            action=ACTION["review"] if f.neutral else ACTION["investigate"],
        )
        for f in findings
    ]


def from_names(verdicts: list[Any], mode: str = "set") -> list[Signal]:
    """Rule (2). Mechanical to repair, but low base rate -- so: review.

    Two edits would resolve any of these (rename the file, or correct the
    fields), and the tool cannot tell which one the author intended. That is a
    genuine choice rather than a missing feature, so the fix is offered as
    candidates and never applied unattended.

    Measured base rate on the reference corpus: 1.6% strict, 2.4% set. Low
    enough that ``needs_review`` is the honest confidence, and saying so beats
    quietly reporting every hit as certain.
    """
    out: list[Signal] = []
    for v in verdicts:
        out.append(
            Signal(
                rule="names",
                status="violation",
                confidence="needs_review",
                message=v.explain(mode),
                path=_rel(v.path),
                fix=Fix(
                    applicability="unsafe",
                    apply="suggest_only",
                    edit={
                        "name_says": sorted(v.name_tokens),
                        "contents_say": sorted(v.content_tokens),
                        "resolve_by": "rename the file, or correct the fields",
                    },
                ),
                action=ACTION["choose"],
            )
        )
    return out


def from_coverage(
    results: list[Any], baseline: frozenset[str] | set[str] | None = None
) -> list[Signal]:
    """Rule (3). A missing test is not something a checker can write.

    ``results`` is every declared key, gated or not -- ``analyse`` reports the
    whole spec -- so the gaps are selected here rather than assumed. Keys that
    are asserted or pinned produce no signal at all: a finding for something
    that is fine would make a consumer filter before it could count.

    ``baseline`` carries the gaps a project already had. They stay in the
    output, because an agent that cannot see them will propose closing a gap
    twice, but they drop to ``needs_review`` and say so: a pre-existing gap is
    a backlog item, and treating it as a fresh regression is how a ratchet
    gets bypassed on its first real use.

    No ``fix`` is emitted either way. An agent *can* write the missing test,
    and the action text says so -- but that is authorship, not a mechanical
    edit, and the two must not arrive through the same field.
    """
    known = set(baseline or ())
    out: list[Signal] = []
    for r in results:
        if not r.is_gap:
            continue
        pre_existing = r.key in known
        out.append(
            Signal(
                rule="coverage",
                status="violation",
                confidence="needs_review" if pre_existing else "certain",
                message=r.explain(),
                key=r.key,
                action=(
                    "Recorded in the baseline already, so it is not a new "
                    "regression. Close it when the parameter is next touched "
                    "rather than as an unrelated edit."
                    if pre_existing
                    else "Write a test that asserts something about this "
                    "parameter, or remove it from the spec if it is no longer "
                    "measured. Mentioning the key in a test without asserting "
                    "on it does not close this."
                ),
            )
        )
    return out


def from_docs(
    findings: list[Any],
    gaps: list[Any] | None = None,
    errors: list[tuple[Any, str]] | None = None,
) -> list[Signal]:
    """Rule (4). The upstream value is known, so the repair is determined.

    A derived document declares which upstream it repeats and what it repeats
    from it. When the two disagree, the correct value is not a guess -- it is
    the one the declaration points at. That makes this the only rule besides
    (5) that can offer a ``safe`` fix.

    A ``SourceGap`` is different: a label missing from one side means the
    comparison never happened, which is ``cannot_check`` rather than a clean
    pass.

    ``errors`` are documents whose declaration would not parse. Their author
    believes they are gated and they are not, so they are the loudest
    ``cannot_check`` of the three -- never folded into a clean count.
    """
    out: list[Signal] = []
    for f in findings:
        out.append(
            Signal(
                rule="docs",
                status="violation",
                confidence="certain",
                message=f.explain() if hasattr(f, "explain") else str(f),
                path=_rel(f.path),
                line=getattr(f, "line_no", None),
                key=getattr(f, "label", None),
                fix=Fix(
                    applicability="safe",
                    apply="auto",
                    edit={
                        "label": getattr(f, "label", None),
                        "found": getattr(f, "found", None),
                        "to": getattr(f, "declared", None),
                        "source": _rel(getattr(f, "source", "")),
                    },
                ),
                action=ACTION["auto"],
            )
        )
    for g in gaps or []:
        out.append(
            Signal(
                rule="docs",
                status="cannot_check",
                confidence="certain",
                message=g.explain() if hasattr(g, "explain") else str(g),
                path=_rel(getattr(g, "path", "")),
                key=getattr(g, "label", None),
                action=ACTION["configure"],
            )
        )
    for path, reason in errors or []:
        out.append(
            Signal(
                rule="docs",
                status="cannot_check",
                confidence="certain",
                message=f"{path}: declaration could not be read -- {reason}",
                path=_rel(path),
                action=(
                    "This document declares an SSOT that could not be parsed, "
                    "so it was NOT checked while its author believes it is "
                    "gated. Fix the declaration before trusting any number in "
                    "it."
                ),
            )
        )
    return out


# --------------------------------------------------------------------------
# the document a caller reads
# --------------------------------------------------------------------------


@dataclass
class Envelope:
    """Everything one run produced, with the counts a caller acts on.

    ``summary`` exists so a consumer does not have to tally the list to answer
    the only two questions it usually has: is there anything I may fix on my
    own, and is there anything a person has to see.
    """

    signals: list[Signal] = field(default_factory=list)
    version: int = SCHEMA_VERSION

    def summary(self) -> dict[str, int]:
        auto = sum(
            1 for s in self.signals if s.fix is not None and s.fix.apply == "auto"
        )
        blocked = sum(1 for s in self.signals if s.status == "cannot_check")
        return {
            "total": len(self.signals),
            "violations": sum(1 for s in self.signals if s.status == "violation"),
            "cannot_check": blocked,
            "auto_fixable": auto,
            "needs_human": sum(
                1
                for s in self.signals
                if s.status == "violation"
                and (s.fix is None or s.fix.apply != "auto")
            ),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "summary": self.summary(),
            "findings": [s.as_dict() for s in self.signals],
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, ensure_ascii=False)


def from_units(mismatches: list[Any]) -> list[Signal]:
    """Rule (4), unit axis. Certain, and not mechanically repairable.

    A unit mismatch is only reachable when the numbers already agree, so it is
    the one finding that survives every other check passing -- which is why it
    is reported separately rather than folded into the value comparison.

    No ``fix``: the tool knows the two documents disagree about the unit, not
    which one is right. Repairing it means either changing the number to suit
    the unit or the unit to suit the number, and those are different claims
    about the world. Guessing between them is exactly the substitution this
    package refuses.
    """
    return [
        Signal(
            rule="docs",
            status="violation",
            confidence="certain",
            message=m.explain(),
            path=_rel(m.path),
            line=m.line_no,
            key=m.label,
            action=(
                "Decide which side is right before changing either. The "
                "numbers agree, so one document has the wrong unit and the "
                "other has the wrong magnitude -- correcting the unit alone "
                "may leave the value wrong by that factor."
            ),
        )
        for m in mismatches
    ]

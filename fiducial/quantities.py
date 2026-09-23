"""Unit and precision of a written quantity — the two axes a bare float loses.

Why this exists (measured, 260923)
----------------------------------
Rule ④ compared two readings of one quantity as ``float`` against ``float``.
Two documents can therefore agree perfectly while meaning different things::

    SSOT.md      | 반응 시간 | 48 h |
    DERIVED.md     반응 시간 48 min 으로 운전한다.

    $ fiducial docs docs/
    fiducial docs: 0 violation(s)          # ← measured, before this module

Changing 48 to 36 was caught; changing ``h`` to ``min`` was not. The unit was
matched by ``_tail_pattern`` and thrown away, so a 60x error read as agreement.

This is **not** the physics-guessing trap the README warns about. Nothing here
decides which unit is correct, and nothing converts between them. It compares
what the author declared against what the author wrote, the same
declared-versus-written comparison rule ④ already makes for the number. A
document that declares no unit is not checked for one.

Significant figures, and why they are a separate question
---------------------------------------------------------
``74.09`` and ``74.09268`` are the same quantity to different precision. In
prose that is usually fine. It stops being fine when a rounded copy is used in
arithmetic that a full-precision value also touches: the reference project
measured ``_MW_CAOH2 = 74.09`` (against 74.09268) creating calcium atoms at
+2.139e-6 kmol/hr in a mass balance that read as exactly closed, because the
unit model built mass ratios from the rounded constant while the stream library
converted moles with the full value.

So precision is reported **separately** from disagreement, and by default only
when the declaration asks for it. A value that agrees to the precision printed
is not a defect; a value printed to *fewer* figures than its source while being
declared equal to it is a lossy copy worth naming.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: A unit token sitting immediately after a number: `48 h`, `30 °C`, `2.4 g/L`,
#: `5 mg·mL⁻¹`, `100 %`. Deliberately permissive about the characters a unit may
#: contain and strict about where it may start — anything further away than one
#: space is prose, not a unit.
#:
#: Letters, `%`, `°`, `Ω`, `µ`, superscripts and the separators `/·⁻¹^-` are in;
#: a trailing period, comma or Korean particle is out (those belong to the
#: sentence). `_UNIT_STOP` holds the words that look like units but are the next
#: word of a sentence.
#: Superscript characters used in unit exponents: ⁻ ¹ ² ³ and friends.
_SUP = "\u207b\u00b9\u00b2\u00b3\u2070\u2074-\u209c"
#: Korean unit nouns that attach directly to a number (`36시간`, `5일`).
#: Only genuine units belong here — a particle like `으로` stays out and is
#: rejected by `_UNIT_STOP`.
_KO_UNITS = "시간|분|초|일|배"

_UNIT_RE = re.compile(
    r"[ \t\u00a0]?"
    r"(?P<unit>"
    r"(?:%|°[CFK]?|Ω|℃|℉)"
    r"|(?:" + _KO_UNITS + r")"
    r"|(?:[A-Za-zµμ][A-Za-z0-9µμ°Ω" + _SUP + r"]*"
    r"(?:\s?[/·⋅*]\s?[A-Za-z0-9µμ°Ω" + _SUP + r"]+)*"
    r"(?:\^-?\d+)?)"
    r")"
)

#: Words that follow a number but are sentence, not unit. Measured against the
#: reference corpus: without this, `48 으로`, `30 and`, `2 or` become units.
#: Korean particles are already stripped by the locale tail pattern; these are
#: the English ones plus the handful of Korean nouns that survive it.
_UNIT_STOP = frozenset({
    "and", "or", "to", "of", "in", "at", "for", "with", "by", "the", "a", "an",
    "is", "was", "were", "are", "as", "than", "then", "per", "each", "from",
    "into", "on", "over", "under", "about", "approx", "approximately",
    "이상", "이하", "미만", "초과", "정도", "가량", "으로", "에서", "까지",
})

#: Units that are written several ways and mean one thing. This is **not** a
#: conversion table — every pair here is the same unit under a different
#: spelling, so folding them prevents a false finding rather than making a
#: physical judgement. `h` and `min` are deliberately absent from each other.
_UNIT_ALIASES = {
    "degc": "°c", "degreec": "°c", "celsius": "°c", "℃": "°c", "c": "°c",
    "degf": "°f", "℉": "°f",
    "degk": "k", "kelvin": "k",
    "hr": "h", "hrs": "h", "hour": "h", "hours": "h", "시간": "h",
    "min": "min", "mins": "min", "minute": "min", "minutes": "min", "분": "min",
    "sec": "s", "secs": "s", "second": "s", "seconds": "s", "초": "s",
    "day": "d", "days": "d", "일": "d",
    "litre": "l", "liter": "l", "l": "l",
    "percent": "%", "pct": "%", "퍼센트": "%",
    "molar": "m",
}


def normalise_unit(unit: str | None) -> str | None:
    """A unit token folded to one spelling, or ``None`` when there is none.

    Only spelling is folded (``hr`` -> ``h``, ``degC`` -> ``°C``). Nothing is
    converted: ``min`` stays ``min`` and will not compare equal to ``h``.
    """
    if not unit:
        return None
    u = unit.strip().strip(".,;:)》」]").replace(" ", " ")
    u = re.sub(r"\s+", "", u)
    if not u:
        return None
    low = u.lower()
    if low in _UNIT_STOP:
        return None
    return _UNIT_ALIASES.get(low, low)


def split_quantity(text: str) -> tuple[str | None, str | None]:
    """``(number text, unit)`` from a declaration scalar like ``"48 h"``.

    Returns ``(None, None)`` when *text* holds no leading number, so a
    declaration carrying a plain string is left alone rather than half-read.
    """
    if not isinstance(text, str):
        return (None, None)
    m = re.match(r"\s*(?P<num>[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?)", text)
    if not m:
        return (None, None)
    rest = text[m.end():]
    um = _UNIT_RE.match(rest)
    unit = normalise_unit(um.group("unit")) if um else None
    return (m.group("num"), unit)


def unit_after(line: str, end_pos: int) -> str | None:
    """The unit written immediately after a number ending at *end_pos*."""
    m = _UNIT_RE.match(line[end_pos:])
    return normalise_unit(m.group("unit")) if m else None


def significant_figures(num_text: str) -> int:
    """How many significant figures *num_text* is written to.

    Trailing zeros after a decimal point count (``2.40`` is 3); a bare integer's
    trailing zeros do not (``100`` is 1, because ``100`` and ``1.00e2`` are not
    the same claim in print).
    """
    s = num_text.strip().replace(",", "").lstrip("+-")
    if not s:
        return 0
    if "e" in s.lower():
        s = re.split(r"[eE]", s)[0]
    if "." in s:
        intpart, frac = s.split(".", 1)
        digits = (intpart + frac).lstrip("0")
        return len(digits) if digits else len(frac)
    s = s.lstrip("0")
    return len(s.rstrip("0")) or 1


@dataclass(frozen=True)
class UnitMismatch:
    """One quantity written with a unit its declaration does not state."""

    path: object
    source: object
    label: str
    declared_unit: str
    found_unit: str | None
    line_no: int
    line: str

    def explain(self) -> str:
        found = self.found_unit or "no unit"
        return (
            f"{self.path}:{self.line_no}: {self.label} is declared in "
            f"{self.declared_unit!r} but this states {found!r}. The numbers "
            f"agree, so nothing else reports it -- a quantity that matches in "
            f"magnitude and differs in unit is the error this check exists for."
            f"\n    {self.line}"
        )


@dataclass(frozen=True)
class PrecisionLoss:
    """A repeated value printed to fewer figures than its declaration."""

    path: object
    source: object
    label: str
    declared_sigfigs: int
    found_sigfigs: int
    declared_text: str
    line_no: int
    line: str

    def explain(self) -> str:
        return (
            f"{self.path}:{self.line_no}: {self.label} is declared as "
            f"{self.declared_text} ({self.declared_sigfigs} s.f.) but this "
            f"prints {self.found_sigfigs} s.f. A rounded copy reads as the same "
            f"quantity and stops being one as soon as arithmetic uses both."
            f"\n    {self.line}"
        )

"""Language-specific patterns for rule (4), kept out of the core.

Rule (4) reads values out of prose, and prose has a language.  The rule was
built against a Korean-and-English research corpus, so its first implementation
carried Korean directly in the core: particles that attach to a number
(``pH 10이``), copulas that mark a past value (``였다``, ``이었``), and the words
that mark a sentence as citing somebody else's process (``선례``, ``특허``).

Those patterns are correct and they stay.  They just do not belong in a module
every user loads.  A project working only in English should not have to read
Korean regexes to understand why a line was skipped, and a project working in a
third language needs somewhere to add its own without editing the package.

So each language is a small record, selected in configuration::

    [tool.fiducial]
    locales = ["en", "ko"]

``en`` is always active.  Naming any locale ADDS to it rather than replacing
it, because a document that mixes languages is the normal case in the corpus
this was built on -- a Korean process note citing an English patent.

What a locale contributes
-------------------------
``value_tail``       characters that may follow a number and are not part of it.
                     Korean particles: ``36시간으로`` must read 36, not 36-and-a-particle.
``label_joiners``    what may sit between a label and its value (``는``, ``은``).
``history_markers``  substrings that mark the line as describing a PAST or
                     rejected value.  Without them every audit trail and every
                     "we corrected X to Y" sentence becomes a finding, which is
                     the documented way these checks get switched off.
``citation_markers`` substrings that mark the number as somebody else's.  The
                     incident this rule exists for turned on exactly this
                     distinction: ``CN101904484A uses pH 5.0`` is a true
                     sentence about prior art, and flagging it teaches the
                     author to disable the gate.

Adding a language is a data change, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class UnknownLocale(ValueError):
    """A locale was named that this package does not carry.

    Raised rather than ignored. Silently falling back to English would leave a
    Korean corpus scanned with English-only patterns while the author believes
    their locale is active -- findings would quietly change shape, and the
    config would be the last place anyone looked.
    """


@dataclass(frozen=True)
class Locale:
    code: str
    #: Alternatives allowed to trail a number without being part of it.
    value_tail: tuple[str, ...] = ()
    #: Alternatives allowed between a label and its number.
    label_joiners: tuple[str, ...] = ()
    #: Substrings meaning "this line describes a past or rejected value".
    history_markers: tuple[str, ...] = ()
    #: Substrings meaning "this number belongs to someone else's process".
    citation_markers: tuple[str, ...] = ()


#: Always active. The markup and the arrow forms are language-independent: a
#: struck-through value and an `X -> Y` correction read the same in any prose.
EN = Locale(
    code="en",
    label_joiners=("=", ":"),
    history_markers=(
        "~~",
        "superseded", "retracted", "replaced", "deprecated", "legacy",
        "stale", "was ", "formerly", "previously",
        "→", "->",
    ),
    citation_markers=("doi:", "http://", "https://", "et al."),
)

#: Measured against a Korean research corpus. The particle list is the part
#: that cannot be guessed: without it `pH 10이` either fails to match or reads
#: the particle as part of the number.
KO = Locale(
    code="ko",
    value_tail=(
        "이", "가", "은", "는", "을", "를",
        "으로", "로", "와", "과", "의", "에",
        "에서", "부터", "까지", "다", "임",
        "이다",
    ),
    label_joiners=("는", "은", "이", "가"),
    history_markers=(
        "폐기", "철회", "정정", "이전",
        "구값", "옛",
        "였다", "이었", "했었", "보였",
        "나왔", "당시",
    ),
    citation_markers=(
        "선례", "특허", "문헌", "출처", "인용",
        "참고",
    ),
)

AVAILABLE: dict[str, Locale] = {loc.code: loc for loc in (EN, KO)}


@dataclass(frozen=True)
class LocaleSet:
    """The union of the selected locales, ready for the matchers."""

    codes: tuple[str, ...]
    value_tail: tuple[str, ...] = ()
    label_joiners: tuple[str, ...] = ()
    history_markers: tuple[str, ...] = ()
    citation_markers: tuple[str, ...] = field(default=())


def resolve(
    codes: tuple[str, ...] = (),
    extra_history_markers: tuple[str, ...] = (),
) -> LocaleSet:
    """Union ``codes`` with English, which is always on.

    An unknown code raises. Ignoring it would scan a corpus with the wrong
    patterns while the config says otherwise, which is the silent
    miscalibration this package exists to refuse.
    """
    wanted = ["en"] + [c for c in codes if c != "en"]
    unknown = [c for c in wanted if c not in AVAILABLE]
    if unknown:
        raise UnknownLocale(
            f"unknown locale(s) {unknown}. Available: {sorted(AVAILABLE)}. "
            "Naming a locale this package does not carry would leave the text "
            "scanned with the wrong patterns, so this is an error rather than "
            "a fallback."
        )

    def gather(attr: str) -> tuple[str, ...]:
        out: list[str] = []
        for code in wanted:
            for item in getattr(AVAILABLE[code], attr):
                if item not in out:
                    out.append(item)
        return tuple(out)

    history = gather("history_markers")
    for marker in extra_history_markers:
        if marker not in history:
            history += (marker,)

    return LocaleSet(
        codes=tuple(wanted),
        value_tail=gather("value_tail"),
        label_joiners=gather("label_joiners"),
        history_markers=history,
        citation_markers=gather("citation_markers"),
    )


#: What the rule uses when nothing is configured. Korean is included because
#: that is what the rule was measured on and dropping it would silently change
#: the behaviour of every existing caller; a project that wants English only
#: sets `locales = ["en"]`.
DEFAULT = resolve(("ko",))

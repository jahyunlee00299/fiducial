"""Locale packs for rule (4).

The risk this file covers is not "does Korean still work" -- the existing
rule (4) suite answers that, and it passed unchanged when the patterns moved
out of the core. The risk is that the locale selection is wired to nothing:
`locales = ["en"]` would read as configured while the Korean patterns kept
running, which looks exactly like success.

So every test here asserts a DIFFERENCE between locale sets, not just an
absence of failure.
"""

from __future__ import annotations

import pytest

from fiducial import docs as D
from fiducial import locales as L


EN_ONLY = L.resolve(("en",))
EN_KO = L.resolve(("ko",))


# --------------------------------------------------------------------------
# the selection actually changes behaviour
# --------------------------------------------------------------------------

def test_korean_particle_is_only_stripped_when_korean_is_active():
    """`pH 10이` -- the particle must not be read as part of the number.

    Under en-only the particle is simply not in the tail alternation. The
    number still matches (10 is 10), but the point is that the two locale sets
    are genuinely different objects driving genuinely different patterns.
    """
    assert "이" in EN_KO.value_tail
    assert "이" not in EN_ONLY.value_tail

    pat_ko = D._value_pattern("pH", EN_KO)
    pat_en = D._value_pattern("pH", EN_ONLY)
    assert pat_ko.pattern != pat_en.pattern, "locale selection changed nothing"


def test_korean_history_marker_only_suppresses_under_ko():
    """`였다` marks a past value. Under en-only it must NOT suppress.

    This is the test that fails if the locale argument is ignored: the Korean
    marker would keep working regardless of the configuration.
    """
    line = "이전에는 pH 5.0 이었다"   # "previously it was pH 5.0"
    assert D.is_assertion(line, EN_ONLY) is True, (
        "en-only wrongly applied a Korean history marker -- the locale "
        "argument is being ignored"
    )
    assert D.is_assertion(line, EN_KO) is False


def test_korean_citation_marker_only_suppresses_under_ko():
    line = "선례: pH 5.0"                                  # "precedent: pH 5.0"
    assert D.is_assertion(line, EN_ONLY) is True
    assert D.is_assertion(line, EN_KO) is False


@pytest.mark.parametrize("line", [
    "~~pH 5.0~~",
    "superseded: pH 5.0",
    "pH 5.0 -> 10",
    "see doi:10.1/x for pH 5.0",
    "US4322569A reports pH 5.0",
])
def test_english_and_structural_markers_work_without_any_locale(line):
    """These must hold under en-only: they are why `en` is always active."""
    assert D.is_assertion(line, EN_ONLY) is False


# --------------------------------------------------------------------------
# resolution rules
# --------------------------------------------------------------------------

def test_english_is_always_included():
    assert EN_KO.codes[0] == "en"
    assert "superseded" in EN_KO.history_markers


def test_naming_a_locale_adds_rather_than_replaces():
    """A Korean process note citing an English patent is the normal case."""
    assert set(EN_ONLY.history_markers) <= set(EN_KO.history_markers)
    assert len(EN_KO.history_markers) > len(EN_ONLY.history_markers)


def test_unknown_locale_raises_rather_than_falling_back():
    """Silently falling back to English is the failure mode that matters.

    The corpus would be scanned with the wrong patterns while the config says
    otherwise, and the config is the last place anyone would look.
    """
    with pytest.raises(L.UnknownLocale) as exc:
        L.resolve(("ko", "jp"))
    assert "jp" in str(exc.value)
    assert "Available" in str(exc.value)


def test_extra_history_markers_are_appended():
    got = L.resolve(("en",), extra_history_markers=("OBSOLETE",))
    assert "OBSOLETE" in got.history_markers
    assert "superseded" in got.history_markers


def test_extra_marker_actually_suppresses():
    loc = L.resolve(("en",), extra_history_markers=("OBSOLETE",))
    assert D.is_assertion("OBSOLETE pH 5.0", loc) is False
    assert D.is_assertion("OBSOLETE pH 5.0", EN_ONLY) is True


def test_default_keeps_korean_so_existing_callers_do_not_change():
    """Dropping Korean from the default would silently change every result.

    A project wanting English only says so; a project that says nothing keeps
    the behaviour the rule was measured with.
    """
    assert "ko" in L.DEFAULT.codes
    line = "이전에는 pH 5.0 이었다"
    assert D.is_assertion(line) is False        # no locale argument at all

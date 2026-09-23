"""Case is the whole distinction for one ladder, and noise for every other.

Measured 260924: `48 mM` and `48 mm` compared equal, so rule (4) returned exit
0 on a document that had turned a concentration into a length. That is the
exact class of error the unit axis exists to catch, passing the check meant to
catch it.

`M` is molar and `m` is metre. The SI prefixes carry that difference down the
whole ladder, and `normalise_unit` lower-cased the token before comparing, so
the difference was gone at the first step.

The fix is enumerated rather than general, and that matters in both
directions. Folding case is *right* for nearly every unit a document writes --
`Hr`, `HR` and `hr` are one unit, and a blanket case-sensitive comparison
would report those as mismatches, which is the opposite failure. So the molar
ladder is listed by hand and everything else keeps folding.

The second half of this file covers a different gap, found by the same
measurement: prose writes `grams` and `metre` where code writes `g` and `m`,
and rule (4) compares exactly that pair. Of 19 unit families drawn from real
bioprocess documents, 10 did not fold to one form, and nearly every gap was a
plural or a written-out name.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fiducial import quantities as Q

REPO = Path(__file__).resolve().parents[1]

_DECL = "---\nssot:\n  source: SSOT.md\n  repeats:\n    phosphate: 48\n---\n"


def _run(tmp_path: Path, upstream: str, document: str):
    (tmp_path / "SSOT.md").write_text(upstream, encoding="utf-8")
    (tmp_path / "DER.md").write_text(_DECL + document, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "fiducial", "docs", "--root", str(tmp_path),
         str(tmp_path / "DER.md")],
        capture_output=True, text=True, cwd=str(REPO),
    )


# --- the defect ------------------------------------------------------------


def test_millimolar_is_not_millimetre(tmp_path: Path) -> None:
    """The measured case: a concentration and a length, reported as agreeing."""
    r = _run(tmp_path, "| phosphate | 48 mM |\n", "phosphate 48 mm.\n")
    assert "unit mismatch" in r.stdout
    assert r.returncode == 1


def test_the_whole_molar_ladder_stays_separate() -> None:
    for conc, length in (("M", "m"), ("mM", "mm"), ("nM", "nm"), ("µM", "µm")):
        assert Q.normalise_unit(conc) != Q.normalise_unit(length), (conc, length)


def test_the_same_concentration_unit_still_agrees(tmp_path: Path) -> None:
    """Separating the ladder must not make a unit disagree with itself."""
    r = _run(tmp_path, "| phosphate | 48 mM |\n", "phosphate 48 mM.\n")
    assert "unit mismatch" not in r.stdout


# --- and the folding it must not break -------------------------------------


def test_case_still_folds_everywhere_else(tmp_path: Path) -> None:
    """`Hr` and `hr` are one unit; reporting them would be the other failure."""
    for a, b in (("Hr", "hr"), ("HOURS", "hours"), ("DegC", "degc"), ("L", "l")):
        assert Q.normalise_unit(a) == Q.normalise_unit(b), (a, b)

    r = _run(tmp_path, "| phosphate | 48 Hr |\n", "phosphate 48 hr.\n")
    assert "unit mismatch" not in r.stdout


# --- prose spellings against code symbols ----------------------------------


def test_prose_spellings_fold_to_the_symbol() -> None:
    """A document writes `grams`; code writes `g`. That pair is the comparison.

    Each family here failed to fold before 260924. They are grouped as
    families rather than asserted pairwise so that adding a spelling to one
    does not need a new test.
    """
    families = [
        ["g", "gram", "grams", "gramme"],
        ["kg", "kilogram", "kilograms"],
        ["mol", "mole", "moles"],
        ["l", "litre", "liter", "litres", "liters"],
        ["m", "metre", "meter", "metres", "meters"],
        ["mm", "millimetre", "millimeter"],
        ["pa", "pascal", "pascals"],
        ["bar", "bars"],
        ["u", "unit", "units"],
    ]
    for spellings in families:
        forms = {Q.normalise_unit(s) for s in spellings}
        assert len(forms) == 1, (spellings, sorted(x for x in forms if x))


def test_the_spelled_out_molar_forms_do_not_land_on_metre() -> None:
    """`molar` used to fold to `m`, which is where the collision started.

    The symbols are resolved before lower-casing; the spelled-out names fold
    to the spelled-out form for the same reason, rather than back onto a
    symbol that means something else.
    """
    assert Q.normalise_unit("molar") == Q.normalise_unit("M")
    assert Q.normalise_unit("millimolar") == Q.normalise_unit("mM")
    assert Q.normalise_unit("micromolar") == Q.normalise_unit("µM")
    assert Q.normalise_unit("molar") != Q.normalise_unit("m")

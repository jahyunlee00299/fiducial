"""Rule (4), unit axis: the same number written in a different unit.

Found 260923, parked unused, wired 260924. Before this, rule (4) compared two
readings of one quantity as `float` against `float`, so two documents could
agree perfectly while meaning different things::

    SSOT.md      | reaction time | 48 h |
    DERIVED.md     reaction time 48 min.

    $ fiducial docs --root .        # exit 0, 0 violations

A factor of sixty, reported as agreement. Changing 48 to 36 was caught;
changing `h` to `min` was not, because the unit was matched by the value
pattern and thrown away.

The check is only reachable when the NUMBERS already agree, which is what
makes it worth having: it is the one finding that survives every other check
passing. That is also why it is reported apart from a value mismatch rather
than folded in -- the two are found under opposite conditions and need
different repairs.

Deliberately narrow, and the tests below pin the narrowness as hard as the
detection. Nothing here decides which unit is *correct* and nothing converts
between them. It compares what the upstream wrote against what this document
wrote -- the same declared-versus-written comparison the rule already makes
for the number. Where either side writes no unit, there is nothing to compare
and silence is not a finding.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_DECL = (
    "---\nssot:\n  source: SSOT.md\n  repeats:\n    reaction time: 48\n---\n"
)


def _run(tmp_path: Path, upstream: str, document: str) -> subprocess.CompletedProcess:
    (tmp_path / "SSOT.md").write_text(upstream, encoding="utf-8")
    (tmp_path / "DER.md").write_text(_DECL + document, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "fiducial", "docs", "--root", str(tmp_path),
         str(tmp_path / "DER.md")],
        capture_output=True, text=True, cwd=str(REPO),
    )


def _caught(r: subprocess.CompletedProcess) -> bool:
    return "unit mismatch" in r.stdout


# --- the defect this was written for ---------------------------------------


def test_the_same_number_in_a_different_unit_is_caught(tmp_path: Path) -> None:
    """48 h against 48 min: agreement on every axis the rule checked before."""
    r = _run(tmp_path, "| reaction time | 48 h |\n", "reaction time 48 min.\n")
    assert _caught(r)
    assert r.returncode == 1, "a 60x error must not exit 0"
    assert "'h'" in r.stdout and "'min'" in r.stdout, "both units named"


def test_the_count_line_mentions_it(tmp_path: Path) -> None:
    """A reader who sees '0 violations' above a printed error trusts the count."""
    r = _run(tmp_path, "| reaction time | 48 h |\n", "reaction time 48 min.\n")
    assert "unit mismatch(es)" in r.stdout


# --- and the false positives it must not produce ---------------------------


def test_a_spelling_difference_is_not_a_mismatch(tmp_path: Path) -> None:
    """`hr` and `h` are one unit. Folding them is the point of normalisation."""
    r = _run(tmp_path, "| reaction time | 48 hr |\n", "reaction time 48 h.\n")
    assert not _caught(r)


def test_a_korean_unit_folds_to_the_same_unit(tmp_path: Path) -> None:
    """`48시간` and `48 h` are the same quantity written in two languages."""
    r = _run(tmp_path, "| reaction time | 48 h |\n", "reaction time 48시간.\n")
    assert not _caught(r)


def test_a_bare_number_downstream_makes_no_claim(tmp_path: Path) -> None:
    """Silence is not a finding: the document stated no unit to disagree with."""
    r = _run(tmp_path, "| reaction time | 48 h |\n", "reaction time 48.\n")
    assert not _caught(r)


def test_a_bare_number_upstream_has_nothing_to_compare(tmp_path: Path) -> None:
    r = _run(tmp_path, "| reaction time | 48 |\n", "reaction time 48 h.\n")
    assert not _caught(r)


def test_a_value_mismatch_is_not_reported_as_a_unit_mismatch(tmp_path: Path) -> None:
    """The two are found under opposite conditions and must stay separate."""
    r = _run(tmp_path, "| reaction time | 48 h |\n", "reaction time 36 h.\n")
    assert not _caught(r)
    assert r.returncode == 1, "the value rule still fires"


# --- the parsing the detection rests on ------------------------------------


def test_the_parser_reads_unit_and_precision(tmp_path: Path) -> None:
    from fiducial import quantities as Q

    assert Q.split_quantity("48 h") == ("48", "h")
    assert Q.split_quantity("48 min") == ("48", "min")
    assert Q.split_quantity("74.09") == ("74.09", None)
    assert Q.normalise_unit("hr") == Q.normalise_unit("h")
    assert Q.normalise_unit("min") != Q.normalise_unit("h")
    assert Q.significant_figures("74.09") == 4
    assert Q.significant_figures("74.09268") == 7


def test_json_reports_it_with_no_fix(tmp_path: Path) -> None:
    """Certain, and not mechanically repairable.

    The tool knows the documents disagree about the unit, not which is right.
    Repairing means changing the number to suit the unit or the unit to suit
    the number -- different claims about the world, and guessing between them
    is the substitution this package refuses.
    """
    import json

    (tmp_path / "SSOT.md").write_text("| reaction time | 48 h |\n", encoding="utf-8")
    (tmp_path / "DER.md").write_text(_DECL + "reaction time 48 min.\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "fiducial", "docs", "--root", str(tmp_path),
         "--format", "json", str(tmp_path / "DER.md")],
        capture_output=True, text=True, cwd=str(REPO),
    )
    doc = json.loads(r.stdout)
    assert doc["summary"]["violations"] == 1
    assert doc["summary"]["auto_fixable"] == 0
    (finding,) = doc["findings"]
    assert finding["confidence"] == "certain"
    assert "fix" not in finding
    assert "which side is right" in finding["action"]

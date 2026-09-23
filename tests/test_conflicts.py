"""One key, two values: the defect rule (1) reports as two separate findings.

    k_ref.setdefault('k_17', 44.0)      # one file
    k_ref.setdefault('k_17', 0.1077)    # another

Two findings of rule (1) and one defect -- a factor of 400 between two places
that both claim to hold the same measured quantity. Nothing reported it,
because no rule looked ACROSS findings.

What the first version got wrong, measured
------------------------------------------
Grouping by key alone ran at **1 real finding in 20** on a 574-file public
corpus. An adversarial audit read every flagged site and refuted 19: the
corpus was 93% test fixtures (240 of 259 sites), and fixtures disagree with
each other by design -- `10x` monotonicity probes, `2x` scenario variants,
per-test dicts of arbitrary round numbers, one regression sample fanned across
every key. A ninth value under `titer` turned out to be eight unrelated
biorefineries sharing a generic name.

So the comparison is anchored: a conflict needs a value in non-test code, and
that is what the fixtures are compared against. 20 findings became 5, and the
one real case survived.

What it still cannot do, and the tests say so
---------------------------------------------
`test_the_remaining_ambiguity_is_real` pins the limit rather than papering
over it. On the same corpus `k_15`, `k_16` and `k_17` are identical on every
structural signal tried, and one of them is a stale copy while two are
deliberate probes. The difference is in what the test MEANS. Pushing the
filter further would have deleted the finding that mattered.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from fiducial import conflicts as C
from fiducial import literals as L

REPO = Path(__file__).resolve().parents[1]


def _scan(tmp_path: Path, files: dict[str, str], keys: list[str]) -> list:
    found = []
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        found.extend(L.scan_file(p, keys))
    return C.find(found)


# --- the defect it exists for ---------------------------------------------


def test_a_stale_copy_in_a_fixture_is_reported(tmp_path: Path) -> None:
    """The measured shape: code corrected, a test never followed."""
    (found,) = _scan(
        tmp_path,
        {
            "model.py": "k_17 = 0.1077\n",
            "test_model.py": "REF = {'k_17': 44.0}\n",
        },
        ["k_17"],
    )
    assert found.key == "k_17"
    assert set(found.values) == {0.1077, 44.0}
    assert round(found.spread) == 409


def test_the_spread_separates_a_rounding_from_a_transcription(tmp_path: Path) -> None:
    """Magnitude is what tells a rounded copy from a 400x slip.

    Both are findings. Only one of them is obviously not a rounding choice,
    and a reader triaging a list needs that ordering.
    """
    small = _scan(
        tmp_path / "a",
        {"m.py": "titer = 2.003\n", "n.py": "titer = 1.208\n"},
        ["titer"],
    )
    big = _scan(
        tmp_path / "b",
        {"m.py": "k = 0.1077\n", "n.py": "k = 44.0\n"},
        ["k"],
    )
    assert small[0].spread < 2
    assert big[0].spread > 100


# --- and the noise it must not report --------------------------------------


def test_fixtures_disagreeing_with_each_other_are_not_a_conflict(
    tmp_path: Path,
) -> None:
    """Two test files, two values, nothing in the code. That is what tests do.

    This single rule removed most of the 19 refuted findings: a `10x`
    monotonicity probe and the value it probes are both fixtures, and neither
    is a claim about the measured quantity.
    """
    assert (
        _scan(
            tmp_path,
            {
                "test_a.py": "REF = {'k_4': 4.8}\n",
                "test_b.py": "PROBE = {'k_4': 48.0}\n",
            },
            ["k_4"],
        )
        == []
    )


def test_one_value_repeated_is_not_a_conflict(tmp_path: Path) -> None:
    """Duplication is rule (1)'s finding, one site at a time. Not this one's."""
    assert (
        _scan(
            tmp_path,
            {"a.py": "eta = 0.87\n", "b.py": "eta = 0.87\n", "c.py": "eta = 0.87\n"},
            ["eta"],
        )
        == []
    )


def test_the_same_name_in_two_packages_is_two_quantities(tmp_path: Path) -> None:
    """`titer` in two biorefineries is not one quantity with two values.

    Measured: that collision alone put nine values under a single key.
    """
    assert (
        _scan(
            tmp_path,
            {
                "biorefineries/cane/s.py": "titer = 117.0\n",
                "biorefineries/microalgae/s.py": "titer = 2.003\n",
            },
            ["titer"],
        )
        == []
    )


def test_a_value_only_in_tests_is_not_compared(tmp_path: Path) -> None:
    """With nothing in the code, there is no value for a fixture to contradict."""
    assert (
        _scan(tmp_path, {"test_x.py": "a = {'k': 1.0}\nb = {'k': 9.0}\n"}, ["k"]) == []
    )


# --- the limit, stated rather than hidden ----------------------------------


def test_the_remaining_ambiguity_is_real(tmp_path: Path) -> None:
    """A deliberate probe and a stale copy look identical here.

    Both are one code value against fixtures that differ from it. The tool
    reports both and says `needs_review`; claiming to tell them apart would
    mean deleting the real one, which is what the measured 1-in-20 version
    did in the other direction.
    """
    stale = _scan(
        tmp_path / "a",
        {"m.py": "k = 0.1077\n", "test_m.py": "REF = {'k': 44.0}\n"},
        ["k"],
    )
    probe = _scan(
        tmp_path / "b",
        {"m.py": "k = 4.8\n", "test_m.py": "TENX = {'k': 48.0}\n"},
        ["k"],
    )
    assert len(stale) == len(probe) == 1
    assert stale[0].sites[0].is_test == probe[0].sites[0].is_test


# --- the wire format -------------------------------------------------------


def test_the_signal_is_never_auto_fixable(tmp_path: Path) -> None:
    """Stronger than the other rules: it cannot know it is even a defect.

    Proposing an edit would ask an agent to overwrite a test doing its job.
    """
    from fiducial import signals as S

    found = _scan(
        tmp_path,
        {"m.py": "k = 0.1077\n", "test_m.py": "R = {'k': 44.0}\n"},
        ["k"],
    )
    (sig,) = S.from_conflicts(found)
    assert sig.confidence == "needs_review"
    assert sig.fix is None
    assert "Read the sites before changing anything" in sig.action


def test_the_cli_reaches_it(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("k_17 = 0.1077\n", encoding="utf-8")
    (tmp_path / "test_m.py").write_text("R = {'k_17': 44.0}\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "fiducial", "literals", "--keys", "k_17",
         "--conflicts", "--format", "json", str(tmp_path)],
        capture_output=True, text=True, cwd=str(REPO),
    )
    doc = json.loads(r.stdout)
    assert r.returncode == 1
    assert doc["summary"]["auto_fixable"] == 0
    assert doc["findings"][0]["rule"] == "conflicts"

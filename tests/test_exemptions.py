"""Which small numbers rule (1) stays quiet about, and what that costs.

`_UNREMARKABLE = {0, 1, -1, 2, 100}` was written so that `x = 0` or a `+1`
index would not be reported as an unsourced measurement -- a checker that does
that earns a permanent place in an ignore list.

It sat at the wrong layer for a year. Rule (1) only ever looks at keys a
project has DECLARED measured, so the counter case cannot reach it: `i = 1` is
not a declared parameter. What the exemption actually reached, measured on a reference
repository against commits its authors later made:

    t_max = 1              a fit window in hours, corrected to 0.5
    "alpha_nh3": 2.0       a key that project's spec declares learnable

Across 97 declared keys it suppressed **2 sites out of 170** -- almost no
quiet bought, two of five answer cases lost.

So it now applies where the key was matched by a PATTERN, not where it was
named. A caller writing `--keys 'k_*'` is casting a net and does not want
every `k_n = 2` loop bound; a caller naming `alpha_nh3` means that parameter,
whatever its value.

Zero and one are the exception to the exception, and it is a deliberate loss
-- see `test_zero_and_one_stay_exempt_even_when_named`.
"""

from __future__ import annotations

from pathlib import Path

from fiducial.literals import scan_source


def _keys(src: str, keys: list[str]) -> set[str]:
    return {f.key for f in scan_source(Path("m.py"), src, keys)}


def test_an_exactly_named_key_is_not_exempted_from_small_numbers() -> None:
    """`alpha_nh3: 2.0` is that parameter's value, not a counter."""
    got = _keys("{'alpha_nh3': 2.0}\nrate = 100\n", ["alpha_nh3", "rate"])
    assert "alpha_nh3" in got, got
    assert "rate" in got, got


def test_a_pattern_match_keeps_the_exemption() -> None:
    """A net picks up counters, and the caller who cast it knows that.

    This is the case the exemption was written for, and the only one where it
    can still fire: an exact name is a statement about one parameter, a glob
    is a statement about a family.
    """
    got = _keys("k_index = 2\nk_rate = 0.876\n", ["k_*"])
    assert "k_index" not in got, got
    assert "k_rate" in got, got


def test_zero_and_one_stay_exempt_even_when_named() -> None:
    """A deliberate loss, and the measurement that decided it.

    Unblocking 0 and 1 for exactly-named keys recovered one answer case
    (`t_max = 1`) and brought 96 findings with it -- `tris_mM = 0.0`,
    `xr_activity_scale = 1.0`, terms switched off and scales left unchanged.
    That is a baseline being composed, not a measurement being invented.

    The two cannot be separated by value, because `1 == 1.0`. The only proxy
    available is `1` written as an int against `1.0` as a float, and that
    rests on a formatting habit which breaks the moment somebody writes
    `t_max = 1.0`. Recall of 4 in 5 with a reason beats 5 in 5 bought with a
    rule that holds by accident.
    """
    got = _keys(
        "xr_activity_scale = 1.0\ntris_mM = 0.0\n",
        ["xr_activity_scale", "tris_mM"],
    )
    assert got == set(), got


def test_the_exemption_never_hides_an_ordinary_value() -> None:
    """Everything outside the set is reported however the key was matched."""
    src = "k_rate = 0.876\nother = 3.5\n"
    assert _keys(src, ["k_*"]) == {"k_rate"}
    assert _keys(src, ["other"]) == {"other"}

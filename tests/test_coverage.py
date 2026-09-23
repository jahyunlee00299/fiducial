"""rule (3) tests — declared parameters with no gate asserting anything.

Run: python tests/test_coverage.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json  # noqa: E402

from fiducial.coverage import (  # noqa: E402
    Coverage,
    analyse,
    load_declared_keys,
)

FAILURES = []


def check(label, cond, detail=""):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def levels(keys, sources):
    """Classify `keys` against in-memory test sources."""
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for i, src in enumerate(sources):
            p = Path(d) / f"test_{i}.py"
            p.write_text(src, encoding="utf-8")
            paths.append(p)
        return {r.key: r.level for r in analyse(keys, paths)}


def test_three_levels():
    got = levels(
        ["asserted_key", "mentioned_key", "absent_key"],
        [
            "def test_a():\n"
            "    assert params['asserted_key'] == 0.5\n"
            "    cfg = {'mentioned_key': 1.0}\n"
            "    return cfg\n"
        ],
    )
    check("asserted -> ASSERTED", got["asserted_key"] is Coverage.ASSERTED, got)
    check("mentioned only -> MENTIONED", got["mentioned_key"] is Coverage.MENTIONED, got)
    check("nowhere -> ABSENT", got["absent_key"] is Coverage.ABSENT, got)


def test_multiline_assert_is_found():
    """A line-based search misses this; it is the usual shape once a message
    is attached, so missing it would under-report real gates."""
    got = levels(
        ["kla_scale"],
        [
            "def test_a():\n"
            "    assert (\n"
            "        params['kla_scale']\n"
            "        == 0.5074\n"
            "    ), 'must match the canonical fit'\n"
        ],
    )
    check("multi-line assert counts", got["kla_scale"] is Coverage.ASSERTED, got)


def test_substring_does_not_count():
    """`k_mtf` must NOT be credited by `k_mtf_sub`.

    Measured: a line-based search credited three keys on exactly this basis.
    """
    got = levels(
        ["k_mtf"],
        ["def test_a():\n    assert smtf(0.0, 0.0, 0.005) == 1.0, 'k_mtf_sub identity'\n"
         "    k_mtf_sub = 0.3\n    return k_mtf_sub\n"],
    )
    check("substring in another name does not count",
          got["k_mtf"] is not Coverage.ASSERTED, got)


def test_key_only_in_assert_message_does_not_count():
    """The message is not part of the claim."""
    got = levels(
        ["qo2_basal"],
        ["def test_a():\n    assert 1 == 1, 'qo2_basal should be positive'\n"],
    )
    check("assert message alone does not count",
          got["qo2_basal"] is not Coverage.ASSERTED, got)


def test_key_inside_a_string_constant_in_the_test_expr():
    """`params['x']` is a real claim about x; the key is a whole-token constant."""
    got = levels(["eta"], ["def test_a():\n    assert params['eta'] > 0\n"])
    check("subscript key counts", got["eta"] is Coverage.ASSERTED, got)


def test_unparseable_test_file_does_not_crash():
    got = levels(["eta"], ["def (\n", "def test_a():\n    assert params['eta'] > 0\n"])
    check("broken test file skipped, good one still counts",
          got["eta"] is Coverage.ASSERTED, got)


def test_refuse_empty_inputs():
    """REFUTE: both vacuous cases must raise, not report success."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "test_a.py"
        p.write_text("assert True\n", encoding="utf-8")
        try:
            analyse([], [p])
        except ValueError:
            check("empty key list refused", True)
        else:
            check("empty key list refused", False, "returned instead of raising")

        try:
            analyse(["eta"], [])
        except ValueError:
            check("empty test list refused", True)
        else:
            check("empty test list refused", False, "returned instead of raising")


def test_load_declared_keys():
    with tempfile.TemporaryDirectory() as d:
        spec = Path(d) / "spec.yaml"
        spec.write_text(
            "version: 1\n"
            "learnable_keys:\n"
            "  # a comment\n"
            "  - eta\n"
            "  - kla_scale\n"
            "optional_keys:\n"
            "  - legacy\n",
            encoding="utf-8",
        )
        keys = load_declared_keys(spec)
        check("reads the right field", keys == ["eta", "kla_scale"], keys)
        other = load_declared_keys(spec, "optional_keys")
        check("reads an alternate field", other == ["legacy"], other)

        empty = Path(d) / "empty.yaml"
        empty.write_text("learnable_keys:\nother: 1\n", encoding="utf-8")
        try:
            load_declared_keys(empty)
        except ValueError:
            check("empty field refused", True)
        else:
            check("empty field refused", False, "a vacuous spec must raise")


def test_refute_mutation():
    """REFUTE: adding a real assertion must move the key out of the gap set."""
    before = levels(["eta"], ["cfg = {'eta': 1.0}\n"])
    after = levels(["eta"], ["def test_a():\n    assert params['eta'] == 0.87\n"])
    check("refute: gap before", before["eta"] is Coverage.MENTIONED, before)
    check("refute: closed after", after["eta"] is Coverage.ASSERTED, after)


def test_pinned_in_a_data_baseline_is_not_a_gap():
    """A key frozen in a golden JSON IS gated -- the test iterates it at runtime.

    Measured: 8 of 28 keys this rule first called "mentioned-only" were pinned in
    tests/golden/golden_baseline.json and compared by test_scalars_exact. Calling
    those gaps would send someone to write a second gate for a parameter that
    already had one.
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        t = root / "test_golden.py"
        t.write_text(
            "def test_scalars(golden, current):\n"
            "    for key, expected in golden['scalars'].items():\n"
            "        assert current[key] == expected\n",
            encoding="utf-8",
        )
        data = root / "golden.json"
        data.write_text(
            json.dumps({"scalars": {"cell_activity_decay": 5.25e-06}}), encoding="utf-8"
        )
        got = {r.key: r for r in analyse(["cell_activity_decay"], [t], [data])}
        r = got["cell_activity_decay"]
        check("pinned in data -> PINNED", r.level is Coverage.PINNED, r.level)
        check("pinned is not a gap", not r.is_gap)
        check("pinned names the file", "golden.json" in r.explain(), r.explain())

        # Without the data file it is a gap again -- the pin is doing the work.
        got2 = {r.key: r for r in analyse(["cell_activity_decay"], [t])}
        check("without --data it reports a gap", got2["cell_activity_decay"].is_gap)


def test_unreadable_data_file_does_not_crash():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        t = root / "test_a.py"
        t.write_text("def test_a():\n    assert 1 == 1\n", encoding="utf-8")
        bad = root / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        got = {r.key: r.level for r in analyse(["eta"], [t], [bad])}
        check("malformed json skipped", got["eta"] is Coverage.ABSENT, got)


def test_module_constant_members_count():
    """A test that collects keys into a constant and asserts over it IS a gate.

    Measured: 11 keys were false gaps because the project writes
        ENZYME_A_FITTED_KEYS = ("kcat_enzyme_a", "km_a_enzyme_a", ...)
        assert not {k for k in ENZYME_A_FITTED_KEYS if ...}
    so the names live in the constant, never in the assert.
    """
    src = (
        "KEYS = ('km_b_enzyme_a', 'ki_a_enzyme_a')\n"
        "def test_a(params, override):\n"
        "    bad = {k for k in KEYS if params[k] != override[k]}\n"
        "    assert not bad\n"
    )
    got = levels(["km_b_enzyme_a", "ki_a_enzyme_a"], [src])
    check("constant in a comprehension inside assert",
          all(v is Coverage.ASSERTED for v in got.values()), got)

    loop = (
        "PRIORS = {'km_p_enzyme_a': 50.0}\n"
        "def test_b(catalog):\n"
        "    for key, expected in PRIORS.items():\n"
        "        assert catalog[key] == expected\n"
    )
    got2 = levels(["km_p_enzyme_a"], [loop])
    check("constant in a for-loop with assert", got2["km_p_enzyme_a"] is Coverage.ASSERTED, got2)

    inert = "KEYS = ('km_b_enzyme_a',)\ndef test_c():\n    return KEYS\n"
    got3 = levels(["km_b_enzyme_a"], [inert])
    check("unused constant is not a gate", got3["km_b_enzyme_a"] is not Coverage.ASSERTED, got3)


def test_waiver_requires_a_reason():
    """A waiver is allowed, but it must say why -- and it lives in the spec."""
    from fiducial.coverage import load_waivers
    with tempfile.TemporaryDirectory() as d:
        good = Path(d) / "good.yaml"
        good.write_text(
            "learnable_keys:\n  - a\n"
            "coverage_waivers:\n"
            '  kd_e_enzyme_a: "not an __init__ kwarg; merged upstream"\n'
            "next_field: 1\n",
            encoding="utf-8",
        )
        w = load_waivers(good)
        check("waiver with reason loads",
              w == {"kd_e_enzyme_a": "not an __init__ kwarg; merged upstream"}, w)

        bare = Path(d) / "bare.yaml"
        bare.write_text("coverage_waivers:\n  kd_e_enzyme_a:\n", encoding="utf-8")
        try:
            load_waivers(bare)
        except ValueError:
            check("bare waiver refused", True)
        else:
            check("bare waiver refused", False, "a reasonless waiver must raise")

        none = Path(d) / "none.yaml"
        none.write_text("learnable_keys:\n  - a\n", encoding="utf-8")
        check("no waiver field is fine", load_waivers(none) == {})


def test_an_assert_can_be_blind_to_the_parameter_it_names():
    """A key inside an assert is NOT evidence the assert can fail on it.

    Measured in the reference corpus: `test_mtf_sub_preserves_keq` sets
    km_p_enzyme_a / km_q_enzyme_a / ki_p_enzyme_a via setattr, then asserts
    `rate == 0` at a manufactured equilibrium. But the rate numerator is structurally zero there
    and those three appear only in the DENOMINATOR, so the assertion holds for
    any value they take. A gate that cannot fail, wearing the shape of one.

    This test pins the CLAIM, not a behaviour: whatever level such a key gets,
    the tool must not be read as having verified it. Deciding sensitivity is
    mutation testing's job -- it runs the suite; this rule does not.
    """
    src = (
        "def test_equilibrium(rate_fn):\n"
        "    enzyme_a.km_p_enzyme_a = 50.0\n"
        "    out = rate_fn(A, B, P=keq*A*B/Q, Q=Q)\n"
        "    assert abs(out[0]) < 1e-12\n"
    )
    got = levels(["km_p_enzyme_a"], [src])
    # Today the key is only MENTIONED (it is not named inside the assert).
    # If a future pattern promotes it, that is the DANGEROUS direction, so the
    # docstring above -- not this assertion -- is what carries the warning.
    check("blind-assert key is not silently certified",
          got["km_p_enzyme_a"] in (Coverage.MENTIONED, Coverage.ABSENT), got)


if __name__ == "__main__":
    for fn in [
        test_three_levels, test_multiline_assert_is_found,
        test_substring_does_not_count, test_key_only_in_assert_message_does_not_count,
        test_key_inside_a_string_constant_in_the_test_expr,
        test_unparseable_test_file_does_not_crash, test_refuse_empty_inputs,
        test_load_declared_keys, test_refute_mutation,
        test_pinned_in_a_data_baseline_is_not_a_gap,
        test_unreadable_data_file_does_not_crash,
        test_module_constant_members_count,
        test_waiver_requires_a_reason,
        test_an_assert_can_be_blind_to_the_parameter_it_names,
    ]:
        print(f"\n{fn.__name__}")
        fn()
    print("\n" + ("FAILED: " + ", ".join(FAILURES) if FAILURES else "all passed"))
    raise SystemExit(1 if FAILURES else 0)

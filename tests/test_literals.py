"""rule (1) tests — declared measured keys, hard-coded or silently defaulted.

Run: python tests/test_literals.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fiducial.literals import scan_source  # noqa: E402

FAILURES = []
KEYS = ["eta", "kla_scale", "xr_activity_scale"]


def check(label, cond, detail=""):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def scan(src, keys=KEYS):
    return scan_source(Path("m.py"), src, keys)


def test_silent_fallback_shapes():
    """A non-neutral default is a fabricated measurement in every fetch shape."""
    for src, label in [
        ("x = params.get('eta', 0.87)\n", ".get"),
        ("x = params.pop('eta', 0.87)\n", ".pop"),
        ("x = params.setdefault('eta', 0.87)\n", ".setdefault"),
        ("x = cfg.get('kla_scale', 2.7)\n", "other receiver"),
        ("x = params.get('eta', -0.5)\n", "negative default"),
    ]:
        f = scan(src)
        check(f"fallback caught: {label}", len(f) == 1 and f[0].kind == "silent_fallback",
              f"got {[(x.kind, x.key) for x in f]}")


def test_neutral_defaults_split_out():
    """0.0/1.0 mean "term off"/"neutral scale", not a fabricated measurement.

    Measured on the reference codebase: 575 of 705 silent-fallback hits (82%)
    defaulted to exactly these two values -- `setdefault("vmax_futile_nadph",
    0.0)`, `setdefault("xr_activity_scale", 1.0)`. Reporting them by default
    buried the 130 that mattered, so they are opt-in rather than dropped.
    """
    for src in ["x = params.get('eta', 0.0)\n", "x = params.get('eta', 1.0)\n"]:
        check(f"neutral hidden by default: {src.strip()}", scan(src) == [])
        f = scan_source(Path("m.py"), src, KEYS, include_neutral=True)
        check(f"neutral surfaces on request: {src.strip()}",
              len(f) == 1 and f[0].neutral, f"got {f}")

    f = scan_source(Path("m.py"), "x = params.get('eta', 0.87)\n", KEYS,
                    include_neutral=True)
    check("non-neutral is not marked neutral", len(f) == 1 and not f[0].neutral)


def test_fallback_without_default_is_clean():
    """`params.get("eta")` returns None and the caller must cope -- that is loud."""
    check("one-arg .get is clean", scan("x = params.get('eta')\n") == [])


def test_undeclared_key_is_clean():
    check("undeclared key ignored", scan("x = params.get('timeout', 30)\n") == [])


def test_bare_literal():
    f = scan("eta = 0.87\n")
    check("bare literal caught", len(f) == 1 and f[0].kind == "bare_literal",
          f"got {[(x.kind, x.key) for x in f]}")
    f = scan("self.kla_scale = 2.7\n")
    check("attribute assignment caught", len(f) == 1 and f[0].key == "kla_scale")


def test_annotated_assignment():
    """AnnAssign must be walked.

    Measured on the reference implementation: omitting this node type made an
    audit report "0 items" where 56 existed.
    """
    f = scan("eta: float = 0.87\n")
    check("annotated assignment caught", len(f) == 1 and f[0].kind == "bare_literal",
          f"got {[(x.kind, x.key) for x in f]}")


def test_unremarkable_numbers_exempt():
    for src in ["eta = 0\n", "eta = 1\n", "eta = -1\n", "eta = 2\n", "eta = 100\n"]:
        check(f"exempt: {src.strip()}", scan(src) == [])


def test_booleans_are_not_numbers():
    check("True is not a measurement", scan("eta = True\n") == [])


def test_non_literal_is_clean():
    for src in [
        "eta = compute_eta(data)\n",
        "eta = params['eta']\n",
        "eta = other.eta\n",
    ]:
        check(f"clean: {src.strip()}", scan(src) == [])


def test_line_numbers_are_real():
    f = scan("import os\n\n\neta = 0.87\n")
    check("line number reported", len(f) == 1 and f[0].line == 4,
          f"got line {f[0].line if f else None}")
    check("snippet captured", bool(f) and "0.87" in f[0].snippet)


def test_empty_keys_refuses():
    """REFUTE: with no declared keys every check passes vacuously, so refuse."""
    try:
        scan_source(Path("m.py"), "eta = 0.87\n", [])
    except ValueError:
        check("empty key list refused", True)
    else:
        check("empty key list refused", False, "returned instead of raising")


def test_refute_mutation_breaks_the_rule():
    """REFUTE: fixing the source must silence the finding.

    If the checker reports a violation whether or not the defect is present, it
    is not reading the code.
    """
    bad = "eta = params.get('eta', 0.87)\n"
    good = "eta = params['eta']\n"
    check("refute: defect fires", len(scan(bad)) == 1)
    check("refute: fixed source is silent", scan(good) == [],
          "fires on correct code -- not actually comparing")


def test_multiple_findings_all_surface():
    src = "eta = 0.87\nkla_scale = params.get('kla_scale', 2.7)\n"
    f = scan(src)
    check("both findings surface", len(f) == 2, f"got {len(f)}")
    check("sorted by line", [x.line for x in f] == [1, 2])



def test_arithmetic_on_two_literals_is_still_a_literal():
    """`P=6 * 101325` is six atmospheres written the way engineers write it.

    Found by a recall measurement rather than by review: a public pressure fix
    (`P=6 * 101325` -> `P=2.1 * 101325`, Bioindustrial-Park 6ee1389052) was
    invisible because the value is a `BinOp`, not a `Constant`. Writing a
    measured quantity times its unit is ordinary in scientific code, so
    reading only `Constant` misses that whole shape.
    """
    src = "f(P=6 * 101325)\ng(P=30 + 273.15)\nh(P=2 ** 3)\n"
    got = {
        f.line: f.value
        for f in scan_source(Path("m.py"), src, ["P"], call_keywords=True)
    }
    check("6 * 101325 folds", got.get(1) == 607950.0, got)
    check("30 + 273.15 folds", got.get(2) == 303.15, got)
    check("2 ** 3 folds", got.get(3) == 8, got)


def test_folding_stops_at_a_name():
    """`6 * scale` is not a literal -- it has a provenance, which is the point.

    Folding deeper would turn "this number came from somewhere" into "this
    number is six times something", and the rule exists to find the first.
    """
    src = "f(P=6 * scale)\ng(P=BASE + 1)\n"
    found = scan_source(Path("n.py"), src, ["P"], call_keywords=True)
    check("no finding for a name-dependent value", found == [], found)


if __name__ == "__main__":
    for fn in [
        test_silent_fallback_shapes, test_neutral_defaults_split_out,
        test_fallback_without_default_is_clean,
        test_undeclared_key_is_clean, test_bare_literal, test_annotated_assignment,
        test_unremarkable_numbers_exempt, test_booleans_are_not_numbers,
        test_non_literal_is_clean, test_line_numbers_are_real,
        test_empty_keys_refuses, test_refute_mutation_breaks_the_rule,
        test_multiple_findings_all_surface,
        test_arithmetic_on_two_literals_is_still_a_literal,
        test_folding_stops_at_a_name,
    ]:
        print(f"\n{fn.__name__}")
        fn()
    print("\n" + ("FAILED: " + ", ".join(FAILURES) if FAILURES else "all passed"))
    raise SystemExit(1 if FAILURES else 0)

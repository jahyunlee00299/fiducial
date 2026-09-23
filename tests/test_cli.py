"""CLI tests — exit codes, and the refusal to report a blind scan as clean.

Run: python tests/test_cli.py
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fiducial.cli import main, EXIT_OK, EXIT_VIOLATIONS, EXIT_CANNOT_CHECK  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def test_literals_exit_codes():
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "bad.py"
        bad.write_text("eta = params.get('eta', 0.87)\n", encoding="utf-8")
        good = Path(d) / "good.py"
        good.write_text("eta = params['eta']\n", encoding="utf-8")

        code, out, _ = run(["literals", "--keys", "eta", str(bad)])
        check("violation -> exit 1", code == EXIT_VIOLATIONS, f"got {code}")
        check("violation explained", "silent_fallback" in out)

        code, _, _ = run(["literals", "--keys", "eta", str(good)])
        check("clean -> exit 0", code == EXIT_OK, f"got {code}")


def test_empty_key_list_is_error_not_pass():
    """A vacuous check must not read as clean."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "m.py"
        f.write_text("eta = 0.87\n", encoding="utf-8")
        code, _, err = run(["literals", "--keys", "", str(f)])
        check("empty --keys -> exit 2", code == EXIT_CANNOT_CHECK, f"got {code}")
        check("empty --keys explained", "vacuously" in err)


def test_zero_files_is_error_not_pass():
    """The failure this package was built after: 0 files scanned, exit 0, believed."""
    with tempfile.TemporaryDirectory() as d:
        missing = str(Path(d) / "nothing_here" / "*.py")
        code, _, err = run(["literals", "--keys", "eta", missing])
        check("0 files -> exit 2", code == EXIT_CANNOT_CHECK, f"got {code}")
        check("0 files explained", "0 python files" in err)

        code, _, err = run(["names", str(Path(d) / "none" / "*.yaml")])
        check("names 0 files -> exit 2", code == EXIT_CANNOT_CHECK, f"got {code}")


def test_names_exit_codes_and_modes():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "a_v15b.yaml").write_text("run_id: a_v16\n", encoding="utf-8")
        (root / "b_v8_v3.yaml").write_text("fit_json: r_v8_v4.json\n", encoding="utf-8")
        (root / "c_v8.yaml").write_text("run_id: c_v8\n", encoding="utf-8")

        code, out, _ = run(["names", "--mode", "strict", str(root)])
        check("strict finds the no-overlap liar", code == EXIT_VIOLATIONS)
        check("strict skips partial overlap", "b_v8_v3" not in out, out[:200])

        code, out, _ = run(["names", "--mode", "set", str(root)])
        check("set finds both", code == EXIT_VIOLATIONS and "b_v8_v3" in out)
        check("set leaves honest file alone", "c_v8.yaml:" not in out)

        only = root / "c_v8.yaml"
        code, _, _ = run(["names", str(only)])
        check("honest file alone -> exit 0", code == EXIT_OK)


def test_unparseable_source_is_error():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "broken.py"
        f.write_text("def (\n", encoding="utf-8")
        code, _, err = run(["literals", "--keys", "eta", str(f)])
        check("syntax error -> exit 2", code == EXIT_CANNOT_CHECK, f"got {code}")
        check("syntax error explained", "cannot parse" in err)


if __name__ == "__main__":
    for fn in [
        test_literals_exit_codes, test_empty_key_list_is_error_not_pass,
        test_zero_files_is_error_not_pass, test_names_exit_codes_and_modes,
        test_unparseable_source_is_error,
    ]:
        print(f"\n{fn.__name__}")
        fn()
    print("\n" + ("FAILED: " + ", ".join(FAILURES) if FAILURES else "all passed"))
    raise SystemExit(1 if FAILURES else 0)

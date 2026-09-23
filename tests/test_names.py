"""rule (2) tests, including the three exclusions that measurement forced.

Run: python tests/test_names.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fiducial.names import inspect_text, version_tokens, scan  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def test_version_tokens():
    check("plain token", version_tokens("optimizer_run_v15b_flask") == {"v15b"})
    check("two tokens", version_tokens("qnehvi_v8_v3_soft") == {"v8", "v3"})
    check("case folded", version_tokens("Run_V2") == {"v2"})
    check("no false hit inside a word", version_tokens("rev15 flask5d") == set())
    check("no bare digits", version_tokens("5d 150 rpm") == set())


def test_golden_case_shape():
    """The reference file: name v15b, five resolved fields v16, prose says v15b/v8.

    This is the exact content shape that defeated two earlier implementations.
    """
    text = """\
# Enzyme A v15b flask NSGA-II 5D
# v15b lineage sibling of the canonical v8 config
# 260806: fit_json advanced v15b -> v16. v18/v19/v20 bounds noted below.
description: "NSGA-II Enzyme A flask 5D - v15b 8cond fit"
extends: mpsp/optimizer_run_v8_flask_5d.yaml
fit_json: manuscript_ssot/canonical/lsq_13d_v16_do25c_kawasaki_8cond.json
parent_id: lsq_13d_v16_do25c_kawasaki_8cond
run_id: optimizer_run_v16_flask_5d
out_dir: runs/2026-08-06/optimizer_run_v16_flask_5d
meta_extra:
  variant: flask_5d_v16
  note: "matches canonical v8 config exactly except fit_json"
"""
    v = inspect_text(Path("optimizer_run_v15b_flask_5d.yaml"), text)
    check("golden: name is v15b", v.name_tokens == {"v15b"}, f"got {v.name_tokens}")
    check("golden: content is v16 only", v.content_tokens == {"v16"},
          f"got {sorted(v.content_tokens)} -- comments/prose/extends must be excluded")
    check("golden: strict fires", v.mismatch_strict)
    check("golden: set fires", v.mismatch_set)


def test_honest_file_is_clean():
    text = """\
# honest config
description: "v8 run"
fit_json: runs/lsq_v8.json
run_id: nsga2_v8_flask
"""
    v = inspect_text(Path("nsga2_v8_flask.yaml"), text)
    check("honest file clean (strict)", not v.mismatch_strict)
    check("honest file clean (set)", not v.mismatch_set, f"content={sorted(v.content_tokens)}")


def test_child_citing_parent_is_clean():
    """A child naming its parent on `extends:` is lineage, not a lie.

    Without this exclusion the set reading fired on 27/127 files instead of 3.
    """
    text = """\
extends: mpsp/optimizer_run_v18_flask_5d.yaml
run_id: optimizer_run_v18c_dtok96
out_dir: runs/2026-08-26/optimizer_run_v18c_dtok96
meta_extra:
  variant: flask_5d_v18c
"""
    v = inspect_text(Path("optimizer_run_v18c_dtok96.yaml"), text)
    check("child citing parent is clean", not v.mismatch_set,
          f"content={sorted(v.content_tokens)}")


def test_path_valued_reference_is_clean():
    """`ratio_source:`/`warm_path:` point elsewhere under keys nobody pre-lists."""
    text = """\
fit_json: runs/2026-04-28/lsq_14d_BC_v8_8cond/calibrated_params.json
parent_id: lsq_14d_BC_v8_8cond
ratio_source: runs/2026-04-28/run_b_ratio_v8_v4/calibrated_params.json
run_id: optimizer_run_b_v8_flask_5d
"""
    v = inspect_text(Path("optimizer_run_b_v8_flask_5d.yaml"), text)
    check("path-valued reference excluded", not v.mismatch_set,
          f"content={sorted(v.content_tokens)} -- v4 comes from ratio_source")


def test_partial_overlap_caught_only_by_set():
    """name v8_v3 vs content v8_v4: the shared v8 hides it from strict."""
    text = """\
fit_json: run_b_ratio_v8_v4.json
run_id: optimizer_run_b_v8_v4_s3soft
"""
    v = inspect_text(Path("optimizer_run_b_v8_v3_s3soft.yaml"), text)
    check("partial overlap: strict misses", not v.mismatch_strict)
    check("partial overlap: set catches", v.mismatch_set)


def test_undecidable_is_not_a_violation():
    v = inspect_text(Path("neutral_name.yaml"), "run_id: thing_v4\n")
    check("content-only is undecidable", v.undecidable)
    check("content-only not a violation", not v.mismatch_set and not v.mismatch_strict)
    v2 = inspect_text(Path("thing_v4.yaml"), "run_id: thing\n")
    check("name-only is undecidable", v2.undecidable)


def test_hash_inside_quotes_survives():
    text = 'note: "run #3"\nrun_id: job_v7\n'
    v = inspect_text(Path("job_v7.yaml"), text)
    check("quoted # does not truncate", not v.mismatch_set,
          f"content={sorted(v.content_tokens)}")


def test_refute_mutation_breaks_the_rule():
    """REFUTE: if the comparison is made vacuous, the golden case must stop firing.

    A rule that keeps reporting the same verdict after its logic is disabled is
    measuring nothing. Here we feed the golden NAME against content whose
    version was corrected, and require the violation to disappear.
    """
    fixed = """\
fit_json: canonical/lsq_13d_v15b_8cond.json
run_id: optimizer_run_v15b_flask_5d
"""
    v = inspect_text(Path("optimizer_run_v15b_flask_5d.yaml"), fixed)
    check("refute: corrected file stops firing", not v.mismatch_set,
          "the rule fires regardless of content -- it is not comparing")


def test_scan_reads_real_files():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "a_v15b.yaml").write_text("run_id: a_v16\n", encoding="utf-8")
        (root / "b_v8.yaml").write_text("run_id: b_v8\n", encoding="utf-8")
        hits = scan([root / "a_v15b.yaml", root / "b_v8.yaml"], mode="set")
        check("scan finds exactly the liar", [h.path.name for h in hits] == ["a_v15b.yaml"],
              f"got {[h.path.name for h in hits]}")


if __name__ == "__main__":
    for fn in [
        test_version_tokens, test_golden_case_shape, test_honest_file_is_clean,
        test_child_citing_parent_is_clean, test_path_valued_reference_is_clean,
        test_partial_overlap_caught_only_by_set, test_undecidable_is_not_a_violation,
        test_hash_inside_quotes_survives, test_refute_mutation_breaks_the_rule,
        test_scan_reads_real_files,
    ]:
        print(f"\n{fn.__name__}")
        fn()
    print("\n" + ("FAILED: " + ", ".join(FAILURES) if FAILURES else "all passed"))
    raise SystemExit(1 if FAILURES else 0)

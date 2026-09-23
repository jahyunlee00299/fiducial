"""Pin rule (2) against the real corpus it was derived from.

The reference corpus is a private research repo that is NOT available in CI,
in the public checkout, or on another machine. Its path is read from the
`FIDUCIAL_REFERENCE_CORPUS` environment variable, which carries no default
on purpose -- a public clone has no such directory, and a machine that does
have the corpus sets the variable locally. So this test SKIPS whenever the
variable is unset or the path it names does not exist -- and skipping is
legitimate only for that reason.

The numbers pinned here come from an adversarial audit, reproduced locally
against a run made on a separate machine (260920):

    comparable files (a version token on BOTH sides) : 127
    strict  (name and contents share no version)     :   2  = 1.6%
    set     (the two sets differ at all)             :   3  = 2.4%

They are pinned because three separate implementations of this rule produced
three different answers on the same files, and only the third matched the audit:

  - scanning raw text          -> golden case came out CLEAN (header comments
                                  narrate "v15b -> v16", so the name matched prose)
  - stripping comments only    -> still clean (`description:` repeats v15b)
  - excluding `extends:` only  -> set fired on 27/127, mostly honest children
                                  citing a parent, plus `ratio_source:` and
                                  `warm_path:` leaking through under keys nobody
                                  would list in advance

If a future change moves any of these three numbers, it has changed what the
rule means -- re-derive the base rate and update the audit, do not adjust the
constant to match.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fiducial.names import inspect_file  # noqa: E402

_corpus_env = os.environ.get("FIDUCIAL_REFERENCE_CORPUS")
CORPUS = Path(_corpus_env) if _corpus_env else None

EXPECTED_COMPARABLE = 127
EXPECTED_STRICT = 2
EXPECTED_SET = 3

# The three files the audit names, by exact filename. These are real filenames
# inside the private corpus, so they are not committed here: a public checkout
# has no way to name them and should not carry them as literals. Set
# `FIDUCIAL_REFERENCE_CORPUS_SET_NAMES` (comma-separated) locally to also
# check identity; without it, only the counts above are checked, which is
# still a real assertion -- just not a name-level one.
_names_env = os.environ.get("FIDUCIAL_REFERENCE_CORPUS_SET_NAMES")
EXPECTED_SET_NAMES = (
    {n.strip() for n in _names_env.split(",") if n.strip()} if _names_env else None
)

FAILURES = []


def check(label, cond, detail=""):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def main() -> int:
    if CORPUS is None:
        print("  SKIP FIDUCIAL_REFERENCE_CORPUS is not set")
        print("       (this is the ONLY legitimate reason to skip this file)")
        return 0
    if not CORPUS.is_dir():
        print(f"  SKIP reference corpus not on this machine: {CORPUS}")
        print("       (this is the ONLY legitimate reason to skip this file)")
        return 0

    files = [
        p
        for p in list(CORPUS.rglob("*.yaml")) + list(CORPUS.rglob("*.yml"))
        if ".git" not in p.parts
    ]
    if not files:
        print(f"  FAIL corpus present at {CORPUS} but no yaml found -- layout changed")
        return 1

    comparable, strict_hits, set_hits = 0, [], []
    for p in files:
        try:
            v = inspect_file(p)
        except OSError:
            continue
        if v.name_tokens and v.content_tokens:
            comparable += 1
            if v.mismatch_strict:
                strict_hits.append(p)
            if v.mismatch_set:
                set_hits.append(p)

    print(f"  corpus: {len(files)} yaml, {comparable} comparable")
    check(
        f"comparable == {EXPECTED_COMPARABLE}",
        comparable == EXPECTED_COMPARABLE,
        f"got {comparable}",
    )
    check(
        f"strict == {EXPECTED_STRICT} (1.6%)",
        len(strict_hits) == EXPECTED_STRICT,
        f"got {len(strict_hits)}: {[p.name for p in strict_hits]}",
    )
    check(
        f"set == {EXPECTED_SET} (2.4%)",
        len(set_hits) == EXPECTED_SET,
        f"got {len(set_hits)}: {[p.name for p in set_hits]}",
    )
    if EXPECTED_SET_NAMES is not None:
        check(
            "set hits are the audited files",
            {p.name for p in set_hits} == EXPECTED_SET_NAMES,
            f"got {sorted(p.name for p in set_hits)}",
        )
    else:
        print("  SKIP name-level check (FIDUCIAL_REFERENCE_CORPUS_SET_NAMES not set)")
    check(
        "strict is a subset of set",
        {p.name for p in strict_hits} <= {p.name for p in set_hits},
    )
    return 1 if FAILURES else 0


if __name__ == "__main__":
    print("test_reference_corpus")
    code = main()
    print("\n" + ("FAILED: " + ", ".join(FAILURES) if FAILURES else "all passed"))
    raise SystemExit(code)

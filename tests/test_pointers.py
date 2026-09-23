"""Rule (5): an index entry that points at something which is not there.

Built from a corpus where the defect was already doing damage: a private
research repo's `param_registry.json` registers 152 fitted parameter sets and
88 of them (58%) do not resolve. The documented loader,
`ParamRegistry.load_params(param_id)`, raises `FileNotFoundError` on the id
the plotting scripts quote by name.

The cases below are the ones that decided the design. Each was run against the
implementation before it was written down here, and three of them changed it:

- a registry with no pointers at all must report BLIND, not clean (rule (2)
  shipped exactly that bug -- `0 comparable` read as exit 0)
- `parent_id: null` is how a root entry spells "no parent"; flagging it would
  report the one definitionally-correct row as broken
- an ambiguous basename must NOT produce a repair proposal, because a repair
  tool pointed at the wrong artefact is worse than no repair at all

The reference-corpus counts are asserted, not described. If the registry is
repaired, `test_reference_corpus_counts` is expected to change -- and it is
written so that a change shows up as a number, not as silence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from fiducial import pointers as P


# The reference corpus is a private research repo, not available in CI, in the
# public checkout, or on another machine. Its path is read from
# `FIDUCIAL_REFERENCE_CORPUS`, which carries no default on purpose -- a
# public clone has no such directory. The registry's location inside that
# corpus is a project-specific layout detail, kept out of this public source
# and supplied instead via `FIDUCIAL_REFERENCE_REGISTRY` (relative to the
# corpus root, forward slashes) when set.
#
# `REFERENCE_INDEX` is `None` rather than a made-up path when the corpus is
# not configured: a placeholder path can accidentally resolve to something
# that DOES exist on some platforms (a drive root, a UNC share), which would
# silently defeat the skipif below. `None` cannot do that.
_corpus_env = os.environ.get("FIDUCIAL_REFERENCE_CORPUS")
_registry_rel = os.environ.get(
    "FIDUCIAL_REFERENCE_REGISTRY", "models/params/param_registry.json"
)
REFERENCE_INDEX: Path | None = (
    Path(_corpus_env) / _registry_rel if _corpus_env else None
)
_REFERENCE_INDEX_EXISTS = REFERENCE_INDEX is not None and REFERENCE_INDEX.exists()


def write(tmp_path: Path, doc: object, name: str = "index.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# --- blindness: the failure mode rule (2) actually shipped ----------------


def test_empty_document_is_blind_not_clean(tmp_path: Path) -> None:
    r = P.inspect_file(write(tmp_path, {}))
    assert r.blind
    assert r.checked == 0
    assert not r.broken
    assert "nothing was checked" in r.summary()


def test_entries_without_pointer_fields_are_blind(tmp_path: Path) -> None:
    doc = {"entries": {"a": {"stage": "x"}, "b": {"note": "y"}}}
    r = P.inspect_file(write(tmp_path, doc))
    assert r.blind, "rows exist but none carries a pointer -- nothing was resolved"


def test_all_resolving_is_reported_as_checked_not_blind(tmp_path: Path) -> None:
    (tmp_path / "real.json").write_text("{}", encoding="utf-8")
    r = P.inspect_file(write(tmp_path, {"entries": {"a": {"file": "real.json"}}}))
    assert not r.blind and not r.broken
    assert "all resolve" in r.summary()
    assert "1 pointers" in r.summary()


# --- what must NOT be flagged --------------------------------------------


def test_null_parent_is_a_root_not_a_dangling_pointer(tmp_path: Path) -> None:
    doc = {"entries": {"a": {"parent_id": None, "file": "gone.json"}}}
    r = P.inspect_file(write(tmp_path, doc))
    assert all(b.pointer.kind != "id" for b in r.broken)


def test_resolving_parent_id_is_not_flagged(tmp_path: Path) -> None:
    doc = {"entries": {"a": {"parent_id": None}, "b": {"parent_id": "a"}}}
    assert not P.inspect_file(write(tmp_path, doc)).broken


def test_empty_string_value_is_skipped(tmp_path: Path) -> None:
    r = P.inspect_file(write(tmp_path, {"entries": {"a": {"file": ""}}}))
    assert r.checked == 0, "an absent claim cannot be a false one"


def test_non_dict_entry_does_not_crash(tmp_path: Path) -> None:
    (tmp_path / "real.json").write_text("{}", encoding="utf-8")
    doc = {"entries": {"a": "just a string", "b": {"file": "real.json"}}}
    assert P.inspect_file(write(tmp_path, doc)).checked == 1


# --- the repair proposal, and its limits ---------------------------------


def test_moved_file_is_repairable_with_one_candidate(tmp_path: Path) -> None:
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "p.json").write_text("{}", encoding="utf-8")
    r = P.inspect_file(write(tmp_path, {"entries": {"a": {"file": "p.json"}}}))
    (b,) = r.broken
    assert b.repairable
    assert b.candidates == ("archive/p.json",)
    assert P.repair_plan(r) == {"a": "archive/p.json"}


def test_ambiguous_basename_is_not_repairable(tmp_path: Path) -> None:
    for d in ("d1", "d2"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "dup.json").write_text("{}", encoding="utf-8")
    r = P.inspect_file(write(tmp_path, {"entries": {"a": {"file": "dup.json"}}}))
    (b,) = r.broken
    assert len(b.candidates) == 2
    assert not b.repairable
    assert P.repair_plan(r) == {}, "two candidates means a guess, not a repair"


def test_missing_file_offers_no_candidates(tmp_path: Path) -> None:
    r = P.inspect_file(write(tmp_path, {"entries": {"a": {"file": "nowhere.json"}}}))
    (b,) = r.broken
    assert b.candidates == ()
    assert not b.repairable
    assert "deleted" in b.explain()


def test_repair_plan_excludes_id_pointers(tmp_path: Path) -> None:
    doc = {"entries": {"a": {"parent_id": "missing"}}}
    r = P.inspect_file(write(tmp_path, doc))
    assert r.broken and P.repair_plan(r) == {}


def test_relocation_order_is_deterministic(tmp_path: Path) -> None:
    for d in ("d2", "d1"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "dup.json").write_text("{}", encoding="utf-8")
    doc = {"entries": {"a": {"file": "dup.json"}}}
    first = P.inspect_file(write(tmp_path, doc)).broken[0].candidates
    second = P.inspect_file(write(tmp_path, doc)).broken[0].candidates
    assert first == second == ("d1/dup.json", "d2/dup.json")


# --- structure and failure ------------------------------------------------


def test_bare_mapping_shape_needs_no_configuration(tmp_path: Path) -> None:
    (tmp_path / "real.json").write_text("{}", encoding="utf-8")
    doc = {"a": {"file": "real.json"}, "b": {"file": "nope.json"}}
    r = P.inspect_file(write(tmp_path, doc))
    assert r.checked == 2 and len(r.broken) == 1


def test_malformed_index_raises_rather_than_reporting_clean(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        P.inspect_file(bad)


def test_root_override_resolves_against_the_given_directory(tmp_path: Path) -> None:
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "p.json").write_text("{}", encoding="utf-8")
    idx = write(tmp_path, {"entries": {"a": {"file": "p.json"}}})
    assert P.inspect_file(idx).broken, "not resolvable beside the index"
    assert not P.inspect_file(idx, root=tmp_path / "elsewhere").broken


def test_custom_key_names_reach_the_scan(tmp_path: Path) -> None:
    doc = {"entries": {"a": {"artifact": "nowhere.json"}}}
    idx = write(tmp_path, doc)
    assert not P.inspect_file(idx).broken, "unknown key is not a pointer by default"
    r = P.inspect_file(idx, file_keys=frozenset({"artifact"}))
    assert len(r.broken) == 1


# --- the corpus this rule was built from ----------------------------------


@pytest.mark.skipif(
    not _REFERENCE_INDEX_EXISTS, reason="reference corpus not on this machine"
)
def test_reference_corpus_counts() -> None:
    """The measured state of the reference corpus's param_registry.json, AFTER the repair.

    These numbers moved once already, exactly as intended. When this rule was
    written on 260923 the corpus read:

        file pointers broken  88   (69 relocatable + 19 gone)
        dangling parent ids   30
        total                118 of 303

    The 69 relocatable ones were then corrected in commit `dce90eff`, and
    this test failed on the next run rather than passing quietly -- which is
    why the counts are asserted instead of described. What remains is what a
    path fix cannot reach.
    """
    r = P.inspect_file(REFERENCE_INDEX)
    files = [b for b in r.broken if b.pointer.kind == "file"]
    ids = [b for b in r.broken if b.pointer.kind == "id"]
    gone = [b for b in files if not b.candidates]

    assert not r.blind
    assert len(files) == 19, f"file pointers broken: {len(files)}"
    assert len(ids) == 30, f"dangling parent ids: {len(ids)}"
    assert len(gone) == 19, "every remaining file pointer names something gone"
    assert not r.repairable, (
        "nothing is relocatable any more -- the 69 that were got fixed in "
        "commit dce90eff, and a new one appearing here means files moved again"
    )
    assert not any(
        len(b.candidates) > 1 for b in files
    ), "no basename is ambiguous in this corpus -- every repair is determined"


@pytest.mark.skipif(
    not _REFERENCE_INDEX_EXISTS, reason="reference corpus not on this machine"
)
def test_the_entry_the_plotting_scripts_quote_now_resolves() -> None:
    """The fit id six scripts hardcode must resolve.

    Which entry id that is, is a detail of the private corpus and is not
    committed here -- it is read from `FIDUCIAL_REFERENCE_FIT_ID`, and the
    test skips (via the module-level `REFERENCE_INDEX` guard plus the check
    below) rather than naming a real entry id in public source.

    Its `kla_scale = 0.7757073373946419` is quoted as `0.776` in BO and
    visualization code. The value was always right -- it matches the fit file
    to the digit. What was broken was the load path that would have made the
    copies unnecessary: the registry pointed at the flat directory the file had
    been moved out of, so `load_params` raised and hardcoding was the only
    thing that worked.

    This is the entry the rule was found on, so it is the one pinned: it must
    resolve, and it must still be the file that holds that value.
    """
    import json

    fit_id = os.environ.get("FIDUCIAL_REFERENCE_FIT_ID")
    if not fit_id:
        pytest.skip("reference corpus fit id not configured (FIDUCIAL_REFERENCE_FIT_ID)")

    r = P.inspect_file(REFERENCE_INDEX)
    assert fit_id not in P.repair_plan(r)
    assert not any(
        b.pointer.entry_id == fit_id for b in r.broken
    ), "the entry six scripts depend on must resolve"

    doc = json.loads(REFERENCE_INDEX.read_text(encoding="utf-8"))
    target = REFERENCE_INDEX.parent / doc["entries"][fit_id]["file"]
    assert target.exists()
    params = json.loads(target.read_text(encoding="utf-8"))
    assert round(params["kla_scale"], 3) == 0.776


# --- the wiring trap the handoff warned about -----------------------------


def test_the_setting_reaches_check_too(tmp_path: Path) -> None:
    """`check` builds each rule's Namespace by hand, so a new setting has to be
    added in two places. Forgetting the second one makes `check` silently use
    the default while the subcommand honours the config -- the exact shape of
    "configured and not in force" this package exists to refuse.

    Proven by behaviour, not by reading the source: with `file_keys` set, the
    custom key is a pointer and `check` exits 1; without it the same index has
    no pointers at all and `check` reports CANNOT CHECK.
    """
    import subprocess
    import sys as _sys

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "i.json").write_text(
        json.dumps({"entries": {"a": {"artifact": "nowhere.json"}}}), encoding="utf-8"
    )
    cfg = tmp_path / "pyproject.toml"
    base = '[tool.fiducial]\nrules = ["pointers"]\npointers_paths = ["sub/i.json"]\n'

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [_sys.executable, "-m", "fiducial", "check"],
            cwd=tmp_path, capture_output=True, text=True,
        )

    cfg.write_text(base + 'file_keys = ["artifact"]\n', encoding="utf-8")
    with_setting = run()
    assert with_setting.returncode == 1, with_setting.stdout + with_setting.stderr
    assert "1 broken pointer" in with_setting.stdout

    cfg.write_text(base, encoding="utf-8")
    without = run()
    assert without.returncode == 2, "an unknown key is not a pointer -- blind, not clean"
    assert "nothing was checked" in without.stdout

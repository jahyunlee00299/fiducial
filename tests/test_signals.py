"""Structured findings: the contract an agent consumes.

The prose these rules emit was written for a person reading a terminal. The
caller that most needs the rules is no longer a person -- someone who sets
parameters by hand already knows where their numbers came from, while a model
writing `params.get("eta", 0.87)` does not. What that caller needs is the one
thing prose cannot give it: what to do about each finding.

Three exit codes cannot say it. `0/1/2` reports whether anything was found, not
whether the caller may act alone. Rule (5) produces the clearest case: a moved
file and a deleted file are both certain violations, and treating them alike
makes an agent invent a path for the one that has no answer.

So two axes, tested here as two axes:

    confidence   is this finding real
    fix          may the caller repair it unattended

The tests below are ordered by what would break first if the design were
wrong. `test_applying_an_auto_fix_actually_resolves_it` is the load-bearing
one: everything else is bookkeeping if a fix marked safe does not repair what
it claims to.
"""

from __future__ import annotations

import json
from pathlib import Path

from fiducial import pointers as P
from fiducial import signals as S

REPO = Path(__file__).resolve().parents[1]


def _index(tmp_path: Path, entries: dict, name: str = "i.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return p


def _signals(idx: Path) -> list[S.Signal]:
    return S.from_pointers([P.inspect_file(idx)])


# --- the claim that matters ------------------------------------------------


def test_applying_an_auto_fix_actually_resolves_it(tmp_path: Path) -> None:
    """A fix marked `safe`/`auto` must repair the defect when applied blindly.

    This is the whole promise of the `auto` mode: an agent applies it without
    looking. If the edit were merely plausible, the mode would be an
    invitation to corrupt a registry, which is worse than emitting no fix at
    all.
    """
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "m.json").write_text("{}", encoding="utf-8")
    idx = _index(tmp_path, {"a": {"file": "m.json"}})

    (sig,) = _signals(idx)
    assert sig.fix is not None and sig.fix.apply == "auto"

    doc = json.loads(idx.read_text(encoding="utf-8"))
    doc["entries"]["a"][sig.fix.edit["field"]] = sig.fix.edit["to"]
    idx.write_text(json.dumps(doc), encoding="utf-8")

    assert not P.inspect_file(idx).broken, "the 'safe' fix did not fix it"


def test_an_ambiguous_case_offers_no_single_target(tmp_path: Path) -> None:
    """Two candidates must not be reducible to something an agent can apply.

    The edit carries `candidates`, never `to` -- so a caller that only knows
    how to read `to` finds nothing to do, which is the correct outcome. This
    is the difference between a tool that refuses to guess and one that hands
    the guess to somebody else.
    """
    for d in ("x", "y"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "dup.json").write_text("{}", encoding="utf-8")
    (sig,) = _signals(_index(tmp_path, {"b": {"file": "dup.json"}}))

    assert sig.fix is not None
    assert sig.fix.apply == "suggest_only"
    assert sig.fix.applicability == "unsafe"
    assert "to" not in sig.fix.edit
    assert len(sig.fix.edit["candidates"]) == 2


def test_a_missing_artefact_offers_no_fix_but_stays_certain(tmp_path: Path) -> None:
    """The two axes pulling apart, which is why there are two of them.

    Nothing by that name exists anywhere, so the finding is as certain as the
    repairable one -- and completely unfixable by a tool. A single severity
    ladder would have to rank these against each other; they do not differ in
    severity at all.
    """
    (sig,) = _signals(_index(tmp_path, {"c": {"file": "gone.json"}}))
    assert sig.confidence == "certain"
    assert sig.fix is None
    assert "person" in sig.action


def test_all_three_pointer_outcomes_are_certain_and_differ_only_in_fix(
    tmp_path: Path,
) -> None:
    """The design claim, stated as one assertion.

    Moved, ambiguous and gone are the same confidence and three different
    instructions. If confidence ever varies across them, the axes have been
    conflated and an agent will treat "we cannot tell which file" as "we are
    not sure there is a problem".
    """
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "m.json").write_text("{}", encoding="utf-8")
    for d in ("x", "y"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "dup.json").write_text("{}", encoding="utf-8")

    sigs = _signals(
        _index(
            tmp_path,
            {
                "moved": {"file": "m.json"},
                "ambiguous": {"file": "dup.json"},
                "gone": {"file": "nowhere.json"},
            },
        )
    )
    by = {s.entry: s for s in sigs}

    assert {s.confidence for s in sigs} == {"certain"}
    assert by["moved"].fix.apply == "auto"
    assert by["ambiguous"].fix.apply == "suggest_only"
    assert by["gone"].fix is None


# --- blind is not clean, and not a violation either -------------------------


def test_blind_is_reported_as_cannot_check(tmp_path: Path) -> None:
    """An index with no resolvable pointer is unchecked, not clean.

    It is also not a violation: counting it as one would tell an agent to go
    fix something, when what is wrong is the invocation.
    """
    (sig,) = _signals(_index(tmp_path, {"z": {"stage": "s"}}))
    assert sig.status == "cannot_check"
    assert sig.fix is None
    assert "not a clean result" in sig.action


def test_summary_separates_what_an_agent_may_do_alone(tmp_path: Path) -> None:
    """The counts a caller acts on, without tallying the list itself."""
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "m.json").write_text("{}", encoding="utf-8")
    env = S.Envelope(
        _signals(
            _index(tmp_path, {"moved": {"file": "m.json"}, "gone": {"file": "no.json"}})
        )
    )
    s = env.summary()
    assert s["auto_fixable"] == 1
    assert s["needs_human"] == 1
    assert s["violations"] + s["cannot_check"] == s["total"]


# --- the wire format -------------------------------------------------------


def test_every_signal_carries_an_action(tmp_path: Path) -> None:
    """An agent reads one finding at a time and has no access to our docs.

    The instruction ships inside the finding for that reason. A caller that
    has to be told separately how to read `apply: auto` is a caller that will
    guess.
    """
    (sig,) = _signals(_index(tmp_path, {"c": {"file": "gone.json"}}))
    assert sig.action and len(sig.action) > 20


def test_the_fix_key_is_absent_rather_than_null(tmp_path: Path) -> None:
    """`"fix" in finding` must answer "is this automatable at all".

    A null would make every consumer write the same two-step check, and some
    would write only the first half.
    """
    (sig,) = _signals(_index(tmp_path, {"c": {"file": "gone.json"}}))
    assert "fix" not in sig.as_dict()


def test_the_document_round_trips(tmp_path: Path) -> None:
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "m.json").write_text("{}", encoding="utf-8")
    env = S.Envelope(_signals(_index(tmp_path, {"a": {"file": "m.json"}})))
    doc = env.as_dict()
    assert json.loads(env.to_json()) == doc
    assert doc["version"] == S.SCHEMA_VERSION


def test_the_message_is_the_rules_own_prose(tmp_path: Path) -> None:
    """The JSON adds fields; it does not replace the explanation.

    An agent deciding what to do needs the reasoning as much as a person does,
    so `message` stays exactly what `explain()` produced rather than being
    reduced to a code.
    """
    idx = _index(tmp_path, {"c": {"file": "gone.json"}})
    (broken,) = P.inspect_file(idx).broken
    (sig,) = _signals(idx)
    assert sig.message == broken.explain()


# --- the vocabulary is borrowed, and stays borrowed -------------------------


def test_applicability_uses_ruffs_measured_values(tmp_path: Path) -> None:
    """`safe` / `unsafe`, as `ruff check --output-format=json` emits them.

    Measured against ruff 0.16.0 rather than read from its documentation. The
    point of borrowing the vocabulary is that a consumer written against one
    tool already knows what these mean; inventing synonyms would discard that.
    """
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "m.json").write_text("{}", encoding="utf-8")
    for d in ("x", "y"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "dup.json").write_text("{}", encoding="utf-8")
    sigs = _signals(
        _index(tmp_path, {"a": {"file": "m.json"}, "b": {"file": "dup.json"}})
    )
    assert {s.fix.applicability for s in sigs if s.fix} == {"safe", "unsafe"}


# --- every rule, through the CLI ------------------------------------------


def _cli(*argv: str, cwd: Path | None = None):
    import subprocess
    import sys

    return subprocess.run(
        [sys.executable, "-m", "fiducial", *argv],
        capture_output=True, text=True, cwd=str(cwd or REPO),
    )


def test_every_rule_emits_the_same_envelope(tmp_path: Path) -> None:
    """All five, not just the one the format was built on.

    An adapter that exists in `signals.py` and is reachable from no
    subcommand is the written-but-unwired shape this repo keeps catching, so
    the wiring is asserted per rule rather than assumed from the module.
    """
    (tmp_path / "m.py").write_text(
        'eta = params.get("eta", 0.87)\n', encoding="utf-8"
    )
    (tmp_path / "a_v15b.yaml").write_text("run_id: a_v16\n", encoding="utf-8")
    (tmp_path / "spec.yaml").write_text(
        "learnable_keys:\n  - alpha\n", encoding="utf-8"
    )
    (tmp_path / "test_x.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (tmp_path / "SSOT.md").write_text("# s\n\nreaction time 48 min\n", encoding="utf-8")
    (tmp_path / "DER.md").write_text(
        "---\nssot:\n  source: SSOT.md\n  repeats:\n    reaction time: 48\n"
        "---\nreaction time 36 min.\n",
        encoding="utf-8",
    )
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "m.json").write_text("{}", encoding="utf-8")
    (tmp_path / "i.json").write_text(
        json.dumps({"entries": {"x": {"file": "m.json"}}}), encoding="utf-8"
    )

    invocations = {
        "literals": ("literals", "--keys", "eta", "--format", "json",
                     str(tmp_path / "m.py")),
        "names": ("names", "--format", "json", str(tmp_path / "a_v15b.yaml")),
        "coverage": ("coverage", "--spec", str(tmp_path / "spec.yaml"),
                     "--format", "json", str(tmp_path / "test_x.py")),
        "docs": ("docs", "--root", str(tmp_path), "--format", "json",
                 str(tmp_path / "DER.md")),
        "pointers": ("pointers", "--format", "json", str(tmp_path / "i.json")),
    }

    for rule, argv in invocations.items():
        r = _cli(*argv)
        assert r.stdout.lstrip().startswith("{"), f"{rule}: {r.stdout[:120]}{r.stderr[:120]}"
        doc = json.loads(r.stdout)
        assert doc["version"] == S.SCHEMA_VERSION, rule
        assert set(doc["summary"]) == {
            "total", "violations", "cannot_check", "auto_fixable", "needs_human"
        }, rule
        assert doc["findings"], f"{rule} produced no finding on a seeded defect"
        for f in doc["findings"]:
            assert f["rule"] == rule
            assert f["status"] in ("violation", "cannot_check")
            assert f["confidence"] in ("certain", "needs_review")
            assert f["message"] and f["action"]


def test_the_rules_that_cannot_repair_emit_no_fix(tmp_path: Path) -> None:
    """Rules (1) and (3) must never hand an agent something to apply.

    Neither a provenance nor a missing test is something a checker can
    synthesise. Emitting a `fix` there would invite exactly the substitution
    the rules exist to catch -- a plausible number, a test that asserts
    nothing.
    """
    (tmp_path / "m.py").write_text(
        'eta = params.get("eta", 0.87)\n', encoding="utf-8"
    )
    r = _cli("literals", "--keys", "eta", "--format", "json", str(tmp_path / "m.py"))
    for f in json.loads(r.stdout)["findings"]:
        assert "fix" not in f

    (tmp_path / "spec.yaml").write_text(
        "learnable_keys:\n  - alpha\n", encoding="utf-8"
    )
    (tmp_path / "test_x.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    r = _cli("coverage", "--spec", str(tmp_path / "spec.yaml"), "--format", "json",
             str(tmp_path / "test_x.py"))
    for f in json.loads(r.stdout)["findings"]:
        assert "fix" not in f


def test_coverage_omits_the_keys_that_are_gated(tmp_path: Path) -> None:
    """A finding for something that is fine makes a consumer filter to count."""
    (tmp_path / "spec.yaml").write_text(
        "learnable_keys:\n  - alpha\n  - beta\n", encoding="utf-8"
    )
    (tmp_path / "test_x.py").write_text(
        "def test_a():\n    assert params['alpha'] == 1\n", encoding="utf-8"
    )
    r = _cli("coverage", "--spec", str(tmp_path / "spec.yaml"), "--format", "json",
             str(tmp_path / "test_x.py"))
    keys = [f["key"] for f in json.loads(r.stdout)["findings"]]
    assert keys == ["beta"], "the asserted key should not appear at all"


def test_docs_reports_an_unreadable_declaration_as_cannot_check(
    tmp_path: Path,
) -> None:
    """Its author believes it is gated, and it is not. Never a clean count."""
    (tmp_path / "BAD.md").write_text(
        "---\nssot:\n  source: [unclosed\n---\nx\n", encoding="utf-8"
    )
    r = _cli("docs", "--root", str(tmp_path), "--format", "json",
             str(tmp_path / "BAD.md"))
    doc = json.loads(r.stdout)
    assert doc["summary"]["cannot_check"] >= 1
    assert r.returncode == 2, "an unchecked document is not a pass"

"""rule (4) — document vs its declared SSOT.

The cases below are the ones measured while building the rule, kept so that a
later change cannot quietly re-break them.  Two groups matter most:

* ``test_catches_*`` — the incident this rule exists for.  If one of these goes
  green-but-silent the rule is decorative.
* ``test_allows_*`` — the sentences a research corpus is *full* of.  If one of
  these starts failing, the finding count climbs and the gate gets switched
  off, which is the documented way these checks die.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from fiducial import docs as D
from fiducial.cli import main


SSOT = """\
# 공정 운전조건 (SSOT)

탈색액은 pH 10 · 30 °C 이하 · 상압으로 U203d에 들어간다.
체류시간은 residence_h 36 이다.
"""


def _corpus(tmp_path: Path, body: str, ssot: str = SSOT) -> Path:
    (tmp_path / "PROCESS_CONDITIONS.md").write_text(ssot, encoding="utf-8")
    doc = tmp_path / "derived.md"
    doc.write_text(textwrap.dedent(body), encoding="utf-8")
    return doc


def _front(repeats: str = "    pH: 10\n") -> str:
    return "---\nssot:\n  source: PROCESS_CONDITIONS.md\n  repeats:\n" + repeats + "---\n"


def _run(doc: Path) -> tuple[list[D.Finding], list[D.SourceGap]]:
    decl = D.read_declaration(doc)
    assert decl is not None, "fixture should declare an SSOT"
    return D.check(decl)


# --------------------------------------------------------------------------
# the incident
# --------------------------------------------------------------------------


def test_catches_the_ph_incident(tmp_path):
    """260922: a PFD asserted pH 5.0 for a step the SSOT holds at pH 10."""
    doc = _corpus(tmp_path, _front() + "U203d-pre 에서 pH 5.0 으로 조정한다.\n")
    findings, _ = _run(doc)
    assert [f.found for f in findings] == [5.0]
    assert findings[0].source_values == [10.0]


@pytest.mark.parametrize(
    "line",
    [
        "**pH 5.0** 으로 운전한다.",                       # bold run
        "노드: `pH 8.5` 로 맞춘다.",                        # inline code
        'PRE["<b>U203d-pre</b><br/>pH 5.0 조정<br/>상압"]',  # mermaid node label
        "pH 5.0으로 조정",                                  # Korean particle, no space
        "pH = 5.0",
        "pH: 5.0",
    ],
)
def test_catches_values_hidden_in_markup(tmp_path, line):
    """Real documents bury the number in markup; that must not be a hiding place."""
    doc = _corpus(tmp_path, _front() + line + "\n")
    findings, _ = _run(doc)
    assert len(findings) == 1, f"missed: {line}"


def test_agreeing_value_is_silent(tmp_path):
    doc = _corpus(
        tmp_path,
        _front("    pH: 10\n    residence_h: 36\n") + "pH 10 · residence_h 36 으로 운전한다.\n",
    )
    findings, gaps = _run(doc)
    assert findings == [] and gaps == []


# --------------------------------------------------------------------------
# what a research corpus legitimately says
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "선례가 갈린다: CN101904484A는 pH 5.0, US4322569A는 pH 7.5~10.5다.",  # prior art
        "260921 정정 — 2차 판은 pH 5.0이라고 적었으나 철회했다.",             # retraction
        "~~pH 5.0~~ 폐기.",                                                   # struck out
        "이전 판에서는 pH 5.0 이었다.",                                       # past tense
        "우리 조건은 pH 10 → 5.0 으로 바꾸자는 제안이 있었다.",               # change arrow
        "출처: 특허 실시예의 pH 5.0.",                                        # attribution
        "문헌의 pH 5.0 은 우리와 다르다.",
    ],
)
def test_allows_citation_and_history(tmp_path, line):
    """A gate that flags these teaches the author to switch it off."""
    doc = _corpus(tmp_path, _front() + line + "\n")
    findings, _ = _run(doc)
    assert findings == [], f"false positive: {line}"


@pytest.mark.parametrize(
    "line",
    [
        "| 운전조건 | pH 4~8 [본문확인] · 온도 유지 |",
        "pH 7.5-10.5 로 돌린다.",
        "pH 4 – 8 구간에서 운전한다.",
        "pH 4 to 8",
    ],
)
def test_allows_ranges(tmp_path, line):
    """A band is not an operating point.

    Measured 260922: on the 562-line reference PFD these were 2 of 2 findings,
    both wrong -- the rule had read `pH 4~8` as the value 4.0. Comparing a
    band's lower bound against a single SSOT value is a category error.
    """
    doc = _corpus(tmp_path, _front() + line + "\n")
    findings, _ = _run(doc)
    assert findings == [], f"range read as a value: {line}"


def test_range_fix_did_not_blind_the_rule(tmp_path):
    """The narrowing above must not have cost the real catch.

    Suppressing false positives by widening what is ignored is the standard way
    a gate becomes decorative, so the incident line is re-checked alongside the
    ranges it now tolerates.
    """
    doc = _corpus(
        tmp_path,
        _front()
        + "| 운전조건 | pH 4~8 [본문확인] |\n"
        + "U203d-pre 에서 pH 5.0 으로 조정한다.\n",
    )
    findings, _ = _run(doc)
    assert [f.found for f in findings] == [5.0]


# --------------------------------------------------------------------------
# a declaration that cannot be used must never read as clean
# --------------------------------------------------------------------------


def test_undeclared_document_is_not_checked(tmp_path):
    doc = _corpus(tmp_path, "# 선언 없음\n\npH 5.0 으로 운전한다.\n")
    assert D.read_declaration(doc) is None


@pytest.mark.parametrize(
    "front, message",
    [
        ("---\nssot:\n  source: PROCESS_CONDITIONS.md\n---\n", "repeats"),
        ("---\nssot:\n  repeats:\n    pH: 10\n---\n", "source"),
        ("---\nssot: PROCESS_CONDITIONS.md\n---\n", "mapping"),
        # An inline mapping is refused rather than half-parsed: a declaration
        # that silently reads as empty is the failure this rule exists to stop.
        ("---\nssot:\n  source: PROCESS_CONDITIONS.md\n  repeats: {}\n---\n", "repeats"),
        ("---\nssot:\n  source: PROCESS_CONDITIONS.md\n  repeats:\n---\n", "repeats"),
    ],
)
def test_malformed_declaration_raises(tmp_path, front, message):
    doc = _corpus(tmp_path, front + "pH 5.0\n")
    with pytest.raises(D.DeclarationError) as exc:
        D.read_declaration(doc)
    assert message in str(exc.value)


def test_missing_source_document_raises(tmp_path):
    doc = _corpus(
        tmp_path,
        "---\nssot:\n  source: NOSUCH.md\n  repeats:\n    pH: 10\n---\npH 5.0\n",
    )
    decl = D.read_declaration(doc)
    with pytest.raises(D.DeclarationError):
        D.check(decl)


def test_quantity_absent_from_source_is_a_gap_not_a_pass(tmp_path):
    """Declaring a quantity the source never states compares nothing."""
    doc = _corpus(tmp_path, _front("    flux_lmh: 40\n") + "flux_lmh 12 로 운전한다.\n")
    findings, gaps = _run(doc)
    assert findings == []
    assert [(g.label, g.side) for g in gaps] == [("flux_lmh", "source")]


def test_quantity_absent_from_the_document_is_also_a_gap(tmp_path):
    """🔴 The dangerous direction.

    Measured while wiring this rule to a real repository: a derived document
    declared `반응 시간`, the SSOT stated it, and the run reported 0 violations
    -- because the derived document writes the same quantity as `시간` and was
    never searched successfully.  Nothing was compared and the output looked
    exactly like agreement.
    """
    doc = _corpus(tmp_path, _front("    residence_h: 36\n") + "체류시간은 넉넉히 잡는다.\n")
    findings, gaps = _run(doc)
    assert findings == []
    assert [(g.label, g.side) for g in gaps] == [("residence_h", "document")]


def test_alias_lets_two_documents_use_different_words(tmp_path):
    """Two documents rarely name one quantity identically.

    Measured on the reference repository: `PROCESS_TARGET.md` calls it
    `생산 규모` and `SCALE_BASIS.md`, which explicitly says that document owns
    the number, calls it `목표 생산량`. Without an alias the rule reports two
    gaps and checks nothing — the pair most worth checking.
    """
    (tmp_path / "PROCESS_CONDITIONS.md").write_text(
        "| 생산 규모 | 2,000 t/yr |\n", encoding="utf-8"
    )
    doc = tmp_path / "derived.md"
    doc.write_text(
        "---\nssot:\n  source: PROCESS_CONDITIONS.md\n  repeats:\n"
        "    목표 생산량 as 생산 규모: 2000\n---\n"
        "| 목표 생산량 | 3,000 t/yr |\n",
        encoding="utf-8",
    )
    findings, gaps = _run(doc)
    assert gaps == []
    assert [(f.label, f.found, f.source_values) for f in findings] == [
        ("목표 생산량", 3000.0, [2000.0])
    ]


def test_alias_agreeing_is_silent(tmp_path):
    (tmp_path / "PROCESS_CONDITIONS.md").write_text(
        "| 생산 규모 | 2,000 t/yr |\n", encoding="utf-8"
    )
    doc = tmp_path / "derived.md"
    doc.write_text(
        "---\nssot:\n  source: PROCESS_CONDITIONS.md\n  repeats:\n"
        "    목표 생산량 as 생산 규모: 2000\n---\n"
        "| 목표 생산량 | 2,000 t/yr |\n",
        encoding="utf-8",
    )
    assert _run(doc) == ([], [])


def test_declaration_is_not_compared_against_itself(tmp_path):
    """🔴 The front matter must not count as prose.

    Found while wiring the rule to a real repository: the declaration's own
    `residence_h: 36` was read as a statement in the document, matched the
    SSOT, and reported agreement — so every declared quantity passed whether or
    not the body said anything. A gate that always passes.
    """
    doc = _corpus(
        tmp_path,
        _front("    residence_h: 36\n") + "본문은 체류시간을 언급하지 않는다.\n",
    )
    findings, gaps = _run(doc)
    assert findings == []
    assert [(g.label, g.side) for g in gaps] == [("residence_h", "document")]


def test_line_numbers_survive_front_matter_removal(tmp_path):
    """Stripping the declaration must not shift the reported line."""
    doc = _corpus(tmp_path, _front() + "pH 5.0 으로 조정한다.\n")
    findings, _ = _run(doc)
    assert findings[0].line_no == 7
    assert doc.read_text(encoding="utf-8").splitlines()[6].startswith("pH 5.0")


def test_gap_is_visible_in_cli_output(tmp_path, capsys):
    """A gap that only shows behind a flag is a gap nobody sees."""
    _corpus(tmp_path, _front("    residence_h: 36\n") + "체류시간은 넉넉히 잡는다.\n")
    main(["docs", str(tmp_path)])
    out = capsys.readouterr().out
    assert "nothing is being compared" in out


def test_strict_gaps_blocks(tmp_path):
    _corpus(tmp_path, _front("    residence_h: 36\n") + "체류시간은 넉넉히 잡는다.\n")
    assert main(["docs", str(tmp_path)]) == 0
    assert main(["docs", "--strict-gaps", str(tmp_path)]) == 1


# --------------------------------------------------------------------------
# exit codes — the contract automation reads
# --------------------------------------------------------------------------


def test_cli_exit_1_on_violation(tmp_path):
    _corpus(tmp_path, _front() + "pH 5.0 으로 조정한다.\n")
    assert main(["docs", str(tmp_path)]) == 1


def test_cli_exit_0_when_consistent(tmp_path):
    _corpus(tmp_path, _front() + "pH 10 으로 운전한다.\n")
    assert main(["docs", str(tmp_path)]) == 0


def test_cli_exit_2_when_nothing_declares(tmp_path):
    """0 of 53 documents declared an SSOT at adoption. Blind is not clean."""
    _corpus(tmp_path, "# 선언 없음\n\npH 5.0\n")
    assert main(["docs", str(tmp_path)]) == 2


def test_cli_exit_2_on_empty_scan(tmp_path):
    assert main(["docs", str(tmp_path / "nope")]) == 2


def test_cli_reports_unusable_declaration_as_violation(tmp_path):
    """The author believes this document is gated; silence would be worse."""
    _corpus(tmp_path, "---\nssot:\n  source: NOSUCH.md\n  repeats:\n    pH: 10\n---\n")
    assert main(["docs", str(tmp_path)]) == 1


# --------------------------------------------------------------------------
# tolerance
# --------------------------------------------------------------------------


def test_tolerance_is_exact_by_default(tmp_path):
    doc = _corpus(tmp_path, _front("    residence_h: 36\n") + "residence_h 35.9 이다.\n")
    assert len(_run(doc)[0]) == 1


def test_tolerance_can_be_relaxed(tmp_path):
    doc = _corpus(tmp_path, _front("    residence_h: 36\n") + "residence_h 35.9 이다.\n")
    decl = D.read_declaration(doc)
    findings, _ = D.check(decl, rel_tol=0.01)
    assert findings == []


# --------------------------------------------------------------------------
# documented limitation — kept as a test so it cannot rot into a surprise
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row, label, expected",
    [
        ("| 반응 시간 | 24 h |", "반응 시간", [24.0]),
        ("| 생산 규모 | 2,000 t/yr |", "생산 규모", [2000.0]),
        ("| 운전조건 | pH 4~8 |", "운전조건", []),        # a band is still skipped
        ("| 반응 시간 | 확정 예정 |", "반응 시간", []),     # no number in the row
    ],
)
def test_reads_values_out_of_table_cells(row, label, expected):
    """Confirmed-specification documents keep their quantities in tables.

    Without this the rule is blind to exactly the documents most worth
    checking — `PROCESS_TARGET.md` states every target as a table row.
    """
    assert [v for _, v, _ in D.find_values(row, label)] == expected


def test_thousands_separator_is_not_misread():
    """🔴 `2,000 t/yr` once parsed as 2.0.

    A gate that misreads the number it compares is worse than no gate: it would
    have reported a 2,000 t/yr target as the value 2.0 and sent someone looking
    for a defect that does not exist.
    """
    assert [v for _, v, _ in D.find_values("생산 규모 2,000 t/yr", "생산 규모")] == [2000.0]


def test_value_in_a_table_row_is_reported_once():
    """The table path and the prose path must not both claim the same number."""
    found = D.find_values("| pH | 10 |", "pH")
    assert [v for _, v, _ in found] == [10.0]


def test_known_limitation_label_and_value_on_separate_lines(tmp_path):
    """A column-oriented table puts the label in the header row and the value
    in a later one, so no single line carries both and the rule does not see
    it.  (A row-oriented table — `| 반응 시간 | 24 h |` — *is* read; see
    ``test_reads_values_out_of_table_cells``.)

    Recorded deliberately: the README states the limitation, and this test
    fails loudly if the behaviour ever changes, so the docs get corrected with
    it rather than drifting out of date."""
    doc = _corpus(
        tmp_path,
        _front() + "| 단계 | pH |\n|---|---|\n| U203d | 5.0 |\n",
    )
    findings, _ = _run(doc)
    assert findings == [], "behaviour changed — update README's limitation section"

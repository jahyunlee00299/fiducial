"""The YAML subset rule (5) needs, and the refusals that keep it honest.

Why a parser at all: the largest public corpus of indexes this package has
been tried against -- 35 PEtab benchmark models -- writes its index in YAML,
so a JSON-only rule cannot see a single one of them. `PyYAML` would solve it
in a line, and this package ships zero dependencies, which is what lets a
project adopt it without a conversation about its supply chain.

The central test is differential, the same shape as the 3.10 TOML fallback in
`test_config.py`: every model in the corpus is parsed both ways and the
results must match. A hand-written parser that disagrees with the real one is
worse than no parser, because the disagreement only shows up on somebody
else's index.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fiducial import minyaml

CORPUS = Path.home() / "scratch" / "fiducial" / "Benchmark-Models-PEtab"


def _models() -> list[Path]:
    root = CORPUS / "Benchmark-Models"
    if not root.is_dir():
        return []
    return sorted(p for d in root.iterdir() if d.is_dir() for p in d.glob("*.yaml"))


# --- the differential test -------------------------------------------------


@pytest.mark.skipif(not _models(), reason="PEtab corpus not on this machine")
def test_agrees_with_pyyaml_on_every_model() -> None:
    """Measured: 36/36 identical, including the outlier shapes.

    Two indentation styles appear in the corpus -- `- condition_files:` opening
    a mapping on the dash line (5 models) and the same key indented under it
    (29 models) -- and both must parse to the same structure.
    """
    yaml = pytest.importorskip("yaml", reason="no PyYAML to compare against")
    for f in _models():
        text = f.read_text(encoding="utf-8")
        assert minyaml.loads(text) == yaml.safe_load(text), f.name


@pytest.mark.skipif(not _models(), reason="PEtab corpus not on this machine")
def test_every_model_in_the_corpus_parses() -> None:
    for f in _models():
        doc = minyaml.loads(f.read_text(encoding="utf-8"))
        assert isinstance(doc, dict) and "problems" in doc, f.name


# --- the subset it does cover ----------------------------------------------


def test_the_shapes_an_index_needs() -> None:
    doc = minyaml.loads(
        "format_version: 1\n"
        "parameter_file: parameters_X.tsv\n"
        "problems:\n"
        "- condition_files:\n"
        "  - experimentalCondition_X.tsv\n"
        "  sbml_files:\n"
        "  - model_X.xml\n"
    )
    assert doc["format_version"] == 1
    assert doc["parameter_file"] == "parameters_X.tsv"
    assert doc["problems"][0]["sbml_files"] == ["model_X.xml"]


def test_scalars_resolve_like_yaml_does() -> None:
    doc = minyaml.loads(
        "i: 1\nf: 2.5\nt: true\nf2: false\nn: null\ns: plain\nq: 'quoted'\n"
    )
    assert doc == {
        "i": 1, "f": 2.5, "t": True, "f2": False,
        "n": None, "s": "plain", "q": "quoted",
    }


def test_a_comment_is_dropped_but_not_inside_a_string() -> None:
    """A filename may legitimately contain `#`."""
    doc = minyaml.loads('a: value  # trailing\nb: "has # inside"\n')
    assert doc == {"a": "value", "b": "has # inside"}


def test_a_colon_in_a_list_item_is_not_a_mapping() -> None:
    """`- http://x` is a scalar. A colon opens a mapping only before a space."""
    doc = minyaml.loads("urls:\n- http://example.com/a\n- b: 1\n")
    assert doc["urls"][0] == "http://example.com/a"
    assert doc["urls"][1] == {"b": 1}


# --- and the refusals ------------------------------------------------------


@pytest.mark.parametrize(
    "text, why",
    [
        ("a: &anchor 1\nb: *anchor\n", "anchors"),
        ("a: |\n  block\n", "block scalars"),
        ("a: 1\n---\nb: 2\n", "multiple documents"),
        ("a: [1, 2]\n", "flow collection"),
        ("a: {b: 1}\n", "flow collection"),
    ],
)
def test_it_refuses_rather_than_approximating(text: str, why: str) -> None:
    """Every refusal is a construct that changes what the document MEANS.

    Skipping the line would hand rule (5) an index whose pointers were never
    the ones written, and the caller would believe they were checked -- the
    same false evidence the 3.10 TOML fallback refuses.
    """
    with pytest.raises(minyaml.YamlError):
        minyaml.loads(text)


def test_an_empty_document_is_an_empty_mapping() -> None:
    assert minyaml.loads("") == {}
    assert minyaml.loads("# only a comment\n") == {}

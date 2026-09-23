"""`[tool.fiducial]` config loading, and the 3.10 TOML fallback.

The fallback is the risky part. It exists because `tomllib` is stdlib only
from 3.11 while this package supports 3.10 with zero dependencies, and a
hand-written parser that disagrees with the real one is worse than no config
file: the project's settings would differ by interpreter.

So the central test here is differential -- every fixture is parsed BOTH ways
on 3.11+ and the results must match. On 3.10 that comparison cannot run, which
is exactly why it must run everywhere else.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from fiducial import config as C


# --------------------------------------------------------------------------
# the differential test: the fallback must agree with tomllib
# --------------------------------------------------------------------------

FIXTURES = [
    'keys = ["eta", "kla_scale"]\n',
    'keys = [\n  "eta",\n  "kla_scale",\n]\n',
    "include_neutral = true\nstrict_gaps = false\n",
    "tol = 0.01\n",
    'names_mode = "strict"\n',
    'keys = ["eta"]  # trailing comment\n',
    'spec = ".claude/params_spec.yaml"\n',
    "neutral_defaults = [0.0, 1.0]\n",
    'extend_self_declaring_keys = ["fit_id"]\n',
    "",                                            # empty table
    'keys = ["a#b"]\n',                            # a hash INSIDE a string
    'rules = ["names", "docs"]\nnames_mode = "set"\n',
]


@pytest.mark.skipif(sys.version_info < (3, 11), reason="no tomllib to compare against")
@pytest.mark.parametrize("body", FIXTURES)
def test_fallback_agrees_with_tomllib(body):
    """The 3.10 reader and the stdlib reader must produce the same dict.

    A config that means one thing on 3.10 and another on 3.13 is a defect that
    only shows up on somebody else's machine.
    """
    import tomllib

    text = "[tool.fiducial]\n" + body
    assert C._parse_toml_subset(text) == tomllib.loads(text), body


def test_fallback_refuses_what_it_cannot_parse():
    """It raises rather than skipping.

    A parser that drops the line it does not understand hands back a config the
    author believes is in force. That is the same false-evidence failure the
    rules themselves exist to catch, so the fallback is loud by construction.
    """
    with pytest.raises(C.ConfigError) as exc:
        C._parse_toml_subset('[tool.fiducial]\nkeys = { inline = "table" }\n')
    assert "refuses rather than skipping" in str(exc.value) or "cannot read" in str(exc.value)


def test_fallback_handles_hash_inside_a_string():
    got = C._parse_toml_subset('[tool.fiducial]\nspec = "a#b.yaml"\n')
    assert got["tool"]["fiducial"]["spec"] == "a#b.yaml"


# Two shapes where the first version of the fallback SILENTLY disagreed with
# tomllib -- found by running 18 hostile inputs through both readers and
# diffing, not by review. Both are now refused rather than guessed, because a
# config that means one thing on 3.10 and another on 3.13 is a defect that
# surfaces only on somebody else's machine.
#
# 16 of the 18 were already correct: 9 agreed exactly, 7 were refused. These
# two were the whole finding.

def test_escaped_quote_is_refused_not_guessed():
    r"""`"he said \"hi\""` parsed as `he said \"hi\"` here, `he said "hi"` there."""
    with pytest.raises(C.ConfigError) as exc:
        C._parse_toml_subset('[tool.fiducial]\na = "he said \\"hi\\""\n')
    assert "escape sequence" in str(exc.value)


def test_dotted_key_is_refused_not_flattened():
    """`a.b = 1` is a nested table; reading it flat gave {"a.b": 1} on 3.10."""
    with pytest.raises(C.ConfigError) as exc:
        C._parse_toml_subset("[tool.fiducial]\na.b = 1\n")
    assert "dotted key" in str(exc.value)


def test_load_toml_actually_reaches_the_fallback_on_310(tmp_path, monkeypatch):
    """The dispatch itself, not just the parser it dispatches to.

    Every other test here calls `_parse_toml_subset` directly, which proves the
    parser works but says nothing about whether `load_toml` ever calls it. On
    this machine (3.13) the tomllib branch always wins, so without this test
    the 3.10 path is code that is tested and never wired -- the exact shape of
    failure this package's own ledger keeps recording.
    """
    p = tmp_path / ".fiducial.toml"
    p.write_text('keys = ["eta"]\n', encoding="utf-8")

    calls = []
    real = C._parse_toml_subset
    monkeypatch.setattr(
        C, "_parse_toml_subset",
        lambda text, **kw: (calls.append((text, kw)), real(text, **kw))[1],
    )
    monkeypatch.setattr(C.sys, "version_info", (3, 10, 0, "final", 0))

    assert C.load_toml(p) == {"keys": ["eta"]}
    assert calls, "load_toml did not use the fallback on a 3.10 interpreter"


def test_load_toml_prefers_tomllib_when_it_exists(tmp_path, monkeypatch):
    """And the converse: on 3.11+ the fallback must NOT be doing the work."""
    if sys.version_info < (3, 11):
        pytest.skip("no tomllib on this interpreter")
    p = tmp_path / ".fiducial.toml"
    p.write_text('keys = ["eta"]\n', encoding="utf-8")

    def _boom(text, **kw):
        raise AssertionError("fallback used although tomllib is available")

    monkeypatch.setattr(C, "_parse_toml_subset", _boom)
    assert C.load_toml(p) == {"keys": ["eta"]}


def test_a_literal_string_with_a_backslash_still_works():
    """The refusal must not swallow the legitimate case it neighbours.

    Windows paths are the reason: `'C:\\x'` in single quotes is a TOML literal
    string, where a backslash is just a backslash, and both readers agree.
    """
    got = C._parse_toml_subset("[tool.fiducial]\nspec = 'C:\\x\\y.yaml'\n")
    assert got["tool"]["fiducial"]["spec"] == "C:\\x\\y.yaml"


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_no_config_anywhere_is_defaults_not_an_error(tmp_path):
    cfg = C.load(start=tmp_path)
    assert cfg.path is None
    assert cfg.names_mode == "set"
    assert cfg.keys == ()


def test_reads_tool_table_from_pyproject(tmp_path):
    _write(tmp_path, "pyproject.toml",
           '[project]\nname = "x"\n\n[tool.fiducial]\nkeys = ["eta"]\n')
    cfg = C.load(start=tmp_path)
    assert cfg.keys == ("eta",)
    assert cfg.path is not None and cfg.path.name == "pyproject.toml"


def test_pyproject_without_our_table_is_skipped_not_claimed(tmp_path):
    """A pyproject that does not configure us must not stop the search.

    In a monorepo the nearest pyproject is frequently some other package's.
    Stopping there would silently apply defaults while the real config sits one
    directory up.
    """
    (tmp_path / "pkg").mkdir()
    _write(tmp_path, "pyproject.toml", '[tool.fiducial]\nkeys = ["outer"]\n')
    _write(tmp_path / "pkg", "pyproject.toml", '[project]\nname = "inner"\n')
    cfg = C.load(start=tmp_path / "pkg")
    assert cfg.keys == ("outer",)


def test_standalone_file_for_a_repo_with_no_pyproject(tmp_path):
    _write(tmp_path, ".fiducial.toml", 'docs_paths = ["docs/"]\ntol = 0.05\n')
    cfg = C.load(start=tmp_path)
    assert cfg.docs_paths == ("docs/",)
    assert cfg.tol == 0.05


def test_unparseable_config_raises_rather_than_falling_back_to_defaults(tmp_path):
    """The failure mode that matters: settings silently not in force.

    Falling back to defaults here would run the checks with the wrong tuning
    while reporting success.
    """
    _write(tmp_path, ".fiducial.toml", "this is not toml at all\n")
    with pytest.raises(C.ConfigError):
        C.load(start=tmp_path)


# --------------------------------------------------------------------------
# a typo must not be silent
# --------------------------------------------------------------------------

def test_unknown_key_is_reported_not_ignored(tmp_path):
    _write(tmp_path, ".fiducial.toml", 'kyes = ["eta"]\nnames_mode = "strict"\n')
    cfg = C.load(start=tmp_path)
    assert cfg.unknown == ("kyes",)
    assert cfg.keys == ()             # the typo did NOT take effect
    assert cfg.names_mode == "strict"  # the valid key still did


def test_hyphenated_keys_are_accepted(tmp_path):
    """ruff-style `extend-select` spelling, since that is what people type."""
    _write(tmp_path, ".fiducial.toml", 'extend-self-declaring-keys = ["fit_id"]\n')
    cfg = C.load(start=tmp_path)
    assert cfg.extend_self_declaring_keys == frozenset({"fit_id"})
    assert cfg.unknown == ()


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    'names_mode = "loose"\n',
    'coverage_level = "everything"\n',
    'rules = ["names", "spelling"]\n',
])
def test_invalid_enum_values_raise(tmp_path, body):
    _write(tmp_path, ".fiducial.toml", body)
    with pytest.raises(C.ConfigError):
        C.load(start=tmp_path)


def test_wrong_type_raises(tmp_path):
    _write(tmp_path, ".fiducial.toml", 'keys = "eta"\n')
    with pytest.raises(C.ConfigError):
        C.load(start=tmp_path)


# --------------------------------------------------------------------------
# extend vs replace
# --------------------------------------------------------------------------

DEFAULT = frozenset({"a", "b", "c"})


def test_extend_keeps_the_defaults():
    assert C.resolve_set(DEFAULT, None, frozenset({"d"})) == frozenset({"a", "b", "c", "d"})


def test_replace_drops_the_defaults():
    assert C.resolve_set(DEFAULT, frozenset({"z"}), frozenset()) == frozenset({"z"})


def test_replace_and_extend_compose():
    assert C.resolve_set(DEFAULT, frozenset({"z"}), frozenset({"y"})) == frozenset({"z", "y"})


def test_neither_leaves_the_default_untouched():
    assert C.resolve_set(DEFAULT, None, frozenset()) == DEFAULT


def test_the_fallback_ignores_tables_that_are_not_ours(tmp_path):
    """A `pyproject.toml` belongs to the project, not to fiducial.

    Found 260923 by the first CI run on 3.10, against THIS package's own
    `pyproject.toml`:

        license = { text = "MIT" }
        -> ConfigError: cannot read '{ text = "MIT" }' as a TOML value

    An inline table is legal TOML the fallback does not implement. Refusing it
    inside `[tool.fiducial]` is right -- a setting must never be silently
    dropped. But `license` sits in `[project]`, fiducial never reads it, and
    refusing it made the tool unusable on 3.10 in any project whose pyproject
    uses an inline table anywhere, which is most of them.
    """
    body = (
        '[project]\n'
        'name = "x"\n'
        'license = { text = "MIT" }\n'
        'authors = [{ name = "A", email = "a@b.c" }]\n'
        '\n'
        '[tool.other]\n'
        'nested = { deep = { deeper = 1 } }\n'
        '\n'
        '[tool.fiducial]\n'
        'keys = ["eta"]\n'
    )
    got = C._parse_toml_subset(body, only="tool.fiducial")
    assert got["tool"]["fiducial"]["keys"] == ["eta"]

    # And it is genuinely the narrowing doing the work, not a lucky parse.
    with pytest.raises(C.ConfigError):
        C._parse_toml_subset(body)


def test_narrowing_does_not_relax_our_own_table(tmp_path):
    """Inside `[tool.fiducial]` the parser is as strict as it ever was.

    This is the property that makes the narrowing safe: it changes which lines
    are read, never how strictly a fiducial setting is judged.
    """
    body = (
        '[project]\n'
        'license = { text = "MIT" }\n'
        '\n'
        '[tool.fiducial]\n'
        'keys = { inline = "table" }\n'
    )
    with pytest.raises(C.ConfigError) as exc:
        C._parse_toml_subset(body, only="tool.fiducial")
    assert "cannot read" in str(exc.value)


def test_a_standalone_config_is_narrowed_to_nothing(tmp_path):
    """`.fiducial.toml` is entirely ours, so nothing there is excused."""
    p = _write(tmp_path, ".fiducial.toml", 'keys = { inline = "table" }\n')
    assert C._scope_for(p) is None
    with pytest.raises(C.ConfigError):
        C._parse_toml_subset(p.read_text(encoding="utf-8"), only=C._scope_for(p))


def test_this_repos_own_pyproject_loads_on_the_310_path():
    """The end-to-end case CI actually failed on."""
    root = Path(__file__).resolve().parents[1]
    p = root / "pyproject.toml"
    got = C._parse_toml_subset(p.read_text(encoding="utf-8"), only=C._scope_for(p))
    assert "rules" in got["tool"]["fiducial"]

"""Enough YAML to resolve pointers in an index, and not one line more.

Why a parser at all
-------------------
Rule (5) reads indexes. The largest public corpus of them this package has been
tried against -- 35 PEtab benchmark models -- writes its index in YAML, not
JSON, so a JSON-only rule cannot see a single one of them.

`PyYAML` would solve it in a line. This package ships zero dependencies, which
is what lets a project adopt it without a conversation about its supply chain,
and the shape actually needed here is small and fixed::

    format_version: 1
    parameter_file: parameters_X.tsv
    problems:
    - condition_files:
      - experimentalCondition_X.tsv
      sbml_files:
      - model_X.xml

Scalars, lists of scalars, mappings, and lists of mappings, nested no deeper
than the corpus goes (measured: two levels, across all 35 models).

Deliberately loud, deliberately narrow
--------------------------------------
Every construct outside that subset raises rather than parsing to something
approximate: anchors, aliases, multi-line scalars, flow collections, tags,
multiple documents. The same reasoning as the 3.10 TOML fallback in
`config.py` -- a parser that quietly half-understands an index hands back
pointers that were never checked, and the caller believes they were.

That refusal is safe here in a way it would not be for a general YAML reader,
because this parser has one job: find the strings that name files. An index
this cannot read is reported as unreadable, which rule (5) already treats as
`cannot_check` rather than clean.

What it does NOT try to be
--------------------------
Not a YAML implementation. It does not resolve types beyond int/float/bool/
null, does not preserve key order guarantees beyond insertion, and has no
opinion on duplicate keys beyond last-wins. If a project needs more, it should
hand rule (5) JSON, or the rule should grow a real dependency and say so.
"""

from __future__ import annotations

import re
from typing import Any


class YamlError(ValueError):
    """The document exists but this reader will not guess at it."""


#: Constructs this reader refuses rather than approximating. Each one changes
#: what a document MEANS, so silently skipping the line would hand back an
#: index whose pointers were never the ones written.
_REFUSED = (
    (re.compile(r"(?<!\S)[&*]\w"), "anchors and aliases"),
    (re.compile(r":\s*[|>]\s*$"), "block scalars"),
    (re.compile(r"^\s*---\s*$", re.M), "multiple documents"),
    (re.compile(r"(?<!\S)!!?\w"), "explicit tags"),
)

_KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<dash>-\s+)?(?P<key>[^:#]+?)\s*:\s*(?P<val>.*)$")
_ITEM_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<val>.+?)\s*$")


def _scalar(text: str) -> Any:
    text = text.strip()
    if not text or text in ("~", "null", "Null", "NULL"):
        return None
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in ("true", "True", "TRUE", "yes", "on"):
        return True
    if text in ("false", "False", "FALSE", "no", "off"):
        return False
    if text[0] in "[{":
        raise YamlError(
            f"flow collection {text!r}. This reader handles block style only; "
            "write the list or mapping across lines, or hand rule (5) JSON."
        )
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def loads(text: str) -> Any:
    """Parse the block-style subset. Raise on anything richer.

    Comments and blank lines are dropped first; a `#` inside a quoted scalar is
    left alone, because a filename may legitimately contain one.
    """
    for pattern, what in _REFUSED:
        if pattern.search(text):
            raise YamlError(
                f"{what} are not supported by this reader. It covers the block "
                "subset an index needs; anything richer should be handed to "
                "rule (5) as JSON."
            )

    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if line.strip():
            lines.append((len(line) - len(line.lstrip()), line.strip()))

    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise YamlError(
            f"could not read line {index + 1}: {lines[index][1]!r}. The "
            "document's indentation does not nest consistently."
        )
    return value


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def _parse_block(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[Any, int]:
    """One block at ``indent``: a sequence if it opens with `-`, else a mapping."""
    if i < len(lines) and lines[i][1].startswith("- "):
        return _parse_sequence(lines, i, indent)
    return _parse_mapping(lines, i, indent)


def _parse_mapping(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[dict, int]:
    out: dict[str, Any] = {}
    while i < len(lines):
        col, text = lines[i]
        if col < indent:
            break
        if col > indent:
            raise YamlError(f"unexpected indentation at {text!r}")
        m = _KEY_RE.match(text)
        if not m:
            raise YamlError(
                f"cannot read {text!r} as `key: value`. This reader covers the "
                "block subset an index needs."
            )
        key = m.group("key").strip().strip('"').strip("'")
        raw = m.group("val").strip()
        i += 1
        if raw:
            out[key] = _scalar(raw)
            continue
        # The value is whatever follows at a deeper indent -- or, for a
        # sequence, at the SAME indent, which is legal YAML and is how 29 of
        # the 35 PEtab models write their file lists.
        if i < len(lines) and (
            lines[i][0] > indent
            or (lines[i][0] == indent and lines[i][1].startswith("- "))
        ):
            out[key], i = _parse_block(lines, i, lines[i][0])
        else:
            out[key] = None
    return out, i


def _parse_sequence(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[list, int]:
    out: list[Any] = []
    while i < len(lines):
        col, text = lines[i]
        if col < indent or not text.startswith("- "):
            break
        if col > indent:
            raise YamlError(f"unexpected indentation at {text!r}")
        body = text[2:].strip()
        # `- key: value` opens a mapping whose first key sits on the dash line.
        if _KEY_RE.match(body) and not _looks_like_scalar_with_colon(body):
            inner_indent = col + 2
            rebuilt = [(inner_indent, body)] + lines[i + 1:]
            value, consumed = _parse_mapping(rebuilt, 0, inner_indent)
            out.append(value)
            i = i + 1 + (consumed - 1)
            continue
        out.append(_scalar(body))
        i += 1
    return out, i


def _looks_like_scalar_with_colon(body: str) -> bool:
    """`- http://x` is a scalar; `- key: value` is a mapping.

    A colon only opens a mapping when a space follows it. That is YAML's own
    rule, and without it a filename or URL containing `:` is read as a key.
    """
    m = re.match(r"^[^:]+:(?P<after>.?)", body)
    return bool(m) and m.group("after") not in ("", " ")

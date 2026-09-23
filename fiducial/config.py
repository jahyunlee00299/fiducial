"""Project configuration: `[tool.fiducial]` in ``pyproject.toml``.

Why a config file at all
------------------------
Every rule here was tuned against one corpus, and the tuning is visible in the
argument list: ``literals`` refuses to run without ``--keys``, ``coverage``
requires ``--spec``, and the lists that decide what counts as prose, as a
pointer to another artefact, or as a neutral default are module constants named
after the project they were measured on.

A second project cannot pass those on the command line every time and will not
edit the package to change them.  A tool that must be re-argued on every
invocation is a tool that gets invoked once.

So the settings live next to the code they describe, in the file a Python
project already has.  ``[tool.fiducial]`` follows the convention ruff, black,
mypy and pytest all use; a project with no ``pyproject.toml`` can use a
standalone ``.fiducial.toml`` instead.

Extend, do not replace
----------------------
Every tuned list is exposed twice:

    self_declaring_keys         -- replace the default outright
    extend_self_declaring_keys  -- add to it, keeping the defaults

The ``extend_`` prefix is ruff's convention (``extend-select``) and it exists
because replacement is the wrong default for adoption: a project that wants to
add one field name should not have to re-type seven, and silently losing the
other six is the kind of surprise that gets a checker switched off.

Reading TOML without a dependency
---------------------------------
``tomllib`` is stdlib from 3.11.  This package supports 3.10, where it is not,
and the core claims zero dependencies -- so on 3.10 a small reader handles the
subset this config actually uses: a table header, ``key = value``, strings,
integers, floats, booleans, and single- or multi-line arrays of those.

That reader is deliberately narrow and deliberately loud.  It raises on any
line it does not understand rather than skipping it, because a config parser
that silently drops a setting hands the user a check they believe is configured
and is not -- the same false evidence this package exists to remove.  Anything
richer than the subset should either be simplified or read on 3.11+.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """The configuration exists but cannot be used.

    Never downgraded to a warning.  A config that fails to load leaves the
    defaults in place while the author believes their settings are active,
    which is worse than having no config at all.
    """


# --------------------------------------------------------------------------
# TOML
# --------------------------------------------------------------------------

_KEY_VALUE_RE = re.compile(r"^([A-Za-z_][\w.-]*)\s*=\s*(.+)$")
_TABLE_RE = re.compile(r"^\[([^\]]+)\]$")


def _strip_comment(line: str) -> str:
    """Drop a trailing `#` comment that is not inside a string."""
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
    return "".join(out).strip()


def _scalar(text: str) -> Any:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        body = text[1:-1]
        # A basic string may contain TOML escapes (`\"`, `\\`, `\n`, `\uXXXX`).
        # Measured against tomllib: returning the raw slice made
        # `"he said \"hi\""` parse as `he said \"hi\"` on 3.10 and
        # `he said "hi"` on 3.13 -- the same config meaning two things
        # depending on the interpreter, which is the one outcome a fallback
        # reader must never produce. Refuse instead of guessing.
        if text[0] == '"' and "\\" in body:
            raise ConfigError(
                f"escape sequence in {text!r}. The Python 3.10 fallback reader "
                "does not implement TOML string escapes, and decoding them "
                "wrongly would make this config mean one thing on 3.10 and "
                "another on 3.11+. Use a literal string ('single quotes'), or "
                "run on 3.11+ where stdlib tomllib is used."
            )
        return body
    if text in ("true", "false"):
        return text == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    raise ConfigError(
        f"cannot read {text!r} as a TOML value. This fallback reader handles "
        "strings, integers, floats, booleans and arrays of those. Simplify the "
        "value, or run on Python 3.11+ where the stdlib tomllib is used instead."
    )


def _array(text: str) -> list[Any]:
    inner = text.strip()[1:-1].strip()
    if not inner:
        return []
    items, buf, quote = [], [], None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            items.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if "".join(buf).strip():
        items.append("".join(buf))
    return [_scalar(i) for i in items if i.strip()]


def _parse_toml_subset(text: str, *, only: str | None = None) -> dict[str, Any]:
    """Enough TOML for `[tool.fiducial]`. Raises on anything else.

    Used only on Python 3.10, where `tomllib` does not exist and the package
    carries no dependencies. Every unrecognised line raises: a parser that
    skips what it does not understand produces a config the author believes is
    in force and is not.

    ``only`` narrows that strictness to one table, and exists because the
    strictness was aimed at the wrong thing. Measured 260923 in CI on 3.10,
    against this package's *own* `pyproject.toml`:

        license = { text = "MIT" }
        -> ConfigError: cannot read '{ text = "MIT" }' as a TOML value

    An inline table is legal TOML the fallback does not implement, and refusing
    it is right *for a fiducial setting* -- the author would otherwise
    believe a setting was in force. But `license` is not a fiducial setting.
    It sits in `[project]`, fiducial never reads it, and refusing it makes
    the tool unusable on 3.10 in any project whose `pyproject.toml` uses an
    inline table anywhere. That is a barrier to adoption produced by strictness
    pointed outside its own scope.

    So with ``only`` set, values outside that table are not parsed at all --
    not skipped after a failed attempt, but never read, because their content
    is none of this parser's business. Inside the table nothing changes: every
    unparseable line still raises. Table *headers* are always parsed, since
    that is how the target table is found.
    """
    data: dict[str, Any] = {}
    table: dict[str, Any] = data
    pending_key: str | None = None
    pending_buf: list[str] = []
    #: None means "no narrowing"; otherwise, whether the current table is the
    #: one we were asked about. Top-of-file keys (before any header) are
    #: outside it by definition.
    in_scope = True if only is None else False

    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line:
            continue

        if pending_key is not None:                 # inside a multi-line array
            pending_buf.append(line)
            joined = " ".join(pending_buf)
            if joined.count("[") <= joined.count("]"):
                table[pending_key] = _array(joined)
                pending_key, pending_buf = None, []
            continue

        m = _TABLE_RE.match(line)
        if m:
            name = ".".join(
                p.strip().strip('"').strip("'") for p in m.group(1).split(".")
            )
            in_scope = True if only is None else name == only
            table = data
            for part in m.group(1).split("."):
                part = part.strip().strip('"').strip("'")
                table = table.setdefault(part, {})
                if not isinstance(table, dict):
                    raise ConfigError(f"[{m.group(1)}] collides with a value")
            continue

        if not in_scope:
            # Outside the table we were asked about. Not this parser's
            # business, so it is not read -- see the note on ``only``.
            continue

        m = _KEY_VALUE_RE.match(line)
        if not m:
            raise ConfigError(
                f"cannot parse TOML line: {raw.strip()!r}. This is the Python "
                "3.10 fallback reader, which handles only `key = value` and "
                "`[table]`. It refuses rather than skipping, so that a setting "
                "is never silently dropped."
            )
        key, value = m.group(1), m.group(2).strip()
        if "." in key:
            # `a.b = 1` is a nested table in TOML, not a key named "a.b".
            # Measured against tomllib: the flat reading produced
            # {"a.b": 1} on 3.10 against {"a": {"b": 1}} on 3.13. fiducial
            # has no nested settings, so this is refused rather than
            # implemented -- an unused shape is not worth a second way to
            # disagree with the real parser.
            raise ConfigError(
                f"dotted key {key!r}. The Python 3.10 fallback reader does not "
                "implement nested tables, and reading this as a flat key would "
                "disagree with stdlib tomllib on 3.11+. No fiducial setting "
                "is nested, so write it as a plain key."
            )
        if value.startswith("["):
            if value.count("[") <= value.count("]"):
                table[key] = _array(value)
            else:
                pending_key, pending_buf = key, [value]
            continue
        table[key] = _scalar(value)

    if pending_key is not None:
        raise ConfigError(f"unterminated array for key {pending_key!r}")
    return data


def load_toml(path: Path, *, only: str | None = None) -> dict[str, Any]:
    """Parse ``path`` with stdlib ``tomllib``, or the 3.10 fallback.

    ``only`` is honoured by the fallback alone: ``tomllib`` parses the whole
    document correctly anyway, so narrowing it would change nothing except to
    make the two paths disagree. The narrowing exists to stop the *fallback*
    refusing valid TOML it does not implement, in parts of the file fiducial
    never reads.
    """
    raw = path.read_bytes()
    if sys.version_info >= (3, 11):
        import tomllib

        try:
            return tomllib.loads(raw.decode("utf-8"))
        except Exception as exc:                     # tomllib.TOMLDecodeError
            raise ConfigError(f"{path}: {exc}") from exc
    return _parse_toml_subset(raw.decode("utf-8"), only=only)


# --------------------------------------------------------------------------
# the settings themselves
# --------------------------------------------------------------------------

#: Filenames searched, in order. `pyproject.toml` first because that is where a
#: Python project's tool settings already live; the standalone file is for a
#: repo that has no pyproject (a docs-only or config-only repo still wants
#: rules (2) and (4)).
CONFIG_NAMES = ("pyproject.toml", ".fiducial.toml")


@dataclass(frozen=True)
class Config:
    """Resolved settings. Every field has a working default."""

    path: Path | None = None            # where these came from, for messages

    # rule (1)
    keys: tuple[str, ...] = ()
    include_neutral: bool = False
    neutral_defaults: tuple[float, ...] | None = None
    literals_paths: tuple[str, ...] = ()

    # rule (2)
    names_mode: str = "set"
    self_declaring_keys: frozenset[str] | None = None
    extend_self_declaring_keys: frozenset[str] = frozenset()
    prose_keys: frozenset[str] | None = None
    extend_prose_keys: frozenset[str] = frozenset()
    reference_keys: frozenset[str] | None = None
    extend_reference_keys: frozenset[str] = frozenset()
    names_paths: tuple[str, ...] = ()
    #: Accept "files read, none comparable" as a pass. Off by default:
    #: that state means the rule checked nothing, and reporting it as
    #: clean is the pass this package refuses everywhere else.
    names_allow_zero_comparable: bool = False

    # rule (3)
    spec: str | None = None
    spec_field: str = "learnable_keys"
    waiver_field: str = "coverage_waivers"
    coverage_level: str = "absent"
    baseline: str | None = None
    tests_paths: tuple[str, ...] = ()
    data_paths: tuple[str, ...] = ()

    # rule (4)
    docs_paths: tuple[str, ...] = ()
    docs_root: str | None = None
    tol: float = 0.0
    strict_gaps: bool = False
    locales: tuple[str, ...] = ()
    extend_history_markers: tuple[str, ...] = ()

    # rule (5)
    pointers_paths: tuple[str, ...] = ()
    #: Directory the index's file pointers resolve against. Default (unset) is
    #: the index file's own directory, which is what a loader reading that
    #: index does. Set it only for an index whose paths are relative to a
    #: project root instead.
    pointers_root: str | None = None
    file_keys: frozenset[str] | None = None
    extend_file_keys: frozenset[str] = frozenset()
    id_keys: frozenset[str] | None = None
    extend_id_keys: frozenset[str] = frozenset()

    # which rules `fiducial check` runs
    rules: tuple[str, ...] = ()

    unknown: tuple[str, ...] = field(default=())


_STR_LIST_FIELDS = {
    "keys", "literals_paths", "names_paths", "tests_paths", "data_paths",
    "docs_paths", "rules", "locales", "extend_history_markers",
    "pointers_paths",
}
_SET_FIELDS = {
    "self_declaring_keys", "extend_self_declaring_keys",
    "prose_keys", "extend_prose_keys",
    "reference_keys", "extend_reference_keys",
    "file_keys", "extend_file_keys",
    "id_keys", "extend_id_keys",
}
_BOOL_FIELDS = {"include_neutral", "strict_gaps", "names_allow_zero_comparable"}
_FLOAT_FIELDS = {"tol"}
_STR_FIELDS = {
    "names_mode", "spec", "spec_field", "waiver_field", "coverage_level",
    "baseline", "docs_root",
}


def find_config(start: Path | None = None) -> Path | None:
    """The nearest config at or above ``start``.

    A `pyproject.toml` with no `[tool.fiducial]` table does not count -- the
    search continues upward, so a package inside a monorepo finds the config
    that actually configures it rather than stopping at the first pyproject.
    """
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        for name in CONFIG_NAMES:
            candidate = directory / name
            if not candidate.is_file():
                continue
            try:
                data = load_toml(candidate, only=_scope_for(candidate))
            except ConfigError:
                # A config we cannot parse is still THIS project's config.
                # Returning it lets `load()` raise with the real reason instead
                # of silently falling through to defaults.
                return candidate
            if _table_of(data, candidate) is not None:
                return candidate
    return None


def _scope_for(path: Path) -> str | None:
    """Which table the 3.10 fallback should read, or None for the whole file.

    `pyproject.toml` belongs to the project, not to fiducial: it carries
    `[project]`, `[build-system]` and whatever other tools live there, and
    those may legally use TOML the fallback does not implement. Only
    `[tool.fiducial]` is ours to be strict about.

    A `.fiducial.toml` is entirely ours, so nothing is narrowed there and an
    unparseable line still refuses -- which is the point of the fallback.
    """
    return "tool.fiducial" if path.name == "pyproject.toml" else None


def _table_of(data: dict[str, Any], path: Path) -> dict[str, Any] | None:
    if path.name == "pyproject.toml":
        tool = data.get("tool")
        if isinstance(tool, dict) and isinstance(tool.get("fiducial"), dict):
            return tool["fiducial"]
        return None
    return data if isinstance(data, dict) else None


def load(path: Path | None = None, start: Path | None = None) -> Config:
    """Read a `Config`, or the all-defaults one when no config exists.

    An unknown key is collected into `Config.unknown` rather than ignored. The
    CLI prints those: a typo in a setting name otherwise leaves the default in
    force while the author believes they changed it, which is exactly the
    silent-miscalibration failure the rules themselves are about.
    """
    if path is None:
        path = find_config(start)
    if path is None:
        return Config()

    data = load_toml(path, only=_scope_for(path))
    table = _table_of(data, path)
    if table is None:
        raise ConfigError(
            f"{path} has no [tool.fiducial] table. Add one, or point at a "
            ".fiducial.toml."
        )

    kwargs: dict[str, Any] = {"path": path}
    unknown: list[str] = []
    valid = {f.name for f in Config.__dataclass_fields__.values()} - {"path", "unknown"}

    for raw_key, value in table.items():
        key = raw_key.replace("-", "_")          # accept ruff-style hyphens
        if key not in valid:
            unknown.append(raw_key)
            continue
        try:
            kwargs[key] = _coerce(key, value)
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError(f"{path}: bad value for {raw_key!r}: {exc}") from exc

    kwargs["unknown"] = tuple(sorted(unknown))
    cfg = Config(**kwargs)
    _validate(cfg, path)
    return cfg


def _coerce(key: str, value: Any) -> Any:
    if key in _SET_FIELDS:
        if not isinstance(value, list):
            raise ConfigError(f"{key} must be an array of strings")
        return frozenset(str(v) for v in value)
    if key in _STR_LIST_FIELDS:
        if not isinstance(value, list):
            raise ConfigError(f"{key} must be an array of strings")
        return tuple(str(v) for v in value)
    if key == "neutral_defaults":
        if not isinstance(value, list):
            raise ConfigError("neutral_defaults must be an array of numbers")
        return tuple(float(v) for v in value)
    if key in _BOOL_FIELDS:
        if not isinstance(value, bool):
            raise ConfigError(f"{key} must be true or false")
        return value
    if key in _FLOAT_FIELDS:
        return float(value)
    if key in _STR_FIELDS:
        return str(value)
    return value


_KNOWN_RULES = ("literals", "names", "coverage", "docs", "pointers")


def _validate(cfg: Config, path: Path) -> None:
    if cfg.names_mode not in ("strict", "set"):
        raise ConfigError(
            f"{path}: names_mode must be 'strict' or 'set', got {cfg.names_mode!r}"
        )
    if cfg.coverage_level not in ("absent", "mentioned"):
        raise ConfigError(
            f"{path}: coverage_level must be 'absent' or 'mentioned', "
            f"got {cfg.coverage_level!r}"
        )
    bad = [r for r in cfg.rules if r not in _KNOWN_RULES]
    if bad:
        raise ConfigError(
            f"{path}: unknown rule(s) {bad}. Known rules: {list(_KNOWN_RULES)}"
        )


def resolve_set(
    default: frozenset[str],
    replace: frozenset[str] | None,
    extend: frozenset[str],
) -> frozenset[str]:
    """Apply the replace/extend pair to one tuned default.

    `replace` wins outright when given; `extend` adds to whichever base is in
    force. Both together are meaningful: replace the default list, then add to
    the replacement.
    """
    base = default if replace is None else replace
    return base | extend

"""One-line "newer version on PyPI" notice. Never changes an exit code, never raises.

Silent unless stderr is a terminal (so pre-commit, CI and pipes are untouched).
Off switches: NO_UPDATE_CHECK=1, CI set. One network probe per 24 h, cached (failures too).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

_TTL_S = 24 * 3600
_TIMEOUT_S = 1.0


def _release(v: str) -> tuple[int, ...]:
    m = re.match(r"\d+(?:\.\d+)*", v)
    return tuple(int(p) for p in m.group(0).split(".")) if m else ()


def _cache_file(dist: str) -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "verification-gates" / f"{dist}.json"


def _latest(dist: str) -> str | None:
    f = _cache_file(dist)
    try:
        c = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - c["t"] < _TTL_S:
            return c["v"]
    except (OSError, ValueError, KeyError):
        pass
    v = None
    try:
        url = f"https://pypi.org/pypi/{dist}/json"
        with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as r:
            v = json.load(r)["info"]["version"]
    except Exception:  # offline, 404 (not on PyPI), bad JSON: all silent
        pass
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"t": time.time(), "v": v}), encoding="utf-8")
    except OSError:
        pass
    return v


def notify(dist: str, current: str) -> None:
    try:
        if os.environ.get("NO_UPDATE_CHECK") or os.environ.get("CI"):
            return
        if not sys.stderr.isatty():
            return
        latest = _latest(dist)
        if latest and _release(latest) > _release(current):
            print(
                f"note: {dist} {latest} is available (you have {current}). "
                f"Upgrade: pip install -U {dist}  |  uvx {dist}@latest",
                file=sys.stderr,
            )
    except Exception:
        pass

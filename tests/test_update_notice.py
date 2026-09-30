import io
import json
import time

import pytest

from fiducial import _update_notice as un


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv("NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("CI", raising=False)


class _Tty(io.StringIO):
    def isatty(self):
        return True


def _seed(tmp_path, dist, v, age=0):
    f = un._cache_file(dist)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"t": time.time() - age, "v": v}))


def test_prints_when_newer(tmp_path, monkeypatch):
    err = _Tty()
    monkeypatch.setattr("sys.stderr", err)
    _seed(tmp_path, "d", "9.9.9")
    un.notify("d", "0.1.0")
    assert "9.9.9" in err.getvalue() and "pip install -U d" in err.getvalue()


def test_silent_when_current_or_older(tmp_path, monkeypatch):
    err = _Tty()
    monkeypatch.setattr("sys.stderr", err)
    _seed(tmp_path, "d", "0.1.0")
    un.notify("d", "0.1.0")
    un.notify("d", "0.2.0")
    assert err.getvalue() == ""


def test_silent_when_not_tty_or_disabled(tmp_path, monkeypatch):
    _seed(tmp_path, "d", "9.9.9")
    err = io.StringIO()
    monkeypatch.setattr("sys.stderr", err)
    un.notify("d", "0.1.0")
    err2 = _Tty()
    monkeypatch.setattr("sys.stderr", err2)
    monkeypatch.setenv("NO_UPDATE_CHECK", "1")
    un.notify("d", "0.1.0")
    monkeypatch.delenv("NO_UPDATE_CHECK")
    monkeypatch.setenv("CI", "true")
    un.notify("d", "0.1.0")
    assert err.getvalue() == "" and err2.getvalue() == ""


def test_network_failure_is_silent_and_negative_cached(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(un.urllib.request, "urlopen", boom)
    err = _Tty()
    monkeypatch.setattr("sys.stderr", err)
    un.notify("d", "0.1.0")
    assert err.getvalue() == ""
    assert json.loads(un._cache_file("d").read_text())["v"] is None


def test_stale_cache_refetches(tmp_path, monkeypatch):
    _seed(tmp_path, "d", "0.1.0", age=un._TTL_S + 5)

    class R(io.StringIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        un.urllib.request, "urlopen",
        lambda *a, **k: R(json.dumps({"info": {"version": "3.0.0"}})),
    )
    assert un._latest("d") == "3.0.0"

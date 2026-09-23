"""rule (1) on foreign code: other containers, other spellings.

Measured 260923 against public research repositories. The rule was built on
one codebase whose measured quantities are module names and attributes. Other
projects keep the same number in a dict, pass it as a keyword, default it in a
signature, and spell one quantity many ways (`k_17`, `kcat_f`, `Titer_gL`).
The ground-truth case is Bioindustrial-Park commit 6001ed0ef5, where the
author corrected `k_ref.setdefault('k_17', 44.0)` to the live 0.1077.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fiducial.literals import KeyMatcher, scan_source


def scan(src, keys=("eta",), **kw):
    return scan_source(Path("m.py"), src, keys, **kw)


def shape(found):
    return [(f.kind, f.key) for f in found]


# --------------------------------------------------------------------------
# containers
# --------------------------------------------------------------------------

@pytest.mark.parametrize("src, kind", [
    ("params['eta'] = 0.87\n", "bare_literal"),          # was a documented no-op
    ("self.p['eta'] = 0.87\n", "bare_literal"),
    ("params = {'eta': 0.87}\n", "bare_literal"),
    ("params = dict(eta=0.87)\n", "bare_literal"),
    ("def f(eta=0.87): pass\n", "silent_fallback"),
    ("def f(*, eta=0.87): pass\n", "silent_fallback"),
    ("async def f(eta=0.87): pass\n", "silent_fallback"),
    ("class M:\n    def __init__(self, x, eta=-0.3): pass\n", "silent_fallback"),
])
def test_every_container_is_caught_once(src, kind):
    assert shape(scan(src)) == [(kind, "eta")]


@pytest.mark.parametrize("src", [
    "params['eta'] = compute()\n",
    "params = {'eta': compute()}\n",
    "run(model, eta=measured.eta)\n",
    "def f(eta=None): pass\n",
    "def f(eta): pass\n",
    "params = {'timeout': 30.5}\n",
    "run(timeout=30.5)\n",
    "params = {'eta': 1}\n",          # unremarkable number
    "params = {**base}\n",            # dict unpacking has a None key
])
def test_no_literal_or_no_declared_key_is_clean(src):
    assert scan(src) == []


def test_signature_neutral_default_follows_the_neutral_split():
    assert scan("def f(eta=1.0): pass\n") == []
    found = scan("def f(eta=1.0): pass\n", include_neutral=True)
    assert shape(found) == [("silent_fallback", "eta")] and found[0].neutral


def test_findings_point_at_the_value_line():
    found = scan("params = {\n    'a': 3,\n    'eta': 0.87,\n}\n")
    assert [f.line for f in found] == [3]


# --------------------------------------------------------------------------
# spellings
# --------------------------------------------------------------------------

def test_the_ground_truth_case_needs_no_advance_knowledge_of_the_name():
    src = "k_ref.setdefault('k_17', 44.0)\n"
    assert scan(src, keys=("kcat",)) == []                 # exact name unknown
    assert shape(scan(src, keys=("k_*",))) == [("silent_fallback", "k_17")]


@pytest.mark.parametrize("name", ["titer", "Titer", "titer_gL", "final_TITER"])
def test_a_pattern_matches_case_insensitively(name):
    assert shape(scan(f"{name} = 68.5\n", keys=("*titer*",))) == [
        ("bare_literal", name)]


def test_an_exact_key_stays_exact():
    """Unchanged semantics for existing declarations: `eta` is not `Eta`."""
    assert scan("Eta = 0.87\n", keys=("eta",)) == []
    assert scan("eta_hat = 0.87\n", keys=("eta",)) == []


def test_pattern_and_exact_compose():
    src = "eta = 0.87\nkcat_r6 = 12.5\ntimeout = 30.5\n"
    assert shape(scan(src, keys=("eta", "kcat*"))) == [
        ("bare_literal", "eta"), ("bare_literal", "kcat_r6")]


def test_a_matcher_of_nothing_is_falsy_so_the_empty_refusal_holds():
    assert not KeyMatcher([])
    assert not KeyMatcher([""])
    with pytest.raises(ValueError):
        scan("eta = 0.87\n", keys=[""])


# --------------------------------------------------------------------------
# keyword arguments belong to the callee
# --------------------------------------------------------------------------

def test_a_callees_keyword_is_not_the_projects_parameter_by_default():
    """pymoo's SBX(eta=15) is a distribution index, not the effectiveness
    factor. Measured on the reference codebase: reading every call's keywords
    took `eta,kla_scale` from 43 findings to 217."""
    assert scan("c = SBX(prob=0.9, eta=15)\n") == []
    assert scan("run(model, eta=0.87)\n") == []


def test_call_keywords_are_opt_in():
    src = "s = Stream('ethanol', price=0.789)\n"
    assert scan(src, keys=("price",)) == []
    assert shape(scan(src, keys=("price",), call_keywords=True)) == [
        ("bare_literal", "price")]


def test_dict_call_is_always_the_projects_mapping():
    assert shape(scan("p = dict(eta=0.87)\n")) == [("bare_literal", "eta")]

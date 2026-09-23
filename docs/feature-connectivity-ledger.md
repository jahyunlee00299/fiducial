# Feature Connectivity Ledger

## unit: names.py — rule (2), file name vs the file's own declared versions

- **Scope**: core
- **Inputs**: paths to YAML/JSON configs; `mode` in `{strict, set}`
- **Outputs**: `scan()` → `[Verdict]`, each with `name_tokens`, `content_tokens`,
  `mismatch_strict`, `mismatch_set`, `undecidable`
- **State ownership**: none — pure function of (path stem, file text)
- **External effects**: reads files; no network, no writes
- **Evidence (Prove)**: `tests/test_names.py`, 21/21 (`python tests/test_names.py`);
  `tests/test_reference_corpus.py` pins the audited base rate on the real corpus
  (127 comparable / 2 strict / 3 set) and names the three files
- **Refutation (Refute)**:
  - **three implementations, three different answers on the same files** — this
    unit was wrong twice before it was right, and each correction was forced by
    measurement, not review:
    1. scanning raw text → the golden case came out **CLEAN** under `strict`.
       Its header comments narrate its own history ("fit_json advanced v15b ->
       v16"), so the name's token matched prose that merely *described* the
       change.
    2. stripping comments → **still clean**. `description:` repeats "v15b" and
       `note:` cites the canonical "v8" sibling, while all five resolved fields
       say v16.
    3. excluding `extends:` → `set` fired on **27/127** instead of 3. Most of
       the excess were honest children citing a parent (`v18c` naming `v18`),
       plus `ratio_source:` and `warm_path:` leaking under keys nobody would
       list in advance. Fixed by recognising the *shape* of the value (a path
       points elsewhere) rather than enumerating key names.
  - corrected file stops firing (`test_refute_mutation_breaks_the_rule`) — the
    rule is comparing, not asserting
  - honest file, child-citing-parent, path-valued reference, content-only and
    name-only files all stay clean
  - `#` inside a quoted string does not truncate the value
- **Regress**: full suite re-run after each of the three corrections; the corpus
  test moved 27 → 8 → 3 and now matches the independent audit exactly
- **Deferred risk**:
  - `SELF_DECLARING_KEYS` is a fixed list (`fit_json`, `parent_id`, `run_id`,
    `out_dir`, `variant`, `id`, `name`). A project using different names for its
    self-declaring fields gets no protection and no warning. Not configurable yet.
  - Version grammar is `v<digits><optional letter>`. Semantic versions
    (`1.2.3`), dates as versions, and `rc`/`beta` suffixes are not recognised.
  - JSON is accepted by the CLI but the prose/reference exclusions are keyed on
    `key:` line syntax, so a JSON config gets weaker filtering than YAML.
  - Base rate measured on ONE corpus (n=127). The 1.6%/2.4% figures are that
    corpus's, not a general claim.

## unit: literals.py — rule (1), measured keys hard-coded or silently defaulted

- **Scope**: core
- **Inputs**: Python source, plus the **required** list of keys declared to stand
  for measured quantities; `include_neutral` flag
- **Outputs**: `scan_file()` → `[Finding]` with `kind` in
  `{silent_fallback, bare_literal}`, `neutral`, line/col, snippet
- **State ownership**: none — pure function of (source, keys)
- **External effects**: reads files; no network, no writes
- **Evidence (Prove)**: `tests/test_literals.py`, 30/30. Live run against the
  reference codebase (1,522 files, 49 declared keys) found
  `model.kla_scale = 0.776` hard-coded in two scripts while the canonical fit
  carries `0.5074` — **a 53% discrepancy, found by the tool, not by review**
- **Refutation (Refute)**:
  - empty key list **raises** instead of passing vacuously
  - fixing the source silences the finding (`test_refute_mutation_breaks_the_rule`)
  - `params.get("eta")` with no default stays clean — absence is loud there
  - undeclared keys ignored (`params.get("timeout", 30)`)
  - `0/1/-1/2/100` exempt; `True` is not a number
  - non-literals clean: `compute_eta(data)`, `params["eta"]`, `other.eta`
  - **`AnnAssign` was initially missed** — the same omission made the reference
    implementation report "0 items" where 56 existed; now covered by its own test
  - **705 raw hits were unusable** — a live run produced 705 findings, of which
    575 (82%) defaulted to `0.0`/`1.0`, i.e. "this term is switched off", not a
    fabricated measurement. Splitting those out (opt-in via `--include-neutral`,
    never silently dropped) took the signal to 115. Found by running it, not by
    designing it.
- **Regress**: full suite green after the neutral split; three tests that had
  encoded `1.0` as their "bad" default were corrected to a non-neutral value
- **Deferred risk**:
  - `_NEUTRAL_DEFAULTS = {0.0, 1.0}` is a heuristic. A genuine measurement that
    happens to equal 1.0 is hidden unless `--include-neutral` is passed.
  - `params["eta"] = 0.87` (subscript assignment) is **not** detected —
    `visit_Subscript` is a stub. Known gap.
  - No cross-file provenance: a literal next to a comment citing its source is
    still flagged. The rule asks "is there a number here", not "is there a
    citation anywhere in reach", despite what the message implies.
  - Key list is supplied by the caller; no spec-file loader yet (the reference
    implementation's `params_spec.yaml` format is not read).

## unit: coverage.py — rule (3), a declared parameter with no gate

- **Scope**: core
- **Inputs**: declared key list (from a spec's `learnable_keys:`), test files
- **Outputs**: `analyse()` → `[KeyCoverage]`, level in `{ASSERTED, MENTIONED, ABSENT}`
- **State ownership**: none; optional baseline file read by the CLI
- **External effects**: reads files
- **Evidence (Prove)**: `tests/test_coverage.py`, 29/29. On the reference project:
  49 declared keys vs 70 test files, with the golden JSONs passed as `--data`
  → **21 asserted, 3 pinned, 14 mentioned-only, 11 absent**
- **Refutation (Refute)**:
  - **"mentioned in tests/" is not coverage** — counting mentions reports 38/49
    covered; counting assertions reports 10/49. The 28-key middle band is keys
    carried through fixtures and configs while no test claims anything about
    them. Had the rule shipped on mentions it would have certified 28 keys that
    assert nothing.
  - **a line-based search over-credited three keys**, each for a different
    reason, and all three are now regression tests:
    · `k_mtf` matched inside `k_mtf_sub` (a different variable)
    · `qo2_basal` matched inside a regex string literal
    · `log_ratio_fdh` matched an assertion that it is ABSENT (`not in source`)
    Fixed by walking `ast.Assert.test` only — the assertion's *message* is not
    part of its claim — and taking string constants as whole tokens.
  - the same AST pass also found 2 keys a line search MISSED (multi-line asserts,
    the usual shape once a message is attached)
  - empty key list and empty test list both raise
  - a test file that will not parse is skipped, and a good file in the same run
    still counts
  - adding a real assertion moves the key out of the gap set
    (`test_refute_mutation`)
  - **11 keys were FALSE gaps** — reported as "mentioned-only" while
    `tests/golden/golden_baseline.json` pinned their values and
    `test_scalars_exact` compared them with `for key, expected in want.items()`.
    The comparison iterates the file at runtime, so no AST pass can see the
    parameter names. Sending someone to write a second gate for a parameter that
    already had one is this rule's own false-positive mode, and it costs work
    rather than merely being quiet. Fixed by the `PINNED` level + `--data`.
  - a malformed JSON passed as `--data` is skipped, not fatal
  - **11 more false gaps: the keys lived in a module constant.** The project
    writes `ENZYME_A_FITTED_KEYS = ("kcat_enzyme_a", "km_a_enzyme_a", ...)` and then asserts
    over that name, so no key appears in any assert. Naming a constant inside an
    assert now credits its members, and so does a `for k in CONST:` loop whose
    body asserts. A constant nothing asserts over is still not a gate
    (`test_module_constant_members_count`). ASSERTED went 10 -> 21.
  - **some keys SHOULD have no gate, and the project knew why.** `kd_e_xr` and
    `kd_e_enzyme_a` are marked "deliberately absent" at
    `tests/golden/make_golden_baseline.py:85` -- not `__init__` kwargs, they
    travel a second configuration path. Forcing a gate there writes a test that
    asserts a fiction. Hence `coverage_waivers` in the spec, which MUST carry a
    reason: a bare key raises (`test_waiver_requires_a_reason`).
- **Regress**: full suite green; the corpus figures moved 12 → 11 → 10 ASSERTED
  as each over-credit was removed, and each step was verified against the file
  that caused it
- **Deferred risk**:
  - 🔴 **appearing in an assert is necessary, not sufficient.** `assert "frac_nox"
    in params` names the key inside an assertion while asserting nothing about
    its value. This rule reports the FLOOR and certifies nothing it passes.
  - 🔴 **the false-gap band was never closed, only shrunk.** Four rewrites, and
    an independent hand audit of the 14 survivors found 8 MORE false gaps under
    three further mechanisms, none implemented: a LOCAL tuple in the test body
    (`for k in ("k_mtf", "K_mtf", "qo2_basal")`), keys as VALUES in a mapping a
    generic loop walks (`CATALOG_TO_SSOT`), and `setattr` + an assertion on a
    downstream consequence (SSE invariance, Haldane equilibrium, QSSA residual).
    A MENTIONED verdict means "no gate found by the patterns here", not "no gate".
  - 🔴 **and the error runs the other way.** `km_p_enzyme_a`/`km_q_enzyme_a`/`ki_p_enzyme_a` are
    set by a test that asserts `rate == 0` at a manufactured equilibrium; the
    numerator is structurally zero there and all three appear only in the
    denominator, so the assertion holds for ANY value. Implementing the
    local-tuple pattern would promote them to ASSERTED — trading a false gap
    (costs an afternoon) for a false gate (costs the thing the gate was for).
    Pinned as a claim in `test_an_assert_can_be_blind_to_the_parameter_it_names`.
  - **the waiver written for `kd_e_enzyme_a`/`kd_e_xr` was wrong and has been
    retracted.** "deliberately absent" at `make_golden_baseline.py:85` scopes to
    that ONE fixture; both keys are gated elsewhere by
    `test_fixed_kinetics_reach_the_ode.py`, which parametrizes over `CANDIDATES`
    and asserts SSE is unchanged when each is pinned at its fitted value. A
    comment saying "deliberately absent" is about the file it sits in.
  - `--level absent` (the default, and what the hook uses) ignores the 14
    remaining mentioned-only keys. They are a real finding left unenforced.
  - Constant tracking is one hop: `A = (...)` then `assert ... A ...`. A constant
    built from another constant, or assembled at runtime, is not followed.
  - A waiver is honoured on the key's name alone; nothing checks that the recorded
    reason is still true.
  - `PINNED` only means the key appears in a data file that was passed in. It
    does NOT verify that any test actually reads that file — a stale golden
    nobody compares would still count. Same floor-not-guarantee caveat as
    `ASSERTED`.
  - Data files are JSON only; a YAML or CSV fixture is not read.
  - `load_declared_keys` reads one YAML shape (`field:` + `  - name`) to keep the
    core dependency-free. A richer spec needs keys passed explicitly.
  - Test discovery is whatever paths the caller passes; a project whose gates
    live outside `tests/` reports false ABSENTs.

## unit: cli.py — entry point, exit-code contract

- **Scope**: interface
- **Inputs**: argv
- **Outputs**: exit `0` clean / `1` violations / `2` cannot check; findings on stdout
- **State ownership**: none
- **External effects**: reads files, writes stdout/stderr
- **Evidence (Prove)**: `tests/test_cli.py`, 15/15 — both rules' exit codes, both
  `names` modes, and all three `cannot check` paths
- **Refutation (Refute)**:
  - empty `--keys` → exit 2, not 0
  - zero matched files → exit 2, not 0 (the failure this package was built after)
  - unparseable source → exit 2
  - **absolute globs crashed** — `Path(".").glob("/abs/*.py")` raises
    `NotImplementedError: Non-relative patterns are unsupported`. A caller
    passing an absolute glob got a traceback instead of results. Found by the
    test, not by review; fixed by splitting the pattern at its fixed root.
- **Regress**: full suite green after the glob fix
- **Deferred risk**:
  - `_run_names` calls `inspect_file` a second time to count comparable files —
    every config is parsed twice. Fine at this corpus size, wasteful at scale.
  - No `--format json`. Automation must parse human text.
  - Only tested on Windows + CI Linux; no macOS runner.

## unit: tests/run_all.py — the suite actually runs

- **Scope**: cross-cutting
- **Inputs**: `tests/*.py`, the committed floor `tests/EXPECTED_TESTS`
- **Outputs**: exit 0 clean / 1 violations or shrinkage / 2 cannot check
- **State ownership**: the floor file (a ratchet)
- **External effects**: runs pytest in a subprocess
- **Evidence (Prove)**: 149 tests execute where 42 did before
- **Refutation (Refute)**: 8/8 probes, each on a mutated copy of the repo —
  - **28 of 70 test functions were never executed.** `test_docs.py` is
    pytest-style; CI ran `python tests/test_<x>.py`, which for that file
    imports the module, calls nothing, and exits 0. A deliberately broken
    assertion in it exited 0 on the CI path and failed only under pytest.
    The whole of rule (4) was counted as passing without running.
  - **the first floor was computed from the files it was about to run**, so a
    probe that deleted one test file took the suite 91 → 41 and still exited 0.
    A bound computed from the thing it bounds is not a bound; the floor moved
    into a committed file.
  - **the two floors were in different units** — executed (91, parametrize
    expands some) vs defined (70) — and comparing them failed a clean suite.
    Separated.
  - missing/unreadable floor → 2, not 0; the no-pytest fallback → 2 and names
    the files it could not run; an unmodified suite still exits 0
- **Regress**: full suite green at each step; floor raised deliberately
- **Deferred risk**: the floor counts tests, not coverage. A test that runs and
  asserts nothing still counts, which is rule (3)'s own caveat applied here.

## unit: config.py — `[tool.fiducial]`, with a 3.10 fallback

- **Scope**: core
- **Inputs**: `pyproject.toml` / `.fiducial.toml`
- **Outputs**: `Config` (frozen), `ConfigError`, `resolve_set()`
- **State ownership**: none
- **External effects**: reads files
- **Evidence (Prove)**: `tests/test_config.py`, 34/34
- **Refutation (Refute)**:
  - **differential against `tomllib`, 18 hostile inputs.** 9 agreed, 7 were
    already refused, and **2 disagreed SILENTLY**: `"he said \"hi\""` kept its
    backslashes, and `a.b = 1` became a flat key instead of a nested table.
    Both now raise. Re-run: 0 silent disagreements. A config meaning one thing
    on 3.10 and another on 3.13 only surfaces on someone else's machine.
  - **the dispatch itself is pinned, both ways.** Every other test calls the
    fallback parser directly, which says nothing about whether `load_toml` ever
    reaches it — on 3.13 the tomllib branch always wins. Without this the 3.10
    path would be tested-but-unwired, the failure this ledger keeps recording.
  - a typo lands in `Config.unknown` rather than being ignored
  - a `pyproject.toml` with no `[tool.fiducial]` does not stop the upward
    search (in a monorepo the nearest one is usually another package's)
  - an unparseable config raises instead of falling back to defaults
- **Regress**: 149 green
- **Deferred risk**:
  - The 3.10 reader covers a subset. Inline tables, arrays of tables,
    multi-line strings, datetimes, hex ints, nested arrays and quoted keys all
    raise. That is deliberate but it is a smaller TOML than 3.11+ accepts.
  - `Config` is flat by construction, which is why dotted keys can be refused.
    A future nested setting needs the fallback extended first.

## unit: locales.py — rule (4)'s language patterns, out of the core

- **Scope**: sub-feature
- **Inputs**: locale codes, extra history markers
- **Outputs**: `LocaleSet`, `UnknownLocale`
- **State ownership**: none
- **External effects**: none
- **Evidence (Prove)**: `tests/test_locales.py`, 14/14 — each asserts a
  DIFFERENCE between locale sets, because "still passes" is what a knob wired
  to nothing also produces
- **Refutation (Refute)**:
  - en-only must NOT apply `였다` / `선례`; ko must. Both directions asserted.
  - the default keeps Korean, so existing callers see no change — dropping it
    would silently alter every result
  - an unknown locale raises rather than falling back to English
  - `check()` / `scan()` / `find_values()` had to be threaded before the
    setting reached anything: the low-level tests passed while
    `[tool.fiducial] locales` changed nothing in a real run
- **Regress**: rule (4)'s 49 tests unchanged and green throughout
- **Deferred risk**: two locales ship (en, ko). A third is a data change, but
  nobody has written one, so the shape is unproven against a real third case.

## unit: runner.py + `fiducial check` — one entry point

- **Scope**: interface
- **Inputs**: `Config`, optional `--rules`
- **Outputs**: per-rule outcomes, a summary, one aggregated exit code
- **State ownership**: none
- **External effects**: stdout/stderr
- **Evidence (Prove)**: `tests/test_adoption_e2e.py`, 10/10 — the real CLI in a
  subprocess against a throwaway repo, configured only by a file
- **Refutation (Refute)**:
  - **`python -m fiducial` did not exist.** No `__main__.py`, so every
    end-to-end probe failed with "cannot be directly executed". The console
    script needs an install; a hook running from a checkout does not have one.
  - **a probe reported PASS while nothing ran at all.** "the file is not
    flagged" was true because fiducial was unrunnable. An absence is evidence
    only once the run is known to have happened, so the assertion now requires
    the rule's own summary line first — the package's own thesis, found inside
    its own test.
  - cannot-check outranks violations in the aggregate; a check that would run
    no rule is itself exit 2; a clean repo is exit 0
  - a misspelled setting is named in the output
- **Regress**: 149 green
- **Deferred risk**:
  - `check` builds each rule's `Namespace` by hand (`_literals_args` etc). A
    new CLI flag must be added in two places or `check` silently uses the
    default.
  - No `--format json` still. Automation parses human text.

## unit: rule (2) zero-comparable — blind is not clean

- **Scope**: core (exit contract)
- **Inputs**: the files rule (2) actually read; `--allow-zero-comparable` /
  `names_allow_zero_comparable`
- **Outputs**: exit 2 when files were read and none could be compared
- **State ownership**: none
- **External effects**: stderr
- **Evidence (Prove)**: `tests/test_zero_comparable.py`, 10/10
- **Refutation (Refute)**:
  - **found by dogfooding, not by review.** Pointing `fiducial check` at this
    repository scanned one YAML, compared none, printed `names clean` and
    exited 0. The one place the package granted itself the pass it refuses in
    rule (1) (empty `--keys`), rule (4) (nothing declares an SSOT) and the CLI
    (zero-file match).
  - the hatch must not hide a finding: `--allow-zero-comparable` on a repo with
    a real v3-vs-v4 mismatch still exits 1. Otherwise a project that set it
    once to quiet a legacy directory would stop being checked at all —
    the failure this rule exists to prevent, reintroduced through its own
    escape hatch.
  - "no files at all" and "files but nothing comparable" stay distinct: both
    exit 2, different messages, because the remedies differ (fix the paths vs.
    accept that your configs are unversioned)
  - a comparable clean file still exits 0
  - **`check` builds each rule's namespace by hand**, the trap this ledger
    already recorded, so the setting is asserted to reach `check` and not only
    the subcommand
- **Regress**: 159 green
- **Deferred risk**:
  - The hatch is per-project, not per-directory. A repo that versions
    `configs/` but not `deploy/` must either split the invocation or accept
    the weaker setting for both.
  - Turning it on is permanent in practice: nothing re-examines whether the
    project has since started versioning its config names, so the setting can
    outlive its reason the way any waiver can.

## wiring: where this is actually invoked

Measured 260921 -- each row below was exercised, not assumed.

| entry point | status | evidence |
|---|---|---|
| `fiducial` console script | wired | `pyproject [project.scripts]`; `fiducial --help` and both rules exercised in CI |
| `python -m fiducial` | **wired 260923** | `__main__.py` added; it did not exist, and every end-to-end probe failed until it did |
| `fiducial check` + `[tool.fiducial]` | **wired, fires** | `tests/test_adoption_e2e.py` runs the real CLI against a throwaway repo configured by file only; 3 cases assert a setting CHANGES the outcome |
| the reference corpus `.git/hooks/pre-commit.local` | **wired, fires** | rule (2): staged a config whose name said v15b and fields said v16 -> exit 1. rule (3): staged a spec declaring an ungated key -> exit 1 |
| the process-modelling repo `.git/hooks/pre-commit.local` | **wired, fires** | same probe in `ssot/params/` -> exit 1 |
| sci-toolkit skill | wired | `skills/fiducial/SKILL.md`, **no source copy** -- calls the installed package |
| pre-commit.com hooks | **wired, fires (measured 260923)** | `tests/test_precommit_framework.py`: the framework builds its own venv from this pyproject, blocks a violating repo, passes a clean one, and the zero-comparable hatch is reachable through `args:` |
| Claude Code hook (`settings.json`) | not wired | rule (1) is already covered there by `params_strict_posttool.sh`; rule (2) has no PostToolUse equivalent yet |
| Codex (`AGENTS.md`) | **wired, fires (measured 260923)** | section added to BOTH `~/.codex/AGENTS.md` and the master copy; `codex exec --sandbox read-only` answered the exit-2 contract and the cwd trap from its rules alone, without running anything |
| pytest plugin (`pytest11`) | **wired, fires (measured 260923)** | `[project.entry-points.pytest11]`; proven on the reference corpus's real 834-test suite (53 keys, 19 gated, gap 0) and in CI (discovery, inertness, strict blocks) |
| rule (2) zero-comparable → exit 2 | **fixed 260923** | found by pointing `check` at this repo; `tests/test_zero_comparable.py` |
| CI runs the whole suite | **fixed 260923** | was running 42 of 70 test functions; `tests/run_all.py` + committed floor |
| pandera adapter | **dropped 260923, measured** | pandera appears in 0 files across the reference corpus / a clustering-research repo / a process-modelling repo / an instrument-analysis repo; pandas appears in 382. Building an adapter nobody imports is the written-but-unwired failure this ledger exists to record, and it would put the first dependency into a package whose zero-dependency claim is load-bearing. See the note below. |

### Why there is no pandera adapter (dropped 260923)

The plan carried one. It was dropped after measuring rather than after
designing, and the measurement is the whole argument:

| | files |
|---|---|
| `pandera` across the reference corpus, a clustering-research repo, a process-modelling repo, an instrument-analysis repo | **0** |
| `import pandas` in the reference corpus alone | 382 |

Three reasons, in order of weight:

1. **Nobody here would load it.** An adapter for a library no repo in this
   workspace imports is written-but-unwired by construction -- the exact
   failure this ledger was created to stop recording.
2. **The seam is wrong.** All four rules are static: they read source, configs
   and prose without executing anything. pandera validates a DataFrame at
   runtime. An "adapter" between them would either re-implement rule (1)
   against a schema object (a different check wearing the same name) or shell
   out to the CLI from a pandera hook (a wrapper, not an integration).
3. **It would cost the dependency claim.** `dependencies = []` is not
   incidental here; the pre-commit hook builds its own env from this pyproject,
   and the 3.10 TOML fallback exists precisely to avoid a dependency. An
   optional extra would still add a code path that CI cannot exercise without
   installing it.

What actually answers the need: the pytest plugin, which reaches the same
runtime moment (a test session) through a seam the package already has, and
which was proven against a real 834-test suite rather than a fixture.

If a consumer does want this, the honest shape is a separate package that
imports fiducial -- not an extra inside it.

### How the git wiring composes with what was already there

`params-strict-guard` (installed by `~/.claude/scripts/install_params_strict_hooks.sh`)
owns `.git/hooks/pre-commit` and chains to `pre-commit.local` **before** its own
scan. fiducial installs there rather than replacing anything: the two rules
check different file types (`.py` vs `.yaml/.json`) and neither needs to know
about the other.

**Scope: staged files only.** Repo-wide sweeps are a separate, deliberate act.
A guard that fails on day one for reasons the committer did not cause gets
bypassed permanently, and a bypassed guard protects nothing. The reference
corpus carries 3 pre-existing rule (2) violations right now; none of them block an unrelated
commit.

### Four measurements, not one

Blocking was the easy half. These were run together, because a gate that only
ever says "no" is indistinguishable from a broken one:

| probe | expected | got |
|---|---|---|
| staged config, name v15b vs fields v16 | blocked (1) | 1 |
| staged config, name and fields agree | pass (0) | 0 |
| staged `.py` only, no config at all | pass (0) | 0 |
| staged `.py` with `params.get("kla_scale", 2.7)` | blocked by rule (1) | 1 |

The fourth is the regression check: the pre-existing rule (1) gate still fires
after fiducial was chained in front of it.

### rule (3) and the baseline — measured, and it failed the first time

Four more probes, after rule (3) was chained in:

| probe | expected | first attempt | with baseline |
|---|---|---|---|
| spec declares an ungated key | blocked (1) | 1 | 1 |
| spec declares a key **with** a gate | pass (0) | **1 — WRONG** | 0 |
| commit that does not touch the spec | pass (0) | 0 | 0 |
| rule (1) violation still blocks | blocked (1) | 1 | 1 |

The second row is the whole reason `--baseline` exists. Adding one properly
gated key still failed, because the project's 11 pre-existing gaps came along
with it. A gate that punishes the correct action on its first real use gets
bypassed that same day, and a bypassed gate protects nothing.

So the gaps that predate the gate are frozen in
`.claude/fiducial_coverage_baseline.txt` (11 keys here). New gaps block; listed
ones are reported and do not. The file is a ratchet: shrink it, never grow it.
Rule (3) also only runs when the spec itself is staged, which is exactly the
moment a key is added.

`exit 2` (cannot check) is deliberately **not** treated as a block in the hook.
When nothing staged is comparable, that is not a violation, and fiducial
distinguishes the two precisely so a caller can tell "clean" from "blind".

### Correction recorded 260921

An earlier probe in this session concluded the existing rule (1) gate had
*missed* `params.get("eta", 0.87)`. That was wrong. `eta` sits in the spec's
`optional_keys` (deprecated), not `learnable_keys`, so not flagging it is
correct behaviour. Re-measured with a genuine learnable key (`kla_scale`) the
existing gate blocks as designed. The claim was retracted before it reached any
card; recorded here because a false "the old gate is broken" finding is exactly
the kind of thing that gets acted on later if it is not written down as refuted.

### The Codex wiring has no sync path (found 260923)

Adding the rule to the master copy alone would have wired nothing.
`~/.claude/scripts/sync_config.sh` copies `CLAUDE.md`, `AGENTS.md`, `CLAUDE/`
and `hooks/` — it does not touch the master's `codex/` directory at all, so
`~/.codex/AGENTS.md` is maintained by hand. The two had already drifted apart
before this change: the master carried a whole `## Gap Audit (C-71..C-85)`
section the local copy lacked, and the local carried a `ku_llm` gateway section
the master lacked. Both copies were therefore edited directly here.

That drift is a separate problem from this feature and was not repaired as part
of it — merging two independently-edited rule files is its own change, with its
own review.

### Still open

- The process-modelling repo's 14 SSOT configs carry no version tokens at all,
  so rule (2) reports `0 violations among 0 comparable` there. That is honest
  -- nothing to compare -- but it means the wiring there is proven only by a
  synthetic probe, not by a finding on real files.
- The two `model.kla_scale = 0.776` sites found by rule (1) are still in the
  tree. Which figures or reported numbers were produced with them is **not yet
  traced**.

### The PyPI token was already project-scoped (measured 260923)

An earlier audit left open the possibility that the publishing token carried
`scope:user`, i.e. write access to every project on the account. It does not.

Decoding the macaroon's caveats (structure only, never the signature) gives:

```
location : pypi.org
identifier: $17620119-5c65-4f94-856f-bf45954a053c
caveat    : *[3,"9de218db-a535-4ece-9da3-33bb1349dfdf"]
```

Caveat version `3` is pypitoken's **project-ID restriction**; a user-scoped
token carries no such caveat. The account publishes exactly one project
(`compat-check`, 6 releases, current 0.6.0 -- `fiducial` itself is not on
PyPI, 404), so the single permitted project ID is that one.

Nothing was rotated. The carried-forward risk was a belief, not a finding, and
measuring it removed it rather than confirming it. Recorded because "replace the
token" was queued as work that turns out not to be needed -- the *next* time a
second project is published, the caveat becomes a real constraint to re-check,
not a leak to repair.

The API does not expose project IDs, so the UUID was not matched to the project
name directly; the one-project account is what closes the gap.

### codex/AGENTS.md: merged, and the sync gap that caused it closed (260923)

The two copies were merged and the structural cause was wired, because merging
alone would have let the same drift re-form.

**The merge.** Three divergent hunks, not the two the handoff recorded:

```
size budget para   master newer (2026-09-15, "covers through C-85", 33 KB)
                   local  stale (2026-09-02, "kept under 30 KB" -- no longer true)
ku_llm gateway     local only  (+ codex_ku.sh subsection)
Gap Audit C-71..85 master only (14 rules Codex could act on and never saw)
```

Merged master-first with the local-only section re-inserted at its own anchor
(both copies placed it immediately before `## Reporting Scripts`, so the
insertion point was unambiguous). Verified by eight assertions before writing:
every heading from either copy survives, no heading is duplicated, the newer
size-budget text wins, and both once-orphaned sections are present. Result is
40,003 bytes against a 128 KiB `project_doc_max_bytes`, so nothing is silently
truncated.

**The cause.** `sync_config.sh` copies into `$HOME/.claude`; Codex reads
`~/.codex/AGENTS.md`. The file needed a destination outside the only root the
script knew, which is why it was never added. Three edits, all on master:
the rsync branch, the `cp` fallback branch, and `needs_sync()`.

`needs_sync()` matters as much as the copies. It only compared paths under
`$dst_root`, so a codex-only change looked like "nothing to sync" and the
script exited before reaching either copy branch.

**Measured, not assumed.** A marker appended to master's copy was absent from
`~/.codex/AGENTS.md`, present after one run, and gone again after master was
reverted -- propagation in both directions.

**What the probe additionally exposed.** The first patch was applied to the
*local* script and was gone minutes later: `scripts/` is itself synced, so
master's copy overwrote it. That is C-13 behaving exactly as documented, but it
also measured a second drift nobody was tracking -- master's `sync_config.sh`
was 16,757 bytes against local's 16,408, i.e. the local machine had been running
an older sync script than the one master shipped. Patching master fixed both in
one run: run 1 pulled the newer script down, run 2 exercised the new wiring.

The drift was never only `codex/AGENTS.md`. It is what a copy outside the sync
does, and two of them were found by probing one.

## Unit: rule (5) -- a pointer whose target is not there

**Layer**: core (a fifth rule beside literals/names/coverage/docs).
**Outcome**: an index that registers artefacts is checked against the
filesystem, and the two repair classes are reported apart.

### Prior art

Rule (2) was the closest existing rule and does not cover this. It compares
version tokens between a file's name and its own fields; these registry entries
carry no version token, and the entry is internally *consistent* -- it simply
describes a file that is not there. A consistency check cannot see a missing
referent. The handoff nominated "a copy that drifted from its upstream"
(four separate instances) as the rule (5) candidate; the detectable core
of that family is a pointer to a target that moved or vanished, and that is
what shipped.

### Inputs / outputs

Input: JSON index files (`pointers_paths`, or paths on the command line).
Output: per-index report plus a repair plan for the unambiguous relocations.
State owned: none -- read-only, no network, no shell.

### Evidence (measured, not designed)

`models/params/param_registry.json` (reference corpus):

```
303 pointers checked
118 broken   88 file + 30 dangling parent_id
  69 relocatable   archive/ 64 · gpo/ 4 · test/ 1, every one unambiguous
  19 gone          16 de_mpsp_*_smoke · 2 lsq_10d_* · literature_baseline
```

58% of the 152 registered entries do not load. `ParamRegistry.load_params(
"run_260403_a")` -- the fit six BO/plotting scripts quote by value --
raises `FileNotFoundError`; the file is one directory down in `archive/`, moved
by commit `d928acba` which did not update the index.

The reference counts are asserted in `test_pointers.py`, not described, so a
repair shows up as a changed number rather than as silence.

### Refutation

Twelve adverse cases run before the tests were written; three changed the
implementation:

```
no pointers at all        -> BLIND (exit 2), not clean.  Rule (2) shipped
                             exactly this bug; repeating it here was the
                             likeliest failure and is now the first test.
parent_id: null           -> a ROOT, not a dangling pointer.  Flagging it
                             would report the one definitionally-correct row.
ambiguous basename        -> NOT repairable, excluded from the plan.  A repair
                             tool pointed at the wrong artefact is worse than
                             no repair.
malformed index           -> raises, never "0 broken"
empty-string value        -> skipped; an absent claim cannot be a false one
bare mapping (no entries) -> handled without configuration
```

Zero ambiguous basenames occur in the reference corpus, so that branch has no
field evidence -- it is handled because a corpus where it *does* occur is
precisely where an automatic repair would do damage.

### Connect

```
fiducial/pointers.py          the rule
fiducial/cli.py               `pointers` subcommand + _run_pointers
                                + _pointers_args + runners table + --rules list
fiducial/config.py            pointers_paths · pointers_root · file_keys ·
                                id_keys (+ extend_), _STR_LIST_FIELDS,
                                _SET_FIELDS, _KNOWN_RULES
tests/test_pointers.py          19 tests
tests/EXPECTED_TESTS            174 -> 193
```

Fired, not just wired. Exit contract measured on all four paths: violations 1,
blind 2, clean 0, no files matched 2. Run through `fiducial check` with
`rules = ["pointers"]` -- reports `pointers violations`, exit 1.

The `check` trap the handoff records (§5-3: each rule's Namespace is built by
hand, so a new setting must be added in two places or `check` silently uses the
default) is covered by `test_the_setting_reaches_check_too`, which proves it by
behaviour: with `file_keys` configured the custom key is a pointer and `check`
exits 1; without it the same index is blind and `check` exits 2.

### Deferred

The repair itself. `repair_plan()` returns the 69 corrections but nothing
applies them -- writing to a research repo's registry is a separate change with
its own review, and the 19 missing artefacts need a person either way.

### Rule (5) found a real defect and repaired it the same day (260923)

The rule was applied to the corpus it was built from, and the repair it
proposed was taken:

```
reference-corpus commit dce90eff  "Point the param registry at where the files actually are"
              69 file fields re-prefixed (archive/ 64, gpo/ 4, test/ 1)
              broken pointers  118/303 -> 49/303
              load_params over all 152 ids   64 -> 133 resolving
```

Verified independently of the checker: `ParamRegistry.load_params` was called
on every registered id before and after. A tool reporting its own repair as
successful is not evidence; the loader is.

The diff is 70 lines and 69 of them prefix a directory onto a `file` value. No
id, stage, `parent_id`, `free_params` entry or fitted value changed, asserted in
the repair script by comparing basenames before writing (the 70th line is a
missing trailing newline).

**Not repaired, deliberately.** 19 entries name a file that exists nowhere (16
`de_mpsp_*_smoke` run outputs, 2 `lsq_10d_*`, `literature_baseline`) and 30
`parent_id`s reference unregistered ancestors. Both are data-loss questions, not
path errors, and inventing a target for them would put a wrong answer where an
honest gap is.

**What this settles about the duplicated constants.** The three (in fact six) `kla_scale = 0.776`
sites are *not* stale copies. The canonical fit holds `0.7757073373946419`,
which rounds to exactly the hardcoded value, and the four sibling constants
(`eta`, `vmax_endo_formate`, `xr_activity_scale`, plus `kla_scale`) all match
their fit file too. The defect was never the value -- it was that the load path
which would have made the copies unnecessary had been broken since `d928acba`,
so hardcoding was the only thing that worked. Refactoring those six call sites
onto `load_params` is now possible, and is a separate change.

The four PNGs these scripts produce were committed once (`c90201a6`) and
deleted (`15a419b6`); they are in neither the tree nor HEAD, so whether any of
them reached a manuscript figure is **not determinable from this repository**
and is recorded as unknown rather than cleared.

### The floor failed a healthy checkout, and the fix had to stay a ratchet (260923)

Adding rule (5)'s two corpus-dependent tests broke the suite everywhere the
private corpus is absent -- which is every machine but this one, and every CI
run. Measured: `191 passed, 2 skipped`, floor 193, **exit 1**. This is the
blocker for publishing the repo at all, since the first thing a public CI run
would have done is fail.

The floor counts what *executed*, deliberately. Three ways out were rejected
before the fourth:

```
count skips as executions   the floor stops meaning "ran"; every future skip
                            is free -- the exact equivalence this package refuses
lower the floor to 191      the two tests could then stop running on the machine
                            that HAS the corpus, silently
compute the floor per env   a bound derived from the thing it bounds is not a
                            bound; this repo measured that once already (91 -> 41,
                            still exit 0)
```

What shipped instead: skips are parsed separately and excused only up to
`ALLOWED_SKIPS = 2`, a committed number sitting next to the floor in the diff.
The bound is the whole point -- a third skip still fails, so "mark it skipped"
never becomes the quiet way to shrink a suite.

**Refutation.** Two probes, both run before the tests were written:

```
rename 3 tests out of collection, corpus absent  -> still fails (defined floor)
add one extra skip (3 > ALLOWED_SKIPS)           -> still fails
```

The allowance does not cover either, which is what makes it safe to have.

**A probe that ate the machine.** The first version of `test_skip_accounting.py`
copied the repo to mutate it -- including itself. Each copy re-ran the probes,
which copied again. It forked without bound and left 1500+ temp directories
before being killed. The file now excludes itself from its own copies, and the
copy's floor is adjusted for what is structurally absent from it (this file's
5 tests, the 4 git-dependent ones since `.git` is not copied, the 2
corpus-dependent ones). Those adjustments are artefacts of the probe, named as
such, and deliberately do NOT relax the property under test.

**Wired.** A CI step asserts the allowance is spent on exactly the two corpus
skips and nothing else -- catching the opposite drift, where the corpus tests
quietly start passing and the allowance silently covers some other skip.
Verified locally against a corpus-less run: 196 passed, 2 skipped, exit 0.

### Publishing, and the six CI runs it took (260923)

The repo is on GitHub, private, with CI green on 3.10 and 3.13. Getting there
cost six runs, and every one of them failed on something local simulation could
not see -- which is the argument for pushing to a private repo before a public
one, rather than a matter of taste.

```
e208e77  3.10 ConfigError on this package's own pyproject.toml
cb558f0  3.13 nine plugin tests, unrecognized --fiducial-spec
5eecd1d  same, plus a miscount: 571 tests reported where 202 ran
7ee27d9  eleven failures that were really one, nested inside a probe
399b87a  3.10 only: 16 skips where the constant allowed 3
d6f1e20  success, both interpreters
```

**What each one actually was.**

The 3.10 TOML fallback refused `license = { text = "MIT" }` in the package's
own `pyproject.toml`. An inline table is legal TOML the fallback does not
implement, and it raises rather than skipping -- correct for a fiducial
setting, wrong for `[project]`, which fiducial never reads. It made the tool
unusable on 3.10 in any project whose pyproject uses an inline table anywhere.
The fallback now parses only the table it was asked for; inside that table it
is exactly as strict as before, asserted by its own test.

The plugin tests need the `pytest11` entry point, because `pytester` starts a
fresh session that inherits neither the parent's `-p` flags nor the repo's
conftest. The workflow ran the suite before installing, deliberately, to show
the package is stdlib-only. Both intentions are kept by installing with
`--no-deps -e .` before the suite, since the later plain `pip install .` step
re-proves the dependency claim. Two intermediate attempts -- a conftest
`pytest_plugins`, then `-p` on every `runpytest` -- were reverted after
measuring: the first collided with pluggy's name registry where the package
WAS installed, the second did not reach the child session at all.

`run_all` counted 571 tests where 202 ran: it summed every `N passed` in
stdout, and the floor probes print the output of the runs they make. A
miscount that inflates satisfies the floor for the wrong reason, so both
parsers now read pytest's final summary line only.

**The floor's allowance was the deepest of them.** It began as
`ALLOWED_SKIPS = 2`, a count, and the build matrix broke it the same day: 3
skips on 3.13, 16 on 3.10, because one `skipif(version_info < (3, 11))` guards
a 12-case `parametrize`. Both numbers are right for their interpreter and no
constant is right for both. Skips are now accepted by REASON -- the private
corpus, an uninstalled `pre-commit`, a missing stdlib module, a tree with no
`.git` -- with the list committed in the source and any other reason failing
the run by name. The workflow keeps the half a reason list cannot check: CI
*is* a checkout, so `not a git checkout` appearing there would mean four
pre-commit tests stopped running, and it fails on that specifically.

The floor itself was also set from this machine, where `pre-commit` is
installed and contributes four tests a clean checkout does not even collect.
It now records what the leanest supported environment runs (198); a richer
machine runs more, which is fine.

**The probe kept disabling itself.** `test_skip_accounting.py` copied the repo
to mutate it -- including itself -- and forked without bound, leaving 1500+
temp directories before it was killed. Then it derived the copy's floor by
subtracting three hand-maintained constants; one drifted, and the shrink probe
came back green on a suite that had genuinely lost three tests. It now measures
the copy's baseline before mutating it, and the parts that do not need a copy
at all are checked against the runner's logic directly.

**The reproduction that finally worked** was an isolated venv (`system_site_
packages=False`) with `git init` and an empty `HOME`. Five earlier attempts
each missed one of those three and passed locally while CI failed.

### Published (260923)

`github.com/jahyunlee00299/fiducial`, MIT, CI green on 3.10 and 3.13.

**Anonymised first, because the research it was measured on is unpublished.**
Every project-identifying name is gone -- repository names, the enzyme and
condition codes in fit ids, the corpus's internal directory layout. Every
measurement stayed: counts, percentages, base rates, dates, commit hashes and
assertion values are untouched, because the evidence is what the repo is for.
A name tells a reader which lab; `88 of 152` tells them whether to believe the
rule.

Terms that look specific but identify nothing were kept -- `kla_scale`, `eta`,
`km_*`, `kcat_*`, `MPSP` appear in any bioprocess model. Version tokens were
kept too (`optimizer_run_v15b_...`), since a version token disagreeing with its
contents *is* rule (2)'s example.

**The corpus path became configuration.** `FIDUCIAL_REFERENCE_CORPUS`, with
no default, plus `FIDUCIAL_REFERENCE_REGISTRY` and
`FIDUCIAL_REFERENCE_FIT_ID` for the layout details inside it. A public clone
skips those tests; a configured machine still runs all 19. Verified both ways.

A placeholder path was tried for the unconfigured case and was wrong in a way
worth recording: `Path("/nonexistent").exists()` is **True** on Windows, where
it resolves to `C:\nonexistent`. That would have silently defeated the
`skipif` and made the corpus tests attempt to run in a checkout that has no
corpus -- a guard that cannot fail, which is the failure this package is about,
inside its own test suite. `REFERENCE_INDEX` is `None` instead, which cannot
resolve to anything.

**Published as a fresh history**, one commit, rather than rewriting 29. The
private repo keeps the development record; the public one carries no
pre-anonymisation revision to recover. `docs/HANDOFF_260923.md` was left out
entirely -- an internal session handoff whose research context is dense and
whose content already exists here in anonymised form.

**Two things the publication itself caught**, neither visible before pushing:
the install instructions in the README and `.pre-commit-hooks.yaml` pointed at
the *private* repo, so the first thing a reader copies would have failed for
everyone but the author; and the CI step that proves the corpus test skipped
still grepped for the pre-anonymisation message. Both were found by reading
the published artefact rather than the local one.

## Unit: structured findings for an agent caller

**Layer**: cross-cutting (a second output format over all five rules; rule ⑤
wired first, the others pending).
**Outcome**: a caller that is a program gets the one thing the prose cannot
give it — what to do about each finding.

### Why, and why now

The rules were written for a person reading a terminal, and the audience has
inverted. Someone who sets parameters by hand rarely runs this checker; they
already know where their numbers came from. A model writing the code does not,
and `params.get("eta", 0.87)` is precisely what one does when it needs a number
it does not have — the confabulation shape rule ① was built around.

### Prior art, and what was taken

Delegated, not assumed. Findings:

```
SARIF        REJECTED as the wire format. Its `level` has no value for "the
             check could not run", and `kind: notApplicable` means "did not
             apply here", not "should have been checked and was not" -- which
             is this package's whole argument. `fixes[]` carries no safety
             grade, so both fields that matter would land in non-standard
             `properties`. Verified against the OASIS schema itself, not docs.
Ruff         TAKEN: `applicability: safe | unsafe`. Measured from `ruff check
             --output-format=json` on 0.16.0 rather than read from its docs --
             the prior-art pass had left the enum unconfirmed, and a probe
             settled it in one run.
ESLint       TAKEN: the `fix` (tool applies) vs `suggestions` (tool offers)
             split, as `apply: auto | suggest_only`.
Semgrep      HALF-TAKEN: severity/confidence separation is the right instinct,
             but this tool has no severity spectrum -- a rule that fires has
             decided. Only the confidence axis applies.
CodeQL       NOT APPLICABLE: `@precision` is rule-level metadata, not a
             per-finding judgement.
```

### The design claim, and the evidence for it

Two axes, because one cannot carry it. Rule ⑤ is the proof, and it is asserted
rather than argued (`test_all_three_pointer_outcomes_are_certain_and_differ_only_in_fix`):

```
moved (1 candidate)      certain   safe/auto           agent applies
gone  (0 candidates)     certain   (no fix key)        agent asks
ambiguous (2+)           certain   unsafe/suggest_only agent shows, picks none
no pointers at all       --        cannot_check        agent fixes the call
```

All three violations are equally certain; what differs is who may act. A single
severity ladder would have to rank cases that do not differ in severity, and
the one it ranked lowest is the one where an agent would invent a path.

Rule ② runs the other way -- 1.6% base rate, so `needs_review`, yet its repair
is mechanical. Any single axis puts these two in the wrong order.

### Refutation

Eleven adverse cases before the tests were written. The load-bearing one:

```
apply the `safe` fix blindly, as an agent would -> the registry resolves
```

A fix marked safe that merely looked plausible would make `auto` an invitation
to corrupt a registry -- worse than emitting no fix at all. Also checked: an
ambiguous edit carries `candidates` and never `to`, so a consumer that only
reads `to` correctly finds nothing to do; a missing artefact emits no `fix`
key at all (absent, not null, so `"fix" in finding` is the whole question);
blind counts as neither clean nor violation.

### Connect

```
fiducial/signals.py        Signal · Fix · Envelope, one adapter per rule
fiducial/cli.py            --format=json on `pointers` + the `check` Namespace
tests/test_signals.py      11 tests
tests/EXPECTED_TESTS       198 -> 208
README.md                  "When the caller is an agent"
```

Fired, not just wired: `fiducial pointers --format=json` through the installed
console script, exit 1, and every claim the README makes about the payload
verified against the real output rather than the code.

The `check` trap held again -- `_pointers_args` needed `format="text"` or
`check` would have raised on the missing attribute.

### Deferred, by decision

`status: cannot_check` is rule-level only. A per-finding version -- "these 3 of
100 files failed to parse, so they are unchecked" -- is a real extension and
was recorded as one rather than built. The other four rules still emit prose
only; their adapters exist in `signals.py` and are unwired until each is
proven the same way.

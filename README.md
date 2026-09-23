# fiducial

*A fiducial is the reference mark a measurement is aligned against.*

Five static checks for work that carries **measured quantities**: a number that
claims to come from an experiment, a fit, or a literature source. Three look at
code and config, the fourth at the prose that repeats those numbers, and the
fifth at the index that says where the artefacts are.

Each rule asks one question of a number that claims to be measured: can you
still get back to what it was measured against?

```
$ fiducial literals --keys eta,kla_scale scripts/
scripts/bo/run_bo_comparison.py:53:8: [bare_literal] 'kla_scale' is declared
measured, but this assigns a literal with no provenance in reach. Record where
the number came from, or read it from the source that owns it.
    model.kla_scale = 0.776

fiducial literals: 1 violation(s) across 214 file(s), keys=eta,kla_scale
```

```
$ fiducial names configs/
configs/optimizer_run_v15b_flask_5d.yaml: name says v15b but contents say v16.
Rename the file or correct the fields -- a lineage token that disagrees with the
file's own fields misleads every human reader of the `extends` chain, even when
the loaded values are right.

fiducial names: 1 violation(s) among 127 comparable file(s) (231 scanned, mode=set)
```

## The five rules

**rule ① `literals`** — a key you have *declared* to be measured must not appear
as a hard-coded number, and must not be fetched with a silent default:

```python
eta = params.get("eta", 0.87)   # missing key -> a wrong fit, not a failure
model.kla_scale = 0.776         # measured where? by whom? against what?
```

**rule ② `names`** — a file name that carries a version token must not
contradict the versions the file's own machine-read fields declare.

**rule ③ `coverage`** — a key the project *declares* measured must have some
test that asserts something about it. Rules ① and ② ask whether a number is
shaped wrongly; this one catches the parameter that is plumbed correctly and
tested by nobody, where the suite stays green because the assertion that would
fail was never written.

```
$ fiducial coverage --spec .claude/params_spec.yaml -- tests/
nox_activity_scale: declared as a fitted/measured parameter, but it does not
appear anywhere in the test tree. Nothing checks it, and nothing will notice
when it changes.
```

**rule ④ `docs`** — a document that repeats a number from another document must
not state a value that contradicts it. Rules ①–③ all watch code; this one covers
the layer where the same drift kept landing unwatched — the PFD, the design
note, the spec summary that quietly carries last month's pH.

```
$ fiducial docs docs/
docs/PFD_reduction.md:161: pH asserted as 5.0 but docs/PROCESS_CONDITIONS.md carries 10.0
    U203d-pre pH 조정 → 5.0

fiducial docs: 1 violation(s) across 4 declared document(s) (54 scanned).
```

The comparison is **declared, not inferred**. A derived document names its
upstream in YAML front matter and lists the quantities it is repeating rather
than originating:

```yaml
---
ssot:
  source: docs/PROCESS_CONDITIONS.md
  repeats:
    pH: 10
    residence_h: 36
---
```

Two documents rarely use one word for one quantity, so a declaration may name
the upstream label after `as`:

```yaml
    목표 생산량 as 생산 규모: 2000
```

Values are read from prose, from row-oriented table cells (`| 반응 시간 | 24 h |`),
and from inside bold, inline code and mermaid node labels. A quantity whose
label is missing from *either* side is reported as a gap rather than counted
clean — a declaration that compares nothing produces the same `0 violations`
line as one that agrees, and the difference is the entire question. `--strict-gaps`
makes gaps block.

Only declared quantities are compared; the rest of the prose is left alone. The
alternative — scanning every document for every number and grouping by label —
was tried on a 54-document research corpus and drowns: the same figure appears
legitimately as prior art (`CN101904484A uses pH 5.0`), as a retracted value,
and as a target distinct from an operating point. Ranges (`pH 4~8`) are skipped
for the same reason: a band is not an operating point, and on the reference
corpus reading its lower bound as a value produced 2 findings out of 2, both
wrong.

**rule ⑤ `pointers`** — an index that registers artefacts must not name ones
that are not there. Rules ①–④ ask whether a number is trustworthy; this one
asks whether the artefact it came from can still be found.

```
$ fiducial pointers models/params/param_registry.json
run_260403_a: file = 'calibrated_run_260403_a_params.json' does
not exist, but that basename does, at
'archive/calibrated_run_260403_a_params.json'. The file moved and the
index was not updated; loading this entry raises FileNotFoundError.

models/params/param_registry.json: 118 of 303 pointers broken
(69 relocatable, 49 needing a decision)
```

Two pointer kinds are resolved: a `file` field against the filesystem, and a
`parent_id` against the other entries in the same index. Both are the same
defect — a reference whose target does not exist — and splitting them across
two tools would mean reading one file twice to ask one question.

The report separates what a tool can fix from what a person must decide, and
that split is the point:

| candidates | verdict | what it means |
|---|---|---|
| exactly 1 | relocatable | the file moved; `repair_plan()` proposes the correction |
| 0 | gone | nothing by that name exists — the artefact was deleted, or never written |
| 2 or more | ambiguous | **no proposal**; picking one would point the index at the wrong artefact |

A single "N broken" would hide that distinction and produce a number nobody can
act on. On the reference corpus the split was 69 / 19 / 0, and every repair was
therefore determined rather than guessed.

This is the rule the other four could not express. Rule ② compares a file's name
against its own contents; these entries are internally *consistent* and simply
describe a file that is not present. A consistency check cannot see a missing
referent.

### One key, two values

Rule ① reports each literal on its own, which is the right unit for "this
number has no provenance" and the wrong one for the defect the same scan walks
past:

```
$ fiducial literals --keys 'k_*' --conflicts src/
k_17: bound to 2 different values (0.1077, 44.0) across 2 places, spread 409x.
Both claim to be the same measured quantity, so at least one is wrong -- and
nothing in the code says which.
    src/model.py:402: 0.1077 (bare_literal, code)
    tests/test_burden.py:37: 44.0 (bare_literal, test)
```

That is a real case: the value was corrected in the code and three test files
still assert against the old one.

**The first version of this ran at 1 real finding in 20.** An adversarial audit
read every flagged site and refuted nineteen — the corpus was 93% test
fixtures, and fixtures disagree by design (`10x` monotonicity probes, `2x`
scenario variants, per-test dicts of round numbers), while a ninth value under
`titer` turned out to be eight unrelated packages sharing a generic name. So
the comparison is anchored: a conflict needs a value in non-test **code**, and
that is what the fixtures are compared against; keys are bucketed per package.
Twenty findings became five, and the real one survived.

It still cannot separate a stale fixture from a deliberate one — on that corpus
three keys are identical on every structural signal and one of them is the
defect. The finding is therefore always `needs_review` and never carries a
fix: proposing an edit would ask an agent to overwrite a test doing its job.

### YAML indexes

Rule ⑤ reads `.yaml` and `.yml` as well as `.json`, with a block-subset reader
rather than a dependency — a list container (`problems:`), keys ending
`_file`/`_files`, and a value that is a list of filenames are all resolved.

Checked against the 35 [PEtab benchmark models][petab]: 180 pointers, and one
index naming an SBML file that is not there. The reader is differential-tested
against PyYAML on every model in that corpus, and refuses anchors, block
scalars, flow collections and multi-document files rather than approximating
them.

[petab]: https://github.com/Benchmark-Models/Benchmark-Models-PEtab

## Why these, and not more

Both shapes are ordinary legal code, so the rules only have force once a key has
been declared to stand for something measured. That declaration is required:
`fiducial literals` refuses to run without `--keys`, because a checker that
guessed which numbers were physical would be wrong constantly and switched off
within a day.

A declaration can name a family instead of a spelling. Another project calls
one quantity `k_17`, `kcat_r6` or `Titer_gL`, and an exact name only finds the
spelling you already knew. `--keys 'k_*,*titer*'` declares the family; patterns
match case-insensitively, exact names stay exact. The number is looked for
wherever a project keeps it: `eta = …`, `obj.eta = …`, `params["eta"] = …`,
`{"eta": …}`, `dict(eta=…)`, and a signature default `def f(eta=…)`, which is
the same silent fallback as `.get("eta", …)`. A keyword argument to any other
call names the callee's parameter, not yours: pymoo's `SBX(eta=15)` is a
distribution index, and reading those by default took one codebase from 43
findings to 217. `--call-keywords` (or `literals_call_keywords = true`) turns
them on for a codebase whose constructors take measured values directly, like
`Stream(price=0.73)`.

Where this departs from its neighbours: [drift-linter][dl] and
[scicode-lint][sl]'s `rep-003` both classify `dict.get(key, default)` as the
*safe* form — absence is handled, so the code is fine. Against a declared
measured key fiducial inverts that judgement. The default **is** the defect,
because it suppresses the loud failure that would have surfaced the missing
measurement. The inversion is the contribution; the AST walk is not novel, and a
`semgrep` `metavariable-regex` rule expresses much of the same matching.

[dl]: https://pypi.org/project/drift-linter/
[sl]: https://arxiv.org/abs/2603.17893

## An empty check is an error, not a pass

```
0  clean
1  violations found
2  the check could not be performed
```

Exit `2` covers an empty `--keys`, zero matched files, unparseable source, an
index carrying no resolvable pointer, and — for rule ② — files read of which
none were comparable.
This package exists because a scanner whose path globs had gone stale printed
`OK — no violations across 0 file(s)` and exited `0` for long enough that
nobody questioned it. A check that cannot fail is worse than no check, because
it reads as evidence.

The same principle runs in CI here: the reference-corpus test skips when the
private corpus is absent, and the workflow then *asserts that a skip is what
happened* rather than accepting a green suite.

## When the caller is an agent

A person who sets parameters by hand rarely needs this checker — they already
know where their numbers came from. A model writing the code does not, and
`params.get("eta", 0.87)` is exactly what one does when it needs a number it
does not have. The rules matter most when nobody human chose the value.

So every rule takes `--format=json` and emits findings a program can act on:

```
$ fiducial pointers --format=json models/params/param_registry.json
```

```json
{
  "version": 1,
  "summary": {"total": 3, "violations": 3, "cannot_check": 0,
              "auto_fixable": 1, "needs_human": 2},
  "findings": [
    {
      "rule": "pointers", "entry": "run_260403_a",
      "status": "violation", "confidence": "certain",
      "message": "… the file moved and the index was not updated …",
      "fix": {"applicability": "safe", "apply": "auto",
              "edit": {"field": "file", "to": "archive/calibrated_run_260403_a_params.json"}},
      "action": "Apply the fix. It is determined — there is exactly one correct repair …"
    }
  ]
}
```

**Two axes, because one cannot carry it.** `confidence` says whether the
finding is real; `fix` says whether the caller may repair it alone. They are
independent, and rule ⑤ is the proof:

| case | confidence | fix | what an agent does |
|---|---|---|---|
| one candidate | `certain` | `safe` / `auto` | applies it |
| no candidate | `certain` | *(absent)* | asks — nothing in the repo has the answer |
| several candidates | `certain` | `unsafe` / `suggest_only` | shows the candidates, picks none |
| no pointers at all | — | *(absent)* | `status: cannot_check` — fix the invocation |

All three violations are equally certain. What differs is who may act, so a
single severity ladder would have to rank cases that do not differ in severity
at all — and an agent reading one number would fill in a path for the case that
has no answer.

Rule ② runs the other way: its base rate is 1.6%, so it is `needs_review` even
though its repair is mechanical.

Across the five, what an agent may do differs by what the rule can know:

| rule | fix | why |
|---|---|---|
| ① `literals` | none | the tool knows the number has no provenance, not what the provenance was — emitting a fix would invite the substitution the rule exists to catch |
| ② `names` | `unsafe` / `suggest_only` | two repairs resolve it (rename, or correct the fields) and only the author knows which was meant |
| ③ `coverage` | none | writing the missing test is authorship, not an edit |
| ④ `docs` | `safe` / `auto` | the declaration names its upstream, so the correct value is known rather than guessed |
| ⑤ `pointers` | depends | see the table above |

Rules ① and ③ deliberately emit no `fix` at all. An agent *can* write a test or
track down a source, and the `action` text says so — but that is authorship,
and it must not arrive through the same field as a mechanical edit.

The vocabulary is borrowed rather than invented. `applicability: safe | unsafe`
is Ruff's, measured from `ruff check --output-format=json` rather than read
from its docs; `apply: auto | suggest_only` is ESLint's split between a fix it
applies and a suggestion it only offers. `message` is the rule's own prose,
unchanged — an agent deciding what to do needs the reasoning as much as a
person does.

`"fix" in finding` answers "is this automatable at all", and
`finding["fix"]["apply"] == "auto"` answers "may I do it without asking".
Nothing has to be parsed out of prose.

**Not SARIF, deliberately.** SARIF's `level` has no value for *the check could
not run*, and `kind: notApplicable` means "did not apply here" rather than
"should have been checked and was not" — which is this package's entire
argument. Its `fixes[]` carries no safety grade either, so both fields that
matter here would land in non-standard `properties`. A five-rule tool does not
need a multi-level envelope to say that.

## Measured behaviour

Against the corpus the rules were derived from (1,522 Python files, 231 YAML):

| | result |
|---|---|
| rule ② comparable files | 127 |
| rule ② `--mode strict` | 2 (1.6%) |
| rule ② `--mode set` | 3 (2.4%) |
| rule ① after neutral split | 115 (from 705) |

**Quote the denominator.** The base rate is low: this is a real defect class,
not a widespread one. `strict` requires the name and contents to share no
version at all; `set` also catches partial-overlap lies — one archived file is
named `v8_v3` while its `fit_json` is `v8_v4`, and its own comment admits
"legacy name only". `set` is the default because that extra case was real and
cost nothing in noise on this corpus.

For rule ①, 575 of 705 raw hits (82%) defaulted to exactly `0.0` or `1.0` —
`setdefault("vmax_futile_nadph", 0.0)` is a term switched off, not a fabricated
measurement. Those are split out by default and returned by `--include-neutral`,
because "the term was off and nobody noticed" is a real failure mode too, just a
different one.

## Adopting it in a new repo

Everything below is optional — the subcommands still take explicit flags. But
a project that writes this once stops re-arguing it on every invocation:

```toml
# pyproject.toml
[tool.fiducial]
rules = ["literals", "names", "docs", "pointers"]

keys            = ["eta", "kla_scale"]     # rule (1): the measured keys
literals_paths  = ["src/"]
names_paths     = ["configs/"]
docs_paths      = ["docs/"]
pointers_paths  = ["models/params/param_registry.json"]   # rule (5)

spec            = ".fiducial/params_spec.yaml"   # rule (3)
tests_paths     = ["tests/"]
baseline        = ".fiducial/coverage_baseline.txt"
```

Then:

```
$ fiducial check
```

`check` runs what the project declared and combines the verdicts
**pessimistically**: any rule that could not run makes the whole command exit
`2`, even when another rule found violations. "Could not check" outranks
"checked and found things", because a partial scan reported as a result is the
failure this package exists to refuse. A `check` that would run *no* rule is
itself exit `2` — a config naming nothing produces the same reassuring silence
as a clean repo.

A project with no `pyproject.toml` can use a standalone `.fiducial.toml`
holding the same keys without the `[tool.fiducial]` header.

`python -m fiducial` works from a checkout, without installing.

### Every tuned list is a setting

The rules were measured on one corpus, and the corpus shows in the defaults:
which config fields declare a file's own version, which are prose, which
defaults mean "this term is switched off". Each is exposed twice —

```toml
self_declaring_keys        = ["fit_ref"]   # replace the default outright
extend_self_declaring_keys = ["fit_ref"]   # add to it, keeping the defaults
```

`extend_` is [ruff's convention][ruff-extend] and exists because replacement is
the wrong default for adoption: adding one field name should not silently drop
the six that were there. The pairs are `self_declaring_keys`, `prose_keys` and
`reference_keys` (rule ②), plus `neutral_defaults` (rule ①) and
`extend_history_markers` (rule ④).

A misspelled setting is **reported, not ignored** — it would otherwise leave
the default in force while the author believes they changed it, which is the
same silent miscalibration the rules themselves are about.

[ruff-extend]: https://docs.astral.sh/ruff/settings/

### Languages

Rule ④ reads values out of prose, and prose has a language. Korean particles
(`pH 10이`), past-tense markers (`였다`) and citation words (`선례`, `특허`) live
in a locale pack rather than the core:

```toml
locales = ["ko"]     # `en` is always active; naming a locale ADDS to it
```

Naming a locale the package does not carry is an error, not a fallback: the
text would be scanned with the wrong patterns while the config said otherwise.

### pytest

Installing fiducial also installs a pytest plugin. It stays silent unless you
name a spec:

```
$ pytest --fiducial-spec .fiducial/params_spec.yaml

fiducial rule (3): 53 declared key(s)
  gated in source                        : 19
  gated by a test that RAN this session  : 19
  (every gate found in source also ran)
```

`fiducial coverage` asks whether an assertion naming a key exists in the
source. Inside a session a second question is answerable and the CLI cannot
reach it: **did that assertion run?** A test skipped by a marker, deselected by
`-k`/`-m`, dropped by `--lf`, or living in a module that failed to import still
satisfies rule ③ from the source while nothing checked the parameter on that
run. The two numbers above are that distinction, and the gap between them is
the finding.

`--fiducial-strict` fails the session when a declared key has no gate among
the tests that ran.

What it does not claim: that a test *ran* says nothing about whether its
assertion is sensitive to the parameter. That is mutation testing's question,
and mutation testing answers it by running the suite with the value changed.
Neither this plugin nor rule ③ attempts it.

### Python 3.10

`tomllib` is stdlib only from 3.11. On 3.10 the config is read by a small
built-in parser covering the subset above, which **raises on anything it does
not understand** rather than skipping it. It was checked differentially against
`tomllib` on 18 inputs; two shapes that disagreed silently (`\"` escapes and
dotted keys) are now refused outright. A config that means one thing on 3.10
and another on 3.13 is a defect that only surfaces on somebody else's machine.

## Install

```bash
pip install fiducial
```

Stdlib only, Python ≥3.10, no dependencies.

### pre-commit

```yaml
- repo: https://github.com/jahyunlee00299/fiducial
  rev: v0.1.0
  hooks:
    - id: fiducial-names
    - id: fiducial-literals
      args: [--keys, "eta,kla_scale,xr_activity_scale"]
```

The hook builds its own isolated environment. It deliberately does not invoke a
bare `python`: an earlier hook in this author's setup did, resolved to the wrong
interpreter on one machine, and blocked *every* commit including clean ones. A
guard that blocks correct work gets disabled, and a disabled guard protects
nothing.

That path is exercised by `tests/test_precommit_framework.py` rather than
assumed — pre-commit builds the venv, blocks a violating repo, and passes a
clean one. It had sat in this repo as "declared, unproven" for exactly as long
as it took someone to run it.

If your configs carry no version tokens at all, rule ② will report that it
compared nothing and exit `2`, which pre-commit treats as a failure. Say so
once rather than deleting the hook:

```yaml
    - id: fiducial-names
      args: [--allow-zero-comparable]
```

## What rule (3) does not tell you

The classifier was rewritten four times against the corpus it was built on, and
each time a band of keys it had called "no gate" turned out to be gated by a
mechanism that leaves no parameter name in the source: values compared out of a
golden JSON at runtime, keys held in a module constant the assert names instead,
keys in a local tuple the test body iterates, keys that are values in a mapping
a generic loop walks, keys set by `setattr` whose gate asserts a downstream
physical consequence rather than the value itself.

Each round shrank the false-gap band without closing it. So a `mentioned-only`
verdict means **"no gate found by the patterns implemented here"**, not "no
gate". Only `absent` — the key appears nowhere in the test tree at all — is
wired to block.

The error runs both ways, and the other direction is worse. In that same corpus
three parameters are set by a test that asserts `rate == 0` at a manufactured
equilibrium, where the rate's numerator is structurally zero and those three
appear only in the denominator: the assertion holds whatever they are. A gate
that cannot fail, wearing the shape of one. Widening the patterns until such a
key counts as `asserted` would trade a false gap — which costs someone an
afternoon — for a false gate, which costs the thing the gate was for.

Whether an assertion is actually sensitive to a parameter is mutation testing's
question, and mutation testing answers it by running the suite. fiducial does
not attempt it.

## What rule (4) does not tell you

It compares a copy against the original; it does not check that the original is
right. And it reads one hop only — if A declares B and B declares C, A is
checked against B alone.

Two shapes are invisible to it. A column-oriented table, where the label sits in
the header row and the value several rows below, carries no single line with
both (a row-oriented table is read). And a quantity the document states without
naming — "이 조건에서 10으로 유지한다" — cannot be matched to a label at all.

Both are cases where the rule stays silent, so neither is caught by "no
findings". That is why a gap is reported loudly and `--strict-gaps` exists: the
honest failure mode of this rule is a declaration that quietly checks nothing,
and the only defence is to say so out loud.

## Scope

fiducial does not version data (use [DVC][dvc]), validate dataframes (use
[pandera][pa]), or pin regression baselines (use [pytest-regressions][pr]). It
asks one question those tools leave open: **is this number allowed to be here at
all?**

Those boundaries are real rather than rhetorical: a pandera adapter was planned
for this package and dropped after measuring. pandera appears in 0 files across
the four repositories this was built for, while `import pandas` appears in 382,
and every rule here is static where pandera validates at runtime. The seam that
actually reaches runtime is the pytest plugin below.

[dvc]: https://dvc.org/
[pa]: https://pandera.readthedocs.io/
[pr]: https://pytest-regressions.readthedocs.io/

## License

MIT

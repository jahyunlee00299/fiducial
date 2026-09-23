# Four axes, one question

Every tool here asks a version of the same thing: **before you believe the
result, does the thing it rests on actually hold?**

```
① environment      ② data            ③ parameters      ④ results
compat-check       (open)            fiducial          pytest-regressions
                                                       syrupy, etc.

"will it even     "which dataset    "where did this   "does it come out
 install here"     produced this     number come        the same way
                   constant"         from"              twice"
```

They are not a pipeline. Each one is a gate that has to hold at a different
*moment*, and wiring them as a single sequential run would put three of them
in the wrong place.

---

## When each gate holds

```
adopting a dependency ─── compat-check ─────────────── once, at decision time
       │
       ▼
 data lands / recalibrates ── (axis ② ) ─────────────── when the data changes
       │
       ▼
   every commit ───────── fiducial (pre-commit) ─────── continuously
       │
       ▼
   every test run ─────── pytest-regressions ────────── continuously
```

`compat-check` takes an *external* target as an argument (`compat-check
https://github.com/pallets/flask`): it answers "may I bring this in". It is
not a pre-commit hook and should not become one — a hook that re-resolves the
whole dependency tree on every commit is a hook that gets disabled.

`fiducial` takes *this* repository's files. It runs on every commit through
`.pre-commit-hooks.yaml`, and through `pytest11` inside the test session.

---

## The one contract all four share

```
0   clean          it ran, it compared things, it found nothing wrong
1   violations     it ran and found something
2   cannot check   it could not run: empty key list, zero matched files,
                   an unparseable source, a resolver that never answered
```

`compat-check` and `fiducial` already implement this identically, which is
what lets a caller treat them as one family without either depending on the
other.

Exit 2 is the axis-crossing part. Every one of these tools was written after
the same failure — a check that reported success because it had checked
nothing — and each names it in its own domain:

- `compat-check`: both `uv` and `pip` are fail-fast, so a single dry-run
  reports only the *first* unsatisfiable requirement and the second hides
  behind it. It drops each failure and retries until all of them surface.
- `fiducial`: a scanner whose path globs had gone stale printed `OK — no
  violations across 0 file(s)` for long enough that nobody questioned it.

Two tools, two domains, one failure mode.

---

## Where they actually touch

### ① → ③ : checking a repository you do not own

This is the real coupling, and it is the one this project hit for itself.

`fiducial` is useful on foreign code — it found a 409x stale parameter in a
public research repository. But to run it there you first have to get that
repository into a state where it can be read, and "it does not install here"
is a different answer from "it has no findings":

```bash
# 1. can this environment even hold the thing?
compat-check https://github.com/some/repo           # 0 / 1 / 2

# 2. only then is a clean fiducial run meaningful
fiducial literals --keys 'k_*' --format json path/to/clone
```

Skipping step 1 produces the exact confusion both tools exist to prevent: a
scan that reports nothing because the code never loaded.

Run against the public research repository this project was tested on, both
steps answered, and step 1 was not a formality:

```
compat-check -> exit 1: conflicts found
fiducial     -> exit 1: 12 findings, all needing a person
```

That repository does **not** resolve cleanly in this environment. A `fiducial`
run there is still worth having — it reads source, not an installed package —
but the two exit codes mean different things and collapsing them would have
hidden one behind the other. Had step 1 returned 2, a clean step 2 would have
meant nothing at all.

### ③ → ④ : a number that changed, and a result that did not

`pytest-regressions` freezes an output and fails when it moves.
`fiducial` explains *why* it moved. Run in the other order and a regression
diff is a mystery; run this way and it has a cause:

```
pytest-regressions:  "MPSP moved 3.17%"
fiducial --conflicts: "k_17 is 0.1077 in the model and 44.0 in three fixtures"
```

Neither tool can produce the other's half.

### ② : the axis that is open

The gap is not data *validation* — pandera and Great Expectations check values,
DVC versions files, and both are mature. The gap is the **binding between a
derived constant and the dataset that produced it**, machine-checkable.

`fiducial`'s rule ⑤ is already the mechanically detectable half of it: an index
that claims "this parameter came from that fit file" is checkable, and on one
research registry **88 of 152 entries did not resolve**. What is missing is the
other half — a calibration constant carrying its measurement date, instrument,
raw-data link and valid range, so that "this slope came from that run" is a
claim a tool can refuse.

A measured case, from an instrument-analysis repo: a `StandardCurve` accepts a
pre-fitted slope and intercept pasted straight into YAML, defaults `r2` to 1.0,
and does not stop `predict()` from extrapolating outside the calibrated range.
An unsourced calibration constant, wearing a perfect R², converting every peak
area into a concentration.

---

## What this is not

It is not one package. The axes differ in maturity, in competition and in
audience, and merging them would force the mature ones to move at the pace of
the open one. `compat-check` and `fiducial` ship separately, on separate
release cycles, and neither imports the other.

What they share is the exit contract and the sentence at the top of this file.
That is enough to compose them in a shell script, a CI job or an agent's
instructions, and it costs neither of them a dependency.

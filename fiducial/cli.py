"""fiducial command line entry point.

Two subcommands, one per rule:

    fiducial literals --keys eta,kla_scale -- src/**/*.py
    fiducial names -- configs/**/*.yaml

Exit codes follow the grep/pytest convention that automation already
understands: ``0`` clean, ``1`` violations found, ``2`` the check could not be
performed.

The distinction between ``1`` and ``2`` is the whole point.  A checker that
reports "0 violations" because it matched no files, or because its key list was
empty, is not clean -- it is blind, and a blind check that exits 0 gets believed.
This package was built after exactly that failure: a scanner whose path globs
had gone stale printed ``OK no violations across 0 file(s)`` and exited 0 for
long enough that nobody questioned it.  So an empty scan is an error here, not a
pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as _config
from . import coverage as _coverage
from . import docs as _docs
from . import literals as _literals
from . import locales as _locales
from . import names as _names
from . import pointers as _pointers
from . import runner as _runner
from . import signals as _signals

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_CANNOT_CHECK = 2


def _expand(patterns: list[str]) -> list[Path]:
    """Files named by literal paths, directories, or globs.

    An absolute glob cannot go through ``Path(".").glob()`` -- pathlib raises
    ``NotImplementedError: Non-relative patterns are unsupported``, which is how
    a caller passing ``/abs/dir/*.py`` got a traceback instead of a file list.
    Split such a pattern into its fixed root and the relative remainder, and
    glob from that root.
    """
    out: list[Path] = []
    for pat in patterns:
        p = Path(pat)
        if p.is_file():
            out.append(p)
            continue
        if p.is_dir():
            out.extend(q for q in p.rglob("*") if q.is_file())
            continue

        if p.is_absolute():
            # Walk down to the last component with no glob metacharacter.
            anchor = Path(p.anchor)
            parts = p.relative_to(anchor).parts
            fixed = [x for x in parts if not any(c in x for c in "*?[")]
            base = anchor.joinpath(*fixed[: len(fixed)]) if fixed else anchor
            # Back off until `base` is a real directory, moving the rest into
            # the pattern.
            rest = parts[len(fixed):]
            while not base.is_dir() and base != anchor:
                rest = (base.name,) + tuple(rest)
                base = base.parent
            pattern = "/".join(rest) if rest else "*"
        else:
            base, pattern = Path("."), pat

        if not base.is_dir():
            continue
        try:
            out.extend(q for q in base.glob(pattern) if q.is_file())
        except (NotImplementedError, ValueError):
            continue
    return sorted(set(out))


def _load_config(args: argparse.Namespace) -> _config.Config:
    """The project's settings, or all-defaults.

    A config that exists but cannot be read is fatal here rather than a
    warning. Falling back to defaults would run every rule with the wrong
    tuning while reporting success -- the same false evidence the rules
    themselves exist to remove.
    """
    explicit = getattr(args, "config", None)
    if explicit:
        return _config.load(Path(explicit))

    # Discover from what is being SCANNED, not from where the command runs.
    # Measured 260923: `fiducial names <foreign repo>` run from inside this
    # package's own checkout picked up our `names_allow_zero_comparable =
    # true` and exited 0 on a foreign tree where the rule compared nothing;
    # the same command from a neutral directory exited 2. The verdict on a
    # tree must not depend on the caller's cwd.
    paths = list(getattr(args, "paths", None) or [])
    if not paths:
        return _config.load(None)
    found = {_config.find_config(_scan_anchor(p)) for p in paths}
    if len(found) > 1:
        names = sorted(str(f) if f else "<none>" for f in found)
        print(
            "fiducial: the scanned paths belong to different configs "
            f"({', '.join(names)}), so no single set of settings applies. "
            "Scan them separately, or pass --config.",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_CANNOT_CHECK)
    (path,) = found
    return _config.Config() if path is None else _config.load(path)


def _scan_anchor(pattern: str) -> Path:
    """The existing directory a path, directory or glob is rooted in."""
    p = Path(pattern)
    fixed = []
    for part in p.parts:
        if any(c in part for c in "*?["):
            break
        fixed.append(part)
    base = Path(*fixed) if fixed else Path(".")
    if base.is_file():
        base = base.parent
    while not base.is_dir() and base != base.parent:
        base = base.parent
    return base.resolve()


def _locale_for(cfg: _config.Config) -> "_locales.LocaleSet":
    return _locales.resolve(cfg.locales, cfg.extend_history_markers)


def _pick(flag, configured, default=None):
    """An explicit flag wins; otherwise the config; otherwise the default."""
    if flag not in (None, (), ""):
        return flag
    if configured not in (None, (), ""):
        return configured
    return default


def _run_literals(args: argparse.Namespace, cfg: _config.Config | None = None) -> int:
    cfg = cfg if cfg is not None else _load_config(args)
    raw = args.keys if getattr(args, "keys", None) else ",".join(cfg.keys)
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        print(
            "fiducial: no declared keys, so every check would pass "
            "vacuously. Pass --keys, or set keys = [...] under "
            "[tool.fiducial].",
            file=sys.stderr,
        )
        return EXIT_CANNOT_CHECK

    paths = list(args.paths) or list(cfg.literals_paths)
    files = [f for f in _expand(paths) if f.suffix == ".py"]
    if not files:
        print(
            f"fiducial: matched 0 python files from {paths!r}. "
            "A scan over nothing reports no violations no matter how broken the "
            "code is -- check the paths.",
            file=sys.stderr,
        )
        return EXIT_CANNOT_CHECK

    findings = []
    unparsed: list[tuple[Path, str]] = []
    for f in files:
        try:
            findings.extend(
                _literals.scan_file(
                    f,
                    keys,
                    include_neutral=args.include_neutral or cfg.include_neutral,
                    neutral_defaults=cfg.neutral_defaults,
                    call_keywords=(
                        getattr(args, "call_keywords", False)
                        or cfg.literals_call_keywords
                    ),
                )
            )
        except SyntaxError as exc:
            # One broken file must not abort the sweep. Measured: a single
            # pre-existing syntax error in a 1,500-file tree took the whole scan
            # to exit 2, so a sweep over a real repo reported nothing at all.
            # Collect them, scan the rest, and report both -- a file that could
            # not be parsed is unchecked, and saying so is the point.
            unparsed.append((f, str(exc)))

    if unparsed and len(unparsed) == len(files):
        for f, exc in unparsed:
            print(f"fiducial: {f}: cannot parse ({exc})", file=sys.stderr)
        print(
            f"fiducial: every one of {len(files)} file(s) failed to parse; "
            "nothing was checked.",
            file=sys.stderr,
        )
        return EXIT_CANNOT_CHECK

    if getattr(args, "format", "text") == "json":
        env = _signals.Envelope(_signals.from_literals(findings))
        print(env.to_json())
        s = env.summary()
        if s["violations"] == 0 and s["cannot_check"]:
            return EXIT_CANNOT_CHECK
        return EXIT_VIOLATIONS if s["violations"] else EXIT_OK

    for find in findings:
        print(find.explain())

    checked = len(files) - len(unparsed)
    print(
        f"\nfiducial literals: {len(findings)} violation(s) "
        f"across {checked} file(s), keys={','.join(keys)}"
    )
    if unparsed:
        # Never fold these into "clean". An unparsed file is an UNCHECKED file.
        print(
            f"fiducial: {len(unparsed)} file(s) could not be parsed and were "
            "NOT checked:",
            file=sys.stderr,
        )
        for f, exc in unparsed:
            print(f"  {f}: {exc}", file=sys.stderr)
    return EXIT_VIOLATIONS if findings else EXIT_OK


def _run_names(args: argparse.Namespace, cfg: _config.Config | None = None) -> int:
    cfg = cfg if cfg is not None else _load_config(args)
    paths = list(args.paths) or list(cfg.names_paths)
    files = [f for f in _expand(paths) if f.suffix in {".yaml", ".yml", ".json"}]
    if not files:
        print(
            f"fiducial: matched 0 config files from {paths!r}. "
            "Check the paths -- an empty scan is not a clean scan.",
            file=sys.stderr,
        )
        return EXIT_CANNOT_CHECK

    mode = args.mode or cfg.names_mode
    prose = _config.resolve_set(
        _names.PROSE_KEYS, cfg.prose_keys, cfg.extend_prose_keys
    )
    reference = _config.resolve_set(
        _names.REFERENCE_KEYS, cfg.reference_keys, cfg.extend_reference_keys
    )
    selfdecl = _config.resolve_set(
        _names.SELF_DECLARING_KEYS,
        cfg.self_declaring_keys,
        cfg.extend_self_declaring_keys,
    )

    args_allow = getattr(args, "allow_zero_comparable", False)

    verdicts = _names.scan(files, mode, prose, reference, selfdecl)
    if getattr(args, "format", "text") == "json":
        env = _signals.Envelope(_signals.from_names(verdicts, mode))
        print(env.to_json())
        s = env.summary()
        if s["violations"] == 0 and s["cannot_check"]:
            return EXIT_CANNOT_CHECK
        return EXIT_VIOLATIONS if s["violations"] else EXIT_OK

    for v in verdicts:
        print(v.explain(mode))

    comparable = sum(
        1
        for f in files
        if (lambda x: x.name_tokens and x.content_tokens)(
            _names.inspect_file(f, prose, reference, selfdecl)
        )
    )
    print(
        f"\nfiducial names: {len(verdicts)} violation(s) "
        f"among {comparable} comparable file(s) ({len(files)} scanned, mode={mode})"
    )

    if verdicts:
        return EXIT_VIOLATIONS

    # Files were found, and not one of them could be compared: every file
    # either carries no version token in its name or declares none in its
    # fields. That is BLIND, not clean, and it had been exiting 0 -- the one
    # place this package granted itself the pass it refuses everywhere else.
    # Rule (1) refuses an empty --keys, rule (4) refuses a corpus where nothing
    # declares an SSOT, and the CLI refuses a zero-file match, all on the same
    # reasoning: a check that cannot fail gets believed.
    #
    # Found 260923 by pointing `fiducial check` at this very repository: one
    # YAML scanned, none comparable, reported "clean", exit 0.
    #
    # Why it needs an off switch, unlike the others. Comparability here is a
    # property of the files, decided after reading them, not of the invocation
    # -- so a project whose configs legitimately carry no version tokens would
    # get exit 2 on every commit forever. That is the shape that gets a guard
    # bypassed, and a bypassed guard protects nothing. The measured case is in
    # this repo's own ledger: one project's 14 SSOT configs carry no version tokens at
    # all. Such a project sets `names_allow_zero_comparable = true` ONCE, in
    # the diff, where a reviewer sees it -- rather than discovering by accident
    # that the rule has been silent for a year.
    if comparable == 0 and not (args_allow or cfg.names_allow_zero_comparable):
        print(
            f"fiducial: {len(files)} config file(s) were read and NONE could "
            "be compared -- no file carries a version token in both its name "
            "and its own fields, so this rule checked nothing. That is blind, "
            "not clean. If your configs genuinely do not version their names, "
            "say so once with `names_allow_zero_comparable = true` under "
            "[tool.fiducial] (or --allow-zero-comparable) and this becomes a "
            "pass.",
            file=sys.stderr,
        )
        return EXIT_CANNOT_CHECK

    return EXIT_OK


def _run_coverage(args: argparse.Namespace, cfg: _config.Config | None = None) -> int:
    cfg = cfg if cfg is not None else _load_config(args)
    spec_name = _pick(getattr(args, "spec", None), cfg.spec)
    if not spec_name:
        print(
            "fiducial: no spec. Pass --spec, or set spec = \"...\" under "
            "[tool.fiducial]. Without a declaration there is nothing to "
            "check coverage OF.",
            file=sys.stderr,
        )
        return EXIT_CANNOT_CHECK
    spec = Path(spec_name)
    if not spec.is_file():
        print(f"fiducial: spec not found: {spec}", file=sys.stderr)
        return EXIT_CANNOT_CHECK
    try:
        keys = _coverage.load_declared_keys(
            spec, _pick(args.field, cfg.spec_field, "learnable_keys")
        )
    except ValueError as exc:
        print(f"fiducial: {exc}", file=sys.stderr)
        return EXIT_CANNOT_CHECK

    test_paths = list(args.tests) or list(cfg.tests_paths)
    tests = [f for f in _expand(test_paths) if f.suffix == ".py"]
    data = [f for f in _expand(list(args.data or ()) or list(cfg.data_paths))
            if f.suffix == ".json"]
    try:
        results = _coverage.analyse(keys, tests, data)
    except ValueError as exc:
        print(f"fiducial: {exc}", file=sys.stderr)
        return EXIT_CANNOT_CHECK

    absent = [r for r in results if r.level is _coverage.Coverage.ABSENT]
    mentioned = [r for r in results if r.level is _coverage.Coverage.MENTIONED]
    asserted = [r for r in results if r.level is _coverage.Coverage.ASSERTED]
    pinned = [r for r in results if r.level is _coverage.Coverage.PINNED]

    level = _pick(args.level, cfg.coverage_level, "absent")
    reported = absent if level == "absent" else absent + mentioned

    # A baseline holds the gaps that already existed. Without it, adding ONE
    # properly gated key still fails because the project's 11 pre-existing gaps
    # come along -- measured, and it is the failure mode that gets a hook
    # bypassed on its first real use. New gaps block; old ones are reported and
    # do not.
    baseline: set[str] = set()
    baseline_name = _pick(getattr(args, "baseline", None), cfg.baseline)
    if baseline_name:
        bp = Path(baseline_name)
        if bp.is_file():
            baseline = {
                ln.strip()
                for ln in bp.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")
            }
        elif not args.write_baseline:
            print(
                f"fiducial: baseline not found: {bp}. Create it with "
                "--write-baseline, or drop --baseline to check every key.",
                file=sys.stderr,
            )
            return EXIT_CANNOT_CHECK

    # An explicit, reasoned waiver in the spec outranks the gate. Some keys
    # SHOULD NOT have a gate, and the project knows why: `kd_e_xr`/`kd_e_enzyme_a` are
    # marked "deliberately absent" in the reference project's golden builder,
    # because they are not __init__ kwargs and travel a second configuration
    # path. Forcing a gate there would produce a test that asserts a fiction.
    #
    # The waiver lives in the SPEC, next to the declaration, not in a flag --
    # so it is reviewed with the parameter and shows up in the diff. Each entry
    # must carry a reason; a bare key is rejected, because "we skipped it" with
    # no reason recorded is the thing that rots.
    waived = _coverage.load_waivers(
        spec, _pick(args.waiver_field, cfg.waiver_field, "coverage_waivers")
    )
    if waived:
        reported = [r for r in reported if r.key not in waived]

    if getattr(args, "format", "text") == "json":
        env = _signals.Envelope(_signals.from_coverage(reported, baseline))
        print(env.to_json())
        s = env.summary()
        if s["violations"] == 0 and s["cannot_check"]:
            return EXIT_CANNOT_CHECK
        return EXIT_VIOLATIONS if s["violations"] else EXIT_OK


    if args.write_baseline:
        bp = Path(baseline_name)
        header = (
            "# fiducial rule (3) baseline -- keys whose gap predates the gate.\n"
            "# Shrink this file; never grow it. A key removed from here can never\n"
            "# come back, which is the ratchet.\n"
        )
        body = "".join(f"{r.key}\n" for r in sorted(reported, key=lambda x: x.key))
        bp.write_text(header + body, encoding="utf-8")
        print(f"fiducial: wrote {len(reported)} pre-existing gap(s) to {bp}")
        return EXIT_OK

    grandfathered = [r for r in reported if r.key in baseline]
    reported = [r for r in reported if r.key not in baseline]

    for r in reported:
        print(r.explain())

    print(
        f"\nfiducial coverage: {len(keys)} declared key(s) vs {len(tests)} test "
        f"file(s) -- {len(asserted)} asserted, {len(pinned)} pinned, "
        f"{len(mentioned)} mentioned-only, {len(absent)} absent. "
        f"Reporting level={level}: {len(reported)} gap(s)."
    )
    if waived:
        print(
            f"  ({len(waived)} key(s) waived in {spec.name} with a recorded "
            "reason. A waiver is a decision, not a pass -- it is in the diff.)"
        )
    if grandfathered:
        print(
            f"  ({len(grandfathered)} pre-existing gap(s) held in the baseline and "
            "not blocking. They are still gaps.)"
        )
    if level == "absent" and mentioned:
        print(
            f"  ({len(mentioned)} key(s) appear in tests but inside no assert; "
            "re-run with --level mentioned to list them.)"
        )
    print(
        "  Appearing in an assert is necessary, not sufficient -- this reports "
        "the floor and certifies nothing."
    )
    return EXIT_VIOLATIONS if reported else EXIT_OK


def _run_docs(args: argparse.Namespace, cfg: _config.Config | None = None) -> int:
    cfg = cfg if cfg is not None else _load_config(args)
    paths = list(args.paths) or list(cfg.docs_paths)
    files = [f for f in _expand(paths) if f.suffix in {".md", ".markdown"}]
    if not files:
        print(
            f"fiducial: matched 0 markdown files from {paths!r}. "
            "An empty scan is not a clean scan -- check the paths.",
            file=sys.stderr,
        )
        return EXIT_CANNOT_CHECK

    root_name = _pick(getattr(args, "root", None), cfg.docs_root)
    root = Path(root_name) if root_name else None
    tol = args.tol if args.tol else cfg.tol
    findings, gaps, declared, errors, units = _docs.scan(
        files, root=root, rel_tol=tol, locale=_locale_for(cfg)
    )

    if getattr(args, "format", "text") == "json":
        env = _signals.Envelope(
            _signals.from_docs(findings, gaps, errors)
            + _signals.from_units(units)
        )
        print(env.to_json())
        s = env.summary()
        if s["violations"] == 0 and s["cannot_check"]:
            return EXIT_CANNOT_CHECK
        return EXIT_VIOLATIONS if s["violations"] else EXIT_OK

    for f in findings:
        print(f.explain())
    # A unit mismatch is only reachable when the NUMBERS agree, so it
    # never appears in the list above -- it has to be printed in its
    # own right or the 60x error stays invisible.
    for u in units:
        print(u.explain())
    # Gaps are printed by default. A declared quantity that is compared against
    # nothing produces the same "0 violations" line as one that agrees, and the
    # difference is the whole question this rule answers.
    for g in gaps:
        print(g.explain())

    for p, msg in errors:
        print(f"fiducial: {p}: {msg}", file=sys.stderr)

    # The heart of this rule. A corpus where nothing declares an SSOT compares
    # nothing, and reporting that as "0 violations" is precisely the blindness
    # this package refuses. Measured at adoption on the reference corpus: 0 of
    # 53 documents carried front matter.
    if not declared:
        print(
            f"fiducial: none of {len(files)} document(s) declare an `ssot:` "
            "block, so no comparison was performed. This rule checks documents "
            "against the source they name; with nothing named it is blind, not "
            "clean. Add front matter to the derived documents:\n"
            "    ---\n"
            "    ssot:\n"
            "      source: docs/UPSTREAM.md\n"
            "      repeats:\n"
            "        pH: 10\n"
            "    ---",
            file=sys.stderr,
        )
        return EXIT_CANNOT_CHECK

    # Unit mismatches are counted here, not alongside `findings`, because a
    # reader who sees "0 violations" above a printed unit error will trust the
    # count over the text. They are named separately so the two kinds stay
    # distinguishable: a wrong number and a wrong unit are different repairs.
    unit_note = f", {len(units)} unit mismatch(es)" if units else ""
    print(
        f"\nfiducial docs: {len(findings)} violation(s){unit_note} across "
        f"{len(declared)} declared document(s) ({len(files)} scanned)."
    )
    if gaps:
        print(
            f"  ({len(gaps)} declared quantity(ies) compared nothing. They are "
            "not violations, but neither are they checks.)"
        )
        if args.strict_gaps or cfg.strict_gaps:
            return EXIT_VIOLATIONS
    if errors:
        # A document whose declaration does not parse is UNCHECKED, and its
        # author believes it is gated. Never fold this into a clean result.
        print(
            f"fiducial: {len(errors)} document(s) declare an SSOT that could "
            "not be used and were NOT checked.",
            file=sys.stderr,
        )
        return EXIT_VIOLATIONS
    return EXIT_VIOLATIONS if (findings or units) else EXIT_OK


def _run_check(args: argparse.Namespace) -> int:
    """Run every configured rule, then combine the verdicts pessimistically."""
    cfg = _load_config(args)

    if args.rules:
        wanted = tuple(r.strip() for r in args.rules.split(",") if r.strip())
        bad = [
            r
            for r in wanted
            if r not in _runner.DEFAULT_RULES + ("literals", "coverage", "pointers")
        ]
        if bad:
            print(f"fiducial: unknown rule(s) {bad}", file=sys.stderr)
            return EXIT_CANNOT_CHECK
    else:
        wanted = _runner.rules_to_run(cfg)

    if not wanted:
        print(
            "fiducial check: no rules to run. A check that runs nothing "
            "produces the same silence as a clean repo, which is the failure "
            "this package was built after. Declare rules = [...] under "
            "[tool.fiducial], or run a subcommand directly.",
            file=sys.stderr,
        )
        return EXIT_CANNOT_CHECK

    runners = {
        "literals": (_run_literals, _literals_args),
        "names": (_run_names, _names_args),
        "coverage": (_run_coverage, _coverage_args),
        "docs": (_run_docs, _docs_args),
        "pointers": (_run_pointers, _pointers_args),
    }

    outcomes: list[_runner.RuleOutcome] = []
    for rule in wanted:
        fn, mk = runners[rule]
        print(f"\n--- fiducial {rule} ---")
        code = fn(mk(cfg), cfg)
        outcomes.append(_runner.RuleOutcome(rule, code))

    print(_runner.summarise(outcomes, cfg))
    return _runner.aggregate(outcomes)


def _run_pointers(args: argparse.Namespace, cfg: _config.Config | None = None) -> int:
    cfg = cfg if cfg is not None else _load_config(args)
    paths = list(args.paths) or list(cfg.pointers_paths)
    files = [f for f in _expand(paths) if f.suffix == ".json"]
    if not files:
        print(
            f"fiducial: matched 0 index files from {paths!r}. "
            "Check the paths -- an empty scan is not a clean scan.",
            file=sys.stderr,
        )
        return EXIT_CANNOT_CHECK

    root = args.root or cfg.pointers_root
    file_keys = _config.resolve_set(
        _pointers.FILE_KEYS, cfg.file_keys, cfg.extend_file_keys
    )
    id_keys = _config.resolve_set(
        _pointers.ID_KEYS, cfg.id_keys, cfg.extend_id_keys
    )

    reports = _pointers.scan(
        files, Path(root) if root else None, file_keys, id_keys
    )
    if getattr(args, "format", "text") == "json":
        # The prose and the JSON describe the same run; only the audience
        # differs. Emitting both would leave a consumer parsing around the
        # part it does not want, so the format picks one.
        env = _signals.Envelope(_signals.from_pointers(reports))
        print(env.to_json())
        s = env.summary()
        if s["violations"] == 0 and s["cannot_check"]:
            return EXIT_CANNOT_CHECK
        return EXIT_VIOLATIONS if s["violations"] else EXIT_OK

    total = broken = blind = 0
    for r in reports:
        total += r.checked
        broken += len(r.broken)
        blind += 1 if r.blind else 0
        for b in r.broken:
            print(b.explain())
        print(r.summary())

    print(
        f"\nfiducial pointers: {broken} broken pointer(s) among {total} "
        f"checked, across {len(files)} index file(s)"
    )

    # An index whose pointers could not be resolved at all is UNCHECKED, not
    # clean -- the same distinction rule (2) had to learn. Reported as exit 2
    # so a caller can tell "everything resolves" from "nothing was looked at".
    if blind == len(reports):
        print(
            f"fiducial: every index read carried no resolvable pointer "
            f"({blind} file(s)). Nothing was verified.",
            file=sys.stderr,
        )
        return EXIT_CANNOT_CHECK
    return EXIT_VIOLATIONS if broken else EXIT_OK


def _literals_args(cfg: _config.Config) -> argparse.Namespace:
    return argparse.Namespace(
        keys="", paths=[], include_neutral=False, call_keywords=False,
        config=None, format="text",
    )


def _names_args(cfg: _config.Config) -> argparse.Namespace:
    return argparse.Namespace(
        paths=[], mode=None, config=None, allow_zero_comparable=False,
        format="text",
    )


def _coverage_args(cfg: _config.Config) -> argparse.Namespace:
    return argparse.Namespace(
        spec=None, field=None, level=None, baseline=None, write_baseline=False,
        waiver_field=None, data=None, tests=[], config=None, format="text",
    )


def _pointers_args(cfg: _config.Config) -> argparse.Namespace:
    return argparse.Namespace(paths=[], root=None, config=None, format="text")


def _docs_args(cfg: _config.Config) -> argparse.Namespace:
    return argparse.Namespace(
        paths=[], root=None, tol=0.0, strict_gaps=False, config=None,
        format="text",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fiducial",
        description="Static checks for parameters that claim to be measured.",
    )
    p.add_argument(
        "--config",
        help="path to a config file, overriding discovery of "
        "pyproject.toml / .fiducial.toml",
    )
    sub = p.add_subparsers(dest="command", required=True)

    chk = sub.add_parser(
        "check",
        help="run the rules this project declared in [tool.fiducial]",
        description="Run the configured rules in one pass. Exit 2 wins over "
        "exit 1: a rule that could not run outranks a rule that found things, "
        "because a partial scan reported as a result is the failure this "
        "package exists to refuse.",
    )
    chk.add_argument(
        "--rules",
        help="comma-separated subset to run, overriding the config",
    )
    chk.set_defaults(func=_run_check)

    lit = sub.add_parser(
        "literals", help="rule 1 -- measured keys hard-coded or silently defaulted"
    )
    lit.add_argument(
        "--keys",
        default="",
        help="comma-separated keys that stand for measured quantities. "
        "Optional once `keys = [...]` is set under [tool.fiducial]; an "
        "explicit --keys still wins.",
    )
    lit.add_argument(
        "--include-neutral",
        action="store_true",
        help="also report defaults of 0.0/1.0 (a term switched off or a neutral "
        "scale). Excluded by default: they were 82%% of hits (575/705) on the "
        "reference codebase and bury the rest.",
    )
    lit.add_argument(
        "--call-keywords",
        action="store_true",
        help="also report measured keys passed as keyword arguments to any "
        "call, e.g. Stream(price=0.73). Off by default: a keyword names the "
        "callee's parameter, and on the reference codebase pymoo's "
        "SBX(eta=15) outnumbered the real hits. dict(...) is always read.",
    )
    lit.add_argument(
        "paths", nargs="*", help="files, directories, or globs "
        "(default: literals_paths from the config)",
    )
    lit.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="text for a person; json for a program -- a confidence per "
        "finding and, where a repair exists, whether the caller may apply "
        "it unattended.",
    )
    lit.set_defaults(func=_run_literals)

    nm = sub.add_parser("names", help="rule 2 -- file names that contradict contents")
    nm.add_argument(
        "--mode",
        choices=["strict", "set"],
        default=None,
        help="strict = name and contents share no version (lower noise); "
        "set = the two disagree at all (catches partial-overlap lies). "
        "Measured base rates on the reference corpus: 1.6%% and 2.4%%.",
    )
    nm.add_argument(
        "--allow-zero-comparable",
        action="store_true",
        help="treat 'files read, none comparable' as a pass instead of exit 2. "
        "For a project whose configs legitimately carry no version tokens in "
        "their names -- say it once, deliberately, rather than letting the "
        "rule be silent by accident.",
    )
    nm.add_argument(
        "paths", nargs="*", help="files, directories, or globs "
        "(default: names_paths from the config)",
    )
    nm.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="text for a person; json for a program -- a confidence per "
        "finding and, where a repair exists, whether the caller may apply "
        "it unattended.",
    )
    nm.set_defaults(func=_run_names)

    ptr = sub.add_parser(
        "pointers",
        help="rule 5 -- index entries pointing at files that are not there",
    )
    ptr.add_argument(
        "--root",
        default=None,
        help="directory the file pointers resolve against "
        "(default: each index file's own directory, which is what a loader "
        "reading that index does)",
    )
    ptr.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="text for a person; json for a program. The JSON carries a "
        "confidence and, where a repair exists, whether the caller may apply "
        "it unattended -- which three exit codes cannot express.",
    )
    ptr.add_argument(
        "paths", nargs="*", help="index files or globs "
        "(default: pointers_paths from the config)",
    )
    ptr.set_defaults(func=_run_pointers)

    cov = sub.add_parser(
        "coverage", help="rule 3 -- declared parameters with no gate asserting anything"
    )
    cov.add_argument(
        "--spec",
        default=None,
        help="YAML file declaring the keys. Optional once `spec = \"...\"` is "
        "set under [tool.fiducial].",
    )
    cov.add_argument(
        "--field",
        default="learnable_keys",
        help="top-level list field in --spec (default: learnable_keys)",
    )
    cov.add_argument(
        "--level",
        choices=["absent", "mentioned"],
        default=None,
        help="absent = keys nowhere in the test tree (default, the hard gap); "
        "mentioned = also keys present in tests but inside no assert. "
        "Measured on the reference project: 11 absent, 28 mentioned-only, "
        "10 asserted out of 49.",
    )
    cov.add_argument(
        "--baseline",
        help="file listing keys whose gap predates this gate; they are reported "
        "but do not fail. Shrink it, never grow it.",
    )
    cov.add_argument(
        "--write-baseline",
        action="store_true",
        help="write the current gaps to --baseline and exit 0. Run once, on "
        "adoption.",
    )
    cov.add_argument(
        "--waiver-field",
        default="coverage_waivers",
        help="mapping in --spec of key -> reason for keys that deliberately "
        "have no gate (default: coverage_waivers). A waiver needs a reason; "
        "a bare key is refused.",
    )
    cov.add_argument(
        "--data",
        nargs="*",
        help="JSON baselines/fixtures the tests compare against (e.g. a golden "
        "file). A key pinned there IS gated, but its name never appears in the "
        "source because the comparison iterates the file at runtime.",
    )
    cov.add_argument(
        "tests", nargs="*", help="test files, directories, or globs "
        "(default: tests_paths from the config)",
    )
    cov.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="text for a person; json for a program -- a confidence per "
        "finding and, where a repair exists, whether the caller may apply "
        "it unattended.",
    )
    cov.set_defaults(func=_run_coverage)

    dc = sub.add_parser(
        "docs",
        help="rule 4 -- a document asserting a value its declared SSOT contradicts",
    )
    dc.add_argument(
        "--root",
        help="directory that `ssot.source:` paths are relative to "
        "(default: the declaring document's own directory)",
    )
    dc.add_argument(
        "--tol",
        type=float,
        default=0.0,
        help="relative tolerance below which two readings of one quantity count "
        "as agreeing (default: 0.0 -- exact). Raise it only for quantities the "
        "documents deliberately round.",
    )
    dc.add_argument(
        "--strict-gaps",
        action="store_true",
        help="also exit 1 when a declared quantity compared nothing (the label "
        "is missing from one side). Gaps are always reported; this decides "
        "whether they block. Worth turning on once a project's declarations "
        "have settled -- a declaration that checks nothing is a check nobody "
        "knows they lack.",
    )
    dc.add_argument(
        "paths", nargs="*", help="markdown files, directories, or globs "
        "(default: docs_paths from the config)",
    )
    dc.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="text for a person; json for a program -- a confidence per "
        "finding and, where a repair exists, whether the caller may apply "
        "it unattended.",
    )
    dc.set_defaults(func=_run_docs)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

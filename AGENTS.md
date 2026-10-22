# AGENTS.md — fiducial

Rules for AI coding agents working in this repository (Claude Code, Codex, Gemini CLI, Hermes and others).
`fiducial` five static checks (literals, names, coverage, docs, pointers) for measured quantities. It ships publicly on GitHub and on PyPI as `fiducial-check`.

## Public repository
- Never commit personal names, machine names, absolute home paths, lab data, project-specific constants or
  credentials. Examples and test fixtures must be toy data.
- A pre-push leak scan runs on this clone; a finding blocks the push. Fix or redact it, never bypass the hook.

## Behaviour contract
- Exit codes are shared with the family (fiducial, provenance-check, regress-check): `0` clean, `1` violations,
  `2` cannot check. A check that compared nothing must exit `2`, never `0`. Do not weaken this to make a test pass.
- The PyPI update notice prints only on a TTY and never changes the exit code.

## Working here
- Tests: `python -m pytest` from the repo root. New behaviour comes with a test.
- New feature or rule: add its row to `docs/feature-connectivity-ledger.md` (what calls it, what proves it).
- Default branch `main`; work on a branch and merge into `main`, never commit to `main` directly.
- Release procedure: `docs/RELEASING.md`. The family overview is `docs/FOUR_AXES.md`.

# Releasing `fiducial-check` to PyPI

## Naming

- Import name: `fiducial` (`import fiducial`). Do not change it; the tests and the README's
  code examples assume it.
- Distribution/install name: `fiducial-check` (`pip install fiducial-check`). The plain name
  `fiducial` on PyPI belongs to an unrelated project, so it cannot be uploaded to. Re-check
  `https://pypi.org/pypi/fiducial/json` before assuming that has changed.
- `pyproject.toml` sets `[project].name = "fiducial-check"`; `[tool.setuptools]` packaging
  still points at the `fiducial/` directory.

## Procedure

1. Run the test suite and `fiducial check` on a clean checkout of `main`; both must pass.
2. Bump the version in `pyproject.toml`.
3. Build: `python -m build`.
4. Validate the artifacts: `twine check dist/*`.
5. Upload: `twine upload dist/*`, using a PyPI token scoped to the `fiducial-check` project
   (PyPI only offers project-scoped tokens after the first upload; the first release of a new
   name needs an account-scope token). Keep the token outside the repository.
6. Verify in a clean virtual environment: `pip install fiducial-check==<version>`, then
   `fiducial check`.
7. Tag the release commit.

"""`python -m fiducial`.

The console script from `[project.scripts]` needs the package installed. This
entry point does not, which matters for a pre-commit hook or a CI step running
against a checkout, and for anyone trying the tool before installing it.
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

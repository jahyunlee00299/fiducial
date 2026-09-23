"""fiducial — static checks for parameters that claim to be measured.

rule (1) `literals`: a declared measured key hard-coded, or silently defaulted.
rule (2) `names`:    a file name whose version contradicts the file's own fields.

Both rules refuse to run on nothing: an empty key list or an empty file match is
an error, not a pass. A check that cannot fail is worse than no check, because
it gets believed.
"""

from .literals import Finding, scan_file as scan_literals, scan_source
from .names import Verdict, inspect_file, inspect_text, scan as scan_names

__version__ = "0.1.0"
__all__ = [
    "Finding", "scan_literals", "scan_source",
    "Verdict", "inspect_file", "inspect_text", "scan_names",
    "__version__",
]

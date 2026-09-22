"""Second runnable step: build the HTML dashboard from the saved submissions.

Run it from the repository root as
python3 qor_parser_demo/02_build_dashboard.py <workspace>/submissions

It is a thin wrapper around the copied apr_dashboard.build_dashboard, so it
adds no display logic of its own. The first step prints the exact command.
"""

import os
import sys

# Running this file puts its own directory first on sys.path. Inserting it
# again makes that explicit, and the check below confirms the package we
# imported is the copy beside this script rather than the original
# apr_dashboard at the repository root.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import apr_dashboard
from apr_dashboard.build_dashboard import main

_EXPECTED_PACKAGE = os.path.join(HERE, "apr_dashboard")
_FOUND_PACKAGE = os.path.dirname(os.path.abspath(apr_dashboard.__file__))
if os.path.normcase(os.path.realpath(_FOUND_PACKAGE)) != os.path.normcase(
        os.path.realpath(_EXPECTED_PACKAGE)):
    raise SystemExit(
        "this demo must use its own package copy at %s, but it imported %s"
        % (_EXPECTED_PACKAGE, _FOUND_PACKAGE))

if __name__ == "__main__":
    sys.exit(main())

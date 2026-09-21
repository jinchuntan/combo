"""Second runnable step: build the HTML dashboard from saved submissions.

Run it as python3 apr_dashboard/02_build_dashboard.py <workspace>/submissions
from the folder that holds apr_dashboard/. It is a thin wrapper around
apr_dashboard.build_dashboard, so python -m apr_dashboard.build_dashboard
does exactly the same thing.
"""

import os
import sys

# Running a file inside the package puts the package directory on sys.path
# instead of its parent, so the parent is added back before importing.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apr_dashboard.build_dashboard import main

if __name__ == "__main__":
    sys.exit(main())

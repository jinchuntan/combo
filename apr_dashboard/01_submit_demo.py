"""First runnable step: submit the demonstration records.

Run it as python3 apr_dashboard/01_submit_demo.py from the folder that holds
apr_dashboard/. It is a thin wrapper around apr_dashboard.example_submit, so
python -m apr_dashboard.example_submit does exactly the same thing.
"""

import os
import sys

# Running a file inside the package puts the package directory on sys.path
# instead of its parent, so the parent is added back before importing.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apr_dashboard.example_submit import main

if __name__ == "__main__":
    sys.exit(main())

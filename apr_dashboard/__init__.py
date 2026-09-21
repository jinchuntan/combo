"""Build APR dashboard submissions from run directories and timing values.

The package holds the timing schema validators, the run metadata helpers and
the submission session. Call initialize to start one.
"""

from .submission import initialize

__all__ = ["initialize"]

"""Public surface for directory_size_counter_utils.

Only names re-exported here are considered stable API.  Keeping the
package ``__init__`` thin means callers can import the two names they
need without dragging in anything else.
"""

from .core import DirectorySummary, summarize_directory

__all__ = ["DirectorySummary", "summarize_directory"]

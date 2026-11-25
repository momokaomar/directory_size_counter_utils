"""Walk a directory tree and aggregate byte and file counts per subdirectory.

The problem this solves: ``du`` gives you one number for a tree and
``os.walk`` gives you a flat stream of paths.  Neither gives you a
*nested* summary where each directory reports the totals of everything
beneath it, which is what you want when you are building a report or
rendering a tree view.

Design decision: the summary is a plain dataclass tree rather than a
dict-of-dicts.  A dataclass keeps ``.total_bytes`` and ``.file_count``
attribute access, is easy to compare in tests, and does not silently
collapse two directories that happen to share a name (a dict keyed by
name would).  The trade-off is that serialising to JSON requires a
recursive encoder, which is a small price for unambiguous structure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence


@dataclass
class DirectorySummary:
    """Aggregated size information for one directory and its descendants.

    ``total_bytes`` and ``file_count`` are recursive: they include every
    regular file at or below this directory.  Symlinks are never followed
    and never counted, because following them can loop forever and because
    a symlink's size is a property of the link, not the target.
    """

    path: str
    total_bytes: int = 0
    file_count: int = 0
    children: List["DirectorySummary"] = field(default_factory=list)

    def as_dict(self) -> dict:
        """Return a JSON-friendly nested dict.

        Provided so callers do not have to reimplement the recursion just
        to feed ``json.dumps``.
        """

        return {
            "path": self.path,
            "total_bytes": self.total_bytes,
            "file_count": self.file_count,
            "children": [child.as_dict() for child in self.children],
        }

    def flatten(self) -> List["DirectorySummary"]:
        """Return this node followed by all descendants, depth-first.

        Useful for printing one line per directory without writing a
        recursive walk at every call site.
        """

        result: List[DirectorySummary] = [self]
        for child in self.children:
            result.extend(child.flatten())
        return result


def summarize_directory(
    root: str,
    *,
    follow_symlinks: bool = False,
    on_error: Optional[callable] = None,
) -> DirectorySummary:
    """Walk ``root`` and return a :class:`DirectorySummary` for it.

    ``root`` may be a file, in which case the returned summary has the
    file's size and a count of one, with no children.  This keeps the
    function total: callers do not need a separate branch for the
    single-file case.

    ``follow_symlinks`` defaults to ``False``.  When ``True`` symlinked
    directories are descended into, which can produce cycles; the caller
    accepts that risk.  Symlinked *files* are still counted only as
    entries, never stat'd through the link, unless ``follow_symlinks`` is
    set.

    ``on_error`` is called with ``(path, exception)`` for any entry that
    cannot be stat'd or listed.  Without it, unreadable entries are
    silently skipped so a single permission error does not abort the
    whole walk.
    """

    if follow_symlinks:
        is_dir = os.path.isdir
        is_file = os.path.isfile
        get_size = os.path.getsize
    else:
        is_dir = lambda p: os.path.isdir(p) and not os.path.islink(p)
        is_file = lambda p: os.path.isfile(p) and not os.path.islink(p)
        get_size = os.path.getsize

    def report(path: str, exc: BaseException) -> None:
        if on_error is not None:
            on_error(path, exc)

    if is_dir(root):
        return _summarize_tree(root, is_dir, is_file, get_size, report)

    if is_file(root):
        try:
            size = get_size(root)
        except OSError as exc:
            report(root, exc)
            size = 0
        return DirectorySummary(path=root, total_bytes=size, file_count=1)

    # Not a directory, not a file: a broken symlink, a FIFO, a socket.
    # Report it as an empty leaf so the caller still sees the path.
    return DirectorySummary(path=root)


def _summarize_tree(
    root: str,
    is_dir,
    is_file,
    get_size,
    report,
) -> DirectorySummary:
    """Recursive worker for :func:`summarize_directory`.

    Split out so the public function's signature stays small and the
    recursion has a clear name.  ``is_dir``/``is_file``/``get_size`` are
    passed in rather than re-derived so the symlink policy chosen by the
    caller is applied uniformly at every level.
    """

    summary = DirectorySummary(path=root)
    try:
        entries: Sequence[str] = sorted(os.listdir(root))
    except OSError as exc:
        report(root, exc)
        return summary

    for name in entries:
        child_path = os.path.join(root, name)
        if is_dir(child_path):
            child = _summarize_tree(child_path, is_dir, is_file, get_size, report)
            summary.children.append(child)
            summary.total_bytes += child.total_bytes
            summary.file_count += child.file_count
        elif is_file(child_path):
            try:
                size = get_size(child_path)
            except OSError as exc:
                report(child_path, exc)
                continue
            summary.total_bytes += size
            summary.file_count += 1
        # Anything else (symlink, FIFO, socket, device) is ignored when
        # not following symlinks; with follow_symlinks the is_* helpers
        # resolve the link and the branch above already handled it.

    return summary

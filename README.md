# directory_size_counter_utils

Walk a directory tree and get back a nested summary of byte counts and file counts for every subdirectory.

```python
from directory_size_counter_utils import summarize_directory

summary = summarize_directory("src")
print(summary.total_bytes, summary.file_count)

for node in summary.flatten():
    print(node.path, node.total_bytes, node.file_count)

import json
print(json.dumps(summary.as_dict(), indent=2))
```

## Why this exists

`du` reports a single number for a tree, and `os.walk` hands you a flat stream of paths. Neither gives you a *nested* structure where each directory already carries the recursive totals of everything beneath it, which is what you need when you are rendering a tree view or attaching sizes to a report.

The trade-off: the result is a tree of `DirectorySummary` dataclasses rather than a dict keyed by directory name. That means serialising requires calling `as_dict()` first, but it also means two sibling directories that happen to share a name stay distinct instead of silently overwriting each other.

## The awkward edge

Symlinks are not followed by default. A symlinked directory contributes nothing to its parent's totals, and a symlinked file is not counted at all, because following links can produce cycles and because a link's own size is not the size of what it points at. If you want the other behaviour, pass `follow_symlinks=True` and accept that a cyclic tree will recurse until the OS stops you.

A second edge: `summarize_directory` accepts a path that is a regular file, or a path that does not exist at all. A file yields a leaf summary with its size and a count of one; a missing path yields an empty leaf. Neither raises, so callers can walk a list of candidate paths without guarding each one.

## API

- `summarize_directory(root, *, follow_symlinks=False, on_error=None) -> DirectorySummary`
  - `root`: directory or file path.
  - `follow_symlinks`: descend into symlinked directories and count symlinked files.
  - `on_error`: optional `callable(path, exception)` invoked for each entry that cannot be listed or stat'd. Without it, unreadable entries are skipped.
- `DirectorySummary`
  - `.path`, `.total_bytes`, `.file_count`, `.children`
  - `.as_dict()` — nested dict suitable for `json.dumps`.
  - `.flatten()` — this node followed by all descendants, depth-first.

import json
import os
import tempfile
import unittest

from directory_size_counter_utils import DirectorySummary, summarize_directory


class SummarizeDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, relpath: str, data: bytes) -> str:
        path = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_empty_directory(self) -> None:
        summary = summarize_directory(self.root)
        self.assertEqual(summary.path, self.root)
        self.assertEqual(summary.total_bytes, 0)
        self.assertEqual(summary.file_count, 0)
        self.assertEqual(summary.children, [])

    def test_single_file_at_root(self) -> None:
        self.write("a.txt", b"hello")
        summary = summarize_directory(self.root)
        self.assertEqual(summary.total_bytes, 5)
        self.assertEqual(summary.file_count, 1)
        self.assertEqual(summary.children, [])

    def test_nested_totals_are_recursive(self) -> None:
        self.write("a.txt", b"1234")          # 4 bytes
        self.write("sub/b.txt", b"123456")   # 6 bytes
        self.write("sub/deep/c.txt", b"12")  # 2 bytes
        summary = summarize_directory(self.root)
        self.assertEqual(summary.total_bytes, 12)
        self.assertEqual(summary.file_count, 3)
        self.assertEqual(len(summary.children), 1)
        sub = summary.children[0]
        self.assertEqual(sub.path, os.path.join(self.root, "sub"))
        self.assertEqual(sub.total_bytes, 8)
        self.assertEqual(sub.file_count, 2)
        self.assertEqual(len(sub.children), 1)
        deep = sub.children[0]
        self.assertEqual(deep.total_bytes, 2)
        self.assertEqual(deep.file_count, 1)

    def test_children_are_sorted_by_name(self) -> None:
        self.write("zeta/x", b"1")
        self.write("alpha/x", b"1")
        self.write("mid/x", b"1")
        summary = summarize_directory(self.root)
        names = [os.path.basename(child.path) for child in summary.children]
        self.assertEqual(names, ["alpha", "mid", "zeta"])

    def test_root_may_be_a_file(self) -> None:
        path = self.write("only.bin", b"abcdef")
        summary = summarize_directory(path)
        self.assertEqual(summary.path, path)
        self.assertEqual(summary.total_bytes, 6)
        self.assertEqual(summary.file_count, 1)
        self.assertEqual(summary.children, [])

    def test_missing_path_is_empty_leaf(self) -> None:
        missing = os.path.join(self.root, "nope")
        summary = summarize_directory(missing)
        self.assertEqual(summary.path, missing)
        self.assertEqual(summary.total_bytes, 0)
        self.assertEqual(summary.file_count, 0)
        self.assertEqual(summary.children, [])

    def test_symlinks_are_not_followed_by_default(self) -> None:
        target_dir = os.path.join(self.root, "real")
        os.makedirs(target_dir)
        with open(os.path.join(target_dir, "data.bin"), "wb") as handle:
            handle.write(b"0123456789")
        link = os.path.join(self.root, "link")
        os.symlink(target_dir, link)
        summary = summarize_directory(self.root)
        # The real directory contributes 10 bytes; the link contributes nothing.
        self.assertEqual(summary.total_bytes, 10)
        self.assertEqual(summary.file_count, 1)
        child_names = sorted(os.path.basename(c.path) for c in summary.children)
        self.assertEqual(child_names, ["real"])

    def test_follow_symlinks_counts_target(self) -> None:
        target_dir = os.path.join(self.root, "real")
        os.makedirs(target_dir)
        with open(os.path.join(target_dir, "data.bin"), "wb") as handle:
            handle.write(b"0123456789")
        link = os.path.join(self.root, "link")
        os.symlink(target_dir, link)
        summary = summarize_directory(self.root, follow_symlinks=True)
        # Both the real directory and the link to it are descended into.
        self.assertEqual(summary.total_bytes, 20)
        self.assertEqual(summary.file_count, 2)
        child_names = sorted(os.path.basename(c.path) for c in summary.children)
        self.assertEqual(child_names, ["link", "real"])

    def test_as_dict_round_trips_through_json(self) -> None:
        self.write("sub/a", b"x")
        summary = summarize_directory(self.root)
        encoded = json.dumps(summary.as_dict())
        decoded = json.loads(encoded)
        self.assertEqual(decoded["path"], self.root)
        self.assertEqual(decoded["file_count"], 1)
        self.assertEqual(decoded["children"][0]["total_bytes"], 1)

    def test_flatten_is_depth_first(self) -> None:
        self.write("a.txt", b"1")
        self.write("sub/b.txt", b"1")
        self.write("sub/deep/c.txt", b"1")
        summary = summarize_directory(self.root)
        paths = [node.path for node in summary.flatten()]
        self.assertEqual(paths[0], self.root)
        self.assertIn(os.path.join(self.root, "sub"), paths)
        self.assertIn(os.path.join(self.root, "sub", "deep"), paths)
        # Root first, then its descendants; the exact order among siblings
        # follows the sorted children list.
        self.assertEqual(paths[1], os.path.join(self.root, "sub"))

    def test_on_error_receives_unreadable_directory(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("running as root; permission bits are not enforced")
        blocked = os.path.join(self.root, "blocked")
        os.makedirs(blocked)
        with open(os.path.join(blocked, "secret"), "wb") as handle:
            handle.write(b"hidden")
        os.chmod(blocked, 0o000)
        errors = []
        try:
            summary = summarize_directory(self.root, on_error=lambda p, e: errors.append((p, e)))
        finally:
            os.chmod(blocked, 0o755)
        self.assertEqual(summary.total_bytes, 0)
        self.assertEqual(summary.file_count, 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][0], blocked)
        self.assertIsInstance(errors[0][1], OSError)

    def test_children_are_distinct_nodes(self) -> None:
        self.write("one/a", b"1")
        self.write("two/a", b"1")
        summary = summarize_directory(self.root)
        self.assertEqual(len(summary.children), 2)
        self.assertIsNot(summary.children[0], summary.children[1])


if __name__ == "__main__":
    unittest.main()

import concurrent.futures
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wiki_index.py"
sys.path.insert(0, str(SCRIPT.parent))
import wiki_index


HEADER = "| Article | Summary | Updated |\n|---------|---------|---------|\n"
BASE = "# Knowledge Base Index\n\nRead the known index directly.\n\n## topic\n\nAuthored introduction.\n\n" + HEADER


def row(key, summary="Original"):
    return f"| [{key}](topic/{key}.md) | {summary} | 2026-10-23 |\n"


def plan_row(key, status="Approved", approved="2026-10-22", updated="2026-10-23"):
    return f"| [{key}]({key}.md) | {status} | Topics | {approved} | {updated} | none |\n"


PLANNING = (
    "# Planning Index\n\n## Active\n\nApproved, newest first.\n\n"
    "| Plan | Status | Topics | Approved | Updated | Audit |\n"
    "|------|--------|--------|----------|---------|-------|\n"
    "{active}\n## Closed\n\nClosed, newest first.\n\n"
    "| Plan | Status | Topics | Approved | Closed | Audit |\n"
    "|------|--------|--------|----------|--------|-------|\n{closed}"
)


class WikiIndexTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "wiki").mkdir()
        self.index = self.root / "wiki" / "index.md"
        self.index.write_text(BASE, encoding="utf-8", newline="\n")

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), str(self.root), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8")

    def test_different_row_additions_combine_in_either_direction(self):
        a, b = BASE + row("a"), BASE + row("b")
        merged = wiki_index.merge_indexes(BASE, a, b)
        self.assertEqual(merged, BASE + row("a") + row("b"))
        self.assertEqual(merged, wiki_index.merge_indexes(BASE, b, a))
        self.assertNotIn("wiki-index-rows", merged)

    def test_distinct_adjacent_updates_and_identical_changes_preserve_prose(self):
        base = BASE + row("a") + row("b")
        a = base.replace(row("a"), row("a", "Café — ✓ `a|b`"))
        b = base.replace(row("b"), row("b", "New B"))
        expected = BASE + row("a", "Café — ✓ `a|b`") + row("b", "New B")
        self.assertEqual(wiki_index.merge_indexes(base, a, b), expected)
        self.assertEqual(wiki_index.merge_indexes(base, expected, expected), expected)

    def test_same_row_conflicts_instead_of_using_date_or_field_winners(self):
        base = BASE + row("a")
        with self.assertRaisesRegex(ValueError, "topic/a.md"):
            wiki_index.merge_indexes(base, BASE + row("a", "Summary A"),
                                     (BASE + row("a", "Summary B")).replace("2026-10-23", "2026-10-24"))
        with self.assertRaisesRegex(ValueError, "topic/a.md"):
            wiki_index.merge_indexes(BASE, BASE + row("a", "New A"), BASE + row("a", "New B"))

    def test_deletion_propagates_but_deletion_against_update_conflicts(self):
        base = BASE + row("a") + row("b")
        self.assertEqual(wiki_index.merge_indexes(base, BASE + row("b"), base + row("c")),
                         BASE + row("b") + row("c"))
        with self.assertRaisesRegex(ValueError, "topic/a.md"):
            wiki_index.merge_indexes(base, BASE + row("b"), base.replace("Original", "Changed", 1))

    def test_independent_topics_and_topic_prose_edits_combine(self):
        alpha = "\n## alpha\n\nNew alpha description.\n\n" + HEADER + row("a")
        beta = "\n## beta\n\nNew beta description.\n\n" + HEADER + row("b")
        self.assertEqual(wiki_index.merge_indexes(BASE, BASE + beta, BASE + alpha), BASE + alpha + beta)
        left = (BASE + row("a")).replace("Authored introduction.", "Revised introduction.")
        right = BASE + row("b")
        result = wiki_index.merge_indexes(BASE, left, right)
        self.assertIn("Revised introduction.", result)
        self.assertIn(row("a") + row("b"), result)
        with self.assertRaisesRegex(ValueError, "prose"):
            wiki_index.merge_indexes(BASE, left, right.replace("Authored introduction.", "Other introduction."))

    def test_plan_move_is_one_entity_and_independent_plan_changes_survive(self):
        base = PLANNING.format(active=plan_row("a") + plan_row("b"), closed="")
        ours = PLANNING.format(active=plan_row("b"), closed=plan_row("a", "Implemented"))
        theirs = base.replace(plan_row("b"), plan_row("b").replace("Topics", "Revised B"))
        result = wiki_index.merge_indexes(base, ours, theirs)
        self.assertEqual(result.count("[a](a.md)"), 1)
        self.assertIn("Revised B", result)
        self.assertEqual(wiki_index.parse_index(result)[1]["a.md"][0], "Closed")
        with self.assertRaisesRegex(ValueError, "a.md"):
            wiki_index.merge_indexes(base, ours, base.replace("Topics", "Revised A", 1))

    def test_plan_sort_uses_approval_for_active_and_closing_for_closed(self):
        base = PLANNING.format(active="", closed="")
        a = PLANNING.format(active=plan_row("old", approved="2026-10-01", updated="2026-10-30"),
                            closed=plan_row("late-close", "Implemented", "2026-10-01", "2026-10-25"))
        b = PLANNING.format(active=plan_row("new", approved="2026-10-22"),
                            closed=plan_row("early-close", "Implemented", "2026-10-22", "2026-10-23"))
        result = wiki_index.merge_indexes(base, a, b)
        self.assertLess(result.index("[new]"), result.index("[old]"))
        self.assertLess(result.index("[late-close]"), result.index("[early-close]"))

    def test_repeated_distributed_merges_and_reordering_do_not_duplicate_rows(self):
        a, b = BASE + row("a"), BASE + row("b")
        combined = wiki_index.merge_indexes(BASE, a, b)
        b_next = BASE + row("c") + row("b", "Changed by B")
        result = wiki_index.merge_indexes(b, combined, b_next)
        self.assertEqual(result, BASE + row("b", "Changed by B") + row("a") + row("c"))
        self.assertEqual(wiki_index.merge_indexes(result, result, result), result)

    def test_duplicate_targets_normalized_links_and_malformed_rows_fail(self):
        for invalid in (BASE + row("a") * 2,
                        BASE + row("a") + row("a").replace("topic/a.md", "./topic/a.md"),
                        BASE + "| Missing a link | Summary | 2026-10-23 |\n",
                        BASE + row("a").replace("topic/a.md", "../escape.md"),
                        BASE + row("a").replace("topic/a.md", "https://example.com/a.md"),
                        BASE + row("a").replace(" | Original | 2026-10-23", ""),
                        BASE + "<<<<<<< HEAD\n"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    wiki_index.merge_indexes(BASE, invalid, BASE + row("b"))

    def test_code_examples_and_unsupported_tables_are_preserved_as_prose(self):
        example = "\n```markdown\n## Example\n" + HEADER + row("example") + "```\n"
        base = BASE + example + "\n| # | Question |\n|---|----------|\n| 1 | Open? |\n"
        result = wiki_index.merge_indexes(base, base.replace(HEADER, HEADER + row("a"), 1),
                                         base.replace(HEADER, HEADER + row("b"), 1))
        self.assertIn(example, result)
        self.assertEqual(set(wiki_index.parse_index(result)[1]), {"topic/a.md", "topic/b.md"})

    def test_existing_non_markdown_assets_and_fragment_links_keep_their_targets(self):
        asset = row("map").replace("topic/map.md", "schemas/map.drawio")
        anchored = row("guide").replace("topic/guide.md", "./topic/guide.md#section")
        merged = wiki_index.merge_indexes(BASE, BASE + asset, BASE + anchored)
        self.assertIn(asset, merged)
        self.assertIn(anchored, merged)
        self.assertEqual(set(wiki_index.parse_index(merged)[1]), {"schemas/map.drawio", "topic/guide.md"})

    def test_topic_deletion_against_new_rows_or_prose_does_not_drop_changes(self):
        intro = "# Knowledge Base Index\n\nRead the known index directly.\n\n"
        for theirs in (BASE + row("a"), BASE.replace("Authored introduction.", "New introduction.")):
            with self.subTest(theirs=theirs):
                with self.assertRaises(ValueError):
                    wiki_index.merge_indexes(BASE, intro, theirs)

    def test_initially_empty_index_accepts_independent_new_topics(self):
        base = "# Knowledge Base Index\n"
        ours = BASE + row("a")
        theirs = (BASE + row("b")).replace("## topic", "## other")
        result = wiki_index.merge_indexes(base, ours, theirs)
        self.assertEqual(set(wiki_index.parse_index(result)[1]), {"topic/a.md", "topic/b.md"})

    def test_snapshot_is_read_only_and_stale_parallel_writers_preserve_all_rows(self):
        before = self.index.read_bytes()
        snapshot = self.root / "before.md"
        result = self.cli("--snapshot", snapshot)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(snapshot.read_bytes(), before)
        self.assertEqual(self.index.read_bytes(), before)
        updates = []
        for number in range(10):
            update = self.root / f"update-{number}.md"
            update.write_text(BASE + row(f"agent-{number}"), encoding="utf-8")
            updates.append(update)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda update: self.cli("--base-file", snapshot, "--updated-file", update), updates))
        self.assertTrue(all(result.returncode == 0 for result in results), results)
        self.assertEqual(len(wiki_index.parse_index(self.index.read_text(encoding="utf-8"))[1]), 10)
        self.assertEqual(list(self.index.parent.iterdir()), [self.index])
        self.assertNotEqual(self.cli("--snapshot", snapshot).returncode, 0)

    def test_rejected_stale_write_and_failed_replace_preserve_latest_bytes(self):
        self.index.write_bytes((BASE + row("a", "Latest")).replace("\n", "\r\n").encode("utf-8-sig"))
        before = self.index.read_bytes()
        with self.assertRaises(ValueError):
            wiki_index.update_index(self.index, BASE + row("a"), BASE + row("a", "Stale"))
        self.assertEqual(self.index.read_bytes(), before)
        with patch.object(wiki_index.os, "replace", side_effect=PermissionError("busy")):
            with self.assertRaises(PermissionError):
                wiki_index.update_index(self.index, BASE, BASE + row("b"))
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(list(self.index.parent.iterdir()), [self.index])
        wiki_index.update_index(self.index, BASE, BASE + row("b"))
        content = self.index.read_bytes()
        self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(content.count(b"\r\n"), content.count(b"\n"))

    def test_planning_cli_and_live_file_alias_guards(self):
        (self.index.parent / "planning").mkdir()
        planning = self.index.parent / "planning" / "index.md"
        planning.write_text(PLANNING.format(active="", closed=""), encoding="utf-8")
        snapshot, updated = self.root / "before.md", self.root / "after.md"
        result = self.cli("--planning", "--snapshot", snapshot)
        self.assertEqual(result.returncode, 0, result.stderr)
        updated.write_text(PLANNING.format(active=plan_row("a"), closed=""), encoding="utf-8")
        result = self.cli("--planning", "--base-file", snapshot, "--updated-file", updated)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[a](a.md)", planning.read_text(encoding="utf-8"))
        self.assertEqual(self.index.read_text(encoding="utf-8"), BASE)
        for args in (("--snapshot", self.index), ("--base-file", self.index, "--updated-file", updated)):
            self.assertNotEqual(self.cli(*args).returncode, 0)

    def test_transient_reader_denial_recovers_without_losing_the_update(self):
        replace = wiki_index.os.replace
        attempts = []

        def briefly_busy(source, target):
            attempts.append(target)
            if len(attempts) == 1:
                raise PermissionError("reader temporarily holds the file")
            replace(source, target)

        with patch.object(wiki_index.os, "replace", side_effect=briefly_busy):
            wiki_index.update_index(self.index, BASE, BASE + row("a"))
        self.assertEqual(self.index.read_text(encoding="utf-8"), BASE + row("a"))

    def git(self, *args, input=None):
        result = subprocess.run(["git", "-C", str(self.root), *args],
                                input=input.encode("utf-8") if input is not None else None, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.decode("utf-8").strip()

    def test_git_driver_combines_independent_rows_and_reports_real_conflicts_without_commits(self):
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        attributes = "wiki/index.md merge=wiki-index\nwiki/planning/index.md merge=wiki-index\n"
        (self.root / ".gitattributes").write_text(attributes, encoding="utf-8")
        result = self.cli("--install-merge-driver")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("merge: wiki-index", self.git("check-attr", "merge", "--", "wiki/index.md"))
        attributes_blob = self.git("hash-object", "-w", "--stdin", input=attributes)

        def tree(content):
            blob = self.git("hash-object", "-w", "--stdin", input=content)
            wiki = self.git("mktree", input=f"100644 blob {blob}\tindex.md\n")
            return self.git("mktree", input=f"100644 blob {attributes_blob}\t.gitattributes\n040000 tree {wiki}\twiki\n")

        a, b = BASE + row("a"), BASE + row("b")
        trees = [tree(text) for text in (BASE, a, b)]
        result = self.git("merge-tree", "--trivial-merge", *trees)
        self.assertNotIn("<<<<<<<", result)
        self.assertIn("topic/a.md", result)
        self.assertIn("topic/b.md", result)
        combined = wiki_index.merge_indexes(BASE, a, b)
        result = self.git("merge-tree", "--trivial-merge", tree(b), tree(combined), tree(b + row("c")))
        self.assertIn("topic/c.md", result)
        for name, content in (("base", a), ("ours", BASE + row("a", "A")), ("theirs", BASE + row("a", "B"))):
            (self.root / name).write_text(content, encoding="utf-8")
        before = (self.root / "ours").read_bytes()
        result = self.cli("--merge", self.root / "base", self.root / "ours", self.root / "theirs")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("topic/a.md", result.stderr)
        self.assertEqual((self.root / "ours").read_bytes(), before)
        self.git("config", "--unset", "merge.wiki-index.driver")
        self.assertIn("<<<<<<<", self.git("merge-tree", "--trivial-merge", *trees))


if __name__ == "__main__":
    unittest.main()

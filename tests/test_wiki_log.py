import concurrent.futures
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wiki_log.py"
SPEC = importlib.util.spec_from_file_location("wiki_log", SCRIPT)
wiki_log = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wiki_log)
ENTRY = "## [2026-10-22] ingest | Shared title\n- Disposition: Update\n"
BASE = "# Wiki Log\n\nHistorical entry.\n"


def record(number, body):
    return (f"## [2026-10-22] ingest | Shared title\n"
            f"<!-- wiki-log-id: 2026-10-22T12000000000{number}Z-{'a' * 32} -->\n"
            f"- Disposition: Update\n\n{body}\n")


class WikiLogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wiki = self.root / "wiki"
        self.wiki.mkdir()
        self.log = self.wiki / "log.md"
        self.log.write_bytes(BASE.replace("\n", "\r\n").encode("utf-8"))

    def run_cli(self, entry="", *args):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), str(self.root), *args],
                              input=entry, capture_output=True, text=True, encoding="utf-8")

    def test_parallel_processes_preserve_all_entries_in_the_known_log(self):
        history = self.log.read_bytes()
        entries = [ENTRY + f"\nAgent {number}: café — ✓\n" for number in range(12)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(self.run_cli, entries))
        self.assertTrue(all(result.returncode == 0 for result in results), results)
        content = self.log.read_text(encoding="utf-8")
        self.assertEqual(len(wiki_log.IDENTITY.findall(content)), len(entries))
        self.assertEqual(len(wiki_log.HEADING.findall(content)), len(entries))
        for number in range(12):
            self.assertEqual(content.count(f"Agent {number}: café — ✓"), 1)
        self.assertTrue(self.log.read_bytes().startswith(history))
        self.assertEqual(list(self.wiki.iterdir()), [self.log])

    def test_read_is_the_known_file_without_writing(self):
        before = self.log.read_bytes()
        result = self.run_cli("", "--read")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, BASE)
        self.assertEqual(before, self.log.read_bytes())

    def test_planning_writes_its_known_log_only(self):
        (self.wiki / "planning").mkdir()
        planning_log = self.wiki / "planning" / "log.md"
        planning_log.write_text("# Planning Log\n", encoding="utf-8")
        history = self.log.read_bytes()
        result = self.run_cli("## [2026-10-22] approved | A plan\n", "--planning")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("approved | A plan", planning_log.read_text(encoding="utf-8"))
        self.assertEqual(history, self.log.read_bytes())

    def test_invalid_entries_do_not_change_the_log(self):
        before = self.log.read_bytes()
        for entry in ("", "A paragraph", ENTRY + ENTRY,
                      "## [2026-10-22] closed | Wrong log\n", ENTRY + "\n<<<<<<< HEAD\n"):
            with self.subTest(entry=entry):
                result = self.run_cli(entry)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, self.log.read_bytes())

    def test_missing_log_is_not_initialized(self):
        missing = self.root / "missing"
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(missing)],
                                input=ENTRY, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.exists())

    def test_entry_file_accepts_utf8_bom_and_preserves_unicode(self):
        source = self.root / "entry.md"
        source.write_text(ENTRY + "\nCafé — ✓\n", encoding="utf-8-sig")
        result = self.run_cli("", "--entry-file", str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Café — ✓\n", self.log.read_text(encoding="utf-8"))

    def test_failed_replace_preserves_history_and_releases_lock(self):
        before = self.log.read_bytes()
        with patch.object(wiki_log.os, "replace", side_effect=PermissionError("busy")):
            with self.assertRaises(PermissionError):
                wiki_log.write_entry(self.log, ENTRY, False)
        self.assertEqual(before, self.log.read_bytes())
        self.assertEqual(list(self.wiki.iterdir()), [self.log])
        wiki_log.write_entry(self.log, ENTRY, False)

    def test_process_exit_releases_lock_without_removing_lock_file(self):
        program = (
            f"import sys, os; sys.path.insert(0, {str(SCRIPT.parent)!r}); import wiki_log;"
            f"\nwith wiki_log.log_lock(wiki_log.Path({str(self.log)!r})): os._exit(0)"
        )
        subprocess.run([sys.executable, "-B", "-c", program], check=True)
        self.assertEqual(self.run_cli(ENTRY).returncode, 0)

    def test_no_material_inventory_reads_the_canonical_log_with_ids(self):
        raw = self.root / "raw" / "t"
        raw.mkdir(parents=True)
        (raw / "orphan.md").write_text("# No material\n", encoding="utf-8")
        result = self.run_cli("## [2026-10-22] ingest | no material: raw/t/orphan.md\n- Disposition: No material\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        checker = SCRIPT.with_name("check_evidence.py")
        result = subprocess.run([sys.executable, "-B", str(checker), str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 evidence error(s), 0 unreferenced raw file(s)", result.stdout)

    def test_merge_preserves_whole_entries_and_is_symmetric(self):
        first, second = record(1, "Agent A body"), record(2, "Agent B body")
        merged = wiki_log.merge_logs(BASE, BASE + "\n" + second, BASE + "\n" + first)
        self.assertEqual(merged, BASE + "\n" + first + "\n" + second)
        self.assertEqual(merged, wiki_log.merge_logs(BASE, BASE + "\n" + first, BASE + "\n" + second))

    def test_merge_deduplicates_shared_ids(self):
        first, second = record(1, "Shared event"), record(2, "New event")
        merged = wiki_log.merge_logs(BASE, BASE + "\n" + first, BASE + "\n" + first + "\n" + second)
        self.assertEqual(merged.count("Shared event"), 1)
        self.assertIn(second, merged)

    def test_repeated_merges_from_independent_machines_preserve_all_entries(self):
        first, second, third = (record(1, "Machine A"), record(2, "Machine B"),
                                record(3, "Machine B next entry"))
        a = BASE + "\n" + first
        b = BASE + "\n" + second
        combined = wiki_log.merge_logs(BASE, a, b)
        b_next = b + "\n" + third
        self.assertFalse(combined.startswith(b))
        result = wiki_log.merge_logs(b, combined, b_next)
        self.assertEqual(result, BASE + "\n" + first + "\n" + second + "\n" + third)

    def test_base_entries_can_move_without_changing_identity(self):
        first, second, third = record(1, "A"), record(2, "B"), record(3, "C")
        base = BASE + "\n" + second
        ours = BASE + "\n" + third + "\n" + second
        theirs = BASE + "\n" + second + "\n" + first
        result = wiki_log.merge_logs(base, ours, theirs)
        self.assertEqual(result, BASE + "\n" + first + "\n" + second + "\n" + third)

    def test_base_entry_deletion_and_body_edits_fail(self):
        base = BASE + "\n" + record(1, "Immutable event")
        for modified in (BASE, base.replace("Immutable event", "Edited event")):
            with self.subTest(modified=modified):
                with self.assertRaises(ValueError):
                    wiki_log.merge_logs(base, modified, base + "\n" + record(2, "New event"))

    def test_growing_entry_set_merge_is_associative_and_idempotent(self):
        a, b, c = (BASE + "\n" + record(number, f"Machine {number}") for number in (1, 2, 3))
        left = wiki_log.merge_logs(BASE, wiki_log.merge_logs(BASE, a, b), c)
        right = wiki_log.merge_logs(BASE, a, wiki_log.merge_logs(BASE, b, c))
        self.assertEqual(left, right)
        self.assertEqual(left, wiki_log.merge_logs(BASE, left, left))

    def test_ambiguous_merges_fail_without_overwriting_ours(self):
        valid = BASE + "\n" + record(1, "Original")
        for ours, theirs in (
            (valid.replace("Historical", "Edited"), valid),
            (valid, BASE + "\n" + record(1, "Different")),
            (BASE + "\n" + ENTRY, valid),
            (valid + "\n<<<<<<< HEAD\n", valid),
        ):
            with self.subTest(ours=ours, theirs=theirs):
                files = [self.root / name for name in ("base", "ours", "theirs")]
                for path, content in zip(files, (BASE, ours, theirs)):
                    path.write_text(content, encoding="utf-8", newline="\n")
                before = files[1].read_bytes()
                result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--merge", *map(str, files)],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(files[1].read_bytes(), before)

    def git(self, *args, input=None):
        result = subprocess.run(["git", "-C", str(self.root), *args],
                                input=input.encode("utf-8") if input is not None else None,
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.decode("utf-8").strip()

    def test_git_invokes_registered_driver_without_creating_commits(self):
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        attributes = "wiki/log.md merge=wiki-log\nwiki/planning/log.md merge=wiki-log\n"
        (self.root / ".gitattributes").write_text(attributes, encoding="utf-8")
        result = self.run_cli("", "--install-merge-driver")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("merge: wiki-log", self.git("check-attr", "merge", "--", "wiki/log.md"))
        attributes_blob = self.git("hash-object", "-w", "--stdin", input=attributes)

        def tree(content):
            blob = self.git("hash-object", "-w", "--stdin", input=content)
            wiki_tree = self.git("mktree", input=f"100644 blob {blob}\tlog.md\n")
            return self.git("mktree", input=(
                f"100644 blob {attributes_blob}\t.gitattributes\n040000 tree {wiki_tree}\twiki\n"))

        trees = [tree(content) for content in (
            BASE, BASE + "\n" + record(1, "Agent A body"), BASE + "\n" + record(2, "Agent B body"))]
        merged = self.git("merge-tree", "--trivial-merge", *trees)
        self.assertNotIn("<<<<<<<", merged)
        self.assertIn("Agent A body", merged)
        self.assertIn("Agent B body", merged)
        a, b, b_next = (BASE + "\n" + record(1, "Agent A body"),
                        BASE + "\n" + record(2, "Agent B body"),
                        BASE + "\n" + record(2, "Agent B body") + "\n" + record(3, "Agent B next entry"))
        combined = wiki_log.merge_logs(BASE, a, b)
        repeated = self.git("merge-tree", "--trivial-merge", tree(b), tree(combined), tree(b_next))
        self.assertIn("Agent B next entry", repeated)
        self.assertNotIn("<<<<<<<", repeated)
        self.git("config", "--unset", "merge.wiki-log.driver")
        self.assertIn("<<<<<<<", self.git("merge-tree", "--trivial-merge", *trees))


if __name__ == "__main__":
    unittest.main()

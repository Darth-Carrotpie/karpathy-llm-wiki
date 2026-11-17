#!/usr/bin/env python3
"""Append to the canonical wiki log under a lock; merge whole appended entries.

Usage: wiki_log.py PROJECT_ROOT [--planning] [--entry-file FILE | --read]
       wiki_log.py PROJECT_ROOT --install-merge-driver
       wiki_log.py --merge BASE OURS THEIRS
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from uuid import uuid4


HEADING = re.compile(r"^## \[\d{4}-\d{2}-\d{2}\] ", re.MULTILINE)
IDENTITY = re.compile(r"^<!-- wiki-log-id: (\d{4}-\d{2}-\d{2}T\d{12}Z-[0-9a-f]{32}) -->$", re.MULTILINE)
CONFLICT = re.compile(r"^(?:<<<<<<< |=======\s*$|>>>>>>> )", re.MULTILINE)


@contextmanager
def log_lock(path: Path):
    # OS locks release on process exit; keep the lock file to avoid unlink races.
    key = hashlib.sha256(os.path.normcase(str(path.resolve())).encode("utf-8")).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"wiki-log-{key}.lock"
    with lock_path.open("a+b") as guard:
        if guard.seek(0, os.SEEK_END) == 0:
            guard.write(b"\0")
            guard.flush()
        if os.name == "nt":
            import msvcrt
        else:
            import fcntl
        deadline = time.monotonic() + 15
        while True:
            try:
                guard.seek(0)
                if os.name == "nt":
                    msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"log is busy: {path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            guard.seek(0)
            if os.name == "nt":
                msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(guard.fileno(), fcntl.LOCK_UN)


def write_entry(path: Path, entry: str, planning: bool) -> None:
    path = path.resolve()
    operations = "approved|revised|closed" if planning else "ingest|query|lint|research|review"
    if not re.match(rf"\A## \[\d{{4}}-\d{{2}}-\d{{2}}\] (?:{operations}) \| \S", entry):
        raise ValueError("entry must start with a dated heading and an operation for this log")
    if len(HEADING.findall(entry)) != 1 or CONFLICT.search(entry) or "<!-- wiki-log-id:" in entry:
        raise ValueError("provide one complete entry without conflict markers or reserved IDs")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S%fZ")
    heading, _, body = entry.rstrip().partition("\n")
    record = f"{heading}\n<!-- wiki-log-id: {stamp}-{uuid4().hex} -->\n{body}".rstrip() + "\n"
    with log_lock(path):
        original = path.read_bytes()
        if CONFLICT.search(original.decode("utf-8-sig")):
            raise ValueError("resolve the existing log conflict before appending")
        separator = b"\n" if original.endswith(b"\n") else b"\n\n"
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".wiki-log-", delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(original + separator + record.encode("utf-8"))
                output.flush()
                os.fsync(output.fileno())
            except BaseException:
                output.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            temporary.chmod(path.stat().st_mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def parse_log(text: str) -> tuple[str, dict[str, str]]:
    starts = list(HEADING.finditer(text))
    legacy_end = len(text)
    entries = {}
    for number, match in enumerate(starts):
        end = starts[number + 1].start() if number + 1 < len(starts) else len(text)
        entry = text[match.start():end].rstrip("\n") + "\n"
        ids = IDENTITY.findall(entry)
        if not ids and "<!-- wiki-log-id:" not in entry and not entries:
            continue
        if len(ids) != 1:
            raise ValueError("entry lacks a unique helper ID; resolve manually")
        if not IDENTITY.match(entry.partition("\n")[2]):
            raise ValueError("entry ID must follow its heading")
        identity = ids[0]
        if not entries:
            legacy_end = match.start()
        if identity in entries and entries[identity] != entry:
            raise ValueError("same entry ID has different content")
        entries[identity] = entry
    return text[:legacy_end].rstrip("\n"), entries


def merge_logs(base: str, ours: str, theirs: str) -> str:
    if any(CONFLICT.search(text) for text in (base, ours, theirs)):
        raise ValueError("log contains unresolved conflict markers")
    legacy, original = parse_log(base)
    entries = dict(original)
    for side in (ours, theirs):
        side_legacy, side_entries = parse_log(side)
        if side_legacy != legacy:
            raise ValueError("historical log content changed; resolve this merge manually")
        for identity, entry in original.items():
            if side_entries.get(identity) != entry:
                raise ValueError("a base entry was changed or deleted; resolve manually")
        for identity, entry in side_entries.items():
            if identity in entries and entries[identity] != entry:
                raise ValueError("same entry ID has different content")
            entries[identity] = entry
    if not entries:
        return base
    return legacy + "\n\n" + "\n".join(entries[key] for key in sorted(entries))


def install_merge_driver(root: Path) -> None:
    python = shlex.quote(sys.executable.replace("\\", "/"))
    script = shlex.quote(str(Path(__file__).resolve()).replace("\\", "/"))
    command = f'{python} -X utf8 -B {script} --merge "%O" "%A" "%B"'
    subprocess.run(["git", "-C", str(root), "config", "--local", "merge.wiki-log.driver", command], check=True)
    print("Installed local wiki-log merge driver; .gitattributes must select it for both logs.")


def main() -> int:
    sys.stdin.reconfigure(encoding="utf-8-sig")
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=Path.cwd(), type=Path)
    parser.add_argument("--planning", action="store_true")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--read", action="store_true")
    source.add_argument("--entry-file", type=Path)
    source.add_argument("--install-merge-driver", action="store_true")
    source.add_argument("--merge", nargs=3, type=Path, metavar=("BASE", "OURS", "THEIRS"))
    args = parser.parse_args()
    try:
        if args.merge:
            _, ours, _ = args.merge
            merged = merge_logs(*(path.read_text(encoding="utf-8") for path in args.merge))
            ours.write_text(merged, encoding="utf-8", newline="\n")
        elif args.install_merge_driver:
            install_merge_driver(args.project_root.resolve())
        else:
            directory = args.project_root.resolve() / "wiki"
            path = (directory / "planning" if args.planning else directory) / "log.md"
            if args.read:
                print(path.read_text(encoding="utf-8"), end="")
            else:
                entry = args.entry_file.read_text(encoding="utf-8-sig") if args.entry_file else sys.stdin.read()
                write_entry(path, entry, args.planning)
                print(path)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"wiki log: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

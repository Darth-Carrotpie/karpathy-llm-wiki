#!/usr/bin/env python3
"""Append to the canonical wiki log under a lock; merge whole appended entries;
seal old entries into immutable segments beside the live log.

Usage: wiki_log.py PROJECT_ROOT [--planning] [--entry-file FILE | --read]
       wiki_log.py PROJECT_ROOT [--planning] --rotate YYYY-MM-DD | --verify
       wiki_log.py PROJECT_ROOT --install-merge-driver
       wiki_log.py --merge BASE OURS THEIRS
"""

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
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


HEADING = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\] ", re.MULTILINE)
IDENTITY = re.compile(r"^<!-- wiki-log-id: (\d{4}-\d{2}-\d{2}T\d{12}Z-[0-9a-f]{32}) -->$", re.MULTILINE)
CONFLICT = re.compile(r"^(?:<<<<<<< |=======\s*$|>>>>>>> )", re.MULTILINE)
# One seal line per sealed segment, closing the live log's header.
SEAL = re.compile(r"^- Sealed before (\d{4}-\d{2}-\d{2}): \[log-sealed-\1\.md\]\(log-sealed-\1\.md\) "
                  r"<!-- wiki-log-seal sha256:([0-9a-f]{64}) -->$", re.MULTILINE)


def segment_name(cutoff: str) -> str:
    return f"log-sealed-{cutoff}.md"


def seal_digest(data: bytes) -> str:
    # LF-normalized so a CRLF checkout of the same segment still verifies.
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def entry_date(entry: str) -> str:
    return HEADING.match(entry).group(1)


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


def replace_atomically(path: Path, data: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".wiki-log-", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            output.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.chmod(path.stat().st_mode)
        # Windows denies a replace while a scanner or reader briefly holds the file;
        # the caller owns the log lock, so a short bounded retry is safe.
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        temporary.unlink(missing_ok=True)


def write_entry(path: Path, entry: str, planning: bool) -> None:
    path = path.resolve()
    operations = "approved|revised|closed|audited" if planning else "ingest|query|lint|research|review|maintenance"
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
        replace_atomically(path, original + separator + record.encode("utf-8"))


def parse_log(text: str) -> tuple[str, dict[str, str], list[str], dict[str, str]]:
    """Split a log into header, seals {cutoff: sha256}, legacy entry slices and ID'd entries."""
    starts = list(HEADING.finditer(text))
    header = text[:starts[0].start()] if starts else text
    seals = {}
    marker = SEAL.search(header)
    if marker:
        for line in header[marker.start():].splitlines():
            found = SEAL.fullmatch(line)
            if found and found.group(1) not in seals:
                seals[found.group(1)] = found.group(2)
            elif line.strip():
                raise ValueError("seal lines must close the log header, once per segment")
        header = header[:marker.start()]
    elif "wiki-log-seal" in header:
        raise ValueError("malformed seal line; resolve manually")
    legacy, entries = [], {}
    for number, match in enumerate(starts):
        end = starts[number + 1].start() if number + 1 < len(starts) else len(text)
        entry = text[match.start():end].rstrip("\n") + "\n"
        ids = IDENTITY.findall(entry)
        if not ids and "<!-- wiki-log-id:" not in entry and not entries:
            legacy.append(text[match.start():end])
            continue
        if len(ids) != 1:
            raise ValueError("entry lacks a unique helper ID; resolve manually")
        if not IDENTITY.match(entry.partition("\n")[2]):
            raise ValueError("entry ID must follow its heading")
        identity = ids[0]
        if identity in entries and entries[identity] != entry:
            raise ValueError("same entry ID has different content")
        entries[identity] = entry
    return header, seals, legacy, entries


def render_log(header: str, seals: dict[str, str], legacy: list[str], entries: list[str]) -> str:
    if seals:
        lines = "\n".join(f"- Sealed before {cutoff}: [{segment_name(cutoff)}]({segment_name(cutoff)}) "
                          f"<!-- wiki-log-seal sha256:{seals[cutoff]} -->" for cutoff in sorted(seals))
        header = header.rstrip("\n") + "\n\n" + lines + "\n\n"
    text = (header + "".join(legacy)).rstrip("\n")
    return text + "\n\n" + "\n".join(entries) if entries else text + "\n"


def sealed_away(base: dict, side: dict, cutoff: str) -> set:
    """Base keys the side removed; only entries dated before the side's new seal may go."""
    removed = set()
    for key, entry in base.items():
        if key in side:
            if side[key] != entry:
                raise ValueError("a base entry was changed or deleted; resolve manually")
        elif cutoff and entry_date(entry) < cutoff:
            removed.add(key)
        else:
            raise ValueError("a base entry was changed or deleted; resolve manually")
    return removed


def legacy_keys(legacy: list[str]) -> dict:
    keyed, seen = {}, {}
    for entry in legacy:
        text = entry.rstrip("\n")
        seen[text] = seen.get(text, 0) + 1
        keyed[(text, seen[text])] = entry
    return keyed


def merge_logs(base: str, ours: str, theirs: str) -> str:
    if any(CONFLICT.search(text) for text in (base, ours, theirs)):
        raise ValueError("log contains unresolved conflict markers")
    header, seals, legacy, original = parse_log(base)
    base_legacy = legacy_keys(legacy)
    entries, dropped, added_seals = dict(original), set(), []
    for side in (ours, theirs):
        side_header, side_seals, side_legacy, side_entries = parse_log(side)
        if side_header.rstrip("\n") != header.rstrip("\n"):
            raise ValueError("historical log content changed; resolve this merge manually")
        if any(side_seals.get(cutoff) != digest for cutoff, digest in seals.items()):
            raise ValueError("a recorded seal changed; resolve manually")
        new_seals = {cutoff: digest for cutoff, digest in side_seals.items() if cutoff not in seals}
        added_seals.append(new_seals)
        cutoff = max(new_seals, default="")
        side_keyed = legacy_keys(side_legacy)
        dropped |= sealed_away(base_legacy, side_keyed, cutoff)
        if list(side_keyed) != [key for key in base_legacy if key in side_keyed]:
            raise ValueError("historical log content changed; resolve this merge manually")
        dropped |= sealed_away(original, side_entries, cutoff)
        for identity, entry in side_entries.items():
            if identity in entries and entries[identity] != entry:
                raise ValueError("same entry ID has different content")
            entries[identity] = entry
    if added_seals[0] and added_seals[1] and added_seals[0] != added_seals[1]:
        raise ValueError("both sides rotated the log differently; rotate on one branch only")
    seals = {**seals, **added_seals[0], **added_seals[1]}
    kept_legacy = [entry for key, entry in base_legacy.items() if key not in dropped]
    kept = [entries[key] for key in sorted(entries) if key not in dropped]
    if not kept and not added_seals[0] and not added_seals[1] and len(kept_legacy) == len(legacy):
        return base
    return render_log(header, seals, kept_legacy, kept)


def rotate_log(path: Path, before: str) -> tuple[Path, int]:
    """Move every entry dated before the cutoff, verbatim, into a new sealed segment."""
    date.fromisoformat(before)
    path = path.resolve()
    segment = path.with_name(segment_name(before))
    with log_lock(path):
        text = path.read_text(encoding="utf-8-sig")
        if CONFLICT.search(text):
            raise ValueError("resolve the existing log conflict before rotating")
        header, seals, legacy, entries = parse_log(text)
        if seals and before <= max(seals):
            raise ValueError("the cutoff must be later than the newest seal")
        moved = [entry.rstrip("\n") + "\n" for entry in legacy if entry_date(entry) < before]
        moved += [entry for entry in entries.values() if entry_date(entry) < before]
        if not moved:
            raise ValueError(f"no entries dated before {before}")
        title = re.search(r"^# (.+)$", header, re.MULTILINE)
        data = (f"# {title.group(1) if title else 'Log'}: sealed before {before}\n\n"
                f"Entries dated before {before}, moved verbatim from [{path.name}]({path.name}). "
                "Sealed: never edit this file; the live log records its SHA-256.\n\n"
                + "\n".join(moved)).encode("utf-8")
        seals[before] = seal_digest(data)
        updated = render_log(header, seals, [e for e in legacy if entry_date(e) >= before],
                             [e for e in entries.values() if entry_date(e) >= before])
        with segment.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        try:
            replace_atomically(path, updated.encode("utf-8"))
        except BaseException:
            segment.unlink(missing_ok=True)
            raise
    return segment, len(moved)


def verify_seals(path: Path) -> list[str]:
    _, seals, _, _ = parse_log(path.read_text(encoding="utf-8-sig"))
    problems = []
    for cutoff, expected in sorted(seals.items()):
        segment = path.with_name(segment_name(cutoff))
        if not segment.is_file():
            problems.append(f"missing sealed segment: {segment.name}")
        elif seal_digest(segment.read_bytes()) != expected:
            problems.append(f"sealed segment changed: {segment.name}")
    return problems


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
    source.add_argument("--rotate", metavar="YYYY-MM-DD", help="seal entries dated before this date")
    source.add_argument("--verify", action="store_true", help="check every seal against its segment")
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
            if args.rotate:
                segment, count = rotate_log(path, args.rotate)
                print(f"sealed {count} entries into {segment}")
            elif args.verify:
                problems = verify_seals(path)
                print("\n".join(problems) or f"all seals verified: {path}")
                return 1 if problems else 0
            elif args.read:
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

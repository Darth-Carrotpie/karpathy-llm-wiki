#!/usr/bin/env python3
"""Update canonical indexes from a snapshot; merge independent rows by article path.

Usage: wiki_index.py PROJECT_ROOT [--planning] --snapshot FILE
       wiki_index.py PROJECT_ROOT [--planning] --base-file FILE --updated-file FILE
       wiki_index.py PROJECT_ROOT --install-merge-driver
       wiki_index.py --merge BASE OURS THEIRS
"""

import argparse
import hashlib
import os
from pathlib import Path
import posixpath
import re
import shlex
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit

from wiki_log import CONFLICT, log_lock


SCHEMAS = {
    ("Article", "Summary", "Updated"),
    ("Backlog", "Summary", "Updated"),
    ("Plan", "Status", "Topics", "Approved", "Updated", "Audit"),
    ("Plan", "Status", "Topics", "Approved", "Closed", "Audit"),
}
ROW = re.compile(r"^\|\s*(?:\[MISSING\]\s*)?\[[^\]]+\]\(([^()\s]+)\)\s*\|")
TOKEN = "<!-- wiki-index-rows: "


def marker(section):
    return TOKEN + hashlib.sha256(section.encode("utf-8")).hexdigest() + " -->\n"


def parse_index(text):
    if CONFLICT.search(text) or TOKEN in text:
        raise ValueError("index contains unresolved or reserved merge markers")
    lines = text.splitlines(keepends=True)
    skeleton, rows, tables = [], {}, {}
    section = None
    fence = None
    number = 0
    while number < len(lines):
        line = lines[number]
        delimiter = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if delimiter:
            ticks = delimiter[1]
            if fence is None:
                fence = ticks
            elif ticks[0] == fence[0] and len(ticks) >= len(fence):
                fence = None
            skeleton.append(line)
            number += 1
            continue
        if not fence:
            heading = re.match(r"^## (.+?)\s*\n?$", line)
            if heading:
                section = heading[1]
            schema = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
            if schema in SCHEMAS:
                if section is None or section in tables:
                    raise ValueError("index needs one supported table per unique topic heading")
                if number + 1 >= len(lines) or not re.fullmatch(
                    r"\s*\|" + r"\s*:?-+:?\s*\|" * len(schema) + r"\s*", lines[number + 1]
                ):
                    raise ValueError(f"invalid table separator in {section}")
                tables[section] = schema
                skeleton.extend((line, lines[number + 1], marker(section)))
                number += 2
                while number < len(lines) and lines[number].lstrip().startswith("|"):
                    row = lines[number]
                    match = ROW.match(row)
                    if not match:
                        raise ValueError(f"unsupported index row in {section}: {row.strip()}")
                    if len(row.strip().strip("|").split("|")) < len(schema):
                        raise ValueError(f"incomplete index row in {section}: {row.strip()}")
                    link = urlsplit(match[1])
                    key = posixpath.normpath(unquote(link.path))
                    if (link.scheme or link.netloc or link.query or key.startswith(("/", "../"))
                            or "\\" in key or key == "."):
                        raise ValueError(f"expected a relative article path: {match[1]}")
                    if key in rows:
                        raise ValueError(f"duplicate index entry: {key}")
                    rows[key] = (section, schema, row.rstrip("\n") + "\n")
                    number += 1
                continue
        skeleton.append(line)
        number += 1
    return "".join(skeleton), rows, tables


def merge_prose(base, ours, theirs):
    if ours == theirs or theirs == base:
        return ours
    if ours == base:
        return theirs
    with tempfile.TemporaryDirectory(prefix="wiki-index-merge-") as directory:
        files = [Path(directory) / name for name in ("ours", "base", "theirs")]
        for path, content in zip(files, (ours, base, theirs)):
            path.write_text(content, encoding="utf-8", newline="\n")
        result = subprocess.run(["git", "merge-file", "-p", "--diff3", *map(str, files)],
                                capture_output=True)
        if result.returncode != 0:
            raise ValueError("index prose or layout conflicts; resolve manually")
        return result.stdout.decode("utf-8")


def merge_layout(base, ours, theirs):
    def sections(text):
        # Ignore headings inside fenced examples, as the row parser does.
        result = {"": ""}
        heading = ""
        fence = None
        for line in text.splitlines(keepends=True):
            delimiter = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
            if delimiter:
                ticks = delimiter[1]
                if fence is None:
                    fence = ticks
                elif ticks[0] == fence[0] and len(ticks) >= len(fence):
                    fence = None
            match = re.match(r"^## (.+?)\s*\n?$", line) if not fence else None
            if match:
                heading = match[1]
                if heading in result:
                    raise ValueError(f"duplicate topic heading: {heading}")
                result[heading] = ""
            result[heading] += line
        return result

    original, left, right = map(sections, (base, ours, theirs))
    order = list(original) + sorted((left.keys() | right.keys()) - original.keys())
    result = []
    for section in order:
        before, our_text, their_text = original.get(section), left.get(section), right.get(section)
        if our_text is None or their_text is None:
            if our_text == their_text or their_text == before:
                chosen = our_text
            elif our_text == before:
                chosen = their_text
            else:
                raise ValueError(f"competing deletion or edit of index topic: {section}")
        else:
            chosen = merge_prose(before or "", our_text, their_text)
        if chosen:
            if result and not result[-1].endswith("\n\n"):
                result.append("\n" if result[-1].endswith("\n") else "\n\n")
            result.append(chosen)
    return "".join(result)


def merge_indexes(base, ours, theirs):
    parsed = [parse_index(text) for text in (base, ours, theirs)]
    original, left, right = (item[1] for item in parsed)
    merged = {}
    for key in sorted(original.keys() | left.keys() | right.keys()):
        before, our_row, their_row = original.get(key), left.get(key), right.get(key)
        if our_row == their_row or their_row == before:
            chosen = our_row
        elif our_row == before:
            chosen = their_row
        else:
            raise ValueError(f"competing edits, deletion or move of index entry: {key}")
        if chosen is not None:
            merged[key] = chosen
    skeleton = merge_layout(*(item[0] for item in parsed))
    # Keep the base's curated order; sort new rows so merge direction cannot change it.
    order = list(original) + sorted(merged.keys() - original.keys())
    sections = {value[0] for value in merged.values()} | {s for item in parsed for s in item[2]}
    for section in sections:
        keys = [key for key in order if key in merged and merged[key][0] == section]
        if keys and merged[keys[0]][1][0] == "Plan":
            # Active uses approval date; Closed uses closing date, not approval date.
            date_cell = 2 if merged[keys[0]][1][4] == "Closed" else 1
            keys.sort(key=lambda key: (merged[key][2].strip().strip("|").rsplit("|", 3)[date_cell].strip(), key),
                      reverse=True)
        token = marker(section)
        if skeleton.count(token) > 1 or (keys and token not in skeleton):
            raise ValueError(f"index rows lost their topic table: {section}")
        skeleton = skeleton.replace(token, "".join(merged[key][2] for key in keys))
    if parse_index(skeleton)[1] != merged:
        raise ValueError("merged index changed a table schema or lost entries")
    return skeleton


def update_index(path, base, updated):
    path = path.resolve()
    with log_lock(path):
        original = path.read_bytes()
        current = original.decode("utf-8-sig").replace("\r\n", "\n")
        merged = merge_indexes(base, current, updated)
        if merged == current:
            return
        if b"\r\n" in original and original.count(b"\n") == original.count(b"\r\n"):
            merged = merged.replace("\n", "\r\n")
        content = merged.encode("utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8")
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".wiki-index-", delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            except BaseException:
                output.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            temporary.chmod(path.stat().st_mode)
            # Windows readers can briefly deny replacement even while writers hold the lock.
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


def install_merge_driver(root):
    python = shlex.quote(sys.executable.replace("\\", "/"))
    script = shlex.quote(str(Path(__file__).resolve()).replace("\\", "/"))
    command = f'{python} -X utf8 -B {script} --merge "%O" "%A" "%B"'
    subprocess.run(["git", "-C", str(root), "config", "--local", "merge.wiki-index.driver", command], check=True)
    print("Installed local wiki-index merge driver; .gitattributes must select it for both indexes.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=Path.cwd(), type=Path)
    parser.add_argument("--planning", action="store_true")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--snapshot", type=Path)
    action.add_argument("--base-file", type=Path)
    action.add_argument("--install-merge-driver", action="store_true")
    action.add_argument("--merge", nargs=3, type=Path, metavar=("BASE", "OURS", "THEIRS"))
    parser.add_argument("--updated-file", type=Path)
    args = parser.parse_args()
    if bool(args.base_file) != bool(args.updated_file):
        parser.error("--base-file and --updated-file are required together")
    try:
        if args.merge:
            result = merge_indexes(*(path.read_text(encoding="utf-8-sig") for path in args.merge))
            args.merge[1].write_text(result, encoding="utf-8", newline="\n")
        elif args.install_merge_driver:
            install_merge_driver(args.project_root.resolve())
        else:
            directory = args.project_root.resolve() / "wiki"
            path = (directory / "planning" if args.planning else directory) / "index.md"
            if any(source and source.resolve() == path.resolve()
                   for source in (args.snapshot, args.base_file, args.updated_file)):
                raise ValueError("use separate temporary snapshot and updated files, not the live index")
            if args.snapshot:
                with log_lock(path):
                    content = path.read_bytes()
                    parse_index(content.decode("utf-8-sig"))
                    with args.snapshot.open("xb") as output:
                        output.write(content)
            else:
                update_index(path, args.base_file.read_text(encoding="utf-8-sig"),
                             args.updated_file.read_text(encoding="utf-8-sig"))
            print(path)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"wiki index: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

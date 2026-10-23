# Concurrent index writes and merges

Read `wiki/index.md` and `wiki/planning/index.md` directly. They remain complete,
authored Markdown files; there are no fragments, generated views or refresh steps.

## Writing in one checkout

Before editing, take a snapshot into a new temporary file outside `wiki/`:

```text
python -X utf8 -B <skill-dir>/scripts/wiki_index.py <project-root> --snapshot <before.md>
```

Copy that snapshot to a second temporary file, `<after.md>`, and edit the second
file. Keep the original snapshot unchanged. Publish the result:

```text
python -X utf8 -B <skill-dir>/scripts/wiki_index.py <project-root> --base-file <before.md> --updated-file <after.md>
```

Add `--planning` to both commands for the planning index. Use fresh temporary
names for each operation. The snapshot command refuses to overwrite an existing
file; neither temporary file may be the live index. Remove your temporary files
after a successful update. Initial index creation is still Initialization's job.

Publishing takes an OS lock, rereads the live index and compares it with both
the original snapshot and your edited copy. This preserves other agents' changes
to different rows, even when your snapshot is old. Locking alone would still
permit a stale full-file overwrite. Successful writes replace the file atomically;
a rejected update or failed replacement leaves its bytes unchanged. OS locks
release on process exit. All concurrent writers must use this helper.

On a conflict, read the current index and reconcile the reported row or prose.
Take a fresh snapshot and reapply your intended change after reviewing the other
agent's work. Do not silently refresh the base and reuse a stale full-file edit.
Coordinate direct edits and Git checkout/merge operations separately from writers.

## Merging local branches and machines

Register once in every project clone that performs local merges:

```text
python -X utf8 -B <skill-dir>/scripts/wiki_index.py <project-root> --install-merge-driver
```

Add these rules to the project's tracked `.gitattributes`, alongside its log rules:

```gitattributes
wiki/index.md merge=wiki-index
wiki/planning/index.md merge=wiki-index
```

Verify with `git check-attr merge -- wiki/index.md wiki/planning/index.md` and
`git config --local --get merge.wiki-index.driver`. Both attributes must report
`wiki-index`, and the config must point to the active Python and installed script.
The script imports `wiki_log.py` from the same installation; install the complete
skill. Re-register after moving Python or the skill.

Each machine fetches, merges locally and then pushes. The merging clone needs the
updated skill and registration; Git does not distribute local config by push.
The attributes alone leave ordinary text merging in effect. This does not cover
hosting-service pull-request merges or distribute an uncommitted local edit.

## Merge rules and limits

- Supported tables are the global index's `Article / Summary / Updated`, planning
  `Active` and `Closed` plan tables, and `Backlog / Summary / Updated`, under unique
  level-two topic headings with one supported table per heading. Other table
  schemas and prose use ordinary three-way text merging. A prose-heavy research
  index is not assigned this driver automatically.
- A row's identity is its normalized relative link path, across all sections of
  that file. Labels, summaries, status, section and dates remain authored content.
  Article paths and non-Markdown assets are accepted; duplicate targets fail.
- Different row edits combine; identical changes appear once. A one-sided
  deletion propagates. Competing edits to the same row, different new rows for
  the same path, delete-versus-edit and move-versus-edit fail for review. No
  newest-date winner, field concatenation or line-union merge is used.
- Independent new topics combine. Topic introductions, headers and other prose
  are retained and three-way merged; conflicting changes require review. Existing
  topic and article order follows the base, with new topics and rows sorted by
  path/name. Active plans sort by approval date and Closed plans by closing date,
  newest first. Row order is not identity.
- On a driver conflict, the command reports the target and leaves Git's `%A`
  unchanged. Git retains the base and both sides as unmerged index stages; use
  your merge tool or `git show :1:wiki/index.md`, `:2:wiki/index.md` and
  `:3:wiki/index.md` to review them. Do not treat the absence of inline markers as
  a resolved merge. Writers should not run during an unresolved Git merge.

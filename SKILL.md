---
name: karpathy-llm-wiki
description: "Use when building or maintaining a personal LLM-powered knowledge base. Triggers: ingesting sources into a wiki, querying wiki knowledge, linting wiki quality, recording or updating a plan in the wiki, 'add to wiki', 'what do I know about', or any mention of 'LLM wiki' or 'Karpathy wiki'. Also use unprompted in any project that has a wiki: right after the user approves a sprint's implementation plan, when an approved plan changes significantly, and when a plan's implementation finishes."
---

# Karpathy LLM Wiki

Build and maintain a personal knowledge base using LLMs. You manage two directories: `raw/` (immutable source material) and `wiki/` (compiled knowledge articles). Sources go into raw/, you compile them into wiki articles, and the wiki compounds over time.

Core ideas from Karpathy:
- "The LLM writes and maintains the wiki; the human reads and asks questions."
- "The wiki is a persistent, compounding artifact."

## Architecture

Three layers, all under the user's project root:

**raw/** — Immutable source material. You read, never modify. Organized by topic subdirectories (e.g., `raw/machine-learning/`).

**wiki/** — Compiled knowledge articles. You have full ownership. Organized by topic subdirectories, one level only: `wiki/<topic>/<article>.md`. Contains two special files:
- `wiki/index.md` — Global index. One row per article, grouped by topic, with link + summary + Updated date.
- `wiki/log.md` — Append-only operation log.

One topic directory is reserved: `wiki/planning/` holds agreed plans with their own `index.md` and `log.md`, and the global index links only to that planning index (see Plan).

**SKILL.md** (this file) — Schema layer. Defines structure and workflow rules.

Templates live in `references/` relative to this file. Read them when you need the exact format for raw files, articles, archive pages, plan pages, the index, or the planning index.

### Initialization

Triggers only on the first Ingest. Check whether `raw/` and `wiki/` exist. Create only what is missing; never overwrite existing files:

- `raw/` directory (with `.gitkeep`)
- `wiki/` directory (with `.gitkeep`)
- `wiki/index.md` — heading `# Knowledge Base Index`, empty body
- `wiki/log.md` — heading `# Wiki Log`, empty body

If Query or Lint cannot find the wiki structure, tell the user: "Run an ingest first to initialize the wiki." Do not auto-create.

## The Grounding Invariant

Every load-bearing fact in wiki/ — numbers, dates, direct quotes — exists verbatim in the raw/ files linked by that article's Raw field. Compile *establishes* this invariant (locate before you write); lint *verifies* it (`scripts/check_evidence.py` greps the high-signal literals — suffixed or large numbers, decimals, ISO dates, longer quotes — in the linked raws; the compile-time locate-before-write rule covers the rest). Because raw/ is immutable, a verified article stays verified; the script re-checks the whole wiki in seconds, so there is no incremental state to maintain.

Two page kinds sit outside the invariant because they do not compile sources: archive pages (a synthesized answer, see Archiving) and plan pages (agreed intent, see Plan).

---

## Ingest

Fetch a source into raw/, then compile it into wiki/ — unless the source adds nothing new. Always fetch; whether to compile depends on the triage below.

### Fetch (raw/)

1. Get the source content using whatever web or file tools your environment provides. If nothing can reach the source, ask the user to paste it directly.

2. Pick a topic directory. Check existing `raw/` subdirectories first; reuse one if the topic is close enough. Create a new subdirectory only for genuinely distinct topics.

3. Save as `raw/<topic>/YYYY-MM-DD-descriptive-slug.md`.
   - Slug from source title, kebab-case, max 60 characters.
   - Published date unknown → omit the date prefix from the file name (e.g., `descriptive-slug.md`). The metadata Published field still appears; set it to `Unknown`.
   - If a file with the same name already exists, append a numeric suffix (e.g., `descriptive-slug-2.md`).
   - Include metadata header: source URL, collected date, published date.
   - Preserve original text. Clean formatting noise. Do not rewrite opinions.

   See `references/raw-template.md` for the exact format.

### Triage

After saving the raw file and before editing wiki/, search wiki/ with the source's key entities and synonyms, then state the disposition:

- **New** — creates one or more new articles.
- **Update** — merges into existing article(s).
- **Disputed** — contradicts existing content; may combine with New or Update (see Compile for conflict annotation).
- **No material** — adds no knowledge beyond what the wiki already holds. Keep the raw file, log it (see Post-Ingest), and stop. Do not force an article out of a thin source.

New, Update, and Disputed may be combined. No material is exclusive.

### Compile (wiki/)

Determine where the new content belongs:

- **Same core thesis as existing article** → Merge into that article. Add the new source to Sources/Raw. Update affected sections.
- **New concept** → Create a new article in the most relevant topic directory. Name the file after the concept, not the raw file.
- **Spans multiple topics** → Place in the most relevant directory. Add See Also cross-references to related articles elsewhere.

These are not mutually exclusive. A single source may warrant merging into one article while also creating a separate article for a distinct concept it introduces. In all cases, check for factual conflicts: if the new source contradicts existing content, mark the contested claims with a **Status: Disputed** block (see `references/article-template.md`). When the conflicting content lives in separate articles, mark both and cross-link them.

**Source fidelity.** Every number, date, and direct quote must be located in the raw file (grep or read) *before* it is written; write the value exactly as found — if the source says 42K, write 42K, not 42,000. Derived values (sums, deltas, counts you computed) must show their components so each component is findable in raw. If you cannot locate a value, do not write its exact form; drop it or state it without precision.

See `references/article-template.md` for article format. Key points:
- Sources field: author, organization, or publication name + date, semicolon-separated.
- Raw field: markdown links to raw/ files, semicolon-separated.
- Relative paths from `wiki/<topic>/` use `../../raw/<topic>/<file>.md` (two levels up to project root).

### Cascade Updates

After the primary article, check for ripple effects. Do not rely on the index alone: search the full wiki for the source's key entities, aliases, and the claims it touches, then update every non-archive article whose content is materially affected. Each updated file gets its Updated date refreshed.

When the new source supersedes or contradicts an existing claim, keep the old claim for the record but mark it with a Status block (see `references/article-template.md`): **Outdated** when something newer replaces it, **Disputed** when sources disagree. Never silently rewrite history.

Archive pages are never cascade-updated (they are point-in-time snapshots).

### Post-Ingest

Update `wiki/index.md`: add or update entries for every touched article — except articles under `wiki/planning/`, whose entries live in `wiki/planning/index.md` (see Plan). When adding a new topic section, include a one-line description. The Updated date reflects when the article's knowledge content last changed, not the file system timestamp. See `references/index-template.md` for format.

Append to `wiki/log.md`:

```
## [YYYY-MM-DD] ingest | <primary article title>
- Disposition: <New; Update; Disputed>
- Raw: <raw file path>
- Updated: <cascade-updated article title>
```

Omit `- Updated:` lines when no cascade updates occur. For No material, log and stop. Use a project-root-relative raw path (for example, `raw/topic/file.md`):

```
## [YYYY-MM-DD] ingest | no material: <project-root-relative raw file path>
- Disposition: No material
```

The exact no-material heading is the machine-readable inventory key; the Disposition line remains required for a complete human-readable log entry.

### Research (multi-source ingest)

Use only when the user explicitly asks to research a topic or gather sources into the wiki. Ordinary knowledge questions go to Query, which never writes files.

1. Split the topic into a few angles. For each, search with a wide net — official names, abbreviations, and synonyms, not just the literal keywords.
2. For any core claim you expect to conclude, deliberately search the opposing side: failures, criticism, failed replications.
3. Save selected sources to raw/ as usual. Searching may run in parallel; compilation must not — compile one source at a time, because index.md, log.md, and cascade updates are shared state.

---

## Query

Search the wiki and answer questions. Examples of triggers:
- "What do I know about X?"
- "Summarize everything related to Y"
- "Compare A and B based on my wiki"

### Steps

1. Read `wiki/index.md` to locate candidate articles, then full-text search wiki/ with the topic's key terms *and their synonyms*. Never claim the wiki has no relevant content until both the index and the full-text search come back empty — and say that you searched.
2. Read the articles you found and synthesize an answer.
3. Prefer wiki content over your own training knowledge. Cite sources with markdown links: `[Article Title](wiki/topic/article.md)` (project-root-relative paths for in-conversation citations; within wiki/ files, use paths relative to the current file).
4. Output the answer in the conversation. Do not write files unless asked.

### Archiving

When the user explicitly asks to archive or save the answer to the wiki:

1. Write the answer as a new wiki page. See `references/archive-template.md`. When converting conversation citations to the archive page, rewrite project-root-relative paths (e.g., `wiki/topic/article.md`) to file-relative paths (e.g., `../topic/article.md` or `article.md` for same-directory).
   - Sources: markdown links to the wiki articles cited in the answer.
   - No Raw field (content does not come from raw/).
   - File name reflects the query topic, e.g., `transformer-architectures-overview.md`.
   - Place in the most relevant topic directory.
2. Always create a new page. Never merge into existing articles (archive content is a synthesized answer, not raw material).
3. Update `wiki/index.md`. Prefix the Summary with `[Archived]`.
4. Append to `wiki/log.md`:
   ```
   ## [YYYY-MM-DD] query | Archived: <page title>
   ```

---

## Plan

Keep a record of agreed work plans — a sprint's implementation plan, its revisions, and its outcome — in `wiki/planning/`. A plan records intent and decisions, not knowledge compiled from sources, so plans follow their own rules: no Raw field, their own index, their own log.

Triggers:
- A sprint's implementation plan is finished and the user approves it → **Record**.
- An approved plan changes significantly → **Revise**.
- A plan's implementation finishes, or the plan is abandoned or replaced → **Close**.
- The user asks to record, update, or close a plan.

The first three are standing duties of whichever agent runs the plan: act on them unprompted, without waiting for the user to ask, and without project instruction files having to repeat them. They apply only in a project that already has a wiki (`wiki/index.md` exists). Without one, plan as usual and write nothing, unless the user asks for the plan to be recorded; that request initializes the wiki as below.

### Layout

```text
wiki/planning/
├── index.md                   ← Planning index: every plan and backlog, with status
├── log.md                     ← Planning log: append-only, plan operations only
├── YYYY-MM-DD-plan-slug.md    ← One page per plan, dated by its approval
└── backlog-slug.md            ← Optional standing to-do lists (ordinary articles)
```

The planning index is a branch of the global index: the one entry point to every upcoming, active, and finished plan. `wiki/index.md` holds a single `planning` row linking to `planning/index.md` and never lists plans or backlogs one by one. Start every plan lookup at the planning index rather than searching for plan files, and avoid linking plan pages directly from outside `wiki/planning/`; link the planning index instead. Plans move from Active to Closed and get superseded; the index stays put, so links to it never go stale.

Initialization: on the first plan operation, create what is missing, never overwriting:
- `wiki/planning/index.md` — see `references/planning-index-template.md`
- `wiki/planning/log.md` — heading `# Planning Log`, empty body
- the `planning` section of `wiki/index.md`, holding its one row — see `references/index-template.md`

If `wiki/` itself is missing, first create `wiki/index.md` and `wiki/log.md` as in Initialization. If `wiki/planning/` already holds ordinary articles (to-do lists, roadmaps), keep them: list them under Backlogs in the planning index and move their rows out of `wiki/index.md`.

### Record (plan approved)

Run right after the user approves the plan, before implementation starts.

1. Create `wiki/planning/YYYY-MM-DD-<slug>.md` from `references/plan-template.md`. The date is the approval date; the slug names the plan's subject, kebab-case, max 60 characters.
2. Write the high-level topics only: the goal, scope in and out, one line per work item, the decisions taken and why, open questions, risks. No steps, file lists or code — the page should read in a minute. If the full plan lives in a durable file, link it in Sources.
3. Header: `Plan status: Approved`, Approved and Updated set to today, `Audit: none` unless the plan itself calls for an audit.
4. Add a row under Active in `wiki/planning/index.md`.
5. Append to `wiki/planning/log.md`:
   ```
   ## [YYYY-MM-DD] approved | <Plan title>
   - Page: wiki/planning/<file>.md
   - Topics: <the high-level topics, comma-separated>
   ```

### Revise (plan changed)

A change is significant when it alters the goal, the scope, a work item, or a decision. Wording, ordering and typo fixes are not: edit in place, no log entry.

For a significant change, **ask the user** which form the record takes. Never choose for them:

- **Overwrite** — rewrite the page body so it describes the plan as it now stands. Add one entry to its Changes section: the date, `Overwritten`, and why. The earlier text survives only in version control.
- **Change record** — leave the existing body untouched. Append a dated entry to Changes holding only what changed: items added, removed or changed, and decisions reversed, each with its reason.

Either way:
1. Refresh Updated in the page header and in the planning index row.
2. Decide the audit flag (below) and write it in the header, the Changes entry, and the index row.
3. Append to `wiki/planning/log.md`:
   ```
   ## [YYYY-MM-DD] revised | <Plan title>
   - Mode: <Overwrite | Change record>
   - Changed: <one line>
   - Audit: <none | needed: reason>
   ```

**Audit flag.** A change calls for a general feature audit when it touches behaviour already implemented (by this plan or an earlier one), changes a contract, data format or interface other parts rely on, or reverses an earlier decision. Then set `Audit: needed — <reason>`; otherwise `Audit: none`. Raise a needed audit with the user; never start it unasked. When it is done, set `Audit: done YYYY-MM-DD`, refresh Updated, and log `## [YYYY-MM-DD] audited | <Plan title>`.

### Close (implementation finished)

Run when the plan's implementation finishes, or when the user abandons or replaces the plan.

1. Set `Plan status:`
   - `Implemented` — every work item shipped.
   - `Partially implemented` — some items did not ship; Outcome lists each with where it went (a backlog item or a follow-up plan).
   - `Dropped` — abandoned; Outcome says why.
   - `Superseded by [<Newer plan>](<file>.md)` — replaced by a newer plan, which gets its own Record.

   Set Closed to today and refresh Updated.
2. Add the Outcome section: what shipped, where it deviated from the plan, and what was deferred and where it went.
3. Update the planning index row and move it from Active to Closed.
4. Append to `wiki/planning/log.md`:
   ```
   ## [YYYY-MM-DD] closed | <Plan title>
   - Status: <Implemented | Partially implemented | Dropped | Superseded>
   - Deferred: <item> → <where it went>
   ```
   Omit `- Deferred:` lines when nothing was deferred.

Closing a plan does not update articles. If the implementation changed what articles describe, that is an Ingest.

### Plan Rules

- Plan pages carry no Raw field. `scripts/check_evidence.py` skips any page whose metadata header has a `Plan status:` line, as it skips archive pages, and it skips `wiki/planning/index.md` and `wiki/planning/log.md`. Facts that matter beyond the plan belong in articles, through Ingest.
- Ingest never cascade-updates a plan page; only Revise and Close change it. Backlogs in `wiki/planning/` are ordinary articles: Ingest maintains them and updates their row in the planning index.
- Never delete a plan page or a planning log entry. The status records how a plan ended.
- Plan operations write `wiki/planning/` and refresh the Updated date of the `planning` row in `wiki/index.md`. They never write `wiki/log.md`.

---

## Lint

Quality checks on the wiki. Three categories with different authority levels.

### Safe Fixes (auto-fix)

Fix these automatically:

**Index consistency** — compare `wiki/index.md` against actual wiki/ files (excluding index.md and log.md, and everything under `wiki/planning/`, which Planning index below covers):
- File exists but missing from index → add entry with `(no summary)` placeholder. For Updated, use the article's metadata Updated date if present (for archive pages, the Archived date); otherwise fall back to file's last modified date.
- Index entry points to nonexistent file → mark as `[MISSING]` in the index. Do not delete the entry; let the user decide.
- Index entry's Updated differs from the article's metadata Updated (or Archived, for archive pages) → update the index entry to match the article.

**Planning index** — compare `wiki/planning/index.md` against the files in `wiki/planning/` (excluding its index.md and log.md) with the three rules above. In addition:
- A plan row's Status, Closed and Audit differ from the plan's header → update the row to match the plan.
- A plan row sits in the wrong section for its status → move it (Approved belongs in Active; every other status in Closed).
- A row in `wiki/index.md` points into `wiki/planning/` other than the planning index row → move it to the planning index.

**Internal links** — for every markdown link in wiki/ article files (body text and Sources metadata), excluding Raw field links (validated by Raw references below), excluding See Also section links (handled by the See Also rule below), and excluding index.md/log.md (handled above):
- Target does not exist → search wiki/ for a file with the same name elsewhere.
  - Exactly one match → fix the path.
  - Zero or multiple matches → report to the user.

**Raw references** — every link in a Raw field must point to an existing raw/ file:
- Target does not exist → search raw/ for a file with the same name elsewhere.
  - Exactly one match → fix the path.
  - Zero or multiple matches → report to the user.

**See Also** — within each topic directory:
- Target of a See Also link does not exist → search wiki/ for a file with the same name elsewhere.
  - Exactly one match → fix the path.
  - Zero matches → remove the link (a dead cross-reference is not load-bearing).
  - Multiple matches → report to the user.

### Mechanical Reports (no fixes)

Run these mechanically with `python3 <skill-dir>/scripts/check_evidence.py <project-root>` (optionally followed by project-root-relative article paths to limit scope). Default scope is the whole wiki; the script is fast. Report findings; never auto-fix facts.

**Source fidelity** — reported suspects are candidates, not verdicts: derived values and product names may appear. Judge each against the raw context and report only real mismatches.

**Evidence errors** — articles the script cannot verify (missing Raw field, unresolvable Raw links, or Raw links escaping `raw/`). These always need a decision, not a fix from the script.

**Unreferenced raw files** — files logged with a No material disposition are excluded; everything else is a genuine backlog reminder.

### Judgment Reports (no fixes)

These rely on your judgment. Report findings without auto-fixing:

- Factual contradictions across articles
- Outdated claims superseded by newer sources but still presented without a Status block
- Missing conflict annotations where sources disagree
- Obviously missing cross-references between related articles (suggest them; do not add silently)
- Malformed Status blocks (Outdated missing its date, or either block missing its explanation; format reference: `references/article-template.md`)
- Orphan pages with no inbound links from other wiki articles
- Missing cross-topic references
- Concepts frequently mentioned but lacking a dedicated page
- Archive pages whose cited source articles have been substantially updated since archival
- Plans still `Approved` whose work appears to have shipped (ask the user whether to Close them)
- Plans flagged `Audit: needed`

### Post-Lint

Append to `wiki/log.md`:

```
## [YYYY-MM-DD] lint | <N> issues found, <M> auto-fixed
```

---

## Conventions

- Standard markdown with relative links throughout.
- wiki/ supports one level of topic subdirectories only. No deeper nesting.
- Today's date for log entries, Collected dates, and Archived dates. Updated dates reflect when the article's knowledge content last changed. Published dates come from the source (use `Unknown` when unavailable).
- Inside wiki/ files, all markdown links use paths relative to the current file. In conversation output, use project-root-relative paths (e.g., `wiki/topic/article.md`).
- Ingest updates both `wiki/index.md` and `wiki/log.md` (a No material ingest updates only the log). Archive (from Query) updates both. Lint updates `wiki/log.md` (and `wiki/index.md` or `wiki/planning/index.md` only when auto-fixing index entries). Plan operations update `wiki/planning/` and the Updated date of the `planning` row in `wiki/index.md`, never `wiki/log.md`. Plain queries do not write any files.

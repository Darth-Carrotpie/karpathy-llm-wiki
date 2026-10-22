# karpathy-llm-wiki

**A reusable skill for building Karpathy-style LLM wikis with Claude Code, Cursor, Codex, and other Agent Skills tools.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Astro-Han/karpathy-llm-wiki?style=social)](https://github.com/Astro-Han/karpathy-llm-wiki)
[![GitHub forks](https://img.shields.io/github/forks/Astro-Han/karpathy-llm-wiki?style=social)](https://github.com/Astro-Han/karpathy-llm-wiki)
[![Agent Skills](https://img.shields.io/badge/Agent_Skills-compatible-blue)](https://agentskills.io)
[![Install](https://img.shields.io/badge/Install-npx_add--skill-green)](https://github.com/Astro-Han/karpathy-llm-wiki#install)

<p align="center">
  <img src="assets/karpathy-tweet.png" alt="Karpathy's tweet about LLM Wiki" width="560">
</p>

`karpathy-llm-wiki` packages [Karpathy's LLM Wiki idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) into one installable [Agent Skills](https://agentskills.io) skill. Your coding agent ingests sources into `raw/`, compiles durable knowledge pages into `wiki/`, answers questions with citations, and lints the wiki for consistency.

## What This Fork Adds: Plan Keeping

This is the `planning` branch of [Darth-Carrotpie/karpathy-llm-wiki](https://github.com/Darth-Carrotpie/karpathy-llm-wiki), a fork of [Astro-Han/karpathy-llm-wiki](https://github.com/Astro-Han/karpathy-llm-wiki). Upstream compiles knowledge but has no structure for the plans a project agrees on: no plan pages, no index for them, and no rules for revising or closing them. This branch adds a fourth operation, **Plan**, which keeps sprint plans in the wiki next to the knowledge they change.

**What the agent does unprompted, in any project that has a wiki:**

| When | Operation | What it writes |
|------|-----------|----------------|
| The user approves a sprint's implementation plan | **Record** | A dated plan page, `wiki/planning/YYYY-MM-DD-slug.md`, holding only the high-level topics (goal, scope, work items, decisions, risks), plus a planning-index row and a planning-log entry |
| An approved plan changes significantly | **Revise** | Asks the user whether to **overwrite** the page or append a **change record** that saves only what changed. Either way it refreshes the dates and sets an **audit flag**: whether the change calls for a general feature audit |
| The plan's implementation finishes | **Close** | Sets the status (Implemented, Partially implemented, Dropped or Superseded), adds an Outcome saying where deferred items went, moves the row to Closed, and logs it |

**A planning branch of the index.** `wiki/planning/index.md` lists every plan (Active and Closed, with status and audit flag) and every standing backlog. The global `wiki/index.md` links only to it, never to individual plans, so every plan lookup starts in one place and plan churn stays out of the global index. `wiki/planning/log.md` records plan operations, apart from the ingest, query and lint log.

**What changed:**

| File | Change |
|------|--------|
| `SKILL.md` | The Plan section: triggers, layout, Record, Revise, Close, and rules. Post-Ingest, Lint and Conventions now know about the planning index |
| `references/plan-template.md` | New: the plan page — status header, Goal, Scope, Work Items, Decisions, Risks, Changes, Outcome |
| `references/planning-index-template.md` | New: the planning index — Active, Closed, Backlogs |
| `references/index-template.md` | The single `planning` row the global index carries |
| `scripts/check_evidence.py` | Plan pages (a `Plan status:` header line) are exempt from the grounding check, like archive pages; the planning index and log are skipped |
| `tests/test_check_evidence.py` | Three tests for those two rules |

**Also in this fork:** Triage gains "Sources that still live in the project". A source that stays in the repository after an ingest is either transferred (compiled, deleted, and every citation repointed in the same task) or left alone as No material, never compiled and kept, because two copies of the same knowledge diverge.

Install this fork as a git clone of the branch ([Install](#install)), so the skill stays a repository you can pull, change and push independently of the projects that use it.

**Concurrent logs.** `wiki/log.md` and `wiki/planning/log.md` remain complete and
directly readable. Append with `scripts/wiki_log.py PROJECT_ROOT` (UTF-8 stdin or
`--entry-file FILE`; `--planning` selects the planning log). The helper locks local
writes and adds hidden entry IDs. Register its whole-entry Git merge driver with
`--install-merge-driver` in each clone and select it in `.gitattributes`; without
registration, ordinary Git conflicts remain. See Concurrent operation logs in
`SKILL.md`. Shared articles and indexes still need coordination.

## What Is an LLM Wiki?

An **LLM wiki** is a knowledge system where the LLM maintains structured wiki pages instead of re-searching raw documents on every question. New sources are compiled into durable markdown pages, cross-references are updated over time, and answers cite the wiki pages that already contain the synthesized knowledge.

This skill gives you four operations:

| Operation | What it does | Output |
|-----------|--------------|--------|
| **Ingest** | Collects a source into `raw/`, triages it, then creates or updates wiki articles — or just logs it when nothing is new | New or updated wiki pages |
| **Query** | Searches the wiki and answers with citations | Grounded answers linking to markdown pages |
| **Plan** | Records an approved plan's high-level topics, its revisions (overwrite or change record, with an audit flag) and its outcome, under `wiki/planning/` with its own index and log | Dated plan pages with a status |
| **Lint** | Checks index integrity, links, and wiki health | Auto-fixes plus reported issues |

See [SKILL.md](SKILL.md) for the full skill specification.

## LLM Wiki vs RAG

| Approach | Knowledge lives in | When synthesis happens | Good for |
|----------|--------------------|------------------------|----------|
| **RAG** | Raw chunks and embeddings | At query time | Broad retrieval across large corpora |
| **LLM Wiki** | Curated markdown pages | During ingest and maintenance | Compounding knowledge, summaries, and durable cross-links |

This skill is optimized for the wiki model: knowledge that improves over time instead of re-deriving relationships on every query.

## Usage Stats

Based on a production knowledge base maintained daily since April 2026:

- **94** wiki articles across **13** topic directories
- **99** source materials ingested
- **87** operation log entries in the last 7 days

See [examples/](examples/) for sample wiki pages, source files, and operation logs.

## Install

Install this fork as a git clone of its `planning` branch, so the skill stays a repository you can update and maintain:

```bash
git clone -b planning https://github.com/Darth-Carrotpie/karpathy-llm-wiki.git ~/.claude/skills/karpathy-llm-wiki
```

Claude Code and GitHub Copilot in VS Code read `~/.claude/skills/`. Codex reads `~/.agents/skills/`, so link the same clone there rather than copying it:

```bash
ln -s ~/.claude/skills/karpathy-llm-wiki ~/.agents/skills/karpathy-llm-wiki    # macOS / Linux
mklink /J "%USERPROFILE%\.agents\skills\karpathy-llm-wiki" "%USERPROFILE%\.claude\skills\karpathy-llm-wiki"    # Windows cmd
```

Keep one clone. A second copy committed into a project's `.claude/skills/`, `.agents/skills/` or `.github/skills/` goes stale. Codex lists same-named skills side by side instead of merging them, so the stale copy can be the one an agent picks.

Update with `git -C ~/.claude/skills/karpathy-llm-wiki pull`. To take upstream changes, add the original as a remote, then merge:

```bash
git remote add upstream https://github.com/Astro-Han/karpathy-llm-wiki.git
git fetch upstream && git merge upstream/main
```

Upstream without the Plan operation installs with `npx add-skill Astro-Han/karpathy-llm-wiki`.

Works with any tool that supports the [Agent Skills](https://agentskills.io) standard.

## Quick Start

### 1. Ingest your first source

Give the skill a URL, a file, or pasted text:

> "Ingest this article: https://example.com/attention-is-all-you-need"

The skill stores the source in `raw/`, then compiles or updates the right knowledge pages in `wiki/`.

### 2. Ask your wiki a question

> "What do I know about attention mechanisms?"

The skill searches the wiki and answers with citations linking back to your markdown pages.

### 3. Keep the wiki healthy

> "Lint my wiki"

Checks for broken links, missing index entries, stale cross-references, and related issues.

### 4. Keep your plans

Approve a sprint plan in a project that has a wiki. The agent records it under `wiki/planning/` without being asked. A significant change makes it ask whether to overwrite the plan or add a change record. Finishing the implementation closes the plan and logs the outcome.

## How the Workflow Works

The core idea from Karpathy: the LLM maintains the wiki while the human focuses on choosing sources and asking good questions.

```text
your-project/
├── raw/            ← Immutable source material
│   └── topic/
│       └── 2026-04-03-source-article.md
├── wiki/           ← Compiled knowledge pages maintained by the LLM
│   ├── topic/
│   │   └── concept-name.md
│   ├── planning/   ← Plan pages, plus the planning index.md and log.md
│   ├── index.md    ← Global table of contents
│   └── log.md      ← Append-only operation log
```

Each new source can update multiple pages, strengthen cross-references, and record contradictions. That is what makes the wiki compound over time.

## Tool Compatibility

This skill follows the [agentskills.io](https://agentskills.io) open standard. The install methods below fetch upstream; for this fork, use the git clone in [Install](#install).

| Tool | Install method |
|------|----------------|
| Claude Code | `npx add-skill Astro-Han/karpathy-llm-wiki` |
| Cursor | `npx add-skill Astro-Han/karpathy-llm-wiki` |
| Codex CLI | Copy to `.agents/skills/karpathy-llm-wiki/` |
| OpenCode | `npx add-skill Astro-Han/karpathy-llm-wiki` |
| Other tools | Copy `SKILL.md`, `references/`, and `scripts/` into the tool's skill directory |

## FAQ

### What is the difference between an LLM wiki and a personal wiki?

An LLM wiki is maintained by the model. It updates summaries, cross-links, index entries, and contradictions as new material arrives. A normal personal wiki depends on manual editing.

### What sources can I ingest?

Web pages, papers, blog posts, PDFs, markdown files, text files, and pasted text. The skill converts everything into markdown under `raw/` and compiles it into `wiki/`.

### Is this production-ready?

The workflow is based on a real knowledge base with 94 articles and 99 sources maintained daily since April 2026. The repo includes examples, templates, and a design spec.

## Design Boundaries

Deliberately not built, after three months of production logs and a survey of the ecosystem (LLM Wiki v2, llm-wiki-compiler, OKF, agent-memory literature):

- **Source-hash freshness tracking** — raw/ is immutable, so hashes guard against events that cannot happen. Genuinely new information arrives as new sources through normal ingest.
- **Persisted line-number citations** — every observed fidelity error was "value absent from the source", which a whole-file grep catches. Anchors only disambiguate a failure mode that has not occurred, and the annotation friction makes agents skip the rule.
- **Numeric confidence or quality scores** — false precision with no calibration behind it. Evidence strength belongs in the prose.
- **Per-article review dates** — nobody can predict at compile time how fast a domain moves. Maintenance is driven by whole-wiki lint, not per-page timers.
- **Access-based decay** — frequently asked is not the same as true.
- **Retract / bad-source machinery** — has not happened yet. Handle it manually until it does.
- **Automatic hooks and scheduled runs** — those belong to the agent harness, not a tool-agnostic skill.
- **Vector or graph search** — at 50K–100K tokens of curated wiki, grep and read are more reliable. Add search tooling only when recall measurably degrades.
- **Typed relationship ontologies** — link semantics live in the prose around the link.
- **OKF conformance** — the spec is a v0.1 draft with a minimal tooling ecosystem. Tracked; will be revisited.
- **MCP servers, UIs, output subsystems** — outside the boundary of a tool-agnostic skill.

## Inspired By

Unofficial community implementation of the workflow from [Karpathy's LLM Wiki idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). The value here is the reusable workflow, prompt structure, and battle-tested knowledge-compilation rules.

See also: [lucasastorian/llmwiki](https://github.com/lucasastorian/llmwiki), [atomicmemory/llm-wiki-compiler](https://github.com/atomicmemory/llm-wiki-compiler). We are tracking Google's [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf) draft and will evaluate compatibility once the spec and tooling mature.

## License

[MIT](LICENSE)

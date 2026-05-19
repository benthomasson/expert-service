# Knowledge Forge Roadmap — Expert-Service Absorbs the EEM Lifecycle

**Date:** 2026-05-19
**Time:** 19:12

## Summary

Filed six feature requests (#24-29) on expert-service that collectively move the EEM build/review lifecycle from agents-python into expert-service itself. This is the architectural shift from expert-service as a read-only serving layer to expert-service as a knowledge forge — managing the full lifecycle of beliefs the same way GitHub manages the lifecycle of code.

## The Current Architecture

```
agents-python (build) → reasons.db → expert-service (serve) → clients (query)
     owns lifecycle          artifact        read-only API        expert CLI / MCP / analyze-webapp
```

agents-python owns the full build lifecycle: fetch sources, summarize, propose beliefs, review, derive. It produces reasons.db as a compiled artifact. expert-service imports the artifact and answers queries. There is no feedback loop from expert-service back to the build process, no versioning, no review trail, and no way to roll back a bad derive round.

## The Forge Architecture

```
agents-python → changesets → expert-service (build + review + serve) → clients
   proposer        PR           owns lifecycle + versioning              query + propose
```

expert-service absorbs the lifecycle. agents-python becomes one source of proposals — alongside manual edits, imports, and auto-proposals from source changes. The review/merge/release steps happen in expert-service, not in the build pipeline.

## The Six Issues

| # | Issue | Role | Depends on |
|---|-------|------|-----------|
| 24 | Belief changesets | Group proposals into reviewable units (the PR) | — |
| 25 | Changeset review workflow | Comments, attribution, approval (the code review) | #24 |
| 26 | EEM versioning | Snapshots, tags, rollback (git tags) | #24 |
| 27 | Belief diff API | Compare network states (git diff) | #26 |
| 28 | Release and deployment | Version pinning, artifacts, release notes (releases) | #26, #24 |
| 29 | Continuous knowledge integration | Auto-propose on source changes (CI/CD) | #24, #6 |

#24 (changesets) is the foundation — everything else depends on it.

## What Changes for Each Component

### agents-python: owner → contributor

Currently agents-python writes directly to reasons.db. With the forge, `derive` and `propose-beliefs` create changesets that go through review. agents-python becomes one contributor among many, not the owner of the EEM.

### analyze-webapp: live queries → version-pinned queries

Currently the webapp queries whatever's live in the belief network. With releases (#28) and version pinning, it can pin to a specific release (e.g. `v2.6.1`) while new beliefs are being reviewed on HEAD. A bad derive round doesn't break production queries.

### expert-build: pipeline → CI trigger

Currently expert-build runs the full pipeline end-to-end. With the forge, it becomes a CI job: detect source changes → run derive → open a changeset → wait for review. The review/merge/release steps happen in expert-service, not in the build script.

### expert MCP server: read-only → read-write

Currently the MCP server exposes read-only tools (search, explain, what-if). With changesets, an MCP client (Claude Code, etc.) could propose corrections: "this belief is wrong, here's why" → creates a changeset with a retraction and replacement. The user's LLM becomes a contributor to the knowledge base, not just a consumer.

### meta-expert: import HEAD → import releases

Currently meta-expert imports the latest beliefs from each expert repo. With releases, it imports from a tagged release rather than HEAD — so a bad derive round in one expert doesn't cascade into the cross-domain aggregation.

## The Software Analogy Is Structural, Not Metaphorical

| Software | EEM (forge) |
|----------|-------------|
| Source code | Source documents |
| Feature branch | Changeset (#24) |
| Pull request | Changeset review (#25) |
| Code review comments | Belief comments (#25) |
| git diff | Belief diff API (#27) |
| git tag / release | EEM versioning (#26) / release (#28) |
| CI pipeline | Continuous integration (#29) |
| Deployment artifact | reasons.db or versioned API endpoint |
| Rollback | Snapshot restore (#26) |

The operations are the same. You start with source material, build a base, then propose changes to that base which get reviewed and accepted or rejected. The derive/review cycle is a pull request. A nogood is a bug report. Retraction cascades are the equivalent of fixing a bug and watching dependent code break.

## Prerequisites

PR #23 (public projects + Alembic) laid the groundwork. Alembic provides versioned schema migrations — required because the forge adds new tables (changeset, changeset_beliefs, changeset_review, belief_comment, network_snapshot, release). Without Alembic, each new table would require manual ALTER TABLE on production.

## Why Now: Query Is Solved, Build Is Next

The project deliberately sequenced query before build. The query problem — how do agents and users access the knowledge in an EEM? — is now solved across multiple surfaces:

- **expert-service** dual-path search (TMS beliefs + FTS source chunks)
- **Data-only mode** for zero-cost serving, with client-side LLM synthesis
- **expert CLI** with anonymous access and LLM fallback
- **MCP server** for tool-using LLM clients (Claude Code, etc.)
- **analyze-webapp** integration via ExpertServiceClient
- **Evals confirming** EEM is cheaper (0.53x), faster (0.47x), and more accurate than from-scratch search

With query solved, the deferred problem is build and update: how does an EEM get constructed, maintained, and kept current as source material changes? Today that process is manual — run agents-python, review beliefs interactively, export reasons.db, import into expert-service. There is no automation, no change detection, and no review trail.

The forge issues (#24-29) solve this. The critical capability is #29 (continuous knowledge integration): agents watch for source changes and automatically propose new beliefs when sources change or become stale. Combined with changesets (#24) and review (#25), this creates a closed loop — sources change, agents propose, humans review, the EEM updates, and deployed clients see the new knowledge at the next release. No manual pipeline runs, no manual imports.

This is the difference between a static artifact and a living knowledge base. The query side treats the EEM as a compiled binary — build once, serve forever. The forge side treats it as a codebase — continuously updated, reviewed, versioned, and released.

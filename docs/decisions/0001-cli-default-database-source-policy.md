---
type: ADR
title: "ADR 0001: CLI Default Database Source Policy"
status: Accepted
timestamp: 2026-06-02
deciders: NEXTAltair
tags: [cli, config, db-read]
depends_on: [sqlite, huggingface-hub]
---

# ADR 0001: CLI Default Database Source Policy

## Context

`tag-db ensure-dbs` is the command users and automation should run when preparing the base tag
databases. The project already has three default base database sources:

- CC0 database
- MIT database
- CC4 database

However, the CLI currently requires at least one `--source` value for `ensure-dbs`. This makes the
default setup path harder than necessary: users must know the source identifiers before they can
prepare the standard database set.

Issue #27 tracks making `ensure-dbs` usable without explicit source arguments. Issue #24 remains
focused on the separate `--base-db` parser bug.

## Decision

`tag-db ensure-dbs` with no `--source` arguments will download or reuse all default base databases:
CC0, MIT, and CC4.

When one or more `--source` arguments are provided, the command will use only the explicitly
specified sources.

The CLI contract is:

- `tag-db ensure-dbs`: prepare the standard default source set.
- `tag-db ensure-dbs --source repo/file.sqlite`: prepare only the specified source.
- `tag-db ensure-dbs --source repo/a.sqlite --source repo/b.sqlite`: prepare only the specified
  sources.

## Rationale

Defaulting to all standard sources gives first-time users and automation a simple setup command.
This matches the existing runtime behavior where omitted base DB paths can fall back to default
database initialization.

Keeping explicit `--source` values exclusive avoids surprising users who ask for a specific
database. If explicit sources were added on top of defaults, users could unintentionally download
or use more databases than requested.

The alternative of keeping `--source` required preserves the current parser behavior but leaves the
most common setup path unnecessarily verbose and pushes internal source knowledge onto users.

## Consequences

- `tag-db ensure-dbs` becomes a useful zero-argument setup command.
- Explicit `--source` remains available for targeted downloads, testing, and custom datasets.
- Help text and tests must describe the default-vs-explicit behavior.
- The implementation should share the default source list with the core initialization path rather
  than duplicating source definitions in the CLI.

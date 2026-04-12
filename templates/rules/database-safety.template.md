---
description: Database access rules — read-only project DBs, GRDB only, no raw sqlite3
paths:
  - "**/*.db"
  - "**/DatabaseReader.swift"
  - "**/db_queries.sh"
---

# Database Safety Rules — %%PROJECT_NAME%%

## Ownership Model
- **%%PROJECT_DB%%**: Our database. Read-write via db_queries.sh (bash scripts).
- **Project-owned databases**: Written by project scripts, read by the app. Treat as internal.
- **Registered external DBs** (e.g., tasks.db in other projects): READ-ONLY. Never write.

## Access Patterns
- Swift code reads via GRDB.swift only — never raw sqlite3 C API in Swift
- Shell scripts use sqlite3 CLI for %%PROJECT_DB%% operations
- `permissions.deny` blocks Write/Edit to *.db files at the tool level
- `protect-databases.sh` hook intercepts sqlite3 write commands to external DBs

## DatabaseReader.swift
- All reads are `async` — they run on a background queue, never block @MainActor
- Must handle missing/corrupt databases gracefully (return empty results, not crashes)
- Schema mismatches: catch GRDB errors, log, return empty — don't crash the app

## Migrations
- Adding columns to project-owned databases: put ALTER TABLE in the owning script with IF NOT EXISTS guard
- After adding migration code, run it immediately against the live DB — don't assume it'll run later
- Never add migrations to %%PROJECT_DB%% from Swift — all schema changes go through db_queries.sh

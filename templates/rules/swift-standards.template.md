---
description: Swift coding standards for %%PROJECT_NAME%%
paths:
  - "**/*.swift"
---

# Swift Standards — %%PROJECT_NAME%%

## Concurrency
- `@MainActor` on all UI-bound state, view models, and ProjectManager
- `async/await` for all database reads — never block the main thread
- Timer-based polling only. No FSEvents. No GRDB DatabaseObservation.

## Types & Safety
- `struct` for data models (Codable for UserDefaults persistence)
- `final class` for ProjectManager (singleton, @MainActor)
- Error types: enums conforming to `LocalizedError`
- No force-unwraps (`!`) — use `guard let` or provide defaults
- No `try!` or `as!` — handle failures explicitly

## Database Access
- All SQLite access via GRDB.swift only — never raw sqlite3 C API
- Zero writes to registered project databases — read-only
- Project databases: read-write via db_queries.sh / project scripts

## SwiftUI Specifics
- Use `Color.accentColor` (not `.accentColor`) inside `.foregroundStyle()` calls
- PascalCase filenames, no type suffix for views (e.g., `TaskBoardView.swift`)

## Project Registration
- After creating any new .swift file, verify it appears in project.pbxproj
- Required sections: PBXBuildFile, PBXFileReference, PBXGroup, PBXSourcesBuildPhase
- The check-pbxproj.sh hook warns on missing registrations, but fix them immediately

## Static Analysis
- SAST: `%%SAST_CONFIG%%`
- Secrets: `gitleaks protect --staged`
- Custom rules: `.semgrep/` directory (project-specific patterns)

---
description: Rust coding standards for %%PROJECT_NAME%%
paths:
  - "**/*.rs"
---

# Rust Standards — %%PROJECT_NAME%%

## Safety
- `#![deny(unsafe_code)]` at crate root unless unsafe is explicitly justified
- All `unsafe` blocks require a `// SAFETY:` comment explaining the invariant
- Prefer `thiserror` for error types, `anyhow` for application error handling

## Types & Ownership
- Prefer borrowing (`&T`) over cloning — clone only when ownership transfer is needed
- Use `Cow<'_, T>` when you need conditional ownership
- Enums over booleans for state — `enum Status { Active, Inactive }` not `is_active: bool`

## Error Handling
- Use `Result<T, E>` — never `unwrap()` or `expect()` in library code
- Application binaries may use `expect()` with descriptive messages
- `?` operator for error propagation — no manual match-and-return

## Concurrency
- Prefer `tokio` for async runtime (if async is needed)
- Use `Arc<Mutex<T>>` sparingly — prefer message passing (`mpsc`, `crossbeam`)
- Never hold a lock across an `.await` point

## Formatting & Linting
- `cargo fmt` — no manual formatting
- `cargo clippy -- -D warnings` — all warnings are errors
- `cargo test` must pass before commit

## Dependencies
- Audit new crates: check maintenance status, download counts, and `cargo audit`
- Prefer Rust ecosystem standards (serde, tokio, tracing) over niche alternatives

## Static Analysis
- SAST: `%%SAST_CONFIG%%`
- Secrets: `gitleaks protect --staged`
- Custom rules: `.semgrep/` directory (project-specific patterns)

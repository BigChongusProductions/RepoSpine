---
description: Go coding standards for %%PROJECT_NAME%%
paths:
  - "**/*.go"
---

# Go Standards — %%PROJECT_NAME%%

## Error Handling
- Always check returned errors — `err != nil` blocks are not optional
- Use `fmt.Errorf("context: %w", err)` for error wrapping
- Define sentinel errors with `errors.New()` for known failure modes
- Never use `panic()` for recoverable errors — panic is for programmer bugs only

## Types & Interfaces
- Accept interfaces, return structs — keeps APIs flexible
- Small interfaces: 1-3 methods. Larger interfaces are a design smell.
- Use `context.Context` as the first parameter in functions that do I/O

## Concurrency
- Use goroutines + channels for concurrent work
- Always pass `context.Context` to long-running goroutines
- Use `sync.WaitGroup` or `errgroup.Group` to manage goroutine lifecycles
- Never start a goroutine without a clear shutdown path

## Formatting & Linting
- `gofmt` — non-negotiable, format on save
- `go vet` — catches common mistakes
- `golangci-lint` with project config — comprehensive linting

## Testing
- Table-driven tests as the default pattern
- Use `testify/assert` or stdlib — be consistent within the project
- `go test -race` in CI — catches data races

## Modules
- One `go.mod` per repository (unless monorepo with clear boundaries)
- Run `go mod tidy` after dependency changes
- Vendor dependencies for reproducible builds: `go mod vendor`

## Static Analysis
- SAST: `%%SAST_CONFIG%%`
- Secrets: `gitleaks protect --staged`
- Custom rules: `.semgrep/` directory (project-specific patterns)

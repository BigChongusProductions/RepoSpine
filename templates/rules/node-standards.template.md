---
description: Node.js/TypeScript coding standards for %%PROJECT_NAME%%
paths:
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.jsx"
---

# Node.js/TypeScript Standards — %%PROJECT_NAME%%

## Type Safety
- TypeScript strict mode enabled — no `any` types without explicit justification
- Use explicit return types on exported functions
- Prefer `interface` for object shapes, `type` for unions/intersections
- No `@ts-ignore` — use `@ts-expect-error` with explanation if needed

## Async/Promises
- Use `async/await` over raw Promises — easier to debug, clearer control flow
- Always handle rejections — no unhandled promise rejections
- Use `Promise.all()` for independent async operations, not sequential awaits

## Error Handling
- Use typed errors (custom Error classes) — not bare string throws
- API boundaries: validate inputs with zod/joi/similar — never trust external data
- Wrap third-party calls in try/catch at the integration boundary

## Dependencies
- Pin exact versions in package.json (no ^ or ~) for production apps
- Run `npm audit` / `pnpm audit` after adding dependencies
- Prefer built-in Node.js APIs over npm packages when equivalent

## Testing
- Tests live next to source files or in `__tests__/` directories
- Use `describe/it` blocks — test one behavior per `it`
- Mock external services at the boundary, not internal modules

## Formatting
- ESLint + Prettier enforced — no manual formatting
- Import order: built-in → external → internal (enforced by ESLint rule)

## Static Analysis
- SAST: `%%SAST_CONFIG%%`
- Secrets: `gitleaks protect --staged`
- Custom rules: `.semgrep/` directory (project-specific patterns)

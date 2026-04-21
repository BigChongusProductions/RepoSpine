---
name: react-components
author: Google Labs
version: 1.0.0
description: Convert Stitch screens to typed React component systems with AST validation
---

# React Components (Stitch Integration)

Convert Google Stitch screen designs into modular, typed React component systems.

## When to Use
- After selecting a Stitch design variant (ST-* tasks)
- During the CONVERT step of the Stitch-first design workflow
- When user says: "convert stitch", "decompose this design", "create components from stitch"

## Prerequisites
- Stitch MCP server must be running (tools: `get_screen_code`, `get_screen_image`)
- A Stitch project ID and screen name

## Workflow

1. **Discover Stitch tools** — verify `get_screen_code` and `get_screen_image` are available

2. **Retrieve design** from Stitch:
   - `get_screen_code(projectId, screenName)` → raw HTML/React output
   - `get_screen_image(projectId, screenName)` → base64 screenshot for visual reference

3. **Decompose into components:**
   - Break monolithic Stitch output into modular React components
   - Each component gets its own file in `src/components/`
   - Extract shared styles into Tailwind theme tokens

4. **Type everything:**
   - Create `Readonly<Props>` interfaces for each component
   - No `any` types — TypeScript strict mode
   - Export named components (no default exports)

5. **Isolate logic:**
   - Extract business logic into custom hooks (`src/hooks/`)
   - Create mock data layer for development (`src/data/`)
   - Separate presentational from stateful components

6. **Validate:**
   - Run `npm run validate` for AST-based quality checks
   - Verify no TypeScript errors
   - Check component renders without hydration errors

## Project-Specific Adaptations

> **Customize this section per project.** Stitch outputs are a starting point, not a final deliverable. After conversion, your ADAPT step may need to:
>
> - Add `'use client'` directive where needed (Next.js App Router)
> - Add SSR guards (`typeof window !== 'undefined'`)
> - Replace hardcoded colors → your theme token system
> - Replace fonts → project CSS variables
> - Add motion library animations (framer-motion, motion.dev, etc.)
> - Wire state store hooks (Zustand, Redux, Jotai, etc.)
> - Add aria-* attributes and ≥44px touch targets
> - Move files to your project's component conventions

## Output Structure
```
src/components/<ComponentName>.tsx    — presentational component
src/hooks/use<ComponentName>.ts       — extracted logic hook
src/data/<component-name>-mock.ts     — development mock data
```

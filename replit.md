# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Each package manages its own dependencies.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)

## Key Commands

- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `pnpm --filter @workspace/api-server run dev` — run API server locally

See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details.

## Python Blackjack Desktop App

A standalone Python project lives in `blackjack/` (independent of the pnpm
workspace). It is a multi-client, encrypted, GUI-based Blackjack game.

- Stack: Python 3.11, Tkinter, raw sockets, threads, `cryptography` (RSA + Fernet).
- Run server: `python -m blackjack.run_server`
- Run client: `python -m blackjack.run_client` (one per player)
- Profiles + RSA key are stored in `blackjack/data/` (auto-created, gitignored).
- See `blackjack/README.md` for full details.

# PCR-0007: Frontend tests run on Vitest with jsdom and React Testing Library

**Decision:** Frontend tests MUST run on Vitest in a jsdom environment, render components with React Testing Library, and live in `frontend/tests/unit/` with one `*.test.ts(x)` file per module in `components/` or `lib/`, mirroring its path.

**Reason:** Jest was weighed and lost: it needs extra transform setup for TypeScript and ESM, and runs slower. `bun test` was weighed and lost: its DOM support for React components is thinner and has fewer examples, which matters when agents write most tests. Vitest needs no transform setup and is what agents write correctly by default.

**Consequence:** `bun run test` runs the whole frontend suite, and CI runs it as the required `frontend / test` check. A second test runner, a test file outside `frontend/tests/unit/`, or a component test that queries by CSS class instead of by role, label or text is a breach. Browser-driven end-to-end tests are not covered here and need their own record.

**Date:** 2026-10-06

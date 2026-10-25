# PCR-0008: Frontend tests fake the backend with MSW

**Decision:** Frontend tests MUST fake backend responses with MSW handlers and MUST NOT reach a real server or replace `fetch` by hand.

**Reason:** Hand-rolled `fetch` mocks in each test file were weighed and lost: every file re-invents the fake backend and the copies drift apart. MSW intercepts at the network layer, so one shared set of handlers covers every test, including streamed responses.

**Consequence:** Default handlers live in `frontend/tests/mocks/handlers.ts`, and a test overrides one with `server.use(...)`. The test setup fails any request that has no handler, so a new endpoint needs a handler before its test can pass. `vi.spyOn(global, 'fetch')` or assigning `global.fetch` in a test is a breach.

**Date:** 2026-10-06

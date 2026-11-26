# ADR-0019: The claim check's settings are options, not environment variables

**Decision:** A setting of how the claim check judges (the question to Jev, the support threshold, skipping hedges, how a claim is cut) MUST be a field of `CheckOptions` passed to `check_claims`, with the live check as its default; it MUST NOT be read from an environment variable.

**Reason:** The project sets most behaviour through `.env` (`CLAIM_CHECK_TIMEOUT_S` included), and that was the option weighed. But the tune run measures several settings in one process, side by side and in parallel, which a process-wide variable cannot do without races; and a setting changed in one machine's `.env` would make the chat's check differ from the one the reference measured, unseen. Options in code make the live check one reviewed default.

**Consequence:** Making a measured change live is a code change to the `CheckOptions` defaults, reviewed in a diff. A new knob of the check is a new field, measured by `claim_referee tune` before its default changes. The timeout stays an environment variable: it bounds the call, it does not change a verdict.

**Scope:** `backend/src/agentic/claim_check.py` (`CheckOptions`, `check_claims`)

**Date:** 2026-11-24

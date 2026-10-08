# Step 29b: authenticated accounting application and UI

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 29a.

**Goal:** Make login, entity membership and role checks mandatory for all protected
localhost reads and actions, with exact authenticated actors in new audit records.

**Architecture:** One authenticated facade wraps the existing workspace services.
Explicit route-to-operation mapping lives at the application boundary, and every
HTTP accounting route calls it. Existing deterministic accounting/review policies
remain unchanged. Reuse the current workbench and server-owned entity mapping.

**Tech stack:** Existing Python HTTP server, SQLite authentication and native UI.
**Spec:** [Step 29](STEP_29_PLAN.md) and [identity core](STEP_29A_PLAN.md).

## Boundary and browser contract

Inventory every public Workspace read/action and every GET/POST route at the
start. Map each to the exact role operation; a missing mapping is a denial and a
coverage failure. Protect direct facade calls as well as HTTP. Do not retain an
unauthenticated fallback triggered by a missing cookie or a `local-operator`
string. Internal fixture/demonstration helpers are explicitly trusted local code.

Pass the resolved user ID through evidence registration, proposal preparation,
review/rejection, approval/posting, account activation, bank actions, scenarios,
close and export authorization. Agent runs retain a distinct runtime actor plus
an authenticated initiator reference; a model cannot turn an initiator's reviewer
role into an allowed approval tool. Bind scope when resuming/canceling runs.

Preserve historical stored payloads and approval/report digests exactly. New role
checks precede historical retry retrieval. Read requests also authorize before
opening another entity's registry, ledger or run log, including automatic schema
initialization or startup enrollment. Unknown/unauthorized entity IDs reveal no
financial state. Browser entity changes clear old state, pending confirmations
and source caches before loading the selected entity.

Serve static login assets without exposing accounting state. Login POST keeps
strict Host/Origin and JSON limits, uses an ephemeral pre-login CSRF challenge,
and returns a new host-only HttpOnly, SameSite=Strict, Path=/ session cookie.
Authenticate cookies only; reject duplicate/ambiguous session cookies. Do not
accept session credentials in URLs or localStorage. Logout revokes and clears the
cookie. Use a distinct session-bound CSRF token for every mutation; stale or
cross-session tokens fail, including after login/logout/entity changes.

Because this delivery binds only local HTTP, document the loopback transport
limitation and do not use an HTTPS cookie prefix that this transport cannot
satisfy. Remote/TLS hosting remains unavailable. Keep existing CSP, no-store,
Origin/Host/length limits and no-body logging. Cookie protections follow the
[OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
checked on 2026-10-08; this is not a claim that loopback HTTP supplies TLS.

The UI shows the signed-in identity, selected entity and role, with a clear logout
control. Render only authorized action controls but also enforce all checks on the
server. On expiry/revocation, clear sensitive displayed state and require login.
No built-in password or silent owner login. Provide exact local setup commands
and a login-first startup flow, preserving the current workspace path.

## Task 1: deny-by-default workspace integration

**Files:** Authenticated facade, workspace actor plumbing, HTTP/CLI/static and
focused service/HTTP tests. Root owns setup documentation, CI and browser checks.

- [ ] RED: unauthenticated state/source/report requests deny; preparer direct HTTP
  approval and direct facade approval deny without a new journal/event; forged
  role/actor/entity fields cannot alter that result.
- [ ] Inventory and wire every existing read/mutation to fixed permissions.
  Test that an intentionally unmapped operation fails closed. Reuse accounting
  tests unchanged where they exercise trusted primitives; migrate HTTP fixtures
  to real synthetic sessions instead of disabling authentication in test mode.
- [ ] Test two real synthetic entities and two identities: each may access only
  its grants; preparer prepares, reviewer approves exact revision; cross-entity
  source/draft/journal/report/run IDs fail without leakage or initialization.
- [ ] Assert all new human audit actors equal authenticated IDs, agent tools
  still lack approval/posting, and historical records/digests remain byte-identical.
- [ ] Exercise revoked/expired sessions, permission changes, stale approval,
  concurrent revocation, replayed cookies/CSRF, duplicate cookies and logout.
- [ ] Add login/logout/entity UI and `demo-authenticated-workspace`; perform real
  browser preparer denial then reviewer approval and restart-preserved identity.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff; independently
  review all route coverage, commit/push/exact CI before the offline read adapter.

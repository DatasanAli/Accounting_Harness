# Step 29: authenticated localhost access

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 28, delivering 29a and 29b separately.

**Goal:** Require a real local login and enforce preparer/reviewer permissions and
entity membership before the workspace reads evidence or changes accounting state.

**Architecture:** A small standard-library identity store owns passwords, sessions
and entity grants. An authenticated application facade resolves those grants for
every operation and supplies the audit actor to existing workspace services. The
HTTP layer exposes that facade; accounting storage remains an internal trusted
library, not an alternative network authorization path.

**Tech stack:** Python, SQLite, hashlib, secrets and the existing loopback UI.
**Spec:** [Phase 09](README.md).

## Global constraints

- No live identity provider, API connection or remote hosting. Bind only loopback.
  Local HTTP authentication is scoped to this synthetic workstation application;
  it does not establish an internet deployment or protect against its OS owner.
- Preserve every existing journal, source, approval, run checkpoint and report.
  Do not change historical `local-operator` actors into new users. New human
  actions use the authenticated stable user ID, supplied only by application code.
- Missing/expired/revoked session, missing entity membership, unknown operation or
  unknown role fails closed before opening the requested accounting workspace.
  Request-supplied actor, role, principal, filesystem path or permissions never
  grants authority. Agent tools cannot acquire a human reviewer capability.
- Source text and model output remain data. Authenticated human approval still
  binds the exact current draft, evidence and policy; login cannot weaken it.
- No passwords, session tokens, authentication databases or personal data in GitHub.
  Only synthetic credentials constructed in temporary tests are permissible.

## Bounded role policy

Use three fixed human roles per entity, with an explicit operation allowlist:

| Role | Allowed operations |
| --- | --- |
| preparer | Read evidence, drafts, reports and audit; register supported evidence; prepare/revise proposals; import local bank CSV; classify/match/withdraw timing; create management scenarios/time/allocations; start/cancel bounded agent runs |
| reviewer | Read the same entity; reject proposals; approve/post the exact supported proposal; confirm reconciliation; confirm close; authorize a later explicitly scoped export |
| owner | Union of preparer and reviewer; activate fixed accounts and manage local grants through the explicit administration surface |

The owner role supports a single-person local demo; preparer and reviewer roles
are distinct when assigned separately. Do not claim that this is mandatory
independent segregation of duties. A preparer cannot promote themselves, approve,
complete reconciliation or close through a direct API. A reviewer cannot silently
edit evidence or a draft while approving it. All newly introduced operations need
an explicit role mapping; default access is denied.

Create users and initial entity grants through a local interactive CLI using
`getpass`, never a password command-line argument or a committed default. The
operator who controls the files remains the bootstrap administrator. A subsequent
authenticated owner can use a narrowly scoped grant/revoke operation if needed;
no unauthenticated browser bootstrap or public registration.

Entity selection uses server-owned registered IDs mapped to already provisioned
workspace paths and immutable entity contexts. Never form a path from an HTTP
entity string. Preserve the current workspace location; provisioning a second
synthetic entity must create its own catalog/evidence/context, not rename the first
ledger. Keep authentication storage outside individual financial report captures.

## Delivery split

1. [29a identity/session/policy core](STEP_29A_PLAN.md): credentials, sessions,
   explicit grants, administrative CLI and an authorization facade exercised with
   two synthetic entities and identities. It does not claim HTTP is protected yet.
2. [29b authenticated application and browser](STEP_29B_PLAN.md): wire every live
   workspace entry point, propagate actors, add login/logout/entity selection and
   prove both direct-service and HTTP denial before protected work.

Tests and demos may invoke trusted accounting primitives directly to construct
synthetic fixtures. That does not make those primitives authenticated public APIs.
The documentation must clearly identify the authenticated facade and show no
application entry point that obtains an owner principal merely from a string.

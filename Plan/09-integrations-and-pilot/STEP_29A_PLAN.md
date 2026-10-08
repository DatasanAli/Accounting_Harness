# Step 29a: local identities, sessions and entity grants

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 28.

**Goal:** Persist local human identities and deny unauthorized entity operations
using an explicit, testable application authorization boundary.

**Architecture:** One focused identity/session module and SQLite store; fixed role
policy from [Step 29](STEP_29_PLAN.md). No JWT framework, OAuth server or external
identity dependency. Authentication records are operational state, separate from
immutable financial evidence.

**Tech stack:** Python standard library and SQLite.
**Spec:** [Step 29](STEP_29_PLAN.md), all global constraints apply.

## Credential/session contract

Use `hashlib.scrypt` with a random salt of at least 16 bytes, N=2**17, r=8, p=1,
32-byte output and an explicit sufficient maxmem (256 MiB). Store the algorithm,
parameters, salt and verifier, never plaintext. Refuse unsupported algorithms and
malformed parameters; fail clearly if this Python lacks scrypt. Compare verifiers
with `secrets.compare_digest`. Support passphrases of 15–256 Unicode characters,
with at most 1024 UTF-8 bytes; do not trim, normalize or silently truncate them.
Fixed parameter verification tests must exercise the real KDF at least once;
focused authorization cases can reuse an already created test identity.

These choices use Python's [hashlib documentation](https://docs.python.org/3/library/hashlib.html#hashlib.scrypt)
and OWASP's [password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
checked on 2026-10-08. This application does not claim FIPS certification.

Login issues a new 32-byte random token; only its SHA-256 verifier is stored.
Session records bind immutable user identity, issued time, last activity, absolute
expiry and revocation. Use explicit 30-minute idle and 8-hour absolute expiry.
The current user/grants are looked up on every authorized operation; roles in a
caller-provided object are never trusted. Password reset, disabling a user and
logout revoke existing sessions. User/grant changes have actor/time/reason audit.
Use injectable UTC time for tests, not real waiting or a browser timestamp.

Login failures must not reveal whether a username exists. Bound login attempts
to 5 attempts per username and 30 attempts globally per 5-minute window, return
a persisted retry time, and allow at most two simultaneous costly KDF operations; do not sleep in request handlers or allow
unbounded 128 MiB allocations. Apply the same failure path to unknown users.
Never log passwords, cookies, verifier bytes or source descriptions.

Authorization resolves token + entity ID + a fixed operation into server-derived
user/role/capabilities. Check identity/session/grant again for each action, including
retries. Revocation prevents new privileged work even when an old request would
otherwise return an idempotent accounting receipt. Serialize grant revocation with
short privileged mutations so an approval cannot commit after a revocation that
won the authorization race. Do not hold this lock across a provider network call;
a resumed run must recheck before its next authorized tool effect.

Use versioned atomic schema creation/migration, SQLite constraints and scoped
retry keys for grant changes. Unknown future schema versions fail without edits.
Provision entity mappings from trusted local paths only; verify immutable stored
entity identity before adding a mapping. New users receive no implicit grants.

## Task 1: credential and authorization lifecycle

**Files:** New focused authentication module/tests and CLI entry points. Parent
owns docs/CI/browser. Existing workspace/HTTP protection is the separate 29b gate.

- [ ] RED: a logged-in preparer for entity A can prepare but cannot approve; the
  same session cannot read or mutate entity B. Unknown operations/roles deny.
- [ ] Implement the fixed role map, real KDF, opaque sessions and grant lifecycle.
  Test wrong passwords, distinct salted hashes, no plaintext/token storage,
  malformed verifiers, expired idle/absolute sessions and fresh login rotation.
- [ ] Exercise logout, password reset, disabled user and grant revocation with
  preexisting sessions; forged user/role dictionaries never authorize an action.
- [ ] Verify bounded failed-login behavior with an injected clock and no sleeps;
  race a grant revocation against a privileged callback and observe one defined
  order without an authorization-to-commit gap. Provider calls never hold locks.
- [ ] Cover initialization/write rollback, reopen, concurrent session issuance,
  explicit synthetic entity mapping and unchanged financial database bytes.
- [ ] Add interactive create-user/grant/revoke CLI commands without password
  argv/env defaults. `demo-access` uses temporary synthetic identities/entities
  and prints allowed preparation, denied approval and denied cross-entity read.
- [ ] Run focused checks then guarded suite/foundation/all demos/diff. Independent
  review, commit/push/exact CI before authenticating the live workspace in 29b.

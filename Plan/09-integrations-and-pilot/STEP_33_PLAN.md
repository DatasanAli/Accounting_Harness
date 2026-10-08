# Step 33: coherent local recovery and operational visibility

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 32; deliver recovery and visibility separately.

**Goal:** Restore a verified complete workspace to a separate destination, reopen
its UI/runs correctly, and expose redacted operational failures without losing
accounting history or replaying side effects.

**Architecture:** An offline maintenance CLI takes a coherent backup of the known
workspace databases and a versioned manifest, then verifies a staged restore
before making the new destination usable. A small read-only status view derives
failure/stall metrics from existing durable run/integration records. No cloud
backup service, background alert delivery or new monitoring stack.

**Tech stack:** Python/SQLite backup API, standard-library file locking and existing
application status UI. **Spec:** [Phase 09](README.md).

## Global constraints

- Synthetic local files only; never upload databases, credentials or raw evidence
  to GitHub. Backups are private local artifacts with restrictive permissions.
- Preserve original workspace untouched. Restore only into a new empty destination;
  refuse same/overlapping/symlinked original paths and traversal-bearing manifests.
- Backup/restore is disaster recovery, not correction of a valid posted entry.
  Ordinary corrections still require the supported linked accounting policy.
- Preserve exact historical journals, source content, approvals, effects, report
  captures and run checkpoints. Do not rewrite recorded actors, paths or scopes
  inside old audit/config/checkpoint payloads to make relocation appear valid.
- Restored provider/external transports stay disabled. Do not restore an old
  browser session as an authenticated login or resume uncertain external writes
  automatically. Explicit local recovery activation and fresh login are required.

## Coherent snapshot and verified relocation

Inventory all workspace stores: sources, ledger (including reviews/subsidiaries/
reports/management state), run log, authentication/entity mappings and integration
outbox/simulator state. Include every file required by the configured synthetic
workspace group; never restore a grant mapping that points back into the original
financial files or silently omits another configured entity's required state.

Require maintenance quiescence enforced by an application-owned file lock shared
by normal workspace operations and held exclusively during backup/restore. Also
establish a fixed lock order for all SQLite writers while capturing their committed
state. Test a concurrent application write is refused/blocked safely; a sequence
of independent file copies is not a coherent backup. Use SQLite's backup mechanism
and integrity/foreign-key checks, never copy live WAL files piecemeal.

The manifest has a strict version, fixed relative file roster, SHA-256/size for
each file, entity/catalog/context/schema identities, capture time and cross-store
verification summary. Totals use exact cents. Hashes detect damage relative to a
trusted local manifest; they do not authenticate an arbitrary imported backup.
Validate bounds, duplicate keys, unknown files/versions and digest/context mismatch
before activation. Stage into a newly created sibling directory and publish the
verified new destination atomically; interrupted/failed restore leaves the original
unchanged and cannot expose a partially verified workspace as ready.

Step 19a reproduced an actual relocation failure: `runs.py` binds absolute ledger
and registry paths in immutable `run_context`/run configs. Its `_path` also feeds
proposal IDs and tool idempotency keys. Merely bypassing the path check or changing
only `_scope` risks replaying a draft after an interrupted tool effect.

Add an explicit versioned relocation record linking the verified backup identity,
original logical storage identities and new physical files. Preserve historical
scope/config/checkpoint bytes. Resolve physical paths through that trusted record
while retaining historical logical run identity and retry keys for existing runs.
A caller-supplied alias/path must not bypass entity/context/tool-policy checks.
New runs use a documented stable identity policy, and any additive migration is
atomic and preserves old run receipts. Ordinary unverified directory copying
should still fail clearly rather than trusting arbitrary aliases.

Restore authentication configuration without reactivating old sessions; record
recovery activation and revoke those sessions explicitly, preserving prior auth
audit. Remap only verified workspace destinations. Do not retain links to original
entity data. Document this intentional operational-state change separately from
byte-identical financial/run history.

## Recovery proof and status policy

The drill creates pending/rejected/posted reviews, completed and interrupted runs,
bank/reconciliation records, reports/scenarios and a simulated uncertain export.
Backup to an ignored local artifact, restore to a separate path, reopen the actual
Workspace/server and compare journals, trial balance, source digests, approval/
review history, captured reports and original run checkpoint bytes. Resume a run
whose draft effect committed before its checkpoint and prove no duplicate draft.
Read the uncertain export without sending it; recovery never assumes it failed.

Measure backup, restore and validation elapsed milliseconds with a monotonic clock;
report the observed data volume and environment, not a promised recovery SLA.
Tests inject faults during each file/manifest/finalization stage. Include corrupt
bytes, wrong entity/context, unsupported schema, missing store and path attacks.

Operational status reports counts and stable references for failed/stalled runs,
registered-but-unenrolled evidence, incomplete imports, uncertain exports, drift
and last successful backup verification. Define stalled as a nonterminal run with
no new checkpoint for at least 15 minutes; use an injected UTC clock. A terminal
review handoff is not a stalled run. Show the threshold and last checkpoint time.

Metrics and visible alerts contain entity-safe IDs, status/error codes, timestamps,
counts and durations only. Exclude source descriptions, account passwords, tokens,
provider request/response bodies and hidden reasoning. Authorization applies to
status/history as to accounting data. Alerts are local UI/CLI notices; sending
email/Slack notifications is outside this request.

## Independently verified deliveries

1. [33a coherent backup and verified relocation](STEP_33A_PLAN.md): restore the
   actual app/runs at a separate destination with preserved history and retry IDs.
2. [33b redacted operational visibility](STEP_33B_PLAN.md): status and local alerts
   derived from existing durable records, without changing accounting activity.

Both gates precede the final synthetic release acceptance.

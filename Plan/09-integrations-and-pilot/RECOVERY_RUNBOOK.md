# Coherent local recovery runbook

The local implementation, demonstration and restored browser rehearsal passed. See [verification](STEP_33A_VERIFICATION.md) for delivery and exact CI evidence.

Recovery covers the complete configured synthetic group: the identity database and every mapped entity, including sources, ledger/reviews/reports/management state, legacy and operational runs, staged reads, export outbox and independent simulated receipts when present. A plain directory copy is not an activated recovery workspace.

## Back up and verify

Run from the repository root, with private destinations outside the original data directories:

```sh
python3 -m accounting_harness backup-workspace --access-db .local/access.sqlite3 --destination .local/backup-001
python3 -m accounting_harness verify-backup --backup .local/backup-001
```

The application takes exclusive maintenance locks, reserves all SQLite writers in a fixed order and uses SQLite backup snapshots. Normal application operations share those locks. If an operation is in progress, backup may report busy; finish or stop it and retry. Do not copy live WAL files manually.

The strict manifest records a fixed relative roster, hashes/sizes, schema/entity/context identities and verification measurements. It rejects omissions, unknown files and unsupported identities. Hashes detect changes relative to a trusted local manifest; they do not authenticate an arbitrary imported bundle. Keep backup files and the manifest together, private and outside GitHub.

## Restore to a new location

```sh
python3 -m accounting_harness restore-workspace --backup .local/backup-001 --destination .local/restored-001 --activate
python3 -m accounting_harness serve --access-db .local/restored-001/access.sqlite3
```

The explicit activation flag authorizes the local recovery operation. Restore verifies a private staged directory before publishing the new group. Use a new destination outside the original and backup directories. Existing, overlapping or symlinked destinations are refused. Original financial and run history remains intact. Operational recovery receipts record successful verification separately; restore remaps identities and revokes sessions only in the new group.

Restored startup preserves pending evidence enrollment until an explicit supported action. Log in again with a restored user account. Old sessions are revoked with an audit event. All entity mappings point into the verified restored group. Historical financial/run payloads retain their original logical scope and retry identity; physical file and dispatch-lock locations move. This allows a committed proposal effect to be recovered after a missing checkpoint without creating another proposal.

Restored provider and external transports remain disabled, even if an enable flag is supplied. Inspect uncertain export history; never assume an interrupted request failed and never issue a new identity to replace it. Recovery does not send pending exports or create remote reversals. Run recovery is local, offline and explicitly invoked.

## Verify the restored application

1. Compare journal counts, exact trial balance and source digests with the capture.
2. Inspect posted, pending and rejected review records and their human approval/evidence references.
3. Reopen captured reports and retained run checkpoints. Resume an interrupted local run through the supported action and confirm no duplicate effect.
4. Inspect the uncertain export without sending it. Confirm prior sessions fail and a fresh login sees the correct entity.
5. Keep both original and restored groups until the recovery result has been reviewed. Do not use restore to reverse legitimate posted accounting activity.

```sh
python3 -m accounting_harness demo-recovery
```

The synthetic drill reports observed data volume and backup/restore/validation elapsed milliseconds. These are measurements for this fixture and environment, not a recovery SLA. A corrupt or failed staged restore must not expose a partial ready workspace. Investigate the reported validation failure; do not bypass schema, context or manifest checks.

## Inspect operational status

Open `#operations` directly in the authenticated UI, or capture the same redacted metadata from a terminal:

```sh
python3 -m accounting_harness operations-status --access-db .local/access.sqlite3 --entity alpha --username owner
```

Use your configured entity and user. The command requires hidden passphrase entry and reads with that user's current grant. Status never enrolls evidence, retries work or sends notifications. Record links recheck authorization. Missing recovery receipts remain unavailable; a backup and a restore are distinct verified operations. See [Step 33b verification](STEP_33B_VERIFICATION.md).

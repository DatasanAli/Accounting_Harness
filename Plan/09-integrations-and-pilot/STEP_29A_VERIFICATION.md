# Step 29a verification: local identities and entity grants

Observed on 2026-10-08. This delivery verifies the identity/authorization core;
HTTP and browser authentication are the separate Step 29b gate.

## Actual terminal and persisted-state rehearsal

Used the delivered `access-create-user` command through a controlling terminal.
Three synthetic users—owner, preparer and reviewer—entered their passphrases twice
through hidden `getpass` prompts. Each received a stable application user ID and
no implicit entity grants. No password argument, environment default or secret
output was used. Rehearsal credentials and session tokens remain private and
ignored locally; they are not part of GitHub.

`access-provision` created two distinct synthetic workspaces. Their catalogs,
registry identities and workspace results agree with their separate entity IDs;
each contains five scoped fictional receipts and zero journals. `access-map-entity`
registered the existing closed reference workspace through read-only identity
checks. Its four-file roster, sizes and SHA-256 hashes remained exactly unchanged.
This is an identity check, not a backup or recovery claim.

Actual `access-grant` commands with explicit `GRANT` confirmations assigned owner
access to all three synthetic entities and preparer/reviewer access only to the
first new entity. The core then demonstrated:

- Preparer preparation, reviewer approval permission and owner activation
  permission resolved to the correct stored user IDs.
- Preparer approval, reviewer preparation, ungranted entity reads, a forged role
  dictionary and an unknown operation were denied before the callback ran.
- CLI `REVOKE` stopped an existing preparer session's action. A separately confirmed
  grant with a new audit reason restored permission.
- Logout invalidated the reviewer session; a fresh login restored its access.
- A new Python process reopened the identity store and retained exact identities,
  roles and sessions, including all role/entity denials.
- Identity database bytes contain neither rehearsal passwords nor raw issued
  session tokens. The original financial workspace stayed unchanged.

The three measured user-creation processes took 0.261, 0.240 and 0.235 seconds.
Observed macOS peak resident memory was approximately 159 MiB per process. These
are local observations, not a deployment performance or security guarantee.

## Reproducible commands

The core demonstration uses disposable fictional data:

```sh
python3 -m accounting_harness demo-access
python3 -m unittest discover -s tests -p test_access.py -v
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
```

For a new local synthetic workspace, supply your own passphrase interactively:

```sh
python3 -m accounting_harness access-create-user --access-db .local/access.sqlite3 --username owner --reason 'Initial local owner'
python3 -m accounting_harness access-provision --access-db .local/access.sqlite3 --workspace .local/access-example --entity access-example --reason 'New synthetic entity'
python3 -m accounting_harness access-grant --access-db .local/access.sqlite3 --username owner --entity access-example --role owner --retry-key initial-owner --reason 'Explicit local owner grant'
```

For already provisioned books, use `access-map-entity` with their existing path and
entity instead of `access-provision`. Provision refuses an existing directory;
mapping checks immutable ledger/source identities without constructing Workspace.
Use separate users and explicit grants for preparer/reviewer segregation. The OS
operator is the trusted bootstrap administrator; these commands are not an
unauthenticated network administration interface.

## Verification and delivery

- 35 focused access tests passed in 15.116 seconds, following observed failures
  for the missing core, CLI/demo and session-identity protection.
- Final guarded suite: 776 tests passed in 68.632 seconds; discovery guard retained.
- All 40 demonstrations passed. The access demo creates a real reviewable draft
  under the resolved preparer ID, retains zero journals and prints the expected
  approval, cross-entity, revoked-session and expired-session denials.
- Foundation and diff checks passed; independent spec/quality review approved
  with no Critical, Important or Minor findings.
- Final-code original-workspace restart preserved all prior financial state,
  attribution/time, costing/budget/indicator versions, financial/cash-flow reports
  and portable export bytes. Fresh-process session checks also passed.
- Commit, remote and exact-SHA CI remain pending.

No HTTP protection or live connection is claimed by this identity-core slice.

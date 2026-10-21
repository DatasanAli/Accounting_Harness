# Offline synthetic workspace runbook

This application rehearses a fictional USD service business for January 2026. Local SQLite journals are authoritative. Provider proposals, remote staging and management scenarios never become actuals without the supported application workflow and human approval. This runbook does not authorize real financial data or live connections.

## Fresh local setup

Use Python 3.12+, SQLite 3.37+, and Node.js for verification. Run from the repository root. There are no third-party Python packages to install. Use a new workspace directory; provisioning refuses an existing one.

```sh
python3 -m accounting_harness access-provision --access-db .local/access.sqlite3 --workspace .local/synthetic-alpha --entity alpha --reason 'Fictional local rehearsal'
python3 -m accounting_harness access-create-user --access-db .local/access.sqlite3 --username preparer --reason 'Fictional local rehearsal'
python3 -m accounting_harness access-create-user --access-db .local/access.sqlite3 --username reviewer --reason 'Fictional local rehearsal'
python3 -m accounting_harness access-create-user --access-db .local/access.sqlite3 --username owner --reason 'Fictional local rehearsal'
python3 -m accounting_harness access-grant --access-db .local/access.sqlite3 --username preparer --entity alpha --role preparer --retry-key setup-preparer --reason 'Fictional local rehearsal'
python3 -m accounting_harness access-grant --access-db .local/access.sqlite3 --username reviewer --entity alpha --role reviewer --retry-key setup-reviewer --reason 'Fictional local rehearsal'
python3 -m accounting_harness access-grant --access-db .local/access.sqlite3 --username owner --entity alpha --role owner --retry-key setup-owner --reason 'Fictional local rehearsal'
python3 -m accounting_harness serve --access-db .local/access.sqlite3
```

Create-user prompts twice for a hidden passphrase; grant asks for explicit `GRANT`. There is no default password or implicit owner. Open the printed loopback URL, log in and select alpha. Owner activates the fixed control accounts needed by a workflow. Preparer registers evidence and prepares a proposal; reviewer checks evidence, date, accounts and amount before confirming the exact revision. Use separate browser contexts for separate identities. Stop the server with Ctrl-C and restart the same command to reuse its state.

Keep identity storage outside financial workspace directories. Keep the complete `.local/` group private and out of GitHub. The localhost UI checks authentication, entity membership and CSRF; it is not an internet deployment. Trusted direct store APIs remain available to the local file owner and are not a substitute for the authenticated service boundary.

## Later provider configuration

Provider calls are disabled by default. These commands document existing configuration only; the campaign did not connect or evaluate either provider live.

```sh
# After independently installing and starting a local Ollama model:
python3 -m accounting_harness serve --access-db .local/access.sqlite3 --enable-providers --ollama-model YOUR_LOCAL_MODEL

# Alternatively, privately set OPENAI_API_KEY in the server's launching environment:
python3 -m accounting_harness serve --access-db .local/access.sqlite3 --enable-providers
```

Never put a key in a command argument, source document, browser field or committed file. Provider credentials remain server-side. Select a provider and explicitly request preparation. The adapters enforce bounded calls; configuration alone proves neither connectivity nor model accuracy. Unknown completion requires review. The operational agent can propose supported workflows and request human review; it cannot approve, post, close or authorize export.

## Accounting limits and real-data gate

The reference month uses the published operational variant, with insurance purchased on January 1. Its adjusted results are revenue 2,700.00, expenses 1,600.00, income 1,100.00, assets 11,500.00, liabilities 600.00, equity 10,900.00 and Cash 9,400.00. Separate bank, accrual and management examples do not change those reference totals.

Posted entries are immutable. Ordinary corrections use supported linked reversals; managed subsidiary effects cannot be bypassed with arbitrary journals or unsupported reversals. Credits, refunds, settlement corrections, foreign currency, tax, payroll, inventory and depreciation require separately approved policies and implementation. Closing locks the effective date range; restoring a backup is disaster recovery, not a way to undo legitimate activity.

Before real-data use, decide and record legal entity, reporting framework, fiscal calendar, jurisdiction, recognition/capitalization/correction policies, operators and segregation of duties, retention, backup custody and authorized external actions. Live model evaluation, real sandbox import/export and actual pilot acceptance are separate outstanding gates.

## Recovery and local status

Back up the complete configured group to a new private destination, verify it, then restore to a separate destination with explicit activation:

```sh
python3 -m accounting_harness backup-workspace --access-db .local/access.sqlite3 --destination .local/backup-001
python3 -m accounting_harness verify-backup --backup .local/backup-001
python3 -m accounting_harness restore-workspace --backup .local/backup-001 --destination .local/restored-001 --activate
python3 -m accounting_harness serve --access-db .local/restored-001/access.sqlite3
```

Fresh login is required after restore. Historical identities and retry keys remain intact, while all restored provider/external transports stay disabled. No uncertain export is retried automatically. Use the [recovery runbook](RECOVERY_RUNBOOK.md) for supported platforms, fault handling and trust limits. A successful backup measurement is not a promised recovery SLA.

The operational-status UI reports local failed/stalled runs, enrollment, incomplete reads, uncertain exports, recorded drift and verified recovery checkpoints. It sends no notifications and makes no retries. Missing backup history is unavailable, not healthy. A terminal review handoff is not stalled; the threshold for nonterminal idle runs is 15 minutes. Status excludes evidence bodies and secret-bearing identifiers.

Capture the same redacted status from a terminal using a provisioned account:

```sh
python3 -m accounting_harness operations-status --access-db .local/access.sqlite3 --entity alpha --username owner
```

The command prompts for a hidden passphrase; do not supply passwords in command arguments. Open `#operations` directly in the authenticated UI to inspect status without loading the ordinary workspace state. Record links recheck authorization and current status before displaying safe metadata. No status screen sends notifications or performs recovery actions.

## Reproduce offline acceptance

```sh
python3 -m accounting_harness demo-acceptance
python3 -m accounting_harness demo-operations-status
python3 -m accounting_harness demo-recovery
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
node --check accounting_harness/static/app.js
```

The offline acceptance suite and browser rehearsal passed. Consult the [release evidence](STEP_34_VERIFICATION.md) for observed results and exact GitHub delivery. The complete documented demonstration set is listed in the [repository README](../../README.md). Foundation checks alone do not prove application behavior.

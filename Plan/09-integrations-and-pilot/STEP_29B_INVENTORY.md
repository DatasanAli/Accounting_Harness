# Step 29b application boundary inventory

Updated: 2026-10-14. The facade resolves current session, fixed role and registered
entity before constructing Workspace. Unknown methods/actions fail closed. HTTP
uses this facade exclusively; no anonymous owner or local-operator fallback exists
in that boundary. Historical actors remain unchanged in trusted storage.

## Entry points and permissions

Public static assets: GET `/`, `/app.js`, `/style.css` (no financial state).
GET `/api/login-challenge` issues a one-use five-minute pre-login challenge;
POST `/api/login` checks its cookie/header pair, exact JSON, Host and Origin.
GET `/api/session` verifies credentials and returns current identity/grants without
extending idle activity. POST `/api/entity` checks membership and rotates CSRF;
POST `/api/logout` revokes the session and clears its cookie. Every other protected
route requires a valid selected entity plus matching X-Entity-ID. Mutations also
require that browser session's current CSRF token. Duplicate credentials deny.

All three human roles share evidence, audit and report reads. Preparer and owner
prepare; reviewer and owner approve. Owner alone activates fixed accounts.
`authorize_export` is reserved for Step 32 external journal export. Existing
local JSON/ZIP report downloads remain reproducible `read_reports` operations;
they neither send data to another service nor authorize external writes.

| GET route | Facade method | Permission |
| --- | --- | --- |
| `/api/state` | `state` | `read_audit` |
| `/api/sources` | `list_sources` | `read_evidence` |
| `/api/report-export` | `report_package` | `read_reports` |
| `/api/budget` | `budget` | `read_reports` |
| `/api/budget-inputs` | `budget_inputs` | `read_reports` |
| `/api/variance` | `variance` | `read_reports` |
| `/api/indicators` | `indicators` | `read_reports` |
| `/api/indicator-inputs` | `indicator_inputs` | `read_reports` |
| `/api/project-cost` | `project_cost` | `read_reports` |
| `/api/financial-statements` | `financial_statements` | `read_reports` |
| `/api/cash-flow` | `cash_flow` | `read_reports` |
| `/api/project-dimensions` | `project_dimensions` | `read_reports` |
| `/api/project-time` | `project_time` | `read_reports` |
| `/api/project-cost-inputs` | `project_cost_inputs` | `read_reports` |
| `/api/bank-statements` | `list_bank_statements` | `read_evidence` |
| `/api/bank-matches` | `bank_matches` | `read_reports` |
| `/api/bank-reconciliation` | `bank_reconciliation` | `read_reports` |
| `/api/bank-statements?bank_account_id=…&statement_id=…` | `bank_statement_detail` | `read_evidence` |
| `/api/external-reads` (Step 30) | `external_reads` | `read_reports` |

`providers` is a direct facade read (`read_audit`) also included in `state`.
`state` aggregates evidence, drafts, journals, audit, reports and provider config;
the current fixed roles all share those read capabilities.

| POST route/action | Permission |
| --- | --- |
| `/api/expense-accrual-proposals` | `prepare_proposal` |
| `/api/revenue-accrual-proposals` | `prepare_proposal` |
| `/api/prepaid-proposals` | `prepare_proposal` |
| `/api/bank-fee-proposals` | `prepare_proposal` |
| `/api/cash-proposals` | `prepare_proposal` |
| `/api/advance-proposals` | `prepare_proposal` |
| `/api/invoice-proposals` | `prepare_proposal` |
| `/api/bill-proposals` | `prepare_proposal` |
| `/api/bill-payment-proposals` | `prepare_proposal` |
| `/api/invoice-collection-proposals` | `prepare_proposal` |
| `/api/advance-earning-proposals` | `prepare_proposal` |
| `/api/indicators` | `manage_scenarios` |
| `/api/budget` | `manage_scenarios` |
| `/api/project-cost` | `manage_allocations` |
| `/api/projects` | `manage_allocations` |
| `/api/project-assignments` | `manage_allocations` |
| `/api/project-time` | `manage_time` |
| `/api/project-time-void` | `manage_time` |
| `/api/close-preview` | `read_reports` |
| `/api/close-confirm` | `confirm_close` |
| `/api/bank-timing` | `record_timing` |
| `/api/bank-reconcile` | `confirm_reconciliation` |
| `/api/bank-fee-account` | `activate_accounts` |
| `/api/activate-account` | `activate_accounts` |
| `/api/bank-match` | `match_bank` |
| `/api/bank-unmatch` | `withdraw_bank_match` |
| `/api/bank-statements` | `import_bank_csv` |
| `/api/sources` | `register_evidence` |
| `/api/operation-sources` | `register_evidence` |
| `/api/run` | `start_run` |
| `/api/cancel` | `cancel_run` |
| `/api/reject` | `reject_proposal` |
| `/api/approve-post` | `approve_post` |
| `/api/qbo-read` (Step 30) | `stage_external` |

`bank-timing` with role `withdraw` uses `withdraw_timing`. Direct convenience
methods below dispatch through exactly the same action mapping, never directly
to a raw Workspace method:

| Direct method | Action |
| --- | --- |
| `prepare_expense_accrual` | `expense-accrual-proposals` |
| `prepare_revenue_accrual` | `revenue-accrual-proposals` |
| `prepare_prepaid` | `prepaid-proposals` |
| `prepare_bank_fee` | `bank-fee-proposals` |
| `prepare_cash` | `cash-proposals` |
| `prepare_advance` | `advance-proposals` |
| `prepare_invoice` | `invoice-proposals` |
| `prepare_bill` | `bill-proposals` |
| `prepare_bill_payment` | `bill-payment-proposals` |
| `prepare_collection` | `invoice-collection-proposals` |
| `prepare_earning` | `advance-earning-proposals` |
| `import_bank_statement` | `bank-statements` |
| `register_source` | `sources` |
| `register_operation_source` | `operation-sources` |

`Workspace.storage` and underscore helpers are trusted internal primitives, never
facade operations. CLI fixture demonstrations and `review-post` are trusted local
OS-owner tools, not public authentication APIs. Fixed account activation accepts
only an account code from 2000, 1100, 2100, 2050, 1150 and 5300.

## Side effects and actor ownership

- Workspace construction can initialize/migrate schemas, register bundled
  synthetic evidence and recover source enrollment. Authorization precedes all
  of this. Registered entity paths are checked read-only before construction;
  unknown/ungranted IDs never open financial files. Bundled sample import keeps
  its fixture-service actor. New enrollment uses the authenticated user ID.
- Reads may initialize existing service schemas and capture reproducible views;
  they do not activate fixed accounts or post journals. Close preview can register
  a deterministic calculation artifact, using the initiating user's actor through
  registration/enrollment; it grants no close permission.
- Bill, invoice, advance and expense/revenue-accrual preparation can activate
  controls in trusted services. The facade first checks activation and requires
  owner permission if missing. The explicit owner action makes preparer workflows
  available. Accrual account/extension insertion shares one ledger transaction.
- Evidence registration/enrollment, human proposals, rejection, approval/posting,
  bank import/matching/timing/reconciliation, project/time/scenario writes and
  close confirmation receive the server-derived stable user ID. Actor, role,
  permissions and filesystem paths supplied in request JSON cannot confer access.
- Agent configurations add an authenticated initiator only to new runs; older
  serialized configurations remain unchanged. Runtime actor is workspace-agent.
  Resume configuration must match the initiating user and immutable entity scope;
  cancel requires that same initiator and current cancel permission. Old unbound
  runs remain readable, but authenticated users cannot adopt them by guessing IDs.
- The identity write lock spans each short application effect through commit.
  Revocation therefore orders before or after a completed financial operation.
  Provider I/O releases that lock; each subsequent run/tool transaction rechecks
  authorization. A late provider response after revocation cannot save a draft.
- Entity switch/logout locks the UI, clears financial state, source selections,
  pending confirmations and form inputs, then reloads. Responses and report bodies
  and background status polls are discarded if the scope generation changed. Pending run recovery metadata in sessionStorage is bound to user and entity, validated only after login; logout/entity change clears it. No credentials are stored there. Current grants are polled every
  15 seconds without extending idle life; a denied request clears state immediately.
- Step 30 `qbo-read` (preparer/owner `stage_external`) accepts only `batch_id`.
  It authorizes briefly, calls the offline simulator outside the identity lock,
  and rechecks authority around each write to the separate `qbo-staging.sqlite3`
  mirror. Staging writes never touch ledger, source or run files (Workspace
  construction keeps its existing startup behavior). `external_reads` never
  creates the mirror. See [Step 30 verification](STEP_30_VERIFICATION.md).

## Transport boundary

Only 127.0.0.1 is bound. Host-only HttpOnly SameSite=Strict Path=/ cookies are used
without HTTPS-only prefixes on this local HTTP transport. This is not TLS or a
remote-hosting design. Host/Origin, no-store, CSP, duplicate JSON/header guards,
16 KiB bodies and silent request logging remain enforced. No default credentials,
URL tokens or web-storage credentials are accepted. See
[OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
(checked 2026-10-14). The OS file owner remains the trusted local administrator.

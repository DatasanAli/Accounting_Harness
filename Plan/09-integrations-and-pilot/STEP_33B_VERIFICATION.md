# Step 33b verification: redacted operational status

Implementation and native browser checks passed. The full guarded suite and independent re-review passed; upload and exact CI are pending.

## Contract

One captured status projection serves authenticated UI and local CLI. Reads inspect existing fixed stores directly without workspace/service initialization, enrollment, retries, posting or transport calls. Authentication session activity remains operational metadata. Per-store read transactions cover a stated collection interval; this is not an atomic accounting-report snapshot.

The policy reports failed/stalled runs, registered-but-unenrolled evidence, incomplete staged reads, uncertain exports, recorded drift and separate verified backup/restore checkpoints. Nonterminal idle work stalls at 900,000ms; terminal review handoffs do not. Missing or invalid history is unavailable, not a healthy zero. Stable scoped references and finite codes replace raw identifiers, descriptions, bodies and errors. Authorized record resolution must preserve entity scope and redaction.

All 48 demonstrations passed; 23 focused status/Node tests and 80 authentication/access/workbench regressions passed. Foundation (131 Markdown files, 421 links, 34 steps), JavaScript syntax and diff checks passed. **922 tests passed in 130.088s**, with the zero-discovery guard intact. Live providers, external monitoring/notifications and automatic recovery actions remain outside this view.

## Browser evidence

Fresh synthetic owner login directly into `#operations` fetched only session/entity/status endpoints. It showed failed/stalled runs (2), pending enrollment (1), incomplete read (1), uncertain/drift exports (2), verified backup and unavailable restore. No source/provider/native-ID sentinel appeared anywhere in the DOM or status JSON. Keyboard capture and record inspection focused the resolved detail; at 390px the document/content widths both measured 375px. Reloading the record link avoided `/api/state` as well. All six accounting/workflow SQLite dumps were identical before login and after capture, record inspection and reload. A direct cross-entity request returned 403.

An actual separately restored group required fresh login and showed verified restore, unavailable local backup history, and preserved failed/stalled/uncertain/drift records. It did not invent a backup receipt from successful restore. Both routes remained redacted and read-only.

## Review correction

Independent review reproduced a P1 keyboard-route loophole: `#operations` → Skip to workspace (`#main`) → global Refresh called `/api/state`, enrolling pending evidence. Remembered status startup at `#main` also selected the wrong visible panel. Both routing decisions now retain the active status view. A shipped-JavaScript/real-store regression first reproduced enrollment from zero to one, then proved unchanged SQL dumps and pending enrollment after the fix; ordinary Evidence navigation still loads its intended state.

The actual browser repeated Skip → Refresh and remembered `#main` reload. Both fetched only status/session endpoints, kept Operational status visible, leaked no sentinel and preserved all six original store dumps. Independent scoped re-review ran all 23 status tests and approved with no remaining findings. The full guarded rerun passed; affected status/workbench demonstrations passed again after the fix.

## Delivery

Pending. Next authorized work: Step 34 synthetic release acceptance and final cross-phase adversarial review/fixes.

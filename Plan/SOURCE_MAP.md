# Textbook review and implementation map

Reviewed on 2026-09-10, in the requested order: **Volume 1 first, then Volume 2**. Both local PDFs were converted to searchable text. The review covered the complete contents and chapter summaries of all 16 Volume 1 chapters and all 13 Volume 2 chapters, with closer reading of the foundational sections listed below. This was a requirements-focused review, not a line-by-line reading of every exercise or an independent verification of every textbook assertion.

The supplied second filename says Financial Accounting, but its title page identifies **Principles of Accounting, Volume 2: Managerial Accounting**. That distinction places its costing and planning material after the financial-bookkeeping foundation.

## Bibliographic references

Mitchell Franklin, Patty Graybeal, and Dixon Cooper, senior contributing authors. OpenStax, Rice University, 2019:

- [Principles of Accounting, Volume 1: Financial Accounting](https://openstax.org/details/books/principles-financial-accounting). Local file: `Principles_of_Financial_Accounting_Vol1.pdf`; 973 PDF pages; digital ISBN 978-1-947172-67-8.
- [Principles of Accounting, Volume 2: Managerial Accounting](https://openstax.org/details/books/principles-managerial-accounting). Local file: `Principles_of_Financial_Accounting_Vol2.pdf`; 677 PDF pages; digital ISBN 978-1-947172-59-3.

The supplied copies' copyright pages state CC BY-NC-SA 4.0. Source PDFs and extracted text remain local. This repository contains original implementation plans and fictional fixtures and uses the books as bibliographic references. Access for free at openstax.org.

See [sources.json](references/sources.json) for exact file hashes and extraction/page conventions. For these supplied copies, **PDF page = printed page + 14** in Volume 1 and **printed page + 12** in Volume 2. Numbers below refer to printed pages; another edition may differ.

## Volume 1: financial accounting coverage

| Chapter; printed start | Implementation implication | Phase |
| --- | --- | --- |
| 1. Role of Accounting in Society; 11 | Identify owner/bookkeeper/reviewer needs and separate financial reporting from management analysis | [01](01-foundation/README.md), [08](08-service-management/README.md) |
| 2. Introduction to Financial Statements; 53 | Account classifications; income, equity, balance sheet and cash-flow relationships | [02](02-ledger-core/README.md), [07](07-period-close/README.md) |
| 3. Analyzing and Recording Transactions; 101 | Evidence → analysis → journal → ledger → trial balance; balanced entries and account-level checks | [02](02-ledger-core/README.md), [03](03-evidence-and-review/README.md) |
| 4. The Adjustment Process; 189 | Distinguish accruals/deferrals; adjust before statements; retain supported recognition dates | [07](07-period-close/README.md) |
| 5. Completing the Accounting Cycle; 259 | Temporary/permanent accounts, closing, post-close trial balance; complete service-business cycle | [07](07-period-close/README.md) |
| 6. Merchandising Transactions; 329 | Service-first scope excludes merchandise; later returns, discounts, freight and inventory systems | [10](10-deferred-extensions/README.md) |
| 7. Accounting Information Systems; 409 | Source storage, processing/output, repeated transaction flows and subsidiary/control reconciliation | [03](03-evidence-and-review/README.md), [04](04-agent-harness/README.md), [05](05-service-bookkeeping/README.md), [09](09-integrations-and-pilot/README.md) |
| 8. Fraud, Internal Controls, and Cash; 481 | Clear responsibilities, review, audit trace and bank reconciliation | [03](03-evidence-and-review/README.md), [06](06-bank-reconciliation/README.md), [09](09-integrations-and-pilot/README.md) |
| 9. Accounting for Receivables; 523 | Earned invoice versus collection, aging and allowances; complex contracts/notes deferred | [05](05-service-bookkeeping/README.md), [10](10-deferred-extensions/README.md) |
| 10. Inventory; 589 | Explicit cost-flow policy and quantity/cost reconciliation; optional inventory extension | [10](10-deferred-extensions/README.md) |
| 11. Long-Term Assets; 637 | Asset versus expense, accumulated depreciation, schedules/disposals/intangibles | [07](07-period-close/README.md), [10](10-deferred-extensions/README.md) |
| 12. Current Liabilities; 677 | Vendor obligations, advances, accruals; payroll/tax/contingencies require separate scope | [05](05-service-bookkeeping/README.md), [07](07-period-close/README.md), [10](10-deferred-extensions/README.md) |
| 13. Long-Term Liabilities; 735 | Debt schedules, interest, premiums/discounts and carrying value | [10](10-deferred-extensions/README.md) |
| 14. Corporation Accounting; 781 | Equity model depends on entity; stock, retained earnings, dividends and EPS are extensions | [01](01-foundation/README.md), [10](10-deferred-extensions/README.md) |
| 15. Partnership Accounting; 841 | Partner capital and allocation policies differ from the sample single-owner model | [10](10-deferred-extensions/README.md) |
| 16. Statement of Cash Flows; 869 | Separate operating/investing/financing; reconcile to cash; distinguish noncash activity | [07](07-period-close/README.md), [10](10-deferred-extensions/README.md) |

Appendix A (919): horizontal/vertical and ratio analysis → Phase 08/10. Appendix B (931): time-value reference tables → Phase 10 debt/capital-budgeting calculations. Appendix C (935): resource directory, not a new implementation feature. Answer keys/index are navigation/reference material, not product requirements.

## Volume 2: managerial accounting coverage

| Chapter; printed start | Implementation implication | Phase |
| --- | --- | --- |
| 1. Accounting as a Tool for Managers; 11 | Planning, control, evaluation; define users and label internal reports | [01](01-foundation/README.md), [08](08-service-management/README.md) |
| 2. Building Blocks of Managerial Accounting; 65 | Direct/indirect, fixed/variable/mixed costs, drivers and relevant range | [08](08-service-management/README.md) |
| 3. Cost-Volume-Profit Analysis; 117 | Contribution, break-even and sensitivity with explicit assumptions and denominator guards | [08](08-service-management/README.md) |
| 4. Job Order Costing; 169 | Service projects use labor and operating overhead; manufacturing journals are optional | [08](08-service-management/README.md), [10](10-deferred-extensions/README.md) |
| 5. Process Costing; 229 | Equivalent units and departmental cost reconciliation; outside service MVP | [10](10-deferred-extensions/README.md) |
| 6. Activity-Based, Variable, and Absorption Costing; 267 | Document allocation drivers; distinguish management allocations from financial actuals | [08](08-service-management/README.md), [10](10-deferred-extensions/README.md) |
| 7. Budgeting; 315 | Version operating/cash budgets, collections/payment timing and flexible activity levels | [08](08-service-management/README.md) |
| 8. Standard Costs and Variances; 365 | Rate/efficiency and budget variance analysis; never manufacture a causal explanation | [08](08-service-management/README.md), [10](10-deferred-extensions/README.md) |
| 9. Responsibility Accounting and Decentralization; 411 | Cost/profit centers and controllable costs; transfer pricing deferred | [08](08-service-management/README.md), [10](10-deferred-extensions/README.md) |
| 10. Short-Term Decision Making; 459 | Relevant costs, outsourcing and resource-constrained scenarios | [10](10-deferred-extensions/README.md) |
| 11. Capital Budgeting Decisions; 505 | Explicit cash-flow/timing assumptions and independently verified NPV/IRR methods | [10](10-deferred-extensions/README.md) |
| 12. Balanced Scorecard and Other Performance Measures; 553 | Financial and nonfinancial metrics with definitions, provenance and controllability | [08](08-service-management/README.md), [10](10-deferred-extensions/README.md) |
| 13. Sustainability Reporting; 593 | Optional sourced metrics; current framework selection required before reporting claims | [10](10-deferred-extensions/README.md) |

Appendix A (627): financial statement analysis, overlapping V1 Appendix A. Appendix B (639): time-value tables. Appendix C (643): suggested resources. These are reference inputs to the same extensions, not duplicate modules.

## Sections read more closely and resulting decisions

| Source | Printed pages / corresponding PDF pages | Decision |
| --- | --- | --- |
| V1 §3.3 | 114–118 / 128–132 | Preserve source evidence before analysis and journal posting |
| V1 §3.5 | 123–127 / 137–141 | Model debit/credit lines and require balanced totals |
| V1 §3.6 | 146–149 / 160–163 | Test every account as well as total balance; a balanced trial balance can still be wrong |
| V1 §8.6 | 500–502 / 514–516 | Distinguish bank timing differences from new book adjustments |
| V1 §14.4 summary | 823 / 837 | Explicit sample equity model; do not mix owner capital with corporate equity accounts |
| V1 Appendix A selected material | 919–920, 924–925 / 933–934, 938–939 | Ratios/trends require definitions, comparable periods and denominator checks |
| V2 §4.8 | 206–207 / 218–219 | Use hours and operating overhead for the service costing extension |
| V2 §7.3 | 329–331 / 341–343 | Separate revenue budgets from cash collection timing |
| V2 §7.4 | 336–338 / 348–350 | Flex variable costs to actual activity before evaluating variances |

## How the source material is used

The books establish accounting concepts and coverage. Integer cents, transactional persistence, idempotency, revision-bound approvals, tool allowlists, prompt-injection handling, run checkpoints, CI and deployment are engineering decisions proposed for this harness; they are not described as textbook requirements.

Introductory examples and summaries can simplify policies or omit formula details. For example, do not turn a simplified adjustment example into a universal restriction on every correction journal; compute process costs per equivalent unit with the required denominator; rank constrained-resource alternatives by contribution per constrained unit. Implement each selected policy against independent examples and review its authoritative requirements when the actual framework/jurisdiction becomes relevant.

The project does not copy historical tax rates, legal thresholds, reporting-body descriptions or textbook examples into live rules, and does not claim GAAP/IFRS compliance merely because its entries balance. The test data is original; every production policy must be explicit and versioned.

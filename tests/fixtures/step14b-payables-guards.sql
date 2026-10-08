-- Published Step 14b/schema 2 trigger definitions, captured before Step 16c.
-- Synthetic migration fixture; no financial rows.

CREATE TRIGGER bill_approved_operation BEFORE INSERT ON vendor_bills
            WHEN NOT EXISTS (
                SELECT 1 FROM approvals a JOIN draft_revisions r USING(draft_id,revision)
                JOIN draft_operation_intents i USING(draft_id,revision)
                WHERE a.approval_id=NEW.approval_id AND r.policy_version='bill-v1'
                  AND r.state='pending'
                  AND r.revision=(SELECT max(revision) FROM draft_revisions WHERE draft_id=r.draft_id)
                  AND json_extract(a.binding_json,'$.revision_digest')=r.content_digest
                  AND json_extract(r.proposal_json,'$.id')=NEW.journal_id
                  AND json_extract(i.intent_json,'$.kind')='vendor_bill'
                  AND json_extract(i.intent_json,'$.bill_id')=NEW.bill_id
                  AND json_extract(i.intent_json,'$.vendor_id')=NEW.vendor_id
                  AND json_extract(i.intent_json,'$.bill_number')=NEW.bill_number
                  AND json_extract(i.intent_json,'$.recognition_event_id')=NEW.recognition_event_id
                  AND json_extract(i.intent_json,'$.principal_cents')=NEW.principal_cents
                  AND json_extract(i.intent_json,'$.expense_account')=NEW.expense_account
                  AND json_extract(i.intent_json,'$.effective_date')=NEW.effective_date
                  AND json_extract(i.intent_json,'$.due_date')=NEW.due_date
                  AND json_extract(i.intent_json,'$.evidence_roles.bill')=NEW.bill_source_id
                  AND json_extract(i.intent_json,'$.evidence_roles.incurrence')=NEW.incurrence_source_id)
            BEGIN SELECT RAISE(ABORT,'bill effect must match approved operation'); END;

CREATE TRIGGER payment_approved_operation BEFORE INSERT ON vendor_bill_payments
            WHEN NOT EXISTS (
                SELECT 1 FROM approvals a JOIN draft_revisions r USING(draft_id,revision)
                JOIN draft_operation_intents i USING(draft_id,revision)
                JOIN vendor_bills b ON b.bill_id=NEW.bill_id
                WHERE a.approval_id=NEW.approval_id AND r.policy_version='bill-payment-v1'
                  AND r.state='pending'
                  AND r.revision=(SELECT max(revision) FROM draft_revisions WHERE draft_id=r.draft_id)
                  AND json_extract(a.binding_json,'$.revision_digest')=r.content_digest
                  AND json_extract(r.proposal_json,'$.id')=NEW.journal_id
                  AND json_extract(i.intent_json,'$.kind')='vendor_bill_payment'
                  AND json_extract(i.intent_json,'$.bill_id')=NEW.bill_id
                  AND json_extract(i.intent_json,'$.vendor_id')=b.vendor_id
                  AND json_extract(i.intent_json,'$.payment_event_id')=NEW.payment_event_id
                  AND json_extract(i.intent_json,'$.allocated_cents')=NEW.allocated_cents
                  AND json_extract(i.intent_json,'$.effective_date')=NEW.effective_date
                  AND NEW.effective_date>=b.effective_date
                  AND json_extract(i.intent_json,'$.evidence_roles.bill')=b.bill_source_id
                  AND json_extract(i.intent_json,'$.evidence_roles.cash')=NEW.cash_source_id)
            BEGIN SELECT RAISE(ABORT,'payment effect must match approved operation'); END;

CREATE TRIGGER payables_post_guard BEFORE INSERT ON posting_events
            WHEN (EXISTS (SELECT 1 FROM payables_context)
                  AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id AND account='2000'))
                 OR EXISTS (SELECT 1 FROM vendor_bills WHERE journal_id=NEW.journal_id)
                 OR EXISTS (SELECT 1 FROM vendor_bill_payments WHERE journal_id=NEW.journal_id)
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM vendor_bills b JOIN journals j ON j.id=b.journal_id
                    WHERE b.journal_id=NEW.journal_id AND j.effective_date=b.effective_date
                    AND (SELECT count(*) FROM lines WHERE journal_id=NEW.journal_id)=2
                    AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                        AND account='2000' AND side='credit' AND cents=b.principal_cents)
                    AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                        AND account=b.expense_account AND side='debit' AND cents=b.principal_cents)
                    AND (SELECT count(*) FROM journal_sources WHERE journal_id=NEW.journal_id)=2
                    AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=b.bill_source_id)
                    AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=b.incurrence_source_id)
                 ) AND NOT EXISTS (
                    SELECT 1 FROM vendor_bill_payments p JOIN vendor_bills b USING(bill_id)
                    JOIN journals j ON j.id=p.journal_id
                    WHERE p.journal_id=NEW.journal_id AND j.effective_date=p.effective_date
                    AND NOT EXISTS (SELECT 1 FROM vendor_bills WHERE journal_id=NEW.journal_id)
                    AND (SELECT count(*) FROM lines WHERE journal_id=NEW.journal_id)=2
                    AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                        AND account='2000' AND side='debit' AND cents=p.allocated_cents)
                    AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                        AND account='1000' AND side='credit' AND cents=p.allocated_cents)
                    AND (SELECT count(*) FROM journal_sources WHERE journal_id=NEW.journal_id)=2
                    AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=b.bill_source_id)
                    AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=p.cash_source_id)
                ) THEN RAISE(ABORT,'AP posting requires matching approved payable effect; correction workflow required') END;
            END;

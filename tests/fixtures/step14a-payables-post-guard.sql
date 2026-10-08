-- Published Step 14a/schema 1 AP seal. Synthetic migration fixture.
CREATE TRIGGER payables_post_guard BEFORE INSERT ON posting_events
            WHEN (EXISTS (SELECT 1 FROM payables_context)
                  AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id AND account='2000'))
                 OR EXISTS (SELECT 1 FROM vendor_bills WHERE journal_id=NEW.journal_id)
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
                ) THEN RAISE(ABORT,'AP posting requires matching approved payable effect; correction workflow required') END;
            END;

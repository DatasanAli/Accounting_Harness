-- Synthetic Step 05 database, exported before Step 06 implementation.
BEGIN TRANSACTION;
CREATE TABLE accounts (code TEXT PRIMARY KEY) STRICT, WITHOUT ROWID;
INSERT INTO "accounts" VALUES('1000');
INSERT INTO "accounts" VALUES('1100');
INSERT INTO "accounts" VALUES('1200');
INSERT INTO "accounts" VALUES('1500');
INSERT INTO "accounts" VALUES('1590');
INSERT INTO "accounts" VALUES('2000');
INSERT INTO "accounts" VALUES('2100');
INSERT INTO "accounts" VALUES('3000');
INSERT INTO "accounts" VALUES('3100');
INSERT INTO "accounts" VALUES('4000');
INSERT INTO "accounts" VALUES('5000');
INSERT INTO "accounts" VALUES('5100');
INSERT INTO "accounts" VALUES('5200');
CREATE TABLE idempotency (
        entity_id TEXT NOT NULL,
        operation TEXT NOT NULL CHECK (operation = 'post-v1'),
        key TEXT NOT NULL CHECK (length(trim(key)) > 0 AND key = trim(key)),
        digest TEXT NOT NULL CHECK (length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'),
        journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id),
        PRIMARY KEY (entity_id, operation, key),
        FOREIGN KEY (entity_id, journal_id) REFERENCES journals(entity_id, id)
    ) STRICT, WITHOUT ROWID;
INSERT INTO "idempotency" VALUES('demo-service-001','post-v1','original-key','8aa3913c1225aeb88310d4ea399d6b41b977143ba1c3551c9b05dfc70ea7cde0','expense');
CREATE TABLE journal_sources (
        journal_id TEXT NOT NULL REFERENCES journals(id),
        position INTEGER NOT NULL CHECK (position >= 0),
        source_id TEXT NOT NULL REFERENCES sources(id),
        PRIMARY KEY (journal_id, position)
    ) STRICT, WITHOUT ROWID;
INSERT INTO "journal_sources" VALUES('expense',0,'source-T01');
CREATE TABLE journals (
        id TEXT PRIMARY KEY CHECK (length(trim(id)) > 0 AND id = trim(id)),
        entity_id TEXT NOT NULL REFERENCES ledger_context(entity_id),
        currency TEXT NOT NULL CHECK (currency = 'USD'),
        effective_date TEXT NOT NULL CHECK (
            effective_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
        description TEXT NOT NULL CHECK (length(trim(description)) > 0),
        UNIQUE (entity_id, id)
    ) STRICT, WITHOUT ROWID;
INSERT INTO "journals" VALUES('expense','demo-service-001','USD','2026-01-05','Fictional erroneous expense');
CREATE TABLE ledger_context (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        entity_id TEXT NOT NULL UNIQUE CHECK (length(trim(entity_id)) > 0),
        canonical TEXT NOT NULL
    ) STRICT, WITHOUT ROWID;
INSERT INTO "ledger_context" VALUES(1,'demo-service-001','{"catalog":{"accounts":[{"active":true,"classification":"asset","code":"1000","name":"Cash","normal_side":"debit","temporary":false},{"active":true,"classification":"asset","code":"1100","name":"Accounts Receivable","normal_side":"debit","temporary":false},{"active":true,"classification":"asset","code":"1200","name":"Prepaid Insurance","normal_side":"debit","temporary":false},{"active":true,"classification":"asset","code":"1500","name":"Equipment","normal_side":"debit","temporary":false},{"active":true,"classification":"asset","code":"1590","name":"Accumulated Depreciation","normal_side":"credit","temporary":false},{"active":true,"classification":"liability","code":"2000","name":"Accounts Payable","normal_side":"credit","temporary":false},{"active":true,"classification":"liability","code":"2100","name":"Unearned Service Revenue","normal_side":"credit","temporary":false},{"active":true,"classification":"equity","code":"3000","name":"Owner Capital","normal_side":"credit","temporary":false},{"active":true,"classification":"equity","code":"3100","name":"Owner Drawings","normal_side":"debit","temporary":true},{"active":true,"classification":"revenue","code":"4000","name":"Service Revenue","normal_side":"credit","temporary":true},{"active":true,"classification":"expense","code":"5000","name":"Rent Expense","normal_side":"debit","temporary":true},{"active":true,"classification":"expense","code":"5100","name":"Software Expense","normal_side":"debit","temporary":true},{"active":true,"classification":"expense","code":"5200","name":"Insurance Expense","normal_side":"debit","temporary":true}],"currency":"USD","entity_id":"demo-service-001"},"known_source_ids":["source-A01","source-A02","source-C01","source-C02","source-C03","source-T01","source-T02","source-T03","source-T04","source-T05","source-T06","source-T07","source-T08","source-T09"],"period_end":"2026-01-31","period_start":"2026-01-01","report_policy":"unadjusted-zero-opening-v1"}');
CREATE TABLE lines (
        journal_id TEXT NOT NULL REFERENCES journals(id),
        position INTEGER NOT NULL CHECK (position >= 0),
        account TEXT NOT NULL REFERENCES accounts(code),
        side TEXT NOT NULL CHECK (side IN ('debit', 'credit')),
        cents INTEGER NOT NULL CHECK (cents > 0),
        PRIMARY KEY (journal_id, position)
    ) STRICT, WITHOUT ROWID;
INSERT INTO "lines" VALUES('expense',0,'5100','debit',12500);
INSERT INTO "lines" VALUES('expense',1,'1000','credit',12500);
CREATE TABLE posting_events (
        journal_id TEXT PRIMARY KEY REFERENCES journals(id),
        actor_id TEXT NOT NULL CHECK (length(trim(actor_id)) > 0 AND actor_id = trim(actor_id)),
        recorded_at TEXT NOT NULL CHECK (recorded_at GLOB '*T*+00:00'),
        operation TEXT NOT NULL CHECK (operation = 'post-v1')
    ) STRICT, WITHOUT ROWID;
INSERT INTO "posting_events" VALUES('expense','local-operator','2026-09-20T18:22:00.331641+00:00','post-v1');
CREATE TABLE sources (id TEXT PRIMARY KEY) STRICT, WITHOUT ROWID;
INSERT INTO "sources" VALUES('source-A01');
INSERT INTO "sources" VALUES('source-A02');
INSERT INTO "sources" VALUES('source-C01');
INSERT INTO "sources" VALUES('source-C02');
INSERT INTO "sources" VALUES('source-C03');
INSERT INTO "sources" VALUES('source-T01');
INSERT INTO "sources" VALUES('source-T02');
INSERT INTO "sources" VALUES('source-T03');
INSERT INTO "sources" VALUES('source-T04');
INSERT INTO "sources" VALUES('source-T05');
INSERT INTO "sources" VALUES('source-T06');
INSERT INTO "sources" VALUES('source-T07');
INSERT INTO "sources" VALUES('source-T08');
INSERT INTO "sources" VALUES('source-T09');
CREATE TRIGGER journals_no_update
                        BEFORE UPDATE ON journals
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER journals_no_delete
                        BEFORE DELETE ON journals
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER lines_no_update
                        BEFORE UPDATE ON lines
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER lines_no_delete
                        BEFORE DELETE ON lines
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER journal_sources_no_update
                        BEFORE UPDATE ON journal_sources
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER journal_sources_no_delete
                        BEFORE DELETE ON journal_sources
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER posting_events_no_update
                        BEFORE UPDATE ON posting_events
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER posting_events_no_delete
                        BEFORE DELETE ON posting_events
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER idempotency_no_update
                        BEFORE UPDATE ON idempotency
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER idempotency_no_delete
                        BEFORE DELETE ON idempotency
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER ledger_context_no_update
                        BEFORE UPDATE ON ledger_context
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER ledger_context_no_delete
                        BEFORE DELETE ON ledger_context
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER accounts_no_update
                        BEFORE UPDATE ON accounts
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER accounts_no_delete
                        BEFORE DELETE ON accounts
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER sources_no_update
                        BEFORE UPDATE ON sources
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER sources_no_delete
                        BEFORE DELETE ON sources
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END;
CREATE TRIGGER lines_sealed
                    BEFORE INSERT ON lines
                    WHEN EXISTS (SELECT 1 FROM posting_events WHERE journal_id = NEW.journal_id)
                    BEGIN SELECT RAISE(ABORT, 'posted journal is sealed'); END;
CREATE TRIGGER journal_sources_sealed
                    BEFORE INSERT ON journal_sources
                    WHEN EXISTS (SELECT 1 FROM posting_events WHERE journal_id = NEW.journal_id)
                    BEGIN SELECT RAISE(ABORT, 'posted journal is sealed'); END;
CREATE TRIGGER journals_no_replace
                    BEFORE INSERT ON journals WHEN EXISTS (SELECT 1 FROM journals WHERE id = NEW.id)
                    BEGIN SELECT RAISE(ABORT, 'ledger records cannot be replaced'); END;
CREATE TRIGGER posting_events_no_replace
                    BEFORE INSERT ON posting_events WHEN EXISTS (SELECT 1 FROM posting_events WHERE journal_id = NEW.journal_id)
                    BEGIN SELECT RAISE(ABORT, 'ledger records cannot be replaced'); END;
CREATE TRIGGER idempotency_no_replace
                    BEFORE INSERT ON idempotency WHEN EXISTS (SELECT 1 FROM idempotency WHERE journal_id = NEW.journal_id OR (entity_id = NEW.entity_id AND operation = NEW.operation AND key = NEW.key))
                    BEGIN SELECT RAISE(ABORT, 'ledger records cannot be replaced'); END;
CREATE TRIGGER ledger_context_frozen
                    BEFORE INSERT ON ledger_context
                    BEGIN SELECT RAISE(ABORT, 'ledger context is frozen'); END;
CREATE TRIGGER accounts_frozen
                    BEFORE INSERT ON accounts
                    BEGIN SELECT RAISE(ABORT, 'ledger context is frozen'); END;
CREATE TRIGGER sources_frozen
                    BEFORE INSERT ON sources
                    BEGIN SELECT RAISE(ABORT, 'ledger context is frozen'); END;
COMMIT;
PRAGMA user_version = 1;

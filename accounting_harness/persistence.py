"""Atomic SQLite storage for a synthetic local ledger, not an authorization layer."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

from accounting_harness.domain.accounts import AccountCatalog, _validate_text
from accounting_harness.domain.journal import Finding
from accounting_harness.domain.ledger import (
    EntryRejected, InMemoryLedger, LedgerEntry, LedgerLine, LedgerSnapshot, trial_balance,
)
from accounting_harness.domain.money import Money

SCHEMA_VERSION = 1
MAX_CENTS = 2**63 - 1
OPERATION = "post-v1"
RECORD_TABLES = ("journals", "lines", "journal_sources", "posting_events", "idempotency")

# Cross-row balance, active-account and complete calendar/period validation live
# in the admission service. SQL constraints are a second, deliberately smaller layer.
SCHEMA = (
    """CREATE TABLE ledger_context (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        entity_id TEXT NOT NULL UNIQUE CHECK (length(trim(entity_id)) > 0),
        canonical TEXT NOT NULL
    ) STRICT, WITHOUT ROWID""",
    """CREATE TABLE accounts (code TEXT PRIMARY KEY) STRICT, WITHOUT ROWID""",
    """CREATE TABLE sources (id TEXT PRIMARY KEY) STRICT, WITHOUT ROWID""",
    """CREATE TABLE journals (
        id TEXT PRIMARY KEY CHECK (length(trim(id)) > 0 AND id = trim(id)),
        entity_id TEXT NOT NULL REFERENCES ledger_context(entity_id),
        currency TEXT NOT NULL CHECK (currency = 'USD'),
        effective_date TEXT NOT NULL CHECK (
            effective_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
        description TEXT NOT NULL CHECK (length(trim(description)) > 0),
        UNIQUE (entity_id, id)
    ) STRICT, WITHOUT ROWID""",
    """CREATE TABLE lines (
        journal_id TEXT NOT NULL REFERENCES journals(id),
        position INTEGER NOT NULL CHECK (position >= 0),
        account TEXT NOT NULL REFERENCES accounts(code),
        side TEXT NOT NULL CHECK (side IN ('debit', 'credit')),
        cents INTEGER NOT NULL CHECK (cents > 0),
        PRIMARY KEY (journal_id, position)
    ) STRICT, WITHOUT ROWID""",
    """CREATE TABLE journal_sources (
        journal_id TEXT NOT NULL REFERENCES journals(id),
        position INTEGER NOT NULL CHECK (position >= 0),
        source_id TEXT NOT NULL REFERENCES sources(id),
        PRIMARY KEY (journal_id, position)
    ) STRICT, WITHOUT ROWID""",
    """CREATE TABLE posting_events (
        journal_id TEXT PRIMARY KEY REFERENCES journals(id),
        actor_id TEXT NOT NULL CHECK (length(trim(actor_id)) > 0 AND actor_id = trim(actor_id)),
        recorded_at TEXT NOT NULL CHECK (recorded_at GLOB '*T*+00:00'),
        operation TEXT NOT NULL CHECK (operation = 'post-v1')
    ) STRICT, WITHOUT ROWID""",
    """CREATE TABLE idempotency (
        entity_id TEXT NOT NULL,
        operation TEXT NOT NULL CHECK (operation = 'post-v1'),
        key TEXT NOT NULL CHECK (length(trim(key)) > 0 AND key = trim(key)),
        digest TEXT NOT NULL CHECK (length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'),
        journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id),
        PRIMARY KEY (entity_id, operation, key),
        FOREIGN KEY (entity_id, journal_id) REFERENCES journals(entity_id, id)
    ) STRICT, WITHOUT ROWID""",
)


class PersistenceBusy(RuntimeError):
    """SQLite could not acquire a lock within the bounded busy timeout."""


@dataclass(frozen=True, slots=True)
class PostingReceipt:
    entry: LedgerEntry
    actor_id: str
    recorded_at: datetime


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class SQLiteLedger:
    """One entity/catalog/period per file; one connection per thread.

    Each write uses BEGIN IMMEDIATE and SQLite's native bounded busy handler
    (2000 ms by default, at most 60000 ms per lock acquisition). A busy failure
    rolls back; the caller may retry using the same explicit idempotency key.
    Existing files must have schema v1 and exactly the requested frozen context.
    No schema migration, context change, update or deletion API is provided.
    """

    def __init__(
        self, path: str | Path, catalog: AccountCatalog,
        period_start: date | str, period_end: date | str,
        *, known_source_ids: set[str] | frozenset[str], busy_timeout_ms: int = 2000,
    ):
        # Validate/snapshot trusted context before creating any database file.
        empty = InMemoryLedger(catalog, period_start, period_end,
                               known_source_ids=known_source_ids).snapshot
        self._empty = replace(empty, catalog=replace(catalog, accounts=catalog.list_accounts()))
        self._sources = frozenset(known_source_ids)
        if type(busy_timeout_ms) is not int or not 0 <= busy_timeout_ms <= 60000:
            raise ValueError("busy_timeout_ms must be an integer from 0 through 60000")
        self._busy_timeout_ms = busy_timeout_ms
        self._context = _canonical(dict(
            catalog=asdict(self._empty.catalog), period_start=empty.period_start.isoformat(),
            period_end=empty.period_end.isoformat(), known_source_ids=sorted(self._sources),
            report_policy="unadjusted-zero-opening-v1",
        ))
        self._connection = sqlite3.connect(path, timeout=busy_timeout_ms / 1000,
                                           isolation_level=None)
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA synchronous = FULL")
            with self._transaction(write=True):
                self._initialize()
        except BaseException:
            self.close()
            raise

    @contextmanager
    def _transaction(self, *, write=False):
        try:
            self._connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield
            self._connection.commit()
        except BaseException as error:
            self._connection.rollback()
            if (isinstance(error, sqlite3.OperationalError)
                    and getattr(error, "sqlite_errorcode", 0) & 255
                    in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)):
                raise PersistenceBusy(
                    f"database busy; lock wait exhausted ({self._busy_timeout_ms} ms); "
                    "retry with the same idempotency key"
                ) from error
            raise

    def _initialize(self):
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            if self._connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
                raise ValueError("refusing to adopt a nonempty unversioned database")
            # execute(), not executescript(): DDL and context stay in this transaction.
            for statement in SCHEMA:
                self._connection.execute(statement)
            self._connection.execute("INSERT INTO ledger_context VALUES (1, ?, ?)",
                                     (self._empty.catalog.entity_id, self._context))
            self._connection.executemany("INSERT INTO accounts VALUES (?)",
                                         [(a.code,) for a in self._empty.catalog.accounts])
            self._connection.executemany("INSERT INTO sources VALUES (?)",
                                         [(s,) for s in sorted(self._sources)])
            for table in (*RECORD_TABLES, "ledger_context", "accounts", "sources"):
                for action in ("UPDATE", "DELETE"):
                    self._connection.execute(f"""CREATE TRIGGER {table}_no_{action.lower()}
                        BEFORE {action} ON {table}
                        BEGIN SELECT RAISE(ABORT, 'ledger records are append-only'); END""")
            for table in ("lines", "journal_sources"):
                self._connection.execute(f"""CREATE TRIGGER {table}_sealed
                    BEFORE INSERT ON {table}
                    WHEN EXISTS (SELECT 1 FROM posting_events WHERE journal_id = NEW.journal_id)
                    BEGIN SELECT RAISE(ABORT, 'posted journal is sealed'); END""")
            # REPLACE may skip DELETE triggers. Guard its conflicts at INSERT,
            # independently of a caller's recursive_triggers setting.
            conflicts = {
                "journals": "id = NEW.id",
                "posting_events": "journal_id = NEW.journal_id",
                "idempotency": "journal_id = NEW.journal_id OR "
                               "(entity_id = NEW.entity_id AND operation = NEW.operation AND key = NEW.key)",
            }
            for table, condition in conflicts.items():
                self._connection.execute(f"""CREATE TRIGGER {table}_no_replace
                    BEFORE INSERT ON {table} WHEN EXISTS (SELECT 1 FROM {table} WHERE {condition})
                    BEGIN SELECT RAISE(ABORT, 'ledger records cannot be replaced'); END""")
            for table in ("ledger_context", "accounts", "sources"):
                self._connection.execute(f"""CREATE TRIGGER {table}_frozen
                    BEFORE INSERT ON {table}
                    BEGIN SELECT RAISE(ABORT, 'ledger context is frozen'); END""")
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema version: {version}")
        else:
            stored = self._connection.execute(
                "SELECT canonical FROM ledger_context WHERE singleton = 1").fetchone()
            if stored != (self._context,):
                raise ValueError("database context does not match requested entity/catalog/period/sources")

    def admit(self, proposal: object, *, idempotency_key: str, actor_id: str) -> PostingReceipt:
        """Validate and store one entry atomically, or return its original receipt.

        Canonical v1 binds context, operator, operation and every validated field.
        Money/string amounts normalize to cents; date/string values to ISO dates;
        optional matching line currency is equivalent to omission. Ordered lines
        and sources preserve order and duplicates; list/tuple forms are equivalent.
        Recorded time is assigned once by the service and excluded from the digest.
        """
        _validate_text(idempotency_key, "idempotency key")
        _validate_text(actor_id, "actor ID")
        with self._transaction(write=True):
            validator = InMemoryLedger(self._empty.catalog, self._empty.period_start,
                                       self._empty.period_end, known_source_ids=self._sources)
            entry = validator.admit(proposal)
            for index, line in enumerate(entry.lines):
                if line.amount.cents > MAX_CENTS:
                    raise EntryRejected((Finding("storage_overflow", f"lines[{index}].amount",
                                                 f"SQLite line cents must be <= {MAX_CENTS}"),))
            payload = dict(id=entry.id, entity_id=entry.entity_id, currency=entry.currency,
                           effective_date=entry.effective_date.isoformat(),
                           description=entry.description, source_ids=entry.source_ids,
                           lines=[dict(account=l.account, side=l.side, cents=l.amount.cents)
                                  for l in entry.lines])
            digest = hashlib.sha256(_canonical(dict(
                context=self._context, actor_id=actor_id, operation=OPERATION, entry=payload,
            )).encode("utf-8")).hexdigest()
            prior = self._connection.execute(
                "SELECT digest, journal_id FROM idempotency WHERE entity_id=? AND operation=? AND key=?",
                (entry.entity_id, OPERATION, idempotency_key),
            ).fetchone()
            if prior:
                if prior[0] != digest:
                    raise ValueError("idempotency key already binds a different payload or actor")
                return self._receipt(prior[1])
            if self._connection.execute("SELECT 1 FROM journals WHERE id=?", (entry.id,)).fetchone():
                raise EntryRejected((Finding("duplicate_entry_id", "id",
                                             "entry ID already exists in this ledger"),))
            recorded_at = datetime.now(timezone.utc)
            self._connection.execute("INSERT INTO journals VALUES (?, ?, ?, ?, ?)",
                                     (entry.id, entry.entity_id, entry.currency,
                                      entry.effective_date.isoformat(), entry.description))
            self._connection.executemany("INSERT INTO journal_sources VALUES (?, ?, ?)",
                                         [(entry.id, i, source) for i, source in enumerate(entry.source_ids)])
            self._connection.executemany("INSERT INTO lines VALUES (?, ?, ?, ?, ?)",
                                         [(entry.id, i, l.account, l.side, l.amount.cents)
                                          for i, l in enumerate(entry.lines)])
            self._connection.execute("INSERT INTO posting_events VALUES (?, ?, ?, ?)",
                                     (entry.id, actor_id, recorded_at.isoformat(), OPERATION))
            self._connection.execute("INSERT INTO idempotency VALUES (?, ?, ?, ?, ?)",
                                     (entry.entity_id, OPERATION, idempotency_key, digest, entry.id))
            return PostingReceipt(entry, actor_id, recorded_at)

    def _entry(self, row) -> LedgerEntry:
        entry_id, entity, currency, effective_date, description = row
        sources = self._connection.execute(
            "SELECT source_id FROM journal_sources WHERE journal_id=? ORDER BY position",
            (entry_id,),
        ).fetchall()
        lines = self._connection.execute(
            "SELECT account, side, cents FROM lines WHERE journal_id=? ORDER BY position",
            (entry_id,),
        ).fetchall()
        return LedgerEntry(entry_id, entity, currency, date.fromisoformat(effective_date),
                           description, tuple(s[0] for s in sources),
                           tuple(LedgerLine(account, side, Money(cents)) for account, side, cents in lines))

    def _receipt(self, entry_id: str) -> PostingReceipt:
        entry = self._entry(self._connection.execute(
            "SELECT id, entity_id, currency, effective_date, description FROM journals WHERE id=?",
            (entry_id,),
        ).fetchone())
        actor, recorded_at = self._connection.execute(
            "SELECT actor_id, recorded_at FROM posting_events WHERE journal_id=?", (entry_id,),
        ).fetchone()
        return PostingReceipt(entry, actor, datetime.fromisoformat(recorded_at))

    @property
    def snapshot(self) -> LedgerSnapshot:
        # ponytail: load all entries for local fixtures; add bounded queries when scale requires it.
        with self._transaction():
            rows = self._connection.execute(
                "SELECT id, entity_id, currency, effective_date, description FROM journals "
                "ORDER BY effective_date, id").fetchall()
            return replace(self._empty, entries=tuple(self._entry(row) for row in rows))

    def trial_balance(self, as_of: date | str):
        return trial_balance(self.snapshot, as_of)

    def counts(self) -> dict[str, int]:
        with self._transaction():
            return {table: self._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                    for table in RECORD_TABLES}

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

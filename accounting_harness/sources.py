"""Immutable synthetic receipt registration, separate from ledger posting."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from accounting_harness.domain.accounts import _validate_text
from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.money import Money
from accounting_harness.persistence import PersistenceBusy, _canonical

SCHEMA_VERSION = 1
APPLICATION_ID = 0x41485352  # AHSR: Accounting Harness Source Registry, not a ledger file.
_FIELDS = frozenset(("schema_version", "synthetic", "entity_id", "document_id", "kind",
                     "document_date", "currency", "amount", "counterparty", "description"))


def load_source_document(path: str | Path) -> dict:
    """Decode a structured JSON source without silently accepting duplicate keys."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    document = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(document, dict):
        raise TypeError("source document must be a JSON object")
    return document


def _content(document: object, entity_id: str) -> tuple[str, str]:
    if not isinstance(document, dict):
        raise TypeError("source document must be a JSON object")
    if document.keys() != _FIELDS:
        raise ValueError("source document must contain exactly the required fields")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported source document schema_version")
    if document["synthetic"] is not True:
        raise ValueError("only synthetic source documents are supported")
    for field in ("entity_id", "document_id", "kind", "document_date", "counterparty", "description"):
        _validate_text(document[field], field)
    if document["entity_id"] != entity_id:
        raise ValueError("source document belongs to a different entity")
    if document["kind"] != "receipt":
        raise ValueError("only receipt documents are supported")
    accounting_date(document["document_date"])
    amount = Money.parse(document["amount"], document["currency"])
    if amount.cents == 0:
        raise ValueError("source amount must be positive")
    content = {key: value for key, value in document.items()
               if key not in ("entity_id", "document_id")}
    content["amount"] = str(amount)
    return document["document_id"], _canonical(content)


@dataclass(frozen=True, slots=True)
class SourceRecord:
    entity_id: str
    document_id: str
    content_digest: str
    canonical_content: str
    actor_id: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class ImportResult:
    record: SourceRecord
    repeated: bool


class SQLiteSourceRegistry:
    """One entity per separate registry file; one connection per thread.

    Identity is the import retry key. Repeated content under another identity
    stays separate. No ledger mutation, approval, or authentication is provided.
    """

    def __init__(self, path: str | Path, entity_id: str, *, busy_timeout_ms: int = 2000):
        _validate_text(entity_id, "entity ID")
        if type(busy_timeout_ms) is not int or not 0 <= busy_timeout_ms <= 60000:
            raise ValueError("busy_timeout_ms must be an integer from 0 through 60000")
        self._entity_id = entity_id
        self._busy_timeout_ms = busy_timeout_ms
        self._connection = sqlite3.connect(path, timeout=busy_timeout_ms / 1000,
                                           isolation_level=None)
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA synchronous = FULL")
            with self._transaction():
                self._initialize()
        except BaseException:
            self.close()
            raise

    @contextmanager
    def _transaction(self):
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
            self._connection.commit()
        except BaseException as error:
            self._connection.rollback()
            if (isinstance(error, sqlite3.OperationalError)
                    and getattr(error, "sqlite_errorcode", 0) & 255
                    in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)):
                raise PersistenceBusy(
                    f"source database busy; lock wait exhausted ({self._busy_timeout_ms} ms); "
                    "retry with the same document identity and content"
                ) from error
            raise

    def _initialize(self):
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        application = self._connection.execute("PRAGMA application_id").fetchone()[0]
        if version == SCHEMA_VERSION and application == APPLICATION_ID:
            stored = self._connection.execute("SELECT entity_id FROM registry_context").fetchall()
            if stored != [(self._entity_id,)]:
                raise ValueError("registry entity does not match requested entity")
            return
        if version or application:
            raise ValueError(f"unsupported source registry schema/application: {version}/{application}")
        if self._connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
            raise ValueError("refusing to adopt a nonempty unversioned database")
        self._connection.execute("""CREATE TABLE registry_context (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            entity_id TEXT NOT NULL UNIQUE CHECK (length(trim(entity_id)) > 0)
        ) STRICT, WITHOUT ROWID""")
        self._connection.execute("INSERT INTO registry_context VALUES (1, ?)", (self._entity_id,))
        self._connection.execute("""CREATE TABLE source_documents (
            entity_id TEXT NOT NULL REFERENCES registry_context(entity_id),
            document_id TEXT NOT NULL CHECK (length(trim(document_id)) > 0 AND document_id = trim(document_id)),
            content_digest TEXT NOT NULL CHECK (
                length(content_digest) = 64 AND content_digest NOT GLOB '*[^0-9a-f]*'),
            canonical_content TEXT NOT NULL CHECK (length(canonical_content) > 0),
            PRIMARY KEY (entity_id, document_id)
        ) STRICT, WITHOUT ROWID""")
        self._connection.execute("""CREATE TABLE registration_events (
            entity_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            actor_id TEXT NOT NULL CHECK (length(trim(actor_id)) > 0 AND actor_id = trim(actor_id)),
            recorded_at TEXT NOT NULL CHECK (recorded_at GLOB '*T*+00:00'),
            operation TEXT NOT NULL CHECK (operation = 'register-source-v1'),
            PRIMARY KEY (entity_id, document_id),
            FOREIGN KEY (entity_id, document_id) REFERENCES source_documents(entity_id, document_id)
        ) STRICT, WITHOUT ROWID""")
        for table in ("registry_context", "source_documents", "registration_events"):
            for action in ("UPDATE", "DELETE"):
                self._connection.execute(f"""CREATE TRIGGER {table}_no_{action.lower()}
                    BEFORE {action} ON {table}
                    BEGIN SELECT RAISE(ABORT, 'source records are append-only'); END""")
            condition = ("1" if table == "registry_context" else
                         "entity_id = NEW.entity_id AND document_id = NEW.document_id")
            self._connection.execute(f"""CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table}
                WHEN EXISTS (SELECT 1 FROM {table} WHERE {condition})
                BEGIN SELECT RAISE(ABORT, 'source records cannot be replaced'); END""")
        self._connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def register(self, document: object, *, actor_id: str) -> ImportResult:
        """Register once; changed content under an existing identity is an error."""
        _validate_text(actor_id, "actor ID")
        document_id, canonical = _content(document, self._entity_id)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self._transaction():
            prior = self._connection.execute(
                "SELECT canonical_content FROM source_documents WHERE entity_id=? AND document_id=?",
                (self._entity_id, document_id)).fetchone()
            if prior:
                # Compare the content itself, so even a digest collision cannot overwrite evidence.
                if prior[0] != canonical:
                    raise ValueError("document identity already binds different content")
                return ImportResult(self.get(document_id), repeated=True)
            self._connection.execute("INSERT INTO source_documents VALUES (?, ?, ?, ?)",
                                     (self._entity_id, document_id, digest, canonical))
            self._connection.execute("INSERT INTO registration_events VALUES (?, ?, ?, ?, ?)",
                                     (self._entity_id, document_id, actor_id,
                                      datetime.now(timezone.utc).isoformat(), "register-source-v1"))
            return ImportResult(self.get(document_id), repeated=False)

    def get(self, document_id: str) -> SourceRecord:
        _validate_text(document_id, "document ID")
        row = self._connection.execute("""SELECT d.entity_id, d.document_id, d.content_digest,
            d.canonical_content, e.actor_id, e.recorded_at
            FROM source_documents d JOIN registration_events e USING (entity_id, document_id)
            WHERE d.entity_id=? AND d.document_id=?""", (self._entity_id, document_id)).fetchone()
        if row is None:
            raise KeyError(document_id)
        return SourceRecord(*row[:5], datetime.fromisoformat(row[5]))

    def counts(self) -> dict[str, int]:
        # One statement gives a consistent snapshot even during another connection's import.
        row = self._connection.execute("""SELECT
            (SELECT count(*) FROM source_documents),
            (SELECT count(*) FROM registration_events)""").fetchone()
        return dict(zip(("documents", "registration_events"), row))

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

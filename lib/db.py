"""Postgres in production, SQLite locally.

Accounts need to survive a deploy, and Vercel's filesystem does not. The
DATABASE_URL the Neon integration writes is used when present; without it the
app falls back to a SQLite file so `python3 app.py` and the tests still work
offline.

The SQL below stays inside what both engines understand. `%s` is translated to
`?` for SQLite, and `FOR UPDATE` is only added on Postgres because SQLite
serialises writers with BEGIN IMMEDIATE instead.
"""

import os
import sqlite3
import ssl
import threading
from contextlib import contextmanager
from urllib.parse import unquote, urlsplit

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS iml_users (
        username   TEXT PRIMARY KEY,
        display    TEXT NOT NULL,
        salt       TEXT NOT NULL,
        hash       TEXT NOT NULL,
        iterations INTEGER NOT NULL,
        created    BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS iml_sessions (
        token    TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        expires  BIGINT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS iml_sessions_expires ON iml_sessions (expires)",
    """CREATE TABLE IF NOT EXISTS iml_state (
        username TEXT PRIMARY KEY,
        rev      INTEGER NOT NULL,
        updated  BIGINT NOT NULL,
        state    TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS iml_throttle (
        k     TEXT PRIMARY KEY,
        n     INTEGER NOT NULL,
        until BIGINT NOT NULL
    )""",
)

_store = None
_lock = threading.Lock()


def _is_postgres(url):
    return url.startswith("postgres://") or url.startswith("postgresql://")


def _sqlite_path(url):
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
    elif url.startswith("sqlite://"):
        path = url[len("sqlite://"):]
    else:
        path = os.environ.get("IML_DB_PATH") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".data", "iml.db")
    path = os.path.abspath(os.path.expanduser(path))
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


class _Conn:
    def __init__(self, raw, dialect):
        self.raw = raw
        self.dialect = dialect

    def run(self, sql, params=()):
        if self.dialect == "sqlite":
            sql = sql.replace("%s", "?")
        cur = self.raw.cursor()
        try:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() if cur.description else []
        finally:
            cur.close()
        return [tuple(row) for row in rows]

    def commit(self):
        if self.dialect == "sqlite":
            if self.raw.in_transaction:
                self.raw.execute("COMMIT")
        else:
            self.raw.commit()

    def rollback(self):
        if self.dialect == "sqlite":
            if self.raw.in_transaction:
                self.raw.execute("ROLLBACK")
        else:
            self.raw.rollback()

    def close(self):
        try:
            self.raw.close()
        except Exception:
            pass


class Store:
    def __init__(self, url):
        self.url = url
        self.dialect = "postgres" if _is_postgres(url) else "sqlite"
        self.path = None if self.dialect == "postgres" else _sqlite_path(url)
        self._schema = False

    def connect(self):
        if self.dialect == "sqlite":
            raw = sqlite3.connect(self.path, timeout=15, isolation_level=None)
            raw.execute("PRAGMA busy_timeout = 15000")
            return _Conn(raw, "sqlite")

        import pg8000

        parts = urlsplit(self.url)
        raw = pg8000.connect(
            user=unquote(parts.username or "postgres"),
            password=unquote(parts.password or ""),
            host=parts.hostname or "localhost",
            port=parts.port or 5432,
            database=(parts.path or "/postgres").lstrip("/") or "postgres",
            ssl_context=ssl.create_default_context(),
            timeout=10,
        )
        return _Conn(raw, "postgres")

    def ensure_schema(self, conn=None):
        if self._schema:
            return
        own = conn is None
        conn = conn or self.connect()
        try:
            for statement in SCHEMA:
                conn.run(statement)
            if not own:
                return
            conn.commit()
            self._schema = True
        finally:
            if own:
                conn.close()

    @contextmanager
    def tx(self):
        conn = self.connect()
        try:
            if self.dialect == "sqlite":
                conn.raw.execute("BEGIN IMMEDIATE")
            self.ensure_schema(conn)
            yield conn
            conn.commit()
            if self.dialect == "postgres":
                self._schema = True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def query(self, sql, params=()):
        conn = self.connect()
        try:
            self.ensure_schema(conn)
            rows = conn.run(sql, params)
            conn.rollback()
            return rows
        finally:
            conn.close()

    def run(self, sql, params=()):
        with self.tx() as conn:
            return conn.run(sql, params)


def store():
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                url = next(
                    (os.environ.get(key, "").strip()
                     for key in ("DATABASE_URL", "POSTGRES_URL",
                                 "POSTGRES_URL_NON_POOLING",
                                 "POSTGRES_PRISMA_URL")
                     if os.environ.get(key, "").strip()),
                    "")
                _store = Store(url)
    return _store


def reset():
    """Tests only: forget the cached connection settings."""
    global _store
    _store = None

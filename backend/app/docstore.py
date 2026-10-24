"""Where the app keeps its three small documents: reports.csv, users.json, .token_secret.

* Default: plain files in DATA_DIR (Docker, a VM, local development).
* With DATABASE_URL set (e.g. a free Neon/Supabase Postgres): one row per document in the
  table ``soilboring_documents``. This is for hosts whose disk is not kept between requests,
  such as Vercel or Render's free tier.

The rest of the app only uses ``read_text``, ``write_text``, ``delete`` and ``lock``. A lock
covers a whole read-modify-write: a process-wide lock for files, a Postgres advisory lock
(held until the transaction commits) for the database, so several serverless instances
cannot overwrite each other's changes.
"""
from __future__ import annotations

import atexit
import contextlib
import contextvars
import os
import pathlib
import tempfile
import threading
from typing import Any, Dict, Iterator, Optional

DATABASE_URL = (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "").strip()
USE_DATABASE = DATABASE_URL.startswith(("postgres://", "postgresql://"))

DATA_PATH = pathlib.Path(os.environ.get("DATA_DIR", "data"))
if not USE_DATABASE:
    DATA_PATH.mkdir(parents=True, exist_ok=True)

TABLE = "soilboring_documents"

# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #

_FILE_LOCKS: Dict[str, threading.RLock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def path_for(name: str) -> pathlib.Path:
    return DATA_PATH / name


def _default_mode(path: pathlib.Path) -> int:
    """Keep an existing file's permissions; new data files are readable (0644) like before."""
    try:
        return os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def _match_owner(tmp_name: str, path: pathlib.Path) -> None:
    """When running as root (e.g. ``docker compose exec`` of the CLI), give the new file
    to the owner of the data folder, so the unprivileged app can still read it."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    try:
        owner = os.stat(path) if path.exists() else os.stat(path.parent)
        os.chown(tmp_name, owner.st_uid, owner.st_gid)
    except OSError:
        pass


def atomic_write_file(path: pathlib.Path, content: str, *, mode: Optional[int] = None) -> None:
    """Write ``content`` to ``path`` atomically (never leaves a partial file).

    ``mode`` is for sensitive files (users.json, the token secret); other files keep
    their current permissions so host-side backups and spreadsheets can still read them.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = _default_mode(path)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        _match_owner(tmp_name, path)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


# --------------------------------------------------------------------------- #
# Postgres
# --------------------------------------------------------------------------- #

# The connection of the transaction that currently holds a lock (per thread/request).
_current: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("docstore_tx", default=None)
_schema_ready = False
_schema_guard = threading.Lock()


_pool: Any = None
_pool_guard = threading.Lock()


def _get_pool():
    """A small connection pool: opening a TLS connection to a hosted database costs
    several round trips, so connections are reused between requests."""
    global _pool
    if _pool is None:
        with _pool_guard:
            if _pool is None:
                from psycopg_pool import ConnectionPool  # only needed in database mode

                _pool = ConnectionPool(
                    DATABASE_URL,
                    min_size=1,
                    max_size=int(os.environ.get("DB_POOL_SIZE", "5")),
                    # prepare_threshold=None: works behind transaction-pooling proxies
                    # (Neon "-pooler" endpoints, Supabase, PgBouncer).
                    kwargs={"autocommit": False, "prepare_threshold": None, "connect_timeout": 10},
                    # Hosted databases close idle connections (Neon suspends after a few
                    # minutes): test each connection before use and drop idle ones early.
                    check=ConnectionPool.check_connection,
                    max_idle=240,
                    open=True,
                )
                atexit.register(close_pool)
    return _pool


def close_pool() -> None:
    global _pool
    with _pool_guard:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextlib.contextmanager
def _pooled() -> Iterator[Any]:
    pool = _get_pool()
    conn = pool.getconn()
    try:
        _ensure_schema(conn)
        yield conn
    finally:
        pool.putconn(conn)  # rolls back anything left uncommitted


def _ensure_schema(conn) -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_guard:
        if _schema_ready:
            return
        # Serialise CREATE TABLE between processes starting at the same time; a plain
        # "IF NOT EXISTS" can still fail with a duplicate type when two run at once.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{TABLE}:schema",))
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {TABLE} ("
            " name text PRIMARY KEY,"
            " content text NOT NULL,"
            " updated_at timestamptz NOT NULL DEFAULT now())"
        )
        conn.commit()
        _schema_ready = True


@contextlib.contextmanager
def _connection() -> Iterator[Any]:
    """The locked transaction's connection if there is one, else a pooled one."""
    tx = _current.get()
    if tx is not None:
        yield tx["conn"]
        return
    with _pooled() as conn:
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def read_text(name: str) -> Optional[str]:
    """The document's text, or None when it does not exist yet."""
    if not USE_DATABASE:
        path = path_for(name)
        if not path.exists():
            return None
        # utf-8-sig also accepts files saved by Excel as "CSV UTF-8" (with a BOM).
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return handle.read()
    with _connection() as conn:
        row = conn.execute(f"SELECT content FROM {TABLE} WHERE name = %s", (name,)).fetchone()
    if row is None:
        return None
    text = row[0]
    return text[1:] if text.startswith("﻿") else text


def write_text(name: str, content: str, *, private: bool = False) -> None:
    if not USE_DATABASE:
        atomic_write_file(path_for(name), content, mode=0o600 if private else None)
        return
    with _connection() as conn:
        conn.execute(
            f"INSERT INTO {TABLE} (name, content, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (name) DO UPDATE SET content = EXCLUDED.content, updated_at = now()",
            (name, content),
        )


def delete(name: str) -> None:
    if not USE_DATABASE:
        with contextlib.suppress(FileNotFoundError):
            path_for(name).unlink()
        return
    with _connection() as conn:
        conn.execute(f"DELETE FROM {TABLE} WHERE name = %s", (name,))


@contextlib.contextmanager
def lock(name: str) -> Iterator[None]:
    """Hold an exclusive, re-entrant lock on one document for a read-modify-write."""
    if not USE_DATABASE:
        with _FILE_LOCKS_GUARD:
            file_lock = _FILE_LOCKS.setdefault(name, threading.RLock())
        with file_lock:
            yield
        return

    tx = _current.get()
    if tx is not None:
        # Re-entrant: one transaction may lock several documents (e.g. users + secret).
        if name not in tx["locks"]:
            tx["conn"].execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{TABLE}:{name}",))
            tx["locks"].add(name)
        yield
        return

    with _pooled() as conn:
        token = _current.set({"conn": conn, "locks": {name}})
        try:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{TABLE}:{name}",))
            yield
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            _current.reset(token)


def reset_all_for_tests() -> None:
    """Remove every document (test helper)."""
    for name in ("reports.csv", "users.json", ".token_secret"):
        delete(name)

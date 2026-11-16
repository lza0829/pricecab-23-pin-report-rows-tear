from __future__ import annotations

import sqlite3
from typing import Any


def next_batch_no(conn: sqlite3.Connection) -> str:
    n = conn.execute("SELECT COUNT(*) c FROM apply_batches").fetchone()["c"] + 1
    return f"AB-{n:04d}"


def create_batch(
    conn: sqlite3.Connection,
    *,
    batch_no: str,
    clock_at: str,
    ticket_count: int,
    line_count: int,
    status: str,
    created_at: str,
) -> int:
    cur = conn.execute(
        '''
        INSERT INTO apply_batches(batch_no, clock_at, ticket_count, line_count, status, created_at)
        VALUES (?,?,?,?,?,?)
        ''',
        (batch_no, clock_at, ticket_count, line_count, status, created_at),
    )
    return int(cur.lastrowid)


def list_batches(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM apply_batches ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_rejection(
    conn: sqlite3.Connection,
    *,
    batch_id: int,
    ticket_id: int,
    ticket_no: str,
    sku_code: str,
    reason: str,
    created_at: str,
) -> None:
    conn.execute(
        '''
        INSERT INTO apply_rejections(batch_id, ticket_id, ticket_no, sku_code, reason, created_at)
        VALUES (?,?,?,?,?,?)
        ''',
        (batch_id, ticket_id, ticket_no, sku_code, reason, created_at),
    )


def list_rejections(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM apply_rejections ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]

from __future__ import annotations

import sqlite3
from typing import Any


def list_book(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        '''
        SELECT b.*, s.title, s.category
        FROM price_book b
        JOIN skus s ON s.sku_code = b.sku_code
        ORDER BY b.sku_code
        '''
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_book(
    conn: sqlite3.Connection,
    *,
    sku_code: str,
    price: float,
    ticket_no: str,
    effective_at: str,
    updated_at: str,
) -> None:
    conn.execute(
        '''
        INSERT INTO price_book(sku_code, current_price, source_ticket_no, effective_at, updated_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(sku_code) DO UPDATE SET
          current_price=excluded.current_price,
          source_ticket_no=excluded.source_ticket_no,
          effective_at=excluded.effective_at,
          updated_at=excluded.updated_at
        ''',
        (sku_code, price, ticket_no, effective_at, updated_at),
    )
    conn.execute(
        '''
        INSERT INTO price_history(sku_code, price, source_ticket_no, effective_at, recorded_at)
        VALUES (?,?,?,?,?)
        ''',
        (sku_code, price, ticket_no, effective_at, updated_at),
    )


def list_history(conn: sqlite3.Connection, sku_code: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if sku_code:
        rows = conn.execute(
            "SELECT * FROM price_history WHERE sku_code=? ORDER BY id DESC LIMIT ?",
            (sku_code, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM price_history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def price_at(conn: sqlite3.Connection, sku_code: str, at: str) -> float | None:
    row = conn.execute(
        '''
        SELECT price FROM price_history
        WHERE sku_code=? AND effective_at <= ?
        ORDER BY effective_at DESC, id DESC
        LIMIT 1
        ''',
        (sku_code, at),
    ).fetchone()
    return float(row["price"]) if row else None

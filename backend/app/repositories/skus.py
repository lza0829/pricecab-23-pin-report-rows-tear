from __future__ import annotations

import sqlite3
from typing import Any


def list_skus(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        '''
        SELECT s.id, s.sku_code, s.title, s.category, s.list_price, s.enabled,
               b.current_price, b.source_ticket_no, b.effective_at AS price_effective_at
        FROM skus s
        LEFT JOIN price_book b ON b.sku_code = s.sku_code
        ORDER BY s.sku_code
        '''
    ).fetchall()
    return [dict(r) for r in rows]


def get_by_code(conn: sqlite3.Connection, sku_code: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM skus WHERE sku_code=?", (sku_code,)).fetchone()
    return dict(row) if row else None

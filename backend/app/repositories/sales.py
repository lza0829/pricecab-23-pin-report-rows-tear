from __future__ import annotations

import sqlite3
from typing import Any


def list_sales(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM sales_fixture ORDER BY sold_at, id"
    ).fetchall()
    return [dict(r) for r in rows]

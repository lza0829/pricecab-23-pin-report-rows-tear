from __future__ import annotations

import sqlite3
from typing import Any

# 冻结对账报告（钉扎报告）持久化。报告头与钉扎行只能经 service 层同事务写入；
# 本层不做任何现场重算，读路径只返回已物化的钉扎数据。


def next_report_no(conn: sqlite3.Connection) -> str:
    n = conn.execute("SELECT COUNT(*) c FROM frozen_reports").fetchone()["c"] + 1
    return f"FR-{n:04d}"


def create_report(conn: sqlite3.Connection, **fields: Any) -> int:
    cols = [
        "report_no", "pinned_clock", "pin_watermark", "status",
        "sale_count", "match_count", "mismatch_count", "missing_count",
        "row_count", "created_at", "materialized_at",
    ]
    cur = conn.execute(
        f"INSERT INTO frozen_reports({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        tuple(fields.get(c) for c in cols),
    )
    return int(cur.lastrowid)


def add_row(conn: sqlite3.Connection, report_id: int, **row: Any) -> None:
    conn.execute(
        '''
        INSERT INTO frozen_report_rows(
          report_id, sale_no, sku_code, sold_at, unit_price, qty,
          expected_price, delta, status
        ) VALUES (?,?,?,?,?,?,?,?,?)
        ''',
        (
            report_id,
            row["sale_no"],
            row["sku_code"],
            row["sold_at"],
            float(row["unit_price"]),
            int(row["qty"]),
            row.get("expected_price"),
            row.get("delta"),
            row["status"],
        ),
    )


def replace_rows(conn: sqlite3.Connection, report_id: int, rows: list[dict[str, Any]]) -> None:
    """整批重建钉扎行（仅 rematerialize 收口使用，与头部计数更新同事务）。"""
    conn.execute("DELETE FROM frozen_report_rows WHERE report_id=?", (report_id,))
    for row in rows:
        add_row(conn, report_id, **row)


def set_materialization(
    conn: sqlite3.Connection,
    report_id: int,
    *,
    sale_count: int,
    match_count: int,
    mismatch_count: int,
    missing_count: int,
    row_count: int,
    materialized_at: str,
) -> None:
    """物化完成落账：头部计数必须与同事务写入的钉扎行同源。"""
    conn.execute(
        '''
        UPDATE frozen_reports
        SET sale_count=?, match_count=?, mismatch_count=?, missing_count=?,
            row_count=?, materialized_at=?
        WHERE id=?
        ''',
        (
            sale_count,
            match_count,
            mismatch_count,
            missing_count,
            row_count,
            materialized_at,
            report_id,
        ),
    )


def set_status(conn: sqlite3.Connection, report_id: int, status: str) -> None:
    conn.execute("UPDATE frozen_reports SET status=? WHERE id=?", (status, report_id))


def supersede_others(conn: sqlite3.Connection, report_id: int) -> None:
    """现行资格唯一：新报告物化完成标现行后，其余报告退位为 superseded。"""
    conn.execute(
        "UPDATE frozen_reports SET status='superseded' WHERE status='current' AND id<>?",
        (report_id,),
    )


def get_report(conn: sqlite3.Connection, report_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM frozen_reports WHERE id=?", (report_id,)).fetchone()
    return dict(row) if row else None


def get_current(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM frozen_reports WHERE status='current' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def list_reports(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM frozen_reports ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def list_rows(conn: sqlite3.Connection, report_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM frozen_report_rows WHERE report_id=? ORDER BY sold_at, id",
        (report_id,),
    ).fetchall()
    return [dict(r) for r in rows]

from __future__ import annotations

import sqlite3
from typing import Any


def next_report_no(conn: sqlite3.Connection) -> str:
    n = conn.execute("SELECT COUNT(*) c FROM reconcile_reports").fetchone()["c"] + 1
    return f"RR-{n:04d}"


def create_report(conn: sqlite3.Connection, **fields: Any) -> int:
    cols = [
        "report_no", "created_at", "business_clock",
        "window_mode", "window_start", "window_end",
        "rel_start_hours", "rel_end_hours",
        "resolved_start", "resolved_end",
        "outside_policy", "mismatch_policy",
        "sale_count", "excluded_count", "in_window_count",
        "match_count", "mismatch_count", "missing_count",
    ]
    cur = conn.execute(
        f"INSERT INTO reconcile_reports({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        tuple(fields.get(c) for c in cols),
    )
    return int(cur.lastrowid)


def add_row(conn: sqlite3.Connection, report_id: int, **row: Any) -> None:
    conn.execute(
        '''
        INSERT INTO reconcile_report_rows(
          report_id, sale_no, sku_code, sold_at, unit_price, qty,
          in_window, expected_price, delta, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ''',
        (
            report_id,
            row["sale_no"],
            row["sku_code"],
            row["sold_at"],
            float(row["unit_price"]),
            int(row["qty"]),
            1 if row["in_window"] else 0,
            row.get("expected_price"),
            row.get("delta"),
            row["status"],
        ),
    )


def list_reports(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM reconcile_reports ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_report(conn: sqlite3.Connection, report_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM reconcile_reports WHERE id=?", (report_id,)
    ).fetchone()
    return dict(row) if row else None


def list_rows(conn: sqlite3.Connection, report_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM reconcile_report_rows WHERE report_id=? ORDER BY sold_at, id",
        (report_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def create_flag_if_absent(conn: sqlite3.Connection, **flag: Any) -> None:
    """同一销售号的不一致只立一次旗标；已处置的不因重跑对账而复开。"""
    conn.execute(
        '''
        INSERT OR IGNORE INTO reconcile_flags(
          sale_no, sku_code, report_id, expected_price, unit_price, delta, status, created_at
        ) VALUES (?,?,?,?,?,?, 'open', ?)
        ''',
        (
            flag["sale_no"],
            flag["sku_code"],
            flag["report_id"],
            flag.get("expected_price"),
            float(flag["unit_price"]),
            flag.get("delta"),
            flag["created_at"],
        ),
    )


def list_flags(conn: sqlite3.Connection, status: str | None = None) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            "SELECT * FROM reconcile_flags WHERE status=? ORDER BY id DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM reconcile_flags ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_flag(conn: sqlite3.Connection, flag_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM reconcile_flags WHERE id=?", (flag_id,)).fetchone()
    return dict(row) if row else None


def resolve_flag(conn: sqlite3.Connection, flag_id: int, *, resolved_at: str, note: str | None) -> None:
    conn.execute(
        "UPDATE reconcile_flags SET status='resolved', resolved_at=?, resolve_note=? WHERE id=?",
        (resolved_at, note, flag_id),
    )


def open_flag_skus(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT sku_code FROM reconcile_flags WHERE status='open'"
    ).fetchall()
    return {r["sku_code"] for r in rows}


def open_flag_map(conn: sqlite3.Connection) -> dict[str, int]:
    """sku_code -> 最小未处置旗标 id，用于拒绝原因溯源。"""
    rows = conn.execute(
        "SELECT sku_code, MIN(id) AS fid FROM reconcile_flags WHERE status='open' GROUP BY sku_code"
    ).fetchall()
    return {r["sku_code"]: int(r["fid"]) for r in rows}

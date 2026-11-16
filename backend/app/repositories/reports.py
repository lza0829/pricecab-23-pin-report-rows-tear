from __future__ import annotations

import sqlite3
from typing import Any


def next_report_no(conn: sqlite3.Connection) -> str:
    n = conn.execute("SELECT COUNT(*) c FROM reconcile_reports").fetchone()["c"] + 1
    return f"RR-{n:04d}"


def create_report(
    conn: sqlite3.Connection,
    *,
    report_no: str,
    pinned_clock: str,
    pin_watermark: str,
    status: str,
    match_count: int,
    mismatch_count: int,
    missing_count: int,
    created_at: str,
) -> int:
    cur = conn.execute(
        '''
        INSERT INTO reconcile_reports(
          report_no, pinned_clock, pin_watermark, status,
          match_count, mismatch_count, missing_count, created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        ''',
        (
            report_no,
            pinned_clock,
            pin_watermark,
            status,
            match_count,
            mismatch_count,
            missing_count,
            created_at,
        ),
    )
    return int(cur.lastrowid)


def add_row(conn: sqlite3.Connection, **fields: Any) -> None:
    conn.execute(
        '''
        INSERT INTO reconcile_report_rows(
          report_id, sale_no, sku_code, status, expected_price, unit_price
        ) VALUES (?,?,?,?,?,?)
        ''',
        (
            fields["report_id"],
            fields.get("sale_no"),
            fields.get("sku_code"),
            fields.get("status"),
            fields.get("expected_price"),
            fields.get("unit_price"),
        ),
    )


def list_reports(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM reconcile_reports ORDER BY id DESC").fetchall()]


def get_report(conn: sqlite3.Connection, report_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM reconcile_reports WHERE id=?", (report_id,)).fetchone()
    return dict(row) if row else None


def list_rows(conn: sqlite3.Connection, report_id: int) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM reconcile_report_rows WHERE report_id=? ORDER BY id",
            (report_id,),
        ).fetchall()
    ]

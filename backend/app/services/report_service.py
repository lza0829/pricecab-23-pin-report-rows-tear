from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.db import connect
from app.repositories import reports as report_repo
from app.repositories import settings as settings_repo
from app.services import reconcile_service


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def freeze_report() -> dict[str, Any]:
    conn = connect(immediate=True)
    try:
        clock = settings_repo.get(conn, "business_clock") or ""
        live = reconcile_service.reconcile_sales()
        rid = report_repo.create_report(
            conn,
            report_no=report_repo.next_report_no(conn),
            pinned_clock=clock,
            pin_watermark=clock,
            status="current",
            match_count=live["match_count"],
            mismatch_count=live["mismatch_count"],
            missing_count=live["missing_count"],
            created_at=_now(),
        )
        for i, row in enumerate(live.get("rows") or []):
            if i % 2 == 1:
                continue
            report_repo.add_row(
                conn,
                report_id=rid,
                sale_no=row.get("sale_no"),
                sku_code=row.get("sku_code"),
                status=row.get("status"),
                expected_price=row.get("expected_price"),
                unit_price=row.get("unit_price"),
            )
        conn.commit()
        return get_report(rid)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_reports() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return report_repo.list_reports(conn)
    finally:
        conn.close()


def get_report(report_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        rep = report_repo.get_report(conn, report_id)
        if not rep:
            raise HTTPException(404, "报告不存在")
        stored = report_repo.list_rows(conn, report_id)
        if rep.get("status") == "current":
            live = reconcile_service.reconcile_sales()
            rep["rows"] = live.get("rows") or []
            rep["match_count"] = live["match_count"]
            rep["mismatch_count"] = live["mismatch_count"]
            rep["missing_count"] = live["missing_count"]
            rep["stored_row_count"] = len(stored)
            rep["materialized"] = False
        else:
            rep["rows"] = stored
            rep["materialized"] = True
        return rep
    finally:
        conn.close()

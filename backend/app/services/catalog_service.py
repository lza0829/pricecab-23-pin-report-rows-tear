from __future__ import annotations

from typing import Any

from app.db import connect
from app.repositories import skus as sku_repo
from app.repositories import settings as settings_repo
from app.repositories import batches as batch_repo
from app.repositories import tickets as ticket_repo
from app.repositories import prices as price_repo
from app.repositories import sales as sales_repo
from app.repositories import reconcile as recon_repo


def dashboard() -> dict[str, Any]:
    conn = connect()
    try:
        clock = settings_repo.get(conn, "business_clock")
        reports = recon_repo.list_reports(conn, limit=1)
        return {
            "project": "pricecab",
            "name": "价签柜",
            "business_clock": clock,
            "sku_count": conn.execute("SELECT COUNT(*) c FROM skus").fetchone()["c"],
            "ticket_count": conn.execute("SELECT COUNT(*) c FROM price_tickets").fetchone()["c"],
            "scheduled_count": conn.execute(
                "SELECT COUNT(*) c FROM price_tickets WHERE status='scheduled'"
            ).fetchone()["c"],
            "applied_count": conn.execute(
                "SELECT COUNT(*) c FROM price_tickets WHERE status='applied'"
            ).fetchone()["c"],
            "book_count": conn.execute("SELECT COUNT(*) c FROM price_book").fetchone()["c"],
            "sale_count": conn.execute("SELECT COUNT(*) c FROM sales_fixture").fetchone()["c"],
            "batch_count": conn.execute("SELECT COUNT(*) c FROM apply_batches").fetchone()["c"],
            "due_now": len(ticket_repo.due_tickets(conn, clock or "")),
            "report_count": conn.execute("SELECT COUNT(*) c FROM reconcile_reports").fetchone()["c"],
            "open_flag_count": conn.execute(
                "SELECT COUNT(*) c FROM reconcile_flags WHERE status='open'"
            ).fetchone()["c"],
            "rejection_count": conn.execute("SELECT COUNT(*) c FROM apply_rejections").fetchone()["c"],
            "latest_report": reports[0] if reports else None,
        }
    finally:
        conn.close()


def list_skus() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return sku_repo.list_skus(conn)
    finally:
        conn.close()

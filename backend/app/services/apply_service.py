from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.db import connect
from app.repositories import settings as settings_repo
from app.repositories import tickets as ticket_repo
from app.repositories import prices as price_repo
from app.repositories import batches as batch_repo
from app.repositories import reconcile as recon_repo
from app.seed import RECON_DEFAULTS
from app.timeutil import norm_ts


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_clock() -> dict[str, Any]:
    conn = connect()
    try:
        return {
            "business_clock": settings_repo.get(conn, "business_clock"),
            "clock_label": settings_repo.get(conn, "clock_label"),
        }
    finally:
        conn.close()


def set_clock(clock_at: str) -> dict[str, Any]:
    clock_at = (clock_at or "").strip()
    if not clock_at:
        raise HTTPException(400, "业务钟不能为空")
    try:
        clock_at = norm_ts(clock_at)
    except ValueError:
        raise HTTPException(400, "业务钟不是合法 ISO 时刻")
    conn = connect(immediate=True)
    try:
        settings_repo.set_value(conn, "business_clock", clock_at)
        conn.commit()
        return get_clock()
    finally:
        conn.close()


def list_batches() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return batch_repo.list_batches(conn)
    finally:
        conn.close()


def list_rejections() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return batch_repo.list_rejections(conn)
    finally:
        conn.close()


def apply_due() -> dict[str, Any]:
    """Apply all scheduled tickets whose effective_at <= business clock.

    mismatch_policy=block 时，凡商品存在「窗内未处置不一致」旗标，
    其所在改价单整单暂缓（保持 scheduled），被拦行写入 apply_rejections 供互证。
    """
    conn = connect(immediate=True)
    try:
        clock = settings_repo.get(conn, "business_clock")
        if not clock:
            raise HTTPException(400, "业务钟未设置")
        mismatch_policy = settings_repo.get(
            conn, "recon_mismatch_policy", RECON_DEFAULTS["recon_mismatch_policy"]
        )
        due = ticket_repo.due_tickets(conn, clock)
        if not due:
            conn.commit()
            return {
                "applied": False,
                "message": "当前业务钟下没有到期改价单",
                "business_clock": clock,
                "mismatch_policy": mismatch_policy,
                "ticket_count": 0,
                "line_count": 0,
                "held_ticket_count": 0,
                "rejections": [],
            }

        open_flags = recon_repo.open_flag_map(conn) if mismatch_policy == "block" else {}

        applicable: list[dict[str, Any]] = []
        held: list[dict[str, Any]] = []
        for t in due:
            lines = ticket_repo.list_lines(conn, t["id"])
            blocked_skus = sorted({l["sku_code"] for l in lines if l["sku_code"] in open_flags})
            if blocked_skus:
                held.append({"ticket": t, "lines": lines, "blocked_skus": blocked_skus})
            else:
                applicable.append({"ticket": t, "lines": lines})

        batch_no = batch_repo.next_batch_no(conn)
        created = _now()
        line_total = 0
        applied_tickets = []
        batch_id = batch_repo.create_batch(
            conn,
            batch_no=batch_no,
            clock_at=clock,
            ticket_count=0,
            line_count=0,
            status="running",
            created_at=created,
        )

        for item in applicable:
            t, lines = item["ticket"], item["lines"]
            for line in lines:
                price_repo.upsert_book(
                    conn,
                    sku_code=line["sku_code"],
                    price=float(line["new_price"]),
                    ticket_no=t["ticket_no"],
                    effective_at=t["effective_at"],
                    updated_at=created,
                )
                line_total += 1
            ticket_repo.mark_applied(conn, t["id"], applied_at=created, batch_id=batch_id)
            applied_tickets.append(t["ticket_no"])

        rejections = []
        for item in held:
            t, lines = item["ticket"], item["lines"]
            for line in lines:
                sku = line["sku_code"]
                if sku not in open_flags:
                    continue
                reason = (
                    f"{sku} 存在窗内未处置不一致（旗标#{open_flags[sku]}），"
                    f"按策略禁止应用到期改价，改价单 {t['ticket_no']} 整单暂缓"
                )
                batch_repo.add_rejection(
                    conn,
                    batch_id=batch_id,
                    ticket_id=t["id"],
                    ticket_no=t["ticket_no"],
                    sku_code=sku,
                    reason=reason,
                    created_at=created,
                )
                rejections.append({"ticket_no": t["ticket_no"], "sku_code": sku, "reason": reason})

        if not held:
            status = "done"
        elif applicable:
            status = "partial"
        else:
            status = "held"
        conn.execute(
            "UPDATE apply_batches SET ticket_count=?, line_count=?, status=? WHERE id=?",
            (len(applied_tickets), line_total, status, batch_id),
        )
        conn.commit()
        return {
            "applied": bool(applied_tickets),
            "batch_no": batch_no,
            "business_clock": clock,
            "mismatch_policy": mismatch_policy,
            "ticket_count": len(applied_tickets),
            "line_count": line_total,
            "tickets": applied_tickets,
            "held_ticket_count": len(held),
            "held": [
                {"ticket_no": h["ticket"]["ticket_no"], "blocked_skus": h["blocked_skus"]}
                for h in held
            ],
            "rejections": rejections,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

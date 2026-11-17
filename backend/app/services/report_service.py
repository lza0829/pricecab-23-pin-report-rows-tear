from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.db import connect
from app.repositories import reports as report_repo
from app.repositories import sales as sales_repo
from app.repositories import prices as price_repo
from app.repositories import settings as settings_repo
from app.timeutil import parse_ts

# 冻结对账报告的全局唯一收口：以钉扎时刻历史 as-of 物化钉扎行并冻结。
#   - 打开报告只读已物化钉扎行，禁止按现行价签现场重算；
#   - 物化未完成（materializing）或头部与钉扎行互证不一致的报告，
#     不得标现行（current=false），不得驱动拦改价；
#   - 钉扎行分叉（缺失/错误）时，用报告自己的钉扎时刻 as-of 重建并冻结
#     （rematerialize），修复不授予现行资格。


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- 钉扎时刻 as-of 物化

def _evaluate_pinned(conn, *, watermark: str, known_at: str) -> dict[str, Any]:
    """以钉扎水位截销售、以钉扎时刻可见的价签历史求期望价。

    watermark：只纳入 sold_at <= 水位的成交（钉扎的数据截止）。
    known_at ：只用 recorded_at <= known_at 的价签历史（钉扎时刻可见），
              冻结后补录的溯及价签不得回流进已钉扎报告。
    """
    end_dt = parse_ts(watermark)
    rows: list[dict[str, Any]] = []
    match = mismatch = missing = 0
    for s in sales_repo.list_sales(conn):
        if parse_ts(s["sold_at"]) > end_dt:
            continue
        expected = price_repo.price_at_known(conn, s["sku_code"], s["sold_at"], known_at)
        sold = float(s["unit_price"])
        if expected is None:
            status, delta = "missing_price", None
            missing += 1
        elif abs(expected - sold) < 1e-9:
            status, delta = "match", 0.0
            match += 1
        else:
            status, delta = "mismatch", round(sold - expected, 4)
            mismatch += 1
        rows.append({
            "sale_no": s["sale_no"],
            "sku_code": s["sku_code"],
            "sold_at": s["sold_at"],
            "unit_price": sold,
            "qty": int(s["qty"]),
            "expected_price": expected,
            "delta": delta,
            "status": status,
        })
    return {
        "rows": rows,
        "sale_count": len(rows),
        "match_count": match,
        "mismatch_count": mismatch,
        "missing_count": missing,
    }


def freeze_report() -> dict[str, Any]:
    """冻结当前业务钟的对账报告：钉扎业务钟与水位，物化全部钉扎行后才标现行。

    报告头（materializing）与全部钉扎行同事务写入，物化落账后才置 current
    并退位旧现行；任何失败整体回滚——不存在「行写了一半、头已标成功」
    的可观测中间态。
    """
    conn = connect(immediate=True)
    try:
        clock = settings_repo.get(conn, "business_clock")
        if not clock:
            raise HTTPException(400, "业务钟未设置，无法钉扎冻结报告")
        created = _now()
        result = _evaluate_pinned(conn, watermark=clock, known_at=created)
        rid = report_repo.create_report(
            conn,
            report_no=report_repo.next_report_no(conn),
            pinned_clock=clock,
            pin_watermark=clock,
            status="materializing",
            sale_count=0,
            match_count=0,
            mismatch_count=0,
            missing_count=0,
            row_count=0,
            created_at=created,
            materialized_at=None,
        )
        for row in result["rows"]:
            report_repo.add_row(conn, rid, **row)
        # 物化落账：头部计数与已写入的钉扎行同源，随后才授予现行资格。
        report_repo.set_materialization(
            conn,
            rid,
            sale_count=result["sale_count"],
            match_count=result["match_count"],
            mismatch_count=result["mismatch_count"],
            missing_count=result["missing_count"],
            row_count=len(result["rows"]),
            materialized_at=created,
        )
        report_repo.set_status(conn, rid, "current")
        report_repo.supersede_others(conn, rid)
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_report(rid)


def rematerialize(report_id: int) -> dict[str, Any]:
    """钉扎行分叉的收口：以报告自己的钉扎时刻 as-of 重建缺失/错误钉扎行并冻结。

    重建只纳入该报告钉扎水位内的成交、只用其钉扎时刻可见的价签历史，
    因此修复结果与当初应有的钉扎行一致，不受修复前补录价签的影响。
    现行资格不因修复而授予：仅原本就标现行的报告修复后恢复现行。
    """
    conn = connect(immediate=True)
    try:
        rep = report_repo.get_report(conn, report_id)
        if not rep:
            raise HTTPException(404, "冻结报告不存在")
        result = _evaluate_pinned(
            conn, watermark=rep["pin_watermark"], known_at=rep["created_at"]
        )
        report_repo.replace_rows(conn, report_id, result["rows"])
        report_repo.set_materialization(
            conn,
            report_id,
            sale_count=result["sale_count"],
            match_count=result["match_count"],
            mismatch_count=result["mismatch_count"],
            missing_count=result["missing_count"],
            row_count=len(result["rows"]),
            materialized_at=_now(),
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_report(report_id)


# ---------------------------------------------------------------- 读取（只读钉扎行）

def _aggregate(stored: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "match_count": sum(1 for r in stored if r["status"] == "match"),
        "mismatch_count": sum(1 for r in stored if r["status"] == "mismatch"),
        "missing_count": sum(1 for r in stored if r["status"] == "missing_price"),
    }


def _integrity(rep: dict[str, Any], stored: list[dict[str, Any]]) -> dict[str, Any]:
    """报告头与钉扎行互证：物化完成且计数同源才可信，才谈得上现行资格。"""
    agg = _aggregate(stored)
    materialized = (
        rep.get("materialized_at") is not None
        and rep.get("status") != "materializing"
        and len(stored) == rep.get("row_count")
        and len(stored) == rep.get("sale_count")
        and agg["match_count"] == rep.get("match_count")
        and agg["mismatch_count"] == rep.get("mismatch_count")
        and agg["missing_count"] == rep.get("missing_count")
    )
    return {
        "stored_row_count": len(stored),
        "materialized": materialized,
        "current": rep.get("status") == "current" and materialized,
    }


def get_report(report_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        rep = report_repo.get_report(conn, report_id)
        if not rep:
            raise HTTPException(404, "冻结报告不存在")
        stored = report_repo.list_rows(conn, report_id)
        # 打开只读钉扎行：禁止按现行价签现场重算，两次打开结果一致。
        rep["rows"] = stored
        rep.update(_integrity(rep, stored))
        return rep
    finally:
        conn.close()


def list_reports() -> list[dict[str, Any]]:
    conn = connect()
    try:
        reps = report_repo.list_reports(conn)
        for rep in reps:
            rep.update(_integrity(rep, report_repo.list_rows(conn, rep["id"])))
        return reps
    finally:
        conn.close()


def current_trusted_report(conn) -> dict[str, Any] | None:
    """拦改价唯一可信的冻结报告入口：现行且物化互证通过，否则视为不存在。"""
    rep = report_repo.get_current(conn)
    if not rep:
        return None
    stored = report_repo.list_rows(conn, rep["id"])
    if not _integrity(rep, stored)["materialized"]:
        return None
    rep["rows"] = stored
    return rep

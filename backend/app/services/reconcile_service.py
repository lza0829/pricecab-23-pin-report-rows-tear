from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import HTTPException

from app.db import connect
from app.repositories import sales as sales_repo
from app.repositories import prices as price_repo
from app.repositories import settings as settings_repo
from app.repositories import reconcile as recon_repo
from app.seed import RECON_DEFAULTS
from app.timeutil import parse_ts, fmt_ts, norm_ts

WINDOW_MODES = ("absolute", "relative")
OUTSIDE_POLICIES = ("exclude", "flag")   # 硬排除 / 入明细但标窗外（互斥）
MISMATCH_POLICIES = ("block", "record")  # 禁止应用到期改价 / 只记账（互斥）


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- 配置

def _config_from_settings(conn) -> dict[str, Any]:
    stored = settings_repo.list_all(conn)
    cfg: dict[str, Any] = dict(RECON_DEFAULTS)
    for key in RECON_DEFAULTS:
        if stored.get(key) not in (None, ""):
            cfg[key] = stored[key]
    return cfg


def _resolve_window(cfg: dict[str, Any], business_clock: str | None) -> tuple[str, str]:
    """把窗配置解析为绝对时刻区间。相对模式必须依赖业务钟，解析结果落库可核。"""
    if cfg["recon_window_mode"] == "absolute":
        try:
            start = parse_ts(cfg["recon_window_start"])
            end = parse_ts(cfg["recon_window_end"])
        except ValueError as e:
            raise HTTPException(400, f"绝对窗起止时刻无法解析: {e}")
    else:
        if not business_clock:
            raise HTTPException(400, "相对业务钟的窗需要先设置业务钟")
        try:
            rel_start = float(cfg["recon_rel_start_hours"])
            rel_end = float(cfg["recon_rel_end_hours"])
        except (TypeError, ValueError):
            raise HTTPException(400, "相对窗小时数必须是数字")
        if rel_start > rel_end:
            raise HTTPException(400, "相对窗起点不能晚于终点")
        clock = parse_ts(business_clock)
        start = clock + timedelta(hours=rel_start)
        end = clock + timedelta(hours=rel_end)
    if start > end:
        raise HTTPException(400, "窗起点不能晚于窗终点")
    return fmt_ts(start), fmt_ts(end)


def get_config() -> dict[str, Any]:
    conn = connect()
    try:
        cfg = _config_from_settings(conn)
        clock = settings_repo.get(conn, "business_clock")
        resolved_start, resolved_end = _resolve_window(cfg, clock)
        return {
            "window_mode": cfg["recon_window_mode"],
            "window_start": cfg["recon_window_start"],
            "window_end": cfg["recon_window_end"],
            "rel_start_hours": float(cfg["recon_rel_start_hours"]),
            "rel_end_hours": float(cfg["recon_rel_end_hours"]),
            "outside_policy": cfg["recon_outside_policy"],
            "mismatch_policy": cfg["recon_mismatch_policy"],
            "business_clock": clock,
            "resolved_start": resolved_start,
            "resolved_end": resolved_end,
        }
    finally:
        conn.close()


def update_config(body: dict[str, Any]) -> dict[str, Any]:
    conn = connect(immediate=True)
    try:
        cfg = _config_from_settings(conn)

        mode = body.get("window_mode", cfg["recon_window_mode"])
        if mode not in WINDOW_MODES:
            raise HTTPException(400, f"window_mode 只能是 {WINDOW_MODES}")
        outside = body.get("outside_policy", cfg["recon_outside_policy"])
        if outside not in OUTSIDE_POLICIES:
            raise HTTPException(400, f"outside_policy 只能是 {OUTSIDE_POLICIES}（互斥）")
        mismatch = body.get("mismatch_policy", cfg["recon_mismatch_policy"])
        if mismatch not in MISMATCH_POLICIES:
            raise HTTPException(400, f"mismatch_policy 只能是 {MISMATCH_POLICIES}（互斥）")

        new_cfg = {
            "recon_window_mode": mode,
            "recon_window_start": cfg["recon_window_start"],
            "recon_window_end": cfg["recon_window_end"],
            "recon_rel_start_hours": cfg["recon_rel_start_hours"],
            "recon_rel_end_hours": cfg["recon_rel_end_hours"],
            "recon_outside_policy": outside,
            "recon_mismatch_policy": mismatch,
        }
        if body.get("window_start") is not None:
            try:
                new_cfg["recon_window_start"] = norm_ts(str(body["window_start"]))
            except ValueError:
                raise HTTPException(400, "window_start 不是合法 ISO 时刻")
        if body.get("window_end") is not None:
            try:
                new_cfg["recon_window_end"] = norm_ts(str(body["window_end"]))
            except ValueError:
                raise HTTPException(400, "window_end 不是合法 ISO 时刻")
        if body.get("rel_start_hours") is not None:
            try:
                new_cfg["recon_rel_start_hours"] = str(float(body["rel_start_hours"]))
            except (TypeError, ValueError):
                raise HTTPException(400, "rel_start_hours 必须是数字")
        if body.get("rel_end_hours") is not None:
            try:
                new_cfg["recon_rel_end_hours"] = str(float(body["rel_end_hours"]))
            except (TypeError, ValueError):
                raise HTTPException(400, "rel_end_hours 必须是数字")

        # 先解析校验通过才落库；历史报告行只读，改窗绝不动旧报告。
        clock = settings_repo.get(conn, "business_clock")
        _resolve_window(new_cfg, clock)
        for key, value in new_cfg.items():
            settings_repo.set_value(conn, key, str(value))
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_config()


# ---------------------------------------------------------------- 跑对账

def _evaluate(conn, cfg: dict[str, Any], clock: str) -> dict[str, Any]:
    resolved_start, resolved_end = _resolve_window(cfg, clock)
    start_dt = parse_ts(resolved_start)
    end_dt = parse_ts(resolved_end)
    outside_policy = cfg["recon_outside_policy"]

    sales = sales_repo.list_sales(conn)
    rows: list[dict[str, Any]] = []
    excluded = match = mismatch = missing = in_window = 0
    for s in sales:
        inside = start_dt <= parse_ts(s["sold_at"]) <= end_dt
        if not inside:
            excluded += 1
            if outside_policy == "flag":
                # 入明细但标窗外：不计一致/不一致，也不参与拦改价
                rows.append({
                    **s,
                    "in_window": 0,
                    "expected_price": None,
                    "delta": None,
                    "status": "out_of_window",
                })
            continue
        in_window += 1
        expected = price_repo.price_at(conn, s["sku_code"], s["sold_at"])
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
            **s,
            "in_window": 1,
            "expected_price": expected,
            "delta": delta,
            "status": status,
        })
    return {
        "resolved_start": resolved_start,
        "resolved_end": resolved_end,
        "rows": rows,
        "sale_count": len(sales),
        "excluded_count": excluded,
        "in_window_count": in_window,
        "match_count": match,
        "mismatch_count": mismatch,
        "missing_count": missing,
    }


def run_reconcile() -> dict[str, Any]:
    """按当前窗配置跑一次对账并落库成报告；报告此后只读，改窗不回写。"""
    conn = connect(immediate=True)
    try:
        cfg = _config_from_settings(conn)
        clock = settings_repo.get(conn, "business_clock")
        if not clock:
            raise HTTPException(400, "业务钟未设置")
        result = _evaluate(conn, cfg, clock)
        created = _now()
        report_id = recon_repo.create_report(
            conn,
            report_no=recon_repo.next_report_no(conn),
            created_at=created,
            business_clock=clock,
            window_mode=cfg["recon_window_mode"],
            window_start=cfg["recon_window_start"] if cfg["recon_window_mode"] == "absolute" else None,
            window_end=cfg["recon_window_end"] if cfg["recon_window_mode"] == "absolute" else None,
            rel_start_hours=float(cfg["recon_rel_start_hours"]) if cfg["recon_window_mode"] == "relative" else None,
            rel_end_hours=float(cfg["recon_rel_end_hours"]) if cfg["recon_window_mode"] == "relative" else None,
            resolved_start=result["resolved_start"],
            resolved_end=result["resolved_end"],
            outside_policy=cfg["recon_outside_policy"],
            mismatch_policy=cfg["recon_mismatch_policy"],
            sale_count=result["sale_count"],
            excluded_count=result["excluded_count"],
            in_window_count=result["in_window_count"],
            match_count=result["match_count"],
            mismatch_count=result["mismatch_count"],
            missing_count=result["missing_count"],
        )
        for row in result["rows"]:
            recon_repo.add_row(conn, report_id, **row)
            if row["status"] == "mismatch":
                recon_repo.create_flag_if_absent(
                    conn,
                    sale_no=row["sale_no"],
                    sku_code=row["sku_code"],
                    report_id=report_id,
                    expected_price=row["expected_price"],
                    unit_price=row["unit_price"],
                    delta=row["delta"],
                    created_at=created,
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


# ---------------------------------------------------------------- 报告与旗标

def list_reports() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return recon_repo.list_reports(conn)
    finally:
        conn.close()


def get_report(report_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        report = recon_repo.get_report(conn, report_id)
        if not report:
            raise HTTPException(404, "对账报告不存在")
        report["rows"] = recon_repo.list_rows(conn, report_id)
        return report
    finally:
        conn.close()


def list_flags(status: str | None = None) -> list[dict[str, Any]]:
    if status not in (None, "open", "resolved"):
        raise HTTPException(400, "status 只能是 open/resolved")
    conn = connect()
    try:
        return recon_repo.list_flags(conn, status=status)
    finally:
        conn.close()


def resolve_flag(flag_id: int, note: str | None) -> dict[str, Any]:
    conn = connect(immediate=True)
    try:
        flag = recon_repo.get_flag(conn, flag_id)
        if not flag:
            raise HTTPException(404, "旗标不存在")
        if flag["status"] == "resolved":
            raise HTTPException(400, "旗标已处置，不能重复处置")
        recon_repo.resolve_flag(conn, flag_id, resolved_at=_now(), note=(note or "").strip() or None)
        conn.commit()
        return recon_repo.get_flag(conn, flag_id)
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------- 价签查询（原有）

def list_price_book() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return price_repo.list_book(conn)
    finally:
        conn.close()


def list_history(sku_code: str | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return price_repo.list_history(conn, sku_code=sku_code)
    finally:
        conn.close()

#!/usr/bin/env python3
"""端到端验证：成交时点窗 + 窗外互斥处理 + 窗内不一致互斥后果 + 报告不可篡改。

用法：
    python3 tests/e2e_recon_window.py [base_url]      # 默认 http://localhost:10600

前置：后端以全新 DATA_DIR 启动（种子夹具 6 笔成交、默认窗 09:00-12:00）。
覆盖：
  1. 窗外硬排除：窗外行不进明细终态、只记排除数，且窗外行（含会不一致的 S-1006）不计入不一致
  2. 窗外入明细标窗外：行在明细中但标窗外，仍不计不一致
  3. block 策略：窗内未处置不一致禁止该商品应用到期改价（拒绝原因落库，价签本不变）
  4. record 策略：不一致只记账，同一改价单应用成功
  5. 处置旗标后 block 策略下可再应用
  6. 改窗：历史报告分桶计数不变，新对账按新窗重算（S-1006 进入窗内成为不一致）
  7. 相对业务钟窗：可解析、可核
  8. 互证：排除数/窗内计数/旗标/拒绝记录/价签本交叉一致
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:10600"
FAILED = []


def call(method, path, body=None, expect=200):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as res:
            payload = json.loads(res.read().decode())
            status = res.status
    except urllib.error.HTTPError as e:
        payload = json.loads(e.read().decode() or "{}")
        status = e.code
    if expect and status != expect:
        raise AssertionError(f"{method} {path} -> {status}（期望 {expect}）：{payload}")
    return payload


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def main():
    # ---------- 0. 健康与初始态 ----------
    health = call("GET", "/api/health")
    check("服务健康", health.get("ok") is True)

    cfg = call("GET", "/api/reconcile/config")
    check(
        "默认窗配置可核（绝对窗 09:00-12:00、硬排除、拦改价）",
        cfg["window_mode"] == "absolute"
        and cfg["resolved_start"] == "2026-11-16T09:00:00Z"
        and cfg["resolved_end"] == "2026-11-16T12:00:00Z"
        and cfg["outside_policy"] == "exclude"
        and cfg["mismatch_policy"] == "block",
        json.dumps(cfg, ensure_ascii=False),
    )

    # ---------- 1. 窗外硬排除 ----------
    r1 = call("POST", "/api/reconcile/run")
    check(
        "R1 分桶：扫描6 / 窗外排除3 / 窗内3 / 一致2 / 不一致1 / 缺价0",
        (r1["sale_count"], r1["excluded_count"], r1["in_window_count"],
         r1["match_count"], r1["mismatch_count"], r1["missing_count"]) == (6, 3, 3, 2, 1, 0),
        json.dumps({k: r1[k] for k in ("sale_count", "excluded_count", "in_window_count",
                                       "match_count", "mismatch_count", "missing_count")}),
    )
    r1_nos = {row["sale_no"] for row in r1["rows"]}
    check(
        "硬排除：窗外行 S-1001/S-1005/S-1006 不在明细终态",
        r1_nos == {"S-1002", "S-1003", "S-1004"} and len(r1["rows"]) == r1["in_window_count"],
        str(r1_nos),
    )
    check(
        "窗外行未计入不一致（S-1006 35.0≠39.9 但窗外，不一致仅 S-1003）",
        all(row["status"] != "mismatch" or row["sale_no"] == "S-1003" for row in r1["rows"]),
    )
    check(
        "报告快照可核：窗配置与解析结果落库",
        r1["window_mode"] == "absolute"
        and r1["resolved_start"] == "2026-11-16T09:00:00Z"
        and r1["resolved_end"] == "2026-11-16T12:00:00Z"
        and r1["business_clock"] == "2026-11-16T09:00:00Z",
    )

    flags = call("GET", "/api/reconcile/flags?status=open")
    check(
        "窗内不一致立旗标：仅 SKU-DAY-021 一面未处置",
        len(flags) == 1 and flags[0]["sku_code"] == "SKU-DAY-021" and flags[0]["sale_no"] == "S-1003",
        json.dumps(flags, ensure_ascii=False),
    )
    flag_id = flags[0]["id"]

    # ---------- 2. 窗外入明细标窗外 ----------
    call("PUT", "/api/reconcile/config", {"outside_policy": "flag"})
    r2 = call("POST", "/api/reconcile/run")
    out_rows = [row for row in r2["rows"] if row["in_window"] == 0]
    check(
        "标窗外：6 行全入明细，3 行标窗外且不带状态评估",
        len(r2["rows"]) == 6 and len(out_rows) == 3
        and all(row["status"] == "out_of_window" and row["expected_price"] is None for row in out_rows),
    )
    check(
        "标窗外：分桶与硬排除一致（排除3/不一致1），窗外行仍不计不一致",
        (r2["excluded_count"], r2["mismatch_count"]) == (3, 1)
        and all(row["status"] != "mismatch" for row in out_rows),
    )
    call("PUT", "/api/reconcile/config", {"outside_policy": "exclude"})

    # ---------- 3. block：未处置不一致禁止应用到期改价 ----------
    call("PUT", "/api/apply/clock", {"business_clock": "2026-11-16T18:00:00Z"})
    call("POST", "/api/tickets", {
        "title": "洗衣液降价", "effective_at": "2026-11-16T15:00:00Z",
        "lines": [{"sku_code": "SKU-DAY-021", "new_price": 39.9}],
    })
    call("POST", "/api/tickets", {
        "title": "茉莉花茶调价", "effective_at": "2026-11-16T15:00:00Z",
        "lines": [{"sku_code": "SKU-TEA-001", "new_price": 26.0}],
    })
    res = call("POST", "/api/apply/due")
    check(
        "block：被旗标商品所在单整单暂缓，其余单应用",
        res["held_ticket_count"] == 1 and res["ticket_count"] == 1 and res["line_count"] == 1
        and res["held"][0]["blocked_skus"] == ["SKU-DAY-021"],
        json.dumps(res, ensure_ascii=False),
    )
    check(
        "block：拒绝原因落库且指向旗标",
        len(res["rejections"]) == 1
        and res["rejections"][0]["sku_code"] == "SKU-DAY-021"
        and f"旗标#{flag_id}" in res["rejections"][0]["reason"],
        json.dumps(res["rejections"], ensure_ascii=False),
    )
    book = {b["sku_code"]: b for b in call("GET", "/api/prices/book")}
    check(
        "block：价签本互证——SKU-DAY-021 未变 45.0，SKU-TEA-001 已变 26.0",
        book["SKU-DAY-021"]["current_price"] == 45.0 and book["SKU-TEA-001"]["current_price"] == 26.0,
        f"DAY-021={book['SKU-DAY-021']['current_price']} TEA-001={book['SKU-TEA-001']['current_price']}",
    )
    tickets = call("GET", "/api/tickets")
    held_ticket = [t for t in tickets if t["title"] == "洗衣液降价"][0]
    check("block：被拦改价单保持 scheduled（未应用成功）", held_ticket["status"] == "scheduled")
    rejections = call("GET", "/api/apply/rejections")
    check(
        "block：拒绝记录与响应互证（1 条，SKU-DAY-021）",
        len(rejections) == 1 and rejections[0]["sku_code"] == "SKU-DAY-021",
    )

    # ---------- 4. record：只记账仍允许应用 ----------
    call("PUT", "/api/reconcile/config", {"mismatch_policy": "record"})
    res = call("POST", "/api/apply/due")
    book = {b["sku_code"]: b for b in call("GET", "/api/prices/book")}
    check(
        "record：同一改价单应用成功，SKU-DAY-021 变 39.9，无新拒绝",
        res["ticket_count"] == 1 and res["held_ticket_count"] == 0
        and book["SKU-DAY-021"]["current_price"] == 39.9
        and len(call("GET", "/api/apply/rejections")) == 1,
        json.dumps(res, ensure_ascii=False),
    )

    # ---------- 5. 处置旗标后 block 可再应用 ----------
    call("PUT", "/api/reconcile/config", {"mismatch_policy": "block"})
    flag = call("POST", f"/api/reconcile/flags/{flag_id}/resolve", {"note": "已与客户核对，差价为活动让利"})
    check("旗标处置", flag["status"] == "resolved" and flag["resolve_note"].startswith("已与客户"))
    call("POST", f"/api/reconcile/flags/{flag_id}/resolve", {"note": "重复处置"}, expect=400)
    call("POST", "/api/tickets", {
        "title": "洗衣液二次调价", "effective_at": "2026-11-16T16:00:00Z",
        "lines": [{"sku_code": "SKU-DAY-021", "new_price": 38.5}],
    })
    res = call("POST", "/api/apply/due")
    book = {b["sku_code"]: b for b in call("GET", "/api/prices/book")}
    check(
        "处置后 block：改价应用成功，SKU-DAY-021 变 38.5",
        res["held_ticket_count"] == 0 and book["SKU-DAY-021"]["current_price"] == 38.5,
        json.dumps(res, ensure_ascii=False),
    )

    # ---------- 6. 改窗：旧报不变，新报重算 ----------
    r1_before = call("GET", f"/api/reconcile/reports/{r1['id']}")
    r2_before = call("GET", f"/api/reconcile/reports/{r2['id']}")
    call("PUT", "/api/reconcile/config", {"window_end": "2026-11-16T14:00:00Z"})
    r3 = call("POST", "/api/reconcile/run")
    check(
        "新窗 09:00-14:00 重算：排除1 / 窗内5 / 一致3 / 不一致2（S-1006 进窗）",
        (r3["excluded_count"], r3["in_window_count"], r3["match_count"], r3["mismatch_count"])
        == (1, 5, 3, 2),
        json.dumps({k: r3[k] for k in ("excluded_count", "in_window_count", "match_count", "mismatch_count")}),
    )
    r1_after = call("GET", f"/api/reconcile/reports/{r1['id']}")
    r2_after = call("GET", f"/api/reconcile/reports/{r2['id']}")
    check(
        "改窗不回写：R1/R2 分桶计数与行数保持原样",
        all(r1_after[k] == r1_before[k] for k in
            ("excluded_count", "in_window_count", "match_count", "mismatch_count", "missing_count"))
        and len(r1_after["rows"]) == len(r1_before["rows"])
        and all(r2_after[k] == r2_before[k] for k in
                ("excluded_count", "in_window_count", "match_count", "mismatch_count"))
        and r1_after["resolved_end"] == "2026-11-16T12:00:00Z",
    )
    flags = call("GET", "/api/reconcile/flags?status=open")
    check(
        "新窗新旗标：SKU-SNK-012 未处置（SKU-DAY-021 已处置不复开）",
        len(flags) == 1 and flags[0]["sku_code"] == "SKU-SNK-012" and flags[0]["sale_no"] == "S-1006",
        json.dumps(flags, ensure_ascii=False),
    )

    # ---------- 7. 相对业务钟窗 ----------
    cfg = call("PUT", "/api/reconcile/config", {
        "window_mode": "relative", "rel_start_hours": -3, "rel_end_hours": 3,
    })
    check(
        "相对窗可核：业务钟 18:00 ±3h -> 15:00~21:00",
        cfg["resolved_start"] == "2026-11-16T15:00:00Z" and cfg["resolved_end"] == "2026-11-16T21:00:00Z",
        json.dumps(cfg, ensure_ascii=False),
    )
    r4 = call("POST", "/api/reconcile/run")
    check(
        "相对窗重算：全部成交在窗外（排除6 / 窗内0）",
        (r4["excluded_count"], r4["in_window_count"], r4["mismatch_count"]) == (6, 0, 0)
        and r4["window_mode"] == "relative" and r4["rel_start_hours"] == -3.0,
    )

    # ---------- 8. 校验与互证 ----------
    call("PUT", "/api/reconcile/config", {
        "window_mode": "absolute", "window_start": "2026-11-16T12:00:00Z", "window_end": "2026-11-16T09:00:00Z",
    }, expect=400)
    call("PUT", "/api/reconcile/config", {"outside_policy": "sometimes"}, expect=400)
    call("PUT", "/api/reconcile/config", {"mismatch_policy": "maybe"}, expect=400)
    dash = call("GET", "/api/dashboard")
    check(
        "仪表盘互证：报告4 / 未处置旗标1 / 拦改价1",
        (dash["report_count"], dash["open_flag_count"], dash["rejection_count"]) == (4, 1, 1),
        json.dumps({k: dash[k] for k in ("report_count", "open_flag_count", "rejection_count")}),
    )
    reports = call("GET", "/api/reconcile/reports")
    check(
        "报告列表只增不改：4 份，各自保留当时窗",
        len(reports) == 4 and reports[-1]["report_no"] == "RR-0001"
        and reports[0]["resolved_start"] == "2026-11-16T15:00:00Z",
    )

    print()
    if FAILED:
        print(f"共 {len(FAILED)} 项失败：")
        for name in FAILED:
            print(f"  - {name}")
        sys.exit(1)
    print("全部通过。")


if __name__ == "__main__":
    main()

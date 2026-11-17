#!/usr/bin/env python3
"""端到端验证：冻结对账报告的钉扎行物化收口（全局唯一：物化钉扎，不做现场重算）。

用法：
    python3 tests/e2e_frozen_report.py [base_url] [db_path]
    默认 http://localhost:10600 与 /tmp/pricecab-data/pricecab.db

前置：后端以全新 DATA_DIR 启动（种子夹具 6 笔成交、初始价签 2026-11-16T00:00 生效）。

覆盖（三条分叉路径互证 + 拦改价读报告入口）：
  1. 冻结即物化：报告头计数与钉扎行同源，打开两次完全一致
  2. 路径一「打开漂移」：补录溯及价签后打开，钉扎行不得现场重算、不得漂移
  3. 拦改价读报告入口：现行冻结报告的钉扎不一致行拦下该商品到期改价（无旗标纯报告驱动）
  4. 现行资格唯一：新冻结退位旧报告；旧报告钉扎行保持钉扎时刻原样
  5. 路径三「半截物化」：钉扎行缺失 -> 不得标现行、不得驱动拦改价 -> rematerialize 收口
  6. 路径二「钉扎行与 as-of 不一致」：篡改行 -> 互证失败不现行不拦 -> rematerialize 按钉扎时刻 as-of 复原
  7. 物化未完成的报告：不得标现行，修复也不授予现行资格
  8. record 策略下冻结报告同样只记账不拦
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:10600"
DB = sys.argv[2] if len(sys.argv) > 2 else "/tmp/pricecab-data/pricecab.db"
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


def tamper(sql, params=()):
    conn = sqlite3.connect(DB)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def row_map(report):
    return {r["sale_no"]: r for r in report["rows"]}


def aggregate(rows):
    return {
        "match_count": sum(1 for r in rows if r["status"] == "match"),
        "mismatch_count": sum(1 for r in rows if r["status"] == "mismatch"),
        "missing_count": sum(1 for r in rows if r["status"] == "missing_price"),
    }


def pinned_shape(report):
    """钉扎行的可比形态：与钉扎时刻同源的部分（忽略自增 id 与 report_id）。"""
    return {
        r["sale_no"]: (r["sku_code"], r["expected_price"], r["status"], r["delta"])
        for r in report["rows"]
    }


def main():
    # ---------- 0. 健康与业务钟 ----------
    health = call("GET", "/api/health")
    check("服务健康", health.get("ok") is True)
    call("PUT", "/api/apply/clock", {"business_clock": "2026-11-16T18:00:00Z"})

    # ---------- 1. 冻结即物化：头与钉扎行同源 ----------
    fr1 = call("POST", "/api/reports/freeze")
    agg = aggregate(fr1["rows"])
    check(
        "FR-0001 物化完成即现行：status/current/materialized 一致",
        fr1["report_no"] == "FR-0001" and fr1["status"] == "current"
        and fr1["materialized"] is True and fr1["current"] is True
        and fr1["materialized_at"] is not None,
        json.dumps({k: fr1[k] for k in ("report_no", "status", "materialized", "current")}),
    )
    check(
        "FR-0001 钉扎业务钟与水位落库（18:00）",
        fr1["pinned_clock"] == "2026-11-16T18:00:00Z"
        and fr1["pin_watermark"] == "2026-11-16T18:00:00Z",
    )
    check(
        "FR-0001 头部计数与钉扎行同源：6 行 / 一致4 / 不一致2 / 缺价0",
        (fr1["sale_count"], fr1["row_count"], fr1["stored_row_count"]) == (6, 6, 6)
        and (fr1["match_count"], fr1["mismatch_count"], fr1["missing_count"]) == (4, 2, 0)
        and (agg["match_count"], agg["mismatch_count"], agg["missing_count"])
        == (fr1["match_count"], fr1["mismatch_count"], fr1["missing_count"]),
        json.dumps({k: fr1[k] for k in ("sale_count", "row_count", "match_count", "mismatch_count", "missing_count")}),
    )
    m1 = row_map(fr1)
    check(
        "FR-0001 钉扎行内容：S-1003 期望45.0 不一致 / S-1006 期望39.9 不一致",
        m1["S-1003"]["expected_price"] == 45.0 and m1["S-1003"]["status"] == "mismatch"
        and m1["S-1003"]["delta"] == -3.0
        and m1["S-1006"]["expected_price"] == 39.9 and m1["S-1006"]["status"] == "mismatch"
        and m1["S-1001"]["status"] == "match" and m1["S-1001"]["expected_price"] == 28.0,
    )

    # ---------- 2. 路径一：打开漂移——补录溯及价签后打开不得现场重算 ----------
    again = call("GET", f"/api/reports/{fr1['id']}")
    check("两次打开完全一致", pinned_shape(again) == pinned_shape(fr1))
    call("POST", "/api/tickets", {
        "title": "茉莉花茶溯及调价", "effective_at": "2026-11-16T07:00:00Z",
        "lines": [{"sku_code": "SKU-TEA-001", "new_price": 26.0}],
    })
    res = call("POST", "/api/apply/due")
    book = {b["sku_code"]: b for b in call("GET", "/api/prices/book")}
    check(
        "钉扎为一致的 SKU-TEA-001 不被冻结报告误拦：溯及价签应用成功（26.0）",
        res["ticket_count"] == 1 and book["SKU-TEA-001"]["current_price"] == 26.0
        and res["frozen_report_no"] == "FR-0001",
        json.dumps(res, ensure_ascii=False),
    )
    after = call("GET", f"/api/reports/{fr1['id']}")
    check(
        "补录溯及价签后打开：钉扎行不漂移（S-1001 仍期望28.0 一致），计数不变",
        pinned_shape(after) == pinned_shape(fr1)
        and after["match_count"] == 4 and after["mismatch_count"] == 2,
        json.dumps(row_map(after)["S-1001"], ensure_ascii=False),
    )

    # ---------- 3. 拦改价读报告入口：纯冻结报告驱动（无旗标） ----------
    call("POST", "/api/tickets", {
        "title": "坚果调价", "effective_at": "2026-11-16T15:00:00Z",
        "lines": [{"sku_code": "SKU-SNK-012", "new_price": 35.0}],
    })
    res = call("POST", "/api/apply/due")
    book = {b["sku_code"]: b for b in call("GET", "/api/prices/book")}
    check(
        "现行冻结报告钉扎不一致行拦改价：SKU-SNK-012 整单暂缓，拒绝原因引用 FR-0001",
        res["held_ticket_count"] == 1 and res["held"][0]["blocked_skus"] == ["SKU-SNK-012"]
        and len(res["rejections"]) == 1 and "FR-0001" in res["rejections"][0]["reason"]
        and book["SKU-SNK-012"]["current_price"] == 39.9,
        json.dumps(res, ensure_ascii=False),
    )

    # ---------- 4. 现行资格唯一：新冻结退位旧报告 ----------
    fr2 = call("POST", "/api/reports/freeze")
    check(
        "FR-0002 现行：溯及价签进入新钉扎（S-1001 期望26.0 不一致），一致3/不一致3",
        fr2["report_no"] == "FR-0002" and fr2["current"] is True
        and (fr2["match_count"], fr2["mismatch_count"]) == (3, 3)
        and row_map(fr2)["S-1001"]["expected_price"] == 26.0
        and row_map(fr2)["S-1001"]["status"] == "mismatch",
        json.dumps({k: fr2[k] for k in ("match_count", "mismatch_count")}),
    )
    fr1_after = call("GET", f"/api/reports/{fr1['id']}")
    check(
        "FR-0001 退位 superseded：钉扎行保持钉扎时刻原样（S-1001 仍28.0一致），不再现行",
        fr1_after["status"] == "superseded" and fr1_after["current"] is False
        and fr1_after["materialized"] is True
        and pinned_shape(fr1_after) == pinned_shape(fr1),
    )
    reports = call("GET", "/api/reports")
    check(
        "报告列表：现行资格唯一（仅 FR-0002 current）",
        len(reports) == 2
        and [r["report_no"] for r in reports if r["current"]] == ["FR-0002"],
        json.dumps([(r["report_no"], r["status"], r["current"]) for r in reports], ensure_ascii=False),
    )
    fr2_pinned = pinned_shape(fr2)

    # ---------- 5. 路径三：半截物化——钉扎行缺失不得标现行、不得驱动拦改价 ----------
    tamper("DELETE FROM frozen_report_rows WHERE report_id=? AND sku_code='SKU-SNK-012'", (fr2["id"],))
    torn = call("GET", f"/api/reports/{fr2['id']}")
    check(
        "钉扎行缺失：互证失败（5/6），materialized=false 且不得标现行",
        torn["stored_row_count"] == 5 and torn["row_count"] == 6
        and torn["materialized"] is False and torn["current"] is False,
        json.dumps({k: torn[k] for k in ("stored_row_count", "row_count", "materialized", "current")}),
    )
    res = call("POST", "/api/apply/due")
    book = {b["sku_code"]: b for b in call("GET", "/api/prices/book")}
    check(
        "物化互证失败的报告不得驱动拦改价：SKU-SNK-012 改价应用成功（35.0）",
        res["held_ticket_count"] == 0 and res["ticket_count"] == 1
        and book["SKU-SNK-012"]["current_price"] == 35.0,
        json.dumps(res, ensure_ascii=False),
    )

    # ---------- 6. rematerialize 收口：按钉扎时刻 as-of 重建，补录价签不回流 ----------
    fixed = call("POST", f"/api/reports/{fr2['id']}/rematerialize")
    check(
        "rematerialize：钉扎行复原为钉扎时刻 as-of（与 FR-0002 原钉扎完全一致）",
        pinned_shape(fixed) == fr2_pinned
        and fixed["materialized"] is True and fixed["current"] is True
        and row_map(fixed)["S-1006"]["expected_price"] == 39.9,
        json.dumps(row_map(fixed)["S-1006"], ensure_ascii=False),
    )
    call("POST", "/api/tickets", {
        "title": "坚果二次调价", "effective_at": "2026-11-16T16:00:00Z",
        "lines": [{"sku_code": "SKU-SNK-012", "new_price": 33.0}],
    })
    res = call("POST", "/api/apply/due")
    check(
        "物化恢复后拦改价恢复：SKU-SNK-012 再被拦，原因引用 FR-0002",
        res["held_ticket_count"] == 1 and "FR-0002" in res["rejections"][0]["reason"],
        json.dumps(res, ensure_ascii=False),
    )

    # ---------- 7. 路径二：钉扎行与 as-of 不一致——篡改行互证失败 ----------
    tamper(
        "UPDATE frozen_report_rows SET expected_price=99.0, status='mismatch', delta=-86.5 "
        "WHERE report_id=? AND sale_no='S-1002'",
        (fr2["id"],),
    )
    poisoned = call("GET", f"/api/reports/{fr2['id']}")
    check(
        "钉扎行被篡改：头部计数与行互证失败，materialized=false 且不得标现行",
        poisoned["materialized"] is False and poisoned["current"] is False,
    )
    call("POST", "/api/tickets", {
        "title": "海苔脆片调价", "effective_at": "2026-11-16T16:00:00Z",
        "lines": [{"sku_code": "SKU-SNK-011", "new_price": 9.9}],
    })
    res = call("POST", "/api/apply/due")
    book = {b["sku_code"]: b for b in call("GET", "/api/prices/book")}
    check(
        "互证失败的报告不得驱动拦改价：SNK-011 与 SNK-012 两单全部应用（9.9 / 33.0），无一被拦",
        res["held_ticket_count"] == 0 and res["ticket_count"] == 2
        and book["SKU-SNK-011"]["current_price"] == 9.9
        and book["SKU-SNK-012"]["current_price"] == 33.0,
        json.dumps(res, ensure_ascii=False),
    )
    fixed2 = call("POST", f"/api/reports/{fr2['id']}/rematerialize")
    check(
        "rematerialize：被篡改行按钉扎时刻 as-of 复原（S-1002 期望12.5 一致）",
        pinned_shape(fixed2) == fr2_pinned
        and row_map(fixed2)["S-1002"]["expected_price"] == 12.5
        and fixed2["materialized"] is True and fixed2["current"] is True,
    )
    call("POST", "/api/tickets", {
        "title": "坚果三次调价", "effective_at": "2026-11-16T16:30:00Z",
        "lines": [{"sku_code": "SKU-SNK-012", "new_price": 31.0}],
    })
    res = call("POST", "/api/apply/due")
    check(
        "复原后现行报告恢复拦改价：SKU-SNK-012 整单暂缓，原因引用 FR-0002",
        res["held_ticket_count"] == 1 and "FR-0002" in res["rejections"][0]["reason"],
        json.dumps(res, ensure_ascii=False),
    )

    # ---------- 8. 物化未完成的报告：不得标现行，修复不授予现行资格 ----------
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    tamper(
        "INSERT INTO frozen_reports(report_no, pinned_clock, pin_watermark, status, "
        "sale_count, match_count, mismatch_count, missing_count, row_count, created_at, materialized_at) "
        "VALUES ('FR-9001', '2026-11-16T18:00:00Z', '2026-11-16T18:00:00Z', 'materializing', "
        "0, 0, 0, 0, 0, ?, NULL)",
        (now,),
    )
    fake_id = None
    for r in call("GET", "/api/reports"):
        if r["report_no"] == "FR-9001":
            fake_id = r["id"]
    fake = call("GET", f"/api/reports/{fake_id}")
    check(
        "物化未完成（materializing）：materialized=false 且不得标现行",
        fake["materialized"] is False and fake["current"] is False,
    )
    repaired = call("POST", f"/api/reports/{fake_id}/rematerialize")
    check(
        "修复物化未完成报告：钉扎行补齐但现行资格不授予（仍非现行、不参与拦改价）",
        repaired["stored_row_count"] == 6 and repaired["current"] is False
        and repaired["materialized"] is False,
        json.dumps({k: repaired[k] for k in ("stored_row_count", "status", "materialized", "current")}),
    )
    reports = call("GET", "/api/reports")
    check(
        "现行资格仍唯一（仅 FR-0002）",
        [r["report_no"] for r in reports if r["current"]] == ["FR-0002"],
        json.dumps([(r["report_no"], r["status"], r["current"]) for r in reports], ensure_ascii=False),
    )
    tamper("DELETE FROM frozen_reports WHERE report_no='FR-9001'")

    # ---------- 9. record 策略：冻结报告同样只记账不拦 ----------
    call("PUT", "/api/reconcile/config", {"mismatch_policy": "record"})
    res = call("POST", "/api/apply/due")
    book = {b["sku_code"]: b for b in call("GET", "/api/prices/book")}
    check(
        "record：被拦的 SKU-SNK-012 改价应用成功（31.0）",
        res["held_ticket_count"] == 0 and book["SKU-SNK-012"]["current_price"] == 31.0,
        json.dumps(res, ensure_ascii=False),
    )
    call("PUT", "/api/reconcile/config", {"mismatch_policy": "block"})

    # ---------- 10. 终态互证：现行报告打开稳定 ----------
    final_a = call("GET", f"/api/reports/{fr2['id']}")
    final_b = call("GET", f"/api/reports/{fr2['id']}")
    check(
        "终态：FR-0002 现行且两次打开完全一致，钉扎行与钉扎时刻同源",
        final_a["current"] is True and pinned_shape(final_a) == pinned_shape(final_b)
        and pinned_shape(final_a) == fr2_pinned,
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

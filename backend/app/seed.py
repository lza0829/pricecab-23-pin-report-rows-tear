from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.db import connect


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def init_schema(conn) -> None:
    conn.executescript(
        '''
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS skus (
          id INTEGER PRIMARY KEY,
          sku_code TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL,
          category TEXT NOT NULL,
          list_price REAL NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS price_tickets (
          id INTEGER PRIMARY KEY,
          ticket_no TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL,
          status TEXT NOT NULL,
          effective_at TEXT NOT NULL,
          note TEXT,
          created_at TEXT NOT NULL,
          applied_at TEXT,
          apply_batch_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS price_ticket_lines (
          id INTEGER PRIMARY KEY,
          ticket_id INTEGER NOT NULL REFERENCES price_tickets(id) ON DELETE CASCADE,
          sku_code TEXT NOT NULL,
          old_price REAL NOT NULL,
          new_price REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS apply_batches (
          id INTEGER PRIMARY KEY,
          batch_no TEXT NOT NULL UNIQUE,
          clock_at TEXT NOT NULL,
          ticket_count INTEGER NOT NULL,
          line_count INTEGER NOT NULL,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_book (
          sku_code TEXT PRIMARY KEY,
          current_price REAL NOT NULL,
          source_ticket_no TEXT,
          effective_at TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_history (
          id INTEGER PRIMARY KEY,
          sku_code TEXT NOT NULL,
          price REAL NOT NULL,
          source_ticket_no TEXT,
          effective_at TEXT NOT NULL,
          recorded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sales_fixture (
          id INTEGER PRIMARY KEY,
          sale_no TEXT NOT NULL UNIQUE,
          sku_code TEXT NOT NULL,
          sold_at TEXT NOT NULL,
          unit_price REAL NOT NULL,
          qty INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hold_applies (
          id INTEGER PRIMARY KEY,
          ticket_id INTEGER,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reconcile_reports (
          id INTEGER PRIMARY KEY,
          report_no TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL,
          business_clock TEXT NOT NULL,
          window_mode TEXT NOT NULL,
          window_start TEXT,
          window_end TEXT,
          rel_start_hours REAL,
          rel_end_hours REAL,
          resolved_start TEXT NOT NULL,
          resolved_end TEXT NOT NULL,
          outside_policy TEXT NOT NULL,
          mismatch_policy TEXT NOT NULL,
          sale_count INTEGER NOT NULL,
          excluded_count INTEGER NOT NULL,
          in_window_count INTEGER NOT NULL,
          match_count INTEGER NOT NULL,
          mismatch_count INTEGER NOT NULL,
          missing_count INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reconcile_report_rows (
          id INTEGER PRIMARY KEY,
          report_id INTEGER NOT NULL REFERENCES reconcile_reports(id) ON DELETE CASCADE,
          sale_no TEXT NOT NULL,
          sku_code TEXT NOT NULL,
          sold_at TEXT NOT NULL,
          unit_price REAL NOT NULL,
          qty INTEGER NOT NULL,
          in_window INTEGER NOT NULL,
          expected_price REAL,
          delta REAL,
          status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reconcile_flags (
          id INTEGER PRIMARY KEY,
          sale_no TEXT NOT NULL UNIQUE,
          sku_code TEXT NOT NULL,
          report_id INTEGER NOT NULL REFERENCES reconcile_reports(id),
          expected_price REAL,
          unit_price REAL NOT NULL,
          delta REAL,
          status TEXT NOT NULL DEFAULT 'open',
          created_at TEXT NOT NULL,
          resolved_at TEXT,
          resolve_note TEXT
        );
        CREATE TABLE IF NOT EXISTS apply_rejections (
          id INTEGER PRIMARY KEY,
          batch_id INTEGER REFERENCES apply_batches(id),
          ticket_id INTEGER,
          ticket_no TEXT NOT NULL,
          sku_code TEXT NOT NULL,
          reason TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        '''
    )


# 对账窗与策略的默认配置：成交时点窗默认覆盖业务日 09:00-12:00（绝对时刻），
# 窗外行默认硬排除，窗内不一致默认禁止对该商品应用到期改价。
RECON_DEFAULTS = {
    "recon_window_mode": "absolute",
    "recon_window_start": "2026-11-16T09:00:00Z",
    "recon_window_end": "2026-11-16T12:00:00Z",
    "recon_rel_start_hours": "-24",
    "recon_rel_end_hours": "0",
    "recon_outside_policy": "exclude",
    "recon_mismatch_policy": "block",
}


def ensure_settings_defaults(conn) -> None:
    for key, value in RECON_DEFAULTS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?,?)",
            (key, value),
        )


def seed_if_empty() -> None:
    conn = connect()
    try:
        init_schema(conn)
        ensure_settings_defaults(conn)
        n = conn.execute("SELECT COUNT(*) c FROM skus").fetchone()["c"]
        if n:
            conn.commit()
            return

        skus = json.loads((FIXTURES / "skus.json").read_text(encoding="utf-8"))
        sales = json.loads((FIXTURES / "sales.json").read_text(encoding="utf-8"))
        now = _now()
        # 初始价签生效时刻固定为业务日零点，保证成交价签比对结果可复现。
        initial_effective = "2026-11-16T00:00:00Z"
        for s in skus:
            conn.execute(
                "INSERT INTO skus(sku_code, title, category, list_price, enabled) VALUES (?,?,?,?,1)",
                (s["sku_code"], s["title"], s["category"], float(s["list_price"])),
            )
            conn.execute(
                "INSERT INTO price_book(sku_code, current_price, source_ticket_no, effective_at, updated_at) VALUES (?,?,NULL,?,?)",
                (s["sku_code"], float(s["list_price"]), initial_effective, now),
            )
            conn.execute(
                "INSERT INTO price_history(sku_code, price, source_ticket_no, effective_at, recorded_at) VALUES (?,?,NULL,?,?)",
                (s["sku_code"], float(s["list_price"]), initial_effective, now),
            )
        for row in sales:
            conn.execute(
                "INSERT INTO sales_fixture(sale_no, sku_code, sold_at, unit_price, qty) VALUES (?,?,?,?,?)",
                (row["sale_no"], row["sku_code"], row["sold_at"], float(row["unit_price"]), int(row["qty"])),
            )
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES ('business_clock', ?)",
            ("2026-11-16T09:00:00Z",),
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES ('clock_label', ?)",
            ("业务钟（可拨，用于判断改价是否到期）",),
        )
        conn.commit()
    finally:
        conn.close()

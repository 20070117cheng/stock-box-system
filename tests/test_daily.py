# -*- coding: utf-8 -*-
import json
import sqlite3

import numpy as np
import pandas as pd

from core.config import DEFAULTS
from jobs.daily import run


def _seed_scannable_stock(db_path):
    """塞一檔會被掃描選中的股票（同 test_scanner 的合成序列）。"""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE company_master (stock_id TEXT, stock_name TEXT, industry TEXT,
        market TEXT, is_active INTEGER);
    CREATE TABLE stock_price_daily (stock_id TEXT, date TEXT, open REAL, high REAL,
        low REAL, close REAL, volume INTEGER, PRIMARY KEY (stock_id, date));
    INSERT INTO company_master VALUES ('6488','環球晶','半導體','上櫃',1);
    """)
    closes = (list(np.linspace(100, 120, 80))
              + [112, 108, 105, 103, 102, 101, 100, 124])
    dates = pd.bdate_range("2026-01-01", periods=len(closes))
    rows = [("6488", dt.strftime("%Y-%m-%d"), float(c), float(c) * 1.01,
             float(c) * 0.99, float(c), 5000) for dt, c in zip(dates, closes)]
    conn.executemany("INSERT INTO stock_price_daily VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return dates[-1].strftime("%Y-%m-%d")


def test_daily_run_produces_outputs(tmp_path):
    db_path = str(tmp_path / "test.db")
    last_date = _seed_scannable_stock(db_path)
    out_dir = str(tmp_path / "outputs")

    result = run(db_path, out_dir, date=last_date, cfg=dict(DEFAULTS),
                 skip_update=True)

    day_dir = tmp_path / "outputs" / last_date
    assert (day_dir / "scan.parquet").exists()
    assert (day_dir / "meta.json").exists()
    scan_df = pd.read_parquet(day_dir / "scan.parquet")
    assert list(scan_df["代號"]) == ["6488"]
    assert (day_dir / "bt_6488.parquet").exists()
    meta = json.loads((day_dir / "meta.json").read_text(encoding="utf-8"))
    assert "6488" in meta["tomorrow_desc"]
    assert result["scanned"] == 1


def test_daily_run_empty_scan_ok(tmp_path):
    """名單為空也要正常結束並寫出空 scan.parquet。"""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE company_master (stock_id TEXT, stock_name TEXT, industry TEXT,
        market TEXT, is_active INTEGER);
    CREATE TABLE stock_price_daily (stock_id TEXT, date TEXT, open REAL, high REAL,
        low REAL, close REAL, volume INTEGER, PRIMARY KEY (stock_id, date));
    """)
    conn.commit()
    conn.close()

    result = run(db_path, str(tmp_path / "outputs"), date="2026-07-06",
                 cfg=dict(DEFAULTS), skip_update=True)
    day_dir = tmp_path / "outputs" / "2026-07-06"
    assert (day_dir / "scan.parquet").exists()
    assert pd.read_parquet(day_dir / "scan.parquet").empty
    assert result["scanned"] == 0

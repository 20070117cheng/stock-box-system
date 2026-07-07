# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from core.config import DEFAULTS
from core.scanner import scan


def _insert_prices(db, sid, closes):
    dates = pd.bdate_range("2026-01-01", periods=len(closes))
    rows = [(sid, dt.strftime("%Y-%m-%d"), float(c), float(c) * 1.01,
             float(c) * 0.99, float(c), 5000) for dt, c in zip(dates, closes)]
    db.executemany(
        "INSERT OR REPLACE INTO stock_price_daily VALUES (?,?,?,?,?,?,?)", rows)
    db.commit()


def test_scan_picks_golden_cross_near_high(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    # 6488：緩漲後回檔壓低 K 值，最後一天強拉創收盤新高 → 當日剛金叉且達門檻
    closes = (list(np.linspace(100, 120, 80))
              + [112, 108, 105, 103, 102, 101, 100, 124])
    _insert_prices(db, "6488", closes)
    # 2330：距 3 年收盤高點太遠，不入選
    _insert_prices(db, "2330", list(np.linspace(100, 150, 80)) + [110] * 8)

    out = scan(db, dict(DEFAULTS))
    assert list(out["代號"]) == ["6488"]
    assert out.iloc[0]["KD狀態"] in ("剛黃金交叉", "準備交叉向上")
    for col in ["代號", "股名", "產業", "市場", "當前價", "3年高點", "距高點比例",
                "3年收盤高點", "距收盤高點比例", "K值", "D值", "KD狀態"]:
        assert col in out.columns


def test_scan_skips_short_history(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    _insert_prices(db, "6488", list(np.linspace(100, 120, 30)))  # 不足 60 筆
    out = scan(db, dict(DEFAULTS))
    assert out.empty


def test_scan_empty_result_has_columns(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    out = scan(db, dict(DEFAULTS))
    assert out.empty
    assert "代號" in out.columns  # 空結果也要有欄位，下游才不會炸

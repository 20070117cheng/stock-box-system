# -*- coding: utf-8 -*-
import json
import os

import numpy as np
import pandas as pd
import pytest

from core.config import DEFAULTS
from core.history import (compute_winrates, refresh, scan_params,
                          trading_dates, update_scan_cache)


def _insert_prices(db, sid, closes, start="2026-01-01"):
    dates = pd.bdate_range(start, periods=len(closes))
    rows = [(sid, dt.strftime("%Y-%m-%d"), float(c), float(c) * 1.01,
             float(c) * 0.99, float(c), 5000) for dt, c in zip(dates, closes)]
    db.executemany(
        "INSERT OR REPLACE INTO stock_price_daily VALUES (?,?,?,?,?,?,?)", rows)
    db.commit()


def test_trading_dates(db):
    out = trading_dates(db, "2026-06-01", "2026-06-05")
    assert out == ["2026-06-01", "2026-06-02", "2026-06-03",
                   "2026-06-04", "2026-06-05"]


def test_update_scan_cache_skips_cached_dates(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    _insert_prices(db, "2330", list(np.linspace(100, 120, 80)))
    dates = trading_dates(db, "2026-01-01", "2026-12-31")
    calls = []
    cache = update_scan_cache(db, dict(DEFAULTS), dates[:3], None,
                              progress=lambda d, t: calls.append(d))
    assert len(calls) == 3  # 三天都要掃
    assert set(cache["選股日"]) == set(dates[:3])

    calls.clear()
    cache2 = update_scan_cache(db, dict(DEFAULTS), dates[:5], cache,
                               progress=lambda d, t: calls.append(d))
    assert len(calls) == 2  # 只補缺的兩天
    assert set(cache2["選股日"]) == set(dates[:5])

    # 裁掉範圍外的舊日子
    cache3 = update_scan_cache(db, dict(DEFAULTS), dates[3:5], cache2)
    assert set(cache3["選股日"]) == set(dates[3:5])


def test_update_scan_cache_marks_empty_days(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    _insert_prices(db, "2330", list(np.linspace(100, 120, 30)))  # 不足60筆→不入選
    d = trading_dates(db, "2026-01-01", "2026-12-31")[-1]
    cache = update_scan_cache(db, dict(DEFAULTS), [d], None)
    assert len(cache) == 1
    assert cache.iloc[0]["代號"] == ""  # 空日標記，之後不重掃
    cache2 = update_scan_cache(db, dict(DEFAULTS), [d], cache)
    assert len(cache2) == 1


def _winner_loser_db(db):
    """兩檔股票：一檔進場後一路漲（勝）、一檔進場後跌破停損（敗）。"""
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    # 緩漲讓 KD 多頭與週低點抬高成立，4 月中突破後一路漲（勝）
    up = list(np.linspace(100, 106, 70)) + [115] + list(np.linspace(116, 180, 40))
    # 相同前段，突破後立刻崩跌 → 觸發停損實現虧損（敗）
    down = list(np.linspace(100, 106, 70)) + [115] + list(np.linspace(110, 70, 40))
    _insert_prices(db, "2330", up)
    _insert_prices(db, "6488", down)


def test_compute_winrates_counts_win_and_loss(db):
    _winner_loser_db(db)
    pick = "2026-04-01"
    scans = pd.DataFrame([
        {"選股日": pick, "代號": "2330", "股名": "台積電", "當前價": 100.0},
        {"選股日": pick, "代號": "6488", "股名": "環球晶", "當前價": 100.0},
    ])
    cfg = dict(DEFAULTS)
    out = compute_winrates(db, cfg, scans, today="2026-12-31")
    assert len(out) == 1
    row = out.iloc[0]
    assert not row["發展中"]  # 4月+3個月 < 12月，窗已結算
    # 兩檔都應有進場；一勝一敗 → 勝率 50%（若其一未進場則數字不同，直接驗證）
    assert row["進場檔數_今"] == 2
    assert row["勝率_今"] == 50.0
    assert row["進場檔數_窗"] == 2
    assert row["勝率_窗"] == 50.0


def test_compute_winrates_developing_day(db):
    _winner_loser_db(db)
    pick = "2026-06-20"
    scans = pd.DataFrame([
        {"選股日": pick, "代號": "2330", "股名": "台積電", "當前價": 100.0},
    ])
    out = compute_winrates(db, dict(DEFAULTS), scans, today="2026-07-07")
    row = out.iloc[0]
    assert row["發展中"]
    assert pd.isna(row["勝率_窗"])  # 窗未結算 → A 版無值


def test_compute_winrates_empty_day(db):
    out = compute_winrates(
        db, dict(DEFAULTS),
        pd.DataFrame([{"選股日": "2026-06-10", "代號": "", "股名": "",
                       "當前價": 0.0}]),
        today="2026-12-31")
    assert len(out) == 1
    assert out.iloc[0]["入選檔數"] == 0
    assert pd.isna(out.iloc[0]["勝率_今"])


def test_refresh_writes_files_and_rebuilds_on_param_change(db, tmp_path):
    _winner_loser_db(db)
    hist = str(tmp_path / "history")
    cfg = dict(DEFAULTS)
    stats = refresh(db, cfg, hist, today="2026-12-31")
    assert stats["days"] > 0
    assert os.path.exists(os.path.join(hist, "scans.parquet"))
    assert os.path.exists(os.path.join(hist, "winrates.parquet"))
    with open(os.path.join(hist, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["scan_params"] == scan_params(cfg)

    # 同參數再跑：不重掃（new_scans=0）
    stats2 = refresh(db, cfg, hist, today="2026-12-31")
    assert stats2["new_scans"] == 0

    # 門檻改變：整份重建（new_scans 回到全部日數）
    cfg2 = dict(cfg)
    cfg2["high_threshold_pct"] = 90.0
    stats3 = refresh(db, cfg2, hist, today="2026-12-31")
    assert stats3["new_scans"] == stats3["days"]

# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from core.config import DEFAULTS
from core.scanner import scan


def _insert_prices(db, sid, closes, start="2026-01-01"):
    dates = pd.bdate_range(start, periods=len(closes))
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


def test_scan_reports_progress(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    _insert_prices(db, "6488", list(np.linspace(100, 120, 80)))
    calls = []
    scan(db, dict(DEFAULTS), progress=lambda done, total: calls.append((done, total)))
    # 每檔公司回報一次（get_companies 過濾後剩 2330、6488 兩檔）
    assert calls == [(1, 2), (2, 2)]


def test_scan_empty_result_has_columns(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    out = scan(db, dict(DEFAULTS))
    assert out.empty
    assert "代號" in out.columns  # 空結果也要有欄位，下游才不會炸


# ---------- pullback 模式 ----------
def _pullback_cfg():
    cfg = dict(DEFAULTS)
    cfg["scan_mode"] = "pullback"
    return cfg


def _wave_base():
    """波段結構：整理 100 → 峰A 115 → 回檔 → 峰B 125（3年高）。

    配合 2026-01-05（週一）起算讓週線對齊：
    最後一次改箱後箱體=[120,125]，回檔須守住箱底 120。
    """
    return (
        [100.0] * 30                                # 整理 6 週（湊滿 scan 的 60 筆門檻）
        + list(np.linspace(103, 108, 5))            # w7 收 108 → 箱[100,108]
        + list(np.linspace(110, 115, 5))            # w6 收 115 → 箱[108,115]（峰A）
        + [112, 111, 110, 111, 111]                 # w7 回檔 → 箱不變
        + list(np.linspace(116, 120, 5))            # w8 收 120 → 箱[115,120]
        + list(np.linspace(121, 125, 5))            # w9 收 125 → 箱[120,125]（峰B=3年高）
    )


MONDAY = "2026-01-05"


def test_pullback_picks_dip_holding_support(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    # 峰B後小回檔（守住箱底120），最後一天強拉讓 KD 剛金叉
    closes = _wave_base() + [123, 122, 121.5, 121, 120.7, 120.5, 124.9]
    _insert_prices(db, "6488", closes, start=MONDAY)
    out = scan(db, _pullback_cfg())
    assert list(out["代號"]) == ["6488"]
    assert "回檔" in out.iloc[0]["KD狀態"]


def test_pullback_rejects_broken_support(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    # 回檔跌破箱底 120 → 不選（即使距高點仍在 7% 內、KD 有金叉）
    closes = _wave_base() + [122, 121, 120.5, 119.5, 118, 117, 124.9]
    _insert_prices(db, "6488", closes, start=MONDAY)
    out = scan(db, _pullback_cfg())
    assert out.empty


def test_pullback_rejects_stale_high(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    # 創高後橫盤 25 個交易日（> recency 20）→ 不選
    closes = _wave_base() + [122.0, 121.5] * 12 + [121.0, 124.9]
    _insert_prices(db, "6488", closes, start=MONDAY)
    out = scan(db, _pullback_cfg())
    assert out.empty


def test_pullback_rejects_no_dip_yet(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    # 最後一天就是 3 年高（尚未回檔）→ 不選
    closes = _wave_base()
    _insert_prices(db, "6488", closes, start=MONDAY)
    out = scan(db, _pullback_cfg())
    assert out.empty

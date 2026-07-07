# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from core.backtest import calculate_tw_cost, run_backtest
from core.config import DEFAULTS


def _price_df(closes, start="2025-01-02"):
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {"open": closes,
         "high": [c * 1.01 for c in closes],
         "low": [c * 0.99 for c in closes],
         "close": closes,
         "volume": [5000] * len(closes)},
        index=dates)


def test_cost_formula():
    # 買 1 張 100 元：100000 + 100000*0.001425*0.6 = 100085.5
    assert abs(calculate_tw_cost(100, 1, True) - 100085.5) < 1e-6
    # 賣 1 張 100 元：100000 - 85.5 - 300 = 99614.5
    assert abs(calculate_tw_cost(100, 1, False) - 99614.5) < 1e-6


def test_backtest_columns_and_alignment():
    closes = list(np.linspace(90, 130, 300))
    df = _price_df(closes)
    start = df.index[260].strftime("%Y-%m-%d")
    res = run_backtest(df, start, dict(DEFAULTS))
    assert len(res.daily) == (df.index >= pd.to_datetime(start)).sum()
    for col in ["close", "k", "d", "平均成本", "移動停利線", "固定停損線",
                "前箱高", "前箱低", "持股張數", "進場目標價", "出場目標價",
                "訊號狀態", "進出場原因說明", "損益金額", "損益獲利率%"]:
        assert col in res.daily.columns
    assert isinstance(res.tomorrow_desc, str) and res.tomorrow_desc


def test_uptrend_eventually_enters():
    # 波動上升（純線性上漲會使 RSV 緩降、KD 恆死叉，觸發不了進場）
    i = np.arange(300)
    closes = list(100 + 0.35 * i + 6 * np.sin(i / 5))
    df = _price_df(closes)
    start = df.index[260].strftime("%Y-%m-%d")
    res = run_backtest(df, start, dict(DEFAULTS))
    assert (res.daily["持股張數"] > 0).any()
    assert (res.daily["訊號狀態"] == "重返進場").any()


def test_crash_exits_by_stop():
    # 波動上升後崩跌四成 → 進場後觸發出場
    closes = list(100 + 0.4 * np.arange(280) + 6 * np.sin(np.arange(280) / 5))
    closes += list(np.linspace(closes[-1], closes[-1] * 0.6, 20))
    df = _price_df(closes)
    start = df.index[250].strftime("%Y-%m-%d")
    res = run_backtest(df, start, dict(DEFAULTS))
    assert (res.daily["訊號狀態"] == "出場").any()
    # 出場後持股歸零
    exit_pos = res.daily.index.get_loc(
        res.daily[res.daily["訊號狀態"] == "出場"].index[0])
    assert res.daily["持股張數"].iloc[exit_pos] == 0


def test_flat_market_stays_out():
    # 完全橫盤：永遠不破箱頂 → 全程空手
    closes = [100.0] * 300
    df = _price_df(closes)
    start = df.index[260].strftime("%Y-%m-%d")
    res = run_backtest(df, start, dict(DEFAULTS))
    assert (res.daily["持股張數"] == 0).all()

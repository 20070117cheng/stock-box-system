# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from core.indicators import calc_kd


def _mk_df(n=120, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.1, 1, n)
    low = close - rng.uniform(0.1, 1, n)
    return pd.DataFrame({"high": high, "low": low, "close": close})


def _legacy_scanner_kd(df, period=9):
    """舊掃描腳本 40-...v3.py 305-336 行的忠實重現：
    暖身期（rolling 未滿）rsv 為 0 且照樣更新 K/D。"""
    df = df.copy()
    min_n = df["low"].rolling(window=period).min()
    max_n = df["high"].rolling(window=period).max()
    denom = max_n - min_n
    rsv = pd.Series(0.0, index=df.index)
    mask = denom > 0
    rsv[mask] = (df["close"][mask] - min_n[mask]) / denom[mask] * 100
    k_list, d_list, k, d = [], [], 50.0, 50.0
    for r in rsv:
        k = (2 / 3) * k + (1 / 3) * r
        d = (2 / 3) * d + (1 / 3) * k
        k_list.append(k)
        d_list.append(d)
    df["k"], df["d"] = k_list, d_list
    return df


def test_kd_converges_to_legacy_scanner():
    """暖身處理不同（NaN 跳過 vs rsv=0），但 EWM 遺忘性使兩者在 60 根後收斂一致。"""
    df = _mk_df()
    got = calc_kd(df.copy())
    ref = _legacy_scanner_kd(df)
    np.testing.assert_allclose(got["k"].iloc[60:], ref["k"].iloc[60:], atol=1e-6)
    np.testing.assert_allclose(got["d"].iloc[60:], ref["d"].iloc[60:], atol=1e-6)


def test_kd_first_periods_nan():
    got = calc_kd(_mk_df())
    assert got["k"].iloc[:8].isna().all()
    assert not np.isnan(got["k"].iloc[8])


def test_kd_zero_range_gives_rsv_zero():
    df = pd.DataFrame({"high": [10.0] * 15, "low": [10.0] * 15, "close": [10.0] * 15})
    got = calc_kd(df)
    # 分母 0 → rsv 0 → K 從 50 一路衰減
    assert got["k"].iloc[-1] < got["k"].iloc[8]


def test_kd_bounds():
    got = calc_kd(_mk_df(300, seed=7))
    valid = got["k"].dropna()
    assert ((valid >= 0) & (valid <= 100)).all()

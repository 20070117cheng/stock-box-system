# -*- coding: utf-8 -*-
"""KD(9,3,3) 統一實作。

台股慣用公式：
  RSV = (close - N日最低) / (N日最高 - N日最低) * 100，分母為 0 時 RSV = 0
  K = 2/3 * 前K + 1/3 * RSV
  D = 2/3 * 前D + 1/3 * K
  K/D 初值 50

暖身期（rolling 未滿 N 日）K/D 記為 NaN 且不更新內部狀態。
舊掃描腳本暖身期以 rsv=0 參與迭代，兩者在約 40 根 K 棒後收斂到相同數值
（EWM 權重 2/3 的遺忘性），詳見 tests/test_indicators.py。
"""
import numpy as np
import pandas as pd


def calc_kd(df: pd.DataFrame, period: int = 9) -> pd.DataFrame:
    """對含 high/low/close 欄的 df 就地加上 k、d 欄並回傳。"""
    low_min = df["low"].rolling(window=period).min()
    high_max = df["high"].rolling(window=period).max()
    denom = high_max - low_min

    rsv = pd.Series(np.nan, index=df.index, dtype=float)
    pos = denom > 0
    rsv[pos] = (df["close"][pos] - low_min[pos]) / denom[pos] * 100
    rsv[denom.notna() & ~pos] = 0.0  # 區間高低相等（如連續一價到底）

    k_list, d_list = [], []
    k, d = 50.0, 50.0
    for r in rsv:
        if pd.isna(r):
            k_list.append(np.nan)
            d_list.append(np.nan)
        else:
            k = (2 / 3) * k + (1 / 3) * r
            d = (2 / 3) * d + (1 / 3) * k
            k_list.append(k)
            d_list.append(d)

    df["k"] = k_list
    df["d"] = d_list
    return df

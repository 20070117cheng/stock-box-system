# -*- coding: utf-8 -*-
"""選股掃描：接近 3 年收盤高點 + KD 剛金叉／將金叉。

條件（沿用舊掃描腳本）：
1. 資料 ≥ 60 筆
2. 現價 ≥ 3年收盤高點 × high_threshold_pct/100
3. KD 剛金叉（昨 K<D、今 K≥D）或準備交叉（K≤D 且 D-K ≤ near_cross_gap）
"""
import datetime
import logging

import pandas as pd

from core.data import get_companies, load_prices
from core.indicators import calc_kd

logger = logging.getLogger(__name__)

COLUMNS = ["代號", "股名", "產業", "市場", "當前價", "3年高點", "距高點比例",
           "3年收盤高點", "距收盤高點比例", "K值", "D值", "KD狀態"]


def scan(conn, cfg: dict, as_of: str | None = None) -> pd.DataFrame:
    """全市場掃描，回傳符合條件的股票清單（欄位同舊 kd_scan_report）。

    as_of: 只用該日（含）之前的資料，預設今天。
    """
    ref_date = (datetime.datetime.strptime(as_of, "%Y-%m-%d")
                if as_of else datetime.datetime.today())
    three_years_ago = (ref_date - datetime.timedelta(days=3 * 365)
                       ).strftime("%Y-%m-%d")
    end = ref_date.strftime("%Y-%m-%d")

    period = int(cfg["kd_period"])
    threshold = float(cfg["high_threshold_pct"]) / 100.0
    near_gap = float(cfg["near_cross_gap"])

    matched = []
    for _, comp in get_companies(conn).iterrows():
        sid = comp["stock_id"]
        df = load_prices(conn, sid, start=three_years_ago, end=end)
        if df.empty or len(df) < 60:
            continue
        try:
            high_3y = float(df["high"].max())
            high_close_3y = float(df["close"].max())
            current_price = float(df["close"].iloc[-1])
            if current_price < high_close_3y * threshold:
                continue

            df = calc_kd(df, period=period)
            current_k = float(df["k"].iloc[-1])
            current_d = float(df["d"].iloc[-1])
            prev_k = float(df["k"].iloc[-2])
            prev_d = float(df["d"].iloc[-2])

            crossed_up = prev_k < prev_d and current_k >= current_d
            getting_close = (current_k <= current_d
                             and (current_d - current_k) <= near_gap)
            if not (crossed_up or getting_close):
                continue

            matched.append({
                "代號": sid,
                "股名": comp["stock_name"],
                "產業": comp["industry"],
                "市場": comp["market"],
                "當前價": round(current_price, 2),
                "3年高點": round(high_3y, 2),
                "距高點比例": f"{round(current_price / high_3y * 100, 2)}%",
                "3年收盤高點": round(high_close_3y, 2),
                "距收盤高點比例": f"{round(current_price / high_close_3y * 100, 2)}%",
                "K值": round(current_k, 2),
                "D值": round(current_d, 2),
                "KD狀態": "剛黃金交叉" if crossed_up else "準備交叉向上",
            })
        except Exception as e:
            logger.warning("%s 計算發生錯誤: %s", sid, e)
            continue

    return pd.DataFrame(matched, columns=COLUMNS)

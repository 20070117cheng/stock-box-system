# -*- coding: utf-8 -*-
"""選股掃描，兩種模式（cfg["scan_mode"]）：

near_high（現行預設，沿用舊掃描腳本）：
1. 資料 ≥ 60 筆
2. 現價 ≥ 3年收盤高點 × high_threshold_pct/100
3. KD 剛金叉（昨 K<D、今 K≥D）或準備交叉（K≤D 且 D-K ≤ near_cross_gap）

pullback（創高回檔不破前高）：
1. 資料 ≥ 60 筆
2. 3年最高收盤價發生在近 pullback_recency_days 個交易日內
3. 現價 < 高點，回檔 ≤ pullback_max_pct %
4. 回檔期間最低收盤 > 當前箱體箱底（突破後新箱底＝突破前的舊箱頂）
5. KD 剛金叉（不含準備交叉）
"""
import datetime
import logging
from typing import Callable

import pandas as pd

from core.data import get_companies, load_prices
from core.indicators import calc_kd

logger = logging.getLogger(__name__)

COLUMNS = ["代號", "股名", "產業", "市場", "當前價", "3年高點", "距高點比例",
           "3年收盤高點", "距收盤高點比例", "K值", "D值", "KD狀態"]


def _check_near_high(df, cfg: dict) -> dict | None:
    """near_high 模式：貼近 3 年收盤高點 + KD 剛金叉／將金叉。"""
    threshold = float(cfg["high_threshold_pct"]) / 100.0
    near_gap = float(cfg["near_cross_gap"])

    high_close_3y = float(df["close"].max())
    current_price = float(df["close"].iloc[-1])
    if current_price < high_close_3y * threshold:
        return None

    df = calc_kd(df, period=int(cfg["kd_period"]))
    current_k = float(df["k"].iloc[-1])
    current_d = float(df["d"].iloc[-1])
    prev_k = float(df["k"].iloc[-2])
    prev_d = float(df["d"].iloc[-2])

    crossed_up = prev_k < prev_d and current_k >= current_d
    getting_close = (current_k <= current_d
                     and (current_d - current_k) <= near_gap)
    if not (crossed_up or getting_close):
        return None
    return {"K值": round(current_k, 2), "D值": round(current_d, 2),
            "KD狀態": "剛黃金交叉" if crossed_up else "準備交叉向上"}


def _check_pullback(df, cfg: dict) -> dict | None:
    """pullback 模式：剛創 3 年新高 → 小幅回檔不破前高 → KD 剛金叉。"""
    from core.backtest import _weekly_boxes  # 延遲載入避免循環相依疑慮

    recency = int(cfg["pullback_recency_days"])
    max_dd = float(cfg["pullback_max_pct"])

    closes = df["close"]
    hi = float(closes.max())
    hi_day = closes[closes == hi].index[-1]          # 最近一次創高日
    bars_since_hi = len(closes) - 1 - closes.index.get_loc(hi_day)
    if bars_since_hi < 1 or bars_since_hi > recency:
        return None                                   # 今天才創高（沒回檔）或創高太久

    current_price = float(closes.iloc[-1])
    drawdown_pct = (hi - current_price) / hi * 100.0
    if current_price >= hi or drawdown_pct > max_dd:
        return None

    # 回檔期間最低收盤要守住箱底（＝突破前的舊箱頂）
    low_since_hi = float(closes.loc[hi_day:].min())
    box_low_now = float(_weekly_boxes(df)["Box_Low"].iloc[-1])
    if low_since_hi <= box_low_now:
        return None

    df = calc_kd(df, period=int(cfg["kd_period"]))
    current_k = float(df["k"].iloc[-1])
    current_d = float(df["d"].iloc[-1])
    prev_k = float(df["k"].iloc[-2])
    prev_d = float(df["d"].iloc[-2])
    if not (prev_k < prev_d and current_k >= current_d):
        return None
    return {"K值": round(current_k, 2), "D值": round(current_d, 2),
            "KD狀態": f"回檔{drawdown_pct:.1f}%後剛金叉"}


_MODE_CHECKS = {"near_high": _check_near_high, "pullback": _check_pullback}


def scan(conn, cfg: dict, as_of: str | None = None,
         progress: Callable[[int, int], None] | None = None) -> pd.DataFrame:
    """全市場掃描，回傳符合條件的股票清單（欄位同舊 kd_scan_report）。

    as_of: 只用該日（含）之前的資料，預設今天。
    progress: 選用回呼，每處理一檔呼叫 progress(已處理數, 總數)。
    """
    ref_date = (datetime.datetime.strptime(as_of, "%Y-%m-%d")
                if as_of else datetime.datetime.today())
    three_years_ago = (ref_date - datetime.timedelta(days=3 * 365)
                       ).strftime("%Y-%m-%d")
    end = ref_date.strftime("%Y-%m-%d")

    check = _MODE_CHECKS[cfg.get("scan_mode", "near_high")]

    matched = []
    companies = get_companies(conn)
    total = len(companies)
    for pos, (_, comp) in enumerate(companies.iterrows(), start=1):
        if progress is not None:
            progress(pos, total)
        sid = comp["stock_id"]
        df = load_prices(conn, sid, start=three_years_ago, end=end)
        if df.empty or len(df) < 60:
            continue
        try:
            extra = check(df, cfg)
            if extra is None:
                continue
            high_3y = float(df["high"].max())
            high_close_3y = float(df["close"].max())
            current_price = float(df["close"].iloc[-1])
            row = {
                "代號": sid,
                "股名": comp["stock_name"],
                "產業": comp["industry"],
                "市場": comp["market"],
                "當前價": round(current_price, 2),
                "3年高點": round(high_3y, 2),
                "距高點比例": f"{round(current_price / high_3y * 100, 2)}%",
                "3年收盤高點": round(high_close_3y, 2),
                "距收盤高點比例": f"{round(current_price / high_close_3y * 100, 2)}%",
            }
            row.update(extra)
            matched.append(row)
        except Exception as e:
            logger.warning("%s 計算發生錯誤: %s", sid, e)
            continue

    return pd.DataFrame(matched, columns=COLUMNS)

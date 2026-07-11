# -*- coding: utf-8 -*-
"""大盤燈號：創近一年新高家數比率（邏輯同 stock-breakout-signals）。

比率高＝行情強。燈號＝現值在近一年序列的相對位置＋近一月趨勢：
綠＝前 30% 且不低於一個月前；紅＝後 30% 且低於一個月前；其餘黃。
"""
import pandas as pd

from core.data import get_companies, load_prices

HIGH_LOOKBACK = 245   # 「近一年新高」的回看交易日
TREND_DAYS = 20       # 「一個月前」


def new_high_ratio_series(conn, end: str, days: int = 245) -> pd.DataFrame:
    """回傳近 days 個交易日的每日創新高家數比率（index=日期）。

    單次全市場掃描：每檔股票算 rolling 245 日最高收盤，
    收盤等於它即為當日創新高。
    """
    start = (pd.to_datetime(end) - pd.Timedelta(days=730)).strftime("%Y-%m-%d")
    hits: list[pd.Series] = []
    actives: list[pd.Series] = []
    for _, comp in get_companies(conn).iterrows():
        df = load_prices(conn, comp["stock_id"], start=start, end=end)
        if df.empty or len(df) < 60:
            continue
        roll_max = df["close"].rolling(HIGH_LOOKBACK, min_periods=60).max()
        hits.append((df["close"] >= roll_max).astype(int))
        actives.append(pd.Series(1, index=df.index))
    if not hits:
        return pd.DataFrame(columns=["ratio", "new_highs", "active"])
    total_hits = pd.concat(hits, axis=1).sum(axis=1)
    total_active = pd.concat(actives, axis=1).sum(axis=1)
    out = pd.DataFrame({"new_highs": total_hits, "active": total_active})
    out["ratio"] = out["new_highs"] / out["active"] * 100.0
    return out.tail(days)


def market_light(series: pd.DataFrame) -> dict:
    """由比率序列判定燈號。回傳 {light, ratio, pct_rank, trend_up, advice}。"""
    if series.empty or len(series) < TREND_DAYS + 1:
        return {"light": "yellow", "ratio": None, "pct_rank": None,
                "trend_up": None, "advice": "資料不足，暫以黃燈處理"}
    r = series["ratio"]
    current = float(r.iloc[-1])
    pct_rank = float((r < current).mean() * 100.0)  # 嚴格比較：持平不算強
    trend_up = bool(current >= float(r.iloc[-(TREND_DAYS + 1)]))
    if pct_rank >= 70 and trend_up:
        light, advice = "green", "行情強——可依計畫買進（單檔上限＝總資金 10%）"
    elif pct_rank <= 30 and not trend_up:
        light, advice = "red", "創新高股稀少且走弱——建議空手等待"
    else:
        light, advice = "yellow", "行情普通——減量操作"
    return {"light": light, "ratio": round(current, 2),
            "pct_rank": round(pct_rank, 1), "trend_up": trend_up,
            "advice": advice}

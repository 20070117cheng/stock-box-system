# -*- coding: utf-8 -*-
"""參數優化：把一組參數的每日勝率表彙整成可比較的指標。

過度擬合防範：指標含前後半段拆分（前半找參數、後半驗證），
解讀時選「鄰近組合也不錯」的高原區，不選孤立尖峰。
"""
import pandas as pd


def summarize_winrates(wr: pd.DataFrame) -> dict:
    """彙整 compute_winrates 的輸出。

    只統計已結算（非發展中）且有進場的日子；前後半按日期序切。
    """
    settled = wr[(~wr["發展中"]) & wr["勝率_窗"].notna()].sort_values("選股日")
    half = len(settled) // 2
    first, second = settled.iloc[:half], settled.iloc[half:]
    now_days = wr[wr["勝率_今"].notna()]

    def _mean(df: pd.DataFrame, col: str) -> float | None:
        return round(float(df[col].mean()), 3) if len(df) else None

    return {
        "settled_days": int(len(settled)),
        "ret_mean": _mean(settled, "平均報酬_窗"),
        "winrate_mean": _mean(settled, "勝率_窗"),
        "ret_first": _mean(first, "平均報酬_窗"),
        "ret_second": _mean(second, "平均報酬_窗"),
        "winrate_first": _mean(first, "勝率_窗"),
        "winrate_second": _mean(second, "勝率_窗"),
        "ret_now_mean": _mean(now_days, "平均報酬_今"),
    }

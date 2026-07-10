# -*- coding: utf-8 -*-
"""勝率歷史：過去一年每個交易日的名單快取與後續勝率。

A 版（窗）：選股日 + winrate_window_months 個月結算——日與日可比、歷史凍結；
今天還沒走完窗的日子標「發展中」。
B 版（今）：算到資料最新日，當「目前戰況」看。
兩版取自同一次回測：回測從選股日跑到今天，途中在窗結算日取一次 snapshot。

名單快取的關鍵前提：過去日期的掃描只用該日（含）之前的資料，永不改變，
所以同參數算過一次就能重複用；會影響名單的參數（門檻/KD）改變時整份重建。
"""
import json
import logging
import os
from typing import Callable

import pandas as pd
from dateutil.relativedelta import relativedelta

from core.data import load_prices
from core.scanner import scan

logger = logging.getLogger(__name__)

# 快取用空字串代號標記「掃過但沒有入選股」的日子，避免每天重掃
SCAN_CACHE_COLUMNS = ["選股日", "代號", "股名", "當前價"]
WINRATE_COLUMNS = ["選股日", "入選檔數", "發展中",
                   "進場檔數_窗", "獲利檔數_窗", "勝率_窗", "平均報酬_窗",
                   "進場檔數_今", "獲利檔數_今", "勝率_今", "平均報酬_今"]


def trading_dates(conn, start: str, end: str) -> list[str]:
    """DB 內 start~end（含）之間有資料的日期清單。"""
    rows = conn.execute(
        "SELECT DISTINCT date FROM stock_price_daily "
        "WHERE date BETWEEN ? AND ? ORDER BY date", (start, end)).fetchall()
    return [r[0] for r in rows]


def scan_params(cfg: dict) -> dict:
    """會影響選股名單的參數（用來判斷快取是否失效）。"""
    params = {"scan_mode": cfg.get("scan_mode", "near_high"),
              "high_threshold_pct": float(cfg["high_threshold_pct"]),
              "kd_period": int(cfg["kd_period"]),
              "near_cross_gap": float(cfg["near_cross_gap"])}
    if params["scan_mode"] == "pullback":
        params.update({
            "pullback_max_pct": float(cfg["pullback_max_pct"]),
            "pullback_recency_days": int(cfg["pullback_recency_days"])})
    elif params["scan_mode"] == "surge":
        params.update({
            "surge_lookback_days": int(cfg["surge_lookback_days"]),
            "surge_rebound_min_pct": float(cfg["surge_rebound_min_pct"])})
    return params


def update_scan_cache(conn, cfg: dict, dates: list[str],
                      cache_df: pd.DataFrame | None,
                      progress: Callable[[int, int], None] | None = None
                      ) -> pd.DataFrame:
    """補掃快取缺少的日期，回傳合併後快取（裁掉 dates 範圍外的舊日子）。"""
    if cache_df is None or cache_df.empty:
        cache_df = pd.DataFrame(columns=SCAN_CACHE_COLUMNS)
    have = set(cache_df["選股日"])
    missing = [d for d in dates if d not in have]
    frames = [cache_df]
    for i, d in enumerate(missing, start=1):
        if progress:
            progress(i, len(missing))
        df = scan(conn, cfg, as_of=d)
        if df.empty:
            rows = pd.DataFrame([{"選股日": d, "代號": "", "股名": "",
                                  "當前價": 0.0}])
        else:
            rows = df[["代號", "股名", "當前價"]].copy()
            rows.insert(0, "選股日", d)
        frames.append(rows)
    merged = pd.concat(frames, ignore_index=True)
    merged = merged[merged["選股日"].isin(set(dates))].reset_index(drop=True)
    return merged[SCAN_CACHE_COLUMNS]


def compute_winrates(conn, cfg: dict, scans_df: pd.DataFrame, today: str,
                     progress: Callable[[int, int], None] | None = None
                     ) -> pd.DataFrame:
    """對快取名單逐日逐檔回測（選股日 → 今天），彙整每日勝率（A窗/B今）。"""
    from core.backtest import run_backtest  # 延遲載入，同 jobs.daily

    window_m = int(cfg["winrate_window_months"])
    today_ts = pd.to_datetime(today)
    stocks = scans_df[scans_df["代號"] != ""]
    days = sorted(set(scans_df["選股日"]))
    groups = {d: g for d, g in stocks.groupby("選股日")}
    price_cache: dict[str, pd.DataFrame] = {}
    earliest = ((pd.to_datetime(days[0]) - relativedelta(years=1))
                .strftime("%Y-%m-%d") if days else today)

    def _prices(sid: str) -> pd.DataFrame:
        if sid not in price_cache:
            price_cache[sid] = load_prices(conn, sid, start=earliest, end=today)
        return price_cache[sid]

    out = []
    for j, d in enumerate(days, start=1):
        if progress:
            progress(j, len(days))
        d_ts = pd.to_datetime(d)
        win_end = d_ts + relativedelta(months=window_m)
        developing = win_end > today_ts
        g = groups.get(d)
        row = {"選股日": d, "入選檔數": 0 if g is None else len(g),
               "發展中": developing,
               "進場檔數_窗": None, "獲利檔數_窗": None,
               "勝率_窗": None, "平均報酬_窗": None,
               "進場檔數_今": 0, "獲利檔數_今": 0,
               "勝率_今": None, "平均報酬_今": None}

        win_returns, now_returns = [], []
        win_wins = now_wins = win_entered = now_entered = 0
        rows_iter = [] if g is None else list(g.iterrows())
        for _, r in rows_iter:
            sid = r["代號"]
            try:
                prices = _prices(sid)
                sliced = prices[prices.index >= d_ts - relativedelta(years=1)]
                if sliced.empty:
                    continue
                bt = run_backtest(sliced, d, cfg)
                daily = bt.daily
                if daily.empty:
                    continue
                # B 版：最後一列
                last = daily.iloc[-1]
                if (daily["持股張數"] > 0).any():
                    now_entered += 1
                    if float(last["損益金額"]) > 0:
                        now_wins += 1
                    now_returns.append(float(last["損益獲利率%"]))
                # A 版：窗結算日（或之前最後交易日）那列
                if not developing:
                    win_daily = daily[daily.index <= win_end]
                    if not win_daily.empty and (win_daily["持股張數"] > 0).any():
                        win_entered += 1
                        w_last = win_daily.iloc[-1]
                        if float(w_last["損益金額"]) > 0:
                            win_wins += 1
                        win_returns.append(float(w_last["損益獲利率%"]))
            except Exception as e:
                logger.warning("%s %s 勝率回測失敗: %s", d, sid, e)

        row["進場檔數_今"] = now_entered
        row["獲利檔數_今"] = now_wins
        if now_entered:
            row["勝率_今"] = round(now_wins / now_entered * 100, 1)
            row["平均報酬_今"] = round(sum(now_returns) / len(now_returns), 2)
        if not developing:
            row["進場檔數_窗"] = win_entered
            row["獲利檔數_窗"] = win_wins
            if win_entered:
                row["勝率_窗"] = round(win_wins / win_entered * 100, 1)
                row["平均報酬_窗"] = round(sum(win_returns) / len(win_returns), 2)
        out.append(row)

    df = pd.DataFrame(out, columns=WINRATE_COLUMNS)
    num_cols = [c for c in WINRATE_COLUMNS if c not in ("選股日", "發展中")]
    df[num_cols] = df[num_cols].astype(float)  # None→NaN，parquet 才存得穩
    return df


def refresh(conn, cfg: dict, history_dir: str, today: str,
            scan_progress: Callable[[int, int], None] | None = None,
            bt_progress: Callable[[int, int], None] | None = None) -> dict:
    """完整更新勝率歷史：補掃快取 → 重算勝率 → 存檔。回傳統計。"""
    os.makedirs(history_dir, exist_ok=True)
    scans_path = os.path.join(history_dir, "scans.parquet")
    winrates_path = os.path.join(history_dir, "winrates.parquet")
    meta_path = os.path.join(history_dir, "meta.json")

    start = (pd.to_datetime(today) - relativedelta(years=1)).strftime("%Y-%m-%d")
    dates = trading_dates(conn, start, today)

    cache_df = None
    params = scan_params(cfg)
    if os.path.exists(scans_path) and os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("scan_params") == params:
            cache_df = pd.read_parquet(scans_path)
        else:
            logger.info("選股參數已變（%s → %s），重建名單快取",
                        meta.get("scan_params"), params)

    before = 0 if cache_df is None else len(set(cache_df["選股日"]))
    cache_df = update_scan_cache(conn, cfg, dates, cache_df,
                                 progress=scan_progress)
    winrates = compute_winrates(conn, cfg, cache_df, today,
                                progress=bt_progress)

    cache_df.to_parquet(scans_path)
    winrates.to_parquet(winrates_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"scan_params": params,
                   "winrate_window_months": int(cfg["winrate_window_months"]),
                   "updated": today}, f, ensure_ascii=False, indent=2)

    return {"days": len(dates), "new_scans": len(set(cache_df["選股日"])) - before,
            "winrate_days": len(winrates)}

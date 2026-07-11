# -*- coding: utf-8 -*-
"""虛擬操盤：用虛擬資金照系統訊號每日模擬零股買賣。

狀態（cash、持股）存 JSON；交易與資金曲線各存 CSV 累加。
規則見 docs/superpowers/specs/2026-07-11-portfolio-features-design.md。
"""
import json
import logging
import os

import pandas as pd
from dateutil.relativedelta import relativedelta

from core.backtest import run_backtest
from core.data import load_prices
from core.position import buy_cost, sell_net, suggest_shares

logger = logging.getLogger(__name__)


def load_state(paper_dir: str, capital: float) -> dict:
    path = os.path.join(paper_dir, "state.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"cash": capital, "holdings": {}}


def save_state(paper_dir: str, state: dict) -> None:
    os.makedirs(paper_dir, exist_ok=True)
    with open(os.path.join(paper_dir, "state.json"), "w",
              encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _append_csv(path: str, rows: list[dict], columns: list[str]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows, columns=columns)
    header = not os.path.exists(path)
    df.to_csv(path, mode="a", header=header, index=False,
              encoding="utf-8-sig")


def run_day(conn, cfg: dict, scan_df: pd.DataFrame, as_of: str,
            paper_dir: str) -> dict:
    """跑一天的虛擬操盤。回傳統計。冪等：同日重跑會先移除當日紀錄。"""
    os.makedirs(paper_dir, exist_ok=True)
    cur = load_state(paper_dir, float(cfg["total_capital"]))
    prev_path = os.path.join(paper_dir, "state_prev.json")
    # 冪等：同日重跑（排程一天可能觸發兩次）→ 從前一日狀態重新算這一天
    if cur.get("date") == as_of and os.path.exists(prev_path):
        with open(prev_path, encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = cur
    day_start_state = json.loads(json.dumps(state))  # 深複製當日起點

    for fname in ("trades.csv", "equity.csv"):
        p = os.path.join(paper_dir, fname)
        if os.path.exists(p):
            df = pd.read_csv(p, encoding="utf-8-sig", dtype={"代號": str})
            df = df[df["日期"] != as_of]
            df.to_csv(p, index=False, encoding="utf-8-sig")

    trades: list[dict] = []
    start_6m = (pd.to_datetime(as_of)
                - relativedelta(months=int(cfg["default_lookback_months"])))
    extended = (start_6m - relativedelta(years=1)).strftime("%Y-%m-%d")
    closes: dict[str, float] = {}

    # 1) 持股檢查：策略喊出場就全數賣出
    for sid in list(state["holdings"].keys()):
        h = state["holdings"][sid]
        try:
            ext = (pd.to_datetime(h["entry_date"])
                   - relativedelta(years=1)).strftime("%Y-%m-%d")
            prices = load_prices(conn, sid, start=ext, end=as_of)
            if prices.empty:
                continue
            closes[sid] = float(prices["close"].iloc[-1])
            cfg_h = dict(cfg)
            cfg_h.update({"entry_price": h["cost"],
                          "initial_size": h["shares"] / 1000.0,
                          "add_position_size": 0.0})
            bt = run_backtest(prices, h["entry_date"], cfg_h)
            last = bt.daily.iloc[-1]
            if (last.name.strftime("%Y-%m-%d") == as_of
                    and str(last["訊號狀態"]) == "出場"):
                price = float(last["close"])
                proceeds = sell_net(price, h["shares"])
                state["cash"] += proceeds
                trades.append({"日期": as_of, "動作": "賣出", "代號": sid,
                               "價格": price, "股數": h["shares"],
                               "金額": round(proceeds),
                               "原因": str(last["進出場原因說明"])})
                del state["holdings"][sid]
        except Exception as e:
            logger.warning("虛擬操盤 %s 持股檢查失敗: %s", sid, e)

    # 2) 新買：今日訊號=重返進場、未持有、額度內
    new_bought = 0
    max_new = int(cfg["paper_max_new_per_day"])
    if scan_df is not None and not scan_df.empty:
        for _, r in scan_df.iterrows():
            if new_bought >= max_new:
                break
            sid = str(r["代號"])
            if sid in state["holdings"]:
                continue
            try:
                prices = load_prices(conn, sid, start=extended, end=as_of)
                if prices.empty:
                    continue
                bt = run_backtest(prices, start_6m.strftime("%Y-%m-%d"), cfg)
                last = bt.daily.iloc[-1]
                if (last.name.strftime("%Y-%m-%d") != as_of
                        or str(last["訊號狀態"]) != "重返進場"):
                    continue
                price = float(last["close"])
                shares = suggest_shares(price, float(cfg["total_capital"]),
                                        float(cfg["position_pct"]))
                if shares < 1:
                    continue
                cost = buy_cost(price, shares)
                if cost > state["cash"]:
                    continue
                state["cash"] -= cost
                state["holdings"][sid] = {
                    "shares": shares, "cost": price, "entry_date": as_of,
                    "name": str(r["股名"])}
                closes[sid] = price
                trades.append({"日期": as_of, "動作": "買進", "代號": sid,
                               "價格": price, "股數": shares,
                               "金額": round(cost),
                               "原因": "系統進場訊號（重返進場）"})
                new_bought += 1
            except Exception as e:
                logger.warning("虛擬操盤 %s 買進評估失敗: %s", sid, e)

    # 3) 結算資金曲線
    value = state["cash"]
    for sid, h in state["holdings"].items():
        if sid not in closes:
            p = load_prices(conn, sid, start=as_of[:4] + "-01-01", end=as_of)
            closes[sid] = float(p["close"].iloc[-1]) if not p.empty \
                else h["cost"]
        value += closes[sid] * h["shares"]

    _append_csv(os.path.join(paper_dir, "trades.csv"), trades,
                ["日期", "動作", "代號", "價格", "股數", "金額", "原因"])
    _append_csv(os.path.join(paper_dir, "equity.csv"),
                [{"日期": as_of, "總值": round(value),
                  "現金": round(state["cash"]),
                  "持股檔數": len(state["holdings"])}],
                ["日期", "總值", "現金", "持股檔數"])
    with open(prev_path, "w", encoding="utf-8") as f:
        json.dump(day_start_state, f, ensure_ascii=False, indent=2)
    state["date"] = as_of
    save_state(paper_dir, state)

    return {"trades": len(trades), "holdings": len(state["holdings"]),
            "cash": round(state["cash"]), "value": round(value)}

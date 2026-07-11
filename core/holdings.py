# -*- coding: utf-8 -*-
"""持股監控：對 holdings.csv 的每檔實際持股跑箱型規則，產生每日警示。

holdings.csv 欄位：stock_id,buy_date,cost,shares（成本=每股、股數=股）。
"""
import logging

import pandas as pd
from dateutil.relativedelta import relativedelta

from core.backtest import run_backtest
from core.data import get_stock_name, load_prices

logger = logging.getLogger(__name__)

COLUMNS = ["代號", "股名", "買進日", "成本", "股數", "現價", "未實現損益",
           "報酬%", "訊號狀態", "移動停利線", "固定停損線", "警示", "說明"]

_ALERT = {"出場": "賣出", "續抱(轉弱)": "注意", "加碼": "加碼機會"}


def build_report(conn, cfg: dict, holdings: pd.DataFrame,
                 as_of: str) -> pd.DataFrame:
    """對每檔持股跑回測（承接既有部位），回傳警示報告。"""
    rows = []
    for _, h in holdings.iterrows():
        sid = str(h["stock_id"]).strip()
        try:
            buy_date = str(h["buy_date"])
            cost = float(h["cost"])
            shares = int(h["shares"])
            extended = (pd.to_datetime(buy_date)
                        - relativedelta(years=1)).strftime("%Y-%m-%d")
            prices = load_prices(conn, sid, start=extended, end=as_of)
            if prices.empty:
                continue
            cfg_h = dict(cfg)
            cfg_h.update({"entry_price": cost,
                          "initial_size": shares / 1000.0,
                          "add_position_size": 0.0})
            bt = run_backtest(prices, buy_date, cfg_h)
            if bt.daily.empty:
                continue
            last = bt.daily.iloc[-1]
            close = float(last["close"])
            pnl = (close - cost) * shares
            status = str(last["訊號狀態"])
            reason = str(last["進出場原因說明"])
            # 策略早幾天已喊出場、但使用者實際仍持有 → 維持賣出警示
            if float(last["持股張數"]) == 0:
                exits = bt.daily[bt.daily["訊號狀態"] == "出場"]
                if not exits.empty:
                    exit_day = exits.index[-1].strftime("%Y-%m-%d")
                    status = f"已於 {exit_day} 觸發出場"
                    reason = str(exits.iloc[-1]["進出場原因說明"])
            rows.append({
                "代號": sid, "股名": get_stock_name(conn, sid),
                "買進日": buy_date, "成本": cost, "股數": shares,
                "現價": close, "未實現損益": round(pnl),
                "報酬%": round((close / cost - 1) * 100, 2),
                "訊號狀態": status,
                "移動停利線": round(float(last["移動停利線"]), 2),
                "固定停損線": round(float(last["固定停損線"]), 2),
                "警示": ("賣出" if status.startswith("已於")
                         else _ALERT.get(status, "持有")),
                "說明": reason,
            })
        except Exception as e:
            logger.warning("持股 %s 監控失敗: %s", sid, e)
    return pd.DataFrame(rows, columns=COLUMNS)

# -*- coding: utf-8 -*-
"""零股、大盤燈號、持股監控、虛擬操盤的行為測試。"""
import numpy as np
import pandas as pd

from core.config import DEFAULTS
from core.holdings import build_report
from core.market import market_light, new_high_ratio_series
from core.paper import load_state, run_day
from core.position import buy_cost, sell_net, suggest_shares


def _insert(db, sid, closes, start="2026-01-05"):
    dates = pd.bdate_range(start, periods=len(closes))
    rows = [(sid, dt.strftime("%Y-%m-%d"), float(c), float(c) * 1.01,
             float(c) * 0.99, float(c), 5000) for dt, c in zip(dates, closes)]
    db.executemany(
        "INSERT OR REPLACE INTO stock_price_daily VALUES (?,?,?,?,?,?,?)", rows)
    db.commit()


# ---------- 零股 ----------
def test_suggest_shares():
    assert suggest_shares(1080, 50000, 10) == 4      # 5000/1080 → 4 股
    assert suggest_shares(35.5, 50000, 10) == 140
    assert suggest_shares(6000, 50000, 10) == 0      # 買不起 1 股


def test_odd_lot_costs_use_min_fee():
    cost = buy_cost(100, 10)          # 1000 元，手續費低消 20
    assert cost == 1000 + 20
    net = sell_net(100, 10)           # 賣出再扣 0.3% 證交稅
    assert net == 1000 - 20 - 3


# ---------- 大盤燈號 ----------
def test_new_high_ratio_and_light(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    _insert(db, "2330", list(np.linspace(100, 150, 80)))   # 一路創高
    _insert(db, "6488", list(np.linspace(150, 100, 80)))   # 一路下跌
    series = new_high_ratio_series(db, "2026-12-31", days=80)
    assert not series.empty
    # 最後一天：2330 創高、6488 沒有 → 比率 50%
    assert series["ratio"].iloc[-1] == 50.0

    up = pd.DataFrame({"ratio": list(np.linspace(1, 10, 60))})
    assert market_light(up)["light"] == "green"
    down = pd.DataFrame({"ratio": list(np.linspace(10, 1, 60))})
    assert market_light(down)["light"] == "red"
    flat = pd.DataFrame({"ratio": [5.0] * 60})
    assert market_light(flat)["light"] == "yellow"


# ---------- 持股監控 ----------
def test_holdings_alert_on_stop_loss(db):
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    # 買在 100，之後跌破固定停損（3%）→ 警示=賣出
    closes = [100.0] * 60 + [100, 99, 98, 96.5]
    _insert(db, "2330", closes)
    buy_date = pd.bdate_range("2026-01-05", periods=61)[-1].strftime("%Y-%m-%d")
    holdings = pd.DataFrame([{"stock_id": "2330", "buy_date": buy_date,
                              "cost": 100.0, "shares": 40}])
    rep = build_report(db, dict(DEFAULTS), holdings, "2026-12-31")
    assert len(rep) == 1
    assert rep.iloc[0]["警示"] == "賣出"
    assert rep.iloc[0]["未實現損益"] == round((96.5 - 100) * 40)


# ---------- 虛擬操盤 ----------
def _paper_db(db):
    """整理 13 週後隔週一跳空突破 → 突破日訊號=重返進場。"""
    db.execute("DELETE FROM stock_price_daily")
    db.commit()
    _insert(db, "2330", [100.0] * 65 + [106.0])


def test_paper_buys_on_entry_signal_and_sells_on_exit(db, tmp_path):
    _paper_db(db)
    paper_dir = str(tmp_path / "paper")
    cfg = dict(DEFAULTS)
    days = pd.bdate_range("2026-01-05", periods=67)
    entry_day = days[65].strftime("%Y-%m-%d")
    scan_df = pd.DataFrame([{"代號": "2330", "股名": "台積電"}])

    stats = run_day(db, cfg, scan_df, entry_day, paper_dir)
    state = load_state(paper_dir, 50000)
    assert stats["trades"] == 1 and "2330" in state["holdings"]
    assert state["holdings"]["2330"]["shares"] == 47   # 5000/106
    assert state["cash"] < 50000

    # 隔日崩跌破停損 → 賣出、現金回流
    _insert(db, "2330", [100.0] * 65 + [106.0, 95.0])
    exit_day = days[66].strftime("%Y-%m-%d")
    stats2 = run_day(db, cfg, None, exit_day, paper_dir)
    state2 = load_state(paper_dir, 50000)
    assert stats2["trades"] == 1 and state2["holdings"] == {}
    trades = pd.read_csv(paper_dir + "/trades.csv", encoding="utf-8-sig")
    assert list(trades["動作"]) == ["買進", "賣出"]


def test_paper_rerun_same_day_is_idempotent(db, tmp_path):
    _paper_db(db)
    paper_dir = str(tmp_path / "paper")
    cfg = dict(DEFAULTS)
    entry_day = pd.bdate_range("2026-01-05", periods=66)[-1].strftime("%Y-%m-%d")
    scan_df = pd.DataFrame([{"代號": "2330", "股名": "台積電"}])
    run_day(db, cfg, scan_df, entry_day, paper_dir)
    run_day(db, cfg, scan_df, entry_day, paper_dir)   # 同日重跑
    trades = pd.read_csv(paper_dir + "/trades.csv", encoding="utf-8-sig")
    equity = pd.read_csv(paper_dir + "/equity.csv", encoding="utf-8-sig")
    assert len(trades) == 1 and len(equity) == 1
    state = load_state(paper_dir, 50000)
    assert state["holdings"]["2330"]["shares"] == 47

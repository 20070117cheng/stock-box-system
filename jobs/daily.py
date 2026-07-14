# -*- coding: utf-8 -*-
"""每日排程入口：更新股價 → 掃描 → 對名單回測 → 存結果。

用法：
    python -m jobs.daily --db tw_stock_v2.db --output-dir outputs
    可選 --date YYYY-MM-DD（預設今天）、--config config.json、--skip-update
"""
import argparse
import datetime
import json
import logging
import os
import sqlite3

from dateutil.relativedelta import relativedelta  # pandas 相依已含 python-dateutil

from core.config import load_config
from core.data import get_companies, load_prices, update_prices
from core.scanner import scan

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run(db_path: str, output_dir: str, date: str | None = None,
        cfg: dict | None = None, skip_update: bool = False,
        skip_history: bool = False, skip_portfolio: bool = False) -> dict:
    """跑完整每日流程，回傳統計 dict。任何單檔失敗記 log 續跑。"""
    import pandas as pd

    from core.backtest import run_backtest  # 延遲載入，避免測試時拉 matplotlib
    from core.history import refresh

    cfg = cfg or load_config("config.json")
    date = date or datetime.datetime.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(db_path)

    result = {"date": date, "scanned": 0, "backtested": 0, "errors": []}
    try:
        if not skip_update:
            from core.data import dates_needing_update, update_prices_official
            comps = get_companies(conn)
            # 主要來源：證交所/櫃買官方 API（yfinance 在 Actions 機房 IP 被擋）
            need = dates_needing_update(conn, date)
            if need:
                official = update_prices_official(conn, comps, need)
                result["update_official"] = official
            # 備援：yfinance 增量（官方已補齊時會全數 skip，成本近零）
            stats = update_prices(conn, comps, today=date)
            logger.info("股價更新：%s", stats)
            result["update"] = stats

        scan_df = scan(conn, cfg, as_of=date)
        result["scanned"] = len(scan_df)
        logger.info("掃描完成：%d 檔入選", len(scan_df))

        day_dir = os.path.join(output_dir, date)
        os.makedirs(day_dir, exist_ok=True)
        scan_df.to_parquet(os.path.join(day_dir, "scan.parquet"))

        # 回測起算日 = date 回推 N 個月
        start_dt = (datetime.datetime.strptime(date, "%Y-%m-%d")
                    - relativedelta(months=int(cfg["default_lookback_months"])))
        start = start_dt.strftime("%Y-%m-%d")
        # KD 與箱體需要暖身，再往前抓一年
        extended = (start_dt - relativedelta(years=1)).strftime("%Y-%m-%d")

        tomorrow_desc = {}
        for sid in scan_df["代號"]:
            try:
                prices = load_prices(conn, sid, start=extended, end=date)
                if prices.empty:
                    result["errors"].append(f"{sid}: 無價格資料")
                    continue
                bt = run_backtest(prices, start, cfg)
                bt.daily.to_parquet(os.path.join(day_dir, f"bt_{sid}.parquet"))
                tomorrow_desc[sid] = bt.tomorrow_desc
                result["backtested"] += 1
            except Exception as e:
                logger.exception("%s 回測失敗", sid)
                result["errors"].append(f"{sid}: {e}")

        meta = {
            "date": date,
            "backtest_start": start,
            "config": cfg,
            "tomorrow_desc": tomorrow_desc,
        }
        with open(os.path.join(day_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        if not skip_portfolio:
            from core.holdings import build_report
            from core.market import market_light, new_high_ratio_series
            from core.paper import run_day

            series = new_high_ratio_series(conn, date)
            series.to_parquet(os.path.join(output_dir, "market.parquet"))
            light = market_light(series)
            with open(os.path.join(output_dir, "market_light.json"), "w",
                      encoding="utf-8") as f:
                json.dump(light, f, ensure_ascii=False, indent=2)
            result["market"] = light["light"]
            logger.info("大盤燈號：%s", light)

            if os.path.exists("holdings.csv"):
                holdings = pd.read_csv("holdings.csv",
                                       dtype={"stock_id": str})
                if not holdings.empty:
                    rep = build_report(conn, cfg, holdings, date)
                    rep.to_parquet(os.path.join(output_dir,
                                                "holdings_report.parquet"))
                    result["holdings"] = len(rep)
                    logger.info("持股監控：%d 檔", len(rep))

            paper_stats = run_day(conn, cfg, scan_df, date,
                                  os.path.join(output_dir, "paper"))
            result["paper"] = paper_stats
            logger.info("虛擬操盤：%s", paper_stats)

        if not skip_history:
            def _sp(done, total):
                if done % 10 == 0 or done == total:
                    logger.info("勝率歷史：補掃名單 %d/%d", done, total)

            def _bp(done, total):
                if done % 25 == 0 or done == total:
                    logger.info("勝率歷史：逐日回測 %d/%d", done, total)

            hist_stats = refresh(conn, cfg,
                                 os.path.join(output_dir, "history"), date,
                                 scan_progress=_sp, bt_progress=_bp)
            result["history"] = hist_stats
            logger.info("勝率歷史更新：%s", hist_stats)

        logger.info("每日流程完成：%s", {k: v for k, v in result.items() if k != "errors"})
        if result["errors"]:
            logger.warning("錯誤清單：%s", result["errors"])
    finally:
        conn.close()
    return result


def main():
    parser = argparse.ArgumentParser(description="每日更新+掃描+回測")
    parser.add_argument("--db", required=True, help="SQLite 資料庫路徑")
    parser.add_argument("--output-dir", required=True, help="結果輸出資料夾")
    parser.add_argument("--date", default=None, help="基準日 YYYY-MM-DD，預設今天")
    parser.add_argument("--config", default="config.json", help="參數檔路徑")
    parser.add_argument("--skip-update", action="store_true", help="跳過股價更新")
    parser.add_argument("--skip-history", action="store_true", help="跳過勝率歷史更新")
    parser.add_argument("--skip-portfolio", action="store_true",
                        help="跳過燈號/持股監控/虛擬操盤")
    args = parser.parse_args()

    run(args.db, args.output_dir, date=args.date,
        cfg=load_config(args.config), skip_update=args.skip_update,
        skip_history=args.skip_history, skip_portfolio=args.skip_portfolio)


if __name__ == "__main__":
    main()

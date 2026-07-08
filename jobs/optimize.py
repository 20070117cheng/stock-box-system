# -*- coding: utf-8 -*-
"""參數優化單組合入口：沿用歷史名單快取，換停利停損重算整年勝率。

用法（每個 Actions matrix job 跑一組）：
    python -m jobs.optimize --db tw_stock_v2.db \
        --scans outputs/history/scans.parquet \
        --stop-profit 10 --fixed-loss 3 --out opt_out
"""
import argparse
import json
import logging
import os
import sqlite3

import pandas as pd

from core.config import load_config
from core.history import compute_winrates
from core.optimize import summarize_winrates

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run(db_path: str, scans_path: str, stop_profit: float, fixed_loss: float,
        out_dir: str) -> dict:
    cfg = load_config("config.json")
    cfg.update({"stop_profit_pct": stop_profit, "fixed_loss_pct": fixed_loss})

    scans = pd.read_parquet(scans_path)
    conn = sqlite3.connect(db_path)
    try:
        today = conn.execute(
            "SELECT MAX(date) FROM stock_price_daily").fetchone()[0]

        def _prog(done, total):
            if done % 25 == 0 or done == total:
                logger.info("回測 %d/%d", done, total)

        wr = compute_winrates(conn, cfg, scans, today, progress=_prog)
    finally:
        conn.close()

    result = {"stop_profit_pct": stop_profit, "fixed_loss_pct": fixed_loss,
              "today": today}
    result.update(summarize_winrates(wr))

    os.makedirs(out_dir, exist_ok=True)
    name = f"sp{stop_profit:g}_fl{fixed_loss:g}.json"
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("完成：%s", result)
    return result


def main():
    p = argparse.ArgumentParser(description="單組停利停損整年重算")
    p.add_argument("--db", required=True)
    p.add_argument("--scans", required=True, help="歷史名單快取 parquet")
    p.add_argument("--stop-profit", type=float, required=True)
    p.add_argument("--fixed-loss", type=float, required=True)
    p.add_argument("--out", required=True, help="結果 JSON 輸出資料夾")
    a = p.parse_args()
    run(a.db, a.scans, a.stop_profit, a.fixed_loss, a.out)


if __name__ == "__main__":
    main()

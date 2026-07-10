# -*- coding: utf-8 -*-
"""指定掃描模式回填勝率歷史（A/B 對比用）。

用法：
    python -m jobs.backfill_history --db tw_stock_v2.db \
        --out outputs/history_pullback --mode pullback
"""
import argparse
import logging
import sqlite3

from core.config import load_config
from core.history import refresh

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    p = argparse.ArgumentParser(description="指定模式回填勝率歷史")
    p.add_argument("--db", required=True)
    p.add_argument("--out", required=True, help="歷史輸出資料夾")
    p.add_argument("--mode", default="pullback",
                   choices=["near_high", "pullback", "surge"])
    p.add_argument("--filters", default="",
                   help="逗號分隔的疊加過濾，如 volume,regime,rs")
    p.add_argument("--config", default="config.json")
    a = p.parse_args()

    cfg = load_config(a.config)
    cfg["scan_mode"] = a.mode
    cfg["scan_filters"] = [f.strip() for f in a.filters.split(",") if f.strip()]
    conn = sqlite3.connect(a.db)
    try:
        today = conn.execute(
            "SELECT MAX(date) FROM stock_price_daily").fetchone()[0]

        def _sp(done, total):
            if done % 10 == 0 or done == total:
                logger.info("補掃名單 %d/%d", done, total)

        def _bp(done, total):
            if done % 25 == 0 or done == total:
                logger.info("逐日回測 %d/%d", done, total)

        stats = refresh(conn, cfg, a.out, today,
                        scan_progress=_sp, bt_progress=_bp)
        logger.info("完成：%s", stats)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

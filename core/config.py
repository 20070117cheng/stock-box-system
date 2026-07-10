# -*- coding: utf-8 -*-
"""所有可調參數集中處。網頁與排程都從這裡讀預設值，config.json 可覆蓋。"""
import json
import os

DEFAULTS = {
    "stop_profit_pct": 10.0,        # 移動停利 %
    "fixed_loss_pct": 3.0,          # 固定停損 %
    "high_threshold_pct": 95.0,     # 距3年收盤高點門檻 %
    "add_position_size": 1.0,       # 每次加碼張數
    "initial_size": 1.0,            # 初始買進張數
    "default_lookback_months": 6,   # 每日自動回測的買入日回推月數
    "kd_period": 9,                 # KD 期數
    "near_cross_gap": 2.0,          # 「準備交叉」的 D-K 最大差距
    "winrate_window_months": 3,     # 勝率歷史的固定觀察窗（月）
    "scan_mode": "near_high",       # near_high=貼近高點｜pullback=創高回檔不破前高
    "pullback_max_pct": 7.0,        # pullback：距 3 年高回檔上限 %
    "pullback_recency_days": 20,    # pullback：3 年高需發生在近 N 個交易日內
}


def load_config(path: str | None = None) -> dict:
    """回傳 DEFAULTS 疊上 json 檔內容；檔案不存在時即為 DEFAULTS。"""
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def save_config(cfg: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

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
    "scan_mode": "near_high",       # near_high=貼近高點｜pullback=創高回檔｜surge=大漲訊號
    "pullback_max_pct": 7.0,        # pullback：距 3 年高回檔上限 %
    "pullback_recency_days": 20,    # pullback：3 年高需發生在近 N 個交易日內
    "surge_lookback_days": 490,     # surge：突破近 N 個交易日高（書 p.63 約 2 年）
    "surge_rebound_min_pct": 60.0,  # surge：反彈幅度下限 %（書 p.70 買股公式2）
    "scan_filters": [],             # 疊加過濾：volume=量能｜regime=大盤濾網｜rs=相對強度
    "volume_surge_ratio": 1.5,      # volume：訊號日成交量 ≥ N 日均量 × 此倍數
    "volume_avg_days": 20,          # volume：均量天數
    "regime_symbol": "0050",        # regime：大盤代理標的
    "regime_ma_days": 200,          # regime：代理標的需站上 N 日均線
    "rs_top_pct": 20.0,             # rs：3個月報酬需排全市場前 N%
    "rs_lookback_days": 60,         # rs：報酬回看交易日數
    "total_capital": 50000,         # 總資金（零股建議股數用）
    "position_pct": 10.0,           # 單檔上限 %（總資金 × 此比例）
    "paper_max_new_per_day": 2,     # 虛擬操盤：每日最多新買檔數
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

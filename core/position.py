# -*- coding: utf-8 -*-
"""零股部位工具：建議股數與股數計的交易成本。

calculate_tw_cost 以「張」為單位（×1000），傳入 股數/1000 即為股數計，
數學上精確；手續費低消 20 元對小額零股偏保守（多數券商零股低消 1 元），
寧可低估獲利。
"""
import math

from core.backtest import calculate_tw_cost


def suggest_shares(price: float, capital: float, position_pct: float) -> int:
    """依總資金與單檔上限 % 回傳建議股數（無條件捨去）。"""
    if price <= 0:
        return 0
    return int(math.floor(capital * position_pct / 100.0 / price))


def buy_cost(price: float, shares: int) -> float:
    """買進 shares 股的總支出（含手續費）。"""
    return calculate_tw_cost(price, shares / 1000.0, is_buy=True)


def sell_net(price: float, shares: int) -> float:
    """賣出 shares 股的淨收入（扣手續費與證交稅）。"""
    return calculate_tw_cost(price, shares / 1000.0, is_buy=False)

# -*- coding: utf-8 -*-
"""達瓦斯箱型策略回測核心。

從舊腳本《批次回測報告.py》移植的純函式版本，策略規則不變：
- 週箱（W-FRI 收盤）：突破箱頂 → 新箱 [舊箱頂, 新高]；跌破箱底 → 新箱 [新低, 舊箱底]
- 進場：收盤突破箱頂 且 KD 多頭 且 當週低點高於前週低點
- 出場優先序：破固定停損 → 破箱底 → 破箱頂 95% 緩衝 → 破移動停利
- 加碼：KD 金叉 且 持股賺錢 且 週低點抬高
- 成本：手續費 0.1425%×0.6（最低 20 元）、賣出加證交稅 0.3%
"""
from dataclasses import dataclass

import pandas as pd

from core.indicators import calc_kd


@dataclass
class BacktestResult:
    daily: pd.DataFrame     # index=日期，含價格、KD、箱體、訊號、損益等欄
    tomorrow_desc: str      # 明日交易提示


def calculate_tw_cost(price: float, shares: float, is_buy: bool = True) -> float:
    """台股交易成本（張數計）。"""
    total_shares = shares * 1000
    raw_amount = price * total_shares
    fee = raw_amount * 0.001425 * 0.6
    if fee < 20 and raw_amount > 0:
        fee = 20
    if is_buy:
        return raw_amount + fee
    return raw_amount - fee - (raw_amount * 0.003)


def _next_kd_cross(df: pd.DataFrame, period: int = 9):
    """逆推明日 KD 交叉目標價與提示文案（舊腳本 calculate_next_kd_cross_price）。"""
    latest_k = float(df["k"].iloc[-1])
    latest_d = float(df["d"].iloc[-1])
    latest_close = float(df["close"].iloc[-1])

    h_n = float(df["high"].iloc[-(period - 1):].max())
    l_n = float(df["low"].iloc[-(period - 1):].min())
    diff_n = h_n - l_n

    rsv_golden_target = 3 * latest_d - 2 * latest_k
    price_golden = (rsv_golden_target * diff_n / 100) + l_n
    pct_golden = ((price_golden - latest_close) / latest_close) * 100

    if rsv_golden_target > 100:
        desc_golden = (f"明日大漲至 {price_golden:.2f} 元 ({pct_golden:+.2f}%) "
                       f"以上方能轉為黃金交叉。")
    elif rsv_golden_target < 0:
        price_golden_safe = max(0.1, price_golden)
        desc_golden = (f"目前超賣，明日收盤高於 {price_golden_safe:.2f} "
                       f"元方能轉為黃金交叉。")
    else:
        desc_golden = f"明日收盤需高於 {price_golden:.2f} 元方能轉為黃金交叉。"

    if price_golden <= 0:
        desc_dead = "明日只要收盤高於 0 元，即可維持多頭波段不變。"
    else:
        desc_dead = (f"明日若跌破 {price_golden:.2f} 元 ({pct_golden:+.2f}%) "
                     f"則將轉為死亡交叉。")

    if latest_k >= latest_d:
        description = f"【目前多頭維持中】 出場提示：{desc_dead} | 進場提示：{desc_golden}"
    else:
        description = f"【目前空頭維持中】 進場提示：{desc_golden} | 出場提示：{desc_dead}"

    return price_golden, rsv_golden_target, description


def _weekly_boxes(df: pd.DataFrame) -> pd.DataFrame:
    """以週收盤建箱體，回傳 index=週五的 DataFrame（Box_High/Box_Low）。"""
    df_weekly = (df["close"].resample("W-FRI").last().dropna()
                 .to_frame(name="weekly_close"))
    box_high = pd.Series(index=df_weekly.index, dtype=float)
    box_low = pd.Series(index=df_weekly.index, dtype=float)
    init_weeks = min(3, len(df_weekly))
    current_high = float(df_weekly["weekly_close"].iloc[0:init_weeks].max())
    current_low = float(df_weekly["weekly_close"].iloc[0:init_weeks].min())

    for i in range(len(df_weekly)):
        w_close = float(df_weekly["weekly_close"].iloc[i])
        if i < init_weeks:
            box_high.iloc[i] = current_high
            box_low.iloc[i] = current_low
            continue
        prev_high = box_high.iloc[i - 1]
        prev_low = box_low.iloc[i - 1]
        if w_close > prev_high:
            current_high = w_close
            current_low = prev_high
        elif w_close < prev_low:
            current_high = prev_high
            current_low = w_close
        else:
            current_high = prev_high
            current_low = prev_low
        box_high.iloc[i] = current_high
        box_low.iloc[i] = current_low

    df_weekly["Box_High"] = box_high
    df_weekly["Box_Low"] = box_low
    return df_weekly


def run_backtest(df_prices: pd.DataFrame, start_date: str, cfg: dict) -> BacktestResult:
    """對單檔股票跑回測。

    df_prices: DatetimeIndex 的日K（需含 start_date 前約一年的暖身資料）。
    start_date: 回測起算日（=舊腳本的「買入日期」，實際為開始觀察日）。
    cfg: core.config 參數 dict。
    """
    period = int(cfg["kd_period"])
    stop_profit_pct = float(cfg["stop_profit_pct"])
    fixed_loss_pct = float(cfg["fixed_loss_pct"])
    add_position_size = float(cfg["add_position_size"])
    initial_size = float(cfg["initial_size"])
    entry_price = 0.0  # 自動化模式一律從空手開始（舊腳本固定參數）

    df = df_prices.copy().sort_index()
    df = calc_kd(df, period=period)

    # 週箱對齊到日線
    df_weekly = _weekly_boxes(df)
    last_high = float(df_weekly["Box_High"].iloc[-1])
    last_low = float(df_weekly["Box_Low"].iloc[-1])
    df["前箱高"] = 0.0
    df["前箱低"] = 0.0
    for date_idx in df.index:
        past = df_weekly[df_weekly.index <= date_idx]
        if not past.empty:
            df.loc[date_idx, "前箱高"] = float(past["Box_High"].iloc[-1])
            df.loc[date_idx, "前箱低"] = float(past["Box_Low"].iloc[-1])
        else:
            df.loc[date_idx, "前箱高"] = last_high
            df.loc[date_idx, "前箱低"] = last_low

    _, _, tomorrow_desc = _next_kd_cross(df, period=period)

    df_filtered = df[df.index >= pd.to_datetime(start_date)].copy().sort_index()

    # 週線低點與前一週低點
    df_filtered["year_week"] = df_filtered.index.to_period("W")
    weekly_low = df_filtered.groupby("year_week")["low"].min().rename("weekly_low")
    prev_weekly_low = weekly_low.shift(1).rename("prev_weekly_low")
    df_filtered = df_filtered.join(weekly_low, on="year_week")
    df_filtered = df_filtered.join(prev_weekly_low, on="year_week")
    df_filtered["prev_weekly_low"] = df_filtered["prev_weekly_low"].fillna(0.0)

    v_shares, v_cost, v_highest = [], [], []
    v_stop_profit, v_stop_loss = [], []
    v_status, v_reason = [], []
    v_entry_target, v_exit_target = [], []
    v_profit_amt, v_profit_pct = [], []

    is_holding = False
    total_invested_cash = 0.0
    highest_close_since_entry = 0.0
    historical_closed_profit = 0.0

    for i in range(len(df_filtered)):
        current_close = df_filtered["close"].iloc[i]
        current_k = df_filtered["k"].iloc[i]
        current_d = df_filtered["d"].iloc[i]
        current_box_high = df_filtered["前箱高"].iloc[i]
        current_box_low = df_filtered["前箱低"].iloc[i]
        current_weekly_low = df_filtered["weekly_low"].iloc[i]
        prev_weekly_low_val = df_filtered["prev_weekly_low"].iloc[i]
        is_weekly_low_higher = current_weekly_low > prev_weekly_low_val

        current_date = df_filtered.index[i]
        df_idx = df.index.get_loc(current_date)

        # 逆推明日 KD 金叉目標價（供進場目標欄位）
        if df_idx >= (period - 1):
            h_n = float(df["high"].iloc[df_idx - (period - 2): df_idx + 1].max())
            l_n = float(df["low"].iloc[df_idx - (period - 2): df_idx + 1].min())
            diff_n = h_n - l_n
            rsv_golden_target = 3 * current_d - 2 * current_k
            kd_cross_entry_target = (rsv_golden_target * diff_n / 100) + l_n
            if rsv_golden_target < 0:
                kd_cross_entry_target = max(0.1, kd_cross_entry_target)
        else:
            kd_cross_entry_target = current_close

        day_shares = 0.0
        day_cost = 0.0
        day_stop_profit = 0.0
        day_stop_loss = 0.0
        day_status = "空手觀望"
        day_reason = "等待策略觸發訊號"
        day_entry_target = 0.0
        day_exit_target = 0.0
        day_profit_amt = 0.0
        day_profit_pct = 0.0

        if i == 0:
            # 自動化模式 entry_price=0 → 從空手開始
            if entry_price > 0 and initial_size > 0:
                initial_total_cost = calculate_tw_cost(entry_price, initial_size, True)
                total_invested_cash = initial_total_cost
                day_cost = initial_total_cost / (initial_size * 1000)
                highest_close_since_entry = max(entry_price, current_close)
                day_shares = initial_size
                day_stop_profit = highest_close_since_entry * (1 - stop_profit_pct / 100)
                day_stop_loss = entry_price * (1 - fixed_loss_pct / 100)
                day_status = "持股續抱"
                day_reason = "承接既有輸入之初始部位"
                day_entry_target = entry_price
                day_exit_target = max(day_stop_profit, day_stop_loss)
                net_revenue = calculate_tw_cost(current_close, initial_size, False)
                day_profit_amt = net_revenue - total_invested_cash
                day_profit_pct = (day_profit_amt / total_invested_cash) * 100
                is_holding = True
            else:
                highest_close_since_entry = 0.0
                total_invested_cash = 0.0
                is_holding = False

        elif not is_holding:
            kd_is_positive = current_k > current_d
            is_above_weekly = current_close > current_box_high
            prev_cost = v_cost[-1] if v_cost else 0.0
            prev_stop_profit = v_stop_profit[-1] if v_stop_profit else 0.0
            prev_stop_loss = v_stop_loss[-1] if v_stop_loss else 0.0

            if kd_is_positive and is_above_weekly and is_weekly_low_higher:
                is_holding = True
                reentry_cash = calculate_tw_cost(current_close, initial_size, True)
                total_invested_cash = reentry_cash
                day_cost = reentry_cash / (initial_size * 1000)
                highest_close_since_entry = current_close
                day_stop_profit = highest_close_since_entry * (1 - stop_profit_pct / 100)
                day_stop_loss = current_close * (1 - fixed_loss_pct / 100)
                day_shares = initial_size
                day_status = "重返進場"
                day_reason = "收盤突破正宗箱頂、KD多頭且週線底點抬高"
                day_entry_target = current_close
                day_exit_target = max(day_stop_profit, day_stop_loss)
                net_revenue = calculate_tw_cost(current_close, initial_size, False)
                day_profit_amt = historical_closed_profit + (net_revenue - total_invested_cash)
                day_profit_pct = (day_profit_amt / total_invested_cash) * 100
            else:
                day_shares = 0.0
                day_cost = prev_cost
                day_stop_profit = prev_stop_profit
                day_stop_loss = prev_stop_loss
                day_status = "空手觀望"
                day_exit_target = 0.0
                if not kd_is_positive:
                    day_reason = "無明確進場訊號（KD死叉/未黃金交叉）"
                    day_entry_target = kd_cross_entry_target
                elif is_above_weekly and not is_weekly_low_higher:
                    day_reason = (f"KD雖突破箱頂且KD多頭，但當週最低點"
                                  f"({current_weekly_low:.2f})未抬高而放棄")
                    day_entry_target = max(current_close, current_box_high)
                else:
                    day_reason = "股價未突破正宗大箱頂，保持觀望"
                    day_entry_target = max(current_close, current_box_high)
                day_profit_amt = historical_closed_profit
                day_profit_pct = v_profit_pct[-1] if v_profit_pct else 0.0

        else:
            prev_shares = v_shares[-1]
            prev_cost = v_cost[-1]
            prev_stop_loss = v_stop_loss[-1]
            prev_stop_profit = v_stop_profit[-1]
            prev_k = df_filtered["k"].iloc[i - 1]
            prev_d = df_filtered["d"].iloc[i - 1]

            highest_close_since_entry = max(highest_close_since_entry, current_close)
            current_stop_profit_price = highest_close_since_entry * (1 - stop_profit_pct / 100)

            is_fixed_loss_broken = current_close < prev_stop_loss
            is_box_broken = current_close < current_box_low
            is_box_high_retested_5pct = current_close < current_box_high * 0.95
            is_stop_profit_broken = current_close < prev_stop_profit

            reason_str = ""
            if is_fixed_loss_broken:
                reason_str = (f"出場:盤後破固定停損價({current_close:.2f})，"
                              f"破({prev_stop_loss:.2f})")
            elif is_box_broken:
                reason_str = (f"出場:盤後破正宗大箱底({current_close:.2f})，"
                              f"破({current_box_low:.2f})")
            elif is_box_high_retested_5pct:
                reason_str = (f"出場:盤後跌破箱頂下緣5%緩衝價({current_close:.2f})，"
                              f"破({current_box_high * 0.95:.2f})")
            elif is_stop_profit_broken:
                reason_str = (f"出場:盤後跌破移動停利線({current_close:.2f})，"
                              f"破({prev_stop_profit:.2f})")

            if reason_str != "":
                is_holding = False
                net_revenue = calculate_tw_cost(current_close, prev_shares, False)
                current_wave_profit = net_revenue - total_invested_cash
                historical_closed_profit += current_wave_profit

                day_shares = 0.0
                day_cost = prev_cost
                day_stop_profit = current_stop_profit_price
                day_stop_loss = prev_stop_loss
                day_status = "出場"
                day_reason = reason_str
                day_entry_target = kd_cross_entry_target
                day_exit_target = current_close
                day_profit_amt = historical_closed_profit
                day_profit_pct = ((historical_closed_profit / total_invested_cash) * 100
                                  if total_invested_cash > 0 else 0.0)
            else:
                kd_golden_cross = (prev_k <= prev_d) and (current_k > current_d)
                is_earning = current_close > prev_cost
                is_kd_dead_cross = current_k < current_d

                if (kd_golden_cross and is_earning and is_weekly_low_higher
                        and add_position_size > 0):
                    add_cash = calculate_tw_cost(current_close, add_position_size, True)
                    total_invested_cash += add_cash
                    day_shares = prev_shares + add_position_size
                    day_cost = total_invested_cash / (day_shares * 1000)
                    day_stop_loss = day_cost * (1 - fixed_loss_pct / 100)
                    day_status = "加碼"
                    day_reason = "持股賺錢、且KD金叉貼近週線底點抬高"
                    day_stop_profit = current_stop_profit_price
                    day_entry_target = current_close
                    day_exit_target = max(day_stop_loss, current_stop_profit_price,
                                          current_box_low, current_box_high * 0.95)
                elif is_kd_dead_cross:
                    day_shares = prev_shares
                    day_cost = prev_cost
                    day_status = "續抱(轉弱)"
                    day_stop_profit = current_stop_profit_price
                    day_stop_loss = prev_stop_loss
                    day_entry_target = kd_cross_entry_target
                    day_exit_target = max(prev_stop_loss, current_stop_profit_price,
                                          current_box_low, current_box_high * 0.95)
                    if kd_golden_cross and is_earning and not is_weekly_low_higher:
                        day_reason = "KD金叉轉弱！且週線低點未抬高放棄加碼"
                    else:
                        day_reason = (f"警示:KD死叉轉弱(K: {current_k:.1f} < "
                                      f"D: {current_d:.1f})，注意防禦價")
                else:
                    day_shares = prev_shares
                    day_cost = prev_cost
                    day_status = "續抱"
                    day_stop_profit = current_stop_profit_price
                    day_stop_loss = prev_stop_loss
                    day_entry_target = kd_cross_entry_target
                    day_exit_target = max(prev_stop_loss, current_stop_profit_price,
                                          current_box_low, current_box_high * 0.95)
                    day_reason = "股價運行於安全區間內"

                net_revenue = calculate_tw_cost(current_close, day_shares, False)
                day_profit_amt = historical_closed_profit + (net_revenue - total_invested_cash)
                day_profit_pct = ((day_profit_amt / total_invested_cash) * 100
                                  if total_invested_cash > 0 else 0.0)

        # 每日唯一出口：所有分支都在這裡剛好 append 一次
        v_shares.append(day_shares)
        v_cost.append(day_cost)
        v_highest.append(highest_close_since_entry)
        v_stop_profit.append(day_stop_profit)
        v_stop_loss.append(day_stop_loss)
        v_status.append(day_status)
        v_reason.append(day_reason)
        v_entry_target.append(day_entry_target)
        v_exit_target.append(day_exit_target)
        v_profit_amt.append(day_profit_amt)
        v_profit_pct.append(day_profit_pct)

    df_filtered["進場目標價"] = v_entry_target
    df_filtered["出場目標價"] = v_exit_target
    df_filtered["持股張數"] = v_shares
    df_filtered["平均成本"] = v_cost
    df_filtered["移動停利線"] = v_stop_profit
    df_filtered["固定停損線"] = v_stop_loss
    df_filtered["訊號狀態"] = v_status
    df_filtered["進出場原因說明"] = v_reason
    df_filtered["損益金額"] = v_profit_amt
    df_filtered["損益獲利率%"] = v_profit_pct

    daily = df_filtered.drop(columns=["year_week"])
    return BacktestResult(daily=daily, tomorrow_desc=tomorrow_desc)

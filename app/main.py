# -*- coding: utf-8 -*-
"""箱型選股回測系統 — Streamlit 網頁。

本機測試：
    streamlit run app/main.py -- --local-db "C:\\path\\to\\tw_stock_v2.db"
雲端部署：
    st.secrets["REPO"] 指向 GitHub repo，DB 自 Release 下載。
"""
import datetime
import json
import os
import sqlite3
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dateutil.relativedelta import relativedelta
from plotly.subplots import make_subplots

# 讓 core 模組可被匯入（app/ 在子資料夾）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.backtest import run_backtest  # noqa: E402
from core.config import DEFAULTS, load_config  # noqa: E402
from core.data import get_companies, get_stock_name, load_prices  # noqa: E402
from core.indicators import calc_kd  # noqa: E402
from core.report import build_excel  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS_DIR = os.path.join(ROOT, "outputs")
CONFIG_PATH = os.path.join(ROOT, "config.json")

st.set_page_config(page_title="箱型選股回測系統", page_icon="📦", layout="wide")


# ---------- 資料來源 ----------
def _local_db_arg() -> str | None:
    argv = sys.argv
    if "--local-db" in argv:
        i = argv.index("--local-db")
        if i + 1 < len(argv):
            return argv[i + 1]
    return os.environ.get("LOCAL_DB") or None


@st.cache_resource(show_spinner="正在準備資料庫…")
def get_db_path() -> str:
    local = _local_db_arg()
    if local and os.path.exists(local):
        return local
    repo = st.secrets.get("REPO", os.environ.get("STOCK_REPO", ""))
    if not repo:
        st.error("找不到資料庫：請設定 secrets 的 REPO 或用 --local-db 指定路徑。")
        st.stop()
    from app.db_fetch import ensure_db
    return ensure_db(repo)


def connect():
    return sqlite3.connect(get_db_path())


@st.cache_data(ttl=3600)
def cached_companies() -> pd.DataFrame:
    with connect() as conn:
        return get_companies(conn)


@st.cache_data(ttl=3600)
def cached_prices(sid: str, start: str, end: str) -> pd.DataFrame:
    with connect() as conn:
        return load_prices(conn, sid, start=start, end=end)


def db_latest_date() -> str:
    with connect() as conn:
        row = conn.execute("SELECT MAX(date) FROM stock_price_daily").fetchone()
    return row[0] or "無資料"


def list_output_dates() -> list[str]:
    if not os.path.isdir(OUTPUTS_DIR):
        return []
    return sorted([d for d in os.listdir(OUTPUTS_DIR)
                   if os.path.isdir(os.path.join(OUTPUTS_DIR, d))], reverse=True)


# ---------- 側欄：日期與參數 ----------
cfg_saved = load_config(CONFIG_PATH)
today = datetime.date.today()

with st.sidebar:
    st.header("⚙️ 回測設定")
    buy_date = st.date_input(
        "買入日期（回測起算日）",
        value=today - relativedelta(months=int(cfg_saved["default_lookback_months"])),
        max_value=today)
    end_date = st.date_input("截止日期", value=today, max_value=today)

    st.subheader("策略參數")
    stop_profit = st.slider("移動停利 %", 3.0, 30.0,
                            float(cfg_saved["stop_profit_pct"]), 0.5)
    fixed_loss = st.slider("固定停損 %", 1.0, 15.0,
                           float(cfg_saved["fixed_loss_pct"]), 0.5)
    high_threshold = st.slider("距3年高點門檻 %", 80.0, 100.0,
                               float(cfg_saved["high_threshold_pct"]), 1.0)
    add_size = st.number_input("每次加碼張數", 0.0, 10.0,
                               float(cfg_saved["add_position_size"]), 1.0)
    lookback_m = st.number_input("預設回推月數（每日自動回測用）", 1, 36,
                                 int(cfg_saved["default_lookback_months"]), 1)

    cfg_now = dict(cfg_saved)
    cfg_now.update({
        "stop_profit_pct": stop_profit,
        "fixed_loss_pct": fixed_loss,
        "high_threshold_pct": high_threshold,
        "add_position_size": add_size,
        "default_lookback_months": int(lookback_m),
    })

    st.caption("改完參數後，切到「個股分析」按【重新回測】即生效。")

    if st.button("💾 存為預設", help="寫回 config.json，之後每日自動排程改用這組參數"):
        token = st.secrets.get("GITHUB_TOKEN", "")
        repo = st.secrets.get("REPO", "")
        if token and repo:
            import base64
            import requests
            api = f"https://api.github.com/repos/{repo}/contents/config.json"
            headers = {"Authorization": f"Bearer {token}"}
            cur = requests.get(api, headers=headers, timeout=30).json()
            body = {
                "message": "chore: 網頁更新預設參數",
                "content": base64.b64encode(
                    json.dumps(cfg_now, ensure_ascii=False, indent=2)
                    .encode("utf-8")).decode(),
                "sha": cur.get("sha"),
            }
            r = requests.put(api, headers=headers, json=body, timeout=30)
            if r.ok:
                st.success("已存回 GitHub，之後每日排程使用新參數。")
            else:
                st.error(f"存檔失敗：{r.status_code} {r.text[:200]}")
        else:
            from core.config import save_config
            save_config(cfg_now, CONFIG_PATH)
            st.success("已存到本機 config.json。")

st.title("📦 箱型選股回測系統")
st.caption(f"資料庫最新日期：**{db_latest_date()}**（每個交易日 15:30 後自動更新）")

tab_scan, tab_stock = st.tabs(["📋 每日選股", "📈 個股分析"])

# ---------- Tab 1：每日選股 ----------
with tab_scan:
    dates = list_output_dates()
    if not dates:
        st.info("尚無每日掃描結果。等雲端排程首跑完成，或先到「個股分析」直接輸入代號分析。")
    else:
        pick_date = st.selectbox("選擇日期", dates, index=0)
        scan_path = os.path.join(OUTPUTS_DIR, pick_date, "scan.parquet")
        if os.path.exists(scan_path):
            scan_df = pd.read_parquet(scan_path)
            if scan_df.empty:
                st.warning(f"{pick_date} 沒有符合條件的股票。")
            else:
                st.subheader(f"{pick_date} 入選 {len(scan_df)} 檔")
                st.dataframe(scan_df, use_container_width=True, hide_index=True)
                st.caption("到「個股分析」分頁可看每一檔的走勢圖與回測明細。")
        else:
            st.warning("該日期缺少掃描檔。")

# ---------- Tab 2：個股分析 ----------
with tab_stock:
    companies = cached_companies()
    id2name = dict(zip(companies["stock_id"], companies["stock_name"]))

    # 預設帶入最新名單
    latest_dates = list_output_dates()
    scan_ids: list[str] = []
    if latest_dates:
        p = os.path.join(OUTPUTS_DIR, latest_dates[0], "scan.parquet")
        if os.path.exists(p):
            scan_ids = list(pd.read_parquet(p)["代號"])

    col1, col2 = st.columns([2, 1])
    with col1:
        options = scan_ids + [s for s in id2name if s not in scan_ids]
        sid = st.selectbox(
            "選擇股票（前面是今日入選名單）", options,
            format_func=lambda s: f"{s} {id2name.get(s, '')}")
    with col2:
        view_range = st.radio(
            "看圖範圍", ["1個月", "3個月", "6個月", "1年", "3年", "自訂"],
            index=2, horizontal=True)

    if view_range == "自訂":
        c1, c2 = st.columns(2)
        view_start = c1.date_input("圖表起日", value=today - relativedelta(years=1))
        view_end = c2.date_input("圖表迄日", value=today)
    else:
        months = {"1個月": 1, "3個月": 3, "6個月": 6, "1年": 12, "3年": 36}[view_range]
        view_start = today - relativedelta(months=months)
        view_end = today

    run_bt = st.button("🔄 重新回測", type="primary")

    if sid:
        buy_str = buy_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        cache_key = (sid, buy_str, end_str,
                     json.dumps(cfg_now, sort_keys=True))

        if run_bt or st.session_state.get("bt_key") != cache_key:
            extended = (buy_date - relativedelta(years=1)).strftime("%Y-%m-%d")
            prices = cached_prices(sid, extended, end_str)
            if prices.empty:
                st.error(f"資料庫沒有 {sid} 的股價資料。")
                st.stop()
            with st.spinner("回測計算中…"):
                bt = run_backtest(prices, buy_str, cfg_now)
            st.session_state["bt_key"] = cache_key
            st.session_state["bt_result"] = bt

        bt = st.session_state["bt_result"]

        # ---- 雙圖：股價(上) + KD(下)，時間軸連動 ----
        chart_start = (pd.to_datetime(view_start) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
        chart_prices = cached_prices(sid, chart_start, view_end.strftime("%Y-%m-%d"))
        if chart_prices.empty:
            st.warning("此範圍內無股價資料。")
        else:
            cdf = calc_kd(chart_prices.copy(), period=int(cfg_now["kd_period"]))
            cdf = cdf[cdf.index >= pd.to_datetime(view_start)]

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                row_heights=[0.7, 0.3], vertical_spacing=0.05)
            fig.add_trace(go.Scatter(x=cdf.index, y=cdf["close"], name="收盤價",
                                     line=dict(color="#1f2937", width=2)), 1, 1)

            overlay = bt.daily[(bt.daily.index >= cdf.index.min())
                               & (bt.daily.index <= cdf.index.max())]
            if not overlay.empty:
                fig.add_trace(go.Scatter(x=overlay.index, y=overlay["前箱高"],
                                         name="箱頂", line=dict(color="#dc2626", width=1)), 1, 1)
                fig.add_trace(go.Scatter(x=overlay.index, y=overlay["前箱低"],
                                         name="箱底", line=dict(color="#dc2626", width=1),
                                         fill="tonexty", fillcolor="rgba(220,38,38,0.05)"), 1, 1)
                hold = overlay[overlay["持股張數"] > 0]
                if not hold.empty:
                    fig.add_trace(go.Scatter(x=hold.index, y=hold["移動停利線"],
                                             name="移動停利", mode="lines",
                                             line=dict(color="#16a34a", dash="dash")), 1, 1)
                    fig.add_trace(go.Scatter(x=hold.index, y=hold["固定停損線"],
                                             name="固定停損", mode="lines",
                                             line=dict(color="#2563eb", dash="dash")), 1, 1)
                entries = overlay[overlay["訊號狀態"].isin(["重返進場", "加碼"])]
                exits = overlay[overlay["訊號狀態"] == "出場"]
                if not entries.empty:
                    fig.add_trace(go.Scatter(
                        x=entries.index, y=entries["close"], name="進場/加碼",
                        mode="markers",
                        marker=dict(symbol="triangle-up", size=12, color="#dc2626")), 1, 1)
                if not exits.empty:
                    fig.add_trace(go.Scatter(
                        x=exits.index, y=exits["close"], name="出場",
                        mode="markers",
                        marker=dict(symbol="triangle-down", size=12, color="#16a34a")), 1, 1)

            fig.add_trace(go.Scatter(x=cdf.index, y=cdf["k"], name="K值",
                                     line=dict(color="#2563eb", width=1.5)), 2, 1)
            fig.add_trace(go.Scatter(x=cdf.index, y=cdf["d"], name="D值",
                                     line=dict(color="#f59e0b", width=1.5)), 2, 1)
            fig.add_hline(y=80, line=dict(color="#9ca3af", dash="dot"), row=2, col=1)
            fig.add_hline(y=20, line=dict(color="#9ca3af", dash="dot"), row=2, col=1)

            fig.update_layout(
                title=f"{sid} {id2name.get(sid, get_stock_name(connect(), sid))}",
                height=620, hovermode="x unified", dragmode="pan",
                legend=dict(orientation="h", y=1.08),
                margin=dict(l=10, r=10, t=80, b=10))
            fig.update_yaxes(title_text="股價", row=1, col=1)
            fig.update_yaxes(title_text="KD", range=[0, 100], row=2, col=1)
            st.plotly_chart(fig, use_container_width=True,
                            config={"scrollZoom": True})

        st.info(f"**明日交易提示**：{bt.tomorrow_desc}")

        latest = bt.daily.iloc[-1]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("最新收盤", f"{latest['close']:.2f}")
        m2.metric("目前狀態", str(latest["訊號狀態"]))
        m3.metric("持股張數", f"{int(latest['持股張數'])}")
        m4.metric("累計損益", f"{latest['損益金額']:,.0f} 元")

        with st.expander("📜 回測每日明細", expanded=False):
            show = bt.daily.copy()
            show.index = show.index.strftime("%Y-%m-%d")
            st.dataframe(
                show[["close", "k", "d", "平均成本", "移動停利線", "固定停損線",
                      "前箱高", "前箱低", "持股張數", "訊號狀態",
                      "進出場原因說明", "損益金額"]].round(2),
                use_container_width=True)

        name = id2name.get(sid, "未知股票")
        st.download_button(
            "⬇️ 下載 Excel 回測報告",
            data=build_excel(bt, sid, name),
            file_name=f"{sid}_{name}_回測報告.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

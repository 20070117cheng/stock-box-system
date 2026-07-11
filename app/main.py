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
from core.scanner import scan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS_DIR = os.path.join(ROOT, "outputs")
CONFIG_PATH = os.path.join(ROOT, "config.json")

st.set_page_config(page_title="箱型選股回測系統", layout="wide")

# 介面風格對齊 stock-breakout-signals 的儀表板（深藍頁首＋膠囊分頁＋白卡片）
st.markdown("""
<style>
.stApp { background: #f1f5f9; }
header[data-testid="stHeader"] { background: rgba(241,245,249,.8); }
h1, h2, h3, h4, p, li, label { font-family: "Microsoft JhengHei", "PingFang TC",
  system-ui, sans-serif; }
.stTabs [role="tablist"] { background: #0f172a; padding: 8px 12px;
  border-radius: 12px; gap: 4px; border-bottom: 0; }
.stTabs [data-testid="stTab"] { background: #1e293b; color: #cbd5e1;
  border-radius: 999px; padding: 4px 16px; border: 0; }
.stTabs [data-testid="stTab"] p { color: inherit; }
.stTabs [data-testid="stTab"]:hover { color: #fff; }
.stTabs [aria-selected="true"] { background: #2563eb !important;
  color: #fff !important; font-weight: 700; }
[data-testid="stMetric"] { background: #fff; border-radius: 12px;
  padding: 12px 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
[data-testid="stExpander"] { background: #fff; border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.stTabs h3 { font-size: 18px; border-left: 4px solid #2563eb;
  padding-left: 10px; }
[data-testid="stSidebar"] { background: #fff; }
</style>
""", unsafe_allow_html=True)


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


@st.cache_data(ttl=86400, show_spinner=False)
def cached_scan_as_of(as_of: str, threshold: float, kd_period: int,
                      near_gap: float, _progress=None) -> pd.DataFrame:
    """時光機掃描：用 as_of 當天（含）之前的資料全市場選股。"""
    cfg = dict(DEFAULTS)
    cfg.update({"high_threshold_pct": threshold, "kd_period": kd_period,
                "near_cross_gap": near_gap})
    with connect() as conn:
        return scan(conn, cfg, as_of=as_of, progress=_progress)


def db_latest_date() -> str:
    with connect() as conn:
        row = conn.execute("SELECT MAX(date) FROM stock_price_daily").fetchone()
    return row[0] or "無資料"


def list_output_dates() -> list[str]:
    if not os.path.isdir(OUTPUTS_DIR):
        return []
    import re
    return sorted([d for d in os.listdir(OUTPUTS_DIR)
                   if os.path.isdir(os.path.join(OUTPUTS_DIR, d))
                   and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)], reverse=True)


# ---------- 共用：股價 + KD 雙圖 ----------
def render_stock_chart(sid: str, name: str, bt, view_start, view_end,
                       kd_period: int, mark_date: str | None = None) -> None:
    """畫股價(上)+KD(下)連動圖，疊回測箱體/停損停利/進出場記號。

    mark_date: 選填，畫一條垂直虛線（時光機的選股日）。
    """
    chart_start = (pd.to_datetime(view_start) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    chart_prices = cached_prices(sid, chart_start,
                                 pd.to_datetime(view_end).strftime("%Y-%m-%d"))
    if chart_prices.empty:
        st.warning("此範圍內無股價資料。")
        return
    cdf = calc_kd(chart_prices.copy(), period=kd_period)
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

    if mark_date:
        fig.add_vline(x=pd.to_datetime(mark_date), line=dict(color="#6b7280", dash="dot"))
        fig.add_annotation(x=pd.to_datetime(mark_date), y=1.02, yref="paper",
                           text="選股日", showarrow=False, font=dict(color="#6b7280"))

    fig.update_layout(
        title=f"{sid} {name}",
        height=620, hovermode="x unified", dragmode="pan",
        legend=dict(orientation="h", y=1.08),
        margin=dict(l=10, r=10, t=80, b=10))
    fig.update_yaxes(title_text="股價", row=1, col=1)
    fig.update_yaxes(title_text="KD", range=[0, 100], row=2, col=1)
    st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})


def show_backtest_detail(bt) -> None:
    """回測每日明細 expander（兩個分頁共用）。"""
    with st.expander("回測每日明細", expanded=False):
        show = bt.daily.copy()
        show.index = show.index.strftime("%Y-%m-%d")
        st.dataframe(
            show[["close", "k", "d", "平均成本", "移動停利線", "固定停損線",
                  "前箱高", "前箱低", "持股張數", "訊號狀態",
                  "進出場原因說明", "損益金額"]].round(2),
            use_container_width=True)


# ---------- 側欄：日期與參數 ----------
cfg_saved = load_config(CONFIG_PATH)
today = datetime.date.today()

with st.sidebar:
    st.header("回測設定")
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

    st.caption("改完參數後，切到「個股分析」按【重新回測】即生效。"
               "時光機分頁的參數獨立，不受側欄影響。")

    if st.button("存為預設", help="寫回 config.json，之後每日自動排程改用這組參數"):
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

st.markdown(f"""
<div style="background:#0f172a;color:#fff;padding:20px 24px;border-radius:12px;
            margin-bottom:12px">
  <h1 style="margin:0 0 4px;font-size:22px;color:#fff">箱型選股回測系統</h1>
  <p style="margin:0;color:#94a3b8;font-size:13px">達瓦斯箱型策略自動掃描台股（上市＋上櫃）
  ｜資料庫最新日期：{db_latest_date()}（每個交易日 15:30 後自動更新）</p>
</div>
""", unsafe_allow_html=True)

# ---------- 大盤燈號橫幅 ----------
_LIGHT = {"green": ("#16a34a", "綠燈"), "yellow": ("#ca8a04", "黃燈"),
          "red": ("#dc2626", "紅燈")}
light_path = os.path.join(OUTPUTS_DIR, "market_light.json")
if os.path.exists(light_path):
    with open(light_path, encoding="utf-8") as f:
        light = json.load(f)
    color, label = _LIGHT.get(light.get("light", "yellow"), _LIGHT["yellow"])
    ratio_txt = (f"創一年新高股比率 {light['ratio']}%"
                 if light.get("ratio") is not None else "")
    st.markdown(f"""
<div style="background:#fff;border-radius:12px;padding:12px 20px;margin-bottom:8px;
            box-shadow:0 1px 3px rgba(0,0,0,.08)">
  <span style="display:inline-block;width:12px;height:12px;border-radius:50%;
               background:{color};margin-right:6px"></span>
  <b style="color:{color}">{label}</b>　{ratio_txt}　—　{light.get('advice', '')}
</div>
""", unsafe_allow_html=True)

tab_scan, tab_stock, tab_time, tab_hold, tab_paper = st.tabs(
    ["每日選股", "個股分析", "時光機", "持股監控", "虛擬操盤"])

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
                from core.position import buy_cost, suggest_shares
                cap = float(cfg_saved.get("total_capital", 50000))
                pct = float(cfg_saved.get("position_pct", 10.0))
                show_df = scan_df.copy()
                show_df["建議股數"] = show_df["當前價"].map(
                    lambda p: suggest_shares(float(p), cap, pct))
                show_df["約需金額"] = show_df.apply(
                    lambda r: round(buy_cost(float(r["當前價"]),
                                             int(r["建議股數"])))
                    if r["建議股數"] > 0 else 0, axis=1)
                st.dataframe(show_df, use_container_width=True,
                             hide_index=True)
                st.caption(f"建議股數＝總資金 {cap:,.0f} 元 × 單檔上限 {pct:.0f}%"
                           "，以零股計（側欄無此設定，改 config.json）。"
                           "到「個股分析」分頁可看走勢圖與回測明細。")
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

    options = scan_ids + [s for s in id2name if s not in scan_ids]
    sid = st.selectbox(
        "選擇股票（前面是今日入選名單）", options,
        format_func=lambda s: f"{s} {id2name.get(s, '')}")
    st.caption("圖表顯示資料庫內全部歷史，可用滾輪縮放、拖曳平移，雙擊還原。")

    run_bt = st.button("重新回測", type="primary")

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

        name = id2name.get(sid, get_stock_name(connect(), sid))
        with connect() as _c:
            first_date = _c.execute(
                "SELECT MIN(date) FROM stock_price_daily WHERE stock_id=?",
                (sid,)).fetchone()[0]
        render_stock_chart(sid, name, bt, first_date or today, today,
                           kd_period=int(cfg_now["kd_period"]))

        st.info(f"**明日交易提示**：{bt.tomorrow_desc}")

        latest = bt.daily.iloc[-1]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("最新收盤", f"{latest['close']:.2f}")
        m2.metric("目前狀態", str(latest["訊號狀態"]))
        m3.metric("持股張數", f"{int(latest['持股張數'])}")
        m4.metric("累計損益", f"{latest['損益金額']:,.0f} 元")

        show_backtest_detail(bt)

        st.download_button(
            "下載 Excel 回測報告",
            data=build_excel(bt, sid, name),
            file_name=f"{sid}_{name}_回測報告.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------- Tab 3：時光機 ----------
with tab_time:
    st.caption("站在過去任一天，用「當時」的資料選股，再看之後照策略操作的結果。"
               "選股當下不知道未來，這裡的績效才能公平檢驗策略。")

    d1, d2 = st.columns(2)
    tm_pick = d1.date_input(
        "選股日期", value=today - relativedelta(months=6),
        max_value=today - datetime.timedelta(days=1), key="tm_pick")
    tm_end = d2.date_input("觀察截止日（預設今天＝放到今天）", value=today,
                           max_value=today, key="tm_end")

    p1, p2, p3, p4 = st.columns(4)
    tm_stop_profit = p1.number_input("移動停利 %", 3.0, 30.0,
                                     float(cfg_saved["stop_profit_pct"]), 0.5,
                                     key="tm_sp")
    tm_fixed_loss = p2.number_input("固定停損 %", 1.0, 15.0,
                                    float(cfg_saved["fixed_loss_pct"]), 0.5,
                                    key="tm_fl")
    tm_threshold = p3.number_input("距3年高點門檻 %", 80.0, 100.0,
                                   float(cfg_saved["high_threshold_pct"]), 1.0,
                                   key="tm_th")
    tm_add = p4.number_input("每次加碼張數", 0.0, 10.0,
                             float(cfg_saved["add_position_size"]), 1.0,
                             key="tm_add")

    run_tm = st.button("執行掃描", type="primary", key="tm_run")

    if run_tm:
        if tm_end <= tm_pick:
            st.error("觀察截止日需晚於選股日期。")
        else:
            pick_str = tm_pick.strftime("%Y-%m-%d")
            end_str = tm_end.strftime("%Y-%m-%d")
            cfg_tm = dict(cfg_saved)
            cfg_tm.update({
                "stop_profit_pct": tm_stop_profit,
                "fixed_loss_pct": tm_fixed_loss,
                "high_threshold_pct": tm_threshold,
                "add_position_size": tm_add,
            })

            bar = st.progress(0.0, text="掃描全市場中（第一次跑要 1～3 分鐘）…")

            def _tm_progress(done: int, total: int) -> None:
                if done % 25 == 0 or done == total:
                    bar.progress(done / total,
                                 text=f"掃描全市場中… {done}/{total}")

            tm_scan_df = cached_scan_as_of(
                pick_str, float(tm_threshold),
                int(cfg_saved["kd_period"]), float(cfg_saved["near_cross_gap"]),
                _progress=_tm_progress)
            bar.empty()

            rows = []
            if not tm_scan_df.empty:
                bt_bar = st.progress(0.0, text="逐檔回測中…")
                extended = (tm_pick - relativedelta(years=1)).strftime("%Y-%m-%d")
                n = len(tm_scan_df)
                for j, (_, r) in enumerate(tm_scan_df.iterrows(), start=1):
                    bt_bar.progress(j / n, text=f"逐檔回測中… {j}/{n}")
                    sid_tm = r["代號"]
                    prices = cached_prices(sid_tm, extended, end_str)
                    if prices.empty:
                        continue
                    bt_tm = run_backtest(prices, pick_str, cfg_tm)
                    daily = bt_tm.daily
                    if daily.empty:
                        continue
                    last = daily.iloc[-1]
                    entered = bool((daily["持股張數"] > 0).any())
                    exits = daily[daily["訊號狀態"] == "出場"]
                    if not entered:
                        status, exit_day = "未進場", "—"
                    elif float(last["持股張數"]) > 0:
                        status, exit_day = "持有中", "—"
                    else:
                        status = "已出場"
                        exit_day = exits.index[-1].strftime("%Y-%m-%d")
                    rows.append({
                        "代號": sid_tm,
                        "股名": r["股名"],
                        "選股日收盤": r["當前價"],
                        "期末狀態": status,
                        "出場日": exit_day,
                        "報酬%": round(float(last["損益獲利率%"]), 2),
                        "損益金額": round(float(last["損益金額"])),
                        "說明": str(last["進出場原因說明"]),
                    })
                bt_bar.empty()

            st.session_state["tm_result"] = {
                "scan": tm_scan_df,
                "table": pd.DataFrame(rows),
                "cfg": cfg_tm,
                "pick": pick_str,
                "end": end_str,
            }

    tm_res = st.session_state.get("tm_result")
    if tm_res:
        pick_str = tm_res["pick"]
        end_str = tm_res["end"]
        cfg_tm = tm_res["cfg"]
        table = tm_res["table"]

        st.subheader(f"{pick_str} 的入選名單，觀察至 {end_str}")
        st.caption(f"參數：移動停利 {cfg_tm['stop_profit_pct']}%、"
                   f"固定停損 {cfg_tm['fixed_loss_pct']}%、"
                   f"門檻 {cfg_tm['high_threshold_pct']}%、"
                   f"每次加碼 {cfg_tm['add_position_size']} 張")

        if tm_res["scan"].empty:
            st.warning("該日期沒有符合條件的股票（或當時資料不足）。")
        elif table.empty:
            st.warning("入選股票在此區間沒有可回測的資料。")
        else:
            entered_df = table[table["期末狀態"] != "未進場"]
            wins = int((entered_df["損益金額"] > 0).sum())
            losses = int((entered_df["損益金額"] < 0).sum())
            n_entered = len(entered_df)

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("入選檔數", f"{len(table)}")
            m2.metric("有進場檔數", f"{n_entered}")
            m3.metric("獲利 / 虧損", f"{wins} / {losses}")
            m4.metric("勝率", f"{wins / n_entered * 100:.0f}%" if n_entered else "—")
            m5.metric("合計損益",
                      f"{entered_df['損益金額'].sum():,.0f} 元" if n_entered else "—")
            if n_entered:
                st.caption(f"有進場股票的平均報酬：{entered_df['報酬%'].mean():.2f}%"
                           "（勝率與損益只統計有進場的股票；"
                           "「未進場」代表觀察期間策略的進場條件沒觸發）")

            st.dataframe(table, use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("單檔詳細")
            tm_sid = st.selectbox(
                "選擇股票", list(table["代號"]),
                format_func=lambda s: f"{s} " + str(
                    table.loc[table["代號"] == s, "股名"].iloc[0]),
                key="tm_sid")
            if tm_sid:
                extended = (pd.to_datetime(pick_str)
                            - relativedelta(years=1)).strftime("%Y-%m-%d")
                prices = cached_prices(tm_sid, extended, end_str)
                bt_tm = run_backtest(prices, pick_str, cfg_tm)
                tm_name = str(table.loc[table["代號"] == tm_sid, "股名"].iloc[0])
                view_start_tm = pd.to_datetime(pick_str) - relativedelta(months=6)
                render_stock_chart(tm_sid, tm_name, bt_tm,
                                   view_start_tm, pd.to_datetime(end_str),
                                   kd_period=int(cfg_saved["kd_period"]),
                                   mark_date=pick_str)
                st.caption("垂直虛線＝選股日。虛線左邊是入選前的走勢，右邊是入選後"
                           "照策略操作的結果。")
                show_backtest_detail(bt_tm)

# ---------- Tab 4：持股監控 ----------
with tab_hold:
    try:
        repo_name = st.secrets.get("REPO", "20070117cheng/stock-box-system")
    except Exception:
        repo_name = "20070117cheng/stock-box-system"
    st.caption("記錄你實際持有的股票，每日收盤後自動用箱型規則檢查該賣、該抱還是該加碼。")
    st.markdown(
        f"編輯持股：到 [GitHub 上的 holdings.csv]"
        f"(https://github.com/{repo_name}/edit/main/holdings.csv) 直接改，"
        "欄位＝代號,買進日,每股成本,股數（例：2330,2026-07-01,1080,4），"
        "隔次排程生效。")
    rep_path = os.path.join(OUTPUTS_DIR, "holdings_report.parquet")
    if not os.path.exists(rep_path):
        st.info("尚無持股報告。在 holdings.csv 填入持股後，等每日排程跑完就會出現。")
    else:
        rep = pd.read_parquet(rep_path)
        if rep.empty:
            st.info("holdings.csv 目前是空的。")
        else:
            n_sell = int((rep["警示"] == "賣出").sum())
            n_watch = int((rep["警示"] == "注意").sum())
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("持股檔數", f"{len(rep)}")
            c2.metric("賣出警示", f"{n_sell}", delta=None)
            c3.metric("注意（轉弱）", f"{n_watch}")
            c4.metric("未實現損益合計", f"{rep['未實現損益'].sum():,.0f} 元")
            if n_sell:
                st.error("有 " + str(n_sell) + " 檔觸發賣出警示，明細見下表「警示」欄。")
            st.dataframe(rep, use_container_width=True, hide_index=True)

# ---------- Tab 5：虛擬操盤 ----------
with tab_paper:
    paper_dir = os.path.join(OUTPUTS_DIR, "paper")
    eq_path = os.path.join(paper_dir, "equity.csv")
    st.caption("系統用虛擬 5 萬元照訊號自動操作零股（單檔上限 10%、每日最多新買 2 檔、"
               "收盤價成交無滑價）——不花錢看系統實際跑起來的樣子。")
    if not os.path.exists(eq_path):
        st.info("虛擬操盤尚未開始，等每日排程首跑完成。")
    else:
        eq = pd.read_csv(eq_path, encoding="utf-8-sig")
        state_path = os.path.join(paper_dir, "state.json")
        state = json.load(open(state_path, encoding="utf-8")) \
            if os.path.exists(state_path) else {"cash": 0, "holdings": {}}
        last = eq.iloc[-1]
        start_cap = float(cfg_saved.get("total_capital", 50000))
        ret_pct = (float(last["總值"]) / start_cap - 1) * 100
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("目前總值", f"{last['總值']:,.0f} 元",
                  f"{ret_pct:+.2f}%")
        c2.metric("現金", f"{last['現金']:,.0f} 元")
        c3.metric("持股檔數", f"{int(last['持股檔數'])}")
        c4.metric("模擬起始資金", f"{start_cap:,.0f} 元")

        fig_eq = go.Figure(go.Scatter(x=pd.to_datetime(eq["日期"]),
                                      y=eq["總值"], mode="lines",
                                      line=dict(color="#2563eb", width=2)))
        fig_eq.add_hline(y=start_cap, line=dict(color="#9ca3af", dash="dot"))
        fig_eq.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10),
                             yaxis_title="總值（元）")
        st.plotly_chart(fig_eq, use_container_width=True)

        if state["holdings"]:
            st.subheader("目前虛擬持股")
            hold_rows = [{"代號": sid, "股名": h.get("name", ""),
                          "股數": h["shares"], "成本": h["cost"],
                          "進場日": h["entry_date"]}
                         for sid, h in state["holdings"].items()]
            st.dataframe(pd.DataFrame(hold_rows),
                         use_container_width=True, hide_index=True)

        tr_path = os.path.join(paper_dir, "trades.csv")
        if os.path.exists(tr_path):
            st.subheader("交易紀錄")
            tr = pd.read_csv(tr_path, encoding="utf-8-sig",
                             dtype={"代號": str})
            st.dataframe(tr.iloc[::-1], use_container_width=True,
                         hide_index=True)

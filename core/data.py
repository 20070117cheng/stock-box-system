# -*- coding: utf-8 -*-
"""資料庫存取層：公司清單、日K讀取、股價增量更新。"""
import datetime
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50          # 每批下載檔數，避免被 Yahoo 鎖 IP
NEW_STOCK_YEARS = 3      # 全新股票回補年數


def get_companies(conn) -> pd.DataFrame:
    """上市/上櫃、4 碼、仍掛牌的公司清單。"""
    return pd.read_sql_query(
        """
        SELECT stock_id, stock_name, industry, market
        FROM company_master
        WHERE (market = '上市' OR market = '上櫃')
          AND LENGTH(stock_id) = 4
          AND is_active = 1
        """,
        conn,
    )


def load_prices(conn, stock_id: str, start: str | None = None,
                end: str | None = None) -> pd.DataFrame:
    """單檔日K，DatetimeIndex 升冪，欄位 open high low close volume。"""
    query = (
        "SELECT date, open, high, low, close, volume FROM stock_price_daily "
        "WHERE stock_id = ?"
    )
    params: list = [stock_id]
    if start:
        query += " AND date >= ?"
        params.append(start)
    if end:
        query += " AND date <= ?"
        params.append(end)
    query += " ORDER BY date ASC"

    df = pd.read_sql_query(query, conn, params=params)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype("int64")
    return df


def get_stock_name(conn, stock_id: str) -> str:
    row = conn.execute(
        "SELECT stock_name FROM company_master WHERE stock_id = ?", (stock_id,)
    ).fetchone()
    return row[0] if row else "未知股票"


def yf_ticker(stock_id: str, market: str) -> str:
    """轉成 Yahoo Finance 代號：上市 .TW、上櫃 .TWO。"""
    return f"{stock_id}{'.TW' if market == '上市' else '.TWO'}"


def _yfinance_downloader(tickers: list[str], start: str) -> pd.DataFrame:
    import yfinance as yf
    return yf.download(tickers=tickers, start=start, group_by="ticker",
                       progress=False, threads=False)


def _has_weekday_between(start: str, end_dt: datetime.datetime) -> bool:
    d = datetime.datetime.strptime(start, "%Y-%m-%d")
    while d <= end_dt:
        if d.weekday() < 5:
            return True
        d += datetime.timedelta(days=1)
    return False


def _extract_rows(df_download, ticker, sid, is_multi) -> list[tuple]:
    """把單一股票的下載結果轉成可寫入的 tuple 列表。

    修復舊腳本縮排 bug：逐列檢查並 append（舊版 append 在迴圈外，
    多日下載只會存到最後一天）。
    """
    if is_multi:
        if ticker not in set(df_download.columns.get_level_values(0)):
            return []
        df_single = df_download[ticker]
    else:
        df_single = df_download
    if "Close" not in df_single.columns:
        return []

    rows = []
    for idx, row in df_single.iterrows():
        try:
            # 停牌日 yfinance 對齊他股時會 ffill 補值，原始 NaN 的列不可寫入
            if pd.isna(row["Close"]) or pd.isna(row["Volume"]):
                continue
            o, h, l, c = (float(row["Open"]), float(row["High"]),
                          float(row["Low"]), float(row["Close"]))
            v = int(row["Volume"])
            if v <= 0 or np.isnan(c):
                continue
            rows.append((sid, idx.strftime("%Y-%m-%d"), o, h, l, c, v))
        except Exception:
            continue
    return rows


_OFFICIAL_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _pf(s) -> float | None:
    """官方 API 數字欄位 → float；'--' 或空值回 None。"""
    s = str(s).replace(",", "").strip()
    if s in ("", "--", "---", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _official_quotes(date: str) -> dict[str, tuple]:
    """抓證交所＋櫃買中心指定日全市場行情 → {代號: (o,h,l,c,v)}。

    yfinance 在 GitHub Actions 的機房 IP 常被 Yahoo 擋（2026-07-10 起
    整批回空），改用官方來源。收盤價為原始市價（非還原權值）。
    """
    import requests

    quotes: dict[str, tuple] = {}

    # 上市（TWSE）
    r = requests.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                     params={"date": date.replace("-", ""),
                             "type": "ALLBUT0999", "response": "json"},
                     headers=_OFFICIAL_HEADERS, timeout=60)
    d = r.json()
    if d.get("stat") == "OK":
        for t in d.get("tables", []):
            f = t.get("fields", [])
            if "證券代號" in f and "收盤價" in f:
                idx = [f.index(k) for k in
                       ("證券代號", "開盤價", "最高價", "最低價", "收盤價", "成交股數")]
                for row in t["data"]:
                    o, h, l, c = (_pf(row[idx[1]]), _pf(row[idx[2]]),
                                  _pf(row[idx[3]]), _pf(row[idx[4]]))
                    v = _pf(row[idx[5]])
                    if c is None or v is None or v <= 0:
                        continue
                    quotes[str(row[idx[0]]).strip()] = (o or c, h or c,
                                                        l or c, c, int(v))
                break

    # 上櫃（TPEx）；其憑證在部分環境驗證失敗，退一步跳過驗證
    url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
    params = {"date": date.replace("-", "/"), "response": "json"}
    try:
        r2 = requests.get(url, params=params, headers=_OFFICIAL_HEADERS,
                          timeout=60)
    except requests.exceptions.SSLError:
        import urllib3
        urllib3.disable_warnings()
        r2 = requests.get(url, params=params, headers=_OFFICIAL_HEADERS,
                          timeout=60, verify=False)
    d2 = r2.json()
    for t in d2.get("tables", []):
        f = t.get("fields", [])
        if f and "代號" in f and "收盤" in f:
            idx = [f.index(k) for k in
                   ("代號", "開盤", "最高", "最低", "收盤", "成交股數")]
            for row in t.get("data", []):
                o, h, l, c = (_pf(row[idx[1]]), _pf(row[idx[2]]),
                              _pf(row[idx[3]]), _pf(row[idx[4]]))
                v = _pf(row[idx[5]])
                if c is None or v is None or v <= 0:
                    continue
                quotes.setdefault(str(row[idx[0]]).strip(),
                                  (o or c, h or c, l or c, c, int(v)))
            break
    return quotes


def update_prices_official(conn, companies: pd.DataFrame, dates: list[str],
                           fetcher=None) -> dict:
    """用官方來源補指定日期的全市場行情。fetcher 可注入（測試用）。"""
    fetcher = fetcher or _official_quotes
    stats = {"dates_ok": [], "inserted_rows": 0, "errors": []}
    valid = set(companies["stock_id"])
    for date in dates:
        try:
            quotes = fetcher(date)
        except Exception as e:
            stats["errors"].append(f"{date}: {e}")
            continue
        rows = [(sid, date, o, h, l, c, v)
                for sid, (o, h, l, c, v) in quotes.items() if sid in valid]
        if not rows:
            stats["errors"].append(f"{date}: 官方來源無資料（可能為休市日）")
            continue
        conn.executemany(
            "INSERT OR IGNORE INTO stock_price_daily "
            "(stock_id, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
        stats["dates_ok"].append(date)
        stats["inserted_rows"] += len(rows)
    logger.info("官方來源更新：%s", stats)
    return stats


def dates_needing_update(conn, today: str, lookback_days: int = 10,
                         min_rows: int = 500) -> list[str]:
    """近 lookback_days 天內，資料筆數不足 min_rows 的平日清單。

    覆蓋兩種情況：整天缺資料、以及部分更新（如 yfinance 只塞進幾檔）。
    休市日官方來源會回無資料，補抓一次後仍為空屬正常。
    """
    end = datetime.datetime.strptime(today, "%Y-%m-%d")
    out = []
    for i in range(lookback_days, -1, -1):
        d = end - datetime.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y-%m-%d")
        n = conn.execute(
            "SELECT COUNT(*) FROM stock_price_daily WHERE date = ?",
            (ds,)).fetchone()[0]
        if n < min_rows:
            out.append(ds)
    return out


def update_prices(conn, companies: pd.DataFrame, downloader=None,
                  today: str | None = None) -> dict:
    """增量更新股價。回傳統計 dict。

    companies: get_companies() 的結果（可先篩選）。
    downloader: (tickers, start) -> DataFrame，預設用 yfinance；測試時注入假函式。
    today: 覆蓋今天日期（測試用），格式 YYYY-MM-DD。
    """
    stats = {"updated": 0, "inserted_rows": 0, "skipped": 0, "errors": []}
    if companies.empty:
        return stats

    downloader = downloader or _yfinance_downloader
    now = (datetime.datetime.strptime(today, "%Y-%m-%d")
           if today else datetime.datetime.today())
    today_str = now.strftime("%Y-%m-%d")
    new_stock_start = (now - datetime.timedelta(days=NEW_STOCK_YEARS * 365)
                       ).strftime("%Y-%m-%d")

    last_dates = dict(conn.execute(
        "SELECT stock_id, MAX(date) FROM stock_price_daily GROUP BY stock_id"
    ).fetchall())

    # 依起始下載日分組
    update_groups: dict[str, list[tuple[str, str]]] = {}
    for _, comp in companies.iterrows():
        sid = comp["stock_id"]
        ticker = yf_ticker(sid, comp["market"])
        last = last_dates.get(sid)

        if last is None:
            start = new_stock_start
            is_new = True
        else:
            if last >= today_str:
                stats["skipped"] += 1
                continue
            start = (datetime.datetime.strptime(last, "%Y-%m-%d")
                     + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            is_new = False

        if start > today_str:
            stats["skipped"] += 1
            continue
        # 假日防護：增量區間內全是週末就不用抓（全新股票直接放行）
        if not is_new and not _has_weekday_between(start, now):
            stats["skipped"] += 1
            continue

        update_groups.setdefault(start, []).append((ticker, sid))

    cursor = conn.cursor()
    for start, pairs in update_groups.items():
        for i in range(0, len(pairs), CHUNK_SIZE):
            chunk = pairs[i:i + CHUNK_SIZE]
            tickers = [t for t, _ in chunk]
            try:
                df_download = downloader(tickers, start)
            except Exception as e:
                stats["errors"].append(f"download {start} batch {i // CHUNK_SIZE}: {e}")
                continue
            if df_download is None or df_download.empty or len(df_download.columns) == 0:
                continue

            is_multi = isinstance(df_download.columns, pd.MultiIndex)
            for ticker, sid in chunk:
                try:
                    rows = _extract_rows(df_download, ticker, sid, is_multi)
                except Exception as e:
                    stats["errors"].append(f"{sid}: {e}")
                    continue
                if rows:
                    cursor.executemany(
                        "INSERT OR IGNORE INTO stock_price_daily "
                        "(stock_id, date, open, high, low, close, volume) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
                    stats["updated"] += 1
                    stats["inserted_rows"] += len(rows)
            conn.commit()

    logger.info("股價更新完成：%s", stats)
    return stats

# -*- coding: utf-8 -*-
"""資料庫存取層：公司清單、日K讀取、股價增量更新。"""
import pandas as pd


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

# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from core.data import (dates_needing_update, get_companies, get_stock_name,
                       load_prices, update_prices, update_prices_official,
                       yf_ticker)


def test_update_prices_official_inserts_only_known_stocks(db):
    fake = {"2330": (100.0, 101.0, 99.0, 100.5, 12345),
            "6488": (50.0, 51.0, 49.0, 50.5, 678),
            "1101": (30.0, 30.5, 29.5, 30.2, 999)}  # 不在 company_master → 略過
    stats = update_prices_official(
        db, get_companies(db), ["2026-07-10"], fetcher=lambda d: fake)
    assert stats["dates_ok"] == ["2026-07-10"]
    assert stats["inserted_rows"] == 2
    row = db.execute("SELECT close, volume FROM stock_price_daily "
                     "WHERE stock_id='2330' AND date='2026-07-10'").fetchone()
    assert row == (100.5, 12345)


def test_update_prices_official_records_empty_as_error(db):
    stats = update_prices_official(
        db, get_companies(db), ["2026-07-11"], fetcher=lambda d: {})
    assert stats["dates_ok"] == []
    assert "2026-07-11" in stats["errors"][0]


def test_dates_needing_update_flags_missing_and_partial(db):
    # conftest 只塞 2026-06 的 2330（每天 1 筆 < min_rows=2）
    need = dates_needing_update(db, "2026-06-10", lookback_days=4, min_rows=2)
    assert need == ["2026-06-08", "2026-06-09", "2026-06-10"]
    db.executemany("INSERT INTO stock_price_daily VALUES (?,?,?,?,?,?,?)",
                   [("6488", "2026-06-09", 1, 1, 1, 1, 1),
                    ("2317", "2026-06-09", 1, 1, 1, 1, 1)])
    need2 = dates_needing_update(db, "2026-06-10", lookback_days=4, min_rows=2)
    assert "2026-06-09" not in need2


def test_get_companies_filters(db):
    df = get_companies(db)
    assert set(df["stock_id"]) == {"2330", "6488"}  # 排除5碼與 is_active=0


def test_load_prices_shape_and_types(db):
    df = load_prices(db, "2330")
    assert len(df) == 30
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert str(df.index.dtype).startswith("datetime64")
    assert df["volume"].dtype == "int64"


def test_load_prices_range(db):
    df = load_prices(db, "2330", start="2026-06-10", end="2026-06-15")
    assert len(df) == 6


def test_load_prices_missing_stock_empty(db):
    df = load_prices(db, "0000")
    assert df.empty


def test_get_stock_name(db):
    assert get_stock_name(db, "2330") == "台積電"
    assert get_stock_name(db, "0000") == "未知股票"


def test_yf_ticker():
    assert yf_ticker("2330", "上市") == "2330.TW"
    assert yf_ticker("6488", "上櫃") == "6488.TWO"


def _fake_downloader_factory(days, holes=None):
    """回傳模擬 yf.download 的函式：MultiIndex 欄位 (ticker, OHLCV)。
    holes: {(ticker, date_str)} 集合，模擬該股當日停牌（欄位 NaN）。"""
    holes = holes or set()

    def dl(tickers, start):
        idx = pd.to_datetime(days)
        cols = pd.MultiIndex.from_product(
            [tickers, ["Open", "High", "Low", "Close", "Volume"]])
        df = pd.DataFrame(index=idx, columns=cols, dtype=float)
        for t in tickers:
            for i, d in enumerate(idx):
                if (t, d.strftime("%Y-%m-%d")) in holes:
                    continue  # 留 NaN
                df.loc[d, (t, "Open")] = 10 + i
                df.loc[d, (t, "High")] = 11 + i
                df.loc[d, (t, "Low")] = 9 + i
                df.loc[d, (t, "Close")] = 10.5 + i
                df.loc[d, (t, "Volume")] = 1000
        return df

    return dl


def test_update_inserts_all_days_not_just_last(db):
    """回歸測試：舊腳本縮排 bug 導致多日下載只存最後一天。"""
    days = ["2026-07-01", "2026-07-02", "2026-07-03"]
    companies = get_companies(db)
    stats = update_prices(db, companies,
                          downloader=_fake_downloader_factory(days),
                          today="2026-07-06")
    n = db.execute(
        "SELECT COUNT(*) FROM stock_price_daily WHERE stock_id='6488'"
    ).fetchone()[0]
    assert n == 3  # 舊 bug 下這裡會是 1
    assert stats["inserted_rows"] >= 3


def test_update_skips_when_current(db):
    db.execute("INSERT INTO stock_price_daily VALUES ('6488','2026-07-06',1,1,1,1,1)")
    db.commit()
    companies = get_companies(db)
    called = []

    def dl(tickers, start):
        called.append(tickers)
        return pd.DataFrame()

    update_prices(db, companies[companies.stock_id == "6488"],
                  downloader=dl, today="2026-07-06")
    assert called == []  # 已是最新，不應呼叫下載


def test_update_skips_nan_and_zero_volume_rows(db):
    """停牌日（NaN）不寫入；防止 ffill 交叉污染。"""
    days = ["2026-07-01", "2026-07-02"]
    companies = get_companies(db)
    update_prices(db, companies[companies.stock_id == "6488"],
                  downloader=_fake_downloader_factory(
                      days, holes={("6488.TWO", "2026-07-02")}),
                  today="2026-07-06")
    rows = db.execute(
        "SELECT date FROM stock_price_daily WHERE stock_id='6488' ORDER BY date"
    ).fetchall()
    assert [r[0] for r in rows] == ["2026-07-01"]


def test_update_incremental_start_after_last_date(db):
    """已有資料的股票只從最後日期次日抓起。"""
    companies = get_companies(db)
    starts = []

    def dl(tickers, start):
        starts.append((tuple(tickers), start))
        return pd.DataFrame()

    # 2330 在 fixture 已有資料到 2026-06-30
    update_prices(db, companies[companies.stock_id == "2330"],
                  downloader=dl, today="2026-07-06")
    assert starts and starts[0][1] == "2026-07-01"

# -*- coding: utf-8 -*-
from core.data import get_companies, get_stock_name, load_prices, yf_ticker


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

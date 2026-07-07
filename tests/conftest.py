# -*- coding: utf-8 -*-
import sqlite3

import pytest


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(tmp_path / "test.db")
    conn.executescript("""
    CREATE TABLE company_master (stock_id TEXT, stock_name TEXT, industry TEXT,
        market TEXT, is_active INTEGER);
    CREATE TABLE stock_price_daily (stock_id TEXT, date TEXT, open REAL, high REAL,
        low REAL, close REAL, volume INTEGER, PRIMARY KEY (stock_id, date));
    INSERT INTO company_master VALUES
      ('2330','台積電','半導體','上市',1),
      ('6488','環球晶','半導體','上櫃',1),
      ('12345','五碼股','其他','上市',1),
      ('9999','下市股','其他','上市',0);
    """)
    dates = ["2026-06-%02d" % d for d in range(1, 31)]
    rows = [("2330", dt, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 1000 + i)
            for i, dt in enumerate(dates)]
    conn.executemany("INSERT INTO stock_price_daily VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    yield conn
    conn.close()

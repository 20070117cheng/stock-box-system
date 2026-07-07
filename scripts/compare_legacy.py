# -*- coding: utf-8 -*-
"""對照驗證：新模組輸出 vs 舊腳本產出（真實資料，唯讀）。

1. 掃描名單：scan() vs kd_scan_report_20260706.xlsx 的代號集合與 K/D 值
2. 回測明細：run_backtest() vs 2026-07-06/ 資料夾的個股 Excel
"""
import os
import sqlite3
import sys

import openpyxl
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.backtest import run_backtest
from core.config import DEFAULTS
from core.data import load_prices
from core.scanner import scan

LEGACY_DIR = r"C:\03-Python\股票萬用箱型理論回測報告"
DB = os.path.join(LEGACY_DIR, "tw_stock_v2.db")
AS_OF = "2026-07-06"
REPORT = os.path.join(LEGACY_DIR, f"kd_scan_report_{AS_OF.replace('-', '')}.xlsx")
BT_DIR = os.path.join(LEGACY_DIR, AS_OF)

failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        failures.append(f"{name}: {detail}")


# ---------- 1. 掃描名單與 K/D ----------
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
old = pd.read_excel(REPORT, dtype={"代號": str})
new = scan(conn, dict(DEFAULTS), as_of=AS_OF)

old_ids = set(old["代號"])
new_ids = set(new["代號"])
check("掃描代號集合一致", old_ids == new_ids,
      f"僅舊有:{sorted(old_ids - new_ids)} 僅新有:{sorted(new_ids - old_ids)}")

merged = old.merge(new, on="代號", suffixes=("_old", "_new"))
kd_ok = True
for _, r in merged.iterrows():
    if abs(r["K值_old"] - r["K值_new"]) > 0.01 or abs(r["D值_old"] - r["D值_new"]) > 0.01:
        kd_ok = False
        print(f"   K/D 不符 {r['代號']}: 舊K={r['K值_old']} 新K={r['K值_new']} "
              f"舊D={r['D值_old']} 新D={r['D值_new']}")
check("K/D 值一致（容差0.01）", kd_ok, f"共比對 {len(merged)} 檔")

# ---------- 2. 回測明細（抽 5 檔） ----------
excels = sorted(f for f in os.listdir(BT_DIR) if f.endswith(".xlsx"))
sample = excels[:: max(1, len(excels) // 5)][:5]

for fname in sample:
    sid = fname.split("_")[0]
    wb = openpyxl.load_workbook(os.path.join(BT_DIR, fname), read_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(min_row=4, max_col=15, values_only=True):
        if row[0] is None:
            break
        rows.append(row)
    wb.close()
    old_bt = pd.DataFrame(rows, columns=[
        "日期", "日收盤價", "K值", "D值", "平均持股成本", "移動停利線", "固定停損線",
        "正宗箱頂", "正宗箱底", "持股張數", "預計進場價", "預計出場價",
        "訊號狀態", "進出場原因說明", "損益金額"])

    start = str(old_bt["日期"].iloc[0])[:10]
    extended = (pd.to_datetime(start) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    prices = load_prices(conn, sid, start=extended, end=AS_OF)
    res = run_backtest(prices, start, dict(DEFAULTS))
    new_bt = res.daily

    ok_len = len(old_bt) == len(new_bt)
    check(f"{sid} 天數一致", ok_len, f"舊{len(old_bt)} 新{len(new_bt)}")
    if not ok_len:
        continue

    status_ok = (old_bt["訊號狀態"].values == new_bt["訊號狀態"].values).all()
    shares_ok = (old_bt["持股張數"].astype(float).values
                 == new_bt["持股張數"].astype(float).values).all()
    amt_diff = (old_bt["損益金額"].astype(float).values
                - new_bt["損益金額"].round(0).values)
    amt_ok = (abs(amt_diff) <= 1).all()  # 舊檔已四捨五入到元
    kd_diff = (old_bt["K值"].astype(float).values - new_bt["k"].round(2).values)
    kdbt_ok = (abs(kd_diff) <= 0.011).all()
    check(f"{sid} 訊號狀態逐日一致", bool(status_ok))
    check(f"{sid} 持股張數逐日一致", bool(shares_ok))
    check(f"{sid} 損益金額一致（±1元）", bool(amt_ok),
          f"最大差 {abs(amt_diff).max():.2f}")
    check(f"{sid} K值一致（容差0.011）", bool(kdbt_ok),
          f"最大差 {abs(kd_diff).max():.4f}")

conn.close()

print()
if failures:
    print(f"共 {len(failures)} 項不一致：")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("全部對照通過 ✔")

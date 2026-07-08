# -*- coding: utf-8 -*-
"""彙整參數優化的全部單組合 JSON → results.parquet + summary.md。

用法：
    python -m jobs.optimize_aggregate --in opt_out --out outputs/optimize
"""
import argparse
import glob
import json
import os

import pandas as pd

HEADER = """# 停利停損參數優化結果

解讀原則：
1. 先看「後半年報酬」（參數沒看過的資料），再看全年
2. 選鄰近組合也不錯的高原區，不選孤立尖峰
3. 樣本只有一年、且偏多頭行情，結論不能外推到空頭

報酬皆為「已結算日子的 3 個月窗平均報酬 %」（含手續費與證交稅）。
"""


def aggregate(in_dir: str, out_dir: str,
              merge_existing: str | None = None) -> pd.DataFrame:
    rows = []
    for path in sorted(glob.glob(os.path.join(in_dir, "**", "*.json"),
                                 recursive=True)):
        with open(path, encoding="utf-8") as f:
            rows.append(json.load(f))
    if not rows:
        raise SystemExit(f"{in_dir} 內找不到結果 JSON")

    df = pd.DataFrame(rows)
    if merge_existing and os.path.exists(merge_existing):
        old = pd.read_parquet(merge_existing)
        # 新結果優先，補上這次沒重跑的舊組合
        df = pd.concat([df, old], ignore_index=True).drop_duplicates(
            subset=["stop_profit_pct", "fixed_loss_pct"], keep="first")
    df = df.sort_values("ret_mean", ascending=False)
    os.makedirs(out_dir, exist_ok=True)
    df.to_parquet(os.path.join(out_dir, "results.parquet"))

    matrix = df.pivot(index="stop_profit_pct", columns="fixed_loss_pct",
                      values="ret_mean").sort_index()
    matrix_2nd = df.pivot(index="stop_profit_pct", columns="fixed_loss_pct",
                          values="ret_second").sort_index()

    lines = [HEADER]
    lines.append(f"資料日期：{df['today'].iloc[0]}，共 {len(df)} 組。\n")
    lines.append("## 全年平均報酬 %（列=移動停利、欄=固定停損）\n")
    lines.append(matrix.to_markdown(floatfmt=".2f"))
    lines.append("\n## 後半年平均報酬 %（驗證段，同座標）\n")
    lines.append(matrix_2nd.to_markdown(floatfmt=".2f"))
    lines.append("\n## 各組合明細（依全年平均報酬排序）\n")
    show = df[["stop_profit_pct", "fixed_loss_pct", "ret_mean",
               "ret_first", "ret_second", "winrate_mean",
               "winrate_second", "ret_now_mean", "settled_days"]]
    show = show.rename(columns={
        "stop_profit_pct": "停利%", "fixed_loss_pct": "停損%",
        "ret_mean": "全年報酬%", "ret_first": "前半報酬%",
        "ret_second": "後半報酬%", "winrate_mean": "全年勝率%",
        "winrate_second": "後半勝率%", "ret_now_mean": "算到今天報酬%",
        "settled_days": "樣本天數"})
    lines.append(show.to_markdown(index=False, floatfmt=".2f"))
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return df


def main():
    p = argparse.ArgumentParser(description="彙整優化結果")
    p.add_argument("--in", dest="in_dir", required=True)
    p.add_argument("--out", dest="out_dir", required=True)
    p.add_argument("--merge-existing", default=None,
                   help="既有 results.parquet，這次沒跑到的組合沿用舊值")
    a = p.parse_args()
    df = aggregate(a.in_dir, a.out_dir, merge_existing=a.merge_existing)
    print(df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()

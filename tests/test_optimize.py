# -*- coding: utf-8 -*-
import json

import pandas as pd

from core.optimize import summarize_winrates
from jobs.optimize_aggregate import aggregate


def _wr(rows):
    return pd.DataFrame(rows, columns=[
        "選股日", "入選檔數", "發展中",
        "進場檔數_窗", "獲利檔數_窗", "勝率_窗", "平均報酬_窗",
        "進場檔數_今", "獲利檔數_今", "勝率_今", "平均報酬_今"])


def test_summarize_splits_halves_and_excludes_developing():
    wr = _wr([
        # 已結算 4 天：前半報酬 10、20，後半 30、40
        {"選股日": "2026-01-02", "發展中": False, "勝率_窗": 50.0,
         "平均報酬_窗": 10.0, "勝率_今": 50.0, "平均報酬_今": 1.0},
        {"選股日": "2026-01-03", "發展中": False, "勝率_窗": 60.0,
         "平均報酬_窗": 20.0, "勝率_今": 50.0, "平均報酬_今": 2.0},
        {"選股日": "2026-01-04", "發展中": False, "勝率_窗": 70.0,
         "平均報酬_窗": 30.0, "勝率_今": 50.0, "平均報酬_今": 3.0},
        {"選股日": "2026-01-05", "發展中": False, "勝率_窗": 80.0,
         "平均報酬_窗": 40.0, "勝率_今": 50.0, "平均報酬_今": 4.0},
        # 發展中與無進場的日子要排除在窗版統計外
        {"選股日": "2026-06-01", "發展中": True, "勝率_窗": None,
         "平均報酬_窗": None, "勝率_今": 90.0, "平均報酬_今": 9.0},
        {"選股日": "2026-01-06", "發展中": False, "勝率_窗": None,
         "平均報酬_窗": None, "勝率_今": None, "平均報酬_今": None},
    ])
    out = summarize_winrates(wr)
    assert out["settled_days"] == 4
    assert out["ret_mean"] == 25.0
    assert out["ret_first"] == 15.0
    assert out["ret_second"] == 35.0
    assert out["winrate_mean"] == 65.0
    # 算到今天版：5 天有值（含發展中的那天）
    assert out["ret_now_mean"] == 3.8


def test_summarize_empty():
    out = summarize_winrates(_wr([]))
    assert out["settled_days"] == 0
    assert out["ret_mean"] is None


def test_aggregate_builds_matrix_and_summary(tmp_path):
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    for sp, fl, ret in [(10, 3, 5.0), (10, 5, 3.0), (15, 3, 7.0), (15, 5, 1.0)]:
        (in_dir / f"sp{sp}_fl{fl}.json").write_text(json.dumps({
            "stop_profit_pct": sp, "fixed_loss_pct": fl, "today": "2026-07-07",
            "settled_days": 100, "ret_mean": ret, "winrate_mean": 50.0,
            "ret_first": ret - 1, "ret_second": ret + 1,
            "winrate_first": 45.0, "winrate_second": 55.0,
            "ret_now_mean": ret}), encoding="utf-8")
    out_dir = tmp_path / "out"
    df = aggregate(str(in_dir), str(out_dir))
    assert len(df) == 4
    assert df.iloc[0]["ret_mean"] == 7.0  # 依全年報酬排序
    assert (out_dir / "results.parquet").exists()
    md = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert "全年平均報酬" in md and "後半年平均報酬" in md

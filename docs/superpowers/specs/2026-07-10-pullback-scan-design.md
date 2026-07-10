# 回檔接手掃描模式（pullback）設計

日期：2026-07-10
狀態：已與使用者確認條件定義

## 目的

使用者想測試第二種進場型態：「創 3 年新高 → 小幅回檔（不破前高）→ KD 剛黃金
交叉」。與現行「貼近高點＋KD 金叉/將金叉」模式做過去一年的 A/B 勝率對比，
用同一把尺（勝率歷史流程）評估孰優孰劣。

## 條件定義（使用者確認）

對每檔股票、以掃描日（含）之前 3 年資料判斷：

1. **剛創 3 年新高**：3 年最高收盤價發生在近 `pullback_recency_days`
   （預設 20）個交易日內
2. **小跌**：現價 < 3 年高，且回檔幅度 ≤ `pullback_max_pct`（預設 7）%
3. **沒跌破前高**：自高點日以來的最低收盤價 > 當前箱體箱底
   （箱型規則中，突破後新箱＝[舊箱頂, 新高]，箱底即突破前的上一個高峰）
4. **KD 剛黃金交叉**：昨 K < D、今 K ≥ D（不含「準備交叉」，使用者要的是
   「剛好金叉」）

## 實作

- `core/config.py`：新增 `scan_mode: "near_high"`（現行）、
  `pullback_max_pct: 7.0`、`pullback_recency_days: 20`
- `core/scanner.py`：`scan()` 依 `cfg["scan_mode"]` 分派；新增 pullback 判斷，
  箱底計算重用 `core/backtest._weekly_boxes`
- `core/history.py`：`scan_params()` 納入 scan_mode 與 pullback 參數
  （模式不同＝名單快取不同）
- 每日排程與現行網頁不受影響（config.json 未設 scan_mode 時走 near_high）

## A/B 驗證

- 新 workflow `backfill-mode.yml`（workflow_dispatch，input=mode）：
  對指定模式跑 `history.refresh` 到 `outputs/history_<mode>/`，commit 回 repo
- 回測參數用現行預設（停利 10／停損 3），兩邊同一組才公平
- 比較指標：已結算日的平均勝率、平均報酬（3 個月窗）、每日入選檔數
  （pullback 條件嚴，預期名單少很多、部分日子掛零）

## 測試

- pytest：合成資料驗證四條件——全符合入選；破箱底不選；高點太久不選；
  未回檔（現價=高點）不選；KD 未金叉不選
- 本機真實 DB 抽 1 天掃描 sanity check 後才推上雲端

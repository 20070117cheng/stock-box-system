# 停利停損參數優化設計

日期：2026-07-08
狀態：已與使用者確認

## 目的

在過去一年的勝率歷史上網格搜尋停利 × 停損組合，找出獲利較高的參數。
使用者已知悉過度擬合風險，方法上以「前後半年分段驗證＋看高原不看尖峰」防範。

## 使用者已確認的決策

1. 只優化停利 × 停損（門檻與 KD 不動，歷史名單快取直接沿用）
2. 在 GitHub Actions 用 matrix 平行跑（公開 repo 免費），不佔本機
3. 產出全部組合的結果供比較，不是只回傳單一「最佳」組合

## 網格

- 移動停利 %：6, 8, 10, 12, 15, 20
- 固定停損 %：2, 3, 4, 5, 7
- 共 30 組，每組一個 matrix job

## 評估指標（每組合）

用 `compute_winrates`（沿用 outputs/history/scans.parquet 名單）算整年每日
勝率表，然後彙整：

- `ret_mean`／`winrate_mean`：已結算（3 個月窗）日子的平均報酬與平均勝率
- `ret_first`／`ret_second`：已結算日子按日期切前後兩半的平均報酬
  （前半找參數、後半驗證；兩半都好才可信）
- `winrate_first`／`winrate_second`：同上的勝率
- `ret_now_mean`：算到今天版的平均報酬（參考用）
- `settled_days`：樣本天數

「今天」統一取 DB 最新日期，避免各 job 執行時間差造成不一致。

## 檔案

- `core/optimize.py`：`summarize_winrates(wr)` 純函式（指標彙整，可測試）
- `jobs/optimize.py`：單組合 CLI
  `--db --scans --stop-profit --fixed-loss --out`，寫 JSON
- `jobs/optimize_aggregate.py`：彙整資料夾內全部 JSON →
  `outputs/optimize/results.parquet` + `summary.md`（依全年平均報酬排序 +
  停利×停損的報酬矩陣，方便看高原）
- `.github/workflows/optimize.yml`：workflow_dispatch 觸發；
  matrix 30 job 各算一組 → aggregate job 收 artifacts、彙整、commit 回 repo

## 結果解讀原則（寫進 summary.md 開頭）

- 先看後半年（out-of-sample）表現，再看全年
- 選「鄰近組合也不錯」的參數區域，不選孤立尖峰
- 樣本只有一年多頭行情，結論不能外推到空頭

## 測試

- pytest：summarize_winrates 用小型假資料驗證切半、排除發展中、NaN 處理
- 本機用 15 天子集跑單組合 CLI 驗證輸出格式，再推上雲端

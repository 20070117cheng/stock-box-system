# 箱型選股回測系統

台股「選股 → 回測」全自動雲端系統。每個交易日 15:30（台北時間）自動：

1. 從 Yahoo 增量更新股價到 SQLite 資料庫
2. 掃描「接近 3 年收盤高點 95% 以上 + KD(9,3,3) 剛金叉／將金叉」的股票
3. 對入選名單跑達瓦斯箱型策略回測（移動停利 10%、固定停損 3%）
4. 結果發佈到網頁，手機、電腦開同一個網址就能看

## 架構

```
GitHub Actions（每日排程）─→ 更新 DB（存 GitHub Release）
                          └→ 掃描+回測結果（存 outputs/，commit 回 repo）
Streamlit Community Cloud ─→ 讀取上述結果呈現網頁，可互動改參數重算
```

## 專案結構

| 路徑 | 職責 |
|------|------|
| `core/config.py` | 所有可調參數（停利%、停損%、門檻%…）集中在這 |
| `core/data.py` | 資料庫存取、yfinance 增量更新 |
| `core/indicators.py` | KD 指標計算 |
| `core/scanner.py` | 選股條件（要改選股規則看這裡） |
| `core/backtest.py` | 箱型策略狀態機（要改進出場規則看這裡） |
| `core/report.py` | Excel 報告產生 |
| `jobs/daily.py` | 每日排程入口 |
| `app/main.py` | Streamlit 網頁（每日選股／個股分析／時光機三分頁） |
| `outputs/日期/` | 每日掃描名單與回測結果（自動產生） |

## 本機開發

```bash
pip install -r requirements.txt
python -m pytest                     # 跑測試（29 個）
streamlit run app/main.py -- --local-db "C:\path\to\tw_stock_v2.db"
```

手動跑一次每日流程：

```bash
python -m jobs.daily --db tw_stock_v2.db --output-dir outputs --skip-update
```

## 部署步驟（一次性）

1. `gh auth login` 登入 GitHub
2. `gh repo create stock-box-system --public --source . --push`
3. 上傳初始資料庫：`gh release create data tw_stock_v2.db --title "資料庫" --notes "每日由 Actions 自動更新"`
4. 手動觸發一次確認可跑：`gh workflow run daily-scan-backtest`
5. 到 [share.streamlit.io](https://share.streamlit.io) 用 GitHub 登入 → New app → 選這個 repo、主檔填 `app/main.py` → Advanced settings 的 Secrets 填：
   ```toml
   REPO = "你的帳號/stock-box-system"
   ```
   （選填 `GITHUB_TOKEN`：填了之後網頁上的「存為預設」會把參數寫回 repo）
6. Deploy 完成後的網址即可分享給任何人

## 時光機（策略驗證）

「每日選股」的名單用今天的資料選出，回頭看的回測損益有事後選擇偏誤，天生偏正。
「時光機」分頁站在過去任一天，用當時的資料選股，再往後模擬到指定截止日——
選股當下不知道未來，這個績效才能公平檢驗策略：

1. 選「選股日期」與「觀察截止日」（預設今天），策略參數在分頁內獨立調整
2. 按「執行掃描」：全市場現算當天名單（第一次約 1～3 分鐘，同條件會快取）
3. 績效總表：每檔從選股日按策略模擬（進出場由策略觸發），附勝率、平均報酬等統計
4. 單檔詳細：走勢圖上垂直虛線標選股日，左邊是入選前、右邊是入選後的實際發展

### 過去一年每日勝率

時光機分頁頂部的圖表，由每日排程自動計算（`outputs/history/`）：

- 每個交易日用當時資料選股，名單算過一次就快取（過去的掃描結果永不改變）
- 每檔從選股日按策略模擬，「3 個月窗」版在選股日後 3 個月結算——日與日可比，
  是主要指標；「算到今天」版當目前戰況看
- 勝率只統計有進場的股票；年平均勝率排除還沒走完 3 個月的「發展中」日子
- 想試不同停利停損：展開「用其他停利停損重算」，沿用快取名單重跑回測（等幾分鐘）
- 改「距3年高點門檻」或 KD 參數要動 config.json 預設值，隔日排程會自動重建整份歷史

## 改參數／改規則

- **日常調參**：網頁側欄直接調，按「重新回測」立即生效；按「存為預設」讓每日排程也改用新參數
- **改選股條件**：編輯 `core/scanner.py` 的 `scan()`
- **改進出場規則**：編輯 `core/backtest.py` 的 `run_backtest()`
- 改完跑 `python -m pytest` 確認測試通過再 push，push 後雲端自動生效

## 常見問題

- **網頁打開要等 30～60 秒**：免費版閒置會休眠，喚醒中，不是壞掉
- **今天沒有新資料**：Yahoo 偶爾抓不到，隔天排程會自動補；網頁上方顯示目前的資料日期
- **排程沒跑**：GitHub → repo → Actions 分頁看 log；公開 repo 60 天無 commit 會自動停用排程，重新啟用即可
